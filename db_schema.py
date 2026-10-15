"""Current SQLite schema initialization and read-only structure checks.

No historical upgrades, data backfills, application startup or user-data reads.
"""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import sqlite3

SCHEMA_PATH = Path(__file__).resolve().with_name('schema.sql')
DATABASE_PATH = SCHEMA_PATH.with_name('legend_zone.db')


@lru_cache(maxsize=1)
def _required_structure():
    # Derive checks from the single schema definition, without duplicating columns
    # or requiring old databases to have identical native FK/CHECK declarations.
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        objects = reference.execute("SELECT type,name,tbl_name FROM sqlite_master "
                                    "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
        columns = {name: {row[1] for row in reference.execute(f'PRAGMA table_info("{name}")')}
                   for kind, name, _ in objects if kind == 'table'}
    return objects, columns


def validate_schema(connection):
    """Check object/column presence using metadata only; never upgrade a database."""
    objects, columns = _required_structure()
    actual = {(row[0], row[1], row[2]) for row in connection.execute(
        'SELECT type,name,tbl_name FROM sqlite_master')}
    missing = [f'{kind} {name}' for kind, name, table in objects if (kind, name, table) not in actual]
    for table, expected in columns.items():
        present = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        missing.extend(f'{table}.{column}' for column in sorted(expected - present))
    if missing:
        raise RuntimeError('Database structure is incomplete: ' + ', '.join(missing) +
                           '. Initialize an empty database with python init_db.py; '
                           'existing databases require a matching completed schema.')


def check_database(path=DATABASE_PATH):
    """Read-only startup check; missing paths must not become empty databases."""
    path = Path(path).resolve()
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)) as connection:
            validate_schema(connection)
    except sqlite3.Error as error:
        raise RuntimeError('Unable to read the database. For a new installation, '
                           'run python init_db.py from the project root.') from error


def initialize_schema(connection):
    """Create the full schema in an empty DB; validate an existing DB unchanged."""
    if connection.in_transaction:
        raise RuntimeError('Commit or roll back before initializing the database.')
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
    if exists:
        validate_schema(connection)
        return False
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        connection.executescript('BEGIN IMMEDIATE;\n' + SCHEMA_PATH.read_text(encoding='utf-8') + '\nCOMMIT;')
    except Exception:
        connection.rollback()
        raise
    return True
