.PHONY: test lint format format-check migrate dev-up dev-down

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

dev-up:
	docker compose up --build

dev-down:
	docker compose down
