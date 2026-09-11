# Onboarding onto YITC — runbook (two branches: greenfield · brownfield-migration)

> **Born:** 2026-06-23, at the ai-gateway gate-1 brownfield migration (the FIRST brownfield onboarding).
> Implements the design home `ideas/practices-layer-paved-path-baseline-for-real-proje.md §Onboarding
> family`. **ONE runbook, two EXPLICIT branches** (anti-complexity F1/F3 — one home, branch by shape, like
> the lifecycle hygiene fast-path). Each onboarding refines it; a general lesson graduates IN
> (`lessons/`→`patterns/`, SPEC-0090). **Live-capture discipline:** append every friction to the
> §Frictions log — now in the sibling `patterns/onboarding-onto-yitc-frictions-log.md` (split per
> SPEC-0120 §3) — AS it happens (owner directive 2026-06-23 — accumulate data live, not
> post-hoc meta-analysis; a periodic meta-analysis pass distils/generalises over the accumulated log).

## Shared core (identical for both branches)

> **Steady-state companion — the host/server surface contract.** This runbook covers ONBOARDING a new
> project. For "how do I work with the CURRENT server's host/kernel surfaces cleanly NOW" — the
> coordination store, `registry.yaml`, the `<host-home>` router, and the host auto-committer, each with
> its OWNER label + maintain/correct steps — read **`patterns/host-server-surface-contract.md`** (the
> single steady-state map; reached from here so it needs no server-wide search).

The **import-completeness gate** — mandatory-core import (the mandatory handbook seed (the generated HANDBOOK_READ_ORDER set) + CLI +
journal + floor trigger-map landed) + the GENERATED activation-checklist declare-or-waive walk
(`graph/activation-checklist.md`, SPEC-0096): one row per kernel baseline concern that declared an
`init_question`, forcing a conscious declare-or-waive. This is what gives both branches the SAME «nothing
the project needs from the kernel is silently dropped» guarantee.

- **Pre-condition (DONE 2026-06-23):** the checklist is auto-grown from each concern spec's
  `init_concern` declaration. As of it covers **3 concerns** — `SPEC-0094` (deploy), `SPEC-0099`
  (no-secrets-in-durable-artifacts), `SPEC-0100` (behavioral-baseline). The deferred concerns
  (config / observability / migrations) auto-appear when `` lands — and ``'s return_trigger
  («a named-project migration onto the kernel pulls the section») FIRES on this ai-gateway migration, so run
  the walk with the expectation that `` ripens alongside Phase 1.
  - **Read the live concern set from the generated SoT, not this prose.** Beyond the 3 above,
    **deploy-AUTONOMY (`SPEC-0097`)** is now a further declare-or-waive concern in the generated walk
    (added — whether the consumer may deploy autonomously: an on-plan policy OR an explicit owner
    born-waiver, never a silent default). The authoritative, auto-grown set is the generated
    [`graph/activation-checklist.md`](../graph/activation-checklist.md) (SPEC-0096) — consult it for the
    current concern list rather than this hand-maintained count.

- **Two surfaces — the activation-checklist SET is NOT 1:1 with the `yitc-ops.yaml` carrier (clarifying the gate-1 finding A).** The activation-checklist SET (3 universal concerns) and the
  `yitc-ops.yaml` carrier (SPEC-0093 — 8 sections) are TWO DISTINCT surfaces, and only **deploy** overlaps.
  This is correct BY DESIGN (the external auditor confirmed it) — do NOT read «3 SET concerns» as
  «3 carrier sections to fill». Each SET concern is acknowledged on its OWN surface:
  - **Carrier-section concern → declared-or-waived IN `yitc-ops.yaml`.** Of the 3 seed concerns only
    **`SPEC-0094` (deploy)** is one: its answer is the `deploy:` / `rollback:` / `live_probe:` sections
    (SPEC-0093 rule 2), each a declare-or-waive stance the `init`/sweep checks fail-closed.
  - **Standing-mechanism concern → acknowledged via its OWN mechanism, NOT a `yitc-ops.yaml` section:**
    - **`SPEC-0099` (no-secrets)** — a standing NOW-rule whose adherence is a CONSTRAINT verified by
      ABSENCE (no secret appears in `events.jsonl` / committed docs / diffs / probe output / auditor
      payloads). Acknowledgement = holding the standing rule; there is NO carrier section, NO stored
      status, NO emitted event (SPEC-0099, surfaced via the doc-checklist adoption-evidence column).
    - **`SPEC-0100` (behavioral)** — acknowledged at AUTHORING TIME by a consumer-authored
      `specs/<SPEC>.yaml` that `cites:` the catalog `patterns/behavioral-baseline-defaults.md`, reached
      via the `before-authoring-interaction` floor reminder in `graph/floor-trigger-map.md` (first
      instance: kupiclub SPEC-0016, confirm-before-irreversible). NOT a carrier section.

  So the SET guarantees CONSIDERATION across BOTH surfaces; a migrator records the deploy answer in
  `yitc-ops.yaml` and acknowledges no-secrets/behavioral via their standing mechanisms above — it does
  NOT expect all three to live in the carrier.

- **The sweep must cover EVERY owner-significant concern that can DEFAULT silently — not only those that
  declared an `init_question` (gate-1.5 finding X-0088, external-audit MED generalized).** The
  activation-checklist only surfaces concerns whose spec declared an `init_concern`/`init_question`; a
  governance/safety concern that has NO such declaration DEFAULTS to a SILENT born-waiver the owner never
  sees on-plan. The motivating gap: **deploy-AUTONOMY (`SPEC-0097`)** — whether the consumer may deploy
  autonomously — was decided as a silent init born-waiver, never surfaced. → **Rule:** every concern that
  can default/waive owner-significant behaviour must appear in the declare-or-waive walk with
  OWNER-VISIBLE wording, forced to EITHER an explicit on-plan declaration OR an explicit owner-authored
  born-waiver (with a real reason) — never an invisible default. `SPEC-0097` is the FIRST concrete concern
  to add (kernel task); the GENERIC sweep that closes the whole class is kernel task. Safety
  corollary: surfacing the DECISION must NOT auto-seed an active policy (that would silently GRANT
  autonomy) — the sweep surfaces the choice, the owner makes it.

### Known environment friction — temp-file writes in a `-C` consumer session are confined to the project root (NOT a yitc guard)

**Symptom (X-0109 /, 2026-06-28).** In a `-C <consumer>` session, writing a temp working file to
the **harness session scratchpad** (a `/tmp/.../scratchpad` path the AI tool offers) is **refused**,
forcing a `stdin`-heredoc fallback (first hit: the social-parser migration).

**The actual refusal source — NAMED (do not mis-attribute).** It is **NOT** the yitc-v2 engine guard:
`SPEC-0078`'s `_assert_write_in_repo` (installed at `bin/yitc-v2#write_text_atomic`) only refuses writes
**under `ENGINE_ROOT`**, and the `/tmp` scratchpad is outside BOTH `ENGINE_ROOT` and `REPO_ROOT` — so the
engine never sees that write. The refusal comes from the **V1 `scope-guard.sh` PreToolUse hook**
(`ai-team-framework/bin/hooks/scope-guard.sh`, wired globally in `~/<provider-config>/settings.json` alongside
`~/bin/user-scope-guard.sh`): it blocks every `Edit`/`Write` whose path is **outside the owned project
root**, anchored on session identity (not cwd). A `/tmp/.../scratchpad` path is outside the owned
consumer root → blocked. This is a **harness-level (provider hook) confinement**, external territory
 — a yitc-v2 Build session cannot edit it, and a kernel carve-out would be the wrong home.

**Supported workaround — write temp files INSIDE the project root.** The scope-guard confines writes to
the owned project, so put scratch files **there**, not in `/tmp`:
- Write the temp working file under the consumer repo root (e.g. a gitignored `.scratch/` or any path
  inside the checkout) — the hook permits it, and a worktree-isolated/gitignored path keeps it out of the
  landed corpus.
- OR keep the `stdin`-heredoc fallback (no on-disk temp file) — already the de-facto escape; it is
  supported, not a defect.

Both avoid the `/tmp` scratchpad entirely. Do **not** file this as a kernel bug against `SPEC-0078` (the
X-0109 mis-routing): the guard that refuses is the external V1 scope-guard hook, by design.

## Branch A — greenfield (zero-to-one, the simpler SUBSET)

Start from empty: initial project CHARTER/conventions, first specs/scenarios authored, consumer-friction
capture. NO preflight, NO in-place overlay, NO legacy comprehension. First instance: kupiclub pilot
(`ideas/`/plan `greenfield-kernel-and-scenario-pilot-kupi-club`). Detailed steps grow here as greenfield
onboardings recur.

## Branch B — brownfield-migration (the SUPERSET) — the gate-1 path

Shared core + preflight the LIVE repo + in-place overlay on a running product + large-context comprehension
of existing code + the two-gate proof. Governing plan: `plans/real-project-integration-onto-v2-phased-migration-`.

> **Legacy prose-docs corpus — MEASURE it, don't trust or bulk-rewrite it.** A brownfield project's
> pre-v2 `docs/` corpus is measurably part-false (aiseller 2026-07: 50% of claims true; boomrocket:
> 63%) and is prime hallucination fuel for every future session. Run the sibling runbook
> **`patterns/legacy-docs-assessment-and-migration.md`** (inventory → mechanical dead-ref scan →
> semantic agent verification → 5-class triage → per-file LEGACY banner → MANDATORY lazy promotion
> into specs/scenarios/lessons) as part of Branch B — dangerous docs (deploy/testing/money) are
> fixed FIRST, before they feed a session.

### B0 — Standalone-repo prerequisite (carve-out, if the target is a monorepo subdir)

**Why:** `bin/yitc-v2 -C <path>` resolves to the path's git TOPLEVEL. If the target is a subdirectory of a
larger monorepo, `-C` resolves to the MONOREPO ROOT, not the service — so the whole migration contract
(own `main`, per-worktree isolation, `land`) does not apply. The target MUST be its own git repo first.

**Procedure (fresh repo — history stays recoverable in the monorepo archive):**
1. **Preflight the path coupling FIRST** — grep host automation + config for the current path before
   moving it. Anything that hardcodes it must be reconciled or the move silently breaks it. (For
   ai-gateway: `offsite-backup.sh` ×2, `session-scope-guard.sh`, `registry.yaml` — see §Frictions log.)
2. **Identify source vs runtime** — copy SOURCE only; EXCLUDE runtime data (live DBs) + secrets. A
   gitignored runtime DB stays with the running deploy, never enters the source repo.
3. **Create the standalone repo** at the projects home (`<host-home>/projects/<name>`): copy source, `git
   init`, initial commit. **Do NOT move/stop the running deploy** — copy, don't `mv`; zero outage.
4. **Repoint the source home** — `registry.yaml` `path:` → the new repo (what yitc routing + `-C` need).
5. **Cutover (explicit, owner-visible — NOT silent):** redeploy the running service from the new repo;
   update the hardcoded automation refs (backup coverage, scope-guard) to the new path; retire the old
   subdir copy AFTER the redeploy is confirmed. Until cutover, the live deploy keeps running from the old
   path (its runtime DB + existing backup coverage intact).

### B1 — Phase 0: worth-it + scope (big-model + OWNER)

Decide IF the project integrates: will it grow (scaffold payoff beats raw-iteration overhead — pays off on
bulk / concurrency / audit-trail, not solo quick edits)? Migrate-while-simple (cost asymmetric). Output:
go/no-go + which backbone parts now vs deferred + the preflight result.

### B2 — Phase 1: bootstrap the minimal backbone + RUN the import-completeness gate FIRST

`bin/yitc-v2 -C <repo> init` (born-empty scaffolds) → run the shared-core import-completeness gate (above)
→ stand up specs for the load-bearing rules + the graph (rules→code) + the first task corpus. Large-context
comprehension of the existing code.

**Enumerate ALL load-bearing surfaces HERE, not at B5 (gate-1 finding, 2026-06-24).** Before declaring the
backbone stood up, walk EVERY charter-named contract + every app entrypoint / route / public symbol and
classify each: spec-or-conscious-waive. A surface a real consumer already depends on IS load-bearing now
(not "grow on incident") — so it gets a spec at B2. The §B5 revizia is then an INDEPENDENT re-check that
CONFIRMS this coverage, not the first place the surfaces are counted. (gate-1 miss: the billing-READ API +
`/health` were load-bearing-but-uncovered and were only caught by the B5 revizia — see §Frictions / §Meta.)

**Pre-study the project's COMPONENTS across dimensions — especially the ones the KERNEL does not model yet
(gate-1.5 generalization, owner-directed 2026-06-25).** The load-bearing-surface walk above is the
GOVERNANCE-surface inventory; alongside it, do a COMPONENT pre-study — sweep the project's real moving
parts by dimension (runtime services, scheduled/product cron, deploy pipeline, liveness/freshness needs,
data deps, host-automation coupling) and flag each as **kernel-modeled** (already has a v2 home: specs /
`yitc-ops.yaml` / lifecycle) vs **KERNEL-ABSENT** (no v2 home yet — e.g. product cron + liveness before
the v2-automation plan existed). The kernel-absent components are the highest-value find: they are what a
naive "just stand up specs" backbone misses and what later bites at restore/cutover. Each migration then
produces a short **META-ANALYSIS** of its pre-study (the social-scraper gate-1.5 model: the 8 meta-findings
X-0085..X-0090), and every kernel-absent gap is fed BACK to the kernel as a `cross request` (→ a kernel
task/plan), so the kernel grows to model it before the NEXT migration hits the same gap (seed-and-grow:
the migrations are the real-incident pull that grows the kernel). This is a STANDING B2 step, not a
one-off — boomrocket/aiseller will each pre-study + meta-analyze their own components.

**A liveness/freshness signal is often a LIVE query, not declarative config — and the kernel reads it via a PROJECT-OWNED adapter (trend-finder L3 gate-2, drained from `fu_2169157e34d6` after; deviation `l3-freshness-source-registry-block-assumption-vs-live-db-logs-reality`).** When a KERNEL-ABSENT liveness/freshness component surfaces in the pre-study, do NOT assume its freshness source is a static config block — INSPECT the real incumbent monitor to see what it ACTUALLY reads (trend-finder's v1 watchdog computes freshness LIVE: a Postgres `last_scanned_at`-vs-`scan_interval_hours` query for discovery + a celery docker-log heartbeat for tracking — there is NO thresholds block). → **generalised: a freshness source can be a live DB query / logs, not a file — verify against the incumbent, never the assumption.** The fix pattern (external consult, RED→adopted): the kernel L3 monitor stays a GENERIC grader; each project supplies a thin **read-only freshness ADAPTER** returning normalized per-pipeline `{fresh|stale|miss}`+age, consumed through the monitor's injectable `_read_pipeline_state` seam — NEVER project-specific SQL/docker embedded in kernel code (P1 + the territory smell). → **generalised: a kernel monitor that must read a project's live state reads it via a project-owned read-only adapter behind an injectable seam.** Recon trap: a project's **name ≠ its repo path** — "trend-finder" is the registry KEY, its repo is `<host-home>/projects/social-parser` (registry `path:`); resolve every repo via `registry.yaml path:`, never the product name (a path built from the product name does not exist).

**Make the migration visible to `/start` (completion step — easy to miss):** set `methodology: yitc_v2`
on the consumer's `<host-home>/registry.yaml` entry (same token as the kernel entry). A migrated project
with NO `methodology:` field DEFAULTS to `legacy`, so `/start` keeps grouping it under 🔵 Legacy even
after a full gate-1 migration. The edit rides the host `<host-home>` AUTO-COMMITTER (don't hand-commit the
monorepo). (gate-1 finding, 2026-06-23 backbone session.)

**Reconcile EVERY registry-derived surface, not just `/start` (gate-1.5 finding X-0090; the workspace.yaml
half CORRECTED at gate-2, 2026-06-26).** `registry.yaml` is a SOURCE of truth other surfaces are DERIVED
from; flipping `methodology:` alone can leave a consumer "migrated" in one view and "legacy" in another.
Reconcile each surface — but note WHICH are auto-derived vs which are v1-only:
- **`/start` + the v2 nightly enumerator are LIVE-derived from `registry.yaml`** — flipping `methodology:
  yitc_v2` auto-regroups the consumer under `/start`'s «YITC-v2 consumers» (no edit), and the v2 nightly
  (`yitc-v2 nightly`) enumerates every `methodology: yitc_v2` project from registry directly. Verify, don't edit.
- **`yitc-workspace/workspace.yaml` is a V1 SURFACE — REMOVE the migrated consumer from its `projects:` list,
  do NOT add it back.** That `projects:` list is what the v1 `yitc check --workspace` / v1 nightly read; a v2
  consumer does NOT belong there. (The generator `generate-workspace.py` only ever puts `methodology: yitc`
  in `projects:`, never `yitc_v2` — so "regenerate so it enters `projects:`" is impossible AND wrong. v2
  consumers are health-checked by the v2 nightly from `registry.yaml`, not via workspace.yaml; social-scraper
  / kupiclub are de-facto absent from it.) **This SUPERSEDES the earlier gate-1.5 instruction to "regenerate
  workspace.yaml so the consumer enters `projects:`"** — that was wrong on both counts.
- **The methodology flip ALONE excludes the consumer from ALL v1 machinery** — the 3 v1 enumerators
  (`yitc-night-cycle.sh`, `auto-session.sh`, `check-methodologist-heartbeat.sh`) each skip `methodology==yitc_v2`
  — so a temporary `active: false` migration-quiesce becomes REDUNDANT after the flip (safe to remove).
All host-territory — rides the `<host-home>` auto-committer, never a hand-commit of the monorepo. (gate-1.5
origin: social-scraper was flipped in `registry.yaml` but stayed stale in `workspace.yaml`; the CLASS holds —
a migration that flips an authoritative registry field reconciles every derived surface — only the
workspace.yaml DIRECTION was corrected at gate-2.)

**Record a liveness + rollback evidence packet (gate-1.5 finding, external-audit MED).** A brownfield
migration runs in-place on a LIVE product, so "the service stayed up" must be EVIDENCED, not asserted.
For every brownfield migration capture a small packet (in the migration plan / §Frictions): **(1) was
runtime touched?** (a backbone-only migration that adds specs/graph/queue touches ZERO runtime — record
the proof of non-touch: no runtime file in the diff, the deploy unchanged); **(2) if touched, what
health/process/container evidence proved continuity** across the change (pre/post health probe, container
up, no error spike); **(3) what rollback path exists** if a cutover is involved (and for a §B0 carve, the
old path keeps running until the redeploy is confirmed — that IS the rollback). This is a recorded packet,
not a new gate — it makes the zero-impact claim auditable instead of anecdotal.

**Quiesce the project's LIVE v1 background writers BEFORE running content-import cards (boomrocket
gate-3 finding, 2026-06-30).** Any cron / systemd timer / app daemon that AUTO-WRITES into a file you
are migrating (a backlog, a decisions log, a scenario dir) will dirty the consumer `main` checkout
mid-migration, and every `land` correctly refuses to fast-forward over the foreign churn — so it blocks
the WHOLE import wave (boomrocket: 2 of 5 background import workers died-but-unlanded on it). Before the
content-import, ENUMERATE every live writer into a to-be-migrated path — `grep` the crontab + `systemctl
list-timers` + app daemons for the target paths — and disable/redirect EACH. Do NOT trust the "named sync
apparatus" list alone: a migrated file is a RETIRED file, so anything still auto-writing it is in scope,
even a product-health cron nobody thought of as "sync". See §Frictions (boomrocket gate-3).

**Transform the project's OWN surface too — not just stand up the corpus (boomrocket gate-3
generalization, 2026-06-30).** Standing up specs/graph/queue is only HALF a migration; the project's own
OPERATIONAL + INSTRUCTION surface must also move off v1, or the §B5 revizia keeps DISCOVERING the same
residue (it recurred across ai-gateway, social-scraper, boomrocket). Three standing B2 sub-steps, each a
recurring miss — do them HERE so B5 CONFIRMS rather than discovers:
- **Wire the ops-contract (`yitc-ops.yaml` + `yitc-verify.yaml`) to REAL surfaces.** `init` seeds every
  section born-WAIVED (deploy / rollback / live_probe / verify / ui / tests / host_config / security). A
  born-waiver left unreplaced on a project that REALLY has that surface is a silent half-migration (the B5
  T6 waiver-vs-real-command finding). Walk EACH section: declare it against the real surface (the deploy
  command, the live URL, the UI stack, the test taxonomy) OR write an HONEST NAMED waiver that cites the
  real surface + a tracked task — never leave the init placeholder text. **Fork (declare-vs-track):**
  declare the cheap real values now; where honest wiring is real engineering (a deploy still routed through
  the v1 framework; a non-hermetic test suite needing an isolated per-run DB), DECLARE what is cheap and
  TRACK the hard re-engineering as its own consumer task — do NOT re-engineer a working production deploy
  under the migration umbrella, and do NOT declare a non-hermetic command the land-gate would then run.
- **Run the SPEC-0100 security authoring-moment defaults over the brownfield surface once (secbaseline
  review).** A migrated project authored its auth + secrets handling BEFORE the kernel's security
  defaults existed, so walk the six SPEC-0100 §Security authoring-moment defaults against the REAL surface:
  key separation (a data-encryption key ≠ the session / JWT signing key) · no secret in logs / traces /
  error bodies · no placeholder secret in a live env · a rehearsed scripted rotation covering every
  ciphertext surface · a backup restore-drill · the auth baseline (httpOnly session / CSRF posture /
  uniform auth errors / login rate-limit). This is a ONE-TIME authoring-moment REVIEW — fill each default
  against the real surface or waive-with-reason — NOT a gap register or a probe obligation (the
  owner-adjudicated LIGHT form; the heavier enforcement form is parked). Grounds: the aiseller
  retrofit-live incidents (X-0369 — 8h prod-auth + 5h key-rotation outages; X-0345 item 1 — a rotation
  with no ciphertext-surface map). Fetch: `<engine>/bin/yitc-v2 -C <path> graph query SPEC-0100`
  §Security authoring-moment defaults.
- **Move the project's OWN AI-instruction docs off v1 AND out of the vendor-specific `<vendor-adapter>.md`
  (the consumer vendor-adapter doctrine — SPEC-0125).** The project's `<vendor-adapter>.md` (and any project
  charter/README) routinely still INSTRUCTS the AI to load v1 methodology (a "Team Mode" /
  `ai-team-framework/core/*.md` methodology-source table) — a HIGH instruction-fidelity defect, because
  a fresh session reads it and loads the retired pipeline. Two moves, per SPEC-0125:
  - **Substantive project operating-context → a PROVIDER-NEUTRAL home, NEVER inside `<vendor-adapter>.md`.**
    `<vendor-adapter>.md` is a the AI provider-vendor-specific filename other providers won't read, so product rules
    (safety bans, integration constraints, PII policy, module/profile notes) live in the ONE declared
    neutral home: the consumer's product **`CHARTER.md`** if it has one, else a project **`AGENTS.md`**
    (`README.md` only if the project explicitly designates it). This mirrors the kernel's own thin
    adapter (: kernel `<vendor-adapter>.md` = a 5-line `@AGENTS.md` pointer).
  - **`<vendor-adapter>.md` = a THIN adapter only** — the engine location + the `-C` verb form + a pointer to the
    neutral home. **CRITICAL — a consumer session has NO local `bin/yitc-v2`, so the adapter MUST show
    the engine-absolute verb form `<engine>/bin/yitc-v2 -C <path> <verb>`** (a bare `bin/yitc-v2` is
    command-not-found in the consumer repo — the X-0144 class). NO product rules, methodology, or deploy
    sections inside `<vendor-adapter>.md` (the trend-finder `## Deploy` over-scope, reverted).

  Drop this thin adapter block into the consumer `<vendor-adapter>.md` (fill in the two absolute paths + the
  neutral-home filename); put the product rules in the neutral home:

  ```markdown
  # <project> — YITC-v2 consumer

  This project runs the YITC-v2 methodology, provided by the kernel (engine) at
  `<engine>` (e.g. `<repo-root>`). This repo has NO local `bin/yitc-v2` — run every
  yitc verb through the engine binary in `-C` mode, targeting THIS repo:

      <engine>/bin/yitc-v2 -C <this-repo-abs-path> <verb> # e.g. … -C <path> graph query SPEC-0007

  Session start: `<engine>/bin/yitc-v2 -C <this-repo-abs-path> session start` (or the `/yitc` entry).
  Read the kernel handbook (CHARTER -> AGENTS -> AGENTS-SESSIONS -> AGENTS-PROTOCOL -> LIFECYCLE ->
  QUEUE -> GRAPH) at the engine; this project's own governed state lives here
  (`specs/` `tasks/` `plans/` `events.jsonl` `yitc-ops.yaml`).

  Project operating-context (safety bans / integration constraints / PII policy / profile):
  see this project's provider-neutral home — <CHARTER.md | AGENTS.md>.
  ```
- **A kernel handbook fork / extraction / read-order re-split must ALSO update the EXTERNAL entry-skill
  read-order glosses ( miss).** The handbook read-order file list is hardcoded in several external,
  out-of-repo copies `graph build` does NOT regenerate: the global entry skills `~/<provider-config>/commands/start.md`
  + the `/yitc` + `/work` skills, and this consumer `<vendor-adapter>.md` template gloss above. When the kernel
  handbook set changes (the split added `AGENTS-SESSIONS` + `AGENTS-PROTOCOL`), every one of these
  glosses is a second copy that silently drifts unless hand-updated in the SAME change. Enumerate + update
  each external read-order gloss as part of any fork/extraction/re-split.
- **Retire EVERY v1 carrier file, not just the headline two.** Marking `BACKLOG.md` / `DECISIONS.md`
  HISTORICAL is necessary but not sufficient — the same sweep covers the SIBLINGS: `CROSS-TASKS.md` (the
  retired per-repo cross-log), `REVIEW-TASKS.md`, stale `drafts/auto-*` dirs, `knowledge/`, and the deploy
  path's v1-framework dependency. Enumerate every v1-corpus-named file + every v1-tooling reference and
  mark/empty/justify EACH. (boomrocket gate-3: F2d marked BACKLOG/DECISIONS but left CROSS-TASKS.md a live
  1405-line v1 log + drafts/ stale + deploy.sh on the v1 deploy-common.sh.)

### B2-import-safety — imported-card provenance + premise-verify + product-card owner-gate (SPEC-0166 · SPEC-0167, both active/code-enforced)

> **Born:** the aiseller 2026-07-13 import wave (85 imported cards in a day; already-fixed burned a
> full pre-claim analysis; the CSRF product card, dispatched inside what the owner read as a
> migration/revizia context, took prod auth down). Origin cross X-0372; plan
> `migration-import-safety-provenance-marker-premise-`. Fetch: `<engine>/bin/yitc-v2 -C <path> graph query
> --kernel SPEC-0166` / `SPEC-0167`.

A brownfield migration re-files an existing backlog into v2 task cards. Three code-enforced safeguards now
guard the import→dispatch path — **RETIREMENT: an imported card no longer flows straight from B2 to B3.**

1. **Import-time provenance — stamp `imported_from:` at import (B2).** Every card re-filed from a prior
   backlog — from ANY source (YITC v1, another methodology like Jira/Linear, a vibe-coding TODO dump, a
   hand-migrated list) — carries `imported_from: <source-ref>`, set at import time. The field schema is
   owned by **SPEC-0028** (the task-schema spec; existing parser, no new store). A card with no
   `imported_from:` is native and unaffected by the gate below.

2. **Premise-verify intake pass BEFORE B3 "run real tasks" (SPEC-0166).** Before an `imported_from:` card
   can be dispatched, a cheap CODE-READ-ONLY intake pass re-checks each card's PREMISE against today's code
   (the Stage-1 anti-reinvention grep, moved to the cheap batch moment) and writes `premise: verified |
   already-done | stale` via the existing `task update` route. **Dispatchability rule (code-enforced):** an
   `imported_from:` card whose `premise:` is not `verified` is NOT dispatchable — `dispatch` and the picker
   refuse with the exact next step (run the intake pass). Routes for the other verdicts (an imported card is
   `ready`, not in-progress, so `task close` is not reachable): `already-done` (the whole card's outcome
   already exists in today's code) → `task update --status wont-do`; `stale` (scope partially matches / a
   moved-or-retired subject → re-scope, not close) → `task update --status parked`. This EXTENDS the
   reactive pre-claim refusal (SPEC-0133) to the proactive intake seam. **So no imported card reaches a
   worker for a full 9-stage run on a premise that no longer holds.**

3. **Product-card owner-gate across the whole migration window (SPEC-0167).** "Migrating the methodology"
   must not silently become "changing the product." The migration WINDOW is this project's own active
   brownfield-onboarding plan (the `real-project-integration-onto-v2-phased-migration-` class — Branch B)
   while it is `executing`; the plan's own status IS the window (no separate flag). While that window is
   open, `dispatch` of a PRODUCT-touching card (mechanical fail-closed test: any `expected_touch` reaching
   a path outside the governance/docs set — `tasks/ specs/ decisions/ plans/ patterns/ lessons/ scenarios/
   *.md graph/ events.jsonl`; when in doubt → product-touching) REFUSES unless the card carries
   `product_dispatch_owner_ack: <ref>` (an optional field set via the existing `task update` route). The
   refusal names the exact token to add. A governance-only card, or a product card outside a window, is
   unaffected. **So nothing product-touching ships in a migration window without the owner's explicit
   per-card say-so.** (NB — the heavier SPEC-0130 whole-window *quiesce* option is DEFERRED to followup
   `fu_5713357f3a9a`; do not treat it as. The SHIPPED safeguard is this per-card owner-ack gate.)

**Net retirement wording:** the old Branch-B path implied imported cards flow straight to B3 "run real
tasks." They do NOT. An `imported_from:` card is not dispatchable until the premise pass marks it
`verified`; a product-touching card is not dispatchable in an open migration window without
`product_dispatch_owner_ack:`. Both gates are code-enforced in `dispatch` — this runbook only describes
them.

### B2-tests — Leg 3: the tests leg (spec→test mapping + tiered gap closure, ledger-carried)

> **Born:** the loud-failure test-building doctrine (`SPEC-0165`, active on main from),
> plan `loud-failure-principle-one-tripwire-per-silently-b`. Fetch: `<engine>/bin/yitc-v2 -C <path>
> graph query --kernel SPEC-0165`.

A migration stands up TWO of the three legs already: **leg 1 = spec-extraction** (B2 stands up specs
for the load-bearing rules) and **leg 2 = module→spec coverage admission** (the §B5 revizia confirms
every load-bearing surface has a spec). What was MISSING is **leg 3 = spec→test mapping + gap
closure**: nothing proved a normative rule has an executable twin, and consumer test-debt cards were
parked non-gating and never returned to (boomrocket 131/1271, aiseller 240/1719 land-wired but with
NO rule→test traceability). Leg 3 closes that — under the loud-failure principle, NOT as a
tests-for-everything sweep:

- **The principle (the whole leg in one line — `SPEC-0165`):** a rule needs a test ONLY if it can
  break **silently**; then it gets exactly ONE **differential tripwire** that makes the breakage
  loud; if the rule already breaks **loudly** (a named existing mechanism fails closed BEFORE the
  harmful action — verb refusal, land-verify failure, schema/type error, startup crash), no test —
  record a **contract-complete waive** instead (mechanism + pre-harm fail point + covered path +
  a representative violating input; plus class, rationale, approver, recheck trigger). "Someone
  would notice" is never loud. Frozen/descriptive specs are not rules — no tripwire, nothing to map.

- **TIERING BOUND — tier-1 upfront at migration, the rest via per-AC discipline (do NOT map the
  whole corpus here).** Map ONLY the **tier-1 dormant-risk zones UPFRONT at B2**, walked in cost-of-
  silent-breakage order: **money → outbound mutations → isolation/access → data mutations →
  background jobs** (boomrocket: money, outbound messaging; aiseller: tenant isolation, access
  control). Every tier-1 normative rule leaves B2 with a named tripwire test OR a contract-complete
  waive in the project's ledger. Everything BELOW tier-1 is NOT mapped in a big upfront sweep — it
  accrues through the **per-AC channel** (``): each NEW task's acceptance criteria name a
  test-or-waive as tasks flow, so coverage grows with work instead of as a migration mega-batch.
  This tiering IS the walk-order bookkeeping of the principle, not a second rule.

- **LEDGER = the carrier artifact (one per project, F4-shaped — extend, don't fork).** The
  rule→tripwire/waive links live in a per-project ledger doc (the shape of boomrocket's F4
  module→spec coverage-admission ledger — reuse it, P1 F1). Role constraint: the ledger stores
  ONLY rule→tripwire/waive links + the waive contracts. The **links are derived bookkeeping**
  (re-derivable from specs + tests); the **waive contracts are the ledger's one class of OWNED
  unique content — the ledger is the single waiver carrier** (waiver facts live nowhere else, so no
  parallel-truth split). The **spec** stays the rule's normative home; the **test** stays the proof.
  Kernel exemplar granularity + the row standard: `specs/yitc-v2-rule-test-ledger.md` (owner-accepted
  2026-07-19).

- **Extend-before-create (one post per rule).** Before writing a new test file, extend the rule's
  existing suite; a new standalone file is justified only by a genuinely NEW rule. Each tripwire is
  **differential** — it proves the rule by a failing input anchored to the SPEC's text (or an
  explicit owner clarification), never to current code behavior. Happy-path multiplication adds
  weight, not loudness.

- **Confirmation, not first-count (leg 3 ↔ §B5).** The §B5 revizia four-axis roll-call (docs ↔ code
  ↔ scenarios ↔ **tests**) CONFIRMS the tier-1 ledger is complete — it is not where the tests leg is
  first done (same B2-counts / B5-confirms discipline as leg 1's load-bearing-surface walk). Frozen
  specs are exempt from the tests axis; dangling tests (a test with no rule) surface there too.

- **Scope — future migrations; retro rides cross asks.** This leg applies to migrations going
  forward. Retro application to ALREADY-migrated consumers (boomrocket, aiseller) is NOT part of a
  new migration's runsheet — it rides the owner-gated consumer `cross` asks (plan card ``),
  not this leg.

### B2b — Sandbox-clone trial rehearsal (heavy/live brownfield: REHEARSE the whole cutover before the one-shot real run)

> **Born:** aiseller gate-4, 2026-07-11 (owner-directed the same day: «такой триал нужно в ранбук
> вписать»). For a HEAVY v1-incumbent migration (live prod + multi-user + host coupling) the
> quiesce/bootstrap/transform runsheet is a ONE-SHOT operation — rehearse it END-TO-END on a
> sandbox clone BEFORE the real morning, as the plan's SPEC-0035 `trial` stage. Method home:
> `patterns/trial-methods.md` §Mode C (sandbox-clone rehearsal); this section is the
> migration-specific instantiation.

- **Build the sandbox:** `git clone` the target repo + copy untracked load-bearing state (`.yitc/`,
  hooks; `.env` as REDACTED shape only — SPEC-0099) + COPIES of every host file the runsheet edits
  (registry.yaml, workspace.yaml(s) — including EVERY collaborator's own workspace/enumerator
  files — crontab dumps for every user). Production untouched by construction.
- **Execute the ENTIRE runsheet against the clone, in order** — including the REAL governed verbs:
  consumer-locus `session start` → `--help` scan → `-C <clone> init` (its guards fire for real:
  legacy-surface hard-fails, scaffold withholds, churn auto-untrack) → ops-contract wiring (the
  wired clone files BECOME the real-run templates) → vendor-adapter/neutral-home transform →
  v1-carrier sweep → post-sweep re-init (delivers withheld scaffolds; re-seeds archived scaffolds)
  → a worktree+land cycle → B3.1 well-formedness + `graph build`.
- **Record per step:** journaled evidence (`trial_run` event), wall-clock timing (feeds the
  real-run day budget), and a VERIFIED undo — execute the undo on the clone at least once
  (git-revert drill + restore-from-copy).
- **Produce the two trial artifacts:** the CONVERGED runsheet (the plan's quiesce/bootstrap section
  updated in place) + the mechanism-transition map (per mechanism: added / removed /
  transferred-where / interaction edges — what breaks what if ordered wrong).
- **Converge:** fix-first fold every surfaced gap → external ad-hoc pass over map + runsheet →
  absorb → targeted re-pass; exit on the SPEC-0035 rule 5 floor + owner judgment.
- **Why it earns its cost (the aiseller evidence):** one afternoon of rehearsal surfaced a
  CRITICAL missed live-writer (a collaborator's OWN v1 night-cycle reading HIS workspace file —
  the registry flip does not touch it), three verb-ordering gates that would each have stalled the
  real morning, a scaffold-delivery ordering (security-audit withheld until the v1 findings path
  retires), and the timing truth (mechanics = seconds; content = the budget). Every one of those
  found at 08:00 on migration day = a stalled one-shot window.

### B3 — Phase 2: run real tasks on the SAFE default; two-gate proof

Real project work through the 9 stages, landing in the project's main. **Precondition (§B2-import-safety):
an `imported_from:` card is only dispatchable here once its premise pass marks it `verified` (SPEC-0166),
and a product-touching card needs `product_dispatch_owner_ack:` while this migration plan is `executing`
(SPEC-0167) — both code-enforced in `dispatch`, so an unverified or unacked card is refused before it
reaches these gates.** **Two-gate proof:** gate 1 = a low-risk smoke task (validates lifecycle FIT); gate
2 = an intentionally REPRESENTATIVE task (the hard part of adoption). NB — for the legacy-brownfield case (no v1 incumbent, e.g. ai-gateway) `realized` does NOT
release the distribution-platform hard-stop; that is the v1-incumbent gate-2 (Boomrocket).
**The two-gate proof validates the LIFECYCLE fits in-project — it is NOT migration-complete on its own.
Completion is the §B5 gate below; do not mark the migration plan `realized` at B3.**

#### B3.1 — Post-first-task consumer well-formedness check (run RIGHT AFTER the first real consumer task)

The first real task is also the first moment the consumer's BOOTSTRAP is exercised end-to-end — so run a
quick well-formedness pass before moving on. It catches scaffold drift (an old bootstrap that predates a
current-init change, or a file an earlier step archived without re-seeding). Checks (all read-only except
the re-seed fix):

- **All current managed scaffolds present.** The authoritative set is the init managed-list (`bin/lib/init.py`
  — currently `MEMORY.md`, `.gitattributes`, `events.jsonl`, `yitc-ops.yaml`,
  `.no-v1-hooks`, `lessons/README.md`, `patterns/.gitkeep`, `graph/.gitkeep`, `.gitignore`). (`yitc-verify.yaml`
  is RETIRED —; the land-verify home is the carrier `yitc-ops.yaml` `verify.layers` section.) Diff the
  consumer's root against a PEER v2 consumer to spot a missing one fast. **Fix a missing scaffold by
  re-running the idempotent `bin/yitc-v2 -C <consumer> init`** — it re-seeds only what's absent (it does
  NOT clobber existing files). Real incident: trend-finder lost `MEMORY.md` because the v1-corpus archive
  step `git mv`'d the v1 one to `v1-archive/` and no v2 `MEMORY.md` was re-seeded — every other consumer had it.
- **No RETIRED surface lingering.** A consumer bootstrapped before a kernel cutover can carry a now-retired
  file — notably `CROSS-TASKS.md` (the per-repo cross log, RETIRED at the cutover; live surface = the
  shared coordination log, `cross request`/`cross inbox`). Current init does NOT seed it, and `-C <consumer>
  init` now ACTIVELY SWEEPS a lingering born-empty / tombstone one (X-0110 — it removes the file,
  emits a `retired_surface_swept` event, and surfaces it in the init output). A CONTENT-BEARING one is NOT
  swept — it trips the hard-fail guard, which blocks init until the operator migrates it (`cross
  request` / task) or consciously waives (`--waive-legacy-cross-tasks "<reason>"`).
- **The land-verify is REAL, not still waived.** After the first task that touches code+tests, confirm
  `yitc-ops.yaml` `verify.layers` declares a per-layer `command:` (not the born section `waiver:`) — i.e.
  the consumer's `land` actually runs its suite, one layer at a time (see §B3.2 below for the harness shape).
- **Graph is clean.** `bin/yitc-v2 -C <consumer> graph build` → `errors=0`.

#### B3.2 — The hermetic verify harness must stand up ALL runtime deps the suite touches (not just the DB)

When wiring a consumer's `yitc-ops.yaml` `verify.layers` per-layer `command:` (the hermetic harness — see §B3.1 + the verify
prompt in §B2), the test compose MUST bring up **every runtime dependency the suite actually exercises**,
discovered from the app's config / `conftest` (DB **AND** any cache / queue / broker, e.g. redis), not just
the database. Real incident (trend-finder): the first verify run failed 5 auth tests purely because
**redis** (the auth rate-limiter backend) was missing from the test compose — the suite needed it, the DB
alone was not enough. Still hermetic + concurrency-safe: every service on a per-run-unique compose project /
network, no host ports, unique-per-run DB name (so parallel worker `land`s never collide).

### B4 — Phase 3 (OPTIONAL): qualify a cheaper model default by an in-project bench

Not a migration-completion gate — run only if a cheaper project default is worth pursuing. (Migration
COMPLETENESS is the §B5 criterion below — not this bench, and not the two-gate proof alone.)

### B5 — Migration-complete gate: when the project is YITC-ready (gates `plan realized`)

> **The completion criterion (owner directive 2026-06-24). A migration is NOT "done" at the two-gate
> proof.** "Migrating a project" is not only installing the methodology — it is TRANSFORMING the
> project's existing documents + code INTO the governed corpus. A project is **YITC-ready** only when
> ALL THREE facets hold:

1. **All project information is in the graph.** Every existing project document (design notes, READMEs,
   the product charter, API / usage docs) is TRANSFORMED into the corpus — `CHARTER.md` + `specs/` +
   `scenarios/` + `lessons/` — and linked in the graph. No project knowledge lives only as prose outside
   the graph. **Spec naming cue:** every spec is a `SPEC-XXXX.yaml` file — the SINGLE spec identifier
   shape; do NOT invent parallel `INVARIANT-*`/`CONFIG-*`/`FSM-*` spec artifacts (a v1-shaped trap — they
   are silently graph-invisible). An invariant/config/FSM is spec CONTENT, not a separate prefix — see
   SPEC-0005 §Identity for the rule (real incident: the boomrocket migration, X-0195/X-0197).
2. **No code without documentation.** Every **load-bearing** code surface is governed by a spec (or a
   `scenario`) via the `implements` graph edge — no orphan load-bearing code. (`graph build` reports the
   code→spec coverage; walk the file's symbols against it.) Genuinely-trivial infra / glue may stay
   uncovered, but an existing surface a real consumer depends on IS load-bearing, NOT "grow on incident".
3. **A final full revizia + triage system-state pass — run `-C` against the consumer.** This means the
   **FULL T1–T8 system-inspection sweep** — ALL 8 themes (T1 doc↔code coherence+coverage · T2
   instruction-fidelity · T3 AI-execution · T4 outcome/cost · T5 meta-loop · T6 operational-integrity ·
   T7 anti-complexity/bloat · T8 adoption), the migration BASELINE (not a rotated monthly subset), each
   run via `patterns/inspection-triage-launch-runbook.md` + the per-theme lens-checklists and emitting
   **`inspection_completed`** — **NOT** the lighter **weekly operational-hygiene tier** (parking-lot /
   blocked-queue / GC checks): that tier is NOT the revizia, and a session that runs only it (0
   `inspection_completed` events) has NOT done the migration-complete revizia. Apply the
   kernel-owned inspection lenses (`patterns/inspection-criteria-roster.md`) + the triage sweep so they
   target the CONSUMER's OWN graph / journal / corpus: `<engine>/bin/yitc-v2 -C <consumer> graph build`
   (the coverage walk for facet 2) + `<engine>/bin/yitc-v2 -C <consumer> triage` (the un-routed-capture
   sweep over the consumer's own journal). The **PRIMARY track is run by the project's OWN in-session
   author in a read-only ASSESS posture** (it inspects via `-C`; it does NOT write while assessing) — NOT
   a detached kernel/operator session run apart from the project. **INDEPENDENCE does not come from the
   primary track's session location**; it comes from the SECOND track — the **external, different-provider
   BLIND pass** that re-grades the same system without seeing the primary verdict (the dual-track the
   §Frictions gate-1 lesson generalises: *the in-session author + an independent blind external pass*).
   **`assessor != fixer` is a ROUTING discipline, not a session-location rule** — a finding the assess pass
   surfaces is never silently self-fixed; it is routed BY REALM: a **product/coverage gap → the consumer's
   OWN `-C` tasks** (the consumer's own Build session does the `-C` fix), a **kernel/methodology gap → the
   kernel via the cross-log** (`cross request`). This is the **write-posture discriminator** (SPEC-0084 §5):
   a direct `-C` write is in-bounds ONLY from the consumer's own `-C` Build write-posture; an assessor's
   finding routes to its realm's queue, never a direct cross-repo write. The lenses + the `triage` verb are
   kernel-owned and PROVIDED to the consumer (like the handbook), but the data they read and the results
   they produce live in the consumer repo. A system-state analysis confirming the
   migrated project is coherent and carries no un-routed deviations or coverage gaps — the gate that
   SYSTEMATICALLY catches facets 1 + 2; it **reuses existing kernel machinery — no new mechanism**
   (anti-complexity §P1).

**Reconciling with anti-complexity (the seed-3-specs reading was too thin).** The minimal seed backbone
(B2: a CHARTER + the load-bearing-rule specs) is for bootstrap SPEED — get the machinery running. Full
document-transformation + load-bearing coverage + the revizia is the migration COMPLETENESS bar. "Grow on
incident" governs genuinely-NEW surfaces added later — NOT documents or load-bearing surfaces that ALREADY
exist at migration time (those get covered now). So **`plan realized` for a migration is gated on this B5
criterion**: the two-gate proof (B3) proves the lifecycle fits; B5 proves the project is fully governed.
(Greenfield, Branch A, has no existing documents to transform, so its "ready" bar is facets 2 + 3 over the
code it authors — same completion idea, smaller surface.)

**First instance (ai-gateway gate-1, 2026-06-24): B5 NOT yet met.** The seed-3-specs backbone left the
billing-READ API (`/api/billing/summary` + `/api/billing/calls` — a real dev-dashboard contract) and the
`DEFAULT_PRICING` unknown-model fallback (the mis-bill subject) UNCOVERED, authored no `scenarios/`,
and did not transform the project's other docs — so the migration plan is held at `executing`, NOT
`realized`, until B5 is met (the consumer-side coverage work is filed as `-C` ai-gateway tasks).

### B5-check-1 — Post-parallel-batch cross-interaction review (a PRE-completion safeguard — run before declaring B5 complete)

> **Born:** boomrocket gate-3, 2026-07-01. **Not post-completion cleanup — a gate that must run BEFORE
> `plan realized`.** After you dispatch a PARALLEL batch of fixes across OVERLAPPING modules, run an
> **external-auditor (SPEC-0036) cross-interaction review** of the landed batch AS A WHOLE — do not treat
> the batch as done just because each task landed green.

- **The trap it catches:** individually-green tasks can CONFLICT when combined. Per-worktree hermetic
  verify checks each task in ISOLATION, so a **cross-interaction** defect — two workers that each edit an
  overlapping surface in a locally-valid but jointly-inconsistent way — passes every per-task gate and
  surfaces only later.
- **The concrete incident (fingerprint `parallel-dispatch-diverges-alembic-heads`):** boomrocket shipped
  **19 parallel fixes across payment / tickets / buyback**; two of them each added an Alembic migration off
  the same parent → **divergent migration heads**. Every per-worktree verify was green; the conflict slipped
  all the way to **deploy pre-flight** (where `alembic upgrade` refuses multiple heads).
- **The step:** whenever a migration (or any batch of ≥2 tasks touching overlapping modules) dispatches
  workers in parallel, after they all land run **one external-auditor pass over the COMBINED diff** asking
  specifically for cross-interaction conflicts — divergent migration heads, two writers of the same
  config/schema/interface, duplicated or contradictory edits to a shared surface. Per-worktree verify does
  NOT cover this; the whole-batch review is the only place it is caught before deploy. Route any finding by
  realm (a product conflict → a consumer `-C` task; a kernel gap → `cross request`).

**Dispatch-liveness while the batch runs — a long SILENT worker is the EXPECTED shape, not a death
(aiseller gate-4, 2026-07-12; X-0338).** Two traps bite exactly during a migration batch, and both push a
Controller toward a WRONG force-recovery:
- **A silent stretch is normal.** A worker blocked in a foreground `land` / audit (or queued for a
  verify-admission slot) emits nothing for minutes BY DESIGN. Silence is not evidence of death.
- **The fleet read is blind to a CONSUMER-locus worker.** `journal query --fleet-verdict` returned
  **CONFIRMED-DEAD (`silent_stop`)** for a worker that was ALIVE and landing a consumer task — because a
  kernel-dispatched worker whose work rides the **consumer** journal is invisible to the kernel-journal
  staleness check (3 false reads in one day; `dispatch --watch` would wake-false-dead every tick). A
  migration batch is made almost entirely of such cards. → **Do NOT treat fleet-verdict as a liveness oracle
  during a consumer migration**: confirm against the CONSUMER journal (and the process) before force-
  recovering, or you discard live work. (Kernel fix routed — fleet-verdict should fold the `-C` consumer
  journals of registry `yitc_v2` projects, which it already enumerates.)

### B5-check-2 — Migration-completion checklist: v1→v2 leftover-tail classes (clear each BEFORE `plan realized`)

> **Born:** boomrocket gate-3, 2026-07-01 — these four classes had to be hand-cleaned across a full day
> because nothing named them. Codified here so the NEXT migration confirms them upfront instead of
> re-discovering them. Walk this list as part of the B5 gate; a migration is not complete while any row is open.

- [ ] **BACKLOG-import task STUBS still pointing to `BACKLOG.md`.** The v1→v2 backlog import can leave task
  cards whose body/`from:` still references the retired `BACKLOG.md` instead of the governed task/spec — find
  them (`grep -rn BACKLOG.md tasks/ specs/`) and re-point or close each stub.
- [ ] **Stale registry `ai_team.enabled` flag.** A migrated project's `registry.yaml` entry may still carry
  the v1 `ai_team.enabled: true` (or an `ai_team:` block) — a v2 consumer is governed by `methodology: yitc_v2`,
  so retire the stale v1 flag.
- [ ] **Retired per-repo `CROSS-TASKS.md` needs a TOMBSTONE.** The per-repo cross-log was superseded by the
  kernel-owned shared coordination store (SPEC-0079 → SPEC-0086 cutover). A migrated repo that still carries a
  live `CROSS-TASKS.md` must have it TOMBSTONED (marked retired, pointing at the `cross` verbs), not left as a
  live-looking log.
- [ ] **Deploy path missing its migration step.** A v2-native deploy command must actually APPLY DB
  migrations (e.g. `alembic upgrade head`) — a migrated deploy path that dropped the v1 migrate-on-deploy step
  will silently ship code ahead of the prod schema (the boomrocket deploy-pre-flight near-miss; see kernel
  X-0145). Confirm the `deploy:` command applies migrations before `plan realized`.
- [ ] **Imported spec corpus stranded at `proposed` with PHANTOM activation owners.** A v1→v2 spec import
  can land the whole corpus at `status: proposed` carrying an `activation_owner_task` that points at a task
  which does not exist in the consumer (typically a kernel-range id copied along with the spec). Such a spec
  is stranded by construction: a `proposed` spec **governs nothing** (SPEC-0005 §4 — non-authoritative), and
  `proposed → active` is written ONLY by that owner task's `task close`, which can never run for a task with
  no card. So the corpus LOOKS migrated while governing nothing, indefinitely. **Every imported spec must
  reach a TERMINAL honest status — one of exactly two routes, per spec:**
  1. **ACTIVATE** — retarget `activation_owner_task` to a **real LOCAL task** that carries a genuine
     **adoption probe**, and let that task's `task close` perform the activation (the sole sanctioned writer
     of `proposed → active`, GRAPH §Spec lifecycle). Never hand-edit `status: active` — an active spec with
     no activating close is a drift-#10 / P5 signal.
  2. **RETIRE / WITHDRAW** — the honest terminal for a spec the consumer will not actually adopt
     (`spec edit <SPEC>`). A withdrawn spec is a clean outcome; a `proposed` one is not.
  **Finder:** `bin/yitc-v2 -C <repo> graph conformance` emits a report-only `ADVISORY (SPEC-0005 §4/§5 …)`
  row per phantom-owner spec (report-only by design — the route is a semantic choice no check can make for
  you; it never blocks a land). **Note the boundary:** a spec with NO `activation_owner_task` at all is
  grandfathered-VALID (SPEC-0005 §5, no retroactive backfill) and is not flagged — this row is about a
  PRESENT-but-unresolvable owner. (Born: boomrocket F2a import, 2026-07-16 — 36 specs owned by nonexistent
  /; kernel X-0437, sibling of the X-0433 shadowing class.)
- [ ] **v1 liveness/freshness monitor retired WITHOUT proven like-for-like v2 coverage.** A v1 watchdog
  (e.g. `watchdog.sh`) must not be retired until v2 reads the SAME live signals via the project's freshness
  adapter, proven by an induced real-miss catch (trend-finder). The kernel monitor returning `none`
  (no declared adapter) reads as **NON-ADOPTED, not coverage** — `none` is not a pass. Confirm the v2 monitor
  caught an induced miss before marking the v1 monitor retired.

### B5-check-3 — ABOVE-KERNEL INFRASTRUCTURE CHECKLIST (the host + per-collaborator surfaces; verify-or-create EACH)

> **Born:** aiseller gate-4, 2026-07-12 — the FIRST multi-user migration (owner-directed enrichment;
> evidence = that day's frictions, `X-0333`..`X-0337`). **Why it exists:** B5-check-1/-2 look INSIDE the
> repo. A migration also rests on surfaces that live ABOVE the kernel — on the HOST and in each HUMAN
> collaborator's own account — and **none of them is derived from anything**: each is a hand-made COPY that
> no mechanism refreshes and that is **invisible from the owner's own session**. aiseller shipped a
> technically-complete migration whose second collaborator still could not run `/work` at all.
>
> **Two homes this section DELEGATES to (cite, don't restate):** the per-person PROVISIONING how-to (OS
> user, registry `users.<name>` entry, `<provider-config>` wiring, secrets, the mandatory **verify-AS-the-user**
> drill) lives in **`patterns/onboarding-a-person-onto-yitc.md`**; the steady-state host surfaces
> (coordination store / registry / router / auto-committer, each with its OWNER label) live in
> **`patterns/host-server-surface-contract.md`**. THIS section is the **migration-completion GATE** over
> them: for THIS migrated project and EACH of its human collaborators, has every row been verified — or
> created?
>
> **The one rule that makes the whole list work: VERIFY AS THE USER, not as the owner.** Every failure below
> was invisible at "the files are in place" and surfaced only under `sudo -u <user> …`. A row is green only
> when the real operation ran, AS that human, and worked.

Walk one column per human collaborator of the migrated project (`registry.yaml` → `users.*.projects`):

- [ ] **1. Registry entries + the validate differential.** The project entry (`methodology: yitc_v2`) AND a
  `users.<name>` entry per collaborator (`projects` + `allowed_commands` — this IS what `/work` resolves
  access from; a missing entry → `/work` refuses). Run the host `validate-registry.sh` and read it as a
  **DIFFERENTIAL** — a pre-existing RED unrelated to this migration must be recorded as such, not "fixed"
  blind, and not allowed to mask a new one. **`active:` is OVERLOADED — enumerate its READERS before you
  flip it** (X-0337): the v1-quiesce meaning (`SPEC-0130`) is NOT the only one — the `/start` picker lists
  only ACTIVE projects, and `generate-the AI provider-md.sh` gates a new collaborator's generated `<vendor-adapter>.md` project
  list on `local_active == true`. Flipping it for quiesce made the live flagship consumer INVISIBLE in
  `/start` for BOTH humans. (This is the §B2 «reconcile every registry-derived surface» rule extended from
  derived VIEWS to independent READERS with their own semantics.)
- [ ] **2. Guard hooks — and WHOSE `settings.json` wires them** (X-0335). A claim that "the
  slash-command-guard / scope-guard hooks permit this flow" is **false unless it names the USER whose
  settings.json wires them**. Hooks in `<host-home>/<provider-config>/settings.json` are dev-user-scope and are **never
  loaded in a collaborator's session** — that session loads `/home/<user>/<provider-config>/settings.json` (which may
  still wire the collaborator's OWN v1-platform hooks), and there is no managed-settings layer above them.
  Verify the hooks that actually fire, per user.
- [ ] **3. Per-user ENTRY SKILLS are CURRENT — `/start` AND `/work`, for EVERY collaborator** (X-0333; the
  owner cue this checklist was created to carry, `fu_9596cebd2ec7`). The entry skills are **per-user COPIES
  that silently go stale** — nothing regenerates them. **VERIFY (never assume)** that each collaborator's
  `~/<provider-config>/commands/` carries the CURRENT `/start` + `/work`; **create the missing one**. Real find: <collaborator>
  carried a **2026-04-14 v1-era `start.md`** (Build/Review picker, team_mode routing, zero mention of
  `yitc_v2` / `-C`) and had **no `work.md` at all** — a headless `/work` as <collaborator> returned literally
  `Unknown command: /work`, so the surfaces the migration cards NAMED were not the ones his session LOADED.
  Run it AS the user, headless. **This row exists so future FORKS and new-project migrations do not
  rediscover it.**
- [ ] **4. Engine binary + sandbox dirs allowlisted in EACH collaborator's `settings.json`** (X-0334). The
  consumer flow's one NON-SKIPPABLE step is `<engine>/bin/yitc-v2 -C <project> session start` — and the
  engine path sits OUTSIDE a cwd-scoped permission sandbox, so without an explicit
  `permissions.allow` entry it hits an approval gate on exactly the step that cannot be skipped (<collaborator>'s
  `permissions.allow` was **empty**; his session start could not execute → no read-order echo, no anchors).
  Allowlist the engine binary + the sandbox dirs the `-C` session reads, per collaborator.
- [ ] **5. Crons — for BOTH/ALL users.** Enumerate `crontab -l` **as every user**, not just the owner: a
  collaborator's OWN v1 night-cycle / enumerator can keep reading HIS workspace file and writing into the
  migrated project long after the registry flip (the registry flip does not touch it — the §B2b rehearsal
  caught exactly this). Disable/redirect each live v1 writer (the §B2 quiesce rule, applied per user).
- [ ] **6. Backup / offsite coverage — INCLUDING the pre-migration packet.** «It is backed up» is a claim to
  **verify against the backup script's actual match patterns**, never to infer from a directory's name. Real
  find: the pre-migration snapshot packet was asserted to live in an offsite-covered home, but
  `offsite-backup.sh` rsyncs only pattern-matched top-level tarballs and its `<host-home>/` sync carries
  `--exclude=backups` — the repo+tag DID travel offsite, the `.yitc`/`.env`/untracked tar did NOT. Confirm
  the kernel repo itself is covered too (a captured gap in its own right).
- [ ] **7. nginx / systemd.** The unit + vhost that actually serve the migrated project are host-territory
  and survive the migration untouched — confirm they point at the (possibly re-homed) repo path, and that a
  `§B0` carve or deploy re-home updated every hardcoded path. `nginx -t` before any reload.
- [ ] **8. Secrets ACL matrix — named-user ACLs when the GROUP over-grants** (X-0336). Group membership is
  the wrong granularity as soon as a second human appears: on aiseller, `<host-home>/secrets` (`drwx------
  dev:dev`, <collaborator> cannot traverse) plus `aiseller.env` (`0600 <collaborator>:<collaborator>`, dev cannot read) locked **BOTH**
  actors out of an `env_file:` used by 5 compose services — while OTHER collaborators (<collaborator-2>, <collaborator-3>) sit
  in group `dev`, which over-grants them. Build the explicit matrix (who must read WHICH secret) and grant
  it with named-user ACLs. Related: a project's own scripts may HARDCODE the shared dev-only secrets path
  instead of the per-user copy (the person-doc §Frictions gotcha).
- [ ] **9. MEMORY onboarding-seed — the SEEDER owns its commit.** The SPEC-0147 onboarding-station pointers
  seeded into the consumer's `MEMORY.md` must not be left UNCOMMITTED on consumer `main`: a dirty
  `MEMORY.md` sits in `land`'s non-bookkeeping set and **wedges every later land in that repo** (the X-0274
  class, hit again from the SEED side on migration day). The CONSUME side self-commits; confirm
  the SEED side did too, and that consumer `main` is land-clean before you hand the project over.

**Also generalised from gate-4 — two craft rules that belong with the gates they bite at:**

- **The B5 blind-track external pass needs its evidence flags ON.** A `-C` blind revizia (`audit adhoc`)
  run WITHOUT `--read-corpus` / `--sweep-file` **ABORTs on no-evidence** — the auditor is forbidden to read
  the repo and nothing was inlined — burning a full auditor invocation and reading as a spurious
  track-divergence. The fix already exists but is not the default: **at the §B5 facet-3
  completion gate, always pass `--read-corpus` + a mechanical `--sweep-file`.**
- **A kernel-governed consumer DEPLOY still needs a CONSUMER task carrier for its live-probe.** The governed
  `liveprobe` verb keys on a **consumer** task YAML carrying the per-change probe assertion. A
  migration-day prod deploy governed by a KERNEL task has no consumer task to key on, so the verb cannot
  run and live evidence degrades to hand-run healthz probes. When a deploy is kernel-governed, put the
  live-probe assertion on the deploy card itself (or file the consumer carrier task) — decide it at cut
  time, not at the deploy seam.


---

> **Split note (per SPEC-0120 §3 per-doc size band).** The accumulated **Frictions log**
> (append-live, newest last) + the per-migration **meta-analysis** passes now live in the sibling
> `patterns/onboarding-onto-yitc-frictions-log.md`. Append every new onboarding friction THERE; this
> file keeps the runbook proper (Shared core + Branch A/B + the B5 completion gate & checks).
