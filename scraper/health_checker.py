"""
health_checker.py — PS-0 PropertyScraper bi-weekly health check mode.

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
expected. Subsequent bi-weekly runs only re-check listings whose last check is
older than config.HEALTH_CHECK_INTERVAL_DAYS.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, List
from urllib.parse import urlparse

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
                removed = self._is_removed(url, external_id, source)
                stats["checked"] += 1

                if removed:
                    self.db.confirm_listing_removed(listing_id, first_seen)
                    stats["confirmed_removed"] += 1
                    log.info("[health_checker] REMOVED confirmed: [%s] %s",
                             source, external_id)
                else:
                    self.db.confirm_listing_active(listing_id)
                    stats["confirmed_active"] += 1
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
            "active: %d  errors: %d",
            stats["checked"],
            stats["confirmed_removed"],
            stats["confirmed_active"],
            stats["errors"],
        )
        return stats

    # ── Core detection logic ──────────────────────────────────────────────────

    def _is_removed(self, url: str, external_id: str, source: str) -> bool:
        """
        Fetch the listing URL and determine if it has been removed.
        Returns True if removed, False if still active (or uncertain).

        Detection cascade — ordered from most reliable to least:
          1. HTTP 404                                       → removed
          2. Redirect away + external_id gone from final URL
             + final URL looks like a generic page          → removed
          3. HTTP 200 with a removal phrase in body          → removed
          4. Anything else (5xx, network error, ambiguous)   → active
             (will retry next health check cycle)
        """
        try:
            resp = self.session.get(url, allow_redirects=True, timeout=15)
        except requests.exceptions.RequestException as exc:
            # Network hiccup — do not penalise the listing. Try again next cycle.
            log.debug("[health_checker] request error for %s: %s", url, exc)
            return False

        # ── 1. Hard 404 ────────────────────────────────────────────────────────
        if resp.status_code == 404:
            log.debug("[health_checker] 404 for %s", url)
            return True

        # ── 2. Redirect away from listing ─────────────────────────────────────
        # After following redirects, if the external_id is no longer in the
        # final URL AND the final URL looks like a category/search/home page,
        # the portal redirected us away from a deleted listing.
        final_url = resp.url or url
        if (final_url != url
                and external_id not in final_url
                and _looks_like_generic_page(final_url)):
            log.debug("[health_checker] redirect to generic page: %s → %s",
                      url, final_url)
            return True

        # ── 3. Removal phrase in 200 response body ─────────────────────────────
        if resp.status_code == 200:
            body_lower = resp.text.lower()
            for phrase in REMOVAL_PHRASES:
                if phrase in body_lower:
                    log.debug("[health_checker] removal phrase '%s' in %s",
                              phrase, url)
                    return True

        # ── 4. Uncertain (5xx, uncommon status, no phrase matched) ────────────
        # Default to active — false negatives (missing a removal) are
        # preferable to false positives (removing a live listing).
        return False


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