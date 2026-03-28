"""
normaliser.py — Converts RawListing → NormalisedListing.

All transformations are pure functions with no side effects and no I/O.
This makes normalisation independently testable against HTML fixtures
without a database or network connection.

Key rules (enforced platform-wide):
  - All monetary values stored as BIGINT kobo (price_naira × 100).
  - All floor areas stored in square metres (sqm). Convert from sqft where needed.
  - Neighbourhood names normalised against canonical list via fuzzy match.
  - Diaspora signal detected via regex against description — no ML required.
"""

from __future__ import annotations

import re
import difflib
import logging
from typing import Optional, Tuple

import config
from scraper.models import RawListing, NormalisedListing

log = logging.getLogger(__name__)

# ── Diaspora signal patterns ───────────────────────────────────────────────────
DIASPORA_PATTERNS = re.compile(
    r'\b(diaspora|dollar[\s-]denominated|forex\s+accepted|forex\s+payment\s+accepted|'
    r'payment\s+in\s+usd|suitable\s+for\s+returnees|diaspora[\s-]friendly|'
    r'diaspora[\s-]targeted|expatriates?|returning\s+nig(?:erian)?|'
    r'payment\s+in\s+foreign\s+currency|usd\s+payment)\b',
    re.IGNORECASE
)

# ── Property type normalisation map ───────────────────────────────────────────
PROPERTY_TYPE_MAP = {
    # Residential
    "detached duplex":       "DETACHED_DUPLEX",
    "semi-detached duplex":  "SEMI_DETACHED_DUPLEX",
    "semi detached duplex":  "SEMI_DETACHED_DUPLEX",
    "terraced duplex":       "TERRACED_DUPLEX",
    "terraced bungalow":     "TERRACED_BUNGALOW",
    "duplex":                "DETACHED_DUPLEX",
    "detached bungalow":     "DETACHED_BUNGALOW",
    "semi-detached bungalow":"SEMI_DETACHED_BUNGALOW",
    "flat / apartment":      "FLAT_APARTMENT",
    "flat/apartment":        "FLAT_APARTMENT",
    "apartment":             "FLAT_APARTMENT",
    "flat":                  "FLAT_APARTMENT",
    "studio":                "STUDIO",
    "studio apartment":      "STUDIO",
    "mini flat":             "MINI_FLAT",
    "miniflat":              "MINI_FLAT",
    "penthouse":             "PENTHOUSE",
    "mansion":               "MANSION",
    "villa":                 "VILLA",
    # Commercial
    "office space":          "OFFICE",
    "warehouse":             "WAREHOUSE",
    "shop":                  "COMMERCIAL_SHOP",
    "showroom":              "SHOWROOM",
    "commercial property":   "COMMERCIAL_OTHER",
    # Land
    "land":                  "LAND",
    "plot of land":          "LAND",
    "serviced land":         "LAND_SERVICED",
}

# ── Price type normalisation ───────────────────────────────────────────────────
RENT_KEYWORDS = re.compile(r'\b(rent|per\s+year|\/year|per\s+annum|p\.?a\.?|lease|to\s+let)\b', re.IGNORECASE)
SALE_KEYWORDS = re.compile(r'\b(sale|for\s+sale|outright|buy|purchase)\b', re.IGNORECASE)

# ── City normalisation ─────────────────────────────────────────────────────────
CITY_PATTERNS = {
    "LAGOS":  re.compile(r'\b(lagos|lekki|victoria\s+island|ikoyi|ikeja|surulere|yaba)\b', re.IGNORECASE),
    "ABUJA":  re.compile(r'\b(abuja|fct|maitama|asokoro|wuse|garki|gwarinpa)\b', re.IGNORECASE),
    "PH":     re.compile(r'\b(port\s+harcourt|p\.?h\.?)\b', re.IGNORECASE),
    "ENUGU":  re.compile(r'\benugu\b', re.IGNORECASE),
    "KANO":   re.compile(r'\bkano\b', re.IGNORECASE),
    "IBADAN": re.compile(r'\bibadan\b', re.IGNORECASE),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═══════════════════════════════════════════════════════════════════════════════

def normalise(raw: RawListing) -> NormalisedListing:
    """Convert a RawListing to a fully typed NormalisedListing."""
    price_kobo, price_parse_failed = parse_price(raw.raw_price)
    price_type                     = parse_price_type(raw.raw_price_type, raw.title, raw.description)
    property_type                  = normalise_property_type(raw.property_type_raw)
    bedrooms                       = parse_integer(raw.raw_bedrooms)
    bathrooms                      = parse_integer(raw.raw_bathrooms)
    floor_area_sqm                 = parse_floor_area_sqm(raw.raw_floor_area)
    floor_area_source              = "PORTAL" if floor_area_sqm is not None else "NONE"
    neighbourhood, nb_normalised   = normalise_neighbourhood(raw.raw_address)
    city                           = infer_city(raw.raw_address, raw.title)
    diaspora                       = is_diaspora_targeted(raw.description)

    # property_type fallback: infer from title, and the description
    if property_type is None:
        property_type = normalise_property_type(raw.title) or normalise_property_type(raw.description)

    return NormalisedListing(
        external_id              = raw.external_id,
        source                   = raw.source,
        url                      = raw.url,
        title                    = raw.title,
        description              = raw.description,
        price_kobo               = price_kobo,
        price_parse_failed       = price_parse_failed,
        price_type               = price_type,
        property_type            = property_type,
        bedrooms                 = bedrooms,
        bathrooms                = bathrooms,
        floor_area_sqm           = floor_area_sqm,
        floor_area_source        = floor_area_source,
        raw_address              = raw.raw_address,
        neighbourhood            = neighbourhood,
        neighbourhood_normalised = nb_normalised,
        city                     = city,
        lat                      = None,
        lng                      = None,
        geocoded                 = False,
        agent_name               = raw.agent_name,
        diaspora_targeted        = diaspora,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Price parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_price(raw: Optional[str]) -> Tuple[Optional[int], bool]:
    """
    Convert any common Nigerian price string to kobo (int).
    Returns (price_kobo, parse_failed).

    Handles:
      "₦45,000,000"       → 4_500_000_000
      "45M"               → 4_500_000_000
      "45.5M"             → 4_550_000_000
      "45 million"        → 4_500_000_000
      "45 million naira"  → 4_500_000_000
      "4500000000"        → 4_500_000_000 (already-kobo heuristic: > ₦10B naira)
      None / ""           → (None, True)
      "Price on Request"  → (None, True)
    """
    if not raw or not raw.strip():
        return None, True

    cleaned = (
        raw
        .replace(",", "")
        .replace("₦", "")
        .replace("N", "")
        .replace("NGN", "")
        .replace("naira", "")
        .replace("Naira", "")
        .strip()
    )

    # "45M" / "45.5M" — only trigger when M is immediately after a digit
    # Guards against "per annum" whose cleaned form ends with 'm'
    upper = cleaned.upper()
    if upper.endswith("M") and len(upper) >= 2 and upper[-2].isdigit():
        try:
            naira = float(cleaned[:-1]) * 1_000_000
            return int(naira * 100), False
        except ValueError:
            return None, True

    # "45B" / "1.5B" (billions — rare but occurs for commercial)
    if cleaned.upper().endswith("B"):
        try:
            naira = float(cleaned[:-1]) * 1_000_000_000
            return int(naira * 100), False
        except ValueError:
            return None, True

    # "45 million" / "45.5 million"
    million_match = re.search(r'([\d.]+)\s*million', cleaned, re.IGNORECASE)
    if million_match:
        try:
            return int(float(million_match.group(1)) * 1_000_000 * 100), False
        except ValueError:
            return None, True

    # Plain numeric — treat as naira unconditionally
    numeric_match = re.search(r'[\d.]+', cleaned)
    if numeric_match:
        try:
            value = float(numeric_match.group())
            return int(value * 100), False   # naira → kobo
        except ValueError:
            return None, True

    log.debug("Price parse failed for: %r", raw)
    return None, True


# ═══════════════════════════════════════════════════════════════════════════════
# Floor area
# ═══════════════════════════════════════════════════════════════════════════════

def parse_floor_area_sqm(raw: Optional[str]) -> Optional[float]:
    """
    Convert any floor area string to square metres.
    Handles sqm, sqft, sq ft, m², sq.m.
    Returns None if field absent or unparseable.
    """
    if not raw:
        return None

    sqm_pattern  = re.compile(r'([\d,]+\.?\d*)\s*(?:sqm|sq\.?\s*m\b|m²)', re.IGNORECASE)
    sqft_pattern = re.compile(r'([\d,]+\.?\d*)\s*(?:sqft|sq\.?\s*ft\b)', re.IGNORECASE)

    if m := sqm_pattern.search(raw):
        return float(m.group(1).replace(",", ""))
    if m := sqft_pattern.search(raw):
        sqft = float(m.group(1).replace(",", ""))
        return round(sqft * 0.0929, 1)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Integer extraction (bedrooms, bathrooms)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_integer(raw: Optional[str]) -> Optional[int]:
    """Extract first integer from a string like '3 Bedrooms' → 3."""
    if not raw:
        return None
    m = re.search(r'\d+', raw)
    return int(m.group()) if m else None


# ═══════════════════════════════════════════════════════════════════════════════
# Price type
# ═══════════════════════════════════════════════════════════════════════════════

def parse_price_type(raw_type: Optional[str],
                     title: Optional[str],
                     description: Optional[str]) -> Optional[str]:
    """
    Classify as FOR_SALE or FOR_RENT.
    Checks raw_type first as a direct value, then falls back to keyword
    scanning across raw_type, title, and description.
    """
    # Direct value — parsers that already know the type pass it explicitly
    if raw_type in ("FOR_SALE", "FOR_RENT", "FOR_SHORT_LET"):
        return raw_type

    combined = " ".join(filter(None, [raw_type, title, description]))
    if RENT_KEYWORDS.search(combined):
        return "FOR_RENT"
    if SALE_KEYWORDS.search(combined):
        return "FOR_SALE"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Property type
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_property_type(raw: Optional[str]) -> Optional[str]:
    """Map raw portal property type string to canonical enum value."""
    if not raw:
        return None
    key = raw.lower().strip()
    if key in PROPERTY_TYPE_MAP:
        return PROPERTY_TYPE_MAP[key]
    # Attempt partial match
    for portal_type, canonical in PROPERTY_TYPE_MAP.items():
        if portal_type in key:
            return canonical
    return raw.upper().replace(" ", "_")[:40]  # store unknown types in a consistent form


# ═══════════════════════════════════════════════════════════════════════════════
# Neighbourhood normalisation
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_neighbourhood(raw_address: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Extract and normalise neighbourhood from raw address string.

    Strategy:
      1. Check each token/phrase in raw_address against canonical list.
      2. Use difflib fuzzy match (cutoff 0.80) to handle spelling variants.
         e.g. "Lekki Ph1", "Lekki ph 1", "Lekki Phase1" → "Lekki Phase 1"
      3. If no canonical match found, return raw address as neighbourhood
         with neighbourhood_normalised=False.

    Returns: (neighbourhood_str, was_normalised)
    """
    if not raw_address:
        return None, False

    canonical = config.CANONICAL_NEIGHBOURHOODS

    # Try exact match first (case-insensitive)
    addr_lower = raw_address.lower()
    for nb in canonical:
        if nb.lower() in addr_lower:
            return nb, True

    # Fuzzy match against each word/phrase chunk in the address
    # Split on comma and slash as neighbourhood delimiters
    chunks = re.split(r'[,/]', raw_address)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        matches = difflib.get_close_matches(chunk, canonical, n=1, cutoff=0.80)
        if matches:
            return matches[0], True

    # No canonical match — store raw (truncated to 60 chars per schema)
    return raw_address[:60], False


# ═══════════════════════════════════════════════════════════════════════════════
# City inference
# ═══════════════════════════════════════════════════════════════════════════════

def infer_city(raw_address: Optional[str], title: Optional[str]) -> Optional[str]:
    """Infer city from address and title string."""
    combined = " ".join(filter(None, [raw_address, title]))
    for city, pattern in CITY_PATTERNS.items():
        if pattern.search(combined):
            return city
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Diaspora signal
# ═══════════════════════════════════════════════════════════════════════════════

def is_diaspora_targeted(description: Optional[str]) -> bool:
    """
    Lightweight regex check for diaspora/forex buyer signals.
    No ML — intentionally a simple pass at extraction time.
    """
    return bool(DIASPORA_PATTERNS.search(description or ""))