# CONTRACTS.md

This file defines the contracts implementation must follow. Update it before changing public APIs, database schema, capability shape, adapter interfaces, audit/usage shape or APISIX route shape.

## Runtime API

All runtime endpoints require `Authorization: Bearer <agent_token>` unless explicitly documented otherwise.

Agent bearer tokens are looked up by the stored `hmac-sha256:<hex>` hash. The plaintext token is returned only by the admin creation response and is never returned by runtime APIs.

### GET /v1/me

Returns the authenticated agent context.

Response fields:

```json
{
  "agent": {
    "id": "uuid",
    "slug": "hermes-alice",
    "display_name": "Hermes Alice",
    "status": "active"
  },
  "workspace": {
    "id": "uuid",
    "slug": "acme",
    "display_name": "Acme SRL",
    "status": "active"
  }
}
```

### GET /v1/capabilities

Returns capabilities visible to the authenticated agent for a selected user.

Query parameters:

- `user`: required user external id for user-scoped capabilities.

Rules:

- Return only active capabilities with an active binding for the agent and user.
- Return schema and safe metadata only.
- Do not return upstream URLs, secrets or adapter private configuration.

### GET /v1/openapi.json

Returns the static OpenAPI document for the authenticated runtime API.

Rules:

- Include runtime endpoints only.
- Do not include admin APIs, health APIs or observability APIs.
- Do not include upstream URLs, secrets or adapter private configuration.

### GET /v1/capabilities/openapi.json

Returns a filtered OpenAPI document for the authenticated agent and selected user.

Query parameters:

- `user`: required user external id.

Rules:

- Include only allowed capabilities.
- Use stable operation ids derived from capability ids.
- Include capability-specific invocation paths that map back to capability ids.
- Do not include admin APIs.

### MCP-compatible tool list

The internal tool-list generator produces MCP-compatible tool descriptors from the same filtered capability set used by `GET /v1/capabilities/openapi.json`.

Rules:

- Tool names are stable and derived from capability ids.
- Each tool descriptor includes the capability input schema.
- Each tool descriptor includes metadata mapping back to the Grantora capability id and invocation path.
- Do not include upstream URLs, secrets or adapter private configuration.

### POST /v1/invoke/{capability_id}

Invokes a capability through the capability executor.

Request body:

```json
{
  "user": "alice",
  "input": {
    "query": "Mario",
    "limit": 10
  }
}
```

Success response:

```json
{
  "request_id": "req_01j...",
  "capability": "nethvoice.phonebook.search",
  "status": "ok",
  "data": {}
}
```

Rules:

- Authenticate the agent.
- Validate workspace, agent, user, capability, binding and role permission.
- Validate input against the capability input schema.
- Resolve the upstream secret according to [SECURITY.md](SECURITY.md).
- Invoke the adapter through the adapter protocol.
- Write audit and usage records for success, error and denied outcomes.

### GET /v1/usage/me

Returns usage summary for the authenticated agent. It must not expose other agents unless authorized by a future admin contract.

## Admin API

Admin endpoints require admin authentication. The MVP uses an admin bootstrap token hash from environment configuration.

Admin clients authenticate with `Authorization: Bearer <admin_bootstrap_token>`. Grantora verifies this token against `ADMIN_BOOTSTRAP_TOKEN_HASH` using the same peppered token hash format as agent tokens.

Required endpoints:

- `POST /v1/admin/workspaces`
- `GET /v1/admin/workspaces`
- `POST /v1/admin/applications`
- `GET /v1/admin/applications`
- `POST /v1/admin/capabilities`
- `GET /v1/admin/capabilities`
- `POST /v1/admin/agents`
- `GET /v1/admin/agents`
- `POST /v1/admin/bindings`
- `GET /v1/admin/bindings`
- `POST /v1/admin/secrets`
- `GET /v1/admin/audit`
- `GET /v1/admin/usage`
- `POST /v1/admin/apisix/sync`
- `GET /v1/admin/apisix/status`

Admin `POST` endpoints must validate workspace ownership and write audit records for security-relevant changes.

### POST /v1/admin/agents

Creates an agent in an active workspace and returns its bearer token exactly once.

Request body:

```json
{
  "workspace_id": "uuid",
  "slug": "hermes-alice",
  "display_name": "Hermes Alice"
}
```

Success response:

```json
{
  "agent": {
    "id": "uuid",
    "workspace_id": "uuid",
    "slug": "hermes-alice",
    "display_name": "Hermes Alice",
    "status": "active"
  },
  "token": "grt_agent_..."
}
```

Rules:

- Store only `token_hash` and `token_hash_algorithm` on the agent record.
- Do not return `token`, `token_hash` or `token_hash_algorithm` from list or runtime responses.
- Creating an agent in a missing or disabled workspace fails safely.

### GET /v1/admin/agents

Returns agent metadata for admin inspection. It never returns plaintext tokens or token hashes.

Optional query parameters:

- `workspace_id`: filter agents to one workspace.

### POST /v1/admin/apisix/sync

Reconciles PostgreSQL APISIX route desired state to the APISIX Admin API.

Success response:

```json
{
  "request_id": "req_01j...",
  "status": "ok",
  "last_started_at": null,
  "last_finished_at": null,
  "checked_routes": 1,
  "changed_routes": 1,
  "error": null
}
```

Safe sync failure response:

```json
{
  "request_id": "req_01j...",
  "status": "error",
  "last_started_at": null,
  "last_finished_at": null,
  "checked_routes": 1,
  "changed_routes": 0,
  "error": {
    "code": "apisix_admin_unavailable",
    "message": "APISIX Admin API is unavailable"
  }
}
```

Rules:

- Authenticate the admin bootstrap token.
- Seed the default `gateway-runtime` desired route when absent.
- Compare current APISIX route state before writing.
- Running sync twice without desired-state changes must not perform a second APISIX update.
- Responses must not include the APISIX Admin URL, API key, upstream response body or stack trace.

### GET /v1/admin/apisix/status

Returns the last APISIX sync status, or `never_run` when no sync has been attempted.

Response fields:

```json
{
  "status": "never_run | ok | error",
  "last_started_at": "datetime | null",
  "last_finished_at": "datetime | null",
  "checked_routes": 0,
  "changed_routes": 0,
  "error": null
}
```

Rules:

- Authenticate the admin bootstrap token.
- Return only stable error codes and safe messages.
- Do not expose APISIX Admin URL, API key, internal URLs, raw response bodies or stack traces.

## Standard Error Response

```json
{
  "request_id": "req_01j...",
  "status": "error",
  "error": {
    "code": "capability_denied",
    "message": "Capability is not allowed for this agent and user"
  }
}
```

Rules:

- `request_id` is always present.
- `error.code` is stable and machine-readable.
- `error.message` is safe for agents.
- Responses must not include secrets, stack traces, internal service URLs or raw upstream bodies.

## Capability Contract

```yaml
id: nethvoice.phonebook.search
name: Search phonebook
version: 1
workspace_id: uuid
application_instance_id: uuid
provider_type: nethvoice
adapter: nethvoice
operation: phonebook.search
auth_mode: user
risk_class: read_only
input_schema:
  type: object
  properties:
    query:
      type: string
      minLength: 1
    limit:
      type: integer
      minimum: 1
      maximum: 50
  required:
    - query
  additionalProperties: false
output_schema:
  type: object
  properties:
    contacts:
      type: array
      items:
        type: object
        properties:
          display_name:
            type: string
          phone:
            type: string
          company:
            type: string
          source:
            type: string
            const: nethvoice
        required:
          - display_name
          - phone
          - company
          - source
        additionalProperties: false
  required:
    - contacts
  additionalProperties: false
```

Valid `auth_mode` values: `system`, `user`, `user+scope`, `admin`.

Valid `risk_class` values: `read_only`, `draft`, `side_effect`, `destructive`, `admin`.

## Binding Contract

```yaml
id: uuid
workspace_id: uuid
agent_id: uuid
user_id: uuid
capability_id: nethvoice.phonebook.search
role_id: uuid
status: active
```

Authorization requires an active binding for the same workspace, agent, user and capability.

## Secret Contract

```yaml
id: uuid
workspace_id: uuid
application_instance_id: uuid
owner_type: workspace | user | agent
owner_id: uuid
secret_type: api_key | bearer_token | basic_auth | oauth_refresh_token | session_cookie
encrypted_value: opaque-ciphertext
status: active | revoked
```

Secrets are encrypted before storage, decrypted only in memory during invocation and never returned through APIs.

## Audit Event Contract

```yaml
id: uuid
timestamp: datetime
request_id: string
workspace_id: uuid
agent_id: uuid | null
user_id: uuid | null
capability_id: string | null
application_instance_id: uuid | null
decision: allow | deny
outcome: success | error
error_code: string | null
latency_ms: integer
remote_addr: string | null
```

Denied requests must be audited even when no adapter is invoked.

## Usage Event Contract

```yaml
id: uuid
timestamp: datetime
workspace_id: uuid
agent_id: uuid
user_id: uuid | null
capability_id: string
application_instance_id: uuid | null
units: integer
status: success | error | denied
latency_ms: integer
```

## Database Entities

Required tables:

```text
workspaces
application_instances
capabilities
agents
users
roles
permissions
role_permissions
bindings
secrets
audit_events
usage_events
apisix_routes
apisix_sync_status
```

Required indexes:

```sql
CREATE INDEX idx_bindings_lookup
ON bindings (workspace_id, agent_id, user_id, capability_id, status);

CREATE INDEX idx_audit_workspace_time
ON audit_events (workspace_id, timestamp DESC);

CREATE INDEX idx_usage_workspace_time
ON usage_events (workspace_id, timestamp DESC);

CREATE INDEX idx_capabilities_workspace_status
ON capabilities (workspace_id, status);
```

## Migration Rules

- Use Alembic for every schema change.
- Migrations must be deterministic and safe to run once.
- Add indexes in the same migration as new lookup paths.
- Do not drop or rewrite security-relevant data without an explicit migration note.
- Update this file before implementing schema changes.

## APISIX Route Contract

Desired APISIX route state is stored in PostgreSQL and reconciled through the APISIX Admin API.

`apisix_routes` fields:

```yaml
id: string
name: string
uri: string
upstream: object
plugins: object
status: active | disabled
created_at: datetime
updated_at: datetime
```

`apisix_sync_status` fields:

```yaml
id: default
status: ok | error
last_started_at: datetime | null
last_finished_at: datetime | null
checked_routes: integer
changed_routes: integer
error_code: string | null
safe_message: string | null
```

```yaml
id: gateway-runtime
uri: /v1/*
upstream:
  type: roundrobin
  nodes:
    grantora-api:8080: 1
plugins:
  prometheus: {}
  request-id: {}
  limit-count:
    count: 1000
    time_window: 60
    rejected_code: 429
```

Rules:

- PostgreSQL desired state wins.
- Reconciliation must be idempotent.
- Unsafe sync failures must leave existing safe routes in place.
- Manual APISIX changes may be overwritten.