import logging

from flask import render_template, redirect, url_for, flash, session
from flask_login import current_user

from extensions import db
from models import User, PlayerStats
from . import bp

logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('lobbies.index'))
    return redirect(url_for('auth.login'))


@bp.route('/rules')
def rules():
    return render_template('rules.html')


@bp.route('/statistics')
def statistics():
    if 'username' not in session:
        flash('You need to be logged in to view statistics!', 'error')
        return redirect(url_for('auth.login'))

    if session.get('is_guest', False):
        flash(
            'Statistics are not available for guest users. Register for an account to track your progress!',
            'info',
        )
        return redirect(url_for('lobbies.index'))

    try:
        user = User.query.filter_by(username=session.get('username')).first()
        if not user:
            flash('User not found!', 'error')
            return redirect(url_for('auth.login'))

        stats = PlayerStats.query.filter_by(user_id=user.id).first()
        if not stats:
            stats = PlayerStats(user_id=user.id)
            db.session.add(stats)
            db.session.commit()

        leaderboard_4p = (
            db.session.query(PlayerStats, User)
            .join(User)
            .filter(PlayerStats.games_played > 0)
            .filter(User.is_bot.is_(False))
            .order_by(PlayerStats.games_won.desc())
            .limit(10)
            .all()
        )

        leaderboard_3p = (
            db.session.query(PlayerStats, User)
            .join(User)
            .filter(PlayerStats.games_played_3p > 0)
            .filter(User.is_bot.is_(False))
            .order_by(PlayerStats.games_won_3p.desc())
            .limit(10)
            .all()
        )

        user_rank_4p = (
            db.session.query(PlayerStats)
            .join(User)
            .filter(PlayerStats.games_won > stats.games_won, PlayerStats.games_played > 0)
            .filter(User.is_bot.is_(False))
            .count()
            + 1
        )

        user_rank_3p = (
            db.session.query(PlayerStats)
            .join(User)
            .filter(PlayerStats.games_won_3p > stats.games_won_3p, PlayerStats.games_played_3p > 0)
            .filter(User.is_bot.is_(False))
            .count()
            + 1
        )

        return render_template(
            'statistics.html',
            user=user,
            stats=stats,
            leaderboard_4p=leaderboard_4p,
            leaderboard_3p=leaderboard_3p,
            user_rank_4p=user_rank_4p,
            user_rank_3p=user_rank_3p,
        )
    except Exception as e:
        logger.error(f"Error accessing statistics page: {e}")
        flash('An error occurred while loading statistics.', 'error')
        return redirect(url_for('lobbies.index'))


@bp.route('/status')
def status():
    try:
        User.query.first()
        return "Database connected successfully!"
    except Exception as e:
        return f"Database connection failed: {e}"
