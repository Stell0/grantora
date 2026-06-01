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