"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 2)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.CHAR(64), nullable=False),
        sa.Column("event_created_at", TS, nullable=True),
        sa.Column("received_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_webhook_events_account_id", "webhook_events", ["account_id"])
    op.create_index("ix_webhook_events_status", "webhook_events", ["status"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("opened_at", TS, nullable=True),
    )

    op.create_table(
        "fundings",
        sa.Column("event_id", sa.Text(), sa.ForeignKey("webhook_events.id"), primary_key=True),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_fundings_account_id", "fundings", ["account_id"])

    op.create_table(
        "authorizations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("merchant", sa.Text(), nullable=True),
        sa.Column("authorized_amount", MONEY, nullable=True),
        sa.Column("created_at", TS, nullable=True),
        sa.Column("captured_amount", MONEY, nullable=True),
        sa.Column("captured_at", TS, nullable=True),
        sa.Column("reversed_amount", MONEY, nullable=True),
        sa.Column("reversed_at", TS, nullable=True),
        sa.Column("first_seen_at", TS, nullable=False),
    )
    op.create_index("ix_authorizations_account_id", "authorizations", ["account_id"])

    op.create_table(
        "refunds",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("authorization_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("event_id", sa.Text(), sa.ForeignKey("webhook_events.id"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_refunds_authorization_id", "refunds", ["authorization_id"])
    op.create_index("ix_refunds_account_id", "refunds", ["account_id"])


def downgrade() -> None:
    op.drop_table("refunds")
    op.drop_table("authorizations")
    op.drop_table("fundings")
    op.drop_table("accounts")
    op.drop_table("webhook_events")
