# PLAN.md

This is the living plan for taking Grantora from the current implemented gateway MVP to a complete standalone product. Keep checkboxes current. Every implementation task must include a test requirement. Public API, database, adapter, audit, usage, error-shape and APISIX route changes must update `CONTRACTS.md` before code changes.

## Planning Rules

- PostgreSQL remains the source of truth for all dynamic state.
- Static configuration comes from environment variables only.
- APISIX is the HTTP data-plane, but Grantora performs business authorization.
- Capability authorization is deny-by-default.
- Agents never receive upstream secrets or raw upstream API access.
- Every runtime invocation attempt must produce audit and usage records, including denials.
- Safe errors must not leak tokens, internal URLs, stack traces or upstream response bodies.
- Tests must start narrow, then expand to integration and end-to-end checks before release.

## Current Version Snapshot

Assessed on 2026-05-31 against `src/grantora/`, `tests/unit/`, `CONTRACTS.md`, `OPERATIONS.md`, `.env.example` and `docker-compose.yml`.

### Implemented Baseline

- [x] FastAPI app factory, health endpoints, request IDs, safe error response shape and optional `/metrics`. Test: `tests/unit/test_app.py` and `tests/unit/test_health.py`.
- [x] SQLAlchemy models and Alembic migrations for workspaces, applications, agents, users, capabilities, roles, permissions, bindings, secrets, audit events, usage events and APISIX sync state. Test: `tests/unit/test_models.py`.
- [x] Agent bearer token hashing and runtime authentication. Test: `tests/unit/test_tokens.py` and `tests/unit/test_auth_api.py`.
- [x] Admin bootstrap authentication plus `POST /v1/admin/agents`, `GET /v1/admin/agents`, `POST /v1/admin/apisix/sync` and `GET /v1/admin/apisix/status`. Test: `tests/unit/test_auth_api.py` and `tests/unit/test_admin_apisix_api.py`.
- [x] Runtime `GET /v1/me`, `GET /v1/capabilities`, `GET /v1/openapi.json`, `GET /v1/capabilities/openapi.json` and `POST /v1/invoke/{capability_id}`. Test: `tests/unit/test_runtime_capabilities.py`.
- [x] Runtime deny-by-default checks for active workspace, agent, user, capability, binding and role permission. Test: runtime capability tests for allowed, denied and disabled capability paths.
- [x] Secret encryption and active-secret resolution for user and workspace/system ownership paths. Test: `tests/unit/test_models.py` and runtime secret tests.
- [x] Audit and usage writes for runtime invocation success, denial and adapter error paths. Test: runtime capability tests.
- [x] Adapter protocol, mock adapter and NethVoice phonebook adapter with normalization, limit enforcement, timeout, oversized payload and safe upstream error mapping. Test: `tests/unit/test_adapters.py`.
- [x] APISIX Admin API client, desired runtime route table, baseline plugins and idempotent reconciliation. Test: `tests/unit/test_apisix_client.py`, `tests/unit/test_apisix_reconciler.py` and `tests/unit/test_admin_apisix_api.py`.
- [x] Static runtime OpenAPI, filtered capability OpenAPI and internal MCP-compatible tool list generation. Test: fixture contract tests in `tests/unit/fixtures/`.
- [x] Dynamic Admin API endpoints for workspaces, applications, users, capabilities, permissions, roles, bindings, secrets, audit and usage, with admin audit writes for security-relevant mutations. Test: `tests/unit/test_admin_dynamic_api.py` and `tests/unit/fixtures/admin_response_contract.json`.
- [x] Local compose file for `grantora-api`, PostgreSQL, APISIX and APISIX etcd. Test: compose startup remains a required manual/integration check.

### Confirmed Gaps

- [x] `GET /v1/usage/me` is contracted in `STRUCTURE.md` and `CONTRACTS.md` and implemented for authenticated agent scope. Test: runtime usage summary tests for authenticated agent scope.
- [x] `tests/integration/` and `tests/e2e/` flows cover PostgreSQL, APISIX and full-through-APISIX suites. Test: env-gated integration/e2e tiers skip when infrastructure variables are absent and fail when configured infrastructure is broken.
- [ ] Compose exposes settings such as `MIGRATIONS_AUTO_RUN`, `APISIX_SYNC_ENABLED`, `APISIX_SYNC_INTERVAL_SECONDS`, `APISIX_FAIL_CLOSED`, retention values and feature flags that are not fully wired in code. Test: settings contract tests document which variables are active and which are reserved.
- [x] The Docker image runs Alembic migrations before Uvicorn when `MIGRATIONS_AUTO_RUN=true`. Test: entrypoint tests cover enabled, disabled and invalid values.
- [ ] `.env.example` contains future variables not present in `Settings`. Test: environment reference test or docs check keeps `.env.example`, `Settings` and this plan aligned.
- [x] The bootstrap path is packaged as `make demo-seed` plus `make smoke` through compose and APISIX. Test: workflow and smoke unit tests cover idempotent seeding and failing checks; full compose remains a manual/e2e check.
- [x] NethVoice phonebook and Nextcloud files search are implemented as real adapters. Test: each real adapter has unit normalization/error mapping tests and integration tests with mock upstream transports.
- [ ] MCP tool listing is an internal generator only. Test: expose and verify the final agent-facing MCP transport or endpoint selected for product use.
- [ ] No production CI, release packaging, image publishing, SBOM, dependency scan or NS8 module packaging is defined yet. Test: release pipeline creates reproducible artifacts and runs all gates.

## Full Software Definition

Grantora is considered complete when a human administrator can deploy it, configure it, create all dynamic objects through supported admin surfaces, connect at least the first real business applications, give an agent a token, let that agent discover and invoke only authorized capabilities through APISIX, and inspect audit, usage, logs and metrics without direct database edits.

Completion requires:

- A complete Admin API for all dynamic state.
- A documented and executable bootstrap path.
- Runtime capability discovery, invocation, filtered OpenAPI and MCP-compatible tool discovery.
- Production-grade APISIX reconciliation and fail-closed behavior.
- At least NethVoice plus one additional business adapter, with clear adapter extension docs.
- Integration and end-to-end tests using PostgreSQL, APISIX and mock upstreams.
- Human operations docs for configuration, backup, restore, upgrades, rotation and troubleshooting.
- Release packaging that remains standalone and can later be managed by an NS8 module.

## Roadmap

## Milestone 8 - Complete Dynamic Admin API

Goal: make Grantora fully configurable without direct database inserts.

- [x] Add `POST /v1/admin/workspaces` and `GET /v1/admin/workspaces` with active/disabled status handling. Test: create, conflict, list, disabled filtering and safe error response tests.
- [x] Add `POST /v1/admin/applications` and `GET /v1/admin/applications` with workspace ownership validation. Test: missing workspace, duplicate slug, list by workspace and no secret/base-url leakage beyond intended fields.
- [x] Add `POST /v1/admin/users` and `GET /v1/admin/users` even though the original contract omitted them from the required endpoint list; users are required for curl-only bootstrap. Test: create/list by workspace, duplicate external id and disabled user lookup.
- [x] Add `POST /v1/admin/capabilities` and `GET /v1/admin/capabilities` with JSON Schema validation for input/output schemas. Test: invalid schema rejected, application workspace mismatch rejected and runtime discovery sees only active authorized capabilities.
- [x] Add `POST /v1/admin/roles`, `GET /v1/admin/roles`, `POST /v1/admin/permissions` or seed built-in permissions deterministically. Test: role grants `capability.describe` plus risk-specific invoke permissions and rejects unknown permission codes.
- [x] Add `POST /v1/admin/bindings` and `GET /v1/admin/bindings` with workspace, agent, user, capability and role consistency checks. Test: cross-workspace binding is rejected and no binding still denies runtime invocation.
- [x] Add `POST /v1/admin/secrets` with encryption before persistence and `GET /v1/admin/secrets` metadata-only listing. Test: plaintext is never stored or returned, revoked secrets are ignored, and owner type/id is validated.
- [x] Add `GET /v1/admin/audit` with filters for workspace, agent, user, capability, decision, outcome and time range. Test: pagination, stable ordering and no sensitive payload exposure.
- [x] Add `GET /v1/admin/usage` with filters and aggregate summaries by workspace, agent, user, capability and status. Test: denied/success/error usage events aggregate correctly.
- [x] Record admin audit events for security-relevant changes: agents, roles, bindings, secrets, applications and capabilities. Test: each admin mutation writes a safe audit event with request id and actor type.
- [x] Add admin response schemas and fixtures for stable contract coverage. Test: intentional API changes require fixture updates.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 9 - Runtime Usage, Lifecycle And Safety

Goal: finish runtime endpoints and lifecycle controls expected by agents and operators.

- [x] Implement `GET /v1/usage/me` for authenticated agents. Test: agent sees only its own usage and cannot infer other agents' usage.
- [x] Add agent disable/revoke or status update endpoint. Test: disabled agents immediately fail runtime authentication.
- [x] Add capability, binding, user and secret status update endpoints. Test: disabling each object immediately affects discovery and invocation.
- [x] Add secret rotation flow that creates a replacement and revokes the old secret atomically. Test: invocation uses the new active secret and never selects revoked secrets.
- [x] Add deterministic permission seeding for `capability.describe`, `capability.invoke.read_only`, `capability.invoke.side_effect` and `capability.invoke.destructive`. Test: migrations or startup seed are idempotent.
- [x] Make `admin` risk capabilities unavailable to runtime agents unless a future explicit contract is approved. Test: admin-risk capability cannot be discovered or invoked through runtime APIs.
- [x] Add response pagination where lists can grow: capabilities, audit, usage and admin resources. Test: cursor or limit/offset behavior is stable and bounded.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 10 - Bootstrap, Seeding And Human Workflow

Goal: let a human bring up a useful demo without touching the database manually.

- [x] Add a documented demo bootstrap command, script or admin API flow for a workspace, application, user, capability, role, binding, secret and agent. Test: clean compose environment can execute the documented flow.
- [x] Add `make demo-seed` only if it uses supported APIs or migrations rather than private test helpers. Test: command is idempotent and reports created/reused objects.
- [x] Add `make smoke` for health, ready, APISIX sync, runtime discovery and one mock invocation. Test: command exits nonzero on any failed step.
- [x] Update `README.md` and `OPERATIONS.md` with the same human flow in this plan. Test: docs command snippets are exercised by e2e or smoke tests.
- [x] Make migration behavior explicit: either implement `MIGRATIONS_AUTO_RUN` safely or remove it from active examples. Test: container startup and manual migration tests cover the selected behavior.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 11 - Integration And End-To-End Test Suites

Goal: prove the product works with real infrastructure, not only SQLite and in-memory fakes.

- [x] Create `tests/integration/` for PostgreSQL session lifecycle and Alembic upgrade from empty database to head. Test: runs against compose PostgreSQL or a disposable test database.
- [x] Add integration tests for Admin API object creation and runtime invocation with real PostgreSQL records. Test: curl-equivalent setup produces a successful mock adapter invocation.
- [x] Add APISIX integration tests against local APISIX Admin API. Test: create/update/read route and verify idempotent reconciliation.
- [x] Add `tests/e2e/` flow through APISIX public port. Test: agent discovers capabilities and invokes allowed capability via `http://localhost:9080`.
- [x] Add e2e denial scenarios: no binding, wrong user, disabled capability, missing secret and upstream adapter error. Test: audit and usage records exist for every attempt.
- [x] Add contract fixture tests for all Admin API responses and error shapes. Test: fixture update is required for intentional changes.
- [x] Add CI commands for unit, integration and e2e tiers with clear skip behavior when Docker is unavailable. Test: CI fails on unmarked integration dependency failures.
- [x] output git commands to add files and commit changes using a conventional commit

## Milestone 12 - Adapter Expansion And Provider Readiness

Goal: move from one real capability to a reusable multi-application gateway.

- [x] Validate NethVoice phonebook against the real provider API contract and document required upstream permissions. Test: mock upstream fixtures match observed provider payloads without storing secrets.
- [x] Add NethVoice adapter health check behavior beyond base URL presence when a safe endpoint exists. Test: health maps unavailable/unauthorized responses safely.
- [x] Add a second provider adapter, preferably `nextcloud.files.search` or the next highest-priority NS8 application. Test: success normalization, empty results, limit enforcement, 401/403, 404, timeout, 429, 5xx and invalid payload.
- [x] Add adapter integration tests with mock upstream containers or `httpx` transports for every real provider. Test: no network access to real services is required in CI.
- [x] Add adapter capability templates or registry metadata for common setup. Test: admin can instantiate a documented capability without hand-writing fragile JSON.
- [x] Add retry policy support for safe read-only operations only. Test: read-only retries are bounded, and side-effect/destructive operations are not retried by default.
- [x] List git commands to add files and commit changes using a conventional commit.

## Milestone 13 - MCP And Agent Tooling

Goal: make agent discovery usable by Hermes and other MCP/OpenAPI consumers.

- [ ] Decide and document the product MCP surface: HTTP endpoint, server-sent session, stdio bridge or generated descriptor only. Test: contract tests cover the selected surface.
- [ ] Expose MCP-compatible tool listing through the selected authenticated runtime endpoint if needed by agents. Test: only allowed capabilities appear and names remain stable.
- [ ] Add invocation mapping from MCP tool call to `POST /v1/invoke/{capability_id}` when Grantora owns that bridge. Test: tool call enforces the same user, binding, secret and audit rules.
- [ ] Add examples for Hermes or a generic MCP client. Test: example uses a generated token and performs discovery plus one invocation.
- [ ] Keep OpenAPI and MCP generation from the same filtered capability set. Test: a fixture asserts both surfaces contain equivalent allowed capabilities.
- [ ] output git commands to add files and commit changes using a conventional commit 

## Milestone 14 - APISIX Production Data Plane

Goal: make APISIX reconciliation operationally safe and automatic.

- [ ] Implement optional startup or background APISIX sync according to `APISIX_SYNC_ENABLED` and `APISIX_SYNC_INTERVAL_SECONDS`. Test: disabled mode never writes; enabled mode syncs idempotently.
- [ ] Implement or remove `APISIX_FAIL_CLOSED`; if implemented, unsafe sync failures must not broaden access. Test: simulated Admin API failure preserves last safe route state.
- [ ] Restrict APISIX Admin API exposure in production examples. Test: compose/production config checks do not publish Admin API unintentionally.
- [ ] Add TLS and public base URL guidance for deployments where APISIX terminates TLS. Test: generated OpenAPI server URL uses configured public base URL when enabled.
- [ ] Add APISIX route management for future admin/runtime split if needed. Test: admin endpoints are never exposed through public APISIX routes unless explicitly intended.
- [ ] Add route drift reporting. Test: status endpoint can report current APISIX route differs from desired PostgreSQL state without leaking admin details.
- [ ] output git commands to add files and commit changes using a conventional commit 

## Milestone 15 - Observability, Retention And Operations

Goal: make operators able to understand and maintain the system safely.

- [ ] Add audit and usage retention jobs or management commands for `AUDIT_RETENTION_DAYS` and `USAGE_RETENTION_DAYS`. Test: records older than retention are removed or archived according to policy.
- [ ] Add metrics tests that counters increment for auth failure, deny, success, adapter error, secret resolution and APISIX sync. Test: `/metrics` contains expected labels without secrets.
- [ ] Add structured log tests for denied and failed invocation paths. Test: logs include request id and safe context, not authorization headers or tokens.
- [ ] Add backup and restore smoke test using compose PostgreSQL dump/restore plus APISIX resync. Test: restored environment can invoke a demo capability.
- [ ] Add runbook sections for common failures: invalid admin hash, bad Fernet key, missing secret, APISIX Admin API unavailable, migration failure and upstream timeout. Test: runbook commands are validated where practical.
- [ ] Add optional OpenTelemetry tracing only if it does not leak payloads or secrets. Test: spans contain safe identifiers only.
- [ ] output git commands to add files and commit changes using a conventional commit 

## Milestone 16 - Security Hardening

Goal: close security gaps before production release.

- [ ] Add security regression tests for raw upstream passthrough absence. Test: arbitrary provider paths cannot be invoked through runtime APIs.
- [ ] Add request body size limits for runtime and admin APIs. Test: oversized requests fail safely before adapter invocation.
- [ ] Add stronger validation for URLs, slugs, capability ids and JSON schemas. Test: SSRF-prone or malformed base URLs are rejected or explicitly constrained.
- [ ] Add admin authorization model beyond bootstrap token when product requirements are clear. Test: non-admin tokens cannot reach admin endpoints, and scoped admins cannot cross workspaces.
- [ ] Add optional OIDC/NS8 identity integration without making NS8 required. Test: standalone bootstrap auth still works when OIDC is disabled.
- [ ] Add external secret store abstraction behind the existing secret resolution rules. Test: PostgreSQL encrypted secrets and external references both fail closed.
- [ ] Add dependency scanning, SBOM generation and container vulnerability checks. Test: release pipeline publishes scan artifacts and blocks critical unresolved findings.
- [ ] output git commands to add files and commit changes using a conventional commit 

## Milestone 17 - Release Packaging And NS8 Readiness

Goal: ship a standalone product that can later be managed by an NS8 module.

- [ ] Publish versioned container images for Grantora API. Test: image starts from a clean environment and reports version.
- [ ] Add production compose or deployment examples with PostgreSQL, APISIX and network isolation. Test: production example passes smoke tests after required secrets are supplied.
- [ ] Add migration and upgrade procedure for versioned releases. Test: upgrade from previous release fixture to current head preserves data and policy.
- [ ] Add NS8 packaging design notes without introducing runtime dependency on NS8 internals. Test: standalone compose remains supported.
- [ ] Add release checklist for contracts, docs, migrations, tests, security scan, backup/restore and changelog. Test: each release candidate completes the checklist.
- [ ] output git commands to add files and commit changes using a conventional commit 

## Milestone 18 - Product Completion Acceptance

Goal: prove the full software is ready for real administrators and agents.

- [ ] A human can follow documented steps from an empty checkout to successful capability invocation through APISIX. Test: e2e script executes the documentation.
- [ ] A human can create, disable, rotate and inspect all required dynamic objects through supported admin surfaces. Test: admin workflow e2e covers create, update/status, revoke and list paths.
- [ ] Agents can discover OpenAPI and MCP-compatible tools filtered by user and authorization. Test: fixture and e2e tests match expected capability set.
- [ ] Operators can back up and restore PostgreSQL plus environment-managed secrets and regenerate APISIX state. Test: restore smoke test succeeds.
- [ ] Security regression matrix passes for every release. Test: matrix in `TESTING.md` is automated or explicitly documented as manual with evidence.
- [ ] output git commands to add files and commit changes using a conventional commit 

## Human Documentation

This section is intentionally written for operators and developers. The same content should be copied or refined into `README.md` and `OPERATIONS.md` as milestones land.

### What Grantora Runs

Local standalone development runs these services:

- `grantora-api`: FastAPI Gateway API.
- `postgres`: PostgreSQL source of truth.
- `apisix`: public HTTP data-plane and optional local Admin API.
- `apisix-etcd`: APISIX runtime configuration backend.

Main local URLs:

- Grantora API direct: `http://localhost:8080`
- APISIX public entrypoint: `http://localhost:9080`
- APISIX Admin API in local compose: `http://localhost:9180`

### Configuration Principles

- Put static configuration in environment variables or `.env`.
- Put dynamic business configuration in PostgreSQL through Admin APIs.
- Generate a real Fernet key for `SECRET_ENCRYPTION_KEY`; the default placeholder will not decrypt valid secrets.
- Generate an admin bootstrap token and store only its `hmac-sha256:<hex>` hash in environment.
- Keep `APISIX_ADMIN_KEY`, token peppers, admin tokens and upstream secrets out of logs and source control.

### Active Environment Variables

These variables are read by the current `Settings` class or the current compose file.

| Variable | Purpose | Current default | Notes |
| --- | --- | --- | --- |
| `GRANTORA_ENV` | Runtime environment name | `development` | Alias: `GATEWAY_ENV`. |
| `GRANTORA_PUBLIC_BASE_URL` | Public URL advertised for the gateway | `http://localhost:9080` | Alias: `GATEWAY_PUBLIC_BASE_URL`. |
| `GRANTORA_BIND_ADDR` | API bind address | `0.0.0.0` | Alias: `GATEWAY_BIND_ADDR`. |
| `GRANTORA_PORT` | API port inside container | `8080` | Alias: `GATEWAY_PORT`. |
| `GRANTORA_API_PORT` | Host port mapped to API direct port | `8080` | Compose-only. |
| `GRANTORA_LOG_LEVEL` | Python logging level | `INFO` | Aliases: `GATEWAY_LOG_LEVEL`, `LOG_LEVEL`. |
| `GRANTORA_JSON_LOGS` | Emit structured JSON logs | `true` | Alias: `GATEWAY_JSON_LOGS`. |
| `DATABASE_URL` | SQLAlchemy database URL | `postgresql+psycopg://grantora:grantora@postgres:5432/grantora` | Required outside local defaults. |
| `DATABASE_POOL_SIZE` | SQLAlchemy pool size | `10` | PostgreSQL only. |
| `DATABASE_MAX_OVERFLOW` | SQLAlchemy max overflow connections | `20` | PostgreSQL only. |
| `MIGRATIONS_AUTO_RUN` | Container migration auto-run switch | `true` | When true, the API entrypoint runs `alembic upgrade head` before Uvicorn. |
| `POSTGRES_DB` | Local compose database name | `grantora` | Compose-only. |
| `POSTGRES_USER` | Local compose database user | `grantora` | Compose-only. |
| `POSTGRES_PASSWORD` | Local compose database password | `grantora` | Compose-only; change for non-disposable environments. |
| `POSTGRES_PORT` | Host port mapped to PostgreSQL | `5432` | Compose-only. |
| `SECRET_ENCRYPTION_KEY` | Fernet key for encrypted upstream secrets | placeholder | Must be generated and preserved for restore. |
| `GRANTORA_AGENT_TOKEN_PEPPER` | HMAC pepper for agent/admin token hashes | placeholder | Aliases: `AGENT_TOKEN_PEPPER`, `TOKEN_HASH_PEPPER`. |
| `GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH` | Hash of bootstrap admin bearer token | unset/placeholder | Alias: `ADMIN_BOOTSTRAP_TOKEN_HASH`. |
| `APISIX_ADMIN_URL` | Internal APISIX Admin API URL | `http://apisix:9180` | Must remain internal in production. |
| `APISIX_ADMIN_KEY` | APISIX Admin API key | `change-me` | Must be changed outside local dev. |
| `APISIX_ADMIN_TIMEOUT_SECONDS` | APISIX Admin API timeout | `5` | Positive float. |
| `APISIX_RUNTIME_UPSTREAM_NODE` | APISIX upstream node for Grantora API | `grantora-api:8080` | Used in desired runtime route. |
| `APISIX_RATE_LIMIT_COUNT` | APISIX baseline rate limit count | `1000` | Positive integer. |
| `APISIX_RATE_LIMIT_TIME_WINDOW` | APISIX rate limit window seconds | `60` | Positive integer. |
| `APISIX_PUBLIC_PORT` | Host port mapped to APISIX public port | `9080` | Compose-only. |
| `APISIX_ADMIN_PORT` | Host port mapped to APISIX Admin API | `9180` | Compose-only; do not publish in production. |
| `METRICS_ENABLED` | Enables `/metrics` | `true` | Metrics path is currently fixed at `/metrics`. |
| `REQUEST_ID_HEADER` | Header used for request id propagation | `X-Request-Id` | Included in responses. |
| `DEFAULT_REQUEST_TIMEOUT_SECONDS` | Reserved/default request timeout setting | `30` | Present in settings; not broadly enforced yet. |
| `UPSTREAM_TIMEOUT_SECONDS` | Adapter request timeout | `30` | Used by NethVoice and Nextcloud adapters. |
| `UPSTREAM_CONNECT_TIMEOUT_SECONDS` | Adapter connect timeout | `5` | Used by NethVoice and Nextcloud adapters. |
| `UPSTREAM_TLS_VERIFY` | Verify upstream TLS certificates | `true` | Used by NethVoice and Nextcloud adapters. |
| `UPSTREAM_MAX_RESPONSE_BYTES` | Maximum upstream response size | `10485760` | Used by NethVoice and Nextcloud adapters. |
| `UPSTREAM_READ_RETRY_ATTEMPTS` | Maximum total attempts for retryable read-only adapter calls | `2` | Side-effecting, destructive, draft and admin capabilities are not retried by default. |

### Reserved Or Planned Variables

These appear in `.env.example` or the product docs but are not fully wired in the current implementation.

| Variable | Planned meaning | Plan item |
| --- | --- | --- |
| `DATABASE_SSLMODE` | PostgreSQL TLS mode | Wire through database URL or remove from example. |
| `APISIX_PUBLIC_URL` | Public APISIX base URL | Align with `GRANTORA_PUBLIC_BASE_URL` or use for APISIX-specific docs. |
| `APISIX_SYNC_ENABLED` | Automatic APISIX sync toggle | Milestone 14. |
| `APISIX_SYNC_INTERVAL_SECONDS` | Background sync interval | Milestone 14. |
| `APISIX_FAIL_CLOSED` | Fail-closed data-plane behavior | Milestone 14. |
| `METRICS_PATH` | Custom metrics path | Either implement or remove. |
| `AUDIT_ENABLED` | Audit toggle | Audit is mandatory; remove or define carefully. |
| `AUDIT_RETENTION_DAYS` | Audit retention period | Milestone 15. |
| `USAGE_RETENTION_DAYS` | Usage retention period | Milestone 15. |
| `FEATURE_MCP` | MCP surface toggle | Milestone 13. |
| `FEATURE_DIRECT_APISIX_PROXY` | Raw proxy toggle | Must remain off by default; any future use needs a security review. |
| `FEATURE_OIDC` | OIDC/admin identity integration | Milestone 16. |
| `FEATURE_EXTERNAL_POLICY_ENGINE` | External policy engine | Future only; deny-by-default remains local. |
| `FEATURE_EXTERNAL_SECRET_STORE` | External secret backend | Milestone 16. |

### Generate Local Secrets

Install dependencies first if running outside Docker. In this repository, `make test` uses the project Python environment when available.

Generate a Fernet key:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

Generate an admin bootstrap token hash. Save the plaintext token somewhere secure; Grantora only stores the hash.

```bash
export ADMIN_BOOTSTRAP_TOKEN='replace-with-long-random-admin-token'
export GRANTORA_AGENT_TOKEN_PEPPER='replace-with-long-random-pepper'

python - <<'PY'
import os
import hashlib
import hmac

token = os.environ['ADMIN_BOOTSTRAP_TOKEN']
pepper = os.environ['GRANTORA_AGENT_TOKEN_PEPPER']
digest = hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()
print(f'hmac-sha256:{digest}')
PY
```

Set these values in `.env`:

```bash
SECRET_ENCRYPTION_KEY='<generated-fernet-key>'
GRANTORA_AGENT_TOKEN_PEPPER='<same-pepper-used-for-hash>'
GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH='hmac-sha256:<generated-digest>'
APISIX_ADMIN_KEY='<local-or-production-apisix-admin-key>'
```

### Local Startup

```bash
cp .env.example .env
# Edit .env with generated SECRET_ENCRYPTION_KEY, GRANTORA_AGENT_TOKEN_PEPPER,
# GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH and APISIX_ADMIN_KEY.
docker compose up --build -d
```

The local container runs migrations automatically before Uvicorn when `MIGRATIONS_AUTO_RUN=true`. To run migrations manually instead, set `MIGRATIONS_AUTO_RUN=false` and execute:

```bash
docker compose exec grantora-api alembic upgrade head
```

Verify health:

```bash
curl -sS http://localhost:8080/healthz
curl -sS http://localhost:8080/readyz
```

Sync APISIX desired routes:

```bash
curl -sS -X POST http://localhost:8080/v1/admin/apisix/sync \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

Check APISIX status:

```bash
curl -sS http://localhost:8080/v1/admin/apisix/status \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

### Target End-To-End Example

This curl-only example is supported by the Milestone 8 Admin API endpoints. Milestone 10 also provides the executable local demo path:

```bash
make demo-seed
make smoke
```

The Make targets use the supported Admin and Runtime APIs and store local demo metadata in `.grantora-demo.env`.

The final flow should work like this from a clean compose environment.

Create a workspace:

```bash
WORKSPACE_ID=$(curl -sS -X POST http://localhost:8080/v1/admin/workspaces \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d '{"slug":"acme","display_name":"Acme SRL"}' | jq -r '.workspace.id')
```

Create a NethVoice application instance:

```bash
APPLICATION_ID=$(curl -sS -X POST http://localhost:8080/v1/admin/applications \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d "{\"workspace_id\":\"$WORKSPACE_ID\",\"slug\":\"nethvoice\",\"display_name\":\"NethVoice\",\"provider_type\":\"nethvoice\",\"base_url\":\"https://nethvoice.example.test\"}" | jq -r '.application.id')
```

Create a user:

```bash
USER_ID=$(curl -sS -X POST http://localhost:8080/v1/admin/users \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d "{\"workspace_id\":\"$WORKSPACE_ID\",\"external_id\":\"alice\",\"display_name\":\"Alice\"}" | jq -r '.user.id')
```

Create the phonebook capability:

```bash
curl -sS -X POST http://localhost:8080/v1/admin/capabilities \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d @- <<JSON
{
	"id": "nethvoice.phonebook.search",
	"workspace_id": "$WORKSPACE_ID",
	"application_instance_id": "$APPLICATION_ID",
	"name": "Search phonebook",
	"version": 1,
	"provider_type": "nethvoice",
	"adapter": "nethvoice",
	"operation": "phonebook.search",
	"auth_mode": "user",
	"risk_class": "read_only",
	"input_schema": {
		"type": "object",
		"properties": {
			"query": {"type": "string", "minLength": 1},
			"limit": {"type": "integer", "minimum": 1, "maximum": 50}
		},
		"required": ["query"],
		"additionalProperties": false
	},
	"output_schema": {
		"type": "object",
		"properties": {
			"contacts": {
				"type": "array",
				"items": {
					"type": "object",
					"properties": {
						"display_name": {"type": "string"},
						"phone": {"type": "string"},
						"company": {"type": "string"},
						"source": {"type": "string", "const": "nethvoice"}
					},
					"required": ["display_name", "phone", "company", "source"],
					"additionalProperties": false
				}
			}
		},
		"required": ["contacts"],
		"additionalProperties": false
	}
}
JSON
```

Create a role with describe and read-only invoke permissions:

```bash
ROLE_ID=$(curl -sS -X POST http://localhost:8080/v1/admin/roles \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d "{\"workspace_id\":\"$WORKSPACE_ID\",\"slug\":\"phonebook-reader\",\"display_name\":\"Phonebook reader\",\"permission_codes\":[\"capability.describe\",\"capability.invoke.read_only\"]}" | jq -r '.role.id')
```

Create an agent and capture its token. This endpoint exists today, but it currently requires the workspace to already exist.

```bash
AGENT_CREATE_RESPONSE=$(curl -sS -X POST http://localhost:8080/v1/admin/agents \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d "{\"workspace_id\":\"$WORKSPACE_ID\",\"slug\":\"hermes-alice\",\"display_name\":\"Hermes Alice\"}")

AGENT_ID=$(printf '%s' "$AGENT_CREATE_RESPONSE" | jq -r '.agent.id')
AGENT_TOKEN=$(printf '%s' "$AGENT_CREATE_RESPONSE" | jq -r '.token')
```

Bind the agent, user, capability and role:

```bash
curl -sS -X POST http://localhost:8080/v1/admin/bindings \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d "{\"workspace_id\":\"$WORKSPACE_ID\",\"agent_id\":\"$AGENT_ID\",\"user_id\":\"$USER_ID\",\"capability_id\":\"nethvoice.phonebook.search\",\"role_id\":\"$ROLE_ID\"}"
```

Store the user's upstream secret. The response must return metadata only, never the secret value.

```bash
curl -sS -X POST http://localhost:8080/v1/admin/secrets \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
	-H 'Content-Type: application/json' \
	-d "{\"workspace_id\":\"$WORKSPACE_ID\",\"application_instance_id\":\"$APPLICATION_ID\",\"owner_type\":\"user\",\"owner_id\":\"$USER_ID\",\"secret_type\":\"bearer_token\",\"value\":\"replace-with-upstream-user-token\"}"
```

Discover the agent identity through APISIX:

```bash
curl -sS http://localhost:9080/v1/me \
	-H "Authorization: Bearer $AGENT_TOKEN"
```

Discover allowed capabilities for Alice:

```bash
curl -sS 'http://localhost:9080/v1/capabilities?user=alice' \
	-H "Authorization: Bearer $AGENT_TOKEN"
```

Invoke the phonebook capability:

```bash
curl -sS -X POST http://localhost:9080/v1/invoke/nethvoice.phonebook.search \
	-H "Authorization: Bearer $AGENT_TOKEN" \
	-H 'Content-Type: application/json' \
	-d '{"user":"alice","input":{"query":"Mario","limit":10}}'
```

Expected success shape:

```json
{
	"request_id": "req_...",
	"capability": "nethvoice.phonebook.search",
	"status": "ok",
	"data": {
		"contacts": []
	}
}
```

Inspect audit and usage:

```bash
curl -sS "http://localhost:8080/v1/admin/audit?workspace_id=$WORKSPACE_ID" \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"

curl -sS "http://localhost:8080/v1/admin/usage?workspace_id=$WORKSPACE_ID" \
	-H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

### Troubleshooting Notes

- `admin_auth_unavailable`: `GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH` or `ADMIN_BOOTSTRAP_TOKEN_HASH` is missing.
- `admin_auth_invalid`: the plaintext admin token, hash or token pepper do not match.
- `agent_auth_invalid`: the agent token is wrong, disabled, missing from the database or hashed with a different pepper.
- `secret_unavailable`: `SECRET_ENCRYPTION_KEY` changed after secrets were written, or the ciphertext is invalid.
- `secret_not_found`: no active secret matches the capability's auth mode and owner lookup.
- `capability_denied`: the workspace, user, capability, binding or role permission check failed.
- `apisix_admin_unavailable`: Grantora cannot reach APISIX Admin API or the Admin key is wrong.
- `upstream_timeout`: the provider did not respond within `UPSTREAM_TIMEOUT_SECONDS` or connect timeout.

### Required Validation Commands

Use the narrowest command while developing, then the full project target before release.

```bash
make test
make lint
make format-check
```

When no virtual environment is available in this workspace, local validation may need explicit `PYTHONPATH` for target-installed dependencies as documented in repository memory. Release validation should use a clean environment.