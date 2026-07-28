"""SQLite schema for users, crops, diagnosis history + follow-up reminders."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "agrisage.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    certification TEXT NOT NULL DEFAULT 'conventional',
    purpose TEXT NOT NULL DEFAULT 'self_consumption',
    daily_limit INTEGER DEFAULT 3
);

CREATE TABLE IF NOT EXISTS crops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    name TEXT NOT NULL,
    emoji TEXT,
    color TEXT,
    growing_environment TEXT NOT NULL DEFAULT 'open_field',
    purpose_override TEXT,
    harvest_date TEXT
);

CREATE INDEX IF NOT EXISTS idx_crops_user ON crops(user_id);

CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id INTEGER,
    crop_id TEXT,
    class_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    follow_up_status TEXT
);

CREATE TABLE IF NOT EXISTS follow_up_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id INTEGER NOT NULL REFERENCES diagnoses(id),
    target_date TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        # Migration for pre-auth DBs: their diagnoses table predates user_id, and
        # CREATE TABLE IF NOT EXISTS silently keeps the old shape.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(diagnoses)")}
        if "user_id" not in cols:
            conn.execute("ALTER TABLE diagnoses ADD COLUMN user_id INTEGER")
        # Must run AFTER the ALTER above (a legacy DB has no user_id column yet),
        # so this index cannot live in the _SCHEMA executescript.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_diagnoses_user_created"
            " ON diagnoses(user_id, created_at)"
        )
        conn.commit()
    finally:
        conn.close()
