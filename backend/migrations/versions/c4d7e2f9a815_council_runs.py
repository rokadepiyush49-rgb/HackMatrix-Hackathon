"""council runs: every Investigation Council run with its engine, model, trace, usage and coverage

Revision ID: c4d7e2f9a815
Revises: 9b2f4e6a1c03
Create Date: 2026-10-11 00:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4d7e2f9a815'
down_revision: str | Sequence[str] | None = '9b2f4e6a1c03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('council_run',
    sa.Column('id', sa.String(length=24), nullable=False),
    sa.Column('alert_id', sa.String(length=24), nullable=False),
    sa.Column('alert_key', sa.String(length=64), nullable=True),
    sa.Column('case_sha256', sa.String(length=64), nullable=True),
    sa.Column('requested_engine', sa.String(length=16), nullable=False),
    sa.Column('engine', sa.String(length=16), nullable=True),
    sa.Column('model', sa.String(length=64), nullable=True),
    sa.Column('prompt_version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('actor', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('coverage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_council_run'))
    )
    op.create_index(op.f('ix_council_run_alert_id'), 'council_run', ['alert_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_council_run_alert_id'), table_name='council_run')
    op.drop_table('council_run')
