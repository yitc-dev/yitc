# Onboarding onto YITC — frictions log ARCHIVE (gate-1 ai-gateway · gate-1.5 social-scraper)

> **Split note (per SPEC-0120 §3 per-doc size band).** These are the EARLY, completed-gate
> frictions — **ai-gateway gate-1** + **social-scraper gate-1.5** + the gate-1 meta-analysis — RELOCATED
> VERBATIM out of `patterns/onboarding-onto-yitc-frictions-log.md` at the gate-1.5 → gate-2 seam, so both
> files load in ONE bounded read (the combined log had reached 906 lines / 83.7 KB — past the SPEC-0120
> must-split ceiling). Content was RELOCATED, not changed. The **LIVE** log (gate-2 trend-finder onward +
> the append-live discipline) stays in the sibling `patterns/onboarding-onto-yitc-frictions-log.md`;
> append EVERY new friction THERE, never here — **this archive is frozen**.

### ai-gateway gate-1 (brownfield) — 2026-06-23

- **`-C` resolves to the monorepo root, not the service.** ai-gateway lived at
  `<host-home>/services/ai-gateway`, a subdir of the `<host-home>` monorepo — `git -C … rev-parse
  --show-toplevel` returned `<host-home>`. Forced the B0 standalone-repo prerequisite. → generalised into B0.
- **The service path is hardcoded in live host automation.** `<host-home>/services/ai-gateway` is hardcoded
  in `offsite-backup.sh` (×2 — Contabo + B2 billing-data backup), `session-scope-guard.sh` (cross-project
  access allowlist), and `registry.yaml` `path:`. A naïve relocate would have silently dropped offsite
  backup coverage of the live billing DB. → generalised into B0 step 1 (preflight the path coupling FIRST).
- **Runtime billing DB lives in-tree.** `data/gateway.db` (live SQLite, gitignored) is runtime state, not
  source — excluded from the carve, stays with the running deploy. → generalised into B0 step 2.
- **Worth-it confirmed by growth, not current size.** ai-gateway is ~250 LOC today (one FastAPI file) but
  is slated to grow toward provider-independence (multi-provider abstraction/routing/billing) — that
  upcoming bulk is the scaffold-payoff justification, not the current size.
- **Carve EXECUTED 2026-06-23 (owner-authorized from the V2 session — captured `deviation_captured`
  `host-carve-out-from-v2-session-owner-authorized`).** New standalone repo `<host-home>/projects/ai-gateway`
  (fresh, `git init`, initial commit `16263ac`; history stays in the `<host-home>` monorepo archive). Source
  copied; `data/` (live billing DB) + the stale empty `.git` excluded. `git -C … rev-parse` now resolves
  to the new repo; `bin/yitc-v2 -C` accepts it → the migration is unblocked.
- **The live service is a RUNNING container, not just files.** `docker ps` shows `ai-gateway` Up 5 weeks —
  the deploy is path-independent once running, so the carve (copy, not `mv`) caused ZERO outage. → B0
  step 3 reaffirmed (copy, never `mv`).
- **Registry repoint is SAFE; the live-deploy cutover is NOT — split them.** `registry.yaml` `path:`
  repointed to the new repo immediately (verified safe: `watchdog.sh` keys off the docker container NAME
  not the registry path; `validate-registry.sh` only checks path-exists, which the new path passes; ~10
  other scripts read the registry but none restart ai-gateway from its path). BUT the DEPLOY cutover stays
  deferred to an explicit owner step — it touches the live billing service + its hardcoded backup. →
  generalised: *repoint the source home now (cheap, reversible); gate the live-deploy cutover behind an
  owner-confirmed window.*
- **Two-copies divergence hazard (transitional).** Until cutover there are TWO copies — the RUNNING one at
  `services/ai-gateway` (canonical for the live deploy + its offsite backup) and the new SOURCE repo at
  `projects/ai-gateway`. Do NOT edit the running copy during the window, or the source repo goes stale.
  → generalised: *keep the transition window short; name the single editable copy.*

### ai-gateway gate-1 — DEPLOY cutover DONE (2026-06-23)

The full cutover ran end-to-end (owner-authorized, same session as the carve):
1. **Redeployed from the new repo** — pre-built the image first (no downtime), then `docker compose down`
   (services) → carried the live `data/gateway.db` over (md5-verified static snapshot) → `up -d` from
   `projects/ai-gateway`. Downtime = seconds. Verified: container `COMPOSE_DIR`+mount = `projects/`,
   `/health` green, billing endpoint reads the DB.
2. **Backup repointed** — `bin/offsite-backup.sh` ×2 → `<host-home>/projects/ai-gateway` (auto-committed).
3. **Scope-guard repointed** — `bin/session-scope-guard.sh` allowlist → `projects/` (auto-committed).
4. **Old copy** — `services/ai-gateway` kept STOPPED as a rollback copy (retire after a confidence window;
   history is in the `<host-home>` monorepo git regardless).

**Host-config commits ride the `<host-home>` AUTO-COMMITTER** — registry.yaml + the two `bin/` scripts were
committed by the host's `chore(auto): update …` committer, not by hand. → generalised: *a host project's
config edits land via the host's own commit mechanism; don't hand-commit the monorepo (it carries the
owner's other pending changes).*

#### Cutover frictions (live)

- **An ops move can return exit-0 while NOT having moved (wrong-cwd trap).** The first `up` ran from the
  OLD cwd (`services/`, the chained block missed `cd projects/`) — it exit-0'd and the service was healthy,
  but `COMPOSE_DIR`/mount still pointed at `services/`. Caught ONLY by inspecting the container labels, not
  by the exit code. Captured `deviation_captured` `ops-move-wrong-cwd-trusted-exit-code`. → **generalised
  (B0 verify-step): after any deploy move, assert `docker inspect … COMPOSE_DIR + Mount.Source` point at
  the NEW path — never trust exit-0.** (The redo via `up` from the correct cwd did a clean `Recreate`.)
- **Minimise downtime: build the new image BEFORE the down/up swap** (the build is the slow part; the
  swap is then a seconds-long down → copy-DB → up).
- **Runtime data ≠ source: carry the live DB explicitly.** The carve excluded `data/gateway.db` (runtime),
  so the new repo started with an empty `data/`; the cutover must copy the live DB across (after `down`,
  for a consistent static snapshot) or the service starts with empty billing history.
- **Activation-checklist SET ≠ `yitc-ops.yaml` carrier sections — two surfaces (captured
  `deviation_captured` `activation-checklist-set-not-1to1-with-yitc-ops-carrier-sections`; finding A).**
  Running the import-completeness gate, the SET's 3 universal concerns (deploy / no-secrets / behavioral)
  read as «3 carrier sections to fill», but only DEPLOY is a `yitc-ops.yaml` section — no-secrets +
  behavioral are standing-mechanism concerns acknowledged elsewhere. The external auditor confirmed
  the split is correct BY DESIGN (wording gap, not a missing carrier section). → generalised into §Shared
  core : the gate guidance now states the two-surface split + WHERE each concern is acknowledged.

### ai-gateway gate-1 — backbone + activation (2026-06-23, session 2)

Phase B2 stood up: CHARTER + 3 brownfield load-bearing specs (billing-integrity / provider-egress /
access-control, derived from `app/main.py` code→rules) + graph + first task corpus, all activated.

- **Brownfield specs must be TRUE on day 1 — audit-pre RED otherwise ( finding).** The first draft
  activated specs that asserted an IDEAL rule (e.g. "unknown-model pricing fallback is SURFACED") the code
  did not yet meet → the external auditor RED-flagged "active specs false on day 1". → generalised: a
  brownfield backbone spec DESCRIBES what the code ALREADY enforces (cite the symbols); any GAP between
  ideal and current is filed as a SEPARATE improvement task and noted in the spec body, never baked into
  the active rule. (Here: the unknown-model `DEFAULT_PRICING` mis-bill gap → ai-gateway task.)
- **Registry `methodology:` field is a migration-completion step — easily missed.** ai-gateway finished
  gate-1 but `/start` still grouped it under Legacy because its `registry.yaml` entry had no
  `methodology:` field (defaults to legacy). → generalised into §B2 above.
- **Carved consumer `<vendor-adapter>.md` keeps the OLD pre-carve path.** ai-gateway's `<vendor-adapter>.md` still says
  "Working directory: <host-home>/services/ai-gateway/" (the pre-carve path). → fix it in the CONSUMER repo
  during B2/B3 (it is the consumer's own file). Captured `carved-…-the AI provider-md-points-at-old-services-path`.
- **Consumer authoring needs a fresh session anchor in each new worktree (read-gate friction).** After
  `-C <consumer> worktree new` (or `worktree adopt`), `task file` / `task commit` REFUSE fail-closed ("no
  session_started anchor for this session in this checkout") until you run `-C <new-worktree> session
  start` once. The gate is UNEVEN — `spec new` did NOT refuse, `task file` DID. → generalised: open every
  new consumer authoring worktree with a `-C <wt> session start` before the first filing/commit verb.
  Captured `consumer-worktree-new-then-task-file-needs-session-anchor` + (adopt sibling)
  `adopt-orphan-then-commit-needs-fresh-session-anchor`.
- **An activated consumer spec needs a `binding:` token BEFORE land — else land conformance ABORTs.** A
  spec that reaches `active` (via its activation_owner_task close) with no `binding:` token is flagged
  dangling, and the land `graph conformance` check ABORTs far from the cause. For an implements-bearing
  descriptive spec the right token is `code-enforced` (`spec edit <SPEC> --old "binding: []" --new
  "binding: [code-enforced]"`). → generalised: set each activated spec's `binding:` (residency token for
  a code-rule spec = `code-enforced`) in the same worktree before `land`.
- **Consumer-side commit `from:` must be consumer-resolvable (audit lens gap).** An external audit-post
  flagged a consumer bootstrap commit's `from:` (an AGENTS handbook-section grounding) as "non-canonical"
  and suggested a `tasks/T-XXXX` path — but a kernel-task path DANGLES in the consumer repo. A
  handbook-section / kernel-SPEC `from:` is the consumer-correct grounding. Captured
  `audit-lens-consumer-side-from-grounding-false-positive`.
- **`-C session start` echo is not consumer-aware enough — own backbone not front-loaded + wrong verb form
  (→ kernel task).** Journal check across three startups (kernel / kupiclub / ai-gateway): a
  consumer DOES read the full kernel handbook (CHARTER→AGENTS→LIFECYCLE→QUEUE→GRAPH, all 5) AND its own
  specs (~1/session) — the methodology lands. But the echo (a) only says "your own CHARTER.md, **if any**"
  generically — it never NAMES the consumer's CHARTER or surfaces its active specs (they are
  `code-enforced`, read on-demand, never front-loaded); and (b) prints "rescan CLI surface:
  `bin/yitc-v2 --help`", but a consumer has NO local `bin/yitc-v2` — the form a session needs is
  `<engine>/bin/yitc-v2 -C <consumer-path> <verb>`, which the echo never shows ("verbs hard to recognise").
  **Why kupiclub felt fine and ai-gateway did not:** the SAME echo gap hits both, but kupiclub's `MEMORY.md`
  was hand-polished (names it a "YITC-v2 consumer" + shows the full `-C` verb form in its header), whereas
  ai-gateway got the `-C init` BORN template, whose own example uses the broken bare `bin/yitc-v2 graph
  query …`. → fix homed in **** (echo names the consumer CHARTER + surfaces specs + shows the `-C`
  verb form; fix the born-`MEMORY.md` template to the kupiclub-style `-C` form). Prior-art model:
  kupiclub's `MEMORY.md`.

### ai-gateway gate-1 — two-gate proof convergence (2026-06-24, session 3)

Phase B3 closed: the two-gate proof ( gate-1 smoke FIT gate-2 representative
completion) was CONVERGED on a single real task, and the migration retro (this card) ran.

- **A gate-proof card is an adoption-RECORDING card, not a re-run.** The owner decided ai-gateway
   — ONE real billing-core task (unknown-model mis-bill, the HARD part of adoption), run
  through all 9 stages and landed in ai-gateway main (`5bd8662`/`822eedc`) — counts as BOTH gate-1
  smoke (FIT) AND gate-2 representative (completion). So the kernel gate cards / do NOT
  re-run any work: each **records** the proof. Their ship is a `live_trigger_evidence` event
  (cross-repo adoption), **no yitc-v2 code diff** — the same adoption-ship shape as /.
  → generalised: *a migration gate is proven by a real in-project task; the kernel gate card is a
  recording wrapper (probe = the task's done+landed state; ship = `live_trigger_evidence`;
  `--prop-follow-up` carries the forward work).*
- **Two repos, two landings — never conflate them.** The real proof task lands in the CONSUMER's main
  (ai-gateway); the kernel gate card lands only its own proof-RECORD in the ENGINE's main (yitc-v2).
  "Both gates landed in ai-gateway main" means the EVIDENCE TASK is in ai-gateway main, not that the
  kernel cards land there.
- **Routine audit-pre RED-flags a recording card (category mismatch) — captured
  `deviation_captured` `audit-pre-category-mismatch-on-gate-proof-recording-card`.** The external
  auditor read literal card scope ("run a task through 9 stages in ai-gateway") WITHOUT the
  owner-decision context that already satisfies the gate, and conflated the two repos (flagged
  "you land in yitc-v2, not ai-gateway"). First pass RED; after the plan stated the owner decision +
  the two-repo split EXPLICITLY up front, the re-audit went YELLOW. → generalised: *a gate-proof
  recording card's plan must, in its FIRST lines, name the proof task + its consumer-repo landing +
  the kernel-repo record landing — otherwise the diff-blind routine auditor reads a "no work" card as
  a defect.* (Analogous to the event-emit-only audit-POST category mismatch, but at audit-PRE, where
  no carve-out flag exists — the fix is plan wording, not a flag.)
- **Absorb the residual YELLOWs mode-(b), don't re-plan into the ceiling.** Both gate cards drew
  minor YELLOW residuals (propagation target; spec-coverage file naming). Each was absorbed in the
  EXISTING audit-pre verdict YAML (no plan re-edit → no re-fingerprint → no forced re-audit), keeping
  the 2-pass audit-loop ceiling intact. → generalised: *for a passable residual on a recording card,
  record the absorption in the verdict YAML and proceed; reserve a plan re-edit (which forces a fresh
  audit pass) for a finding that genuinely changes the plan.*

### ai-gateway gate-1 — full B5 revizia ran; dual-track caught the optimistic self-verdict (2026-06-24, session 4)

The FIRST real migration-complete revizia (B5 facet 3) ran end-to-end `-C` against ai-gateway: all 8
themes emitted `inspection_completed` (`run_ref=migration-b5-baseline-2026-06-24`), triage ran 3×
(watermark-continuous), and an explicit `migration_b5_verdict` event was written.

- **The primary in-session track self-assessed OPTIMISTICALLY; the external blind track corrected it.**
  The primary verdict (06:46:56Z) said CONDITIONAL "substantially met, 0 HIGH". The independent
  blind-audit track then found 3 confirmed findings the primary MISSED — **1 HIGH** (a live billing
  under-report: `/api/billing/summary` timestamp-format string-compare) + 2 MED, including a facet-2 miss
  (`app/main.py#health` is load-bearing but ungoverned) — and a corrected **NOT COMPLETE** verdict
  superseded the optimistic one (06:54:34Z), naming its own primary-track blind spots (no billing-SQL
  correctness probe in T6; incomplete route-coverage walk in T1). → **generalised: the migration-complete
  revizia MUST run the dual-track (the in-session author + an independent blind external pass) — the
  author self-grades optimistically on its OWN migration, and a single-track "substantially met" is exactly
  the verdict the blind track most often overturns. A single-track finding is a method gap, not a pass**
  (CHARTER §P4a — auditor independence; the M5 dual-track run-mode is doing its job).
- **A B5 verdict is a GATE, not a closeout — the revizia being "done" ≠ the migration being done.** The
  inspection ran correctly AND honestly returned NOT COMPLETE: it surfaced 6 follow-up tasks (4 B5 blockers
  /0011/0012/0013 + 2 quality /0010), all `ready`, none landed. → generalised: *a clean,
  complete revizia that returns NOT COMPLETE is a SUCCESS of the gate; `plan realized` waits for the named
  `closes_b5_when` task set to LAND and the facet checks to re-pass — never on the revizia's completion
  alone.*
- **The methodology-tooling gap the revizia found routes to the KERNEL, the product gaps to the CONSUMER.**
  The "init silently waives a non-empty legacy `CROSS-TASKS.md`" finding (a MIGRATION-PROCESS gap, not an
  ai-gateway product bug) was routed via the cross-log as **X-0083** → kernel task ****; the
  product/coverage gaps became ai-gateway's OWN `-C` tasks. → reaffirms the §B5 assessor≠fixer
  discriminator (SPEC-0084 §5): a read-only operator's finding routes by REALM — kernel-craft to the
  kernel cross-log, consumer-product to the consumer queue — never a direct cross-repo write.
- **Several B5 findings were COVERAGE GAPS the BACKBONE stage (B2) should have caught — the revizia is
  currently the safety net for incomplete B2 scoping.** The ungoverned billing-READ API
  (`/api/billing/summary` + `/api/billing/calls`, named in the ai-gateway CHARTER) and the `/health` route
  are **load-bearing surfaces that EXISTED at migration time** — by the §B5 own rule ("'grow on incident'
  governs genuinely-NEW surfaces, NOT load-bearing surfaces that ALREADY exist at migration time"), they
  belonged in the B2 backbone, not deferred to B5 discovery. B2 stood up specs for the WRITE/proxy path
  only and skipped the read path; the CHARTER's load-bearing list was never reconciled with the authored
  spec set (→). → **generalised: B2 must run an EXPLICIT load-bearing-surface enumeration up front —
  walk EVERY charter-named contract + every app entrypoint/route/symbol → spec-or-conscious-waive — so the
  B5 revizia CONFIRMS completeness rather than DISCOVERING it.** When B5 is finding load-bearing coverage
  holes (not just polish), B2 under-scoped. (This sharpens §B2 + §B5 facet-2: the coverage walk is a
  backbone-time step, with B5 the independent re-check — not the first time the surfaces are counted.)

### social-scraper gate-1.5 (legacy brownfield, the 2nd instance) — 2026-06-24

The 2nd brownfield migration (umbrella PART-4: socialscraper → trendfinder → boomrocket). A SECOND
legacy instance generalizing the runbook beyond ai-gateway. B0–B2-foundation ran this session
(plan filed; `master→main`; `-C init`; import-completeness gate; CHARTER + load-bearing-surface map).

- **B0 cost is a SPECTRUM — here it was ~zero (the opposite end from ai-gateway).** social-scraper was
  ALREADY its own git repo at the projects home (`git rev-parse --show-toplevel` = the dir itself), and
  host automation (`offsite-backup.sh` ×2, `session-scope-guard.sh`, `verify-backup.sh`,
  `collect-infra.sh`) ALREADY pointed at its `<host-home>/projects/social-scraper` path — so the entire
  gate-1 B0 carve + cutover + backup-repoint (ai-gateway's single biggest cost) was a NO-OP. → generalised:
  **B0 still RUNS its preflight (confirm toplevel + grep host path-coupling + check the live deploy), but a
  project already standalone at the projects home with host automation already pointing there skips the
  carve/cutover/repoint entirely.** The preflight is mandatory; the carve is conditional on where the repo sits.
- **A stale non-main default branch (`master`) is a real B0 step for older repos.** social-scraper's only
  branch was `master`; `-C init` + the migration contract assume `main`. `git branch -m master main` (no
  remote → trivial; the live docker deploy keys off the container, not the branch name) is the
  normalization, done at B0 BEFORE `-C init`. → generalised into a B0 sub-step: **a brownfield repo
  predating the `main` default needs the `master→main` rename at B0** (the runbook §B0 / the init
  note already names «retire a stale non-main default branch» as its own concern — this is when it fires).
- **A THIRD legacy sub-shape: "light ai_team" (`ai_team.enabled` WITHOUT `team_mode`).** Between
  pure-legacy (ai-gateway: just <vendor-adapter>.md + CROSS-TASKS.md, no ai_team) and v1-incumbent (full Team-Mode,
  trendfinder/boomrocket). social-scraper's registry had `team_mode: false` BUT `ai_team: {enabled: true,
  roles: [code-auditor]}` + NO `methodology:` — and the legacy v1 hooks were ACTIVELY writing `.yitc/`
  (awareness-ledger, `audit-pre-impl`, pipeline/cd-guard invocations) at migration time. It is still
  classified **legacy** (no BACKLOG-as-governance / DECISIONS / roles dir / ai_team pipeline) — NOT the
  v1-incumbent surface — and the light hooks retire cleanly: `-C init`'s `.no-v1-hooks` marker stops them +
  `.yitc/` is gitignored; the registry `methodology: yitc_v2` flip + dropping the `ai_team` block is the
  host-side completion. → generalised: **the legacy↔v1-incumbent split has a middle "light ai_team"
  sub-shape — classify it legacy (common mechanics), add only a small hook-retirement step at init, NOT the
  full v1-governance migration.**
- **`-C land` targeting + a dirty consumer main blocked the land (captured `deviation_captured`
  `consumer-land-blocked-by-host-lock-and-manual-graph-build-on-main`).** Two distinct snags landing the
  CHARTER batch: (a) a bare `land` run from INSIDE the consumer worktree hit the ENGINE repo ("current
  branch is main — nothing to land") — the engine CLI's `land` without `-C` operates on the engine repo,
  not cwd; you MUST `<engine>/bin/yitc-v2 -C <consumer-worktree> land`. (b) `-C land` then ABORTED because
  the consumer MAIN checkout carried untracked dirt: a host `<provider-config>-session-main.lock` cross-contaminating
  the consumer repo root + an untracked `graph/` left by a manual `-C graph build` I ran on main for the
  mandatory-core check. → generalised: **always `-C <worktree> land` (never bare `land` from a consumer
  worktree); gitignore the host `<provider-config>-session-main.lock` at init (consumer churn); and verify the
  consumer graph in a worktree — or accept that a manual `-C graph build` dirties main and clean it before
  land (land rebuilds+commits graph as bookkeeping).**
- **Carried-forward gate-1 lessons that HELD (no new friction):** the consumer-worktree `-C session start`
  anchor before the first filing verb; the consumer-side `from:` grounded in a kernel pattern/handbook
  section (`patterns/onboarding-onto-yitc-runbook.md §B2`), not a dangling kernel-task path; the
  two-surface import-completeness gate (deploy→`yitc-ops`, no-secrets→standing-rule absence,
  behavioral→authoring-time). The brownfield-specs-true-on-day-1 rule is PRE-APPLIED in the CHARTER's
  surface map (the BACKLOG hygiene gaps are filed as separate tasks, never baked into a day-1 spec rule).

- **Brownfield spec ACTIVATION — per-spec adoption tasks, NOT a bulk flip, NOT work-first-deferred
  (external consult 2026-06-24, `decisions/spec-activation-timing-brownfield-migration-audit-adhoc.yaml`,
  YELLOW).** The backbone authored 5 load-bearing specs as `proposed`; the question was HOW/WHEN they reach
  `active`. The owner questioned doing the "primary activation" from the kernel migration session at all.
  The external auditor settled it:
  - **Work-first deferral is WRONG** (leave them `proposed` until some future feature task happens to touch
    each surface): a load-bearing surface no task ever touches sits non-governing FOREVER, so **B5 facet-2
    ("load-bearing code governed by an ACTIVE spec") can never honestly pass at migration-complete time.**
  - **One omnibus "flip all N" task is too coarse**: it weakens the adoption probe and can **hide a false /
    under-checked spec behind one umbrella closure** (the very risk the brownfield-true-on-day-1 rule guards).
  - **The right shape = one LIGHTWEIGHT brownfield-adoption task PER SPEC (or per tightly-coherent surface
    cluster), DURING the migration**, whose REAL work is **fidelity-verification of code↔spec** (does the
    spec faithfully describe what the code enforces?) and whose **close activates** that spec; probe =
    `implements` anchors resolve + the existing tests cover the surface. So `proposed→active` rides a real
    adoption act, exactly as the v2 `activation_owner_task` model intends — not a synthetic status event.
  - **Session placement (owner Q, 2026-06-24):** these adoption tasks are the **PROJECT's own `-C` work**
    and are best run **from the project's OWN launched session** (a clean consumer `session start` that
    reads its own CHARTER + the proposed specs IS the first adoption probe — "done = adopted" — and keeps
    the migration-OPERATOR role distinct from the project's own work). The migration operator delivers the
    `proposed` backbone + graph + queue; the project session brings it to `active`. The `-C` write-posture
    is identical either way (SPEC-0084 §5), so this is a cleanliness/validation preference, not a
    territory rule. → generalises §B2/§B5: author load-bearing specs `proposed` at B2; activate them via
    per-spec fidelity-adoption tasks during migration (gate-1 ai-gateway's bulk-in-B2 activation is
    superseded by this per-spec shape).

### social-scraper gate-1.5 — post-migration meta-analysis: init/process gaps (2026-06-24, session 2)

A distillation pass over the FULL gate-1.5 migration (after the backbone landed and the dispatch+watcher
ran the backlog as parallel workers) surfaced 8 init/process findings. Each is GENERAL migration craft →
graduated here (the traveling `patterns/` home, SPEC-0090 realm-routing); each was routed to a kernel
fix or host action (truth = the cross log + `task list`, not this prose). **What WORKED first:** per-spec
fidelity-adoption (above) caught 2 real spec↔code inaccuracies; once `.gitattributes events.jsonl
merge=union` was seeded, `dispatch` + watcher ran the spec-activation backlog as concurrent workers.

- **`-C init` born-waived verify despite an existing test suite (X-0085 →, DONE).** init now
  DETECTS a brownfield test suite and seeds a verify contract instead of a silent born-waiver. →
  generalised: **init must not born-waive a gate a brownfield repo already has the substance for** —
  detect-then-seed, never silent-default.
- **`-C init` didn't seed `.gitattributes events.jsonl merge=union` (X-0086 →, DONE).** Without
  the union-merge attribute, concurrent workers' journal appends conflict on land. Now seeded at init.
  → generalised: **the concurrency primitives a consumer needs to run parallel workers (union-merge on
  the journal) are part of the born backbone, not a thing the operator hand-adds after the first collision.**
- **SPEC-0094 `live_probe` fires on EVERY task of a deploying project, incl. no-runtime-surface ones
  (gap 3 →).** 5 spec-activation tasks each needed a HAND `live_probe` waiver — pure friction,
  and a hand-waiver habit erodes the gate. → wanted: **a class/shape DEFAULT that auto-waives the live
  probe for a no-runtime-surface change** (the probe still fires for a real runtime-touching change).
- **No hermetic test harness is seeded/prompted for a brownfield repo WITH tests (gap 4 →).**
  Had to hand-build `docker-compose.test.yml` + a concurrency-safe `verify.sh`. → wanted: **init B2/B5
  PROMPTS for a hermetic + concurrency-safe verify command** when a test suite is detected (pairs with
  X-0085's detect leg) — concurrency-safe because dispatch runs workers in parallel.
- **Per-worktree session-anchor friction (gap 5 → folded into this runbook).** Every new consumer
  worktree needs its own `-C <wt> session start` anchor before the first filing verb (the engine echo
  is per-checkout, not inherited from the main checkout). → **clarity line: treat the `-C <worktree>
  session start` anchor as a per-worktree step, once per worktree, like the worktree creation itself —
  not a once-per-migration step** (re-stated here because the gate-1 §Frictions #4 named it as ergonomics,
  not as a standing per-worktree action).
- **Deploy-AUTONOMY (SPEC-0097) is NOT a conscious import-completeness concern → silent born-waiver
  (X-0088 →).** The import-completeness gate covers deploy (SPEC-0094) / no-secrets / behavioral
  — but NOT the deploy-autonomy DECISION, so init defaults it to a waiver the owner never sees on-plan.
  → fix: **add SPEC-0097 as a 4th CONSCIOUS declare-or-waive concern** so the owner DECIDES on-plan; init
  must NOT auto-seed an active autonomy policy (that would silently GRANT autonomy — unsafe). The fix
  surfaces the DECISION, not the policy. → generalises the §B2 two-surface declare-or-waive to FOUR concerns.
- **A mis-classified triggered mechanism escapes Principle 8 (X-0089 →).** A periodic celery-beat
  cache-GC was filed `class:feature` not `class:infra`; SPEC-0036's adoption-honesty lens scopes the
  live-trigger-evidence demand to `class:infra` ONLY, so the mis-label bypassed it — its probe was a
  direct-call unit test (proves the code, not that the mechanism FIRES), audit-post went GREEN, and no
  celery-beat runner exists in prod so the GC never runs. → fix: **broaden the SPEC-0036 audit-post
  adoption lens** from "for class:infra check live-trigger" to "for ANY shipped mechanism that fires on a
  trigger (schedule/hook/event/periodic) demand live-trigger or synthetic-load evidence, not a unit test"
  (a prompt sharpening — the independent audit catches the mis-classification) + a SPEC-0060 task-authoring
  cue (triggered mechanism ⇒ class:infra + live-trigger acceptance). No new detector/gate — reuse SPEC-0036/0060.
- **Migration flips `registry.yaml` but not the derived `workspace.yaml` (X-0090 → + host-fixed).**
  registry went `methodology: yitc_v2` but `workspace.yaml` kept social-scraper in `other_projects` as
  `legacy`, so it was EXCLUDED from `yitc check --workspace` / the nightly cycle (a P7 registry↔workspace
  dissonance). Host-fixed now (moved into the active `projects:` list). → **runbook B5 / host-completion
  step: after the methodology flip, regenerate/update `workspace.yaml` so the consumer enters the active
  `projects:` list** (host territory — outside the consumer repo). Generalises beyond this one file:
  **a migration that flips a SOURCE-of-truth field (registry) must reconcile every DERIVED surface
  (workspace.yaml, and audit any other registry-derived file) in the same host-completion pass** — else
  the consumer is "migrated" in one view and "legacy" in another.

### social-scraper gate-1.5 — external retrospective audit conclusions (2026-06-24, YELLOW)

An INDEPENDENT external audit (CHARTER §P4a, different provider) reviewed the gate-1.5 retrospective +
the proposed kernel fixes (`decisions/social-scraper-migration-retro-audit-adhoc.yaml`). It CONFIRMED
the operator/project-session split is sound (operator delivers a `proposed` backbone; the consumer's own
`-C` session does per-spec activation — leaving specs `proposed` at hand-off is acceptable ONLY if the
activation tasks are filed, owned by the consumer session, and B5 cannot pass until they land) and that
.. are anti-complexity-safe **only insofar as they sharpen existing prompts/checklists/lenses,
never add a new gate/detector**. Its 4 blind-spot findings GENERALISE several of the above one-offs into
classes — fold each into the runbook here:

- **(HIGH) The `live_probe` auto-waive MUST key off TOUCHED RUNTIME SURFACES, not a task/spec CLASS or a
  "migration task" label.** A class-based shortcut can silently waive a real deploy-risk change. →
  **runbook §B2/§B3 rule:** the live-probe default is an explicit NON-runtime-surface ALLOWLIST
  (docs / graph / queue / spec-text / task-metadata / kernel-only paperwork); ANY consumer runtime code,
  runtime/deploy config, hook, scheduler, or startup-path change stays explicit declare-or-waive. (Sharpens
   gap-3 — encoded in its child card.)
- **(MED) X-0090 is a CLASS, not a `registry→workspace` one-off:** a migration that flips an authoritative
  registry field without regenerating EVERY derived surface that drives routing/checks/reporting leaves the
  consumer "migrated" in one view and "legacy" in another. → **runbook §B2 host-completion step:** after the
  `methodology: yitc_v2` flip, REGENERATE + VERIFY every registry-derived surface — confirm the consumer
  appears in `/start`, `yitc check --workspace`, and any nightly/workspace enumerator that keys off derived
  state. (Broadens.)
- **(MED) Silent born-waiver/default is a PATTERN, not just deploy-autonomy:** fixing only SPEC-0097 leaves
  init/import-completeness still able to default owner-significant concerns without an on-plan declaration.
  → **runbook §Shared core import-completeness step:** add an owner-visible born-waiver/default SWEEP — list
  every concern spec whose init path can default/waive behaviour, and force each to be EITHER explicitly
  declared on-plan OR explicitly born-waived with owner-visible wording. SPEC-0097 is the FIRST concrete
  instance, not the only one. (Filed as its own kernel task; stays the SPEC-0097 instance.)
- **(MED) No migration-level "service stayed live" + rollback evidence packet:** brownfield operators can
  claim zero-runtime-impact without a standard evidence artifact. → **runbook §B0/§B2 checklist bullet:**
  every brownfield migration records a liveness/rollback evidence packet — was runtime touched? what
  health/process/container evidence proved continuity? what rollback path exists if a cutover is involved?
  if no runtime touch, record the proof of NON-touch.
- **(caution, carried into §Meta) Any P8/adoption lens keyed off an AUTHOR-CHOSEN label is likely a CLASS,
  not a one-off:** X-0089 (mis-classified triggered mechanism escapes the class:infra-scoped lens) should
  prompt an audit for OTHER label-keyed adoption checks with an intrinsic-behaviour alternative. The
  SPEC-0036 broadening must stay narrowly scoped to "any shipped mechanism whose SUCCESS DEPENDS ON AN
  EXTERNAL TRIGGER FIRING" (live-trigger / synthetic-load evidence) — NOT a blanket demand on all infra or
  all features. (Narrows.)

## Meta-analysis — gate-1 ai-gateway migration (the first brownfield instance)

> Periodic distillation pass over the accumulated §Frictions log (runbook intro discipline). It
> generalises the gate-1 instance into recurring SHAPES; the raw entries stay above.

**The recurring shapes (what a brownfield migration repeatedly hits):**

1. **Standalone-repo prerequisite dominates B0.** The single biggest gate-1 cost was that `-C`
   resolves to the git TOPLEVEL — a monorepo subdir is not a migratable unit. Preflight the path
   coupling (host automation hardcodes the path), carve a fresh repo (copy source, exclude runtime
   DB + secrets), repoint registry NOW but gate the live-deploy cutover behind an owner window.
2. **The import-completeness gate has TWO surfaces, not one.** The activation-checklist SET (3
   universal concerns) ≠ the `yitc-ops.yaml` carrier (8 sections); only `deploy` overlaps. Each
   concern is acknowledged on its OWN surface (deploy → carrier; no-secrets → standing-rule absence;
   behavioral → authoring-time spec). Reading "3 SET concerns" as "3 carrier sections" is the trap.
3. **Brownfield specs must be TRUE on day 1.** A backbone spec DESCRIBES what the code already
   enforces (cite the symbols); any ideal↔current GAP is a SEPARATE filed task noted in the spec
   body, never baked into the active rule — else audit-pre RED-flags "active spec false on day 1".
4. **Consumer-session ergonomics are the rough edge.** Each new consumer worktree needs a `-C
   <wt> session start` anchor before the first filing verb; an activated consumer spec needs a
   `binding:` token before land; the `-C session start` echo + born-`MEMORY.md` are not yet
   consumer-aware (own CHARTER/specs not front-loaded, wrong verb form) → kernel fix.
5. **The gate proof is a recording, the audit is diff-blind.** A migration gate is proven by a real
   in-project task; the kernel records it (event-emit-only ship). State the owner decision + two-repo
   split explicitly so the routine auditor does not misread the recording card as "no work".
6. **Host-config edits ride the host's own auto-committer.** A migrated project's `registry.yaml` /
   `bin/` script edits land via the `<host-home>` `chore(auto)` committer — never hand-commit the
   monorepo (it carries the owner's other pending changes).
7. **The migration-complete revizia is dual-track, and "substantially met" is a red flag.** The B5
   facet-3 revizia self-grades optimistically on the author's OWN migration; the independent blind track
   is what catches the real gaps (gate-1: a HIGH live-billing bug + a facet-2 ungoverned route the primary
   track scored clean). Run both tracks; treat a single-track pass as a method gap; and remember the
   verdict is a GATE — a clean revizia returning NOT COMPLETE is a success, and `plan realized` waits on the
   named `closes_b5_when` tasks LANDING, not on the revizia finishing.

**Per-deviation routing roll-call (SPEC-0090 realm-routing — AC2, no friction dropped).** EVERY
gate-1 migration deviation is GENERAL onboarding/kernel craft — about the MIGRATION
PROCESS, not ai-gateway product specifics — so each is graduated INTO this traveling runbook
(`patterns/`, the GENERAL home): the B0 carve/path-coupling/runtime-DB frictions; the deploy-cutover
wrong-cwd + minimise-downtime + carry-the-DB frictions; the two-surface declare-or-waive; the
methodology-field completion step; the brownfield-specs-true-on-day-1 rule; the consumer
session-anchor + spec-`binding:` + `-C` echo ergonomics (→); the consumer-side `from:`
grounding; and the session-3 gate-proof recording-card + audit-pre category-mismatch frictions above.
**NONE is ai-gateway-product-specific craft**, so none is homed in ai-gateway's `lessons/` — and a
yitc-v2 Build session would not write that anyway : a project-specific lesson would route via
a `bin/yitc-v2 cross request` to ai-gateway (SPEC-0086), never a direct cross-repo write. Exactly two
homes; all gate-1 items land in the runbook; zero dropped.
