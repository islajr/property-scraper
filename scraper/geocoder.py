"""
geocoder.py — Neighbourhood-level geocoding with two-layer cache.

Uses Nominatim (OpenStreetMap) — completely free, no API key, no payment.
https://nominatim.openstreetmap.org

Two-layer cache strategy:
  Layer 1 (memory): Dict keyed on (neighbourhood_lower, city_lower).
                    Lives for the duration of one scraper run.
                    Pre-loaded from Layer 2 at startup.
  Layer 2 (DB):     raw_data.geocode_cache table on Supabase.
                    Persists across runs. After 4-6 weeks the vast majority
                    of new listings hit the cache with zero API calls.

Nominatim fair-use policy: max 1 request/second, must set a descriptive
User-Agent. With ~60-80 unique (neighbourhood, city) pairs across Lagos
and Abuja, you will exhaust new geocoding requests within the first 2 runs.
"""

from __future__ import annotations

import time
import logging
import dataclasses
from typing import Dict, List, Optional, Tuple

import requests

from scraper.models import NormalisedListing
import config

log = logging.getLogger(__name__)

CacheKey = Tuple[str, str]   # (neighbourhood_lower, city_lower)

NOMINATIM_URL   = "https://nominatim.openstreetmap.org/search"
NOMINATIM_AGENT = f"PropertyScraper/1.0 (nigerian-proptech-research; {config.NOMINATIM_CONTACT_EMAIL})"
NOMINATIM_DELAY = 1.1   # seconds — fair-use: max 1 req/sec


class Geocoder:
    def __init__(self, db):
        self.db      = db
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": NOMINATIM_AGENT})
        self.memory_cache: Dict[CacheKey, Tuple[float, float]] = {}
        self._preload_from_db()

    def enrich(self, listings: List[NormalisedListing]) -> List[NormalisedListing]:
        enriched = []
        for listing in listings:
            lat, lng = self._geocode(listing.neighbourhood, listing.city)
            enriched.append(dataclasses.replace(listing, lat=lat, lng=lng, geocoded=(lat is not None)))
        return enriched

    def _preload_from_db(self) -> None:
        try:
            rows = self.db.fetch_geocode_cache()
            self.memory_cache.update(rows)
            log.info("Geocode cache pre-loaded: %d entries from DB", len(rows))
        except Exception as exc:
            log.warning("Could not pre-load geocode cache from DB: %s", exc)

    def _geocode(self, neighbourhood: Optional[str], city: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
        if not neighbourhood:
            return None, None

        key: CacheKey = ((neighbourhood or "").lower(), (city or "").lower())

        if key in self.memory_cache:
            return self.memory_cache[key]

        # Cache miss — call Nominatim
        query  = f"{neighbourhood}, {city or 'Nigeria'}, Nigeria"
        params = {"q": query, "format": "json", "limit": 1, "countrycodes": "ng", "addressdetails": 0}

        time.sleep(NOMINATIM_DELAY)  # Nominatim fair-use: 1 req/sec

        try:
            resp = self.session.get(NOMINATIM_URL, params=params, timeout=10)
            resp.raise_for_status()
            results = resp.json()
        except Exception as exc:
            log.error("Nominatim error for %r: %s", query, exc)
            return None, None

        if not results:
            log.debug("No Nominatim result for: %r", query)
            return None, None

        lat = float(results[0]["lat"])
        lng = float(results[0]["lon"])

        self.memory_cache[key] = (lat, lng)
        try:
            self.db.save_geocode_cache(neighbourhood, city or "", lat, lng)
        except Exception as exc:
            log.warning("Failed to persist geocode cache entry: %s", exc)

        log.debug("Geocoded %r -> (%.4f, %.4f)", query, lat, lng)
        return lat, lng