"""revoked sessions: sign-out invalidates every token of that sign-in

Revision ID: e6b3a9c1d702
Revises: d5e8f1a2b3c4
Create Date: 2026-10-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6b3a9c1d702'
down_revision: str | Sequence[str] | None = 'd5e8f1a2b3c4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('revoked_session',
    sa.Column('sid', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('sid', name=op.f('pk_revoked_session'))
    )
    op.create_index(op.f('ix_revoked_session_expires_at'), 'revoked_session', ['expires_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_revoked_session_expires_at'), table_name='revoked_session')
    op.drop_table('revoked_session')
