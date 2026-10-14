CREATE TABLE IF NOT EXISTS match_debug_sessions (
    match_id TEXT PRIMARY KEY REFERENCES matches(id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'recording',
    last_turn INTEGER NOT NULL DEFAULT 0,
    frame_count INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0,
    incomplete INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS match_debug_events (
    match_id TEXT NOT NULL REFERENCES match_debug_sessions(match_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    actor TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (match_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_match_debug_turn
    ON match_debug_events (match_id, turn_index, sequence);
