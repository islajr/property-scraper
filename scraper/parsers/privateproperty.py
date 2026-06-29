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
        if not title:
            h1 = soup.select_one("h1")
            if h1:
                title = h1.get_text(strip=True)

        raw_price       = second_text(soup, PRICE_SELECTOR)
        if raw_price is None:
            price_span = None
            for el in soup.find_all(["span", "strong", "h2", "h3", "div"]):
                txt = el.get_text(strip=True)
                if txt and (txt.startswith("₦") or txt.startswith("$") or txt.startswith("USD")):
                    if any(c.isdigit() for c in txt):
                        price_span = el
                        break
            if price_span:
                raw_price = price_span.get_text(strip=True)

        # Pre-check for possible null page through marked signs like null prices
        if raw_price == None:
            log.warning("[%s] Null Listing: %s. Skipping", self.source, url)    # null listing
            return None

        raw_bedrooms    = _text(soup, BEDROOMS_SELECTOR)
        if raw_bedrooms is None:
            raw_bedrooms = self._find_feature_by_text(soup, ["bed", "bedroom"])

        raw_bathrooms   = _text(soup, BATHROOMS_SELECTOR)
        if raw_bathrooms is None:
            raw_bathrooms = self._find_feature_by_text(soup, ["bath", "bathroom"])

        raw_address     = _text(soup, ADDRESS_SELECTOR)
        if not raw_address:
            for el in soup.find_all(["p", "span", "div"]):
                txt = el.get_text(strip=True)
                if txt and len(txt) < 150:
                    if any(token in txt.lower() for token in ["lagos", "abuja", "enugu", "ph", "kano", "ibadan"]):
                        if title and txt in title:
                            continue
                        raw_address = txt
                        break

        description     = _text(soup, DESCRIPTION_SELECTOR)
        if not description:
            for el in soup.find_all("div", class_=lambda x: x and any(c in x.lower() for c in ["desc", "detail", "about"])):
                txt = el.get_text(strip=True)
                if txt and len(txt) > 100:
                    description = el.get_text("\n", strip=True)
                    break
        
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

    def _find_feature_by_text(self, soup: BeautifulSoup, keywords: List[str]) -> Optional[str]:
        for el in soup.find_all(["li", "span", "p", "div"]):
            txt = el.get_text(strip=True)
            if txt and len(txt) < 50:
                txt_lower = txt.lower()
                if any(k in txt_lower for k in keywords):
                    if any(c.isdigit() for c in txt_lower):
                        return txt
        return None

    def next_page_url(self, base_search_url: str, page_number: int) -> Optional[str]:
        if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:   # safety ceiling
            return None
        return f"{base_search_url}&page={page_number}"

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