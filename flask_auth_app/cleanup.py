"""
Background cleanup worker.

Runs every 30 minutes and deletes:
  - Orphaned bot users (is_bot=True, not in any lobby)
  - Guest users (email @temporary.invalid) older than 24 hours
  - Lobbies with game_started=True for more than 1 hour (stuck game)
  - Any lobby older than 2 hours (abandoned)
"""

import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_INTERVAL = 30 * 60   # 30 minutes between runs
_INITIAL_DELAY = 60   # 1 minute after startup before first run


def start_cleanup_worker(app):
    t = threading.Thread(target=_loop, args=(app,), daemon=True)
    t.start()
    logger.info("Cleanup worker started")


def _loop(app):
    time.sleep(_INITIAL_DELAY)
    while True:
        try:
            with app.app_context():
                n_bots, n_guests, n_lobbies = _run()
                if n_bots or n_guests or n_lobbies:
                    logger.info(
                        f"Cleanup: removed {n_bots} orphaned bot(s), "
                        f"{n_guests} stale guest(s), {n_lobbies} stale lobby/ies"
                    )
        except Exception as e:
            logger.error(f"Cleanup error: {e}", exc_info=True)
        time.sleep(_INTERVAL)


def _run():
    from extensions import db
    from models import User, Lobby, LobbyPlayer, PlayerStats, GameResultParticipant

    now = datetime.utcnow()

    # ── Orphaned bots (is_bot=True, not in any lobby) ────────────────────────
    orphan_bot_ids = [
        r[0] for r in (
            db.session.query(User.id)
            .filter(User.is_bot == True)
            .outerjoin(LobbyPlayer, LobbyPlayer.user_id == User.id)
            .filter(LobbyPlayer.id.is_(None))
        )
    ]
    n_bots = 0
    if orphan_bot_ids:
        # Bots have no PlayerStats or GameResultParticipant rows.
        # Defensively handle any lobby they might own.
        bot_owned = [r[0] for r in db.session.query(Lobby.id)
                     .filter(Lobby.owner_id.in_(orphan_bot_ids))]
        if bot_owned:
            LobbyPlayer.query.filter(LobbyPlayer.lobby_id.in_(bot_owned)).delete(synchronize_session=False)
            Lobby.query.filter(Lobby.id.in_(bot_owned)).delete(synchronize_session=False)
        n_bots = User.query.filter(User.id.in_(orphan_bot_ids)).delete(synchronize_session=False)

    # ── Guest users older than 24 hours ─────────────────────────────────────
    n_guests = 0
    cutoff_guest = now - timedelta(hours=24)
    stale_guests = User.query.filter(
        User.email.like('%@temporary.invalid'),
        User.created_at < cutoff_guest,
    ).all()

    for u in stale_guests:
        uid = u.id
        GameResultParticipant.query.filter_by(user_id=uid).delete(synchronize_session=False)
        PlayerStats.query.filter_by(user_id=uid).delete(synchronize_session=False)
        LobbyPlayer.query.filter_by(user_id=uid).delete(synchronize_session=False)
        owned = [r[0] for r in db.session.query(Lobby.id).filter_by(owner_id=uid)]
        if owned:
            LobbyPlayer.query.filter(LobbyPlayer.lobby_id.in_(owned)).delete(synchronize_session=False)
            Lobby.query.filter(Lobby.id.in_(owned)).delete(synchronize_session=False)
        User.query.filter_by(id=uid).delete(synchronize_session=False)
        n_guests += 1

    # ── Stale lobbies ────────────────────────────────────────────────────────
    cutoff_game = now - timedelta(hours=1)   # game in-progress > 1 h
    cutoff_any  = now - timedelta(hours=2)   # any lobby > 2 h

    stale_ids = [
        r[0] for r in db.session.query(Lobby.id).filter(
            db.or_(
                db.and_(Lobby.game_started == True,  Lobby.created_at < cutoff_game),
                Lobby.created_at < cutoff_any,
            )
        )
    ]

    n_lobbies = 0
    if stale_ids:
        # Notify any players still on the game page so they're redirected
        try:
            from extensions import socketio as _sio
            for stale_lobby in Lobby.query.filter(Lobby.id.in_(stale_ids), Lobby.game_started == True):
                _sio.emit('game_force_end', {}, room=stale_lobby.code)
        except Exception:
            pass

        LobbyPlayer.query.filter(LobbyPlayer.lobby_id.in_(stale_ids)).delete(synchronize_session=False)
        n_lobbies = Lobby.query.filter(Lobby.id.in_(stale_ids)).delete(synchronize_session=False)

        # Remove stale entries from the in-memory games dict
        try:
            from game.socket_handlers import games
            for lid in stale_ids:
                games.pop(lid, None)
        except Exception:
            pass

    db.session.commit()

    if n_bots or n_guests or n_lobbies:
        try:
            from extensions import socketio
            socketio.emit('stats_updated', {}, broadcast=True)
        except Exception:
            pass

    return n_bots, n_guests, n_lobbies
