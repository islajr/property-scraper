# Property type audit: 13 November 2026

This is a point-in-time, read-only inventory of `raw_data.scraped_listings` and
the current classifier. No classifications, schema, or lifecycle data were
changed. Counts include active and removed listings. The last recorded discovery
observation was 7 November 2026; this report does not imply a fresh portal visit.

The [taxonomy proposal](property-type-taxonomy.md) defines the recommended
contract. [The inventory SQL](../scripts/audit_property_types.sql) can repeat the
counts and bounded examples using a consistent, read-only database transaction.
Its vocabulary list deliberately describes the old classifier, so future runs
can still measure the legacy contract rather than silently move the baseline.

The committed inventory SQL was validated with `psql -X -v ON_ERROR_STOP=1` on
13 November 2026 at 09:15 UTC. All statements succeeded, the totals matched the
initial audit, and the transaction ended with `ROLLBACK`. The normaliser suite
was rerun on the proposal branch: 95 tests passed. A separate consistency check
verified that the proposal retains exactly the 19 existing codes, has 17 distinct
additions, and uses the same legacy vocabulary as the inventory SQL.

## Stored values

| Portal | Listings | Distinct non-NULL types | Outside the intended vocabulary, including NULL |
| --- | ---: | ---: | ---: |
| NigeriaPropertyCentre | 10,833 | 76 | 2,890 |
| PrivateProperty | 8,232 | 1,438 | 1,791 |
| PropertyPro | 9,037 | 1,661 | 2,238 |
| All portals | 28,102 | 3,150 | 6,919 |

Distinct counts are per source and are not additive: portals share some values.

- 21,183 rows (75.4%) use one of the intended codes. Membership is not proof of
  correctness.
- 6,919 rows (24.6%) are outside that vocabulary: 6,918 have other non-NULL values
  and one has NULL. There were no blank type values.
- Of the 3,150 distinct non-NULL values, 16 are intended codes and 3,134 are not.
- 2,706 non-NULL type values occur on only one listing each.
- The map permits 19 codes. `LAND_SERVICED`, `SEMI_DETACHED_BUNGALOW`, and
  `SEMI_DETACHED_DUPLEX` have no stored rows; retain them in the proposed contract.

Selected frequent values:

| Stored type | Listings | Observation |
| --- | ---: | --- |
| `FLAT_APARTMENT` | 11,725 | Includes titles explicitly advertising mini flats and studios |
| `DETACHED_DUPLEX` | 5,736 | Includes semi-detached titles and generic duplex inference |
| `LAND` | 1,814 | Advertised use and serviced status need separate evidence |
| `TERRACED_DUPLEX` | 771 | Valid intended code; still requires evidence review |
| `DETACHED` | 745 | Attachment alone, without a complete form |
| `TERRACED` | 489 | Attachment alone, without a complete form |
| `SEMI-DETACHED` | 355 | Attachment alone, without a complete form |
| `SELF_CONTAIN_(SINGLE` | 196 | Incomplete label and missing category support |
| `HOUSE` | 193 | Useful broad form absent from the intended map |
| `RESIDENTIAL` | 149 | May describe residential land rather than a building |
| `MIXED-USE` | 74 | Requires land/building and primary-asset context |
| `BLOCK_OF` | 60 | Incomplete label; asset scope must be established |

## Code and fixture findings

1. `normalise_property_type()` returns unmatched text uppercased, with spaces
   replaced and a 40-character limit. Titles therefore become new apparent
   types. The database column is unrestricted text with no vocabulary constraint.
2. Partial matching follows map insertion order. “Detached duplex” precedes
   “semi-detached duplex”; “flat” and “apartment” precede mini-flat/studio aliases;
   “land” precedes “serviced land”. Exact aliases may work while the same phrase
   embedded in a title fails.
3. Unknown input returns a non-NULL value. An unrecognized portal label prevents
   title fallback; an unrecognized title prevents description fallback.
4. PropertyPro and PrivateProperty set `property_type_raw=None`. The saved
   NigeriaPropertyCentre fixture supplies `Semi-detached`, without “duplex”.
5. Raw portal type is present in the transfer object but is not persisted in the
   listings table. There is no classification status, evidence, or version.
6. Discovery skips known active listings. The existing-row writer updates pricing
   and some lifecycle/location fields but does not update property type.
7. `market.classify_property(title, raw_type, bedrooms)` defines a second
   vocabulary. It can default unknown-bedroom apartments to `2_BED_FLAT` and
   infer house form from bedrooms. Caller activity was not established in this
   audit; the function's existence is not proof that every consumer uses it.

Saved primary-listing fixtures reproduced these outputs without portal requests:

| Portal | Primary evidence | Current output | Proposed handling |
| --- | --- | --- | --- |
| NigeriaPropertyCentre | Label `Semi-detached`; title `4 Bedroom Semi Detached Duplex. Off Plan` | `SEMI-DETACHED` | `SEMI_DETACHED_DUPLEX`; title refines the incomplete label |
| PrivateProperty | Title `For sale: A Building Suitable For A Hotel With 80rooms & Hall` | `FOR_SALE:_A_BUILDING_SUITABLE_FOR_A_HOTE` | Review the asset's existing use; “suitable for” alone does not establish `HOTEL` |
| PropertyPro | Title `Newly Furnished 3 Bedroom Luxury Apartment` | `FLAT_APARTMENT` | Retain `FLAT_APARTMENT` if no conflicting primary evidence |

The existing normaliser suite passed 95 tests during the initial audit. It tests
some known aliases but also expects arbitrary non-NULL output for unknown input
and accepts generic duplex as detached. Passing that baseline does not establish
classification accuracy.

## Indicators inside recognized labels

These title-based counts identify review candidates. They are not a manually
adjudicated error rate, can overlap, and must not be added together.

| Indicator | Listings |
| --- | ---: |
| `DETACHED_DUPLEX` with a semi-detached title | 1,169 |
| `FLAT_APARTMENT` with a mini-flat title | 1,328 |
| `FLAT_APARTMENT` with a studio title | 343 |
| `DETACHED_DUPLEX` without “detached” in the title | 2,186 |
| `LAND` with “serviced” in the title | 2 |

Absence of a term from a title is not proof of an error; other evidence may
support the stored type. These counts show why the backfill must inspect all
rows rather than only unrecognized codes.

## Representative stored listings and proposed decisions

The following are actual rows inspected during the audit, selected to illustrate
different failure modes. They are not a random or fully labelled evaluation set.
Proposals use the inspected title and, where noted, description. Apply-mode
decisions must recheck the full saved primary evidence and detect concurrent
changes. Previous type values must remain available in the classification audit.

| Listing ID | Portal | Stored type | Inspected evidence | Proposed decision |
| --- | --- | --- | --- | --- |
| 28193 | PrivateProperty | `DETACHED_DUPLEX` | Title: `For rent: 4 Bedroom Semi Detached Duplex` | `SEMI_DETACHED_DUPLEX`; explicit attachment correction |
| 28364 | NigeriaPropertyCentre | `FLAT_APARTMENT` | Title: `Mini Flat` | `MINI_FLAT`; specific form |
| 28371 | NigeriaPropertyCentre | `FLAT_APARTMENT` | Title: `Standard Room and Parlor (Mini Flat) with 2 Toilets` | `MINI_FLAT`; explicit alias, not bedroom inference |
| 28401 | NigeriaPropertyCentre | `SEMI-DETACHED` | Title and description identify a four-bedroom semi-detached duplex | `SEMI_DETACHED_DUPLEX`; incomplete label refined |
| 28461 | NigeriaPropertyCentre | `DETACHED` | Title: `Two Bedrooms Bungalow Available`; excerpt identifies a bungalow | `BUNGALOW`; attachment unresolved from inspected evidence |
| 28470 | NigeriaPropertyCentre | `TERRACED` | Title: `Luxury 3 Bedroom Duplex`; excerpt describes a duplex | `DUPLEX`; attachment unresolved from inspected evidence |
| 28479 | NigeriaPropertyCentre | `SELF_CONTAIN_(SINGLE` | Title: `Gorgeous One Bedroom Studio Apartment`; description explicitly says studio apartment | `STUDIO` based on explicit advertised form; bedroom/layout consistency needs separate review |
| 28298 | NigeriaPropertyCentre | `RESIDENTIAL` | Title: `Residential Land, 400SQM`; description explicitly offers land | `LAND`, advertised land use `RESIDENTIAL` |
| 28397 | NigeriaPropertyCentre | `COMMERCIAL` | Title: `3,000 SQM Commercial Land`; description offers land for lease | `LAND`, advertised land use `COMMERCIAL` |
| 26781 | NigeriaPropertyCentre | `HOTEL_/_GUEST` | Title and description explicitly offer a 21-room hotel for lease | `HOTEL`; distinguish an entire hotel from a short-let apartment |
| 22974 | NigeriaPropertyCentre | `FILLING` | Title and description explicitly identify a gas plant | `UNSUPPORTED`, type NULL; gas plant is not automatically a filling station |
| 28299 | NigeriaPropertyCentre | `MIXED-USE` | Title says terrace duplex; description discusses plot sizes and land title | `AMBIGUOUS`, type NULL pending asset-context review |
| 28228 | NigeriaPropertyCentre | `BLOCK_OF` | Title advertises an individual two-bedroom apartment; excerpt discusses a development | Review full evidence for asset scope; do not certify an entire block from this label |
| 28457 | NigeriaPropertyCentre | `HOUSE` | Title and excerpt advertise a four-bedroom private compound without a clear house form | Review the full evidence before certifying `HOUSE`; bedrooms alone cannot establish it |

For the last two rows, no final status is claimed from the limited excerpt.
If full saved evidence is still insufficient or contradictory, use the matching
unresolved state rather than carrying the old label forward as verified.

## Limits and next step

This audit establishes vocabulary drift and reproducible failure modes. It does
not estimate the new classifier's coverage or accuracy, prove every legacy label
wrong, or reconstruct lost raw portal labels. The local CSV export is older than
the live database and was not used as the migration source.

The next implementation step is the shared classifier and additive storage
contract in the proposal. Before an apply run, produce a full dry-run transition
report, including unchanged verified rows, corrections, broad classifications,
unresolved states, and coverage by portal and lifecycle status. Keep database
classification callers and external consumers in the migration inventory.
