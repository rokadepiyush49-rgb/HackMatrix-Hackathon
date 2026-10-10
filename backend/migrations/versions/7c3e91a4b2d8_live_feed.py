"""live feed: source rows held back for the end-to-end demo

Revision ID: 7c3e91a4b2d8
Revises: 60f0fd2f94a1
Create Date: 2026-10-04 11:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7c3e91a4b2d8'
down_revision: str | Sequence[str] | None = '60f0fd2f94a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('feed_event',
    sa.Column('seq', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('t', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_table', sa.String(length=24), nullable=False),
    sa.Column('ref', sa.String(length=24), nullable=False),
    sa.Column('system', sa.String(length=40), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('row', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('effect', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('strand', sa.String(length=12), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('seq', name=op.f('pk_feed_event'))
    )
    op.create_index(op.f('ix_feed_event_ref'), 'feed_event', ['ref'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_feed_event_ref'), table_name='feed_event')
    op.drop_table('feed_event')
