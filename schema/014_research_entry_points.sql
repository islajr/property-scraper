-- A small consumer schema and a dictionary for operational objects. No data moves.
BEGIN;
SET LOCAL lock_timeout='5s';
CREATE SCHEMA IF NOT EXISTS research;
COMMENT ON SCHEMA research IS 'Consumer entry points for listing research. One listing is not necessarily one physical property. Existing underlying access controls still apply.';
COMMENT ON SCHEMA raw_data IS 'Scraped listing state, versioned evidence, immutable decision history and operational bookkeeping. Start everyday analysis in research.';

-- Later migrations may append columns. Replaying this introduction must not
-- remove them, just as 011 must not downgrade the room-aware research contract.
DO $entry_points$ BEGIN
 IF to_regclass('research.properties') IS NULL THEN
  EXECUTE $view$
   CREATE VIEW research.properties WITH (security_invoker=true) AS
   SELECT r.*,s.description,s.property_type_raw,s.property_type_raw_source,
    s.bedrooms AS stored_bedrooms,s.bathrooms AS stored_bathrooms,
    s.city,s.neighbourhood,s.neighbourhood_normalised,s.raw_address,
    s.lat,s.lng,s.geocoded,s.first_seen_at,s.last_health_check_at
   FROM raw_data.property_research_current r
   JOIN raw_data.scraped_listings s ON s.id=r.listing_id
  $view$;
 END IF;
 IF to_regclass('research.review_queue') IS NULL THEN
  EXECUTE 'CREATE VIEW research.review_queue WITH (security_invoker=true) AS SELECT * FROM raw_data.property_review_queue';
 END IF;
END $entry_points$;

CREATE OR REPLACE VIEW research.room_count_coverage WITH (security_invoker=true) AS
 SELECT s.source,s.property_category,s.listing_status,m.field,m.status,
  count(*) AS listings,count(m.stored_value) AS populated_values,
  count(*) FILTER(WHERE NOT r.room_counts_current) AS stale_assessments
 FROM raw_data.scraped_listings s
 JOIN raw_data.property_research_current r ON r.listing_id=s.id
 CROSS JOIN LATERAL (VALUES
  ('bedrooms'::text,s.bedrooms,r.bedrooms_status),
  ('bathrooms'::text,s.bathrooms,r.bathrooms_status)) m(field,stored_value,status)
 GROUP BY s.source,s.property_category,s.listing_status,m.field,m.status;

COMMENT ON VIEW research.properties IS 'One row per portal listing, with current interpretations, retained stored room numbers, source text and approximate location. Filter individual field statuses; no cross-portal physical-property deduplication is implied.';
COMMENT ON VIEW research.review_queue IS 'Actionable source, classification, quantity and room-evidence questions. Room flags are review triggers, not confirmed errors.';
COMMENT ON VIEW research.room_count_coverage IS 'Room evidence coverage by portal, category, lifecycle, field and status. Populated unverified numbers remain distinct from supported claims.';
COMMENT ON COLUMN research.properties.stored_bedrooms IS 'Current stored number, preserved even if evidence is unverified or stale. Consult bedrooms_status, room_count_evidence and bedrooms_per_dwelling.';
COMMENT ON COLUMN research.properties.stored_bathrooms IS 'Current stored number, preserved even if evidence is unverified or stale. Consult bathrooms_status, room_count_evidence and bathrooms_per_dwelling.';
COMMENT ON COLUMN research.properties.geocoded IS 'Coordinates came from the neighbourhood/city geocoder; they do not establish an independently verified parcel position.';
COMMENT ON COLUMN research.properties.neighbourhood_normalised IS 'Boolean: the neighbourhood label matched the canonical vocabulary. This is not a second neighbourhood-name column.';

COMMENT ON TABLE raw_data.scraped_listings IS 'Latest saved state of each portal/source listing, unique by source and external_id. Includes source text, stored values and derived interpretations; no guarantee of one physical property per row.';
COMMENT ON TABLE raw_data.listing_history IS 'Lifecycle and pricing events. A pricing-context change is distinct from a comparable price movement; removal is not proof of a completed transaction.';
COMMENT ON TABLE raw_data.geocode_cache IS 'Reusable coordinates for a neighbourhood/city pair, generally an approximate area location rather than a property-specific position.';
COMMENT ON TABLE raw_data.scrape_runs IS 'Per-portal discovery and execution results for operations; not listing-level data-quality certification.';
COMMENT ON TABLE raw_data.rental_pricing_backfills IS 'Audited before/after changes from bounded rental-pricing metadata repairs, including reversal ownership.';
COMMENT ON TABLE raw_data.property_type_versions IS 'Registered versions of the canonical property vocabulary.';
COMMENT ON TABLE raw_data.property_type_vocabulary IS 'Allowed canonical forms and category/family/facet defaults for each vocabulary version; source labels are retained separately.';
COMMENT ON TABLE raw_data.property_classification_history IS 'Immutable before/after classifications with source evidence, run identity and reversal ownership.';
COMMENT ON TABLE raw_data.property_classification_operations IS 'Frozen manifests for classification-only backfills and reversals.';
COMMENT ON TABLE raw_data.property_classification_receipts IS 'Durable per-listing results for classification-only operations; support safe resume without repeating completed work.';
COMMENT ON TABLE raw_data.property_count_assessments IS 'Source-bound quantity extraction snapshots with rule fingerprints and outstanding questions.';
COMMENT ON TABLE raw_data.property_count_observations IS 'Individual count claims, entity/relationship, exact/range bounds, parent/offer references and source evidence.';
COMMENT ON TABLE raw_data.property_count_decisions IS 'Append-only ACCEPT/HOLD/REJECT/REVOKE decisions on count claims; held quantities are not supported counts.';
COMMENT ON TABLE raw_data.property_fact_assessments IS 'Immutable assessments shared by features/offers and room evidence. Use rule_version to distinguish kinds; later rows do not automatically replace unrelated kinds.';
COMMENT ON TABLE raw_data.property_fact_revocations IS 'Append-only retractions of fact assessments, preserving the original evidence.';
COMMENT ON TABLE raw_data.property_unification_runs IS 'Frozen manifests for combined unification, room repairs and their reversals. The manifest kind identifies the operation.';
COMMENT ON TABLE raw_data.property_unification_receipts IS 'Durable per-listing operation results. A completed retry attempts no work; concurrent changes require reconciliation.';

COMMENT ON VIEW raw_data.property_research_current IS 'Supported room-aware property-research-v2 reader. Source freshness is separate from verification of each field; retained unverified values are exposed explicitly.';
COMMENT ON VIEW raw_data.property_review_queue IS 'Outstanding classification, offer, quantity and room questions, including explicit exceptional-count flags and next actions.';
COMMENT ON VIEW raw_data.current_property_counts IS 'Accepted, unrevoked quantity claims whose source evidence still matches the saved listing. Do not combine incompatible asset/unit/availability relationships.';
COMMENT ON VIEW raw_data.current_property_facts IS 'Latest applicable feature/offer assessment for saved source evidence; room assessments do not supersede feature history.';
COMMENT ON VIEW raw_data.current_property_rooms IS 'Latest applicable room assessment for saved source and asset context. An applicable assessment may explicitly retain unverified numbers.';
COMMENT ON VIEW raw_data.property_classification_coverage IS 'Property-type coverage by source and classification state; unresolved cases remain in the population.';
COMMENT ON VIEW raw_data.comparable_rental_prices IS 'Current rental quotes with supported currency, period and price basis. Eligibility does not certify physical-property identity or bedrooms.';
COMMENT ON VIEW raw_data.rental_price_summary IS 'Grouped current comparable rental-price summaries, not reconstructed historical transactions.';
COMMENT ON VIEW raw_data.rental_pricing_coverage IS 'Pricing-context coverage including unresolved rental quote periods and bases.';
COMMIT;
