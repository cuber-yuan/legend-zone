from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, username=None, role='user', membership='standard'):
        self.id = id
        self.username = username
        self.role = role
        self.membership = membership

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_vip(self):
        return self.membership == 'vip'
