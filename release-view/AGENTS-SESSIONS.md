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

1. **READ your audience's seed** (all sessions): <!--GEN:read-order:arrow generated from HANDBOOK_READ_ORDER — DO NOT EDIT; regen via `graph build`-->CHARTER.md → AGENTS-STARTUP.md → AGENTS-SESSIONS.md → AGENTS-PROTOCOL.md → LIFECYCLE.md → QUEUE.md → GRAPH.md<!--/GEN:read-order--> + the floor trigger-map (`graph/floor-trigger-map.md`) — who reads which form of it, and how, is homed in AGENTS §At session start.
   Nothing task-specific here — so the AI always holds the rules.
2. **`bin/yitc-v2 session start`** (the session-tied `--help` scan comes before your first guarded work verb: AGENTS §At session start). `session start` is a **NON-MUTATING dispatch** (reads/reports startup state; never
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
     decision's own task card). A **FOREIGN- or un-stamped worktree
     is NEVER auto-resumed**: BLOCK «already held by session X» — PRESENCE is NOT orphanhood; adoption
     stays EXPLICIT, never auto. ONE carve-out : a CONTROLLER startup whose foreign holder is CONFIRMED
     DEAD (the SPEC-0133 `_session_proc_alive` predicate) prints `acting in <T>` + the `controller_acting_in_worktree`
     key instead — read-only, nothing stamped, so execution verbs still refuse. An own-stamped resume holds
     regardless of how many OTHERS are in-progress. **The own-stamp / foreign branch check runs
     FIRST and returns before any count logic — so the await-owner posture below NEVER suppresses an
     own-stamped resume.** Else by `in-progress` count: 1 → print its resume contract (resume of
     existing work, not a queue-scan); **0 or >1 → await an owner cue, NO candidate** (>1 first
     prints a brief concurrent note). **No auto-picker :** the dispatch STOPS
     auto-scanning the queue after startup — it does NOT offer a top-ready candidate; it ALSO surfaces the
     WAITING-ON-OWNER paused-task signal (a safety reminder) and runs NO auto-counts (no `N ready / M
     parked` queue scan until cued). **A MEMORY continuation-seed / `[instruction]` entry is NOT the owner cue (SPEC-0039 §4):** even when
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
     NOT-grounds + the stop-and-name-the-ground reflex live in SPEC-0141 §2/§3a/§3b (single-SoT).** ">1" is concurrent, not a dissonance — same-task double-claim is structurally impossible (unique ids + the worktree guard). **Session start is UNCHANGED by SPEC-0126's autonomous-continuation
     doctrine (per SPEC-0126):** it still AWAITS an owner cue and NEVER auto-picks — context-bounded
     autonomous continuation begins ONLY after the owner authorizes a plan/batch (the doctrine home is
     §Orchestrate posture + CHARTER §6), never at startup.
   - **cross coordination-log surface (report-only, per SPEC-0086):** the `cross-coord:` counts `session start` prints are
     surfacing, NOT a queue-scan and NOT an auto-pull — intake (pull / act) stays an owner-commanded `cross pick`/`task file` act.
     `cross outbox` / `cross inbox` re-fold the full non-terminal ledger (no subset verb — the vocabulary is frozen). The shared
     log is identity-agnostic (every participant folds the SAME out-of-repo log). **Triage default (SPEC-1010 §3):** sort each `to:me` item and judge whose matter it is BEFORE taking it — how it is sorted, the default answer and what the note names are homed there, not restated here.

   **This AMENDS Phase-3 dispatch** — ** is Final/frozen and stays cited as
   superseded-in-part** for that clause: the **resume** halves (own-stamp + len==1) and the
   `session_started` emit ( base) are unchanged; the auto-**pick**, the auto-**counts** and the
   Build|Review type choice are RETIRED. The new standing rule is HOMED here (this
   mandatory-tier section, re-read verbatim post-`/compact`).

Task pickup thus lives in the Controller dispatch of the verb, on an owner cue (never a pre-choice phase). The v1
continuation-rehydrate battery (cap / monitor-arm / release-debt / aggregate-counter) is **NOT**
imported — session startup runs no capacity/parallelism, monitor-arming, release-state, or
aggregate-counter logic (solo *author*, one-task-at-a-time — sequential, per-session count not capped — no UNBOUNDED pipeline (the **default** bounded orchestrate controller-selector posture — §Session-types → Orchestrate posture — IS that bounded selector+dispatcher, not the UNBOUNDED pipeline), no-release V2 — but
concurrent SESSIONS are expected; "solo" = one author, not one session at a time). Enforcement stays deferred (non-goal #7).

### Controller (the interactive posture)
<!--AUDIENCE:controller-->

- **Where:** the interactive main session — broad across projects (read-leaning): reads ANY project, files tasks, authors specs/plans, runs ad-hoc audits.
- **What:** **DEFAULT — take the orchestrate controller-selector posture** (§Session-types → Orchestrate posture): instead of executing itself, dispatch independent ready tasks to background **Workers** and coordinate their order — via `bin/yitc-v2 dispatch` (`patterns/background-session-dispatch.md §Dispatch launcher`), never the provider in-process subagent tool. **Fallback (owner say-so) — execute a task itself / make a bounded in-scope edit:** run the Worker flow in-session — **one task at a time** through all 9 lifecycle stages without handoffs (a session may take further tasks in sequence).
- **Permissions:** read ANY project; write code / specs / plans / tasks, run tests, commit, deploy (if owner authorized). The right to write comes from the orthogonal gates (path-territory / worktree-before-write / 9-stage lifecycle), NOT the posture label.
- **Boundary:** every WRITE stays in ONE project. Cross-project observation → halt + route per §Filing rule (a `bin/yitc-v2 cross request` coordination item; governed by SPEC-0084/85/86), never silent implementation. Dispatch is the default because it keeps the Controller's context for coordination — a clear or sequential chain included (rule + the mode-cost duty: SPEC-0141 §3a). Either way it rides the ordinary worktree + 9-stage lifecycle.

### Writes happen in a worktree

**The trigger is the WRITE, not the session label.** Parallel sessions sharing one working
tree collide (the 2026-05-29 incident: a duplicate ID + a `git add -A` cross-sweep).
This is exactly **WHY the per-write worktree is MANDATORY, not optional** : concurrent sessions are expected and
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
- **EXCEPTION (cont.) — the SCOPED SELF-COMMIT family: each of these verbs commits its OWN narrow
  record when run from the main checkout and rides the batch inside a writing worktree — never
  hand-commit for one.** Members: `memory consume --station <id>` / `memory seed` (the
  onboarding-pointer MEMORY.md writes ONLY — every other buffer-entry write still takes a
  `work/<slug>` worktree→land; SPEC-0039 §5(b) / SPEC-0147 §7), `task claim-landed` (ONLY a card whose
  deliverable is derivably already on `main` — every ordinary card still claims via
  `worktree new --task`), `task refuse` (the SPEC-0133 pre-claim refusal), `task update --queue-jump`
  (the SPEC-0184 rule-9 land-admission mark), and the `task close` settle arms `--settle-probe`
  (SPEC-1011) / `--settle-observation`. From the **main checkout** each stages its one artifact
  (MEMORY.md, or the card) + the journal receipt ONLY (never `git add -A`), refuses on preexisting
  dirt in that artifact, and is idempotent on re-run. Inside a `task/` or `work/` **writing
  worktree** none commits to `main`: each defers to the ordinary in-worktree path, so its write
  reaches `main` only with that batch's `land` (`task claim-landed` refuses there and names the
  ordinary claim). A settle arm writes NOTHING to git there — the batch's own `task commit` carries
  it; the `--settle-live-probe` / `--live-probe-outcome` arms are not yet on that rule and still
  make their own scoped commit. Each verb's admission detail is at the head of its `--help`, which
  names its home.
- **EXCEPTION (cont.) — `session handoff *` needs NO worktree.** It writes
  ONLY the anchored repo's `<git-common-dir>/yitc/handoffs/` (machine-local, never in the working tree,
  never committed) plus its journal rows — never a source/artifact file — so it runs from any checkout.
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
- Create it before the first edit with the verb (control-point, NOT raw git): `bin/yitc-v2
  worktree new --task T-XXXX` (or `--work <slug>`). The verb emits a `worktree_created` journal event;
  a raw `git worktree add` leaves no such evidence. (Raw git stays a legitimate recovery escape hatch.)
- **`worktree new --task` ALSO claims the task** (option B): it validates the task is
  `ready` + unblocked BEFORE creating the worktree, then writes `ready → in-progress` (Analysis) +
  the `task_picked` event INSIDE the new worktree, so the claim reaches `main` only via `land`. A `task
  pick` on `main` would leave an uncommitted claim the worktree (branched from committed HEAD) never
  sees — the desync. `task pick` is therefore a **read-only inspector** only.
- Integrate via the single blessed path, **run FROM the main checkout — never `cd` into the worktree**:
  **`bin/yitc-v2 land --task T-XXXX`** / **`bin/yitc-v2 -C <worktree> land`** (a `work/<slug>` batch:
  `land --branch work/<slug>`). It does update-from-main → events union+dedup → graph rebuild → verify → ff-only main → remove worktree;
  run-from-main removes all three frictions at once (no wrong-branch ABORT, no getcwd false-fail, no
  `cd`-back dance). `main` stays the SOLE integration branch — no PR/release/dev-branch ceremony.
- **A non-union merge conflict from main has a COVERING VERB — never finish it with raw `git commit`:**
  `land` and `worktree sync` both STOP on one. Resolve the named files, `git add` each, then
  **`bin/yitc-v2 worktree sync --resolved --task T-XXXX`** — it refuses a half-resolution, commits the
  merge, and records WHICH paths you resolved (`merge_resolved_by_hand`). Custody is UNCHANGED: a hand
  resolution is authored content, so SPEC-0077 §3a still requires the re-audit.
- **Why `main` looks "stale" until land (isolation, NOT a bug):** a worktree is a branch off `main`, which
  advances ONLY via the ff at `land` — so every edit, the claim (`ready→in-progress`) and emitted events are
  INVISIBLE on `main` until you land, which is what lets concurrent sessions not collide. Corollary
  (the Slip-5 trap): a *relative* grep from the main checkout won't see your worktree's edits —
  **verify a write in the same checkout you wrote it** (absolute path or `git -C`). Fallback if you DID `cd`
  in (run-from-main avoids it): `cd` back after `land` — it removed the worktree dir, so `getcwd` fails and the exit reads nonzero though land succeeded (`land` prints a `cd <main>` cue).
- **Running `land` — read its FINAL stdout line, never the shell exit.** That line is the terminal-status
  token `LAND: OK <sha>` / `LAND: ABORT <reason>` (match `^LAND: (OK|ABORT)\b`). Capture STDERR too
  (`2>&1`, match `^(LAND:|yitc-v2:)`): a refusal before verify prints only a `yitc-v2:` line and no
  token. **Terminal = the token or the land process exiting** — `yitc-v2:` also prefixes
  ordinary progress, so never gate on that line alone (SPEC-0180 rule 2c). The verify runs for
  MINUTES, and how you wait SPLITS BY SESSION KIND:
  - **INTERACTIVE session:** PREFER running it in the background, keyed off the token or the
    journal; key recovery off the journal, NEVER off the wrapper's process lifetime. A non-worker land
    leaves your session at entry (journaled `land_process_group_escaped`;
    `YITC_LAND_KEEP_PROCESS_GROUP=1` restores the old coupling), so a watcher that dies, times out or
    was never armed costs a **re-arm, not a re-land** — re-attach by tailing the journal or the log.
    A land PROVEN failed keeps its governed recovery route (`worktree recover-land` / re-`land`).
  - **DISPATCHED WORKER (headless one-shot):** run it **SYNCHRONOUSLY in the FOREGROUND**, with a
    generous timeout — NEVER background-and-await: a headless worker's process exits when it yields the
    turn, killing the land (SPEC-0103); when the land (or `task test --run`) cannot fit the per-call
    cap, the held-turn exit is SPEC-0180's.
  - The rest — timed-wrapper kill shapes, admission waits, telling a stopped land from a queued one,
    the opt-out knob, the worker heartbeat — is `patterns/background-session-monitoring.md`
    §Running land; `land --help` names it too.

A read-only Controller session is NOT special-cased: it reads on main, but a filing it does takes a
`work/<slug>` worktree like any write.

### Scope boundary discipline (any V2 write)

**Territorial ownership, not semantic relevance** — V2 write scope is path-based, not topic-based; it is the WRITE that is gated, not the posture. "It relates to V2 protocol" ≠ "it's editable from a V2 write".

**Own territory = the repository this session works in** (editable by any write from this session — in the engine, the engine root; in a consumer, that consumer's own root):
- `realpath <repo-root>/**` ONLY (the engine's own root; a consumer session reads its own repository root here). Use `realpath`, not a raw string prefix — symlinks inside the repo or `../` relative paths defeat naive prefix checks.

**External territory** = anything outside that repository (referenced read-only — NEVER edited or made an acceptance probe target from any write; not monitored/probed — with ONE narrow carve-out: a **read-only fold of the kernel-owned SHARED coordination log** for `to:<self>` routing/intake entries (via **`bin/yitc-v2 cross inbox`**) is territory-SAFE and PERMITTED (reading a coordination log for intake ≠ surveillance/probing of another project); the carve-out is read-only and scoped to that shared log — every WRITE to another project's repo stays forbidden, SPEC-0084 §3. *(The retired per-repo `CROSS-TASKS.md`, tombstoned at the cutover when its per-repo spec was superseded, was this carve-out's predecessor surface.)*). The engine host's neighbours, as examples:
- `<host-home>/projects/<project>/` (V1 platform)
- `<host-home>/<provider-config>/` (user-level settings, `/yitc` skill commands, hooks)
- `<host-home>/bin/`
- `<host-home>/yitc-workspace/` (operating plans, retrospective drafts)
- `<host-home>/.gitignore`
- Any `realpath <host-home>/*` outside `<repo-root>/`

**Pre-mutate path check** — before Edit/Write/Bash that mutate state: resolve `realpath` of the touched path; verify it starts with the realpath-resolved root of the repository this session works in. If outside → halt + escalate.

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
**The monitor is armed BY THE LAUNCH :** a dispatched Worker is a separate sub-session the harness sends no completion notification for, so detection is system-driven, never an owner poke (rule home: `patterns/background-session-monitoring.md §Watcher`). `dispatch` itself continues into the §Watcher loop in the SAME process and ends on its `WATCH:` token — there is NO post-dispatch arming step to take or skip (X-1443 / X-1440). Run the `dispatch` call, and a `dispatch --watch` re-arm alike, under the harness background primitive with its stdout left attached — not redirected to a file, not piped, not filtered: a call whose stdout goes to a file is recorded `watch_armed(reachability=unreachable)` and earns no monitoring credit, under the harness background primitive too.
`dispatch --watch` remains the route for RE-arming once a watch has ENDED (woke / timed out) and for a launch run `--no-self-arm-watch`; a `--watch` over ids with a LIVE watcher is refused as a duplicate — one live watcher per task, never two.
When the dispatched batch ORIGINATES from the owner stating a LIST of follow-up items, follow the intake
working-order (premise-verify → classify → decompose+batch → ONE owner checkpoint → dispatch → verify
each land) — see `patterns/owner-list-intake-working-order.md` (pointer, not restated here).

**Context-bounded autonomous continuation within the authorized batch (per SPEC-0126).** Once the owner
has authorized the batch, the Controller proceeds task→task WITHOUT pausing for an owner cue at any seam
that carries no human decision — dispatch the next independent ready task, verify each land, keep going —
stopping only on a genuine owner decision or the `session context` threshold (SPEC-0115 → a clean-seam
fresh-session hand-off, SPEC-1004). This changes NOTHING about session start (it still awaits an owner
cue, no auto-pick — §Startup phases); autonomy begins ONLY after that authorization, and self-fetch beyond
the authorized batch stays forbidden (retirement (b)). **Non-blocking batch:** a task that raises a genuine
owner question does NOT freeze the batch — PARK it using its existing waiting-on-owner state (`task pause
--reason owner-wait` — the SOLE carrier, surfaced at session start; NOT the `blocked` status, which no verb
writes — QUEUE §Verb routes), CAPTURE its question durably+visibly via the existing followup capture
(`bin/yitc-v2 followup add` with `OWNER-QUESTION: <T-ID>` in the text — it reads `fired` once that card
closes, SPEC-0095; NO new question store/FSM), and CONTINUE the other independent ready tasks; the
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

