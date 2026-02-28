"""
parsers/privateproperty.py — PrivateProperty.com.ng parser.

Strong Abuja coverage. Server-rendered HTML. Good neighbourhood tagging.
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
LISTING_CARD_SELECTOR  = "div.p24_regularTile"
PRICE_SELECTOR         = "span.p24_price"
BEDROOMS_SELECTOR      = "span.p24_featureDetails[title='Bedrooms']"
BATHROOMS_SELECTOR     = "span.p24_featureDetails[title='Bathrooms']"
FLOOR_AREA_SELECTOR    = "span.p24_featureDetails[title='Floor Size']"
ADDRESS_SELECTOR       = "span.p24_address"
TITLE_SELECTOR         = "span.p24_title"
DESCRIPTION_SELECTOR   = "div.p24_description"
PROPERTY_TYPE_SELECTOR = "span.p24_propertyType"
AGENT_NAME_SELECTOR    = "div.p24_agentName span"
PRICE_TYPE_SELECTOR    = "span.p24_listingTypeText"
EXTERNAL_ID_PATTERN    = re.compile(r'(\d{5,})(?:[/?#]|$)')


class PrivatePropertyParser(BaseParser):
    source     = "privateproperty"
    base_url   = "https://www.privateproperty.com.ng"
    search_url = "https://www.privateproperty.com.ng/for-sale"

    def get_listing_urls(self, page_soup: BeautifulSoup) -> List[str]:
        urls = []
        for card in page_soup.select(LISTING_CARD_SELECTOR):
            link = card.find("a", href=True)
            if link:
                href = link["href"]
                if not href.startswith("http"):
                    href = self.base_url + href
                urls.append(href)
        return urls

    def parse_listing(self, soup: BeautifulSoup, url: str) -> Optional[RawListing]:
        ext_id = self._extract_external_id(url)
        if not ext_id:
            log.warning("[privateproperty] Could not extract external_id from: %s", url)
            return None

        title         = _text(soup, TITLE_SELECTOR)
        raw_price     = _text(soup, PRICE_SELECTOR)
        raw_price_type= _text(soup, PRICE_TYPE_SELECTOR)
        raw_bedrooms  = _text(soup, BEDROOMS_SELECTOR)
        raw_bathrooms = _text(soup, BATHROOMS_SELECTOR)
        raw_floor     = _text(soup, FLOOR_AREA_SELECTOR)
        raw_address   = _text(soup, ADDRESS_SELECTOR)
        description   = _text(soup, DESCRIPTION_SELECTOR)
        prop_type     = _text(soup, PROPERTY_TYPE_SELECTOR)
        agent         = _text(soup, AGENT_NAME_SELECTOR)

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
        return f"{self.search_url}?page={page_number}"

    def _extract_external_id(self, url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url)
        return m.group(1) if m else None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None