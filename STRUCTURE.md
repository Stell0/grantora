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
  .github/
    workflows/
  docker-compose.yml
  pyproject.toml
  Makefile
  containers/
    grantora-api.Dockerfile
    apisix/
  deploy/
    compose.production.yml
    production.env.example
  src/
    grantora/
  tests/
    unit/
    integration/
    e2e/
  docs/
    release.md
    ns8-packaging.md
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
  metrics.py              Prometheus metrics registry and recording helpers
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
  openapi/                filtered OpenAPI and MCP tool descriptions
  cli/                    local human workflow commands
```

## API Modules

- `src/grantora/api/runtime.py`: `/v1/me`, `/v1/capabilities`, `/v1/capabilities/openapi.json`, `/v1/mcp/tools`, `/v1/mcp/call`, `/v1/invoke/{capability_id}`, `/v1/usage/me`.
- `src/grantora/api/admin.py`: `/v1/admin/*` management endpoints.
- `src/grantora/api/health.py`: `/healthz` and `/readyz`.
- `src/grantora/main.py`: `/metrics` when enabled.

## Database Ownership

- SQLAlchemy models live in `src/grantora/db/models/` or a clearly equivalent package under `src/grantora/db/`.
- During development, database schema changes are made directly in SQLAlchemy models and created with `Base.metadata.create_all()` on fresh disposable state.
- Database schema changes must update [CONTRACTS.md](CONTRACTS.md) before or with implementation.
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
- `tests/integration/`: PostgreSQL schema bootstrap, APISIX reconciliation, mock upstream calls and metrics.
- `tests/e2e/`: full request flow through APISIX into Grantora API.

## Release And Deployment Assets

- `.github/workflows/tests.yml`: unit/lint CI and manually gated integration/e2e validation.
- `.github/workflows/security.yml`: dependency audit, SBOM and container vulnerability gates.
- `.github/workflows/release.yml`: versioned Grantora API image publishing and clean image smoke.
- `deploy/compose.production.yml`: standalone production compose example with APISIX as the only published service.
- `deploy/production.env.example`: non-secret production environment template.
- `docs/release.md`: release, production deployment, upgrade and checklist procedure.
- `docs/ns8-packaging.md`: NS8 module boundaries that preserve standalone operation.