# Student Success Assistant — Phase 1 Decision Log

Resolutions for the six design issues raised against the specification. All documents in this set have been revised to match.

> **Notation used across the document set:** `D1–D6` are these decisions. `F1–F7` are the architectural forces in `01_Architecture.md` §2. `ADR-001`–`ADR-016` are the technology decisions in `03_Technology_Decisions.md`.

**Document set**

| File | Contents |
|---|---|
| `00_Decision_Log.md` | This document — D1–D6 and their downstream impact |
| `01_Architecture.md` | Layers, modules, runtime topology, cross-cutting concerns |
| `02_Project_Structure.md` | Folder tree, import contracts, build order |
| `03_Technology_Decisions.md` | ADR-001 – ADR-016, stack summary |
| `04_Data_Strategy_and_Deployment.md` | ER-level schema, migration policy, deployment |
| `05_Scoring_Model.md` | The D2 scoring specification |

---

## D1 — Leaderboards are derived projections *(was I1 — approved)*

**Decision.** Current rankings live in Redis sorted sets, rebuilt on a schedule from `weekly_user_stats`. PostgreSQL stores `leaderboard_snapshots` only where historical rankings are a product requirement ("you were #3 last week").

**Impact.** No `leaderboards` base table. Redis is authoritative for nothing — a flush costs a rebuild. Removes write amplification on the study-session path.

---

## D2 — Balanced, capped scoring *(was I2 — approved)*

**Decision.** No ranking on raw study hours. Score combines consistency, goal completion, improvement, focus quality, and healthy streaks, with per-day caps and a wellbeing gate.

**Impact.** Substantial — this defines the columns of `daily_user_stats` and `weekly_user_stats`. Full specification in `05_Scoring_Model.md`. Component scores are persisted alongside the total so the bot can explain *why* a score moved, which serves the "understand your behaviour" goal far better than an opaque number.

---

## D3 — Rollups yes, generic event log no *(was I3 — approved with simplification)*

**Decision.** Raw tracking records remain the source of truth. `daily_user_stats` and `weekly_user_stats` are rebuildable aggregates. **No `user_events` table** until a concrete analytics or audit requirement exists.

**Impact.** One fewer table, one fewer retention policy, no JSONB property-bag to police. The `outbox` table is dropped for the same reason — `notifications` already provides a durable queue for the only external side effect the system has.

**Accepted cost, stated plainly:** behavioural funnel and retention analysis cannot be performed retroactively for the period before such a table exists. The trigger to introduce it: a named question that raw tracking data cannot answer (e.g. "where do users abandon onboarding?"). At that point it is a new table, not a redesign — nothing in this architecture blocks it.

---

## D4 — Internal identity, Telegram stored separately *(was I4 — approved)*

**Decision.** `users.id BIGINT GENERATED ALWAYS AS IDENTITY` is the internal primary key and the target of every foreign key. `users.public_id UUID` is the only identifier exposed externally (API paths, export files, deep links). Telegram identity lives in a separate `telegram_accounts` table.

**Rationale for bigint-plus-UUID rather than a UUID primary key:** bigint keys are half the width, keep index locality on the high-volume `study_sessions` table, and avoid random-insert page splits. A separate `public_id` gets the property that actually matters externally — ids that cannot be enumerated or counted by an outsider. Adding a second login provider later is a new row in a new table, not a migration of every foreign key.

---

## D5 — Background job runtime deferred *(was I5 — decision deferred)*

**Decision.** **No Celery, no broker, in the tracking MVP.** Background work is defined behind abstract interfaces now; the implementation is chosen when scheduled notifications and heavy analytics are actually built.

**MVP implementation.** An `InProcessJobRunner` and a small `scheduler` process in the same image, running an asyncio loop guarded by a Postgres advisory lock. The only periodic job the tracking MVP needs is the nightly rollup, which is SQL-bound and takes seconds.

**Interfaces fixed now** (in `domain`/`application`, so the choice stays cheap):

- `JobRunner.enqueue(spec) -> JobId` — fire-and-forget
- `PeriodicSchedule` — declarative registration of recurring jobs
- `JobContext` — correlation id, attempt number, deadline

**The rule that makes this deferral safe:** *a job is an application use case; the runner only decides where and when it executes.* No job contains logic that lives nowhere else. Swapping the runner touches one adapter package.

**Trigger to decide** — adopt a real queue when any of these becomes true:

1. Rate-limited fan-out delivery is needed (scheduled notifications).
2. A job routinely exceeds ~60 seconds (model training, batch chart rendering).
3. Retries with backoff and a dead-letter path become a requirement rather than a nicety.
4. Job execution must scale beyond one host.

**Candidates at that point:** Taskiq (async-native, matches the codebase, no `asyncio.run` bridging) versus Celery (mature ecosystem, Flower, transferable operational knowledge). Evaluated with real job profiles rather than in the abstract — which is precisely why deferring was the right call.

**Consequence to accept:** the MVP has no retry-with-backoff and no job durability across a crash mid-execution. Acceptable because the only job is idempotent and rerunnable. **Every job written before the queue decision must be idempotent** — this is now a hard rule, not a preference, because it is what keeps the migration path open.

---

## D6 — Cohort thresholds for shared analytics *(was I6 — approved)*

**Decision.** Any aggregate spanning more than one user requires a minimum cohort of **k ≥ 20** contributing users, and excludes all free-text fields (subject names, session notes, goal titles).

**Enforcement.** A single `AnonymisedAggregateQuery` helper in `analytics` that refuses to return a result below threshold. Group statistics for groups smaller than 20 show individual opt-in data only — never a "group average" that two members can subtract to recover a third's numbers.

---

## Revised open items for Phase 2

Everything blocking is now resolved. Two decisions remain deliberately open, neither blocking:

| Item | Decide by | Notes |
|---|---|---|
| ORM mapper approach — hand-written vs. imperative mapping (ADR-004) | ~5th entity | Does not affect schema |
| Scoring component weights (`05_Scoring_Model.md` §4) | First real data | Configuration, not structure — tune, don't redesign |

**Phase 2 is unblocked.** Recommended scope: domain entities and rules for `identity` + `tracking`, the first Alembic migration, repositories, and the nightly rollup job — the vertical slice described in `02_Project_Structure.md` §9.
