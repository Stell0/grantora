from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from grantora.db.models import Capability

MAX_MCP_TOOL_NAME_LENGTH = 128
TOOL_NAME_HASH_LENGTH = 8


def build_mcp_tool_list(capabilities: Iterable[Capability]) -> dict[str, Any]:
    sorted_capabilities = sorted(capabilities, key=lambda capability: capability.id)
    tool_names = capability_tool_name_map(sorted_capabilities)
    return {
        "tools": [
            {
                "name": tool_names[capability.id],
                "description": capability.name,
                "inputSchema": deepcopy(capability.input_schema),
                "_meta": {
                    "grantora/capability_id": capability.id,
                    "grantora/invocation_path": f"/v1/invoke/{capability.id}",
                },
            }
            for capability in sorted_capabilities
        ]
    }


def capability_tool_name_map(capabilities: Iterable[Capability]) -> dict[str, str]:
    sorted_capabilities = sorted(capabilities, key=lambda capability: capability.id)
    base_names = {
        capability.id: capability_tool_name(capability.id) for capability in sorted_capabilities
    }
    base_name_counts = Counter(base_names.values())
    duplicate_base_names = {base_name for base_name, count in base_name_counts.items() if count > 1}

    used_names: set[str] = set()
    tool_names: dict[str, str] = {}
    for capability in sorted_capabilities:
        base_name = base_names[capability.id]
        if base_name in duplicate_base_names:
            tool_name = _hashed_tool_name(base_name, capability.id, used_names)
        else:
            tool_name = base_name
        used_names.add(tool_name)
        tool_names[capability.id] = tool_name
    return tool_names


def capability_tool_name(capability_id: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", capability_id).strip("_").lower()
    if not normalized:
        return "capability"
    if normalized[0].isdigit():
        return f"capability_{normalized}"
    return normalized


def _hashed_tool_name(base_name: str, capability_id: str, used_names: set[str]) -> str:
    digest = hashlib.sha256(capability_id.encode("utf-8")).hexdigest()
    hash_length = TOOL_NAME_HASH_LENGTH
    while hash_length <= len(digest):
        suffix = digest[:hash_length]
        max_base_length = MAX_MCP_TOOL_NAME_LENGTH - len(suffix) - 1
        trimmed_base_name = base_name[:max_base_length].rstrip("_") or "capability"
        tool_name = f"{trimmed_base_name}_{suffix}"
        if tool_name not in used_names:
            return tool_name
        hash_length += TOOL_NAME_HASH_LENGTH
    raise ValueError("could not generate a unique MCP tool name")
