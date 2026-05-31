# STRUCTURE.md

This file defines where Grantora code and operational assets belong. Do not invent new top-level locations without updating this map.

## Repository Layout

```text
grantora/
  PROJECT.md
  README.md
  AGENTS.md
  STRUCTURE.md
  PLAN.md
  CONTRACTS.md
  ADAPTERS.md
  SECURITY.md
  TESTING.md
  OPERATIONS.md
  .env.example
  docker-compose.yml
  pyproject.toml
  alembic.ini
  Makefile
  containers/
    grantora-api.Dockerfile
    apisix/
  migrations/
    versions/
  src/
    grantora/
  tests/
    unit/
    integration/
    e2e/
  docs/
```

Only the documentation and compose files are present at project start. The remaining paths are created as their milestones are implemented.

## Runtime Components

- `grantora-api`: FastAPI service for runtime API, admin API, invocation, audit, usage and APISIX reconciliation.
- `postgres`: source of truth for Grantora dynamic state.
- `apisix`: HTTP data-plane and edge gateway.
- `apisix-etcd`: APISIX runtime configuration backend.
- `mock-upstream-app`: optional test provider for adapter integration tests.

## Python Package Layout

```text
src/grantora/
  main.py                 FastAPI application factory and startup wiring
  config.py               environment-only static configuration
  logging.py              structured JSON logging setup
  api/                    FastAPI route modules
  auth/                   agent and admin authentication
  rbac/                   runtime RBAC and binding checks
  capabilities/           capability registry, discovery and invocation orchestration
  adapters/               application adapters
  secrets/                encryption, storage and secret resolution
  audit/                  audit event writes and queries
  usage/                  usage event writes and queries
  apisix/                 APISIX Admin API client and reconciler
  db/                     SQLAlchemy models, session and persistence helpers
  schemas/                Pydantic request and response models
  telemetry/              metrics, tracing and request IDs
  openapi/                filtered OpenAPI and future MCP tool descriptions
```

## API Modules

- `src/grantora/api/runtime.py`: `/v1/me`, `/v1/capabilities`, `/v1/invoke/{capability_id}`, `/v1/usage/me`.
- `src/grantora/api/admin.py`: `/v1/admin/*` management endpoints.
- `src/grantora/api/health.py`: `/healthz` and `/readyz`.
- `src/grantora/api/metrics.py`: `/metrics` when enabled.

## Database Ownership

- SQLAlchemy models live in `src/grantora/db/models/` or a clearly equivalent package under `src/grantora/db/`.
- Alembic migration scripts live in `migrations/versions/`.
- Database schema changes must update [CONTRACTS.md](CONTRACTS.md) before implementation.
- PostgreSQL owns dynamic state; APISIX and adapters must be treated as generated or external runtime state.

## Adapter Ownership

- Shared adapter contracts live in `src/grantora/adapters/base.py`.
- Provider adapters live in `src/grantora/adapters/{provider}.py`.
- Adapter-specific tests live in `tests/unit/adapters/` and `tests/integration/adapters/`.
- Adapter behavior must follow [ADAPTERS.md](ADAPTERS.md).

## APISIX Integration Flow

```text
PostgreSQL desired route state
  -> Grantora APISIX reconciler
  -> APISIX Admin API
  -> APISIX runtime config in etcd
  -> inbound requests routed to grantora-api
```

APISIX must not become the business authorization engine. Grantora API performs final authentication, delegation checks, capability authorization, secret lookup, audit and usage writes.

## Test Layout

- `tests/unit/`: pure logic tests for RBAC, tokens, schema validation, adapters and error mapping.
- `tests/integration/`: PostgreSQL, migrations, APISIX reconciliation, mock upstream calls and metrics.
- `tests/e2e/`: full request flow through APISIX into Grantora API.