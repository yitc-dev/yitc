---
name: consumer-suite-parallelization
class: technique
sourced_from: <project> (parallelize the backend-integration verify suite — 990 tests, 269s sequential quiet-box) + <project> X-0892 / (the layer-SPLIT transition — measured double-run bill + the coverage-hole replay) + <project> X-0931 / (the post-split window measured — the all-or-nothing savings shape and the attribution-replay method) + <project> X-0945 / X-0946 / (the probe-invocation-shape lever — the measured throwaway-vs-exec fleet asymmetry, and the decision NOT to derive a fleet threshold from it) + <project> 2026-08-25 (the one-week land window measured for the SECOND-round split question — the 63% bring-up floor and the co-fire rate that together decide how FINE a layer may be cut) + <project> X-1478 / / / / / / / (the verify-parallelism programme measured 2026-09-14..17 — land wall 405.7s -> 133s, the stack layer 437s -> 124s; the ordered adoption path in §Adopting concurrency is distilled from it)
applies_to: any consumer cutting its land-verify wall-clock — a layer that runs a large HERMETIC suite sequentially (§Parallelize), a monolithic layer being SPLIT into several subject-scoped layers (§Splitting a monolithic layer), or a layer whose cost is in HOW its probes invoke their container rather than in the probes themselves (§How your probes invoke their container) — any consumer about to MEASURE what a split bought it (§What shape of saving, §Before you trust a per-land attribution), and any consumer planning a SECOND round of splitting on an already-split layer (§How FINE to cut). Those levers stay consumer-scoped. ONLY §The WASTE lever applies more widely — any project reading an expensive verify unit for known waste — the kernel's own suite included (the T4 P7 probe's checklist home). §Adopting concurrency — the order of operations applies to any consumer adopting SPEC-0152 rule-16 CONCURRENCY (`independent_layers` + `layer_worker_shares`) — it orders the steps, it does not restate their rules.
---

# Consumer suite parallelization (pytest-xdist on a hermetic suite)

## Problem

One growing test layer comes to dominate every land's verify wall-clock (<project>: 990 backend
tests ≈ 269s quiet-box ≈ ~90% of each ~280s land, timeout already raised once 300→600s). The
sequential runtime grows with the suite forever; raising the timeout treats the symptom. Subject
scoping (SPEC-0152 rule 16 `subject_globs`) removes the layer from IRRELEVANT lands — this pattern
cuts the cost of the lands that DO run it. The two levers compose.

A THIRD lever comes first for a consumer that still has ONE monolithic layer: **split it**, so
subject scoping has something to address. That split has its own two traps, both measured, and they
are documented below — §Splitting a monolithic layer and §Before you retire the broad row. Sections 1
through 5 below are the PARALLELIZE lever; read the split sections if that is the lever you are on.

A FOURTH lever sits INSIDE a layer and is invisible to the other three: **how your probes invoke
their container**. One consumer measured roughly 47% of a 197s layer as pure container
create-and-destroy — not test work, and not something splitting or parallelizing that layer would
have removed. See §How your probes invoke their container. It is a question to answer, not a number
to hit.

**If you are on the split lever, read §What shape of saving the split actually buys BEFORE you plan
around it.** The savings are real and large, but for most cards they arrive all-or-nothing rather than
as the cheap partial runs most readers assume — whether a partial run is reachable at all depends on
how your own globs scope your tests and your specs — and that shape decides which realization
criterion you can even state. Reading it after you have designed your measurement is reading it too
late.

## Precondition — hermetic first, parallel second

Parallelize ONLY a layer that is already hermetic per-run (the SPEC-0152 rule-16 hermeticity
contract: unique-per-run container/port/db — see <project> `bin/verify-hermetic.sh`). Intra-run
test-level parallel safety is a SEPARATE claim the suite must earn: every worker needs its own
resource slice. For the DB mechanism fork (per-worker database vs schema vs transaction rollback)
see `patterns/test-isolation-strategies.md` — pick the least-churn mechanism that catches the bug
classes you care about.

## Solution shape

1. **Per-worker resource isolation** — key every external resource by the xdist worker id
   (`PYTEST_XDIST_WORKER`): per-worker DB name/schema on the SAME per-run ephemeral postgres, or a
   worker-keyed transaction scope. No shared mutable fixture across workers.
2. **Enable xdist** — `pytest -n auto` (or a fixed sane N for a known box) in the layer command;
   keep a single-run escape flag (env or CLI) so a debugging session can serialize.
3. **Prove the differential** — a deliberately-broken test MUST still turn the layer RED under
   `-n`; capture that run. A parallel runner that swallows failures is a gate-weakening, not a
   speedup (SPEC-0103: the suite CONTENT is untouched — only wall-clock changes).
4. **Measure before/after on the same box** — record both figures verbatim in the closure record
   (<project> target: 269s → ≤120s). A "feels faster" claim is not a probe.
5. **Update the layer timeout comment** — the declared per-layer `timeout:` was sized for the
   sequential run; re-derive it from the measured parallel figure + headroom, and say so in the
   carrier comment.

## When NOT to apply

- The suite is not hermetic per-run — fix that first (this pattern does not create isolation).
- Tests share mutable fixtures or are order-dependent — xdist reorders; flakes will present as
  gate noise, the worst failure mode for a land gate.
- The layer is not the wall-clock driver — measure first; parallelizing a 10s layer buys nothing
  and adds a moving part.
- CPU-starved runner boxes under verify-admission contention (SPEC-0132): `-n auto` on a loaded
  box can be SLOWER than sequential; prefer a fixed small N there.

## Live instance

<project> is the first application of this pattern (its numbers above); its closure record
carries the measured before/after and the differential broken-test run.

---

# The SPLIT lever — cutting one monolithic layer into several

## Splitting a monolithic layer — the transition bill (know it, then plan the retirement)

The split ask tells a consumer to cut its single executable verify layer into several layers along
its own test taxonomy, **cutting by SETUP COST, not by class name**. What that ask does NOT say —
and what you must hold anyway — is **retire the row you split**.

If you leave the original broad row declared while the new narrow layers also run, **every land pays
the same work twice** until the broad row is retired. The usual shape: the old entry-point script is
kept as a thin DRIVER whose last lines invoke the new per-layer scripts, so the default row runs all
of them and each layer row runs its own again.

**Measured (<project>, X-0892, 2026-08-14, idle host).** `scripts/verify.sh` was left as a 116-line
driver whose last three lines invoke the three new scripts. Per-layer, measured: static **133.3s** +
frontend-unit **10.4s** + stack **189.0s** = **332s duplicated**, against a real full-running land of
**728s** — the arithmetic closes on that duplicate plus the pinned re-run. It cost them a day.

**The posture is NOT "retire it immediately."** Keeping the broad row through the transition is the
RIGHT safety posture: it is exactly why a wrong or too-narrow glob on a new layer could not let a
diff through unverified. The rule is:

- **Know the bill.** From the moment you declare the new layers until you retire the broad row, your
  worst-case land cost is roughly the split work PLUS the broad row — not less than before, more.
- **Plan the retirement as part of the split**, with a date or a trigger (e.g. "after N lands with
  zero divergence between the broad row and the union"), not as a vague later.
- **Retire only through the check below.** Do not drop the row on the strength of the globs looking
  right — two audits passed <project>'s globs and they still had holes.

## How FINE to cut — the floor that splitting cannot divide

§Splitting a monolithic layer tells you to cut **by setup cost**. This is the other half of that
sentence: **the point at which cutting by setup cost stops paying.** Read it before you plan a
second round of splitting, because the first round's success does not predict the second's.

**Cut a layer finer ONLY when BOTH hold:**

1. the parts have **non-overlapping subject globs** — a given diff wakes one part, not several; and
2. there is **no shared expensive preparation** the parts would each re-pay.

**If either fails, more layers is the wrong instrument.** What you actually want is **selection
INSIDE the layer** — and that is a different, larger piece of work, because the kernel's skip
predicate operates on `verify.layers[].subject_globs` and cannot see below a layer. Selection inside
a layer needs its own skip oracle, which you would be building, not declaring.

**Measured — <project>, one week, 2026-08-25.** 179 lands. **65% of them ran no layer at all** (subject
scoping already doing its work), and the entire verify spend across the window was **3.4 hours**. Of
the executing lands, **45 of 63 ran more than one layer together**. The stack layer's median run was
**117s, of which 73s (63%) was bring-up before any test work**.

**The arithmetic that decides it.** Cutting that stack layer into 12 finer ones would pay **12 stack
bring-ups against the one it pays today**. The 63% floor is not divisible by splitting, because every
part re-pays it in full — so the finer cut LOSES there, and loses by more the finer you cut. This is
the same quantity §Splitting a monolithic layer calls "setup cost", met from the other direction: it
is what you are cutting BY at the first split, and what you run OUT of at the next one.

**A high co-fire rate is evidence AGAINST a finer cut, not for it.** It is easy to read "the layers
run together most of the time" as "they are entangled, cut them apart properly". It means the
opposite: co-firing parts re-pay the shared floor on **every** land, so co-firing is the shape in
which splitting is most expensive and least effective. Read your own co-fire rate before designing a
second cut — condition 1 above is exactly what a high rate falsifies.

**Scope bound.** These are two conditions to check against your own numbers, not a threshold and not
a check. There is no fleet-wide fraction at which a cut becomes wrong — §Why there is NO fleet-wide
number here applies here unchanged, and for the same reason.

## Before you retire the broad row — replay the coverage check

When the broad row finally goes, the union of the narrow replacements **may not cover what the broad
row covered**. The gap is invisible until the row is gone: after that, a diff touching an uncovered
path simply runs nothing and the land is green for free.

**The check needs no new machinery — it is a replay of the kernel's own skip predicate.**

1. Take the **RETIRING row's** globs (what the broad layer claimed as its subject).
2. Replay `_subject_globs_would_skip` (`bin/lib/worktree.py`) over each of those globs — as the
   candidate diff path — against the **union of the replacement layers'** `subject_globs`.
3. **Pass condition: at least one replacement layer RUNS for each.** Any glob for which every
   replacement would skip is a coverage hole; fix the replacements' globs before flipping.

**It finds real holes.** Run before flipping on <project>'s own set, it found TWO — `<project>.pin`
(a pinned-library bump would have run NOTHING) and `scripts/**` (an ordinary new script would have run
NOTHING) — **after two audits had already passed those same globs**. Reviewers read globs for
plausibility; only the replay reads them for coverage.

**Scope bound:** this is a documented MANUAL procedure, deliberately not a verb. A check verb for it
would need its own card and its own evidence of recurrence (CHARTER §Principle 1 filter 4).

## What shape of saving the split actually buys — all-or-nothing, unless your globs scope the test and the spec

Read this before you plan around the split's payoff. **The saving is large. It is simply not the
shape most readers assume.** A reader arriving at subject scoping expects "cheap partial runs" — a
land that runs two of five layers and skips three. For a consumer whose build rule ships a behaviour
change together with its TEST and its SPEC in ONE change, **an ordinary substantive card produces a
partial run only when BOTH companions are scoped to the layer the change belongs to.** Where either
one reaches every layer, plan for all-or-nothing: either every skip is cancelled and you pay a full
run, or the whole diff is disjoint from every layer and you pay ~nothing.

**The cause has two independent legs — either one alone cancels every skip** (<project> X-0931,
accepted by the kernel):

- **The test leg.** The companion test lands under `tests/`, which hits the kernel's HARDCODED
  verify-infra floor — `_SUBJECT_VERIFY_INFRA_GLOBS = ("bin/**", "tests/**", "yitc-ops.yaml")` in
  `bin/lib/worktree.py`. A path matching the floor takes the SPEC-0077 supremacy edge: full run, no
  layer skipped, regardless of any `subject_globs` you declared. Two members are conditional (the
  rule is SPEC-0152 rule 16, `bin/yitc-v2 graph query SPEC-0152`): a `yitc-ops.yaml` change that
  leaves the carrier's verification sections equal is judged by your `subject_globs` like any other
  path; and a changed test file forces ONLY the layers that own it when that ownership is PROVEN —
  it is one of the test files you DECLARE (`tests.classes[].globs`), at least one layer's
  `subject_globs` claim it, and at least one layer's do not. So this leg cancels every skip only for
  a test path that is NOT such an owned declared test file: one no declared class glob names (which
  includes every project that declares no test-file globs), one no layer claims, one every scoped
  layer claims, one you listed under `verify.infra_globs`, or one a layer's `command:` names.
- **The spec leg.** The companion spec lands under `specs/`, which hits whatever layers THAT consumer
  declared `specs/**` on. This leg is the consumer's own glob breadth, not the kernel's floor, and
  nothing in the kernel changes it.

So a card carrying an unowned test, or a spec every layer globs, cannot be partial even in principle;
a card whose test is an owned declared test AND whose spec glob is scoped to the same layer runs
that layer and skips the rest on the candidate leg.

**The figures below were measured BEFORE the test leg became ownership-aware, when ANY
`tests/` touch cancelled every skip.** They are kept as measured — they are the history that earned
the rule — and are not a description of current behaviour for a consumer that declares its test
files and scopes them per layer.

**Measured over <project>'s post-split window** (X-0931, 45 lands, re-measured 2026-08-16): of the 10
full-run lands, **6 touch the kernel floor** (all 6 via `tests/**`, one also `yitc-ops.yaml`) and the
other **4 touch no floor path at all** — 3 frontend cards whose only reach into their expensive stack
layer is a `specs/**` touch, plus 1 touching a verify script all three layers glob. <project> filed
that second half against THEMSELVES as their own glob breadth; it is not a kernel ask. Both legs are
real, and a consumer that narrowed only its own `specs/**` globs would still have the test leg.

**And the saving is a win, reported as one:** 73% of verify wall-clock removed over the window —
**5762s actual against a 21239s all-ran counterfactual**, whole-window median **0.8s** against the
**36.6s** pre-split median. All-or-nothing is not a degraded outcome; 30 of those 45 lands (67%) were
all-skip. What you buy is a large majority of near-free lands, not a cheaper full run.

**Scope bound, so the claim stays falsifiable:** the same window does contain **5 partial runs** out
of 45. Partial runs exist in the mechanism — in that window they were reachable only for lands that
were not ordinary substantive cards. Since an ordinary card reaches one too, but only under
the two conditions above (an owned declared test, a layer-scoped spec glob). **The consequence to act
on: do not design your rollout, your budget, or your success criterion around partial runs until you
have replayed your own globs and seen that your cards actually meet both conditions.**

### The realization criterion that follows

**Do NOT hand a consumer "every tier observed running ALONE at least once" as a realization gate.**
For a consumer whose tests or specs reach every layer it is **unsatisfiable without a deliberate
violation of that consumer's own build discipline**: selecting one expensive layer alone requires
shipping a behaviour change WITHOUT its test and WITHOUT its spec. It is reachable only where the
companion test is an owned declared test file and the companion spec's glob is scoped to the same
layer (the two conditions of the section above) — a property of that consumer's globs, which the
gate would then be measuring instead of the split. This is worth stating out loud because **a
consumer derived this criterion independently and carried it for two days** before retiring it
(X-0931, when a `tests/` touch still forced a full run regardless) — it is a trap a careful reader
walks into unaided, not one that has to be handed over.

**The reachable replacement, which the kernel ALREADY asks for, is FORWARD SAME-COMMIT RE-RUNS.** It
is what the unsatisfiable version was reaching for, and the only route that can supply it: X-0871
asked for ≥20 recorded would-skip decisions and then a re-run of a sample against the SAME commit,
and the card that owns it today — ** AC3** — says an OFFLINE REPLAY of the engine predicate
over historical lands plus a clean sample re-run, **zero false skips**. State the replacement beside
the rejection whenever you send either, so a reader cannot take away only the half that blocks them.

### Noted: a floor touch is TWO effects, not one

Purely informational sizing — but a consumer costing a `tests/` touch should know it can pay twice.
A floor touch (a) cancels every skip — for a test path, only when it is not an owned declared test
file, as above — AND (b) adds the **SPEC-0077** pinned last-green re-run on top, wherever the project
runs that leg. Effect (b) is NOT conditional: the pinned trigger fires on ANY `tests/` change, owned
or not, and that leg runs every layer. Measured (<project> X-0931, before): a floor-touching
full run at **557s median** against **316s** for a non-floor full run — about **241s per land**,
roughly **1450s of their 5762s window**. Size a `tests/` touch as two effects, not one.

## Before you trust a per-land attribution — replay the engine's own predicate

Any claim of the form "this land ran full BECAUSE of that card" is an ATTRIBUTION, and an attribution
is a reconstruction of what the engine saw. Reconstruct it wrong and you will manufacture findings
that are not there. Before drawing ANY conclusion from per-land numbers:

1. **Reconstruct `base_ref` as the MAIN-SIDE PARENT of the last merge-of-main in the branch's
   first-parent chain.** Do NOT use the previous land's ship commit (the `land_completed`
   `data.sha`) — that is the BRANCH ship commit, not the main tip the engine passes to
   `_merged_tree_delta_paths` as `base_ref`, so the range sweeps in unrelated concurrent branches and
   **MANUFACTURES contamination that never existed**.
2. **Replay the engine's own skip predicate over the reconstructed diffs** — `_subject_globs_would_skip`
   (`bin/lib/worktree.py`) plus the `_SUBJECT_VERIFY_INFRA_GLOBS` supremacy edge — including the two
   answers that decide whether a floor touch takes that edge at all, each computed by the ENGINE's own
   function over the carrier at the two revisions (SPEC-0152 rule 16): for a diff that lists
   `yitc-ops.yaml`, the section comparison (`_ops_carrier_freed_paths`); for a diff that lists a path
   under `tests/`, the ownership proof (`_owned_test_freed_paths`). Hand the UNION of the two freed
   sets to the edge, as the land does. A replay that omits either one reconstructs a full run the
   engine did not take, and cannot reach the 100% of step 3. Not a re-derivation of what the globs
   "should" mean: the predicate the engine actually ran.
3. **Pass condition: 100% reproduction of the recorded per-layer decisions.** Every layer, every land
   in the window. <project> reproduces **45/45**. Below 100%, you have not earned any conclusion yet —
   fix the reconstruction first.

> **An attribution that cannot reproduce the journal is measuring a different range than the engine
> did.** — <project>, X-0931

**The incident that earns the rule.** <project> reported to the kernel that of 10 full-run lands, **7
had a range attributable to a single card and 3 were contaminated** by concurrent lands, with a named
6/4 boundary under a strict branch rule. They then applied the method above and **corrected it
unprompted: the real figure is 10 attributable, 0 contaminated** — the entire contamination was the
`base_ref` error in step 1, and the disputed land turned out to be single-card and floor-free, making
the flagged boundary moot rather than resolved. The kernel had not used the 7/3 figure, so nothing
downstream unwound. The correction is recorded here because it is what makes the method credible: the
wrong number was plausible, survived being sent, and was caught only by the replay.

## When you send this ask

The split ask sent to <project> (X-0871) carried neither of the two facts above, and that omission is
what cost them the day. **Any future layer-split rollout ask MUST carry these two sentences**, cited
from here rather than re-derived:

> **Retire the row you split — and until you do, every land pays the work twice.** Keeping the broad
> row through the transition is the correct safety posture, but it is a DOUBLED bill, not a free one
> (measured: 332s of duplicated layer work against a 728s land), so plan the retirement as part of
> the split.
>
> **Before you drop the broad row, replay `_subject_globs_would_skip` over that row's globs against
> the union of the replacements, and require that at least one layer RUNS for each.** Run on
> <project>'s own set this found two real coverage holes that two audits had already passed.
>
> **What the split buys you is mostly ALL-OR-NOTHING savings, not cheap partial runs — and that is
> the expected shape, not a disappointment.** If your build rule ships a change with its TEST and its
> SPEC, an ordinary substantive card runs partially only when BOTH are scoped to the layer the change
> belongs to: the test must be one of the test files you declare (`tests.classes[].globs`) that some
> layers' `subject_globs` claim and others do not — any other `tests/` path hits the kernel's
> `tests/**` floor — and the spec must land under a glob you did not give to every layer. Either
> companion reaching every layer cancels every skip (measured on <project> before the test leg became
> ownership-aware: 73% of verify wall removed anyway — 5762s against a 21239s all-ran
> counterfactual). **So do not adopt "every tier observed running ALONE at least once" as your
> realization gate — unless your globs meet both conditions it is unsatisfiable without violating
> your own build discipline, and where they do it measures your globs, not the split.** The reachable
> criterion is forward SAME-COMMIT re-runs (X-0871; AC3), and before you trust any per-land
> attribution, replay the engine's predicate — with BOTH of its freed answers, the carrier section
> comparison and the test-ownership proof — over a `base_ref` reconstructed as the main-side parent
> of the last merge-of-main and require 100% reproduction of the recorded decisions.

---

# The SHAPE lever — how your probes invoke their container

## How your probes invoke their container

The other three levers move work between lands or across CPUs. This one is about a cost that is
inside a single layer and survives all of them: **whether each probe brings up its own container, or
runs inside one the layer brought up once.**

**Two shapes, and BOTH are legitimate.** This section names the choice; it does not rank them.

- **THROWAWAY** — each probe runs in its own container (`docker compose run --rm …`). Maximum
  isolation: nothing a probe does can reach the next one. You pay a container bring-up per probe.
- **EXEC** — the layer brings a stack up ONCE and each probe runs inside it (`docker compose exec …`).
  One bring-up for the whole layer. The probes now share a process and a filesystem, so they must not
  fight over shared state — that sharing is a real constraint, not a formality.

**A probe that genuinely needs its own process is legitimately throwaway.** The consumer that
measured this kept several of theirs for exactly that reason, with a written reason on each. The
failure being described here is not "throwaway is wrong" — it is that the choice was never made.

## The measurement — one project, one counter-example, and that is the whole evidence base

**Measured 2026-08-16 (<project> X-0945 / X-0946), counting compose invocations in each verify path:**

| project | throwaway (`run --rm`) | exec |
|---|---|---|
| <project> | 55 | 10 |
| <project> | 0 | 70 |
| <project> | 2 | 15 |

For <project> that shape cost about **92s of a 197s layer — roughly 47%** (an empty throwaway
container measured 1.8s steady-state; a real cheap probe measured 3.43s, so more than half of each
probe was create-and-destroy). **<project> does the same KIND of work for zero container churn.**

**Nobody was wrong on purpose.** Two projects arrived at opposite shapes independently, and nothing
in the methodology, the onboarding runbook, or any check ever put the question in front of them. A
project that writes its first probe as `compose run --rm` writes its fifty-fifth the same way,
because each one individually looks fine.

## Why there is NO fleet-wide number here, and why there will not be one

Read this before the method below, because it governs how the numbers above may be used.

**This section states no target, no ratio, and no threshold — deliberately.** The evidence is ONE
measured project plus ONE counter-example. Whether 55 throwaway containers is bad in some OTHER
project depends on that project's probe shape and isolation needs, which are exactly the things the
measurement did not look at. A number derived from a single reading would fire on projects nobody
examined, and being told "you are over the line" by a line drawn somewhere else teaches a reader to
ignore the line rather than to look at their layer.

**That objection was raised by the REPORTER against their own ask** (X-0946), and it was accepted in
full rather than answered around. It is recorded here in their terms because a reader who finds only
the 47% figure and not this paragraph has taken away the wrong half.

**It is also the standing answer in this repo, not a one-off judgement.** CHARTER §Principle 2 ruled
the same way on the handbook's byte axis: report the outcome and the trajectory, decree **no second
cap and no token number**, because a decreed number is voluntaristic — what decides is a placement
test, never a threshold. SPEC-0127 §5 says it again for the worker-seed total: *a total has no
reader-facing threshold, only a trajectory.* This lever is the same shape, so it gets the same
treatment.

**The consequence, stated plainly: the table above is evidence that the QUESTION is worth asking. It
is not a target to move toward.** A project that reads it, looks at its own layer, and concludes its
throwaway probes are correct has given a complete answer.

## How to tell which shape YOU have

Two steps, and the bound between them matters more than either.

1. **Find the expensive LAYER from your own journal.** Since, each verify layer that executes
   records its own `duration_ms`, folded into `land_completed.verify_metrics.per_layer_durations`
   (`{layers: [{layer, duration_ms}], attributed_ms}`) — report-only, nothing reads it to decide
   anything. The unattributed remainder is `verify_wall_ms - attributed_ms` (engine sweep, admission
   wait, setup), so the total decomposes rather than being replaced.

   > **Per-LAYER is not per-PHASE, and this step does NOT show you container churn.** The churn is
   > INSIDE a layer; the kernel runs a project-owned script and does not know its phases. What this
   > buys you is that you now know WHICH layer to open — before it, <project> obtained every number
   > above by hand-instrumenting a run. Do not read a slow layer as a diagnosis.

2. **Count that layer's own invocations.** In the layer's script(s): `grep -c 'compose run --rm'`
   against `grep -c 'compose exec'`. Then calibrate the unit on your own box — time an EMPTY
   throwaway container (`compose run --rm <svc> true`) and multiply. <project>'s unit was 1.8s; yours
   is yours. The arithmetic is then entirely in your own numbers, which is the point.

If the count is high and the reasons are not written down anywhere, you have found an accident
rather than a decision — and that, not the count, is the thing worth fixing.

## What was considered instead, and why this is prose

The fleet-wide question X-0946 asked — *should something be fleet-wide, and if so in what form* —
was decided as **PROSE in this catalog: no check, no threshold, no new mechanism**.
Rejected, each for a reason a later reader can weigh:

- **A kernel CHECK counting throwaway invocations.** The kernel cannot see probe shape without
  reading another project's scripts — territory. And a check must return a verdict, which
  means a number no one has the evidence for.
- **A fleet-wide THRESHOLD, or a report-only metric carrying one.** The section above.
- **A recurring INSPECTION THEME.** It converts a single measurement into a standing per-cycle
  obligation on every project, and fires on shapes nobody looked at — the threshold objection wearing
  a cadence. It also removes nothing (CHARTER §Principle 1 filter 3).
  *Not contradicted by the T4 P7 probe.* P7 carries no count and no line: it selects the
  units a project's OWN measurements already say are most expensive, or stepped, and READS them.
  It adds no theme and rides T4's existing cadence. What it looks for is §The WASTE lever below.
- **A `lessons/` entry.** A lesson is per-repo and NON-TRAVELING by definition (SPEC-0090), so a
  lesson in the kernel repo reaches nobody in the fleet — which is the one thing this ask needed. The
  throwaway-to-exec conversion as it applies to a specific project's scripts IS that project's lesson,
  and theirs to write.
- **A second born-scaffold comment.** Already shipped: put this choice into the born
  `verify:` section of a project's `yitc-ops.yaml` (carrier SPEC-0093), so a project meets it while
  writing its FIRST layer. Restating it here would be a second home for one concern (CHARTER
  §Principle 5) — hence the pointer in §See also, not a copy.

**And the honest limit, since the ask was specifically about projects whose shape is already set.**
The born comment reaches a project writing its first layer; it never fires again. This section
reaches a project that goes LOOKING at its verify cost — plus, for a project named in this file's
`sourced_from`, the report-only SPEC-0119 rule-22 line that surfaces an own-evidence pattern it never
cited (measured reach: 8 patterns across 5 projects, not all nine). **Nothing here reaches a project
that never examines its verify cost at all.** The only form that would is a pushed check carrying a
number — the thing being rejected above. That gap is accepted knowingly, not overlooked; what makes
it acceptable is that step 1 above turned "go looking" from a hand-instrumented run into reading your
own journal.

## Adopting concurrency — the order of operations

**Applies to any consumer adopting SPEC-0152 rule-16 concurrency** (`independent_layers` +
`layer_worker_shares`). Five steps, in this order. Each is a CUE plus a POINTER to the rule's own
home — nothing normative is restated here; the only content carried is <project>'s measured evidence,
which lives nowhere else (X-1478 / / -).

**1. Instrument first — and persist the reading where a later reader can re-open it.** Before any
declaration, measure what the layers actually cost, and write the reading to a DURABLE path, never a
temp file written only on success. Evidence: <project>'s first whole per-chunk reading showed a lane
packer planning from a cost map off by 23x on one chunk — and that reading was lost within half an
hour to exactly such a temp file. No pointer needed: this step IS the incident.

**2. Rebuild the cost map from measurement — never auto-tune it.** The map is a RECORDED artifact
with a stated write policy, not a number recomputed live from the last run's guesswork. Read what
that policy is at its home — SPEC-0132 §6 and `bin/yitc-v2 verify-durations --help` (`--rebuild` is
the kernel precedent); this section asserts nothing about which runs may write it. Evidence:
<project>'s rebuild moved 45 chunks / 137.4s declared to 58 / 476.1s.

**3. Trial serial-then-concurrent on the REAL host, across repeated lands.** The conflict-domain
contract and its closed class set live in SPEC-1007 — read it there. What SPEC-1007 does NOT cover,
and this step exists for: **host-accumulating** resources (docker networks, volumes, address pools)
are a CAPACITY axis OUTSIDE its seven pairwise classes. They accumulate across lands instead of
conflicting between a pair, so a clone-based pairwise trial cannot see them. Evidence: the kernel's
clone trial of <project>'s four layers found ZERO conflicts, and the first two real concurrent lands
aborted on an exhausted docker address pool (nine networks leaked in a day against a ~31-network
default pool). Route the preflight for such a resource to the project's OWN layer `prep:`
(pointer: SPEC-0152 rule 16) — the kernel stays docker-free.

**4. Only then declare `independent_layers` + `layer_worker_shares` — and ship the reader of the
share.** The fields' shape and the kernel/project division of responsibility are governed by
SPEC-0152 rule 16; this step prescribes none of it. The `independent_layers` declaration is YOUR
project's own risk judgement — what that standing is, that an `owns:` declaration is not required
for it, and the resource classes to walk over each pair before you declare are SPEC-1007 rules 1
and 2 — read them there. Its own content is one measured fact:
<project>'s audit-pre REDDED a share that nothing read, and that RED was right. And one report
of what <project>'s own acceptance asked for — offered as a method others MAY copy, not a requirement
— per-layer durations summing ABOVE the wall (272.1s of layers inside a 133.1s wall, 2.04x), because
a shorter wall alone is also what you get when the longest layer is merely cut.

**5. LAST, re-measure every layer timeout under the new regime before trusting it.** What the
timeout tuple is, what moves it, and what a re-measurement owes are all governed by SPEC-0208
Rule 1 + Rule 5 — read them there. This step restates none of it and exists only to put the
re-measurement LAST. Evidence: <project> reached this step holding a serial-era
re-margin ask whose direction was the opposite of what the new regime measured.

**The order is not a preference.** You cannot set fractions before you know real costs, and you
cannot margin a timeout before the regime is final.

# The WASTE lever — reading an expensive unit for known waste

**Applies to any project, the kernel's own suite included** (the other levers above stay
consumer-scoped). The first three levers move work between lands, across CPUs, or out of container
churn. This one reads a slow unit and asks what it spends its time ON. The premise is plain: tests
are usually written sub-optimally at first, and the large wins found so far were found by a person
who went looking. The T4 P7 inspection probe points HERE; this section is the only place the list is
written down.

## Select by measurement — never read everything

1. **The most expensive units.** Kernel: the per-file table `tests/verify-durations.json` (values in
   `unit_ms`). A consumer has no per-file table: use `land_completed.verify_metrics.per_layer_durations`
   and open the most expensive LAYER.
2. **A STEP, bisected to the card that landed it.** This found the three largest <project> items: stack
   +62s at, a static self-test 0.5s→13.0s at, a touch-target test 4.8s→11.02s at.
   Kernel: the SPEC-0119 rule-19 slow-tail growth line. Consumer: the per-layer series over time.
3. **Rule out host load before you call it a step.** If EVERY layer moves together and no commit
   touched the verify path in the window, it is load, not a card.

## The checklist — largest measured cost first

Measured in <project>'s read-only audits (2026-09-14, routed as X-1410) unless marked.

1. **A test that really waits out its own retry or backoff schedule** (~62s). Inject the clock.
2. **A fixed sleep used as synchronization** instead of a readiness signal (~30s).
3. **Building a whole image or container for seconds of work, then deleting it** (~17-22s), often
   with a per-run name that defeats the cache.
4. **A self-test that runs the real script end to end** and regressed when the script stopped failing
   fast (0.5s→13s).
5. **Re-parsing the same large input on every call**, including quadratic scans (14s of an 18.7s run;
   11s).
6. **Library default poll intervals on teardown** (`serve_forever`'s 0.5s across 17 tests).
7. **Dependency reinstall with no cache** in a throwaway container.
8. **Per-item CLI loops against docker or a database** (3 `docker inspect` per host container).
9. **Independent containers, phases or suites run serially**, and the same deterministic work done
   twice per run (kernel:).
10. **Grace loops that always run to their deadline**, and anything that can loop or hang.
11. **Starting containers that are only inspected.**
12. **Stale scheduler cost estimates** because the measurement is written, then deleted.
13. **Unbounded corpus reads and disk/IO churn** (kernel:) — HYPOTHESIS until a
    project measures the share.
14. **Repeated process or interpreter startup — rank LAST.** Real but usually small: <project>
    measured ~0.3s per pytest call (20 calls ≈ 5-6s).

**Already fixed — check for a REGRESSION, not a new finding:** container create-and-destroy per probe
(<project>, 250.7s→159.9s, guarded by its own check script; §How your probes invoke their
container). **Hygiene, no wall-clock:** run artefacts never pruned (917MB under /tmp).

## The reporting rule — every finding, no exceptions

- **`file:line`** for the waste.
- **A MEASURED number with the source a reader can re-open**, OR an explicit **HYPOTHESIS** label.
  Mixing the two up inflates a total. So a savings sum is an order of magnitude, not a promise.
- **Is it DELIBERATE isolation for correctness?** A hold for determinism, or a throwaway container a
  probe really needs, is not waste. Keep the property and change the instrument (e.g. a release file
  instead of a timer). A speed-up that weakens a gate is a regression, not a finding (SPEC-0103).
- **Route it.** A finding about one project's code is never pattern content: send it to that project
  (`cross request`, citing an existing request rather than duplicating it). A kernel finding becomes a
  kernel card or a `followup`. Name the id in the inspection record.

## See also

- **SPEC-0093 verify section** (`bin/yitc-v2 graph query SPEC-0093`) / `graph/born-ops.yaml` — the
  DECLARATION-TIME sibling of §How your probes invoke their container : the same choice,
  put in front of a project while it writes its first verify layer. That text is homed there.
- (`bin/yitc-v2 graph query `) — the per-layer duration record step 1 above reads,
  and its report-only fence.
- **SPEC-0152 rule 16** (`bin/yitc-v2 graph query SPEC-0152`) — the `verify.layers[]` /
  `subject_globs:` schema contract these procedures operate on. The kernel grades stance and
  structural shape there, never glob COVERAGE — which is why the replay above is yours to run.
- **SPEC-0077** (`bin/yitc-v2 graph query SPEC-0077`) — "Pinned last-green verify for
  verify-path-touching lands"; the supremacy edge that makes a floor touch cancel every skip — except
  the two conditional members SPEC-0152 rule 16 homes (a section-equal carrier change; an owned
  declared test file) — and the pinned re-run that is its SECOND, unconditional effect (§Noted: a
  floor touch is TWO effects).
- ** AC3** (`bin/yitc-v2 graph query `) and the ask it answers, **X-0871** — the
  kernel's ACTUAL realization criterion (offline replay over historical would-skip decisions plus a
  clean same-commit sample re-run, zero false skips), which is the reachable replacement above.
- **`patterns/hermetic-in-time-suite-latency-triage.md`** — the composing lever when a layer is slow
  for a hidden reason rather than a big one.
