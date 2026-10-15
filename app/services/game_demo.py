"""Select a completed, renderable replay for a game introduction page."""
import json
from ..db import get_db_connection

BOARD_SIZES = {'Gomoku': 15, 'Tic Tac Toe': 3, 'Connect Four': 7}


def _valid_frames(game, frames):
    if not isinstance(frames, list) or not frames or not all(isinstance(f, dict) for f in frames):
        return False
    if game in BOARD_SIZES:
        width, height = BOARD_SIZES[game], 6 if game == 'Connect Four' else BOARD_SIZES[game]
        occupied, heights = set(), [0] * width
        for i, move in enumerate(frames):
            x, y, side = (move.get(k) for k in ('x', 'y', 'player'))
            if any(type(n) is not int for n in (x, y, side)) or not (0 <= x < width and 0 <= y < height):
                return False
            if side != i % 2 + 1 or (x, y) in occupied:
                return False
            if game == 'Connect Four' and y != height - 1 - heights[x]:
                return False
            occupied.add((x, y))
            heights[x] += 1
        return True
    if len(frames) < 2:
        return False
    initial = frames[0]
    if game in ('Snake', 'Mini Snake'):
        if any(type(initial.get(k)) is not int or initial[k] <= 0 for k in ('width', 'height')):
            return False
        points = initial.get('obstacle')
        if not isinstance(points, list):
            return False
        for point in [initial.get('0'), initial.get('1'), *points]:
            if not isinstance(point, dict) or any(type(point.get(k)) is not int for k in ('x', 'y')):
                return False
            if not (1 <= point['x'] <= initial['height'] and 1 <= point['y'] <= initial['width']):
                return False
        return all(all(type(f.get(s)) is int and 0 <= f[s] <= 3 for s in ('0', '1')) for f in frames[1:])
    if game == 'Tank Battle':
        if not all(isinstance(initial.get(k), list) and len(initial[k]) == 3 and
                   all(type(n) is int for n in initial[k]) for k in ('brick', 'water', 'steel')):
            return False
        return all(all(isinstance(f.get(s), list) and len(f[s]) == 2 and
                       all(type(a) is int and -1 <= a <= 7 for a in f[s]) for s in ('0', '1')) for f in frames[1:])
    return False


def get_game_demo(game):
    column = 'move_history' if game in BOARD_SIZES else 'displays'
    with get_db_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f'SELECT winner,{column} AS frames FROM matches '
                       f"WHERE game=? AND status='finished' AND {column} IS NOT NULL "
                       'ORDER BY created_at DESC,id DESC', (game,))
        while (row := cursor.fetchone()) is not None:
            try:
                frames = json.loads(row['frames'])
                if not _valid_frames(game, frames):
                    continue
            except (ValueError, TypeError):
                continue
            winner = row['winner']
            if game in BOARD_SIZES:
                winner = winner + 1 if winner in (0, 1) else 0
            return {'game': game, 'frames': frames, 'winner': winner}
    return None
