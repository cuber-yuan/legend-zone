"""Single-process chat persistence, with the same 24-hour retention as the UI."""
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
import time

CHAT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'chat.json'
RETENTION_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)


class ChatStorageError(Exception):
    pass


class ChatStore:
    def __init__(self, path=CHAT_PATH, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = RLock()
        self._loaded = False
        self._messages = []

    def _persist(self, messages):
        temporary = None
        try:
            if not messages:
                self.path.unlink(missing_ok=True)
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                    prefix='.chat-', suffix='.tmp', delete=False) as output:
                temporary = Path(output.name)
                json.dump({'version': 1, 'messages': messages}, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError) as error:
            raise ChatStorageError('Unable to save chat history.') from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning('Unable to remove a temporary chat file.')

    def _retained(self, messages):
        cutoff = self.clock() - RETENTION_SECONDS
        return [message for message in messages if message['created_at'] > cutoff]

    def _load(self):
        if self._loaded:
            return
        try:
            try:
                with self.path.open(encoding='utf-8') as source:
                    document = json.load(source)
            except FileNotFoundError:
                self._messages = []
                self._loaded = True
                return
            if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('messages'), list):
                raise ValueError('Unsupported chat history format.')
            messages = []
            for row in document['messages']:
                if (not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ('user', 'text', 'time'))
                        or type(row.get('created_at')) not in (int, float) or not math.isfinite(row['created_at'])):
                    raise ValueError('Invalid chat history record.')
                messages.append({key: row[key] for key in ('user', 'text', 'time', 'created_at')})
            retained = self._retained(messages)
            if len(retained) != len(messages) or not retained:
                self._persist(retained)
            self._messages = retained
            self._loaded = True
        except (OSError, ValueError, OverflowError) as error:
            # Preserve unreadable/corrupt history rather than overwriting it.
            raise ChatStorageError('Unable to load chat history.') from error

    def _prune(self):
        # A killed process can leave an uncommitted temporary file behind.
        # Its contents expire too; never read them back as accepted messages.
        cutoff = self.clock() - RETENTION_SECONDS
        try:
            leftovers = list(self.path.parent.glob('.chat-*.tmp'))
        except OSError:
            leftovers = []
            logger.warning('Unable to scan temporary chat files.')
        for temporary in leftovers:
            try:
                if temporary.stat().st_mtime <= cutoff:
                    temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning('Unable to remove an expired temporary chat file.')
        self._load()
        retained = self._retained(self._messages)
        if len(retained) != len(self._messages):
            self._persist(retained)
            self._messages = retained

    def prune(self):
        with self._lock:
            self._prune()

    @staticmethod
    def _public(message):
        return {key: message[key] for key in ('user', 'text', 'time')}

    def snapshot(self):
        with self._lock:
            self._prune()
            return [self._public(message) for message in self._messages]

    def add(self, user, text):
        with self._lock:
            self._load()
            now = self.clock()
            message = {'user': user, 'text': text, 'time': datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S'),
                       'created_at': now}
            updated = self._retained(self._messages) + [message]
            self._persist(updated)
            self._messages = updated
            return self._public(message)


chat_store = ChatStore()


def cleanup_chat_history():
    try:
        chat_store.prune()
    except ChatStorageError:
        logger.exception('Chat history cleanup failed; the stored file was preserved.')
