---
name: consume-verb-output-whole
class: discipline
sourced_from: X-0336 (owner-proposed 2026-07-12) + four captured deviations — three same-day on a consumer project (fp `self-truncated-tool-output-hides-verb-guidance`, fp `backgrounded-deploy-output-truncated-by-tail-pipe`) + the kernel-side duplicate-filing incident (fp `grep-swallowed-verb-output-misread-as-noop-duplicate-filing`, events.jsonl)
applies_to: every invocation of a governed CLI verb (kernel or consumer) from an AI session, a script, or a background worker — the READER side of verb output. The writer side is `patterns/cli-line-directive-vs-reference.md`.
---

# Consume a verb's stdout WHOLE — select afterwards, never at the pipe

## Problem

A governed verb's stdout is a **composed message**, not a value. One invocation carries, in one
stream: what the verb did, the verdict, the refusal reason, the read-gate it wants satisfied, the
next command in the flow, and the guidance the caller does not yet know it needs. Which line matters
is decided by what the verb DID — and the caller cannot know that before reading it.

So a filter applied **at invocation** (`… | tail -5`, `… | grep OK`, `… | head -20`) throws away the
part it could not have predicted. Three failure shapes, all observed:

1. **A discarded verdict reads as success.** A deploy piped through `tail` kept the last lines and
   ate two gate verdicts above them; the caller advanced on a gate it never saw.
2. **A discarded guidance line reads as absence.** A dispatch piped through `grep` kept the launch
   line and ate the arm-the-monitor instruction below it; the non-skippable watcher-arming step was
   simply never performed.
3. **A non-matching filter reads as a no-op.** A `task file` piped through a `grep` that matched
   nothing returned empty, was misread as "the verb did nothing", and was re-run — filing the same
   card twice (the duplicate had to be walked back as `wont-do`).

The discarded text is **not recoverable**. A mutating verb is not a getter: re-invoking it to re-read
its own output either duplicates the mutation (shape 3 above) or burns a bounded resource (an audit
pass). Truncation at the pipe is therefore a **one-way loss**, which is what separates it from an
ordinary sloppy read.

## Solution

**Capture the whole output first; select from the saved text after.**

- **Invoke bare.** Run the verb with no pipe and read the output in full. If it is long, that length
  is the verb telling you something — read it, do not clip it.
- **If you must reduce, save first.** Tee to a file, then filter the *file*:
  `bin/yitc-v2 <verb> … 2>&1 | tee /tmp/<verb>.out` → then `grep`/`sed` over `/tmp/<verb>.out`.
  Filtering is a **read over saved text**, never a filter at the pipe. The full text stays available
  when the line you actually needed turns out to be one you did not think to match.
- **Never infer a no-op from an empty filter.** An empty `grep` result says nothing about whether the
  verb ran. Before re-invoking any mutating verb, check the durable evidence it leaves — the journal
  (**`bin/yitc-v2 journal query`**, the segment-aware reader: the journal is one logical history
  across bounded physical segments, SPEC-0190 rule 1, so reading the live path directly can miss an
  older row and hand you the same false no-op this pattern is about), the artifact on disk,
  `git status` — never the absence of a matched line.
- **Backgrounded / logged runs: same rule.** Redirect the FULL stream to a log
  (`… > <log> 2>&1`) and read the log whole. A `tail -N` on a live log is a progress peek, never the
  basis for a decision.

**The one sanctioned exception — a CONTRACTED machine-keyed line.** Where a verb *promises* a
terminal-status token as its final stdout line, a caller MAY key on that token. The standing instance
is `land`: `LAND: OK <sha>` / `LAND: ABORT <reason>` (match `^LAND: (OK|ABORT)\b`) — the contract is
homed at AGENTS-SESSIONS §Writes-happen-in-a-worktree and restated at
[[background-session-monitoring]] §Token contract. "Contracted" means the verb's own documented
promise, held stable for machine callers. Absent such a promise there is no key to match on, and
matching one you invented is exactly the failure above. Keying on the token still does not license
DISCARDING the rest: the token decides the branch, the full output tells you what happened.

## Example

The kernel `land` contract is the exception done right, and it shows why the rule holds elsewhere:
`land` guarantees ONE final line for machines and prints everything else — verify progress, the
`cd <main>` cue, the debt echo — for the reader. A caller keys on `^LAND: (OK|ABORT)` and still reads
the body: the token routes, the body informs.

Every other verb in the inventory makes no such promise. `session start` opens with the seed and
general-verb pointers and closes with the cross-coordination and debt echoes; `worktree new` prints
the claim, then the read-gate warning, then the ordered Stage-1 procedure, then the whole per-stage
command sequence. Clip either end of those and you lose a mandatory step — which is precisely how the
three incidents above happened. (Including, honestly, a fourth: the session that authored this pattern
piped its own `session start` through `tail -25` and captured the deviation against itself.)

## Anti-pattern

```bash
bin/yitc-v2 task file --title … | grep '^T-' # empty match → "did nothing" → re-run → duplicate card
bin/yitc-v2 dispatch --task T-XXXX | grep launched # ate the arm-the-monitor guidance below
./deploy.sh 2>&1 | tail -5 # ate two gate verdicts above the tail
bin/yitc-v2 session start | tail -25 # ate the seed + general-verb pointers above
```

And the second half of the anti-pattern: **re-invoking a mutating verb to re-read its own output**
(`mutated-verb-reinvoked-to-reread-its-own-output`). If the output is gone, recover from the journal
or the artifact — never by running the verb again.

## Cites

- `X-0336` — the owner-proposed origin (its other half — a report-only unmonitored-dispatch debt line
  reusing the SPEC-0119 machinery — is; this pattern is the advice, that is the mechanism)
- Fingerprints: `self-truncated-tool-output-hides-verb-guidance` ·
  `backgrounded-deploy-output-truncated-by-tail-pipe` ·
  `grep-swallowed-verb-output-misread-as-noop-duplicate-filing` ·
  `mutated-verb-reinvoked-to-reread-its-own-output`
- [[cli-line-directive-vs-reference]] — the WRITER side of this surface (every AI-facing CLI line is
  unambiguously a directive or a reference); this pattern is the reader side of the same contract
- [[session-tooling-discipline]] — the sibling tool-call habits (SHAs come from verb output; never
  chain a command after `land`)
- [[background-session-monitoring]] §Token contract — the `LAND:` machine-keyed final-line contract
  (the exception above); AGENTS-SESSIONS §Writes-happen-in-a-worktree is its normative home
- [[error-friction-tracking]] — the capture reflex that made this class countable
