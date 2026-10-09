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


def _player_entry(payload):
    """Return (name, bot_id, version) from one players-JSON slot.

    Old rows stored a bare string; new rows store {name, bot_id, version}.
    Accept both so pre-versioning matches don't disappear from the homepage.
    """
    if isinstance(payload, str):
        return payload, None, None
    if isinstance(payload, dict):
        return payload.get('name'), payload.get('bot_id'), payload.get('version')
    return None, None, None


def register_home_events(socketio):
    @socketio.on('connect', namespace='/')
    def handle_connect():
        user_id = str(uuid4())

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM matches WHERE status = 'finished' ORDER BY created_at DESC LIMIT 20")
                matches = cursor.fetchall()
                for match in matches:
                    for k, v in match.items():
                        if isinstance(v, datetime.datetime):
                            match[k] = v.strftime('%m-%d %H:%M')

                for match in matches:
                    try:
                        p = json.loads(match['players']) if match['players'] else {}
                    except (json.JSONDecodeError, TypeError):
                        p = {}
                    p1_name, p1_bot, p1_ver = _player_entry(p.get('player_1'))
                    p2_name, p2_bot, p2_ver = _player_entry(p.get('player_2'))
                    match['player_1'] = p1_name
                    match['player_2'] = p2_name
                    match['player_1_id'] = p1_bot
                    match['player_2_id'] = p2_bot
                    match['player_1_version'] = p1_ver
                    match['player_2_version'] = p2_ver
        except Exception as e:
            print("Failed to fetch matches:", e)
            matches = []
        finally:
            if conn:
                conn.close()
        emit('latest_matches', {"matches": matches})
