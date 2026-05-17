import json
from datetime import datetime
from extensions import db


class GameResult(db.Model):
    __tablename__ = 'game_result'
    id = db.Column(db.Integer, primary_key=True)
    lobby_code = db.Column(db.String(6), nullable=False, index=True)
    num_players = db.Column(db.Integer, nullable=False)
    winner = db.Column(db.Integer, nullable=True)
    is_tie = db.Column(db.Boolean, default=False)
    scores_json = db.Column(db.String(100), nullable=False)
    player_names_json = db.Column(db.String(300), nullable=False)
    played_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    participants = db.relationship(
        'GameResultParticipant', backref='game', cascade='all, delete-orphan'
    )

    @property
    def scores(self):
        raw = json.loads(self.scores_json)
        # JSON keys are strings; convert back to int keys
        return {int(k): v for k, v in raw.items()}

    @property
    def player_names(self):
        return json.loads(self.player_names_json)

    def __repr__(self):
        return f'<GameResult {self.id} lobby={self.lobby_code} {self.num_players}p>'


class GameResultParticipant(db.Model):
    __tablename__ = 'game_result_participant'
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game_result.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    won = db.Column(db.Boolean, nullable=False)

    user = db.relationship('User')
