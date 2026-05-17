"""add game_result and game_result_participant tables

Revision ID: 7a3b91cd02ef
Revises: 04c8dc5bd11d
Create Date: 2026-05-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7a3b91cd02ef'
down_revision = '04c8dc5bd11d'
branch_labels = None
depends_on = None


def upgrade():
    # Guard against db.create_all() having already created these tables
    # (happens on fresh installs where create_all runs before flask db upgrade).
    bind = op.get_bind()
    existing = sa.inspect(bind).get_table_names()

    if 'game_result' not in existing:
        op.create_table(
            'game_result',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('lobby_code', sa.String(length=6), nullable=False),
            sa.Column('num_players', sa.Integer(), nullable=False),
            sa.Column('winner', sa.Integer(), nullable=True),
            sa.Column('is_tie', sa.Boolean(), nullable=True),
            sa.Column('scores_json', sa.String(length=100), nullable=False),
            sa.Column('player_names_json', sa.String(length=300), nullable=False),
            sa.Column('played_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_game_result_lobby_code', 'game_result', ['lobby_code'])
        op.create_index('ix_game_result_played_at', 'game_result', ['played_at'])

    if 'game_result_participant' not in existing:
        op.create_table(
            'game_result_participant',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('game_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('won', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['game_id'], ['game_result.id']),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_table('game_result_participant')
    op.drop_index('ix_game_result_played_at', 'game_result')
    op.drop_index('ix_game_result_lobby_code', 'game_result')
    op.drop_table('game_result')
