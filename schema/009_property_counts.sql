-- Additive count assessments and append-only decisions. No listing updates.
BEGIN;
SET LOCAL lock_timeout='5s';

CREATE TABLE IF NOT EXISTS raw_data.property_count_assessments (
 id BIGSERIAL PRIMARY KEY,
 listing_id BIGINT NOT NULL REFERENCES raw_data.scraped_listings(id),
 rule_version TEXT NOT NULL,
 extractor_sha256 TEXT NOT NULL CHECK (extractor_sha256 ~ '^[0-9a-f]{64}$'),
 source_hash TEXT NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
 source_row_version TEXT NOT NULL CHECK (source_row_version ~ '^[0-9]+$'),
 run_id UUID NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('COUNTS_FOUND','REVIEW_REQUIRED','NO_PATTERN_MATCH')),
 questions JSONB NOT NULL CHECK (jsonb_typeof(questions)='array'),
 assessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(listing_id,rule_version,extractor_sha256,source_hash)
);
CREATE TABLE IF NOT EXISTS raw_data.property_count_observations (
 id BIGSERIAL PRIMARY KEY,
 assessment_id BIGINT NOT NULL REFERENCES raw_data.property_count_assessments(id),
 ordinal INTEGER NOT NULL CHECK (ordinal>=0),
 counted_entity TEXT NOT NULL CHECK (counted_entity IN ('BUILDING','DWELLING_UNIT','ROOM','BEDROOM','BEDROOM_SHORTHAND','UNSPECIFIED_UNIT')),
 quantity_kind TEXT NOT NULL CHECK (quantity_kind IN ('EXACT','RANGE','AT_LEAST')),
 quantity_min NUMERIC NOT NULL CHECK (quantity_min::text NOT IN ('NaN','Infinity','-Infinity') AND quantity_min>=0 AND quantity_min=trunc(quantity_min)),
 quantity_max NUMERIC CHECK (quantity_max::text NOT IN ('NaN','Infinity','-Infinity') AND quantity_max>=0 AND quantity_max=trunc(quantity_max)),
 relationship TEXT NOT NULL CHECK (relationship IN ('OFFERED_ASSET','CONTAINED_UNIT','BEDROOMS_PER_DWELLING','DEVELOPMENT_AVAILABILITY','UNRESOLVED')),
 parent_key TEXT,
 offer_key TEXT,
 evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence)='array' AND jsonb_array_length(evidence)>0),
 review_flags JSONB NOT NULL CHECK (jsonb_typeof(review_flags)='array'),
 rule TEXT NOT NULL,
 UNIQUE(assessment_id,ordinal)
);
CREATE TABLE IF NOT EXISTS raw_data.property_count_decisions (
 id BIGSERIAL PRIMARY KEY,
 observation_id BIGINT NOT NULL REFERENCES raw_data.property_count_observations(id),
 decision TEXT NOT NULL CHECK (decision IN ('ACCEPT','HOLD','REJECT','REVOKE')),
 reason TEXT NOT NULL CHECK (length(trim(reason))>0),
 run_id UUID NOT NULL,
 decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS property_count_decision_latest ON raw_data.property_count_decisions(observation_id,id DESC);
CREATE INDEX IF NOT EXISTS property_count_assessment_latest ON raw_data.property_count_assessments(listing_id,id DESC);

CREATE OR REPLACE FUNCTION raw_data.property_count_source_hash(title TEXT,description TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT encode(sha256(convert_to(length(coalesce(title,''))::text||':'||coalesce(title,'')||
        length(coalesce(description,''))::text||':'||coalesce(description,''),'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION raw_data.property_count_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Count evidence and decisions are append-only'; END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['property_count_assessments','property_count_observations','property_count_decisions'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('raw_data.'||t)::regclass AND tgname='count_immutable') THEN
   EXECUTE format('CREATE TRIGGER count_immutable BEFORE UPDATE OR DELETE ON raw_data.%I FOR EACH ROW EXECUTE FUNCTION raw_data.property_count_immutable()',t);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION raw_data.property_count_validate_decision() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE o raw_data.property_count_observations; BEGIN
 SELECT * INTO STRICT o FROM raw_data.property_count_observations WHERE id=NEW.observation_id;
 -- All decision writers serialize on the assessment without mutating evidence.
 PERFORM 1 FROM raw_data.property_count_assessments WHERE id=o.assessment_id FOR UPDATE;
 -- Allocate order only after serialization: a waiting insertion may already
 -- have consumed its BIGSERIAL default before entering this trigger.
 NEW.id := nextval(pg_get_serial_sequence('raw_data.property_count_decisions','id'));
 IF NEW.decision='ACCEPT' AND (
    o.counted_entity IN ('BEDROOM_SHORTHAND','UNSPECIFIED_UNIT') OR o.relationship='UNRESOLVED' OR
    o.quantity_min<1 OR
    (o.quantity_kind='EXACT' AND o.quantity_max IS DISTINCT FROM o.quantity_min) OR
    (o.quantity_kind='AT_LEAST' AND o.quantity_max IS NOT NULL) OR
    (o.quantity_kind='RANGE' AND (o.quantity_max IS NULL OR o.quantity_max<o.quantity_min)) OR
    (o.relationship='BEDROOMS_PER_DWELLING' AND o.counted_entity<>'BEDROOM') OR
    (o.relationship='OFFERED_ASSET' AND o.counted_entity NOT IN ('BUILDING','DWELLING_UNIT','ROOM')) OR
    (o.relationship='CONTAINED_UNIT' AND o.counted_entity NOT IN ('DWELLING_UNIT','ROOM')) OR
    (o.relationship='DEVELOPMENT_AVAILABILITY' AND o.counted_entity NOT IN ('BUILDING','DWELLING_UNIT')) OR
    (o.relationship='OFFERED_ASSET' AND o.offer_key IS NULL) OR
    (o.relationship IN ('CONTAINED_UNIT','BEDROOMS_PER_DWELLING') AND o.parent_key IS NULL)
 ) THEN RAISE EXCEPTION 'Count observation is not eligible for acceptance'; END IF;
 RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='raw_data.property_count_decisions'::regclass AND tgname='count_decision_validate') THEN
  CREATE TRIGGER count_decision_validate BEFORE INSERT ON raw_data.property_count_decisions
  FOR EACH ROW EXECUTE FUNCTION raw_data.property_count_validate_decision();
 END IF;
END $$;

CREATE OR REPLACE VIEW raw_data.current_property_counts AS
WITH current_assessment AS (
 SELECT DISTINCT ON (a.listing_id) a.*
 FROM raw_data.property_count_assessments a JOIN raw_data.scraped_listings s ON s.id=a.listing_id
 WHERE a.rule_version='property-counts-v1'
   AND a.source_hash=raw_data.property_count_source_hash(s.title,s.description)
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
