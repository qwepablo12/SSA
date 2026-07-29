# Student Success Assistant — Database Schema

**Phase 2 · Database Layer · First Vertical Slice**
Version 1.1 · Status: **approved with adjustments** — see §0.

Source of truth: `00_Decision_Log.md` (D1–D6), `01_Architecture.md`, `04_Data_Strategy_and_Deployment.md`.

---

## 0. Approved adjustments

| Q | Resolution | Effect on this document |
|---|---|---|
| **Q1** | **Rejected.** No exclusion constraint, no `btree_gist`. Overlap of completed sessions validated in the application layer. The partial unique index preventing multiple active sessions **stays**. | §6 — exclusion constraint struck; no extensions required anywhere in the schema |
| **Q2** | **Approved.** Timezone changes never rewrite historical `local_date`. | §15.7 confirmed |
| **Q3** | **Approved.** Minimal `goals` + `goal_schedule_days` included. | §10, §11 stand |
| **Q4** | **Approved.** Soft-deleted study sessions purged permanently after 30 days. | §6, §14 — adds a scheduled maintenance job in Phase 3 |
| **Q5** | **Approved.** Sleep attributed to the **wake** date. | §7 confirmed |
| **Q6** | **Approved.** Timezone validation in the application layer; no trigger. | §2 confirmed |
| **Q7** | **Deferred.** `weekly_user_stats` moves to the Gamification phase. | §13 out of scope; **slice is now 11 tables** |

**Consequence of Q1 to carry into the application layer:** `CompleteStudySession` must check for overlap against existing completed sessions before commit. Because this is no longer enforced by the database, it is a *checked* invariant rather than a *guaranteed* one — a concurrent double-write can still produce overlap. Mitigated by the partial unique index (only one session can be in progress at a time, so the realistic race is narrow) and by a data-quality check in the nightly rollup that logs, rather than fixes, any overlap it finds. Revisit Q1 if that check ever fires.

**Consequence of Q7:** the nightly `rebuild_daily_stats` job is the only rollup in the MVP. `weekly_user_stats` is specified in §13 for reference but is **not** built in this phase.

---

## 1. Scope

**Twelve tables**, plus `alembic_version`.

| Group | Tables |
|---|---|
| Identity | `users`, `telegram_accounts`, `privacy_settings` |
| Tracking | `subjects`, `study_sessions`, `sleep_logs`, `mood_logs`, `exercise_logs` |
| Goals (minimal) | `goals`, `goal_schedule_days` |
| Rollups | `daily_user_stats`, `weekly_user_stats` |

**Deliberately excluded from this slice:** friendships, groups, achievements, streaks, challenges, notifications, model registry, predictions, leaderboard snapshots. None is required by tracking or by the rollups, and each would be speculative now.

**Also excluded, per approved decisions:** any leaderboard base table (D1), `user_events` (D3), `outbox` (D3).

### 1.1 A scope judgement worth confirming

The brief says "goals only where required by tracking". Two columns of `daily_user_stats` — `is_committed_day` and `met_daily_goal` — need a goal to exist. There were two ways to satisfy that:

- **Include a minimal `goals` + `goal_schedule_days` now** (proposed).
- Ship rollups with those columns absent, add them in a later migration.

I propose including them, because "did I hit today's target?" is the core tracking loop rather than a gamification extra, and because the consistency denominator (`committed_days`) is the one input that cannot be reconstructed retroactively — if a user did not declare their intended days in week 1, week 1's consistency is unknowable forever. Everything else in the goals module (progress history, difficulty factors, goal types beyond study minutes) is deferred. See open question **Q3** if you would rather defer entirely.

### 1.2 Conventions applied to every table

- **Timestamps:** `TIMESTAMPTZ`, always UTC. Never `TIMESTAMP`.
- **Surrogate keys:** `BIGINT GENERATED ALWAYS AS IDENTITY` on entity tables. Two deliberate exceptions, justified in place: 1:1 extension tables key on `user_id`; rollup tables key on their grain.
- **Enumerations:** `TEXT` + `CHECK`, never native Postgres `ENUM` (ADR-003 — adding a value is one `ALTER` rather than a migration dance).
- **Audit columns:** `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` everywhere; `updated_at` on mutable tables, maintained by the application (SQLAlchemy `onupdate`) with `DEFAULT now()` as the insert value.
- **Alembic naming convention**, set on the declarative base before migration #1:

```
ix_%(column_0_label)s
uq_%(table_name)s_%(column_0_name)s
ck_%(table_name)s_%(constraint_name)s
fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s
pk_%(table_name)s
```

- **No extensions required** except optionally `btree_gist` (open question **Q1**). `gen_random_uuid()` is built in from PostgreSQL 13.

---

# Part I — Identity

## 2. `users`

**Purpose.** The internal identity record. Every other table in the system points here. Deliberately contains **no Telegram fields** (D4) — this table must be meaningful when a web client exists.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | no | — | Internal PK, target of every FK |
| `public_id` | `UUID` | no | `gen_random_uuid()` | The **only** identifier exposed externally |
| `timezone` | `TEXT` | no | `'UTC'` | IANA name, e.g. `Europe/London` |
| `locale` | `TEXT` | no | `'en'` | BCP-47 language tag |
| `display_name` | `TEXT` | yes | — | User-chosen, for greetings and future social display |
| `status` | `TEXT` | no | `'active'` | `active` / `suspended` / `deleted` |
| `onboarding_completed_at` | `TIMESTAMPTZ` | yes | — | Drives the bot's onboarding branch |
| `created_at` | `TIMESTAMPTZ` | no | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | no | `now()` | |
| `deleted_at` | `TIMESTAMPTZ` | yes | — | Erasure marker; see §14 |

**Keys.** PK `id`. Unique `public_id`.

**Check constraints.**

- `ck_users_status` — `status IN ('active','suspended','deleted')`
- `ck_users_timezone_not_blank` — `length(trim(timezone)) > 0`
- `ck_users_display_name_length` — `display_name IS NULL OR length(display_name) BETWEEN 1 AND 64`

**Indexes.** PK; `uq_users_public_id`; partial `ix_users_deleted_at ON users (deleted_at) WHERE deleted_at IS NOT NULL` — used only by the erasure sweep, so a partial index keeps it near-empty.

**Timezone validity is enforced in the application, not the database.** A `CHECK` cannot query `pg_timezone_names`, and `AT TIME ZONE` *raises* on an invalid zone rather than returning `NULL`, so it cannot be caught by a constraint either. The application validates against `zoneinfo.available_timezones()` on write. A trigger validating against `pg_timezone_names` is possible and is noted as **Q6** — my recommendation is to skip it, because the only writer is the application and a trigger adds a moving part for a value that comes from a fixed picker list.

**Why `display_name` rather than reading Telegram's `first_name`:** copying the Telegram profile name into every greeting would put a Telegram-shaped assumption into the identity layer, which is exactly what D4 exists to prevent. It is nullable — the bot falls back to a neutral greeting.

**Privacy.** `display_name` is user-supplied free text and is scrubbed on erasure. `public_id` is random, so external identifiers cannot be enumerated or counted.

**Deletion.** All child tables cascade from `users.id`. See §14 for the erasure procedure.

---

## 3. `telegram_accounts`

**Purpose.** Telegram-specific identity, isolated so that adding a second login provider is a new table rather than a schema-wide migration (D4).

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `user_id` | `BIGINT` | no | — | **PK and FK** → `users.id` |
| `telegram_id` | `BIGINT` | no | — | Telegram's user id |
| `chat_id` | `BIGINT` | no | — | Private-chat address for outbound messages |
| `telegram_username` | `TEXT` | yes | — | Mutable; cached for support and display |
| `language_code` | `TEXT` | yes | — | Telegram's reported language, used to seed `users.locale` |
| `linked_at` | `TIMESTAMPTZ` | no | `now()` | |
| `last_seen_at` | `TIMESTAMPTZ` | yes | — | Updated on interaction; cheap activity signal |

**Keys.** PK `user_id`. FK `user_id → users(id) ON DELETE CASCADE`. Unique `telegram_id`.

**Relationship.** 1:1 with `users`.

**Why `user_id` is the primary key instead of a surrogate `id`:** the relationship is genuinely 1:1, so a separate identity column would add a key nobody references and would permit two Telegram accounts per user at the schema level — a state the application would then have to police. Using `user_id` as the PK makes the 1:1 a structural guarantee. The same reasoning applies to `privacy_settings`.

**Check constraints.**

- `ck_telegram_accounts_telegram_id_positive` — `telegram_id > 0`
- `ck_telegram_accounts_username_length` — `telegram_username IS NULL OR length(telegram_username) <= 32`

**Indexes.** PK (`user_id`); `uq_telegram_accounts_telegram_id` — this one is hit on **every single incoming update**, so it is the hottest index in the database.

**Why `chat_id` is stored separately when it currently equals `telegram_id`:** for private chats the two are equal today, but that is an undocumented Telegram invariant rather than a guarantee, and it stops being true the moment the bot is ever used in a group context. `chat_id` is the address we send to; `telegram_id` is who the person is. Conflating an address with an identity is cheap to avoid now and expensive to untangle later. This is the one field in the schema I would call speculative, and I would defend it on the grounds that it costs 8 bytes.

**Privacy.** `telegram_id`, `chat_id`, and `telegram_username` are directly identifying. This row is deleted outright on erasure — never anonymised and retained.

---

## 4. `privacy_settings`

**Purpose.** Per-user privacy and consent state. Exists from the first user row even though social features are not in this slice.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `user_id` | `BIGINT` | no | — | PK and FK → `users.id` |
| `profile_visibility` | `TEXT` | no | `'private'` | `private` / `friends` / `groups` |
| `stats_visibility` | `TEXT` | no | `'private'` | same domain |
| `leaderboard_opt_in` | `BOOLEAN` | no | `false` | D1/D2 — off by default |
| `research_consent` | `BOOLEAN` | no | `false` | Gates inclusion in cross-user datasets (D6) |
| `research_consent_at` | `TIMESTAMPTZ` | yes | — | When consent was given |
| `updated_at` | `TIMESTAMPTZ` | no | `now()` | |

**Keys.** PK `user_id`. FK `ON DELETE CASCADE`.

**Check constraints.**

- `ck_privacy_settings_profile_visibility` — `IN ('private','friends','groups')`
- `ck_privacy_settings_stats_visibility` — same
- `ck_privacy_settings_research_consent_timestamp` — `(research_consent = false) OR (research_consent_at IS NOT NULL)`

**Indexes.** PK only. This table is always accessed by `user_id`.

**Why it ships now, before any feature reads it:** consent must be recorded from the moment data collection begins, and defaults must be correct for the first cohort of users. Backfilling a `false` consent flag onto existing rows later is technically trivial but means there is a window during which the consent state of early users is genuinely ambiguous. The table costs four columns.

**Why `research_consent_at` is not redundant:** a boolean records the current state; consent needs an auditable moment. If consent is ever questioned, "true" is not an answer.

**Privacy.** This table *is* the privacy control surface. Row is deleted on erasure; the consent timestamp is not retained.

---

# Part II — Tracking

## 5. `subjects`

**Purpose.** User-defined study subjects. Per-user, not a shared catalogue.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` identity | no | — | PK |
| `user_id` | `BIGINT` | no | — | FK → `users.id` |
| `name` | `TEXT` | no | — | Free text |
| `colour` | `TEXT` | yes | — | `#RRGGBB`, for charts |
| `is_archived` | `BOOLEAN` | no | `false` | Hidden from pickers, retained for history |
| `created_at` | `TIMESTAMPTZ` | no | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | no | `now()` | |

**Keys.** PK `id`. FK `user_id → users(id) ON DELETE CASCADE`.

**Unique constraints.** `uq_subjects_user_name` as a **functional unique index** on `(user_id, lower(name))` — "Maths" and "maths" are the same subject, and letting both exist silently splits a user's statistics in two. Archived subjects are included in the constraint, so a name cannot be reused while an archived subject holds it; that is intentional, because reusing a name would merge two conceptually distinct subjects in historical charts.

**Check constraints.**

- `ck_subjects_name_length` — `length(trim(name)) BETWEEN 1 AND 100`
- `ck_subjects_colour_format` — `colour IS NULL OR colour ~ '^#[0-9A-Fa-f]{6}$'`

**Indexes.** PK; the functional unique index above; partial `ix_subjects_user_active ON subjects (user_id) WHERE NOT is_archived` for the subject picker, which is rendered on nearly every session start.

**Why archive rather than delete:** deleting a subject would either orphan or destroy the sessions attached to it. Archiving preserves history at the cost of one boolean. Hard deletion remains possible and is handled by `study_sessions.subject_id ON DELETE SET NULL`.

**Privacy.** `name` is user-supplied free text and is therefore **excluded from all cross-user datasets** (D6) — subject names are frequently identifying ("Dissertation — J. Smith supervision").

---

## 6. `study_sessions`

**Purpose.** The primary behavioural record and the highest-volume table in the system. Source of truth for everything the analytics layer derives.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` identity | no | — | PK |
| `user_id` | `BIGINT` | no | — | FK → `users.id` |
| `subject_id` | `BIGINT` | yes | — | FK → `subjects.id`; NULL = unspecified |
| `status` | `TEXT` | no | `'in_progress'` | `in_progress` / `completed` / `abandoned` / `discarded` |
| `started_at` | `TIMESTAMPTZ` | no | — | UTC |
| `ended_at` | `TIMESTAMPTZ` | yes | — | NULL while in progress |
| `local_date` | `DATE` | no | — | Derived at write time; see below |
| `duration_seconds` | `INTEGER` | yes | *generated* | `GENERATED ALWAYS AS (...) STORED` |
| `planned_minutes` | `SMALLINT` | yes | — | What the user intended |
| `focus_score` | `SMALLINT` | yes | — | Self-reported 1–5 |
| `session_type` | `TEXT` | no | `'focus'` | `focus` / `review` / `practice` / `reading` / `other` |
| `interruption_count` | `SMALLINT` | no | `0` | |
| `notes` | `TEXT` | yes | — | Free text |
| `created_at` | `TIMESTAMPTZ` | no | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | no | `now()` | |
| `deleted_at` | `TIMESTAMPTZ` | yes | — | Soft delete for user-corrected mistakes |

**Keys.** PK `id`. FK `user_id → users(id) ON DELETE CASCADE`. FK `subject_id → subjects(id) ON DELETE SET NULL`.

**Generated column.**

```sql
duration_seconds INTEGER
  GENERATED ALWAYS AS (
    CASE WHEN ended_at IS NULL THEN NULL
         ELSE EXTRACT(EPOCH FROM (ended_at - started_at))::INTEGER END
  ) STORED
```

Stored rather than application-computed so the value can never disagree with the timestamps it derives from — a class of bug that is invisible until a chart looks wrong months later. Seconds rather than minutes because rounding at write time loses fidelity permanently; presentation rounds to minutes.

**Check constraints.**

- `ck_study_sessions_status` — `status IN ('in_progress','completed','abandoned','discarded')`
- `ck_study_sessions_end_after_start` — `ended_at IS NULL OR ended_at > started_at`
- `ck_study_sessions_status_end_consistency` — `(status = 'in_progress') = (ended_at IS NULL)`
- `ck_study_sessions_max_duration` — `ended_at IS NULL OR ended_at <= started_at + INTERVAL '12 hours'`
- `ck_study_sessions_focus_range` — `focus_score IS NULL OR focus_score BETWEEN 1 AND 5`
- `ck_study_sessions_session_type` — `session_type IN ('focus','review','practice','reading','other')`
- `ck_study_sessions_interruptions_non_negative` — `interruption_count >= 0`
- `ck_study_sessions_planned_minutes_positive` — `planned_minutes IS NULL OR planned_minutes > 0`

**On the 12-hour ceiling:** the domain rule from Phase 1 is 8 hours, enforced in `domain/tracking/rules.py`. The database ceiling is deliberately looser. A database constraint is a backstop against corruption, not a restatement of a business rule — setting it at exactly 8 hours would mean every future adjustment to the product rule requires a migration, and would make legitimate data repair harder. 12 hours catches the real failure mode (a forgotten timer producing a 3-day session) without encoding policy.

**Unique constraints.**

```sql
CREATE UNIQUE INDEX uq_study_sessions_one_active
  ON study_sessions (user_id) WHERE status = 'in_progress';
```

**At most one running session per user, enforced structurally.** Double-tapping "start" is the single most likely concurrency bug in the whole bot, and this makes it impossible rather than unlikely.

**Overlap prevention — application layer (Q1 rejected).** No exclusion constraint and no `btree_gist`. `CompleteStudySession` checks the new interval against the user's existing completed sessions before commit and raises `ConflictError` on overlap. The nightly rollup additionally logs (does not repair) any overlap it encounters, so that if the check is ever bypassed the data-quality problem is visible rather than silent.

**Indexes.**

| Index | Purpose |
|---|---|
| `ix_study_sessions_user_started` on `(user_id, started_at DESC) WHERE deleted_at IS NULL` | User history — the dominant read pattern |
| `ix_study_sessions_rollup` on `(local_date, user_id) WHERE deleted_at IS NULL` | The nightly rollup, which scans one date across all users |
| `ix_study_sessions_user_subject` on `(user_id, subject_id, local_date) WHERE deleted_at IS NULL` | Per-subject breakdowns |
| `uq_study_sessions_one_active` | The partial unique above |

All are partial on `deleted_at IS NULL` because every production query carries that predicate; including deleted rows would bloat the indexes for no reader.

**Why `local_date` is stored rather than derived on read.** It looks redundant — it is computable from `started_at` and `users.timezone`. It is stored for two independent reasons, either of which alone would justify it:

1. **Performance.** The nightly rollup groups millions of rows by local date. Computing `(started_at AT TIME ZONE u.timezone)::date` per row requires joining `users` and applying a function, which makes the expression unindexable in practice and turns a cheap index range scan into a full scan plus sort.
2. **Correctness, which matters more.** A user who moves from London to Tokyo changes their timezone. If `local_date` were derived on read, every historical session would silently re-bucket — a Tuesday-evening session logged months ago would become Wednesday, streaks would change retroactively, and past statistics the user has already seen would differ from what they saw. Storing the value at write time means history records the day as it was actually experienced.

The value is computed once, in the application, at insert: `(started_at AT TIME ZONE users.timezone)::date`.

**Deletion behaviour.** Cascade from `users`. `SET NULL` from `subjects` so hard-deleting a subject never destroys behavioural history. User-initiated deletion is **soft** (`deleted_at`), because sessions are frequently deleted by mistake and undo is worth having; soft-deleted rows are excluded from every rollup and every index. **Purged permanently 30 days after `deleted_at`** (Q4 approved) by a scheduled maintenance job, so deleted personal notes do not persist indefinitely.

**Privacy.** `notes` is free text — excluded from cross-user datasets (D6) and scrubbed on erasure.

---

## 7. `sleep_logs`

**Purpose.** Daily sleep record. A primary input to both productivity prediction and the wellbeing gate.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` identity | no | — | PK |
| `user_id` | `BIGINT` | no | — | FK → `users.id` |
| `local_date` | `DATE` | no | — | The **wake** date |
| `duration_minutes` | `SMALLINT` | no | — | Authoritative value |
| `bedtime_at` | `TIMESTAMPTZ` | yes | — | Optional |
| `wake_at` | `TIMESTAMPTZ` | yes | — | Optional |
| `quality` | `SMALLINT` | yes | — | 1–5 |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | no | `now()` | |

**Keys.** PK `id`. FK `ON DELETE CASCADE`.

**Unique constraints.** `uq_sleep_logs_user_date` on `(user_id, local_date)` — one sleep record per night. Re-logging updates rather than appends.

**Check constraints.**

- `ck_sleep_logs_duration_range` — `duration_minutes BETWEEN 0 AND 1440`
- `ck_sleep_logs_quality_range` — `quality IS NULL OR quality BETWEEN 1 AND 5`
- `ck_sleep_logs_wake_after_bedtime` — `bedtime_at IS NULL OR wake_at IS NULL OR wake_at > bedtime_at`

**Indexes.** PK; the unique above (which also serves `(user_id, local_date DESC)` range queries); `ix_sleep_logs_local_date ON (local_date)` for the rollup's cross-user pass.

**Why `duration_minutes` is authoritative and the timestamps are optional.** Requiring bed and wake times would be more precise and would destroy logging compliance — most people will answer "about seven hours" and abandon a form that demands two timestamps. Since sleep duration is what every downstream consumer actually uses, duration is the required field and the timestamps are an enrichment for users who want them. **This is a deliberate trade of precision for data volume**, on the grounds that a sparse precise dataset is worth less than a dense approximate one for this purpose.

**Timezone.** Sleep is attributed to the **wake date** — the night of the 3rd→4th is logged as the 4th. This must be fixed now because it silently determines every sleep-versus-productivity correlation the project will ever compute; the alternative (bedtime date) is equally defensible but must not be chosen twice. Confirmation requested as **Q5**.

**Privacy.** No free text. Sleep data is health-adjacent and is never included in any cross-user aggregate below the k = 20 threshold, and never in group displays at all.

---

## 8. `mood_logs`

**Purpose.** Point-in-time affect record. Multiple entries per day are allowed.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` identity | no | — | PK |
| `user_id` | `BIGINT` | no | — | FK → `users.id` |
| `recorded_at` | `TIMESTAMPTZ` | no | `now()` | |
| `local_date` | `DATE` | no | — | Derived from `recorded_at` |
| `mood` | `SMALLINT` | no | — | 1–5 |
| `energy` | `SMALLINT` | yes | — | 1–5 |
| `stress` | `SMALLINT` | yes | — | 1–5 |
| `note` | `TEXT` | yes | — | Free text |
| `created_at` | `TIMESTAMPTZ` | no | `now()` | |

**Keys.** PK `id`. FK `ON DELETE CASCADE`.

**Unique constraints.** **None.** Mood genuinely varies within a day, and collapsing it to one value per day would discard the most interesting signal in the dataset — intra-day variation around study sessions. The daily rollup averages.

**Check constraints.**

- `ck_mood_logs_mood_range` — `mood BETWEEN 1 AND 5`
- `ck_mood_logs_energy_range` — `energy IS NULL OR energy BETWEEN 1 AND 5`
- `ck_mood_logs_stress_range` — `stress IS NULL OR stress BETWEEN 1 AND 5`
- `ck_mood_logs_note_length` — `note IS NULL OR length(note) <= 1000`

**Indexes.** PK; `ix_mood_logs_user_recorded ON (user_id, recorded_at DESC)`; `ix_mood_logs_local_date ON (local_date)` for the rollup.

**Why `local_date` is stored here too:** same reasoning as `study_sessions` — the rollup groups by it, and a timezone change must not retroactively move a mood entry to a different day.

**Privacy.** `note` is free text, frequently sensitive (mood notes are where people write about their lives). Excluded from cross-user datasets unconditionally, scrubbed first on erasure, and never surfaced in any shared view regardless of visibility settings.

---

## 9. `exercise_logs`

**Purpose.** Physical activity record — a feature for productivity modelling and a wellbeing signal.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` identity | no | — | PK |
| `user_id` | `BIGINT` | no | — | FK → `users.id` |
| `occurred_at` | `TIMESTAMPTZ` | no | — | |
| `local_date` | `DATE` | no | — | Derived |
| `activity_type` | `TEXT` | no | `'other'` | `cardio` / `strength` / `walking` / `sport` / `other` |
| `duration_minutes` | `SMALLINT` | no | — | |
| `intensity` | `TEXT` | yes | — | `low` / `moderate` / `high` |
| `created_at` | `TIMESTAMPTZ` | no | `now()` | |

**Keys.** PK `id`. FK `ON DELETE CASCADE`.

**Unique constraints.** None — multiple sessions per day are normal.

**Check constraints.**

- `ck_exercise_logs_duration_range` — `duration_minutes BETWEEN 1 AND 600`
- `ck_exercise_logs_activity_type` — `IN ('cardio','strength','walking','sport','other')`
- `ck_exercise_logs_intensity` — `intensity IS NULL OR intensity IN ('low','moderate','high')`

**Indexes.** PK; `ix_exercise_logs_user_occurred ON (user_id, occurred_at DESC)`; `ix_exercise_logs_local_date ON (local_date)`.

**Privacy.** No free text. Health-adjacent; same handling as sleep.

---

# Part III — Goals (minimal)

## 10. `goals`

**Purpose.** The user's declared target. In this slice, only what tracking needs: a daily or weekly study-minutes target.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` identity | no | — | PK |
| `user_id` | `BIGINT` | no | — | FK → `users.id` |
| `metric` | `TEXT` | no | `'study_minutes'` | `study_minutes` / `session_count` |
| `period` | `TEXT` | no | `'daily'` | `daily` / `weekly` |
| `target_value` | `INTEGER` | no | — | Minutes or sessions |
| `status` | `TEXT` | no | `'active'` | `active` / `completed` / `cancelled` |
| `starts_on` | `DATE` | no | — | Local date |
| `ends_on` | `DATE` | yes | — | NULL = open-ended |
| `created_at` | `TIMESTAMPTZ` | no | `now()` | Anti-gaming input, see below |
| `updated_at` | `TIMESTAMPTZ` | no | `now()` | |

**Keys.** PK `id`. FK `ON DELETE CASCADE`.

**Unique constraints.**

```sql
CREATE UNIQUE INDEX uq_goals_one_active_per_metric_period
  ON goals (user_id, metric, period) WHERE status = 'active';
```

One active goal per metric and period. Without this, "your daily target" has no single answer and the rollup would have to pick arbitrarily.

**Check constraints.**

- `ck_goals_metric` — `metric IN ('study_minutes','session_count')`
- `ck_goals_period` — `period IN ('daily','weekly')`
- `ck_goals_status` — `status IN ('active','completed','cancelled')`
- `ck_goals_target_positive` — `target_value > 0`
- `ck_goals_end_after_start` — `ends_on IS NULL OR ends_on >= starts_on`

**Indexes.** PK; the partial unique above; `ix_goals_user_status ON (user_id, status)`.

**Why `created_at` is load-bearing rather than decorative:** the scoring model's anti-gaming rule (`05_Scoring_Model.md` §3.2) excludes goals created less than 24 hours before the period they govern. That rule needs a creation timestamp that cannot be edited, which is why goals are never updated in place when the target changes — a target change **cancels** the old goal and inserts a new one. This keeps an honest history of what was committed to and when.

**Privacy.** No free text in this slice (goal titles are deferred). Target values are personal but not identifying.

---

## 11. `goal_schedule_days`

**Purpose.** The days of the week a user has committed to studying. This is the denominator of the consistency metric — the single most important input to the scoring model.

| Column | Type | Null | Notes |
|---|---|---|---|
| `goal_id` | `BIGINT` | no | FK → `goals.id` |
| `weekday` | `SMALLINT` | no | ISO weekday, 1 = Monday … 7 = Sunday |

**Keys.** Composite PK `(goal_id, weekday)`. FK `goal_id → goals(id) ON DELETE CASCADE`.

**Check constraints.** `ck_goal_schedule_days_weekday_range` — `weekday BETWEEN 1 AND 7`.

**Indexes.** PK only. The table is tiny (≤ 7 rows per goal) and always read wholesale for a goal.

**Why a table rather than a bitmask or boolean array on `goals`.** A `SMALLINT` bitmask would be one column and is genuinely tempting at this size. It was rejected because bitmask semantics have to be re-derived in every consumer — SQL rollups, Python rules, and eventually a dashboard — and each place is an opportunity to get the bit order wrong in a way no constraint can catch. A two-column table is self-describing, joinable, and constrainable. It is one of the few places where the more "enterprise" option is also the simpler one to reason about.

**Naming note.** Phase 1 (`04` §3) referred to this as `goal_schedules`. Renamed to `goal_schedule_days` because the grain is one row per day, and a plural that does not name the grain invites the assumption that a row is a whole schedule.

**Deletion.** Cascades with the goal, which cascades with the user.

---

# Part IV — Rollups

Both rollup tables are **derived, idempotent, and fully rebuildable** from the tables above. Deleting either entirely and recomputing must reproduce them exactly. Neither is ever written by a user-facing request path.

## 12. `daily_user_stats`

**Purpose.** The analytical spine (`04` §3). Every user-facing statistic, every chart, the weekly rollup, and every future ML feature reads from here rather than from raw tables.

**Grain.** One row per user per local date on which anything was recorded.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `user_id` | `BIGINT` | no | — | PK part, FK → `users.id` |
| `local_date` | `DATE` | no | — | PK part |
| `study_seconds_raw` | `INTEGER` | no | `0` | Truth — user analytics and ML |
| `study_seconds_capped` | `INTEGER` | no | `0` | Scoring input (`05` §5) |
| `session_count` | `SMALLINT` | no | `0` | |
| `completed_session_count` | `SMALLINT` | no | `0` | |
| `abandoned_session_count` | `SMALLINT` | no | `0` | |
| `weighted_focus` | `NUMERIC(3,2)` | yes | — | Duration-weighted mean, 1.00–5.00 |
| `subjects_touched` | `SMALLINT` | no | `0` | |
| `is_active_day` | `BOOLEAN` | no | `false` | Met the minimum-duration bar |
| `is_committed_day` | `BOOLEAN` | no | `false` | Was in the declared schedule |
| `daily_goal_seconds` | `INTEGER` | yes | — | Snapshot of the target that applied |
| `met_daily_goal` | `BOOLEAN` | yes | — | NULL = no goal in force |
| `sleep_minutes` | `SMALLINT` | yes | — | |
| `sleep_quality` | `SMALLINT` | yes | — | |
| `mean_mood` | `NUMERIC(3,2)` | yes | — | |
| `mean_energy` | `NUMERIC(3,2)` | yes | — | |
| `mean_stress` | `NUMERIC(3,2)` | yes | — | |
| `mood_log_count` | `SMALLINT` | no | `0` | Confidence weight for the means |
| `exercise_minutes` | `SMALLINT` | no | `0` | |
| `wellbeing_flag` | `TEXT` | no | `'ok'` | `ok` / `caution` / `concern` |
| `computed_at` | `TIMESTAMPTZ` | no | `now()` | |
| `source_version` | `SMALLINT` | no | `1` | Rollup logic version |

**Keys.** Composite PK `(user_id, local_date)`. FK `user_id → users(id) ON DELETE CASCADE`.

**Why a composite natural primary key here, against the surrogate-key rule:** the grain *is* the identity. A surrogate `id` would add a column nothing references and would allow two rows for the same user-day, which is precisely the state the rollup must never produce. The composite PK makes the idempotent write a plain `INSERT ... ON CONFLICT (user_id, local_date) DO UPDATE`, with correctness guaranteed by the key rather than by the job's logic.

**Check constraints.**

- `ck_daily_user_stats_wellbeing_flag` — `IN ('ok','caution','concern')`
- `ck_daily_user_stats_counts_non_negative` — all count and seconds columns `>= 0`
- `ck_daily_user_stats_capped_le_raw` — `study_seconds_capped <= study_seconds_raw`
- `ck_daily_user_stats_focus_range` — `weighted_focus IS NULL OR weighted_focus BETWEEN 1 AND 5`
- `ck_daily_user_stats_mood_range` — each mean `IS NULL OR BETWEEN 1 AND 5`
- `ck_daily_user_stats_completed_le_total` — `completed_session_count <= session_count`

`ck_daily_user_stats_capped_le_raw` deserves a note: it is the **anti-overwork invariant expressed as a database constraint**. If a future change to the capping logic ever produced a capped value above the raw value, the write fails rather than silently inflating a score.

**Indexes.** PK `(user_id, local_date)` — serves user history directly, including range scans. Plus `ix_daily_user_stats_local_date ON (local_date)` for the weekly rollup and any cross-user pass.

**Why both `study_seconds_raw` and `study_seconds_capped` are stored.** They answer different questions and conflating them is how a scoring cap silently becomes a lie in a user's own analytics. The user's charts and every ML feature use `raw` — a person who studied 10 hours should see 10 hours. Scoring uses `capped`. Storing only `raw` would mean recomputing the cap on every scoring read (and needing the goal-at-the-time to do it); storing only `capped` would corrupt the dataset the entire project exists to build.

**Why `daily_goal_seconds` is snapshotted.** The cap depends on the goal in force *on that day*. If the user later raises their target, recomputing history against the new target would retroactively change past days. Snapshotting makes the rollup reproducible: rebuilding March produces March's numbers, not today's.

**Why `mood_log_count` alongside the means.** A mean of one entry and a mean of eight are different evidence. Without the count, downstream consumers cannot weight them, and the ML layer would treat a single grumpy afternoon as equal to a full day of sampling.

**Deletion.** Cascades with the user. Additionally, rows are freely deletable and recomputable — this table has no independent value.

**Timezone.** `local_date` is inherited from the raw records' stored `local_date`, never recomputed. The rollup performs no timezone arithmetic at all, which keeps timezone logic in exactly one place: the write path of the raw tables.

**Privacy.** Contains no free text by construction. This is the table cross-user aggregates read from, gated by k ≥ 20 and `research_consent` (D6).

---

## 13. `weekly_user_stats`

**Purpose.** Weekly behavioural aggregate. **Scoring columns are deliberately not included in this slice** — the five score components (`05_Scoring_Model.md` §7) arrive with the gamification phase, as an `ALTER TABLE`.

**Grain.** One row per user per ISO week.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `user_id` | `BIGINT` | no | — | PK part, FK → `users.id` |
| `iso_year` | `SMALLINT` | no | — | PK part |
| `iso_week` | `SMALLINT` | no | — | PK part, 1–53 |
| `week_start_local_date` | `DATE` | no | — | Monday of the ISO week |
| `active_days` | `SMALLINT` | no | `0` | |
| `committed_days` | `SMALLINT` | no | `0` | Consistency denominator |
| `consistency_ratio` | `NUMERIC(4,3)` | yes | — | `active / committed`, capped at 1.000 |
| `study_seconds_raw` | `INTEGER` | no | `0` | |
| `study_seconds_capped` | `INTEGER` | no | `0` | |
| `session_count` | `SMALLINT` | no | `0` | |
| `mean_focus` | `NUMERIC(3,2)` | yes | — | |
| `goals_set` | `SMALLINT` | no | `0` | |
| `goals_met` | `SMALLINT` | no | `0` | |
| `mean_sleep_minutes` | `SMALLINT` | yes | — | |
| `mean_mood` | `NUMERIC(3,2)` | yes | — | |
| `exercise_minutes` | `SMALLINT` | no | `0` | |
| `wellbeing_flag` | `TEXT` | no | `'ok'` | Weekly assessment |
| `computed_at` | `TIMESTAMPTZ` | no | `now()` | |
| `source_version` | `SMALLINT` | no | `1` | |

**Keys.** Composite PK `(user_id, iso_year, iso_week)`. FK `ON DELETE CASCADE`.

**Check constraints.**

- `ck_weekly_user_stats_iso_week_range` — `iso_week BETWEEN 1 AND 53`
- `ck_weekly_user_stats_iso_year_range` — `iso_year BETWEEN 2024 AND 2100`
- `ck_weekly_user_stats_active_le_seven` — `active_days BETWEEN 0 AND 7`
- `ck_weekly_user_stats_committed_le_seven` — `committed_days BETWEEN 0 AND 7`
- `ck_weekly_user_stats_capped_le_raw` — `study_seconds_capped <= study_seconds_raw`
- `ck_weekly_user_stats_goals_met_le_set` — `goals_met <= goals_set`
- `ck_weekly_user_stats_consistency_range` — `consistency_ratio IS NULL OR consistency_ratio BETWEEN 0 AND 1`

**Indexes.** PK; `ix_weekly_user_stats_year_week ON (iso_year, iso_week)` for the future leaderboard rebuild, which reads a week across all users.

**Why `week_start_local_date` is stored when it is derivable from `(iso_year, iso_week)`.** ISO week arithmetic is correct but unreadable — every ad-hoc query, every chart axis, and every debugging session wants a date. Deriving it requires `to_date(... 'IYYY-IW')` incantations that are easy to get subtly wrong (particularly around year boundaries, where ISO week 1 can begin in December). One `DATE` column removes an entire category of off-by-one bug from every future consumer.

**Why ISO week rather than a user-configurable week start.** ISO weeks start Monday, universally. Supporting Sunday-start weeks would make every cross-user comparison ambiguous and every leaderboard incomparable. Users who think in Sunday-start weeks lose a little familiarity; the dataset stays coherent. Worth revisiting only if it causes real complaints.

**Deletion.** Cascades with the user; freely recomputable.

**Privacy.** Same as daily — no free text, k ≥ 20 gate for any cross-user use.

---

# Part V — Cross-cutting behaviour

## 14. Deletion behaviour, consolidated

| Table | Parent FK action | User-initiated deletion |
|---|---|---|
| `users` | — | Erasure procedure below |
| `telegram_accounts` | `users` CASCADE | Deleted outright |
| `privacy_settings` | `users` CASCADE | Deleted outright |
| `subjects` | `users` CASCADE | Archive (`is_archived`); hard delete permitted |
| `study_sessions` | `users` CASCADE; `subjects` SET NULL | Soft (`deleted_at`) |
| `sleep_logs` | `users` CASCADE | Hard delete |
| `mood_logs` | `users` CASCADE | Hard delete |
| `exercise_logs` | `users` CASCADE | Hard delete |
| `goals` | `users` CASCADE | Status `cancelled`, never deleted |
| `goal_schedule_days` | `goals` CASCADE | With the goal |
| `daily_user_stats` | `users` CASCADE | Not user-deletable; recomputable |
| `weekly_user_stats` | `users` CASCADE | Not user-deletable; recomputable |

**Why soft delete only on `study_sessions`.** It is the record users delete by accident (wrong subject, wrong duration, forgot to stop the timer), and it is the one whose loss visibly damages their history. Sleep, mood, and exercise entries are cheap to re-enter and deleting one is almost always intentional. Adding `deleted_at` to every table would mean every query in the system carries a predicate for a feature nobody needs.

**Account erasure** is a single transaction: `DELETE FROM users WHERE id = ?`. Every table in this slice cascades, so there is nothing to enumerate and nothing to forget. That property is a design goal, not a coincidence — it is why no table in this slice denormalises personal data outside its owning row. Redis keys and cached artefacts are purged after the transaction commits.

Because `study_sessions` uses soft deletion, the erasure path must delete rather than mark — a `deleted_at` row still contains `notes`. The cascade handles this correctly by construction.

## 15. Timezone handling, consolidated

1. **Every timestamp is `TIMESTAMPTZ`, stored UTC.** No `TIMESTAMP` column exists in the schema.
2. **`users.timezone` is an IANA name.** Offsets are never stored — they are wrong twice a year.
3. **`local_date` is computed once, at write time**, in the application: `(<event timestamp> AT TIME ZONE users.timezone)::date`. It is never recomputed on read and never rewritten.
4. **Rollups perform no timezone arithmetic.** They group by the stored `local_date`. All timezone logic lives on the write path of four tables.
5. **DST is handled correctly for durations** because `TIMESTAMPTZ` subtraction yields absolute elapsed time. A session spanning a clock change records the time actually spent.
6. **DST is handled correctly for days** because a "day" is defined by `local_date`, not by a 24-hour window. Local days of 23 and 25 hours simply exist.
7. **Timezone changes are not retroactive** (proposed — **Q2**). Changing `users.timezone` affects records written after the change. History keeps the days as they were experienced.
8. **ISO week derivation** uses `local_date`, so weeks follow the user's local calendar.

## 16. Privacy implications, consolidated

**Free-text fields** — `users.display_name`, `subjects.name`, `study_sessions.notes`, `mood_logs.note`. These are the only re-identification vectors in the slice. They are excluded from every cross-user dataset unconditionally (D6), never included in any export destined for anywhere but the user themselves, and are the fields scrubbed first in any anonymisation path.

**Directly identifying** — `telegram_accounts.telegram_id`, `chat_id`, `telegram_username`. Confined to one table, deleted outright on erasure.

**Health-adjacent** — `sleep_logs`, `mood_logs`, `exercise_logs`, and `daily_user_stats.wellbeing_flag`. Never shown in any group or shared view, at any visibility setting. The wellbeing gate reads them; nothing user-facing outside the owner's own view does.

**Cross-user aggregation** reads only `daily_user_stats` and `weekly_user_stats`, requires `privacy_settings.research_consent`, and enforces k ≥ 20 in `AnonymisedAggregateQuery`.

**Export coverage.** Every table in this slice contains `user_id` (directly, or through `goals` for `goal_schedule_days`), so export enumerates twelve tables. A test asserts the export registry covers every user-scoped table in the metadata — a new table cannot be silently omitted.

---

## 17. ER diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                              users                                  │
│  id            BIGINT   PK  (internal, target of every FK)          │
│  public_id     UUID     UQ  (the only externally exposed id)        │
│  timezone      TEXT         (IANA)                                  │
│  locale, display_name, status, onboarding_completed_at              │
│  created_at, updated_at, deleted_at                                 │
└───┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┘
    │ 1:1      │ 1:1      │ 1:N      │ 1:N      │ 1:N      │ 1:N
    ▼          ▼          ▼          ▼          ▼          ▼
┌─────────┐ ┌────────┐ ┌────────┐ ┌───────┐ ┌────────┐ ┌──────────┐
│telegram_│ │privacy_│ │subjects│ │ goals │ │ sleep_ │ │  mood_   │
│accounts │ │settings│ │        │ │       │ │  logs  │ │   logs   │
│         │ │        │ │ id  PK │ │ id PK │ │ id  PK │ │  id  PK  │
│user_id  │ │user_id │ │user_id │ │user_id│ │user_id │ │ user_id  │
│  PK/FK  │ │ PK/FK  │ │name    │ │metric │ │local_  │ │recorded_ │
│telegram_│ │*_visib.│ │  UQ    │ │period │ │ date UQ│ │  at      │
│  id  UQ │ │lb_optin│ │ (lower)│ │target │ │duration│ │local_date│
│chat_id  │ │research│ │archived│ │status │ │quality │ │mood/enrg │
└─────────┘ │_consent│ └───┬────┘ │starts │ └────────┘ │  /stress │
            └────────┘     │      │ _on   │            │  note    │
                           │      └───┬───┘            └──────────┘
                           │          │ 1:N
                           │          ▼
                           │   ┌──────────────────┐
                           │   │goal_schedule_days│
                           │   │ goal_id  PK/FK   │
                           │   │ weekday  PK 1..7 │
                           │   └──────────────────┘
                           │
        ┌──────────────────┘ subject_id (nullable, ON DELETE SET NULL)
        │
        ▼
┌───────────────────────────────────────┐     ┌──────────────────┐
│           study_sessions              │     │  exercise_logs   │
│  id              BIGINT  PK           │     │  id      BIGINT  │
│  user_id         FK CASCADE           │     │  user_id FK      │
│  subject_id      FK SET NULL          │     │  occurred_at     │
│  status          in_progress|completed│     │  local_date      │
│                  |abandoned|discarded │     │  activity_type   │
│  started_at      TIMESTAMPTZ          │     │  duration_min    │
│  ended_at        TIMESTAMPTZ NULL     │     │  intensity       │
│  local_date      DATE  (stored)       │     └──────────────────┘
│  duration_seconds  GENERATED STORED   │
│  focus_score, session_type,           │
│  interruption_count, planned_minutes  │
│  notes, deleted_at                    │
│                                       │
│  UQ (user_id) WHERE in_progress       │
│  EXCLUDE no time overlap  [optional]  │
└───────────────┬───────────────────────┘
                │
                │  all raw tracking tables feed the nightly rollup
                │  (grouped by stored local_date — no tz arithmetic)
                ▼
┌───────────────────────────────────────────────────────┐
│                   daily_user_stats                    │
│  PK (user_id, local_date)          ← grain is the key │
│  study_seconds_raw / study_seconds_capped             │
│  session_count, completed, abandoned, subjects_touched│
│  weighted_focus                                       │
│  is_active_day, is_committed_day                      │
│  daily_goal_seconds (snapshot), met_daily_goal        │
│  sleep_minutes, sleep_quality                         │
│  mean_mood / energy / stress, mood_log_count          │
│  exercise_minutes, wellbeing_flag                     │
│  computed_at, source_version                          │
│  CHECK capped <= raw   ← anti-overwork invariant      │
└───────────────────────┬───────────────────────────────┘
                        │  weekly rollup
                        ▼
┌───────────────────────────────────────────────────────┐
│                  weekly_user_stats                    │
│  PK (user_id, iso_year, iso_week)                     │
│  week_start_local_date                                │
│  active_days, committed_days, consistency_ratio       │
│  study_seconds_raw / capped, session_count, mean_focus│
│  goals_set, goals_met                                 │
│  mean_sleep_minutes, mean_mood, exercise_minutes      │
│  wellbeing_flag, computed_at, source_version          │
│                                                       │
│  score component columns added in gamification phase  │
└───────────────────────────────────────────────────────┘

Not in this slice, per approved decisions:
  ✗ leaderboards base table (D1)   ✗ user_events (D3)   ✗ outbox (D3)
```

---

## 18. Unresolved design questions

Each needs a decision before migration #1. My recommendation is stated first in each case.

**Q1 — Overlap exclusion constraint on `study_sessions`?**
Adding `EXCLUDE USING gist` prevents the same minute being counted in two sessions, which would inflate every downstream statistic. It requires the `btree_gist` extension (available on every managed Postgres, one line in the migration) and makes bulk backfills and data repair more awkward, since violating rows are rejected rather than flagged.
*Recommendation: include it.* Double-counted time is a silent corruption of the exact dataset the project exists to produce, and the partial-unique index alone does not prevent it (two sequential sessions with mistyped times can overlap without either being `in_progress`).

**Q2 — Should a timezone change rewrite historical `local_date`?**
Proposed: no. History records days as they were experienced; a session logged on Tuesday evening in London stays Tuesday after moving to Tokyo. The alternative — backfilling every `local_date` and recomputing all rollups on timezone change — makes past statistics consistent with the present but silently alters numbers the user has already seen, and can break streaks retroactively.
*Recommendation: do not rewrite.* But this needs an explicit decision because it is invisible until someone travels.

**Q3 — Confirm goals belong in this slice.**
Proposed: yes, minimally (§1.1). The argument for including them is that `committed_days` cannot be reconstructed retroactively. The argument against is that it widens a slice you scoped as "tracking".
*Recommendation: include `goals` + `goal_schedule_days` as specified, defer everything else in the goals module.*

**Q4 — Purge policy for soft-deleted `study_sessions`.**
Rows with `deleted_at` set are excluded from all reads and indexes but retain `notes` indefinitely. Options: keep forever (simplest), or a maintenance job purging after 30 days (cleaner privacy posture, one more scheduled job).
*Recommendation: purge after 30 days.* It gives a real undo window and prevents deleted personal notes living forever, at the cost of one small idempotent job that the scheduler already exists to run.

**Q5 — Confirm sleep is attributed to the wake date.**
The night of the 3rd→4th is logged as the 4th. Defensible either way, but it silently determines every sleep-versus-productivity correlation the project will compute, so it must be decided once and documented rather than assumed twice.
*Recommendation: wake date.* It matches how people answer "how did you sleep last night?" and aligns sleep with the study day it plausibly affects.

**Q6 — Validate `users.timezone` against `pg_timezone_names` with a trigger?**
Application validation via `zoneinfo` already covers the only writer.
*Recommendation: no trigger.* The value comes from a fixed picker list, the application is the sole writer, and a trigger adds a moving part to a table that is otherwise trivially simple.

**Q7 — Should `weekly_user_stats` ship in this slice at all?**
It is specified above because your brief asked for weekly rollups. But nothing in the tracking MVP reads it — the first real consumer is the scoring model in the gamification phase, and its most valuable columns are the score components that are explicitly deferred.
*Recommendation: build the table and the job now anyway.* It validates the rollup pattern at a second grain, it is trivially rebuildable if the shape turns out wrong, and having a week of real aggregates to look at will materially improve the scoring weights. But it is the one table here I would accept an argument for deferring.

---

## 19. Recommended implementation order

Each step is independently testable and leaves the tree green. Steps 1–4 are prerequisites for everything.

**Step 0 — Foundation (no tables).**
`infrastructure/database/base.py` with `DeclarativeBase` and the naming convention; `engine.py` with async engine and sessionmaker; `SqlAlchemyUnitOfWork`; Alembic scaffolding with `env.py` wired to the metadata and to `Settings`. **The naming convention must be in place before the first `alembic revision` is generated** — retrofitting constraint names later means hand-editing migrations across every environment.

**Step 1 — Identity models.** `users`, `telegram_accounts`, `privacy_settings`. Small, no dependencies, and they exercise the 1:1 pattern, the identity column, and the UUID default.

**Step 2 — Migration 001, identity.** Generate, then **read the generated SQL line by line** — autogenerate misses partial indexes, functional indexes, and generated columns. Test `upgrade head` then `downgrade base` against a scratch database.

**Step 3 — Tracking models.** `subjects`, then `study_sessions` (the most constraint-heavy table in the slice), then `sleep_logs`, `mood_logs`, `exercise_logs`.

**Step 4 — Migration 002, tracking.** Hand-write the partial unique index, the functional unique index on `(user_id, lower(name))`, and the generated column. None of these will be produced correctly by autogenerate.

**Step 5 — Goals models and migration 003.** `goals`, `goal_schedule_days`, plus the partial unique index on active goals.

**Step 6 — Rollup model and migration 004.** `daily_user_stats` only (Q7 — `weekly_user_stats` deferred to the Gamification phase). Composite primary key, all check constraints.

**Step 7 — Repositories and mappers**, in the same order: identity, tracking, goals, rollups. Integration-tested against a real Postgres with per-test transaction rollback.

**Step 8 — Constraint tests.** A dedicated test module asserting that each constraint actually rejects what it claims to: two `in_progress` sessions, a negative duration, `capped > raw`, a duplicate `(user_id, local_date)` sleep log, a 20-hour session, a case-variant duplicate subject name. **These tests are the deliverable of this phase as much as the schema is** — an unenforced constraint is a comment.

**Step 9 — Seed and factory fixtures.** `factory_boy` factories for every model, plus a CLI seed command generating a realistic month of data for one user. This is what makes the rollup work in the next phase testable at all.

**Explicitly not in this phase:** the rollup jobs themselves, the scheduler process, and any bot handler. Those are Phase 3, and they consume this schema rather than shaping it.

---

## 20. Approval requested

Please confirm or amend **Q1–Q7**. Q1, Q3, and Q5 change the schema; Q2 and Q4 change behaviour; Q6 and Q7 are scope.

On approval I will write the SQLAlchemy models and Alembic migrations in the order in §19, one step at a time, pausing after Step 2 so you can review the first migration's generated SQL before the pattern is repeated four more times.
