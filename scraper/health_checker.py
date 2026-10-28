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
expected. Subsequent three-day runs only re-check listings whose last check is
older than config.HEALTH_CHECK_INTERVAL_DAYS.

── Concurrency model ─────────────────────────────────────────────────────────
HTTP requests are made concurrently via aiohttp + asyncio. A semaphore caps
simultaneous open connections at config.HEALTH_CHECK_CONCURRENCY (default 50)
so we don't hammer portals or exhaust file descriptors.

All DB writes remain synchronous (psycopg2 / DatabaseWriter) and happen on the
main thread after the async fetch phase completes. The split is:

  Phase 1 — async HTTP  │ asyncio.gather over all candidates simultaneously
  Phase 2 — sync DB     │ serial loop: confirm_listing_removed / confirm_listing_active

This keeps DatabaseWriter completely unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable, Any
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from scraper import normaliser

import config
from scraper.db_writer import DatabaseWriter
from scraper.models import NormalisedListing

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

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


# How many concurrent HTTP connections to allow at once.
# Tune this in config.py. Lower = more polite to portals; higher = faster.
# 50 is a safe starting point — adjust down if you see 429s or connection errors.
_DEFAULT_CONCURRENCY = 50


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class _CheckResult:
    """Holds the outcome of a single async URL check, ready for DB writes."""
    listing_id:  int
    source:      str
    external_id: str
    first_seen:  object        # datetime — passed through for confirm_listing_removed
    is_removed:  bool
    observed_price: Optional[int]  # kobo, or None
    error:       Optional[str] = None
    observed_quote: Optional[NormalisedListing] = None


# ── Main class ────────────────────────────────────────────────────────────────

class HealthChecker:
    """
    Checks each candidate ACTIVE listing URL individually and confirms
    removal or continued activity via db_writer.

    The public interface (run / __init__) is identical to the old synchronous
    version. Only the HTTP layer is now async; DB writes are still synchronous.
    """

    def __init__(self, db: DatabaseWriter) -> None:
        self.db = db
        self._parsers = self._build_parsers()

    def _build_parsers(self) -> Dict:
        from scraper.parsers.propertypro import PropertyProParser
        from scraper.parsers.privateproperty import PrivatePropertyParser
        from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
        return {
            "propertypro":           PropertyProParser({}, load_robots=False),
            "privateproperty":       PrivatePropertyParser({}, load_robots=False),
            "nigeriapropertycentre": NigeriaPropertyCentreParser({}, load_robots=False),
        }

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, force_all=False, checkpoint_state=None, on_batch_complete=None):
        from scraper.traffic_guard import health_traffic
        with health_traffic():
            return self._run(force_all, checkpoint_state, on_batch_complete)

    def _run(
        self,
        force_all: bool = False,
        checkpoint_state: Optional[Dict[str, Any]] = None,
        on_batch_complete: Optional[Callable[[List[Dict], int, Dict[str, int]], None]] = None,
    ) -> Dict[str, int]:
        """
        Fetch all health-check candidates from the DB, verify them in micro-batches
        concurrently, and write results to the DB immediately after each batch completes.

        Returns a stats dict:
            {checked, confirmed_removed, confirmed_active, price_changes, errors}
        """
        # Load starting state from checkpoint if available
        if checkpoint_state:
            stats = checkpoint_state.get("stats", {
                "checked": 0, "confirmed_removed": 0, "confirmed_active": 0, "price_changes": 0, "errors": 0
            })
            candidates = checkpoint_state.get("candidates", [])
            start_idx = checkpoint_state.get("last_processed_idx", 0)
            log.info("[health_checker] Resuming health checks from checkpoint at index %d/%d", start_idx, len(candidates))
        else:
            stats = {
                "checked":           0,
                "confirmed_removed": 0,
                "confirmed_active":  0,
                "price_changes":     0,
                "errors":            0,
            }
            candidates = self.db.fetch_listings_for_health_check(force_all=force_all)
            start_idx = 0
            log.info("[health_checker] %d listings due for health check", len(candidates))

        if not candidates or start_idx >= len(candidates):
            log.info("[health_checker] Nothing to check — all listings are up to date.")
            return stats

        # Sieve remaining candidates from the start_idx
        remaining_candidates = candidates[start_idx:]
        batch_size = getattr(config, "HEALTH_CHECK_BATCH_SIZE", 50)
        batches = [remaining_candidates[i : i + batch_size] for i in range(0, len(remaining_candidates), batch_size)]
        log.info("[health_checker] Slicing %d remaining candidates into %d batches of size %d", 
                 len(remaining_candidates), len(batches), batch_size)

        current_idx = start_idx
        for batch_idx, batch in enumerate(batches, 1):
            log.info("[health_checker] Processing batch %d/%d (size: %d, index: %d)...", 
                     batch_idx, len(batches), len(batch), current_idx)

            # ── Phase 1: async HTTP (current batch) ───────────────────────────
            # All network I/O happens here concurrently for this batch. No DB calls inside.
            results: List[_CheckResult] = asyncio.run(self._run_async(batch))

            # ── Phase 2: sync DB writes (current batch) ───────────────────────
            # Serial loop: safe to call psycopg2 / DatabaseWriter as normal.
            for result in results:
                if result.error:
                    log.warning(
                        "[health_checker] error checking [%s] %s — %s",
                        result.source, result.external_id, result.error,
                    )
                    stats["errors"] += 1
                    continue

                stats["checked"] += 1

                if result.is_removed:
                    self.db.confirm_listing_removed(result.listing_id, result.first_seen)
                    stats["confirmed_removed"] += 1
                    log.info("[health_checker] REMOVED confirmed: [%s] %s",
                             result.source, result.external_id)
                else:
                    if result.observed_quote is not None:
                        quote = result.observed_quote
                        if quote.price_type in ('FOR_RENT', 'FOR_SHORT_LET'):
                            counts = stats.setdefault('rental_periods', {})
                            counts[quote.price_period_status] = counts.get(quote.price_period_status, 0) + 1
                        price_changed = self.db.confirm_listing_active(
                            result.listing_id, result.first_seen, observed_quote=result.observed_quote)
                    else:
                        price_changed = self.db.confirm_listing_active(
                            result.listing_id, result.first_seen, result.observed_price)
                    stats["confirmed_active"] += 1

                    if price_changed:
                        stats["price_changes"] += 1
                        log.info("[health_checker] PRICE_CHANGE detected: [%s] %s",
                                 result.source, result.external_id)
                    else:
                        log.debug("[health_checker] still active: [%s] %s",
                                  result.source, result.external_id)

            current_idx += len(batch)
            if on_batch_complete:
                on_batch_complete(candidates, current_idx, stats)

        log.info(
            "[health_checker] complete — checked: %d  removed: %d  "
            "active: %d  changes: %d  errors: %d",
            stats["checked"],
            stats["confirmed_removed"],
            stats["confirmed_active"],
            stats["price_changes"],
            stats["errors"],
        )
        return stats


    # ── Async orchestration ───────────────────────────────────────────────────

    async def _run_async(self, candidates: List[Dict]) -> List[_CheckResult]:
        """
        Opens a single aiohttp session shared across all requests, then fans
        out one coroutine per candidate behind a semaphore.
        """
        concurrency = getattr(config, "HEALTH_CHECK_CONCURRENCY", _DEFAULT_CONCURRENCY)
        per_domain_limit = getattr(config, "HEALTH_CHECK_PER_DOMAIN_CONCURRENCY", 3)
        global_semaphore = asyncio.Semaphore(concurrency)
        domain_semaphores = defaultdict(lambda: asyncio.Semaphore(per_domain_limit))

        # TCPConnector: limit total open sockets to the same cap. ssl=False
        # disables certificate verification for speed; set ssl=True if your
        # portals use self-signed certs that need verification.
        connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
        timeout   = aiohttp.ClientTimeout(total=20)   # per-request wall-clock timeout

        async with aiohttp.ClientSession(
            headers=HEADERS,
            connector=connector,
            timeout=timeout,
            trust_env=True,
        ) as session:
            tasks = []
            for row in candidates:
                url = row.get("url", "")
                domain = urlparse(url).netloc.lower() or row.get("source", "default")
                tasks.append(
                    self._check_with_semaphore(
                        session, global_semaphore, domain_semaphores[domain], row
                    )
                )
            # return_exceptions=True: a crashed coroutine doesn't abort the rest.
            raw = await asyncio.gather(*tasks, return_exceptions=True)

        # Unwrap any unexpected exceptions that slipped past the inner try/except.
        results: List[_CheckResult] = []
        for item, row in zip(raw, candidates):
            if isinstance(item, Exception):
                results.append(_CheckResult(
                    listing_id=row["id"],
                    source=row["source"],
                    external_id=row["external_id"],
                    first_seen=row["first_seen_at"],
                    is_removed=False,
                    observed_price=None,
                    error=f"unhandled: {item}",
                ))
            else:
                results.append(item)

        return results

    async def _check_with_semaphore(
        self,
        session:          aiohttp.ClientSession,
        global_semaphore: asyncio.Semaphore,
        domain_semaphore: asyncio.Semaphore,
        row:              Dict,
    ) -> _CheckResult:
        """
        Wraps _check_listing_async with:
          - global & domain semaphores: caps overall open connections and per-portal load
          - per-request random delay: polite jitter so we don't send a
            thundering herd at portal servers the moment we acquire the slot
          - per-listing exception handling: errors become an error-flagged result
        """
        async with global_semaphore:
            async with domain_semaphore:
                # Jitter: random delay between MIN and MAX before each request.
                # This spreads load across the portal's rate-limit windows.
                delay = random.uniform(
                    config.HEALTH_CHECK_DELAY_MIN,
                    config.HEALTH_CHECK_DELAY_MAX,
                )
                await asyncio.sleep(delay)

                listing_id  = row["id"]
                source      = row["source"]
                external_id = row["external_id"]
                url         = row["url"]
                first_seen  = row["first_seen_at"]

                try:
                    is_removed, observed_price = await self._check_listing_async(
                        session, url, external_id, source
                    )
                    return _CheckResult(
                        listing_id=listing_id,
                        source=source,
                        external_id=external_id,
                        first_seen=first_seen,
                        is_removed=is_removed,
                        observed_price=observed_price.price_kobo if hasattr(observed_price, "price_kobo") else observed_price,
                        observed_quote=observed_price if hasattr(observed_price, "price_kobo") else None,
                    )
                except Exception as exc:
                    return _CheckResult(
                        listing_id=listing_id,
                        source=source,
                        external_id=external_id,
                        first_seen=first_seen,
                        is_removed=False,
                        observed_price=None,
                        error=str(exc),
                    )

    # ── Core detection logic ──────────────────────────────────────────────────

    async def _check_listing_async(
        self,
        session:     aiohttp.ClientSession,
        url:         str,
        external_id: str,
        source:      str,
    ) -> Tuple[bool, Optional[NormalisedListing]]:
        """
        Async equivalent of the old _check_listing. Fetches the URL and returns
        (is_removed, observed_quote).
        Retries on timeout or connection errors with backoff to survive PC sleep.
        """
        max_retries = 4
        backoff_base = 2
        max_backoff_delay = getattr(config, "HEALTH_CHECK_MAX_BACKOFF_DELAY", 30.0)

        for attempt in range(max_retries + 1):
            try:
                # Set a per-request timeout to ensure we don't hang indefinitely
                request_timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, allow_redirects=True, timeout=request_timeout) as resp:
                    status    = resp.status
                    final_url = str(resp.url)

                    if status == 404:
                        log.debug("[health_checker] 404 for %s", url)
                        return True, None

                    if final_url != url and external_id not in final_url:
                        log.debug("[health_checker] redirect stripped external_id: %s → %s",
                                  url, final_url)
                        return True, None

                    if status == 200:
                        # Read body only on a 200 — saves bandwidth on error pages.
                        body = await resp.text(errors="replace")
                        body_lower = body.lower()

                        for phrase in REMOVAL_PHRASES:
                            if phrase in body_lower:
                                log.debug("[health_checker] removal phrase '%s' in %s",
                                          phrase, url)
                                return True, None

                        # Listing is confirmed active — try to extract current price.
                        observed_price = self._extract_observed_quote(body, url, source)
                        return False, observed_price

                    # Force retry on other status codes (5xx, etc.) by raising
                    resp.raise_for_status()

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                exc_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if attempt < max_retries:
                    raw_wait = (backoff_base ** attempt) + random.uniform(0, 1)
                    wait = min(raw_wait, max_backoff_delay)
                    if attempt < 2:
                        log.debug("[health_checker] Transient check error [%s] on %s (attempt %d/%d) — retrying in %.1fs",
                                  exc_detail, url, attempt + 1, max_retries + 1, wait)
                    else:
                        log.warning("[health_checker] Transient check error [%s] on %s (attempt %d/%d) — retrying in %.1fs",
                                    exc_detail, url, attempt + 1, max_retries + 1, wait)
                    await asyncio.sleep(wait)
                    continue
                log.error("[health_checker] Max check retries exceeded [%s] for %s", exc_detail, url)
                raise exc

        return False, None

    def _extract_observed_quote(self, html: str, url: str,
                                source: str) -> Optional[NormalisedListing]:
        """
        Parse current price from listing page HTML using the portal's own parser
        and the shared normaliser. Returns a typed listing, or None on parser failure.
        Pure parsing of the primary page quote; retains cadence and currency evidence.
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
            return normalised
        except Exception as exc:
            log.debug("[health_checker] price extraction failed for %s: %s", url, exc)
            return None

