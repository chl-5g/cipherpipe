#!/usr/bin/env python3
"""SQLite persistence for messages, contacts, and state."""
import sqlite3, os, time
from backend.core.config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "cipherpipe.db")


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            pubkey TEXT PRIMARY KEY,
            petname TEXT,
            display_name TEXT,
            about TEXT,
            picture TEXT,
            nip05 TEXT,
            last_seen INTEGER,
            added_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            pubkey TEXT NOT NULL,
            content TEXT NOT NULL,
            msg_type TEXT DEFAULT 'text',
            direction TEXT CHECK(direction IN ('in','out')) NOT NULL,
            created_at INTEGER NOT NULL,
            received_at INTEGER,
            delivered INTEGER DEFAULT 0,
            read_status INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_messages_pubkey ON messages(pubkey);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(pubkey, content);
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    for col, typ in [("delivered", "INTEGER DEFAULT 0"), ("read_status", "INTEGER DEFAULT 0")]:
        try: db.execute(f"ALTER TABLE messages ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError: pass
    db.commit()
    db.close()


def add_message(event_id, pubkey, content, direction, msg_type="text", created_at=None, received_at=None, delivered=0):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO messages(event_id, pubkey, content, msg_type, direction, created_at, received_at, delivered) VALUES(?,?,?,?,?,?,?,?)",
        (event_id, pubkey, content, msg_type, direction, created_at or int(time.time()), received_at or int(time.time()), delivered)
    )
    row_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO messages_fts(rowid, pubkey, content) VALUES(?,?,?)", (row_id, pubkey[:12], content))
    db.commit()
    db.close()


def mark_delivered(event_id):
    db = get_db()
    db.execute("UPDATE messages SET delivered=1 WHERE event_id=?", (event_id,))
    db.commit()
    db.close()


def mark_read(event_id):
    db = get_db()
    db.execute("UPDATE messages SET read_status=1 WHERE event_id=?", (event_id,))
    db.commit()
    db.close()


def get_messages(pubkey, limit=50, before=None):
    db = get_db()
    q = "SELECT * FROM messages WHERE pubkey=? "
    args = [pubkey]
    if before:
        q += "AND created_at < ? "
        args.append(before)
    q += "ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    rows = db.execute(q, args).fetchall()
    db.close()
    return [dict(r) for r in reversed(rows)]


def search_messages(query, limit=50):
    db = get_db()
    rows = db.execute(
        "SELECT m.* FROM messages m JOIN messages_fts f ON m.id = f.rowid WHERE messages_fts MATCH ? ORDER BY m.created_at DESC LIMIT ?",
        (query, limit)
    ).fetchall()
    db.close()
    return [dict(r) for r in reversed(rows)]


def upsert_contact(pubkey, **kwargs):
    db = get_db()
    existing = db.execute("SELECT pubkey FROM contacts WHERE pubkey=?", (pubkey,)).fetchone()
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        db.execute(f"UPDATE contacts SET {sets} WHERE pubkey=?", (*kwargs.values(), pubkey))
    else:
        keys = ["pubkey"] + list(kwargs.keys())
        vals = [pubkey] + list(kwargs.values())
        db.execute(f"INSERT INTO contacts ({','.join(keys)}) VALUES ({','.join('?'*len(keys))})", vals)
    db.commit()
    db.close()


def list_contacts():
    db = get_db()
    rows = db.execute("SELECT * FROM contacts ORDER BY added_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]


def delete_contact(pubkey):
    db = get_db()
    db.execute("DELETE FROM contacts WHERE pubkey=?", (pubkey,))
    db.execute("DELETE FROM messages WHERE pubkey=?", (pubkey,))
    db.commit()
    db.close()


def get_state(key):
    db = get_db()
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    db.close()
    return row["value"] if row else None


def set_state(key, value):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO state(key, value) VALUES(?,?)", (key, str(value)))
    db.commit()
    db.close()
