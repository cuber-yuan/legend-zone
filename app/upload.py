from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import os
import secrets
from werkzeug.utils import secure_filename
from .db import get_db_connection

upload_bp = Blueprint('upload', __name__)


UPLOAD_FOLDER = 'uploads/bots'
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1MB max file size
ALLOWED_EXTENSIONS = {'.py', '.zip'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {ext[1:] for ext in ALLOWED_EXTENSIONS}


def validate_file_magic(file_stream):
    """Validate file type by checking magic numbers."""
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


def save_bot_to_db(user_id, bot_name, description, language, source_code=None, file_path=None, game=None):
    conn = None
    try:
        conn = get_db_connection()
        print(f"Saving bot for user_id: {user_id}, bot_name: {bot_name}, game: {game}")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bots (user_id, bot_name, description, language, source_code, file_path, game)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, bot_name, description, language, source_code, file_path, game)
        )
        conn.commit()
    finally:
        if conn:
            conn.close()

@upload_bp.route('/upload-bot', methods=['POST'])
@login_required
def upload_bot():
    if request.content_length > MAX_CONTENT_LENGTH:
        return jsonify({"message": f"File too large. Maximum size is {MAX_CONTENT_LENGTH // (1024*1024)}MB."}), 413
    
    original_bot_name = request.form.get('botName') or 'bot'
    suffix = secrets.token_urlsafe(6)
    bot_name_unique = f"{secure_filename(original_bot_name)}-{suffix}"
    description = request.form.get('botDescription')
    language = request.form.get('language')
    source_code = request.form.get('sourceCode')
    bot_file = request.files.get('botFile')
    game = request.form.get('game')

    if not original_bot_name or len(original_bot_name) < 4:
        return jsonify({"message": "Bot name must be at least 4 characters."}), 400
    if not description or len(description) < 4:
        return jsonify({"message": "Bot description must be at least 4 characters."}), 400
    if not source_code and not bot_file:
        return jsonify({"message": "Please upload a file or enter source code."}), 400

    user_id = current_user.id

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if game:
            cursor.execute(
                "SELECT COUNT(1) as cnt FROM bots WHERE bot_name = ? AND game = ? AND user_id != ?",
                (original_bot_name, game, user_id)
            )
        else:
            cursor.execute(
                "SELECT COUNT(1) as cnt FROM bots WHERE bot_name = ? AND (game IS NULL OR game = '') AND user_id != ?",
                (original_bot_name, user_id)
            )
        exists = cursor.fetchone()['cnt'] > 0
        if exists:
            return jsonify({"message": "Bot name already exists for this game (used by another user)."}), 409
    finally:
        if conn:
            conn.close()

    file_path = None
    if bot_file:
        if not bot_file.filename:
            return jsonify({"message": "No file selected."}), 400
        
        if not allowed_file(bot_file.filename):
            return jsonify({"message": f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
        
        try:
            validate_file_magic(bot_file)
        except ValueError as e:
            return jsonify({"message": str(e)}), 400
        
        user_dir = os.path.join(UPLOAD_FOLDER, str(current_user.id), bot_name_unique)
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, secure_filename(bot_file.filename))
        bot_file.save(file_path)

    save_bot_to_db(
        user_id=user_id,
        bot_name=original_bot_name,
        description=description,
        language=language,
        source_code=source_code if not bot_file else None,
        file_path=file_path,
        game=game,
    )

    return jsonify({"message": "Bot uploaded successfully!"})
