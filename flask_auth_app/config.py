import os

basedir = os.path.abspath(os.path.dirname(__file__))


def _resolve_db_uri(default_path):
    uri = os.environ.get('DATABASE_URL', f'sqlite:///{default_path}')
    # Heroku/Render export 'postgres://' but SQLAlchemy 1.4+ requires 'postgresql://'
    if uri.startswith('postgres://'):
        uri = 'postgresql://' + uri[len('postgres://'):]
    return uri


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Session cookies: never accessible from JS, same-site to mitigate CSRF
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


class DevelopmentConfig(Config):
    DEBUG = True
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-key-do-not-use-in-production')
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = _resolve_db_uri(os.path.join(basedir, 'users.db'))


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True  # only send cookie over HTTPS
    SQLALCHEMY_DATABASE_URI = _resolve_db_uri(os.path.join(basedir, 'data', 'septica.db'))

    @classmethod
    def init_app(cls, app):
        if not os.environ.get('SECRET_KEY'):
            raise RuntimeError(
                'SECRET_KEY environment variable is not set. '
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
