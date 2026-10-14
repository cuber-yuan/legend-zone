"""Bounded, public, persistent execution traces. Never reinterpret replay data as logs."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import subprocess
import threading
import time

from ..db import get_db_connection
from .utils import utc_now_iso

logger = logging.getLogger(__name__)
FIELD_LIMIT = 64 * 1024
MATCH_LIMIT = 16 * 1024 * 1024
_recorder = ContextVar('match_debug_recorder', default=None)
_event = ContextVar('match_debug_event', default=None)


def current_recorder():
    return _recorder.get()


def current_event_status():
    event = _event.get()
    return event['status'] if event else None


def bind_recorder(recorder):
    return _recorder.set(recorder)


def reset_recorder(token):
    _recorder.reset(token)


def clipped(value, limit=FIELD_LIMIT):
    if value is None:
        return '', False
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    elif not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    raw = value.encode('utf-8', 'replace')
    return raw[:limit].decode('utf-8', 'ignore'), len(raw) > limit


def trace_fields(**values):
    event = _event.get()
    if event is None:
        return
    for key, value in values.items():
        if key in ('input', 'stdout', 'stderr', 'diagnostic'):
            event[key], cut = clipped(value)
            if cut and key not in event['truncated_fields']:
                event['truncated_fields'].append(key)
        else:
            event[key] = value


def trace_failure(status, message):
    event = _event.get()
    if event is not None:
        if event['status'] in ('pending', 'success'):
            trace_fields(status=status)
        if not event['diagnostic']:
            trace_fields(diagnostic=str(message))


def trace_callback_output(value):
    event = _event.get()
    if event is not None and event['status'] == 'pending':
        if event['kind'] == 'human' and value is not None:
            # Socket payloads also contain routing/session identifiers, not game I/O.
            action = json.loads(value)
            value = {key: action[key] for key in ('x', 'y', 'response') if key in action}
        trace_fields(stdout=value)


def run_process(*args, **kwargs):
    """Preserve subprocess semantics, including raw output attached to exceptions."""
    start = time.perf_counter()
    try:
        result = subprocess.run(*args, **kwargs)
    except subprocess.TimeoutExpired as exc:
        trace_fields(stdout=exc.stdout, stderr=exc.stderr, exit_code=None,
                     status='timeout', diagnostic='Execution exceeded its time limit.')
        raise
    except subprocess.CalledProcessError as exc:
        trace_fields(stdout=exc.stdout, stderr=exc.stderr, exit_code=exc.returncode,
                     status='runtime_error', diagnostic='Process exited with a non-zero code.')
        raise
    except Exception:
        trace_failure('execution_error', 'Unable to start the process.')
        raise
    else:
        trace_fields(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode,
                     status='success' if result.returncode == 0 else 'runtime_error')
        return result
    finally:
        trace_fields(duration_ms=round((time.perf_counter() - start) * 1000, 3))


class DebugRecorder:
    def __init__(self, match_id, executors=(), player_types=()):
        self.match_id = match_id
        self.executors = executors
        self.player_types = player_types
        self.turn = 0
        self.frame = 0
        self.sequence = 0
        self.bytes_used = 0
        self.truncated = False
        self.incomplete = False
        self.finished = False
        self._lock = threading.Lock()
        self.enabled = self._write('INSERT INTO match_debug_sessions (match_id, created_at) VALUES (?, ?)',
                                   (match_id, utc_now_iso()))

    def _write(self, sql, params, extra=()):
        connection = None
        try:
            connection = get_db_connection()
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                for extra_sql, extra_params in extra:
                    cursor.execute(extra_sql, extra_params)
            connection.commit()
            return True
        except Exception:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    logger.exception('Failed to roll back the debug transaction')
            self.incomplete = True
            logger.exception('Failed to persist a debug record for match %s', self.match_id)
            return False
        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    self.incomplete = True
                    logger.exception('Failed to close the debug database connection')

    def begin_turn(self, turn=None):
        self.turn = self.turn + 1 if turn is None else turn

    def complete_frame(self, frame=None):
        self.frame = self.turn if frame is None else frame

    @contextmanager
    def capture(self, actor, input_value, kind='process'):
        with self._lock:
            self.sequence += 1
            sequence = self.sequence
            turn = self.turn
        event = {'actor': actor, 'kind': kind, 'status': 'pending', 'input': '',
                 'stdout': '', 'stderr': '', 'diagnostic': '', 'duration_ms': None,
                 'exit_code': None, 'truncated_fields': []}
        if actor.startswith('player_'):
            seat = int(actor[-1]) - 1
            executor = self.executors[seat] if seat < len(self.executors) else None
            event['kind'] = self.player_types[seat] if seat < len(self.player_types) else 'bot'
            event['bot_id'] = getattr(executor, 'bot_id', None)
            event['bot_version_id'] = getattr(executor, 'version_id', None)
        token = _event.set(event)
        start = time.perf_counter()
        try:
            trace_fields(input=input_value)
            yield event
        except Exception:
            trace_failure('execution_error', 'Execution did not complete.')
            raise
        finally:
            if event['status'] == 'pending':
                event['status'] = 'success'
            if event['duration_ms'] is None:
                event['duration_ms'] = round((time.perf_counter() - start) * 1000, 3)
            _event.reset(token)
            self._store(sequence, turn, event)

    def _store(self, sequence, turn, event):
        with self._lock:
            if not self.enabled:
                return
            raw = json.dumps(event, ensure_ascii=False)
            size = len(raw.encode('utf-8'))
            if self.bytes_used + size > MATCH_LIMIT:
                # Preserve the event/status for every turn even after the data budget is exhausted.
                for field in ('input', 'stdout', 'stderr', 'diagnostic'):
                    if event[field] and field not in event['truncated_fields']:
                        event['truncated_fields'].append(field)
                    event[field] = ''
                event['limit_reached'] = True
                raw = json.dumps(event, ensure_ascii=False)
                self.truncated = True
            else:
                self.bytes_used += size
            self.truncated = self.truncated or bool(event['truncated_fields'])
            update = ('UPDATE match_debug_sessions SET last_turn=?, frame_count=?, truncated=?, incomplete=?, '
                      'event_count=event_count+1, stored_bytes=stored_bytes+? WHERE match_id=?',
                      (self.turn, self.frame, int(self.truncated), int(self.incomplete), len(raw.encode('utf-8')), self.match_id))
            self._write('INSERT INTO match_debug_events (match_id, sequence, turn_index, actor, status, payload) '
                        'VALUES (?, ?, ?, ?, ?, ?)',
                        (self.match_id, sequence, turn, event['actor'], event['status'], raw), extra=(update,))

    def finish(self, frame_count, error=None, interrupted=False):
        self.frame = max(0, frame_count)
        if not self.enabled:
            self.finished = True
            return
        self._write('UPDATE match_debug_sessions SET status = ?, last_turn = ?, frame_count = ?, '
                    'truncated = ?, incomplete = ?, error = ?, finished_at = ? WHERE match_id = ?',
                    ('interrupted' if interrupted else 'complete', self.turn, self.frame,
                     int(self.truncated), int(self.incomplete or interrupted), clipped(error, 4096)[0] or None,
                     utc_now_iso(), self.match_id))
        self.finished = True
