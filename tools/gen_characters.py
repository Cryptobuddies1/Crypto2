"""Erzeugt die 100 Crypto Buddies: Grafiken (SVG), Namen, Seltenheit und Spielwerte.

Aufruf (im Projektordner):  python tools/gen_characters.py
Schreibt:  characters.json        (Werte für den Server)
           webapp/characters.js   (Werte + Grafiken für die App)
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INK = "#1f1a3d"

# ------------------------------------------------------------------ Farben
def hx(c):
    c = c.lstrip("#"); return [int(c[i:i + 2], 16) for i in (0, 2, 4)]

def mix(a, b, t):
    A, B = hx(a), hx(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(A, B))

# ------------------------------------------------------------ Tierarten
# name, Anzeigename, main, light, dark, Vornamen (je Edition einer)
SPECIES = [
    ("pinguin",   "Pinguin",   "#1e3a5f", "#ffffff", "#0f2440", ["Pino", "Paul", "Pia", "Pepe", "Polly"]),
    ("fuchs",     "Fuchs",     "#f97316", "#fff7ed", "#c2410c", ["Fritzi", "Felix", "Finja", "Fred", "Flo"]),
    ("igel",      "Igel",      "#a16207", "#fde68a", "#78350f", ["Igor", "Ida", "Ivo", "Ilse", "Ingo"]),
    ("eule",      "Eule",      "#8b5cf6", "#ede9fe", "#6d28d9", ["Ella", "Emil", "Elsa", "Erik", "Edda"]),
    ("schildi",   "Schildi",   "#4ade80", "#dcfce7", "#15803d", ["Toni", "Tilda", "Theo", "Tara", "Timo"]),
    ("axolotl",   "Axolotl",   "#fbcfe8", "#fdf2f8", "#ec4899", ["Axel", "Anni", "Arno", "Alma", "Ari"]),
    ("katze",     "Katze",     "#94a3b8", "#f1f5f9", "#475569", ["Kiki", "Karl", "Kira", "Kurt", "Klara"]),
    ("hase",      "Hase",      "#e7d8c9", "#fffaf5", "#b8a089", ["Hanni", "Hugo", "Heidi", "Hans", "Hedi"]),
    ("baer",      "Bär",       "#92400e", "#fcd9a8", "#5b2a07", ["Bruno", "Berta", "Ben", "Bella", "Bodo"]),
    ("panda",     "Panda",     "#ffffff", "#ffffff", "#1f2937", ["Pauli", "Pippa", "Piet", "Paula", "Pablo"]),
    ("frosch",    "Frosch",    "#65a30d", "#ecfccb", "#3f6212", ["Fridolin", "Frieda", "Frank", "Fanny", "Ferdi"]),
    ("koala",     "Koala",     "#9ca3af", "#f3f4f6", "#4b5563", ["Kalle", "Koko", "Konrad", "Kaja", "Knut"]),
    ("hamster",   "Hamster",   "#f59e0b", "#fffbeb", "#b45309", ["Hubert", "Hilde", "Harry", "Henni", "Holger"]),
    ("biber",     "Biber",     "#7c4a1e", "#e8c9a0", "#4a2a0e", ["Benno", "Bärbel", "Bastian", "Britta", "Boris"]),
    ("krake",     "Krake",     "#f472b6", "#fce7f3", "#be185d", ["Kai", "Karla", "Kuno", "Kim", "Kasimir"]),
    ("hund",      "Hund",      "#d6a76c", "#fff4e0", "#8a5a2b", ["Hektor", "Hanna", "Helmut", "Herta", "Hasso"]),
    ("loewe",     "Löwe",      "#fbbf24", "#fef3c7", "#b45309", ["Leo", "Lotte", "Lenny", "Lia", "Ludwig"]),
    ("affe",      "Affe",      "#8b5a3c", "#f5d0b0", "#5a3420", ["Anton", "Ada", "Ali", "Amelie", "August"]),
    ("faultier",  "Faultier",  "#a8916f", "#f0e6d2", "#5c4a33", ["Fabian", "Fee", "Falk", "Fiona", "Florian"]),
    ("drache",    "Drache",    "#22c55e", "#fef08a", "#166534", ["Damian", "Dina", "Diego", "Dalia", "Dorian"]),
]

# Editionen = Seltenheit
EDITIONS = [
    {"id": "klassik", "name": "Klassik", "rarity": "Normal", "color": "#94a3b8", "tint": None,      "t": 0.0},
    {"id": "frost",   "name": "Frost",   "rarity": "Selten",     "color": "#38bdf8", "tint": "#bae6fd", "t": 0.55},
    {"id": "lava",    "name": "Lava",    "rarity": "Sehr selten",     "color": "#f43f5e", "tint": "#f87171", "t": 0.5},
    {"id": "gold",    "name": "Gold",    "rarity": "Legendär",   "color": "#f59e0b", "tint": "#fcd34d", "t": 0.6},
    {"id": "kosmos",  "name": "Kosmos",  "rarity": "Epic",   "color": "#a855f7", "tint": "#8b5cf6", "t": 0.6},
]

# ------------------------------------------------------------ Bausteine
def eyes(y=46, dx=10, r=5, cx=50):
    return (f'<circle cx="{cx-dx}" cy="{y}" r="{r}" fill="{INK}"/><circle cx="{cx+dx}" cy="{y}" r="{r}" fill="{INK}"/>'
            f'<circle cx="{cx-dx+1.8}" cy="{y-1.8}" r="{r*.34:.1f}" fill="#fff"/><circle cx="{cx+dx+1.8}" cy="{y-1.8}" r="{r*.34:.1f}" fill="#fff"/>')

def blush(y=54, dx=17):
    return (f'<ellipse cx="{50-dx}" cy="{y}" rx="4.5" ry="2.8" fill="#f9a8d4" opacity=".75"/>'
            f'<ellipse cx="{50+dx}" cy="{y}" rx="4.5" ry="2.8" fill="#f9a8d4" opacity=".75"/>')

def smile(y=57, w=5):
    return f'<path d="M{50-w} {y}q{w} {w*.8} {w*2} 0" stroke="{INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>'

def head(m, rx=27, ry=24, cy=46):
    return f'<ellipse cx="50" cy="{cy}" rx="{rx}" ry="{ry}" fill="{m}"/>'

def body(m, l):
    return (f'<ellipse cx="50" cy="80" rx="19" ry="14" fill="{m}"/>'
            f'<ellipse cx="50" cy="82" rx="11" ry="9" fill="{l}"/>')


def species_art(sid, m, l, d):
    """Gibt (hinten, kopf_und_gesicht) zurück."""
    back, front = "", ""
    if sid == "pinguin":
        back = body(m, l) + f'<ellipse cx="38" cy="93" rx="7" ry="3.5" fill="#fb923c"/><ellipse cx="62" cy="93" rx="7" ry="3.5" fill="#fb923c"/>'
        front = head(m) + f'<ellipse cx="50" cy="50" rx="19" ry="16" fill="{l}"/>' + eyes(47, 9) + '<path d="M45 54l5 5 5-5z" fill="#fb923c"/>' + blush(55, 14)
    elif sid == "fuchs":
        back = f'<path d="M66 84c14-2 22-16 16-28-2 10-10 14-18 16z" fill="{m}"/><path d="M78 60c4 4 5 9 4 0-3-6-6-6-4 0z" fill="{l}"/>' + body(m, l)
        front = (f'<path d="M25 30 30 8l16 18zM75 30 70 8 54 26z" fill="{m}"/><path d="M29 26l3-12 8 10zM71 26l-3-12-8 10z" fill="{d}"/>'
                 + head(m) + f'<path d="M23 50c6 18 48 18 54 0-9 6-18 4-27 13-9-9-18-7-27-13z" fill="{l}"/>' + eyes(44, 11)
                 + f'<ellipse cx="50" cy="58" rx="4" ry="3" fill="{INK}"/>' + blush(54, 19))
    elif sid == "igel":
        pts = " ".join(f"{50+34*__import__('math').cos(a):.1f},{44+30*__import__('math').sin(a):.1f} {50+24*__import__('math').cos(a+0.17):.1f},{44+21*__import__('math').sin(a+0.17):.1f}"
                       for a in [3.14 + i * 0.35 for i in range(10)])
        back = f'<polygon points="18,60 {pts} 82,60" fill="{d}"/>' + body(m, l)
        front = head(m, 26, 23, 48) + f'<ellipse cx="50" cy="54" rx="19" ry="16" fill="{l}"/>' + eyes(50, 9) + f'<circle cx="50" cy="58" r="3.5" fill="{INK}"/>' + blush(57, 15) + smile(61, 3)
    elif sid == "eule":
        back = body(m, l) + f'<path d="M42 78q4 3 8 0M50 78q4 3 8 0M46 85q4 3 8 0" stroke="{d}" stroke-width="1.6" fill="none" opacity=".5"/>'
        front = (f'<path d="M24 32l6-18 12 12zM76 32l-6-18-12 12z" fill="{d}"/>' + head(m)
                 + f'<circle cx="39" cy="45" r="11" fill="{l}"/><circle cx="61" cy="45" r="11" fill="{l}"/>' + eyes(46, 11, 5.5)
                 + '<path d="M46 54l4 6 4-6z" fill="#f59e0b"/>')
    elif sid == "schildi":
        back = (f'<ellipse cx="50" cy="80" rx="30" ry="17" fill="{d}"/><path d="M50 66l9 6v10l-9 6-9-6V72zM31 74h8l2 9-6 5-8-4zM69 74h-8l-2 9 6 5 8-4z" fill="{m}" opacity=".8"/>'
                f'<ellipse cx="50" cy="94" rx="28" ry="4" fill="{l}"/>')
        front = head(m, 23, 21, 44) + eyes(43, 9) + blush(51, 14) + smile(53, 4)
    elif sid == "axolotl":
        back = (f'<g fill="{d}"><ellipse cx="17" cy="34" rx="10" ry="4" transform="rotate(-25 17 34)"/><ellipse cx="14" cy="45" rx="10" ry="4"/><ellipse cx="17" cy="56" rx="10" ry="4" transform="rotate(25 17 56)"/>'
                f'<ellipse cx="83" cy="34" rx="10" ry="4" transform="rotate(25 83 34)"/><ellipse cx="86" cy="45" rx="10" ry="4"/><ellipse cx="83" cy="56" rx="10" ry="4" transform="rotate(-25 83 56)"/></g>') + body(m, l)
        front = head(m, 31, 24) + eyes(44, 13) + f'<path d="M41 54q9 7 18 0" stroke="{INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>' + blush(52, 22)
    elif sid == "katze":
        back = f'<path d="M68 86c12 0 16-10 12-20" stroke="{m}" stroke-width="6" fill="none" stroke-linecap="round"/>' + body(m, l)
        front = (f'<path d="M26 34 28 12l16 13zM74 34 72 12 56 25z" fill="{m}"/><path d="M30 28l1-10 8 7zM70 28l-1-10-8 7z" fill="#f9a8d4"/>'
                 + head(m) + f'<ellipse cx="50" cy="56" rx="11" ry="8" fill="{l}"/>' + eyes(45, 11)
                 + '<path d="M47 53h6l-3 3z" fill="#f472b6"/>' + smile(57, 3)
                 + f'<path d="M24 53h12M24 58l12-2M76 53H64M76 58l-12-2" stroke="{d}" stroke-width="1.3" stroke-linecap="round"/>')
    elif sid == "hase":
        back = body(m, l)
        front = (f'<ellipse cx="38" cy="16" rx="7" ry="18" fill="{m}" transform="rotate(-10 38 16)"/><ellipse cx="62" cy="16" rx="7" ry="18" fill="{m}" transform="rotate(10 62 16)"/>'
                 f'<ellipse cx="38" cy="17" rx="3.5" ry="13" fill="#f9a8d4" transform="rotate(-10 38 17)"/><ellipse cx="62" cy="17" rx="3.5" ry="13" fill="#f9a8d4" transform="rotate(10 62 17)"/>'
                 + head(m) + eyes(46, 10) + '<ellipse cx="50" cy="53" rx="3" ry="2.2" fill="#f472b6"/>' + smile(56, 3)
                 + '<rect x="47" y="58" width="6" height="5" rx="1" fill="#fff" stroke="#d6d3d1"/>' + blush(54, 17))
    elif sid == "baer":
        back = body(m, l)
        front = (f'<circle cx="28" cy="26" r="9" fill="{m}"/><circle cx="72" cy="26" r="9" fill="{m}"/><circle cx="28" cy="26" r="4.5" fill="{l}"/><circle cx="72" cy="26" r="4.5" fill="{l}"/>'
                 + head(m) + f'<ellipse cx="50" cy="56" rx="12" ry="9" fill="{l}"/>' + eyes(44, 11) + f'<ellipse cx="50" cy="53" rx="4" ry="3" fill="{INK}"/>' + smile(58, 3) + blush(52, 19))
    elif sid == "panda":
        back = f'<ellipse cx="50" cy="80" rx="19" ry="14" fill="{d}"/><ellipse cx="50" cy="82" rx="11" ry="9" fill="{l}"/>'
        front = (f'<circle cx="28" cy="26" r="9" fill="{d}"/><circle cx="72" cy="26" r="9" fill="{d}"/>' + head(m)
                 + f'<ellipse cx="39" cy="46" rx="8" ry="9" fill="{d}" transform="rotate(-20 39 46)"/><ellipse cx="61" cy="46" rx="8" ry="9" fill="{d}" transform="rotate(20 61 46)"/>'
                 + '<circle cx="40" cy="46" r="3.5" fill="#fff"/><circle cx="60" cy="46" r="3.5" fill="#fff"/><circle cx="40.8" cy="46" r="2" fill="#1f1a3d"/><circle cx="59.2" cy="46" r="2" fill="#1f1a3d"/>'
                 + f'<ellipse cx="50" cy="55" rx="3.5" ry="2.5" fill="{d}"/>' + smile(59, 3) + blush(56, 19))
    elif sid == "frosch":
        back = body(m, l)
        front = (head(m, 30, 21, 50) + f'<circle cx="35" cy="32" r="11" fill="{m}"/><circle cx="65" cy="32" r="11" fill="{m}"/>'
                 + '<circle cx="35" cy="32" r="7" fill="#fff"/><circle cx="65" cy="32" r="7" fill="#fff"/>' + eyes(32, 15, 4.5)
                 + f'<path d="M34 54q16 11 32 0" stroke="{d}" stroke-width="2.5" fill="none" stroke-linecap="round"/>' + blush(52, 22))
    elif sid == "koala":
        back = body(m, l)
        front = (f'<circle cx="24" cy="32" r="13" fill="{m}"/><circle cx="76" cy="32" r="13" fill="{m}"/><circle cx="24" cy="32" r="8" fill="{l}"/><circle cx="76" cy="32" r="8" fill="{l}"/>'
                 + head(m) + eyes(44, 12) + f'<ellipse cx="50" cy="53" rx="6" ry="8" fill="{d}"/>' + smile(63, 3) + blush(56, 19))
    elif sid == "hamster":
        back = body(m, l)
        front = (f'<circle cx="31" cy="26" r="6" fill="{m}"/><circle cx="69" cy="26" r="6" fill="{m}"/><circle cx="31" cy="26" r="3" fill="#f9a8d4"/><circle cx="69" cy="26" r="3" fill="#f9a8d4"/>'
                 + head(m, 28, 24) + f'<ellipse cx="33" cy="56" rx="11" ry="9" fill="{l}"/><ellipse cx="67" cy="56" rx="11" ry="9" fill="{l}"/><ellipse cx="50" cy="56" rx="9" ry="8" fill="{l}"/>'
                 + eyes(44, 11) + '<ellipse cx="50" cy="52" rx="2.8" ry="2" fill="#f472b6"/>' + smile(56, 3) + blush(54, 20))
    elif sid == "biber":
        back = (f'<ellipse cx="74" cy="88" rx="14" ry="7" fill="{d}" transform="rotate(-20 74 88)"/>'
                f'<path d="M66 86l14-6M68 91l14-6" stroke="{m}" stroke-width="1.5"/>') + body(m, l)
        front = (f'<circle cx="29" cy="28" r="6" fill="{d}"/><circle cx="71" cy="28" r="6" fill="{d}"/>' + head(m)
                 + f'<ellipse cx="50" cy="55" rx="12" ry="9" fill="{l}"/>' + eyes(44, 11) + f'<ellipse cx="50" cy="51" rx="4" ry="3" fill="{INK}"/>'
                 + '<rect x="45" y="56" width="10" height="7" rx="1.5" fill="#fff" stroke="#e7e5e4"/><path d="M50 56v7" stroke="#e7e5e4"/>' + blush(53, 19))
    elif sid == "krake":
        tent = "".join(f'<path d="M{x} 66c{s*4} 10 {s*-4} 18 {s*4} 26" stroke="{m}" stroke-width="7" fill="none" stroke-linecap="round"/>'
                       for x, s in [(34, -1), (44, 1), (56, -1), (66, 1)])
        back = tent
        front = (f'<path d="M22 56c0-26 12-40 28-40s28 14 28 40c-6 8-50 8-56 0z" fill="{m}"/>'
                 + f'<circle cx="38" cy="28" r="4" fill="{l}" opacity=".7"/><circle cx="62" cy="24" r="3" fill="{l}" opacity=".7"/>'
                 + eyes(46, 10) + smile(53, 4) + blush(52, 18))
    elif sid == "hund":
        back = f'<path d="M68 82c10-4 14-12 10-18" stroke="{m}" stroke-width="6" fill="none" stroke-linecap="round"/>' + body(m, l)
        front = (head(m) + f'<ellipse cx="25" cy="44" rx="8" ry="16" fill="{d}" transform="rotate(15 25 44)"/><ellipse cx="75" cy="44" rx="8" ry="16" fill="{d}" transform="rotate(-15 75 44)"/>'
                 + f'<ellipse cx="50" cy="56" rx="13" ry="9" fill="{l}"/>' + eyes(44, 10) + f'<ellipse cx="50" cy="52" rx="4.5" ry="3.2" fill="{INK}"/>'
                 + '<path d="M47 58h6v4a3 3 0 01-6 0z" fill="#fb7185"/>' + blush(53, 17))
    elif sid == "loewe":
        import math
        mane = "".join(f'<circle cx="{50+30*math.cos(a):.1f}" cy="{46+28*math.sin(a):.1f}" r="9" fill="{d}"/>' for a in [i * math.pi / 6 for i in range(12)])
        back = f'<path d="M68 86c10 0 14-6 12-14" stroke="{m}" stroke-width="4" fill="none"/><circle cx="80" cy="71" r="4" fill="{d}"/>' + body(m, l)
        front = (mane + head(m, 26, 23) + f'<circle cx="32" cy="28" r="5" fill="{m}"/><circle cx="68" cy="28" r="5" fill="{m}"/>'
                 + f'<ellipse cx="50" cy="55" rx="11" ry="8" fill="{l}"/>' + eyes(44, 10) + f'<path d="M46 51h8l-4 4z" fill="{INK}"/>' + smile(58, 3) + blush(52, 17))
    elif sid == "affe":
        back = f'<path d="M66 88c16 2 18-14 8-16" stroke="{m}" stroke-width="5" fill="none" stroke-linecap="round"/>' + body(m, l)
        front = (f'<circle cx="21" cy="46" r="9" fill="{m}"/><circle cx="79" cy="46" r="9" fill="{m}"/><circle cx="21" cy="46" r="5" fill="{l}"/><circle cx="79" cy="46" r="5" fill="{l}"/>'
                 + head(m, 26, 24) + f'<path d="M50 34c-8-8-20-2-18 10-6 4-4 20 18 22 22-2 24-18 18-22 2-12-10-18-18-10z" fill="{l}"/>'
                 + eyes(44, 9) + f'<circle cx="47" cy="53" r="1.3" fill="{INK}"/><circle cx="53" cy="53" r="1.3" fill="{INK}"/>' + smile(57, 5))
    elif sid == "faultier":
        back = body(m, l)
        front = (head(m) + f'<ellipse cx="50" cy="49" rx="21" ry="17" fill="{l}"/>'
                 + f'<ellipse cx="38" cy="47" rx="8" ry="5" fill="{d}" transform="rotate(15 38 47)"/><ellipse cx="62" cy="47" rx="8" ry="5" fill="{d}" transform="rotate(-15 62 47)"/>'
                 + '<path d="M35 47q3 2 6 0M59 47q3 2 6 0" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round"/>'
                 + f'<ellipse cx="50" cy="54" rx="3.5" ry="2.5" fill="{INK}"/>' + smile(58, 4))
    elif sid == "drache":
        back = (f'<path d="M32 74 10 58l4 20 8-2zM68 74l22-16-4 20-8-2z" fill="{d}"/>'
                f'<path d="M66 88c12 4 18-4 16-12l6 2" stroke="{m}" stroke-width="5" fill="none" stroke-linecap="round"/>') + body(m, l)
        front = (f'<path d="M34 28 30 10l10 12zM66 28l4-18-10 12z" fill="{l}"/>'
                 + f'<path d="M42 22l4-8 4 8 4-8 4 8z" fill="{d}"/>' + head(m)
                 + f'<ellipse cx="50" cy="56" rx="13" ry="8" fill="{l}"/>' + eyes(43, 11)
                 + f'<circle cx="46" cy="54" r="1.5" fill="{d}"/><circle cx="54" cy="54" r="1.5" fill="{d}"/>' + smile(59, 4) + blush(51, 19))
    return back, front


# ------------------------------------------------------------- Zubehör
def hat(kind, ed_color):
    return {
        "helm":    '<path d="M27 26a23 15 0 0146 0z" fill="#facc15"/><rect x="24" y="24" width="52" height="5" rx="2.5" fill="#eab308"/><circle cx="50" cy="18" r="5" fill="#fef9c3" stroke="#eab308" stroke-width="2"/>',
        "kappe":   '<path d="M28 27a22 15 0 0144 0z" fill="#3b82f6"/><path d="M50 27h28a4 4 0 01-4 5H50z" fill="#1d4ed8"/><circle cx="50" cy="13" r="2.5" fill="#1d4ed8"/>',
        "muetze":  '<path d="M27 28c0-16 46-16 46 0z" fill="#ef4444"/><rect x="25" y="25" width="50" height="7" rx="3.5" fill="#fff"/><circle cx="50" cy="10" r="5" fill="#fff"/>',
        "zylinder":'<rect x="36" y="4" width="28" height="20" rx="2" fill="#1f2937"/><rect x="28" y="22" width="44" height="5" rx="2.5" fill="#1f2937"/><rect x="36" y="17" width="28" height="4" fill="#dc2626"/>',
        "krone":   f'<path d="M32 26 30 8l10 9 10-12 10 12 10-9-2 18z" fill="#fbbf24" stroke="#b45309" stroke-width="1.5"/><circle cx="50" cy="16" r="2.5" fill="#ef4444"/><circle cx="38" cy="19" r="1.8" fill="#3b82f6"/><circle cx="62" cy="19" r="1.8" fill="#22c55e"/>',
        "zauber":  f'<path d="M30 26 52 1 70 26z" fill="#4c1d95"/><rect x="26" y="23" width="48" height="6" rx="3" fill="#6d28d9"/><path d="M48 10l1.5 3 3 .5-2.2 2 .5 3-2.8-1.5-2.8 1.5.5-3-2.2-2 3-.5z" fill="#fde047"/>',
        "flamme":  '<path d="M50 4c6 8 12 10 10 18-1 5-6 7-10 7s-9-2-10-7c-1-6 4-8 6-14 2 4 3 5 4 6 1-3 0-6 0-10z" fill="#f97316"/><path d="M50 14c3 4 6 6 5 10-1 3-3 4-5 4s-4-1-5-4c0-3 3-5 5-10z" fill="#fde047"/>',
        "schleife":'<path d="M50 24l-12-7v14zM50 24l12-7v14z" fill="#ec4899"/><circle cx="50" cy="24" r="3.5" fill="#be185d"/>',
        "": "",
    }[kind]

def face(kind):
    return {
        "brille":  f'<g fill="none" stroke="{INK}" stroke-width="2"><circle cx="39" cy="46" r="7.5"/><circle cx="61" cy="46" r="7.5"/><path d="M46.5 46h7"/></g>',
        "sonne":   '<path d="M30 42h17v5a6 6 0 01-6 6h-5a6 6 0 01-6-6zM53 42h17v5a6 6 0 01-6 6h-5a6 6 0 01-6-6z" fill="#111827"/><path d="M47 43h6" stroke="#111827" stroke-width="2"/><path d="M33 44l4 0" stroke="#fff" stroke-width="1.5" opacity=".6"/>',
        "monokel": '<circle cx="61" cy="46" r="8" fill="none" stroke="#b45309" stroke-width="2.2"/><path d="M68 50c2 8 0 16-4 22" stroke="#b45309" stroke-width="1" fill="none"/>',
        "": "",
    }[kind]

def neck(kind):
    return {
        "halstuch": '<path d="M33 66h34l-17 12z" fill="#ef4444"/><path d="M36 66h28" stroke="#b91c1c" stroke-width="3"/>',
        "schal":    '<path d="M31 64c12 6 26 6 38 0v7c-12 6-26 6-38 0z" fill="#38bdf8"/><path d="M58 68l4 14h-7l-2-12z" fill="#0ea5e9"/><path d="M37 66v6M45 68v6M53 68v6" stroke="#e0f2fe" stroke-width="2"/>',
        "fliege":   '<path d="M50 69l-9-5v10zM50 69l9-5v10z" fill="#7c3aed"/><circle cx="50" cy="69" r="2.5" fill="#4c1d95"/>',
        "kette":    '<path d="M36 65q14 10 28 0" stroke="#fbbf24" stroke-width="2.5" fill="none"/><circle cx="50" cy="72" r="4" fill="#fbbf24" stroke="#b45309"/>',
        "": "",
    }[kind]

def item(kind):
    return {
        "muenze":  '<g transform="translate(76 80)"><circle r="9" fill="#f59e0b"/><circle r="6.5" fill="#fcd34d"/><text y="3.5" font-size="9" font-weight="900" text-anchor="middle" fill="#b45309" font-family="sans-serif">₿</text></g>',
        "pickel":  '<path d="M70 94 82 66" stroke="#92400e" stroke-width="3.5" stroke-linecap="round"/><path d="M72 64q10-6 20 4" stroke="#9ca3af" stroke-width="4" fill="none" stroke-linecap="round"/>',
        "juwel":   '<g transform="translate(77 80)"><path d="M-8-3l4-5h8l4 5-8 11z" fill="#22d3ee" stroke="#0e7490" stroke-width="1.2"/><path d="M-8-3h16M-4-8l4 16 4-16" stroke="#0e7490" stroke-width=".8" fill="none"/></g>',
        "sack":    '<g transform="translate(77 82)"><path d="M-9 8c-2-10 3-14 6-15l-3-4h12l-3 4c3 1 8 5 6 15z" fill="#d6b88a" stroke="#8a6a3a"/><text y="6" font-size="9" font-weight="900" text-anchor="middle" fill="#8a6a3a" font-family="sans-serif">$</text></g>',
    }[kind]

def effect(ed):
    if ed == "frost":
        f = lambda x, y, s: f'<g transform="translate({x} {y}) scale({s})" stroke="#e0f2fe" stroke-width="1.6" stroke-linecap="round"><path d="M0-5v10M-4.3-2.5l8.6 5M-4.3 2.5l8.6-5"/></g>'
        return f(12, 16, 1) + f(88, 22, .8) + f(10, 74, .7)
    if ed == "lava":
        return ''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fb923c" opacity=".85"/>' for x, y, r in [(12, 20, 2.2), (88, 14, 1.8), (90, 60, 2), (8, 66, 1.5)])
    if ed == "gold":
        s = lambda x, y, k: f'<path d="M{x} {y-5*k}l{1.2*k} {3.8*k} {3.8*k} {1.2*k}-{3.8*k} {1.2*k}-{1.2*k} {3.8*k}-{1.2*k}-{3.8*k}-{3.8*k}-{1.2*k} {3.8*k}-{1.2*k}z" fill="#fde68a"/>'
        return s(12, 18, 1) + s(88, 26, .8) + s(14, 70, .7) + s(88, 72, .9)
    if ed == "kosmos":
        return (''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity=".9"/>' for x, y, r in [(10, 14, 1.4), (20, 30, .9), (88, 18, 1.2), (82, 34, .8), (92, 62, 1), (8, 70, 1.2)])
                + '<ellipse cx="50" cy="44" rx="40" ry="9" fill="none" stroke="#c4b5fd" stroke-width="1.5" opacity=".6" transform="rotate(-15 50 44)"/>')
    return ""

def background(ed):
    bg = {"klassik": ("#f5f3ff", "#ede9fe"), "frost": ("#e0f2fe", "#bae6fd"), "lava": ("#ffe4e6", "#fecaca"),
          "gold": ("#fef9c3", "#fde68a"), "kosmos": ("#2e1065", "#4c1d95")}[ed]
    return bg


def build_svg(sid, ed, acc):
    sp = next(s for s in SPECIES if s[0] == sid)
    e = next(x for x in EDITIONS if x["id"] == ed)
    m, l, d = sp[2], sp[3], sp[4]
    if e["tint"]:
        m, l, d = mix(m, e["tint"], e["t"]), mix(l, "#ffffff", .2) if ed != "kosmos" else mix(l, "#ddd6fe", .4), mix(d, e["tint"], e["t"] * .6)
    back, front = species_art(sid, m, l, d)
    parts = [effect(ed) if ed == "kosmos" else "", back, front, neck(acc["neck"]), item(acc["item"]),
             hat(acc["hat"], e["color"]), face(acc["face"]), effect(ed) if ed != "kosmos" else ""]
    return f'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'


def pick_accessories(rng, ed, sid):
    if ed == "klassik":
        a = dict(hat=rng.choice(["helm", "kappe", "", "schleife", "helm"]), face=rng.choice(["", "", "brille"]), neck=rng.choice(["halstuch", "", ""]), item=rng.choice(["muenze", "pickel"]))
    elif ed == "frost":
        a = dict(hat=rng.choice(["muetze", "muetze", "", "kappe"]), face=rng.choice(["", "sonne"]), neck="schal", item=rng.choice(["juwel", "muenze"]))
    elif ed == "lava":
        a = dict(hat=rng.choice(["flamme", "flamme", "helm"]), face=rng.choice(["sonne", "", "sonne"]), neck=rng.choice(["halstuch", ""]), item=rng.choice(["pickel", "juwel"]))
    elif ed == "gold":
        a = dict(hat="krone", face=rng.choice(["monokel", "", "sonne"]), neck="kette", item=rng.choice(["sack", "muenze"]))
    else:
        a = dict(hat=rng.choice(["zauber", "zylinder", "zauber"]), face=rng.choice(["", "monokel", "brille"]), neck=rng.choice(["fliege", ""]), item="juwel")
    # Sonnenbrille/Monokel passen nicht auf Frosch-, Panda- und Eulenaugen
    if sid in ("frosch", "panda", "eule") and a["face"]:
        a["face"] = ""
    # Hasenohren und große Hüte vertragen sich nicht
    if sid == "hase" and a["hat"] in ("helm", "kappe", "muetze", "zylinder"):
        a["hat"] = "schleife" if ed in ("klassik", "frost") else a["hat"]
    return a


# ------------------------------------------------------------- Werte
def build():
    rng = random.Random(3)
    chars = []
    i = 0
    for ei, e in enumerate(EDITIONS):
        for sp in SPECIES:
            sid, label, *_, names = sp
            first = names[ei]
            cid = f"{first.lower()}_{sid}".replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            price = 0 if i == 0 else int(round(500 * 1.18 ** (i - 1), -1 if i < 15 else -2))
            rate = 5 if i == 0 else round(price / (25 + 3 * i), 1)
            up = 60 if i == 0 else int(round(max(100, price * 0.4), -1))
            acc = pick_accessories(rng, e["id"], sid)
            chars.append({
                "id": cid, "name": f"{first} {label}", "species": sid, "edition": e["id"], "edition_name": e["name"],
                "rarity": e["rarity"], "rarity_color": e["color"], "no": i + 1,
                "price": price, "rate": rate, "up": up, "svg": build_svg(sid, e["id"], acc),
                "bg": background(e["id"]),
            })
            i += 1
    return chars


if __name__ == "__main__":
    chars = build()
    stats = [{k: c[k] for k in ("id", "name", "edition", "rarity", "no", "price", "rate", "up")} for c in chars]
    (ROOT / "characters.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "webapp" / "characters.js").write_text("window.KUMPELS=" + json.dumps(chars, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(len(chars), "Figuren erzeugt. Teuerste:", chars[-1]["name"], f'{chars[-1]["price"]:,}', "Punkte")
