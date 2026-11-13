# Reviewed property classification backfill

The backfill command applies a reviewed preview in bounded increments and can
reverse its own changes. Both `apply` and `reverse` subcommands default to a
server-enforced read-only dry run. Writes require the explicit `--apply` flag.
Neither subcommand runs migrations or contacts listing portals.

Apply migration [007](../schema/007_property_classification_operations.sql) after
006 before enabling writes. It adds operation receipts and audit row versions;
it does not change any listing classifications. Existing deployment entry points
already apply numbered migrations in order.

## Review the selection

Use the detailed JSONL produced by `scripts.preview_property_classification`
together with its companion `.summary.json`. The loader validates the entire
artifact before a write connection is opened, including checksum, count, unique
increasing listing IDs, metadata shape, rule version, and decision times. It
stages a private copy so editing the original file during execution cannot
change what gets applied.

New previews include the exact classifier source hash and external listing ID.
The original v1 preview remains supported. Every proposed decision, including
legacy previews, is recomputed from current saved evidence before apply and must
match the reviewed decision. A checksum establishes file integrity, not that a
person has approved the decisions.

The original 28,102-row preview contains these review groups:

| Proposed transition | Rows | Review action |
| --- | ---: | --- |
| Apartment to mini flat | 1,352 | Check the explicit mini-flat/room-and-parlour evidence |
| Detached duplex to semi-detached duplex | 1,193 | Check attachment and form in primary text |
| Detached duplex to generic duplex | 1,094 | Keep attachment unknown if surviving evidence cannot establish it |
| Detached duplex to terraced duplex | 958 | Distinguish terraced attachment from a terrace amenity |
| Apartment to studio | 337 | Check explicit studio evidence rather than bedroom count |
| Apartment to block of flats | 218 | Hold for scope review: a unit in a block is not the whole building |

484 rows contain at least one description evidence match, and seven carry an
attachment-conflict reason. Inspect those contexts when selecting a cohort. These
are review categories, not newly adjudicated error counts. No classifier rules
are changed by this backfill release.

## Prepared four-listing canary

These title-based cases span all three enabled portals and both lifecycle states:

| ID | Portal | Lifecycle | Previous type | Reviewed proposed type |
| --- | --- | --- | --- | --- |
| 7 | PropertyPro | Removed | `DETACHED_DUPLEX` | `SEMI_DETACHED_DUPLEX` |
| 78 | PropertyPro | Removed | `FLAT_APARTMENT` | `MINI_FLAT` |
| 165 | PrivateProperty | Active | `FLAT_APARTMENT` | `STUDIO` |
| 14355 | NigeriaPropertyCentre | Active | `SEMI-DETACHED` | `SEMI_DETACHED_DUPLEX` |

Their primary titles explicitly identify the forms. A read-only check during
implementation found all four eligible against the saved preview; no production
updates were performed. Eligibility must be checked again at apply time because
subsequent scraper activity may change a row.

The reviewed input is `.local/property-types/preview-v1.jsonl`, with SHA256:

```text
75c9a1e62c87988e0418190cbdba6106cbdf25109757cd46cbfb4f36c19886d6
```

Repeat the dry run from the repository root:

```bash
python -m scripts.backfill_property_classification apply \
  --report .local/property-types/preview-v1.jsonl \
  --run-id 04c9865a-312e-4c71-bf94-97f80409b514 \
  --ids 7,78,165,14355 --max-records 4 \
  --output .local/property-types/canary-review.json
```

After reviewing that result and deploying migration 007, the exact same command
with `--apply` enables the four updates. This is a prepared operational action,
not a statement that the canary has already run. The run ID is fixed for this
canary; use a new UUID for another reviewed cohort.

## Apply, stop, and resume

A run ID is permanently bound to its database fingerprint, input digest, rule
version, and selection. Supported filters are `--source`, `--status`,
`--decision-status`, `--type`, `--ids`, `--after-id`, and `--through-id`. Filters
refer to the reviewed preview, not a moving set of newly discovered rows.

`--max-records` limits pending rows attempted **per invocation**, defaulting to
100. Repeat the same run ID, artifact, and filters to process the next pending
rows. The budget can change between invocations; the selection cannot. ID bounds
are fixed selection criteria, not resume cursors. A locked early row remains
pending even if later rows have already finished.

For every selected pending row, the command checks:

1. The connected database matches the reviewed fingerprint.
2. Source, lifecycle state, row version, previous classification, and any saved
   external ID still match the preview. Any update to a row, even a price-only
   observation, makes the old proposal stale.
3. Reclassifying the current saved label/title/description yields the same
   reviewed decision. The old canonical label is never treated as raw evidence.

An eligible update changes only classification fields. Its before/after audit
event and durable receipt commit in the same transaction. Classification time
reflects revalidation at apply, not a fabricated historic observation date.
Prices, listing purpose, descriptions, lifecycle dates, suspected-sale flags,
and transaction-proxy history are not rewritten.

Receipts in PostgreSQL are the resume authority. If a process stops after commit
but before saving a local report, the next invocation finds that receipt and
does not repeat the update. If audit or receipt insertion fails, the row update
rolls back too. Each row commits independently, so earlier completed rows remain
available for reconciliation after a later failure.

The command saves a local JSON result, defaulting to
`.local/property-types/apply-RUN_ID.json`. It includes the bound manifest,
selection, outcomes, and remaining pending count. Database errors suppress
connection details. After an interruption or local report failure, reuse the
same run ID rather than assuming nothing committed.

| Outcome | Meaning |
| --- | --- |
| `ELIGIBLE` | Dry run: evidence and concurrency checks passed; nothing applied |
| `APPLIED` | Classification, audit, and receipt committed |
| `UNCHANGED` | The reviewed decision is already supported; no listing update or new classification audit |
| `CONCURRENT_CHANGE` | Stored row differs from the reviewed snapshot; not overwritten |
| `MISSING` | Listing no longer exists |
| `PROPOSAL_MISMATCH` | Current rules/evidence disagree with the reviewed result |
| `RETRYABLE_LOCK` | The row is busy; no terminal receipt, so retry on resume |

Terminal skips are recorded so resume cannot later overwrite a changed row using
an old approval. Resolve them with fresh evidence, a new preview, and a new run
ID. `complete=true` means all selected rows have terminal receipts; inspect the
outcome counts to see which were applied, unchanged, or skipped. A dry run leaves
pending counts unchanged and never creates an operation or receipt.

## Reverse a backfill

Reversal targets only `APPLIED` receipts from an existing backfill run. It never
reverses discovery or health-check audits. Give reversal its own UUID:

```bash
python -m scripts.backfill_property_classification reverse \
  --original-run-id 04c9865a-312e-4c71-bf94-97f80409b514 \
  --run-id 888ff218-97c4-41e7-90de-d130fd73a9dc --max-records 4
```

This is also read-only unless `--apply` is supplied. Reuse the reversal run ID
and filters to resume a bounded reversal. It restores the exact prior metadata,
including legacy labels and their honest unreviewed state, only when:

- The listing still has the backfill's applied row version and metadata.
- The backfill event remains its latest classification audit.
- That event has not already been reversed.

Later observations produce `SUBSEQUENT_CHANGE` and are left intact. Previously
reversed events produce `ALREADY_REVERSED`. A successful reversal appends a
`REVERSAL` audit referencing the original event and records a receipt; it never
edits or deletes the original audit. A unique database index prevents a second
reversal of the same event.

Apply and all its reversals share an operation lock. Starting an actual reversal
permanently stops further apply resume for that original run, including any
pending rows. This prevents a partially resumed apply from repairing more rows
after an operator has started undoing it. Further repairs require a fresh
preview and new apply run. A reversal dry run does not pause the apply run.

## Inspect durable results

```sql
SELECT run_id, kind, reverse_of, manifest, created_at
FROM raw_data.property_classification_operations
ORDER BY created_at DESC;

SELECT run_id, outcome, COUNT(*)
FROM raw_data.property_classification_receipts
GROUP BY run_id, outcome;

SELECT id, listing_id, run_id, origin, reverses_id,
       old_classification, new_classification, applied_row_version
FROM raw_data.property_classification_history
WHERE origin IN ('BACKFILL', 'REVERSAL')
ORDER BY id;
```

Operations, receipts, and classification history are append-only. Keep the
additive schema and evidence during operational rollback. Downstream callers of
`market.classify_property` and fixed external enum contracts still require their
own migration; neither this tool nor reversal rebuilds market snapshots.

## Implementation validation

The full local suite passed 488 tests with both database URLs explicitly set to
disposable PostgreSQL. Backfill checks include bounded resume, an interruption
after commit, rollback on audit/receipt failures, source/price/lifecycle changes,
proposal recomputation, real row-lock contention, apply/reversal exclusion,
immutable receipts, exact reversal, and preservation of unrelated fields.
Artifact checks cover complete preflight, private staging, source/digest binding,
credential redaction, and preventing output from overwriting a reviewed input.

The production canary check used no `--apply` flag and returned
`read_only=true`, four `ELIGIBLE` outcomes, and four remaining pending rows. The
detailed result is `.local/property-types/canary-review.json`; no operation or
receipt was created by that dry run.
