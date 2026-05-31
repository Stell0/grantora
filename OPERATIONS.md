# OPERATIONS.md

This file documents how to run and operate Grantora during standalone development. It later becomes the base for NS8 module packaging notes.

## Environment Variables

All static configuration comes from environment variables. Start from [.env.example](.env.example):

```bash
cp .env.example .env
```

Required groups:

- Core service: environment, bind address, public base URL and logging.
- Database: PostgreSQL URL, pool size and migration behavior.
- Security: `SECRET_ENCRYPTION_KEY`, `GRANTORA_AGENT_TOKEN_PEPPER` or `AGENT_TOKEN_PEPPER`, and `GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH` or `ADMIN_BOOTSTRAP_TOKEN_HASH`.
- APISIX: public URL, Admin API URL, Admin API key and sync settings.
- Observability: metrics, audit retention, usage retention and request id header.
- Upstream defaults: timeouts, TLS verification and response size limit.

Agent and admin bootstrap token hashes use the `hmac-sha256:<hex>` format. Generate the admin bootstrap hash with the same token pepper that the service will receive at runtime.

## Local Docker Compose

Start local services:

```bash
docker compose up --build
```

Stop local services:

```bash
docker compose down
```

Remove local database volumes only when disposable state is acceptable:

```bash
docker compose down -v
```

Local service names:

- `grantora-api`: Gateway API service
- `postgres`: PostgreSQL source of truth
- `apisix`: APISIX data-plane and Admin API
- `apisix-etcd`: APISIX configuration backend

## Database Migrations

Expected commands once the Python skeleton exists:

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

Rules:

- Run migrations before starting production traffic.
- Do not edit applied migration files in shared environments.
- Include indexes for new lookup paths.
- Keep migration behavior independent of NS8 internals.

## APISIX Bootstrap

Grantora stores desired APISIX routes in PostgreSQL and reconciles them through the APISIX Admin API.

Operational rules:

- PostgreSQL desired state wins.
- Manual APISIX changes may be overwritten.
- APISIX Admin API must be internal-only outside local development.
- Failed sync must not open access broader than the previous safe route state.

Manual sync endpoint after implementation:

```bash
curl -X POST http://localhost:8080/v1/admin/apisix/sync \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

## Health Checks

Required endpoints:

- `/healthz`: process is alive.
- `/readyz`: database and required dependencies are reachable.
- `/metrics`: Prometheus-compatible metrics when enabled.

## Logs

Logs must be structured JSON in production. Required fields include timestamp, level, request id, workspace id when known, agent id when known, user id when known, capability id when known and message.

Never log secrets, tokens, authorization headers, cookies or raw sensitive payloads.

## Metrics

Minimum metrics:

```text
grantora_requests_total{workspace,agent,user,capability,status}
grantora_request_duration_seconds{workspace,capability,provider}
grantora_authorization_denied_total{workspace,reason}
grantora_upstream_requests_total{workspace,provider,status}
grantora_upstream_errors_total{workspace,provider,error_code}
grantora_secret_resolution_total{workspace,provider,result}
grantora_apisix_sync_total{status}
grantora_apisix_sync_duration_seconds
```

## Backup And Restore

Back up:

- PostgreSQL database
- Environment-managed encryption keys and token peppers
- Any external secret backend references when added

Do not rely on APISIX etcd as the source of truth. APISIX state is generated from PostgreSQL and should be reconstructable by reconciliation.

Restore order:

1. Restore environment secrets.
2. Restore PostgreSQL.
3. Run migrations if needed.
4. Start Grantora API.
5. Reconcile APISIX routes.
6. Verify `/readyz`, `/metrics` and a demo capability invocation.

## Upgrade Rules

- Apply database migrations before enabling code that depends on them.
- Keep old route state safe until APISIX reconciliation succeeds.
- Preserve backward-compatible error codes unless [CONTRACTS.md](CONTRACTS.md) is updated.
- Document any required secret rotation or re-encryption step.

## Future NS8 Packaging Notes

The NS8 module should package and manage upstream Grantora; it should not fork Grantora logic.

The module may generate environment files, manage containers, configure backup and restore, expose actions, integrate with account domains and connect to NS8 UI. The upstream application must continue to run outside NS8 with environment variables and PostgreSQL.