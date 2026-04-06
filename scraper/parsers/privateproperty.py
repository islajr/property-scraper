"""
parsers/privateproperty.py — PrivateProperty.ng parser.

Strong Abuja coverage. Server-rendered HTML. Good neighbourhood tagging.
Selectors are named constants at module level for one-line maintenance.
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

# ── Selector constants ─────────────────────────────────────────────────────────
LISTING_CARD_SELECTOR   = ".similar-listings-info"
PRICE_CURRENCY_SELECTOR = ".property-info .price>strong"
PRICE_SELECTOR          = ".property-info .price>strong"
BEDROOMS_SELECTOR       = ".property-info .property-benefit>li"
BATHROOMS_SELECTOR      = ".property-info .property-benefit>li"
FLOOR_AREA_SELECTOR     = None  # should look into extracting for present variants
ADDRESS_SELECTOR        = ".property-info>p"
TITLE_SELECTOR          = ".property-info>h1"
DESCRIPTION_SELECTOR    = ".description-property>.row .description-list"
# PROPERTY_TYPE_SELECTOR  = f"{LISTING_CARD_SELECTOR} div.pl-title h6>a:nth-of-type(2)"
AGENT_NAME_SELECTOR     = ".sidebar-main .marketed-by a.media>img"
# PRICE_TYPE_SELECTOR     = "span.p24_listingTypeText" # Not Found
EXTERNAL_ID_PATTERN     = re.compile(r'/listings/[^?#]+-([A-Za-z0-9]{4,10})(?:[?#/]|$)', re.IGNORECASE)


class PrivatePropertyParser(BaseParser):
    source     = "privateproperty"
    base_url   = "https://privateproperty.ng"
    search_urls = [
        "https://privateproperty.ng/property-for-sale?sort=postedOn&order=desc", 
        "https://privateproperty.ng/property-for-rent?sort=postedOn&order=desc", 
        "https://privateproperty.ng/short-let?sort=postedOn&order=desc"
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
            log.warning("[privateproperty] Could not extract external_id from: %s", url)
            return None

        title           = _text(soup, TITLE_SELECTOR)
        price_currency  = _text(soup, TITLE_SELECTOR)
        raw_price       = second_text(soup, PRICE_SELECTOR)
        # raw_price_type= _text(soup, PRICE_TYPE_SELECTOR)
        raw_bedrooms    = _text(soup, BEDROOMS_SELECTOR)
        raw_bathrooms   = _text(soup, BATHROOMS_SELECTOR)
        # raw_floor     = _text(soup, FLOOR_AREA_SELECTOR)
        raw_address     = _text(soup, ADDRESS_SELECTOR)
        description     = _text(soup, DESCRIPTION_SELECTOR)
        # prop_type     = _text(soup, PROPERTY_TYPE_SELECTOR)
        # agent           = element_text(soup, AGENT_NAME_SELECTOR, 'alt')
        
        # Price type — PrivateProperty encodes in the search URL / breadcrumb
        if "for-sale" in url:
            raw_price_type = "FOR_SALE"
        elif "for-rent" in url:
            raw_price_type = "FOR_RENT"
        elif "short-let" in url:
            raw_price_type = "FOR_SHORT_LET"
        else:
            raw_price_type = None

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
            raw_floor_area    = None,
            description       = description,
            property_type_raw = None,
            agent_name        = None,
        )

    def next_page_url(self, base_search_url: str, page_number: int) -> Optional[str]:
        if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:   # safety ceiling
            return None
        return f"{base_search_url}?page={page_number}"

    def _extract_external_id(self, url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url)
        return m.group(1) if m else None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None

def second_text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """Select second matching element and return stripped text, or None"""
    el = soup.select_one(selector + ":nth-of-type(2)")
    return el.get_text(strip=True) if el else None

def element_text(soup: BeautifulSoup, selector: str, element: str) -> Optional[str]:
    """Select text within an element of a given tag and return either the stripped text or None"""
    el = soup.find(selector)[element]
    return el if el else None