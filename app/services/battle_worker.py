# app/services/battle_worker.py

import random
import time

from ..gomoku import run_auto_gomoku_match
from ..snake import run_auto_snake_match
from ..tank2 import run_auto_tank_match
from ..tictactoe import run_auto_tictactoe_match
from ..connect4 import run_auto_connect4_match
from .utils import get_db_connection

def select_bots_for_game(game_name):
    """Pick two distinct bots; the runner uses each bot's latest version."""
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


def get_game_bot_counts():
    """Return the number of registered bots in each game pool."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT game, COUNT(*) AS bot_count FROM bots GROUP BY game")
            return {row['game']: row['bot_count'] for row in cursor.fetchall()}
    finally:
        if conn:
            conn.close()


def schedule_all_games():
    """Allocate a fixed match budget across games in proportion to bot counts."""
    games_to_run = ['Gomoku', 'Snake', 'Tank Battle', 'Tic Tac Toe', 'Connect Four']

    auto_match_runners = {
        'Gomoku': run_auto_gomoku_match,
        'Snake': run_auto_snake_match,
        'Tank Battle': run_auto_tank_match,
        'Tic Tac Toe': run_auto_tictactoe_match,
        'Connect Four': run_auto_connect4_match,
    }

    try:
        bot_counts = get_game_bot_counts()
    except Exception as e:
        print(f"Error while counting bots for automated matches: {e}")
        return

    eligible_games = [game for game in games_to_run if bot_counts.get(game, 0) >= 2]
    if not eligible_games:
        return

    # Keep the current per-cycle match budget. With uniform bot selection inside
    # each game, weighting game slots by pool size gives each bot the same
    # expected number of appearances across games.
    selected_games = random.choices(
        eligible_games,
        weights=[bot_counts[game] for game in eligible_games],
        k=len(eligible_games),
    )

    for game in selected_games:
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
