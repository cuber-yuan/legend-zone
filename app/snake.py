import json
import os
import pymysql
from uuid import uuid4
import concurrent.futures

from flask import Blueprint, request
from flask_socketio import emit, join_room

from .code_executor import CodeExecutor
from .cpp_judge_executor import CppJudgeExecutor

snake_bp = Blueprint('snake', __name__)
sessions = {}  # { user_id: { 'sid': ..., 'game': ... } }

# --- ELO Rating Constants ---
K_FACTOR = 32
DEFAULT_RATING = 1500

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

def _calculate_new_ratings(rating_1, rating_2, winner):
    """
    Calculates the new ELO ratings for two bots based on the game result.
    winner: 0 for P1 win, 1 for P2 win, -1 for draw.
    """
    R_A = rating_1
    R_B = rating_2

    # Calculate Expected Scores
    E_A = 1 / (1 + 10**((R_B - R_A) / 400))
    E_B = 1 / (1 + 10**((R_A - R_B) / 400))

    # Determine Actual Scores (S)
    if winner == 0:  # Player 1 (A) wins
        S_A, S_B = 1, 0
    elif winner == 1:  # Player 2 (B) wins
        S_A, S_B = 0, 1
    else:  # Draw or error (-1)
        S_A, S_B = 0.5, 0.5

    # Calculate New Ratings
    R_A_new = R_A + K_FACTOR * (S_A - E_A)
    R_B_new = R_B + K_FACTOR * (S_B - E_B)

    return R_A_new, R_B_new

def _update_bot_ratings(player_1_id, player_2_id, winner):
    """
    Fetches current ratings, calculates new ratings, and updates the database.
    Only runs if both IDs are valid (i.e., not human players).
    """
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            # 1. Fetch current ratings
            # Use DEFAULT_RATING if the rating column is NULL
            cursor.execute("SELECT id, COALESCE(rating, %s) AS rating FROM bots WHERE id IN (%s, %s)", 
                           (DEFAULT_RATING, player_1_id, player_2_id))
            bots_data = {row['id']: row['rating'] for row in cursor.fetchall()}

            rating_1 = bots_data.get(player_1_id)
            rating_2 = bots_data.get(player_2_id)

            if rating_1 is None or rating_2 is None:
                print("Error: Could not retrieve ratings for both bots.")
                return

            # 2. Calculate new ratings
            R_1_new, R_2_new = _calculate_new_ratings(rating_1, rating_2, winner)

            # 3. Update ratings in the database
            cursor.execute("UPDATE bots SET rating = %s WHERE id = %s", (R_1_new, player_1_id))
            cursor.execute("UPDATE bots SET rating = %s WHERE id = %s", (R_2_new, player_2_id))
            conn.commit()
            print(f"Ratings updated. P1({player_1_id}): {rating_1:.2f} -> {R_1_new:.2f}, P2({player_2_id}): {rating_2:.2f} -> {R_2_new:.2f}")

    except Exception as e:
        print("Failed to update bot ratings:", e)
    finally:
        if conn:
            conn.close()


class SnakeGameSession:
    def __init__(self, cpp_path, bot_1_code=None, bot_2_code=None):
        self.game_id = str(uuid4())
        self.cpp_judge = CppJudgeExecutor(cpp_path)
        self.bot_1 = CodeExecutor(code=bot_1_code) if bot_1_code else None
        self.bot_2 = CodeExecutor(code=bot_2_code) if bot_2_code else None
        self.bot_1_type = 'bot' if bot_1_code else 'human'
        self.bot_2_type = 'bot' if bot_2_code else 'human'

    def terminate(self):
        if self.bot_1: self.bot_1.cleanup()
        if self.bot_2: self.bot_2.cleanup()


def register_snake_events(socketio):
    @socketio.on('connect', namespace='/snake')
    def handle_connect():
        user_id = str(uuid4())
        sessions[user_id] = {'sid': request.sid}
        join_room(request.sid)
        emit('init', {'user_id': user_id})
        
    @socketio.on('new_game', namespace='/snake')
    def new_game(data):
        user_id = data['user_id']
        if user_id in sessions:
            sessions[user_id]['terminated'] = True
        bot_1_code = data.get('bot_1_code')
        bot_2_code = data.get('bot_2_code')
        cpp_path = os.path.join(os.path.dirname(__file__), '../judges/snake_judge.exe')
        page_path = data.get('page_path', '')
        if '/msnake' in page_path:
            print("successfully change judge.")
            cpp_path = os.path.join(os.path.dirname(__file__), '../judges/msnake_judge.exe')
        game = SnakeGameSession(cpp_path, bot_1_code, bot_2_code)
        sessions[user_id] = {'sid': request.sid, 'game': game}

        # Get player selections from the frontend.
        player_1_id_str = data.get('left_player_id')
        player_2_id_str = data.get('right_player_id')

        player_1_type = 'human' if data.get('left_is_human') else 'bot'
        player_2_type = 'human' if data.get('right_is_human') else 'bot'
        
        # Determine if it's a bot vs bot match for rating updates
        is_bot_match = (player_1_type == 'bot' and player_2_type == 'bot')
        
        # Convert IDs to int only if they are bots and exist
        player_1_id_int = int(player_1_id_str) if player_1_type == 'bot' and player_1_id_str else None
        player_2_id_int = int(player_2_id_str) if player_2_type == 'bot' and player_2_id_str else None


        print(f"Starting game {game.game_id} with players: {player_1_id_str} ({player_1_type}) vs {player_2_id_str} ({player_2_type})")


        executor_1 = _get_bot_executor(player_1_id_str) if player_1_type == 'bot' else None
        executor_2 = _get_bot_executor(player_2_id_str) if player_2_type == 'bot' else None

        game_state_dict = game.cpp_judge.run_raw_json({});
        # fuck zhouhy, the judge have bugs
        # game_state_dict['display']['width'] , game_state_dict['display']['height'] = game_state_dict['display']['height'], game_state_dict['display']['width']

        maxTurn = 200
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
            if user_id not in sessions or sessions[user_id]['sid'] != sid:
                print(f"User {user_id} disconnected, terminating game loop.")
                break
            
            input_str_1 = json.dumps(input_dict_1)
            input_str_2 = json.dumps(input_dict_2)
            # print(f"========== Turn {turn + 1} Input ==========\n {input_str_1}\n {input_str_2}")
            def get_output_1():
                if player_1_type == 'human':
                    while 'pending_move' not in sessions[user_id]:
                        if user_id not in sessions or sessions[user_id]['sid'] != sid:
                            # print(f"User {user_id} disconnected, terminating game loop.")
                            break
                        socketio.sleep(0.05)
                    return json.dumps(sessions[user_id].pop('pending_move'))
                else:
                    return executor_1.run(input_str_1)

            def get_output_2():
                if player_2_type == 'human':
                    while 'pending_move' not in sessions[user_id]:
                        if user_id not in sessions or sessions[user_id]['sid'] != sid:
                            # print(f"User {user_id} disconnected, terminating game loop.")
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

            # print(f"========== Turn {turn + 1} Output ==========\n {output_1}\n {output_2}")
            
            judge_input_dict['log'].append({}) # leave odd items empty
            judge_input_dict['log'].append({"0": json.loads(output_1), "1": json.loads(output_2)})
            game_state_dict = game.cpp_judge.run_raw_json(judge_input_dict)
            displays.append(game_state_dict['display'])
            response = {
                'state': game_state_dict['display'],
                'game_id': game.game_id
            }
            
            # if sessions[user_id].get('terminated'):
            #     print(f"User {user_id} started a new game, terminating previous game loop.")
            #     break
            # print('this send to frontend', game_state_dict['display'])
            emit('update', response, room=sid)

            if game_state_dict['command'] == 'finish':
                print(game_state_dict)
                if 'winner' in game_state_dict.get('display', {}):
                    # winner: 0 for P1, 1 for P2, -1 for Draw
                    winner = game_state_dict['display']['winner']
                else:
                    winner = -1

                emit('finish', {"winner": winner, 'game_id': game.game_id}, room=sid)
                
                # --- UPDATE BOT RATING IF BOT VS BOT ---
                if is_bot_match and player_1_id_int and player_2_id_int:
                    _update_bot_ratings(player_1_id_int, player_2_id_int, winner)
                else:
                    print("Skipping rating update: Not a bot vs bot match.")
                # --- END RATING UPDATE ---
                
                
                # --- Insert match record into database ---
                conn = None
                try:
                    conn = _get_db_connection()
                    with conn.cursor() as cursor:
                        
                        # Get Bot Name or label as HUMAN
                        p1_id_for_db = player_1_id_str if player_1_type == 'bot' else None
                        p2_id_for_db = player_2_id_str if player_2_type == 'bot' else None

                        username_1 = '<i>HUMAN</i>'
                        if p1_id_for_db:
                            cursor.execute("SELECT bot_name FROM bots WHERE id = %s", (p1_id_for_db,))
                            row1 = cursor.fetchone()
                            if row1:
                                username_1 = row1['bot_name']

                        username_2 = '<i>HUMAN</i>'
                        if p2_id_for_db:
                            cursor.execute("SELECT bot_name FROM bots WHERE id = %s", (p2_id_for_db,))
                            row2 = cursor.fetchone()
                            if row2:
                                username_2 = row2['bot_name']
                                
                    players = json.dumps({'player_1': username_1, 'player_2': username_2})
                    with conn.cursor() as cursor:
                        sql = """
                            INSERT INTO matches (game, players, winner, displays)
                            VALUES (%s, %s, %s, %s)
                        """
                        cursor.execute(sql, (
                            'Snake',
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
            input_dict_1['requests'].append(json.loads(output_2)['response'])
            input_dict_1['responses'].append(json.loads(output_1)['response'])
            input_dict_2['requests'].append(json.loads(output_1)['response'])
            input_dict_2['responses'].append(json.loads(output_2)['response'])

            

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
        # print(f"User {user_id} made a move: {move}")