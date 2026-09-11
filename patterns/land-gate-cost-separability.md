---
name: land-gate-cost-separability
class: observation
binding: []
sourced_from: <durable artifact> (measurement of this repo's own events.jsonl, window 2026-08-18..2026-08-25) — RE-DERIVED 2026-08-30 by over the same window, n=959 land_completed rows, under the corrected reset-aware wait fold + the four 2026-08-17 abort rows named in the card scope
applies_to: reading whether a rejecting land gate's wall-clock cost is separable from the verify it precedes — the open question behind the batching plan's pre-flight entry condition. Consumed by that plan's pre-flight decision; consumed by for the instrumentation it names.
---

# Observation — a rejecting land gate's cost IS separable, and the gates are not what an aborted land costs

> **Reading, not a fix.** Produced by. Implementing pre-flight is explicitly out of scope
> and remains the batching plan's decision. This artifact supplies the numbers that decision needs.

## §1 — Verdict in one line

The split is **possible today for three of its four components**, from journal fields the card did
not know were there; and it overturns the question's own premise — the gates are **cheap** (median
0–87 s of evaluation), the **verify run is cheaper still** (103 min out of 6971 min, 1.5 %), and
**68 % of every aborted land is spent waiting for the land reservation** before any gate or any
verify runs at all.

## §2 — Method

### 2a. The three sources, all already recorded, no new instrumentation

| # | Source | Gives | Coverage in window |
|---|---|---|---|
| A | `land_completed{status:abort}.duration_ms` | the single undifferentiated total | 411/411 aborts |
| B | `land_completed{status:abort}.verify_metrics` — `verify_wall_ms`, `queue_wait_ms` | verify-admission wait + verify run | 220/411 aborts |
| C | `waiting_for_land_reservation` / `waiting_for_verify_admission_slot` `.waited_s`, keyed by `branch` (`_LAND_QUEUE_WAIT_TYPES`, `bin/lib/worktree.py:9562`) | reservation wait | 68 440 rows repo-wide |

Source B is the one the card missed. It is the abort half of the verify metrics, added by
precisely because failing lands are the only lands that can evidence a selector disagreement — and
it happens to carry the wall-clock split too.

### 2b. The attribution arithmetic

For one abort row at `ts` with total `duration_ms`:

```
episode_window = [ts - duration_ms, ts]
reservation_s = SUM of the per-PARK peaks of the source-C rows for this branch inside
                  episode_window, taken per wait-type and summed across types
verify_admit_s = verify_metrics.queue_wait_ms / 1000 (0 when B absent)
verify_run_s = (verify_wall_ms - queue_wait_ms) / 1000 (0 when B absent)
gate_attrib_s = duration_ms/1000 - reservation_s - verify_admit_s - verify_run_s
```

`verify_wall_ms` is **queue-inclusive** (documented at `bin/lib/worktree.py:28420-28427`), which is
why the run is derived by subtracting the queue rather than read directly.

**The wait fold is a reset-aware SUM, and it used to be a `max` ( — the correction).**
`waited_s` is cumulative WITHIN ONE PARK and **restarts at 0** when a displaced land parks again
(`bin/lib/worktree.py` — `_t0` is re-seeded on every entry to `_acquire_land_reservation`;
`bin/lib/batch_landing.py` — it restarts when a NEW land process parks; an observed reset is
recorded for at 11:17:14Z after 561 s of waiting). A `max` over such a series therefore
reported only the land's **longest single park** while the land paid **all of them** — the figure
was low by construction, not by sampling. The fold now cuts a new park at every **DROP** in
`waited_s` and sums the per-park peaks (`journal.fold_wait_segments`, the one home both this reading
and SPEC-0119 rule 27 resolve through). It is emphatically **not** a naive sum across rows, which
would count each rising series over and over; **a wait that never reset is one segment and folds to
exactly the same number as before.**

**What the correction is worth, isolated from every other variable.** Both folds run over the SAME
411 abort rows, 2026-08-30:

| fold | reservation total | share of the 6971 min |
|---|---:|---:|
| `max` (before) | 4334 min | 62 % |
| reset-aware sum (after) | **4774 min** | **68 %** |

440 minutes of real waiting were invisible in the published figure, and every `gate↑` upper bound
was correspondingly 440 minutes too generous — in the one direction that makes a queueing problem
read as a gating one.

**The population is 411 aborts, not the 352 the original run saw.** Re-deriving the same
window on 2026-08-30 reads 959 `land_completed` rows (548 ok / 411 abort) where the original run
read 815 (463 / 352): the journal now holds more of that window's segments than it did on
2026-08-25. That is a POPULATION change, not the fold's doing, which is exactly why the table above
runs both folds over one population — the delta there is the arithmetic alone. Every figure from §3
onward is the 2026-08-30 re-derivation under the corrected fold; the original run's figures are
superseded, not amended.

### 2c. Why the two waits are summed and not deduplicated

They are different phases: `waiting_for_land_reservation` is the reservation, `queue_wait_ms` is the
SPEC-0132 verify-admission slot. This was checked, not assumed — across the 220 verify-reaching
aborts `median(reservation_s - verify_admit_s) = -1.8 s` while individual rows diverge widely
(e.g. reservation 1429 s against admission 242 s), and `waiting_for_verify_admission_slot`
heartbeats do not co-occur with the reservation heartbeats on these rows. Two medians that happen
to land near each other are not one series.

### 2d. Population, window, and the segment hazard

Window 2026-08-18..2026-08-25 inclusive, as re-derived 2026-08-30: **959 `land_completed` rows,
548 ok / 411 abort** (the original 2026-08-25 run of the same window saw 815 / 463 / 352 — see §2b).
A raw read of `events.jsonl` sees only 2026-08-18 onward — the journal is segmented
(SPEC-0190 rule 1), so the fold reads every `archive/events-*.jsonl` plus the live segment and
de-duplicates on `(ts, canonical data)`. Skipping this silently drops the card's own 2026-08-17
rows, which live entirely in an archive segment.

Every number here is folded from **production rows written by real lands** — no bench, no
re-run under a profiler (`lessons/a-measurement-taken-outside-its-harness-measures-the-harness.md`).
The reconstruction script is a WORKSHOP instrument (`dev-utilities/`, a surface a release does not
carry — SPEC-0195 rule 1a): it folds the workshop's own journal, so it is named here as the
provenance of these figures, not offered as a tool that travels with this pattern. The method it
implements is stated in full above, which is what makes the figures re-derivable on any journal.

## §3 — What separated, and what did not

**AC1 explicitly asks which components of a land duration this could and could not separate.**

| Component | Separable? | How, and on what population |
|---|---|---|
| Reservation wait | **YES** | source C, per branch per episode, reset-aware sum (§2b); all 411 aborts |
| Verify-admission wait | **YES**, on 220/411 | source B `queue_wait_ms`; **absent on the 191 aborts that never reached verify**, where it is genuinely zero — the branch never queued for a slot |
| Verify run (queue-exclusive) | **YES**, on 220/411 | source B `verify_wall_ms - queue_wait_ms`; zero by construction on the other 191 |
| Gate evaluation | **NO — only an upper bound** | it is the *remainder* after the three above, so it bundles gate evaluation **plus** candidate assembly, the merge, the graph rebuild, commit bookkeeping and stack unwind. Reported everywhere below as *gate-attributable (upper bound)*, never as gate cost |

So the honest answer to AC3 is **not** "cannot determine". It is: three of four components separate
from existing fields; the fourth is bounded above but not isolated. See §7.

**Two premises in the card's own scope are corrected here** (CHARTER §Principle 7 — recorded, not
silently overridden):

1. *"verify_duration_ms was 0 on all four aborts"* — **refuted; the key is ABSENT, never zero.**
   `_emit_land_abort` (`bin/lib/worktree.py:15335`) has no write of `verify_duration_ms` or
   `admission_wait_ms` on any path. Across the window the keys are absent on 411/411 aborts and
   present on 548/548 ok rows, and the value `0` occurs nowhere. The four rows the card cites
   resolve by duration to `work/collapse-duplicate-cards` 332 s, `task/` 485 s, 729 s and
   1366 s (11:38:58Z / 11:51:58Z / 12:15:37Z) — key absent on all four.
   **Origin of the "0":** `dev-utilities/measure-land-budget.py:247` reads
   `d.get("verify_duration_ms") or 0`, coercing absent to zero and then classifying *every* abort
   as `aborted_before_verify` with `aborted_verify_wall_hours: 0.0` — although 220/411 demonstrably
   ran the suite. That tool's headline split between "redo driven by failing tests" and "redo driven
   by main-advanced races" is therefore wrong on the abort side. Captured as deviation
   `measure-land-budget-coerces-absent-verify-duration-to-zero`
   (`events.jsonl#ts=`); fixing it is out of this card's scope.
   **This settles the dissonance scope asks both cards to reconcile: ABSENT is the true
   fact, so the remedy is to WRITE the keys, not to correct a zero.**

2. *"the journal gives no split between waiting, candidate assembly, gate evaluation and verify"* —
   **refined:** it gives waiting (both kinds) and verify, and bounds assembly+gate jointly.

## §4 — Per-gate phase split (2026-08-18..2026-08-25, 411 aborts, re-derived 2026-08-30)

Medians in seconds; `total` in minutes. `reserv` = reservation wait, `admit` = verify-admission
wait, `run` = verify run, `gate↑` = gate-attributable **upper bound**.

| abort class | n | total (min) | med total | med reserv | med admit | med run | med gate↑ | reached verify |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| verify-failed | 194 | 3955 | 777 | 214 | 223 | 8 | 275 | 194/194 |
| verify-timeout | 26 | 1056 | 813 | 50 | 262 | 13 | 351 | 26/26 |
| rebaseline-unauthorized | 34 | 622 | 537 | 60 | 0 | — | 228 | 0/34 |
| merge-non-union-conflict | 44 | 507 | 103 | 60 | 0 | — | **15** | 0/44 |
| corpus-integrity | 14 | 242 | 56 | 0 | 0 | — | **53** | 0/14 |
| retries-exhausted | 1 | 235 | 14118 | 8967 | 0 | — | 5151 | 0/1 |
| unclassified (dirty main) | 9 | 227 | 423 | 401 | 0 | — | **23** | 0/9 |
| audited-diff-stale | 33 | 124 | 38 | 0 | 0 | — | **38** | 0/33 |
| repeated-abort-backstop | 16 | 2 | 6 | 0 | 0 | — | 6 | 0/16 |
| concurrent-land-same-worktree | 14 | 1 | 5 | 0 | 0 | — | 4 | 0/14 |
| work-batch-uncarried-product-source | 1 | 0.1 | 6 | 0 | 0 | — | 6 | 0/1 |
| uncommitted-dirt | 25 | 0.01 | 0.03 | 0 | 0 | — | 0.03 | 0/25 |

**Aggregates.**

- **Pre-verify aborts (191, 1960 min):** reservation wait **1612 min (82 %)**, gate-attributable
  348 min (18 %).
- **Verify-reaching aborts (220, 5011 min):** reservation **3162 min (63 %)**, verify-admission
  813 min (16 %), **verify run 103 min (2 %)**, remainder 932 min (19 %).
- **Across all 411 aborts (6971 min):** reservation **4774 min = 68 %**; verify run **103 min = 1.5 %**.

The headline the card was reaching for inverts: an aborted land is overwhelmingly *queueing*, not
*gating* and not *verifying*.

## §5 — The three gates the card names

### (a) spec-edit chokepoint (SPEC-0005)

Fires at `bin/lib/worktree.py:9083`. It has no `abort_class` of its own, so it is found by reason
text rather than by class. Two populations, both reported because they differ:

| population | n | med total | med gate↑ | p90 gate↑ |
|---|---:|---:|---:|---:|
| whole recorded history | 117 | 108 s | **87 s** | 312 s |
| the 2026-08-18..25 window (what the §8 script prints) | 19 | 397 s | **71 s** | — |

(The chokepoint's own cost is unmoved by the fold correction: its rows carry no reset.)

The gate's own cost is stable across both (87 s vs 71 s); what moves is the *total*, because the
window's rows queued longer. That stability is the point — see below.

Two findings beyond the cost:

- **It is a cheap gate sitting behind an expensive queue.** In-window rows show it firing *after*
  the branch already paid its reservation (0–1634 s) and its verify-admission slot (192–263 s),
  for ~40–100 s of its own work. This is the single clearest pre-flight candidate in the corpus.
- **It has no `abort_class` of its own and contaminates two that do.** Its 117 rows are classed
  `verify-failed` (108) and `corpus-integrity` (9) — 10 and 9 respectively inside this window, because it dies through those `_die` paths.
  Any reading that treats `verify-failed` as "a real defect the gate caught" — including the
  SPEC-0119 rule-27 debt echo, which reports `verify-failed 167x 3528.4min` as *the gate earning its
  keep* — over-counts by however many chokepoint refusals it contains. That is a structural
  refusal, not a failing test.

### (b) pinned last-green / rebaseline (SPEC-0077) — two arms, and they must not be averaged

`rebaseline-unauthorized` is one `abort_class` carrying two refusals whose cost differs by 8×.
Separated here by the `abort_preflight` row-shape marker :

| arm | n | total (min) | med gate↑ | med reserv |
|---|---:|---:|---:|---:|
| authorization — preflight (already moved early) | 18 | 348 | **75 s** | 290 s |
| waive-coverage (reads `pinned_bad` after a full pinned run) | 16 | 274 | **587 s** | 0 s |

This is the measured confirmation of claim that a trend over their union describes
neither. Note the honest asymmetry: for the waive-coverage arm the "gate" *is* a full pinned run,
so its 587 s is not a cheap check that could simply be hoisted — it is the suite, wearing a
different refusal.

### (c) rebaseline-waiver scope refusal

Not a separate class — it is the waive-coverage arm above, and its sub-cases are already recorded
as `rebaseline_bad_token_reasons` (`ambiguous` / `insufficient-bare-token` / `no-match`).
Cost as measured in (b): median 587 s of gate-attributable time, none of it queue.

## §6 — AC2: the falsifier for the pre-flight hypothesis

**The claim under test.** Pre-flighting every candidate before batch formation is worth it only if
what it saves in poisoned batches exceeds what it costs in per-candidate evaluation.

**The measured red-batch price** (card scope, 2026-08-17, one poisoned member `task/`):
1294 s of innocent solo verify (225 + 518 + 551) + 2580 s of the poisoned member's own failed
attempts = **P = 3874 s**.

**The measured formation load** (`land_batch_formed`, same window, re-derived 2026-08-30):
**795 formations**, of which **137 are multi-member**. Total candidate-evaluations if every
candidate is pre-flighted at formation: **1024**.

**Break-even.** With `c` = cost per candidate evaluation and `R` = poisoned batches prevented over
the window:

```
1024 · c = R · 3874 => c* = 3.78 · R seconds
```

**Read as a falsifier — the hypothesis dies if `c` exceeds `3.78 · R`.** Substituting the measured
gate costs from §4/§5 gives the required prevention rate per week:

| pre-flighted gate | measured c | R needed per week to break even |
|---|---:|---:|
| uncommitted-dirt | 0.03 s | 0.008 |
| merge-non-union-conflict | 15 s | 4.0 |
| audited-diff-stale | 38 s | 10 |
| corpus-integrity | 53 s | 14 |
| spec-edit chokepoint | 71 s | **19** |
| rebaseline authorization arm | 75 s | **20** |
| rebaseline waive-coverage arm | 587 s | **155** |

**The observed R, and why it is the decisive number.** In the same 795 formations, **zero** land
rows carry `members_removed` — no batch dissolution was recorded in the window at all. The card's
red-batch price is **one incident on 2026-08-17, the day before the window opens**, so the most
defensible reading of R over the window is `R ≈ 0`, and even generously `R = 1` clears only the
first two rows of that table.

**Therefore the falsifier fires for every gate above ~4 s per candidate, at the observed rate.**
Formation-time pre-flight of the chokepoint would need to prevent 19 poisoned batches a week and
prevented, on the record, none. **Pre-flight justified as batch-poisoning insurance is falsified by
this data.**

**But the same numbers justify a different move, and this is the reading's substantive finding.**
The cost pre-flight would actually recover is not the poisoned batch — it is the **queue wait a
cheap gate sits behind**. Each of the 191 pre-verify aborts paid a median-inclusive **8.4 minutes**
of reservation wait (1612 min total) to be refused by a check costing 0–53 s that depended on
nothing the queue provides. That saving is **1612 min over 7 days, independent of batch size,
independent of poisoning rate, and it needs no batch to exist at all** — it is a hoist, not
insurance. Whether to make it is the batching plan's call; this card only prices it.

## §7 — AC3: the residual, and the instrumentation a later card needs

**What remains unseparable.** Gate evaluation cannot be isolated from candidate assembly, merge,
graph rebuild and unwind — `gate↑` is a subtraction remainder, so every figure in its column is an
upper bound. On the verify-reaching side that remainder is 932 min (19 %) and is not attributable
at all today.

**The instrumentation is already filed as ``** — *"Record on an aborted land row the same
wall-clock split an ok land row already carries"* (write `admission_wait_ms` and
`verify_duration_ms` as present keys on the abort payload, make absent-vs-zero stop being the
reader's problem, and have SPEC-0119 rule 27 consume the split). **No duplicate card is filed by
; is the named instrumentation and this reading is cited into it.**

Two things this reading hands that its own scope does not yet have:

1. **The absent-vs-zero dissonance is settled: ABSENT, on 411/411, verified against the emit code.**
    scope lists this as unreconciled and asks for exactly this determination.
2. **Its stated hypothesis is confirmed for one field and refuted for the other.** supposes
   "the abort emit path already holds both values". For the **verify-admission** half that is true —
   `verify_metrics.queue_wait_ms` is already on 220/411 abort rows and needs only promoting to a
   top-level key. For the **191 pre-verify aborts** it is false: those rows have no verify phase to
   report, so the honest record there is an explicit zero plus a marker that no verify was
   attempted, not a value fetched from machinery that never ran.

**What as scoped still would not answer,** and what a further card would need: an explicit
timestamp at the gate-evaluation boundary (a `gate_entered` mark, or a per-phase `duration_ms`
breakdown on the abort row) to split assembly from gate evaluation. Until then the §4 `gate↑`
column stays an upper bound, and the §6 break-even table is correspondingly **conservative** — the
true `c` is at or below every figure shown, which strengthens rather than weakens the falsifier.

## §8 — Re-deriving these numbers

```
python3 dev-utilities/fold-land-abort-phase-split.py --since 2026-08-18 --until 2026-08-25
```

Reads every journal segment, prints the §4 table, the §5 arm split and the §6 break-even
arithmetic. Read-only; no repo state is touched.

## §9 — Every reader that publishes a reservation-wait figure ( AC3)

The fold corrected in §2b is not the only place `waited_s` is folded into a published number, and a
correction applied to one reader while another keeps the old fold is two numbers that disagree —
worse than the undercount. The enumeration below is the complete set as of 2026-08-30, found by
sweeping `bin/`, `dev-utilities/` and `patterns/` for `waited_s` and for
`journal.LAND_QUEUE_WAIT_TYPES`.

| reader | what it publishes | disposition |
|---|---|---|
| `dev-utilities/fold-land-abort-phase-split.py` + this reading | per-land reservation wait | **SWITCHED** to the reset-aware sum (§2b) |
| `bin/lib/debt.py::_abort_attributed_wait_ms` (SPEC-0119 rule 27) | per-land queue minutes vs verify-run minutes | **SWITCHED** — same question, same fold, same undercount |
| `bin/lib/views.py::_view_admission_series` (SPEC-0132 rule 4) | `peak_wait_s_median` / `peak_wait_s_max` | **OUT OF SCOPE** — what it publishes is *named* a PEAK and is true as one (the longest single park), not a claimed total; and its rule-4 numerator is boolean membership (*did* this land queue), which no fold change can move. Switching it would redefine a rule-4 series, not correct an arithmetic error |
| `dev-utilities/measure-land-budget.py::_fold_queue` | per-EPISODE wait distribution | **OUT OF SCOPE — no defect**: it already cuts an episode at every `waited_s` DROP and is the prior art this correction follows |

No other site folds `waited_s` for publication: `bin/lib/journal.py` defines the carrier, the
observation reader and (since) the segment fold itself; `bin/lib/batch_landing.py` reads it
for phantom/re-park detection, preferring `queued_since_s`; `bin/lib/worktree.py` emits it.

**Named, not widened into ( scope bound):** `peak_wait_s_*` is honestly labelled, but a
reader asking "how long did this land queue" will read a peak as a total. That is its own card.
