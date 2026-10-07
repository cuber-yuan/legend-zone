from flask import Blueprint, request
from . import socketio
from judges.gomoku_judge import GomokuJudge
from uuid import uuid4
from flask_socketio import emit, join_room
import json
import os
from .code_executor import CodeExecutor
import uuid
from .db import get_db_connection
from .services.rating_service import update_bot_ratings

gomoku_bp = Blueprint('gomoku', __name__)

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

def run_auto_gomoku_match(player_1_id, player_2_id):
    """
    Runs a non-interactive (AI vs AI) Gomoku match, updates rating, and logs result.
    This function is designed to be called by a background worker.
    player_1_id (Black), player_2_id (White)
    """
    print(f"Running auto Gomoku match: {player_1_id} (Black) vs {player_2_id} (White)")

    executor_1 = _get_bot_executor(str(player_1_id))
    executor_2 = _get_bot_executor(str(player_2_id))

    if not executor_1 or not executor_2:
        print("Error: Failed to load both bot executors for auto match.")
        return

    match_id = uuid.uuid4().hex

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT bot_name FROM bots WHERE id = ?", (player_1_id,))
            row1 = cursor.fetchone()
            name1 = row1['bot_name'] if row1 else str(player_1_id)
            cursor.execute("SELECT bot_name FROM bots WHERE id = ?", (player_2_id,))
            row2 = cursor.fetchone()
            name2 = row2['bot_name'] if row2 else str(player_2_id)
            players = json.dumps({'player_1': name1, 'player_2': name2})
            cursor.execute(
                "INSERT INTO matches (id, game, players, status) VALUES (?, ?, ?, 'playing')",
                (match_id, 'Gomoku', players)
            )
            conn.commit()
    except Exception as e:
        print("Failed to create auto match record:", e)
        if conn:
            conn.close()
        executor_1.cleanup()
        executor_2.cleanup()
        return
    finally:
        if conn:
            conn.close()

    game = GomokuJudge()
    game.game_id = str(uuid.uuid4())
    game.new_game(
        black_player_type='bot',
        white_player_type='bot',
        black_executor=executor_1,
        white_executor=executor_2
    )

    active_matches[match_id] = {
        'judge': game,
        'game_id': game.game_id,
        'player_1_id': player_1_id,
        'player_2_id': player_2_id,
        'player_1_type': 'bot',
        'player_2_type': 'bot',
    }

    try:
        socketio.emit('match_started', {'match_id': match_id, 'board': game.board, 'game_id': game.game_id}, room=match_id)

        for turn in range(256):
            input_str = game.send_action_to_ai()

            if game.current_player == 1:
                output_str = executor_1.run(input_str)
            else:
                output_str = executor_2.run(input_str)

            try:
                move_data = json.loads(output_str)
                x, y = move_data['x'], move_data['y']
            except (json.JSONDecodeError, KeyError):
                print(f"AI for player {game.current_player} returned invalid data. Player {3 - game.current_player} wins.")
                game.winner = 3 - game.current_player
                break

            if game.is_terminated:
                break

            if not game.apply_move(x, y):
                print(f"AI for player {game.current_player} made an invalid move. Player {3 - game.current_player} wins.")
                game.winner = 3 - game.current_player
                break

            winner = game.check_win(x, y)
            if winner != 0:
                game.winner = winner

            response = {
                'board': game.board,
                'ai_move': {'x': x, 'y': y, 'player': 3 - game.current_player},
                'winner': game.winner,
                'game_id': game.game_id,
                'match_id': match_id
            }
            socketio.emit('update', response, room=match_id)

            if game.winner != 0 or game.is_terminated:
                print(f"Game ended after {turn + 1} turns. Winner: {game.winner}")
                break
    finally:
        active_matches.pop(match_id, None)

    result_winner = game.winner if game.winner != 0 else -1
    elo_winner = result_winner - 1 if result_winner in (1, 2) else -1
    update_bot_ratings(player_1_id, player_2_id, elo_winner)

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE matches SET winner = ?, move_history = ?, status = 'finished'
                WHERE id = ?
            """, (result_winner - 1 if result_winner in (1, 2) else -1,
                  json.dumps(game.move_history), match_id))
            conn.commit()
    except Exception as e:
        print("Failed to update auto match record:", e)
    finally:
        if conn:
            conn.close()

    socketio.emit('match_finished', {
        'match_id': match_id,
        'winner': game.winner,
        'move_history': game.move_history
    }, room=match_id)

    executor_1.cleanup()
    executor_2.cleanup()

def register_gomoku_events(socketio):
    @socketio.on('connect', namespace='/gomoku')
    def handle_connect():
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id}, room=request.sid)
        print(f'new gomoku user connected: {user_id}')

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
            emit('match_status', {
                'match_id': match_id,
                'status': 'playing',
                'board': game.board,
                'game_id': game.game_id,
                'move_history': game.move_history
            }, room=request.sid)
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

        executor_1 = _get_bot_executor(player_1_id) if player_1_type == 'bot' else None
        executor_2 = _get_bot_executor(player_2_id) if player_2_type == 'bot' else None

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

        emit('game_started', {'board': game.board, 'game_id': game.game_id}, room=broadcast_target)


        current_player_type = game.black_player_type if game.current_player == 1 else game.white_player_type
        

        def get_output_1(input: str = None):
            if player_1_type == 'human':
                while 'pending_move' not in sessions[user_id]:
                    if user_id not in sessions or sessions[user_id]['sid'] != sid:
                        break
                    socketio.sleep(0.05)
                return json.dumps(sessions[user_id].pop('pending_move'))
            else:
                return executor_1.run(input)

        def get_output_2(input: str = None):
            if player_2_type == 'human':
                while 'pending_move' not in sessions[user_id]:
                    if user_id not in sessions or sessions[user_id]['sid'] != sid:
                        break
                    socketio.sleep(0.05)
                return json.dumps(sessions[user_id].pop('pending_move'))
            else:
                return executor_2.run(input)


        # main game loop
        try:
            for turn in range(256):
                output_str = ""
                input_str = game.send_action_to_ai()
                if game.current_player == 1:
                    output_str = get_output_1(input_str)
                if game.current_player == 2:
                    output_str = get_output_2(input_str)

                try:
                    move_data = json.loads(output_str)
                    x, y = move_data['x'], move_data['y']
                except (json.JSONDecodeError, KeyError):
                    print(f"AI for player {game.current_player} returned invalid data: {output_str}.")
                    game.winner = 3 - game.current_player
                    emit('update', {'board': game.board, 'winner': game.winner, 'error_msg': 'AI returned invalid move.', 'game_id': game.game_id, 'match_id': match_id}, room=broadcast_target)
                    return
                if game.is_terminated:
                    break


                if not game.apply_move(x, y):
                    game.winner = 3 - game.current_player
                    emit('update', {'board': game.board, 'winner': game.winner, 'error_msg': 'AI made an invalid move.', 'game_id': game.game_id, 'match_id': match_id}, room=broadcast_target)
                    return

                winner = game.check_win(x, y)
                if winner != 0:
                    game.winner = winner

                response = {
                    'board': game.board,
                    'ai_move': {'x': x, 'y': y, 'player': 3 - game.current_player},
                    'winner': game.winner,
                    'game_id': game.game_id,
                    'match_id': match_id
                }
                emit('update', response, room=broadcast_target)
                if game.winner != 0 or game.is_terminated:
                    print(f"Game ended after {turn + 1} turns. Winner: {game.winner}")
                    break
        finally:
            if match_id:
                active_matches.pop(match_id, None)

        # update ratings and save match
        if player_1_type == 'bot' and player_2_type == 'bot':
            update_bot_ratings(player_1_id, player_2_id, game.winner - 1)

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT bot_name FROM bots WHERE id = ?", (player_1_id,))
                row1 = cursor.fetchone()
                username_1 = row1['bot_name'] if row1 else str(player_1_id)
                if player_1_type == 'human':
                    username_1 = '<i>HUMAN</i>'
                cursor.execute("SELECT bot_name FROM bots WHERE id = ?", (player_2_id,))
                row2 = cursor.fetchone()
                username_2 = row2['bot_name'] if row2 else str(player_2_id)
                if player_2_type == 'human':
                    username_2 = '<i>HUMAN</i>'
            players = json.dumps({'player_1': username_1, 'player_2': username_2})

            result_winner = game.winner if game.winner != 0 else -1
            elo_winner = result_winner - 1 if result_winner in (1, 2) else -1

            with conn.cursor() as cursor:
                if match_id:
                    cursor.execute("""
                        UPDATE matches SET players = ?, winner = ?, move_history = ?, status = 'finished'
                        WHERE id = ?
                    """, (players, elo_winner, json.dumps(game.move_history), match_id))
                else:
                    cursor.execute("""
                        INSERT INTO matches (id, game, players, winner, move_history, status)
                        VALUES (?, ?, ?, ?, ?, 'finished')
                    """, (uuid.uuid4().hex, 'Gomoku', players, elo_winner, json.dumps(game.move_history)))
                conn.commit()
        except Exception as e:
            print("Failed to update match record:", e)
        finally:
            if conn:
                conn.close()

        if match_id:
            socketio.emit('match_finished', {
                'match_id': match_id,
                'winner': game.winner,
                'move_history': game.move_history
            }, room=match_id)

                    

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