# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Student Success Assistant (SSA) — a Telegram-first academic companion that tracks study sessions and
wellbeing data, and layers gamification/analytics/ML on top without rewarding overwork. Single Python
package `ssa`, `src/` layout, Python >=3.12. The project is currently at the very start of Phase 2
(implementation) — most of `docs/` describes the *approved* target architecture, and the tree is being
built bottom-up to match it, in the order fixed by `docs/02_Project_Structure.md` §9 (shared/domain
common → identity+tracking domain → first migration → repositories → application use cases → DI wiring
→ bot skeleton → scheduler). Read `docs/01_Architecture.md` and `docs/02_Project_Structure.md` before
adding anything that doesn't have an obvious home yet — the target package layout is already fully
specified there even though most of it doesn't exist on disk yet.

## Tech stack

Python 3.12+, `uv` for dependency management. SQLAlchemy 2.x async ORM + `asyncpg`, Alembic migrations,
PostgreSQL, `pydantic-settings`, `structlog` are base dependencies and are already wired up (see
`src/ssa/infrastructure/database/`, `src/ssa/shared/settings.py`). aiogram 3.x, FastAPI, and Redis are
declared as **optional extras** (`bot`, `api` in `pyproject.toml`) and are not yet installed or used in
`src/` — the MVP image installs only the base group until the bot/API layer actually ships (see the
comment above `[project.optional-dependencies]`). Don't add aiogram/FastAPI/Redis code against the base
install; if a task needs one of them, install the matching extra first (`uv sync --extra bot` /
`--extra api`) and say so. Local Postgres runs via Docker Compose (`docker-compose.yml`); Redis has no
compose service yet — it arrives with the bot (FSM state, rate limiting) per `docker-compose.yml`'s own
top comment. Ruff (lint + format) and mypy (strict on `domain`/`application`) are configured in
`pyproject.toml`; pytest + pytest-asyncio drive the test suite.

## Workflow

These rules govern how to work in this repo, independent of any single task:

- **Inspect before modifying.** Read the actual current file/module before changing it, even if
  `docs/` or this file describes the target state — the tree is mid-build (Phase 2) and code doesn't
  always match the design docs yet. Don't assume a file's contents from its description here.
- **Work incrementally.** Prefer small, reviewable steps over large simultaneous changes, especially
  across layer boundaries (domain → application → infrastructure → apps).
- **Run checks after each completed step**: `make fmt`, `make lint`, `make typecheck`, `make layers`,
  and the relevant test slice (`make test-unit` for domain/application work, `make test` — needs
  `make up` — when infrastructure or migrations are touched).
- **Do not proceed while checks are failing.** Fix or explicitly flag a failure before starting the
  next step; don't stack unrelated changes on top of a red suite.
- **Never commit secrets or the real `.env` file.** `.env` is already git-ignored — keep it that way,
  and only ever edit `.env.example` with placeholder values.
- **Show the `git diff` before every commit** and wait for confirmation.
- **Never push to GitHub without asking first**, even to a feature branch.

## Commands

Dependency management is `uv`. All commands below are also in the `Makefile` — prefer `make <target>`.

```
make install     # uv sync --all-extras --group dev
make up           # start local Postgres (docker compose), and creates the *_test DB via scripts/init-test-db.sql
make down         # stop Postgres, keep the volume
make psql         # psql shell into the dev DB

make fmt          # ruff format + ruff check --fix (src tests migrations)
make lint         # ruff format --check + ruff check, no fixes
make typecheck    # mypy src
make layers       # import-linter — enforces the architecture, see below
make test         # full suite, needs `make up`
make test-unit    # domain-only tests, no DB, fast (`pytest -m "not integration"`)
make check        # lint + typecheck + layers + test — everything CI runs

make migrate      # alembic upgrade head
make revision m="add users"   # alembic revision --autogenerate -m "..."
make downgrade    # alembic downgrade -1
make current      # alembic current
make history      # alembic history --verbose
```

Running a single test: `uv run pytest tests/unit/test_foundation.py::test_name` (standard pytest
node-id selection works throughout; `test-unit` is just `-m "not integration"`).

Integration tests (`@pytest.mark.integration`) require a live Postgres — run `make up` first. They
connect to a database whose name must end in `_test` (`tests/conftest.py` asserts this); it's a guard
because the harness truncates whatever it connects to. Every test runs inside a transaction rolled back
at teardown (`join_transaction_mode="create_savepoint"`), so tests never see each other's rows and
`commit()` inside code under test is safe to call for real.

No SQLite anywhere, ever, even for "simple" tests — partial indexes, generated columns, and
`TIMESTAMPTZ` semantics don't exist in SQLite, so a passing SQLite suite proves nothing about the
constraints the schema relies on.

## Architecture

Layered clean architecture, dependencies point inward only, enforced in CI by `import-linter`
(`pyproject.toml` `[tool.importlinter]`, run via `make layers`) — not by convention:

```
apps/*  (bot, api, scheduler, cli)   — thin adapters, zero business logic
   ↓
application/   — use cases / services: orchestration, transactions, authorisation
   ↓
domain/        — entities, value objects, rules, protocols. Pure Python.
   ↑ implements protocols
infrastructure/ — SQLAlchemy repos, Redis, Telegram sender, job runner, ML store
```

- `domain` imports nothing internal, and must never import `sqlalchemy`, `alembic`, `aiogram`,
  `fastapi`, `redis`, `pandas`, or `asyncpg`. It declares repository/Clock/UnitOfWork **protocols**;
  infrastructure implements them. This inversion is what makes the domain unit-testable with no
  database and no mocking library.
- `application` imports `domain` + `shared` only — no framework imports, and no job-runtime library
  (celery/taskiq) either. This is the mechanism that makes the deferred job-runtime decision (D5,
  see Decision Log) safe: swapping the in-process scheduler for a real queue later touches only
  `infrastructure`/`apps`, never `application`.
- `apps.bot` additionally may not import `ssa.infrastructure.database.models` or `matplotlib`.
- A PR that breaks any of the above fails CI (`make layers` / `lint-imports`), not just review.

**ORM models and domain entities are deliberately separate classes**, joined by explicit mappers
(`infrastructure/database/mappers/`), not shared. This costs more code than mapping directly, in
exchange for: domain stays free of `sqlalchemy` so the dependency rule is enforceable rather than
aspirational, lazy-loading can never leak into business logic, and schema changes don't ripple into
domain rules. (Documented as revisitable around the fifth entity — see ADR-004 — if it proves to be
excessive friction; not a decision to silently override before then.)

**Feature modules are bounded contexts** (`identity`, `tracking`, `goals`, `social`, `gamification`,
`analytics`, `ml`, `notifications`), each owning its own entities/services/repositories inside every
layer. They form a DAG (`identity` depends on nothing; everything else eventually depends on it — full
table in `docs/01_Architecture.md` §5). Module A never imports module B's repositories or ORM models
directly — it goes through B's service/protocol, or reacts to a **domain event** B published (e.g.
`tracking` publishes `StudySessionCompleted`; `gamification` subscribes). Any proposed dependency
cycle between modules is a design error to be resolved with an event, not a back-reference.

**One request/update/job = one DB session = one transaction = one commit**, owned by the application
service (`@transactional` marks that single commit point). Repositories add/query/flush — they never
commit or roll back. Nested use cases join the caller's transaction rather than opening their own.

**Time**: every timestamp is `TIMESTAMPTZ`/UTC; `users.timezone` is an IANA name, never an offset.
"Today", streaks, and rollups are computed in the user's local time via the injected `Clock` protocol
(`src/ssa/domain/common/protocols.py`) — application code must never call `datetime.now()` directly,
since that's what makes time freezable in tests.

**Errors**: a single `SSAError` hierarchy in `src/ssa/domain/common/errors.py`
(`ValidationError`, `NotFoundError`, `PermissionDeniedError`, `ConflictError`, `RateLimitedError`,
`ExternalServiceError`), translated once at each boundary (bot → friendly text, API → HTTP status).
Infrastructure exceptions (`sqlalchemy.IntegrityError`, `RedisError`, `TelegramAPIError`) must be
caught in `infrastructure/` and re-raised as one of these — a raw SQLAlchemy exception reaching a
handler is a bug in the repository that let it through, not an acceptable edge case.

**Config**: one typed `Settings` (`src/ssa/shared/settings.py`, `pydantic-settings`, `SSA_` env prefix,
`__` nested delimiter, `extra="forbid"`). Loaded once via `Settings.load()` at process entrypoints only
(`apps/*/main.py`, Alembic `env.py`, test harness) and injected everywhere else — never read
`os.environ` deep inside a module. A missing/malformed value must fail at boot, not on first use.

**DB naming/types**: `src/ssa/infrastructure/database/base.py` defines the Alembic-critical constraint
`NAMING_CONVENTION` (must exist before migration 001 — retrofitting means hand-editing every migration
in every environment) and a `type_annotation_map` where `datetime` → `TIMESTAMP(timezone=True)`
structurally, so a naive timestamp column can't be created by accident. `str` maps to `TEXT`, not
`VARCHAR(n)` — length limits are expressed as named CHECK constraints instead, in `types.py`.

**Runtime processes**, one codebase/image, different entrypoints: `bot` (aiogram 3, Telegram webhook),
`api` (FastAPI, for future web/mobile clients), `scheduler` (asyncio loop + Postgres advisory lock,
nightly/weekly rollups — exactly one instance by design), `worker` (post-MVP, queue-routed). The
scheduler/job layer is deliberately swappable for Taskiq/Celery later (D5) — jobs are thin adapters
over the same application use cases a handler would call, and **every job must be idempotent**
(`rebuild_*` naming is used deliberately for scheduled use cases to keep that visible), since the MVP
scheduler has no retry-with-backoff or crash recovery.

## Reference documents

`docs/` contains the approved design and is the source of truth ahead of code for anything not yet
built — consult before inventing structure:

- `00_Decision_Log.md` — D1–D6 resolved architecture questions (leaderboards as derived Redis
  projection, capped/balanced scoring instead of raw hours, no generic event log, internal bigint id +
  external `public_id` UUID, deferred job-runtime choice, k≥20 anonymised-analytics threshold).
- `01_Architecture.md` — the full architecture (this file's Architecture section is a condensed view).
- `02_Project_Structure.md` — target package layout, naming conventions, build order.
- `03_Technology_Decisions.md`, `04_Data_Strategy_and_Deployment.md`, `05_Scoring_Model.md`,
  `06_Database_Schema.md` — technology choices, deployment/data retention strategy, the gamification
  scoring formula (caps + wellbeing gate), and schema design.

## Conventions

| Concern | Convention |
|---|---|
| Modules | `snake_case`, plural for collections (`handlers/`, `repositories/`) |
| Domain entities | Singular noun (`StudySession`) |
| ORM models | Same name as the entity, disambiguated only by import path (`infrastructure.database.models`), never aliased |
| Repository methods | `get_by_id` (raises `NotFoundError`), `find_by_id` (returns `None`), `list_*`, `add`, `remove` |
| Use case classes | Verb phrase, single `execute()` (`CompleteStudySession`) |
| Scheduled jobs | `rebuild_*` — signals idempotence at the call site |
| Async | Everything I/O-touching is `async def`; everything else is pure/sync |
| Type hints | Mandatory everywhere; `mypy` is strict-by-flags on `ssa.domain.*` and `ssa.application.*` (see `pyproject.toml`), looser elsewhere |

`shared/` is the only package importable from every layer and is meant to stay tiny (Settings, logging
config, correlation-id context vars, generic typing helpers) — no business concepts, no I/O clients. If
it grows past a few hundred lines it has become a dumping ground.

`notebooks/` is read-only with respect to production code and is never imported by `src/` — anything
proven useful there gets rewritten into `application/ml/` with tests.
