import logging
from datetime import datetime

from flask import render_template, redirect, url_for, flash, session
from flask_login import login_required, current_user

from extensions import db, socketio
from models import User, Lobby, LobbyPlayer
from . import bp

logger = logging.getLogger(__name__)


@bp.route('/game/<lobby_code>')
@login_required
def page(lobby_code):
    lobby = Lobby.query.filter_by(code=lobby_code).first_or_404()

    if not lobby.game_started:
        flash('The game has not been started yet. Please wait for the lobby owner to start the game.', 'warning')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

    username = session.get('username')
    if username:
        user = User.query.filter_by(username=username).first()
        if user and not LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first():
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies.index'))

    return render_template('game.html', lobby=lobby, current_user=current_user)


@bp.route('/game/<lobby_code>/leave', methods=['POST'])
def leave(lobby_code):
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()

        if not lobby:
            flash('Lobby not found or no longer active!', 'error')
            return redirect(url_for('lobbies.index'))

        lp = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if not lp:
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies.index'))

        player_team = lp.team
        db.session.delete(lp)
        db.session.commit()

        remaining_count = LobbyPlayer.query.filter_by(lobby_id=lobby.id).count()
        lobby_name = lobby.name

        if remaining_count == 0:
            db.session.delete(lobby)
            db.session.commit()
            socketio.emit('admin_lobby_inactive', {
                'lobby_code': lobby_code,
                'lobby_name': lobby_name,
                'reason': 'Auto-deleted (all players left)',
                'time': datetime.utcnow().strftime('%H:%M:%S'),
            }, room='admin_room')

        socketio.emit('player_left_game', {
            'username': user.username,
            'user_id': user.id,
            'lobby_code': lobby_code,
            'team': player_team,
            'remaining_players': remaining_count,
            'is_last_player': remaining_count == 0,
        }, room=lobby_code)

        socketio.emit('admin_player_left_game', {
            'username': user.username,
            'user_id': user.id,
            'lobby_code': lobby_code,
            'lobby_name': lobby_name,
            'team': player_team,
            'remaining_players': remaining_count,
            'time': datetime.utcnow().strftime('%H:%M:%S'),
            'is_last_player': remaining_count == 0,
        }, room='admin_room')

        if remaining_count > 0:
            socketio.emit('admin_lobby_player_left_game', {
                'username': user.username,
                'user_id': user.id,
                'team': player_team,
                'remaining_players': remaining_count,
            }, room=f"admin_lobby_{lobby_code}")

        flash('You have left the game and the lobby!', 'success')
        return redirect(url_for('lobbies.index'))
    except Exception as e:
        logger.error(f"Error leaving game: {e}")
        db.session.rollback()
        flash('An error occurred while leaving game. Please try again.', 'error')
        return redirect(url_for('lobbies.index'))
