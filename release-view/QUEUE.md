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

**Size cap:** ≤ 50 tasks. If exceeds, **anti-complexity violation** — defer some to the parking lot or close with rationale, don't grow capacity.

**Order:** picker reads ready ∩ requires-unblocked tasks first by `priority:` field (`high | medium | low`). No multi-axis priority taxonomy.

### Done log

**Location:** `tasks/<id>.yaml` where `status: done` plus required fields `closed_at:`, `commit:`, `probe_passed: true` — **or `probe_passed: deferred`** for a done card that still carries an undischarged deferred probe (the three-state closure contract: the card is done and its shipped work is proven, but a criterion whose proof lands after the ship is not yet discharged; `task close --settle-probe` flips it to `true` when the last one is. Rule home: SPEC-0015 §`probe_passed` is THREE-STATE).

**Retention:** all done tasks stay in `tasks/` directory indefinitely. They're grep-able history. Don't move to a separate archive.

**The done-count is NOT a split trigger** — it is a node-volume count-gate of the class retired at its authoritative home (SPEC-0031 §Node-volume, owner directive 2026-06-06): counts grow with the work, so a fixed number signals nothing. **The sole trigger is observed grep/tooling friction** (a real incident); the `~500`/`~1500` marks are history, not triggers.

> **Dated re-decision — KEEP FLAT; count-branch RETIRED (2026-07-17, done-count 1759).**
> Third firing of the pure-count trigger, and the last — this pass removes the branch that fires.
> Grounds (CHARTER §P1): **F4** — of 3073 `deviation_captured` events the 6 done-log ones are ALL
> the trigger firing itself (601/865/1599/1844/this run); **zero** report real friction (glob+grep of
> 1976 YAMLs = 0.068s). **F3** — a split adds a second location, removes nothing, and at-risk
> `tasks/T-...` citations grew ~620 → 964: cost up, benefit nil. Prior re-decision
> (2026-06-23, done-count 865): keep flat, same grounds; it left `~1500` — which is what re-fired.

### Parking lot

**Location:** `tasks/<id>.yaml` where `status: parked` plus required field `parked_reason:` and optional `return_trigger:`.

**Semantics:** "we considered this, decided not to do now, here's when to revisit". Different from `status: wont-do` (which means "decided not to do, period").

**Review trigger:** the Controller's weekly review scans the parking lot. If return_trigger condition met → status flips to ready.

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

**Park-mid-audit land path (X-0118):** when a task is parked mid-audit — its Stage-8 audit-post is RED (e.g. a kernel-gap false-RED) and the owner parks it rather than forcing a GREEN that does not exist — closure is unavailable (`task close` is RED-blocked) and a standalone `task commit` is refused (`_audit_commit_shift_hazard`). So `bin/yitc-v2 task update --status parked`, when run inside a writing worktree that carries a dirty RED audit record, **self-commits its park record and folds the dirty `decisions/<tid>-audit-(post|consult-*).yaml`** (scoped staging — task YAML + events.jsonl + the task's own audit/consult records only). That leaves the worktree land-clean, so `bin/yitc-v2 land --task T-XXXX` integrates the parked bookkeeping to main with `status: parked` intact (land has no audit/closure RED-gate — the GREEN-gate lives only in `task close`). This is the park sibling of the `task pause` and `task update --status wont-do` self-commits. A plain park with no dirty audit record is unchanged (NON-terminal — it rides a later/batch commit).

**Prematurely-closed UNLANDED task — rework in place, or discard + re-claim; NEVER hand-edit status:** if a task was `task close`d before its land-verify passed (Stage-6 false-green — LIFECYCLE §Stage 9), its `done` + closure commit exist ONLY on the un-integrated branch; `land` never ran, so on **main the task is still `ready`**. Two sanctioned recoveries, neither needing a reopen verb — pick by whether the branch is worth keeping:
- **REWORK IN PLACE (default when the build has converged —, X-0820).** The branch survives: apply the new fix, re-prove it with **`bin/yitc-v2 task test --run`** (admitted on a done card *once the code determines the closure is not on `main`*), commit it via **`bin/yitc-v2 work commit`** (the post-close collateral route — `task commit` still refuses, and points here), then re-audit the current tree with **`bin/yitc-v2 audit post --task T-XXXX --reaudit-after-close`** ( — with `audit consult --reaudit-after-close` past the ceiling) and `land`. When the re-proved deliverable no longer matches the card TEXT the re-audit judges it against, correct that text through the FOURTH leg — **`bin/yitc-v2 task update --old/--new`**, which admits an **`acceptance`-only** field edit on such a card (any other field still refuses, and the row is marked `post_close` so a later reader sees the closure PRECEDED the correction —). Nothing is discarded and no raw git is needed. Admission is **DERIVED, never asserted**: the verb reads what `main` says about the card (`ready` / `in-progress` = closure still branch-local; anything else, incl. undeterminable, refuses fail-closed) — so passing this route a card whose closure LANDED is impossible.
- **DISCARD + RE-CLAIM (when the branch is not worth keeping):** **`worktree park`** (tears down branch+worktree, discarding the premature closure) then **re-claim via `worktree new --task`** — chain-of-custody stays clean.

**ANTI-PATTERN — forbidden:** hand-editing a done card's `status: done → in-progress` — the anti-pattern that desynced chain-of-custody + audit ceiling. A task that genuinely **LANDED** done has **no reopen** — file a NEW task (the LIFECYCLE §Stage 9 "no clean reopen" rule).

## YAML schema (one task per file)
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0028.** `bin/yitc-v2 graph query SPEC-0028`

## Picker logic
<!--AUDIENCE:controller-->

When the Controller, on an owner cue, assembles the ready queue and selects «what to work on» (the Controller SELECTS; a Worker claims ONLY its assigned task id via `worktree new --task` — no generic self-fetch, AGENTS §Orchestrate posture):

1. Read all `tasks/*.yaml` where `status: ready`
2. Filter: exclude where any `requires:` target is incomplete:
   - target = task → `status != done` blocks
   - target = decision → **NON-BLOCKING** (the decision-resolution branch was retired by, gated-safe by the sweep — 0 non-terminal tasks depended on decision-unblock semantics). A decision is a cites-only reference, never a lifecycle-blocking prerequisite — same as a spec. Use `cites:` for decision dependencies.
   - target = spec → **NOT allowed as `requires:` target** — specs are reference artifacts, not lifecycle-blocking. Use `cites:` for spec dependencies.
   Only a task `requires:` target blocks; transitive depth ≤ 3. `cites:` field is informational — NOT a blocking filter.
3. Sort: priority high → medium → low
4. Pick first
5. **Claim it by creating its worktree: `bin/yitc-v2 worktree new --task T-XXXX`** (option B). The claim — `status: ready → in-progress` (`current_stage: Analysis`) +
   the `task_picked` event — is written **inside the new worktree**, so it reaches `main` only
   via `land` (: main changes ONLY via land). `task pick` is a **read-only inspector** —
   it validates a task is claimable and points at `worktree new --task`; it does NOT mutate.
   The previous design (pick flips status on `main` uncommitted, then `worktree new` branches
   from committed HEAD) caused the desync — the worktree never saw the claim. The
   `status` field is still the observable "picked" signal (`task list --status in-progress`,
   after land).

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

> **Triage sweep + window — retrieved (SPEC-0055).** Fetch on demand: `bin/yitc-v2 graph query
> SPEC-0055` (triage VERB: `bin/yitc-v2 triage`). The cadence in the roster stays mandatory.

## What this REPLACES from v1
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0055.** `bin/yitc-v2 graph query SPEC-0055`
