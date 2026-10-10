"""account aggregator: consents and consented statement rows, with data source and expiry

Revision ID: d5e8f1a2b3c4
Revises: c4d7e2f9a815
Create Date: 2026-10-11 01:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd5e8f1a2b3c4'
down_revision: str | Sequence[str] | None = 'c4d7e2f9a815'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('aa_consent',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('customer_id', sa.String(length=16), nullable=False),
    sa.Column('alert_id', sa.String(length=24), nullable=True),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('data_source', sa.String(length=16), nullable=False),
    sa.Column('provider_consent_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('date_from', sa.Date(), nullable=False),
    sa.Column('date_to', sa.Date(), nullable=False),
    sa.Column('created_by', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('data_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('redirect_url', sa.Text(), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rejected', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_aa_consent'))
    )
    op.create_index(op.f('ix_aa_consent_customer_id'), 'aa_consent', ['customer_id'], unique=False)
    op.create_table('aa_fi_txn',
    sa.Column('id', sa.String(length=24), nullable=False),
    sa.Column('consent_id', sa.String(length=40), nullable=False),
    sa.Column('customer_id', sa.String(length=16), nullable=False),
    sa.Column('fip_id', sa.String(length=40), nullable=False),
    sa.Column('masked_account', sa.String(length=32), nullable=False),
    sa.Column('txn_id', sa.String(length=64), nullable=False),
    sa.Column('txn_type', sa.String(length=8), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('amount_paise', sa.BigInteger(), nullable=False),
    sa.Column('balance_paise', sa.BigInteger(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('value_date', sa.Date(), nullable=True),
    sa.Column('narration', sa.String(length=200), nullable=False),
    sa.Column('reference', sa.String(length=200), nullable=False),
    sa.Column('data_source', sa.String(length=16), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['consent_id'], ['aa_consent.id'], name=op.f('fk_aa_fi_txn_consent_id_aa_consent'),
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_aa_fi_txn'))
    )
    op.create_index(op.f('ix_aa_fi_txn_consent_id'), 'aa_fi_txn', ['consent_id'], unique=False)
    op.create_index(op.f('ix_aa_fi_txn_customer_id'), 'aa_fi_txn', ['customer_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_aa_fi_txn_customer_id'), table_name='aa_fi_txn')
    op.drop_index(op.f('ix_aa_fi_txn_consent_id'), table_name='aa_fi_txn')
    op.drop_table('aa_fi_txn')
    op.drop_index(op.f('ix_aa_consent_customer_id'), table_name='aa_consent')
    op.drop_table('aa_consent')
