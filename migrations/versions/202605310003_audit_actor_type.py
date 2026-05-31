"""Add audit actor type.

Revision ID: 202605310003
Revises: 202605310002
Create Date: 2026-05-31 13:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202605310003"
down_revision = "202605310002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("actor_type", sa.String(length=32), server_default="agent", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "actor_type")
