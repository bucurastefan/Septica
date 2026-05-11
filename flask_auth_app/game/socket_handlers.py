import logging
from datetime import datetime

from flask import session
from flask_socketio import emit, join_room, leave_room

from extensions import db, socketio
from models import User, Lobby, LobbyPlayer, PlayerStats, get_ordered_players
from .logic import SepticaGame

logger = logging.getLogger(__name__)

games = {}
game_completion_messages = {}


# ---------------------------------------------------------------------------
# Connection / room helpers
# ---------------------------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        logger.info(f"User {session['username']} connected")
        if session.get('is_admin', False):
            join_room('admin_room')
            logger.info(f"Admin {session['username']} joined admin_room")
    else:
        logger.info("Anonymous user connected")


@socketio.on('join_lobby_room')
def handle_join_lobby_room(data):
    lobby_code = data.get('lobby_code')
    if lobby_code:
        join_room(lobby_code)
        logger.info(f"User joined room: {lobby_code}")


@socketio.on('leave_lobby_room')
def handle_leave_lobby_room(data):
    lobby_code = data.get('lobby_code')
    if lobby_code:
        leave_room(lobby_code)
        logger.info(f"User left room: {lobby_code}")


@socketio.on('join_admin_lobby_room')
def handle_join_admin_lobby_room(data):
    if not session.get('is_admin', False):
        return
    lobby_code = data.get('lobby_code')
    if lobby_code:
        join_room(f"admin_lobby_{lobby_code}")
        logger.info(f"Admin joined room: admin_lobby_{lobby_code}")


# ---------------------------------------------------------------------------
# Game lifecycle
# ---------------------------------------------------------------------------

@socketio.on('initialize_game')
def handle_initialize_game(data):
    lobby_code = data.get('lobby_code')

    lobby = Lobby.query.filter_by(code=lobby_code).first()
    if not lobby or not lobby.game_started:
        emit('error', {'message': 'Game has not been started yet'})
        return

    if lobby_code not in games:
        starting_player = SepticaGame.calculate_starting_player(
            lobby.total_games_played, lobby.player_count_type
        )
        games[lobby_code] = SepticaGame(starting_player, num_players=lobby.player_count_type)

    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    if not user:
        emit('error', {'message': 'User not found'})
        return

    if not LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first():
        emit('error', {'message': 'You are not a member of this lobby'})
        return

    lobby_players = get_ordered_players(lobby.id, lobby.player_count_type)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)

    if player_position is not None:
        join_room(f"{lobby_code}_player_{player_position}")
        player_names = [lp.user.username for lp in lobby_players]

        game_state = games[lobby_code].get_game_state(player_position)
        game_state['position'] = player_position
        game_state['username'] = username
        game_state['player_names'] = player_names
        emit('game_state_update', game_state)


@socketio.on('play_card')
def handle_play_card(data):
    lobby_code = data.get('lobby_code')
    card_index = data.get('card_index')

    lobby = Lobby.query.filter_by(code=lobby_code).first()
    if not lobby or not lobby.game_started:
        emit('error', {'message': 'Game has not been started yet'})
        return

    if lobby_code not in games:
        emit('error', {'message': 'Game not found'})
        return

    user = _get_current_user()
    if not user:
        emit('error', {'message': 'User not found'})
        return

    if not LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first():
        emit('error', {'message': 'You are not a member of this lobby'})
        return

    lobby_players = get_ordered_players(lobby.id, lobby.player_count_type)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)
    if player_position is None:
        return

    player_names = [lp.user.username for lp in lobby_players]
    success, error = games[lobby_code].play_card(player_position, card_index)

    if success:
        if _handle_game_completion(lobby_code, lobby, lobby_players):
            return
        _broadcast_game_state(lobby_code, lobby_players, player_names)
    else:
        emit('game_error', {'message': error})


@socketio.on('take_hand')
def handle_take_hand(data):
    _handle_hand_action(data, 'take')


@socketio.on('forfeit_hand')
def handle_forfeit_hand(data):
    _handle_hand_action(data, 'forfeit')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_current_user():
    username = session.get('username')
    return User.query.filter_by(username=username).first() if username else None


def _broadcast_game_state(lobby_code, lobby_players, player_names):
    for i in range(len(lobby_players)):
        state = games[lobby_code].get_game_state(i)
        state['position'] = i
        state['player_names'] = player_names
        emit('game_state_update', state, room=f"{lobby_code}_player_{i}")


def _handle_hand_action(data, action):
    lobby_code = data.get('lobby_code')
    if lobby_code not in games:
        return

    lobby = Lobby.query.filter_by(code=lobby_code).first()
    user = _get_current_user()
    if not user or not lobby:
        return

    lobby_players = get_ordered_players(lobby.id, lobby.player_count_type)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)
    if player_position is None:
        return

    player_names = [lp.user.username for lp in lobby_players]
    fn = games[lobby_code].take_hand if action == 'take' else games[lobby_code].forfeit_hand
    success, error = fn()

    if success:
        if _handle_game_completion(lobby_code, lobby, lobby_players):
            return
        _broadcast_game_state(lobby_code, lobby_players, player_names)
    else:
        emit('game_error', {'message': error})


def _handle_game_completion(lobby_code, lobby, lobby_players):
    game = games[lobby_code]
    if not game.is_game_finished():
        return False

    result = game.get_game_result()
    winner = result['winner']
    is_tie = result['is_tie']
    scores = result['scores']
    hands_won = result['hands_won']
    num_players = game.num_players

    player_names = [lp.user.username for lp in lobby_players]

    lobby.total_games_played += 1

    if num_players == 3:
        notification_message, notification_type, is_perfect_game = _resolve_3player_outcome(
            lobby, player_names, winner, is_tie, scores, hands_won
        )
    else:
        notification_message, notification_type, is_perfect_game = _resolve_4player_outcome(
            lobby, winner, is_tie, scores, hands_won
        )

    _update_player_statistics(lobby, lobby_players, winner, is_tie, scores,
                               hands_won, is_perfect_game, num_players)
    db.session.commit()

    # Build the per-player notification stored for the lobbies page
    if num_players == 3:
        score_str = ', '.join(f"{player_names[i]}: {scores[i]}" for i in range(3))
        lobby_stat_str = (
            f"{player_names[0]}: {lobby.team1_wins} - "
            f"{player_names[1]}: {lobby.team2_wins} - "
            f"{player_names[2]}: {lobby.team3_wins} wins"
        )
        completion_message = f"{notification_message} Scores: {score_str}. Lobby: {lobby_stat_str}"
    else:
        completion_message = (
            f"{notification_message} Lobby Stats: "
            f"Team Purple: {lobby.team1_wins} wins - Team Black: {lobby.team2_wins} wins"
        )

    for lp in lobby_players:
        game_completion_messages[lp.user.username] = {
            'message': completion_message,
            'type': notification_type,
            'lobby_code': lobby_code,
        }

    lobby.game_started = False
    db.session.commit()
    del games[lobby_code]

    completion_data = {
        'game_finished': True,
        'winner_team': winner,
        'is_tie': is_tie,
        'scores': scores,
        'num_players': num_players,
        'player_names': player_names,
        'lobby_stats': {
            'team1_wins': lobby.team1_wins,
            'team2_wins': lobby.team2_wins,
            'team3_wins': lobby.team3_wins,
            'next_game_multiplier': lobby.next_game_multiplier,
        },
        'message': completion_message,
        'notification_type': notification_type,
    }

    for i in range(len(lobby_players)):
        emit('game_completed', completion_data, room=f"{lobby_code}_player_{i}")
    emit('game_completed', completion_data, room=lobby_code)

    return True


def _resolve_4player_outcome(lobby, winner, is_tie, scores, hands_won):
    """Return (notification_message, notification_type, is_perfect_game) for 4-player."""
    if is_tie:
        lobby.next_game_multiplier = 2
        msg = f"Game ended in a tie! ({scores[0]}-{scores[1]}) Next game is worth 2 points."
        return msg, "info", False

    is_perfect = (
        (hands_won[0] == 0 and winner == 1) or
        (hands_won[1] == 0 and winner == 0)
    )
    points = lobby.next_game_multiplier + (1 if is_perfect else 0)

    if winner == 0:
        lobby.team1_wins += points
        team_name = "Team Purple"
    else:
        lobby.team2_wins += points
        team_name = "Team Black"

    lobby.next_game_multiplier = 1

    if is_perfect:
        msg = (
            f"{team_name} wins PERFECTLY! ({scores[0]}-{scores[1]}, "
            f"opponent won 0 hands) +{points} points (bonus for shutout)."
        )
    else:
        msg = f"{team_name} wins! ({scores[0]}-{scores[1]}) +{points} points awarded."

    return msg, "success", is_perfect


def _resolve_3player_outcome(lobby, player_names, winner, is_tie, scores, hands_won):
    """Return (notification_message, notification_type, is_perfect_game) for 3-player."""
    if is_tie:
        lobby.next_game_multiplier = 2
        score_str = ', '.join(f"{player_names[i]}: {scores[i]}" for i in range(3))
        msg = f"Game ended in a tie! ({score_str}) Next game is worth 2 points."
        return msg, "info", False

    # Perfect game: winner took all hands
    losers = [i for i in range(3) if i != winner]
    is_perfect = all(hands_won[i] == 0 for i in losers)
    points = lobby.next_game_multiplier + (1 if is_perfect else 0)

    winner_name = player_names[winner]
    if winner == 0:
        lobby.team1_wins += points
    elif winner == 1:
        lobby.team2_wins += points
    else:
        lobby.team3_wins += points

    lobby.next_game_multiplier = 1

    score_str = ', '.join(f"{player_names[i]}: {scores[i]}" for i in range(3))
    if is_perfect:
        msg = (
            f"{winner_name} wins PERFECTLY! Scores: {score_str}. "
            f"+{points} points (bonus for shutout)."
        )
    else:
        msg = f"{winner_name} wins! Scores: {score_str}. +{points} points awarded."

    return msg, "success", is_perfect


def _get_or_create_stats(user_id):
    stats = PlayerStats.query.filter_by(user_id=user_id).first()
    if not stats:
        stats = PlayerStats(user_id=user_id)
        db.session.add(stats)
        db.session.flush()
    return stats


def _update_player_statistics(lobby, lobby_players, winner, is_tie, scores,
                               hands_won, is_perfect_game, num_players):
    try:
        if num_players == 3:
            _update_stats_3player(lobby_players, winner, is_tie, scores,
                                   hands_won, is_perfect_game)
        else:
            _update_stats_4player(lobby_players, winner, is_tie, scores,
                                   hands_won, is_perfect_game)
        db.session.commit()
        logger.info(f"Updated player statistics for lobby {lobby.code}")
    except Exception as e:
        logger.error(f"Error updating player statistics: {e}")
        db.session.rollback()


def _update_stats_3player(lobby_players, winner, is_tie, scores, hands_won, is_perfect_game):
    """Each player is strictly individual — no team grouping."""
    total_hands = sum(hands_won.values())

    if is_tie:
        for lp in lobby_players:
            s = _get_or_create_stats(lp.user_id)
            s.games_played += 1
            s.total_hands_played += total_hands
            s.current_lose_streak = 0
            s.last_updated = datetime.utcnow()
        return

    winner_score = scores[winner]
    loser_score_total = sum(scores[i] for i in range(3) if i != winner)

    for i, lp in enumerate(lobby_players):
        s = _get_or_create_stats(lp.user_id)
        s.games_played += 1
        s.total_hands_played += total_hands
        s.last_updated = datetime.utcnow()

        if i == winner:
            s.games_won += 1
            s.total_points_scored += winner_score
            s.total_points_conceded += loser_score_total
            s.current_win_streak += 1
            s.current_lose_streak = 0
            s.longest_win_streak = max(s.longest_win_streak, s.current_win_streak)
            if is_perfect_game:
                s.perfect_games += 1
        else:
            s.games_lost += 1
            s.total_points_scored += scores[i]
            s.total_points_conceded += winner_score
            s.current_lose_streak += 1
            s.current_win_streak = 0
            s.longest_lose_streak = max(s.longest_lose_streak, s.current_lose_streak)


def _update_stats_4player(lobby_players, winner, is_tie, scores, hands_won, is_perfect_game):
    """Team-based stats for 4-player (positions 0,2 = team 0; 1,3 = team 1)."""
    team0_ids = [lp.user_id for i, lp in enumerate(lobby_players) if i % 2 == 0]
    team1_ids = [lp.user_id for i, lp in enumerate(lobby_players) if i % 2 != 0]
    total_hands = sum(hands_won.values())

    if is_tie:
        for lp in lobby_players:
            s = _get_or_create_stats(lp.user_id)
            s.games_played += 1
            s.total_hands_played += total_hands
            s.current_lose_streak = 0
            s.last_updated = datetime.utcnow()
        return

    if winner == 0:
        winning_ids, losing_ids = team0_ids, team1_ids
        winning_score, losing_score = scores[0], scores[1]
        winning_hands, losing_hands = hands_won[0], hands_won[1]
    else:
        winning_ids, losing_ids = team1_ids, team0_ids
        winning_score, losing_score = scores[1], scores[0]
        winning_hands, losing_hands = hands_won[1], hands_won[0]

    was_comeback = losing_score > 0 and winning_score > losing_score

    for uid in winning_ids:
        s = _get_or_create_stats(uid)
        s.games_played += 1
        s.games_won += 1
        s.total_points_scored += winning_score
        s.total_points_conceded += losing_score
        s.total_hands_played += winning_hands + losing_hands
        s.current_win_streak += 1
        s.current_lose_streak = 0
        s.longest_win_streak = max(s.longest_win_streak, s.current_win_streak)
        if is_perfect_game:
            s.perfect_games += 1
        if was_comeback:
            s.comeback_wins += 1
        s.last_updated = datetime.utcnow()

    for uid in losing_ids:
        s = _get_or_create_stats(uid)
        s.games_played += 1
        s.games_lost += 1
        s.total_points_scored += losing_score
        s.total_points_conceded += winning_score
        s.total_hands_played += losing_hands + winning_hands
        s.current_lose_streak += 1
        s.current_win_streak = 0
        s.longest_lose_streak = max(s.longest_lose_streak, s.current_lose_streak)
        s.last_updated = datetime.utcnow()
