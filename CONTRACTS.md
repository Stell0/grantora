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
- `limit`, `offset`: bounded pagination.

Rules:

- Return only active capabilities with an active binding for the agent and user.
- Select the runtime user by the `user` external id inside the authenticated agent's workspace; missing or disabled users return an empty capability set.
- Require the role to grant both `capability.describe` and the capability risk class's runtime invoke permission.
- Return schema and safe metadata only.
- Do not return upstream URLs, secrets or adapter private configuration.

### GET /v1/openapi.json

Returns the static OpenAPI document for the authenticated runtime API.

Rules:

- Include runtime endpoints only.
- Include a `servers` entry using `GRANTORA_PUBLIC_BASE_URL` when configured.
- Do not include admin APIs, health APIs or observability APIs.
- Do not include upstream URLs, secrets or adapter private configuration.

### GET /v1/capabilities/openapi.json

Returns a filtered OpenAPI document for the authenticated agent and selected user.

Query parameters:

- `user`: required user external id.

Rules:

- Include only allowed capabilities.
- Include a `servers` entry using `GRANTORA_PUBLIC_BASE_URL` when configured.
- Use stable operation ids derived from capability ids. If multiple allowed capability ids normalize to the same tool name, append deterministic hash suffixes so generated operation ids remain unique.
- Include capability-specific invocation paths that map back to capability ids.
- Do not include admin APIs.

### GET /v1/mcp/tools

Returns an MCP-compatible tool list for the authenticated agent and selected user. Grantora's product MCP surface is authenticated HTTP JSON under the runtime API; it does not expose a streaming MCP session or stdio server in this milestone.

Query parameters:

- `user`: required user external id.

Rules:

- Build the list from the same filtered capability set used by `GET /v1/capabilities/openapi.json`.
- Tool names are stable and derived from capability ids. If multiple allowed capability ids normalize to the same name, Grantora appends deterministic hash suffixes.
- Each tool descriptor includes the capability input schema.
- Each tool descriptor includes metadata mapping back to the Grantora capability id and invocation path.
- Do not include upstream URLs, secrets or adapter private configuration.

### POST /v1/mcp/call

Maps an MCP-style tool call to the same capability executor used by `POST /v1/invoke/{capability_id}`.

Request body:

```json
{
  "user": "alice",
  "name": "nethvoice_phonebook_search",
  "arguments": {
    "query": "Mario",
    "limit": 10
  }
}
```

Success response:

```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"contacts\":[]}"
    }
  ],
  "structuredContent": {
    "contacts": []
  },
  "isError": false,
  "_meta": {
    "grantora/request_id": "req_01j...",
    "grantora/capability_id": "nethvoice.phonebook.search"
  }
}
```

Rules:

- Resolve `name` only against the authenticated agent and selected user's allowed MCP tool list.
- Enforce the same user, binding, permission, secret resolution, input validation, adapter dispatch, output validation, audit and usage rules as `POST /v1/invoke/{capability_id}`.
- Unknown or unauthorized tool names fail closed with the standard safe `capability_denied` response.
- The response exposes normalized adapter data only, never upstream URLs, secrets or raw upstream response bodies.

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
- Select the runtime user from the request body by external id inside the authenticated agent's workspace.
- Validate workspace, agent, user, capability, binding, role status and role permissions.
- Require both `capability.describe` and the risk-specific invoke permission.
- Deny capabilities with risk class `admin`; runtime agents have no admin-risk invoke permission in this contract.
- Validate input against the capability input schema.
- Resolve the upstream secret according to [SECURITY.md](SECURITY.md).
- Invoke the adapter through the adapter protocol.
- Write audit and usage records for success, error and denied outcomes.

### GET /v1/usage/me

Returns usage summary for the authenticated agent. It must not expose other agents unless authorized by a future admin contract.

Optional query parameters:

- `user_id`, `capability_id`, `status`: filter the authenticated agent's usage records.
- `start_time`, `end_time`: inclusive timestamp range filters.
- `limit`, `offset`: bounded pagination.

Success response includes:

- `usage`: matching usage events for the authenticated agent ordered newest first.
- `summaries`: aggregates grouped by workspace, agent, user, capability and status with event counts and total units.

Rules:

- The authenticated agent id is always enforced server-side and cannot be overridden.
- Responses never include bearer tokens, secret values, encrypted values, raw request bodies or upstream response bodies.

## Observability API

### GET /healthz

Returns process liveness for container and load balancer checks.

Response fields:

```json
{
  "status": "ok",
  "service": "grantora-api",
  "environment": "production",
  "version": "0.1.0"
}
```

Rules:

- Must not require authentication.
- Must not connect to PostgreSQL or upstream providers.
- Must include the running Grantora package version so published images can report their version after startup.

### GET /readyz

Returns readiness for serving traffic.

Rules:

- Must not require authentication.
- Must verify PostgreSQL reachability.
- Must return a safe error response without stack traces or internal connection details when dependencies are unavailable.

### GET /metrics

Returns Prometheus-compatible metrics when `METRICS_ENABLED=true`.

Rules:

- The endpoint is not part of runtime OpenAPI or filtered capability OpenAPI.
- Metrics must not expose secrets, bearer tokens, authorization headers, cookies, raw request payloads or raw upstream response bodies.
- Required metric families:
  - `grantora_requests_total{workspace,agent,user,capability,status}`
  - `grantora_request_duration_seconds{workspace,capability,provider}`
  - `grantora_authorization_denied_total{workspace,reason}`
  - `grantora_upstream_requests_total{workspace,provider,status}`
  - `grantora_upstream_errors_total{workspace,provider,error_code}`
  - `grantora_secret_resolution_total{workspace,provider,result}`
  - `grantora_apisix_sync_total{status}`
  - `grantora_apisix_sync_duration_seconds`

## Admin API

Admin endpoints require admin authentication. Bootstrap admin access uses an environment-provided token hash. DB-backed admin credentials may also authenticate with the same bearer-token hash format and can be scoped to one workspace. Optional OIDC/NS8 admin identity is disabled by default and only accepts explicitly allowlisted subjects from trusted proxy addresses when enabled.

Admin clients authenticate with `Authorization: Bearer <admin_token>`. Grantora verifies bootstrap tokens against `ADMIN_BOOTSTRAP_TOKEN_HASH`, or DB-backed admin credentials against the `admin_credentials.token_hash` column, using the same peppered token hash format as agent tokens. OIDC admin subjects are read from `OIDC_SUBJECT_HEADER` only when `FEATURE_OIDC=true`, the request client address matches `OIDC_TRUSTED_PROXY_CIDRS`, and the subject appears in `OIDC_ADMIN_SUBJECTS`.

Rules:

- Bootstrap and allowlisted OIDC admins are super admins.
- DB-backed admin credentials with `workspace_id=null` are super admins.
- DB-backed admin credentials with a workspace id can only create, list, update or inspect resources in that workspace.
- Scoped admins cannot run APISIX sync/status or create global permissions.
- Agent bearer tokens are never valid admin credentials.
- Slugs, provider ids, adapter ids, operation ids, capability ids, permission codes and external user ids must match the constrained identifier patterns implemented by request schemas.
- Application `base_url` values must be HTTP or HTTPS origins with no credentials, path, query, fragment, localhost name, bare host name or literal private/local address.
- Request bodies larger than `MAX_REQUEST_BODY_BYTES` fail before route handlers with safe `request_body_too_large` errors.
- Capability schemas must be bounded object schemas, must set top-level `additionalProperties=false`, and must not contain `$ref` or `$dynamicRef` references.
- Raw upstream passthrough capability definitions are rejected by default.

Required endpoints:

- `POST /v1/admin/workspaces`
- `GET /v1/admin/workspaces`
- `PATCH /v1/admin/workspaces/{workspace_id}`
- `POST /v1/admin/applications`
- `GET /v1/admin/applications`
- `PATCH /v1/admin/applications/{application_id}`
- `POST /v1/admin/users`
- `GET /v1/admin/users`
- `POST /v1/admin/capabilities`
- `GET /v1/admin/capabilities`
- `POST /v1/admin/roles`
- `GET /v1/admin/roles`
- `PATCH /v1/admin/roles/{role_id}`
- `POST /v1/admin/permissions`
- `GET /v1/admin/permissions`
- `POST /v1/admin/agents`
- `GET /v1/admin/agents`
- `POST /v1/admin/agents/{agent_id}/rotate-token`
- `PATCH /v1/admin/agents/{agent_id}`
- `POST /v1/admin/bindings`
- `GET /v1/admin/bindings`
- `PATCH /v1/admin/bindings/{binding_id}`
- `POST /v1/admin/secrets`
- `GET /v1/admin/secrets`
- `PATCH /v1/admin/secrets/{secret_id}`
- `POST /v1/admin/secrets/{secret_id}/rotate`
- `GET /v1/admin/audit`
- `GET /v1/admin/usage`
- `POST /v1/admin/apisix/sync`
- `GET /v1/admin/apisix/status`

Admin write endpoints must validate workspace ownership when a resource belongs to a workspace and write safe audit records for security-relevant changes. Global admin writes, such as permission creation, write audit records with `workspace_id=null`.

Admin list endpoints that expose stateful resources use `include_disabled=false` by default. When supported, `include_disabled=true` also returns disabled or revoked rows for operator inspection.

### POST /v1/admin/workspaces

Creates a workspace.

Request body:

```json
{
  "slug": "acme",
  "display_name": "Acme SRL",
  "status": "active"
}
```

Success response:

```json
{
  "workspace": {
    "id": "uuid",
    "slug": "acme",
    "display_name": "Acme SRL",
    "status": "active"
  }
}
```

Rules:

- Workspace slugs are globally unique.
- Valid statuses are `active` and `disabled`.
- Disabled workspaces are hidden from default admin lists and are not valid parents for new dynamic objects.

### GET /v1/admin/workspaces

Returns workspace metadata.

Optional query parameters:

- `include_disabled`: include disabled workspaces when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/workspaces/{workspace_id}

Updates a workspace lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Disabled workspaces are hidden from default admin lists and are not valid parents for new dynamic objects.
- The update writes a safe admin audit record.

### POST /v1/admin/applications

Creates an application instance in an active workspace.

Request body:

```json
{
  "workspace_id": "uuid",
  "slug": "nethvoice",
  "display_name": "NethVoice",
  "provider_type": "nethvoice",
  "base_url": "https://nethvoice.example.test",
  "status": "active"
}
```

Success response wraps an `application` object with `id`, `workspace_id`, `slug`, `display_name`, `provider_type`, `base_url` and `status`.

Rules:

- Application slugs are unique per workspace.
- Creating an application in a missing or disabled workspace fails safely.
- `base_url` is constrained to an origin such as `https://nethvoice.example.test`; it cannot include provider paths, credentials, localhost/private addresses, query strings or fragments.
- Admin application responses may include the configured `base_url`, but must never include secrets or provider credentials.

### GET /v1/admin/applications

Returns application instance metadata.

Optional query parameters:

- `workspace_id`: filter to one workspace.
- `include_disabled`: include disabled application instances when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/applications/{application_id}

Updates an application instance lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Re-activating an application requires its workspace to be active.
- Disabled applications are hidden from default admin lists and their capabilities cannot be discovered or invoked.
- The update writes a safe admin audit record.

### POST /v1/admin/users

Creates a user identity in an active workspace.

Request body:

```json
{
  "workspace_id": "uuid",
  "external_id": "alice",
  "display_name": "Alice",
  "status": "active"
}
```

Success response wraps a `user` object with `id`, `workspace_id`, `external_id`, `display_name` and `status`.

Rules:

- User external ids are unique per workspace.
- Disabled users are hidden from default admin lists and from runtime user lookup.

### GET /v1/admin/users

Returns user metadata.

Optional query parameters:

- `workspace_id`: filter to one workspace.
- `include_disabled`: include disabled users when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/users/{user_id}

Updates a user lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Disabled users are not valid runtime users for discovery or invocation.
- The update writes a safe admin audit record.

### POST /v1/admin/capabilities

Creates a capability bound to an application instance in an active workspace.

Request body follows the [Capability Contract](#capability-contract).

Success response wraps a `capability` object with all capability contract metadata except private adapter configuration.

Rules:

- Capability ids are globally unique stable identifiers.
- Capability ids, names, provider types, adapter ids, operations, auth modes, risk classes and schemas are validated before persistence.
- The referenced application instance must belong to the same active workspace.
- `input_schema` and `output_schema` must be valid JSON Schemas.
- Valid `auth_mode` and `risk_class` values are the values documented in the capability contract.
- Private adapter configuration is not accepted in the capability create contract.

### GET /v1/admin/capability-templates

Returns built-in capability templates for supported provider adapters.

Optional query parameters:

- `provider_type`: filter templates to one provider type.
- `limit`, `offset`: bounded pagination.

Success response wraps a `templates` array. Each template includes `id`, `name`, `version`, `provider_type`, `adapter`, `operation`, `auth_mode`, `risk_class`, `input_schema`, `output_schema`, `required_secret_types` and `upstream_permissions`.

Rules:

- Templates contain safe setup metadata only; they must not include base URLs, secrets, tokens or provider-private configuration.
- Built-in templates are validated against the capability definition rules before they are exposed or instantiated.
- Template schemas are the canonical examples for creating common capabilities without hand-writing JSON Schema.

### POST /v1/admin/capabilities/from-template

Creates a capability from a built-in template.

Request body:

```json
{
  "template_id": "nextcloud.files.search",
  "workspace_id": "uuid",
  "application_instance_id": "uuid",
  "id": "nextcloud.files.search",
  "name": "Search files",
  "version": 1,
  "status": "active"
}
```

`id`, `name` and `version` are optional overrides. When omitted, the template values are used.

Success response is the same as `POST /v1/admin/capabilities`.

Rules:

- The referenced application instance must belong to the same active workspace.
- The application provider type must match the selected template provider type.
- Unknown templates fail with `capability_template_not_found`.
- Created capabilities still use globally unique capability ids.

### GET /v1/admin/capabilities

Returns capability metadata.

Optional query parameters:

- `workspace_id`: filter to one workspace.
- `application_instance_id`: filter to one application instance.
- `include_disabled`: include disabled capabilities when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/capabilities/{capability_id}

Updates a capability lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Disabled capabilities cannot be discovered or invoked.
- Capabilities with `risk_class=admin` are never available through runtime discovery or invocation in the MVP.
- The update writes a safe admin audit record.

### POST /v1/admin/permissions

Creates or registers a global permission code. Grantora also seeds the built-in capability permissions deterministically when roles are created or permissions are listed.

Request body:

```json
{
  "code": "capability.invoke.read_only",
  "description": "Invoke read-only capabilities"
}
```

Rules:

- Permission codes are globally unique.
- Built-in permission codes are `capability.describe`, `capability.invoke.read_only`, `capability.invoke.side_effect` and `capability.invoke.destructive`.
- The write requires a super-admin principal and writes a safe global admin audit record with `workspace_id=null`.

### GET /v1/admin/permissions

Returns registered permission codes.

Optional query parameters:

- `limit`, `offset`: bounded pagination.

Rules:

- Built-in permission seeding is idempotent and includes exactly `capability.describe`, `capability.invoke.read_only`, `capability.invoke.side_effect` and `capability.invoke.destructive`.

### POST /v1/admin/roles

Creates a role in an active workspace and attaches existing permission codes.

Request body:

```json
{
  "workspace_id": "uuid",
  "slug": "phonebook-reader",
  "display_name": "Phonebook reader",
  "permission_codes": [
    "capability.describe",
    "capability.invoke.read_only"
  ],
  "status": "active"
}
```

Success response wraps a `role` object with `id`, `workspace_id`, `slug`, `display_name`, `permission_codes` and `status`.

Rules:

- Role slugs are unique per workspace.
- Unknown permission codes are rejected.
- Runtime discovery requires `capability.describe` plus the risk-specific invoke permission.

### GET /v1/admin/roles

Returns role metadata and attached permission codes.

Optional query parameters:

- `workspace_id`: filter to one workspace.
- `include_disabled`: include disabled roles when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/roles/{role_id}

Updates a role lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Re-activating a role requires its workspace to be active.
- Disabled roles deny runtime discovery and invocation immediately.
- The update writes a safe admin audit record.

### POST /v1/admin/bindings

Creates an authorization binding between a workspace, agent, user, capability and role.

Request body follows the [Binding Contract](#binding-contract), without `id`.

Rules:

- The workspace, agent, user, capability and role must all be active.
- The agent, user, capability and role must all belong to the binding workspace.
- Cross-workspace bindings are rejected.

### GET /v1/admin/bindings

Returns binding metadata.

Optional query parameters:

- `workspace_id`, `agent_id`, `user_id`, `capability_id`, `role_id`: filter bindings.
- `include_disabled`: include disabled bindings when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/bindings/{binding_id}

Updates a binding lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Disabled bindings deny runtime discovery and invocation immediately.
- The update writes a safe admin audit record.

### POST /v1/admin/secrets

Stores an upstream secret encrypted at rest, or stores an encrypted external secret reference that will be resolved by a configured external backend in a future deployment.

Request body:

```json
{
  "workspace_id": "uuid",
  "application_instance_id": "uuid",
  "owner_type": "user",
  "owner_id": "uuid",
  "secret_type": "bearer_token",
  "value": "plaintext-secret"
}
```

External reference request body:

```json
{
  "workspace_id": "uuid",
  "application_instance_id": "uuid",
  "owner_type": "user",
  "owner_id": "uuid",
  "secret_type": "bearer_token",
  "external_reference": "vault://grantora/alice-token"
}
```

Success response wraps a metadata-only `secret` object with `id`, `workspace_id`, `application_instance_id`, `owner_type`, `owner_id`, `secret_type` and `status`.

Rules:

- Exactly one of `value` or `external_reference` must be provided.
- `value` or the external reference marker is encrypted before persistence and is never returned.
- `encrypted_value` is never returned.
- External references fail closed with `secret_unavailable` unless an explicit external secret backend is enabled and able to resolve the reference.
- The application instance must belong to the same active workspace.
- `owner_type=workspace` requires `owner_id` to match the workspace id.
- `owner_type=user` and `owner_type=agent` require an active owner in the same workspace.

### GET /v1/admin/secrets

Returns metadata-only secret records.

Optional query parameters:

- `workspace_id`, `application_instance_id`, `owner_type`, `owner_id`: filter secrets.
- `include_revoked`: include revoked secrets when true.
- `limit`, `offset`: bounded pagination.

### PATCH /v1/admin/secrets/{secret_id}

Updates a secret status.

Request body:

```json
{
  "status": "revoked"
}
```

Rules:

- Valid statuses are `active` and `revoked`.
- Revoked secrets are not selected during runtime invocation.
- The update writes a safe admin audit record.

### POST /v1/admin/secrets/{secret_id}/rotate

Revokes an active secret and creates a replacement in one transaction.

Request body:

```json
{
  "value": "new-plaintext-secret",
  "secret_type": "bearer_token"
}
```

Rotation may use `external_reference` instead of `value`, with the same exactly-one-source rule as secret creation.

Success response includes metadata for the replacement `secret` and the `revoked_secret`. `secret_type` is optional and defaults to the old secret type.

Rules:

- The old secret must exist and be active.
- The replacement uses the same workspace, application instance, owner type and owner id as the old secret.
- The old secret is revoked before commit and cannot be selected by runtime invocation after the rotation commits.
- Plaintext and encrypted secret values are never returned.
- The update writes a safe admin audit record.

### GET /v1/admin/audit

Returns safe audit events.

Optional query parameters:

- `workspace_id`, `actor_type`, `agent_id`, `user_id`, `capability_id`, `decision`, `outcome`: filter audit events.
- `start_time`, `end_time`: inclusive timestamp range filters.
- `limit`, `offset`: bounded pagination.

Rules:

- Results are ordered by newest event first, with stable id ordering for ties.
- Responses never include bearer tokens, secret values, encrypted values, raw request bodies or upstream response bodies.

### GET /v1/admin/usage

Returns usage events and aggregate summaries.

Optional query parameters:

- `workspace_id`, `agent_id`, `user_id`, `capability_id`, `status`: filter usage events.
- `start_time`, `end_time`: inclusive timestamp range filters.
- `limit`, `offset`: bounded pagination.

Success response includes:

- `usage`: matching usage events ordered newest first.
- `summaries`: aggregates grouped by workspace, agent, user, capability and status with event counts and total units.

Rules:

- Denied, success and error events are all included.
- Agents and users cannot read this admin endpoint; runtime agent usage has a separate `/v1/usage/me` contract.

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
- `include_disabled`: include disabled agents when true.
- `limit`, `offset`: bounded pagination.

### POST /v1/admin/agents/{agent_id}/rotate-token

Rotates an agent bearer token and returns the new plaintext token exactly once.

Success response uses the same shape as `POST /v1/admin/agents`:

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

- Store only the replacement `token_hash` and `token_hash_algorithm` on the existing agent record.
- The old plaintext token fails runtime authentication after the rotation commits.
- The response must not include `token_hash` or `token_hash_algorithm`.
- The update writes a safe admin audit record.

### PATCH /v1/admin/agents/{agent_id}

Updates an agent lifecycle status.

Request body:

```json
{
  "status": "disabled"
}
```

Rules:

- Valid statuses are `active` and `disabled`.
- Disabled agents fail runtime authentication immediately.
- The update writes a safe admin audit record.

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

- Authenticate a super-admin principal.
- Seed the default `gateway-runtime` desired route when absent.
- Compare current APISIX route state before writing. When `APISIX_FAIL_CLOSED=true`, load all current route state before any write so Admin API failures preserve the last known data-plane route state.
- Mark generated APISIX routes with Grantora ownership labels and delete only stale APISIX routes carrying those labels when their PostgreSQL desired route no longer exists.
- Running sync twice without desired-state changes must not perform a second APISIX update.
- Responses must not include the APISIX Admin URL, API key, upstream response body or stack trace.

Automatic reconciliation is enabled when `APISIX_SYNC_ENABLED=true`. Grantora runs one startup sync and then repeats sync every `APISIX_SYNC_INTERVAL_SECONDS` seconds until shutdown.

### GET /v1/admin/apisix/status

Returns the last APISIX sync status, or `never_run` when no sync has been attempted. Add `include_drift=true` to compare the current APISIX route state with Grantora's desired PostgreSQL state.

Response fields:

```json
{
  "status": "never_run | ok | error",
  "last_started_at": "datetime | null",
  "last_finished_at": "datetime | null",
  "checked_routes": 0,
  "changed_routes": 0,
  "error": null,
  "route_drift": {
    "status": "not_checked | in_sync | drifted | error",
    "checked_routes": 0,
    "drifted_routes": 0,
    "missing_routes": 0,
    "error": null
  }
}
```

Rules:

- Authenticate the admin bootstrap token.
- Do not call the APISIX Admin API unless `include_drift=true`.
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

Built-in template `nextcloud.files.search` follows the same capability shape with these provider-specific fields:

```yaml
id: nextcloud.files.search
name: Search files
version: 1
provider_type: nextcloud
adapter: nextcloud
operation: files.search
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
    files:
      type: array
      items:
        type: object
        properties:
          path:
            type: string
          display_name:
            type: string
          mime_type:
            type: string
          size:
            type:
              - integer
              - "null"
          modified_at:
            type:
              - string
              - "null"
          source:
            type: string
            const: nextcloud
        required:
          - path
          - display_name
          - mime_type
          - size
          - modified_at
          - source
        additionalProperties: false
  required:
    - files
  additionalProperties: false
```

Built-in template `hubspot.contacts.search` follows the same capability shape with these provider-specific fields:

```yaml
id: hubspot.contacts.search
name: Search contacts
version: 1
provider_type: hubspot
adapter: hubspot
operation: contacts.search
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
          id:
            type: string
          display_name:
            type: string
          email:
            type:
              - string
              - "null"
          company:
            type:
              - string
              - "null"
          phone:
            type:
              - string
              - "null"
          job_title:
            type:
              - string
              - "null"
          source:
            type: string
            const: hubspot
        required:
          - id
          - display_name
          - email
          - company
          - phone
          - job_title
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

Secret resolution selects only active secrets. Rotating a secret is done by inserting the replacement as `active` and marking the old secret `revoked`; revoked secrets are not selected for invocation. External secret references are stored as encrypted markers in `encrypted_value`; unresolved or disabled external backends fail closed with `secret_unavailable`.

## Admin Credential Contract

```yaml
id: uuid
subject: string
token_hash: hmac-sha256:<hex>
token_hash_algorithm: hmac-sha256
workspace_id: uuid | null
status: active | disabled
```

Rules:

- `workspace_id=null` means super admin.
- A non-null `workspace_id` scopes the admin credential to that active workspace.
- Plaintext admin tokens are never stored or returned by runtime APIs.

## Adapter Hardening Contract

Adapters must enforce configured upstream timeouts and response size limits.

Configuration:

```text
UPSTREAM_TIMEOUT_SECONDS
UPSTREAM_CONNECT_TIMEOUT_SECONDS
UPSTREAM_MAX_RESPONSE_BYTES
UPSTREAM_TLS_VERIFY
UPSTREAM_READ_RETRY_ATTEMPTS
```

Rules:

- Upstream timeouts return the safe error code `upstream_timeout`.
- Upstream responses larger than `UPSTREAM_MAX_RESPONSE_BYTES` return the safe error code `upstream_payload_too_large`.
- Read-only capabilities may retry retryable network failures, 429 and 5xx responses up to `UPSTREAM_READ_RETRY_ATTEMPTS` total attempts.
- Side-effecting, destructive, draft and admin capabilities are not retried by default.
- Safe adapter errors must not include upstream response bodies, internal URLs, stack traces or credential material.

## Audit Event Contract

```yaml
id: uuid
timestamp: datetime
request_id: string
actor_type: agent | admin_bootstrap | admin_token | admin_oidc
workspace_id: uuid | null
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
Admin mutations use `actor_type` for the authenticated admin principal; runtime agent activity uses `actor_type: agent`. Global admin mutations that are not scoped to one workspace use `workspace_id=null`.

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

Development schema rule: SQLAlchemy models are the source for the current schema. During the pre-release phase, application startup creates missing tables from `Base.metadata.create_all()` on clean disposable PostgreSQL state or test schemas.

Common model rules:

- Mutable configuration tables include `created_at` and `updated_at` generated in UTC.
- Audit and usage event `timestamp` values are generated in UTC.
- Lifecycle statuses are constrained to `active` or `disabled`.
- Secret statuses are constrained to `active` or `revoked`.
- Capability schemas default to a closed empty object schema and must pass the same JSON Schema validation used by Admin APIs before persistence.
- Query helpers must filter through active workspace-owned related records rather than trusting ids alone.

Required tables:

```text
workspaces
admin_credentials
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

CREATE INDEX idx_admin_credentials_token_hash_status
ON admin_credentials (token_hash, status);

CREATE INDEX idx_admin_credentials_workspace_status
ON admin_credentials (workspace_id, status);

CREATE UNIQUE INDEX uq_bindings_active_lookup
ON bindings (workspace_id, agent_id, user_id, capability_id)
WHERE status = 'active';

CREATE UNIQUE INDEX uq_secrets_active_owner
ON secrets (workspace_id, application_instance_id, owner_type, owner_id)
WHERE status = 'active';
```

Required uniqueness and constraints:

- Workspace slugs are globally unique.
- Application instance, agent and role slugs are unique per workspace.
- User external ids are unique per workspace.
- Agent token hashes and admin credential token hashes are unique.
- Capability ids are globally unique.
- Only one active binding may exist for a workspace, agent, user and capability.
- Only one active secret may exist for a workspace, application instance, owner type and owner id.
- Event counters and latency values are non-negative, and usage units are positive.

## Development Schema Rules

- Edit SQLAlchemy models directly while Grantora has no production installations.
- Start with a clean disposable PostgreSQL volume or temporary test schema after model changes.
- Let application startup create the current schema from model metadata.
- Add indexes and constraints directly to the model change that introduces a lookup path or invariant.
- Update this file before or with schema changes.

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
uri: /v1/runtime/*
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
apisix_payload:
  labels:
    grantora_managed: "true"
    grantora_route_id: gateway-runtime
  uris:
    - /v1/me
    - /v1/capabilities
    - /v1/capabilities/openapi.json
    - /v1/openapi.json
    - /v1/invoke/*
    - /v1/usage/me
    - /v1/mcp/tools
    - /v1/mcp/call
```

Rules:

- PostgreSQL desired state wins.
- Reconciliation must be idempotent.
- Reconciliation deletes stale generated APISIX routes only when the current APISIX route carries `grantora_managed=true`; foreign routes and unlabeled manual routes are never deleted by Grantora.
- Unsafe sync failures must leave existing safe routes in place.
- Public APISIX routes expose runtime endpoints only; `/v1/admin/*` is not part of the public data-plane route set.
- Manual APISIX changes may be overwritten.