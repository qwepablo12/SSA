# Student Success Assistant — Project Structure

**Phase 1 · Architecture & Foundation**
Version 1.1 · Companion to `01_Architecture.md` · incorporates decisions D1–D6

---

## 1. Repository layout

Single repository, single installable package `ssa`, four entrypoints.

```
student-success-assistant/
├── src/
│   └── ssa/
│       ├── domain/
│       ├── application/
│       ├── infrastructure/
│       ├── apps/
│       └── shared/
├── migrations/
├── tests/
├── scripts/
├── docs/
├── deploy/
├── notebooks/
├── pyproject.toml
├── docker-compose.yml
├── docker-compose.override.yml
├── Dockerfile
├── Makefile
├── .env.example
└── README.md
```

`src/` layout (rather than a top-level `ssa/`) is deliberate: it makes it impossible to accidentally import the source tree instead of the installed package, which is the usual cause of "works locally, fails in Docker".

---

## 2. `domain/` — pure business core

No framework imports. No I/O. This directory could be copied into a completely different application and still compile.

```
domain/
├── common/
│   ├── entity.py            # Entity base, identity equality
│   ├── value_objects.py     # Duration, FocusScore, DateRange, LocalDate
│   ├── events.py            # DomainEvent base + registry
│   ├── errors.py            # SSAError hierarchy (Architecture §7.2)
│   └── protocols.py         # Clock, UnitOfWork, EventPublisher,
│                            #   JobRunner, PeriodicSchedule, JobContext  (D5)
│
├── identity/
│   ├── entities.py          # User, TelegramAccount, PrivacySettings
│   ├── enums.py             # PrivacyLevel, AccountStatus
│   ├── rules.py             # can_view_profile(), deletion invariants
│   └── repositories.py      # UserRepository protocol
│
├── tracking/
│   ├── entities.py          # StudySession, SleepLog, MoodLog, ExerciseLog, Subject
│   ├── enums.py             # SessionType, Mood, ExerciseIntensity
│   ├── rules.py             # max session length, overlap detection, focus scoring
│   ├── events.py            # StudySessionCompleted, SleepLogged
│   └── repositories.py
│
├── goals/                   # Goal, GoalPeriod, CommittedSchedule, progress evaluation
├── social/
│   ├── entities.py          # Friendship, StudyGroup, Membership
│   ├── policies.py          # VisibilityPolicy — the single authorisation point
│   └── repositories.py
├── gamification/
│   ├── entities.py          # Achievement, Streak, Challenge, WeeklyScore
│   ├── scoring.py           # pure functions: the five components, caps,
│   │                        #   wellbeing gate  (05_Scoring_Model.md)
│   ├── rules.py             # streak continuity, grace days, cold-start gate
│   └── repositories.py
├── analytics/               # DailyStats, WeeklyStats, Insight, ChartSpec,
│                            #   AnonymisedAggregateQuery (k >= 20)  (D6)
├── ml/
│   ├── entities.py          # Prediction, Recommendation, ModelVersion
│   ├── protocols.py         # ProductivityPredictor, Recommender, BurnoutDetector
│   └── features.py          # FeatureSet definition (as_of-aware, leakage-safe)
└── notifications/           # Notification, NotificationPreferences, QuietHours
```

**Why entities are rich, not dataclasses:** `StudySession.complete(ended_at)` validates duration and emits the completion event. If that logic lives in a service instead, every new caller can forget it. Rules that must always hold belong on the entity.

**Why `gamification/scoring.py` is pure functions rather than a service:** the scoring model is a deterministic transformation of stats into a score. Keeping it free of I/O means the caps and the wellbeing gate can be property-tested exhaustively against extreme inputs (Architecture §11) — which is the only way to *prove*, rather than hope, that no amount of overwork raises a score.

**Why repository protocols live in `domain/`, not `infrastructure/`:** this is the dependency inversion that makes the whole layering work. The domain declares what it needs; infrastructure supplies it.

---

## 3. `application/` — use cases

One class per use case where the operation is non-trivial; grouped service classes where operations are simple CRUD around one entity.

```
application/
├── common/
│   ├── dto.py               # Pydantic DTOs crossing the boundary
│   ├── uow.py               # UnitOfWork protocol + context manager
│   └── decorators.py        # @transactional, @authorised
│
├── identity/
│   ├── services.py          # UserService: register, update_timezone, set_privacy
│   ├── dto.py
│   └── use_cases/
│       ├── onboard_user.py
│       ├── export_user_data.py
│       └── delete_account.py
│
├── tracking/
│   ├── services.py          # StudySessionService, WellbeingLogService
│   └── use_cases/
│       ├── start_session.py
│       ├── complete_session.py     # publishes StudySessionCompleted
│       └── log_daily_wellbeing.py
│
├── goals/services.py
├── social/services.py       # friend requests, groups; delegates to VisibilityPolicy
├── gamification/
│   ├── services.py
│   ├── handlers.py          # reacts to StudySessionCompleted → award achievements
│   └── use_cases/
│       ├── compute_weekly_scores.py    # idempotent
│       └── rebuild_leaderboards.py     # writes Redis sorted sets  (D1)
├── analytics/
│   ├── services.py          # read-side queries for the bot/api
│   └── use_cases/
│       ├── rebuild_daily_stats.py      # idempotent, scheduled
│       ├── rebuild_weekly_stats.py     # idempotent, scheduled
│       └── generate_insights.py
├── ml/
│   ├── services.py          # reads stored predictions
│   └── use_cases/
│       ├── build_features.py
│       ├── train_models.py
│       └── run_batch_inference.py
└── notifications/
    ├── services.py          # enqueue (respects quiet hours + daily cap)
    └── use_cases/dispatch_due_notifications.py
```

**Every use case invoked by a job is idempotent** (Architecture §6.2) — `rebuild_*` names are chosen over `compute_*` deliberately, to keep that expectation visible at every call site.

**DTO boundary:** handlers pass DTOs in and receive DTOs out. ORM models never leave the application layer, and domain entities never reach a handler. This is what stops a template change from being coupled to a column rename.

**`@transactional`:** marks the single commit point of a use case (Architecture §7.1). Nested use cases are called without it and join the caller's transaction.

---

## 4. `infrastructure/` — adapters out

```
infrastructure/
├── database/
│   ├── engine.py            # async engine + sessionmaker factories
│   ├── base.py              # DeclarativeBase + naming_convention (Alembic-critical)
│   ├── uow.py               # SqlAlchemyUnitOfWork
│   ├── models/              # ORM models — mirror the domain, are NOT the domain
│   │   ├── user.py
│   │   ├── tracking.py
│   │   ├── social.py
│   │   ├── gamification.py
│   │   ├── analytics.py
│   │   ├── ml.py
│   │   └── notification.py
│   ├── mappers/             # ORM model ⇄ domain entity
│   └── repositories/        # implement the domain protocols
│       ├── user_repository.py
│       ├── study_session_repository.py
│       └── ...
│
├── cache/
│   ├── redis_client.py
│   ├── leaderboard_cache.py # Redis sorted sets — current rankings  (D1)
│   └── rate_limiter.py      # token bucket
│
├── jobs/                    # the swappable runtime  (D5)
│   ├── in_process.py        # InProcessJobRunner — MVP
│   ├── schedule.py          # declarative PeriodicSchedule registry
│   ├── advisory_lock.py     # Postgres lock: single scheduler instance
│   └── README.md            # migration notes for Taskiq / Celery
│
├── telegram/
│   ├── sender.py            # TelegramSender — the ONLY outbound Telegram path
│   └── throttle.py          # 30/s global, 1/s per chat
│
├── ml/
│   ├── model_store.py       # artifact load/save, versioning
│   ├── estimators/          # sklearn / XGBoost / LightGBM wrappers
│   └── heuristics/          # HeuristicRecommender — the cold-start implementation
│
├── analytics/
│   └── chart_renderer.py    # matplotlib/plotly → PNG; scheduler/worker only,
│                            #   never imported by apps.bot (import contract)
│
└── clock.py                 # SystemClock implementing the Clock protocol
```

**Separate ORM models and domain entities (mappers, not shared classes).** This is the one place the structure costs more code than the naive approach, and it is worth it because: the domain stays free of `sqlalchemy` (making the dependency rule enforceable rather than aspirational), lazy-loading can't leak into business logic and cause surprise queries, and schema changes stop rippling into domain rules. If this proves to be excessive friction in Phase 2, the fallback is imperative mapping (`registry.map_imperatively`), which preserves the separation with less mapper code. That decision is worth revisiting once ~5 entities exist — not before.

---

## 5. `apps/` — entrypoints (thin)

```
apps/
├── bot/
│   ├── main.py              # dispatcher setup, webhook/polling, DI container
│   ├── middlewares/
│   │   ├── correlation.py
│   │   ├── di.py
│   │   ├── user.py          # telegram_id → User, onboarding branch
│   │   ├── throttling.py
│   │   └── error.py
│   ├── handlers/            # one module per feature; NO business logic
│   │   ├── start.py
│   │   ├── study.py
│   │   ├── wellbeing.py
│   │   ├── goals.py
│   │   ├── stats.py
│   │   ├── social.py
│   │   ├── settings.py
│   │   └── privacy.py       # export, delete
│   ├── keyboards/           # inline/reply keyboard builders
│   ├── presenters/          # domain DTO → user-facing text
│   ├── states.py            # FSM states (Redis-backed storage)
│   └── filters.py
│
├── api/
│   ├── main.py              # FastAPI app factory
│   ├── dependencies.py
│   ├── exception_handlers.py  # SSAError → HTTP status
│   ├── routers/
│   │   ├── health.py
│   │   ├── users.py
│   │   ├── sessions.py
│   │   ├── goals.py
│   │   ├── analytics.py
│   │   ├── social.py
│   │   └── predictions.py
│   └── schemas/             # request/response models
│
├── scheduler/               # MVP background process  (D5)
│   ├── main.py              # asyncio loop, advisory lock, graceful shutdown
│   ├── schedule.py          # ALL periodic jobs declared in one place
│   └── jobs/                # thin adapters — no logic
│       ├── analytics.py     # nightly rebuild_daily_stats
│       └── maintenance.py   # retention, anonymisation
│
└── cli/
    └── main.py              # typer: seed, backfill, rebuild-stats, export
```

**`apps/scheduler/` is a placeholder for a queue runtime, and is structured to be one.** Jobs are thin adapters over use cases; the schedule is declared in a single module. Replacing the in-process loop with Taskiq or Celery means rewriting `main.py` and re-registering the same job functions — the `jobs/` modules and everything they call are untouched. That property is the whole reason the D5 deferral is safe rather than a postponed problem.

**Presenters exist so that message copy is testable and translatable.** Handlers that build strings inline are the reason bot codebases become unmaintainable — you cannot change tone, add a language, or fix a typo without touching control flow.

**Presenters are also where the scoring explanation lives** — `05_Scoring_Model.md` requires the bot to show *why* a score moved, which is a formatting concern over persisted component values, not a service concern.

---

## 6. Supporting directories

```
migrations/                  # Alembic; one migration per logical change, both directions tested
│   ├── env.py
│   └── versions/
│
tests/
│   ├── unit/                # domain — no DB, fast, the bulk of the suite
│   ├── integration/         # repositories, real Postgres
│   ├── application/         # use cases end-to-end within a transaction
│   ├── api/
│   ├── bot/
│   ├── factories/           # factory_boy
│   └── conftest.py
│
scripts/                     # entrypoint.sh, wait-for-it, backup.sh
deploy/                      # Caddyfile, systemd unit, CI deploy scripts
docs/                        # these documents + ADRs + ERD
notebooks/                   # EDA and model prototyping (never imported by src/)
```

### `shared/`

The only package importable from every layer, and deliberately tiny: `Settings` (pydantic-settings), logging configuration, correlation-id context vars, and generic typing helpers. **No business concepts, no I/O clients.** A `shared/` package that grows past a few hundred lines has become a dumping ground and should be split — this is the most common way a clean layering quietly dissolves.

**`notebooks/` is read-only with respect to production code.** Anything a notebook proves useful gets rewritten into `application/ml/` with tests. Notebooks are never imported.

---

## 7. Import rules, stated as contracts

Enforced by `import-linter` in CI (`pyproject.toml`), not by discipline:

```
ssa.domain          →  (nothing internal)
ssa.application     →  ssa.domain, ssa.shared
ssa.infrastructure  →  ssa.domain, ssa.shared
ssa.apps.*          →  ssa.application, ssa.infrastructure, ssa.domain, ssa.shared
```

Additional forbidden-import contracts:

- `ssa.domain` must not import `sqlalchemy`, `aiogram`, `fastapi`, `redis`, `pandas`.
- `ssa.application` must not import `sqlalchemy`, `aiogram`, `fastapi`, or **any job-runtime library** — this contract is what physically enforces the D5 deferral.
- `ssa.apps.bot` must not import `ssa.infrastructure.database.models` or `matplotlib`.
- No module in `ssa.domain.<module_a>` may import `ssa.domain.<module_b>` outside the DAG in Architecture §5.

A violation fails the build. This is the mechanism that keeps the architecture true in month 18, not just month 1.

---

## 8. Naming and style conventions

| Concern | Convention |
|---|---|
| Modules/packages | `snake_case`, plural for collections (`handlers/`, `repositories/`) |
| Domain entities | Singular noun (`StudySession`) |
| ORM models | Same name, in `infrastructure.database.models` — disambiguated by import path, never aliased |
| Repository methods | `get_by_id` (raises), `find_by_id` (returns `None`), `list_*`, `add`, `remove` |
| Use case classes | Verb phrase (`CompleteStudySession`), single `execute()` |
| Scheduled jobs | `rebuild_*` when idempotent — which, per Architecture §6.2, is all of them |
| Async | Everything I/O-touching is `async def`; sync functions are pure |
| Type hints | Mandatory on every function, `mypy --strict` on domain + application |
| Docstrings | Required on public classes and non-obvious functions; explain *why*, not *what* |

---

## 9. Build order for Phase 2 and beyond

Bottom-up, so that every layer is testable when written:

1. `shared/` + `domain/common/` + `Settings` + `Clock`
2. `domain/identity` + `domain/tracking` entities and rules — **with unit tests, no DB**
3. `infrastructure/database` base, models, first Alembic migration
4. Repositories + mappers + integration tests
5. `application/identity` + `application/tracking` use cases
6. DI container wiring
7. `apps/bot` skeleton: start, onboarding, log a study session
8. `apps/scheduler` + `rebuild_daily_stats`, with the idempotence test
9. Everything else, one feature module at a time, each vertically complete

Steps 1–8 produce a working end-to-end slice through every layer *including the background path*. That slice is what validates this architecture — if any of it feels wrong there, it is cheaper to change then than after eight feature modules exist. Step 8 in particular is what proves the D5 deferral holds: if the scheduler cannot run a real job cleanly through the use-case layer, the abstraction is wrong and it is better to find out in week two.
