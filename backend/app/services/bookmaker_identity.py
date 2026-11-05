"""Explicit legacy title aliases; never infer identity from a changed title."""
BOOKMAKERS = {
    "fanduel": ("FanDuel",), "draftkings": ("DraftKings",),
    "betmgm": ("BetMGM",), "williamhill_us": ("Caesars", "William Hill (US)"),
    "betrivers": ("BetRivers",), "bovada": ("Bovada",),
    "betonlineag": ("BetOnline.ag",), "betus": ("BetUS",),
    "mybookieag": ("MyBookie.ag",), "lowvig": ("LowVig.ag",),
    "espnbet": ("ESPN BET",), "fanatics": ("Fanatics", "Fanatics Sportsbook"),
    "hardrockbet": ("Hard Rock Bet",), "hardrockbet_fl": ("Hard Rock Bet (FL)",),
    "ballybet": ("Bally Bet",),
    "fliff": ("Fliff",),
}


def legacy_key(title):
    matches = [key for key, titles in BOOKMAKERS.items() if title in titles]
    return matches[0] if len(matches) == 1 else None


def resolve_book(offers, key):
    matches = [offer for offer in offers if offer.provider_bookmaker_key == key]
    if not matches:
        matches = [offer for offer in offers if not offer.provider_bookmaker_key
                   and legacy_key(offer.sportsbook) == key]
    if len(matches) > 1:
        raise ValueError("Ambiguous legacy bookmaker identity; manual remediation required")
    return matches[0] if matches else None
