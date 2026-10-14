"""Small additive migrations, usable without importing/starting the Flask app."""
from pathlib import Path


def migrate_debug_schema(connection):
    source = Path(__file__).resolve().parent / 'migrations' / '001_match_debug.sql'
    connection.executescript(source.read_text(encoding='utf-8'))
    connection.commit()
