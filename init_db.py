import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'legend_zone.db')


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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            players TEXT,
            winner INTEGER,
            displays TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.commit()
    conn.close()
    print(f"SQLite database initialized at: {DB_PATH}")


if __name__ == '__main__':
    init_db()
