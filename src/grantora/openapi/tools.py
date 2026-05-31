from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from grantora.db.models import Capability


def build_mcp_tool_list(capabilities: Iterable[Capability]) -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": capability_tool_name(capability.id),
                "description": capability.name,
                "inputSchema": deepcopy(capability.input_schema),
                "_meta": {
                    "grantora/capability_id": capability.id,
                    "grantora/invocation_path": f"/v1/invoke/{capability.id}",
                },
            }
            for capability in sorted(capabilities, key=lambda capability: capability.id)
        ]
    }


def capability_tool_name(capability_id: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", capability_id).strip("_").lower()
    if not normalized:
        return "capability"
    if normalized[0].isdigit():
        return f"capability_{normalized}"
    return normalized
