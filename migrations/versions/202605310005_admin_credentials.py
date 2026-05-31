"""Add DB-backed admin credentials.

Revision ID: 202605310005
Revises: 202605310004
Create Date: 2026-05-31 16:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202605310005"
down_revision = "202605310004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("token_hash_algorithm", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject", name="uq_admin_credentials_subject"),
        sa.UniqueConstraint("token_hash", name="uq_admin_credentials_token_hash"),
    )
    op.create_index(
        "idx_admin_credentials_token_hash_status",
        "admin_credentials",
        ["token_hash", "status"],
        unique=False,
    )
    op.create_index(
        "idx_admin_credentials_workspace_status",
        "admin_credentials",
        ["workspace_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_admin_credentials_workspace_status", table_name="admin_credentials")
    op.drop_index("idx_admin_credentials_token_hash_status", table_name="admin_credentials")
    op.drop_table("admin_credentials")
