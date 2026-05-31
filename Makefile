.PHONY: test test-unit test-integration test-e2e test-all lint format format-check migrate demo-seed smoke dev-up dev-down

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

dev-up:
	docker compose up --build

dev-down:
	docker compose down
