-- Corrected room counts reuse fact assessment history; no new physical tables.
BEGIN;
SET LOCAL lock_timeout='5s';
ALTER TABLE raw_data.scraped_listings
 ADD COLUMN IF NOT EXISTS raw_bedrooms TEXT,
 ADD COLUMN IF NOT EXISTS raw_bathrooms TEXT,
 ADD COLUMN IF NOT EXISTS room_metric_sources JSONB NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS room_count_data JSONB NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS room_count_legacy JSONB;

CREATE OR REPLACE FUNCTION raw_data.property_room_source_hash(
 source TEXT,external_id TEXT,title TEXT,description TEXT,raw_type TEXT,
 raw_bedrooms TEXT,raw_bathrooms TEXT,property_type TEXT,asset_scope TEXT,metric_sources JSONB)
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT encode(sha256(convert_to(string_agg(
  CASE WHEN value IS NULL THEN '-1:' ELSE length(value)::text||':'||value END,'' ORDER BY ordinal),'UTF8')),'hex')
 FROM unnest(ARRAY[source,external_id,title,description,raw_type,raw_bedrooms,raw_bathrooms,
  property_type,asset_scope,metric_sources->>'bedrooms',metric_sources->>'bathrooms'])
 WITH ORDINALITY AS inputs(value,ordinal)
$$;

CREATE OR REPLACE VIEW raw_data.current_property_rooms AS
 SELECT DISTINCT ON (a.listing_id) a.* FROM raw_data.property_fact_assessments a
 JOIN raw_data.scraped_listings s ON s.id=a.listing_id
 WHERE a.rule_version='property-rooms-v1' AND a.source_hash=raw_data.property_room_source_hash(
   s.source,s.external_id,s.title,s.description,s.property_type_raw,s.raw_bedrooms,s.raw_bathrooms,
   s.property_type,s.property_asset_scope,s.room_metric_sources)
 AND NOT EXISTS(SELECT 1 FROM raw_data.property_fact_revocations r WHERE r.assessment_id=a.id)
 ORDER BY a.listing_id,a.id DESC;

COMMENT ON COLUMN raw_data.scraped_listings.room_count_data IS
 'Current bedroom/bathroom interpretation: scalar, status, basis, evidence and source fingerprint. Unknown is not zero.';
COMMENT ON COLUMN raw_data.scraped_listings.room_count_legacy IS
 'First pre-repair numeric bedroom/bathroom values. Unverified historical data, retained for provenance.';
COMMENT ON VIEW raw_data.current_property_rooms IS
 'Applicable room-count assessment history; a changed source or asset context invalidates the old assessment.';
COMMIT;
