-- Versioned vocabulary and source-bound research facts; rerunnable and additive.
BEGIN;
SET LOCAL lock_timeout='5s';
INSERT INTO raw_data.property_type_versions VALUES ('property-types-v3') ON CONFLICT DO NOTHING;
INSERT INTO raw_data.property_type_vocabulary(version,code,category,family,attachment,asset_scope)
SELECT 'property-types-v3',code,category,family,attachment,asset_scope
FROM raw_data.property_type_vocabulary WHERE version='property-types-v2' ON CONFLICT DO NOTHING;
INSERT INTO raw_data.property_type_vocabulary(version,code,category,family) VALUES
 ('property-types-v3','HOSTEL','COMMERCIAL','HOSTEL'),
 ('property-types-v3','GAS_PLANT','COMMERCIAL','GAS_PLANT'),
 ('property-types-v3','EVENT_VENUE','COMMERCIAL','EVENT_VENUE') ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION raw_data.property_evidence_hash(title TEXT,description TEXT,raw_type TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT encode(sha256(convert_to(length(coalesce(title,''))::text||':'||coalesce(title,'')||
   length(coalesce(description,''))::text||':'||coalesce(description,'')||
   CASE WHEN raw_type IS NULL THEN '' ELSE length(raw_type)::text||':'||raw_type END,'UTF8')),'hex')
$$;
CREATE TABLE IF NOT EXISTS raw_data.property_fact_assessments (
 id BIGSERIAL PRIMARY KEY,
 listing_id BIGINT NOT NULL REFERENCES raw_data.scraped_listings(id),
 source_hash TEXT NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
 extractor_sha256 TEXT NOT NULL CHECK(extractor_sha256 ~ '^[0-9a-f]{64}$'),
 rule_version TEXT NOT NULL,
 run_id UUID NOT NULL,
 facts JSONB NOT NULL CHECK(jsonb_typeof(facts)='object'),
 assessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(listing_id,source_hash,extractor_sha256)
);
CREATE INDEX IF NOT EXISTS property_fact_latest ON raw_data.property_fact_assessments(listing_id,id DESC);
CREATE TABLE IF NOT EXISTS raw_data.property_unification_runs (
 run_id UUID PRIMARY KEY,
 manifest JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS raw_data.property_unification_receipts (
 run_id UUID NOT NULL REFERENCES raw_data.property_unification_runs(run_id),
 listing_id BIGINT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('APPLIED','REVERSED','CONCURRENT_CHANGE','MISSING')),
 completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(run_id,listing_id)
);
CREATE TABLE IF NOT EXISTS raw_data.property_fact_revocations (
 assessment_id BIGINT PRIMARY KEY REFERENCES raw_data.property_fact_assessments(id),
 run_id UUID NOT NULL,
 reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='raw_data.property_fact_assessments'::regclass AND tgname='fact_immutable') THEN
  CREATE TRIGGER fact_immutable BEFORE UPDATE OR DELETE ON raw_data.property_fact_assessments
  FOR EACH ROW EXECUTE FUNCTION raw_data.property_count_immutable();
 END IF;
END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['property_unification_runs','property_unification_receipts','property_fact_revocations'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('raw_data.'||t)::regclass AND tgname='unification_immutable') THEN
   EXECUTE format('CREATE TRIGGER unification_immutable BEFORE UPDATE OR DELETE ON raw_data.%I FOR EACH ROW EXECUTE FUNCTION raw_data.property_count_immutable()',t);
  END IF;
 END LOOP;
END $$;
CREATE OR REPLACE VIEW raw_data.current_property_facts AS
 WITH latest AS (
 SELECT DISTINCT ON (a.listing_id) a.* FROM raw_data.property_fact_assessments a
 JOIN raw_data.scraped_listings s ON s.id=a.listing_id
 WHERE a.source_hash=raw_data.property_evidence_hash(s.title,s.description,s.property_type_raw)
 ORDER BY a.listing_id,a.id DESC
 ) SELECT a.* FROM latest a WHERE NOT EXISTS (
   SELECT 1 FROM raw_data.property_fact_revocations r WHERE r.assessment_id=a.id);
CREATE OR REPLACE VIEW raw_data.current_property_counts AS
WITH current_assessment AS (
 SELECT DISTINCT ON (a.listing_id) a.*
 FROM raw_data.property_count_assessments a JOIN raw_data.scraped_listings s ON s.id=a.listing_id
 WHERE a.rule_version='property-counts-v2'
   AND a.source_hash=raw_data.property_evidence_hash(s.title,s.description,s.property_type_raw)
 ORDER BY a.listing_id,a.id DESC
), latest_decision AS (
 SELECT DISTINCT ON (observation_id) * FROM raw_data.property_count_decisions
 ORDER BY observation_id,id DESC
)
SELECT a.listing_id,a.id AS assessment_id,o.id AS observation_id,a.rule_version,
 a.source_hash,a.assessed_at,o.counted_entity,o.relationship,o.quantity_kind,
 o.quantity_min,o.quantity_max,o.parent_key,o.offer_key,o.evidence,
 d.decision AS review_state,d.id AS decision_id,d.decided_at
FROM current_assessment a JOIN raw_data.property_count_observations o ON o.assessment_id=a.id
JOIN latest_decision d ON d.observation_id=o.id WHERE d.decision='ACCEPT';

COMMIT;
