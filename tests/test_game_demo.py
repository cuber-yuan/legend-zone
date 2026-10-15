"""Game introductions: temporary SQLite and rendered templates, no app startup."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
package = types.ModuleType('app')
package.__path__ = [str(ROOT/'app')]
package.socketio = MagicMock()
sys.modules['app'] = package
from app.db import DictLiteConnection
from db_schema import initialize_schema


class GameDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'fixture.db'
        self.factory = lambda: DictLiteConnection(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            initialize_schema(connection)

    def sql(self, query, args=()):
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute(query,args)
            rows = cursor.fetchall()
            connection.commit()
            return rows

    def test_game_intro_uses_latest_renderable_finished_replay(self):
        from app.services import game_demo
        frames = [{'x':0,'y':0,'player':1},{'x':1,'y':0,'player':2}]
        players = {'player_1':{'name':'Alpha <Bot>'},'player_2':{'name':'Beta'}}
        for mid,status,payload in [('valid','finished',json.dumps(frames)),('bad','finished','not json'),
                                   ('empty','finished','[]'),('running','playing',json.dumps(frames))]:
            self.sql('INSERT INTO matches(id,game,players,status,winner,move_history,created_at) VALUES (?,?,?,?,?,?,?)',
                     (mid,'Tic Tac Toe',json.dumps(players),status,0,payload,str(len(self.sql('SELECT id FROM matches')))))
        with patch.object(game_demo,'get_db_connection',self.factory):
            demo = game_demo.get_game_demo('Tic Tac Toe')
            self.assertEqual(demo['frames'],frames)
            self.assertNotIn('players',demo)
            self.assertEqual(demo['winner'],1)
            self.assertIsNone(game_demo.get_game_demo('Snake'))

    def test_game_demo_validates_all_six_replay_formats(self):
        from app.services.game_demo import _valid_frames
        snake = [{'width':11,'height':10,'obstacle':[],'0':{'x':1,'y':1},'1':{'x':10,'y':11}},
                 {'0':1,'1':3,'grow':'true'}]
        tank = [{'brick':[0,0,0],'water':[0,0,0],'steel':[0,0,0]}, {'0':[-1,-1],'1':[-1,-1]}]
        for game,frames in [('Gomoku',[{'x':0,'y':0,'player':1}]),('Tic Tac Toe',[{'x':0,'y':0,'player':1}]),
                            ('Connect Four',[{'x':0,'y':5,'player':1}]),('Snake',snake),('Mini Snake',snake),('Tank Battle',tank)]:
            self.assertTrue(_valid_frames(game,frames),game)
            self.assertFalse(_valid_frames(game,[]),game)
            self.assertFalse(_valid_frames(game,[None]),game)
        self.assertFalse(_valid_frames('Connect Four',[{'x':0,'y':0,'player':1}]))
        self.assertFalse(_valid_frames('Snake',[snake[0],{'0':-1,'1':3}]))
        self.assertFalse(_valid_frames('Tank Battle',[tank[0],{'0':'bad','1':[-1,-1]}]))

    def test_intro_routes_show_guide_and_demo_without_match_controls(self):
        import importlib
        from flask import Flask
        from flask_login import LoginManager
        main = importlib.import_module('app.main')
        from app.services import game_demo
        web = Flask(__name__,template_folder=str(ROOT/'app/templates'))
        web.register_blueprint(main.main_bp)
        login = LoginManager(web)
        login.user_loader(lambda _: None)
        web.jinja_env.globals['url_for'] = lambda endpoint,**kw: '/static/'+kw['filename'] if endpoint=='static' else '/'+endpoint
        games = [('gomoku','Gomoku'),('tictactoe','Tic Tac Toe'),('connect4','Connect Four'),
                 ('snake','Snake'),('msnake','Mini Snake'),('tank','Tank Battle')]
        demo = {'players':{'player_1':{'name':'Alpha <Bot>'},'player_2':{'name':'Beta'}},
                'frames':[{'x':0,'y':0,'player':1}],'winner':0}
        for slug,game in games:
            with patch.object(game_demo,'get_game_demo',return_value=dict(demo,game=game)) as lookup:
                response = web.test_client().get('/'+slug)
            self.assertEqual(response.status_code,200,slug)
            lookup.assert_called_once_with(game)
            html = response.get_data(as_text=True)
            self.assertIn('id="gameDemoData"',html)
            self.assertNotIn('class="match-players"',html)
            self.assertIn('How to Play as Human',html)
            self.assertNotIn('id="replayControls"',html)
            self.assertNotIn('data-replay-debug',html)
        with patch.object(game_demo,'get_game_demo',return_value=None):
            html = web.test_client().get('/snake').get_data(as_text=True)
        self.assertNotIn('id="gameDemoData"',html)
        self.assertNotIn('class="match-players"',html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
