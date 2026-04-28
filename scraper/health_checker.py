"""
health_checker.py — PS-0 PropertyScraper three-day health check mode.

Fetches each ACTIVE listing URL individually to confirm whether it is still live.
Only this module (via db_writer.confirm_listing_removed) may set
listing_status = 'REMOVED'. The main feed scraper never marks listings removed
directly — it only increments missed_run_count when a listing ages off the
recent feed.

Run via:
    python -m scraper.orchestrator --health-check
    ./run.sh --health-check

The first run after deployment will check all ACTIVE listings
(last_health_check_at IS NULL). On a large DB this may take a while — that is
expected. Subsequent three-day runs runs only re-check listings whose last check is
older than config.HEALTH_CHECK_INTERVAL_DAYS.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from scraper import normaliser

import requests

import config
from scraper.db_writer import DatabaseWriter

log = logging.getLogger(__name__)

# Browser-like headers to avoid trivial bot blocks.
HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Phrases in page content that signal the listing is gone.
# All matched case-insensitively against the lowercased response body.
# Keep this list conservative — false positives (marking active listings as
# removed) are worse than false negatives (missing a removal for one cycle).
REMOVAL_PHRASES: List[str] = [
    "listing not found",
    "property not found",
    "this listing has been removed",
    "this listing is no longer available",
    "listing has expired",
    "this property has been sold",
    "advert not found",
    "this ad has been deleted",
    "this ad no longer exists",
    "this property is no longer available",
    "page not found",
    "404 - page not found",
    "oops! page not found",
    "the page you are looking for",          # generic 404 copy used by several portals
]

# URL path fragments that indicate the request landed on a non-listing page
# after a redirect. Used in conjunction with external_id absence to confirm
# the redirect is meaningful (not just a URL normalisation).
GENERIC_PAGE_PATH_FRAGMENTS: List[str] = [
    "/property-for-sale",
    "/property-for-rent",
    "/properties",
    "/search",
    "/listings",
    "/results",
    "/adverts",
    "/real-estate",
    "/showtype",
]


class HealthChecker:
    """
    Checks each candidate ACTIVE listing URL individually and confirms
    removal or continued activity via db_writer.
    """

    def __init__(self, db: DatabaseWriter) -> None:
        self.db = db
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        # Parsers instantiated once — robots.txt loaded once per run, not per listing.
        # Empty active_listings: we are not doing feed scraping, no consecutive-known logic.
        self._parsers = self._build_parsers()

    def _build_parsers(self) -> Dict:
        from scraper.parsers.propertypro import PropertyProParser
        from scraper.parsers.privateproperty import PrivatePropertyParser
        from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
        return {
            "propertypro":           PropertyProParser({}),
            "privateproperty":       PrivatePropertyParser({}),
            "nigeriapropertycentre": NigeriaPropertyCentreParser({}),
        }

    def run(self) -> Dict[str, int]:
        """
        Fetch all health-check candidates from the DB, verify each URL,
        and update the DB accordingly.

        Returns a stats dict:
            {checked, confirmed_removed, confirmed_active, errors}
        """
        stats: Dict[str, int] = {
            "checked":           0,
            "confirmed_removed": 0,
            "confirmed_active":  0,
            "price_changes":     0, 
            "errors":            0,
        }

        candidates = self.db.fetch_listings_for_health_check()
        log.info("[health_checker] %d listings due for health check", len(candidates))

        if not candidates:
            log.info("[health_checker] Nothing to check — all listings are up to date.")
            return stats

        for row in candidates:
            listing_id  = row["id"]
            source      = row["source"]
            external_id = row["external_id"]
            url         = row["url"]
            first_seen  = row["first_seen_at"]

            try:
                is_removed, observed_price = self._check_listing(url, external_id, source)
                stats["checked"] += 1

                if is_removed:
                    self.db.confirm_listing_removed(listing_id, first_seen)
                    stats["confirmed_removed"] += 1
                    log.info("[health_checker] REMOVED confirmed: [%s] %s",
                             source, external_id)
                else:
                    price_changed = self.db.confirm_listing_active(listing_id, observed_price)
                    stats["confirmed_active"] += 1
                    
                    if price_changed:
                        stats["price_changes"] += 1
                        log.info("[health_checker] PRICE_CHANGE detected: [%s] %s",
                                 source, external_id)
                    else:
                        log.debug("[health_checker] still active: [%s] %s",
                                source, external_id)

            except Exception as exc:
                # Per-listing errors must not abort the whole run.
                log.warning("[health_checker] error checking [%s] %s — %s",
                            source, external_id, exc, exc_info=True)
                stats["errors"] += 1

            # Polite delay between requests.
            time.sleep(random.uniform(
                config.HEALTH_CHECK_DELAY_MIN,
                config.HEALTH_CHECK_DELAY_MAX,
            ))

        log.info(
            "[health_checker] complete — checked: %d  removed: %d  "
            "active: %d  changes: %d    errors: %d",
            stats["checked"],
            stats["confirmed_removed"],
            stats["confirmed_active"],
            stats["price_changes"],
            stats["errors"],
        )
        return stats

    # ── Core detection logic ──────────────────────────────────────────────────

    def _check_listing(self, url: str, external_id: str,
                       source: str) -> Tuple[bool, Optional[int]]:
        """
        Fetch the listing URL and return (is_removed, observed_price_kobo).
        observed_price_kobo is None when the listing is removed, or when price
        extraction fails — the latter is non-fatal, the listing stays active.
        """
        try:
            resp = self.session.get(url, allow_redirects=True, timeout=15)
        except requests.exceptions.RequestException as exc:
            log.debug("[health_checker] request error for %s: %s", url, exc)
            return False, None

        if resp.status_code == 404:
            log.debug("[health_checker] 404 for %s", url)
            return True, None

        final_url = resp.url or url
        if (final_url != url
                and external_id not in final_url
                and _looks_like_generic_page(final_url)):
            log.debug("[health_checker] redirect to generic page: %s → %s",
                      url, final_url)
            return True, None

        if resp.status_code == 200:
            body_lower = resp.text.lower()
            for phrase in REMOVAL_PHRASES:
                if phrase in body_lower:
                    log.debug("[health_checker] removal phrase '%s' in %s",
                              phrase, url)
                    return True, None

            # Listing is confirmed active — try to extract current price from the
            # same HTML we already fetched. Failure here is non-fatal.
            observed_price = self._extract_observed_price(resp.text, url, source)
            return False, observed_price

        return False, None

    def _extract_observed_price(self, html: str, url: str,
                                source: str) -> Optional[int]:
        """
        Parse current price from listing page HTML using the portal's own parser
        and the shared normaliser. Returns kobo, or None on any failure.
        """
        parser = self._parsers.get(source)
        if parser is None:
            return None
        try:
            soup = BeautifulSoup(html, "html.parser")
            raw  = parser.parse_listing(soup, url)
            if raw is None:
                return None
            normalised = normaliser.normalise(raw)
            if normalised.price_parse_failed:
                return None
            return normalised.price_kobo
        except Exception as exc:
            log.debug("[health_checker] price extraction failed for %s: %s", url, exc)
            return None


# ── Module-level helpers ──────────────────────────────────────────────────────

def _looks_like_generic_page(url: str) -> bool:
    """
    Returns True when a URL appears to be a homepage, search results page,
    or category index rather than an individual listing detail page.

    Used only after confirming that the external_id is absent from the URL,
    so a false positive here (e.g., a listing URL that happens to contain
    '/search') is extremely unlikely.
    """
    parsed  = urlparse(url.lower())
    path    = parsed.path.rstrip("/")

    # Bare domain with no meaningful path — definitely a homepage.
    if path in ("", "/"):
        return True

    # Fragment-only navigation (/#section).
    if not path or path.startswith("/#"):
        return True

    # Paths that are characteristic of listing index / search pages.
    for fragment in GENERIC_PAGE_PATH_FRAGMENTS:
        if path.startswith(fragment) or fragment in path:
            return True

    return False