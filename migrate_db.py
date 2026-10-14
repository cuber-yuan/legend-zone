"""Apply additive schema changes to an EXISTING SQLite database; never reset it."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3

from db_migrations import migrate_debug_schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parent / 'legend_zone.db')
    args = parser.parse_args()
    path = args.database.resolve()
    # mode=rw deliberately refuses to create an accidental empty database.
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)) as connection:
        migrate_debug_schema(connection)
    print('Additive debug schema migration complete.')


if __name__ == '__main__':
    main()
