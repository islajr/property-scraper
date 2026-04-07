-- =============================================================================
-- PS-0 PropertyScraper — Migration 002
-- Adds last_health_check_at to scraped_listings.
--
-- Run after 001_raw_data_schema.sql. Idempotent (IF NOT EXISTS guards).
-- =============================================================================

ALTER TABLE raw_data.scraped_listings
    ADD COLUMN IF NOT EXISTS last_health_check_at TIMESTAMPTZ;

-- Index supports the health check candidate query:
--   WHERE listing_status = 'ACTIVE'
--     AND (last_health_check_at IS NULL
--          OR last_health_check_at < NOW() - INTERVAL '14 days')
-- Partial index on ACTIVE listings only — keeps it small.
CREATE INDEX IF NOT EXISTS idx_sl_health_check
    ON raw_data.scraped_listings (last_health_check_at ASC NULLS FIRST)
    WHERE listing_status = 'ACTIVE';