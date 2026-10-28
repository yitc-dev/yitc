---
name: draining-provider-memory-and-context-home
class: runbook
sourced_from: the kernel's own drain (lessons/provider-memory-sweep-2026-10.md + its group ledgers -s1..-s6, 410 notes dispositioned, model lessons/global-memory-v2-migration-sweep.md) + the cryptochart measurement in public issue yitc#210 (25 days - 640 notes, an index truncated at load, an owner rule found nowhere else, two red Stage-6 runs from a note past the truncation line; its context home 537 lines, most of them worker rules) + owner directives events.jsonl#ts= (option a) and go #ts=. Authored; read by the followups fu_92ba39adb47d (host consumers) and fu_f9ee489e8e54 (remote link-back on yitc#210 / #82) armed on (the memory-off setting) and (the quick-rule route to lessons).
applies_to: every project before it takes the provider memory-off setting - drain first, switch off second. Also any project whose context home (SPEC-0125) has filled with rules for workers.
---

# Draining a project's provider memory and context home into its corpus

## Problem

The assistant tool a project runs in may keep a memory of its own, outside the repository: notes it
writes for itself and reads back when a session starts. That memory reaches no dispatched worker, no
other provider's assistant and no review, and SPEC-0039 §6 limits what it may hold. In practice it fills
with craft, rules and owner decisions that belong in the corpus, and the project's context home
(`CHARTER.md` or `AGENTS.md`, SPEC-0125) fills the same way, with rules for workers that SPEC-0125
rule 1a says it never holds.

Measured: the kernel's memory held 410 notes; cryptochart's held 640 with an index cut off at load,
more craft than its `lessons/`, and at least one owner rule found nowhere else. Two of its Stage-6 runs
went red because the note that would have prevented it sat past the cut. Switching the memory off
before draining it loses those rules. So the drain comes first, and the switch comes second.

## Solution: the order

Every step is a read, a lesson written in a worktree, or an existing verb. No new verb is needed.

1. **Inventory (read only).** List the provider's own memory directory for this project, with names
   and modification times, and record the listing time. The location is the provider's, read from its
   implementation config. This how-to names no path. The directory is external territory: no session of
   the project edits, moves or deletes anything in it.
2. **Drain the memory.** Give every note one disposition (below), each claim checked first.
3. **Drain the context home.** Move its worker rules out (§Draining the context home).
4. **Write the ledger** (§The ledger) in the same worktree, and land it.
5. **The owner applies the DELETE list.** The owner backs up the directory first. Before deleting a
   listed name, the owner compares its modification time with the one the inventory recorded: a note
   changed since then is not deleted, because its new content has not been checked, and it gets a
   row of its own first. The owner deletes the rest and records it as an `external_action` event
   (SPEC-0116). No session deletes from that directory.
6. **Take the memory-off setting** through `init --refresh-scaffolds` once the kernel release that
   carries it serves the project. Then check that no new file appears in the directory after
   the switch.

## Where each note goes: the six dispositions

The home for each kind of content is the row of `graph query capture-routing` (SPEC-0157) for that
situation. Read the home there. The table below only names the dispositions.

| Disposition | What it means | Where it goes |
|---|---|---|
| **MOVED** | still-true craft or fact, not yet in the corpus | the lesson (or pattern, if it travels) that the capture-routing row names, written in this drain's worktree |
| **ALREADY-IN-CORPUS** | the claim is already stated in a governed home | nowhere; the ledger cites where it is |
| **RULE** | a standing rule, or an owner decision found nowhere else | the home that capture-routing names for a rule, by its own card or followup. Where the home is unclear, ask the owner |
| **LOG** | history, or an index file that has no content of its own | the journal and the cards already hold it; nothing moves |
| **KEEP** | fits what SPEC-0039 §6 still allows, or is unresolved | stays in the memory and is left off the DELETE list |
| **STALE** | the tree or the journal refutes it | dropped; the ledger names what refuted it |

**Check each claim before moving it, by the kind of claim it is.**
- A **technical claim** (a code path, a test, how a verb behaves) is checked against the current tree. It
  is dropped only when the tree refutes it, or when what it names cannot be found. The ledger records
  the check: a path and line, or a command and its result.
- An **owner rule or decision** is checked against the journal's `owner_directive` rows, the cards and
  the context home. It is never checked against code, because an owner rule may not be implemented yet.
  An owner rule found nowhere else is never dropped. It takes RULE, and its source note stays KEEP
  until that RULE row is resolved.
- A note you cannot classify stays **KEEP** until it is resolved.

Run timings and incident narratives are history: leave them out, and keep the task ids as provenance.

## Draining the context home

The context home keeps the owner's decisions about the product: the product profile, integration
constraints, safety bans, the data policy and the grouping preference (SPEC-0125 rule 1a). Those stay
where they are. Anything else is drained:

- **A rule for the project's workers** moves out to a lesson whose claims each cite their evidence: a
  code path, a journal row or a test. A claim with no evidence is marked as a hypothesis. This is the
  quick-rule route adds to capture-routing. A lesson becomes a stage-bound spec only through
  its own card.
- **State of the moment, history, and facts the repository already holds** are removed. The journal,
  the cards and the views carry them (rule 1a lists which).
- **Check each line as in the memory drain:** a technical claim against the tree, an owner decision
  against the journal. Each removed line gets a disposition row of its own.

## The ledger

The ledger is one lesson per project (split into group ledgers plus a totals file when the set is
large). The kernel's `provider-memory-sweep-2026-10` lessons are the model. It records **both** drains:

- one row per memory note and per removed context-home line, giving the entry, its disposition, the
  target home, how it was checked, and what was left out;
- the totals, kept apart for each drain: listed = dispositioned, per disposition. A home with no
  worker rules records 0 for the home drain. Step 5 is skipped only when the DELETE list is empty;
- the **DELETE list**: every listed name that is not KEEP, each with the modification time the
  inventory recorded, because step 5 compares against it. A note written after the listing time is
  not on the list and needs its own row first. A note changed after the listing time is treated the
  same way. That is also what happens when a session writes or edits a note while the drain is
  running.

## Anti-pattern

- Switching the memory off before the drain: the rules it held are lost without anyone seeing them.
- A session deleting or editing inside the provider's memory directory. Only the owner applies the
  list, after a backup.
- Dropping a claim because the code does not show it, when the claim is an owner decision.
- Moving a note without checking it: stale craft then reaches every worker as if it were current.
- Moving worker rules from the memory into the context home. That is the same accumulation, in a
  file every session loads.

## Cites

SPEC-0039 §6 (what the provider memory may hold) · SPEC-0125 rule 1a (what the context home keeps) ·
SPEC-0157 (capture-routing, the home for each disposition) · SPEC-0090 (lessons stay local, patterns
travel) · SPEC-0116 (`external_action` for the owner's delete) · (the kernel drain) ·
(the memory-off setting) · (the quick-rule route).
