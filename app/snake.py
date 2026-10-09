import json
import os
from uuid import uuid4
import concurrent.futures

from flask import Blueprint, request
from flask_login import current_user
from flask_socketio import emit, join_room, disconnect

from .code_executor import CodeExecutor
from .cpp_judge_executor import CppJudgeExecutor
from .db import get_db_connection
from .services.rating_service import update_bot_ratings
from .services.bot_service import load_latest_version, player_json_for_bot, player_json_for_human

snake_bp = Blueprint('snake', __name__)
sessions = {}
active_matches = {}


def _get_bot_executor(bot_id):
    rec = load_latest_version(bot_id)
    if not rec:
        return None
    return CodeExecutor(workdir=rec['file_path'], language=rec['language'])


class SnakeGameSession:
    def __init__(self, cpp_path):
        self.game_id = str(uuid4())
        self.cpp_judge = CppJudgeExecutor(cpp_path)

    def terminate(self):
        pass


def register_snake_events(socketio):
    @socketio.on('connect', namespace='/snake')
    def handle_connect():
        if not current_user.is_authenticated:
            disconnect()
            return False
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id})

    @socketio.on('join_match', namespace='/snake')
    def handle_join_match(data):
        match_id = data.get('match_id')
        if not match_id:
            return
        join_room(match_id)
        print(f'{request.sid} joined snake match room {match_id}')

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
                print("Error loading snake match status:", e)
            finally:
                if conn:
                    conn.close()

    @socketio.on('new_game', namespace='/snake')
    def new_game(data):
        user_id = data['user_id']
        if user_id in sessions:
            sessions[user_id]['terminated'] = True

        match_id = data.get('match_id')

        cpp_path = os.path.join(os.path.dirname(__file__), '../judges/snake_judge.exe')
        game_name = data.get('game_name', 'Snake')
        if game_name == 'Mini Snake' or '/msnake' in data.get('page_path', ''):
            cpp_path = os.path.join(os.path.dirname(__file__), '../judges/msnake_judge.exe')

        game = SnakeGameSession(cpp_path)
        sid = request.sid

        player_1_id_str = data.get('left_player_id') or data.get('p1_bot_id')
        player_2_id_str = data.get('right_player_id') or data.get('p2_bot_id')
        player_1_type = 'human' if data.get('left_is_human') or data.get('p1_is_human') else 'bot'
        player_2_type = 'human' if data.get('right_is_human') or data.get('p2_is_human') else 'bot'

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

        print(f"Starting snake game {game.game_id} (match={match_id}): "
              f"{player_1_id_str} ({player_1_type}) vs {player_2_id_str} ({player_2_type})")

        try:
            game_state_dict = game.cpp_judge.run_raw_json({})

            maxTurn = 200
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

            for turn in range(maxTurn):
                session_gone = user_id not in sessions or sessions[user_id].get('sid') != sid
                if session_gone and (player_1_type == 'human' or player_2_type == 'human'):
                    print(f"Human player {user_id} disconnected, terminating snake game loop.")
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

                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    future1 = pool.submit(get_output_1)
                    future2 = pool.submit(get_output_2)
                    output_1 = future1.result()
                    output_2 = future2.result()

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
                    if 'winner' in game_state_dict.get('display', {}):
                        winner = int(game_state_dict['display']['winner'])
                    else:
                        winner = -1

                    emit('finish', {
                        'winner': winner,
                        'game_id': game.game_id,
                        'match_id': match_id,
                    }, room=broadcast_target)

                    conn = None
                    try:
                        conn = get_db_connection()
                        p1_json = player_json_for_bot(player_1_id_str) if player_1_type == 'bot' else player_json_for_human()
                        p2_json = player_json_for_bot(player_2_id_str) if player_2_type == 'bot' else player_json_for_human()
                        players = json.dumps({'player_1': p1_json, 'player_2': p2_json})

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
                                """, (uuid4().hex, 'Snake', players, winner, json.dumps(displays)))
                            conn.commit()
                    except Exception as e:
                        print("Failed to save snake match record:", e)
                    finally:
                        if conn:
                            conn.close()

                    if player_1_type == 'bot' and player_2_type == 'bot':
                        update_bot_ratings(player_1_id_str, player_2_id_str, winner if winner in (0, 1) else -1)

                    if match_id:
                        socketio.emit('match_finished', {
                            'match_id': match_id,
                            'winner': winner,
                            'displays': displays,
                        }, room=match_id)

                    print(f"Snake game finished (match={match_id}). Winner: {winner}")
                    break

                input_dict_1['requests'].append(json.loads(output_2)['response'])
                input_dict_1['responses'].append(json.loads(output_1)['response'])
                input_dict_2['requests'].append(json.loads(output_1)['response'])
                input_dict_2['responses'].append(json.loads(output_2)['response'])

        finally:
            if match_id:
                active_matches.pop(match_id, None)
            game.terminate()

    @socketio.on('disconnect', namespace='/snake')
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

    @socketio.on('player_move', namespace='/snake')
    def handle_player_move(data):
        user_id = data.get('user_id')
        game_id = data.get('game_id')
        user_session = sessions.get(user_id)

        if not user_id or not game_id or not user_session:
            return

        move = json.loads(data.get('move'))
        sessions[user_id]['pending_move'] = move


def run_auto_snake_match(player_1_id, player_2_id):
    """
    自动（AI vs AI）Snake 对战。由 battle_worker 后台调用。
    与 register_snake_events 里的对战循环同构，但：
      - 不依赖 socket/human
      - 创建 matches 记录并在结束后写回 winner / displays
      - 调用 update_bot_ratings 更新 ELO
    """
    print(f"Running auto Snake match: {player_1_id} vs {player_2_id}")

    executor_1 = _get_bot_executor(str(player_1_id))
    executor_2 = _get_bot_executor(str(player_2_id))
    if not executor_1 or not executor_2:
        print("Error: Failed to load both bot executors for auto Snake match.")
        return

    match_id = uuid4().hex

    # 1) 创建 matches 记录
    conn = None
    try:
        conn = get_db_connection()
        players = json.dumps({
            'player_1': player_json_for_bot(player_1_id),
            'player_2': player_json_for_bot(player_2_id),
        })
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO matches (id, game, players, status) VALUES (?, ?, ?, 'playing')",
                (match_id, 'Snake', players),
            )
            conn.commit()
    except Exception as e:
        print("Failed to create auto Snake match record:", e)
        if conn:
            conn.close()
        executor_1.cleanup()
        executor_2.cleanup()
        return
    finally:
        if conn:
            conn.close()

    # 2) 跑对战
    cpp_path = os.path.join(os.path.dirname(__file__), '../judges/snake_judge.exe')
    cpp_judge = CppJudgeExecutor(cpp_path)

    displays = []
    winner = -1
    try:
        game_state_dict = cpp_judge.run_raw_json({})
        max_turn = 200
        judge_input = {'log': [], 'initdata': game_state_dict['initdata']}
        input_1 = {"requests": [game_state_dict['content']['0']], "responses": []}
        input_2 = {"requests": [game_state_dict['content']['1']], "responses": []}
        displays.append(game_state_dict['display'])

        for _ in range(max_turn):
            out1 = executor_1.run(json.dumps(input_1))
            out2 = executor_2.run(json.dumps(input_2))
            judge_input['log'].append({})
            judge_input['log'].append({"0": json.loads(out1), "1": json.loads(out2)})
            game_state_dict = cpp_judge.run_raw_json(judge_input)
            displays.append(game_state_dict['display'])

            if game_state_dict['command'] == 'finish':
                if 'winner' in game_state_dict.get('display', {}):
                    winner = int(game_state_dict['display']['winner'])
                else:
                    winner = -1
                break

            r1 = json.loads(out1)['response']
            r2 = json.loads(out2)['response']
            input_1['requests'].append(r2)
            input_1['responses'].append(r1)
            input_2['requests'].append(r1)
            input_2['responses'].append(r2)
    except Exception as e:
        print(f"Auto Snake match crashed: {e}")
    finally:
        executor_1.cleanup()
        executor_2.cleanup()

    # winner 标准化：0/1/-1
    db_winner = winner if winner in (0, 1) else -1
    elo_winner = winner if winner in (0, 1) else -1
    update_bot_ratings(player_1_id, player_2_id, elo_winner)

    # 3) 写回 matches
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE matches SET winner = ?, displays = ?, status = 'finished'
                WHERE id = ?
            """, (db_winner, json.dumps(displays), match_id))
            conn.commit()
    except Exception as e:
        print("Failed to update auto Snake match record:", e)
    finally:
        if conn:
            conn.close()

    print(f"Auto Snake match finished. Winner: {db_winner} (-1=draw, 0=P1, 1=P2)")
