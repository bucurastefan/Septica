import logging
from datetime import datetime

from flask import render_template, redirect, url_for, request, flash, session
from flask_login import login_required

from extensions import db, socketio
from models import User, Lobby, LobbyPlayer, generate_lobby_code
from game.socket_handlers import game_completion_messages
from . import bp

logger = logging.getLogger(__name__)


def _user_in_active_lobby(user_id):
    for lp in LobbyPlayer.query.filter_by(user_id=user_id).all():
        if lp.lobby.is_active:
            return lp.lobby
    return None


@bp.route('/lobbies')
def index():
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        if not user:
            flash('User not found!', 'error')
            return redirect(url_for('auth.login'))

        if user.username in game_completion_messages:
            msg = game_completion_messages.pop(user.username)
            flash(msg['message'], msg['type'])

        user_lobbies, user_active_games = [], []
        for lp in user.lobby_players:
            if lp.lobby.is_active:
                (user_active_games if lp.lobby.game_started else user_lobbies).append(lp.lobby)

        public_lobbies = [
            l for l in Lobby.query.filter_by(is_active=True, is_public=True, game_started=False).all()
            if l not in user_lobbies
        ]

        return render_template(
            'lobbies.html',
            user=user,
            user_lobbies=user_lobbies,
            public_lobbies=public_lobbies,
            user_active_games=user_active_games,
        )
    except Exception as e:
        logger.error(f"Error accessing lobbies page: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('auth.login'))


@bp.route('/lobby/create', methods=['POST'])
def create():
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()

        current_lobby = _user_in_active_lobby(user.id)
        if current_lobby:
            flash(
                f'You are already in lobby {current_lobby.code}. Please leave that lobby first.',
                'error',
            )
            return redirect(url_for('lobbies.detail', lobby_code=current_lobby.code))

        is_public = request.form.get('is_public') is not None
        player_count_type = int(request.form.get('player_count_type', 4))
        if player_count_type not in [3, 4]:
            player_count_type = 4

        lobby_code = generate_lobby_code()
        lobby_name = f"Lobby {user.username}"

        new_lobby = Lobby(
            code=lobby_code,
            name=lobby_name,
            owner_id=user.id,
            is_active=True,
            is_public=is_public,
            player_count_type=player_count_type,
        )
        db.session.add(new_lobby)
        db.session.flush()

        # In 3-player mode the creator is automatically the first seat (Team 1)
        first_team = 1 if player_count_type == 3 else 0
        db.session.add(LobbyPlayer(lobby_id=new_lobby.id, user_id=user.id, team=first_team))
        db.session.commit()

        socketio.emit('admin_lobby_created', {
            'lobby_id': new_lobby.id,
            'lobby_code': lobby_code,
            'lobby_name': lobby_name,
            'owner_username': user.username,
            'owner_id': user.id,
            'is_public': is_public,
            'created_at': new_lobby.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }, room='admin_room')

        if is_public:
            socketio.emit('lobbies_list_changed')

        flash(
            f'Lobby created! Code: {lobby_code}. Select a team and invite 3 more friends!',
            'success',
        )
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error creating lobby: {e}")
        db.session.rollback()
        flash('An error occurred while creating lobby. Please try again.', 'error')
        return redirect(url_for('lobbies.index'))


@bp.route('/lobby/join', methods=['POST'])
def join():
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby_code = request.form.get('lobby_code', '').strip().upper()

        if not lobby_code:
            flash('Please enter a lobby code!', 'error')
            return redirect(url_for('lobbies.index'))

        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()
        if not lobby:
            flash('Invalid lobby code or lobby no longer active!', 'error')
            return redirect(url_for('lobbies.index'))

        if lobby.game_started:
            flash('Cannot join this lobby: the game has already started!', 'error')
            return redirect(url_for('lobbies.index'))

        if lobby.is_full:
            flash('This lobby is full!', 'error')
            return redirect(url_for('lobbies.index'))

        if LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first():
            flash('You are already in this lobby!', 'info')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        current_lobby = _user_in_active_lobby(user.id)
        if current_lobby:
            flash(
                f'You are already in lobby {current_lobby.code}. Please leave that lobby first.',
                'error',
            )
            return redirect(url_for('lobbies.detail', lobby_code=current_lobby.code))

        # In 3-player mode, assign the next free seat automatically (1 → 2 → 3)
        if lobby.player_count_type == 3:
            taken = {p.team for p in lobby.players}
            assigned_team = next((t for t in [1, 2, 3] if t not in taken), 0)
        else:
            assigned_team = 0

        lp = LobbyPlayer(lobby_id=lobby.id, user_id=user.id, team=assigned_team)
        db.session.add(lp)
        db.session.commit()

        joined_at = datetime.utcnow().strftime('%H:%M:%S')
        socketio.emit('player_joined', {
            'username': user.username,
            'user_id': user.id,
            'joined_at': joined_at,
            'team': lp.team,
        }, room=lobby_code)

        socketio.emit('admin_player_joined', {
            'username': user.username,
            'user_id': user.id,
            'joined_at': joined_at,
            'lobby_code': lobby_code,
            'lobby_name': lobby.name,
            'player_count': lobby.player_count,
        }, room='admin_room')

        socketio.emit('admin_lobby_player_joined', {
            'username': user.username,
            'user_id': user.id,
            'joined_at': joined_at,
        }, room=f"admin_lobby_{lobby_code}")

        if lobby.is_public:
            socketio.emit('lobbies_list_changed')

        flash(f'Successfully joined lobby {lobby_code}!', 'success')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error joining lobby: {e}")
        db.session.rollback()
        flash('An error occurred while joining lobby. Please try again.', 'error')
        return redirect(url_for('lobbies.index'))


@bp.route('/lobby/<lobby_code>')
def detail(lobby_code):
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()

        if not lobby:
            flash('Lobby not found or no longer active!', 'error')
            return redirect(url_for('lobbies.index'))

        if not LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first():
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies.index'))

        # Show the post-game result message if one is waiting for this player
        if user.username in game_completion_messages:
            msg = game_completion_messages.pop(user.username)
            flash(msg['message'], msg['type'])

        return render_template(
            'lobby_detail.html',
            lobby=lobby,
            is_owner=(lobby.owner_id == user.id),
            user=user,
        )
    except Exception as e:
        logger.error(f"Error viewing lobby: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('lobbies.index'))


@bp.route('/lobby/<lobby_code>/leave', methods=['POST'])
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

        is_owner = lobby.owner_id == user.id
        db.session.delete(lp)

        remaining = LobbyPlayer.query.filter_by(lobby_id=lobby.id).all()
        new_owner_username = None

        lobby_code_copy = lobby.code
        lobby_name_copy = lobby.name

        if len(remaining) == 0:
            db.session.delete(lobby)
            socketio.emit('admin_lobby_inactive', {
                'lobby_code': lobby_code_copy,
                'lobby_name': lobby_name_copy,
            }, room='admin_room')
        elif is_owner:
            new_owner = remaining[0].user
            new_owner_username = new_owner.username
            lobby.owner_id = new_owner.id
            socketio.emit('owner_changed', {
                'previous_owner': user.username,
                'new_owner': new_owner_username,
                'new_owner_id': new_owner.id,
            }, room=lobby_code)
            socketio.emit('admin_owner_changed', {
                'lobby_code': lobby.code,
                'lobby_name': lobby.name,
                'previous_owner': user.username,
                'new_owner': new_owner_username,
            }, room='admin_room')

        db.session.commit()

        socketio.emit('player_left', {'username': user.username, 'user_id': user.id}, room=lobby_code)
        socketio.emit('admin_player_left', {
            'username': user.username,
            'user_id': user.id,
            'lobby_code': lobby_code,
            'lobby_name': lobby_name_copy,
            'player_count': len(remaining),
            'is_owner': is_owner,
            'new_owner': new_owner_username,
        }, room='admin_room')

        if remaining:
            socketio.emit('admin_lobby_player_left', {
                'username': user.username,
                'user_id': user.id,
                'is_owner': is_owner,
                'new_owner': new_owner_username,
            }, room=f"admin_lobby_{lobby_code}")

        socketio.emit('lobbies_list_changed')
        flash('Successfully left the lobby!', 'success')
        return redirect(url_for('lobbies.index'))
    except Exception as e:
        logger.error(f"Error leaving lobby: {e}")
        db.session.rollback()
        flash('An error occurred while leaving lobby. Please try again.', 'error')
        return redirect(url_for('lobbies.index'))


@bp.route('/lobby/<lobby_code>/update_settings', methods=['POST'])
def update_settings(lobby_code):
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()

        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('lobbies.index'))

        if lobby.owner_id != user.id:
            flash('Only the lobby owner can update settings!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.game_started:
            flash('Cannot update settings after game has started!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        new_player_count_type = int(request.form.get('player_count_type', 4))
        if new_player_count_type not in [3, 4]:
            flash('Invalid game type!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.player_count_type == 4 and new_player_count_type == 3 and lobby.player_count >= 4:
            flash('Cannot switch to 3-player mode while 4 players are in the lobby. Ask one player to leave first.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.player_count_type != new_player_count_type:
            for player in lobby.players:
                player.team = 0

            lobby.player_count_type = new_player_count_type
            if lobby.name and '(' in lobby.name:
                lobby.name = lobby.name.split('(')[0].strip()

            # Stats from a different game mode are meaningless — reset them
            lobby.team1_wins = 0
            lobby.team2_wins = 0
            lobby.team3_wins = 0
            lobby.total_games_played = 0
            lobby.next_game_multiplier = 1

            db.session.flush()

            if new_player_count_type == 3:
                # 3-player: auto-assign everyone
                for lp in sorted(lobby.players, key=lambda p: p.joined_at):
                    lobby.assign_team(lp.user_id)
            else:
                # 4-player: auto-assign bots only (humans pick their team manually)
                for lp in sorted(lobby.players, key=lambda p: p.joined_at):
                    u = User.query.get(lp.user_id)
                    if u and u.is_bot:
                        lobby.assign_team(lp.user_id)

            db.session.commit()

            # Notify every client in the lobby so they reload and see the new settings
            socketio.emit('lobby_settings_updated', {
                'lobby_code': lobby_code,
                'player_count_type': new_player_count_type,
            }, room=lobby_code)

            flash(
                f'Lobby updated to {new_player_count_type}-player game! All team assignments have been reset.',
                'success',
            )
        else:
            flash('No changes made to lobby settings.', 'info')

        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error updating lobby settings: {e}")
        flash('An error occurred while updating lobby settings. Please try again.', 'error')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))


@bp.route('/lobby/<lobby_code>/start', methods=['POST'])
def start_game(lobby_code):
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()

        if not lobby:
            flash('Lobby not found or no longer active!', 'error')
            return redirect(url_for('lobbies.index'))

        if lobby.owner_id != user.id:
            flash('Only the lobby owner can start the game!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        required_players = lobby.player_count_type
        if lobby.player_count != required_players:
            flash(f'You need exactly {required_players} players to start the game!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.unassigned_players:
            flash('All players must be assigned to a team before starting!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.player_count_type == 3:
            if not (len(lobby.team1_players) == 1 and len(lobby.team2_players) == 1 and len(lobby.team3_players) == 1):
                flash('Each team must have exactly 1 player in a 3-player game!', 'error')
                return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
        else:
            if not (len(lobby.team1_players) == 2 and len(lobby.team2_players) == 2):
                flash('Each team must have exactly 2 players in a 4-player game!', 'error')
                return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        lobby.game_started = True
        db.session.commit()

        socketio.emit('game_started', {
            'lobby_code': lobby_code,
            'redirect_url': url_for('game.page', lobby_code=lobby_code),
        }, room=lobby_code)

        socketio.emit('lobby_game_started', {
            'lobby_code': lobby_code,
            'lobby_name': lobby.name,
            'owner_username': user.username,
        })

        return redirect(url_for('game.page', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error starting game: {e}")
        flash('An error occurred while starting game. Please try again.', 'error')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))


@bp.route('/lobby/<lobby_code>/change_team', methods=['POST'])
def change_team(lobby_code):
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

        # 3-player lobbies use automatic seat assignment
        if lobby.player_count_type == 3:
            flash('Team seats are assigned automatically in 3-player games.', 'info')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        new_team = int(request.form.get('team', 0))
        if new_team not in [0, 1, 2]:
            flash('Invalid team selection!', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        old_team = lp.team
        if old_team != 0 and new_team != 0:
            flash('You must first leave your current team before joining a new one.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if new_team in [1, 2]:
            team_players = lobby.team1_players if new_team == 1 else lobby.team2_players
            team_name = "Team Purple" if new_team == 1 else "Team Black"
            if len(team_players) >= 2:
                flash(f'{team_name} is already full!', 'error')
                return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        lp.team = new_team
        db.session.commit()

        socketio.emit('player_team_changed', {
            'username': user.username,
            'user_id': user.id,
            'old_team': old_team,
            'new_team': new_team,
        }, room=lobby_code)

        if new_team == 0:
            flash('You left your team and are now unassigned.', 'success')
        else:
            flash(f'You joined {"Team Purple" if new_team == 1 else "Team Black"}!', 'success')

        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error changing team: {e}")
        db.session.rollback()
        flash('An error occurred while changing team. Please try again.', 'error')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))


@bp.route('/lobby/<lobby_code>/vote_reset_stats', methods=['POST'])
def vote_reset_stats(lobby_code):
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

        lp.voted_reset_stats = not lp.voted_reset_stats
        db.session.commit()

        all_players = LobbyPlayer.query.filter_by(lobby_id=lobby.id).all()
        votes_count = sum(1 for p in all_players if p.voted_reset_stats)
        total_needed = lobby.player_count_type

        socketio.emit('reset_vote_update', {
            'votes_count': votes_count,
            'total_needed': total_needed,
            'voters': [p.user.username for p in all_players if p.voted_reset_stats],
            'total_players': len(all_players),
        }, room=lobby_code)

        if len(all_players) == total_needed and votes_count == total_needed:
            lobby.team1_wins = 0
            lobby.team2_wins = 0
            lobby.team3_wins = 0
            lobby.total_games_played = 0
            lobby.next_game_multiplier = 1
            for p in all_players:
                p.voted_reset_stats = False
            db.session.commit()

            socketio.emit('stats_reset', {
                'message': 'Lobby statistics have been reset!',
                'team1_wins': 0,
                'team2_wins': 0,
                'team3_wins': 0,
                'total_games_played': 0,
                'next_game_multiplier': 1,
            }, room=lobby_code)

            flash('Statistics have been reset successfully!', 'success')
        else:
            if lp.voted_reset_stats:
                if len(all_players) == total_needed:
                    flash(f'You voted to reset statistics! ({votes_count}/{total_needed} votes)', 'info')
                else:
                    flash(
                        f'You voted to reset statistics! Need {total_needed} players in lobby first. '
                        f'({len(all_players)}/{total_needed} players)',
                        'warning',
                    )
            else:
                flash('You withdrew your vote to reset statistics.', 'info')

        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error voting for stats reset: {e}")
        db.session.rollback()
        flash('An error occurred while voting. Please try again.', 'error')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))


# ---------------------------------------------------------------------------
# Bot management
# ---------------------------------------------------------------------------

@bp.route('/lobby/<lobby_code>/add_bot', methods=['POST'])
def add_bot(lobby_code):
    if 'username' not in session:
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()

        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('lobbies.index'))

        if lobby.owner_id != user.id:
            flash('Only the lobby owner can add bots.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.game_started:
            flash('Cannot add bots after the game has started.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.is_full:
            flash('Lobby is already full.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        if lobby.player_count_type == 4 and lobby.player_count >= 4:
            flash('Cannot switch to 3-player mode while 4 players are in the lobby.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        difficulty = request.form.get('difficulty', 'easy')
        if difficulty not in ('easy', 'medium', 'hard', 'smart'):
            difficulty = 'easy'

        # Create the bot user with a unique name
        import uuid
        bot_username = f"Bot_{difficulty.capitalize()}_{uuid.uuid4().hex[:4].upper()}"
        bot = User(
            username=bot_username,
            email=f"bot_{uuid.uuid4().hex}@bot.internal",
            password='',
            is_bot=True,
            bot_difficulty=difficulty,
        )
        db.session.add(bot)
        db.session.flush()

        # Auto-assign team (works for both 3-player and 4-player)
        if lobby.player_count_type == 3:
            taken = {p.team for p in lobby.players}
            team = next((t for t in [1, 2, 3] if t not in taken), 0)
        else:
            team1 = len(lobby.team1_players)
            team2 = len(lobby.team2_players)
            if team1 <= team2 and team1 < 2:
                team = 1
            elif team2 < 2:
                team = 2
            else:
                team = 0

        lp = LobbyPlayer(lobby_id=lobby.id, user_id=bot.id, team=team)
        db.session.add(lp)
        db.session.commit()

        from datetime import timezone
        joined_at = datetime.now(timezone.utc).strftime('%H:%M:%S')
        socketio.emit('player_joined', {
            'username': bot_username,
            'user_id': bot.id,
            'joined_at': joined_at,
            'team': team,
            'is_bot': True,
            'bot_difficulty': difficulty,
        }, room=lobby_code)

        if lobby.is_public:
            socketio.emit('lobbies_list_changed')

        flash(f'Bot ({difficulty}) added to the lobby.', 'success')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error adding bot: {e}")
        db.session.rollback()
        flash('An error occurred while adding bot.', 'error')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))


@bp.route('/lobby/<lobby_code>/remove_bot/<int:bot_user_id>', methods=['POST'])
def remove_bot(lobby_code, bot_user_id):
    if 'username' not in session:
        return redirect(url_for('auth.login'))

    try:
        user = User.query.filter_by(username=session['username']).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()

        if not lobby or lobby.owner_id != user.id:
            flash('Only the lobby owner can remove bots.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        bot = User.query.get(bot_user_id)
        if not bot or not bot.is_bot:
            flash('Bot not found.', 'error')
            return redirect(url_for('lobbies.detail', lobby_code=lobby_code))

        # Remove any stale PlayerStats (bots shouldn't have them, but clean up just in case)
        from models import PlayerStats
        stale_stats = PlayerStats.query.filter_by(user_id=bot.id).first()
        if stale_stats:
            db.session.delete(stale_stats)

        # Cascade on User already deletes LobbyPlayer, but be explicit to be safe
        lp = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=bot.id).first()
        if lp:
            db.session.delete(lp)

        db.session.delete(bot)
        db.session.commit()

        socketio.emit('player_left', {'username': bot.username, 'user_id': bot_user_id}, room=lobby_code)
        if lobby.is_public:
            socketio.emit('lobbies_list_changed')

        flash('Bot removed from the lobby.', 'success')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error removing bot: {e}")
        db.session.rollback()
        flash('An error occurred while removing bot.', 'error')
        return redirect(url_for('lobbies.detail', lobby_code=lobby_code))
