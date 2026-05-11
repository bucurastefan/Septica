import random
import string
from datetime import datetime
from extensions import db


class Lobby(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)
    game_started = db.Column(db.Boolean, default=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    player_count_type = db.Column(db.Integer, default=4)

    team1_wins = db.Column(db.Integer, default=0)
    team2_wins = db.Column(db.Integer, default=0)
    team3_wins = db.Column(db.Integer, default=0)
    total_games_played = db.Column(db.Integer, default=0)
    next_game_multiplier = db.Column(db.Integer, default=1)

    owner = db.relationship('User', foreign_keys=[owner_id])
    players = db.relationship('LobbyPlayer', back_populates='lobby', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Lobby {self.code}>'

    @property
    def player_count(self):
        return len(self.players)

    @property
    def team1_players(self):
        return [p for p in self.players if p.team == 1]

    @property
    def team2_players(self):
        return [p for p in self.players if p.team == 2]

    @property
    def team3_players(self):
        return [p for p in self.players if p.team == 3]

    @property
    def unassigned_players(self):
        return [p for p in self.players if p.team == 0]

    @property
    def is_full(self):
        return self.player_count >= self.player_count_type

    @property
    def max_teams(self):
        return 3 if self.player_count_type == 3 else 2

    def get_next_starter_info(self):
        from game.logic import SepticaGame
        next_starter_position = SepticaGame.calculate_starting_player(
            self.total_games_played, self.player_count_type
        )
        ordered_players = get_ordered_players(self.id, self.player_count_type)

        if len(ordered_players) >= self.player_count_type:
            starter_player = ordered_players[next_starter_position]

            if self.player_count_type == 3:
                team_names = {0: 'Purple', 1: 'Black', 2: 'Green'}
                team_name = team_names.get(next_starter_position, 'Unknown')
                player_number = 1
            else:
                team_name = "Purple" if next_starter_position % 2 == 0 else "Black"
                player_number = 1 if next_starter_position < 2 else 2

            return {
                'username': starter_player.user.username,
                'position': next_starter_position,
                'team_name': team_name,
                'player_number': player_number,
                'can_show': True,
            }
        return {'can_show': False}

    def assign_team(self, user_id):
        player = LobbyPlayer.query.filter_by(lobby_id=self.id, user_id=user_id).first()
        if not player:
            return False

        if player.team != 0:
            return True

        team1_count = len(self.team1_players)
        team2_count = len(self.team2_players)
        team3_count = len(self.team3_players) if self.player_count_type == 3 else 0

        if self.player_count_type == 3:
            if team1_count == 0:
                player.team = 1
            elif team2_count == 0:
                player.team = 2
            elif team3_count == 0:
                player.team = 3
            else:
                return False
        else:
            if team1_count <= team2_count and team1_count < 2:
                player.team = 1
            elif team2_count < 2:
                player.team = 2
            else:
                return False

        return True


class LobbyPlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    team = db.Column(db.Integer, default=0)
    voted_reset_stats = db.Column(db.Boolean, default=False)

    lobby = db.relationship('Lobby', back_populates='players')
    user = db.relationship('User', back_populates='lobby_players')

    def __repr__(self):
        return f'<LobbyPlayer {self.user.username} in {self.lobby.code}, Team {self.team}>'


def generate_lobby_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Lobby.query.filter_by(code=code).first():
            return code


def get_ordered_players(lobby_id, player_count_type=4):
    """
    Return lobby players in seat order.

    4-player: interleaved by team — T1[0], T2[0], T1[1], T2[1]
              (positions 0,2 = Team Purple; positions 1,3 = Team Black)

    3-player: one player per team in team-number order — T1, T2, T3
              (positions 0, 1, 2 — each player is their own team)
    """
    if player_count_type == 3:
        t1 = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=1).first()
        t2 = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=2).first()
        t3 = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=3).first()
        return [p for p in [t1, t2, t3] if p is not None]

    team1 = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=1).order_by(LobbyPlayer.joined_at).all()
    team2 = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=2).order_by(LobbyPlayer.joined_at).all()
    ordered = []
    for i in range(2):
        if i < len(team1):
            ordered.append(team1[i])
        if i < len(team2):
            ordered.append(team2[i])
    return ordered
