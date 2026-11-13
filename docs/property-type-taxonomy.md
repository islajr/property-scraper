# Property types: proposed vocabulary and classification contract

Status: proposal for review. This document does not change the running scraper,
database schema, or stored classifications. The supporting inventory and sample
mapping are in [the audit](property-type-audit-2026-11-13.md).

The aim is to give research and applications a dependable meaning for each
property type. Existing types are the starting point. Keep a type when the
evidence supports it, correct errors explicitly, and keep unresolved records
visible. A low unknown count is not evidence of a good classifier.

## Respecting the existing vocabulary

Retain all 19 codes defined by `scraper.normaliser.PROPERTY_TYPE_MAP`, including
the three that were absent from the audited database. A code's presence in that
map establishes its intended meaning; it does not certify every row using it.

| Existing code | Proposed category | Meaning to preserve |
| --- | --- | --- |
| `FLAT_APARTMENT` | `RESIDENTIAL` | An individual flat or apartment without a supported more specific type |
| `MINI_FLAT` | `RESIDENTIAL` | An explicitly advertised mini flat or room-and-parlour unit |
| `STUDIO` | `RESIDENTIAL` | An explicitly advertised studio; bedroom count alone is insufficient |
| `PENTHOUSE` | `RESIDENTIAL` | An explicitly advertised penthouse |
| `DETACHED_DUPLEX` | `RESIDENTIAL` | A duplex explicitly described as detached |
| `SEMI_DETACHED_DUPLEX` | `RESIDENTIAL` | A duplex explicitly described as semi-detached |
| `TERRACED_DUPLEX` | `RESIDENTIAL` | A duplex explicitly described as terraced |
| `DETACHED_BUNGALOW` | `RESIDENTIAL` | A bungalow explicitly described as detached |
| `SEMI_DETACHED_BUNGALOW` | `RESIDENTIAL` | A bungalow explicitly described as semi-detached |
| `TERRACED_BUNGALOW` | `RESIDENTIAL` | A bungalow explicitly described as terraced |
| `MANSION` | `RESIDENTIAL` | An explicitly advertised mansion; do not infer attachment |
| `VILLA` | `RESIDENTIAL` | An explicitly advertised villa; do not infer attachment |
| `OFFICE` | `COMMERCIAL` | Office space or an individual office unit |
| `COMMERCIAL_SHOP` | `COMMERCIAL` | A shop or retail unit |
| `SHOWROOM` | `COMMERCIAL` | A showroom |
| `WAREHOUSE` | `COMMERCIAL` | A warehouse; commercial is the broad category, not a claim about zoning |
| `COMMERCIAL_OTHER` | `COMMERCIAL` | Explicit commercial premises without a supported more specific type |
| `LAND` | `LAND` | A land parcel with no established serviced status |
| `LAND_SERVICED` | `LAND` | Land explicitly advertised as serviced |

`COMMERCIAL_OTHER` is a valid broad classification supported by commercial
evidence. It must not become the catch-all for missing, conflicting, or unfamiliar
text. A legitimate broad type such as `HOUSE` is also useful and can be classified
without knowing its finer attributes.

## Proposed additions

These additions cover recurring evidence in the existing data and allow honest
classifications without assuming a more specific type. Alias rules must be
verified against primary listing evidence during implementation.

| Proposed code | Category | Required evidence or boundary |
| --- | --- | --- |
| `HOUSE` | `RESIDENTIAL` | A residential house; form may be unknown |
| `DUPLEX` | `RESIDENTIAL` | A duplex with unspecified attachment; never default to detached |
| `BUNGALOW` | `RESIDENTIAL` | A bungalow with unspecified attachment |
| `TOWNHOUSE` | `RESIDENTIAL` | Explicit townhouse; do not assume it is a duplex |
| `MAISONETTE` | `RESIDENTIAL` | Explicit maisonette; keep distinct from a generic apartment |
| `SELF_CONTAINED` | `RESIDENTIAL` | Explicit self-contained unit without enough evidence for mini flat or studio |
| `ROOM` | `RESIDENTIAL` | An individual room offered as the listing; private facilities are not assumed |
| `BLOCK_OF_FLATS` | `RESIDENTIAL` | The advertised asset is an entire block of flats, not a unit within one |
| `OFFICE_BUILDING` | `COMMERCIAL` | The advertised asset is an entire office building |
| `HOTEL` | `COMMERCIAL` | A hotel offered as the asset; a short-let apartment is not automatically a hotel |
| `GUEST_HOUSE` | `COMMERCIAL` | A guest house offered as the asset; do not use a nearby landmark |
| `SCHOOL` | `COMMERCIAL` | Existing or purpose-built school premises offered as the asset |
| `HOSPITAL` | `COMMERCIAL` | Existing or purpose-built hospital premises offered as the asset |
| `RESTAURANT` | `COMMERCIAL` | Restaurant premises offered as the asset |
| `FACTORY` | `COMMERCIAL` | Factory premises offered as the asset |
| `FILLING_STATION` | `COMMERCIAL` | Explicit filling/petrol station; a gas plant requires its own supported mapping |
| `MIXED_USE_PROPERTY` | `MIXED_USE` | A built property explicitly containing multiple uses |

This gives 36 proposed type codes: 19 retained and 17 additions. New codes require
a documented definition, representative evidence, aliases, and regression cases.
Unfamiliar terms remain reviewable until that work is done.

## Separate attributes from property type

Use stable type codes for the advertised asset. Keep these distinctions separate:

- **Category:** `RESIDENTIAL`, `COMMERCIAL`, `LAND`, or `MIXED_USE`. A known type
  determines its category through the vocabulary lookup. A record may have a
  supported category while its type is unresolved; otherwise category is NULL.
- **Attachment:** `DETACHED`, `SEMI_DETACHED`, or `TERRACED`; NULL when unknown.
  The six existing compound duplex/bungalow codes imply their corresponding
  attachment. `HOUSE` with explicit semi-detached evidence can retain that
  attachment without inventing a duplex. The classifier must keep these fields
  consistent.
- **Asset scope:** `UNIT`, `WHOLE_BUILDING`, `MULTIPLE_UNITS`, `LAND_PARCEL`, or
  NULL when unresolved. A flat in a block is not a whole block. Do not infer that
  several units offered together constitute an entire building.
- **Land use:** `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, `AGRICULTURAL`, or
  `MIXED_USE`, and NULL when unknown. This records the advertised use, not legally
  verified zoning. Commercial land remains category `LAND`; mixed-use land does
  not become a built `MIXED_USE_PROPERTY`.
- **Bedrooms:** keep the existing numeric attribute independent. Missing bedrooms
  stay missing; one bedroom does not establish a studio or mini flat.
- **Listing purpose and pricing:** keep the existing sale/rent/short-let and
  pricing contracts independent. Short let, furnished, luxury, serviced apartment,
  off-plan, and location are not substitutes for property form.

For example, `DETACHED_DUPLEX` remains that exact code and implies detached
attachment. Plain “duplex” becomes `DUPLEX` with unknown attachment. The proposed
lookup should also expose families for aggregation, so research can group all
duplex subtypes together without discarding the stored distinctions.

## Classification result and unresolved markers

Proposed persisted metadata, in addition to the type and supported attributes:

| Field | Contract |
| --- | --- |
| `property_type_raw` | Original primary portal label, if captured; never fabricate it from the old canonical value |
| `property_type_status` | One of the states below; required after migration |
| `property_type_evidence` | Bounded structured evidence: field/source, exact matched text, rule ID, and conflicting candidates when present |
| `property_type_version` | Version of the vocabulary and rules used for this decision |
| `property_type_classified_at` | Time of classification, not a replacement for the listing observation time |

| Status | Meaning | Canonical type |
| --- | --- | --- |
| `CLASSIFIED` | Evidence establishes a supported type, including a legitimate broad type | Required |
| `INSUFFICIENT_EVIDENCE` | Missing or generic information cannot establish the asset's type | NULL |
| `AMBIGUOUS` | Incompatible evidence about the advertised asset remains unresolved | NULL |
| `UNSUPPORTED` | A specific asset type is present but has no supported vocabulary mapping | NULL |
| `LEGACY_UNREVIEWED` | Existing row has not yet been assessed with the new rules | Preserve its previous value during rollout only |

If a disputed subtype still allows a broad type, record that broad type and leave
the disputed attribute unknown. If the asset type itself is disputed, retain the
candidates in evidence and mark it ambiguous. A standalone label such as
“Residential” can establish category without establishing type.

Consumers must filter on `CLASSIFIED` before treating the canonical type as
verified. Unresolved rows stay available for coverage reporting and review. Do
not put `OTHER`, title fragments, or concatenated candidate names in the type
field as substitutes for these states.

Preserve each previous stored value in an append-only classification audit before
changing it. Record listing ID, before/after type and metadata, rule version, run
ID, evidence, and classification time. The previous value alone is not evidence
for the new result. The historic original portal label was not persisted, so
offline recovery must explicitly report that absence.

## Evidence rules

1. Restrict evidence to the primary listing. Prefer its explicit structured label
   and category/breadcrumb information, then its title. A specific title can
   refine a compatible broad portal label. An unrecognized label must not stop
   examination of other evidence.
2. Use the description only for statements identifying the offered asset. Do not
   classify from amenities, a boys' quarter, nearby landmarks, recommendations,
   agent inventories, or proposed alternative uses. “Suitable for a hotel” does
   not prove an existing hotel.
3. Apply specific aliases before broad aliases and use word/phrase boundaries.
   Recognize hyphen/spacing/plural variants, including “semi detached”, “terrace
   duplex”, and “miniflat”. Do not let “detached” consume “semi-detached”, or
   “flat” consume “mini flat”. Exact alias matching and free-text matching must
   agree on these distinctions.
4. Treat existing canonical values as supported inputs when re-normalizing
   records, but do not use a historic classification to overrule conflicting
   primary evidence during backfill. Re-normalizing a verified code must be
   idempotent.
5. Separate compatible refinement from conflict. “Flat / Apartment” plus “Mini
   Flat” supports `MINI_FLAT`; “block of flats” plus an individual apartment title
   needs scope assessment. “Mixed-use” plus “terrace duplex” requires context;
   neither word match alone settles the offered asset.
6. Use portal URLs/breadcrumbs only when they describe the same primary listing.
   A search feed's category is not independent proof, and a misleading redirect
   must not supply another asset's classification.
7. Never infer form, attachment, bedrooms, serviced land, or asset scope from
   price, location, bedroom count, or a default. Avoid numeric confidence scores
   until there is a labelled evaluation set against which to calibrate them.

## Backfill and compatibility

The backfill must assess all rows, including apparently canonical values and
removed listings. The live audit found errors inside recognized codes, so merely
replacing unrecognized values would preserve material inconsistencies.

Use an additive rollout: add metadata and audit storage, deploy the shared
classifier on inserts and supported update paths, and then run a dry-run-first
offline backfill. Defaults must keep old checkpoints and dataclass factories
readable. Existing rows begin as `LEGACY_UNREVIEWED`; they must not be certified
merely because their value belongs to the vocabulary.

The apply command must be explicitly selected, bounded, resumable, idempotent,
and guarded against concurrent changes to the evidence or classification.
Preserve before/after results and support reversal without overwriting newer
observations. Classification changes must not alter prices, lifecycle dates,
activity, suspected-sale flags, or historical transaction events.

Known active listings are skipped during discovery, and the normal writer does
not update their property types. An explicit backfill is required. Live enrichment
of unresolved active listings, if needed, must be a separate bounded operation;
it must not rewrite old observation dates or imply historical certainty.

The database also contains `market.classify_property(title, raw_type, bedrooms)`.
Its vocabulary and defaults differ from the scraper's. Inventory its callers and
external API/report consumers before migration. Provide an explicit versioned
mapping or adapter for any legacy grouping; do not silently replace the function
or alter existing market snapshots. The Python classifier and downstream SQL
must consume one vocabulary rather than evolve competing definitions.

## Incremental implementation and acceptance

1. **Proposal and inventory:** this document, the audit, and read-only inventory
   SQL in a focused PR to `master`.
2. **Classifier and storage:** canonical lookup, additive migration, traceable
   classification result, evidence capture across enabled parsers, consistent
   persistence paths, and constraints. Include a documented deployment order for
   fresh and existing databases before enabling code that requires new columns.
3. **Backfill and consumers:** dry-run reports, audited apply/reversal, coverage
   summaries by portal/status, and documented downstream contract migration.

Use incremental conventional commits and PRs targeting `master`. A proposal's
acceptance does not mean a production backfill has been executed.

Implementation acceptance requires:

- Every audited row receives an honest state; no target forces all rows into
  `CLASSIFIED`.
- All 19 retained codes keep their meanings; supported new labels never create
  arbitrary canonical values.
- Regression cases cover specific-before-broad aliases, canonical-code inputs,
  incomplete labels, unsupported terms, conflict, description context, land use,
  asset scope, and missing attributes.
- A reviewed evaluation set spans all portals, frequent and rare types, canonical
  errors, and unresolved cases. Report errors and coverage separately; do not
  present matching the old labels as classifier accuracy.
- Disposable-database checks verify constraints, additive migration reruns,
  checkpoint compatibility, audited updates, concurrency guards, and reversal.
- Dry-run mode writes no database data and makes no portal requests. A repeated
  apply makes no duplicate changes, and interruption can resume safely.
- Consumers can distinguish verified current classifications, legacy values,
  unresolved evidence, and classifications made under different rule versions.
