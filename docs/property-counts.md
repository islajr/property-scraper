# Property counts: contract and operations

Counts describe different things: assets offered, units within a building,
bedrooms per dwelling, and development availability. Never put those quantities
in one unqualified unit_count field or add them together. The accepted review
decisions are recorded in [PR #12](https://github.com/islajr/property-scraper/pull/12).

This guide consolidates the count profiling instructions and storage proposal.
The dated [17 November profile](archive/property-count-profile-2026-11-17.md)
remains an archived baseline, not the current operating manual.

## Storage contract

Migration 009 creates three additive tables and a current-count view. It does
not update scraped_listings or create count values for existing listings.

| Object | Purpose |
| --- | --- |
| property_count_assessments | Listing ID, source hash/row version, rule version, exact extractor fingerprint, run ID, time, and outstanding questions |
| property_count_observations | Quantity, entity, relationship, parent/offer keys, rule, flags, and source evidence |
| property_count_decisions | Append-only ACCEPT, HOLD, REJECT, or REVOKE decisions with run ID, reason, and time |
| current_property_counts | The latest applicable assessment's accepted observations, whose source text still matches the listing |

Entities include BUILDING, DWELLING_UNIT, ROOM, and BEDROOM. UNSPECIFIED_UNIT and
BEDROOM_SHORTHAND remain candidate entities and cannot be accepted as established
counts. Relationships distinguish OFFERED_ASSET, CONTAINED_UNIT,
BEDROOMS_PER_DWELLING, DEVELOPMENT_AVAILABILITY, and UNRESOLVED. Parent and offer
keys are local references within a listing assessment; they are not new property
IDs or proof that a particular unit has been independently identified.
An offer key is also not a certified mapping to the existing price column.
Do not multiply or divide prices by these counts without verifying price basis.

EXACT retains equal bounds; AT_LEAST has no upper bound; RANGE retains bounds.
SQL acceptance checks require a valid positive integer quantity and compatible
entity/relationship. Zero claims, unresolved roles, and invalid bounds can be
retained as held evidence, but cannot pass acceptance. Version 1 does not accept
zero-bedroom claims, compute derived totals, or automatically resolve ranges.

Duplicate compatible source claims become one observation with multiple evidence
items. Source spans retain both the count phrase and surrounding relationship
wording. Assessed time is extraction time, not a fabricated original observation
date. No count is independently physically verified by this pipeline.

## Initial extraction rules

The assessor uses saved primary title/description text, not previous canonical
types or numeric bedroom columns. It builds on the raw count profiler, then
accepts only narrow relationships:

- Explicit bedroom wording adjacent to a dwelling form or an explicit per-unit
  qualifier can establish BEDROOMS_PER_DWELLING.
- A singular block-of-flats or explicit building-contents phrase can establish
  contained dwelling quantities. It does not manufacture a building count of one.
- A numeric quantity with explicit sold/rented/leased/taken-together wording can
  establish an offered bundle, provided the counted entity is established.
- An explicit numeric one in a primary title can establish an individually
  offered asset when it is not an ancillary, layout, portfolio, or availability
  claim. Room counts additionally need clear shared-accommodation context.
- Explicit availability in development/stock context can establish an inventory
  count, kept separate from a fixed-price bundle.

The initial automatic rules hold flagged wording, all offer-alternative cases,
truncated sources, ranges, ambiguous relationships, and mixed/conflicting quantity
parents. They use only early description identity text, not later feature lists
or agent inventories. Per-dwelling bedroom claims above 20 and quantities above
10,000 require review; those are review gates, not definitions of valid property
sizes. Unsupported claims remain intact with their reason and next action.

Having a supported bedroom count does not close a missing offered-quantity
question. Assessments can contain accepted and held observations together.
NO_PATTERN_MATCH means that the current patterns found nothing, not that the
listing necessarily lacks counts or that the missing-evidence work is complete.
Known alternatives and complex building/layout portfolios still need explicit
offer/parent modelling before automatic acceptance. No grammatical singular or
property-type default silently becomes an exact one.

## Inspect before storing

```bash
# Raw literal phrases, context flags, and coverage.
python -m scripts.profile_property_counts \
  --output .local/property-counts/profile.jsonl

# Normalized observations, proposed decisions, and outstanding questions.
python -m scripts.preview_property_counts \
  --output .local/property-counts/assessment.jsonl
```

Both commands enforce read-only repeatable-read access on PostgreSQL, run no
migrations, and make no portal requests. They write private local reports with
checksums and source fingerprints. Detailed listing evidence belongs under the
ignored .local directory. Check a summary/report checksum before pairing them.
Preview decisions are proposed outputs, not applied production values or an
accuracy estimate. These reports are not classification-backfill artifacts and
are marked apply_compatible=false.

The profiler limits titles to 2,000 characters, descriptions to 20,000, and
candidates to 100. The assessor uses the same limits and holds truncated inputs.
Possible source conflicts, shorthand, availability, and alternative-offer hints
are not exhaustive detectors. Reconcile report IDs with the current inventory
before any later correction run.

## Persistence and reversal API

persist_assessment in scraper/property_count_store.py is an internal transactional
API for future bounded rollout/observation callers. It requires the reviewed
source row version, source hash, extractor fingerprint, and a UUID run ID. It
locks the source row, rejects stale source/rules, recomputes the decision from
actual saved evidence, and inserts assessment, observations, and decisions in
the caller's transaction. A retry returns ALREADY_ASSESSED instead of creating
duplicate evidence. The caller must commit or roll back explicitly.

revoke_assessment appends REVOKE decisions only when the latest decisions still
belong to the expected original run. It does not erase history, overwrite newer
review decisions, or cause a retried original assessment to resurrect counts.
Decision insertions serialize on their assessment; SQL rejects update/delete of
stored evidence and decisions.

The current view compares the full title/description source hash with the listing.
Changed evidence hides stale counts until reassessed. Price-only changes do not
invalidate them. New decisions change visibility without deleting original claims.
Manual corrections requiring different normalized fields need new evidence-bearing
observations/assessment rules; a bare ACCEPT cannot bypass unresolved SQL fields.

This PR deliberately has no production apply CLI, background queue, or discovery
writer integration. The API is exercised only against disposable databases here.
A later production caller needs a reviewed bounded selection, a run manifest,
checkpoint/report reconciliation, and explicit operational verification. Merely
deploying the schema does not populate counts or schedule that operation.

## Query examples

```sql
SELECT listing_id, offer_key, quantity_min AS dwellings_offered
FROM raw_data.current_property_counts
WHERE relationship = 'OFFERED_ASSET' AND counted_entity = 'DWELLING_UNIT'
  AND quantity_kind = 'EXACT';

SELECT listing_id, parent_key, quantity_min AS contained_dwellings
FROM raw_data.current_property_counts
WHERE relationship = 'CONTAINED_UNIT' AND counted_entity = 'DWELLING_UNIT'
  AND quantity_kind = 'EXACT';

SELECT listing_id, parent_key, quantity_min AS bedrooms_per_dwelling
FROM raw_data.current_property_counts
WHERE relationship = 'BEDROOMS_PER_DWELLING' AND quantity_kind = 'EXACT';
```

The view already excludes held, rejected, revoked, and stale observations. Do not
sum mutually exclusive offers, mix availability with offered bundles, or join
unidentified parent keys across listings. Research coverage must still include
listings without accepted counts and report their unresolved reasons separately.

## Latest extraction preview and verification

The read-only 17 November 2026 snapshot at 22:41:47 UTC contained 28,955 listings.
The initial rules proposed at least one accepted count in 12,734 listings:
12,701 had supported bedroom-per-dwelling counts, nine had offered-asset counts,
and 74 had contained-unit counts. These groups overlap. 15,991 listings had held
claims, and 5,738 had no current pattern match. No production counts were stored.

The offered-quantity question remains open for 28,946 listings. This is a strict
initial automatic extraction, not evidence that the rest lack counts or require
individual manual inspection. Review recurring wording and missing patterns in
batches. Preview ACCEPT means supported by the proposed rule, not independently
verified property facts or permission to apply the complete report.

All 563 tests passed, including disposable-database migration reruns, source
preservation, idempotency, transaction rollback, stale-source/rule rejection,
freshness, immutable history, SQL acceptance checks, and reversal that respects
newer review decisions. Autocommit callers are rejected. The profiler's corrected
numeric-boundary regression is backported to PR #14, whose 522 tests also passed.

One preview regression caught 12 bedrooms being split into a false one-unit and
two-bedroom interpretation. The fixed boundary and overlap flags prevent that
promotion. The earlier raw unit/building-clue figure of 1,794 is superseded by
1,744 in the refreshed candidate profile. Neither figure is a verified unit count.

Final assessment preview SHA-256:
`e74f544e3038b9036fabc53fd6975cdb4f192a5d6ceaecf151ff7ae05da7ed79`.
Extractor SHA-256:
`d7b5a89835c19bb781f73a6f4dfa01ab13fff910d613b7aa87533e8c53bf34be`.

## Deployment and review

Apply numbered migrations in order before a count-storage caller is deployed.
009 depends on the existing raw_data listings schema, not classification-v2 rules.
Count rule/version changes require fresh previews; preserve historical artifacts.
This implementation builds on the profiler in PR #14, which should land first,
then this branch can be rebased against master. Classification PR #13 is separate.

Before a production rollout, review the proposed observations and relationships,
especially offered/contained quantities, mixed layouts, source conflicts, and
unsupported singular wording. Then prepare the bounded caller and observation
integration. No production migration or count write is performed in this PR.
