"""
parsers/jiji.py — Jiji.ng property section parser.

Selectors verified against live HTML fixture, February 2026.
Uses Playwright (sync API) — Jiji renders content via JavaScript.

Key changes from initial scaffold:
  - External IDs are now alphanumeric (e.g. "saFgVBX3QXLb3rsljTXA53Ls")
  - wait_until="networkidle" instead of domcontentloaded (more reliable)
  - Listing attributes (type, bedrooms, bathrooms) parsed from b-advert-icon-attribute divs
  - Price from qa-advert-price-view-title
  - Address from b-advert-info-statistics--region
"""

from __future__ import annotations

import re
import time
import random
import logging
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, Page, Browser

from scraper.models import RawListing
import config

log = logging.getLogger(__name__)

# ── Selector constants ─────────────────────────────────────────────────────────
LISTING_CARD_SELECTOR   = "div.b-advert-card"              # search results card
PRICE_SELECTOR          = "div.qa-advert-price-view-title" # "₦ 145,000,000"
ADDRESS_SELECTOR        = "div.b-advert-info-statistics--region"   # "Abuja, Lugbe District"
ATTRIBUTE_SELECTOR      = "div.b-advert-icon-attribute"    # repeated: Type / Beds / Baths
DESCRIPTION_SELECTOR    = "div.qa-advert-description"  # qa- prefix = stable test hook
AGENT_NAME_SELECTOR     = "div.b-seller-block__name"
TITLE_SELECTOR          = "h1"

# https://jiji.ng/lugbe/houses-apartments-for-sale/4bdrm-duplex-...-saFgVBX3QXLb3rsljTXA53Ls.html
EXTERNAL_ID_PATTERN     = re.compile(r'-([A-Za-z0-9]{10,})\.html?$')

SEARCH_URL = "https://jiji.ng/real-estate/houses-apartments-for-sale"
BASE_URL   = "https://jiji.ng"

# Playwright settings
PAGE_TIMEOUT     = 30_000   # ms — page navigation timeout
SELECTOR_TIMEOUT = 20_000   # ms — wait_for_selector timeout (increased from 15s)


class JijiParser:
    source = "jiji"

    def __init__(self, active_listings: Dict[Tuple[str, str], Optional[int]]):
        self.active_listings = active_listings

    def scrape(self) -> List[RawListing]:
        results: List[RawListing] = []
        with sync_playwright() as p:
            browser: Browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                results = self._scrape_with_page(page)
            finally:
                browser.close()
        return results

    def _scrape_with_page(self, page: Page) -> List[RawListing]:
        results: List[RawListing] = []
        consecutive_known = 0
        page_number = 1

        while True:
            url = self._page_url(page_number)
            log.info("[jiji] Fetching page %d: %s", page_number, url)

            try:
                # networkidle waits for JS to fully settle — more reliable than domcontentloaded
                page.goto(url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
                page.wait_for_selector(LISTING_CARD_SELECTOR, timeout=SELECTOR_TIMEOUT)
            except Exception as exc:
                log.error("[jiji] Playwright error on page %d: %s", page_number, exc)
                break

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(page.content(), "html.parser")
            cards = soup.select(LISTING_CARD_SELECTOR)

            if not cards:
                log.info("[jiji] No listing cards on page %d — end of results", page_number)
                break

            listing_urls = []
            for card in cards:
                link = card.find("a", href=True)
                if link:
                    href = link["href"]
                    if not href.startswith("http"):
                        href = BASE_URL + href
                    listing_urls.append(href)

            for listing_url in listing_urls:
                ext_id = self._extract_external_id(listing_url)
                if ext_id and (self.source, ext_id) in self.active_listings:
                    consecutive_known += 1
                    if consecutive_known >= config.PAGINATION_STOP_AFTER_KNOWN:
                        log.info("[jiji] %d consecutive known — stopping", consecutive_known)
                        return results
                    continue
                else:
                    consecutive_known = 0

                time.sleep(random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX))

                try:
                    page.goto(listing_url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
                    listing_soup = BeautifulSoup(page.content(), "html.parser")
                    raw = self._parse_listing(listing_soup, listing_url)
                    if raw:
                        results.append(raw)
                except Exception as exc:
                    log.error("[jiji] Error parsing %s: %s", listing_url, exc)

            page_number += 1
            if page_number > 50:
                log.info("[jiji] Safety cap at page 50")
                break

            time.sleep(random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX))

        log.info("[jiji] Scrape complete: %d listings", len(results))
        return results

    def _parse_listing(self, soup, url: str) -> Optional[RawListing]:
        # Use canonical URL for clean ID extraction
        canonical = soup.find("link", rel="canonical")
        id_url    = canonical["href"] if canonical else url
        ext_id    = self._extract_external_id(id_url)
        if not ext_id:
            return None

        title     = _text(soup, TITLE_SELECTOR)
        raw_price = _text(soup, PRICE_SELECTOR)
        raw_address = _text(soup, ADDRESS_SELECTOR)
        description = _text(soup, DESCRIPTION_SELECTOR)
        agent       = _text(soup, AGENT_NAME_SELECTOR)

        # Parse attributes — ordered: property type, bedrooms, bathrooms
        attrs = [el.get_text(strip=True) for el in soup.select(ATTRIBUTE_SELECTOR)]
        prop_type  = attrs[0] if len(attrs) > 0 else None
        raw_beds   = attrs[1] if len(attrs) > 1 else None  # "4 bedrooms"
        raw_baths  = attrs[2] if len(attrs) > 2 else None  # "5 bathrooms"

        # Price type from URL or price string
        raw_price_type = None
        if raw_price and any(k in raw_price.lower() for k in ["/month", "/year", "per month"]):
            raw_price_type = "FOR_RENT"
        elif "houses-apartments-for-sale" in id_url:
            raw_price_type = "FOR_SALE"
        elif "houses-apartments-for-rent" in id_url:
            raw_price_type = "FOR_RENT"

        return RawListing(
            external_id       = ext_id,
            source            = self.source,
            url               = id_url,
            title             = title or "",
            raw_price         = raw_price,
            raw_price_type    = raw_price_type,
            raw_bedrooms      = raw_beds,
            raw_bathrooms     = raw_baths,
            raw_address       = raw_address,
            raw_floor_area    = None,
            description       = description,
            property_type_raw = prop_type,
            agent_name        = agent,
        )

    @staticmethod
    def _page_url(page_number: int) -> str:
        return SEARCH_URL if page_number == 1 else f"{SEARCH_URL}?page={page_number}"

    @staticmethod
    def _extract_external_id(url: str) -> Optional[str]:
        # Primary: long alphanumeric ID at end of URL before .html
        m = EXTERNAL_ID_PATTERN.search(url)
        if m:
            return m.group(1)
        # Fallback: any long alphanumeric segment
        m2 = re.search(r'([A-Za-z0-9]{15,})', url)
        return m2.group(1) if m2 else None


def _text(soup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None