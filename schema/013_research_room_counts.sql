-- Extend the research contract with source-bound bedroom/bathroom decisions.
BEGIN;
CREATE OR REPLACE VIEW raw_data.property_research_current AS
WITH rooms AS (
 SELECT s.id AS listing_id,s.room_count_data AS data,
 coalesce(p.id IS NOT NULL AND s.room_count_data=p.facts->'assessment'
  AND s.bedrooms IS NOT DISTINCT FROM (s.room_count_data->'bedrooms'->>'stored_value')::integer
  AND s.bathrooms IS NOT DISTINCT FROM (s.room_count_data->'bathrooms'->>'stored_value')::integer,false) AS current
 FROM raw_data.scraped_listings s LEFT JOIN raw_data.current_property_rooms p ON p.listing_id=s.id
), counts AS (
 SELECT listing_id,jsonb_agg(jsonb_build_object(
   'entity',counted_entity,'relationship',relationship,'kind',quantity_kind,
   'minimum',quantity_min,'maximum',quantity_max,'parent_key',parent_key,
   'offer_key',offer_key,'evidence',evidence) ORDER BY observation_id) AS observations,
   CASE WHEN count(DISTINCT quantity_min) FILTER(WHERE relationship='BEDROOMS_PER_DWELLING')=1
     AND bool_and(quantity_kind='EXACT') FILTER(WHERE relationship='BEDROOMS_PER_DWELLING')
     THEN min(quantity_min) FILTER(WHERE relationship='BEDROOMS_PER_DWELLING') END AS bedrooms_per_dwelling,
   bool_or(relationship='OFFERED_ASSET' AND (quantity_kind<>'EXACT' OR quantity_min<>1)) AS multi_asset_offer
 FROM raw_data.current_property_counts GROUP BY listing_id
), assessment AS (
 SELECT DISTINCT ON (a.listing_id) a.* FROM raw_data.property_count_assessments a
 JOIN raw_data.scraped_listings s ON s.id=a.listing_id
 WHERE a.rule_version='property-counts-v2'
 AND a.source_hash=raw_data.property_evidence_hash(s.title,s.description,s.property_type_raw)
 ORDER BY a.listing_id,a.id DESC
), latest_decision AS (
 SELECT DISTINCT ON (observation_id) * FROM raw_data.property_count_decisions
 ORDER BY observation_id,id DESC
), claims AS (
 SELECT a.listing_id,jsonb_agg(jsonb_build_object(
   'observation_id',o.id,'entity',o.counted_entity,'relationship',o.relationship,
   'kind',o.quantity_kind,'minimum',o.quantity_min,'maximum',o.quantity_max,
   'parent_key',o.parent_key,'offer_key',o.offer_key,'evidence',o.evidence,
   'review_state',d.decision,'rule',o.rule,'review_flags',o.review_flags)
   ORDER BY o.ordinal) AS observations
 FROM assessment a JOIN raw_data.property_count_observations o ON o.assessment_id=a.id
 JOIN latest_decision d ON d.observation_id=o.id GROUP BY a.listing_id
)
SELECT s.id AS listing_id,s.source,s.external_id,s.url,s.title,s.listing_status,
 'property-research-v2'::text AS contract_version,
 s.property_type,s.property_type_status,s.property_type_version,s.property_category,
 s.property_type_family,s.property_attachment,s.property_asset_scope,s.property_land_use,
 s.property_type_evidence,
 CASE WHEN rooms.current THEN CASE WHEN rooms.data->'bedrooms'->>'status'='KNOWN'
  AND rooms.data->'bedrooms'->>'basis'='PER_DWELLING' THEN (rooms.data->'bedrooms'->>'value')::numeric END
  ELSE NULL END AS bedrooms_per_dwelling,
 CASE WHEN s.room_count_legacy IS NOT NULL THEN (s.room_count_legacy->>'bedrooms')::smallint ELSE s.bedrooms END AS legacy_bedrooms,
 coalesce(c.observations,'[]'::jsonb) AS counts,
 a.state AS count_state,coalesce(a.questions,'[]'::jsonb) AS count_questions,
 f.facts->'features' AS features,f.facts->'offers' AS offers,
 f.facts->'questions' AS review_questions,
 coalesce((f.facts->>'multiple_offers')::boolean,false) AS multiple_offers,
 s.price_type,s.price_kobo,s.price_currency,s.price_period,s.price_period_count,
 s.price_period_status,s.price_basis,
 coalesce((f.id IS NOT NULL AND a.id IS NOT NULL AND s.property_type_version='property-types-v3' AND rooms.current),false) AS contract_current,
 coalesce((f.id IS NOT NULL AND a.id IS NOT NULL AND s.property_type_version='property-types-v3' AND rooms.current AND NOT coalesce((f.facts->>'multiple_offers')::boolean,false)
   AND NOT coalesce(c.multi_asset_offer,false)
   AND NOT coalesce(a.questions @> '[{"reason":"asset_quantity_relationship_unestablished"}]'::jsonb,false)
   AND s.property_type_status='CLASSIFIED' AND s.property_asset_scope='UNIT'
   AND s.price_kobo>0 AND s.price_currency='NGN' AND s.price_basis='PROPERTY'
   AND (s.price_type='FOR_SALE' OR s.price_period_status='KNOWN')),false) AS single_unit_price_candidate,
 f.assessed_at AS facts_assessed_at,a.assessed_at AS counts_assessed_at,
 s.last_seen_at,coalesce(claims.observations,'[]'::jsonb) AS count_claims,
 CASE WHEN rooms.current AND rooms.data->'bathrooms'->>'status'='KNOWN'
  AND rooms.data->'bathrooms'->>'basis'='PER_DWELLING' THEN (rooms.data->'bathrooms'->>'value')::numeric END AS bathrooms_per_dwelling,
 CASE WHEN s.room_count_legacy IS NOT NULL THEN (s.room_count_legacy->>'bathrooms')::smallint ELSE s.bathrooms END AS legacy_bathrooms,
 CASE WHEN rooms.current THEN rooms.data->'bedrooms'->>'status' ELSE 'PENDING' END AS bedrooms_status,
 CASE WHEN rooms.current THEN rooms.data->'bathrooms'->>'status' ELSE 'PENDING' END AS bathrooms_status,
 rooms.data->'bedrooms'->>'basis' AS bedrooms_basis,rooms.data->'bathrooms'->>'basis' AS bathrooms_basis,
 rooms.data AS room_count_evidence,rooms.current AS room_counts_current,
 CASE WHEN rooms.current THEN s.bedrooms END AS bedrooms_as_advertised,
 CASE WHEN rooms.current THEN s.bathrooms END AS bathrooms_as_advertised
FROM raw_data.scraped_listings s LEFT JOIN counts c ON c.listing_id=s.id
LEFT JOIN rooms ON rooms.listing_id=s.id
LEFT JOIN assessment a ON a.listing_id=s.id
LEFT JOIN claims ON claims.listing_id=s.id
LEFT JOIN raw_data.current_property_facts f ON f.listing_id=s.id;

CREATE OR REPLACE VIEW raw_data.property_review_queue AS
SELECT listing_id,source,external_id,url,property_type,property_type_status,
 CASE WHEN NOT contract_current THEN 0 WHEN property_type_status<>'CLASSIFIED' THEN 1
      WHEN multiple_offers THEN 2 WHEN jsonb_array_length(coalesce(review_questions,'[]'::jsonb))>0 THEN 3
      ELSE 4 END AS priority,
 CASE WHEN NOT contract_current THEN 'Refresh assessment using current rules and saved source.'
      WHEN property_type_status='AMBIGUOUS' THEN 'Review conflicting asset claims; verify the primary offered asset on the portal.'
      WHEN property_type_status='UNSUPPORTED' THEN 'Review the source label for a vocabulary addition or supported alias.'
      WHEN property_type_status<>'CLASSIFIED' THEN 'Revisit the detail page; inspect breadcrumb, description and images for asset identity.'
      WHEN multiple_offers THEN 'Separate the offers; confirm each price, period, asset and ownership basis.'
      ELSE 'Review the attached count and source questions; record evidence before accepting a quantity.' END AS next_action,
 review_questions,count_questions,count_claims,bedrooms_status,bathrooms_status,room_count_evidence
FROM raw_data.property_research_current
WHERE NOT contract_current OR property_type_status<>'CLASSIFIED' OR multiple_offers
 OR jsonb_array_length(coalesce(review_questions,'[]'::jsonb))>0
 OR jsonb_array_length(count_questions)>0
 OR bedrooms_status NOT IN ('KNOWN','NOT_APPLICABLE') OR bathrooms_status NOT IN ('KNOWN','NOT_APPLICABLE');
COMMIT;
