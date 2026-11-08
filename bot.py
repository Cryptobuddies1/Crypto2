"""Crypto Buddies – Telegram-Bot + Mini-App-Server + Auszahlungen in einem Prozess.

Start:  python bot.py        (Einstellungen in .env, siehe .env.example)
"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import math
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
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
MONETAG_ZONE_ID = env("MONETAG_ZONE_ID", "")               # optional: Monetag als letzter Ersatz
RICHADS_PUB_ID = env("RICHADS_PUB_ID", "1028233")          # RichAds: zweiter Anbieter nach AdsGram (leer = aus)
RICHADS_APP_ID = env("RICHADS_APP_ID", "9592")
DEV_MODE = env("DEV_MODE", "false").lower() == "true"      # nur zum Testen: Diamanten ohne Werbeanbieter
ADS_VERIFY = env("ADS_VERIFY", "false").lower() == "true"     # true = nur per AdsGram Reward-URL bestätigte Werbung zählt
ADSGRAM_SECRET = env("ADSGRAM_SECRET", "")

# Auszahlung je 4-Stunden-Runde: Figuren-Erträge werden voll in USDT gutgeschrieben
# eCPM, Notbremse und Mindest-Videos stehen jetzt in game.DEFAULTS und werden im Admin-Panel (Reiter "Wirtschaft") geändert
MIN_PAYOUT = float(env("MIN_PAYOUT", "1.0"))        # USDT, darunter wird angespart

# CryptoBot
PAYOUT_MODE = env("PAYOUT_MODE", "off")             # off = nur gutschreiben, test = Testnetz, live = echtes Geld
CRYPTOPAY_TOKEN = env("CRYPTOPAY_TOKEN", "")
PAYOUT_ASSET = env("PAYOUT_ASSET", "TRX")            # Auszahlung in TRX (Beträge im Spiel bleiben in $)
TOPUP_ASSETS = env("TOPUP_ASSETS", "ALL")            # womit Spieler bezahlen können: ALL = alle Coins von CryptoBot, sonst z. B. "USDT,TRX"


def pay_assets() -> dict:
    """Leer = CryptoBot bietet alle unterstützten Coins an (USDT, TON, BTC, ETH, LTC, BNB, TRX, USDC)."""
    v = TOPUP_ASSETS.strip().upper()
    return {} if v in ("", "ALL", "*") else {"accepted_assets": v.replace(" ", "")}

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
        CREATE TABLE IF NOT EXISTS pass_buys (
            invoice_id INTEGER PRIMARY KEY, user_id INTEGER, price REAL, currency TEXT, days INTEGER,
            status TEXT, url TEXT, created REAL, paid REAL);
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
                          ("username", "TEXT"),
                          ("awake_until", "REAL NOT NULL DEFAULT 0"), ("last_settle", "REAL NOT NULL DEFAULT 0"),
                          ("coins", "REAL NOT NULL DEFAULT 0"), ("ad_rev", "REAL NOT NULL DEFAULT 0"),
                          ("dia_frac", "REAL NOT NULL DEFAULT 0"), ("skips_day", "TEXT"),
                          ("skips_today", "INTEGER NOT NULL DEFAULT 0"), ("pass_until", "REAL NOT NULL DEFAULT 0")]:
            if col not in cols:   # Spalten für ältere Datenbanken nachrüsten
                con.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        if "awake_until" not in cols:   # Umstellung aufs Wach-System: alle starten wach
            con.execute("UPDATE users SET awake_until=?, last_settle=?", (game.now() + game.CFG["start_awake_hours"] * 3600, game.now()))
        kcols = [r[1] for r in con.execute("PRAGMA table_info(kumpels)")]
        for col, decl in [("xp", "REAL NOT NULL DEFAULT 0"), ("skip_ads", "INTEGER NOT NULL DEFAULT 0")]:
            if col not in kcols:
                con.execute(f"ALTER TABLE kumpels ADD COLUMN {col} {decl}")
                if col == "xp":   # vorhandene Figuren dürfen sofort einmal leveln
                    con.execute("UPDATE kumpels SET xp=3600")
        con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated REAL, by_admin INTEGER)")
        con.execute("DELETE FROM settings WHERE key IN ('coin_share','coin_usd','brake_ratio','brake_grace_usd','brake_dia_per_min')")
        load_settings(con)
        # Coins wurden entfernt: noch vorhandene Coins einmalig in $ gutschreiben (1 Coin = 0,0001 $)
        con.execute("UPDATE users SET usdt=usdt+coins*0.0001, points_total=points_total+coins*0.0001, coins=0 WHERE coins>0")
        pcols = [r[1] for r in con.execute("PRAGMA table_info(payouts)")]
        for col, decl in [("asset", "TEXT"), ("asset_amount", "REAL"), ("rate", "REAL")]:
            if col not in pcols:
                con.execute(f"ALTER TABLE payouts ADD COLUMN {col} {decl}")
        for j in game.JACKPOTS:   # Startpositionen einmalig festlegen (geheim)
            con.execute("INSERT OR IGNORE INTO jackpots (char_id, every, next_pos) VALUES (?,?,?)",
                        (j["char"], j["every"], game.first_jackpot_pos(j["every"])))


def load_settings(con) -> dict:
    """Liest die im Admin-Panel geänderten Wirtschafts-Werte und aktiviert sie."""
    saved = {}
    for r in con.execute("SELECT key, value FROM settings"):
        if r["key"] in game.DEFAULTS:
            try:
                saved.update(game.clean_settings({r["key"]: json.loads(r["value"])}))
            except Exception as e:
                log.warning("Einstellung %s ungültig, Standard wird benutzt: %s", r["key"], e)
    game.apply_settings(saved)
    return saved


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


def ensure_user(con, user_id: int, name: str, ref_by: int | None = None, username: str | None = None,
                source: str = "bot") -> dict:
    """Legt einen Spieler an. Gibt {"new": bool, "referrer": id|None} zurück."""
    if con.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        con.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))
        return {"new": False, "referrer": None}
    valid_ref = bool(ref_by and ref_by != user_id and con.execute("SELECT 1 FROM users WHERE id=?", (ref_by,)).fetchone())
    con.execute("INSERT INTO users (id, name, created, ref_by, awake_until, last_settle) VALUES (?,?,?,?,?,?)",
                (user_id, name, game.now(), ref_by if valid_ref else None,
                 game.now() + game.CFG["start_awake_hours"] * 3600, game.now()))
    if valid_ref:
        con.execute("UPDATE users SET diamonds=diamonds+? WHERE id IN (?,?)", (game.REFERRAL_DIAMONDS, user_id, ref_by))
        events.add(con, ref_by, "invites", 1)
    if game.CFG.get("notify_new_users"):
        total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        ref_name = None
        if valid_ref:
            r = con.execute("SELECT name, username FROM users WHERE id=?", (ref_by,)).fetchone()
            ref_name = f"{r['name'] or 'Spieler'}" + (f" (@{r['username']})" if r["username"] else "") + f" · {ref_by}"
        try:
            asyncio.get_running_loop().create_task(notify_new_user(user_id, name, username, ref_name, total, source))
        except RuntimeError:   # kein laufender Event-Loop (z. B. Tests)
            pass
    return {"new": True, "referrer": ref_by if valid_ref else None}


async def notify_new_user(user_id: int, name: str, username: str | None, ref_name: str | None, total: int, source: str):
    """Meldet dem Besitzer (ADMIN_ID) jeden neuen Spieler."""
    who = html.escape(name or "Spieler") + (f" (@{html.escape(username)})" if username else "")
    text = (f"🆕 <b>Neuer Spieler #{total}</b>\n👤 {who}\n🆔 <code>{user_id}</code>\n"
            f"📍 {'Mini-App' if source == 'app' else '/start im Bot'}\n"
            f"{'👥 eingeladen von ' + html.escape(ref_name) if ref_name else '👥 ohne Einladung'}")
    for owner in sorted(ADMIN_IDS):
        try:
            await bot.send_message(owner, text, parse_mode="HTML")
        except Exception as e:
            log.warning("Neuer-Spieler-Meldung an %s fehlgeschlagen: %s", owner, e)


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
    """Schreibt den Profit aller Figuren bis jetzt gut – nur für die Wachzeit, aufgeteilt auf die 4-Stunden-Runden.
    Wachzeit füllt außerdem die XP."""
    t = t or game.now()
    u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not u:
        return
    awake_end = min(t, max(u["awake_until"], u["pass_until"]))
    per_round: dict[int, float] = {}
    kumpels = con.execute("SELECT * FROM kumpels WHERE user_id=?", (user_id,)).fetchall()
    for k in kumpels:
        if k["last_collect"] >= t:
            continue
        awake = max(0.0, awake_end - k["last_collect"])
        if awake > 0:
            per_sec = game.daily_profit(k["char_id"], k["level"]) / 86400
            for p, secs in game.split_by_period(k["last_collect"], awake_end):
                per_round[p] = per_round.get(p, 0) + per_sec * secs
        xp = min(k["xp"] + awake, max(k["xp"], xp_need(u, k["level"])))
        con.execute("UPDATE kumpels SET last_collect=?, xp=? WHERE user_id=? AND char_id=?", (t, xp, user_id, k["char_id"]))
    con.execute("UPDATE users SET last_settle=? WHERE id=?", (t, user_id))
    total = 0.0
    for p, pts in per_round.items():
        total += pts
        con.execute("""INSERT INTO round_points (user_id, period, points) VALUES (?,?,?)
                       ON CONFLICT(user_id, period) DO UPDATE SET points=points+excluded.points""", (user_id, p, pts))
    if total:
        con.execute("UPDATE users SET points_total=points_total+? WHERE id=?", (total, user_id))
        events.add(con, user_id, "profit", total, t)


def has_pass(u, t: float | None = None) -> bool:
    """Komfort-Pass aktiv: alle Buddies dauerhaft wach, keine XP-Wartezeit."""
    return u["pass_until"] > (t or game.now())


def xp_need(u, level: int) -> int:
    return 0 if has_pass(u) else game.xp_wait(level)


def wake_info(u, t: float) -> dict:
    until = max(u["awake_until"], u["pass_until"])
    left = max(0.0, until - t)
    per = game.CFG["wake_hours"] * 3600
    room = game.CFG["wake_max_hours"] * 3600 - left
    return {"awake_until": until, "awake_left": left, "wake_hours": game.CFG["wake_hours"],
            "wake_max_hours": game.CFG["wake_max_hours"], "wake_videos_to_full": max(0, math.ceil(room / per - 0.01)) if per else 0,
            "wake_full": room < 60, "pass_until": u["pass_until"], "pass_active": has_pass(u, t),
            "pass_price_eur": game.CFG["pass_price_eur"], "pass_days": game.CFG["pass_days"],
            "pass_open": None}


def econ_view() -> dict:
    """Zahlen, die die App für Anzeigen braucht (Verdienst-Übersicht, Kosten, Chancen)."""
    c = game.CFG
    return {"bases": {ch["id"]: game.base_daily(ch["id"]) for ch in game.CHARACTERS},
            "mult": [c["mult_mid_level"], c["mult_mid"], c["mult_max"]],
            "packs": {k: game.PACKS[k] for k in ("start", "bronze", "silber", "gold")},
            "xp_band": c["xp_band"], "xp_waits": c["xp_waits"], "skip_limits": c["skip_limits"],
            }


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
        need = xp_need(u, lvl) if lvl < game.MAX_LEVEL else 0
        rest = max(0.0, need - k["xp"])
        kumpels.append({
            "id": k["char_id"], "level": lvl, "copies": k["copies"],
            "daily": game.daily_profit(k["char_id"], lvl),
            "next_daily": game.daily_profit(k["char_id"], lvl + 1) if lvl < game.MAX_LEVEL else None,
            "level_cost": game.level_cost(k["char_id"], lvl) if lvl < game.MAX_LEVEL else None,
            "xp": min(k["xp"], need), "xp_need": need, "skip_ads": k["skip_ads"],
            "skip_videos": game.skip_videos(rest) if rest > 0 else 0,
        })
    skips_today = u["skips_today"] if u["skips_day"] == today else 0
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
        "eligible": ads_last_24h(con, user_id, t) >= game.CFG["min_ads_24h"],
        "last_round": dict(last) if last else None,
        "streak": u["streak"] if u["last_daily"] in (today, yesterday) else 0,
        "daily_available": u["last_daily"] != today,
        "ads_today": ads_today, "next_ad_at": u["last_ad"] + game.ad_cooldown(), "ad_cooldown": game.ad_cooldown(),
        "next_ad_reward": game.ad_reward(ads_today),
        "starter_available": not u["starter_used"],
        "friends": con.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,)).fetchone()[0],
        "ref_earned": round(u["ref_earned"], 6), "ref_share": game.REFERRAL_SHARE, "ref_diamonds": game.REFERRAL_DIAMONDS,
        "kumpels": kumpels, "payouts": payouts, "top": top,
        "min_payout": MIN_PAYOUT, "payout_asset": PAYOUT_ASSET, "payout_mode": PAYOUT_MODE, "min_ads_24h": game.CFG["min_ads_24h"],
        **wake_info(u, t), "pass_open": (lambda r: dict(r) if r else None)(con.execute(
            "SELECT invoice_id, url FROM pass_buys WHERE user_id=? AND status='active' AND created>? ORDER BY created DESC LIMIT 1",
            (user_id, t - 3600)).fetchone()),
        "skips_today": skips_today, "skips_max": game.CFG["skip_max_day"], "skip_diamonds": game.CFG["skip_diamonds"],
        "econ": econ_view(),
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
        "richads": {"pub": RICHADS_PUB_ID, "app": RICHADS_APP_ID} if (RICHADS_PUB_ID and RICHADS_APP_ID) else None,
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
    level, diamonds, spent, done, xp = k["level"], u["diamonds"], 0, 0, k["xp"]
    steps = max(1, min(int(steps or 1), game.MAX_LEVEL))
    why = "no_diamonds"
    while done < steps and level < game.MAX_LEVEL:
        need = xp_need(u, level)
        if xp < need:   # XP noch nicht voll
            why = "xp_wait"
            break
        cost = game.level_cost(char, level)
        if diamonds - spent < cost:
            why = "no_diamonds"
            break
        spent += cost; level += 1; done += 1; xp = 0.0
    if not done:
        if level >= game.MAX_LEVEL:
            raise E(400, "max_level")
        raise E(400, why, m=math.ceil((xp_need(u, level) - xp) / 60))
    con.execute("UPDATE users SET diamonds=diamonds-? WHERE id=?", (spent, user_id))
    con.execute("UPDATE kumpels SET level=?, xp=?, skip_ads=0 WHERE user_id=? AND char_id=?", (level, xp, user_id, char))
    return {"levels": done, "spent": spent}


def act_ad(con, user_id, u, purpose="diamonds", char=None):
    """Ein gesehenes Video. purpose: diamonds (💎), wake (alle Buddies +2,4 Std wach, keine 💎),
    skip (XP einer Figur sofort füllen, gibt 💎)."""
    t = game.now()
    cfg = game.CFG
    today = date.today().isoformat()
    if not (ADSGRAM_BLOCK_ID or MONETAG_ZONE_ID or RICHADS_PUB_ID or DEV_MODE):   # ohne Werbeanbieter keine Diamanten
        raise E(400, "ads_off")
    if purpose not in ("diamonds", "wake", "skip"):
        raise E(400, "unknown_action")
    if t < u["last_ad"] + game.ad_cooldown():
        raise E(400, "ad_wait", s=int(u['last_ad'] + game.ad_cooldown() - t) + 1)
    k = None
    skips_today = u["skips_today"] if u["skips_day"] == today else 0
    if purpose == "wake" and wake_info(u, t)["wake_full"]:
        raise E(400, "wake_full", h=cfg["wake_max_hours"])
    if purpose == "skip":
        k = con.execute("SELECT * FROM kumpels WHERE user_id=? AND char_id=?", (user_id, char)).fetchone()
        if not k:
            raise E(400, "no_figure")
        if k["level"] >= game.MAX_LEVEL or k["xp"] >= xp_need(u, k["level"]):
            raise E(400, "xp_full")
        if skips_today >= cfg["skip_max_day"]:
            raise E(400, "skip_limit", n=cfg["skip_max_day"])
    if ADS_VERIFY:   # nur von AdsGram bestätigte Ansichten der letzten 2 Minuten zählen
        row = con.execute("SELECT id FROM ad_views WHERE user_id=? AND source='s2s' AND used=0 AND ts>? ORDER BY ts LIMIT 1",
                          (user_id, t - 120)).fetchone()
        if not row:
            raise E(400, "ad_unconfirmed")
        con.execute("UPDATE ad_views SET used=1 WHERE id=?", (row["id"],))
    else:
        con.execute("INSERT INTO ad_views (user_id, ts, period, source, used) VALUES (?,?,?,?,1)",
                    (user_id, t, game.period_of(t), "client"))
    ads_today = u["ads_today"] if u["ads_day"] == today else 0
    rev = game.ad_revenue()
    con.execute("UPDATE users SET last_ad=?, ads_day=?, ads_today=?, ad_rev=ad_rev+? WHERE id=?",
                (t, today, ads_today + 1, rev, user_id))
    events.add(con, user_id, "ads", 1, t)
    res = {"purpose": purpose, "diamonds": 0}
    if purpose == "diamonds":
        res["diamonds"] = game.ad_reward(ads_today)
    elif purpose == "wake":
        new = min(max(t, u["awake_until"]) + cfg["wake_hours"] * 3600, t + cfg["wake_max_hours"] * 3600)
        con.execute("UPDATE users SET awake_until=? WHERE id=?", (new, user_id))
        res["awake_until"] = new
    else:
        res["diamonds"] = int(cfg["skip_diamonds"])
        need = game.xp_wait(k["level"])
        watched = k["skip_ads"] + 1
        if watched >= game.skip_videos(need - k["xp"]):   # genug Videos → XP voll
            con.execute("UPDATE kumpels SET xp=?, skip_ads=0 WHERE user_id=? AND char_id=?", (need, user_id, char))
            con.execute("UPDATE users SET skips_day=?, skips_today=? WHERE id=?", (today, skips_today + 1, user_id))
            res["filled"] = True
        else:
            con.execute("UPDATE kumpels SET skip_ads=? WHERE user_id=? AND char_id=?", (watched, user_id, char))
            res["filled"] = False
    if res["diamonds"]:
        con.execute("UPDATE users SET diamonds=diamonds+? WHERE id=?", (res["diamonds"], user_id))
    return res


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
        "currency_type": "fiat", "fiat": "USD", **pay_assets(),   # Rechnung in $, bezahlt mit beliebigem Coin
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


async def act_buy_pass(user_id: int) -> dict:
    """Rechnung für den Komfort-Pass (in Euro, bezahlt mit beliebigem Coin über CryptoBot)."""
    if not SHOP_ENABLED or not CRYPTOPAY_TOKEN:
        raise E(400, "topup_off")
    price, days = game.CFG["pass_price_eur"], game.CFG["pass_days"]
    with db() as con:   # offene Rechnung wiederverwenden statt neue anzulegen
        row = con.execute("SELECT invoice_id, url FROM pass_buys WHERE user_id=? AND status='active' AND created>? AND price=?",
                          (user_id, game.now() - 3000, price)).fetchone()
    if row:
        return {"url": row["url"], "invoice_id": row["invoice_id"]}
    res = await cryptopay("createInvoice", {
        "currency_type": "fiat", "fiat": "EUR", **pay_assets(),
        "amount": f"{price:.2f}", "payload": f"pass:{user_id}",
        "description": tr(user_lang(user_id), "pass_desc", days=days), "expires_in": 3600,
        "allow_comments": False, "allow_anonymous": False})
    if not res.get("ok"):
        raise E(502, "cryptobot_down")
    inv = res["result"]
    url = inv.get("mini_app_invoice_url") or inv.get("bot_invoice_url") or inv.get("pay_url")
    with db() as con:
        con.execute("INSERT INTO pass_buys (invoice_id, user_id, price, currency, days, status, url, created) VALUES (?,?,?,?,?,?,?,?)",
                    (inv["invoice_id"], user_id, price, "EUR", days, "active", url, game.now()))
    return {"url": url, "invoice_id": inv["invoice_id"]}


def grant_pass(con, user_id: int, days: int) -> float:
    """Pass gutschreiben/verlängern. Vorher abrechnen, damit die Zeit vor dem Kauf nicht als wach zählt."""
    settle(con, user_id)
    u = con.execute("SELECT pass_until FROM users WHERE id=?", (user_id,)).fetchone()
    until = max(game.now(), u["pass_until"]) + days * 86400
    con.execute("UPDATE users SET pass_until=? WHERE id=?", (until, user_id))
    return until


def credit_pass(con, invoice_id: int) -> int | None:
    """Schreibt einen bezahlten Pass genau einmal gut. Gibt die user_id zurück."""
    row = con.execute("SELECT * FROM pass_buys WHERE invoice_id=?", (invoice_id,)).fetchone()
    if not row or row["status"] == "paid":
        return None
    con.execute("UPDATE pass_buys SET status='paid', paid=? WHERE invoice_id=?", (game.now(), invoice_id))
    grant_pass(con, row["user_id"], row["days"])
    log.info("KOMFORT-PASS an Spieler %s (%s Tage)", row["user_id"], row["days"])
    return row["user_id"]


async def check_passes(user_id: int | None = None) -> int:
    if not CRYPTOPAY_TOKEN:
        return 0
    with db() as con:
        q, args = "SELECT invoice_id FROM pass_buys WHERE status='active' AND created>?", [game.now() - 2 * 3600]
        if user_id:
            q += " AND user_id=?"; args.append(user_id)
        ids = [r[0] for r in con.execute(q, args)]
    if not ids:
        return 0
    res = await cryptopay("getInvoices", {"invoice_ids": ",".join(map(str, ids))})
    n = 0
    with db() as con:
        for inv in (res.get("result") or {}).get("items", []):
            if inv.get("status") == "paid" and credit_pass(con, inv["invoice_id"]):
                n += 1
            elif inv.get("status") == "expired":
                con.execute("UPDATE pass_buys SET status='expired' WHERE invoice_id=?", (inv["invoice_id"],))
    return n


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


APP_VERSION = "2026-11-08.6"


@app.get("/version")
async def version():
    """Zeigt, welche Code-Version auf dem Server läuft (zur Kontrolle nach einem Deploy)."""
    return {"version": APP_VERSION,
            "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7] or "unbekannt",
            "commit_message": os.environ.get("RAILWAY_GIT_COMMIT_MESSAGE", "")[:80],
            "promo": (BASE / "webapp" / "promo").is_dir(),
            "ads": ad_providers() or "keine"}


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
    if data.get("update_type") == "invoice_paid" and str(inv.get("payload", "")).startswith("pass:"):
        with db() as con:
            uid = credit_pass(con, int(inv["invoice_id"]))
            until = con.execute("SELECT pass_until FROM users WHERE id=?", (uid,)).fetchone()[0] if uid else 0
        if uid:
            try:
                await bot.send_message(uid, tr(user_lang(uid), "pass_ok", date=datetime.fromtimestamp(until).strftime("%d.%m.%Y")))
            except Exception:
                pass
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
        await check_passes(user_id)
        action = "state"
    if action == "buy_pass":
        return await act_buy_pass(user_id)

    with db() as con:
        joined = ensure_user(con, user_id, name, parse_ref(start_param), tg_user.get("username"), "app")   # Einladung auch beim direkten App-Start
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
            result = act_ad(con, user_id, u, body.get("purpose", "diamonds"), body.get("char"))
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
                      "ads": ad_providers() or "–", "ecpm": game.CFG["ecpm_usd"]}
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
        # ---------------- Wirtschaft
        if action == "econ_get":
            with db() as con:
                saved = {r["key"] for r in con.execute("SELECT key FROM settings")}
                ads7 = con.execute("SELECT COUNT(*) FROM ad_views WHERE ts>?", (game.now() - 7 * 86400,)).fetchone()[0]
                awake_n = con.execute("SELECT COUNT(*) FROM users WHERE awake_until>? OR pass_until>?", (game.now(), game.now())).fetchone()[0]
                passes_n = con.execute("SELECT COUNT(*) FROM users WHERE pass_until>?", (game.now(),)).fetchone()[0]
                passes_sold = con.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM pass_buys WHERE status='paid'").fetchone()
            return {"defaults": game.DEFAULTS, "values": game.CFG, "changed": sorted(saved),
                    "info": {"ads_7d": ads7, "awake_now": awake_n, "passes_active": passes_n,
                             "passes_sold": passes_sold[0], "passes_eur": round(passes_sold[1], 2)}}
        if action == "econ_set":
            owner_only()
            try:
                vals = game.clean_settings(body.get("values") or {})
            except ValueError as e:
                raise HTTPException(400, str(e))
            with db() as con:
                for k, v in vals.items():
                    if v == game.DEFAULTS[k]:
                        con.execute("DELETE FROM settings WHERE key=?", (k,))
                    else:
                        con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", (k, json.dumps(v), game.now(), admin_id))
                load_settings(con)
            log_action("econ_set", details=vals)
            return {"ok": True, "values": game.CFG}
        if action == "econ_reset":
            owner_only()
            with db() as con:
                con.execute("DELETE FROM settings")
                load_settings(con)
            log_action("econ_reset")
            return {"ok": True, "values": game.CFG}
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
                                          "created", "last_seen", "lang", "blocked", "collection_bonus", "pass_until")}
                prof["friends"] = con.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (uid,)).fetchone()[0]
                prof["is_admin"] = is_admin(uid, con)
                prof["log"] = [dict(r) for r in con.execute(
                    "SELECT admin_id, action, details, ts FROM admin_log WHERE target=? ORDER BY id DESC LIMIT 10", (uid,))]
            return {"user": prof, "kumpels": ks}
        if action == "user_pass":   # Komfort-Pass manuell vergeben (Tage > 0) oder entfernen (0)
            uid, days = int(body["id"]), int(body.get("days", 0))
            with db() as con:
                if not con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                    raise ValueError("Spieler nicht gefunden")
                if days > 0:
                    until = grant_pass(con, uid, days)
                else:
                    settle(con, uid)
                    con.execute("UPDATE users SET pass_until=0 WHERE id=?", (uid,))
                    until = 0
            log_action("user_pass", uid, {"days": days})
            if days > 0 and body.get("notify"):
                try:
                    await bot.send_message(uid, tr(user_lang(uid), "pass_ok", date=datetime.fromtimestamp(until).strftime("%d.%m.%Y")))
                except Exception:
                    pass
            return {"ok": True, "pass_until": until}
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
            revenue = views * game.ad_revenue()
            min_ads, cap = game.CFG["min_ads_24h"], game.CFG["max_payout_per_round"]
            rows = [r for r in con.execute("SELECT user_id, points FROM round_points WHERE period=? AND points>0", (p,))
                    if not min_ads or ads_last_24h(con, r["user_id"], end) >= min_ads]
            total = sum(r["points"] for r in rows)
            factor = 1.0
            if cap > 0 and total > cap:   # Notbremse
                factor = cap / total
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
        joined = ensure_user(con, u.id, u.first_name, parse_ref(command.args), u.username, "bot")
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
            ensure_user(con, q.from_user.id, q.from_user.first_name, None, q.from_user.username)
            con.execute("UPDATE users SET lang=? WHERE id=?", (lang, q.from_user.id))
        await q.message.answer(tr(lang, "lang_set"), reply_markup=play_keyboard(lang))
    await q.answer()


@dp.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Deine Telegram-ID / Your Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    with db() as con:
        ensure_user(con, message.from_user.id, message.from_user.first_name, None, message.from_user.username)
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


def ad_providers() -> str:
    """Reihenfolge, in der die App Werbung versucht."""
    p = []
    if ADSGRAM_BLOCK_ID.strip().isdigit():
        p.append("AdsGram")
    if RICHADS_PUB_ID and RICHADS_APP_ID:
        p.append("RichAds")
    if MONETAG_ZONE_ID:
        p.append("Monetag")
    return " → ".join(p)


def check_config() -> None:
    """Prüft beim Start die wichtigsten Einstellungen und meldet Probleme deutlich im Log."""
    problems = []
    if not WEBAPP_URL.startswith("https://"):
        problems.append("WEBAPP_URL fehlt oder ist nicht https – die Mini App lässt sich nicht öffnen")
    if not (ADSGRAM_BLOCK_ID or MONETAG_ZONE_ID or RICHADS_PUB_ID):
        problems.append("Kein Werbeanbieter (ADSGRAM_BLOCK_ID / RICHADS_PUB_ID / MONETAG_ZONE_ID) – Videos und Diamanten sind gesperrt")
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
    log.info("Start: Version %s (Commit %s), Auszahlung=%s (%s), Shop=%s, Werbung=%s", APP_VERSION,
             os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7] or "?", PAYOUT_MODE, PAYOUT_ASSET,
             "an" if SHOP_ENABLED else "aus", ad_providers() or "keine")


async def main():
    check_config()
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info"))
    await asyncio.gather(server.serve(), run_bot(), payout_loop(), events_loop())


if __name__ == "__main__":
    asyncio.run(main())
