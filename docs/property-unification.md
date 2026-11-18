# Unified property data: consumer contract and rollout

The supported consumer entry point is `raw_data.property_research_current`,
contract `property-research-v2`. It returns **one row per portal listing**, including
unresolved records. A listing is not proof of a unique physical property; adverts
from different portals may describe the same building.

Room-count quality now includes bedrooms and bathrooms, their evidence, scope and
original legacy values. See [room-count policy and repair](property-counts.md#bedrooms-and-bathrooms-evidence-backed-current-fields).
Unknown bathroom values must not be filled from bedroom quantities.

## What consumers can use

| Field | Meaning |
| --- | --- |
| property_type, property_type_status | A bounded canonical type, or NULL with a reason-bearing unresolved status |
| property_category, property_type_family | Aggregation category and family; neither is legal zoning |
| property_attachment, property_asset_scope, property_land_use | Separate facets; NULL means the evidence did not establish one |
| bedrooms_per_dwelling | Accepted exact bedroom quantity when the accepted layouts agree; NULL for mixed, conflicting or absent evidence |
| legacy_bedrooms, legacy_bathrooms | First pre-repair numbers, retained for comparison; not certified |
| bathrooms_per_dwelling | Supported exact bathroom quantity for a dwelling; toilets and ensuite wording do not supply a number |
| bedrooms_as_advertised, bathrooms_as_advertised | Stored numbers including retained UNVERIFIED values; use status and evidence to decide whether to include them |
| bedrooms_status, bathrooms_status | Field-specific quality marker, including ambiguity, mixed layouts and missing evidence |
| room_count_evidence, room_counts_current | Source-bound room claims, warnings and freshness |
| count_claims | All current extracted/reviewed quantity claims with ACCEPT/HOLD/REJECT/REVOKE state, evidence and observation ID; held quantities are not certified counts |
| counts | Accepted quantities with entity, relationship, bounds, parent, offer and evidence; never one unqualified unit_count |
| features | Advertiser claims, including explicit negatives and private/shared/unknown scope; absence means unknown |
| offers, multiple_offers | Source-bound reviewed offer options and a flag that the headline price cannot represent every option |
| review_questions, count_questions | Specific evidence gaps and follow-up actions |
| contract_current | Current classification version plus applicable count, feature and room assessments for the saved source |
| single_unit_price_candidate | An initial eligibility filter for a classified individual unit with a supported NGN quote; consumers must still match purpose, period, location and comparables |

Use the status and freshness fields explicitly:

```sql
SELECT listing_id, property_type, bedrooms_per_dwelling, counts, features
FROM raw_data.property_research_current
WHERE contract_current AND property_type_status='CLASSIFIED';

SELECT property_type_status, count(*)
FROM raw_data.property_research_current
GROUP BY property_type_status;

SELECT listing_id, url, priority, next_action, review_questions, count_questions
FROM raw_data.property_review_queue
ORDER BY priority, listing_id;
```

Keep unresolved records in coverage denominators. Do not read NULL as zero, turn
an unknown unit quantity into one, add contained units to offered buildings,
assume rental periods, or divide a price by a count without establishing its
basis. A feature such as cinema or home office does not add a bedroom.

The view exposes accepted source claims, not independently inspected property
facts. It deliberately retains broad types such as HOUSE when no narrower form
is established. Future health checks can improve evidence; they cannot establish
facts that the advert does not disclose. Text-only rules do not inspect images.

Existing bedroom/bathroom numbers are preserved during historical assessment.
UNVERIFIED is an evidence-quality marker, not a claim that a number is wrong.
The stored/as-advertised fields retain these numbers so consumers can decide
whether to include them. Supported per-dwelling fields require KNOWN status.
Corrections of existing numbers require a fresh, unambiguous labelled primary
metric; missing or conflicting observations never clear a stored number.
Room freshness and `contract_current` describe assessment applicability, not
verification of each number. Inspect the individual room statuses explicitly.

## Reviewed examples

The user's original CSV is retained unchanged in
[the review archive](archive/property-type-review-2026-11-14.csv).
Its notes are implemented in `scraper/property_reviews.json`; the old literal
PENDING cells are preserved as historical input, not rewritten approval records.
Each interpreted decision identifies its review case and matches the portal ID
and exact raw label/title/description fingerprint. Changed source evidence stops
that decision from applying. Rules and registry bytes enter preview fingerprints.

All 31 reviewed examples have a primary type. Specific layout/count decisions
remain separate: R15 retains five flats comprising two 2-bedroom layouts and
three 1-bedroom layouts. This does not establish that one advertised price buys
all five flats. R07's five units do not become a certified bundle automatically.

Four cases retain explicit actions:

| Case | Action |
| --- | --- |
| R21 | Confirm bedrooms per unit and separate individual-unit and all-unit offers |
| R26 | Reconcile saved studio/mini-flat prices of 7m/13.5m with the review's 8m/14m; confirm period |
| R28 | Confirm whole-hostel ownership versus investment interest, and which of three offers applies |
| R31 | Confirm bare versus cultivated land and parcel size; saved text advertises acre/hectare alternatives |

The hostel is a supported commercial accommodation asset type; category does
not establish the ownership interest or whole-building scope. Agricultural land
use does not establish that land is bare or that a particular parcel area is known.
The gas-plant type does not certify the size or ownership boundary of the site.

## Rollout

Changes to production follow the repository's PR-to-master process. Merge this
integration before deploying it. Apply SQL migrations in filename order, including
008 (v2 vocabulary), 009 (counts), 010 (v3 vocabulary/facts/operations) and 011
(research views), before running the updated writers. Migration installation alone
does not reclassify existing records.

Take a private source backup and generate a fresh preview using the merged code:

```bash
python -m scripts.unify_properties preview \
  --output .local/property-types/unification.jsonl
```

This command uses a server-enforced read-only repeatable snapshot. Inspect its
summary, coverage, 31 review cases, source conflicts and unusual transitions.
Artifacts include the database fingerprint, exact rule fingerprints and a
checksum. They contain listing evidence and belong in ignored private storage.
Do not regenerate a report in place once an apply run has started.

Use a new UUID per operation and selection. A four-record canary is a separate
operation from the remaining full inventory:

```bash
# Dry run; --apply is intentionally absent.
python -m scripts.unify_properties apply \
  --report .local/property-types/unification.jsonl --run-id <uuid> \
  --ids 8,69,22974,25268 --max-records 4

# Apply only after checking the dry run.
python -m scripts.unify_properties apply \
  --report .local/property-types/unification.jsonl --run-id <same-uuid> \
  --ids 8,69,22974,25268 --max-records 4 --apply
```

Inspect the canary, then generate a fresh full preview and use a different run
UUID with no `--ids`. Repeat the bounded apply command until `remaining` is zero.
The default batch is 100 rows, maximum 500. Each batch locks rows in ID order and
checks portal identity, row version, prior classification and recomputed output.
All writes and durable receipts share a transaction. Interruptions can be retried
with exactly the same run UUID/report/selection. Changed rows receive
CONCURRENT_CHANGE and require a new preview/run rather than overwriting new data.
Retry lock/timeouts on the same run. There are no automatic portal requests.

Discovery, relisting and identity-matched health checks assess new saved evidence
in their existing transactions. Pricing-only repair paths do not invent source
observations. Repeating unchanged evidence does not duplicate assessments or
resurrect revoked counts. Old DTO/checkpoint classifications are recomputed when
the classifier version differs.

## Reversal and verification

```bash
# Default is a read-only eligibility check.
python -m scripts.unify_properties reverse \
  --original-run-id <apply-uuid> --run-id <new-reversal-uuid>
# Add --apply only after inspecting eligibility; repeat bounded batches as needed.
```

Reversal restores only unchanged latest classifications written by that run,
appends count revocations and retracts the run's latest feature assessments. Any
later listing edit or later count/feature review prevents automatic reversal.
Previously existing assessments are not owned by the run and are protected.
A reversed apply run cannot be resumed. Keep the backup for cases requiring
manual recovery. Schema objects remain installed and audit history remains intact.

Before handing data to consumers, verify:

- Preview and receipt totals reconcile, including all changed/missing records.
- Every listing has a current contract assessment or an explicit queue action.
- Canonical vocabulary and status constraints validate; LEGACY_UNREVIEWED is gone
  after all unchanged historical rows have been processed.
- The 31 review cases retain their decisions, unit mixes and follow-up actions.
- Prices, descriptions, identity and lifecycle fields were not rewritten by the
  backfill; compare the private before/after baseline and account for scraper edits.
- A repeated completed apply attempts zero rows, and source edits hide stale
  counts and features until the next assessment.

Other projects must adopt this view and its status/period filters themselves;
this repository cannot silently update external analyses or their cached exports.
The review queue is the continuing backlog, ordered by freshness, asset identity,
offer ambiguity and then count questions. Count gaps are not all equally urgent:
a missing total offered quantity can coexist with usable bedroom/type evidence.
