# PATTERNS.md — Pattern Catalog

Knowledge patterns extracted from real project work. Each pattern = `patterns/<name>.md` file. This index = catalog.

`patterns/` is V2's **knowledge/reference catalog** — it houses not only positive reusable patterns
(technique / architecture / discipline / observation) but also **methodology lessons**:
rejected/withdrawn methodological options + the why-it's-done-this-way rationale (the role orphaned
when the `decision new` class retired — a spec keeps pure rule-text per SPEC-0005 rule 3, so the
rejected+why half needed a home; see `patterns/methodology-lessons.md`). All of it is non-normative
reference knowledge (`patterns/doc-conventions.md` §Authority boundary) — standing rules live in specs
or handbook prose, not here.

## Schema for patterns/<name>.md

```markdown
---
name: <kebab-case-slug>
class: technique | architecture | discipline | observation | adapter | reference | runbook
sourced_from: <project name либо v1 path>
applies_to: <when к use — concrete trigger>
---

# <Pattern Title>

## Problem
<What goes wrong without this pattern.>

## Solution
<What к do. Concrete, not abstract.>

## Example
<Code либо doc snippet, real if possible.>

## Anti-pattern
<What NOT to do — what people try that doesn't work.>

## Cites
<Related patterns, project decisions.>
```

A `patterns/<name>.md` is USUALLY one pattern-shaped document. It MAY instead be a **curated
multi-lesson catalog** under the same frontmatter + section shape — e.g. `methodology-lessons.md`,
whose §Example holds an accreting list of `### Lesson N` entries. Same node type, same `patterns/`
home; still ONE doc, not a new format.

## Catalog


One row per `patterns/*.md`, alphabetical — the SAME order as `bin/yitc-v2 graph query
--type pattern`, so a completeness/drift check is a literal line-up (diff the two). This
hand-curated table adds the **Purpose** gloss the generated list cannot carry (no `purpose:`
frontmatter field); refresh it against that generated view when patterns are added or retired.

| Pattern | Class | Purpose |
|---|---|---|
| [atomic-state-file-writes.md](patterns/atomic-state-file-writes.md) | technique | Write state files via tempfile + os.replace; prevents partial-write corruption on crash |
| [audit-trail-field-level.md](patterns/audit-trail-field-level.md) | architecture | One audit table at field granularity; audit_update compares old vs new per field |
| [background-session-dispatch.md](patterns/background-session-dispatch.md) | discipline | Worker-dispatch mechanics half of the orchestrate posture — the M2 worker session-identity read-gate anchor, the blessed `bin/yitc-v2 dispatch` launcher, the worker fail-closed self-check, separate-sub-session-only dispatch + full-lifecycle, and the long-command detached-launch recipe |
| [background-session-monitoring.md](patterns/background-session-monitoring.md) | discipline | Controller's land-rhythm / watch / recover half of the orchestrate posture after dispatching background Workers (monitoring read = `journal query --fleet-verdict`) |
| [background-session-operation.md](patterns/background-session-operation.md) | discipline | Controller's how-to for the LAUNCH / selection / coordination half of the orchestrate posture — decompose an authorized batch, plan+pace dispatch waves, select via `--carve-out`, gate cross-chain ordering + sole-controller |
| [batch-operation-resilience.md](patterns/batch-operation-resilience.md) | technique | Per-item try/except + audit-before-business-logic + upsert sync + mandatory end-of-batch report |
| [behavioral-baseline-defaults.md](patterns/behavioral-baseline-defaults.md) | discipline | Seeded cross-project behavioral / UX-safety defaults a new project should not re-derive when authoring user-facing interactions |
| [big-plan-checklist.md](patterns/big-plan-checklist.md) | discipline | 7-probe pre-finalization check for substantive plans; Probe 7's id/deferral checks are MECHANIZED by the `plan check` structural pre-pass (SPEC-0046, ex-SPEC-0040/0037/0012) — only judgement items + links remain |
| [the AI provider-code-mcp-runbook.md](patterns/the AI provider-code-mcp-runbook.md) | adapter | the AI provider Code-specific MCP connect/use commands — the provider binding for working-with-mcp-in-v2 (NON-NORMATIVE) |
| [cli-line-directive-vs-reference.md](patterns/cli-line-directive-vs-reference.md) | discipline | Every AI-facing CLI line must be unambiguously a DIRECTIVE or a REFERENCE — authoring rule for verb output / stage & seed deliveries / "read X" pointers / refusals |
| [<external-auditor>-auditor-runbook.md](patterns/<external-auditor>-auditor-runbook.md) | adapter | <external-auditor> CLI install / update / login / troubleshoot mechanics for the external auditor + owner `<external-auditor>` (host-specific <host-home>; NON-NORMATIVE) |
| [concurrency-gate-inert-skip.md](patterns/concurrency-gate-inert-skip.md) | technique | Speed up a heavy concurrent verify/gate via an observability-based inert skip (land-style re-check-then-fast-forward loops) |
| [consume-verb-output-whole.md](patterns/consume-verb-output-whole.md) | discipline | Read a governed verb's stdout WHOLE — `tail`/`grep`/`head` at invocation discards the verdict/guidance/next-step in the part you clipped; save the full output, select from it afterwards; the contracted `LAND:` token is the one machine-keyed exception |
| [decision-log-format.md](patterns/decision-log-format.md) | discipline | Two-tier markdown decision tracking (operational ledger + chronicle) — portable alternative to YAML-per-entry |
| [deploy-smoke-test.md](patterns/deploy-smoke-test.md) | discipline | Post-deploy headless-browser smoke run + ErrorBoundary webhook for production error capture |
| [design-tool-roundtrip.md](patterns/design-tool-roundtrip.md) | discipline | Absorbing a design edit-set pulled from an external design tool back onto v2 carriers |
| [doc-conventions.md](patterns/doc-conventions.md) | discipline | Rules for creating structured V2 docs (spec / pattern / handbook section / task) — read before Filing/Execution if scope births a new artifact |
| [emergency-mode.md](patterns/emergency-mode.md) | discipline | By-hand fallback for when the V2 tooling ITSELF is broken — entry / run / startup-reading / exit+reconcile; rare escape hatch, fix-the-tool default, >1/30d → Review audit |
| [error-boundary.md](patterns/error-boundary.md) | architecture | React class component wrapping App; renders fallback UI instead of white screen on render-tree crash |
| [error-friction-tracking.md](patterns/error-friction-tracking.md) | discipline | Intent-vs-actual accumulation layer — deviation_captured events (event-only by default) + routine aspect-audits + promotion-only errors/E-XXXX case files |
| [event-emit-only-audit-post.md](patterns/event-emit-only-audit-post.md) | discipline | Absorbing the Stage-8 audit-post category mismatch when a ship = a single events.jsonl emission (adoption probe), not an accompanying code diff |
| [fsm-enum-whitelist.md](patterns/fsm-enum-whitelist.md) | architecture | StrEnum + transitions dict + service validator; single status_transitions audit table |
| [host-server-surface-contract.md](patterns/host-server-surface-contract.md) | reference | How to work cleanly with the CURRENT server's host/kernel surfaces (registry.yaml, <host-home> router, host auto-committer, coordination store) |
| [inspection-criteria-roster.md](patterns/inspection-criteria-roster.md) | reference | Part 1 — the freshness-hashed living criteria of the inspection roster (cadence values + operational-hygiene weekly checklist + per-theme T1–T10 lens-checklists) |
| [inspection-criteria-roster-navigation-map.md](patterns/inspection-criteria-roster-navigation-map.md) | reference | Companion — the umbrella navigation map of every recurring check (check → theme → cadence → how-to-run → rule-home), across the continuous-reflex / system-inspection / apex / consumer-local tiers |
| [inspection-criteria-roster-run-and-lenses.md](patterns/inspection-criteria-roster-run-and-lenses.md) | reference | Part 2 — the inspection run-mode, the cross-theme method (M1–M9), the foundations and the architecture-drift lens (SPEC-0120 split) |
| [inspection-criteria-roster-themes-delivery-outcome-adoption.md](patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md) | reference | Part 3 — the T2 / T4 / T5 / T6 / T8 per-theme lens-checklists, served and freshness-hashed alongside part 1 (SPEC-0120 split) |
| [inspection-triage-launch-runbook.md](patterns/inspection-triage-launch-runbook.md) | discipline | Owner-invoked combined inspection + test-triage LAUNCH procedure sequencing the existing pieces |
| [local-first-consumer-contribution.md](patterns/local-first-consumer-contribution.md) | discipline | Consumer needs a kernel shape that doesn't exist yet: proceed local-first → signal the kernel → bless-from-example → reconcile |
| [methodology-lessons.md](patterns/methodology-lessons.md) | discipline | Curated catalog of methodology lessons — rejected/withdrawn options + the why-rationale (role orphaned when `decision new` retired); consulted at Stage-1 Analysis prior-art sweep. NOT deviations (errors/E-XXXX) / NOT instructions (specs) |
| [onboarding-a-person-onto-yitc.md](patterns/onboarding-a-person-onto-yitc.md) | runbook | Non-technical-user primer + operator runbook for handing a production project to a non-technical human |
| [onboarding-onto-yitc-frictions-log.md](patterns/onboarding-onto-yitc-frictions-log.md) | runbook | Accumulated onboarding frictions log + per-migration meta-analysis, split out of the onboarding runbook (append live, newest last) |
| [onboarding-onto-yitc-runbook.md](patterns/onboarding-onto-yitc-runbook.md) | runbook | Standing a project up on YITC — ONE runbook, two branches (greenfield · brownfield-migration), shared import-completeness core |
| [owner-list-intake-working-order.md](patterns/owner-list-intake-working-order.md) | discipline | Working order for processing an owner-stated LIST of to-dos / behaviour changes in one intake |
| [plan-finalization-runbook.md](patterns/plan-finalization-runbook.md) | discipline | Driving a plan postcheck → realized (or a terminal partial/rejected/cancelled) — read before `plan stage realized` |
| [plan-lifecycle.md](patterns/plan-lifecycle.md) | discipline (RETIRED) | RETIRED into `specs/SPEC-0034` (single normative home for the plan lifecycle); file is a tombstone pointer |
| [post-ship-soak-observation.md](patterns/post-ship-soak-observation.md) | discipline | Observe shipped work in real operation after closure (latent-defect classes invisible at ship) — observe the SHIP, don't gate it |
| [realize-on-evidenced-soak-not-just-the-gate.md](patterns/realize-on-evidenced-soak-not-just-the-gate.md) | discipline | Finalize a plan on EVIDENCED soak, not just a coded readiness flag standing in for a human-judged criterion |
| [repeated-work-lens.md](patterns/repeated-work-lens.md) | discipline | The seven classes of doing the same work twice in product code (N+1, re-reads, re-fetch, unbounded loops, repeated scans, frontend re-trigger loops, no-watermark workers) — severity rubric, remedy shapes, report shape + the pasteable monthly `sweep` declaration; used at detection (the sweep) and prevention (a task's Plan stage) |
| [recovery-runbook.md](patterns/recovery-runbook.md) | discipline | Rolling back a bad-but-green land — semantic corpus corruption with working tooling (not broken tooling, not dead-weight removal) |
| [retirement-procedure.md](patterns/retirement-procedure.md) | discipline | Orderly removal of dead weight — analysis ( detector) → warn → disable → analyze → remove; manual-first; PEP 387 analog |
| [session-tooling-discipline.md](patterns/session-tooling-discipline.md) | discipline | Operational tool-call discipline that keeps the worktree + verb flow from corrupting state |
| [single-carrier-generated-views.md](patterns/single-carrier-generated-views.md) | architecture | Collapse a tangled delivery into ONE authoritative carrier + generated views, cut over atomically (the win is DELETING a model, not adding one) |
| [soft-delete.md](patterns/soft-delete.md) | architecture | SoftDeleteMixin (deleted_at) + partial unique indexes; enables recovery without 409 on recreate |
| [spike-mode.md](patterns/spike-mode.md) | discipline | Runbook for a caged throwaway spike end to end — the yitc-ops declaration, the four cage atoms (three CHECKED, 4d DISCIPLINE), shared-vs-own sandbox, the stale-router entrance, and the knowledge-not-code discard exit |
| [task-decomposition.md](patterns/task-decomposition.md) | discipline (RETIRED) | RETIRED 2026-06-02 — absorbed into the decomposition spec (now `specs/SPEC-0046`); file is a tombstone pointer |
| [test-isolation-strategies.md](patterns/test-isolation-strategies.md) | technique | Three async-SQLAlchemy strategies (rollback / recreate / savepoint) with tradeoff matrix |
| [time-decay-scoring.md](patterns/time-decay-scoring.md) | technique | Exponential decay tied to event timestamp (not recompute time); half_life as a dynamic setting |
| [timezone-utc-database.md](patterns/timezone-utc-database.md) | architecture | UTC in DB with DateTime(timezone=True) + server_default now; convert only at the display layer |
| [trial-methods.md](patterns/trial-methods.md) | discipline | Catalog of plan-stage `trial` run modes + accumulated lessons; the mode choice is recorded in the plan, not here |
| [ui-enhancement.md](patterns/ui-enhancement.md) | discipline | Where a UI delta lives in the v2 model — designing / reviewing a user-facing affordance on a consumer app |
| [ux-destructive-operation-safety.md](patterns/ux-destructive-operation-safety.md) | discipline | Three-layer defense (confirm-with-consequences / undo via soft-delete / disabled-with-tooltip) with application matrix |
| [ux-general-principles.md](patterns/ux-general-principles.md) | discipline | Universal web UX rulebook — fundamentals / mobile / desktop / error prevention / forms / data integrity |
| [v1-freshness-watchdog-retirement-map.md](patterns/v1-freshness-watchdog-retirement-map.md) | observation | Deciding the fate of each per-project v1 freshness / watchdog / nightly surface as projects migrate onto yitc-v2 |
| [validate-deviation-task-premise-at-analysis.md](patterns/validate-deviation-task-premise-at-analysis.md) | discipline | Validate a deviation-framed task's PREMISE at Stage-1 Analysis before designing the fix |
| [verb-design.md](patterns/verb-design.md) | discipline | The 5 design aspects of a CLI verb (4 purposes + failure-behaviour) — the rubric before adding or changing a verb |
| [verification-protocol.md](patterns/verification-protocol.md) | discipline | Owner-invokable 12-dimension verification (self-check + external independent) for task / decision / milestone closure |
| [working-with-mcp-in-v2.md](patterns/working-with-mcp-in-v2.md) | discipline | Provider-neutral MCP governance — connecting, keeping the connected set clean, capturing external writes |

### Generated-vs-hand — decided NOT NOW (per CHARTER §P1)

The card weighed generating this table from `patterns/` frontmatter (per
`single-carrier-generated-views`) against P1 F3 (it would remove the hand-maintained table).
Resolution: **not now.**

- **The completeness/drift concern is ALREADY met by an existing generated view** —
  `bin/yitc-v2 graph query --type pattern` lists every pattern from the graph index and cannot
  drift. "Is anything missing?" needs no new mechanism; the answer is the diff above.
- **F3 — net addition, not removal.** The only thing this table adds over that generated list is
  the curated **Purpose** column, which has no frontmatter carrier (`applies_to` is a longer,
  different-altitude "when to read" trigger, not a one-line purpose). Generating the table would
  require a NEW `purpose:` field across all 51 files + a `graph build` generator codepath + a
  conformance drift-check — more machinery than the ~51-row table it replaces.
- **F4 — disproportionate for a non-normative reference catalog.** The drift (~monthly, a handful
  of rows) is real but cheaply fixed by this refresh + the generated-view diff; a generator earns
  its keep only if hand-refresh proves to recur painfully. Revisit then, not on principle.

