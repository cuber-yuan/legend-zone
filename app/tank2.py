from flask import Blueprint, request
from . import socketio
from .cpp_judge_executor import CppJudgeExecutor
from .code_executor import CodeExecutor
from flask_socketio import emit, join_room
from uuid import uuid4
import os
import json
import pymysql
from .services.utils import get_db_connection

tank_bp = Blueprint('tank', __name__)
sessions = {}  # { user_id: { 'sid': ..., 'game': ... } }



def _get_bot_executor(bot_id):
    if not bot_id:
        return None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT source_code, file_path, language FROM bots WHERE id = %s", (bot_id,))
            result = cursor.fetchone()
        if result:
            return CodeExecutor(code=result['source_code'], language=result['language'], path=result['file_path'])
    finally:
        if conn:
            conn.close()
    return None

class TankGameSession:
    def __init__(self, cpp_path, bot_top_code=None, bot_bottom_code=None):
        self.game_id = str(uuid4())
        self.cpp_judge = CppJudgeExecutor(cpp_path)
        self.bot_top = CodeExecutor(code=bot_top_code) if bot_top_code else None
        self.bot_bottom = CodeExecutor(code=bot_bottom_code) if bot_bottom_code else None
        self.bot_top_type = 'bot' if bot_top_code else 'human'
        self.bot_bottom_type = 'bot' if bot_bottom_code else 'human'
        

    def run_turn(self, judge_input_json):
        if self.bot_top:
            bot_input = self._make_bot_input(judge_input_json, side='top')
            bot_output = self.bot_top.run(bot_input)
            action = json.loads(bot_output)["response"]
            # 补全responses最后一项
            if len(judge_input_json["responses"]) < len(judge_input_json["requests"]) - 1:
                judge_input_json["responses"].append(action)
            else:
                judge_input_json["responses"][-1] = action
        if self.bot_bottom:
            bot_input = self._make_bot_input(judge_input_json, side='bottom')
            bot_output = self.bot_bottom.run(bot_input)
            action = json.loads(bot_output)["response"]
            # 补全requests最后一项
            if len(judge_input_json["requests"]) < len(judge_input_json["responses"]) + 1:
                judge_input_json["requests"].append(action)
            else:
                judge_input_json["requests"][-1] = action

        # 2. 调用cpp裁判
        judge_output = self.cpp_judge.run_raw_json(judge_input_json)
        return judge_output

    def _make_bot_input(self, judge_input_json, side):
        # 生成bot输入格式，兼容bot协议
        # side: 'top' or 'bottom'
        side_idx = 0 if side == 'top' else 1
        opponent = 'bottom' if side == 'top' else 'top'
        # 取地图
        map_obj = judge_input_json["requests"][0].copy()
        map_obj["mySide"] = side_idx
        # 取历史
        my_history = judge_input_json["responses"]
        opponent_history = judge_input_json["requests"][1:]
        return json.dumps({
            "requests": [map_obj] + opponent_history,
            "responses": my_history
        })

    def terminate(self):
        if self.bot_top: self.bot_top.cleanup()
        if self.bot_bottom: self.bot_bottom.cleanup()

# --- SocketIO事件注册 ---
def register_tank_events(socketio):
    @socketio.on('connect', namespace='/tank2')
    def handle_connect():
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id})

    @socketio.on('new_game', namespace='/tank2')
    def new_game(data):
        user_id = data['user_id']
        bot_top_code = data.get('bot_top_code')
        bot_bottom_code = data.get('bot_bottom_code')
        cpp_path = os.path.join(os.path.dirname(__file__), '../judges/tank_judge.exe')
        game = TankGameSession(cpp_path, bot_top_code, bot_bottom_code)
        sessions[user_id] = {'sid': request.sid, 'game': game}

        # Get player selections from the frontend.
        # Assumes frontend sends 'top_player_id' and 'bottom_player_id'
        # where the value is 'human' or a bot ID string.
        player_1_id = data.get('top_player_id')
        player_2_id = data.get('bottom_player_id')

        player_1_type = 'human' if player_1_id == 'human' else 'bot'
        player_2_type = 'human' if player_2_id == 'human' else 'bot'

        top_executor = _get_bot_executor(player_1_id) if player_1_type == 'bot' else None
        bot_executor = _get_bot_executor(player_2_id) if player_2_type == 'bot' else None

        game_state_dict = game.cpp_judge.run_raw_json({});
        print(game_state_dict);
        maxTurn = game_state_dict['initdata']['maxTurn']
        judge_input_dict = {'log':[], 'initdata': game_state_dict['initdata']}

        input_dict_1 = { "requests": [game_state_dict['content']['0']], "responses": [] }
        input_dict_2 = { "requests": [game_state_dict['content']['1']], "responses": [] }

        user_session = sessions.get(user_id)
        sid = user_session['sid']
        displays = []
        emit('game_started', {
            'state': game_state_dict['display'],
            'game_id': game.game_id
        }, room=sid)
        displays.append(game_state_dict['display'])

        for turn in range(maxTurn):
            # time.sleep(1)
            # print('this send to frontend', game_state_dict['display'])

            input_str_1 = json.dumps(input_dict_1)
            input_str_2 = json.dumps(input_dict_2)
            # print(f"========== Turn {turn + 1} Input ==========\n {top_input_str}\n {bot_input_str}")

            top_output = top_executor.run(input_str_1)
            bot_output = bot_executor.run(input_str_2)
            # print(f"========== Turn {turn + 1} Output ==========\n {top_output}\n {bot_output}")
            
            # 构造裁判输入
            judge_input_dict['log'].append({}) # 奇数个元素留空
            judge_input_dict['log'].append({"0": json.loads(top_output), "1": json.loads(bot_output)})
            game_state_dict = game.cpp_judge.run_raw_json(judge_input_dict)
            displays.append(game_state_dict['display'])
            response = {
                'state': game_state_dict['display'],
                'game_id': game.game_id
            }
            emit('update', response, room=sid)

            if game_state_dict['command'] == 'finish':
                # print(game_state_dict)
                winner = -2  # TODO: Determine winner from game_state_dict
                # --- Insert match record into database ---
                try:
                    conn = get_db_connection()
                    # 查 bots 表获取用户名
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT bot_name FROM bots WHERE id = %s", (player_1_id,))
                        row1 = cursor.fetchone()
                        username_1 = row1['bot_name'] if row1 else str(player_1_id)
                        if player_1_type == 'human':
                            username_1 = '<i>HUMAN</i>'
                        cursor.execute("SELECT bot_name FROM bots WHERE id = %s", (player_2_id,))
                        row2 = cursor.fetchone()
                        username_2 = row2['bot_name'] if row2 else str(player_2_id)
                        if player_2_type == 'human':
                            username_2 = '<i>HUMAN</i>'
                    players = json.dumps({'player_1': username_1, 'player_2': username_2})
                    with conn.cursor() as cursor:
                        sql = """
                            INSERT INTO matches (game, players, winner, displays)
                            VALUES (%s, %s, %s, %s)
                        """
                        cursor.execute(sql, (
                            'Tank Battle',
                            players,
                            winner,
                            json.dumps(displays)
                        ))
                        conn.commit()
                except Exception as e:
                    print("Failed to insert match record:", e)
                finally:
                    if conn:
                        conn.close()
                # --- End DB insert ---
                print("Game finished by judge.")
                break
            input_dict_1['requests'].append(json.loads(bot_output)['response'])
            input_dict_1['responses'].append(json.loads(top_output)['response'])
            input_dict_2['requests'].append(json.loads(top_output)['response'])
            input_dict_2['responses'].append(json.loads(bot_output)['response'])

            
            

    @socketio.on('player_move', namespace='/tank2')
    def handle_player_move(data):
        user_id = data.get('user_id')
        judge_input_json = data.get('judge_input_json')
        if not user_id or not judge_input_json: return
        game = sessions.get(user_id, {}).get('game')
        if not game: return
        judge_output = game.run_turn(judge_input_json)
        emit('update', judge_output, room=sessions[user_id]['sid'])

    @socketio.on('disconnect', namespace='/tank2')
    def handle_disconnect():
        user_id_to_del = None
        for user_id, session_data in sessions.items():
            if session_data.get('sid') == request.sid:
                game = session_data.get('game')
                if game: game.terminate()
                user_id_to_del = user_id
                break
        if user_id_to_del:
            del sessions[user_id_to_del]