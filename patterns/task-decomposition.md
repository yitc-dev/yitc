---
name: task-decomposition
class: discipline
status: retired
retired: '2026-06-02 — absorbed into <workshop-spec> (single normative home); removal-trigger shipped'
sourced_from: ad-hoc decomposition-heuristic audit 2026-06-01 (decisions/adhoc-task-decomposition-heuristic-audit.yaml) + V2 doc-model-rework / Phase-1 audit-pre churn 2026-06-01
applies_to: RETIRED — see <workshop-spec>.
---

# Task Decomposition — RETIRED (absorbed into <workshop-spec>)

> **This pattern is retired.** Its doctrine — *decompose by ONE provable claim/invariant per
> accept-unit (defined against the audit-pre gate), not by line count* — now lives single-sourced in
> **`specs/<workshop-spec>`** (`### A. Decomposition discipline`), the normative home, alongside the
> mechanized `plan check` structural pre-pass that enforces the related deferral-tracking rule.
> This file is a tombstone pointer so historical `from:` / plan citations to the path stay valid
> (retirement-procedure.md Step 4 — content moved, path preserved).

See **<workshop-spec>** for: the one-claim-per-accept-unit rule, the audit-pre RED red-flag catalog
(>1 claim / contradicts-accepted / under-specified), and the execution-readiness rule (name the
aligned artifact + the proof path). Was grounded in the V2 audit-pre churn (each `passes: 2`); prior-art (analogy only): INVEST, ADR/PEP one-decision-per-document,
vertical-slice decomposition.
