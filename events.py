"""News und Turniere. Alle Funktionen bekommen eine offene Datenbank-Verbindung (con)."""
import json
import time

# Wonach in einem Turnier gewertet wird
METRICS = {
    "profit":  {"en": "Profit earned", "de": "Verdienter Profit", "unit": "usd"},
    "packs":   {"en": "Packs opened",  "de": "Geöffnete Packs",   "unit": "count"},
    "ads":     {"en": "Videos watched", "de": "Gesehene Videos",  "unit": "count"},
    "invites": {"en": "Friends invited", "de": "Eingeladene Freunde", "unit": "count"},
}
PRIZE_TYPES = ("diamonds", "usd")


def init(con) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY, title_en TEXT, title_de TEXT, body_en TEXT, body_de TEXT,
        pinned INTEGER NOT NULL DEFAULT 0, created REAL, broadcast INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS tournaments (
        id INTEGER PRIMARY KEY, name_en TEXT, name_de TEXT, metric TEXT, start REAL, end REAL,
        prize_type TEXT, prizes TEXT, status TEXT NOT NULL DEFAULT 'open', created REAL, finished REAL);
    CREATE TABLE IF NOT EXISTS tournament_scores (
        tid INTEGER, user_id INTEGER, score REAL NOT NULL DEFAULT 0, updated REAL, PRIMARY KEY (tid, user_id));
    CREATE TABLE IF NOT EXISTS tournament_results (
        tid INTEGER, rank INTEGER, user_id INTEGER, score REAL, prize REAL, PRIMARY KEY (tid, rank));
    """)


# ------------------------------------------------------------------ Punkte zählen
def add(con, user_id: int, metric: str, amount: float, t: float | None = None) -> None:
    """Zählt `amount` für alle laufenden Turniere mit dieser Wertung."""
    t = t or time.time()
    if not amount:
        return
    for (tid,) in con.execute("SELECT id FROM tournaments WHERE status='open' AND metric=? AND start<=? AND end>?",
                              (metric, t, t)).fetchall():
        con.execute("""INSERT INTO tournament_scores (tid, user_id, score, updated) VALUES (?,?,?,?)
                       ON CONFLICT(tid, user_id) DO UPDATE SET score=score+excluded.score, updated=excluded.updated""",
                    (tid, user_id, amount, t))


# ------------------------------------------------------------------ Ansicht für Spieler
def _name(row, lang, field):
    return row[f"{field}_{lang}"] or row[f"{field}_en"] or row[f"{field}_de"] or ""


def leaderboard(con, tid: int, limit: int = 10) -> list[dict]:
    return [dict(user_id=r["user_id"], name=r["name"] or "Player", score=round(r["score"], 6))
            for r in con.execute("""SELECT s.user_id, s.score, u.name FROM tournament_scores s
                                    LEFT JOIN users u ON u.id=s.user_id WHERE s.tid=? AND s.score>0
                                    ORDER BY s.score DESC, s.updated ASC LIMIT ?""", (tid, limit))]


def my_rank(con, tid: int, user_id: int) -> dict | None:
    r = con.execute("SELECT score, updated FROM tournament_scores WHERE tid=? AND user_id=?", (tid, user_id)).fetchone()
    if not r or r["score"] <= 0:
        return None
    better = con.execute("""SELECT COUNT(*) FROM tournament_scores WHERE tid=? AND
                            (score>? OR (score=? AND updated<?))""", (tid, r["score"], r["score"], r["updated"])).fetchone()[0]
    return {"rank": better + 1, "score": round(r["score"], 6)}


def tour_public(con, row, lang: str, user_id: int | None = None) -> dict:
    d = {"id": row["id"], "name": _name(row, lang, "name"), "metric": row["metric"],
         "metric_label": METRICS[row["metric"]][lang if lang in ("en", "de") else "en"],
         "unit": METRICS[row["metric"]]["unit"], "start": row["start"], "end": row["end"],
         "prize_type": row["prize_type"], "prizes": json.loads(row["prizes"] or "[]"), "status": row["status"],
         "top": leaderboard(con, row["id"])}
    if row["status"] == "finished":
        d["results"] = [dict(r) for r in con.execute(
            """SELECT r.rank, r.score, r.prize, u.name FROM tournament_results r LEFT JOIN users u ON u.id=r.user_id
               WHERE r.tid=? ORDER BY r.rank""", (row["id"],))]
    if user_id:
        d["me"] = my_rank(con, row["id"], user_id)
    return d


def player_view(con, user_id: int, lang: str) -> dict:
    t = time.time()
    news = [dict(id=r["id"], title=_name(r, lang, "title"), body=_name(r, lang, "body"), created=r["created"], pinned=bool(r["pinned"]))
            for r in con.execute("SELECT * FROM news ORDER BY pinned DESC, created DESC LIMIT 15")]
    live = con.execute("SELECT * FROM tournaments WHERE status='open' AND start<=? AND end>? ORDER BY end", (t, t)).fetchall()
    soon = con.execute("SELECT * FROM tournaments WHERE status='open' AND start>? ORDER BY start LIMIT 3", (t,)).fetchall()
    done = con.execute("SELECT * FROM tournaments WHERE status='finished' ORDER BY finished DESC LIMIT 2").fetchall()
    return {"news": news,
            "tournaments": {"live": [tour_public(con, r, lang, user_id) for r in live],
                            "upcoming": [tour_public(con, r, lang, user_id) for r in soon],
                            "finished": [tour_public(con, r, lang, user_id) for r in done]}}


# ------------------------------------------------------------------ Turnier beenden
def finish_due(con, t: float | None = None) -> list[dict]:
    """Beendet abgelaufene Turniere und vergibt die Preise. Gibt die Gewinner für Benachrichtigungen zurück."""
    t = t or time.time()
    out = []
    for row in con.execute("SELECT * FROM tournaments WHERE status='open' AND end<=?", (t,)).fetchall():
        prizes = json.loads(row["prizes"] or "[]")
        top = leaderboard(con, row["id"], len(prizes))
        winners = []
        for rank, (entry, prize) in enumerate(zip(top, prizes), start=1):
            prize = float(prize)
            if row["prize_type"] == "diamonds":
                con.execute("UPDATE users SET diamonds=diamonds+? WHERE id=?", (int(prize), entry["user_id"]))
            else:
                con.execute("UPDATE users SET usdt=usdt+? WHERE id=?", (prize, entry["user_id"]))
            con.execute("INSERT OR REPLACE INTO tournament_results VALUES (?,?,?,?,?)",
                        (row["id"], rank, entry["user_id"], entry["score"], prize))
            winners.append({"rank": rank, "user_id": entry["user_id"], "name": entry["name"], "prize": prize})
        con.execute("UPDATE tournaments SET status='finished', finished=? WHERE id=?", (t, row["id"]))
        out.append({"id": row["id"], "name_en": row["name_en"], "name_de": row["name_de"],
                    "prize_type": row["prize_type"], "winners": winners})
    return out


# ------------------------------------------------------------------ Admin
def create_news(con, d: dict) -> int:
    if not (d.get("title_en") or d.get("title_de")) or not (d.get("body_en") or d.get("body_de")):
        raise ValueError("Titel und Text in mindestens einer Sprache nötig")
    cur = con.execute("INSERT INTO news (title_en, title_de, body_en, body_de, pinned, created) VALUES (?,?,?,?,?,?)",
                      (d.get("title_en", "").strip(), d.get("title_de", "").strip(), d.get("body_en", "").strip(),
                       d.get("body_de", "").strip(), int(bool(d.get("pinned"))), time.time()))
    return cur.lastrowid


def create_tournament(con, d: dict) -> int:
    if d.get("metric") not in METRICS:
        raise ValueError("Unbekannte Wertung")
    if d.get("prize_type") not in PRIZE_TYPES:
        raise ValueError("Preis-Art muss diamonds oder usd sein")
    start, end = float(d["start"]), float(d["end"])
    if end <= start:
        raise ValueError("Ende muss nach dem Start liegen")
    prizes = [float(p) for p in d.get("prizes", []) if str(p).strip() != ""]
    if not prizes or any(p < 0 for p in prizes):
        raise ValueError("Mindestens ein Preis nötig")
    if not (d.get("name_en") or d.get("name_de")):
        raise ValueError("Name nötig")
    cur = con.execute("""INSERT INTO tournaments (name_en, name_de, metric, start, end, prize_type, prizes, created)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (d.get("name_en", "").strip(), d.get("name_de", "").strip(), d["metric"], start, end,
                       d["prize_type"], json.dumps(prizes), time.time()))
    return cur.lastrowid


def admin_tournaments(con) -> list[dict]:
    rows = con.execute("SELECT * FROM tournaments ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, start DESC LIMIT 30").fetchall()
    out = []
    for r in rows:
        d = tour_public(con, r, "de")
        d.update(name_en=r["name_en"], name_de=r["name_de"],
                 players=con.execute("SELECT COUNT(*) FROM tournament_scores WHERE tid=? AND score>0", (r["id"],)).fetchone()[0])
        out.append(d)
    return out
