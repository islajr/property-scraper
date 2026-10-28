"""Durable local recovery queue. SQLite state never substitutes for the DB audit."""
from contextlib import contextmanager
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import time


class RecoveryState:
    def __init__(self, directory, target):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory/'queue.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    listing_id INTEGER PRIMARY KEY, source TEXT NOT NULL, price_type TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', reason TEXT,
                    visits INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                    network_started INTEGER NOT NULL DEFAULT 0,
                    row_json TEXT, quote_json TEXT, visible_purpose TEXT,
                    run_id TEXT, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(source,status,retry_at,listing_id);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, started_at REAL NOT NULL, finished_at REAL,
                    config_json TEXT NOT NULL, http_attempts INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running'
                );
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id);
                CREATE TABLE IF NOT EXISTS portals (
                    source TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
                    cooldown_until REAL NOT NULL DEFAULT 0, reason TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, listing_id INTEGER,
                    source TEXT, outcome TEXT NOT NULL, reason TEXT, created_at REAL NOT NULL
                );
            ''')
            previous = db.execute("SELECT value FROM metadata WHERE key='target'").fetchone()
            if previous and previous['value'] != target:
                raise ValueError('State directory belongs to a different database target')
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('target',?)", (target,))
        os.chmod(self.path, 0o600)

    @classmethod
    def existing(cls, directory):
        path = Path(directory)/'queue.sqlite3'
        if not path.exists():
            raise ValueError('No recovery queue exists in this state directory yet')
        db = sqlite3.connect(path)
        try:
            row = db.execute("SELECT value FROM metadata WHERE key='target'").fetchone()
            if row is None: raise ValueError('Recovery state has no database identity')
            return cls(directory, row[0])
        finally:
            db.close()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self, candidates):
        count = 0
        with self.connect() as db:
            for lid, source, kind in candidates:
                count += db.execute('INSERT OR IGNORE INTO jobs(listing_id,source,price_type,updated_at) VALUES (?,?,?,?)',
                                    (lid,source,kind,time.time())).rowcount
        return count

    def import_attempt(self, lid, source, reason):
        with self.connect() as db:
            db.execute('''INSERT INTO jobs(listing_id,source,status,reason,updated_at)
                VALUES (?,?,'imported',?,?) ON CONFLICT(listing_id) DO UPDATE SET
                status='imported',reason=excluded.reason,updated_at=excluded.updated_at
                WHERE jobs.status IN ('pending','retryable')''', (lid,source,reason,time.time()))

    def recover_interrupted(self, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='ready',reason='resuming_saved_quote' WHERE status='working' AND quote_json IS NOT NULL")
            db.execute("UPDATE jobs SET status='retryable',retry_at=?,reason='interrupted_visit' WHERE status='working' AND network_started=1", (now+300,))
            db.execute("UPDATE jobs SET status='pending',reason='interrupted_before_request' WHERE status='working'")

    def begin_run(self, run_id, config):
        with self.connect() as db:
            db.execute('INSERT INTO runs(run_id,started_at,config_json) VALUES (?,?,?)', (run_id,time.time(),json.dumps(config)))

    def finish_run(self, run_id, status):
        with self.connect() as db:
            db.execute('UPDATE runs SET finished_at=?,status=? WHERE run_id=?', (time.time(),status,run_id))

    def claim(self, source, apply, max_visits=2, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET status='held',reason='retry_limit_reached' WHERE source=? AND status='retryable' AND visits>=?", (source,max_visits))
            row = db.execute('''SELECT * FROM jobs WHERE source=? AND (
                status IN ('pending','ready') OR (status='previewed' AND ?)
                OR (status='retryable' AND retry_at<=? AND visits<?))
                ORDER BY CASE WHEN status IN ('ready','previewed') THEN 0 ELSE 1 END,listing_id LIMIT 1''',
                (source,int(apply),now,max_visits)).fetchone()
            if row is None: return None
            db.execute("UPDATE jobs SET status='working',network_started=0,updated_at=? WHERE listing_id=?", (now,row['listing_id']))
            return {**dict(row),'claimed_from':row['status']}

    def release(self, job):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=? WHERE listing_id=?', (job['claimed_from'],job['listing_id']))

    def start_visit(self, lid):
        with self.connect() as db:
            db.execute('UPDATE jobs SET visits=visits+1,network_started=1,updated_at=? WHERE listing_id=?', (time.time(),lid))

    def request(self, run_id):
        with self.connect() as db:
            db.execute('UPDATE runs SET http_attempts=http_attempts+1 WHERE run_id=?', (run_id,))

    def save_quote(self, lid, row, quote, purpose, audit_run):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='ready',row_json=?,quote_json=?,visible_purpose=?,run_id=?,updated_at=? WHERE listing_id=?",
                       (json.dumps(row,default=str),json.dumps(quote,default=str),purpose,audit_run,time.time(),lid))

    def finish(self, job, run_id, status, reason, retry_at=0):
        lid = job['listing_id']
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,reason=?,retry_at=?,updated_at=? WHERE listing_id=?',
                       (status,reason,retry_at,time.time(),lid))
            db.execute('INSERT INTO events(run_id,listing_id,source,outcome,reason,created_at) VALUES (?,?,?,?,?,?)',
                       (run_id,lid,job['source'],status,reason,time.time()))

    def portal(self, source):
        with self.connect() as db:
            row = db.execute('SELECT * FROM portals WHERE source=?', (source,)).fetchone()
        return dict(row) if row else dict(failures=0,cooldown_until=0,reason=None)

    def portal_result(self, source, failed, reason, threshold=5, cooldown=1800):
        previous = self.portal(source)
        failures = previous['failures']+1 if failed else 0
        until = time.time()+cooldown if failures>=threshold else 0
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO portals VALUES (?,?,?,?)', (source,failures,until,reason if failed else None))
        return until

    def reset(self, ids):
        with self.connect() as db:
            for lid in ids:
                # Explicit operator action; no blanket retry of ambiguous pages.
                db.execute("UPDATE jobs SET status='pending',reason='operator_retry',retry_at=0,visits=0,row_json=NULL,quote_json=NULL,run_id=NULL WHERE listing_id=? AND status IN ('held','retryable','imported','skipped')", (lid,))

    def summary(self, run_id=None):
        with self.connect() as db:
            rows = db.execute('SELECT source,status,COUNT(*) AS n FROM jobs GROUP BY source,status ORDER BY source,status').fetchall()
            run = db.execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone() if run_id else None
            events = db.execute('SELECT source,outcome,reason,COUNT(*) AS n FROM events WHERE run_id=? GROUP BY source,outcome,reason', (run_id,)).fetchall() if run_id else []
            portals = [dict(row) for row in db.execute('SELECT * FROM portals ORDER BY source')]
        return dict(queue=[dict(row) for row in rows],run=dict(run) if run else None,
                    outcomes=[dict(row) for row in events],portals=portals)
