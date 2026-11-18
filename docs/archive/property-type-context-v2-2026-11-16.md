# Property classification v2: context preview

Status: read-only preview of the accepted spelling/context implementation.
No production migrations, listing updates, or portal requests were performed.
Definitions and feature proposals are discussed separately in
[review PR #12](https://github.com/islajr/property-scraper/pull/12).

## Method

Production snapshot: **2026-11-16 07:00:41.528846+00:00 UTC** (08:00:41 WAT on
16 November 2026). Scanned **28,955 listings** in one server-enforced read-only,
repeatable-read transaction. Both the master v1 implementation and this v2
implementation classified the same saved raw labels, titles, and descriptions.
Previous canonical values were not used as primary evidence.

The private JSONL preview and its summary are bound by a checksum and classifier
source fingerprint. The complete artifact passed the normal backfill preflight;
its six accepted review examples produced the expected types. Preflight verifies
artifact consistency, not classification accuracy or permission to apply it.

## Changes compared with v1

| Comparison on the same source snapshot | Listings |
| --- | ---: |
| Classification type/status/facets changed | 170 |
| Previously unresolved under v1, proposed CLASSIFIED under v2 | 154 |
| Previously CLASSIFIED under v1, proposed unresolved under v2 | 4 |
| Supported type refined or corrected while remaining CLASSIFIED | 5 |
| Unresolved state changed from insufficient evidence to ambiguity | 7 |

These counts exclude changes solely to version, timestamp, or evidence metadata.
They compare classifier outputs, not applied production changes. A version-only
update is not counted as a recovered listing. The 154 proposals include 73
self-contained units, 37 flats/apartments, nine maisonettes, and supported home
forms recovered from explicit leading description statements. These are preview
outcomes, not independently verified accuracy or approved backfill selections.

Four formerly supported results now expose unresolved questions: listing 3236
used ROOM for bedroom wording without a supported house form; 6464 contains both
maisonette and duplex; 10829 and 29352 combine a House label with maisonette
wording. Their definitions/evidence require review rather than a forced winner.

The context guard also keeps listing 16278 unresolved: removing a spurious ROOM
candidate does not prove an entire block is for sale. Listing 3718 remains
unresolved because its BQ room is ancillary and the main home's form is unstated.
Both were checked in the final artifact. The guard does not settle the general
scope-recovery backlog.

For reference, the full unfiltered v2 proposal contains 25,983
CLASSIFIED, 672 AMBIGUOUS,
2,268 INSUFFICIENT_EVIDENCE, and
32 UNSUPPORTED results. This includes pre-existing
v1 proposals for held legacy records. Those are not newly approved scope decisions;
do not treat the unfiltered preview as an apply selection.

## Deployment and limits

- Apply migration 008 before v2 writers. It registers the same 36 vocabulary
  codes under the new rule version and leaves old observations and audits intact.
- Keep old v1 artifacts immutable. Any later apply needs a reviewed v2 selection
  and must retain the audited row-version and evidence guards.
- Reconcile the old 14 November worklist with this 28,955-row inventory before a
  correction run; the older baseline contained 28,102 rows.
- Independently offered rooms, offices, and cinemas remain primary candidates.
  The classifier does not add features to storage or invent bedroom counts.
- Structured feature extraction, multi-offer representation, new vocabulary,
  pending precedence decisions, and wider scope recovery remain separate work.

## Validation

**534 tests passed**, including disposable PostgreSQL migration reruns, v1
preservation, vocabulary compatibility, classification persistence/audit, and
backfill/reversal checks. New cases cover accepted interpretations, contrasting
assets, explicit negation, other agent inventories, exact corroborating evidence,
ancillary BQ rooms, and the whole-block guard. Test execution used only the
explicitly selected disposable database, never production.

Private preview SHA-256: `18a88031e91acea5314fdf41898166b034f074e99897093aff5e6c253f9636aa`.
Classifier SHA-256: `37dd98a12d4a6815501c535162d6262bec31f558b43f0f3ca0eee66af1f0e7be`.
