from flask import Blueprint, request
from flask_login import current_user
from . import socketio
from judges.connect4_judge import ConnectFourJudge, COLS, ROWS
from uuid import uuid4
from flask_socketio import emit, join_room
import json
import uuid
from .services.rating_service import update_bot_ratings
from .services.bot_service import get_bot_executor as _get_bot_executor, build_players_json
from .services.match_service import (create_match_record, finalize_match_record,
                                     update_match_result, state_payload)

connect4_bp = Blueprint('connect4', __name__)

sessions = {}
active_matches = {}

GAME_NAME = 'Connect Four'
MAX_TURNS = COLS * ROWS


def _emit_state(game, match_id, room, extra=None):
    payload = {'match_id': match_id}
    if extra:
        payload.update(extra)
    emit('update', state_payload(game, payload), room=room)


def _parse_column(output_str):
    """Read the chosen column from a bot's stdout. Returns None if unusable."""
    try:
        return int(json.loads(output_str)['x'])
    except (ValueError, TypeError, KeyError):
        return None


def run_auto_connect4_match(player_1_id, player_2_id):
    """Non-interactive (AI vs AI) Connect Four match for the background ladder."""
    print(f"Running auto Connect Four match: {player_1_id} vs {player_2_id}")

    executor_1 = _get_bot_executor(str(player_1_id))
    executor_2 = _get_bot_executor(str(player_2_id))
    if not executor_1 or not executor_2:
        print("Error: Failed to load both bot executors for auto match.")
        return

    players = build_players_json(player_1_id, 'bot', player_2_id, 'bot')
    try:
        match_id = create_match_record(GAME_NAME, players)
    except Exception as e:
        print("Failed to create auto match record:", e)
        executor_1.cleanup()
        executor_2.cleanup()
        return

    game = ConnectFourJudge()
    game.game_id = str(uuid.uuid4())
    game.new_game('bot', 'bot', executor_1, executor_2)

    active_matches[match_id] = {
        'judge': game,
        'game_id': game.game_id,
        'player_1_id': player_1_id,
        'player_2_id': player_2_id,
        'player_1_type': 'bot',
        'player_2_type': 'bot',
    }

    socketio.emit('match_started', {
        'match_id': match_id, 'board': game.board, 'game_id': game.game_id
    }, room=match_id)

    try:
        for _ in range(MAX_TURNS):
            input_str = game.send_action_to_ai()
            executor = executor_1 if game.current_player == 1 else executor_2

            # A bot that crashes, times out or answers nonsense forfeits rather
            # than taking the whole match thread down with it.
            try:
                col = _parse_column(executor.run(input_str))
            except Exception as exc:
                print(f"Connect Four bot {game.current_player} failed: {exc}")
                game.winner = 3 - game.current_player
                break

            if game.is_terminated:
                break
            if col is None or not game.apply_move(col):
                game.winner = 3 - game.current_player
                break

            landed = game.move_history[-1]
            winner = game.check_win(landed['x'], landed['y'])
            if winner != 0:
                game.winner = winner

            socketio.emit('update', state_payload(game, {
                'ai_move': {'x': landed['x'], 'y': landed['y'], 'player': 3 - game.current_player},
                'match_id': match_id,
            }), room=match_id)

            if game.winner != 0 or game.is_board_full():
                break
    except Exception as exc:
        # Anything unexpected still has to close the match out, otherwise the
        # row is stranded at status='playing' and the rating never moves.
        print(f"Connect Four auto match aborted: {exc}")
    finally:
        active_matches.pop(match_id, None)
        executor_1.cleanup()
        executor_2.cleanup()

    elo_winner = (game.winner - 1) if game.winner in (1, 2) else -1
    update_bot_ratings(player_1_id, player_2_id, elo_winner, match_id)
    update_match_result(match_id, elo_winner, json.dumps(game.move_history), 'move_history')

    socketio.emit('match_finished', {
        'match_id': match_id,
        'winner': game.winner,
        'move_history': game.move_history,
    }, room=match_id)


def register_connect4_events(socketio):
    @socketio.on('connect', namespace='/connect4')
    def handle_connect():
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id}, room=request.sid)

    @socketio.on('join_match', namespace='/connect4')
    def handle_join_match(data):
        match_id = data.get('match_id')
        if not match_id:
            return
        join_room(match_id)

        if match_id in active_matches:
            match_info = active_matches[match_id]
            game = match_info['judge']
            emit('match_status', state_payload(game, {
                'match_id': match_id,
                'status': 'playing',
                'move_history': game.move_history
            }), room=request.sid)
        else:
            from .db import get_db_connection
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, move_history, winner, players FROM matches WHERE id = ?", (match_id,))
                    match = cursor.fetchone()
                if match and match['status'] == 'finished':
                    move_history = json.loads(match['move_history']) if match['move_history'] else []
                    db_winner = match['winner']
                    game_winner = (db_winner + 1) if db_winner in (0, 1) else 0
                    emit('match_status', {
                        'match_id': match_id,
                        'status': 'finished',
                        'winner': game_winner,
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

    @socketio.on('new_game', namespace='/connect4')
    def new_game(data):
        if not current_user.is_authenticated:
            return
        user_id = data['user_id']
        user_session = sessions.get(user_id)
        if not user_session:
            return

        game = ConnectFourJudge()
        game.game_id = str(uuid.uuid4())

        sid = user_session['sid']
        match_id = data.get('match_id')
        sessions[user_id] = {'sid': sid, 'match_id': match_id, game.game_id: game}

        player_1_id = data.get('black_bot')
        player_2_id = data.get('white_bot')
        player_1_type = 'human' if data.get('black_is_human', False) else 'bot'
        player_2_type = 'human' if data.get('white_is_human', False) else 'bot'

        executor_1 = _get_bot_executor(player_1_id) if player_1_type == 'bot' else None
        executor_2 = _get_bot_executor(player_2_id) if player_2_type == 'bot' else None

        game.new_game(player_1_type, player_2_type, executor_1, executor_2)

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

        emit('game_started', state_payload(game), room=broadcast_target)

        def wait_for_human():
            while 'pending_move' not in sessions.get(user_id, {}):
                if user_id not in sessions or sessions[user_id]['sid'] != sid:
                    break
                socketio.sleep(0.05)
            return json.dumps(sessions[user_id].pop('pending_move')) \
                if 'pending_move' in sessions.get(user_id, {}) else None

        def get_output_1(input_str=None):
            return wait_for_human() if player_1_type == 'human' else executor_1.run(input_str)

        def get_output_2(input_str=None):
            return wait_for_human() if player_2_type == 'human' else executor_2.run(input_str)

        try:
            for _ in range(MAX_TURNS):
                input_str = game.send_action_to_ai()
                get_output = get_output_1 if game.current_player == 1 else get_output_2

                # A crashed bot, or a human who left, forfeits instead of
                # killing the thread that writes the match record.
                try:
                    output_str = get_output(input_str)
                    if output_str is None:
                        game.winner = 3 - game.current_player
                        break
                    col = _parse_column(output_str)
                except Exception as exc:
                    print(f"Connect Four player {game.current_player} failed: {exc}")
                    game.winner = 3 - game.current_player
                    break

                if game.is_terminated:
                    break
                if col is None or not game.apply_move(col):
                    game.winner = 3 - game.current_player
                    _emit_state(game, match_id, broadcast_target, {'error_msg': 'Invalid move.'})
                    break

                landed = game.move_history[-1]
                winner = game.check_win(landed['x'], landed['y'])
                if winner != 0:
                    game.winner = winner

                _emit_state(game, match_id, broadcast_target, {
                    'ai_move': {'x': landed['x'], 'y': landed['y'], 'player': 3 - game.current_player}
                })
                if game.winner != 0 or game.is_board_full():
                    break
        except Exception as exc:
            print(f"Connect Four match aborted: {exc}")
        finally:
            if match_id:
                active_matches.pop(match_id, None)

        elo_winner = (game.winner - 1) if game.winner in (1, 2) else -1
        if player_1_type == 'bot' and player_2_type == 'bot':
            update_bot_ratings(player_1_id, player_2_id, elo_winner, match_id)

        players = build_players_json(player_1_id, player_1_type, player_2_id, player_2_type, human_name=current_user.username)
        finalize_match_record(match_id, GAME_NAME, players, elo_winner, json.dumps(game.move_history), 'move_history')

        if match_id:
            socketio.emit('match_finished', {
                'match_id': match_id,
                'winner': game.winner,
                'move_history': game.move_history,
            }, room=match_id)

    @socketio.on('player_move', namespace='/connect4')
    def handle_player_move(data):
        user_id = data.get('user_id')
        game_id = data.get('game_id')
        user_session = sessions.get(user_id)
        if not user_id or not game_id or not user_session:
            return
        sessions[user_id]['pending_move'] = data

    @socketio.on('disconnect', namespace='/connect4')
    def handle_disconnect():
        user_id_to_del = None
        for user_id, session_data in sessions.items():
            if session_data.get('sid') == request.sid:
                user_id_to_del = user_id
                break
        if user_id_to_del:
            del sessions[user_id_to_del]
