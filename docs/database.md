# Finding your way around the database

Start with the research readers. The remaining objects make collection, evidence,
review, history and recovery work; they are not 17 competing versions of the same
property list. PostgreSQL schemas are namespaces, and views are saved queries.
Adding a view does not duplicate the stored rows.

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
| `property_fact_assessments` | Feature/offer and room assessments, distinguished by `rule_version` |
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
