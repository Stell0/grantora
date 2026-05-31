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
- Security hardening: `MAX_REQUEST_BODY_BYTES`, optional `FEATURE_OIDC` plus OIDC subject settings, and optional `FEATURE_EXTERNAL_SECRET_STORE`.
- Local workflow helpers: `ADMIN_BOOTSTRAP_TOKEN`, `GRANTORA_API_URL`, `GRANTORA_RUNTIME_URL` and optional `DEMO_*` values used by `make demo-seed` and `make smoke`.
- APISIX: public URL, Admin API URL, Admin API key and sync settings.
- Observability: metrics, audit retention, usage retention, request id header and optional tracing.
- Upstream defaults: timeouts, TLS verification, response size limit and read-only retry attempts.

Agent and admin bootstrap token hashes use the `hmac-sha256:<hex>` format. Generate the admin bootstrap hash with the same token pepper that the service will receive at runtime. The plaintext `ADMIN_BOOTSTRAP_TOKEN` is for local operator commands only; it is not passed to `grantora-api` by the compose file.

DB-backed admin credentials use the same token hash format and can be scoped to a workspace. Scoped admins can manage resources in that workspace only; APISIX sync/status and global permission creation require a super-admin principal.

OIDC/NS8 admin identity remains optional. Leave `FEATURE_OIDC=false` for standalone bootstrap-token operation. When enabling it, set `OIDC_ADMIN_SUBJECTS` to an allowlist and deploy Grantora behind a trusted component that strips incoming identity headers before setting `OIDC_SUBJECT_HEADER`.

Grantora rejects oversized JSON requests before route handlers using `MAX_REQUEST_BODY_BYTES`. Application `base_url` values are constrained to HTTP/HTTPS origins and must not point at localhost, private addresses, bare hostnames or provider paths.

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

The local API container entrypoint runs migrations before Uvicorn when `MIGRATIONS_AUTO_RUN=true`:

```bash
docker compose up --build -d grantora-api
```

Disable automatic migrations by setting `MIGRATIONS_AUTO_RUN=false`, then run migrations manually:

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

Rules:

- Run migrations before starting production traffic.
- Invalid `MIGRATIONS_AUTO_RUN` values make the container exit before serving traffic.
- Do not edit applied migration files in shared environments.
- Include indexes for new lookup paths.
- Keep migration behavior independent of NS8 internals.

## Demo Bootstrap And Smoke

From a clean local checkout, copy `.env.example`, generate real secret material, start compose, seed the demo and run smoke:

```bash
cp .env.example .env
# Edit .env with SECRET_ENCRYPTION_KEY, GRANTORA_AGENT_TOKEN_PEPPER,
# ADMIN_BOOTSTRAP_TOKEN and GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH.
docker compose up --build -d
make demo-seed
make smoke
```

`make demo-seed` uses only Admin API endpoints. It creates or reuses:

- workspace `demo`
- mock application `mock-phonebook`
- user `alice`
- capability `mock.phonebook.search`
- role `phonebook-reader`
- binding for the demo agent, user, capability and role
- user-owned upstream secret metadata
- agent `hermes-demo`

The command writes demo ids and the one-time agent token returned by agent creation to `.grantora-demo.env`. Keep that file local; it is ignored by git. If the file is deleted after the agent already exists, Grantora cannot return the plaintext agent token again, so set `DEMO_AGENT_TOKEN` manually or recreate the disposable demo data.

`make smoke` loads `.env` and `.grantora-demo.env`, then exits nonzero if any step fails:

- `GET /healthz` on the direct API
- `GET /readyz` on the direct API
- `POST /v1/admin/apisix/sync` on the direct API
- `GET /v1/capabilities?user=alice` through APISIX
- `POST /v1/invoke/mock.phonebook.search` through APISIX
- `GET /v1/mcp/tools?user=alice` through APISIX
- `POST /v1/mcp/call` through APISIX

## Retention And Tracing

Prune expired audit and usage data with the retention management command. Use a dry run first when changing retention windows:

```bash
make retention RETENTION_FLAGS=--dry-run
make retention
```

The command reads `AUDIT_RETENTION_DAYS` and `USAGE_RETENTION_DAYS` from the current environment and deletes rows older than the computed cutoff. It never logs or prints secret values.

Optional OpenTelemetry tracing is controlled by these environment variables:

- `OTEL_TRACING_ENABLED`: enable or disable tracing.
- `OTEL_SERVICE_NAME`: service name recorded in spans.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: optional OTLP/HTTP collector endpoint.
- `OTEL_EXPORTER_OTLP_TIMEOUT_SECONDS`: exporter timeout for remote collectors.

When tracing is enabled, Grantora records only safe identifiers such as request id, path, status code, workspace id, agent id, user id and capability id when they are known. It does not attach authorization headers, tokens, cookies, payload bodies or upstream secret material to spans.

## Security Gates

Run release security gates before publishing artifacts:

```bash
python -m pip install -e '.[security]'
make security-scan
make sbom
docker build -t grantora-api:security -f containers/grantora-api.Dockerfile .
make container-scan IMAGE=grantora-api:security
```

`make security-scan` writes `dist/security/dependency-vulnerabilities.json` and fails on unresolved dependency findings reported by `pip-audit`. `make sbom` writes a CycloneDX JSON SBOM to `dist/security/sbom.cdx.json`. `make container-scan` writes `dist/security/container-vulnerabilities.json` and fails on high or critical container findings reported by Trivy. The `Security Gates` workflow runs the same dependency/SBOM gates, scans the built container image and uploads the security artifacts.

External secret references can be submitted with `external_reference` instead of `value` on secret create or rotation. References are stored as encrypted markers. Until an external secret backend is configured, runtime secret resolution fails closed with `secret_unavailable` and never invokes the adapter.

## MCP And Agent Tooling

Grantora's product MCP surface is authenticated HTTP JSON under the runtime API. It is intended for Hermes or generic MCP-aware clients that need a stable tool list and a tool-call bridge without receiving upstream secrets or raw provider URLs.

Use the demo agent token generated by `make demo-seed`:

```bash
source .grantora-demo.env

curl -sS 'http://localhost:9080/v1/mcp/tools?user=alice' \
  -H "Authorization: Bearer $DEMO_AGENT_TOKEN"
```

Call the generated demo tool through the MCP bridge:

```bash
curl -sS -X POST http://localhost:9080/v1/mcp/call \
  -H "Authorization: Bearer $DEMO_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user":"alice","name":"mock_phonebook_search","arguments":{"query":"Mario","limit":5}}'
```

Operational rules:

- `/v1/mcp/tools` is generated from the same filtered capability set as `/v1/capabilities/openapi.json`.
- `/v1/mcp/call` maps a tool name back to the matching capability and then uses the same executor as `POST /v1/invoke/{capability_id}`.
- Unknown or unauthorized tool names fail closed and still create audit and usage records.
- Responses include normalized adapter data and Grantora metadata only; they do not include upstream URLs, secrets or raw upstream response bodies.

## Integration And E2E Validation

Run unit tests without external services:

```bash
make test-unit
```

Run PostgreSQL and APISIX integration tests against local compose services or another disposable environment:

```bash
export GRANTORA_INTEGRATION_DATABASE_URL='postgresql+psycopg://grantora:grantora@localhost:5432/grantora'
export GRANTORA_INTEGRATION_APISIX_ADMIN_URL='http://localhost:9180'
export GRANTORA_INTEGRATION_APISIX_ADMIN_KEY="$APISIX_ADMIN_KEY"
make test-integration
```

The PostgreSQL integration fixture creates a temporary schema and drops it after the test, so it does not reset the whole database. If the integration variables are absent, the tests skip; if they are set but PostgreSQL or APISIX is unavailable, the tests fail.

Run e2e tests through APISIX after the compose stack is up and the admin bootstrap token is available:

```bash
export GRANTORA_RUN_E2E=1
export GRANTORA_E2E_API_URL='http://localhost:8080'
export GRANTORA_E2E_RUNTIME_URL='http://localhost:9080'
make test-e2e
```

The e2e suite seeds a unique demo workspace through Admin APIs, syncs APISIX, verifies discovery and invocation through `http://localhost:9080`, and checks that denied, missing-secret and upstream-error attempts have audit and usage records.

Run the destructive backup and restore smoke flow only against disposable compose state:

```bash
export GRANTORA_RUN_BACKUP_RESTORE_SMOKE=1
make backup-restore-smoke
```

That workflow seeds the demo, writes a PostgreSQL custom dump, tears down compose volumes, restores PostgreSQL from the dump, waits for Grantora readiness, resyncs APISIX and verifies a demo capability invocation still succeeds.

Provider adapter integration tests use sanitized mock upstream payloads and `httpx` transports, so they do not require network access to NethVoice or Nextcloud.

## Provider Capability Templates

Grantora ships built-in capability templates for common real adapters:

- `nethvoice.phonebook.search`
- `nextcloud.files.search`

List templates:

```bash
curl -sS 'http://localhost:8080/v1/admin/capability-templates' \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

Create a capability from a template after creating the matching application instance:

```bash
curl -sS -X POST http://localhost:8080/v1/admin/capabilities/from-template \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "template_id": "nextcloud.files.search",
    "workspace_id": "<workspace-id>",
    "application_instance_id": "<nextcloud-application-id>",
    "id": "nextcloud.files.search.demo"
  }'
```

Templates include JSON Schemas, adapter ids, required secret types and required upstream permissions. They never include provider base URLs, tokens or passwords.

## APISIX Bootstrap

Grantora stores desired APISIX routes in PostgreSQL and reconciles them through the APISIX Admin API.

Automatic sync is controlled by:

- `APISIX_SYNC_ENABLED`: when true, Grantora runs one startup sync and then schedules background reconciliation.
- `APISIX_SYNC_INTERVAL_SECONDS`: interval between background reconciliation attempts.
- `APISIX_FAIL_CLOSED`: when true, Grantora preloads current APISIX route state before writing so Admin API read failures preserve the last known route state.

Operational rules:

- PostgreSQL desired state wins.
- Manual APISIX changes may be overwritten.
- APISIX Admin API must be internal-only outside local development.
- Local compose binds the APISIX Admin API to `127.0.0.1:${APISIX_ADMIN_PORT:-9180}`; do not publish it on public interfaces in production examples.
- Public APISIX routes expose runtime endpoints only; admin endpoints stay on the direct Grantora API and require the admin bootstrap token.
- Failed sync must not open access broader than the previous safe route state.

Manual sync endpoint:

```bash
curl -X POST http://localhost:8080/v1/admin/apisix/sync \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

Check last sync status and optional route drift:

```bash
curl -sS 'http://localhost:8080/v1/admin/apisix/status?include_drift=true' \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

When APISIX terminates TLS, set `GRANTORA_PUBLIC_BASE_URL` to the external HTTPS URL, for example `https://gateway.example.test`. Runtime OpenAPI and filtered capability OpenAPI use that URL in their `servers` list so agents do not learn internal container URLs.

## Health Checks

Required endpoints:

- `/healthz`: process is alive.
- `/readyz`: database and required dependencies are reachable.
- `/metrics`: Prometheus-compatible metrics when enabled.

## Logs

Logs must be structured JSON in production. Required fields include timestamp, level, request id, workspace id when known, agent id when known, user id when known, capability id when known and message.

Never log secrets, tokens, authorization headers, cookies or raw sensitive payloads.

Denied and failed runtime invocation paths also emit structured runtime logs with safe decision, outcome and error code fields so operators can correlate audit records with request logs.

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
- Any external secret backend references and backend configuration when used

Do not rely on APISIX etcd as the source of truth. APISIX state is generated from PostgreSQL and should be reconstructable by reconciliation.

Local backup example:

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > grantora.dump
cp .env grantora.env.backup
```

Local restore example into a clean compose environment:

```bash
docker compose down -v
cp grantora.env.backup .env
docker compose up -d postgres
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < grantora.dump
docker compose up -d grantora-api apisix-etcd apisix
docker compose exec grantora-api alembic upgrade head
curl -X POST http://localhost:8080/v1/admin/apisix/sync \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

Validated shortcut for local disposable environments:

```bash
make backup-restore-smoke
```

Restore order:

1. Restore environment secrets.
2. Restore PostgreSQL.
3. Run migrations if needed.
4. Start Grantora API.
5. Reconcile APISIX routes.
6. Verify `/readyz`, `/metrics` and a demo capability invocation.

Acceptance test: restoring into a clean local environment must recreate workspaces, application instances, agents, users, capabilities, bindings, encrypted secrets, audit events, usage events and APISIX desired route state from PostgreSQL. A fresh APISIX reconciliation must recreate generated APISIX runtime routes.

## Troubleshooting Runbook

Invalid admin hash:

```bash
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

Use the output to replace `GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH` when requests return `admin_auth_invalid` or `admin_auth_unavailable`.

Bad Fernet key:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

If requests fail with `secret_unavailable`, verify the restored `SECRET_ENCRYPTION_KEY` matches the key that encrypted the stored secrets. Rotating the key without re-encrypting data will make old ciphertext unreadable.

Missing secret:

```bash
curl -sS 'http://localhost:8080/v1/admin/secrets?workspace_id=<workspace-id>&owner_type=user&owner_id=<user-id>' \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

If runtime returns `secret_not_found`, confirm there is one active secret for the expected owner and application instance, and rerun `make demo-seed` for the demo workflow if the local demo secret was removed.

APISIX Admin API unavailable:

```bash
curl -sS 'http://localhost:8080/v1/admin/apisix/status?include_drift=true' \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
```

If sync reports `apisix_admin_unavailable`, verify `APISIX_ADMIN_URL`, `APISIX_ADMIN_KEY`, the local `127.0.0.1:${APISIX_ADMIN_PORT:-9180}` binding and container reachability before retrying `POST /v1/admin/apisix/sync`.

Migration failure:

```bash
docker compose exec grantora-api python -m alembic upgrade head
```

If startup fails before the API is ready, run the migration manually to surface the schema error, then inspect container logs and the latest migration for incompatible changes.

Upstream timeout:

```bash
curl -sS http://localhost:8080/metrics | grep 'grantora_upstream_\|grantora_secret_resolution_'
```

If runtime returns `upstream_timeout`, confirm the upstream base URL, `UPSTREAM_TIMEOUT_SECONDS`, `UPSTREAM_CONNECT_TIMEOUT_SECONDS`, TLS settings and the user or workspace secret are correct before retrying.

## Upgrade Rules

- Apply database migrations before enabling code that depends on them.
- Keep old route state safe until APISIX reconciliation succeeds.
- Preserve backward-compatible error codes unless [CONTRACTS.md](CONTRACTS.md) is updated.
- Document any required secret rotation or re-encryption step.

## Future NS8 Packaging Notes

The NS8 module should package and manage upstream Grantora; it should not fork Grantora logic.

The module may generate environment files, manage containers, configure backup and restore, expose actions, integrate with account domains and connect to NS8 UI. The upstream application must continue to run outside NS8 with environment variables and PostgreSQL.