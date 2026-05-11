import logging

from flask import render_template, redirect, url_for, request, flash, session
from werkzeug.security import generate_password_hash

from extensions import db, socketio
from models import User, Lobby
from . import bp

logger = logging.getLogger(__name__)


def _require_admin():
    if not session.get('is_admin', False):
        flash('You do not have permission to access this page!', 'error')
        return False
    return True


@bp.route('/dashboard')
def dashboard():
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        user_count = User.query.filter_by(is_admin=False).count()
        lobby_count = Lobby.query.filter_by(is_active=True).count()
        return render_template('admin_dashboard.html', user_count=user_count, lobby_count=lobby_count)
    except Exception as e:
        logger.error(f"Error accessing admin dashboard: {e}")
        flash('An error occurred while accessing admin dashboard.', 'error')
        return redirect(url_for('lobbies.index'))


@bp.route('/users')
def users():
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        all_users = User.query.filter_by(is_admin=False).all()
        return render_template('admin_users.html', users=all_users)
    except Exception as e:
        logger.error(f"Error accessing admin users page: {e}")
        flash('An error occurred while retrieving users.', 'error')
        return redirect(url_for('admin.dashboard'))


@bp.route('/user/<int:user_id>')
def user_details(user_id):
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        user = User.query.get_or_404(user_id)
        if user.is_admin:
            flash('Cannot view admin user details!', 'error')
            return redirect(url_for('admin.users'))
        return render_template('admin_user_details.html', user=user)
    except Exception as e:
        logger.error(f"Error accessing user details: {e}")
        flash('An error occurred while retrieving user details.', 'error')
        return redirect(url_for('admin.users'))


@bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
def edit_user(user_id):
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        user = User.query.get_or_404(user_id)
        if user.is_admin:
            flash('Cannot edit admin user!', 'error')
            return redirect(url_for('admin.users'))

        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')

            existing = User.query.filter(
                ((User.username == username) | (User.email == email)) & (User.id != user_id)
            ).first()
            if existing:
                flash('Username or email already exists!', 'error')
                return render_template('admin_edit_user.html', user=user)

            user.username = username
            user.email = email
            new_password = request.form.get('password')
            if new_password:
                user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('User updated successfully!', 'success')
            return redirect(url_for('admin.user_details', user_id=user.id))

        return render_template('admin_edit_user.html', user=user)
    except Exception as e:
        logger.error(f"Error editing user: {e}")
        flash('An error occurred while editing user.', 'error')
        return redirect(url_for('admin.users'))


@bp.route('/user/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        user = User.query.get_or_404(user_id)
        if user.is_admin:
            flash('Cannot delete admin user!', 'error')
            return redirect(url_for('admin.users'))
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
        return redirect(url_for('admin.users'))
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        flash('An error occurred while deleting user.', 'error')
        return redirect(url_for('admin.users'))


@bp.route('/lobbies')
def lobbies():
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        active_lobbies = Lobby.query.filter_by(is_active=True).all()
        return render_template('admin_lobbies.html', lobbies=active_lobbies)
    except Exception as e:
        logger.error(f"Error accessing admin lobbies page: {e}")
        flash('An error occurred while retrieving lobbies.', 'error')
        return redirect(url_for('admin.dashboard'))


@bp.route('/lobby/<lobby_code>')
def lobby_detail(lobby_code):
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        lobby = Lobby.query.filter_by(code=lobby_code).first()
        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('admin.lobbies'))
        return render_template('admin_lobby_detail.html', lobby=lobby)
    except Exception as e:
        logger.error(f"Error accessing lobby details: {e}")
        flash('An error occurred while retrieving lobby details.', 'error')
        return redirect(url_for('admin.lobbies'))


@bp.route('/lobby/<lobby_code>/delete', methods=['POST'])
def delete_lobby(lobby_code):
    if not _require_admin():
        return redirect(url_for('lobbies.index'))
    try:
        lobby = Lobby.query.filter_by(code=lobby_code).first()
        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('admin.lobbies'))

        code_copy = lobby.code
        name_copy = lobby.name
        db.session.delete(lobby)
        db.session.commit()

        socketio.emit('admin_lobby_inactive', {
            'lobby_code': code_copy,
            'lobby_name': name_copy,
        }, room='admin_room')

        flash('Lobby deleted successfully!', 'success')
        return redirect(url_for('admin.lobbies'))
    except Exception as e:
        logger.error(f"Error deleting lobby: {e}")
        flash('An error occurred while deleting lobby.', 'error')
        return redirect(url_for('admin.lobbies'))
