-- CareerBridge database schema
-- Apply on a fresh machine: sqlite3 careerbridge.db < docs/schema.sql

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    task_type   TEXT    NOT NULL,
    url         TEXT,
    profile_id  TEXT,
    username    TEXT,
    payload     TEXT    NOT NULL DEFAULT '{}',
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  REAL    NOT NULL DEFAULT (unixepoch()),
    updated_at  REAL    NOT NULL DEFAULT (unixepoch()),
    result      TEXT
);

CREATE TABLE IF NOT EXISTS health_issues (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    module        TEXT NOT NULL,
    port          INTEGER NOT NULL,
    restart_count INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending'
);
