---
name: plan-draft-documents
class: discipline
sourced_from: one consumer project's sandbox-exit simulation (2026-11-13) and its hand-over to the kernel, cross item X-2379 (provenance only — read-only, never a dependency); the cancelled kernel plan `sandbox-exit-plan-check-and-cut-kernel-mechanism` §Evidence base and §Design part 3 (K19), which carried the measurements into this repository
applies_to: you are drafting a LARGE plan — one that will be cut into several cards and that changes a system already in production (new roles, tables, routes, background jobs, money or access paths). Read it at `plan file`, before the plan's first check round. NOT needed for a one-card change or a plan that touches only text.
---

# Plan draft documents — what to prepare before a plan's first check round

> **Discipline pattern.** Method text, not a mechanism: no gate reads these documents, no verb
> refuses without them, and no kernel store holds them. The skeleton `plan file` seeds carries one
> `## Draft documents` slot that points here (SPEC-0043 item 11 — `bin/yitc-v2 graph query SPEC-0043`).
>
> **This doc travels** (SPEC-0090): it names no project's paths, roles or tables. The documents
> themselves are PROJECT documents — written in the project, about the project, kept where the
> project keeps its docs. The kernel ships only the method.

## §Problem

A large plan drafted from the owner's words and one design note meets the existing system for the
first time at the external check. Every seam the draft did not know about — a guard test that freezes
a table list, a role that already has a policy, a route registry — comes back as a finding, one facet
per pass. The check rounds then do the discovery work the draft skipped, at the auditor's price.

Measured on one consumer project's re-run of a real sandbox exit (the same plan written twice, once
from the owner's words plus one architecture note, once from a set of draft documents):

| What was measured | Draft documents (set of 7) | One architecture note |
|---|---|---|
| The 70 key items of the real run (full / partial / not covered) | **21 / 37 / 12** | 11 / 28 / 31 |
| The 105 gaps the real cut had to close (full / partial / not covered) | **58 / 29 / 18** | — |
| Code defects found that no key item named | 5 | — |
| Cost to produce | 22 min wall, ~46 min helper time, helpers in parallel | — |

The seam map, used through the cut, left **zero findings of its class across 11 cards**. One document
went wrong: a rights matrix whose TECHNICAL remedy (a row-level-security fix) was never checked against
how the database actually behaved. That one wrong answer seeded **six of the eight high themes of
round 1** and three loops of rights rework. That is where the verify-first rule below comes from.

These figures are ONE project's measurement, said so (CHARTER §Principle 1 filter 4). A second project
reporting in the same form is the trigger for anything more than this text.

## §The six document kinds

Each is a short project document with one job. Write the ones the plan needs; a plan that touches no
access path needs no rights matrix.

### 1. Rights or threat matrix
Who may do what to which record — every role × every action × every new or changed object, with the
answer AND the mechanism that enforces it (a policy, a check in a handler, a guard in a query). For a
plan with a public surface, the same table carries the threats (who can reach it unauthenticated,
what they can enumerate).
**What it catches:** a role that can read a neighbour's rows, an action no role may take, a grant that
widens an existing rule. **Its known failure:** the mechanism column written from memory — see the
verify-first rule.

### 2. Seam map
Every place the plan's new code meets existing code: a shared definition, an API contract, a registry
(routes, menus, migrations, background jobs), a module two roles reach. One row per seam: the existing
side (named function, file, table), the new side, and which card will own the join.
**What it catches:** the "used before created" order, a producer/consumer pair split across two cards
with nobody owning the join (SPEC-0046 §A, producer-owns-the-seam), a registry nobody updates.

### 3. Guards by change kind
For each KIND of change the plan makes — a migration, a new table, a new key, a new database
connection, a new API address, a new screen, a new test — the project's existing tests and checks that
freeze that kind (an inventory test, a route list, a schema snapshot, an end-to-end registry). One
row per kind: the guard files the card must update together with its change.
**What it catches:** the red verify on a card that "only added a table" because a stack inventory test
lists every table. A STANDING document: kept in the project and updated by every plan (below).

### 4. Pre-mortem
"It is three months later and this plan failed — why?" Ten to twenty concrete failure stories,
each with what in the plan would prevent it or the honest answer "nothing".
**What it catches:** the missing rollback, the job that runs twice, the data the owner meant but
nobody wrote down.

### 5. Readiness checklist
What must be true before the first card is dispatched: data seeded, logins for each role on the
stand, the main branch green, migrations numbered after main's head, the owner's open questions
answered. The project's standing template, filled for this plan.
**What it catches:** the card that waits a day on a missing login or a red main.

### 6. Decision records (ADRs)
One short record per design choice the plan makes between real alternatives: the options, the one
chosen, why, and what would make it wrong.
**What it catches:** the same alternative re-proposed by every check round, because the plan states
the choice but not why the other one lost.

## §Standing and per-plan documents

- **Standing** (live in the project, every plan updates them): guards by change kind, the system seam
  map, the system rights matrix, the readiness checklist template.
- **Per plan:** the pre-mortem, the plan's own seam map, the ADRs, and — for a sandbox exit — the
  prototype registry (`patterns/spike-mode.md` §5c, SPEC-1058).

A standing document is only worth its upkeep while it is current; a plan that changes a seam, a role
or a guard updates the standing document in the same card that makes the change.

## §Who writes them, and when

- **Before the first check round of the plan** (`plan check`), from the owner's words and the code —
  and, for a sandbox exit, the code BEFORE the prototype, so the documents describe the system the
  prototype will land into.
- **Helpers, in parallel.** One in-session helper per document (or per pair of small ones), each given
  the plan draft, the owner's words and the code paths to read. The measured run took 22 minutes wall
  for seven documents. The controller reads the results, reconciles contradictions between them, and
  asks the owner what only the owner can answer.
- **Project content, project format.** Which roles, which guards, which seams exist is the project's
  knowledge; the kernel ships no filled document and no template beyond the six headings above —
  a filled one would be stale on the project's first change.

## §The verify-first rule

**A document about a mechanism is verified against the live system before it enters a plan.**

Any row that states HOW the system behaves — this policy blocks that read, this role cannot reach
that table, this job runs once per day, this guard fails on a new column — is checked by running it:
a query under the real role, a request against the stand, the guard test run on a scratch change, the
scheduler's actual configuration read. A row that cannot be checked yet is marked unverified and stays
OUT of the plan's design text until it is.

Why it is a rule and not advice: a draft document is read as fact by everything after it. The plan
copies its answer, the check rounds argue with the plan's copy, and the fix loops patch the copy —
the measured wrong rights remedy cost six high themes and three loops, all downstream of one
unchecked row. Checking that row first would have cost minutes.

Corollary for the plan text: do not RETELL a mechanism in the plan. Name the existing function or
policy and say "as is"; describe only what the plan adds. Every retelling in the measured run drifted
from the system and seeded a medium finding next to it.

## §How the documents reach the cut

The documents do not travel to the cards whole. At the cut (`plan stage decomposition`, SPEC-0070),
the project fills each card skeleton from them:

- a seam map row becomes the owning card's `requires:` edge and a line of its scope;
- a guards-by-change-kind row becomes the card's guard files in `expected_touch` (`Owns:` in the
  plan's `## Units`, SPEC-0043 item 10) and a criterion that those guards stay green;
- a rights matrix row becomes a criterion with its probe under the real limited login;
- a pre-mortem story that the plan answers becomes a criterion or a probe; one it does not answer
  becomes an owner question before accept.

In the measured run, card skeletons generated from the plan's units closed 95 of the 105 gaps of the
real cut before any external check, once the seams and guards were filled in. Filling them is the
project's work; `plan show <slug> --unit-skeletons` prints the skeletons it fills.

**A draft document that disagrees with a carried registry item is an owner question before accept.**
For a sandbox exit the plan carries the prototype registry (SPEC-1058). Where a draft document — a
rights matrix, a seam map, a guards row, an ADR — prescribes something different from a registry
item the plan carries, the difference is not settled in a card: before `plan stage accepted` the
owner answers, and the answer is recorded either as an `owner_row` amendment of the item (SPEC-1058
§2 — the amended item then holds in every check) or as the document corrected to the item. In one
measured run a card followed a rights matrix that forbade grants the registry carried; the
decomposition-fidelity gate (SPEC-0070) went RED on it, and the registry was amended after accept at
the price of one more change check.

## §What the auditor reads — and what it does not

**The external auditor never reads these documents whole.** They are project documents; a plan
check packet carries the plan, its registry and its specs, and a pass that also carried seven
documents would burn its budget on reference text. The measured gain did not come from the auditor
reading them: it came from the plan being written with them, and from **helpers reading them** —
the drafting helper, the blind self-check helper that compares a fix against the documents and the
live system, and the cut helpers filling card skeletons. Where a check needs one row, that row is
quoted into the plan or the card, never the document attached.

## §Anti-pattern

- **A document written from memory of the system.** It looks complete and is wrong in the one place
  that matters. Verify first.
- **The documents as a gate.** No verb asks for them and none should: a plan that needs none is
  normal, and a checklist that becomes a gate becomes a form to fill.
- **A kernel template filled with one project's content.** The kernel carries the six headings and
  the rules on this page; the rows are the project's.
- **Attaching the documents to every audit.** The auditor judges the plan; the documents served the
  people and helpers who wrote it.

## §Cites

- **SPEC-0043** item 11 — the `## Draft documents` slot `plan file` seeds, with the verify-first cue.
- **SPEC-0046** §A — producer owns the seam; the cut grain the seam map feeds.
- **SPEC-0070** — the decomposition gate the filled skeletons pass.
- **SPEC-1058** and `patterns/spike-mode.md` §5c — the prototype registry, the sandbox-exit document.
- **SPEC-0090** — why this method travels as a pattern and each project's documents stay its own.
- `patterns/big-plan-checklist.md` — the big-plan probe that asks whether these were prepared.
