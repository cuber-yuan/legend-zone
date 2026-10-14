-- Forward-only refinement: do not rewrite the already-applied 002 migration.
DROP TRIGGER preserve_deleted_version_snapshots;
CREATE TRIGGER preserve_deleted_version_snapshots BEFORE DELETE ON bot_versions
BEGIN
    UPDATE match_players SET bot_version_id=NULL WHERE bot_version_id=OLD.id;
    DELETE FROM rating_history WHERE version_id=OLD.id;
END;
DROP TRIGGER preserve_deleted_bot_snapshots;
CREATE TRIGGER preserve_deleted_bot_snapshots BEFORE DELETE ON bots
BEGIN
    UPDATE match_players SET bot_version_id=NULL, bot_id=NULL WHERE bot_id=OLD.id;
    DELETE FROM rating_history WHERE bot_id=OLD.id;
END;
CREATE TRIGGER validate_game_counts_insert BEFORE INSERT ON games
WHEN NEW.min_players IS NULL OR NEW.max_players IS NULL OR NEW.min_players<=0 OR NEW.max_players<NEW.min_players
BEGIN SELECT RAISE(ABORT, 'Invalid game player counts'); END;
CREATE TRIGGER validate_game_counts_update BEFORE UPDATE ON games
WHEN NEW.min_players IS NULL OR NEW.max_players IS NULL OR NEW.min_players<=0 OR NEW.max_players<NEW.min_players
BEGIN SELECT RAISE(ABORT, 'Invalid game player counts'); END;
DROP TRIGGER validate_debug_session_insert;
CREATE TRIGGER validate_debug_session_insert BEFORE INSERT ON match_debug_sessions
WHEN NOT EXISTS (SELECT 1 FROM matches WHERE id=NEW.match_id)
  OR NEW.last_turn < 0 OR NEW.frame_count < 0 OR NEW.truncated NOT IN (0,1) OR NEW.incomplete NOT IN (0,1)
  OR NEW.status NOT IN ('recording','complete','interrupted')
BEGIN SELECT RAISE(ABORT, 'Invalid debug session'); END;
DROP TRIGGER validate_debug_session_update;
CREATE TRIGGER validate_debug_session_update BEFORE UPDATE ON match_debug_sessions
WHEN NEW.last_turn < 0 OR NEW.frame_count < 0 OR NEW.truncated NOT IN (0,1) OR NEW.incomplete NOT IN (0,1)
  OR NEW.status NOT IN ('recording','complete','interrupted')
BEGIN SELECT RAISE(ABORT, 'Invalid debug session'); END;
CREATE TRIGGER validate_debug_event_update BEFORE UPDATE ON match_debug_events
WHEN NEW.sequence <= 0 OR NEW.turn_index < 0 OR NEW.actor NOT IN ('judge','player_1','player_2')
  OR NOT EXISTS (SELECT 1 FROM match_debug_sessions WHERE match_id=NEW.match_id)
BEGIN SELECT RAISE(ABORT, 'Invalid debug event'); END;
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
