"""Isolated debug regression checks. Does not import create_app or open production data."""
import importlib
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Skip app/__init__.py (dotenv/application globals); all game code stays real.
package = types.ModuleType('app')
package.__path__ = [str(ROOT / 'app')]
package.socketio = MagicMock()
sys.modules['app'] = package
from app.db import DictLiteConnection
from app.services import debug_service as debug
from app.services import match_lifecycle as lifecycle
from app.services import match_service
from app.code_executor import CodeExecutor
from app.cpp_judge_executor import CppJudgeExecutor
from db_migrations import migrate_debug_schema
from flask import Flask, request

logging.disable(logging.CRITICAL)


class DebugTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / 'isolated.db'
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute('CREATE TABLE matches (id TEXT PRIMARY KEY, game TEXT, players TEXT, '
                               'winner INTEGER, move_history TEXT, displays TEXT, status TEXT, created_at TEXT)')
            migrate_debug_schema(connection)
        self.connection = lambda: DictLiteConnection(str(self.db_path))
        for module in (debug, match_service):
            mocked = patch.object(module, 'get_db_connection', self.connection)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.rating = patch.object(lifecycle, 'update_bot_ratings').start()
        self.addCleanup(patch.stopall)
        self.mid = match_service.create_match_record('Test', '{}')

    def rows(self, table, where='', args=()):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(f'SELECT * FROM {table} {where}', args)
            return cursor.fetchall()

    def events(self, mid=None):
        return [dict(json.loads(row['payload']), turn=row['turn_index'])
                for row in self.rows('match_debug_events', 'WHERE match_id=? ORDER BY sequence', (mid or self.mid,))]

    def recorder(self, types=('bot', 'bot')):
        recorder = debug.DebugRecorder(self.mid, (), types)
        token = debug.bind_recorder(recorder)
        self.addCleanup(debug.reset_recorder, token)
        return recorder

    def scope(self, **kwargs):
        defaults = dict(match_id=self.mid, game_name='Test', players='{}', player_ids=('a', 'b'),
                        player_types=('bot', 'bot'), payload_col='move_history', socketio=MagicMock(),
                        namespace='/test', room=self.mid, active_matches={}, executors=())
        defaults.update(kwargs)
        return lifecycle.match_lifecycle(**defaults)

    def test_additive_migration_and_cli(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            before = connection.execute('SELECT * FROM matches').fetchall()
            migrate_debug_schema(connection)
            migrate_debug_schema(connection)
            self.assertEqual(before, connection.execute('SELECT * FROM matches').fetchall())
        missing = Path(self.temp.name) / 'missing.db'
        result = subprocess.run([sys.executable, str(ROOT / 'migrate_db.py'), '--database', str(missing)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

    def test_raw_python_output_and_stderr(self):
        work = Path(self.temp.name) / 'fixture_bot'
        work.mkdir()
        (work / 'main.py').write_text('import sys\nsys.stdin.read()\nsys.stderr.write("warning\\n")\nsys.stdout.write(\' {"x": 1, "y": 2} \\n\')', encoding='utf-8')
        self.recorder().begin_turn()
        executor = CodeExecutor(str(work))
        self.assertEqual(lifecycle.read_board_move(lambda: executor.run('EXACT INPUT'), 0, input_str='EXACT INPUT'), (1, 2))
        event = self.events()[0]
        self.assertEqual(event['input'], 'EXACT INPUT')
        self.assertEqual(event['stdout'], ' {"x": 1, "y": 2} ' + os.linesep)
        self.assertEqual(event['stderr'], 'warning' + os.linesep)
        self.assertEqual(event['exit_code'], 0)
        self.assertEqual(event['status'], 'success')
        self.assertGreater(event['duration_ms'], 0)

    def test_bad_output_and_invalid_types_are_preserved(self):
        recorder = self.recorder()
        for value in ('<script>alert(1)</script>', '{"x":true,"y":0}', '[1,2]'):
            recorder.begin_turn()
            with self.assertRaises(lifecycle.PlayerForfeit):
                lifecycle.read_board_move(lambda: value, 0, input_str='{}')
        for event, raw in zip(self.events(), ('<script>alert(1)</script>', '{"x":true,"y":0}', '[1,2]')):
            self.assertEqual(event['stdout'], raw)
            self.assertEqual(event['status'], 'protocol_error')
            self.assertEqual(event['stderr'], '')

    def test_runtime_error_and_timeout_partial_output(self):
        self.recorder().begin_turn()
        failures = [subprocess.CalledProcessError(7, ['fixture'], b'partial', b'actual stderr'),
                    subprocess.TimeoutExpired(['fixture'], 1, output=b'timeout partial', stderr=b'before timeout')]
        for failure in failures:
            with patch.object(debug.subprocess, 'run', side_effect=failure):
                with self.assertRaises(lifecycle.PlayerForfeit):
                    lifecycle.read_response(lambda: debug.run_process(['fixture']), 0, '{}')
        events = self.events()
        self.assertEqual([e['status'] for e in events], ['runtime_error', 'timeout'])
        self.assertEqual(events[0]['exit_code'], 7)
        self.assertEqual(events[1]['stdout'], 'timeout partial')
        self.assertEqual(events[1]['stderr'], 'before timeout')
        self.assertIsNone(events[1]['exit_code'])

    def test_compilation_diagnostic_is_not_runtime_stderr(self):
        work = Path(self.temp.name)
        (work / 'main.cpp').write_text('invalid fixture', encoding='utf-8')
        self.recorder().begin_turn()
        with patch('app.cpp_compiler.CppCompiler.compile_file', side_effect=RuntimeError('fixture compile failure')):
            with self.assertRaises(lifecycle.PlayerForfeit):
                lifecycle.read_response(lambda: CodeExecutor(str(work), 'cpp').run('{}'), 0, '{}')
        event = self.events()[0]
        self.assertEqual(event['status'], 'compile_error')
        self.assertIn('fixture compile failure', event['diagnostic'])
        self.assertEqual(event['stderr'], '')

    def test_human_transport_identifiers_are_excluded(self):
        self.recorder(('human', 'bot')).begin_turn()
        action = lifecycle.read_response(lambda: '{"user_id":"secret-session","game_id":"routing", "response":{"direction":1}}', 0, '{}')
        self.assertEqual(action, {'response': {'direction': 1}})
        self.assertNotIn('secret-session', json.dumps(self.events()))
        self.assertEqual(json.loads(self.events()[0]['stdout']), action)

    def test_simultaneous_context_and_symmetric_failures(self):
        self.recorder()
        with self.assertRaises(lifecycle.PlayerForfeit) as raised:
            lifecycle.read_simultaneous_actions((lambda: 'bad1', lambda: 'bad2'), ('input1', 'input2'))
        self.assertEqual(raised.exception.winner, -1)
        events = sorted(self.events(), key=lambda event: event['actor'])
        self.assertEqual([e['actor'] for e in events], ['player_1', 'player_2'])
        self.assertEqual([e['input'] for e in events], ['input1', 'input2'])
        self.assertTrue(all(e['turn'] == 1 and e['status'] == 'protocol_error' for e in events))

    def test_size_limits_and_utf8(self):
        recorder = self.recorder()
        with recorder.capture('judge', '中' * debug.FIELD_LIMIT):
            debug.trace_fields(stdout='x' * (debug.FIELD_LIMIT + 1))
        event = self.events()[0]
        self.assertLessEqual(len(event['input'].encode()), debug.FIELD_LIMIT)
        self.assertEqual(set(event['truncated_fields']), {'input', 'stdout'})
        recorder.bytes_used = debug.MATCH_LIMIT
        with recorder.capture('judge', 'new input'):
            debug.trace_fields(stdout='new output')
        recorder.finish(0)
        self.assertTrue(self.events()[1]['limit_reached'])
        self.assertEqual(self.events()[1]['stdout'], '')
        self.assertEqual(self.rows('match_debug_sessions')[0]['truncated'], 1)

    def test_failed_round_persists_before_notification_and_cleans(self):
        from judges.tictactoe_judge import TicTacToeJudge
        game, executor, socket = TicTacToeJudge(), MagicMock(), MagicMock()
        executor.bot_id, executor.version_id = 'fixture', 1
        active = {self.mid: game}
        def announce(*args, **kwargs):
            self.assertEqual(self.rows('matches')[0]['status'], 'finished')
            self.assertEqual(self.rows('match_debug_sessions')[0]['status'], 'complete')
            raise RuntimeError('notification failed')
        socket.emit.side_effect = announce
        with self.scope(board_game=game, executors=(executor,), socketio=socket, active_matches=active):
            lifecycle.play_board_game(game, (lambda _: '{"x":0,"y":0}', lambda _: 'INVALID'), lambda _: None, 9)
        session = self.rows('match_debug_sessions')[0]
        self.assertEqual((session['last_turn'], session['frame_count']), (2, 1))
        self.assertEqual(self.rows('matches')[0]['winner'], 0)
        self.assertEqual(len(game.move_history), 1)
        self.assertEqual(self.events()[-1]['status'], 'protocol_error')
        self.assertFalse(active)
        executor.cleanup.assert_called_once()
        self.rating.assert_called_once_with('a', 'b', 0, self.mid)
        self.assertIsNone(debug.current_recorder())

    def test_illegal_board_move_is_judge_failure(self):
        from judges.tictactoe_judge import TicTacToeJudge
        game = TicTacToeJudge()
        with self.scope(board_game=game):
            lifecycle.play_board_game(game, (lambda _: '{"x":99,"y":99}', lambda _: '{}'), lambda _: None, 9)
        self.assertEqual(self.events()[-1]['actor'], 'judge')
        self.assertEqual(self.events()[-1]['status'], 'invalid_move')
        self.assertEqual(self.rows('match_debug_sessions')[0]['frame_count'], 0)
        self.assertEqual(self.rows('matches')[0]['winner'], 1)

    def test_judge_abort_not_rated(self):
        with self.scope():
            with debug.current_recorder().capture('judge', '{}'):
                raise RuntimeError('synthetic judge failure')
        self.rating.assert_not_called()
        self.assertEqual(self.rows('matches')[0]['winner'], -1)
        self.assertEqual(self.events()[0]['status'], 'execution_error')

    def test_database_result_failure_still_cleans_and_marks_interruption(self):
        executor = MagicMock()
        with patch.object(lifecycle, 'finalize_match_record', side_effect=RuntimeError('save failure')):
            with self.assertRaises(RuntimeError):
                with self.scope(executors=(executor,)):
                    pass
        executor.cleanup.assert_called_once()
        self.rating.assert_not_called()
        self.assertEqual(self.rows('match_debug_sessions')[0]['status'], 'interrupted')
        self.assertIsNone(debug.current_recorder())

    def test_legacy_setup_failure_still_cleans(self):
        executor = MagicMock()
        with patch.object(lifecycle, 'create_match_record', side_effect=RuntimeError('setup failure')):
            with self.assertRaises(RuntimeError):
                with self.scope(match_id=None, executors=(executor,)):
                    self.fail('must not enter')
        executor.cleanup.assert_called_once()

    def test_trace_write_failure_does_not_abort_game(self):
        with patch.object(debug, 'get_db_connection', side_effect=RuntimeError('debug unavailable')):
            with self.scope() as result:
                result.winner = 1
                with debug.current_recorder().capture('judge', '{}'):
                    debug.trace_fields(stdout='{}')
        self.assertEqual(self.rows('matches')[0]['winner'], 1)

    def test_public_api_legacy_missing_invalid_and_failed_round(self):
        main = importlib.import_module('app.main')
        web = Flask(__name__)
        web.register_blueprint(main.main_bp)
        with patch.object(main, 'get_db_connection', self.connection):
            client = web.test_client()
            self.assertFalse(client.get(f'/api/matches/{self.mid}/debug').json['available'])
            self.assertEqual(client.get('/api/matches/missing/debug').status_code, 404)
            for value in ('-1', '1.5', 'x', '100001'):
                self.assertEqual(client.get(f'/api/matches/{self.mid}/debug?turn={value}').status_code, 400)
            recorder = self.recorder()
            recorder.begin_turn(2)
            with recorder.capture('player_2', 'input'):
                debug.trace_fields(stdout='not JSON', status='protocol_error')
            recorder.finish(1, 'Player failed to return a valid action.')
            manifest = client.get(f'/api/matches/{self.mid}/debug')
            self.assertEqual(manifest.status_code, 200)  # anonymous visitor
            self.assertEqual(manifest.headers['Cache-Control'], 'no-store')
            self.assertEqual(manifest.json['failure_turn'], 2)
            self.assertNotIn('events', manifest.json)
            turn = client.get(f'/api/matches/{self.mid}/debug?turn=2').json
            self.assertEqual(turn['events'][0]['stdout'], 'not JSON')
            self.assertEqual(client.get(f'/api/matches/{self.mid}/debug?turn=1').json['events'], [])
            bulk = client.get(f'/api/matches/{self.mid}/debug?all=1')
            self.assertEqual(bulk.status_code, 200)
            self.assertEqual(bulk.headers['Cache-Control'], 'no-store')
            self.assertEqual(bulk.json['failure_turn'], 2)
            self.assertEqual(bulk.json['events'], turn['events'])
            for query in ('all=0', 'all=x', 'all=1&turn=2'):
                self.assertEqual(client.get(f'/api/matches/{self.mid}/debug?{query}').status_code, 400)

    def test_bulk_api_includes_all_rounds_and_actors_without_per_round_limit(self):
        main = importlib.import_module('app.main')
        web = Flask(__name__)
        web.register_blueprint(main.main_bp)
        recorder = self.recorder()
        for turn in range(40):
            recorder.begin_turn(turn)
            for actor in ('judge', 'player_1', 'player_2'):
                with recorder.capture(actor, f'input-{turn}'):
                    debug.trace_fields(stdout=f'output-{turn}')
        recorder.finish(39)
        with patch.object(main, 'get_db_connection', self.connection):
            snapshot = web.test_client().get(f'/api/matches/{self.mid}/debug?all=1').json
        self.assertEqual(len(snapshot['events']), 120)
        self.assertEqual(snapshot['events'][0]['turn'], 0)
        self.assertEqual(snapshot['events'][-1]['turn'], 39)
        self.assertEqual(snapshot['events'][-1]['stdout'], 'output-39')
        self.assertEqual(len(snapshot['turns']), 40)

    def test_real_chess_judges_complete_with_traces(self):
        for module_name, class_name, size, column_only in [('gomoku', 'GomokuJudge', 15, False),
                                                          ('tictactoe', 'TicTacToeJudge', 3, False),
                                                          ('connect4', 'ConnectFourJudge', 7, True)]:
            game = getattr(importlib.import_module('judges.' + module_name + '_judge'), class_name)()
            mid = match_service.create_match_record(module_name, '{}')
            def move(_):
                if column_only:
                    return json.dumps({'x': next(x for x in range(size) if game.is_valid_move(x))})
                return json.dumps(next({'x': x, 'y': y} for y in range(size) for x in range(size) if game.board[y][x] == 0))
            with self.scope(match_id=mid, board_game=game):
                lifecycle.play_board_game(game, (move, move), lambda _: None, 256, column_only=column_only)
            events = self.events(mid)
            self.assertTrue(all(e['status'] == 'success' for e in events), module_name)
            self.assertEqual(len(events), len(game.move_history) * 2 + 1)
            self.assertTrue(game.winner or game.is_board_full())

    def test_real_cpp_judges_input_output_and_frame_mapping(self):
        from judges.build import judge_binary_path
        for name in ('snake_judge', 'msnake_judge', 'tank2_judge'):
            binary = judge_binary_path(name)
            if not Path(binary).exists():
                self.skipTest('Local compiled judge binaries unavailable')
            mid = match_service.create_match_record(name, '{}')
            with self.scope(match_id=mid, payload_col='displays') as result:
                judge = CppJudgeExecutor(binary)
                state = judge.run_raw_json({})
                result.payload.append(state['display'])
                response = {'response': [-1, -1]} if name == 'tank2_judge' else {'response': {'direction': 0}}
                a, b = lifecycle.read_simultaneous_actions((lambda: json.dumps(response), lambda: json.dumps(response)), ('input-a', 'input-b'))
                state = judge.run_raw_json({'initdata': state['initdata'], 'log': [{}, {'0': a, '1': b}]})
                result.payload.append(state['display'])
            events = self.events(mid)
            self.assertEqual(events[0]['actor'], 'judge')
            self.assertEqual(events[-1]['actor'], 'judge')
            self.assertEqual({e['actor'] for e in events[1:3]}, {'player_1', 'player_2'})
            self.assertEqual([e['turn'] for e in events], [0, 1, 1, 1])
            self.assertTrue(all(e['status'] == 'success' for e in events), name)
            self.assertIn('display', json.loads(events[-1]['stdout']))
            self.assertEqual(events[-1]['exit_code'], 0)

    def test_cpp_raw_bytes_and_invalid_json(self):
        recorder = self.recorder()
        judge = CppJudgeExecutor(sys.executable)  # existence check only; process is mocked below
        for output in (b' {"display": {}}\r\n', b'NOT JSON\r\n', b'\xff\xfe'):
            result = subprocess.CompletedProcess(['fixture'], 0, output, b'raw stderr\r\n')
            with patch.object(debug.subprocess, 'run', return_value=result):
                if output.startswith(b' {'):
                    self.assertEqual(judge.run_raw_json({}), {'display': {}})
                else:
                    with self.assertRaises((ValueError, UnicodeDecodeError)):
                        judge.run_raw_json({})
        events = self.events()
        self.assertEqual(events[0]['stdout'], ' {"display": {}}\r\n')
        self.assertTrue(all(e['stderr'] == 'raw stderr\r\n' for e in events))
        self.assertTrue(all(e['status'] == 'protocol_error' for e in events[1:]))

    def test_interactive_entrypoints_for_all_six_games(self):
        class Socket:
            def __init__(self):
                self.handlers = {}
                self.emit = MagicMock()
            def on(self, event, namespace):
                def register(callback):
                    self.handlers[event] = callback
                    return callback
                return register
            def sleep(self, _):
                pass
        class Bot:
            bot_id, version_id = 'fixture', 1
            def __init__(self, slug):
                self.slug, self.calls = slug, 0
                self.cleanup = MagicMock()
            def run(self, value):
                self.calls += 1
                if self.slug in ('snake', 'msnake'):
                    return json.dumps({'response': {'direction': 0 if self.calls == 1 else -1}})
                if self.slug == 'tank2':
                    return json.dumps({'response': [-1, -1] if self.calls == 1 else [99, 99]})
                history = json.loads(value)['move_history']
                if self.slug == 'connect4':
                    return json.dumps({'x': next(x for x in range(7) if sum(m['x'] == x for m in history) < 6)})
                size = 3 if self.slug == 'tictactoe' else 15
                used = {(m['x'], m['y']) for m in history}
                return json.dumps(next({'x': x, 'y': y} for y in range(size) for x in range(size) if (x, y) not in used))
        for slug, module_name, register_name in [('gomoku', 'gomoku', 'register_gomoku_events'),
                                                ('tictactoe', 'tictactoe', 'register_tictactoe_events'),
                                                ('connect4', 'connect4', 'register_connect4_events'),
                                                ('snake', 'snake', 'register_snake_events'),
                                                ('msnake', 'snake', 'register_snake_events'),
                                                ('tank2', 'tank2', 'register_tank_events')]:
            module = importlib.import_module('app.' + module_name)
            socket, bots = Socket(), [Bot(slug), Bot(slug)]
            mid = match_service.create_match_record(slug, '{}')
            module.sessions['fixture'] = {'sid': 'fixture-sid'}
            with patch.object(module, '_get_bot_executor', side_effect=bots), \
                 patch.object(module, 'build_players_json', return_value='{}'), \
                 patch.object(module, 'current_user', types.SimpleNamespace(is_authenticated=True, username='Fixture')), \
                 patch.object(module, 'emit'):
                getattr(module, register_name)(socket)
                with Flask(__name__).test_request_context('/'):
                    request.sid = 'fixture-sid'
                    socket.handlers['new_game']({'user_id': 'fixture', 'match_id': mid, 'black_bot': 'a',
                                                'white_bot': 'b', 'p1_bot_id': 'a', 'p2_bot_id': 'b',
                                                'game_name': 'Mini Snake' if slug == 'msnake' else slug})
            session = self.rows('match_debug_sessions', 'WHERE match_id=?', (mid,))[0]
            self.assertEqual(session['status'], 'complete', slug)
            self.assertFalse(session['error'], (slug, session['error']))
            self.assertGreater(session['frame_count'], 0, slug)
            self.assertTrue(all(e['status'] == 'success' for e in self.events(mid)), slug)
            self.assertNotIn(mid, module.active_matches)
            for bot in bots:
                bot.cleanup.assert_called_once()

    def test_scheduled_entrypoints_record_both_players(self):
        for slug, runner in [('gomoku', 'run_auto_gomoku_match'), ('tictactoe', 'run_auto_tictactoe_match'),
                             ('connect4', 'run_auto_connect4_match'), ('snake', 'run_auto_snake_match'),
                             ('tank2', 'run_auto_tank_match')]:
            module = importlib.import_module('app.' + slug)
            def move(value):
                if slug == 'snake':
                    return '{"response":{"direction":-1}}'
                if slug == 'tank2':
                    return '{"response":[99,99]}'
                history = json.loads(value)['move_history']
                if slug == 'connect4':
                    return json.dumps({'x': next(x for x in range(7) if sum(m['x'] == x for m in history) < 6)})
                used, size = {(m['x'], m['y']) for m in history}, 3 if slug == 'tictactoe' else 15
                return json.dumps(next({'x': x, 'y': y} for y in range(size) for x in range(size) if (x, y) not in used))
            bots = [MagicMock(bot_id='fixture-a', version_id=1), MagicMock(bot_id='fixture-b', version_id=2)]
            for bot in bots:
                bot.run.side_effect = move
            existing = {row['id'] for row in self.rows('matches')}
            with patch.object(module, '_get_bot_executor', side_effect=bots), \
                 patch.object(module, 'build_players_json', return_value='{}'):
                getattr(module, runner)('fixture-a', 'fixture-b')
            new_ids = {row['id'] for row in self.rows('matches')} - existing
            self.assertEqual(len(new_ids), 1)
            mid = new_ids.pop()
            session = self.rows('match_debug_sessions', 'WHERE match_id=?', (mid,))[0]
            self.assertEqual(session['status'], 'complete', slug)
            self.assertFalse(session['error'], (slug, session['error']))
            self.assertEqual({e['actor'] for e in self.events(mid)}, {'judge', 'player_1', 'player_2'})
            for bot in bots:
                bot.cleanup.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
