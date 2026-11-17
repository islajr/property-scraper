# Property counts: storage design for review

Status: proposed design, informed by the saved-text profiling stage. The user
accepted count semantics, not these table names, columns, or promotion rules.
There is no migration or production persistence in this PR. The
[profile guide](property-count-profiling.md) explains the candidate evidence.

## Recommended shape

Use a separate assessment with child observations rather than adding a single
unit_count column to scraped_listings. An advert can describe buildings, their
contained flats, bedroom layouts, and several price/offer options at once.

| Proposed object | Information it preserves |
| --- | --- |
| Count assessment | Listing identity, source row version, source-text checksum, extraction time, rule version, completeness, and outstanding questions |
| Count observation | Exact/range/lower-bound quantity, counted entity, relationship, parent/offer key, source field and span, original text, context, review state, and flags |
| Observation decision/history | Accepted/rejected/held interpretation, rationale, responsible reviewer or approved rule, input references, run ID, and audit time |

An assessment without observations still records a coverage outcome and a next
action. It does not fabricate a NULL observation, zero assets, or an exact one.
Do not mark a missing pattern as a completed missing-evidence investigation.
Known not-applicable cases need an explicit reviewed decision.

Initial counted entities could be BUILDING, DWELLING_UNIT, ROOM, and BEDROOM.
Candidates can retain UNSPECIFIED_UNIT and BEDROOM_SHORTHAND while their meaning
is unresolved. Candidate relation hints do not become accepted relationships
without an approved interpretation. The initial relationships to review are:

- OFFERED_ASSET: assets included in the particular offer or bundle.
- CONTAINED_UNIT: units within the referenced building or portfolio.
- BEDROOMS_PER_DWELLING: a stated count attached to a dwelling or uniform layout.
- DEVELOPMENT_AVAILABILITY: stock availability rather than the subject of a
  fixed bundle price.

Parent and offer references distinguish one block containing four flats from
four separate flat offers. A room within a BQ is not automatically the main
offered asset. Keep unmatched or unknown relationships reviewable, not silently
promoted to OFFERED_ASSET.

## Integrity and lifecycle rules

- EXACT quantities have equal lower and upper values. AT_LEAST has a lower value
  and no upper value. RANGE keeps ordered bounds; reversed or unclear source
  ranges remain held. Counts of offered assets must be positive.
- Explicit zero bedroom claims require their own reviewed attribute semantics.
  A studio label alone does not establish a zero count. Unknown is not zero.
- Source observations retain their wording and offsets. Repeated title and
  description claims are evidence of one fact where compatible, not counts to sum.
- Mixed layouts remain separate observations. Do not assign their sum to
  bedrooms_per_unit. Derived totals retain explicit inputs and a calculation;
  they never masquerade as source-stated counts.
- Input hashes, row versions, and observation references guard stale applies.
  A current fetch is new evidence and must not rewrite old observation dates,
  property identity, prices, or lifecycle history.
- Decisions are append-only. A re-extraction links to its predecessor; an apply
  can resume with durable receipts and must not duplicate facts after a retry.
  Final uniqueness and supersession keys need a migration-level review.
- A count may be promoted only after entity, relationship, quantity interpretation,
  and parent/offer scope pass an approved rule or review. A regex match alone is
  not acceptance. Preserve conflicting claims until their context is resolved.

## Consumer query examples to review

The following SQL assumes a future current_property_counts view exposing only
the latest applicable decisions. Neither this view nor these columns exist yet.
The view must have a documented freshness/supersession policy before release.

```sql
-- Offered dwelling quantities, excluding building/container and bedroom counts.
SELECT listing_id, offer_key, quantity_min AS dwellings_offered
FROM raw_data.current_property_counts
WHERE review_state = 'ACCEPTED'
  AND relationship = 'OFFERED_ASSET'
  AND counted_entity = 'DWELLING_UNIT'
  AND quantity_kind = 'EXACT';

-- Building contents, kept distinct from the number of buildings offered.
SELECT listing_id, parent_key, quantity_min AS contained_dwellings
FROM raw_data.current_property_counts
WHERE review_state = 'ACCEPTED'
  AND relationship = 'CONTAINED_UNIT'
  AND counted_entity = 'DWELLING_UNIT'
  AND quantity_kind = 'EXACT';
```

Research must not sum mutually exclusive offer options, mix availability with
fixed bundles, or treat one advert as several independent properties. Coverage
queries must include listings without accepted counts, with reasons separated
into missing text, unresolved interpretation, model gaps, and unavailable sources.

## Review before implementation

Confirm the entity/relationship vocabulary and offer/parent references against
the sampled inventory. Settle acceptance rules, representation of uncertainty,
freshness, and aggregation examples. Then build an additive migration, immutable
decision history, extraction preview, and bounded audited apply in a separate PR
against master. Classification PR #13 need not absorb count storage or feature
extraction in order to be reviewed and merged on its own scope.
