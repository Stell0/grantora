from __future__ import annotations

import sys

from grantora.cli.demo_workflow import (
    HTTPGrantoraClient,
    WorkflowError,
    print_smoke_result,
    run_smoke,
    smoke_config_from_env,
)


def main() -> int:
    try:
        config = smoke_config_from_env()
        admin_client = HTTPGrantoraClient(config.api_url, timeout_seconds=config.timeout_seconds)
        runtime_client = HTTPGrantoraClient(
            config.runtime_url,
            timeout_seconds=config.timeout_seconds,
        )
        checks = run_smoke(admin_client, runtime_client, config)
        print_smoke_result(checks, config)
    except WorkflowError as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
