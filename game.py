"""Spielregeln von Crypto Buddies. Alle Zahlen zum Einstellen stehen hier oben."""
import json
import math
import random
import time
from pathlib import Path

# ---------------------------------------------------------------- Einstellungen
MAX_LEVEL = 500
PERIOD_SECONDS = 4 * 60 * 60          # Auszahlungsrunde: alle 4 Stunden

# Tagesprofit in US-Dollar auf Stufe 1: (von, bis) je Edition – die 20 Tierarten liegen gleichmäßig dazwischen
EDITION_USD = {
    "klassik": (0.001, 0.002),
    "frost":   (0.004, 0.008),
    "lava":    (0.015, 0.030),
    "gold":    (0.060, 0.120),
    "kosmos":  (0.300, 0.500),        # Epic
}
PROFIT_PER_LEVEL = 0.05               # jede Stufe +5 % vom Grundprofit (Stufe 500 = 25,95 ×)

# Diamanten pro Stufe: (2 + 0,15 × Stufe) × Seltenheits-Faktor, aufgerundet
LEVEL_COST_FACTOR = {"klassik": 1.0, "frost": 1.25, "lava": 1.5, "gold": 2.0, "kosmos": 2.5}
DUPLICATE_REFUND = 0.40               # Doppelte Figur: 40 % der Pack-Kosten als Diamanten zurück

# Packs: Preis in Diamanten und Chancen je Edition (Prozent, Summe 100)
PACKS = {
    "start":  {"name": "Start-Pack",  "price": 0,   "odds": {"klassik": 100}},
    "bronze": {"name": "Bronze-Pack", "price": 40,  "odds": {"klassik": 75, "frost": 20, "lava": 4,  "gold": 0.9,  "kosmos": 0.1}},
    "silber": {"name": "Silber-Pack", "price": 100, "odds": {"klassik": 45, "frost": 35, "lava": 15, "gold": 4.8,  "kosmos": 0.2}},
    "gold":   {"name": "Gold-Pack",   "price": 200, "odds": {"frost": 50, "lava": 35, "gold": 14.7, "kosmos": 0.3}},
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
COLLECTION_BONUS_USDT = 1000


def refund(pack: str) -> int:
    """Diamanten zurück bei einer doppelten Figur."""
    return int(PACKS[pack]["price"] * DUPLICATE_REFUND)

# Diamanten durch Werbung: unbegrenzt, mit Pause zwischen zwei Videos
AD_COOLDOWN = 45                      # Sekunden zwischen zwei Werbungen
AD_DIAMONDS = 2                       # Diamanten pro Video
def ad_reward(ads_today: int) -> int:
    return AD_DIAMONDS

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


def base_daily(char_id: str) -> float:
    """US-Dollar pro Tag auf Stufe 1."""
    if char_id in JACKPOT_USD:
        return JACKPOT_USD[char_id]
    c = BY_ID[char_id]
    lo, hi = EDITION_USD[c["edition"]]
    species_idx = (c["no"] - 1) % 20          # 0 … 19
    return lo + (hi - lo) * species_idx / 19


def daily_profit(char_id: str, level: int) -> float:
    """US-Dollar pro Tag einer Figur auf einer Stufe."""
    return round(base_daily(char_id) * (1 + PROFIT_PER_LEVEL * (level - 1)), 6)


def level_cost(char_id: str, level: int) -> int:
    """Diamanten für den Schritt von `level` auf `level + 1`."""
    return math.ceil((2 + 0.15 * level) * LEVEL_COST_FACTOR[BY_ID[char_id]["edition"]])


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
