import json
from ..db import get_db_connection
from ..code_executor import CodeExecutor


def load_version(bot_id, version_number=None):
    """Return the selected version (latest by default) with parent bot metadata.

    Uses bot_versions.version_number (not id) so the "current" version stays
    stable even if rows were ever backfilled out of order.
    """
    if not bot_id:
        return None
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT bv.id AS version_id,
                       bv.version_number,
                       bv.description AS version_description,
                       bv.file_path,
                       bv.rating       AS version_rating,
                       b.id            AS bot_id,
                       b.bot_name,
                       b.language,
                       b.game,
                       b.user_id
                FROM bots b
                JOIN bot_versions bv ON bv.bot_id = b.id
                WHERE b.id = ? AND (? IS NULL OR bv.version_number = ?)
                ORDER BY bv.version_number DESC
                LIMIT 1
                """,
                (bot_id, version_number, version_number)
            )
            return cursor.fetchone()
    finally:
        if conn:
            conn.close()


def load_latest_version(bot_id):
    return load_version(bot_id)


def player_json_for_bot(bot_id, version_number=None):
    rec = load_version(bot_id, version_number)
    if not rec:
        return {"name": str(bot_id)}
    return {"name": rec['bot_name'], "bot_id": rec['bot_id'], "version": rec['version_number']}


def player_json_for_human(label="HUMAN"):
    return {"name": label, "type": "human"}


def get_bot_executor(bot_id, version_number=None, *, match_id=None, seat=None):
    """Use the saved selection for manual matches; default to latest otherwise."""
    if match_id:
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute('SELECT players, status, started_at FROM matches WHERE id=?', (match_id,))
            match = cursor.fetchone()
        if not match or match['status'] != 'playing' or match['started_at'] is not None:
            raise ValueError('Match is missing, finished or already started.')
        player = json.loads(match['players']).get(f'player_{seat}', {})
        if player.get('type') == 'human' or str(player.get('bot_id')) != str(bot_id):
            raise ValueError('Bot does not match the saved seat.')
        version_number = player.get('version')
    rec = load_version(bot_id, version_number)
    if not rec:
        return None
    executor = CodeExecutor(workdir=rec['file_path'], language=rec['language'])
    executor.bot_id = rec['bot_id']
    executor.version_id = rec['version_id']
    executor.version_number = rec['version_number']
    executor.bot_name = rec['bot_name']
    return executor


def build_players_json(p1_id, p1_type, p2_id, p2_type, human_name=None):
    """Serialize the matches.players JSON object for two slots (bot or human).

    A human match is always started by one signed-in session, which steers both
    seats of a hot seat, so a single name covers every human slot. Without it the
    slot falls back to the generic label the UI has shown historically.
    """
    def human():
        return player_json_for_human(human_name or 'HUMAN')

    p1 = player_json_for_bot(p1_id) if p1_type == 'bot' else human()
    p2 = player_json_for_bot(p2_id) if p2_type == 'bot' else human()
    return json.dumps({'player_1': p1, 'player_2': p2})
