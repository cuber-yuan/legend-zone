"""Explicitly add Mini Snake to an existing database; never reset or alter tables."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db_schema import validate_schema


def register_mini_snake(database):
    database = Path(database).resolve()
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=30)) as connection:
        validate_schema(connection)
        with connection:
            cursor = connection.execute("""
                INSERT INTO games(name,description,min_players,max_players)
                VALUES ('Mini Snake','Snake battle on a fixed 10-row by 11-column map',2,2)
                ON CONFLICT(name) DO NOTHING
            """)
            return cursor.rowcount == 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'legend_zone.db')
    args = parser.parse_args()
    try:
        added = register_mini_snake(args.db)
    except (sqlite3.Error, RuntimeError) as error:
        parser.exit(1, f'Unable to register Mini Snake: {error}\n')
    print('Mini Snake registered.' if added else 'Mini Snake is already registered; no changes made.')


if __name__ == '__main__':
    main()
