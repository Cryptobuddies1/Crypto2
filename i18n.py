"""Texte des Servers und des Bots in Englisch und Deutsch. Standard: Englisch."""
DEFAULT_LANG = "en"
LANGS = ("en", "de")

TEXTS = {
    # Fehlermeldungen der App
    "no_signature":      {"en": "Missing signature", "de": "Keine Signatur"},
    "bad_signature":     {"en": "Invalid signature", "de": "Ungültige Signatur"},
    "session_expired":   {"en": "Session expired – please reopen the app", "de": "Sitzung abgelaufen – App neu öffnen"},
    "open_in_telegram":  {"en": "Please open the game in Telegram", "de": "Bitte in Telegram öffnen"},
    "unknown_action":    {"en": "Unknown action", "de": "Unbekannte Aktion"},
    "unknown_pack":      {"en": "Unknown pack", "de": "Unbekanntes Pack"},
    "starter_used":      {"en": "Starter pack already opened", "de": "Start-Pack schon geöffnet"},
    "no_diamonds":       {"en": "Not enough diamonds", "de": "Nicht genug Diamanten"},
    "no_figure":         {"en": "You don't own this figure", "de": "Figur nicht vorhanden"},
    "max_level":         {"en": "Maximum level reached", "de": "Maximale Stufe erreicht"},
    "ad_wait":           {"en": "Next video in {s} s", "de": "Nächste Werbung in {s} s"},
    "xp_wait":           {"en": "XP not full yet – {m} min left (or watch a video to fill it)",
                          "de": "XP noch nicht voll – noch {m} Min (oder per Video sofort füllen)"},
    "xp_full":           {"en": "XP is already full", "de": "XP ist schon voll"},
    "skip_limit":        {"en": "Instant fill limit reached ({n} per day)", "de": "Sofort-Füllen-Limit erreicht ({n} pro Tag)"},
    "wake_full":         {"en": "Your team is already awake for {h} h", "de": "Dein Team ist schon {h} Std wach"},
    "ad_unconfirmed":    {"en": "Video not confirmed yet – wait a moment and tap again",
                          "de": "Werbung noch nicht bestätigt – bitte kurz warten und erneut tippen"},
    "daily_done":        {"en": "Already claimed today", "de": "Heute schon abgeholt"},
    "shop_off":          {"en": "Shop is not available", "de": "Shop ist nicht aktiv"},
    "diamond_steps":     {"en": "Only in steps of {n} diamonds", "de": "Nur in Schritten von {n} Diamanten"},
    "no_balance":        {"en": "Not enough balance – top up first", "de": "Nicht genug Guthaben – lade zuerst auf"},
    "topup_off":         {"en": "Top-up is not available", "de": "Aufladen ist nicht aktiv"},
    "bad_amount":        {"en": "Invalid amount", "de": "Ungültiger Betrag"},
    "cryptobot_down":    {"en": "CryptoBot is not reachable", "de": "CryptoBot nicht erreichbar"},
    "unknown_package":   {"en": "Unknown package", "de": "Unbekanntes Paket"},
    "ads_off":           {"en": "Videos are not available yet", "de": "Videos sind noch nicht verfügbar"},
    "bad_lang":          {"en": "Unknown language", "de": "Unbekannte Sprache"},

    # Bot-Nachrichten
    "welcome": {
        "en": "Hi {name}! 👋\n\nIn <b>Crypto Buddies</b> you collect figures that earn a daily profit. "
              "Every 4 hours your earnings are credited – from $1 they are paid out automatically in TRX.\n\n"
              "🎁 Your first pack is free!",
        "de": "Hallo {name}! 👋\n\nBei <b>Crypto Buddies</b> sammelst du Figuren, die jeden Tag Dollar verdienen. "
              "Alle 4 Stunden wird gutgeschrieben, ab 1 $ automatisch in TRX ausgezahlt.\n\n"
              "🎁 Dein erstes Pack ist gratis!"},
    "invited":     {"en": "💎 You were invited: +{n} diamonds!", "de": "💎 Du wurdest eingeladen: +{n} Diamanten!"},
    "friend_joined": {"en": "👥 {name} joined with your link: +{n} diamonds! You now get {p} % of everything they earn.",
                      "de": "👥 {name} ist über deinen Link beigetreten: +{n} Diamanten! Du bekommst jetzt {p} % von allem, was dein Freund verdient."},
    "play":        {"en": "Play now", "de": "Jetzt spielen"},
    "menu_play":   {"en": "Play", "de": "Spielen"},
    "payout_sent": {"en": "💸 Payout: <b>${usd}</b> ({amount} {asset}) was sent to your @CryptoBot wallet.",
                    "de": "💸 Auszahlung: <b>{usd} $</b> ({amount} {asset}) wurden an deine @CryptoBot-Wallet geschickt."},
    "payout_failed": {"en": "⚠️ Your payout could not be sent. Open @CryptoBot once and press Start – it will then work automatically in the next round.",
                      "de": "⚠️ Deine Auszahlung konnte nicht gesendet werden. Öffne einmal @CryptoBot und drücke Start, dann klappt es in der nächsten Runde automatisch."},
    "topup_ok":    {"en": "✅ ${amount} topped up – you can buy diamonds now.",
                    "de": "✅ {amount} $ aufgeladen – du kannst jetzt Diamanten kaufen."},
    "stars_ok":    {"en": "💎 +{n} diamonds credited!", "de": "💎 +{n} Diamanten gutgeschrieben!"},
    "stars_title": {"en": "{n} diamonds", "de": "{n} Diamanten"},
    "stars_desc":  {"en": "{n} diamonds for Crypto Buddies", "de": "{n} Diamanten für Crypto Buddies"},
    "payout_comment": {"en": "Crypto Buddies payout", "de": "Crypto Buddies Auszahlung"},
    "topup_desc":  {"en": "Crypto Buddies: top up ${amount}", "de": "Crypto Buddies: {amount} $ aufladen"},
    "lang_cmd":    {"en": "Choose your language:", "de": "Wähle deine Sprache:"},
    "lang_set":    {"en": "Language set to English 🇬🇧", "de": "Sprache auf Deutsch gestellt 🇩🇪"},
}


def tr(lang: str | None, key: str, **kw) -> str:
    t = TEXTS[key].get(lang or DEFAULT_LANG) or TEXTS[key][DEFAULT_LANG]
    return t.format(**kw) if kw else t
