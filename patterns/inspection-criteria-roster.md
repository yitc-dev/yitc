---
name: inspection-criteria-roster
class: reference
sourced_from: <durable artifact> (drain-at-realize rule — a plan drains durable content to a stable home before terminal) + deviation `living-criteria-home-hosted-in-realized-terminal-plan` (the grounding incident — the inspection living-criteria were homed in an FSM plan that can reach realized/terminal) + owner-directive 2026-06-08 (option A — stand up the stable pattern home now so SPEC-0057 points at a real target) + SPEC-0057 (the inspection construct — the identity home this roster serves; §3 living-criteria home, §9 cadence model) + SPEC-0034 §realized (the drain-at-realize gate this home is the drain TARGET for) / plan unify-revizia-all-checks-under-one-construct-singl (the unification drain — absorbed the QUEUE.md §Re-review-triggers checks as roster rows + drained the realized roster plans' living-home role into this single map; QUEUE/runbook now POINT here)
applies_to: the freshness-hashed LIVING CRITERIA of the inspection roster — the `CADENCE` cadence values (parsed by `bin/lib/inspection.py parse_cadence`), the **operational-hygiene weekly checklist** (`inspect record --tier weekly` hashes it), and the **per-theme lens-checklists** (`inspect record --theme T<n>` hashes each) for **T1, T3, T7, T9, T10** — the remaining five, **T2, T4, T5, T6, T8**, are the co-equal PART 3 (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`, SPEC-0120 split), served and hashed there. This is PART 1; the umbrella NAVIGATION MAP (check → theme → cadence → how-to-run → rule-home, across the continuous-reflex / system-inspection / apex / consumer-local tiers) is the co-equal companion `patterns/inspection-criteria-roster-navigation-map.md` (SPEC-0120 byte-axis split), and the run-mode + cross-theme method + foundations + architecture-drift lens are PART 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split). This pattern is the durable HOME the criteria drain INTO; it is a doc home, not a mechanism/verb/store/rule (each rule it serves homes elsewhere — SPEC-0057 construct, SPEC-0034 drain-gate, SPEC-0055/0056 triage — it cites, it does not restate; SPEC-0005 rule 8 one-home). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — the living criteria (part 1: cadence · operational-hygiene · the T1 / T3 / T7 / T9 / T10 lens-checklists)

> **What this IS:** the freshness-hashed **living criteria** of the inspection roster — the
> `CADENCE` cadence values, the **operational-hygiene weekly checklist**, and the **per-theme
> lens-checklists for T1, T3, T7, T9, T10** (`bin/lib/inspection.py` hashes these three as the `criteria_ref` /
> `--tier weekly` freshness subjects, SPEC-0057 §6). The umbrella **navigation map** — one row per
> recurring check (check → theme → cadence → how-to-run → rule-home), across the continuous-reflex /
> system-inspection index / anti-complexity-apex / consumer-local tiers — is the co-equal companion
> **`patterns/inspection-criteria-roster-navigation-map.md`** (SPEC-0120 byte-axis split). The
> run-mode + cross-theme method + foundations + architecture-drift lens are the co-equal **part 2**
> (`patterns/inspection-criteria-roster-run-and-lenses.md`, SPEC-0120 split), and the
> **T2 / T4 / T5 / T6 / T8** lens-checklists are the co-equal **part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split). It is a **non-FSM
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
> **The T2 / T4 / T5 / T6 / T8 lens-checklists → part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split).

## The cadence model (per SPEC-0057 §9 — pointer, not restated)

Each roster row carries a **cadence tier** (a per-theme SETTING, §3 — NOT a new classifying axis).
The tiers (SPEC-0057 §9, owner-approved markup 2026-06-23):

| Tier | What runs | Cadence | Cost |
|---|---|---|---|
| **Continuous (reflexes)** | deviation capture, dissonance, file-on-observation | always; not scheduled | ~0 |
| **Operational hygiene** | parking-returns, blocked, MEMORY GC, postcheck-ready, overdue, lifecycle-integrity, read-gate, canary, cron-drift, soak-scan, bench-refresh, lesson-generalization | weekly | cheap — mostly one verb/view |
| **System inspection (T1–T10)** | the per-theme lens-checklists below (T2 / T4 / T5 / T6 / T8 in part 3) | monthly, themes ROTATED (~2–3 per cycle — a NON-NORMATIVE starting heuristic, not a governed threshold; the durable cadence is per-row) | costly — external audits / pattern-mining |
| **Anti-complexity apex** | v1-pattern accretion return + roster-currency | quarterly | medium |

**Manual-first (SPEC-0057 §2, UNCHANGED):** no cron / verb / auto-session runs an inspection; cadence
is owner-invoked. (A mechanical host-cron that only PRE-COMPUTES a digest — no AI session — is allowed;
an auto-SESSION is OUT until a CHARTER §6/§7 change. Both deferred as tracked `ideas/` seeds.)

**Machine-readable cadence values (the SINGLE parseable home —).** The per-tier cadence
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
| MEMORY.md buffer GC sweep | T5 | weekly | `buffer clean` / manual §5(c) sweep | SPEC-0039 §5(c) |
| Realize-ready postcheck plans | T5 | weekly | `plan list --status postcheck` + view `postcheck-plans-readiness`; finalize ready via `plan stage realized` (worktree) | SPEC-0034 §realized; |
| Read-gate discipline (kind-split refusal ratio) | T2 | weekly | `bin/yitc-v2 graph query discipline-ratio` | SPEC-0059 / |
| Host-leak canary backstop | T6 | weekly | `bin/yitc-v2 audit canary-backstop` | SPEC-0066 §3 |
| Bench regular-refresh cadence | T3/T4 | weekly | refresh per plan `ai-bench-operation-…` (its regular-refresh cadence section); cell-select by running `python3 dev-utilities/bench/rule-conformance.py` (the delivered v2-self bench script — NOT a `graph query` view; see lesson `rule-conformance-is-a-bench-script-not-a-graph-view`) | plan `ai-bench-operation-accumulating-tables-and-model-r`; SPEC-0047; lesson `rule-conformance-is-a-bench-script-not-a-graph-view` |
| Dispatch-worker lifecycle-integrity sweep | T3/T6 | weekly | `bin/yitc-v2 journal query --lifecycle-integrity` (`--since` to widen) | / |
| Overdue-recheck revisit sweep | T8 | weekly | `bin/yitc-v2 graph query overdue-recheck` | SPEC-0094 §3 / |
| Coordination-store backup-verify cron drift-check | T6 | weekly | **DIFFERENTIAL first, and it is the decisive one — user-INDEPENDENT:** `ls -lt <host-home>/.yitc-coordination/backups \| head -3` (the store dir is resolved by the ONE resolution site `cross.resolve_log_path` — `bin/verify-backup.sh` writes its snapshots to `<that dir>/backups`) — a snapshot dated within the last day at ~03:45 proves the job RAN (only the NAMES/dates are needed — the snapshot FILES are 0600, the dir itself is `o+rx`; access hinges on TRAVERSING `<host-home>`, which is `other::---` plus a per-user ACL — verified 2026-08-28 that collaborator `<collaborator>` reads this listing fine. An operator NOT on that ACL gets Permission denied, which is an ACCESS answer, not drift: fall back to `sudo -u dev ls -lt …`, and never to reinstall). A cron LINE that exists proves nothing about whether the job runs. Presence-check is SECONDARY and is USER-RELATIVE — the job lives in the OWNING account **`dev`**, so ask for THAT crontab: `sudo crontab -l -u dev \| grep yitc-coord-verify`; a bare `crontab -l` run by a non-`dev` operator returns 0 matches and reads as drift. REINSTALL ONLY IF THE DIFFERENTIAL IS STALE — never on an empty grep alone (that reading already filed a duplicate-install card, aiseller X-1137/X-1177 + kupiclub X-1141; a duplicate job installed in a non-owner crontab writes to a dev-only log dir and fails silently while this row reads green). | SPEC-0084;; |
| Born-waiver freshness — init placeholder never replaced (per-project `yitc-ops.yaml`) | T6/T7 | weekly | `bin/yitc-v2 nightly` (the per-project `born_waivers` check surfaces each stale waiver path) | SPEC-0093; SPEC-0105 §1; |
| Post-verification soak-scan | T8 | weekly | read each recent non-hygiene closure's `post_verification`; route per §1; file follow-ups via `task file` | SPEC-0048 §6 |
| Lesson generalization sweep | T5 | weekly | Review-judged generalization lens over `lessons/` (consolidate / promote-split / `cross request` / retire-narrow) | SPEC-0090 §2b |
| Journal growth + untriaged-capture pressure | T5/T7 | weekly | `bin/yitc-v2 graph query journal-hygiene` (report-only digest: events.jsonl size vs 10MB + the watermark-derived UNROUTED backlog) | SPEC-0052; SPEC-0055; |
| Land-verify concurrency stability — recurring/non-deterministic `fail_class` + scaling watch-points | T6 | weekly | run the one-liner in §T6 → **land-verify concurrency stability** (part 3) (surfaces `_verify_scaling_signals` Rule-3/4 signals + scans recent `land_completed` A4 `fail_class`); report-only | SPEC-0132 Rules 3-4; SPEC-0057 |
| Abort assertion legibility — what share of aborted lands can NAME what broke (mute share, waive-token bindability) | T6 | weekly | run the fold in §T6 → **abort assertion legibility** (part 3) — pass the repo root, so the SAME block runs under `-C <consumer>`; folds on the assertion TEXT, never `abort_class`; report-only | SPEC-0057; SPEC-0077 §3a;; kupiclub X-1050 |
| Parallel-landing health — formation width, queue carry & throughput trajectory | T6 | weekly | run the fold in §T6 → **parallel-landing health** (part 3) — pass the repo root, so the SAME block runs under `-C <consumer>` over its own journal; report-only | SPEC-0132; SPEC-0119; SPEC-0057; |
| Load-sensitive lane sequential tail — over bound? → dispose the global-rework question | T5 | weekly | `bin/yitc-v2 [-C <repo>] debt` — read the load-sensitive-lane line (count + serialized wall + which bound, if any, is crossed; never recompute it by hand). OVER EITHER BOUND record the disposition per §T5 → **load-sensitive lane over bound?** (part 3): a DATED line in this week's `inspect record --tier weekly` naming the two numbers and choosing (a) the global-rework card it files or (b) why not + a re-check date. Another per-file card is not a disposition; report-only | SPEC-0132 §3; SPEC-0119; / |
| Parallel-landing blockage — one cause across branches · dead lands · branches ahead of main | T6 | weekly | `bin/yitc-v2 [-C <repo>] debt` — read the rule-26, rule-23 and rule-24 lines (cited, never re-implemented — see §T6 → **parallel-landing health**, part 3) | SPEC-0119 rules 23/24/26 |
| Exercise-the-gated-paths — dry-run the gated/rarely-walked paths that never fire (deploy guard shape · non-owner verify · onboarding-delivery seam) | T6 | monthly | run the 3 exercises in §T6 → **exercise-the-gated-paths** (part 3) (each NON-mutating: `deploy --print-guard` · a `verify.layers[]` layer as a non-owner · the onboarding-delivery seam render); report-only | SPEC-0057; plan `anti-false-green-doctrine-differential-proven-chec`; X-0366 |
| Exemption-case revision — is the declared audit-post exemption still warranted, and is the feedback that would tell us alive? | T8 | monthly | `bin/yitc-v2 [-C <consumer>] inspect record --theme T8 --tracks primary,external` (the report-only `case_review` block: one four-field proposal per declared case + its covered share over the case's own `window_days`); see §T8 → **exemption-case revision** (part 3) | SPEC-0178 rules 7+9; SPEC-0057; |
| Reverse-adoption — runtime-vs-shipped divergence (live code with no governed-deploy provenance · proof debt · live-probe vs declared surface · host reconciliation drift) | T8 | monthly | run the 4 probes in §T8 → **reverse-adoption (runtime-vs-)** (part 3) (each read-only); report-only; a probe that could not run reports **not-run**, never "clean" | SPEC-0057; X-0366 |
| Production-readiness — what this project's derived profile REQUIRES and its `yitc-ops.yaml` does not answer | production-readiness lens (report-only; NOT a T1..T10 slot) | monthly, 20-minute box, since-last-run watermark (`inspection_completed`) | `bin/yitc-v2 [-C <repo>] debt` — read the rule-39 gap line — then `bin/yitc-v2 [-C <repo>] profile`; file AT MOST 1 profile-mismatch + 2 top-risk items per project per run, and record "no gap" EXPLICITLY when there is none | SPEC-0198; SPEC-0119 rule 39; SPEC-0100; |
| Done log size | T7 | monthly | observed grep/tooling friction ONLY — the ~500/~1500 marks are history, not triggers; KEEP-FLAT re-decided, count-branch retired | QUEUE.md §Done log;; |
| New owner observations → file new tasks | — | per session | `task file` | QUEUE.md §Re-review |

> **Triage sweep + window — retrieved (SPEC-0055).** The triage VERB (`bin/yitc-v2 triage`) sweeps the
> un-routed captures since the last watermark; window/route rules: `bin/yitc-v2 graph query SPEC-0055`.
> The weekly / monthly / per-session cadence above stays mandatory.

## Per-theme lens-checklists (T1–T10) — the living criteria

> **T1–T10 live across TWO parts.** THIS part carries **T1, T3, T7, T9, T10**; **T2, T4, T5, T6, T8**
> live in **part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`,
> SPEC-0120 split) — a pointer line stands at each of their places below. Both parts are
> SERVED: `inspect record --theme T<n>` resolves the section in whichever part holds it and hashes
> THAT part's bytes, so a moved checklist's `criteria_ref` names part 3 and stays as fresh
> as one that never moved.

Surfaces (M4) + probes (event/state/measurable). Base definitions converged from the 2026-05-31
dual-track calibration; the 2026-06 refresh (`inspection-list-refresh-…`, trial-converged) lens-deltas
are FOLDED in here. The run-by-run trial tracker / method-lesson narrative stays as HISTORY in those
realized plans (history, not a live list). Re-deepen each theme per run.

### Themes carried in part 3 — T2 · T4 · T5 · T6 · T8

These five lens-checklists live in **part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`, SPEC-0120 split), moved there
VERBATIM when this part re-crossed both one-bounded-read ceilings. They are SERVED exactly as the
sections below: `inspect record --theme T<n>` resolves each in part 3 and hashes part 3's bytes
, so their freshness is unchanged by the move.

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
  (spec anchor OR a below-admission marker; 2026-07 refresh); **event-catalog check on TWO
  levels** — types AND payload-keys, vs BOTH catalog homes SPEC-0025 + SPEC-0161 (substring match, not regex — regex gave false
  positives; ≥4-char token guard — short tokens pass by incidental substring; payload ground truth = a
  journal-window type→data-keys map; skipping the payload half is a HALF-RUN, not a run; a RECURRENT
  catalog-lag finding REQUIRES the carrier lookup in the finding body — 2026-07 refresh);
  **FSM-statement check** — every FSM assertion in the handbook ≡ its authoritative FSM home; **«no
  silent gaps» (full M4 walk)** — verb×governing-rule, lifecycle-step×description, event×SPEC-0025
  catalog, helper×spec-anchor; the defect is a SILENT gap, not absence of a spec per se.
- **Method:** read IMPL not help (M1); validate the probe (M2); scan the ACTIVE queue first;
  external track gets PRE-COMPUTED mechanical sweeps as input (it has no interpreter — chain/dangling
  sweeps were blocked); semantic diff stays its strength.
- **Repo-shape inputs — READ THESE BEFORE A T1 MECHANICAL PASS, on any repo (X-0666, boomrocket
  2026-08-06).** Every mechanical probe above takes repo-shape INPUTS — the FIVE boomrocket
  measured: **id namespaces**, **test roots**, **ledger/table shape**, **waive-contract shape**,
  **ledger-parse shape** — and each is **DERIVED FROM THE INSPECTED REPO**, never assumed to
  be the kernel's. Where to read each: id namespaces per the dangling-`cites` probe above; test roots
  per the roll-call sub-probe's Probe 3; ledger shape per its Probe 2; waive-contract shape likewise
  per Probe 2 — a contract field may be HOISTED into a table's section preamble instead of repeated
  per row, so the shape to read is where the row's fields actually come from, not one assumed
  per-row form; ledger-parse shape from the inspected ledger FILE's own sectioning — a ledger may be
  one table, or many sections a flat parse merges into one, so read how that file is cut before
  parsing it. (The last two are stated here because they are where boomrocket's false positives 4
  and 5 came from — X-0756, filed at our invitation in X-0755.) These five are T1 probe INPUTS; the
  rule about what an unvalidated pass YIELDS is no longer stated here — it was lifted, realm-agnostic
  and run-wide, to **part 2 §Run-mode → «Validate before you report»** (which carries the boomrocket
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
(`specs/<PROJECT>-rule-test-ledger.md`; kernel = `specs/yitc-v2-rule-test-ledger.md`, broad-mapped by
) — the ledger is the roll-call sheet: one row per atom, tripwire-or-waive (SPEC-0165 §8). The
axis READS the ledger, it does not re-home rules (P5 / SPEC-0005 rule 8; the spec stays the rule's home,
the test stays the proof, the ledger stays derived bookkeeping — never a parallel truth). **Scope
(SPEC-0165 §7):** only NORMATIVE rules of ACTIVE specs — descriptive/frozen specs are not rules. **Walk
order (SPEC-0165 §6):** by the COST of silent breakage (money → outbound mutations → isolation/access →
data mutations → background jobs).

| Lens | Surfaces | Probes |
|---|---|---|
| **rule→test roll-call** | the rule↔test ledger · the tier-1 normative-rule set of active specs · the tripwire suites the ledger links · the ledger's waive contracts | the 5 probes below |

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
- **Probe 5 — extend-before-create signal (SPEC-0165 §5):** a task that added a NEW standalone tripwire
  file whose rule already had a suite draws the review question «which existing rule suite did you
  extend?» — accretion (one-file-per-task-forever) is a finding, not coverage. Null ≠ clean: a clean
  roll-call carries the swept atom-set + the ledger revision as evidence, never a bare "none" (F-#2).

### T3 — AI-execution fidelity (boundary-watch, output-quality)

- **Surfaces:** journal intent↔actual (fed by `owner_directive`, 2073) + the AI-slip catalogue
  (deviations + `E-XXXX`) + git + the CHARTER 20-class list.
- **Probes:** M6 verdict-gating chronology; M7 claimed-artifacts-exist (enumerate the deviation
  catalogue; M2-validate synthetic fixtures e.g. ``); class tally (`from:` probe method, 2026-07: BODY-grep `from:`/`emergency:`, never trailer-parse; **exclude verb-generated
  bookkeeping by its GENERATOR, not by one literal subject** — the commits
  `worktree._land_bookkeeping_commit` mints, whose subject IS that helper's format string
  `<msg_prefix>: bookkeeping (<branch>)`. The filter is
  `^(land|worktree sync): bookkeeping \((task/T-[0-9]+|work/[a-z0-9._/-])\)$`, WHOLE-subject
  anchored. The verb alternation is the helper's `msg_prefix` set as CALLED in `bin/lib/`
  (`land` — worktree.py; `worktree sync` — worktree_lifecycle.py); naming only `land:`
  left the sync class reported as a `from:`-discipline violation on every run against
  body-less verb output nobody authored — X-1186 (aiseller 2026-08-27), the same
  phantom-violation shape as X-0591. Keyed on the GENERATOR because a per-literal fix makes every
  future `msg_prefix` the next false positive, discovered the same way. Anchored WHOLE-subject
  because the exclusion must key on provenance, not appearance: this reader has no minted sha to
  key on (the strictest-subject-shape discipline `debt._dead_land_tip_is_land_marker` already
  ships for the same forgeable-subject hazard), so a look-alike no generator produced —
  `land: bookkeeping for T-123`, or the two authored `land: bookkeeping (…) — <suffix>` commits in
  this history — does NOT match and is STILL reported; **exclude merge commits by a CASE-INSENSITIVE subject match —
  the filter is `(?i)^merge (branch|commit|remote-tracking)\b`, i.e. `git log --grep` needs `-i`, or
  use `--no-merges`. Capital-`M` `Merge branch …` is only git's DEFAULT wording; a hand-written
  lowercase `merge branch …` is the same class, and a case-SENSITIVE filter silently records it as a
  `from:`-discipline violation — the phantom-violation half of X-0591 (boomrocket 2026-08-06), which
  the case-sensitive form reproduces on every run**; every exclusion documented by fingerprint);
  **boundary-watch** — no
  de-facto multi-agent / orchestration creep in sessions (orchestrate posture owner-invoked + trial
  only; any appearance = P7 dissonance + decision, not silent acceptance; the 2026-07 fence set: execution-cue
  discipline SPEC-0141 — a work-cue is not a mode-cue; the dispatch advisor stays read-only SPEC-0136;
  autonomy stays batch-bounded SPEC-0126; intent↔actual also feeds on SPEC-0153 dispatch-correlation
  sections); **output-quality lens** —
  a constant external judge (frozen template; a change = a fingerprint change) over correctness /
  completeness / minimality of a completed task's diff; on code tasks the judge gets objective anchors
  (test results + AC probes); for multiple executors of one task, pairwise ranking in addition to
  scores. Dominant + recurring class: #7 hallucinated-context + #8 false-confidence («assert without
  verify»).
- **B5-delta — per-land verify-status (T3/T6; grounding: trend-finder B5, run_ref
  migration-b5-baseline-2026-06-28):** for EACH `land` in the window, check that land's recorded
  `consumer_verify` status — a foundational/backbone land with `consumer_verify: waiver` is a FINDING
  (it was not test-gated). A bare "land OK" count hides a waived-verify land (the blind track caught
  exactly what the primary's land-count missed).

### T7 — Anti-complexity / bloat (doc/code layering, generalization)

- **Surfaces:** the whole SPEC-0120 §1 **durable-doc set** — the handbook (CHARTER/AGENTS/LIFECYCLE/
  QUEUE/GRAPH + any read-order part) + `specs/` + `patterns/` + `lessons/` + `scenarios/` (size +
  language; the old "handbook size/trajectory" surface is the handbook SUBSET of this, widened by
); counts vs review-triggers (handbook 2000/2500 — node-volume counts (tasks, patterns,
  lessons, the frozen decision corpus) are NOT review-triggers, see probes); audit-YAML accretion;
  AGENTS injection cost; mechanism count vs v1; retirement use;
  the cost-view; adjacent state stores (`.yitc/`, `journal-sync-state/`, `views/`); **code**
  (`bin/yitc-v2` — dead branches, legacy aliases, parallel paths, duplicated logic between verbs;
   retirement candidates).
- **Probes:** each measured size/count vs its **governing** trigger (handbook 2000/2500) — report
  `fired? / acted?`; a fired-but-unacted trigger is a FINDING, not a clean measurement. **NODE-VOLUME
  counts are NOT such triggers:** there is NO numeric node-volume trigger for ANY node type — the
  per-node-type thresholds (`tasks<100`/`tasks>500`, `patterns<30`, `decisions<50`) were RETIRED
  (SPEC-0031 §Node-volume — counts grow with the work; consolidation/retirement is a regular
  Review judgement on observed cost, never a count-gate), as was the done-log `~500`/`~1500` mark
  (QUEUE §Done-log). The `decisions/` D-file count is additionally FROZEN monotonic history
  (`decision new` retired —), so it can never satisfy a ceiling. Measure node-volume
  anti-complexity by ACTIVE/displacement surfaces (audit-YAML accretion, injection mass — already in
  this row), **not** file-count.
  > **Dated re-base — no count-gate is the post-split answer (2026-07-17; patterns 61,
  > lessons 41).** The `patterns<30` trigger did not merely *predate* the SPEC-0089/0090 travel/local
  > split — it is a -retired count-gate that (`decisions<50`) and
  > (`tasks<100`/`patterns<30`) had ALREADY dropped from the then-live home. The roster
  > unification (commit 4f7005a72, 2026-06-23) re-introduced it by copying this parenthetical verbatim
  > from the FROZEN, banner-marked `plans/inspection-revizia-concept.md` instead of from the FIXED live
  > home, silently reverting both landed fixes. So the honest re-base is **not a new number**: post-split,
  > `patterns/` (traveling craft) and `lessons/` (local craft) are MEASURED, never gated. **Migration
  > note for the next single-home consolidation:** copy from the LIVE home, not the frozen predecessor —
  > a frozen doc preserves the bug its live twin already fixed.
  AGENTS lines/chars/≈tokens-per-load; hooks/gates/journals;
  superseded/withdrawn/terminal counts; **watch bloat-DISPLACEMENT** — caps held → accretion migrates
  to un-capped surfaces (decisions, audit-YAMLs, injection mass); quantify displacement against the
  calibration baseline (263→803 ×3.05/6d first measure); decisions-count EXCLUDES audit files from the
  `D-*.yaml` glob; **generalization lens (§2.7c)** — the constructive twin of retirement ( removes
  DEAD; this finds LIVE-but-DUPLICATED — parallel paths, kindred rules, verb-families with a common
  core, specs with overlapping subject) — RESOLVED by trial: NO T9 split, the consolidation lens stays
  in T7 (standing 2026-07 watch subject: the 6-spec security set SPEC-0145/0148/0149/0150/0154/0155 —
  one domain, overlap candidates for ONE consolidation review). **Feeds:** `trend-report`. Absence-claims must be evidence-grade over the WHOLE governed space
  (tasks all-status + plans + ideas + decisions-non-audit + MEMORY.md); a narrow sweep = needs-data;
  carry-forward each item → its found carrier (with status/parked-reason) or confirmed absence.
- **B5-delta — deploy-still-on-v1 dependency (grounding: trend-finder B5):** a migrated consumer whose
  deploy path still SOURCES the v1 framework (e.g. `deploy.sh` sourcing
  `ai-team-framework/.../deploy-common.sh`, incl. a fallback search) = INCOMPLETE v1 retirement — do
  NOT rationalize it as "intended shared infra" without an EXPLICIT recorded decision; absent that, it
  is a finding.
- **B5-delta — product-state-looks-like-v1 clarifier (grounding: trend-finder B5):** a repo-ROOT file
  whose NAME resembles an archived v1 governance file (e.g. `BACKLOG.md` / `DECISIONS.md`) may be
  INTENTIONAL product runtime-state, not v1 residue — verify provenance BEFORE flagging. Treat as
  product-state IFF all three hold: (1) a `docker-compose` bind-mount target, (2) created by a tracked
  consumer task, AND (3) `.gitignore`d so runtime appends don't pollute land/deploy. Lacking those
  three AND matching an archived v1 corpus name ⇒ treat as v1 residue (a finding).

**T7 sub-probe — durable-doc governance: SIZE band (2 axes) + LANGUAGE (report-only; per SPEC-0120).**
The methodology's own docs must stay legible + loadable: a durable doc is held to two standing
properties — it stays **small enough to load in one read** (the 400–500-line band) and (kernel) is
**English-only**. This sub-probe MEASURES both over the whole durable set; it is **report-only, NEVER
a gate** (CHARTER non-goal #2; SPEC-0080 P-A6 posture — identical to the Architecture-drift lens). The
carrier of the recorded metrics is the T7 run's **`inspection_completed`** event: `bin/yitc-v2 inspect
record --theme T7` attaches a report-only `durable_docs` block (per-doc
`{path, lines, bytes, est_tokens, cyrillic_lines}` + the derived buckets), and the verb PRINTS the
aggregate counts on both size axes plus a per-doc row for every FLAGGED doc. A `-C` consumer run scans
ITS OWN durable docs (the probe is engine-resident, travels with the engine — no per-project setup).

**Size is measured on TWO axes — lines AND bytes.** Lines alone under-read a DENSE doc: the
§3 band was grounded on ~25 tokens/line, but live-measured ~39.8 tok/line on the generated
worker seed, and measured a **1.7x density spread ACROSS the seed docs** (CHARTER ~102 B/line
vs AGENTS ~163 B/line). So a doc can sit comfortably in-band on LINES while its token weight nears the
reader's one-bounded-read page cap — line-clean, yet **single-read-UNSAFE**, which is precisely the
property §3 exists to protect. The byte axis is deterministic (`wc -c`, no tokenizer) and calibrated at
**~2.52 bytes/token** from live reader measurement; `est_tokens` is a derived REPORT figure,
never a gate input. The two axes are **independent**: a doc is flagged if EITHER trips.

| Lens | Surfaces | Probes (each → a CANDIDATE finding, never a block) |
|---|---|---|
| **durable-doc size** | the SPEC-0120 §1 durable set (handbook + `specs/` + `patterns/` + `lessons/` + `scenarios/`) | the 4 size-probes (2 per axis) + the language-probe below |

- **Probe SIZE-1 — over-band candidate, LINE axis (§3):** a durable doc >500 lines is a report-only split
  CANDIDATE (`durable_docs.over_band`). NOT a fail — a doc modestly over 500 with no clean coherent
  seam MAY stay up to the functional ceiling. Between 500 and the ceiling = "split at the next coherent
  seam", not urgent.
- **Probe SIZE-2 — over-ceiling must-split, LINE axis (§3):** a durable doc ≥~800 lines (beyond one bounded read —
  the ~25K-token page) is a MUST-SPLIT candidate (`durable_docs.over_ceiling`). The two size counts are
  reported **SEPARATELY** (over-band vs over-ceiling, DISJOINT buckets) — never merged into one number.
  When split, cut at a coherent seam + aim each part into the band (SPLIT, never delete content).
- **Probe SIZE-3 — over-band candidate, BYTE axis (§3):** a durable doc >40000 bytes is a report-only
  split CANDIDATE (`durable_docs.over_band_bytes`). The byte band mirrors the line band's proportion of
  its own ceiling (500/800 = 0.625 → 0.625 × 63000 ≈ 40000).
- **Probe SIZE-4 — over-ceiling must-split, BYTE axis (§3):** a durable doc ≥63000 bytes (25000 tokens ×
  ~2.52 B/token — the one-bounded-read page cap) is a MUST-SPLIT candidate
  (`durable_docs.over_ceiling_bytes`). Byte buckets are DISJOINT from each other and reported
  SEPARATELY, exactly as the line buckets are. **The differential is the point:** a doc that PASSES the
  line axis but trips a byte bucket is flagged on the byte axis ALONE — that is the single-read-unsafe
  dense doc the line-only probe silently called in-band.
- **Both size axes are REALM-AGNOSTIC** — they scan the methodology set in every realm (engine-self and
  `-C` consumer alike). Only the LANGUAGE axis below is kernel-realm-gated.
- **Probe LANGUAGE — kernel English-only (§2):** a mechanical Cyrillic scan
  (`grep -P '[А-Яа-яЁё]'`, `durable_docs.cyrillic` = per-doc Cyrillic-bearing-line count) over the
  durable set. **KERNEL-realm axis (SPEC-0120 §2/X-0208):** English-only binds by REALM — the
  probe flags a doc's Cyrillic ONLY engine-self (`REPO_ROOT == ENGINE_ROOT`). A `-C` consumer's own
  METHODOLOGY docs (`specs/`/`patterns/`/`lessons/`/`scenarios/`) are owner-language-allowed while
  project-local and are NOT language-flagged; the consumer's PRODUCT/management docs (product
  `CHARTER.md`/`README.md`, `BACKLOG`/`DECISIONS`/`MEMORY`) are likewise EXEMPT — so in a `-C` consumer
  NOTHING is language-flagged. English re-binds when a doc is PROMOTED into the engine's own methodology
  (the engine-self scan IS the promotion gate). Realised in code by the `durable_doc_metrics` `cyrillic`
  bucket populating only when `REPO_ROOT == ENGINE_ROOT`; the SIZE probe is UNCHANGED — it scans the
  methodology set in every realm. Report-only CANDIDATES; escalate a persistent false-positive on a
  legitimately-kernel doc to a declared `yitc-ops.yaml` allow-list ONLY on a real incident (CHARTER §P1
  F4), not before.
  **The bucket has an EXPECTED residue — read it against the declared allow-list.** SPEC-0120
  §2 carries a DECLARED allow-list (four grounds: the probe's own character class; owner-cue lexicons
  matched literally; owner-facing output templates stored verbatim; verbatim quoted historical records),
  and because the probe stays REPORT-ONLY the docs it covers KEEP APPEARING in `durable_docs.cyrillic`.
  So a non-empty bucket is not by itself a finding: check each path against that list, and report only
  what is NOT on it. That residue is what makes a genuinely NEW violation visible instead of hiding it
  inside an old exemption. Single-SoT — the list lives in SPEC-0120 §2 and is NOT copied here.
- **Probe null ≠ clean (F-#2), held by the RESULT CONTRACT (SPEC-0173 rules 1+2):** a clean
  result is never a bare "none found". The shape is defined at ONE site —
  `bin/lib/inspection.py#result_contract` — and this roster does not re-spell it, it points at it. The
  three fields it merges into `durable_docs` are: `swept` (how many surfaces were ACTUALLY looked at),
  `excluded` (rows of `{class, reason, files, bytes}` — the classes the scan cannot reach BY
  CONSTRUCTION, reason `exempt` / `out-of-realm` / `unscanned`), and `no_data` (rule 1 — a run that
  swept nothing produced NO VERDICT and is rendered NO-DATA, never as a clean run with zero findings).
  So a clean T7 result reads "swept N, excluded <the named classes>, 0 over-band / 0 over-ceiling /
  0 over-band-bytes / 0 over-ceiling-bytes / 0 Cyrillic". The `swept` count alone is NOT the
  swept-surface evidence any more: it counts what WAS looked at and can never surface what was
  unreachable — the class that let a 93,857-byte rule-test ledger sit above the ceiling while the run
  reported its over-ceiling set EMPTY.

**T7 sub-probe — worker-seed audience guard: no controller-content re-accretion (HARD-fail; per SPEC-0127).**
The dispatched **Worker** boots a per-audience seed (the `core`+`worker` sections), NOT the full
handbook — so Controller-only content must NOT re-accrete into that worker seed over time. Unlike the
durable-doc sub-probe above (report-only candidates), the two audience invariants here are **HARD** —
a violation is a HIGH finding that must be fixed, not merely noted (SPEC-0127 §5). The state-check the
inspection READS is the already-generated **`graph/worker-startup-inventory.md`** §HARD PROBE (derived
by `bin/yitc-v2 graph build` from the seed docs' `<!--AUDIENCE:core|controller|worker-->` section
markers) — no new mechanism: the inventory computes both probes; this criterion is the
recurring READ of them. This is NOT a land gate (SPEC-0057 manual-first, report-only posture — the
committed==regenerated DRIFT is what `graph conformance` enforces; the HARD PROBE is read at inspection
time). **How to run:** `bin/yitc-v2 graph build`, then read `graph/worker-startup-inventory.md`
§HARD PROBE — BOTH probes MUST read `PASS`.

| Lens | Surfaces | Probes |
|---|---|---|
| **worker-seed audience guard** | the generated `graph/worker-startup-inventory.md` (derived from the `<!--AUDIENCE:...-->` section markers on CHARTER/AGENTS*/LIFECYCLE/QUEUE/GRAPH) | the 3 probes below |

- **Probe LEAK (HARD, §5 condition 1) — controller content in the worker seed:** inventory line
  `(1) controller-tagged sections inside the worker seed: N` — **N MUST be 0**; any nonzero is a HARD
  FAIL (a `controller`-tagged section leaked into the assembled worker seed — a resolution/assembly
  bug or a mis-tag). The detector scans the ACTUAL generated worker-seed string for each controller
  section's own heading (not the tautological effective-audience recompute).
- **Probe UNTAGGED (HARD, §5 condition 2) — 0 untagged seed sections required:** inventory line
  `(2) untagged #/## seed sections: N` — **N MUST be 0**; any untagged `#`/`##` seed section is a HARD
  FAIL. Runtime resolution defaults untagged → `core` for safety, but a section MUST be EXPLICITLY
  tagged — so a forgotten controller-only section cannot silently re-accrete as core (SPEC-0124 consult
  option 1). The inventory lists each offending section under "Untagged #/## sections".
- **Probe SIZE (report-only drift signal, §5):** inventory lines `worker-seed content lines:` /
  `worker-seed tokens:` are a report-only drift signal (no hard threshold until the owner sets one) —
  a growing worker seed is watched, not failed.
- **Probe null ≠ clean (F-#2):** a clean result is "swept N seed sections, probe 1 = 0 — PASS, probe
  2 = 0 — PASS" (the inventory's own section-audience-map row count is the swept-surface evidence),
  never a bare "none found".

**T7 sub-probe — hand-executed-procedure-should-be-a-verb (report-only candidate; per the 2026-07-04 kernel prose-vs-verb meta-analysis).**
A large, tangled AUTHORED-PROSE procedure the AI RE-READS and HAND-EXECUTES — a multi-step
checklist/runbook/liveness-recipe re-loaded and hand-applied — is a CANDIDATE for encapsulation behind a
single **read-only** verb: the AI CALLS the verb and gets a result/checklist back, instead of re-loading
+ hand-running 100s of lines of nuanced prose (context economy + execution clarity + fewer recurring
hand-errors). This is the authored-prose twin of the T7 **generalization lens (§2.7c)** above; cross-tag
**T4 context-economy** as its cost dimension. **Report-only, NEVER a gate** (identical posture to the
durable-doc sub-probe); disposition (build / extend / leave) is triage → a Build task + owner. The
archetype found by the meta-analysis: the dispatch-monitoring liveness recipe (~880 lines re-run every
batch) → a read-only `journal query --dispatch-status --fleet-verdict` extension.

**FREQUENCY GATE (load-bearing — the payoff is economy-per-load × LOAD-FREQUENCY-across-sessions).**
Nominate ONLY prose loaded + hand-executed FREQUENTLY across the system's sessions (per-session /
near-daily — e.g. the dispatch liveness recipe re-run every batch). A **RARE-CADENCE** activity — the
weekly revizia roster/runbook itself, big-plan-checklist authoring, emergency-mode, onboarding — is
**NOT a candidate even if internally long and repetitive**: loading a bit more prose once a week is
cheaper than carrying a verb, and a verb there is anti-complexity bloat for marginal gain (owner,
2026-07-04). **Frequency-across-sessions, not size, is the gate.** (Self-note: this roster is itself
rare-cadence — so it is correctly OUT of scope by its own gate.)

**Exclusions (not a finding):** rare-cadence activities (above); one-time onboarding reads; append-only
logs; pure teaching/judgment prose (a rubric of judgments is not mechanizable); any chunk ALREADY
verb-delivered.

| Lens | Surfaces | Probes |
|---|---|---|
| **hand-executed-prose→verb** | `patterns/` + handbook procedures/runbooks/liveness-recipes re-loaded FREQUENTLY across sessions | classify each: loaded-frequently-across-sessions (NOT rare-cadence)? deterministic-enough-to-encapsulate? extends-an-existing-verb (Principle 1)? → each qualifying chunk = ONE candidate finding naming (a) prose home + line count, (b) re-execution FREQUENCY evidence, (c) extend-vs-new |

- **Probe null ≠ clean (F-#2):** a clean result carries the swept-surface evidence (which
  frequently-loaded prose homes were walked + their per-session load frequency), never a bare "none found".

### T9 — Capability graduation & adoption (kernel↔consumer capability portfolio)

**Identity.** T9 scans the **capability PORTFOLIO** — the running question «what cross-cutting
capability should the KERNEL offer projects, and what should each PROJECT adopt or build?». It is a
periodic SCAN, not a gate, and it owns ONLY the portfolio *graduate/adopt/local/waive/return*
decision. It does **not** re-run health/reuse/adoption checks — those stay in T6 (operational
integrity), T7 (generalization), T8 (adoption of shipped V2 capabilities); T9 POINTS at them, never
duplicates (guardrail against double-home).

**Hard boundary (CHARTER §6).** The kernel only OFFERS + GRADES a project-declared,
project-owned probe (the SPEC-0110 adapter shape). Container-restart, self-heal, and runtime
ownership stay the PRODUCT's (docker `restart:` etc.) — never a kernel autopilot. Design lineage:
`decisions/kernel-runtime-monitoring-doctrine-audit-adhoc.yaml` +
`decisions/capability-inspection-theme-audit-adhoc.yaml` (both external-audited).

**Two lenses (run the one that fits the checkout):**

- **KERNEL lens — «is candidate X ripe to GRADUATE into an adoptable offering?»** Probe (derived,
  no new store): ≥2 projects hold a divergent LOCAL copy of X (grep sibling repos) **OR** ≥N open
  `cross request`s pull for X **OR** the SPEC-0104 cross-project comparison lens surfaced ≥2 siblings
  that solved X. Ripe → file the offering as an `adoptable` extension (SPEC-0101) or a shared-CODE
  extraction (X-0205 / SPEC-0122); not ripe → leave on the raw surface.
- **PROJECT lens (run under `-C <project>`) — «do I NEED capability X yet?»** Outcomes (each
  event/state-checkable): **(a) have it** — declared in this project's `yitc-ops.yaml` / an adopted
  `extensions:` entry → nothing; **(b) need it, kernel offers it** (`adoptable`) → adopt the
  offering; **(c) need it, no kernel offering yet** → build it LOCALLY (product realm) AND emit a
  `cross request` pull-signal to the kernel (feeds the KERNEL lens above — the demand→graduation
  loop); **(d) not yet** → record a parked `return_trigger`.

**No new state (guardrail).** Every T9 signal is DERIVED from an existing mechanism — `cross`
requests, sibling-repo local-copy grep, `yitc-ops.yaml` / `adoptable` declarations, parked-task
`return_trigger`s, the SPEC-0104 lens. T9 adds no store, no status field, no FSM.

**4-filter admission (SPEC-0057 owner-gated new-theme bar; owner directive 2026-07-04).** F1 existing
analog = the inspection roster itself (reused, not a parallel mechanism). F2 view/content, not a new
entity (a theme = a lens-checklist). F3 removed = the «file a plan/card per candidate capability»
escalation (candidates now live on the raw surface until a real pull graduates them). F4 real pull =
the 2026-07-04 owner thread + the grow-on-pull L1/L2/L3 precedent (SPEC-0105/0106/0107→0110).

#### T9 ACTIVE rows (probe-shaped — the only rows an inspection run acts on)

| Capability | Probe (event/state) | Placement | Source-signal | Return / retire |
|---|---|---|---|---|
| Runtime error alerting (500s / exceptions) | project declares an error-alert sink (or waives); prod-serving project without one = open row | kernel-adoptable (declare-or-waive marker; grades presence, not the sink) | ≥2 projects wire ad-hoc error alerting | retire when an offering exists + adopted |
| Backup restore-DRILL | project's backup is periodically RESTORE-verified, not just taken (state: last restore-drill age vs threshold) | kernel-adoptable — GRADE-only (grades the operator-RUN drill's last-run age, SPEC-0110 shape; the kernel NEVER runs the drill — operator-owned) | recurring backup-exists-but-never-restored gap | retire when the drill's freshness is graded by the SPEC-0110 monitor + adopted |

#### T9 RAW candidate surface (idea-pool — NO obligation; each tagged; promote to an ACTIVE row only when a probe exists)

Tags: `existing-pointer` (already an offering — see the cited spec) · `kernel-adoptable` (candidate
offering) · `product-local` (project-only, kernel does not offer) · `other-theme` (belongs to T6/T7/T8).

**Graduation records (RECORD-ONLY — an `existing-pointer` capability already born in the kernel; no
new mechanism).** A row promoted to `existing-pointer` because the offering already ships gets a
one-line record here naming its adopt path + adoption/conformance probe — not a new detector (each
cited spec keeps its own anti-detector stance):

- **Consumer provider-neutral context-home + thin vendor adapter → SPEC-0125** (owner
  directive 2026-07-10, RECORD-ONLY). **Adopt path:** `bin/yitc-v2 -C <project> init` unconditionally
  stands up the thin vendor adapter + populated neutral project-context home (the `consumer_init` born
  event; impl `bin/lib/init.py#_ensure_consumer_vendor_adapter`) — mandatory-born, not opt-in.
  **Adoption/conformance probe:** the rollout wave (done, resolves X-0163/X-0164) —
  conformance cross trail **X-0291..X-0294** (kupiclub / boomrocket / bc-community / trend-finder:
  thin adapter VP1-clean + populated neutral home VP2-met). SPEC-0125's declined drift-detector/lock
  stance stands — no conformance mechanism is added here (this is a pointer, not a gate).

- **Frontend availability / uptime → SPEC-0174** (validate pass 2026-08-25, RECORD-ONLY —
  RETIRED from the T9 ACTIVE rows above by that row's own `retire when graduated to an adoptable
  extension` condition, now MET). **Adopt path:** declare a `freshness:` section whose adapter probes
  the live HTTP surface, carrying the MANDATORY `freshness.reachability.target` naming the address it
  reaches (SPEC-0110 rule 6), and cite SPEC-0174 in `extensions.adopts[]`; a project with no live
  edge WAIVES in `extensions.waives[]` with a forward-aware reason. Grade-only — the kernel never
  issues a request of its own (SPEC-0174 rule 2). **Adoption/conformance probe:** the rollout
  (done) — one cross ask per consumer, trail **X-0645..X-0653**; three consumers landed an adoption.

  **VALIDATED classification — all TEN registry `yitc_v2` consumers, each read from its OWN declared
  shape in `<project>/yitc-ops.yaml`.** Note the DENOMINATOR MOVED: this row was filed
  against NINE projects; ai-safety was registered as a first-class consumer afterwards, so the
  population is ten.
  - **Declared (3)** — `extensions.adopts[] spec: SPEC-0174` + `freshness.reachability.target`:
    boomrocket (`https://boomrocket.me/api/v1/health`, plus the `*/15` host cron
    `product_cron.host_crons[boomrocket-edge-availability]`) · aiseller
    (`https://aiseller.glukonair.ru`) · social-scraper (`http://<ip>:8002/health`).
  - **Waived (3)** — explicit `extensions.waives[] spec: SPEC-0174`, forward-aware reason: kupiclub
    (waive is about VALUE not applicability — live edge, deploy seam covered by the adopted SPEC-0094
    `live_probe`, no unnoticed-outage incident; owner waive 2026-08-13, X-0645) · bc-community
    (X-0646) · ticket-review (X-0650).
  - **Open (4)** — `extensions:` section PRESENT with a `waives:` list but NO SPEC-0174 entry in
    either list, so the declare-or-waive is genuinely outstanding; each already holds a LIVE
    cross ask, so nothing further is owed from the kernel: cardlab (X-0647) · social-parser /
    trend-finder (X-0648, the one open row with a real UI + live deploy) · ai-safety (X-0651) ·
    ai-gateway (X-0653).

  **The key-name grep does NOT reproduce this result, in EITHER direction — it is why this row was
  filed at candidate grade (X-0851 precedent).** `grep -ic uptime` over the whole of each consumer's
  `yitc-ops.yaml` gives boomrocket 2, all others 0. Both of boomrocket's lines are PROSE inside an
  `alert_routing:` comment stating «THIS IS NOT EXTERNAL UPTIME MONITORING» — not a declaration; and
  the nine «misses» conceal three adoptions and three explicit waivers. No `uptime:` carrier exists
  anywhere: no SPEC-0093 concern declares a `section:`/`carrier_path:` of that name, so the literal
  key could never have been the answer. Read each project's declared shape; never the key name.

- **Runtime health & availability:** container health + restart-policy declared `kernel-adoptable`;
  TLS cert-expiry `kernel-adoptable`; host resource watch (disk/mem/inode) `kernel-adoptable`
  (near SPEC-0105/0111); upstream-dependency reachability (external APIs / DB) `kernel-adoptable`;
  queue/worker liveness `product-local`; external-API rate-limit/quota headroom `product-local`.
- **Data & jobs:** data/output freshness `existing-pointer` (SPEC-0110); cron/scheduled-work
  governance `existing-pointer` (L2, in-flight plan); data-integrity / schema-drift `product-local`;
  DB-migration discipline `product-local`; retention / data-lifecycle `product-local`.
- **Errors & observability:** log retention/aggregation `kernel-adoptable`; telemetry/analytics wired
  `product-local`; tracing / request-id propagation `product-local`; SLO/SLA tracking `product-local`.
- **Security & deps:** secrets declaration + rotation reminder `kernel-adoptable`; dependency
  freshness / CVE scan `kernel-adoptable`; auth/authz baseline `other-theme`/doctrine (X-0205 shared
  PATTERN); access-audit / least-privilege `product-local`; pentest cadence `product-local`;
  supply-chain / lockfile integrity `product-local`.
- **Build & quality (UI):** UI baseline / design-system `existing-pointer` (SPEC-0093 `ui.baseline` +
  SPEC-0100); test taxonomy `existing-pointer` (SPEC-0093 `tests.classes`); perf/bundle budget
  (Lighthouse) `product-local`; accessibility `product-local`; visual-regression `product-local`;
  i18n/l10n `product-local`; SEO/meta `product-local`.
- **Ops & deploy:** deploy smoke gate `existing-pointer` (SPEC-0094); rollback-rehearsal cadence
  `kernel-adoptable`; canary/blue-green `product-local`; feature-flag discipline `product-local`;
  environment parity (staging≈prod) `product-local`.
- **Cost & capacity:** cloud/API spend monitoring `product-local`; capacity/scaling headroom
  `product-local`.
- **Reuse & shared code:** shared-CODE extraction `other-theme`/doctrine (X-0205 + plan
  `extract-the-ticket-review-system-into-a-shared-cro`); cross-project engineering-knowledge exchange
  `other-theme` (idea `engineering-knowledge-exchange-between-projects`); shared-PATTERN promotion
  `other-theme` (T7/SPEC-0090 lesson-generalization).
- **Docs & onboarding:** README/runbook currency `product-local`; per-project onboarding runbook
  `product-local`; API/contract docs `product-local`; consumer provider-neutral project-context home
  + thin vendor-adapter (thin `<vendor-adapter>.md` → neutral home) `existing-pointer` (SPEC-0125).
- **Auditor-added families (2026-07-04):** incident/alert routing `kernel-adoptable`; DNS/domain
  expiry `kernel-adoptable`; config/env validation `kernel-adoptable`; API contract/versioning
  `product-local`; PII / data classification `product-local`.

### T10 — Real-work observation loop (cross-project worker×auditor PAIR observation)

**Identity.** T10 scans the **real-work observation loop** (SPEC-0135): across ALL v2 projects, which
AI configurations actually ran and how they fared. Its identity is the **worker×auditor PAIR** —
`provider×model×effort` on each side — the worker (session_started) joined by `session_ref` to the
external auditor (external_audit_completed). It answers "which way to move": which pair to recommend to
users, where discipline breaks, how to size hardware per project class. A periodic SCAN, not a gate.

**Probe (derived, no new store).** The KERNEL cross-project rollup lens:
`bin/yitc-v2 graph query observation-rollup` — enumerates every registry `yitc_v2` project (kernel
included, via the read-only nightly enumeration seam, SPEC-0105 §2), reads each project's
`events.jsonl`, and returns worker×auditor PAIR slices with **sample_size + project_count + raw
verdict counts** per pair. The per-PROJECT companion is `graph query observation [project]` (a single
project measuring itself). No new store/event — pure read-time derived (SPEC-0135 §1/§3).

**FINDINGS not scores — the §4 fence HELD (the load-bearing invariant).** T10 emits FINDINGS, never a
composite quality SCORE and never a universal «best pair». The `observation-rollup` payload carries the
`no_best_pair` note by construction; a T10 run reads each pair ONLY against its own `sample_size`
(confidence), and pairs are ordered by sample-size (confidence), NOT ranked by quality. A low-sample
pair is a low-confidence observation, not a verdict. This is SPEC-0057 §4 (EVALUATION = THE FINDINGS,
NOT A COLOR) applied to the observation loop — do not invent a rubric/band/score on top of the counts.

**What a run does (findings, event/state-checkable).** (a) run `observation-rollup`; (b) read the
high-sample pairs against their verdict-mix (GREEN/YELLOW/RED/ABORT counts) — a pair with a materially
worse verdict-mix at adequate sample is a FINDING (steer away / investigate), never a score — and
  never a CAUSAL steer without controlling for task class: SPEC-0072 blast-radius routing sends harder
  tasks to higher-effort pairs, confounding the mix (2026-07); (c) note
pairs whose sample is too thin to say anything (findings = «insufficient data», file a soak follow-up,
do NOT rank them); (d) surface cross-project divergence (a pair healthy in one project, poor in
another) as a discipline/environment finding. Cost is NOT in this rollup (cross-project cost needs each
project's local transcript archive — SPEC-0135 §3; the per-project `observation` view owns read-time
cost). Route findings to the one nonconformity sink like every theme (SPEC-0055/0056); emit one
`inspection_completed` (theme=T10) per run even on zero findings (SPEC-0057 §6).

**No new state (guardrail).** Every T10 signal is DERIVED from existing events (session_started worker
triple + external_audit_completed auditor triple, both) via existing saved-view carriers. T10
adds no store, no status field, no FSM, no score — it is the observation loop's periodic read.

**4-filter admission (SPEC-0057 owner-gated new-theme bar; observation-loop plan).** F1
existing analog = the inspection roster itself + the `observation`/`observation-rollup` saved-view
family (reused, not a parallel mechanism). F2 view/content, not a new entity (a theme = a
lens-checklist over an existing derived view). F3 removed = the ad-hoc "where to look to see how
AI» question that had no periodic home. F4 real pull = the SPEC-0135 doctrine + the CHARTER
§Success-criteria measurement gap it closes (the 10th inspection theme SPEC-0135 §Scenario names).

## Architecture-drift lens, drain obligation & what-homes-elsewhere → **part 2**

> The architecture-drift lens (SPEC-0080/0081), the drain-obligation pointer, and the
> what-homes-elsewhere pointers now live in **part 2**:
> **`patterns/inspection-criteria-roster-run-and-lenses.md`** (SPEC-0120 split).
