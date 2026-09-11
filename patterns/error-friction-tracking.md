---
name: error-friction-tracking
class: discipline
sourced_from: 'decisions/ (intent-vs-actual layer; 2 full external passes YELLOW×2 absorbed). Prior-art donors — Python devguide issue triage (single operating base), IEEE 1044 (vocabulary), ISO 9001 §10.2 CAPA (recurrence threshold), Lean muda+kaizen (kind enum), Google SRE postmortem/5-Whys (RCA), MASFT + coding-agent failure taxonomies (gap probes)'
applies_to: accumulating and acting on intent-vs-actual deviations — capture a friction the moment it eats time/tokens (event), and run the routine aspect-audits over a recent session/task to surface errors/frictions. Extends patterns/verification-protocol.md (the base check). NOT a pre-work plan gate (use big-plan-checklist.md).
---

# Error / Friction Tracking — the accumulation + intent-vs-actual layer

> **Discipline pattern. EXTENDS `patterns/verification-protocol.md` — not a parallel system.**
> verification-protocol already owns the intent-vs-actual lane (its 4 categories «Wrong-thing / Wrong-way /
> Wrong-time / Not-told-the-AI» ARE the deviation taxonomy; its 13 dimensions map 1:1 to CHARTER
> principles; it runs two independent tracks with a bounded anti-recursion stop rule). This pattern
> adds the four things it lacks: **accumulation**, **friction / time-token capture**, a thorough
> **aspect-split** (incl. a NEW resource aspect), and a **promotion** path into durable case files.
> It REFERENCES verification-protocol's judgment matrix; it never reproduces it.

## §Problem

`verification-protocol.md` judges **correctness** of one run and is then **ephemeral** — a GREEN/GREEN
comparison saves nothing. So:

- Frictions that eat **time/tokens** (redundant re-reads, duplicate tool calls, a manual reconciliation
  done by hand again) are silently worked around and **recur**, because nothing records them.
- There is no **accumulation**: a deviation seen in three different sessions never becomes "N≥2, fix it".
- Correctness-only judging misses **cost** entirely.
- Ad-hoc per-phase "retrospective" docs are unrepeatable and drift.

V2's deeper purpose is **AI management**: prove the AI did what the docs/plan intended, and surface
where it deviated or wasted resources. That needs a cheap capture path + a thorough, repeatable search
procedure + a place for repeated findings to land.

## §Solution

### The three-tier model (made explicit to avoid Principle-5 duplication)

| Layer | Role | Where it lives |
|---|---|---|
| 20 AI failure classes (CHARTER) | stable cause/risk **TAXONOMY** | `CHARTER.md §AI failure classes` |
| `events.jsonl` (`failed_attempt`, `dissonance_detected`, + `deviation_captured`, ex-`friction_captured`) | raw **OBSERVATIONS** (cheap, immediate) | `events.jsonl` |
| verification-protocol self-check + external YAMLs | per-run **JUDGMENTS** (the base check) | `decisions/<scope>-self-check.yaml` / `-external-verify.yaml` |
| `errors/E-XXXX.yaml` | **SYNTHESIZED CASE FILES** — promotion-only, reference-first | `errors/` (template: `errors/_template.yaml`) |
| growth-engine rule (CHARTER) | repeated cases reveal a **NEW failure class** → file a decision | `CHARTER.md §Growth` |

No layer restates another. Case files **link back**; they never copy matrices or payloads.

### CAPTURE — immediate, cheap, event-only by default

The moment a deviation eats time/tokens, record it as ONE event. No RCA in the immediate path.

- Event type string: **`deviation_captured`** (snake_case, like `task_closed` / `commit_landed`;
  renamed from `friction_captured` — that name biased every capture to "friction"). The
  legacy `friction_captured` is read-only: readers parse both. The canonical events-catalog entry is
  in `AGENTS.md` (formalized via, renamed via); the emit is append-only (consumers
  ignore unknown types).
- Payload `data` fields (the shape from — see `errors/_template.yaml` for the promoted form):
  - `kind`: `defect | friction | improvement` — **OPTIONAL at capture** (decided in triage — normative home SPEC-0056 §1; established by §2)
  - `relates_to`: failure-class id (CHARTER) and/or originating aspect (below) — reuse, don't invent
  - `impact`: `low | med | high` (or cost bucket `<5m | 5-30m | >30m`)
  - `fingerprint`: stable dedup/recurrence key (same wording every recurrence → countable)
  - `refs`: anchors to evidence (`events.jsonl#ts=…`, verification YAMLs, git sha)
  - `captured_via`: how the capture was surfaced (`manual | inspection | audit-run | owner-surfaced | …`) — set **`owner-surfaced`** when an external prompt had to surface it (see the trip-wire below)

Emit with the existing CLI verb: `bin/yitc-v2 event deviation_captured --task <id> --data '{…}'`.
**A deviation stays event-only by default** — most never become a case file.

**The inversion trip-wire — the felt "not worth capturing" IS the trigger (X-0214).** The
reflex is stated as a prohibition ("do NOT pre-decide is-it-worth-it") — but a *silent* worth-it
skip leaves no artifact, so the miss is invisible and self-reinforcing (the exact failure the
reflex exists to prevent). So invert it: **the moment you catch yourself weighing whether a
deviation is worth capturing, that hesitation IS the capture — emit first, let triage decide
value later** (`impact`/promotion are triage's job, never a pre-capture filter). Capturing a
low-value deviation costs one event line; skipping a real one makes it recur invisibly.

**Owner-surfaced = a MISSED reflex, and it must be COUNTABLE.** If the owner (or any external
prompt) had to surface a deviation you had already noticed and silently passed on, the reflex
already failed — capture it now AND mark **`captured_via: owner-surfaced`** so the miss is
greppable and countable (it feeds the §AUDIT `ai-failure-class` lens + the N≥2 recurrence roll-up,
turning an otherwise-invisible silent skip into a tracked class — X-0214's ≥32-event corpus
recurrence). This reuses the existing `captured_via` field (no new store, no detector — CHARTER
non-goal #7); the 2 legacy `owner-observation` spellings are read-only prior art (readers grep
both, mirroring the `friction_captured`→`deviation_captured` rename precedent). The promoted class
is **E-0044**.

> The **crisp session-start trigger** for this CAPTURE step is held in `AGENTS.md §At-session-start`
> («Deviation capture — HOLD ALL SESSION», renamed) so the rule is always in context. That block is the
> trigger + immediate action ONLY; THIS pattern remains the full procedure (no restatement drift).

### CADENCE — WHEN each tier fires (engine methodology, inherited by every consumer)

The CAPTURE block above is the *what*; this is the *when*. The three steps fire at DIFFERENT moments,
and capture/classify/record are all **automatic — never gated on an owner cue**. The reflex itself is
not restated here — its trigger lives in `AGENTS.md §At-session-start` («Deviation capture — HOLD ALL
SESSION»), the triage that consumes captures lives in SPEC-0056; this section adds only the *timing*:

1. **Event = immediate reflex.** The `deviation_captured` journal append happens the moment a
   deviation is noticed — no worktree needed (append-only journal, foldable from the main checkout). The reflex itself (when/why to capture) lives in `AGENTS.md §At-session-start` — see there.
2. **Durable artifact write = next governed write-point.** Any durable follow-on — a promoted
   `errors/E-XXXX.yaml` case file, or (for a consumer) its own friction SoT doc — is a normal artifact
   WRITE, so it rides the NEXT governed write-point: the current task's worktree if the finding is
   in-scope, else a small `work/<slug>` batch the next time a worktree is open (or at that task's
   `land`). NOT a separate interrupt-worktree mid-task, and never owner-gated.
3. **Cross-log routing to a PEER = owner-gated, EXCEPT the kernel-bound subclass (X-0042).**
   A general `target:<peer>` hand-off (the "new finding appeared — peer please triage" routing) still
   waits for an explicit owner cue (own-write/peer-read only — never edit the peer's log, SPEC-0079).
   **But one subclass auto-fires WITHOUT the owner: a deviation the session ALREADY classified
   kernel-bound** — marked `realm: kernel` AND `target: yitc-v2` (the EXISTING capture marker,
   REUSED — there is NO new auto-classifier; the session's own classification IS the signal). It
   auto-files a `cross request --kind bugfix --to yitc-v2` (SPEC-0085 §3 routing) **at the CAPTURE
   itself** — the moment `event deviation_captured` appends the marked row, from whatever checkout you
   are standing in — so the kernel hand-off works for a consumer **without a per-item owner «razobrat»
   ("sort-out") gate**. **`land` stays the BACKSTOP**, sweeping main's journal for rows that predate
   this seam or arrived by another path; it re-files nothing already routed.

   **Why the routing moment is the CAPTURE and not `land` (X-1073).** The land tail reads
   **main's** journal, so a capture made inside a branch reached the kernel only when that branch
   landed — and a capture made in a branch that CANNOT LAND, because its own subject is what blocks the
   land, could never route at all: the
   worse the defect, the less likely its report escaped. It cost us once. A kupiclub worker captured a
   kernel defect, halted with the worktree intact, and all three rows sat in the branch journal —
   invisible to `cross outbox` and to the kernel — until a controller went looking and re-emitted them
   **by hand**, a manual fallback no verb covered; the stranded finding then arrived late as X-1074,
   after two items had been answered as resolved on a fix that does not reach the case. Routing at
   capture is legal exactly where the capture is: a `cross *` append needs no worktree and is
   territory-in-bounds from any checkout (SPEC-0084 r5), and the participant identity resolves
   off the MAIN checkout name even from inside a worktree. **That hand re-emit is RETIRED** —
   nothing needs re-emitting, because nothing is stranded. The capture-time file is fail-open and
   print-only: a cross-log hiccup never turns the one-command reflex into an error, it names the skip,
   and the next `land` re-files the fingerprint. It is **idempotent**: the file dedups by the originating `fingerprint`,
   so a re-land of an already-routed deviation files nothing (no duplicate `cross_requested`). ONLY
   the kernel-consumability subclass auto-fires — NOT every idea. Owner judgement stays ONLY
   kernel-side (triage + decide-to-broadcast), never a per-consumer gate; the kernel's OWN land never
   routes to itself (`self == yitc-v2` short-circuits). The append rides the shared kernel-owned
   coordination log via the `cross` verbs (no worktree — / SPEC-0084 r5).

   **Two halves, one marker — the realm routes, the prose does not (X-0253).** `realm` is the
   **enumerated** half (the SPEC-0073 placement realms `kernel | v2-self | project`, validated at
   capture); `relates_to` stays the **free-text aspect** (a CHARTER failure-class id and/or prose) and
   **never routes on its own**. The split exists because the routable half USED to live inside that
   free-text field as an exact string match: a kernel-shaped deviation worded as prose («kernel:
   dispatch-status reader…», «orchestrate/dispatch coordination») matched nothing and was dropped
   **silently**, while this very section promised the hand-off was automatic. The legacy exact
   `relates_to: kernel` marker still resolves to the kernel realm, so every already-routing capture keeps
   routing. A **near-miss** — realm-without-target, target-without-realm, or a kernel-naming aspect with
   no `realm: kernel` — is **WARNED at `land`, never routed**: report-only, because auto-routing off an
   ambiguous prose match is exactly what SPEC-0085 §3 forbids. An explicitly non-kernel realm is **not**
   exempt from the warn: realm-says-project + aspect-says-kernel is a contradiction (CHARTER §P7),
   and swallowing it would re-open the silent drop.

**Receiver side + intake hygiene — closing the loop (X-0037/X-0042 /, pairs with the
author-side above).** The author-side auto-file (step-3) opens the loop; two receiver-side rules close
it WITHOUT a manual reconcile:
- **Auto cross-done at task close.** A task may carry a STRUCTURED link `resolves_cross: X-NNNN`
  (SPEC-0028) to the coordination item(s) it resolves. At **`task close`**, for each linked item the
  closer RECEIVES (`self == item.to`) that is `picked`, `cross_done` auto-fires (SPEC-0085 §3 receiver
  path) — so a shipped fix never leaves its cross request dangling (the manual-reconcile class that left
  12 X-items non-terminal until a hand sweep). IDEMPOTENT (already-done/never-picked → no-op) and
  FAIL-OPEN (a coordination-log hiccup never aborts a completed closure). The AUTHOR's `closed` terminal
  stays an explicit `cross close`.
- **Intake staleness/relevance guard at `cross pick`.** Before accepting an item, `cross pick` REFUSES a
  STALE pick — a DONE local task already resolves it (its `resolves_cross` link IS the "fix already
  landed" evidence) — naming the resolver, with a `--force` override; and SURFACES a
  not-actionable-for-this-side item (addressed to a different peer) so a side can skip it. So no side
  re-picks already-addressed or irrelevant work (the duplicate-intake class that produced the redundant
.. wave). Rule home: SPEC-0086 `cross pick`.

So: capture + classify + durable-record = automatic; a kernel-bound hand-off auto-fires at the
CAPTURE (idempotent; land re-sweeps as the backstop); the receiver auto-closes its half at LAND of the resolving task ( — keyed off the
close reaching `done` on main, NOT the in-worktree `task close`) via the `resolves_cross` link and
refuses a stale/irrelevant intake at `cross pick`; any OTHER cross-log hand-off = on command.

**Why this is engine-homed (not per-consumer).** This cadence — incl. the kernel-bound auto-file — is
a METHODOLOGY rule: how ANY session records frictions and routes an already-classified
kernel-consumability deviation back to the kernel, not a domain rule of one project. It is delivered
to a consumer through the SAME path as the rest of this pattern: a `-C <consumer>` session resolves
engine `patterns/` at the engine install path (the engine-content resolution), so a consumer
**inherits** this cadence and MUST NOT re-author it in its own CHARTER/docs (the F-015 drift the
kupiclub pilot surfaced; UNPARKS kupiclub).

### AUDIT — the search/detection procedure (5 routine aspect-audits + meta trigger-only)

A FIXED SMALL set of bounded aspect-audits, each thorough **within its aspect**, all findings flowing
into the ONE errors channel (no per-finding artifacts, no scoring ledger). Run over a recent
session/task. Each aspect is a lens; where it overlaps verification-protocol it **cites** the dimension
rather than re-runs it.

1. **doc-conformance** — were all MUSTs read? supplied at the right time? steps done in order?
   contradictions? all required data loaded? *(overlaps verification-protocol D2/D9 — cite, don't re-run.)*
2. **doc-health** — anything superfluous / duplicated / too-complex? repeated-but-useless? a missing
   MUST? candidates to simplify / generalize / delete? *(serves CHARTER §Principle 1 + handbook cap.)*
3. **cli-vs-manual** — what was done by hand, and why? which repeatable hand-actions should become CLI
   verbs ( control-points)? which existing CLI should change / be removed?
4. **resource** *(NEW — the cost lane verification-protocol lacks)* — token/time waste, redundant
   re-reads, duplicate tool calls, context-window utilization, runaway loops.
5. **ai-failure-class** — the 20 CHARTER classes + the **4 gap probes** below. *(overlaps D11.)*

Plus a 6th, **`meta`** (is the audit procedure itself correct?), **TRIGGER-ONLY** — run it only on a
governance change, repeated audit divergence, or owner request; **never** on an ordinary painful
session (running it routinely invites verification-of-verification — see §Anti-pattern).

#### The 4 gap probes (live inside aspect 5)

- **(a) existence + intended-target match** — every import/package/path is not just *a* real path but
  the *intended* file/module per plan / tool-calls / diff. Catches the real-but-wrong-target failure.
- **(b) silent fail-open + security scan** — diff scan for suppressed exceptions, permissive defaults,
  hardcoded secrets.
- **(c) reasoning↔action mismatch + post-/compact re-read** — stated plan vs the actual tool calls;
  and after `/compact`, was the mandated re-read (CHARTER/LIFECYCLE) actually performed?
- **(d) resource/token waste signals** — redundant re-reads, duplicate tool calls, runaway loops
  (shared lens with aspect 4; recorded once).

### PROMOTE — manual, file-or-waive (not automated)

An `errors/E-XXXX.yaml` case file is synthesized ONLY at the promotion boundary:

- a **hard defect**, OR
- a **recurring friction crossing threshold** (`N≥2` events with the same `fingerprint` — growth-engine
  parity), OR
- an **owner-requested investigation**.

At the threshold the reviewer **MUST** resolve it: **file a fix task** OR **explicitly waive with a
reason**. No silent drop. **owner + due are OPTIONAL for solo (normative home SPEC-0056 §4; established by)** — QUEUE has no
owner/due fields and V2 is solo-author, so `error promote --to-task` does not force them (they are
recorded in the case `resolution:` only when supplied). What prevents the ownerless "we'll fix it
someday" limbo is not a forced owner field but the routing + reopen-FSM + the **`triage run` STALE
open-N≥2 file-or-waive-overdue flag** (normative home SPEC-0056 §1): an open case recurring N≥2 with no owning fix-task is
surfaced as `⚠ STALE file-or-waive-overdue` until it is filed or waived.

**Remedy-existence sweep before filing a TRULY-NEW** (normative home: **SPEC-0056 §1**; this only cites it).
Owner/case-file ABSENCE alone does not prove a candidate is new: before a TRULY-NEW is promoted, sweep
code / a verb / a pattern / a spec for an analog REMEDY — if one already exists, route **ALREADY-BUILT**
(confirm it, do **not** file a duplicate), not truly-new. `triage run` reads the verdict from TWO
carriers (a ref ⇒ ALREADY-BUILT · `absent` ⇒ REMEDY-ABSENT swept-clean · nothing ⇒
`⚠ REMEDY-UNSWEPT`, sweep first): the capture's own `remedy_ref`, and — since — a
**triage-time** record made against an ALREADY-CAPTURED fingerprint with
**`bin/yitc-v2 triage remedy --fp <fp> --remedy <ref> | --absent`**, which WINS when both exist. Use
the verb: the sweep is a triage-time act over a backlog, so the capture-time field is unwritable
exactly when the rule demands it, and the only retroactive alternative — re-capturing the same
fingerprint — would falsify the recurrence count. A visible advisory, the same posture as the STALE flag — not an
enforced gate (CHARTER non-goal #7). Closes the round-3 misses / (remedy already existed).

### Cluster-aware recurrence count — the dedup HOME for fingerprint fragmentation

`fingerprint` is AI-authored free text, so ONE root often accrues many near-synonym fingerprints (the
land-false-fail class got ≥4; the broader land class ~14). Keyed per-exact-string, each alias reads
`N=1` and the true recurrence stays **invisible** — defeating the `N≥2` threshold above (the exact
failure the capture reflex exists to prevent). The **dedup home is the `cites:` LINK RULE** (normative home SPEC-0055; established by §9 —
the single EXCLUSIVE clustering carrier): a case file lists in `cites:` the member fingerprints it
subsumes, and its own `fingerprint:` is the canonical key. The recurrence count is **cluster-aware** —
`graph query --type error --recurring` and `triage run` Section B (via `_capture_cluster_counts`) roll
member counts up under the canonical fingerprint so a fragmented root is counted as ONE class. Ownership
is deterministic + single-count (self-ownership wins, else smallest E-id; each fp counted once). This is
a derived **VIEW** (anti-complexity Filter 2), not a new store or write-path; `sibling_fingerprints` is a
non-authoritative convenience mirror only (never the derivation source). NOTE: this counts a KNOWN
(already-cited) cluster; surfacing a fragmented root for its FIRST promotion (DISCOVERY) is a separate,
deferred concern — `plans/strengthen-the-deviation-mechanism-s-convergence-d.md` C1 (stem clustering).

### Same-root dedupe before filing + confirm-cause-or-disband admission

> Operative mirror — the normative home is **SPEC-0056 §1 (pre-filing dedupe) + §2 (the admission rule)**
> (established by §5/§6). This procedure follows them; it does not restate the rule text divergently.

**Same-root dedupe BEFORE filing — SCOPED, not blanket.** Before opening a NEW `errors/E-XXXX.yaml` for a
fingerprint, check whether it is a **respelling of a PROVEN alias family** — a confirmed root already
routed / `linked`. If so, route the new spelling `linked` (add it to the root's `cites:` per the §9 LINK
RULE), do **not** open a duplicate case. **Positive example:** `no-verb-for-task-status-transition` and its
respellings are the SAME proven root, closed by **** — a new spelling links there. **Negative
example (the guard against over-merge):** findings that merely share a failure-CLASS are **not** synonym
dups — the audit-loop-ceiling frictions share the "ceiling" lens but are DIFFERENT roots, so they are NOT
deduped. The CHARTER class is a discovery LENS (§6); the **proven-alias family** is the dedupe unit.

**Confirm-cause-or-disband admission — one fingerprint → at most one confirmed-cause cluster.** A case
file that asserts an UMBRELLA class but carries `cites: None` (subsumes no member fingerprints) **and**
`rca: None` (no 5-whys confirming a shared cause) is a **LENS, not a confirmed root** → **confirm the
cause (do the one 5-whys + cite its members) OR disband it** (a false root is itself a defect). **Named
case: E-0015** (`verb-invoked-from-main-checkout`, claimed as a class umbrella at N≈8 with `cites: None` +
`rca: null`) — it asserts a class but subsumes nothing and confirms no cause. This is the testable form of
the §Anti-pattern below ("inventing a class as the root"): catch over-clustering at admission, not after it
accretes.

### TWO OPINIONS — external only at the promotion boundary

Extends verification-protocol's Track A/B. The internal AI runs the aspect-audits. The **external
auditor** (different provider, CHARTER §Principle 4a) is required to confirm/reject **ONLY at the
promotion boundary** (a fix task / a decision / a new failure class) — **not** a default dual-run of
every aspect. verification-protocol's **bounded anti-recursion rule still binds**: one comparison pass
authoritative; divergence → escalate to owner; **NO verification-of-verification**.

> **Pointer (non-normative, procedure-referential only):** the SAME four-eyes principle applies to a
> whole TRIAGE WINDOW's ROUTING — an independent external-auditor pass (via `audit adhoc`) reviews the
> session's §5 dispositions and the two conclusion sets are reconciled. That rule's normative home is
> **SPEC-0056 §6** (threshold-or-owner-invoked, structural independence, `reconciliation:` block cross-
> referencing the `triage_run_completed` watermark — no new store); this is a pointer, not a restatement
> (SPEC-0005 rule 8, one home).

### Where accumulated errors live (graph)

`errors/` becomes the 11th graph node type and `graph build` indexes it — but that wiring is ****,
not this pattern. This pattern is the manual-first procedure; the CLI verbs (`error file/list/show/
promote`, `audit run --aspect <a> [--external]`, `graph query --type error --recurring`) ship in
****. Manual-first until then (owner directive).

**Multi-error incident arc → the E-case body is the narrative home (normative home SPEC-0056 §4a).** When
one incident spans a whole ARC — many `deviation_captured` captures across days plus several fix-tasks /
lessons / specs — its NARRATIVE home is the promoted `errors/E-XXXX.yaml` case file's BODY, **one arc =
one E-case** whose `cites:` links the member fingerprints / tasks / lessons / specs (the existing edge).
Do **not** invent a parallel `docs/incidents/` doc class or a per-arc store (the v1-accretion trap this
whole channel exists to avoid). This complements the §Anti-pattern below: the narrative home **cites** its
arc by anchor, it does not copy evidence in. Pointer, not a divergent restatement (SPEC-0005 rule 8).

## §Example — the dry-run that debugged this procedure

**Subject (pinned):** this session's startup. Prior **** session emitted a `commit_landed` event
via the CLI for commit `9846e82` but ended **before committing the journal line**; the next session had
to detect and reconcile it (committed as `91d2138`) before it could create its worktree.

**Aspect run:** `cli-vs-manual` — a repeatable hand-action (reconciling an orphaned auto-emitted event
at session start) that is a candidate for a future CLI / land-time check.

**Captured (event-only):**

```bash
bin/yitc-v2 event deviation_captured --task --data '{
  "relates_to": "cli-vs-manual",
  "impact": "low",
  "fingerprint": "orphaned-auto-emit-event-uncommitted-at-session-end",
  "refs": ["91d2138", "events.jsonl#ts="]
}'
```

**Promotion check:** `N=1`, low impact, not a hard defect, no owner request → **NOT promoted**. Stays
event-only; no `errors/E-XXXX.yaml` authored. (If this same `fingerprint` appears again, `N≥2` would
cross the threshold and force a file-or-waive.) This is the event-only-by-default path working as
intended.

## §Anti-pattern

- **Copying evidence into the case file.** Pasting a verification-protocol dimension table, a full event
  payload, or a diff into `errors/E-XXXX.yaml`. Case files are reference-first — link by anchor; the
  judgment matrix has one home (verification-protocol).
- **Promoting every friction.** A case file per friction recreates V1's 508-artifact accretion. Event-
  only by default; promote only at the hard-defect / N≥2 / owner-request boundary.
- **Dual-running the external auditor on every aspect.** Burns quota and invites cherry-picking. External
  confirms/rejects only at the promotion boundary.
- **Running `meta` routinely.** It is trigger-only; running it on an ordinary session is verification-of-
  verification, which the bounded anti-recursion rule forbids.
- **Silently working around a deviation.** If it ate time/tokens and you didn't record a `deviation_captured`
  event, the recurrence is invisible and will cost again.
- **Inventing a new taxonomy / scoring system / per-probe ledger.** Reuse the 20 CHARTER classes + the 5
  aspects; findings flow into the one errors channel.

## §Cites

- `patterns/verification-protocol.md` — the base check this EXTENDS (13 dimensions, two tracks, bounded
  anti-recursion). Reference-first source of the judgment matrix.
- `decisions/-error-friction-tracking-intent-vs-actual.yaml` — the governing decision (Architectural).
- `errors/_template.yaml` — the promoted-case-file shape.
- `CHARTER.md §AI failure classes` — the 20-class taxonomy (D11 / aspect 5). `§Principle 1` (anti-complexity,
  doc-health), `§Principle 4a` (external auditor independence), `§Principle 5` (single source of truth,
  reference-first), `§Growth` (growth-engine: repeated cases → new class).
- `AGENTS.md §events.jsonl schema` — `deviation_captured` catalog entry (formalized, renamed from `friction_captured` by); existing
  `failed_attempt` / `dissonance_detected` are the prior raw-observation events.
- `patterns/doc-conventions.md` — artifact-creation structure + authority boundary (canonical wins).
- `patterns/big-plan-checklist.md` — sibling discipline pattern (pre-work plan authoring; this is post-work).
- Downstream tasks: (events catalog) · (graph 11th node + indexing) · (CLI verbs) ·
   (cron auto-session). This pattern is the manual-first foundation.
