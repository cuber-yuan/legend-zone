from flask import Blueprint, request
from flask_login import current_user
from . import socketio
from judges.gomoku_judge import GomokuJudge
from uuid import uuid4
from flask_socketio import emit, join_room
import json
import uuid
from .db import get_db_connection
from .services.bot_service import get_bot_executor as _get_bot_executor, build_players_json
from .services.match_service import create_match_record, state_payload
from .services.match_lifecycle import match_lifecycle, play_board_game, wait_for_move

gomoku_bp = Blueprint('gomoku', __name__)

sessions = {}
active_matches = {}


def run_auto_gomoku_match(player_1_id, player_2_id):
    """Run a scheduled bot match using the same completion path as live games."""
    executor_1 = _get_bot_executor(str(player_1_id))
    executor_2 = _get_bot_executor(str(player_2_id))
    executors = (executor_1, executor_2)
    if not all(executors):
        for executor in executors:
            if executor:
                executor.cleanup()
        return

    players = build_players_json(player_1_id, 'bot', player_2_id, 'bot')
    try:
        match_id = create_match_record('Gomoku', players)
    except Exception:
        for executor in executors:
            executor.cleanup()
        raise

    game = GomokuJudge()
    game.game_id = str(uuid.uuid4())
    with match_lifecycle(
        match_id=match_id, game_name='Gomoku', players=players,
        player_ids=(player_1_id, player_2_id), player_types=('bot', 'bot'),
        payload_col='move_history', socketio=socketio, namespace='/gomoku',
        room=match_id, active_matches=active_matches, executors=executors,
        board_game=game,
        notify=lambda result: socketio.emit('update', state_payload(game, {
            'match_id': match_id, 'error_msg': result.error_msg,
        }), room=match_id, namespace='/gomoku'),
    ):
        game.new_game('bot', 'bot', executor_1, executor_2)
        active_matches[match_id] = {
            'judge': game, 'game_id': game.game_id,
            'player_1_id': player_1_id, 'player_2_id': player_2_id,
            'player_1_type': 'bot', 'player_2_type': 'bot',
        }
        socketio.emit('match_started', {
            'match_id': match_id, 'board': game.board, 'game_id': game.game_id,
        }, room=match_id, namespace='/gomoku')
        play_board_game(
            game, (executor_1.run, executor_2.run),
            lambda extra: socketio.emit('update', state_payload(game, {
                'match_id': match_id, **extra,
            }), room=match_id, namespace='/gomoku'),
            256, column_only=False,
        )


def register_gomoku_events(socketio):
    @socketio.on('connect', namespace='/gomoku')
    def handle_connect():
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id}, room=request.sid)

    @socketio.on('join_match', namespace='/gomoku')
    def handle_join_match(data):
        match_id = data.get('match_id')
        if not match_id:
            return
        join_room(match_id)
        print(f'{request.sid} joined match room {match_id}')

        if match_id in active_matches:
            match_info = active_matches[match_id]
            game = match_info['judge']
            emit('match_status', state_payload(game, {
                'match_id': match_id,
                'status': 'playing',
                'move_history': game.move_history
            }), room=request.sid)
        else:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, move_history, winner, players FROM matches WHERE id = ?", (match_id,))
                    match = cursor.fetchone()
                if match and match['status'] == 'finished':
                    move_history = json.loads(match['move_history']) if match['move_history'] else []
                    db_winner = match['winner']
                    gomoku_winner = (db_winner + 1) if db_winner in (0, 1) else 0
                    emit('match_status', {
                        'match_id': match_id,
                        'status': 'finished',
                        'winner': gomoku_winner,
                        'move_history': move_history
                    }, room=request.sid)
                elif match and match['status'] == 'playing':
                    emit('match_status', {
                        'match_id': match_id,
                        'status': 'not_started',
                        'players': match['players']
                    }, room=request.sid)
            except Exception as e:
                print("Error loading match status:", e)
            finally:
                if conn:
                    conn.close()

    @socketio.on('new_game', namespace='/gomoku')
    def new_game(data):
        if not current_user.is_authenticated:
            return
        user_id = data['user_id']
        user_session = sessions.get(user_id)
        if not user_session: return

        for key, value in user_session.items():
            if isinstance(value, GomokuJudge):
                value.terminate()

        game = GomokuJudge()
        game.game_id = str(uuid.uuid4())
        
        sid = user_session['sid']
        match_id = data.get('match_id')
        sessions[user_id] = {'sid': sid, 'match_id': match_id, game.game_id: game}

        player_1_id = data.get('black_bot')
        player_2_id = data.get('white_bot')
        player_1_type = 'human' if data.get('black_is_human', False) else 'bot'
        player_2_type = 'human' if data.get('white_is_human', False) else 'bot'

        executor_1 = _get_bot_executor(player_1_id, match_id=match_id, seat=1) if player_1_type == 'bot' else None
        executor_2 = _get_bot_executor(player_2_id, match_id=match_id, seat=2) if player_2_type == 'bot' else None

        game.new_game(
            black_player_type=player_1_type,
            white_player_type=player_2_type,
            black_executor=executor_1,
            white_executor=executor_2
        )

        broadcast_target = match_id if match_id else sid

        if match_id:
            active_matches[match_id] = {
                'judge': game,
                'game_id': game.game_id,
                'player_1_id': player_1_id,
                'player_2_id': player_2_id,
                'player_1_type': player_1_type,
                'player_2_type': player_2_type,
            }

        players = build_players_json(
            player_1_id, player_1_type, player_2_id, player_2_type,
            human_name=current_user.username,
        )

        def get_output(player, input_str):
            player_type = (player_1_type, player_2_type)[player]
            if player_type == 'human':
                return wait_for_move(sessions, user_id, sid, game, socketio)
            return (executor_1, executor_2)[player].run(input_str)

        with match_lifecycle(
            match_id=match_id, game_name='Gomoku', players=players,
            player_ids=(player_1_id, player_2_id),
            player_types=(player_1_type, player_2_type),
            payload_col='move_history', socketio=socketio, namespace='/gomoku',
            room=broadcast_target, active_matches=active_matches,
            executors=(executor_1, executor_2), board_game=game,
            notify=lambda result: emit('update', state_payload(game, {
                'match_id': match_id, 'error_msg': result.error_msg,
            }), room=broadcast_target),
        ):
            emit('game_started', state_payload(game), room=broadcast_target)
            play_board_game(
                game, (lambda value: get_output(0, value), lambda value: get_output(1, value)),
                lambda extra: emit('update', state_payload(game, {
                    'match_id': match_id, **extra,
                }), room=broadcast_target),
                256, column_only=False,
            )

    @socketio.on('player_move', namespace='/gomoku')
    def handle_player_move(data):
        user_id = data.get('user_id')
        game_id = data.get('game_id') 
        user_session = sessions.get(user_id)
        if not user_id or not game_id or not user_session:
            return
        print(data)
        sessions[user_id]['pending_move'] = data


    @socketio.on('disconnect', namespace='/gomoku')
    def handle_disconnect():
        user_id_to_del = None
        for user_id, session_data in sessions.items():
            if session_data.get('sid') == request.sid:
                user_id_to_del = user_id
                break
        
        if user_id_to_del:
            del sessions[user_id_to_del]
            print(f'User {user_id_to_del} disconnected and all sessions cleaned up')