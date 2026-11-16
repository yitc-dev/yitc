---
name: hermetic-in-time-suite-latency-triage
class: technique
sourced_from: boomrocket X-0431 / (declared-hermetic backend suite hid a ~19.5s-per-test celery result-backend connect-retry stall — 7 tests ≈ 136s of a 145s file — found only by a faulthandler stack dump; owner-authorized cross-intake to the kernel 2026-07-16)
applies_to: any project whose test suite is DECLARED hermetic yet whose per-test durations are suspiciously uniform, or whose land/CI wall-clock is dominated by one test layer that grows with the suite
---

# Hermetic-in-TIME suite-latency triage (durations → uniform-cluster → faulthandler)

## Problem

A suite declared **hermetic** (SPEC-0152 rules 10/16 — no shared data, `land` runs it on the live
tree with no network) can still be **non-hermetic in TIME**: a prod code path under test fires an
external infrastructure call (a broker `.delay`, a cache client, a third-party HTTP client) that the
hermetic container does NOT provide, and the test then **waits out that dependency's connect/retry
timeout** — a hidden per-test stall. Nothing in DATA-hermeticity notices it. The stall is easy to miss
precisely because the OBVIOUS externals are already mocked: it takes only ONE unmocked infra call on
ONE prod path to silently set a whole suite's per-test floor, and that floor survives suite growth and
pins the parallel wall-clock (`--dist loadfile` cannot split a single slow file across workers).

This is the diagnostic + fix recipe for the doctrine in **SPEC-0152 §25** (hermetic-class admission —
a class declared hermetic is hermetic in TIME). It is the hermetic-in-TIME half assumed by
`patterns/consumer-suite-parallelization.md`'s "hermetic first, parallel second" precondition: verify
time-hermeticity with THIS recipe before reaching for pytest-xdist.

## The diagnostic signature

**Uniform per-test durations clustering near a configured timeout value (~15-20s) = a hidden external
wait.** Real test work has a spread of durations; a cluster of tests all taking almost exactly the
same 15-20s is not compute — it is the same connect/retry timeout being waited out, once per test. The
value pins the culprit: it matches the external client's default connect + retry budget, not anything
in your code.

## The recipe

1. **Profile — where does the wall-clock go?**
   ```
   pytest --durations=25 <suite>
   ```
   Read the slowest N. A HEALTHY suite shows a spread. The SIGNATURE is a block of tests at a
   near-identical duration clustered around a round timeout-shaped number.

2. **Confirm — what is the process actually doing during the stall?** Dump the stack at a threshold
   just below the observed per-test time so the dump lands mid-wait:
   ```
   pytest -o faulthandler_timeout=10 <one-slow-test>
   ```
   The stack trace names the exact frame — a broker/result-backend `connect` / `retry` / `sleep`, a
   socket `getaddrinfo`, an HTTP client `connect` — proving it is an external wait, not compute. This
   is the single decisive step: durations SUGGEST, the stack dump PROVES.

3. **Fix — make the external eager, stubbed, or fail-FAST** (SPEC-0152 §25 admission criterion):
   - run the work **eager / in-process** in the test env (e.g. celery `task_always_eager = True`, so
     `.delay` runs inline and never touches a broker);
   - **stub / mock** the client (as the obvious externals — email, bot APIs — already were);
   - or, where a real call is intended but the external is absent in test, configure a **short connect
     timeout in the test environment** so an absent external errors in milliseconds instead of waiting
     out a full ~15-20s connect/retry budget.

   Waiting out a real connect timeout to an absent external is a doctrine VIOLATION, not a slow test —
   fix the hermeticity, do not just raise the land timeout (that treats the symptom and lets the floor
   keep growing).

## Worked example — boomrocket

boomrocket's backend suite was declared hermetic; PuzzleBot and email were mocked. But prod endpoints
fire celery `.delay`, the hermetic container has no Redis, and the celery **result-backend retried
~19.5s per call** waiting for the absent broker. `pytest --durations` showed 7 tests clustered at
~19.5s (≈136s of a 145s file); `pytest -o faulthandler_timeout=10` dumped the stack mid-wait onto the
celery result-backend retry frame — the confirmation. The fix : celery `task_always_eager` in
the test env + a short test-env broker connect timeout. Per-test time dropped from ~19.5s to
negligible, unpinning the whole suite's parallel floor.

## See also

- **SPEC-0152 §25** — the hermetic-class admission criterion this recipe serves (the authoring
  doctrine; report-only, no gate).
- **`patterns/consumer-suite-parallelization.md`** — the composing lever: once a layer is hermetic in
  TIME, parallelize it (pytest-xdist) to cut the wall-clock of the lands that DO run it.
- **`patterns/test-isolation-strategies.md`** — the DATA-hermeticity companion (isolate DB state).
