# Onboarding onto YITC — frictions log & per-migration meta-analysis

> **Split note (per SPEC-0120 §3 per-doc size band).** This file is the accumulated
> **Frictions log** + per-migration meta-analysis, relocated verbatim out of
> `patterns/onboarding-onto-yitc-runbook.md` at the §Frictions-log seam so the runbook proper and its
> live-capture log each load in one bounded read. The RUNBOOK proper (Shared core + Branch A/B +
> the B5 completion gate & checks) stays in the sibling `patterns/onboarding-onto-yitc-runbook.md`.
> Content was RELOCATED, not changed. **Live-capture discipline is unchanged** — append every new
> friction here (newest last), AS it happens (owner directive 2026-06-23); a periodic meta-analysis
> pass distils/generalises over the accumulated log back into the runbook proper.

## Frictions log (append live — newest last)

> One entry per friction/deviation/decision hit during a real onboarding. Small frictions count — they are
> exactly what post-hoc reconstruction loses. Generalise into the branch steps above during the periodic
> meta-analysis pass; keep the raw entry here.

> **Archive pointer.** The EARLY completed gates — **ai-gateway gate-1** and **social-scraper
> gate-1.5**, plus the gate-1 meta-analysis — were relocated VERBATIM to the sibling
> `patterns/onboarding-onto-yitc-frictions-log-archive.md` (per SPEC-0120 §3, to keep each file within one
> bounded read). This live log carries **gate-2 trend-finder onward** and remains the append target for
> future gates.
### trend-finder gate-2 (FIRST full v1-incumbent / Team-Mode) — B2 bootstrap preconditions had two GENERAL gaps (2026-06-26)

The first full v1-incumbent gate-2 surfaced two B0/quiesce preconditions the plan assumed done but reality
had NOT met — both GENERAL to any v1-incumbent (full Team-Mode) brownfield repo, so generalised here for
boomrocket / aiseller (do these UPFRONT, do not discover them mid-bootstrap):

- **`.no-v1-hooks` does NOT disable the consumer's repo-LOCAL git hooks — a v1-incumbent carries BOTH.**
  The `.no-v1-hooks` marker silences the GLOBAL interactive hooks only. A full Team-Mode repo ALSO has
  repo-local `.git/hooks/{pre-commit,commit-msg,post-commit,post-merge,pre-push}`; trend-finder's local
  `pre-commit` (68K, "protect main from direct code commits — allow only management files") REJECTED
  `init`'s sanctioned direct-to-main bootstrap commit AND would reject every v2 `land` commit to main
  (silently — init swallowed the non-zero `git commit`, leaving scaffolds staged-not-committed). →
  **generalised: class-A quiesce on a v1-incumbent MUST ALSO disable the repo-local git hooks** — move
  `.git/hooks/{pre-commit,commit-msg,post-commit,post-merge,pre-push}` aside to `.git/hooks-v1-disabled/`
  (reversible; `.git/` is unversioned; running product untouched — hooks fire only on git ops). Deviation
  `gate2-consumer-repo-local-v1-git-hooks-survive-quiesce-block-init-bootstrap-commit`.

- **A long-lived v1 auto-session leaves `main` STALE behind a dated `auto-session-YYYY-MM-DD` branch.**
  trend-finder's live code (the running containers' build source) sat on `auto-session-2026-04-22`, **186
  commits AHEAD** of a `main` frozen the day that branch was cut — the v1 auto-session committed to the
  dated branch for ~2 months and never merged back, and deploy builds the working tree with no branch rule,
  so the drift stayed INVISIBLE (the project even filed its own "main 175 behind" hygiene task and never
  acted on it). → **generalised: at B0, EXPECT a v1-incumbent's `main` to be stale; the normalization is a
  clean fast-forward of `main` to the live branch HEAD + checkout main (NOT migrating onto the stale main),
  done AFTER a backup — immutable tags for the old-main + live SHAs + an all-refs `git bundle` off-repo.**
  Running containers build from the baked image / working tree (not the branch name), so the ff + checkout
  is zero-impact. Verify the build source FIRST (`docker-compose build:` context, image build date vs
  reflog) so you know which branch is actually live. Deviation
  `gate2-trend-finder-main-186-behind-auto-session-branch-precondition-unmet`.

- **(kernel hardening candidate, deviation captured) `init` is not idempotent-safe to a HALF-completed
  first run.** First `init` staged the scaffolds but the bootstrap `git commit` was rejected (by the
  not-yet-disabled local hook) and init SILENTLY swallowed it; the RE-run then no-op'd ("already
  initialized") on file-PRESENCE — leaving the staged bootstrap permanently uncommitted (init cannot
  self-heal). Worked around by committing the verified-init-managed-only staged index by hand once hooks
  were off. Deviation `gate2-init-not-idempotent-safe-half-completed-bootstrap-commit-swallowed` → init
  should detect staged-but-uncommitted scaffolds / a missing bootstrap commit, and never swallow a failed
  bootstrap commit.

### trend-finder gate-2 — host-completion + deploy re-home (2026-06-26, session 2)

Findings GENERAL to any v1-incumbent gate-2 (do these knowingly; several supersede earlier gate-1/1.5 prose):

- **`workspace.yaml` is a V1 surface — see the CORRECTED §B2 host-completion prose above.** A migrated
  v2 consumer is REMOVED from `workspace.yaml projects:`, never added; v2 consumers are enumerated by the v2
  nightly from `registry.yaml`. The methodology flip ALONE excludes the consumer from all 3 v1 enumerators, so
  the `active: false` quiesce is then redundant. Deviation `workspace-yaml-stale-vs-generator-unrelated-drift`.

- **DEPLOY re-home onto the v2 contract (SPEC-0094) — name the existing `deploy.sh`, but mind these :**
  - The celery-rebuild coupling (`EXTRA_REBUILD`) must be ASSERTED, not just preserved. Put the assert in
    `bin/smoke-test.sh` — the v1 production gate (`check-production-gate.sh:125`) AUTO-runs it as a BLOCKING
    check → a non-zero exit reaches the deploy-common auto-rollback (chain: check-production-gate → `fail`
    /exit 1 → deploy-common `deploy_rollback`). NOT `POST_DEPLOY_HOOK` (it is non-blocking).
  - **`bin/smoke-test.sh` MUST be `chmod +x`** or the gate SILENTLY skips it ("No smoke test found").
  - **Do NOT assert image-ID equality across services:** `docker compose` tags backend / celery-worker /
    celery-beat as SEPARATE per-service images with DIFFERENT ids (verified live) — id-equality false-fails
    every deploy. Assert a SHARED RELEASE SIGNAL instead — best a release-label/version propagated into all
    three (a `.Created` build-timestamp proximity is a brittle proxy — external consult). Deviation
    `smoke-test-image-id-equality-wrong-use-created-timestamp`.
  - **VERIFY-BUILD before trusting a deploy gate:** dry-run the assert against the LIVE running containers
    BEFORE the deploy — it caught the image-id bug here.
  - **The v2 deploy path INHERITS the v1 PRE-deploy release gate.** `deploy.sh`'s `PRE_DEPLOY_GATE` runs
    `check-release-gate.sh`, which blocks on v1 Build Gate + DECISIONS blockers (retired v1-governance) AND
    REAL security findings. A migrated project's deploy must SHED the v1-governance pre-gate while KEEPING a
    real security gate — do NOT `--bypass-gates` (it bypasses real security). Discovered when the
    validation deploy was blocked. Deviation `v2-deploy-inherits-v1-release-gate-blocks-validation-deploy`;
    tracked by (deploy-path fix) (the 2 real critical security findings decision).
  - `rollback:` — a v1-incumbent often has NO standalone rollback script (only deploy-common's auto-rollback
    on a gate FAILURE; the prev-image tags are cleaned up post-success). Declare a reasoned waiver + file a
    real-rollback-command followup.
  - Keep `policy:` OWNER-GATED (do NOT opt into autonomous deploys without an owner decision, SPEC-0097).
    `live_probe` = a simple liveness GET (e.g. `/api/health`); the deeper "is it actually working" (scheduled-
    scan freshness) is a SEPARATE concern, NOT the deploy-contract liveness probe.

- **Dual-repo mechanics (gate-2):** the engine card record (analysis/plan/audits/closure) lands in the ENGINE
  worktree; the CONSUMER artifacts (`yitc-ops.yaml`, `bin/smoke-test.sh`) ride a `-C <consumer> worktree new
  --work … → work commit → -C land`. The actual deploy is OWNER-GATED (SPEC-0097), at the deploy seam.

- **A contract-only change whose acceptance is a live-trigger deploy probe stays OPEN if the deploy is blocked
  by unrelated pre-existing issues** — park it explicitly ("contract authored + audited; live adoption blocked
  pending X"), never informally waive Done=Adopted (external consult confirmed). is parked this way.

### trend-finder gate-2 — archive the v1 Team-Mode governance corpus (2026-06-26, session 3)

Findings GENERAL to any v1-incumbent gate-2 corpus-archive (the v1 Team-Mode governance corpus retirement step):

- **The v1 Team-Mode corpus = a fixed 8-surface set — `git mv` it to `v1-archive/` (history kept, not deleted):**
  `BACKLOG.md` / `DECISIONS.md` / `DEFERRED.md` / `PROJECT_STATUS.md` / `MEMORY.md` / `CROSS-TASKS.md` /
  `team-mode/` / the v1 `<vendor-adapter>.md`. add-before-remove: only AFTER the v2 backbone is live (its own
  `CHARTER.md` + `specs/` + `graph/` + `yitc-ops.yaml`) — verify that first.
- **Keep the archive card PURE — it is ONE accept-unit (the `git mv`).** Do NOT bundle a `CHARTER.md` edit
  or a `-C init` re-seed into it — both got flagged as scope-creep by audit-pre (twice) + audit-post. A
  governance edit or a buffer re-seed is a SEPARATE concern; bundling them turns a mechanical archive into a
  multi-claim governance change.
- **v1 `<vendor-adapter>.md` mixes Team-Mode routing with a few project-safety lines** (e.g. "no DNS/nginx change w/o
  confirm", "no delete w/o confirm", "commit before big edit"). The instinct to preserve them into
  `CHARTER.md` is WRONG by default — they are already covered: "edit only inside the repo" + an out-of-repo
  DNS/nginx config edit = kernel territory-guard (DNS/nginx configs live OUTSIDE the repo, so already
  blocked); "no delete / commit-first" = the global `<host-home>/<vendor-adapter>.md` owner-prefs + the worktree→land
  discipline. So archiving `<vendor-adapter>.md` WHOLE loses no LIVE safety. Only migrate a line if it is genuinely
  uncovered (none were here).
- **`CROSS-TASKS.md` is doubly-obsolete** — it is a v1 Team-Mode file AND the per-repo `CROSS-TASKS.md` TYPE
  was tombstoned at the cutover (SPEC-0079 superseded; cross-coordination moved to the kernel shared
  log). Never re-seed a live one. (`MEMORY.md`'s born-empty v2 re-seed, if wanted, is `-C init`'s job, NOT
  the archive card's.)
- **Prove the archive NON-LIVE to tooling, not just relocated (the real probe, audit-post-hardened):** after
  the `git mv`, run `-C graph build` and confirm `v1-archive/` has **0 index references** (build `errors=0`).
  It is naturally ignored because `graph build` indexes by KNOWN node-dirs (`specs/`/`scenarios/`/`lessons/`/
  …), not arbitrary top-level `.md` — so a top-level `v1-archive/` is non-live by construction. This
  graph-build-clean result IS the infra P8 live-trigger adoption evidence for closing the card.
- **Repo-name vs product-name alias trips the external auditor:** trend-finder's repo DIR is
  `social-parser` but its PRODUCT (and `CHARTER.md` title) is "Trend-Finder". audit-pre HIGH-flagged "plan
  points at a different repo" purely from this. State the alias in the plan + verify the `-C` checkout root
  (toplevel + CHARTER title) before the worktree.

### trend-finder gate-2 — B3 two-gate proof, a real consumer task through 9 stages (consumer) (2026-06-26, session 4)

Findings GENERAL to running the §B3 two-gate proof on any v1-incumbent gate-2 (the proof = a kernel
RECORDING card whose ship is cross-repo adoption evidence; the REAL 9-stage run happens in the consumer):

- **The recording card runs the FULL substantive flow WITH both external audits — do NOT assume "adoption-ship = no audit" from an empty `decisions/`.** The audit YAMLs are MOVED OUT at closure (`audit_yamls_archived` → `decisions/archive/`), so an absent `decisions/T-XXXX-audit-*.yaml` is NOT proof the card skipped audits. Confirm prior-art from the JOURNAL sequence (`bin/yitc-v2 journal query --task T-XXXX` — the segment-aware reader, SPEC-0190 rule 4; a raw grep of the journal path sees the live segment only → see `audit_pre_completed`/`audit_post_completed`), never from a `decisions/` dir listing (a real near-miss this session: the analysis first asserted the wrong thing from the empty dir, caught before audit-pre).
- **One real consumer task converges gate-1 + gate-2** (the gate-1 model; ai-gateway precedent). The representative task can be the consumer's OWN ready queue item — even a low-risk `docs` task (here, authoring the consumer's first `scenarios/`) still exercises the FULL 9-stage lifecycle incl. BOTH external audits in-project. The proof is "lifecycle FIT held, no bypass," NOT "a hard code change." ASK the owner which task before running (low-risk consumer item vs a real product fix).
- **Prove main-membership STRUCTURALLY at closure, not by free-text alone** (an audit-pre finding to absorb): after `-C land`, assert `git -C <repo> branch --contains <ship-sha>` shows `main` + the task `status:done` on main + the artifact present on main; embed `{sha, branch:main}` in the `live_trigger_evidence` data, and rest the close `--probe` on that structured record.
- **A born-empty consumer `land` verify is WAIVED** — `bin/yitc-v2 init` seeds a `yitc-ops.yaml` whose `verify:` section is born section-WAIVED (tests may EXIST, e.g. `backend/tests/`, but no hermetic command is). So the consumer's first proof does NOT run a real test-suite at `land`; the acceptance PROBE you choose (here `-C graph build` resolving the new nodes) is what actually gets exercised. **Standing residual to FILE: declare a hermetic + concurrency-safe `verify.layers` (each layer a `command:`) in the consumer's `yitc-ops.yaml`** (unique-per-run port/DB — concurrent worker `land`s run it in parallel) before anyone relies on consumer land-verify. (`yitc-verify.yaml` is RETIRED —; `land` runs every declared layer + refuses a legacy file.)
- **`covers:` anchors = verbatim spec `implements:` strings resolve cleanly** (no SPEC-0076 rule-6b dangling-reference hard-error) — a safe way to exercise the `covers` edge in a consumer's FIRST scenarios. When authoring those scenarios, scrub `## Notes` for stray normative words ("never"/"must") — audit-post flags them against the zero-normative boundary (SPEC-0076 rule 2); the rule lives in the cited spec, the scenario only points at it.
- **Commit TYPE ≠ task CLASS:** a proof/recording card is `class: infra`, but `task commit` REJECTS `infra` — the message TYPE must be an allowed git type (use `chore(T-XXXX): …` for a records-only ship).
- **The repo-vs-product alias RECURRED** (audit-pre HIGH-flagged the same way it did) — reinforces the prior entry: put the repo-identity line (`<dir> IS <Product>`, same repo) in the proof card's plan BEFORE audit-pre.

The proof closes §B3 only — it is NOT migration-complete (that is §B5, gated on the v1-incumbent retirements + watchdog-retire).

### trend-finder gate-2 — post-first-task audit surfaced 2 scaffold-drift findings + the harness-deps lesson (2026-06-27, session 5)

Distilled into the procedure as **§B3.1 (post-first-task well-formedness check)** + **§B3.2 (harness stands
up ALL runtime deps)** — this is the raw incident record (P5: the procedure sections are the durable home).

- **Harness-deps (X-0102 → §B3.2):** trend-finder (wire the hermetic verify) was done well, but its
  FIRST verify run failed 5 auth tests because the test compose brought up only postgres — the auth
  rate-limiter needs **redis**. Lesson: the hermetic harness must stand up every runtime dep the suite
  touches (DB + cache/queue), discovered from config/conftest. (Fixed in; redis now in the compose.)
- **Missing managed scaffold (→ §B3.1):** trend-finder had **no `MEMORY.md`** — the v1-corpus archive step
   `git mv`'d the v1 one to `v1-archive/` and no v2 `MEMORY.md` was re-seeded; every other consumer
  had it. Fix = idempotent `-C init` re-seed.
- **Retired surface lingering (→ §B3.1):** older consumers (kupiclub, social-scraper — bootstrapped pre-)
  still carry a now-retired `CROSS-TASKS.md`; current init does NOT seed it (legacy guard only). Cleanup is a
  cross-request to each, not a current-init bug. (The `init` subcommand `--help` description still LISTS
  `CROSS-TASKS.md` among born scaffolds — stale text, separate kernel fix.)
- **Why a post-first-task check earns its place:** the first real task is the first end-to-end exercise of the
  bootstrap; scaffold drift (archive-without-reseed, pre-cutover residue) is invisible until then. Cheap
  read-only pass, catches it at the natural moment.

### trend-finder gate-2 — L3 freshness migration: source design-vs-reality (INTERIM — L3 in flight) — 2026-06-28 (session 6)

The L3 liveness/freshness layer (plan `v2-automation-grow-l2-product-cron-governance-l3-l`, the freshness
half of the trend-finder migration) was decomposed into cards and its prove-leg hit a design-vs-reality
gap. **INTERIM capture (live-capture discipline) — the prove card + the project freshness adapter
(cross X-0107 to social-parser) are STILL IN FLIGHT**; the final distillation is followup
`fu_2169157e34d6`, to drain after lands. Findings already firm:

- **A project's freshness SOURCE may be a LIVE signal, not a static config block (the central gap; deviation
  `l3-freshness-source-registry-block-assumption-vs-live-db-logs-reality`).** SPEC-0110 r2 ORIGINALLY assumed
  trend-finder's freshness thresholds live in a static `registry.yaml pipelines:` block ("the same block the
  v1 watchdog reads"). REALITY (read `<host-home>/bin/watchdog.sh` directly): the v1 watchdog computes freshness
  LIVE — **discovery** = a Postgres query (`accounts.last_scanned_at` vs per-account `scan_interval_hours` + 2h
  grace — the threshold is a DB COLUMN); **tracking** = a celery-worker docker-log heartbeat (`tracking_scan …
  succeeded` within 8h). There is NO static thresholds block. → **generalised: at B2 pre-study, do NOT assume a
  project's liveness/freshness signal is declarative config — INSPECT the real incumbent monitor to find what
  it ACTUALLY reads; a freshness source can be a live DB query / logs, not a file.**
- **The fix (external consult `decisions/-audit-adhoc.yaml`, RED → adopted): generic kernel GRADER +
  project READ-ONLY ADAPTER.** The kernel L3 monitor stays a generic grader; each project supplies a thin
  read-only freshness ADAPTER returning NORMALIZED per-pipeline freshness ({fresh|stale|miss}+age); the kernel
  consumes it through the monitor's already-injectable `_read_pipeline_state` seam — NO project-specific
  SQL/docker in kernel code (P1 + the territory smell the consult flagged). → **generalised: a kernel
  monitor that must read a project's live state reads it via a PROJECT-OWNED read-only adapter behind the
  injectable seam, never project infra embedded in the kernel.** (SPEC-0110 redesigned in, DONE; the
  adapter is cross X-0107 → social-parser; the live prove+schedule is, owner-supervised.)
- **`none`/no-adapter must read as NON-ADOPTED for a retiring-v1 project (consult finding 3).** The kernel
  monitor returns `none` (no coverage) when a project has no declared freshness adapter — so the migration gate
  must treat `none` as NON-ADOPTED for a project slated to retire its v1 watchdog; it must NOT count
  as coverage. → **generalised: the like-for-like coverage proof requires v2 to read the SAME live signals v1
  reads (via the adapter), proven by an induced real-miss catch BEFORE v1 retirement — `none` is not a pass.**
- **Project name ≠ repo path (recon trap).** "trend-finder" is the registry KEY; its repo lives at
  `<host-home>/projects/social-parser` (registry `path:`). A path built from the product name
  (`<host-home>/projects/trend-finder`) does NOT exist. → resolve a project's repo via `registry.yaml path:`,
  never the product name.
- **Tooling deviation: the decomposition-fidelity card-set renderer HIDES parked status
  (`plan-card-set-render-omits-parked-status`; fix filed).** `bin/lib/plan.py#_plan_render_card_set`
  renders cut cards without status/parked/return_trigger, so a correctly-PARKED grow-on-pull pull-card (here
  the L2 card) read as "executable now" to the gate-executing auditor → a false-coverage RED.
  Workaround this session: surface the parked marker in the card's own scope text. → fix homed in.

### trend-finder gate-2 — post- plan-FINALIZATION traps (the `plan realized` close-out) — 2026-06-29

Three GENERAL traps surfaced finalizing a migration plan after (the `plan stage realized` aggregate
`audit post --plan` close-gate). They are about the FINALIZE moment specifically — the suite + the corpus +
the fix-task all interlock there in ways that don't bite during ordinary task work:

- **TRAP (a) — finalize-time time-bomb test (the suite is GREEN before 18:00 UTC, RED after).** A consumer
  suite passed every run during the day, then the SAME unchanged tree went RED at finalize-time in the
  evening: `_probe_trend_candidate_yield` fires on **0 candidates** late in the day (a real-clock-dependent
  assertion — the candidate pool drains as the UTC day advances). A finalize gate that ran the suite at an
  earlier hour would have shipped a tree that is red at the real finalize moment. → **generalised: a plan's
  finalize close-gate must RUN THE CONSUMER SUITE AT THE REAL FINALIZE-TIME, never trust an earlier-in-the-day
  green; a wall-clock-dependent assertion is a finalize-time time-bomb — hunt and de-time-bomb such tests, or
  the green you finalized on is stale by the hour you land.**
- **TRAP (b) — red-suite chicken-and-egg (a red consumer suite blocks the land that would FILE the fix).** Once
  the consumer suite is RED, EVERY consumer `land` aborts on the failing verify — INCLUDING the land that would
  file/carry the fix-task for that very failure. You cannot "file the fix first, fix it next land": there is no
  green land to file it on. → **generalised: when a red consumer suite blocks all lands, the fix must RIDE THE
  SAME LAND THAT CONTAINS IT — the corrected test and its task filing land together in one worktree, because no
  prior green land exists to file the fix separately (the red-suite chicken-and-egg).**
- **TRAP (c) — corpus-cite-honesty before `plan realized` (dead tasks still citing the plan force an aggregate
  RED).** The aggregate `audit post --plan` corpus = every task that `cite`s the plan. A **wont-do / parked /
  deferred** task that STILL cites the plan is counted as corpus — so its un-realized state makes the aggregate
  finalization audit go RED even though the live work is complete. The cure is structural, not prose: **cut the
  `cite` edge** from the dead task (and document why in its body), shrinking the corpus to the genuinely-realized
  set; then the changed corpus earns a **freshness re-audit that re-pins the verdict CEILING-EXEMPT** (the
  `corpus_signature` axis — SPEC-0124 §Audit-loop ceiling). → **generalised: before `plan stage realized`, run
  corpus-cite-honesty — STRUCTURALLY cut the plan-cite from any wont-do/parked/deferred task and document the
  cut; do NOT leave a dead task citing the plan, or the aggregate audit RED-blocks finalize. The freshness
  re-audit over the shrunk corpus is ceiling-exempt, so the cut costs nothing against the audit-loop ceiling.**

### boomrocket gate-3 (v1-incumbent heavy) — live v1 writers dirty consumer main + block every land (2026-06-30)

During the F2 content-import wave (5 background workers dispatched in parallel), **2 of 5 died-but-unlanded
on the SAME blocker**: the boomrocket `main` checkout carried foreign UNCOMMITTED churn, so `land` correctly
refused the fast-forward (`LAND: ABORT … uncommitted non-bookkeeping changes`). Root cause: live v1 background
writers still AUTO-WRITING into the very files being migrated — the `boomrocket-health` cron
(`health_check.py --notify`) appends `SF-*` entries to `BACKLOG.md` daily, and scenarium ticket-processing
left untracked yamls under `docs/scenarios/tickets/updates/processed/`.

- **Why it was missed (the reason to NOT repeat next project):** F1c retired the NAMED scenarium sync apparatus
  (the obvious `scenarium-sync.timer` + crons) but `health_check.py` is a SEPARATE product-health cron that
  ALSO auto-writes `BACKLOG.md` — it was never on the mental "sync apparatus" list. The plan enumerated the
  things that *call themselves* sync, not every writer of the migrated files.
- **Controller recovery this session:** committed the benign auto-churn to clear the tree, hand-landed each
  dead worker's already-committed content + engine closure. Non-trivial cost; avoidable up-front.
- → **generalised: BEFORE the B2 content-import (see §B2 precondition), enumerate ALL live writers into every
  to-be-migrated path — `grep` crontab + `systemctl list-timers` + app daemons for the target file paths — and
  quiesce/redirect EACH, not just the named sync timers. A migrated file is a RETIRED file: anything still
  auto-writing it is in scope.** Durable home: the F2d-equivalent "retire v1 governance carriers" card now
  scopes this quiesce step (boomrocket). Deviation fingerprint `boomrocket-consumer-main-dirty-blocks-land`.

### boomrocket gate-3 — B5 dual-track revizia: the migration left the project's OWN surface on v1 (2026-06-30, session 2)

The full dual-track T1–T8 B5 revizia (primary = 4 parallel read-only theme agents; external = an independent
blind <external-auditor> pass over a neutral state digest) returned **NOT-COMPLETE** — but the gap was NOT the corpus.
The corpus/lifecycle/adoption were SOLID: 39 specs / 14 scenarios / `errors=0`, a real v2 ship +
production pipelines (D-078 / SCN-012), F4 coverage-admission with no orphans, the 782-green backend suite,
queue + meta-loop healthy (T3/T4/T5/T8 all CLEAN). The residue was the project's OWN surface — and the SAME
classes the prior two B5s hit:
- **ops-contract born-waivers never wired** — deploy/verify/ui/tests/host_config all still init placeholders
  on a LIVE app. Fixed in-session (B1: declared the real values; the genuinely-hard parts —
  hermetic-verify + deploy-off-v1 — tracked as /, the declare-vs-track fork).
- **<vendor-adapter>.md still v1** — a "Team Mode" methodology-source table pointing the AI at `ai-team-framework/core/*.md`
  (a HIGH instruction-fidelity defect; the external blind pass rated it HIGHER than the primary, as the §B5
  blind-spot note predicts). Fixed.
- **partial v1-carrier retirement** — CROSS-TASKS.md a live 1405-line v1 log left unmarked + stale `drafts/` +
  deploy.sh on the v1 deploy-common.sh (routed).
- **dual-track agreement was strong** on the 3 core residue items; the blind track caught residue the primary
  rated more leniently — reaffirming the dual-track blind pass earns its cost on every `-C` migration-complete.
- → **generalised into §B2 "Transform the project's OWN surface too"** (ops-contract wiring + <vendor-adapter>.md off v1
  + exhaustive v1-carrier retirement) so the NEXT migration wires these UPFRONT and B5 confirms, not discovers.
- Also surfaced a KERNEL bug (not a runbook item, captured as a deviation): `init --adopt-extension SPEC-XXXX`
  appends to `extensions.adopts` but leaves the born forward-aware `waives` entry for the SAME spec — a
  contradictory adopts+waives state the caller must hand-fix. Fingerprint
  `init-adopt-extension-leaves-contradictory-adopts-and-waives-same-spec`.

### boomrocket gate-3 — two migration-completion aids generalised INTO the B5 gate (2026-07-02)

The boomrocket migration surfaced two recurring migration-completion gaps that the runbook did not yet
name (routed kernel-side as `X-0151`, resolved by):
- **Cross-interaction slips per-worktree verify.** The F-wave shipped **19 parallel fixes across
  payment / tickets / buyback**; two added Alembic migrations off the same parent → **divergent heads**. Every
  per-worktree hermetic verify was green — the conflict surfaced only at **deploy pre-flight**. Per-task
  isolation cannot see a jointly-inconsistent batch. Fingerprint `parallel-dispatch-diverges-alembic-heads`.
- **A v1→v2 leftover-tail keeps re-appearing** and got hand-cleaned all day: BACKLOG-import task stubs still
  pointing at `BACKLOG.md`, a stale registry `ai_team.enabled`, a retired per-repo `CROSS-TASKS.md` lacking a
  tombstone, and a v2-native deploy path that dropped its migration step.
- → **generalised into the two B5 sub-checks above** (§B5-check-1 post-parallel-batch cross-interaction
  review + §B5-check-2 the 4-class migration-completion checklist), both framed as PRE-`plan realized`
  safeguards so the next migration confirms them at the gate instead of re-discovering them at deploy.

### aiseller gate-4 (v1-incumbent heavy — the FIRST MULTI-USER migration) — migration day (2026-07-12)

> The fifth brownfield instance and the first with a **second human collaborator** (`<collaborator>`) who owns his
> own server user, his own `~/<provider-config>` surfaces, and his own crontab. Everything below is a deviation
> captured LIVE on migration day (fingerprints are the real journal ones — grep either journal:
> `bin/yitc-v2 journal query --type deviation_captured` in the kernel AND `bin/yitc-v2 -C <aiseller> journal query --type deviation_captured` in the consumer repo).

**A. The multi-user axis — every per-user surface is a per-user COPY, and copies rot silently.** None of
this is visible from the owner's own session; all of it was found only by running **AS the user**
(`sudo -u <collaborator> …`, the mandatory drill from `patterns/onboarding-a-person-onto-yitc.md`):
- **`<collaborator>-user-level-entry-skills-stale-no-work-command`** — <collaborator>'s `~/<provider-config>/commands/` held a **stale
  2026-04-14 v1-era `start.md`** (Build/Review session-type picker, team_mode routing, zero mention of
  `yitc_v2` / consumer / `-C`) and **no `work.md` at all** — a headless `/work` as <collaborator> returns literally
  `Unknown command: /work`. The dev-side entry skills were never propagated to his user-level dir, so the
  surfaces the migration cards NAMED are not the ones his session LOADS. (Repaired by.)
- **`<collaborator>-engine-binary-outside-permission-sandbox`** — the engine binary (`<engine>/bin/yitc-v2`) sits
  OUTSIDE <collaborator>'s cwd-scoped permission sandbox, so the one NON-SKIPPABLE consumer step
  (`-C <consumer> session start`) hits a permission-approval gate. Observed live: session start could not
  execute → no read-order echo, no anchors. His `permissions.allow` was **empty**.
- **`<collaborator>-session-loads-own-settings-not-dev-guard-hooks`** (P7 artifact-vs-reality) — the migration brief
  and plan both assert <collaborator>'s flow is permitted by the `slash-command-guard` + `scope-guard` hooks wired in
  `<host-home>/<provider-config>/settings.json`. Those are **dev-user-scope** settings and are **never loaded in a <collaborator>
  session**: that session loads `/home/<collaborator>/<provider-config>/settings.json`, which wires their OWN v1-platform hooks.
  There is no managed-settings layer above them either. → **a claim about "the hooks protect this flow" is
  false unless it names WHICH USER's settings.json wires them.**
- **`` secrets ACL (both actors locked out)** — the secrets move left `.env` unreadable by BOTH
  actors: `<host-home>/secrets` is `drwx------ dev:dev` (<collaborator> cannot traverse) and `aiseller.env` is `0600
  <collaborator>:<collaborator>` (dev cannot read), while `docker-compose.yaml` uses `env_file:.env` in 5 services → the next
  `docker compose up` fails for BOTH. Latent, not an outage (running containers already hold their env).
  **Group membership is not enough when the group over-grants** — the fix is a named-user ACL matrix.
- **`aiseller-health-runbook-docker-compose-unrunnable-as-dev`** — the incumbent ~350-line health protocol
  writes every SQL block as `docker compose exec -T db psql …`, which **fails for an AI session running as
  `dev`** (the `.env` it needs is <collaborator>-owned 0600). A documented ritual that its own stated audience cannot
  execute — a **silent-unrunnable runbook**.

**B. Registry `active:` is overloaded — one field, three readers, no co-design.**
- **`registry-active-false-hides-v2-consumer-from-start-picker`** / **`spec-0130-registry-active-false-collides-with-picker-visibility-semantics`** —
  SPEC-0130 mandates `active: false` at gate-2 quiesce meaning ONLY «the v1 AI-Team stops treating this as
  active». But two OTHER live readers read the SAME field as «the project is alive/visible»: the `/start`
  picker (lists only ACTIVE projects) and `bin/generate-the AI provider-md.sh` (its `local_active == true` test gates
  the project list written into a newly-provisioned collaborator's `<vendor-adapter>.md`). Net effect: the live
  flagship consumer went **INVISIBLE in `/start`** for the owner AND for <collaborator> right after a successful
  migration. (<collaborator>'s scoped `/work` was unaffected — it resolves `users.<collaborator>.projects`.)

**C. Fleet/liveness reads are blind to a consumer-locus worker (KERNEL GAP — 3 false reads today).**
- **`fleet-verdict-blind-to-consumer-locus-worker`** — `journal query --fleet-verdict` returned
  **CONFIRMED-DEAD (silent_stop, 2-tick)** for the worker **while it was alive and landing consumer
  task in the aiseller locus**. A kernel-dispatched worker whose work rides the **CONSUMER** journal
  is invisible to the kernel fleet read — the proc check and the kernel-journal staleness check BOTH
  misfire. `dispatch --watch` would wake-false-dead every tick for any consumer-heavy card. Three workers
  were false-read this way today. Fix candidate: fleet-verdict folds the `-C` consumer journals of registry
  `yitc_v2` projects (it already knows them) before declaring `silent_stop`.

**D. Ordering + gate frictions (each cost a real stall).**
- **`aiseller-p2-requires-edge-vs-dirty-main-land-order`** (decomposition-deadlock class) — the cut's
  `requires:` edge contradicted consumer **land mechanics**: (ops-contract) could not LAND while
  aiseller `main` carried the 25 decided-leftover dirty paths owned by the sweep cards — but the sweep cards
  REQUIRED done. A deadlock, surfaced by the worker's handback, resolved by a governed `requires:`
  re-order. → **when cutting a migration plan, the `requires:` graph must respect that `land` refuses to
  fast-forward over foreign dirt: the card that CLEARS the dirt precedes the card that must land through it.**
- **`consumer-b5-blind-audit-adhoc-without-read-corpus-or-sweep-aborts-no-evidence`** — the `-C` external
  BLIND revizia (`audit adhoc`) run WITHOUT `--read-corpus` / `--sweep-file` **ABORTs on no-evidence** (the
  auditor is forbidden to read the repo and nothing was inlined) — it burns a full auditor invocation and
  reads as a spurious track-divergence. The fix already EXISTS (`--read-corpus` + a mechanical
  `--sweep-file`) but is **not the default and is easy to forget at a completion gate**.
- **`onboarding-seed-leaves-memory-dirty-on-consumer-main`** (the X-0274 class, from the SEED side) — the
  onboarding-pointer SEEDING (<collaborator>'s + dev's station rows in the consumer `MEMORY.md`) left the seed
  **uncommitted on consumer `main`**, wedging every later `land`. The CONSUME side owns its commit
, but the SEEDER does not. Recovered by a scoped direct commit.
- **`liveprobe` needs a consumer task carrier** (deploy-card class, consumer journal) — the governed
  `liveprobe` verb keys on a **consumer task YAML** carrying the per-change probe assertion, but the
  migration-day prod deploy was governed by a **KERNEL** task — no consumer task existed to key
  on, so live evidence had to be gathered by direct healthz probes (internal :8007 + public + runner :8011 =
  200/200/200). Fixed in-flight by the Controller adding the assertion to the kernel card.
- **`ac-probe-event-types-not-surfaced-at-execution-stage-entry`** — an AC-probe emitted under a BESPOKE
  event type (`igor_entry_path_verified`) instead of the COVERED `state_checked` class; the whitelist is
  closed, so audit-post rendered genuinely-present journal evidence as ABSENT and RED-flagged AC1 (**1
  wasted audit pass**). The covered set is not surfaced at Execution stage-entry — a worker only learns it
  by grepping the CLI after the RED.
- **`controller-stray-external-action-bookkeeping-note`** (Controller self-catch) — one stray
  `external_action` event (`action=none`, a bookkeeping note) appended by the Controller, violating the
  SPEC-0116 bright line (reads / no-effect calls are excluded). Journal is append-only, so the line stays:
  harmless noise, flagged for triage awareness. **Recorded because a Controller's own slips are exactly the
  ones nobody else captures.**
- **`aiseller-premigration-packet-home-not-offsite-covered`** — the plan asserted the pre-migration snapshot
  packet lives in an OFFSITE-COVERED backup home; it does not (`offsite-backup.sh` rsyncs only
  pattern-matched top-level tarballs and its `<host-home>/` sync `--exclude=backups`). The repo+tag DO travel
  offsite; the residual gap is the `.yitc` / `.env` / untracked tar. → **"it's backed up" is a claim to
  VERIFY against the backup script's actual match patterns, not to assume from the directory's name.**
- **`the AI provider-runner-repo-the AI provider-md-dependency-edge-is-false`** (false-premise risk edge carried through the
  plan, a card scope, AND the Controller brief) — all three asserted «the AI provider-runner reads the repo
  `<vendor-adapter>.md` context → re-run the functional probe post-transform». **It does not:** `runner.py` invokes the
  CLI with a HARDCODED `cwd=/tmp` and an explicit `--exclude-dynamic-system-prompt-sections`. A risk edge
  that three artifacts agreed on was still false — **agreement is not evidence; read the code.**

**E. Dispatch-liveness (3 worker deaths on long silent waits).** Workers died / were force-recovered while
BLOCKED on legitimately long silent waits. Combined with **C** above, the lesson is one: **a long SILENT
stretch is the EXPECTED shape of a foreground `land`/audit — not a death signal**, and a fleet read that
cannot see the consumer locus must not be treated as a liveness ORACLE. Today's halts were dominated by
audit-loop-ceiling holds (`bg_dispatch_halted` × 6 on), two
`controller_stop`s, and two governed pre-claim `refused`s (— the SPEC-0133 exit working
as designed).

## Meta-analysis — gate-4 aiseller migration (the FIRST multi-user instance)

> Periodic distillation pass over the §aiseller gate-4 entries above (runbook intro discipline). It
> generalises the instance into recurring SHAPES + routes every kernel-absent gap; the raw entries stay above.

**The recurring shapes (what a MULTI-USER v1-incumbent migration adds on top of gates 1–3):**

1. **Every per-user surface is a COPY, and a copy rots invisibly.** Entry skills (`/start`, `/work`),
   `settings.json` (permission allowlist + hooks), crontab, secrets ACLs — each exists ONCE PER HUMAN, is
   never regenerated from a source of truth, and is invisible from the owner's session. The owner's surfaces
   being correct says NOTHING about a collaborator's. → **the above-kernel checklist (§B5-check-3), walked
   per collaborator, AS that collaborator.**
2. **A shared field with several readers needs co-design, not a flip.** `registry.active` was flipped for a
   v1-quiesce meaning and silently changed `/start` visibility + collaborator `<vendor-adapter>.md` generation. →
   **before flipping any registry field, enumerate its READERS** (the §B2 «reconcile EVERY registry-derived
   surface» rule, now extended: not just derived VIEWS — independent READERS with their own semantics).
3. **The kernel's own fleet/liveness reads are single-locus.** A kernel-dispatched worker doing CONSUMER
   work is invisible to the kernel fleet read — so the Controller's cheapest liveness instrument
   systematically lies on exactly the cards a migration is made of. This is a **KERNEL GAP**, not a
   migration quirk.
4. **A completion-gate's expensive external pass needs its evidence flags ON BY DEFAULT.** The blind B5
   revizia aborts with no evidence unless `--read-corpus`/`--sweep-file` is remembered — a default that
   fails CLOSED into a wasted invocation and a spurious "track divergence".
5. **Ordering claims must respect land mechanics.** A `requires:` edge that ignores «`land` refuses to
   fast-forward over foreign dirt» produces a genuine deadlock no worker can resolve in-scope.
6. **Three artifacts agreeing is not evidence.** The the AI provider-runner risk edge was false in the plan, the card,
   AND the brief. The only thing that settled it was reading `runner.py`.

**X-numbered multi-user meta-findings (the NEW class this migration contributes; ids continue the shared
sequence — max on disk before today = X-0332):**

- **X-0333 — per-user entry skills are un-propagated stale COPIES.** A collaborator's
  `~/<provider-config>/commands/{start,work}.md` are per-user copies that no mechanism refreshes; <collaborator>'s were 3 months
  stale and `work.md` was absent entirely (`/work` → `Unknown command`). Routed: §B5-check-3 row 3 (this
  change) + the person-doc enrichment task (below).
- **X-0334 — a collaborator's permission sandbox excludes the engine binary.** The one mandatory consumer
  step (`session start` through `<engine>/bin/yitc-v2`) is outside a cwd-scoped sandbox → approval gate on
  the non-skippable step; `permissions.allow` was empty. Routed: §B5-check-3 row 4.
- **X-0335 — guard hooks are per-user, so a claim that "the guards permit this flow" must name WHOSE
  settings.json wires them.** The brief/plan asserted dev-scope hooks protect a <collaborator> session; they are
  never loaded there. Routed: §B5-check-3 row 2.
- **X-0336 — group-based secrets access over-grants AND under-grants simultaneously.** `dev:dev 0700` +
  `<collaborator>:<collaborator> 0600` locked BOTH actors out of a shared `env_file`; other collaborators (<collaborator-2>, <collaborator-3>) sit
  in group `dev`, which over-grants. Named-user ACLs are the fix when the group is the wrong granularity.
  Routed: §B5-check-3 row 8.
- **X-0337 — `registry.active` is overloaded across independent readers** (v1 quiesce vs `/start` visibility
  vs collaborator-`<vendor-adapter>.md` generation) — a quiesce flip hid the live flagship consumer from the picker.
  Routed: §B5-check-3 row 1 + the §B2 registry-reader rule (this change).
- **X-0338 — fleet-verdict is blind to a consumer-locus worker** (3 false CONFIRMED-DEAD reads today).
  Routed: **kernel task** (below) — this is a kernel defect, not runbook craft.

**Per-deviation routing roll-call (SPEC-0090 realm-routing — no friction dropped).** Every gate-4 deviation
is either (a) GENERAL migration/onboarding craft → generalised INTO the runbook here (the §B5-check-3
checklist + the §B2 registry-readers rule + the §B5 read-corpus default + the §B2b/dispatch-liveness note),
or (b) a KERNEL defect → routed to the kernel's OWN queue. **Note the realm asymmetry:** this repo IS the
kernel, so a kernel gap found here routes via `task file` / `followup` — a `cross request` addressed to
`yitc-v2` from `yitc-v2` would be a self-addressed no-op (SPEC-0084: the cross log carries CROSS-project
routing). Consumer-product findings (the aiseller health-runbook, the secrets ACL) route to **aiseller's own
`-C` queue**, never a direct cross-repo write. Zero items are ai-seller-product-specific craft homed here.

**Kernel-absent gaps → the routing recommendation (named here, NOT authored here):**

- **AI-safety / AI-embeddedness doctrine (`fu_53e01ab68382` + the armed sibling `fu_698581669b2f`).** The
  owner's three live cues (an `ai_safety` ops-contract concern · SPEC-0100 baseline entries · a traveling
  `ai-safety-health` revizia theme · the two-layer travel model for the fork) plus the inbound-hardening
  sibling (consumer-authored text becomes UNTRUSTED INPUT to kernel AI sessions once the kernel forks
  externally) are **multi-spec doctrine** — they exceed what a task card should carry. **RECOMMENDATION: one
  kernel PLAN** (CHARTER §P1 4-filter check at its draft stage; extend the EXISTING SPEC-0026
  instruction-injection home rather than inventing a parallel one). Deliberately **not authored by this
  card** — naming it is this card's job.
- **fleet-verdict consumer-locus blindness (X-0338)** → kernel task **** (fold the `-C` consumer
  journals before declaring `silent_stop`).
- **`fu_7a8ba374ec5c` (remote-sync / CI ops-contract concern)** — its ARMED trigger («aiseller plan P6
  meta-analysis») FIRES with this pass → promoted to kernel task ****.
- **`fu_e0e14db83ac9` (init `--adopt-extension` leaves contradictory adopts+waives)** — its trigger (the
  plan's decomposition stage) has PASSED, but the concern is **NOT moot**: it was RE-EVIDENCED on migration
  day (9 aiseller per-concern adoption records still read `waived` while the carrier stance says adopted —
  the X-0088 half-registration class alive inside the very mechanism meant to close it). Promoted to kernel
  task **** rather than dropped.
- **The per-user-surface staleness class (X-0333/X-0334) also belongs in the PERSON doc** — an adjacent
  improvement to a file outside this card's declared scope, so filed per AGENTS §Filing rule as kernel task
  **** instead of being smuggled into this diff.

**Routed ids (this pass): · · ·.** The AI-safety doctrine seed stays a
PLAN recommendation (`fu_53e01ab68382` + `fu_698581669b2f` remain the carriers) — deliberately not
authored as a task here.
