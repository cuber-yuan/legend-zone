"""Back up and migrate an existing SQLite database without starting the application."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from db_migrations import migrate_schema, pending_migrations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parent / 'legend_zone.db')
    parser.add_argument('--check', action='store_true', help='Only list pending migrations.')
    parser.add_argument('--backup', type=Path, help='New backup file path; by default use a timestamped sibling.')
    args = parser.parse_args()
    path = args.database.resolve()
    with closing(sqlite3.connect(path.as_uri() + ('?mode=ro' if args.check else '?mode=rw'), uri=True, timeout=30)) as connection:
        pending = pending_migrations(connection)
        if args.check:
            print('Pending: ' + (', '.join(p.stem for p, _ in pending) or 'none'))
            return
        if pending:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = (args.backup or path.with_name(f'{path.stem}.backup-{stamp}.db')).resolve()
            if backup == path:
                parser.error('Backup must be a different file.')
            # Exclusive creation prevents accidentally overwriting an existing backup.
            with backup.open('xb'):
                pass
            with closing(sqlite3.connect(backup)) as destination:
                connection.backup(destination)
            print(f'Backup saved: {backup}')
        applied = migrate_schema(connection)
        print('Applied: ' + (', '.join(applied) or 'none (already current)'))
        violations = connection.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            print(f'Existing foreign-key violations require review: {len(violations)}. No rows were deleted.')


if __name__ == '__main__':
    main()
