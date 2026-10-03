---
name: realize-on-evidenced-soak-not-just-the-gate
class: discipline
sourced_from: 'Vehicle-1 trial run (attempt) of plan systematic-reusable-craft-lesson-capture-at-closur, 2026-06-19 — an attempted `plan stage realized` surfaced that all 4 postcheck plans were coded realize_ready=true yet NONE had its owner-judged soak EVIDENCED; confirms the convergence-audit hindsight-risk warning (decisions/lesson-capture-trial-convergence-audit-adhoc.yaml) live'
applies_to: 'deciding to finalize a plan postcheck-to-realized (SPEC-0034). Read BEFORE `plan stage realized`. The same shape applies to any coded ready-flag view standing in for a human-judged criterion.'
---

# Pattern: realize on EVIDENCED soak, not just the readiness gate

## Problem

The `postcheck-plans-readiness` view reports `realize_ready: true`, which reads as "go". But that flag
only checks the CODED gates (finalization-ready + retire-on-proof-resolved). The actual
`postcheck → realized` entry is **owner-judged** (SPEC-0034 §realized — "real-data soak confirms
intent"), and the plan's realization-exit names a concrete soak (min-runs + outcomes + an evidence-home
that CITES the runs). A 2026-06-19 sweep found ALL 4 postcheck plans coded-`realize_ready: true` yet
NONE had its soak runs recorded/cited — so a naive realize would FALSELY finalize a plan (and flip its
spec corpus) on an unmet criterion: the exact "shipped/closed-but-not-adopted" class V2 guards
(CHARTER §P3/§P8).

## Solution

1. **`realize_ready: true` is NECESSARY, NOT SUFFICIENT.** Treat it as "the coded gates don't object",
   never as "the soak is done".
2. **Verify the EVIDENCE before realizing:** open the plan's `## Postcheck probe block`, read its
   `min-runs` + `evidence-home`, and confirm the cited soak runs ACTUALLY EXIST (the verdict YAMLs /
   journal events / durable artifacts it names). No citations ⇒ not realize-ready, regardless of the view.
2. **null ≠ done:** "the soak wasn't recorded" = NOT confirmed (the `post-ship-soak-observation` rule —
   graduate on POSITIVE evidence, never on silence).
3. **If the soak is genuinely unmet → do NOT realize.** Either run + record the real soak, or leave the
   plan in `postcheck`. Never force a finalize for momentum (or for trial fuel) — that is the anti-pattern.
4. **Same shape for any coded "ready?" over a human judgement** — the flag answers a NARROWER question
   than the word implies; re-read what it actually checks.

## Refinement — the soak ARRIVES on a schedule set by the carrier's natural frequency (2026-06-21)

A Vehicle-1 batch (10 postcheck plans verified, 3 realized cleanly) showed *why* the gate and the
evidence diverge in time: **a postcheck soak accumulates at the rate its evidence-carrier is naturally
invoked.** The realization-exit names a live-use carrier (a `task_filed`/`task_closed`, a `land_completed`,
an `audit_*_completed`, a `plan check` run); how fast it reaches `min-runs` depends entirely on how often
that carrier fires in normal work.

- **High-frequency carriers self-soak fast.** The `task`, `land`/`worktree`/`plan`, `graph`/`journal`/`view`
  verb-family extractions reached their `min-runs` within hours-to-a-day post-land purely from ordinary
  sessions (e.g. 35+ `task_filed` / 19+ `task_closed`; 136 land/plan carrier events). For these,
  `realize_ready: true` and a genuinely-evidenced soak converge almost together — verify and realize.
- **Low-frequency carriers do NOT self-soak.** An `audit post`-through-the-module carrier (rare), a manual
  bench batch, or a `plan check` over a `scenario_roles`-bearing plan (deliberate) will sit at `realize_ready:
  true` for *days* with zero recorded soak — not because the work is unsound but because the trigger seldom
  fires on its own. Waiting is silent non-confirmation (null ≠ done).

**So:** when a plan's soak-carrier is low-frequency, do not wait for the soak to "happen" — either
**deliberately generate + record it** (run the audit / the bench batch / the `plan check` and cite it), or
leave the plan in `postcheck` with that gap named. Judge realize-timing by *carrier frequency*, not by the
gate flag or elapsed days.

## Anti-pattern

- **Reading `realize_ready: true` as "realize now"** and finalizing on an unproven soak.
- **Forcing a realize** because an owner/controller asked to "close one" without first checking which
  one's soak is actually evidenced — pick the one whose evidence holds, or report that none does.
- **A view/gate whose NAME overstates what it checks** — `realize_ready` should ideally be read
  alongside its definition (coded gates only); if the name keeps misleading, that is a view-naming
  improvement candidate (report-only, not a blocker).

## Cites

- `SPEC-0034` §realized (owner-judged finalization; the postcheck probe block contract).
- `patterns/post-ship-soak-observation.md` (null ≠ clean; graduate on positive confirmations).
- `decisions/lesson-capture-trial-convergence-audit-adhoc.yaml` (the convergence audit whose hindsight-risk this confirms).
- `SPEC-0089` — the reflection discipline; this is its trial run #7 (Vehicle-1 attempt) + run #8 (Vehicle-1 clean realize batch, the §Refinement source).
- `lessons/library-extraction.md` — the sibling already-homed extraction craft (the batch's mechanical lesson declined to duplicate it — correct route).
