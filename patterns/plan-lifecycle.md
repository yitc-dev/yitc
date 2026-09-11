---
name: plan-lifecycle
class: discipline
status: retired
retired: '2026-06-05 — retired into specs/SPEC-0034 (single normative home, P5) by; AGENTS/GRAPH refs repointed'
sourced_from: decisions/-draft-idea-lifecycle.yaml (renamed draft→plan + accept-gate by) + owner design conversation 2026-05-29
applies_to: RETIRED — see specs/SPEC-0034 (the single normative home for the plan lifecycle).
---

# Plan / Idea Lifecycle — RETIRED into SPEC-0034

> **This pattern is retired.** Its normative content — the plan FSM + per-stage mechanics,
> the plan↔spec linkage chain (born → activate → finalize), the mandatory big-plan check at the
> `executing`-gate, the sibling `idea` class, the file shape, and the planning-hygiene anti-patterns —
> now lives single-home in **`specs/SPEC-0034`** "Plan lifecycle" (CHARTER §P5 — one normative home).
> Fetch it: `bin/yitc-v2 graph query SPEC-0034`. The plan-lifecycle SKELETON is in `LIFECYCLE.md`
> §Plan lifecycle; the per-stage DETAIL is delivered at `plan stage <NAME>` entry (the
> `plan-stage-entry:` axis), mirroring the task stage-entry model.
>
> The deferral-as-prose standing rule — any deferral of a plan part / spec-body half MUST be a
> **tracked task** (parked/blocked, with a `return_trigger`), never prose — remains homed in
> **`specs/SPEC-0040`** (supersedes SPEC-0037, ex-SPEC-0012), alongside its mechanized `plan check` structural pre-pass.
>
> This file is a tombstone pointer so historical `from:` / `sourced_from` / plan citations to the path
> stay valid as a redirect (retirement-procedure.md Step 4 — content moved, path preserved). It holds
> zero normative content.
