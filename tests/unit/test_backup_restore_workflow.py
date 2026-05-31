from __future__ import annotations

from pathlib import Path

from grantora.cli.backup_restore_workflow import BackupRestoreSmokeConfig, run_backup_restore_smoke
from grantora.cli.demo_workflow import CheckReport, DemoSeedConfig, DemoSeedResult


class RecordingCommandRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None, Path | None]] = []

    def run(
        self,
        command: tuple[str, ...],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
    ) -> None:
        self.calls.append((command, stdout_path, stdin_path))
        if stdout_path is not None:
            stdout_path.write_bytes(b"backup")
        if stdin_path is not None:
            assert stdin_path.read_bytes() == b"backup"


class RecordingClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.posts: list[tuple[str, str | None]] = []

    def get(self, path: str, *, token: str | None = None, query=None):
        if path == "/readyz":
            return {"status": "ok", "checks": {"database": "ok"}}
        return {}

    def post(self, path: str, *, token: str | None = None, payload=None):
        self.posts.append((path, token))
        if path == "/v1/admin/apisix/sync":
            return {"status": "ok", "checked_routes": 1, "changed_routes": 0}
        return {}


def test_backup_restore_workflow_runs_compose_sequence_and_restores_smoke(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = RecordingCommandRunner()
    admin_clients: list[RecordingClient] = []

    def fake_client_factory(base_url: str, timeout_seconds: float) -> RecordingClient:
        del timeout_seconds
        client = RecordingClient(base_url)
        if base_url == "http://api.test":
            admin_clients.append(client)
        return client

    seed_result = DemoSeedResult(
        reports=[],
        workspace_id="workspace-1",
        application_id="application-1",
        user_id="user-1",
        capability_id="mock.phonebook.search",
        role_id="role-1",
        agent_id="agent-1",
        binding_id="binding-1",
        secret_id="secret-1",
        agent_token="grt_agent_demo",
    )
    smoke_checks = [CheckReport("mock-invocation", "ok", "adapter returned status ok")]
    monkeypatch.setattr(
        "grantora.cli.backup_restore_workflow.seed_demo",
        lambda admin_client, config: seed_result,
    )
    monkeypatch.setattr(
        "grantora.cli.backup_restore_workflow.run_smoke",
        lambda admin_client, runtime_client, config: smoke_checks,
    )

    config = BackupRestoreSmokeConfig(
        seed_config=DemoSeedConfig(
            api_url="http://api.test",
            admin_token="admin-token",
            output_env_path=tmp_path / "demo.env",
        ),
        runtime_url="http://runtime.test",
        dump_path=tmp_path / "grantora.dump",
        startup_timeout_seconds=1,
    )

    checks = run_backup_restore_smoke(runner, config, client_factory=fake_client_factory)

    assert checks == smoke_checks
    assert [call[0] for call in runner.calls] == [
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "pg_dump",
            "-U",
            "grantora",
            "-d",
            "grantora",
            "--format=custom",
        ),
        ("docker", "compose", "down", "-v"),
        ("docker", "compose", "up", "-d", "postgres"),
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "pg_isready",
            "-U",
            "grantora",
            "-d",
            "grantora",
        ),
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "-U",
            "grantora",
            "-d",
            "grantora",
            "--clean",
            "--if-exists",
        ),
        ("docker", "compose", "up", "-d", "grantora-api", "apisix-etcd", "apisix"),
    ]
    assert admin_clients[-1].posts == [("/v1/admin/apisix/sync", "admin-token")]
    assert not config.dump_path.exists()


def test_backup_restore_workflow_can_keep_dump_file(tmp_path: Path, monkeypatch) -> None:
    runner = RecordingCommandRunner()
    monkeypatch.setattr(
        "grantora.cli.backup_restore_workflow.seed_demo",
        lambda admin_client, config: DemoSeedResult(
            reports=[],
            workspace_id="workspace-1",
            application_id="application-1",
            user_id="user-1",
            capability_id="mock.phonebook.search",
            role_id="role-1",
            agent_id="agent-1",
            binding_id="binding-1",
            secret_id="secret-1",
            agent_token="grt_agent_demo",
        ),
    )
    monkeypatch.setattr(
        "grantora.cli.backup_restore_workflow.run_smoke",
        lambda admin_client, runtime_client, config: [],
    )

    config = BackupRestoreSmokeConfig(
        seed_config=DemoSeedConfig(
            api_url="http://api.test",
            admin_token="admin-token",
            output_env_path=tmp_path / "demo.env",
        ),
        runtime_url="http://runtime.test",
        dump_path=tmp_path / "grantora.dump",
        startup_timeout_seconds=1,
        keep_dump=True,
    )

    run_backup_restore_smoke(
        runner,
        config,
        client_factory=lambda base_url, timeout_seconds: RecordingClient(base_url),
    )

    assert config.dump_path.exists()