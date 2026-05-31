# PLAN.md

This roadmap is the working build order for Grantora. Keep checkboxes current and add a test requirement to every new task.

## Milestone 0 - Repository Skeleton

- [x] Create `pyproject.toml` with FastAPI, SQLAlchemy or SQLModel, Alembic, Pydantic, httpx and prometheus dependencies. Test: dependency lock or install completes in a clean environment.
- [x] Create `src/grantora/main.py` with a FastAPI app factory. Test: app imports without side effects.
- [x] Add `/healthz` and `/readyz`. Test: local HTTP request returns 200 and JSON status.
- [x] Create PostgreSQL session wiring from `DATABASE_URL`. Test: integration check connects to local compose PostgreSQL.
- [x] Initialize Alembic migrations. Test: `alembic upgrade head` succeeds on an empty database.
- [x] Replace the compose bootstrap `grantora-api` command with the real FastAPI entrypoint. Test: `docker compose up --build` starts all required services.

## Milestone 1 - Core Data Model

- [x] Add workspace model. Test: create, read and active-status query.
- [x] Add application instance model. Test: lookup by workspace and slug.
- [x] Add agent model with token hash fields. Test: active agent lookup by token hash path.
- [x] Add user model. Test: lookup by workspace and external id.
- [x] Add capability model with JSONB input and output schemas. Test: active capability lookup by id and workspace.
- [x] Add role and permission models. Test: role grants expected runtime permission.
- [x] Add binding model. Test: binding lookup uses workspace, agent, user, capability and status.
- [x] Add secret metadata and encrypted value model. Test: secret is stored encrypted and not returned by default queries.
- [x] Add audit event model. Test: denied and successful decisions can be recorded.
- [x] Add usage event model. Test: successful, denied and error status events can be recorded.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 2 - Agent Authentication

- [x] Implement agent token creation. Test: generated token is returned only once.
- [x] Implement token hashing with pepper. Test: plaintext token is never persisted.
- [x] Authenticate `Authorization: Bearer` runtime requests. Test: missing, invalid, disabled and valid agents produce expected results.
- [x] Add `/v1/me`. Test: authenticated agent receives workspace and agent metadata without secrets.
- [x] Implement admin bootstrap authentication. Test: invalid admin token is denied and valid token can reach admin endpoints.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 3 - Capability Invocation

- [x] Add `GET /v1/capabilities`. Test: agent sees only capabilities allowed for the selected user.
- [x] Add `POST /v1/invoke/{capability_id}`. Test: valid request reaches adapter and returns normalized data.
- [x] Implement deny-by-default authorization. Test: no binding, wrong user, disabled agent and disabled capability are denied.
- [x] Validate capability input schema. Test: invalid input returns a safe validation error.
- [x] Resolve secrets according to the lookup order. Test: missing secret fails closed.
- [x] Write audit events for allow and deny decisions. Test: denied request is audited.
- [x] Write usage events for success, denied and error outcomes. Test: usage record includes workspace, agent, user, capability and latency.
- [x] Output git add and conventional commit commands.

## Milestone 4 - APISIX Integration

- [x] Add APISIX Admin API client. Test: client can create, update and read a route against local APISIX.
- [x] Add `apisix_routes` desired-state table. Test: route definition round-trips through PostgreSQL.
- [x] Implement idempotent route reconciliation. Test: running sync twice produces no second change.
- [x] Add baseline plugins for request IDs, Prometheus and rate limiting. Test: reconciled route contains required plugin config.
- [x] Add `/v1/admin/apisix/sync` and `/v1/admin/apisix/status`. Test: admin endpoint reports last sync status safely.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 5 - First Adapter

- [x] Add mock adapter. Test: invocation engine can call it without network access.
- [x] Add NethVoice phonebook adapter. Test: mock upstream response normalizes to the contact output schema.
- [x] Enforce result limit and safe field selection. Test: oversized upstream result is trimmed and sensitive fields are excluded.
- [x] Normalize upstream errors. Test: 401, 404, timeout and 5xx map to safe Grantora error codes.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 6 - MCP/OpenAPI Tool Description

- [x] Add static runtime OpenAPI route. Test: `/v1/openapi.json` returns the Grantora runtime API schema.
- [x] Add filtered capability OpenAPI. Test: agent/user pair sees only allowed capabilities.
- [x] Add MCP-compatible tool list generator. Test: generated tool names are stable and map back to capability ids.
- [x] Add contract tests for schema stability. Test: intentional API changes require fixture updates.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 7 - Observability And Hardening

- [x] Add Prometheus metrics. Test: `/metrics` exposes request, authorization, upstream, secret and APISIX sync counters.
- [x] Add structured JSON logs. Test: logs include request id and omit secrets and authorization headers.
- [x] Add secret rotation behavior. Test: revoked secret is not selected for invocation.
- [x] Add timeout and payload size enforcement. Test: slow and oversized upstream responses fail safely.
- [x] Document backup and restore procedure. Test: restore into a clean local environment recreates Grantora dynamic state.
- [x] output git commands to add files and commit changes using a conventional commit