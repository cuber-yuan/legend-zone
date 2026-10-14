"""One exit path for interactive and scheduled matches."""
from contextlib import contextmanager, nullcontext
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import logging

from .match_service import finalize_match_record, create_match_record
from .debug_service import (DebugRecorder, current_recorder, bind_recorder, reset_recorder,
                            trace_fields, trace_failure, trace_callback_output)
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


def read_player_action(get_output, player, input_str=None, validate=None):
    """Capture raw data before parsing; preserve execution errors and invalid JSON."""
    recorder = current_recorder()
    capture = recorder.capture(f'player_{player + 1}', input_str) if recorder else nullcontext()
    with capture:
        try:
            output = get_output()
            # run_process records original bytes first; this also covers Human callbacks.
            trace_callback_output(output)
            if output is None:
                raise ValueError('Opponent left the game.')
            try:
                action = json.loads(output)
                if not isinstance(action, dict):
                    raise ValueError('Player output must be a JSON object.')
                if recorder and player < len(recorder.player_types) and recorder.player_types[player] == 'human':
                    action = {key: action[key] for key in ('x', 'y', 'response') if key in action}
                if validate:
                    validate(action)
            except (ValueError, TypeError) as exc:
                trace_failure('protocol_error', str(exc))
                raise
            return action
        except Exception as exc:
            trace_failure('protocol_error' if isinstance(exc, UnicodeDecodeError) else 'execution_error', str(exc))
            raise PlayerForfeit(player, 'Player failed to return a valid action.') from exc


def read_board_move(get_output, player, column_only=False, input_str=None):
    keys = ('x',) if column_only else ('x', 'y')

    def validate(action):
        if any(type(action.get(key)) is not int for key in keys):
            raise ValueError('Move coordinates must be integers.')

    action = read_player_action(get_output, player, input_str, validate)
    return tuple(action[key] for key in keys)


def read_response(get_output, player, input_str=None):
    def validate(action):
        if 'response' not in action:
            raise ValueError('Player output is missing response.')

    return read_player_action(get_output, player, input_str, validate)


def read_simultaneous_actions(get_outputs, inputs=None):
    recorder = current_recorder()
    if recorder:
        recorder.begin_turn()
    inputs = inputs or (None, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        # ContextVars do not automatically propagate into executor threads.
        futures = [pool.submit(copy_context().run, read_response, get_output, player, inputs[player])
                   for player, get_output in enumerate(get_outputs)]
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
    """Run turns with the same trace format as process-based judges."""
    recorder = current_recorder()
    if recorder:
        with recorder.capture('judge', {'board_size': len(game.board), 'columns': len(game.board[0])}, 'python_judge'):
            trace_fields(stdout={'board': game.board, 'current_player': game.current_player, 'winner': game.winner})
    for _ in range(max_turns):
        if recorder:
            recorder.begin_turn(len(game.move_history) + 1)
        if game.is_terminated:
            raise RuntimeError('Game was terminated.')
        player = game.current_player - 1
        input_str = game.send_action_to_ai()
        move = read_board_move(lambda: get_outputs[player](input_str), player, column_only, input_str)
        context = {'board': game.board, 'player': game.current_player,
                   'action': dict(zip(('x',) if column_only else ('x', 'y'), move))}
        capture = recorder.capture('judge', context, 'python_judge') if recorder else nullcontext()
        with capture:
            if not game.apply_move(*move):
                trace_fields(status='invalid_move', stdout={'accepted': False, 'board': game.board},
                             diagnostic='Player made an invalid move.')
                raise PlayerForfeit(player, 'Player made an invalid move.')
            landed = game.move_history[-1]
            winner = game.check_win(landed['x'], landed['y'])
            if winner:
                game.winner = winner
            trace_fields(stdout={'accepted': True, 'board': game.board, 'current_player': game.current_player,
                                 'winner': game.winner, 'board_full': game.is_board_full()})
        if recorder:
            recorder.complete_frame(len(game.move_history))
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
    recorder = None
    trace_token = None
    result = MatchResult()
    if board_game is not None:
        result.payload = board_game.move_history
    try:
        recording_id = match_id or create_match_record(game_name, players)
        recorder = DebugRecorder(recording_id, executors, player_types)
        trace_token = bind_recorder(recorder)
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
            recording_id, game_name, players, result.winner,
            json.dumps(result.payload), payload_col,
        )
        frame_count = len(result.payload) if payload_col == 'move_history' else max(0, len(result.payload) - 1)
        recorder.finish(frame_count, result.error_msg)
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
        if trace_token is not None:
            reset_recorder(trace_token)
        if recorder is not None and not recorder.finished:
            frame_count = len(result.payload) if payload_col == 'move_history' else max(0, len(result.payload) - 1)
            recorder.finish(frame_count, 'Match completion was interrupted.', interrupted=True)
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
