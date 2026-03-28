"""
models.py — Data transfer objects for PS-0 PropertyScraper.

RawListing:       strings exactly as extracted from portal HTML — no typing, no cleaning.
NormalisedListing: fully typed, cleaned fields ready for database insertion.

The two-stage model makes normalisation independently testable against HTML fixtures
without requiring a database connection.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class RawListing:
    """
    Unprocessed listing data extracted directly from portal HTML.
    All fields are raw strings (or None). No interpretation applied.
    """
    external_id:       str            # portal's own listing identifier (from URL or page)
    source:            str            # 'propertypro' | 'privateproperty' | 'nigeriapropertycentre' | 'jiji'
    url:               str            # full listing URL
    title:             str            # raw listing title
    raw_price:         Optional[str]  # e.g. "₦45,000,000" / "45M" / "45 million naira" / None
    raw_price_type:    Optional[str]  # e.g. "For Sale" / "For Rent" / "For Short Let" / None
    raw_bedrooms:      Optional[str]  # e.g. "3 Bedrooms" / "3 bed" / None
    raw_bathrooms:     Optional[str]  # e.g. "2 Bathrooms" / None
    raw_address:       Optional[str]  # full address string as listed
    raw_floor_area:    Optional[str]  # e.g. "250 sqm" / "2,700 sqft" / None
    description:       Optional[str]  # full listing description text
    property_type_raw: Optional[str]  # e.g. "Detached Duplex" / "Flat / Apartment"
    agent_name:        Optional[str]  # listed agent or developer name


@dataclass
class NormalisedListing:
    """
    Cleaned, typed, database-ready listing record.
    All monetary values in kobo (BIGINT). All areas in sqm (float).
    """
    external_id:              str
    source:                   str
    url:                      str
    title:                    str
    description:              Optional[str]

    # Price
    price_kobo:               Optional[int]   # ALWAYS kobo — ₦45M = 4_500_000_000
    price_parse_failed:       bool            # True when raw price present but unparseable
    price_type:               Optional[str]   # 'FOR_SALE' | 'FOR_RENT'

    # Property attributes
    property_type:            Optional[str]
    bedrooms:                 Optional[int]
    bathrooms:                Optional[int]
    floor_area_sqm:           Optional[float] # sqm — converted from sqft where needed
    floor_area_source:        str             # 'PORTAL' | 'OSM' | 'NONE'

    # Location
    raw_address:              Optional[str]
    neighbourhood:            Optional[str]
    neighbourhood_normalised: bool            # True when matched to canonical list
    city:                     Optional[str]   # 'LAGOS' | 'ABUJA' | raw city name
    lat:                      Optional[float]
    lng:                      Optional[float]
    geocoded:                 bool

    # Agent / marketing
    agent_name:               Optional[str]
    diaspora_targeted:        bool            # True when description signals diaspora buyer

    # Lifecycle (set by db_writer, not normaliser)
    first_seen_at:            Optional[datetime] = None
    last_seen_at:             Optional[datetime] = None
    listing_status:           str = 'ACTIVE'   # 'ACTIVE' | 'REMOVED'
    suspected_sold:           bool = False
    missed_run_count:         int = 0