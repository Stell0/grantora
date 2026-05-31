from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from grantora.auth import TOKEN_HASH_ALGORITHM, hash_token
from grantora.cli.retention import main as retention_main
from grantora.config import Settings
from grantora.db import Base, Database
from grantora.db.models import Agent, AuditEvent, UsageEvent, Workspace
from grantora.retention import purge_expired_events


def test_purge_expired_events_removes_rows_older_than_retention(tmp_path: Path) -> None:
    database = create_database(tmp_path)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
        audit_retention_days=30,
        usage_retention_days=7,
    )
    workspace_id, agent_id = seed_workspace_and_agent(database, settings)
    reference_time = datetime(2026, 5, 31, tzinfo=UTC)

    with database.session_factory() as session:
        session.add_all(
            [
                AuditEvent(
                    request_id="req_old_audit",
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    actor_type="agent",
                    decision="allow",
                    outcome="success",
                    latency_ms=10,
                    timestamp=reference_time - timedelta(days=31),
                ),
                AuditEvent(
                    request_id="req_new_audit",
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    actor_type="agent",
                    decision="allow",
                    outcome="success",
                    latency_ms=12,
                    timestamp=reference_time - timedelta(days=5),
                ),
                UsageEvent(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    capability_id="mock.phonebook.search",
                    status="success",
                    latency_ms=15,
                    timestamp=reference_time - timedelta(days=8),
                ),
                UsageEvent(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    capability_id="mock.phonebook.search",
                    status="success",
                    latency_ms=16,
                    timestamp=reference_time - timedelta(days=2),
                ),
            ]
        )
        session.commit()

    with database.session_factory() as session:
        result = purge_expired_events(session, settings, reference_time=reference_time)
        session.commit()

    assert result.audit_deleted == 1
    assert result.usage_deleted == 1

    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 1

    database.dispose()


def test_retention_cli_dry_run_reports_prunable_rows_without_deleting_them(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    database_path = tmp_path / "grantora.sqlite"
    database = create_database(tmp_path)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{database_path}",
        environment="test",
        audit_retention_days=14,
        usage_retention_days=14,
    )
    workspace_id, agent_id = seed_workspace_and_agent(database, settings)
    reference_time = datetime.now(UTC)

    with database.session_factory() as session:
        session.add(
            AuditEvent(
                request_id="req_old_cli",
                workspace_id=workspace_id,
                agent_id=agent_id,
                actor_type="agent",
                decision="deny",
                outcome="error",
                error_code="capability_denied",
                latency_ms=8,
                timestamp=reference_time - timedelta(days=30),
            )
        )
        session.commit()

    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "14")
    monkeypatch.setenv("USAGE_RETENTION_DAYS", "14")

    exit_code = retention_main(["--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["audit_deleted"] == 1
    assert payload["usage_deleted"] == 0

    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1

    database.dispose()


def create_database(tmp_path: Path) -> Database:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    return database


def seed_workspace_and_agent(database: Database, settings: Settings) -> tuple[object, object]:
    with database.session_factory() as session:
        workspace = Workspace(slug="demo", display_name="Demo")
        session.add(workspace)
        session.flush()
        agent = Agent(
            workspace_id=workspace.id,
            slug="retention-agent",
            display_name="Retention Agent",
            token_hash=hash_token("retention-token", settings.agent_token_pepper),
            token_hash_algorithm=TOKEN_HASH_ALGORITHM,
        )
        session.add(agent)
        session.commit()
        return workspace.id, agent.id