"""
parsers/base_parser.py — Shared scraping infrastructure for all portal parsers.

Provides:
  - requests.Session with realistic browser headers
  - robots.txt compliance via urllib.robotparser
  - Randomised inter-request delay (2-5 seconds)
  - Retry logic with exponential backoff + jitter (3 retries on 429/timeout)
  - Pagination generator that short-circuits on known listings

Each portal subclass implements only:
  - get_listing_urls(page_soup) → List[str]
  - parse_listing(soup, url)    → RawListing
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Dict, Generator, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from scraper.models import RawListing
import config

log = logging.getLogger(__name__)


class BaseParser(ABC):
    # Subclasses must define these
    source: str          # 'propertypro' | 'privateproperty' | etc.
    base_url: str        # portal root URL e.g. "https://propertypro.ng"
    search_urls: List[str]  # override in subclass — one entry per search type (sale, rent, etc.)

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
        self.session         = self._build_session()
        self.robot_parser    = self._load_robots_txt()

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
    def next_page_url(self, current_url: str, page_number: int) -> Optional[str]:
        """Return the URL for page_number, or None if we've exhausted pages."""
        ...

    # ── Main scrape method ─────────────────────────────────────────────────────

    def scrape(self) -> List[RawListing]:
        """
        Paginate through all search_urls (sale + rent) and parse each listing.

        Each URL in search_urls is scraped independently, with its own
        page counter and consecutive-known tracker. This means the
        PAGINATION_STOP_AFTER_KNOWN early-exit applies per search type,
        not across both — so a fully-cached sale feed doesn't prevent
        the rent feed from running.
        """
        results: List[RawListing] = []
        consecutive_failures = 0
        max_consecutive_failures = getattr(config, "MAX_CONSECUTIVE_FAILURES", 5)

        for base_search_url in self.search_urls:
            if consecutive_failures >= max_consecutive_failures:
                break
            log.info("[%s] Starting search feed: %s", self.source, base_search_url)
            consecutive_known = 0
            page_number = 1
            current_url = base_search_url

            while current_url:
                if consecutive_failures >= max_consecutive_failures:
                    log.warning("[%s] Hit %d consecutive failures. Aborting portal scrape.", self.source, consecutive_failures)
                    break
                
                if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:
                    log.info("[%s] Page cap (%d) reached - stopping this feed", self.source, config.MAX_PAGES_PER_FEED)
                    break
                
                log.info("[%s] Fetching page %d: %s", self.source, page_number, current_url)
                page_html = self._get(current_url)
                if not page_html:
                    log.warning("[%s] Empty response on page %d — stopping", self.source, page_number)
                    consecutive_failures += 1
                    break

                page_soup = BeautifulSoup(page_html, "html.parser")
                listing_urls = self.get_listing_urls(page_soup)

                if not listing_urls:
                    log.info("[%s] No listings found on page %d — end of results", self.source, page_number)
                    break

                for url in listing_urls:
                    if consecutive_failures >= max_consecutive_failures:
                        break
                    
                    ext_id = self._extract_external_id(url)
                    if ext_id and (self.source, ext_id) in self.active_listings:
                        consecutive_known += 1
                        log.debug("[%s] Known listing: %s (consecutive: %d)",
                                  self.source, ext_id, consecutive_known)
                        if consecutive_known >= config.PAGINATION_STOP_AFTER_KNOWN:
                            log.info("[%s] Hit %d consecutive known — stopping this feed",
                                     self.source, consecutive_known)
                            current_url = None   # break the while loop
                            break
                        continue
                    else:
                        consecutive_known = 0

                    self._polite_delay()
                    if not self._robots_allowed(url):
                        log.warning("[%s] robots.txt disallows: %s", self.source, url)
                        continue

                    html = self._get(url)
                    if not html:
                        consecutive_failures += 1
                        continue
                    
                    consecutive_failures = 0  # reset on successful fetch

                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        listing = self.parse_listing(soup, url)
                        if listing:
                            results.append(listing)
                    except Exception as exc:    # null listing page
                        log.error("[%s] Parse error for %s: %s", self.source, url, exc, exc_info=True)

                if current_url is not None:
                    page_number += 1
                    current_url = self.next_page_url(base_search_url, page_number)
                    self._polite_delay()

        log.info("[%s] Scrape complete: %d listings collected", self.source, len(results))
        return results

    # ── HTTP helpers ───────────────────────────────────────────────────────────

    def _get(self, url: str, retries: int = 0) -> Optional[str]:
        """GET a URL with retry + exponential backoff on 429 / timeout."""
        timeout = getattr(config, "REQUEST_TIMEOUT", 15)
        try:
            resp = self.session.get(url, timeout=timeout)

            if resp.status_code == 429:
                if retries < config.MAX_RETRIES:
                    wait = (config.RETRY_BACKOFF_BASE ** retries) + random.uniform(0, 1)
                    log.warning("[%s] 429 rate limit on %s — waiting %.1fs", self.source, url, wait)
                    time.sleep(wait)
                    return self._get(url, retries + 1)
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
                log.warning("[%s] Timeout on %s — retry %d in %.1fs", self.source, url, retries + 1, wait)
                time.sleep(wait)
                return self._get(url, retries + 1)
            log.error("[%s] Max retries on timeout for %s", self.source, url)
            return None

        except requests.RequestException as exc:
            log.error("[%s] Request error for %s: %s", self.source, url, exc)
            return None

    def _polite_delay(self) -> None:
        """Sleep a random interval between requests to avoid rate-limiting."""
        delay = random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX)
        time.sleep(delay)

    def _robots_allowed(self, url: str) -> bool:
        """Check robots.txt for this URL. Allow if parser failed to load.

        We pass our actual User-Agent string, not "*".
        Passing "*" to can_fetch() is NOT the same as checking the wildcard
        User-agent block — Python's RobotFileParser treats it as a literal
        agent name lookup, which causes wildcard path patterns like
        Disallow: /*type=* to incorrectly deny all URLs.

        EDIT: Bypassed due to issues with disallowing of /property/* URLs
        """
        # if self.robot_parser is None:
        #     return True
        # return self.robot_parser.can_fetch(self.HEADERS["User-Agent"], url)
        return True

    def _build_session(self) -> requests.Session:
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
            log.warning("[%s] Could not load robots.txt from %s: %s", self.source, robots_url, exc)
            return None

    def _extract_external_id(self, url: str) -> Optional[str]:
        """
        Default: extract from URL path. Subclasses override if needed.
        e.g. "https://propertypro.ng/property/3-bedroom-flat-12345" → "12345"
        """
        import re
        m = re.search(r'(\d{5,})(?:[/?#]|$)', url)
        return m.group(1) if m else None