from flask import Blueprint, request
from flask_login import current_user
from . import socketio
from .cpp_judge_executor import CppJudgeExecutor
from .code_executor import CodeExecutor
from flask_socketio import emit, join_room, disconnect
from uuid import uuid4
import os
import json
import concurrent.futures
from .db import get_db_connection

tank_bp = Blueprint('tank', __name__)
sessions = {}
active_matches = {}


def _get_bot_executor(bot_id):
    if not bot_id:
        return None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT source_code, file_path, language FROM bots WHERE id = ?", (bot_id,))
            result = cursor.fetchone()
        if result:
            return CodeExecutor(code=result['source_code'], language=result['language'], path=result['file_path'])
    finally:
        if conn:
            conn.close()
    return None


class TankGameSession:
    def __init__(self, cpp_path):
        self.game_id = str(uuid4())
        self.cpp_judge = CppJudgeExecutor(cpp_path)

    def terminate(self):
        pass


def register_tank_events(socketio):
    @socketio.on('connect', namespace='/tank2')
    def handle_connect():
        if not current_user.is_authenticated:
            disconnect()
            return False
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id})

    @socketio.on('join_match', namespace='/tank2')
    def handle_join_match(data):
        match_id = data.get('match_id')
        if not match_id:
            return
        join_room(match_id)
        print(f'{request.sid} joined tank match room {match_id}')

        if match_id in active_matches:
            match_info = active_matches[match_id]
            emit('match_status', {
                'match_id': match_id,
                'status': 'playing',
                'game_id': match_info['game_id'],
                'latest_display': match_info.get('latest_display'),
            }, room=request.sid)
        else:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, displays, winner, players FROM matches WHERE id = ?", (match_id,))
                    match = cursor.fetchone()
                if match and match['status'] == 'finished':
                    displays = json.loads(match['displays']) if match['displays'] else []
                    emit('match_status', {
                        'match_id': match_id,
                        'status': 'finished',
                        'winner': match['winner'],
                        'displays': displays,
                    }, room=request.sid)
                elif match and match['status'] == 'playing':
                    emit('match_status', {
                        'match_id': match_id,
                        'status': 'not_started',
                        'players': match['players'],
                    }, room=request.sid)
            except Exception as e:
                print("Error loading tank match status:", e)
            finally:
                if conn:
                    conn.close()

    @socketio.on('new_game', namespace='/tank2')
    def new_game(data):
        user_id = data['user_id']
        if user_id in sessions:
            sessions[user_id]['terminated'] = True

        match_id = data.get('match_id')

        cpp_path = os.path.join(os.path.dirname(__file__), '../judges/tank2_judge.exe')
        game = TankGameSession(cpp_path)
        sid = request.sid

        player_1_id_str = data.get('top_player_id') or data.get('p1_bot_id')
        player_2_id_str = data.get('bottom_player_id') or data.get('p2_bot_id')
        player_1_type = 'human' if data.get('top_is_human') or data.get('p1_is_human') else 'bot'
        player_2_type = 'human' if data.get('bottom_is_human') or data.get('p2_is_human') else 'bot'

        executor_1 = _get_bot_executor(player_1_id_str) if player_1_type == 'bot' else None
        executor_2 = _get_bot_executor(player_2_id_str) if player_2_type == 'bot' else None

        sessions[user_id] = {'sid': sid, 'match_id': match_id, 'game': game}

        broadcast_target = match_id if match_id else sid

        if match_id:
            active_matches[match_id] = {
                'game': game,
                'game_id': game.game_id,
                'player_1_id': player_1_id_str,
                'player_2_id': player_2_id_str,
                'player_1_type': player_1_type,
                'player_2_type': player_2_type,
                'latest_display': None,
            }

        print(f"Starting tank game {game.game_id} (match={match_id}): "
              f"{player_1_id_str} ({player_1_type}) vs {player_2_id_str} ({player_2_type})")

        try:
            game_state_dict = game.cpp_judge.run_raw_json({})

            maxTurn = game_state_dict['initdata']['maxTurn']
            judge_input_dict = {'log': [], 'initdata': game_state_dict['initdata']}
            input_dict_1 = {"requests": [game_state_dict['content']['0']], "responses": []}
            input_dict_2 = {"requests": [game_state_dict['content']['1']], "responses": []}

            displays = []

            emit('game_started', {
                'state': game_state_dict['display'],
                'game_id': game.game_id,
                'match_id': match_id,
            }, room=broadcast_target)
            displays.append(game_state_dict['display'])

            if match_id and match_id in active_matches:
                active_matches[match_id]['latest_display'] = game_state_dict['display']

            winner = None
            for turn in range(maxTurn):
                if user_id not in sessions or sessions[user_id].get('sid') != sid:
                    print(f"User {user_id} disconnected, terminating tank game loop.")
                    break

                input_str_1 = json.dumps(input_dict_1)
                input_str_2 = json.dumps(input_dict_2)

                def get_output_1():
                    if player_1_type == 'human':
                        while 'pending_move' not in sessions[user_id]:
                            if user_id not in sessions or sessions[user_id].get('sid') != sid:
                                break
                            socketio.sleep(0.05)
                        return json.dumps(sessions[user_id].pop('pending_move'))
                    else:
                        return executor_1.run(input_str_1)

                def get_output_2():
                    if player_2_type == 'human':
                        while 'pending_move' not in sessions[user_id]:
                            if user_id not in sessions or sessions[user_id].get('sid') != sid:
                                break
                            socketio.sleep(0.05)
                        return json.dumps(sessions[user_id].pop('pending_move'))
                    else:
                        return executor_2.run(input_str_2)

                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                        future1 = pool.submit(get_output_1)
                        future2 = pool.submit(get_output_2)
                        output_1 = future1.result()
                        output_2 = future2.result()
                except Exception as e:
                    print(f"Bot execution error on turn {turn + 1}: {e}")
                    p1_failed = future1.done() and future1.exception() is not None
                    p2_failed = future2.done() and future2.exception() is not None
                    if p1_failed and p2_failed:
                        winner = -1
                    elif p1_failed:
                        winner = 1
                    else:
                        winner = 0
                    break

                judge_input_dict['log'].append({})
                judge_input_dict['log'].append({"0": json.loads(output_1), "1": json.loads(output_2)})
                game_state_dict = game.cpp_judge.run_raw_json(judge_input_dict)
                displays.append(game_state_dict['display'])

                response = {
                    'state': game_state_dict['display'],
                    'game_id': game.game_id,
                    'match_id': match_id,
                }
                emit('update', response, room=broadcast_target)

                if match_id and match_id in active_matches:
                    active_matches[match_id]['latest_display'] = game_state_dict['display']

                if game_state_dict['command'] == 'finish':
                    content = game_state_dict.get('content', {})
                    result_0 = content.get('0', 1)
                    result_1 = content.get('1', 1)
                    if result_0 == 2:
                        winner = 0
                    elif result_1 == 2:
                        winner = 1
                    else:
                        winner = -1
                    break

                input_dict_1['requests'].append(json.loads(output_2)['response'])
                input_dict_1['responses'].append(json.loads(output_1)['response'])
                input_dict_2['requests'].append(json.loads(output_1)['response'])
                input_dict_2['responses'].append(json.loads(output_2)['response'])

            if winner is not None:
                emit('finish', {
                    'winner': winner,
                    'game_id': game.game_id,
                    'match_id': match_id,
                }, room=broadcast_target)

                conn = None
                try:
                    conn = get_db_connection()
                    with conn.cursor() as cursor:
                        username_1 = '<i>HUMAN</i>'
                        if player_1_type == 'bot' and player_1_id_str:
                            cursor.execute("SELECT bot_name FROM bots WHERE id = ?", (player_1_id_str,))
                            row1 = cursor.fetchone()
                            if row1:
                                username_1 = row1['bot_name']

                        username_2 = '<i>HUMAN</i>'
                        if player_2_type == 'bot' and player_2_id_str:
                            cursor.execute("SELECT bot_name FROM bots WHERE id = ?", (player_2_id_str,))
                            row2 = cursor.fetchone()
                            if row2:
                                username_2 = row2['bot_name']

                    players = json.dumps({'player_1': username_1, 'player_2': username_2})

                    with conn.cursor() as cursor:
                        if match_id:
                            cursor.execute("""
                                UPDATE matches SET players = ?, winner = ?, displays = ?, status = 'finished'
                                WHERE id = ?
                            """, (players, winner, json.dumps(displays), match_id))
                        else:
                            cursor.execute("""
                                INSERT INTO matches (id, game, players, winner, displays, status)
                                VALUES (?, ?, ?, ?, ?, 'finished')
                            """, (uuid4().hex, 'Tank Battle', players, winner, json.dumps(displays)))
                        conn.commit()
                except Exception as e:
                    print("Failed to save tank match record:", e)
                finally:
                    if conn:
                        conn.close()

                if match_id:
                    socketio.emit('match_finished', {
                        'match_id': match_id,
                        'winner': winner,
                        'displays': displays,
                    }, room=match_id)

                print(f"Tank game finished (match={match_id}). Winner: {winner}")

        finally:
            if match_id:
                active_matches.pop(match_id, None)
            game.terminate()

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

    @socketio.on('player_move', namespace='/tank2')
    def handle_player_move(data):
        user_id = data.get('user_id')
        game_id = data.get('game_id')
        user_session = sessions.get(user_id)

        if not user_id or not game_id or not user_session:
            return

        move = json.loads(data.get('move'))
        sessions[user_id]['pending_move'] = move
