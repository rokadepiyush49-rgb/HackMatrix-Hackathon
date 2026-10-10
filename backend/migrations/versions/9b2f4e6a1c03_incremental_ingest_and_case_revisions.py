"""incremental ingest (delivery receipts, arrival time, content hash) and append-only case revisions

Revision ID: 9b2f4e6a1c03
Revises: 7c3e91a4b2d8
Create Date: 2026-10-10 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9b2f4e6a1c03'
down_revision: str | Sequence[str] | None = '7c3e91a4b2d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('feed_event', sa.Column('content_sha256', sa.String(length=64), nullable=True))
    op.add_column('feed_event', sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('feed_event', sa.Column('late_by_s', sa.Integer(), nullable=True))

    op.create_table('feed_receipt',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('seq', sa.Integer(), nullable=True),
    sa.Column('ref', sa.String(length=24), nullable=False),
    sa.Column('source_table', sa.String(length=24), nullable=False),
    sa.Column('event_t', sa.DateTime(timezone=True), nullable=False),
    sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('outcome', sa.String(length=12), nullable=False),
    sa.Column('late', sa.Boolean(), nullable=False),
    sa.Column('late_by_s', sa.Integer(), nullable=True),
    sa.Column('effect', sa.String(length=12), nullable=True),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feed_receipt'))
    )
    op.create_index(op.f('ix_feed_receipt_ref'), 'feed_receipt', ['ref'], unique=False)
    op.create_index(op.f('ix_feed_receipt_run_id'), 'feed_receipt', ['run_id'], unique=False)

    op.create_table('case_revision',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('alert_key', sa.String(length=64), nullable=False),
    sa.Column('alert_id', sa.String(length=24), nullable=False),
    sa.Column('rev', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('snapshot_sha256', sa.String(length=64), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('trigger', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_case_revision')),
    sa.UniqueConstraint('alert_key', 'rev', name=op.f('uq_case_revision_alert_key_rev'))
    )
    op.create_index(op.f('ix_case_revision_alert_id'), 'case_revision', ['alert_id'], unique=False)
    op.create_index(op.f('ix_case_revision_run_id'), 'case_revision', ['run_id'], unique=False)
    # Earlier case states are evidence of how a case developed: the database refuses to change them.
    op.execute("""
        CREATE FUNCTION case_revision_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'case_revision is append-only';
        END $$;
        CREATE TRIGGER case_revision_append_only BEFORE UPDATE OR DELETE ON case_revision
            FOR EACH ROW EXECUTE FUNCTION case_revision_append_only();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS case_revision_append_only ON case_revision")
    op.execute("DROP FUNCTION IF EXISTS case_revision_append_only()")
    op.drop_index(op.f('ix_case_revision_run_id'), table_name='case_revision')
    op.drop_index(op.f('ix_case_revision_alert_id'), table_name='case_revision')
    op.drop_table('case_revision')
    op.drop_index(op.f('ix_feed_receipt_run_id'), table_name='feed_receipt')
    op.drop_index(op.f('ix_feed_receipt_ref'), table_name='feed_receipt')
    op.drop_table('feed_receipt')
    op.drop_column('feed_event', 'late_by_s')
    op.drop_column('feed_event', 'arrived_at')
    op.drop_column('feed_event', 'content_sha256')
