---
name: decision-log-format
class: discipline
sourced_from: <host-home>/knowledge/patterns/decision-log-format.md
applies_to: any project where architectural/product decisions accumulate and need to be retrievable months later; pair with task tracker so backlog items can cite D-XXX
---

# Two-Tier Decision Tracking

## Problem

Decisions decay into chat scrollback. A month later nobody remembers what was decided, why an alternative was rejected, or who raised the question. A single log either becomes too verbose for operational use or too terse for retrospective context.

## Solution

Two files with different jobs:

| File | Purpose | Audience | Record lifecycle |
|---|---|---|---|
| `DECISIONS.md` | operational ledger — pending + recently resolved | PM / developer (daily) | new on top; old slides down |
| `docs/decisions-log.md` | chronicle — full context, alternatives, rationale | retrospective, onboarding, audit | append-only, never deleted |

> Note: in YITC v2 itself, this two-tier pattern is collapsed into one per-decision YAML file (`decisions/D-XXXX.yaml`) per CHARTER Principle 5 (single source of truth). The pattern below is the **portable form** for other projects where a two-tier markdown ledger fits the team workflow better than per-entry YAML.

## Example

**`DECISIONS.md` (operational):**

```markdown
# Project — Owner Decisions

## Awaiting decision

### [D-XXX] Short question title
- **Date:** YYYY-MM-DD
- **Source:** who raised it
- **Context:** 2-3 sentences — the problem
- **Options:**
  1. Option A — pros / cons
  2. Option B — pros / cons
- **Recommendation:** what the team proposes

---

## Resolved

### [D-XXX] Short title
- **Date:** YYYY-MM-DD, resolved YYYY-MM-DD
- **Source:** owner / team
- **Context:** the problem
- **Decision:** what was chosen + key details
- **Rejected:**
  - Option A (reason)
  - Option B (reason)
```

**`docs/decisions-log.md` (chronicle):**

```markdown
### YYYY-MM-DD — D-XXX: Decision title

**Context:** extended description — why the question came up,
what data was available, what was already tried.

**Decision:**
- What was chosen (implementation details)
- Linked tasks (B-XXX)

**Implementation:** B-XXX

---
```

## Anti-pattern

- One mega-log only — scanning «what's pending» drowns in historical entries
- Operational ledger only — a year later you cannot reconstruct **why** an alternative was rejected, so the same question gets re-litigated
- Reuse a decision number even when the prior decision was withdrawn — breaks cross-references from code and backlog
- Strip the «rejected» section on resolution — the rejection rationale IS the value; without it the team relitigates the same alternatives later
- Delete records after decision is reversed — instead, write a new dated entry citing the old one

## Rules

- Decision numbers are immutable — never reuse, even on withdrawal
- «We decided not to do this» IS a decision — record it
- Source field mandatory: «owner», «team», «audit» — supports retrospective
- Reversal = new dated entry citing the prior decision

## Cites

- v1 source: a production CMS project with 52+ entries in the operational ledger and matching chronicle
- Related (cross-pattern): for a pure-YAML alternative, see V2 CHARTER §Decision lifecycle (PEP-shape per-entry YAML)
