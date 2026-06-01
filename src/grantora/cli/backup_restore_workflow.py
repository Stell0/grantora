from __future__ import annotations

import os
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from grantora.cli.demo_workflow import (
    DEFAULT_RUNTIME_URL,
    CheckReport,
    DemoSeedConfig,
    GrantoraClient,
    HTTPGrantoraClient,
    SmokeConfig,
    WorkflowError,
    _env,
    _float_env,
    demo_seed_config_from_env,
    run_smoke,
    seed_demo,
    write_demo_env,
)


class CommandRunner(Protocol):
    def run(
        self,
        command: tuple[str, ...],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class BackupRestoreSmokeConfig:
    seed_config: DemoSeedConfig
    runtime_url: str
    dump_path: Path
    compose_command: tuple[str, ...] = ("docker", "compose")
    timeout_seconds: float = 10.0
    startup_timeout_seconds: float = 60.0
    postgres_service: str = "postgres"
    postgres_user: str = "grantora"
    postgres_db: str = "grantora"
    api_service: str = "grantora-api"
    apisix_etcd_service: str = "apisix-etcd"
    apisix_service: str = "apisix"
    keep_dump: bool = False


class SubprocessCommandRunner:
    def run(
        self,
        command: tuple[str, ...],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
    ) -> None:
        stdin_handle = None
        stdout_handle = None
        try:
            if stdin_path is not None:
                stdin_handle = stdin_path.open("rb")
            if stdout_path is not None:
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                stdout_handle = stdout_path.open("wb")

            completed = subprocess.run(
                list(command),
                check=True,
                stdin=stdin_handle,
                stdout=stdout_handle or subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if stdout_handle is None and completed.stdout:
                return
        except FileNotFoundError as exc:
            raise WorkflowError(f"Command not found: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore").strip() if exc.stderr else ""
            detail = _format_command(command)
            if stderr:
                raise WorkflowError(f"Command failed: {detail}: {stderr}") from exc
            raise WorkflowError(f"Command failed: {detail}") from exc
        finally:
            if stdin_handle is not None:
                stdin_handle.close()
            if stdout_handle is not None:
                stdout_handle.close()


def backup_restore_config_from_env() -> BackupRestoreSmokeConfig:
    seed_config = demo_seed_config_from_env()
    runtime_url = _env(
        "GRANTORA_RUNTIME_URL",
        _env("GRANTORA_PUBLIC_BASE_URL", _env("APISIX_PUBLIC_URL", DEFAULT_RUNTIME_URL)),
    )
    compose_command = tuple(shlex.split(_env("GRANTORA_COMPOSE_COMMAND", "docker compose")))
    if not compose_command:
        raise WorkflowError("GRANTORA_COMPOSE_COMMAND must not be empty")

    return BackupRestoreSmokeConfig(
        seed_config=seed_config,
        runtime_url=runtime_url,
        dump_path=Path(_env("GRANTORA_BACKUP_RESTORE_DUMP_PATH", ".grantora-backup.dump")),
        compose_command=compose_command,
        timeout_seconds=_float_env("GRANTORA_WORKFLOW_TIMEOUT_SECONDS", 10.0),
        startup_timeout_seconds=_float_env("GRANTORA_BACKUP_RESTORE_STARTUP_TIMEOUT_SECONDS", 60.0),
        postgres_service=_env("GRANTORA_BACKUP_POSTGRES_SERVICE", "postgres"),
        postgres_user=_env("POSTGRES_USER", "grantora"),
        postgres_db=_env("POSTGRES_DB", "grantora"),
        api_service=_env("GRANTORA_BACKUP_API_SERVICE", "grantora-api"),
        apisix_etcd_service=_env("GRANTORA_BACKUP_APISIX_ETCD_SERVICE", "apisix-etcd"),
        apisix_service=_env("GRANTORA_BACKUP_APISIX_SERVICE", "apisix"),
        keep_dump=_bool_env("GRANTORA_KEEP_BACKUP_DUMP", False),
    )


def run_backup_restore_smoke(
    command_runner: CommandRunner,
    config: BackupRestoreSmokeConfig,
    *,
    client_factory: Callable[[str, float], GrantoraClient] | None = None,
) -> list[CheckReport]:
    resolved_client_factory = client_factory or _http_client_factory
    admin_client = resolved_client_factory(config.seed_config.api_url, config.timeout_seconds)
    seed_result = seed_demo(admin_client, config.seed_config)
    resolved_agent_token = seed_result.agent_token or config.seed_config.existing_agent_token
    if resolved_agent_token is None:
        raise WorkflowError(
            "Backup and restore smoke requires DEMO_AGENT_TOKEN when demo-seed "
            "reuses an existing agent."
        )

    write_demo_env(config.seed_config.output_env_path, seed_result, config.seed_config)
    config.dump_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        command_runner.run(_pg_dump_command(config), stdout_path=config.dump_path)
        command_runner.run((*config.compose_command, "down", "-v"))
        command_runner.run((*config.compose_command, "up", "-d", config.postgres_service))
        _wait_for_postgres(command_runner, config)
        command_runner.run(_pg_restore_command(config), stdin_path=config.dump_path)
        command_runner.run(
            (
                *config.compose_command,
                "up",
                "-d",
                config.api_service,
                config.apisix_etcd_service,
                config.apisix_service,
            )
        )

        restored_admin_client = resolved_client_factory(
            config.seed_config.api_url,
            config.timeout_seconds,
        )
        _wait_for_gateway_ready(restored_admin_client, config.startup_timeout_seconds)
        restored_admin_client.post(
            "/v1/admin/apisix/sync",
            token=config.seed_config.admin_token,
        )
        restored_runtime_client = resolved_client_factory(
            config.runtime_url,
            config.timeout_seconds,
        )
        smoke_config = SmokeConfig(
            api_url=config.seed_config.api_url,
            runtime_url=config.runtime_url,
            admin_token=config.seed_config.admin_token,
            agent_token=resolved_agent_token,
            user_external_id=config.seed_config.user_external_id,
            capability_id=seed_result.capability_id,
            timeout_seconds=config.timeout_seconds,
            invocation_input={"query": _env("DEMO_QUERY", "Mario"), "limit": 5},
        )
        return run_smoke(restored_admin_client, restored_runtime_client, smoke_config)
    finally:
        if not config.keep_dump and config.dump_path.exists():
            config.dump_path.unlink()


def _wait_for_postgres(command_runner: CommandRunner, config: BackupRestoreSmokeConfig) -> None:
    deadline = time.monotonic() + config.startup_timeout_seconds
    command = (
        *config.compose_command,
        "exec",
        "-T",
        config.postgres_service,
        "pg_isready",
        "-U",
        config.postgres_user,
        "-d",
        config.postgres_db,
    )
    last_error: WorkflowError | None = None
    while time.monotonic() < deadline:
        try:
            command_runner.run(command)
            return
        except WorkflowError as exc:
            last_error = exc
            time.sleep(1)
    if last_error is not None:
        raise WorkflowError(
            f"PostgreSQL did not become ready within {config.startup_timeout_seconds} seconds"
        ) from last_error
    raise WorkflowError(
        f"PostgreSQL did not become ready within {config.startup_timeout_seconds} seconds"
    )


def _wait_for_gateway_ready(client: GrantoraClient, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: WorkflowError | None = None
    while time.monotonic() < deadline:
        try:
            body = client.get("/readyz")
        except WorkflowError as exc:
            last_error = exc
            time.sleep(1)
            continue

        if body.get("status") == "ok" and body.get("checks", {}).get("database") == "ok":
            return
        time.sleep(1)

    if last_error is not None:
        raise WorkflowError(
            f"Grantora did not become ready within {timeout_seconds} seconds"
        ) from last_error
    raise WorkflowError(f"Grantora did not become ready within {timeout_seconds} seconds")


def _pg_dump_command(config: BackupRestoreSmokeConfig) -> tuple[str, ...]:
    return (
        *config.compose_command,
        "exec",
        "-T",
        config.postgres_service,
        "pg_dump",
        "-U",
        config.postgres_user,
        "-d",
        config.postgres_db,
        "--format=custom",
    )


def _pg_restore_command(config: BackupRestoreSmokeConfig) -> tuple[str, ...]:
    return (
        *config.compose_command,
        "exec",
        "-T",
        config.postgres_service,
        "pg_restore",
        "-U",
        config.postgres_user,
        "-d",
        config.postgres_db,
        "--clean",
        "--if-exists",
    )


def _http_client_factory(base_url: str, timeout_seconds: float) -> GrantoraClient:
    return HTTPGrantoraClient(base_url, timeout_seconds=timeout_seconds)


def _format_command(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise WorkflowError(f"{name} must be a boolean value")
