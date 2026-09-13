<!-- GENERATED — identity-agnostic release view of the methodology handbook. Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->

# LIFECYCLE.md — 9-Stage Task Lifecycle
<!--AUDIENCE:core-->

## Two flow types
<!--AUDIENCE:core-->

- **Non-hygiene (substantive):** all 9 stages.
- **Hygiene fast-path:** stages 1, 5, 6, 7, 9. Skip 2-3-4-8 (no plan, no audits).

**Fast-path eligibility — a governance-surface-touching change is NOT hygiene.** A change whose
diff touches a **SPEC** (`specs/*.yaml`), a **PINNED-TEST surface** (the SPEC-0077 pinned last-green
verify-path — `bin/yitc-v2 graph query SPEC-0077`), or an **always-loaded SEED** (a
`HANDBOOK_READ_ORDER` handbook file or the floor trigger-map) is **fast-path INELIGIBLE** — by
definition NOT hygiene. It takes the **substantive** path (all 9 stages, both audits), so any
last-green **rebaseline** it performs carries a fresh audit-post (satisfying SPEC-0077's A-prime
own-homework-close). Classification is **MECHANICAL** — path/surface-based, **fail-closed** on any
touched governance surface (when in doubt, substantive). *(Self-exemplifying: editing this
`HANDBOOK_READ_ORDER` file is itself substantive.)*
  - **Incidental-staleness carve-out.** A pinned check that is only INCIDENTALLY stale — not
    semantically touched by this change — MAY still escalate to substantive to REBASELINE it,
    WITHOUT implying semantic ownership of the pinned subject; record the incidental staleness as
    the **rebaseline reason** (the `--rebaseline` reason / commit body).

**Doctrine — blast-radius (not diff-size) sets gate weight.** The governing principle
behind the eligibility rule above: how many gates a change pays is set by its **blast-radius**, not by
its line count. A spec / pinned-test / always-loaded-seed touch is high-blast-radius at ANY size — so
the fast-path-eligibility rule above is its INSTANCE, and a one-line seed edit paying the substantive
path is **proportionate, not a tax**. There is **no size-based lighter tier** — that is exactly the v1
tier-classifier CHARTER §6 forbids ("No tier classification: every substantive task gets audit-pre +
audit-post"). The **sibling** application of the same "blast-radius, not size" principle is
**SPEC-0072** (effort-tier routing) on a DIFFERENT axis — blast-radius sets the *effort tier* (a
worker's model/effort) there, the *gate weight* here (one principle, two axes). The real relief for a
recurring "this is disproportionate" complaint is **ergonomics + resolving it BY CITATION to this
doctrine**, never cutting a gate.

> **Plan analog:** the PLAN lifecycle has no single fast-path like this — its obligations
> vary by plan SHAPE, not by one binary switch. See **§Plan lifecycle → Plan routing** for
> how they differ (trial opt-in · big-plan checklist weight · spec-corpus finalization audit).

## Routing — which carrier (plan vs one-or-a-few tasks vs followup)
<!--AUDIENCE:core-->

§Two flow types chooses the flow WITHIN a task; this chooses the CARRIER first — plan,
one-or-a-few tasks, a staged followup, or a plain record. Pick the LIGHTEST carrier that fits;
a heavier one is not "safer", it just pays audits the change does not need (the X-0074 trigger).

**Run the sieve, don't ask.** The carrier is a SELF-APPLIED decision — a mechanical sieve
answered from the change's OWN properties, NOT a fork to pose to the owner (X-0213): S0
record-only fact → no-worktree capture (`event`/`followup`) · S1 needs a standing-rule SPEC
corpus / fidelity-audited multi-task cut / trial-on-real-data → PLAN · S2 else → one-or-a-few
bare TASKS (a mid-work dodelka staged via `followup add`, drained later). Full procedure —
lightest-first order, per-branch conditions, escalate-a-genuine-decision-not-the-carrier rule:
**`bin/yitc-v2 graph query SPEC-0140`**. Batch-drain working-order: `patterns/owner-list-intake-working-order.md`.

## The 9 stages
<!--AUDIENCE:core-->

### Stage 1 — Analysis

**Goal:** understand the task before doing anything.

> **Retrieved — moved to SPEC-0032**. The full ordered Stage-1 procedure (prior-art grep incl. the
> plan-layer sweep → cite-the-proof → standing-rule?→SPEC-0005 → decomposition?→SPEC-0046 → read-cited →
> file-clarification; + Done-when a/b/c) is **delivered at the Analysis stage-entry** ( — the claim
> `worktree new --task` IS Analysis-entry; SPEC-0032 binds `stage-entry:Analysis`, delivered by `stage Analysis`).
> Fetch via `bin/yitc-v2 graph query SPEC-0032`. (Supersedes always-loaded retention — same model as §Stage 3.)

**Done when:** can name (a) what exists already, (b) what changes, (c) the smallest concrete edit (full criteria in SPEC-0032).

### Stage 2 — Filing

**Goal:** task exists in `tasks/<id>.yaml` with the canonical schema.

If task already filed (you're picking up an existing one) — skip to Stage 3.

**Filing checklist:**
- ID: `T-<NNNN>` (sequential, allocated via CLI)
- Title: one line, present tense imperative
- Class: `feature | fix | refactor | docs | infra | hygiene`
- Scope: bulleted list of concrete changes
- Acceptance: list of verifiable criteria — **each MUST include probe evidence** (event emitted, state checked, measurable effect)
- Cites: list of related task IDs / spec IDs / decision IDs

> **Before decomposing, confirm the carrier** — is this change a plan, one-or-a-few tasks, or a
> staged followup? See **§Routing — which carrier**. Decomposition cuts a change ALREADY routed to a
> plan/task; it does not decide whether a plan was warranted.

**Decomposition discipline (SPEC-0046 — delivered at the Analysis stage-entry; supersedes
SPEC-0040/SPEC-0037/SPEC-0012 with the four cutting refinements + the plan-split criterion
+ the verifier-after-settled requires rule).** Before
filing — or RESHAPING — a task, cut by **ONE provable claim per accept-unit** (not by size), and carry any
deferral as a tracked task, never prose. If the unit proves >1 claim, **SPLIT** and encode the order via
`requires:`. A **VERIFIER** unit (one that checks a SETTLED subject — a spec self-test / coherence check /
conformance run) runs only AFTER its subject landed; at decomposition its `requires:` MUST name every
writer of its subject — machine-readable, never prose/operator memory (§A3). SPEC-0046 binds
`stage-entry:Analysis` only — the decompose decision (decide-how + split) is
an Analysis decision; filing is capture, not a delivery moment ( completes). Read it via
`bin/yitc-v2 graph query SPEC-0046`.

**Done when:** YAML committed to `tasks/<id>.yaml`. CLI emits `task_filed` event.

**If task scope creates a new artifact** (decision / spec / pattern) — consult `patterns/doc-conventions.md` for structure guidance before authoring.

### Stage 3 — Plan (substantive tasks only)

**Goal:** explicit implementation plan before code touched.

> **Retrieved — SPEC-0027 — stage-DELIVERED at Plan entry** : `bin/yitc-v2 stage Plan --task T-XXXX` delivers SPEC-0027 in its stage bundle (the lifecycle delivery axis — a lighter pointer, NOT a floor-trigger; this stage stays non-gated). Also fetchable on demand: `bin/yitc-v2 graph query SPEC-0027`.

**Done when:** `implementation_plan:` field non-empty in the task YAML.

### Stage 4 — Audit-pre (substantive tasks only)

**Goal:** external auditor checks plan against scope.

- **Recommended path** : `bin/yitc-v2 audit pre --task T-XXXX [--full]` — wraps the configured external-audit adapter, applies V2 universal lens + per-stage overlay, parses verdict, saves to `decisions/T-XXXX-audit-pre.yaml`, emits events. SPEC-0001 self-test + audit-loop ceiling enforcement automatic.
- **Manual fallback (emergency only)**: ONLY if the `audit` verb/CLI is unavailable (emergency-mode — `patterns/emergency-mode.md`): invoke the external auditor directly in the concrete adapter form declared in `bin/audit-config.yaml` (the provider binding's home), with a hand-authored prompt; save verdict YAML manually (SPEC-0001 quoting hazards). NOT a routine alternative — the verb is the obligatory path (AGENTS §Verb-execution discipline); a custom prompt goes through `audit adhoc --prompt`/`-f`, not a hand fallback.
- Verdict: GREEN / YELLOW / RED / ABORT
- **GREEN** = proceed to Stage 5
- **YELLOW** = absorb findings inline (within the audit-loop ceiling — SPEC-0124 §Audit-loop ceiling), then proceed
- **RED** = STOP. Re-plan or escalate to owner. Never silent-loop.
- **ABORT** = STOP. Auditor unavailable or output malformed. Surface to owner, do not proceed without a verdict.

**Two ways to absorb a YELLOW finding (and how each meets the audit-loop ceiling):**

- **(a) Edit the plan.** Changing `implementation_plan:` **re-fingerprints** it, so the prior
  audit-pre no longer matches the plan ( `require-audit-pre-matches-plan`); `task execute`
  REFUSES until a fresh `bin/yitc-v2 audit pre` re-verifies the changed plan. That re-audit **is a
  new absorption pass** — it is what generates a pass, so it counts against the ceiling.
- **(b) Record without changing the plan.** When the finding is a residual that does NOT warrant
  re-planning, record it into the **existing** audit-pre verdict YAML (`absorbed:` / `notes:` fields,
  per AGENTS §Saved audit result schema) via **`bin/yitc-v2 audit pre --task T-XXXX --absorb "<text>"`**
  — the governed field-edit route, never a hand-edit of the governed YAML (a hand-edit skips
  the deterministic `audit_finding_absorbed` emit, so the absorption is invisible to later sessions).
  It runs no auditor and leaves `verdict:` / `passes:` / `plan_fingerprint:` untouched; it refuses a
  non-YELLOW record (RED/ABORT = STOP, GREEN has nothing to absorb) and a custody-re-pinned one. The
  plan text is unchanged → no re-fingerprint → no forced re-audit → this does **not** generate a new pass.
  The SAME route serves a **plan-gate** residual — `bin/yitc-v2 audit pre --plan <slug> --gate <id>
  --absorb "<text>"`, gate id per SPEC-0124 §Plan-target parity — on identical terms.

**Ceiling interaction, and what happens AT the ceiling:** the ceiling counts **re-audit passes**, and
mode (a) is the only thing that generates one (mode (b) closes a residual without a re-audit, so it
neither starts nor evades a pass). It is homed in **SPEC-0124 §Audit-loop ceiling**; what happens ONCE
IT IS REACHED, in **SPEC-0204** — the Controller records ONE typed decision per residual (`audit
decide`), then exactly ONE pass runs on them (`--on-decisions`); a dispatched Worker never decides, it
HALTS naming its residual fingerprints. Consult episodes, `--owner-reset` and `--reopen` are RETIRED
and REFUSE with that pointer. Never silent-loop.

**Done when:** audit verdict GREEN or YELLOW-absorbed. Event `audit_pre_completed` emitted with verdict + finding count.

### Stage 5 — Execution

**Goal:** code change matches plan.

> **Retrieved — SPEC-0027.** `bin/yitc-v2 graph query SPEC-0027`

**Done when:** code on disk, plan items checked off mentally.

### Stage 6 — Tests

**Goal:** project tests green with the new code.

> **Retrieved — SPEC-0027 — stage-DELIVERED at Tests entry** : `bin/yitc-v2 stage Tests --task T-XXXX` delivers SPEC-0027 in its stage bundle (same delivery axis as Stage 3 Plan — a lighter pointer, NOT a floor-trigger; stays non-gated). Also fetchable on demand: `bin/yitc-v2 graph query SPEC-0027`.

**Done when:** test runner exits 0 with output captured — verify via `bin/yitc-v2 task test --run` (the full subprocess suite = land's CANDIDATE leg; a bare `pytest tests/` skips script-style `__main__` tests → false-GREEN). A green here is NOT the land verdict: `land` verifies TWO legs (SPEC-0077) and the pinned last-green leg is not run here.

### Stage 7 — Commit

**Goal:** atomic commit landing the change.

- **One logical change-set per task — not literally one git object.** The CANONICAL
  model of a task's commit footprint on `main`: (a) the **ship commit(s)** for the task's diff
  via `task commit` (aim for one; it is callable ×N — Stage 7); (b) a small **closure-record
  commit** (status:done + probes — Stage 9 bookkeeping); (c) `land`'s own **bookkeeping commits**
  (reconcile events+graph, `land_completed`). "Atomic" means one coherent change-set + one storage
  format (CHARTER §Principle 5 — single source of truth governs storage FORMAT/parser/journal, NOT
  git-commit count), not a single git commit. AGENTS §Stage 7 + CHARTER §P5 cross-reference HERE.
- Format: `<type>(<task-id>): <subject>\n\n<body>\n\nfrom: <durable artifact>`
- `from:` cites durable artifact: task YAML (`tasks/T-XXXX-*.yaml`) / decision YAML / spec YAML / handbook section / **materialized journal entry (`events.jsonl#source_ref=<locator>` or `events.jsonl#ts=<ISO>`)**. NOT raw provider session log.
- Tests must be green BEFORE commit (T4 rule)
- Commit body includes Co-Authored-By trailer

**Done when:** `git log -1` shows commit, exit 0.

### Stage 8 — Audit-post (substantive tasks only)

**Goal:** external auditor confirms shipped diff matches plan.

- **Recommended path** : `bin/yitc-v2 audit post --task T-XXXX [--commit SHA] [--full]` — same wrapper as Stage 4 plus auto-fetches commit diff via `git show`, includes in prompt. **The subject is the task's RECORDED commit, never HEAD** — `--commit` when given, else the last `commit_landed` for this task, and it REFUSES when neither resolves ( chain-of-custody: audit a recorded commit, not a guess). Only `--reaudit-after-close` targets HEAD, by its own contract. It also refuses when the resolved subject provably carries **no authored content** — every path in it lifecycle bookkeeping — naming the empty subject rather than spending a pass on a diff with none of the card's work in it (a ship that genuinely has no diff says so with its own overlay flag).
- **Manual fallback (emergency only)**: as Stage 4 (emergency-mode `patterns/emergency-mode.md`; the verb is the obligatory path per AGENTS §Verb-execution discipline), plus diff context in the hand-authored prompt.
- Verdict: GREEN / YELLOW / RED / ABORT
- **GREEN** = proceed to Stage 9
- **YELLOW** = file follow-up task for findings, proceed — OR absorb INLINE (mode-a): fix +
  `task commit --absorb` + re-audit of the new commit (counts a pass against the §audit-loop ceiling)
- **RED** = STOP. Never silent-pass. Fix the named cause IN SCOPE and re-audit the new commit
  (`task commit --fix-red` —, admitted only on a commit carrying authored content; when the RED's ONLY fix is the card's own record, its `--card-repair` arm —, admitted instead on proof the audited ship it rides on exists), else revert or escalate (`blocked-on-land`, SPEC-0103) when the cause is out-of-scope or environmental. AT the audit-loop ceiling the route is **SPEC-0204**, not a consult or a reset (§Stage 4 ceiling).
- **ABORT** = STOP. Auditor unavailable or output malformed. Surface to owner.

**Deferred-adoption edge cases — one family, five variants named here** (SPEC-0036's overlay table is the full, authoritative set — it also carries `--external-action`, `--preshipped-deliverable` and the `--zero-ship-diff` short-circuit). For these ships the adoption proof legitimately does not exist yet at the diff-only, pre-land Stage-8 audit-post, so a base audit-post false-REDs "adoption missing"; run audit-post with the variant's overlay flag, which tells the auditor the absence is the NORMAL ordering for that ship, never a defect. The variants:

- **(a) event-emit-only ships** — ship = single `events.jsonl` event emission (adoption probe per CHARTER §Principle 8, not a code diff); base audit-post may RED-flag closure-metadata absence as a defect — category mismatch since closure work IS Stage 9 following Stage 8. Flag: `audit post --task T-XXXX --event-emit-only` (overlay: the not-yet-emitted P8 event's absence is EXPECTED). See `patterns/event-emit-only-audit-post.md` for the absorption protocol; closure proceeds via Stage 9 hand-edit fallback if AC probes verified independently.
- **(b) serve/deploy ships** (SPEC-0094 §5) — ship = a live deploy (an ACTION, not a code diff); live-adoption is proven at the deploy seam + recorded at Stage-9 Closure (the per-change `live_probe` evidence), AFTER audit-post. Flag: `audit post --task T-XXXX --serve-deploy`; removes the X-0039 owner-reset/ceiling-burn.
- **(c) host-config ships** (SPEC-0094 §3 / SPEC-0111) — the `host_config: true` marker; adoption proof is the THREE hostapply evidences (`apply_confirmed` / `host_health_sweep_passed` / `host_reconciliation_recorded`) recorded by the SPEC-0111 apply seam at Stage-9 Closure, AFTER audit-post. Flag: `audit post --task T-XXXX --host-config`; removes the X-0117 false-RED. **Finished by (X-0119/X-0120):** the overlay was only half the fix — `_ac_probe_evidence_events_for` now ALSO surfaces those 3 evidences (when they exist) as task_id-tied adoption evidence to audit-post, and a task ceilinged on a since-fixed false-RED earns ONE ceiling-exempt re-audit (the TASK lens-version axis, `bin/yitc-v2 graph query SPEC-0036`) — so a host_config task closes cleanly without the Stage-9 hand-edit (kupiclub).
- **(d) land-emitted non-P8 acceptance-event ships** (SPEC-0036 / X-0188) — acceptance probe is a NON-P8 event **emitted by `land` at Stage 9** (e.g. `verify_layer_prep`), so it legitimately does not exist yet at the pre-land Stage-8 audit-post. The `--event-emit-only` overlay is P8-CLOSURE-event-specific (`consumer_read_evidence` / `live_trigger_evidence`), so it does NOT cover an arbitrary land-emitted acceptance event and the base audit-post false-REDs "acceptance probe not satisfied" (X-0188 — burned 2 RED passes + a convergence consult on this structural false-RED). Flag: `audit post --task T-XXXX --land-emitted-event` (recorded `land_emitted_event: true` in the saved verdict YAML; --task audit-post only). The GENERALIZATION of the event-emit-only carve-out to a NON-P8 event.
- **(e) post-ship-observation ships** (SPEC-0036 / X-0710) — the acceptance proof is a **multi-day post-ship PRODUCTION OBSERVATION** (aiseller : «the daily count is flat or falling over 7 days»), so the reading cannot exist at the pre-land, diff-only audit-post — its window opens only after the ship. Flag: `audit post --task T-XXXX --post-ship-observation` (recorded `post_ship_observation: true` + `post_ship_observation_due_by:`; --task audit-post only). **Not a blanket excuse — the deferral is TRACKED:** the flag is fail-closed on the card's own `post_ship_observation: {observation, due_by}` declaration (SPEC-0028), re-verified at the `task close` seam, and the pending observation stays on the `overdue-recheck` debt view (the session-start debt echo) from declaration until a `settled_by` locator names where the recorded reading landed — time passing never discharges it.

**The family is CLOSED against a declaring-card variant — that shape is the card-repair ROUTE, not a
sixth member (X-1240).** A carrier-/entry-DECLARING card (its deliverable IS a declaration —
a live entrance, a carrier, a host config) cannot read the evidence of its own declaration before the
land, so its RED names the evidence the CARD RECORDS as stale. Do NOT reach for an overlay of your
own: the ORDERING half is covered by whichever member above matches the ship (`host_config` /
`serve-deploy`), DERIVED from the card's own declaration — so a card that took that
false-RED is a card missing its declaration — and re-recording the evidence is a bookkeeping-only fix,
which is `task commit --fix-red --card-repair` (SPEC-0015 §Internal). Measured on aiseller,
which closed GREEN on the same commit once its card declared `host_config`.

**Done when:** audit verdict GREEN or YELLOW-with-followup-filed.

**Leave the audit-post YAML dirty — `task close` commits it, NOT a standalone `task commit`.**
After `audit post` writes `decisions/<task>-audit-post.yaml`, do NOT run a standalone `task commit` on
it: that shifts the recorded commit past the audited commit and DEADLOCKS closure (the / E-0008
chain-of-custody trap). `task close` folds the dirty audit YAML into its own closure-record commit.
**THREE sanctioned exceptions — one per admitting verdict, same mechanics throughout:** the mode-a absorption cycle
(`task commit --absorb` — YELLOW) and the RED in-scope-fix leg (`task commit --fix-red` —
RED, and only on positive proof the commit carries authored content, so a fixless RED absorption stays
refused at both doors; its `--card-repair` arm, admits the card-record repair on the
different proof that the audited ship it rides on exists), and the GREEN second-ship leg (`task commit --reship` — GREEN, same authored-content proof: audit-post passed and a further IN-SCOPE ship is still needed; nothing further to ship means the GREEN stands and Stage 9 is the route). Each folds the superseded verdict INTO its commit (NEVER hand-delete it — that
zeroes the passes counter), then the REQUIRED `audit post --commit <new>` re-pins custody and carries the
trail (`passes_trail`). Full rule + the `cmd_task_commit` foot-gun guard: SPEC-0015 §Internal
(`bin/yitc-v2 graph query SPEC-0015`).

### Stage 9 — Closure

**Goal:** task marked done with adoption evidence (Principle 3 — «done = adopted»).

> **Retrieved — moved to SPEC-0015** (Part I-A demote). The full closure contract —
> audit-post-precedes-closure ordering, the `task close` path (incl. `--batch-close` for stranded-`ready`
> work-batch tasks; hand-edit fallback EMERGENCY/genuine-gap ONLY), probe verification (empty set →
> rejected), and the infra-class Principle-8 adoption-strength WARN (`adoption_evidence_seen`) — `retrieved`-tier at Closure stage-entry (SPEC-0015 binds `stage-entry:Closure`). Read: `bin/yitc-v2 graph query SPEC-0015`.

**Done when:** task YAML `status: done` + probe events captured (full contract in SPEC-0015).

> **⚠ Verify BEFORE you close — closure has no clean undo; close LAST in a batch.** Closure is safe
> only after a **land-equivalent verify** passes — the SPEC-0077 pinned suite `land` re-runs, self-checked
> at Stage 6 by `task test --run`. Bare `pytest tests/` skips script-style `__main__` tests and
> reads **false-GREEN**; a done-but-unlanded task is no fix and has no clean reopen.

## Plan lifecycle
<!--AUDIENCE:controller-->

The PLAN-axis mirror of the 9-stage task lifecycle: a SKELETON here in the always-loaded
handbook + the per-stage normative DETAIL delivered on-demand at the moment of use. Unlike a
task (which carries BOTH `status` and `current_stage`), a plan has **no picker** — sessions never
scan `plans/` — so it keeps a SINGLE FSM field, `status`, whose values ARE the stages.

**FSM (authoritative):** `draft → specs → trial → accepted → decomposition → executing → postcheck → realized`
(terminal `partial | rejected | cancelled`). `trial` (SPEC-0035) is a controlled real-data
design-convergence stage between `specs` and `accepted`: its entry is **OWNER-INVOKED and only
for trial-ELIGIBLE plans** (mechanism/behavioral, not text-audit-verifiable). A non-eligible
prose/docs plan SKIPS it via the two-branch `accepted` entry-gate — the live path stays
`specs → accepted` directly for it. This fork is SURFACED at the post-specs decision point by the
`plan stage specs` + `plan file` verb next-hints — both branches are named so an eligible
plan is not silently routed past `trial` (eligibility stays owner-judged, no detector).

**One rule for every transition:** the verb gates the **PRIOR stage's completion** (a check «at the
end of stage N» is the ENTRY gate of stage N+1). One line per LINEAR stage — `status` · entry-gate ·
work · task analog:

- **draft** — start (`plan file` creates it) · author the draft (WIP planning) — front-load doctrine + skeleton sections delivered at `plan file`: SPEC-0043 (`graph query SPEC-0043`) · *Analysis*
- **specs** — draft is thought-through · `plan stage specs` asks the **mandatory-blocking** `gate-specs` external audit (RED/ABORT holds the transition — gate policy home: SPEC-0083) · compose + check the draft specs (`spec new --draft`) · *Filing/Plan*
- **trial** *(owner-invoked, trial-eligible plans only — SPEC-0035)* — draft specs composed + checked · run the planned mechanism on real(-ish) data until the design converges (baked `## Trial protocol`; never mutates production data); owner judges convergence on journaled runs · *pre-accept design-convergence soak*
- **accepted** — draft specs composed + checked · confirm plan+specs, compose `implementation_plan`; specs born `proposed`. ORDER : compose `implementation_plan` + the realization-exit block FIRST, then `plan check`, then `plan stage accepted`, then `decomposition` — the freshness `content_hash` covers the plan BODY, so a realization-exit block written after the check stales it and buys a full re-check (a frontmatter-field edit does not); a fresh check does NOT preserve mode-b `absorbed:` · *Plan*
- **decomposition** *(SPEC-0070)* — `plan check` GREEN/YELLOW + impl-plan composed + specs `proposed` (LARGE plan: mandatory big-plan check) · cut the plan into task cards (SPEC-0046); the cut SET is then gated by a mandatory external decomposition-fidelity audit (SPEC-0070) before `executing` · *pre-build cut + fidelity gate*
- **executing** — the cut passed the decomposition-fidelity audit (SPEC-0070) · the task cards run their own 9 stages (pure build; the cut is already audited) · *Execution + Tests*
- **postcheck** — all tasks done + aggregate `audit post --plan` GREEN · real-data soak ×N + monitoring «works as intended» + corrections · *Audit-post + adoption soak*
- **realized** *(terminal)* — real-data soak confirms intent; `plan stage realized` finalize-gate + `--into <IDs>` · — · *Closure*
- **terminals** — `partial` (remainder → a NEW plan, never prose) · `rejected` / `cancelled` (`--reason` required); file STAYS in `plans/` · *wont-do*

**Verb tie:** `bin/yitc-v2 plan stage <NAME>` is the SOLE writer of the FSM; it gates the prior
stage, runs the stage side-effects, and DELIVERS SPEC-0034's matching slice at stage-ENTRY (the
`plan-stage-entry:<NAME>` axis — the plan analog of the task `stage <NAME>` bundle).

> **Retrieved — SPEC-0034 — stage-DELIVERED at each `plan stage` entry.** The full per-stage
> mechanics (entry-gate / work / side-effects), the plan↔spec linkage chain (born → activate →
> finalize), and the NORMATIVE mandatory big-plan check at the `executing`-gate live in the
> `retrieved` tier — NOT duplicated here. Read via `bin/yitc-v2 graph query SPEC-0034`; full
> procedure in `patterns/plan-lifecycle.md`.

### Plan routing — what varies by plan shape (pointer-view, P5)

Unlike the task lifecycle's single binary hygiene fast-path (§Two flow types), the plan
lifecycle has **no single hygiene-style fast-path**: every plan transits the same FSM, but
**one stage (`trial`) is conditionally skipped by owner judgement** and the remaining
differences are **gate-WEIGHT variations**, not skipped stages. This view consolidates the
per-shape routing for discoverability; the rule bodies live in the cited specs — nothing is
restated here (P5).

- **`trial` — one OPTIONAL owner-judged stage (SPEC-0035).** The default path is
  `specs → accepted` directly. `trial` is entered ONLY for trial-ELIGIBLE plans
  (mechanism/behavioral, not honestly text-audit-verifiable) and ONLY on owner invocation —
  it is a real stage that some plans skip, NOT a generic lightening. For a trial-eligible
  plan the `plan check` role NARROWS: it is no longer the design-convergence gate (the trial
  soak is), only the assembled-package audit. Rule: `graph query SPEC-0035`.
- **Big-plan checklist — a gate-WEIGHT variation, not a skipped stage (SPEC-0034).**
  `plan check` (FULL capability) runs for EVERY plan at the `draft → accepted` accept-gate
  (SPEC-0034); only the extra big-plan checklist + `checklist_pass` is LARGE-plan-only. This is NOT a
  settled "~200 lines / purely automatic" threshold — the apply-when criteria are substantive
  (`patterns/big-plan-checklist.md`); the current implementation's line-count auto-flag is an
  aid, not the normative trigger. Rule: `graph query SPEC-0034` §Mandatory big-plan check +
  `patterns/big-plan-checklist.md`.
- **Spec-corpus finalization audit — present only for spec-bearing plans (SPEC-0034 / SPEC-0070).**
  A task-only / spec-free plan skips the spec-corpus aggregate `audit post --plan` surfaces
  (auto-skipped by the shared finalization helper). It does NOT skip the rest: `postcheck`
  still requires its cited tasks done + the probe block, and `realized` still requires its
  other exit gates. The decomposition cut SET is gated by the mandatory external
  decomposition-fidelity audit (SPEC-0070) for EVERY plan. Rule: `graph query SPEC-0070`.

## Resume contract
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0027.** `bin/yitc-v2 graph query SPEC-0027`

## Hygiene Fast-Path
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0027.** `bin/yitc-v2 graph query SPEC-0027`

## Stage FSM per class — current_stage semantic names
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0027.** `bin/yitc-v2 graph query SPEC-0027`

## Search-Before-Build cross-cutting
<!--AUDIENCE:core-->

All stages (especially 1, 3, 5) apply CHARTER Principle 1 filters:

1. **Existing analog?** Grep before designing. Use `yitc-v2 graph query <similar-spec>` or bare `grep -rn`. For a consolidated report (rules / verb governance / …), check `yitc-v2 graph query --type view` FIRST — a ready saved-lens may already answer it (REF_AVAILABLE).
2. **Extend vs create?** Extending wins by default.
3. **What gets removed?** If nothing — escalate.
4. **Real incident?** If imagined necessity — defer.

## Scenario authoring (pointer — per SPEC-0076)
<!--AUDIENCE:core-->

A **scenario** (`scenarios/<slug>.md`, the 7th graph node) is the human-facing user-path artifact —
zero-normative narration that `cites` the specs where every rule lives. It is NOT a lifecycle stage;
this is a navigational pointer, not a restated rule (the rules live single-SoT in SPEC-0076 — fetch
via `bin/yitc-v2 graph query SPEC-0076`; authoring shape: `scenarios/_template.md`).

- **Where authoring sits:** at the PLAN `draft → specs` seam — as a plan's specs are composed, the
  scenario is authored/updated alongside them (it composes those specs into a user-path). See
  §Plan lifecycle.
- **Per-stage checks:** scenario coherence is checked on the EXISTING lifecycle stages (no new gate,
  no new lifecycle) — the stage map + which checks WARN vs BLOCK live single-SoT in **SPEC-0076 §6**.

## Queue interaction (cross-stage)
<!--AUDIENCE:core-->

If during any stage you discover a new task:
- Same task scope, trivial → handle inline, mention in commit
- Adjacent improvement, separate concern → file new task (Stage 2 for that task), continue current
- Cross-project issue → file a `bin/yitc-v2 cross request` coordination item on the shared coordination log addressed `to:<project>` (governed by SPEC-0084/85/86), don't implement

Filing IS work product (CHARTER #6 + LIFECYCLE Stage 2). Don't pretend tasks don't exist by skipping filing.

## Refs
<!--AUDIENCE:core-->

- Distilled from: `yitc-workspace/task-lifecycle-canonical-spec-2026-05-24.md`
- Done = Adopted enforcement: CHARTER Principle 3
- Anti-complexity filters: CHARTER Principle 1
