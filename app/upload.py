from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import os
import pymysql
from dotenv import load_dotenv
import secrets
from werkzeug.utils import secure_filename

load_dotenv()

upload_bp = Blueprint('upload', __name__)


UPLOAD_FOLDER = 'uploads/bots'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_user_id_by_username(username):
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def save_bot_to_db(user_id, bot_name, description, language, source_code=None, file_path=None, game=None):
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    print(f"Saving bot for user_id: {user_id}, bot_name: {bot_name}, game: {game}")
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO bots (user_id, bot_name, description, language, source_code, file_path, game)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, bot_name, description, language, source_code, file_path, game)
    )
    conn.commit()
    conn.close()

@upload_bp.route('/upload-bot', methods=['POST'])
@login_required
def upload_bot():
    # preserve original name but generate a unique bot_name to avoid duplicates on filesystem
    original_bot_name = request.form.get('botName') or 'bot'
    # use a short secure random suffix for storage folder only
    suffix = secrets.token_urlsafe(6)
    bot_name_unique = f"{secure_filename(original_bot_name)}-{suffix}"
    description = request.form.get('botDescription')
    language = request.form.get('language')
    source_code = request.form.get('sourceCode')
    bot_file = request.files.get('botFile')
    game = request.form.get('game')

    # validate input
    if not original_bot_name or len(original_bot_name) < 4:
        return jsonify({"message": "Bot name must be at least 4 characters."}), 400
    if not description or len(description) < 4:
        return jsonify({"message": "Bot description must be at least 4 characters."}), 400
    if not source_code and not bot_file:
        return jsonify({"message": "Please upload a file or enter source code."}), 400

    # lookup user id
    user_id = get_user_id_by_username(current_user.id)
    if not user_id:
        return jsonify({"message": "User not found."}), 404

    # check duplicate bot name for this game; if exists, reject upload
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    try:
        cursor = conn.cursor()
        # If game provided, ensure bot_name is unique within that game across different users.
        # Allow same user to upload same bot_name (versions).
        if game:
            cursor.execute(
                "SELECT COUNT(1) FROM bots WHERE bot_name = %s AND game = %s AND user_id != %s",
                (original_bot_name, game, user_id)
            )
        else:
            # If no game specified, treat NULL/empty as the same category.
            cursor.execute(
                "SELECT COUNT(1) FROM bots WHERE bot_name = %s AND (game IS NULL OR game = '') AND user_id != %s",
                (original_bot_name, user_id)
            )
        exists = cursor.fetchone()[0] > 0
        if exists:
            return jsonify({"message": "Bot name already exists for this game (used by another user)."}), 409
    finally:
        conn.close()

    # save file or source code
    file_path = None
    if bot_file:
        # build storage path: uploads/bots/<user_id>/<unique_folder>/
        user_dir = os.path.join(UPLOAD_FOLDER, str(current_user.id), bot_name_unique)
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, secure_filename(bot_file.filename))
        bot_file.save(file_path)

    # save to database using the original bot name (not the storage suffix)
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