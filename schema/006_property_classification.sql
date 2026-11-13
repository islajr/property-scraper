-- Additive contract: old labels remain untouched and explicitly unreviewed.
-- Apply before deploying classification-aware writers. Safe to rerun.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS raw_data.property_type_versions (
    version TEXT PRIMARY KEY
);
INSERT INTO raw_data.property_type_versions VALUES ('property-types-v1') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS raw_data.property_type_vocabulary (
    version TEXT NOT NULL REFERENCES raw_data.property_type_versions(version),
    code TEXT NOT NULL,
    category TEXT NOT NULL,
    family TEXT NOT NULL,
    attachment TEXT,
    asset_scope TEXT,
    PRIMARY KEY (version, code),
    UNIQUE (version, code, category, family)
);
INSERT INTO raw_data.property_type_vocabulary
    (version, code, category, family, attachment, asset_scope) VALUES
    ('property-types-v1', 'BLOCK_OF_FLATS', 'RESIDENTIAL', 'BLOCK_OF_FLATS', NULL, 'WHOLE_BUILDING'),
    ('property-types-v1', 'BUNGALOW', 'RESIDENTIAL', 'BUNGALOW', NULL, NULL),
    ('property-types-v1', 'COMMERCIAL_OTHER', 'COMMERCIAL', 'COMMERCIAL_OTHER', NULL, NULL),
    ('property-types-v1', 'COMMERCIAL_SHOP', 'COMMERCIAL', 'COMMERCIAL_SHOP', NULL, NULL),
    ('property-types-v1', 'DETACHED_BUNGALOW', 'RESIDENTIAL', 'BUNGALOW', 'DETACHED', NULL),
    ('property-types-v1', 'DETACHED_DUPLEX', 'RESIDENTIAL', 'DUPLEX', 'DETACHED', NULL),
    ('property-types-v1', 'DUPLEX', 'RESIDENTIAL', 'DUPLEX', NULL, NULL),
    ('property-types-v1', 'FACTORY', 'COMMERCIAL', 'FACTORY', NULL, NULL),
    ('property-types-v1', 'FILLING_STATION', 'COMMERCIAL', 'FILLING_STATION', NULL, NULL),
    ('property-types-v1', 'FLAT_APARTMENT', 'RESIDENTIAL', 'APARTMENT', NULL, 'UNIT'),
    ('property-types-v1', 'GUEST_HOUSE', 'COMMERCIAL', 'GUEST_HOUSE', NULL, 'WHOLE_BUILDING'),
    ('property-types-v1', 'HOSPITAL', 'COMMERCIAL', 'HOSPITAL', NULL, NULL),
    ('property-types-v1', 'HOTEL', 'COMMERCIAL', 'HOTEL', NULL, 'WHOLE_BUILDING'),
    ('property-types-v1', 'HOUSE', 'RESIDENTIAL', 'HOUSE', NULL, NULL),
    ('property-types-v1', 'LAND', 'LAND', 'LAND', NULL, 'LAND_PARCEL'),
    ('property-types-v1', 'LAND_SERVICED', 'LAND', 'LAND', NULL, 'LAND_PARCEL'),
    ('property-types-v1', 'MAISONETTE', 'RESIDENTIAL', 'APARTMENT', NULL, 'UNIT'),
    ('property-types-v1', 'MANSION', 'RESIDENTIAL', 'HOUSE', NULL, NULL),
    ('property-types-v1', 'MINI_FLAT', 'RESIDENTIAL', 'APARTMENT', NULL, 'UNIT'),
    ('property-types-v1', 'MIXED_USE_PROPERTY', 'MIXED_USE', 'MIXED_USE', NULL, NULL),
    ('property-types-v1', 'OFFICE', 'COMMERCIAL', 'OFFICE', NULL, NULL),
    ('property-types-v1', 'OFFICE_BUILDING', 'COMMERCIAL', 'OFFICE_BUILDING', NULL, 'WHOLE_BUILDING'),
    ('property-types-v1', 'PENTHOUSE', 'RESIDENTIAL', 'APARTMENT', NULL, 'UNIT'),
    ('property-types-v1', 'RESTAURANT', 'COMMERCIAL', 'RESTAURANT', NULL, NULL),
    ('property-types-v1', 'ROOM', 'RESIDENTIAL', 'ROOM', NULL, 'UNIT'),
    ('property-types-v1', 'SCHOOL', 'COMMERCIAL', 'SCHOOL', NULL, NULL),
    ('property-types-v1', 'SELF_CONTAINED', 'RESIDENTIAL', 'ROOM', NULL, 'UNIT'),
    ('property-types-v1', 'SEMI_DETACHED_BUNGALOW', 'RESIDENTIAL', 'BUNGALOW', 'SEMI_DETACHED', NULL),
    ('property-types-v1', 'SEMI_DETACHED_DUPLEX', 'RESIDENTIAL', 'DUPLEX', 'SEMI_DETACHED', NULL),
    ('property-types-v1', 'SHOWROOM', 'COMMERCIAL', 'SHOWROOM', NULL, NULL),
    ('property-types-v1', 'STUDIO', 'RESIDENTIAL', 'APARTMENT', NULL, 'UNIT'),
    ('property-types-v1', 'TERRACED_BUNGALOW', 'RESIDENTIAL', 'BUNGALOW', 'TERRACED', NULL),
    ('property-types-v1', 'TERRACED_DUPLEX', 'RESIDENTIAL', 'DUPLEX', 'TERRACED', NULL),
    ('property-types-v1', 'TOWNHOUSE', 'RESIDENTIAL', 'HOUSE', NULL, NULL),
    ('property-types-v1', 'VILLA', 'RESIDENTIAL', 'HOUSE', NULL, NULL),
    ('property-types-v1', 'WAREHOUSE', 'COMMERCIAL', 'WAREHOUSE', NULL, NULL)
ON CONFLICT DO NOTHING;

ALTER TABLE raw_data.scraped_listings
    ADD COLUMN IF NOT EXISTS property_category TEXT,
    ADD COLUMN IF NOT EXISTS property_type_family TEXT,
    ADD COLUMN IF NOT EXISTS property_attachment TEXT,
    ADD COLUMN IF NOT EXISTS property_asset_scope TEXT,
    ADD COLUMN IF NOT EXISTS property_land_use TEXT,
    ADD COLUMN IF NOT EXISTS property_type_raw TEXT,
    ADD COLUMN IF NOT EXISTS property_type_raw_source TEXT,
    ADD COLUMN IF NOT EXISTS property_type_status TEXT NOT NULL DEFAULT 'LEGACY_UNREVIEWED',
    ADD COLUMN IF NOT EXISTS property_type_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS property_type_version TEXT REFERENCES raw_data.property_type_versions(version),
    ADD COLUMN IF NOT EXISTS property_type_classified_at TIMESTAMPTZ;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='sl_property_type_contract'
                   AND conrelid='raw_data.scraped_listings'::regclass) THEN
        ALTER TABLE raw_data.scraped_listings ADD CONSTRAINT sl_property_type_contract CHECK (
            property_type_status IN ('CLASSIFIED','INSUFFICIENT_EVIDENCE','AMBIGUOUS','UNSUPPORTED','LEGACY_UNREVIEWED')
            AND (property_category IS NULL OR property_category IN ('RESIDENTIAL','COMMERCIAL','LAND','MIXED_USE'))
            AND (property_attachment IS NULL OR property_attachment IN ('DETACHED','SEMI_DETACHED','TERRACED'))
            AND (property_asset_scope IS NULL OR property_asset_scope IN ('UNIT','WHOLE_BUILDING','MULTIPLE_UNITS','LAND_PARCEL'))
            AND (property_land_use IS NULL OR property_land_use IN ('RESIDENTIAL','COMMERCIAL','INDUSTRIAL','AGRICULTURAL','MIXED_USE'))
            AND (property_type_raw_source IS NULL OR property_type_raw_source IN ('PORTAL_TYPE','BREADCRUMB'))
            AND ((property_type_raw IS NULL) = (property_type_raw_source IS NULL))
            AND jsonb_typeof(property_type_evidence)='object'
            AND CASE WHEN property_type_status='LEGACY_UNREVIEWED' THEN
                property_type_version IS NULL AND property_type_classified_at IS NULL
            ELSE
                property_type_version IS NOT NULL AND property_type_classified_at IS NOT NULL
                AND COALESCE(jsonb_typeof(property_type_evidence->'matches')='array', FALSE)
                AND CASE WHEN property_type_status='CLASSIFIED' THEN
                    property_type IS NOT NULL AND property_category IS NOT NULL AND property_type_family IS NOT NULL
                    AND jsonb_array_length(property_type_evidence->'matches')>0
                ELSE property_type IS NULL AND property_type_family IS NULL
                    AND property_attachment IS NULL AND property_asset_scope IS NULL AND property_land_use IS NULL END
            END
            AND (property_attachment IS NULL OR property_type_family IN ('HOUSE','DUPLEX','BUNGALOW'))
            AND (property_land_use IS NULL OR property_category='LAND')
            AND CASE
                WHEN property_type_status <> 'CLASSIFIED' THEN TRUE
                WHEN property_type IN ('DETACHED_DUPLEX','DETACHED_BUNGALOW') THEN property_attachment IS NOT DISTINCT FROM 'DETACHED'
                WHEN property_type IN ('SEMI_DETACHED_DUPLEX','SEMI_DETACHED_BUNGALOW') THEN property_attachment IS NOT DISTINCT FROM 'SEMI_DETACHED'
                WHEN property_type IN ('TERRACED_DUPLEX','TERRACED_BUNGALOW') THEN property_attachment IS NOT DISTINCT FROM 'TERRACED'
                WHEN property_type IN ('DUPLEX','BUNGALOW') THEN property_attachment IS NULL
                ELSE TRUE END
            AND (property_type_status <> 'CLASSIFIED' OR CASE
                WHEN property_type IN ('LAND','LAND_SERVICED') THEN property_asset_scope IS NOT DISTINCT FROM 'LAND_PARCEL'
                WHEN property_type IN ('BLOCK_OF_FLATS','OFFICE_BUILDING','HOTEL','GUEST_HOUSE') THEN property_asset_scope IS NOT DISTINCT FROM 'WHOLE_BUILDING'
                ELSE TRUE END)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='sl_property_type_vocabulary'
                   AND conrelid='raw_data.scraped_listings'::regclass) THEN
        ALTER TABLE raw_data.scraped_listings ADD CONSTRAINT sl_property_type_vocabulary
            FOREIGN KEY (property_type_version,property_type,property_category,property_type_family)
            REFERENCES raw_data.property_type_vocabulary(version,code,category,family) NOT VALID;
    END IF;
END $$;
ALTER TABLE raw_data.scraped_listings VALIDATE CONSTRAINT sl_property_type_contract;
ALTER TABLE raw_data.scraped_listings VALIDATE CONSTRAINT sl_property_type_vocabulary;

CREATE TABLE IF NOT EXISTS raw_data.property_classification_history (
    id BIGSERIAL PRIMARY KEY,
    listing_id BIGINT NOT NULL REFERENCES raw_data.scraped_listings(id),
    run_id UUID NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('DISCOVERY','HEALTH_CHECK','BACKFILL','REVERSAL')),
    old_classification JSONB,
    new_classification JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reverses_id BIGINT REFERENCES raw_data.property_classification_history(id)
);
CREATE INDEX IF NOT EXISTS idx_property_classification_listing
    ON raw_data.property_classification_history(listing_id,id);
CREATE INDEX IF NOT EXISTS idx_property_classification_run
    ON raw_data.property_classification_history(run_id);
CREATE OR REPLACE FUNCTION raw_data.property_classification_history_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'Property classification history is append-only; append a reversal instead';
END $$;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='property_classification_history_immutable'
                   AND tgrelid='raw_data.property_classification_history'::regclass) THEN
        CREATE TRIGGER property_classification_history_immutable
            BEFORE UPDATE OR DELETE ON raw_data.property_classification_history
            FOR EACH ROW EXECUTE FUNCTION raw_data.property_classification_history_immutable();
    END IF;
END $$;

CREATE OR REPLACE VIEW raw_data.property_classification_coverage AS
SELECT source,listing_status,property_type_status,property_type_version,COUNT(*) AS listing_count
FROM raw_data.scraped_listings
GROUP BY source,listing_status,property_type_status,property_type_version;
COMMIT;
