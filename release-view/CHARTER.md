<!-- GENERATED — identity-agnostic release view of the methodology handbook. Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->

# YITC v2 — Charter
<!--AUDIENCE:core-->

## What V2 is
<!--AUDIENCE:core-->

A minimal AI-assisted development methodology for **one developer (the owner)** working with a **primary AI agent** on multiple production projects (the owner's revenue-generating products).

**The product is owner's revenue-generating projects. V2 is supposed to make those projects ship faster, not to be a project itself.**

## What V2 is NOT (explicit non-goals)
<!--AUDIENCE:core-->

The non-goals list is critical anti-recurrence discipline. V1 accreted to 95 pre-commit gates / 60 hooks / 5 journals / 22 design principles / 508 spec artifacts precisely because it kept saying yes to "just one more mechanism". V2 says no by default.

- **NOT** a multi-role pipeline framework (no PM/Architect/Developer/Tester/Critic split — see `LIFECYCLE.md`). The bounded orchestrate controller-selector (Principle 6) is **not** such a framework — it is the Controller selecting + dispatching independent tasks to ordinary full Worker sessions; the §6 named retirements still forbid a framework.
- **NOT** a hook-laden enforcement platform (no pre-commit gate cascade; tests green = commit) — ONE named exception: the in-repository post-compaction entry (it runs the print-only brief only, bounded in time and output, and never blocks a compaction); any other hook still takes the four filters + owner approval
- **NOT** a multi-format documentation corpus (one handbook within the Principle 2 size budget — see Principle 2)
- **NOT** a multi-storage system (one YAML format, one parser, one journal)
- **NOT** a self-improving platform that consumes more development effort than it saves
- **NOT** a backlog management system optimized for thousand-entry archives (active queue within the QUEUE.md §Buckets size cap; rest = parking lot or deleted)
- **NOT** a behavioral discipline detector (no autonomy FSM, no pseudo-ask classifier, no drift counter, no halt-detection — simple rules in `<vendor-adapter>.md`)

## AI failure classes V2 anticipates
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0023.** `bin/yitc-v2 graph query SPEC-0023`

## The 8 Principles
<!--AUDIENCE:core-->

These are how decisions are made. They change rarely (semi-annual review at most).

### 1. Anti-complexity

Each proposed addition (mechanism / file / rule / process) MUST pass 4 filters before adoption:

1. **Existing analog?** Extend it, don't create parallel.
2. **New entity or new view?** View preferred over new data structure.
3. **What gets removed when this is added?** If nothing — addition suspect.
4. **Real incident OR concrete prior-art evidence OR documented external analog?** Real incident in V2 OR observed pattern in v1 (predecessor distilled by V2) OR analog in external systems we depend on — all count. Purely imagined necessity (no real / no prior-art / no analog) — defer.

**Scale-aware refinement:** when prior-art evidence shows entity proliferation pattern in v1 (e.g., 22 DPs / 41 policies / 508 RULE artifacts grew from minimal start), design V2 for projected scale upfront — not "current minimum + migrate later". Migration cost asymmetric: cheap at small scale, painful at large. Pure "defer until V2 empirical pull" = too conservative when prior-art evidence strong.

Anti-complexity is principle #1 because V1 accumulated 95 gates / 60 hooks / 22 DPs precisely from skipping these filters. V2 fails closed: when in doubt, don't add.

### 2. Documentation-first

**Cannot perform a substantive action in the system if there is no durable artifact describing its basis.**

Any mutation (commit / file edit / decision / external API call / task closure) cites:

- **`from:`** — durable artifact (task / spec / decision / project-side doc / **primary AI session transcript**) grounding this action. A `decision` here is an EXISTING frozen-history entry cited by id, never a freshly-authored one (the decision corpus is frozen — §Decision lifecycle). **Ephemeral chat NOT captured anywhere doesn't qualify** — capture as a task or, when it establishes a NEW standing rule, a spec (`spec new`) first. **Exception (qualified by which supersedes it):** the primary AI provider session log, if locally persisted by the AI tool, captures chat durably + automatically — but a RAW session-log pointer is legitimate ONLY for routine low-stakes forensic reference, NOT load-bearing governance. For a load-bearing `from:` citation, MATERIALIZE it to a journal entry (`events.jsonl#source_ref=<locator>` or `events.jsonl#ts=<ISO>`) and cite THAT, never the raw provider log (matching AGENTS §Session-log-awareness + LIFECYCLE §Stage-7). Author a spec only when the directive warrants durable governance, not for routine commands.

Mutated artifacts are visible in the diff — no separate `to:` field needed.

Read-only actions require `from:` only if substantive (e.g. analysis-time prior-art grep). Trivial shell commands (`ls / grep / cat / git log`) don't.

**Foundational/bootstrap exception.** An inaugural standing-rule artifact (the first spec in a new system or the first of a new class — historically the inaugural decisions …, now authored as specs) MAY cite external priors (owner directive, external auditor verdict, parent rule in a sibling system) as `from:` when no internal durable artifact yet exists. The artifact MUST explicitly note this is a bootstrap citation in its context or rationale fields. Subsequent artifacts cite internal durable artifacts only.

**Emergency bypass.** For urgent production incidents where no prior `from:` artifact exists:
- Marker `emergency: <description ≥ 30 chars including incident context>` in the commit body
- Bypass of `from:` requirement, owner-authorized
- Required: within 72 hours, write retro-doc capturing the new protocol + file post-incident task
- Frequency check: > 1 use per 30 days triggers a Controller review-audit

**Size budget:**
- Hard cap: ≤ 2500 lines total across the FULL generated `HANDBOOK_READ_ORDER` set — every split
  part counts, so splitting a file into read-order-served parts does NOT escape the aggregate (the
  conformance/check path SUMS the generated set, not a fixed 5-file list). The cap stays a hard
  fail-closed limit; the compaction discipline (SPEC-0127 §8) is unchanged.
- Warning threshold: 2000 lines — a Controller review pass reviews the growth trajectory; identifies compaction candidates
- **The rest of the budget rule — retrieved (SPEC-0127 §8).** Which files are handbook members and
  which are excluded, the reported byte/token axis, the compaction trigger and the deletion rule:
  read it before editing a seed doc — `bin/yitc-v2 graph query SPEC-0127`.

### 3. Done = Adopted

Acceptance criteria for any task MUST include **probe evidence** (event emit / state check / measurable effect). «Code committed» is NOT «done». Without adoption probe passing, task does NOT close.

This closes the v1 failure mode «shipped infrastructure that nobody actually invoked» — class accumulated for months before being detected by inventory audits.

### 4. AI Independence

Two-axis independence:

**(a) Auditor independence:** Internal AI (primary) + external auditor SHOULD be different providers — each catches blind spots of the other, and where a second provider is available that pairing is the norm, not an option. When NO external provider resolves for the tier (binding → env → PATH → repo config, none answering), the audit is ADMITTED on the primary provider — never refused, never a wait — and every such verdict is STAMPED `auditor_independence: same-provider` and REMINDED AGAINST at session start. When an external provider DOES resolve, that path is UNCHANGED and the verdict is stamped `external`. No external-only gate, no refusal arm. This is SCOPED to the no-external-provider fallback: it does not make same-provider auditing a free choice. **Retrieved — SPEC-0201** (the stamp, the journaled same-provider event, the reminder seam, the resolution order): `bin/yitc-v2 graph query SPEC-0201`.

**(b) Provider-neutral methodology language:** Methodology docs (`CHARTER.md`, `LIFECYCLE.md`, etc.) MUST NOT mention specific provider names or model IDs in normative text. Use abstractions ("primary AI", "external auditor"). Concrete provider bindings live in implementation config (`bin/`, hooks if added).

### 5. Single Source of Truth

- **One YAML format** for operational state (tasks, decisions, specs)
- **One parser library** (`bin/lib/state.py` when CLI ships)
- **One journal** (`events.jsonl`, append-only)
  - **Amendment (SPEC-0084 — the shared coordination instance, additive).** "One journal" means one journal **MECHANISM** — one line-format, one parser, one append + union-merge discipline — **NOT one physical FILE**. That mechanism MAY have a per-project instance (`<repo>/events.jsonl`) **AND** ONE governed shared coordination instance (the kernel-owned cross-project log). The shared instance is a **PERMITTED second INSTANCE** of the same mechanism, not a parallel journal. A literal second journal **FORMAT, parser, or discipline** still violates this principle. Authority home: SPEC-0084 (`graph query SPEC-0084`); reconciled in its other homes SPEC-0001 + SPEC-0002.
- **One decisions log** (`decisions/<id>.yaml` per-entry, never markdown) — **FROZEN history** as of the Phase-1 cut: a NEW standing rule is authored as a spec (`spec new`), not a new decision (§Decision lifecycle)
- **Derived artifacts are committed**, never `.gitignored`
- **No parallel paths** — if you find yourself writing "migration from old reader to new reader", stop and fix at source
- **Scope note :** "single source of truth" governs storage FORMAT / parser / journal — NOT git-commit COUNT; the per-task multi-commit reality is canonically documented at LIFECYCLE §Stage 7, not duplicated here.

### 6. One interactive posture (Controller) + the dispatched Worker

**One interactive posture, not a type choice.** The interactive main session opens in a SINGLE posture — **the Controller**: read-leaning, broad across projects, **dispatch-by-default**, self-executing a task only on owner say-so. There is no Build-vs-Review choice at startup — that distinction had eroded to near-nominal (both defaulted to dispatch; the type was never a permission class). The **right to write is granted by NO label** but by the orthogonal gates that apply to EVERY session: path-territory (per write, one project), worktree-before-write, and the 9-stage lifecycle for substantive change. This merge leaves those gates UNCHANGED. Cross-project observation stays routing/filed, never silent implementation.

**"Build" survives only as the dispatched Worker's executing flow.** A **Worker** is an ordinary full background session that runs ONE task through all 9 lifecycle stages (the 9-stage lifecycle — LIFECYCLE.md §The 9 stages) in its own `task/T-XXXX` worktree, ending in `land` — no handoffs, no in-session role split. Workers launch via `bin/yitc-v2 dispatch` (the blessed launcher, `patterns/background-session-dispatch.md §Dispatch launcher`), NEVER the provider in-process subagent tool. The Controller MAY run that same Build flow ITSELF, but only on owner say-so (the fallback). Intake stays owner-authorized either way — the owner starts the session and authorizes the batch.

**Net taxonomy → Controller (interactive) + Worker (dispatched)** — the vocabulary the Orchestrate posture already names. This merge RATIFIES controller/worker as primary and retires Build|Review as a startup choice: a REMOVAL + re-use of existing vocabulary (CHARTER §P1 F3), not a new entity, a hidden third mode, or a role split.

**Named retirements — what STAYS forbidden (the §6 fence, carried VERBATIM):** no auto-launch / no self-fetch / batch-bounded / no stateful orchestrator / no in-process fan-out (no autopilot-FSM; a Worker is a separate sub-session, never an in-process subagent; no cap/queue-state machinery, no liveness-arming FSM, no role taxonomy; no decide-without-owner). The owner always authorizes the batch and makes genuine decisions. If V2 grows beyond 1-developer capacity in 6+ months, **then** we discuss multi-role. Not now.

**Solo author, concurrent sessions.** "Solo" means one *author* (the owner + the AI doing all 9 stages itself) — NOT one session at a time. **Multiple concurrent SESSIONS are expected and supported**: the interactive Controller alongside several background Workers on *different* tasks, plus auto-sessions for analysis/hygiene. This is precisely why per-write **worktree isolation is mandatory** — parallel sessions sharing one working tree collide. A single session works **one task at a time** — sequentially through its 9 stages, never two in parallel — but the per-session task **count is not limited** (a session may take further ready tasks in sequence). The cross-session rule is "one active claim per task id" (QUEUE §Picker), not "one task at a time" globally.

#### Controller only — orchestrate posture and context-bounded continuation
<!--AUDIENCE:controller-->

**Orchestrate posture — the bounded controller-selector (the amendment ratified by plan `orchestrate-posture-for-the-main-session-6-amendme`).** The Controller's DEFAULT posture: instead of executing a task itself, it **selects + dispatches** independent ready tasks to Workers and **coordinates their order** — selection + dependency-gating on stateless reads, within ONE owner-authorized batch. The Controller never runs a Worker's stages in-process. This is a *posture*, **NOT a third type** (Controller + Worker stays the whole taxonomy) and **NOT the forbidden orchestrator**. The operational protocol + the named retirements are homed in AGENTS §Session-types → Orchestrate posture. The owner always starts the session AND authorizes the batch.

**Context-bounded autonomous continuation (per SPEC-0126).** Within an owner-authorized **plan-drive** (advancing a plan across its FSM stages after the owner took it into work) or **background batch** (running dispatched Workers over an owner-authorized task set), the Controller proceeds across seams — plan stage→stage, batch task→task — WITHOUT pausing for an owner cue at any seam that carries no human decision. This is the plan/batch-level analog of a Worker running one task's 9 stages without asking the human between them. It STOPS only on (i) a **genuine owner decision** (the AGENTS §When-to-ask-owner-vs-proceed triggers + §6(f) missing/ambiguous `requires:` edge + a heavy mandatory gate RED/ABORT on an unresolved cause per §7) or (ii) the **context threshold** — when `session context` (SPEC-0115) reaches the configured bound, STOP at a clean seam and propose a fresh-session hand-off (SPEC-1004, interactive only), with no lost work. This is INSIDE the fence: the owner authorizes the plan/batch up front and still makes every genuine decision, and it adds NO auto-start, NO auto-pick at session start (session start still awaits an owner cue), and NO self-fetch beyond the authorized plan/batch — the **named retirements above are UNCHANGED**. Full rule: `graph query SPEC-0126`.

### 7. Dissonance Is a Question

When AI detects inconsistency between durable artifacts (docs disagree, spec contradicts code, a frozen decision conflicts with task acceptance, etc.) — **do NOT silently choose**. Capture the contradiction (`deviation_captured`) or escalate explicitly, and author a spec when the resolution establishes a NEW standing rule. Continue only after one source declared authoritative or conflict resolved.

**Detection triggers:**
- Two docs prescribe different rules for the same concern
- Code behavior contradicts spec claim
- Task acceptance criteria contradicts cited decision
- New addition's filter check fails but appears to be justified by override claim
- A mandatory HEAVY gate (external audit ~min, land verify ~30-60s) returns RED/ABORT **repeatedly on the SAME unresolved cause** — a re-run just re-fails identically (the 2026-06-09 freeze class)

**Protocol:** halt action → record contradiction (the session log captures it durably — manual `dissonance_detected` event optional, not obligated) → author a spec (when a NEW standing rule resolves it) or escalate to owner → resume after explicit resolution.

**The re-run-vs-resolve fork (heavy gates).** A heavy mandatory gate that RED/ABORTs *again on the same unresolved cause* a prior pass already surfaced is itself a dissonance: **STOP — resolve the cause or escalate; do NOT blindly re-run the gate.** Re-running a slow gate against an unresolved contradiction is the freeze failure (both 2026-06-09 incidents — the plan-gate case still burned 2 full audits before the contradiction was recognised). This recognition is behavioral, held always; it is structurally backed by the audit-loop ceiling (SPEC-0124 §Audit-loop ceiling) and the land repeated-abort backstop — cite those for enforcement, this is the principle.

Without it the foundation accumulates silent contradictions until catastrophic correction.

### 8. Adoption Verification Strength for Infrastructure

**Principle 3 "Done = Adopted" extended:** for **infrastructure-class** work (format-migration, generator, event-emit, graph index, audit artifact, parser, query, hook) — closure requires **consumer-side adoption evidence**:

- **Consumer-read evidence** — next consumer actually reads the new artifact (event captures the read or state-check confirms)
- **Live-trigger evidence** — mechanism fires in production or synthetic load (event captures the fire)
- Or **explicitly blocking adoption follow-up** filed (with trigger condition + ownership)

"Tests green" **by itself** is NOT sufficient for infrastructure closure. Probe-side adoption (CHARTER §Principle 3 baseline) is sufficient for product-class work, not infra-class.

**Inaugural codification exemption.** When a decision is inaugural codification of Principle 8 itself or its first amendment, no prior consumer can have read it (bootstrap moment). For such inaugural decisions, substitute proof acceptable:
- Same-session synthetic exercise (mental walk through new rule applied to a hypothetical scenario)
- First downstream decision or task citing the new rule (proves consumer awareness — durable artifact citation)
- Plus standard Bootstrap exception per Principle 2 F4 absorption

Mirror to the Principle 2 Bootstrap exception for inaugural decisions.

## Project-declared audit-post exemption (per SPEC-0178)
<!--AUDIENCE:core-->

A project MAY declare, in its own operating contract, named **cases** whose matching cards close
WITHOUT the Stage-8 audit-post — each with a mandatory reason recording who accepted the risk and
why. This authorises the policy at the principle level; the rules live in SPEC-0178 and the
contract-level conditions in SPEC-0015 + SPEC-0036.

**Absent a declaration, every substantive task takes audit-post — the fail-closed default.** What a
project is BORN with gains a ratified exception: it is **the state every project starts in, absent an
owner ratification recorded at birth.** This ADDS a ratified exception; it does not move the default.
The two are separate code paths — SPEC-0189 rule 7 binds the first, so a birth that writes a relaxing
declaration never changes what silence means for any project that never opted in.

**The merit, not the convenience.** A born declaration is **attributable, reviewable and
reversible**: it names the owner who ratified it, it sits in the project's own contract where a
review can read it, and the project removes it by deleting a case. The current born state is the
opposite of each — an implicit gate nobody declared, that no review watches, and that no one is
recorded as having chosen. Where that ratifying decision is unavailable — any noninteractive birth —
no declaration is written at all.

**Two bounds. All three surfaces state them identically; a surface stating a different bound is a
standing contradiction (§Principle 7), not a wording variation:**
1. **audit-post ONLY.** A case never reaches audit-pre, the Tests stage, the land-verify layers, the
   worktree-before-write rule, or the Closure probes.
2. **A skipped audit-post burns NO audit-loop pass and CANNOT satisfy Principle-8 adoption
   evidence.** An absent audit is not a failed one; an infra-class card takes audit-post regardless.

**Automation may only RESTORE a gate, never remove one** — removal is always an explicit project act.
**AND that automatic restoration is INOPERATIVE wherever the `kind` judgement is not made:** it counts
only captures judged a DEFECT at triage, a call that is optional and — measured over three consumers'
entire history — never made there. Where it is not made, restoration is carried by SPEC-0178's
periodic review instead.

**Self-reference guard.** A case never reaches a governance surface — a spec, the pinned-test surface,
an always-loaded seed, or the declaring contract itself — whatever it says. Computed on the diff, never
on the declaration.

**Recorded: the external auditor advised outer caps (~3 skipped cards, or a 14-day window, per case)
and the owner DECLINED (2026-08).** The owner declined on the grounds that a cap converts a project's
own risk judgement into a kernel-set number that fits no project: the exemption is already bounded by
what it can reach (the two bounds and the self-reference guard above), already attributable
card-by-card, and already reversible by a restoration that only ever tightens. A cap would expire the
declaration on arithmetic rather than on evidence, while the honest report of ACTUAL coverage —
which SPEC-0178 requires per case — informs the same decision without pre-empting it.

## Decision lifecycle
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0024.** `bin/yitc-v2 graph query SPEC-0024`

## Failure trigger
<!--AUDIENCE:core-->

Don't escalate complexity in response to friction. Reduce.
In any correction loop — audit rounds, trial cycles, a task's fix cycle, debugging — when the next round finds a defect in the previous round's fix, the fixes are the failure signal: stop patching, find the simpler invariant that removes the whole class, and ask the owner when the simplification changes a promise.

## Anti-recurrence discipline
<!--AUDIENCE:core-->

Each addition to V2 (new file, new mechanism, new principle, new gate) requires:

1. Explicit anti-complexity check (4 filters, written down)
2. Real incident citation (commit / event / failure mode observed in V2)
3. Owner approval (during a Controller review)
4. What gets deleted alongside

Without all 4 — addition rejected. Owner enforces this during the Controller's review.

## Refs
<!--AUDIENCE:core-->

- V1 frozen reference: `<v1-archive>/` + `<v1-workspace>/`
- Review-preparation docs (read before authoring V2 charters):
  - `yitc-workspace/task-lifecycle-canonical-spec-2026-05-24.md` (959 lines — distilled into `LIFECYCLE.md`)
  - `yitc-workspace/project-done-equals-working-2026-05-25.md` (304 lines — informs Principle 3)
  - `yitc-workspace/yitc-queue-management-doc-audit-2026-05-24.md` (298 lines — distilled into `QUEUE.md`)
  - `yitc-workspace/awaiting-adoption-queue-reframe-2026-05-25.md` (anti-complexity reframe example — original filename contains provider name kept in v1 archive only)
