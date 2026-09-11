<!-- GENERATED — identity-agnostic release view of the methodology handbook. Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->

# AGENTS — Session types (part 2 of 3 of the AGENTS protocol)
<!--AUDIENCE:core-->

> SOURCE part 2 of the AGENTS protocol (`HANDBOOK_READ_ORDER`: CHARTER → AGENTS → AGENTS-SESSIONS →
> AGENTS-PROTOCOL → LIFECYCLE → QUEUE → GRAPH). All parts are assembled — in order — into your audience's runtime
> seed (Worker: the assembled `graph/worker-seed.md` part chain; Controller: the SOURCE parts directly in the read-order — SPEC-0007 §5c).

## Session types
<!--AUDIENCE:core-->

The session posture — the one interactive **Controller** + the dispatched **Worker** — and their definitions live in **CHARTER §Principle 6** (the authoritative home; not restated here, so the enumeration cannot diverge). **Emergency is NOT a third posture**: if
the V2 machinery itself breaks (the `bin/yitc-v2` CLI won't run / worktree+land broken / git bad state), drop
to the documented degraded-execution **emergency MODE** overlaying the Controller (or a Worker's flow) — entry is
tool-independent (owner phrase + read `patterns/emergency-mode.md`), never a startup verb.

### Startup phases
<!--AUDIENCE:controller-->

`/yitc` startup is **two explicit phases** — there is no Build|Review type choice (one interactive Controller posture):

1. **READ the mandatory handbook** (all sessions): <!--GEN:read-order:arrow generated from HANDBOOK_READ_ORDER — DO NOT EDIT; regen via `graph build`-->CHARTER.md → AGENTS.md → AGENTS-SESSIONS.md → AGENTS-PROTOCOL.md → LIFECYCLE.md → QUEUE.md → GRAPH.md<!--/GEN:read-order--> + the floor trigger-map (`graph/floor-trigger-map.md`, always-loaded seed). **Read your audience's seed** — a Worker: the assembled `graph/worker-seed.md` **and every continuation part it chains to** (IN PLACE OF the source files in that arrow; one part is not the seed); the Controller: the SOURCE parts in that arrow DIRECTLY, each single-read-safe (SPEC-0007 §5c). CHARTER first (pedagogical pin); the retrieved tier is NOT loaded at startup — it is
   delivered at stage-entry (the one canonical order — §At-session-start §Bootstrap-floor + the `-C` consumer `session start` echo; the engine self-start no longer echoes it).
   Nothing task-specific here — so the AI always holds the rules.
2. **`bin/yitc-v2 session start`, then scan `bin/yitc-v2 --help`** — the verb-inventory scan runs HERE, immediately AFTER `session start`, NOT in Phase 1: its fetch-receipt must post-date the `session_started` anchor the `--help` read-gate windows from, else a pre-anchor Phase-1 scan is not credited and the first gated verb (`worktree new`/`task file`) refuses. `session start` (the interactive **Controller** — no `--type` choice; a dispatched **Worker** carries `--type build`) — keeps `session_started` emit
   (the engine self-start's read-order echo was retired as Phase-1-redundant; a `-C` consumer still gets the engine-resolved read-order echo) AND adds a **NON-MUTATING dispatch** (reads/reports startup state; never
   changes task status/stage — that FSM/enforcement creep is CHARTER non-goal #7):
   - **controller → resume-or-await (concurrency-aware §4; auto-pick removed):** FIRST,
     branch-identify — if THIS checkout is a `task/T-XXXX` worktree and that task is in-progress,
     resume THAT task **ONLY if its session stamp is YOUR OWN session** ( — `worktree new`
     stamps every worktree at creation with its owner session-id + started-at, a dumb provenance
     marker in the worktree's private git dir, no TTL/lease). **Stamp scope (accepted):** the
     own-stamp distinguishes genuinely-SEPARATE sessions — it does NOT distinguish sibling background
     workers in one fleet, which inherit a single provider `<provider-session-env>` so their stamps
     share a `session_ref` (within-fleet own/foreign COLLAPSES). That is accepted: within-fleet safety
     rests on the per-task-id worktree guard + dispatch discipline (a worker is bounded to its
     ASSIGNED ids; no picker-driven self-fetch, no sibling-resume), NOT the stamp; the dangerous
     CROSS-session double-claim stays -enforced. **A dispatcher-assigned STATIC ordered
     batch (≤ front-load cap, `requires:`-ordered, picker NOT consulted) is in-bounds — it is the
     already-legal «take further tasks in sequence», not self-fetch; full carve-out homed in
     `patterns/background-session-operation.md`.** Reopen the fence ONLY if a fleet ever intends autonomous
     within-fleet resume/self-fetch or an actual within-fleet incident appears (consult first the
     ad-hoc external audit of this stamp-scope decision, filed under `decisions/` beside that
     decision's own task card — cited by description rather than by filename here, because the
     published release view strips task ids and a path carrying one would render as a file that does
     not exist). A
     **FOREIGN- or un-stamped worktree
     is NEVER auto-resumed**: BLOCK «already held by session X» — PRESENCE is NOT orphanhood; adoption
     stays EXPLICIT, never auto. ONE carve-out : a CONTROLLER startup whose foreign holder is CONFIRMED
     DEAD (the SPEC-0133 `_session_proc_alive` predicate) prints `acting in <T>` + the `controller_acting_in_worktree`
     key instead — read-only, nothing stamped, so execution verbs still refuse. An own-stamped resume holds
     regardless of how many OTHERS are in-progress. **The own-stamp / foreign branch check runs
     FIRST and returns before any count logic — so the await-owner posture below NEVER suppresses an
     own-stamped resume.** Else by `in-progress` count: 1 → print its resume contract (resume of
     existing work, not a queue-scan); **0 or >1 → await an owner cue, NO candidate** (>1 first
     prints a brief concurrent note —). **No auto-picker :** the dispatch STOPS
     auto-scanning the queue after startup — it does NOT offer a top-ready candidate; it ALSO surfaces the
     WAITING-ON-OWNER paused-task signal (a safety reminder) and runs NO auto-counts (no `N ready / M
     parked` queue scan until cued). **A
     MEMORY continuation-seed / `[instruction]` entry is NOT the owner cue (SPEC-0039 §4):** even when
     `MEMORY.md` carries mandate/continuation seeds, AWAIT a LIVE owner cue in THIS session and never
     self-select which seed thread to resume — plan/task continuation begins only on that live cue (a
     stored "owner-authorized" claim does not satisfy it). When
     the owner cues a BATCH, the DEFAULT is to take the orchestrate controller-selector posture
     (§Session-types → Orchestrate posture) — dispatch the independent ready tasks to background Workers
     and coordinate their order (you claim no worktree yourself; the WORKERS do). When the owner
     instead cues you to take a task YOURSELF (the owner-say-so self-execution fallback), you **claim it
     via `worktree new --task T-XXXX`** (worktree creation IS the claim / option B; `task
     pick` is read-only, does NOT claim). **The claim needs a LIVE execution-cue — owner-authorized
     EXECUTION, NOT a prior DESIGN agreement** (a filed/`ready` task or an earlier design go does not itself
     authorize it; SPEC-0141). **A work cue authorizes THAT the work happens, NOT the MODE: the default is
     DISPATCH, and self-executing it yourself needs its OWN explicit owner say-so — the enumerated
     NOT-grounds + the stop-and-name-the-ground reflex live in SPEC-0141 §2/§3a/§3b (single-SoT).** The pre- bare ">1 → STOP" stays RETIRED (same-task double-claim is structurally impossible — unique ids + the worktree guard); >1 is concurrent, not a dissonance. **Session start is UNCHANGED by SPEC-0126's autonomous-continuation
     doctrine (per SPEC-0126):** it still AWAITS an owner cue and NEVER auto-picks — context-bounded
     autonomous continuation begins ONLY after the owner authorizes a plan/batch (the doctrine home is
     §Orchestrate posture + CHARTER §6), never at startup.
   - **cross coordination-log surface (report-only, the Controller and `-C` consumers, per SPEC-0086 —):**
     after startup, `session start` prints report-only `cross-coord:` fold-view COUNTS over the
     kernel-owned SHARED coordination log — the author-side **outbox** (`from:me` items a peer fixed,
     awaiting MY close — the "fixed→verify at start" surface, the done-awaiting-close subset) + the inbound
     **inbox** needing a DECISION (`to:me` items still `requested` and not yet tracked by a local task via
     `resolves_cross` — `picked`/`done`/task-linked are excluded). Fold-derived (no stored status —
     `cross outbox` / `cross inbox`; **re-fold exactness,:** BOTH `cross outbox` AND
     `cross inbox` re-fold the FULL non-terminal ledger — each a SUPERSET of its start surface, which is
     only an actionable cut (outbox = the `done`/fixed→verify subset; inbox = the `requested`-and-not-
     task-linked needs-decision subset). The superset is the acceptable durable re-fold; each exact start
     cut is recoverable within it (outbox: its `status==done` rows; inbox: its `requested`-and-unlinked
     rows); no subset verb — the vocabulary is frozen),
     report-only, NO auto-pull (surfacing ≠ queue-scan — the LOG-vs-queue line holds; DISTINCT from the
     QUEUE-exploration counts the dispatch's await-clause removed above, and does not reinstate them). The shared
     log is identity-agnostic (every participant folds the SAME out-of-repo log). Since the cutover
     (SPEC-0079 superseded) this is the SOLE cross surface — the old per-repo SPEC-0079 `cross-log:` inbound
     count was REMOVED. Intake (pull / act) stays an owner-commanded `cross pick`/`task file` act.

   **This AMENDS Phase-3 dispatch** (now the single **Controller** dispatch — the former
   build *resume-or-**pick*** and review *counts* branches are merged). ** is Final/frozen and stays
   cited as superseded-in-part** for that dispatch clause: the **resume** halves (own-stamp + len==1) and
   the `session_started` emit ( base) are unchanged (the engine read-order echo was separately retired by as Phase-1-redundant; the `-C` consumer echo stays); only the auto-**pick** and the
   auto-**counts** are removed in favour of awaiting an explicit owner cue, and the Build|Review type choice
   is RETIRED. The new standing rule is HOMED here (this mandatory-tier section, re-read verbatim
   post-`/compact`) — satisfying the SPEC-0007 §coherence-invariant for changed `session start` delivery
   without a new spec.

Task pickup thus lives in the Controller dispatch of the verb, on an owner cue (never a pre-choice phase). The v1
continuation-rehydrate battery (cap / monitor-arm / release-debt / aggregate-counter) is **NOT**
imported — session startup runs no capacity/parallelism, monitor-arming, release-state, or
aggregate-counter logic (solo *author*, one-task-at-a-time — sequential, per-session count not capped — no UNBOUNDED pipeline (the **default** bounded orchestrate controller-selector posture — §Session-types → Orchestrate posture — IS that bounded selector+dispatcher, not the UNBOUNDED pipeline), no-release V2 — but
concurrent SESSIONS are expected; "solo" = one author, not one session at a time).
Enforcement stays deferred (non-goal #7).

### Controller (the interactive posture)
<!--AUDIENCE:controller-->

- **Where:** the interactive main session — broad across projects (read-leaning): reads ANY project, files tasks, authors specs/plans, runs ad-hoc audits.
- **What:** **DEFAULT — take the orchestrate controller-selector posture** (§Session-types → Orchestrate posture): instead of executing itself, dispatch independent ready tasks to background **Workers** and coordinate their order — via `bin/yitc-v2 dispatch` (`patterns/background-session-dispatch.md §Dispatch launcher`), never the provider in-process subagent tool. **Fallback (owner say-so) — execute a task itself / make a bounded in-scope edit:** run the Worker flow in-session — **one task at a time** through all 9 lifecycle stages without handoffs (a session may take further tasks in sequence).
- **Permissions:** read ANY project; write code / specs / plans / tasks, run tests, commit, deploy (if owner authorized). The right to write comes from the orthogonal gates (path-territory / worktree-before-write / 9-stage lifecycle), NOT the posture label.
- **Boundary:** every WRITE stays in ONE project. Cross-project observation → halt + route per §Filing rule (a `bin/yitc-v2 cross request` coordination item; governed by SPEC-0084/85/86), never silent implementation. A direct in-scope edit is the FALLBACK, fired only when the write path is ONE already-clear in-scope task; the moment it is unclear or parallelizable, prefer dispatch. Either way it rides the ordinary worktree + 9-stage lifecycle.

### Writes happen in a worktree

**The trigger is the WRITE, not the session label.** Parallel sessions sharing one working
tree collide (the 2026-05-29 incident: a duplicate ID + a `git add -A` cross-sweep).
This is exactly **WHY the per-write worktree is MANDATORY, not optional** ( reaffirmed
this and withdrew demote-to-optional proposal): concurrent sessions are expected and
growing (review alongside build, auto-sessions, parallel builds on different tasks), and isolation
is the industry-standard primitive that makes them non-interfering. The ergonomic pain (land
deleting the cwd, cwd-binding confusion) is fixed by *hardening* the flow (land-from-main,
cwd-independent verbs), not by removing isolation. So:

- **READS** (Review browsing, analysis, any session that only inspects) stay on the **main
  checkout** — no worktree, no branch.
- **EXCEPTION — append-only JOURNAL events need NO worktree.** A `bin/yitc-v2 event …`
  append — INCLUDING `deviation_captured` (the capture reflex) — MAY be emitted from the **main
  checkout**: the journal is append-only + union-merged, `cmd_event` requires no writing worktree, and
  any resulting `events.jsonl` dirt on main is folded into main by the next `land` (`_auto_sync` /
  `_land_integrate` step-2b). The "ANY WRITE → worktree" rule below governs **source / artifact**
  writes, NOT journal appends — so a deviation capture stays a one-command reflex from anywhere, never
  gated behind opening a worktree.
  **The promise is KEPT at audit time, never narrowed (SPEC-0168 rule 7 — `graph query SPEC-0168`):** an **ACCEPTANCE-PROBE emit from the main checkout is COVERED** — the task's audit packet FOLDS that task-tied row from main's journal into the audit checkout's evidence and renders it with a visible cross-instance provenance mark ("present, sourced from main, not yet landed") instead of reporting the criterion unproven (X-0558) — so do NOT read that burn as "emit inside the worktree to be safe": that author-side workaround is exactly what the reader rule retires, and this exception imposes no such obligation. **What the fold covers is the CHECKOUT it came from, never the TYPE — do not generalize this to "every task-tied row is folded":** rule 2's task-id tie is a NECESSARY condition on folding, not a sufficient one, so a row whose event TYPE no kernel evidence class defines — a type a CONSUMER project invented — is folded only under a two-part **conjunction** (the card-opt-in route): this card's own **acceptance text NAMES the event type** AND the row is task_id-tied. Name the type in your acceptance, or the row is excluded (the packet now says so out loud rather than rendering an empty section, X-0686).
- **EXCEPTION (cont.) — `cross *` shared-coordination appends ALSO need NO worktree (per SPEC-0084 rule 5).**
  A governed `cross *` append to the kernel-owned SHARED coordination store is the **same journal
  MECHANISM** (append-only + union-merged), so it needs **no worktree** and is in-bounds from any session
  (incl. the main checkout) — see §Scope-boundary discipline for the territory carve-out. UNLIKE an
  `event` / `deviation_captured` append, the shared store lives **OUTSIDE every repo**, so a `cross *`
  append is **not repo-local `events.jsonl` dirt and is NOT reconciled by this repo's `land`** — the
  shared store's own append + union-merge (and kernel-only rotation) handle it (mechanics: the protocol
  sibling SPEC-0085). This section grants only the no-worktree + territory legality; it asserts no
  land-fold for the out-of-repo store. Authority home: SPEC-0084 (`graph query SPEC-0084`).
- **EXCEPTION (cont.) — the CONSUMER BOOTSTRAP (`bin/yitc-v2 -C <path> init`) needs NO worktree AND makes a
  sanctioned one-time direct-to-`main` bootstrap COMMIT.** A fresh consumer has no task/work
  worktree workflow yet and cannot even `land` until `init` delivers its verify contract — a chicken-and-egg
  the worktree→land path cannot resolve. So `init` (the consumer-side bootstrap verb) both WRITES its born
  scaffolds without a worktree AND commits them + the journal directly to `main` (ensuring `main` is the
  checked-out branch first), so the bootstrap reaches main via a GOVERNED commit, not a loose dirty working
  tree. It stages ONLY the init-managed scaffolds (never `git add -A`)
  and is idempotent. Retiring a stale non-main default branch (e.g. `master`) is a separate normalization
  concern, handled by its own follow-up task. Every OTHER source/artifact write — including in a consumer
  once bootstrapped — rides the worktree→land path below. (Same capture-not-isolation rationale as the journal-append exception.)
- **EXCEPTION (cont.) — the ONBOARDING-POINTER writes (`memory consume --station <id>` / `memory
  seed`) self-commit their MEMORY.md change directly to `main`, on IDENTICAL terms (per the X-0274 and
  X-0330..0332 incidents).** A SPEC-0147 station is voiced+consumed, or seeded into a
  consumer, on the MAIN checkout at a session-start / provisioning seam — no worktree batch carries
  the write, and a dirty MEMORY.md sits in `land`'s **non-bookkeeping** set, so leaving it
  uncommitted wedges EVERY later land in that repo (measured on three consumers, 2026-07-12). So
  each verb owns its own governed commit, the **second and third** sanctioned direct-to-main commits
  alongside the `-C init` bootstrap above. Kept NARROW by construction, both alike: staging
  **MEMORY.md + the one journal receipt ONLY** (never `git add -A`); fail-closed refusal on
  preexisting MEMORY.md dirt, on a journal delta that is not a VALID APPEND (parseable, purely
  appended event lines — validity, NOT substantiveness, per X-0361), or on a merge in
  progress; a deterministic message; idempotent, receipt-gated no-op on re-run. `init`'s in-process
  seed rides `init`'s OWN bootstrap commit at that seam, so an aborted init strands nothing. Inside
  a real `task/`/`work/` worktree both ride that batch, unchanged — every OTHER buffer-entry write
  still takes a `work/<slug>` worktree→land. Posture-matched to the terminal task pause/wont-do/park
  self-commits. Rule homes: SPEC-0039 §5(b) / SPEC-0147 §7.
- **EXCEPTION (cont.) — five TASK-CARD verbs joined the same scoped-self-commit family, on the same
  bounds.** `task claim-landed` (per X-1002) writes `ready → in-progress` + its `task_picked`
  for a card whose deliverable is DERIVABLY already on `main`, without a worktree — admission is
  derived and fail-closed, never asserted, so it refuses every ordinary card and the claim
  path is untouched. `task refuse` records the SPEC-0133 pre-claim refusal onto a `ready`
  card without touching its status. `task update --queue-jump` sets/clears the SPEC-0184
  rule-9 land-admission mark, writing it at a merge-stable HEADER position and suppressing the
  `last_verified` bump so a concurrent closing branch does not conflict. **The two late-linkage
  SETTLE arms of `task close` are members too — `--settle-probe` and
  `--settle-observation` **: each writes a governed record onto an already-DONE card whose
  own writing worktree is long gone, so from `main` it owns its own scoped commit exactly as the
  three above do. All five stage the card +
  the journal receipt ONLY, refuse on preexisting card dirt, are idempotent on re-run, and defer to
  the ordinary in-worktree path when run inside a writing worktree.
  - **The deferral half is load-bearing, not a tidiness rule (promoting the halt of
    2026-09-04).** A settle that self-commits INSIDE a writing worktree strands a **reading-class**
    card — one whose deliverable IS a governed record written into ANOTHER card: the authored content
    lands under the other card's id BEFORE the citing card's own `task commit`, so the recorded ship
    carries only that card's own bookkeeping and `audit post` loud-stops on the
    no-authored-content guard, with every available exit (`--zero-ship-diff`, `--repin-ship`)
    asserting something untrue. So inside a `task/` or `work/` worktree a settle writes NOTHING to
    git and rides the batch. The `--settle-live-probe` / `--live-probe-outcome` arms have **not** yet
    been brought onto this rule.
- **ANY WRITE** happens in a short-lived **worktree + branch** off `main`:
  - `task/T-XXXX` — a single-task Build flow (bounded by the 9-stage contract).
  - `work/<slug>` — any other coherent filing batch (a spec, plan, draft, or a Review that
    files tasks / operates the frozen-decision backlog). Landed promptly — NOT a long-lived "misc" branch.
  - **Why `--task` vs `--work` (the choice IS derivable — split on WHAT the artifact IS, not its
    file-type):** `--task T-XXXX` works UNDER an *existing* task id (its 9-stage flow) — use it when the
    artifact is that task's **DELIVERABLE**, INCLUDING a doc/pattern authored under a claimed docs/feature
    task (precedent: commits `docs` / `docs` in a `task/` worktree — a doc is NOT
    automatically a `--work` artifact). Use `--work <slug>` when the artifact's **carrier IS the batch
    itself**: a standalone reference owned by no task (a `spec` via `spec new`, an idea, a plan draft) OR
    a brand-new task with **no id yet** — let the *filing verb* (`task file` / `spec new`) ALLOCATE the id
    inside the worktree (chicken-and-egg: no `task/T-XXXX` worktree for a task that doesn't exist — the id
    is filing's output, not its input). **Filing is NOT executing — the hand-off:** when `task file`
    allocates a task id in a `--work` batch, that batch's job ENDS at filing — **`land` it, THEN claim the
    new id via `worktree new --task T-XXXX` and run the 9 stages in THAT worktree.** Do NOT author the
    task's deliverable inside the filing batch.
- Create it before the first edit with the verb (control-point, NOT raw git —): `bin/yitc-v2
  worktree new --task T-XXXX` (or `--work <slug>`). The verb emits a `worktree_created` journal event;
  a raw `git worktree add` leaves no such evidence. (Raw git stays a legitimate recovery escape hatch.)
- **`worktree new --task` ALSO claims the task** (option B): it validates the task is
  `ready` + unblocked BEFORE creating the worktree, then writes `ready → in-progress` (Analysis) +
  the `task_picked` event INSIDE the new worktree, so the claim reaches `main` only via `land`. A `task
  pick` on `main` would leave an uncommitted claim the worktree (branched from committed HEAD) never
  sees — the desync. `task pick` is therefore a **read-only inspector** only.
- Integrate via the single blessed path, **run FROM the main checkout — never `cd` into the worktree**:
  **`bin/yitc-v2 land --task T-XXXX`** or **`bin/yitc-v2 -C <worktree> land`** (for a `work/<slug>` batch:
  `land --branch work/<slug>`). It does update-from-main → events union+dedup → graph rebuild → verify → ff-only main → remove worktree;
  one run-from-main form removes all three frictions at once (no wrong-branch ABORT, no getcwd false-fail,
  no `cd`-back dance). `main` stays the SOLE integration branch — no PR/release/dev-branch ceremony.
- **Why `main` looks "stale" until land (this is isolation, NOT a bug):** a worktree is a normal
  git branch off `main`; `main` advances ONLY via the ff at `land`. So every edit, the claim
  (`ready→in-progress`), and emitted events are INVISIBLE on `main` until you land — standard
  feature-branch isolation, exactly what lets concurrent sessions not collide. Corollary
  (the Slip-5 trap): a *relative* grep run from the main checkout won't see your worktree's
  edits — **verify a write in the same checkout you wrote it** (absolute path or `git -C <worktree>`).
- **Fallback — ONLY if you did `cd` into the worktree** (the run-from-main form above avoids this): `cd`
  back to main after `land` — land removed the worktree dir, leaving the shell in a deleted directory (`getcwd` error / nonzero exit though land succeeded); `land` prints a `cd <main>` cue.
- **Backgrounded / tool-invocation callers: key off the `LAND:` token, NOT the shell exit.** Land emits a contracted machine-readable **terminal-status token as its FINAL stdout line**:
  `LAND: OK <sha>` on success / `LAND: ABORT <reason>` on refusal (match `^LAND: (OK|ABORT)\b`,
  case-sensitive — the lowercase human `land:` line + the `cd <main>` cue never collide); parse THAT, not
  the shell exit. Run-from-main keeps your cwd alive, but the token matters either way: the legacy
  in-worktree `cd <worktree> && bin/yitc-v2 land` has its cwd removed by the *successful* land so the
  wrapper's `getcwd` fails and the shell exit reads nonzero though land exited 0 (E-0010 manifestation D —
  the false-fail); the token survives it. The `land_completed` journal event stays INTERNAL provenance —
  the STDOUT token is the single caller-facing terminal-status contract.
  - **A `LAND:`-ONLY filter is not a complete watcher — capture STDERR and admit `^yitc-v2:` too.** A pre-verify REFUSAL (a missing `-C` target, a fail-closed session identity, any guard
    upstream of `cmd_land`'s terminal-signal seam) never reaches the token: it prints as a plain
    `yitc-v2: …` line on **stderr** and exits nonzero, so a `^LAND:`-only watcher captures an EMPTY
    file (measured 2026-08-13, X-0843 — an instance of SPEC-0165 item 11). Redirect `2>&1` and match
    `^(LAND:|yitc-v2:)`; the `LAND:` token stays the TERMINAL-STATUS contract, unchanged.
    **That widening is for CAPTURE ONLY — never gate TERMINALITY on it (SPEC-0180 rule 2c).**
    Terminality is **token-or-exit**: the `^LAND: (OK|ABORT)\b` token, or the land process EXITING.
    `yitc-v2:` is the tool's GENERIC message prefix — `land` prints ordinary progress under it (the
    graph auto-rebuild notice, the verify heartbeat) — so a bare `yitc-v2:` line is terminal only WITH
    an exit, never on its own. Collapsing the two is a measured false green: a poll loop keyed on
    `^(LAND:|yitc-v2:)` fired at 47 s on a graph-rebuild notice while the land was still verifying, and
    its premature exit then killed the healthy land. Capture wide; gate narrow.
- **`land` verify runs for several MINUTES — and how you run it SPLITS BY SESSION KIND ( — the
  two audiences must not be conflated; the §2 verify step update-from-main → graph rebuild → pinned
  hermetic test suite routinely runs minutes, longer than a tool's short default command timeout):**
  - **INTERACTIVE session:** PREFER **backgrounding `land`** and keying off the `LAND:` token — it frees
    the conversation instead of blocking on a minutes-long verb; OR set a generous foreground timeout up
    front. (A foreground caller on a tool's short default timeout gets verify KILLED mid-run and must
    re-run — recurring friction, 2026-06-25.) **Qualifier — under verify-admission CONTENTION, WRAP the
    land in the harness Monitor primitive and key recovery off the JOURNAL** (2026-07-18, fingerprint
    `interactive-background-land-killed-in-admission-wait`): a land queued on a SPEC-0132 admission slot
    (`waiting_for_verify_admission_slot` heartbeats, no output) outlives BOTH a plain background land
    (swept nondeterministically) AND a plain foreground one (the harness ~600s cap kills the group at its
    move-to-background boundary) — so run it under the harness **Monitor** (a persistent
    watch-until-condition wrapper that outlives one turn/cap — survived 2/2 incl. hour-long waits), and
    key ALL recovery off the JOURNAL (`LAND:` token + admission heartbeats + the IDEMPOTENT `worktree
    recover-land` / re-`land` verbs, `patterns/background-session-monitoring.md`), NEVER off the wrapper's
    process lifetime. Parallel lands stay — **NO land fan-out cap** (owner directive 2026-07-18). The token contract is unchanged.
    **AMENDED 2026-08-24 — the wrapper choice is no longer a CORRECTNESS requirement, because
    the land no longer shares the wrapper's process group.** The qualifier above was accurate and its
    journal-keyed-recovery half is UNCHANGED — but it could not deliver its own promise ("key ALL
    recovery off the JOURNAL, NEVER off the wrapper's process lifetime") while the wrapper *owned* the
    land instead of merely watching it: journal-keyed recovery then recovered a land already destroyed,
    and the lost admission-queue position (~40 min, 2026-08-23) was not recoverable at all. That is why
    the class recurred through 4 measured deaths under a rule that was correct as written — the remedy
    held only while every operator picked a persistent wrapper, and picking wrong failed **silently**.
    A non-worker `land` now **leaves the caller's process group at entry** (`os.setsid`, journaled as
    `land_process_group_escaped`), so a group-directed kill aimed at your wrapper no longer reaches the
    land. **What this changes for you:** a watcher that dies, times out, or was **never armed** now costs
    a **re-arm and nothing else** — re-attach by tailing the journal or the log; do NOT re-run `land`
    on the assumption the first one died. Monitor stays the **recommended** wrapper (you still want to
    SEE the token, and a persistent watcher is still the least friction), but it is now an ergonomic
    preference, not the thing standing between you and a destroyed land. Opt back into the old coupling
    with `YITC_LAND_KEEP_PROCESS_GROUP=1` if you ever need the land to die with its caller.
    **Telling them apart — and the ONE thing durable state cannot tell you** (narrowed by owner ruling
    2026-08-24 on a GREEN external adjudication; the verdict YAML and the full rationale live with this
    change's own task card and in `patterns/background-session-monitoring.md` — cited there rather than
    by filename here, because the published release view strips task ids and a path carrying one would
    render as a file that does not exist)**:**
    both `_LAND_QUEUE_WAIT_TYPES` heartbeats carry the land's `pid`; an external kill by a CATCHABLE
    signal journals `land_terminated_externally` — that row names a cause because the land's own
    handler witnessed it. **Heartbeat staleness** (3 missed beats of the published cadence) says only
    that the land **STOPPED EMITTING, cause unknown** — it does NOT say "killed". An UNCATCHABLE kill
    (SIGKILL) and a silent hard crash (segfault, OOM) leave IDENTICAL rows, because no process can
    journal its own SIGKILL; separating those two needs an EXTERNAL observer (a parent's wait status,
    the killer's own log, cgroup/OOM or auditd records), none of which is the dead land's durable
    state. So: **do not read a stale heartbeat as evidence that something killed your land.** What you
    DO get is the discrimination that matters operationally — a land that stopped emitting never reads
    the same as a healthy queued one. (Absence of a `LAND:` token proves nothing on its own — that is
    the general reading rule, homed once at SPEC-0165 item 11, not restated here.)
    The **DISPATCHED WORKER** case below is the opposite rule and is deliberately untouched: a worker's
    land stays in its worker's process group (SPEC-0103 / SPEC-0180).
  - **DISPATCHED WORKER (headless one-shot):** MUST run `land` **synchronously in the FOREGROUND** with a
    generous timeout — **NEVER background-and-await** the token. A headless worker's process EXITS when it
    yields the turn, so a backgrounded land is killed mid-flight before `LAND: OK` (the recurring
    worker-land-death class — /, 2026-06-27). This is the dispatch preamble rule #1
    (SYNCHRONOUS-TO-LAND) / SPEC-0103; the interactive "prefer background" guidance above does **NOT**
    apply to a worker. Foreground-by-construction belt : in a dispatched-worker context
    (`YITC_EXPECTED_SESSION_REF` set) `land` streams a periodic verify-progress **heartbeat** to stderr
    so the minutes-long foreground run stays visibly alive (no "looks hung" timeout-fear) — tune/disable
    via `YITC_VERIFY_HEARTBEAT_SECS` (default 20s; `<=0` disables). Additive observability only — the
    verify verdict/gate is unchanged.
  (Provider-neutral: the exact default-timeout value is harness-specific — the rule is "land is a
  minutes-long verb"; the foreground-vs-background treatment splits by session kind as above.)

A read-only Controller session is NOT special-cased: it reads on main, but a filing it does takes a
`work/<slug>` worktree like any write.

### Scope boundary discipline (any V2 write)

**Territorial ownership, not semantic relevance** — V2 write scope is path-based, not topic-based; it is the WRITE that is gated, not the posture. "It relates to V2 protocol" ≠ "it's editable from a V2 write".

**V2 territory** (editable by any V2 write):
- `realpath <repo-root>/**` ONLY. Use `realpath`, not a raw string prefix — symlinks inside the repo or `../` relative paths defeat naive prefix checks.

**External territory** (referenced read-only — NEVER edited or made an acceptance probe target from any V2 write; not monitored/probed — with ONE narrow carve-out: a **read-only fold of the kernel-owned SHARED coordination log** for `to:<self>` routing/intake entries (via **`bin/yitc-v2 cross inbox`**) is territory-SAFE and PERMITTED (reading a coordination log for intake ≠ surveillance/probing of another project); the carve-out is read-only and scoped to that shared log — every WRITE to another project's repo stays forbidden, SPEC-0084 §3. *(The retired per-repo `CROSS-TASKS.md`, tombstoned at the cutover / SPEC-0079 superseded, was this carve-out's predecessor surface.)*):
- `<host-home>/projects/ai-team-framework/` (V1 platform)
- `<host-home>/<provider-config>/` (user-level settings, `/yitc` skill commands, hooks)
- `<host-home>/bin/`
- `<host-home>/yitc-workspace/` (operating plans, retrospective drafts)
- `<host-home>/.gitignore`
- Any `realpath <host-home>/*` outside `<repo-root>/`

**Pre-mutate path check** — before Edit/Write/Bash that mutate state: resolve `realpath` of the touched path; verify it starts with the realpath-resolved V2 root. If outside → halt + escalate.

**External-auditor prompt discipline** — prompts sent to the external auditor MUST NOT reference external paths as "artifacts to update / maintain / monitor". Only legitimate references: read-only provenance (sourced_from), historical prior-art citations, boundary definitions (listing what NOT to touch).

**Cross-territory work routing:**
- Surfaced during an executing (Worker / self-executing Controller) flow → halt current action + escalate (route to the Controller / owner) or file a V2 task tagged as a parked V2 dependency (status: parked, parked_reason cites external trigger needed)
- EDITING another project's repo = itself a cross-territory edit = NOT a sanctioned V2 write. Routing cross-project work per §Filing rule is NOT a cross-territory action — it appends the kernel-owned SHARED coordination log via `bin/yitc-v2 cross request` (neutral coordination infrastructure belonging to NO project repo — the shared-store carve-out just below), never another project's repo — this resolves the prior Filing-rule↔Scope-boundary contradiction.

**Shared coordination store — append-in-bounds carve-out (per SPEC-0084 rule 5).** A governed append (via the `cross` verbs) to the **kernel-owned SHARED coordination store** is **territory-IN-BOUNDS from any session**, NOT a cross-repo write — because that store is **neutral kernel-owned coordination infrastructure belonging to NO project repo** (appending to it is not writing another project's repo). The carve-out is **SCOPED to the ONE shared store ONLY**: writing another project's REPO stays forbidden, and own-write / peer-read on per-repo artifacts (incl. the read-only `cross inbox` fold of the shared log above) is UNCHANGED. The append rides the no-worktree journal-append path (§Writes happen in a worktree). Authority home: SPEC-0084 (`graph query SPEC-0084`).

**Legitimate cross-territory references** (NOT leaks):
- `patterns/*` `sourced_from:` provenance fields
- CHARTER / LIFECYCLE / decisions references to `<v1-archive>` or `<v1-workspace>` as prior-art citations (read-only)
- Decision body references to historical V1 incidents (read-only)
- Audit prompt/result path references in legacy artifacts (historical record)

These are read-only provenance, not maintenance obligations.

### Worker (the dispatched executing flow)

- **What:** an ordinary full background session that executes EXACTLY ONE task through all 9 lifecycle stages (analysis → … → done) in its own `task/T-XXXX` worktree, ending in `land` — a pure executor (no handoffs, no in-process sub-workers). **"Build" is this flow's historical name.** A Worker is launched by the Controller via `bin/yitc-v2 dispatch`, NEVER as an in-process subagent; the Controller MAY run this same flow itself, but only on owner say-so (the §Controller fallback).
- **Where:** inside ONE project directory (`<projects-root>/<project-name>/`).
- **Permissions / boundary:** the same orthogonal gates as any session — read/write code in its ONE project, run tests, commit, `land`; the per-write worktree + 9-stage lifecycle + path-territory govern. A cross-project need → halt + route per §Filing rule, never edit another repo.
- The broad, read-leaning, file-tasks/author-specs/run-ad-hoc-audits breadth (the former Review posture) now lives in the **Controller** (§Controller above) — it is not a separate session type.

### Orchestrate posture (controller-selector) — the operational protocol (per CHARTER §6)
<!--AUDIENCE:controller-->

The DEFAULT posture of the interactive main session (now the single **Controller** posture): instead of executing a
task itself, it **selects + dispatches** independent ready tasks to background **Workers** and
**coordinates their order**, then verifies + integrates as they `land`. Dispatch is launched with the
blessed verb **`bin/yitc-v2 dispatch`** (`patterns/background-session-dispatch.md §Dispatch launcher`),
NEVER the provider in-process subagent tool — a Worker is a separate sub-session, not a subagent. It is a selector+dispatcher on
**stateless reads** (the `requires:` topology + the live worktree list + the journal), NOT a stateful
orchestrator. The PROCEDURE (launch / selection / monitoring / abnormal-situation recovery) is homed
single-SoT in `patterns/background-session-operation.md` — this section is the GOVERNANCE rule only
(CHARTER §6 carries the principle-level statement; this is its operational protocol + the boundary).
**Arming the monitor is non-skippable:** immediately after a `dispatch` and BEFORE yielding the turn,
the Controller MUST arm the §Watcher poll-until-terminal monitor — a dispatched Worker is a separate
sub-session the harness sends no completion notification for, so completion-detection is system-driven,
never an owner poke (rule home: `patterns/background-session-monitoring.md §Watcher`).
When the dispatched batch ORIGINATES from the owner stating a LIST of follow-up items, follow the intake
working-order (premise-verify → classify → decompose+batch → ONE owner checkpoint → dispatch → verify
each land) — see `patterns/owner-list-intake-working-order.md` (pointer, not restated here).

**Context-bounded autonomous continuation within the authorized batch (per SPEC-0126).** Once the owner
has authorized the batch, the Controller proceeds task→task WITHOUT pausing for an owner cue at any seam
that carries no human decision — dispatch the next independent ready task, verify each land, keep going —
stopping only on a genuine owner decision or the `session context` threshold (SPEC-0115 → a clean-seam
fresh-session hand-off, SPEC-0114). This changes NOTHING about session start (it still awaits an owner
cue, no auto-pick — §Startup phases); autonomy begins ONLY after that authorization, and self-fetch beyond
the authorized batch stays forbidden (retirement (b)). **Non-blocking batch:** a task that raises a genuine
owner question does NOT freeze the batch — PARK it using its existing waiting-on-owner state (`task pause
--reason owner-wait` — the SOLE carrier, surfaced at session start; NOT the `blocked` status, which no verb
writes — QUEUE §Verb routes), CAPTURE its question durably+visibly via the existing followup/journal capture
(`bin/yitc-v2 followup` — NO new question store/FSM), and CONTINUE the other independent ready tasks; the
owner answers the accumulated questions on reconnect. (Distinct from a task blocked on an unmet `requires:`
dependency, which waits per the QUEUE §Picker rule — this governs the OWNER-QUESTION block only.) Full
rule: `graph query SPEC-0126`.

- **Controller** = the interactive main session in this posture. It decomposes the owner-authorized
  batch, dispatches workers, holds cross-chain ordering, and monitors durable state. It does NOT run a
  worker's 9 stages in-process (it MAY execute a task itself, but only on explicit owner say-so — a
  separate ordinary Worker action in its own worktree).
- **Worker** = an ordinary full background session (the executing flow historically named "Build"): one task, its own `task/T-XXXX` worktree, all 9 stages,
  ending in `land` (a pure executor).

**Named retirements — what STAYS forbidden (the §6-amendment boundary):**
- **(a) no auto-launch / autopilot-FSM** — the owner always starts the controller session AND
  authorizes the batch.
- **(b) batch-bounded** — the controller works ONLY the given batch: no self-fetched work, no infinite
  loop; batch done → report + stop.
- **(c) no in-session sub-worker fan-out** inside one Build — a Build worker is a separate sub-session
  launched with `bin/yitc-v2 dispatch`, never an in-process subagent (that would dissolve per-write
  worktree isolation, the independent-provider audit, and the 9-stage governance at once). Read-only / ephemeral helper
  subagents (search, analysis) stay legitimate — the ban is scoped to the WORKER role, not the tool.
- **(d) no cap/queue-state machinery, no liveness-arming infra, no role-taxonomy** — the controller is a
  selector+dispatcher on stateless reads, not a stateful orchestrator.
- **(e) the worker stays a pure executor** — the cross-chain wait lives in the CONTROLLER, never a
  self-waiting worker.
- **(f) on a missing or ambiguous `requires:` edge the controller does NOT dispatch-by-default** — it
  STOPS and asks the owner / files the fix (a selector+dispatcher, never a silent planner).

If the posture ever wants to spawn autonomously, hold a stateful queue, cap parallelism in code, or
decide-without-owner → STOP: that is the forbidden orchestrator (CHARTER §6 non-goals).

