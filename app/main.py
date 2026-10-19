from flask import Blueprint, render_template, request, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user
import datetime
import uuid
import json
from .db import get_db_connection
from .services.bot_service import player_json_for_human
from .services.utils import utc_now_iso
from .home import clear_setup_tables
from .services.match_listing import recent_bot_matches

main_bp = Blueprint('main', __name__)

# Cap the rating chart so a long-lived bot does not render a thousand points.
RATING_HISTORY_LIMIT = 20

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
    is_owner = False
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, created_at FROM users WHERE username = ?", (username,))
            user_row = cursor.fetchone()
            if not user_row:
                return redirect(url_for('main.home'))
            user_id = user_row['id']
            registered_at = user_row.get('created_at')
            is_owner = bool(current_user.is_authenticated and current_user.id == user_id)

            cursor.execute("""
                SELECT
                    b.id,
                    b.bot_name AS name,
                    b.game,
                    b.language,
                    lv.version_number AS latest_version,
                    lv.rating         AS latest_rating,
                    lv.description    AS latest_description,
                    (SELECT COUNT(*) FROM bot_versions WHERE bot_id = b.id) AS versions
                FROM bots b
                LEFT JOIN bot_versions lv
                       ON lv.bot_id = b.id
                      AND lv.version_number = (SELECT MAX(version_number) FROM bot_versions WHERE bot_id = b.id)
                WHERE b.user_id = ?
                ORDER BY b.bot_name
            """, (user_id,))
            bots = cursor.fetchall()
    except Exception:
        bots = []
        registered_at = None
    finally:
        if conn:
            conn.close()

    return render_template('profile.html', bots=bots, user_not_found=False, username=username, registered_at=registered_at, is_owner=is_owner)

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
                        lv.version_number AS version,
                        lv.rating,
                        u.username AS owner
                    FROM bots b
                    JOIN bot_versions lv
                      ON lv.bot_id = b.id
                     AND lv.version_number = (SELECT MAX(version_number) FROM bot_versions WHERE bot_id = b.id)
                    JOIN users u ON b.user_id = u.id
                    WHERE b.game = ?
                    ORDER BY lv.rating DESC, b.bot_name
                """, (game,))

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
    """Return one row per logical bot for the game; versions are collapsed at
    the DB layer so callers don't need the old MAX(id)-per-name hack."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, bot_name
            FROM bots
            WHERE game = ?
            ORDER BY bot_name
        """, (game_name,))
        return cursor.fetchall()
    finally:
        if conn:
            conn.close()

@main_bp.route('/gomoku')
def gomoku():
    return render_game_intro('Gomoku', 'gomoku.html')

@main_bp.route('/tank')
def tank():
    return render_game_intro('Tank Battle', 'tank.html')

@main_bp.route('/snake')
def snake():
    return render_game_intro('Snake', 'snake.html')

@main_bp.route('/tictactoe')
def tictactoe():
    return render_game_intro('Tic Tac Toe', 'tictactoe.html')

@main_bp.route('/connect4')
def connect4():
    return render_game_intro('Connect Four', 'connect4.html')

@main_bp.route('/msnake')
def msnake():
    return render_game_intro('Mini Snake', 'snake.html')


def render_game_intro(game, template):
    from .services.game_demo import get_game_demo
    demo = get_game_demo(game)
    return render_template(template, bots=[], demo=demo, match=demo)

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
            
            # Public version metadata only; never expose source or file paths.
            cursor.execute("""
                SELECT id, bot_name AS name
                FROM bots
                WHERE game = ?
                ORDER BY bot_name
            """, (game['name'],))
            bots = cursor.fetchall()
            cursor.execute('SELECT v.bot_id, v.version_number FROM bot_versions v '
                           'JOIN bots b ON b.id=v.bot_id WHERE b.game=? '
                           'ORDER BY v.version_number DESC', (game['name'],))
            versions = {}
            for version in cursor.fetchall():
                versions.setdefault(version['bot_id'], []).append(version['version_number'])
        return jsonify([{'id': b['id'], 'name': b['name'], 'versions': versions.get(b['id'], [])}
                        for b in bots])
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
    'Tic Tac Toe': 'tictactoe.html',
    'Connect Four': 'connect4.html',
}

@main_bp.route('/api/matches', methods=['POST'])
@login_required
def api_create_match():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Expected a JSON object'}), 400
    game_id = data.get('game_id')
    players = data.get('players', [])
    if not isinstance(players, list) or len(players) != 2:
        return jsonify({'error': 'Exactly two players are required'}), 400

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM games WHERE id = ?", (game_id,))
            game = cursor.fetchone()
            if not game:
                return jsonify({'error': 'Game not found'}), 404

        players_map = {}
        for idx, player in enumerate(players, start=1):
            if not isinstance(player, dict) or player.get('type') not in ('bot', 'human'):
                return jsonify({'error': 'Invalid player type'}), 400
            if player['type'] == 'bot':
                version = player.get('version')
                if version is not None and (type(version) is not int or version < 1):
                    return jsonify({'error': 'Invalid bot version'}), 400
                with conn.cursor() as cursor:
                    cursor.execute('SELECT b.bot_name, v.version_number, '
                                   '(SELECT MAX(version_number) FROM bot_versions WHERE bot_id=b.id) AS latest '
                                   'FROM bots b JOIN bot_versions v ON v.bot_id=b.id '
                                   'WHERE b.id=? AND b.game=? AND (? IS NULL OR v.version_number=?) '
                                   'ORDER BY v.version_number DESC LIMIT 1',
                                   (player.get('botId'), game['name'], version, version))
                    selected = cursor.fetchone()
                if not selected:
                    return jsonify({'error': 'Bot or version not found for this game'}), 400
                players_map[f"player_{idx}"] = {
                    'name': selected['bot_name'], 'bot_id': player['botId'],
                    'version': selected['version_number'],
                    'rating_eligible': selected['version_number'] == selected['latest'],
                }
            else:
                # A human seat is the signed-in user; the client shows it read-only,
                # so derive it here instead of trusting whatever was posted.
                players_map[f"player_{idx}"] = player_json_for_human(current_user.username)

        match_id = uuid.uuid4().hex
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO matches (id, game, players, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (match_id, game['name'], json.dumps(players_map), 'playing', utc_now_iso())
            )
            conn.commit()
        # The match now exists, so this host's setup table is no longer a table
        # being set up. Cleared server-side because the browser redirects away.
        clear_setup_tables(current_user.id)
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
            cursor.execute("SELECT id, game, players, status, winner, move_history, displays FROM matches WHERE id = ?", (match_id,))
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
            if match.get('displays'):
                match['displays'] = json.loads(match['displays'])
            if match.get('players'):
                match['players'] = json.loads(match['players'])

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
            cursor.execute("SELECT id, game, players, status, winner, move_history, displays FROM matches WHERE id = ?", (match_id,))
            match = cursor.fetchone()
            if not match:
                return jsonify({'error': 'Match not found'}), 404
            result = dict(match)
            if result.get('move_history'):
                result['move_history'] = json.loads(result['move_history'])
            if result.get('displays'):
                result['displays'] = json.loads(result['displays'])
            return jsonify(result)
    except Exception as e:
        print(f"Error fetching match: {e}")
        return jsonify({'error': 'Failed to fetch match'}), 500
    finally:
        if conn:
            conn.close()

@main_bp.route('/api/matches/<match_id>/debug')
def match_debug(match_id):
    """Public debug snapshot, with optional bulk events for local replay caching."""
    include_all = request.args.get('all') == '1'
    raw_turn = request.args.get('turn')
    if ('all' in request.args and not include_all) or (include_all and raw_turn is not None):
        return jsonify({'error': 'Use all=1 or turn=N, not both.'}), 400
    turn = None
    if raw_turn is not None:
        try:
            turn = int(raw_turn)
            if turn < 0 or turn > 100000:
                raise ValueError()
        except (TypeError, ValueError):
            return jsonify({'error': 'turn must be a non-negative integer.'}), 400
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT status FROM matches WHERE id = ?', (match_id,))
            match = cursor.fetchone()
            if not match:
                return jsonify({'error': 'Match not found.'}), 404
            cursor.execute('SELECT * FROM match_debug_sessions WHERE match_id = ?', (match_id,))
            session = cursor.fetchone()
            if not session:
                return jsonify({'available': False, 'events': [], 'turns': []})
            if turn is not None:
                cursor.execute('SELECT sequence, turn_index, payload FROM match_debug_events '
                               'WHERE match_id = ? AND turn_index = ? ORDER BY sequence LIMIT 100',
                               (match_id, turn))
                events = []
                for row in cursor.fetchall():
                    event = json.loads(row['payload'])
                    event.update(sequence=row['sequence'], turn=row['turn_index'])
                    events.append(event)
                return jsonify({'available': True, 'turn': turn, 'events': events})
            cursor.execute("SELECT turn_index, COUNT(*) AS event_count, "
                           "MAX(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS has_error "
                           'FROM match_debug_events WHERE match_id = ? GROUP BY turn_index ORDER BY turn_index',
                           (match_id,))
            turns = [{'turn': row['turn_index'], 'event_count': row['event_count'],
                      'has_error': bool(row['has_error'])} for row in cursor.fetchall()]
            result = {
                'available': True, 'schema_version': session['schema_version'],
                'status': session['status'], 'frame_count': session['frame_count'],
                'last_turn': session['last_turn'], 'turns': turns,
                'truncated': bool(session['truncated']), 'incomplete': bool(session['incomplete']),
                'error': session['error'],
                'failure_turn': session['last_turn'] if session['last_turn'] > session['frame_count']
                or (session['last_turn'] == 0 and session['error']) else None,
            }
            if include_all:
                cursor.execute('SELECT sequence, turn_index, payload FROM match_debug_events '
                               'WHERE match_id = ? ORDER BY sequence', (match_id,))
                result['events'] = []
                for row in cursor.fetchall():
                    event = json.loads(row['payload'])
                    event.update(sequence=row['sequence'], turn=row['turn_index'])
                    result['events'].append(event)
            response = jsonify(result)
            response.headers['Cache-Control'] = 'no-store'
            return response
    finally:
        connection.close()


@main_bp.route('/bot/<string:bot_id>')
def bot_detail(bot_id):
    conn = None
    bot = None
    versions = []
    history = []
    history_total = 0
    recent_matches = []
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    b.id,
                    b.bot_name AS name,
                    b.game,
                    b.language,
                    b.created_at,
                    b.user_id,
                    b.is_private,
                    u.username AS owner
                FROM bots b
                LEFT JOIN users u ON b.user_id = u.id
                WHERE b.id = ?
            """, (bot_id,))
            bot = cursor.fetchone()

            if bot:
                recent_matches = recent_bot_matches(cursor, bot_id)
                cursor.execute("""
                    SELECT id, version_number, description, source_code, file_path, rating, created_at
                    FROM bot_versions
                    WHERE bot_id = ?
                    ORDER BY version_number DESC
                """, (bot_id,))
                versions = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) AS n FROM rating_history WHERE bot_id = ?", (bot_id,))
                history_total = cursor.fetchone()['n']
                # Newest N points, then re-sorted oldest-first so the line still
                # reads left to right.
                cursor.execute("""
                    SELECT version_number, match_id, rating, created_at FROM (
                        SELECT bv.version_number, rh.match_id, rh.rating, rh.created_at, rh.id
                        FROM rating_history rh
                        JOIN bot_versions bv ON bv.id = rh.version_id
                        WHERE rh.bot_id = ?
                        ORDER BY rh.created_at DESC, rh.id DESC
                        LIMIT ?
                    )
                    ORDER BY created_at ASC, id ASC
                """, (bot_id, RATING_HISTORY_LIMIT))
                history = cursor.fetchall()
                if versions:
                    latest = versions[0]
                    bot = dict(bot)
                    bot['latest_version'] = latest['version_number']
                    bot['rating'] = latest['rating']
                    bot['description'] = latest['description']
                    bot['is_owner'] = bool(
                        current_user.is_authenticated and current_user.id == bot['user_id'])
                    # Gate here rather than in the markup, so a hidden source never
                    # enters the template context for a stranger to find.
                    if bot['is_owner'] or not bot['is_private']:
                        bot['source_code'] = latest['source_code']
                    # Expose only whether files exist — the absolute workdir would
                    # leak the server's directory layout to any visitor.
                    bot['has_files'] = bool(latest['file_path'])
                    bot['can_download'] = bool(
                        (bot['is_owner'] or not bot['is_private'])
                        and (latest['source_code'] is not None or latest['file_path']))
                # Version rows need metadata only, including for private Bots.
                versions = [{key: value for key, value in version.items()
                             if key not in ('source_code', 'file_path')} for version in versions]
    except Exception as e:
        print(f"Error loading bot {bot_id}: {e}")
        abort(500)
    finally:
        if conn:
            conn.close()

    if not bot:
        abort(404)

    return render_template('bot_detail.html', bot=bot, versions=versions, history=history,
                           history_total=history_total, history_limit=RATING_HISTORY_LIMIT,
                           recent_matches=recent_matches)
