# ADAPTERS.md

Application adapters translate Grantora capabilities into provider-specific API calls. Each adapter must hide provider quirks and return normalized Grantora results.

## Adapter Interface

```python
from typing import Protocol


class Adapter(Protocol):
    id: str
    provider_type: str

    async def invoke(
        self,
        capability: "Capability",
        input_data: dict,
        context: "InvocationContext",
        secret: "SecretMaterial",
    ) -> "AdapterResult":
        ...

    async def health(
        self,
        application: "ApplicationInstance",
    ) -> "HealthResult":
        ...
```

Shared adapter types belong in `src/grantora/adapters/base.py`. Provider implementations belong in `src/grantora/adapters/{provider}.py`.

## Invocation Context

Adapters receive only the data needed to perform the capability:

```json
{
  "request_id": "req_01j...",
  "workspace": {"id": "uuid", "slug": "acme"},
  "agent": {"id": "uuid", "slug": "hermes-alice"},
  "user": {"id": "uuid", "external_id": "alice"},
  "application": {"id": "uuid", "type": "nethvoice", "base_url": "https://nethvoice.example.test"},
  "capability": {"id": "nethvoice.phonebook.search", "operation": "phonebook.search"}
}
```

Secret material is passed separately and must never be logged, returned or stored in adapter metadata.

## Adapter Result

```json
{
  "status": "ok",
  "data": {},
  "usage_units": 1,
  "upstream_status": 200,
  "safe_metadata": {}
}
```

Rules:

- `data` must match the capability output schema.
- `usage_units` defaults to 1 for a successful invocation.
- `safe_metadata` must not include secrets, raw upstream bodies or private configuration.

## Error Mapping

Adapters must map provider errors into safe Grantora errors:

```json
{
  "status": "error",
  "error_code": "upstream_unauthorized",
  "safe_message": "The upstream application rejected the delegated credentials",
  "upstream_status": 401,
  "retryable": false
}
```

Required mappings:

- Upstream 401 or 403 -> `upstream_unauthorized`
- Upstream 404 -> `upstream_not_found`
- Upstream timeout -> `upstream_timeout`
- Upstream 429 -> `upstream_rate_limited`
- Upstream 5xx -> `upstream_error`
- Invalid upstream response -> `upstream_invalid_response`
- Oversized upstream response -> `upstream_payload_too_large`

## Secret Lookup Rules

Adapters do not choose secrets. The invocation engine resolves secret material before adapter execution.

Lookup order for user-scoped capabilities:

1. User-owned secret for the application instance
2. Workspace delegated secret when policy explicitly allows it
3. Application service secret for system-level capabilities only
4. Fail closed

Adapters may reject incompatible secret types but must not fall back to hard-coded credentials.

## Timeout And Retry Behavior

- Use the configured upstream connect timeout and request timeout.
- Enforce the configured maximum upstream response size before parsing provider payloads.
- Do not retry non-idempotent capabilities unless the capability contract explicitly allows it.
- Read-only capabilities may retry safe network failures, 429 responses and 5xx responses up to `UPSTREAM_READ_RETRY_ATTEMPTS` total attempts.
- Side-effecting, destructive, draft and admin capabilities are not retried by default.
- Always return a safe timeout or upstream error when retries are exhausted.

## Logging Rules

- Log request id, workspace id, capability id, provider type and safe status.
- Do not log authorization headers, tokens, cookies, decrypted secrets or raw upstream response bodies.
- Do not log contact payloads, file contents or message bodies by default.

## Adapter Extension Rules

- Start from a curated capability contract. Do not add raw upstream method, path, URL, header or body passthrough unless the public contracts and security model explicitly change first.
- Let the invocation engine perform authorization, input schema validation and secret resolution. Adapters must receive `SecretMaterial`; they must not query the database, choose a different secret or fall back to hard-coded credentials.
- Inject credentials only into provider requests inside the adapter or another controlled broker layer. Never include credentials in `data`, `safe_metadata`, exceptions, logs, metrics or health responses.
- Enforce configured upstream request timeout, connect timeout, TLS verification and maximum response size before parsing provider payloads.
- Use bounded read-only retry behavior for idempotent capabilities only. Draft, side-effecting, destructive and admin-risk capabilities must not retry by default.
- Normalize successful provider responses into the capability output schema and drop upstream-only fields by default.
- Map provider and transport failures to safe `AdapterResult.error(...)` values. Do not expose raw upstream response bodies, stack traces, internal URLs or credential material in `safe_message`.
- Keep health checks credential-free unless a future contract says otherwise, and return only safe reachability status.
- Tests must use mock transports or mock upstream services only. No adapter test may contact a real business service.

## Current Built-In Real Adapters

- `nethvoice.phonebook.search`: read-only search over the NethVoice phonebook API.
- `nextcloud.files.search`: read-only file search against the Nextcloud OCS search provider.
- `hubspot.contacts.search`: read-only contact search against HubSpot CRM contacts via bearer-token auth only.

The HubSpot adapter is intentionally narrow. It only exposes curated contact search, always posts to `/crm/v3/objects/contacts/search`, always allowlists the returned fields (`id`, `display_name`, `email`, `company`, `phone`, `job_title`, `source`), and never exposes arbitrary HubSpot paths or raw response payloads to agents.

## Adding A New Adapter

1. Add the provider and capability contract to [CONTRACTS.md](CONTRACTS.md).
2. Add `src/grantora/adapters/{provider}.py`.
3. Implement the shared adapter protocol.
4. Add schema validation for normalized output.
5. Add unit tests for success normalization and error mapping.
6. Add integration tests with a mock upstream service.
7. Update [PLAN.md](PLAN.md) if the adapter is part of an active milestone.

## Capability Templates

Built-in setup templates live in `src/grantora/adapters/templates.py` and are exposed through the Admin API:

- `GET /v1/admin/capability-templates`
- `POST /v1/admin/capabilities/from-template`

Templates include capability ids, adapter ids, operations, JSON Schemas, required secret types and upstream permissions. They must not include base URLs, tokens, passwords, cookies or private provider configuration.

## First Adapter: NethVoice Phonebook Search

Capability id: `nethvoice.phonebook.search`

Input:

```json
{
  "query": "Mario",
  "limit": 10
}
```

Output:

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

Rules:

- Read-only only.
- Call the configured application `base_url` at `GET /api/phonebook/search` with `query` and the enforced `limit`.
- Enforce maximum result limit from the capability input schema.
- Return only `display_name`, `phone`, `company` and `source` unless the contract is updated.
- Do not log contact payloads by default.
- Required upstream permission: delegated phonebook/contact read access for the selected user or API key.
- Health probing calls the same safe phonebook endpoint without credentials. A 401 or 403 means the upstream is reachable but credentials are required; 404, timeout, 429 and 5xx are mapped to safe health errors.
- Provider payload fixtures are sanitized in `tests/unit/fixtures/nethvoice_phonebook_observed.json`; they must not contain real tokens, cookies, upstream secrets or private contact data.

## Second Adapter: Nextcloud Files Search

Capability id: `nextcloud.files.search`

Input:

```json
{
  "query": "report",
  "limit": 10
}
```

Output:

```json
{
  "files": [
    {
      "path": "/Documents/Quarterly report.pdf",
      "display_name": "Quarterly report.pdf",
      "mime_type": "application/pdf",
      "size": 4096,
      "modified_at": "2024-06-01T12:00:00Z",
      "source": "nextcloud"
    }
  ]
}
```

Rules:

- Read-only only.
- Call the configured application `base_url` at `GET /ocs/v2.php/search/providers/files/search` with `term` and the enforced `limit`.
- Send `OCS-APIRequest: true` and request JSON responses.
- Support `basic_auth` secrets formatted as `username:app-password` and `bearer_token` secrets when the deployment supports bearer authentication.
- Required upstream permissions: delegated file read/search access for the selected user. For typical Nextcloud deployments this means a user app password or equivalent credential with Files access.
- Normalize only `path`, `display_name`, `mime_type`, `size`, `modified_at` and `source`; do not expose share metadata, owner details, raw WebDAV URLs, etags or preview links unless the contract is updated.
- Health probing calls the OCS file search endpoint without credentials and maps unauthorized, unavailable and timeout responses safely.