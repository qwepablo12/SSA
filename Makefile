.PHONY: help install up down logs psql fmt lint typecheck layers test test-unit check migrate revision downgrade current history

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install all dependency groups into the local venv
	uv sync --all-extras --group dev

up:  ## Start local PostgreSQL
	docker compose up -d
	@echo "waiting for postgres..." && sleep 2

down:  ## Stop local PostgreSQL (keeps the volume)
	docker compose down

logs:  ## Tail PostgreSQL logs
	docker compose logs -f postgres

psql:  ## Open a psql shell against the dev database
	docker compose exec postgres psql -U ssa -d ssa

fmt:  ## Format
	uv run ruff format src tests migrations
	uv run ruff check --fix src tests migrations

lint:  ## Lint (no fixes)
	uv run ruff format --check src tests migrations
	uv run ruff check src tests migrations

typecheck:  ## Static types
	uv run mypy src

layers:  ## Enforce the architecture (01 §3, 02 §7)
	uv run lint-imports

test:  ## Full suite (needs `make up`)
	uv run pytest

test-unit:  ## Domain-only tests — no database, fast
	uv run pytest -m "not integration"

check: lint typecheck layers test  ## Everything CI runs

migrate:  ## Apply all migrations
	uv run alembic upgrade head

revision:  ## Autogenerate a migration: make revision m="add users"
	uv run alembic revision --autogenerate -m "$(m)"

downgrade:  ## Roll back one migration
	uv run alembic downgrade -1

current:  ## Show the applied revision
	uv run alembic current

history:  ## Show migration history
	uv run alembic history --verbose
