"""
parsers/nigeriapropertycentre.py — NigeriaPropertyCentre.com parser.

Wide geographic coverage including secondary cities. Server-rendered HTML.
Selectors are named constants at module level for one-line maintenance.
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional

from bs4 import BeautifulSoup

from scraper.models import RawListing
from scraper.parsers.base_parser import BaseParser

log = logging.getLogger(__name__)

# ── Selector constants ─────────────────────────────────────────────────────────
LISTING_CARD_SELECTOR   = "article.property-listing"
PRICE_SELECTOR          = "strong.price"
BEDROOMS_SELECTOR       = "li.bedrooms"
BATHROOMS_SELECTOR      = "li.bathrooms"
FLOOR_AREA_SELECTOR     = "li.size"
ADDRESS_SELECTOR        = "address.property-address"
TITLE_SELECTOR          = "h2.listing-name a"
DESCRIPTION_SELECTOR    = "div.property-description"
PROPERTY_TYPE_SELECTOR  = "span.property-type"
AGENT_NAME_SELECTOR     = "span.agent-name"
PRICE_TYPE_SELECTOR     = "span.listing-type"
EXTERNAL_ID_PATTERN     = re.compile(r'-(\d{5,})(?:\.html)?(?:[/?#]|$)')


class NigeriaPropertyCentreParser(BaseParser):
    source     = "nigeriapropertycentre"
    base_url   = "https://nigeriapropertycentre.com"
    search_url = "https://nigeriapropertycentre.com/for-sale"

    def get_listing_urls(self, page_soup: BeautifulSoup) -> List[str]:
        urls = []
        for article in page_soup.select(LISTING_CARD_SELECTOR):
            link = article.find("a", href=True)
            if link:
                href = link["href"]
                if not href.startswith("http"):
                    href = self.base_url + href
                urls.append(href)
        return urls

    def parse_listing(self, soup: BeautifulSoup, url: str) -> Optional[RawListing]:
        ext_id = self._extract_external_id(url)
        if not ext_id:
            log.warning("[nigeriapropertycentre] Could not extract external_id from: %s", url)
            return None

        title          = _text(soup, TITLE_SELECTOR)
        raw_price      = _text(soup, PRICE_SELECTOR)
        raw_price_type = _text(soup, PRICE_TYPE_SELECTOR)
        raw_bedrooms   = _text(soup, BEDROOMS_SELECTOR)
        raw_bathrooms  = _text(soup, BATHROOMS_SELECTOR)
        raw_floor      = _text(soup, FLOOR_AREA_SELECTOR)
        raw_address    = _text(soup, ADDRESS_SELECTOR)
        description    = _text(soup, DESCRIPTION_SELECTOR)
        prop_type      = _text(soup, PROPERTY_TYPE_SELECTOR)
        agent          = _text(soup, AGENT_NAME_SELECTOR)

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
        if page_number > 50:
            return None
        # NPC uses /page-N/ suffix pattern
        return f"{self.search_url}/page-{page_number}"

    def _extract_external_id(self, url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url)
        return m.group(1) if m else None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None