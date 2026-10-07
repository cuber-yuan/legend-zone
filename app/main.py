from flask import Blueprint, render_template, request, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user
import datetime
import uuid
import json
from .db import get_db_connection

main_bp = Blueprint('main', __name__)

messages = []

def clean_expired_messages():
    now = datetime.datetime.now()
    messages[:] = [msg for msg in messages if (now - msg["dt"]).total_seconds() < 86400]

@main_bp.route('/')
def home():
    return render_template('index.html')

@main_bp.route('/games')
def games():
    return render_template('games.html')

@main_bp.route('/profile')
def profile_root():
    if current_user.is_authenticated:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT username FROM users WHERE id = ?", (current_user.id,))
                row = cursor.fetchone()
                if row:
                    return redirect(url_for('main.profile', username=row['username']))
        finally:
            if conn:
                conn.close()
    abort(404)

@main_bp.route('/profile/<username>')
def profile(username):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, created_at FROM users WHERE username = ?", (username,))
            user_row = cursor.fetchone()
            if not user_row:
                return redirect(url_for('main.home'))
            user_id = user_row['id']
            registered_at = user_row.get('created_at')

            cursor.execute("""
                SELECT
                    bot_name AS name,
                    COUNT(*) AS versions,
                    MIN(id) AS id,
                    MAX(description) AS description
                FROM bots
                WHERE user_id = ?
                GROUP BY bot_name
                ORDER BY name
            """, (user_id,))
            bots = cursor.fetchall()
    except Exception:
        bots = []
        registered_at = None
    finally:
        if conn:
            conn.close()

    return render_template('profile.html', bots=bots, user_not_found=False, username=username, registered_at=registered_at)

@main_bp.route('/rating')
def rating():
    conn = None
    ratings = {}
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT game FROM bots ORDER BY game")
            games = [row['game'] for row in cursor.fetchall()]

            for game in games:
                cursor.execute("""
                    SELECT
                        b.id,
                        b.bot_name AS name,
                        b.rating,
                        u.username AS owner
                    FROM bots b
                    JOIN users u ON b.user_id = u.id
                    WHERE b.game = ?
                      AND b.id IN (
                        SELECT MAX(id) FROM bots WHERE game = ? GROUP BY bot_name
                      )
                    ORDER BY b.rating DESC, b.bot_name
                """, (game, game))

                ratings[game] = cursor.fetchall()

    except Exception as e:
        print(f"Database error in /rating: {e}")

    finally:
        if conn:
            conn.close()

    return render_template('rating.html', ratings=ratings)

@main_bp.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify(success=False, error="Login required"), 401 if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('main.chat'))
        message = request.form.get('message')
        if message:
            clean_expired_messages()
            conn = None
            username = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute("SELECT username FROM users WHERE id = ?", (current_user.id,))
                    row = cursor.fetchone()
                    if row:
                        username = row['username']
            finally:
                if conn:
                    conn.close()
            if username:
                msg_obj = {
                    "user": username,
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

def get_latest_bots_for_game(game_name):
    """Get latest record (max id) for each bot_name within a game."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, bot_name
            FROM bots
            WHERE game = ?
              AND id IN (
                SELECT MAX(id) FROM bots WHERE game = ? GROUP BY bot_name
              )
            ORDER BY bot_name
        """, (game_name, game_name))
        return cursor.fetchall()
    finally:
        if conn:
            conn.close()

@main_bp.route('/gomoku')
def gomoku():
    bots = get_latest_bots_for_game('Gomoku')
    return render_template('gomoku.html', bots=bots)

@main_bp.route('/tank')
def tank():
    bots = get_latest_bots_for_game('Tank Battle')
    return render_template('tank.html', bots=bots)

@main_bp.route('/snake')
def snake():
    bots = get_latest_bots_for_game('Snake')
    return render_template('snake.html', bots=bots)

@main_bp.route('/msnake')
def msnake():
    bots = get_latest_bots_for_game('Mini Snake')
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

@main_bp.route('/api/games')
def api_games():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name FROM games ORDER BY name")
            games = cursor.fetchall()
        return jsonify([{'id': g['id'], 'name': g['name']} for g in games])
    except Exception as e:
        print(f"Error fetching games: {e}")
        return jsonify([])
    finally:
        if conn:
            conn.close()

@main_bp.route('/api/bots')
def api_bots():
    game_id = request.args.get('game_id')
    if not game_id:
        return jsonify([])
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Get game name from game_id
            cursor.execute("SELECT name FROM games WHERE id = ?", (game_id,))
            game = cursor.fetchone()
            if not game:
                return jsonify([])
            
            # Get latest bots for this game
            cursor.execute("""
                SELECT id, bot_name AS name
                FROM bots
                WHERE game = ?
                  AND id IN (
                    SELECT MAX(id) FROM bots WHERE game = ? GROUP BY bot_name
                  )
                ORDER BY bot_name
            """, (game['name'], game['name']))
            bots = cursor.fetchall()
        return jsonify([{'id': b['id'], 'name': b['name']} for b in bots])
    except Exception as e:
        print(f"Error fetching bots: {e}")
        return jsonify([])
    finally:
        if conn:
            conn.close()

GAME_TEMPLATES = {
    'Gomoku': 'gomoku.html',
    'Tank Battle': 'tank.html',
    'Snake': 'snake.html',
    'Mini Snake': 'snake.html',
}

@main_bp.route('/api/matches', methods=['POST'])
def api_create_match():
    data = request.get_json()
    game_id = data.get('game_id')
    players = data.get('players', [])

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM games WHERE id = ?", (game_id,))
            game = cursor.fetchone()
            if not game:
                return jsonify({'error': 'Game not found'}), 404

            match_id = uuid.uuid4().hex
            cursor.execute(
                "INSERT INTO matches (id, game, players, status) VALUES (?, ?, ?, ?)",
                (match_id, game['name'], json.dumps(players), 'playing')
            )
            conn.commit()
        return jsonify({'match_id': match_id, 'game_name': game['name']})
    except Exception as e:
        print(f"Error creating match: {e}")
        return jsonify({'error': 'Failed to create match'}), 500
    finally:
        if conn:
            conn.close()

@main_bp.route('/match/<match_id>')
def match_view(match_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, game, players, status, winner, move_history FROM matches WHERE id = ?", (match_id,))
            match = cursor.fetchone()
            if not match:
                abort(404)

            game_name = match['game']
            template = GAME_TEMPLATES.get(game_name)
            if not template:
                abort(404)

            match = dict(match)
            if match.get('move_history'):
                match['move_history'] = json.loads(match['move_history'])

            bots = get_latest_bots_for_game(game_name)
            return render_template(template, bots=bots, match_id=match_id, match=match)
    except Exception as e:
        print(f"Error loading match: {e}")
        abort(500)
    finally:
        if conn:
            conn.close()

@main_bp.route('/api/matches/<match_id>')
def api_get_match(match_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, game, players, status, winner, move_history FROM matches WHERE id = ?", (match_id,))
            match = cursor.fetchone()
            if not match:
                return jsonify({'error': 'Match not found'}), 404
            result = dict(match)
            if result.get('move_history'):
                result['move_history'] = json.loads(result['move_history'])
            return jsonify(result)
    except Exception as e:
        print(f"Error fetching match: {e}")
        return jsonify({'error': 'Failed to fetch match'}), 500
    finally:
        if conn:
            conn.close()

@main_bp.route('/bot/<int:bot_id>')
def bot_detail(bot_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, bot_name AS name, description, user_id, game FROM bots WHERE id = ?", (bot_id,))
            bot = cursor.fetchone()
            if not bot:
                abort(404)
    except Exception:
        abort(500)
    finally:
        if conn:
            conn.close()

    return render_template('bot_detail.html', bot=bot)
