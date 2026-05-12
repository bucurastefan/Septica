import logging
import re
from datetime import datetime

from flask import render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, LobbyPlayer
from . import bp

logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{3,20}$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _validate_registration(username, email, password):
    """Return an error string or None if inputs are valid."""
    if not username or not _USERNAME_RE.match(username):
        return 'Username must be 3–20 characters (letters, digits, underscores only).'
    if not email or not _EMAIL_RE.match(email) or len(email) > 120:
        return 'Please enter a valid email address.'
    if not password or len(password) < 8:
        return 'Password must be at least 8 characters.'
    return None


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        try:
            user = User.query.filter_by(username=username).first()
            if user and not user.is_bot and check_password_hash(user.password, password):
                login_user(user)
                session['username'] = username
                session['is_admin'] = bool(user.is_admin)
                flash('Login successful!', 'success')
                return redirect(url_for('lobbies.index'))
            else:
                flash('Invalid username or password!', 'error')
        except Exception as e:
            logger.error(f"Error during login: {e}")
            flash('An error occurred during login. Please try again.', 'error')
    return render_template('login.html')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        error = _validate_registration(username, email, password)
        if error:
            flash(error, 'error')
            return redirect(url_for('auth.register'))

        try:
            existing_user = User.query.filter(
                (User.username == username) | (User.email == email)
            ).first()
            if existing_user:
                flash('Username or email already exists!', 'error')
                return redirect(url_for('auth.register'))

            new_user = User(
                username=username,
                email=email,
                password=generate_password_hash(password),
            )
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
    return render_template('register.html')


@bp.route('/guest_login', methods=['POST'])
def guest_login():
    guest_name = request.form.get('guest_name', '').strip()

    if not guest_name:
        flash('Please enter a guest name!', 'error')
        return redirect(url_for('auth.login'))

    if not _USERNAME_RE.match(guest_name):
        flash('Guest name must be 3–20 characters (letters, digits, underscores only).', 'error')
        return redirect(url_for('auth.login'))

    if User.query.filter_by(username=guest_name).first():
        flash('This name is already taken. Please choose another name.', 'error')
        return redirect(url_for('auth.login'))

    try:
        import secrets
        guest_user = User(
            username=guest_name,
            email=f"guest_{secrets.token_hex(8)}@temporary.invalid",
            password=generate_password_hash(secrets.token_hex(16)),
            is_admin=False,
        )
        db.session.add(guest_user)
        db.session.commit()

        login_user(guest_user)
        session['username'] = guest_name
        session['is_guest'] = True
        session['guest_user_id'] = guest_user.id
        session['is_admin'] = False

        flash(
            f'Welcome, {guest_name}! You are playing as a guest. Your data will be deleted when you leave.',
            'success',
        )
        return redirect(url_for('lobbies.index'))
    except Exception as e:
        logger.error(f"Error creating guest user: {e}")
        flash('An error occurred while creating guest account. Please try again.', 'error')
        return redirect(url_for('auth.login'))


@bp.route('/convert_guest', methods=['GET', 'POST'])
def convert_guest():
    if not session.get('is_guest', False):
        flash('This feature is only available for guest users.', 'error')
        return redirect(url_for('lobbies.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not _EMAIL_RE.match(email) or len(email) > 120:
            flash('Please enter a valid email address.', 'error')
            return render_template('convert_guest.html')

        if not password or len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('convert_guest.html')

        try:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user and not existing_user.email.endswith('@temporary.invalid'):
                flash('This email is already registered.', 'error')
                return render_template('convert_guest.html')

            guest_user = User.query.get(session.get('guest_user_id'))
            if guest_user:
                guest_user.email = email
                guest_user.password = generate_password_hash(password)
                db.session.commit()

                session['is_guest'] = False
                session.pop('guest_user_id', None)

                flash(
                    'Your guest account has been converted to a registered account! Your game progress is now saved.',
                    'success',
                )
                return redirect(url_for('lobbies.index'))
            else:
                flash('Guest user not found.', 'error')
                return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Error converting guest account: {e}")
            flash('An error occurred while converting your account. Please try again.', 'error')

    return render_template('convert_guest.html')


@bp.route('/logout')
def logout():
    try:
        if session.get('is_guest', False) and 'guest_user_id' in session:
            guest_user_id = session['guest_user_id']
            guest_user = User.query.get(guest_user_id)
            if guest_user:
                for lp in LobbyPlayer.query.filter_by(user_id=guest_user_id).all():
                    db.session.delete(lp)
                db.session.delete(guest_user)
                db.session.commit()
                logger.info(f"Deleted guest user: {guest_user.username}")
    except Exception as e:
        logger.error(f"Error deleting guest user during logout: {e}")
        db.session.rollback()

    logout_user()
    session.clear()
    flash('You have been logged out!', 'success')
    return redirect(url_for('auth.login'))
