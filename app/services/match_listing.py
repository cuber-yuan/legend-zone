"""首页和 Bot 详情共用的比赛列表数据。"""
import json


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
    return match


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
    matches = [format_match(row) for row in cursor.fetchall()]
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
