---
name: concurrency-gate-inert-skip
class: technique
sourced_from: plan speed-up-land-under-concurrency-inert-retry-re-ver (realized 2026-06-09) + SPEC-0064 (inert-path classifier) + SPEC-0065 (inert-retry re-verify skip) — distilled retrospectively as the FIRST trial run of plan systematic-reusable-craft-lesson-capture-at-closur (Vehicle 3, SPEC-0089)
applies_to: speeding up a MANDATORY heavy verify/gate (seconds-to-minutes) that runs OUTSIDE the integration lock under optimistic-concurrency retries — `land`-style integration, CI-merge gates, any "re-check then fast-forward" loop where concurrent writers thrash the gate. Read at Stage-1 Analysis BEFORE adding a skip/cache to a slow concurrent gate.
---

# Pattern: speeding up a heavy concurrent gate by an OBSERVABILITY-based inert skip

> Distilled from the `land` concurrency speedup (measured worst-case 457s vs ~96s single-verify on 32
> cores). The reusable craft is NOT "cache the verify" — it is the SAFE CONDITION for skipping it.

## Problem

A mandatory heavy gate (a full test/verify run) executed OUTSIDE the integration lock under optimistic
concurrency THRASHES: while it runs (~96s), `main` advances, so the retry re-runs the FULL gate, up to
the retry cap — worst-case N× the single-run cost. Backoff is trivial against a multi-second gate
window. Naively skipping the re-run is unsafe; the hard part is stating WHEN a skip is sound.

## Solution

1. **Classify the FINAL merged-tree delta** (the diff about to fast-forward), NOT the original change —
   `inert | observable`. Skip the heavy re-run ONLY for an `inert` delta; an `observable` delta keeps
   the FULL gate. **Fail closed:** anything not provably inert is observable.
2. **The safe condition is OBSERVABILITY, narrower than "doesn't touch code/tests".** Two
   independently-verified changes can INTERACT, so the test is: does the merged tree differ ONLY in
   paths the verification environment cannot OBSERVE? Anything influencing **test discovery, imports,
   env/config, generated fixtures, repo-root behavior, or the verification checkout shape is
   RUN-forcing.** Carry a small **proven-inert allowlist** (pure data artifacts — e.g. task/decision/
   plan YAML, the journal, the derived graph index) + everything else observable.
3. **ONE classifier authority.** Exactly one helper produces the inert verdict + reason taxonomy on the
   final-tree delta; every skip site CONSUMES it — never a second "inert" encoding per call-site
   (verify a "predicate-authority" check that all consumers call the one helper).
4. **Never a silent skip.** Record `skipped(reason)` on the gate's completion telemetry, so every skip
   is journal-visible and auditable.
5. **Skip ONLY the heavy leg.** The cheap integration steps (state union, index rebuild/validation, the
   fast-forward) still run on the inert path — the skip removes only the expensive re-verify.

## Example

`land` under concurrency: the optimistic retry re-merges; if the final delta is allowlist-only
(`tasks/ decisions/ plans/ events.jsonl graph/`) the retry SKIPS re-verify and ff's, recording
`reverify_skipped` on `land_completed`; a delta pulling in `bin/ tests/ specs/ *.md` RE-RUNS the full
verify. Inert retries collapse toward the single ~96s; observable retries deliberately keep the safe
multi-verify path.

## Anti-pattern

- **Classifying by "the tests don't read this file" instead of by OBSERVABILITY** — misses that two
  independently-green changes can interact once merged; the skip must be on the merged-tree delta.
- **Two encodings of "inert"** (one per skip site) — they drift; one becomes unsafe silently.
- **A silent skip** with no telemetry — a wrong skip is then invisible until a bad merge reaches main.
- **Allowlisting an "almost data" path** that actually steers discovery/imports/fixtures/repo-root —
  fail closed instead; add to the allowlist only with a proof of non-observability.

## Cites

- `SPEC-0064` (inert-path classifier) · `SPEC-0065` (inert-retry re-verify skip) — the code-backed home.
- plan `speed-up-land-under-concurrency-inert-retry-re-ver` — the realized work this is distilled from.
- `SPEC-0089` — the closure/realize reflection discipline that produced this entry (its first trial run).
