# Property classification: implementation and rollout

The shared classifier in `scraper/property_types.py` implements the
[taxonomy contract](property-type-taxonomy.md) as `property-types-v1`. It retains
all 19 legacy codes and adds the 17 agreed forms. Unknown text no longer becomes
a canonical type. The original [audit](property-type-audit-2026-11-13.md) remains
the baseline inventory, not an estimate of current classifier accuracy.
The [full read-only preview](property-type-preview-2026-11-13.md) records proposed
states and transitions for the 28,102 listings inspected during implementation.

## Current behaviour

Discovery normalization returns the property type together with category,
family, attachment, asset scope, advertised land use, raw portal label, status,
matched evidence, rule version, and classification time. The numeric bedrooms,
listing purpose, price, and lifecycle contracts remain independent.

| Evidence | Result |
| --- | --- |
| Semi-detached label and a duplex title | `SEMI_DETACHED_DUPLEX` |
| Generic duplex | `DUPLEX`, attachment NULL |
| Mini flat in a generic apartment category | `MINI_FLAT` |
| Conflicting detached and terraced descriptors on a duplex | `DUPLEX`, attachment NULL; evidence records the conflict |
| Commercial label and an explicit land title | `LAND`, advertised use `COMMERCIAL` |
| Bungalow with a terrace amenity | `BUNGALOW`; the terrace does not establish attachment |
| Block-of-flats label and an individual-apartment title | `AMBIGUOUS`, type NULL |
| Gas plant | `UNSUPPORTED`, type NULL |
| Bedrooms or short-let purpose without form evidence | `INSUFFICIENT_EVIDENCE`, type NULL |

The vocabulary lookup supplies aggregation families. For example, generic,
detached, semi-detached, and terraced duplexes share family `DUPLEX`; the finer
type codes remain available. A house does not become a duplex because it has
four bedrooms. Mansion, villa, and townhouse attachment requires separate
evidence. `COMMERCIAL` is a broad asset category, not verified legal zoning.

### Evidence boundaries

PropertyPro captures the last type-bearing link in the primary listing's
breadcrumb. It preserves that link's wording as `BREADCRUMB` evidence and ignores
location/purpose suffixes while matching. PrivateProperty captures the labelled
type in the primary property-details section. NigeriaPropertyCentre retains its
primary type label, including incomplete descriptors such as “Semi-detached”.
Missing labels remain NULL. No raw label is fabricated from a historic type.

Rules use word boundaries, plural/spacing/hyphen aliases, and specific phrases
before broader phrases. Separate incompatible assets remain candidates rather
than being hidden by whichever rule matches first. Compatible labels can refine
each other. Included features, nearby landmarks, negations, and alternative uses
are not evidence of another offered asset. “Suitable for a hotel” does not
establish an existing hotel.

Description recovery is deliberately limited. When primary text cannot identify
an asset, the classifier checks up to three leading description statements with
an explicit asset form near the start, stopping at feature, location, or price
headings. A specific primary title/label is not overridden by a general
description. Unknown marketing prose remains unresolved. This first version
does not use portal URL slugs or infer form from bedroom counts.

Input processing is bounded to 1,000 characters for a portal label, 2,000 for a
title, and the leading 3,000 characters of a description. Evidence contains at
most 40 matches, with source, exact text, rule ID, and the supported candidate or
attribute. These limits can leave some records unresolved. Coverage is reported
separately from accuracy; there is no numeric confidence score.

## Storage and transaction behaviour

Migration [006](../schema/006_property_classification.sql) adds the metadata,
versioned `raw_data.property_type_vocabulary` lookup, classification audit table,
and `raw_data.property_classification_coverage` view. It never rewrites existing
property labels, prices, or lifecycle dates. Existing rows start as
`LEGACY_UNREVIEWED`, with no invented raw label, evidence, or classification date.

The database constrains status/type coherence, supported categories and facets,
known rule versions, vocabulary/category/family agreement, compound attachment,
and required scope for land and whole-building types. A `CLASSIFIED` result must
have a supported code and evidence. Unresolved nonlegacy results have a NULL
type. Legacy values remain readable until explicitly reviewed.

The discovery writer persists classification on inserts, ordinary updates, and
relisting/conflict paths. Health checks persist it when a typed primary
observation has the same source and external ID as the stored listing. An
unparseable new price does not prevent a supported classification correction;
the existing price-rejection contract still preserves the prior price.

Classification and audit insertion share the caller's transaction. Every change
records old/new metadata, origin, run ID, rule version, and decision time in
`raw_data.property_classification_history`. Initial decisions have no previous
classification. Identical decisions do not create duplicate history or refresh
their classification time. Audit rows cannot be updated or deleted; a future
backfill reversal must append a new event.

Old dataclass/checkpoint shapes retain defaults. Before writing an unreviewed
DTO, the writer classifies its saved title/description/raw label; it never treats
the old canonical value as new evidence. The pricing-recovery job remains a
pricing-only repair path; it does not apply property-type changes discovered
incidentally during a quote visit.

## Preview existing listings before applying a backfill

Run from the repository root:

```bash
python -m scripts.preview_property_classification \
  --output .local/property-types/preview-v1.jsonl
```

The command reads `DATABASE_URL` from the environment or `.env`. It has no apply
mode, runs no migrations, and visits no portals. PostgreSQL enforces a read-only,
repeatable-read transaction. It works before migration 006 because it uses the
original columns and reads optional metadata through `row_to_json`.

It streams an atomic local JSONL report and a companion `preview-v1.summary.json`.
Each row includes the listing identity, saved title, previous/proposed metadata,
and observed row version. The summary contains state counts, type transitions,
coverage by portal and lifecycle state, a credential-free database fingerprint,
and the report's SHA256. A partial run
does not replace the last completed report. Verify the checksum before pairing
a summary with a detailed report; the two files are replaced individually.

Optional bounds:

```bash
python -m scripts.preview_property_classification \
  --source nigeriapropertycentre --status ACTIVE --limit 500 \
  --output .local/property-types/npc-sample.jsonl
```

`--after-id` and `--batch-size` are also supported. Filters are recorded, and a
bounded report is explicitly marked as a partial database scan. Full reports
include removed rows and apparently valid canonical labels. Old values are
never fed back to the classifier as raw labels. Original portal labels absent
from historic storage are explicitly counted as unavailable.

Connection failures suppress libpq details to prevent credentials entering logs.
Reports are project-local and ignored by Git. Detailed reports contain listing
evidence, so share a reviewed aggregate summary rather than committing every
row's text to the repository.

## Deployment order and consumers

1. Review the PR, regression cases, disposable-database checks, and full preview.
   The preview is a proposal, not permission for a production rewrite.
2. Apply numbered migrations in order before starting classification-aware
   writers. `run.sh`, weekly discovery, and daily health-check workflows already
   apply all files under `schema/` in order. Direct Python invocations and other
   deployments must arrange this explicitly. Migration 006 is additive and
   repeatable; it uses a short lock timeout rather than waiting indefinitely.
3. Capture classifications on new primary observations. Discovery still skips
   known active URLs; do not expect the normal runs to repair the full inventory.
4. Review dry-run transitions and unresolved examples, then implement a separate
   bounded, auditable apply/reversal command with concurrency guards and resume.
   The [backfill runbook](property-classification-backfill.md) documents migration
   007, exact selections, durable receipts, and the prepared four-listing canary.
   Both subcommands default to read-only; no production backfill has been run as
   part of implementation.
5. Inventory callers of `market.classify_property` and external enum/API/report
   consumers. Move them to the shared contract or a documented versioned adapter.
   This release does not replace that external function or rebuild market
   snapshots. Clients must tolerate new codes and explicit unresolved states.

Consumers should select verified classifications explicitly:

```sql
SELECT property_category, property_type_family, property_type, COUNT(*)
FROM raw_data.scraped_listings
WHERE property_type_status = 'CLASSIFIED'
  AND property_type_version = 'property-types-v1'
GROUP BY property_category, property_type_family, property_type;

SELECT * FROM raw_data.property_classification_coverage;
```

Keep sale/rent/short-let, billing-period, currency, and price-basis eligibility
guards when comparing prices. A supported property form alone does not make
prices comparable. Keep unresolved and legacy rows in coverage denominators.

Operational rollback means rolling back the application code while retaining
the additive columns, vocabulary, and audit evidence. Do not drop the audit
table or overwrite a historic type from a fresh portal visit. Old application
writers must not continue updating already verified rows without updating their
classification evidence; stop affected jobs while reverting or correcting them.

## Verification

The regression set includes all canonical codes; phrase, conflict, context, scope,
and missing-evidence cases; saved primary HTML from the enabled portals; and
[32 title-only examples](../tests/fixtures/property_type_cases.json) from the
database audit. Their expected decisions have explicit rationales. They are
review examples, not a randomly sampled ground-truth dataset or an accuracy
estimate for all listings.

Tests using an explicitly selected disposable `TEST_DATABASE_URL` check initial
migration and reruns, legacy preservation, vocabulary agreement, constraints,
audit immutability, update/relisting/health-check paths, idempotence, transaction
rollback, and pre-migration read-only preview. No test uses production as its
database fixture.
