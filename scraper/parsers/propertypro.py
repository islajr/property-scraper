"""
parsers/propertypro.py — PropertyPro.ng parser.

PropertyPro is the market leader for Lagos/Abuja listings.
Pages are server-rendered HTML — no JavaScript execution required.
Selectors are named constants at module level for one-line maintenance.

MAINTENANCE: If a Telegram alert shows propertypro new_listings=0, check selector
drift first. Open a live listing in browser DevTools and compare against the
constants below. A single-line selector change is typically all that's needed.
"""

from __future__ import annotations

import re
import logging
import config
from typing import List, Optional

from bs4 import BeautifulSoup

from scraper.models import RawListing
from scraper.parsers.base_parser import BaseParser

log = logging.getLogger(__name__)

# ── Selector constants — update these when portal HTML changes ─────────────────
LISTING_CARD_SELECTOR   = ".pl-title"
# LISTING_LINK_SELECTOR   = "a.single-room-info--image"
PRICE_CURRENCY_SELECTOR = ".property-pricing>.pricing>h2>strong"
PRICE_SELECTOR          = ".property-pricing>.pricing>h2>strong"
BEDROOMS_SELECTOR       = ".property-contact-block>.property-pros ul li"
BATHROOMS_SELECTOR      = ".property-contact-block>.property-pros ul li"
FLOOR_AREA_SELECTOR     = "span[data-tooltip='Size'] strong"    # None
ADDRESS_SELECTOR        = ".content-block>p"
TITLE_SELECTOR          = "h1.page-heading"
DESCRIPTION_SELECTOR    = ".content-block>.line-paragraph"
# PROPERTY_TYPE_SELECTOR  = TITLE_SELECTOR    # gotten from title
AGENT_NAME_SELECTOR     = "#sidebar .flex-grow-1>a>h4"
EXTERNAL_ID_PATTERN     = re.compile(r'/property/[^?#]+-([A-Za-z0-9]{4,10})(?:[?#/]|$)', re.IGNORECASE)
NEXT_PAGE_SELECTOR      = "a.next.page-numbers"


class PropertyProParser(BaseParser):
    source      = "propertypro"
    base_url    = "https://propertypro.ng"
    search_urls  = [
        "https://propertypro.ng/property-for-sale?sort=postedOn&order=desc",
        "https://propertypro.ng/property-for-rent?sort=postedOn&order=desc", 
        "https://propertypro.ng/property-for-short-let?sort=postedOn&order=desc"
    ]

    def get_listing_urls(self, page_soup: BeautifulSoup) -> List[str]:
        urls = []
        for card in page_soup.select(LISTING_CARD_SELECTOR):
            link = card.select_one("a[href]")
            if link:
                href = link["href"]
                if not href.startswith("http"):
                    href = self.base_url + href
                urls.append(href)
        return urls

    def parse_listing(self, soup: BeautifulSoup, url: str) -> Optional[RawListing]:
        ext_id = self._extract_external_id(url)
        if not ext_id:
            log.warning("[propertypro] Could not extract external_id from: %s", url)
            return None

        title           = _text(soup, TITLE_SELECTOR)
        price_currency  = second_text(soup, PRICE_CURRENCY_SELECTOR)
        raw_price       = _text(soup, PRICE_SELECTOR)
        raw_bedrooms    = _text(soup, BEDROOMS_SELECTOR)
        raw_bathrooms   = _text(soup, BATHROOMS_SELECTOR)
        raw_floor       = _text(soup, FLOOR_AREA_SELECTOR)
        raw_address     = _text(soup, ADDRESS_SELECTOR)
        description     = _text(soup, DESCRIPTION_SELECTOR)
        # prop_type       = _text(soup, PROPERTY_TYPE_SELECTOR)
        agent           = _text(soup, AGENT_NAME_SELECTOR)
        
        # Pre-check for possible null page through marked signs like null prices and currencies
        if raw_price == None or price_currency == None:
            log.warning("[%s] Null Listing: %s. Skipping", self.source, url)    # null listing
            return

        # Price type — PropertyPro encodes in the search URL / breadcrumb
        if "for-sale" in url:
            raw_price_type = "FOR_SALE"
        elif "for-rent" in url:
            raw_price_type = "FOR_RENT"
        elif "for-short-let" in url:
            raw_price_type = "FOR_SHORT_LET"
        else:
            raw_price_type = None

        return RawListing(
            external_id       = ext_id,
            source            = self.source,
            url               = url,
            title             = title,
            raw_price         = price_currency + raw_price,
            raw_price_type    = raw_price_type,
            raw_bedrooms      = raw_bedrooms,
            raw_bathrooms     = raw_bathrooms,
            raw_address       = raw_address,
            raw_floor_area    = raw_floor,
            description       = description,
            property_type_raw = None,
            agent_name        = agent,
        )

    def next_page_url(self, base_search_url: str, page_number: int) -> Optional[str]:
        # PropertyPro uses ?page=N pagination
        if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:   # testing safety cap
            return None
        return f"{base_search_url}?page={page_number}"

    def _extract_external_id(self, url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url)
        return m.group(1) if m else None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """Select first matching element and return stripped text, or None."""
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None

def second_text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """Select second matching element and return stripped text, or None"""
    el = soup.select_one(selector + ":nth-of-type(2)")
    return el.get_text(strip=True) if el else None