"""Base exclusiva de prueba; reservas durables impiden intentos duplicados."""
import json
import sqlite3
from contextlib import contextmanager
import config

DB_PATH = config.ROOT / 'data' / 'test_results.sqlite3'

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()

def timestamp():
    return config.now_colombia().isoformat(timespec='seconds')

def init_db():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
          CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, test_date TEXT NOT NULL, slot TEXT NOT NULL,
            channel TEXT NOT NULL CHECK(channel IN ('calls','whatsapp','email')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            status TEXT NOT NULL, external_id TEXT, detail TEXT,
            UNIQUE(test_date, slot, channel));
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, status TEXT NOT NULL, detail TEXT);
          CREATE TABLE IF NOT EXISTS balance_cutoffs (
            cutoff_date TEXT PRIMARY KEY, principal_before REAL, monthly_rate REAL,
            interest_capitalized REAL, principal_after REAL, created_at TEXT);
          CREATE TABLE IF NOT EXISTS balance_snapshots (
            id INTEGER PRIMARY KEY, snapshot_date TEXT, principal REAL,
            days_accrued INTEGER, daily_rate REAL, accrued_interest REAL,
            total_balance REAL, last_cutoff_date TEXT, next_cutoff_date TEXT,
            created_at TEXT);
        ''')

def claim(slot, channel):
    manual = slot.startswith('manual_')
    allowed = ('calls', 'whatsapp', 'email') if manual else config.PLAN.get(slot, ())
    if channel not in allowed:
        raise ValueError('Canal fuera del plan de prueba')
    day = config.now_colombia().date()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        cur = c.execute('''INSERT OR IGNORE INTO attempts
          (test_date,slot,channel,created_at,updated_at,status)
          VALUES(?,?,?,?,?,'reserved')''',
          (day.isoformat(), slot, channel, timestamp(), timestamp()))
        if cur.rowcount == 0:
            return None
        attempt_id = cur.lastrowid
        c.execute('INSERT INTO events(attempt_id,created_at,status) VALUES(?,?,?)',
                  (attempt_id, timestamp(), 'reserved'))
        return attempt_id

def update(attempt_id, status, external_id=None, detail=None):
    payload = json.dumps(detail or {}, ensure_ascii=False, default=str)
    with connect() as c:
        c.execute('''UPDATE attempts SET updated_at=?,status=?,
          external_id=COALESCE(?,external_id),detail=? WHERE id=?''',
          (timestamp(), status, external_id, payload, attempt_id))
        c.execute('INSERT INTO events(attempt_id,created_at,status,detail) VALUES(?,?,?,?)',
                  (attempt_id, timestamp(), status, payload))

def attempts():
    with connect() as c:
        return c.execute('SELECT * FROM attempts ORDER BY test_date, slot, id').fetchall()

def upsert_cutoff(cutoff_date, principal_before, monthly_rate, interest_capitalized, principal_after):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO balance_cutoffs VALUES(?,?,?,?,?,?)',
          (cutoff_date, principal_before, monthly_rate, interest_capitalized, principal_after, timestamp()))

def add_snapshot(snapshot_date, principal, days_accrued, daily_rate, accrued_interest,
                 total_balance, last_cutoff_date, next_cutoff_date):
    with connect() as c:
        c.execute('''INSERT INTO balance_snapshots
          (snapshot_date,principal,days_accrued,daily_rate,accrued_interest,
          total_balance,last_cutoff_date,next_cutoff_date,created_at)
          VALUES(?,?,?,?,?,?,?,?,?)''', (snapshot_date, principal, days_accrued,
          daily_rate, accrued_interest, total_balance, last_cutoff_date, next_cutoff_date, timestamp()))

