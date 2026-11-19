# Storage handoff: 19 November 2026

The scraper now works against a complete local PostgreSQL database. Supabase is
the shared publication copy. Other projects can keep using their existing four
tables; the full audit history stays available locally for investigation and recovery.

This was a storage move. It did not guess bedrooms, bathrooms, areas or property
types, drop old adverts, trim price history or change listing IDs.

## What was checked

The fresh seed matched all 18 original tables across `raw_data` and `market` by
row count and normalized logical content fingerprints. The four research views
were restored too. After initializing publication, a new full backup was copied
to the Linux filesystem and restored into a separate database. All **25 tables**
matched, including the four published-state cache tables and three local operations
tables. `research.properties` returned **28,955 distinct listings**, all with current
contracts. The disposable verification database was removed after checking it.

The four shared tables were left in place with these cutover counts:

| Table | Rows |
| --- | ---: |
| `raw_data.scraped_listings` | 28,955 |
| `raw_data.listing_history` | 56,798 |
| `raw_data.geocode_cache` | 354 |
| `raw_data.scrape_runs` | 252 |

Before retirement, every original table matched the restored backup and live local
archive again under remote write locks. Twelve explicitly named tables and ten
dependent views were removed remotely using `RESTRICT`; the full shared-table
content manifest was unchanged afterward. The eleven audit/repair tables are listed
in [the storage layout](storage-layout.md#the-complete-local-dataset); the twelfth
is legacy `market.neighbourhood_snapshots`. Their local copies are preserved.
Other applications' schemas were left alone. The two small vocabulary tables remain
remotely because shared listing foreign keys reference them.

Measured database size changed from **547,073,171 bytes
(547.1 MB)** to **143,371,411 bytes
(143.4 MB)**. This is `pg_database_size` at cutover, not a promise
that the provider's dashboard updates immediately or that subsequent growth stops.

## Where the data actually lives

| Location | What lives there and how to use it |
| --- | --- |
| `/run/media/isla-jr/FED0C720D0C6DE51/property-scraper/archive.ext4` | Preallocated 12 GiB ext4 image on the existing Windows partition. The physical partition was not reformatted. Do not edit, move or delete the image while mounted. |
| `/run/media/isla-jr/ps-archive/postgres/` | Permanent PostgreSQL data directory. Use SQL, never edit files here. The database is `property_scraper_archive`. |
| `/run/media/isla-jr/ps-archive/backups/` | Initial seed, full archive dumps, SHA-256 sidecars, seed/restore proofs and archive identity report. |
| `/run/media/isla-jr/ps-archive/published/<UUID>/` | Immutable baseline/delta CSV payloads and manifests. Join UUID to local `ops.shared_publications.id` and the remote checkpoint. |
| `/run/media/isla-jr/ps-archive/legacy-artifacts/` | Copies of the pre-cutover `.local/room-counts`, `.local/areas` and `.local/storage` evidence/reports, preserving filenames and historical context. |
| `/run/media/isla-jr/ps-archive/repair-artifacts/` | Deployment proofs, helper scripts and archived service definitions. Future frozen review/repair reports belong here with their operation UUID. |
| `.local/storage/archive-backups/` in the repository | Independent Linux-filesystem copies of daily full database dumps and published payloads. Three daily dumps retained on each filesystem; publication directories retained. |
| `.local/room-counts/`, `.local/areas/`, `.local/storage/` | Existing local observations, worksheets and operation reports. Originals were retained as well as copied into the image. Keep historical plans as evidence; their old target fingerprints are not replayable against the new local database. |
| Supabase | Complete four-table shared dataset, two vocabulary support tables, bounded `ops.shared_publication_state`, plus lightweight views requiring only shared tables. |

The independent backup is on another filesystem but the same machine. It protects
against loss of the Windows volume, not loss of the entire laptop. A second-device
or encrypted off-machine copy remains a useful next step. Automated backup covers
the database and publication payloads. The preserved legacy file artifacts exist
on both filesystems; newly created standalone observation/repair files must also
be copied independently. Do not assume a database dump includes arbitrary files.

## Connecting without mixing the copies

Protected root `.env` now has local `DATABASE_URL`, remote `SHARED_DATABASE_URL`,
archive UUID, image/root/UUID settings and the independent backup path. The prior
configuration is retained privately at `.local/storage/pre-local-switch.env`.
Neither file belongs in Git. Remote credentials are unchanged and are never printed
in the committed reports.

The local PostgreSQL server accepts the current Linux user's peer-authenticated
UNIX socket, **not TCP connections**. A local SQL client can use:

```bash
psql 'postgresql:///property_scraper_archive?host=/home/isla-jr/Documents/se-workspace/property-scraper/.local/run/postgres&port=55440'
```

Use this connection for full `research.*` readers, classifications, quantity/fact
audits, previews and repairs. For other applications, keep their existing Supabase
connection and four-table reads. `research.*` now needs the local archive; those
views depended on the heavy evidence tables and are not published remotely.
Listing IDs and history event IDs are identical in both copies. Audit run UUIDs,
scrape-run IDs and publication UUIDs are distinct identifiers; do not join them
merely because each is called a run or batch.

`publication_cache` stores the last published rows, while local `raw_data` may be
newer. `ops.shared_publications` records local READY/PUBLISHED batches and frozen
manifests. The remote checkpoint has one current publication UUID and manifest.
For exact reconstruction, restore a full backup separately and use its retained
publication payloads/checkpoints. A manifest hash alone is not the data.

## What runs automatically

- `property-scraper-archive.service`: persistent PostgreSQL, with image/mount UUID validation before startup.
- `property-scraper-publisher.timer`: retry publication every fifteen minutes. Normal successful `run.sh` collection also attempts publication.
- `property-scraper-backup.timer`: full backup daily at **04:30 local time**; three daily dumps on each filesystem.
- `scraper-health.timer`: restored to its pre-cutover hourly schedule, now requiring the archive service.
- GitHub discovery and health workflows: remain manually disabled. CI remains enabled and passed **786 tests**. A laptop UNIX socket is not reachable from a GitHub runner.

These are user services. On this machine lingering is disabled, so they start with
the user's session rather than guaranteeing unattended startup before login. If the
volume is unavailable, startup fails visibly rather than creating an empty archive.
When the machine or publisher is offline, Supabase remains readable at the last
successful publication. Check the checkpoint time; freshness does not advance by itself.

```bash
systemctl --user status property-scraper-archive.service
systemctl --user list-timers 'property-scraper-*' scraper-health.timer
journalctl --user -u property-scraper-publisher.service -n 30
journalctl --user -u property-scraper-backup.service -n 30
```

See [the operator guide](local-publication.md) before stopping/unmounting or restoring.
A daily backup can lose up to a day's unpublished/local-only work after storage
loss. Published payloads are mirrored during backup, not synchronously every fifteen
minutes. Shorten that window or add independent storage if the recovery requirement
changes. Old restored checkpoints deliberately cannot overwrite newer shared data.

## Verification records and next maintenance

The complete independent backup used for cutover was `archive-20261119T154748Z.dump`;
its SHA-256 is `fec0e908a128dbb42ff32841da1f5de32eb48d6c13643b46aaac327550e80d29`. Machine-readable proof files are
`.local/storage/permanent-archive.json`, `archive-restore-proof.json`,
`shared-retirement.json` and `migration-complete.json`. The retirement report records
the exact archived tables, removed views and before/after shared manifests. Copies
of the principal proofs and private cutover helpers live under archive repair artifacts.
Do not commit credentials or database dumps.

Keep watching backup failures, publisher conflicts/lag, free space on both volumes
and remote growth. New schema/vocabulary changes need an explicit shared migration
and local cache migration before publication. Full `schema/*.sql` replay is for
the working archive only. Database identity guards reject collectors/full migrations
pointed at the published store; they are not a replacement for scoped reader roles.

The next useful improvements are a checksummed migration ledger, a scheduled
restore drill, an independent-device backup, and a deliberate contract for any
new downstream research fields. These can build on the preserved local evidence
without filling the shared database with another full audit copy.
