---
name: trial-methods
class: discipline
sourced_from: specs/SPEC-0035 (plan stage `trial`) + plans/add-a-controlled-real-data-trial-stage-between-pla.md (proposing plan §4) + plans/fresh-session-task-dispatch-context-economics-hand.md (dogfood runs 1-2 — the motivating incident)
applies_to: entering a plan's `trial` stage (`plan stage trial`) — picking a trial mode and baking the per-plan `## Trial protocol` section into the plan (SPEC-0035 rule 3). Reference catalog of trial methods + accumulated lessons; the mode choice is recorded in the plan, not here.
---

# Trial Methods — catalog of plan-stage `trial` run modes + lessons

> **Discipline pattern (reference catalog).** This is the **single home for reusable trial
> methods / lessons** (SPEC-0035 rule 6). It RECOMMENDS how to run a `trial`; it does NOT
> restate the normative `trial`-stage rules — those live in **SPEC-0035** (the spec) and
> **SPEC-0034** (the plan FSM). On conflict, the spec wins (`patterns/doc-conventions.md`
> §Authority boundary). Fetch the norms: `bin/yitc-v2 graph query SPEC-0035`.

## Problem

A mechanism-class plan — one that births a spec / verb / flow — can pass a text audit
(`plan check`) and still carry design edge-cases that are invisible on paper. The
mechanism's real behaviour only surfaces when it actually runs: concurrency races,
unreliable free-text gates, isolation flaws, false-signal reads, latent bugs.

Real incident (the motivating one): dogfooding the `fresh-session-task-dispatch` plan
surfaced a concurrency double-claim (→), an unreliable gate-at-land via free text,
a supervision journal-isolation flaw, false-HANG reads on long external steps, and a real
`task commit` bug self-found by a dispatched session (→). **`plan check` found none
of them** — none was visible to text-only audit. Accepting such a plan on paper alone ships
the design unconverged, and the correction then happens *post-accept* (the expensive
re-accept → re-audit → re-finalize loop on an already-`accepted` spec).

The `trial` stage answers this: run the planned mechanism in a controlled way on real(-ish)
data until the design stops changing, **before** `accepted`. This file catalogs HOW to run
it — the methods + the lessons learned.

## Solution

At `plan stage trial` entry, decide eligibility (SPEC-0035 rule 2), pick a mode below, and
**bake the choice + criteria into the plan's `## Trial protocol`** (SPEC-0035 rule 3). Both
modes produce the SAME product: design knowledge (edge-cases) folded back into the plan +
its draft specs. Neither mutates production data (SPEC-0035 rule 4).

### Mode A — controlled / run-to-convergence

- **What it is:** run the planned flow on real(-ish) data, run after run, correcting the
  plan + draft specs in place after each run, until a run produces no further changes.
- **When to pick:** the mechanism can be exercised in an emulated or manually-stepped form
  that is reviewable + rollbackable; you want a tight, repeatable loop you fully control.
- **How to run:** define the run shape (inputs, the slice of the flow exercised); run it;
  log raw observations to `events.jsonl`; fold each edge-case back into plan + specs; repeat.
  Exit on the SPEC-0035 rule 5 floor (≥1 journaled run + a trial-summary in the plan + plan
  & specs unchanged across the last 2 cycles) PLUS the per-plan baked criteria, owner-judged.
- **Real example:** `fresh-session-task-dispatch` run-1 (gate-at-land) and run-2
  (full-completion incl. land) — controlled hand-runs of the dispatch mechanism that caught
  the gate-at-land unreliability (n=2 empirically) and the `task commit` bug.

### Mode B — in-vivo / live backlog

- **What it is:** push real, current backlog tasks manually through the working system and
  observe how the design settles under genuine load — the mechanism runs on production work
  rather than an emulation.
- **When to pick:** the mechanism is already wired enough to carry live work, and the
  edge-cases you fear are load- / concurrency-shaped (only real parallel sessions surface
  them). Requires the safety envelope to be settled FIRST (baked into the protocol).
- **How to run:** route live tasks through the mechanism under a bounded safety envelope;
  observe concurrent behaviour; capture raw observations to the journal; fold findings back
  into plan + specs. Same SPEC-0035 rule 5 exit floor + per-plan criteria + owner judgment.
- **Real example:** the 2026-06-03 run — `parallel-work` + dispatch under live concurrent
  sessions, where the mechanism actually turned on production work rather than being emulated.

### Mode C — sandbox-clone rehearsal (one-shot operations: migrations / cutovers)

- **What it is:** for a plan whose execution is a ONE-SHOT real-world operation (a brownfield
  migration, a cutover, a host reconfiguration), build a full SANDBOX CLONE of the target (git clone
  + copy of untracked load-bearing state, secrets REDACTED to shape-only — SPEC-0099) plus COPIES of
  the host files the operation edits (registry, workspace files, crontab dumps), then execute the
  ENTIRE runsheet against the clone — including the REAL governed verbs (`-C <clone> init`,
  worktree+land cycle) — recording per step: journaled evidence, wall-clock timing, and a VERIFIED
  undo (execute the undo on the clone at least once). Output: the CONVERGED runsheet + a
  mechanism-transition map (per mechanism: added / removed / transferred-where / interaction edges).
- **When to pick:** the real run is one-shot and hard to roll back cheaply (live prod, multi-user
  repo, host coupling); the design risk is ORDERING/interaction, which text audit cannot exercise.
  Production is NEVER mutated (the rule 3-4 envelope holds by construction — the clone absorbs
  every write; host edits happen on copies).
- **How to run:** clone + copy state → execute runsheet steps in order, timing each → run the real
  consumer verbs against the clone (they surface real gate refusals: locus receipts, init guards,
  scaffold withholds) → fold every surfaced ordering fix back into the runsheet/plan (fix-first) →
  undo-drill (git revert / restore-from-copy executed once) → external pass over map + runsheet;
  iterate until a pass surfaces nothing new. Same SPEC-0035 rule 5 exit floor + owner judgment.
- **Real example:** the aiseller migration trial (2026-07-11, `trial_run` run 1, plan
  `migrate-aiseller-onto-yitc-v2-v1-incumbent-heavies`): the clone rehearsal surfaced a CRITICAL
  missed live-writer (a second human's OWN v1 night-cycle enumerating the project from HIS
  workspace file — invisible to the registry flip), 3 verb-ordering gates (consumer-locus session
  start before `-C init`; `--help` scan per locus; post-sweep re-init to deliver a withheld
  scaffold), and proved ALL migration mechanics run in seconds — the day budget is content work.
  Runbook home for the migration-specific procedure: `patterns/onboarding-onto-yitc-runbook.md`
  §Sandbox-clone trial rehearsal (this section carries the reusable trial METHOD only).

### Dual convergence analysis — the independent external read at exit (SPEC-0035 rule 5)

Whichever mode (A or B) produced the runs, the **convergence assessment at exit is dual**: the
trial-summary records BOTH the **primary AI self-analysis** (the verdict against the baked criteria)
AND an **independent EXTERNAL convergence read**. The external read applies CHARTER §Principle 4a
auditor-independence to the convergence JUDGMENT itself — it catches a primary blind-spot of the
shape "the single running session declared its own design converged." (Normative rule home:
SPEC-0035 rule 5; this is the rule-6 METHOD carrier for HOW to run it.)

- **How to run it (reuse `audit adhoc` — no new verb, CHARTER §Principle 1):** after the runs have
  settled and the primary trial-summary is drafted, invoke
  `bin/yitc-v2 audit adhoc --slug <plan>-trial-convergence` (SPEC-0036) with a prompt asking the
  external auditor to judge convergence **INDEPENDENTLY**: derive the verdict from the baked trial
  criteria (rule 3) + the journal run-refs, treating the primary trial-summary as **context/carrier
  only** (not the thing it ratifies). The verdict + recommendation save to
  `decisions/<slug>-audit-adhoc.yaml` and emit the audit events.
- **Fold the two reads together:** record in the trial-summary whether the two reads **AGREE**. Two
  independent reads converging strengthens the signal; a **divergence** (primary says "converged",
  external says "not yet", or vice-versa) is a question for the owner to weigh — an **INPUT, never a
  blocker**. Trial exit stays owner-judged and is **NOT externally gated** (the SPEC-0035 rule 5
  boundary): the read informs owner judgment, it does not gate the `trial → accepted` transition.
- **Not the accept-gate.** This exit-time convergence read is distinct from the package-level
  `plan check` (FULL) at the `accepted`-gate — a separate, later audit of the assembled package; the
  dual read neither duplicates nor replaces it.
- **Real example (the method's own dogfood):** the `forward-propagation-adoption-trigger-disposition-r`
  plan dual-read its trial convergence on 2026-06-09 — the primary controlled-emulation trial summary
  was independently re-read via `audit adhoc`
  (`decisions/forward-propagation-trial-convergence-audit-adhoc.yaml`, YELLOW): the two reads **agreed**
  on outcome-set completeness + rule-5 convergence and **diverged** only on an infra-only scope claim,
  which a follow-up consult then adjudicated GREEN. The divergence was the load-bearing signal — a
  single primary read would have missed the scope issue.

### Carrier boundary (editorial rule — SPEC-0035 rule 6)

Hard boundaries, no parallel carrier (CHARTER §Principle 5):

- **`patterns/trial-methods.md` (this file)** carries ONLY reusable methods + lessons.
- **`events.jsonl`** carries ONLY raw trial-run observations.
- **the plan** carries ONLY the baked `## Trial protocol` + the exit-facing trial-summary
  (the verdict against the baked criteria).

Moving raw run observations into the plan, or methods/lessons into the spec, is FORBIDDEN.
This is the editorial discipline that keeps the four carriers (journal / plan / this pattern
/ spec) non-overlapping.

### Lessons — observed convergence criteria (distilled)

> **Distilled from real runs (NOT invented).** These are **recommendations** — how to read
> "is this trial converged?" — distilled by **** from accumulated `trial_run` journal
> evidence (≥6 plans soaked through `trial`; `bin/yitc-v2 journal query --type trial_run --limit 0`). The **normative**
> exit floor stays in **SPEC-0035 rule 5**; on conflict the spec wins. A rule-worthy slice MAY
> later migrate up to the spec — until then these are pattern-level recommendations only.

**The observable floor (baseline — SPEC-0035 rule 5, restated, NOT re-legislated here):** a
trial may exit only with (i) **≥1 journaled `trial_run`**, (ii) a **trial-summary** in the plan
(the verdict against the baked criteria), and (iii) **plan + draft specs unchanged across the
last 2 trial cycles** — PLUS the per-plan baked criteria, owner-judged. Everything below is how
that floor showed up *in practice* + the reusable reads that the real runs taught.

**Observed convergence criteria — distilled recommendations:**

1. **Stop-changing is the load-bearing signal: ≥2 consecutive runs that produce ZERO edits to
   plan + draft specs.** The floor's "unchanged across last 2 cycles" leg is what actually fires
   in practice — read it as *two clean cycles*, not one. **Cite:** the `per-stage-external-audit-question-templates`
   trial (mode B-in-vivo) — runs 1–2 produced template-text edits, run 3 was a clean GREEN
   cycle, run 4 re-applied the *same* texts and produced no edits → the rule-5 floor leg was
   explicitly logged satisfied. Journal: `events.jsonl#ts=` (clean cycle 1)
   + `events.jsonl#ts=` (clean cycle 2, "plan + draft specs unchanged across
   last 2 trial cycles — SPEC-0035 rule-5 floor leg satisfied"). **The confirmation run is not
   ceremony** — a single clean cycle can be luck; the second proves it.

2. **A converged trial drives the defect-find rate toward zero across runs — but the
   per-iteration text must stay STABLE while it still catches real defects.** Convergence is
   "no NEW design changes", not "no findings ever". A gate whose own text keeps changing every
   run has not converged; a gate whose text is fixed and whose findings have gone to zero has.
   **Cite:** same trial — the P3 gate text was **STABLE across 4 passes while catching 3 real
   defects** (`events.jsonl#ts=`), then later runs drove findings to zero
   without further text change. Read the two together: stable-instrument + falling-find-rate =
   converged; either one alone is not enough.

3. **Re-derivation beats one-shot: a converged design must survive a frontier CHANGE mid-trial,
   not just a static snapshot.** If a trial's subject is recomputed-vs-cached state, the
   convergence test is whether the mechanism *recomputes correctly when the world moves under
   it* — a one-shot carve that looked right on the opening snapshot can be wrong twice by the end.
   **Cite:** the `parallel-work-preparation-carve-out-picker` trial (mode A, shadow-live-queue) —
   a mid-computation land changed the frontier and birthed a new task, the currency/recompute rule
   fired, and the run logged "a one-shot carve would have been wrong twice"; the claim-lag and
   verifier-after-settled substrate rules were validated live, not on paper. Journal:
   `events.jsonl#ts=` (run 1) + `events.jsonl#ts=`
   (run 2, historical-replay confirmation).

4. **For load/concurrency-shaped (mode B in-vivo) trials, convergence = the deviation profile
   STABILIZES (recurring classes named, no NEW class, no new ceiling case) AND guardrail
   violations stay at zero across runs/batches.** An in-vivo trial does not exit because nothing
   went wrong — real work throws flaky tests and dup filings. It exits when the *set* of deviation
   classes stops growing batch-over-batch and every guard held. **Cite:** the
   `orchestrate-posture` trial (mode B in-vivo, batches 1–3) — the same deviation classes recurred
   and stabilized (flaky-land-verify under parallel lands, cross-session duplicate filing) while
   **`guardrail_violations: 0`** held every batch and the one audit-ceiling halt resolved
   by-design (governance STOP → owner consult), not by a guard breach. Journal:
   `events.jsonl#ts=` (batch 1) + `events.jsonl#ts=`
   (batch 2) + `events.jsonl#ts=` (batch 3, "guard_rail_violation: false").

**Per-mode note (A vs B).** Mode A (controlled run-to-convergence) reads convergence as
criteria 1+2+3 — a *tight repeatable loop* where the clean-cycle and re-derivation signals are
the whole story. Mode B (in-vivo live backlog) adds criterion 4 — under genuine load you also
need the deviation profile to stop growing and the safety envelope to hold; "no edits this run"
alone is weaker evidence when each run sees different live work, so the stable-deviation-profile
read is what substitutes for a perfectly repeatable loop.

### Lesson — a harness with more access than the real actors validates an unobeyable rule

*(distilled 2026-08-11, plan `close-the-spike-mode-safety-floor-to-data-carried-`, trial cycle 5.)*

A trial harness usually runs with every capability at hand — both ends of a pipeline, both databases,
every credential — because that is what makes it convenient to write. The real actors the rule governs
do not have that. So a harness can demonstrate a rule working while the party actually obliged to obey
it could never perform the step at all.

The live case: a rule required the completeness proof to enumerate the SOURCE of a copied dataset. The
harness held source and copy simultaneously and the check passed cleanly. But the real proof runs after
the restore, inside the sandbox, and a sibling rule gives live-system read permission to the export step
ALONE — so the proof could never build that enumeration. The rule was unobeyable, and the run was green.

**The check:** when a cycle passes, ask what the HARNESS had that the obliged actor does not — access,
timing, both sides of a boundary, a credential, a second copy. Read what the run ASSUMED, not only what
it printed. A green that rests on borrowed capability is not evidence about the rule.

## Example

A baked `## Trial protocol` in a plan (what entering `trial` writes INTO the plan, per
SPEC-0035 rule 3) — this catalog is what you consult to fill the `mode` line:

```markdown
## Trial protocol
- mode: A (controlled run-to-convergence) — chosen because the dispatch flow can be
  hand-stepped reviewably; load-shape edge-cases are not the primary risk here.
- probe targets: gate-at-land reliability; concurrency double-claim; commit-path bugs.
- exit criteria: SPEC-0035 rule 5 floor + plan & both draft specs unchanged across 2 runs.
- safety envelope: emulated dispatch only; no production task status mutated.
- eligibility rationale (rule 2b): paper audit cannot surface the gate/race classes —
  prior-art: the run-1/run-2 incident.
```

The raw runs go to `events.jsonl`; the verdict-against-criteria goes back into the plan as
the trial-summary; only the *reusable* lesson (if any) migrates here.

## Anti-pattern

- **Accumulating raw runs in the plan or in this file.** Raw observations live ONLY in
  `events.jsonl` (carrier boundary). The plan keeps the exit-facing summary; this file keeps
  only the distilled, reusable lesson.
- **Pre-filling §Lessons with speculative criteria.** Criteria are distilled FROM real
  trials, not invented up front — inventing them is the v1 speculative-accretion
  failure this whole methodology fights.
- **Treating `trial` as a mandatory gate on every plan.** It is owner-invoked and eligible
  only for mechanism/behavioural plans whose convergence cannot be honestly text-audited
  (SPEC-0035 rule 2). A prose/docs plan takes the skip path `specs → accepted`.
- **Building an orchestrator / supervisor / autonomous loop to "run" trials.** `trial` is a
  manual Build/Review practice run with existing tooling — NO new session type, dispatcher,
  or detector (SPEC-0035 rule 8 / CHARTER non-goals #1/#7).
- **Mutating production data during a trial.** Forbidden — only emulation/modulation or
  reviewable + rollbackable manual execution (SPEC-0035 rule 4).

## Sibling modes — which bounded mode you are actually in

The plan-stage `trial` is ONE member of a family of THREE bounded operating modes. They are
distinguished by WHAT is bounded, and picking the wrong one wastes the entry:

- **`patterns/trial-methods.md` (this file)** — a PLAN's `trial` stage: a controlled real-data
  practice run of a mechanism before the plan is accepted. Bounded by the plan's baked
  `## Trial protocol` + the SPEC-0035 rule-5 exit floor. Owner-invoked.
- **`patterns/spike-mode.md`** — a THROWAWAY debugging exploration against a sandbox stack: reproduce
  a bug, measure a behaviour, try an approach. Bounded by the cage; its exit is knowledge, never
  landed code (SPEC-0172). Unlike a `trial` it is not a plan stage, produces no plan artifact, and
  proves nothing about a mechanism's convergence.
- **`patterns/emergency-mode.md`** — the by-hand fallback for when the TOOLING itself is broken.
  Bounded by owner-authorization + retro + the frequency check. Never a routine bypass.

## Cites

- `specs/SPEC-0035` — plan stage `trial` (the normative spec; this file is its rule-3/rule-6 home)
- `plans/add-a-controlled-real-data-trial-stage-between-pla.md` — the proposing plan (modes A/B §4, full deliberation)
- `plans/fresh-session-task-dispatch-context-economics-hand.md` — the dogfood runs (motivating incident)
- `specs/SPEC-0034` — the plan FSM (`trial` between `specs` and `accepted`)
- `specs/SPEC-0027` — `implementation_plan` / resume-contract (the bake-the-protocol analog)
- `tasks/` — distilled the observed convergence criteria into §Lessons (≥2 real trial journal runs; return_trigger fired)
- `CHARTER.md §Principle 5` (single source of truth — the carrier-boundary basis), `§Principle 1` (anti-complexity), `§Principle 3` + `§Principle 8` (Done = Adopted)
- `patterns/doc-conventions.md` — §Authority boundary (pattern recommends; spec/handbook own norms)
- `patterns/spike-mode.md` (SPEC-0172) + `patterns/emergency-mode.md` — the two sibling bounded
  modes, §Sibling modes above
