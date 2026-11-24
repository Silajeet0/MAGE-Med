.PHONY: bootstrap backend frontend db-upgrade neo4j-up neo4j-down format format-check lint typecheck test build check smoke

ifneq (,$(wildcard .env))
include .env
export
endif

MAGE_MED_BACKEND_HOST ?= 127.0.0.1
MAGE_MED_BACKEND_PORT ?= 8000
MAGE_MED_FRONTEND_HOST ?= 127.0.0.1
MAGE_MED_FRONTEND_PORT ?= 5173

bootstrap:
	uv sync --all-packages --frozen
	npm ci

backend:
	uv run uvicorn mage_med_backend.main:app --host $(MAGE_MED_BACKEND_HOST) --port $(MAGE_MED_BACKEND_PORT) --no-access-log

frontend:
	npm --workspace @mage-med/frontend run dev -- --host $(MAGE_MED_FRONTEND_HOST) --port $(MAGE_MED_FRONTEND_PORT)

db-upgrade:
	uv run alembic -c apps/backend/alembic.ini upgrade head

neo4j-up:
	docker compose -f infrastructure/compose.yaml up -d --wait

neo4j-down:
	docker compose -f infrastructure/compose.yaml down

format:
	uv run ruff format .
	npm run format

format-check:
	uv run ruff format --check .
	npm run format:check

lint:
	uv run ruff check .
	npm run lint

typecheck:
	uv run mypy
	npm run typecheck

test:
	uv run pytest -m "not neo4j_smoke"
	npm test

build:
	npm run build

check: format-check lint typecheck test build

smoke:
	bash scripts/smoke.sh
