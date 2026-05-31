#!/bin/sh
set -eu

case "${MIGRATIONS_AUTO_RUN:-false}" in
    true|TRUE|1|yes|YES|on|ON)
        echo "Running database migrations"
        python -m alembic upgrade head
        ;;
    false|FALSE|0|no|NO|off|OFF|"")
        echo "Skipping database migrations"
        ;;
    *)
        echo "Invalid MIGRATIONS_AUTO_RUN value: ${MIGRATIONS_AUTO_RUN}" >&2
        exit 64
        ;;
esac

exec "$@"
