from ..db import get_db_connection

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


def update_bot_ratings(player_1_id, player_2_id, winner):
    """
    Fetches current ratings, calculates new ratings, and updates the database.
    player_1_id and player_2_id must be integers (bot IDs).
    """
    p1_id_int = int(player_1_id)
    p2_id_int = int(player_2_id)

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, COALESCE(rating, ?) AS rating FROM bots WHERE id IN (?, ?)",
                (DEFAULT_RATING, p1_id_int, p2_id_int)
            )

            bots_data = {row['id']: row['rating'] for row in cursor.fetchall()}

            rating_1 = bots_data.get(p1_id_int)
            rating_2 = bots_data.get(p2_id_int)

            if rating_1 is None or rating_2 is None:
                print("Error: Could not retrieve ratings for both bots. Check if IDs exist or match the returned type.")
                return

            R_1_new, R_2_new = _calculate_new_ratings(rating_1, rating_2, winner)

            cursor.execute("UPDATE bots SET rating = ? WHERE id = ?", (R_1_new, player_1_id))
            cursor.execute("UPDATE bots SET rating = ? WHERE id = ?", (R_2_new, player_2_id))
            conn.commit()
            print(f"Ratings updated. P1({player_1_id}): {rating_1:.2f} -> {R_1_new:.2f}, P2({player_2_id}): {rating_2:.2f} -> {R_2_new:.2f}")

    except Exception as e:
        print("Failed to update bot ratings:", e)
    finally:
        if conn:
            conn.close()
