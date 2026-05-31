# TESTING.md

Grantora tests must prove that agents only see and invoke allowed capabilities, secrets stay hidden, audit and usage records are written, and APISIX routes remain generated state.

## Test Commands

Expected project commands once the skeleton exists:

```bash
make test
make test-unit
make test-integration
make test-e2e
make lint
make format
make demo-seed
make smoke
make retention RETENTION_FLAGS=--dry-run
make backup-restore-smoke
make security-scan
make sbom
make container-scan IMAGE=grantora-api:security
make release-image
make release-image-smoke
```

Until the Makefile exists, use direct tool commands such as `pytest`, `ruff check`, `ruff format --check` and `alembic upgrade head`.

`make demo-seed` and `make smoke` require local compose services plus `.env` values for the admin bootstrap token, token hash, token pepper and secret encryption key.

`make test-integration` loads `.env` and runs `tests/integration/`. Tests skip when `GRANTORA_INTEGRATION_DATABASE_URL` or `GRANTORA_INTEGRATION_APISIX_ADMIN_URL` is absent. If those variables are set, unavailable PostgreSQL or APISIX services are test failures.

`make test-e2e` loads `.env` and runs `tests/e2e/`. Tests skip unless `GRANTORA_RUN_E2E=1` and `ADMIN_BOOTSTRAP_TOKEN` are set. Once enabled, the suite expects the direct API and APISIX public URL to be reachable and fails on infrastructure errors.

`make backup-restore-smoke` is destructive and should only be used against disposable compose data. The opt-in e2e coverage skips unless `GRANTORA_RUN_BACKUP_RESTORE_SMOKE=1` is set.

## Unit Tests

Required areas:

- RBAC permission checks
- Binding lookup and deny-by-default behavior
- Token hashing and verification
- Secret encryption and decryption
- Secret lookup order
- Capability input schema validation
- Adapter result normalization
- Adapter error mapping
- Standard error response formatting
- Oversized request body rejection before admin/runtime handlers
- Strong identifier, URL and capability schema validation
- Scoped DB-backed admin credentials and optional OIDC admin subjects
- Metrics endpoint exposure and counter increments
- Structured JSON request logs without authorization headers or secrets
- Structured JSON runtime decision logs for denied and failed invocation paths
- Optional OpenTelemetry span emission with safe identifiers only
- Version reporting through `/healthz`
- Release image, production compose and release documentation static checks
- Revoked secret exclusion during secret resolution
- Upstream timeout and maximum response size enforcement
- Audit and usage retention pruning commands

## Integration Tests

Required areas:

- PostgreSQL connection and session lifecycle
- Alembic migrations from empty database to head
- Alembic upgrade from the previous release fixture to head preserving data and policy
- Admin creation of workspace, agent, user, application, capability, binding and secret
- Runtime authentication with real database records
- Invocation path with mock adapter
- Audit writes for allow and deny decisions
- Usage writes for success, denied and error outcomes
- Metrics endpoint exposure
- APISIX Admin API route reconciliation

Current integration environment variables:

```text
GRANTORA_INTEGRATION_DATABASE_URL=postgresql+psycopg://grantora:grantora@localhost:5432/grantora
GRANTORA_INTEGRATION_APISIX_ADMIN_URL=http://localhost:9180
GRANTORA_INTEGRATION_APISIX_ADMIN_KEY=$APISIX_ADMIN_KEY
```

The PostgreSQL fixture uses a temporary schema inside the configured database and drops that schema after each test.

## End-To-End Tests

Required flows:

- Agent gets filtered capabilities through APISIX.
- Agent gets filtered capability OpenAPI through APISIX.
- Agent gets MCP-compatible tools through APISIX.
- Agent invokes an allowed capability through APISIX.
- Documented demo seed and smoke workflow succeeds through APISIX.
- Admin workflow can list, disable, rotate and revoke dynamic objects through Admin APIs.
- Agent with no binding is denied.
- Agent cannot act for another user.
- Agent cannot invoke a disabled capability.
- Missing secret fails closed.
- Upstream adapter error returns a safe error.
- Audit event is created for every invocation attempt.
- Usage event is created for success, denied and error outcomes.
- APISIX route reconciliation is idempotent.
- Backup and restore smoke can recreate PostgreSQL state and still invoke the demo capability.

Current e2e environment variables:

```text
GRANTORA_RUN_E2E=1
GRANTORA_RUN_BACKUP_RESTORE_SMOKE=1
ADMIN_BOOTSTRAP_TOKEN=<plaintext bootstrap token for local operator commands>
GRANTORA_E2E_API_URL=http://localhost:8080
GRANTORA_E2E_RUNTIME_URL=http://localhost:9080
```

## Security Regression Matrix

Minimum scenarios and release evidence:

| Scenario | Evidence |
| --- | --- |
| agent with no binding is denied | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| agent cannot act for another user | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| agent cannot invoke disabled capability | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| secret is not returned in responses | `make test-unit` |
| secret is not written to logs | `make test-unit` |
| invalid PostgreSQL secret ciphertext fails closed | `make test-unit` |
| external secret reference fails closed when no backend is configured | `make test-unit` |
| denied request is audited | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| successful request is audited | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| usage counter is written | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| adapter error is normalized | `make test-unit`; `make test-e2e` with `GRANTORA_RUN_E2E=1` |
| APISIX route reconciliation is idempotent | `make test-unit`; `make test-integration` with APISIX env |
| raw upstream path passthrough is unavailable by default | `make test-unit` |
| SSRF-prone upstream base URLs are rejected | `make test-unit` |
| oversized request bodies are rejected safely | `make test-unit` |
| dependency audit, SBOM and container scan artifacts are generated for release candidates | `make security-scan`; `make sbom`; `make container-scan IMAGE=<candidate-image>` |
| versioned release image starts clean and reports its package version | `make release-image`; `make release-image-smoke` |
| production compose does not publish PostgreSQL, Grantora API or APISIX Admin API host ports | `make test-unit` |

## Adapter Tests

Every adapter must include:

- Success normalization test
- Empty result test
- Maximum limit enforcement test
- Upstream 401 or 403 mapping test
- Upstream timeout mapping test
- Upstream 5xx mapping test
- Invalid upstream payload mapping test
- No-secret-in-log assertion when log capture is practical
- Mock upstream transport coverage for each real provider adapter, with sanitized fixtures and no network access to real services

## Contract Tests

Use fixture tests for stable contracts once implementation starts:

- Runtime API response shape
- Admin API response shape
- Standard error response shape
- Capability manifest shape
- Adapter result shape
- Audit event shape
- Usage event shape
- Filtered OpenAPI output for a seeded demo agent and user

Intentional contract changes must update [CONTRACTS.md](CONTRACTS.md) and the matching fixtures in the same change.