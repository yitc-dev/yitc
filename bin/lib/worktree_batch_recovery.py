"""worktree_batch_recovery — the KILLED-LAND arm of `worktree recover-land` (T-11559).

WHY THIS IS ITS OWN MODULE, AND NOT PART OF `worktree_lifecycle.py`. Two reasons, and they agree.
(1) SUBJECT. `worktree_lifecycle.py`'s own boundary statement is that the LAND path's tree —
`cmd_land` and its batch-landing helpers (SPEC-0184) — stays OUT of it by construction. This arm's
whole subject is a half-formed SPEC-0184 BATCH: it reads `land_batch_formed.member_tips`, classifies
the land's own bookkeeping commit, and re-appends the rows the land had folded. It is a land-seam
concern that a worktree-lifecycle verb happens to be the door to, so it belongs beside the land
concern it is about. (2) SEAM. T-11522's extraction contract requires every top-level definition in
`worktree_lifecycle.py` to carry a forwarding residue under its historical name in the host
`bin/lib/worktree.py`; that host file is owned by a neighbouring plan and is deliberately NOT touched
by this card, so a body added there would have had to be added to a file this task may not edit.

WIRING. `cli.py#cmd_worktree_recover_land` binds `cmd_batch_residue` (with its host collaborators)
into the `_recover_land_batch_residue` injection point on
`worktree_lifecycle.cmd_worktree_recover_land`, which dispatches to it when `--batch-residue` is set.
Nothing here is imported by `worktree_lifecycle.py`.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib; it imports
neither the host nor any sibling `bin/lib` module — every collaborator arrives by keyword injection.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# ── T-11559 — the KILLED-LAND arm of `worktree recover-land` (SPEC-0184 rule 4's honest bound) ────
# THE ASYMMETRY THIS CLOSES. A batch merges its PEERS into the head member's own branch. On every
# end where the batch does not land, `_land_restore_candidate_head` (T-11226) + T-11467's
# bookkeeping rollback take them back off — but both run from a `finally`, and a process KILLED
# outright (the harness's hard per-call cap; measured twice on 2026-08-26) runs no `finally`. So the
# GRACEFUL end is covered and the VIOLENT one is not, exactly under the contention that makes
# batching worth having. `_land_batch_foreign_merges` / `_land_contamination_advisory` already
# DETECT the residue and say so on the land preflight — but their remedy line hands the operator RAW
# GIT. This arm is the governed verb that detector was missing.
#
# WHY A THIRD ARM AND NOT A NEW VERB (CHARTER §P1 F1). Same shape as the two arms above — observe →
# fail-closed liveness → restore → hand back — differing only in WHAT is observed (a peer's merge
# commits, not a closure record or an absent worktree) and WHAT is restored (the branch's pre-batch
# tip, not a worktree). It mints no event type (`land_batch_head_restored` is the row the in-process
# restoration already writes) and no store: the pre-batch tip is READ from `land_batch_formed`'s
# `member_tips`, which T-11517 put there for precisely this reason — "RECORD WHAT BECOMES
# UNRECOVERABLE".
_RECOVER_RESIDUE_BOOKKEEPING_SUBJECT_RE = re.compile(r"^(?:land|worktree sync): bookkeeping \(")

# The paths a land/sync bookkeeping commit is allowed to carry. The SUBJECT alone is forgeable
# (T-9799 refused to identify an amend target by subject for exactly that reason), so eligibility
# here is subject AND footprint: a commit wearing the subject but carrying authored content fails
# the footprint test and the whole recovery REFUSES rather than discarding it.
_RECOVER_RESIDUE_BOOKKEEPING_PATHS = ("events.jsonl",)
_RECOVER_RESIDUE_BOOKKEEPING_PREFIXES = ("graph/",)


def _residue_bookkeeping_only(sha: str, W: "Path", _run_git_cap) -> bool:
    """True iff `sha` is a single-parent commit whose subject AND changed-file footprint are both a
    land/sync bookkeeping commit's. Unreadable ⇒ False — an unanswerable question never licenses a
    discard (the fail-closed direction the whole arm takes)."""
    try:
        r = _run_git_cap(["show", "--no-patch", "--format=%P%x00%s", sha], W)
        if getattr(r, "returncode", 1) != 0:
            return False
        parents_raw, _, subject = (getattr(r, "stdout", "") or "").strip().partition("\x00")
        if len(parents_raw.split()) != 1:
            return False
        if not _RECOVER_RESIDUE_BOOKKEEPING_SUBJECT_RE.match(subject.strip()):
            return False
        f = _run_git_cap(["show", "--name-only", "--format=", sha], W)
        if getattr(f, "returncode", 1) != 0:
            return False
        paths = [p.strip() for p in (getattr(f, "stdout", "") or "").splitlines() if p.strip()]
        if not paths:
            return False
        return all(p in _RECOVER_RESIDUE_BOOKKEEPING_PATHS
                   or p.startswith(_RECOVER_RESIDUE_BOOKKEEPING_PREFIXES) for p in paths)
    except Exception:                          # noqa: BLE001 — an unreadable commit is never eligible
        return False


def _residue_pre_batch_tip(branch: str, foreign: "list[dict]", W: "Path", *,
                           _segment_lines, _events_path, _run_git_cap) -> "tuple[str | None, str]":
    """Resolve this branch's PRE-BATCH tip from the journal. Returns `(tip, why_not)` — exactly one
    of the two is meaningful, and `tip` is None whenever the answer is not PROVEN.

    THE SOURCE IS `land_batch_formed.member_tips` (T-11517), read NEWEST-FIRST, and it is the reason
    this recovery can exist at all: those tips are resolved ABOVE the peer merge, so they are the one
    record of where the head member's branch stood before the batch touched it. Reading the branch
    itself cannot answer this — post-merge state is indistinguishable from pre-existing state, which
    is the retraction T-11517's own docstring records.

    A row qualifies only when its recorded tip is (i) a resolvable commit, (ii) an ANCESTOR of the
    branch's current HEAD, and (iii) strictly BELOW every foreign merge found on the branch. (iii) is
    what makes the answer this batch's rather than an older one's: a tip that does not sit under all
    of the residue would leave part of it behind.

    Segment-aware by construction — `_segment_lines` is the shipped `journal.segment_lines` (SPEC-0190
    rule 4). A raw read of the journal PATH sees the live segment only and would report an older
    formation as absent, which here would read as "no evidence" and REFUSE a recoverable branch."""
    if _segment_lines is None or _events_path is None:
        return (None, "the journal reader was not injected, so no formation record can be read")
    rows = []
    try:
        for line in _segment_lines(_events_path):
            if "land_batch_formed" not in line:
                continue                        # cheap prefilter before the parse — this scans history
            try:
                e = json.loads(line)
            except Exception:                   # noqa: BLE001 — a malformed row is not evidence
                continue
            if (e or {}).get("type") != "land_batch_formed":
                continue
            rows.append(e)
    except Exception as exc:                    # noqa: BLE001
        return (None, f"the journal could not be read ({type(exc).__name__}: {exc})")
    if not rows:
        return (None, "no `land_batch_formed` row exists at all")

    foreign_shas = [str(f.get("sha") or "") for f in (foreign or ()) if f.get("sha")]
    seen_any = False
    for e in reversed(rows):                    # NEWEST first
        for mt in ((e.get("data") or {}).get("member_tips") or ()):
            if str((mt or {}).get("branch") or "") != branch:
                continue
            seen_any = True
            tip = str((mt or {}).get("tip") or "").strip()
            if not tip:
                continue                        # a null tip is recorded as a FACT, never a guess
            try:
                if _run_git_cap(["rev-parse", "--verify", "--quiet", f"{tip}^{{commit}}"],
                                W).returncode != 0:
                    continue
                if _run_git_cap(["merge-base", "--is-ancestor", tip, "HEAD"], W).returncode != 0:
                    continue
                if any(_run_git_cap(["merge-base", "--is-ancestor", tip, s], W).returncode != 0
                       or tip == s for s in foreign_shas):
                    continue                    # the residue is not wholly ABOVE this tip
            except Exception:                   # noqa: BLE001 — an unprovable tip is not a tip
                continue
            return (tip, "")
    if seen_any:
        return (None, f"every `land_batch_formed` row naming {branch} records a tip this branch "
                      f"cannot be proven to sit above (unresolvable, not an ancestor of HEAD, or not "
                      f"below every foreign merge)")
    return (None, f"no `land_batch_formed` row names {branch} as a batch member — so nothing attests "
                  f"that a land batch put these merges here")


def cmd_batch_residue(target: str, *, is_work: bool, _append_event, _die, _main_worktree,
                                _worktree_path_for_branch, REPO_ROOT, _run_git_cap=None,
                                _land_proc_alive=None, _work_land_proc_alive=None,
                                _land_batch_foreign_merges=None,
                                _land_contamination_advisory=None,
                                _segment_lines=None, _events_path=None,
                                _RECOVER_LAND_WORK_SLUG_RE=None) -> None:
    """`worktree recover-land (--task T-XXXX | --work <slug>) --batch-residue` — return a branch that
    a KILLED land left carrying a half-formed SPEC-0184 batch to its PRE-BATCH tip. IDEMPOTENT and
    FAIL-CLOSED: it restores only what the journal PROVES a batch put there, and refuses everything
    else with the reason named.

    HOST BINDING, stated here because the diff cannot show it (`lessons/an-audit-cannot-see-the-
    unchanged-wrapper-that-injects-a-dep`): every `_`-prefixed collaborator below arrives by
    KEYWORD INJECTION from `cli.py#cmd_worktree_recover_land`, which forwards through
    `worktree.py#cmd_worktree_recover_land`'s `**kw` residue untouched. `_land_batch_foreign_merges`
    / `_land_contamination_advisory` are the SHIPPED T-11226 detector pair (host module
    `bin/lib/worktree.py`, read at call time so a `-C` rebind or a test monkeypatch is honoured);
    `_segment_lines` is `journal.segment_lines`. This function imports none of them.

    THE FIVE REFUSALS, and each is a different way the answer can fail to be provable:
      1. no git reader / no liveness probe injected — an unanswerable question never licenses a write;
      2. a land for this branch is PROVEN LIVE — recovery never races or respawns a live land, and
         this arm starts no land of its own. JOURNAL SILENCE IS NOT DEATH and is never read as such:
         the gate is a POSITIVE liveness probe (`_land_proc_alive` / the T-11137
         `_work_land_proc_alive` keyed on the `--branch work/<slug>` argv), never a worktree-presence
         count and never an inference from an absent or stale row
         (`lessons/a-presence-count-is-not-a-liveness-probe`);
      3. no `land_batch_formed` row attests this branch as a batch member — THE DIFFERENTIAL: a
         branch that merged a peer DELIBERATELY is never unwound, because nothing recorded a batch
         putting it there;
      4. a commit above the recorded tip is none of: a foreign peer merge, peer content that merge
         brought in (topologically, from the merges' SECOND parents — it stays on the peer's own
         branch, so dropping it here destroys nothing), a bookkeeping commit, already on `main`, or a
         catch-up merge OF `main` — THIS branch's AUTHORED commit is never
         destroyed to satisfy this arm (the eligibility posture of T-11467's own rollback walk);
      5. the worktree is gone — out of this arm's shape, and a ROUTE rather than a dead end: it names
         `worktree new` (the covering verb that restores a worktree) so the operator re-enters here.

    TWO IDEMPOTENT NO-OPS, each resting on a POSITIVE fact rather than on a missing value: the branch
    does not exist (already landed/deleted), and the branch carries no foreign merges (nothing to
    undo — which is the exit a SECOND run takes, so running it twice leaves the same state twice).

    NOTHING JOURNALED IS LOST, and no journal read is needed to achieve it. `events.jsonl` is
    append-only + union-merged, so a bare `git reset --hard` would discard the rows the killed land
    had folded. Rather than read-modify-write the file (T-11467's approach, correct in ITS place),
    this restores the pre-reset HEAD's blob into the WORKING TREE with git after the reset: on this
    branch that blob is a SUPERSET of the tip's, because appends only ever add — so every row is
    preserved by construction, with no read, no dedup and no temp file. `--worktree` only, so the
    rows land back as ordinary trailing DIRT for the next land's fold and this recovery stages
    nothing.
    """
    branch = f"work/{target}" if is_work else f"task/{target}"
    if is_work:
        if not re.fullmatch(_RECOVER_LAND_WORK_SLUG_RE or r"[a-z0-9]+(?:-[a-z0-9]+)*", target or ""):
            _die(f"worktree recover-land: --work slug must be kebab-case [a-z0-9-], got {target!r}")
    elif not re.fullmatch(r"T-\d{4,}", target or ""):
        _die(f"worktree recover-land: invalid --task id {target!r} (expected T-NNNN)")

    probe = _work_land_proc_alive if is_work else _land_proc_alive
    if _run_git_cap is None or probe is None or _land_batch_foreign_merges is None:
        _die("worktree recover-land: REFUSED — the git reader / land-liveness probe / batch-residue "
             "detector was not injected, so this recovery cannot observe the branch it would rewrite "
             "(fail-closed).")

    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    if _run_git_cap(["rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}"],
                    main_wt).returncode != 0:
        print(f"worktree recover-land: no branch {branch} — already landed/deleted; nothing to "
              f"restore (idempotent no-op).")
        return

    # LIVENESS BEFORE ANYTHING ELSE — a live land is mid-batch by definition, and the merges on the
    # branch are its working state, not residue.
    if probe(target):
        _die(f"worktree recover-land: REFUSED — a LIVE `land` proc for {branch} is in flight. Its "
             f"peer merges are that land's working state, not residue; wait for it to reach "
             f"`LAND: OK`/`LAND: ABORT` (its own `finally` restores the branch on every non-landing "
             f"end), then re-run this if anything is left.")

    wt = _worktree_path_for_branch(branch)
    if wt is None or not Path(wt).exists():
        _die(f"worktree recover-land: REFUSED — {branch} has no live worktree, and this arm rewrites "
             f"a branch IN its worktree. Restore one with the covering verb "
             f"`bin/yitc-v2 worktree new --{'work' if is_work else 'task'} {target}`, then re-run "
             f"`worktree recover-land --{'work' if is_work else 'task'} {target} --batch-residue`. "
             f"(A land KILLED mid-flight leaves the worktree in place — the tear-down is on the "
             f"SUCCESS path — so this refusal means something else removed it.)")
    W = Path(wt)

    foreign = _land_batch_foreign_merges(branch, W, "main", _run_git_cap=_run_git_cap)
    if not foreign:
        print(f"worktree recover-land: {branch} carries no batch peer merges main lacks — no "
              f"half-formed batch residue to undo (idempotent no-op).")
        return

    tip, why_not = _residue_pre_batch_tip(branch, foreign, W, _segment_lines=_segment_lines,
                                          _events_path=_events_path, _run_git_cap=_run_git_cap)
    if not tip:
        if _land_contamination_advisory is not None:
            for ln in _land_contamination_advisory(branch, foreign, W):
                print(ln, file=sys.stderr, flush=True)
        _die(f"worktree recover-land: REFUSED — {branch} carries {len(foreign)} merge(s) of other "
             f"branches, but {why_not}. A merge this branch made DELIBERATELY must never be unwound "
             f"by a recovery, so with no formation record attesting a batch put it here this arm "
             f"stops and leaves the branch exactly as it is.")

    # AUTHORED-WORK GUARD — nothing above the tip is discarded unless it is PROVABLY the batch's or
    # the land's own. Same eligibility posture (and the same four admissible classes) as T-11467's
    # `_land_rollback_bookkeeping_to_entry`, applied out-of-process.
    foreign_shas = {str(f.get("sha") or "") for f in foreign}
    # THE PEERS' OWN COMMITS ARE PART OF THE RESIDUE, and they must be admissible or this guard
    # refuses every real case. A peer merge brings the peer's history with it, so `tip..HEAD` holds
    # the merge commit AND everything under its SECOND parent. Those commits are ANOTHER branch's
    # authored work — discarding them HERE destroys nothing, because they remain on the peer's own
    # branch, which is where they belong and where its land will find them. The set is computed
    # TOPOLOGICALLY from the merges' second parents (one `rev-list`), never from a branch NAME: a
    # peer branch may already have been deleted by the time anyone recovers this one.
    peer_content: "set[str]" = set()
    second_parents = []
    for _fsha in foreign_shas:
        _pr = _run_git_cap(["log", "-1", "--format=%P", _fsha], W)
        _pp = (getattr(_pr, "stdout", "") or "").split()
        if getattr(_pr, "returncode", 1) == 0 and len(_pp) == 2:
            second_parents.append(_pp[1])
    if second_parents:
        _rl = _run_git_cap(["rev-list", *second_parents, f"^{tip}"], W)
        if getattr(_rl, "returncode", 1) != 0:
            _die(f"worktree recover-land: REFUSED — the peer content merged into {branch} could not "
                 f"be enumerated, so this branch's OWN commits cannot be told apart from the "
                 f"batch's (fail-closed).")
        peer_content = {ln.strip() for ln in (getattr(_rl, "stdout", "") or "").splitlines()
                        if ln.strip()}

    walk = _run_git_cap(["log", "--format=%H%x00%P", f"{tip}..HEAD"], W)
    if getattr(walk, "returncode", 1) != 0:
        _die(f"worktree recover-land: REFUSED — the commits above {tip[:9]} on {branch} could not be "
             f"listed, so none of them can be proven discardable (fail-closed).")
    for line in (getattr(walk, "stdout", "") or "").splitlines():
        sha, _, parents_raw = line.partition("\x00")
        sha = sha.strip()
        if not sha or sha in foreign_shas or sha in peer_content:
            continue                            # the residue itself: a peer merge this batch made,
                                                # or the peer content that merge brought with it
        if _run_git_cap(["merge-base", "--is-ancestor", sha, "main"], W).returncode == 0:
            continue                            # already ON main: resetting past it destroys nothing
        parents = parents_raw.split()
        if len(parents) == 2 and _run_git_cap(
                ["merge-base", "--is-ancestor", parents[1], "main"], W).returncode == 0:
            continue                            # a catch-up merge OF main — provably not authored
        if _residue_bookkeeping_only(sha, W, _run_git_cap):
            continue                            # the killed land's own bookkeeping commit
        _die(f"worktree recover-land: REFUSED — {sha[:9]} sits above the recorded pre-batch tip "
             f"{tip[:9]} on {branch} and is NOT a batch peer merge, peer content that merge brought "
             f"in, a bookkeeping commit, a catch-up merge of main, or already on main. It looks like "
             f"AUTHORED work, and this arm never "
             f"destroys authored work to undo a batch. Inspect it with "
             f"`git -C {W} log --oneline {tip}..HEAD` and land or move it first.")

    # NOTHING JOURNALED IS LOST — and the restoration is done BY GIT, not by reading the file.
    # `events.jsonl` is append-only + union-merged, so a bare `git reset --hard` would discard the
    # rows the killed land had folded. The obvious repair is to read the file, reset, and write the
    # missing lines back (T-11467's `_land_rollback_bookkeeping_to_entry` does exactly that, and its
    # raw read is CORRECT there). Here git can do the same job with no read at all: the pre-reset
    # HEAD's copy of the journal is a SUPERSET of the tip's on this branch — appends only ever add —
    # so restoring THAT blob into the working tree after the reset preserves every row by
    # construction, with no read, no dedup and no temp file. Deliberately `--worktree` only: the rows
    # land back as ordinary trailing worktree DIRT, which is precisely what the next land's step-1b
    # fold is for, and staging them here would make this recovery author a commit it has no business
    # authoring.
    head_before = (getattr(_run_git_cap(["rev-parse", "HEAD"], W), "stdout", "") or "").strip()
    if not head_before:
        _die(f"worktree recover-land: REFUSED — HEAD on {branch} is unreadable, so the journal rows "
             f"this reset would discard could not be restored afterwards (branch untouched).")

    r = _run_git_cap(["reset", "--hard", tip], W)
    if getattr(r, "returncode", 1) != 0:
        _die(f"worktree recover-land: REFUSED — `git reset --hard {tip[:9]}` on {branch} exited "
             f"nonzero: {(getattr(r, 'stderr', '') or getattr(r, 'stdout', '') or '').strip()}")

    rows_restored = False
    rj = _run_git_cap(["restore", "--source", head_before, "--worktree", "--", "events.jsonl"], W)
    if getattr(rj, "returncode", 1) == 0:
        rows_restored = True
    else:
        # The branch IS at its pre-batch tip; what failed is the row restoration. Say exactly that —
        # reporting a clean restore would be the one dishonest outcome available here.
        print(f"worktree recover-land: WARNING — {branch} was restored to {tip}, but the journal "
              f"rows the reset removed could NOT be put back: "
              f"{(getattr(rj, 'stderr', '') or getattr(rj, 'stdout', '') or '').strip()}. They remain "
              f"wherever they were already landed; recover them with "
              f"`git -C {W} restore --source {head_before} --worktree -- events.jsonl`.",
              file=sys.stderr, flush=True)

    _append_event("land_batch_head_restored", (None if is_work else target),
                  {"branch": branch, "pre_sha": tip, "outcome": "restored",
                   "reason": "killed-land-residue", "batch_size": len(foreign) + 1,
                   "peers": [str(f.get("merged_branch") or "") for f in foreign],
                   "dropped_commits": [str(f.get("sha") or "") for f in foreign],
                   "journal_rows_restored": rows_restored,
                   "journal_source": head_before})
    print(f"worktree recover-land: {branch} restored to its pre-batch tip {tip} — "
          f"{len(foreign)} peer merge(s) left behind by a KILLED land removed "
          f"({', '.join(str(f.get('merged_branch') or '?') for f in foreign)})"
          + ("; the journal rows it had folded are preserved as trailing worktree dirt for the "
             "next land to fold" if rows_restored else "") + ".")
    print(f"next: the branch is yours again — `bin/yitc-v2 worktree sync "
          f"--{'work' if is_work else 'task'} {target}` to pre-flight, then land it.")


