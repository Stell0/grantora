from __future__ import annotations

import tomllib
from pathlib import Path

from grantora import __version__

ROOT = Path(__file__).parents[2]


def test_package_version_matches_project_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert __version__ == project["version"]


def test_release_image_build_publish_and_smoke_are_defined() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    dockerfile = (ROOT / "containers" / "grantora-api.Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "release-image:" in makefile
    assert "--build-arg GRANTORA_VERSION=$(VERSION)" in makefile
    assert "release-image-smoke:" in makefile
    assert "http://127.0.0.1:$(RELEASE_SMOKE_PORT)/healthz" in makefile
    assert "publish-image: release-image" in makefile
    assert "docker push $(RELEASE_IMAGE)" in makefile

    assert "ARG GRANTORA_VERSION=0.1.0" in dockerfile
    assert "org.opencontainers.image.version" in dockerfile
    assert "GRANTORA_IMAGE_VERSION=${GRANTORA_VERSION}" in dockerfile

    assert "name: Release Image" in workflow
    assert "tags:" in workflow and '"v*"' in workflow
    assert "Tag ${GITHUB_REF_NAME} does not match pyproject version" in workflow
    assert "Smoke image reports version" in workflow
    assert (
        "docker push ${{ steps.release.outputs.image }}:${{ steps.release.outputs.version }}"
        in workflow
    )


def test_production_compose_uses_published_image_and_isolates_private_services() -> None:
    compose = (ROOT / "deploy" / "compose.production.yml").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy" / "production.env.example").read_text(encoding="utf-8")

    assert "image: ${GRANTORA_IMAGE:-ghcr.io/grantora/grantora-api" in compose
    assert "build:" not in compose
    assert "MIGRATIONS_AUTO_RUN: ${MIGRATIONS_AUTO_RUN:-false}" in compose
    assert "GRANTORA_PUBLIC_BASE_URL: ${GRANTORA_PUBLIC_BASE_URL:?set" in compose
    assert "SECRET_ENCRYPTION_KEY: ${SECRET_ENCRYPTION_KEY:?set" in compose
    assert (
        "GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH: ${GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH:?set" in compose
    )
    assert "APISIX_ADMIN_KEY: ${APISIX_ADMIN_KEY:?set" in compose
    assert '- "${APISIX_PUBLIC_PORT:-9080}:9080"' in compose
    assert "${GRANTORA_API_PORT" not in compose
    assert "${POSTGRES_PORT" not in compose
    assert "${APISIX_ADMIN_PORT" not in compose
    assert "9180:9180" not in compose
    assert "grantora-private:" in compose
    assert "internal: true" in compose
    assert "grantora-egress:" in compose

    assert "GRANTORA_IMAGE=ghcr.io/grantora/grantora-api:0.1.0" in env_example
    assert "POSTGRES_PASSWORD=replace-with-long-random-postgres-password" in env_example
    assert "SECRET_ENCRYPTION_KEY=replace-with-generated-fernet-key" in env_example


def test_release_and_ns8_docs_cover_upgrade_and_standalone_requirements() -> None:
    release_doc = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    ns8_doc = (ROOT / "docs" / "ns8-packaging.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    operations = (ROOT / "OPERATIONS.md").read_text(encoding="utf-8")

    assert "make release-image" in release_doc
    assert "make release-image-smoke" in release_doc
    assert "python -m alembic upgrade head" in release_doc
    assert 'curl -sS "$GRANTORA_API_URL/healthz"' in release_doc
    assert "make backup-restore-smoke" in release_doc
    assert "make security-scan" in release_doc
    assert "make sbom" in release_doc
    assert "make container-scan IMAGE=<candidate-image>" in release_doc
    assert "## Release Checklist" in release_doc
    assert 'git commit -m "feat: add release packaging and production deployment"' in release_doc

    assert "must not import NS8 libraries" in ns8_doc
    assert "Standalone compose deployments must keep working" in ns8_doc
    assert "PostgreSQL" in ns8_doc

    assert "deploy/compose.production.yml" in readme
    assert "docs/release.md" in operations
