"""首页和 Bot 详情共用的比赛列表数据。"""
import json
import math


def _rating(value):
    if type(value) not in (int, float):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def format_match(match):
    match = dict(match)
    try:
        players = json.loads(match.get('players') or '{}')
    except (ValueError, TypeError):
        players = {}
    if not isinstance(players, dict):
        players = {}
    for seat in (1, 2):
        key = f'player_{seat}'
        player = players.get(key)
        if isinstance(player, str):
            player = {'name': player}
        if not isinstance(player, dict):
            player = {}
        match[key] = player.get('name')
        match[f'{key}_id'] = player.get('bot_id')
        match[f'{key}_version'] = player.get('version')
        match[f'{key}_is_human'] = player.get('type') == 'human'
        match[f'{key}_rating'] = _rating(player.get('rating_before'))
    return match


def add_match_ratings(cursor, matches):
    """Fill only provable historical ratings; never substitute current ratings."""
    if not matches:
        return matches
    placeholders = ','.join('?' for _ in matches)
    cursor.execute(f"""
        SELECT p.match_id, p.seat, p.bot_id_snapshot, p.version_number_snapshot, previous.rating
        FROM match_players p
        JOIN matches m ON m.id=p.match_id
        JOIN rating_history h ON h.match_id=p.match_id AND h.version_id=p.bot_version_id
        JOIN rating_history previous ON previous.id=(
            SELECT prior.id FROM rating_history prior
            WHERE prior.version_id=h.version_id AND prior.id<h.id ORDER BY prior.id DESC LIMIT 1
        )
        WHERE p.match_id IN ({placeholders}) AND p.player_type='bot'
          AND p.snapshot_source='execution' AND previous.created_at < m.started_at
          AND h.created_at >= m.started_at
    """, tuple(match['id'] for match in matches))
    by_id = {match['id']: match for match in matches}
    for row in cursor.fetchall():
        match = by_id[row['match_id']]
        key = f"player_{row['seat']}"
        if (match.get(f'{key}_rating') is None and not match.get(f'{key}_is_human')
                and match.get(f'{key}_id') == row['bot_id_snapshot']
                and match.get(f'{key}_version') == row['version_number_snapshot']):
            match[f'{key}_rating'] = _rating(row['rating'])
    return matches


def recent_bot_matches(cursor, bot_id, limit=20):
    # Prefer recorded seats; older matches without seats can still carry Bot IDs
    # in players JSON. Never infer identity from a name shared with another Bot.
    cursor.execute("""
        SELECT m.id, m.game, m.players, m.winner, m.status, m.created_at, m.rating_status,
               EXISTS (SELECT 1 FROM match_players human
                       WHERE human.match_id = m.id AND human.player_type = 'human') AS has_human
        FROM matches m
        WHERE m.status = 'finished' AND (
            EXISTS (SELECT 1 FROM match_players p
                    WHERE p.match_id = m.id AND p.bot_id = ?)
            OR (NOT EXISTS (SELECT 1 FROM match_players p WHERE p.match_id = m.id)
                AND (json_extract(CASE WHEN json_valid(m.players) THEN m.players ELSE '{}' END,
                                  '$.player_1.bot_id') = ?
                     OR json_extract(CASE WHEN json_valid(m.players) THEN m.players ELSE '{}' END,
                                     '$.player_2.bot_id') = ?))
        )
        ORDER BY m.created_at DESC, m.id DESC LIMIT ?
    """, (bot_id, bot_id, bot_id, limit))
    matches = add_match_ratings(cursor, [format_match(row) for row in cursor.fetchall()])
    if not matches:
        return matches
    # A version inherits its own baseline. Compare history insertion order within
    # that version, never adjacent matches by creation time or another version.
    placeholders = ','.join('?' for _ in matches)
    cursor.execute(f"""
        SELECT h.match_id, h.rating - (
            SELECT previous.rating FROM rating_history previous
            WHERE previous.version_id = h.version_id AND previous.id < h.id
            ORDER BY previous.id DESC LIMIT 1
        ) AS delta
        FROM rating_history h
        WHERE h.bot_id = ? AND h.match_id IN ({placeholders})
    """, (bot_id, *(match['id'] for match in matches)))
    deltas = {row['match_id']: row['delta'] for row in cursor.fetchall()}
    for match in matches:
        if (match['has_human'] or match['player_1_is_human'] or match['player_2_is_human']
                or match['player_1'] == 'HUMAN' or match['player_2'] == 'HUMAN'):
            match['rating_delta'] = None
        else:
            match['rating_delta'] = (0 if match['rating_status'] == 'skipped'
                                     else deltas.get(match['id']))
    return matches
