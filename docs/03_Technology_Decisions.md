# Student Success Assistant — Technology Decisions

**Phase 1 · Architecture & Foundation**
Version 1.1 · incorporates decisions D1–D6 (`00_Decision_Log.md`)

Architecture Decision Records. Each record states what was decided, why, what it costs, and what would make us change our mind.

> **Notation:** `F1–F7` are the architectural forces in `01_Architecture.md` §2; `D1–D6` are the approved decisions in `00_Decision_Log.md`.

---

## Summary table

| # | Decision | Status |
|---|---|---|
| 001 | Monorepo, one image, multiple entrypoints | Accepted |
| 002 | Clean layered architecture with enforced dependency rule | Accepted |
| 003 | PostgreSQL 16 + SQLAlchemy 2.0 async + Alembic | Accepted |
| 004 | Separate ORM models from domain entities | Accepted (revisit ~5th entity) |
| 005 | `dishka` for dependency injection | Accepted |
| 006 | **Background job runtime deferred; abstract interfaces now** | Accepted (D5) |
| 007 | Redis for cache, FSM state, rate limiting, leaderboards | Accepted |
| 008 | aiogram 3 with webhooks in production | Accepted |
| 009 | Batch ML with a table-based model registry | Accepted |
| 010 | Docker Compose on a single VPS | Accepted |
| 011 | `uv` for dependency management | Accepted |
| 012 | `structlog` + Sentry; Prometheus deferred | Accepted |
| 013 | Notification queue in Postgres, broker-agnostic | Accepted |
| 014 | Balanced capped scoring, not hours-based ranking | **Accepted** (D2) |
| 015 | Internal bigint PK + external UUID + separate Telegram identity | **Accepted** (D4) |
| 016 | No generic event log until a concrete requirement exists | **Accepted** (D3) |

---

## ADR-001 — Monorepo, one Docker image, multiple entrypoints

**Context.** SSA needs a Telegram bot, a REST API, and background execution. These could be separate repositories and images, or one image run several ways.

**Decision.** One repository, one installable package, one Docker image. Processes differ only in their start command.

**Consequences.**
- Positive: no version skew between bot and API; refactoring across the boundary is a single commit; one CI pipeline; one image build and pull.
- Positive: a shared domain layer is only practical this way — the alternative is publishing an internal library, which is real overhead for a solo project.
- Positive: adding the future `worker` process (ADR-006) costs a compose entry, not a new build pipeline.
- Negative: the image will eventually contain ML libraries the bot never uses (~300 MB of scipy/xgboost). Acceptable; mitigated by multi-stage builds and layer caching. Split into slim and ML images only if pull times become a real problem.
- Negative: any change redeploys everything. At this cadence, not a concern.

**Revisit if:** a second developer owns one service exclusively, or the image passes ~2 GB.

---

## ADR-002 — Clean layered architecture with an enforced dependency rule

**Context.** The spec demands loose coupling, scalability, and future web/mobile clients. Options ranged from framework-first (aiogram handlers calling SQLAlchemy directly, as most bot tutorials do), through a conventional service layer, to full DDD with aggregates and CQRS.

**Decision.** Four layers — domain, application, infrastructure, apps — with dependencies pointing inward, ports declared as domain protocols, and the rule enforced by `import-linter` in CI.

**Rationale.** Framework-first is the reason most Telegram bots cannot grow a second client: the business logic is inside the handlers. Full DDD is genuine over-engineering for a solo project (F4) — event sourcing and CQRS solve problems (audit reconstruction, extreme read/write asymmetry) that SSA does not have. The middle option keeps the property that actually matters (business logic independent of delivery mechanism) at modest cost.

This ADR is also the enabler for ADR-006: deferring an infrastructure choice is only safe when the layer above it cannot see it.

**Consequences.**
- Positive: domain rules are unit-testable with no database, so the test suite runs in seconds and gets written.
- Positive: adding a web dashboard means adding routers, not restructuring.
- Negative: more files and more indirection than a beginner would write. Every use case touches 3–4 files.
- Negative: the discipline is only as good as the enforcement — hence the CI contract, which is non-negotiable.

**Revisit if:** the indirection demonstrably slows feature work with no corresponding benefit. Merge `application` into `domain` before ever letting `apps` touch the database.

---

## ADR-003 — PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic

**Context.** The data model is highly relational and the project's purpose is analytical.

**Decision.** PostgreSQL 16 as the only persistent store. SQLAlchemy 2.0 with `asyncio` and the typed `Mapped[]` declarative style. Alembic for migrations.

**Rationale.** Postgres covers relational integrity *and* the analytical workload (window functions, `generate_series`, `FILTER`, CTEs) that the rollups need — meaning no separate analytics store for a long time. `TIMESTAMPTZ`, JSONB for the few schemaless fields, partial and expression indexes, `FOR UPDATE SKIP LOCKED` for the notification dispatcher, and **advisory locks for the scheduler singleton** (ADR-006) are all directly load-bearing in this design.

Async SQLAlchemy because both aiogram and FastAPI are async; a sync driver would block the event loop and quietly destroy concurrency.

**Consequences.**
- Positive: one database to operate, back up, and reason about.
- Positive: `Mapped[]` gives real type checking on models.
- Positive: with no broker in the MVP (ADR-006), Postgres is the *only* stateful dependency besides Redis — a very small operational surface.
- Negative: async SQLAlchemy has sharper edges — lazy loading raises instead of silently querying, so relationships must be loaded explicitly (`selectinload`). Arguably a benefit: no accidental N+1.

**Explicitly rejected:** MongoDB (no relational integrity, and the data is relational); SQLite (concurrent writes, no proper types); a separate analytics warehouse (unjustified before ~10⁷ rows).

**Alembic conventions:** a `naming_convention` on the declarative base from the very first migration. Retrofitting constraint names later means hand-editing migrations across every environment.

---

## ADR-004 — ORM models separate from domain entities

**Context.** The alternative — using SQLAlchemy declarative classes directly as domain entities — is far less code and is what most Python projects do.

**Decision.** Keep them separate, with explicit mappers.

**Rationale.** Shared classes would put `sqlalchemy` imports inside `domain`, which makes ADR-002's dependency rule unenforceable — the contract would have to be dropped, and with it the guarantee. It also drags session lifecycle, lazy loading, and identity-map semantics into business logic, which is how "why did calling a property fire 400 queries" happens.

**Consequences.**
- Positive: domain tests need no database at all. This matters most for `gamification/scoring.py`, where the caps must be property-tested against thousands of extreme inputs — impossible at speed if scoring needed a database.
- Positive: schema changes do not automatically become domain changes.
- Negative: mapper code per entity — real, ongoing cost.
- Negative: easy to let the two drift.

**Mitigation and fallback.** If the mapper burden proves excessive in Phase 2, move to SQLAlchemy **imperative mapping** (`registry.map_imperatively`), which maps tables onto plain domain classes with no ORM base class — keeping the domain framework-free *and* eliminating hand-written mappers. Decide after roughly five entities exist and the cost is measurable rather than imagined.

---

## ADR-005 — `dishka` for dependency injection

**Context.** The design requires request-scoped dependencies (one session per update) shared across two frameworks plus a scheduler. Options: manual factories in middleware, `dependency-injector`, `dishka`, or FastAPI's native `Depends`.

**Decision.** `dishka`.

**Rationale.** Async-native, first-party integrations for both aiogram 3 and FastAPI, and explicit scopes (`APP` / `REQUEST`) — exactly the session-per-request requirement. FastAPI's `Depends` is excellent but does not exist in aiogram, so it would leave half the system hand-wired. Manual wiring works at 10 services and becomes a tangle at 50.

It also gives the scheduler a uniform way to open a request-equivalent scope per job run, so job adapters look like handlers rather than like a special case.

**Consequences.**
- Positive: one wiring style across bot, API, scheduler, and CLI; trivial dependency overrides in tests.
- Negative: a third-party dependency in a core position, with a smaller ecosystem than FastAPI's.
- Mitigation: services take protocols in `__init__` and are constructible by hand. If `dishka` were abandoned, replacing it is a container rewrite, not a service rewrite.

---

## ADR-006 — Background job runtime deferred; abstract interfaces now *(D5)*

**Context.** The original plan was Celery + Redis, which created real friction: Celery is synchronous, the data layer is async (ADR-003). The workarounds were duplicating the repository layer in sync form, bridging with `asyncio.run()`, or switching to a natively async library. But the deeper observation is that **the tracking MVP has almost no background work** — one nightly rollup, SQL-bound, a few seconds long. Choosing a distributed task queue to run it would be selecting infrastructure ahead of the requirement that justifies it.

**Decision.** No broker and no queue library in the tracking MVP. Background execution is defined behind domain protocols — `JobRunner`, `PeriodicSchedule`, `JobContext` — with an `InProcessJobRunner` and a small `scheduler` process (asyncio loop, Postgres advisory lock for single-instance safety). The queue library is chosen when the workload requires one.

**Trigger conditions** — adopt a real queue when any becomes true:

1. Rate-limited fan-out delivery is needed (scheduled notifications).
2. A job routinely exceeds ~60 seconds (ML training, batch chart rendering).
3. Retries with backoff and a dead-letter path become a requirement, not a nicety.
4. Job execution must scale beyond one host.

Conditions 1 and 2 will both arrive with the notifications and ML phases. The decision is deferred by roughly one phase, not indefinitely.

**Rationale.** The friction that made this hard to decide — sync Celery against an async codebase — is an artefact of comparing options in the abstract. With real job profiles in hand, the comparison becomes concrete: if every job is async and I/O-bound, Taskiq wins on fit; if operational maturity and tooling dominate, Celery wins. Guessing now, and possibly discovering the `asyncio.run` bridge is unpleasant after twenty tasks are written, is strictly worse than deciding with evidence.

**What makes the deferral safe rather than a postponed problem:**

- Jobs are application use cases. The runner decides *where and when*, never *what*. No logic lives in a job adapter.
- `application` is forbidden from importing any job-runtime library, enforced by an `import-linter` contract. The deferral cannot rot through drift.
- **Every job is idempotent.** Rerunnability is the MVP's entire recovery strategy, and it is also what makes a future queue's automatic retries safe.
- The notification queue (ADR-013) is broker-agnostic by design, so the largest future consumer of background execution does not depend on the choice.

**Consequences.**
- Positive: one fewer moving part, one fewer container, one fewer failure mode during the phase where the priority is getting the data model right.
- Positive: zero sync/async bridging code written speculatively.
- Positive: the eventual decision is made against measurements.
- Negative: no retry-with-backoff, no durability across a crash mid-job, no distributed execution. Acceptable: the sole MVP job is idempotent and reruns on the next tick.
- Negative: the scheduler must be a singleton. Enforced by advisory lock, not by documentation.
- Negative: some throwaway code (the in-process runner, ~150 lines). Cheap, and it remains useful for local development after the migration.

**Revisit at:** the first trigger condition. Candidates: **Taskiq** (async-native, no bridging, matches the codebase) vs. **Celery** (mature ecosystem, Flower, transferable operational knowledge).

---

## ADR-007 — Redis for cache, FSM storage, rate limiting, and leaderboards

**Context.** Several needs (cache, bot conversation state, rate limiting, leaderboard rankings) could each have a dedicated technology. With ADR-006, Redis is no longer needed as a broker.

**Decision.** One Redis instance, logically separated by key prefix and database index.

**Rationale.** Each of these is a natural Redis workload, and operating one more service is real cost (F4). Sorted sets fit leaderboards exactly (D1); `INCR` + `EXPIRE` fits token buckets; aiogram ships a Redis FSM storage backend.

**Could Redis be dropped from the MVP too?** Considered, and rejected. In-memory FSM state would be lost on every deploy, dropping users mid-conversation — a visible UX regression for a bot whose core flow is a multi-step dialogue. Redis is one container with no schema and no migrations; the operational cost is close to zero and the benefit is immediate.

**Consequences.**
- Positive: minimal operational surface; no broker to run.
- Negative: single point of failure for several concerns; a flush loses in-progress conversations. Acceptable because **no durable state lives only in Redis** — leaderboards rebuild from `weekly_user_stats`, notifications live in Postgres (ADR-013), and a lost FSM state costs the user one restarted dialogue.
- Configuration: `maxmemory-policy allkeys-lru` on the cache index; AOF enabled as cheap insurance.

---

## ADR-008 — aiogram 3, webhooks in production, polling locally

**Decision.** Webhooks in production behind Caddy with a secret token; long polling in local development.

**Rationale.** Webhooks scale better, cut latency, and avoid a constantly open outbound connection. Polling locally avoids needing a public URL or a tunnel for everyday work. The switch is a config flag; nothing above the delivery layer knows the difference.

**Security:** validate `X-Telegram-Bot-Api-Secret-Token` on every webhook request. Without it, the endpoint accepts forged updates from anyone who finds the URL.

**Consequences.** Positive: production-appropriate performance, local ergonomics preserved. Negative: two code paths in `apps/bot/main.py` (about 20 lines) and a TLS requirement in production, which Caddy handles automatically.

---

## ADR-009 — Batch ML with a table-based model registry

**Decision.** Nightly batch inference writing to a `predictions` table; a `model_registry` table plus artifacts on a mounted volume; no MLflow, no separate ML service.

**Rationale.** These predictions — tomorrow's likely productivity, burnout risk, recommended study window — are daily-granularity by nature. Nothing needs sub-second freshness. Batch removes model memory, load time, and inference latency from every user-facing process, and makes prediction quality auditable after the fact because every prediction is stored with its model version.

A separate ML service would look impressive on a portfolio but adds a deployment, a network hop, and a failure mode to solve a problem that does not exist at this scale. In-process inference couples model memory and versioning to the web process and makes rollback a redeploy. MLflow is a service to run for what a six-column table provides here.

**Models consume raw behavioural signals, not the weekly score** (ADR-014). The score encodes deliberate product value judgements — caps, gates, weights — and feeding it to a model would contaminate an empirical prediction with normative choices.

**Consequences.**
- Positive: user-facing latency is a primary-key lookup.
- Positive: model rollback is `UPDATE model_registry SET is_active = ...` — no deployment.
- Positive: stored predictions with versions give free offline evaluation data.
- Negative: predictions can be up to 24h stale. For these targets, immaterial.
- Negative: no true real-time personalisation. Explicitly out of scope.

**Cold start:** `HeuristicRecommender` implements the same protocol and is used until a user has sufficient history. The product is useful from day one and the heuristics double as the baseline the models must beat.

**Dependency note:** training is trigger condition 2 for ADR-006. ML and the queue decision arrive together.

---

## ADR-010 — Docker Compose on a single VPS

**Decision.** A single VPS (4 vCPU / 8 GB to start) running Docker Compose. MVP services: `caddy`, `postgres`, `redis`, `migrate`, `bot`, `api`, `scheduler`.

**Rationale.** Thousands of users on this workload is a small load — a well-indexed Postgres on modest hardware handles it with room to spare. Compose gives full control, predictable cost (~$20–40/month), no vendor constraints on long-running processes, and an environment that matches local development almost exactly.

PaaS is tempting for the reduced ops work but constrains background processes and persistent volumes, and gets expensive with several services. Kubernetes at this scale is pure overhead — and reviewers of a portfolio read unnecessary Kubernetes as a judgement signal, not a skill signal.

**Consequences.**
- Positive: cheap, portable, dev/prod parity, no vendor lock-in.
- Positive: the Compose topology maps one-to-one onto Kubernetes manifests if scale ever demands it.
- Negative: you own backups, TLS renewal, OS patching, and monitoring. Mitigated: Caddy automates TLS, a nightly `pg_dump` to off-site storage is cron plus ten lines, unattended-upgrades handles patching.
- Negative: single point of failure; no zero-downtime deploys initially. Acceptable — a study bot can be down for 30 seconds.

**Scaling path, in order:** vertical resize → separate database host → read replica for analytics → queue runtime and multiple workers (ADR-006) → orchestrator.

---

## ADR-011 — `uv` for dependency management

**Decision.** `uv` with `pyproject.toml` and a committed `uv.lock`; dependency groups for `dev`, `ml`, `api`, `bot`.

**Rationale.** Order-of-magnitude faster than Poetry or pip-tools, which matters most in Docker builds and CI. Standards-based (PEP 621), so migrating away is trivial. Lockfile guarantees reproducible builds. Dependency groups mean the MVP image need not carry the ML stack at all until ML ships.

**Python 3.12** — mature typing, `asyncio.TaskGroup` (used directly by the scheduler loop), meaningful performance gains, wide library support. Not 3.13: parts of the scientific stack still lag.

---

## ADR-012 — `structlog` + Sentry; Prometheus deferred

**Decision.** `structlog` with JSON output and correlation ids; Sentry for exception tracking; no metrics stack in Phase 1.

**Rationale.** With a few thousand users, "what broke and for whom" is answered by structured logs plus Sentry. A Prometheus/Grafana stack is two more services to run and tune for dashboards nobody will watch daily at this stage. The correlation id — propagated from Telegram update through job execution to the delivered notification — is the highest-value observability investment and costs almost nothing.

**One metric is worth tracking manually from day one:** scheduler job duration and outcome, logged per run. It is the evidence that will decide ADR-006 trigger condition 2.

**Revisit at:** the first performance problem that logs cannot explain.

---

## ADR-013 — Notification queue in Postgres, broker-agnostic

**Decision.** Notifications are rows in a Postgres table with `scheduled_for` and `status`. A periodic job claims due rows with `FOR UPDATE SKIP LOCKED` and dispatches them.

**Rationale.** The obvious alternative — one queued task per reminder — creates an unbounded set of pending tasks, makes cancellation and rescheduling awkward (a user changing quiet hours would need every future task revoked), gives no queryable state, and loses everything if the broker is wiped. The database-queue pattern is durable, inspectable, cancellable, and horizontally scalable via `SKIP LOCKED`.

**It is also broker-agnostic**, which is what lets ADR-006 defer the queue choice without the notifications design being hostage to it. The same table and the same dispatch query work under the in-process scheduler, Taskiq, or Celery.

**Consequences.**
- Positive: full history and analytics on notifications — "do reminders actually change behaviour?" is a question this project should be able to answer.
- Positive: preference changes take effect immediately, because nothing was pre-scheduled in a broker.
- Negative: up to 60 seconds of scheduling latency. Irrelevant for study reminders.
- Negative: a polling query every minute. Trivially cheap with a partial index on `(scheduled_for) WHERE status = 'pending'`.

---

## ADR-014 — Balanced capped scoring, not hours-based ranking *(D2 — accepted)*

**Context.** The specification listed leaderboards. The Vision explicitly rejects "unhealthy competition" and "rewarding excessive studying". A leaderboard ranked on total study hours rewards precisely the behaviour the project sets out to discourage — and undermines burnout detection, which would be flagging risk in the same users the leaderboard publicly celebrates.

**Decision.** Rank on a composite 0–100 weekly score built from consistency (30), goal completion (25), focus quality (20), improvement (15), and healthy streaks (10), with per-day caps, an anti-gaming difficulty factor on goals, and a wellbeing gate that freezes rather than penalises. Leaderboards are opt-in, scoped to friends and groups only, and are computed projections rather than stored state (D1). Full specification in `05_Scoring_Model.md`.

**Rationale.** Preserves the social motivation the product wants while removing the incentive to overwork. Makes the metric fairer — a student with 3 hours a day available is not structurally locked out of the top. And it makes the product coherent: every feature points the same direction.

**Consequences.**
- Positive: gamification and wellbeing goals stop contradicting each other.
- Positive: component scores are persisted, so the score is explainable — which turns a leaderboard into a behavioural insight rather than a vanity number.
- Positive: caps are pure functions, so "no amount of overwork raises a score" is a property test, not an aspiration.
- Negative: less immediately legible than "hours studied"; needs an in-bot explanation.
- Negative: more computation and more rollup columns than a simple sum.
- Negative: self-reported focus is inflatable. Weighted below consistency and goal completion; a behavioural proxy can be blended in later.

**Weights are configuration**, versioned via `scoring_version` on every stored score row, so a reweighting does not invalidate history.

---

## ADR-015 — Internal bigint PK, external UUID, separate Telegram identity *(D4 — accepted)*

**Decision.** `users.id BIGINT GENERATED ALWAYS AS IDENTITY` is the internal primary key and the target of every foreign key. `users.public_id UUID` is the only identifier exposed externally. Telegram identity lives in `telegram_accounts` (1:1, `telegram_id BIGINT UNIQUE`).

**Rationale.** Using `telegram_id` as the primary key would bake the first client into every foreign key in the system, defeating the future web/mobile goal (F1).

**Why bigint internally rather than a UUID primary key:** bigint keys are half the width, keep index locality on the high-volume `study_sessions` table, and avoid the random-insert page splits that UUIDv4 primary keys cause. The property that actually matters externally — ids that cannot be enumerated or counted by an outsider — is delivered by `public_id` without paying the storage and locality cost on every index in the database. (UUIDv7 would largely solve the locality problem, but adds a dependency and still doubles key width for no benefit in a single-database system.)

**Consequences.**
- Positive: a second login provider is a new table, not a migration of every foreign key.
- Positive: no enumerable ids in API paths, exports, or deep links.
- Negative: two identifiers per user, and a rule to remember about which crosses the boundary. Enforced by DTOs — `public_id` is the only one present in any API schema or export.

---

## ADR-016 — No generic event log until a concrete requirement exists *(D3 — accepted)*

**Decision.** Raw tracking records are the source of truth; `daily_user_stats` and `weekly_user_stats` are rebuildable aggregates. **No `user_events` table and no `outbox` table.**

**Rationale.** A generic event log is infrastructure for questions not yet asked. The behavioural questions the product currently has are answered by the tracking records themselves. An `outbox` is likewise unnecessary: the only external side effect the system has is sending a Telegram message, and the `notifications` table (ADR-013) already provides a durable, queryable queue for exactly that — a second generic mechanism would be redundant.

**Consequences.**
- Positive: one fewer table, one fewer retention policy, no JSONB property-bag to police, no second durable-delivery mechanism to keep consistent with the first.
- Negative, stated openly: **funnel and retention analysis cannot be performed retroactively** for the period before such a table exists. If onboarding drop-off becomes a question in month six, the answer starts accumulating from month six.

**Revisit when:** a named question exists that raw tracking data cannot answer — onboarding funnel drop-off is the likely first. At that point it is a new table and a new job, not a redesign; nothing in this architecture blocks it.

---

## Stack summary

| Layer | Choice | Phase |
|---|---|---|
| Language | Python 3.12 | MVP |
| Bot framework | aiogram 3.x | MVP |
| API framework | FastAPI | MVP |
| ORM | SQLAlchemy 2.0 (async) | MVP |
| Migrations | Alembic | MVP |
| Database | PostgreSQL 16 | MVP |
| Cache / FSM / rate limit | Redis 7 | MVP |
| Background execution | In-process scheduler (asyncio + advisory lock) | MVP |
| Task queue | **Deferred** — Taskiq or Celery | Post-MVP (ADR-006) |
| DI | dishka | MVP |
| Validation / settings | Pydantic + pydantic-settings 2.x | MVP |
| Logging | structlog | MVP |
| Errors | Sentry SDK | MVP |
| Testing | pytest, pytest-asyncio, testcontainers, factory_boy, hypothesis | MVP |
| Lint / format | ruff | MVP |
| Types | mypy (strict on domain + application) | MVP |
| Layering | import-linter | MVP |
| Packaging | uv | MVP |
| Containers | Docker + Compose | MVP |
| Reverse proxy / TLS | Caddy 2.x | MVP |
| CI/CD | GitHub Actions | MVP |
| Data | pandas, NumPy | Analytics phase |
| ML | scikit-learn, XGBoost, LightGBM | ML phase |
| Charts | Matplotlib, Plotly | Analytics phase |
| Metrics | **Deferred** — Prometheus/Grafana | If needed (ADR-012) |

`hypothesis` is included in the MVP set specifically for the scoring property tests (ADR-014) — the caps are a correctness guarantee, and example-based tests cannot establish one.

---

## Open decisions

Neither blocks Phase 2.

| Item | Decide by | Impact |
|---|---|---|
| ORM mapper approach — hand-written vs. imperative (ADR-004) | ~5th entity | No schema impact |
| Job runtime — Taskiq vs. Celery (ADR-006) | First trigger condition | One adapter package |
| Scoring weights (`05_Scoring_Model.md` §4) | First real data | Configuration only |
