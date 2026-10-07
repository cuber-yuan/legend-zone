from flask_login import UserMixin
from werkzeug.security import generate_password_hash

class User(UserMixin):
    def __init__(self, id, username=None):
        self.id = id
        self.username = username