import logging
from datetime import datetime

from flask import render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, LobbyPlayer
from . import bp

logger = logging.getLogger(__name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        try:
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
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
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
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

    if len(guest_name) > 20:
        flash('Guest name must be 20 characters or less!', 'error')
        return redirect(url_for('auth.login'))

    if User.query.filter_by(username=guest_name).first():
        flash('This name is already taken. Please choose another name.', 'error')
        return redirect(url_for('auth.login'))

    try:
        guest_user = User(
            username=guest_name,
            email=f"guest_{datetime.utcnow().timestamp()}@temporary.com",
            password="guest_temp_password",
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
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Please provide both email and password.', 'error')
            return render_template('convert_guest.html')

        try:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user and not existing_user.email.startswith('guest_'):
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
