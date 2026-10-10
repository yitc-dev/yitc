---
name: background-session-operation
class: discipline
sourced_from: plan [[orchestrate-posture-for-the-main-session-6-amendme]] (the §6 orchestrate-posture amendment, now landed in CHARTER §6 + AGENTS) + the parallel-dispatch deviation cluster (2026-06-01/02/03) + two by-hand controlling-session runs (2026-06-04 / 2026-06-05)/ (per-write worktree isolation) + the land-as-crash-checkpoint discipline
applies_to: the orchestrate posture of an interactive CONTROLLER session (Build- or Review-typed) — when the interactive main session decomposes an owner-authorized batch, dispatches independent background Build sessions, gates cross-chain ordering, and monitors them. This pattern is the PROCEDURE only; the GOVERNANCE rule (the §6 amendment + named retirements) homes in CHARTER §6 + AGENTS (one home per rule).
---

# Background-session operation — the controller's how-to

> **STATUS: governance landed; post-amendment soak.** The §6/AGENTS amendment that makes the bounded
> orchestrate controller-selector the preferred main-session posture **has landed** (CHARTER §6 + AGENTS
> §Session-types → Orchestrate posture — the canonical governance home + the named retirements). The
> posture stays **owner-invoked** (named retirement (a) — the owner starts the session + authorizes the
> batch); it is no longer trial-gated. Plan [[orchestrate-posture-for-the-main-session-6-amendme]] is in
> its post-amendment realization soak. The guard rails below are this pattern's PROCEDURE; the governing
> rule + boundary live in CHARTER §6 + AGENTS (one home per rule).
>
> **Provider-neutral by rule (CHARTER §P4b).** Roles/mechanisms are named abstractly — «background worker»,
> «controller», «one-shot background-worker primitive», «session transcript», «external auditor», «test
> runner», «timed durable-state poll». No concrete tool/provider names appear in this normative body; the
> concrete-tool provenance lives in the owning plan's §Provenance note.

## §What this is — controller + workers

- **Worker = an ordinary Build session.** One task, its own `task/T-XXXX` worktree, all 9 stages, ends in
  `land`. If front-loaded with a dependency-CHAIN it runs task→land→task→land in sequence. Nothing new —
  already legal (one task at a time; a session may take further tasks in sequence).
- **Controller = the main session in orchestrate posture.** It decomposes the owner-authorized batch,
  dispatches workers, holds the cross-chain ordering, and monitors. It does NOT execute a task's 9 stages
  itself (it MAY, on owner say-so, but parallel dispatch is preferred).

- **The controller posture is TYPE-ORTHOGONAL — an interactive session of EITHER type (Build- or
  Review-typed) may control.** In its DISPATCH role the controller never executes a task's 9 stages and
  performs no source edits itself: dispatch is (a) read-only selection (`graph query --carve-out`), (b) spawning
  background workers — the spawned WORKER, not the controller, runs `worktree new --task` + claims +
  edits, (c) append-only journal events (the no-worktree exception), and (d) monitoring durable
  state. That footprint — read + journal-append only — sits comfortably **within a Review start-posture**
  (which is read-leaning by default, though it MAY also make a bounded direct edit — AGENTS §Review), which
  is why a Review-typed session may control while STAYING in its dispatch role (it delegates rather than
  executing the stages itself). **Reconciliation of the
  "controller MAY execute on owner say-so" allowance above:** that owner-say-so execution is a *separate
  Build action* (its own `task/T-XXXX` worktree, the AGENTS §Session-types narrow exception) — so a
  Review-typed controller dispatches but never itself runs a worker's 9 stages in-process; no self-contradiction. **Governance home:**
  CHARTER §6 + AGENTS §Review now carry this rule (the controller carve-out + the named retirements);
  the posture stays owner-invoked (named retirement (a)).
- **Non-binding type tendency (graduated from the MEMORY trial-note at the orchestrate-posture plan's
  realize, 2026-06-22 — an OBSERVATION, never a constraint).** Because the posture is type-orthogonal,
  the OWNER chooses the dispatch slice; type grants no dispatch-right and forbids none. The observed
  tendency is only that a **Build**-typed controller TENDS to dispatch the free/ready queue and a
  **Review**-typed controller TENDS to dispatch plan-cut tasks — a preference, not a rule, and no third
  type or permission change (a drafted per-type role definition was external-audit RED for drifting into
  role-taxonomy; resolved type-orthogonal). Either controller may dispatch either slice on owner cue.

## §Working rhythm — plan → dispatch → verify-with-controller-context → next

The economy this posture buys (owner direction 2026-06-06; context-economics prior-art
[[fresh-session-task-dispatch-context-economics-hand]]): the interactive controller holds the
EXPENSIVE strategic context — the plan, the discussion, the «why». Execution is what burns context
fastest (handbook bootstrap, test runs, two audit cycles per task), so it is pushed OUT to fresh
background workers whose context is disposable.

1. **Plan / discuss** in the controller — design, decompose, decide with the owner.
2. **Dispatch** the resulting tasks to background workers (selection via `--carve-out`); the controller's
   context is NOT spent on their execution.
3. **After each `land`**, the controller VERIFIES the result against its OWN retained discussion context
   — it remembers what was meant and why, so it judges «is this what we intended?» better than a worker
   can self-assess.
4. **Next** — dispatch the next batch, or correct the plan, as the verification and the owner direct.

A worker death costs only its disposable warm context (§land-after-each (`background-session-monitoring.md`)), never the strategic thread.

## §Launch — chains, front-loading, speed-FIRST (the DEFAULT; one scoped small-task cost-first exception)

> **ADVISOR BEFORE EVERY WAVE (mandatory step — run it FIRST, before you shape ANY wave).** Before
> planning EACH dispatch wave, run the read-only Axis-B advisor `bin/yitc-v2 journal query --dispatch-plan`
> (scoped `--plan <slug>` | `--tasks T-…`, ~3s — <workshop-spec>). It CONSUMES `graph query --carve-out`
> (SPEC-0044 eligibility: chains/clash/waits/in-flight) + `journal query --dispatch-readiness`
> (SPEC-0133 fleet-width) and hands you the proposed batch shape (which cards into which warm workers,
> how wide, in what order) + a `next:` handback of the judgements you still make yourself. Do NOT
> hand-plan waves from the prose below by memory — this advisor is the plan-time entry point; the prose
> is its detail home, not a substitute for running it. (Distinct from the readiness advisor `dispatch`
> AUTO-serves in its own pre-launch decision frame at line 1: THAT is fleet-width self-served at launch;
> THIS `--dispatch-plan` is the wider queue-shaping advisor YOU invoke at plan time and it is NOT
> auto-run.) **Why mandatory:** the 2026-07-10 drive ran ZERO advisor calls and hand-planned every wave
> (deviation — the discipline gap this step closes); the advisor exists precisely so queue-building no
> longer depends on recalling this wall.

> **LAUNCH POLICY (apply at dispatch — the controller decides without an owner prompt).** Speed-first
> among already-safe shapes is the **DEFAULT** (the §Guard-rails invariants are never on the trade
> table) — it holds for EVERY shape EXCEPT the one small-task cost-first branch named in line 4. WIDTH
> comes first and DEPTH second: fill every free stream of the fleet width before packing, and pack only
> the SMALL tasks no free stream could start now — a short chain's not-yet-ready tail, or independent
> tasks beyond the free streams (line 2) — instead of leaving them for later launches:
> 1. **Max parallelism is PRIMARY** — independent ready tasks → as many concurrent background workers
> as the collision-free topology allows, up to the fleet width the owner sets (currently 3 streams —
> `events.jsonl#ts=`). Never leave a free stream idle in order to pack. A LARGE
> or RISKY task (context-heavy, likely-to-block, wide blast radius) stays a singleton worker.
> 2. **SMALL tasks go 2-3 per warm worker by DEFAULT** (owner directive
> `events.jsonl#ts=`), in two shapes. (a) A sequential `requires:`-chain of 2-3
> SMALL tasks goes WHOLE to one warm worker, whether or not anything else is ready — only its head is
> claimable, so the chain could not use a second stream anyway; independent tasks fill the other
> streams. (b) INDEPENDENT ready SMALL tasks that outnumber the free streams are spread over every
> free stream, as evenly as possible and at most 3 per worker, rather than one per launch with the
> rest waiting — a worker MAY carry a single task when the count does not divide (3 small tasks and
> 3 free streams → 1+1+1; 4 → 2+1+1; 7 → 3+2+2). Each worker's ids are front-loaded as a static
> ordered batch: the Controller names the ids, in order, in the spawn brief
> (the in-bounds carve-out of `background-session-monitoring.md` §Guard rails item 2 — no new
> mechanism). Why it pays: the stage deliverer sends a spec ONCE per context epoch (`bin/lib/cli.py`,
> `if held.get(sid) and tee.hexdigest in held[sid]:` → a one-line `already delivered in this
> context epoch (unchanged)` pointer instead of the body), so the 2nd and 3rd task get the stage specs
> the worker already holds as pointers, and the ~123 kB seed is paid once; measured after the
> 2026-10-07..09 trims, a worker's protocol text is ~0.8-1.0 MB per task, so 2-3 fit one 1M-token
> context with room. **Stop rule — binds BOTH sides:** the Controller does not hand a warm worker a
> further task once its context has passed HALF its window or once it has halted (at an audit
> ceiling, on `blocked-on-land`, or on a pause); and the WORKER, before it claims each next id of its
> assigned batch, reads the `context:` line its own `session start` prints — past half, or after any
> such halt, it starts no further id, ends its turn after its last `LAND: OK`, and names the
> unstarted ids in its final report, which the Controller re-dispatches to a fresh worker. A longer
> chain splits across successive warm workers (2-3 + remainder).
> 3. **Tokens break ties only (in the DEFAULT regime)** — decide by token-economy ONLY between
> equally-fast shapes; never trade a faster front for a cheaper one — EXCEPT in the line-4 branch.
> Line-2 packing is not such a trade: it packs only tasks no free stream could start now.
> 4. **Small different-claim follow-ups → cost-FIRST (the ONE exception).** When several SMALL tasks each
> prove a DIFFERENT claim (so SPEC-0046's one-claim-per-accept-unit FORBIDS merging them into one
> task — the PRIMARY same-claim lever stays first when claims ARE homogeneous) AND each task's work
> is << one worker's bootstrap, ACCUMULATE the already-available ones (the followups buffer — the
> `followup` verb, SPEC-0095) and front-load the batch into ONE warm worker (bootstrap paid once)
> instead of one dispatch each. This is the ONLY case where token/bootstrap cost LEADS. **Release
> boundary (batch-bounded, CHARTER §6):** batch only the small followups ALREADY available in the
> current owner-authorized window and dispatch at window close — NEVER delay a ready task waiting for
> HYPOTHETICAL future small tasks (that is the forbidden self-fetch / autopilot wait); the owner may
> explicitly say "hold for N" to override.
>
> **Unchanged fence — the warm batch never widens it (CHARTER §6, carried verbatim):** no auto-launch / no self-fetch / batch-bounded / no stateful orchestrator / no in-process fan-out (no autopilot-FSM; a Worker is a separate sub-session, never an in-process subagent; no cap/queue-state machinery, no liveness-arming FSM, no role taxonomy; no decide-without-owner). The owner always authorizes the batch and makes genuine decisions.

**§Two axes — fleet-WIDTH vs tasks-PER-worker (orient before sizing a wave).** Dispatch planning moves on
TWO orthogonal axes; do not conflate them. **Axis A — fleet width** (how many workers run CONCURRENTLY) is
bounded by the box + the land frontier: detail-1's build-concurrency ceiling (the `journal query
--dispatch-readiness` advisor — nproc/loadavg/free slots) + the §Land-admission throttle (the smaller,
separate land-concurrency ceiling). The owner's "how much hardware" + "how many simultaneous lands" inputs
live HERE. **Axis B — tasks per worker** (how many tasks one WARM worker carries) is the front-load cap
(detail-2 chains + detail-4 cost-first small-tasks) — for SMALL tasks the default is 2-3 per worker
(policy line 2, with its stop rule); for the rest a controller judgement, NOT a number. This is the
"optimize context" lever: a fleet can be WIDE-and-thin (1 task/worker) or NARROW-and-warm (a chain/worker).
Axis A is a throughput/safety ceiling; Axis B is a context-economy choice under it — sized by §Tasks-per-worker
context sizing below. (Pointer only — each axis's rules stay in their homes named here, P5.)

The detail behind each policy line:

Planning policy (owner-set 2026-06-05): optimize **wall-clock SPEED first, token-economy second** — among
already-safe dispatch shapes only (the §Guard-rails invariants are never on the trade table). This is the
**DEFAULT regime**; the ONE exception is the small-task cost-first branch (detail-4 below — SPEC-0046 /
SPEC-0095), where for SMALL different-claim follow-ups bootstrap-economy LEADS.

1. **Maximize parallelism (primary).** Decompose into dependency-CHAINS (maximal `requires:`-ordered
   spines) + independent singletons. Default to the WIDEST collision-free front — independent
   chains/singletons → as many concurrent background workers as the topology allows. Do NOT serialize
   merely to save bootstrap cost — packing SMALL tasks 2-3 per worker (policy line 2) is not such a
   serialization: it applies only to SMALL tasks no free stream could start now (a short chain's
   not-yet-ready tail, or independent tasks beyond the free streams), never by leaving a stream idle.
   - **The build-concurrency ceiling is a controller JUDGEMENT bound against an owner-set SUGGESTED
     width (graduated from the MEMORY trial-knob at plan `orchestrate-posture-for-the-main-session-6-amendme`
     realize, 2026-06-22 — same form as the front-load cap; re-based on the owner constant).** When the owner gives an open-ended "drain the queue / run the free tasks"-style cue
     WITHOUT a stated parallelism, the controller bounds the concurrent background-dispatch workers by
     what stays collision-free + per-worker front-load-judgeable — a **ceiling, NOT a target**: orient
     around **`MAX_FLEET_WIDTH` = 8** (`bin/lib/journal.py`), the owner's per-server bound on concurrent
     workers, which REPLACES the earlier ad-hoc ≈5 trial-knob reference (owner_directive
     2026-07-11). You do not carry that number in memory — the **dispatch-readiness advisor ECHOES it**
     on every launch (`server bounds (SUGGESTED — never a coded cap): max_fleet_width=8 …`),
     so guidance and constant cannot drift. The topology + the §Land-admission throttle bound it LOWER;
     the owner overrides per command (named tasks | until the ready-queue empties | a specific N |
     "hold for N"). **Still no coded cap** — `MAX_FLEET_WIDTH` is **SUGGESTED**, a number the controller
     judges its wave AGAINST, and is DELIBERATELY NOT clamped into `recommended_wave_ceiling`
     (`bin/lib/journal.py`, the note): SPEC-0133 §6 («never a coded cap») makes a hard cap the
     forbidden orchestrator (CHARTER §6). Advisory, never a gate — an owner bound, not a machine one.
   - **`dispatch` SELF-SERVES the readiness advisory in the pre-launch decision frame — you no longer
     read the box yourself (MECHANIZED→/SPEC-0133 §6; supersedes the hand
     nproc/loadavg/worker-count RULE, AND the earlier manual pre-wave READ step).** The
     `dispatch` verb runs the `journal query --dispatch-readiness` fold ITSELF and PRINTS the advisory
     BEFORE the first launch line — fold → visible advisory → launch — so you size/confirm the wave
     against the LIVE numbers on screen, not memory (the missed-read failure this closed: 2026-07-10
     waves that skipped the manual read, deviation `dispatched-wave-without-consuming-dispatch-readiness`;
     consult `decisions/dispatch-readiness-delivery-audit-adhoc.yaml`, verdict A-with-bounds). The
     advisory returns `headroom` (nproc + loadavg +
     free_slots), `live_worker_count` (LIVE workers across EVERY session on this box — `task/` dispatches
     **AND** `work/<slug>` filing/interactive lands, not just this controller's), a
     `recommended_wave_ceiling`, `sole_controller`, and `in_flight_land`. You may still run
     `journal query --dispatch-readiness` ad-hoc between waves, but no SEPARATE pre-wave read obligation
     remains — the launcher delivers it at the chokepoint. This retires the hand reads
     (`nproc`/`loadavg`, the `git worktree list` cross-session tally, the `land-frontier` line) — the
     2026-07-02 miss (counting only `task/` dispatches, missing 2 concurrent `work/` lands → the box
     oversubscribed, `concurrent-land-thundering-herd-full-verify-per-ff-retry`) is exactly what
     `live_worker_count` now counts for you. **PACE refills by `in_flight_land`** — hold the next
     land-bound launch while a land is in flight, so the fleet fills as lands drain. The advisor is
     **ADVISORY, never a gate** (`recommended_wave_ceiling` you may ignore) — **NO scheduler, NO hard
     cap, NO queue-state machine** (the CHARTER §6 fence; §6-safe by the SPEC-0133 §1 test). Same class
     as every other §Launch/§Watcher (`background-session-monitoring.md`) discipline: an operating
     practice the controller honors, not a gate.
   - **LAND YOUR OWN BATCH AGAINST THE SAME SIGNAL — and prefer COMBINING filings to landing each
     separately.** The two `in_flight_land` disciplines above and below cover the fleet (pacing
     refills) and a NEW controller taking over an id-set (the §sole-controller check) — neither covers the
     controller's OWN land, which is the third case. **CHECK:** before landing your own filing batch, read
     `in_flight_land` off the same dispatch-readiness advisory you already have on screen. Since
     BOTH of its legs are process-based (`_work_land_proc_alive`, `bin/lib/journal.py`), so it reports a
     land actually RUNNING right now — a `true` reading means your land will queue behind that one for a
     reservation plus a full verify, and a human-facing land ends up waiting behind a bookkeeping one.
     **COMBINE — the BIGGER WIN, and the half not to lose behind the checking half:** consulting the signal
     only DEFERS a land; combining filings REMOVES one. A controller filing three cards in one sitting
     should land ONCE, not three times. The measured incident (2026-08-15): EIGHT separate filing batches
     landed several minutes apart, each paying its own reservation wait plus a ~6 min verify, when most
     could have ridden one batch (deviation `controller-lands-its-own-batches-without-consulting-in_flight_land`).
     Serialization made this WORSE, not better — those lands used to race and now QUEUE; the
     waiting is correct behaviour and is not the defect, MAKING a wait that did not need to exist is.
     **ADVISORY, never a gate** — same class as its two siblings: no new verb, flag or state, and **NO
     scheduler, NO priority lane, NO queue-state machine, NO hard cap** (the CHARTER §6 fence — the same
     fence that makes a land PRIORITY the wrong answer, since a priority needs an ordered queue where today
     there is only a lock). This buys the relief by not CREATING the work, never by reordering it.
2. **Front-load a chain into ONE warm worker.** A necessarily-sequential `requires:` chain goes to one
   worker, front-loaded into its spawn prompt (bootstrap paid once; context-locality bonus). A chain
   longer than the **front-load cap** splits across successive warm workers (cap + remainder).
   - **Re-based 2026-10-09 : SMALL tasks now carry a stated default of 2-3 per warm worker**
     (policy line 2 — its basis is the once-per-epoch stage delivery and the measured per-task protocol
     size, evidence the 2026-06 soaks below did not have). The history below stays as the record of the
     earlier judgement-only bound, which still governs tasks that are not small.
   - **The front-load cap is a controller JUDGEMENT bound, not a fixed number (re-tuned 2026-06-09).**
     The bound is what one warm worker can carry safely = **per-worker context budget + death-blast-radius**;
     the controller judges it per dispatch. **No magic constant** — the earlier provisional "3 tasks/worker"
     is DROPPED: across the orchestrate-posture trial soaks (batches 1-5, 2026-06-05..08) realized front-load
     was **1-2 tasks/worker**, "3" was never reached, and no chain was ever split by it; no context-pressure
     or blast-radius incident was attributable to chain LENGTH (land-after-each bounds the blast-radius
     independent of the count). So no evidence-grounded number exists to assert — the judgement bound stands
     in its place. (Re-tuning to a new constant "2" was rejected: the 1-2 observation does not establish that
     precision — CHARTER §P6.)
3. **Tokens break ties only (DEFAULT regime).** When two shapes are EQUALLY fast, prefer the one that
   front-loads chains (fewer bootstraps). Never trade a faster front for a cheaper one — EXCEPT the
   detail-4 small-task branch. (Policy-line-2 packing keeps the front as wide: it packs only SMALL
   tasks no free stream could start now.) *(Speed-first ordering — lines 1+3 — confirmed unchanged by the trial
   soaks: max-parallelism-primary held every batch; tokens never overrode a faster front in the
   default regime.)*
4. **Small different-claim follow-ups → cost-FIRST (the one scoped exception).** The trigger has TWO parts,
   BOTH required: (a) each task's work is **<< one worker's bootstrap** (a small follow-up — a one-liner,
   a tiny fix), and (b) the tasks prove **DIFFERENT claims**, so SPEC-0046's one-claim-per-accept-unit
   forbids merging them into a single task (when claims are HOMOGENEOUS the PRIMARY lever wins — one
   task, not this branch). Then the controller ACCUMULATES the already-available small follow-ups (the
   followups buffer — the `followup` verb, SPEC-0095) and **front-loads the batch into ONE warm
   worker** (the existing front-load mechanism, line 2 — bootstrap paid ONCE) rather than paying a fresh
   bootstrap per dispatch. This is the SINGLE case where token/bootstrap economy LEADS over raw
   parallelism; the §Guard-rails collision-free invariants still bound it (cost never overrides safety).
   - **Release boundary (batch-bounded — CHARTER §6 named retirement (b)).** Accumulate ONLY the small
     followups ALREADY available in the CURRENT owner-authorized batch/window, and dispatch the batch at
     the window's close. **NEVER delay a ready task solely waiting for HYPOTHETICAL future small tasks** —
     that would be the forbidden self-fetch / autopilot wait (§Orchestrate posture retirements). The
     owner may explicitly say "hold for N more" to override; absent that, available-now is the cut.
   - **Provenance:** the cost-first branch rests on SPEC-0046 (the merge-or-split claim test that makes
     a follow-up "different-claim"), SPEC-0095 / (the followups buffer = the accumulation surface),
     and (the trial-confirmed speed-first default this branch is the scoped exception to).

**§Tasks-per-worker context sizing — the Axis-B judgement residual (how many tasks in ONE warm worker).**
For SMALL tasks the front-load cap starts from the default of 2-3 per warm worker (policy line 2, with its
stop rule); the three bounds below are what SHRINK it, and for other tasks it is a controller JUDGEMENT, not
a number. The **COMPUTABLE factors that
judgement once weighed by hand — chain-grouping, effort-tier homogeneity, critical-path-shadow packing, and
fleet-width — are now COMPUTED by the read-only Axis-B advisor `journal query --dispatch-plan`** (<workshop-spec>). It CONSUMES `graph query --carve-out` (SPEC-0044 — chains/clash/waits/in-flight) + `journal query
--dispatch-readiness` (SPEC-0133 — fleet-width headroom) and proposes which ready cards pack into which warm
workers, in what order, how wide — tier-homogeneous, shadow-packed, fleet-width-bounded. **Do NOT re-derive
those operational rules by hand here** (this section is no longer a parallel source for them — read the
advisor's proposal). What the advisor CANNOT decide it hands BACK (its `Handback` block); that residual
judgement — a bound, none a coded constant — is all that stays here:

1. **`/compact`-threshold ceiling** *(the advisor's `compact-risk` handback).* Front-loading exists to pay the
   ~seed bootstrap ONCE. But a batch that pushes a warm worker PAST its `/compact` point mid-chain makes it
   re-read the whole seed — you re-pay the very bootstrap you were saving. The advisor SURFACES a group at
   compact risk; you decide: keep a batch under the worker's compact threshold; a context-HEAVY task (many
   file reads, a large diff) belongs SINGLETON, not chained behind others.
2. **Context-contamination (a QUALITY cost, not just tokens).** A fresh worker = clean context = independence.
   Warm-batching lets task-1's context (and any mistake/hallucination in it) bleed into task-2 — the seed's
   own confabulation incident (a worker inventing a foreign-scenario land-halt from inherited context). This
   is the ceiling on the detail-4 cost-first branch: bootstrap-economy never overrides the §Guard-rails
   collision-free invariants, AND it stops before a warm chain grows long enough to contaminate.
3. **Likely-to-block isolation.** A task with a real "ask owner" fork (architectural, ambiguous scope) can
   HALT mid-flow — and a block on task-1 of a warm chain freezes its warm siblings behind it. Singleton a
   likely-to-block task; do NOT chain others behind it. (Batch-LEVEL parking of an owner-question is SPEC-0126
   — park it, keep other independents moving; this is the IN-worker corollary: don't build the chain that
   parking then can't rescue.)

The platform primitive is a **one-shot background-worker** with **no warm session-continuation channel**
to the controller — so warm-reuse = front-loading the chain into the spawn prompt, NOT messaging a running
worker. A dead worker's warm context is unrecoverable (re-bootstrap). A mid-flight ASSIGNMENT change is a
planned stop → respawn → resume-from-claim-point, never an in-place edit (§Enrichment C5 of the picker plan).

**§Effort-tier-at-filing — set the worker's model/effort UP FRONT, not by a post-block bump (DISCIPLINE).**
The lever that routes a worker's model + reasoning-effort is the card's **`effort_tier`** (SPEC-0072, active) —
resolved at DISPATCH into a `(model, effort)` pair via `bin/effort-routing-config.yaml` (the §Dispatch-launcher
preflight — `background-session-dispatch.md`). So the discipline is: **tag a card substantive-vs-mechanical via `effort_tier` AT FILING/dispatch**,
so the worker is routed to the right weight from its FIRST turn — a substantive card is filed
`task file --critical` (or `--effort-tier critical`), a routine mechanical follow-up keeps the default `normal`.
Do NOT run a card at the default tier, watch a worker BLOCK because the too-weak low-effort route could not
carry it, then reach for a global `dispatch --effort` bump after the fact (the too-weak-low-route lesson): the invocation-level
`--model/--effort` override stays a per-launch ESCAPE HATCH, not the routing plan. Judging stakes at filing time
puts the routing where it belongs — on the card, read by every future dispatch. **This is adoption discipline
ONLY — no new mechanism:** the tier field, the `--critical`/`--effort-tier` filing flags, and the dispatch-time
tier→model/effort map all already exist (SPEC-0072); this adds no parallel weight taxonomy, only the habit of
setting the EXISTING tier up front.

**§Land-admission — the ENFORCED verify-admission serialization + the advisory wave-pacing layered over it (RULE → superseded by SPEC-0132).**
Build concurrency (the "max N background workers" launch knob, §Launch line 1) bounds how many workers
BUILD at once — it does NOT bound how many `land` verify+ff run SIMULTANEOUSLY. That is a SEPARATE
concern, because **each `land` verify is itself a CPU-saturating ~150-file PARALLEL test run**: unbounded
K simultaneous lands would oversubscribe the box. Real incident (2026-06-10, deviation
`concurrent-land-thundering-herd-full-verify-per-ff-retry`): ~6 workers reached `land` together → ~20
concurrent test procs, the box oversubscribed, `main` stalled ~10 min while every ff-race LOSER re-ran the
full verify on each retry. The concern is now bounded by a **code-enforced** admission governor with an
**advisory** controller pacing layer over it — two DISTINCT layers, not one soft ceiling:

- **ENFORCED — the SPEC-0132 verify-admission serialization (code, the true safety bound).** There is
  NO controller-honored fixed land-concurrency ceiling any more — the earlier provisional soft knob (a
  small default land-concurrency number, owner-tunable) is RETIRED. What ships instead is `land`'s own
  `_land_integrate` admission governor
  (`bin/lib/worktree.py`, SPEC-0132): before it runs the verify it computes a per-verify
  worker cap and a concurrency-slot count from the LIVE multi-resource host headroom —
  `_bound = _verify_worker_bound` (the MIN across cores/memory/fd-PID/disk-inode headroom),
  `_admitted_workers = min(_bound, _verify_worker_ceiling)` (the machine setting
  `lib.worktree._VERIFY_WORKER_CEILING`, its built-in default the code constant), and
  `_admitted_slots = max(1, _bound // _admitted_workers)`. The
  slot is a crash-safe `fcntl` flock semaphore (`_verify_admission`) held for the verify phase, so
  instantaneous workers across ALL concurrent lands **IN ONE REPO** ≤ `slots × W ≤` the host bound — a
  hard, code-enforced admission, NOT a best-effort discipline. SPEC-0132 is the SINGLE home of this
  model + the arithmetic (`bin/yitc-v2 graph query SPEC-0132`); this doc points at it and does NOT
  restate the value (Single SoT, P5).
  - **WHAT THIS POOL DOES NOT BOUND — read this BEFORE sizing a wave.** The pool is keyed
    **PER REPO** (`_verify_slot_dir` hashes `realpath(main_wt)`), so it has **NEVER** bounded
    **CROSS-PROJECT** land concurrency. Each project landing concurrently gets its OWN full pool. A low
    per-verify ceiling masks this by accident — it makes every repo's verify smaller — and a raised
    one removes that protection. The ceiling is a MACHINE SETTING (`lib.worktree._VERIFY_WORKER_CEILING`): read THIS host's value with `bin/yitc-v2 config list` before sizing, never a number
    remembered from another host. The width a verify actually runs at is
    `W = min(host bound, ceiling setting)` — the governor's resource bound still caps a larger setting.
    The arithmetic a controller needs, in two DISTINCT numbers — do not mix them:
    - **Pool CAPACITY per repo** — `slots × W`, where `slots = bound // W`. This is the most one
      repo's pool would ever admit; it is what the per-repo bound guarantees, not what a project
      normally draws.
    - **EXPECTED load per landing project** — **W workers**, because per-project
      serialization holds each repo to ONE land inside `merge → verify → ff`, i.e. one occupied slot.
      This is the number to size a wave with: N projects landing at once draw about N × W against the
      host's cores, so over-subscription begins at the first N whose N × W exceeds them.
    (The figures that stood here — 13, then 26 — were / history of the built-in default.)
    **Nothing in the code stops any of this** —
    the only bound on cross-project lands is the controller's own wave pacing below, which is why the
    disclosure lives here rather than only in a code comment.
  - **Observable wait :** while a land BLOCKS on a full slot pool it emits
    a throttled `waiting_for_verify_admission_slot` heartbeat (task_id-scoped; carries
    `branch`/`waited_s`/`slots`), so a queued land reads as ALIVE-and-landing, never a hang (the F2
    worker-death class) — see §Synchronous-to-LAND (`background-session-monitoring.md`). Since
     a repo's peers usually queue one step EARLIER, at the land reservation
    (`waiting_for_land_reservation`) — both rows mean "queued and alive", never a hang.
- **ADVISORY — controller wave-pacing, layered OVER the enforced serialization (throughput smoothing, not a safety bound).**
  Because the enforced serialization makes concurrent land-verifies WAIT (a queued land blocks on its
  slot), the controller still SMOOTHS the arrival rate so the box is not filled with land-bound workers
  all queued behind the single slot — this is throughput/latency hygiene, DISTINCT FROM (and no longer
  the safety guarantee for) the serialization above. Two controller levers, both already in hand
  (`decisions/land-concurrency-throughput-audit-adhoc.yaml`):
  1. **STAGGER launches** so workers' build-finish (and thus land) times do not synchronize — offset
     dispatch within a wave rather than firing all workers at the same instant.
  2. **PACE dispatch by the CROSS-SESSION land frontier.** The §Watcher (`background-session-monitoring.md`) dispatch-status reader
     (`journal query --dispatch-status`) classifies each worker's stage AND prints a
     `land-frontier (cross-session)` line (from `_live_land_frontier`) counting ALL live
     non-main worktrees — `task/` dispatches **AND** `work/<slug>` filing/interactive lands. Size the
     wave against THAT count, not just this controller's own dispatches: the 2026-07-02 recurrence
     (`concurrent-land-thundering-herd-full-verify-per-ff-retry`) sized wave-1 off 5 own `task/`
     dispatches and MISSED 2 concurrent `work/` lands → the box oversubscribed. HOLD the next
     land-bound worker while the cross-session frontier is deep.
- **Code-enforced backstop — the frontier-scaled retry backoff.** Because the pacing layer
  above is best-effort, `land`'s own optimistic-concurrency retry backoff
  (`_land_retry_backoff_seconds`) SIZES its de-correlation window by the SAME cross-session
  frontier: a wider observed wave → a wider backoff (capped) → concurrent advances COALESCE, so a
  losing lander re-merges the LATEST main and re-verifies ONCE, not one full verify per ff-race
  retry. This bounds the re-verify count when a herd forms; it is a `time.sleep` — NOT a lock/gate
  (land still converges identically; only timing changes).
- **Layer summary.** The ENFORCED verify-admission slot (SPEC-0132) is the hard safety bound that
  makes concurrent land-verifies serialize on a typical host; the controller stagger + frontier pacing
  are ADVISORY throughput smoothing over it (same class as every other §Launch/§Watcher
  (`background-session-monitoring.md`) RULE), and the frontier-scaled backoff is a timing-only backstop.
  Even without the advisory layer, any residual concurrent land is safe — the admission slot + `land`'s
  ff-only retry reconcile it (the incident was a throughput/oversubscription cost, never a correctness
  failure). Cross-ref §Watcher (`background-session-monitoring.md`) (the controller already watches lands) + §Cross-chain wait.

**Brief discipline (controller-side, from the 2026-06-05 run):**
- **Verify verb invocations in the brief against the LIVE `--help` surface** before dispatch — a wrong
  flag propagated to 2 workers in one run (each burned a failed invocation; the cause fingerprint is
  `controller-brief-propagates-wrong-verb-flag`). Safer: name the verb and let the worker consult help.
- **«Run SYNCHRONOUSLY to LAND» is now AUTO-INJECTED by the verb — the brief need not restate
  it (see §Synchronous-to-LAND (`background-session-monitoring.md`)).** A headless one-shot worker that backgrounds a step + yields exits
  before `land`, so the `dispatch` verb PREPENDS the standing `DISPATCH_WORKER_PREAMBLE` (run every step
  in the foreground through `LAND: OK`, never `run_in_background` a long step / never background-and-await,
  + the subagent-role rule) to every brief. The controller MAY still reinforce it in the brief, but a
  hand-omitted brief no longer drops the contract — it is on by construction.
- **The task YAML is authoritative; the brief is a snapshot.** Scope can go stale between filing and
  dispatch under concurrent lands (a sibling already shipped half the scope — the
  `task-scope-stale-after-concurrent-land` case). Briefs say so; workers re-derive at Stage-1 against
  their own branch point.
- **Never write a pointer to an id you have not allocated yet** — id allocation is cross-worktree and
  concurrent; allocate via the filing verb FIRST, then record pointers (the / followup-pointer
  race).
- **STOP hand-writing premise-verification into a brief — it is a Stage-1 DUTY now.** Every
  executing session already owes the narrow premise check at Analysis (the duty + its scope, its
  not-applicable branch and its bounds live single-SoT in **SPEC-0032 §Internal step 2** — `bin/yitc-v2
  graph query SPEC-0032`; not restated here). So a brief must NOT re-type «verify the premise before you
  claim / check the stated cause still holds»: hand-typed, it reaches only the workers the controller
  happened to word it for, it is reworded per card (~10 times, differently each time, in one 2026-08-13
  session), and it reads as a per-card favour instead of a standing duty. What the brief still owes is
  the FACTS — name the card's stated cause and where the evidence sits — and then let the spec own the
  duty. Same removal shape as the SYNCHRONOUS-TO-LAND bullet above: once a contract moved to a standing
  surface, the brief stops carrying it.

## §Selection — `bin/yitc-v2 graph query --carve-out` FIRST; hand procedure = fallback + explanation

> **The carve-out verb SHIPPED (SPEC-0044 active, 2026-06-06).** The selection is COMPUTED:
> **`bin/yitc-v2 graph query --carve-out`** returns `{chains, singletons, waits (release
> predicates), clash_report, in_flight}` — reading the projection + the live worktree list + the
> ready set ITSELF (a hand-screen from task prose is never the substrate — the §C1
> discipline-under-load class the verb exists to remove). **Recompute after every `land`** (a
> selection is a snapshot). The `clash_report` carries the ONLY owner questions; `waits` are silent
> sequencing. What the verb deliberately does NOT do (SPEC-0044): rank/launch the safe shapes
> (§Launch above owns that), reserve tasks (SELECTION ≠ RESERVATION), or the floor-task
> code-overlap judgement — step 4 below stays a CONTROLLER DUTY. The numbered procedure below
> remains as the FALLBACK (verb unavailable) and the explanation of what the verb computes; steps
> 3–4 stay live duties either way.

The collision screen is **spec-lineage ONLY**:

1. Read the ready set + their `requires:` edges + the in-progress set (the live worktree list → each
   `task/T-XXXX`). The in-progress set is a FIXED frontier — exclude any ready task sharing an
   activating-spec lineage with one in flight.
2. **Collision = activating specs share a lineage.** Ordered (`requires`/`supersedes`) → NOT parallel but
   legitimate: the later task simply **waits** (silent sequencing). `multi-proposer-unordered` (≥2
   `proposed` specs reshape the same target, no order — the shipped `graph query --projected` flag) →
   **owner question** (set an order / merge / drop one), per P7.
3. **Put a real claim-dependency in the machine-readable `requires:` edge — never owner memory** (a missing
   edge admits a race; a false edge throttles the front). A downstream **verifier** task is ineligible
   against a contract still being written — eligibility gates on the depended-on surface being
   **settled/landed**, not merely filed.
4. **Code overlap — a CONTROLLER-JUDGMENT screen on the TOUCHED SYMBOLS, not output-file names.** Read what
   FUNCTIONS / regions each task EDITS (its scope text / declared touch-surface — `expected_touch` when set), NOT the artifacts it produces. Two outcomes:
   - **Same file, DIFFERENT function → benign git ff land-reconcile → PARALLELIZE** (unchanged): leave it to
     surface at `land` as a cheap reconcile (the real runs cost ~one benign reconcile, lost nothing — §M2).
   - **Same FUNCTION / shared dispatcher / shared `argparse` option → STRONG overlap → a NON-benign semantic
     land-conflict → CHAIN** the two: front-load both into ONE warm worker so the second builds on the
     **settled** first, never racing it from a stale branch point.
   The screen reads SYMBOLS because **disjoint output files do NOT imply disjoint code** — the exact
   controller miss in the `_run_view` deviation (fingerprint
   `concurrent-view-lens-tasks-both-extend-run_view-dispatcher-nonbenign-land-conflict`):
   (task-scorecard) ∥ (trend-report) were judged independent on «separate `views/*.yaml`», but BOTH
   rewrote the shared `bin/yitc-v2#_run_view` dispatcher with incompatible signatures + each added a
   `graph query` argparse option → ``'s `land` hit a real non-union conflict needing a hand semantic
   merge (the second landed CORRECTLY aborted, work intact — but the cost was a manual merge the screen
   should have pre-empted by CHAINing 395→396).
   This is a manual controller-judgment refinement only; the **carve-out VERB's automatic code-overlap
   pre-screen stays DEFERRED** ([[parallel-work-preparation-carve-out-picker]] §Scope / §DEFERRED-code-overlap-proxy)
   — that auto screen is gated on its own separate pain-record (the `_run_view` case is its N=1), at coarse
   granularity only, never AST-derived.

## §Cross-chain wait — home it in the CONTROLLER, not a self-waiting worker

When a chain-tail `requires:` a task in ANOTHER chain, the release condition is the deterministic predicate
**`all(requires) == done on main`**, which flips when the last constraining task lands. **Home the wait in
the controller** (it already watches lands) — release the dependent chain-tail when the predicate flips. Do
NOT make the worker block on its own `requires:` (it pays idle-cost — an idle session is not a free wait,
every poll is a turn — and adds a liveness/stuck class). The controller-gated release keeps the worker a
pure executor; selection + dependency-gating live in the controller.

## §Sole-controller guard — one controller per owner batch across a session refresh (RULE)

**The trigger is the SESSION-REFRESH SEAM.** When the owner cues «obnovim sessiyu» / «refresh session»
(SPEC-1004 — the session refresh hand-off rule; lineage <workshop-spec> → <workshop-spec>), the controller produces one fresh-session hand-off and a
NEW controller session picks up the same owner-authorized batch. The hazard: the NEW controller starts
dispatching or working the batch while the PRIOR session — or a background `land` it left in flight — is
STILL acting on the same ordered chain, so **two controllers drive one batch at once** (fingerprint
`concurrent-double-controller-on-one-owner-batch-via-session-refresh-seed`). Concretely a session refresh
mid-chain spawned two sessions both driving one ordered regrade spine (fingerprint
`concurrent-two-sessions-driving-one-ordered-b5-regrade-chain`) — duplicate dispatch onto the same chain
tasks, racing the cross-chain release each controller thought it owned.

**The batch-ownership KEY is the explicit owner-batch task-id SET.** The handoff is keyed by the EXACT
set of task ids the owner authorized for THIS batch (the ordered chain + its singletons) — not a fuzzy
"the work we were doing". The seam contract is symmetric: **the moment the prior controller produces (and
the new one consumes) the refresh-seed, the PRIOR controller STOPS dispatching, releasing, or working that
id-set** — a single seed-consumption transfers sole ownership of the named id-set, so the two controllers
cannot both believe they own the chain tail. The new controller's check below is THEN over that exact set.

**RULE — sole-controller check BEFORE dispatching or working.** On receiving a refresh-seed, the NEW
controller — BEFORE it dispatches any worker, releases any cross-chain wait, or works the batch itself —
verifies it is the **SOLE** controller acting on the owner-batch id-set, by reading durable state (NEVER a
transcript / opaque guess — §Monitoring (`background-session-monitoring.md`)). Read the two signals off the
**`journal query --dispatch-readiness` advisor** (MECHANIZED/SPEC-0133 — do not hand-assemble the
liveness/land-frontier reads):
- **No live prior CONTROLLER session** on the same id-set — the advisor's **`sole_controller`** signal
  (with its live-controller count) is the read: it counts live controllers dispatching in the window, so
  `sole_controller: true` confirms no prior session is still driving the chain. Corroborate scope against
  the owner-batch id-set via the per-worker `journal query --fleet-verdict` verdicts (every worker the prior
  session launched for an id in the set reads a terminal verdict, none still `working` + un-landed).
- **No background `land` is in flight** on the id-set — the advisor's **`in_flight_land`** signal: a
  committed-but-landing task means the prior controller's last `land` has not reached `LAND: OK <sha>` on
  `main`, and a new controller that re-dispatches / releases the chain-tail now races it. Wait for
  `in_flight_land: false` before acting.

Only once BOTH are confirmed clear does the new controller dispatch / release / work. The check is the
controller analog of the per-worker §Dispatch in-flight pre-flight guard (—
`background-session-dispatch.md`) — an ADVISORY
read-only durable-state read, NOT a lock/lease (no autonomy-FSM — CHARTER §P1); it narrows the
double-drive window, and any residual concurrent action is still safe because `land`'s ff-only retry
reconciles it (the cost is wasted redundant dispatch + a racy release, never lost work).

**Clean-seam handoff discipline (the prior controller's half).** The refresh-seed should be produced at a
**clean seam** — a point with NO in-flight `land` and NO half-dispatched wave on the shared chain: finish
(or let `land` complete to `LAND: OK`) the current land-bound worker, stop launching the next wave, and
THEN write the hand-off. A seam taken mid-`land` or mid-wave hands the new controller an ambiguous frontier
(is that worker mine to wait on, or dead?) — exactly the state the sole-controller check above must then
disambiguate. Producing the seed at a clean seam makes the new controller's check a cheap confirmation
rather than a recovery (cross-ref §Abnormal situations in `background-session-monitoring.md` for the recovery path when the seam was NOT clean).

### §Concurrent live controllers — two live owner windows on one concern (RULE / X-0430)

**The trigger is NOT a refresh seam — it is two CONCURRENTLY-LIVE controller sessions.** The guard above
keys off the session-REFRESH handoff (one session hands the batch to its successor). But the owner may
have TWO interactive controller windows open at once, each driving the same owner concern with NO handoff
between them — and there the batch-id-set key does not exist. This is the X-0430 class: on 2026-07-16 two
live <project> controllers built duplicates TWICE in one day ( refused as a byte-equivalent of
landed; collided with on 3 files — 2 full worker builds + a hand merge burned). The
hazard is structural: a controller's filing/claim read screens against LANDED state (the graph index) plus
the `task/T-XXXX` claim frontier, but a peer session's **filed-but-unclaimed card** and its **`work/<slug>`
batch intent** live in an UN-LANDED worktree — invisible to the other session until land.

**The cross-session check — the filing/claim in-flight-intent advisory.** At BOTH filing
(`task file`) and claim (`worktree new --task`), the SPEC-0044 preview now ALSO folds the OTHER live
worktrees' in-flight intents: it scans `git worktree list` (excluding this checkout's own branch), diffs
each live `task/` + `work/` branch's changed files vs `main` — reading un-landed filed cards' title/scope
AND the `work/<slug>` branch slug + changed-file set (so a cardless work batch on concern K surfaces too) —
and prints a report-only advisory when one overlaps this card's concern (the shared filing-preview
`_overlap_via` title/path rule + a plain expected_touch↔changed-file intersection). This is the two-live-
windows analog of the refresh-seam `sole_controller` check above: an ADVISORY read-only durable-state read,
**NOT a lock/lease/reservation/FSM** (SPEC-0044 §4 read-only invariant — CHARTER §P1 / non-goal #7). It
narrows the double-build window; any residual concurrent action is still safe because `land`'s ff-only
retry reconciles it (the cost is a wasted redundant card/build, never lost work). When the peer branch
lands or is removed, its intent is on `main` (or gone) and the advisory disappears — the read discriminates.

---

> **Split note (per SPEC-0120 §3 per-doc size band).** This how-to is now THREE
> single-read-safe siblings:
> - **This file — LAUNCH + selection + coordination:** §What-this-is, §Working-rhythm, **§Launch**,
> **§Selection**, **§Cross-chain-wait**, **§Sole-controller**, **§Concurrent-controllers**.
> - **`patterns/background-session-dispatch.md` — WORKER-DISPATCH-MECHANICS :**
> **§Dispatch — worker session identity**, the **§Dispatch launcher**, the **worker fail-closed
> self-check**, **§Dispatch mode + full-lifecycle**, and **§Long-command-exceeds-tool-timeout**.
> - **`patterns/background-session-monitoring.md` — LAND-RHYTHM / MONITORING / RECOVERY :**
> **§land-after-each**, **§Synchronous-to-LAND**, **§Monitoring**, **§Watcher**, **§Recovery-trigger**,
> **§Abnormal situations**, **§Guard rails**, **§Stale-worktree hygiene**.
