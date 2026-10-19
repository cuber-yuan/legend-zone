"""Administrator-only pages. Membership does not grant management privileges."""
from functools import wraps

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(view):
    @wraps(view)
    @login_required
    def guarded(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return guarded


@admin_bp.route('/test')
@admin_required
def test_page():
    response = render_template('admin_test.html')
    return response, 200, {'Cache-Control': 'private, no-store', 'Vary': 'Cookie'}
