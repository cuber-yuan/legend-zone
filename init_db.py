import sqlite3
from contextlib import closing
import os
import sys
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
from db_schema import initialize_schema


DB_PATH = os.path.join(os.path.dirname(__file__), 'legend_zone.db')


def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Deleted database: {DB_PATH}")
    else:
        print(f"Database not found: {DB_PATH}")


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()

        initialize_schema(conn)

        # Insert test data
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            password_hash = generate_password_hash('123456')
            cursor.execute(
                "INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
                ('admin', password_hash, 'cuber_yuan@outlook.com', now)
            )
            print("Inserted test user: admin")

        # Seed per-game rather than "only if the table is empty": an existing
        # database (yours or production's) would otherwise never learn about a game
        # added later. name is UNIQUE, so INSERT OR IGNORE makes this re-runnable.
        default_games = [
            ('Gomoku', 'Five in a row', 1, 2, 2),
            ('Snake', 'Snake battle game', 1, 2, 2),
            ('Mini Snake', 'Snake battle on a fixed 10-row by 11-column map', 1, 2, 2),
            ('Tank Battle', 'Tank battle game', 1, 2, 2),
            ('Tic Tac Toe', 'Classic 3x3 noughts and crosses', 1, 2, 2),
            ('Connect Four', 'Drop discs into columns and line up four in a row', 1, 2, 2),
        ]
        added = []
        for game in default_games:
            cursor.execute("SELECT 1 FROM games WHERE name = ?", (game[0],))
            if cursor.fetchone():
                continue
            cursor.execute(
                "INSERT INTO games (name, description, author_id, min_players, max_players, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                game + (now,)
            )
            added.append(game[0])
        if added:
            print(f"Inserted missing default games: {added}")

        conn.commit()
    print(f"SQLite database initialized at: {DB_PATH}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    init_db()
