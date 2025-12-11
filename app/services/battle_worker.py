# app/services/battle_worker.py

import os
import random
import time

import pymysql
from ..gomoku import run_auto_gomoku_match # 导入解耦后的游戏运行函数
from .utils import get_db_connection #, get_bot_executor




# ... (可以为其他游戏导入 run_auto_snake_match 等)

def select_bots_for_game(game_name):
    """
    根据游戏名称，从数据库中选择两名 Bot 进行对战。

    选择逻辑：
    1. 仅选择特定游戏 (game_name) 的 Bot。
    2. 仅选择每个 bot_name 的最新版本 (MAX(id))。
    3. 在满足条件的 Bot 中随机选取两个不同的 Bot ID。

    :param game_name: 游戏的名称 (例如 'Gomoku', 'Snake')
    :return: (player_1_id, player_2_id) 或 (None, None)
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. 查询数据库，获取指定游戏的所有 Bot 的最新 ID
            # 这里的 SQL 逻辑与 main.py 中用于 Bot 列表显示的逻辑相似
            cursor.execute("""
                SELECT id
                FROM bots
                WHERE game = %s
                  AND id IN (
                    SELECT MAX(id) FROM bots WHERE game = %s GROUP BY bot_name
                  )
            """, (game_name, game_name))
            
            # 提取所有 Bot ID
            bot_ids = [row['id'] for row in cursor.fetchall()]

            if len(bot_ids) < 2:
                print(f"Error: Not enough bots available ({len(bot_ids)}) for automated match in {game_name}.")
                return None, None
            
            # 2. 随机选取两个不同的 Bot ID
            # random.sample(population, k) 从序列中随机选取 k 个不重复的元素
            p1_id, p2_id = random.sample(bot_ids, 2)
            
            # 确保返回的 ID 是整数类型 (与数据库和 rating_service.py 保持一致)
            return int(p1_id), int(p2_id)

    except Exception as e:
        print(f"Error during bot selection for {game_name}: {e}")
        return None, None
    finally:
        if conn:
            conn.close()


def schedule_all_games():
    """遍历所有游戏，并安排一场对战，供 APScheduler 调用。"""
    games_to_run = ['Gomoku'] 
    
    for game in games_to_run:
        player_1_id, player_2_id = select_bots_for_game(game)
        p1_id_int = int(player_1_id) 
        p2_id_int = int(player_2_id)
        print(f"Scheduling match for {game} between Bot {player_1_id} and Bot {player_2_id}")
        if player_1_id and player_2_id:
            if game == 'Gomoku':
                run_auto_gomoku_match(p1_id_int, p2_id_int)
            # if game == 'Snake':
            #     run_auto_snake_match(player_1_id, player_2_id)
            
        # 避免瞬间运行太多比赛，可以加入短暂的延迟
        time.sleep(1)

# ... (在主应用启动文件 (app.py 或 __init__.py) 中设置 APScheduler 定期调用 schedule_all_games)