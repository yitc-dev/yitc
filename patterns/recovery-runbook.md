---
name: recovery-runbook
class: discipline
sourced_from: 'external consult 2026-06-16 (decisions/kernel-protection-recovery-set-audit-adhoc.yaml finding 3, MED) — recovery is strong for OBVIOUS breakage (a LAND-ABORT, a git revert) but weak for SEMANTIC corruption that PASSES tests + plan consumer-engine-write-boundary-guard-recovery-runb (U-3)'
applies_to: the RARE case where a land INTEGRATED successfully (tooling worked, tests green) but the corpus is SEMANTICALLY corrupt — a wrong-but-passing change that degrades later workers / consumers before detection (schema / export / dispatch behaviour). NOT broken tooling (that is patterns/emergency-mode.md); NOT removing dead weight (that is patterns/retirement-procedure.md).
---

# Recovery Runbook — rolling back a bad-but-green land (semantic corruption with working tooling)

> **Discipline pattern (rare recovery procedure).** This is the sibling of `patterns/emergency-mode.md`:
> emergency-mode is for when the TOOLING is broken; THIS runbook is for when the tooling WORKED — the
> land integrated, tests were green — but the shipped change is semantically wrong and is now degrading
> later sessions / workers / consumers. The two are DISTINCT recovery surfaces; this file owns the
> working-tool / corrupt-corpus case. It is a **how-to procedure, NOT a new rule, gate, verb, or
> mechanism** — it reuses the existing escape hatches (`git revert`, a lightweight tag, `bin/yitc-v2`
> probes).

## §Problem

`land`'s gate catches OBVIOUS breakage: a `LAND: ABORT`, a failing verify, a bad git state (recovered
via `patterns/emergency-mode.md`). It does NOT catch a change that PASSES verify but is semantically
wrong — a wrong-but-green schema / export-slice / dispatch / graph-build behaviour that only manifests
later, when a downstream worker or a `-C` consumer trips over it. By then the bad commit is already on
`main` and may have successors. The temptation is an ad-hoc panicked `git reset` on `main` — which
rewrites canonical history and discards provenance. This runbook makes the rollback **deliberate, safe,
and reversible** instead.

## §When to use (and when NOT)

USE when ALL hold: the tooling RUNS fine (not emergency-mode); a landed change is semantically corrupt
(wrong-but-green); and the corruption is degrading real work. NOT for: a verb refusing on purpose (the
tool working — satisfy the gate); broken tooling (→ `patterns/emergency-mode.md`); retiring an
intentionally-dead artifact (→ `patterns/retirement-procedure.md`).

## §1 — Last-green tagging (before a risky autonomous wave)

Before a risky batch (an autonomous dispatch wave, a broad schema/CLI change), tag the current known-good
`main` HEAD so the rollback target is unambiguous later:

```
git -C <main> tag yitc-last-green-<YYYYMMDD-HHMM> <main-HEAD-sha>
```

**The tag is an ADVISORY convenience pointer to an already-verified commit — NOT a second source of
truth.** The journal (`events.jsonl`) + the graph remain authoritative for "what was true when"; the tag
just saves you from hunting the SHA under pressure. It records nothing the journal does not already hold,
so it never needs reconciling and may be deleted freely once recovery is done.

## §2 — Rollback-target selection

Identify the FIRST bad commit and the last good one:

1. `git -C <main> log --oneline -20` + the journal (`bin/yitc-v2 journal query --type commit_landed
   --limit 20` — the segment-aware reader, SPEC-0190 rule 4) — find the
   `task_closed` / `commit_landed` of the offending ship.
2. The rollback target = the last-green tag (§1) if one was set for this wave, ELSE the parent of the
   first bad commit (`<bad-sha>^`), confirmed green by re-running the §4 probes against it.
3. Prefer the NARROWEST target: revert only the bad commit(s), not every commit since the tag, unless the
   later commits depend on the bad one.

## §3 — Recovery procedure (SPLIT by state — `revert` vs `reset` are NOT interchangeable)

- **Shared / `main`-integrated bad land → `git revert` (NEVER `reset`).** The bad commit is already in
  canonical history other checkouts/sessions have seen, so history must NOT be rewritten. Create a
  recovery worktree off `main` and revert there, then land the revert the normal way:
  ```
  bin/yitc-v2 worktree new --work recover-<slug>
  cd <worktree> && git revert --no-edit <bad-sha> [<bad-sha-2>...]
  # run §4 probes, then:
  bin/yitc-v2 land
  ```
  A revert is itself a new commit — provenance is preserved, `main` stays append-only, concurrent
  sessions see a clean forward history.
- **Disposable / pre-share worktree only → `git reset` is acceptable.** ONLY inside a throwaway worktree
  or a branch that has NOT been landed/shared may you `git reset --hard <target>` to drop local commits.
  **`main` is NEVER rewritten** (no `reset`, no force-push, no history surgery on the canonical branch).
- After the revert lands, `cd` back to the main checkout (land removes the worktree dir — `patterns`/
   cwd cue).

## §4 — Post-revert probes (prove the corpus is healthy again)

Run these against the recovered `main` (or the recovery worktree before landing); each must be green:

- `bin/yitc-v2 graph build` → exit 0 (index rebuilds clean, no dangling/conformance regressions);
- `bin/yitc-v2 graph conformance` → `CONFORMANCE: GREEN`;
- `bin/yitc-v2 session start --type review` → exit 0 (the engine's own entrypoint loads);
- `bin/yitc-v2 -C <a-disposable-consumer> init` → exit 0 (the consumer entrypoint the bad land may have
   degraded still works).

Capture the probe results in the recovery work-batch commit body (the durable evidence the corpus is
green again). File a post-incident task on the ROOT cause (why the wrong-but-green change passed verify),
mirroring the emergency-bypass 72-hour-retro discipline.

## §5 — Rehearsal (practise WITHOUT touching `main`)

To rehearse this runbook (or validate it), work entirely in a **disposable worktree/branch checked out
from a tagged last-green SHA — NEVER on `main`, NEVER on production data**:

```
git -C <main> worktree add -b rehearse-recovery <tmp-dir> <last-green-tag>
# fabricate a deliberately-broken state INSIDE the throwaway checkout, then walk §2→§3→§4,
# assert the §4 probes go green, and discard the worktree (git worktree remove <tmp-dir>).
```

The fabricated breakage lives only inside the throwaway checkout and is discarded — the rehearsal proves
the steps without risking the canonical corpus (the U-3 realization probe).

## §Non-goals (anti scope-creep)

This pattern is **documentation of a recovery procedure, not a new mechanism.** It adds NO verb, hook,
gate, ledger, flag, file format, detector, or "recovery FSM"; it introduces NO standing rule (a standing
rule would be re-homed to a spec per SPEC-0005 rule 8 — this is a how-to, not a rule surface). It reuses
the existing escape hatches (`git revert`, a plain git tag, `bin/yitc-v2 worktree new` / `land` /
`graph build` / `graph conformance` / `session start` / `init`). `patterns/emergency-mode.md` scope is
UNCHANGED — this is its sibling for the working-tool / corrupt-corpus case, not an extension of it. A
future proposal to AUTOMATE bad-land detection (a verify-after-land detector, a `--recover` flag) is a
SEPARATE decision subject to CHARTER §Principle 1's 4 filters — not grandfathered through this pattern.

## §Cites

- `decisions/kernel-protection-recovery-set-audit-adhoc.yaml` (finding 3 MED — the gap this closes) +
  plan `consumer-engine-write-boundary-guard-recovery-runb` (U-3, the proposing plan)
- `patterns/emergency-mode.md` (the BROKEN-tooling sibling — distinct surface, cross-linked from its
  §Non-goals) + `patterns/retirement-procedure.md` (the remove-dead-weight sibling)
- (`main` only via land; writes in a worktree — §3 revert-in-a-worktree) + CHARTER §Principle 2
  (the 72-hour-retro / post-incident-task discipline reused in §4)
- SPEC-0078 (the consumer→engine write-boundary guard — the U-2 sibling that PREVENTS one corruption
  class this runbook RECOVERS from)
