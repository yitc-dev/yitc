---
name: verify-cost-playbook
class: technique
sourced_from: <durable artifact> (owner decision 2026-10-16, the verify-acceleration review in the kernel Controller session e116fd80). Folds six kernel patterns (land-gate-cost-separability, test-file-wall-attribution, verify-venue-when-it-pays, choosing-a-bound-tests-boundary, test-isolation-strategies, verify-layer-adapter-protocol), cryptochart's own test method and research notes (its <workshop-spec>, lessons and docs/research/2026-10-04-verify-cost + 2026-10-08-interaction-test-cost, read-only), the public proposals #33 #93 #98 #102 #106 #107 #109, and the cross items X-2003..X-2022 filed to <project> and <project> on 2026-10-16. Every number below is quoted from one of these, with its ref.
applies_to: making a project's verify cheaper — reading where its test time goes, choosing a technique, declaring it, and knowing what it risks. The reference the weekly test-suite-shape inspection (Lens C) reads its findings against.
cites:
  - SPEC-0057
  - SPEC-0132
  - SPEC-0152
  - SPEC-0165
  - SPEC-0181
  - SPEC-0186
  - <workshop-spec>
  - <workshop-spec>
  - SPEC-1030
  - SPEC-1051
  - <workshop-spec>
  -
---

# Verify-cost playbook — the techniques that make a project's checks cheaper

> **Plainly.** Every land and every card's self-check runs a project's tests, and on a busy project
> that time is most of what a change costs. This page lists the techniques that have cut it in
> practice, on this methodology's own projects, each with the number it moved and where that number
> was read. It adds no rule: where a technique needs a declaration, the rule behind it is the spec
> named in its **Do** line, and that spec wins on any difference.

**How to read an entry.** **Cuts** — which cost it removes. **Applies when** — the reading that says
your project has that cost. **Do** — the declaration or edit, and the spec that governs it. **Risk** —
what you can lose. **Measured** — a project, its numbers, and the ref you can re-read them from.

**Neighbouring patterns.** Two more pages go deeper on one axis each and are not repeated here:
`patterns/consumer-suite-parallelization.md` (making a consumer suite parallel and splitting its
layers) and `patterns/hermetic-in-time-suite-latency-triage.md` (a hidden retry stall
inside a suite declared hermetic).

**Order of work.** Measure first (the next section), then take the fixed costs, then the layer cuts,
then the run discipline. A technique whose **Applies when** reading is absent on your project is
not for you yet.

## Measure before cutting

### Read where the wall goes before choosing a cut

**Cuts.** Cuts aimed at the wrong cost — the commonest waste in this whole page.
**Applies when.** Always first. Fold the recorded land and test rows of the last week: wait vs run,
per-layer wall, per-file wall, red causes.
**Do.** The fold methods are in the two kernel readings: the phase split of an aborted land
(`patterns/land-gate-cost-separability.md` §2) and the per-file exclusive attribution
(`patterns/test-file-wall-attribution.md` §2). Lens C (the weekly test-suite-shape inspection,
SPEC-0057 §3) re-runs these readings per repo.
**Risk.** None; a reading taken outside the harness that produced the numbers measures the harness.
**Measured.** Kernel, 411 aborted lands over one week: 68 % of their time was the wait for the land
reservation and 1.5 % was the verify run itself (`patterns/land-gate-cost-separability.md` §4).
Kernel suite: the cuts that keep every check cut about 14 % of test work, while the serialized tail
of eleven files was 35 % of the leg (`patterns/test-file-wall-attribution.md` §5–§6).

### Profile a slow file before rewriting it

**Cuts.** Rewrites of the part of a test that is not slow.
**Applies when.** One file or one class of files dominates a layer.
**Do.** Profile the test process (a sampling or call profiler, `time` for user vs sys) and attribute
by cause before choosing between test edits and engine edits.
**Risk.** None.
**Measured.** cryptochart: 14 interaction files took 349 s of 464 s; the product's own code was 1.7 %
of it and the DOM emulation 52 % (cryptochart `docs/research/2026-10-08-interaction-test-cost/summary.md`).
Kernel: in the heaviest files, git fixture commands were 5.6 % of the wall and in-process work 56 %
(`patterns/test-file-wall-attribution.md` §1).

## The fixed costs first

### One install per land, in one deps layer

**Cuts.** A package install (`npm ci` and the like) repeated in every layer.
**Applies when.** Count the installs one land performs; more than one is this cost.
**Do.** One first layer carries the `prep:` that installs; the test layers carry none (the layer
contract: SPEC-0152 rule 16).
**Risk.** Low: a layer that silently needed its own install fails loudly on the first run.
**Measured.** cryptochart: seven installs per land became one; together with a lighter trace and the
history tests in parallel, a land running every layer went from 869 s to 689 s (cryptochart
`lessons/measuring-on-this-host.md`, `docs/research/2026-10-04-verify-cost/trial-report.md`). <project>:
24 Stage-6 runs went red in the install step alone (X-2005).

### A lighter browser trace

**Cuts.** A cost every browser test pays whether it fails or not.
**Applies when.** The runner records a full trace for every test.
**Do.** Record traces on failure or on retry only, in the runner's own configuration.
**Risk.** A failure seen once without its trace is harder to read.
**Measured.** cryptochart: full traces cost 54 s against 46 s on two spec files (cryptochart
`lessons/measuring-on-this-host.md` there).

### Process starts and repeated builds — measure, then usually leave them

**Cuts.** Shell and process start-up, repeated production builds.
**Applies when.** A shell-heavy layer, a script run per test case.
**Do.** Trace one run with timestamps per command before touching it.
**Risk.** Spending a card on a cost too small to matter.
**Measured.** cryptochart: one process start costs about 3.3 ms (1,000 runs in 3.27 s); nine production
builds came to under 20 s and were left as they were; a 9 s security script run 16 times (~145 s of
562 s) was measured and also left (cryptochart `docs/research/2026-10-04-verify-cost/ops-layer.md`).

### Two cheap settings for a DOM-emulation suite

**Cuts.** Per-interaction overhead in a component suite.
**Applies when.** A profile shows the DOM emulation, not the product, holds the time.
**Do.** The testing library's own settings (skip hidden-element queries by default, skip the pointer
events check) in the suite's setup.
**Risk.** The hidden-element default weakens the proof that a control is exposed to the user.
**Measured.** cryptochart: one file went from 47.0 s to 42.7 s (−9 %) (cryptochart
`docs/research/2026-10-08-interaction-test-cost/summary.md`).

### Share a derivation many test files recompute

**Cuts.** The same whole-corpus derivation rebuilt inside every file that needs it.
**Applies when.** Profiles of several heavy files show the same function at the top.
**Do.** A content-keyed cache or one per-run artifact the files read; the assertions stay.
**Risk.** A cache keyed on less than the inputs serves a stale value; key it on content.
**Measured.** Kernel: the corpus-derivation group was 26 files and about 588 s of expected saving, the
largest single group (`patterns/test-file-wall-attribution.md` §5, followup `fu_058acc949384`).

## Layers by area

### Cut layers by product area, with `subject_globs` from a dependency audit

**Cuts.** Layers that run although nothing they test changed.
**Applies when.** The per-layer skip rate is low, or a docs-only land runs code layers.
**Do.** Declare each layer's `subject_globs` (SPEC-0152 rule 16) as a superset of what its command
really reads — found by auditing the layer's dependencies, not guessed — and add a new path to its
layer's globs in the same card that adds it. How to lay the tests out is SPEC-0165 item 12.
**Risk.** A path the layer reads but its globs miss gives a false skip; a project-wide file inside a
layer's globs defeats the split.
**Measured.** cryptochart: a card-only land went from 563 s to 14–21 s (cryptochart
`docs/research/2026-10-04-verify-cost/trial-report.md`); before a fix, a project-wide file in the
subjects made seven of eleven full lands run every layer (same report). <project>: a layer was skipped on
about 21 % of 372 lands (X-2003).

### Move heavy, narrow tests into a layer of their own

**Cuts.** A whole-stack layer run for changes only a few of its tests read.
**Applies when.** One layer holds most of the verify hours and is rarely skipped.
**Do.** Split it by product area, each part with its own `subject_globs` (SPEC-0165 item 12 (b)); the
split's mechanics and its transition bill are `patterns/consumer-suite-parallelization.md`
§Splitting a monolithic layer.
**Risk.** More layers to keep declared; a shared fixture file in every part's globs undoes it.
**Measured.** <project>: the stack layer took 20 of the 34 verify hours and was skipped on 12 % of lands;
after the same move at cryptochart its lands skipped the browser layers on 50–60 % (X-2013).

### Move a layer's required checks into a layer of their own

**Cuts.** A bring-up paid on every run by a layer whose own units are cheap.
**Applies when.** A layer's bring-up (its `prep:` and the stack its `required:` checks run in) is most of
its wall, its units take seconds, a deciding selection would save only those seconds, **and** the two
halves read different inputs, so most changes would wake one half, not both. Read the co-fire rate first:
where a split's parts mostly run together, each re-pays the bring-up and the split loses
(`patterns/consumer-suite-parallelization.md` §How FINE to cut).
**Do.** Unit selection cannot skip the `required:` checks: they run on every run of the layer, a run
that selects no unit included (<workshop-spec> rule 5, SPEC-1030 rule 4), and so does the bring-up they need.
Only the whole-layer skip of a layer no changed path touches skips the bring-up too (SPEC-0152 rule 16).
So put the checks-only half in a layer of its own, with `subject_globs` covering every input of its
checks, and leave the units in theirs; the split's mechanics are `patterns/consumer-suite-parallelization.md`
§Splitting a monolithic layer.
**Risk.** A checks layer whose globs miss an input of its checks is skipped when it should run; each
change that reaches both halves pays the bring-up twice, so overlapping inputs undo the saving.
**Measured.** <project>: the design layer's median wall was about 130 s, nearly all bring-up, for 5 units
of about 1 s each, so a deciding selection would have saved 1–5 s a run; the kernel declined to scope
the checks by their own inputs and named this split instead (X-2070).

### Write `subject_globs` as patterns, not per-file lists

**Cuts.** Full-layer runs caused by editing the layer declarations themselves.
**Applies when.** Shadow selection answers `verify-implementation-touch` or `declared-check-surface`
on most decisions.
**Do.** Globs as directories or name patterns; a verify script that finds its files by pattern. The
answers and what each means: `patterns/verify-layer-adapter-protocol.md` §Making a layer narrow.
**Risk.** A glob too wide admits paths the layer's tests do not read (`unknown-path`).
**Measured.** Two projects, 78 lands, 141 layer decisions, 136 of them the full layer; one project
answered one of those two reasons on 74 of its 101 decisions
(`patterns/verify-layer-adapter-protocol.md` §The two commonest answers).

## Parallel layers only after a load reading

### Run layers side by side, sized to the host

**Cuts.** The wall of layers run one after another.
**Applies when.** Wall ÷ sum of layer times is near 1 **and** a load reading of the heaviest layer run
alone shows spare cores.
**Do.** `verify.independent_layers` and per-layer worker shares in `yitc-ops.yaml` (SPEC-0152 rule 16;
what makes layers truly independent is SPEC-0041 §1c); the order of adoption is
`patterns/consumer-suite-parallelization.md` §Adopting concurrency.
**Risk.** Shares summing above the host's allotment overload it, and timing-bound tests go red.
**Measured.** <project>: wall/sum 1.03 over 314 full runs — about 11 h of 23.3 h (47 %) was waiting
(X-2004). cryptochart, 4 cores: three layers together failed 10 timing-bound tests at load 17, so it was
not taken there (cryptochart `lessons/measuring-on-this-host.md`).

### Split the longest file of a parallel layer

**Cuts.** Idle slots while one long file finishes.
**Applies when.** One file is a large share of its parallel layer's wall.
**Do.** Cut that file into several; a test over half its time limit is cut too.
**Risk.** Shared setup paid more than once.
**Measured.** cryptochart: an ops layer went from 234.4 s to 152.9 s (−35 %) with the file sum unchanged
(cryptochart `docs/research/2026-10-04-verify-cost/ops-layer.md`). <project>: one file is 186 of 253 s
(74 %) of its layer (X-2016).

### Take the serialized tail into the pool where it is safe

**Cuts.** Files run one at a time after the parallel pool.
**Applies when.** The tail is a large share of the leg wall.
**Do.** Re-check each line of `tests/load-sensitive.txt` with its holder (Lens C reading 3).
**Risk.** A file that truly needs the quiet tail goes flaky in the pool.
**Measured.** Kernel: eleven tail files were 155 s, 35 % of the leg; pooling them models the leg 438 s →
287 s (`patterns/test-file-wall-attribution.md` §6, followup `fu_5bc5d0a56c0c`).

## Cheap checks first

### Run size and lint checks before the long ones

**Cuts.** A long run that ends red on a check that takes seconds.
**Applies when.** Red causes include file-size limits, lint or formatting.
**Do.** A first layer of the cheap checks, or the adapter's `required:` commands (<workshop-spec> rule 1).
**Risk.** None beyond one more layer to declare.
**Measured.** <project>: the file-size limit reddened 40 Stage-6 runs and lint 13, each found at the end of
a 4–5 min run (X-2006).

### Prefer the lightest test class that proves the step

**Cuts.** Stack and browser tests for outcomes an in-memory test proves.
**Applies when.** A step's only test needs the database or the whole stack although its outcome is a
computed value.
**Do.** Split load from compute and bind the logic to in-memory tests
(`patterns/choosing-a-bound-tests-boundary.md` §0); for an engine self-test, the isolation techniques of
SPEC-0041 §2; for a database product suite, `patterns/test-isolation-strategies.md`.
**Risk.** A wiring fault only the stack sees — keep one wiring test per path.
**Measured.** <project> : 4 stack tests at 27.7 s became 2 stack tests (21.0 s) and 10 in-memory tests
(2.6 s) (`patterns/choosing-a-bound-tests-boundary.md` §0).

## Time limits and waits

### Set a timeout as a band around the measured time

**Cuts.** Red runs from a limit set just above a quiet-host reading.
**Applies when.** A layer's p90 is close to its `timeout:`.
**Do.** Set the limit near twice the measured time and re-declare it when a reading passes half of it.
**Risk.** A hang is detected later.
**Measured.** <project> backend: timeout 240 s against a p90 of 222 s, 25 timeouts on loaded days (X-2007).
<project> `static`: 180 s against a p90 of 176 s, 11 timeouts beside 27 real reds (X-2015).

### Wait on the condition, never on a fixed pause

**Cuts.** Flaky reds on a busy host, and time spent sleeping on a quiet one.
**Applies when.** Tests contain fixed sleeps or start allowances.
**Do.** Wait for the observable condition, with a far upper bound that only a real hang reaches.
**Risk.** None, once the bound is far.
**Measured.** cryptochart: fixed pauses of 40, 200 and 500 ms and a 1,500 ms start allowance failed on a
busy host (cryptochart `lessons/tests-wait-for-the-condition.md`); a pixel loop of one assertion per
pixel ran 3.9 minutes (cryptochart `lessons/browser-tests-of-the-chart.md`).

### Replace a real clock with a fake one

**Cuts.** Tests that wait out real time to see a timeout or a retry bound.
**Applies when.** A file's wall is mostly sleeping.
**Do.** Inject the clock; assert on the bound, not on elapsed seconds.
**Risk.** The fake must advance the way the real one does where the code reads it.
**Measured.** <project>: one loop-bound file takes 136 s, 21 % of its layer, aimed at under 5 s (X-2017).

## Heavy and flaky tests in their own place

### Put load-sensitive tests in the load-sensitive lane

**Cuts.** Whole layers re-run because one timing-bound test failed under load.
**Applies when.** The same tests go red together on loaded runs and pass alone.
**Do.** The lane and its automatic entry are <workshop-spec> rule 11; a group that fails together leaves too few
single rescues for the automatic entry, so append it by hand.
**Risk.** The lane runs one file at a time and lengthens the tail.
**Measured.** <project>: five browser specs went red 12 times each in 6 days; in 52 runs, 4–6 of them were
red at once (X-2014, X-2022). <project>: the coupling tests caused 30+ reds (X-2008).

## Adapters, then shadow, then deciding

### Declare an adapter, record in shadow, decide on evidence

**Cuts.** Running a whole layer for a change that reaches a few of its files.
**Applies when.** A runner can list its files and name the files a change reaches.
**Do.** The adapter protocol and samples (`patterns/verify-layer-adapter-protocol.md`); `selection:` and
`credit:` start at `shadow`, which only records (<workshop-spec> rule 8); `deciding` is SPEC-1030, with its
recorded reason.
**Risk.** Under `deciding` a skipped file's failure is not seen on that run and can reach `main`.
**Measured.** <project> frontend: shadow answered `unknown-path` on 193 of 220 runs, and only 5 would have
selected units (X-2009). <project>: whole-layer answers on about 70 % of runs (X-2019).

## The Stage-6 credit and what voids it

### Let the land take the card's own green run

**Cuts.** The land re-running the suite the card's self-check just ran.
**Applies when.** Lands repeat a full verify after a green `task test --run`.
**Do.** Nothing to declare: the credit is on by default; its five conditions are SPEC-0186 and
SPEC-0065 §Bound, and LIFECYCLE §Stage 8 (Tests) summarizes them.
**Risk.** None of its own; it voids itself when its conditions fail.
**Measured.** cryptochart: land verify fell from a 704 s median to 28–35 s (public issue #33,
cryptochart `docs/research/2026-10-04-verify-cost/trial-report.md`).

### Re-sign before the final run, not after it

**Cuts.** A second full self-check paid for a signature line.
**Applies when.** A card edits a signed spec or another file the run's tree includes after the run.
**Do.** Finish every edit and re-sign before `task commit`, then take the governed run once, at the Tests stage after audit-post (SPEC-1038 §Tests).
**Risk.** None.
**Measured.** cryptochart: one card paid a second 665 s run for two signature lines (cryptochart
`docs/research/2026-10-04-verify-cost/trial-report.md`).

### Sync with main, then take the final run

**Cuts.** A credit voided because `main` moved under the run.
**Applies when.** Lands record `main-moved` as the reason a credit was refused.
**Do.** `worktree sync` before the final run; an advance by inert bookkeeping keeps the credit
(SPEC-0186).
**Risk.** None.
**Measured.** cryptochart: of 211 lands, 60 lost the credit to `main-moved` at 474 verify-minutes, against
104 credited at 10 (public issue #98); <project>: 87 `main-moved` lands of about 280 s each (X-2003).

### Credit per layer, across runs and retries

**Cuts.** Re-running every layer after a red run or a failed land attempt.
**Applies when.** A fix touches one layer, yet the next run repeats all of them.
**Do.** The engine carries per-layer credit between runs and attempts; what still voids it (a timed-out
layer's report, a card-wide full layer) is <workshop-spec> and SPEC-0186.
**Risk.** None of its own.
**Measured.** cryptochart: three cards re-ran all 15 layers after a red, at 456, 330 and 466 s
(public issue #106); five land retries threw away about 40 min (public issue #107).

## Batching and card size

### Keep cards small and land them in batches

**Cuts.** A card's fixed cost — two audits, a full run, a land — paid for too little change.
**Applies when.** Cards take several Stage-6 runs, or one card's fixed cost exceeds its work.
**Do.** Cards of one to two hours, grouped by family; a project-side test-method spec like cryptochart's
holds the project's own rules.
**Risk.** A batch poisoned by one red member re-verifies the innocent ones.
**Measured.** cryptochart: a card-only work-batch land went from a 99 s mean to 14–21 s (cryptochart
`docs/research/2026-10-04-verify-cost/trial-report.md`). <project>: a card's fixed cost is about 10–15 min
(X-2012).

## The venue and the host

### Do not run heavy verifies beside each other on one host

**Cuts.** The slow-down and the reds of overlapping runs.
**Applies when.** Heavy runs start while two or more others are running.
**Do.** The verify-admission slots are SPEC-0132; a project with its own browser runs keeps one at a time
on its host; the venue's concurrent Stage-6 limit is a host setting.
**Risk.** Waiting for a slot instead of running.
**Measured.** cryptochart: runs alone took a 564 s median and runs at least 80 % overlapped 933 s, with 5
against 28 longest-layer reds (public issue #93); 10 of 12 runs with peak load1 at or above 100 went red,
against 2 of 38 below it (public issue #109); 43 % of heavy runs started beside two or more others
(public issue #102).

### Size the verify workers to the free cores

**Cuts.** Cores left idle by a fixed worker count.
**Applies when.** The suite's per-file sum ÷ workers is well above its longest file.
**Do.** The worker count is a host setting; the bound is the file sum over the workers, never under the
longest file.
**Risk.** Overcommitting a shared host.
**Measured.** Kernel: 14388 s of files over 13 workers bounds the run at about 18.4 min, with heavy verifies
in flight averaging 0.6–1.3 for 19 of 24 hours.

### Move the verify to a rented venue only when it pays

**Cuts.** Verify load on a small or shared development machine.
**Applies when.** The suite is long, lands are frequent, and running it slows everything else.
**Do.** `patterns/verify-venue-when-it-pays.md`; the venue contract is SPEC-1029.
**Risk.** Money per hour and one session's attention per working window.
**Measured.** Kernel: raising the box takes about a minute and refreshing its snapshot about seven
(`patterns/verify-venue-when-it-pays.md` §What it costs).

## What to move before a deploy, and how to check it

The rule for a declared pre-deploy class — what a land skips, what the deploy runs on the candidate,
which targets it gates — is SPEC-1051; this section is how a project reads its own numbers before it
moves anything. The numbers come from one saved view over the project's own journal:
`bin/yitc-v2 graph query verify-unit-cost [<layer:file...>] [--since <date>] [--until <date>]`
(SPEC-1051 rule 7). It prints, per unit and place, runs, median and total time, real and flaky
failures, the land-wait model and each pre-deploy class's catch record; it decides nothing. Every
reading below quotes the plan `plans/deferred-checks-a-project-moves-costly-checks-out-.md` (plan), by
its section.

### Read each file's cost and catches, with the common-mode caveat

**Cuts.** A move chosen from a feeling about which tests are slow or useless.
**Applies when.** Always first, before naming any candidate.
**Do.** Per file: runs in the window, median, week total, real vs flaky failures (a failure is real
when the same card's tree never passed the file afterwards). Read the run count beside every catch
count, and read a long window: a short quiet window lies.
**Risk.** Real vs flaky is a proxy. An identical flaky count on several files of one layer is one
common-mode layer failure, not per-file flakiness.
**Measured.** <project>, one week, 1,627 layer runs: four files took 1,676 min with 0 real catches
(plan §Model: what <project> would move, events.jsonl#ts=); four 258-run files
all showed «15 flaky» — one layer failure (same plan section, Caveats, events.jsonl#ts=).
cryptochart: 44 of 636 files «zero-catch» over 4 days did catch real defects over two weeks (plan
§Field check done, Placement per check; public issue #140).

### Model the land wait before promising faster lands

**Cuts.** A move sold as «faster lands» that only lowers load.
**Applies when.** Layers run side by side, so the land waits for the slowest one.
**Do.** Find which layer is slowest per run; recompute median, mean and p90 with the named files
removed (the view's land-wait model). A file outside the slowest layer moves load, not wait.
**Risk.** The model subtracts file time serially; a layer that runs files in parallel gains less.
**Measured.** <project>: removing the four candidates moved median 298 → 298 s, mean 327 → 315 s, p90
561 → 533 s; adding six zero-catch browser files gave median 236 s (−21 %), because the browser layer
was the slowest in 23 of 49 runs (plan §Model: what <project> would move, Browser files,
events.jsonl#ts=).

### Candidate signs and never-move signs

**Cuts.** Moving a check that catches real defects, or keeping one that only costs.
**Applies when.** A file is on the shortlist from the two readings above.
**Candidate.** Costly, runs on most cards, no real catch over a long window, and guards what only a
deploy brings to the host — compose loop ceilings, a sandbox secret cage, memory under load (plan
§Model: what <project> would move, the candidates table; cryptochart's heap test, 482.6 s, plan
§Cryptochart's working implementation).
**Never move.** A file with real catches on lands: <project>'s top browser files held most of the
week's real catches (3, 2, 4, 1 — plan §Model: what <project> would move); moving the whole browser
layer would have moved 21 real catches away (same section, Browser files).
**Measured.** <project>'s week (events.jsonl#ts=, events.jsonl#ts=);
cryptochart's heap test (events.jsonl#ts=, the plan's read of its implementation).

### Split a test file held in the lands by one failing or edited part

**Cuts.** A whole file kept in every land because one part of it failed or changed.
**Applies when.** The held block of `bin/yitc-v2 pre-deploy list` names a file with a large serial
share, its failure text naming one cheap test — a split candidate; a file held only by UNJUDGED
failures that name no test leaves the window by itself, and a split does not help it.
**Do.** Move the tests that never failed into a new file; the failing part keeps the original name,
so its failure history stays with it (SPEC-1051 rule 7 judges a file). Helpers both files use go to
one shared module, never copied. The weekly review files the split as a card (Lens C reading 5).
**Risk.** A new file starts with no history and lists only once it reaches the land threshold with a
full green run; shared setup is paid twice.
**Measured.** Kernel, 2026-10-26, 28 days / 100 lands: a failure kept 329 files in the lands (26 % of
serial time), a recent edit 72 files (5.5 %); of the 26 %, 13.5 % were files with one UNJUDGED failure
(owner trial events.jsonl#ts=). The pilot split of
test_publish_surface_boundary.py: the two catching tests 31 s of 144 s.

### Shadow before moving

**Cuts.** A move decided on one reading that a longer one would have overturned.
**Applies when.** A candidate set is named and the project is about to declare it.
**Do.** Keep the candidates running on lands for a window and record whether each would have been
caught only before the deploy — the shadow-then-decide shape <workshop-spec> uses for selection; then the
project decides, as an explicit act (SPEC-0178).
**Measured.** <project>'s six zero-catch browser files are a reasonable candidate set, to be decided by
<project> only after such a window (plan §Model: what <project> would move, Reading,
events.jsonl#ts=).

### Traps the three projects met

**Measured.** Each trap names the plan section its numbers come from; the readings are the owner
requests events.jsonl#ts= (<project>), events.jsonl#ts= (<project>
and cryptochart), events.jsonl#ts= (the stand run) and the field check of public
issue #161.

- **Run before the switch.** A class that runs after production is recreated leaves the bad build
  serving until rollback: <project>'s e2e gate, 97 deploys, 9 failed, 3 auto-rollbacks (plan §What
  <project> and cryptochart already moved out, <project>; across-projects item 3).
- **Per target.** cryptochart deployed acceptance 6 times without a run; <project>'s cage tests guard
  its sandbox target, not production (plan §What <project> and cryptochart already moved out,
  across-projects item 4; §Model: what <project> would move, Targets).
- **Rescue before red.** canvas-parity flakes in ~7 % of runs and would stop ~1 deploy in 14 without
  the land's rescue; cryptochart rescued 13 flakes in 10 green runs (plan §Model: what <project> would
  move, Flaky files in a gate; across-projects item 5).
- **Contention.** A red whose failures are timeouts beside other runs is CONTENDED, not red:
  cryptochart had one contention red (5 browser files, 34 runs beside it) and 9 of 13 runs with lands
  beside them; <project> 5 timeouts at host load 43–57 (plan §What <project> and cryptochart already
  moved out).
- **A new check meets its stand first.** A pre-deploy check never runs on lands, so its own fault
  first shows at a deploy: 3 cryptochart release blockers were runner-check faults, and 2 of 3
  rollbacks after a green run were the checks' own faults (plan §A new or changed pre-deploy check
  runs once on a stand at its card).
- **A release-only regression waits on main until the next release.** cryptochart's heap test caught
  two product regressions that sat on main until the release; `live-ticks.test.tsx` stayed unseen
  ~13 h through ~20 lands (plan §What <project> and cryptochart already moved out, across-projects
  item 2; §Field check done). Keep releases frequent.

## Tried and not taken

- **Rescuing a layer after its time bound** — withdrawn: it would weaken the signal the bound gives
  (public issue #93).
- **Heavy layers only at night or before deploy** — declined by that project's owner for about an hour
  saved over two plans (cryptochart `docs/research/2026-10-04-verify-cost/trial-report.md`).
- **Pre-flighting every batch candidate as insurance** — falsified at the observed poisoning rate
  (`patterns/land-gate-cost-separability.md` §6).
