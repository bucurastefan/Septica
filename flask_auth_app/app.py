import logging
import os

from flask import Flask
from werkzeug.security import generate_password_hash

from config import config
from extensions import db, login_manager, socketio

logging.basicConfig(level=logging.DEBUG)


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, cors_allowed_origins='*')

    login_manager.login_view = 'auth.login'

    from models import User

    @login_manager.user_loader
    def load_user(user_id):  # noqa: F811 — registered as callback, not called directly
        return User.query.get(int(user_id))

    # Register blueprints
    from auth import bp as auth_bp
    from main import bp as main_bp
    from lobbies import bp as lobbies_bp
    from game import bp as game_bp
    from admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(lobbies_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(admin_bp)

    # Register SocketIO handlers by importing the module
    from game import socket_handlers  # noqa: F401 — imported for handler registration side-effects

    with app.app_context():
        _run_migrations(app)
        db.create_all()
        _ensure_admin_user()

    return app


def _run_migrations(app):
    """Add new columns to an existing database without breaking old installs."""
    import sqlite3
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite:///'):
        return
    db_path = db_uri.replace('sqlite:///', '')
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(user)")
    existing = {row[1] for row in cur.fetchall()}
    new_cols = {
        'is_bot':         'BOOLEAN DEFAULT 0',
        'bot_difficulty': 'TEXT',
    }
    for col, definition in new_cols.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE user ADD COLUMN {col} {definition}")
    conn.commit()
    conn.close()


def _ensure_admin_user():
    from models import User
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@example.com',
            password=generate_password_hash('superboss'),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()
        logging.getLogger(__name__).info("Admin user created")


application = create_app()

if __name__ == '__main__':
    socketio.run(application, host='0.0.0.0', port=5000, debug=True)
