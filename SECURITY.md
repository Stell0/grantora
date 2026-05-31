# SECURITY.md

Grantora's security model separates agent identity, human user identity and upstream application credentials. The default outcome is deny.

## Identity Model

- Agent identity authenticates the runtime caller.
- User identity represents the human actor on whose behalf a capability may run.
- Workspace identity scopes agents, users, applications, capabilities, secrets, audit and usage.
- Application identity identifies an upstream provider instance such as NethVoice or Nextcloud.

An authenticated agent is not automatically allowed to act for any user. Runtime authorization must prove the agent, user, capability, role and binding relationship inside the same active workspace.

## Agent Tokens

- Agents authenticate with bearer tokens in the MVP.
- Store only token hashes, never plaintext tokens.
- Use a configured pepper from environment variables.
- The MVP hash format is `hmac-sha256:<hex>` using HMAC-SHA-256 over the plaintext token with the configured token pepper.
- Return generated tokens only once at creation time.
- Revoking or disabling an agent must deny future requests immediately.

## Admin Authentication

- Bootstrap admin access uses an environment-provided token hash.
- Bootstrap and DB-backed admin token hashes use the same `hmac-sha256:<hex>` peppered hash format as agent tokens.
- DB-backed admin credentials may be super-admin credentials or scoped to one workspace. Scoped admins must not read, create or mutate resources outside their workspace.
- Optional OIDC/NS8 admin identity is disabled by default. When enabled, Grantora accepts only explicitly allowlisted subjects from the configured trusted subject header.
- Admin endpoints are separate from runtime agent endpoints.
- Agent bearer tokens are not admin tokens and must fail admin authentication.
- Admin changes to security-relevant objects must create audit records.
- OIDC or NS8 integration must preserve the same authorization checks and must be deployed behind a trusted component that strips spoofed identity headers.

## Secret Encryption

- Encrypt upstream secrets before storing them in PostgreSQL.
- Keep encryption keys only in environment variables or a future external secret backend.
- External secret references may be stored only as encrypted markers. If the external backend is disabled or cannot resolve the marker, invocation fails closed with a safe secret error.
- Decrypt secrets only in memory during invocation.
- Never return upstream secrets through runtime or admin APIs.
- Never log decrypted secrets, ciphertext values, authorization headers, cookies or refresh tokens.

## Capability Authorization

Every invocation must check:

- Workspace is active.
- Agent is active and belongs to the workspace.
- User is active and belongs to the workspace when the capability is user-scoped.
- Capability is active and belongs to the workspace.
- Binding is active for workspace, agent, user and capability.
- Role grants the permission required by the capability risk class.
- Secret or delegated session is resolvable.

No binding means no access. No valid user delegation means no user-scoped invocation. No usable upstream secret means fail closed.

## Runtime Permissions

Minimum runtime permissions:

- `capability.describe`
- `capability.invoke.read_only`
- `capability.invoke.side_effect`
- `capability.invoke.destructive`

Risk class mapping:

- `read_only` requires `capability.invoke.read_only`.
- `draft` and `side_effect` require `capability.invoke.side_effect`.
- `destructive` requires `capability.invoke.destructive`.
- `admin` is not available to runtime agents in the MVP.

## Audit Requirements

Audit is mandatory and stored in PostgreSQL. It is not just logs.

Audit every invocation attempt, including:

- Missing or invalid binding
- Disabled agent, user, workspace or capability
- Missing secret
- Input validation failure
- Adapter success
- Adapter error
- Upstream timeout or failure

Audit records must include request id, workspace, agent when known, user when known, capability when known, decision, outcome, error code and latency.

## Logging Restrictions

Never log:

- Upstream secrets
- Agent bearer tokens
- Admin tokens
- Authorization headers
- Refresh tokens
- Session cookies
- User passwords
- Full upstream response bodies unless explicitly redacted
- Contact lists, file contents or message bodies by default

Logs should include request id, workspace id, agent id, user id, capability id, decision and safe error code where available.

## Unsafe Patterns

- Never allow raw upstream path passthrough by default.
- Never allow capability schemas that accept arbitrary upstream URLs, paths, methods, headers or raw bodies by default.
- Never accept upstream application base URLs pointing at localhost, private addresses, bare hostnames or URL paths.
- Never process request bodies larger than the configured `MAX_REQUEST_BODY_BYTES` limit.
- Never trust `user` from a request without checking binding.
- Never skip audit on denied requests.
- Never let APISIX replace Grantora business authorization.
- Never give application API keys to agents.
- Never store raw user passwords.
- Never make NS8 internals required for standalone Grantora operation.

## Revocation Behavior

- Disabled agents cannot authenticate.
- Disabled users cannot be used for user-scoped invocation.
- Disabled capabilities cannot be discovered or invoked.
- Disabled bindings deny access immediately.
- Revoked secrets are not selected by secret resolution.
- Secret rotation revokes the old active secret and creates the replacement in one committed admin operation; runtime invocation can only select active secrets after the commit.
- APISIX route sync failures must not open broader access than the last known safe route state.

## Threat Model Summary

Primary threats:

- Agent attempts to act for another user.
- Agent attempts to discover or invoke unbound capabilities.
- Agent attempts to exfiltrate upstream credentials.
- Admin or developer accidentally exposes raw upstream APIs.
- Upstream provider returns sensitive fields that should not reach agents.
- Logs or metrics capture secrets or sensitive payloads.
- APISIX manual changes bypass Grantora policy.

Primary mitigations:

- Deny-by-default authorization.
- Curated capability contracts.
- Secret brokerage inside Grantora.
- Adapter output normalization.
- Mandatory audit and usage records.
- PostgreSQL desired state for APISIX routes.
- Environment-only static configuration.
- Bounded request bodies and constrained identifiers, URLs and JSON schemas.
- Release security gates for dependency audit, SBOM generation and container vulnerability scanning.