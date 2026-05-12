from datetime import datetime
from extensions import db


class PlayerStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)

    # ── 4-player stats ──────────────────────────────────────────────────────
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    games_lost = db.Column(db.Integer, default=0)
    total_points_scored = db.Column(db.Integer, default=0)
    total_points_conceded = db.Column(db.Integer, default=0)
    longest_win_streak = db.Column(db.Integer, default=0)
    current_win_streak = db.Column(db.Integer, default=0)
    longest_lose_streak = db.Column(db.Integer, default=0)
    current_lose_streak = db.Column(db.Integer, default=0)
    total_hands_played = db.Column(db.Integer, default=0)
    perfect_games = db.Column(db.Integer, default=0)
    comeback_wins = db.Column(db.Integer, default=0)

    # ── 3-player stats ──────────────────────────────────────────────────────
    games_played_3p = db.Column(db.Integer, default=0)
    games_won_3p = db.Column(db.Integer, default=0)
    games_lost_3p = db.Column(db.Integer, default=0)
    total_points_scored_3p = db.Column(db.Integer, default=0)
    total_points_conceded_3p = db.Column(db.Integer, default=0)
    longest_win_streak_3p = db.Column(db.Integer, default=0)
    current_win_streak_3p = db.Column(db.Integer, default=0)
    longest_lose_streak_3p = db.Column(db.Integer, default=0)
    current_lose_streak_3p = db.Column(db.Integer, default=0)
    total_hands_played_3p = db.Column(db.Integer, default=0)
    perfect_games_3p = db.Column(db.Integer, default=0)

    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('stats', uselist=False))

    def __repr__(self):
        return f'<PlayerStats for {self.user.username}: {self.games_won}/{self.games_played}>'

    # ── 4-player computed ───────────────────────────────────────────────────
    @property
    def win_rate(self):
        if self.games_played == 0:
            return 0.0
        return round((self.games_won / self.games_played) * 100, 2)

    @property
    def loss_rate(self):
        if self.games_played == 0:
            return 0.0
        return round((self.games_lost / self.games_played) * 100, 2)

    @property
    def average_points_per_game(self):
        if self.games_played == 0:
            return 0.0
        return round(self.total_points_scored / self.games_played, 2)

    @property
    def average_points_conceded_per_game(self):
        if self.games_played == 0:
            return 0.0
        return round(self.total_points_conceded / self.games_played, 2)

    @property
    def point_differential(self):
        return self.total_points_scored - self.total_points_conceded

    # ── 3-player computed ───────────────────────────────────────────────────
    @property
    def win_rate_3p(self):
        if self.games_played_3p == 0:
            return 0.0
        return round((self.games_won_3p / self.games_played_3p) * 100, 2)

    @property
    def average_points_per_game_3p(self):
        if self.games_played_3p == 0:
            return 0.0
        return round(self.total_points_scored_3p / self.games_played_3p, 2)

    @property
    def average_points_conceded_per_game_3p(self):
        if self.games_played_3p == 0:
            return 0.0
        return round(self.total_points_conceded_3p / self.games_played_3p, 2)

    @property
    def point_differential_3p(self):
        return self.total_points_scored_3p - self.total_points_conceded_3p
