from __future__ import annotations

import argparse
import json
import sys

from grantora.config import Settings
from grantora.db import Database
from grantora.retention import purge_expired_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune expired audit and usage records.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would be pruned without deleting them.",
    )
    args = parser.parse_args(argv)

    settings = Settings()
    database = Database(settings)
    try:
        with database.session_factory() as session:
            result = purge_expired_events(session, settings, dry_run=args.dry_run)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
    except Exception as exc:
        print(f"retention failed: {exc}", file=sys.stderr)
        return 1
    finally:
        database.dispose()

    print(
        json.dumps(
            {
                "dry_run": result.dry_run,
                "audit_deleted": result.audit_deleted,
                "usage_deleted": result.usage_deleted,
                "audit_cutoff": result.audit_cutoff.isoformat(),
                "usage_cutoff": result.usage_cutoff.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())