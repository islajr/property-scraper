# Property counts: contract and operations

Counts describe different things: assets offered, units within a building,
bedrooms per dwelling, and development availability. Never put those quantities
in one unqualified unit_count field or add them together. The reviewed source notes are retained in the
[review archive](archive/property-type-review-2026-11-14.csv).

This guide consolidates the count profiling instructions and storage proposal.
The dated [17 November profile](archive/property-count-profile-2026-11-17.md)
remains an archived baseline, not the current operating manual.

The current `property-counts-v2` assessor also uses source-bound review decisions
and hashes the raw type alongside title/description. Migration 010 updates the
current-count view accordingly; v1 observations remain immutable history.
Discovery integration and bounded apply/reversal are documented in the
[unified operations guide](property-unification.md).

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
  qualifier can establish BEDROOMS_PER_DWELLING. Explicit detached, semi-detached
  and terraced modifiers between bedroom quantity and dwelling form are supported.
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
API used by bounded rollout and observation callers. It requires the reviewed
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

The v2 current view compares the raw label/title/description source hash with the listing.
Changed evidence hides stale counts until reassessed. Price-only changes do not
invalidate them. New decisions change visibility without deleting original claims.
Manual corrections requiring different normalized fields need new evidence-bearing
observations/assessment rules; a bare ACCEPT cannot bypass unresolved SQL fields.

The unified runner supplies frozen previews, bounded batches, manifests and durable
receipts. Discovery and primary health checks also populate assessments. See the
[operations guide](property-unification.md). Installing schema objects alone does
not populate historic counts or complete a rollout.

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

## Deployment and verification

Apply numbered migrations in order before deploying callers. Migration 010
registers v2 count freshness based on the raw type as well as title/description;
v1 observations remain immutable history. Rule changes require fresh previews.
The current production preview and rollout status are recorded separately; the
[17 November profile](archive/property-count-profile-2026-11-17.md) is a historical
baseline, not a claim that the database has been populated.

Tests cover source/rule guards, insertion and resume, count entity/relationship
acceptance, immutable audit evidence, source freshness, concurrent decisions,
reversal ownership and batch failures. The unified runner also verifies SQL
pagination so batches larger than 100 observations retain every returned ID and
initial decision. No test uses production.

## Bedrooms and bathrooms: evidence-backed current fields

Room quality is part of `property-research-v2`. The original numeric columns had
two problems: some portal parsers read the same first widget for both fields,
and old observations were never refreshed on updates. Some numbers were also
placeholders or combined text, such as 1234 bedrooms on a land advert.

The repaired writer reads separately identified primary metrics, saves the raw
strings and their label/icon provenance, and updates both numbers in the same
transaction as their immutable evidence. It also uses explicit saved text and
source-bound reviews where they establish the quantity. Toilets, ensuite wording,
room capacity, BQ accommodation and bedrooms do not manufacture bathroom totals.
Source conflicts stay unresolved; mixed layouts retain their component claims.

Primary labels are still advertiser claims. If a residential per-dwelling pair
contains a count of at least ten that exceeds five times the other count, the
larger candidate requires review rather than an automatic fill or correction.
The explicit candidate and `UNUSUAL_PRIMARY_ROOM_RATIO` flag remain visible;
existing numbers are preserved. This threshold prompts verification, not a
conclusion that the advert is false. Likewise, a title describing different
bedroom layouts cannot establish that a single bathroom widget applies to each
dwelling. Bathroom totals remain held unless the source explicitly qualifies
the number for each unit. Never divide an aggregate widget by the unit count.

Use these fields in `raw_data.property_research_current`:

- `bedrooms_per_dwelling` and `bathrooms_per_dwelling`: supported exact quantities
  whose basis is an individual dwelling. A whole building or a shared room needs
  separate context; a count attached to that advert is not automatically per flat.
- `bedrooms_as_advertised` and `bathrooms_as_advertised`: stored scalar numbers,
  including retained unverified values. Read their statuses alongside them.
  `bedrooms_basis`/`bathrooms_basis` describe the extracted supporting claims,
  not a certified basis for an unverified stored number.
- `bedrooms_status` and `bathrooms_status`: KNOWN, UNKNOWN, AMBIGUOUS,
  MIXED_LAYOUT, REVIEW_REQUIRED, UNVERIFIED or NOT_APPLICABLE. UNVERIFIED means an
  existing number was retained without sufficient consistent supporting evidence.
  PENDING means the saved source
  needs reassessment. KNOWN means supported as advertised, not physically verified.
- `room_count_evidence`: all contributing claims, held inputs, warnings and next
  actions. `room_counts_current` checks that source, interpretation, audit and
  saved numeric values still agree. The v2 `contract_current` includes this check.
- `legacy_bedrooms` and `legacy_bathrooms`: the first pre-repair values, kept for
  comparison. They do not become verified because they look plausible.

The historical backfill preserves every existing non-null number in the main
`scraped_listings.bedrooms` and `.bathrooms` columns. A suspected parser defect
is not proof that a particular number is wrong. Missing numbers may be filled
from explicit supported evidence; existing numbers are corrected only after a
fresh, unambiguous labelled primary metric supports the replacement. An omitted,
malformed or conflicting field never clears an existing number. This applies to
future discovery, health checks and bounded recovery as well as the backfill.

Original numbers are retained in `room_count_legacy`, and each
assessment has a before/after record in `property_fact_assessments` under
rule `property-rooms-v1`. This adds no physical history tables. New listings have
no invented historical values.

Each field's evidence records `value` (the extracted supported candidate, if any),
`stored_value`, `evidence_status`, `storage_action`, warnings and a next action.
An unverified stored value can differ from a supported text candidate: that is a
comparison to investigate, not permission to overwrite it. `room_counts_current`
means this assessment matches the current saved source and numbers; it does not
mean the numbers are verified. Consumers may retain unverified values or filter
them explicitly. The per-dwelling fields expose only supported KNOWN claims.

### Repair and rollout

Install migration 012 before new writers. Migration 013 publishes the v2 reader.
For a controlled cutover, install 012, complete and verify the bounded room repair,
then publish 013 and resume the updated writers. Retain the source backup and
reviewed artifacts. A pre-migration preview is informational and cannot be applied.

```bash
python -m scripts.repair_room_counts preview --output .local/room-counts/repair.jsonl
# Inspect coverage, status transitions, changed values and evidence first.
python -m scripts.repair_room_counts apply --report .local/room-counts/repair.jsonl \
  --run-id <uuid> --ids <reviewed-canary-ids> --max-records 25
# Adding --apply enables writes. Use a fresh preview/new run for the full inventory.
# Repeat the same bounded full run until remaining=0; maximum batch size is 500.
python -m scripts.repair_room_counts reverse --original-run-id <apply-uuid> --run-id <new-uuid>
```

Both repair and reversal default to read-only. Writes bind the artifact, code,
source identity, row version and selection. Changes, audit and receipts commit
atomically. A completed retry writes nothing; reversal cannot overwrite later
observations. Room history shares the existing manifests/receipts and fact history.
Price-only repairs remain price-only. Existing unified repairs also reassess rooms
when asset context changes, and coordinate room reversal with their other changes.

### Recovering values that were never saved

Most historical bathroom numbers have no retained labelled source. Keep those
numbers and mark their evidence UNVERIFIED while recovery proceeds. Existing
NULLs remain explicit gaps unless evidence supplies a count; they do not mean
that the property has no bathroom. Some current pages genuinely omit a bathroom
value; omission cannot erase a saved count or establish a replacement.

```bash
python -m scripts.refresh_room_counts --source propertypro --limit 25 \
  --after-id 0 --output .local/room-counts/primary-observations-001.json
```

This bounded command observes primary pages and saves a report. It respects robot
directives, uses the recovery traffic lock, defers to health-check traffic, checks
identity and requires exact title/description agreement. Add `--apply` only to
save the room fields and audit. Prices and unrelated fields are unchanged.
Changed text is reported as needing a full health-check observation. Unavailable,
redirected and incomplete pages stay unresolved. Use a new report path and its
`next_after_id` to continue; do not repeatedly revisit the same unresolved pages.

When operating from a worktree, set PROPERTY_SCRAPER_LOCK_DIR to the production
checkout's `.local/locks` so recovery and health checks share the same host lock.
This is bounded recovery tooling, not an unattended retry scheduler.

Room-only observation callers may use `room_count_store.persist_many` with an
`observations` mapping to batch writes while retaining each actual saved before
state and immutable audit. They must lock/check source rows and validate page
identity and source agreement first. The API rejects mismatched portal identities;
changed-source observations still require a full listing transaction. Repeated
identical observations retain the original storage-action record and emit no
additional audit solely because an earlier fill/correction is now unchanged.

### Turning the verification backlog into usable data

UNVERIFIED is a starting condition to investigate, not a finished cleanup. A
bedroom assessment and a bathroom assessment are separate: an unverified bathroom
must not discard a supported bedroom, property type or price. Count coverage by
field, portal, asset category and active/removed status. A missing bathroom number
on a land listing is different from one on an active flat listing.

Every room preview now writes a matching `.review.csv` worksheet and includes its
checksum and row count in the summary. Rows contain the listing URL, stored values,
candidate counts, statuses, asset context, review reasons, priority, source hash,
next action and blank review-result/evidence/note columns. Keep the frozen export;
copy it before adding review notes. Editing a worksheet does not itself update the
database or turn a number into a verified fact.

The priorities are:

| Priority | Work |
| --- | --- |
| 0 | Negative counts, 100+ counts and possible concatenated-digit values such as 123/1234 |
| 1 | Counts above 20, unexplained zeroes, positive room counts on land and unusual room ratios |
| 2 | Stored numbers that conflict with supported source claims, or conflicting/mixed source evidence |
| 3 | Ordinary retained numbers whose evidence is still unverified |
| 4 | Missing or unresolved counts without a stored number |

These are review triggers, not errors established by a numeric threshold. For
example, 120 bedrooms could be a hotel-wide claim. Check building/unit scope and
primary evidence before accepting or correcting it. The ratio check applies only
to residential unit adverts: at least one count is 10 or more and exceeds five
times the other positive count. Equal ordinary bedroom/bathroom numbers are not
an outlier trigger. Flags are exposed in `room_count_evidence.review_flags` and in
the research review queue as `room_review_flags` and `room_review_priority`.

Most primary-page recovery should be automatic. Select active exceptional rows
first, followed by source conflicts and ordinary unverified counts. Each request
can recover both fields; `--field` also permits a field-specific pass. Use the
worksheet IDs to prioritize without revisiting unrelated rows:

```bash
python -m scripts.refresh_room_counts --ids <comma-separated-reviewed-ids> \
  --limit 25 --output .local/room-counts/priority-recovery-001.json
python -m scripts.refresh_room_counts --source propertypro --field bathrooms \
  --limit 25 --after-id <cursor> --output .local/room-counts/bathrooms-002.json
```

Recovery reports distinguish supported observations, newly supported fields,
proposed corrections, proposed fills and failure outcomes. Without `--apply`,
all of these are proposed improvements, not production changes. Exact source
changes go through a full identity-checked health observation so current metrics
are not combined with stale listing text. Missing widgets, inaccessible pages and
genuine conflicts remain visible with their reason. Do not repeatedly revisit
them in an immediate retry loop.

Start with a bounded pilot across portals and work priorities, measure the actual
yield, then run successive batches and compare coverage before/after. A useful
completion report accounts for every exceptional value, separates resolved from
unavailable/changed/conflicting cases, and lists the next action for each remaining
case. It must not equate HTTP success with a supported count, extrapolate a small
pilot into a promised accuracy percentage, or make the backlog smaller by relabelling
unsupported values as verified. Continued new observations should reduce the
backlog automatically; evidence that portals never disclose remains a real limit.

Downstream bedroom analyses can use `bedrooms_status='KNOWN'` and the appropriate
count basis without requiring a verified bathroom. Bathroom-dependent analyses
should report their smaller supported sample. Exploratory analyses may include
retained UNVERIFIED numbers explicitly, inspect the outlier flags and compare
results with the supported subset. Describe those assumptions and differences in
portal coverage rather than presenting the whole database as uniformly verified.
