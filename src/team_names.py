"""Team-name resolution between SportsPredict / FIFA naming and free datasets.

SportsPredict gives 3-letter FIFA codes (resolved to full names via
``seed_team_codes.FIFA_CODES``). Free datasets (martj42 international results,
The Odds API, Reddit) use their own country spellings. This module maps our
canonical FIFA full names to the spellings those sources use.
"""

from src.seed_team_codes import FIFA_CODES

# Reverse lookup: 3-letter code -> canonical FIFA full name.
CODE_TO_NAME = {code: name for name, code in FIFA_CODES.items()}

# FIFA canonical name -> name used by the martj42 international-results dataset.
# Only entries that DIFFER from our canonical spelling need to be listed.
_DATASET_ALIASES = {
    "Cabo Verde": "Cape Verde",
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey",
}

# Common alternative spellings -> canonical FIFA name, so we can resolve raw
# strings coming from odds feeds / Reddit / news back to our team space.
_INBOUND_ALIASES = {
    "cape verde": "Cabo Verde",
    "czech republic": "Czechia",
    "turkey": "Türkiye",
    "usa": "United States",
    "united states of america": "United States",
    "korea republic": "South Korea",
    "south korea": "South Korea",
    "ivory coast": "Ivory Coast",
    "cote d'ivoire": "Ivory Coast",
    "côte d'ivoire": "Ivory Coast",
    "dr congo": "DR Congo",
    "democratic republic of the congo": "DR Congo",
    "iran": "Iran",
    "ir iran": "Iran",
}


def code_to_name(code_or_name: str) -> str:
    """Resolve a 3-letter FIFA code to a full name; pass through full names."""
    if not code_or_name:
        return code_or_name
    key = code_or_name.strip()
    return CODE_TO_NAME.get(key.upper(), key)


def to_dataset_name(fifa_name: str) -> str:
    """Map a canonical FIFA full name to the martj42 dataset spelling."""
    if not fifa_name:
        return fifa_name
    return _DATASET_ALIASES.get(fifa_name.strip(), fifa_name.strip())


def to_canonical(raw_name: str) -> str:
    """Best-effort: map any inbound spelling (odds feed, Reddit, news) to our
    canonical FIFA name. Normalises '&' -> 'and' so e.g. the odds feed's
    'Bosnia & Herzegovina' matches our 'Bosnia and Herzegovina'."""
    if not raw_name:
        return raw_name
    cleaned = raw_name.strip().replace(" & ", " and ")
    return _INBOUND_ALIASES.get(cleaned.lower(), cleaned)
