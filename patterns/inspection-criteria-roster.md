---
name: inspection-criteria-roster
class: reference
sourced_from: <durable artifact> (drain-at-realize rule — a plan drains durable content to a stable home before terminal) + deviation `living-criteria-home-hosted-in-realized-terminal-plan` (the grounding incident — the inspection living-criteria were homed in an FSM plan that can reach realized/terminal) + owner-directive 2026-06-08 (option A — stand up the stable pattern home now so SPEC-0057 points at a real target) + SPEC-0057 (the inspection construct — the identity home this roster serves; §3 living-criteria home, §9 cadence model) + SPEC-0034 §realized (the drain-at-realize gate this home is the drain TARGET for) / plan unify-revizia-all-checks-under-one-construct-singl (the unification drain — absorbed the QUEUE.md §Re-review-triggers checks as roster rows + drained the realized roster plans' living-home role into this single map; QUEUE/runbook now POINT here)
applies_to: the freshness-hashed LIVING CRITERIA of the inspection roster — the `CADENCE` cadence values (parsed by `bin/lib/inspection.py parse_cadence`), the **operational-hygiene weekly checklist** (`inspect record --tier weekly` hashes it), and the **per-theme lens-checklists** (`inspect record --theme T<n>` hashes each) for **T1, T3, T7** — **T2, T4, T5** are the co-equal PART 3 (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`, SPEC-0120 split) **T6, T8** the co-equal PART 5 (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`) **T9** the co-equal PART 4 (`patterns/inspection-criteria-roster-portfolio-observation.md`, SPEC-0120 split) and **T10** the co-equal PART 6 (`patterns/inspection-criteria-roster-real-work-observation.md`, SPEC-0120 split), served and hashed there. This is PART 1; the umbrella NAVIGATION MAP (check → theme → cadence → how-to-run → rule-home, across the continuous-reflex / system-inspection / apex / consumer-local tiers) is the co-equal companion `patterns/inspection-criteria-roster-navigation-map.md` (SPEC-0120 byte-axis split), and the run-mode + cross-theme method + foundations + architecture-drift lens are PART 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split). This pattern is the durable HOME the criteria drain INTO; it is a doc home, not a mechanism/verb/store/rule (each rule it serves homes elsewhere — SPEC-0057 construct, SPEC-0034 drain-gate, SPEC-0055/0056 triage — it cites, it does not restate; SPEC-0005 rule 8 one-home). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — the living criteria (part 1: cadence · operational-hygiene · the T1 / T3 / T7 lens-checklists)

> **What this IS:** the freshness-hashed **living criteria** of the inspection roster — the
> `CADENCE` cadence values, the **operational-hygiene weekly checklist**, and the **per-theme
> lens-checklists for T1, T3, T7** (`bin/lib/inspection.py` hashes these three as the `criteria_ref` /
> `--tier weekly` freshness subjects, SPEC-0057 §6). The umbrella **navigation map** — one row per
> recurring check (check → theme → cadence → how-to-run → rule-home), across the continuous-reflex /
> system-inspection index / anti-complexity-apex / consumer-local tiers — is the co-equal companion
> **`patterns/inspection-criteria-roster-navigation-map.md`** (SPEC-0120 byte-axis split). The
> run-mode + cross-theme method + foundations + architecture-drift lens are the co-equal **part 2**
> (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split), and the
> **T2 / T4 / T5** lens-checklists are the co-equal **part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split), **T6 / T8** the co-equal **part 5**, the **T9** lens-checklist the co-equal **part 4**
> (`patterns/inspection-criteria-roster-portfolio-observation.md`,
> SPEC-0120 split) and **T10** the co-equal **part 6** (`patterns/inspection-criteria-roster-real-work-observation.md`). It is a **non-FSM
> pattern** — it has no `draft→realized`
> lifecycle, so it can host LIVING/durable content indefinitely without ever becoming a terminal
> carrier. This is deliberately the home a PLAN's living criteria **drain into** at the plan's
> `realized` transition (the drain-at-realize rule, **SPEC-0034 §realized**). It introduces **no new
> mechanism, verb, store, or rule** — it is the durable doc destination, nothing more. Each rule it
> maps homes elsewhere (cited inline, never restated — P5 / SPEC-0005 rule 8).

> **Single-home invariant (plan `unify-revizia-all-checks-under-one-construct-singl`):**
> this roster is the SOLE living list of recurring checks. `QUEUE.md §Re-review triggers` is a POINTER
> here (no parallel list); `patterns/inspection-triage-launch-runbook.md` READS this roster (it does
> not re-host it); the realized roster plans (`inspection-list-refresh-2026-06-fresh-roster-lense`,
> `inspection-revizia-concept`) carry only trial/calibration HISTORY (their living-home role drained
> here). `SPEC-0057` stays the CONSTRUCT definition and points here; this roster never restates the
> construct rules.

> **The umbrella navigation map (check → theme → cadence → how-to-run → rule-home) → companion**
> (`patterns/inspection-criteria-roster-navigation-map.md`, SPEC-0120 split). **Orientation,
> run-mode, cross-theme method, foundations & the architecture-drift lens → part 2**
> (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split).
> **The T2 / T4 / T5 lens-checklists → part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split). **T6 / T8 → part 5** (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`). **The T9 lens-checklist → part 4**
> (`patterns/inspection-criteria-roster-portfolio-observation.md`,
> SPEC-0120 split); **T10 → part 6** (`patterns/inspection-criteria-roster-real-work-observation.md`).

## The cadence model (per SPEC-0057 §9 — pointer, not restated)

Each roster row carries a **cadence tier** (a per-theme SETTING, §3 — NOT a new classifying axis).
The tiers (SPEC-0057 §9, owner-approved markup 2026-06-23):

| Tier | What runs | Cadence | Cost |
|---|---|---|---|
| **Continuous (reflexes)** | deviation capture, dissonance, file-on-observation | always; not scheduled | ~0 |
| **Operational hygiene** | parking-returns, blocked, MEMORY GC, postcheck-ready, overdue, lifecycle-integrity, read-gate, canary, cron-drift, soak-scan, bench-refresh, lesson-generalization | weekly | cheap — mostly one verb/view |
| **System inspection (T1–T10)** | the per-theme lens-checklists below (T2 / T4 / T5 in part 3; T6 / T8 in part 5; T9 in part 4; T10 in part 6) | monthly, themes ROTATED (~2–3 per cycle — a NON-NORMATIVE starting heuristic, not a governed threshold; the durable cadence is per-row) | costly — external audits / pattern-mining |
| **Anti-complexity apex** | v1-pattern accretion return + roster-currency | quarterly | medium |

**Manual-first (SPEC-0057 §2, UNCHANGED):** no cron / verb / auto-session runs an inspection; cadence
is owner-invoked. (A mechanical host-cron that only PRE-COMPUTES a digest — no AI session — is allowed;
an auto-SESSION is OUT until a CHARTER §6/§7 change. Both deferred as tracked `ideas/` seeds.)

**Machine-readable cadence values (the SINGLE parseable home).** The per-tier cadence
day-thresholds below are the SoT the review-due semaphore consumes (`inspection.parse_cadence` reads
THIS block; the CLI holds NO cadence literal — SPEC-0093/AC3). The prose tiers above are the human
gloss of the same numbers. Editing a value here re-thresholds the semaphore with no code change.

<!--CADENCE (SPEC-0057 §9 cadence values — parsed by bin/lib/inspection.py parse_cadence)
weekly_days: 7
monthly_days: 30
quarterly_days: 90
-->

The **review-due semaphore** (a report-only debt-echo view, SPEC-0119) reads this block + the
`inspection_completed` journal anchors: the WEEKLY operational-hygiene sweep is anchored by
`bin/yitc-v2 inspect record --tier weekly` (weekly_days), each **T1–T10** system theme by
`inspect record --theme T<n>` (monthly_days), and each **consumer-DECLARED** theme (a
`yitc-ops.yaml inspection.themes[]` entry, SPEC-0093 rule 12) by the same
`inspect record --theme <slug>` — at the day-value of **its OWN declared `cadence:` tier**
(`weekly|monthly|quarterly` → the matching `*_days` above), never one uniform monthly. A
subject whose day-value is not parseable here is skipped, never guessed. It fires ONLY when a subject
is past its cadence AND substantive work happened since its last run (no work → no nag) — it never
runs or gates an inspection (SPEC-0057 §2 manual-first is unchanged; surfacing due-ness ≠ running).

## Operational-hygiene weekly checklist — the weekly living checks

> One tier of the umbrella roster map, kept HERE alongside the per-theme lens-checklists below because
> both are the freshness-hashed **living criteria** — `inspect record --tier weekly` hashes this
> operational-hygiene section and `--theme T<n>` hashes each per-theme checklist (SPEC-0057 §6). The
> full umbrella **navigation map** (continuous reflexes · the T1–T10 system-inspection index · the
> anti-complexity apex · consumer-local product-adaptation themes) lives in the co-equal companion
> **`patterns/inspection-criteria-roster-navigation-map.md`** (SPEC-0120 split).

### Tier — Operational hygiene (weekly; + monthly / per-session as noted)

| Check | Theme | Cadence | How to run (verb\|view) | Rule-home |
|---|---|---|---|---|
| Parking lot — return triggers met? | T5 | weekly | `task list` (parked) review | QUEUE.md §Parking lot |
| Blocked queue — blockers cleared? | T5 | weekly | `task list --status blocked` review | QUEUE.md §Blocked |
| MEMORY.md buffer GC sweep | T5 | weekly | manual §5(c) stale-leftover sweep — the §T5 MEMORY.md buffer GC lens (part 3) | SPEC-0039 §5(c) |
| Realize-ready postcheck plans | T5 | weekly | `plan list --status postcheck` + view `postcheck-plans-readiness`; finalize ready via `plan stage realized` (worktree) | SPEC-0034 §realized; |
| Read-gate discipline (kind-split refusal ratio) | T2 | weekly | `bin/yitc-v2 graph query discipline-ratio` | SPEC-0059 / |
| Host-leak canary backstop | T6 | weekly | `bin/yitc-v2 audit canary-backstop` | SPEC-0066 §3 |
| Bench regular-refresh cadence | T3/T4 | weekly | refresh per plan `ai-bench-operation-…` (its regular-refresh cadence section); cell-select by running `python3 dev-utilities/bench/rule-conformance.py` (the delivered v2-self bench script — NOT a `graph query` view; see lesson `rule-conformance-is-a-bench-script-not-a-graph-view`) | plan `ai-bench-operation-accumulating-tables-and-model-r`; <workshop-spec>; lesson `rule-conformance-is-a-bench-script-not-a-graph-view` |
| Dispatch-worker lifecycle-integrity sweep | T3/T6 | weekly | `bin/yitc-v2 journal query --lifecycle-integrity` (`--since` to widen) | / |
| Overdue-recheck revisit sweep | T8 | weekly | `bin/yitc-v2 graph query overdue-recheck` | SPEC-0094 §3 / |
| Coordination-store backup-verify cron drift-check | T6 | weekly | **DIFFERENTIAL first, and it is the decisive one — user-INDEPENDENT:** `ls -lt <host-home>/.yitc-coordination/backups \| head -3` (the store dir is resolved by the ONE resolution site `cross.resolve_log_path` — `bin/verify-backup.sh` writes its snapshots to `<that dir>/backups`) — a snapshot dated within the last day at ~03:45 proves the job RAN (only the NAMES/dates are needed — the snapshot FILES are 0600, the dir itself is `o+rx`; access hinges on TRAVERSING `<host-home>`, which is `other::---` plus a per-user ACL — verified 2026-08-28 that collaborator `<collaborator>` reads this listing fine. An operator NOT on that ACL gets Permission denied, which is an ACCESS answer, not drift: fall back to `sudo -u dev ls -lt …`, and never to reinstall). A cron LINE that exists proves nothing about whether the job runs. Presence-check is SECONDARY and is USER-RELATIVE — the job lives in the OWNING account **`dev`**, so ask for THAT crontab: `sudo crontab -l -u dev \| grep yitc-coord-verify`; a bare `crontab -l` run by a non-`dev` operator returns 0 matches and reads as drift. REINSTALL ONLY IF THE DIFFERENTIAL IS STALE — never on an empty grep alone (that reading already filed a duplicate-install card, <project> X-1137/X-1177 + <project> X-1141; a duplicate job installed in a non-owner crontab writes to a dev-only log dir and fails silently while this row reads green). | SPEC-0084;; |
| Born-waiver freshness — init placeholder never replaced (per-project `yitc-ops.yaml`) | T6/T7 | weekly | `bin/yitc-v2 nightly` (the per-project `born_waivers` check surfaces each stale waiver path) | SPEC-0093; SPEC-0105 §1; |
| Post-verification soak-scan | T8 | weekly | read each recent non-hygiene closure's `post_verification`; route per §1; file follow-ups via `task file` | <workshop-spec> §6 |
| Lesson generalization sweep | T5 | weekly | Review-judged generalization lens over `lessons/` (consolidate / promote-split / `cross request` / retire-narrow) | SPEC-0090 §2b |
| Journal growth + untriaged-capture pressure | T5/T7 | weekly | `bin/yitc-v2 graph query journal-hygiene` (report-only digest: events.jsonl size vs 10MB + the watermark-derived UNROUTED backlog) | SPEC-0052; SPEC-0055; |
| Land-verify concurrency stability — recurring/non-deterministic `fail_class` + scaling watch-points | T6 | weekly | run the one-liner in §T6 → **land-verify concurrency stability** (part 5) (surfaces `_verify_scaling_signals` Rule-3/4 signals + scans recent `land_completed` A4 `fail_class`); report-only | SPEC-0132 Rules 3-4; SPEC-0057 |
| Abort assertion legibility — what share of aborted lands can NAME what broke (mute share, waive-token bindability) | T6 | weekly | run the fold in §T6 → **abort assertion legibility** (part 5) — pass the repo root, so the SAME block runs under `-C <consumer>`; folds on the assertion TEXT, never `abort_class`; report-only | SPEC-0057; SPEC-0077 §3a;; <project> X-1050 |
| Parallel-landing health — formation width, queue carry & throughput trajectory | T6 | weekly | run the fold in §T6 → **parallel-landing health** (part 5) — pass the repo root, so the SAME block runs under `-C <consumer>` over its own journal; report-only | SPEC-0132; SPEC-0119; SPEC-0057; |
| Load-sensitive lane sequential tail — over bound? → dispose the global-rework question | T5 | weekly | `bin/yitc-v2 [-C <repo>] debt` — read the load-sensitive-lane line (count + serialized wall + which bound, if any, is crossed; never recompute it by hand). OVER EITHER BOUND record the disposition per §T5 → **load-sensitive lane over bound?** (part 3): a DATED line in this week's `inspect record --tier weekly` naming the two numbers and choosing (a) the global-rework card it files or (b) why not + a re-check date. Another per-file card is not a disposition; report-only | SPEC-0132 §3; SPEC-0119; / |
| Parallel-landing blockage — one cause across branches · dead lands · branches ahead of main | T6 | weekly | `bin/yitc-v2 [-C <repo>] debt` — read the rule-26, rule-23 and rule-24 lines (cited, never re-implemented — see §T6 → **parallel-landing health**, part 5) | SPEC-0119 rules 23/24/26 |
| Exercise-the-gated-paths — dry-run the gated/rarely-walked paths that never fire (deploy guard shape · non-owner verify · onboarding-delivery seam) | T6 | monthly | run the 3 exercises in §T6 → **exercise-the-gated-paths** (part 5) (each NON-mutating: `deploy --print-guard` · a `verify.layers[]` layer as a non-owner · the onboarding-delivery seam render); report-only | SPEC-0057; plan `anti-false-green-doctrine-differential-proven-chec`; X-0366 |
| Exemption-case revision — is the declared audit-post exemption still warranted, and is the feedback that would tell us alive? | T8 | monthly | `bin/yitc-v2 [-C <consumer>] inspect record --theme T8 --tracks primary,external` (the report-only `case_review` block: one four-field proposal per declared case + its covered share over the case's own `window_days`); see §T8 → **exemption-case revision** (part 5) | SPEC-0178 rules 7+9; SPEC-0057; |
| Reverse-adoption — runtime-vs-shipped divergence (live code with no governed-deploy provenance · proof debt · live-probe vs declared surface · host reconciliation drift) | T8 | monthly | run the 4 probes in §T8 → **reverse-adoption (runtime-vs-)** (part 5) (each read-only); report-only; a probe that could not run reports **not-run**, never "clean" | SPEC-0057; X-0366 |
| Production-readiness — what this project's derived profile REQUIRES and its `yitc-ops.yaml` does not answer | production-readiness lens (report-only; NOT a T1..T10 slot) | monthly, 20-minute box, since-last-run watermark (`inspection_completed`) | `bin/yitc-v2 [-C <repo>] debt` — read the rule-39 gap line — then `bin/yitc-v2 [-C <repo>] profile`; file AT MOST 1 profile-mismatch + 2 top-risk items per project per run, and record "no gap" EXPLICITLY when there is none; an admission claim needs the code read (part 2 F-#2a) | SPEC-0198; SPEC-0119 rule 39; SPEC-0100; |
| Done log size | T7 | monthly | observed grep/tooling friction ONLY — the ~500/~1500 marks are history, not triggers; KEEP-FLAT re-decided, count-branch retired | QUEUE.md §Done log;; |
| First-pass audit RED / YELLOW shares per project — task audit-pre / audit-post and five plan gates, vs baseline | T5 | monthly | the fold in §T5 → **standing first-pass audit probe** (part 3): `graph query outcome-ratio` at two `--until` dates + `journal query` plan-gate rows; one `measurement_recorded` row per month; over baseline by >5 points 2 months running → a filed card or plan | plan `author-passes-audit-on-the-first-try-give-the-auth` §Verification plan; owner directive events.jsonl#ts=; SPEC-0057; |
| Ready-queue age by priority/class (not only blocked) + briefs of security-class cross items (G12) | T5 | weekly | `bin/yitc-v2 task list` + `bin/yitc-v2 cross inbox` | SPEC-0057; |
| Kernel-lifecycle residue graded: worktree claims, land residue dirs, lifecycle-integrity scope, pause residue (G13) | T6 | weekly | claims: `git worktree list` vs `bin/yitc-v2 journal query --type worktree_created`; land residue: `ls.yitc/land-logs/` + `git branch --list 'task/*' 'work/*'`; lifecycle integrity: `bin/yitc-v2 debt`; pauses: `bin/yitc-v2 journal query --type task_paused` | SPEC-0057; |
| New owner observations → file new tasks | — | per session | `task file` | QUEUE.md §Re-review |

> **Triage sweep + window — retrieved (SPEC-0055).** The triage VERB (`bin/yitc-v2 triage`) sweeps the
> un-routed captures since the last watermark; window/route rules: `bin/yitc-v2 graph query SPEC-0055`.
> The weekly / monthly / per-session cadence above stays mandatory.

## Per-theme lens-checklists (T1–T10) — the living criteria

> **T1–T10 live across FIVE parts.** THIS part carries **T1, T3, T7**; **T2, T4, T5**
> live in **part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split), **T6, T8** in **part 5** (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`), **T9** in **part 4**
> (`patterns/inspection-criteria-roster-portfolio-observation.md`, SPEC-0120 split) and
> **T10** in **part 6** (`patterns/inspection-criteria-roster-real-work-observation.md`, SPEC-0120 split) — a
> pointer line stands at each of their places below. All parts are
> SERVED: `inspect record --theme T<n>` resolves the section in whichever part holds it and hashes
> THAT part's bytes, so a moved checklist's `criteria_ref` names its part and stays as fresh
> as one that never moved.

Surfaces (M4) + probes (event/state/measurable). Base definitions converged from the 2026-05-31
dual-track calibration; the 2026-06 refresh (`inspection-list-refresh-…`, trial-converged) lens-deltas
are FOLDED in here. The run-by-run trial tracker / method-lesson narrative stays as HISTORY in those
realized plans (history, not a live list). Re-deepen each theme per run.

### Themes carried in parts 3 and 5 — T2 · T4 · T5 · T6 · T8

T2 / T4 / T5 live in **part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`, SPEC-0120 split), and
T6 / T8 in **part 5** (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`), each moved VERBATIM at a
one-bounded-read ceiling. `inspect record --theme T<n>` resolves each in the part holding it and hashes
that part's bytes, so their freshness is unchanged by the move.

- **T2** — Instruction↔doc fidelity + delivery/readiness
- **T4** — Outcome / cost-effectiveness (context-economy)
- **T5** — Meta-loop health (ceiling-mining, postcheck-aging, roster-currency, MEMORY GC)
- **T6** — Operational integrity
- **T8** — Adoption (done = adopted)

They are NOT restated here, and no `### T<n> —` stub stands in for them: two served parts claiming
one section makes the resolver REFUSE rather than silently hash a stub. This heading is a
pointer, not a theme — it does not match the `### T<n> ` shape the theme reader looks for.

### T1 — Doc↔code coherence (coverage, «no silent gaps», drift-possibility)

- **Surfaces:** handbook (CHARTER/AGENTS/LIFECYCLE/QUEUE/GRAPH) + `decisions/` + the `bin/yitc-v2`
  IMPLEMENTATION (not `--help`) + delivery/graph surfaces (per-spec `binding:`, the GENERATED
  floor-trigger-map, stage-entry bundles) + the GENERATED born-ops/concern-registry surfaces (born
  sections ↔ the SPEC-0128 registry roster; an orphan/unwired concern hook is a finding).
- **Probes:** explicit contradictions (P7); doc↔code drift (#9); supersession atomicity, checked ALONG
  THE CHAIN to the head (one-level gives false positives); **dangling `requires`/`cites` — resolved
  against the ID NAMESPACES the INSPECTED repo actually has, not one assumed corpus** (X-0666): on a
  consumer that is the repo's own corpus UNION the KERNEL spec-id set it legitimately cites (the
  methodology specs travel as kernel — SPEC-0073 §1; the `_kernel_spec_ids` fallback for the
  spec leg for the scenario leg), and a consumer running its OWN `T-NNNN`/`SPEC-NNNN`
  numbering may COLLIDE with kernel ids — so resolve per REALM, never by id shape alone; **coverage both
  ways** — spec→code dead anchors via `graph build` stderr, code→spec un-specced surface via
  the SPEC-0005/ admission test (NOT every-file); **named-reference resolution incl VERBS** — a
  doc reference to a named view/verb/artifact resolves to an existing, NOT-retired one OR is explicitly
  deferred (run-1: `decision new` cited live while hard-refused in code); a NEW verb whose ONLY home is
  a pattern does not pass by home-existence alone — record an explicit SPEC-0005 admission judgement
  (spec anchor OR a below-admission marker; 2026-07 refresh). **Resolve by an INVOCATION-SHAPED match,
  never a bare substring** — the same guard the event-catalog probe below already carries, which this
  probe lacked while resolving references of the same shape: a bare-token search reads a verb as homed
  wherever its letters occur, so short and common subcommand names (`get`, `set`, `status`, `report`,
  `reach`, `delete`) resolve to dozens of specs that never mention the verb. Measured 2026-09-20 on this
  repo: `get` read **136** anchoring specs bare vs **1** under an invocation-shaped reading (×136), and
  the bare reading resolved EVERY new verb to a home — i.e. it reported a confident CLEAN — while the
  guarded reading left two verbs with no home at all. The bare form is the false-clean generator; **event-catalog check on TWO
  levels** — types AND payload-keys, resolved by the predicate its rule home states: **read
  SPEC-0161 §Catalog completeness reconcile and apply it** (`bin/yitc-v2 graph query SPEC-0161`) — the
  rule is NOT restated here, so this line cannot drift from it. Reading only SPEC-0025 + SPEC-0161 is
  the RETIRED method: measured 2026-09-20 on this repo at **139 "missing" types vs 2 real**, a ×70
  false-gap rate — run it only as a declared control arm, never as the measurement. (Substring match, not regex — regex gave false positives; ≥4-char token guard —
  short tokens pass by incidental substring; payload ground truth = a journal-window type→data-keys map;
  skipping the payload half is a HALF-RUN, not a run; a RECURRENT catalog-lag finding REQUIRES the
  carrier lookup in the finding body — 2026-07 refresh);
  **FSM-statement check** — every FSM assertion in the handbook ≡ its authoritative FSM home,
  resolved against a NAMED FSM INVENTORY, never by token shape: this repo declares at least FOUR
  distinct status/stage FSMs with four distinct homes — **task status** → QUEUE.md §State transitions ·
  **spec status** → GRAPH.md §Spec lifecycle · **plan status** → SPEC-0034 · **task STAGE** →
  LIFECYCLE.md §The 9 stages — and they SHARE TOKENS (`draft` belongs to both the spec FSM and the plan
  FSM). Without the inventory the probe collides them: measured 2026-09-20, a first mechanical run
  classified all seven plan-stage names as out-of-FSM tokens of the SPEC lifecycle — three false
  positives produced by the missing inventory, not by any drift; **«no
  silent gaps» (full M4 walk)** — verb×governing-rule, lifecycle-step×description, event×SPEC-0025
  catalog, helper×spec-anchor; the defect is a SILENT gap, not absence of a spec per se — **and that
  discriminator governs every REPORT-ONLY signal this theme reads**: a report-only signal (a `graph
  build` possibly-stale signature, a frozen-history anchor, a conformance WARN) with a NAMED, OPEN
  carrier is **swept-with-evidence, not a finding** — cite the carrier id in the sweep; the SAME signal
  with NO carrier, or with a carrier that is closed or missing, IS a finding, because nothing is
  tracking it. Absence of a carrier must be CHECKED, never assumed either way. Without this rule the
  case is genuinely undecidable and two tracks of one paired run split on it: measured 2026-09-20, the
  primary read the 10 possibly-stale signatures as swept (carrier, open) while the external
  filed them as a LOW finding, on identical data.
- **Finding UNIT and severity floor (so two tracks of one paired run are comparable).** ONE finding per
  distinct DEFECT-and-ROOT, not per affected instance: several surfaces failing the same rule for the
  same reason are ONE finding naming them all (the two un-homed verbs are one finding, not two), while
  one surface failing two different rules is two. Without this the two tracks split and bundle the same
  observations differently and a paired run reads as diverged when it agrees — measured 2026-09-20,
  where the primary filed per-instance and the external per-root on an identical matrix.
  **Severity floor:** an EXECUTABLE surface reachable by an operator with no governing rule at all — a
  verb, an emitted event type, a module — is **at least MEDIUM**, never LOW; LOW is for a resolvable
  reference that is merely imprecise. An un-homed executable surface is a governance gap, not a typo.
- **Method:** read IMPL not help (M1); validate the probe (M2); scan the ACTIVE queue first;
  external track gets PRE-COMPUTED mechanical sweeps as input (it has no interpreter — chain/dangling
  sweeps were blocked); semantic diff stays its strength. **Every journal reading in this theme goes
  through the segment-aware reader `bin/yitc-v2 journal query` — a raw grep of the live `events.jsonl`
  path is a MEASUREMENT ERROR, not a shortcut.** Why, at its home: `bin/yitc-v2 graph query SPEC-0190`
  (the reader rule is NOT restated here). This is rule B's THIRD failure mode landing inside T1's own
  instrument set. Measured 2026-09-20 on this repo: of 140 emitter-derived type names, a raw grep of
  the live path read ZERO for 50, and the segment-aware reader recovered NON-ZERO rows for **17 of
  those 50 — a 34% false-zero rate**. A T1 finding resting on a raw-grep zero is unproven; state which
  reader each count came from.
- **Repo-shape inputs — READ THESE BEFORE A T1 MECHANICAL PASS, on any repo (X-0666, <project>
  2026-08-06).** Every mechanical probe above takes repo-shape INPUTS — the FIVE <project>
  measured: **id namespaces**, **test roots**, **ledger/table shape**, **waive-contract shape**,
  **ledger-parse shape** — and each is **DERIVED FROM THE INSPECTED REPO**, never assumed to
  be the kernel's. Where to read each: id namespaces per the dangling-`cites` probe above; test roots
  per the roll-call sub-probe's Probe 3; ledger shape per its Probe 2; waive-contract shape likewise
  per Probe 2 — a contract field may be HOISTED into a table's section preamble instead of repeated
  per row, so the shape to read is where the row's fields actually come from, not one assumed
  per-row form; ledger-parse shape from the inspected ledger FILE's own sectioning — a ledger may be
  one table, or many sections a flat parse merges into one, so read how that file is cut before
  parsing it. (The last two are stated here because they are where <project>'s false positives 4
  and 5 came from — X-0756, filed at our invitation in X-0755.) These five are T1 probe INPUTS; the
  rule about what an unvalidated pass YIELDS is no longer stated here — it was lifted, realm-agnostic
  and run-wide, to **part 2 §Run-mode → «Validate before you report»** (which carries the <project>
  5-of-5 false-positive rate as one of its two groundings). Read that step; it binds this pass on any
  repo, kernel included. One home — this note points, it does not restate (P5 / SPEC-0005 rule 8).
  This is a
  probe-INPUT discipline, deliberately NOT an executable probe generator: SPEC-0057 is manual-first by
  declaration, so a runner would be a new owner-gated mechanism (CHARTER §P1 F4).

**T1 sub-probe — drift-possibility (anti-drift-by-construction; folded in):** a sub-probe of
T1 that catches the hand-maintained restatement BEFORE it diverges (statement == home NOW, but CAN
drift), vs T1-today which catches drift that ALREADY happened. **Audit baseline = SPEC-0067** (the
drift-capable-vs-drift-proof classifier); probe shape per SPEC-0057 §5 (PROBE-ONLY). Grounding
blind-spot: `deviation_captured#ts=`
(`inspection-roster-no-drift-possibility-derivation-audit-lens`). Landed by (plan
`drift-possibility-inspection-lens`).

| Lens | Surfaces | Probes |
|---|---|---|
| **drift-possibility** | handbook prose · specs · patterns — any section that STATES a rule / FSM / contract / threshold whose authoritative home is ELSEWHERE | the 5 probes below |

- **Scope — SECTION-LOCAL unless a carrier names the corpus.** In a per-theme run (a fold
  card, a cadence run) the walk covers the surfaces THAT RUN inspects — the theme's own roster section
  and the artifacts its carrier names — and the sweep records that scope as its swept surface. The
  corpus-wide walk over every handbook/spec/pattern section is NOT a per-cycle probe: it runs only when
  a plan or card names it as its subject. A per-theme run therefore writes no «corpus-wide walk NO-DATA»
  line; the absence it would have stated is this scope, stated once here.

- **Probe 1 — classify each such statement by SPEC-0067:** drift-**PROOF** (a `cites`/navigational
  pointer · a `graph query` derived-view · a generated artifact like the floor-map · an explicit
  `> Retrieved — SPEC` pointer · a declared SPEC-0005-rule-3 note) OR drift-**CAPABLE** (a
  hand-maintained restatement that can diverge)? Discriminating test (SPEC-0067 §3): *"if the home's
  rule-text changed, would THIS text have to be changed too, BY HAND, to stay correct?"* — YES ⇒
  drift-CAPABLE, NO ⇒ drift-PROOF.
- **Probe 2 — each drift-CAPABLE statement = ONE convert-to-single-home finding:** name it + its
  authoritative home + the proof-conversion (pointer / derived-view / generated). `candidate_home` is
  PROPOSED for triage; disposition (keep/delete/generate) is triage → Build task + owner governance.
  Every finding MUST enter triage.
- **Probe 3 — null ≠ clean (F-#2):** a clean result carries swept-surface evidence, never a bare "none".
- **Probe 4 — `explicit_sync_governed`** (a derived HINT inside the finding, NOT a new verdict-class):
  set ONLY when the restatement is backed by an EXPLICIT governed sync-rule / coherence-invariant cited
  at the site (e.g. the read-order's SPEC-0007 §5b «must never diverge») → suggested conversion =
  GENERATION. NEVER downgrades the classification: a TRUE-flagged restatement is STILL drift-CAPABLE.
- **Probe 5 — home vs surface:** `candidate_home` is the rule's AUTHORITATIVE artifact (spec/decision);
  a generated/derived echo (e.g. the `session start` read-order echo) is a SURFACE, never the home.

**T1 sub-probe — rule→test roll-call (loud-failure coverage; folded in / SPEC-0165):** the
4th T1 axis. Where drift-possibility asks «CAN this restatement diverge?», roll-call asks the coverage
question one axis over: «is every silently-breakable atomic RULE proven by a tripwire test, or an
explicitly-contracted waive?». **Checklist source = the per-project rule↔test ledger**
(`specs/<PROJECT>-rule-test-ledger.md`; kernel = `specs/yitc-v2-rule-test-ledger.md`, broad-mapped) — the ledger is the roll-call sheet: one row per atom, tripwire-or-waive (SPEC-0165 §8). The
axis READS the ledger, it does not re-home rules (P5 / SPEC-0005 rule 8; the spec stays the rule's home,
the test stays the proof, the ledger stays derived bookkeeping — never a parallel truth). **Scope
(SPEC-0165 §7):** only NORMATIVE rules of ACTIVE specs — descriptive/frozen specs are not rules. **Walk
order (SPEC-0165 §6):** by the COST of silent breakage (money → outbound mutations → isolation/access →
data mutations → background jobs).

| Lens | Surfaces | Probes |
|---|---|---|
| **rule→test roll-call** | the rule↔test ledger · the tier-1 normative-rule set of active specs · the tripwire suites the ledger links · the ledger's waive contracts | the 5 probes below |

- **Instrument — the per-atom reading.** `python3 dev-utilities/reference-revizia-sweep-constructor.py
  [--repo <path>] --roll-call [<ledger>] --since <date>` reads a SECTIONED ledger ATOM by atom (row header
  `**<LABEL>.**`; a contract field HOISTED into the section preamble counts as present) and prints: probe 1
  NEITHER rows · probe 2 waive rows missing a field · probe 3 dead links (the EXISTENCE half, repo-relative
  — a consumer's declared test roots stay the operator's input) · probe 5 candidates (test files git-ADDED
  since `--since` whose row's SPEC anchor already had an older suite). It is an operator-run READER in the
  reference-constructor shape, not a probe runner (SPEC-0057 stays manual-first). What it cannot read stays
  manual: probe 3's DIFFERENTIAL half and probe 4's join. A run that does not use it states its own
  per-atom method; a mention count stands in for neither.

- **Probe 1 — no NEITHER rows (SPEC-0165 §Verification b):** every tier-1 normative atom resolves to a
  tripwire test **or** a waive — an atom with neither (or absent from the ledger entirely) is a coverage
  GAP finding. A named-GAP row is acceptable bookkeeping; a SILENT absence is the defect.
- **Probe 2 — waive-contract completeness (SPEC-0165 §4):** each waive carries ALL seven fields —
  `{class, mechanism, fail-point, path, violating-input, approver, recheck-trigger}`. A waive missing any
  field is a finding (it is rejected at review by the same rule). **Read the ledger's actual SHAPE first
  (X-0666):** a ledger may carry **MULTIPLE tables** (per area / per tier / per surface), and a table's
  contract fields may be **HOISTED into a section preamble** instead of repeated per row — so a field is
  present if the row OR its governing preamble supplies it, and absence from ONE table is not absence
  from the ledger. Assuming one flat table with all seven fields per row is a false-positive generator.
- **Probe 3 — tripwire link resolves + is differential:** each linked tripwire test path EXISTS (a
  renamed/deleted test = a dead link finding, the coverage-side twin of the T1 spec→code dead-anchor
  probe) and proves the rule DIFFERENTIALLY (violating input fails / quarantined input passes), not by
  mere presence. **Resolve paths against the inspected repo's DECLARED test roots, never one assumed
  `tests/` root (X-0666):** read them from that repo's `yitc-ops.yaml` — `tests.classes[]` (the
  class×moment INVENTORY, SPEC-0093 rule 10) and `verify.layers[]` (the authoritative executable
  land-verify layer universe + its per-layer `command`, SPEC-0152 rule 16). A consumer with a
  non-kernel test layout resolves every link as dead under the assumed-root reading.
- **Probe 4 — recheck-trigger currency:** an atom whose recheck-trigger has FIRED since the link was made
  (its spec edited · a frozen→active flip · its area touched) is a STALE row needing re-verification — the
  roll-call equivalent of drift-possibility's «CAN drift» made «HAS the trigger fired».
  **THE UNIT IS THE ONE SPEC-0165 §8 DEFINES — NEVER THE SPEC MENTION; a spec-mention count is not a roll-call reading.**
  The unit and the ledger's row model are defined at their home: `bin/yitc-v2 graph query SPEC-0165`
  (§8) — read it there and apply it; this line names neither the unit's definition nor the row model.
  What it adds is the T1-local REFUSAL: a count of
  how often `SPEC-NNNN` appears in the ledger answers a different question and cannot establish the
  result, and a run that substitutes it has not run this axis. Caught 2026-09-20 by the BLIND external
  track against a primary pass that had made exactly that substitution; recorded so the substitution is
  refused by the checklist rather than by luck.
  **Name the instrument, and mind its false-zero form.** The mechanical currency reading is: the
  ledger's own last-edit commit date, then the ACTIVE specs **TOUCHED** since it (`git log --since=<that
  date> --name-only -- specs/`), each joined to its ledger rows. The reading an operator reaches for
  first — specs **ADDED** since that date — is a FALSE ZERO, because the declared trigger is «its spec
  EDITED», not «a new spec appeared». Measured 2026-09-20 on this repo: the ADDED reading returned **0
  and read CLEAN**, while the declared trigger returned **61 fired, of which 20 carry no ledger row at
  all**.
- **Probe 5 — extend-before-create signal (SPEC-0165 §5):** a task that added a NEW standalone tripwire
  file whose rule already had a suite draws the review question «which existing rule suite did you
  extend?» — accretion (one-file-per-task-forever) is a finding, not coverage. Null ≠ clean: a clean
  roll-call carries the swept atom-set + the ledger revision as evidence, never a bare "none" (F-#2).

- **G8 — instrument self-check:** an absent input is NO-DATA, not clean; each waiver's compensating-control name must exist; read ALL of the kernel `graph conformance` output incl. activation-checklist drift (<workshop-spec>).

### T3 — AI-execution fidelity (boundary-watch, output-quality)

- **Surfaces:** journal intent↔actual (fed by `owner_directive`) + the AI-slip catalogue
  (deviations + `E-XXXX`) + git + the CHARTER 20-class list.
- **Disqualify synthetic rows BEFORE any count:** a `session_ref` `test-*` or a `project` not keyed in
  the server registry (`<host-home>/registry.yaml` `projects:`, read-only) is test output, not behaviour
  — state the disqualified count; a count taken over them is a false reading. **M2-validate** each instrument — counting, classifying AND each
  absent-carrier detector — by PLANTING one synthetic input it must flag (e.g. a `from:` naming
  `tasks/-…`; a row that DOES carry the missing field) and recording that it did.
- **Probes:** M6 verdict-gating chronology — a close with no earlier `audit_post_completed` is a bypass
  ONLY if the verdict record (`decisions/**/<tid>-audit-post.yaml` `audited_at` / `passes_trail`) also
  post-dates it; a verdict that pre-dates the close with no journal row is a journal-integrity finding;
  M7 claimed-artifacts-exist — resolve every path a commit's `from:` cites at THAT commit (`git
  cat-file -e <sha>:<path>`; a `T-/SPEC-/E-` id that resolves under a drifted slug is clean); an id
  merely MENTIONED in a deviation is not a claim; class tally (`from:` probe method, 2026-07:
  BODY-grep `from:`/`emergency:`, never trailer-parse; **exclude verb-generated commits by their
  GENERATOR** — derive the set each run from the `bin/lib` `commit -m` call sites (rule B applied to
  subjects); at 2026-09-21 it is `^(land|worktree sync): bookkeeping \((task/T-[0-9]+|work/[a-z0-9._/-])\)$`
  (`worktree._land_bookkeeping_commit` `msg_prefix`) and `^chore\(T-[0-9]+\): card bookkeeping$` (`worktree.py`, 112 phantom
  violations when omitted), each WHOLE-subject anchored so an authored look-alike is still reported
  (X-1186, X-0591); **exclude merges CASE-INSENSITIVELY** — `(?i)^merge (branch|commit|remote-tracking)\b`
  or `--no-merges`); slip tally over AI-authored captures (`actor: ai-agent`, `captured_via` absent,
  any `self*` spelling, or `owner-surfaced` — machine, mirror and inspection captures excluded) by ROOT (M9: one root =
  one governed rule breached by one action; record the fingerprint predicate that maps spellings to it,
  so a re-run reproduces the cluster) with its denominator — no class-number dominance claim (no field
  carries the CHARTER class); a root breaching a governed rule in ≥3 distinct sessions is AT LEAST a
  MEDIUM finding (a higher §Severity row still applies; capturing each instance does not discharge it).
  **Build each root predicate by ROOT-STEM clustering, never a literal substring of one spelling**
  : seed the families from the deterministic stem clusterer (`triage run` Section B2 / `graph
  query --type error --recurring`, SPEC-0055 §Discovery stem-clustering); state the root as a
  conjunction of STEM FAMILIES (subject · breach manner or order · action), each a hyphen-token
  alternation, so a respelling in any word order still lands — and EVERY alternative carries its own
  subject (a verb name such as `spec-edit` is never the subject), or a neighbouring artifact's slip
  merges in; READ the matched spellings and drop, with a reason, any whose subject is a verb, guard or
  doc defect (a different root); M2-plant the window's NEWEST real spelling beside a canonical one, and
  a NEGATIVE whose subject is a neighbouring artifact. The literal `spec-body AND (hand|raw)` missed
  `t12804-raw-spec-edit-instead-of-spec-edit` (the 2026-09-23 sweep read 66 with it). The two recurring
  roots, over the lower-cased fingerprint, re-run over the population since
  2026-07-17 (where the literal read 67, one capture after the sweep) —
  spec-edit root (spec body changed outside `spec edit`):
  `^(?!spec-(edit|hand-edit-guard|reverify)-)(?:(?=.*(^|-)(spec(?!-edit(-|$))|anchor-repoint|implements-anchor|block-scalar))(?=.*((^|-)(hand|raw|sed|regex|bulk)|(instead|bypass\w*|off|outside)-(\w+-){0,3}spec-edit))(?=.*(^|(?<!spec)-)(edit|amend|repoint|writ|wrote|split))|(?!.*(^|-)(task|card|yaml|plan|audit|doc)s?-(\w+-)*(hand|raw|sed|regex|bulk)\w*-spec-edit).*(^|-)(hand|raw|sed|regex|bulk)\w*-spec-edit)`
  — 83 rows / 82 sessions / 62 spellings, a superset over every journal fingerprint of the sweep's
  broadened literal (read 75 there);
  audit-pre root (Execution work authored before the audit-pre gate):
  `^(?=.*(^|-)(edit|draft|execut|wrote|writ|implement|author|built|build|code|diff|stage5|fix))(?=.*(^|-)(worker|execution|stage5|code|source|implementation|diff|fix|edits)-(\w+-)*?(before|preced\w*|during)-(\w+-){0,6}(audit-pre|stage4))`
  — 44 rows / 44 sessions / 41 spellings, where the sweep's literal read 20.
- **Boundary-watch** — no de-facto multi-agent / orchestration creep; any appearance = P7 dissonance +
  decision, never silent acceptance. Read POSTURE at the row's ts (the session's latest
  `session_started` `type` before it), never by dispatch-set membership: a `build` session emitting
  `bg_dispatch_launched` or `ceiling_decision` is a breach (a Worker never dispatches or decides —
  SPEC-0204). Fences (rule at its home) and their carriers: ceiling decisions SPEC-0191/SPEC-0204 —
  each `ceiling_decision.directive` resolves to an `owner_directive` row · decide-authority SPEC-0169 —
  `authorization_*`/`right_exercised` over registry projects · advisor read-only <workshop-spec> — its verb
  (`journal query --dispatch-plan`) appends only its receipt · execution-cue SPEC-0141 + batch-bounded
  autonomy SPEC-0126 — the launch's authorizing cue (the `owner_directive` classifier alone is not a
  carrier: a status question inside an authorized batch reads `question`) · held-turn detached land
  SPEC-0180 — its admission. A fence whose carrier is ABSENT is a NO-DATA line AND one MEDIUM finding
  per missing carrier (fences sharing one missing carrier = one finding).
- **Age-based terminal actions (G16):** a bulk or automated action that terminates a governed artifact
  (plan cancel, worktree removal) on AGE alone conforms only when a same-session `owner_directive`
  states that age criterion; an automated one that removes a registered/held worktree without reading
  its dirt or pause state is a finding.
- **Severity:** HIGH — a fence breach, a gate bypass, destruction of uncommitted authored work;
  MEDIUM — a fence or probe the journal cannot adjudicate, an instrument defect that corrupts a whole
  count, a provenance-violation population > 0; LOW — isolated record gaps. One finding per
  defect-and-root, never per instance.
- **Output-quality** is NOT a revizia probe: the frozen-template judge
  (`dev-utilities/bench/judge-template.md`, `scorecard.py` (d)) runs only inside an owner-invoked
  bench batch (0 verdicts to 2026-09-21).
- **B5-delta — per-land verify-status (CONSUMER runs only; grounding: <project> B5, run_ref
  migration-b5-baseline-2026-06-28):** for EACH `land`, a foundational land with `consumer_verify:
  waiver` is a FINDING (not test-gated). The kernel has no consumer verify layer, so its
  `land_completed` carries no `consumer_verify` — B5 is N/A there (record it as such).

- **G9 — owner-row provenance:** a cited owner row's source and timing are checked; machine rows in the owner carrier are a finding — `bin/yitc-v2 journal query --type owner_directive`.

### T7 — Anti-complexity / bloat (doc/code layering, generalization)

- **Surfaces:** the whole SPEC-0120 §1 **durable-doc set** — the handbook (CHARTER/AGENTS/LIFECYCLE/
  QUEUE/GRAPH + any read-order part) + `specs/` + `patterns/` + `lessons/` + `scenarios/` (size +
  language); counts vs review-triggers (handbook 2000/2500 — node-volume counts (tasks, patterns,
  lessons, the frozen decision corpus) are NOT review-triggers, see probes); audit-YAML accretion;
  AGENTS injection cost; mechanism count vs v1; retirement use;
  the cost-view; adjacent state stores (`.yitc/`, `journal-sync-state/`, `views/`); **code** —
  SIZE and DUPLICATION are the Architecture-drift lens's probes (part 2): T7 does NOT re-detect them,
  it READS that lens's SPEC-0080 size bucket (`wc -l bin/lib/*.py` against the budget) as a governing
  trigger (below) and checks retirement residue (a retired mechanism's code references = 0).
- **Probes:** each measured size/count vs its **governing** trigger (handbook 2000/2500; the SPEC-0120
  byte/line must-split ceilings; the SPEC-0080 code size budget; `graph build` > 5 s) — report
  `fired? / acted?`; a fired-but-unacted trigger is a FINDING, not a clean measurement. **Acted** means
  an OPEN card, or a card that CLOSED the subject, carries it NOW; a card closed wont-do/superseded
  whose own reason names a re-file condition that has since been met (the prerequisite landed) is
  UNACTED, and a subject split earlier that has re-crossed the ceiling is fired AGAIN. **NODE-VOLUME
  counts are NOT such triggers:** there is NO numeric node-volume trigger for ANY node type (SPEC-0031 §Node-volume; the done-log mark, QUEUE §Done-log; `decisions/` is FROZEN
  monotonic history). Measure node-volume anti-complexity by ACTIVE/displacement
  surfaces (audit-YAML accretion, injection mass — already in this row), **not** file-count.
  AGENTS lines/chars/≈tokens-per-load; hooks/gates/journals;
  superseded/withdrawn/terminal counts; **watch bloat-DISPLACEMENT** — caps held → accretion migrates
  to un-capped surfaces (decisions, audit-YAMLs, injection mass); quantify displacement against the
  calibration baseline (263→803 ×3.05/6d first measure); decisions-count EXCLUDES audit files from the
  `D-*.yaml` glob; a surface with NO governing trigger is QUANTIFIED, never a finding;
  **generalization lens (§2.7c)** — the constructive twin of retirement ( removes DEAD; this
  finds LIVE-but-DUPLICATED — kindred rules, verb-families with a common core, specs with overlapping
  subject; code-level duplication is the Architecture-drift DUPLICATION probe). Its SUBJECTS are
  DERIVED each run, never a dated named set: the NEW mechanism families the run's delta source assigns
  to T7 (a refresh plan's §Delta sources / T7 disposition; absent one, the specs activated in the
  window whose code landed as NEW `bin/lib` modules — a module EXTRACTED from an existing one is the
  Architecture-drift lens's, not a family). Each subject gets a reading — overlap with an existing
  module / verb family / spec, or none demonstrated; only DEMONSTRATED overlap (two homes for one rule,
  a verb family re-implementing a common core) with no consolidation disposition (an open or closed
  review card, or a recorded no-merge) is a finding (MEDIUM); a closed review retires its subject. **Feeds:**
  `trend-report`. Absence-claims must be evidence-grade over the WHOLE governed space (tasks
  all-status + plans + ideas + decisions-non-audit + MEMORY.md); a narrow sweep = needs-data;
  carry-forward each item → its found carrier (with status/parked-reason) or confirmed absence.
- **B5-delta — CONSUMER-scoped (a kernel run records both N/A, never "clean"):** (a) deploy-still-on-v1
  — a migrated consumer whose deploy path still SOURCES the v1 framework (e.g. `deploy.sh` sourcing
  `<project>/.../deploy-common.sh`, incl. a fallback search) = INCOMPLETE v1 retirement,
  a finding absent an EXPLICIT recorded decision; (b) product-state clarifier — a repo-ROOT file whose
  NAME resembles an archived v1 governance file (`BACKLOG.md` / `DECISIONS.md`) is product-state IFF
  (1) a `docker-compose` bind-mount target, (2) created by a tracked consumer task, AND (3)
  `.gitignore`d; lacking those three ⇒ v1 residue (a finding).
- **Severity (one table, every T7 probe; applied PER SUBJECT, so one root may yield one finding per
  severity):** **HIGH** = a fired-but-unacted must-split on a doc delivered to every session of a
  kind (an always-loaded seed part, or an `active` spec named in the window's `stage_entered` /
  `plan_stage_entered` `delivered` lists — the instrument, not the `binding:` text) — a one-read breach
  on a delivered contract; any worker-seed HARD probe
  (1)-(3) violation. **MEDIUM** = any other fired-but-unacted governing trigger; an instrument that
  reports a whole axis clean while its own per-item record shows otherwise; demonstrated overlap with
  no consolidation disposition. **LOW** =
  report-only candidates awaiting a disposition (a language candidate off the allow-list, a
  prose→verb candidate); a criteria-scoping defect. A declared NO-DATA line is not itself a finding.

**T7 sub-probe — durable-doc governance: SIZE band (2 axes) + LANGUAGE (report-only; per SPEC-0120).**
The methodology's own docs must stay loadable in one read and (kernel) English-only. MEASURED over the
whole durable set, report-only, NEVER a gate (CHARTER non-goal #2; SPEC-0080 P-A6 posture). Carrier:
the T7 run's **`inspection_completed`** — `bin/yitc-v2 inspect record --theme T7` attaches a report-only
`durable_docs` block (per-doc `{path, lines, bytes, est_tokens, cyrillic_lines}` + the derived
buckets) and PRINTS the aggregate counts plus a row per FLAGGED doc. A `-C` consumer run scans ITS
OWN durable docs.

| Lens | Surfaces | Probes (each → a CANDIDATE finding, never a block) |
|---|---|---|
| **durable-doc size** | the SPEC-0120 §1 durable set (handbook + `specs/` + `patterns/` + `lessons/` + `scenarios/`) | the 4 size buckets + the language-probe below |

- **Probes SIZE-1..4 — two INDEPENDENT axes, four DISJOINT buckets, reported SEPARATELY (never merged):**
  `over_band` / `over_ceiling` on LINES, `over_band_bytes` / `over_ceiling_bytes` on BYTES — the
  thresholds and the ~2.52 B/token calibration live in SPEC-0120 §3 and `bin/lib/inspection.py`
  (single-SoT, not restated here). Over-band = split CANDIDATE at the next coherent seam; over-ceiling
  = MUST-SPLIT (SPLIT, never delete content). The byte axis exists because lines under-read a DENSE doc
  (: 1.7x density spread): a doc line-clean but byte-over-ceiling is single-read-UNSAFE
  and is flagged on the byte axis ALONE. Both size axes are REALM-AGNOSTIC; only LANGUAGE is
  kernel-realm-gated. Each over-ceiling doc then takes the governing-trigger `fired? / acted?` read
  above, severity per the table.
- **Probe LANGUAGE — kernel English-only (§2):** a mechanical Cyrillic scan (`grep -P '[А-Яа-яЁё]'`)
  over the durable set; binds by REALM (SPEC-0120 §2/X-0208) — engine-self only; a `-C`
  consumer's methodology and product docs are NOT language-flagged. **Read the per-doc
  `cyrillic_lines` record, never the `cyrillic` bucket alone:** the bucket populates only when
  `REPO_ROOT == ENGINE_ROOT`, so on a KERNEL run a bucket SMALLER than the count of docs with
  `cyrillic_lines > 0` is an instrument defect (MEDIUM), not a clean axis. Then check each
  Cyrillic-bearing path against SPEC-0120 §2's DECLARED allow-list (single-SoT there, NOT copied here);
  report only what is NOT on it — the expected residue is what keeps a NEW violation visible.
- **Probe null ≠ clean (F-#2), held by the RESULT CONTRACT (<workshop-spec> rules 1+2):** the shape
  is defined at ONE site — `bin/lib/inspection.py#result_contract` — merging `swept`, `excluded` (rows of
  `{class, reason, files, bytes}`, reason `exempt` / `out-of-realm` / `unscanned`) and `no_data` (a run
  that swept nothing is NO-DATA, never clean) into `durable_docs`. A clean result reads "swept N,
  excluded <the named classes>, 0 over-band / 0 over-ceiling / 0 over-band-bytes / 0 over-ceiling-bytes
  / 0 Cyrillic"; `swept` alone cannot surface what was unreachable (the 93,857-byte ledger that sat
  above the ceiling while the over-ceiling set read EMPTY).

**T7 sub-probe — worker-seed audience guard: no controller-content re-accretion (HARD-fail; per SPEC-0127).**
The dispatched **Worker** boots a per-audience seed (the `core`+`worker` sections), NOT the full
handbook — so Controller-only content must NOT re-accrete into it. The audience invariants are
**HARD** — a violation must be fixed (SPEC-0127 §5; HIGH per the §Severity table above). The inspection READS the
generated **`graph/worker-startup-inventory.md`** §HARD PROBE (derived by `bin/yitc-v2 graph build`
from the `<!--AUDIENCE:core|controller|worker-->` markers) — no new mechanism. NOT a land
gate (committed==regenerated DRIFT is `graph conformance`'s). **How to run:** `bin/yitc-v2 graph
build`, then read §HARD PROBE — EVERY numbered probe there MUST read `PASS`.

| Lens | Surfaces | Probes |
|---|---|---|
| **worker-seed audience guard** | the generated `graph/worker-startup-inventory.md` (derived from the `<!--AUDIENCE:...-->` markers on CHARTER/AGENTS*/LIFECYCLE/QUEUE/GRAPH) | the probes below |

- **Probe LEAK (HARD, §5 condition 1):** inventory line
  `(1) controller-tagged sections inside the worker seed: N` — **N MUST be 0** (a leaked `controller`
  section = an assembly bug or a mis-tag; the detector scans the ACTUAL generated seed string for each
  controller heading).
- **Probe UNTAGGED (HARD, §5 condition 2):** inventory line `(2) untagged #/## seed sections: N` —
  **N MUST be 0**; resolution defaults untagged → `core`, so a section MUST be EXPLICITLY tagged or a
  forgotten controller-only section silently re-accretes as core.
- **Probe PARTS (HARD):** inventory line `(3) worker-seed parts over the size band: N` — **N MUST be 0**;
  the band is the one the inventory itself DECLARES (its «size band per RENDERED part» line), not the
  durable-doc over-band threshold.
- **Probe SIZE (report-only drift signal):** measure the seed in BYTES — the sum of `wc -c` over
  `graph/worker-seed*.md` + est_tokens at the SPEC-0120 calibration — and compare to the last run. The
  inventory's `worker-seed tokens (whitespace-split)` line is a WORD count that under-reads this
  weight ~3x; never report it as tokens. Watched, not failed.
- **Probe null ≠ clean (F-#2):** a clean result is "swept N seed sections, probes (1)-(3) = 0 — PASS"
  (the inventory's section-audience-map row count is the swept-surface evidence).

**Delivered-protocol-weight sub-probe (report-only).** What a delivered spec carries inside
(history + code-detail share, threshold 5% per spec) and what each trigger delivers × its firings —
nine probes P1-P9, the `delivered_weight` block this theme's `inspect record` run attaches, severity
and the null ≠ clean line: the lens table is in part 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`
§Delivered-protocol-weight lens). Each run also takes two steps there : **P10 RE-CHECK** — two
specs trimmed since the last T7 run, every line of the trimming card's committed rule inventory checked
against the current delivered body and every MOVED home (the check: SPEC-0005 §3, `bin/yitc-v2 graph
query SPEC-0005`); a miss is a `deviation_captured` — and **P11 RANKING** — the top 5 specs by
`stage_entered` deliveries × current contract-view bytes, the heaviest labelled by the SPEC-0005 §3 classes.

**T7 sub-probe — hand-executed-procedure-should-be-a-verb (report-only candidate; per the 2026-07-04 kernel prose-vs-verb meta-analysis).**
A large AUTHORED-PROSE procedure the AI RE-READS and HAND-EXECUTES (a multi-step checklist / runbook /
liveness-recipe) is a CANDIDATE for encapsulation behind a single **read-only** verb — the authored-prose
twin of the generalization lens above; cross-tag **T4 context-economy**. **Report-only, NEVER a gate**;
disposition (build / extend / leave) is triage → a Build task + owner. Archetype: the dispatch-monitoring
liveness recipe (~880 lines re-run every batch) → `journal query --dispatch-status --fleet-verdict`.

**FREQUENCY GATE (load-bearing — the payoff is economy-per-load × LOAD-FREQUENCY-across-sessions).**
Nominate ONLY prose loaded + hand-executed FREQUENTLY across sessions. The evidence is the procedure's
own DECLARED TRIGGER (per session / per dispatch / per land = frequent; weekly or rarer = out) — there
is no journaled per-doc load receipt, so a run never waits on one. RARE-CADENCE activities (this roster,
big-plan-checklist authoring, emergency-mode, onboarding) are NOT candidates even if long (owner,
2026-07-04): **frequency, not size, is the gate.**

**Exclusions (not a finding):** rare-cadence activities; one-time onboarding reads; append-only logs;
pure teaching/judgment prose; any chunk ALREADY verb-delivered.

| Lens | Surfaces | Probes |
|---|---|---|
| **hand-executed-prose→verb** | `patterns/` + handbook + dispatch-injected procedures/runbooks/recipes whose declared trigger is frequent | classify each: frequent by declared trigger? deterministic-enough-to-encapsulate? extends-an-existing-verb (Principle 1)? → each qualifying chunk = ONE candidate naming (a) prose home + size, (b) the declared trigger, (c) extend-vs-new |

- **Probe null ≠ clean (F-#2):** a clean result names the frequently-triggered prose homes walked and
  their declared triggers, never a bare "none found".

### Themes carried in part 4 — T9 · T10

These two lens-checklists moved to **part 4** (`patterns/inspection-criteria-roster-portfolio-observation.md`, SPEC-0120 split)
VERBATIM when this part re-crossed the one-bounded-read BYTE ceiling; T10 then moved on, VERBATIM, to
**part 6** (`patterns/inspection-criteria-roster-real-work-observation.md`) when part 4 crossed it in turn. They are SERVED exactly as the
sections above: `inspect record --theme T<n>` resolves each in the part that holds it and hashes that
part's bytes, so their freshness is unchanged by the move.

- **T9** — Capability graduation & adoption (kernel↔consumer capability portfolio)
- **T10** — Real-work observation loop (cross-project worker×auditor PAIR observation)

They are NOT restated here, and no `### T<n> —` stub stands in for them: two served parts claiming
one section makes the resolver REFUSE rather than silently hash a stub. This heading is a
pointer, not a theme — it does not match the `### T<n> ` shape the theme reader looks for.

## Architecture-drift lens, drain obligation & what-homes-elsewhere → **part 2**

> The architecture-drift lens (SPEC-0080/0081), the drain-obligation pointer, and the
> what-homes-elsewhere pointers now live in **part 2**:
> **`patterns/inspection-criteria-roster-run-and-lenses.md`** (SPEC-0120 split).
