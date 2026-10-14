from ..db import get_db_connection
from .utils import utc_now_iso

K_FACTOR = 32
DEFAULT_RATING = 1500


def _calculate_new_ratings(rating_1, rating_2, winner):
    """
    Calculates the new ELO ratings for two bots based on the game result.
    winner: 0 for P1 win, 1 for P2 win, -1 for draw.
    """
    R_A = rating_1
    R_B = rating_2

    E_A = 1 / (1 + 10**((R_B - R_A) / 400))
    E_B = 1 / (1 + 10**((R_A - R_B) / 400))

    if winner == 0:
        S_A, S_B = 1, 0
    elif winner == 1:
        S_A, S_B = 0, 1
    else:
        S_A, S_B = 0.5, 0.5

    R_A_new = R_A + K_FACTOR * (S_A - E_A)
    R_B_new = R_B + K_FACTOR * (S_B - E_B)

    return R_A_new, R_B_new


def _latest_version(cursor, bot_id):
    cursor.execute(
        """
        SELECT id, COALESCE(rating, ?) AS rating
        FROM bot_versions
        WHERE bot_id = ?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (DEFAULT_RATING, bot_id)
    )
    return cursor.fetchone()


def record_history(cursor, bot_id, version_id, match_id, rating):
    """Append one point to the bot's rating timeline.

    Version creation uses a null match ID. Match settlement checks existing
    history under BEGIN IMMEDIATE before changing either participant's rating.
    """
    cursor.execute(
        """
        INSERT OR IGNORE INTO rating_history (bot_id, version_id, match_id, rating, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (bot_id, version_id, match_id, rating, utc_now_iso())
    )


def update_bot_ratings(player_1_id, player_2_id, winner, match_id=None):
    """Atomically rate the versions pinned at execution start, not today's latest versions."""
    p1_id = str(player_1_id)
    p2_id = str(player_2_id)

    conn = None
    try:
        conn = get_db_connection()
        # Serialize reads and writes, including the idempotency check.
        conn._conn.execute('BEGIN IMMEDIATE')
        with conn.cursor() as cursor:
            def finish(status, error=None):
                if match_id:
                    cursor.execute('UPDATE matches SET rating_status=?, rating_error=?, rated_at=? WHERE id=?',
                                   (status, error, utc_now_iso() if status == 'applied' else None, match_id))
                conn.commit()
                return status

            if match_id:
                cursor.execute('SELECT status,winner,rating_status FROM matches WHERE id=?', (match_id,))
                match = cursor.fetchone()
                if not match or match['status'] != 'finished' or match['winner'] != winner:
                    raise ValueError('Only a saved, matching result can be rated.')
                if match['rating_status'] in ('applied', 'skipped'):
                    conn.commit()
                    return match['rating_status']
                cursor.execute('SELECT p.seat,p.bot_id_snapshot,p.bot_version_id,p.snapshot_source,v.id,'
                               'COALESCE(v.rating,?) AS rating FROM match_players p '
                               'LEFT JOIN bot_versions v ON v.id=p.bot_version_id WHERE p.match_id=? ORDER BY p.seat',
                               (DEFAULT_RATING, match_id))
                versions = cursor.fetchall()
                if len(versions) != 2 or any(v['snapshot_source'] != 'execution' for v in versions):
                    raise ValueError('Actual execution versions are unknown; historical matches are not re-rated.')
                if [v['bot_id_snapshot'] for v in versions] != [p1_id, p2_id]:
                    raise ValueError('Rating participants do not match the saved execution snapshot.')
                if p1_id == p2_id:
                    return finish('skipped', 'Self-play does not change ratings.')
                if any(v['id'] is None for v in versions):
                    return finish('skipped', 'A participating bot version no longer exists.')
                v1, v2 = versions
                cursor.execute('SELECT version_id FROM rating_history WHERE match_id=?', (match_id,))
                previous = {row['version_id'] for row in cursor.fetchall()}
                if previous:
                    if previous != {v1['id'], v2['id']}:
                        raise ValueError('Partial or mismatched rating history requires manual review.')
                    return finish('applied')
            else:
                # Compatibility for direct calls that have no match record.
                if p1_id == p2_id:
                    return finish('skipped')
                v1, v2 = _latest_version(cursor, p1_id), _latest_version(cursor, p2_id)
                if not v1 or not v2:
                    return finish('skipped')

            rating_1 = v1['rating']
            rating_2 = v2['rating']
            R_1_new, R_2_new = _calculate_new_ratings(rating_1, rating_2, winner)

            cursor.execute("UPDATE bot_versions SET rating = ? WHERE id = ?", (R_1_new, v1['id']))
            cursor.execute("UPDATE bot_versions SET rating = ? WHERE id = ?", (R_2_new, v2['id']))
            record_history(cursor, p1_id, v1['id'], match_id, R_1_new)
            record_history(cursor, p2_id, v2['id'], match_id, R_2_new)
            return finish('applied')
    except Exception as exc:
        if conn:
            conn.rollback()
            if match_id:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE matches SET rating_status='failed', rating_error=? "
                                   "WHERE id=? AND status='finished' AND rating_status NOT IN ('applied','skipped')",
                                   (str(exc)[:2048], match_id))
                conn.commit()
        raise
    finally:
        if conn:
            conn.close()
