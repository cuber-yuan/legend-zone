"""Bot 比赛列表验证，仅使用临时数据库。"""
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import DictLiteConnection
from app.services.match_listing import format_match, recent_bot_matches
from db_schema import initialize_schema


class BotMatchesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.db'
        with closing(sqlite3.connect(self.path)) as conn, conn:
            initialize_schema(conn)
            conn.execute("INSERT INTO users(id, username, password_hash) VALUES (1,'owner','unused')")
            for bid in ('target', 'other'):
                conn.execute("INSERT INTO bots(id,user_id,bot_name,game) VALUES (?,1,?,'Connect Four')", (bid, bid))

    def add_match(self, mid, players, seat=None, status='finished'):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO matches(id,game,players,winner,status,created_at) VALUES (?,'Connect Four',?,0,?,?)",
                         (mid, json.dumps(players), status, mid))
            if seat:
                conn.execute("""INSERT INTO match_players(match_id,seat,player_type,bot_id,
                             player_name,snapshot_source) VALUES (?,1,'bot',?,?,'execution')""", (mid, seat, seat))

    def matches(self):
        with DictLiteConnection(self.path) as conn, conn.cursor() as cursor:
            return recent_bot_matches(cursor, 'target')

    def test_identity_both_seats_versions_and_limit(self):
        for number in range(25):
            key = 'player_1' if number % 2 else 'player_2'
            self.add_match(f'{number:02}', {key: {'bot_id': 'target', 'name': 'Snapshot', 'version': number + 1}}, 'target')
        self.add_match('99', {'player_1': {'bot_id': 'target'}}, 'target', 'playing')
        self.add_match('98', {'player_1': {'name': 'target', 'bot_id': 'other'}}, 'other')
        rows = self.matches()
        self.assertEqual([row['id'] for row in rows], [f'{n:02}' for n in range(24, 4, -1)])
        self.assertEqual(rows[0]['player_2_version'], 25)
        self.assertNotIn('move_history', rows[0])

    def test_legacy_json_fallback_and_recorded_identity(self):
        self.add_match('01', {'player_2': {'bot_id': 'target', 'name': 'Old name', 'version': 1}})
        self.add_match('02', {'player_1': 'target'})
        self.add_match('03', {'player_1': {'bot_id': 'target'}}, 'other')
        self.add_match('04', [])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE matches SET players='invalid json' WHERE id='04'")
        self.assertEqual([m['id'] for m in self.matches()], ['01'])
        for payload in ('invalid', '[]', 'null', '{"player_1":"Old name"}'):
            row = format_match({'players': payload})
            self.assertIn('player_1', row)

    def test_detail_keeps_private_source_out_of_context(self):
        import importlib
        from flask import Flask
        main = importlib.import_module('app.main')
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE bots SET is_private=1 WHERE id='target'")
            conn.execute("INSERT INTO bot_versions(bot_id,version_number,source_code) VALUES ('target',1,'SECRET_FIXTURE')")
        self.add_match('01', {'player_1': {'bot_id': 'target', 'name': 'Snapshot'}})
        web = Flask(__name__)
        with web.test_request_context('/bot/target'), \
             patch.object(main, 'get_db_connection', lambda: DictLiteConnection(self.path)), \
             patch.object(main, 'current_user', SimpleNamespace(is_authenticated=False)), \
             patch.object(main, 'render_template', side_effect=lambda template, **context: context):
            context = main.bot_detail('target')
        self.assertNotIn('source_code', context['bot'])
        self.assertEqual(len(context['recent_matches']), 1)

    def test_rating_changes_use_each_versions_previous_record(self):
        for mid in ('01', '02', '03', '04', '05', '06', '07'):
            self.add_match(mid, {'player_1': {'bot_id': 'target', 'name': 'Snapshot'}}, 'target')
        with closing(sqlite3.connect(self.path)) as conn, conn:
            versions = []
            for number in (1, 2, 3):
                versions.append(conn.execute(
                    "INSERT INTO bot_versions(bot_id,version_number) VALUES ('target',?)",
                    (number,)).lastrowid)
            for version, mid, rating in [(0,None,1500), (0,'01',1516.125),
                                         (1,None,1800), (1,'02',1788),
                                         (0,'03',1516.125), (2,'07',1501)]:
                conn.execute("INSERT INTO rating_history(bot_id,version_id,match_id,rating) VALUES ('target',?,?,?)",
                             (versions[version], mid, rating))
            conn.execute("UPDATE matches SET rating_status='skipped' WHERE id='04'")
            conn.execute("UPDATE matches SET rating_status='failed' WHERE id='05'")
            conn.execute("UPDATE matches SET rating_status='applied' WHERE id IN ('01','02','03','07')")
        changes = {m['id']: m['rating_delta'] for m in self.matches()}
        self.assertEqual(changes, {'01':16.125, '02':-12, '03':0, '04':0,
                                   '05':None, '06':None, '07':None})

    def test_human_matches_show_no_rating_change(self):
        for mid, human in [('01', {'name':'Person','type':'human'}), ('02', 'Person'), ('03', 'HUMAN')]:
            self.add_match(mid, {'player_1':{'bot_id':'target'}, 'player_2':human}, 'target')
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE matches SET rating_status='skipped'")
            conn.execute("""INSERT INTO match_players(match_id,seat,player_type,player_name,snapshot_source)
                            VALUES ('02',2,'human','Person','execution')""")
        self.assertTrue(all(m['rating_delta'] is None for m in self.matches()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
