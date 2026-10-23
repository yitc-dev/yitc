---
name: project-release-guide
class: reference
sourced_from: plan deferred-checks-a-project-moves-costly-checks-out- (§Analysis aid item 3, owner request to give projects a reference of what they can do and must set up themselves; public issues #140 and #161). Every worked example and number below is quoted from that plan's read-only readings of cryptochart, <project> and <project> (2026-10-10..22).
applies_to: a project that deploys from its land queue and wants to know which part of its release the kernel runs and which part it must build — release batching, the stand-then-production order, live checks on the served site, rollback, re-running one step after a flake.
cites:
  - SPEC-1042
  - SPEC-0094
  - SPEC-0097
  - SPEC-0015
  - SPEC-1030
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

Four parts, each specified in **SPEC-1042**. The rules are there and only there; this list says what
each part is for.

- **The pre-deploy run inside the deploy** — a full check of the exact revision a gated deploy ships,
  before its command (SPEC-1042 rules 3-4).
- **The per-target gate** — the project names which deploy targets, stands included, need that run
  (SPEC-1042 rules 1 and 5).
- **The stand run of a new or changed check** — such a check meets the project's stand once after its
  card lands, before a production deploy depends on it: its run inside the pre-deploy run of a stand
  deploy that completed on the landed revision (SPEC-1042 rule 6). It shows the check itself works. It
  is not a check of the build the stand serves — a pre-deploy check runs on a fresh checkout of the
  candidate; checking the served build is your project's post-deploy checks (B3).
- **The analysis view** — reads the project's own journal to show which checks could leave the lands
  and what that changes (SPEC-1042 rule 7; how to read it: `patterns/verify-cost-playbook.md`).

## Part B — what your project sets up itself

SPEC-1042 §8 names these five as the project's own. For each: what to decide, how the three projects
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
  are SPEC-1042 rule 3. Its cost: production ships on a run up to that age old, so a failure only a
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

## What stays out of both lists

A run of the declared pre-deploy checks on main between releases (so a release-only regression waits
at most a day, B1) is not in SPEC-1042: it is a follow-up of the proposing plan.

## See also

- SPEC-1042 — the kernel rules behind Part A.
- SPEC-0094 — the `deploy` verb, its targets, `--expect-revision` and the load window.
- `patterns/verify-cost-playbook.md` — how to find which checks to move out of lands.
- `patterns/deploy-smoke-test.md` — a post-deploy page check (B3).
- `patterns/deploy-coherence.md` — keeping the served runtime in step with the deployed code.
