"""Add APISIX integration state.

Revision ID: 202605310002
Revises: 202605310001
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202605310002"
down_revision = "202605310001"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "apisix_routes",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("uri", sa.String(length=2048), nullable=False),
        sa.Column("upstream", JSON_DOCUMENT, nullable=False),
        sa.Column("plugins", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_apisix_routes_status", "apisix_routes", ["status"], unique=False)

    op.create_table(
        "apisix_sync_status",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_routes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("changed_routes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("safe_message", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("apisix_sync_status")
    op.drop_index("idx_apisix_routes_status", table_name="apisix_routes")
    op.drop_table("apisix_routes")
