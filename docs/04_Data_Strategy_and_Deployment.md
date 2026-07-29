# Student Success Assistant — Database Strategy & Deployment

**Phase 1 · Architecture & Foundation**
Version 1.1 · incorporates decisions D1–D6 (`00_Decision_Log.md`)
ER-level design and operational approach. Column-level DDL and indexes land in Phase 2 with the first migration.

---

# Part I — Database Strategy

## 1. Guiding principles

1. **Raw tracking records are immutable.** Nothing derived ever overwrites a source record. Every aggregate is rebuildable from raw data — which means an analytics or scoring bug is a rerun, not permanent data loss.
2. **Three tiers, clearly separated:** source of truth → rollups → disposable caches. A table belongs to exactly one tier.
3. **Time is UTC in the database, local in the domain.** All timestamps `TIMESTAMPTZ`; every rollup row carries an explicit `local_date`.
4. **Internal keys are bigint; external identifiers are UUIDs** (D4).
5. **Constraints in the database, not only in Python.** The database is the last line of defence and the only one that survives a bad migration script or a manual fix.
6. **Every table is designed with deletion in mind** — an account erasure request must be executable in one transaction.
7. **Build the table when the question exists** (D3). No speculative event logs, no generic property bags.

---

## 2. Entity map

```
                            ┌──────────────┐
                            │    users     │  id BIGINT (internal)
                            │              │  public_id UUID (external)
                            └──────┬───────┘
        ┌──────────────┬───────────┼────────────┬──────────────┐
        ▼              ▼           ▼            ▼              ▼
┌───────────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────────┐
│telegram_      │ │privacy_  │ │subjects│ │  goals   │ │notification_ │
│accounts (1:1) │ │settings  │ │        │ │ +schedule│ │preferences   │
└───────────────┘ └──────────┘ └───┬────┘ └────┬─────┘ └──────────────┘
                                   │           │
                    ┌──────────────┴───┐       ▼
                    ▼                  │  ┌──────────────┐
            ┌────────────────┐         │  │goal_schedule │
            │ study_sessions │─────────┘  └──────────────┘
            └────────┬───────┘
                     │
   ┌─────────────────┼────────────────┐
   ▼                 ▼                ▼
┌──────────┐  ┌───────────┐   ┌──────────────┐
│sleep_logs│  │ mood_logs │   │exercise_logs │
└─────┬────┘  └─────┬─────┘   └──────┬───────┘
      └─────────────┴────────┬───────┘
                             ▼  (nightly, idempotent)
                  ┌──────────────────────┐
                  │  daily_user_stats    │  ← the analytical spine
                  └──────────┬───────────┘
                             ▼  (weekly, idempotent)
                  ┌──────────────────────┐
                  │  weekly_user_stats   │  ← component scores + total
                  └──────────┬───────────┘
                             ├──────────▶ Redis sorted sets (live rankings)
                             ├──────────▶ leaderboard_snapshots (history)
                             └──────────▶ ml_feature_snapshots ──▶ predictions
                                                                   recommendations

  SOCIAL                              GAMIFICATION
  friendships (user↔user)             achievements (catalogue)
  study_groups                        user_achievements (earned)
  group_memberships                   streaks
                                      challenges / challenge_participants

  SYSTEM
  notifications (queue)   model_registry   alembic_version
```

No `user_events` table and no `outbox` table (D3 / ADR-016).

---

## 3. Table inventory by tier

### Tier 1 — Source of truth

| Table | Notes | Phase |
|---|---|---|
| `users` | `id BIGINT IDENTITY` (internal PK), `public_id UUID UNIQUE` (external), `timezone` (IANA), locale, status, `created_at`, `deleted_at`. **No Telegram fields.** | MVP |
| `telegram_accounts` | 1:1 with users. `telegram_id BIGINT UNIQUE NOT NULL`, username, language code. Isolating the first client here is what makes future login providers additive (D4). | MVP |
| `privacy_settings` | 1:1. Profile visibility, stats visibility, `leaderboard_opt_in` (default **false**), research-data consent. | MVP |
| `subjects` | Per-user. Name, colour, archived flag. Unique on `(user_id, lower(name))`. | MVP |
| `study_sessions` | **Highest-volume table.** user, subject, `started_at`, `ended_at`, planned duration, self-reported focus (1–5), session type, interruption count, `was_completed`, notes. | MVP |
| `sleep_logs` | One per user per local date. Bed time, wake time, duration, quality. | MVP |
| `mood_logs` | Ordinal mood, energy, stress, optional note. Timestamped; several per day allowed. | MVP |
| `exercise_logs` | Type, duration, intensity. | MVP |
| `goals` | Target metric, target value, period, date range, status, `created_at` (enforces the 24h anti-gaming rule). | MVP |
| `goal_schedule_days` | The user's **committed days** — the denominator of the consistency component (`05` §3.1). One row per weekday. | MVP |
| `goal_progress` | Per-period achieved value, retained for history. **Deferred out of the first slice** — derivable from `daily_user_stats` until the goals module proper is built (`06` §1.1). | Goals phase |
| `friendships` | Directed rows with status (`pending`/`accepted`/`blocked`). | Social phase |
| `study_groups`, `group_memberships` | Group, role, join date, visibility level. | Social phase |
| `achievements` | Static catalogue, seeded via data migration. | Gamification |
| `user_achievements` | Earned records with `earned_at`. Unique on `(user_id, achievement_id)`. | Gamification |
| `streaks` | Current and longest streak per type, `last_active_local_date`, `grace_days_used_this_month`. | Gamification |
| `challenges`, `challenge_participants` | Time-boxed group challenges. | Gamification |
| `notifications` | The durable queue (ADR-013). | Notifications |
| `notification_preferences` | Quiet hours, per-category toggles, daily cap. | Notifications |
| `model_registry` | Version, algorithm, `trained_at`, metrics JSONB, artifact path, `is_active`. | ML phase |

### Tier 2 — Rollups (idempotent, fully rebuildable)

| Table | Grain | Purpose | Phase |
|---|---|---|---|
| `daily_user_stats` | `(user_id, local_date)` | The analytical spine. Full column list in `06_Database_Schema.md` §12 — both `study_seconds_raw` (truth, for the user and for ML) and `study_seconds_capped` (scoring input) are stored, because they answer different questions and conflating them is how a cap silently becomes a lie in someone's own analytics. | MVP |
| `weekly_user_stats` | `(user_id, iso_year, iso_week)` | The five component scores, their inputs, `total_score`, `wellbeing_gate_applied`, `scoring_version`. | Gamification |
| `ml_feature_snapshots` | `(user_id, as_of_date)` | Frozen feature vector with an explicit `as_of` — makes temporal leakage structurally difficult rather than a matter of care. | ML phase |
| `predictions` | `(user_id, target_date, prediction_type)` | Value, confidence, `model_version`, `generated_at`. | ML phase |
| `recommendations` | `(user_id, generated_at)` | Type, payload JSONB, source (`heuristic` / `model:<version>`), user response. Storing the source is what allows an honest answer to "do the models actually beat the rules?" | ML phase |
| `leaderboard_snapshots` | `(scope, scope_id, iso_year, iso_week)` | Historical standings only (D1). | Gamification |

### Tier 3 — Cache (Redis, disposable by definition)

Live leaderboard sorted sets (D1), rendered chart references, hot profile lookups, rate-limit buckets, aiogram FSM state. **Nothing here is a source of truth.** Losing all of it costs a rebuild, never data.

---

## 4. Key design decisions

**Identity (D4).** `users.id BIGINT GENERATED ALWAYS AS IDENTITY` is the internal primary key and the target of every foreign key. `users.public_id UUID` is the only identifier that appears in API paths, export files, or deep links. Rationale for the split — index width and locality on the high-volume tables, without exposing enumerable ids — is in ADR-015. Telegram, email, and any future provider identity live in their own tables, never in a foreign key.

**All timestamps `TIMESTAMPTZ`, stored UTC.** `users.timezone` is an IANA name. Any table representing a *user's day* (rollups, sleep logs, streaks) additionally stores an explicit `local_date DATE`, because "which day was that session" is a domain question that cannot be re-derived cheaply or correctly after a timezone change.

**Enums as `VARCHAR` + `CHECK`, not native Postgres enums.** Native enums require a migration to add a value and cannot drop one at all. A check constraint is one `ALTER`. Python `Enum` classes provide type safety; the constraint provides integrity.

**JSONB is confined to genuinely schemaless payloads** — `notifications.payload`, `model_registry.metrics`, `recommendations.payload`. Core domain attributes are always real columns. Per D3 there is no property-bag table at all, which removes the main way JSONB tends to spread.

**Both raw and capped study minutes are stored** on `daily_user_stats`. The cap is a scoring decision, not a data decision; the user's own analytics and every ML feature use the raw value.

**Soft delete vs. erasure.** `deleted_at` for user-hideable content (a mistyped session). Account deletion is genuine erasure: personal data removed or irreversibly anonymised in one transaction, with only anonymised aggregate rows optionally retained under explicit prior consent. "Set a flag and keep everything" does not satisfy a deletion request.

**Alembic naming convention on the declarative base from migration #1.** Without it, autogenerated constraint names differ per environment and later migrations break in ways that are painful to unpick.

**Money-shot indexes** (specified fully in Phase 2, but the shape is known):

- `study_sessions (user_id, started_at DESC)` — the dominant access pattern.
- `daily_user_stats (user_id, local_date DESC)` — every chart, stat, and rollup query.
- `weekly_user_stats (user_id, iso_year, iso_week)` — scoring and leaderboard rebuilds.
- `telegram_accounts (telegram_id)` unique — hit on literally every update.
- `users (public_id)` unique — every external lookup.
- `notifications (scheduled_for) WHERE status = 'pending'` — partial index for the dispatcher.
- `friendships (user_id, status)` and its mirror.

**Partitioning: designed for, not yet applied.** `study_sessions` is the only table that will reach tens of millions of rows, and it is naturally range-partitionable by month on `started_at`. Phase 2 keeps it unpartitioned — a few hundred thousand rows needs no partitioning, and partitioning adds real query and migration complexity — but avoids anything that would block it: no unique constraints excluding the partition key, no foreign keys pointing *into* it. Dropping `user_events` (D3) removes the other candidate entirely.

**Concurrency.** Streak updates and challenge scoring are read-modify-write and will race under concurrent sessions. Handled with row-level locking (`SELECT ... FOR UPDATE`) on the streak row inside the use-case transaction, never with optimistic retry loops in Python.

**Scheduler singleton.** The `scheduler` process holds a Postgres **advisory lock** for the duration of each job run (ADR-006). Two scheduler instances cannot double-run a rollup, and the guarantee lives in the database rather than in a deployment convention that someone will eventually break.

---

## 5. Migration policy

- Every schema change is an Alembic migration. No manual DDL in any environment, ever.
- One migration per logical change; both `upgrade()` and `downgrade()` implemented and **tested** in CI.
- Migrations run as a **one-shot job before the app containers start**, never in an application entrypoint — otherwise every container races to migrate the same database.
- Destructive changes are split across two deploys: add the new column and dual-write, backfill, switch reads, drop in a later release. Never a rename in a single step.
- Index creation on large tables uses `CREATE INDEX CONCURRENTLY` in a migration marked non-transactional.
- Seed data (achievement catalogue, subject presets) ships as data migrations so environments are reproducible from an empty database.

---

## 6. Privacy implementation

The Vision's privacy requirements are schema-level obligations, not settings screens:

| Requirement | Mechanism |
|---|---|
| Data export | `ExportUserData` use case → background job → JSON + CSV bundle covering every table containing `user_id`, keyed by `public_id`. A registry of exportable tables lives in code, with a test asserting it covers every user-scoped table — so a new table cannot be silently omitted. |
| Account deletion | `DeleteAccount` use case → single transaction, cascade-delete owned rows, anonymise rows that must survive for others' integrity (group challenge history), then purge Redis keys and cached charts. |
| Privacy settings | Enforced in `social.VisibilityPolicy` — **one code path**, applied to every cross-user read. Never re-implemented per feature. |
| Friend/group permissions | Membership plus per-group visibility level, checked by the same policy. |
| Leaderboard participation | `leaderboard_opt_in`, default **false**. Own score always visible to self. |
| Anonymous analytics (D6) | `AnonymisedAggregateQuery` refuses any cross-user result with fewer than **k = 20** contributing users, and excludes all free-text fields (subject names, session notes, goal titles). Groups below 20 members show opt-in individual data only — never a "group average" that two members can subtract to recover a third's numbers. |

**Retention:** raw tracking records are kept while the account is active — they are the product. Deleted accounts leave nothing behind within 30 days, including in backups older than the retention window. With no event log (D3), there is no high-volume telemetry stream needing its own downsampling policy.

---

# Part II — Deployment

## 7. Topology

Single VPS (start at 4 vCPU / 8 GB), Docker Compose, one image (ADR-010, ADR-001).

### 7.1 Tracking MVP

| Service | Image | Command | Notes |
|---|---|---|---|
| `caddy` | caddy:2 | — | TLS (automatic), reverse proxy, webhook + API routing |
| `postgres` | postgres:16 | — | Named volume, healthcheck, tuned `shared_buffers` / `work_mem` |
| `redis` | redis:7 | — | AOF on, `allkeys-lru` on the cache index |
| `migrate` | `ssa` | `alembic upgrade head` | One-shot; app services depend on its successful completion |
| `bot` | `ssa` | `python -m ssa.apps.bot` | Webhook mode |
| `api` | `ssa` | `uvicorn ssa.apps.api.main:app` | |
| `scheduler` | `ssa` | `python -m ssa.apps.scheduler` | **Exactly one replica.** Advisory lock enforces it |

**Seven services, no broker.** That is the whole MVP production footprint.

### 7.2 Post-MVP addition

When the ADR-006 trigger fires, a `worker` service (and, if Celery is chosen, a `beat` service) joins the compose file, and periodic scheduling moves from `scheduler` into the queue runtime. Queues are separated — `default`, `analytics`, `ml`, `notifications` — so a 20-minute training run cannot delay a time-sensitive reminder. No other service changes.

**Volumes:** `pgdata`, `redisdata`, `caddy_data` (certificates); later `models` (ML artifacts) and `media` (rendered charts).

**Health and ordering:** every service has a healthcheck; `depends_on` uses `condition: service_healthy`. `restart: unless-stopped` throughout.

---

## 8. Container build

Multi-stage Dockerfile:

1. **builder** — `uv sync --frozen` into a virtualenv.
2. **runtime** — slim base, copy the venv and source, run as a **non-root user**, `HEALTHCHECK` defined.

Layer ordering: dependency manifests copied and installed *before* application source, so code changes do not invalidate the dependency layer. A source-only rebuild takes seconds.

The MVP image installs only the `bot`, `api`, and base dependency groups — **the ML stack is not installed until ML ships** (ADR-011), keeping the MVP image small.

`.dockerignore` excludes `.git`, `notebooks/`, `tests/`, `.venv`, and local `.env` files — without it, the build context balloons and secrets can leak into images.

---

## 9. Environments

| | Local | Staging (optional) | Production |
|---|---|---|---|
| Telegram | Long polling, separate test bot | Webhook, staging bot | Webhook, live bot |
| Database | Compose Postgres | Compose Postgres | Compose Postgres + nightly off-site backup |
| Scheduler | On demand via CLI | Enabled | Enabled |
| Migrations | Manual (`make migrate`) | Automatic on deploy | Automatic on deploy |
| Logs | Pretty console | JSON | JSON + Sentry |
| Debug | On | Off | Off |

Configuration is entirely environment variables, read once into a typed `Settings` object at boot (Architecture §7.5). A missing required variable is a startup crash with a clear message — never a `None` discovered three hours later inside a nightly job. Scoring weights live here too, so tuning them is a restart rather than a migration.

**Secrets:** `.env` on the server with `600` permissions, owned by the deploy user; GitHub Actions secrets for CI. `.env.example` documents every key with a dummy value and is the only such file in the repository. A dedicated secrets manager is unnecessary complexity at this scale — revisit when more than one person deploys.

---

## 10. CI/CD

**On every pull request:** `ruff check` + `ruff format --check` → `mypy` (strict on domain and application) → `import-linter` (the layering contracts, including the one forbidding job-runtime imports in `application`) → `pytest` against service-container Postgres and Redis, with a coverage floor → `docker build` → Alembic round-trip test (`upgrade head` then `downgrade base`).

**Two tests are treated as release blockers**, because they protect the guarantees the design rests on: rollup idempotence, and the scoring caps (Architecture §11).

**On merge to `main`:** build and push the image tagged with the commit SHA → SSH to the host → `docker compose pull` → run the one-shot `migrate` service → recreate app services → smoke-test `/health` → roll back to the previous SHA tag on failure.

Immutable SHA tags mean rollback is `docker compose up` with the previous tag — no rebuild, no guessing what `latest` pointed at.

---

## 11. Backup and recovery

- **Nightly `pg_dump`** (custom format, compressed) to off-site object storage, 30-day retention.
- **Weekly full-restore test into a scratch container.** An untested backup is not a backup; this is the single highest-value operational habit in the whole document.
- **WAL archiving** added when the acceptable data-loss window drops below 24 hours. Not yet — a study bot losing one day of logs is partially recoverable from user memory, and the operational cost is not free.
- Redis: AOF persistence only. No backup — everything in it is reconstructible.
- ML artifacts (once they exist): synced to object storage nightly. Cheap, and retraining is expensive.
- **Documented recovery runbook**, target RTO one hour, written before it is needed rather than during an incident.

---

## 12. Operational safeguards

| Risk | Mitigation | Phase |
|---|---|---|
| Two schedulers double-running a rollup | Postgres advisory lock, not a deployment convention | MVP |
| Job crashes mid-execution | Every job idempotent; reruns on next tick (the MVP's entire recovery strategy) | MVP |
| A long rollup blocking user-facing work | Rollup runs in its own process, never in the bot | MVP |
| Postgres connection exhaustion | Bounded pools per process; PgBouncer if the count grows | MVP |
| Migration failure mid-deploy | One-shot migrate job gates app startup; failure aborts the deploy, previous version keeps running | MVP |
| Disk filling | Log rotation, disk-usage alert at 80% | MVP |
| Telegram rate limits (30/s global, 1/s per chat) | Single `TelegramSender` with a Redis token bucket; retry-after honoured; nothing else may call the Bot API | Notifications |
| Bulk notification fan-out spiking the DB | Dispatcher claims batches of 500 with `SKIP LOCKED`, paced against the token bucket | Notifications |
| ML training starving user-facing work | Dedicated queue, separate worker concurrency, CPU limits | ML |
| Chart rendering blocking the bot | Rendering is scheduler/worker-only; `apps.bot` is forbidden from importing matplotlib by an import contract | Analytics |

---

## 13. Capacity expectation

At 5,000 active users averaging 3 study sessions per day:

- `study_sessions`: ~5.5M rows/year — a rounding error for Postgres with the right indexes.
- `daily_user_stats`: ~1.8M rows/year.
- `weekly_user_stats`: ~260k rows/year.
- Nightly rollup over one day of data: seconds. Comfortably inside a single-process scheduler, which is what makes the ADR-006 deferral tenable rather than optimistic.
- Peak Telegram load: comfortably inside a single bot container.

**The stated scale is not a scaling problem.** It is a *correctness and data-quality* problem — which is why this phase spent its effort on layering, timezone handling, rebuildable aggregates, and a scoring model that cannot be gamed, rather than on horizontal scaling machinery.

---

## 14. Phase 2 entry checklist

All blocking decisions are resolved (`00_Decision_Log.md`). Remaining items are confirmations, not open questions:

- [x] Leaderboards derived, not stored (D1)
- [x] Balanced capped scoring; rollup columns specified (D2, `05_Scoring_Model.md` §7)
- [x] No `user_events`, no `outbox`; rebuildable rollups only (D3)
- [x] Internal bigint PK + external UUID + separate `telegram_accounts` (D4)
- [x] Background runtime deferred behind abstract interfaces (D5)
- [x] k ≥ 20 cohort minimum, no free-text in cross-user datasets (D6)
- [ ] ORM mapper approach — decide around the fifth entity (ADR-004). No schema impact.

**First slice scope** (detailed in `06_Database_Schema.md`, delivered across four migrations): `users`, `telegram_accounts`, `privacy_settings`, `subjects`, `study_sessions`, `sleep_logs`, `mood_logs`, `exercise_logs`, `goals`, `goal_schedule_days`, `daily_user_stats`, `weekly_user_stats`.
