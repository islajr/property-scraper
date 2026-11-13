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
from dataclasses import asdict
from scraper.pricing import parse_terms, parse_amount, SHORT_LET
import difflib
import logging
from typing import Optional, Tuple

import config
from scraper.models import RawListing, NormalisedListing
from scraper.property_types import classify

log = logging.getLogger(__name__)

# ── Diaspora signal patterns ───────────────────────────────────────────────────
DIASPORA_PATTERNS = re.compile(
    r'\b(diaspora|dollar[\s-]denominated|forex\s+accepted|forex\s+payment\s+accepted|'
    r'payment\s+in\s+usd|suitable\s+for\s+returnees|diaspora[\s-]friendly|'
    r'diaspora[\s-]targeted|expatriates?|returning\s+nig(?:erian)?|'
    r'payment\s+in\s+foreign\s+currency|usd\s+payment)\b',
    re.IGNORECASE
)

# ── Price type normalisation ───────────────────────────────────────────────────
RENT_KEYWORDS = re.compile(r'\b(rent|per\s+year|\/year|per\s+annum|p\.?a\.?|lease|to\s+let)\b', re.IGNORECASE)
SALE_KEYWORDS = re.compile(r'\b(sale|for\s+sale|outright|buy|purchase)\b', re.IGNORECASE)

# ── City normalisation ─────────────────────────────────────────────────────────
CITY_PATTERNS = {
    "LAGOS":        re.compile(r'\b(lagos|lekki|victoria\s+island|ikoyi|ikeja|surulere|yaba)\b', re.IGNORECASE),
    "ABUJA":        re.compile(r'\b(abuja|fct|maitama|asokoro|wuse|garki|gwarinpa)\b', re.IGNORECASE),
    "PH":           re.compile(r'\b(port\s+harcourt|p\.?h\.?)\b', re.IGNORECASE),
    "ENUGU":        re.compile(r'\benugu\b', re.IGNORECASE),
    "KANO":         re.compile(r'\bkano\b', re.IGNORECASE),
    "IBADAN":       re.compile(r'\bibadan\b', re.IGNORECASE),
    "IMO":          re.compile(r'\bimo\b', re.IGNORECASE), 
    "OGUN":         re.compile(r'\bogun\b', re.IGNORECASE), 
    "EDO":          re.compile(r'\b(edo|benin)\b', re.IGNORECASE), 
    "NASSARAWA":    re.compile(r'\bnassarawa\b', re.IGNORECASE)
        
}


# ═══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═══════════════════════════════════════════════════════════════════════════════

def normalise(raw: RawListing) -> NormalisedListing:
    """Convert a RawListing to a fully typed NormalisedListing."""
    price_kobo, price_parse_failed = parse_price(raw.raw_price_text or raw.raw_price)
    price_type                     = parse_price_type(raw.raw_price_type, raw.title, raw.description)
    terms = parse_terms(raw.raw_price_text or raw.raw_price, price_type)
    property_classification        = classify(raw.property_type_raw, raw.title, raw.description,
                                             raw.property_type_raw_source)
    bedrooms                       = parse_integer(raw.raw_bedrooms)
    bathrooms                      = parse_integer(raw.raw_bathrooms)
    floor_area_sqm                 = parse_floor_area_sqm(raw.raw_floor_area)
    floor_area_source              = "PORTAL" if floor_area_sqm is not None else "NONE"
    neighbourhood, nb_normalised   = normalise_neighbourhood(raw.raw_address)
    city                           = infer_city(raw.raw_address, raw.title)
    diaspora                       = is_diaspora_targeted(raw.description)

    return NormalisedListing(
        external_id              = raw.external_id,
        source                   = raw.source,
        url                      = raw.url,
        title                    = raw.title,
        description              = raw.description,
        price_kobo               = price_kobo,
        price_parse_failed       = price_parse_failed,
        price_type               = price_type,
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
        **asdict(property_classification),
        **asdict(terms),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Price parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_price(raw: Optional[str]) -> Tuple[Optional[int], bool]:
    """Parse the advertised positive NGN amount exactly; do not convert cadence or FX.

    Missing, non-NGN, ranged, fractional-kobo, and BIGINT-overflow amounts fail.
    """
    return parse_amount(raw)


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
    Classify as FOR_SALE, FOR_RENT, or FOR_SHORT_LET.
    Checks raw_type first as a direct value, then falls back to keyword
    scanning across raw_type, title, and description.
    """
    # Direct value — parsers that already know the type pass it explicitly
    if raw_type in ("FOR_SALE", "FOR_RENT", "FOR_SHORT_LET"):
        return raw_type

    combined = " ".join(filter(None, [raw_type, title, description]))
    if SHORT_LET.search(combined):
        return "FOR_SHORT_LET"
    if RENT_KEYWORDS.search(combined):
        return "FOR_RENT"
    if SALE_KEYWORDS.search(combined):
        return "FOR_SALE"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Property type
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_property_type(raw: Optional[str]) -> Optional[str]:
    """Compatibility helper; full decisions and unresolved markers use classify()."""
    return classify(raw).property_type


# ═══════════════════════════════════════════════════════════════════════════════
# Neighbourhood normalisation
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_for_match(text: str) -> str:
    """Helper to normalise text for matching (lowercase, strip non-alphanumeric, collapse spaces)."""
    if not text:
        return ""
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', text.lower())
    return " ".join(cleaned.split())


def _clean_noise(text: str) -> str:
    """Helper to strip common noise words from matching comparison."""
    cleaned = _clean_for_match(text)
    noise_words = [
        "estate", "estates", "extension", "extensions", "phase", "ph", "district", "districts",
        "zone", "zones", "area", "areas", "street", "st", "road", "rd", "avenue", "ave",
        "close", "cl", "court", "ct", "layout", "gardens", "garden", "villas", "villa",
        "axis", "stop", "bus stop"
    ]
    pattern = r'\b(' + '|'.join(noise_words) + r')\b'
    cleaned = re.sub(pattern, ' ', cleaned)
    return " ".join(cleaned.split())


def normalise_neighbourhood(raw_address: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Extract and normalise neighbourhood from raw address string.

    Strategy cascading tiers:
      1. Cleaned Exact Match: Substring search (case/punctuation-insensitive).
      2. Noise-Insensitive Substring Match: Strips suffixes/prefixes (Estate, Phase, etc.) from both sides.
      3. Chunk-Level Noise-Free Fuzzy Match: Splits on delimiters and fuzzy matches chunk segments.
      4. Word-Level Fuzzy Match Fallback: Compares individual words (len >= 4) using difflib SequenceMatcher
         to capture typos/variations (e.g. Gwarimpa/Gwarinpa, Mabuchi/Mabushi).

    Returns: (neighbourhood_str, was_normalised)
    """
    if not raw_address:
        return None, False

    # Sort canonical list by length descending to ensure longer/more specific matches are checked first
    canonical = sorted(config.CANONICAL_NEIGHBOURHOODS, key=len, reverse=True)

    # 1. Exact cleaned match
    addr_clean = _clean_for_match(raw_address)
    for nb in canonical:
        nb_clean = _clean_for_match(nb)
        if nb_clean and nb_clean in addr_clean:
            return nb, True

    # 2. Suffix/noise-insensitive match
    addr_noise_free = _clean_noise(raw_address)
    if addr_noise_free:
        for nb in canonical:
            nb_noise_free = _clean_noise(nb)
            if nb_noise_free and nb_noise_free in addr_noise_free:
                if len(nb_noise_free) > 2:
                    return nb, True

    # 3. Chunk-level fuzzy match
    chunks = re.split(r'[,/]', raw_address)
    for chunk in chunks:
        chunk_clean = _clean_noise(chunk)
        if not chunk_clean or len(chunk_clean) < 3:
            continue
        
        for nb in canonical:
            nb_clean = _clean_noise(nb)
            if not nb_clean:
                continue
            
            ratio = difflib.SequenceMatcher(None, chunk_clean, nb_clean).ratio()
            if ratio >= 0.85:
                return nb, True

    # 4. Word-level fuzzy fallback (handles typos/variations)
    words = [w for w in addr_clean.split() if len(w) >= 4]
    for word in words:
        for nb in canonical:
            nb_clean = _clean_for_match(nb)
            if len(nb_clean) >= 4 and abs(len(word) - len(nb_clean)) <= 1:
                ratio = difflib.SequenceMatcher(None, word, nb_clean).ratio()
                if ratio >= 0.85:
                    return nb, True

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
