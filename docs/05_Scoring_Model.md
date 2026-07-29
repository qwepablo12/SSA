# Student Success Assistant — Scoring Model

**Phase 1 · Architecture & Foundation**
Implements decision D2. This document defines what the system rewards, and therefore what behaviour it will produce.

---

## 1. Design position

A scoring formula in a product like this is not a display detail — it is the product's actual value system. Whatever it rewards is what users will do. Three constraints follow directly from the Vision:

1. **More hours must never mean a better score past a healthy point.** Not "diminishing returns" — a hard cap, above which additional study contributes exactly zero.
2. **A student with 3 hours a day available must be able to score as well as one with 8.** Scoring is relative to the user's own commitments and baseline, not to absolute output.
3. **Poor wellbeing must not be convertible into rank.** A user studying through sleep deprivation cannot buy a higher position with it.

A fourth constraint comes from the analytics goal: **the score must be explainable.** Component values are persisted, so the bot can say "your score fell because your consistency dropped from 6 days to 3", not just show a number moving. An unexplainable score teaches nothing, which would make it worthless for a product whose stated purpose is behavioural insight.

---

## 2. Scope of application

The score is computed **weekly**, per user, from `daily_user_stats`.

It is used for: friend and group leaderboards (opt-in), personal progress display, and challenge ranking. It is **not** used for: achievements (which are event-based), ML features (which use raw behavioural signals — the score is an opinionated summary and would inject its own bias into models), or anything shown without the user's explicit opt-in.

---

## 3. Components

Total is **0–100**, from five components. All are computed within a single ISO week in the user's local timezone.

### 3.1 Consistency — 30 points

The largest component, deliberately. Consistency is the behaviour the product exists to build.

```
consistency_ratio = active_days / committed_days
consistency       = 30 × min(1.0, consistency_ratio)
```

- `committed_days` — days the user declared they intend to study, from `goal_schedule_days`. Defaults to 5 if no schedule is set.
- `active_day` — a day with at least one completed session meeting a minimum duration (default 15 minutes), so that a 2-minute session cannot manufacture a streak.
- Ratio caps at 1.0. Studying all 7 days when 4 were committed scores the same as hitting all 4. **Exceeding your commitment is not rewarded** — that is the anti-overwork principle applied at the schedule level.

### 3.2 Goal completion — 25 points

```
completion_rate = goals_met / goals_set
goal_completion = 25 × completion_rate × difficulty_factor
```

`difficulty_factor` guards against the obvious exploit — setting trivially low goals to farm a perfect rate:

```
difficulty_factor = clamp(goal_target / rolling_median_target_8w, 0.6, 1.0)
```

A goal at or above your own 8-week median target counts fully. A goal well below it is discounted, but never below 0.6 — because deliberately reducing a target during a hard week is legitimate self-management, and punishing it heavily would teach users to hide when they are struggling. That would be actively harmful for a product with a burnout-detection feature.

**Anti-gaming rule:** goals must be created at least 24 hours before the period they govern. A goal set retroactively, or set and immediately met, is excluded from scoring (though it still counts for the user's own progress display — nothing is hidden from the user themselves).

### 3.3 Improvement — 15 points

Rewards trajectory rather than level, which is what makes the board winnable by everyone.

```
delta            = current_week_consistency − baseline_consistency_4w
improvement      = 7.5 + 15 × clamp(delta, −0.5, +0.5)
```

Centred at 7.5: a user holding steady gets half the component. Improvement adds up to 7.5; decline subtracts up to 7.5 but never more. Note it measures improvement in **consistency**, not in hours — otherwise this component would reintroduce exactly the escalation the model is built to prevent.

New users (fewer than 4 weeks of history) receive the neutral 7.5 rather than being scored on a baseline that does not exist.

### 3.4 Focus quality — 20 points

```
weighted_focus = Σ(session_focus × session_minutes_capped) / Σ(session_minutes_capped)
focus_quality  = 20 × (weighted_focus / 5)
```

Self-reported focus (1–5) weighted by capped session duration, so a single well-rated 10-minute session does not outweigh a week of real work — while a marathon low-focus session cannot dominate the average either.

`session_minutes_capped` is defined in §5.

**Known limitation, accepted:** self-reported focus is gameable by simply always reporting 5. Mitigations: the value is also shown back to the user in their own trend charts, where inflation destroys the usefulness they personally get from it, and this component is weighted below consistency and goal completion. A behavioural proxy (interruption count, session completion versus abandonment) can be blended in later once there is data to validate it against.

### 3.5 Healthy streak — 10 points

```
streak_component = 10 × min(1.0, current_streak_days / 14)
```

Saturates at 14 days. A 200-day streak scores identically to a 14-day one — which is the point. Uncapped streaks create loss aversion, and loss aversion is what drives people to study while ill rather than break a number.

**Streak rules designed to reduce that pressure:**

- A streak counts *committed* days, so a planned rest day never breaks it.
- Each user gets one **grace day per month** — one missed committed day does not reset the streak.
- Breaking a streak is reported neutrally ("your streak reset — you averaged 4 days a week last month, which is solid"), never with loss framing, and never after 22:00 local time.

---

## 4. Weights, and their status

| Component | Weight | Rewards |
|---|---|---|
| Consistency | 30 | Showing up as often as you said you would |
| Goal completion | 25 | Meeting commitments you set honestly |
| Improvement | 15 | Getting better relative to yourself |
| Focus quality | 20 | Working well, not just working long |
| Healthy streak | 10 | Sustained rhythm, saturating early |

These weights are **configuration, not structure** — held in `Settings`, versioned, and tunable without a migration. They are a starting position based on the Vision's priorities, not an empirical result. Expect to revise them once there is real data; that revision is a config change and a leaderboard rebuild, not a redesign.

Every weekly score row stores its `scoring_version`, so historical scores remain interpretable after a reweighting.

---

## 5. Caps and guards

**Daily study cap.** Minutes contributing to any component are capped per day:

```
session_minutes_capped_daily = min(actual_minutes, daily_goal_minutes × 1.2)
```

with a hard ceiling of 8 hours per day regardless of goal. Beyond the cap, additional study contributes **exactly zero** to the score. It is still recorded fully, still shown to the user in their own analytics, and still feeds burnout detection — it simply cannot be converted into rank.

**Wellbeing gate.** Evaluated weekly from tracked data. If any of the following holds:

- mean sleep below 6 hours across the week
- mean mood in the lowest band for 3+ consecutive days
- 3+ days exceeding the hard 8-hour ceiling
- mean stress in the highest band with declining focus

then the score is **frozen at the previous week's value** and the user is excluded from leaderboard *gains* for that week.

Frozen, not penalised — this is the important distinction. A penalty would punish someone already having a bad week, and would teach users to stop logging sleep and mood honestly, which would destroy the data the entire project depends on. Freezing removes the incentive without adding a cost. The user sees a private, non-judgemental note explaining it, and no one else sees anything at all.

**Cold start.** A user appears on leaderboards only after 14 days of history and 10 completed sessions. Below that, they see their own score with a "still calibrating" note. This prevents a first-week user from ranking first on a two-day sample.

**Inactivity.** Extended absence decays the score toward zero over 4 weeks rather than dropping it immediately — returning after a break should not feel like starting from nothing.

---

## 6. Leaderboard construction

Following D1, leaderboards are projections and not stored state.

**Scope.** Friends and groups only. **No global leaderboard** — comparing yourself to 5,000 strangers is demotivating for the ~4,900 who are not near the top, and serves no behavioural purpose the friend board does not serve better.

**Opt-in.** Off by default. `privacy_settings.leaderboard_opt_in` governs appearance; the user's own score is always visible to themselves.

**Storage.** Redis sorted set per `(scope, scope_id, iso_week)`, rebuilt after each weekly rollup. `leaderboard_snapshots` in Postgres retains final weekly standings for history.

**Presentation constraints** (these are design requirements, not copy suggestions):

- Show the user's own position and immediate neighbours, not a full ranked list.
- Show the component breakdown, not only the total.
- Never show another user's raw hours, sleep, or mood — only the composite score.
- No "you dropped 4 places" push notification. Rank changes are pull-only.

---

## 7. Schema implications

> **Storage note.** Study time is persisted in **seconds** (`06_Database_Schema.md` §12) so that no rounding is baked in at write time. The formulas in this document are written in minutes for readability; the implementation converts at the presentation boundary.

### `daily_user_stats` — one row per `(user_id, local_date)`

| Column | Purpose |
|---|---|
| `study_seconds_raw` | Truth, for the user's own analytics and for ML |
| `study_seconds_capped` | Scoring input (§5) |
| `session_count`, `completed_session_count` | Activity and abandonment |
| `weighted_focus` | §3.4 numerator, precomputed |
| `is_active_day` | Meets the minimum-duration bar |
| `is_committed_day` | Was this day part of the declared schedule |
| `met_daily_goal` | Goal completion input |
| `sleep_minutes`, `sleep_quality` | Wellbeing gate |
| `mean_mood`, `mean_energy`, `mean_stress` | Wellbeing gate |
| `exercise_minutes` | ML feature |
| `subjects_touched` | Breadth, for insights |
| `wellbeing_flag` | `ok` / `caution` / `concern` |

### `weekly_user_stats` — one row per `(user_id, iso_year, iso_week)`

Component scores stored individually — `consistency_score`, `goal_completion_score`, `improvement_score`, `focus_quality_score`, `streak_score` — plus `total_score`, their inputs (`active_days`, `committed_days`, `goals_set`, `goals_met`, `baseline_consistency_4w`, `streak_days_end`), `wellbeing_gate_applied`, and `scoring_version`.

**Storing components rather than only the total is the single most important schema decision in this document.** It is what makes the score explainable, debuggable, retroactively re-weightable, and useful as behavioural insight rather than as a bare number.

---

## 8. Rebuild guarantees

Both rollups are **idempotent and fully rebuildable** from raw tracking data. Recomputing any week must produce an identical row, given the same `scoring_version` and weights.

This is testable and will be tested: a scoring bug becomes a rerun rather than permanently corrupted history, and a weight change can be evaluated against past data before being deployed.

---

## 9. Open for tuning after first data

Not blocking Phase 2 — all are parameters:

- Component weights (§4).
- Minimum session duration for an active day (default 15 min).
- Streak saturation point (default 14 days) and grace-day allowance.
- Wellbeing gate thresholds — deliberately conservative to start; false positives here are cheap, false negatives are not.
- Whether to blend a behavioural focus proxy into §3.4.
