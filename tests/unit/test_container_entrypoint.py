from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENTRYPOINT = Path(__file__).parents[2] / "containers" / "grantora-api-entrypoint.sh"


def test_entrypoint_runs_migrations_when_auto_run_is_enabled(tmp_path: Path) -> None:
    env, log_path = entrypoint_env(tmp_path, migrations_auto_run="true")

    completed = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo app-started"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "Running database migrations" in completed.stdout
    assert "app-started" in completed.stdout
    assert log_path.read_text(encoding="utf-8") == "-m alembic upgrade head\n"


def test_entrypoint_skips_migrations_when_auto_run_is_disabled(tmp_path: Path) -> None:
    env, log_path = entrypoint_env(tmp_path, migrations_auto_run="false")

    completed = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo app-started"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "Skipping database migrations" in completed.stdout
    assert "app-started" in completed.stdout
    assert not log_path.exists()


def test_entrypoint_rejects_invalid_auto_run_value(tmp_path: Path) -> None:
    env, _log_path = entrypoint_env(tmp_path, migrations_auto_run="sometimes")

    completed = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo app-started"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 64
    assert "Invalid MIGRATIONS_AUTO_RUN value: sometimes" in completed.stderr
    assert "app-started" not in completed.stdout


def entrypoint_env(tmp_path: Path, *, migrations_auto_run: str) -> tuple[dict[str, str], Path]:
    log_path = tmp_path / "python-calls.log"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        '#!/bin/sh\necho "$@" >> "$ENTRYPOINT_LOG"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "ENTRYPOINT_LOG": str(log_path),
            "MIGRATIONS_AUTO_RUN": migrations_auto_run,
            "PATH": f"{tmp_path}:{env['PATH']}",
        }
    )
    return env, log_path
