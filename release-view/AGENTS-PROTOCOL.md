<!-- GENERATED — identity-agnostic release view of the methodology handbook. Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->

# AGENTS — Worker protocol, gates & references (part 3 of 3 of the AGENTS protocol)
<!--AUDIENCE:core-->

> SOURCE part 3 of the AGENTS protocol (`HANDBOOK_READ_ORDER`). All parts are assembled — in order — into your
> audience's runtime seed (Worker: the assembled `graph/worker-seed.md` part chain; Controller: the SOURCE parts directly in the read-order — SPEC-0007 §5c).

## Worker protocol per task (the 9-stage executing flow; the Controller runs it too on owner say-so)
<!--AUDIENCE:core-->

For every task, work through the 9-stage lifecycle in order:

**Analysis → Filing → Plan → Audit-pre → Execution → Tests → Commit → Audit-post → Closure**

The full per-stage contract (goal, done-when, the verbs and the retrieved spec each stage
delivers) lives at its single home — **LIFECYCLE.md §The 9 stages** (§Stage 1-9). This list is a
navigational pointer to those stages, not a restatement of their rules.

Hygiene tasks take the **Fast-Path** (a reduced stage set) — see **LIFECYCLE.md §Two flow types**.

## Commit format
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0014** (the commit contract: `<type>(<task-id>): <subject>` format + `from:` discipline + the «`task commit` owns staging» rule + emergency bypass + `Co-Authored-By` trailer; delivered at the Commit stage-entry). `bin/yitc-v2 graph query SPEC-0014`

## When to ask owner vs proceed
<!--AUDIENCE:core-->

**Proceed autonomously when:**
- Task scope is clear, single path forward
- Refactor / hygiene / mechanical change
- Implementing per agreed plan (audit-pre GREEN)

**Ask owner when (rare):**
- Genuine architectural fork with no clear default
- Acceptance criteria ambiguous, would change scope
- Deletion / destructive operation on data
- New mechanism proposed (anti-complexity filter #4 says «real incident?» — if no incident, ask owner before adding)

When asking — always offer a recommended default + 1-sentence rationale. Never paste a menu.

**Name the authority artifact — or it is not an owner decision.** BEFORE escalating anything, answer
one question: **which ARTIFACT says this is the owner's call?** Name the clause — a spec's own
owner-gate clause, SPEC-0121 §5's AUTHORITY-class list, a CHARTER §6 fence line — not a `--help` line:
`--help` states a flag's DEFAULT authority, never its full clause (SPEC-0077 §A-prime option (B) lets
a dispatched Worker self-clear the very `--rebaseline` that `--help` calls "OWNER-ACKED"). If you
cannot name the clause, it is **not an owner decision** — it is ceremony, and ceremony dressed in
evidence (a recommendation, a costed alternative, real citations) is harder to spot than a bare menu:
proceed instead, and capture the deviation if the artifact turns out to say otherwise. Grounds — two
same-day incidents, 2026-07-10: the escalation fired off an *unread* authority clause, on a
gate the worker could (and already had) cleared itself by a sanctioned path; the mirroring hold
correctly kept an authority-class criterion for the owner once its clause WAS read. Provenance:
`plans/queue-drive-meta-analysis-parallelism-human-checkp.md` §Axis 2.

**Non-blocking batch — an owner question never freezes the batch (per SPEC-0126).** In an owner-authorized
background batch, when ONE task hits an "ask owner" trigger above, do NOT halt the whole batch waiting for
the answer. PARK that task in its existing waiting-on-owner state (`bin/yitc-v2 task pause --reason
owner-wait` — the SOLE carrier; it surfaces at session start. NOT the `blocked` status: no verb writes
it, so prescribing it would name an unreachable state — QUEUE §Verb routes), CAPTURE its
question durably+visibly via the existing followup/journal capture (`bin/yitc-v2
followup` — reuse the existing primitive, NO new question store/FSM), and CONTINUE the other independent
ready tasks. The owner answers the accumulated questions on reconnect. (This is the OWNER-QUESTION block;
a task blocked on an unmet `requires:` dependency waits per QUEUE §Picker instead.) The doctrine home is
CHARTER §6 + AGENTS-SESSIONS §Orchestrate posture; full rule: `graph query SPEC-0126`.

## When NOT to add a mechanism
<!--AUDIENCE:core-->

If you find yourself wanting to add:
- A new hook
- A new pre-commit gate
- A new file format
- A new parser path
- A new behavioral detector
- A new ledger / log / journal
- A new layer of indirection
- **A cache on a view because a composed seam got slow** — the seam owes ONE request-scoped ReadScope at its wiring site, not N caches; rule + exemption carrier: SPEC-0190 rule 10 (`graph query SPEC-0190`), rubric aspect 6 in `patterns/verb-design.md`.

→ STOP. Apply Principle 1 (anti-complexity) 4 filters. Write them down in the spec that homes the new rule (`spec new`) or its proposing plan. Get owner approval (the Controller, on owner say-so) before implementing.

V1 accreted to 95 gates / 60 hooks / 5 journals because this stop was skipped. V2 does not get to repeat.

**Retiring dead weight.** The flip side of «when NOT to add»: when something accretes
or rots, retire it via `patterns/retirement-procedure.md` — analysis ( candidate detector) →
warn → disable → analyze → remove. Manual-first (automate only once the steps repeat). Candidates
surface in the weekly Review audit + at any «what gets removed?» (Principle 1 F3) moment. Applies to
rules / patterns / handbook prose / code obligations; NOT to append-only events or done-task history.

**Verbs are the control surface.** Verbs — not provider hooks — are the control / guard / journal points (the AI's behavioral obligation to USE them, never hand-doing a verb's work, is the always-loaded §Verb-execution discipline norm above). Before adding or changing a verb, check it against the 4-purpose rubric in `patterns/verb-design.md` (ease / error-reduction / journal-marking / control-chokepoint). Standing answer to «let's add a hook for X» = EXTEND the verb that is «before X» (prior-art `_auto_sync` / `_auto_rebuild_graph`, both NOT hooks). A verb that does a **lifecycle stage's work** is built to the standing `patterns/verb-design.md §Stage-work-verb BUILD recipe` BY CONSTRUCTION — stage read-check + stage-correspondence guard + `read_gate_refused` on every refusal, two refusal axes verified; the decomposition structural pre-pass alongside it is **REPORT-ONLY**, never a blocker (SPEC-0046).

## Filing rule
<!--AUDIENCE:core-->

If discovery happens mid-task (you notice something else that needs fixing):
- **Trivial fix in same scope:** apply inline, mention in the commit body
- **Adjacent improvement:** file `tasks/<id>.yaml` for future, don't expand current task
- **Cross-project issue:** file a coordination item on the kernel-owned SHARED coordination log via **`bin/yitc-v2 cross request`** (the AUTHOR verb — allocates the immutable id, emits `cross_requested`) addressed `to:<project>`, don't implement. The append rides the no-worktree journal path (§Writes happen in a worktree) and is territory-in-bounds (§Scope-boundary → shared-store carve-out). Governing contract: **SPEC-0084** (authority/placement/realm) + **SPEC-0085** (event FSM / kind protocols) + **SPEC-0086** (the `cross` verbs). The **`-C` kernel↔consumer** intake direction is preserved by the cross system (SPEC-0086; historical origin SPEC-0079 §6).

This is Principle #1 filter applied at runtime: don't grow scope; file for later instead.

## Planning artifacts — plans / ideas
<!--AUDIENCE:controller-->

Two tracked planning classes live OUTSIDE the task queue:
- **`plans/<slug>.md`** — work-in-progress planning, markdown + frontmatter (patterns model), with a status FSM whose authoritative carrier (the stage set + terminals) is LIFECYCLE §Plan lifecycle (not restated here).
- **`ideas/<slug>.md`** — flat forward-looking notes (no FSM), held until an incident makes one actionable.

**Vocabulary (the amendment).** The folder is named after the CLASS (`plans/`)
and no STATUS shares that name, so the old «draft overload» is gone. Refer to an item by its
`status:`: `status: draft` = WIP (still deciding) · `status: accepted` = a vetted candidate (gated
on a fresh `plan check`; take-into-work on owner cue) · `realized | partial | rejected | cancelled` = terminal
(the file STAYS in `plans/`; the authoritative terminal set + FSM is LIFECYCLE §Plan lifecycle — this is a vocabulary restatement, not the SoT). View the two active lists via `bin/yitc-v2 plan list --status accepted`
(candidates) / `--status draft` (WIP) — **ONE directory, status-filtered**, NOT a folder per status
(that would move files on every transition + break `from:`/`closed_into` path-citations + double-
encode `status:` — P5). Prior-art: PEP / ADR keep one directory + a status header.

**The accept-gate :** `plan stage accepted` flips `draft → accepted` ONLY if a fresh
GREEN/YELLOW `plan check` verdict exists (freshness = a content hash recorded by the check; the
mirror of `decision accept`), so `accepted` honestly means «a verified plan».

**The plan is the standing successor of `decision finalize` for AGGREGATE finalization (Part B).**
`plan stage accepted` does more than flip status — it **births the change-corpus** (the plan's `draft` specs →
`proposed`); and `plan stage realized` (for a spec-bearing plan) is **gated by an aggregate
`audit post --plan`** over the plan + its **realized-spec corpus** — every spec the plan realized: born
by it (`proposed_by==slug`) OR activated by one of its implementing tasks (`activation_owner_task` ∈ the
tasks that `cite` the plan; broadened, so a reorg/task-only plan's corpus is not silently empty) —
the inherited role of the retired `decision finalize`, at a whole-corpus altitude. A NEW
governance lifecycle finalizes through the plan, **never** `decision finalize` (backlog-only; `decision
new` is retired). A plan that realized no specs (none born by it, none activated by its tasks) stays
decompose-only (backward-compat). Full workflow: SPEC-0034 (`bin/yitc-v2 graph query SPEC-0034`).

**Sessions do NOT scan or analyze plans/ or ideas/ at startup** — the picker reads `tasks/` ONLY. A `plan` is taken into work **only on owner cue**, and Build **always re-checks currency** (Stage-1) before decomposing it into tasks/decisions — **and, for a spec-bearing plan, its realized-spec corpus (specs born by it OR activated by an implementing task)** — then marks the plan `realized`/`partial` (a spec-bearing plan only after the aggregate `audit post --plan` close-gate). Verification is a manual action (`bin/yitc-v2 plan check` — big-plan-checklist if large + external audit), **not** a persisted status. Full workflow: SPEC-0034 (`bin/yitc-v2 graph query SPEC-0034`).

**Carve-out — a report-only COUNT is not that scan (SPEC-0119 rule 21).** The clause above
governs the PICKER and queue-EXPLORATION: what leads a session to SELF-SELECT work. A derived,
report-only CENSUS of how many plans sit in each NON-TERMINAL stage — rendered suppressed-when-clean
on the SPEC-0119 debt echo, at the seams that echo already has — is PERMITTED and is not a startup
scan in the sense meant here: it names no candidate, ranks nothing, suggests nothing, selects nothing,
and counts no terminal plan. The picker still reads `tasks/` **ONLY**, and a plan is still taken into
work **only on owner cue**. Same boundary the corpus already draws at SPEC-0085 §8 («surfacing ≠
queue-scan»), and the same one drawn by the retirement of the startup picker, which removed
the picker and the auto-counts while explicitly KEEPING the waiting-on-owner surfacing as «a safety
signal, not queue-exploration».

## External auditor
<!--AUDIENCE:core-->

When invoking external auditor, use full-capability mode for:
- Big-plan validation (>200 lines)
- Architectural decisions
- Conceptual / coherence audits

Use lighter-capability mode for:
- Routine pre/post audits on small changes
- Quick verdict on absorption iterations

Audit-loop ceiling — homed in **SPEC-0124 §Audit-loop ceiling**; what happens ONCE IT IS REACHED in **SPEC-0204** (the Controller records one typed decision per residual, then ONE bounded `--on-decisions` pass; consult episodes / `--owner-reset` / `--reopen` are retired and REFUSE). Never a silent loop.

## Anti-recurrence discipline checks
<!--AUDIENCE:core-->

Before commit, AI MUST self-check:
- Did this task add a new mechanism? If yes, did anti-complexity filter pass + owner-approved?
- Did handbook total line count grow? If yes, what was deleted alongside?
- Did acceptance criteria include probe evidence (Principle 3)? If no, do not close task.
- Is this an **infra-class** task? If yes, does closure have a Principle-8 adoption artifact — a **SUBSTANTIVE** `consumer_read_evidence`/`live_trigger_evidence` event for the task (payload resolves non-circular machine evidence AND names the differential failing input — «would this still pass if the thing under test were BROKEN?»; prose-only no longer counts — contract homed in SPEC-0015), or — for a REMOVAL task — a probe key naming the verified absence ? An adoption-NAMED probe is no longer a carrier (retired : it matched on the key alone, unread). If none, `task close` WARNs (E-0005, non-blocking) — confirm adoption (emit a P8 event) or file a blocking follow-up before closing.

The AI runs these checks **mentally** before commit; the infra-class adoption check is additionally backstopped by the `task close` E-0005 WARN (the §infra-class bullet above). There is no dedicated self-check verb — the discipline rides the existing verbs, not a new mechanism (CHARTER §Principle 1).

## What is NOT in V2
<!--AUDIENCE:core-->

(For mental model — these are deliberately absent.)

- No UNBOUNDED pipeline orchestration — what stays absent is **in-session sub-worker fan-out** (a Build worker spawned as an in-process subagent), **auto-launch / autopilot** (a session that starts itself or self-fetches work), and a **stateful orchestrator** (no `orchestrate-route.py` / `spawn_backend.py`, no cap/queue-state machinery, no liveness-arming FSM, no role taxonomy). The **bounded controller-selector posture is PERMITTED** (§Session-types → Orchestrate posture): it dispatches independent tasks to other full Build SESSIONS — separate sub-sessions launched with the blessed verb `bin/yitc-v2 dispatch` (`patterns/background-session-dispatch.md §Dispatch launcher`), never in-process subagent Build workers — and is owner-invoked, batch-bounded, and stateless.
- No multi-role taxonomy (no roles/*.yaml — the AI agent does all stages itself)
- No autonomy FSM (no «observe/fix/autonomous» state machine, no drift counter, no pseudo-ask detector)
- No tier classification (every substantive task gets audit-pre + audit-post; no «file_scope skips audit»)
- No bypass-ledger / closure-wiring / liveness-registry
- No PostToolUse hook chain enforcing read-receipts (the AI agent natively tracks Read tool events)
- No awareness-ledger ENFORCEMENT — a session-scoped read-receipt ledger (`.yitc/awareness-ledger-current-session.yaml`, read-receipts ONLY, folded take-latest by `land`) DOES exist and is described single-home in AGENTS §Where cross-session work lives; what stays deferred is any layer that GATES on it («claimed-but-not-read» enforcement) — deferred until first incident (pairs with the "No PostToolUse hook chain enforcing read-receipts" line above)

If any of these gets requested mid-V2 — anti-complexity filter #4 («real incident?») applies.

## External auditor invocation contract
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0036** — the external-auditor invocation contract: who the auditor is, WHEN invoked across TASK/DECISION/PLAN gates, GREEN/YELLOW/RED/ABORT handling + the audit-loop ceiling; delivered at the Audit-pre + Audit-post stage-entries. `bin/yitc-v2 graph query SPEC-0036`
> (Supersedes SPEC-0016 at the closure.)

## events.jsonl schema
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0025.** `bin/yitc-v2 graph query SPEC-0025`

## External auditor prompt principles (universal + per-stage)
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0036** (the universal V2 evaluation lens + the TASK per-stage overlays for audit-pre/audit-post; delivered at the Audit-pre + Audit-post stage-entries). `bin/yitc-v2 graph query SPEC-0036`

The DECISION-audit overlays + the ad-hoc form below are NOT hosted by SPEC-0036 — they
remain always-loaded:

### Per-stage overlays (decision-audit + ad-hoc — retained)
<!--AUDIENCE:controller-->

**decision audit-pre (Draft → Accepted)** — «is this design sound to commit task resource to?»:
- the 4 anti-complexity filters genuinely pass (a decision is a governance change);
- it EXPLICITLY amends the canonical surfaces it changes (does not silently bypass them);
- alternatives / prior-art considered (existing analog — Principle 1 F1); reuse over reinvention;
- scope bounded; **retirements named** (replacement, not accretion — what is removed/forbidden?);
- `adoption_probe` is event/state/measurable (Principle 3 + 8 for infra-class);
- coherence: does it contradict an existing decision / handbook rule (Principle 7 dissonance)?

**decision audit-post (Accepted → Final)** — «did reality realize the decision's intent, coherently, across ALL its implementing tasks?»:
- every implementing task (`refs.follow_ups` `T-NNNN`) is `done`;
- the decision's `acceptance_criteria` / `adoption_probe` are ACTUALLY realized — probe evidence present, not merely claimed (catches the shipped-but-not-adopted class);
- coherence: shipped reality matches what the decision SAID — no drift, no contradiction with other artifacts (P7);
- the **retirements actually happened** (what the decision said to remove / forbid is removed / forbidden);
- **Review-only :** same as the task audit-post — do NOT run tests; VERIFY the recorded Stage-6 evidence of the implementing tasks.

**ad-hoc Review** — open-form. Owner specifies focus in the prompt itself. No fixed schema. Recommended path : `bin/yitc-v2 audit adhoc --slug <slug> [--prompt …|-f file|stdin] [--routine]` — wraps the external-auditor invocation + V2 lens, saves `decisions/<slug>-audit-adhoc.yaml`, emits the audit events; FULL model by default. **Run it from a `work/<slug>` writing worktree** (`bin/yitc-v2 worktree new --work <slug>`) — it SAVES that verdict YAML, so it is a write and the write-isolation guard refuses it on the main checkout. Naming the precondition here is what stops a first invocation predictably failing (X-0407); the rule's ONE home is §Writes happen in a worktree (AGENTS-SESSIONS.md).

### Saved audit result schema (canonical YAML)

> **Retrieved — SPEC-0036 §Saved audit result** — the canonical annotated audit-result YAML schema (every field + the annotated example + the audit-trail purpose) is homed in SPEC-0036's body, delivered at the audit-pre / audit-post stage-entry (demoted from this seed by). `bin/yitc-v2 graph query SPEC-0036`

## Instruction injection protocol
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0026.** `bin/yitc-v2 graph query SPEC-0026`

## Rule visibility and reverse-mapping
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0026.** `bin/yitc-v2 graph query SPEC-0026`

## Event types catalog extension
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0025.** `bin/yitc-v2 graph query SPEC-0025`

## Recommendation Default — owner communication
<!--AUDIENCE:controller-->

When AI presents a choice to the owner (architectural fork, design alternative, ambiguous scope):

**Ask INLINE in prose — NEVER the structured form/menu question UI (per owner directive 2026-06-07).**
The banned shape is the multiple-choice **form/menu question tool** (an `AskUserQuestion`-style
option-card UI): do NOT use it to ask the owner. The owner answers inline in the chat line; a form is
friction. Present every choice as prose in the format below (this strengthens §When to ask owner vs
proceed's «Never paste a menu» by naming the tool-form as the banned shape).

**Always lead with one recommended option** framed around reliability — not speed, not elegance, not minimal diff. Alternatives follow as a list with explicit trade-offs.

**Format:**

```
**Recommend: (A) — <reason in one line>.**
Alternatives:
- (B)... — <trade-off>
- (C)... — <trade-off>
```

If the owner just says "go ahead" — AI takes (A) and proceeds. Owner can always redirect.

**Anti-pattern:** "there are 3 options — which do we take?" without a named preference. Owner does not have local context and is being asked to make a judgement call AI should already have made.

**Tie-break criterion:** when 2+ alternatives equally reliable (data integrity / predictable behaviour / rollback-possible) — choose **minimum churn / narrowest surface area**. Never tie-break on speed or elegance.

**Default option — offer an external-auditor consult on a structural/pre-plan fork.** When
the fork you are presenting is **structural/design and NOT yet a plan or task** (an architecture direction,
a doctrine shape, a "which way do we build this" choice made before any lifecycle stage is claimed), name
**"check it with the external auditor"** (`bin/yitc-v2 audit adhoc`) as one of the offered options — so the
owner (especially a new one) discovers the auditor consult is available without having to ask for it by
hand (the real incident: the owner had to request it manually). **Bounds:** this applies to
**structural/pre-plan forks ONLY** — NOT routine choices (a naming pick, a trivial toggle) and NOT
in-lifecycle gates (the Stage-4/8 `audit pre|post` are already mandatory there, not an offered option). It
is **OFFERED, never auto-fired**: the auditor runs only if the owner takes the option, so the audit-loop
ceiling (SPEC-0124) is untouched. Still lead with your own recommended option per the format above — the
auditor consult is an *additional* alternative for a genuinely open structural fork, not a substitute for
the recommendation you should already have formed.

**Slip example (v1 DP#14 origin):** AI presented the owner with a 3-way fork "which model to use for bucket assignment?" without a preference. Owner spent decision energy AI should have already absorbed. Pattern repeats → owner trust drain + decision fatigue.

V1 had DP#14. V2 codifies same inline as soft discipline (mandatory practice, not an enforced gate).
