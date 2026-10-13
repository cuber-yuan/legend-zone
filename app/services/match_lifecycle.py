"""One exit path for interactive and scheduled matches."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import logging

from .match_service import finalize_match_record
from .rating_service import update_bot_ratings

logger = logging.getLogger(__name__)


class PlayerForfeit(Exception):
    def __init__(self, player, message):
        super().__init__(message)
        self.winner = -1 if player is None else 1 - player


@dataclass
class MatchResult:
    winner: int = -1
    payload: list = field(default_factory=list)
    error_msg: str = None
    rated: bool = True


def read_player_action(get_output, player):
    """Attribute execution and JSON protocol failures to the acting player."""
    try:
        output = get_output()
        if output is None:
            raise ValueError('Opponent left the game.')
        action = json.loads(output)
        if not isinstance(action, dict):
            raise ValueError('Player output must be a JSON object.')
        return action
    except Exception as exc:
        raise PlayerForfeit(player, 'Player failed to return a valid action.') from exc


def read_board_move(get_output, player, column_only=False):
    action = read_player_action(get_output, player)
    keys = ('x',) if column_only else ('x', 'y')
    if any(type(action.get(key)) is not int for key in keys):
        raise PlayerForfeit(player, 'Move coordinates must be integers.')
    return tuple(action[key] for key in keys)


def read_response(get_output, player):
    action = read_player_action(get_output, player)
    if 'response' not in action:
        raise PlayerForfeit(player, 'Player output is missing response.')
    return action


def read_simultaneous_actions(get_outputs):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read_response, get_output, player)
                   for player, get_output in enumerate(get_outputs)]
        # Wait for both so simultaneous failures are treated symmetrically.
        failures = [player for player, future in enumerate(futures)
                    if future.exception() is not None]
        if failures:
            raise PlayerForfeit(failures[0] if len(failures) == 1 else None,
                                'Player failed to return a valid action.')
        return tuple(future.result() for future in futures)


def wait_for_move(sessions, user_id, sid, game, socketio):
    while not game.is_terminated:
        session = sessions.get(user_id)
        if not session or session.get('sid') != sid or session.get(game.game_id) is not game:
            return None
        if 'pending_move' in session:
            return json.dumps(session.pop('pending_move'))
        socketio.sleep(0.05)
    return None


def play_board_game(game, get_outputs, send_update, max_turns, column_only=False):
    """Run turns; execution/protocol/illegal-move failures use one forfeit path."""
    for _ in range(max_turns):
        if game.is_terminated:
            raise RuntimeError('Game was terminated.')
        player = game.current_player - 1
        input_str = game.send_action_to_ai()
        move = read_board_move(lambda: get_outputs[player](input_str), player, column_only)
        if not game.apply_move(*move):
            raise PlayerForfeit(player, 'Player made an invalid move.')
        landed = game.move_history[-1]
        winner = game.check_win(landed['x'], landed['y'])
        if winner:
            game.winner = winner
        send_update({'ai_move': landed})
        if game.winner or game.is_board_full():
            break


@contextmanager
def match_lifecycle(*, match_id, game_name, players, player_ids, player_types,
                    payload_col, socketio, namespace, room, active_matches,
                    executors, board_game=None, notify=None, cleanup=()):
    """Persist before notifying; always release resources, including on early return.

    Bot failures are forfeits. Unexpected server/judge failures close the row
    without moving Elo. Persistence failures propagate instead of announcing
    a result that was never saved.
    """
    result = MatchResult()
    if board_game is not None:
        result.payload = board_game.move_history
    try:
        try:
            yield result
        except PlayerForfeit as exc:
            result.winner = exc.winner
            result.error_msg = str(exc)
        except Exception:
            logger.exception('%s match %s aborted', game_name, match_id)
            result.winner = -1
            result.rated = False
            result.error_msg = 'Match aborted due to a server or judge error.'

        if board_game is not None:
            result.payload = board_game.move_history
            if result.error_msg is None:
                result.winner = board_game.winner - 1 if board_game.winner in (1, 2) else -1
            board_game.winner = result.winner + 1 if result.winner in (0, 1) else 0

        saved_id = finalize_match_record(
            match_id, game_name, players, result.winner,
            json.dumps(result.payload), payload_col,
        )
        if result.rated and player_types == ('bot', 'bot'):
            try:
                update_bot_ratings(*player_ids, result.winner, saved_id)
            except Exception:
                logger.exception('Failed to rate completed match %s', saved_id)

        client_winner = board_game.winner if board_game is not None else result.winner
        event = {'match_id': match_id, 'winner': client_winner, payload_col: result.payload}
        if result.error_msg:
            event['error_msg'] = result.error_msg
        # A failed socket emission must not prevent another notification or cleanup.
        if notify:
            try:
                notify(result)
            except Exception:
                logger.exception('Failed to notify match room %s', room)
        try:
            socketio.emit('match_finished', event, room=room, namespace=namespace)
        except Exception:
            logger.exception('Failed to announce match %s', saved_id)
    finally:
        if match_id:
            active_matches.pop(match_id, None)
        for executor in executors:
            if executor is not None:
                try:
                    executor.cleanup()
                except Exception:
                    logger.exception('Failed to clean up executor for match %s', match_id)
        for release in cleanup:
            try:
                release()
            except Exception:
                logger.exception('Failed to release game resources for match %s', match_id)
