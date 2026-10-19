"""Explicit one-time users-table update; never called by application startup."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db_schema import validate_schema


def update_user_access(database, admin_username=None):
    database = Path(database).resolve()
    backup = None
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=30)) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(users)')}
            if not columns:
                raise ValueError('The users table does not exist.')
            if admin_username is not None:
                if not conn.execute('SELECT 1 FROM users WHERE username=?', (admin_username,)).fetchone():
                    raise ValueError('The specified administrator account does not exist.')
            definitions = {
                'role': "TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin'))",
                'membership': "TEXT NOT NULL DEFAULT 'standard' CHECK (membership IN ('standard','vip'))",
            }
            missing = [column for column in definitions if column not in columns]
            promote = admin_username is not None and ('role' not in columns or conn.execute(
                'SELECT role FROM users WHERE username=?', (admin_username,)).fetchone()[0] != 'admin')
            if missing or promote:
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                backup = database.with_name(database.name + '.user-access-' + stamp + '.bak')
                # A separate reader can back up while this transaction holds the
                # writer reservation, keeping the pre-update snapshot consistent.
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=30)) as reader, \
                     closing(sqlite3.connect(backup)) as target:
                    reader.backup(target)
                for column in missing:
                    conn.execute(f'ALTER TABLE users ADD COLUMN {column} {definitions[column]}')
                if promote:
                    conn.execute("UPDATE users SET role='admin' WHERE username=?", (admin_username,))
            validate_schema(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'legend_zone.db')
    parser.add_argument('--admin', help='Existing username to explicitly grant administrator access.')
    args = parser.parse_args()
    try:
        backup = update_user_access(args.db, args.admin)
    except (sqlite3.Error, ValueError, RuntimeError) as error:
        parser.exit(1, f'User access update failed: {error}\n')
    if backup:
        print(f'Pre-update backup: {backup}')
    print('User access schema is up to date.' + (' Administrator access configured.' if args.admin else ''))


if __name__ == '__main__':
    main()
