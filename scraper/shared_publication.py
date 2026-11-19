"""Durable local snapshots/deltas and compare-and-swap publication of four tables."""
import gzip
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

TABLES = {'scraped_listings': ('id',), 'geocode_cache': ('neighbourhood', 'city'),
          'scrape_runs': ('id',), 'listing_history': ('id',)}
VERSION = 'shared-publication-v1'


class PublicationError(RuntimeError):
    pass


def assert_archive(conn, expected):
    if not expected:
        raise PublicationError('Archive identity must be configured')
    expected = str(UUID(str(expected)))
    try:
        with conn.cursor() as q:
            q.execute('SELECT archive_id::text FROM ops.local_archive_identity WHERE singleton')
            row = q.fetchone()
    except psycopg2.errors.UndefinedTable:
        conn.rollback()
        raise PublicationError('Target is not an initialized local archive') from None
    if not row or row[0] != expected:
        raise PublicationError('Archive identity differs; refuse full-schema writes')


def assert_working_target(conn, expected=None, require_archive=False):
    with conn.cursor() as q:
        q.execute("SELECT to_regclass('ops.shared_publication_state') IS NOT NULL")
        if q.fetchone()[0] is True:
            raise PublicationError('Published shared store refuses full-schema/collector writes')
    if require_archive:
        assert_archive(conn, expected)


def initialize_local(conn, archive_id):
    archive_id = str(UUID(str(archive_id)))
    with conn.cursor() as q:
        q.execute('''CREATE SCHEMA IF NOT EXISTS ops;
          CREATE TABLE IF NOT EXISTS ops.local_archive_identity(
            singleton boolean PRIMARY KEY CHECK(singleton),archive_id uuid NOT NULL);
          CREATE TABLE IF NOT EXISTS ops.publisher_state(
            singleton boolean PRIMARY KEY CHECK(singleton),publication_id uuid,
            manifest jsonb NOT NULL);
          CREATE TABLE IF NOT EXISTS ops.shared_publications(
            id uuid PRIMARY KEY,previous_id uuid,manifest jsonb NOT NULL,
            status text NOT NULL CHECK(status IN ('READY','PUBLISHED')),
            created_at timestamptz NOT NULL DEFAULT now(),acknowledged_at timestamptz);
          CREATE SCHEMA IF NOT EXISTS publication_cache''')
        q.execute('INSERT INTO ops.local_archive_identity VALUES(true,%s) ON CONFLICT DO NOTHING', (archive_id,))
        assert_archive(conn, archive_id)
        for table, pk in TABLES.items():
            q.execute(sql.SQL('CREATE TABLE IF NOT EXISTS publication_cache.{} (LIKE raw_data.{})').format(sql.Identifier(table), sql.Identifier(table)))
            q.execute('SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=%s::regclass AND contype=\'p\')', ('publication_cache.'+table,))
            if not q.fetchone()[0]:
                q.execute(sql.SQL('ALTER TABLE publication_cache.{} ADD PRIMARY KEY ({})').format(sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, pk))))
    conn.commit()


def _configure(conn):
    with conn.cursor() as q:
        q.execute("SET TIME ZONE 'UTC'")
        q.execute("SET datestyle='ISO, YMD'")
        q.execute("SET extra_float_digits=3")
        q.execute("SET statement_timeout='180s'")
        q.execute("SET lock_timeout='3s'")
    conn.commit()


def _columns(conn, schema, table):
    with conn.cursor() as q:
        q.execute('''SELECT attname,format_type(atttypid,atttypmod),attnotnull
          FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum''', (schema+'.'+table,))
        return [list(r) for r in q]


def _digest(conn, query):
    with conn.cursor() as q:
        q.execute(sql.SQL('''SELECT count(*),encode(sha256(convert_to(string_agg(h,'' ORDER BY h COLLATE "C"),'UTF8')),'hex')
          FROM (SELECT encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),'hex') h FROM ({}) t) hashes''').format(query))
        rows, digest = q.fetchone()
        return dict(rows=rows, digest=digest)


def manifest(conn, schema='raw_data'):
    return {t: dict(columns=_columns(conn, schema, t), **_digest(conn, sql.SQL('SELECT * FROM {}.{}').format(sql.Identifier(schema), sql.Identifier(t)))) for t in TABLES}


def _fsync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Publisher:
    def __init__(self, local_url, shared_url, archive_id, root):
        self.local_url, self.shared_url = local_url, shared_url
        self.archive_id, self.root = str(UUID(str(archive_id))), Path(root).resolve()
        if not (self.root/'postgres/PG_VERSION').is_file():
            raise PublicationError('Permanent archive storage is unavailable')
        self.local = psycopg2.connect(local_url, connect_timeout=15, keepalives=1, keepalives_idle=15, keepalives_interval=5, keepalives_count=3, tcp_user_timeout=30000)
        self.remote = None
        _configure(self.local)
        assert_archive(self.local, self.archive_id)
        self.local.rollback()
        with self.local.cursor() as q:
            q.execute("SELECT pg_try_advisory_lock(hashtextextended('shared-publication-v1',0))")
            if not q.fetchone()[0]:
                self.local.close()
                raise PublicationError('Another publisher is active')
        self.local.commit()

    def close(self):
        if self.remote:
            self.remote.close()
        self.local.close()

    def capture(self, bootstrap=False):
        self.local.set_session(isolation_level='REPEATABLE READ')
        try:
            with self.local.cursor() as q:
                q.execute("SELECT id::text,manifest FROM ops.shared_publications WHERE status='READY' ORDER BY created_at,id LIMIT 1")
                pending = q.fetchone()
                if pending:
                    self.local.rollback()
                    return pending
                q.execute('SELECT publication_id::text,manifest FROM ops.publisher_state WHERE singleton')
                prior = q.fetchone()
            if bootstrap == bool(prior):
                raise PublicationError('Bootstrap state differs; use the matching publication phase')
            current = manifest(self.local)
            if prior and current == prior[1]:
                self.local.rollback()
                return None
            if prior and manifest(self.local, 'publication_cache') != prior[1]:
                raise PublicationError('Published local cache differs from its checkpoint')
            pid = str(uuid4());directory = self.root/'published'/pid
            directory.mkdir(parents=True, mode=0o700)
            data = dict(version=VERSION, archive_id=self.archive_id, state=current, files={}, bootstrap=bootstrap)
            for table, pk in TABLES.items():
                if _columns(self.local, 'publication_cache', table) != current[table]['columns']:
                    raise PublicationError('Cache schema requires an explicit migration')
                if bootstrap:
                    select = sql.SQL('SELECT s.* FROM raw_data.{} s').format(sql.Identifier(table))
                else:
                    join = sql.SQL(' AND ').join(sql.SQL('s.{}=c.{}').format(sql.Identifier(k), sql.Identifier(k)) for k in pk)
                    with self.local.cursor() as q:
                        q.execute(sql.SQL('SELECT 1 FROM publication_cache.{} c WHERE NOT EXISTS(SELECT 1 FROM raw_data.{} s WHERE {}) LIMIT 1').format(sql.Identifier(table), sql.Identifier(table), join))
                        if q.fetchone():
                            raise PublicationError('Shared row deletion requires an explicit reviewed migration')
                    cols = [r[0] for r in current[table]['columns']]
                    left = sql.SQL(',').join(sql.SQL('s.{}').format(sql.Identifier(k)) for k in cols)
                    right = sql.SQL(',').join(sql.SQL('c.{}').format(sql.Identifier(k)) for k in cols)
                    select = sql.SQL('SELECT s.* FROM raw_data.{} s LEFT JOIN publication_cache.{} c ON {} WHERE c.{} IS NULL OR ROW({}) IS DISTINCT FROM ROW({})').format(sql.Identifier(table), sql.Identifier(table), join, sql.Identifier(pk[0]), left, right)
                digest = _digest(self.local, select)
                path = directory/(table+'.csv.gz')
                with gzip.open(path, 'wb') as f, self.local.cursor() as q:
                    q.copy_expert(sql.SQL("COPY ({}) TO STDOUT WITH (FORMAT CSV, ENCODING 'UTF8')").format(select).as_string(self.local), f)
                _fsync(path)
                data['files'][table] = dict(**digest, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            p = directory/'manifest.json';p.write_text(json.dumps(data, sort_keys=True)+'\n');_fsync(p);_fsync(directory);_fsync(directory.parent)
            with self.local.cursor() as q:
                q.execute("INSERT INTO ops.shared_publications(id,previous_id,manifest,status) VALUES(%s,%s,%s,'READY')", (pid, prior[0] if prior else None, Json(data)))
            self.local.commit()
            return pid, data
        except Exception:
            self.local.rollback()
            raise

    def _files(self, pid, data):
        if data['version'] != VERSION or data['archive_id'] != self.archive_id or set(data['files']) != set(TABLES):
            raise PublicationError('Publication manifest differs')
        directory = self.root/'published'/str(UUID(pid))
        if json.loads((directory/'manifest.json').read_text()) != data:
            raise PublicationError('Frozen publication manifest changed')
        for table in TABLES:
            if hashlib.sha256((directory/(table+'.csv.gz')).read_bytes()).hexdigest() != data['files'][table]['sha256']:
                raise PublicationError('Frozen publication payload changed')
        return directory

    def _apply(self, conn, schema, directory, data):
        for table, pk in TABLES.items():
            if _columns(conn, schema, table) != data['state'][table]['columns']:
                raise PublicationError('Shared schema differs; explicit migration required')
            stage = 'ps_stage_'+table
            with conn.cursor() as q:
                q.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE {}.{}) ON COMMIT DROP').format(sql.Identifier(stage), sql.Identifier(schema), sql.Identifier(table)))
                with gzip.open(directory/(table+'.csv.gz'), 'rb') as f:
                    q.copy_expert(sql.SQL("COPY {} FROM STDIN WITH (FORMAT CSV, ENCODING 'UTF8')").format(sql.Identifier(stage)).as_string(conn), f)
                q.execute(sql.SQL('ALTER TABLE {} ADD PRIMARY KEY ({})').format(sql.Identifier(stage), sql.SQL(',').join(map(sql.Identifier, pk))))
            actual = _digest(conn, sql.SQL('SELECT * FROM {}').format(sql.Identifier(stage)))
            if actual != {k:data['files'][table][k] for k in ('rows','digest')}:
                raise PublicationError('Staged payload differs from frozen delta')
            cols = [r[0] for r in data['state'][table]['columns']]
            changed = [c for c in cols if c not in pk]
            with conn.cursor() as q:
                q.execute(sql.SQL('INSERT INTO {}.{} AS target ({}) SELECT {} FROM {} WHERE true ON CONFLICT ({}) DO UPDATE SET {} WHERE ROW({}) IS DISTINCT FROM ROW({})').format(
                    sql.Identifier(schema), sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, cols)), sql.SQL(',').join(map(sql.Identifier, cols)), sql.Identifier(stage), sql.SQL(',').join(map(sql.Identifier, pk)),
                    sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(c),sql.Identifier(c)) for c in changed),
                    sql.SQL(',').join(sql.SQL('target.{}').format(sql.Identifier(c)) for c in changed),
                    sql.SQL(',').join(sql.SQL('EXCLUDED.{}').format(sql.Identifier(c)) for c in changed)))
        if manifest(conn, schema) != data['state']:
            raise PublicationError('Published rows do not exactly match the frozen state')

    def _acknowledge(self, pid, data, directory):
        try:
            self._apply(self.local, 'publication_cache', directory, data)
            with self.local.cursor() as q:
                q.execute('INSERT INTO ops.publisher_state VALUES(true,%s,%s) ON CONFLICT(singleton) DO UPDATE SET publication_id=EXCLUDED.publication_id,manifest=EXCLUDED.manifest', (pid, Json(data['state'])))
                q.execute("UPDATE ops.shared_publications SET status='PUBLISHED',acknowledged_at=now() WHERE id=%s", (pid,))
            self.local.commit()
        except Exception:
            self.local.rollback()
            raise

    def publish(self, bootstrap=False):
        item = self.capture(bootstrap)
        if not item:
            return dict(stage='NO_CHANGES')
        pid, data = item;directory = self._files(pid, data)
        self.remote = psycopg2.connect(self.shared_url, connect_timeout=15, keepalives=1, keepalives_idle=15, keepalives_interval=5, keepalives_count=3, tcp_user_timeout=30000)
        _configure(self.remote)
        def identity(conn):
            with conn.cursor() as q:
                q.execute("SELECT current_database(),current_setting('port'),pg_postmaster_start_time()")
                result=q.fetchone()
            conn.rollback()
            return result
        if identity(self.local)==identity(self.remote):
            raise PublicationError('Local and shared targets must differ')
        with self.remote.cursor() as q:
            q.execute("SELECT to_regclass('ops.local_archive_identity')")
            if q.fetchone()[0] is not None:
                raise PublicationError('Shared target is a local archive; refuse publication')
        self.remote.rollback()
        try:
            with self.remote.cursor() as q:
                q.execute("SELECT pg_advisory_xact_lock(hashtextextended('shared-publication-v1',0))")
                for t in TABLES:q.execute(sql.SQL('LOCK TABLE raw_data.{} IN EXCLUSIVE MODE').format(sql.Identifier(t)))
                q.execute('CREATE SCHEMA IF NOT EXISTS ops')
                q.execute('''CREATE TABLE IF NOT EXISTS ops.shared_publication_state(
                    singleton boolean PRIMARY KEY CHECK(singleton),archive_id uuid NOT NULL,
                    publication_id uuid NOT NULL,manifest jsonb NOT NULL,published_at timestamptz NOT NULL DEFAULT now())''')
                q.execute('SELECT archive_id::text,publication_id::text,manifest FROM ops.shared_publication_state WHERE singleton FOR UPDATE');state=q.fetchone()
            actual = manifest(self.remote)
            if state and state[0] != self.archive_id:
                raise PublicationError('Shared target belongs to a different archive')
            if state and state[1] == pid:
                if actual != data['state'] or state[2] != actual:
                    raise PublicationError('Interrupted publication has conflicting remote contents')
                self.remote.rollback()
            else:
                with self.local.cursor() as q:
                    q.execute('SELECT previous_id::text FROM ops.shared_publications WHERE id=%s', (pid,));previous=q.fetchone()[0]
                    q.execute('SELECT manifest FROM ops.publisher_state WHERE singleton');prior=q.fetchone()
                self.local.rollback()
                if data['bootstrap']:
                    if state or previous or actual != data['state']:
                        raise PublicationError('Bootstrap requires identical seeded shared data')
                else:
                    if not state or state[1] != previous or not prior or state[2] != prior[0] or actual != prior[0]:
                        raise PublicationError('Remote revision/content conflict; reconcile before publishing')
                    self._apply(self.remote, 'raw_data', directory, data)
                # Published IDs are explicit. Keep serial high-water marks usable
                # for a later restore, without moving an existing sequence back.
                with self.remote.cursor() as q:
                    for table, pk in TABLES.items():
                        if pk != ('id',):
                            continue
                        q.execute(sql.SQL("SELECT pg_get_serial_sequence(%s,'id'),max(id) FROM raw_data.{}").format(sql.Identifier(table)), ('raw_data.'+table,))
                        sequence, maximum = q.fetchone()
                        if sequence and maximum is not None:
                            q.execute('SELECT last_value FROM pg_sequences WHERE schemaname=%s AND sequencename=(SELECT relname FROM pg_class WHERE oid=%s::regclass)', ('raw_data', sequence))
                            last = q.fetchone()[0]
                            q.execute('SELECT setval(%s::regclass,%s,true)', (sequence, max(last or 1, maximum)))
                with self.remote.cursor() as q:
                    q.execute('INSERT INTO ops.shared_publication_state(singleton,archive_id,publication_id,manifest) VALUES(true,%s,%s,%s) ON CONFLICT(singleton) DO UPDATE SET archive_id=EXCLUDED.archive_id,publication_id=EXCLUDED.publication_id,manifest=EXCLUDED.manifest,published_at=now()', (self.archive_id,pid,Json(data['state'])))
                self.remote.commit()
            self._acknowledge(pid, data, directory)
            return dict(stage='PUBLISHED', publication_id=pid, rows={t:data['files'][t]['rows'] for t in TABLES})
        except Exception:
            self.remote.rollback();self.local.rollback()
            raise
