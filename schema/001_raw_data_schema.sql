-- =============================================================================
-- PS-0 PropertyScraper — Database Schema
-- Schema: raw_data (isolated from all other application schemas)
-- Target: Supabase free tier (PostgreSQL 15)
-- Run once before the first scraper run.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS raw_data;

-- =============================================================================
-- Main listings table — CURRENT STATE only.
-- Full event history is in listing_history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw_data.scraped_listings (
    id                       BIGSERIAL PRIMARY KEY,

    -- Deduplication key
    external_id              TEXT NOT NULL,
    source                   TEXT NOT NULL,    -- 'propertypro' | 'privateproperty' | 'nigeriapropertycentre' | 'jiji'
    UNIQUE (source, external_id),

    -- Core listing data
    url                      TEXT NOT NULL,
    title                    TEXT,
    description              TEXT,

    -- Price — ALWAYS kobo (BIGINT). ₦45,000,000 = 4500000000
    price_kobo               BIGINT,
    price_parse_failed       BOOLEAN NOT NULL DEFAULT FALSE,
    price_type               TEXT,             -- 'FOR_SALE' | 'FOR_RENT'

    -- Property attributes
    property_type            TEXT,
    bedrooms                 SMALLINT,
    bathrooms                SMALLINT,
    floor_area_sqm           NUMERIC(8,2),     -- sqm only. NULL if not stated.
    floor_area_source        TEXT DEFAULT 'NONE',  -- 'PORTAL' | 'OSM' | 'NONE'

    -- Location
    raw_address              TEXT,
    neighbourhood            VARCHAR(60),
    neighbourhood_normalised BOOLEAN NOT NULL DEFAULT FALSE,
    city                     TEXT,
    lat                      DOUBLE PRECISION,
    lng                      DOUBLE PRECISION,
    geocoded                 BOOLEAN NOT NULL DEFAULT FALSE,

    -- Agent / marketing
    agent_name               TEXT,
    diaspora_targeted        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Lifecycle tracking
    listing_status           TEXT NOT NULL DEFAULT 'ACTIVE',  -- 'ACTIVE' | 'REMOVED'
    suspected_sold           BOOLEAN NOT NULL DEFAULT FALSE,
    missed_run_count         SMALLINT NOT NULL DEFAULT 0,
    first_seen_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Listing history — every price change and status change event.
-- This is the listing-as-transaction-proxy engine.
-- event_type: 'LISTED' | 'PRICE_CHANGE' | 'REMOVED' | 'RELISTED'
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw_data.listing_history (
    id          BIGSERIAL PRIMARY KEY,
    listing_id  BIGINT NOT NULL REFERENCES raw_data.scraped_listings(id),
    event_type  TEXT NOT NULL,
    old_value   BIGINT,        -- price_kobo before change (NULL for LISTED)
    new_value   BIGINT,        -- price_kobo after change (NULL for REMOVED)
    event_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    notes       TEXT
);

-- =============================================================================
-- Geocode cache — keyed on (neighbourhood, city). Persistent across runs.
-- After 4–6 weeks warm-up, >95% of new listings will hit this cache
-- without consuming any Google Maps API quota.
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw_data.geocode_cache (
    neighbourhood  VARCHAR(60) NOT NULL,
    city           TEXT NOT NULL,
    lat            DOUBLE PRECISION NOT NULL,
    lng            DOUBLE PRECISION NOT NULL,
    PRIMARY KEY    (neighbourhood, city)
);

-- =============================================================================
-- Run log — one row per portal per run.
-- status: 'SUCCESS' | 'PARTIAL' | 'FAILED'
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw_data.scrape_runs (
    id                BIGSERIAL PRIMARY KEY,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source            TEXT NOT NULL,
    new_listings      INT NOT NULL DEFAULT 0,
    updated_listings  INT NOT NULL DEFAULT 0,
    suspected_sold    INT NOT NULL DEFAULT 0,
    price_changes     INT NOT NULL DEFAULT 0,
    status            TEXT NOT NULL,
    error_message     TEXT,
    duration_seconds  NUMERIC(8,2)
);

-- =============================================================================
-- Indexes — tuned for anticipated AVM and Market Report query patterns
-- =============================================================================

-- Single-column indexes
CREATE INDEX IF NOT EXISTS idx_sl_source           ON raw_data.scraped_listings(source);
CREATE INDEX IF NOT EXISTS idx_sl_city             ON raw_data.scraped_listings(city);
CREATE INDEX IF NOT EXISTS idx_sl_neighbourhood    ON raw_data.scraped_listings(neighbourhood);
CREATE INDEX IF NOT EXISTS idx_sl_price_kobo       ON raw_data.scraped_listings(price_kobo);
CREATE INDEX IF NOT EXISTS idx_sl_bedrooms         ON raw_data.scraped_listings(bedrooms);
CREATE INDEX IF NOT EXISTS idx_sl_listing_status   ON raw_data.scraped_listings(listing_status);
CREATE INDEX IF NOT EXISTS idx_sl_suspected_sold   ON raw_data.scraped_listings(suspected_sold);
CREATE INDEX IF NOT EXISTS idx_sl_first_seen       ON raw_data.scraped_listings(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_sl_diaspora         ON raw_data.scraped_listings(diaspora_targeted);

-- History indexes
CREATE INDEX IF NOT EXISTS idx_lh_listing_id       ON raw_data.listing_history(listing_id);
CREATE INDEX IF NOT EXISTS idx_lh_event_type       ON raw_data.listing_history(event_type);
CREATE INDEX IF NOT EXISTS idx_lh_event_date       ON raw_data.listing_history(event_date);

-- Composite — Market Report neighbourhood price queries
CREATE INDEX IF NOT EXISTS idx_sl_mkt_report
    ON raw_data.scraped_listings(city, neighbourhood, listing_status, first_seen_at);