-- Current database schema. Used only to initialize an empty database.
-- Existing databases are validated without schema or data changes.

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE bots (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    bot_name TEXT NOT NULL,
    game TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'cpp' CHECK (language IN ('python3','cpp')),
    is_private INTEGER NOT NULL DEFAULT 0 CHECK (is_private IN (0,1)),
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (bot_name, game)
);

CREATE TABLE bot_versions (
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

CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    author_id INTEGER,
    min_players INTEGER DEFAULT 2,
    max_players INTEGER DEFAULT 4,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (min_players > 0 AND max_players >= min_players)
);

CREATE TABLE matches (
    id TEXT PRIMARY KEY,
    game TEXT NOT NULL,
    players TEXT,
    winner INTEGER CHECK (winner IN (-1,0,1)),
    displays TEXT,
    move_history TEXT,
    status TEXT NOT NULL DEFAULT 'playing' CHECK (status IN ('playing','finished')),
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    started_at TEXT,
    finished_at TEXT,
    termination_reason TEXT,
    error_message TEXT,
    rating_status TEXT NOT NULL DEFAULT 'unknown' CHECK (rating_status IN ('unknown','pending','applied','skipped','failed')),
    rating_error TEXT,
    rated_at TEXT
);

CREATE TABLE match_players (
    match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE RESTRICT,
    seat INTEGER NOT NULL CHECK (seat IN (1,2)),
    player_type TEXT NOT NULL CHECK (player_type IN ('bot','human','unknown')),
    bot_id TEXT REFERENCES bots(id) ON DELETE SET NULL,
    bot_version_id INTEGER REFERENCES bot_versions(id) ON DELETE SET NULL,
    bot_id_snapshot TEXT,
    player_name TEXT NOT NULL,
    version_number_snapshot INTEGER CHECK (version_number_snapshot > 0),
    snapshot_source TEXT NOT NULL CHECK (snapshot_source IN ('execution','history')),
    PRIMARY KEY (match_id, seat),
    CHECK (player_type = 'bot' OR (bot_id IS NULL AND bot_version_id IS NULL))
);

CREATE TABLE match_debug_sessions (
    match_id TEXT PRIMARY KEY REFERENCES matches(id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'recording',
    last_turn INTEGER NOT NULL DEFAULT 0,
    frame_count INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0,
    incomplete INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    stored_bytes INTEGER NOT NULL DEFAULT 0 CHECK (stored_bytes >= 0),
    event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0)
);

CREATE TABLE match_debug_events (
    match_id TEXT NOT NULL REFERENCES match_debug_sessions(match_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    actor TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (match_id, sequence)
);

CREATE TABLE rating_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    version_id INTEGER NOT NULL REFERENCES bot_versions(id) ON DELETE CASCADE,
    match_id TEXT,
    rating REAL NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (version_id, match_id)
);

CREATE INDEX idx_bots_game_name ON bots (game, bot_name);

CREATE INDEX idx_bots_owner_name ON bots (user_id, bot_name);

CREATE INDEX idx_match_debug_turn
    ON match_debug_events (match_id, turn_index, sequence);

CREATE INDEX idx_match_players_bot ON match_players (bot_id, match_id);

CREATE INDEX idx_match_players_version ON match_players (bot_version_id);

CREATE INDEX idx_matches_status_created ON matches (status, created_at);

CREATE INDEX idx_rating_history_bot ON rating_history (bot_id, created_at);

CREATE INDEX idx_rating_history_match ON rating_history (match_id);

CREATE TRIGGER preserve_deleted_bot_snapshots BEFORE DELETE ON bots
BEGIN
    UPDATE match_players SET bot_version_id=NULL, bot_id=NULL WHERE bot_id=OLD.id;
    DELETE FROM rating_history WHERE bot_id=OLD.id;
END;

CREATE TRIGGER preserve_deleted_version_snapshots BEFORE DELETE ON bot_versions
BEGIN
    UPDATE match_players SET bot_version_id=NULL WHERE bot_version_id=OLD.id;
    DELETE FROM rating_history WHERE version_id=OLD.id;
END;

CREATE TRIGGER protect_bot_owners BEFORE DELETE ON users
WHEN EXISTS (SELECT 1 FROM bots WHERE user_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'User still owns bots'); END;

CREATE TRIGGER protect_debug_events BEFORE DELETE ON match_debug_sessions
WHEN EXISTS (SELECT 1 FROM match_debug_events WHERE match_id=OLD.match_id)
BEGIN SELECT RAISE(ABORT, 'Session still has retained debug events'); END;

CREATE TRIGGER protect_match_debug_history BEFORE DELETE ON matches
WHEN EXISTS (SELECT 1 FROM match_debug_sessions WHERE match_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'Match still has retained debug history'); END;

CREATE TRIGGER validate_bots_insert BEFORE INSERT ON bots
WHEN NEW.language NOT IN ('python3','cpp') OR NEW.is_private NOT IN (0,1)
  OR NOT EXISTS (SELECT 1 FROM users WHERE id=NEW.user_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot metadata or owner'); END;

CREATE TRIGGER validate_bots_update BEFORE UPDATE ON bots
WHEN NEW.language NOT IN ('python3','cpp') OR NEW.is_private NOT IN (0,1)
  OR NOT EXISTS (SELECT 1 FROM users WHERE id=NEW.user_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot metadata or owner'); END;

CREATE TRIGGER validate_debug_event_insert BEFORE INSERT ON match_debug_events
WHEN NEW.sequence <= 0 OR NEW.turn_index < 0 OR NEW.actor NOT IN ('judge','player_1','player_2')
  OR NOT EXISTS (SELECT 1 FROM match_debug_sessions WHERE match_id=NEW.match_id)
BEGIN SELECT RAISE(ABORT, 'Invalid debug event'); END;

CREATE TRIGGER validate_debug_event_update BEFORE UPDATE ON match_debug_events
WHEN NEW.sequence <= 0 OR NEW.turn_index < 0 OR NEW.actor NOT IN ('judge','player_1','player_2')
  OR NOT EXISTS (SELECT 1 FROM match_debug_sessions WHERE match_id=NEW.match_id)
BEGIN SELECT RAISE(ABORT, 'Invalid debug event'); END;

CREATE TRIGGER validate_debug_session_insert BEFORE INSERT ON match_debug_sessions
WHEN NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id)
  OR NEW.last_turn < 0 OR NEW.frame_count < 0 OR NEW.truncated NOT IN (0,1) OR NEW.incomplete NOT IN (0,1)
  OR NEW.status NOT IN ('recording','complete','interrupted')
BEGIN SELECT RAISE(ABORT, 'Invalid debug session'); END;

CREATE TRIGGER validate_debug_session_update BEFORE UPDATE ON match_debug_sessions
WHEN NEW.last_turn < 0 OR NEW.frame_count < 0 OR NEW.truncated NOT IN (0,1) OR NEW.incomplete NOT IN (0,1)
  OR NEW.status NOT IN ('recording','complete','interrupted')
BEGIN SELECT RAISE(ABORT, 'Invalid debug session'); END;

CREATE TRIGGER validate_game_counts_insert BEFORE INSERT ON games
WHEN NEW.min_players IS NULL OR NEW.max_players IS NULL OR NEW.min_players<=0 OR NEW.max_players<NEW.min_players
BEGIN SELECT RAISE(ABORT, 'Invalid game player counts'); END;

CREATE TRIGGER validate_game_counts_update BEFORE UPDATE ON games
WHEN NEW.min_players IS NULL OR NEW.max_players IS NULL OR NEW.min_players<=0 OR NEW.max_players<NEW.min_players
BEGIN SELECT RAISE(ABORT, 'Invalid game player counts'); END;

CREATE TRIGGER validate_history_insert BEFORE INSERT ON rating_history
WHEN NOT EXISTS (SELECT 1 FROM bot_versions WHERE id=NEW.version_id AND bot_id=NEW.bot_id)
  OR (NEW.match_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id))
BEGIN SELECT RAISE(ABORT, 'Invalid rating history reference'); END;

CREATE TRIGGER validate_history_update BEFORE UPDATE ON rating_history
WHEN NOT EXISTS (SELECT 1 FROM bot_versions WHERE id=NEW.version_id AND bot_id=NEW.bot_id)
  OR (NEW.match_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id))
BEGIN SELECT RAISE(ABORT, 'Invalid rating history reference'); END;

CREATE TRIGGER validate_matches_insert BEFORE INSERT ON matches
WHEN NEW.status IS NULL OR NEW.status NOT IN ('playing','finished')
  OR (NEW.winner IS NOT NULL AND NEW.winner NOT IN (-1,0,1))
BEGIN SELECT RAISE(ABORT, 'Invalid match status or winner'); END;

CREATE TRIGGER validate_matches_update BEFORE UPDATE ON matches
WHEN NEW.status IS NULL OR NEW.status NOT IN ('playing','finished')
  OR (NEW.winner IS NOT NULL AND NEW.winner NOT IN (-1,0,1))
BEGIN SELECT RAISE(ABORT, 'Invalid match status or winner'); END;

CREATE TRIGGER validate_player_version_insert BEFORE INSERT ON match_players
WHEN NEW.bot_version_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM bot_versions WHERE id=NEW.bot_version_id AND bot_id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Version does not belong to this player'); END;

CREATE TRIGGER validate_player_version_update BEFORE UPDATE OF bot_id, bot_version_id ON match_players
WHEN NEW.bot_version_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM bot_versions WHERE id=NEW.bot_version_id AND bot_id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Version does not belong to this player'); END;

CREATE TRIGGER validate_termination_insert BEFORE INSERT ON matches
WHEN NEW.termination_reason IS NOT NULL AND NEW.termination_reason NOT IN
    ('normal','invalid_move','timeout','protocol_error','runtime_error','compile_error','execution_error',
     'disconnect','server_error','turn_limit','unsupported','double_forfeit','unknown')
BEGIN SELECT RAISE(ABORT, 'Invalid match termination reason'); END;

CREATE TRIGGER validate_termination_update BEFORE UPDATE ON matches
WHEN NEW.termination_reason IS NOT NULL AND NEW.termination_reason NOT IN
    ('normal','invalid_move','timeout','protocol_error','runtime_error','compile_error','execution_error',
     'disconnect','server_error','turn_limit','unsupported','double_forfeit','unknown')
BEGIN SELECT RAISE(ABORT, 'Invalid match termination reason'); END;

CREATE TRIGGER validate_versions_insert BEFORE INSERT ON bot_versions
WHEN NEW.version_number IS NULL OR NEW.version_number <= 0
  OR NOT EXISTS (SELECT 1 FROM bots WHERE id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot version'); END;

CREATE TRIGGER validate_versions_update BEFORE UPDATE ON bot_versions
WHEN NEW.version_number IS NULL OR NEW.version_number <= 0
  OR NOT EXISTS (SELECT 1 FROM bots WHERE id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot version'); END;
