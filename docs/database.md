# Finding your way around the database

Start with the research readers. The remaining objects make collection, evidence,
review, history and recovery work; they are not competing versions of the same
property list. PostgreSQL schemas are namespaces, and views are saved queries.
Adding a view does not duplicate the stored rows.

Dependent applications currently use `raw_data.scraped_listings`,
`raw_data.listing_history`, `raw_data.geocode_cache` and `raw_data.scrape_runs`.
The deployed [storage split](storage-layout.md) preserves all four locally and
remotely, while full audit/recovery tables and research views live locally.
The dictionary below describes the **complete local schema**. Supabase retains
the four application tables, two vocabulary support tables and the small
`ops.shared_publication_state` checkpoint. See the
[handoff](storage-handoff-2026-11-19.md) for locations, access and verified results.

Before migration 014, the entry points are `raw_data.property_research_current`
and `raw_data.property_review_queue`. Migration 014 adds three consumer views in
`research`, describes the operational objects with database comments, and leaves
the 17 physical tables in place. It does not grant anonymous access or move data.

## The everyday readers

| Object | What you get |
| --- | --- |
| `research.properties` | One row per portal listing: current interpretations, retained stored rooms, source text, pricing and location |
| `research.review_queue` | Classification, offer, quantity and room questions, with flags and next actions |
| `research.room_count_coverage` | Separate bedroom/bathroom evidence coverage by source, category, lifecycle and status |
| `research.area_measurements` (015) | Individual current size claims, including held evidence and land/floor/scope distinctions |

The properties view preserves the `property-research-v2` fields and adds useful
source/location fields. `stored_bedrooms` and `stored_bathrooms` are available even
if their evidence is unverified or stale. The per-dwelling fields are supported
interpretations and may therefore be NULL while a retained stored number exists.
That is deliberate: consumers choose which representation fits their study.

`neighbourhood_normalised` is a boolean flag. Coordinates are generally for a
neighbourhood/city lookup, not a verified parcel. One listing is not necessarily
one physical property; several portals can advertise the same property.

## Current source state

| Physical table | Why it exists |
| --- | --- |
| `raw_data.scraped_listings` | Latest state for `(source, external_id)`: source text, pricing, classification, stored fields and evidence summaries |
| `raw_data.geocode_cache` | Reusable neighbourhood/city coordinates |
| `raw_data.scrape_runs` | Per-portal operational run results and timings |

Read `scraped_listings` when investigating what was saved or why a derived value
looks wrong. Use the research reader for normal analysis rather than reimplementing
classification and evidence rules in each application.

## Vocabulary and classification history

| Physical table | Why it exists |
| --- | --- |
| `property_type_versions` | Registered vocabulary versions |
| `property_type_vocabulary` | Allowed forms and aggregation/facet defaults by version |
| `property_classification_history` | Before/after classification decisions and reversal ownership |

These tables are in `raw_data`. Vocabulary rows define allowed outputs; they do
not mean a source advert actually establishes that form. The classification status
and evidence on each listing answer that separate question.

## Quantity claims and their decisions

| Physical table in `raw_data` | Why it exists |
| --- | --- |
| `property_count_assessments` | Source-bound extraction snapshots, rule fingerprints and outstanding questions |
| `property_count_observations` | Individual entity/relationship quantities, bounds, parents, offers and evidence |
| `property_count_decisions` | Append-only ACCEPT, HOLD, REJECT and REVOKE actions |

The split lets us retain a literal claim without accepting its interpretation.
A building containing four flats is not four buildings, and four units available
is not proof that one price buys all four. A reversal can change acceptance while
preserving the original observation and who made the decision.

## Shared fact history

| Physical table in `raw_data` | Why it exists |
| --- | --- |
| `property_fact_assessments` | Feature/offer, room and area assessments, distinguished by `rule_version` |
| `property_fact_revocations` | Append-only assessment retractions |

Rooms reuse this history rather than adding another set of physical audit tables.
Do not select the latest fact row indiscriminately: a later room assessment is
not a replacement for a feature assessment. Use the appropriate current view.

## Lifecycle, pricing and controlled operations

| Physical table in `raw_data` | Why it exists |
| --- | --- |
| `listing_history` | Lifecycle and pricing events, including non-comparable context changes |
| `rental_pricing_backfills` | Audited pricing-metadata repairs and reversals |
| `property_classification_operations` | Frozen manifests for classification-only repairs/reversals |
| `property_classification_receipts` | Per-listing classification-operation outcomes |
| `property_unification_runs` | Manifests for unified repairs, room repairs and reversals; inspect operation kind |
| `property_unification_receipts` | Durable per-listing results for those operations |

Manifests describe the exact operation. Receipts tell a resumed run which records
already finished. History explains what changed. None should be treated as another
current inventory to join without considering its one-to-many relationship.

Removing receipts can make completed work appear pending. Removing history destroys
provenance and can disable safe reversals. Retention and archiving need an explicit
policy, not an attempt to make the schema browser look shorter.

## Existing current and coverage views

| View in `raw_data` | What it means |
| --- | --- |
| `property_research_current` | Room-aware consumer contract backing the research properties reader |
| `property_review_queue` | Outstanding questions and explicit room review flags |
| `current_property_counts` | Accepted, unrevoked quantity claims still applicable to saved source |
| `current_property_facts` | Applicable feature/offer assessment |
| `current_property_rooms` | Applicable room assessment; it can explicitly retain unverified numbers |
| `current_property_areas` (015) | Applicable area assessment matching both saved source and stored area values |
| `property_classification_coverage` | Classification coverage by portal and status |
| `comparable_rental_prices` | Quotes meeting the existing currency/cadence/basis criteria |
| `rental_price_summary` | Grouped current comparable rental quotes |
| `rental_pricing_coverage` | Pricing context completeness, including unresolved cases |

Freshness here means the assessment applies to the saved source, not that the page
was fetched recently or the property was independently inspected. Inspect source
age, field statuses and outstanding flags separately.

## Queries worth keeping

Measure evidence support with honest denominators:

```sql
SELECT source, field, status, sum(listings) AS listings
FROM research.room_count_coverage
WHERE property_category = 'RESIDENTIAL' AND listing_status = 'ACTIVE'
GROUP BY source, field, status
ORDER BY source, field, status;
```

Find exceptional counts before working through ordinary evidence gaps:

```sql
SELECT listing_id, source, url, bedrooms_status, bathrooms_status,
       room_review_flags, next_action
FROM research.review_queue
WHERE jsonb_array_length(room_review_flags) > 0
ORDER BY room_review_priority NULLS LAST, listing_id;
```

Read the database's own dictionary:

```sql
SELECT n.nspname AS schema_name, c.relname AS object_name,
       c.relkind, obj_description(c.oid) AS explanation
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('raw_data', 'research') AND c.relkind IN ('r','v','m')
ORDER BY n.nspname, c.relkind, c.relname;
```

For historical decisions, start with one listing ID and the relevant history kind.
Do not join every count/feature/history row into the research reader and assume
the expanded result is still one row per listing.

## Access and future organization

The research views use `security_invoker=true`: the calling role still needs its
underlying privileges. Creating the schema does not grant anonymous users access,
expose it through a hosted API automatically, or justify sharing an owner credential
with downstream applications. Give dependent applications an appropriately scoped
reader role and configure schema exposure deliberately if they use an API.

The first cleanup is a small front door, database comments and this dictionary.
Moving evidence and operations into `audit`/`ops` namespaces can follow a dependency
inventory covering Python SQL, views, migrations, grants, repair scripts and external
consumers. A schema move does not reduce table size or fix duplicate physical ads.

Numbered migrations currently replay. Migration 014 preserves later-appended
consumer columns rather than recreating an older shape. A checksummed migration
ledger is a separate change that must cover all runners consistently.

## Working with sizes (migration 015)

```sql
SELECT listing_id, supported_floor_area_sqm, floor_area_status,
       supported_land_area_sqm, land_area_status, area_evidence
FROM research.properties
WHERE listing_status = 'ACTIVE';
```

The supported columns require a current assessment and a KNOWN final field status.
The stored columns preserve prior numbers even when unsupported. Floor and land
are different measures; do not add them. A site size for an apartment is not the
apartment's floor area. Individual claim rows can be usable while the final field
is ambiguous because another claim disagrees. Exact conversions remain in claim
JSON; scalar storage rounds to two decimal places. These are advertised claims,
not surveyed measurements.

## Storage maintenance and retention

On 19 November 2026, production occupied 583,765,139 bytes (583.8 MB decimal).
The largest consumers were shared fact assessments (207 MB), current listings
(127 MB) and classification history (109 MB). The evidence and audit histories
added during the data-quality work account for much of the growth. Research views
are saved queries and do not duplicate those stored rows.

A compressed backup of `raw_data`, `research` and `market` was taken before
maintenance. Ten large tables and their indexes were physically compacted.
Every compacted table retained exactly the same row count and logical-content
hash. Database size fell to 547,040,403 bytes (547.0 MB): **36.7 MB reclaimed**,
with no listing, history or receipt rows deleted. The local hourly timer was
paused during maintenance and restored afterward.

This still exceeds the free allowance. The remaining space is predominantly
live data; removing tables merely to shorten the schema browser would discard
evidence. Disposable compression rehearsals did not produce useful additional
savings, so those settings were not applied to production.

An unapplied retention proposal identifies 39,696 superseded fact assessments
from before the verified cutover: 10,399 feature/offer, 21,367 room and 7,930 area
assessments. Their stored JSON payload totals approximately 41.2 MB; reclaimable
physical space also depends on row/index overhead and subsequent compaction.
The proposal excludes every currently applicable assessment, the latest per
listing/rule family and every assessment referenced by a revocation. It preserves all
listings, original values, classification and lifecycle history, manifests and
receipts. Nothing in this cohort has been deleted.

Archiving that cohort would move older derivation history out of online SQL.
Historical inspection or rollback reconstruction would then require the cold
backup. That is a retention decision requiring approval, followed by a reviewed,
scoped archive operation with current-reader protection and verified restoration.
Append-only protections must not be disabled ad hoc to satisfy a storage quota.

Private measurements, backup checksums, restore checks and the exact candidate
IDs are under `.local/storage/`. They do not belong in source control. Continue
measuring relation/index sizes and growth after normal runs; a one-time cleanup
does not cap future history growth. PostgreSQL compaction can temporarily lock a
table, so coordinate scheduled writers and use bounded lock waits. See the
[Supabase storage guide](https://supabase.com/docs/guides/platform/database-size).

## Local publication control

These objects were added during the local/shared storage deployment. They do not
represent another set of scraped properties.

| Object | Location and purpose |
| --- | --- |
| `ops.local_archive_identity` | Local singleton UUID checked by collectors, backups and publisher |
| `ops.publisher_state` | Local last-acknowledged publication UUID and four-table manifest |
| `ops.shared_publications` | Local READY/PUBLISHED journal; links each UUID to its immutable payload directory and expected predecessor |
| `publication_cache.scraped_listings`, `listing_history`, `geocode_cache`, `scrape_runs` | Local exact copy of the last published rows, independent of newer working state |
| `ops.shared_publication_state` | Remote singleton archive/publication UUID, manifest and publication timestamp |

The complete local database has the original 18 physical tables (17 in `raw_data`,
one legacy `market` table), four cache tables and three local control tables. The
remote store keeps six physical `raw_data` tables and its single checkpoint table.
See [local-publication.md](local-publication.md) for transaction/retry behavior.
