"""evidence_custody — the SPEC-0168 EVIDENCE-CUSTODY seam at the land, extracted byte-identical
from `bin/lib/worktree.py` (T-11525, plan `split-worktree-py-along-its-own-spec-seams-runner-`).
This is the FIFTH and LAST of that plan's cuts.

WHAT IS IN HERE, AND WHY THE BOUNDARY IS THE ONE IT IS. The move-set is the TRANSITIVE-EXCLUSIVE
closure rooted at this subject's OWN entry points, where a helper moves iff EVERY top-level caller of
it is already in the move-set. Two groups of roots:
  (a) THE FOLD SEAM — SPEC-0168 rule 1 ("the evidence set is the LANDABLE journal instance, on both
      checkouts") and rule 6 (the atomic rewrite): `_fold_main_journal_into_branch`, the ONE
      `bin/lib/worktree.py#` anchor SPEC-0168 carried, together with the pre-ff journal unwind pair
      that exists BECAUSE of its `reset_main` reset — `_main_journal_snapshot` / `_restore_main_journals`
      (T-10723 / E-0055).
  (b) THE CUSTODY CHECK — SPEC-0168 rule 5's report-only land-seam verification that evidence the
      audit packet CREDITED actually ARRIVED in the committed journal: `_journal_keys`,
      `_custody_counted_keys`, `_custody_classify`, `_custody_report_lines`, `_custody_committed_keys`,
      `_custody_emit_report`, and the three non-landing MODE constants with their remedy table.

NOT IN HERE, AND THIS IS THE SEAM DECISION RATHER THAN AN OMISSION: `_land_integrate`. It is the sole
top-level caller of six of the nine movers — the CALLER of evidence custody, not evidence custody —
and rooting at it is attempt-1 of the T-11519 failure, which T-11524 re-measured on this very file
(its own closure went 86 -> 225 defs and dragged THIS subject along). Rooting at the subject puts the
land seam outside the cut BY CONSTRUCTION rather than by an exclusion list someone has to remember to
write (`lessons/library-extraction.md` §"Root the closure at the SUBJECT's own entry point").

THE CARD'S MARKER MEASUREMENT IS NOT THIS BOUNDARY, and the difference is the whole point. The
`SPEC-0168 rule 5` section banner in the host ran to EOF and so enclosed 4649 lines / 20 defs — but
3485 of those lines are `_land_integrate` alone, plus `_update_from_main`, the SPEC-0077 land-preflight
line-builders and the worktree-leftover recovery helpers. None of them is evidence custody. Also NOT
here, though it sits three defs above the banner and cites "SPEC-0168 rule 3's discipline" in its own
docstring: `_old_shape_journal_refusal`, which is SPEC-0190 journal-rotation logic BORROWING custody's
identity function. A name that mentions the domain is not membership; membership is by call-site.

Also not here: batch landing (`bin/lib/batch_landing.py`), the verify runner
(`bin/lib/verify_runner.py`), the SPEC-0077 pinned verify and its rebaseline arm
(`bin/lib/rebaseline_currency.py`) and the worktree lifecycle (`bin/lib/worktree_lifecycle.py`).

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 / T-11523 / T-11524 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM from
the original source — never `ast.unparse`, which reformats and loses byte-identity — and every
non-stdlib free name (host stayers, host globals, AND moved siblings via their host residue) arrives as
a keyword-only injected parameter, computed with `symtable` over each function's scope SUBTREE. The
host keeps a `functools.wraps` residue under every historical name, so every `worktree.<sym>` caller,
monkeypatch and source-scanning test keeps resolving — and `inspect.getsource(worktree.<sym>)` unwraps
to the REAL body here.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib and already-extracted
lower leaves; it NEVER back-imports the host.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

from lib import events
from lib import journal as journal_mod   # SPEC-0190 rule 4b: the segment-aware revision reader
from lib import task as task_mod         # SPEC-0168 rules 1-4: the packet-side evidence fold


def _fold_main_journal_into_branch(main_wt, *, _die, _run_git_cap, EVENTS_PATH, _BOOKKEEPING_ALLOWLIST, _DERIVED_MERGE_ARTIFACTS, _capture_reopen_errors_dirt, _dedup_events, _is_foldable_journal, _is_yitc_session_state, write_text_atomic, reset_main: bool = True, _foreign_main_dirt_message=None, _main_dirt_verdict=None, _tracked_paths=None) -> bool:
    """Fold main's append-only bookkeeping dirt (events.jsonl / graph/index.json) into the LANDING
    BRANCH's events.jsonl (union) and — when `reset_main` — clean main's working tree, so journal
    dirt cannot block the ff (D-0049 fold-promise). Returns True iff the branch changed (the CALLER
    decides whether/when to commit). Refuses (via `_die`) on any substantive (non-allowlist) main dirt.

    `reset_main` (T-10245) — the REFUSAL and the UNION are unconditional; only the trailing RESET of
    main's working tree is the caller's. The reset is the ff's clean-tree precondition, so it is owed
    ONLY by the site that ffs (the in-lock pre-ff re-fold, default True). Land's EARLY step-2b passes
    False: main's uncommitted `session_started` anchor + `cli:seed` receipt are the ONLY live backing
    for a concurrent interactive session's carried `YITC_SESSION_REF` (SPEC-0137 Rule 2.1 path (b) —
    path (a), a live runtime record, is structurally dead under a headless harness where every CLI
    call is its own short-lived subprocess), so resetting them away at step-2b hid that session's
    identity for the whole verify and fail-closed every governed verb it ran. Main is dirty at the ff
    anyway — the pre-ff re-fold exists precisely to absorb appends made DURING verify (E-0006/T-0229)
    — so step-2b's reset never provided the ff's precondition; it only opened the window.

    ALSO folds a CONSUMER's tracked `.yitc/` per-session operational state (T-0871, F-008 residual):
    the `.yitc/events.jsonl` hook-tail is unioned alongside the root journal, and the non-append
    `.yitc/awareness-ledger*` / `.yitc/journal-sync-state/**` YAMLs are take-latest-discarded by the
    trailing `checkout HEAD` — so a live interactive consumer session lands without hand-aligning its
    `.yitc/` state. Matched explicitly + fail-closed (`_is_yitc_session_state`); INERT for the engine
    (which gitignores `.yitc/`). An UNMATCHED `.yitc/` path stays foreign → still blocks.

    ALSO folds a capture-time reopen's paired `errors/E-XXXX.yaml` flip (T-0615 — see
    `_capture_reopen_errors_dirt`): the deterministic file-half of an append the fold already carries,
    copied onto the branch + staged so it reaches main via the ff PAIRED with its event (no
    event-vs-file desync), without widening the static `_BOOKKEEPING_ALLOWLIST`.

    ONE fold implementation, TWO call-sites (anti-cx F1, T-0229): land step-2b (folded by step-3's
    reconcile commit; `reset_main=False`) AND inside the lock pre-ff (caller commits immediately —
    closes the E-0006 journal-dirt ff-starvation window; resets). `EVENTS_PATH` is the branch's events
    path at both sites."""
    branch_wt = EVENTS_PATH.parent
    # T-11372: ONE classification (SPEC-0188 rule 4) — the subtraction that used to be inline here now
    # lives in `_main_dirt_verdict`, so `cmd_land`'s P0 arm can ask the SAME question without folding.
    verdict = _main_dirt_verdict(main_wt, branch_wt, _run_git_cap=_run_git_cap,
                                 _BOOKKEEPING_ALLOWLIST=_BOOKKEEPING_ALLOWLIST,
                                 _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                                 _capture_reopen_errors_dirt=_capture_reopen_errors_dirt,
                                 _is_yitc_session_state=_is_yitc_session_state)
    # ERROR LEG — WRITTEN OUT, NOT CHANGED (audit-pre finding, T-11372). This polarity is PRE-EXISTING:
    # the former inline read never checked git's returncode, so a failed `git status` produced empty
    # stdout → an empty dirty set → `return False`. Extracting the read into a helper made that path
    # NAMEABLE, and an inherited-from-a-swallowed-returncode polarity is exactly the kind a future
    # author flips by accident, so it is now explicit and pinned by a characterization arm
    # (tests/test_t11372_foreign_main_dirt_preflight.py). Whether this backstop SHOULD fail closed is a
    # real question and a recorded finding — it is NOT decided inside a placement card, which changes
    # only WHERE the question is asked, never WHAT counts as foreign dirt.
    if verdict["verdict"] == "error":
        return False
    main_dirty = verdict["main_dirty"]
    if not main_dirty:
        return False
    capture_reopen = verdict["capture_reopen"]
    nonbk = verdict["foreign"]
    if nonbk:
        # CORRECT refusal — NOT a bug (T-0541). Foreign uncommitted SOURCE dirt on the shared main
        # checkout (e.g. a concurrent session's mis-targeted edit) MUST block the ff; folding it would
        # bury another session's work. This is DISTINCT from the auto-foldable replayable bookkeeping:
        # (a) the E-0010/T-0254 journal/derived dirt below, and (b) the T-0615 capture-reopen
        # errors/E-XXXX.yaml flip subtracted above (the deterministic file-half of an `error_reopened`
        # append the fold carries — NOT foreign work). Do NOT widen _BOOKKEEPING_ALLOWLIST to silence
        # this. A backgrounded worker that hits this returns blocked-on-land + worktree-intact and the
        # CONTROLLER resolves — never touch the foreign work (cross-session safety):
        # patterns/background-session-monitoring.md §Abnormal → "Foreign uncommitted SOURCE dirt ...".
        # T-11929: the WHOSE clause is DERIVED by the verdict (against the landing branch), never
        # asserted here. `.get` keeps a stand-in verdict from a test double honest — an absent key
        # renders "undetermined", never the accusation.
        _die(_foreign_main_dirt_message(main_wt, nonbk, verdict.get("ownership", "undetermined")))
    changed = False
    # Fold each capture-reopen errors/ flip onto the branch (mirror of the events.jsonl union-fold
    # below) — copy main's working version + stage it; the caller's reconcile / pre-ff commit (both
    # `git commit` the whole index) carries it to main via the ff, paired with its folded event.
    # CONTENT-CONDITIONAL (T-10245): report `changed` only on a real difference. Under the step-2b
    # `reset_main=False` path main keeps its errors/ flip until the pre-ff re-fold, which therefore
    # re-sees a path step-2b already folded; an unconditional `changed = True` there would stage
    # nothing (identical content) yet drive `_land_bookkeeping_commit` — and on its non-amend leg
    # (a merge intervened, so HEAD != the sha this land minted) `git commit` on an empty index fails
    # → a spurious `refold-commit-failed` _die.
    for rel in sorted(capture_reopen):
        src = (main_wt / rel).read_text(encoding="utf-8")
        dst = branch_wt / rel
        if dst.exists() and dst.read_text(encoding="utf-8") == src:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src, encoding="utf-8")
        _run_git_cap(["add", "--", rel], branch_wt)
        changed = True
    # Union every append-only JOURNAL dirty on main into the LANDING BRANCH — the root events.jsonl
    # AND any `.yitc/events.jsonl` hook-tail (T-0871) — keeping BOTH sides' rows. ONE loop (anti-cx
    # F1) replaces the former root-only block; the branch path == `branch_wt / jrel` (== EVENTS_PATH
    # for the root journal). Each unioned journal is staged so the caller's reconcile / pre-ff commit
    # (`git commit` of the whole index) carries it to main via the ff (the root journal is also in
    # `_BOOKKEEPING_ALLOWLIST` → re-staged by step-3; staging here too is harmless + makes the
    # `.yitc/` journal reach main without widening the static allowlist — mirror of capture_reopen).
    for jrel in sorted(p for p in main_dirty if _is_foldable_journal(p)):
        mp = main_wt / jrel
        bp = branch_wt / jrel
        main_lines = mp.read_text(encoding="utf-8").splitlines() if mp.exists() else []
        # T-10734: hold the BRANCH journal's OWN sidecar `journal_lock` across the read-modify-write
        # CYCLE below. Both call sites already lock MAIN's journals (step-2b / the pre-ff section) —
        # but the file this fold MUTATES is the BRANCH's, and it was written under no lock at all. That
        # is the writer-side rule of `lessons/land-critical-section-locks-every-journal-it-folds.md`
        # (SPEC-0168 rule 6) applied to the journal it was still missing.
        # WHAT THIS FIXES — the LOST-UPDATE half, which T-10755's atomic write does NOT touch. That
        # change made the swap a temp+`os.replace`, so no reader can observe an empty/prefix journal;
        # the TORN-READ half is closed and needs no lock. But atomicity says nothing about the CYCLE:
        # read(bp) → union/dedup → replace(bp) is a read-modify-write, so a lock-taking `append_event`
        # to this same branch journal that lands BETWEEN the read and the replace is silently
        # overwritten by the replace — evidence loss, invisible, exactly the E-0021 class the main-side
        # lock already closes on main's journals.
        # LOCK ORDER (checked against the existing main-side acquisition, as the card asks): MAIN
        # journals OUTER, BRANCH journal INNER, always. Both call sites enter their main root+hook-tail
        # locks and only then call this fold, and no site anywhere takes a main-journal lock while
        # holding a branch-journal one — so the order is total and two concurrent lands cannot cycle.
        # (Independently: a `task/`/`work/` branch journal lives in ONE land's private worktree, so two
        # lands do not even contend for the same branch sidecar; the ordering argument is the belt.)
        # DEGENERATE CASE — branch_wt == main_wt (resolved): then `bp` IS the journal the CALLER
        # already flocked. `flock` is per-fd, so re-acquiring LOCK_EX on a second fd from this same
        # process would block on ourselves — a self-deadlock. Skip the acquire there; the caller's lock
        # already covers the file, so coverage is unchanged.
        # HOLD DURATION — deliberately the SHORTEST window that is still a lock: ONE journal's RMW
        # cycle, re-entered per journal, and NOT the whole fold (main's read above stays outside, under
        # the caller's main lock) and NOT verify. Shorter is not a lock at all — the cycle IS the race
        # — while anything longer would stall every concurrent session appending to this repo's ~111MB
        # journal behind a land. Same discipline the main-side sites already state: "held only for this
        # short fold — NOT across verify — so appenders are not starved".
        with contextlib.ExitStack() as _branch_journal_lock:
            if branch_wt.resolve() != main_wt.resolve():
                _branch_journal_lock.enter_context(events.journal_lock(bp))
            branch_lines = bp.read_text(encoding="utf-8").splitlines() if bp.exists() else []
            merged = _dedup_events(branch_lines + main_lines)
            if merged != [ln for ln in branch_lines if ln]:
                bp.parent.mkdir(parents=True, exist_ok=True)
                # T-10755: ATOMIC rewrite (temp + rename), never a truncating `write_text`. SPEC-0168 rule 6
                # names THIS write as the truncate-window hazard: `open('w')` truncates AT open, so a
                # reader inside the multi-MB rewrite observes an EMPTY or PREFIX journal — the T-0369
                # land false-fails, and the ~57 MB-of-~110 MB `UnicodeDecodeError` that task exists to
                # end. The T-10734 lock now wrapping this cycle does NOT make the atomic write
                # redundant, and vice versa — they close DIFFERENT halves and neither subsumes the
                # other: atomicity reaches EVERY reader (a NON-lock-taking one, and the pinned
                # last-green engine's reader, which no lock of ours can serialize) but cannot protect a
                # read-modify-write CYCLE; the lock serializes lock-taking WRITERS across that cycle but
                # would leave a non-locking reader torn. Rename-within-a-directory is atomic on POSIX
                # and is explicitly SAFE for the sidecar design: `journal_lock`'s own docstring already
                # anticipates it ("a future temp-file+rename would swap its inode ... the sidecar is
                # O_CREAT-only, never truncated/renamed, so its inode is stable") — which is exactly why
                # the two compose instead of fighting: the lock is on the STABLE sidecar inode, not on
                # the data file this replaces. The union+dedup SEMANTICS are untouched — same text, same
                # order, same keep-first identity; only the write SHAPE changed. Reuses the ONE
                # `write_text_atomic` (injected — it lives in the non-importable CLI script, the same
                # seam SPEC-0168 rule 3 prescribes), never a second implementation.
                write_text_atomic(bp, "".join(ln + "\n" for ln in merged))
                _run_git_cap(["add", "--", jrel], branch_wt)
                changed = True
    # Clean main's working tree so the journal/derived dirt cannot block the ff (D-0049 fold-promise).
    # SKIPPED when `reset_main` is False (T-10245 — land's step-2b): the union above already carried
    # every row onto the branch, so main's loose copy is now redundant-but-READABLE, and leaving it
    # keeps a concurrent interactive session's identity backing (its `session_started` anchor +
    # `cli:seed` receipt) resolvable for the whole verify. The ff's clean-tree precondition is owed by
    # the pre-ff re-fold, which resets INSIDE the journal_lock immediately before the ff.
    # A TRACKED-dirty path is restored to HEAD (clears index+worktree; HEAD not bare `checkout --`,
    # which restores from the INDEX and leaves a STAGED allowlist change behind → a later refusal,
    # T-0105). An UNTRACKED path is NOT in HEAD, so `checkout HEAD --` silently NO-OPS and the file
    # PERSISTS — and the branch's TRACKED copy then cannot ff (git refuses to overwrite an untracked
    # working-tree file), which the ff-failed residual-dirt retry misreads as "main advancing" and
    # loops to exhaustion (T-9464 — the FIRST-land consumer whose root events.jsonl is not yet
    # committed). Everything still in main_dirty here has passed the nonbk guard above (substantive/
    # foreign SOURCE dirt already `_die`d), so it is all REPLAYABLE bookkeeping — journals (content
    # already unioned onto the branch), derived graph/index.json (rebuilt), .yitc/ session state
    # (take-latest); REMOVE the untracked copies so the ff brings the branch's TRACKED version back,
    # losing nothing. `git clean -f -d` handles untracked files AND dirs uniformly and never touches
    # gitignored paths (this dirt came from porcelain `??`, not `!!`). For the engine's OWN land both
    # journal + graph are TRACKED and `.yitc/` is gitignored → the untracked set is empty and behaviour
    # is byte-identical to the prior single `checkout HEAD`.
    if reset_main:
        tracked = sorted(_tracked_paths(main_dirty, main_wt, _run_git_cap))   # T-11506: one call, not one per path
        untracked = sorted(set(main_dirty) - set(tracked))
        if tracked:
            _run_git_cap(["checkout", "HEAD", "--", *tracked], main_wt)
        if untracked:
            _run_git_cap(["clean", "-f", "-d", "--", *untracked], main_wt)
    return changed


def _main_journal_snapshot(main_wt: Path, main_dirty, *, _is_foldable_journal) -> "dict[str, list[str]]":
    """Leg 1 of the pre-ff journal unwind (T-10723 / E-0055): capture main's WORKING content for every
    foldable journal that is dirty on main, BEFORE `_fold_main_journal_into_branch` resets it.

    The pre-ff re-fold RESETS main's working tree (`git checkout HEAD -- <tracked>`), which strips
    every UNCOMMITTED main-side row — and D-0049 SANCTIONS exactly those rows (a no-worktree `event`
    append from the main checkout: a deviation capture, a `session_started` anchor, a `cli:seed`
    receipt). The reset is owed ONLY to the ff's clean-tree precondition, so it is safe exactly while
    the ff FOLLOWS it. It does not always follow — hence this snapshot + `_restore_main_journals`.

    Scoped to `_is_foldable_journal` (the root `events.jsonl` + the `.yitc/events.jsonl` hook-tail):
    those are the append-only UNION journals whose rows must never be dropped. The non-append
    `.yitc/` YAMLs + the derived artifacts are take-latest/rebuilt by design and are deliberately NOT
    snapshotted — restoring them would resurrect state the fold correctly discards.

    PURE apart from the reads (returns plain data), so the unwind is unit-testable without git."""
    snapshot = {}
    for jrel in sorted(p for p in main_dirty if _is_foldable_journal(p)):
        mp = main_wt / jrel
        snapshot[jrel] = mp.read_text(encoding="utf-8").splitlines() if mp.exists() else []
    return snapshot


def _restore_main_journals(snapshot, main_wt: Path, *, _dedup_events, write_text_atomic=None) -> "list[str]":
    """Leg 2 of the pre-ff journal unwind (T-10723 / E-0055): UNION the pre-fold snapshot back into
    main's working journals when the ff did NOT follow the reset. Returns the restored `jrel`s.

    WHY THE SNAPSHOT ALONE IS NOT ENOUGH — the same argument deploy.py's `_journal_union_restore`
    makes at the sibling ROLLBACK seam (T-10633 / X-0479): folding + resetting only unblocks the tree
    switch, it does not SURVIVE one that never happens. On the ff-SUCCESS path nothing is owed — the
    ff writes the branch's unioned content into main's working tree, so the rows come back by
    construction. On every other path they do not:
      (M1) `_land_bookkeeping_commit` fails -> `refold-commit-failed` _die: the branch commit never
           happened, so main's stripped working file was the ONLY carrier of those rows.
      (M2) `merge --ff-only` fails -> the residual-dirt retry: main would stay stripped for the WHOLE
           next verify (minutes), re-opening precisely the T-10245 window step-2b's `reset_main=False`
           closed.
      (M3) that ff failure on a non-retriable residual, or `_LAND_MAX_RETRIES` exhaustion -> _die:
           main stays stripped permanently.
    In all three, those rows are the ONLY live backing for a concurrent interactive session's carried
    `YITC_SESSION_REF` (SPEC-0137 Rule 2.1 path (b) — path (a), a live runtime record, is structurally
    dead under a headless harness), so `_require_seed_read` / `_require_help_read` then refuse BOTH
    `worktree new` AND `land` for that session until a manual re-anchor. That is E-0055.

    UNION, NEVER OVERWRITE. Per journal: `_dedup_events(current + snapshot)` — CURRENT first so a row
    written after the reset keeps its position under keep-first dedup, and no row from EITHER side is
    ever dropped. That is what makes "no journal line lost" structural rather than best-guess (the
    rule stated at the rollback seam, reusing the SAME `_dedup_events` single home — CHARTER §P5, so
    the dedup KEY has one definition, not two). Written back ONLY on a real difference, so a journal
    that already holds everything is left byte-untouched.

    Restoring re-dirties ONLY `events.jsonl` / `.yitc/events.jsonl`, which the ff-failed residual
    check already classifies as the benign retriable bookkeeping class — so this adds no abort_class,
    no refusal, and no change to the retry budget. Main simply returns to the sanctioned D-0049 dirty
    state it was in before the fold.

    ATOMIC WRITE-BACK (T-10755). This rewrites MAIN's journal, so it takes the same temp+rename shape
    as the fold's branch-journal write. Defence in depth rather than load-bearing here: every call site
    is already INSIDE the pre-ff `journal_lock`, which — once a reader's sidecar is resolved
    env-independently (`events._persistent_lock_root`) — genuinely serialises lock-taking readers.
    `write_text_atomic` is OPTIONAL solely for SPEC-0077 back-compat: the pinned last-green verify runs
    merged_base's `tests/` against the CANDIDATE `bin/**`, and merged_base's
    `test_t10723_land_preff_unwind_preserves_main_anchor` calls this helper module-DIRECTLY without the
    dep. Making it required would TypeError under the pinned run and abort every land. Production never
    reaches the fallback — `_land_integrate` injects it at both call sites, which
    `test_t10755_land_injects_atomic_writer_at_every_journal_rewrite` asserts from source."""
    restored = []
    for jrel, snap_lines in sorted(snapshot.items()):
        mp = main_wt / jrel
        current = mp.read_text(encoding="utf-8").splitlines() if mp.exists() else []
        merged = _dedup_events(current + list(snap_lines))
        if merged == current:
            continue          # already holds everything — leave the file byte-untouched
        mp.parent.mkdir(parents=True, exist_ok=True)
        _text = "".join(ln + "\n" for ln in merged)
        if write_text_atomic is not None:
            write_text_atomic(mp, _text)
        else:
            mp.write_text(_text, encoding="utf-8")   # pinned-verify back-compat only (see docstring)
        restored.append(jrel)
    return restored
# ── SPEC-0168 rule 5 — evidence CUSTODY at the land seam (T-10731, X-0558) ───────────────────────
# Rule 4 lets the audit packet CREDIT evidence that lives only in main's uncommitted tail ("present,
# sourced from main, not yet landed"). Rule 5 is what keeps that honest: the land seam verifies the
# credited rows ACTUALLY ARRIVED in the committed journal, and REPORTS LOUDLY when they did not — so a
# task cannot permanently pass audit-post on evidence that never landed.
#
# REPORT-ONLY IS THE CONTRACTED FLOOR, and this is the whole behaviour shipped here (T-10731 scope /
# SPEC-0168 rule 5 as amended by plan-check finding 1). Escalating to a REFUSAL is PERMITTED by the
# rule but deliberately NOT taken: gating land on a check whose false-positive rate is unmeasured
# would trade a false RED at audit-post for a false ABORT at land — the same class of defect X-0558
# is. The call site therefore adds NO abort path and cannot change land's exit status.
#
# THREE NON-LANDING MODES, NEVER ONE "missing" (trial run 2, 2026-08-06 — all three reproduced in an
# isolated repo). They have different remedies, and a single collapsed message is the shape that gets
# muted, so the classifier below keeps them apart and the renderer prints one section per mode.
_CUSTODY_MODE_ABORTED = "aborted"       # (a) still on main's disk, not committed — RECOVERABLE
_CUSTODY_MODE_LOST = "lost"             # (b) gone from disk entirely — a genuine LOSS
_CUSTODY_MODE_READER_SET = "reader_set"  # (c) from a structurally unlandable instance — READER defect


def _journal_keys(path, *, _event_dedup_key) -> dict:
    """`{dedupe key: raw line}` for one journal instance. Read-only + tolerant: an absent/unreadable
    instance is ORDINARY (rule 1) and yields `{}`; a key-function failure degrades to raw-line
    identity, exactly as the readers' `_folded_journal_events` does (never drop a row silently)."""
    out = {}
    try:
        if not path or not Path(path).exists():
            return out
        lines = [ln for ln in (l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines()) if ln]
    except OSError:
        return out
    for ln in lines:
        try:
            key = _event_dedup_key(ln)
        except Exception:            # noqa: BLE001 — mirrors the reader's tolerant key contract
            key = ln
        out.setdefault(key, ln)      # keep-first, the write side's own identity discipline
    return out


def _custody_counted_keys(tid: str, W: Path, main_wt: Path, *, _event_dedup_key, _journal_keys=None) -> dict:
    """The rows the audit packet COUNTED for `tid`, as `{dedupe key: raw line}`.

    Same three rules the packet reader applies, and the SAME single homes for each — no second
    definition of either (rule 3's anti-drift is about the KEY function and the task-id CARRIER, and
    both are taken from their one home): rule 1's evidence set = the LANDABLE root `events.jsonl` of
    the two instances (the branch being landed + main), never the gitignored `.yitc/` hook-tail;
    rule 2's DUAL task-id carrier via `task_mod._event_task_id`; rule 3's identity via the injected
    `_event_dedup_key`. The fold's ORDER is irrelevant here and no provenance mark is needed — a SET
    of keys is what custody compares, and set-collapse == the reader's keep-first dedupe.

    MUST be called under the fold's `journal_lock` discipline (rule 6): the fold writes main's journal
    with a truncating `write_text`, so an unlocked read inside that window sees an EMPTY or PREFIX
    journal and would count nothing — an unlocked reader here would re-create X-0558 by another route
    AND fire this very custody check spuriously."""
    counted = {}
    if not tid:
        return counted        # a `work/` branch has no task — custody is a per-task property (rule 2)
    try:
        for jp in (W / "events.jsonl", main_wt / "events.jsonl"):
            for key, line in _journal_keys(jp, _event_dedup_key=_event_dedup_key).items():
                if key in counted:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict) and task_mod._event_task_id(ev) == tid:
                    counted[key] = line
    except Exception:          # noqa: BLE001 — degrade to "no custody check"; NEVER a land fault, and
        return {}              # the call site stays one line so the fold's lock-proximity guard holds
    return counted


def _custody_classify(counted: dict, *, committed_keys, main_disk_keys, hook_tail_keys) -> dict:
    """Split the counted rows that are ABSENT from the post-land COMMITTED journal into the three
    non-landing modes. Returns `{mode: [raw line, …]}`, empty lists included — a row that DID land is
    not a finding and appears nowhere.

    The discriminator is the one confirmed workable in trial run 2: a set difference of the counted
    keys against the committed keys, then ON-DISK PRESENCE separates (a) from (b). The hook-tail is
    tested FIRST because it is the one absence that is not about this land at all: such a row is on
    disk forever and committable never, so reporting it as lost evidence would fire the check forever
    and get it muted — it is a defect in the READER SET (rule 1 scoping), and must be named as one.
    Rule 1 as corrected makes (c) unreachable; it is kept as a live tripwire, not as dead code."""
    modes = {_CUSTODY_MODE_ABORTED: [], _CUSTODY_MODE_LOST: [], _CUSTODY_MODE_READER_SET: []}
    for key, line in counted.items():
        if key in committed_keys:
            continue
        if key in hook_tail_keys and key not in main_disk_keys:
            modes[_CUSTODY_MODE_READER_SET].append(line)
        elif key in main_disk_keys:
            modes[_CUSTODY_MODE_ABORTED].append(line)
        else:
            modes[_CUSTODY_MODE_LOST].append(line)
    return modes


_CUSTODY_MODE_TEXT = {
    _CUSTODY_MODE_ABORTED: ("still on main's disk but NOT COMMITTED (a land did not carry it) — "
                            "RECOVERABLE: re-run land from the main checkout"),
    _CUSTODY_MODE_LOST: ("GONE FROM DISK — a genuine LOSS: the audit packet counted evidence that no "
                         "longer exists anywhere (main's dirt was discarded before land). "
                         "RECOVER: re-emit the evidence, then re-run the acceptance probe"),
    _CUSTODY_MODE_READER_SET: ("sourced from a STRUCTURALLY UNLANDABLE instance (the gitignored "
                               ".yitc/ hook-tail) — this is a READER-SET defect, NOT lost evidence: "
                               "SPEC-0168 rule 1 scopes the evidence set to landable instances. "
                               "FIX THE READER; the row can never be committed"),
}


def _custody_report_lines(tid: str, modes: dict, *, counted_total: int) -> "list[str]":
    """Render the loud report — ONE SECTION PER MODE, never a single collapsed "evidence missing".
    Returns `[]` when every counted row landed: SILENCE IS THE DISCRIMINATOR, so a clean land stays
    byte-identical on stdout/stderr and the report means something when it does appear."""
    if not any(modes.values()):
        return []
    total = sum(len(v) for v in modes.values())
    out = [f"land: EVIDENCE CUSTODY — {total} of {counted_total} audit-packet-counted event row(s) for "
           f"{tid} did NOT land (SPEC-0168 rule 5; report-only, this land is unaffected):"]
    for mode in (_CUSTODY_MODE_ABORTED, _CUSTODY_MODE_LOST, _CUSTODY_MODE_READER_SET):
        rows = modes.get(mode) or []
        if not rows:
            continue
        out.append(f"  [{mode}] {len(rows)} row(s) — {_CUSTODY_MODE_TEXT[mode]}")
        for line in rows:
            out.append(f"    {line[:300]}")
    return out


def _custody_committed_keys(W: Path, main_wt: Path, *, _run_git_cap, _event_dedup_key) -> set:
    """The keys a counted row can be considered SAFE under: the COMMITTED root journal of main AND of
    the branch being landed. Both, because this reader serves BOTH custody seams and must apply ONE
    comparison rule at each (a second rule is the drift SPEC-0168 rule 3 exists to prevent).

    Why the branch side belongs here. On the ff-SUCCESS seam main HEAD *is* the branch tip, so the
    branch adds nothing — the set is the same. On the ABORT seam it is decisive: every row the branch
    already committed is on its way to main and will land with the next attempt, so treating those as
    missing would print a "genuine loss" report on ORDINARY aborted lands — the false-positive flood
    that gets a custody check muted, which is exactly what rule 5 must not become."""
    # T-11444 / SPEC-0190 rule 4b — SPEC-0190 names this reader as the FIFTH git-revision one, the
    # member rule 4b's own enumeration missed (A1's census found it). Custody asks whether a counted
    # evidence row is committed ANYWHERE the logical journal lives, so it must span the segment set at
    # HEAD on both checkouts: a row that rotated into an archive segment is safe, and reading the live
    # segment alone would report it as a "genuine loss" that never happened — the false-positive flood
    # this reader's docstring above says must not become the norm.
    keys = set()
    for cwd in (main_wt, W):
        try:
            # T-11805 — ONE git process for the whole fold where that is safe (this reader pays the
            # fork-per-segment cost TWICE, once per checkout). Same segments, same fold order, same
            # bytes; the seam falls back to the per-segment argvs whenever the batch would not be
            # complete, so a missing journal at HEAD still degrades exactly as it did before.
            argvs = journal_mod.revision_segment_show_argvs(
                "HEAD", cwd, run=lambda a, _c=cwd: _run_git_cap(a, _c))
        except OSError:
            continue
        for argv in argvs:
            try:
                r = _run_git_cap(argv, cwd)
            except OSError:
                continue
            if r.returncode != 0:
                continue                      # no such checkout / no committed journal — ordinary
            for ln in (l.strip() for l in r.stdout.splitlines()):
                if not ln:
                    continue
                try:
                    keys.add(_event_dedup_key(ln))
                except Exception:             # noqa: BLE001 — the tolerant key contract
                    keys.add(ln)
    return keys


def _custody_emit_report(tid, counted, W: Path, main_wt: Path, *, _run_git_cap, _event_dedup_key,
                         stream=None, _custody_classify=None, _custody_committed_keys=None, _custody_report_lines=None, _journal_keys=None) -> "list[str]":
    """Both custody seams in ONE place: classify the counted rows, render, print to stderr. Returns
    the printed lines (`[]` = every counted row is accounted for → total silence).

    NEVER RAISES, on any path — a custody defect must not become a land failure (T-10731 AC3). That is
    the reason the whole body is inside a bare `except`: the two call sites are the ff-success tail and
    the abort unwind, and neither may acquire a new way to fail."""
    try:
        if not (tid and counted):
            return []
        modes = _custody_classify(
            counted,
            committed_keys=_custody_committed_keys(W, main_wt, _run_git_cap=_run_git_cap,
                                                   _event_dedup_key=_event_dedup_key),
            main_disk_keys=set(_journal_keys(main_wt / "events.jsonl",
                                             _event_dedup_key=_event_dedup_key)),
            hook_tail_keys=set(_journal_keys(main_wt / ".yitc" / "events.jsonl",
                                             _event_dedup_key=_event_dedup_key)))
        lines = _custody_report_lines(tid, modes, counted_total=len(counted))
        for line in lines:
            print(line, file=stream if stream is not None else sys.stderr)
        return lines
    except Exception:                          # noqa: BLE001 — custody never fails a land
        return []
