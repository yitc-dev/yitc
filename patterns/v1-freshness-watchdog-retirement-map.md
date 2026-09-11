---
name: v1-freshness-watchdog-retirement-map
class: observation
sourced_from: plan v2-project-automation-governance-methodology-night (L1 seed) + SPEC-0105 (v2 methodology-nightly, active) + SPEC-0107 (L3 freshness probe, withdrawn → follow-on plan) + the X-0090 incident (v1 nightly not methodology-aware) + the controller's read-only verification of the host cron surfaces 2026-06-25
applies_to: deciding the fate of each per-project v1 freshness/watchdog/nightly surface as projects migrate onto yitc-v2 — read when wiring the v2 methodology-nightly (SPEC-0105), when partitioning the v1 host nightly, or when CHARTER §P1 F3 «what gets removed?» is asked of v1 automation
cites:
  - SPEC-0105
  - SPEC-0107
  - SPEC-0106
  - v2-automation-grow-l2-product-cron-governance-l3-l
  - retirement-procedure
---

# v1 Freshness / Watchdog Retirement Map

> **Observation (a captured finding worth keeping, not a rule).** As projects migrate onto
> yitc-v2, the per-project v1 nightly / watchdog / freshness machinery that watches them today
> must each be given a **named disposition** — CHARTER §P1 F3 forbids a silent leftover. This map
> is that record: one row per v1 surface. It changes no rule and edits no host surface (the v1
> crons live in **external territory** — read-only provenance, never edited from a v2 session).

## What replaces them on the v2 side

- **L1 — `bin/yitc-v2 nightly`** (SPEC-0105, **active**): the bounded, methodology-AWARE v2 nightly.
  Enumerates `registry.yaml` projects whose `methodology == yitc_v2` and runs READ-ONLY governance /
  health checks (queue freshness, corpus/graph integrity, backup-verify). It **CHECKS and REPORTS
  only** — it never starts an autonomous work session, never self-fetches a task (the CHARTER §6 fence).
- **L3 — freshness probe** (SPEC-0107): "did the project's regular work actually run / is the output
  fresh?", run INDEPENDENTLY of the project's own loop. **NOT built yet** — SPEC-0107 is `withdrawn`
  (with L2 product-cron, SPEC-0106); both are deferred to the follow-on plan
  **`v2-automation-grow-l2-product-cron-governance-l3-l`** (grow-on-pull, when the first project needs it).

## Disposition vocabulary

- **kept-as-source** — the surface stays as the source of truth (typically: it keeps doing its job
  for v1 projects); nothing in v2 removes it.
- **replaced-by-`<v2-surface>`** — the named v2 surface now owns this concern for v2 projects.
- **removed-when-`<trigger>`** — the surface is slated for removal once a named trigger fires; until
  then it stays. The trigger is concrete (a built capability and/or a migration), never "someday".

## The retirement set — superseded v1 surfaces

| # | v1 surface (host, external territory) | Cadence | What it does | Disposition |
|---|---|---|---|---|
| 1 | `bin/yitc-night-cycle.sh` | cron 23:00 | Enumerates `yitc-workspace/workspace.yaml` projects and runs a v1 `yitc auto-session` on **each** — **no methodology filter** (the X-0090 structural hole). | **kept-as-source** for v1 projects; its **v2-project enumeration is replaced-by `bin/yitc-v2 nightly`** (SPEC-0105). The actual *partition* (make it stop enumerating v2 projects) is the separate card **** — referenced here, not done by this map. |
| 2 | `bin/check-methodologist-heartbeat.sh` | cron 5:00 | Workspace.yaml projects — checks methodologist-finding **freshness**. | **kept-as-source** for v1 projects. v2 has **no methodologist role** (CHARTER §6 — no multi-role taxonomy), so for a v2 project the equivalent governance/health-freshness concern is **replaced-by `bin/yitc-v2 nightly`** (queue-freshness + corpus integrity). v2 projects partitioned out by **** (the registry-by-path methodology filter; scoped only `yitc-night-cycle.sh`, row #1). |
| 3 | `bin/watchdog.sh` | cron */15 | Hardcoded container / pipeline checks (social-parser, planfix) — product-runtime liveness/freshness. | **kept-as-source** today (still watches social-parser / planfix). **removed-when** the follow-on plan `v2-automation-grow-l2-product-cron-governance-l3-l` builds the **L3 freshness probe (SPEC-0107)** AND the watched project has migrated to v2. Until both, it stays. |
| 4 | `bin/auto-session.sh` | registry `team_mode:true` enum (not directly cron'd) | Launches v1 auto-sessions for `team_mode:true` projects. | **kept-as-source** for v1 `team_mode` projects. There is **deliberately no v2 replacement**: the bounded v2 nightly checks-and-reports only and never runs an autonomous session — autonomy in v2 is opt-in **per project** via the deploy/work-autonomy declare-or-waive (SPEC-0097), **never an automation default** (CHARTER §6 fence). v2 projects must be partitioned out of its enumeration (**** — the `methodology:yitc_v2` exclusion in `load_team_projects`; scoped only `yitc-night-cycle.sh`, row #1). |

## Out-of-set (enumerated for completeness — NOT a v2-superseded surface)

One host surface is listed in the migration brief but is **not** a per-project freshness/watchdog
surface superseded by v2, so it is recorded here separately rather than in the retirement set above:

| v1 surface | Cadence | What it does | Disposition |
|---|---|---|---|
| `projects/ai-team-framework/bin/check-heartbeats.py` | cron */5 | Heartbeats of the **v1 platform's OWN subsystems** (ai-team-framework internals) — not the per-project roster. | **kept-as-source** — it watches the v1 platform itself, not migrated projects; nothing in the v2 methodology-nightly supersedes it. **removed-when** the v1 platform (ai-team-framework) is itself retired. Enumerated here only so its fate is on record (no silent leftover). |

## Coverage checklist (acceptance — CHARTER §P1 F3)

Every v1 freshness/watchdog surface the brief enumerates has a named disposition above — **no silent
leftover**:

- `bin/yitc-night-cycle.sh` → kept-as-source (v1) / replaced-by `bin/yitc-v2 nightly` (v2 enum), partition ✓
- `bin/check-methodologist-heartbeat.sh` → kept-as-source (v1) / replaced-by `bin/yitc-v2 nightly` (v2), partition ✓
- `bin/watchdog.sh` → kept-as-source / removed-when L3 (SPEC-0107) built + project migrated ✓
- `bin/auto-session.sh` → kept-as-source (v1) / no v2 replacement by design (CHARTER §6), partition ✓
- `projects/ai-team-framework/bin/check-heartbeats.py` → kept-as-source / removed-when v1 platform retired (out-of-set) ✓

## Cites

- **SPEC-0105** — the v2 methodology-nightly (L1) that replaces v1 nightly enumeration for v2 projects.
- **SPEC-0107** (withdrawn) — the L3 freshness probe; the named `removed-when` trigger for `watchdog.sh`.
- **SPEC-0106** (withdrawn) — L2 product-cron governance, the sibling deferred layer.
- **`v2-automation-grow-l2-product-cron-governance-l3-l`** — the follow-on plan carrying L2/L3.
- **`retirement-procedure.md`** — the orderly removal PROCESS each `removed-when` trigger feeds into.
- **** — the host-partition card that stops the v1 nightly from enumerating v2 projects.
