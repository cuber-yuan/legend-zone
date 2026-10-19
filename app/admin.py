"""Administrator-only pages. Membership does not grant management privileges."""
from functools import wraps
import sqlite3

from flask import Blueprint, abort, render_template, jsonify, request
from flask_login import current_user, login_required
from .services import database_browser

admin_bp = Blueprint('admin', __name__)


def admin_required(view):
    @wraps(view)
    @login_required
    def guarded(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return guarded


@admin_bp.route('/admin')
@admin_required
def test_page():
    response = render_template('admin_test.html')
    return response, 200, {'Cache-Control': 'private, no-store', 'Vary': 'Cookie'}


@admin_bp.after_request
def prevent_admin_caching(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.vary.add('Cookie')
    return response


@admin_bp.route('/admin/database/tables')
@admin_required
def database_tables():
    try:
        return jsonify(tables=database_browser.list_tables())
    except sqlite3.Error:
        return jsonify(error='Database unavailable. Please try again.'), 503


@admin_bp.route('/admin/database/table')
@admin_required
def database_table():
    try:
        name = request.args.get('name', '')
        if not name:
            raise ValueError('Select a table.')
        page = int(request.args.get('page', '1'))
        page_size = int(request.args.get('page_size', '25'))
        return jsonify(database_browser.read_table(name, page, page_size))
    except ValueError:
        return jsonify(error='Invalid table or pagination parameters.'), 400
    except LookupError:
        return jsonify(error='Table not found.'), 404
    except sqlite3.Error:
        return jsonify(error='Unable to read this table. Please try again.'), 503
