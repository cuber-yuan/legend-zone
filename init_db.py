import sqlite3
import os
import sys
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash


DB_PATH = os.path.join(os.path.dirname(__file__), 'legend_zone.db')


def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Deleted database: {DB_PATH}")
    else:
        print(f"Database not found: {DB_PATH}")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            bot_name TEXT NOT NULL,
            game TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'cpp',
            is_private INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            UNIQUE (bot_name, game)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            description TEXT,
            source_code TEXT,
            file_path TEXT,
            rating REAL DEFAULT 1500,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE,
            UNIQUE (bot_id, version_number)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            game TEXT NOT NULL,
            players TEXT,
            winner INTEGER,
            displays TEXT,
            move_history TEXT,
            status TEXT DEFAULT 'playing',
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            author_id INTEGER,
            min_players INTEGER DEFAULT 2,
            max_players INTEGER DEFAULT 4,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rating_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT NOT NULL,
            version_id INTEGER NOT NULL,
            match_id TEXT,
            rating REAL NOT NULL,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            UNIQUE (version_id, match_id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rating_history_bot
            ON rating_history (bot_id, created_at)
    """)

    # Columns added after a table first shipped. CREATE TABLE IF NOT EXISTS never
    # alters an existing table, so databases created before the change (including
    # production) need an idempotent ALTER. Re-running is harmless: SQLite reports
    # "duplicate column name" once the column is present.
    #
    # DEFAULT 0 keeps every pre-existing bot public. New bots are private because
    # upload_bot passes is_private=1 explicitly rather than leaning on this default.
    for table, column, ddl in (
        ('bots', 'is_private', 'INTEGER NOT NULL DEFAULT 0'),
    ):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            print(f"Added column {table}.{column}")
        except sqlite3.OperationalError as exc:
            if 'duplicate column' not in str(exc).lower():
                raise

    conn.commit()
    
    # Insert test data
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        password_hash = generate_password_hash('123456')
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
            ('admin', password_hash, 'cuber_yuan@outlook.com', now)
        )
        print("Inserted test user: admin")
    
    cursor.execute("SELECT COUNT(*) FROM games")
    if cursor.fetchone()[0] == 0:
        default_games = [
            ('Gomoku', 'Five in a row', 1, 2, 2),
            ('Snake', 'Snake battle game', 1, 2, 2),
            ('Tank Battle', 'Tank battle game', 1, 2, 2),
            ('Tic Tac Toe', 'Classic 3x3 noughts and crosses', 1, 2, 2),
        ]
        for game in default_games:
            cursor.execute(
                "INSERT INTO games (name, description, author_id, min_players, max_players, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                game + (now,)
            )
        print(f"Inserted {len(default_games)} default games: {[g[0] for g in default_games]}")
    
    conn.commit()
    conn.close()
    print(f"SQLite database initialized at: {DB_PATH}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    init_db()
