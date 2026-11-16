-- Register the reviewed spelling/context revision before deploying v2 writers.
-- The vocabulary is unchanged. Existing rows, audit history, and v1 remain intact.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$ BEGIN
    IF (SELECT count(*) FROM raw_data.property_type_vocabulary
        WHERE version = 'property-types-v1') <> 36 THEN
        RAISE EXCEPTION 'Apply migration 006 with its complete vocabulary before migration 008';
    END IF;
END $$;

INSERT INTO raw_data.property_type_versions VALUES ('property-types-v2')
ON CONFLICT DO NOTHING;

INSERT INTO raw_data.property_type_vocabulary
    (version, code, category, family, attachment, asset_scope)
SELECT 'property-types-v2', code, category, family, attachment, asset_scope
FROM raw_data.property_type_vocabulary WHERE version = 'property-types-v1'
ON CONFLICT DO NOTHING;

COMMIT;
