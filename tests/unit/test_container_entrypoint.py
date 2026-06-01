from __future__ import annotations

import subprocess
from pathlib import Path

ENTRYPOINT = Path(__file__).parents[2] / "containers" / "grantora-api-entrypoint.sh"


def test_entrypoint_starts_requested_command() -> None:
    completed = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo app-started"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == "app-started\n"
