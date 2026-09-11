---
name: emergency-mode
class: discipline
sourced_from: real incident 2026-05-30 (this session improvised a by-hand-on-main fallback when the worktree/land flow was broken pre-) + CHARTER §Principle 2 emergency-bypass (external/internal prior-art — owner-authorized + retro-doc + frequency-check) (the SHA / stage-skip slips a by-hand flow must avoid) (emergency = degraded-execution MODE, not a 3rd session type; tool-independent entry; external-auditor-vetted)
applies_to: the RARE case where the V2 tooling that normally mediates writes is ITSELF broken — bin/yitc-v2 unrunnable, the worktree/land machinery broken, or git in a bad state — so the normal verb-mediated Build flow cannot run. NOT a routine bypass. Default is always fix-the-tool first.
---

# Emergency Mode — a documented by-hand fallback when the machinery itself is broken

> **Discipline pattern (rare escape hatch).** The verb-mediated Build flow (`worktree new` →
> edit → `task commit` → `land`) is the normal path. Emergency mode is what you do when the
> tool that would write the fix is **itself** down. It is the operational sibling of CHARTER
> §Principle 2 **emergency-bypass** (which bypasses the `from:` requirement for an urgent
> incident) — same shape: owner-authorized, documented, frequency-checked. NOT a new mechanism,
> NOT a gate — a written procedure so the by-hand path is safe and reversible instead of ad-hoc.

## §Problem

When `bin/yitc-v2` won't run, or the worktree/land control-points are broken, you cannot use the
blessed verbs that normally make a write safe (the claim, the atomic `task commit`, the ff-only
`land`, the auto-emitted events). The temptation is to "just do it by hand on main." That worked
once (2026-05-30, see §Example) but was **undocumented and ad-hoc**, and a naive by-hand flow
re-opens exactly the slips the verbs prevent: raw-main writes ( violation), the
`git add -A` cross-sweep, wrong/missing commit SHAs and skipped stages ( Slips),
and missing journal events. The fix is not "never go by hand" — it is a **documented minimal-safe
by-hand procedure** with clear entry, run, startup-reading, and exit+reconcile steps.

## §Solution

> **Emergency is a MODE, not a third session type.** You are still doing a normal
> **Build** or **Review** session — emergency just overlays it because the machinery is down. It
> adds NO new session type, lifecycle, startup-verb, or routing (the moment it would, it becomes a
> forbidden 3rd type — CHARTER §P6). The Build-vs-Review choice is UNCHANGED and is an *input* to
> emergency mode, never something it decides.

### Triage — which part is broken (the fallback is GRADUATED)

Before going by-hand, find out HOW MUCH is actually broken — fall back only as far as the breakage
requires, never all-the-way-to-manual by reflex:

1. Does `bin/yitc-v2` run at all? (`bin/yitc-v2 --help`) — if yes, most verbs still work; you may
   only need to hand-do the ONE broken verb.
2. Is it only `land`/worktree that's wedged (but `task commit` / `event` work)? Then commit + record
   normally and only integrate by hand.
3. Is git itself in a bad state? Then stabilise git FIRST (that is the real fix), before any task work.

Use the SMALLEST fallback that unblocks you. Record (for §Exit) exactly which verbs you replaced by
hand vs which still worked — see the reproduced-vs-skipped note in §(b).

### Entry — HOW you enter (tool-independent)

The entry CANNOT depend on the broken binary, so there is **no `session start --type emergency`**.
Entry is: an **owner phrase** ("rabotay vruchnuyu, instrument sloman" / "go manual, the tool is broken")
+ the AI **reading THIS file**. Markdown + chat survive a dead binary; a startup verb does not. At a
COLD start with the binary down, the owner's phrase NAMES the session type (Build or Review); mid-
session you keep the type you already have. Entry is owner-authorized (like emergency-bypass).

### (a) ENTRY-criteria — when emergency mode is justified (and when it is NOT)

**Default = fix the tool first.** Emergency mode is justified ONLY when the tool that would write
the fix is itself down. Concretely, enter ONLY when one of these holds AND blocks progress:

- `bin/yitc-v2` is unrunnable (import error / crash / corrupt state file) and the fix is not a
  one-line obvious edit you can make and immediately re-run;
- the worktree/`land` machinery is broken (e.g. `land` fails mid-integration, a worktree is wedged);
- git is in a bad state (detached/corrupt index, interrupted rebase) that the verbs can't navigate.

**NOT emergency mode** (fix-the-tool instead): a verb merely *refused* you on purpose (a gate firing
is the tool WORKING — escalate or satisfy the gate, do not bypass); a single broken line in
`bin/yitc-v2` you can just edit and re-run; impatience. A refusal is not a breakage.

Entry is **owner-authorized** (like emergency-bypass): note it in chat + the eventual commit body.

### (b) RUN — the minimal safe by-hand sequence

Preserve the *intent* of the verbs even when the verbs are down:

- **Commits go on a branch, never raw `main`** ( isolation holds even by hand): `git worktree
  add -b task/T-XXXX../yitc-v2-wt/T-XXXX main` is the documented recovery escape hatch (raw git is
  legitimate here precisely because the verb is down). If even worktrees are broken, a throwaway
  branch off main — still NOT commits onto `main` directly.
- **Stage the whole worktree, no pathspec games** (mirror `git add -A`): `git add -A` in
  the isolated checkout; never hand-pick / pathspec-exclude (the v1 B-722/ gotcha).
- **Record closure/audit artifacts by hand** via the LIFECYCLE Stage-9 + audit hand-edit fallbacks:
  write the task YAML closure fields (`status: done`, `closed_at`, `commit`, `probe_passed`,
  `probes`), and save any audit verdict to `decisions/<id>-audit-<stage>.yaml` in the canonical shape.
- **Avoid the slips:** use the REAL commit SHA from `git rev-parse HEAD` (not a guessed/stale
  one); do NOT skip stages — a by-hand flow still runs Analysis→…→Closure in order; verify a write in
  the SAME checkout you wrote it (absolute path / `git -C`), not a relative grep from elsewhere.
- **Hand-emit the events the verbs would have** (append-only JSON lines to `events.jsonl`):
  `task_picked`, `commit_landed`, audit + `task_closed` — matching the schema in AGENTS §events.jsonl.
- **Scope/path discipline is NOT relaxed** : emergency mode loosens the
  *automation*, never the *rules*. The path-based territory boundary still holds — by-hand work stays
  inside the project's own paths; do NOT edit another project / external territory because the verb
  that would have guarded it is down.
- **Keep a reproduced-vs-skipped record** (the concrete-exit-reconciliation discipline):
  as you go, jot which normal guarantees you reproduced BY HAND (e.g. "claimed by hand-edit + emitted
  task_picked") vs which you SKIPPED (e.g. "no audit-pre — auditor unreachable"). This list IS the
  §Exit checklist — it makes reconciliation concrete instead of "looked fine".

### (c) STARTUP — what to READ on entering emergency mode

Still authoritative (read / hold): **CHARTER** (all 8 principles — they do not suspend), the
`from:`/probe discipline (Principle 2 + 3), the worktree-isolation *intent*, the commit
format slip list, and the Stage-9 / audit hand-edit fallbacks in LIFECYCLE + AGENTS.

Temporarily **suspended** (because the mechanism is down, not the rule): the specific verb
control-points (`task commit`, `land`, auto-emit) — you reproduce their EFFECT by hand. The rules
they enforce stay in force; only their automation is unavailable.

### (d) EXIT + reconcile — return to the normal flow

The moment the tooling is fixed:

1. **Reconcile the journal:** re-run anything the verbs would now do (`bin/yitc-v2 graph build`;
   if any events were missed, emit them via `bin/yitc-v2 event …`). The journal is append-only, so
   late/duplicate-safe entries are fine — never rewrite history.
2. **Integrate the by-hand branch the normal way** if `land` is back (`bin/yitc-v2 land`), or a
   plain ff-merge to `main` if not, then delete the branch.
3. **Verify:** `graph build` exit 0; the task's probes hold; no raw-main commits slipped in.
4. **Write the retro + file the post-incident task** (mirrors emergency-bypass's 72-hour retro
   requirement): one short note on what broke + a task to fix the tool so the bypass is not needed
   again. The bug that forced emergency mode is itself the highest-priority follow-up.

## §Example (the real prior-art)

**2026-05-30.** Before / / landed, the worktree/claim/land flow was broken
(claim desync; `land` left the shell in a deleted cwd; relative-grep verification missed
worktree-local edits — the Slip-5 trap). To keep shipping, the session improvised a
by-hand-on-main flow. It WORKED and unblocked progress, but was undocumented and ad-hoc — and it
brushed the very slips listed in §(b). (claim-in-worktree) (land-from-main + `cd`
cue), and then fixed the normal flow, so emergency mode is **not** needed
day-to-day. This pattern captures the fallback so the next time the machinery breaks, the by-hand
path is a *documented, safe, reversible* procedure rather than an improvisation.

## §Anti-pattern (the anti-routine guard)

- **Routine bypass.** Emergency mode is the RARE escape hatch, not a faster path. The standing
  default is **fix the tool**, then use the normal verbs. Reaching for by-hand because a verb is
  slow / strict / inconvenient is abuse (CHARTER AI failure class #16 Bypass abuse).
- **Frequency check** (verbatim mirror of CHARTER §Principle 2 emergency-bypass): **> 1 use per
  30 days triggers a Review-session audit** — repeated need means the tooling has a standing defect
  to fix, not a fallback to lean on.
- **A gate firing is NOT a breakage.** If a verb refused you on purpose, the tool is working —
  satisfy the gate or escalate to the owner; do not "go manual" to route around a deliberate guard
  (that is the `bypass-audit-via-env-var` anti-pattern in AGENTS §External auditor).
- **No silent by-hand.** Every emergency-mode entry is owner-authorized + leaves the retro +
  post-incident task (§d). Undocumented by-hand work is invisible and un-reconcilable.

## §Owner — how the owner triggers it (no button, just words)

The owner does not run anything technical. To enter emergency mode the owner **says it in chat** —
e.g. "rabotay vruchnuyu, instrument sloman" / "go manual, the tool is broken". That phrase IS the
owner-authorization the §Anti-pattern requires; the AI then reads this file and follows §Triage →
§Run → §Exit. Two practical owner notes: (1) a verb *refusing* on purpose is the tool WORKING — that
is not a reason to go manual; (2) if emergency mode is needed **more than once a month**, that is a
signal of a real tooling defect to fix, not a fallback to lean on (the frequency check). Nothing is
lost while broken — the whole methodology is plain text files in git; a fresh AI session can read
them and recover.

## §Non-goals (anti scope-creep)

This pattern is **documentation of a fallback, not a new mechanism.** It does NOT add a verb, hook,
gate, ledger, flag, file format, or "emergency FSM." It reuses the existing recovery escape hatches
(raw `git worktree`, the Stage-9 / audit hand-edit fallbacks, `bin/yitc-v2 event`) and the existing
emergency-bypass frequency-check discipline. If a future proposal wants to *automate* emergency mode
(a detector, an `--emergency` flag, a registry), that is a SEPARATE decision subject to CHARTER
§Principle 1's 4 filters — not grandfathered through this pattern.

**Out of scope — semantic corruption with WORKING tooling (the sibling runbook).** This file is for when
the TOOLING is broken. A land that INTEGRATED fine (tooling worked, tests green) but is semantically
CORRUPT (a wrong-but-green change degrading later workers / consumers) is a DIFFERENT recovery surface —
see **`patterns/recovery-runbook.md`** (last-green tagging, rollback-target selection, `revert`-vs-`reset`
by state, post-revert probes). Emergency mode's scope is UNCHANGED; that runbook is its sibling, not an
extension of it.

## §Sibling modes — pick the right bounded mode before you enter this one

This file is ONE member of a family of THREE bounded operating modes. They are distinguished by WHAT
is bounded, and reading the wrong one wastes the entry:

- **`patterns/emergency-mode.md` (this file)** — the TOOLING is broken, and a delivery still has to
  happen by hand. Bounded by owner-authorization + retro + the frequency check.
- **`patterns/spike-mode.md`** — the tooling is FINE and you are running a THROWAWAY debugging
  exploration against a sandbox stack. Bounded by the cage; its exit is knowledge, never landed code
  (SPEC-0172). Not an emergency: nothing is broken and nothing is being delivered.
- **`patterns/trial-methods.md`** — a PLAN's `trial` stage: a controlled real-data practice run of a
  mechanism before it is accepted. Bounded by the plan's baked `## Trial protocol` + the SPEC-0035
  rule-5 exit floor. Owner-invoked, and never a delivery fallback.

If the tooling works, you are in one of the other two, not here.

## §Cites

- CHARTER §Principle 2 (emergency-bypass — the owner-authorized + retro + frequency-check analog)
- CHARTER §Principle 1 (anti-complexity — §Non-goals guard) + AI failure class #16 (Bypass abuse)
- (writes happen in a worktree; `main` only via land) (`task commit` owns staging)
- LIFECYCLE §Stage 9 + AGENTS §External-auditor-invocation-contract (the hand-edit fallbacks)
- / / / / (the 2026-05-30 incident + the fixes that retired the need)
- (emergency = degraded-execution MODE, not a 3rd session type; tool-independent entry — the §Solution preamble + §Entry + §Triage) (scope discipline not relaxed — §Run)
- `patterns/spike-mode.md` (SPEC-0172) + `patterns/trial-methods.md` (SPEC-0035) — the two sibling
  bounded modes, §Sibling modes above
