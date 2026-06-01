from __future__ import annotations

import os

import pytest

from grantora.cli.backup_restore_workflow import (
    SubprocessCommandRunner,
    backup_restore_config_from_env,
    run_backup_restore_smoke,
)

pytestmark = pytest.mark.e2e


def test_backup_restore_smoke_round_trip_restores_runtime_invocation() -> None:
    if os.environ.get("GRANTORA_RUN_BACKUP_RESTORE_SMOKE") != "1":
        pytest.skip(
            "Set GRANTORA_RUN_BACKUP_RESTORE_SMOKE=1 to run the destructive "
            "backup/restore smoke test."
        )
    if not os.environ.get("ADMIN_BOOTSTRAP_TOKEN"):
        pytest.skip("Set ADMIN_BOOTSTRAP_TOKEN to run the destructive backup/restore smoke test.")

    checks = run_backup_restore_smoke(
        SubprocessCommandRunner(),
        backup_restore_config_from_env(),
    )

    assert any(check.name == "mock-invocation" and check.status == "ok" for check in checks)
