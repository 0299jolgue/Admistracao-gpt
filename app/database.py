import sqlite3
from pathlib import Path
from .config import settings

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS devices (id INTEGER PRIMARY KEY, device_uid TEXT UNIQUE NOT NULL, name TEXT NOT NULL, model TEXT DEFAULT '', manufacturer TEXT DEFAULT '', android_version TEXT DEFAULT '', agent_version TEXT DEFAULT '1.0.0', battery INTEGER DEFAULT 0, status TEXT DEFAULT 'OFFLINE', network TEXT DEFAULT '', ip TEXT DEFAULT '', last_seen TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, revoked INTEGER DEFAULT 0, demo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS device_tokens (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, token_hash TEXT UNIQUE NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS enrollment_requests (id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, token_hash TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, type TEXT NOT NULL, payload TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP, sent_at TEXT, completed_at TEXT, status TEXT DEFAULT 'PENDING', response TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'PENDING');
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, app TEXT DEFAULT '', title TEXT DEFAULT '', content TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, device_id INTEGER, type TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS apk_builds (id INTEGER PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT, finished_at TEXT, error TEXT DEFAULT '', path TEXT DEFAULT '', size INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''

def connect():
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(settings.db_path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = connect()
    c.executescript(SCHEMA)
    c.commit()
    c.close()

def fetch(sql, params=()):
    c = connect()
    rows = c.execute(sql, params).fetchall()
    c.close()
    return rows

def fetch_one(sql, params=()):
    c = connect()
    row = c.execute(sql, params).fetchone()
    c.close()
    return row

def execute(sql, params=()):
    c = connect()
    cur = c.execute(sql, params)
    c.commit()
    value = cur.lastrowid
    c.close()
    return value
