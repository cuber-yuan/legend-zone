import sqlite3
import os
import sys
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
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bot_name TEXT NOT NULL,
            game TEXT NOT NULL,
            description TEXT,
            source_code TEXT,
            file_path TEXT,
            language TEXT DEFAULT 'cpp',
            rating INTEGER DEFAULT 1500,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            game TEXT NOT NULL,
            players TEXT,
            winner INTEGER,
            displays TEXT,
            status TEXT DEFAULT 'playing',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
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
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.commit()
    
    # Insert test data
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        password_hash = generate_password_hash('123456')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            ('admin', password_hash, 'cuber_yuan@outlook.com')
        )
        print("Inserted test user: admin")
    
    cursor.execute("SELECT COUNT(*) FROM games")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO games (name, description, author_id, min_players, max_players) VALUES (?, ?, ?, ?, ?)",
            ('Gomoku', 'Five in a row', 1, 2, 2)
        )
        print("Inserted test game: Gomoku")
    
    conn.commit()
    conn.close()
    print(f"SQLite database initialized at: {DB_PATH}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    init_db()
