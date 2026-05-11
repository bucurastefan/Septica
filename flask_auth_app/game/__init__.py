from flask import Blueprint

bp = Blueprint('game', __name__)

from . import routes  # noqa: E402, F401
