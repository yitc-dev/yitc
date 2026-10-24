---
name: verify-layer-adapter-protocol
class: runbook
sourced_from: public proposal 60 on the release mirror (an adopter turned the adapter on for six Playwright layers and had to read engine source to write the project script). The protocol stated here is read off the engine's adapter pass; the contract it serves is <workshop-spec>.
applies_to: writing the project-owned script behind a verify layer's `adapter:` block — what the kernel hands it, what it has to answer, and one sample to copy per report profile
cites:
  - <workshop-spec>
  - SPEC-0152
---

# The verify-layer adapter protocol — and a sample adapter per runner

> **Catalog.** This page is one source of `patterns/verify-cost-playbook.md`, which lists every verify-cost
> technique with its measured case — read it there when choosing what to cut.

> **Plainly.** A verify layer normally tells the kernel one thing: its command passed or failed.
> An **adapter** is a small script in *your* repository that lets the kernel see the layer's
> tests file by file — list them, run exactly the ones it names, and report each one. This page
> states everything that script and the kernel say to each other, and points at four samples you
> can copy. What the kernel then *does* with the per-file results — re-run a failed file alone,
> count flaky files, record what a change would reach — is the contract, SPEC-1035
> (`yitc-v2 graph query --kernel SPEC-1035`); none of it is restated here.

## When you need this page

You have a project with a declared verify layer (`verify.layers[]` in `yitc-ops.yaml`) whose
tests run inside a runner — Vitest, Playwright, pytest — or as one script per file, and you want
per-file results. You write one script, declare it on the layer, and keep it: the kernel never
ships or imports an adapter.

If the layer declares no `adapter:`, nothing on this page applies and the layer behaves exactly
as before.

## Start from a sample

| Profile | Sample to copy | Answers |
|---|---|---|
| `vitest/1` | `patterns/verify-layer-adapter-samples/vitest-adapter.py` | `list`, `related`, `run` |
| `playwright/1` | `patterns/verify-layer-adapter-samples/playwright-adapter.py` | `list`, `related`, `run` |
| `pytest/1` | `patterns/verify-layer-adapter-samples/pytest-adapter.py` | `list`, `run` |
| `script/1` | `patterns/verify-layer-adapter-samples/script-adapter.py` | `list`, `run` |

1. Copy the sample for your runner into your repository (for example to `tools/`).
2. Edit the few values under `SETTINGS` at its top — where the runner's config lives and how
   your project starts the runner.
3. Declare it on the layer (next section) and commit both.

Each sample is plain text you own from the copy on; change it freely. Every sample is run by the
kernel's own test suite through the real adapter pass, so what you copy is known to speak the
protocol below.

## The declaration

```yaml
verify:
  layers:
    - layer: frontend
      # `command:` stays the layer's full command — the fallback
      command: bash bin/verify-frontend.sh
      adapter:
        list: python3 tools/vitest-adapter.py
        related: python3 tools/vitest-adapter.py
        run: python3 tools/vitest-adapter.py
        report_profile: vitest/1
        sources:
          - tools/vitest-adapter.py
          - web/vitest.config.js
```

The three commands may be one script (the samples are): the manifest says which action is
wanted. The key set is closed — an unknown key fails the declaration before any layer runs.

| Key | What you write |
|---|---|
| `run` | Required. The command that runs the units the kernel names and writes the runner's report. |
| `list` | The command that enumerates the layer's test files without running a test. Leave it out when the runner has none; the per-file rows are then diagnostics only and the layer's `command:` decides. |
| `related` | The command that names the test files a change reaches, without running a test. Leave it out when the runner has none; per-file report, re-run and rescue still work. |
| `report_profile` | Required. One of the profiles in the table further down — how the runner's own report reads. |
| `sources` | The repository paths (files or directories) that implement the adapter and the runner configuration its commands read. Every repository file a command names has to be listed here, itself or a directory above it. |
| `required` | Commands for the layer's non-test checks (typecheck, lint, build). They run before `run`; a failing one fails the layer. |
| `modelled` | File-name suffixes (`.ts`, `.py`, …) the runner's dependency tracking resolves. Left out, it means JavaScript and TypeScript source modules only; a changed file of any other kind is recorded as reaching the full layer. |
| `triggers` | Extra `globs` mapped to `units` or to `full: true` — files a test reads without importing them. |
| `selection` | `off` (default), `shadow` or `deciding`. `shadow` records what the change would select; the full layer still runs. `deciding` runs only the test files the change reaches, and the whole layer wherever the kernel cannot place the change. |
| `selection_deciding_reason` | Written with `selection: deciding`, and only with it: who accepted the risk of that mode, and why. |
| `credit` | `off` (default), `shadow` or `deciding`. `shadow` records which passes a fix attempt could reuse; the full layer still runs. `deciding` reuses them: after a failed run and a fix, the next attempt runs the files that failed and the files the fix reaches. |
| `credit_deciding_reason` | Written with `credit: deciding`, and only with it: who accepted the risk of that mode, and why. |
| `rescue` | `on` (default) or `off`. Whether a file that fails and then passes alone keeps the verdict green. |

What each key *means* for the verdict is SPEC-1035 rule 1 and the rules it names; the two
`deciding` modes, their reasons and what makes such a declaration malformed are SPEC-1030.

## How the kernel calls your command

- It runs the command through the shell with the **repository root of the checkout being
  verified** as the working directory, after the layer's `prep:` (so `node_modules` and the like
  are in place), with the layer's environment.
- Before every call it creates a fresh, empty directory outside the repository, writes
  `manifest.json` into it and puts that file's path in the environment variable
  **`YITC_VERIFY_ADAPTER_MANIFEST`**. The directory is removed after the call.
- Your command reads the manifest, does the one thing its `action` names, writes its answer or
  its reports to the paths the manifest gives, and exits.
- The calls of one pass over the layer share the layer's `timeout:`.

## The manifest

A JSON object. Read the keys you need and ignore any you do not know.

| Key | Present on | What it holds |
|---|---|---|
| `schema` | every call | The protocol version, the number `1`. |
| `run_id` | every call | A name for this call, unique within the verify. |
| `layer` | every call | The layer's name. |
| `action` | every call | `list`, `related` or `run` — what to do. |
| `profile` | every call | The layer's `report_profile`. |
| `project` | every call | On `run` of a listed inventory, for a profile whose report does not name the runner project: the one project to run (an empty string when the runner has a single project). Otherwise `null`. |
| `units` | every call | On `run`: the units to execute, each as `list` gave it, or `null` when the layer has no `list` — then run everything the layer runs. On a re-run a unit may also carry `cases` (see «What `run` does»). On `related`: the whole inventory. On `list`: `null`. |
| `output` | every call | The path where `list` and `related` write their answer. |
| `report` | every call | The path where `run` makes the runner write its JUnit report. |
| `second_report` | every call | The path where `run` makes the runner write its second report, or `null` when the profile has none. |
| `base` | `related` only | The commit the kernel compares against. |
| `changed` | `related` only | The repository-relative paths the kernel sees as changed. |
| `isolated` | a re-run or a lane run only | `true`: run the named units one at a time (no parallel files). Absent on a first attempt. |

## What `list` answers

`list` writes one JSON object to the manifest's `output` path and exits 0. It names the files
**the layer's command runs** — not everything the runner could collect from a directory — and
runs no test body.

### The `list` answer

| Key | What it holds |
|---|---|
| `schema` | The number `1`. |
| `units` | A non-empty list of units (next table). |
| `errors` | A list of text messages; empty when the enumeration is complete. Any entry means "this inventory is not reliable". |
| `versions` | Optional. Up to 16 names mapped to version text (each at most 100 characters) — the runner and any dependency tracker it uses. Without it the layer's recorded identity is withheld. |

### Each `list` unit

| Key | What it holds |
|---|---|
| `file` | Required. The test file, repository-relative, in plain form: no leading `/`, no `./`, no `..`. |
| `project` | The runner project the file belongs to. Leave it out (or empty) when the runner has one project. |
| `report_id` | The name the runner's own report gives this unit, when that is not what the profile derives by itself (the profiles table says what it derives). |
| `group` | A label shared by files that only work together (a serial suite). A group is re-run and counted whole. |

The kernel treats the inventory as unusable for this run — and runs the layer's full `command:`
instead — when the command exits nonzero or times out, the answer is missing or is not this
shape, `schema` is not `1`, `errors` is not empty, `units` is empty, a file is not in plain repository-relative form,
the same file and project appear twice, or one file is listed in two projects under a profile
whose report does not name the project.

A unit MAY also carry `classes`: the names of the declared test classes it belongs to
(`tests.classes[].class`); leave it out for a unit of no class. The kernel reads it only for a
pre-deploy class: every unit of one `group` names the same pre-deploy class or none, and a land
or a Stage-6 run leaves a pre-deploy unit out after every other choice (<workshop-spec> rules 1-2).

## What `related` answers

`related` is asked only on a layer declaring `selection: shadow` or `credit: shadow`. It gets the
whole inventory as `units`, plus `base` and `changed`, and writes to `output` the units the
change reaches — **without running a test**. It may let the runner work that out from `base`
itself.

### The `related` answer

| Key | What it holds |
|---|---|
| `schema` | The number `1`. |
| `units` | The units reached; may be empty. |
| `errors` | A list of text messages; any entry makes the answer a failed one. |

### Each `related` unit

| Key | What it holds |
|---|---|
| `file` | Required. A file of the inventory, exactly as `list` gave it. |
| `project` | Its runner project, exactly as `list` gave it; left out when `list` gave none. |

A unit the inventory does not hold, a nonzero exit or a missing answer makes `related` a failed
answer, and the kernel records the full layer. An empty answer never means "nothing is affected"
on its own — the kernel decides that, from what the runner can and cannot see (SPEC-1035 rule 3).

## What `run` does

`run` executes **exactly** the manifest's `units` in one runner invocation where the runner takes
several files, and:

- makes the runner write its JUnit XML report to `report`, and its second report to
  `second_report` when that is not `null`;
- turns the runner's **own retries off** (the profile says how) — every retry is the kernel's;
- passes `project` to the runner when the manifest gives one;
- runs the units one at a time when `isolated` is `true`;
- runs only the named test cases of a unit that carries `cases` — a list of the case names your
  runner's own report gave the failed tests of that file on the first attempt (for pytest
  `<Class>::<name>` or `<name>`). Running the whole file instead is also correct: the kernel
  reads the report the same way, and a file reads passed when every case that ran passed. Match
  the names exactly; never turn them into a pattern that can match another test;
- exits with the runner's exit code: nonzero when a test failed.

The kernel reads the report against what it asked for. The report is dropped — and the layer's
full `command:` or its exit code decides — when a requested unit has no record or only skipped
ones, a unit appears that was not requested or appears twice, the report is missing, malformed or
older than the call, the second report is missing or not that runner's, a failure is recorded
that is not a test's own, the runner retried a test itself, or the exit code is nonzero while
every unit reads passed. A failed test on a requested unit is **not** a dropped report: it is that
unit's failure, and the kernel re-runs it alone.

## The report profiles

A profile says how one runner family's own report reads. `report_id` matters only when the name
in the report differs from what the profile derives.

| Profile | Runner | The report names a unit by | Without `report_id` the kernel looks for | Second report | Report names the runner project | Per-case rows | Own retries off | `related` diff |
|---|---|---|---|---|---|---|---|---|
| `vitest/1` | Vitest 4 and 5 | the suite `name` | the unit's `file` | Vitest's JSON report | no | yes | `--retry=0` | `merge-base` |
| `playwright/1` | Playwright | the suite `name` plus its `hostname` (the project) | the unit's `file` | Playwright's JSON report | yes | yes | `--retries=0` | `worktree` |
| `pytest/1` | pytest | the dotted module at the start of a test case's `classname` | the unit's `file` as a dotted module | none | no | yes | `no rerun plugin` | `kernel` |
| `script/1` | one script per file | the suite `name` | the unit's `file` | none | no | no | `one process per file, no retry loop` | `kernel` |

What `report_id` names, per profile:

- **`vitest/1`** — the suite name: the test file's path relative to Vitest's root directory,
  which is the directory of the Vitest config unless the config sets `root` itself. When that
  root is the repository root the name is the unit's own `file` and no `report_id` is needed;
  when it is `web/`, the unit `web/src/a.test.ts` has `report_id: src/a.test.ts`.
- **`playwright/1`** — the suite name: the spec's path relative to the config's root directory
  (usually its `testDir`). The unit `e2e/tests/login.spec.ts` has `report_id: login.spec.ts`. The
  runner project is read from the suite's `hostname`, so `report_id` never carries it.
- **`pytest/1`** — the module as pytest's report spells it: the path from pytest's root
  directory with dots for slashes and no `.py`. With pytest rooted at the repository root the
  kernel derives `tests.test_a` from `tests/test_a.py` by itself; with pytest rooted in `svc/`,
  the unit `svc/tests/test_a.py` has `report_id: tests.test_a`. A test class becomes part of the
  test case's identity, never of the unit. pytest picks its root directory from the nearest
  configuration file at or above where it starts, so a `pytest.ini` at the repository root
  changes every name for a suite kept in a sub-directory; the sample pins the root directory to
  its `RUNNER_DIR` setting so the names stay the ones that setting says.
- **`script/1`** — the suite name, which the adapter itself writes: one suite per file, named by
  the unit's `file`, holding one test case that carries a `failure` when the file exited nonzero.
  There are no per-case rows; the verdict is the file's.

The last column says whose diff a `related` answer speaks for: `kernel` — the adapter answers
from the manifest's `changed` list; `merge-base` — the runner diffs `<base>...HEAD` plus staged,
unstaged and untracked files; `worktree` — the runner compares the working tree with `<base>`,
untracked files included. The kernel works that set out with git and trusts no answer for a path
outside it.

## Checking your adapter

Run the layer the way the kernel does — `yitc-v2 task test --run` on a card in a worktree — and
read the layer's line in the output:

```
land(consumer): verify layer 'frontend' adapter report (vitest/1, first attempt): 118 unit(s) — 118 passed; report usable
```

- `report usable` — the kernel accepted the inventory and the report; per-file results now decide.
- ``adapter `list` is unusable for this run (<reason>)`` — fix what the reason names; the full
  `command:` decided this run.
- `rows are diagnostics only (void: <reasons>)` — the report was dropped for the reasons listed;
  the commonest is a `report_id` that does not match the name in the runner's report.

The void reason `unit-only-skipped` names a listed unit — a test file, within one runner project
where the runner has several — whose every test was skipped in this run; SPEC-1035 rule 4 drops
the report for it, and will on each run while the unit stays that way. Do not skip a whole file
from inside it: take the file out of what the layer runs for that project, in the runner's own
configuration, so that `list` no longer names the pair. Put it back when the file holds a test
that runs there.

The same record rides the layer's row on the `tests_passed` / `tests_failed` and `land_completed`
journal rows, under `adapter`.

## Making a layer narrow

> **Plainly.** On a layer that declares `selection: shadow`, the record of each run names the
> kernel's answer for that change. On most projects that answer is the whole layer nearly every
> time, and most of those answers come from what the project itself declared. This section says how
> to read the answer in your own rows and, for each name the answer can carry, which of your
> declarations to look at — or that there is none and the kernel is right.

This is a how-to, not a rule, and it adds none. It says in plain words what you are seeing when
your row carries an answer, names the rule that holds the conditions, and says where to look. The
rules it names:

- the ladder, its steps and their order — SPEC-1035 rule 6;
- what makes a changed path `unknown` — SPEC-1035 rule 3;
- what a trigger does — SPEC-1035 rule 7;
- when a layer is skipped whole, which changes run every layer and what a project may declare about
  that — SPEC-0152 rule 16;
- how to lay tests out so that a change reaches few of them — SPEC-0165 item 12.

Read each with `yitc-v2 graph query --kernel <id>`. A description here is of your row, in a
reader's words; the conditions are the rule's, and wherever this section and a rule differ, the
rule holds.

This section is about one number: how often your layer's ladder reaches its last answer. A
`shadow` layer already records it, and what `shadow` does with the answer is SPEC-1035 rule 8. The
modes in which the answer decides what runs are not part of that contract: they are the active
contract SPEC-1030's.

### Read your own rows first

The layer's row on every `tests_passed`, `tests_failed` and `land_completed` journal row carries
the adapter record, and its `selection` entry is the ladder's answer for that run:

| Field | What it tells you |
|---|---|
| `decision` | `full` — the whole layer. `units` — the ladder reached its last answer. |
| `rung`, `reason` | Which step of the ladder answered, and the name of the answer. The tables below are keyed by `reason`. `rung` is `null` on an answer given outside the lettered steps. |
| `changed`, `eligible` | How many paths the change holds, and how many of them this layer's `subject_globs` admit. |
| `unknown`, `unknown_more` | On `unknown-path`: the first of those paths, each with its `why`, and the count of the rest. |
| `related`, `related_reason` | Whether `related` was asked and how it ended, and the cause of a failed one. |
| `units_total`, `would_run`, `would_omit` | The size of the inventory; on `units`, the files the ladder would run and the files it would leave out. |

`yitc-v2 journal query --type land_completed --limit 30 --json` prints your last thirty lands, one
JSON object a line. The run itself says the same in one line of its output:

```
land(consumer): verify layer 'frontend' shadow selection (recorded, never acted on — the full layer ran): rung (d) — unknown-path: the full layer
```

Count the `reason` values over those lands and start with the commonest. What clearing one answer
earns while another still stands is the closing sentence of SPEC-1035 rule 6.

A record that answers on rung (a) lists the paths of your change that produced the answer in
`fired_paths` — at most 20 of them, with the count of the rest in `fired_paths_more`; SPEC-0025
registers both. A record with neither key was written before the kernel recorded them, or answers
for a reason that has no path: for such a land, list the change yourself — `git diff --name-only
<base> <the landed commit>`, with the `base` the record carries. Hold the paths against «The two
commonest answers» below.

### Each full-layer answer

The second column is the step of the ladder the answer belongs to. The third says what you are
seeing in your row, and the fourth names the rule that holds the conditions.

| `reason` | Rung | What you are seeing | The rule | What to look at |
|---|---|---|---|---|
| `no-base` | none | The run had no commit to compare your change with, so it had no list of changed paths. | SPEC-0152 rule 16, its fail-closed edges | Nothing to declare; the kernel is right. |
| `diff-unresolvable` | none | The run could not read the list of paths your change holds. The recorded reason carries the error after a colon. | SPEC-0152 rule 16, its fail-closed edges | Nothing to declare; the kernel is right. A repeat is a fault to report, not a setting. |
| `no-diff` | none | The change the run compared holds no path. | SPEC-1035 rule 6, its default | Nothing to declare; the kernel is right. |
| `no-verify-globs` | (a) | The kernel's own verify-infrastructure set read as empty on this run. No layer row shows this today. | SPEC-0152 rule 16, which names that set | Nothing to declare. |
| `verify-implementation-touch` | (a) | Your change holds a path of the verify infrastructure the kernel names for every project: a file under the root `tests/`, or `yitc-ops.yaml`. A file under your root `bin/` is not such a path. Every layer of the run carries the same answer. | SPEC-0152 rule 16; SPEC-1035 rule 6 (a) | Which path it was — the record's `fired_paths`; what to do about it — «The two commonest answers» below. |
| `declared-check-surface` | (a) | Your change holds a file that one of your layers' `command:` names, a path your `verify.infra_globs` lists, or a file under an adapter's `sources:` entry kept under your root `bin/`. Every layer of the run carries the same answer. | SPEC-0152 rule 16, its `verify.infra_globs` paragraph | Which path it was — the record's `fired_paths`. What your cards edit there — «The two commonest answers» below. For an edit of the checks themselves the kernel is right. |
| `owned-test-ownership` | (a) | A changed test file was taken as particular layers' own, and the layer list the run held did not bear that out. Every layer of the run carries the same answer. | SPEC-0152 rule 16, its ownership-aware paragraph | Nothing to declare; the kernel is right. Which test files they were — the record's `fired_paths`. A repeat is a fault to report. |
| `adapter-sources` | (a) | Your change holds a path under this layer's `sources:`. | SPEC-1035 rules 1 and 6 (a) | Which path it was — the record's `fired_paths`. `sources:` — it lists what implements the adapter and the runner configuration, and for a change to one of those the kernel is right. Keep out of those files anything your cards edit for another reason. |
| `dependency-manifest` | (b) | Your change holds a dependency manifest, a lockfile, or a toolchain or browser version pin. | SPEC-1035 rule 6 (b) | Nothing to declare; the kernel is right. |
| `trigger-full` | (c) | One of your own `triggers:` entries that names the full layer covers a path of your change. | SPEC-1035 rules 6 (c) and 7 | That `triggers:` entry: whether it can name the `units:` that read those files instead. |
| `trigger-unit-not-listed` | (c) | A `triggers:` entry that covers a path of your change names a test file this run's inventory does not hold. | SPEC-1035 rules 6 (c) and 7 | The `units:` of that `triggers:` entry — a test file renamed, moved or deleted since it was written. |
| `no-inventory` | none | The run had no usable inventory from `list` for this layer. | SPEC-1035 rule 3, its safe fallback | The layer's line in the run's output — «Checking your adapter» above. |
| `unrevealable-void` | none | The layer's report profile names a kind of failed run its report cannot show. No profile of this page does today. | SPEC-1035 rule 4, its limit clause | Nothing to declare. |
| `related-absent` | (d) | The adapter declares no `related`. | SPEC-1035 rule 3, its safe fallback; rule 6 (d) | The adapter's `related` key: whether your runner can name the tests a change reaches without running them — the fourth habit of SPEC-0165 item 12 (a). |
| `unknown-path` | (d) | At least one changed path this layer's `subject_globs` admit is `unknown`. The record lists them. | SPEC-1035 rules 3 and 6 (d) | The reason each listed path carries — «The `why` of an unknown path» below. |
| `related-failed` | (d) | `related` was asked and gave no usable answer; `related_reason` names the cause. | SPEC-1035 rule 6 (d) | Your `related` command — «What `related` answers» above. |
| `related-timed-out` | (d) | `related` was asked and did not finish in the time the run gave it. | SPEC-1035 rule 6 (d) | How long your `related` takes, and the layer's `timeout:`. |
| `browser-layer-change` | (e) | On a layer that covers the `e2e` class: your change holds application, server or asset code for which the adapter declares no relation to its test files. | SPEC-1035 rule 6 (e) | `triggers:` that map application paths to the test files exercising them; and whether the layer should be split by product area — SPEC-0165 item 12 (b). |

One more full-layer record is not the ladder's answer: `selection-error`, a fault in the
selection itself. Its `error` field carries the cause, and it is a fault to report.

### The `why` of an unknown path

Each `unknown` path in the record carries a `why`. The columns read as in the table above.

| `why` | What you are seeing | The rule | What to look at |
|---|---|---|---|
| `outside-modelled` | The path is of a kind your `modelled:` does not list, and no `triggers:` entry names it. | SPEC-1035 rule 3 (ii); rule 7 | Three declarations, in this order. First the layer's `subject_globs`: whether the layer's tests read that path at all. Then `triggers:`: an entry that names the test files reading it. Last `modelled:`: whether the runner's dependency tracking follows that kind of file. |
| `deleted-or-renamed` | The path is no longer a file of the tree the run verified. | SPEC-1035 rule 3 (i) | Nothing to declare; the kernel is right. |
| `not-in-runner-diff` | The runner's own diff — the form its profile names in the last column of the profiles table — does not hold the path. | SPEC-1035 rule 3 (iii) | Nothing to declare; the kernel is right. |
| `runner-diff-unreadable` | The run could not read the runner's own diff. | SPEC-1035 rule 3 (iii) | Nothing to declare. A repeat is a fault to report. |

### The two commonest answers

Measured on the two projects that recorded a shadow selection before this section was written:
78 lands, 141 layer decisions, 136 of them the full layer. One project answered
`verify-implementation-touch` or `declared-check-surface` on 74 of its 101 decisions; the other
answered `unknown-path` on 36 of its 40. Replaying those lands gave five causes. Four trace to
the project's own declarations. The fifth was the kernel's own set, which has since changed:
cause 4 says what it is now.

1. **A per-file list inside the script a layer's `command:` names** — `declared-check-surface`.
   The script listed its test files one by one, so every card that added a test added a line to
   it. A script that finds its files by a pattern needs no edit for a new test.
2. **A per-file list inside `subject_globs`** — `verify-implementation-touch`, through
   `yitc-ops.yaml`. The globs named files one by one, so every card that added a file edited the
   layer declarations. What an edit of the carrier means for the run, and for the test files
   changed beside it, is SPEC-0152 rule 16 — its section-aware and ownership-aware paragraphs.
   Globs written as a directory or a name pattern already admit the next file; how wide to write
   them is the third habit of SPEC-0165 item 12 (a).
3. **Files under `tests/` that the declarations give to no one layer** —
   `verify-implementation-touch`. In the measured project they were fixtures, and a test file
   changed in the same card as the layer declarations. Which test files are one layer's own, and
   how a project keeps a shared one on the full run, is the ownership-aware paragraph of
   SPEC-0152 rule 16.
4. **Product or operations scripts kept under the root `bin/`** — `verify-implementation-touch`
   on the measured lands, and no longer: your root `bin/` is not part of the kernel's set
   (SPEC-0152 rule 16), so such a file is judged by each layer's `subject_globs` like any other
   path. To keep a root `bin/` helper on the full run, list it under `verify.infra_globs`. If a
   layer's tests exercise scripts kept under the root `bin/`, name those paths in that layer's
   `subject_globs`. A root `bin/` file your contract already names — the path in a layer's
   `command:`, an adapter's `sources:` entry — keeps the full run and answers
   `declared-check-surface`.
5. **Globs that admit what the runner does not place** — `unknown-path` with `outside-modelled`.
   A frontend layer whose `subject_globs` admitted backend tests, specs and operations notes; a
   one-script-per-file layer modelling `.py` whose globs admitted design files and frontend
   sources. The three declarations of the table above, in that order.

**What belongs in a card of its own.** Changing how a verify script finds its files, splitting a
layer: each changes what your verify does, so each is a card with its
own run and its own recorded answer. A wish for the kernel's own set to read differently is a
proposal to the kernel, not a declaration.

**Narrow on evidence.** Each declaration here trades width for trust. Which direction of a glob is
the unsound one is the third habit of SPEC-0165 item 12 (a); what an unlisted kind of file means
for a `related` answer is SPEC-1035 rule 3. Declare what the tests are known to read, and watch the
record's `disagreements` (SPEC-1035 rule 9).

## Limits worth knowing

- The report is checked for **consistency** with what was asked, nothing more: the adapter and
  the runner are both yours.
- A file argument is a filter for most runners, not an exact name. Where a filter can match a
  second file, the kernel sees a unit it did not ask for and drops the report — it fails toward
  the full layer, never toward a silent skip. Each sample states its own limit in its header.
- A sample does not check what its runner prints. When the runner prints something unexpected the
  script stops with an error or lists nothing, and either way the kernel runs the layer's full
  `command:`.
- `selection: shadow` and `credit: shadow` only record: under them the kernel skips no test
  file. `selection: deciding` and `credit: deciding` do leave test files unrun. A failure in
  such a file is not seen on that run and can reach `main`, and the full run before a deploy
  is yours to make (SPEC-1030 rule 7).
