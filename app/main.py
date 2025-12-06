from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import login_required, current_user
import pymysql
import os
from dotenv import load_dotenv
import datetime

load_dotenv()

main_bp = Blueprint('main', __name__)

messages = []

def clean_expired_messages():
    now = datetime.datetime.now()
    # Only keep messages within the last 24 hours
    messages[:] = [msg for msg in messages if (now - msg["dt"]).total_seconds() < 86400]

@main_bp.route('/')
def home():
    return render_template('index.html')

@main_bp.route('/games')
def games():
    return render_template('games.html')

@main_bp.route('/profile')
def profile():
    return render_template('profile.html')

@main_bp.route('/rating')
def rating():
    return render_template('rating.html')

@main_bp.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        if not current_user.is_authenticated:
            # Prevent posting if not logged in
            return jsonify(success=False, error="Login required"), 401 if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('main.chat'))
        message = request.form.get('message')
        if message:
            clean_expired_messages()
            msg_obj = {
                "user": current_user.get_id(),
                "text": message,
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "dt": datetime.datetime.now()
            }
            messages.append(msg_obj)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=True, message={
                    "user": msg_obj["user"],
                    "text": msg_obj["text"],
                    "time": msg_obj["time"]
                })
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False)
        return redirect(url_for('main.chat'))
    clean_expired_messages()
    return render_template('chat.html', messages=messages)

@main_bp.route('/chat/messages')
def chat_messages():
    clean_expired_messages()
    return jsonify([
        {
            "user": msg["user"],
            "text": msg["text"],
            "time": msg["time"]
        } for msg in messages
    ])

@main_bp.route('/gomoku')
def gomoku():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT id, bot_name FROM bots where game = 'Gomoku'")
    bots = cursor.fetchall()
    conn.close()

    return render_template('gomoku.html', bots=bots)

@main_bp.route('/tank')
def tank():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT id, bot_name FROM bots where game = 'Tank Battle'")
    bots = cursor.fetchall()
    conn.close()

    return render_template('tank.html', bots=bots)

@main_bp.route('/snake')
def snake():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT id, bot_name FROM bots where game = 'Snake'")
    bots = cursor.fetchall()
    conn.close()
    return render_template('snake.html', bots=bots)

@main_bp.route('/msnake')
def msnake():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT id, bot_name FROM bots where game = 'Mini Snake'")
    bots = cursor.fetchall()
    conn.close()
    return render_template('snake.html', bots=bots)

@main_bp.route('/yahtzee')
def yahtzee():
    return render_template('yahtzee.html')

@main_bp.route('/catking')
def catking():
    return render_template('catking.html')

@main_bp.route('/injoker')
def injoker():
    return render_template('injoker.html')