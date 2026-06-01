# Grantora

Grantora is the standalone Agent Capability Gateway described in this document.

## Project Definition

**Status:** project blueprint  
**Target:** standalone upstream application, later packaged and managed by a NethServer 8 module  
**Core stack:** Apache APISIX, PostgreSQL, standalone Gateway API service, adapter framework  
**Primary consumers:** Hermes Agent and other AI/automation agents  
**Primary providers:** business applications such as NethVoice/NethCTI, WebTop, Nextcloud, Mattermost/Matrix and future NS8 applications

---

## 1. Executive summary

Grantora is a standalone software component that allows agents to safely use business application APIs on behalf of users.

It sits between agents and application APIs. Agents authenticate to the gateway, discover the capabilities available to them, invoke those capabilities, and receive normalized results. The gateway decides whether the agent is allowed to act for the requested user, which capability can be used, which upstream application must be called, which API key or delegated session must be used, and how the operation must be audited and metered.

The gateway must not be implemented as a generic raw API proxy. It must expose a curated capability layer.

```text
Agent → APISIX → Gateway API / Capability Executor → Application API
```

For the first version, Apache APISIX is used from the start as the HTTP data-plane and edge gateway. PostgreSQL is the source of truth for workspaces, applications, agents, users, roles, bindings, capabilities, secrets, audit events and usage data.

The software must be fully standalone. The later NethServer 8 module will install, configure, start and manage this upstream application, but the upstream application must not depend on NS8 internals to run.

---

## 2. Why this project is needed

NethServer 8 can already run multiple business applications. Users already work inside applications such as WebTop, NethVoice, Nextcloud and Mattermost/Matrix. These applications often share LDAP identities, but they do not expose a unified, secure and user-scoped automation layer.

Agents such as Hermes need to interact with these applications, but several unsafe or impractical patterns must be avoided:

```text
Do not give application API keys directly to agents.
Do not ask users to manually create and paste API tokens into agents.
Do not let agents use broad admin credentials.
Do not expose raw application APIs without capability-level authorization.
Do not lose the distinction between the agent identity and the human user identity.
Do not lose auditability of cross-application actions.
```

The gateway solves this by providing a controlled layer where:

```text
agent identity + user delegation + capability authorization + secret brokerage + application adapter + audit
```

are handled in one place.

---

## 3. Problems solved

## 3.1 Agents need to use application APIs without owning application secrets

Agents authenticate to the gateway. The gateway stores and uses the upstream API keys, tokens or delegated sessions. Agents never receive reusable downstream credentials.

## 3.2 Agents need to act on behalf of users

The gateway models the relationship:

```text
agent A is allowed to act for user U in workspace W using capability C
```

This is different from authenticating the agent as a service account.

## 3.3 Agents need to know which APIs/tools are available

The gateway exposes a capability catalog and generated OpenAPI/MCP-compatible tool descriptions. These descriptions are filtered according to the authenticated agent, requested user and workspace.

## 3.4 Application APIs are heterogeneous

NethVoice, WebTop, Nextcloud, Mattermost and other applications have different API styles, authentication systems, error formats and data models. The gateway hides this behind adapters and normalized capability contracts.

## 3.5 Administrators need RBAC and audit

The gateway provides RBAC for configuration and runtime authorization. Every invocation is logged with agent, user, workspace, capability, upstream provider, decision, status and latency.

## 3.6 Usage must be monitored by user and agent

The gateway records usage per workspace, user, agent, capability and provider. APISIX provides gateway-level metrics; the Gateway API stores business-level usage and audit events.

---

## 4. Design principles

## 4.1 Standalone first

The project must run outside NethServer 8.

The future NS8 module will:

```text
install the upstream application
configure it through environment variables
start containers/services
backup PostgreSQL and secrets
expose module actions
integrate with NS8 UI and account domains
```

The upstream application must remain usable in non-NS8 environments.

## 4.2 APISIX from the start

APISIX is part of the first architecture, not a later addition.

APISIX responsibilities:

```text
HTTP edge gateway
TLS termination if deployed directly
request routing
basic traffic control
rate limiting
request IDs
gateway metrics
optional OIDC/JWT/key-auth validation
routing to Gateway API services
```

The Gateway API remains responsible for business decisions:

```text
workspace resolution
agent-user delegation
capability authorization
RBAC
secret lookup
application adapter execution
audit
usage accounting
```

## 4.3 PostgreSQL as source of truth

PostgreSQL stores all dynamic application data:

```text
workspaces
application instances
capabilities
agents
users
roles
permissions
bindings
secrets metadata
encrypted secrets or secret references
audit events
usage events
APISIX route desired state
```

APISIX may use its own configuration backend such as etcd internally, but PostgreSQL remains the source of truth for this application. A reconciler writes APISIX routes/plugins/upstreams from PostgreSQL into APISIX.

## 4.4 Environment-only static configuration

All static runtime configuration must come from environment variables.

No required hand-written config file should be mounted into the gateway service.

Examples:

```text
DATABASE_URL
APISIX_ADMIN_URL
APISIX_ADMIN_KEY
SECRET_ENCRYPTION_KEY
PUBLIC_BASE_URL
LOG_LEVEL
METRICS_ENABLED
```

Dynamic business configuration is stored in PostgreSQL and managed through Admin APIs.

## 4.5 Capabilities, not raw APIs

Agents invoke stable capabilities:

```text
nethvoice.phonebook.search
nextcloud.files.search
webtop.calendar.list
mattermost.channel.post
```

They should not call arbitrary upstream paths.

## 4.6 Deny by default

No binding means no access.

No valid user delegation means no user-scoped invocation.

No usable upstream secret/session means fail closed.

## 4.7 Secrets outside agents

Agents may receive tool schemas, normalized results, opaque handles and safe error messages.

Agents must not receive:

```text
upstream API keys
refresh tokens
user passwords
application admin credentials
broker encryption keys
adapter private configuration
```

---

## 5. Scope

## 5.1 MVP scope

The MVP must implement the complete end-to-end path with one or two real capabilities.

Recommended first capability:

```text
nethvoice.phonebook.search
```

Alternative or second capability:

```text
nextcloud.files.search
```

MVP includes:

```text
APISIX data-plane
Gateway API service
PostgreSQL schema managed from SQLAlchemy models during development
environment-only static configuration
agent authentication
workspace model
application instance model
capability registry
RBAC and binding model
secret storage/use
capability invocation
audit logging
usage logging
Prometheus-compatible metrics
generated OpenAPI
one real adapter
containerized development setup
```

## 5.2 Out of scope for MVP

```text
full NS8 module packaging
full UI
all application adapters
OIDC SSO for users
complex ABAC engine
billing
generic API developer portal
multi-company SaaS control plane
cross-workspace federation
RAG/search engine
```

## 5.3 Future scope

```text
MCP facade
OIDC integration
OpenFGA/Cerbos/OPA policy backend
OpenBao/Vault-compatible secret backend
adapter marketplace
admin UI
user consent UI
RAG/search integration
quota enforcement
APISIX direct-proxy execution mode for simple capabilities
```

---

## 6. High-level architecture

```mermaid
flowchart TD
    Agent[Hermes / Agent]
    APISIX[Apache APISIX\nData-plane / Edge Gateway]
    API[Gateway API\nControl + Runtime API]
    Exec[Capability Executor]
    Adapter[Application Adapter]
    App[Application API\nNethVoice / Nextcloud / WebTop / Mattermost]
    PG[(PostgreSQL\nSource of Truth)]
    Reconciler[APISIX Reconciler]
    Metrics[Metrics / Audit Export]

    Agent --> APISIX
    APISIX --> API
    API --> Exec
    Exec --> Adapter
    Adapter --> App
    API <--> PG
    Exec <--> PG
    Reconciler <--> PG
    Reconciler --> APISIX
    API --> Metrics
    APISIX --> Metrics
```

---

## 7. Components

## 7.1 Apache APISIX

APISIX is the HTTP entry point.

Responsibilities:

```text
accept inbound HTTP traffic from agents/admin clients
route /v1/* to Gateway API
route /docs/* to API documentation if enabled
expose gateway metrics
apply coarse rate limits
apply coarse authentication plugins when useful
add request/correlation IDs
limit request size
timeout slow clients/upstreams
```

Initial route model:

```text
/v1/*                  → gateway-api:8080
/openapi.json          → gateway-api:8080/openapi.json
/docs/*                → gateway-api:8080/docs/*
/healthz               → gateway-api:8080/healthz
/metrics               → gateway-api:8080/metrics or APISIX Prometheus endpoint
```

APISIX should not contain business authorization logic in MVP. It can validate coarse agent tokens if useful, but the Gateway API must still perform final authorization.

## 7.2 Gateway API

The Gateway API is the main application service.

Responsibilities:

```text
admin API
runtime API
agent authentication
capability description
RBAC evaluation
binding evaluation
user delegation validation
secret lookup
capability execution orchestration
audit logging
usage accounting
OpenAPI generation
APISIX desired-state generation
```

Recommended implementation:

```text
Python FastAPI
SQLAlchemy or SQLModel
SQLAlchemy metadata schema creation
Pydantic models
httpx for upstream HTTP calls
prometheus_client for metrics
structured JSON logging
```

## 7.3 Capability Executor

The executor handles `POST /v1/invoke/{capability_id}`.

Responsibilities:

```text
validate input schema
load capability
load binding
validate agent-user delegation
load upstream application instance
resolve secret/session
execute adapter
normalize output
write audit event
write usage event
return response
```

The executor can live inside Gateway API for MVP. It can become a separate worker/service later.

## 7.4 Adapter framework

Adapters translate generic capability contracts into application-specific API calls.

Example adapters:

```text
adapters/nethvoice.py
adapters/nextcloud.py
adapters/webtop.py
adapters/mattermost.py
```

Each adapter must implement a stable internal interface:

```python
class Adapter:
    def supports(self, capability: Capability) -> bool: ...
    async def invoke(self, context: InvocationContext, input: dict) -> InvocationResult: ...
    async def health(self, app: ApplicationInstance) -> HealthResult: ...
```

## 7.5 PostgreSQL

PostgreSQL stores all persistent state.

Responsibilities:

```text
source of truth for gateway domain model
audit and usage events
secret metadata and encrypted secret values
APISIX desired configuration
direct schema bootstrap from the current model metadata
```

Recommended extensions/features:

```text
uuid generation
jsonb for schemas and flexible metadata
indexes on workspace/agent/user/capability/time
optional pgcrypto if database-side encryption is chosen
```

Application-level encryption is preferred for secrets so that encrypted values are opaque to PostgreSQL.

## 7.6 APISIX Reconciler

The reconciler syncs PostgreSQL desired state into APISIX.

Responsibilities:

```text
read active APISIX route definitions from PostgreSQL
create/update/delete APISIX routes through Admin API
verify APISIX state
report sync status
retry transient failures
fail closed for unsafe route states
```

For MVP, this can run as part of Gateway API startup and on admin changes. Later it can become a dedicated worker.

## 7.7 Metrics and audit exporter

Metrics and audit are separate concerns.

Metrics answer:

```text
how many requests
latency
error rates
rate-limit events
upstream failures
```

Audit answers:

```text
who did what
on behalf of whom
using which capability
against which provider
with which decision
with which outcome
```

---

## 8. Runtime request flow

## 8.1 Capability discovery

```mermaid
sequenceDiagram
    participant A as Agent
    participant X as APISIX
    participant G as Gateway API
    participant DB as PostgreSQL

    A->>X: GET /v1/capabilities as agent
    X->>G: Forward request
    G->>G: Authenticate agent
    G->>DB: Load agent, users, bindings, capabilities
    G->>G: Filter visible capabilities
    G-->>X: Capability catalog
    X-->>A: Allowed tools only
```

## 8.2 Capability invocation

```mermaid
sequenceDiagram
    participant A as Agent
    participant X as APISIX
    participant G as Gateway API
    participant DB as PostgreSQL
    participant AD as Adapter
    participant APP as Application API

    A->>X: POST /v1/invoke/nethvoice.phonebook.search
    X->>G: Forward request
    G->>G: Authenticate agent
    G->>DB: Load capability + binding + user delegation
    G->>G: Authorize RBAC
    G->>DB: Resolve upstream secret/session
    G->>AD: Invoke adapter
    AD->>APP: Call application API with upstream credential
    APP-->>AD: Application response
    AD-->>G: Normalized result
    G->>DB: Write audit + usage
    G-->>X: Normalized response
    X-->>A: Result
```

---

## 9. Execution modes

## 9.1 Adapter execution mode

This is the MVP mode.

```text
Agent → APISIX → Gateway API → Adapter → Application API
```

Use when:

```text
request/response transformation is needed
upstream secret selection is dynamic
user-scoped authorization is required
application errors must be normalized
API is not safe to expose directly
```

## 9.2 Direct APISIX proxy mode

This is a future optimization for simple, low-risk capabilities.

```text
Agent → APISIX → Application API
               ↘ Gateway authz/credential hook
```

Use only when:

```text
the upstream API already has safe request/response format
credential injection is simple
no heavy transformation is needed
APISIX plugin/hook can enforce the same policy safely
```

The MVP must not depend on direct APISIX proxy mode.

---

## 10. Domain model

## 10.1 Workspace

A workspace represents a company or logical business context.

```yaml
workspace:
  id: uuid
  slug: acme
  display_name: Acme SRL
  status: active
```

## 10.2 Application instance

An application instance is an upstream application that exposes APIs.

```yaml
application_instance:
  id: uuid
  workspace_id: uuid
  slug: nethvoice1
  type: nethvoice
  base_url: https://nethvoice.example.test
  status: active
  tls_verify: true
  metadata: {}
```

## 10.3 Capability

A capability is a stable tool/action exposed to agents.

```yaml
capability:
  id: nethvoice.phonebook.search
  workspace_id: uuid
  application_instance_id: uuid
  adapter: nethvoice
  operation: phonebook.search
  auth_mode: user
  risk_class: read_only
  input_schema: {}
  output_schema: {}
  status: active
```

## 10.4 Agent

An agent is a runtime consumer such as Hermes.

```yaml
agent:
  id: uuid
  workspace_id: uuid
  slug: hermes-alice
  display_name: Hermes Alice
  token_hash: ...
  status: active
```

## 10.5 User

A user is the human actor that the agent may act for.

```yaml
user:
  id: uuid
  workspace_id: uuid
  external_id: alice
  display_name: Alice
  source: local | ldap | oidc | ns8
  status: active
```

## 10.6 Role

A role groups permissions.

```yaml
role:
  id: uuid
  workspace_id: uuid
  name: personal_agent
  permissions:
    - capability.describe
    - capability.invoke.read_only
```

## 10.7 Binding

A binding authorizes an agent to use a capability for a user or user group.

```yaml
binding:
  id: uuid
  workspace_id: uuid
  agent_id: uuid
  user_id: uuid
  capability_id: nethvoice.phonebook.search
  role_id: uuid
  status: active
```

## 10.8 Secret

A secret stores or references upstream credentials.

```yaml
secret:
  id: uuid
  workspace_id: uuid
  application_instance_id: uuid
  owner_type: workspace | user | agent
  owner_id: uuid
  secret_type: api_key | bearer_token | basic_auth | oauth_refresh_token | session_cookie
  encrypted_value: ...
  status: active
```

## 10.9 Audit event

```yaml
audit_event:
  id: uuid
  timestamp: datetime
  request_id: string
  workspace_id: uuid
  agent_id: uuid
  user_id: uuid
  capability_id: string
  application_instance_id: uuid
  decision: allow | deny
  outcome: success | error
  error_code: string | null
  latency_ms: integer
  remote_addr: string
```

## 10.10 Usage event

```yaml
usage_event:
  id: uuid
  timestamp: datetime
  workspace_id: uuid
  agent_id: uuid
  user_id: uuid
  capability_id: string
  application_instance_id: uuid
  units: integer
  status: success | error | denied
  latency_ms: integer
```

---

## 11. RBAC model

## 11.1 Administrative RBAC

Controls who can configure the gateway.

Minimum roles:

```yaml
gateway_admin:
  - workspace.create
  - workspace.manage
  - application.manage
  - capability.manage
  - agent.manage
  - binding.manage
  - secret.manage
  - audit.read
  - usage.read

workspace_admin:
  - application.manage
  - capability.manage
  - agent.manage
  - binding.manage
  - secret.manage
  - audit.read
  - usage.read

auditor:
  - audit.read
  - usage.read
```

## 11.2 Runtime RBAC

Controls what an agent may do.

Minimum runtime permissions:

```yaml
capability.describe
capability.invoke.read_only
capability.invoke.side_effect
capability.invoke.destructive
```

Runtime authorization requires all checks to pass:

```text
agent is active
workspace is active
user is active
agent is allowed to act for user
capability is active
binding is active
role permits capability risk class
upstream secret/session is available
```

---

## 12. Capability contract

## 12.1 Capability manifest

Capabilities can be created through Admin API or loaded from manifests.

```yaml
id: nethvoice.phonebook.search
name: Search phonebook
version: 1
workspace: acme
provider: nethvoice1
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
        required:
          - display_name
          - phone
```

## 12.2 Auth modes

```text
system       no human user required
user         must execute on behalf of a human user
user+scope   must execute on behalf of a user and match explicit scopes
admin        administrative capability
```

## 12.3 Risk classes

```text
read_only          reads data only
draft              creates non-final artifacts
side_effect         sends messages, starts calls, writes data
destructive         deletes or overwrites data
admin              changes configuration/security
```

## 12.4 Invocation request

```http
POST /v1/invoke/{capability_id}
Authorization: Bearer <agent_token>
Content-Type: application/json
```

```json
{
  "user": "alice",
  "input": {
    "query": "Mario",
    "limit": 10
  }
}
```

## 12.5 Invocation response

```json
{
  "request_id": "req_01j...",
  "capability": "nethvoice.phonebook.search",
  "status": "ok",
  "data": {
    "contacts": [
      {
        "display_name": "Mario Rossi",
        "phone": "+390...",
        "company": "Acme"
      }
    ]
  }
}
```

## 12.6 Error response

```json
{
  "request_id": "req_01j...",
  "status": "error",
  "error": {
    "code": "capability_denied",
    "message": "Capability not allowed for this agent and user"
  }
}
```

Error messages returned to agents must be safe and must not leak upstream credentials, internal URLs or sensitive stack traces.

---

## 13. Public API contract

## 13.1 Runtime API

```http
GET  /v1/me
GET  /v1/capabilities
GET  /v1/openapi.json
GET  /v1/capabilities/openapi.json
POST /v1/invoke/{capability_id}
GET  /v1/usage/me
```

## 13.2 Admin API

```http
POST   /v1/admin/workspaces
GET    /v1/admin/workspaces
POST   /v1/admin/applications
GET    /v1/admin/applications
POST   /v1/admin/capabilities
GET    /v1/admin/capabilities
POST   /v1/admin/agents
GET    /v1/admin/agents
POST   /v1/admin/bindings
GET    /v1/admin/bindings
POST   /v1/admin/secrets
GET    /v1/admin/audit
GET    /v1/admin/usage
POST   /v1/admin/apisix/sync
GET    /v1/admin/apisix/status
```

## 13.3 Health and observability API

```http
GET /healthz
GET /readyz
GET /metrics
```

---

## 14. OpenAPI and agent tool description

The gateway must generate an OpenAPI description of the runtime API.

Two OpenAPI outputs are needed:

## 14.1 Static API OpenAPI

Describes the gateway API itself.

```text
GET /v1/openapi.json
```

## 14.2 Filtered capability OpenAPI

Describes only the capabilities allowed for the authenticated agent and selected user.

```text
GET /v1/capabilities/openapi.json?user=alice
```

This output can later be converted to MCP tools.

The agent should see only allowed capabilities.

---

## 15. APISIX integration contract

## 15.1 APISIX desired route object

Stored in PostgreSQL and reconciled into APISIX.

```yaml
apisix_route:
  id: gateway-runtime
  uri: /v1/*
  upstream:
    type: roundrobin
    nodes:
      gateway-api:8080: 1
  plugins:
    prometheus: {}
    request-id: {}
    limit-count:
      count: 1000
      time_window: 60
      rejected_code: 429
```

## 15.2 Reconciliation rules

```text
PostgreSQL desired state wins.
APISIX config is treated as generated runtime state.
Manual APISIX changes may be overwritten.
Reconciler must be idempotent.
Reconciler must log every create/update/delete.
Unsafe sync failures must leave existing safe routes in place.
```

## 15.3 APISIX admin configuration

The Gateway API talks to APISIX Admin API using environment configuration:

```text
APISIX_ADMIN_URL
APISIX_ADMIN_KEY
APISIX_SYNC_ENABLED
APISIX_SYNC_INTERVAL_SECONDS
```

## 15.4 APISIX plugin baseline

Recommended from MVP:

```text
prometheus
request-id
limit-count or limit-req
cors only if needed
real-ip if behind another proxy
```

Optional later:

```text
jwt-auth
openid-connect
key-auth
ext-plugin-pre-req
proxy-rewrite
```

---

## 16. Environment configuration contract

All static configuration must be environment-driven.

## 16.1 Core service

```bash
GATEWAY_ENV=production
GATEWAY_PUBLIC_BASE_URL=https://gateway.example.test
GATEWAY_BIND_ADDR=0.0.0.0
GATEWAY_PORT=8080
GATEWAY_LOG_LEVEL=INFO
GATEWAY_JSON_LOGS=true
```

## 16.2 Database

```bash
DATABASE_URL=postgresql+psycopg://gateway:gateway@postgres:5432/gateway
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_SSLMODE=prefer
```

## 16.3 Security

```bash
SECRET_ENCRYPTION_KEY=base64:...
AGENT_TOKEN_PEPPER=base64:...
ADMIN_BOOTSTRAP_TOKEN_HASH=...
TOKEN_HASH_ALGORITHM=argon2id
```

## 16.4 APISIX

```bash
APISIX_PUBLIC_URL=http://apisix:9080
APISIX_ADMIN_URL=http://apisix:9180
APISIX_ADMIN_KEY=...
APISIX_SYNC_ENABLED=true
APISIX_SYNC_INTERVAL_SECONDS=30
APISIX_FAIL_CLOSED=true
```

## 16.5 Observability

```bash
METRICS_ENABLED=true
METRICS_PATH=/metrics
AUDIT_RETENTION_DAYS=365
USAGE_RETENTION_DAYS=365
REQUEST_ID_HEADER=X-Request-Id
```

## 16.6 Upstream defaults

```bash
UPSTREAM_TIMEOUT_SECONDS=30
UPSTREAM_CONNECT_TIMEOUT_SECONDS=5
UPSTREAM_TLS_VERIFY=true
UPSTREAM_MAX_RESPONSE_BYTES=10485760
```

## 16.7 Feature flags

```bash
FEATURE_MCP=false
FEATURE_DIRECT_APISIX_PROXY=false
FEATURE_OIDC=false
OIDC_ADMIN_SUBJECTS=
OIDC_SUBJECT_HEADER=X-Grantora-Admin-Subject
OIDC_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
FEATURE_EXTERNAL_POLICY_ENGINE=false
FEATURE_EXTERNAL_SECRET_STORE=false
```

---

## 17. Repository structure

Recommended standalone repository layout:

```text
agent-capability-gateway/
  README.md
  PROJECT.md
  LICENSE
  pyproject.toml
  docker-compose.yml
  containers/
    gateway-api.Dockerfile
    apisix/
      config.template.yaml
  src/
    gateway/
      __init__.py
      main.py
      config.py
      logging.py
      db.py
      security/
        auth.py
        tokens.py
        encryption.py
        rbac.py
      models/
        workspace.py
        application.py
        capability.py
        agent.py
        user.py
        role.py
        binding.py
        secret.py
        audit.py
        usage.py
        apisix.py
      schemas/
        runtime.py
        admin.py
        capability.py
        errors.py
      api/
        runtime.py
        admin.py
        health.py
        metrics.py
      executor/
        invoke.py
        context.py
        errors.py
      adapters/
        base.py
        nethvoice.py
        nextcloud.py
        webtop.py
        mattermost.py
      apisix/
        client.py
        desired_state.py
        reconciler.py
      observability/
        metrics.py
        audit.py
        usage.py
      openapi/
        filtered.py
        tools.py
  tests/
    unit/
    integration/
    e2e/
  docs/
    architecture.md
    api.md
    adapter-development.md
    deployment.md
```

---

## 18. Database schema outline

## 18.1 Core tables

```sql
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

## 18.2 Important indexes

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

## 18.3 JSONB usage

Use JSONB for:

```text
capability input_schema
capability output_schema
application metadata
adapter config
APISIX plugin config
safe error details
```

Do not store unencrypted secrets in JSONB.

---

## 19. Secret management

## 19.1 MVP secret backend

Use encrypted secrets in PostgreSQL.

Rules:

```text
encrypt before storing
keep encryption key only in environment
never log secret values
never return secret values through API
rotate secrets by writing new encrypted values
support forced revocation
```

## 19.2 Secret lookup order

For user-scoped capabilities:

```text
1. user-owned secret for application
2. workspace delegated secret if policy allows
3. application service secret if capability is system-level
4. fail closed
```

## 19.3 Future secret backend

Add optional external secret backends later:

```text
OpenBao
HashiCorp Vault-compatible API
Passbolt
NS8 secret integration
```

---

## 20. Adapter contract

## 20.1 Adapter input context

```json
{
  "request_id": "req_01j...",
  "workspace": {
    "id": "...",
    "slug": "acme"
  },
  "agent": {
    "id": "...",
    "slug": "hermes-alice"
  },
  "user": {
    "id": "...",
    "external_id": "alice"
  },
  "application": {
    "id": "...",
    "type": "nethvoice",
    "base_url": "https://nethvoice.example.test"
  },
  "capability": {
    "id": "nethvoice.phonebook.search",
    "operation": "phonebook.search"
  },
  "secret": {
    "type": "bearer_token",
    "value": "decrypted-at-runtime-only"
  }
}
```

## 20.2 Adapter output

```json
{
  "status": "ok",
  "data": {},
  "usage_units": 1,
  "upstream_status": 200,
  "safe_metadata": {}
}
```

## 20.3 Adapter error

```json
{
  "status": "error",
  "error_code": "upstream_unauthorized",
  "safe_message": "The upstream application rejected the delegated credentials",
  "upstream_status": 401,
  "retryable": false
}
```

---

## 21. First adapter: NethVoice phonebook search

## 21.1 Goal

Expose a narrow, read-only, high-value capability.

```text
nethvoice.phonebook.search
```

## 21.2 Input

```json
{
  "query": "Mario",
  "limit": 10
}
```

## 21.3 Output

```json
{
  "contacts": [
    {
      "display_name": "Mario Rossi",
      "phone": "+390...",
      "company": "Acme",
      "source": "nethvoice"
    }
  ]
}
```

## 21.4 Security

```text
read-only
user-scoped if NethVoice API supports it
workspace-scoped service token only if explicitly configured
limit maximum results
return only required fields
log invocation metadata, not contact payload by default
```

---

## 22. Observability

## 22.1 Metrics

Expose Prometheus-compatible metrics.

Minimum metrics:

```text
gateway_requests_total{workspace,agent,user,capability,status}
gateway_request_duration_seconds{workspace,capability,provider}
gateway_authorization_denied_total{workspace,reason}
gateway_upstream_requests_total{workspace,provider,status}
gateway_upstream_errors_total{workspace,provider,error_code}
gateway_secret_resolution_total{workspace,provider,result}
apisix_sync_total{status}
apisix_sync_duration_seconds
```

## 22.2 Logs

All logs should be structured JSON.

Required fields:

```text
timestamp
level
request_id
workspace_id
agent_id
user_id
capability_id
message
```

Never log:

```text
secrets
tokens
authorization headers
full upstream response bodies unless explicitly redacted
```

## 22.3 Audit

Audit must be stored in PostgreSQL.

Audit is not just logs. It must be queryable and retained according to policy.

---

## 23. Security requirements

## 23.1 Authentication

MVP:

```text
agent bearer tokens
admin bootstrap token
hashed tokens in PostgreSQL
```

Later:

```text
OIDC/JWT
mTLS for internal components
NS8 API integration
```

## 23.2 Authorization

Every invocation must check:

```text
agent active
workspace active
user active
binding active
role permission
capability status
risk class allowed
secret/session resolvable
```

## 23.3 Secret handling

```text
secrets encrypted at rest
secrets decrypted only in memory during invocation
secrets never returned to agents
secrets never logged
secret rotation supported
secret revocation supported
```

## 23.4 Network security

```text
APISIX is the only public entrypoint
Gateway API can be internal-only behind APISIX
PostgreSQL is internal-only
APISIX Admin API is internal-only
Application upstreams configured with TLS verification by default
```

---

## 24. Development environment

## 24.1 Local docker compose

Services:

```text
apisix
apisix-etcd
postgres
gateway-api
mock-nethvoice
prometheus optional
```

## 24.2 Developer commands

```bash
make dev-up
make dev-down
make test
make lint
make format
make seed-demo
make apisix-sync
```

## 24.3 Demo seed data

Seed should create:

```text
workspace acme
user alice
agent hermes-alice
application nethvoice1
capability nethvoice.phonebook.search
secret nethvoice1-api-token
binding hermes-alice → alice → nethvoice.phonebook.search
```

---

## 25. Testing strategy

## 25.1 Unit tests

```text
RBAC checks
binding checks
token hashing
secret encryption/decryption
capability schema validation
adapter normalization
error mapping
```

## 25.2 Integration tests

```text
PostgreSQL metadata schema creation
Gateway API with real PostgreSQL
APISIX route reconciliation
mock upstream application calls
audit writes
usage writes
metrics exposed
```

## 25.3 End-to-end tests

```text
agent gets capabilities
agent invokes allowed capability
agent denied for missing binding
agent denied for wrong user
secret missing causes fail closed
upstream error returns safe error
audit event is created
usage event is created
APISIX routes request correctly
```

---

## 26. Packaging and deployment

## 26.1 Standalone container deployment

The upstream application should provide images for:

```text
gateway-api
```

Use official images for:

```text
apache/apisix
postgres
etcd
```

## 26.2 NS8 module deployment later

The NS8 module should not fork the upstream app logic.

The module should provide:

```text
container orchestration
state directory
secrets.env generation
environment file generation
PostgreSQL backup/restore
APISIX internal configuration
NS8 actions
NS8 UI integration
route/firewall integration if needed
LDAP/user-domain mapping if needed
```

The upstream application remains standalone.

---

## 27. Migration path to NS8 module

## 27.1 Standalone phase

```text
Build and validate the Gateway application.
Use docker compose.
Use mock applications and one real adapter.
Do not depend on NS8 internals.
```

## 27.2 NS8-compatible phase

```text
Add environment variables matching NS8 module conventions.
Ensure all state paths are configurable.
Ensure backup/restore is clean.
Ensure service startup is deterministic.
Expose health endpoints.
```

## 27.3 NS8 module phase

```text
Create ns8-capability-gateway module.
Use upstream containers.
Generate environment files.
Configure PostgreSQL.
Configure APISIX.
Expose actions.
Add UI.
Integrate with user domains and installed module discovery.
```

---

## 28. Anti-patterns to avoid

```text
Do not expose a generic /proxy/{application}/{path} endpoint to agents.
Do not give application API keys to agents.
Do not store raw user passwords.
Do not let APISIX become the business policy engine.
Do not store static configuration in hand-edited YAML files.
Do not make the upstream application depend on NS8-specific paths or commands.
Do not log secrets or full sensitive payloads.
Do not implement all adapters before proving the first end-to-end flow.
```

---

## 29. Implementation milestones

## Milestone 1 — Skeleton

```text
FastAPI project
PostgreSQL connection
SQLAlchemy metadata schema creation
Docker compose with APISIX + etcd + PostgreSQL + gateway-api
health endpoints
environment configuration
```

## Milestone 2 — Domain model

```text
workspace model
application instance model
user model
agent model
capability model
role/permission model
binding model
secret model
```

## Milestone 3 — Authentication and RBAC

```text
agent token generation
agent token hashing
admin bootstrap auth
runtime authorization checks
binding validation
```

## Milestone 4 — APISIX integration

```text
APISIX client
route desired state table
route reconciliation
baseline plugins
APISIX sync status
```

## Milestone 5 — Invocation engine

```text
POST /v1/invoke/{capability_id}
input schema validation
secret resolution
adapter dispatch
audit event
usage event
safe errors
```

## Milestone 6 — First adapter

```text
mock adapter
NethVoice phonebook adapter
normalized Contact output
integration tests
```

## Milestone 7 — Capability discovery

```text
GET /v1/capabilities
filtered OpenAPI generation
agent-visible tool schemas
```

## Milestone 8 — Observability

```text
Prometheus metrics
audit query API
usage query API
structured logs
```

## Milestone 9 — Hardening

```text
secret rotation
binding revocation
rate limits
timeouts
payload size limits
security tests
backup/restore procedure
```

---

## 30. Final definition

Grantora is a standalone capability broker for agents.

It uses APISIX as HTTP data-plane from the start, PostgreSQL as the source of truth, and environment variables for all static configuration.

It authenticates agents, authorizes them to act on behalf of users, exposes only allowed capabilities, stores and uses upstream application credentials without revealing them to agents, proxies/adapts requests to application APIs, enforces RBAC, records audit and usage, and generates machine-readable API/tool contracts.

The later NethServer 8 module should package and manage this upstream application, not replace it.
