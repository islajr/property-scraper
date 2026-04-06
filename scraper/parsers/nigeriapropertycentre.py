"""
parsers/nigeriapropertycentre.py — NigeriaPropertyCentre.com parser.

Wide geographic coverage including secondary cities. Server-rendered HTML.
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
LISTING_CARD_SELECTOR   = ".wp-block-title"
PRICE_CURRENCY_SELECTOR = ".property-details-price span[itemprop='priceCurrency']"
PRICE_SELECTOR          = ".property-details-price span[itemprop='price']"
BEDROOMS_SELECTOR_VAL   = ".fa-bed+span"
BEDROOMS_SELECTOR_NAME  = ".fa-bed+span"
BATHROOMS_SELECTOR_VAL  = "i.fa-bath+span[itemprop='value']"
BATHROOMS_SELECTOR_NAME = "i.fa-bath+span[itemprop='name']"
FLOOR_AREA_SELECTOR_VAL = "i.fa-square+span[itemprop='value']"
FLOOR_AREA_SELECTOR_UNIT= "i.fa-square+span[itemprop='unitText']"
ADDRESS_SELECTOR        = ".property-details>address"
TITLE_SELECTOR          = ".property-details>h4"
DESCRIPTION_SELECTOR    = "p[itemprop='description']"
PROPERTY_TYPE_SELECTOR  = "span.property-type"  # Not Found
AGENT_NAME_SELECTOR     = ".disclaimer .voffset-bottom-0>strong"
PRICE_TYPE_SELECTOR     = "span.listing-type"
EXTERNAL_ID_PATTERN    = re.compile(r'/(\d{5,})(?:-[a-z0-9-]+)?(?:\.html)?$', re.IGNORECASE)


class NigeriaPropertyCentreParser(BaseParser):
    source      = "nigeriapropertycentre"
    base_url    = "https://nigeriapropertycentre.com"
    search_urls = [
        "https://nigeriapropertycentre.com/for-sale", 
        "https://nigeriapropertycentre.com/for-rent", 
        "https://nigeriapropertycentre.com/for-rent/short-let"
    ]

    def get_listing_urls(self, page_soup: BeautifulSoup) -> List[str]:
        urls = []
        for article in page_soup.select(LISTING_CARD_SELECTOR):
            link = article.select_one("a[href]")
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

        title               = _text(soup, TITLE_SELECTOR)
        raw_price_currency  = _text(soup, PRICE_CURRENCY_SELECTOR)
        raw_price           = _text(soup, PRICE_SELECTOR)
        # raw_price_type      = _text(soup, PRICE_TYPE_SELECTOR)
        raw_bedrooms_val    = _text(soup, BEDROOMS_SELECTOR_VAL)
        raw_bedrooms_name   = next_sibling_text(soup, BEDROOMS_SELECTOR_VAL) if raw_bedrooms_val is not None else None
        raw_bathrooms_val   = _text(soup, BATHROOMS_SELECTOR_VAL)
        raw_bathrooms_name  = next_sibling_text(soup, BATHROOMS_SELECTOR_VAL) if raw_bathrooms_val is not None else None
        # raw_floor_val       = _text(soup, FLOOR_AREA_SELECTOR_VAL)
        # raw_floor_unit      = _text(soup, FLOOR_AREA_SELECTOR_UNIT)
        raw_address         = _text(soup, ADDRESS_SELECTOR)
        description         = _text(soup, DESCRIPTION_SELECTOR)
        prop_type           = _text(soup, PROPERTY_TYPE_SELECTOR)
        agent               = _text(soup, AGENT_NAME_SELECTOR)
        

         # Pre-check for possible null page through marked signs like null prices and currencies
        if raw_price == None or raw_price_currency == None:
            log.warning("[%s] Null/Unwanted Listing: %s. Skipping", self.source, url)    # null listing
            return

        # Price type — NigeriaPropertyCentre encodes in the search URL / breadcrumb
        if "for-sale" in url:
            raw_price_type = "FOR_SALE"
        elif "short-let" in url:
            raw_price_type = "FOR_SHORT_LET"
        elif "for-rent" in url:
            raw_price_type = "FOR_RENT"
        else:
            raw_price_type = None

        return RawListing(
            external_id       = ext_id,
            source            = self.source,
            url               = url,
            title             = title or "",
            raw_price         = raw_price_currency + raw_price,
            raw_price_type    = raw_price_type,
            raw_bedrooms      = raw_bedrooms_val + raw_bedrooms_name if raw_bedrooms_name is not None else None,
            raw_bathrooms     = raw_bathrooms_val + raw_bathrooms_name if raw_bathrooms_name is not None else None,
            raw_address       = raw_address,
            raw_floor_area    = None,
            description       = description,
            property_type_raw = prop_type,
            agent_name        = agent,
        )

    def next_page_url(self, base_search_url: str, page_number: int) -> Optional[str]:
        if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:   # safety ceiling
            return None
        # NPC uses ?page=N pagination
        return f"{base_search_url}?page={page_number}"

    def _extract_external_id(self, url: str) -> Optional[str]:
        m = EXTERNAL_ID_PATTERN.search(url.rstrip("/"))
        return m.group(1) if m else None


def _text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None

def next_sibling_text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """ Finds the next sibling of the provided element and returns the embedded text as a str, or None """
    el = soup.select_one(selector).find_next_sibling()
    return el.get_text(strip=True) if el else None
