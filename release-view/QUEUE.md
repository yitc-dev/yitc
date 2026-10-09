<!-- GENERATED — identity-agnostic release view of the methodology handbook. Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->

# QUEUE.md — Queue Model
<!--AUDIENCE:core-->

Three-bucket model.

## Buckets
<!--AUDIENCE:core-->

### Active queue

**Location:** `tasks/<id>.yaml` where `status:` is one of: `ready | in-progress`.

> **`blocked` is LEGACY / read-tolerated — NOT an active-queue state.** No verb writes it
> (`TASK_FILING_STATUSES`, `bin/lib/task.py` — `task update --status` cannot reach it) and no doctrine
> prescribes it; the waiting-on-owner park is `task pause --reason owner-wait` (§Verb routes). It
> survives only as a tolerated value on the READ side (`TASK_OPEN_STATUSES` / `TASK_LIST_STATUSES`), so
> a legacy card carrying it still lists and closes. Do not prescribe it; see §Verb routes.

> **Filename convention:** `tasks/<id>.yaml` is shorthand. Canonical on-disk form is `tasks/T-NNNN-<slug>.yaml`, where `<slug>` is title kebab-cased (first 50 chars, lowercase, non-alnum → `-`). Allocated by `bin/yitc-v2 task file` per `_template.yaml`. Both forms used interchangeably in this doc — same single-file-per-task storage.

**Size cap:** ≤ 50 tasks whose moment has come — `in-progress` cards plus `ready` cards whose every task `requires:` target is done (a terminal `wont-do` target is not waited on; this is the picker's requires-unblocked filter, §Picker logic). A `ready` card still waiting on a task `requires:` target is reported as waiting and is not counted. If exceeds, **anti-complexity violation** — defer some to the parking lot or close with rationale, don't grow capacity.

### Done log

**Location:** `tasks/<id>.yaml` where `status: done` plus required fields `closed_at:`, `commit:`, `probe_passed: true` — **or `probe_passed: deferred`** for a done card that still carries an undischarged deferred probe (the three-state closure contract: the card is done and its shipped work is proven, but a criterion whose proof lands after the ship is not yet discharged; `task close --settle-probe` flips it to `true` when the last one is. Rule home: SPEC-0015 §`probe_passed` is THREE-STATE).

**Retention:** all done tasks stay in `tasks/` directory indefinitely. They're grep-able history. Don't move to a separate archive.

**The done-count is NOT a split trigger** — it is a node-volume count-gate of the class retired at its authoritative home (SPEC-0031 §Node-volume, owner directive 2026-06-06): counts grow with the work, so a fixed number signals nothing. **The sole trigger is observed grep/tooling friction** (a real incident); the `~500`/`~1500` marks are history, not triggers.

> **KEEP FLAT — the count-branch is RETIRED.** Every firing of the pure-count trigger was
> the trigger firing itself; none reported real friction. Do not re-add a count-based split branch.

### Parking lot

**Location:** `tasks/<id>.yaml` where `status: parked` plus required field `parked_reason:` and optional `return_trigger:`.

**Semantics:** "we considered this, decided not to do now, here's when to revisit". Different from `status: wont-do` (which means "decided not to do, period").

## State transitions
<!--AUDIENCE:core-->

```
ready → in-progress (when a Worker — or the Controller self-executing on owner say-so — picks up)
ready → parked (defer before pickup — parking-lot semantics)
in-progress → done (closure stage complete + probe pass)
in-progress → parked (decision to defer mid-task)
parked → ready (return trigger fired)
any active (not done) → wont-do (with rationale in YAML; stays in tasks/ — done is shipped history, terminal)
```

No other transitions. No "in-review", "under-audit", "awaiting-critic", "released". Those concepts don't exist in V2 — `in-progress` covers all of them. **Waiting-on-external / waiting-on-owner is likewise NOT a status transition** : it is `task pause --reason owner-wait`, which writes `paused_at` + the resume contract ONTO the in-progress card (the card stays `in-progress`) and surfaces at session start — see §Verb routes. The 9-stage lifecycle is sequential within a single executing session (a Worker, or the Controller self-executing), not tracked as separate task states.

**Verb routes:** park / unpark / wont-do run via `bin/yitc-v2 task update --status …` (`--note` alone = amendment note); `ready → in-progress` is the claim (`worktree new --task`), `in-progress → done` is `task close`.

**Waiting on owner / external — `task pause`, never `blocked` (the SINGLE HOME of this answer).** A task waiting on an owner answer (the SPEC-0126 §4 non-blocking-batch park) or on anything external is parked with **`bin/yitc-v2 task pause --reason owner-wait`**: it writes `paused_at`/`paused_reason` + the resume contract (`resume_from` / `next_action`) onto the still-`in-progress` card, self-commits, and SURFACES at session start as the WAITING-ON-OWNER signal. The `blocked` status is **NOT** that carrier and is prescribed by NOTHING: no verb has ever written it (`TASK_FILING_STATUSES` excludes it, so `task update --status` cannot reach it) — zero observed usage in the system's whole history, so per CHARTER §P1 F4 the blocked-leg verbs are NOT added; the reachable `task pause` already covers the need (F1), and what this removes (F3) is the verbless prescription itself. `blocked` survives only as a read-tolerated legacy value (§Active queue). **A Controller-cued clean STOP is the sibling reason `--reason controller-wait`** : a worker whose brief ends in «STOP and report» records it the same way, and that row is TERMINAL — `journal query --dispatch-status/--fleet-verdict` read it as `paused(controller-wait)` / needs-decision naming the recorded `next_action` (never `working`), the dispatch in-flight guard yields to it without `--force`, and `bin/yitc-v2 dispatch --resume T-XXXX [--brief <delta>]` relaunches with the recorded contract heading the worker's task-specific brief. Hitting a genuine need `task pause` cannot express = capture a deviation → verb extension.

**Park-mid-audit land path (X-0118):** when the owner parks a task whose Stage-8 audit-post is RED, its park record still reaches main — read the recipe before parking: `bin/yitc-v2 graph query rare-task-recovery-recipes` (lead «Park-mid-audit land path»). The one land-side exception stays named here: `land` refuses a `status: wont-do` branch that carries unaudited authored content (`wont-do-unaudited-ship` — rule home SPEC-0103).

**Prematurely-closed UNLANDED task — rework in place, or discard + re-claim; NEVER hand-edit status:** a task `task close`d before its land-verify passed is `done` only on its un-integrated branch — on **main the task is still `ready`**. It has two sanctioned recoveries and needs no reopen verb — read the recipe before acting: `bin/yitc-v2 graph query rare-task-recovery-recipes` (lead «Prematurely-closed UNLANDED task»).

**ANTI-PATTERN — forbidden:** hand-editing a done card's `status: done → in-progress` — the anti-pattern that desynced chain-of-custody + audit ceiling. A task that genuinely **LANDED** done has **no reopen** — file a NEW task (the LIFECYCLE §Stage 9 "no clean reopen" rule).

## YAML schema (one task per file)
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0028.** `bin/yitc-v2 graph query SPEC-0028`

## Picker logic
<!--AUDIENCE:controller-->

When the Controller, on an owner cue, assembles the ready queue and selects «what to work on» (the Controller SELECTS; a Worker claims ONLY its assigned task id via `worktree new --task` — no generic self-fetch, AGENTS §Orchestrate posture):

- **Eligible:** `status: ready` and no incomplete `requires:` target. Only a task `requires:` target blocks (`status != done`): a decision id there is NON-BLOCKING, a spec id is NOT allowed there, and `cites:` is informational — field rules: `bin/yitc-v2 graph query SPEC-0028`. `bin/yitc-v2 task pick T-XXXX` reports one card's claimability; it is a read-only inspector.
- **Order:** priority high → medium → low, pick first (`bin/yitc-v2 task list --status ready` prints the ready cards in that order).
- **Claim it by creating its worktree: `bin/yitc-v2 worktree new --task T-XXXX`.** The claim — `status: ready → in-progress` (`current_stage: Analysis`) + the `task_picked` event — is written **inside the new worktree**, so it reaches `main` only via `land` (mechanics: AGENTS-SESSIONS §Writes happen in a worktree).
- How deep a `requires:` chain may run is set where the chain is cut — a decomposition authoring rule, not a picker check: `bin/yitc-v2 graph query SPEC-0046`.

**Order:** picker reads ready ∩ requires-unblocked tasks first by `priority:` field (`high | medium | low`). No multi-axis priority taxonomy.

No queue-saturation logic, no parallel-cap, no cap-per-account, no rate-limit awareness. Solo *author* — but concurrent sessions are expected : the invariant is **one active claim per task id** (a task id has at most one in-progress claim / `task/T-XXXX` worktree), NOT "one task at a time" globally. **Different** tasks may run concurrently in separate worktrees; the per-task-id guard only rejects a second claim of the *same* task.

## Re-review triggers
<!--AUDIENCE:controller-->

> **Single home — the roster (plan `unify-revizia-all-checks-under-one-construct-singl`).**
> The recurring-check list (weekly / monthly / per-session operational checks + the T1–T8 system
> inspection themes + continuous reflexes + the quarterly anti-complexity apex) is no longer carried
> here as a parallel list. It lives single-home in the inspection criteria roster — the umbrella
> navigation map (every check → theme → cadence → how-to-run → rule-home) in
> **`patterns/inspection-criteria-roster-navigation-map.md`**, and the living lens-checklists it indexes
> in **`patterns/inspection-criteria-roster.md`** (SPEC-0120 split). Read it there. The
> Controller's review cadence is unchanged; it is now sourced from the
> roster, not this section (CHARTER §P5 — no double-home). No automated re-review; no cron jobs Day 1.

**Review trigger:** the Controller's weekly review scans the parking lot. If return_trigger condition met → status flips to ready.

> **Triage sweep + window — retrieved (SPEC-0055).** Fetch on demand: `bin/yitc-v2 graph query
> SPEC-0055` (triage VERB: `bin/yitc-v2 triage`). The cadence in the roster stays mandatory.
