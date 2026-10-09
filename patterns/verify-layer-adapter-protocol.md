---
name: verify-layer-adapter-protocol
class: runbook
sourced_from: public proposal 60 on the release mirror (an adopter turned the adapter on for six Playwright layers and had to read engine source to write the project script). The protocol stated here is read off the engine's adapter pass; the contract it serves is SPEC-1006.
applies_to: writing the project-owned script behind a verify layer's `adapter:` block — what the kernel hands it, what it has to answer, and one sample to copy per report profile
cites:
  - SPEC-1006
  - SPEC-0152
---

# The verify-layer adapter protocol — and a sample adapter per runner

> **Plainly.** A verify layer normally tells the kernel one thing: its command passed or failed.
> An **adapter** is a small script in *your* repository that lets the kernel see the layer's
> tests file by file — list them, run exactly the ones it names, and report each one. This page
> states everything that script and the kernel say to each other, and points at four samples you
> can copy. What the kernel then *does* with the per-file results — re-run a failed file alone,
> count flaky files, record what a change would reach — is the contract, SPEC-1006
> (`yitc-v2 graph query --kernel SPEC-1006`); none of it is restated here.

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
| `selection` | `off` (default) or `shadow`. `shadow` records what the change would select; the full layer still runs. |
| `credit` | `off` (default) or `shadow`. `shadow` records which passes a fix attempt could reuse; the full layer still runs. |
| `rescue` | `on` (default) or `off`. Whether a file that fails and then passes alone keeps the verdict green. |

What each key *means* for the verdict is SPEC-1006 rule 1 and the rules it names.

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
| `units` | every call | On `run`: the units to execute, each as `list` gave it, or `null` when the layer has no `list` — then run everything the layer runs. On `related`: the whole inventory. On `list`: `null`. |
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
on its own — the kernel decides that, from what the runner can and cannot see (SPEC-1006 rule 3).

## What `run` does

`run` executes **exactly** the manifest's `units` in one runner invocation where the runner takes
several files, and:

- makes the runner write its JUnit XML report to `report`, and its second report to
  `second_report` when that is not `null`;
- turns the runner's **own retries off** (the profile says how) — every retry is the kernel's;
- passes `project` to the runner when the manifest gives one;
- runs the units one at a time when `isolated` is `true`;
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

The same record rides the layer's row on the `tests_passed` / `tests_failed` and `land_completed`
journal rows, under `adapter`.

## Limits worth knowing

- The report is checked for **consistency** with what was asked, nothing more: the adapter and
  the runner are both yours.
- A file argument is a filter for most runners, not an exact name. Where a filter can match a
  second file, the kernel sees a unit it did not ask for and drops the report — it fails toward
  the full layer, never toward a silent skip. Each sample states its own limit in its header.
- A sample does not check what its runner prints. When the runner prints something unexpected the
  script stops with an error or lists nothing, and either way the kernel runs the layer's full
  `command:`.
- `selection: shadow` and `credit: shadow` only record. Nothing in this protocol makes the
  kernel skip a test file.
