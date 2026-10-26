-- Additive pricing context. Legacy amounts and lifecycle/history remain unchanged.
-- Apply before deploying pricing-aware writers. Safe to apply repeatedly.
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE raw_data.scraped_listings
    ADD COLUMN IF NOT EXISTS price_period TEXT,
    ADD COLUMN IF NOT EXISTS price_period_count INTEGER,
    ADD COLUMN IF NOT EXISTS price_period_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS price_period_source TEXT NOT NULL DEFAULT 'LEGACY_UNKNOWN',
    ADD COLUMN IF NOT EXISTS raw_price_text TEXT,
    ADD COLUMN IF NOT EXISTS price_period_evidence TEXT,
    ADD COLUMN IF NOT EXISTS price_currency TEXT,
    ADD COLUMN IF NOT EXISTS price_basis TEXT NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS pricing_observed_at TIMESTAMPTZ;
ALTER TABLE raw_data.listing_history
    ADD COLUMN IF NOT EXISTS old_pricing JSONB,
    ADD COLUMN IF NOT EXISTS new_pricing JSONB,
    ADD COLUMN IF NOT EXISTS price_comparable BOOLEAN NOT NULL DEFAULT FALSE;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sl_rental_period_contract'
                   AND conrelid = 'raw_data.scraped_listings'::regclass) THEN
        ALTER TABLE raw_data.scraped_listings ADD CONSTRAINT sl_rental_period_contract CHECK (
            price_period_status IN ('KNOWN', 'UNKNOWN', 'CONFLICT', 'UNSUPPORTED', 'NOT_APPLICABLE')
            AND price_period_source IN ('PORTAL_PRICE', 'TITLE', 'DESCRIPTION', 'MANUAL', 'LEGACY_UNKNOWN')
            AND price_basis IN ('PROPERTY', 'AREA', 'ROOM', 'PERSON', 'UNKNOWN')
            AND (price_currency IS NULL OR price_currency IN ('NGN', 'USD', 'GBP', 'EUR'))
            AND CASE WHEN price_period_status = 'KNOWN' THEN
                price_type IS NOT NULL AND price_type IN ('FOR_RENT', 'FOR_SHORT_LET')
                AND price_period IS NOT NULL AND price_period IN ('HOUR','DAY','NIGHT','WEEK','MONTH','YEAR')
                AND price_period_count IS NOT NULL AND price_period_count > 0
            ELSE price_period IS NULL AND price_period_count IS NULL END
            AND (price_period_status <> 'NOT_APPLICABLE' OR (price_type IS NOT NULL AND price_type = 'FOR_SALE'))
        ) NOT VALID;
    END IF;
END $$;
ALTER TABLE raw_data.scraped_listings VALIDATE CONSTRAINT sl_rental_period_contract;

-- Each applied metadata-only repair has an independent, reversible audit record.
CREATE TABLE IF NOT EXISTS raw_data.rental_pricing_backfills (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    listing_id BIGINT NOT NULL REFERENCES raw_data.scraped_listings(id),
    rule_version TEXT NOT NULL,
    old_pricing JSONB NOT NULL,
    new_pricing JSONB NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reversed_at TIMESTAMPTZ,
    applied_row_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_rental_backfill_run ON raw_data.rental_pricing_backfills(run_id);

-- Never mix unknown periods, currency, property basis, or different cadences.
CREATE OR REPLACE VIEW raw_data.comparable_rental_prices AS
SELECT id, source, external_id, city, neighbourhood, listing_status, price_type,
       price_kobo, price_period, price_period_count, pricing_observed_at
FROM raw_data.scraped_listings
WHERE price_type IN ('FOR_RENT','FOR_SHORT_LET')
  AND price_period_status = 'KNOWN' AND price_currency = 'NGN'
  AND price_basis = 'PROPERTY' AND price_kobo > 0 AND NOT price_parse_failed;
COMMIT;
