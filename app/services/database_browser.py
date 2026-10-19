"""Bounded, read-only database browsing for the administrator UI."""
from contextlib import closing
import sqlite3

from db_schema import DATABASE_PATH

CELL_LIMIT = 1000
HIDDEN_COLUMNS = {'password', 'password_hash', 'source_code', 'secret', 'secret_key', 'api_key', 'token'}


def _connect():
    return sqlite3.connect(DATABASE_PATH.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _table_names(connection):
    return [row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")]


def list_tables():
    with closing(_connect()) as connection:
        return _table_names(connection)


def read_table(name, page=1, page_size=25):
    if page < 1 or page_size not in (25, 50, 100):
        raise ValueError('Invalid pagination.')
    with closing(_connect()) as connection:
        connection.execute('BEGIN')
        if name not in _table_names(connection):
            raise LookupError('Table not found.')
        table = _quote(name)
        info = connection.execute(f'PRAGMA table_info({table})').fetchall()
        columns = [{'name': row[1], 'type': row[2], 'primary_key': bool(row[5]),
                    'hidden': row[1].lower() in HIDDEN_COLUMNS} for row in info]
        total = connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        expressions = []
        for column in columns:
            identifier = _quote(column['name'])
            if column['hidden']:
                expressions.append('NULL')  # Never read protected values into Python.
            else:
                expressions.append(f"CASE WHEN typeof({identifier})='blob' "
                                   f"THEN '[BLOB] ' || hex(substr({identifier},1,64)) "
                                   f"WHEN typeof({identifier})='text' THEN substr({identifier},1,{CELL_LIMIT + 1}) "
                                   f'ELSE {identifier} END')
        keys = [_quote(row[1]) for row in sorted(info, key=lambda row: row[5]) if row[5]]
        order = ','.join(keys) if keys else 'rowid'
        rows = connection.execute(f"SELECT {','.join(expressions)} FROM {table} ORDER BY {order} LIMIT ? OFFSET ?",
                                  (page_size, (page - 1) * page_size)).fetchall()
        return {'name': name, 'columns': columns, 'rows': rows, 'total': total,
                'page': page, 'pages': pages, 'page_size': page_size, 'cell_limit': CELL_LIMIT}
