"""Spielregeln von Crypto Buddies. Alle Zahlen zum Einstellen stehen hier oben."""
import json
import math
import random
import time
from pathlib import Path

# ---------------------------------------------------------------- Einstellungen
MAX_LEVEL = 500
PERIOD_SECONDS = 4 * 60 * 60          # Auszahlungsrunde: alle 4 Stunden

# ---------------------------------------------------------------- Wirtschaft (im Admin-Panel änderbar)
# Diese Werte sind die Standards. Im Admin-Panel (Reiter "Wirtschaft") geänderte Werte werden in der
# Datenbank gespeichert und überschreiben sie – ohne neues Deployment.
DEFAULTS = {
    "ecpm_usd": 2.48,             # Einnahmen pro 1.000 Videos in $
    # Verdienst: Grundwert = alter Grundwert / base_divisor, steigt gleichmäßig: bis Stufe mult_mid_level auf mult_mid,
    # danach bis Stufe 500 auf mult_max. Standard: eine gerade Linie von 1 auf 389,25 (Stufe 500 = 25,95 × alter Grundwert)
    "base_divisor": 15.0,
    "mult_mid_level": 300, "mult_mid": 233.637, "mult_max": 389.25,
    # Level-Kosten: (2 + 0,15 × Stufe) × Faktor; bis Stufe cost_easy_until × cost_easy_mult (leichter Einstieg);
    # Lava/Gold/Kosmos/Jackpot × cost_block_mult je 100er-Block; ab Stufe cost_high_from zusätzlich × cost_high_mult
    "cost_f_klassik": 1.0, "cost_f_frost": 1.25, "cost_f_lava": 1.5, "cost_f_gold": 2.0, "cost_f_kosmos": 2.5,
    "cost_easy_until": 100, "cost_easy_mult": 0.5,
    "cost_block_mult": 1.0, "cost_high_from": 300, "cost_high_mult": 1.0,
    # Packs: Preis und Chancen in Prozent
    "packs": {
        "bronze": {"price": 40,  "odds": {"klassik": 75.45, "frost": 20, "lava": 4,  "gold": 0.45, "kosmos": 0.1}},
        "silber": {"price": 100, "odds": {"klassik": 47.4,  "frost": 35, "lava": 15, "gold": 2.4,  "kosmos": 0.2}},
        "gold":   {"price": 200, "odds": {"frost": 57.35, "lava": 35, "gold": 7.35, "kosmos": 0.3}},
    },
    # Werbung
    "ad_diamonds": 2,             # 💎 pro normalem Video
    "ad_cooldown": 45,            # Sekunden zwischen zwei Videos
    # Wach-System: Buddies verdienen und sammeln XP nur, solange sie wach sind
    "wake_hours": 2.4,            # Stunden wach pro Wach-Video (für alle Buddies, ohne Diamanten)
    "wake_max_hours": 24,         # höchstens so viele Stunden auf Vorrat
    "start_awake_hours": 1,       # neue Spieler starten so lange wach
    # XP-Wartezeit vor jedem Level: Minuten je 10er-Stufenblock (Stufe 1–9, 10–19, … letzter Wert gilt danach)
    "xp_band": 10, "xp_waits": [0, 0, 1, 1, 2, 2, 3, 3, 5, 5] + [10] * 10 + [15] * 10 + [20],
    "skip_limits": [20, 40, 60],  # Restzeit bis … Min → 1 / 2 / 3 Videos zum Sofort-Füllen
    "skip_max_day": 30,           # Sofort-Füllen pro Tag
    "skip_diamonds": 2,           # 💎 pro Skip-Video
    # Komfort-Pass (Kauf über CryptoBot): alle Buddies dauerhaft wach, keine XP-Wartezeit
    "pass_price_eur": 9.99, "pass_days": 365,
    # Premium-Shop (Kauf über CryptoBot, Preise in $) – Normalpreise
    "shop_gold_pack_usd": 59.99,  # garantiert ein Gold-Buddy
    "shop_epic_pack_usd": 119.99, # garantiert ein Kosmos-Buddy
    "shop_boost_usd": 19.99,      # Level-Boost lebenslang: jedes Level kostet nur 1/boost_divisor der Diamanten
    "boost_divisor": 3.0,
    "max_level_usd": {"klassik": 7.99, "frost": 19.99, "lava": 119.99, "gold": 599.99, "kosmos": 1999.99},
    # Willkommens-Angebot: neue Spieler bekommen in den ersten welcome_days Tagen einmalig Rabatt (nicht auf Boost/Pass)
    "welcome_discount": 0.75, "welcome_days": 7,
    # Gebundener Willkommensbonus: neue Spieler können ihn einmal annehmen; frei (auf die Balance), sobald
    # Bonus + verdientes Guthaben welcome_bonus_target erreichen – bis dahin keine Auszahlung
    "welcome_bonus_usd": 15.0, "welcome_bonus_target": 25.0,
    # Sammel-Bonus: einmalig für alle normalen Buddies, ohne Zeitlimit
    "collection_bonus_usd": 300.0,
    # Sonstiges
    "notify_new_users": 1,        # 1 = Besitzer (ADMIN_ID) bekommt bei jedem neuen Spieler eine Nachricht, 0 = aus
    "min_ads_24h": 0,             # alte Regel: Videos in 24 h für die Rundenauszahlung (0 = aus, das Wach-System ersetzt sie)
    "max_payout_per_round": 0.0,  # Notbremse in $ pro Runde (0 = keine)
}
CFG: dict = json.loads(json.dumps(DEFAULTS))


def _same_type(default, value):
    """Wandelt einen Wert aus dem Admin-Panel in den Typ des Standardwerts um (Fehler bei Unsinn)."""
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        v = int(float(value))
        if v < 0:
            raise ValueError("negativ")
        return v
    if isinstance(default, float):
        v = float(value)
        if v < 0 or v != v:
            raise ValueError("negativ")
        return v
    if isinstance(default, list):
        if isinstance(value, str):
            value = json.loads(value) if value.strip().startswith("[") else [x for x in value.replace(";", ",").split(",") if x.strip()]
        out = [float(x) for x in value]
        if not out or min(out) < 0:
            raise ValueError("Liste leer oder negativ")
        return [int(x) if x == int(x) else x for x in out]
    if isinstance(default, dict):
        if isinstance(value, str):
            value = json.loads(value)
        return value
    return value


def check_packs(packs: dict) -> dict:
    out = {}
    for k in ("bronze", "silber", "gold"):
        p = packs[k]
        odds = {e: float(w) for e, w in p["odds"].items() if float(w) > 0}
        if not odds or any(e not in EDITION_USD for e in odds):
            raise ValueError(f"Pack {k}: unbekannte Edition")
        if abs(sum(odds.values()) - 100) > 0.05:
            raise ValueError(f"Pack {k}: Chancen ergeben {sum(odds.values()):.2f} % statt 100 %")
        out[k] = {"price": int(p["price"]), "odds": odds}
    return out


def clean_settings(values: dict) -> dict:
    """Prüft geänderte Werte. Unbekannte Schlüssel → Fehler."""
    out = {}
    for k, v in values.items():
        if k not in DEFAULTS:
            raise ValueError(f"Unbekannte Einstellung {k}")
        try:
            out[k] = _same_type(DEFAULTS[k], v)
        except Exception as e:
            raise ValueError(f"{k}: ungültiger Wert ({e})")
        if k == "packs":
            out[k] = check_packs(out[k])
        if k == "max_level_usd":
            d = out[k]
            if set(d) - set(EDITION_USD) or any(float(v) <= 0 for v in d.values()):
                raise ValueError("max_level_usd: nur klassik/frost/lava/gold/kosmos mit Preis > 0")
            out[k] = {e: round(float(v), 2) for e, v in d.items()}
    return out


def apply_settings(overrides: dict) -> None:
    """Setzt die aktiven Werte = Standard + gespeicherte Änderungen."""
    CFG.clear()
    CFG.update(json.loads(json.dumps(DEFAULTS)))
    for k, v in overrides.items():
        if k in DEFAULTS:
            CFG[k] = v
    for k, p in CFG["packs"].items():
        PACKS[k] = {"name": PACKS.get(k, {}).get("name", k), "price": p["price"], "odds": dict(p["odds"])}

# Tagesprofit in US-Dollar auf Stufe 1: (von, bis) je Edition – die 20 Tierarten liegen gleichmäßig dazwischen
EDITION_USD = {
    "klassik": (0.001, 0.002),
    "frost":   (0.004, 0.008),
    "lava":    (0.015, 0.030),
    "gold":    (0.060, 0.120),
    "kosmos":  (0.300, 0.500),        # Epic
}
PREMIUM_EDITIONS = ("lava", "gold", "kosmos")   # Level-Kosten verdoppeln sich je 100er-Block
DUPLICATE_REFUND = 0.40               # Doppelte Figur: 40 % der Pack-Kosten als Diamanten zurück

# Packs: Preis in Diamanten und Chancen je Edition (Prozent, Summe 100) – Bronze/Silber/Gold kommen aus CFG["packs"]
PACKS = {
    "start":  {"name": "Start-Pack",  "price": 0,   "odds": {"klassik": 100}},
    "bronze": {"name": "Bronze-Pack"}, "silber": {"name": "Silber-Pack"}, "gold": {"name": "Gold-Pack"},
}

# Jackpot-Figuren: fester Tagesertrag auf Stufe 1, vergeben über den Zähler aller geöffneten Packs (ohne Start-Pack).
# JACKPOT_MODE "block": genau 1 Treffer in jedem Block von `every` Packs, an zufälliger, geheimer Stelle (Schutz vor Bots)
#              "exact": immer genau das every-te, 2×every-te … Pack
JACKPOT_MODE = "block"
JACKPOTS = [
    {"char": "pablo_panda",   "usd": 5,  "every": 525_000},
    {"char": "kasimir_krake", "usd": 10, "every": 1_400_000},
    {"char": "ludwig_loewe",  "usd": 25, "every": 4_925_000},
    {"char": "dorian_drache", "usd": 50, "every": 19_882_000},
]
JACKPOT_USD = {j["char"]: j["usd"] for j in JACKPOTS}

# Sammel-Bonus: wer alle normalen Figuren (ohne Jackpots) besitzt, bekommt einmalig diesen Betrag gutgeschrieben


def refund(pack: str) -> int:
    """Diamanten zurück bei einer doppelten Figur."""
    return int(PACKS[pack]["price"] * DUPLICATE_REFUND)

# Diamanten durch Werbung: unbegrenzt, mit Pause zwischen zwei Videos (Werte in CFG)
def ad_reward(ads_today: int = 0) -> int:
    return int(CFG["ad_diamonds"])


def ad_cooldown() -> int:
    return int(CFG["ad_cooldown"])


def ad_revenue() -> float:
    """Geschätzte Einnahme pro Video in $."""
    return CFG["ecpm_usd"] / 1000

DAILY_STEP = 1                        # Tagesbonus = Serientag × 1 → Tag 1: 1 💎 … Tag 7: 7 💎
REFERRAL_DIAMONDS = 5                 # für Einlader und Eingeladenen
REFERRAL_SHARE = 0.20                 # Einlader bekommt zusätzlich 20 % der Einnahmen seiner geworbenen Freunde (on top)

# Diamanten kaufen mit Guthaben/Einzahlung
DIAMONDS_PER_USDT = 100               # 100 💎 = 1 USDT
TOPUP_AMOUNTS = [1, 5, 10, 25]        # Aufladebeträge in USDT (CryptoBot)

# Diamanten-Shop mit Telegram Stars: Diamanten → Preis in Stars
STAR_PACKAGES = {"d100": (100, 50), "d550": (550, 250), "d1200": (1200, 500)}

# ---------------------------------------------------------------- Figuren
CHARACTERS = json.loads((Path(__file__).parent / "characters.json").read_text(encoding="utf-8"))
BY_ID = {c["id"]: c for c in CHARACTERS}
BY_EDITION: dict[str, list[str]] = {}          # normale Ziehung – ohne Jackpot-Figuren
for _c in CHARACTERS:
    if _c["id"] not in JACKPOT_USD:
        BY_EDITION.setdefault(_c["edition"], []).append(_c["id"])
assert all(j in BY_ID for j in JACKPOT_USD), "Jackpot-Figur nicht gefunden"
REGULAR_IDS = [c["id"] for c in CHARACTERS if c["id"] not in JACKPOT_USD]     # die 96 Sammel-Figuren
REGULAR_SET = set(REGULAR_IDS)


def raw_base(char_id: str) -> float:
    """Ursprünglicher Tageswert auf Stufe 1 (Bezugsgröße)."""
    if char_id in JACKPOT_USD:
        return JACKPOT_USD[char_id]
    c = BY_ID[char_id]
    lo, hi = EDITION_USD[c["edition"]]
    species_idx = (c["no"] - 1) % 20          # 0 … 19
    return lo + (hi - lo) * species_idx / 19


def base_daily(char_id: str) -> float:
    """US-Dollar pro Tag auf Stufe 1."""
    return raw_base(char_id) / CFG["base_divisor"]


def multiplier(level: int) -> float:
    """Ertrags-Faktor einer Stufe: bis mult_mid_level langsam, danach steil bis Stufe 500."""
    mid_l, mid, top = CFG["mult_mid_level"], CFG["mult_mid"], CFG["mult_max"]
    if level <= mid_l:
        return 1 + (mid - 1) * (level - 1) / max(1, mid_l - 1)
    return mid + (top - mid) * (level - mid_l) / max(1, MAX_LEVEL - mid_l)


def daily_profit(char_id: str, level: int) -> float:
    """US-Dollar pro Tag einer Figur auf einer Stufe."""
    return round(base_daily(char_id) * multiplier(level), 6)


def cost_factor(char_id: str) -> float:
    if char_id in JACKPOT_USD:   # Jackpots: Kosmos-Faktor × (Jackpot-Wert / mittlerer Kosmos-Wert)
        kos = [raw_base(i) for i in BY_EDITION["kosmos"]]
        return CFG["cost_f_kosmos"] * JACKPOT_USD[char_id] / (sum(kos) / len(kos))
    return CFG["cost_f_" + BY_ID[char_id]["edition"]]


def level_cost(char_id: str, level: int, boost: bool = False) -> int:
    """Diamanten für den Schritt von `level` auf `level + 1` (mit Level-Boost nur ein Bruchteil)."""
    c = (2 + 0.15 * level) * cost_factor(char_id)
    if level <= CFG["cost_easy_until"]:
        c *= CFG["cost_easy_mult"]
    c = math.ceil(c)
    if char_id in JACKPOT_USD or BY_ID[char_id]["edition"] in PREMIUM_EDITIONS:
        c = math.ceil(c * CFG["cost_block_mult"] ** ((level - 1) // 100))
    if level > CFG["cost_high_from"]:
        c = math.ceil(c * CFG["cost_high_mult"])
    if boost and CFG["boost_divisor"] > 0:
        c = math.ceil(c / CFG["boost_divisor"])
    return max(1, c)


def sale_price(usd: float) -> float:
    """Willkommens-Preis, abgerundet auf ,99 (59,99 → 14,99)."""
    x = usd * (1 - CFG["welcome_discount"])
    return round(max(0.99, math.floor(x + 0.01) - 0.01), 2)


def xp_wait(level: int) -> int:
    """Sekunden Wachzeit, die eine Figur vor dem Schritt von `level` auf `level + 1` sammeln muss."""
    waits = CFG["xp_waits"]
    return int(round(waits[min(level // max(1, CFG["xp_band"]), len(waits) - 1)] * 60))


def skip_videos(remaining_s: float) -> int:
    """Videos, um die restliche XP-Zeit sofort zu füllen."""
    lim = CFG["skip_limits"]
    for i, m in enumerate(lim):
        if remaining_s <= m * 60:
            return i + 1
    return len(lim) + math.ceil((remaining_s - lim[-1] * 60) / (20 * 60))


def first_jackpot_pos(every: int, rng=None) -> int:
    """Stelle des ersten Treffers (Zählung ab 1)."""
    if JACKPOT_MODE == "exact":
        return every
    return (rng or random.SystemRandom()).randint(1, every)


def next_jackpot_pos(pos: int, every: int, rng=None) -> int:
    """Stelle des nächsten Treffers nach einem Treffer an `pos`."""
    if JACKPOT_MODE == "exact":
        return pos + every
    block_start = ((pos - 1) // every + 1) * every + 1
    return block_start + (rng or random.SystemRandom()).randint(0, every - 1)


def pull(pack: str, rng: random.Random | None = None) -> str:
    """Zieht eine zufällige Figur aus einem Pack."""
    rng = rng or random.SystemRandom()
    odds = PACKS[pack]["odds"]
    edition = rng.choices(list(odds), weights=list(odds.values()))[0]
    return rng.choice(BY_EDITION[edition])


# ---------------------------------------------------------------- Zeit & Runden
def now() -> float:
    return time.time()

def period_of(t: float) -> int:
    return int(t // PERIOD_SECONDS)

def period_end(p: int) -> float:
    return (p + 1) * PERIOD_SECONDS

def split_by_period(a: float, b: float):
    """Teilt den Zeitraum [a, b] an den Rundengrenzen: liefert (runde, sekunden)."""
    while a < b:
        p = period_of(a)
        end = min(b, period_end(p))
        yield p, end - a
        a = end


apply_settings({})
