"""Initial schema.

Revision ID: 202605310001
Revises:
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202605310001"
down_revision = None
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_workspaces_slug"), "workspaces", ["slug"], unique=False)

    op.create_table(
        "application_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_application_instances_workspace_slug"),
    )
    op.create_index(
        "idx_application_instances_workspace_slug",
        "application_instances",
        ["workspace_id", "slug", "status"],
        unique=False,
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("token_hash_algorithm", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
    )
    op.create_index(
        "idx_agents_token_hash_status", "agents", ["token_hash", "status"], unique=False
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "external_id", name="uq_users_workspace_external_id"),
    )
    op.create_index(
        "idx_users_workspace_external_status",
        "users",
        ["workspace_id", "external_id", "status"],
        unique=False,
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_roles_workspace_slug"),
    )
    op.create_index(
        "idx_roles_workspace_slug_status",
        "roles",
        ["workspace_id", "slug", "status"],
        unique=False,
    )

    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )

    op.create_table(
        "capabilities",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("application_instance_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("risk_class", sa.String(length=32), nullable=False),
        sa.Column("input_schema", JSON_DOCUMENT, nullable=False),
        sa.Column("output_schema", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["application_instance_id"], ["application_instances.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_capabilities_workspace_status",
        "capabilities",
        ["workspace_id", "status"],
        unique=False,
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["permission_code"], ["permissions.code"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("role_id", "permission_code"),
    )

    op.create_table(
        "bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_bindings_lookup",
        "bindings",
        ["workspace_id", "agent_id", "user_id", "capability_id", "status"],
        unique=False,
    )

    op.create_table(
        "secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("application_instance_id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("secret_type", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.ForeignKeyConstraint(["application_instance_id"], ["application_instances.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_secrets_lookup",
        "secrets",
        ["workspace_id", "application_instance_id", "owner_type", "owner_id", "status"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.String(length=128), nullable=True),
        sa.Column("application_instance_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("remote_addr", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["application_instance_id"], ["application_instances.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_audit_workspace_time", "audit_events", ["workspace_id", "timestamp"], unique=False
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("application_instance_id", sa.Uuid(), nullable=True),
        sa.Column("units", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["application_instance_id"], ["application_instances.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_usage_workspace_time", "usage_events", ["workspace_id", "timestamp"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_usage_workspace_time", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("idx_audit_workspace_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("idx_secrets_lookup", table_name="secrets")
    op.drop_table("secrets")
    op.drop_index("idx_bindings_lookup", table_name="bindings")
    op.drop_table("bindings")
    op.drop_table("role_permissions")
    op.drop_index("idx_capabilities_workspace_status", table_name="capabilities")
    op.drop_table("capabilities")
    op.drop_table("permissions")
    op.drop_index("idx_roles_workspace_slug_status", table_name="roles")
    op.drop_table("roles")
    op.drop_index("idx_users_workspace_external_status", table_name="users")
    op.drop_table("users")
    op.drop_index("idx_agents_token_hash_status", table_name="agents")
    op.drop_table("agents")
    op.drop_index("idx_application_instances_workspace_slug", table_name="application_instances")
    op.drop_table("application_instances")
    op.drop_index(op.f("ix_workspaces_slug"), table_name="workspaces")
    op.drop_table("workspaces")
