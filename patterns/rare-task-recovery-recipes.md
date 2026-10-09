---
name: rare-task-recovery-recipes
class: discipline
sourced_from: 'QUEUE.md §State transitions, moved here verbatim by under patterns/methodology-lessons.md Lesson 13 (a relocated rare branch keeps an index line and a help-head pointer)'
applies_to: 'two rare task states — the owner parks a task whose Stage-8 audit-post is RED; a task was closed before its land-verify passed, so its closure sits on an un-integrated branch'
---

# Rare task recovery recipes — parking on a RED audit-post, and a task closed before its land

> **How-to, not a rule.** The task state model — the transitions, the verb routes, waiting on the
> owner, «a LANDED done card has no reopen — file a new task» and the ban on hand-editing a done
> card's status — stays in `QUEUE.md` §State transitions. This file carries the two recipes that
> section names by its cue lines; each reuses existing verbs and adds no gate. A session meets a
> pointer here at the moment of need: the QUEUE cue line, the refusal of the verb that blocked it
> (`task commit` on a done card or over a dirty audit-post record, `worktree park` over a closed
> branch), and the first lines of the acting verb's help. Search this file for the bold lead the
> pointer names. «points here» in the rework recipe means this file. A new edge case of either
> recipe is written here.

## The two recipes

**Park-mid-audit land path (X-0118):** when a task is parked mid-audit — its Stage-8 audit-post is RED (e.g. a kernel-gap false-RED) and the owner parks it rather than forcing a GREEN that does not exist — closure is unavailable (`task close` is RED-blocked) and a standalone `task commit` is refused (`_audit_commit_shift_hazard`). So `bin/yitc-v2 task update --status parked`, when run inside a writing worktree that carries a dirty RED audit record, **self-commits its park record and folds the dirty `decisions/<tid>-audit-(post|consult-*).yaml`** (scoped staging — task YAML + events.jsonl + the task's own audit/consult records only). That leaves the worktree land-clean, so `bin/yitc-v2 land --task T-XXXX` integrates the parked bookkeeping to main with `status: parked` intact (land has no audit/closure RED-gate for a NON-terminal card — the GREEN-gate lives only in `task close`; the ONE exception is a TERMINAL `status: wont-do` card whose branch carries authored content no GREEN/YELLOW audit-post covers: `land` refuses it `wont-do-unaudited-ship` — revert the ship on the branch, or `worktree park` + a new card — because nothing returns to re-audit what a wont-do card ships / <project>). This is the park sibling of the `task pause` and `task update --status wont-do` self-commits. A plain park with no dirty audit record is unchanged (NON-terminal — it rides a later/batch commit).

**Prematurely-closed UNLANDED task — rework in place, or discard + re-claim; NEVER hand-edit status:** if a task was `task close`d before its land-verify passed (Stage-6 false-green — LIFECYCLE §Stage 9), its `done` + closure commit exist ONLY on the un-integrated branch; `land` never ran, so on **main the task is still `ready`**. Two sanctioned recoveries, neither needing a reopen verb — pick by whether the branch is worth keeping:
- **REWORK IN PLACE (default when the build has converged —, X-0820).** The branch survives: apply the new fix, re-prove it with **`bin/yitc-v2 task test --run`** (admitted on a done card *once the code determines the closure is not on `main`*), commit it via **`bin/yitc-v2 work commit`** (the post-close collateral route — `task commit` still refuses, and points here), then re-audit the current tree with **`bin/yitc-v2 audit post --task T-XXXX --reaudit-after-close`** (past the audit-loop ceiling the Controller records one `audit decide` per residual, then ONE `bin/yitc-v2 audit post --task T-XXXX --reaudit-after-close --on-decisions` pass runs — SPEC-0204) and `land`. When the re-proved deliverable no longer matches the card TEXT the re-audit judges it against, correct that text through the FOURTH leg — **`bin/yitc-v2 task update --old/--new`**, which admits an **`acceptance`-only** field edit on such a card (any other field still refuses, and the row is marked `post_close` so a later reader sees the closure PRECEDED the correction). Nothing is discarded and no raw git is needed. Admission is **DERIVED, never asserted**: the verb reads what `main` says about the card (`ready` / `in-progress` = closure still branch-local; anything else, incl. undeterminable, refuses fail-closed) — so passing this route a card whose closure LANDED is impossible.
- **DISCARD + RE-CLAIM (when the branch is not worth keeping):** **`worktree park`** (tears down branch+worktree, discarding the premature closure) then **re-claim via `worktree new --task`** — chain-of-custody stays clean.
