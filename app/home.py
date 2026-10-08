from flask import Blueprint, request
from . import socketio
from judges.gomoku_judge import GomokuJudge
from uuid import uuid4
from flask_socketio import emit, join_room
import json
import os
from .code_executor import CodeExecutor
import uuid
import datetime
from .db import get_db_connection

home_bp = Blueprint('home', __name__)

sessions = {} 


def register_home_events(socketio):
    @socketio.on('connect', namespace='/')
    def handle_connect():
        user_id = str(uuid4())

        # Query matches table and send to user
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM matches WHERE status = 'finished' ORDER BY created_at DESC LIMIT 20")
                matches = cursor.fetchall()
                # Convert datetime fields to string
                for match in matches:
                    for k, v in match.items():
                        if isinstance(v, datetime.datetime):
                            match[k] = v.strftime('%m-%d %H:%M')

                # 收集所有玩家名，批量查每个 name 对应的最新 bot id
                # （players JSON 字段里只存了名字，没存 id）
                all_names = set()
                for match in matches:
                    try:
                        p = json.loads(match['players']) if match['players'] else {}
                    except (json.JSONDecodeError, TypeError):
                        p = {}
                    for name in p.values():
                        if isinstance(name, str):
                            all_names.add(name)

                name_to_id = {}
                if all_names:
                    placeholders = ','.join('?' * len(all_names))
                    params = list(all_names)
                    # 拿每个 bot_name 的最新版本 id
                    cursor.execute(f"""
                        SELECT bot_name, id FROM bots
                        WHERE bot_name IN ({placeholders})
                          AND id IN (SELECT MAX(id) FROM bots WHERE bot_name IN ({placeholders}) GROUP BY bot_name)
                    """, params + params)
                    for row in cursor.fetchall():
                        name_to_id[row['bot_name']] = row['id']

                # 把 id 挂到每场 match 上（前端用它把名片渲染成指向 /bot/<id> 的链接）
                for match in matches:
                    try:
                        p = json.loads(match['players']) if match['players'] else {}
                    except (json.JSONDecodeError, TypeError):
                        p = {}
                    match['player_1_id'] = name_to_id.get(p.get('player_1'))
                    match['player_2_id'] = name_to_id.get(p.get('player_2'))
        except Exception as e:
            print("Failed to fetch matches:", e)
            matches = []
        finally:
            if conn:
                conn.close()
        # print(matches)
        emit('latest_matches', {"matches": matches})


