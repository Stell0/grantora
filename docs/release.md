# Release And Upgrade Guide

This guide defines the standalone Grantora release process. Release artifacts must be usable without NethServer 8 and must keep PostgreSQL as the source of truth for dynamic state.

## Versioned API Images

The image version comes from `project.version` in `pyproject.toml`, which must match `grantora.__version__`. The running image reports that version from `GET /healthz`.

Build and smoke-test a release image locally:

```bash
make release-image REGISTRY=ghcr.io/grantora
make release-image-smoke REGISTRY=ghcr.io/grantora
```

Publish the versioned image after tests, security gates and the image smoke pass:

```bash
make publish-image REGISTRY=ghcr.io/grantora
```

The `Release Image` GitHub workflow runs on `v*` tags. It verifies that the tag matches `pyproject.toml`, builds the image with OCI labels, starts it with `MIGRATIONS_AUTO_RUN=false`, confirms `/healthz` reports the release version, and then pushes both `<version>` and `sha-<short-sha>` tags to GHCR.

## Production Compose Example

Copy the production environment template and provide real secrets:

```bash
cp deploy/production.env.example .env.production
```

Start from a clean host:

```bash
# Docker
docker compose --env-file .env.production -f deploy/compose.production.yml pull
docker compose --env-file .env.production -f deploy/compose.production.yml up -d postgres apisix-etcd
docker compose --env-file .env.production -f deploy/compose.production.yml run --rm grantora-api python -m alembic upgrade head
docker compose --env-file .env.production -f deploy/compose.production.yml up -d

# Podman
podman compose --env-file .env.production -f deploy/compose.production.yml pull
podman compose --env-file .env.production -f deploy/compose.production.yml up -d postgres apisix-etcd
podman compose --env-file .env.production -f deploy/compose.production.yml run --rm grantora-api python -m alembic upgrade head
podman compose --env-file .env.production -f deploy/compose.production.yml up -d
```

The production example publishes only the APISIX public port. PostgreSQL, APISIX etcd, Grantora API and the APISIX Admin API stay on container networks. Grantora API also joins an egress network so adapters can reach approved business applications.

After required secrets and demo/admin data are supplied, run the same smoke checks used for local operation:

```bash
GRANTORA_API_URL=http://127.0.0.1:8080 GRANTORA_RUNTIME_URL="$GRANTORA_PUBLIC_BASE_URL" make smoke
```

For production deployments, point `GRANTORA_API_URL` at the private operator-accessible Grantora API endpoint and `GRANTORA_RUNTIME_URL` at the APISIX public URL.

## Upgrade Procedure

Before upgrading:

1. Read the release notes, migration notes and this checklist.
2. Back up PostgreSQL and the environment-managed secret material.
3. Run `make backup-restore-smoke` against disposable state when validating the release candidate.
4. Confirm `make security-scan`, `make sbom` and `make container-scan IMAGE=<candidate-image>` pass.

Upgrade one release:

```bash
# Docker
docker compose --env-file .env.production -f deploy/compose.production.yml pull grantora-api
docker compose --env-file .env.production -f deploy/compose.production.yml stop grantora-api
docker compose --env-file .env.production -f deploy/compose.production.yml run --rm grantora-api python -m alembic upgrade head
docker compose --env-file .env.production -f deploy/compose.production.yml up -d grantora-api

# Podman
podman compose --env-file .env.production -f deploy/compose.production.yml pull grantora-api
podman compose --env-file .env.production -f deploy/compose.production.yml stop grantora-api
podman compose --env-file .env.production -f deploy/compose.production.yml run --rm grantora-api python -m alembic upgrade head
podman compose --env-file .env.production -f deploy/compose.production.yml up -d grantora-api

curl -sS "$GRANTORA_API_URL/healthz"
curl -sS "$GRANTORA_API_URL/readyz"
curl -sS -X POST "$GRANTORA_API_URL/v1/admin/apisix/sync" \
  -H "Authorization: Bearer $ADMIN_BOOTSTRAP_TOKEN"
make smoke
```

Rollback is a restore operation unless a release explicitly documents a safe downgrade. Restore the previous PostgreSQL backup, restore the previous environment-managed secrets, start the previous image tag and reconcile APISIX.

## Release Checklist

- [ ] `pyproject.toml` version and `grantora.__version__` match.
- [ ] Contracts, migrations, docs and changelog entries are updated for intentional behavior changes.
- [ ] `make test-unit` passes.
- [ ] `make test-integration` passes against disposable PostgreSQL and APISIX.
- [ ] `make test-e2e` passes through APISIX.
- [ ] `make backup-restore-smoke` passes against disposable compose data.
- [ ] `make security-scan`, `make sbom` and `make container-scan IMAGE=<candidate-image>` pass and artifacts are retained.
- [ ] `make release-image` and `make release-image-smoke` pass.
- [ ] Production compose is reviewed for required secrets, public URL, network exposure and APISIX Admin API isolation.
- [ ] The versioned image is pushed and the pushed digest is recorded.

Useful commit commands for release packaging work:

```bash
git add .github/workflows/release.yml containers/grantora-api.Dockerfile deploy docs Makefile README.md OPERATIONS.md TESTING.md STRUCTURE.md CONTRACTS.md PLAN.md src/grantora/api/health.py tests
git commit -m "feat: add release packaging and production deployment"
```