"""
parsers/base_parser.py — Shared scraping infrastructure for all portal parsers.

Provides:
  - requests.Session with realistic browser headers (one session per thread)
  - robots.txt compliance via urllib.robotparser
  - Randomised inter-request delay (2-5 seconds)
  - Retry logic with exponential backoff + jitter (3 retries on 429/timeout)
  - Pagination that is strictly sequential (page N determines page N+1's URLs)
  - Per-page concurrent listing fetches via ThreadPoolExecutor

Each portal subclass implements only:
  - get_listing_urls(page_soup) → List[str]
  - parse_listing(soup, url)    → RawListing
  - next_page_url(base_url, page_number) → Optional[str]

── Concurrency model ─────────────────────────────────────────────────────────
Pagination MUST remain sequential: page 3's URLs are only known after page 2
is fetched, and the consecutive_known early-exit depends on observing listings
in feed order. Parallelising across pages would break both of these.

What IS parallelisable: the individual listing-page fetches within a single
search-results page. Once we have the URL list for page N, all those listing
fetches are independent and can go out simultaneously.

Flow per search feed:
  fetch page 1 (sequential)
    → extract listing URLs
    → fan out listing fetches concurrently (ThreadPoolExecutor)
    → collect results in original URL order
    → evaluate consecutive_known in order → early-exit if threshold hit
  fetch page 2 (sequential)
    → repeat

Thread pool size is controlled by config.SCRAPER_LISTING_CONCURRENCY (default 8).
Keep this conservative for discovery — portals are more likely to rate-limit
a scraper that fires 20 simultaneous requests than they are a health checker.
"""

from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from scraper.models import RawListing
import config

log = logging.getLogger(__name__)

# Default concurrency for per-page listing fetches.
# Overridden by config.SCRAPER_LISTING_CONCURRENCY if set.
_DEFAULT_LISTING_CONCURRENCY = 8


class BaseParser(ABC):
    # Subclasses must define these
    source: str
    base_url: str
    search_urls: List[str]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "DNT":             "1",
    }

    def __init__(self, active_listings: Dict[Tuple[str, str], Optional[int]]):
        """
        Args:
            active_listings: Pre-fetched {(source, ext_id): price_kobo} dict.
                             Used to short-circuit pagination when we've caught up
                             to listings already in the database.
        """
        self.active_listings = active_listings
        # Main-thread session used for search-result page fetches (sequential).
        # Worker threads build their own sessions via _make_session() — a
        # requests.Session is not thread-safe and must not be shared.
        self.session      = self._make_session()
        self.robot_parser = self._load_robots_txt()

    # ── Abstract interface ─────────────────────────────────────────────────────

    @abstractmethod
    def get_listing_urls(self, page_soup: BeautifulSoup) -> List[str]:
        """Extract all listing URLs from a search results page."""
        ...

    @abstractmethod
    def parse_listing(self, soup: BeautifulSoup, url: str) -> Optional[RawListing]:
        """Parse a single listing page into a RawListing. Return None on parse failure."""
        ...

    @abstractmethod
    def next_page_url(self, base_search_url: str, page_number: int) -> Optional[str]:
        """Return the URL for page_number, or None if we've exhausted pages."""
        ...

    # ── Main scrape method ────────────────────────────────────────────────────

    def scrape(self) -> List[RawListing]:
        """
        Paginate through all search_urls and parse each listing.

        Pages are fetched sequentially (order matters for consecutive_known and
        for knowing which URLs exist on each page). Within each page, listing
        fetches are fanned out concurrently via a thread pool.
        """
        results: List[RawListing] = []
        concurrency = getattr(config, "SCRAPER_LISTING_CONCURRENCY", _DEFAULT_LISTING_CONCURRENCY)

        for base_search_url in self.search_urls:
            log.info("[%s] Starting search feed: %s", self.source, base_search_url)
            consecutive_known = 0
            page_number       = 1
            current_url       = base_search_url
            stop_feed         = False

            while current_url and not stop_feed:

                if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:
                    log.info("[%s] Page cap (%d) reached — stopping this feed",
                             self.source, config.MAX_PAGES_PER_FEED)
                    break

                log.info("[%s] Fetching page %d: %s", self.source, page_number, current_url)
                page_html = self._get(self.session, current_url)
                if not page_html:
                    log.warning("[%s] Empty response on page %d — stopping",
                                self.source, page_number)
                    break

                page_soup    = BeautifulSoup(page_html, "html.parser")
                listing_urls = self.get_listing_urls(page_soup)

                if not listing_urls:
                    log.info("[%s] No listings found on page %d — end of results",
                             self.source, page_number)
                    break

                # ── Classify URLs before fetching ─────────────────────────────
                # Split into (known, unknown) so we can:
                #   (a) skip known ones without fetching
                #   (b) only fan out HTTP work for unknown ones
                # We also need to preserve the original order for the
                # consecutive_known counter, so we build an ordered plan first.
                fetch_plan: List[Tuple[str, bool]] = []  # (url, is_known)
                for url in listing_urls:
                    ext_id   = self._extract_external_id(url)
                    is_known = bool(ext_id and (self.source, ext_id) in self.active_listings)
                    fetch_plan.append((url, is_known))

                unknown_urls = [url for url, is_known in fetch_plan if not is_known]

                # ── Fan out fetches for unknown listings ───────────────────────
                # Each worker gets its own session (thread-safety).
                # Results keyed by URL so we can reconstruct order afterward.
                fetched: Dict[str, Optional[RawListing]] = {}

                if unknown_urls:
                    log.debug("[%s] Page %d: %d unknown listings to fetch (pool=%d)",
                              self.source, page_number, len(unknown_urls), concurrency)

                    with ThreadPoolExecutor(max_workers=concurrency) as pool:
                        future_to_url: Dict[Future, str] = {
                            pool.submit(self._fetch_and_parse, url): url
                            for url in unknown_urls
                        }
                        for future in as_completed(future_to_url):
                            url    = future_to_url[future]
                            result = None
                            try:
                                result = future.result()
                            except Exception as exc:
                                log.error("[%s] Unhandled error fetching %s: %s",
                                          self.source, url, exc, exc_info=True)
                            fetched[url] = result

                # ── Collect results in original feed order ─────────────────────
                # This is where consecutive_known is evaluated — in the same
                # order the portal returns listings, so the early-exit signal
                # means what it meant in the original sequential version.
                for url, is_known in fetch_plan:
                    if is_known:
                        ext_id = self._extract_external_id(url)
                        consecutive_known += 1
                        log.debug("[%s] Known listing: %s (consecutive: %d)",
                                  self.source, ext_id, consecutive_known)
                        if consecutive_known >= config.PAGINATION_STOP_AFTER_KNOWN:
                            log.info("[%s] Hit %d consecutive known — stopping feed",
                                     self.source, consecutive_known)
                            stop_feed = True
                            break
                    else:
                        consecutive_known = 0
                        listing = fetched.get(url)
                        if listing:
                            results.append(listing)

                if not stop_feed:
                    page_number += 1
                    current_url  = self.next_page_url(base_search_url, page_number)
                    self._polite_delay()   # delay between pages, on main thread

        log.info("[%s] Scrape complete: %d listings collected", self.source, len(results))
        return results

    # ── Worker method (runs in thread pool) ───────────────────────────────────

    def _fetch_and_parse(self, url: str) -> Optional[RawListing]:
        """
        Fetch a single listing URL and parse it. Runs inside a worker thread.

        Each call builds a fresh session — requests.Session is not thread-safe
        and must never be shared across threads. The overhead of one Session
        per call is negligible; TCP connection reuse within a single listing
        fetch (redirect chains) still works fine.

        A per-request jitter delay is applied before the fetch to spread load.
        """
        if not self._robots_allowed(url):
            log.warning("[%s] robots.txt disallows: %s", self.source, url)
            return None

        # Jitter: spread concurrent requests so they don't all land at once.
        jitter = random.uniform(0, config.REQUEST_DELAY_MAX)
        time.sleep(jitter)

        session = self._make_session()
        try:
            html = self._get(session, url)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")
            try:
                return self.parse_listing(soup, url)
            except Exception as exc:
                log.error("[%s] Parse error for %s: %s", self.source, url, exc, exc_info=True)
                return None
        finally:
            session.close()

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, session: requests.Session, url: str,
             retries: int = 0) -> Optional[str]:
        """
        GET a URL with retry + exponential backoff on 429 / timeout.

        Takes an explicit session argument so both the main thread and worker
        threads can call this with their own session safely.
        """
        try:
            resp = session.get(url, timeout=20)

            if resp.status_code == 429:
                if retries < config.MAX_RETRIES:
                    wait = (config.RETRY_BACKOFF_BASE ** retries) + random.uniform(0, 1)
                    log.warning("[%s] 429 rate limit on %s — waiting %.1fs",
                                self.source, url, wait)
                    time.sleep(wait)
                    return self._get(session, url, retries + 1)
                log.error("[%s] Max retries exceeded on 429 for %s", self.source, url)
                return None

            if resp.status_code == 403:
                log.warning("[%s] 403 Forbidden on %s — bot detection?", self.source, url)
                return None

            resp.raise_for_status()
            return resp.text

        except requests.Timeout:
            if retries < config.MAX_RETRIES:
                wait = config.RETRY_BACKOFF_BASE ** retries
                log.warning("[%s] Timeout on %s — retry %d in %.1fs",
                            self.source, url, retries + 1, wait)
                time.sleep(wait)
                return self._get(session, url, retries + 1)
            log.error("[%s] Max retries on timeout for %s", self.source, url)
            return None

        except requests.RequestException as exc:
            log.error("[%s] Request error for %s: %s", self.source, url, exc)
            return None

    def _polite_delay(self) -> None:
        """Sleep a random interval between page fetches."""
        delay = random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX)
        time.sleep(delay)

    def _robots_allowed(self, url: str) -> bool:
        """Check robots.txt for this URL. Allow if parser failed to load."""
        return True

    def _make_session(self) -> requests.Session:
        """Create a new requests.Session with portal headers applied."""
        session = requests.Session()
        session.headers.update(self.HEADERS)
        return session

    def _load_robots_txt(self) -> Optional[RobotFileParser]:
        robots_url = urljoin(self.base_url, "/robots.txt")
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
            return rp
        except Exception as exc:
            log.warning("[%s] Could not load robots.txt from %s: %s",
                        self.source, robots_url, exc)
            return None

    def _extract_external_id(self, url: str) -> Optional[str]:
        """
        Default: extract numeric ID from URL path.
        e.g. "https://propertypro.ng/property/3-bedroom-flat-12345" → "12345"
        Subclasses override for non-numeric or differently-structured IDs.
        """
        m = re.search(r'(\d{5,})(?:[/?#]|$)', url)
        return m.group(1) if m else None
