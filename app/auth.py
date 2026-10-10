from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from .models import User
from . import login_manager
from .db import get_db_connection
from .services.utils import utc_now_iso

auth_bp = Blueprint('auth', __name__)

def get_user_from_db(username):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row:
            return {'id': row['id'], 'username': row['username'], 'password_hash': row['password_hash']}
        return None
    finally:
        if conn:
            conn.close()

def create_user_in_db(username, password, email):
    password_hash = generate_password_hash(password)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)", (username, password_hash, email, utc_now_iso()))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        if conn:
            conn.close()

@login_manager.user_loader
def load_user(user_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return User(row['id'], row['username'])
        return None
    finally:
        if conn:
            conn.close()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = get_user_from_db(username)
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(user_data['id'], user_data['username'])
            login_user(user)
            return jsonify({"message": "Login successful"})
        else:
            return jsonify({"message": "Invalid credentials"}), 401
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    next_page = request.referrer or url_for('main.home')
    return redirect(next_page)

@auth_bp.route('/protected')
@login_required
def protected():
    return jsonify({"message": f"Hello, {current_user.id}! This is a protected route."})

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        if not username or not password:
            return jsonify({"message": "Username and password required"}), 400
        if get_user_from_db(username):
            return jsonify({"message": "Username already exists"}), 409
        if create_user_in_db(username, password, email):
            return redirect(url_for('main.home'))
        else:
            return jsonify({"message": "Registration failed"}), 500
    return render_template('register.html')