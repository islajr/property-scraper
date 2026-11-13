-- Read-only inventory of the existing classifier's vocabulary and stored data.
-- Run with DATABASE_URL exported in your environment:
-- psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f scripts/audit_property_types.sql
-- This inventories legacy results. It does not implement the proposed taxonomy.

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';

SELECT transaction_timestamp() AS audited_at,
       MIN(first_seen_at) AS oldest_first_seen,
       MAX(first_seen_at) AS newest_first_seen,
       MAX(last_seen_at) AS latest_last_seen
FROM raw_data.scraped_listings;

-- These are the 19 codes in the pre-taxonomy PROPERTY_TYPE_MAP, including
-- allowed codes with no stored rows. Vocabulary membership is not correctness.
WITH legacy_vocabulary(code) AS (
    VALUES ('FLAT_APARTMENT'), ('MINI_FLAT'), ('STUDIO'), ('PENTHOUSE'),
           ('DETACHED_DUPLEX'), ('SEMI_DETACHED_DUPLEX'), ('TERRACED_DUPLEX'),
           ('DETACHED_BUNGALOW'), ('SEMI_DETACHED_BUNGALOW'), ('TERRACED_BUNGALOW'),
           ('MANSION'), ('VILLA'), ('OFFICE'), ('COMMERCIAL_SHOP'), ('SHOWROOM'),
           ('WAREHOUSE'), ('COMMERCIAL_OTHER'), ('LAND'), ('LAND_SERVICED')
)
SELECT CASE WHEN GROUPING(sl.source) = 1 THEN 'ALL' ELSE sl.source END AS source,
       COUNT(*) AS listings,
       COUNT(DISTINCT sl.property_type) AS distinct_nonnull_types,
       COUNT(*) FILTER (WHERE sl.property_type IS NULL) AS null_types,
       COUNT(*) FILTER (WHERE BTRIM(sl.property_type) = '') AS blank_types,
       COUNT(*) FILTER (WHERE v.code IS NOT NULL) AS within_legacy_vocabulary,
       COUNT(*) FILTER (WHERE v.code IS NULL) AS outside_legacy_vocabulary
FROM raw_data.scraped_listings sl
LEFT JOIN legacy_vocabulary v ON sl.property_type = v.code
GROUP BY GROUPING SETS ((sl.source), ())
ORDER BY GROUPING(sl.source) DESC, sl.source;

SELECT source, listing_status, COUNT(*) AS listings,
       COUNT(DISTINCT property_type) AS distinct_nonnull_types
FROM raw_data.scraped_listings
GROUP BY source, listing_status
ORDER BY source, listing_status;

-- Full frequency inventory, including NULL and arbitrary title fragments.
SELECT property_type, COUNT(*) AS listings
FROM raw_data.scraped_listings
GROUP BY property_type
ORDER BY listings DESC, property_type NULLS LAST;

-- Diagnostic indicators only: titles may be misleading, mixed, or conflicting.
-- Counts may overlap and must not be summed or described as verified errors.
SELECT COUNT(*) FILTER (
           WHERE property_type = 'DETACHED_DUPLEX'
             AND title ~* 'semi[ -]detached'
       ) AS semi_detached_title_as_detached,
       COUNT(*) FILTER (
           WHERE property_type = 'FLAT_APARTMENT'
             AND title ~* '\mmini[ -]?flat\M'
       ) AS mini_flat_title_as_flat,
       COUNT(*) FILTER (
           WHERE property_type = 'FLAT_APARTMENT'
             AND title ~* '\mstudio\M'
       ) AS studio_title_as_flat,
       COUNT(*) FILTER (
           WHERE property_type = 'DETACHED_DUPLEX'
             AND title !~* '\mdetached\M'
       ) AS detached_without_detached_in_title,
       COUNT(*) FILTER (
           WHERE property_type = 'LAND'
             AND title ~* '\mserviced\M'
       ) AS serviced_title_as_land
FROM raw_data.scraped_listings;

-- Representative rows for incomplete labels and categories missing from the map.
-- These are bounded examples, not a random evaluation set or a backfill result.
SELECT DISTINCT ON (property_type)
       id, source, title, property_type,
       LEFT(description, 350) AS description_excerpt
FROM raw_data.scraped_listings
WHERE property_type IN (
    'DETACHED', 'TERRACED', 'SEMI-DETACHED', 'SELF_CONTAIN_(SINGLE',
    'BLOCK_OF', 'HOTEL_/_GUEST', 'MIXED-USE', 'RESIDENTIAL', 'HOUSE',
    'COMMERCIAL', 'FILLING'
)
ORDER BY property_type, id DESC;

-- Two recent examples for each diagnostic; evidence needs review before apply.
WITH diagnostics(reason, expected_current_type, title_pattern) AS (
    VALUES ('semi_detached_title_as_detached', 'DETACHED_DUPLEX', 'semi[ -]detached'),
           ('mini_flat_title_as_flat', 'FLAT_APARTMENT', '\mmini[ -]?flat\M'),
           ('studio_title_as_flat', 'FLAT_APARTMENT', '\mstudio\M')
), examples AS (
    SELECT d.reason, sl.id, sl.source, sl.title, sl.property_type,
           ROW_NUMBER() OVER (PARTITION BY d.reason ORDER BY sl.id DESC) AS rank
    FROM raw_data.scraped_listings sl
    JOIN diagnostics d ON sl.property_type = d.expected_current_type
                      AND sl.title ~* d.title_pattern
)
SELECT reason, id, source, title, property_type
FROM examples
WHERE rank <= 2
ORDER BY reason, id DESC;

ROLLBACK;
