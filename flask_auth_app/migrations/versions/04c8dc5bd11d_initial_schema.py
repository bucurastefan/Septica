"""initial schema

Revision ID: 04c8dc5bd11d
Revises: 
Create Date: 2026-05-12 13:09:41.083153

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04c8dc5bd11d'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Drop legacy columns only if they exist (old installs had them, fresh ones don't)
    conn = op.get_bind()
    existing = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(lobby)"))}

    with op.batch_alter_table('lobby', schema=None) as batch_op:
        if 'team1_name' in existing:
            batch_op.drop_column('team1_name')
        if 'team2_name' in existing:
            batch_op.drop_column('team2_name')


def downgrade():
    pass
