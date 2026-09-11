---
name: background-session-dispatch
class: discipline
sourced_from: split from [[background-session-operation]] (per SPEC-0120 §3 per-doc size band — the operation file crossed the one-bounded-read ceiling) — the WORKER-DISPATCH-MECHANICS half. Substance sourced as in the parent — plan [[dispatch-via-sub-sessions-only-subagents-forbidden]] (the M2 session-identity contract) + [[orchestrate-posture-for-the-main-session-6-amendme]] (the §6 amendment)// (the blessed launcher + worker fail-closed self-check + the standing preamble) + X-0445 (the long-command detached-launch recipe).
applies_to: the DISPATCH mechanics a controller + its background Build workers rely on — the M2 worker-session-identity read-gate anchor, the blessed `bin/yitc-v2 dispatch` launcher contract, the worker fail-closed self-check, the separate-sub-session-only dispatch shape + full-lifecycle adherence, and the long-command detached-launch recipe. Sibling of [[background-session-operation]] (the LAUNCH + selection + coordination half) and [[background-session-monitoring]] (the land-rhythm / monitoring / recovery half). This pattern is the PROCEDURE only; the GOVERNANCE rule homes in CHARTER §6 + AGENTS (one home per rule).
---

# Background-session dispatch — worker session identity, the launcher, and the long-command recipe

> **Split sibling (per SPEC-0120 §3 per-doc size band).** This file carries the
> WORKER-DISPATCH-MECHANICS half of the controller how-to — **§Dispatch — worker session identity**,
> the **§Dispatch launcher**, the **worker fail-closed self-check**, **§Dispatch mode + full-lifecycle
> adherence**, and **§Long-command-exceeds-tool-timeout**. The LAUNCH + selection + cross-chain +
> sole-controller half stays in the sibling `patterns/background-session-operation.md`; the
> land-rhythm / monitoring / recovery half is in `patterns/background-session-monitoring.md`.
>
> **Provider-neutral by rule (CHARTER §P4b).** Roles/mechanisms are named abstractly; concrete
> tool/provider bindings (the `the AI provider`/`<external-auditor>` launch adapters, the `env -u` carrier scrub, the
> permission flag) live ONLY in `bin/yitc-v2` code, never in this normative body.

## §Dispatch — worker session identity (the read-gate anchor, M2)

> **RULE (M2 dispatch-uniqueness contract — the enforcement side of plan
> [[dispatch-via-sub-sessions-only-subagents-forbidden]] §Step 1).** Every dispatched background
> worker MUST have BOTH of these, or its commit/close will be refused:
> 1. **(a) The worker emits `session_started`** — it runs `bin/yitc-v2 session start --type build` at
> startup. This event is the **anchor** of the SPEC-0050 read-gate evidence window. As of **
> the gate is FAIL-CLOSED**: a worker whose `session_ref` has NO `session_started` in its checkout
> has no valid evidence window, so `task commit` / `task close` REFUSE (the refusal names the fix —
> run `session start` in that checkout, which writes the anchor locally; the retry then anchors —
> deadlock-free, SPEC-0050 §3). A compliant worker that already started its session is unaffected.
> 2. **(b) The dispatcher gives each worker a fresh, distinct per-worker session identifier — by
> SCRUBBING ALL inherited session-identity carriers from the launcher environment, THEN setting a
> fresh one** — so two concurrent workers never share a `session_ref` (a shared ref would let one
> worker's contract fetch cross-credit another's commit/close — the within-fleet cross-credit
> SPEC-0050 was hardened against; the session_ref-only model is safe ONLY because dispatch gives
> distinct refs). **Setting a fresh id alone is INSUFFICIENT (the §Findings H1-CAVEAT):** if the
> launcher shell exports an inherited identity carrier, the highest-precedence carrier OVERRIDES the
> freshly-set id for at least part of the worker's tooling reads, transiently collapsing the
> controller↔worker `session_ref`. The guarantee is therefore **scrub-the-WHOLE-carrier-set, then
> set** — fix by CATEGORY (scrub every member of the identity-carrier set, not just the one carrier
> observed to leak), so an unmodeled or newly-added carrier cannot survive the scrub.

**Why this is the M2 contract.** The read-gate (SPEC-0050) credits a governing-contract read by
`session_ref` + an in-window `cli_invoked`. Both halves of the identity matter: the **anchor** (a)
bounds the window (no stale pre-session read counts; no unanchored admit-any), and the **distinct
ref** (b) keeps the window private to one worker (no cross-worker credit). Together they make «this
worker fetched this contract this session» an honest, non-forgeable precondition.

**Anchor requirement is CUED at claim.** The per-checkout anchor requirement applies to ANY
claim — a dispatched worker AND a manual interactive `worktree new --task` — because each worktree is
a separate checkout with its own journal, and the read-gate reads the CURRENT checkout's journal. So
`worktree new --task` now PRINTS a cue at claim (before the Stage-1 guidance): run `session start` in
the new worktree FIRST, before any `graph query <SPEC>` read or gated verb — reads done before the
anchor are not credited. This is **cue-only, fail-closed**: `worktree new` does NOT auto-emit a
`session_started` anchor. Env-ABSENCE (`YITC_EXPECTED_SESSION_REF` unset) is NOT treated as
authenticated «interactive» — it is fundamentally ambiguous (an interactive human OR a miswired
keyless worker), so auto-anchoring it would let a miswired worker bypass the fail-closed backstop.
The anchor stays emitted ONLY by `session start` (which also runs the self-check for a keyed
worker). The cue fixes discoverability (you no longer learn the requirement only at a commit/close
refusal); it changes no gate behaviour — the content-rule is SPEC-0042 §2 / SPEC-0050 §2.

**Concrete mechanism (example — the rule above is the contract, this is one way to satisfy (b)).**
The session-per-sub-session dispatcher **scrubs the whole inherited identity-carrier set, then sets a
fresh per-worker id** in the same launch — e.g.

```sh
# scrub EVERY member of the carrier set (env -u per var), THEN set the fresh id
env -u <provider-session-env> -u CODEX_THREAD_ID -u YITC_SESSION_REF \
  the AI provider --session-id <fresh-uuid> -p <brief> … # one worker
```

where `<provider-session-env>`, `CODEX_THREAD_ID`, `YITC_SESSION_REF` are the concrete members of
the resolution carrier set (`bin/yitc-v2#SESSION_REF_ENV_VARS`, highest-precedence first). The H1
live run got distinct ids natively (2026-06-07, 3 concurrent sub-sessions — plan §Findings H1 = PASS)
**only because that launcher exported none of these carriers**; the §Findings H1-CAVEAT showed that
when the controller's shell DOES export one (e.g. an interactive controller exporting its own
`<provider-session-env>`), the inherited carrier overrides `--session-id` and the ref collapses — so
the scrub is mandatory, not optional. The carrier names + `env -u` incantation above are
provider-specific (kept to this code example per CHARTER §P4b); the normative contract is
provider-neutral («scrub all inherited identity carriers, then set a fresh per-worker identifier»).

### §Dispatch launcher — the blessed verb `bin/yitc-v2 dispatch` (governing home of the W4 launcher)

> **This subsection is the single governing home of the dispatch-launcher contract** (SPEC-0005 rule 8
> «one home» — the contract lives HERE, not duplicated into a spec; it extends the M2(b) rule above
> rather than restating it). **Owner-invoked, never autopilot** — the orchestrate posture is now
> chartered (CHARTER §6 + AGENTS §Session-types), and named retirement (a) keeps it owner-invoked: the
> verb ships under owner direction, never as autopilot.

The hand-incantation above is now wrapped by **ONE blessed launcher verb** — so the env-scrub footgun
(the H1-CAVEAT) and the wrong-hand-typed-flag risk (`controller-brief-propagates-wrong-verb-flag`)
cannot recur per-launch:

```
bin/yitc-v2 dispatch --task T-XXXX (--brief "<prompt>" | -f <brief-file> | <stdin)
# LIST form — repeat --task to launch SEVERAL sequentially in ONE invocation:
bin/yitc-v2 dispatch --task T-A --task T-B --brief "<prompt A>" --brief "<prompt B>"
bin/yitc-v2 dispatch --task T-A --task T-B -f <brief-A> -f <brief-B>
```

**The brief is PREAMBLE + DELTA — the launcher composes the preamble itself.** What
`--brief`/`-f` carries is the **DELTA**: only what is specific to THIS dispatch. Everything the
Controller used to retype into every brief is **DERIVED at launch from durable state** and prepended —
the card (title, class, tier, `requires`/`cites`, scope, and its **acceptance VERBATIM**); every
`owner_directive` journal row covering that card, its plan (`decomposed_from`) or the `all` wildcard,
rendered **VERBATIM with its `events.jsonl#ts=` locator** (coverage through the same token-exact
SPEC-0204 rule 2 predicate `audit._directive_covers_task`, never a substring match); one «as shipped»
block per `requires` id the journal records as closed (title + closing commit + its P8 probe results);
the **stop/land contract**, which renders from the ONE template `dispatch.DISPATCH_STOP_LAND_CONTRACT`
— itself `_build_sync_to_land_rule(controller_lands=True)`, the SAME single source `SYNC_TO_LAND_RULE`
comes from, so the two land regimes share one escalation tail and cannot drift apart; and the current
venue line. The composed text is written **beside the launch log** (`<log>.brief.md`) and its path
rides the existing `bg_dispatch_launched` row as `brief`, so that locator resolves to the exact text
the worker read. Nothing here is a new store or event type. **`--brief-raw`** keeps the historical
verbatim pass-through for the rare hand-crafted case: no preamble, no composed file, no `brief`
locator. The composition **fails LOUD** (the launch is refused, naming `--brief-raw`) — unlike every
other advisory at this seam, a preamble that vanished silently would launch a worker believing its
brief complete while the owner's binding rules were missing from it.

**The launcher takes a LIST.** `--task` is REPEATABLE: the controller hands the EXPLICIT
ordered list of ids + one brief per task, and the launcher loops it, launching each worker
SEQUENTIALLY in one invocation. This is still the owner's explicit list — NOT selection / ordering /
retry (non-goal #7 holds). Brief pairing: one brief per task, supplied through EITHER repeated
`--brief` XOR repeated `-f` (in task order) XOR a single `stdin` stream (single-task only); **mixing
`--brief` and `-f` is rejected** (ambiguous task↔brief pairing). **Fail-closed preflight:** all ids
are validated (duplicates rejected) and all briefs resolved BEFORE any spawn — a bad invocation
launches NOTHING (no partial launch). **Why one invocation, not N concurrent ones:** the loop is
synchronous (no concurrency), so each `bg_dispatch_launched` append fully completes before the next
worker spawns — the appends are **SERIALIZED by construction**, avoiding the concurrent-append loss
that separate concurrent `dispatch` processes risked on MAIN's journal
(`startup-event-emit-silent-loss-concurrent-main-checkout`; `_append_event` additionally flocks the
file). The single-`--task` form below is the N=1 case of this same loop.

The verb performs exactly the blessed launch(es) (verb-design rubric: error-reduction +
control-chokepoint + journal-marking), and **nothing more** — it is a LAUNCHER, NOT an orchestrator
(NO selection / ordering / retry / wait / ownership FSM — CHARTER non-goal #7; selection stays the
controller's manual §Launch (`background-session-operation.md`) duty). For EACH task in the list it does:

0. **In-flight pre-flight guard — SKIP a spawn onto an already-claimed task**. Immediately
   before this task's spawn, the launcher re-reads the live `git worktree list` frontier (the SAME
   `_live_task_worktrees` substrate the per-task-id guard + the §Selection
   (`background-session-operation.md`) carve-out use). If a
   live `task/T-XXXX` worktree already holds the id, it does NOT spawn a redundant worker: it prints an
   advisory skip line (which worktree, which holder session per the stamp + the holder's last
   journal event) and emits ONE `bg_dispatch_skipped` event (below), then CONTINUES to the other ids
   (a per-task skip, NOT a fail-closed abort of the whole invocation). This kills the COMMON redundant
   dispatch BEFORE a wasted sub-session bootstrap — previously the collision surfaced only LATER, inside
   the worker at `worktree new` time (the guard, which remains the hard backstop). It is an
   **ADVISORY read-only guard, NOT a lock / reservation / lease** (no queue-state, no auto-adopt of a
   foreign worktree —): the per-task re-read narrows but does not eliminate the guard→spawn
   window; closing it atomically is the deeper PARKED reservation rule. Reading the frontier to
   REFUSE is not selection/ordering (non-goal #7 holds — the launcher still never PICKS what to run).
   - **In-flight-DISPATCH extension (X-0124).** The live-worktree read above is blind to the
     ~8s window where a SIBLING controller already launched a worker for this id but the worker has not
     yet bootstrapped its `task/T-XXXX` worktree — the worker journals `bg_dispatch_launched` on MAIN
     BEFORE creating the worktree, so two controllers reading the same ready queue both dispatch it (the
      worktree guard caught the double-claim only LATER, inside the second worker). So, AFTER the
     live-worktree skip, the launcher ALSO classifies the id via the existing dispatch-status reader
     (`_dispatch_status_events` + `_classify_dispatch` — Principle 1, no new store/mechanism): a
     `working` class with NO live worktree (the live check already `continue`d on a live one) == a recent
     launched-but-not-yet-claimed dispatch still in flight ⇒ SKIP (advisory line + a `bg_dispatch_skipped`
     with `reason: "in-flight-dispatch"`, `held_by: <sibling controller session_ref>`). A dead/stale prior
     dispatch classifies `silent_stop` (NOT `working`), so re-dispatch stays correctly ALLOWED. Same
     ADVISORY read-only character as the base guard (no lock/reservation — full atomicity is the
     PARKED); the recency window narrows but does not eliminate the guard→spawn race.
   - **What keys the SKIP, and the `--force` escape (X-0131).** The in-flight-DISPATCH SKIP keys
     specifically on a RECENT `bg_dispatch_launched` with no live worktree — i.e. a launch genuinely still
     in flight. A merely skipped/filed-only id (its events are only `task_filed` / `commit_landed` /
     `bg_dispatch_skipped`, with NO `bg_dispatch_launched`) is NOT in-flight and dispatches NORMALLY — a
     prior SKIP does not itself poison the id. To override the SKIP when you know the prior launch is dead,
     pass `bin/yitc-v2 dispatch --force`: it launches even when a recent launched-but-unclaimed dispatch is
     detected (the manual escape; the read-only guard is advisory, never a lock).
1. **Fresh, distinct session id** — a per-worker `uuid4` (the M2(b) distinctness guarantee, H1).
2. **Scrub ALL inherited identity carriers, THEN set the fresh id** — by CATEGORY over the whole
   `SESSION_IDENTITY_REGISTRY['env']` set ( single-SoT — never a hand-listed subset, so an
   unmodeled/new carrier cannot leak). This is the code form of «scrub the whole carrier set, then
   set» — it closes the H1-CAVEAT controller↔worker collapse structurally.
3. **Assign the `expected` identity as an EXPLICIT contract input** — carried to the worker as
   `YITC_EXPECTED_SESSION_REF`, a var DISTINCT from the resolution carriers (so it is never resolved
   AS the identity). This is the launcher half of the worker fail-closed self-check (the worker
   compares its resolved `session_ref` against `expected`; mismatch ⇒ fail-closed abort — its own
   task). `expected` is launcher-ASSIGNED, never env-resolved (external-review (3)).
4. **Prepend the standing worker-discipline preamble, THEN spawn the background worker**.
   Before the spawn, the launcher wraps the controller's brief with the standing
   `bin/yitc-v2#DISPATCH_WORKER_PREAMBLE` (via the pure `_compose_worker_brief` — the preamble LEADS,
   the controller's brief follows), so every headless worker is told the synchronous-to-LAND +
   subagent-role contract UPFRONT even if the brief omits it (§Synchronous-to-LAND (`background-session-monitoring.md`)). This is a
   STANDING wrap, not a brief composed from the task — `_resolve_dispatch_briefs` still only carries
   what it is handed (non-goal #7 holds). The spawn itself is the provider binding — kept in CODE only
   (`bin/yitc-v2#DISPATCH_PROVIDERS`, the `the AI provider -p --session-id` adapter; CHARTER §P4b). The
   worker is spawned with an **autonomous permission posture** : a headless background
   worker has no interactive approver, so it must NOT gate on per-action approval — otherwise it
   reads fine but fail-stops on its first governed write (claim / commit / land) with nothing to
   approve it. The concrete permission flag is a provider-bound bit and lives in code only (P4b);
   narrowing this full bypass to a data-driven least-privilege policy is the follow-up.
   Worker stdout/stderr → `.yitc/dispatch-logs/<task>-<id>.log` (scannable for a launch-time 401-death).
5. **Emit ONE dispatch event** — `bg_dispatch_launched` (the launch marker of the `bg_dispatch_*`
   family; lives in code + this pattern, NOT the SPEC-0025 catalog — same as `bg_dispatch_halted`),
   bound to the MAIN checkout's journal (append-only, no worktree —). Schema: `task_id: T-XXXX`;
   `data: {dispatch: <tag=task>, expected: <assigned worker session_ref>, provider, pid, log}`. The
   envelope `session_ref` is the CONTROLLER's; `data.expected` is the worker's assigned ref — so
   `data.expected != envelope session_ref` is the launch-distinctness probe.

The `bg_dispatch_*` family (code + this pattern, NOT the SPEC-0025 catalog) thus has: `bg_dispatch_launched`
(step 5), `bg_dispatch_halted`, and `bg_dispatch_skipped` (step 0 — the skip marker; schema:
`task_id: T-XXXX`, `data: {dispatch, reason, held_by: <holder session_ref|null>[, worktree]}`, bound to
MAIN's journal). `reason` is one of two: `"in-flight"` (a live `task/T-XXXX` worktree already holds the
id — carries `worktree`) or `"in-flight-dispatch"` ( — a sibling controller's recent
`bg_dispatch_launched` is still in flight, worker not yet at a worktree — no `worktree` key).

**Terminal token — the LAUNCH-mode transport acknowledgement.** A LAUNCH invocation ends
with ONE machine-parseable FINAL stdout line, the sibling of `land`'s `LAND: OK|ABORT` and
`dispatch --watch`'s `WATCH: …` — same parse-the-TOKEN-not-the-shell-exit contract, not a
second mechanism:

```
DISPATCH: <VERDICT> <id>=<outcome>[; <id>=<outcome> …]
# e.g. DISPATCH: MIXED =launched(expected=6f3a…); =skipped
```

`<VERDICT>` is one of **four** values: `LAUNCHED`, `SKIPPED`, `REFUSED` — the single per-task
outcome when every id in the invocation agrees — or **`MIXED`** when they do not. The per-id
fragments carry the same three outcomes: `launched(expected=<session_ref>)` (spawned, and its
`bg_dispatch_launched` row written), `skipped` (a step-0 in-flight guard deferred to a live sibling —
cleanly re-dispatchable later), `refused` (a confirmed-dead orphan whose worktree teardown was
REFUSED — needs a human `worktree adopt`/`park` before this id can move). Every id that reached an
outcome is rendered, so a LIST invocation stays readable from that one line.

**Token-present IMPLIES row-exists.** A `launched` fragment is composed only AFTER that task's
`bg_dispatch_launched` append RETURNS. The append is fail-closed by exception, so a failed write
emits no fragment for that id (and no token at all) — never a launched fragment over a missing row.

**It is a TRANSPORT ACKNOWLEDGEMENT, never authoritative proof of worker state, and its ABSENCE
proves NOTHING.** A missing token reads identically for a launcher still running, one killed
mid-flight, and a truncated capture. The durable discriminator stays the JOURNAL —
`bin/yitc-v2 journal query --dispatch-status` — and no recovery or decision path may read this token
back out of a captured log to decide dispatch state. Note also that it prints LATER than the
per-task lines, so it does NOT serve a MID-FLIGHT read; that is what the per-task FLUSH is
for (`controller-reads-an-unflushed-background-log-as-proof-a-dispatch-did-not-happen`).

**Wrapper rule (mirrors the land rule):** capture `2>&1` and match `^(DISPATCH:|yitc-v2:)`.
The fail-closed preflight (bad id, duplicate, brief mismatch, provider/product gate) refuses on
STDERR and exits before any token prints — a wrapper matching stdout alone would read that refusal
as a silent no-token run.

Provider-neutrality (CHARTER §P4b): the normative rule above is abstract («the launcher assigns an
expected worker identity, scrubs the inherited identity carriers, spawns the worker, emits a dispatch
event carrying `expected`»). The concrete bindings (`the AI provider`, `--session-id`, the `env -u` /
registry-scrub, the carrier names) live ONLY in `bin/yitc-v2` code, never in this rule text.

**Operator knob — <external-auditor> worker binary (concrete binding, operator how-to not normative rule).**
A <external-auditor> WORKER must run on an UNCONFINED <external-auditor>: the snap-packaged <external-auditor> blocks POSIX semaphores
(`/dev/shm`), so the worker's `land`-verify multiprocessing tests fail. Select the worker's <external-auditor>
executable EXPLICITLY with **`YITC_CODEX_WORKER_BIN`** (default bare `<external-auditor>` = PATH/snap, backward-compat;
the `_spawn_codex_worker` adapter preflights an explicit override before spawn). Pair it with
**`CODEX_HOME`** to REUSE the existing subscription auth — NO new login. EXPLICIT per-role selection only;
NEVER shadow the auditor's <external-auditor> in ambient PATH (a shadow already broke the auditor — a reverted
deviation). Canonical worker dispatch (auth reused, auditor untouched):
`YITC_DISPATCH_PROVIDER=<external-auditor> YITC_CODEX_WORKER_BIN=<unconfined-<external-auditor>> CODEX_HOME=<existing-<external-auditor>-home> bin/yitc-v2 dispatch …`.
Same provider-bound-in-code rationale as the `the AI provider` binding above (CHARTER §P4b).

### §Dispatch — worker fail-closed self-check + startup-frozen identity (the worker half of M2)

The launcher half above assigns `expected`; this is the **worker half** it named as «its own task». Two
coupled guarantees, both in `bin/yitc-v2` code (CHARTER §P4b — concrete carriers in code, rule abstract):

1. **Fail-closed identity self-check at session start.** Before any claim/worktree, the worker
   mechanically compares its **resolved** session identity against the launcher-assigned **expected**
   contract input. The check is **GATED on the worker contract being present** — a normal interactive
   session (no launcher, no `expected`) is unaffected. In worker-mode (contract present): a **mismatch**
   (resolved ≠ expected — identity collapse / foreign environment) **or an absent/ambiguous expected
   value** ⇒ **fail-closed ABORT before any claim/worktree**, emitting a refusal event from the
   pre-claim state (append-only journal, no worktree —). `expected` is read ONLY as the explicit
   contract input — **never** resolved from the ordinary identity carriers (no env-resolution fallback
   for `expected`; external concept-audit (3)), so the check cannot be self-satisfied. Worker-mode is
   identified by the **presence** of the contract input (the launcher sets it unconditionally; there is
   no separate worker flag). The residual miswired-no-contract case is backstopped by the read-gate's
   fail-closed `session_started`-anchor requirement (SPEC-0050) — a check-skipping worker still cannot
   commit/close.
2. **Startup-frozen session identity.** The session identity is **frozen at startup and immutable** for
   the worker lifetime: every later governed check / journal emit / read-gate consumes the **frozen**
   value, **never re-resolving from the drift-prone identity carriers**. The freeze is carried by the
   launcher-assigned contract input — assigned ONCE at dispatch, categorically distinct from the
   resolution carriers — which is the only anchor that survives across the worker's **separate
   per-invocation CLI processes** (session start / commit / close are distinct processes; an in-process
   snapshot alone cannot bridge them). This closes the start-only-checking gap (a later governed verb
   re-resolving from drifted inputs would otherwise bypass the startup guarantee — external
   concept-audit finding 1).

> The **land-checkpoint** read-check across all FSM stages is a SEPARATE rollout, gated on this soak —
> deliberately NOT in.

## §Dispatch mode — separate provider sub-sessions ONLY (in-process subagent Build workers forbidden)

> **RULE — the operational face of the standing AGENTS §"What is NOT in V2" «no subagent dispatch».**
> A background Build worker (one that claims a task, runs the 9 stages, writes the corpus) is
> dispatched as a **separate provider sub-session** — its own `session_ref` / checkout /
> audit-independence / 9 stages / `land` — and **never as an in-process subagent**. An in-process
> subagent Build worker has no **agent-identity**: fleet siblings collapse onto one shared
> `session_ref` (observed — the 167c561d batch: 7 parallel workers, identical `session_ref`), so the
> journal cannot attribute reads/claims and the read-gate cannot keep each worker's evidence window
> private (§Dispatch — worker session identity, M2). Separate provider sub-sessions get distinct
> `session_ref`s natively ([[dispatch-via-sub-sessions-only-subagents-forbidden]] §Findings H1).
> This section governs ONLY the Build-worker dispatch shape. The narrower carve-out — that subagents
> stay legitimate for **ephemeral read-only / research-helper roles** (exploration, parallel search,
> analysis fan-out) that do NOT claim a task or write the corpus — is **SETTLED** by
> [[orchestrate-posture-for-the-main-session-6-amendme]] §"Scope of the ban" (owner-clarified
> 2026-06-07) + [[dispatch-via-sub-sessions-only-subagents-forbidden]]; it is **CITED here, not
> re-decided** — the policy home stays the plan (single-SoT). So a dispatched worker MAY spawn
> read-only helper subagents and await them inline, but a Build-worker ROLE is never an in-process
> subagent (the rule above). The **CHARTER §6 ratification** of the orchestrate posture has **landed**
> (CHARTER §6 + AGENTS §Session-types); only the plan's `realized` finalization remains. The `dispatch` verb's worker preamble
> (`bin/yitc-v2#DISPATCH_WORKER_PREAMBLE`) operationalizes this carve-out for every dispatched
> worker. (Record-of-time: the 2026-06-06 owner-directed in-session subagent / workflow Build-worker
> dispatch candidate was exercised as a trial probe and **REJECTED** on exactly this agent-identity
> collapse; it is no longer a default — distinct from the read-only-helper carve-out, which stays
> legitimate.)

**§Dispatch worker — FULL-lifecycle adherence (RULE).** A dispatched Build worker runs the
**full 9-stage lifecycle through a governed `land`** — it does NOT hand-roll a shortcut. Concretely a
worker MUST: **(a) CLAIM via `bin/yitc-v2 worktree new --task T-XXXX`** (the worktree creation IS the
claim option B) and **NEVER `task pick`** (a READ-ONLY inspector that does NOT claim — the
 trap); **(b) WORKTREE-BEFORE-WRITE** every source/artifact edit (only journal `event` appends
are no-worktree); **(c)** run the external **`audit pre` (Stage 4) + `audit post` (Stage 8)** —
not skipped because the change "looks correct"; **(d)** integrate via a **REAL `bin/yitc-v2 land`** to
the `LAND: OK` token, **never hand-emit a `land_completed`** event to fake completion (the verb owns
that emit). This is the SAME standing claim/worktree/land rule the interactive flow follows (AGENTS
§Writes-happen-in-a-worktree) — restated here as the worker's brief because a headless worker that
slips it ships UNAUDITED code. The `dispatch` verb injects (a)–(d) into every worker brief
(`bin/yitc-v2#DISPATCH_WORKER_PREAMBLE` point 3). It is a **brief, NOT a hard commit-to-main gate** —
legitimate journal-append / emergency / recovery direct commits stay allowed (non-goal #7); the
post-hoc backstop is the report-only **`journal query --lifecycle-integrity`** sweep
(QUEUE §Re-review triggers), which FLAGS a dispatched land lacking its `worktree_created` +
`task_picked` + audit chain.

**Controller lesson (X-0044) — dispatch a lifecycle-heavy build on a CAPABLE model.** The
2026-06-20 X-0044 incident worker bypassed the whole lifecycle above (called `task pick`, never made a
worktree, committed straight to main, hand-emitted a fake `land_completed`, ran no audit) — and the
confounder was a **controller error**: that worker was mis-dispatched on a smaller model (sonnet),
while the PRIOR worker on the same chain, dispatched on a capable model (opus), ran the 9 stages
correctly. **Model capability affects protocol adherence**: when dispatching a build that must honour
the full lifecycle (claim → worktree → audit → land), route it to a capable model (`dispatch
--model`), not the cheapest tier.

**Observe via durable state, never an opaque guess (real incident — the AI-bench co-launch,
2026-06-06).** A batch dispatched as opaque one-shot workers HID two failures until they were dug out
of provider output files by hand: (a) a transient **auth-401** that killed all three workers at
launch, and (b) a **shared-worktree-parent collision**
(`bench-colaunch-shared-worktree-parent-collision`) where only the race-winner ran and the other two
HALTed. The remedy is NOT an in-session surface (that re-introduces the shared-`session_ref` collapse
above) but a **durable-state read**: the controller's near-launch verify reads
`journal query --dispatch-status` (the §Monitoring (`background-session-monitoring.md`) reader — the authoritative liveness/terminal
classifier) and confirms each worker's `worktree_created` / `task_picked` (the CLAIM) appeared within the
near-launch grace (§Monitoring (`background-session-monitoring.md`) «Launch-side liveness» — grace ≥ 10 min, the CLAIM is the positive signal,
a missing claim *within* grace is still-booting not death), catching a genuine launch-time failure (e.g.
the auth-401 above) WITHOUT false-declaring a slow bootstrap dead (cf. §Monitoring (`background-session-monitoring.md`): read durable state,
never guess; never auto-re-dispatch on a slow/ambiguous claim — surface to the controller).

- **The §Guard-rails (`background-session-monitoring.md`) invariants are PER-WORKER** — each worker gets its OWN `task/T-XXXX` worktree
  (isolation), its OWN external audit at Stages 4/8, its OWN full 9 stages + `land`, and its OWN
  distinct `session_ref` (the M2 dispatch contract above).

**Provider account/slot allocation is EXTERNAL infra — not a YITC controller duty (RETIRED).** YITC
is provider-neutral (CHARTER §P4b): it does NOT manage, reserve, or coordinate the provider's compute /
account / slot allocation — that machinery lives entirely OUTSIDE the corpus and is unactionable from a V2
controller shell. The controller carries **no slot-awareness duty**. YITC's only requirement under a
provider-side disruption is to RESUME work cleanly once the provider side is healthy, and that resilience is
ALREADY provided by the death/resume contract — **§land-after-each (`background-session-monitoring.md`)** (every task checkpoints onto `main`, so
a death loses only warm context) + **§Abnormal (`background-session-monitoring.md`) → 401-death recovery** (detect → adopt the committed worktree
→ re-audit → close → land). That contract is the **SOLE reliance** under provider-side disruption; no
pre-flight slot reservation is needed or attempted. *(Record-of-time: a prior pre-flight section asked the
controller to reserve the wave's active provider slot via an external env knob; retired because it
leaked external provider-infra into the corpus (§P4b) and was unreachable from the controller shell — the
reservation channel was the external crontab env, not the controller — deviation
`slot-reservation-preflight-unreachable-from-v2-controller-crontab-env-not-shell`.)*

## §Long-command-exceeds-tool-timeout — detached launch + bounded foreground poll windows (RULE)

> **The gap this closes (real incident — X-0445, 2026-07-16).** The worker preamble mandates
> **run every step synchronously in the FOREGROUND, blocking** AND forbids **background-and-yield**
> (§Synchronous-to-LAND (`background-session-monitoring.md`) — a one-shot worker's process EXITS when it
> yields, so a backgrounded step dies before it finishes). Both hold. But a command that runs LONGER
> than the tool's **hard foreground cap** (a ~16-min prod apply against a ~10-min bash cap) satisfies
> **neither**: foreground = killed mid-run by the cap; background+yield = process exit. The rules left
> that case with **no stated resolution**, and the reader's only visible exit looked like the forbidden
> one — **3 boomrocket workers died partly here; one backgrounded the apply and yielded → process
> exit → "died at Execution entry, zero prod actions"**. Same class kernel-side on minutes-long lands
> (fp `harness-kills-backgrounded-land-mid-verify-interactive-session`). This section states the
> resolution.

**The recipe — detach the PROCESS, hold the TURN.**

1. **Launch FULLY DETACHED** — `setsid` (own session + process group), stdout+stderr redirected to a
   **logfile**, stdin closed. Detached from the tool's process tree, the command survives BOTH the
   foreground cap AND the tool-call boundary; nothing kills it when a bash invocation returns.
2. **POLL the logfile in BOUNDED FOREGROUND windows that HOLD the turn.** Each window is a short
   foreground command (well under the cap) that tails/greps the log; when a window returns without the
   terminal token, **re-invoke the next window INLINE, in the same turn**. You never yield.
3. **GATE on TERMINALITY, which has exactly TWO forms** — the command's own contracted final-line
   token (prior-art: `land`'s `^LAND: (OK|ABORT)\b`), **OR the detached PROCESS EXITING**.
   Nothing else is terminal: not wall-clock, not log length, not log quiet, not vibes — and above
   all **not a bare `yitc-v2:` line** (see the capture-vs-terminality rule below). Neither form
   present = not done, keep polling. The process-exit form is what saves you when a command dies
   without printing its token; poll it as `kill -0 <pid>` beside the token grep, and read the log
   for the verdict once either fires.
4. On the token: read the log's verdict and continue the lifecycle **in the same turn**.

```bash
# 0. the log path carries a RUN DISCRIMINATOR — never a bare /tmp/<job>.log (see the RULE below)
LOG=/tmp/yitc-$YITC_EXPECTED_SESSION_REF-T-XXXX-<job>.log
# 1. detached launch — survives the tool cap AND the tool-call boundary.
# `>` (truncate), not `>>`: the log is THIS attempt's, so a retry's poll cannot see the last one's token
setsid bash -c "<long-self-verifying-command> > $LOG 2>&1" < /dev/null &
LAND_PID=$! #...or read a pidfile the detached shell wrote; you need a PID, not a pattern
# 2+3. bounded foreground poll window, re-invoked INLINE until token-or-exit
timeout 300 bash -c "until grep -qE '^<TERMINAL-TOKEN>' $LOG || ! kill -0 $LAND_PID 2>/dev/null; do sleep 10; done"
```

**EVERY READ YOU MAKE ABOUT YOUR OWN RUN IS SCOPED TO *THIS* RUN (RULE).** The recipe above
has a worker write a log, poll a token in it, and watch a process. Each of those three reads answers
"how is MY run doing?" — and each was observed answering it about a DIFFERENT run instead. The cheapest
form of that misread is a false GREEN (a foreign verdict banked as your own), which is why this is a
rule rather than a note: **eight captures over four days, 2026-08-30..09-02.** Three instances:

- **A scratch log carries a run discriminator — never a bare `/tmp/<name>.log`.** `/tmp` is HOST-GLOBAL
  on a box that runs many concurrent sessions and more than one user, and a task id is allocated
  PER-REPO, so `ap.log` / `tt2.log` / `suite2.log` are names several runs pick independently. Four
  times the path already existed owned by another session or user: the redirect was **denied, the verb
  never ran at all**, and the `tail` printed a FOREIGN task's audit verdict or suite failures as this
  run's. Put the file under your **worktree** (`.yitc/` there is
  gitignored, so it can never surface as land-blocking dirt) or give it `<sessionref>-<task>`. This
  EXTENDS the convention the engine already applies to the log it writes for you —
  `/tmp/yitc-land-{repo-slug}-{root-hash}-{task}.log` (`_land_log_path`, `bin/lib/dispatch.py`),
  shipped by off X-0994, which is the same false-GREEN class one layer down.
- **A re-land poll is anchored to THIS attempt's bytes.** The engine's start-detach land log
  (`.yitc/land-logs/<branch>.log`) is opened APPEND-ONLY across attempts — deliberately, so a second
  failure stays readable beside the first. The cost is that after an ABORT the previous attempt's
  `^LAND: (OK|ABORT)` token is still in the file, so a whole-file `grep` matches it and reports
  terminal while the new land is still verifying. The engine now stats the log
  BEFORE launching the child and prints its poll **already anchored** —
  `tail -c +N <log> | grep -qE "^LAND: (OK|ABORT)"` (`_land_log_new_attempt_offset` /
  `_start_detach_notice`, `bin/lib/worktree.py`) — so use the form it prints. For a log YOU spell, `>`
  rather than `>>` buys the same property by construction. **This does not relax SPEC-0180 rule 2c**:
  terminality is still token-or-exit and capture stays wide — what is scoped is only WHICH BYTES the
  token may be read from.
- **A liveness poll uses the child PID, never `pgrep -f` carrying text from its own argv.**
  `pgrep -f "task test T-XXXX"` invoked from a shell whose own command line contains that string
  **matches itself**, so it can never report the work finished — measured reading finished work as
  RUNNING for ~50 minutes. Hold the pid you launched and poll `kill -0 <pid>`. The
  governed reader `_session_proc_alive` (`bin/lib/journal.py`) already excludes its own pid and matches
  argv ELEMENTS rather than a flattened line; the hazard is named for the CONTROLLER's monitor in
  §Recovery-trigger (`background-session-monitoring.md`, the 2026-07-05 miss). This is that
  same rule stated for the polls a WORKER writes about its own children. No pid available? Ground-truth
  off the journal — never off a pattern that can match the process doing the asking.

**CAPTURE and TERMINALITY are two DIFFERENT obligations — admit the diagnostic channel, gate on
token-or-exit (RULE, SPEC-0180 rule 2c).** Both sentences, and they must never be collapsed into one
filter:
- **CAPTURE — redirect `2>&1` and admit `^yitc-v2:`.** A pre-verify REFUSAL (a missing `-C` target, a
  fail-closed session identity, any guard upstream of the terminal-signal seam) never reaches the
  contracted token: it prints as a plain `yitc-v2: …` line on **stderr** and exits nonzero. A watcher
  that captures only `^LAND:` on stdout turns that clear, correct refusal into an EMPTY log plus a
  generic "script failed exit 1" — silence exactly where the message was (X-0843). So capture
  the diagnostic channel.
- **TERMINALITY — token or process exit, never the prefix.** `yitc-v2:` is the tool's **GENERIC message
  prefix**, not a status contract: the same prefix carries ordinary progress (the graph auto-rebuild
  notice, the verify heartbeat). A `yitc-v2:` line is terminal only WITH an exit, never on its own.

**Name the failure that collapsing them causes**, because it is the one this rule was written from: a
poll loop keyed on `^(LAND:|yitc-v2:)` — the widened filter, correct for capture, wrongly used as the
terminal gate — **fired at 47 s on `yitc-v2: graph auto-rebuild (land) — 14 possibly-stale spec(s)`
while the land was still verifying**. The loop declared victory on a progress notice, the run exited,
and its premature exit then KILLED the healthy land through the worker-liveness binding. Capture-wide,
gate-narrow: a widened CAPTURE filter reaching the TERMINALITY decision is a false green that also
destroys the work it misread.

**ADMISSIBLE FOR `land` — this recipe is no longer barred from the one command it cites as its prior
art (SPEC-0180, shipped by).** The recipe was previously self-contradictory here: it
names `land`'s `^LAND: OK` token as its exemplar, while the shipped `YITC_SYNCHRONOUS_LAND` guard
refused exactly this shape for a worker land (captured as `deviation_captured` fp
`long-command-recipe-contradicts-synchronous-land-guard`). That P7 dissonance is resolved: a DISPATCHED
worker's `land` MAY run detached under this recipe when it presents a **held-turn claim** the land
verifies **server-side** against the pid in its own `bg_dispatch_launched` dispatch record (a
caller-asserted pid proves nothing and is refused). Fail-closed on every other form: no resolvable
dispatch record — an interactive land, a hand-run — means NO claim is admissible and the pre-existing
refusal stands unchanged. An admitted detached land is bound to the WORKER's process liveness and
terminates itself, with a journaled `land_worker_liveness_lost` record, if that worker dies. So the two
yield-shaped outcomes differ and must not be conflated: a **claim-free** detach is REFUSED AT
ADMISSION; a **claiming** worker that yields anyway is ADMITTED AND LATER KILLED. Both end with no
land; only the second leaves a running land to kill.

**APPLICABILITY BOUND — self-verifying commands ONLY.** This recipe is admissible **only** when the
detached command is **SELF-VERIFYING**: it either (a) commits + verifies its own work and emits a
contracted terminal token, or (b) rolls back cleanly on failure. Then the durable outcome is decided by
the command itself, and the poll window is only *observing* a verdict that exists with or without a
reader. **A NON-self-verifying command is NOT eligible** — detaching it means a session death leaves
**unverified, half-applied state** nobody adjudicates, which is strictly worse than the timeout it was
meant to dodge. If the command is not self-verifying, make it so (wrap it in a commit+verify+token or a
clean-rollback harness) before detaching it — do NOT detach it as-is.

**NON-WEAKENING — this does NOT relax SYNCHRONOUS-TO-LAND (explicit).** The rule home is unchanged:
**§Synchronous-to-LAND (`background-session-monitoring.md`)**. **The TURN IS HELD THROUGHOUT** — every
poll window is ordinary foreground work in the SAME turn, and the worker itself still reaches
`LAND: OK` before yielding. **Background-and-YIELD stays FORBIDDEN**, unchanged. The distinction that
makes this legal is exactly: **what is detached is the OS PROCESS, never the TURN.** A worker that
launches detached and then *yields* has not applied this recipe — it has committed the F2 death this
section exists to prevent. Nor is this a licence to force a blocked step through: the **SPEC-0103**
scope boundary is untouched — a block from an out-of-scope or environmental cause still STOPs and
escalates (`blocked-on-land <task> <reason>`), and no gate/test/guard is ever weakened to make a long
command pass.

**Anti-complexity (CHARTER §P1) — why this earns its place.** **F1 existing analog?** None —
`grep -rn 'setsid|nohup|detach'` over `patterns/` + `specs/` + `AGENTS*.md` and
`grep -rn 'foreground-timeout|timeout cap'` both returned ZERO for this sense; the closest kin is the
AGENTS-SESSIONS `land`-runs-for-MINUTES bullet, which splits foreground-vs-background by session kind
but is silent on exceeding a HARD cap. **F2 new entity or view?** A section in this existing pattern
file — no new verb, gate, mechanism, or store. **F3 what gets removed?** The "no stated resolution"
dead-end that made background-and-yield read as the only available exit. **F4 real incident?** X-0445 —
3 dead workers, one with zero prod actions — plus the same-class kernel fp above.

---

> **Split note (per SPEC-0120 §3 per-doc size band).** This file was carved from
> `patterns/background-session-operation.md` when that file crossed the one-bounded-read ceiling
> (831 lines / 73KB — over-ceiling on both the line and byte axes). The LAUNCH + §Selection +
> §Cross-chain-wait + §Sole-controller half stays there; the land-rhythm / monitoring / recovery half
> is in `patterns/background-session-monitoring.md`. Split relocates content — it removes nothing
> (SPEC-0120 §3 SPLIT-never-delete).
