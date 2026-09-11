---
name: inspection-criteria-roster-navigation-map
class: reference
sourced_from: <durable artifact> (SPEC-0120 byte-axis re-split of patterns/inspection-criteria-roster.md — part 1 re-crossed the 63000-byte must-split ceiling after the split; the umbrella navigation map + orientation re-home here VERBATIM per SPLIT-never-delete, keeping the code-read living criteria — the `CADENCE` values, the operational-hygiene weekly checklist, the T1–T10 lens-checklists — in part 1 so bin/lib/inspection.py criteria_ref/tier hashing + parse_cadence are UNAFFECTED) + SPEC-0120 (durable-doc size governance) + patterns/inspection-criteria-roster.md (part 1 — the living-criteria home this map indexes) (the single-home unify-revizia drain this roster serves)
applies_to: the umbrella ROSTER MAP — the single navigation index mapping every recurring check → theme → cadence → how-to-run → rule-home (continuous reflexes · an operational-hygiene pointer · the T1–T10 system-inspection index · the anti-complexity apex · consumer-local product-adaptation themes). The freshness-hashed LIVING CRITERIA it indexes (the `CADENCE` values, the operational-hygiene weekly checklist, the T1 / T3 / T7 / T9 / T10 lens-checklists) stay in part 1 (`patterns/inspection-criteria-roster.md`), with the T2 / T4 / T5 / T6 / T8 lens-checklists in part 3 (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`); the run-mode + cross-theme method + foundations + architecture-drift lens are part 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`). This is a navigation/index doc — it POINTS, it does not restate rules (P5 / SPEC-0005 rule 8). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — the umbrella navigation map (companion)

> **What this IS:** the **umbrella navigation map** half of the inspection criteria roster — one row per
> recurring check mapping **check → theme → cadence → verb|view (how to run) → rule-home**. The
> freshness-hashed **living criteria** it indexes live in **part 1**
> (`patterns/inspection-criteria-roster.md`): the `CADENCE` values, the **operational-hygiene
> weekly checklist**, and the **T1 / T3 / T7 / T9 / T10 per-theme lens-checklists** — with the
> remaining **T2 / T4 / T5 / T6 / T8** checklists in **part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split). The run-mode + cross-theme method +
> foundations + architecture-drift lens are the co-equal **part 2**
> (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split). Split from part 1
> by **** (byte-axis re-cross); content VERBATIM (SPLIT-never-delete).

> **Single-home invariant (plan `unify-revizia-all-checks-under-one-construct-singl`):**
> this roster (all parts together) is the SOLE living list of recurring checks. `QUEUE.md §Re-review
> triggers` is a POINTER here (no parallel list); `patterns/inspection-triage-launch-runbook.md` READS
> this roster (it does not re-host it). This map POINTS at each rule's home — it never restates the rule
> (P5 / SPEC-0005 rule 8).

## The unified roster map (the single living map of every recurring check)

One row per recurring check: **check → theme → cadence → verb|view (how to run) → rule-home**. Every
pre-unification `QUEUE.md` trigger folds in here under its tier; every T1–T10 system theme has its row
in §System-inspection. No check lives in two homes.

### Tier — Continuous reflexes (always; not scheduled)

| Check | Theme | Cadence | How to run (verb) | Rule-home |
|---|---|---|---|---|
| Deviation capture (the moment something is not as it should be) | T5 meta-loop | always (reflex) | `bin/yitc-v2 event deviation_captured …` | /; SPEC-0056 |
| Dissonance flag (a contradiction with an existing rule/artifact) | T1/T5 | always (reflex) | capture + raise | CHARTER §P7; SPEC-0056 |
| File-on-observation (adjacent/cross issue noticed mid-task) | — | always (reflex) | `task file` / `cross request` | AGENTS §Filing rule |

### Tier — Operational hygiene (weekly) → part 1

The weekly operational-hygiene checklist (parking-lot · blocked-queue · MEMORY GC · postcheck-ready ·
overdue-recheck · lifecycle-integrity · read-gate · canary · cron-drift · soak-scan · bench-refresh ·
lesson-generalization · journal-hygiene · …) is a **freshness-hashed living checklist** and lives in
**part 1** (`patterns/inspection-criteria-roster.md` §Operational-hygiene weekly checklist) — `inspect
record --tier weekly` hashes that section there. Read it there.

### Tier — System inspection (T1–T10; monthly, themes rotated)

Each theme's **how-to-run = the launch runbook** (`patterns/inspection-triage-launch-runbook.md` —
dual-track, blind-first); each theme's **living lens-checklist = the `### T<n>` section in part 1 or
part 3** — **T1 / T3 / T7 / T9 / T10** in `patterns/inspection-criteria-roster.md`
§Per-theme lens-checklists, **T2 / T4 / T5 / T6 / T8** in `patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`
(SPEC-0120 split). Every `§T<n> checklist` reference in the table below resolves in
whichever of the two parts holds that theme; `inspect record --theme T<n>` resolves it the same
way and hashes THAT part. One `inspection_completed` event per theme per run
(SPEC-0025 schema; SPEC-0057 §6).

| Theme | What it examines | Cadence | How to run | Rule-home |
|---|---|---|---|---|
| **T1** Doc↔code coherence | docs + code consistent + non-contradictory (P7; #9 drift); coverage both ways; «no silent gaps»; drift-possibility; rule→test roll-call vs the ledger | monthly (rotated) | runbook + §T1 checklist | SPEC-0057; SPEC-0165 |
| **T2** Instruction↔doc fidelity + delivery/readiness | what we TELL the AI == the canon; delivery promised↔journal↔log; readiness via read-gate | monthly (rotated) | runbook + §T2 checklist | SPEC-0057 |
| **T3** AI-execution fidelity | does the AI follow the workflow (git/worktree/land/commit) + ship non-regressing tested changes; 20-class list; boundary-watch; output-quality | monthly (rotated) | runbook + §T3 checklist | SPEC-0057 |
| **T4** Outcome / cost-effectiveness | are we commanding right for the result AND is it worth it (owner time/trust/friction + cost-to-value); context-economy | monthly (rotated) | runbook + §T4 checklist | SPEC-0057 |
| **T5** Meta-loop health | does detect→triage→closure + the inspection system itself RUN and CLOSE; ceiling pattern-mining; postcheck-aging; roster-currency; MEMORY GC | monthly (rotated) | runbook + §T5 checklist | SPEC-0057 |
| **T6** Operational integrity | tests + RED-GREEN, backup/archive, data/state integrity (`events.jsonl`/graph), reproducibility/recovery, deps, `land`. **Security is NO LONGER a standalone T6 subject** — it is carried by the profile-gated **Production-readiness** lens row below, which asks each project only what its own derived profile requires instead of asking every project the same security question regardless of stage | monthly (rotated) | runbook + §T6 checklist | SPEC-0057 |
| **T7** Anti-complexity / bloat + generalization | the methodology's own WEIGHT (handbook size, rule/decision count, injection cost, retirement candidates) + doc/code layering + generalization lens | monthly (rotated) | runbook + §T7 checklist | SPEC-0057 |
| **T8** Adoption (done=adopted) | do shipped V2 capabilities actually get INVOKED in real work (P8 shipped-but-not-invoked) | monthly (rotated) | runbook + §T8 checklist | SPEC-0057 |
| **T9** Capability graduation & adoption | the kernel↔consumer capability PORTFOLIO — is a candidate ripe to GRADUATE into a kernel offering (kernel lens) / for THIS project to ADOPT or BUILD-local (project lens, `-C`)? portfolio decision ONLY — NOT re-hosting T6/T7/T8 health/reuse/adoption | monthly (rotated) OR quarterly | runbook + §T9 checklist | SPEC-0057 |
| **T10** Real-work observation loop | the cross-project worker×auditor PAIR (provider×model×effort) observation — which AI configurations run at what verdict-mix + sample-size across ALL v2 projects, to steer methodology evolution / recommend a pair / size hardware. FINDINGS not scores (§4 fence): read pairs against their own sample-size, NEVER a universal «best pair» | monthly (rotated) OR quarterly (revizia cadence) | `bin/yitc-v2 graph query observation-rollup` (kernel) + §T10 checklist | SPEC-0057 §4; SPEC-0135 |
| **Architecture-drift** (report-only lens — NOT a T1..T10 slot; runs recorded via a `run_ref`-tagged `inspection_completed`, not `inspect record --theme`, see part 2 §Architecture-drift lens) | the engine corpus's CODE conformance to SPEC-0080 evolution principles (size/duplication/unrealized-seam) | monthly (rotated) | runbook + §Architecture-drift lens (part 2) | SPEC-0080 / SPEC-0081 |
| **Production-readiness** (report-only lens — NOT a T1..T10 slot; the SIBLING of the Architecture-drift row above, recorded the same way via a `run_ref`-tagged `inspection_completed`) | what THIS project's own derived growth profile requires and its `yitc-ops.yaml` does not answer — the SPEC-0119 rule-39 gap register, read against the profile snapshot the run acted under | **monthly**, TIME-BOXED to **20 minutes**, and SINCE-LAST-RUN: the watermark is this project's last `inspection_completed` for this lens, so a run reads only what changed since it. **CAPPED — at most 1 profile-mismatch item + 2 top-risk items filed per project per run** (SPEC-0198 rule 7); the cross-project rollup renders FIRST. A run with nothing to file RECORDS "no gap" EXPLICITLY — a silent run and a clean one must never read the same | `bin/yitc-v2 [-C <repo>] debt` (read the rule-39 gap line) + `bin/yitc-v2 [-C <repo>] profile`, then `inspect record` | SPEC-0198; SPEC-0119 rule 39; SPEC-0100; SPEC-0057; |

### Tier — Anti-complexity apex (quarterly)

| Check | Theme | Cadence | How to run | Rule-home |
|---|---|---|---|---|
| v1-pattern accretion return (is V2 becoming v1?) | T7 | quarterly | T7 deep run + displacement re-measure | SPEC-0052 / SPEC-0057 |
| Roster-currency — «is the inspection list itself stale?» | T5 | quarterly | T5 roster-currency lens → owner cue for a refresh cycle | §T5 checklist (part 1); SPEC-0057 §3 |

### Consumer-local product-adaptation themes (a consumer grows its OWN rows — POINTER, not restated)

Every tier above is a **KERNEL** recurring check — the engine inspecting its own methodology corpus. A
**consumer** project grows its OWN project-local inspection themes ON TOP of these, declared in the
`inspection.themes[]` section of its `yitc-ops.yaml`. Such a theme **ADAPTS a kernel T1–T10 lens
APPROACH to the PROJECT realm** — the METHOD travels, the engine themes do not (a consumer's own
revizia inspects its own domain/docs, never the engine's T1–T10). It stays an ordinary declared theme,
**NOT a new category, frame, runner, event, or sink**. This roster only POINTS at the rules — it never
restates them (P5 / SPEC-0005 rule 8):

- **Product-adaptation framing (NON-NORMATIVE):** **SPEC-0057 §9** (the product-adaptation note).
- **The consumer theme declare-shape (incl. the `sweep` probe kind):** **SPEC-0160 rule 12** (rule 12
  moved there with the SPEC-0093 section-schema split — a bare `rule 12` resolves to SPEC-0160; the
  carrier framework + declare-or-waive stance stay SPEC-0093's).

**Product-adaptation examples** (illustrative — each ADAPTS a kernel lens approach to the project realm;
none is a kernel roster row):

| Consumer-local theme (example) | Adapts the APPROACH of | Probe kind | Cadence |
|---|---|---|---|
| `design-canon-health` — design-token / layout adherence across the local design canon | T1 doc↔code coherence (canon ↔ product surfaces) | **`sweep`** | monthly |
| content-freshness / UX-copy consistency | T1/T2 fidelity (what we ship ↔ the canon) | `sweep` | monthly |
| `repeated-work` — the seven classes of doing the same work twice (N+1, re-reads, re-fetch, unbounded loops, repeated scans, frontend re-trigger loops, no-watermark workers) across the product's own code; checklist + report shape home: [`patterns/repeated-work-lens.md`](repeated-work-lens.md) | T4 context economy (read amplification — kernel counters there, hand-run here) | **`sweep`** | monthly |
| a graph/journal query a consumer runs over its OWN corpus | T8 adoption (the check IS a query) | `view` | per declared |

**The `sweep` cadence row — a probe KIND, not a kernel check.** A consumer product-realm theme whose
check is a hand-run audit over local-canon surfaces (not a `graph query <view>`) declares a **`sweep`**
probe rather than a `view:`, and carries a cadence tier like every roster row (§The cadence model, part 1). The
probe-KIND shape, its fail-closed rules, and how a run executes/emits all home in **SPEC-0160 rule 12**
+ **SPEC-0057 §2/§6** — this roster only names the kind, it does not restate them.

**The offered consumer inspection kit (OFFERED, non-mandatory —).** The pieces above compose
into a kit a consumer may OPT INTO via its `yitc-ops.yaml` — never a mandatory pipeline, never a gate.
Nothing here is a new mechanism; the kit is just the name for three existing, additive surfaces used
together:
1. **Product-theme declaration** — declare a `sweep` (or `view`) theme in `inspection.themes[]`
   (SPEC-0160 rule 12); a consumer with none simply waives (declare-or-waive, fail-closed).
2. **Report-only sweep-payload budget** — a `sweep` run measures the byte-size its `surfaces:` glob
   (optional `against:`) would inline and carries a report-only `sweep_payload` block on the emitted
   `inspection_completed` (an advisory print), warning BEFORE a hand-run revizia — or inlining those
   surfaces into an `audit adhoc` consult — overruns the auditor's payload timeout (the X-0275 class on
   the sibling adhoc path). **Report-only, never a gate**; tune/disable via
   `YITC_INSPECT_SWEEP_PAYLOAD_WARN_BYTES` (`<=0` disables).
3. **Task-tied evidence** — `inspect record --theme <slug> --tracks primary,external --task T-NNNN` ties the run to a task so a
   card whose AC names an `inspection_completed` probe renders its proof in the audit-post packet.

Adds **NO** new event kind / verb / spec / runner / cron / classifier / sink — the kit rides the
existing `inspection_completed` and the existing `inspect record` verb (the parent plan's hard
anti-complexity blockers held). Manual-first is unchanged (SPEC-0057 §2): running the sweep by hand +
recording it IS the cadence.

> **Run-mode, cross-theme method (M1–M9) & inspection foundations → part 2**
> (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split).
>
> **The T2 / T4 / T5 / T6 / T8 lens-checklists → part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`, SPEC-0120 split).
