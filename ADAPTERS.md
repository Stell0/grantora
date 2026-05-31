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
- Do not retry non-idempotent capabilities unless the capability contract explicitly allows it.
- Read-only capabilities may retry safe network failures once when the caller can tolerate duplicate reads.
- Always return a safe timeout or upstream error when retries are exhausted.

## Logging Rules

- Log request id, workspace id, capability id, provider type and safe status.
- Do not log authorization headers, tokens, cookies, decrypted secrets or raw upstream response bodies.
- Do not log contact payloads, file contents or message bodies by default.

## Adding A New Adapter

1. Add the provider and capability contract to [CONTRACTS.md](CONTRACTS.md).
2. Add `src/grantora/adapters/{provider}.py`.
3. Implement the shared adapter protocol.
4. Add schema validation for normalized output.
5. Add unit tests for success normalization and error mapping.
6. Add integration tests with a mock upstream service.
7. Update [PLAN.md](PLAN.md) if the adapter is part of an active milestone.

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
- Enforce maximum result limit from the capability input schema.
- Return only `display_name`, `phone`, `company` and `source` unless the contract is updated.
- Do not log contact payloads by default.