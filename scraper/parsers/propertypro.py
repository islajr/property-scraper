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
from typing import List, Optional

from bs4 import BeautifulSoup

from scraper.models import RawListing
from scraper.parsers.base_parser import BaseParser

log = logging.getLogger(__name__)

# ── Selector constants — update these when portal HTML changes ─────────────────
LISTING_CARD_SELECTOR   = "div.single-room-info.listing"
LISTING_LINK_SELECTOR   = "a.single-room-info--image"          # href on the card
PRICE_SELECTOR          = "h3.price-name"
BEDROOMS_SELECTOR       = "span[data-tooltip='Bedrooms'] strong"
BATHROOMS_SELECTOR      = "span[data-tooltip='Bathrooms'] strong"
FLOOR_AREA_SELECTOR     = "span[data-tooltip='Size'] strong"
ADDRESS_SELECTOR        = "h4.listings-property--address"
TITLE_SELECTOR          = "h3.listings-property--title a"
DESCRIPTION_SELECTOR    = "div.listings-property-text--description"
PROPERTY_TYPE_SELECTOR  = "div.fur-areea span.fur-areea-bed:first-child"
AGENT_NAME_SELECTOR     = "div.agent-name"
EXTERNAL_ID_PATTERN     = re.compile(r'/property/[a-z0-9-]+-(\d+)', re.IGNORECASE)
NEXT_PAGE_SELECTOR      = "a.next.page-numbers"


class PropertyProParser(BaseParser):
    source      = "propertypro"
    base_url    = "https://www.propertypro.ng"
    search_url  = "https://www.propertypro.ng/property-for-sale?per_page=24"

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

        title        = _text(soup, TITLE_SELECTOR)
        raw_price    = _text(soup, PRICE_SELECTOR)
        raw_bedrooms = _text(soup, BEDROOMS_SELECTOR)
        raw_bathrooms= _text(soup, BATHROOMS_SELECTOR)
        raw_floor    = _text(soup, FLOOR_AREA_SELECTOR)
        raw_address  = _text(soup, ADDRESS_SELECTOR)
        description  = _text(soup, DESCRIPTION_SELECTOR)
        prop_type    = _text(soup, PROPERTY_TYPE_SELECTOR)
        agent        = _text(soup, AGENT_NAME_SELECTOR)

        # Price type — PropertyPro encodes in the search URL / breadcrumb
        raw_price_type = "FOR_SALE"  # default; override if rental signals present
        if raw_price and "per year" in raw_price.lower():
            raw_price_type = "FOR_RENT"

        return RawListing(
            external_id       = ext_id,
            source            = self.source,
            url               = url,
            title             = title or "",
            raw_price         = raw_price,
            raw_price_type    = raw_price_type,
            raw_bedrooms      = raw_bedrooms,
            raw_bathrooms     = raw_bathrooms,
            raw_address       = raw_address,
            raw_floor_area    = raw_floor,
            description       = description,
            property_type_raw = prop_type,
            agent_name        = agent,
        )

    def next_page_url(self, base_search_url: str, page_number: int) -> Optional[str]:
        # PropertyPro uses ?page=N pagination
        if page_number > 50:   # safety cap
            return None
        return f"{self.search_url}&page={page_number}"

    def _extract_external_id(self, url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url)
        return m.group(1) if m else None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """Select first matching element and return stripped text, or None."""
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None