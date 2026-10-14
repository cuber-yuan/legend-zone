"""Migration/settlement regressions: temporary SQLite, no app factory or real uploads."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
package = types.ModuleType('app')
package.__path__ = [str(ROOT / 'app')]
package.socketio = MagicMock()
sys.modules['app'] = package
from app.db import DictLiteConnection
from app.services import bot_service, match_service, rating_service, debug_service, match_lifecycle
import db_migrations

logging.disable(logging.CRITICAL)  # Expected fault-injection cases are asserted below.

LEGACY_CORE_SCHEMA = '''
CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,email TEXT,created_at TEXT);
CREATE TABLE bots(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,bot_name TEXT NOT NULL,game TEXT NOT NULL,language TEXT NOT NULL DEFAULT 'cpp',is_private INTEGER NOT NULL DEFAULT 0,created_at TEXT,UNIQUE(bot_name,game));
CREATE TABLE bot_versions(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id TEXT NOT NULL,version_number INTEGER NOT NULL,description TEXT,source_code TEXT,file_path TEXT,rating REAL DEFAULT 1500,created_at TEXT,FOREIGN KEY(bot_id) REFERENCES bots(id) ON DELETE CASCADE,UNIQUE(bot_id,version_number));
CREATE TABLE matches(id TEXT PRIMARY KEY,game TEXT NOT NULL,players TEXT,winner INTEGER,displays TEXT,move_history TEXT,status TEXT DEFAULT 'playing',created_at TEXT);
CREATE TABLE games(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,description TEXT,author_id INTEGER,min_players INTEGER DEFAULT 2,max_players INTEGER DEFAULT 4,created_at TEXT);
CREATE TABLE rating_history(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id TEXT NOT NULL,version_id INTEGER NOT NULL,match_id TEXT,rating REAL NOT NULL,created_at TEXT,UNIQUE(version_id,match_id));
'''


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.db'
        self.factory = lambda: DictLiteConnection(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            db_migrations.migrate_schema(connection)
            connection.execute("INSERT INTO users (id,username,password_hash) VALUES (1,'fixture','not-a-real-account')")
            for bot in ('a', 'b'):
                connection.execute("INSERT INTO bots(id,user_id,bot_name,game,language) VALUES (?,1,?,'Tic Tac Toe','python3')", (bot, bot))
                connection.execute('INSERT INTO bot_versions(bot_id,version_number,rating,file_path) VALUES (?,1,1500,?)', (bot, self.temp.name))
            connection.commit()
        for module in (bot_service, match_service, rating_service, debug_service):
            mocked = patch.object(module, 'get_db_connection', self.factory)
            mocked.start()
            self.addCleanup(mocked.stop)

    def sql(self, sql, args=()):
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute(sql, args)
            rows = cursor.fetchall()
            connection.commit()
            return rows

    def new_match(self, types=('bot', 'bot'), same=False):
        second = 'a' if same else 'b'
        players = bot_service.build_players_json('a', types[0], second, types[1], human_name='Fixture Human')
        mid = match_service.create_match_record('Tic Tac Toe', players)
        executors = (bot_service.get_bot_executor('a') if types[0] == 'bot' else None,
                     bot_service.get_bot_executor(second) if types[1] == 'bot' else None)
        return mid, players, executors

    def scope(self, mid, players, executors, types=('bot', 'bot'), same=False):
        return match_lifecycle.match_lifecycle(match_id=mid, game_name='Tic Tac Toe', players=players,
            player_ids=('a', 'a' if same else 'b'), player_types=types, payload_col='move_history',
            socketio=MagicMock(), namespace='/test', room=mid, active_matches={}, executors=executors)

    def test_empty_and_repeated_migrations(self):
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(db_migrations.migrate_schema(connection), [])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 4)
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(len(self.sql('SELECT id FROM bots')), 2)

    def test_new_database_initializer_uses_all_migrations(self):
        initializer = importlib.import_module('init_db')
        fresh = Path(self.temp.name)/'initialized.db'
        with patch.object(initializer, 'DB_PATH', str(fresh)):
            initializer.init_db()
        with closing(sqlite3.connect(fresh)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0],4)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM games').fetchone()[0],5)
            self.assertIn('rating_status',{row[1] for row in connection.execute('PRAGMA table_info(matches)')})

    def test_migration_failure_rolls_back_columns_tables_and_version(self):
        scripts = Path(self.temp.name) / 'migrations'
        shutil.copytree(ROOT / 'migrations', scripts)
        with (scripts / '002_match_integrity.sql').open('a', encoding='utf-8') as file:
            file.write('\nINVALID SQL FOR ROLLBACK TEST;\n')
        fresh = Path(self.temp.name) / 'failed.db'
        with patch.object(db_migrations, 'MIGRATIONS', scripts), closing(sqlite3.connect(fresh)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                db_migrations.migrate_schema(connection)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 2)
            self.assertNotIn('rating_status', {row[1] for row in connection.execute('PRAGMA table_info(matches)')})
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='match_players'").fetchone())
        with closing(sqlite3.connect(fresh)) as connection:
            self.assertEqual(db_migrations.migrate_schema(connection), ['002_match_integrity','003_integrity_guards'])

    def test_applied_migration_checksum_is_checked(self):
        scripts = Path(self.temp.name) / 'changed'
        shutil.copytree(ROOT / 'migrations', scripts)
        with (scripts / '000_core.sql').open('a', encoding='utf-8') as file:
            file.write('\n-- unexpected edit\n')
        with patch.object(db_migrations, 'MIGRATIONS', scripts), closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaisesRegex(RuntimeError, 'modified'):
                db_migrations.migrate_schema(connection)

    def test_cli_backup_dry_run_and_repeat(self):
        old = Path(self.temp.name) / 'old.db'
        backup = Path(self.temp.name) / 'backup.db'
        with closing(sqlite3.connect(old)) as connection:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('preserved')")
            connection.commit()
        command = [sys.executable, str(ROOT / 'migrate_db.py'), '--database', str(old)]
        subprocess.run(command + ['--check'], check=True, capture_output=True)
        self.assertFalse(backup.exists())
        subprocess.run(command + ['--backup', str(backup)], check=True, capture_output=True)
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM marker').fetchone()[0], 'preserved')
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone())
        subprocess.run(command, check=True, capture_output=True)
        missing = Path(self.temp.name) / 'missing.db'
        self.assertNotEqual(subprocess.run([sys.executable, str(ROOT / 'migrate_db.py'), '--database', str(missing)], capture_output=True).returncode, 0)
        self.assertFalse(missing.exists())

    def test_running_match_rates_original_versions_after_new_upload(self):
        mid, players, executors = self.new_match()
        with self.scope(mid, players, executors) as result:
            self.sql("INSERT INTO bot_versions(bot_id,version_number,rating) VALUES ('a',2,1500)")
            result.winner = 0
        versions = self.sql('SELECT bot_id,version_number,rating FROM bot_versions ORDER BY bot_id,version_number')
        self.assertEqual([v['rating'] for v in versions], [1516, 1500, 1484])
        self.assertEqual(self.sql('SELECT version_number_snapshot FROM match_players WHERE match_id=? ORDER BY seat', (mid,)),
                         [{'version_number_snapshot': 1}, {'version_number_snapshot': 1}])
        match = self.sql('SELECT * FROM matches WHERE id=?', (mid,))[0]
        self.assertEqual(match['rating_status'], 'applied')
        self.assertEqual(match['termination_reason'], 'normal')
        self.assertTrue(match['started_at'] and match['finished_at'] and match['rated_at'])

    def test_stale_setup_snapshot_is_replaced_with_actual_executor_version(self):
        mid, players, _ = self.new_match()
        self.sql("INSERT INTO bot_versions(bot_id,version_number,rating) VALUES ('a',2,1500)")
        executors = (bot_service.get_bot_executor('a'), bot_service.get_bot_executor('b'))
        with self.scope(mid, players, executors) as result:
            result.winner = 0
        match = self.sql('SELECT players FROM matches WHERE id=?', (mid,))[0]
        self.assertEqual(json.loads(match['players'])['player_1']['version'], 2)
        self.assertEqual(self.sql("SELECT rating FROM bot_versions WHERE bot_id='a' ORDER BY version_number"),
                         [{'rating': 1500}, {'rating': 1516}])

    def test_concurrent_repeat_settlement_only_applies_once(self):
        mid, players, executors = self.new_match()
        players = match_service.bind_match_players(mid, players, ('bot','bot'), executors)
        match_service.finalize_match_record(mid, 'Tic Tac Toe', players, 0, '[]', 'move_history')
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda _: rating_service.update_bot_ratings('a','b',0,mid), range(2))), ['applied','applied'])
        self.assertEqual(self.sql('SELECT rating FROM bot_versions ORDER BY bot_id'), [{'rating':1516},{'rating':1484}])
        self.assertEqual(len(self.sql('SELECT id FROM rating_history WHERE match_id=?', (mid,))), 2)

    def test_rating_failure_rolls_back_and_can_retry(self):
        mid, players, executors = self.new_match()
        original = rating_service.record_history
        calls = []
        def fail_second(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('Synthetic second-history failure')
            return original(*args)
        with patch.object(rating_service, 'record_history', side_effect=fail_second):
            with self.scope(mid, players, executors) as result:
                result.winner = 0
        self.assertEqual(self.sql('SELECT rating FROM bot_versions ORDER BY bot_id'), [{'rating':1500},{'rating':1500}])
        self.assertEqual(self.sql('SELECT id FROM rating_history WHERE match_id=?', (mid,)), [])
        match = self.sql('SELECT status,rating_status,rating_error FROM matches WHERE id=?', (mid,))[0]
        self.assertEqual((match['status'], match['rating_status']), ('finished','failed'))
        self.assertIn('Synthetic', match['rating_error'])
        self.assertEqual(rating_service.update_bot_ratings('a','b',0,mid), 'applied')
        self.assertEqual(len(self.sql('SELECT id FROM rating_history WHERE match_id=?', (mid,))), 2)

    def test_human_selfplay_and_server_abort_are_skipped(self):
        for kinds, same, abort in [(('human','bot'),False,False), (('bot','bot'),True,False), (('bot','bot'),False,True)]:
            mid, players, executors = self.new_match(kinds, same)
            with self.scope(mid, players, executors, kinds, same) as result:
                if abort:
                    raise RuntimeError('Synthetic judge failure')
                result.winner = 0
            row = self.sql('SELECT status,rating_status,termination_reason,error_message FROM matches WHERE id=?',(mid,))[0]
            self.assertEqual((row['status'], row['rating_status']), ('finished','skipped'))
            if abort:
                self.assertEqual(row['termination_reason'], 'server_error')
                self.assertTrue(row['error_message'])
        self.assertEqual(self.sql('SELECT id FROM rating_history'), [])

    def test_deleted_bot_keeps_snapshots_matches_logs_and_scored_state(self):
        mid, players, executors = self.new_match()
        with self.scope(mid, players, executors) as result:
            with debug_service.current_recorder().capture('player_1', '{}'):
                debug_service.trace_fields(stdout='{"x":0,"y":0}')
            result.winner = 0
        self.sql("DELETE FROM bots WHERE id='a'")
        snapshot = self.sql('SELECT * FROM match_players WHERE match_id=? AND seat=1',(mid,))[0]
        self.assertIsNone(snapshot['bot_id'])
        self.assertIsNone(snapshot['bot_version_id'])
        self.assertEqual((snapshot['bot_id_snapshot'],snapshot['player_name'],snapshot['version_number_snapshot']),('a','a',1))
        self.assertEqual(len(self.sql('SELECT sequence FROM match_debug_events WHERE match_id=?',(mid,))),1)
        self.assertEqual(rating_service.update_bot_ratings('a','b',0,mid),'applied')
        self.assertEqual(self.sql("SELECT rating FROM bot_versions WHERE bot_id='b'")[0]['rating'],1484)

    def test_deletion_during_match_does_not_rate_another_version(self):
        mid, players, executors = self.new_match()
        with self.scope(mid, players, executors) as result:
            self.sql("INSERT INTO bot_versions(bot_id,version_number,rating) VALUES ('a',2,1500)")
            self.sql("DELETE FROM bot_versions WHERE bot_id='a' AND version_number=1")
            result.winner = 0
        self.assertEqual(self.sql('SELECT rating_status FROM matches WHERE id=?',(mid,))[0]['rating_status'],'skipped')
        self.assertTrue(all(row['rating']==1500 for row in self.sql('SELECT rating FROM bot_versions')))

    def test_constraints_reject_bad_new_writes(self):
        for statement in ["UPDATE bots SET is_private=4 WHERE id='a'", "UPDATE bots SET user_id=99 WHERE id='a'",
                          "UPDATE bot_versions SET version_number=0", "DELETE FROM users WHERE id=1",
                          "INSERT INTO matches(id,game,status) VALUES ('bad','x','invalid')",
                          "INSERT INTO matches(id,game,winner) VALUES ('bad','x',5)"]:
            with self.assertRaises(sqlite3.IntegrityError), self.factory() as connection:
                connection._conn.execute(statement)

    def test_forfeit_reason_and_saved_winner_are_explicit(self):
        for seat, reason, winner in [(0,'timeout',1),(1,'invalid_move',0),(None,'double_forfeit',-1)]:
            mid, players, executors = self.new_match()
            with self.scope(mid, players, executors):
                raise match_lifecycle.PlayerForfeit(seat, 'Synthetic player failure', reason)
            row=self.sql('SELECT winner,termination_reason,error_message,rating_status FROM matches WHERE id=?',(mid,))[0]
            self.assertEqual((row['winner'],row['termination_reason'],row['rating_status']),(winner,reason,'applied'))
            self.assertEqual(row['error_message'],'Synthetic player failure')

    def test_match_cannot_be_started_or_finished_twice(self):
        mid, players, executors = self.new_match()
        players = match_service.bind_match_players(mid, players, ('bot','bot'), executors)
        with self.assertRaises(ValueError):
            match_service.bind_match_players(mid, players, ('bot','bot'), executors)
        match_service.finalize_match_record(mid,'Tic Tac Toe',players,0,'[]','move_history')
        with self.assertRaises(ValueError):
            match_service.finalize_match_record(mid,'Tic Tac Toe',players,1,'[]','move_history')
        self.assertEqual(self.sql('SELECT winner FROM matches WHERE id=?',(mid,))[0]['winner'],0)

    def test_debug_counters_are_atomic_and_count_utf8_bytes(self):
        mid, _, _ = self.new_match()
        recorder = debug_service.DebugRecorder(mid)
        with recorder.capture('judge', '中文'):
            debug_service.trace_fields(stdout='output')
        row = self.sql('SELECT event_count,stored_bytes FROM match_debug_sessions WHERE match_id=?',(mid,))[0]
        payload = self.sql('SELECT payload FROM match_debug_events WHERE match_id=?',(mid,))[0]['payload']
        self.assertEqual(row, {'event_count':1,'stored_bytes':len(payload.encode('utf-8'))})
        self.sql("CREATE TRIGGER reject_debug_counter BEFORE UPDATE OF event_count ON match_debug_sessions BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with recorder.capture('judge', '{}'):
            pass
        self.assertEqual(len(self.sql('SELECT sequence FROM match_debug_events WHERE match_id=?',(mid,))),1)
        recorder.finish(0)
        self.assertEqual(self.sql('SELECT incomplete FROM match_debug_sessions WHERE match_id=?',(mid,))[0]['incomplete'],1)


class LegacyUpgradeTests(unittest.TestCase):
    def test_existing_snapshots_and_unknowns_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory, closing(sqlite3.connect(Path(directory)/'old.db')) as connection:
            # Legacy definitions do not have the new fields, table or stronger constraints.
            connection.executescript(LEGACY_CORE_SCHEMA)
            debug_schema=(ROOT/'migrations/001_match_debug.sql').read_text(encoding='utf-8')
            debug_schema=debug_schema.replace(' REFERENCES matches(id) ON DELETE RESTRICT','').replace(' REFERENCES match_debug_sessions(match_id) ON DELETE RESTRICT','')
            connection.executescript(debug_schema)
            connection.execute("INSERT INTO users(id,username,password_hash) VALUES(1,'fixture','fixture')")
            connection.execute("INSERT INTO bots(id,user_id,bot_name,game) VALUES('a',1,'Old Name','Tic Tac Toe')")
            connection.execute("INSERT INTO bot_versions(id,bot_id,version_number) VALUES(1,'a',1),(2,'a',2)")
            players=json.dumps({'player_1':{'name':'Historical Name','bot_id':'a','version':1},'player_2':'Legacy Player'})
            connection.execute("INSERT INTO matches(id,game,players,status,winner) VALUES('old','Tic Tac Toe',?,'finished',0)",(players,))
            connection.execute("INSERT INTO matches(id,game,players,status,winner) VALUES('broken','x','not json','finished',-1)")
            connection.execute("INSERT INTO match_debug_sessions(match_id,created_at,finished_at,status) VALUES('old','start','end','complete')")
            payload=json.dumps({'stdout':'中文'},ensure_ascii=False)
            connection.execute("INSERT INTO match_debug_events VALUES('old',1,0,'judge','success',?)",(payload,))
            connection.commit()
            db_migrations.migrate_schema(connection)
            self.assertEqual(connection.execute("SELECT players FROM matches WHERE id='old'").fetchone()[0],players)
            row=connection.execute("SELECT bot_version_id,player_name,snapshot_source FROM match_players WHERE match_id='old' AND seat=1").fetchone()
            self.assertEqual(row,(1,'Historical Name','history'))
            self.assertEqual(connection.execute("SELECT rating_status,finished_at FROM matches WHERE id='old'").fetchone(),('unknown','end'))
            self.assertEqual(connection.execute("SELECT rating_status,termination_reason,finished_at FROM matches WHERE id='broken'").fetchone(),('unknown','unknown',None))
            self.assertEqual(connection.execute("SELECT event_count,stored_bytes FROM match_debug_sessions WHERE match_id='old'").fetchone(),(1,len(payload.encode())))
            self.assertEqual(db_migrations.migrate_schema(connection),[])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE bots SET user_id=99 WHERE id='a'")
            connection.rollback()
            connection.execute("DELETE FROM bots WHERE id='a'")
            self.assertEqual(connection.execute("SELECT bot_id,bot_version_id,player_name FROM match_players WHERE match_id='old' AND seat=1").fetchone(),(None,None,'Historical Name'))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM match_debug_events').fetchone()[0],1)
            connection.rollback()


if __name__ == '__main__':
    unittest.main(verbosity=2)
