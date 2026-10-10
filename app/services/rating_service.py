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


def _already_scored(cursor, match_id):
    """True if this match already moved any rating.

    Guards the ELO update itself, not just the history insert: re-applying a
    match would compound the delta on bot_versions.rating while the timeline
    stayed put, silently desyncing the chart from the live number.
    """
    cursor.execute("SELECT 1 FROM rating_history WHERE match_id = ? LIMIT 1", (match_id,))
    return cursor.fetchone() is not None


def record_history(cursor, bot_id, version_id, match_id, rating):
    """Append one point to the bot's rating timeline.

    INSERT OR IGNORE keeps a UNIQUE(version_id, match_id) collision from
    raising and rolling back the rating UPDATEs sharing this transaction;
    _already_scored is what actually prevents a repeat.
    """
    cursor.execute(
        """
        INSERT OR IGNORE INTO rating_history (bot_id, version_id, match_id, rating, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (bot_id, version_id, match_id, rating, utc_now_iso())
    )


def update_bot_ratings(player_1_id, player_2_id, winner, match_id=None):
    """Update ELO on the latest bot_versions row for each bot.

    player_1_id / player_2_id are logical bot IDs (bots.id). Rating lives on
    bot_versions so a rewrite inherits its predecessor's rating at creation
    and only the currently-competing version's number moves after a match.
    match_id links the appended rating_history points back to the game; it is
    null on the legacy game-page path that never created a match row.
    """
    p1_id_int = int(player_1_id)
    p2_id_int = int(player_2_id)

    if p1_id_int == p2_id_int:
        print(f"Self-play match for bot {p1_id_int}: rating unchanged.")
        return

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if match_id and _already_scored(cursor, match_id):
                print(f"Match {match_id} already scored: rating unchanged.")
                return

            v1 = _latest_version(cursor, p1_id_int)
            v2 = _latest_version(cursor, p2_id_int)
            if not v1 or not v2:
                print(f"Error: no version found for bot {p1_id_int} or {p2_id_int}")
                return

            rating_1 = v1['rating']
            rating_2 = v2['rating']
            R_1_new, R_2_new = _calculate_new_ratings(rating_1, rating_2, winner)

            cursor.execute("UPDATE bot_versions SET rating = ? WHERE id = ?", (R_1_new, v1['id']))
            cursor.execute("UPDATE bot_versions SET rating = ? WHERE id = ?", (R_2_new, v2['id']))
            record_history(cursor, p1_id_int, v1['id'], match_id, R_1_new)
            record_history(cursor, p2_id_int, v2['id'], match_id, R_2_new)
            conn.commit()
            print(f"Ratings updated. P1({p1_id_int}/v-vid {v1['id']}): {rating_1:.2f} -> {R_1_new:.2f}, "
                  f"P2({p2_id_int}/v-vid {v2['id']}): {rating_2:.2f} -> {R_2_new:.2f}")
    except Exception as e:
        print("Failed to update bot ratings:", e)
    finally:
        if conn:
            conn.close()
