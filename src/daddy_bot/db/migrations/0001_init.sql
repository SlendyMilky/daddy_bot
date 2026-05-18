CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS json_imports (
    filename TEXT PRIMARY KEY,
    imported_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT,
    username TEXT,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS bibine_subscribers (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    username TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bibine_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bibine_polls (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS bibine_place_state (
    chat_id INTEGER NOT NULL,
    week_iso TEXT NOT NULL,
    poll_message_id INTEGER,
    proposals TEXT NOT NULL,
    PRIMARY KEY (chat_id, week_iso)
);

CREATE TABLE IF NOT EXISTS princesse_pool (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    first_name TEXT NOT NULL,
    username TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS princesse_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS princesse_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    voice_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    sid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL,
    sent_by INTEGER NOT NULL,
    target_chat_id INTEGER NOT NULL,
    message_preview TEXT NOT NULL,
    success INTEGER NOT NULL
);
