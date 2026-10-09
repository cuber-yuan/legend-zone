import sqlite3
import os


class DictLiteCursor:
    """sqlite3 cursor wrapper that returns dict-like rows, mimicking pymysql DictCursor."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        query = query.replace('%s', '?')
        if params is None:
            self._cursor.execute(query)
        else:
            self._cursor.execute(query, params)
        return self

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        return [dict(row) for row in self._cursor.fetchall()]

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class DictLiteConnection:
    """sqlite3 connection wrapper that mimics pymysql connection interface."""

    def __init__(self, db_path):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def cursor(self, cursorclass=None):
        return DictLiteCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_db_connection():
    """Returns a SQLite connection with dict cursor interface."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'legend_zone.db')
    return DictLiteConnection(db_path)
