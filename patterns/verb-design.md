---
name: verb-design
class: discipline
sourced_from: decisions/-verb-design-doctrine-cli-verbs-as-the-ai-control-s.yaml (consolidates latent / / doctrine)
applies_to: before adding OR changing a CLI verb (`bin/yitc-v2 <verb>`) — the rubric a new/changed verb is checked against
---

# Verb Design — the 5 design aspects of a CLI verb (4 purposes + failure-behaviour)

## Problem

Every substantive repository mutation in V2 goes through a CLI verb, and the CLI is the
**only** durable control surface — it is provider-neutral (CHARTER §Principle 4b), so it is
where guards, journal-marking, and error-prone mechanics belong (NOT in a provider hook).

But «what is a verb actually for?» kept being re-derived ad-hoc each time a new verb was
designed. The expectations — does it guard? does it mark the journal? does it own the unsafe
step? — drifted per verb (failure class #4 accretion). The four purposes already lived latent
across three decisions ( deterministic emit control-points verb owns
staging) but were never stated as one reusable rubric.

## Solution

Check every new or changed verb against these **six design aspects** — the **four PURPOSES** (what
a verb is *for*: it earns its existence by serving ≥1, a strong verb serves several; a verb that
serves *none* is not a verb — see Anti-pattern) PLUS its **FAILURE-BEHAVIOUR** (how it *dies*), the
fifth aspect added by, PLUS its **READ CONTRACT** (what it *costs to answer*), the sixth added
by.

1. **EASE** — one call performs a correct multi-step sequence the AI would otherwise hand-assemble
   (and assemble inconsistently).
2. **ERROR-REDUCTION** — the verb **owns** the error-prone mechanics, so the AI cannot get them
   wrong. (Prior-art: `task commit` owns `git add` staging — — after manual staging
   mis-fired three times.)
3. **JOURNAL-MARKING** — the verb emits its event **deterministically from the CLI**, not from AI
   memory. (Prior-art: the deterministic auto-emit chain — — and `_auto_sync` materializing
   the session log —.) **Delivery-observability corollary (floor-gated verbs — SPEC-0013
   §Delivery-observability):** a verb that is a floor-trigger gate (`FLOOR_TRIGGERS` /
   `graph/floor-trigger-map.md`) MUST *also* make the before-X **contract it consumed** journal-observable,
   so a journal-only delivery-coherence analysis can read *which* contract governed the gate without
   scraping the transient transcript. The signal MUST be a **deterministic P5-honoring projection**
   (derived from the synced invocation × the binding map, or a verb-emitted field set from the binding
   and reconcilable to the invocation) — never a fakeable self-reported second fact. New floor-gated
   verbs inherit this by construction: design it in, don't retrofit.
4. **CONTROL CHOKEPOINT** — the verb is **where guards/checks hang**, and the raw/manual
   equivalent is **forbidden** so the verb is the only path. The behavioral obligation — the AI MUST
   use the verb, never hand-do its work (hand-work skips the journal emit → invisible) — is the
   always-loaded `AGENTS §Verb-execution discipline` norm. (Prior-art: control-points over hooks
   —; `land` as the sole integration path —.)
5. **FAILURE-BEHAVIOUR** — design how the verb **dies**, not only its happy path. Three
   rules: **(a) clean-fail / atomicity** — if it dies mid-way it leaves a CLEAN state (no half-applied
   claim, no stranded caller cwd; incidents: a `task pick` left an uncommitted claim, an early `land`
   stranded the shell in a deleted dir). **(b) input-artifact preconditions** — build on a RECORDED
   artifact, never a hand-typed/invented value (artifacts-as-gates: `task close` requires the recorded
   commit + an audit-post for THAT commit; `task execute` requires an audit-pre bound to the plan).
   Explicit NON-CLAIM: this LOWERS the COST of a cascade (a clean failure is trivially recoverable) but
   does NOT prevent the parallel-tool-call cascade itself — that is harness-level, unreachable from
   verb design ( Slip 3). The aspect is about recoverability, not cascade-prevention.
   **(c) journal-observable refusal** — a verb's *death* (a refusal / abort) leaves a journal trace
   (`gate_refused`), not stderr-only — the death-path mirror of purpose #3 journal-marking. Today
   refusals are `_die` **stderr-only** (zero refusal events in `events.jsonl`), so a gate-hit /
   bypass *attempt* is invisible across sessions. This is **UNIVERSAL** — every verb's every refusal
   path (read-gate REFUSE, identity self-check, stage-correspondence guard, the `land`-conformance
   gate), not one gate. It is **NOT** the «event for telemetry's sake» anti-pattern (below): it
   carries the discipline-analytics signal a transient transcript cannot durably hold — the same
   carve-out the anti-pattern already grants the reconcilable projection, here for the *refusal*
   fact. **Mechanism home (not re-hosted here, P5):** the `gate_refused` event + the closed
   delta→event map live in `plans/verb-vs-manual-execution-discipline-where-a-hand-a.md` (external
   audit cleared the discipline-analytics justification); the event enters the SPEC-0025 catalog when
   that mechanism ships (co-design). This bullet is the **doctrine** line; the plan is the **mechanism**.
   **(d) applicable-route refusal** — a refusal message IS recovery guidance, so the
   route it names MUST be **executable from the state the refusal just detected**. A verb that
   computed that state *in order to* refuse can therefore **distinguish which route applies** — so
   naming an inapplicable one is a design defect, not an unavoidable cost: it spends a full
   round-trip to discover, at the moment the operator is already blocked. Three same-day instances
   (2026-08-06/07) are the prior-art: a deploy rollback guard pointing at the **forward**-deploy form
   (X-0597); a custody-mismatch refusal naming `--repin-ship`, whose own precondition
   cannot hold in the state that produced the refusal (X-0611 corrected by X-0612); and an
   `--owner-reset` basis refusal naming as the exit an **escalation that has already happened**. A
   fourth same-class instance the next day widens only the observed COUNT, not this rule's subject —
   an advisory demanding a `test-not-applicable:` waive token the sole governed field-edit route
   cannot insert (fingerprint
   `task-update-field-edit-cannot-insert-the-waive-token-its-sibling-advisory-demands`, `events.jsonl`
   2026-08-07); the class the journal names there is *guidance naming a route inapplicable in the
   state that produced it*, of which the obligation stated here is the **refusal subset**.
   **BOUNDARY — refusals only:** a case with **no refusal at all** is not a member. The absence of a
   read-only way to re-read a verb's own stage cue (X-0606, fixed by) is a *different*
   concern with its own shipped fix — this sub-rule does **not** stretch into a general obligation to
   offer read-only inspection. **Pointers, not restatements (SPEC-0005 rule 8):** whether the refusal
   leaves a trace is (c) above; whether the refusal should fire at all is (b); which blocks the
   refused caller may self-clear versus must escalate is **SPEC-0121** (`graph query SPEC-0121`).

6. **READ CONTRACT** — design what the verb **costs to answer**, not only what it
   answers. **Cue:** the moment a verb or seam composes MORE THAN ONE journal or card view, it owes
   ONE request-scoped ReadScope at the wiring site, the views it composes stop owning their own
   folds, and it owes a regression pinning folds ≤ 1 per segment and card parses ≤ 1 per card. The
   TELL that you are in this aspect's territory: you are about to add a cache to a view because a
   seam got slow. That is the wrong lever — the seam needs one scope, not N caches. **Rule home:
   SPEC-0190 rule 10** (`bin/yitc-v2 graph query SPEC-0190`), including the exemption carrier and
   what rule 10 retires; not restated here (SPEC-0005 rule 8). Prior-art: / /
    — three one-site fixes, each found by a human waiting, before the rule existed.

Home of the doctrine: this pattern (a how-to rubric, NOT counted in the handbook cap) plus ONE
normative anchor line in AGENTS §When NOT to add a mechanism. The rubric introduces **no new event
and no new mechanism** — it is articulation of doctrine that already exists.

## Stage-work-verb BUILD recipe (by-construction)

A verb that does a **lifecycle stage's work** (a stage work-verb on either axis — the task 9-stage
lifecycle or the plan FSM) is a CONTROL CHOKEPOINT (aspect #4) for that stage. It is built to ONE
fixed recipe, so every new/changed stage work-verb adopts the enforcement BY CONSTRUCTION — never
re-derived per verb (the cross-axis invariant it instantiates is owned by **SPEC-0059**; this is its
verb-build consequence):

- **(a) stage read-check** — the verb REFUSES (BLOCK) unless its stage's docs were fetched **this
  session** (the SPEC-0050 read-check primitive, session-scope).
- **(b) stage-correspondence guard** — the verb REFUSES (BLOCK) unless `current_stage` == its own
  stage (`_require_stage_correspondence`), so it cannot act at the wrong stage.
- **(c) `read_gate_refused` emit on EVERY refusal** — each BLOCK journals a `read_gate_refused`
  event carrying its `kind` (`read-check` | `stage-correspondence` | `verification-exists` — all
  three). This is the verb's failure-behaviour (#5) + journal-marking (#2/#3)
  on the death-path: a gate-hit is analyzable per `kind`, never stderr-only. **Event shape + kinds
  are owned by SPEC-0025 / SPEC-0050** — this recipe POINTS, it does not restate them.
- **(d) two refusal axes verified per verb** — the verb's build verifies BOTH refusal paths:
  unread-docs (a) AND wrong-stage (b) each refuse, and the valid flow PASSES (no false-refuse).

The decomposition **structural pre-pass** that runs alongside is **REPORT-ONLY** — a judgement
heuristic owned by **SPEC-0046**, NEVER a hard block; do not mis-file it as a fourth blocking check.
The three checks (a)/(b)/(c) BLOCK; the pre-pass only reports.

## Example

Real () V2 verbs, by which purpose they serve:

- `task file` — **#1 + #2**: one call allocates the next id, validates the schema, and emits
  `task_filed` — the AI never hand-assembles the YAML or picks an id (which would collide).
- `task commit` — **#2**: runs `git add -A` in the one-task worktree itself, removing the manual
  staging step that mis-staged 3× (the git-pathspec-exclude gotcha).
- `_auto_sync` (verb side-effect, SPEC-0004) — **#3**: materializes the session log into
  `events.jsonl` on every governance verb — capture does not depend on the AI remembering to emit.
- `land` — **#4**: the sole path to `main`; integration checks hang on it and the raw
  `git merge` / push equivalents are not the sanctioned path. The chokepoint is *what makes a guard
  possible*.

Planned applications of the rubric (**not yet shipped** — for illustration only): a `worktree new`
verb (#1+#2 — one call creates branch + worktree off `main`, vs an error-prone hand-typed `git
worktree add`) and a `_require_writing_worktree` write-isolation guard (#4) — /.

## Anti-pattern

- **A pure marker / validator-only verb** — a verb that does no useful work, only stamps a flag or
  checks a condition, is a hook in disguise. If «ensure X before Y» is needed, **extend the verb
  that is already «before X»** rather than add a standalone gate.
- **A new event for telemetry's sake** — adding an event type just to "log that the verb ran" when
  the synced session log already records the real invocation. (Rejected `cli_invoked` §rejected_ideas.)
  **Carve-out (SPEC-0013 §Delivery-observability):** the floor-gated **consumed-contract**
  signal is NOT this anti-pattern when it is a *deterministic P5-honoring projection* (derived from the
  synced invocation × the binding map, not an independently-emitted fact) that answers the
  delivery-coherence audit query the transient transcript cannot — the documented `ideas/cli-invoked-…`
  revisit-trigger, fired by delivery-inspection finding-1 (journal-blind class, N=2). The bar stays high:
  a *fakeable self-reported* "I ran X" event is still the anti-pattern; only the reconcilable projection clears it.
- **A provider hook instead of a verb** — putting the guard/journal logic in a provider-specific
  hook re-introduces provider dependency (CHARTER §Principle 4b) and a second control surface.
- **A verb that re-hosts the routing map (the META-RULE, SPEC-0033)** — a verb that carries its OWN
  copy of *what/when to deliver* (a per-verb routing payload, or a handbook section enumerating routing
  on the side) instead of letting the binding-derived LENS decide (`_build_binding_views` over the single
  `binding:` field — SPEC-0013). The rule: **each verb does its OWN work and emits THAT work's content** —
  a verb is a self-check + an optional post-hint; the what/when routing is the lens, NOT a per-verb
  payload. Consequence to preserve: a stage-bound action has **exactly ONE delivery source** (no
  `stage-entry:<bad>`, no stage-entry co-present with a second source, no relocated gating stage with no
  bundle). `bin/yitc-v2 graph conformance` enforces this one-source self-test **report-at-land** — NOT a
  write-path / fail-closed gate (non-goal #7 / GRAPH not-a-validation-layer).

## Cites

- `decisions/-verb-design-doctrine-cli-verbs-as-the-ai-control-s.yaml` — the codifying decision
- `decisions/-...` — purpose #3, deterministic journal emit (retired manual lifecycle telemetry)
- `decisions/-deterministic-lifecycle-capture-via-task-cli.yaml` — purpose #4, control-points over hooks
- `decisions/-task-commit-owns-artifact-staging-no-manual-git-ad.yaml` — purpose #2, verb owns staging
- `decisions/-auto-sync-journal-on-all-cli-verbs-control-point-s.yaml` — purpose #3, sync as verb side-effect
- `decisions/-write-isolation-closure-path-based-main-write-guar.yaml` — purpose #4, write-isolation guard
- `decisions/-artifacts-as-gates-each-verb-validates-its-input-a.yaml` — aspect #5, failure-behaviour (clean-fail + input-artifact preconditions)
- `specs/SPEC-0033-meta-rule-each-verb-does-its-own-work-the-one-sour.yaml` — the meta-rule (verb does its own work; one-source delivery), code-enforced by `graph conformance`
- `specs/SPEC-0059-universal-stage-contract-and-lifecycle-verb-map-de.yaml` — the cross-axis stage contract the §Stage-work-verb BUILD recipe instantiates (read-check / stage-correspondence / verification-exists kinds → SPEC-0025/SPEC-0050; report-only pre-pass → SPEC-0046, cited in-body)
- `AGENTS.md §When NOT to add a mechanism` — the normative anchor line points here
