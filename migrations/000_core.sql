-- Baseline for empty databases. Existing tables and rows are preserved.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS bots (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    bot_name TEXT NOT NULL,
    game TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'cpp' CHECK (language IN ('python3','cpp')),
    is_private INTEGER NOT NULL DEFAULT 0 CHECK (is_private IN (0,1)),
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (bot_name, game)
);
CREATE TABLE IF NOT EXISTS bot_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    description TEXT,
    source_code TEXT,
    file_path TEXT,
    rating REAL DEFAULT 1500,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (bot_id, version_number)
);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    game TEXT NOT NULL,
    players TEXT,
    winner INTEGER CHECK (winner IN (-1,0,1)),
    displays TEXT,
    move_history TEXT,
    status TEXT NOT NULL DEFAULT 'playing' CHECK (status IN ('playing','finished')),
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    author_id INTEGER,
    min_players INTEGER DEFAULT 2,
    max_players INTEGER DEFAULT 4,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (min_players > 0 AND max_players >= min_players)
);
CREATE TABLE IF NOT EXISTS rating_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    version_id INTEGER NOT NULL REFERENCES bot_versions(id) ON DELETE CASCADE,
    match_id TEXT,
    rating REAL NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (version_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_rating_history_bot ON rating_history (bot_id, created_at);
