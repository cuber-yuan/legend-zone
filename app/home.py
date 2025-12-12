from flask import Blueprint, request
from . import socketio
from judges.gomoku_judge import GomokuJudge
from uuid import uuid4
from flask_socketio import emit, join_room
import sys
import json
import io
from unittest.mock import patch
import contextlib
import subprocess
import tempfile
import os
from .code_executor import CodeExecutor
import uuid
import pymysql
from dotenv import load_dotenv
import datetime
from app.services.utils import get_db_connection

load_dotenv()

home_bp = Blueprint('home', __name__)

sessions = {} 


def register_home_events(socketio):
    @socketio.on('connect', namespace='/')
    def handle_connect():
        user_id = str(uuid4())
        print(f'new home user connected: {user_id}')

        # Query matches table and send to user
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM matches ORDER BY created_at DESC LIMIT 20")
                matches = cursor.fetchall()
                # Convert datetime fields to string
                for match in matches:
                    for k, v in match.items():
                        if isinstance(v, datetime.datetime):
                            match[k] = v.strftime('%m-%d %H:%M')
        except Exception as e:
            print("Failed to fetch matches:", e)
            matches = []
        finally:
            if conn:
                conn.close()
        # print(matches)
        emit('latest_matches', {"matches": matches})


