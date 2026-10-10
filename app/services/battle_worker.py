# app/services/battle_worker.py

import random
import time

from ..gomoku import run_auto_gomoku_match
from ..snake import run_auto_snake_match
from ..tank2 import run_auto_tank_match
from ..tictactoe import run_auto_tictactoe_match
from .utils import get_db_connection




# ... (可以为其他游戏导入 run_auto_snake_match 等)

def select_bots_for_game(game_name):
    """Pick two distinct bots for an auto match.

    Version selection happens inside the runners (each bot plays with its
    latest bot_versions row), so here we only need logical bot IDs.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM bots WHERE game = ?", (game_name,))
            bot_ids = [row['id'] for row in cursor.fetchall()]

            if len(bot_ids) < 2:
                print(f"Error: Not enough bots available ({len(bot_ids)}) for automated match in {game_name}.")
                return None, None

            p1_id, p2_id = random.sample(bot_ids, 2)
            return p1_id, p2_id

    except Exception as e:
        print(f"Error during bot selection for {game_name}: {e}")
        return None, None
    finally:
        if conn:
            conn.close()


def schedule_all_games():
    """遍历所有游戏，并安排一场对战，供 APScheduler 调用。"""
    games_to_run = ['Gomoku', 'Snake', 'Tank Battle', 'Tic Tac Toe']

    auto_match_runners = {
        'Gomoku': run_auto_gomoku_match,
        'Snake': run_auto_snake_match,
        'Tank Battle': run_auto_tank_match,
        'Tic Tac Toe': run_auto_tictactoe_match,
    }

    for game in games_to_run:
        player_1_id, player_2_id = select_bots_for_game(game)
        if player_1_id is None or player_2_id is None:
            continue
        print(f"Scheduling match for {game} between Bot {player_1_id} and Bot {player_2_id}")
        runner = auto_match_runners.get(game)
        if runner is None:
            print(f"No auto-match runner registered for {game}, skipping.")
            continue
        runner(player_1_id, player_2_id)

        time.sleep(1)

# ... (在主应用启动文件 (app.py 或 __init__.py) 中设置 APScheduler 定期调用 schedule_all_games)