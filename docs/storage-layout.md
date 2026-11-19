# Where the data lives and how it gets shared

The intended split is straightforward: local PostgreSQL keeps the complete working
dataset and its evidence; Supabase publishes the data other applications need.
We preserve shared data locally too. Supabase will never be the only place holding
a listing, a price event, a geocode result or a run log.

**Status: this is the agreed data boundary and proposed migration contract, not a
completed deployment.** Today the scraper still uses `DATABASE_URL` for its full
database writes. Supabase still contains the audit tables. Local backups have been
restored and checked in disposable databases; a permanent local working database
and publisher have not yet been deployed. The test databases were removed.

## The four tables applications currently share

The confirmed consumer contract is below. The actual run-log name is `scrape_runs`,
not `scraped_runs`. Keep the existing `raw_data` names and all existing columns.

| Table | Local working/archive database | Supabase | What it is useful for |
| --- | --- | --- | --- |
| `raw_data.scraped_listings` | Full current state, published versions and retained observations | Current published listings, including active and removed adverts | Search, classification, room/area analysis, pricing context and current inventory |
| `raw_data.listing_history` | Complete event history and publication records | Complete shared price/lifecycle history | Asking-price changes, listing availability and longitudinal studies |
| `raw_data.geocode_cache` | Complete reusable cache and publication records | Shared cache | Reusing neighbourhood/city coordinates across projects |
| `raw_data.scrape_runs` | Complete logs and publication records | Shared run logs | Collection coverage, failures, timings and freshness monitoring |

This preserves the current shared tables in full. It does not introduce an active-only
filter, silently age out history, omit columns or discard rows because no application
uses them today. Field statuses, raw/source fields, original room/area values and
pricing context stay attached to the shared listing row.

After the 19 November compaction, these four relations occupied **129,441,792 bytes
(129.4 MB decimal), including their indexes and associated storage**. That is their
measured footprint, not a forecast of the whole future Supabase project: system
catalogs, small supporting structures and subsequent growth also need space.

The cloud may retain small supporting tables as well. In particular,
`property_type_versions` and `property_type_vocabulary` support existing listing
foreign keys. Retain referenced vocabulary versions. Publication also needs compact
checkpoint/revision metadata. These are internal supports for the four-table
contract, not another full audit archive. The schema and storage budget for that
metadata must be measured before cutover.

## How the shared records tie together

`scraped_listings.id` is the stable listing key. `(source, external_id)` is its unique
portal identity. Copy existing IDs explicitly when seeding locally and publishing;
do not generate different IDs for the same listing in each database. A portal
listing is not a deduplicated physical-property identity across portals.

`listing_history.listing_id` is a real foreign key to `scraped_listings.id`.
`listing_history.id` identifies the individual event and must also remain stable.
Publish parent listings before their events, in one coherent remote transaction.
Retain removed listings so their history keeps a valid parent. Amounts remain in
**kobo**; retain `old_pricing`, `new_pricing` and `price_comparable` alongside the
amounts. A changed billing period is not automatically a comparable price movement.
An advert removal does not prove a completed sale or rent transaction.

`geocode_cache` uses `(neighbourhood, city)` as its primary key. Listings can be
matched to that pair by name, but there is no listing-to-cache foreign key and some
listings have no matching cache entry. These are generally area centroids, not
verified parcel coordinates. The location-refresh limitations in
[CODEBASE.md](../CODEBASE.md) still apply.

`scrape_runs.id` identifies a run-log row; `source` identifies the portal. There is
currently no per-listing foreign key to this table. Its numeric ID is not a listing
ID, and its aggregate counts do not prove which exact listing changed. Audit UUIDs
are a separate kind of identifier. A future publication ID can correlate a published
batch, but it must not invent a historical relationship that was never recorded.

## The complete local dataset

Local storage retains all four shared tables, all their columns, the full original
audit tables, registered vocabulary versions and preserved legacy datasets. The
shared contract limits what is published, not what is retained for future work.

This migration covers scraper-owned `raw_data`, `research` and preserved `market`
objects. Other applications retain ownership of their own schemas.

| Local data | Connection to the listing or operation | What it is useful for |
| --- | --- | --- |
| `property_classification_history` | `listing_id`; optional operation association through the audit's UUID `run_id` | Explaining an old/new classification and reconstructing earlier decisions |
| `property_classification_operations`, `property_classification_receipts` | Operation `run_id`; receipts also reference `history_id` | Owned classification repairs, resumable work and guarded reversals |
| `property_count_assessments` | `listing_id`, source hash and rule version | Recording the interpretation of units, layouts and offers |
| `property_count_observations`, `property_count_decisions` | Observation `assessment_id`; decision `observation_id` | Retaining literal claims separately from ACCEPT/HOLD/REJECT/REVOKE decisions |
| `property_fact_assessments`, `property_fact_revocations` | Assessment `listing_id` and rule family; revocation `assessment_id` | Feature/offer, room and area evidence, before/after values and retractions |
| `property_unification_runs`, `property_unification_receipts` | Operation `run_id`, with per-listing receipts | Frozen selections, safe resume, completed-work recognition and recovery |
| `rental_pricing_backfills` | `listing_id`, repair UUID and before/after quote metadata | Understanding and reversing pricing-context repairs |
| Original source fields and saved observation artifacts | Portal identity, observation time and source hash | Reassessment, selector investigation and validation against advertised wording |
| Existing `market` snapshots and other preserved legacy data | Their original keys, dates and schema | Historical investigation; old snapshots are not automatically trustworthy comparable-price series |

All tables above remain linked to the same local listing IDs as the shared copy.
Not every classification audit UUID has a classification-operation manifest: normal
discovery/health audits can have their own UUID. Count `parent_key` and `offer_key`
values are scoped claims, not global property IDs to join across adverts.

Use the [database dictionary](database.md) for the existing columns and views.
Local `research.properties`, `research.review_queue`, `research.room_count_coverage`
and `research.area_measurements` remain available for deeper work. Their current
implementations need audit/assessment tables; those full readers do not become
cloud-independent merely because their SQL view names are retained.

Existing title/description/raw fields and saved JSON observations are preserved.
The pipeline does not currently retain a complete HTML archive for every fetch.
Any future HTML/image/snapshot retention must have explicit storage and retention
rules; a successful scrape does not imply that such an archive already exists.

### Files, database storage and published copies

Choose a permanent archive root on the selected volume. The layout below is the
target layout, not a set of directories already provisioned on this machine:

| Location relative to the archive root | Contents and connection to the database |
| --- | --- |
| `postgres/` | Persistent local PostgreSQL storage for all shared tables, full audit tables and the transactional publication journal. Access records through PostgreSQL, not by editing its data files. |
| `backups/` | Consistent compressed database backups, schema/sequence definitions and checksums. A manifest records the dataset/schema version, capture time and event range. Keep an independent backup copy outside this volume. |
| `observations/` | Saved source evidence, keyed by portal identity, capture time and content hash; database evidence/publication records identify the matching artifact. |
| `repair-artifacts/` | Frozen previews, selections, verification reports and historical run artifacts, tied to their run IDs and original database fingerprints. |
| `published/` | Periodic compressed snapshots of all four shared tables and publication manifests. Retain intervening versions through the durable local journal rather than making a full database copy for every batch. |

The publication journal must commit inside the local database transaction; a loose
file queued after that commit is insufficient to guarantee recovery. Files can
hold referenced artifacts and snapshots. A manifest/hash identifies their exact
contents, while the retained payload makes reconstruction possible.

Existing verified backups and reports currently live under ignored
`.local/storage/`; existing verification artifacts also live under
`.local/room-counts/` and `.local/areas/`. Preserve them and their original path/run
context when seeding the permanent archive. They are operational data, not Git
source files. Backup credentials and connection strings do not belong in manifests.

## Accessing the right copy

Connect a SQL client to Supabase for the shared application dataset. After the
local working database is deployed, connect to it for full research, audits and
recovery. Use separate saved connections and appropriately scoped reader roles.
The local database contains the same shared table names, so choosing the connection
is what chooses the dataset. Secrets belong in protected configuration.

These queries work against the shared schema today and the local mirror after seeding:

```sql
-- An advert's lifecycle/pricing events: one listing, potentially many events.
SELECT l.id, l.source, l.external_id, h.id AS event_id,
       h.event_type, h.event_date, h.old_value, h.new_value,
       h.old_pricing, h.new_pricing, h.price_comparable
FROM raw_data.scraped_listings l
JOIN raw_data.listing_history h ON h.listing_id = l.id
WHERE l.id = 123
ORDER BY h.event_date, h.id;

-- Operational collection summaries, separate from listing-level quality.
SELECT id, run_at, source, status, new_listings, updated_listings,
       price_changes, duration_seconds
FROM raw_data.scrape_runs
ORDER BY run_at DESC, id DESC
LIMIT 20;
```

For deeper audit work, use the local connection after cutover:

```sql
SELECT id, run_id, origin, recorded_at, old_classification, new_classification
FROM raw_data.property_classification_history
WHERE listing_id = 123
ORDER BY id;
```

The split does not yet introduce runnable new configuration switches. Today the
application reads `DATABASE_URL`. Implementation must explicitly distinguish the
local working connection from the shared publication connection, rather than
silently changing that variable's meaning for some commands.

## Preserving what was actually published

A local current row can be newer than its shared counterpart while publication is
pending. Retain the published payload/version locally, as well as the newest local
working state. That lets us reconstruct exactly what dependent applications saw.

Each durable local publication record should identify the batch/event, table and
stable key, payload hash, expected remote revision, source/rule versions and status.
Retain enough source/payload data to reproduce the version; a hash alone is not a
backup. Keep the detailed journal locally. Remote metadata needs only bounded
publication checkpoints and the latest revision needed for safe reconciliation.

Commit source observations, derived changes and publication work locally first.
Publish a coherent batch remotely with identity, payload and expected-revision
checks; acknowledge it locally afterward. If the remote commit succeeds but the
local acknowledgement is interrupted, reconcile the remote event/revision before
retrying. Replaying an event must not create duplicate listings or history events.
Conflicting contents under the same event/key require investigation.

The two databases cannot share one ordinary PostgreSQL transaction. The protocol
must handle that interruption explicitly. Dependent readers use Supabase without
contacting the local machine. An offline publisher leaves the previous shared
dataset readable but stops new publication; expose the last successful publication
time instead of implying that stale data is fresh.

## Reconstruction and reconciliation

Preserve immutable archives and reconstruct in a separate local working copy.
Record the source archive and rule versions, preview the proposed changes, and
verify them before publishing a correction. Keep an independent backup copy and
regularly test restoration.

PostgreSQL `xmin` values are database-specific. A restored local row has a different
transaction history from its original remote row. Historical `source_row_version`
and `applied_row_version` values remain evidence of the original operation, not
portable concurrency tokens. Existing frozen production repair artifacts also bind
to the production database fingerprint. Generate new local plans against the local
target; do not disable those guards or replay a production artifact against a clone.

Compare a reviewed local result with the current remote logical revision and
content hash. A mismatch needs reconciliation; an older local restore must not
overwrite a newer shared observation. Corrections need a new local audit and
publication record. Historical quote corrections require explicit review, not a
blanket assumption that today's billing period applied to earlier prices.

## Cutover and operating checklist

1. Choose permanent local storage with room for the database, WAL, backups, a
   reconstruction copy and growth. The project filesystem had only about 1.4 GB
   free when checked on 19 November. Free capacity or select a larger volume before
   activating the local master. Temporary `/tmp` test clusters are not that archive.
2. Pause every writer for a consistent final seed. Restore the full scraper
   dataset and its definitions locally, including all four shared tables, audit
   records and sequence state.
   Verify logical row/content hashes, stable IDs, foreign keys and local readers.
3. Build and test the durable publisher. Adapt discovery, health, reviews, repairs,
   recovery, dashboards and schedules to their intended connections. Existing
   GitHub scraper schedules are disabled; enabling one requires a durable route
   to local archival or an explicitly designed staging service.
4. Separate full local migrations from compact shared migrations. Today `run.sh`
   and cloud wrappers replay the full schema; they must not recreate remote audit
   tables after cleanup. Keep CI databases disposable and isolated from both stores.
5. Rehearse publication, retries, interrupted acknowledgements, conflicting updates,
   missing evidence, restored archives and rollback locally. Check every existing
   column and row of the four-table contract, not only aggregate counts.
6. Verify the permanent local archive and independent backup before removing any
   remote history. Inventory scraper-internal view/FK dependencies too: downstream
   use of four tables does not make the current writer independent of its audits.
7. Remove only explicitly archived remote structures after the new path passes.
   Preserve shared tables in place, their IDs, price/lifecycle history, constraints,
   grants and referenced vocabulary. Avoid schema-wide cascading drops. Compact
   afterward and measure the actual database footprint.
8. Monitor publication lag, failed/conflicting events, local backup health and
   remote growth. A below-300-MB project footprint is a working design budget,
   not a measured guarantee. Future consumers get an explicit shared-contract
   extension built from preserved local data, not an automatic copy of all audits.

The previous narrow proposal to archive 39,696 superseded assessments remains
unapplied. The broader split above is now the preferred direction. Production
history remains online until the archive, replacement writer path and cutover
checks are implemented and verified through incremental PRs to `master`.
