---
name: test-isolation-strategies
class: technique
sourced_from: <host-home>/knowledge/patterns/test-isolation-strategies.md
applies_to: async SQLAlchemy / FastAPI projects choosing how to isolate test database state between tests
---

# Test Isolation Strategies (async SQLAlchemy)

## Problem

Async tests with a real database must be isolated from each other — a row created by test A must not be visible to test B. The three available strategies have different speed/correctness tradeoffs; picking the wrong one wastes hours either in test runtime or in debugging cross-test pollution.

## Solution

Three named strategies, choose by scale + correctness need:

### 1. Rollback

- Engine created once at session scope
- Each test runs inside a transaction that's rolled back at teardown
- **+** Fast, minimal overhead
- **−** Doesn't catch commit-related bugs (autoflush, post-commit hooks)

### 2. Recreate

- Engine created per test
- `create_all` / `drop_all` for each test
- **+** Total isolation, mirrors production deploy
- **−** Slow — 5-10× the rollback strategy

### 3. Savepoint

- Outer transaction begins at session; each test opens a nested savepoint
- `commit` is intercepted to flush rather than commit
- **+** Catches commit-path bugs while staying fast
- **−** Requires monkey-patching `Session.commit`

## Example

**Recommendation matrix:**

| Project size | Need commit-path correctness? | Strategy |
|---|---|---|
| < 100 tests | No | Rollback |
| < 100 tests | Yes | Savepoint |
| > 100 tests | Yes | Savepoint |
| Strict prod-parity | Yes | Recreate |

Reusable fixtures library covers all three strategies + an HTTP client factory + event-loop fixture: pair with whatever async-test-runner the project already uses.

## Anti-pattern

- Mix strategies across modules — tests inherit different isolation semantics, debugging becomes guesswork
- Skip isolation entirely («just truncate at start of suite») — parallel test runners are unsafe; single-runner builds get slow as data accumulates
- Recreate strategy by default — wastes minutes per CI run for no real benefit under 100 tests

## Process-global leakage when standalone-script tests run under one-process pytest

When test files are written as STANDALONE scripts (`python3 tests/test_x.py` — each its own process)
but ALSO run together under `pytest tests/` (one interpreter), any PROCESS-GLOBAL a test leaks
(an `os.environ` key, the cwd) survives into every test that runs after it → the full run becomes
order-DEPENDENT (passes in isolation, fails in suite, different failure set per ordering).

**Diagnose empirically, don't theorize.** Run `pytest tests/ -x` to get the FIRST failing test and
WHY — that one stderr line names the leaked seam (here: `YITC_ALLOW_MAIN_WRITE` popped by a sibling
refusal test → a later test's main-write was refused). Confirm order-independence with TWO orderings
(default + reversed file order, or pytest-randomly two seeds) both exit 0.

**Fix at the root with ONE autouse fixture, not N edits.** A single `tests/conftest.py` autouse
fixture that snapshots `dict(os.environ)` + `os.getcwd` and restores them on teardown
(`os.environ.clear; os.environ.update(saved)` — undoes both leaked SETs and leaked POPs) fixes the
whole class at once. This beat editing 57 files that each leaked via a module-top
`os.environ.setdefault` (CHARTER §Principle 1 — minimum surface). A `conftest.py` is inert to the
standalone `python3 tests/test_x.py` path, so it adds no regression there.

**What does NOT need this:** module-globals on a per-file-loaded module instance
(`importlib.util.module_from_spec`, never inserted into `sys.modules`) are private to that file and
cannot cross to a sibling — only genuinely process-wide seams (env + cwd) leak. Don't over-sandbox
state that is already per-file. (Prior-art: E-0023 / fixed two files by hand; generalized.)

## Cites

- v1 source: distilled from three projects' `conftest.py` (one production CMS, one production data-ingest, one scraping tool)
- Related: idempotent seed fixtures (use `Session.merge` + fixed UUIDs) for shared baseline data
- / E-0023 / ideas/test-fixture-env-hermeticity-broader-sweep.md — process-global env/cwd leakage section above
