from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from grantora.config import Settings

SENSITIVE_LOG_KEYS = ("authorization", "cookie", "password", "secret", "token")


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "request_id",
            "trace_id",
            "span_id",
            "workspace_id",
            "agent_id",
            "user_id",
            "capability_id",
            "provider_type",
            "decision",
            "outcome",
            "usage_status",
            "error_code",
            "method",
            "path",
            "status_code",
            "duration_ms",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    level = logging.getLevelName(settings.log_level.upper())
    if not isinstance(level, int):
        level = logging.INFO

    formatter: logging.Formatter
    if settings.json_logs:
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())
    for handler in root_logger.handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
