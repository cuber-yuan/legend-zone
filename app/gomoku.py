from flask import Blueprint, request
from . import socketio
from judges.gomoku_judge import GomokuJudge
from uuid import uuid4
from flask_socketio import emit, join_room
import json
from unittest.mock import patch
import os
from .code_executor import CodeExecutor
import uuid
import pymysql
from dotenv import load_dotenv
from .services.rating_service import update_bot_ratings

load_dotenv()

gomoku_bp = Blueprint('gomoku', __name__)

sessions = {} 


def _get_db_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def _get_bot_executor(bot_id):
    if not bot_id:
        return None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT source_code, file_path, language FROM bots WHERE id = %s", (bot_id,))
            result = cursor.fetchone()
        if result:
            return CodeExecutor(code=result['source_code'], language=result['language'], path=result['file_path'])
    finally:
        if conn:
            conn.close()
    return None

## temporary function for running auto gomoku match
def run_auto_gomoku_match(player_1_id, player_2_id):
    """
    Runs a non-interactive (AI vs AI) Gomoku match, updates rating, and logs result.
    This function is designed to be called by a background worker.
    player_1_id (Black), player_2_id (White)
    """
    print(f"Running auto Gomoku match: {player_1_id} (Black) vs {player_2_id} (White)")

    # 1. 初始化执行器
    executor_1 = _get_bot_executor(str(player_1_id))
    executor_2 = _get_bot_executor(str(player_2_id))

    if not executor_1 or not executor_2:
        print("Error: Failed to load both bot executors for auto match.")
        return

    # 2. 运行游戏
    game = GomokuJudge()
    game.game_id = str(uuid.uuid4())
    game.new_game(
        black_player_type='bot',
        white_player_type='bot',
        black_executor=executor_1,
        white_executor=executor_2
    )
    
    # 3. 核心游戏循环 (复制并修改原 new_game 中的循环)
    for turn in range(256):
        output_str = ""
        input_str = game.send_action_to_ai()

        # 根据当前玩家调用对应的 Bot Executor
        if game.current_player == 1:
            output_str = executor_1.run(input_str)
        if game.current_player == 2:
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
        
        if game.winner != 0 or game.is_terminated:
            print(f"Game ended after {turn + 1} turns. Winner: {game.winner}")
            break
    
    # 4. 结果处理
    result_winner = game.winner if game.winner != 0 else -1 # 0: Draw, 1: Black, 2: White
    
    # ELO 更新
    # Gomoku 约定: 1=Black (P1), 2=White (P2). ELO 约定: 0=P1, 1=P2, -1=Draw
    elo_winner = result_winner - 1 if result_winner in (1, 2) else -1
    update_bot_ratings(player_1_id, player_2_id, elo_winner)

    # 比赛记录插入数据库 (使用 get_db_connection 代替)
    # (此处的逻辑与原 gomoku.py 底部类似，但需要使用 get_db_connection)
    # ... (省略数据库插入代码，与原文件逻辑相似，但需使用 get_db_connection)
    
    # 清理 Executor
    if executor_1: executor_1.cleanup()
    if executor_2: executor_2.cleanup()

def register_gomoku_events(socketio):
    @socketio.on('connect', namespace='/gomoku')
    def handle_connect():
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id}, room=request.sid)
        print(f'new gomoku user connected: {user_id}')

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
        sessions[user_id] = {'sid': sid, game.game_id: game}

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

        emit('game_started', {'board': game.board, 'game_id': game.game_id}, room=sid)


        current_player_type = game.black_player_type if game.current_player == 1 else game.white_player_type
        

        def get_output_1(input: str = None):
            if player_1_type == 'human':
                while 'pending_move' not in sessions[user_id]:
                    if user_id not in sessions or sessions[user_id]['sid'] != sid:
                        # print(f"User {user_id} disconnected, terminating game loop.")
                        break
                    socketio.sleep(0.05)
                return json.dumps(sessions[user_id].pop('pending_move'))
            else:
                return executor_1.run(input)

        def get_output_2(input: str = None):
            if player_2_type == 'human':
                while 'pending_move' not in sessions[user_id]:
                    if user_id not in sessions or sessions[user_id]['sid'] != sid:
                        # print(f"User {user_id} disconnected, terminating game loop.")
                        break
                    socketio.sleep(0.05)
                return json.dumps(sessions[user_id].pop('pending_move'))
            else:
                return executor_2.run(input)


        # main game loop
        for turn in range(256):
            output_str = ""
            # print(f"Turn {turn + 1}, current player: {game.current_player}")
            input_str = game.send_action_to_ai()
            # print(f"Input to AI: {input_str}")
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
                emit('update', {'board': game.board, 'winner': game.winner, 'error_msg': 'AI returned invalid move.'}, room=sid)
                return
            if game.is_terminated:
                break


            if not game.apply_move(x, y):
                game.winner = 3 - game.current_player
                emit('update', {'board': game.board, 'winner': game.winner, 'error_msg': 'AI made an invalid move.'}, room=sid)
                return

            winner = game.check_win(x, y)
            if winner != 0:
                game.winner = winner

            response = {
                'board': game.board,
                'ai_move': {'x': x, 'y': y, 'player': 3 - game.current_player},
                'winner': game.winner,
                'game_id': game.game_id
            }
            emit('update', response, room=sid)
            if game.winner != 0 or game.is_terminated:
                print(f"Game ended after {turn + 1} turns. Winner: {game.winner}")
                # update ratings
                if player_1_type == 'bot' and player_2_type == 'bot':
                    update_bot_ratings(player_1_id, player_2_id, game.winner - 1 ) # winner: 0 for P1 win, 1 for P2 win, -1 for draw

                # --- Insert match record into database ---
                try:
                    conn = _get_db_connection()
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
                            'Gomoku',
                            players,
                            winner-1, # TODO set black as 0, white as 1
                            json.dumps(response)
                        ))
                        conn.commit()
                except Exception as e:
                    print("Failed to insert match record:", e)
                finally:
                    if conn:
                        conn.close()
                # --- End DB insert ---
                break

                    

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
                # for key, value in list(session_data.items()):
                #     if isinstance(value, GomokuJudge):
                #         if value.black_executor: value.black_executor.cleanup()
                #         if value.white_executor: value.white_executor.cleanup()
                user_id_to_del = user_id
                break
        
        if user_id_to_del:
            del sessions[user_id_to_del]
            print(f'User {user_id_to_del} disconnected and all sessions cleaned up')