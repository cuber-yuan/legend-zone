import uuid
import json
from ..db import get_db_connection
from .utils import utc_now_iso

# Whitelist the per-game payload column so the f-string SQL stays injection-safe.
_PAYLOAD_COLS = {'move_history', 'displays'}


def state_payload(game, extra=None):
    """Serialize judge state into a client update payload.

    current_player and player_types are what let the browser decide whether a
    click is actually a legal move. Without them a human cannot tell whose turn
    it is, so either every click is accepted (letting a player move out of
    turn) or none are (which is the bug that made human games unplayable).
    Deriving both from the judge keeps the three games from drifting apart.
    """
    payload = {
        'board': game.board,
        'winner': game.winner,
        'game_id': game.game_id,
        'current_player': game.current_player,
        'player_types': {
            '1': game.black_player_type,
            '2': game.white_player_type,
        },
    }
    if extra:
        payload.update(extra)
    return payload


def create_match_record(game, players_json, status='playing'):
    """Insert a fresh matches row and return its generated id."""
    match_id = uuid.uuid4().hex
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO matches (id, game, players, status, created_at, rating_status) VALUES (?, ?, ?, ?, ?, 'unknown')",
                (match_id, game, players_json, status, utc_now_iso())
            )
            conn.commit()
    finally:
        if conn:
            conn.close()
    return match_id


def bind_match_players(match_id, players_json, player_types, executors):
    """Lock actual executor versions once; setup-page version snapshots are not authoritative."""
    try:
        players = json.loads(players_json) if isinstance(players_json, str) else players_json
    except (TypeError, ValueError):
        players = {}
    if not isinstance(players, dict):
        players = {}
    with get_db_connection() as conn:
        try:
            conn._conn.execute('BEGIN IMMEDIATE')
            with conn.cursor() as cursor:
                cursor.execute('SELECT status, started_at FROM matches WHERE id=?', (match_id,))
                match = cursor.fetchone()
                if not match or match['status'] != 'playing' or match['started_at'] is not None:
                    raise ValueError('Match is missing, finished or already started.')
                for seat, player_type in enumerate(player_types, 1):
                    player = players.get(f'player_{seat}', {})
                    player = dict(player) if isinstance(player, dict) else {'name': str(player)}
                    executor = executors[seat - 1] if seat <= len(executors) else None
                    version_id = getattr(executor, 'version_id', None)
                    bot_id = getattr(executor, 'bot_id', None)
                    bot_id = str(bot_id) if isinstance(bot_id, (str, int)) else player.get('bot_id')
                    cursor.execute('SELECT id FROM bots WHERE id=?', (bot_id,))
                    bot_exists = cursor.fetchone() if player_type == 'bot' else None
                    version = None
                    if player_type == 'bot' and type(version_id) is int:
                        cursor.execute('SELECT id, bot_id, version_number FROM bot_versions WHERE id=?', (version_id,))
                        version = cursor.fetchone()
                        if version and version['bot_id'] != bot_id:
                            raise ValueError('Executor version does not belong to the selected bot.')
                    if player_type == 'bot':
                        actual_name = getattr(executor, 'bot_name', None)
                        if isinstance(actual_name, str):
                            player['name'] = actual_name
                        number = version['version_number'] if version else getattr(executor, 'version_number', None)
                        number = number if type(number) is int and number > 0 else None
                        player.update(bot_id=bot_id, version=number)
                    else:
                        bot_id, number = None, None
                        player = {'name': player.get('name') or 'HUMAN', 'type': 'human'}
                    player['name'] = str(player.get('name') or 'Unknown player')
                    players[f'player_{seat}'] = player
                    cursor.execute('DELETE FROM match_players WHERE match_id=? AND seat=?', (match_id, seat))
                    cursor.execute('INSERT INTO match_players (match_id,seat,player_type,bot_id,bot_version_id,'
                                   'bot_id_snapshot,player_name,version_number_snapshot,snapshot_source) '
                                   "VALUES (?,?,?,?,?,?,?,?,'execution')",
                                   (match_id, seat, player_type, bot_id if bot_exists else None,
                                    version['id'] if version else None, bot_id, player['name'], number))
                normalized = json.dumps(players)
                cursor.execute('UPDATE matches SET players=?, started_at=?, rating_status=? WHERE id=?',
                               (normalized, utc_now_iso(), 'pending' if player_types == ('bot', 'bot') else 'skipped', match_id))
            conn.commit()
            return normalized
        except Exception:
            conn.rollback()
            raise


def finalize_match_record(match_id, game, players_json, winner, payload_json, payload_col,
                          termination_reason='normal', error_message=None, rated=True):
    """Close out an interactive match: UPDATE the row when match_id is known,
    otherwise INSERT a completed row (the legacy no-match-id game-page path)."""
    if payload_col not in _PAYLOAD_COLS:
        raise ValueError(f"invalid payload column: {payload_col}")
    saved_id = match_id or uuid.uuid4().hex
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if match_id:
                cursor.execute(
                    f"UPDATE matches SET players=?, winner=?, {payload_col}=?, status='finished', "
                    'finished_at=?, termination_reason=?, error_message=?, rating_status=?, rating_error=NULL '
                    "WHERE id=? AND status='playing'",
                    (players_json, winner, payload_json, utc_now_iso(), termination_reason, error_message,
                     'pending' if rated else 'skipped', match_id)
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"match not found: {match_id}")
            else:
                cursor.execute(
                    f"INSERT INTO matches (id,game,players,winner,{payload_col},status,created_at,finished_at,"
                    "termination_reason,error_message,rating_status) VALUES (?,?,?,?,?,'finished',?,?,?,?,?)",
                    (saved_id, game, players_json, winner, payload_json, utc_now_iso(), utc_now_iso(),
                     termination_reason, error_message, 'pending' if rated else 'skipped')
                )
            conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
    return saved_id
