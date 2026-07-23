"""SQLite schema for diagnosis history + follow-up reminders."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "agrisage.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
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
        conn.commit()
    finally:
        conn.close()
