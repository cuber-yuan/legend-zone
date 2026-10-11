from flask import Blueprint, request, jsonify, render_template, abort
from flask_login import login_required, current_user
import os
import shutil
import time
import uuid
import zipfile
from werkzeug.utils import secure_filename
from .db import get_db_connection
from .services.utils import utc_now_iso
from .services.rating_service import record_history

upload_bp = Blueprint('upload', __name__)


UPLOAD_ROOT = 'uploads/bots'
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1MB max file size
ALLOWED_EXTENSIONS = {'.py', '.cpp', '.cc', '.zip'}
LANGUAGE_TO_ENTRY = {'python3': 'main.py', 'cpp': 'main.cpp'}
EXTENSION_TO_LANGUAGE = {'.py': 'python3', '.cpp': 'cpp', '.cc': 'cpp'}
os.makedirs(UPLOAD_ROOT, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {ext[1:] for ext in ALLOWED_EXTENSIONS}


def _infer_language(bot_file, form_language):
    """File extension wins over the form's language selector.

    The upload form defaults to Python, so users who forget to switch to C++
    otherwise lock their bot to the wrong language forever.
    """
    if not bot_file or not bot_file.filename:
        return form_language
    lower = bot_file.filename.lower()
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if lower.endswith(ext):
            return lang
    return form_language


def validate_file_magic(file_stream):
    header = file_stream.read(8)
    file_stream.seek(0)
    if not header:
        raise ValueError("Empty file")
    if header.startswith(b'MZ'):
        raise ValueError("Windows executable files are not allowed")
    if header.startswith(b'\x7fELF'):
        raise ValueError("Linux executable files are not allowed")
    if header.startswith(b'#!'):
        raise ValueError("Script files with shebang are not allowed")
    return True


def _version_dir(user_id, bot_id, version_number):
    return os.path.join(UPLOAD_ROOT, str(user_id), str(bot_id), f"v{version_number}")


def _safe_extract_zip(zip_ref, extract_dir):
    extract_dir = os.path.realpath(extract_dir)
    for member in zip_ref.namelist():
        member_path = os.path.realpath(os.path.join(extract_dir, member))
        if not member_path.startswith(extract_dir):
            raise ValueError(f"Zip Slip attack detected: {member}")
    zip_ref.extractall(extract_dir)


def _store_version_files(version_dir, language, source_code, bot_file):
    """Populate the version directory with either the uploaded file or the pasted source.

    For single-file uploads (py/cpp) we rewrite the file to a canonical entry
    name so the executor can find it without parsing user-supplied filenames.
    For zip uploads we extract verbatim — the archive is expected to carry its
    own entry file (e.g. __main__.py).
    """
    os.makedirs(version_dir, exist_ok=True)
    if bot_file:
        filename = bot_file.filename.lower()
        if filename.endswith('.zip'):
            zip_path = os.path.join(version_dir, secure_filename(bot_file.filename))
            bot_file.save(zip_path)
            extract_dir = os.path.join(version_dir, 'src')
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                _safe_extract_zip(zf, extract_dir)
            os.remove(zip_path)
            return os.path.join(extract_dir).replace('\\', '/')
        entry_name = LANGUAGE_TO_ENTRY[language]
        bot_file.save(os.path.join(version_dir, entry_name))
    elif source_code:
        entry_name = LANGUAGE_TO_ENTRY[language]
        with open(os.path.join(version_dir, entry_name), 'w', encoding='utf-8') as f:
            f.write(source_code)
    return version_dir.replace('\\', '/')


def _next_version_number(cursor, bot_id):
    cursor.execute("SELECT COALESCE(MAX(version_number), 0) AS v FROM bot_versions WHERE bot_id = ?", (bot_id,))
    return cursor.fetchone()['v'] + 1


def _previous_rating(cursor, bot_id, prev_version_number):
    if prev_version_number <= 0:
        return 1500
    cursor.execute(
        "SELECT rating FROM bot_versions WHERE bot_id = ? AND version_number = ?",
        (bot_id, prev_version_number)
    )
    row = cursor.fetchone()
    return row['rating'] if row and row['rating'] is not None else 1500


def _validate_payload(language, description, source_code, bot_file):
    if not description or len(description) < 4:
        return "Bot description must be at least 4 characters."
    if not source_code and not bot_file:
        return "Please upload a file or enter source code."
    if bot_file and bot_file.filename:
        if not allowed_file(bot_file.filename):
            return f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        try:
            validate_file_magic(bot_file)
        except ValueError as e:
            return str(e)
    if language not in LANGUAGE_TO_ENTRY:
        return f"Unsupported language: {language}"
    return None


@upload_bp.route('/upload-bot', methods=['POST'])
@login_required
def upload_bot():
    if request.content_length and request.content_length > MAX_CONTENT_LENGTH:
        return jsonify({"message": f"File too large. Maximum size is {MAX_CONTENT_LENGTH // (1024*1024)}MB."}), 413

    bot_name = (request.form.get('botName') or '').strip()
    description = request.form.get('botDescription')
    language = _infer_language(request.files.get('botFile'), request.form.get('language'))
    source_code = request.form.get('sourceCode')
    bot_file = request.files.get('botFile')
    game = request.form.get('game')

    if not bot_name or len(bot_name) < 4:
        return jsonify({"message": "Bot name must be at least 4 characters."}), 400

    err = _validate_payload(language, description, source_code, bot_file)
    if err:
        return jsonify({"message": err}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id FROM bots WHERE bot_name = ? AND game = ?",
            (bot_name, game)
        )
        existing = cursor.fetchone()
        if existing:
            if existing['user_id'] == current_user.id:
                return jsonify({"message": "Bot already exists. Use New Version to update it."}), 409
            return jsonify({"message": "Bot name already taken by another user for this game."}), 409

        now = utc_now_iso()
        bot_id = uuid.uuid4().hex
        # Explicitly private: the column default is 0 only so that pre-existing
        # bots stay public when the ALTER adds it to an old database.
        cursor.execute(
            "INSERT INTO bots (id, user_id, bot_name, game, language, is_private, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (bot_id, current_user.id, bot_name, game, language, now)
        )

        version_dir = _version_dir(current_user.id, bot_id, 1)
        file_path = _store_version_files(version_dir, language, source_code, bot_file)

        cursor.execute(
            """
            INSERT INTO bot_versions (bot_id, version_number, description, source_code, file_path, rating, created_at)
            VALUES (?, 1, ?, ?, ?, 1500, ?)
            """,
            (bot_id, description, source_code if not bot_file else None, file_path, now)
        )
        # Baseline point so the rating chart starts at the bot's birth instead
        # of its first finished match.
        record_history(cursor, bot_id, cursor.lastrowid, None, 1500)
        conn.commit()
    except Exception as e:
        print("Failed to create bot:", e)
        if conn:
            conn.rollback()
        return jsonify({"message": "Failed to create bot."}), 500
    finally:
        if conn:
            conn.close()

    return jsonify({"message": "Bot uploaded successfully!", "bot_id": bot_id})


@upload_bp.route('/bots/<string:bot_id>/new-version')
@login_required
def new_version_page(bot_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT b.id, b.bot_name, b.game, b.language, b.user_id,
                   (SELECT MAX(version_number) FROM bot_versions WHERE bot_id = b.id) AS latest_version
            FROM bots b WHERE b.id = ?
            """,
            (bot_id,)
        )
        bot = cursor.fetchone()
    finally:
        if conn:
            conn.close()

    if not bot:
        abort(404)
    if bot['user_id'] != current_user.id:
        abort(403)

    return render_template('new_version.html', bot=bot)


@upload_bp.route('/bots/<string:bot_id>/versions', methods=['POST'])
@login_required
def add_version(bot_id):
    if request.content_length and request.content_length > MAX_CONTENT_LENGTH:
        return jsonify({"message": f"File too large. Maximum size is {MAX_CONTENT_LENGTH // (1024*1024)}MB."}), 413

    description = request.form.get('botDescription')
    source_code = request.form.get('sourceCode')
    bot_file = request.files.get('botFile')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, language FROM bots WHERE id = ?", (bot_id,))
        bot = cursor.fetchone()
        if not bot:
            return jsonify({"message": "Bot not found."}), 404
        if bot['user_id'] != current_user.id:
            return jsonify({"message": "Not your bot."}), 403

        language = bot['language']
        inferred = _infer_language(bot_file, language)
        if bot_file and bot_file.filename and not bot_file.filename.lower().endswith('.zip') and inferred != language:
            return jsonify({"message": f"File extension ({inferred}) does not match bot language ({language}). Language is locked once v1 exists."}), 400

        err = _validate_payload(language, description, source_code, bot_file)
        if err:
            return jsonify({"message": err}), 400

        next_v = _next_version_number(cursor, bot_id)
        prev_rating = _previous_rating(cursor, bot_id, next_v - 1)

        version_dir = _version_dir(bot['user_id'], bot_id, next_v)
        file_path = _store_version_files(version_dir, language, source_code, bot_file)

        cursor.execute(
            """
            INSERT INTO bot_versions (bot_id, version_number, description, source_code, file_path, rating, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (bot_id, next_v, description, source_code if not bot_file else None, file_path, prev_rating, utc_now_iso())
        )
        record_history(cursor, bot_id, cursor.lastrowid, None, prev_rating)
        conn.commit()
    except Exception as e:
        print("Failed to add version:", e)
        if conn:
            conn.rollback()
        return jsonify({"message": "Failed to add version."}), 500
    finally:
        if conn:
            conn.close()

    return jsonify({"message": "Version added!", "version_number": next_v})


def _remove_bot_directory(user_id, bot_id):
    """Delete a bot's upload tree, reporting whether it really went away.

    ignore_errors=True used to swallow failures here while the DB rows had
    already been committed, silently stranding a directory nothing pointed at
    any more. The path is logged server-side only — never returned to the
    client, since it reveals the server's layout.
    """
    bot_dir = os.path.join(UPLOAD_ROOT, str(user_id), str(bot_id))
    for attempt in range(2):
        try:
            shutil.rmtree(bot_dir)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            if attempt == 0:
                # A ladder match may still hold this directory as its cwd.
                time.sleep(0.5)
                continue
            print("Bot rows deleted but directory survived %s: %s" % (bot_dir, exc))
            return False


def sweep_orphan_bot_dirs():
    """Reclaim upload directories whose bot row no longer exists.

    Startup-only: at request time this could race with an upload that has
    written its files but not yet inserted the row. This is also the only
    recovery path for a directory orphaned by a crash between the DB commit
    and the rmtree in delete_bot.
    """
    if not os.path.isdir(UPLOAD_ROOT):
        return

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id FROM bots")
        rows = cursor.fetchall()
    except Exception as exc:
        print("Skipped orphan bot sweep:", exc)
        return
    finally:
        if conn:
            conn.close()

    # A row with no id means the insert never completed (bot ids are generated
    # in upload_bot before the INSERT, so a NULL means schema or code drift).
    # Deleting on that reading would wipe live bots, so refuse outright.
    alive = set()
    for row in rows:
        uid, bid = row['user_id'], row['id']
        if uid is None or bid is None or str(bid).strip() == '':
            print("Skipped orphan bot sweep: a bots row has a null id — "
                  "schema drift, refusing to delete anything.")
            return
        alive.add((str(uid), str(bid)))

    # An empty result means something is wrong with the database, not that
    # every bot is gone — refuse to delete anything on that reading.
    if not alive:
        print("Skipped orphan bot sweep: database reports no bots.")
        return

    removed = 0
    for user_id in os.listdir(UPLOAD_ROOT):
        user_dir = os.path.join(UPLOAD_ROOT, user_id)
        if not os.path.isdir(user_dir):
            continue
        if not user_id.isdigit():
            continue
        for bot_id in os.listdir(user_dir):
            # Bot ids are uuid4().hex: exactly 32 lowercase hex characters.
            # Anything shorter or looser (a 'cafe' folder, a stray file) is not
            # ours to delete, so match the real shape rather than a hex-ish guess.
            if len(bot_id) != 32 or any(c not in '0123456789abcdef' for c in bot_id):
                continue
            orphan = os.path.join(user_dir, bot_id)
            if not os.path.isdir(orphan):
                continue
            if (user_id, bot_id) in alive:
                continue
            try:
                shutil.rmtree(orphan)
                removed += 1
                print("Removed orphan bot directory:", orphan.replace('\\', '/'))
            except OSError as exc:
                print("Could not remove orphan bot directory %s: %s" % (orphan, exc))
    if removed:
        print("Orphan bot sweep reclaimed %d director%s" % (removed, 'y' if removed == 1 else 'ies'))


@upload_bp.route('/bots/<string:bot_id>/delete', methods=['POST'])
@login_required
def delete_bot(bot_id):
    """Permanently remove a bot, all its versions, and its uploaded files.

    The caller must echo the literal string DELETE in the request body — a
    second line of defence behind the frontend's type-to-confirm modal.
    """
    payload = request.get_json(silent=True) or {}
    if payload.get('confirm') != 'DELETE':
        return jsonify({"message": "Confirmation failed. Type DELETE to confirm."}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id FROM bots WHERE id = ?", (bot_id,))
        bot = cursor.fetchone()
        if not bot:
            return jsonify({"message": "Bot not found."}), 404
        if bot['user_id'] != current_user.id:
            return jsonify({"message": "Not your bot."}), 403

        # SQLite foreign keys are off by default, so cascade explicitly.
        cursor.execute("DELETE FROM rating_history WHERE bot_id = ?", (bot_id,))
        cursor.execute("DELETE FROM bot_versions WHERE bot_id = ?", (bot_id,))
        cursor.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        conn.commit()
    except Exception as e:
        print("Failed to delete bot:", e)
        if conn:
            conn.rollback()
        return jsonify({"message": "Failed to delete bot."}), 500
    finally:
        if conn:
            conn.close()

    removed = _remove_bot_directory(current_user.id, bot_id)
    if not removed:
        return jsonify({
            "message": "Bot deleted, but its uploaded files are still on disk and "
                       "will be reclaimed on the next server restart.",
            "files_remaining": True,
        })

    return jsonify({"message": "Bot deleted."})


@upload_bp.route('/bots/<string:bot_id>/visibility', methods=['POST'])
@login_required
def set_visibility(bot_id):
    """Flip whether this bot's source is visible to other users.

    The bot itself stays public — it appears in rankings and match listings, and
    only its source code is gated. Note this governs the webpage alone: another
    user's running bot can still read files off disk until the execution
    sandbox is tightened.
    """
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload.get('is_private'), bool):
        return jsonify({"message": "is_private must be a boolean."}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id FROM bots WHERE id = ?", (bot_id,))
        bot = cursor.fetchone()
        if not bot:
            return jsonify({"message": "Bot not found."}), 404
        if bot['user_id'] != current_user.id:
            return jsonify({"message": "Not your bot."}), 403

        cursor.execute("UPDATE bots SET is_private = ? WHERE id = ?",
                       (1 if payload['is_private'] else 0, bot_id))
        conn.commit()
    except Exception as e:
        print("Failed to update bot visibility:", e)
        if conn:
            conn.rollback()
        return jsonify({"message": "Failed to update visibility."}), 500
    finally:
        if conn:
            conn.close()

    return jsonify({"message": "Visibility updated.", "is_private": payload['is_private']})
