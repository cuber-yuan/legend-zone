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
CREATE INDEX idx_match_players_bot ON match_players (bot_id, match_id);
CREATE INDEX idx_match_players_version ON match_players (bot_version_id);
CREATE INDEX IF NOT EXISTS idx_matches_status_created ON matches (status, created_at);
CREATE INDEX IF NOT EXISTS idx_bots_owner_name ON bots (user_id, bot_name);
CREATE INDEX IF NOT EXISTS idx_bots_game_name ON bots (game, bot_name);
CREATE INDEX IF NOT EXISTS idx_rating_history_match ON rating_history (match_id);

-- Also enforce new writes on legacy tables without rewriting their stored rows.
CREATE TRIGGER validate_bots_insert BEFORE INSERT ON bots
WHEN NEW.language NOT IN ('python3','cpp') OR NEW.is_private NOT IN (0,1)
  OR NOT EXISTS (SELECT 1 FROM users WHERE id=NEW.user_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot metadata or owner'); END;
CREATE TRIGGER validate_bots_update BEFORE UPDATE ON bots
WHEN NEW.language NOT IN ('python3','cpp') OR NEW.is_private NOT IN (0,1)
  OR NOT EXISTS (SELECT 1 FROM users WHERE id=NEW.user_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot metadata or owner'); END;
CREATE TRIGGER protect_bot_owners BEFORE DELETE ON users
WHEN EXISTS (SELECT 1 FROM bots WHERE user_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'User still owns bots'); END;
CREATE TRIGGER validate_versions_insert BEFORE INSERT ON bot_versions
WHEN NEW.version_number IS NULL OR NEW.version_number <= 0
  OR NOT EXISTS (SELECT 1 FROM bots WHERE id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot version'); END;
CREATE TRIGGER validate_versions_update BEFORE UPDATE ON bot_versions
WHEN NEW.version_number IS NULL OR NEW.version_number <= 0
  OR NOT EXISTS (SELECT 1 FROM bots WHERE id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Invalid bot version'); END;
CREATE TRIGGER validate_matches_insert BEFORE INSERT ON matches
WHEN NEW.status IS NULL OR NEW.status NOT IN ('playing','finished')
  OR (NEW.winner IS NOT NULL AND NEW.winner NOT IN (-1,0,1))
BEGIN SELECT RAISE(ABORT, 'Invalid match status or winner'); END;
CREATE TRIGGER validate_matches_update BEFORE UPDATE ON matches
WHEN NEW.status IS NULL OR NEW.status NOT IN ('playing','finished')
  OR (NEW.winner IS NOT NULL AND NEW.winner NOT IN (-1,0,1))
BEGIN SELECT RAISE(ABORT, 'Invalid match status or winner'); END;
CREATE TRIGGER validate_history_insert BEFORE INSERT ON rating_history
WHEN NOT EXISTS (SELECT 1 FROM bot_versions WHERE id=NEW.version_id AND bot_id=NEW.bot_id)
  OR (NEW.match_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id))
BEGIN SELECT RAISE(ABORT, 'Invalid rating history reference'); END;
CREATE TRIGGER validate_history_update BEFORE UPDATE ON rating_history
WHEN NOT EXISTS (SELECT 1 FROM bot_versions WHERE id=NEW.version_id AND bot_id=NEW.bot_id)
  OR (NEW.match_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id))
BEGIN SELECT RAISE(ABORT, 'Invalid rating history reference'); END;
CREATE TRIGGER validate_player_version_insert BEFORE INSERT ON match_players
WHEN NEW.bot_version_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM bot_versions WHERE id=NEW.bot_version_id AND bot_id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Version does not belong to this player'); END;
CREATE TRIGGER validate_player_version_update BEFORE UPDATE OF bot_id, bot_version_id ON match_players
WHEN NEW.bot_version_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM bot_versions WHERE id=NEW.bot_version_id AND bot_id=NEW.bot_id)
BEGIN SELECT RAISE(ABORT, 'Version does not belong to this player'); END;
CREATE TRIGGER preserve_deleted_version_snapshots BEFORE DELETE ON bot_versions
BEGIN UPDATE match_players SET bot_version_id=NULL WHERE bot_version_id=OLD.id; END;
CREATE TRIGGER preserve_deleted_bot_snapshots BEFORE DELETE ON bots
BEGIN UPDATE match_players SET bot_version_id=NULL, bot_id=NULL WHERE bot_id=OLD.id; END;

CREATE TRIGGER validate_debug_session_insert BEFORE INSERT ON match_debug_sessions
WHEN NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id)
  OR NEW.last_turn < 0 OR NEW.frame_count < 0 OR NEW.truncated NOT IN (0,1) OR NEW.incomplete NOT IN (0,1)
BEGIN SELECT RAISE(ABORT, 'Invalid debug session'); END;
CREATE TRIGGER validate_debug_session_update BEFORE UPDATE ON match_debug_sessions
WHEN NEW.last_turn < 0 OR NEW.frame_count < 0 OR NEW.truncated NOT IN (0,1) OR NEW.incomplete NOT IN (0,1)
BEGIN SELECT RAISE(ABORT, 'Invalid debug session'); END;
CREATE TRIGGER validate_debug_event_insert BEFORE INSERT ON match_debug_events
WHEN NEW.sequence <= 0 OR NEW.turn_index < 0 OR NEW.actor NOT IN ('judge','player_1','player_2')
  OR NOT EXISTS (SELECT 1 FROM match_debug_sessions WHERE match_id=NEW.match_id)
BEGIN SELECT RAISE(ABORT, 'Invalid debug event'); END;
CREATE TRIGGER protect_match_debug_history BEFORE DELETE ON matches
WHEN EXISTS (SELECT 1 FROM match_debug_sessions WHERE match_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'Match still has retained debug history'); END;
CREATE TRIGGER protect_debug_events BEFORE DELETE ON match_debug_sessions
WHEN EXISTS (SELECT 1 FROM match_debug_events WHERE match_id=OLD.match_id)
BEGIN SELECT RAISE(ABORT, 'Session still has retained debug events'); END;
