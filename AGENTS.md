# AGENTS.md

## Mission

Grantora is a standalone capability gateway for agents. It lets agents use business application APIs through explicit, audited capabilities while keeping upstream secrets and raw APIs away from agents.

## Non-Negotiable Rules

- Do not expose upstream application secrets to agents.
- Do not implement raw API passthrough as the default model.
- All static configuration comes from environment variables.
- PostgreSQL is the source of truth for dynamic state.
- APISIX is the HTTP data-plane.
- Capability authorization is deny-by-default.
- Every invocation must produce audit and usage records, including denied invocations.
- Safe error responses must not leak tokens, internal URLs, stack traces or upstream response bodies.

## Main References

- [PROJECT.md](PROJECT.md): product definition and architecture
- [STRUCTURE.md](STRUCTURE.md): code and module structure
- [CONTRACTS.md](CONTRACTS.md): API, database and adapter contracts
- [PLAN.md](PLAN.md): implementation roadmap
- [SECURITY.md](SECURITY.md): authentication, secrets and threat model
- [TESTING.md](TESTING.md): required tests and acceptance matrix
- [ADAPTERS.md](ADAPTERS.md): adapter interface and behavior rules
- [OPERATIONS.md](OPERATIONS.md): local operation, schema bootstrap and deployment notes

## Coding Conventions

- Use Python FastAPI for the Gateway API.
- Use SQLAlchemy or SQLModel for database models; during development, create schema from metadata on disposable state.
- Use Pydantic models for request, response and internal contract validation.
- Use `httpx` for upstream HTTP calls.
- Use structured JSON logging and never log secrets or authorization headers.
- Keep runtime code under `src/grantora/` using the ownership boundaries in [STRUCTURE.md](STRUCTURE.md).
- Add or update tests in `tests/` for every behavior change.
- Prefer small, explicit modules over broad utility files.
- Keep [PROJECT.md](PROJECT.md), [STRUCTURE.md](STRUCTURE.md) and other reference documents up to date with architectural decisions and rationale.

## Development Workflow

1. Read [PROJECT.md](PROJECT.md).
2. Read [STRUCTURE.md](STRUCTURE.md).
3. Check [PLAN.md](PLAN.md) for the current milestone.
4. Update [CONTRACTS.md](CONTRACTS.md) before changing public APIs, database schema, adapter interfaces, error formats or APISIX route shape.
5. Update [SECURITY.md](SECURITY.md) before changing authentication, authorization, token handling, secret handling or audit behavior.
6. Run the narrowest relevant tests, then the project test target before finalizing.
7. Update [README.md](README.md) and [TESTING.md](TESTING.md) with any new environment variables, test targets or manual acceptance steps.
8. Update [PROJECT.md](PROJECT.md) and [STRUCTURE.md](STRUCTURE.md) with any architectural decisions or rationale.

## How To Run Tests

Use the project commands once the skeleton exists:

```bash
make test
make lint
```

Until `Makefile` exists, use the equivalent direct commands documented in [TESTING.md](TESTING.md) and [OPERATIONS.md](OPERATIONS.md).

## How To Add A Capability

1. Add or update the capability contract in [CONTRACTS.md](CONTRACTS.md).
2. Add the capability schema and risk class to the capability registry.
3. Add authorization checks for the capability risk class.
4. Add adapter dispatch logic only through the adapter interface in [ADAPTERS.md](ADAPTERS.md).
5. Add audit and usage assertions to tests.
6. Add filtered discovery and OpenAPI coverage.

## How To Add An Adapter

1. Read [ADAPTERS.md](ADAPTERS.md).
2. Add the adapter under `src/grantora/adapters/`.
3. Implement the shared adapter protocol.
4. Map upstream errors to safe Grantora errors.
5. Use secret material only in memory during invocation.
6. Add unit tests for normalization and error mapping.
7. Add integration tests with a mock upstream service.

## Do Not Change Without Updating Contracts

- Runtime API paths, request bodies or response bodies
- Admin API paths, request bodies or response bodies
- Database entities, indexes or schema rules
- Capability manifest fields
- Adapter protocol, result type or error type
- Standard error response shape
- APISIX desired route shape
- Audit event or usage event schema

## Definition Of Done

- Code implemented
- Tests added or updated
- API contract updated when behavior changed
- Schema models, contract docs and tests updated when schema changed
- Audit and usage behavior preserved
- Authorization remains deny-by-default
- No secrets leak in logs, responses, metrics or tests

## Commit Messages
Use /commit skill for commits