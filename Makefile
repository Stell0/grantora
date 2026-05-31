.PHONY: test test-unit test-integration test-e2e test-all lint format format-check migrate demo-seed smoke retention backup-restore-smoke security-scan sbom container-scan release-security release-image release-image-smoke publish-image dev-up dev-down

SECURITY_ARTIFACT_DIR ?= dist/security
IMAGE ?= grantora-api:security
VERSION ?= $(shell python -c "import pathlib, tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
REGISTRY ?= ghcr.io/grantora
IMAGE_NAME ?= grantora-api
RELEASE_IMAGE ?= $(REGISTRY)/$(IMAGE_NAME):$(VERSION)
RELEASE_SMOKE_PORT ?= 18080

test:
	pytest

test-unit:
	pytest tests/unit

test-integration:
	@set -a; \
	[ ! -f .env ] || . ./.env; \
	set +a; \
	pytest tests/integration -m integration

test-e2e:
	@set -a; \
	[ ! -f .env ] || . ./.env; \
	set +a; \
	pytest tests/e2e -m e2e

test-all:
	pytest tests/unit tests/integration tests/e2e

lint:
	ruff check .

format:
	ruff format .

format-check:
	ruff format --check .

migrate:
	alembic upgrade head

demo-seed:
	@set -a; \
	[ ! -f .env ] || . ./.env; \
	[ ! -f .grantora-demo.env ] || . ./.grantora-demo.env; \
	set +a; \
	PYTHONPATH=src$${PYTHONPATH:+:$${PYTHONPATH}} python -m grantora.cli.demo_seed

smoke:
	@set -a; \
	[ ! -f .env ] || . ./.env; \
	[ ! -f .grantora-demo.env ] || . ./.grantora-demo.env; \
	set +a; \
	PYTHONPATH=src$${PYTHONPATH:+:$${PYTHONPATH}} python -m grantora.cli.smoke

retention:
	@set -a; \
	[ ! -f .env ] || . ./.env; \
	set +a; \
	PYTHONPATH=src$${PYTHONPATH:+:$${PYTHONPATH}} python -m grantora.cli.retention

backup-restore-smoke:
	@set -a; \
	[ ! -f .env ] || . ./.env; \
	[ ! -f .grantora-demo.env ] || . ./.grantora-demo.env; \
	set +a; \
	PYTHONPATH=src$${PYTHONPATH:+:$${PYTHONPATH}} python -m grantora.cli.backup_restore_smoke

security-scan:
	mkdir -p $(SECURITY_ARTIFACT_DIR)
	python -m pip_audit --strict --format json --output $(SECURITY_ARTIFACT_DIR)/dependency-vulnerabilities.json

sbom:
	mkdir -p $(SECURITY_ARTIFACT_DIR)
	python -m cyclonedx_py environment --output-format JSON --output-file $(SECURITY_ARTIFACT_DIR)/sbom.cdx.json

container-scan:
	mkdir -p $(SECURITY_ARTIFACT_DIR)
	trivy image --severity CRITICAL,HIGH --exit-code 1 --format json --output $(SECURITY_ARTIFACT_DIR)/container-vulnerabilities.json $(IMAGE)

release-security: security-scan sbom container-scan

release-image:
	docker build \
		--build-arg GRANTORA_VERSION=$(VERSION) \
		--build-arg VCS_REF=$$(git rev-parse --short=12 HEAD 2>/dev/null || printf unknown) \
		--build-arg BUILD_DATE=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-t $(RELEASE_IMAGE) \
		-f containers/grantora-api.Dockerfile .

release-image-smoke:
	@container_id=$$(docker run --rm -d \
		-p 127.0.0.1:$(RELEASE_SMOKE_PORT):8080 \
		-e MIGRATIONS_AUTO_RUN=false \
		-e DATABASE_URL=sqlite+pysqlite:///:memory: \
		$(RELEASE_IMAGE)); \
	cleanup() { docker rm -f "$$container_id" >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT; \
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		body=$$(curl -fsS http://127.0.0.1:$(RELEASE_SMOKE_PORT)/healthz 2>/dev/null || true); \
		if printf '%s' "$$body" | grep -q '"version":"$(VERSION)"'; then \
			printf '%s\n' "$$body"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	docker logs "$$container_id"; \
	exit 1

publish-image: release-image
	docker push $(RELEASE_IMAGE)

dev-up:
	docker compose up --build

dev-down:
	docker compose down
