import logging
import os

from flask import Flask, request
from werkzeug.security import generate_password_hash

from config import config
from extensions import db, login_manager, socketio

logging.basicConfig(level=logging.DEBUG)


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    cfg = config[config_name]
    app.config.from_object(cfg)

    # Explicitly read SECRET_KEY from environment at runtime so it always
    # reflects the current process environment, regardless of class-level evaluation order.
    if os.environ.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = os.environ['SECRET_KEY']

    # Run any class-level init validation (raises in production if SECRET_KEY missing)
    if hasattr(cfg, 'init_app'):
        cfg.init_app(app)

    db.init_app(app)
    login_manager.init_app(app)

    # In production restrict SocketIO to the app's own origin
    allowed_origins = os.environ.get('CORS_ORIGIN', '*')
    socketio.init_app(app, cors_allowed_origins=allowed_origins)

    login_manager.login_view = 'auth.login'

    from models import User

    @login_manager.user_loader
    def load_user(user_id):  # noqa: F811
        return User.query.get(int(user_id))

    # ── Security headers on every response ──────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Only add HSTS on HTTPS responses in production
        if not app.debug and request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

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

    # Register SocketIO handlers
    from game import socket_handlers  # noqa: F401

    # Set up Flask-Migrate
    from flask_migrate import Migrate
    Migrate(app, db)

    with app.app_context():
        # Ensure data directory exists (used by production SQLite path)
        _ensure_data_dir(app)
        # create_all is a safe no-op when tables already exist;
        # for schema migrations use: flask db upgrade
        db.create_all()
        _ensure_admin_user()

    return app


def _ensure_data_dir(app):
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if uri.startswith('sqlite:///'):
        db_path = uri[len('sqlite:///'):]
        data_dir = os.path.dirname(db_path)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)


def _ensure_admin_user():
    from models import User
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@example.com',
            password=generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'superboss')),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()
        logging.getLogger(__name__).info("Admin user created")


application = create_app()

if __name__ == '__main__':
    socketio.run(application, host='0.0.0.0', port=5000, debug=True)
