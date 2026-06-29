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
        if not title:
            h1 = soup.select_one("h1")
            if h1:
                title = h1.get_text(strip=True)

        price_currency  = second_text(soup, PRICE_CURRENCY_SELECTOR)
        raw_price       = _text(soup, PRICE_SELECTOR)
        if raw_price is None or price_currency is None:
            price_span = None
            for el in soup.find_all(["span", "h2", "h3", "div"]):
                txt = el.get_text(strip=True)
                if txt and (txt.startswith("₦") or txt.startswith("$") or txt.startswith("USD")):
                    if any(c.isdigit() for c in txt):
                        price_span = el
                        break
            if price_span:
                combined_price = price_span.get_text(strip=True)
                if combined_price.startswith("₦"):
                    price_currency = "₦"
                    raw_price = combined_price[1:]
                elif combined_price.startswith("$"):
                    price_currency = "$"
                    raw_price = combined_price[1:]
                elif combined_price.startswith("USD"):
                    price_currency = "USD"
                    raw_price = combined_price[3:]
                else:
                    price_currency = ""
                    raw_price = combined_price

        # Pre-check for possible null page through marked signs like null prices and currencies
        if raw_price == None or price_currency == None:
            log.warning("[%s] Null Listing: %s. Skipping", self.source, url)    # null listing
            return None

        raw_bedrooms    = _text(soup, BEDROOMS_SELECTOR)
        if raw_bedrooms is None:
            raw_bedrooms = self._find_feature_by_text(soup, ["bed", "bedroom"])

        raw_bathrooms   = _text(soup, BATHROOMS_SELECTOR)
        if raw_bathrooms is None:
            raw_bathrooms = self._find_feature_by_text(soup, ["bath", "bathroom"])

        raw_floor       = _text(soup, FLOOR_AREA_SELECTOR)
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

        agent           = _text(soup, AGENT_NAME_SELECTOR)
        if not agent:
            for el in soup.find_all(["h4", "h5", "span", "a"]):
                txt = el.get_text(strip=True)
                if txt and len(txt) < 60:
                    parent = el.parent
                    is_agent_section = False
                    for _ in range(3):
                        if parent:
                            if parent.name in ["div", "aside", "section"]:
                                p_class = " ".join(parent.get("class", [])) + str(parent.get("id", ""))
                                if any(c in p_class.lower() for c in ["sidebar", "agent", "market", "owner", "contact"]):
                                    is_agent_section = True
                                    break
                            parent = parent.parent
                        else:
                            break
                    if is_agent_section:
                        if not any(lbl in txt.lower() for lbl in ["contact", "agent", "whatsapp", "call", "phone"]):
                            agent = txt
                            break

        # Price type — PropertyPro encodes in the search URL / breadcrumb
        if "for-sale" in url:
            raw_price_type = "FOR_SALE"
        elif "for-rent" in url:
            raw_price_type = "FOR_RENT"
        elif "for-shortlet" in url:
            raw_price_type = "FOR_SHORT_LET"
        else:
            raw_price_type = None

        return RawListing(
            external_id       = ext_id,
            source            = self.source,
            url               = url,
            title             = title or "",
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
        # PropertyPro uses ?page=N pagination
        if config.MAX_PAGES_PER_FEED and page_number > config.MAX_PAGES_PER_FEED:   # safety ceiling
            return None
        return f"{base_search_url}&page={page_number}"

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