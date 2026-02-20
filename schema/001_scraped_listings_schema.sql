CREATE SCHEMA IF NOT EXISTS scraped_listings

-- define properties table
CREATE TABLE scraped_listings.properties (
    id                          UUID PRIMARY KEY DEFAULT gen_random__uuid(),
    source_url                  TEXT NOT NULL UNIQUE,
    source_portal               VARCHAR(30) NOT NULL,
    price_ngn                   BIGINT CHECK (price_ngn > 0),
    price_type                  VARCHAR(15),
    price_parse_failed          BOOLEAN NOT NULL DEFAULT FALSE,
    bedrooms                    SMALLINT,
    bathrooms                   SMALLINT,
    property_type               VARCHAR(30),
    raw_address                 TEXT,
    neighbourhood               VARCHAR(60),
    neighbourhood_normalised    BOOLEAN DEFAULT FALSE,
    city                        VARCHAR(25),
    sqft                        INT,
    description_text            TEXT,
    longitude                   DOUBLE,
    latitude                    DOUBLE,
    listing_status              VARCHAR(10) NOT NULL DEFAULT 'ACTIVE',
    missed_run_count            SMALLINT NOT NULL DEFAULT 0,
    first_seen_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()

);

-- geo-coding cache
CREATE TABLE scraped_listings.geocode_cache(
    neighbourhood               VARCHAR(60) DEFAULT NOT NULL,
    city                        VARCHAR(10) DEFAULT NOT NULL,
    latitude                    DOUBLE NOT NULL,
    longitude                   DOUBLE NOT NULL,
    PRIMARY KEY(neighbourhood, city)
);

-- scraper run log
CREATE TABLE scraped_listings.run_log(
    id                          BIGSERIAL PRIMARY KEY,
    run_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    portal                      VARCHAR(30) NOT NULL, 
    new_listings                INT NOT NULL DEFAULT 0,
    updated_listings            INT NOT NULL DEFAULT 0,
    failed_listings             INT NOT NULL DEFAULT 0,
    status                      VARCHAR(10) NOT NULL CHECK (status IN ('SUCCESS', 'PARTIAL', 'FAILED')),
    error_message               TEXT
);

-- anticipated indexes for faster lookups on consumer projects
CREATE INDEX idx_sl_city            ON scraped_listings.properties(city);
CREATE INDEX idx_sl_neighbourhood   ON scraped_listings.properties(neighbourhood);
CREATE INDEX idx_sl_price_ngn       ON scraped_listings.properties(price_ngn);
CREATE INDEX idx_sl_bedrooms        ON scraped_listings.properties(bedrooms);
CREATE INDEX idx_sl_first_seen      ON scraped_listings.properties(first_seen_at);
CREATE INDEX idx_sl_listing_status  ON scraped_listings.properties(listing_status);
CREATE INDEX idx_sl_property_type   ON scraped_listings.properties(property_type);
