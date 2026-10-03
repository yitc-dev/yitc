---
name: choosing-a-bound-tests-boundary
class: technique
sourced_from: SPEC-0076 §5/§6(a) (the bound-test contract this teaches, as amended) + the two-consumer trial of plan [[scenarios-as-executable-specs-bind-scenario-steps-]] (read-only provenance) — <project> (a UI step bound to a RENDER-WIRING test) and <project> (a server step bound to a DOMAIN-INVARIANT test), the auditor finding of the 2026-09-21 consult (a service test bound to a render fault proves nothing about the render), and <project> (the load/compute split, closed 2026-09-22 — §0's worked example). SPEC-0090 travel test PASSED — both consumers needed it; each consumer's runner mechanics stay in its own `lessons/`.
applies_to: any project binding a scenario step to a test — the §5 test anchor of SPEC-0076 (a step's `covers` naming `tests/<file>#<fn|label>` beside its production anchor). Read it BEFORE writing or choosing the test a step binds, and when a step "cannot be tested without the whole stack". Provider- and runner-neutral — tool names below are examples, never required steps.
cites:
  - SPEC-0076
  - SPEC-0090
  - scenarios-as-executable-specs-bind-scenario-steps-
---

# Choosing a bound test's boundary

SPEC-0076 §5 says WHAT a bound test is (point-first, at the step's own observable boundary,
reddened by a step-specific fault input, named additively beside the production anchor) and §6(a)
why it matters (it is the regression obligation's producer). This pattern is the HOW: how to make
that boundary exist, find it, and prove the test sits on it. It restates no rule — on any conflict
SPEC-0076 wins.

## §0 — Shape the function so the boundary EXISTS

A step can only bind a cheap, precise test if the code has a seam at the step's outcome. The seam
is made by one split:

- **A function either LOADS or DECIDES — never both.**
  - A **loader** takes the outside world in (DB session, HTTP client, file, clock) and hands back
    plain rows/values. It makes **no decisions**: no filtering by business meaning, no ownership,
    no attribution, no "which one counts".
  - A **decider / computer** takes plain rows in and returns a result. It holds **no session and
    does no IO**, so it runs in memory in milliseconds.
- **The decision lives in compute, never in the loader** — above all an ownership / attribution
  decision ("whose is this", "who gets credit"). A loader that decides hides the decision behind
  the IO, so only a full-stack test can see it; that is where the 2026-09-11 <project> defect sat.
- **ONE endpoint / wiring test per path** proves the loader and the decider are connected (the
  request reaches the loader, the result reaches the response). **The logic steps bind in-memory
  tests** of the decider, one per step outcome.

Smell: a step whose only possible test needs the database (or the whole running stack) although
the step's outcome is a computed figure — the computation is trapped inside a loader.

**Worked example — <project> (the load/compute split; closed 2026-09-22, these figures are
its closure record).** Before: 4 bound tests, all on the stack, 27.7 s wall. After: 2 tests on the
stack (21.0 s) + 10 in-memory tests (2.6 s); 3 of the scenario's 5 steps are fully stack-free,
step 5 is split (wiring on the stack, logic in memory), step 1 stays an endpoint test on the DB.
More assertions, less stack, and each step's red now names that step. The closure note also
re-measured at a comparable host load (load1 ≈ 5): the stack tests went 18.25 s → 17.40 s wall
(pytest 0.54 s → 0.49 s), and the 10 compute tests ran in 0.08 s of pytest time with no DB fixture.

## §1 — Point-first: find before you write

Before writing a test for a step, search the suites for one that already asserts the step's
**user-visible outcome** (the text a user sees, the figure they get, the status they reach) —
e.g. grep for the outcome's literal string, the field name, the route. If one exists, bind it.
Write a new test only when none asserts that outcome. A test that merely exercises the same code
without asserting the outcome does not count.

## §2 — The boundary rule: bind at the step's OWN observable boundary

| The step is… | Bind… | Example harness (illustrative only) |
|---|---|---|
| a UI step (a screen shows / enables / hides something) | a **render / component test** that mounts the screen and asserts what renders — render WIRING | a component-test runner such as vitest + a DOM testing library |
| a server step (a figure, a state, an ownership outcome) | an **API / service test with a fixture** — or, after §0, an in-memory test of the decider — asserting the DOMAIN INVARIANT | a unit runner such as pytest, with the fixture as plain rows |

**Never bind a service test to a render fault.** If the step fails because the screen renders the
wrong thing, a service test stays green through that fault — it proves the data, not the render
(the 2026-09-21 consult finding). The reverse holds too: a render test that mocks the figure away
does not prove the figure.

## §3 — One step-specific fault input per bound test

Before the test counts, show it RED on a fault input **specific to this step** — break exactly the
behaviour the step narrates (flip the attribution, drop the rendered label, shift the boundary
value) and watch it fail. Then:

- the red must **name the step's outcome** (the assertion message or test name says what the user
  would have seen wrong), not a generic "expected X got Y" three layers down;
- one fault input per bound test — a test that reddens on everything distinguishes nothing, and a
  test that reddens only on a crash proves no outcome.

If no step-specific fault makes it fail, it is not bound to this step — go back to §2 (wrong
boundary) or §0 (no seam yet).

## §4 — Anchors are additive

- The test anchor sits **beside** the production anchor in the step's `covers`; the production
  anchor stays (impact discovery keys on it, execution on the test anchor — SPEC-0076 §5).
- Name the test function or label **in full**, as written in the test file.
- A production anchor found wrong is corrected by **adding** the right one beside it, never by
  replacing it, so the step is never left unanchored mid-change.

## What stays out

Each consumer's runner mechanics — how it starts its stack, how it selects node ids, its scripts —
live in that consumer's `lessons/` (SPEC-0090), never here. The selection rule (diff ∩ production
anchors → those steps' test anchors) is SPEC-0076's, and execution stays consumer-local.
