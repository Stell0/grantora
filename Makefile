.PHONY: test lint format format-check migrate demo-seed smoke dev-up dev-down

test:
	pytest

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
