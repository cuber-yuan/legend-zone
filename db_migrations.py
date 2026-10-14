"""Versioned SQLite migrations. No Flask imports, application startup or user-file access."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


MIGRATIONS = Path(__file__).resolve().parent / 'migrations'


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def pending_migrations(connection):
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
    applied = dict(connection.execute('SELECT version, checksum FROM schema_migrations')) if exists else {}
    paths = sorted(MIGRATIONS.glob('[0-9][0-9][0-9]_*.sql'))
    if not paths:
        raise RuntimeError('Migration SQL files are missing.')
    if set(applied) - {path.stem for path in paths}:
        raise RuntimeError('Database contains migrations not available in this checkout.')
    pending = []
    for path in paths:
        checksum = hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
        if path.stem in applied:
            if applied[path.stem] != checksum:
                raise RuntimeError(f'Applied migration was modified: {path.name}')
        else:
            pending.append((path, checksum))
    return pending


def _execute_sql(connection, source):
    # executescript() commits implicitly; execute complete statements to keep DDL atomic.
    statement = ''
    for line in source.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ''
    if statement.strip():
        connection.execute(statement)


def _add_columns(connection, table, columns):
    existing = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')


def _prepare_integrity(connection):
    _add_columns(connection, 'matches', {
        'started_at': 'TEXT',
        'finished_at': 'TEXT',
        'termination_reason': 'TEXT',
        'error_message': 'TEXT',
        'rating_status': "TEXT NOT NULL DEFAULT 'unknown' CHECK (rating_status IN ('unknown','pending','applied','skipped','failed'))",
        'rating_error': 'TEXT',
        'rated_at': 'TEXT',
    })
    _add_columns(connection, 'match_debug_sessions', {
        'stored_bytes': 'INTEGER NOT NULL DEFAULT 0 CHECK (stored_bytes >= 0)',
        'event_count': 'INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0)',
    })


def _backfill_integrity(connection):
    # Preserve historical uncertainty: setup snapshots do not prove which version executed.
    for match_id, players_json in connection.execute('SELECT id, players FROM matches'):
        try:
            players = json.loads(players_json) if players_json else {}
        except (ValueError, TypeError):
            continue
        if not isinstance(players, dict):
            continue
        for seat in (1, 2):
            player = players.get(f'player_{seat}')
            if isinstance(player, str):
                player = {'name': player}
            if not isinstance(player, dict):
                continue
            bot_id = str(player['bot_id']) if player.get('bot_id') else None
            player_type = 'bot' if bot_id else 'human' if player.get('type') == 'human' else 'unknown'
            version = player.get('version')
            version = version if type(version) is int and version > 0 else None
            exists = connection.execute('SELECT id FROM bots WHERE id=?', (bot_id,)).fetchone()
            version_row = connection.execute('SELECT id FROM bot_versions WHERE bot_id=? AND version_number=?',
                                             (bot_id, version)).fetchone() if exists and version else None
            connection.execute(
                'INSERT INTO match_players (match_id,seat,player_type,bot_id,bot_version_id,bot_id_snapshot,'
                'player_name,version_number_snapshot,snapshot_source) VALUES (?,?,?,?,?,?,?,?,?)',
                (match_id, seat, player_type, bot_id if exists else None, version_row[0] if version_row else None,
                 bot_id, str(player.get('name') or 'Unknown player'), version, 'history'))
    connection.execute("UPDATE matches SET termination_reason='unknown' WHERE status='finished'")
    connection.execute("""UPDATE matches SET
        started_at=(SELECT created_at FROM match_debug_sessions WHERE match_id=matches.id),
        finished_at=(SELECT finished_at FROM match_debug_sessions WHERE match_id=matches.id),
        error_message=(SELECT error FROM match_debug_sessions WHERE match_id=matches.id),
        termination_reason=CASE WHEN EXISTS (SELECT 1 FROM match_debug_sessions
            WHERE match_id=matches.id AND status='complete' AND error IS NULL) THEN 'normal' ELSE 'unknown' END
        WHERE status='finished'""")
    connection.execute("""UPDATE matches SET rating_status='applied'
        WHERE status='finished' AND (SELECT COUNT(DISTINCT version_id) FROM rating_history WHERE match_id=matches.id)>=2""")
    connection.execute("""UPDATE matches SET rated_at=(SELECT MAX(created_at) FROM rating_history WHERE match_id=matches.id)
        WHERE rating_status='applied'""")
    connection.execute("""UPDATE matches SET rating_status='skipped' WHERE status='finished' AND rating_status='unknown'
        AND EXISTS (SELECT 1 FROM match_players WHERE match_id=matches.id AND player_type='human')""")
    connection.execute("""UPDATE match_debug_sessions SET
        event_count=(SELECT COUNT(*) FROM match_debug_events WHERE match_id=match_debug_sessions.match_id),
        stored_bytes=COALESCE((SELECT SUM(length(CAST(payload AS BLOB))) FROM match_debug_events
            WHERE match_id=match_debug_sessions.match_id),0)""")


def migrate_schema(connection):
    if connection.in_transaction:
        raise RuntimeError('Commit or roll back before running schema migrations.')
    connection.execute('PRAGMA foreign_keys=ON')
    applied = []
    for path, checksum in pending_migrations(connection):
        connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations ('
                               'version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)')
            # Recheck under the write lock in case another startup migrated first.
            row = connection.execute('SELECT checksum FROM schema_migrations WHERE version=?', (path.stem,)).fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError(f'Applied migration was modified: {path.name}')
                connection.commit()
                continue
            if path.stem == '002_match_integrity':
                _prepare_integrity(connection)
            _execute_sql(connection, path.read_text(encoding='utf-8'))
            if path.stem == '002_match_integrity':
                _backfill_integrity(connection)
            connection.execute('INSERT INTO schema_migrations VALUES (?,?,?)', (path.stem, checksum, _now()))
            connection.commit()
            applied.append(path.stem)
        except Exception:
            connection.rollback()
            raise
    return applied


# Compatibility for callers from the first debug-mode release.
migrate_debug_schema = migrate_schema
