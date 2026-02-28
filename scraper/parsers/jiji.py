"""
parsers/jiji.py — Jiji.ng property section parser.

Jiji renders listing content via JavaScript — requests + BeautifulSoup alone
will return an empty shell. playwright (sync API) is required.

Architecture note:
  The browser context is opened ONCE per run and reused across all pages.
  Opening and closing per-listing would be too slow (3–5s cold start each time).
  Browser is launched headless; chromium only (installed in GitHub Actions step).

MAINTENANCE: Jiji has a higher HTML-change frequency than the other portals.
If new_listings drops to zero, check LISTING_CARD_SELECTOR first.
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

# ── Selector constants — update these when portal HTML changes ─────────────────
LISTING_CARD_SELECTOR   = "div.b-list-advert-base"
LISTING_LINK_ATTR       = "a.b-list-advert-base__item-title"
PRICE_SELECTOR          = "span.qa-advert-price"
BEDROOMS_SELECTOR       = "span[itemprop='numberOfRooms']"
BATHROOMS_SELECTOR      = None   # Jiji rarely shows bathrooms on listing page
FLOOR_AREA_SELECTOR     = "span.b-advert-attribute__name:-soup-contains('Area') + span"
ADDRESS_SELECTOR        = "span.b-advert-address__text"
TITLE_SELECTOR          = "h1.qa-advert-title"
DESCRIPTION_SELECTOR    = "div.b-advert-description-text"
PROPERTY_TYPE_SELECTOR  = "span.b-advert-attribute__name:-soup-contains('Type') + span"
AGENT_NAME_SELECTOR     = "span.qa-seller-name"
EXTERNAL_ID_PATTERN     = re.compile(r'_(\d+)\.html?$')
SEARCH_URL              = "https://jiji.ng/real-estate/houses-apartments-for-sale"
BASE_URL                = "https://jiji.ng"


class JijiParser:
    """
    Standalone class (does not extend BaseParser) because playwright's
    page management is fundamentally different from requests.Session.
    The retry/delay logic is reimplemented inline.
    """
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
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/121.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
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
                page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                page.wait_for_selector(LISTING_CARD_SELECTOR, timeout=15_000)
            except Exception as exc:
                log.error("[jiji] Playwright error on page %d: %s", page_number, exc)
                break

            content = page.content()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")

            cards = soup.select(LISTING_CARD_SELECTOR)
            if not cards:
                log.info("[jiji] No listing cards on page %d — end of results", page_number)
                break

            listing_urls = []
            for card in cards:
                link = card.select_one("a[href]")
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
                    page.goto(listing_url, timeout=30_000, wait_until="domcontentloaded")
                    listing_content = page.content()
                    listing_soup = BeautifulSoup(listing_content, "html.parser")
                    raw = self._parse_listing(listing_soup, listing_url)
                    if raw:
                        results.append(raw)
                except Exception as exc:
                    log.error("[jiji] Error parsing %s: %s", listing_url, exc)

            page_number += 1
            if page_number > 50:
                log.info("[jiji] Safety cap reached at page 50")
                break

            time.sleep(random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX))

        log.info("[jiji] Scrape complete: %d listings", len(results))
        return results

    def _parse_listing(self, soup, url: str) -> Optional[RawListing]:
        ext_id = self._extract_external_id(url)
        if not ext_id:
            return None

        title        = _text(soup, TITLE_SELECTOR)
        raw_price    = _text(soup, PRICE_SELECTOR)
        raw_bedrooms = _text(soup, BEDROOMS_SELECTOR)
        raw_floor    = _text(soup, FLOOR_AREA_SELECTOR)
        raw_address  = _text(soup, ADDRESS_SELECTOR)
        description  = _text(soup, DESCRIPTION_SELECTOR)
        prop_type    = _text(soup, PROPERTY_TYPE_SELECTOR)
        agent        = _text(soup, AGENT_NAME_SELECTOR)

        # Jiji shows price type in description / breadcrumb
        raw_price_type = None
        if raw_price and "/month" in (raw_price or "").lower():
            raw_price_type = "FOR_RENT"
        elif raw_price and "/year" in (raw_price or "").lower():
            raw_price_type = "FOR_RENT"

        return RawListing(
            external_id       = ext_id,
            source            = self.source,
            url               = url,
            title             = title or "",
            raw_price         = raw_price,
            raw_price_type    = raw_price_type,
            raw_bedrooms      = raw_bedrooms,
            raw_bathrooms     = None,
            raw_address       = raw_address,
            raw_floor_area    = raw_floor,
            description       = description,
            property_type_raw = prop_type,
            agent_name        = agent,
        )

    @staticmethod
    def _page_url(page_number: int) -> str:
        if page_number == 1:
            return SEARCH_URL
        return f"{SEARCH_URL}?page={page_number}"

    @staticmethod
    def _extract_external_id(url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url)
        if m:
            return m.group(1)
        # Fallback: last numeric segment
        m2 = re.search(r'(\d{5,})', url)
        return m2.group(1) if m2 else None


def _text(soup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None