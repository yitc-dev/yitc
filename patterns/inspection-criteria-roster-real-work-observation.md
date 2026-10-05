---
name: inspection-criteria-roster-real-work-observation
class: reference
sourced_from: <durable artifact> (SPEC-0120 must-split of patterns/inspection-criteria-roster-portfolio-observation.md — part 4 crossed the one-bounded-read BYTE ceiling at 687 lines / 63,272 bytes after the lands; the T10 lens-checklist re-homes here VERBATIM per SPLIT-never-delete) (the reader that resolves per-theme sections across the DECLARED parts in bin/lib/inspection.py ROSTER_CRITERIA_PART_SUFFIXES) + SPEC-0120 (durable-doc size governance) + SPEC-0057 (the inspection construct — §3 living-criteria home) + patterns/inspection-criteria-roster.md (part 1 — the roster's resolution origin)
applies_to: PART 6 of the single living inspection home (SPEC-0057) — the freshness-hashed per-theme lens-checklist for T10 (the real-work observation loop — cross-project worker×auditor PAIR observation). `inspect record --theme T10` hashes the section HERE, resolved through the declared-part tuple. T9 stays in part 4 (`patterns/inspection-criteria-roster-portfolio-observation.md`); the umbrella navigation map is `patterns/inspection-criteria-roster-navigation-map.md`. All roster files are ONE living home split for loadability (SPEC-0120). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — part 6 (the real-work-observation lens-checklist)

> **What this IS:** PART 6 of the single living inspection home (SPEC-0057) — the freshness-hashed
> **per-theme lens-checklist** for **T10**, split out of
> `patterns/inspection-criteria-roster-portfolio-observation.md` (PART 4) under the SPEC-0120
> one-bounded-read BYTE ceiling. Content is VERBATIM (SPLIT-never-delete): the section is
> byte-identical to the one part 4 carried, so its `@<section-hash>` is unchanged — only the path a
> `criteria_ref` names moves from part 4 to this file. No pointer stub was left behind under a
> `### T10 —` heading: one section, one home.
>
> **The other parts:** the umbrella navigation map →
> **`patterns/inspection-criteria-roster-navigation-map.md`**; T9 → **part 4**
> (`patterns/inspection-criteria-roster-portfolio-observation.md`).

## Per-theme lens-checklists (part 6) — the living criteria

### T10 — Real-work observation loop (cross-project worker×auditor PAIR observation)

**Identity.** T10 scans the **real-work observation loop** (SPEC-0135): across ALL v2 projects, which
AI configurations actually ran and how they fared. Its identity is the **worker×auditor PAIR** —
`provider×model×effort` on each side — the worker (session_started) joined by `session_ref` to the
external auditor (external_audit_completed). It answers "which way to move": which pair to recommend to
users and where discipline breaks. A periodic SCAN, not a gate.

**NO-DATA: hardware sizing — instrument absent.** The third purpose this theme was born with —
«how to size hardware per project class» — is **not runnable from either T10 instrument**, and the run
states that rather than implying a read it cannot take. The kernel rollup carries no cost or resource
field at all (by design, §Probe). The per-project companion carries `cost_usd`, but almost all of it
sits in the slice that has no configuration to attribute it to: measured 2026-09-20 on the kernel
project, 93.4% of sessions (6,560 of 7,023) fall in the all-`unknown` worker slice, and of
$47,718.08 total measured cost **$47,266.96 (99.05%) is inside that slice**. Exactly ONE identified
slice carries any cost at all (`the provider/<provider-model>/low`, $451.12); every other identified slice
reads `cost_usd: null`. So the attributed cost base is ~1% of the measured total and covers one
configuration — not a numerator a per-configuration sizing claim can rest on. **RESTORATION CONDITION — all THREE, because cost
attribution alone would still not make a sizing claim runnable:** (1) an attributable RESOURCE or
HARDWARE measure exists per configuration — cost is a price, not a capacity, and no carried row
exposes memory, CPU, context or wall-clock per worker slice; (2) that measure is attributed to an
IDENTIFIED worker slice, not to the all-`unknown` slice; and (3) a PROJECT-CLASS carrier exists and is
readable — the purpose is sizing «per project class», and no instrument in this theme defines or
carries a project class at all. Until all three hold, a run records this NO-DATA line and makes no
sizing claim.

**Probe (derived, no new store).** The KERNEL cross-project rollup lens:
`bin/yitc-v2 graph query observation-rollup` — enumerates every registry `yitc_v2` project (kernel
included, via the read-only nightly enumeration seam, SPEC-0105 §2), folds each project's journal, and
returns worker×auditor PAIR slices. The per-PROJECT companion is `graph query observation [project]`
(a single project measuring itself). No new store/event — pure read-time derived (SPEC-0135
§1/§3).

**The DECISION-CARRYING fields — read these, not a remembered subset.** This is not a schema dump and
does not try to be one. Excluded as genuinely NON-decisional are exactly three: `keyed_by` and
`pairs` (how the payload is shaped) and `unattributed_reasons_note` (a gloss on a field that IS
listed). Everything else carries an arm below — including three that look structural and are not:
each pair's `worker` and `auditor` IDENTITY blocks carry the sentinel disqualification AND the
canonical thin-pair key, and `pair_count` is the figure the one-population rule recomputes. What
follows is the list of fields that CARRY A DECISION in this checklist; the pre-2026-09 criteria named
three of them. Per pair: its `worker` and `auditor` identity triples, `sample_size`,
`project_count` + `projects`, `sessions`, raw `verdicts`, `verdict_mix_claimed` (a
`verdict_mix_not_claimed` reason when below floor), and the THREE complete marginals
`by_effort_tier` / `by_task_class` / `by_project`, plus the calendar marginal `by_window` (the ISO week
of each audit row — the recency carrier of the `retired-thin` arm below). At payload level: `pair_count` (the figure the
one-population rule recomputes) and the COVERAGE keys `project_count` + `projects_scanned` — which
name how many and WHICH projects the fold actually read, and are the carrier for the all-projects
check; do not confuse those two with a PAIR's own `project_count`/`projects`, which count only the
projects that pair was observed in. Then the attribution block
(`total_observations` · `attributed_observations` · `unattributed_observations` ·
`unattributed_reasons` · `attributed_share` · `window`), the absence block (`observed_workers` ·
`observed_auditors` · `zero_run_pairs` · `zero_run_pair_count` · `absence`), `sample_adequacy_floor`
+ `sample_adequacy`, the three contract notes `no_best_pair` / `stakes` / `controls`, and `source`. A run that
reads only sample_size + project_count + verdict counts is reading an obsolete subset of its own
instrument and will miss every arm below.

**SEGMENT HORIZON — state it, do not assume it (G12 / SPEC-0190 rule 4).** The fold is segment-aware:
`_read_pair_observations_for_project` iterates `journal_mod.segment_lines`, so it reads the
WHOLE logical journal — archive segments plus the live segment — not the live path alone. This is
load-bearing rather than hypothetical wherever ANY scanned project carries archives, because there the
live segment is only part of the record. HOW MANY projects that is, and which, is a MEASUREMENT this
text does not make: archive coverage changes with every rotation, so the run DERIVES the relationship
from its own archive-count rows and reports it — never reading a standing characterisation («most», «a
minority», «rare») out of these criteria, which is the same staleness the numerals had, spelled in
words. The
payload does NOT state this — it carries no segment key and no temporal-window key — so **a run
states its own segment horizon explicitly, from a named probe and not from the payload**: per scanned
project, the archive-segment COUNT and the EARLIEST and LATEST covered event dates. **The two
boundaries come from different probes, and conflating them is the trap.** The archive FILENAMES
(`<project>/archive/events-YYYY-MM-DD.jsonl`) give the count and the earliest date, and they give the
last ARCHIVED date — they say nothing about the LIVE segment, which is by construction the most recent
and is named by no filename date. So the LATEST boundary is read from the events themselves through
the segment-aware reader (`journal query`), never inferred from the newest archive filename; where
that read is unavailable the run states the latest boundary as **UNKNOWN** for that project rather
than quoting an archive date as if it were the horizon.
**AND THE EARLIEST BOUNDARY IS READ THE SAME WAY, for every project — including the archive-less
ones.** The horizon the fold actually has is the COVERED-EVENT span; the ARCHIVE span is a different,
narrower thing. The two are reported SEPARATELY and neither substitutes for the other. A project with
no archive has an UNKNOWN *archive* span — never a zero one — but it still has a covered span, read
from its live segment's own first and last events. Reporting «archives: 0» plus a latest date, with no
earliest, leaves that project's horizon unstated while looking complete. A count without a span is not
a horizon, and a one-sided span is not a span.
**NO MEASURED COUNT IS FROZEN INTO THESE CRITERIA.** Archive counts and spans change with every
rotation — a number written here is stale before the next run and would contradict that run's own
probe. The criteria carry the PROBE; each run carries its own reading. No time-bounded claim is made
from a payload that declares no window on the time axis, and no count is read from a raw grep of a
live `events.jsonl` (the rule-B third failure mode).

**FINDINGS not scores — the §4 fence HELD (the load-bearing invariant).** T10 emits FINDINGS, never a
composite quality SCORE and never a universal «best pair». The `observation-rollup` payload carries the
`no_best_pair` note by construction; a T10 run reads each pair ONLY against its own `sample_size`
(confidence), and pairs are ordered by sample-size (confidence), NOT ranked by quality. A low-sample
pair is a low-confidence observation, not a verdict. This is SPEC-0057 §4 (EVALUATION = THE FINDINGS,
NOT A COLOR) applied to the observation loop — do not invent a rubric/band/score on top of the counts.

**MANDATORY QUALIFIER — every pair claim names its denominator (presence is not absence, M8).** A T10
reading is TRUE OF THE ATTRIBUTED WINDOW ONLY, and the run SAYS SO on the face of the claim: no count,
share or steer is recorded without `attributed_observations / total_observations` beside it. Reading
2026-09-20: **13,173 of 20,445 = attributed_share 0.644**, i.e. 35.6% of the record is outside every
pair row — and the leak is named, not diffuse: `worker_triple_incomplete` 4,539 (62.4% of the
unattributed), `auditor_triple_incomplete` 2,266 (31.2%), `worker_session_absent` 391 (5.4%),
`no_session_ref` 76 (1.0%). This qualifier is the direct descendant of the 2026-08-13 finding
`observation-rollup-attributes-only-15pct-worker-triple-incomplete`; the 2026-09-13 revizia row still
read `observation-rollup(24 pairs)` with no denominator, which is the miss this arm closes.
**THE QUALIFIER BINDS BOTH INSTRUMENTS.** `graph query observation [project]` now states its own
coverage — `attribution.<project>` = sessions / attributed_sessions / attributed_share — and
the run QUOTES it. It is computed by REJECTION, never by complement: a slice is attributed only if it
carries `unknown` on NO worker axis, so a PARTIAL unknown (e.g. `the provider / unknown / high`) is NOT
counted as identified. The companion resolves every session to its JOURNAL'S OWNER, as the rollup
does; before it keyed on the stamped `project`, which in a worktree is the task id / slug, so
~43% of the kernel's sessions were dropped from the kernel's slice. Corrected reading on the kernel
project 2026-09-23: **3,332 of 7,791 sessions attributed = 0.428**. The frozen 2026-09-20 figure
(461 of 7,023 = 0.066) and the 93.4% / 99.05% all-`unknown` shares in §NO-DATA above were read from
that truncated view — re-measure them from the corrected view before quoting. An instrument that cannot state its own
coverage does not thereby have full coverage, and a partial identity is not an identity.

**IDENTITY VALIDITY — what counts as a pair, and what absence means.** Two arms, both mandatory:
- **A SENTINEL IS NOT A CONFIGURATION.** The attribution window admits an observation whose triples
  carry no `unknown` axis — but a non-`unknown` string is not thereby an identity. The live case:
  `unchanged-fp-carry-forward` (`CARRY_FORWARD_AUDITOR_MARKER`, `bin/lib/audit.py`) is stamped where
  the unchanged-fingerprint carry-forward records an auditor **without sending any prompt** —
  its own definition states that naming a provider/model there «describes an invocation that did not
  happen». It passes the window's resolved test and surfaces as a real auditor. Measured 2026-09-20:
  2 of 9 `observed_auditors`, 3 of 28 `pairs`, 19 observations at a 0.947 adverse share. A run
  DISQUALIFIES every such marker BEFORE reading any mix, names it as disqualified with its count, and
  never reports it as a pair — an adverse mix on an auditor that never ran is a false steer, and the
  §4 fence does not catch it because no score is involved.
- **THE DISQUALIFICATION DEFINES ONE POPULATION, AND EVERY DOWNSTREAM COUNT IS RECOMPUTED FROM IT.**
  Disqualifying a sentinel and then quoting the payload's own totals is the same defect in a new
  place: the payload's figures are PRE-filter. So the run fixes ONE post-disqualification population
  at this step and every later number — the pair count, the attributed denominator, the below-floor
  count, the observed grid and its zero-run cells — is recomputed against it and reported as such,
  never copied from the payload. Worked on the 2026-09-20 reading, so the recomputation is
  demonstrated and not merely required: pairs 28 → **25**; attributed observations 13,173 → **13,154**
  (total_observations 20,445 is UNCHANGED — a disqualified observation leaves the numerator, not the
  population, so attributed_share 0.6440 → **0.6434**); below-floor pairs 5 of 28 → **3 of 25**; the
  observed grid 6×9 = 54 → **6×7 = 42** and its zero-run cells 26 → **17**. A run that reports a
  disqualification beside an un-recomputed total has not applied it.
- **ABSENCE IS A READ, NOT A SILENCE.** The payload distinguishes three states (`absence` note): listed in `pairs` (observed), listed in `zero_run_pairs` (both sides in live use, never
  run together — a REAL gap), and in neither (UNOBSERVED — no evidence either way). A run reads
  `zero_run_pairs` explicitly; 26 of the 54 observed-grid cells at this cutoff. A cell missing from
  `pairs` is never reported as disuse. This arm is computed AFTER the sentinel disqualification above:
  a sentinel in the auditor axis inflates the grid and manufactures gaps against a non-identity.

**What a run does (findings, event/state-checkable).** (a) run `observation-rollup`; (b) read the
pairs AT OR ABOVE the declared adequacy floor against their verdict-mix (GREEN/YELLOW/RED/ABORT
counts) — a pair with a materially worse verdict-mix at adequate sample is a FINDING (steer away /
investigate), never a score — and **never a CAUSAL steer without controlling for the ROUTED
confounder, which is `by_effort_tier`, NOT task class.** SPEC-0072 blast-radius routing binds
worker-effort to task STAKES, so a high-effort pair's sample is mostly critical-tier work and carries
a worse mix by stakes rather than by pair quality. The instrument's own `stakes` note is explicit:
compare ONLY within a matching `by_effort_tier` bucket; `by_task_class` is the SECONDARY stratifier,
because SPEC-0072 rule 4 routes on stakes and explicitly NOT on class. A comparison controlled for
class alone has not controlled for the confound. **State the bucket you compared in and its
occupancy** — a bucket comparison whose occupancy is not reported cannot be told apart from one that
had nothing to discriminate. Occupancy is reported POST-disqualification, over the surviving pairs —
a figure taken from the payload's full pair list is pre-filter and must not be quoted here. (c) pairs BELOW the floor are recorded as «insufficient data» with their n, and are
never ranked, compared or steered on — each is then read as `retired-thin` or as a soak obligation by
the recency arm below; (d) surface cross-project DIFFERENCES (a pair reading better in
one project than another) as DESCRIPTIVE OBSERVATIONS — never as a discipline/environment finding or a
steer, for the reason stated under §A CROSS-PROJECT DIFFERENCE below: `by_project` pools across effort
tiers, so a project comparison is uncontrolled for the very confound arm (b) makes mandatory. Cost is NOT in this rollup (cross-project cost needs each
project's local transcript archive — SPEC-0135 §3; the per-project `observation` view owns read-time
cost). Route findings to the one nonconformity sink like every theme (SPEC-0055/0056); emit one
`inspection_completed` (theme=T10) per run even on zero findings (SPEC-0057 §6).

**THE THIN/ADEQUATE LINE IS DECLARED BY THE INSTRUMENT, NOT REDRAWN PER RUN.** «High-sample»,
«adequate sample» and «too thin» all resolve to ONE declared threshold: `sample_adequacy_floor` (5 at
this cutoff), surfaced per pair as `verdict_mix_claimed: true|false` with a
`verdict_mix_not_claimed` reason. A run USES that stamp and does not invent a second line — the
X-0596 incident (n=1 and n=35 rendering identically, each reader redrawing the line) is what the
declaration exists to end. Two bounds travel with it: the floor is REPORT-ONLY (a below-floor pair is
still listed in full, in its usual sort position — nothing is filtered or gated), and the floor is
**pair-level ONLY**. weighed extending it to the marginals and DECLINED: a floor calibrated on
a pooled n does not transfer to a bucket's n. A BUCKET is judged on its own `sample_size`, in prose —
a thin bucket is a thin finding. The below-floor COUNT is likewise post-disqualification: at the
2026-09-20 reading 3 of the 25 surviving pairs, where the payload's own «5 of 28» is pre-filter —
two of those five ARE the sentinel pairs, so quoting it re-admits exactly what P7 excluded.
**The floor says HOW MUCH was observed, never WHEN.** Whether a below-floor pair can still grow is a
separate reading — the recency arm directly below — and that arm leaves the floor, the stamp and the
report-only posture exactly as stated here.

**A THIN PAIR WHOSE CONFIGURATION HAS LEFT USE IS `retired-thin` — REPORTED, NEVER SOAKED.**
A soak follow-up waits for a sample to grow, and a sample grows only while BOTH sides of the pair are
still being run. With no time axis the floor cannot tell «thin so far» from «thin for good»: the
2026-09-23 run re-read three thin pairs unchanged and recorded that one of them, on an auditor
configuration it read as no longer running, «can now never leave thin status» (finding
`t10-top-confidence-pairs-are-a-retired-auditor-config-no-recency-axis`). The arm is DECLARED in four
parts, so two runs on the same rows classify identically:
- **CARRIER — the rollup's own `by_window`; no new instrument.** Each pair's `by_window` partitions its
  sample by the ISO week (`YYYY-Www`, UTC) of each audit row. A side's LAST-SEEN is the latest dated
  week in which that exact triple (provider/model/effort) appears in the `by_window` of ANY surviving
  pair: the worker's is taken over every surviving pair carrying that worker triple, the auditor's
  likewise. It is read over the post-disqualification population (the one-population rule above). The
  `unknown` bucket dates nothing — a side whose observations ALL sit in `unknown` has last-seen UNKNOWN.
- **WINDOW — declared: three ISO weeks, the week the run is taken in plus the two before it.** Week
  resolution, because that is the resolution the carrier has; three, because the scan is periodic and
  one quiet week must not read as retirement. Revisit the width on evidence, never per run.
- **CLASSIFICATION.** A below-floor surviving pair is `retired-thin` when its worker's OR its
  auditor's last-seen is DATED and falls before the window's first week. One side is enough: the pair
  cannot gain an observation without both. UNKNOWN is not «before»: a side with no dated week can
  never establish retirement by itself, and it does not cancel the OTHER side's dated last-seen when
  that one falls before the window. A pair that neither side retires stays an ordinary thin pair, so
  the uncertainty resolves toward the soak obligation, never away from it.
- **CONSEQUENCE.** A `retired-thin` pair is still listed as «insufficient data» with its n — arm (c)
  and the floor are untouched — and the run records, per pair: the canonical key (below), the window
  as its first and last ISO week, each side's last-seen, and which side fell outside. It is NOT a soak
  obligation: no soak follow-up is filed for a `retired-thin` key, whatever the lookup returns. An
  OPEN item the lookup matches to a `retired-thin` key is DROPPED through the followup seam's own
  drop verb (`followup drop <id>`), with that reading as its reason (key, window, both last-seen
  weeks), and the run carries the dropped id. Like the filing below it is a WRITE the run makes from
  its own checkout, never one of the read-only probes this roster spells as a runnable command. The
  drop needs no listing of its own: it reads the one pre-filing listing the soak arm already takes.

**What the recency arm leaves alone, and what it does not claim.** The floor, the
`verdict_mix_claimed` stamp and the canonical key are unchanged, and a pair at or above the floor is
read exactly as before. The run states every observed side's last-seen ONCE — it is the table the
classification reads — and for an at-or-above-floor pair that line is a description of the record,
never a steer. `retired-thin` is a READING recomputed by each run, not a stored state: once a later
run finds NEITHER side dated before its window — the configuration that had left use is observed
again and the other side still is — the pair is an ordinary thin pair again, the lookup finds no
item, and the filing rule below applies. One side returning while the other is still dated before the
window changes nothing: the pair stays `retired-thin`. That costs one drop and one re-file per
genuine return, against one dead item re-read on every scan. And last-seen is true of the ATTRIBUTED window
only (the mandatory qualifier above): a configuration running solely in the unattributed remainder
reads as unseen, so the run words the class as «no attributed observation inside the window» and
never as «no longer in use». Worked at the 2026-10-05 reading, so the classification is demonstrated
and not merely required — run week 2026-W41, window 2026-W39..W41, 6 below-floor pairs of 45
surviving: three share ONE worker configuration last seen 2026-W38 (their auditors 2026-W40) and are
`retired-thin`; the other three have both sides at 2026-W40 or W41 and stay soak obligations. Read
without this arm, the same rows give no `retired-thin` pair and six obligations.

**A SOAK FOLLOW-UP IS RE-USED, NEVER RE-FILED EACH SCAN.** A thin pair is thin for as long as it stays
thin, so «file a soak follow-up» on a periodic scan would file the same item every cycle. The lookup
is SPELLED, because «keyed by the pair» is not executable: the CANONICAL KEY is
`t10-thin-pair:<worker.provider>/<worker.model>/<worker.effort>__<auditor.provider>/<auditor.model>/<auditor.effort>`
(the six axes in payload order, lowercase, no spaces), and the LOOKUP is
`bin/yitc-v2 followup list --status open` with the caller matching that key against the listed items
(`followup list` filters by `--status` only — it has no `--grep`, so the match is the caller's, and
spelling one here would be an unrunnable probe of the kind this lens exists to catch). **AT MOST TWO
listings per RUN, and never one per pair:** the listing is the full open population either way, so the
run fetches it ONCE before filing and matches every surviving thin-pair key against that single result
set; then, ONLY IF it filed anything, it takes ONE shared post-batch listing to evidence every new
item's round trip at once. So the bound is one listing when nothing is filed, two when something is —
never one per pair, which is an N+1 over an unchanged population
(`patterns/repeated-work-lens.md`). Stating it as a flat «one listing» would contradict the round-trip
evidence rule below, which cannot be satisfied from a listing taken before the filing existed. Before filing, the run runs that lookup
for each below-floor surviving pair and CARRIES THE RESULT into the run record — the matched item's
id, or an explicit NO-MATCH line for that key. A match on a `retired-thin` key is dropped, not
re-used, and a NO-MATCH on one files nothing (the recency arm above). **A recorded NO-MATCH OBLIGES a
filing — for EVERY surviving thin pair that is not `retired-thin`, not a chosen one.** «May file» leaves the arm fail-open from the other end: a run
can record three NO-MATCHes, file one, and present the arm as discharged while two pairs stay
untracked and re-NO-MATCH forever. So the run files for each NO-MATCH key, then takes ONE post-batch
listing and carries exactly one matching id and key per newly filed item. It states explicitly when
there was nothing to file (every key that is not `retired-thin` matched). **AND THE FILING SIDE CARRIES THE KEY, or the dedup fails open:** a
newly filed thin-pair followup MUST embed the exact canonical key verbatim in the text `followup list`
returns, because a lookup that matches on a key nothing stores returns NO-MATCH forever and re-files
the same pair every scan — a dedup rule that reads as working while never matching. Matching and
storing are one rule with two halves; a run that files without embedding the key has not discharged
this arm. **And the round trip is EVIDENCED, not assumed:** after filing, the run re-runs the lookup
and carries the result — the new item's id together with the exact key it now matches on. A storage
rule whose read-back was never exercised is a closure nobody has tested; demonstrating it costs one
re-read of a listing the run already fetches. A filing with no carried lookup result is refused: the dedup is the
carried evidence, not the intention. No new store and no watermark mechanism is added — the arm names
the existing followup seam it reuses (the repeated-work discipline,
`patterns/repeated-work-lens.md`).

**A CROSS-PROJECT DIFFERENCE IS DESCRIPTIVE UNTIL IT IS CONTROLLED — and today it cannot be.** Arm
(d) asks for «a pair healthy in one project, poor in another» as a DISCIPLINE/ENVIRONMENT finding,
i.e. a causal steer about a project. But the same criteria make effort tier the MANDATORY control for
any causal steer (arm (b)), and `by_project` is a MARGINAL POOLED ACROSS EFFORT TIERS. The instrument
carries `by_effort_tier` and `by_project` as separate marginals and NO project×effort JOINT cell —
deliberately, because a product grid would be hundreds of mostly-n<5 cells (the phantom-cell
decision recorded in the view's own `stakes` note). So a project difference is EXACTLY the confounded
comparison arm (b) forbids, arriving by a different door: two projects that sent the pair different
MIXES of routed work will differ in mix whatever their discipline. The measured case is stark — the
pair carrying the largest gap (0.260) has an effort population of critical 316 / unknown 62 / normal
3, so that gap lives almost entirely in critical-tier work, and whether the two projects sent the
same critical work is a question no carried row can answer.
**THEREFORE: a `by_project` difference is reported as a DESCRIPTIVE OBSERVATION and NEVER as a
discipline/environment finding or a steer.** It names a place to look, not a cause. **NO-DATA:
controlled cross-project divergence — instrument absent: no project×effort_tier joint carrier.**
RESTORATION CONDITION: a joint cell (or an equivalent stratified read) exists and both of its sides
clear the eligibility bound — at which point the arm becomes a finding arm again under the rule below,
unchanged. Until then the two bounds below govern which differences are worth REPORTING; they do not
promote any of them to a cause.

**A DESCRIPTIVE DIFFERENCE STILL CARRIES ITS CARRIER AND ADEQUACY ON BOTH SIDES.** Arm (d) is read off
`by_project` — the marginal built for this mandate, because `project_count` and the bare
`projects` list structurally cannot express «healthy here, poor there». And a divergence is a
comparison of TWO cells, so BOTH cells are judged on their own `sample_size` before any
observation is REPORTED at all. **The cell-level rule is DECLARED, so two runs on the same
rows reach the same conclusion** — «judge it on its own n» alone is discretion wearing a rule's
clothes. The rule, and it is an EVIDENCE rule, not a score, rank or band (§4 fence): a divergence
REPORTABLE DIFFERENCE requires TWO conditions, and the run states both n's and the measured difference
beside it: (i) ELIGIBILITY — BOTH cells at `sample_size` ≥ 30; and (ii) the DIFFERENCE TEST — the
absolute difference in adverse share (RED+ABORT over the cell's own n) is **≥ 0.10**, i.e. ten
percentage points. Eligibility alone is not enough: without (ii) two runs reading identical rows would
report different sets, which is discretion by another name. These are REPORTING filters over an arm
that is descriptive throughout — passing both does NOT promote a difference to a finding, a
divergence or a cause. Failing either, the observation is not reported at all. Why 30 and not the pair-level floor of 5: the floor
answers «is this pair's mix claimable at all», a one-sided question calibrated on a pooled n, and
 DECIDED it does not transfer to a marginal's bucket (§thin/adequate line below). A DIFFERENCE
between two cells is a two-sided question and needs the stricter bound; 30 is the conventional
small-sample threshold, declared here so it is inspectable and arguable rather than re-invented per
run. And 0.10 for the difference: a plain absolute bound on a share, reproducible from the two cells
alone, with no weighting, ranking or composite behind it. Revisit either bound on evidence, never per
run.

**DECLARE THE COMPARISON UNIVERSE, AND EVALUATE ALL OF IT.** A threshold applied to a convenience
subset is worse than no threshold: it reports a conclusion about the whole population from whatever
rows the sweep happened to print. The universe is DECLARED — **for EACH surviving pair, every
unordered couple of its `by_project` cells in which BOTH cells are eligible.** Cross-PAIR comparison
is OUT of scope: the theme's unit is one pair observed in two projects, and comparing different pairs
re-opens the stakes confound the `by_effort_tier` arm exists to close. The run states the SIZE of the
universe, how many comparisons qualify, and EVERY qualifying one — never a bare «no divergence
found», which is a claim about the entire universe and has to be earned over all of it. THIS RULE WAS
WRITTEN AGAINST A MEASURED FAILURE: a run evaluated ONE comparison, measured a 3.4-point gap, and
reported the cutoff difference-free; the real universe held 52 eligible comparisons of which 13
passed both bounds, the largest at 26.0 points. The conclusion was not incomplete — it was inverted.
(Those 13 are DESCRIPTIVE observations under the control rule above, not discipline findings; the
universe rule governs how completely the set is evaluated, never what the set is allowed to claim.)

**No new state (guardrail).** Every T10 signal is DERIVED from existing events (session_started worker
triple + external_audit_completed auditor triple, both) via existing saved-view carriers. T10
adds no store, no status field, no FSM, no score — it is the observation loop's periodic read.

**4-filter admission (SPEC-0057 owner-gated new-theme bar; observation-loop plan).** F1
existing analog = the inspection roster itself + the `observation`/`observation-rollup` saved-view
family (reused, not a parallel mechanism). F2 view/content, not a new entity (a theme = a
lens-checklist over an existing derived view). F3 removed = the ad-hoc "where to look to see how
AI» question that had no periodic home. F4 real pull = the SPEC-0135 doctrine + the CHARTER
§Success-criteria measurement gap it closes (the 10th inspection theme SPEC-0135 §Scenario names).

