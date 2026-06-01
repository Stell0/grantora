from __future__ import annotations

import sys

from grantora.cli.backup_restore_workflow import (
    SubprocessCommandRunner,
    backup_restore_config_from_env,
    run_backup_restore_smoke,
)
from grantora.cli.demo_workflow import WorkflowError


def main() -> int:
    try:
        config = backup_restore_config_from_env()
        checks = run_backup_restore_smoke(SubprocessCommandRunner(), config)
        print(
            f"Backup and restore smoke completed against API {config.seed_config.api_url} "
            f"and runtime {config.runtime_url}"
        )
        for check in checks:
            print(f"ok {check.name}: {check.detail}")
    except WorkflowError as exc:
        print(f"backup-restore-smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
