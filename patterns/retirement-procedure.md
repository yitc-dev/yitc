---
name: retirement-procedure
class: discipline
sourced_from: owner-directive 2026-05-29 ("let's make documentation on analyzing what to delete plus a procedure — warning, disabling, analysis, deletion; manual-first, automate as we gain experience") + PEP 387 (Python deprecation / backwards-compat policy — external prior-art) reverse-mapping (candidate detector)
applies_to: removing dead weight — a rule / pattern / handbook section / CLI verb or code obligation / a superseded decision or spec. Run during the weekly Review audit when flags candidates, or whenever CHARTER §1 F3 «what gets removed?» surfaces. Manual-first.
---

# Retirement Procedure — orderly removal of dead weight

> Discipline pattern (manual-first). V2's **anti-accretion immune system**: nothing rots forever
> in limbo, nothing vanishes abruptly. PEP 387 analog. NOT a gate — informs, not enforces.

## Problem

V1 accreted to 95 gates / 60 hooks / 22 DPs because dead weight was never removed — there was no
orderly disposal. V2 has a *detector* for dead weight ( reverse-mapping flags «not cited in
30d») but no *process* to retire a candidate → either candidates pile up as «probably dead but
nobody pulled the trigger», or things vanish abruptly and confusingly. A detector without disposal
is half a tool.

## Scope — what this applies to

Applies to things that **accrete and can rot**:
- **rules** (doc-extracted), **patterns**, **handbook prose/sections**, **CLI verbs / code obligations**.
- decisions & specs already carry terminal states (`Superseded` / `Withdrawn`; `retired`) — here the
  pattern adds only the missing **cadence** (phase out, don't instant-flip or never).

Does **NOT** apply to: **events.jsonl** (append-only history — never removed) and **done tasks**
(kept as grep-able history per QUEUE.md). Those are immutable record by design. More generally, **what
to do at the terminal step depends on the FILE TYPE** — history-of-record is archived, never deleted;
only genuinely-dead non-history weight is removed. See §File-type retention for the per-type table.

## Solution — Analysis + 4-step procedure (manual-first)

**Step 0 — Analysis (what to retire).** Feed from the existing detector:
`bin/yitc-v2 graph query --never-cited-in-rationale --window 30d` (manual review). A candidate
qualifies if: not cited/used in the window, OR superseded by another mechanism, OR no real incident
keeps it alive (CHARTER §1 F4). Record candidate + reason.

**Step 1 — Warn (deprecate).** Mark it `deprecated: <date> — <reason> — removal-trigger: <condition/date>`.
Leave it **working and visible** so anyone relying on it sees the warning (rule/doc-line: annotate;
code: comment + log line; pattern/spec: frontmatter/status note).

**Step 2 — Disable.** Stop relying on it — remove from the active path / stop invoking it — but
keep it present. Observe that nothing breaks during the disable window.

**Step 3 — Analyze.** At the trigger, verify no live use remains — query the journal/graph
(`journal query --grep <name>`, `graph query <id>`). If a consumer still depends → **HALT**,
re-evaluate (maybe it wasn't dead). Dissonance is a question (CHARTER §Principle 7).

**Step 3 — HIGH-BLAST-RADIUS case: a recorded pre-cut consumer inventory (gated).** When the target is
a **first-class entity or a graph schema node-type/edge** (blast radius = every reader, not one doc
line), Step 3 is NOT a glance — produce a **recorded inventory of EVERY consumer** (query call-sites,
saved views/projections, self-tests asserting the type/edge, pickers, schema assertions, any code
reading it), give **each a recorded fate** (keep / migrate / retire / follow-up), and **wire the gate
machine-readably** — the cut task `requires:` the inventory task, so the cut cannot start until the
inventory is `done` (operator memory is not the gate). Pass = **zero un-triaged consumers**. Decouple
the producer cut from cosmetic moves (a folder rename can balloon 10× on live refs — drop the cosmetic
part rather than block the safe cut). An unexpected consumer surfacing mid-cut → migrate or file a
blocking follow-up, **NEVER a silent cut** (and worktree isolation means a relative grep won't see the
cut yet — verify in the same checkout). Prior-art: the graph-slim 11→6 cut
(`retire-the-decision-entity-scaffolding-drop-from-g`..) landed GREEN behind exactly this
recorded, requires-gated inventory.

**Step 4 — Archive-or-remove (decide by FILE TYPE — never blanket-`rm`).** The terminal action
depends on what the thing IS (full per-type table in §File-type retention below):

- **Dead non-history weight** (a doc-extracted rule / a handbook section or prose line / a CLI verb /
  a code obligation): **delete it.** Record what + why in the commit (`from:` + the deprecation note).
- **Tracked history-of-record** (the corpus — `events.jsonl`, `tasks/`, `decisions/`,
  `plans/`): **never `rm`.** It is grep-able history by design. If a folder distends, **archive the
  old SUBTREE in-tree** (rotate the old segment aside — the canonical path STAYS where it is, e.g.
  done tasks remain under `tasks/`; this is an in-tree rotation, NEVER a move to a separate out-of-tree
  archive — QUEUE.md: «stay in `tasks/` indefinitely»).
- **Authored governance artifacts (specs / patterns):** retire **with trace, never `rm`** — a spec
  flips to `Superseded` / `retired` (stays in `specs/`); a dead pattern is retired via the procedure
  above but its removal preserves trace (superseding note + git history). The directories are never
  bulk-archived.

## File-type retention — what the terminal step means per type

The 4-step procedure removes **dead weight**; this table fixes what «remove» means once you reach
Step 4, **by file type**. The one rule across all of it: **delete = never, for anything that is
history-of-record.** «Archive» means **rotate/compress in place**, never `rm`, never a move to a
separate out-of-tree archive.

| File type | Examples | Terminal action |
|---|---|---|
| **Tracked corpus (history-of-record)** | `events.jsonl`, `tasks/`, `decisions/`, `plans/` | **NEVER delete.** Grep-able history by design. If a folder distends, **archive the old SUBTREE in-tree** (rotate the old segment aside; canonical path unchanged). The ONLY concrete split rule is the existing QUEUE.md `tasks/` 500+ done-entry carve-out — everywhere else «distends» is a **Review-judgement** call, not a new count-gate (the plan's number-triggers were removed for exactly this reason). `events.jsonl` is append-only — not split for size now (time-chunking is deferred). |
| **Authored governance artifacts** (can rot, but carry trace) | a `specs/SPEC-*.yaml`, a `patterns/<name>.md` | **Retire-with-trace, do not `rm`.** A dead/superseded spec flips to `superseded`/`retired` (it stays in `specs/`); a dead pattern is retired via the 4-step procedure but its removal preserves trace (a superseding note + git history), never a silent delete. The `specs/` and `patterns/` **directories** are never bulk-archived. |
| **`.yitc/` working data** (gitignored, NOT history-of-record) | `.yitc/bench/`, `.yitc/transcript-archive/` | **Chunk + compress** old segments; never the live record. Safe to compact because it is not the source of truth. |
| **Derived artifacts** | `graph/index.json`, `graph/floor-trigger-map.md` | **Regenerate** (`bin/yitc-v2 graph build`) — never hand-archive or hand-edit. The source is the corpus; a stale derived file is rebuilt, not retired. |
| **Dead non-history weight** | a doc-extracted rule / a handbook section or prose line / a CLI verb / a code obligation | **Delete** — this is what the 4-step warn→disable→analyze→remove procedure above is for. Deletion is legitimate here (with `from:` + the deprecation note). |

The boundary: the first three rows are NEVER `rm`-deleted (history is archived, working data is
compressed, derived is regenerated); authored governance artifacts (specs/patterns) are
retired-with-trace, not deleted. Only the last row — genuinely-dead non-history prose/obligations —
is deleted. This is the §Anti-pattern «Retiring immutable history» made explicit.

## Manual-first → automate-later

Run by hand during the weekly Review audit when surfaces candidates. **No code / CLI now.**
Automate (a verb feeding off the detector) ONLY after experience shows the steps repeat enough to
warrant it (CHARTER §1 F4 + automation-first). Premature automation is the accretion this prevents.

## Discoverability (teaching-path — applied by hand pending plan B)

The AI must KNOW this exists: a pointer lives in `AGENTS.md` (§When NOT to add a mechanism
neighborhood), and the trigger is the weekly Review audit + any CHARTER §1 F3 «what gets removed?»
moment. (First manual application of the adoption/teaching-path idea before it is formalized.)

## Example

```
# events.jsonl — Step 1 warn
{"ts":"2026-06-01T...","type":"deprecation_marked","data":{"target":"rule:agents:some-section:should",
 "reason":"not cited 42d ","removal_trigger":"2026-07-01 if still uncited"}}
# … disable window … Step 3 analyze: graph/journal show no live use → Step 4 remove (commit + from:)
```

## Anti-pattern

- **Silent deletion** (no warn/disable window) — breaks consumers, leaves no trace.
- **Eternal limbo** — flagging a candidate but never removing it (the detector-without-disposal gap).
- **Premature automation** — building a retirement CLI/gate before the manual steps have repeated.
- **Retiring immutable history** — `rm`-ing any tracked history-of-record (events.jsonl, done tasks,
  decisions, specs, plans) instead of archiving it in-tree. History is append-only; if a folder
  distends, rotate the old subtree aside — never delete it (§File-type retention).
- **Deleting a derived file to «retire» it** — `graph/index.json` and the floor trigger-map are
  regenerated by `graph build`, never retired; the source of truth is the corpus (§File-type retention).

## Cites

 (this procedure); (reverse-mapping candidate detector + retirement-candidate query);
PEP 387 (deprecation-policy prior-art); CHARTER §Principle 1 F3/F4, §Principle 7; automation-first.
