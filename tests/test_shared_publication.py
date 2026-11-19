"""Real commit/copy boundaries in two disposable PostgreSQL databases."""
import os
from uuid import uuid4
import psycopg2
import pytest
from psycopg2 import sql
from scraper.shared_publication import Publisher, PublicationError, initialize_local


@pytest.fixture
def pair(tmp_path):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL required')
    admin = psycopg2.connect(url)
    admin.autocommit = True
    # libpq omits the password from get_dsn_parameters(). Preserve the test
    # URL credentials when connecting to the newly created databases.
    params = psycopg2.extensions.parse_dsn(url)
    params = {k: params[k] for k in ('host', 'port', 'user', 'password') if params.get(k)}
    names = ['pub_local_' + uuid4().hex[:10], 'pub_shared_' + uuid4().hex[:10]]
    conns = []
    try:
        for name in names:
            with admin.cursor() as q:
                q.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
            c = psycopg2.connect(dbname=name, **params)
            conns.append(c)
            with c.cursor() as q:
                q.execute('''CREATE SCHEMA raw_data;
                  CREATE TABLE raw_data.scraped_listings(id bigserial PRIMARY KEY,source text NOT NULL,
                    external_id text NOT NULL,amount numeric(18,2),evidence jsonb,note text,UNIQUE(source,external_id));
                  CREATE TABLE raw_data.listing_history(id bigint PRIMARY KEY,
                    listing_id bigint REFERENCES raw_data.scraped_listings(id),event_type text);
                  CREATE TABLE raw_data.geocode_cache(neighbourhood text,city text,lat double precision,
                    lng double precision,PRIMARY KEY(neighbourhood,city));
                  CREATE TABLE raw_data.scrape_runs(id bigint PRIMARY KEY,status text);
                  INSERT INTO raw_data.scraped_listings VALUES(1,'portal','A',1234567890123456.78,
                    '{"status":"UNVERIFIED","value":null}',E'line one\\n"quoted", text');
                  INSERT INTO raw_data.listing_history VALUES(1,1,'LISTED');
                  INSERT INTO raw_data.geocode_cache VALUES('Lekki','LAGOS',6.472839127893123,3.456789123456789);
                  INSERT INTO raw_data.scrape_runs VALUES(1,'SUCCESS')''')
            c.commit()
        archive = str(uuid4())
        initialize_local(conns[0], archive)
        (tmp_path / 'postgres').mkdir()
        (tmp_path / 'postgres/PG_VERSION').write_text('test')
        urls = [psycopg2.extensions.make_dsn(dbname=name, **params) for name in names]
        yield dict(local=conns[0], remote=conns[1], urls=urls, root=tmp_path, archive=archive)
    finally:
        for c in conns:
            c.close()
        for name in names:
            with admin.cursor() as q:
                q.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH(FORCE)').format(sql.Identifier(name)))
        admin.close()


def publisher(p):
    return Publisher(*p['urls'], p['archive'], p['root'])


def read(c, table):
    c.rollback()
    with c.cursor() as q:
        q.execute('SELECT row_to_json(t)::text FROM raw_data.' + table + ' t ORDER BY id')
        return q.fetchall()


def test_bootstrap_delta_precision_identity_and_completed_retry(pair):
    p = pair
    pub = publisher(p)
    try:
        assert pub.publish(True)['stage'] == 'PUBLISHED'
        assert pub.publish()['stage'] == 'NO_CHANGES'
        with p['local'].cursor() as q:
            q.execute('UPDATE raw_data.scraped_listings SET amount=9876543210123456.79,evidence=%s WHERE id=1',
                      ('{"status":"KNOWN","value":3}',))
            q.execute("INSERT INTO raw_data.scraped_listings VALUES(2,'portal','B',NULL,'{}',NULL)")
            q.execute("INSERT INTO raw_data.listing_history VALUES(2,2,'LISTED')")
        p['local'].commit()
        result = pub.publish()
        assert result['rows']['scraped_listings'] == 2
        assert result['rows']['listing_history'] == 1
        assert read(p['local'], 'scraped_listings') == read(p['remote'], 'scraped_listings')
        assert read(p['local'], 'listing_history') == read(p['remote'], 'listing_history')
        with p['remote'].cursor() as q:
            q.execute("SELECT nextval('raw_data.scraped_listings_id_seq')")
            assert q.fetchone()[0] == 3
        p['remote'].rollback()
        assert pub.publish()['stage'] == 'NO_CHANGES'
    finally:
        pub.close()


def test_remote_commit_before_local_ack_is_reconciled(pair, monkeypatch):
    p = pair
    pub = publisher(p)
    try:
        pub.publish(True)
        with p['local'].cursor() as q:
            q.execute("UPDATE raw_data.scraped_listings SET note='updated' WHERE id=1")
        p['local'].commit()
        original = pub._acknowledge
        def interrupted(*args):
            raise RuntimeError('Simulated lost acknowledgement')
        monkeypatch.setattr(pub, '_acknowledge', interrupted)
        with pytest.raises(RuntimeError):
            pub.publish()
        assert read(p['remote'], 'scraped_listings') == read(p['local'], 'scraped_listings')
        monkeypatch.setattr(pub, '_acknowledge', original)
        assert pub.publish()['stage'] == 'PUBLISHED'
        assert pub.publish()['stage'] == 'NO_CHANGES'
    finally:
        pub.close()


def test_foreign_remote_update_blocks_publication_and_preserves_pending_delta(pair):
    p = pair
    pub = publisher(p)
    try:
        pub.publish(True)
        with p['local'].cursor() as q:
            q.execute("UPDATE raw_data.scraped_listings SET note='local' WHERE id=1")
        p['local'].commit()
        with p['remote'].cursor() as q:
            q.execute("UPDATE raw_data.scraped_listings SET note='remote correction' WHERE id=1")
        p['remote'].commit()
        before = read(p['remote'], 'scraped_listings')
        with pytest.raises(PublicationError, match='conflict'):
            pub.publish()
        assert read(p['remote'], 'scraped_listings') == before
        with p['local'].cursor() as q:
            q.execute("SELECT count(*) FROM ops.shared_publications WHERE status='READY'")
            assert q.fetchone()[0] == 1
        p['local'].rollback()
    finally:
        pub.close()


def test_changed_payload_and_shared_row_deletion_are_rejected(pair):
    p = pair
    pub = publisher(p)
    try:
        pub.publish(True)
        with p['local'].cursor() as q:
            q.execute("UPDATE raw_data.scraped_listings SET note='pending' WHERE id=1")
        p['local'].commit()
        pid, data = pub.capture()
        path = p['root'] / 'published' / pid / 'scraped_listings.csv.gz'
        path.write_bytes(b'changed')
        with pytest.raises(PublicationError, match='payload'):
            pub.publish()
        with p['local'].cursor() as q:
            q.execute('DELETE FROM ops.shared_publications WHERE id=%s', (pid,))
            q.execute('DELETE FROM raw_data.listing_history')
        p['local'].commit()
        with pytest.raises(PublicationError, match='deletion'):
            pub.publish()
    finally:
        pub.close()


def test_remote_transaction_rolls_back_all_shared_changes(pair, monkeypatch):
    p = pair
    pub = publisher(p)
    try:
        pub.publish(True)
        before = read(p['remote'], 'scraped_listings')
        with p['local'].cursor() as q:
            q.execute("INSERT INTO raw_data.scraped_listings VALUES(2,'portal','B',1,'{}','new')")
            q.execute("INSERT INTO raw_data.listing_history VALUES(2,2,'LISTED')")
        p['local'].commit()
        original = pub._apply
        def failed(conn, schema, directory, data):
            original(conn, schema, directory, data)
            raise RuntimeError('Simulated failure before remote commit')
        monkeypatch.setattr(pub, '_apply', failed)
        with pytest.raises(RuntimeError):
            pub.publish()
        assert read(p['remote'], 'scraped_listings') == before
        assert len(read(p['remote'], 'listing_history')) == 1
        monkeypatch.setattr(pub, '_apply', original)
        assert pub.publish()['stage'] == 'PUBLISHED'
        assert len(read(p['remote'], 'listing_history')) == 2
    finally:
        pub.close()


def test_unreachable_shared_store_keeps_durable_local_work(pair):
    p = pair
    pub = publisher(p)
    try:
        pub.publish(True)
        with p['local'].cursor() as q:
            q.execute("UPDATE raw_data.scraped_listings SET note='offline work' WHERE id=1")
        p['local'].commit()
        pub.shared_url = 'postgresql:///missing?host=' + str(p['root'])
        with pytest.raises(psycopg2.OperationalError):
            pub.publish()
        with p['local'].cursor() as q:
            q.execute("SELECT count(*) FROM ops.shared_publications WHERE status='READY'")
            assert q.fetchone()[0] == 1
        p['local'].rollback()
        pub.shared_url = p['urls'][1]
        assert pub.publish()['stage'] == 'PUBLISHED'
    finally:
        pub.close()


def test_older_local_restore_cannot_overwrite_a_newer_publication(pair):
    p = pair
    pub = publisher(p)
    try:
        pub.publish(True)
        with p['local'].cursor() as q:
            q.execute('SELECT publication_id::text,manifest FROM ops.publisher_state')
            old_id, old_manifest = q.fetchone()
            q.execute('SELECT note FROM raw_data.scraped_listings WHERE id=1')
            old_note = q.fetchone()[0]
        p['local'].rollback()
        with p['local'].cursor() as q:
            q.execute("UPDATE raw_data.scraped_listings SET note='newer shared data' WHERE id=1")
        p['local'].commit()
        pub.publish()
        from psycopg2.extras import Json
        with p['local'].cursor() as q:
            q.execute('UPDATE ops.publisher_state SET publication_id=%s,manifest=%s', (old_id, Json(old_manifest)))
            q.execute('UPDATE publication_cache.scraped_listings SET note=%s WHERE id=1', (old_note,))
            q.execute("UPDATE raw_data.scraped_listings SET note='new work after restore' WHERE id=1")
        p['local'].commit()
        before = read(p['remote'], 'scraped_listings')
        with pytest.raises(PublicationError, match='conflict'):
            pub.publish()
        assert read(p['remote'], 'scraped_listings') == before
    finally:
        pub.close()


def test_full_writer_rejects_shared_target_and_wrong_archive_identity(pair, monkeypatch):
    import config
    from scraper.db_writer import DatabaseWriter
    p = pair
    monkeypatch.setattr(config, 'STORAGE_MODE', 'local-shared')
    monkeypatch.setattr(config, 'ARCHIVE_DATABASE_ID', p['archive'])
    with pytest.raises(PublicationError, match='not an initialized local archive'):
        DatabaseWriter(p['urls'][1])
    monkeypatch.setattr(config, 'ARCHIVE_DATABASE_ID', str(uuid4()))
    with pytest.raises(PublicationError, match='identity differs'):
        DatabaseWriter(p['urls'][0])
    monkeypatch.setattr(config, 'ARCHIVE_DATABASE_ID', p['archive'])
    db = DatabaseWriter(p['urls'][0])
    db.close()


def test_legacy_writer_also_refuses_a_published_shared_store(pair,monkeypatch):
    import config
    from scraper.db_writer import DatabaseWriter
    p=pair;pub=publisher(p)
    try:
        pub.publish(True)
        monkeypatch.setattr(config,'STORAGE_MODE','legacy')
        with pytest.raises(PublicationError,match='Published shared store'):
            DatabaseWriter(p['urls'][1])
    finally:pub.close()
