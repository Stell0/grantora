from __future__ import annotations

import sys

from grantora.cli.demo_workflow import (
    HTTPGrantoraClient,
    WorkflowError,
    demo_seed_config_from_env,
    print_seed_result,
    seed_demo,
    write_demo_env,
)


def main() -> int:
    try:
        config = demo_seed_config_from_env()
        client = HTTPGrantoraClient(config.api_url, timeout_seconds=config.timeout_seconds)
        result = seed_demo(client, config)
        write_demo_env(config.output_env_path, result, config)
        print_seed_result(result, config)
    except WorkflowError as exc:
        print(f"demo-seed failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
