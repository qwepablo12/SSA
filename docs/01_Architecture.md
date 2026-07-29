# Student Success Assistant — System Architecture

**Phase 1 · Architecture & Foundation**
Version 1.1 · Status: **approved** — incorporates decisions D1–D6 (`00_Decision_Log.md`)

---

## 1. Purpose of this document

This document defines the system architecture for SSA before any implementation code is written. It fixes the layer boundaries, the module responsibilities, the runtime topology, and the rules that all later phases must obey.

If a later feature cannot be built without violating a rule in this document, the rule is revisited explicitly — it is not quietly broken.

---

## 2. Architectural forces

These are the forces that actually shaped the design. Everything below traces back to one of them.

> **Notation:** forces are `F1–F7`; the approved decisions from `00_Decision_Log.md` are `D1–D6`. They are different things and are referenced separately throughout.

| # | Force | Architectural consequence |
|---|---|---|
| F1 | Telegram is the *first* client, not the only one | Business logic must live outside the bot layer. `aiogram` must be replaceable without touching services. |
| F2 | The project's real product is **data** | Data model and aggregate design are first-class concerns, not a side effect of features. |
| F3 | ML arrives *after* months of data collection | The system must work with zero models, and gain models without redesign. Cold-start is a designed state, not a bug. |
| F4 | Solo developer, long-lived project | Optimise for readability and low operational surface. Reject complexity that only pays off at 100k+ users. |
| F5 | Wellbeing is an explicit goal | Gamification and analytics must be constrained *in code* so they cannot reward overwork. |
| F6 | Thousands of users, not millions | Single-node Postgres is sufficient. Design for horizontal readiness, deploy vertically. |
| F7 | Infrastructure choices should be made when they are needed | Background execution, ML serving, and metrics are defined behind interfaces and chosen later. |

---

## 3. Architectural style

**Layered clean architecture with an explicit dependency rule**, organised internally by feature module (bounded context).

```
        ┌──────────────────────────────────────────────┐
        │  DELIVERY / ADAPTERS  (inbound)              │
        │  aiogram handlers · FastAPI routers ·        │
        │  scheduled jobs · CLI                        │
        └───────────────────┬──────────────────────────┘
                            │ depends on
        ┌───────────────────▼──────────────────────────┐
        │  APPLICATION  (use cases / services)         │
        │  orchestration, transactions, authorisation  │
        └───────────────────┬──────────────────────────┘
                            │ depends on
        ┌───────────────────▼──────────────────────────┐
        │  DOMAIN                                      │
        │  entities, value objects, rules, protocols   │
        │  pure Python — no I/O, no framework imports  │
        └───────────────────▲──────────────────────────┘
                            │ implements protocols
        ┌───────────────────┴──────────────────────────┐
        │  INFRASTRUCTURE  (outbound)                  │
        │  SQLAlchemy repos · Redis · Telegram sender · │
        │  job runner · model store · chart renderer   │
        └──────────────────────────────────────────────┘
```

### The dependency rule

**Dependencies point inward only.** Concretely, and enforced in CI by an import-linter contract:

- `domain` imports nothing from `application`, `infrastructure`, or `apps`. It must not import `sqlalchemy`, `aiogram`, `fastapi`, or `redis`.
- `application` imports `domain` only. It talks to the outside world exclusively through **protocols declared in the domain** (`StudySessionRepository`, `Clock`, `NotificationSender`, `JobRunner`, `Recommender`).
- `infrastructure` imports `domain` (to implement its protocols) and may import anything external.
- `apps/*` (bot, api, scheduler) import `application` and wire `infrastructure` into it at startup. They contain **no business rules**.

This is the single most important constraint in the project. It is what makes F1 (a future web/mobile client) a two-week job rather than a rewrite, and what makes F7 (deferred infrastructure choices) safe rather than reckless.

### Why not pure hexagonal / DDD-heavy?

Full DDD (aggregates, domain events, CQRS, repositories per aggregate root) would be defensible but is over-engineered for F4. We take the parts that pay for themselves — the dependency rule, protocol-based ports, rich domain entities — and skip the parts that mostly add ceremony. See ADR-002.

---

## 4. Runtime topology

**One codebase, one Docker image, different entrypoints.** The set of processes grows with need.

### 4.1 Tracking MVP

```
                  Telegram
                      │ webhook (HTTPS)
                      ▼
                 ┌─────────┐
   web/mobile ──▶│  Caddy  │◀── TLS termination, routing
   (future)      └────┬────┘
                 ┌────┴──────────────┐
                 ▼                   ▼
          ┌────────────┐      ┌────────────┐
          │  bot       │      │  api       │
          │ aiogram 3  │      │  FastAPI   │
          └─────┬──────┘      └──────┬─────┘
                └────────┬───────────┘
                         │  same application + domain layer
             ┌───────────┴───────────┐
             ▼                       ▼
       ┌──────────┐            ┌─────────┐
       │ Postgres │            │  Redis  │  FSM state, rate limits
       └────▲─────┘            └─────────┘
            │
       ┌────┴───────┐
       │ scheduler  │  asyncio loop, advisory-lock guarded
       └────────────┘  nightly rollups only — no broker
```

### 4.2 After the job-runtime decision (D5 trigger)

The `scheduler` process is replaced by a queue runtime (Taskiq or Celery — decided later) plus worker processes. **Nothing above the adapter layer changes**, because jobs are application use cases and the runner only decides where and when they execute.

| Process | Responsibility | Scaling | Phase |
|---|---|---|---|
| `bot` | Telegram webhook intake, conversational UX, input parsing, response rendering | Horizontal; stateless | MVP |
| `api` | REST for future web/mobile clients, health/readiness | Horizontal; stateless | MVP |
| `scheduler` | Periodic jobs: nightly and weekly rollups | **Exactly one instance**, enforced by a Postgres advisory lock | MVP |
| `worker` | Notification dispatch, ML training and batch inference, chart rendering, exports | Horizontal; queue-routed | Post-MVP |

**Why `bot` and `api` are separate processes but share a codebase (F1, F4):** a Telegram update storm must not degrade API latency and vice versa, and each has a different failure mode and deploy cadence. But making the bot an HTTP client of the API would duplicate authentication, serialisation, and error mapping for zero benefit while both are written by the same person in the same language. Shared library, separate processes is the right point on that curve.

**Why the scheduler is a separate process even in the MVP:** running the rollup inside the bot would let a long-running aggregation block user-facing updates, and would break the moment a second bot replica appeared (two replicas, two rollups). One purpose-built process with a lock costs about 150 lines and removes both problems.

---

## 5. Feature modules (bounded contexts)

Modules are the *vertical* organisation; layers are the *horizontal* one. Each module owns its entities, services, and repositories.

| Module | Owns | Depends on | Must not |
|---|---|---|---|
| **identity** | User, TelegramAccount, PrivacySettings, consent, timezone, account lifecycle | — | depend on any other module |
| **tracking** | StudySession, SleepLog, MoodLog, ExerciseLog, Subject | identity | know about scoring, leaderboards, or ML |
| **goals** | Goal, GoalProgress, target evaluation, committed schedule | identity, tracking | write tracking data |
| **social** | Friendship, StudyGroup, Membership, visibility rules | identity | contain scoring logic |
| **gamification** | Achievement, Streak, Challenge, weekly score, leaderboard projection | identity, analytics, social | write to tracking or goals |
| **analytics** | Daily/weekly rollups, insight generation, chart specs | identity, tracking, goals | be the source of truth for raw data |
| **ml** | Feature assembly, training, model registry, Prediction, Recommendation | identity, analytics | be a hard dependency of any core flow |
| **notifications** | Notification queue, preferences, quiet hours, delivery | identity | compute domain state itself |

Anything that *triggers* a notification (a goal deadline, an achievement, a daily insight) publishes a domain event; `notifications` subscribes. No module calls `notifications` directly, and `notifications` never asks another module to compute state for it.

### Inter-module rules

1. **Module A never imports module B's repositories or ORM models.** It calls B's *service* through a protocol, or reads a shared read-model.
2. **Dependencies form a DAG**, exactly as in the table above — `identity` has no outgoing dependencies and everything else eventually reaches it. Any proposed cycle is a design error; resolve it by introducing a domain event, not a back-reference.
3. **Cross-module reactions go through domain events**, not direct calls. `StudySessionCompleted` is published by `tracking`; `gamification` and `goals` subscribe. This is why "finishing a session unlocks an achievement" does not put an achievement import inside the tracking service.

**Event mechanism (D3 simplification):** an in-process synchronous dispatcher, running inside the same transaction as the use case that raised the event. There is **no generic outbox table and no event log** — the only external side effect the system has is sending a Telegram message, and `notifications` already provides a durable, queryable table for exactly that. A general-purpose event-sourcing substrate would be infrastructure built for a requirement that does not yet exist.

---

## 6. Request lifecycle

### 6.1 Telegram update

```
Telegram → Caddy → aiogram Dispatcher
   → middleware: correlation-id
   → middleware: DI request scope (opens DB session + UoW)
   → middleware: user resolution  (telegram_id → User, or onboarding branch)
   → middleware: rate limit (Redis token bucket, per user)
   → middleware: error boundary
   → handler                     [thin: parse update → DTO, call service, render reply]
       → application service     [use case: authorise, orchestrate, commit once]
           → domain entity       [rules: "a session cannot exceed 8h", "streak breaks after a missed committed day"]
           → repository protocol
               → SQLAlchemy repository → Postgres
   ← reply rendered by a presenter/keyboard module (never inline f-strings in handlers)
```

**Handler discipline** — a handler may not: import SQLAlchemy, hold business rules, format numbers with domain meaning, or call more than one service method for a single user action. If a handler needs two service calls, that is a missing use case.

### 6.2 Background job

```
scheduler tick → job adapter  [thin: acquire lock, build DI scope, run use case]
                    → same application service layer
```

Job adapters are adapters exactly like handlers. **A job never contains a SQL query or a business rule.** This is what allows "recompute yesterday's stats" to be triggered from the scheduler, a CLI command, or an admin endpoint with identical behaviour — and it is the mechanism that keeps the deferred queue decision (D5) cheap.

**Every job must be idempotent.** Running it twice produces the same result as running it once. This is a hard rule, not a preference: the MVP scheduler has no retry-with-backoff and no durability across a crash mid-execution, so rerunnability is the entire recovery strategy. It is also what makes migrating to a real queue — which will retry on failure — safe.

---

## 7. Cross-cutting concerns

### 7.1 Transactions & Unit of Work

- One request/update/job = **one DB session = one transaction = one commit**, opened by the DI scope and committed at the *application service* boundary.
- **Repositories never commit and never roll back.** They add, query, and flush. Ownership of the transaction sits one layer up.
- Nested use cases participate in the caller's transaction; they do not open their own.
- Reads that don't mutate still get a session, but the scope commits nothing.

### 7.2 Error handling

A single domain exception hierarchy, translated once at each boundary:

```
SSAError
├── ValidationError        → bot: friendly correction     · api: 422
├── NotFoundError          → bot: "I couldn't find that"  · api: 404
├── PermissionDeniedError  → bot: "That's private"        · api: 403
├── ConflictError          → bot: "You already have..."   · api: 409
├── RateLimitedError       → bot: silent/backoff          · api: 429
└── ExternalServiceError   → bot: "try again shortly"     · api: 502
```

Rules: infrastructure exceptions (`IntegrityError`, `RedisError`, `TelegramAPIError`) are **caught in infrastructure and re-raised as domain errors** — a `sqlalchemy` exception must never reach a handler. Unexpected exceptions are logged with the correlation id, reported to Sentry, and surfaced to the user as a generic apology with that id. No bare `except:`. No exception swallowed without a log line.

### 7.3 Dependency injection

`dishka` — async-native, has first-party integrations for both `aiogram 3` and `FastAPI`, and supports request-scoped providers (which is exactly what the session-per-request rule needs).

Scopes: `APP` (engine, settings, Redis pool, loaded models) → `REQUEST` (session, UoW, repositories, services).

Services receive their dependencies through `__init__` as **protocol types**, never concrete classes. This is what makes the domain unit-testable with zero infrastructure and no mocking library.

### 7.4 Time and timezone

Non-negotiable, and the most common source of silent data corruption in this class of app:

- Every timestamp column is `TIMESTAMPTZ`, always stored in **UTC**.
- `users.timezone` holds an **IANA name** (`Europe/London`), not an offset — offsets break twice a year.
- "Today", "this week", streak boundaries, and daily rollups are computed in the **user's local time**, then persisted as an explicit `local_date` column on rollup rows.
- Application code never calls `datetime.now()`. It depends on a `Clock` protocol, so time can be frozen in tests.

### 7.5 Configuration

`pydantic-settings`, one typed `Settings` object, populated from environment variables. Loaded once at startup and injected — **never read via `os.environ` deep inside a module**. Missing or malformed config fails loudly at boot, not on first use. No secrets in the repository; `.env.example` documents every key with a dummy value.

Scoring weights and thresholds (`05_Scoring_Model.md` §4) live here — configuration, versioned, tunable without a migration.

### 7.6 Observability

- `structlog`, JSON output, every line carrying `correlation_id`, `user_id`, `module`.
- One correlation id generated per update/request, propagated into job execution so a computed statistic can be traced back to the session that triggered it.
- Sentry for exceptions. `/health` (liveness) and `/ready` (DB + Redis reachable) on the API.
- Prometheus metrics deferred (F7) — logs plus Sentry are sufficient at this scale.

### 7.7 Security & privacy

- Telegram identity is verified by the webhook secret token and, for future web clients, Telegram Login widget signature validation. The API issues its own JWTs; Telegram identity is exchanged for a session, never used as a bearer token.
- **Internal identity is decoupled from Telegram (D4):** `users.id` (bigint) is internal and is the target of every foreign key; `users.public_id` (UUID) is the only identifier ever exposed externally, so ids cannot be enumerated; `telegram_accounts` holds the Telegram-specific identity.
- Authorisation lives in the **application layer**, never in handlers. Every read of another user's data passes through a single `VisibilityPolicy` in `social` — friend/group permissions are enforced in one place, not re-derived per feature.
- Data export and account deletion are first-class use cases from day one, because retrofitting erasure onto a schema with scattered denormalised copies is painful.
- Cross-user analytics require a minimum cohort of **k ≥ 20** and exclude all free-text fields (D6), enforced by a single `AnonymisedAggregateQuery` helper that refuses to return under-threshold results.

---

## 8. The ML layer

**Design position: ML is a plug-in, never a dependency of a core flow.** If every model were deleted, the bot must still track, analyse, and motivate. This is the direct consequence of F3.

### Pipeline

```
raw logs ──nightly──▶ daily_user_stats ──▶ feature snapshots
                                                │
                              weekly training ──┤──▶ model registry (versioned artifact + metrics)
                                                │
                              nightly inference ┴──▶ predictions / recommendations tables
                                                         │
                                              bot & api read stored rows
```

**Batch, not online.** Predictions are precomputed and stored with `model_version`, `generated_at`, and a confidence value. The bot performs a primary-key lookup. Rationale: productivity and burnout predictions are daily-granularity phenomena — nothing about them requires sub-second freshness, and this removes model loading, latency, and memory pressure from the user-facing processes entirely.

**Training and inference are the workload that triggers the D5 queue decision.** They are long-running and CPU-bound, which is exactly condition 2 of that trigger. The MVP scheduler is not asked to run them.

**Models consume raw behavioural signals, not the weekly score.** The score is an opinionated, weighted summary; feeding it to a model would inject the product's value judgements into what is supposed to be an empirical prediction.

### Cold start (the part most designs get wrong)

`Recommender` and `ProductivityPredictor` are **domain protocols with two implementations**:

1. `HeuristicRecommender` — transparent rules ("your focus scores are 25% higher after 7h+ sleep"). Needs no data.
2. `ModelRecommender` — trained model, activated **per user** only once that user crosses a data threshold (e.g. ≥30 logged sessions and ≥14 days of history).

Selection happens in a single factory. The bot code is identical either way. This means the product is useful on day one and gets smarter silently — and it gives an honest benchmark to evaluate the models against, which is more valuable for a Data Science portfolio than the models themselves.

### Model management

A `model_registry` table (version, algorithm, trained_at, metrics JSONB, artifact path, `is_active`) plus artifacts on a mounted volume. Promotion to `is_active` requires beating the current champion on a held-out set. **MLflow is deliberately excluded** — it is a service to operate for a benefit a six-column table provides here (F4). Revisit if experiment volume grows.

**Leakage guard:** features are assembled strictly from data available *before* the prediction target's timestamp. A `FeatureBuilder` that takes an explicit `as_of` datetime makes this structural rather than a matter of discipline.

---

## 9. Analytics layer

Three tiers, and the distinction matters:

1. **Raw tracking records** — immutable source of truth, never mutated by analytics.
2. **Rollups** (`daily_user_stats`, `weekly_user_stats`) — computed nightly, idempotent, fully rebuildable from raw. Every user-facing statistic, the weekly score, and every ML feature reads from here.
3. **Cached projections** (Redis) — leaderboards, "top subject this week". Disposable by definition.

Per D3, there is **no generic `user_events` table**. Raw tracking records answer the behavioural questions the product currently has. If a question arises that they cannot answer — onboarding funnel drop-off is the likely first one — an event table is added then, as a new table rather than a redesign. The cost of this choice is stated openly in the decision log: such analysis cannot be performed retroactively for the preceding period.

Chart rendering is CPU-bound and must never run in the bot's event loop. In the MVP, charts are limited to those the scheduler can precompute; on-demand chart rendering ships with the worker, after the D5 decision.

---

## 10. Notifications

Notifications are **post-MVP**, and their arrival is trigger condition 1 for the D5 job-runtime decision. The design is fixed now because it constrains the schema.

**Anti-pattern rejected:** scheduling one queue task per user reminder. It creates unbounded pending tasks, makes cancellation and rescheduling awkward, and loses everything if the broker is wiped.

**Design:** notifications are **rows in Postgres** with `scheduled_for`, `status`, and `payload`. A periodic job claims due rows with:

```sql
SELECT ... FROM notifications
WHERE status = 'pending' AND scheduled_for <= now()
ORDER BY scheduled_for
FOR UPDATE SKIP LOCKED LIMIT 500
```

`SKIP LOCKED` makes the dispatcher safely horizontally scalable. State is queryable, cancellable, and survives a broker wipe. This design is **broker-agnostic** — it works identically under the MVP scheduler, Taskiq, or Celery, which is a large part of why deferring that choice is low-risk.

**Telegram rate limits are a hard constraint,** not an afterthought: ~30 messages/second globally and ~1/second per chat. All outbound Telegram traffic goes through a single `TelegramSender` in infrastructure enforcing a Redis token bucket, with retry-after handling and exponential backoff. Nothing else in the codebase is allowed to call `bot.send_message` directly.

**Wellbeing constraints are enforced here, in code:** per-user quiet hours, a daily notification cap, no streak-loss messaging after 22:00 local, and no rank-change notifications at all (`05_Scoring_Model.md` §6). F5 is an architectural requirement, not a copy decision.

---

## 11. Testing strategy

| Layer | Type | Infrastructure | Target |
|---|---|---|---|
| domain | pure unit | none | ~95% — this is where the rules live |
| application | service tests | real Postgres, rolled back per test | ~85% |
| infrastructure | integration | real Postgres + Redis | key paths |
| bot handlers | adapter tests | mocked Bot, real dispatcher | smoke + regressions |
| api | contract tests | `httpx.AsyncClient` | all endpoints |

Tooling: `pytest`, `pytest-asyncio`, `testcontainers` (or a compose test DB), `factory_boy` for fixtures, `freezegun` (or the injected `Clock`) for time. Each test runs in a transaction that is rolled back — no shared mutable state between tests.

**Two mandatory property-style tests**, because they protect the two guarantees the whole design rests on:

1. **Rollup idempotence** — recomputing any period twice produces an identical row.
2. **Scoring caps hold** — no input, however extreme, produces a score above the cap or lets excess hours raise a total.

Quality gates in CI: `ruff` (lint + format), `mypy --strict` on `domain` and `application`, `import-linter` for the dependency rule, `pytest` with a coverage floor. A PR that breaks the layering fails the build.

---

## 12. Resolved design decisions

The six issues raised against the specification are resolved. Full rationale in `00_Decision_Log.md`.

| # | Issue | Resolution |
|---|---|---|
| D1 | Leaderboards as a base table | **Derived projection.** Redis for current rankings; `leaderboard_snapshots` in Postgres only for history. |
| D2 | Hours-based ranking contradicts wellbeing goal | **Balanced capped scoring** — consistency, goal completion, improvement, focus quality, healthy streaks. Spec in `05_Scoring_Model.md`. |
| D3 | Generic event log | **Not built.** Raw tracking records plus rebuildable rollups. No `user_events`, no `outbox`. Revisit on a concrete requirement. |
| D4 | Telegram ID as primary key | **Internal bigint `users.id`** + external `public_id` UUID + separate `telegram_accounts`. |
| D5 | Celery/async friction | **Deferred.** No broker in the tracking MVP; abstract `JobRunner` and `PeriodicSchedule` interfaces, in-process scheduler, decision on trigger conditions. |
| D6 | "Anonymous analytics" undefined | **k ≥ 20 cohort minimum**, no free-text fields in cross-user datasets, enforced in one query helper. |

---

## 13. What Phase 1 explicitly does not decide

Deferred, with the reason:

- **Background job runtime** — Taskiq vs. Celery vs. other, decided against real job profiles when notifications or ML land (D5).
- Detailed column-level DDL and index definitions → Phase 2, alongside the first Alembic migration. Column *inventories* are fixed (`04` §3, `05` §7).
- Concrete ML feature list and algorithm choice → after real data exists; deciding now would be guessing.
- Scoring component weights → structure is fixed, values are configuration to tune against real data.
- ORM mapper approach — hand-written vs. imperative mapping (ADR-004) → decide around the fifth entity.
- Kubernetes, service mesh, read replicas, sharding → not justified at this scale (F6). The compose topology maps onto them without redesign when it is.
- Web/mobile front-end technology → the REST contract is the commitment; the client is not.

---

## 14. Phase 2 scope

Nothing is blocking. Recommended scope, in build order (`02_Project_Structure.md` §9):

1. `shared/`, `domain/common/`, `Settings`, `Clock`
2. `domain/identity` + `domain/tracking` entities and rules — unit-tested, no database
3. First Alembic migration: users, telegram_accounts, privacy_settings, subjects, study_sessions, sleep/mood/exercise logs
4. Repositories, mappers, integration tests
5. `application` use cases for onboarding and session tracking
6. DI container wiring
7. `apps/bot`: start, onboarding, log a study session
8. `apps/scheduler` + the nightly `rebuild_daily_stats` job, with the idempotence test

Steps 1–8 produce a working end-to-end slice through every layer, including the background path. That slice is what validates this architecture — if any of it feels wrong there, it is cheaper to change then than after eight feature modules exist.
