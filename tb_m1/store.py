"""Durable, SQLite-backed local outbox and central case receiver.

M1 is a single-device synthetic-data prototype. SQLite transactions and unique
(case_id, revision) identities are deliberate; sync status never enters the M0 case.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from contract import canonical, check_next, digest, validate_or_raise


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA journal_mode=WAL')
    db.row_factory = sqlite3.Row
    return db


@contextmanager
def db_connection(path):
    db = connect(path)
    try:
        yield db
    finally:
        db.close()


LOCAL_DDL = '''
CREATE TABLE IF NOT EXISTS outbox (
 case_id TEXT NOT NULL, revision INTEGER NOT NULL,
 payload TEXT NOT NULL, content_hash TEXT NOT NULL,
 sync_status TEXT NOT NULL CHECK (sync_status IN ('pending','acked','needs_attention')),
 attempt_count INTEGER NOT NULL DEFAULT 0,
 last_attempt_at TEXT, acked_at TEXT, last_error TEXT,
 PRIMARY KEY(case_id,revision)
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(sync_status,case_id,revision);
'''
CENTRAL_DDL = '''
CREATE TABLE IF NOT EXISTS cases (
 case_id TEXT NOT NULL, revision INTEGER NOT NULL,
 payload TEXT NOT NULL, content_hash TEXT NOT NULL, received_at TEXT NOT NULL,
 PRIMARY KEY(case_id,revision)
);
CREATE INDEX IF NOT EXISTS cases_latest ON cases(case_id,revision DESC);
'''


class LocalOutbox:
    def __init__(self, path):
        self.path = str(path)
        with db_connection(self.path) as db:
            db.executescript(LOCAL_DDL)

    def enqueue(self, case):
        validate_or_raise(case)
        payload = canonical(case)
        hashed = digest(payload)
        with db_connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT * FROM outbox WHERE case_id=? ORDER BY revision DESC LIMIT 1',
                                (case['case_id'],)).fetchone()
            if latest:
                if latest['revision'] == case['revision'] and latest['content_hash'] == hashed:
                    db.execute('COMMIT')
                    return 'already_queued'
                check_next(json.loads(latest['payload']), case)
            db.execute('''INSERT INTO outbox(case_id,revision,payload,content_hash,sync_status)
                          VALUES(?,?,?,?, 'pending')''', (case['case_id'], case['revision'], payload, hashed))
            db.execute('COMMIT')
        return 'queued'

    def pending(self):
        with db_connection(self.path) as db:
            return [dict(row) for row in db.execute('''SELECT * FROM outbox
                WHERE sync_status='pending' ORDER BY case_id,revision''')]

    def record_attempt(self, case_id, revision):
        with db_connection(self.path) as db:
            db.execute('''UPDATE outbox SET attempt_count=attempt_count+1,
                last_attempt_at=? WHERE case_id=? AND revision=? AND sync_status='pending' ''',
                (utc_now(), case_id, revision))

    def acknowledge(self, case_id, revision, hashed):
        with db_connection(self.path) as db:
            row = db.execute('SELECT content_hash FROM outbox WHERE case_id=? AND revision=?',
                             (case_id, revision)).fetchone()
            if row is None or row['content_hash'] != hashed:
                raise ValueError('ACK payload hash mismatch; do not discard case')
            db.execute('''UPDATE outbox SET sync_status='acked', acked_at=?, last_error=NULL
                          WHERE case_id=? AND revision=?''', (utc_now(), case_id, revision))

    def error(self, case_id, revision, message, *, needs_attention=False):
        with db_connection(self.path) as db:
            db.execute('''UPDATE outbox SET sync_status=?, last_error=?
                          WHERE case_id=? AND revision=?''',
                       ('needs_attention' if needs_attention else 'pending', message[:500], case_id, revision))

    def status(self):
        with db_connection(self.path) as db:
            return [dict(row) for row in db.execute('''SELECT case_id,revision,sync_status,
                attempt_count,acked_at,last_error FROM outbox ORDER BY case_id,revision''')]


class InvalidCase(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class CentralReceiver:
    def __init__(self, path):
        self.path = str(path)
        with db_connection(self.path) as db:
            db.executescript(CENTRAL_DDL)

    def ingest(self, case):
        try:
            validate_or_raise(case)
        except (ValueError, TypeError) as exc:
            raise InvalidCase(str(exc)) from exc
        payload = canonical(case)
        hashed = digest(payload)
        case_id, revision = case['case_id'], case['revision']
        with db_connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT content_hash FROM cases WHERE case_id=? AND revision=?',
                                  (case_id, revision)).fetchone()
            if existing:
                if existing['content_hash'] == hashed:
                    db.execute('COMMIT')
                    return {'case_id':case_id, 'revision':revision, 'content_hash':hashed, 'result':'duplicate'}
                raise RevisionConflict('same case_id/revision, different content; requires reconciliation')
            latest = db.execute('SELECT payload,revision FROM cases WHERE case_id=? ORDER BY revision DESC LIMIT 1',
                                (case_id,)).fetchone()
            if latest:
                try:
                    check_next(json.loads(latest['payload']), case)
                except ValueError as exc:
                    raise RevisionConflict(str(exc)) from exc
            db.execute('''INSERT INTO cases(case_id,revision,payload,content_hash,received_at)
                          VALUES(?,?,?,?,?)''', (case_id, revision, payload, hashed, utc_now()))
            db.execute('COMMIT')
        return {'case_id':case_id, 'revision':revision, 'content_hash':hashed, 'result':'stored'}

    def latest(self, case_id):
        with db_connection(self.path) as db:
            row = db.execute('SELECT payload FROM cases WHERE case_id=? ORDER BY revision DESC LIMIT 1',
                             (case_id,)).fetchone()
        return json.loads(row['payload']) if row else None

    def revisions(self, case_id):
        with db_connection(self.path) as db:
            return [r['revision'] for r in db.execute('SELECT revision FROM cases WHERE case_id=? ORDER BY revision',
                                                     (case_id,))]
