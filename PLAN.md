# PLAN.md

Grantora is in active development and has no production installations. This plan describes how to finish the standalone Grantora product only. External packaging, including any future platform-specific module, is intentionally out of scope for this repository plan.

Keep this file current. Every completed task must have a test or smoke-check path. API, database model, adapter, authorization, audit, usage, error-shape and APISIX route changes must update the relevant contract documentation before or with code changes.

## Non-Negotiable Project Rules

- Grantora is standalone software.
- Apache APISIX is the HTTP data-plane.
- PostgreSQL is the source of truth for dynamic state.
- Static configuration comes from environment variables only.
- Grantora performs business authorization; APISIX does not decide business permissions.
- Capability authorization is deny-by-default.
- Agents never receive upstream secrets or raw upstream API access.
- Runtime capability discovery must be filtered by agent, user, workspace, capability status and RBAC grants.
- Every runtime invocation attempt must produce audit and usage records, including denials.
- Safe errors must not leak tokens, secret values, internal URLs, stack traces or upstream response bodies.
- No migration code is used while Grantora is in development.
- Do not add schema migration tooling or migration commands until the project has a real release/upgrade policy.
- During development, schema changes are applied by editing SQLAlchemy models and recreating disposable databases.

## Development Database Rule

Grantora is not installed in production yet. The database schema is allowed to change directly with the models.

Current rule:

1. Edit SQLAlchemy models directly.
2. Start with a clean disposable PostgreSQL volume or test schema when the model changes.
3. Let the application create the current schema from `Base.metadata.create_all()` during development startup.
4. Do not preserve backward compatibility for old development databases unless explicitly needed for a test fixture.
5. Do not add migration files, migration runners, migration make targets or migration release notes.

When Grantora gets its first real versioned deployment, introduce a separate upgrade policy at that time.

## Current Baseline

Implemented or substantially present:

- FastAPI application factory.
- Health and readiness endpoints.
- Request ID propagation.
- Safe error response shape.
- Optional Prometheus metrics.
- SQLAlchemy models for core dynamic state.
- PostgreSQL-backed persistence.
- Agent bearer-token hashing and runtime authentication.
- Admin bootstrap authentication.
- Dynamic Admin APIs for core objects.
- Runtime endpoints for `/v1/me`, capability discovery, filtered OpenAPI, MCP-compatible tools and invocation.
- Deny-by-default runtime authorization.
- Secret encryption and active-secret resolution.
- Audit and usage recording for runtime paths.
- Mock, NethVoice phonebook and Nextcloud files adapters.
- APISIX Admin API client and route reconciliation.
- Local compose stack for Grantora API, PostgreSQL, APISIX and APISIX etcd.
- Demo seed and smoke commands.
- Retention command for audit and usage rows.

Completed cleanup after this plan change:

- Remove migration dependency and files.
- Remove migration environment variables from examples and compose files.
- Replace migration startup behavior with development schema creation.
- Update tests and docs that still mention legacy migration workflows.

## Milestone 1 - Remove Migration System

Goal: make the repository consistent with the development-phase database rule.

Tasks:

- [x] Remove the legacy schema migration dependency. Test: clean install succeeds without the removed package.
- [x] Delete the legacy migration config. Test: repository search finds no active migration config.
- [x] Delete the legacy migration tree. Test: repository search finds no migration files.
- [x] Remove the legacy migration auto-run environment variable from settings, compose files, environment examples, release workflow and docs. Test: repository search finds no legacy variable reference.
- [x] Remove the legacy migration make target. Test: invoking the removed target fails because it no longer exists.
- [x] Remove migration commands from release and operations docs. Test: docs search finds no legacy migration command.
- [x] Add a development schema bootstrap based on current SQLAlchemy metadata. Test: clean PostgreSQL volume starts and `make demo-seed` can create objects without manual DB commands.
- [x] Update integration tests so they create/drop disposable schemas from metadata, not migrations. Test: `make test-integration` passes when PostgreSQL test variables are configured.

## Milestone 2 - Rebase Documentation On Current Architecture

Goal: make documentation describe the actual standalone development model.

Tasks:

- [x] Update `README.md` local run instructions to state that the development API creates the current schema automatically.
- [x] Update `OPERATIONS.md` to remove migration and platform-packaging assumptions.
- [x] Update `TESTING.md` to remove migration-specific test requirements.
- [x] Update `STRUCTURE.md` if it mentions migration directories or upgrade flows.
- [x] Update `CONTRACTS.md` only if API behavior changed.
- [x] Keep future external packaging out of this plan.

## Milestone 3 - Stabilize Core Contracts

Goal: make Grantora’s core product model explicit enough for coding agents and human developers.

Tasks:

- [x] Confirm `PROJECT.md` defines the standalone product boundary.
- [x] Confirm `CONTRACTS.md` defines Admin API, Runtime API, capability, audit, usage, error and APISIX contracts.
- [x] Confirm `STRUCTURE.md` matches the actual repository layout.
- [x] Confirm `AGENTS.md` instructs coding agents to update contracts before implementation changes.
- [x] Add contract tests for every public response shape that is considered stable.

Acceptance:

- A developer can understand what to build without reading implementation first.
- A coding agent can find the correct file for API, DB, adapter, APISIX and test changes.
- No documented contract depends on deployment packaging outside this standalone repository.

## Milestone 4 - Database Model Hardening

Goal: make the current direct schema safe and coherent while migrations are intentionally absent.

Tasks:

- [x] Review all SQLAlchemy models for missing constraints, indexes and cascade behavior.
- [x] Ensure workspace isolation is enforced through model relationships and query helpers.
- [x] Ensure unique constraints exist for slugs, external ids, role names and capability ids where needed.
- [x] Ensure status fields are normalized and validated by API schemas.
- [x] Ensure JSON schema fields have sane defaults and validation before persistence.
- [x] Ensure timestamps are timezone-aware and consistently generated.

Tests:

- Unit tests cover model creation and constraint failures.
- Integration tests create a fresh schema from metadata on PostgreSQL.
- Runtime and Admin API tests do not rely on stale pre-existing data.

## Milestone 5 - Admin API Completion

Goal: make all dynamic state configurable through supported APIs.

Tasks:

- [x] Verify CRUD/status APIs for workspaces.
- [x] Verify CRUD/status APIs for application instances.
- [x] Verify CRUD/status APIs for users.
- [x] Verify CRUD/status APIs for agents and agent tokens.
- [x] Verify CRUD/status APIs for capabilities.
- [x] Verify CRUD/status APIs for permissions, roles and bindings.
- [x] Verify create/list/rotate/revoke APIs for secrets.
- [x] Verify audit and usage query APIs with filters and pagination.
- [x] Verify APISIX sync/status APIs.
- [x] Ensure all write APIs produce safe audit records.

Tests:

- Admin API unit tests cover create, list, conflict, invalid reference, cross-workspace rejection, status change and safe response shape.
- Contract fixtures are updated for intentional response changes.

## Milestone 6 - Runtime Authorization And Delegation

Goal: make agent-on-behalf-of-user behavior deterministic and auditable.

Tasks:

- [x] Define a single runtime user-selection rule for all runtime endpoints.
- [x] Ensure agent authentication rejects missing, invalid, disabled and revoked credentials.
- [x] Ensure a disabled workspace denies all runtime access.
- [x] Ensure disabled users deny discovery and invocation.
- [x] Ensure disabled capabilities are hidden and cannot be invoked by direct id.
- [x] Ensure disabled bindings deny immediately.
- [x] Ensure role permissions require both `capability.describe` and the risk-specific invoke permission.
- [x] Ensure admin-risk capabilities are unavailable to runtime agents unless a future explicit contract changes this.

Tests:

- Unit matrix for allowed and denied combinations.
- Every denial writes audit and usage events.
- Runtime error shape stays safe and consistent.

## Milestone 7 - Capability Registry And Tool Surfaces

Goal: keep capability definitions as the source of truth for agent tools.

Tasks:

- [x] Verify capability IDs, names, descriptions, schemas, provider type, risk class and adapter config are validated.
- [x] Verify runtime capability list is filtered and paginated.
- [x] Verify filtered OpenAPI is generated from the same authorized capability set.
- [x] Verify MCP-compatible tool listing is generated from the same authorized capability set.
- [x] Verify MCP tool call maps to the same invocation path and authorization checks.
- [x] Add capability template coverage for common provider setup.

Tests:

- Fixture tests compare filtered OpenAPI and MCP tools for the same seeded agent/user.
- Invalid capability schemas are rejected before persistence.
- Tool names remain stable across runs.

## Milestone 8 - Invocation Engine And Adapters

Goal: make capability execution safe, observable and extensible.

Tasks:

- [x] Verify invocation validates request input against capability schema.
- [x] Verify secret resolution is fail-closed.
- [x] Verify secrets are decrypted only in memory during invocation.
- [x] Verify upstream credentials are injected only by adapters or controlled broker code.
- [x] Verify upstream timeouts and response-size limits.
- [x] Verify upstream errors normalize to safe Grantora error codes.
- [x] Verify read-only retry policy is bounded and never applies to side-effecting/destructive capabilities by default.
- [x] Document adapter extension rules.


Tests:

- Mock adapter tests cover success and error paths.
- Real adapter tests use mock transports or mock upstreams only.
- No test contacts real business services.

## Milestone 9 - APISIX Reconciliation

Goal: keep APISIX as generated runtime state.

Tasks:

- [ ] Verify desired APISIX routes are generated from Grantora configuration.
- [ ] Verify reconciliation is idempotent.
- [ ] Verify stale Grantora-managed routes are cleaned up safely.
- [ ] Verify foreign APISIX routes are not touched.
- [ ] Verify Admin API key and internal APISIX details never leak in errors or logs.
- [ ] Verify sync status and drift reports are safe for operators.
- [ ] Verify admin routes are not exposed through public APISIX routes unless explicitly intended.


Tests:

- Unit tests for desired route generation.
- Integration tests against local APISIX Admin API.
- E2E tests through APISIX public port.

## Milestone 10 - Observability, Retention And Operations

Goal: make operators able to understand and maintain Grantora during development and pre-release validation.

Tasks:

- [ ] Verify structured logs contain request id and safe entity ids only.
- [ ] Verify logs omit authorization headers, tokens, cookies, secret values, encrypted values and payload bodies.
- [ ] Verify metrics counters increment for auth failures, denials, successes, adapter errors, secret resolution and APISIX sync.
- [ ] Verify audit and usage retention support dry-run and destructive modes.
- [ ] Verify backup/restore smoke works with PostgreSQL dump/restore plus APISIX resync.
- [ ] Update runbooks for common failures: invalid admin hash, bad Fernet key, missing secret, APISIX Admin API unavailable and upstream timeout.


Tests:

- Unit tests for log safety and metrics labels.
- Retention command tests.
- Opt-in backup/restore smoke for disposable compose state.

## Milestone 11 - Security Hardening

Goal: close security gaps before any production release.

Tasks:

- [ ] Deny raw upstream passthrough by default.
- [ ] Enforce request body size limits for admin and runtime APIs.
- [ ] Validate URLs to reduce SSRF risk.
- [ ] Validate slugs, ids and JSON schemas strictly.
- [ ] Keep external secret references fail-closed until a backend is explicitly configured.
- [ ] Keep optional OIDC/header-based admin identity disabled by default and safe behind trusted proxies only.
- [ ] Add dependency audit, SBOM and container scan gates.


Tests:

- Security regression matrix in `TESTING.md` is automated where practical.
- Manual security checks are documented with evidence requirements.

## Milestone 12 - Developer Workflow And CI

Goal: make local and CI validation obvious.

Tasks:

- [ ] Ensure `make test-unit` works from a clean Python environment.
- [ ] Ensure `make test-integration` uses disposable PostgreSQL schemas created from metadata.
- [ ] Ensure `make test-e2e` uses documented compose services and APISIX.
- [ ] Ensure `make demo-seed` and `make smoke` work on a clean disposable stack.
- [ ] Ensure `make lint` and `make format-check` are documented.
- [ ] Ensure CI runs unit checks and clearly gates optional infrastructure tests.
- [ ] Remove CI references to migrations.


## Completion Criteria For Standalone Core

Grantora standalone core is ready for a first real release only when:

- A clean checkout can start the local stack without manual database commands.
- A human can seed a demo through supported Admin APIs.
- An agent can discover only authorized capabilities through APISIX.
- An agent can invoke an allowed capability through APISIX.
- Denied invocations produce audit and usage records.
- Secrets never leave Grantora through responses, logs, metrics, traces or generated tool descriptions.
- APISIX state can be regenerated from PostgreSQL-backed Grantora state.
- Backup/restore from PostgreSQL plus environment-managed secrets works on disposable state.
- Unit, integration and e2e tests pass in their documented environments.
- No migration system exists in the repository.
