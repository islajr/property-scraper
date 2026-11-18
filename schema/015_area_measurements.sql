-- Advertised land/floor areas reuse existing fact history; no new physical tables.
BEGIN;
SET LOCAL lock_timeout='5s';
ALTER TABLE raw_data.scraped_listings
 ADD COLUMN IF NOT EXISTS raw_floor_area TEXT,
 ADD COLUMN IF NOT EXISTS raw_area_fields JSONB NOT NULL DEFAULT '[]',
 ADD COLUMN IF NOT EXISTS land_area_sqm NUMERIC(18,2),
 ADD COLUMN IF NOT EXISTS area_data JSONB NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS area_legacy JSONB;

CREATE OR REPLACE FUNCTION raw_data.property_area_source_hash(row_data JSONB)
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT encode(sha256(convert_to(string_agg(
  CASE WHEN value IS NULL THEN '-1:' ELSE length(value)::text||':'||value END,'' ORDER BY group_no,item_no,field_no),'UTF8')),'hex')
 FROM (
  SELECT 0 AS group_no,0::bigint AS item_no,ordinal AS field_no,row_data->>key AS value
  FROM unnest(ARRAY['source','external_id','title','description','property_type_raw','property_type',
    'property_category','property_type_family','property_asset_scope','raw_floor_area']) WITH ORDINALITY keys(key,ordinal)
  UNION ALL
  SELECT 1,item_no,ordinal,item->>key
  FROM jsonb_array_elements(coalesce(row_data->'raw_area_fields','[]'::jsonb)) WITH ORDINALITY items(item,item_no)
  CROSS JOIN unnest(ARRAY['role','label','value','source']) WITH ORDINALITY keys(key,ordinal)
 ) inputs
$$;

CREATE OR REPLACE VIEW raw_data.current_property_areas WITH (security_invoker=true) AS
 SELECT DISTINCT ON (a.listing_id) a.*
 FROM raw_data.property_fact_assessments a JOIN raw_data.scraped_listings s ON s.id=a.listing_id
 WHERE a.rule_version='property-areas-v1'
 AND a.source_hash=raw_data.property_area_source_hash(to_jsonb(s))
 AND a.facts->'assessment'=s.area_data
 AND (s.area_data->'floor_area_sqm'->>'stored_value')::numeric IS NOT DISTINCT FROM s.floor_area_sqm
 AND (s.area_data->'land_area_sqm'->>'stored_value')::numeric IS NOT DISTINCT FROM s.land_area_sqm
 AND NOT EXISTS(SELECT 1 FROM raw_data.property_fact_revocations v WHERE v.assessment_id=a.id)
 ORDER BY a.listing_id,a.id DESC;

-- Append once to the existing consumer prefix. Preserve room and location columns,
-- including any future extensions if this migration is replayed.
DO $areas$ DECLARE previous_definition TEXT; BEGIN
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns
   WHERE table_schema='research' AND table_name='properties' AND column_name='areas_current') THEN
  SELECT rtrim(pg_get_viewdef('research.properties'::regclass,true),E';\n ') INTO previous_definition;
  EXECUTE 'CREATE OR REPLACE VIEW research.properties WITH (security_invoker=true) AS SELECT p.*,
    s.floor_area_sqm AS stored_floor_area_sqm,s.floor_area_source,s.land_area_sqm AS stored_land_area_sqm,
    CASE WHEN a.id IS NOT NULL AND s.area_data->''floor_area_sqm''->>''status''=''KNOWN''
      THEN s.floor_area_sqm END AS supported_floor_area_sqm,
    CASE WHEN a.id IS NOT NULL AND s.area_data->''land_area_sqm''->>''status''=''KNOWN''
      THEN s.land_area_sqm END AS supported_land_area_sqm,
    CASE WHEN a.id IS NULL THEN ''STALE_OR_UNASSESSED'' ELSE s.area_data->''floor_area_sqm''->>''status'' END AS floor_area_status,
    CASE WHEN a.id IS NULL THEN ''STALE_OR_UNASSESSED'' ELSE s.area_data->''land_area_sqm''->>''status'' END AS land_area_status,
    a.id IS NOT NULL AS areas_current,
    CASE WHEN a.id IS NOT NULL THEN s.area_data ELSE ''{}''::jsonb END AS area_evidence
    FROM ('||previous_definition||') p JOIN raw_data.scraped_listings s ON s.id=p.listing_id
    LEFT JOIN raw_data.current_property_areas a ON a.listing_id=s.id';
 END IF;
END $areas$;

CREATE OR REPLACE VIEW research.area_measurements WITH (security_invoker=true) AS
 SELECT s.id AS listing_id,s.source,s.listing_status,a.id AS assessment_id,
  claim_no AS claim_number,claim->>'role' AS area_role,claim->>'basis' AS area_basis,
  (claim->>'sqm')::numeric AS sqm,(claim->>'usable')::boolean AS claim_usable,
  claim->>'precision' AS precision,claim AS evidence
 FROM raw_data.scraped_listings s JOIN raw_data.current_property_areas a ON a.listing_id=s.id
 CROSS JOIN LATERAL jsonb_array_elements(s.area_data->'claims') WITH ORDINALITY claims(claim,claim_no);

COMMENT ON COLUMN raw_data.scraped_listings.raw_floor_area IS 'Explicit floor-area field only. Generic portal Size widgets belong in raw_area_fields with their actual role/provenance.';
COMMENT ON COLUMN raw_data.scraped_listings.raw_area_fields IS 'Original labelled area widgets, with role and primary/legacy source scope. Generic Size does not establish floor area.';
COMMENT ON COLUMN raw_data.scraped_listings.land_area_sqm IS 'Stored advertised land area in sqm. Consult research.properties.land_area_status and area_evidence before use.';
COMMENT ON COLUMN raw_data.scraped_listings.area_data IS 'Source-bound area claims, exact unit conversions, roles, basis, precision, review reasons and stored-value decisions. Not a physical measurement.';
COMMENT ON COLUMN raw_data.scraped_listings.area_legacy IS 'First stored floor/land values and floor source before assessment; retained even when unsupported.';
COMMENT ON VIEW raw_data.current_property_areas IS 'Latest unrevoked area assessment matching both current source evidence and current stored area values. Independent of room and feature histories.';
COMMENT ON VIEW research.area_measurements IS 'One row per current advertised area claim, including held claims. claim_usable is not final field acceptance: consult research.properties field status to detect conflicting claims.';
COMMENT ON COLUMN research.properties.supported_floor_area_sqm IS 'Current supported floor area only, in sqm. area_evidence retains scope/basis and approximate wording. Old unsupported values remain in stored_floor_area_sqm.';
COMMENT ON COLUMN research.properties.supported_land_area_sqm IS 'Current supported land area only, in sqm. Per-unit, shared-site, range, conflicting and unclear claims remain in evidence.';
COMMIT;
