from ..db import get_db_connection


def load_latest_version(bot_id):
    """Return latest bot_versions row joined with parent bot metadata.

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
                       bv.source_code,
                       bv.file_path,
                       bv.rating       AS version_rating,
                       b.id            AS bot_id,
                       b.bot_name,
                       b.language,
                       b.game,
                       b.user_id
                FROM bots b
                JOIN bot_versions bv ON bv.bot_id = b.id
                WHERE b.id = ?
                ORDER BY bv.version_number DESC
                LIMIT 1
                """,
                (bot_id,)
            )
            return cursor.fetchone()
    finally:
        if conn:
            conn.close()


def player_json_for_bot(bot_id):
    rec = load_latest_version(bot_id)
    if not rec:
        return {"name": str(bot_id)}
    return {"name": rec['bot_name'], "bot_id": rec['bot_id'], "version": rec['version_number']}


def player_json_for_human(label="HUMAN"):
    return {"name": label, "type": "human"}
