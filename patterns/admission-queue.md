---
name: admission-queue
class: technique
sourced_from: <durable artifact> (activation owner of SPEC-1045, plan port-cryptochart-s-settled-admission-queue-into-th). The worked example is cryptochart's settled queue, its ops/deploy/wait-for-room.py at the pinned source revision SPEC-1045 ## Rationale names (its THE SETTINGS table read there), and the values issue 197 on the kernel's public tracker reports in force; the kernel's own values are the engine's built-in defaults (`bin/yitc-v2 config list`).
applies_to: switching a repository onto the engine's resource-admission queue, choosing its keys, and keeping the land's Stage-6 credit while the queue is on.
cites:
  - SPEC-1045
  - SPEC-1031
  - SPEC-0152
  - SPEC-0065
  - SPEC-1038
  - SPEC-0186
---

# The admission queue — switching a repo on, its keys, and the card order that keeps the credit

> **Plainly.** With the queue on, every governed Stage-6 run (`task test --run`), own-tests check
> (`task test --own`) and land of a repo starts only when the queue admits it: one land at a time, a
> card's run pulling `main` first and taking the project's quick checks, a green run holding the repo
> for that card's own land, and bookkeeping and credit-ready lands passing at once. It decides WHEN
> started work takes the repo's verify resources, never WHICH work exists. This page adds no rule: the
> queue's rules are SPEC-1045 (`bin/yitc-v2 graph query SPEC-1045`), the setting classes SPEC-1031, the
> two `verify:` switches and the quick set SPEC-0152 rule 16 — on any difference those win.

## 1. The switch

The queue applies while the main checkout's `yitc-ops.yaml` declares

```yaml
admission:
  mode: engine
```

and the machine has not vetoed it (`YITC_ADMISSION_ENGINE=off` in the environment or the machine
settings file reads it off — SPEC-1045 rule 3). Switched off, every entry point behaves exactly as its
own spec states and no row gains a field.

**Switching an existing project on: finish the tasks, switch, go on.** A process reads the switch once,
at its start, and keeps that path; there is no transition step and no scan for ungated work. So:
1. let the cards in flight land (or pause them) — `journal query --admission` and `debt` show what is
   still running;
2. land the one-line `admission: mode: engine` change through an ordinary card (`yitc-ops.yaml` is
   the project's operating contract: the substantive path, both audits);
3. go on — the switch is read from the base tree, so it takes effect from the NEXT land, never on the
   land that carries it.

**A new project is born with it on.** Its first `init` writes the born `admission:` section with
`mode: engine`; a re-seed into an existing `yitc-ops.yaml` without the section writes `mode: off`, so
an existing project switches itself on as above. What a new project does next: §5.

## 2. Every key, by who sets it

The project DECLARES (in `admission:` — non-numeric, deciding only WHEN its work is admitted):

| key | what it decides | engine default (the kernel's) | cryptochart |
|---|---|---|---|
| `mode` | the switch | `off` (born `engine`) | its own script today; it switches to `engine` after the release |
| `order` | the classes' order of passing | `light, land-mark, land, run-mark, run-light, run` | the same sequential order (#197 comment 4) |
| `at_once` | classes that pass with no load reading and no spacing | `light, bookkeeping, credit, no-layer, own-tests` | the same |
| `light_layers` | layers a light land may run | `deps, static, ops, integrity` | the same (its own layer names) |
| `planning.paths` | where a planning land's changes lie | `plans/ ideas/ specs/ scenarios/ docs/ tasks/ decisions/ lessons/` | the same |
| `planning.branches` | a planning land's branch prefixes | `work/` | the same |
| `planning_lands` | `after-run` (held by another card's unit and hold) or `immediately` | `immediately` with a non-empty `verify.layers`, else `after-run` | the source's planning land: `after-run` |
| `green_hold` | hold the repo for a green card's land | `on` | on (GREEN_HOLD 900 s, #197) |
| `run_land_unit` | a card's run and land as one unit | `on` | on (RUN_LAND_UNIT 1, #197) |

The project's VERIFY contract carries the two switches that change what a run verifies, read only while
the queue is on (SPEC-0152 rule 16), and the quick set they act on:

| key | engine default | what it does |
|---|---|---|
| `verify.sync_at_stage6_admission` | on | the run calls `worktree sync --task` at its admission |
| `verify.post_sync_set_first` | on | the quick set first: a sync proof that covers Closure ends the run, a RED stops it |
| `verify.post_sync_set` | none | the quick set — layer names, or a list of test files the engine's runner runs where SPEC-0152 rule 16 takes that form (no `verify.layers` declared, or the engine's own repository). None declared: neither switch acts |

The MACHINE sets every number and every value that describes the host (SPEC-1031 PERFORMANCE, or
BUDGET for a bound that stops started work), and the veto — `bin/yitc-v2 config list` shows each with
its source, `config set` changes one on this host:

| key | engine default (the kernel's) | cryptochart's source value |
|---|---|---|
| `YITC_ADMISSION_THRESHOLD_PCT` | 30 | 30 |
| `YITC_ADMISSION_WINDOW_S` / `_SAMPLE_S` / `_EMPTY_SAMPLE_S` | 90 / 3 / 3 | 90 / 3 / 3 |
| `YITC_ADMISSION_POLL_S` / `_SPACING_S` / `_STEP_S` | 15 / 60 / 0.25 | 15 / 60 / 0.25 |
| `YITC_ADMISSION_RUNS_AHEAD` | 8 | 8 |
| `YITC_ADMISSION_LAND_TAIL_THRESHOLD_PCT` | 10 | 10 |
| `YITC_ADMISSION_PIN` / `_LIGHT_PIN` | empty (no pinning) | `2-15,18-31` / empty — its host's CPUs |
| `YITC_ADMISSION_LOCAL_RUNS` / `_REMOTE_SLOTS` | 1 / `engine` | 1 (#197 comment 1) / `engine` |
| `YITC_ADMISSION_GREEN_HOLD_S` | 900 | 900 |
| `YITC_ADMISSION_QUICK_LOCK_BOUND_S` | 300 | 300 |
| `YITC_ADMISSION_QUICK_RUN_BOUND_S` / `_SYNC_BOUND_S` (BUDGET) | 300 / 600 | 300 / 600 |
| `YITC_ADMISSION_LAND_SET_BOUND_S` / `_FILE_BOUND_S` (BUDGET) | 120 / 60 | 120 / 60 |
| `YITC_ADMISSION_ENGINE` (the veto) | `auto` | — |

Not ported, so no key: the source's batch size (the engine admits ONE land at a time — a rule), its
release lock and gate, land groups and refusal span (SPEC-1045 rule 2). A host tunes the PERFORMANCE
numbers for itself (`config set`, e.g. a higher threshold on a host whose land verifies are wide); the
built-in defaults above stay the engine's.

**The kernel's own declaration** (its `yitc-ops.yaml`, SPEC-0186 rule 6): `admission: mode: engine`
and its quick set as test files, the engine's form beside its one suite layer — five whole-repo test
files a sync from `main` can break (the spec anchors resolve, their signatures are current, the
manifest and the graph's spec-to-code map regenerate, the scenario corpus holds). Every other key is
the default.

## 3. The card order that keeps the credit

The land takes a card's green Stage-6 run as its candidate leg only on SPEC-0065 §Bound's conditions —
the tested tree is the landed tree, and `main` has not moved past it (or a passed post-sync proof covers
the move). With the queue on, the order that keeps it is:

1. **edit** the change;
2. **`task commit`**, with `--reverify SPEC-NNNN` for each spec whose anchored code the diff moved — the
   ship commit, every re-sign in it (a re-sign after the audit would change the audited subject);
3. **`audit post`** on that commit;
4. **`task test --run`** — the run is admitted, syncs `main` in, takes the quick set, runs, and its green
   end sets the card's green hold: no other card's run and no land that runs a layer passes until this
   card's land ends;
5. **`task close`** — commits only the card's own record (inert for the credit);
6. **`land`** — credit-ready: it passes at once and takes the run's verdict.

Anything substantive between 4 and 6 (a fix commit, a hand-resolved merge) moves the tree off the tested
one: the land then re-verifies. A card that waits long after its green run loses the hold after
`YITC_ADMISSION_GREEN_HOLD_S`, and another card's land may then move `main`; the next `task test --run`
syncs and, when the quick set proves the move, ends at once on that proof (SPEC-1038 Closure coverage
permitting) instead of running the full verify again.

## 4. Reading it

- `bin/yitc-v2 journal query --admission` — the queue as it stands (waiters, what passed, the hold),
  and the comparison protocol's soak window over the main journal: credit share, cards per hour, abort
  rate, signals and unknown outcomes, against the fixed baseline before the switch-on.
- Every pass, wait, leave and step is an `admission_*` row on the main journal; every `land_completed`
  and Stage-6 result row carries `admission: engine`, the queue revision and the configuration hash.

## 5. First setup in a new project

What a project does once, after its first `init`, so the queue does its whole job. The rules stay in
their homes: the queue SPEC-1045, the quick set and the two `verify:` switches SPEC-0152 rule 16, who
sets which value SPEC-1031.

1. **On once verify is confirmed.** The born `yitc-ops.yaml` declares `admission: mode: engine` and, in
   `verify:`, the kernel-provided `integrity` layer named as the quick set (`post_sync_set: [integrity]`).
   But `verify:` is born-permissive: an init run without `--confirm-born-permissive verify:<owner>` (every
   AI-run init, which has no TTY to ask on) withholds the whole section, so there is no verify layer and
   no quick set until it is confirmed (SPEC-0189 rule 8). Once confirmed, nothing to switch on;
   `mode: off` is the way out (§1).
2. **Pick the quick set.** Take the checks that most often break right after `main` is merged in: the
   spec, contract or schema integrity checks, the graph or index build, import and lint. Together they
   stay well under a minute. Never a slow end-to-end test: the quick set runs before every full run,
   and a slow one only delays it.
3. **Declare it in the right form.** With `verify.layers` declared (the born case), `post_sync_set`
   names layers from that list: put the quick checks in a light layer of their own beside
   `integrity` and name both. With no `verify.layers` declared, it is a list of `test_*.py` files the
   engine's runner runs (SPEC-0152 rule 16; the engine's own form: SPEC-0186 rule 6). A name that is
   no declared layer, or a file entry that is no `test_*.py` path, is refused by the `init` sweep.
4. **Leave the two switches on.** `verify.sync_at_stage6_admission` and `verify.post_sync_set_first`
   default on and act only once the quick set is declared; leave them out of the file.
5. **Check it took.** After the first card's `task test --run`, `bin/yitc-v2 journal query --admission`
   shows the run's pass, and its `admission_step` rows show the sync and the quick set run before the
   full verify.
6. **Machine numbers are the server's.** The load threshold, the width floor and the runs per project
   are MACHINE settings of the host (`bin/yitc-v2 config list`, §2), never keys in the project's file.
