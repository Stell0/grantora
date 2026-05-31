"""Seed default runtime permissions.

Revision ID: 202605310004
Revises: 202605310003
Create Date: 2026-05-31 13:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202605310004"
down_revision = "202605310003"
branch_labels = None
depends_on = None


DEFAULT_PERMISSIONS = {
    "capability.describe": "Describe capabilities",
    "capability.invoke.read_only": "Invoke read-only capabilities",
    "capability.invoke.side_effect": "Invoke side-effecting capabilities",
    "capability.invoke.destructive": "Invoke destructive capabilities",
}

permissions_table = sa.table(
    "permissions",
    sa.column("code", sa.String(length=128)),
    sa.column("description", sa.String(length=255)),
)


def upgrade() -> None:
    connection = op.get_bind()
    permission_codes = sorted(DEFAULT_PERMISSIONS)
    existing_codes = set(
        connection.execute(
            sa.select(permissions_table.c.code).where(
                permissions_table.c.code.in_(permission_codes)
            )
        ).scalars()
    )
    rows = [
        {"code": code, "description": DEFAULT_PERMISSIONS[code]}
        for code in permission_codes
        if code not in existing_codes
    ]
    if rows:
        op.bulk_insert(permissions_table, rows)


def downgrade() -> None:
    op.execute(
        permissions_table.delete().where(permissions_table.c.code.in_(sorted(DEFAULT_PERMISSIONS)))
    )
