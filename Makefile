.PHONY: test test-unit test-integration test-e2e test-all lint format format-check migrate demo-seed smoke retention backup-restore-smoke security-scan sbom container-scan release-security dev-up dev-down

SECURITY_ARTIFACT_DIR ?= dist/security
IMAGE ?= grantora-api:security

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

dev-up:
	docker compose up --build

dev-down:
	docker compose down
