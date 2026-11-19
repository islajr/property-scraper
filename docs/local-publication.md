# Running the local archive and shared publisher

This is the runtime contract for the local/shared implementation. Deployment and
verified sizes are recorded separately in the operational handoff. The
[storage layout](storage-layout.md) explains the four-table consumer contract.

`DATABASE_URL` selects the complete working archive. `SHARED_DATABASE_URL` selects
Supabase's published dataset. A collector or full-schema migration checks the
archive identity before operating in `local-shared` mode. A database marked as a
published shared store rejects the full writer even in legacy mode. Cloud jobs now
require a reachable `ARCHIVE_DATABASE_URL` and matching archive ID; old Supabase
credentials are not a fallback collection target. Keep those workflows disabled
until a durable cloud-accessible archive exists.

## Protected configuration

These are configuration names, not credentials or runnable placeholder values:

| Setting | Meaning |
| --- | --- |
| `PROPERTY_SCRAPER_STORAGE_MODE=local-shared` | Enable identity-checked archive writes |
| `DATABASE_URL` | Permanent local working database connection |
| `SHARED_DATABASE_URL` | Published Supabase connection, reserved for publication |
| `ARCHIVE_DATABASE_ID` | UUID registered in the verified local seed |
| `ARCHIVE_ROOT` | Mounted ext4 archive root containing `postgres/` and the file archive |
| `ARCHIVE_IMAGE` | The preallocated image file on the Windows volume |
| `ARCHIVE_FILESYSTEM_UUID` | Expected inner ext4 UUID; prevents fallback to another volume |
| `ARCHIVE_BACKUP_COPY` | Independent backup directory on another filesystem |

Keep `.env` private. Never print its values into reports or paste database URLs
into tickets. Run the commands below from the repository root using its virtualenv.

The mount helper uses the desktop disk service, reuses an existing image mapping,
and checks the filesystem UUID and mount point. Missing media or authorization
causes a visible failure; it does not initialize an empty replacement database.
Stop the archive service cleanly before unmounting its volume or booting Windows.
The image preserves the host partition's layout.

## Publication

After a consistent, verified full seed, initialize its archive identity locally.
The seed procedure records that UUID; it is not a new UUID for each run or restore.
Then bootstrap only when the local and shared copies of all four tables match:

```bash
python -m scripts.publish_shared_data bootstrap
python -m scripts.publish_shared_data publish
```

Bootstrap adds a small shared checkpoint and seeds the local published cache. It
never repairs a mismatch by overwriting shared rows. Subsequent publications use
changed-row CSV deltas, including exact decimal, JSON, NULL and timestamp values.
All four shared tables keep their existing names, columns, primary keys and IDs.
Serial sequence high-water marks are advanced, never reset backward.

Local `publication_cache` tables preserve exactly the last published four-table
state, independently of newer local working rows. `ops.shared_publications` retains
READY/PUBLISHED manifests, immutable payload references and acknowledgement times.
The payload directory under `published/<UUID>/` retains the full baseline or delta
and its SHA-256 checksums. Source and staged SQL content fingerprints use SHA-256
with normalized UTC/date/float formatting. A hash identifies data; retained payloads
and the database backup make it reconstructable.

The shared `ops.shared_publication_state` contains one current archive/publication
UUID, manifest and publication time. It is not a cloud audit ledger. Publication
locks out concurrent writers while allowing ordinary readers, checks the previous
revision and actual shared contents, applies deltas and updates the checkpoint in
one transaction. The local acknowledgement updates the published cache afterward.

If the process stops after the shared commit, the next run recognizes its UUID
and contents and finishes the local acknowledgement. An unreachable shared server
leaves durable READY work locally. A conflicting remote edit or stale local restore
stops publication instead of overwriting newer shared data. Shared row deletion is
not supported by this publisher; removal remains a listing status/event.

Schema or vocabulary changes need explicit shared/cache migration before publishing
rows that use them. The publisher refuses incompatible columns or failed constraints.
It does not silently omit new fields.

## Services and access

`python -m scripts.install_archive_services` writes per-user units and reloads the
user manager; it does not activate them. The cutover procedure activates them only
after seed, bootstrap and backup verification:

- `property-scraper-archive.service`: mount guard and permanent PostgreSQL server.
- `property-scraper-publisher.timer`: fifteen-minute publication/retry cadence.
- `property-scraper-backup.timer`: daily full backup at 04:30 in the host timezone.
- The existing health service gains a dependency on the archive service. Its timer
  keeps its prior cadence. Successful local `run.sh` collection also attempts publication.

Inspect them with `systemctl --user status <unit>` and
`journalctl --user -u <service>`. SQL clients connect locally for full research and
recovery; dependent applications keep their existing Supabase table access.

Useful publication checks are:

```sql
-- Local connection.
SELECT id, previous_id, status, created_at, acknowledged_at
FROM ops.shared_publications ORDER BY created_at DESC LIMIT 20;
SELECT publication_id FROM ops.publisher_state;

-- Shared connection.
SELECT archive_id, publication_id, published_at
FROM ops.shared_publication_state;
```

A local success is not proof of successful publication. Collection remains committed
when publication fails; the separate publisher service reports/retries that failure.
The last shared publication time is the freshness signal for dependent readers.

## Backups and recovery

```bash
python -m scripts.backup_local_archive
```

The backup includes all user schemas in the local database, including the shared
four, audits, published cache and journal. It checks the archive identity, validates
the dump catalog, copies the dump to an independent filesystem and verifies SHA-256.
Committed publication directories are mirrored there too. The routine retains the
latest three `archive-*.dump` files on each side; it does not delete the original
seed backup, historical evidence or publication chain.

Full restoration is tested at cutover. Keep repeating restore drills. Daily backups
leave a recovery window: evidence collected after the last independent backup can
be lost if the archive volume fails. Reduce that window with more frequent or
additional durable backup storage if required. The shared tables are another copy
of published business data, not a replacement for the full local evidence archive.

Restore into a separate local database first, using a compatible PostgreSQL version
and protected publication files. Compare table content, IDs, constraints and current
readers before changing the working connection. Keep the archive UUID from the
restored backup. Database-specific `xmin` values and historical target fingerprints
are not portable recovery tokens; create new guarded local repair plans.

A backup older than the shared publication is deliberately rejected for new writes.
Restore a newer verified backup, or prepare a reviewed reconciliation against a
fresh shared snapshot in a scratch database. Do not clear the checkpoint to force
publication. The initial implementation detects that conflict; it does not invent
an automatic merge or rewrite lost audit history.

The independent archive backup is separate from private connection configuration.
Recover credentials through their protected configuration/secret store, not a
public manifest. Preserve the database seed reports and archive-instance metadata.
