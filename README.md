# Crypto Buddies – Telegram Mini App

Sammelspiel in Telegram: Spieler ziehen Figuren aus Packs, leveln sie mit Diamanten bis Stufe 500, und die Figuren verdienen jeden Tag einen festen Dollar-Betrag.
Alle 4 Stunden wird der Ertrag gutgeschrieben und ab 1 USDT automatisch über **@CryptoBot** ausgezahlt.

## So funktioniert das Spiel
| Was | Wie |
|---|---|
| **Figuren** | 100 Stück, 5 Editionen (Klassik, Frost, Lava, Gold, Kosmos). Man bekommt sie nur aus Packs. |
| **Tagesprofit** | US-Dollar pro Tag auf Stufe 1: Klassik 0,001–0,002 $, Frost 0,004–0,008 $, Lava 0,015–0,03 $, Gold 0,06–0,12 $, Kosmos (Epic) 0,30–0,50 $. Jede Stufe +5 %; Stufe 500 = rund 26 × so viel. |
| **Aufleveln** | Kostet Diamanten: (2 + 0,15 × Stufe) × Seltenheitsfaktor. Klassik bis 500 ≈ 20.000 💎, Kosmos ≈ 49.500 💎. |
| **Packs** | Start gratis (einmal, nur Klassik), Bronze 40 💎 (Epic 0,1 %), Silber 100 💎 (Epic 0,2 %), Gold 200 💎 (Epic 0,3 %). Alle Chancen stehen in `game.py` und in der App. Doppelte Figur = 40 % der Pack-Kosten als Diamanten zurück (Bronze 16 💎, Silber 40 💎, Gold 80 💎). |
| **Jackpot-Figuren** | 4 Kosmos-Figuren mit festem Ertrag: Pablo Panda 5 $/Tag (1 von 525.000 Packs), Kasimir Krake 10 $ (1 von 1.400.000), Ludwig Löwe 25 $ (1 von 4.925.000), Dorian Drache 50 $ (1 von 19.882.000). Vergabe über einen gemeinsamen Zähler aller geöffneten Packs (ohne Start-Pack). Standard `JACKPOT_MODE = "block"`: genau 1 Treffer pro Block an geheimer Zufallsstelle. `"exact"`: immer genau das N-te Pack. Treffen zwei Jackpots dasselbe Pack, bekommt der Spieler den höheren, der andere geht ins nächste Pack. Einstellbar in `game.py` (`JACKPOTS`). |
| **Sammel-Bonus** | Wer alle 96 normalen Figuren besitzt (Jackpots zählen nicht), bekommt einmalig `COLLECTION_BONUS_USDT` (Standard 1.000) aufs Guthaben. Achtung: Bei den aktuellen Chancen braucht man dafür im Mittel rund 3,3 Mio. Diamanten (Simulation). |
| **Diamanten** | Werbung: 2 💎 pro Video (unbegrenzt, 45 s Pause). Tagesbonus: Tag 1 = 1 💎 … Tag 7 = 7 💎. Freunde: +5 💎 für beide, dazu bekommt der Einlader 20 % on top von allem, was seine Freunde verdienen (`REFERRAL_SHARE`). Kaufen: 100 💎 = 1 USDT aus Einzahlung oder Guthaben (Shop, standardmäßig aus). |
| **Auszahlung** | Alle 4 h wird der Ertrag aller Figuren voll in USDT gutgeschrieben. Nur wer in den letzten 24 h mindestens eine Werbung gesehen hat (`MIN_ADS_24H`), bekommt den Ertrag der Runde. Ab 1 USDT wird automatisch gesendet. |

Alle Spielzahlen stehen oben in `game.py`, alle Betriebs-Einstellungen in `.env`.
Wenn du in `game.py` etwas änderst, passe die gleichen Zahlen oben in `webapp/index.html` (Abschnitt „Daten & Regeln“) an. Die werden für die Anzeige und die Demo gebraucht.

## Admin-Panel
- Schick dem Bot **/id**, trag die Zahl als `ADMIN_ID` ein (mehrere Admins mit Komma: `123,456`), neu starten.
- Dann **/admin** im Bot → Knopf „Admin-Panel öffnen“. Admins sehen zusätzlich in der App unter *Events* einen Knopf zum Panel.
- **Übersicht:** Spieler, Aktive, Videos, Packs, Werbeeinnahmen gegen Gutschriften (7 Tage), CryptoBot-Guthaben, letzte Runden.
- **News:** Titel und Text auf EN/DE, anheften, optional als Bot-Nachricht an alle. Erscheint in der App unter *Events*.
- **Turniere:** Name, Wertung (verdienter Profit, geöffnete Packs, gesehene Videos, eingeladene Freunde), Start/Ende, Preise für Platz 1, 2, 3 … in Diamanten oder Dollar. Gezählt wird nur, was im Turnier-Zeitraum passiert. Am Ende vergibt der Server die Preise automatisch und benachrichtigt die Gewinner. „Jetzt beenden“ und „Abbrechen“ gibt es auch.
- **Nachricht:** Text an alle Spieler (jeder in seiner Sprache), ca. 20 Nachrichten pro Sekunde. Wer den Bot blockiert hat, wird übersprungen.
- Das Panel prüft bei jedem Aufruf die Telegram-Anmeldung und die Admin-ID.

## Sprache
- App und Bot sind standardmäßig auf **Englisch**. Spieler wechseln oben in der App per Dropdown (🇬🇧 EN / 🇩🇪 DE) oder im Bot mit `/language`. Die Wahl wird am Server gespeichert und gilt auch für Bot-Nachrichten und Fehlermeldungen.
- Texte der App: `webapp/index.html` (Abschnitt `I18N`), Texte von Server und Bot: `i18n.py`.

## Einladungslinks
- Jeder Spieler bekommt seinen Link in der App unter *Diamonds → Invite friends* (mit Kopieren- und Teilen-Knopf): `https://t.me/DEINBOT?start=ref_<Telegram-ID>`.
- Der Bot-Benutzername wird beim Start automatisch von Telegram geholt. Ein falscher `BOT_USERNAME` in der `.env` kann den Link also nicht kaputt machen.
- Erkannt wird die Einladung sowohl beim `/start` im Bot als auch, wenn die App direkt über einen Link mit `startapp=ref_<ID>` geöffnet wird.
- Bonus gibt es nur für **neue** Spieler, nie für sich selbst oder für unbekannte IDs. Der Einlader bekommt eine Nachricht, sobald jemand über seinen Link beitritt.

## Dateien
| Datei | Inhalt |
|---|---|
| `bot.py` | Telegram-Bot, Server für die Mini App, Auszahlungs-Runden, CryptoBot, Stars-Shop |
| `game.py` | Spielregeln und Zahlen |
| `characters.json` / `webapp/characters.js` | Die 100 Figuren (erzeugt von `tools/gen_characters.py`) |
| `webapp/index.html` | Die Oberfläche |

## Start auf Railway (kurz)
1. Projektordner (ohne `.env`) in ein **privates** GitHub-Repository hochladen.
2. railway.com → New Project → Deploy from GitHub repo.
3. Im Service → **Variables → Raw Editor** → Inhalt von `railway-variables.txt` einfügen → Update.
4. Service → **Settings → Networking → Generate Domain**. Die Adresse als `WEBAPP_URL` bei den Variablen eintragen.
5. Service → **Volume** hinzufügen, Mount Path `/data` (dort liegt die Datenbank, `DB_PATH=/data/kumpels.db`).
6. Startbefehl kommt aus dem `Procfile` (`python bot.py`). Railway setzt `PORT` selbst – nicht überschreiben.
7. Im Bot `/id` → Zahl als `ADMIN_ID` eintragen → fertig. Im Log (Deployments → View Logs) stehen fehlende Einstellungen.

## Einrichten
1. **Bot:** @BotFather → `/newbot` → Token in `.env` (`BOT_TOKEN`, `BOT_USERNAME`).
2. **Online stellen:** z. B. Railway oder Render, Startbefehl `python bot.py`, Variablen aus `.env` eintragen, dauerhaftes Volume für die Datenbank (`DB_PATH=/data/kumpels.db`). Die https-Adresse als `WEBAPP_URL` eintragen.
3. **Testen am PC:** `pip install -r requirements.txt`, dann `cloudflared tunnel --url http://localhost:8000` und `python bot.py`.

## Werbung
**Reihenfolge beim Tippen auf „Video ansehen“:** 1. AdsGram → 2. Monetag (nur wenn AdsGram gerade keine Werbung hat) → sonst Hinweis „kein Video verfügbar“. Bricht der Spieler das Video ab, gibt es nichts.

**AdsGram (Hauptanbieter)**
1. Konto auf partner.adsgram.ai anlegen.
2. *Ad Platform* erstellen: App-Name, Telegram-Direktlink, Web-App-URL (`WEBAPP_URL`) und Bot-ID (aus @BotFather).
3. *Ad unit* erstellen, Typ **Reward** → oben rechts „<> Show code“ → **Copy BlockID** → als `ADSGRAM_BLOCK_ID` eintragen (nur Ziffern).
4. Zur Moderation schicken (dauert meist einige Stunden an Werktagen).
5. Optional zweiter Block, Typ **Interstitial** (`int-12345`) → `ADSGRAM_INTERSTITIAL_ID`: Vollbild-Werbung nach jedem 3. geöffneten Pack.
6. Später, bei vielen Spielern: im Reward-Block die Reward-URL `https://DEINE-ADRESSE/adsgram/reward?userid=[userId]&secret=DEIN_SECRET` eintragen und `ADS_VERIFY=true` + `ADSGRAM_SECRET` setzen.

**Monetag (Ersatz)**
1. Konto auf monetag.com → *Telegram Mini App* → App-URL hinzufügen → Zone **Rewarded Interstitial** erstellen.
2. Die Zone-ID als `MONETAG_ZONE_ID` eintragen. Die App lädt `libtl.com/sdk.js` mit `data-zone` und ruft `show_<Zone-ID>()` auf. Vergleiche das einmal mit dem Code, den Monetag dir anzeigt.

**Wichtig:** Solange weder `ADSGRAM_BLOCK_ID` noch `MONETAG_ZONE_ID` gesetzt ist, läuft der Entwicklungsmodus – Spieler bekommen Diamanten ohne echtes Video. Vor dem Start also unbedingt eintragen.

## Auszahlungen in TRX (CryptoBot)
- Im Spiel ist alles in **$**. Bei der Auszahlung rechnet der Server den $-Betrag zum aktuellen CryptoBot-Kurs in **TRX** um (`PAYOUT_ASSET=TRX`) und speichert Kurs und TRX-Betrag. Spieler sehen „$1.37 · 4.28 TRX“.
- Vor jeder Runde prüft der Server, ob genug TRX in deiner CryptoBot-App liegt. Wenn nicht, hält er die Auszahlungen an und schreibt dir (`ADMIN_ID`).
- Aufladen läuft als **Rechnung in $**, die Spieler mit USDT oder TRX bezahlen (`TOPUP_ASSETS`).
- CryptoBot verlangt pro Überweisung etwa 1 $ Mindestbetrag, deshalb `MIN_PAYOUT` nicht unter 1 setzen.
- Deine CryptoBot-App mit **TRX** aufladen, nicht nur mit USDT.

## Auszahlungen (CryptoBot)
1. Zuerst **Testnetz**: @CryptoTestnetBot → Crypto Pay → Create App → Token als `CRYPTOPAY_TOKEN`, `PAYOUT_MODE=test`. In den App-Einstellungen Überweisungen (Transfers) erlauben.
2. App mit Test-USDT aufladen, ein paar Runden laufen lassen, mit `/status` im Bot kontrollieren.
3. Dann echtes Konto über @CryptoBot, neues Token, `PAYOUT_MODE=live`.
- Jede Auszahlung hat eine eindeutige `spend_id`. Bricht etwas ab, wird beim nächsten Versuch nicht doppelt gezahlt.
- Abgelehnte Auszahlungen (z. B. Spieler hat @CryptoBot nie gestartet) gehen zurück aufs Guthaben, der Spieler bekommt eine Nachricht.
- `MAX_PAYOUT_PER_ROUND` (Standard 0 = aus) ist eine Notbremse: Wird in einer Runde mehr gutgeschrieben, wird für alle anteilig gekürzt.
- Ist eine Runde teurer als die geschätzten Werbeeinnahmen, schickt der Bot dir (`ADMIN_ID`) eine Warnung mit dem Verlust.
- Lade die CryptoBot-App immer nur mit dem Geld auf, das du für die nächsten Runden brauchst.

## Diamanten-Shop und Aufladen (`SHOP_ENABLED`)
- **Diamanten kaufen:** 100 💎 = 1 USDT (`DIAMONDS_PER_USDT` in `game.py`). Bezahlt wird zuerst aus der *Einzahlung*, dann aus dem *Guthaben*.
- **Aufladen:** 1 / 5 / 10 / 25 USDT (`TOPUP_AMOUNTS`) über eine CryptoBot-Rechnung. Das Geld landet in der *Einzahlung*, die nur für Diamanten verwendet und nicht ausgezahlt werden kann.
- Gutschrift kommt per Webhook: In @CryptoBot (bzw. @CryptoTestnetBot) → Crypto Pay → deine App → Webhooks die Adresse `https://DEINE-ADRESSE/cryptopay/webhook` eintragen. Die Signatur wird geprüft, jede Rechnung wird nur einmal gutgeschrieben. Zusätzlich gibt es in der App „Zahlung prüfen“.
- **Automatisch auszahlen** können Spieler im Wallet ausschalten, um Verdientes anzusparen und in Diamanten zu stecken.
- Telegram-Stars-Pakete gibt es zusätzlich (`STAR_PACKAGES`), ebenfalls nur mit `SHOP_ENABLED=true`.

## Wichtig vor dem Start mit echtem Geld
- **Wirtschaftlichkeit:** Die Erträge sind feste Dollar-Beträge und hängen nicht von den Werbeeinnahmen ab. In einer Simulation (Spieler sieht 10–40 Werbungen/Tag, kauft Bronze-Packs, eCPM 1,5 $) lagen die Auszahlungen nach 90 Tagen beim 10- bis 20-Fachen der Werbeeinnahmen dieses Spielers. Zum Ausgleich die Beträge in `EDITION_USD` senken, Diamanten-Belohnungen verringern, `MIN_ADS_24H` erhöhen oder die Notbremse setzen.
- **eCPM:** `ECPM_USD` dient nur dem Alarm. Die echten Einnahmen siehst du im AdsGram-Dashboard.
- **Diamanten-Shop / Aufladen:** Geld einzahlen → Diamanten → zufällige Packs → Figuren, die Krypto auszahlen, ergibt Einsatz, Zufall und Gewinn – das ist sehr nah an Glücksspiel. Dazu verwahrst du mit der Einzahlung Kundengeld, was je nach Ausgestaltung eigene Regeln auslösen kann (Zahlungsdienste, Krypto-Verwahrung). Österreich hat ein Glücksspielmonopol, und österreichische Gerichte haben Lootboxen schon als Glücksspiel eingestuft. Deshalb ist `SHOP_ENABLED=false`. Erst nach Prüfung durch einen Anwalt einschalten.
- **Steuern/Gewerbe:** Einnahmen und Auszahlungen mit dem Steuerberater klären.
