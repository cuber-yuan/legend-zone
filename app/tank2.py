from flask import Blueprint, request
from flask_login import current_user
from . import socketio
from .cpp_judge_executor import CppJudgeExecutor
from judges.build import judge_binary_path
from flask_socketio import emit, join_room
from uuid import uuid4
import os
import json
from .db import get_db_connection
from .services.bot_service import get_bot_executor as _get_bot_executor, build_players_json
from .services.match_service import create_match_record
from .services.match_lifecycle import match_lifecycle, read_simultaneous_actions

tank_bp = Blueprint('tank', __name__)
sessions = {}
active_matches = {}


class TankGameSession:
    def __init__(self, cpp_path):
        self.game_id = str(uuid4())
        self.cpp_path = cpp_path
        self.cpp_judge = None

    def terminate(self):
        pass


def tank_payload(game_id, match_id, player_1_type, player_2_type, state=None, extra=None):
    """Build the per-turn client payload.

    Both sides command their two tanks before the judge advances, so the browser
    needs `player_types` to know which seat (if any) it is supposed to steer, and
    it must never offer an action the judge would reject outright.
    """
    payload = {
        'game_id': game_id,
        'match_id': match_id,
        'player_types': {'1': player_1_type, '2': player_2_type},
    }
    if state is not None:
        payload['state'] = state
    if extra:
        payload.update(extra)
    return payload


def register_tank_events(socketio):
    @socketio.on('connect', namespace='/tank2')
    def handle_connect():
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
                'player_types': {'1': match_info['player_1_type'], '2': match_info['player_2_type']},
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
        if not current_user.is_authenticated:
            return
        user_id = data['user_id']
        if user_id in sessions:
            sessions[user_id]['terminated'] = True

        match_id = data.get('match_id')

        cpp_path = judge_binary_path('tank2_judge')
        game = TankGameSession(cpp_path)
        sid = request.sid

        player_1_id_str = data.get('top_player_id') or data.get('p1_bot_id')
        player_2_id_str = data.get('bottom_player_id') or data.get('p2_bot_id')
        player_1_type = 'human' if data.get('top_is_human') or data.get('p1_is_human') else 'bot'
        player_2_type = 'human' if data.get('bottom_is_human') or data.get('p2_is_human') else 'bot'

        executor_1 = _get_bot_executor(player_1_id_str, match_id=match_id, seat=1) if player_1_type == 'bot' else None
        executor_2 = _get_bot_executor(player_2_id_str, match_id=match_id, seat=2) if player_2_type == 'bot' else None

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

        displays = []
        players = build_players_json(
            player_1_id_str, player_1_type, player_2_id_str, player_2_type,
            human_name=current_user.username,
        )
        with match_lifecycle(
            match_id=match_id, game_name='Tank Battle', players=players,
            player_ids=(player_1_id_str, player_2_id_str),
            player_types=(player_1_type, player_2_type), payload_col='displays',
            socketio=socketio, namespace='/tank2', room=broadcast_target,
            active_matches=active_matches, executors=(executor_1, executor_2),
            cleanup=(game.terminate,),
            notify=lambda result: emit('finish', tank_payload(
                game.game_id, match_id, player_1_type, player_2_type,
                extra={'winner': result.winner, 'error_msg': result.error_msg},
            ), room=broadcast_target),
        ) as result:
            result.payload = displays
            game.cpp_judge = CppJudgeExecutor(game.cpp_path)
            game_state_dict = game.cpp_judge.run_raw_json({})

            maxTurn = game_state_dict['initdata']['maxTurn']
            judge_input_dict = {'log': [], 'initdata': game_state_dict['initdata']}
            input_dict_1 = {"requests": [game_state_dict['content']['0']], "responses": []}
            input_dict_2 = {"requests": [game_state_dict['content']['1']], "responses": []}

            emit('game_started', tank_payload(game.game_id, match_id, player_1_type, player_2_type,
                                              state=game_state_dict['display']), room=broadcast_target)
            displays.append(game_state_dict['display'])

            if match_id and match_id in active_matches:
                active_matches[match_id]['latest_display'] = game_state_dict['display']

            winner = None
            for turn in range(maxTurn):
                session_gone = user_id not in sessions or sessions[user_id].get('sid') != sid
                if session_gone and (player_1_type == 'human' or player_2_type == 'human'):
                    print(f"Human player {user_id} disconnected, terminating tank game loop.")
                    winner = 1 if player_1_type == 'human' else 0
                    break

                input_str_1 = json.dumps(input_dict_1)
                input_str_2 = json.dumps(input_dict_2)

                def wait_for_human(seat):
                    """Pop one seat's command, or return None if the player walked away."""
                    while seat not in (sessions.get(user_id, {}).get('pending_moves') or {}):
                        if user_id not in sessions or sessions[user_id].get('sid') != sid:
                            return None
                        socketio.sleep(0.05)
                    session = sessions.get(user_id) or {}
                    return json.dumps((session.get('pending_moves') or {}).pop(seat))

                def get_output_1():
                    return wait_for_human('1') if player_1_type == 'human' else executor_1.run(input_str_1)

                def get_output_2():
                    return wait_for_human('2') if player_2_type == 'human' else executor_2.run(input_str_2)

                output_1, output_2 = read_simultaneous_actions((get_output_1, get_output_2), (input_str_1, input_str_2))

                judge_input_dict['log'].append({})
                judge_input_dict['log'].append({"0": output_1, "1": output_2})
                game_state_dict = game.cpp_judge.run_raw_json(judge_input_dict)
                displays.append(game_state_dict['display'])

                emit('update', tank_payload(game.game_id, match_id, player_1_type, player_2_type,
                                            state=game_state_dict['display']), room=broadcast_target)

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

                input_dict_1['requests'].append(output_2['response'])
                input_dict_1['responses'].append(output_1['response'])
                input_dict_2['requests'].append(output_1['response'])
                input_dict_2['responses'].append(output_2['response'])

            result.winner = winner if winner in (0, 1) else -1

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
        seat = str(data.get('seat') or '1')
        user_session = sessions.get(user_id)

        if not user_id or not game_id or not user_session:
            return

        move = json.loads(data.get('move'))
        # One mailbox slot per seat: a hot-seat match has this one browser answering
        # for both sides, and each side's getter must take its own command.
        user_session.setdefault('pending_moves', {})[seat] = move


def run_auto_tank_match(player_1_id, player_2_id):
    """
    Automated (AI vs AI) Tank Battle match, invoked in the background by battle_worker.
    Mirrors the match loop in register_tank_events, except:
      - no socket/human dependency
      - creates a matches record and writes back winner / displays when finished
      - calls update_bot_ratings to update ELO
    Winner semantics: 0 = Top Player wins, 1 = Bottom Player wins, -1 = draw
    """
    print(f"Running auto Tank match: {player_1_id} (Top) vs {player_2_id} (Bottom)")

    executor_1 = _get_bot_executor(str(player_1_id))
    executor_2 = _get_bot_executor(str(player_2_id))
    if not executor_1 or not executor_2:
        print("Error: Failed to load both bot executors for auto Tank match.")
        return

    # 1) Create the matches record
    players = build_players_json(player_1_id, 'bot', player_2_id, 'bot')
    try:
        match_id = create_match_record('Tank Battle', players)
    except Exception as e:
        print("Failed to create auto Tank match record:", e)
        executor_1.cleanup()
        executor_2.cleanup()
        return

    displays = []
    winner = -1
    with match_lifecycle(
        match_id=match_id, game_name='Tank Battle', players=players,
        player_ids=(player_1_id, player_2_id), player_types=('bot', 'bot'),
        payload_col='displays', socketio=socketio, namespace='/tank2',
        room=match_id, active_matches=active_matches,
        executors=(executor_1, executor_2),
    ) as result:
        result.payload = displays
        cpp_judge = CppJudgeExecutor(judge_binary_path('tank2_judge'))
        game_state_dict = cpp_judge.run_raw_json({})
        max_turn = game_state_dict['initdata']['maxTurn']
        judge_input = {'log': [], 'initdata': game_state_dict['initdata']}
        input_1 = {"requests": [game_state_dict['content']['0']], "responses": []}
        input_2 = {"requests": [game_state_dict['content']['1']], "responses": []}
        displays.append(game_state_dict['display'])

        for _ in range(max_turn):
            input_str_1, input_str_2 = json.dumps(input_1), json.dumps(input_2)
            out1, out2 = read_simultaneous_actions(
                (lambda: executor_1.run(input_str_1), lambda: executor_2.run(input_str_2)),
                (input_str_1, input_str_2),
            )
            judge_input['log'].append({})
            judge_input['log'].append({"0": out1, "1": out2})
            game_state_dict = cpp_judge.run_raw_json(judge_input)
            displays.append(game_state_dict['display'])

            if game_state_dict['command'] == 'finish':
                # Tank2 rule: content[side] == 2 marks the WINNING side (0 = lost, 1 = draw).
                content = game_state_dict.get('content', {})
                result_0 = content.get('0', 1)
                result_1 = content.get('1', 1)
                if result_0 == 2 and result_1 != 2:
                    winner = 0  # side 0 won
                elif result_1 == 2 and result_0 != 2:
                    winner = 1  # side 1 won
                else:
                    winner = -1
                break

            r1 = out1['response']
            r2 = out2['response']
            input_1['requests'].append(r2)
            input_1['responses'].append(r1)
            input_2['requests'].append(r1)
            input_2['responses'].append(r2)
        result.winner = winner if winner in (0, 1) else -1
