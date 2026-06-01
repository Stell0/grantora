# NS8 Packaging Design Notes

Grantora remains a standalone upstream application. An NS8 module may manage it, but the runtime must not import NS8 libraries, require NS8 services, or store dynamic state outside PostgreSQL.

## Module Responsibilities

- Generate and preserve environment files containing static configuration and secret material.
- Start the published Grantora API image, PostgreSQL, APISIX and APISIX etcd with network isolation equivalent to `deploy/compose.production.yml`.
- Use a clean or compatible PostgreSQL database; during development the API creates the current schema from SQLAlchemy metadata at startup.
- Trigger APISIX reconciliation after install, restore and upgrade.
- Back up PostgreSQL plus environment-managed `SECRET_ENCRYPTION_KEY`, token peppers, APISIX Admin key and any external secret-store configuration.
- Expose UI or actions for health, readiness, APISIX sync status, backup, restore, smoke checks and secret rotation.

## Upstream Boundaries

- Grantora configuration stays environment-only.
- Dynamic workspaces, applications, users, capabilities, roles, bindings, secrets, audit and usage stay in PostgreSQL.
- APISIX remains generated data-plane state, not the source of truth.
- The Admin API remains the supported dynamic configuration surface.
- Standalone compose deployments must keep working without NS8-specific files or services.

## NS8 Integration Points

- Optional OIDC/NS8 admin identity can be enabled with `FEATURE_OIDC=true` only behind a trusted component in `OIDC_TRUSTED_PROXY_CIDRS` that strips and sets the configured identity header.
- Account-domain integration should create or map users through supported Admin APIs.
- Module backup hooks should reuse the documented PostgreSQL dump/restore and APISIX resync order.
- Module upgrades should use versioned container tags and the same release checklist in `docs/release.md`.

## Acceptance Checks

- A standalone deployment using `deploy/compose.production.yml` can start, sync APISIX and pass smoke tests.
- Removing NS8-specific environment variables leaves bootstrap-token administration available.
- Restoring PostgreSQL and environment secrets into a clean standalone compose deployment preserves policy and invocation behavior.