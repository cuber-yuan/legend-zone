import pymysql
import os

# --- ELO Rating Constants ---
K_FACTOR = 32
DEFAULT_RATING = 1500

def get_db_connection():
    """Returns a connection to the MySQL database."""
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def _calculate_new_ratings(rating_1, rating_2, winner):
    """
    Calculates the new ELO ratings for two bots based on the game result.
    winner: 0 for P1 win, 1 for P2 win, -1 for draw.
    """
    R_A = rating_1
    R_B = rating_2

    # Calculate Expected Scores
    E_A = 1 / (1 + 10**((R_B - R_A) / 400))
    E_B = 1 / (1 + 10**((R_A - R_B) / 400))

    # Determine Actual Scores (S)
    if winner == 0:  # Player 1 (A) wins
        S_A, S_B = 1, 0
    elif winner == 1:  # Player 2 (B) wins
        S_A, S_B = 0, 1
    else:  # Draw or error (-1)
        S_A, S_B = 0.5, 0.5

    # Calculate New Ratings
    R_A_new = R_A + K_FACTOR * (S_A - E_A)
    R_B_new = R_B + K_FACTOR * (S_B - E_B)

    return R_A_new, R_B_new


def update_bot_ratings(player_1_id, player_2_id, winner):
    """
    Fetches current ratings, calculates new ratings, and updates the database.
    player_1_id and player_2_id must be integers (bot IDs).
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. Fetch current ratings
            # Use DEFAULT_RATING if the rating column is NULL
            sql = "SELECT id, COALESCE(rating, %s) AS rating FROM bots WHERE id IN (%s, %s)"
            print(sql)
            cursor.execute("SELECT id, COALESCE(rating, %s) AS rating FROM bots WHERE id IN (%s, %s)",
                           (DEFAULT_RATING, player_1_id, player_2_id))
            bots_data = {row['id']: row['rating'] for row in cursor.fetchall()}

            rating_1 = bots_data.get(player_1_id)
            rating_2 = bots_data.get(player_2_id)

            if rating_1 is None or rating_2 is None:
                print("Error: Could not retrieve ratings for both bots.")
                return

            # 2. Calculate new ratings
            R_1_new, R_2_new = _calculate_new_ratings(rating_1, rating_2, winner)

            # 3. Update ratings in the database
            cursor.execute("UPDATE bots SET rating = %s WHERE id = %s", (R_1_new, player_1_id))
            cursor.execute("UPDATE bots SET rating = %s WHERE id = %s", (R_2_new, player_2_id))
            conn.commit()
            print(f"Ratings updated. P1({player_1_id}): {rating_1:.2f} -> {R_1_new:.2f}, P2({player_2_id}): {rating_2:.2f} -> {R_2_new:.2f}")

    except Exception as e:
        print("Failed to update bot ratings:", e)
    finally:
        if conn:
            conn.close()