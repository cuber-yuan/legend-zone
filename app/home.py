from flask import Blueprint, request
from flask_login import current_user
from . import socketio
from judges.gomoku_judge import GomokuJudge
from uuid import uuid4
from flask_socketio import emit, join_room
import os
from .code_executor import CodeExecutor
import uuid
from .db import get_db_connection
from .services.match_listing import format_match, add_match_ratings

home_bp = Blueprint('home', __name__)

sessions = {}

# Tables being set up, keyed by the socket sid that opened one. The homepage
# renders these for everyone else, so a table has to disappear as soon as its
# host closes the tab (disconnect) or the match actually starts.
setup_tables = {}

_SEAT_TYPES = ('bot', 'human')


def _clean_seats(seats):
    """Reduce a client payload to at most two displayable seats.

    The names come from an untrusted socket, so they are length-capped here and
    escaped again on render.
    """
    if not isinstance(seats, list):
        return []
    cleaned = []
    for seat in seats[:2]:
        if not isinstance(seat, dict):
            continue
        name = str(seat.get('name') or '')[:40].strip()
        if not name:
            continue
        kind = seat.get('type') if seat.get('type') in _SEAT_TYPES else 'bot'
        cleaned.append({'type': kind, 'name': name})
    return cleaned


def _table_list():
    return list(setup_tables.values())


def _broadcast_tables():
    socketio.emit('tables_update', {'tables': _table_list()}, namespace='/')


def clear_setup_tables(user_id):
    """Remove every setup table owned by this user, called when their match starts."""
    owned = [sid for sid, table in setup_tables.items() if table.get('user') == user_id]
    for sid in owned:
        del setup_tables[sid]
    if owned:
        _broadcast_tables()


def register_home_events(socketio):
    @socketio.on('connect', namespace='/')
    def handle_connect():
        user_id = str(uuid4())

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, game, players, winner, status, created_at FROM matches WHERE status = 'finished' ORDER BY created_at DESC, id DESC LIMIT 20")
                matches = add_match_ratings(cursor, [format_match(row) for row in cursor.fetchall()])
        except Exception as e:
            print("Failed to fetch matches:", e)
            matches = []
        finally:
            if conn:
                conn.close()
        emit('latest_matches', {"matches": matches})
        # Only the new client needs this snapshot; the others get later diffs.
        emit('tables_update', {'tables': _table_list()})

    @socketio.on('table_open', namespace='/')
    def handle_table_open(data=None):
        if not current_user.is_authenticated:
            return
        game = str((data or {}).get('game') or '')[:40].strip()
        if not game:
            return
        setup_tables[request.sid] = {
            'id': request.sid,
            'game': game,
            'host': current_user.username,
            'user': current_user.id,
            'seats': _clean_seats((data or {}).get('seats')),
        }
        _broadcast_tables()

    @socketio.on('table_update', namespace='/')
    def handle_table_update(data=None):
        table = setup_tables.get(request.sid)
        if not table:
            return
        table['seats'] = _clean_seats((data or {}).get('seats'))
        _broadcast_tables()

    @socketio.on('table_close', namespace='/')
    def handle_table_close(data=None):
        # data is accepted and ignored: flask-socketio passes the client's payload
        # straight through with no arity fallback, so a zero-argument handler
        # raises TypeError that the framework then swallows.
        if setup_tables.pop(request.sid, None) is not None:
            _broadcast_tables()

    @socketio.on('disconnect', namespace='/')
    def handle_disconnect():
        if setup_tables.pop(request.sid, None) is not None:
            _broadcast_tables()
