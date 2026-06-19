-- =============================================================================
-- PS-0 PropertyScraper — Migration 003
-- Adds next_health_check_at and index to scraped_listings for optimization.
--
-- Run after 002_add_health_check_at.sql. Idempotent (IF NOT EXISTS guards).
-- =============================================================================

ALTER TABLE raw_data.scraped_listings
    ADD COLUMN IF NOT EXISTS next_health_check_at TIMESTAMPTZ;

-- Backfill next_health_check_at for existing checked active properties
UPDATE raw_data.scraped_listings
SET next_health_check_at = last_health_check_at + (
    CASE
        WHEN first_seen_at >= last_health_check_at - INTERVAL '14 days' THEN INTERVAL '1.9 days'
        WHEN first_seen_at >= last_health_check_at - INTERVAL '60 days' THEN INTERVAL '6.8 days'
        ELSE INTERVAL '13.8 days'
    END
)
WHERE next_health_check_at IS NULL AND last_health_check_at IS NOT NULL;

-- Index supports the optimized health check selection query
CREATE INDEX IF NOT EXISTS idx_sl_next_health_check
    ON raw_data.scraped_listings (next_health_check_at ASC NULLS FIRST)
    WHERE listing_status = 'ACTIVE';
