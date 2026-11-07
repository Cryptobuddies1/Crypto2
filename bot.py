"""Crypto Buddies – Telegram-Bot + Mini-App-Server + Auszahlungen in einem Prozess.

Start:  python bot.py        (Einstellungen in .env, siehe .env.example)
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

import aiohttp
import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
                           MenuButtonWebApp, Message, PreCheckoutQuery, WebAppInfo)
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

import events
import game
from i18n import LANGS, tr

load_dotenv()
env = os.environ.get
BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_USERNAME = env("BOT_USERNAME", "")
WEBAPP_URL = env("WEBAPP_URL", "")
PORT = int(env("PORT", "8000"))
DB_PATH = env("DB_PATH", "kumpels.db")
ADMIN_IDS = {int(x) for x in env("ADMIN_ID", "0").replace(" ", "").split(",") if x.isdigit() and int(x)}
ADMIN_ID = min(ADMIN_IDS) if ADMIN_IDS else 0           # Haupt-Admin für Warnungen (mehrere IDs mit Komma möglich)

# Werbung
ADSGRAM_BLOCK_ID = env("ADSGRAM_BLOCK_ID", "")             # Reward-Block (nur Ziffern, z. B. 12345)
ADSGRAM_INTERSTITIAL_ID = env("ADSGRAM_INTERSTITIAL_ID", "")   # optional: Vollbild-Werbung nach jedem 3. Pack ("int-12345")
MONETAG_ZONE_ID = env("MONETAG_ZONE_ID", "")               # optional: Monetag als zweiter Anbieter
DEV_MODE = env("DEV_MODE", "false").lower() == "true"      # nur zum Testen: Diamanten ohne Werbeanbieter
ADS_VERIFY = env("ADS_VERIFY", "false").lower() == "true"     # true = nur per AdsGram Reward-URL bestätigte Werbung zählt
ADSGRAM_SECRET = env("ADSGRAM_SECRET", "")

# Auszahlung je 4-Stunden-Runde: Figuren-Erträge werden voll in USDT gutgeschrieben
ECPM_USD = float(env("ECPM_USD", "1.5"))           # nur für den Alarm: geschätzte Einnahmen pro 1.000 Werbungen
MAX_PAYOUT_PER_ROUND = float(env("MAX_PAYOUT_PER_ROUND", "0"))   # Notbremse in $ (0 = keine Grenze)
MIN_ADS_24H = int(env("MIN_ADS_24H", "1"))          # wer in 24 h keine Werbung sah, bekommt den Rundenertrag nicht
MIN_PAYOUT = float(env("MIN_PAYOUT", "1.0"))        # USDT, darunter wird angespart

# CryptoBot
PAYOUT_MODE = env("PAYOUT_MODE", "off")             # off = nur gutschreiben, test = Testnetz, live = echtes Geld
CRYPTOPAY_TOKEN = env("CRYPTOPAY_TOKEN", "")
PAYOUT_ASSET = env("PAYOUT_ASSET", "TRX")            # Auszahlung in TRX (Beträge im Spiel bleiben in $)
TOPUP_ASSETS = env("TOPUP_ASSETS", "USDT,TRX")       # womit Spieler Aufladungen in $ bezahlen können

# Diamanten-Shop (Telegram Stars) – erst nach rechtlicher Prüfung einschalten!
SHOP_ENABLED = env("SHOP_ENABLED", "false").lower() == "true"

BASE = Path(__file__).parent
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kumpels")


def is_owner(user_id: int) -> bool:
    """Besitzer = IDs aus ADMIN_ID in den Einstellungen. Nur sie dürfen Admins verwalten."""
    return user_id in ADMIN_IDS


def is_admin(user_id: int, con=None) -> bool:
    if user_id in ADMIN_IDS:
        return True
    def check(c):
        return bool(c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone())
    if con is not None:
        return check(con)
    with db() as c:
        return check(c)


def E(status: int, key: str, **kw) -> HTTPException:
    """Fehler mit Textschlüssel – wird in der Sprache des Spielers ausgegeben."""
    return HTTPException(status, {"key": key, "kw": kw})


# ================================================================ Datenbank
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, name TEXT,
            diamonds INTEGER NOT NULL DEFAULT 0,
            points_total REAL NOT NULL DEFAULT 0,
            usdt REAL NOT NULL DEFAULT 0,
            usdt_paid REAL NOT NULL DEFAULT 0,
            last_daily TEXT, streak INTEGER NOT NULL DEFAULT 0,
            ref_by INTEGER, starter_used INTEGER NOT NULL DEFAULT 0, collection_bonus INTEGER NOT NULL DEFAULT 0,
            last_ad REAL NOT NULL DEFAULT 0, ads_day TEXT, ads_today INTEGER NOT NULL DEFAULT 0,
            created REAL);
        CREATE TABLE IF NOT EXISTS kumpels (
            user_id INTEGER, char_id TEXT, level INTEGER NOT NULL DEFAULT 1,
            copies INTEGER NOT NULL DEFAULT 1, last_collect REAL NOT NULL,
            PRIMARY KEY (user_id, char_id));
        CREATE TABLE IF NOT EXISTS round_points (
            user_id INTEGER, period INTEGER, points REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, period));
        CREATE TABLE IF NOT EXISTS ad_views (
            id INTEGER PRIMARY KEY, user_id INTEGER, ts REAL, period INTEGER,
            source TEXT, used INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS ad_user ON ad_views(user_id, ts);
        CREATE TABLE IF NOT EXISTS pulls (
            id INTEGER PRIMARY KEY, user_id INTEGER, pack TEXT, char_id TEXT, duplicate INTEGER, ts REAL);
        CREATE TABLE IF NOT EXISTS rounds (
            period INTEGER PRIMARY KEY, views INTEGER, revenue REAL, pool REAL,
            points REAL, players INTEGER, closed_at REAL);
        CREATE TABLE IF NOT EXISTS round_shares (
            user_id INTEGER, period INTEGER, points REAL, usdt REAL, PRIMARY KEY (user_id, period));
        CREATE TABLE IF NOT EXISTS payouts (
            id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, spend_id TEXT UNIQUE,
            status TEXT, error TEXT, created REAL, done REAL);
        CREATE TABLE IF NOT EXISTS jackpots (
            char_id TEXT PRIMARY KEY, every INTEGER, next_pos INTEGER, hits INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER);
        INSERT OR IGNORE INTO meta VALUES ('packs_opened', 0);
        CREATE TABLE IF NOT EXISTS topups (
            invoice_id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT, url TEXT, created REAL, paid REAL);
        CREATE TABLE IF NOT EXISTS diamond_buys (
            id INTEGER PRIMARY KEY, user_id INTEGER, diamonds INTEGER, from_deposit REAL, from_balance REAL, ts REAL);
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY, user_id INTEGER, stars INTEGER, diamonds INTEGER,
            charge_id TEXT UNIQUE, ts REAL);
        """)
        events.init(con)
        con.executescript("""
        CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT, added_by INTEGER, created REAL);
        CREATE TABLE IF NOT EXISTS admin_log (id INTEGER PRIMARY KEY, admin_id INTEGER, action TEXT, target INTEGER, details TEXT, ts REAL);
        """)
        cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
        for col, decl in [("collection_bonus", "INTEGER NOT NULL DEFAULT 0"), ("deposit", "REAL NOT NULL DEFAULT 0"),
                          ("autopayout", "INTEGER NOT NULL DEFAULT 1"), ("ref_earned", "REAL NOT NULL DEFAULT 0"),
                          ("lang", "TEXT NOT NULL DEFAULT 'en'"),
                          ("last_seen", "REAL NOT NULL DEFAULT 0"), ("blocked", "INTEGER NOT NULL DEFAULT 0"),
                          ("username", "TEXT")]:
            if col not in cols:   # Spalten für ältere Datenbanken nachrüsten
                con.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        pcols = [r[1] for r in con.execute("PRAGMA table_info(payouts)")]
        for col, decl in [("asset", "TEXT"), ("asset_amount", "REAL"), ("rate", "REAL")]:
            if col not in pcols:
                con.execute(f"ALTER TABLE payouts ADD COLUMN {col} {decl}")
        for j in game.JACKPOTS:   # Startpositionen einmalig festlegen (geheim)
            con.execute("INSERT OR IGNORE INTO jackpots (char_id, every, next_pos) VALUES (?,?,?)",
                        (j["char"], j["every"], game.first_jackpot_pos(j["every"])))


def jackpot_check(con) -> str | None:
    """Zählt ein geöffnetes Pack und gibt die Jackpot-Figur zurück, falls dieses Pack ein Treffer ist."""
    con.execute("UPDATE meta SET value=value+1 WHERE key='packs_opened'")
    n = con.execute("SELECT value FROM meta WHERE key='packs_opened'").fetchone()[0]
    hits = con.execute("SELECT * FROM jackpots WHERE next_pos<=?", (n,)).fetchall()
    if not hits:
        return None
    best = max(hits, key=lambda h: game.JACKPOT_USD.get(h["char_id"], 0))
    for h in hits:
        if h["char_id"] == best["char_id"]:
            con.execute("UPDATE jackpots SET hits=hits+1, next_pos=? WHERE char_id=?",
                        (game.next_jackpot_pos(h["next_pos"], h["every"]), h["char_id"]))
        else:   # zwei Treffer gleichzeitig: der kleinere rutscht ins nächste Pack
            con.execute("UPDATE jackpots SET next_pos=? WHERE char_id=?", (n + 1, h["char_id"]))
    return best["char_id"]


def ensure_user(con, user_id: int, name: str, ref_by: int | None = None) -> dict:
    """Legt einen Spieler an. Gibt {"new": bool, "referrer": id|None} zurück."""
    if con.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        con.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))
        return {"new": False, "referrer": None}
    valid_ref = bool(ref_by and ref_by != user_id and con.execute("SELECT 1 FROM users WHERE id=?", (ref_by,)).fetchone())
    con.execute("INSERT INTO users (id, name, created, ref_by) VALUES (?,?,?,?)",
                (user_id, name, game.now(), ref_by if valid_ref else None))
    if valid_ref:
        con.execute("UPDATE users SET diamonds=diamonds+? WHERE id IN (?,?)", (game.REFERRAL_DIAMONDS, user_id, ref_by))
        events.add(con, ref_by, "invites", 1)
    return {"new": True, "referrer": ref_by if valid_ref else None}


def parse_ref(arg: str | None) -> int | None:
    """'ref_123456' → 123456"""
    if arg and arg.startswith("ref_") and arg[4:].isdigit():
        return int(arg[4:])
    return None


def ref_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}" if BOT_USERNAME else ""


def user_lang(user_id: int) -> str:
    with db() as con:
        r = con.execute("SELECT lang FROM users WHERE id=?", (user_id,)).fetchone()
    return r[0] if r else "en"


async def notify_referrer(referrer: int, name: str):
    try:
        await bot.send_message(referrer, tr(user_lang(referrer), "friend_joined", name=name,
                                            n=game.REFERRAL_DIAMONDS, p=round(game.REFERRAL_SHARE * 100)))
    except Exception:
        pass


def settle(con, user_id: int, t: float | None = None) -> None:
    """Schreibt den Profit aller Figuren bis jetzt gut – aufgeteilt auf die 4-Stunden-Runden."""
    t = t or game.now()
    per_round: dict[int, float] = {}
    for k in con.execute("SELECT * FROM kumpels WHERE user_id=?", (user_id,)).fetchall():
        if k["last_collect"] >= t:
            continue
        per_sec = game.daily_profit(k["char_id"], k["level"]) / 86400
        for p, secs in game.split_by_period(k["last_collect"], t):
            per_round[p] = per_round.get(p, 0) + per_sec * secs
        con.execute("UPDATE kumpels SET last_collect=? WHERE user_id=? AND char_id=?", (t, user_id, k["char_id"]))
    total = 0.0
    for p, pts in per_round.items():
        total += pts
        con.execute("""INSERT INTO round_points (user_id, period, points) VALUES (?,?,?)
                       ON CONFLICT(user_id, period) DO UPDATE SET points=points+excluded.points""", (user_id, p, pts))
    if total:
        con.execute("UPDATE users SET points_total=points_total+? WHERE id=?", (total, user_id))
        events.add(con, user_id, "profit", total, t)


def ads_last_24h(con, user_id: int, t: float) -> int:
    return con.execute("SELECT COUNT(*) FROM ad_views WHERE user_id=? AND ts>? AND (used=1 OR source='s2s')",
                       (user_id, t - 86400)).fetchone()[0]


def state(con, user_id: int) -> dict:
    t = game.now()
    u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    ads_today = u["ads_today"] if u["ads_day"] == today else 0
    kumpels = []
    for k in con.execute("SELECT * FROM kumpels WHERE user_id=?", (user_id,)):
        lvl = k["level"]
        kumpels.append({
            "id": k["char_id"], "level": lvl, "copies": k["copies"],
            "daily": game.daily_profit(k["char_id"], lvl),
            "next_daily": game.daily_profit(k["char_id"], lvl + 1) if lvl < game.MAX_LEVEL else None,
            "level_cost": game.level_cost(k["char_id"], lvl) if lvl < game.MAX_LEVEL else None,
        })
    p = game.period_of(t)
    rp = con.execute("SELECT points FROM round_points WHERE user_id=? AND period=?", (user_id, p)).fetchone()
    last = con.execute("""SELECT r.period, r.pool AS paid, r.points, s.usdt FROM rounds r
                          LEFT JOIN round_shares s ON s.period=r.period AND s.user_id=?
                          ORDER BY r.period DESC LIMIT 1""", (user_id,)).fetchone()
    payouts = [dict(r) for r in con.execute(
        "SELECT amount, status, created, asset, asset_amount FROM payouts WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,))]
    top = [dict(name=r["name"] or "Spieler", score=round(r["points_total"], 4))
           for r in con.execute("SELECT name, points_total FROM users ORDER BY points_total DESC LIMIT 10")]
    return {
        "server_time": t, "user_id": user_id, "bot_username": BOT_USERNAME, "ref_link": ref_link(user_id), "lang": u["lang"],
        "diamonds": u["diamonds"], "usdt": round(u["usdt"], 6), "usdt_paid": round(u["usdt_paid"], 2),
        "points_total": u["points_total"],
        "round_points": rp["points"] if rp else 0, "round_end": game.period_end(p),
        "eligible": ads_last_24h(con, user_id, t) >= MIN_ADS_24H,
        "last_round": dict(last) if last else None,
        "streak": u["streak"] if u["last_daily"] in (today, yesterday) else 0,
        "daily_available": u["last_daily"] != today,
        "ads_today": ads_today, "next_ad_at": u["last_ad"] + game.AD_COOLDOWN,
        "next_ad_reward": game.ad_reward(ads_today),
        "starter_available": not u["starter_used"],
        "friends": con.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,)).fetchone()[0],
        "ref_earned": round(u["ref_earned"], 6), "ref_share": game.REFERRAL_SHARE, "ref_diamonds": game.REFERRAL_DIAMONDS,
        "kumpels": kumpels, "payouts": payouts, "top": top,
        "min_payout": MIN_PAYOUT, "payout_asset": PAYOUT_ASSET, "payout_mode": PAYOUT_MODE, "min_ads_24h": MIN_ADS_24H,
        "jackpots": [{"char": j["char"], "usd": j["usd"]} for j in game.JACKPOTS],   # ohne Chancen
        "collected": collected(con, user_id), "collection_total": len(game.REGULAR_IDS),
        "collection_bonus": game.COLLECTION_BONUS_USDT, "collection_bonus_paid": bool(u["collection_bonus"]),
        "dup_refund": {k: game.refund(k) for k in game.PACKS},
        "shop_enabled": SHOP_ENABLED, "deposit": round(u["deposit"], 6), "autopayout": bool(u["autopayout"]),
        "diamonds_per_usdt": game.DIAMONDS_PER_USDT, "topup_amounts": game.TOPUP_AMOUNTS,
        "topups_open": [dict(r) for r in con.execute(
            "SELECT invoice_id, amount, url FROM topups WHERE user_id=? AND status='active' AND created>? ORDER BY created DESC",
            (user_id, game.now() - 3600))], "adsgram_block_id": ADSGRAM_BLOCK_ID,
        "adsgram_int_id": ADSGRAM_INTERSTITIAL_ID, "monetag_zone": MONETAG_ZONE_ID,
        "star_packages": {k: {"diamonds": d, "stars": s} for k, (d, s) in game.STAR_PACKAGES.items()},
        "is_admin": is_admin(user_id, con),
        **events.player_view(con, user_id, u["lang"]),
    }


# ================================================================ Telegram-Prüfung
def verify_init_data(init_data: str) -> dict:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise E(401, "no_signature")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        raise E(401, "bad_signature")
    if game.now() - int(pairs.get("auth_date", 0)) > 24 * 3600:
        raise E(401, "session_expired")
    return json.loads(pairs["user"]), pairs.get("start_param")


# ================================================================ Spiel-Aktionen
def act_pack(con, user_id, u, pack):
    if pack not in game.PACKS:
        raise E(400, "unknown_pack")
    if pack == "start":
        if u["starter_used"]:
            raise E(400, "starter_used")
        con.execute("UPDATE users SET starter_used=1 WHERE id=?", (user_id,))
    else:
        price = game.PACKS[pack]["price"]
        if u["diamonds"] < price:
            raise E(400, "no_diamonds")
        con.execute("UPDATE users SET diamonds=diamonds-? WHERE id=?", (price, user_id))
    jackpot = jackpot_check(con) if pack != "start" else None
    char = jackpot or game.pull(pack)
    if jackpot:
        log.info("JACKPOT %s an Spieler %s", jackpot, user_id)
    k = con.execute("SELECT * FROM kumpels WHERE user_id=? AND char_id=?", (user_id, char)).fetchone()
    back = 0
    if k:   # Doppelt: 40 % der Pack-Kosten zurück
        back = game.refund(pack)
        con.execute("UPDATE kumpels SET copies=copies+1 WHERE user_id=? AND char_id=?", (user_id, char))
        con.execute("UPDATE users SET diamonds=diamonds+? WHERE id=?", (back, user_id))
    else:
        con.execute("INSERT INTO kumpels (user_id, char_id, last_collect) VALUES (?,?,?)", (user_id, char, game.now()))
    con.execute("INSERT INTO pulls (user_id, pack, char_id, duplicate, ts) VALUES (?,?,?,?,?)",
                (user_id, pack, char, int(bool(k)), game.now()))
    if pack != "start":
        events.add(con, user_id, "packs", 1)
    bonus = False
    if not k and not jackpot and not u["collection_bonus"] and collected(con, user_id) >= len(game.REGULAR_IDS):
        con.execute("UPDATE users SET collection_bonus=1, usdt=usdt+? WHERE id=?", (game.COLLECTION_BONUS_USDT, user_id))
        bonus = True
        log.info("SAMMEL-BONUS an Spieler %s", user_id)
    return {"char": char, "duplicate": bool(k), "refund": back, "jackpot": bool(jackpot),
            "collection_bonus": bonus}


def collected(con, user_id: int) -> int:
    """Anzahl verschiedener normaler Figuren (ohne Jackpots)."""
    marks = ",".join("?" * len(game.JACKPOT_USD))
    return con.execute(f"SELECT COUNT(*) FROM kumpels WHERE user_id=? AND char_id NOT IN ({marks})",
                       (user_id, *game.JACKPOT_USD)).fetchone()[0]


def act_levelup(con, user_id, u, char, steps):
    k = con.execute("SELECT * FROM kumpels WHERE user_id=? AND char_id=?", (user_id, char)).fetchone()
    if not k:
        raise E(400, "no_figure")
    level, diamonds, spent, done = k["level"], u["diamonds"], 0, 0
    steps = max(1, min(int(steps or 1), game.MAX_LEVEL))
    while done < steps and level < game.MAX_LEVEL:
        cost = game.level_cost(char, level)
        if diamonds - spent < cost:
            break
        spent += cost; level += 1; done += 1
    if not done:
        raise E(400, "max_level" if level >= game.MAX_LEVEL else "no_diamonds")
    con.execute("UPDATE users SET diamonds=diamonds-? WHERE id=?", (spent, user_id))
    con.execute("UPDATE kumpels SET level=? WHERE user_id=? AND char_id=?", (level, user_id, char))
    return {"levels": done, "spent": spent}


def act_ad(con, user_id, u):
    t = game.now()
    if not (ADSGRAM_BLOCK_ID or MONETAG_ZONE_ID or DEV_MODE):   # ohne Werbeanbieter keine Diamanten
        raise E(400, "ads_off")
    if t < u["last_ad"] + game.AD_COOLDOWN:
        raise E(400, "ad_wait", s=int(u['last_ad'] + game.AD_COOLDOWN - t) + 1)
    if ADS_VERIFY:   # nur von AdsGram bestätigte Ansichten der letzten 2 Minuten zählen
        row = con.execute("SELECT id FROM ad_views WHERE user_id=? AND source='s2s' AND used=0 AND ts>? ORDER BY ts LIMIT 1",
                          (user_id, t - 120)).fetchone()
        if not row:
            raise E(400, "ad_unconfirmed")
        con.execute("UPDATE ad_views SET used=1 WHERE id=?", (row["id"],))
    else:
        con.execute("INSERT INTO ad_views (user_id, ts, period, source, used) VALUES (?,?,?,?,1)",
                    (user_id, t, game.period_of(t), "client"))
    today = date.today().isoformat()
    ads_today = u["ads_today"] if u["ads_day"] == today else 0
    reward = game.ad_reward(ads_today)
    con.execute("UPDATE users SET diamonds=diamonds+?, last_ad=?, ads_day=?, ads_today=? WHERE id=?",
                (reward, t, today, ads_today + 1, user_id))
    events.add(con, user_id, "ads", 1, t)
    return {"diamonds": reward}


def act_daily(con, user_id, u):
    today = date.today()
    if u["last_daily"] == today.isoformat():
        raise E(400, "daily_done")
    streak = u["streak"] + 1 if u["last_daily"] == (today - timedelta(days=1)).isoformat() else 1
    reward = game.DAILY_STEP * min(streak, 7)
    con.execute("UPDATE users SET diamonds=diamonds+?, streak=?, last_daily=? WHERE id=?",
                (reward, streak, today.isoformat(), user_id))
    return {"diamonds": reward}


def act_buy_diamonds(con, user_id, u, diamonds):
    """Diamanten mit Einzahlung (zuerst) und Guthaben kaufen."""
    if not SHOP_ENABLED:
        raise E(400, "shop_off")
    diamonds = int(diamonds or 0)
    if diamonds < game.DIAMONDS_PER_USDT or diamonds % game.DIAMONDS_PER_USDT:
        raise E(400, "diamond_steps", n=game.DIAMONDS_PER_USDT)
    cost = diamonds / game.DIAMONDS_PER_USDT
    if u["deposit"] + u["usdt"] + 1e-9 < cost:
        raise E(400, "no_balance")
    from_dep = min(u["deposit"], cost)
    from_bal = round(cost - from_dep, 6)
    con.execute("UPDATE users SET deposit=deposit-?, usdt=usdt-?, diamonds=diamonds+? WHERE id=?",
                (from_dep, from_bal, diamonds, user_id))
    con.execute("INSERT INTO diamond_buys (user_id, diamonds, from_deposit, from_balance, ts) VALUES (?,?,?,?,?)",
                (user_id, diamonds, from_dep, from_bal, game.now()))
    return {"diamonds": diamonds, "cost": cost}


def credit_topup(con, invoice_id: int, amount: float) -> int | None:
    """Schreibt eine bezahlte Aufladung genau einmal gut. Gibt die user_id zurück."""
    row = con.execute("SELECT * FROM topups WHERE invoice_id=?", (invoice_id,)).fetchone()
    if not row or row["status"] == "paid":
        return None
    con.execute("UPDATE topups SET status='paid', paid=? WHERE invoice_id=?", (game.now(), invoice_id))
    con.execute("UPDATE users SET deposit=deposit+? WHERE id=?", (row["amount"], row["user_id"]))
    return row["user_id"]


async def act_topup(user_id: int, amount) -> dict:
    if not SHOP_ENABLED or not CRYPTOPAY_TOKEN:
        raise E(400, "topup_off")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise E(400, "bad_amount")
    if amount not in game.TOPUP_AMOUNTS:
        raise E(400, "bad_amount")
    res = await cryptopay("createInvoice", {
        "currency_type": "fiat", "fiat": "USD", "accepted_assets": TOPUP_ASSETS,   # Rechnung in $, bezahlt mit USDT oder TRX
        "amount": f"{amount:.2f}", "payload": f"topup:{user_id}",
        "description": tr(user_lang(user_id), "topup_desc", amount=f"{amount:g}", asset="$"), "expires_in": 3600,
        "allow_comments": False, "allow_anonymous": False})
    if not res.get("ok"):
        raise E(502, "cryptobot_down")
    inv = res["result"]
    url = inv.get("mini_app_invoice_url") or inv.get("bot_invoice_url") or inv.get("pay_url")
    with db() as con:
        con.execute("INSERT INTO topups (invoice_id, user_id, amount, status, url, created) VALUES (?,?,?,?,?,?)",
                    (inv["invoice_id"], user_id, amount, "active", url, game.now()))
    return {"url": url, "invoice_id": inv["invoice_id"]}


async def check_topups(user_id: int | None = None) -> int:
    """Fragt bei CryptoBot nach, ob offene Aufladungen bezahlt wurden (zusätzlich zum Webhook)."""
    if not CRYPTOPAY_TOKEN:
        return 0
    with db() as con:
        q = "SELECT invoice_id FROM topups WHERE status='active' AND created>?"
        args = [game.now() - 2 * 3600]
        if user_id:
            q += " AND user_id=?"; args.append(user_id)
        ids = [r[0] for r in con.execute(q, args)]
    if not ids:
        return 0
    res = await cryptopay("getInvoices", {"invoice_ids": ",".join(map(str, ids))})
    credited = 0
    with db() as con:
        for inv in (res.get("result") or {}).get("items", []):
            if inv.get("status") == "paid" and credit_topup(con, inv["invoice_id"], float(inv["amount"])):
                credited += 1
            elif inv.get("status") == "expired":
                con.execute("UPDATE topups SET status='expired' WHERE invoice_id=?", (inv["invoice_id"],))
    return credited


# ================================================================ API
@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)


NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


@app.get("/")
async def index():
    return FileResponse(BASE / "webapp" / "index.html", headers=NO_CACHE)


@app.get("/logo.png")
async def logo():
    return FileResponse(BASE / "webapp" / "logo.png", media_type="image/png")


@app.get("/characters.js")
async def characters_js():
    return FileResponse(BASE / "webapp" / "characters.js", media_type="application/javascript")


PROMO_TYPES = {".jpg": "image/jpeg", ".pdf": "application/pdf"}


@app.get("/promo/{name}")
async def promo_file(name: str):
    """Werbebanner und Whitepaper für Spieler zum Teilen."""
    path = BASE / "webapp" / "promo" / name
    ext = path.suffix.lower()
    if "/" in name or ".." in name or ext not in PROMO_TYPES or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=PROMO_TYPES[ext], filename=f"CryptoBuddies_{name}",
                        content_disposition_type="inline" if ext == ".pdf" else "attachment")


@app.get("/adsgram/reward")
async def adsgram_reward(userid: int, secret: str = ""):
    """AdsGram ruft diese Adresse auf, wenn ein Spieler eine Werbung zu Ende gesehen hat."""
    if ADSGRAM_SECRET and not hmac.compare_digest(secret, ADSGRAM_SECRET):
        raise HTTPException(403, "falsches Secret")
    t = game.now()
    with db() as con:
        con.execute("INSERT INTO ad_views (user_id, ts, period, source) VALUES (?,?,?,'s2s')", (userid, t, game.period_of(t)))
    return PlainTextResponse("ok")


@app.post("/cryptopay/webhook")
async def cryptopay_webhook(request: Request):
    """CryptoBot meldet bezahlte Rechnungen. Signatur: HMAC-SHA256(Body, SHA256(Token))."""
    raw = await request.body()
    secret = hashlib.sha256(CRYPTOPAY_TOKEN.encode()).digest()
    sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not CRYPTOPAY_TOKEN or not hmac.compare_digest(sig, request.headers.get("crypto-pay-api-signature", "")):
        raise HTTPException(401, "falsche Signatur")
    data = json.loads(raw)
    inv = data.get("payload") or {}
    if data.get("update_type") == "invoice_paid" and str(inv.get("payload", "")).startswith("topup:"):
        with db() as con:
            uid = credit_topup(con, int(inv["invoice_id"]), float(inv["amount"]))
        if uid:
            try:
                with db() as con:
                    amt = con.execute("SELECT amount FROM topups WHERE invoice_id=?", (int(inv["invoice_id"]),)).fetchone()[0]
                await bot.send_message(uid, tr(user_lang(uid), "topup_ok", amount=f"{amt:g}"))
            except Exception:
                pass
    return {"ok": True}


@app.post("/api/{action}")
async def api(action: str, request: Request, x_init_data: str | None = Header(None)):
    lang = "en"
    try:
        if not x_init_data:
            raise E(401, "open_in_telegram")
        tg_user, start_param = verify_init_data(x_init_data)
        user_id = int(tg_user["id"])
        lang = user_lang(user_id)
        body = await request.json() if await request.body() else {}
        return await handle(action, user_id, tg_user, start_param, body)
    except HTTPException as e:
        if isinstance(e.detail, dict) and "key" in e.detail:
            raise HTTPException(e.status_code, tr(lang, e.detail["key"], **e.detail["kw"]))
        raise


async def handle(action, user_id, tg_user, start_param, body):
    name = tg_user.get("first_name") or tg_user.get("username") or "Player"

    if action == "buy":   # Rechnungslink in Telegram Stars
        if not SHOP_ENABLED:
            raise E(400, "shop_off")
        pkg = game.STAR_PACKAGES.get(body.get("package"))
        if not pkg:
            raise E(400, "unknown_package")
        lang = user_lang(user_id)
        link = await bot.create_invoice_link(
            title=tr(lang, "stars_title", n=pkg[0]), description=tr(lang, "stars_desc", n=pkg[0]),
            payload=f"{body['package']}:{user_id}", currency="XTR",
            prices=[LabeledPrice(label=tr(lang, "stars_title", n=pkg[0]), amount=pkg[1])])
        return {"link": link}
    if action == "topup":
        return await act_topup(user_id, body.get("amount"))
    if action == "topup_check":
        await check_topups(user_id)
        action = "state"

    with db() as con:
        joined = ensure_user(con, user_id, name, parse_ref(start_param))   # Einladung auch beim direkten App-Start
        settle(con, user_id)
        con.execute("UPDATE users SET last_seen=?, blocked=0, username=? WHERE id=?",
                    (game.now(), (tg_user.get("username") or "").lower() or None, user_id))
        u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        result = None
        if action == "state":
            pass
        elif action == "lang":
            if body.get("lang") not in LANGS:
                raise E(400, "bad_lang")
            con.execute("UPDATE users SET lang=? WHERE id=?", (body["lang"], user_id))
        elif action == "pack":
            result = act_pack(con, user_id, u, body.get("pack"))
            if result["collection_bonus"] and ADMIN_ID:
                asyncio.get_running_loop().create_task(bot.send_message(
                    ADMIN_ID, f"🏆 Sammel-Bonus ({game.COLLECTION_BONUS_USDT} USDT) an {name} ({user_id}) – alle {len(game.REGULAR_IDS)} Figuren gesammelt"))
            if result["jackpot"] and ADMIN_ID:
                asyncio.get_running_loop().create_task(bot.send_message(
                    ADMIN_ID, f"🎰 Jackpot: {game.BY_ID[result['char']]['name']} "
                              f"({game.JACKPOT_USD[result['char']]} $/Tag) an {name} ({user_id})"))
        elif action == "levelup":
            result = act_levelup(con, user_id, u, body.get("char"), body.get("steps", 1))
        elif action == "ad":
            result = act_ad(con, user_id, u)
        elif action == "daily":
            result = act_daily(con, user_id, u)
        elif action == "buy_diamonds":
            result = act_buy_diamonds(con, user_id, u, body.get("diamonds"))
        elif action == "autopayout":
            con.execute("UPDATE users SET autopayout=? WHERE id=?", (int(bool(body.get("on"))), user_id))
        else:
            raise E(404, "unknown_action")
        s = state(con, user_id)
        s["result"] = result
    if joined["referrer"]:
        asyncio.get_running_loop().create_task(notify_referrer(joined["referrer"], name))
    return s



# ================================================================ Admin-Panel
@app.get("/admin")
async def admin_page():
    return FileResponse(BASE / "webapp" / "admin.html", headers=NO_CACHE)


async def broadcast(texts: dict, button: bool = True) -> dict:
    """Schickt eine Nachricht an alle Spieler in ihrer Sprache. Läuft im Hintergrund, ca. 20 Nachrichten/Sekunde."""
    with db() as con:
        users = con.execute("SELECT id, lang FROM users WHERE blocked=0").fetchall()
    sent = failed = 0
    for u in users:
        text = texts.get(u["lang"]) or texts.get("en") or texts.get("de")
        try:
            await bot.send_message(u["id"], text, reply_markup=play_keyboard(u["lang"]) if button else None)
            sent += 1
        except Exception as e:
            failed += 1
            if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                with db() as con:
                    con.execute("UPDATE users SET blocked=1 WHERE id=?", (u["id"],))
        await asyncio.sleep(0.05)
    log.info("Rundsendung: %s gesendet, %s fehlgeschlagen", sent, failed)
    return {"sent": sent, "failed": failed}


def news_text(n: dict, lang: str) -> str:
    title = n.get(f"title_{lang}") or n.get("title_en") or n.get("title_de")
    body = n.get(f"body_{lang}") or n.get("body_en") or n.get("body_de")
    return f"📰 <b>{title}</b>\n\n{body}"


async def admin_stats() -> dict:
    t = game.now()
    with db() as con:
        q = lambda sql, *a: con.execute(sql, a).fetchone()[0]
        st = {
            "users": q("SELECT COUNT(*) FROM users"),
            "active_24h": q("SELECT COUNT(*) FROM users WHERE last_seen>?", t - 86400),
            "new_24h": q("SELECT COUNT(*) FROM users WHERE created>?", t - 86400),
            "ads_24h": q("SELECT COUNT(*) FROM ad_views WHERE ts>? AND (used=1 OR source='s2s')", t - 86400),
            "packs_24h": q("SELECT COUNT(*) FROM pulls WHERE ts>?", t - 86400),
            "owed": round(q("SELECT COALESCE(SUM(usdt),0) FROM users"), 2),
            "deposits": round(q("SELECT COALESCE(SUM(deposit),0) FROM users"), 2),
            "paid_total": round(q("SELECT COALESCE(SUM(amount),0) FROM payouts WHERE status='done'"), 2),
            "pending": q("SELECT COUNT(*) FROM payouts WHERE status='pending'"),
            "credited_7d": round(q("SELECT COALESCE(SUM(pool),0) FROM rounds WHERE closed_at>?", t - 7 * 86400), 2),
            "revenue_7d": round(q("SELECT COALESCE(SUM(revenue),0) FROM rounds WHERE closed_at>?", t - 7 * 86400), 2),
            "rounds": [dict(r) for r in con.execute("SELECT period, views, revenue, pool AS paid, players, closed_at FROM rounds ORDER BY period DESC LIMIT 6")],
        }
    st["settings"] = {"payout_mode": PAYOUT_MODE, "payout_asset": PAYOUT_ASSET, "shop": SHOP_ENABLED,
                      "ads": "AdsGram" if ADSGRAM_BLOCK_ID else ("Monetag" if MONETAG_ZONE_ID else "–"), "ecpm": ECPM_USD}
    st["cryptobot"] = None
    if CRYPTOPAY_TOKEN:
        try:
            bal = await cryptopay("getBalance", {})
            st["cryptobot"] = {b["currency_code"]: float(b["available"]) for b in bal.get("result") or [] if float(b.get("available", 0))}
        except Exception as e:
            st["cryptobot"] = {"error": str(e)[:80]}
    return st


@app.post("/admin/api/{action}")
async def admin_api(action: str, request: Request, x_init_data: str | None = Header(None)):
    if not x_init_data:
        raise HTTPException(401, "Bitte über /admin im Bot öffnen")
    try:
        tg_user, _ = verify_init_data(x_init_data)
    except HTTPException as e:
        raise HTTPException(401, "Anmeldung ungültig – Panel neu öffnen")
    admin_id = int(tg_user["id"])
    if not is_admin(admin_id):
        raise HTTPException(403, "Kein Admin")
    body = await request.json() if await request.body() else {}

    def log_action(action, target=None, details=None):
        with db() as con:
            con.execute("INSERT INTO admin_log (admin_id, action, target, details, ts) VALUES (?,?,?,?,?)",
                        (admin_id, action, target, json.dumps(details, ensure_ascii=False) if details else None, game.now()))

    def owner_only():
        if not is_owner(admin_id):
            raise HTTPException(403, "Nur der Besitzer (ADMIN_ID) darf Admins verwalten")

    try:
        if action == "me":
            return {"id": admin_id, "owner": is_owner(admin_id)}
        # ---------------- Admins
        if action == "admins_list":
            with db() as con:
                admins = [dict(r) for r in con.execute(
                    "SELECT a.user_id, COALESCE(u.username, a.username) AS username, u.name, a.created FROM admins a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.created")]
                owners = [dict(user_id=i, username=(con.execute("SELECT username FROM users WHERE id=?", (i,)).fetchone() or [None])[0]) for i in sorted(ADMIN_IDS)]
            return {"owners": owners, "admins": admins}
        if action == "admin_add":
            owner_only()
            uname = str(body.get("username", "")).strip().lstrip("@").lower()
            with db() as con:
                u = con.execute("SELECT id, name, username FROM users WHERE username=? OR CAST(id AS TEXT)=?", (uname, uname)).fetchone()
                if not u:
                    raise ValueError(f"@{uname} wurde nicht gefunden – die Person muss den Bot zuerst einmal mit /start öffnen")
                con.execute("INSERT OR IGNORE INTO admins (user_id, username, added_by, created) VALUES (?,?,?,?)",
                            (u["id"], u["username"], admin_id, game.now()))
            log_action("admin_add", u["id"], {"username": uname})
            try:
                await bot.send_message(u["id"], "🔑 Du bist jetzt Admin von Crypto Buddies. Schick /admin, um das Panel zu öffnen.\n"
                                                 "You are now an admin of Crypto Buddies. Send /admin to open the panel.")
            except Exception:
                pass
            return {"ok": True, "user_id": u["id"], "name": u["name"]}
        if action == "admin_remove":
            owner_only()
            uid = int(body["user_id"])
            if uid in ADMIN_IDS:
                raise ValueError("Besitzer können nur über ADMIN_ID in den Einstellungen entfernt werden")
            with db() as con:
                con.execute("DELETE FROM admins WHERE user_id=?", (uid,))
            log_action("admin_remove", uid)
            return {"ok": True}
        # ---------------- Spieler
        if action == "user_search":
            q = str(body.get("q", "")).strip().lstrip("@").lower()
            with db() as con:
                rows = con.execute("""SELECT id, name, username, diamonds, usdt, last_seen FROM users
                                      WHERE CAST(id AS TEXT)=? OR username LIKE ? OR LOWER(name) LIKE ?
                                      ORDER BY last_seen DESC LIMIT 20""", (q, f"{q}%", f"%{q}%")).fetchall() if q else \
                       con.execute("SELECT id, name, username, diamonds, usdt, last_seen FROM users ORDER BY last_seen DESC LIMIT 20").fetchall()
            return {"users": [dict(r) for r in rows]}
        if action == "user_get":
            uid = int(body["id"])
            with db() as con:
                u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                if not u:
                    raise ValueError("Spieler nicht gefunden")
                ks = [dict(id=k["char_id"], level=k["level"], copies=k["copies"], daily=game.daily_profit(k["char_id"], k["level"]))
                      for k in con.execute("SELECT * FROM kumpels WHERE user_id=? ORDER BY level DESC", (uid,))]
                prof = {k: u[k] for k in ("id", "name", "username", "diamonds", "usdt", "deposit", "usdt_paid", "points_total",
                                          "created", "last_seen", "lang", "blocked", "collection_bonus")}
                prof["friends"] = con.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (uid,)).fetchone()[0]
                prof["is_admin"] = is_admin(uid, con)
                prof["log"] = [dict(r) for r in con.execute(
                    "SELECT admin_id, action, details, ts FROM admin_log WHERE target=? ORDER BY id DESC LIMIT 10", (uid,))]
            return {"user": prof, "kumpels": ks}
        if action == "user_grant":
            uid, char = int(body["id"]), str(body["char"])
            level = max(1, min(game.MAX_LEVEL, int(body.get("level", 1))))
            if char not in game.BY_ID:
                raise ValueError("Unbekannte Figur")
            with db() as con:
                if not con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                    raise ValueError("Spieler nicht gefunden")
                settle(con, uid)
                k = con.execute("SELECT * FROM kumpels WHERE user_id=? AND char_id=?", (uid, char)).fetchone()
                if k:
                    con.execute("UPDATE kumpels SET level=? WHERE user_id=? AND char_id=?", (level, uid, char))
                else:
                    con.execute("INSERT INTO kumpels (user_id, char_id, level, last_collect) VALUES (?,?,?,?)", (uid, char, level, game.now()))
            log_action("grant_kumpel", uid, {"char": char, "level": level})
            if body.get("notify"):
                lang = user_lang(uid)
                nm = game.BY_ID[char]["name"]
                try:
                    await bot.send_message(uid, (f"🎁 You received <b>{nm}</b> (level {level})!" if lang == "en"
                                                 else f"🎁 Du hast <b>{nm}</b> (Stufe {level}) bekommen!"), reply_markup=play_keyboard(lang))
                except Exception:
                    pass
            return {"ok": True}
        if action == "user_kumpel_remove":
            uid, char = int(body["id"]), str(body["char"])
            with db() as con:
                settle(con, uid)
                con.execute("DELETE FROM kumpels WHERE user_id=? AND char_id=?", (uid, char))
            log_action("remove_kumpel", uid, {"char": char})
            return {"ok": True}
        if action == "user_balance":
            uid, field, mode = int(body["id"]), body.get("field"), body.get("mode")
            if field not in ("diamonds", "usdt", "deposit") or mode not in ("add", "set"):
                raise ValueError("Feld oder Modus ungültig")
            value = float(body["value"])
            if field == "diamonds":
                value = int(round(value))
            with db() as con:
                u = con.execute(f"SELECT {field} FROM users WHERE id=?", (uid,)).fetchone()
                if not u:
                    raise ValueError("Spieler nicht gefunden")
                new = (u[0] + value) if mode == "add" else value
                if new < 0:
                    raise ValueError("Ergebnis wäre negativ")
                con.execute(f"UPDATE users SET {field}=? WHERE id=?", (new, uid))
            log_action("balance", uid, {"field": field, "mode": mode, "value": value, "old": u[0], "new": new})
            if body.get("notify") and new > u[0]:
                lang = user_lang(uid)
                diff = new - u[0]
                what = (f"{int(diff)} 💎" if field == "diamonds" else (f"${diff:.2f}" if lang == "en" else f"{diff:.2f} $"))
                try:
                    await bot.send_message(uid, f"🎁 +{what} " + ("credited to your account!" if lang == "en" else "wurden dir gutgeschrieben!"),
                                           reply_markup=play_keyboard(lang))
                except Exception:
                    pass
            return {"ok": True, "old": u[0], "new": new}
        if action == "characters":
            return {"characters": [dict(id=c["id"], name=c["name"], edition=c["edition"], no=c["no"],
                                        jackpot=c["id"] in game.JACKPOT_USD) for c in game.CHARACTERS]}
        if action == "stats":
            return await admin_stats()
        if action == "news_list":
            with db() as con:
                return {"news": [dict(r) for r in con.execute("SELECT * FROM news ORDER BY created DESC LIMIT 50")]}
        if action == "news_create":
            with db() as con:
                nid = events.create_news(con, body)
                n = dict(con.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone())
            if body.get("broadcast"):
                asyncio.get_running_loop().create_task(broadcast({"en": news_text(n, "en"), "de": news_text(n, "de")}))
                with db() as con:
                    con.execute("UPDATE news SET broadcast=1 WHERE id=?", (nid,))
            return {"ok": True, "id": nid}
        if action == "news_delete":
            with db() as con:
                con.execute("DELETE FROM news WHERE id=?", (int(body["id"]),))
            return {"ok": True}
        if action == "news_pin":
            with db() as con:
                con.execute("UPDATE news SET pinned=? WHERE id=?", (int(bool(body.get("pinned"))), int(body["id"])))
            return {"ok": True}
        if action == "tour_list":
            with db() as con:
                return {"tournaments": events.admin_tournaments(con), "metrics": events.METRICS}
        if action == "tour_create":
            with db() as con:
                tid = events.create_tournament(con, body)
            if body.get("broadcast"):
                name = {"en": body.get("name_en") or body.get("name_de"), "de": body.get("name_de") or body.get("name_en")}
                asyncio.get_running_loop().create_task(broadcast({
                    "en": f"🏆 <b>New tournament: {name['en']}</b>\nOpen the game to join – the best players win prizes!",
                    "de": f"🏆 <b>Neues Turnier: {name['de']}</b>\nÖffne das Spiel und mach mit – die Besten gewinnen Preise!"}))
            return {"ok": True, "id": tid}
        if action == "tour_cancel":
            with db() as con:
                con.execute("UPDATE tournaments SET status='cancelled', finished=? WHERE id=? AND status='open'", (game.now(), int(body["id"])))
            return {"ok": True}
        if action == "tour_end_now":
            with db() as con:
                con.execute("UPDATE tournaments SET end=? WHERE id=? AND status='open'", (game.now(), int(body["id"])))
            await finish_tournaments()
            return {"ok": True}
        if action == "broadcast":
            texts = {k: v for k, v in {"en": body.get("text_en", ""), "de": body.get("text_de", "")}.items() if v.strip()}
            if not texts:
                raise ValueError("Text fehlt")
            asyncio.get_running_loop().create_task(broadcast(texts))
            with db() as con:
                n = con.execute("SELECT COUNT(*) FROM users WHERE blocked=0").fetchone()[0]
            return {"ok": True, "recipients": n}
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e) or "Ungültige Eingabe")
    raise HTTPException(404, "Unbekannte Aktion")


async def finish_tournaments():
    with db() as con:
        done = events.finish_due(con)
    for t in done:
        for w in t["winners"]:
            lang = user_lang(w["user_id"])
            prize = f"{int(w['prize'])} 💎" if t["prize_type"] == "diamonds" else (f"${w['prize']:.2f}" if lang == "en" else f"{w['prize']:.2f} $")
            name = t[f"name_{lang}"] or t["name_en"] or t["name_de"]
            text = (f"🏆 Tournament „{name}“ is over – you finished <b>#{w['rank']}</b> and won <b>{prize}</b>!" if lang == "en"
                    else f"🏆 Turnier „{name}“ ist vorbei – du bist auf <b>Platz {w['rank']}</b> und gewinnst <b>{prize}</b>!")
            try:
                await bot.send_message(w["user_id"], text)
            except Exception:
                pass
        if ADMIN_ID:
            try:
                await bot.send_message(ADMIN_ID, f"🏁 Turnier #{t['id']} beendet, {len(t['winners'])} Gewinner ausgezeichnet.")
            except Exception:
                pass


async def events_loop():
    while True:
        try:
            await finish_tournaments()
        except Exception:
            log.exception("Fehler beim Beenden von Turnieren")
        await asyncio.sleep(30)


# ================================================================ Auszahlungs-Runden
def close_rounds(t: float | None = None) -> list[dict]:
    """Schließt alle abgelaufenen Runden und schreibt die Erträge der Figuren voll in USDT gut."""
    t = t or game.now()
    current = game.period_of(t)
    closed = []
    with db() as con:
        for (uid,) in con.execute("SELECT id FROM users").fetchall():   # alles bis jetzt gutschreiben
            settle(con, uid, t)
        open_periods = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM round_points WHERE period<? AND period NOT IN (SELECT period FROM rounds) ORDER BY period",
            (current,))]
        for p in open_periods:
            end = game.period_end(p)
            src = "source='s2s'" if ADS_VERIFY else "source='client'"
            views = con.execute(f"SELECT COUNT(*) FROM ad_views WHERE period=? AND {src}", (p,)).fetchone()[0]
            revenue = views * ECPM_USD / 1000
            rows = [r for r in con.execute("SELECT user_id, points FROM round_points WHERE period=? AND points>0", (p,))
                    if ads_last_24h(con, r["user_id"], end) >= MIN_ADS_24H]
            total = sum(r["points"] for r in rows)
            factor = 1.0
            if MAX_PAYOUT_PER_ROUND > 0 and total > MAX_PAYOUT_PER_ROUND:   # Notbremse
                factor = MAX_PAYOUT_PER_ROUND / total
            paid = 0.0
            for r in rows:
                amount = round(r["points"] * factor, 6)
                paid += amount
                con.execute("INSERT OR REPLACE INTO round_shares VALUES (?,?,?,?)", (r["user_id"], p, r["points"], amount))
                con.execute("UPDATE users SET usdt=usdt+? WHERE id=?", (amount, r["user_id"]))
                ref = con.execute("SELECT ref_by FROM users WHERE id=?", (r["user_id"],)).fetchone()
                if ref and ref[0] and amount > 0:   # Werbebonus: 20 % on top an den Einlader
                    bonus = round(amount * game.REFERRAL_SHARE, 6)
                    con.execute("UPDATE users SET usdt=usdt+?, ref_earned=ref_earned+? WHERE id=?", (bonus, bonus, ref[0]))
                    paid += bonus
            con.execute("INSERT INTO rounds VALUES (?,?,?,?,?,?,?)", (p, views, revenue, paid, total, len(rows), t))
            info = {"period": p, "views": views, "revenue": revenue, "paid": paid, "players": len(rows), "factor": factor}
            closed.append(info)
            log.info("Runde %s: %s Werbungen, ~%.2f $ Einnahmen, %.4f $ gutgeschrieben, %s Spieler", p, views, revenue, paid, len(rows))
    return closed


def queue_payouts() -> None:
    """Legt Auszahlungen für alle an, die über der Mindestgrenze liegen."""
    if PAYOUT_MODE == "off":
        return
    t = game.now()
    with db() as con:
        for u in con.execute("SELECT id, usdt FROM users WHERE usdt>=? AND autopayout=1", (MIN_PAYOUT,)).fetchall():
            amount = int(u["usdt"] * 100) / 100          # auf Cent abrunden
            con.execute("UPDATE users SET usdt=usdt-? WHERE id=?", (amount, u["id"]))
            con.execute("INSERT INTO payouts (user_id, amount, spend_id, status, created) VALUES (?,?,?,?,?)",
                        (u["id"], amount, f"kk-{u['id']}-{int(t)}", "pending", t))


async def cryptopay(method: str, params: dict) -> dict:
    host = "testnet-pay.crypt.bot" if PAYOUT_MODE == "test" else "pay.crypt.bot"   # test = Testnetz für alles
    async with aiohttp.ClientSession() as s:
        async with s.post(f"https://{host}/api/{method}", json=params,
                          headers={"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}, timeout=aiohttp.ClientTimeout(total=20)) as r:
            return await r.json()


async def usd_rate(asset: str) -> float:
    """Kurs: 1 Einheit `asset` = x US-Dollar (von CryptoBot)."""
    if asset in ("USDT", "USDC"):
        return 1.0
    res = await cryptopay("getExchangeRates", {})
    for r in res.get("result") or []:
        if r.get("source") == asset and r.get("target") == "USD" and r.get("is_valid"):
            return float(r["rate"])
    raise RuntimeError(f"Kein Kurs für {asset}")


async def send_payouts() -> None:
    """Schickt offene Auszahlungen über CryptoBot in PAYOUT_ASSET (z. B. TRX).
    Der $-Betrag wird beim ersten Versuch zum aktuellen Kurs umgerechnet und gespeichert, damit eine
    Wiederholung mit derselben spend_id genau denselben Betrag schickt."""
    if PAYOUT_MODE == "off" or not CRYPTOPAY_TOKEN:
        return
    with db() as con:
        pending = con.execute("SELECT * FROM payouts WHERE status='pending' ORDER BY id").fetchall()
    if not pending:
        return
    try:
        rate = await usd_rate(PAYOUT_ASSET)
        bal = await cryptopay("getBalance", {})
        available = sum(float(b.get("available", 0)) for b in bal.get("result") or [] if b.get("currency_code") == PAYOUT_ASSET)
    except Exception as e:
        log.warning("CryptoBot nicht erreichbar: %s", e)
        return
    needed = 0.0
    with db() as con:   # Beträge festlegen (nur beim ersten Versuch)
        for p in pending:
            if p["asset_amount"] is None:
                amt = int(p["amount"] / rate * 100) / 100           # auf 0,01 abrunden
                con.execute("UPDATE payouts SET asset=?, asset_amount=?, rate=? WHERE id=?", (PAYOUT_ASSET, amt, rate, p["id"]))
                needed += amt
            else:
                needed += p["asset_amount"]
        pending = con.execute("SELECT * FROM payouts WHERE status='pending' ORDER BY id").fetchall()
    if needed > available:
        log.warning("Zu wenig %s bei CryptoBot: %.2f nötig, %.2f vorhanden", PAYOUT_ASSET, needed, available)
        if ADMIN_ID:
            try:
                await bot.send_message(ADMIN_ID, f"⚠️ Auszahlungen angehalten: {needed:.2f} {PAYOUT_ASSET} nötig, "
                                                 f"nur {available:.2f} {PAYOUT_ASSET} in der CryptoBot-App. Bitte aufladen.")
            except Exception:
                pass
        return
    for p in pending:
        lang = user_lang(p["user_id"])
        try:
            res = await cryptopay("transfer", {"user_id": p["user_id"], "asset": p["asset"],
                                               "amount": f"{p['asset_amount']:.2f}", "spend_id": p["spend_id"],
                                               "comment": tr(lang, "payout_comment")})
        except Exception as e:                       # Netzwerkfehler: bleibt offen, nächste Runde erneut
            log.warning("Auszahlung %s: %s", p["id"], e)
            continue
        with db() as con:
            if res.get("ok"):
                con.execute("UPDATE payouts SET status='done', done=? WHERE id=?", (game.now(), p["id"]))
                con.execute("UPDATE users SET usdt_paid=usdt_paid+? WHERE id=?", (p["amount"], p["user_id"]))
                msg = tr(lang, "payout_sent", usd=f"{p['amount']:.2f}", amount=f"{p['asset_amount']:.2f}", asset=p["asset"])
            else:                                    # abgelehnt: $-Betrag zurück aufs Guthaben
                err = json.dumps(res.get("error"))[:300]
                con.execute("UPDATE payouts SET status='failed', error=? WHERE id=?", (err, p["id"]))
                con.execute("UPDATE users SET usdt=usdt+? WHERE id=?", (p["amount"], p["user_id"]))
                msg = tr(lang, "payout_failed")
        try:
            await bot.send_message(p["user_id"], msg)
        except Exception:
            pass


async def payout_loop():
    while True:
        try:
            for r in close_rounds():
                if ADMIN_ID and r["paid"] > r["revenue"]:
                    await bot.send_message(ADMIN_ID, (
                        f"⚠️ Runde {r['period']}: {r['paid']:.2f} $ gutgeschrieben, aber nur ca. {r['revenue']:.2f} $ "
                        f"Werbeeinnahmen ({r['views']} Werbungen). Verlust dieser Runde: {r['paid'] - r['revenue']:.2f} $."))
            queue_payouts()
            await send_payouts()
        except Exception:
            log.exception("Fehler in der Auszahlungsrunde")
        wait = game.period_end(game.period_of(game.now())) - game.now() + 5
        await asyncio.sleep(max(5, wait))


# ================================================================ Bot
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


def play_keyboard(lang: str):
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang, "play"), web_app=WebAppInfo(url=WEBAPP_URL))]])


@dp.message(CommandStart())
async def start(message: Message, command: CommandObject):
    u = message.from_user
    with db() as con:
        joined = ensure_user(con, u.id, u.first_name, parse_ref(command.args))
        con.execute("UPDATE users SET username=?, blocked=0 WHERE id=?", ((u.username or "").lower() or None, u.id))
    lang = user_lang(u.id)
    text = tr(lang, "welcome", name=u.first_name)
    if joined["referrer"]:
        text += "\n" + tr(lang, "invited", n=game.REFERRAL_DIAMONDS)
        asyncio.get_running_loop().create_task(notify_referrer(joined["referrer"], u.first_name))
    await message.answer(text, reply_markup=play_keyboard(lang))


@dp.message(Command("language", "sprache"))
async def language(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="lang:de")]])
    await message.answer(tr(user_lang(message.from_user.id), "lang_cmd"), reply_markup=kb)


@dp.callback_query(F.data.startswith("lang:"))
async def set_language(q: CallbackQuery):
    lang = q.data.split(":", 1)[1]
    if lang in LANGS:
        with db() as con:
            ensure_user(con, q.from_user.id, q.from_user.first_name)
            con.execute("UPDATE users SET lang=? WHERE id=?", (lang, q.from_user.id))
        await q.message.answer(tr(lang, "lang_set"), reply_markup=play_keyboard(lang))
    await q.answer()


@dp.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Deine Telegram-ID / Your Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    with db() as con:
        ensure_user(con, message.from_user.id, message.from_user.first_name)
        con.execute("UPDATE users SET username=? WHERE id=?", ((message.from_user.username or "").lower() or None, message.from_user.id))
    if not is_admin(message.from_user.id):
        return
    if not WEBAPP_URL:
        await message.answer("WEBAPP_URL fehlt in den Einstellungen.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="⚙️ Admin-Panel öffnen", web_app=WebAppInfo(url=WEBAPP_URL.rstrip("/") + "/admin"))]])
    await message.answer("Admin-Panel", reply_markup=kb)


@dp.message(Command("status"))
async def status(message: Message):
    if not is_admin(message.from_user.id):
        return
    with db() as con:
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        last = con.execute("SELECT * FROM rounds ORDER BY period DESC LIMIT 1").fetchone()
        owed = con.execute("SELECT COALESCE(SUM(usdt),0) FROM users").fetchone()[0]
        paid = con.execute("SELECT COALESCE(SUM(amount),0) FROM payouts WHERE status='done'").fetchone()[0]
    text = f"👥 Spieler: {users}\n💰 Offenes Guthaben: {owed:.2f} $\n✅ Ausgezahlt: {paid:.2f} $\nModus: {PAYOUT_MODE}"
    if last:
        text += (f"\n\nLetzte Runde: {last['views']} Werbungen · ca. {last['revenue']:.2f} $ Einnahmen · "
                 f"{last['pool']:.2f} $ gutgeschrieben · {last['players']} Spieler")
    if PAYOUT_MODE != "off" and CRYPTOPAY_TOKEN:
        try:
            bal = await cryptopay("getBalance", {})
            text += "\n\nCryptoBot: " + ", ".join(f"{b['available']} {b['currency_code']}" for b in bal.get("result", []) if float(b["available"]))
        except Exception as e:
            text += f"\n\nCryptoBot nicht erreichbar: {e}"
    await message.answer(text)


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=SHOP_ENABLED, error_message=None if SHOP_ENABLED else tr(user_lang(q.from_user.id), "shop_off"))


@dp.message(F.successful_payment)
async def paid(message: Message):
    sp = message.successful_payment
    pkg_key, _, uid = sp.invoice_payload.partition(":")
    diamonds = game.STAR_PACKAGES.get(pkg_key, (0, 0))[0]
    with db() as con:
        try:
            con.execute("INSERT INTO purchases (user_id, stars, diamonds, charge_id, ts) VALUES (?,?,?,?,?)",
                        (int(uid), sp.total_amount, diamonds, sp.telegram_payment_charge_id, game.now()))
            con.execute("UPDATE users SET diamonds=diamonds+? WHERE id=?", (diamonds, int(uid)))
        except sqlite3.IntegrityError:
            return   # schon gutgeschrieben
    await message.answer(tr(user_lang(message.from_user.id), "stars_ok", n=diamonds))


async def run_bot():
    global BOT_USERNAME
    me = await bot.get_me()
    if me.username and BOT_USERNAME != me.username:   # Benutzername automatisch – Einladungslinks stimmen immer
        if BOT_USERNAME:
            log.warning("BOT_USERNAME (%s) passt nicht zum Bot (%s) – verwende %s", BOT_USERNAME, me.username, me.username)
        BOT_USERNAME = me.username
    if WEBAPP_URL:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Play", web_app=WebAppInfo(url=WEBAPP_URL)))
    await dp.start_polling(bot)


def check_config() -> None:
    """Prüft beim Start die wichtigsten Einstellungen und meldet Probleme deutlich im Log."""
    problems = []
    if not WEBAPP_URL.startswith("https://"):
        problems.append("WEBAPP_URL fehlt oder ist nicht https – die Mini App lässt sich nicht öffnen")
    if not (ADSGRAM_BLOCK_ID or MONETAG_ZONE_ID):
        problems.append("Kein Werbeanbieter (ADSGRAM_BLOCK_ID / MONETAG_ZONE_ID) – Videos und Diamanten sind gesperrt")
    if ADSGRAM_BLOCK_ID and not ADSGRAM_BLOCK_ID.strip().isdigit():
        problems.append(f"ADSGRAM_BLOCK_ID muss eine reine Zahl sein (z. B. 12345), eingetragen ist '{ADSGRAM_BLOCK_ID}' – AdsGram wird übersprungen")
    if ADSGRAM_INTERSTITIAL_ID and not (ADSGRAM_INTERSTITIAL_ID.startswith("int-") and ADSGRAM_INTERSTITIAL_ID[4:].isdigit()):
        problems.append(f"ADSGRAM_INTERSTITIAL_ID muss wie 'int-12345' aussehen, eingetragen ist '{ADSGRAM_INTERSTITIAL_ID}'")
    if not ADMIN_ID:
        problems.append("ADMIN_ID fehlt – kein Admin-Panel und keine Warnungen. Schick dem Bot /id und trag die Zahl ein")
    if PAYOUT_MODE in ("live", "test") and not CRYPTOPAY_TOKEN:
        problems.append("PAYOUT_MODE ist an, aber CRYPTOPAY_TOKEN fehlt – es wird nichts ausgezahlt")
    if PAYOUT_MODE == "live" and MIN_PAYOUT < 1:
        problems.append("MIN_PAYOUT unter 1 – CryptoBot lehnt Überweisungen unter ca. 1 $ ab")
    if DEV_MODE:
        problems.append("DEV_MODE ist an – Diamanten auch ohne Werbung! Nur zum Testen")
    for p in problems:
        log.warning("⚠️  %s", p)
    log.info("Start: Auszahlung=%s (%s), Shop=%s, Werbung=%s", PAYOUT_MODE, PAYOUT_ASSET,
             "an" if SHOP_ENABLED else "aus", "AdsGram" if ADSGRAM_BLOCK_ID else ("Monetag" if MONETAG_ZONE_ID else "keine"))


async def main():
    check_config()
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info"))
    await asyncio.gather(server.serve(), run_bot(), payout_loop(), events_loop())


if __name__ == "__main__":
    asyncio.run(main())
