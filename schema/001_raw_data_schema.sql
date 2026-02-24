CREATE SCHEMA IF NOT EXISTS raw_data

-- scraped property listings table - current state only
CREATE TABLE raw_data.scraped_listings (
    id                          BIGSERIAL PRIMARY KEY,
    external_id                 TEXT NOT NULL,
    url                         TEXT NOT NULL UNIQUE,
    source                      TEXT NOT NULL,                  -- 'propertypro' | privateproperty', etc
    title                       TEXT NOT NULL,
    description                 TEXT,
    price_kobo                  BIGINT CHECK (price_kobo > 0),  -- ALWAYS in kobo
    price_type                  TEXT,                           -- 'FOR_SALE' | 'FOR_RENT'
    price_parse_failed          BOOLEAN NOT NULL DEFAULT FALSE,
    property_type               TEXT,
    bedrooms                    SMALLINT,
    bathrooms                   SMALLINT,
    floor_area_sqm              NUMERIC(8,2) DEFAULT NULL       -- sqm. NULL if not stated
    floor_area_source           TEXT DEFAULT 'NONE'
    raw_address                 TEXT,
    neighbourhood               VARCHAR(60),
    neighbourhood_normalised    BOOLEAN NOT NULL DEFAULT FALSE,
    city                        TEXT,
    lat                         DOUBLE PRECISION,               -- latitude
    lng                         DOUBLE PRECISION,               -- longitude
    agent_name                  TEXT,
    diaspora_targeted           BOOLEAN NOT NULL DEFAULT FALSE,
    listing_status              TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(listing_status IN ('ACTIVE', 'REMOVED')),
    suspected_sold              BOOLEAN NOT NULL DEFAULT FALSE,
    missed_run_count            SMALLINT NOT NULL DEFAULT 0,
    first_seen_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source, external_id)

);

-- listing history - every price change and status change event
CREATE TABLE raw_data.listing_history (
    id                          BIGSERIAL PRIMARY KEY,
    listing_id                  BIGINT NOT NULL REFERENCES raw_data.scraped_listings(id),
    event_type                  TEXT NOT NULL CHECK(event_type IN ('LISTED', 'PRICE_CHANGE', 'REMOVED', 'RELISTED')),  
    old_value                   BIGINT,                         -- price_kobo before change (NULL if LISTED)
    new_value                   BIGINT,                         -- price_kobo after change (NULL if REMOVED)
    event_date                  DATE NOT NULL DEFAULT CURRENT_DATE,
    notes                       TEXT
);

-- geo-coding cache - persistent across runs
CREATE TABLE raw_data.geocode_cache(
    neighbourhood               VARCHAR(60) DEFAULT NOT NULL,
    city                        VARCHAR(10) DEFAULT NOT NULL,
    lat                         DOUBLE PRECISION NOT NULL,
    lng                         DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(neighbourhood, city)
);

-- scraper run log - one row per portal per run
CREATE TABLE raw_data.scrape_runs_log(
    id                          BIGSERIAL PRIMARY KEY,
    run_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                      TEXT NOT NULL, 
    new_listings                INT NOT NULL DEFAULT 0,
    updated_listings            INT NOT NULL DEFAULT 0,
    suspected_sold              INT NOT NULL DEFAULT 0,
    price_changes               INT NOT NULL DEFAULT 0,
    status                      TEXT NOT NULL CHECK (status IN ('SUCCESS', 'PARTIAL', 'FAILED')),
    error_message               TEXT, BIGINT,
    duration_seconds            NUMERIC(8,2)
);

-- anticipated indexes for faster lookups on consumer projects
CREATE INDEX idx_sl_source            ON raw_data.scraped_listings(source);
CREATE INDEX idx_sl_city              ON raw_data.scraped_listings(city);
CREATE INDEX idx_sl_neighbourhood     ON raw_data.scraped_listings(neighbourhood);
CREATE INDEX idx_sl_price_kobo        ON raw_data.scraped_listings(price_kobo);
CREATE INDEX idx_sl_bedrooms          ON raw_data.scraped_listings(bedrooms);
CREATE INDEX idx_sl_listing_status    ON raw_data.scraped_listings(listing_status);
CREATE INDEX idx_sl_suspected_sold    ON raw_data.scraped_listings(suspected_sold);
CREATE INDEX idx_sl_first_seen        ON raw_data.scraped_listings(first_seen_at);
CREATE INDEX idx_sl_diaspora          ON raw_data.scraped_listings(diaspora_targeted);
CREATE INDEX idx_lh_listing_id        ON raw_data.listing_history(listing_id);
CREATE INDEX idx_lh_event_type        ON raw_data.listing_history(event_type);
CREATE INDEX idx_lh_event_date        ON raw_data.listing_history(event_date);
-- composite for market report neighbourhood price queries
CREATE INDEX idx_sl_mkt_report        ON raw_data.scraped_listings(city, neighbourhood, listing_status, first_seen_at);
