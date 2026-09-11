---
name: background-session-monitoring
class: discipline
sourced_from: split out of [[background-session-operation]] (per SPEC-0120 §3 per-doc size band) — shares that pattern's provenance cluster (the parallel-dispatch deviation cluster 2026-06-01/02/03 + the controller watcher/recovery incidents 2026-06-05). MECHANIZED into a thin verb-pointing recipe by (plan [[mechanize-controller-worker-observability-into-rea]] CARD-4) — the hand-executed liveness/monitoring/fleet-sweep prose (~880 lines) was RETIRED in favour of `journal query --fleet-verdict` (SPEC-0133). The WATCH LOOP around that verb was itself mechanized by (`dispatch --watch`), retiring the hand-rolled poll snippet after the two 2026-07-09 watcher incidents (false ALL_TERMINAL from grep-absence; premature `blocked` from one transient snapshot).
applies_to: the LAND-RHYTHM + MONITORING + RECOVERY half of the orchestrate posture — after a CONTROLLER dispatches background Workers. The MONITORING READ is now the read-only verb `journal query --fleet-verdict` (SPEC-0133); this file is the thin OPERATOR RECIPE — the land-rhythm/worker rules + the recovery-ACTION taxonomy the verb deliberately does NOT prescribe (SPEC-0133 §2 — no recommended_action). The LAUNCH / DISPATCH / SELECTION half is the sibling [[background-session-operation]]. PROCEDURE + governance-only prose; the GOVERNANCE rule homes in CHARTER §6 + AGENTS + SPEC-0103.
---

# Background-session monitoring — the controller's land-rhythm, watch & recover half

> **MECHANIZED (SPEC-0133).** The controller no longer hand-executes ~880 lines of liveness prose.
> Worker liveness is now READ from ONE read-only verb — **`journal query --fleet-verdict`** — returning, per
> in-flight worker, its class + raw evidence + a non-mutating **verdict** (alive / dead / needs-decision).
> The former hand-executed multi-signal death test, the standing full-fleet sweep computation, and the
> by-hand process/argv liveness recipe are **RETIRED** — the verb computes them. What survives here is what
> the verb CANNOT carry: the land-rhythm + worker contract, and the recovery-ACTION taxonomy the controller
> (a human-in-the-loop) chooses from (SPEC-0133 §2 gives NO recommended_action). Read the verb, then act.

## §land-after-each — the crash-robustness checkpoint (RULE)

**A background task unit MUST end in `land`** — never carry a committed-but-unlanded task across a dispatch
boundary. `land` checkpoints the task onto `main` (the SOLE integration path): a worker death at task *k*
leaves tasks 1..*k*-1 PERMANENTLY on main, task *k* resumable from its retained worktree + `current_stage`,
tasks *k*+1..N un-started. Blast-radius of any death = «lose warm context», NEVER «lose work». `land` also
shrinks the in-progress frontier so currency re-evaluates dependents → land = checkpoint AND release-trigger.

## §Synchronous-to-LAND — a headless worker never backgrounds+yields (RULE)

**A headless dispatched (one-shot, NON-persistent) Build worker MUST run EVERY stage step synchronously in
the foreground through the `LAND: OK` token** — tests, commit, audit-post, close, AND land. Never background a
long step and yield: a one-shot worker's process EXITS when it yields, so it dies before land runs, leaving
the task built but UNLANDED (incidents). **The contrast is persistence:** an
interactive CONTROLLER may background a step and resume on its completion; a one-shot worker may NOT.

**What this rule actually protects is the HELD TURN, not the foreground process (SPEC-0180 rule 1 —
reconciliation, NOT a relaxation).** The single failure the paragraph above exists to prevent is: the worker
YIELDS its turn, its process exits, the step dies mid-flight. The property that prevents it is that **the
worker holds its turn until the terminal outcome** — NOT that the step runs inside the worker's own
foreground process group. Those two coincide for every step that FITS the harness's hard per-call cap, which
is why they were written as one thing; above the cap they come apart, and only the first is load-bearing (a
foreground land killed at the cap reaches no token either, so foreground-ness alone buys nothing there).
**So: what may be detached is the OS PROCESS, never the TURN.** A step whose runtime exceeds the cap may run
as a DETACHED process while the worker holds its turn in bounded, inline poll windows — the recipe +
its applicability bound live at **§Long-command-exceeds-tool-timeout (`background-session-dispatch.md`)**,
and for `land` specifically that shape is ADMISSIBLE only under the shipped held-turn claim (SPEC-0180 rule 2). **BACKGROUND-AND-YIELD STAYS FORBIDDEN, UNCHANGED** — a worker that launches
detached and then yields has not applied the recipe, it has committed the exact death this rule names, and
under the claiming path its land is then KILLED mid-flight by the worker-liveness watchdog (`main`
untouched; recover via the idempotent `worktree recover-land`). Nor is any of this a licence to force a
blocked step through: the scope boundary below (**SPEC-0103**) is untouched.
**Interactive long/admission-wait land — wrap in Monitor, key recovery off the JOURNAL (2026-07-18,
fingerprint `interactive-background-land-killed-in-admission-wait`):** under verify-admission contention a
long wait outlives BOTH a plain background land (swept nondeterministically) AND a plain foreground one
(the harness ~600s cap kills the group at its move-to-background boundary), so the controller runs the
land under the harness **Monitor** primitive (persistent watch-until-condition wrapper that outlives one
turn/cap — survived 2/2 incl. hour-long waits) and keys ALL recovery off the JOURNAL (`LAND:` token +
admission heartbeats + the IDEMPOTENT `worktree recover-land` / re-`land` verbs, §Abnormal), NEVER off the
wrapper's process lifetime. Parallel lands stay — NO fan-out cap (owner directive 2026-07-18); harden the
machinery, do not serialize. This is the seed §land qualifier (AGENTS-SESSIONS) in operator form — one
home, not a divergent second.
**AMENDED 2026-08-24 — the wrapper CHOICE no longer decides whether the land survives.** A
non-worker `land` leaves the caller's process group at entry (journaled `land_process_group_escaped`), so a
group-directed kill aimed at your wrapper does not reach the land: a watcher that dies, times out or was
NEVER ARMED costs a re-arm and nothing else. This is what the "NEVER off the wrapper's process lifetime"
half above always promised and could not deliver while the wrapper OWNED the land — the reason the class
recurred through 4 measured deaths under a correct rule (picking the wrong wrapper failed SILENTLY).
Monitor remains RECOMMENDED (you still want to see the token) but is now ergonomics, not correctness; opt
back into the old coupling with `YITC_LAND_KEEP_PROCESS_GROUP=1`. A land that stopped emitting is now
PARTLY attributable, and the boundary is normative (amended 2026-08-24 on external adjudication,
`decisions/-audit-adhoc.yaml`): `pid` on both queue-wait rows; `land_terminated_externally` for a
CATCHABLE kill, the one arm that names a cause because a handler witnessed it; and heartbeat staleness (3
missed beats) for **stopped emitting, cause UNKNOWN** — never "killed", since an uncatchable SIGKILL and a
silent segfault/OOM leave identical rows and no process can journal its own SIGKILL. Attributing THAT needs
an external observer, which is out of scope here. Absence of a `LAND:` token still proves nothing, being
equally true of a healthy queued land. The DISPATCHED-WORKER rule is the opposite case and is untouched.
Rule home stays the seed §land qualifier (AGENTS-SESSIONS). ENFORCED
at the source: the `dispatch` verb INJECTS it as the standing worker preamble (`DISPATCH_WORKER_PREAMBLE`) and `stage <NAME>` re-prints it at the long-command / land stage-entries, both consuming the
ONE shared `SYNC_TO_LAND_RULE` constant. The scope boundary bounding this pressure homes single-SoT in
**SPEC-0103** — never weaken/skip a gate to force a blocked land; STOP and escalate instead.

## §Monitoring — READ the fleet through `journal query --fleet-verdict` (verb, SPEC-0133)

**The monitoring read is ONE verb, never a hand-assembled grep** (hand reads mis-judged healthy workers
repeatedly — a transcript mtime read «hung»; a missing worktree read «never started» when it meant «already
LANDED»; SPEC-0133 §5 F4)**:**

- **`journal query --fleet-verdict`** — per in-flight worker: `class` + the raw `evidence` the verdict rests
  on + a non-mutating **`verdict` ∈ {alive, dead, needs-decision}** + `verdict_basis`. This is the
  authoritative liveness/terminal read: it unions BOTH journals (worktree + main, deduped), the
  proc-by-session-ref liveness, the active-CHILD (auditor / test / land) slow-≠-hung discriminator, and
  worktree land-readiness — all the reads the retired prose spelled out by hand.
- **`journal query --dispatch-status [--task T-XXXX]`** — the class-only INSPECTOR (working / TERMINAL(done|halt)
  / closed_pending_land / blocked_on_land(needs-owner) / silent_stop / hang_suspect / launch-stall) for a
  spot-check of one task's or the wave's class, and — under `--json` — the POSITIVE terminal proof the
  watcher parses (`class == TERMINAL`). It is NOT the heartbeat/state-change poll: the watcher tick RUNS
  `--fleet-verdict` for liveness and `--dispatch-status --json` for terminality (§Watcher). Reach for it by
  hand only to read a single class on demand.

**The field/evidence/verdict contract is homed in SPEC-0133, NOT restated here** (`graph query SPEC-0133`,
§2). The operator-facing fact: the verb reports per-worker evidence + a verdict, and emits **NO
`recommended_action`** — it answers «what is observable now + is a human decision needed», never «what to
do». **Choosing the recovery act (land / adopt / re-bootstrap / escalate) stays the controller's call** (the
§Recovery-trigger + §Abnormal taxonomy below). The verb is §6-safe by the SPEC-0133 §1 test (pure
current-state → report; it never mutates / waits / schedules / re-invokes / kills / picks).

**Slow ≠ hung.** A full 9-stage fix is inherently long; the verb's `evidence.child` surfaces an ACTIVE
auditor / test-runner / `land` process — a `working` worker mid-flight, NOT a hang. Judge by verdict, not clock.

## §Watcher — dispatch OBLIGES a watcher; the blessed surface is `dispatch --watch` (RULE)

**`dispatch` ⇒ the controller MUST arm a recurring (≤5 min) watcher that re-invokes the controller on
land / stall / blocked-on-land / timeout.** Arming is **NON-SKIPPABLE**, done IMMEDIATELY after dispatch
returns, BEFORE yielding — a dispatched worker is a SEPARATE provider sub-session, so the harness sends **NO
completion notification**; without the armed watcher the controller has no event to wake it and detection
falls back to an OWNER POKE (incident 2026-06-09).

**MECHANIZED — do NOT hand-roll the loop.** The obligation was non-skippable but the mechanism was
unowned, so every controller re-implemented the tick, the confirmation and the terminal check by hand. Two
incidents on 2026-07-09 came straight out of that: a **false ALL_TERMINAL** read off a grep's *absence*, and a
**premature `blocked`** acted on from ONE transient snapshot. The blessed surface is now a verb:

```
bin/yitc-v2 dispatch --watch --task T-XXXX [--task T-YYYY...] # run under Monitor, key off the token
    [--watch-interval 60] [--watch-timeout 3600] [--watch-confirm-ticks 2]
```

- **NESTING — a wrapper's timeout MUST EXCEED `--watch-timeout`, or the token is destroyed by its own
  transport (RULE).** `--watch-timeout` bounds the VERB; the Monitor / `timeout` / harness wrapper you run it
  under bounds the TRANSPORT. Give them the same bound and the transport kills the verb at the very moment
  it is due to report: the verb's terminal line is written LAST, so a wrapper that expires simultaneously
  truncates the one output the whole watch exists to produce. **Measured:** an hour of watching produced NO
  token at all — wrapper and verb shared a one-hour bound, the wrapper killed the verb exactly as it was
  about to emit, and the controller got an empty read instead of a verdict. Set the wrapper strictly longer
  (a full tick's headroom, not one second), and let `--watch-timeout` be what ends the wait — it exits
  `TIMEOUT` (rc 2) cleanly and tells you to re-arm, which a killed wrapper never does. The same nesting
  applies to any wrapped token-emitting verb, `land` included: **the wrapper must outlive the verb it
  wraps.** This is the transport-side companion of "key ALL recovery off the JOURNAL, never off the
  wrapper's process lifetime" below — the journal saves you when this is violated, it does not excuse it.
- **Token contract — the `LAND:` analog.** The FINAL stdout line is a machine-readable terminal
  status: match **`^WATCH: (WAKE|ALL_TERMINAL|ANY_TERMINAL|TIMEOUT)\b`** (case-sensitive) and parse THAT —
  never the shell exit, never a free-text grep of a human report. `WAKE` (rc 1) = an actionable verdict
  CONFIRMED, or every dispatch TERMINAL with a recovery-bearing detail; `ALL_TERMINAL` (rc 0) = every watched
  task positively done; `ANY_TERMINAL` (rc 3) = the `--watch-any-terminal` opt-in only (below);
  `TIMEOUT` (rc 2) = re-arm. Tick progress goes to stderr, so stdout carries the token alone.
- **Running an N-slot refill queue? `--watch-any-terminal` (SPEC-0133 rule 5c).** By DEFAULT one
  sibling finishing never ends the watch, so «start a replacement AS EACH worker lands, not in
  waves» could only be expressed as one single-task watcher process per worker, hand-re-armed after every
  land. The opt-in makes ONE watcher exit `WATCH: ANY_TERMINAL` (rc 3) as soon as ANY watched task reads a
  positive `class=TERMINAL(done)` across the same `--watch-confirm-ticks`, with the token NAMING that task —
  refill that one slot and re-arm over the rest. It still prints the WHOLE fleet, so siblings are never
  abandoned; an early terminal with a recovery-bearing detail exits `WAKE` as it always did; and unflagged,
  the exit contract is byte-for-byte what it was.
- **The exit IS the re-invoke — but run it under Monitor, or it may never reach that exit (2026-08-12).** The
  verb simply *exits* with its token and your harness's completion notification wakes you; re-invoking the AI
  stays a harness capability the provider-neutral CLI cannot perform (CHARTER §P4b) and the observability verb
  must never do (SPEC-0133 rule 1). **A PLAIN background job is NOT how you hold that wait.** A watcher waits
  out a worker's tens-of-minutes lifecycle, and a plainly-backgrounded long wait CAN BE SWEPT BEFORE IT
  REPORTS: on 2026-08-12 the blessed watcher was backgrounded EXACTLY as this bullet used to prescribe and was
  killed before emitting a single line — status `killed`, empty output, zero `WATCH:` token — while the worker
  it watched ran on unaffected. The loss is SILENT and fails in the direction that HIDES itself: the controller
  believes the non-skippable monitor is armed while nothing is watching, so the obligation is DEFEATED, not
  merely inconvenienced. So run the watcher under the harness **Monitor** primitive — the SAME persistent
  watch-until-condition wrapper §Synchronous-to-LAND names for a contended `land` (re-arming under it held for
  six further watches that session) — and **key ALL recovery off the JOURNAL** (the `WATCH:` token +
  `journal query --fleet-verdict` / `--dispatch-status --json`, re-derivable from current state at any tick,
  SPEC-0133 §3), NEVER off the wrapper's process lifetime: a wrapper that dies costs you a re-arm, not the
  fleet's state. One rule for both long controller waits — this is that rule, not a second one.
- **§6-safe by construction.** A read-only poll over the existing readers: no scheduler, no queue-state
  machine, no cap, no auto-adopt, no liveness-arming FSM, no auto-relaunch (the CHARTER §6 named retirements).
  It mutates nothing and persists nothing across invocations — the consecutive-tick counters are in-memory for
  one run. It prescribes no act: **choosing the recovery act stays yours** (§Abnormal below).
- **Positive terminal, never absence** (SPEC-0165 item 11 — homed there, not restated here). Completion is
  proven off each task's parsed `class == TERMINAL` token (`journal query --dispatch-status --json`), for
  EVERY watched task; a missing or unparseable row counts as NOT-terminal. The false-ALL_TERMINAL fix.
- **Confirm across ≥2 consecutive ticks.** An actionable verdict (`dead` / `needs-decision`) wakes only once
  it PERSISTS for `--watch-confirm-ticks` ticks (default 2 — the §Recovery-trigger (b) rule). A
  verdict that settles back to `alive` resets its streak. This is the premature-`blocked` fix. A `working`
  heartbeat carries verdict `alive` and therefore NEVER wakes you — without that half a watcher is a
  busy-loop. Both halves are pinned by differential tests (`tests/test_dispatch_watch.py`).
- **Heartbeat, not only event-driven.** Every verdict field is re-derivable from CURRENT state with no
  triggering event (SPEC-0133 §3), so each tick RE-DERIVES every in-flight worker's verdict. This bounds
  MISSED-TRUE-DEATH latency to one tick and catches the blind spot an event-driven watcher misses — a worker
  that DIES WHILE ALREADY STUCK (already `closed_pending_land` / `blocked_on_land`, then its proc dies → no
  class-CHANGE → an event-only watcher never wakes).
- **`halted` is a recovery-bearing class the heartbeat catches.** A worker that emits
  `bg_dispatch_halted` and exits BEFORE claiming a worktree (a pre-claim self-halt at analysis) is never
  in-flight by proc/claim/child — an event-only watcher, and the older verdict, would MISS it entirely. The
  heartbeat surfaces a RECENT unresolved halt as **verdict `needs-decision` / class `halted`**, carrying the
  halt reason in `verdict_basis`, and the watcher WAKES on it. It is recovery-bearing exactly like the other
  blocked classes: the controller escalates the named blocker to the owner and, once resolved, RE-DISPATCHES a
  fresh worker (no worktree to adopt — the halt was pre-claim). A stale halt ages out of the window (the
  controller's live decision window, not a permanent orphan). A halt that HAS aged out of `--fleet-verdict` is
  still caught by the positive-terminal read: `TERMINAL(halt)` exits `WAKE`, never a clean `ALL_TERMINAL`.
- **Do not abandon siblings.** A watcher covering several tasks keeps watching the REMAINING ones after one
  changes class — never exit on the first task's state-change (incident). The verb holds this by
  construction: `ALL_TERMINAL` requires ALL watched tasks terminal, a `WAKE` fires only on an actionable
  verdict (never on a benign class change), and a wake prints the WHOLE fleet so you re-arm over the survivors.
- **Retire a prior watcher by PID, never `pkill -f <pattern>`** — `pkill -f` matches the FULL command line of
  every process INCLUDING the killer's own shell (its argv carries the pattern) → it kills its own parent
  shell, misread as "watchers don't hold here" (incident 2026-06-23). Kill by captured PID, or let the prior
  bounded watcher exit on its own (`--watch-timeout` bounds it by construction).
- **Default cadence 60s, set by the TERMINAL SEAM — and the ≥2-tick confirm is what makes the interval
  the latency (supersedes the X-0536 ~300s recommendation).** The header's "≤5 min" is still a
  CEILING and 60s satisfies it. **Why the interval IS the latency:** the watcher confirms a verdict across
  `--watch-confirm-ticks` (default 2) consecutive ticks, so detection is bounded by **2 × interval**. That
  cuts both ways, and X-0536 read only one side of it: at 300s the bound is ~10 min, which is what
  actually happened on 2026-09-07 — land at 04:46:51Z went unreported until 04:56:21Z, the
  dependent card was dispatched ~8 min late, and the OWNER had to surface it (standing directive
  2026-09-06, «своевременно пускай другие в работу»). At 60s the same seam bounds to ~2 min.
- **What X-0536 got right, and the one premise that does not hold.** Its concern was real — a worker's
  lifecycle IS tens-of-minutes long, so most ticks read a state that has not moved. But its stated COST —
  "dozens of identical re-derivations per real class-change, **each burning a controller re-invoke** for
  nothing" — describes the HAND-ROLLED loops that retired, not the verb. `dispatch --watch` EXITS
  only on a contracted token (`WAKE` / `ALL_TERMINAL` / `ANY_TERMINAL` / `TIMEOUT`); a tick whose verdict
  is not actionable prints nothing, exits nothing, and **re-invokes no controller** — it sleeps and polls
  again. So a quiet tick costs one journal fold, never a controller wake.
- **The surviving cost is the fold, and it is bounded — measured, not assumed.** Each tick runs one
  `journal query --fleet-verdict`: **duration_ms median ~12s (max ~16s)** folded from this repo's own
  `cli_invoked` rows post- (n=8, 98 segments, ~395k rows parsed). It did NOT become cheap — that is
  still «11-15s per read». It is affordable because it sits **well under the 60s interval**, so
  ticks never overlap or pile up and the cadence stays the binding constraint. `--watch-interval` remains
  the per-call override: raise it for a genuinely slow fleet where no dependent work is waiting on the
  seam, and drop `--watch-confirm-ticks` only if you accept the flap it guards against.
- **Two observed pitfalls (X-0536) — both come from reading state the WRONG way, and the verb already avoids
  both; do NOT hand-roll a poll that re-introduces them:**
  - **`watcher-terminal-check-matches-filing-commit`** — proving a task terminal by a `git log --grep T-XXXX`
    (or any commit-message scan for the id) FALSE-fires: the task's **filing commit** already carries `T-XXXX`
    in its subject, so the grep matches from the moment the task was filed — long before any land. This is the
    same class as the false-ALL_TERMINAL-off-absence pitfall above (proving terminality off the wrong signal).
    The fix is **terminal-state emission only**: prove completion off each task's parsed `class == TERMINAL`
    token (`journal query --dispatch-status --json`, the "Positive terminal, never absence" bullet), NEVER off
    a commit-message grep.
  - **`watcher-diff-includes-heartbeat-timestamp`** — diffing the raw status line tick-over-tick fires a
    spurious "state changed" EVERY heartbeat, because the line carries a per-tick heartbeat TIMESTAMP that
    advances on every poll even when nothing real changed → an endless wake-loop. The fix is to **exclude the
    heartbeat timestamp from any change-diff**: compare only the semantic verdict/class fields (the
    re-derivable state, SPEC-0133 §3), never the timestamp. The verb holds this by construction — it wakes on
    an actionable verdict confirmed across ticks, not on a raw-line diff.

Running `journal query --fleet-verdict` by hand stays the ad-hoc fallback (a spot-check), not the primary
path — the watcher runs it for you, on the tick, with the confirmation and the terminal check attached.

## §Recovery-trigger — act only on the verb's verdict, CONFIRMED (RULE)

The §Monitoring/§Watcher reads DETECT; this governs WHEN to ACT. **THE GATE — a controller takes a recovery
ACTION (land / kill / reset / re-bootstrap / adopt) ONLY when BOTH hold:**
- **(a) the verb classifies it** — `journal query --fleet-verdict` returns **verdict `dead`** or
  **`needs-decision`** (with a recovery-bearing class: closed_pending_land, silent_stop, hang_suspect,
  blocked_on_land(needs-owner), launch-stall, or halted). Never a hand-rolled `pgrep`/`pkill` — the verb IS the
  liveness source (it self-excludes and reads argv elements correctly; a `verdict: alive` is authoritative —
  never assert dead while your own read says alive, CHARTER §Principle 7). **The governed proc-liveness
  behind the verb — `_session_proc_alive` (`bin/lib/journal.py`) — matches argv EXACT-ADJACENCY (an element
  == `--session-id` AND the NEXT element == the session-ref exactly) AND EXCLUDES the reader's own pid, so it
  provably cannot self-match the monitor's own command line.** Do NOT hand-roll a bare-session-ref probe —
  `pgrep -fc 'session-id <ref>'` (or any `pgrep -f` carrying `<ref>`) SELF-MATCHES the monitor's OWN cmdline
  (which embeds `<ref>`) → always reads the worker ALIVE → MISSES a true death (the 2026-07-05 incident: a
  controller poll self-matched and never detected the worker's death). If the verb genuinely does not
  cover a case, ground-truth death via journal (`bg_dispatch_halted` / `land_completed` absence) + `git
  worktree list` — never a bare-session-ref `pgrep`.
- **(b) the verdict is CONFIRMED across the heartbeat re-derive (≥2 consecutive ticks)** — never a single
  read. A `land` in flight makes an instant read flicker; a worker's pid FLAPS across harness re-invocations
  while alive. Act only when the SAME `dead`/`needs-decision` persists; a `needs-decision` that resolves to
  `alive` next tick was live-but-settling — do NOT act.

Worktree existence, when needed, is read via `git worktree list` (ABSOLUTE sibling paths `<repo>-wt/T-XXXX`),
never a repo-relative probe; an "absent" worktree can mean already-LANDED, not dead. For a generic process the
verb does not cover, use an exact-NAME match (`pgrep -x the AI provider`, self-excluded) — NEVER `pgrep -f <pattern>`
carrying text from your own argv.

## §Abnormal situations — the recovery-ACTION taxonomy (controller's call; verdict from the verb)

Read the verdict/class from the verb; pick the ACTION here. The verb never prescribes the act (SPEC-0133 §2).

- **`closed_pending_land` → RECOVER-LAND it, do NOT respawn.** The worker CLOSED in its worktree but the
  close has not landed; only INTEGRATION is missing. But FIRST grace-wait for terminal : this is a
  TRANSIENT phase — a synchronous-to-LAND worker reads `closed_pending_land` WHILE actively self-landing (a
  `land` is long + silent). The verb's `evidence.land` sub-signal (`closed_pending_land(…,land-alive|land-dead)`)
  is the discriminator: `land-alive` = a real `land` proc for this task is in flight → LEAVE it (firing your own
  `land` RACES it → the E-0035 torn-tree guard aborts the premature reland); `land-dead` + confirmed proc-dead +
  still un-landed → then RECOVER it. **Governed recovery — MECHANIZED:** run
  `bin/yitc-v2 worktree recover-land --task T-XXXX` — ONE governed, FAIL-CLOSED, IDEMPOTENT verb that
  RE-VERIFIES the gate IN-CODE (the OBSERVED worktree state is closed-but-unlanded — its on-branch task card
  reads `status: done` — AND land-DEAD AND session-proc-DEAD; any live signal →
  REFUSE, so a mistaken invocation on a live self-land fails closed — unlike a hand `adopt`+`land`), then adopts
  (re-stamp → `worktree_adopted`, the visible recovery record) + delegates to the existing `land` engine (LAND:
  OK). Idempotent: an already-landed/absent worktree is a no-op success. This REPLACES the hand-executed
  grace-wait+confirm+`worktree adopt`+`land` dance a worker's turn-yield used to lose the build to (the
  incident). The raw `bin/yitc-v2 land --task T-XXXX` still works as the fallback once you have HAND-confirmed
  land-dead + proc-dead, but `recover-land` is the governed default (it enforces that gate for you).
   — the admission observes the WORKTREE, not the classification: a worker that ESCALATED
  (`blocked-on-land`) before dying classifies TERMINAL(halt) while its branch IS closed-but-unlanded, and the
  class used to SHADOW that state and refuse the recovery outright (a manual
  adopt+land dance each). The class + `closed_at` now survive only as CORROBORATION in the refusal text; the
  three liveness legs are unchanged and still run AFTER admission, so a LIVE worker is refused as before.
  **SPEC-0005 admission judgement — BELOW ADMISSION, this pattern is `recover-land`'s only prose home BY
  DESIGN (recorded, 2026-07-17; satisfies the T1 named-verb probe).** No spec anchor is warranted:
  the verb states no NEW standing rule — it MECHANIZES rules already homed elsewhere. Its land-alive REFUSE
  leg IS the SPEC-0134 worker-land non-preemption invariant (already `cited_by`, the task that built
  the verb); "the verb reads the class, the operator picks the act" is SPEC-0133 §2; the adopt+land delegation
  is the existing `land` engine contract (SPEC-0014 / SPEC-0132). SPEC-0005 §2 delete-test: a
  SPEC-recover-land would not materially improve change analysis — an editor re-derives every constraint from
  those homes — and it would fail legs (2) survives-an-internal-refactor + (3) implementation-shape-independent,
  because the gate IS the implementation shape, i.e. it would paraphrase one function's control flow (§2's
  NOT-a-spec clause). Adding one is also a CHARTER §Principle 1 miss (an existing analog already carries it).
- **`launch-stall(no-claim-past-grace)` → re-bootstrap, do NOT adopt.** Launched but never
  CAME UP and never claimed, past the near-launch grace — a DEAD dispatch with NO worktree to adopt. Confirm
  `dead` per the gate, SURFACE for a confirmed controller decision (never auto-redispatch on silence — it
  races a slow-but-live boot), then re-bootstrap a fresh worker.
- **`silent_stop` / `hang_suspect` → confirm dead, then recover from durable state.** `silent_stop` = no live
  claim; `hang_suspect` = a LIVE claim held but stale (detect+surface only — never auto-kill). Once `dead` is
  confirmed across the heartbeat, terminate/recover and resume from `current_stage` (§land-after-each keeps
  1..*k*-1 safe on main).
- **Premature exit (worker gone, task unlanded — a death subclass).** The verb reads `verdict: dead` (proc
  gone, journal quiescent, no live child). SPLIT by checkpoint: NO ship-commit beyond the claim → ordinary
  Death (re-bootstrap + resume); a ship-commit present → RESPAWN a fresh worker to ADOPT the committed
  worktree → finish → `task close` → `land`. Never key the
  death decision on the launched Popen pid (RETIRED, both-ways-unreliable) — the verb's session-ref liveness
  is the signal.
  **HOW you respawn it — a plain `dispatch`, and NOTHING for the controller to adopt first.**
  Run `bin/yitc-v2 dispatch --task T-XXXX --brief …`, unchanged and un-`--force`d. The in-flight guard
  now has THREE arms, and it picks between them itself: a live-held worktree → SKIP (unchanged); a
  journal-quiescent `hang_suspect` orphan → torn down + re-dispatched; and a SETTLED TERMINAL
  (a `bg_dispatch_halted` escalation / a death terminal) whose holder it DETERMINES dead → the worktree
  is **PRESERVED** (never torn down — it holds the ship commit) and a fresh worker is launched into it,
  its brief carrying an ADOPT-FIRST block that overrides the preamble's `worktree new` claim step. The
  worker then runs `worktree adopt --task T-XXXX --confirm-dead` itself. **Do NOT adopt as the
  controller first to "unblock" the dispatch** — that re-stamps the worktree to a LIVE session, which
  the guard reads as held, and the loop closes again (this route was previously unexecutable for exactly
  that reason: the worker that must adopt could not be launched until the adopt had happened, and
  `--force` reaches only the launched-but-no-worktree case — had to escalate a routine tail to
  the owner on 2026-08-12). **What still refuses, and why that is the point:** liveness is DETERMINED at
  both ends, never asserted — dispatch re-dispatches only when the stamped holder's process is gone AND
  no live process holds the worktree path, and an UNSTAMPED (raw-git) worktree names no holder, so its
  death is unverifiable and it takes the protective SKIP; `worktree adopt --confirm-dead` re-verifies
  the same two reads in code and refuses a live holder however the flag was passed (SPEC-0134 rule 2 /
, the double-claim incident). The flag is provenance; the reads are the enforcement.
- **Claim-less rogue/dead worker (launched, never reached a worktree, may have dirtied `main`) → MECHANIZED
  stop.** A dispatch that came up but NEVER claimed a `task/T-XXXX` worktree, yet left a process
  and/or pre-claim SOURCE dirt on the shared `main` checkout. Recover with the one governed verb
  **`bin/yitc-v2 dispatch --stop --task T-XXXX [--restore-path <file> …]`**: it STOPS the launched pid
  (signaled ONLY when `/proc/<pid>/cmdline` still carries the exact `--session-id <worker_ref>` — never a
  stale-pid blind kill, the PID-reuse guard), captures a `.yitc/rogue-recovery/<task>-<ts>.diff` evidence
  bundle of the main-checkout dirt BEFORE any restore, reverts ONLY the operator-named `--restore-path`
  files (FAIL-CLOSED — unattributable dirt, e.g. a concurrent session's WIP, is never blanket-reverted, and
  the journal is refused as a target), and emits the terminal `bg_dispatch_halted` the in-flight dispatch
  guard CONSUMES (launched-sublist axis) so the task is redispatchable via a plain `dispatch` WITHOUT
  `--force`. STATELESS (target derived from journal+git, no worker registry — CHARTER §6), IDEMPOTENT, and
  it REFUSES a settled dispatch (done/halt/landed) or one still holding a LIVE worktree claim (that is the
  `worktree adopt`/`recover-land` path, not this). The raw kill+restore+halt sequence survives as the
  documented emergency FALLBACK only if the verb is unavailable — prefer the verb (it enforces every gate).
- **401-auth-death (a death subclass — external provider credential rotation kills a worker mid-run).** No
  `bg_dispatch_halted` is emitted, so the verb classes it `hang_suspect` (live claim lingers). The
  controller's finer read: a nonzero worker exit-code + a log scan anchored to `API Error: 401` /
  `Invalid authentication` (anchor the phrase, not a bare `401`). Recovery = the adopt-the-committed-worktree
  path above (adopt → emit any missing P8/closure events → re-audit within the loop ceiling → close → land).
- **By-design governance STOP (neither death nor hang).** A worker hitting a hard boundary (audit-loop
  ceiling with a standing RED; an ABORT verdict; a P7 dissonance; a land repeated-abort backstop) STOPS AND
  REPORTS by contract — durable state intact, main untouched — emitting `bg_dispatch_halted`. The common
  owner-gated cases auto-emit it (audit-ceiling, land repeated-abort) with
  `data.needs_owner_reset: true`, which the verb surfaces as **`blocked_on_land(needs-owner)`** — a
  recoverable owner-gated block, never a hang/orphan. Controller path:
  escalate to the OWNER → on authorization, **RESPAWN a fresh worker by DEFAULT** to adopt the holder's
  worktree (the §6-preferred posture) — mechanically that is the plain `dispatch --task` of the
  §Premature-exit bullet above (this class classifies TERMINAL, so a dead holder gets the PRESERVING
  arm: worktree kept, worker adopts). The owner gate is on the AUTHORIZATION, not on the
  mechanics — once authorized there is no owner decision left in the recovery itself. Finish in the controller session itself ONLY where a respawn buys
  nothing (owner say-so on a trivial drained tail, or the degraded no-spawn-primitive fallback); a pass-3
  residual finding routes to a FOLLOW-UP task, never inline absorption.
- **Closed-but-unlanded stale-audit orphan (the land-saga class).** A worker `task close`d but `land`
  FAILED — a concurrent merge advanced `main` so the recorded audit no longer covers the merged tree (STALE
  audit) and/or the SPEC-0077 pinned verify trips on a verify-path delta. **PRIMARY — in-place re-audit**
  (preserves the work): `bin/yitc-v2 audit post --reaudit-after-close --task T-XXXX` re-pins a fresh GREEN at
  HEAD; then `land` — if it touches the verify-path and the pinned verify fails on a superseded assertion, the
  reland needs the owner-acked `land --rebaseline --rebaseline-reason "<≥30 chars>"`. A HEADLESS worker CANNOT
  supply that ack — it STOPS and returns **`blocked-on-rebaseline <task> <reason>`** (worktree intact), never
  grinding the gate / `land --no-tests` / hand-emitting `land_completed`. **FALLBACK — discard + re-execute**:
  nothing landed (task still `ready` on `main`) → remove the worktree and re-run the 9 stages on current `main`.
- **Foreign uncommitted SOURCE dirt on the shared `main` checkout → land-ABORT, controller-resolves.** A
  worker's `land` ABORTs (`LAND: ABORT … main worktree … uncommitted non-bookkeeping changes …`) when the
  shared checkout carries a concurrent session's uncommitted SOURCE edit. **This is land behaving CORRECTLY**
  — do NOT touch land's fold/allowlist. The worker MUST NOT touch the foreign work (no stash/checkout/add/
  edit — cross-session isolation is ABSOLUTE); it returns **`blocked-on-land <reason>`** worktree-intact +
  land-ready, no retry loop. The controller waits for that session to land (or stashes only with owner
  authorization — NEVER destroys foreign WIP), then re-lands the worker.
- **Controller takeover — MECHANIZED.** A foreign worktree never auto-resumes; adoption is an
  EXPLICIT `bin/yitc-v2 worktree adopt --task T-XXXX --confirm-dead` ( — NOT a hand stamp edit), which
  re-stamps + emits one `worktree_adopted` record, then resume from `current_stage`. `--confirm-dead` is the
  controller's ASSERTION that the §Recovery-trigger gate held FIRST (the verb does no auto-death decision).
- **Within-fleet stamp collapse — ACCEPTED (its own home).** Fleet siblings share one provider
  session id, so the own/foreign stamp collapses within a fleet — accepted (no harm): within-fleet safety
  rests on the per-task-id worktree guard + dispatch discipline (each worker its ONE assigned id, no
  self-fetch, no sibling-resume), not the stamp. Cross-session double-claim STAYS enforced by.

## §Guard rails — the trial boundary (canonical home = CHARTER §6 at realization)

The named §6 retirements — listed here ONLY as the operating boundary; **never traded for speed:**
1. **No auto-launch / autopilot** — the OWNER starts the orchestrator session and authorizes the batch.
2. **Controller is batch-bounded** — works ONLY the given batch; never self-fetches; never loops; batch done
   → report + stop. A WORKER is likewise bounded to its ASSIGNED ids (a static ordered batch is in-bounds;
   picker-driven self-fetch and sibling-resume are out).
3. **No in-session sub-worker fan-out inside one Build** — each unit is a full top-level Build session with
   its own worktree (read-only research subagents stay legitimate; a Build ROLE is never an in-process one).
4. **No cap/queue-state machinery, liveness-arming infra, or role-taxonomy** — the controller is a
   selector+dispatcher on stateless reads (incl. the read-only `--fleet-verdict` verb, §6-safe because it
   only reports — SPEC-0133 §1), not a stateful orchestrator.
5. **Worker = pure executor** — the cross-chain wait lives in the controller. Non-negotiable also: per-write
   worktree isolation; `land` after every task; independent-provider audit (P4).

## §Stale-worktree hygiene — `worktree sweep` + the host cron step

Concurrent worker sessions + the land-verify pinned last-green path (SPEC-0077) leave leftover `/tmp`
worktrees + engine-bin dirs. The v2-native backstop is **`bin/yitc-v2 worktree sweep`** : it
removes STALE (age > `--max-age-hours`, default 24h) AND not-live worktrees/temp dirs only — NEVER the main
checkout, a `task/T-XXXX` worktree (recover those via `worktree adopt`), or anything own-stamped / proc-alive
/ younger than the retention floor (`--dry-run` lists without acting). Wire one host crontab line so it runs
unattended (host territory — do NOT edit the crontab from a v2 worktree):

```cron
*/30 * * * * cd <repo-root> && bin/yitc-v2 worktree sweep
```

The **scheduled** wiring (and v2-project governance cron generally) is owned by the layer-1 methodology
nightly in plan `v2-project-automation-governance-methodology-night` — ships + documents the verb.
