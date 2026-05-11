from flask import Blueprint

bp = Blueprint('lobbies', __name__)

from . import routes  # noqa: E402, F401
