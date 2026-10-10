import uuid
from ..db import get_db_connection
from .utils import utc_now_iso

# Whitelist the per-game payload column so the f-string SQL stays injection-safe.
_PAYLOAD_COLS = {'move_history', 'displays'}


def create_match_record(game, players_json, status='playing'):
    """Insert a fresh matches row and return its generated id."""
    match_id = uuid.uuid4().hex
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO matches (id, game, players, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (match_id, game, players_json, status, utc_now_iso())
            )
            conn.commit()
    finally:
        if conn:
            conn.close()
    return match_id


def finalize_match_record(match_id, game, players_json, winner, payload_json, payload_col):
    """Close out an interactive match: UPDATE the row when match_id is known,
    otherwise INSERT a completed row (the legacy no-match-id game-page path)."""
    if payload_col not in _PAYLOAD_COLS:
        raise ValueError(f"invalid payload column: {payload_col}")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if match_id:
                cursor.execute(
                    f"UPDATE matches SET players = ?, winner = ?, {payload_col} = ?, status = 'finished' WHERE id = ?",
                    (players_json, winner, payload_json, match_id)
                )
            else:
                cursor.execute(
                    f"INSERT INTO matches (id, game, players, winner, {payload_col}, status, created_at) VALUES (?, ?, ?, ?, ?, 'finished', ?)",
                    (uuid.uuid4().hex, game, players_json, winner, payload_json, utc_now_iso())
                )
            conn.commit()
    except Exception as e:
        print("Failed to save match record:", e)
    finally:
        if conn:
            conn.close()


def update_match_result(match_id, winner, payload_json, payload_col):
    """Write winner + payload onto an existing match row (auto-ladder finish,
    where players was already recorded at creation time)."""
    if payload_col not in _PAYLOAD_COLS:
        raise ValueError(f"invalid payload column: {payload_col}")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE matches SET winner = ?, {payload_col} = ?, status = 'finished' WHERE id = ?",
                (winner, payload_json, match_id)
            )
            conn.commit()
    except Exception as e:
        print("Failed to update match record:", e)
    finally:
        if conn:
            conn.close()
