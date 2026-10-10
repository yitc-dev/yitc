---
name: inspection-criteria-roster-themes-integrity-adoption
class: reference
sourced_from: <durable artifact> (SPEC-0120 byte-ceiling split of patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md — part 3 sat at 710 lines / 62,749 bytes, 251 B under the 63,000 B one-bounded-read ceiling with the T5/T6/T8 folds of plan inspection-list-refresh-2026-09-delta-recalibratio still to land; the T6 and T8 lens-checklists re-home here VERBATIM per SPLIT-never-delete, size-fence exit (b) for part 3) (the part-1 → part-4 precedent this copies shape for shape) (bin/lib/inspection.py resolves per-theme sections across the DECLARED parts in ROSTER_CRITERIA_PART_SUFFIXES, so a moved theme keeps an honest freshness hash) + SPEC-0120 (durable-doc size governance) + SPEC-0057 (the inspection construct — §3 living-criteria home)
applies_to: PART 5 of the single living inspection home (SPEC-0057) — the freshness-hashed per-theme lens-checklists for T6 (operational integrity) and T8 (adoption). `inspect record --theme T<n>` hashes each section HERE, resolved through the declared-part tuple. Part 1 (`patterns/inspection-criteria-roster.md`) keeps the `CADENCE` values, the operational-hygiene weekly checklist and the T1 / T3 / T7 lens-checklists; part 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`) the run-mode + cross-theme method + foundations + architecture-drift lens; part 3 (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`) the T2 / T4 / T5 lens-checklists; part 4 (`patterns/inspection-criteria-roster-portfolio-observation.md`) the T9 lens-checklist; part 6 (`patterns/inspection-criteria-roster-real-work-observation.md`) the T10 lens-checklist; the umbrella navigation map is `patterns/inspection-criteria-roster-navigation-map.md`. All six files are ONE living home split for loadability (SPEC-0120). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — part 5 (the operational-integrity & adoption lens-checklists)

> **What this IS:** PART 5 of the single living inspection home (SPEC-0057) — the freshness-hashed
> **per-theme lens-checklists** for **T6 and T8**, split out of
> `patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md` (PART 3) under the SPEC-0120
> one-bounded-read byte ceiling. Content is VERBATIM (SPLIT-never-delete): these sections are
> byte-identical to the ones part 3 carried, so `inspect record --theme T6|T8` reproduces the SAME section
> hash here — only the `criteria_ref` path changed. No pointer stub was left behind under a `### T<n> —`
> heading: one section, one home (a second claimant makes the resolver refuse).
>
> **The other parts:** cadence · operational-hygiene weekly checklist · T1 / T3 / T7 → **part 1**
> (`patterns/inspection-criteria-roster.md`). Run-mode · cross-theme method · foundations ·
> architecture-drift lens → **part 2** (`patterns/inspection-criteria-roster-run-and-lenses.md`).
> T2 / T4 / T5 → **part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`).
> T9 → **part 4** (`patterns/inspection-criteria-roster-portfolio-observation.md`). T10 → **part 6**
> (`patterns/inspection-criteria-roster-real-work-observation.md`). The umbrella
> navigation map → **`patterns/inspection-criteria-roster-navigation-map.md`**.

## Per-theme lens-checklists (part 5) — the living criteria

### T6 — Operational integrity

- **Surfaces:** tests (RED-GREEN; primary owns); `events.jsonl` integrity; graph
  reproducibility; `land`; deps; secrets; read-verb side-effects; worktree session-stamps + claim
  semantics; the `LAND:` token contract; the verify infrastructure (undated — re-read the specs, not a list):
  test-host isolation (SPEC-0041), hermetic sandbox + its data floor (<workshop-spec>/0175), the admission governor
  (SPEC-0132), anti-false-green admission (SPEC-0156), `--rebaseline` (SPEC-0077); **every verify SHORTCUT** —
  re-verify skip, inert canary skip, batch landing + member verdicts, pinned policy, remote venue, `--no-tests`,
  withheld tail write — since a skipped verify is where a false green enters; destructive hygiene sweeps
  (a `worktree_swept` item of kind `worktree` under the worktree root, i.e. a REGISTERED one, is a FINDING); **derived-artifact growth vs fixed-offset guards** (a generated artifact
  grows → an unrelated task's guard fires — the / class); session-identity integrity
  (SPEC-0137 ref carry, fail-closed rediscovery); integrity probes read the MAIN-checkout journal;
  B5 declare-or-waive is CONSUMER-scoped (engine-self is excluded by identity, SPEC-0186 rule 6); **MCP external-mutation
  capture** (SPEC-0118 — a substantive external write through any MCP tool must leave a journal line
  like a deploy does).
- **Probes:** tests exit-0 (in a WRITABLE checkout); **journal tests_failed read PAIRED, never flat** — a
  `tests_failed` counts as RED only when UNPAIRED (no LATER `tests_passed` for the same task); a paired
  red→green is the Stage-6 loop working and is reported as a count, never a finding (see **tests
  red→green pairing** below; the 2026-09-23 external track read 5 paired reds as a HIGH); a **RED-path canary** (deliberate-fail → FAIL+exit
  1 — suite-green alone does not prove failures surface); parse/dedup; ts-backsteps = structural-by-design
  (union-merge interleave at land — parse+dedup, monotonicity is NOT the contract); **in-memory graph
  rebuild ×2 idempotent + diff-vs-committed explainable by new artifacts** (bare `==committed` does not
  hold in a live repo); land ff-only (the «merges» are branch-side update-from-main); **ALL imports
  incl function-level** (the PyYAML miss — not top-level `^import`); secret grep; **stamp check** — the
  `yitc-session-stamp.json` lives in the PRIVATE git dir (`.git/worktrees/<name>/`), not the worktree;
  claim-enforcement proven by TEST NAMES (t0362 4/4 + claim-guard + picker-exclusion), not stamp-file
  presence; **MCP capture-delivery (SPEC-0118)** — for a session that drove a substantive external
  write through an MCP tool, the journal carries the outbound-external-mutation capture line (the
  capture-delivery contract, the `outbound-external-mutation` floor); a silent MCP-driven external
  write is a FINDING (M8 presence≠absence — zero capture-lines is no-data, not proof-of-compliance).
  **Shortcut soundness:** per shortcut in Surfaces, count its rows and the ones that lost their
  evidence — a rebaseline with no reason, a batch member verdict `unaccounted`, a tail write withheld,
  a land-ok task branch with neither `task_picked` nor `worktree_created`; each such row is a FINDING.
  **Feeds:** `trend-report`. **No decreed threshold:** land-verify time is a TRAJECTORY read off the
  SPEC-0132 Tier-C signals (the 2026-06-17 60s/120s line was permanently exceeded — 372 s median
  2026-07..09 — and carried no information); test-leak share has no carrier (NO-DATA until one exists);
  graph: two in-memory rebuilds MUST be identical (any difference = RED), and a diff vs committed is a
  finding only when not explained by new artifacts.
- **pinned-gate RED triage — which of three causes, and the remedy for each.** A pinned
  last-green gate going RED has three causes with three different remedies, and reaching for the
  wrong one is how a gate gets weakened to make a red go away. Classify BEFORE acting (SPEC-0191
  §5 block-classification; the default under uncertainty is STOP):
  - **2a — TIMING.** The red is a wall-clock / admission-wait artifact, not a subject failure: the
    assertion is about duration, or the test lost its slot under SPEC-0132 contention. **Remedy:**
    re-run under the admission path; if it REPRODUCES, hermetize or bound the offending test **at
    source** (<workshop-spec>). **Never widen the timeout** — that converts a measurable flake into an
    invisible one, and the widened bound outlives everyone who remembers why.
  - **2b — CORPUS-CENSUS.** A census / count assertion drifted because the CORPUS grew, and the diff
    never touched the counted subject (the / derived-artifact-growth-vs-fixed-offset
    class). **Remedy:** REBASELINE the pinned last-green, with the mechanical tie — the diff, the
    named assertion, the pre-existing audited artifact — recorded in `--rebaseline-reason`
    (SPEC-0077 §3a incidental staleness, LIFECYCLE §Two-flow-types carve-out). Only on a **fresh
    GREEN audit-post**; never a silent bump, and never as a way past 2c.
  - **2c — CHANGED-SUBJECT.** The diff really did move the asserted subject: this is a TRUE SIGNAL
    and the gate is doing its job. **Remedy:** fix **in scope** and re-audit the new commit. Where
    the cause is OUT of scope or environmental, `blocked-on-land` with the **verbatim failing
    assertions** (SPEC-0103) — the contracted escalation is the correct outcome, not a failure.
    Never weaken, skip or delete the assertion to pass.
  **The classification is evidence-bearing, not a vibe:** 2b is the only one a worker may
  self-clear, and only on the mechanical tie above; an unproven flake, a deliberate guard, or ANY
  uncertain block is a HALT (SPEC-0191 §5 three-rung ladder). **Probe:** the share of pinned-gate
  reds (`land_completed` `verify-failed` aborts whose `verify_mode` names `pinned`) carrying a recorded
  classification — the halt row's own `block_classification` (stamped on every blocked-on-land halt since
; `block_classified` is RETIRED, its historical rows read as legacy), or a LATER land of the SAME branch with a
  `rebaselined` mode and a non-empty `rebaseline_reason`; a red with no later land of its branch in the
  window is right-censored (counted apart, never as unclassified) — an unclassified red is itself the finding, since a red
  cleared without a named cause is indistinguishable from a gate quietly weakened.
- **B5-delta — waiver-vs-real-command coherence (grounding: <project> B5):** a `yitc-ops.yaml`
  declare-or-waive section WAIVED while the repo carries a real, wired command for it is an incoherence
  FINDING — e.g. `tests:` waived while `bin/verify.sh` exists AND the `land` is test-gated. A waiver
  must not contradict a present capability; reconcile (declare it) or justify the waiver explicitly.
- **backup/restore — sweep BOTH layers before grading (grounding: revizia-consumers-2026-09-27).** Before grading a project's backup or restore posture — including a SPEC-0162 stance or
  a restore waiver — sweep, READ-ONLY, for that project's subject (its DB container / dump name):
  (1) the repo's own backup/restore artifacts, AND (2) the HOST layer outside every repo —
  `<host-home>/backups/` (the 4-hourly dumps), `<host-home>/bin/offsite-backup.sh` (the off-host copy)
  and `<host-home>/bin/verify-backup.sh` with its log `<host-home>/backups/verify-backup.log` (the daily
  full restore; read the last result for that container), cited as host provenance
  (`patterns/host-server-surface-contract.md`), never edited. The result NAMES which layers were
  swept (F-#2); a repo-only sweep is reported as REPO-SCOPED, never as «no backup» / «restore never
  run». A waiver saying «no restore-drill practice» while the host verify log shows restores for
  that container is a B5-delta-shape incoherence FINDING. (Measured: <project>'s converged backup
  false positive and <project> C08 were both refuted by this host layer.)
- **tests red→green pairing (grounding: revizia 2026-09-23 T6 track divergence).** Its verdict obeys §Run-mode rule (3) (`inspection-criteria-roster-run-and-lenses.md` — print the no-data / excluded share before any `clean`). A flat
  `tests_failed` count misreads the Stage-6 loop — a worker runs the suite, sees red, fixes, re-runs
  green. PAIR each red with a LATER `tests_passed` of the SAME `task_id` (strictly later `ts`: an
  EARLIER green never pairs a red). A red ALSO pairs with a strictly later `land_completed` status
  `ok` of the same task (envelope `task_id`, else the `task/<id>` branch leaf) that re-ran its layers:
  every `layers[].layer` of the red reads `passed` in the land's `consumer_verify_layers`
  (`skipped-disjoint-subject` means the command did NOT run, SPEC-0152 rule 16), and a red with no
  consumer layer needs the land's `verify_metrics`. Reds come from the window `[S,U]`;
  greens from `S` onward with no upper bound, so a green landing after the window still pairs. Report `paired` and `unpaired`
  separately; only an UNPAIRED red is a candidate finding (it may also be an in-flight task — check
  the card before calling it). The window's counts are NOT a frozen snapshot: a row that lands later
  with a `ts` inside `[S,U]` raises `reds` (the 2026-09-23 window read 5, then 6 on re-run), so the
  check is `unpaired=0` and `paired == reds`, never a fixed `paired` number. Segment-aware reader
  (SPEC-0190 rule 4); stdin-fed, so a fixture can be piped in place of the three queries. Report-only.
  Run (S/U = the window; `-C <repo>` for a consumer):
  ```
  S= U=; J="bin/yitc-v2 journal query --limit 0 --json"
  { $J --type tests_failed --since $S --until $U; $J --type tests_passed --since $S; $J --type land_completed --since $S; } | python3 -c '
  import sys,json,collections
  rows=[json.loads(l) for l in sys.stdin if l.strip]
  reds=[r for r in rows if r.get("type")=="tests_failed"]
  greens=collections.defaultdict(list)
  for r in rows:
      if r.get("type")=="tests_passed": greens[r.get("task_id")].append(r["ts"])
  lands=collections.defaultdict(list)
  for r in rows:
      d=r.get("data") or {}; b=d.get("branch") or ""
      t=r.get("task_id") or (b[5:] if b.startswith("task/") else None)
      if r.get("type")=="land_completed" and d.get("status")=="ok" and t: lands[t].append((r["ts"],d))
  def land_ok(r):
      want={x["layer"] for x in (r.get("data") or {}).get("layers") or [] if isinstance(x,dict) and x.get("layer")}
      for ts,d in lands[r.get("task_id")]:
          got={x.get("layer") for x in d.get("consumer_verify_layers") or [] if isinstance(x,dict) and x.get("outcome")=="passed"}
          if ts>r["ts"] and (want<=got if want else bool(d.get("verify_metrics"))): return True
      return False
  unp=[r for r in reds if not any(g>r["ts"] for g in greens[r.get("task_id")]) and not land_ok(r)]
  print("tests reds=%d paired=%d unpaired=%d" % (len(reds), len(reds)-len(unp), len(unp)))
  for r in unp: print(" UNPAIRED red: %s %s" % (r.get("task_id"), r["ts"]))'
  ```
- **land-verify concurrency stability (weekly; grounding: the 2026-07-03 concurrency flake class —
  oversubscription + ff-race — that SPEC-0132 governs).** Its verdict obeys §Run-mode rule (3) (`inspection-criteria-roster-run-and-lenses.md` — print the no-data / excluded share before any `clean`). The durable, recurring successor to the
  proposing plan's one-week post-Z real-data watch, so that flake class cannot silently drift back.
  Two report-only reads over the recent `land_completed` A4 verify-metrics window (SPEC-0132 Rule 2 /
  SPEC-0025), REUSING the shipped pure signal — **no new store/detector/parser** (CHARTER §P1):
  (a) the SPEC-0132 Rule-3/4 watch-point signals via `bin/lib/worktree.py#_verify_scaling_signals`,
  and (b) a scan of that window's `fail_class`. **FINDING criterion is precise:** a non-ok
  `fail_class` is a FINDING only when **RECURRING** (the same non-ok class ≥ 2× in the window) OR
  **NON-DETERMINISTIC** (≥ 2 distinct non-ok classes = class-switching flakiness); a lone one-off
  non-ok class is a report-only observation, not a finding. `failed` (the tests themselves went red)
  is the SUBJECT outcome, not an infrastructure class, and is excluded — counting it made the
  criterion fire on every window with two red lands. A row with no `fail_class` is `no-metrics`,
  printed apart — absent evidence never reads as `ok`: an all-unmeasured window says NO-DATA, a
  partly-unmeasured one DEGRADED with its no-metrics share, and `clean` prints only over a fully
  measured window; every verdict names the window bounds and measured/total. **report-only — never an autonomous
  action (CHARTER §6 fence);** the owner/Review decides whether to act. Run:
  ```
  python3 -c 'import sys,json,collections; sys.path.insert(0,"bin")
  from lib.worktree import _verify_scaling_signals
  ev=[e for e in (json.loads(l) for l in open("events.jsonl") if "\"land_completed\"" in l)
      if e.get("type")=="land_completed"][-200:] # by TYPE — a substring also matches rows that merely mention it
  rows=[e.get("data",{}) for e in ev]
  fc=collections.Counter((d.get("verify_metrics") or {}).get("fail_class") or "no-metrics" for d in rows)
  bad={k:v for k,v in fc.items if k not in ("ok","failed","no-metrics")}
  recurring={k:v for k,v in bad.items if v>=2}
  nondet = len(bad)>=2
  n=len(rows); nm=fc.get("no-metrics",0)
  win="window %s..%s, %d/%d measured" % (ev[0].get("ts","?") if ev else "-", ev[-1].get("ts","?") if ev else "-", n-nm, n)
  print("window n=%d fail_class=%s" % (n, dict(fc)))
  if n==nm:
      print("fail_class: NO-DATA — no row carries a fail_class, no verdict (%s)" % win)
  elif nm: # judged over the measured rows only, and SAID so — never a bare clean
      print("fail_class: DEGRADED — %d/%d no-metrics; verdict below covers the measured rows only (%s)" % (nm, n, win))
  if n>nm and (recurring or nondet):
      print("FINDING: land-verify fail_class instability — recurring=%s non-deterministic=%s (%s)" % (recurring or "none", nondet, win))
  elif n>nm and bad:
      print("observation (report-only, not a finding): lone one-off non-ok class(es)=%s (%s)" % (bad, win))
  elif n>nm and not nm:
      print("fail_class: clean — no finding (%s)" % win)
  walls=sum(1 for d in rows if isinstance(d.get("verify_metrics"),dict) and d["verify_metrics"].get("verify_wall_ms") is not None)
  sig="\n".join(_verify_scaling_signals(rows))
  cov="%d/%d rows carry a verify wall; %s" % (walls, n, win)
  if not walls: print("scaling signals: NO-DATA — no row carries a verify wall (%s)" % cov)
  elif walls<n: print("scaling signals: DEGRADED — measured rows only (%s):" % cov, sig or "none over the measured rows")
  else: print("scaling signals (%s):" % cov, sig or "none — clean")'
  ```
  (Run over a SEGMENT-AWARE root, never the bare checkout: the checkout `events.jsonl` holds only the
  LIVE segment (SPEC-0190), so a window reaching past it is silently truncated. Build the root as a dir
  whose `events.jsonl` is `bin/yitc-v2 journal query --since <start> --limit 0 --json` and whose `bin`
  links the repo's; the same applies to the two blocks below. The window is the last ~200 rows. Signals may fire report-only on scaling watch-points independent of
  `fail_class` — SPEC-0132 Rules 3-4.)
- **abort assertion legibility — what share of aborts can NAME what broke (weekly; report-only;
  grounding: <project> X-1050, who measured 96 of 133 assertion entries (72%) reading
  `(no assertion captured)` across 105 aborted lands).** Its verdict obeys §Run-mode rule (3) (`inspection-criteria-roster-run-and-lenses.md` — print the no-data / excluded share before any `clean`). The sibling bullet above asks whether the
  verify is STABLE; this one asks whether its refusals are LEGIBLE. **It is not a legibility nicety,
  and that is what earns it the weekly slot:** a `land --rebaseline` waive token must NAME an
  assertion, so a MUTE abort leaves the token nothing to bind to and the land ends at a human — the
  origin of that project's 61 waive-coverage refusals. One root, two symptoms, neither visible
  without the fold. REUSES the shipped pure signal `bin/lib/worktree.py#_abort_assertion_legibility`
  — **no new store / detector / parser / event / gate** (CHARTER §P1), and it reads back the very
  markers `_surface_failing_assertions` writes.
  **METHOD — the part both sides paid to learn, and the part not to "simplify":** fold on the **TEXT**
  of `failing_assertions` and **NEVER on `abort_class`**. `abort_class` is a ROUTING label, not a
  measurement bucket: it unions refusals of different PLACEMENT and different MOVABILITY, so a share
  computed from it measures the taxonomy instead of the legibility (that hazard is its own card). And **bound the window to the CURRENT layer configuration** — folding across a layer
  REMOVAL mixes a layer that no longer exists into today's diagnosis; the fold opens its window after
  the newest row recorded under a removed layer and SAYS how many rows that excluded. A repo with no
  `verify.layers` declaration is told there is no boundary to apply, never that the bound was clean.
  **NO THRESHOLD IS DECREED, and that is measured rather than shrugged:** this kernel reads 2.5% mute
  over its last 300 aborted lands, <project> read 72% over theirs — two orders of magnitude on the
  same fold, so any cross-repo number would be voluntaristic. The share is a TRAJECTORY the
  owner/Review reads; **report-only, never an autonomous action** (CHARTER §6 fence / SPEC-0057 §2),
  and it moves no exit code. The three entry buckets (named / mute / unshaped) and the row-level
  "carried no `failing_assertions` at all" count are never added together — each absence is a
  different absence. The CAUSE side is not duplicated here: fixes the column-zero banner
  matcher, one source of mute aborts on this side. Run:
  ```
  import sys, os, json
  root = sys.argv[1] if len(sys.argv) > 1 else "."
  sys.path.insert(0, os.path.join(root, "bin"))
  from lib.worktree import _abort_assertion_legibility
  rows = [e.get("data", {})
          for e in (json.loads(l) for l in open(os.path.join(root, "events.jsonl"), encoding="utf-8", errors="replace")
                    if '"land_completed"' in l)
          if e.get("type") == "land_completed"][-300:] # by TYPE, not by substring
  layers = None # or the names in this repo's yitc-ops.yaml `verify.layers[].layer`
  print("\n".join(_abort_assertion_legibility(rows, current_layers=layers)["report"]))
  ```
  (Run as `python3 <this block> /path/to/repo` — pure stdlib beyond the kernel module it imports, so
  the SAME block runs under `-C <consumer>` over that repo's own journal. A consumer passes its
  declared layer names as `layers` to get the configuration bound; leaving it None reports that no
  boundary applies rather than pretending one did. **The carrier key is `layer`** — until
  this block named a `name` key on those entries — a key that does not exist — and a consumer following it
  verbatim got `[None, None...]`, which the fold then read as a real declaration: it reported
  `0 of 0... (None%)` and excluded that repo's two BUSIEST LIVE layers as "no longer declared",
  while the correct key over the same journal read 75% mute (<project> X-1145). A declaration that
  resolves to no usable name is now **REFUSED and says so** rather than folded — still report-only,
  still no exit code; passing `None` remains the honest way to say "I am declaring nothing".)

**T6 sub-lens — parallel-landing health (weekly; report-only; grounding: the kernel SPEC-0161
recorded-set freeze of 2026-08-21 · the consumer suppressor <project> found on their first non-empty
formation, X-1072 / · the same day's fleet overrun, 11 workers against a printed advisory
width of 8).** Every other landing surface is per-BRANCH, per-TASK or per-SESSION; none asks whether
PARALLEL landing is working AT ALL. So a congestion regime is discovered by whoever happens to be
landing into it, at full verify cost, instead of at a scheduled read. This lens closes that by folding
the two events the batch path already emits — `land_batch_formed` and `land_completed` — into one
weekly read. **Report-only, manual-first, NEVER an autonomous action** (CHARTER §6 fence / SPEC-0057
§2); it introduces no store, no event, no verb and no gate.

**Read it right — three rules, each of which the controller's own first fold got wrong:**
1. **A SOLO BATCH IS NOT BY ITSELF A DEFECT.** The head holds the slot and cannot be skipped, and
   dropping peers protects them from a batch the head's diff already dooms. shipped
   VISIBILITY only and changed no behaviour. Formation width is therefore REPORTED as a
   **trajectory** and is deliberately **not a finding criterion** — a solo-share criterion was built,
   measured against real windows, and REMOVED because it fired on a healthy one.
2. **`stale-wait-row` IS NOT AN EXCLUDED BRANCH.** It is a historical wait row correctly discarded as
   outside the freshness window, and it outnumbers the real exclusions by ~6x (669 vs a true top of
   117 on 2026-08-21). Ranking it beside them inverts the whole reading, so the fold counts it
   separately and says so.
3. **`engagement` tells you whether batching was even ENABLED.** All 105 of that day's kernel
   formations read `kernel-authored-verify` — batching was on, so whatever made those heads ineligible
   was NOT the engagement switch. On a consumer the same field is what exposes a suppressor
   (<project>'s window reads a mix of `project-authored-verify-undeclared` /
   `-declared-unsafe` / `project-declared-combined-candidate-safe`).

**The per-BRANCH and per-CAUSE reads are NOT re-implemented here — run `bin/yitc-v2 [-C <repo>] debt`**
and read its rule-26 line (one abort cause refusing several different branches — the entry point for
"what actually froze it"), rule-23 (dead lands), rule-24 (branches ahead of main) and rule-27 (what
the aborts cost). Those are, windowed, consumer-capable views; this lens CITES them and adds
only the cross-cutting fold they have no place for (CHARTER §P5). Note when reading rule 26 that in a
busy repo it is routinely non-empty — it is a good *cause* lookup and a poor congestion *detector*,
which is why the finding criterion below is the zero-success stretch instead.

**FINDING criteria — measured, not decreed, and only two:** (a) a **CONGESTION REGIME** — >= 5
distinct branches aborted across a stretch of >= 60 min in which NOTHING landed; (b) the **abort share
ROSE >= 15 pp** vs the preceding window of equal length (both windows >= 20 terminal lands). Replayed
over seven consecutive real kernel days these fire on 2026-08-21 alone (7 branches / 73 min, +21 pp)
and are silent on 2026-08-16..20, whose worst stretches run 2-4 branches. Everything else printed is
trajectory, not verdict.

**AN EVICTION IS NOT AN ABORT, and [b]/[c] count it apart.** A `land_completed` row whose
`abort_class` is `land-reservation-park-limit` is a EVICTION: the land waited out the land
reservation behind a holder that would not release and then STOPPED — it verified nothing, merged
nothing and spent no CPU. Every other abort describes a branch that was JUDGED and refused; an
eviction is a fact about the QUEUE. Counting it in the abort share therefore reads ONE congestion
TWICE — once as the wait, once as a failure that never happened (measured 2026-09-11: 4 of 14 aborts
in the 11:39-13:40Z window, each after 149 min queued; owner ruling «в долгах не считать»). So the
fold drops evictions from the TERMINAL-LAND population entirely — `n`, `ok`, `abort` and both shares
are over the non-evicted set, and so is [c]'s zero-success stretch, so a wait can no longer
manufacture a congestion-regime finding out of itself. They are printed as their own `evicted=N`
beside those figures, never inside them. The key literal below is the same one `bin/lib/debt.py`
names as `ABORT_CLASS_PARK_LIMIT_EVICTION`; this block cannot import it (it is contracted to run on
pure stdlib against any repo, see the next paragraph), so `tests/test_debt_park_limit_counted_apart.py`
extracts this block and asserts the two agree rather than leaving the duplication on trust.

**Runs against ANY repo — pass the repo root, so a consumer runs it unchanged over ITS OWN journal**
(`python3 <this block> /path/to/consumer`); it is pure stdlib and resolves no kernel path. Optional
2nd/3rd args replay a window: `<end-ISO> <days>`. A repo with no rows in the window says so explicitly
rather than reading "clean". Run:
```
import sys, os, json, collections, datetime
root = sys.argv[1] if len(sys.argv) > 1 else "."
F = "%Y-%m-%dT%H:%M:%SZ"
end = sys.argv[2] if len(sys.argv) > 2 else datetime.datetime.now(datetime.timezone.utc).strftime(F)
days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
e1 = datetime.datetime.strptime(end, F)
b1, b0 = (e1 - datetime.timedelta(days=days)).strftime(F), (e1 - datetime.timedelta(days=2*days)).strftime(F)
form = {"window": [], "prior": []}; land = {"window": [], "prior": []}
for line in open(os.path.join(root, "events.jsonl"), encoding="utf-8", errors="replace"):
    if '"land_batch_formed"' not in line and '"land_completed"' not in line: continue
    try: ev = json.loads(line)
    except Exception: continue
    ts, t, d = ev.get("ts", ""), ev.get("type"), ev.get("data") or {}
    w = "window" if b1 <= ts < end else ("prior" if b0 <= ts < b1 else None)
    if not w: continue
    if t == "land_batch_formed": form[w].append(d)
    elif t == "land_completed": land[w].append((ts, d.get("status"), d.get("branch"), d.get("abort_class")))
if not form["window"] and not land["window"]:
    print("parallel-landing: no land_batch_formed / land_completed rows in %s.. %s — nothing landed in this repo in the window (report-only, not 'clean')" % (b1, end)); sys.exit
EVICTED = "land-reservation-park-limit" # / — the eviction abort_class; MUST equal
                                          # debt.ABORT_CLASS_PARK_LIMIT_EVICTION (asserted by test)
def is_evicted(r):
    return r[1] == "abort" and isinstance(r[3], str) and r[3].strip == EVICTED
def terminal(l):
    """The terminal lands — evictions removed. A land that stopped WAITING was never judged."""
    return [r for r in l if not is_evicted(r)]
def solo_pct(f):
    return round(100 * sum(1 for d in f if (d.get("members") or 0) <= 1) / len(f)) if f else "n/a"
def abort_share(l):
    return 100 * sum(1 for r in l if r[1] == "abort") / len(l) if l else None
def abort_pct(l): # printed, rounded; the finding below compares the UNROUNDED shares
    return round(abort_share(l)) if l else "n/a"
f, l_all = form["window"], land["window"]
l = terminal(l_all); l_prior = terminal(land["prior"])
ev = [r for r in l_all if is_evicted(r)]
qd = sorted((d.get("queue_depth") or 0) for d in f)
exc = collections.Counter; stale = 0
for d in f:
    for x in (d.get("queue_excluded") or []):
        r = x.get("reason") or "?"
        stale += (r == "stale-wait-row")
        if r != "stale-wait-row": exc[r] += 1
print("window %s.. %s (prior = the %dd before it)" % (b1, end, days))
print("[a] formations n=%d width=%s solo=%s%% (prior %s%%) queue_depth med=%s max=%s engagement=%s"
      % (len(f), dict(sorted(collections.Counter((d.get("members") or 0) for d in f).items)), solo_pct(f),
         solo_pct(form["prior"]), qd[len(qd)//2] if qd else 0, qd[-1] if qd else 0,
         dict(collections.Counter(d.get("engagement") or "none" for d in f))))
print(" real per-branch exclusions (ranked): %s" % (exc.most_common(6) or "none"))
print(" stale-wait-row: %d — a historical wait row correctly DISCARDED, NOT an excluded branch; never rank it beside the above" % stale)
print("[b] terminal lands n=%d ok=%d abort=%d abort share %s%% (prior %s%%) evicted=%d (park-limit — NOT an abort, NOT in n/ok/abort/share above)"
      % (len(l), sum(1 for r in l if r[1] == "ok"), sum(1 for r in l if r[1] == "abort"), abort_pct(l), abort_pct(l_prior), len(ev)))
l.sort(key=lambda r: r[0]) # by ts only — the tuple now carries a possibly-None abort_class
bounds = [b1] + [r[0] for r in l if r[1] == "ok"] + [end]; worst = (0, 0.0, ""); regime = None
for x, y in zip(bounds, bounds[1:]):
    br = {r[2] for r in l if x < r[0] < y and r[1] == "abort"}
    mins = (datetime.datetime.strptime(y, F) - datetime.datetime.strptime(x, F)).total_seconds / 60
    if (len(br), mins) > (worst[0], worst[1]): worst = (len(br), mins, x)
    if len(br) >= 5 and mins >= 60 and (regime is None or len(br) > regime[0]): regime = (len(br), mins, x)
print("[c] worst zero-success stretch: %d distinct branch(es) aborted over %.0f min from %s" % worst)
find = [] # judged over EVERY stretch, not only the printed worst: a short wide one must not hide a long one
if regime:
    find.append("CONGESTION REGIME — %d distinct branches aborted across %.0f min in which NOTHING landed (from %s); read the cause with `bin/yitc-v2 debt` rule-26 line, then fix it ON MAIN" % regime)
if len(l) >= 20 and len(l_prior) >= 20 and abort_share(l) - abort_share(l_prior) >= 15:
    find.append("abort share ROSE %d pp (%d%% -> %d%%) vs the prior window" % (abort_pct(l) - abort_pct(l_prior), abort_pct(l_prior), abort_pct(l)))
# Formation WIDTH is deliberately NOT a finding criterion: the head holds the slot and cannot be
# skipped, and dropping peers protects them from a batch the head's diff already dooms ( —
# visibility only, no behaviour change). Width is REPORTED in [a] as a trajectory, never judged.
print(("FINDING: " + " | ".join(find)) if find else "no trajectory finding — [a]/[b]/[c] above are the TRAJECTORY, not a verdict on any one formation")
```
(Default window: the last 7 days, compared against the 7 before it. A repo that has not turned
batching on has no `land_batch_formed` rows — section [a] is then empty and [b]/[c] still apply.)

**T6 sub-lens — exercise-the-gated-paths (monthly; report-only; grounding: X-0366 / plan
`anti-false-green-doctrine-differential-proven-chec`).** The rest of the revizia model READS artifacts
(docs/specs/journal/graph) — but **a gate that never fires cannot fail a check, so a never-walked path
rots unpassable INVISIBLY** (X-0366: <project>'s owner-gated deploy hid an unpassable security gate until
an 8h prod-auth outage forced it, and a declared verify layer was green-for-owner + structurally
impossible for any other user). This lens closes that blind-spot by periodically **EXERCISING** the
gated/rarely-walked paths in a **NON-mutating dry-run**, instead of only inspecting the artifacts that
describe them. It is **report-only, manual-first, NEVER an autonomous action** (CHARTER §6 fence /
SPEC-0057 §2 — a dry-run exercise is still an OBSERVATION: owner-invoked, non-blocking); the owner/Review
decides whether an unpassable path is a finding. Adds **no new construct / verb / event / store** — it
reuses the shipped dry-run seams below.

| Lens | Surfaces | Probes |
|---|---|---|
| **exercise-the-gated-paths** | the gated/rarely-walked paths a corpus read never walks: the deploy guard shape · a declared `verify.layers[]` coverage boundary · the onboarding-delivery seam | the 3 exercises below (each NON-mutating) |

- **Exercise (a) — deploy guard shape (dry-run):** run `bin/yitc-v2 deploy --print-guard` — the EXISTING
  governed dry-run seam (SPEC-0094 §1; `bin/lib/deploy.py`): it emits the guard-snippet machine contract
  a consumer embeds in its `deploy.sh`, **WITHOUT a live deploy** (no code change; the parent card's
  illustrative "deploy check-shape" == the shipped `--print-guard`). The guard shape still RESOLVES ⇒ the
  gate that only fires on a real deploy is not silently broken. A non-resolving / malformed guard = a
  finding.
- **Exercise (b) — a `verify.layers[]` layer AS A NON-owner (dry-run):** run a declared verify layer as a
  **non-owner user** (a verify/test execution — non-mutating). The false-green class this catches:
  a layer that is green FOR THE OWNER but structurally impossible for any other user (X-0366 #5) — a
  coverage boundary a corpus read of `verify.layers[].covers` cannot. A layer that only the owner's
  environment can pass = a coverage-boundary finding (SPEC-0093 / SPEC-0152).
- **Exercise (c) — the onboarding-delivery seam (read-only):** confirm the onboarding seam still DELIVERS
  a due station — the seam nudge / `session start` onboarding digest RENDERS the due station
  (`_onboarding_seam_nudge` / `_onboarding_digest`, read-only, no consume), OR run
  `bin/yitc-v2 memory consume --station <id>` against a **DISPOSABLE fixture station only** (the exercise
  consumes NO live MEMORY.md pointer → no durable corpus mutation). A seam that no longer surfaces a due
  station = a finding (the rarely-walked delivery path rotted).
- **Probe null ≠ clean (F-#2):** a clean result NAMES which gated paths were exercised (deploy guard
  resolved / a layer ran as non-owner / the onboarding seam rendered), never a bare "none".

- **G3 — deploy/rollback joins:** each deploy joins to the next `live_probe`; a rollback falls in the deployed range; count null `abort_class`; a product commit with no carrier task is a finding — `bin/yitc-v2 journal query --type live_probe` + `bin/yitc-v2 journal query --type land_completed`.

### T8 — Adoption (done = adopted)

- **Surfaces:** verb invocation (MAP verb→effect-event); feature adoption (views, `--projected`/
  `--as-of`, `journal query`); P8 evidence (`consumer_read_evidence`/`live_trigger_evidence`) vs
  closures; the SPEC-0038 observation SUB-lens (per-task `post_verification` of done tasks — plan-born
  read within the plan's `postcheck` window, work-first read standalone); `task_closed`
  `post_verification_gap` markers.
- **Probes:** built-and-not-invoked list; P8-evidence / closure ratio (NAME the instrument: the at-close
  `adoption_evidence_seen` flag ≠ a join to any P8 row — 216 vs 340 of 424 infra closures, 2026-09);
  saved-view query count (`cli_invoked` `graph query` `node_id` resolved against `graph query --type view`); **per
  SURFACE** (base vs advanced/recovery — aggregate «closed/not-closed» is FORBIDDEN: base may be ×16.6
  adopted while advanced is built-not-invoked); distinguish recovery-only verbs from routine (a low
  recovery-lens count is NOT a defect; `--as-of` = PROVISIONAL recovery-by-design pending one real
  Review-recovery-flow check, no force-adopt); SPEC-0038 fill-vs-forget rate (observe-only, no
  graduation/causal claims); F-#3 re-check (is the grep-fallback still needed or did views close it).
  **Sub-lens records OBSERVATIONS ONLY — no verdicts, no graduation, no status writes; NOT its own theme**
  (it stays a T8 sub-lens — distinct from the T9 capability-graduation theme below, which owns the
  kernel↔consumer capability-portfolio decision).
  Map EVERY verb of the current parser inventory (`--help`) to an EXCLUSIVE effect-event (M2: `cli_invoked`
  covers the read-marked verbs plus the receipt-marked ones — `debt`, `profile`, `verify-durations`,
  `frontend-errors`, `task intake`, `audit status`, `spec ledger-label`; a FLAG is read from its
  row's `data.shape`, which keeps flags verbatim, so `graph query --as-of`/`--projected` ARE identifiable;
  a row every governed verb emits, e.g. `right_exercised`, is no one subcommand's effect). Derive names
  by rule B with the reference constructor's `--reconcile --since --until` — module-constant and
  f-string-template emitters included, observed types bucketed; its `unmapped` bucket (local-variable
  typed or `event`-verb ad hoc) is REPORTED, never counted as a zero (2026-09 window: 69 unmapped vs 83
  under the retired literal-only regex). A surface with neither an exclusive effect-event nor `cli_invoked` coverage is NO-DATA
  (unidentifiable), never a zero. Count via `journal query` only (SPEC-0190: 76 types sat in archive
  segments alone, 2026-09-21); fold payload-value spellings (`kind` `blocked-on-land`/`blocked_on_land`)
  before a per-kind count; joins (seeded→`onboarding_station_consumed`, closure→P8 row) look back past
  the window start and report left-censored rows apart.

**T8 sub-lens — reverse-adoption (runtime-vs-) (monthly; report-only; grounding: X-0366;
calibrated 2026-07-18, dual-track blind-first).** T8 above reads adoption in ONE direction:
**shipped → invoked** — every probe starts from something the corpus says was SHIPPED and asks whether
it was used. The **reverse** direction is unread: **live runtime code that was never governed-deployed**.
Nothing in the corpus points at it — no closure, no P8 evidence, no `deploy_completed` to start from —
so a corpus-only read cannot see it (X-0366: a container recreate silently shipped main to prod; the
not-adopted view had no reverse notion; 8h outage while every corpus-reading check stayed GREEN). Same
shape as the T6 blind-spot, one axis over: **a divergence the corpus has no record of cannot be read out
of the corpus.** It is **report-only, manual-first, NEVER an autonomous action** (CHARTER §6 fence /
SPEC-0057 §2 — a reverse probe is still an OBSERVATION: owner-invoked, non-blocking); the owner/Review
decides whether a divergence is a finding. Adds **no new construct / verb / event / store** — it reuses
the shipped read-only seams below; it never deploys, reconciles, or mutates anything.

| Lens | Surfaces | Probes |
|---|---|---|
| **reverse-adoption (runtime-vs-)** | what is LIVE but has no governed-deploy provenance: deployed-state vs `deploy_completed` history · post-deploy proof debt · live-probe reachability vs declared surface · host-config reconciliation drift | the 4 probes below (each read-only) |

- **Probe (a) — live state vs `deploy_completed` provenance.** For each project declaring a deploy
  contract, compare what is RUNNING against the journal's `deploy_completed` history. A live surface
  with **no** `deploy_completed` carrier = runtime that reached prod outside the governed seam — the
  X-0366 class. Read-only: the journal + the project's declared deploy contract (SPEC-0094 §1).
  *Cause-side sibling:* the implicit-shipping-path topology (bind mounts / mutable tags) is watched by
  the shipped runtime-delivery declaration + mount advisory — this probe catches the
  RESULT when that path fired.
- **Probe (b) — post-deploy-proof debt (SPEC-0149).** Read `graph query not-adopted`, which STATES its
  status (the `debt` echo is suppressed-when-clean: its silence is not an empty result). A deploy whose proof never landed is a shipped-but-unproven
  runtime claim — the reverse-direction sibling of a closure with no P8 evidence.
- **Probe (c) — live-probe reachability vs DECLARED surface.** Run the per-change `live_probe` GET
  (`bin/yitc-v2 liveprobe`, non-mutating) against what the corpus DECLARES is live. A probe that
  resolves to a surface no closure accounts for — or a declared surface no probe can reach — is a
  divergence. (Distinct from T6's exercise (b): that asks "can a non-owner PASS this gate?"; this asks
  "does the corpus ACCOUNT for what answers?")
- **Probe (d) — host-config reconciliation drift (SPEC-0111).** Compare the recorded
  `host_reconciliation_recorded` evidence against the host's current config. Live host config with no
  reconciliation record = host state that diverged from its governed apply seam.
- **Probe null ≠ clean (F-#2):** a clean result NAMES which reverse probes ran and what each resolved
  (deploy provenance matched for projects X/Y · proof-debt view empty · live probe reached the declared
  surface · host reconciliation current), never a bare "none". A probe that could not RUN is reported as
  **not-run**, never folded into "clean" — that conflation is the false-green this lens exists to catch.

**T8 sub-lens — exemption-case revision: «is the mechanism and its feedback alive?» (monthly;
report-only; SPEC-0178 rules 7+9).** A project may declare, in its own `yitc-ops.yaml`
`audit_scrutiny.cases[]`, named cases whose matching cards close WITHOUT the Stage-8 audit-post. That
declaration is an accepted risk, and the thing that keeps it honest is not a cap — the owner declined
outer caps (CHARTER §Project-declared audit-post exemption) — but a periodic look at whether the
mechanism is still doing what the project thought it was. A T8 sub-lens rather than a theme of its own
because this IS T8's question one surface over: T8 asks whether a shipped thing is actually being
used, and this asks whether a declared exemption is still warranted **and whether the feedback that
would tell us has anyone left making it**. Adds no store, no verb, no cadence of its own.

**Run it:** `bin/yitc-v2 inspect record --theme T8 --tracks primary,external` (or `--dry-run` to read the block without
recording a run) — the `inspection_completed` event carries the report-only `case_review` block, one
proposal per declared case. Under `-C <consumer>` it folds THAT consumer's carrier and journal; the
kernel's own file declares none of these cases, so its own run reports «0 declared» and that is the correct answer,
not an empty result.

| Lens | Surfaces | Probes |
|---|---|---|
| **exemption-case revision** | `yitc-ops.yaml audit_scrutiny.cases[]` · `task_closed.data.exempted_case` (the closure end) · `task_closed.data.case_out_of_path` (rule 6) · `task_closed.data.governance_takeback` (rule 3 — its re-sign-only mark feeds the rule-9 line) · `deviation_captured` attributions (the rule-5 join) | the four-field proposal + the covered share below |

- **The PROPOSAL format (rule 7) — four fields, never three.** Every proposal names the **CASE**, the
  **ACTION** (`restore` · `narrow` · `widen` · `leave`), the **BASIS** (the specific records) and the
  **STRENGTH** of that basis — either **direct observation** or **absence of observation**. The verb
  derives a CANDIDATE action; the human decides. `widen` is never machine-proposed: rule 7 says the
  review does not compute whether to loosen.
- **Absence is labelled, and is NEVER read as safety.** A case with no defect judgement against it
  surfaces as a `restore` candidate whose strength is *absence of observation* — because zero
  attributions means EITHER nothing escaped OR nobody made the call, and no record distinguishes
  those. This is the same F-#2 discipline as the reverse-adoption lens above, applied to a population
  rather than a probe; treat a quiet case the way you treat a probe that could not run.
- **Read the UNCOUNTED captures, not only the counted ones.** Case-linked captures carrying no `kind`
  are the difference between «nothing happened» and «nobody looked». The block reports them separately
  with the reason each does not count — that split is the actual liveness signal, and a count of
  records is not a probe of the thing that produces them (`lessons/a-presence-count-is-not-a-liveness-
  probe`).
- **Why this lens exists at all (measured, cycle 15).** End-to-end over four projects' entire history,
  the automatic restoration chain collapses to **zero** at the `kind: defect` triage hop on all three
  consumers. So wherever that judgement is not made, the automatic brake never fires and **this review
  is the restoration carrier**. It is a weaker promise than an automatic one and a TRUE one.
- **The covered SHARE (rule 9) — report-only, over the case's OWN `window_days`.** Each case reports
  the share of closed cards it actually exempted over its own W (kernel default 90), NOT since the last
  review: the median inter-review gap is 0 days on all four projects, so a since-last-review
  denominator is usually empty (cycle 19). **No ceiling, no threshold, nothing refused** — a wide share
  still accepts every close. Two consecutive reviews therefore compare like-for-like periods, and the
  DRIFT between them is the signal a reviewer weighs: a case creeping from 10% to 40% has changed what
  the project is accepting without anyone re-deciding it. An empty denominator reports **undefined**,
  never 0% — a measurement not taken must not read as a reassuring one.
- **What the reviewer decides.** Nothing here is applied. Take each proposal to the project: keep it
  (`leave`), tighten the declared `paths:` (`narrow` — rule 6's out-of-path rows are the evidence for
  this one), or put the gate back (`restore`, always an owner act — re-declaring a restored case is
  never automatic). A `widen` is a fresh project decision, made with the share in front of you.


- **G6 — P8 by realm:** partition P8 evidence by subject realm; name which closure classes must carry P8; waived concerns are checked against the active profile — `bin/yitc-v2 journal query --type consumer_read_evidence` + `bin/yitc-v2 profile`.
- **G14 — stage-discard root cause:** `NO-DATA: stage-discard root cause — instrument absent: per-session command-shape archive`.

## The other parts of this roster

- **Part 1** (`patterns/inspection-criteria-roster.md`) — the `CADENCE` values, the
  operational-hygiene weekly checklist, and the T1 / T3 / T7 lens-checklists.
- **Part 2** (`patterns/inspection-criteria-roster-run-and-lenses.md`) — the run-mode, the
  cross-theme method (M1–M9), the foundations and the architecture-drift lens.
- **Part 3** (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`) — the T2 / T4 /
  T5 lens-checklists.
- **Part 4** (`patterns/inspection-criteria-roster-portfolio-observation.md`) — the T9
  lens-checklist.
- **Part 6** (`patterns/inspection-criteria-roster-real-work-observation.md`) — the T10 lens-checklist.
- **Navigation map** (`patterns/inspection-criteria-roster-navigation-map.md`) — one row per
  recurring check: check → theme → cadence → how-to-run → rule-home.

This heading also BOUNDS the T8 section above: a theme's freshness hash runs to the next `##`/`###`
heading, so a part must not end on living criteria followed by loose prose.
