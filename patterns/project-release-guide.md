---
name: project-release-guide
class: reference
sourced_from: plan deferred-checks-a-project-moves-costly-checks-out- (§Analysis aid item 3, owner request to give projects a reference of what they can do and must set up themselves; public issues #140 and #161). Every worked example and number below is quoted from that plan's read-only readings of cryptochart, <project> and <project> (2026-10-10..22), except Part C, whose sources it names: cryptochart's public issue #201 and <project>'s stand note (cross:X-2082, 2026-10-26/27).
applies_to: a project that deploys from its land queue and wants to know which part of its release the kernel runs and which part it must build — release batching, the stand-then-production order, live checks on the served site, rollback, re-running one step after a flake.
cites:
  - SPEC-1051
  - <workshop-spec>
  - SPEC-1047
  - SPEC-0142
  - SPEC-0109
  - <workshop-spec>
  - SPEC-0094
  - SPEC-0097
  - SPEC-0015
  - SPEC-1030
  - SPEC-1054
  - SPEC-0205
  - SPEC-0065
---

# Project-side release guide — what the kernel runs before a deploy, and what your project sets up itself

> **Plainly.** A release is more than one `deploy` call: someone chooses which landed cards go out
> together, deploys them to a stand before production, checks the served site, and rolls back when a
> check goes red. The kernel runs one part of that — the full check of the exact revision before the
> deploy command. The rest is each project's own, and three projects have already built it in
> different ways. This page shows what each of them did and what it cost. It adds no rule and no gate
> reads it: where a kernel part is named, its spec is the rule and wins on any difference.

## Problem

A project that lets its lands run less (SPEC-1030 deciding selection, or checks moved out of lands)
needs a full check somewhere before its users meet the build — and a release order around it. Without
a reference each project rebuilds that order from scratch, and meets the same traps the others
already measured: a stand that checked old code and stayed green, a batch too large to tell which
card broke it, a live check whose own fault rolled back a good build, a whole release re-run because
one step flaked.

## Part A — what the kernel provides

Four parts, each specified in **SPEC-1051**. The rules are there and only there; this list says what
each part is for.

- **The pre-deploy run inside the deploy** — a full check of the exact revision a gated deploy ships,
  before its command (SPEC-1051 rules 3-4).
- **The per-target gate** — the project names which deploy targets, stands included, need that run
  (SPEC-1051 rules 1 and 5).
- **The stand run of a new or changed check** — such a check meets the project's stand once after its
  card lands, before a production deploy depends on it: its run inside the pre-deploy run of a stand
  deploy that completed on the landed revision (SPEC-1051 rule 6). It shows the check itself works. It
  is not a check of the build the stand serves — a pre-deploy check runs on a fresh checkout of the
  candidate; checking the served build is your project's post-deploy checks (B3).
- **The analysis view** — reads the project's own journal to show which checks could leave the lands
  and what that changes (SPEC-1051 rule 7; how to read it: `patterns/verify-cost-playbook.md`).

## Part B — what your project sets up itself

SPEC-1051 §8 names these five as the project's own. For each: what to decide, how the three projects
did it, and the trap they measured.

### B1. Release batching — how many landed cards go out in one deploy

- **Decide:** how many cards a release carries, and how you find the one that broke a red release.
- **cryptochart:** a release of about 10 cards (its release 6799cf10f, landed 2026-10-21, carried 10
  and reached done on its third run).
- **<project>:** about 7 cards a deploy (2026-10-16: 64 lands, 9 deploys).
- **Trap — a large batch is hard to attribute.** A red run on a big batch names many candidate cards;
  cryptochart's red release surfaced 5 blockers over 5 hours, one per round. Batches formed on a main
  that was already red carried the red into the release (public issue #118). Keep batches small enough
  that the kernel's «cards since the last passed run» list is short, and do not cut a batch on a red
  main.
- **Trap — a check that runs only before a deploy waits for the next release.** cryptochart's
  release-only test `live-ticks.test.tsx` broke at a card landed 2026-10-21 and stayed unseen about
  13 hours through about 20 lands, until the release run caught it. Infrequent releases stretch that
  window.

### B2. The stand-then-production order

- **Decide:** whether a release goes to a stand first, which target that is, and what must pass there
  before production.
- **cryptochart:** one command, one lock — full verify of the release revision → acceptance deploy →
  acceptance runner install → acceptance full run and served run → production deploy → production
  runner → production full run. Each step writes its own row, so a stopped release resumes from the
  step that stopped it.
- **<project>:** a `sandbox` target (`production: false`); its sandbox cage tests guard exactly that
  target and run on lands today (owner soak decision events.jsonl#ts=). Name
  `sandbox` as a gated target beside production (Part A) only if those cage files move off lands into
  a pre-deploy class.
- **Trap — a stand that checks old code stays green.** On the reporting project a staging stand
  checked 4-day-old code and stayed green (public issue #140). Deploy the release revision to the
  stand; never trust a stand whose served build you did not just put there.
- **Trap — a stand target deployed without the check.** cryptochart deployed its acceptance target 6
  times without a full run. Name every target a check guards, not only production.
- **Option — one run for both targets of one candidate.** By default the stand deploy and the
  production deploy of one candidate each run the whole pre-deploy run (about 31 min each on the
  reporting project). Declaring `reuse_run: {reason: <why>}` on every pre-deploy class guarding
  production lets its deploy stand on the stand deploy's passed, completed run of the same candidate
  under the same declaration, within your `pre_deploy_reuse_max_age_minutes` threshold — the bounds
  are SPEC-1051 rule 3. Its cost: production ships on a run up to that age old, so a failure only a
  second run would show (a flaky or host-dependent check) goes unseen; record in the reason why your
  project accepts that.

### B3. Live checks on the served site

- **Decide, declare and configure — these checks are your project's own.** The kernel brings no
  check of its own against the build your stand or production serves; its stand run (Part A) only
  shows that a pre-deploy check works. Your project decides what it checks on the served site, before
  or after users meet it; declares and configures each check where it runs — a deploy-time
  `tests.classes[]` entry, your deploy script; runs a new or changed check once on its stand before
  production trusts it; and names who owns each check's own correctness.
- **<project>:** a Playwright e2e suite (about 100 tests, about 61 s a deploy, 15 of its specs need
  production data) and a live login gate, declared as `moment: deploy` classes. In 2026-10-01..16 the
  deploy gate caught a layout change that broke pixel baselines and a production data defect (a
  warehouse rename); lands could see neither.
- **cryptochart:** a production runner installed and run after each production deploy; acceptance
  gets its own served run first (B2).
- **<project>:** health, authenticated and browser row-press probes on the served app in its deploy
  script.
- **Trap — the check itself is the fault.** cryptochart: 3 of 10 production deploys after a green
  full run were rolled back on live checks — 2 of the 3 were faults of the checks, 1 a real page
  defect no test covered. 3 release blockers were runner checks tested only on stand-ins. A new or
  changed live check meets a stand first — the same habit Part A's stand run gives a pre-deploy check.
- **Trap — load makes false reds.** <project>: five timeouts at host load 43-57 read as a red gate
  (2026-10-08). Read a timeout-only red under load as contention, not as a defect.

### B4. Rollback

- **Decide:** what triggers a rollback, which build you roll back to, and whether a red check can
  roll back automatically.
- **<project>:** automatic rollback on a red deploy gate — 3 auto-rollbacks in 97 production deploys
  (2026-10-01..16).
- **cryptochart:** rolls back only while production still serves the checked revision, so a rollback
  never undoes a build it did not check.
- **Trap — checking after the switch leaves a bad build serving.** <project>'s e2e runs after the
  production containers are recreated, so a red leaves the new build serving until the rollback ends.
  Run every check that can run off production before the switch (Part A's pre-deploy run); keep after-switch checks for what needs production data, with rollback behind them.
- **Trap — a rollback driven by a faulty check.** <project> 2026-10-13: a gate-tooling bug turned a
  cleared flake into a rollback. An automatic rollback is only as good as the check that fires it
  (B3).

### B5. Re-run one step after a flake, not the whole release

- **Decide:** what a flaked step costs — a re-run of that step, or a new release from the start.
- **cryptochart:** inside the full run each failed unit is re-run alone (rescue); after that only the
  failed release step is re-run, not the whole release. 13 flakes were rescued in 10 green runs.
- **<project>:** 11 of 97 production deploys passed only after a flaky clearance.
- **<project>:** its canvas-parity check flakes in about 7 % of runs — moved into a release gate as it
  is, it would stop about 1 deploy in 14 without a rescue.
- **Trap — a row refused after a long run forces a repeat.** cryptochart's release rows met the
  session-identity check only after its 12-minute full run, which then had to be repeated (and once
  masked a real red). Check that the release can record its rows before the long step.

## Part C — a worked setup: releasing through an unattended machine stand

Part B says what to decide. This part shows one way to put it together, built from a real release:
cryptochart's write-up of its stand-first release (public issue #201, engine of
2026-10-24) is the worked example; <project>'s stand, built from this page (cross:X-2067, cross:X-2082),
is a second one in C7. Every number in C1-C6 is cryptochart's; C7's are <project>'s. The kernel rules stay in their specs —
SPEC-1051 for the pre-deploy run, SPEC-0094 for `deploy`, SPEC-0097 for the deploy classes, SPEC-0205
rule 7 for stand roles, SPEC-1054 for the stand's data — and win on any difference with this page.

A **machine stand** here is a `production: false` deploy target that no person works on: the release
command deploys the release revision to it, the kernel's pre-deploy run checks that revision, the
project's own checks then read the served stand, and only then does production get the same revision.

### C1. The configuration — `yitc-ops.yaml`

The parts of the contract a stand-first release needs. Every value line says what it does; the
kernel's own config readers accept this block as it stands (the guide's test feeds it through them).

<!-- worked-config -->
```yaml
deploy: # the deploy verb's carrier (SPEC-0094)
  command: "ops/deploy/deploy.sh production" # the plain `deploy` — production; `default` in a class's targets
  targets: # named targets: `deploy --target <name>`
    acceptance: # the machine stand: same host, own port, service and data store
      command: "ops/deploy/deploy.sh acceptance" # what `deploy --target acceptance` runs
      production: false # the SPEC-0097 class gate does not apply; the pre-deploy gate still does (it is in targets: below)
      role: acceptance # SPEC-0205 rule 7: serves landed main; two advisory deploy lines, never a refusal
    sandbox: # a person's sandbox: deployed by hand, never gated
      command: "ops/deploy/deploy.sh sandbox" # what `deploy --target sandbox` runs
      production: false # not production, and named in no pre-deploy class, so no run guards it
verify: # what lands, Stage-6 runs and pre-deploy runs execute
  layers: # the declared verify layers
    - layer: node # a land-verify layer (SPEC-0152 rule 16)
      command: "ops/test/run-layer.sh node" # runs at every land and Stage-6 run, minus the pre-deploy units
    - layer: browser # a second land-verify layer
      command: "ops/test/run-layer.sh browser" # its pre-deploy units are tagged by the adapter's list answer
  layer_worker_shares: # each layer's fraction of a land's worker allotment
    node: 0.5 # half the allotment at a land
    browser: 0.5 # the other half
  pre_deploy_layer_worker_shares: # the table the pre-deploy run applies instead : the release units make layers heavier there
    node: 0.4 # node is lighter once its release-only units are counted
    browser: 0.6 # browser carries most release-only units
tests: # the test-class taxonomy (SPEC-0093 rule 10)
  classes: # one entry per class
    - class: release-only # the pre-deploy class (SPEC-1051 rule 1)
      moment: pre-deploy # left out of lands and Stage-6 runs, forced full runs included
      reason: "owner decision 2026-10-20: these units found no real fault at a land over 6 weeks of runs" # why they leave the lands
      targets: [default, acceptance] # both the stand deploy and the production deploy need a passed run first
      stand: acceptance # SPEC-1051 rule 6: a card changing one of these units is proven on this stand's run
      reuse_run: {reason: "the stand deploy's run of the same revision stands for production; a host-dependent flake may go unseen"} # SPEC-1051 rule 3
thresholds: # project thresholds (SPEC-1031)
  pre_deploy_reuse_max_age_minutes: 120 # how old a stand run production may stand on (band 1..1440; 120 is the default)
```
<!-- /worked-config -->

What the block leaves to the project: which units belong to `release-only`. The class names no files;
each unit is tagged `classes: [release-only]` in the verify adapter's `list` answer (<workshop-spec> rule
3). cryptochart keeps one list (`ops/test/lib/release-only.tsv`, 513 files) read by one module that
every runner configuration and every adapter asks, and its runners leave the listed files out unless
the release sets `CRYPTOCHART_E2E_RELEASE_RUN=1` on its `deploy` calls. A list the reader cannot
parse is an error, never an empty list — read empty, it would send every release-only unit back to
every land.

### C2. The one-command release

One project script runs the whole chain under one lock, and prints one last line. Each step writes
its row through the engine, so a stopped release resumes from the step that stopped it. The kernel
verbs it calls:

<!-- release-outline -->
| Step | What runs | The row it leaves | Stops the release when |
|---|---|---|---|
| (a1) stand deploy | `bin/yitc-v2 deploy --target acceptance --expect-revision <sha>` — the kernel runs the pre-deploy run (every verify layer whole plus every `release-only` unit, on a fresh checkout of `<sha>`, with the land's rescue), then the stand command | one pre-deploy run row per run, `deploy_completed` | the run is red: nothing is deployed anywhere |
| (a2) stand checks installed | the project's runner installed at `<sha>` on the stand | the project's own row | the install fails |
| (a3) served checks on the stand | the project's live checks against the served stand, re-run once whole on a red | the project's own row | red twice |
| (a4) served-path checks on the stand | the project's served-path checks | the project's own row | red twice |
| (1) production deploy | `bin/yitc-v2 deploy --class A --expect-revision <sha>` (`--class S` when the diff touches the security surface) — stands on (a1)'s run under `reuse_run`, no second run | `deploy_completed` naming the run it stood on | the reuse is declined and its own run is red, or the §6 last-moment revision check refuses |
| (2) production checks installed | the project's runner and monitor at `<sha>` | the project's own row | the install fails |
| (3) production live checks | the project's live checks against production | the project's own row | red: go to (5) |
| (4) settle the cards | `bin/yitc-v2 task close T-NNNN --settle-probe <key> --settle-evidence events.jsonl#ts=<row>` for each card whose deferred probe this release proves (procedure: SPEC-1011) | the settled probe | — (an unsettled probe is listed, not forced) |
| (5) rollback, on a red (3) | `bin/yitc-v2 deploy --rollback <previous sha>` while production still serves `<sha>` | the rollback's `deploy_completed` | — |
<!-- /release-outline -->

Around the steps (all project script, SPEC-1051 rule 8):

- **Start.** Wait for a near-empty land queue (or a night window), then read `main` HEAD — that is
  the release revision.
- **Lock.** Let lands in flight end, then hold every land and run until the release ends. Without the
  lock a land during the ~40-minute chain moves `main`, and the production deploy refuses at the
  SPEC-0094 §6 last-moment revision check.
- **One last line.** `RELEASE: DONE <sha>` / `RELEASE: STOPPED <sha> at step (<n>): <reason>` /
  `RELEASE: REFUSED <reason>`. After a red nothing is done by hand; the next run of the same command
  starts again, and resumes when production already serves the sha (only with a passed pre-deploy
  row of the sha in the journal, read by `bin/yitc-v2 journal query`).

### C3. Every credit in the chain — what is not run twice

| Credit | Granted by | Bound |
|---|---|---|
| A land takes the worker's green Stage-6 run as its candidate leg | kernel, SPEC-0065 §Bound | `main` advanced only by inert paths, or a passed post-sync proof covers the advance; same tree |
| Release-only units never run at lands or Stage-6 runs | kernel class, SPEC-1051 rule 2, plus the project's list | forced full runs included; they run at the deploy instead |
| The pre-deploy run rescues a failed unit, re-runs a timeout-only red run with a land beside it, re-runs alone a layer that ran out of time with nobody beside it | kernel, SPEC-1051 rule 3 | a second red is red |
| The production deploy stands on the stand deploy's run | kernel `reuse_run`, SPEC-1051 rule 3 | newest run of the sha, all rows passed, same classes and declaration, younger than the threshold, a `deploy_completed` names it |
| A red live run on the stand is made once more, whole | project script | at most twice |
| Deferred card probes are settled from the release's own rows | project script, through `task close --settle-probe` | only cards whose commit is an ancestor of the sha |
| A resume skips the deploys | project script | only with a passed pre-deploy row of the sha |

### C4. A card that adds or changes a check — how it meets the stand

A check that runs only at the deploy, or only against a deployed site, is never run by the card's own
land. So its proof comes in two halves: one before the land, one on the stand after it. The second
half is a deferred probe on the card (SPEC-0015), so the card closes and lands while the probe waits.

| The card adds or changes | Before its land | After its land, on the stand | Who settles it |
|---|---|---|---|
| an ordinary test | its own tests, then the Tests run | — | the land |
| a pre-deploy unit (a file in the class, its adapter or runner config) | a hand run of that unit as the release would run it | its run inside the next stand deploy's pre-deploy run on a revision carrying the card (SPEC-1051 rule 6, the `stand-release-only` deferred probe) | the release, through `task close --settle-probe` citing the class row |
| a check of the deployed site | its stand-in tests | **project-specific** — see below | the project |
| a product change with a live probe | its tests | the release's own live runs, on the stand and on production | the release, from the production run's row |

**Checks of the deployed site are each project's own** (SPEC-1051 rule 8; B3). The kernel has no
class for them and gives them no stand probe. One option a project may adopt is cryptochart's: the
card carries a deferred probe, and a controller settles it by hand between releases with one focused
reading on the stand — deploy `main` to the stand under the stand's check lock, install the runner at
the card's landed commit, run that one check once, reinstall at `main`, and record one
`state_checked` row naming the card's commit, the served release, the runner commit and the result
(its project rule, <workshop-spec> rule 12). A red reading is fixed by a card before the next release, so a
broken new check is not first found by the release that depends on it.

### C5. A real release, measured

cryptochart, 2026-10-24/25: five attempts of the same command. Four stopped at (a1) — the design
working: a red pre-deploy run refused the stand deploy, nothing reached the stand or production, the
lock came off, lands resumed.

| Run | Stopped by | Fixed by |
|---|---|---|
| 1 | the run published no worker allotment, every layer sized itself to all 32 host cores; ~40 red files on load alone | kernel (public issue #193) |
| 2 | a layer at its time bound; a release-only test calling an engine private symbol an update removed; a number compared as `174.50` against `174.5` | project cards |
| 3 | the run's own load: release shares summed to ~46 workers on 32 CPUs; plus a test broken by a landed product card | project cards; the separate pre-deploy share table |
| 4 | one real red: a dialog test broken by a landed product card | a project card |
| 5 | — | `RELEASE: DONE` |

The passing release: lock 18 s; (a1) pre-deploy run 17 min 14 s (16 layers whole plus 561
release-only units, nothing rescued) and stand deploy 25 s; (a3) stand live run 565 s; (a4) 18 s;
(1) production deploy 31 s, standing on a 10-minute-old run; (3) production live run 488 s; (4) 25
deferred probes settled in ~3 min. About 40 minutes end to end, lands held throughout; `reuse_run`
saved a second run of about 17 minutes.

### C6. Questions a project asks when it sets this up

Asked by <project> (cross:X-2067) for its own stand.

#### C6.1 The four places, and which may share a stack

1. **A person's own sandbox** — where someone explores, often a spike (`patterns/spike-mode.md`).
   Serves whatever that person is working on.
2. **`main`, reached only through cards** — a spike's result enters as a card that names it
   (SPEC-0205 rules 5-6); nothing is copied in by hand.
3. **The acceptance view of `main`** — a sandbox serving landed `main` for a person to look at
   (SPEC-0205 rule 7, `role: acceptance`).
4. **The machine stand** — a `production: false` target in the pre-deploy class's `targets:`, which
   only the release command deploys.

Spike work and landed code never share a stack instance: a stack is a spike stack or an acceptance
stack by what it serves (SPEC-0205 rule 7). The machine stand **may** double as the acceptance view —
cryptochart's acceptance target is both — because a release always deploys its own revision to the
stand first (step a1) and holds the stand's check locks while it reads it. Keep them **separate**
when a person's acceptance session runs long or changes the stand's data while a release could
start, or when the release must never wait for a person to finish looking: then the machine stand
serves only release revisions, and the acceptance view takes `main` whenever someone asks.

#### C6.2 Where each kind of check runs

| Check | Where | Who runs it |
|---|---|---|
| the verify layers, minus the pre-deploy units | every land and Stage-6 run | kernel |
| the pre-deploy units, plus every layer whole | the pre-deploy run before each gated deploy — the stand deploy, and production unless it stands on the stand's run | kernel, SPEC-1051 |
| a changed pre-deploy unit, proven on the stand | inside the next stand deploy's pre-deploy run | kernel, SPEC-1051 rule 6 |
| served-site checks on the stand | after the stand deploy, against the served stand | project (C2 a3, a4) |
| production live checks | after the production deploy | project (C2 step 3), with rollback behind them (B4) |

A pre-deploy run checks a fresh checkout of the revision, not the served build; only the project's
served-site checks read what the stand and production actually serve.

#### C6.3 Cutting a release batch and resuming after a red step

Cut the batch at `main` HEAD after the start wait (B1: keep it small, never on a red `main`). The lock
then stops `main` moving. A red step stops the release with its one last line and releases the lock;
nothing is undone by hand. Fix the cause by cards — they land normally — then run the same command
again: it takes the new HEAD, and a red (a1) found nothing deployed, so the new run starts clean. A
run that stopped after production already serves the sha resumes from the step after the deploys,
because the journal holds the passed pre-deploy row and the `deploy_completed` rows (B5: re-run the
step, not the release).

#### C6.4 An ungated sandbox target beside a gated stand target

Declare both as `production: false` targets (C1: `sandbox`, `acceptance`). Only the target a
pre-deploy class names in `targets:` is gated: `deploy --target acceptance` runs the pre-deploy run
first, `deploy --target sandbox` runs its command straight away. Neither takes the SPEC-0097 class
gate, which reads `production: true` only. The cost of leaving the sandbox ungated is that it may
serve a revision whose release-only units never ran — fine for looking, never a substitute for the
stand.

#### C6.5 The stand's data — a treated production copy, and its first bring-up

A stand that must behave like production needs production-shaped data. Its sanctioned source is a
restored production copy treated before the stack is used, on the three strands of SPEC-1054
(reachability — by default neutralize what could reach a live system; disclosure — what is harmful
merely by being readable; operational state — defuse what would make work happen) — the same treatment a spike copy takes;
SPEC-0205 rule 7 applies it to an acceptance stand holding such a copy. By default the stand runtime
never connects to live production; only the named refresh step reads it, read-only. These are the
recommended defaults: what the stand may keep — an ACCEPT on any strand, or a relaxed default — is
the project's decision, recorded in its own decision file with purpose, readers, scope and
destruction (SPEC-1054 §0). Give the stand its own
data store and its own identity from day one, and bring up a brand-new stack the way
`patterns/spike-mode.md` §First bring-up of a brand-new stack and §Several stacks describe. A stand
whose checks need no production data (cryptochart's stub market-data upstream on the stand) can skip
the copy entirely.

#### C6.6 The reuse_run trade-off

The option, its bounds and its cost are stated in B2 (Option — one run for both targets) and
SPEC-1051 rule 3; this answer adds only the measured side. With `reuse_run` the production deploy
took 31 s instead of a second ~17-minute run, on a run 10 minutes old. What it gives up is a second
run on the same revision: a flaky or host-dependent unit that passed once ships unseen. Declare it
when your stand and production run on the same host and the steps between the two deploys are short
(cryptochart: 8-38 minutes, against the 120-minute default threshold); leave it out when production
runs somewhere the stand does not.

### C7. A second stand, measured: <project>

<project> built its stand from this page on 2026-10-26/27 (cross:X-2082). What differs from C1-C6:

- **Shape.** A separate stand stack, never a person's sandbox (C6.1 keep-separate case), with its own
  data store holding a treated production copy (C6.5) and an address only machines read. The two
  people's sandbox targets stay ungated (C6.4).
- **Configuration.** One `production: false` stand target; the existing pre-deploy class widened to
  name it beside production, with `reuse_run` and its reason and a 120-minute reuse bound (C6.6).
- **Release command.** The C2 steps, plus an arm that stops after the stand. Its settle step does not
  settle probes itself — a matching deploy row does not prove a criterion — it lists the candidate
  cards and prints the settle commands for the Controller.
- **Measured.** The first gated stand deploy was refused by a red pre-deploy run on a real defect,
  fixed by a project card; the second passed with a pre-deploy run of ~10 min and a stand deploy of
  33 s. <project>'s production has not yet released through the stand: that is the owner's call.

Advisory, from <project>'s first bring-up: check the session carry the governed deploy needs before
restoring the production copy, not after — <project> keeps that check in its own bring-up script.

## What stays out of both lists

A run of the declared pre-deploy checks on main between releases (so a release-only regression is
seen at the next completed daily run, B1) is not in SPEC-1051: it is SPEC-1047's, set up as Part D.

## Part D — the scheduled pre-deploy run: a daily run of the pre-deploy checks on main

The B1 trap above — a check that runs only before a deploy waits for the next release — has a kernel
answer: `deploy --scheduled-run` runs on main's head, once a day, the same pre-deploy run a gated deploy
runs, and deploys nothing. Its rules are SPEC-1047 (`bin/yitc-v2 graph query SPEC-1047 --kernel`); this
part shows how a project sets it up and how it is checked. Where this text and the spec differ, the
spec wins.

### D1. The crontab line

One line in the crontab of the account that owns the project's main checkout. `<engine>` is the engine
install path, `<project>` the project's main checkout, `<name>` a short name for this job, `<log>` the
file the run's output goes to; pick the minute and hour yourself (a quiet hour, outside your usual
release window):

<!-- scheduled-run-crontab-line -->
```
17 4 * * * cd <project> && <engine>/bin/yitc-v2 -C <project> session start >> <log> 2>&1 && YITC_SESSION_REF=cron-<name> <engine>/bin/yitc-v2 -C <project> deploy --scheduled-run >> <log> 2>&1
```

Both halves of the SPEC-0142 §6 invocation contract are on that line and neither may be dropped: the
`session start` before the verb, and `YITC_SESSION_REF=cron-<name>` carried into it. Without the first
the verb is refused before it runs (no session record, SPEC-0137); without the second it is refused
with «no YITC_SESSION_REF is carried»; either way no row is written and the day is lost. Run it from the
main checkout: a run started anywhere else is refused (SPEC-1047 rule 2). A host that wraps its cron
jobs in a notify script may put the wrapper in front of the whole line, as it does for its other jobs.

### D2. Declare it in the project's product_cron section

The cron is the project's own scheduled work, so it is declared in `yitc-ops.yaml`'s `product_cron:`
section (SPEC-0109), in place of the born waiver. Keep the line in ONE committed file — the scheduler
definition, the single source the host's crontab is installed from — and let the section point at it:

<!-- scheduled-run-product-cron -->
```yaml
product_cron:
  scheduler: crontab
  source: ops/crontab # the committed crontab file holding the D1 line
  inventory: # derived from `source:`, never typed by hand (SPEC-0109 rule 2)
    - job: scheduled-pre-deploy-run
      schedule: "17 4 * * *"
      command: deploy --scheduled-run
```

The section's rule 3 asks for observed runs, not only a declaration: the run's own rows (D4) are those
observations.

### D3. The queue it needs

The run takes its place in the project's common queue of runs and lands (SPEC-1045), so the queue must
be on: `admission.mode: engine` in `yitc-ops.yaml`, and no `YITC_ADMISSION_ENGINE=off` veto on the
machine. With the queue off the command is refused before it runs, naming the switch (and the veto
when that is what holds it off), and writes no row. Once on, the run waits its turn behind the lands
already queued, holds the verify resources shared while it runs, and never moves `main`.

### D4. What it records, and the debt line

Each run writes one `test_class_executed` row per pre-deploy class, marked `run_kind: scheduled`, with
no `target`; its `evidence:` names the run log under `.yitc/`. No deploy reads these rows: every
gated deploy still runs its own pre-deploy run. A passed run clears the class-staleness debt line as
any run of the class does.

When the project's current scheduled run is red, the next session start in the main checkout (and an
explicit `bin/yitc-v2 debt`) prints one line:

```
debt: scheduled pre-deploy run red [<date> <candidate> <run_ref>] — … its log: <evidence> — read the log and file what it finds as ordinary work
```

The line names the run, never the cause. The agent that triages it opens the named log — the run's
fail-to-end report: every failing unit and layer, the rescued ones named, and the cards landed since
the last passed scheduled run — and files what it finds as ordinary work (a card or a followup that
cites the log). The line clears by itself once a later scheduled run of main passes; nothing refuses
on it.

### D5. The adoption steps a project is asked for

The kernel asks each project that takes the run up for the steps below, as a coordination request;
the request text is this list. They are the evidence that the run works on that project, not only on
the kernel's fixture.

1. Install the D1 line in the owning account's crontab and commit it to the D2 `source:` file;
   replace the `product_cron` waiver with the D2 declaration; switch the queue on (D3) if it is off.
2. Soak for seven days. Each day counts only when a scheduled row of that day is matched, by time, to
   a line of the scheduler's own log for the same job (the system cron log, or the log of the notify
   wrapper). A row from a hand run of the same command matches no scheduler line and is no soak day.
3. Exercise one red run: a run that reads red (a real break, or a unit broken on purpose and then
   fixed), the debt line shown, and the line gone after the next passed run. It counts only with a
   triage record beside it — a card or followup that cites the run log, or a recorded decision on
   it.
4. Reply to the request with the seven matched days (row stamps beside the scheduler log lines) and
   the red run's log, its triage record and the run that cleared it.

The weekly review then keeps checking that the job still fires: the inspection roster's
«scheduled pre-deploy runs» row (`patterns/inspection-criteria-roster.md`) matches a scheduled row on
each day of the week against the scheduler's log. No monitor of its own exists for a stopped cron;
that weekly check is it.

## See also

- SPEC-1051 — the kernel rules behind Part A.
- SPEC-1047 — the scheduled pre-deploy run behind Part D; SPEC-0142 §6 — the cron invocation contract.
- SPEC-0094 — the `deploy` verb, its targets, `--expect-revision` and the load window.
- `patterns/verify-cost-playbook.md` — how to find which checks to move out of lands.
- `patterns/deploy-smoke-test.md` — a post-deploy page check (B3).
- `patterns/deploy-coherence.md` — keeping the served runtime in step with the deployed code.
- `patterns/spike-mode.md` — sandboxes, stand roles and a stack's first bring-up (C6.1, C6.5).
