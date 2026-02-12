#!/usr/bin/env python3
"""Initialize the TaskManager SQLite database."""

import json
import os
import sqlite3
import sys

DB_PATH = os.path.expanduser("~/.openclaw/workspace/data/taskmanager.db")


def get_connection():
    """Get a connection to the database, creating directory if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables and indexes."""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id     INTEGER PRIMARY KEY,
            username        TEXT,
            first_name      TEXT,
            last_name       TEXT,
            display_name    TEXT,
            chat_ids        TEXT DEFAULT '[]',
            first_seen_at   TEXT DEFAULT (datetime('now')),
            last_seen_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        CREATE INDEX IF NOT EXISTS idx_users_first_name ON users(first_name);

        CREATE TABLE IF NOT EXISTS tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            description     TEXT NOT NULL,
            title           TEXT,
            creator_id      INTEGER NOT NULL,
            creator_username TEXT,
            assignee_id     INTEGER,
            assignee_username TEXT,
            chat_id         INTEGER NOT NULL,
            deadline        TEXT,
            priority        TEXT DEFAULT 'medium' CHECK(priority IN ('low','medium','high')),
            status          TEXT DEFAULT 'todo' CHECK(status IN ('todo','in_progress','done','cancelled','overdue')),
            cron_job_ids    TEXT DEFAULT '[]',
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            completed_at    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_creator ON tasks(creator_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_chat ON tasks(chat_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline);
    """)

    conn.commit()
    conn.close()
    return {"status": "ok", "db_path": DB_PATH, "message": "Database initialized successfully"}


if __name__ == "__main__":
    try:
        result = init_db()
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
