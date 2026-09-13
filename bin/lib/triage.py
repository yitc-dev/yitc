"""Triage verb-family for the yitc-v2 CLI — `triage` (the un-routed-capture sweep `cmd_triage_run`
+ the displacement-retention `cmd_triage_sweep`, SPEC-0055 / SPEC-0061 / D-0086 / SPEC-0056). The
seventh layer-2 verb-family extraction (after scenario/error/gates/spec/dispatch/session.py), plan
`layer-2-tail-remainder-decomposition-of-bin-yitc-v` wave-2a card T-9337.

bin/yitc-v2 keeps the thin argparse residue cmd_triage_run/cmd_triage_sweep (the `set_defaults(func=…)`
entrypoints, wiring unchanged) which delegate here, injecting the host collaborators + path globals
each verb reads — the spec.py / dispatch.py / session.py precedent — so a `-C` REPO_ROOT rebind and
every `monkeypatch.setattr(yitc, …)` stay honored at call time.

DESIGN: the host-dependent index-builders (_discovery_stem_clusters / _error_fingerprint_index /
_fingerprint_cites_index / _owner_closed_at_index / _displacement_retention_sweep) DELIBERATELY stay
host-side and are injected (the error.py precedent — some are cross-family: _error_fingerprint_index +
_displacement_retention_sweep are also injected into error.py / audit.py, so they MUST stay host). The
six triage-EXCLUSIVE status/route constants + the seven PURE helpers (which read only those consts and
call each other) move HERE module-level, so they resolve module-local with byte-identical bodies. The
host keeps re-export aliases for the pure helpers used externally (_stem_family_key / _remedy_verdict /
_currency_status / _suggest_route / _recurs_after_close).

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
stdlib + the already-extracted lower leaf lib.state; it NEVER back-imports the host. Behaviour is
byte-identical to the inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import re
from pathlib import Path

from lib import state
from lib import journal as journal_mod  # T-11444: the SPEC-0190 segment-aware journal folds


_DONE_STATUSES = {"done", "Final"}                                   # the fix shipped + adopted

_OPEN_STATUSES = {"ready", "in-progress", "blocked", "Draft", "Accepted"}  # owned, NOT yet fixed

_DECLINED_STATUSES = {"wont-do", "waived"}                          # owner declined → recurrence reopens

_INTO_WORK = {"TRULY-NEW", "REGRESSED"}            # the only currency tokens that become a fix-task (D-0086 §8)

_REMEDY_ABSENT_TOKENS = {"absent", "none", "no", "swept-none", "remedy-absent"}

_STALE_OPEN_STATUSES = {"open", "reopened"}

# Root-stem clustering tuning (T-9729, closes E-0026 fragmentation). The token-PREFIX predicate alone
# only merges spellings that share a LEADING token run, so a root respelled with different word ORDER
# (`hand-edited-spec-body-…` vs `spec-body-edited-by-hand-…` vs `spec-file-hand-edited-…`) stays
# fragmented and undercounts. The SECOND predicate (below) merges by SIGNIFICANT-TOKEN-SET OVERLAP —
# order-independent — so a respelled root clusters as ONE discovery family. STOPWORDS are structural
# glue only (function words), dropped before overlap so `…-by-hand-not-via-…` filler does not dilute
# the ratio. The TWO gates together are the anti-over-merge guard (the §2 over-clustering defect, the
# SPEC-0056 lens-vs-root line): a pair merges ONLY when it shares >= _STEM_SHARED_MIN significant tokens
# (short-fp guard) AND their significant-token Jaccard >= _STEM_JACCARD_MIN. A pair sharing only a
# generic LENS (e.g. `…-spec-edit-…` two tokens) stays separate — discovery is advisory anyway
# (confirm-cause-or-disband, SPEC-0056 §2), never an authoritative count.
_STEM_STOPWORDS = frozenset({
    "of", "by", "not", "via", "to", "the", "a", "an", "on", "in", "no",
    "for", "and", "or", "is", "was", "be", "at", "with",
})
_STEM_JACCARD_MIN = 0.6   # significant-token-set overlap ratio to merge two near-synonym spellings
_STEM_SHARED_MIN = 3      # AND at least this many SHARED significant tokens (guards short fingerprints)

# THE ONE HOME OF THE ADMITTED FINGERPRINT-TOKEN SHAPE (T-10961). Both ends of the SPEC-0069 link rule
# read it: the close-side validator (`task.py#_CLOSES_FP_RE`, a re-export alias of this constant) and the
# reader-side "is this cites entry a fingerprint?" test below. They were separately spelled and DIVERGED —
# the capture side (`event deviation_captured`) admits any token, while the close side required lowercase,
# so 109 of 3455 distinct captured fingerprints (mixed-case acronyms like `…noData-ABORT…`, `lens:subject`
# tokens) could never be linked to the task that fixed them and read as un-routed debt forever.
# The shape is a WHITESPACE-FREE token: uppercase + colon admitted; whitespace, slashes and the empty
# string still REFUSED, so a typo / free text can never pollute the canonical `cites:` carrier.
FINGERPRINT_SHAPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_FP_SHAPE = FINGERPRINT_SHAPE_RE   # historical name kept for the local readers below

# A `cites:` entry is a MIXED bag — fingerprints live beside artifact ids (SPEC-0147, T-10319, D-0086).
# The landed-fix-in-class check stem-clusters ONLY the fingerprints: tokenizing `T-10319` on `-` would
# let the prefix predicate merge unrelated ids into one family. That exclusion used to ride on the shape
# being lowercase-only (an uppercase id failed it by construction); now that the shape admits uppercase,
# the exclusion is EXPLICIT — this predicate, applied at the use site before the shape test.
_CITES_ARTIFACT_ID_RE = re.compile(r"^(?:T|D|E|X|B|SPEC|RULE)-\d", re.IGNORECASE)


def _declared_root(fp: str) -> "str | None":
    """The DECLARED root of a `<root>:<subject>` fingerprint, else None (T-11898).

    THE ONE HOME of "a colon declares a root" — read by `_stem_family_key` predicate (3) and by
    `_declared_root_siblings` (the Section-A per-row root label), so the two readers cannot drift (P5).

    The `<root>:<subject>` shape is an EXISTING convention, not one this function invents:
    `FINGERPRINT_SHAPE_RE` deliberately admits the colon, and the `_CITES_ARTIFACT_ID_RE` note above
    names `lens:subject` tokens as a known spelling. A fingerprint that uses it is NAMING its own root
    and applying it to a varying subject (a test file, a path) — so reading the root back is reading a
    DECLARATION, not guessing at a similarity. That is what makes it exact where the two heuristic
    predicates beside it are thresholded.

    Returns None for a colonless fingerprint, and for a degenerate one whose root or subject half is
    empty (`:x` / `x:`) — those declare nothing, and admitting them would let an empty root merge every
    other degenerate spelling into one meaningless family."""
    if not fp or ":" not in fp:
        return None
    root, _, subject = fp.partition(":")
    if not root or not subject:
        return None
    return root


def _stem_family_key(fingerprints: list) -> dict:
    """Group fingerprints into root-stem families (the discovery clusterer's pure core, T-0458;
    root-stem overlap added T-9729 to close E-0026 fragmentation; DECLARED-ROOT added T-11898 to close
    the `<root>:<subject>` fragmentation). Two fingerprints are SAME-FAMILY iff ANY predicate holds
    (transitively merged via union-find):

      (1) TOKEN-PREFIX — one's hyphen-token sequence is a PREFIX of the other's. Merges spellings that
          extend a shared leading run: `plan-check-on-main`, `plan-check-on-main-dirties-...`,
          `plan-check-on-main-writes-...`. (NOT blind substring — `plan-check-verdict-stray-...` and
          `plan-check-generic-lens-...` diverge at token 3 and stay separate.)

      (2) ROOT-STEM OVERLAP (order-INDEPENDENT) — the two SIGNIFICANT-token SETS (tokens minus the
          structural _STEM_STOPWORDS) share >= _STEM_SHARED_MIN tokens AND have a Jaccard ratio
          >= _STEM_JACCARD_MIN. Merges a root respelled with different word ORDER that predicate (1)
          misses — e.g. `hand-edited-spec-body-instead-of-spec-edit-verb`,
          `spec-body-edited-by-hand-not-spec-edit-verb`, `spec-file-hand-edited-...`,
          `spec-body-hand-edit-bypasses-spec-edit-verb-...` all cluster as ONE family (the E-0026
          spec-edit-bypass family). The two gates TOGETHER are the anti-over-merge guard (the SPEC-0056
          §2 over-clustering / lens-vs-root line): a pair sharing only a generic LENS (e.g. just
          `spec`+`edit`, < _STEM_SHARED_MIN) or a low overlap stays separate.

      (3) DECLARED ROOT (T-11898) — both fingerprints spell `<root>:<subject>` with an IDENTICAL
          `<root>` (see `_declared_root`). EXACT, not thresholded: such a fingerprint is not a
          respelling of a root, it NAMES its root and varies the subject, so 15 spellings of
          `land-verify-timeout:<test file>` are ONE root fragmented by a filename. Predicates (1) and
          (2) are STRUCTURALLY BLIND to this, and measurably so: the tokenizer splits on `-` only, so
          the `:` fuses root-tail and subject into one opaque token — `land-verify-timeout:test_x.py`
          tokenizes ['land','verify','timeout:test_x.py']. Two members are then both 3 tokens
          differing at token 3 (no prefix), sharing only {land, verify} = 2 < _STEM_SHARED_MIN with
          Jaccard 0.5 < _STEM_JACCARD_MIN. Loosening those thresholds to reach it would over-merge
          everything else; splitting the tokenizer on `:` lands the family EXACTLY on both bounds
          (3 shared, Jaccard exactly 0.600) and breaks for any subject containing a hyphen — both
          rejected at T-11898 Analysis in favour of reading the declaration.
          OVER-MERGE BOUND, MEASURED over this repo's whole uncited corpus (5067 fingerprints, the
          real `_discovery_stem_clusters` leftover set, 2026-08-30): families 4851 -> 4832 — exactly
          20 singletons merge into 1 family of 21 and NOTHING else moves. Of 5253 distinct captured
          fingerprints only 45 carry a colon and exactly ONE colon-root has >1 subject.

    DETERMINISTIC total order (audit-pre F0): the family key = the lexicographically-smallest member
    among the SHORTEST-token-length members (length-then-lexicographic) — EXCEPT a family whose members
    ALL declare the SAME root, which is keyed by that DECLARED ROOT so the caller can NAME the root
    instead of an arbitrary member (guarded so it never shadows a real fingerprint — see below);
    members are returned SORTED lexicographically; all three predicates are symmetric +
    iteration-order-independent. Returns
    {stem_key: [member_fp, ...]} for EVERY family (singletons included — the caller decides the >=2
    surfacing threshold). DISCOVERY-ONLY advisory: a surfaced family is a CONFIRM-CAUSE-OR-DISBAND
    candidate (SPEC-0056 §2), never an authoritative recurrence count."""
    fps = sorted(set(f for f in fingerprints if f))
    toks = {f: f.split("-") for f in fps}
    sig = {f: frozenset(t for t in toks[f] if t not in _STEM_STOPWORDS) for f in fps}
    droot = {f: _declared_root(f) for f in fps}          # (3) the DECLARED `<root>:` half, else None
    parent = {f: f for f in fps}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)   # deterministic root = lexicographically smaller

    # O(n^2) pairwise test over the (tens-of-fingerprints) open set — bounded by design
    # (D-0086 §4: clustering depth is measured in FINGERPRINTS, not events).
    for i, a in enumerate(fps):
        for b in fps[i + 1:]:
            # (3) DECLARED ROOT first — an exact declaration outranks the two heuristics below, and
            # testing it first keeps the cheap case cheap. `is not None` is load-bearing: a colonless
            # fingerprint has root None, and `None == None` would merge every colonless spelling.
            if droot[a] is not None and droot[a] == droot[b]:
                union(a, b)
                continue
            ta, tb = toks[a], toks[b]
            short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if long_[: len(short)] == short:      # (1) one token-sequence is a prefix of the other
                union(a, b)
                continue
            shared = sig[a] & sig[b]              # (2) order-independent significant-token overlap
            if len(shared) >= _STEM_SHARED_MIN:
                denom = len(sig[a] | sig[b])
                if denom and len(shared) / denom >= _STEM_JACCARD_MIN:
                    union(a, b)
    families: dict = {}
    for f in fps:
        families.setdefault(find(f), []).append(f)
    out: dict = {}
    for members in families.values():
        members = sorted(members)
        # stem key = shortest-token member, lexicographic tie-break (a total order, no scan/hash order)
        stem = min(members, key=lambda m: (len(toks[m]), m))
        # T-11898: a family whose members ALL declare the SAME root is keyed by that DECLARED ROOT
        # rather than by an arbitrary member — otherwise the caller labels a 21-spelling family with
        # whichever test filename happens to sort first, which reads as a root and is not one.
        # TWO GUARDS, both fail-closed back to the member key:
        #   * every member must declare the SAME root (a mixed family was merged by (1)/(2) as well,
        #     so its root is not the whole story and the member key stays honest);
        #   * the root must not itself be one of the clustered fingerprints — a synthetic key may
        #     never shadow a real fingerprint, which is also what makes a key collision between two
        #     families impossible (two families cannot share a declared root: sharing one merges them).
        roots = {droot[m] for m in members}
        if len(members) > 1 and len(roots) == 1:
            root = next(iter(roots))
            if root is not None and root not in parent:
                stem = root
        out[stem] = members
    return out


def _fix_boundaries(owners: list, owner_closed_at: dict) -> list:
    """The SPEC-0061 R-A comparison boundaries available for an owner set — the `closed_at` (or
    equivalent datable landing) of every done/Final owner that carries one.

    Extracted from `_recurs_after_close` (T-11897) so ONE expression answers BOTH questions the
    boundary rule asks: *what* is the boundary to compare against, and *is there one at all*. The
    second question is new — the honesty leg below has to distinguish "the captures predate the fix"
    from "no fix boundary could be established", and those two must never be computed by two
    expressions that can drift apart. Pure, order-independent; behaviour is byte-identical to the
    inline comprehension it replaces."""
    return [owner_closed_at[i] for (i, s, _k) in owners
            if s in _DONE_STATUSES and i in owner_closed_at]


def _recurs_after_close(owners: list, capture_tss: list, owner_closed_at: dict, fallback: bool) -> bool:
    """R-A temporal recurrence (SPEC-0061) — REPLACES the bare all-time `count >= 2` for the done-owner
    branch. For a fingerprint owned by a done/Final fix-task, the recurrence is REAL only if it
    POST-DATES the fix: at least one capture `ts` strictly AFTER the owning fix-task's `closed_at`. With
    SEVERAL done-owners the boundary is the LATEST `closed_at` (SPEC-0061 R-A) — a recurrence is real
    only if it post-dates the MOST RECENT fix; a capture between an earlier and the latest fix is part of
    the incident the latest fix addressed, not a regression of it. Captures at or before the boundary are
    the SAME incident — caught while the fix was being built — NOT a regression, so the done-owner reads
    ALREADY-FIXED. With NO done/Final owner carrying a `closed_at` there is no fix boundary to compare
    against, so the prior count-based `fallback` is returned UNCHANGED (a no-owner fp recurring N>=2 stays
    a promotion candidate; an open/declined owner is decided by `_currency_status`, recurs is irrelevant
    there). ISO-UTC string compare — the same idiom the window uses (`ts > prior`)."""
    boundaries = _fix_boundaries(owners, owner_closed_at)
    if not boundaries:
        return fallback
    boundary = max(boundaries)
    return any(ts > boundary for ts in capture_tss if ts)


def _resolved_case_fix_owner(err, owners: list, error_fix_task: dict, owner_closed_at: dict,
                             error_root_fix_at: dict = None) -> list:
    """E-0036 de-regression boundary fix. A `resolved` case-file whose fix-task cites the CASE-ID (not
    the fingerprint) leaves that done fix-task ABSENT from the cites-owners (cites_idx is keyed by
    fingerprint), so `_recurs_after_close` finds NO fix boundary and falls back to a false REGRESSED for
    all-pre-fix captures. Resolve the case's `resolution.fix_task` as a SYNTHETIC done LINK-RULE owner
    (only when it carries a `closed_at` — presence in owner_closed_at ⇒ done — and is not already a
    cites-owner), so the EXISTING `_recurs_after_close` boundary logic engages AND `_currency_status`
    reads ALREADY-FIXED. `err` is (E-id, status) or None; returns `owners` unchanged when not applicable.

    SECOND BOUNDARY SHAPE — `resolution.kind: root_fix_landed` (T-11897). `error resolve --root-fix`
    resolves a case whose root fix landed via a carrier that is NOT a promote-filed fix-task (a plan,
    a spec, a verb change, a standing-rule edit). Such a case records its `root_fix` as PROSE and has
    NO fix_task at all, so the branch above can never resolve it — and with no boundary EVERY capture,
    including ones long predating the fix, fell through to a false REGRESSED. That is the same false
    reading the E-0036 carve-out exists to prevent, for the sibling shape (measured 2026-08-30: E-0058
    reported 83x REGRESSED with its last capture 16 days BEFORE its fix; E-0048 likewise).

    `error_root_fix_at` maps such a case-id to its DATABLE landing instant (see
    `_error_root_fix_landed_at`); when present it is resolved as a synthetic done owner keyed by the
    CASE id, so the EXISTING `_recurs_after_close` comparison engages with no new comparator. The
    fix_task shape is tried FIRST and is untouched; `error_root_fix_at` defaults to None, so every
    pre-T-11897 caller behaves exactly as before."""
    if not err or err[1] != "resolved":
        return owners
    ft = error_fix_task.get(err[0])
    if ft and ft in owner_closed_at:                  # E-0036: the fix_task shape, unchanged
        if any(i == ft and s in _DONE_STATUSES for (i, s, _k) in owners):
            return owners                             # already a DONE cites-owner — boundary already engages
        return owners + [(ft, "done", "task")]
    # T-11897: no fix-task boundary — fall back to a DATABLE landed root fix, when one is recorded.
    at = (error_root_fix_at or {}).get(err[0])
    if not at:
        return owners                                 # no boundary of either shape — the honesty leg decides
    if any(i == err[0] and s in _DONE_STATUSES for (i, s, _k) in owners):
        return owners
    return owners + [(err[0], "done", "error")]


def _mention_derived_boundary_owners(owners: list, err, mentions: list, boundaries: dict) -> list:
    """T-11903 — the SECOND, WEAKER, EXPLICITLY-LABELLED comparison-boundary source: a done card that
    NAMES this fingerprint in body text but does NOT carry it in `cites:`.

    THIS IS A BOUNDARY SOURCE, NOT A LINKAGE SOURCE, AND IT DOES NOT REDEFINE OWNERSHIP. SPEC-0068
    makes linkage `cites:`-EXCLUSIVE, and T-11898 READ the mentioning cards and confirmed that rule
    CORRECT as written — the cards genuinely do not cite what they discuss. So the LINK RULE is
    untouched: `_fingerprint_cites_index` stays the sole ownership authority, and what this adds is a
    strictly weaker, separately-marked answer to the DIFFERENT question `_recurs_after_close` asks —
    *is there a datable fix to compare these captures against?* A mention cannot say who owns a
    fingerprint; a DONE card's `closed_at` can still say when a fix landed.

    THE SHAPE IS THE ESTABLISHED SYNTHETIC-OWNER IDIOM, deliberately — `_resolved_case_fix_owner`
    already resolves an off-cites boundary carrier (E-0036's `resolution.fix_task`, T-11897's
    `root_fix_landed`) as a synthetic done owner so the EXISTING comparator engages with no new
    comparator. Same move here, third carrier. Consequently THE BOUNDARY IS THE LATEST `closed_at`
    ACROSS ALL MENTIONING DONE CARDS BY CONSTRUCTION: every qualifying card is returned, and
    `_fix_boundaries` + `_recurs_after_close` already take `max()` over the done owners. That is not a
    detail — it INVERTS verdicts, and it is why the rule is expressed by REUSING the comparator rather
    than by a second `max()` that could drift from it. Measured on
    `worktree-sweep-permission-impossible-residue` (12 occurrences): read against two of its three
    mentioning cards (closed 2026-08-10) its 2026-08-21 capture reads REGRESSED; read against all
    three, whose latest closed 2026-08-30, the SAME capture reads ALREADY-FIXED. The interactive
    Controller made exactly this error by hand on 2026-08-30 and reported a genuine regression to the
    owner before the full sweep corrected it.

    TWO GATES, both fail-closed, and together they are what keeps this weaker source from ever
    OUTRANKING or IMPERSONATING a citation:
      * `not owners and not err` — it fires ONLY where the row would otherwise render a bare TRULY-NEW.
        A cites-derived owner or a case file already governs the fingerprint and is NEVER displaced,
        so a mention can only fill a vacuum, never overrule evidence.
      * done-with-a-boundary ONLY — a mentioning card contributes only when its status is in
        `_DONE_STATUSES` AND it carries a datable boundary. An OPEN mentioning card yields NOTHING:
        promoting prose into an OWNED-IN-FLIGHT verdict would assert live ownership off a body
        mention, which is precisely the claim SPEC-0068 forbids. A decision (`Final`, no `closed_at`)
        likewise contributes no boundary and so is absent here.

    The caller MARKS the resulting verdict mention-derived (`_currency_status(..., mention_derived=)`)
    so a reader can always tell it from a cites-derived one — the provenances are never merged.
    Returns [] when not applicable, so the caller's owner set is unchanged. Pure, order-independent,
    no I/O; `boundaries` is the SAME merged map the comparator reads, never a second one."""
    if owners or err:
        return []
    return [(i, s, k) for (i, s, k) in (mentions or [])
            if s in _DONE_STATUSES and i in boundaries]


def _remedy_verdict(remedy) -> str:
    """Map a recorded `data.remedy_ref` capture value to one of three tokens (D-0086 §5, T-0500):
      ALREADY-BUILT — a remedy reference was recorded (an analog fix/mechanism already exists);
      REMEDY-ABSENT — the sweep ran and found NONE (an explicit absent/none marker) ⇒ genuinely new;
      REMEDY-UNSWEPT — nothing recorded yet ⇒ the sweep has NOT been done, so a TRULY-NEW is NOT
                       promotable until it is (the gate surfaced in triage output, never auto-judged).
    Only REMEDY-ABSENT clears a TRULY-NEW candidate into-work; ALREADY-BUILT routes already-built."""
    if remedy is None:
        return "REMEDY-UNSWEPT"
    s = str(remedy).strip()
    if not s:
        return "REMEDY-UNSWEPT"
    if s.lower() in _REMEDY_ABSENT_TOKENS:
        return "REMEDY-ABSENT"
    return "ALREADY-BUILT"   # any other non-empty value is a remedy reference (a path / verb / id / note)


def _currency_status(owners: list, err, recurs: bool, remedy=None,
                     boundary_unresolvable: bool = False,
                     mention_derived: bool = False,
                     retest_absent: bool = False) -> "tuple[str, str]":
    """The status-aware triage VIEW (D-0086 §5/§8, T-0457; remedy sweep T-0500). Returns
    (currency_status, route_string) where currency_status ∈ {ALREADY-FIXED, OWNED-IN-FLIGHT, REGRESSED,
    TRULY-NEW, ALREADY-BUILT} — the SINGLE into-work classifier (into-work = TRULY-NEW + REGRESSED only;
    ALREADY-BUILT is NOT into-work — an analog remedy already exists). The route_string is the finer
    §8 advisory disposition (adds `declined` for a wont-do/waived owner — a reopen-signal, NOT a
    currency token). `recurs` = this fingerprint recurs anew (a routing-window capture / a
    cluster rollup) so a done-owner that recurs is a REGRESSION, not still-fixed.

    `remedy` is the recorded remedy-existence sweep value (`data.remedy_ref`), consulted ONLY when the
    owner/case-file analysis would otherwise return TRULY-NEW (the sole branch that files a NEW
    candidate, D-0086 §5 remedy sub-check): a found ref ⇒ ALREADY-BUILT (route confirm-the-existing-
    remedy, never file a duplicate); an UNSWEPT verdict ⇒ TRULY-NEW but flagged not-promotable-until-
    swept; REMEDY-ABSENT ⇒ a genuinely-new TRULY-NEW that the sweep cleared. Default None preserves the
    pre-T-0500 TRULY-NEW behaviour for every existing caller. Owned / done / declined branches are
    untouched — a remedy sweep is meaningless once an owner/case-file already governs the fingerprint.

    Multi-owner precedence is over the FULL owner set, tuple-order-INDEPENDENT (audit-pre F0): an
    active/open owner DOMINATES (live work — never duplicate), else a done/Final owner decides
    fixed-vs-regressed, else (every owner declined) the route is `declined`. The `err` case-file
    status is folded in the same way when no cites-owner exists.

    `boundary_unresolvable` (T-11897) says the caller could establish NO comparison boundary for a
    `resolved` case file — neither a done fix-task's `closed_at` nor a datable landed root fix. Then
    `recurs` carries no information about the fix at all (it has fallen back to the bare all-time
    count), so calling the result REGRESSED asserts something unproven. The branch below says so
    instead. It adds NO sixth currency token: an unresolvable case reads OWNED-IN-FLIGHT, which is
    already this branch's non-recurring verdict and already NOT into-work — what changes is that the
    route NAMES the absent boundary rather than defaulting silently to either label.

    `mention_derived` (T-11903) says the done-owner boundary this verdict rests on came from an
    UNLINKED BODY MENTION (`_mention_derived_boundary_owners`), not from a `cites:` link. THE TWO
    PROVENANCES ARE NEVER MERGED: a mention is weaker evidence than a citation, so the route SAYS SO,
    and a reader can always tell which kind of verdict they are looking at. Silently collapsing them
    would trade one invisible error for another — an unmarked ALREADY-FIXED derived from prose reads
    exactly like one derived from a link, and only one of them is backed by an author's explicit
    assertion. It adds NO sixth currency token (SPEC-0056 §5 enumerates exactly five) and changes no
    into-work membership: it annotates the ROUTE of the ALREADY-FIXED / REGRESSED verdicts it can
    reach. Default False keeps every existing caller byte-identical.

    `retest_absent` (T-11936) is the SAME move applied to the ALREADY-BUILT branch: it says the live
    remedy verdict rests on an ARTIFACT ALONE — nobody re-ran the ORIGINAL FAILING INPUT against it.
    An unmarked already-built reads identically whether the behaviour was confirmed or merely an
    artifact was spotted, and that indistinguishability produced two incidents three weeks apart in
    OPPOSITE directions (2026-08-26 retired a live defect off the message-only T-10772; 2026-08-31
    resurrected a defect T-10899 had already fixed, read off the same artifact). Going forward the
    write side refuses to RECORD such a clearance; this mark is what makes the ALREADY EXISTING
    corpus of unbacked verdicts legible without rewriting a single row of it. It adds NO sixth
    currency token (SPEC-0056 §5 enumerates exactly five), changes no into-work membership —
    ALREADY-BUILT stays not-into-work — and annotates only the ROUTE. Default False keeps every
    existing caller byte-identical."""
    statuses = [s for (_i, s, _k) in owners]
    if any(s in _OPEN_STATUSES for s in statuses):
        who = ", ".join(i for (i, s, _k) in owners if s in _OPEN_STATUSES)
        return "OWNED-IN-FLIGHT", (f"in-flight — owned by {who} (open: no-dup, but NOT yet fixed; "
                                   "never duplicate)")
    # BY-DESIGN RESIDUAL (T-11041, SPEC-0056 §4). A case whose waive DECLARES
    # `resolution.by_design_residual: true` asserts that the recurrence REMAINS by design and a
    # downstream guard catches it — so a later match is EXPECTED, not a contradiction of the
    # disposition. The CAPTURE path already honours that declaration (T-10924: the match surfaces as
    # `error_residual_recurrence` and the case file is left UNWRITTEN instead of flipping to
    # `reopened`); this classifier never read it, so the SAME rule reported the SAME recurrence as
    # REGRESSED / into-work and prescribed `confirm + reopen the root-fix` — the precise act §4
    # forbids for this case. Two surfaces of ONE spec disagreeing IS the defect (E-0053: 67x, whose
    # false REGRESSED was driven by done-owner T-10924 — the very task that shipped this rule).
    #
    # PRECEDENCE is deliberate and sits BELOW the open-owner branch above: an OPEN owner is genuinely
    # live work and must keep dominating (never duplicate it). What is suppressed is exactly the
    # done-owner-recurs and resolved-case REGRESSED verdicts below.
    #
    # SCOPE is the DECLARATION, never a case id: an undeclared resolved/waived case keeps its reopen
    # and REGRESSED semantics verbatim (§4 `only a case that DECLARES it`), so a genuine regression
    # still flips and still surfaces. Read DEFENSIVELY — `_error_fingerprint_index` is cross-family
    # and stays a 2-tuple, so a 2-tuple caller keeps its exact prior behaviour.
    if err and len(err) > 2 and err[2]:
        return "ALREADY-FIXED", (f"by-design residual — case file {err[0]} ({err[1]}) DECLARES "
                                 "`resolution.by_design_residual` (SPEC-0056 §4): this recurrence is "
                                 "EXPECTED and absorbed by a downstream guard, NOT a regression. It "
                                 "surfaces as `error_residual_recurrence`; do NOT reopen, do NOT "
                                 "re-file (not into-work)")
    # UNRESOLVABLE BOUNDARY (T-11897, SPEC-0061 R-A). A `resolved` case file for which NO comparison
    # boundary could be established at all. Placed BELOW the open-owner branch deliberately — genuinely
    # live work must keep dominating — and ABOVE the done-owner branch, because a done owner carrying
    # no readable boundary produces exactly the same unproven REGRESSED this exists to stop.
    #
    # SCOPED to a `resolved` case file, and it never invents a verdict: it withholds one. The honest
    # reading of "these captures may or may not predate a fix nobody can date" is neither
    # ALREADY-FIXED nor REGRESSED, so the route says which fact is missing and what would supply it.
    # A wrong-but-quiet label is more expensive than a loud absence: it is what routes already-fixed
    # causes back into work, or hides real ones.
    if boundary_unresolvable and err and err[1] == "resolved":
        return "OWNED-IN-FLIGHT", (f"boundary-unresolvable — case file {err[0]} is `resolved` but "
                                   "records NO datable fix boundary (no done fix_task, no datable "
                                   "landed root fix), so whether these captures predate the fix CANNOT "
                                   "be established. NOT judged fixed and NOT judged regressed (not "
                                   "into-work): establish the boundary first — link the fix task, or "
                                   "re-resolve so the landing is recorded — then re-read this row")
    if any(s in _DONE_STATUSES for s in statuses):
        who = ", ".join(i for (i, s, _k) in owners if s in _DONE_STATUSES)
        # T-11903: the provenance MARK. Appended, never substituted — the verdict text a cites-derived
        # row prints is unchanged, so the two provenances stay distinguishable at a glance.
        mark = ("  [MENTION-DERIVED boundary — the fix date came from a card that NAMES this "
                "fingerprint in BODY TEXT and does NOT cite it, so this is WEAKER evidence than a "
                "`cites:` link and links nothing (SPEC-0068). CONFIRM against the named card(s) "
                "before acting; citing the fingerprint (`task close --closes-fp <fp>`, SPEC-0069) "
                "turns this into an ordinary cites-derived verdict]" if mention_derived else "")
        if recurs:
            return "REGRESSED", (f"REGRESSED — {who} fixed this (done) but it RECURS "
                                 "(confirm + reopen the root-fix; into-work)" + mark)
        return "ALREADY-FIXED", (f"already-fixed — {who} (done): confirm the probe holds; "
                                 "do NOT re-file (never duplicate)" + mark)
    if any(s in _DECLINED_STATUSES for s in statuses):
        who = ", ".join(i for (i, s, _k) in owners if s in _DECLINED_STATUSES)
        # declined owner: recurrence is a REOPEN-SIGNAL, NOT "handled". Owned ⇒ absent from into-work
        # (currency_status OWNED-IN-FLIGHT) but the route names the reopen cue explicitly (AC1).
        return "OWNED-IN-FLIGHT", (f"declined / reopen-signal — {who} (wont-do/waived): a recurrence "
                                   "is NOT handled — reopen the decision, do not silently re-file")
    if owners:                                            # owner(s) exist but unknown status — be safe
        who = ", ".join(i for (i, _s, _k) in owners)
        return "OWNED-IN-FLIGHT", f"linked — already cited by {who} (LINK RULE owns it; never duplicate)"
    if err:
        if err[1] in _DECLINED_STATUSES or err[1] == "resolved":
            cur = "REGRESSED" if (recurs and err[1] == "resolved") else "OWNED-IN-FLIGHT"
            return cur, f"linked/promote — case file {err[0]} ({err[1]}) already owns this fp"
        return "OWNED-IN-FLIGHT", f"linked/promote — case file {err[0]} ({err[1]}) already exists for this fp"
    # No owner, no case file → the owner/status analysis says TRULY-NEW. But owner-ABSENCE alone does
    # not prove the REMEDY is new (T-0500): consult the recorded remedy-existence sweep before filing.
    verdict = _remedy_verdict(remedy)
    if verdict == "ALREADY-BUILT":
        # T-11936: the provenance MARK, appended never substituted — the verdict text an evidenced
        # row prints is unchanged, so the two provenances stay distinguishable at a glance.
        retest_mark = ("  [NO BEHAVIOURAL RE-TEST RECORDED — this verdict rests on the ARTIFACT alone; "
                       "nobody re-ran the ORIGINAL FAILING INPUT against it, so it does not show the "
                       "behaviour changed. An artifact can be message-only and still read like a fix "
                       "(T-10772). RE-TEST BEFORE ACTING on this row, in either direction — an "
                       "unverified already-built has both retired a live defect and resurrected a "
                       "dead one. Settle it with `yitc-v2 triage remedy --fp <fp> --remedy <ref> "
                       "--retested \"<the input you re-ran, and what it did>\"`]"
                      if retest_absent else "")
        return "ALREADY-BUILT", (f"already-built — an analog remedy already exists ({str(remedy).strip()}); "
                                 "confirm it covers this, do NOT file a duplicate (SPEC-0056 §1 remedy sweep)"
                                 + retest_mark)
    if recurs:
        base = "promote candidate — recurring N>=2 (file an E-XXXX, or link to a confirmed root)"
    else:
        base = "event-only — singleton, no owner (or `linked` if it shares a confirmed root)"
    if verdict == "REMEDY-UNSWEPT":
        base += "; REMEDY-UNSWEPT — sweep code/verb/pattern/spec FIRST (analog ⇒ ALREADY-BUILT, not truly-new)"
    return "TRULY-NEW", base


def _with_by_design(err, by_design_ids) -> "tuple | None":
    """Attach the SPEC-0056 §4 by-design-residual declaration onto a `(E-id, status)` case tuple as a
    3rd element, so `_currency_status` can read it through the SINGLE chokepoint every surface already
    routes through (T-11041). Returns the tuple unchanged when there is no case file. The host-side
    `_error_fingerprint_index` deliberately KEEPS its 2-tuple shape (it is cross-family — injected into
    error.py/audit.py — and a pinned stub asserts that shape), so the widening happens HERE, at the
    triage call sites, and `_currency_status` reads element 2 defensively."""
    if not err:
        return err
    return (err[0], err[1], err[0] in by_design_ids)

def _suggest_route(fp: str, count: int, owners: list, err, recurs: bool = False, remedy=None,
                   boundary_unresolvable: bool = False, mention_derived: bool = False,
                   retest_absent: bool = False) -> str:
    """ADVISORY hint only (the AI/owner routes — the verb does not decide). Status-aware per D-0086
    §5/§8 (T-0457): the route string now branches on the OWNER STATUS, not just owner presence —
    a done / open / wont-do owner read identically as "linked, never duplicate" was the gap. Returns
    `<CURRENCY-TOKEN> · <route>` so the status is visible inline. `recurs` distinguishes a regression
    (a done-owner fp that recurs) from a still-fixed one. `remedy` is the recorded remedy-existence
    sweep value (T-0500) — consulted only on the TRULY-NEW branch (ALREADY-BUILT when a remedy exists).
    `mention_derived` (T-11903) marks a verdict whose fix boundary came from an unlinked body mention
    rather than a `cites:` link — passed straight through, so the route says which provenance it rests
    on and the two are never merged."""
    currency, route = _currency_status(owners, err, recurs, remedy, boundary_unresolvable,
                                       mention_derived, retest_absent)
    return f"{currency} · {route}"


def _print_remedy_gate(currency: str, remedy, retest_reason: "str | None" = None) -> None:
    """Surface the remedy-existence sweep verdict for a TRULY-NEW candidate (D-0086 §5, T-0500). A
    TRULY-NEW is the only currency that FILES a new candidate, so before it is promoted the triager
    MUST record a remedy-existence sweep. If none is recorded yet (REMEDY-UNSWEPT) print the gate so
    the candidate is never silently promoted as new when an analog remedy already exists in code / a
    verb / a pattern / a spec (the round-3 misses T-0469 / T-0470). This is a VISIBLE ADVISORY, the
    same posture as the §5 STALE flag — NOT an enforced gate (CHARTER non-goal #7); the verb gathers,
    the AI/owner judges (D-0086 §5)."""
    if currency != "TRULY-NEW":
        return
    verdict = _remedy_verdict(remedy)
    if verdict == "REMEDY-UNSWEPT" and retest_reason:
        # T-11936: the sweep DID run and DID find an artifact — what it could not do is re-run the
        # original failing input, and it said why. Print the account, not a bare "unswept": the
        # reader needs to know the artifact exists AND that it does not clear the candidate.
        print("      ⚠ REMEDY FOUND BUT NOT RE-TESTED — an artifact was recorded, but the reported "
              "BEHAVIOUR was never re-run against it, so it does NOT clear this candidate (T-11936).")
        print(f"        why it could not be re-run: {retest_reason}")
        print("        settle it: yitc-v2 triage remedy --fp <fp> --remedy '<the analog>' "
              "--retested '<the input you re-ran, and what it did>'")
    elif verdict == "REMEDY-UNSWEPT":
        print("      ⚠ REMEDY-UNSWEPT — sweep code/verb/pattern/spec for an analog remedy BEFORE filing "
              "(SPEC-0056 §1: an analog ⇒ ALREADY-BUILT, not truly-new), then record the verdict:")
        print("        yitc-v2 triage remedy --fp <fp> --remedy '<the analog>' | --absent   (T-11675)")
    else:   # REMEDY-ABSENT — the sweep ran and cleared it
        print(f"      remedy-existence: {verdict} (swept clean — genuinely new)")


def _print_boundary_gate(err, boundary_unresolvable: bool) -> None:
    """Surface an UNRESOLVABLE fix boundary on the row itself (T-11897). Same posture as
    `_print_remedy_gate` — a VISIBLE ADVISORY, never an enforced gate (CHARTER non-goal #7): the verb
    gathers, the AI/owner judges.

    WHY A PRINT AND NOT JUST THE ROUTE STRING. Only Section A renders `suggested route:`; the two
    Section-B loops print `currency_status:` and discard the route. Without this the absent boundary
    would be named on one surface out of three, and the surface it is missing from is the one the
    backlog drain reads. Suppressed-when-clean: nothing prints unless a boundary is genuinely
    unestablishable."""
    if not (boundary_unresolvable and err and err[1] == "resolved"):
        return
    print(f"      ⚠ BOUNDARY-UNRESOLVABLE — case file {err[0]} is `resolved` but records no datable "
          "fix boundary")
    print("        (no done fix_task, no datable landed root fix), so these captures are NOT judged "
          "fixed and NOT judged")
    print("        regressed — establish the boundary before routing this row (SPEC-0061 R-A).")


def _landed_fix_class_siblings(fp: str, cites_idx: dict) -> list:
    """LANDED-FIX-IN-CLASS (T-10340) — does this capture's CLASS already have a landed fix?

    The EXACT-fingerprint case is already handled: a done owner of `fp` itself makes `_currency_status`
    return ALREADY-FIXED (T-0457 / SPEC-0061). The hole this closes is the CLASS case — `fp` is a
    near-synonym RESPELLING of a fingerprint a done task closed. Section A resolves aliases through the
    CITED-rollup only and deliberately never consults a stem family (a discovery hint must not be a
    currency AUTHORITY, SPEC-0056 §2), so such a capture falls through to TRULY-NEW and a duplicate card
    gets cut. That refusal is right for CURRENCY and wrong for VISIBILITY: the reader is simply never
    TOLD a landed sibling exists. Hence a FLAG (this helper feeds `_print_landed_fix_flag`), never a
    currency token and never a block.

    Reuses existing durable state ONLY — no new store, no new index (CHARTER §P1 F2):
      * `cites_idx` = `_fingerprint_cites_index()`, the §9 LINK-RULE view fp -> [(id, status, kind)],
        whose fingerprint entries are written by `task close --closes-fp <fp>` (SPEC-0069, human-asserted);
      * `_DONE_STATUSES` — the same fixed vocabulary `_currency_status` reads;
      * `_stem_family_key` — the same pure clusterer the discovery view uses.

    Returns [(sibling_fp, owner_id), ...] sorted deterministically, or [] when there is nothing to say:
    no landed fingerprint at all, or `fp` is ITSELF exactly owned by a landed fix (already ALREADY-FIXED
    — re-flagging it would be noise on a line that is already correct).

    HONEST LIMIT: this sees exactly what `--closes-fp` recorded. A landed fix whose closing task never
    asserted a fingerprint contributes no link and yields no flag. Deriving the link from a capture's
    `task_id` ("encountered during T", not "T fixed it") was explicitly rejected at the T-0635 specs
    gate and stays rejected — widening the link source is a separate, owner-gated change."""
    fixed: dict = {}
    for cited, owners in cites_idx.items():
        # artifact ids never enter a stem family — excluded EXPLICITLY (T-10961: the shared shape now
        # admits uppercase, so the id exclusion can no longer ride on lowercase-ness), then shape-tested.
        if _CITES_ARTIFACT_ID_RE.match(str(cited).strip()) or not _FP_SHAPE.match(str(cited)):
            continue
        landed = sorted({i for (i, s, _k) in owners if s in _DONE_STATUSES})
        if landed:
            fixed[str(cited)] = landed
    if not fixed or fp in fixed:
        return []                                       # nothing landed, or exact-fp → ALREADY-FIXED
    families = _stem_family_key([fp] + sorted(fixed))
    members = next((m for m in families.values() if fp in m), [])
    return sorted((m, owner) for m in members if m in fixed for owner in fixed[m])


def _print_landed_fix_flag(currency: str, fp: str, cites_idx: dict) -> None:
    """Surface the landed-fix-in-class flag for a TRULY-NEW capture (T-10340). TRULY-NEW is the ONLY
    currency that files a NEW card, so this is exactly the moment before a capture becomes a card — the
    one place the check belongs (a second site would duplicate the rule, CHARTER §P5).

    A VISIBLE ADVISORY, the same posture as its siblings `_print_remedy_gate` / the §5 STALE flag: it
    FLAGS, it does not BLOCK. Filing stays the author's call; the check only removes the excuse of not
    knowing. No event, no exit-code change, no mutation of `currency_status` (a blocker here would be
    exactly the gate cascade CHARTER §non-goals forbids). Real incidents: T-10299, T-10323 (duplicate of
    landed T-10319), fu_7b60f308f8de (shipped by T-10130), T-10345 (shipped by T-10263 — one background
    worker wasted)."""
    if currency != "TRULY-NEW":
        return
    siblings = _landed_fix_class_siblings(fp, cites_idx)
    if not siblings:
        return
    print("      ⚠ LANDED-FIX-IN-CLASS — this class already has a LANDED fix; confirm it does not "
          "already cover this BEFORE cutting a card (T-10340):")
    for sib_fp, owner in siblings:
        print(f"          {sib_fp}  closed by {owner} (done)")
    print("        disposition: confirm the landed fix covers this ⇒ do NOT file a duplicate (link the "
          "fingerprint via `task close --closes-fp`, SPEC-0069); if it genuinely does NOT cover this, "
          "file and say why in the card.")


def _declared_root_siblings(fp: str, counts: dict) -> "tuple | None":
    """The DECLARED-ROOT family of `fp` among CAPTURED fingerprints (T-11898) — feeds
    `_print_declared_root_flag`. Returns `(root, siblings, total)` where `siblings` are the OTHER
    captured spellings declaring the same root (sorted) and `total` is the family's whole occurrence
    count, or None when `fp` declares no root or no sibling spelling was ever captured.

    Derived straight from `_declared_root` + the existing `counts` view — no new store, no index, and
    deliberately NOT the discovery clusterer: Section A is per-capture and must not consult a cluster
    view for anything (a discovery hint is never a currency authority, SPEC-0056 §2). This yields only
    a LABEL, so it borrows none of that authority."""
    root = _declared_root(fp)
    if root is None:
        return None
    siblings = sorted(f for f in counts if f != fp and _declared_root(f) == root)
    if not siblings:
        return None
    return root, siblings, counts.get(fp, 0) + sum(counts.get(s, 0) for s in siblings)


def _print_declared_root_flag(fp: str, counts: dict) -> None:
    """Name the DECLARED ROOT on a Section-A row (T-11898). Section A prints ONE row per fingerprint
    CLASS in the routing window and cannot be collapsed into a family row the way Sections B/B2 are —
    so without this a 21-spelling root still reads as 21 unrelated brand-new classes there.

    Report-only + suppressed-when-clean, the `_print_landed_fix_flag` / `_print_remedy_gate` posture:
    it never sets a currency token, never changes a route, emits no event and moves no exit code.
    Printed for EVERY currency (unlike the landed-fix flag, which is TRULY-NEW-only): knowing that a
    row is one spelling of a 112-occurrence root is what stops it being read as brand-new work, and
    that is exactly as true of an ALREADY-FIXED or OWNED-IN-FLIGHT member."""
    fam = _declared_root_siblings(fp, counts)
    if not fam:
        return
    root, siblings, total = fam
    print(f"      declared root: {root}  ({len(siblings) + 1} captured spellings, {total} occurrence(s) "
          f"all-time) — this fingerprint names its root and varies the SUBJECT, so it is ONE spelling "
          f"of that root, not a class of its own (T-11898)")


def _print_unlinked_mention_flag(currency: str, fp: str, mention_idx: dict,
                                 mention_derived: bool = False) -> None:
    """UNLINKED MENTION (T-11898) — an existing card NAMES this fingerprint in its body but does NOT
    carry it in `cites:`, so the LINK RULE cannot see it and the row renders as brand-new work.

    THIS DOES NOT LINK ANYTHING, AND MUST NOT. SPEC-0068 makes linkage `cites:`-EXCLUSIVE ("no
    body-text parsing") and says in the same breath that "a human-readable body mention is allowed but
    is never the derivation source". Both halves are honoured here: the mention is reported, never
    derived from — `currency`, the suggested route, the exit code and `_fingerprint_cites_index` are
    all untouched. What this closes is that SPEC-0068's own allowed-but-not-a-source rule had NO
    failure detector: an author who mentioned without citing produced a silent
    `(no case file — promotion candidate)`, and the next reviewer cut a duplicate card.

    MEASURED at T-11898 (2026-08-30): `selection-omitted-a-test-naming-a-changed-path` rendered
    ownerless at 141 occurrences while T-11462 / T-11475 / T-11476 (done) and T-11883 (ready) all name
    it in prose and NONE cites it; `worktree-sweep-permission-impossible-residue` likewise at 12, named
    by T-10891 and T-10897.

    TRULY-NEW only, the `_print_landed_fix_flag` boundary: that is the one currency that files a NEW
    card, so it is the exact moment before a mention-without-citation becomes a duplicate. Advisory,
    never a block — filing stays the author's call; this only removes the excuse of not knowing.

    WIDENED BY `mention_derived` (T-11903), and the widening is what keeps this advisory HONEST. Once
    a mention supplies the comparison boundary, the very rows this flag was written for stop being
    TRULY-NEW — they become ALREADY-FIXED or REGRESSED — so a TRULY-NEW-ONLY gate would have made the
    flag VANISH from exactly the rows now acting on the mention. That is the worst reading of all: a
    verdict resting on prose, with the prose it rests on no longer shown. So the flag ALSO fires for a
    mention-derived verdict, naming the cards the boundary came from. The gate stays otherwise
    unchanged (no mentions ⇒ silent; a cites-derived non-TRULY-NEW row ⇒ silent, as before)."""
    if currency != "TRULY-NEW" and not mention_derived:
        return
    mentions = mention_idx.get(fp) or []
    if not mentions:
        return
    if mention_derived:
        print(f"      ⚠ UNLINKED MENTION — {len(mentions)} existing artifact(s) NAME this fingerprint "
              f"in body text but do NOT carry it in `cites:`. The currency verdict above rests on the "
              f"LATEST `closed_at` among the DONE one(s) — a MENTION-DERIVED boundary, weaker than a "
              f"`cites:` link and owning nothing (T-11903):")
    else:
        print(f"      ⚠ UNLINKED MENTION — {len(mentions)} existing artifact(s) NAME this fingerprint in "
              f"body text but do NOT carry it in `cites:`, so the LINK RULE cannot see them and this row "
              f"reads as brand-new work (T-11898):")
    for aid, status, kind in mentions:
        print(f"          {aid} ({status}, {kind})")
    print("        this is NOT a link and does not own the fingerprint (SPEC-0068: linkage derives "
          "from `cites:` EXCLUSIVELY, a body mention is never the derivation source). READ those "
          "artifact(s) BEFORE filing: if one already covers this, do NOT file a duplicate — add the "
          "fingerprint to its `cites:` (`task close --closes-fp <fp>`, SPEC-0069) so the link becomes "
          "real; if none covers it, file and say why in the card.")


def _stale_open_ownerless(err_status: str, recurs: bool, owners: list, fix_task) -> bool:
    """STALE flag predicate (T-0460, D-0086 §PROMOTE): an open/reopened case that RECURS (N>=2) with
    NO owning fix-task is `file-or-waive-overdue` — it has sat in the limbo without being routed. NOT
    stale once a fix is filed: post-T-0459 `investigating` already means a fix-task exists, and a
    cites-owner that is a task (the §9 LINK RULE) OR a resolution.fix_task both mean it is owned. The
    AND is explicit (audit-pre F0): open|reopened AND recurs AND no task-owner AND no resolution.fix_task."""
    if err_status not in _STALE_OPEN_STATUSES or not recurs:
        return False
    if fix_task:                                          # the case already records a spawned fix-task
        return False
    if any(k == "task" for (_i, _s, k) in owners):        # a §9 cites-owner that is a task owns it
        return False
    return True


def _named_capturers(rows: list, is_named_actor=None) -> list:
    """The DISTINCT real PEOPLE among `rows`' capturers, first-seen order (T-10410).

    The triage half of the T-10405 author-surfacing idiom (`followup.py#_fmt_row`): a view names the
    capturer when there IS a person to name and stays SILENT otherwise (suppressed-when-clean), so the
    ~1000 `ai-agent` kernel captures gain no noise. The "is this a person?" predicate is INJECTED
    (`lib/memory.py#is_named_actor`, threaded from the host) — triage.py stays import-clean.
    """
    if not is_named_actor:
        return []
    seen: list = []
    for r in rows:
        a = r.get("actor")
        if is_named_actor(a) and a not in seen:
            seen.append(a)
    return seen


def cmd_triage_remedy(args: argparse.Namespace, *, EVENTS_PATH, _append_event, _die,
                      _scan_captures) -> None:
    """`triage remedy` — record a remedy-existence verdict against an ALREADY-CAPTURED fingerprint
    (T-11675 / X-1131). The WRITE side the SPEC-0063 §1 remedy sub-check never had.

    SPEC-0063 §1 requires a remedy-existence verdict before a TRULY-NEW candidate is promoted, and
    `triage run` flags every unswept row `⚠ REMEDY-UNSWEPT`. But the sanctioned carrier — the
    capture's own `data.remedy_ref` — is writable only at capture time, while the sweep is a
    TRIAGE-time act over an accumulated backlog. This verb closes that gap: it records the verdict
    at the moment the rule actually demands it, WITHOUT touching any recurrence count (see
    `_remedy_sweep_index` for why the distinct event type is the load-bearing choice).

    The sweep itself stays AI/owner-PERFORMED, unchanged (SPEC-0063 §1): this verb RECORDS a verdict
    a human reached; it never greps for an analog itself. Advisory posture is unchanged too — the
    recording clears the REMEDY-UNSWEPT flag, it does not gate `promote` (CHARTER non-goal #7).

    FAIL-CLOSED on three axes: the fingerprint MUST already appear among captured fingerprints (this
    records a verdict ABOUT a capture — it is not a back door for inventing one), EXACTLY one of
    `--remedy <ref>` / `--absent` must be given (a verdict with no direction records nothing), and —
    T-11936 — a `--remedy` must state its RE-TEST DIRECTION: exactly one of `--retested <what you
    re-ran, and what it did>` (⇒ ALREADY-BUILT, a real clearance) or `--no-retest <why it cannot be
    re-run>` (⇒ REMEDY-UNSWEPT — the artifact is RECORDED, the candidate is NOT cleared).

    WHY THE THIRD AXIS. `--remedy` records that an ARTIFACT exists; only re-running the ORIGINAL
    FAILING INPUT records that the BEHAVIOUR changed. Recording the first as if it were the second
    misleads in BOTH directions, three weeks apart: the 2026-08-26 sweep marked
    `owner-reset-unreachable-when-consult-survivor-is-hold-for-owner` already-built off T-10772, which
    is message-only and says so in its own docstring (a LIVE defect retired on paper); on 2026-08-31 a
    reporter read that same artifact, did not re-test, and filed X-1210 + T-11928 against a defect
    T-10899 had already fixed (a DEAD defect resurrected). The un-re-tested branch records the
    INABILITY rather than a built verdict — REUSING the existing third token, no fourth state is
    invented — which fails in the conservative direction: the candidate stays flagged, never silently
    retired. `--absent` is untouched: a sweep that found nothing has no behaviour to re-test.

    No worktree needed — an `event` append rides the D-0049 journal-append exception."""
    fp = (args.fp or "").strip()
    if not fp:
        _die("triage remedy: --fp <fingerprint> is required")
    have_ref = bool((args.remedy or "").strip())
    if have_ref == bool(args.absent):
        _die("triage remedy: give EXACTLY one of --remedy <ref> (an analog remedy EXISTS ⇒ "
             "ALREADY-BUILT) or --absent (the sweep ran and found NONE ⇒ REMEDY-ABSENT). "
             "A verdict with no direction records nothing.")
    known = {c["fp"] for c in _scan_captures(EVENTS_PATH) if c["fp"]}
    if fp not in known:
        _die(f"triage remedy: fingerprint '{fp}' has no capture in this journal — refusing. This verb "
             "records a remedy-existence verdict ABOUT an already-captured deviation; capture it "
             "first (`yitc-v2 event deviation_captured --data '{\"fingerprint\": \"...\"}'`), or "
             "check the spelling against `yitc-v2 triage run`.")
    # T-11936 — THE RE-TEST DIRECTION. A `--remedy <ref>` records that an ARTIFACT exists; only a
    # re-run of the ORIGINAL FAILING INPUT records that the BEHAVIOUR changed. Recording the first as
    # if it were the second is what produced both 2026-08 incidents, in OPPOSITE directions: the
    # 2026-08-26 sweep retired a LIVE defect off the message-only T-10772, and on 2026-08-31 a reader
    # of that same artifact resurrected a defect T-10899 had already fixed. So an ALREADY-BUILT
    # CLEARANCE now requires the re-test statement, and where the input cannot be re-run the verb
    # records THAT INABILITY rather than a built verdict. Fail-closed with the exactly-one idiom this
    # verb already applies to --remedy/--absent; `--absent` is untouched (a sweep that found nothing
    # has no behaviour to re-test). Advisory posture downstream is unchanged (CHARTER non-goal #7) —
    # nothing here gates `promote`; what is refused is RECORDING AN UNBACKED CLEARANCE.
    retested = (getattr(args, "retested", None) or "").strip()
    no_retest = (getattr(args, "no_retest", None) or "").strip()
    if have_ref:
        if bool(retested) == bool(no_retest):
            _die("triage remedy: --remedy records that an ARTIFACT exists; it does NOT by itself show "
                 "the BEHAVIOUR changed. Give EXACTLY one of --retested \"<the original failing input "
                 "you re-ran, and what it did>\" (⇒ ALREADY-BUILT, a real clearance) or --no-retest "
                 "\"<why that input cannot be re-run>\" (⇒ REMEDY-UNSWEPT — the artifact is recorded, "
                 "the candidate is NOT cleared). A remedy reference with no re-test direction is "
                 "exactly the record that both retired a live defect and resurrected a dead one "
                 "(T-11936).")
    elif retested or no_retest:
        _die("triage remedy: --retested / --no-retest describe a re-run of the failing input against a "
             "REMEDY, so they belong with --remedy. --absent means the sweep found no remedy at all — "
             "there is nothing to re-test against.")
    ref = (args.remedy or "").strip() if have_ref else "absent"
    verdict = _remedy_verdict(ref)      # the ONE mapping — never a second spelling of the 3-state
    if have_ref and no_retest:
        # The INABILITY, recorded instead of a built verdict. REUSES the existing third token — no
        # fourth remedy state is invented — and it is the conservative direction: the candidate stays
        # flagged not-promotable rather than being silently retired on an unverified artifact.
        verdict = "REMEDY-UNSWEPT"
    data = {"fingerprint": fp, "verdict": verdict, "remedy_ref": ref}
    if have_ref:
        data["retested"] = retested or None
        if no_retest:
            data["retest_absent_reason"] = no_retest
    if getattr(args, "swept", None):
        data["swept"] = args.swept      # WHAT was swept — provenance for the next reader
    if getattr(args, "found", None):
        data["found"] = args.found      # WHAT the sweep found — the reasoning, not just the verdict
    _append_event("remedy_swept", getattr(args, "task", None) or None, data)
    print(f"remedy-existence recorded: {fp} -> {verdict}  (remedy_ref: {ref})")
    if verdict == "REMEDY-UNSWEPT":
        # T-11936: the artifact IS recorded and named — what is withheld is the clearance.
        print(f"  artifact found: {ref}")
        print(f"  NOT re-tested — {no_retest}")
        print("  routes REMEDY-UNSWEPT, NOT already-built: the artifact exists but the reported "
              "BEHAVIOUR was not re-run against it, so this does NOT clear the candidate (T-11936). "
              "Re-record with --retested once the original failing input can be re-run.")
    elif verdict == "ALREADY-BUILT":
        print(f"  re-tested: {retested}")
        print("  routes ALREADY-BUILT — an analog remedy already exists AND the reported behaviour "
              "was re-run against it; confirm it covers this, do NOT file a duplicate (SPEC-0063 §1). "
              "ALREADY-BUILT is NOT into-work.")
    else:
        print("  routes TRULY-NEW, swept clean — genuinely new, into-work (SPEC-0063 §1).")
    print("  `triage run` reads this record alongside the capture-time `remedy_ref`; recurrence "
          "counts are untouched (this is not a capture).")


def cmd_triage_run(args: argparse.Namespace, *, ERRORS_DIR, EVENTS_PATH, _append_event, _capture_cluster_counts, _capture_fingerprint_counts, _case_attributions, _case_closure_index, _cross_origin_fp_index, _die, _discovery_stem_clusters, _error_fingerprint_index, _fingerprint_cites_index, _last_triage_watermark, _owner_closed_at_index, _read_yaml, _scan_captures, _stage_bundle_specs, _is_consumer_build, is_named_actor=None, _fingerprint_mention_index=None) -> None:
    """Sweep un-routed captures since the last watermark, print the routes + §5 checklist; `--complete`
    emits the triage_run_completed watermark (the CLOSED boundary that closes this run's window)."""
    prior = _last_triage_watermark(EVENTS_PATH)
    if args.complete:
        # The WATERMARK is the durable routed-boundary (audit-pre F0 — no per-fingerprint ledger):
        # window_since records the window THIS run covered = the prior watermark (or null bootstrap).
        # window_through is the ROUTED-BOUNDARY the next run reads (T-0542): the max ts of the window
        # the operator ACTUALLY ROUTED. Keying the next window off window_through — not off the
        # completion-event `ts` (= now) — closes the same-second SILENT-LOSS class: a capture in a
        # later second than the boundary stays in-window instead of colliding with `ts==now` and
        # falling out forever (see _last_triage_watermark for the full hazard note).
        #
        # GAP-FREE basis (audit-post F1): the boundary MUST be the max ts of what the READ run showed,
        # NOT a fresh rescan at completion — a rescan would advance past a capture that arrived in the
        # read→complete gap (shown to no one, yet marked routed → lost). So `--through TS` lets the
        # operator PIN the read window's max ts (the `triage run` read prints the value to copy). When
        # `--through` is given it is authoritative. When it is OMITTED (back-compat default), the rescan
        # max is recorded as a best-effort boundary — still a strict improvement over `ts=now` — but the
        # read→complete-gap capture remains the documented residual (alongside the exact-equal-second
        # tie), both DEFERRED to T-0533's per-capture routed-marker. It defaults to `prior` when nothing
        # newer is seen (a no-op `--complete` → the boundary never regresses, stays drainable).
        if getattr(args, "through", None):
            # Validate the operator-pinned boundary (audit-post F1): it must be a well-formed UTC ISO ts
            # AND never EARLIER than `prior` — a backward move would re-open already-routed captures and
            # break the non-regressing safety contract this task introduces. (Equal to `prior` is fine —
            # a no-op window.) The completion `ts` (= now) is the natural upper sanity bound but is NOT
            # enforced: a same-second skew between the pinned value and now is exactly the case we accept.
            try:
                _dt.datetime.fromisoformat(args.through.strip().replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                _die(f"triage run --complete --through: {args.through!r} is not a UTC ISO timestamp "
                     f"(expected e.g. 2026-06-07T12:00:00Z).")
            if prior is not None and args.through < prior:
                _die(f"triage run --complete --through: {args.through!r} is EARLIER than the current "
                     f"boundary {prior!r} — that would regress the routed boundary and re-open already-"
                     f"routed captures (non-regression safety contract, T-0542). Pin the READ run's max ts.")
            window_through = args.through            # operator-pinned read-window max (gap-free path)
        else:
            observed = [c["ts"] for c in _scan_captures(EVENTS_PATH)
                        if c["type"] == "deviation_captured" and c["ts"]
                        and (prior is None or c["ts"] > prior)]
            window_through = max(observed) if observed else prior

        # T-9639 (X-0126): RECORD THE ROUTE PER CAPTURE, not just a watermark count. The window's
        # captures WERE routed (e.g. 4->tasks, 3->cross) but the old `--complete` recorded routed=0
        # because nothing DERIVED the counts and no capture->target link was recorded — the routing
        # audit-trail was lost. We do NOT add a new carrier: the capture->target link is read from the
        # ALREADY-PERSISTED filing carriers (the source of truth, created at filing time) — a task via
        # the §9 LINK RULE `cites:` (`_fingerprint_cites_index`) and a cross via `cross_requested.
        # origin_fp` (`_cross_origin_fp_index`). One route ROW per capture EVENT in the window (NOT
        # collapsed to distinct fp — two same-second same-fp captures yield two rows; audit-pre F2).
        # T-10505 (X-0344): the THIRD carrier — an E-file case file. SPEC-0055 §Triage run names FOUR
        # routes (`event-only` · `linked` · `promote-to-fix-task` · `promote-to-E-XXXX`), but the T-9639
        # loop consulted only the cites + cross carriers, so the spec's own `promote-to-E-XXXX` route fell
        # into the `else:` and was reported as un-dispositioned — the under-count aiseller filed X-0344 on.
        # `_error_fingerprint_index` was ALREADY injected here and never read (the dangling DI that
        # betrays the gap). Its value is a `(E-id, status)` TUPLE — same shape `_currency_status` /
        # `_resolved_case_fix_owner` read — so take `err[0]` for the id, never the raw tuple.
        cites_idx = _fingerprint_cites_index()           # fp -> [(id, status, kind)]
        cross_idx = _cross_origin_fp_index()             # origin_fp -> X-id
        error_idx = _error_fingerprint_index()           # fp -> (E-id, status)
        # T-11849 — CONSERVATION AT THE WATERMARK. `window_caps` requires `c["fp"]`, because every
        # routing carrier is keyed by fingerprint. That filter is correct, but it was SILENT: a
        # no-fingerprint capture was counted by the read path's header, shown a row, then dropped here
        # while the boundary still advanced past it — unreachable in every future window. So derive
        # the FULL window first (the same filter minus the fingerprint requirement) and report the
        # difference instead of swallowing it.
        _full_window = [c for c in _scan_captures(EVENTS_PATH)
                        if c["type"] == "deviation_captured" and c["ts"]
                        and (prior is None or c["ts"] > prior)
                        and (window_through is None or c["ts"] <= window_through)]
        window_caps = [c for c in _full_window if c["fp"]]
        withheld_no_fp = [c for c in _full_window if not c["fp"]]
        routes: list = []
        for c in window_caps:
            fp = c["fp"]
            cited = cites_idx.get(fp)
            err = error_idx.get(fp)
            if cited:                                    # task/decision owns it (prefer a task target)
                tid, _st, kind = next((e for e in cited if e[2] == "task"), cited[0])
                routes.append({"ts": c["ts"], "fingerprint": fp,
                               "target_kind": kind, "target_id": tid})
            elif fp in cross_idx:                        # routed to a cross coordination item
                routes.append({"ts": c["ts"], "fingerprint": fp,
                               "target_kind": "cross", "target_id": cross_idx[fp]})
            elif err:                                    # promoted to an E-file case file (SPEC-0055 route 4)
                routes.append({"ts": c["ts"], "fingerprint": fp,
                               "target_kind": "error", "target_id": err[0]})
            # else: genuinely unrouted (event-only) — no link to record

        # routed/linked are DERIVED authoritatively from the route set (NOT operator override — the
        # X-0126 defect was a recorded count disagreeing with the actual routes). `linked` = the cites-
        # owned subset (task/decision); the cross subset is routed-but-not-`linked`. `promoted` stays
        # operator-supplied — whether a route is to a NEWLY-filed vs pre-existing owner is not derivable
        # post-hoc. The --routed/--linked flags are retained for CLI back-compat but no longer override.
        derived_routed = len(routes)
        derived_linked = sum(1 for r in routes if r["target_kind"] in ("task", "decision"))
        data = {"routed": derived_routed, "linked": derived_linked,
                "promoted": int(args.promoted or 0), "window_since": prior,
                "window_through": window_through,
                # T-11849: the conservation trail — how many captures the window HELD, and how many
                # of them no route could be recorded for. Without these a reader of the recorded
                # event sees `routed=N` with no way to tell N from the window it closed.
                "window_captures": len(_full_window),
                "withheld_no_fingerprint": len(withheld_no_fp)}
        if routes:                                       # the per-capture capture->target audit-trail
            data["routes"] = routes

        # T-10505 (X-0344): NEVER ZERO THE OPERATOR'S NUMBERS SILENTLY. The flags stay non-authoritative
        # (reverting that is the X-0126 defect), but an operator who asserts 5 and sees 0 recorded is owed
        # the REASON — otherwise the derivation reads as a silent bug (which is exactly what got filed).
        for flag, asserted, derived in (("--routed", getattr(args, "routed", None), derived_routed),
                                        ("--linked", getattr(args, "linked", None), derived_linked)):
            if asserted is not None and int(asserted) != derived:
                print(f"WARN: {flag} {int(asserted)} does not match the DERIVED count {derived} — the "
                      f"derived value is authoritative and is what gets recorded (T-9639/X-0126: a count "
                      f"disagreeing with the actual routes was the defect). A capture counts as routed "
                      f"ONLY through a persisted carrier: a task/decision that `cites:` its fingerprint "
                      f"(`task close --closes-fp <fp>`), a cross item carrying it as `origin_fp`, or an "
                      f"errors/E-XXXX case file owning it. An uncounted route means its link was never "
                      f"recorded — link it, then re-run.")
        # T-11849: WARN — never advance the boundary past a capture no route was recorded for without
        # saying so. WARN rather than refuse: a no-fingerprint capture is legitimately event-only, and
        # refusing would wedge the very backlog this reporting exists to let the operator close. Same
        # non-silent posture as the X-0344 `--routed` WARN just below.
        if withheld_no_fp:
            print(f"WARN: {len(withheld_no_fp)} of the window's {len(_full_window)} capture(s) carry "
                  f"NO fingerprint, so no route could be recorded for them (every routing carrier — a "
                  f"task `cites:`, a cross `origin_fp`, an E-file — is keyed by fingerprint). The "
                  f"boundary is about to advance PAST them, and they will not appear in any future "
                  f"window. If any of them still needs routing, stop, assign it a fingerprint, and "
                  f"re-run. Recorded as withheld_no_fingerprint={len(withheld_no_fp)}.")
        _append_event("triage_run_completed", None, data)
        print(f"triage_run_completed emitted — window_captures={data['window_captures']} "
              f"routed={data['routed']} linked={data['linked']} "
              f"withheld_no_fingerprint={data['withheld_no_fingerprint']} "
              f"promoted={data['promoted']}; window_since={prior or '(bootstrap — journal start)'}; "
              f"window_through={window_through or '(no captures observed — boundary unchanged)'}")
        if routes:
            print(f"  recorded {len(routes)} capture->target route(s): "
                  + ", ".join(f"{r['fingerprint']}->{r['target_id']}" for r in routes[:6])
                  + (" …" if len(routes) > 6 else ""))
        print("the next `triage run` sweeps only captures AFTER window_through (closed boundary, T-0542).")
        return

    captures = _scan_captures(EVENTS_PATH)
    counts = _capture_fingerprint_counts(EVENTS_PATH)
    # T-11675: the TRIAGE-TIME remedy sweep records (`remedy_swept`), the second read input to the
    # SPEC-0063 §1 3-state beside the capture-time field. Folded ONCE here; a distinct event type, so
    # `counts` above and every recurrence input below are untouched by it.
    remedy_sweeps, remedy_retests = _remedy_sweep_index(EVENTS_PATH)   # T-11936: refs + re-test provenance
    cites_idx = _fingerprint_cites_index()
    # T-11898: the UNLINKED-MENTION advisory index — artifacts that NAME a captured fingerprint in body
    # text without carrying it in `cites:`. Report-only; the LINK RULE above stays the sole authority
    # (SPEC-0068). Keyed on `counts` (the CAPTURED set) so it is a lookup, never prose-mining. Optional
    # by injection (the `is_named_actor` precedent): absent ⇒ the flag simply never fires.
    mention_idx = _fingerprint_mention_index(counts) if _fingerprint_mention_index else {}
    err_idx = _error_fingerprint_index()
    # E-id -> resolution.fix_task (or None) — the STALE-flag predicate (T-0460) needs to know whether a
    # case already spawned a fix-task. Read once here (a derived view, no new store); err_idx keeps its
    # 2-tuple shape so every existing unpacker is untouched.
    error_fix_task: dict = {}
    # T-11041: the set of case-ids whose waive DECLARES `resolution.by_design_residual: true` — the
    # SPEC-0056 §4 flag the currency classifier must honour (a declared residual recurrence is
    # EXPECTED, never REGRESSED/into-work). Collected in the SAME single pass that already reads
    # `resolution` for error_fix_task: no extra I/O, no new store (anti-complexity F2).
    error_by_design: set = set()
    # T-11897: the case-ids resolved via a LANDED ROOT FIX rather than a promote-filed fix-task
    # (`resolution.kind: root_fix_landed`). Such a case records its root_fix as PROSE and carries no
    # fix_task, so the E-0036 boundary above can never resolve it. Collected in the SAME single pass
    # that already reads `resolution` — no extra I/O, no new store (anti-complexity F2).
    error_root_fix_kind: set = set()
    # T-11921: the case-ids whose `resolution` is present but NOT a mapping. Every read below treats
    # `resolution` as a mapping, so ONE malformed record used to take the WHOLE `triage run` down with
    # `AttributeError: 'str' object has no attribute 'get'` — the reader died instead of NAMING the
    # record it could not read. A malformed one is now SKIPPED for the resolution-derived indices and
    # reported as malformed after the pass; the run continues. Reuses the existing WARN convention, no
    # new store beyond the id list the WARN needs (anti-complexity F2).
    error_malformed_resolution: list = []
    if ERRORS_DIR.exists():
        for _p in state.scan_errors(ERRORS_DIR):
            _d = _read_yaml(_p)
            if _d.get("id"):
                # `or {}` alone would swallow a FALSEY malformed value ("" / [] / 0) back into the
                # absent case, so the raw value is type-checked FIRST and only then defaulted: absent
                # or null = no resolution (ordinary), anything else non-mapping = malformed (T-11921).
                _raw = _d.get("resolution")
                if _raw is not None and not isinstance(_raw, dict):
                    error_malformed_resolution.append(_d["id"])
                    continue
                _res = _raw or {}
                error_fix_task[_d["id"]] = _res.get("fix_task")
                if _res.get("by_design_residual"):
                    error_by_design.add(_d["id"])
                if _d.get("status") == "resolved" and _res.get("kind") == "root_fix_landed":
                    error_root_fix_kind.add(_d["id"])
    if error_malformed_resolution:
        print(f"WARN: {len(error_malformed_resolution)} error record(s) carry a MALFORMED "
              f"`resolution` (present but not a mapping) and were skipped for every resolution-derived "
              f"read: {', '.join(sorted(error_malformed_resolution))}. Today's schema writes "
              f"`resolution` as a MAPPING with a `kind`; fix the named record(s) — the rest of this "
              f"run is unaffected (T-11921).")
    # R-A temporal recurs (SPEC-0061): a done-owner's recurrence is REAL only if a capture post-dates
    # the fix's closed_at. owner_closed_at = {task-id: closed_at}; fp_tss = all-time capture timestamps
    # per fingerprint (same capture set that feeds `counts`), so _recurs_after_close can test
    # "a capture strictly AFTER closed_at" instead of the bare all-time count for a done-owner.
    owner_closed_at = _owner_closed_at_index()
    # T-11897: the SECOND boundary shape. A `root_fix_landed` case has no fix-task and therefore no
    # `closed_at`, so its datable landing is folded from its own `error_resolved` journal row and
    # merged into ONE boundary map the R-A comparator reads. `owner_closed_at` itself is NOT mutated
    # (it is a shared derived view), and E-ids cannot collide with T-ids, so the merge is total.
    error_root_fix_at = _error_root_fix_landed_at(EVENTS_PATH, error_root_fix_kind)
    boundaries = {**owner_closed_at, **error_root_fix_at}
    fp_tss: dict = {}
    for _c in captures:
        if _c["fp"] and _c["ts"]:
            fp_tss.setdefault(_c["fp"], []).append(_c["ts"])
    # R-C cited-rollup (SPEC-0061, T-0626): the AUTHORITATIVE cite-based cluster rollup (the SAME view
    # Section B uses) — computed ONCE here so Section A can link a cited-ALIAS of an owned root to that
    # root (instead of a string-miss TRULY-NEW), and Section B reuses it. member_to_canon maps each
    # cluster member fp to its canonical root. The DISCOVERY stem-cluster (_discovery_stem_clusters,
    # SPEC-0055) is deliberately NOT consulted — cited-rollup ONLY (a hint is never a currency authority).
    clusters = _capture_cluster_counts(EVENTS_PATH)
    member_to_canon = {m: canon for canon, cl in clusters.items() for m in cl["members"]}
    # Routing window: deviation_captured strictly AFTER the last non-probe watermark (closed
    # boundary). Legacy friction_captured is read-only — it feeds the cluster set, not routing.
    window = [c for c in captures if c["type"] == "deviation_captured"
              and (prior is None or c["ts"] > prior)]

    # T-0542: the max ts of THIS read's window — the gap-free boundary to PIN at completion. Printed so
    # the operator can copy it into `triage run --complete --through <ts>`, recording the boundary at
    # what THIS read actually showed (NOT a rescan at completion, which would advance past a capture
    # that arrived in the read→complete gap — audit-post F1).
    read_through = max((c["ts"] for c in window if c["ts"]), default=prior)

    print("# triage run (SPEC-0055 §triage-run slow lane — owner-invoked Review scan, NOT cron/auto)")
    print(f"sweep window: deviation_captured since {prior or '(bootstrap — journal start)'} "
          f"(the watermark is a CLOSED boundary, excluded from this window)")
    if window:
        print(f"to close this exact window gap-free, run: `triage run --complete --through {read_through}` "
              f"(pins the boundary at what THIS read showed — T-0542)")
    print()

    # ---- Filing-contract delivery at the triage/revizia ENTRY (T-9638 / X-0128; the ACTIVE Filing bundle) ----
    # The triage scan's expected OUTPUT is filing (the promote-to-fix-task route in Section C), but no
    # task Filing stage is entered here — so a `task file` mid-batch would surprise-refuse on the
    # SPEC-0059 read-gate (the Filing bundle not fetched this session) even though the handbook seed was
    # read. Deliver the Filing stage-entry contract AT this entry, symmetric with the Filing stage-entry,
    # by emitting an HONEST node_id-bearing delivery-RECEIPT per bundle spec: verb="triage run" (NOT
    # "graph query", so a journal consumer never confuses it with a real interactive fetch) carrying
    # node_id=<spec> + an explicit `delivery` marker. The read-gate's credit path `_fetched_spec_ids`
    # keys ONLY on data.node_id (verb-agnostic, bin/lib/gates.py), so this receipt credits the gate via
    # the EXISTING path — no new reducer, no new event type (CHARTER P1; same idiom as the journal
    # recovery-rescan credit). So the filing batch is not interrupted.
    #   T-10686: the delivered set is DERIVED from the ACTIVE Filing bundle (`_stage_bundle_specs("Filing")`,
    #   the SAME binding-derived carrier the read-gate enforces — bin/lib/gates.py `_require_reads`), NOT a
    #   hardcoded SPEC-0060. When SPEC-0165 (loud-failure doctrine) activates it ALSO binds stage-entry:Filing
    #   (T-10679), widening the gate to {SPEC-0060, SPEC-0165}; deriving here keeps triage's delivery in lockstep
    #   so the batch stays un-surprised under the widened gate (P5 single-source). `include_kernel` mirrors the
    #   gate's `_is_consumer_build()` resolution so a -C consumer's kernel-provided Filing specs are delivered too.
    #   A corpus-read failure degrades `_stage_bundle_specs` to [] — fall back to the always-active SPEC-0060 so
    #   the T-9638 guarantee never regresses on a broken sandbox.
    filing_specs = _stage_bundle_specs("Filing", include_kernel=_is_consumer_build()) or ["SPEC-0060"]
    for _sid in filing_specs:
        _append_event("cli_invoked", None,
                      {"verb": "triage run", "node_id": _sid,
                       "delivery": "filing-contract-at-triage-entry"})
    _joined = ", ".join(filing_specs)
    print(f"filing-contract delivery ({_joined}, T-9638): triage's expected output is filing "
          "(promote-to-fix-task) — the task-authoring doctrine is delivered at this entry, so a "
          f"`task file` below is not read-gate-refused. Read the full doctrine: "
          f"`yitc-v2 graph query {filing_specs[0]}`.")
    print()

    # ---- Section A: routing window — the captures to route THIS run ----
    # T-11849 — CONSERVATION. Three populations were printed for one window with nothing reconciling
    # them: the header counts capture EVENTS, the bullet rows count fingerprint CLASSES (one row per
    # class, `xN this window`), and a `currency_status:` verdict is printed ONLY inside the
    # fingerprint-class loop. Measured on the 2026-08-30 corpus: header 2025, rows 1728 (1636 class
    # rows + 92 no-fingerprint rows), currency 1636 — and the arithmetic DOES conserve (1933 + 92 =
    # 2025), so nothing is missing from the LISTING. What was genuinely lost sits one level down: a
    # no-fingerprint capture gets no verdict here AND is dropped by `--complete`'s `window_caps`
    # (which requires `c["fp"]`) while the watermark still advances past it — counted, shown, never
    # routed, then unreachable in every future window. So the header is NEVER lowered to make the
    # numbers agree (that would hide the population); instead the arithmetic is STATED, a self-check
    # makes a future divergence loud, and the withheld set is NAMED with its reason. Deliberately NOT
    # a 5th `currency_status` value: SPEC-0056 §5 enumerates exactly five, and a missing fingerprint
    # is an absence of routing evidence, not a currency state (CHARTER §P1 F2 — a derived statement
    # over a new entity). Report-only throughout, the `_print_remedy_gate` / `_print_landed_fix_flag`
    # posture: no currency, route or exit-code changes here.
    by_fp: dict = {}
    no_fp: list = []
    for c in window:
        (by_fp.setdefault(c["fp"], []) if c["fp"] else no_fp).append(c)
    _fp_caps = sum(len(g) for g in by_fp.values())
    print(f"== A. Routing window: {len(window)} capture(s) to route ==")
    if window:
        print(f"  conservation: {len(window)} capture(s) = {_fp_caps} in {len(by_fp)} fingerprint "
              f"class(es) (one row each, x N per row) + {len(no_fp)} without a fingerprint "
              f"(one row each) = {len(by_fp) + len(no_fp)} row(s) below")
        # The self-check (T-11849): every counted capture must reach a row. Today this always holds —
        # it exists so that a FUTURE filter between the window and the render FAILS LOUDLY instead of
        # rendering as a silently shorter list, which is precisely how this class hid.
        _rendered = _fp_caps + len(no_fp)
        if _rendered != len(window):
            print(f"  ⚠⚠ CONSERVATION BREACH: {len(window) - _rendered} counted capture(s) reach NO "
                  f"row below — they cannot be routed, and advancing the watermark past them loses "
                  f"them permanently. Do NOT run `triage run --complete` until this is explained.")
    if not window:
        print("  (none — every capture before the watermark is already routed)")
    else:
        for fp in sorted(by_fp):
            grp = by_fp[fp]
            rel = next((g["relates_to"] for g in grp if g["relates_to"]), "")
            # T-0500: the recorded remedy-existence sweep value for this fp (first non-empty, like rel).
            # T-11675: a TRIAGE-TIME `triage remedy` record WINS over it when one exists.
            remedy = _resolve_remedy(fp, next((g["remedy"] for g in grp if g.get("remedy")), None),
                                     remedy_sweeps)
            # T-11936: does the live remedy verdict rest on an ARTIFACT alone (no re-run of the
            # original failing input)? Read from the same latest-wins fold.
            retest_absent, retest_reason = _resolve_retest(fp, remedy_retests)
            owners = cites_idx.get(fp, [])
            e = _with_by_design(err_idx.get(fp), error_by_design)
            # R-C (SPEC-0061, T-0626): if fp has NO exact owner AND no own case file but IS a cited-ALIAS
            # member of an owned root cluster (the authoritative cited-rollup), inherit the ROOT's
            # ownership so the alias links/OWNED instead of a string-miss TRULY-NEW. Gate `not owners and
            # not e` = direct/self ownership wins (already linked); R-C fires only on the genuine miss.
            # Cited-rollup ONLY — discovery-stem (SPEC-0055) is never consulted here.
            if not owners and not e:
                _canon = member_to_canon.get(fp)
                if _canon and _canon != fp:
                    owners = cites_idx.get(_canon, [])
                    e = _with_by_design((clusters[_canon]["error"], clusters[_canon]["status"]),
                                        error_by_design)
            print(f"  • {fp}  (x{len(grp)} this window, x{counts.get(fp, 0)} all-time)")
            if rel:
                print(f"      relates_to: {rel}")
            # T-10410: WHO captured this class — printed ONLY when a real person did (suppressed-when-clean,
            # the followup-list idiom). Read-only beside the routing facts; never a currency/route input.
            _by = _named_capturers(grp, is_named_actor)
            if _by:
                print(f"      captured by: {', '.join(_by)}")
            e_txt = f"{e[0]} ({e[1]})" if e else "— none"
            own_txt = ", ".join(f"{i}({s},{k})" for i, s, k in owners) if owners else "— none"
            print(f"      E-XXXX: {e_txt}    cites-owned-by: {own_txt}")
            # R-A (SPEC-0061): a done-owner recurs only if a capture post-dates its closed_at; with no
            # done-owner closed_at the prior all-time count>=2 stands (the fallback). E-0036: resolve a
            # resolved case's done fix-task (cited by case-id, not the fp) as a synthetic done owner so
            # the boundary engages instead of a false REGRESSED.
            r_owners = _resolved_case_fix_owner(e, owners, error_fix_task, boundaries,
                                                error_root_fix_at)
            # T-11903: the THIRD boundary carrier — a DONE card that NAMES this fingerprint in body
            # text without citing it. Applied AFTER the case-file shapes above, and gated on
            # `not owners and not e` inside the helper, so a cites-derived or case-file verdict is
            # never displaced: this can only fill the vacuum where the row would render a bare
            # TRULY-NEW. The boundary is the LATEST closed_at across ALL mentioning done cards,
            # because the EXISTING comparator already takes max() over the done owner set.
            m_owners = _mention_derived_boundary_owners(r_owners, e, mention_idx.get(fp), boundaries)
            mention_derived = bool(m_owners)
            r_owners = r_owners + m_owners
            recurs = _recurs_after_close(r_owners, fp_tss.get(fp, []), boundaries,
                                         counts.get(fp, 0) >= 2)
            # T-11897: a `resolved` case for which NEITHER boundary shape resolved — `recurs` has
            # fallen back to the bare count and says nothing about the fix, so the verdict must
            # withhold rather than default. Same predicate the comparator uses, never a second one.
            unresolvable = bool(e) and e[1] == "resolved" and not _fix_boundaries(r_owners, boundaries)
            currency, _route = _currency_status(r_owners, e, recurs, remedy, unresolvable,
                                                mention_derived, retest_absent)
            print(f"      currency_status: {currency}    "
                  f"into-work: {'YES' if currency in _INTO_WORK else 'no'}")
            _print_remedy_gate(currency, remedy, retest_reason)   # T-0500 / T-11936
            _print_boundary_gate(e, unresolvable)  # T-11897: name an unestablishable fix boundary
            # T-11898: name the DECLARED ROOT, so one spelling of a many-spelling root is not read as a
            # class of its own. Section A is per-capture and cannot be rolled up the way B/B2 are.
            _print_declared_root_flag(fp, counts)
            # T-10340: the capture is about to become a card — flag a class whose fix ALREADY LANDED.
            # Advisory beside the remedy gate; never a currency/route change (`currency` is read, not set).
            _print_landed_fix_flag(currency, fp, cites_idx)
            # T-11898: an existing card NAMES this fingerprint in prose but never cited it — the miss
            # the cites-exclusive LINK RULE cannot see. Advisory only; links nothing (SPEC-0068).
            _print_unlinked_mention_flag(currency, fp, mention_idx, mention_derived)
            # MERGE NOTE (T-11897 x T-11898, concurrent siblings on one file): both halves add ADVISORY
            # rows here and both touched this route line. BOTH are kept — T-11897's boundary gate +
            # `unresolvable` route argument (the currency-boundary half) AND T-11898's declared-root and
            # unlinked-mention flags (the fingerprint-identity half). Neither hunk was discarded.
            print(f"      suggested route: {_suggest_route(fp, counts.get(fp, 0), r_owners, e, recurs, remedy, unresolvable, mention_derived, retest_absent)}")
        if no_fp:
            # T-11849: name the WITHHELD set + WHY, the card's explicit second branch. These captures
            # ARE counted by the header and DO get a row — what they do not get is a currency verdict
            # or a `--complete` route record, because every routing carrier is keyed by fingerprint.
            print(f"  ── {len(no_fp)} capture(s) WITHHELD from routing: no fingerprint, so no "
                  f"currency verdict and no `--complete` route record (every routing carrier — a task "
                  f"`cites:`, a cross `origin_fp`, an E-file — is keyed by fingerprint) ──")
        for c in no_fp:
            _by1 = f"  [by: {c['actor']}]" if (is_named_actor and is_named_actor(c.get("actor"))) else ""
            print(f"  • (no fingerprint) {c['ts']} relates_to={c['relates_to'] or '—'}: "
                  f"{c['finding'][:80]}{_by1}")
            print("      withheld from routing: no fingerprint — `triage run --complete` records no "
                  "route for this capture, and the watermark still advances past it. Assign a "
                  "fingerprint in triage or this capture is unreachable in every future window.")
            print("      suggested route: assign a fingerprint in triage, or event-only if one-off")
    print()

    # ---- Section A2: SPEC-0178 rule 5 — the DERIVED audit-post case attribution (T-11158) ----
    # WHERE THE JOIN SURFACES IS TRIAGE, "because that is where the judgement already lives" (rule 5).
    # `kind` is optional at capture and decided at triage (SPEC-0056 §1), and this sweep already walks
    # un-routed captures and assigns each a route — so the derived link RIDES that existing pass: the
    # router is HANDED "this capture is against a card that closed under case X" instead of being
    # expected to reconstruct a counterfactual about a card whose exempt status the author may never
    # have seen. No new surface and no new moment of judgement; the `kind: defect` call stays human and
    # is the only thing left that is.
    # REPORT-ONLY and SUPPRESSED-WHEN-CLEAN (the `_print_landed_fix_flag` idiom): a project that
    # declares no case — every project until one opts in, and the kernel permanently — sees nothing.
    # The state itself is DERIVED at every read (rule 5), so nothing here is recorded or remembered.
    case_rows = [r for r in _case_attributions(window, closure_index=_case_closure_index(EVENTS_PATH))
                 if r["case"] or r["disagreement"]]
    if case_rows:
        _counting = sum(1 for r in case_rows if r["counts"])
        print(f"== A2. audit-post case attribution: {len(case_rows)} case-linked capture(s), "
              f"{_counting} advancing a restoration counter (SPEC-0178 rule 5 — report-only) ==")
        for r in case_rows:
            _src = ("derived" if r["derived"] and not r["manual"] else
                    "supplied" if r["manual"] and not r["derived"] else
                    "derived+supplied (agree)" if r["case"] else "CONFLICT")
            _verdict = ("COUNTS toward restoration (K attributed defects in W restore the case)"
                        if r["counts"] else "does NOT count — " + r["why"])
            print(f"  • {r['ts']}  {r['task_id'] or '(no task_id)'}  "
                  f"case: {r['case'] or '— unresolved'}  [{_src}]")
            print(f"      {_verdict}")
        print("  the DERIVED case is canonical; a hand-supplied `exempted_case` applies only where no")
        print("  derived one exists, and a DISAGREEMENT advances nothing until a human resolves it —")
        print("  either the card's recorded case is wrong or the capture was attributed to the wrong one.")
        print()

    # ---- Section B: cluster set — generalization depth, all-time, by fingerprint ----
    # CLUSTER-AWARE (T-0277): a fragmented root (many near-synonym fingerprints, each N=1) is rolled
    # up under its canonical fingerprint via the `cites:` LINK RULE so the TRUE recurrence is countable
    # (closes the D-0035 undercount). Clustered members are shown under the canonical class, not
    # standalone; un-clustered fingerprints keep the prior per-fingerprint disposition.
    # `clusters` is computed ONCE near the top (with the R-C derived views, T-0626) and reused here.
    clustered_members = {fp for cl in clusters.values() for fp in cl["members"]}

    def _surface_cluster(canon: str, cl: dict) -> bool:
        # N>=2 ADVISORY, NOT a visibility gate on a KNOWN root (T-0460, D-0086 §5). Every cluster from
        # _capture_cluster_counts is case-file-owned (a known root via the §9 cites: rollup), so it
        # surfaces when total>=2 OR it is a known-root ALIAS-SINGLETON: total==1 whose single captured
        # member is a cited ALIAS (not the canonical itself), i.e. the canonical is uncaptured but an
        # alias recurred once. That alias-singleton must show as linked/regressed, never be hidden by
        # the promotion threshold (the prior >=2 re-gate dropped it). A lone canonical with no captured
        # aliases is already excluded upstream (total==canon count is not returned by the rollup).
        if cl["total"] >= 2:
            return True
        # total==1 from the rollup is BY CONSTRUCTION a captured alias of an uncaptured canonical
        # (a total==canon-count cluster is filtered out upstream), so it IS the alias-singleton case.
        return cl["total"] == 1 and canon not in cl["members"]

    cluster_rows = {canon: cl for canon, cl in clusters.items() if _surface_cluster(canon, cl)}
    # DISCOVERY stem-clusters (T-0458) — uncited near-synonym families, a SIBLING of the cited-rollup
    # above (which is untouched). A recurring fp that belongs to a discovery family is shown under that
    # family, NOT standalone (no double-print).
    discovery = _discovery_stem_clusters(EVENTS_PATH)
    discovery_members = {fp for cl in discovery.values() for fp in cl["members"]}
    recurring = {fp: n for fp, n in counts.items()
                 if n >= 2 and fp not in clustered_members and fp not in discovery_members}
    print(f"== B. Cluster set: {len(cluster_rows) + len(recurring)} cited/standalone recurring "
          f"fingerprint(s) "
          f"(generalization depth — all-time, by fingerprint; known-root clusters rolled up via cites "
          f"LINK RULE; N>=2 is the PROMOTION advisory, NOT a visibility gate on a known root — T-0460; "
          f"uncited discovery families are NOT counted here — listed separately in B2, T-0458/T-0480) ==")
    print("   cluster by a CONFIRMED shared cause (one 5-whys, SPEC-0056 §2); the failure-class tag is a LENS, not the root")
    if not cluster_rows and not recurring:
        print("  (none)")
    else:
        # rolled-up canonical classes first (aggregate count makes a fragmented root visible)
        for canon in sorted(cluster_rows, key=lambda c: (-cluster_rows[c]["total"], c)):
            cl = cluster_rows[canon]
            rel = next((c["relates_to"] for c in captures
                        if c["fp"] in cl["members"] and c["relates_to"]), "")
            print(f"  {cl['total']}x  {canon}  -> {cl['error']} ({cl['status']}) "
                  f"[clustered: {len(cl['members'])} fingerprints, cites LINK RULE]")
            if rel:
                print(f"        lens: {rel}")
            print(f"        members: {', '.join(sorted(cl['members']))}")
            # a clustered root is owned by its case file (cl['error']/cl['status']); cites-owners
            # of the canonical add to that. A SURFACED cluster has >=1 captured member, so it IS a
            # recurrence of the known root (audit-post F0): a done-owner alias-singleton (total=1) is a
            # REGRESSION, not still-fixed — so recurs=True for any surfaced cluster, decoupling the
            # currency-state from the N>=2 promotion threshold (which only gates visibility / into-work).
            cl_owners = cites_idx.get(canon, [])
            # R-A (SPEC-0061): a surfaced cluster is a recurrence of the known root (fallback True), BUT
            # if a done cites-owner of the canonical fixed it, that recurrence is real only if a
            # member-capture post-dates the fix's closed_at (else ALREADY-FIXED). A case-file-only owner
            # (no done task closed_at) keeps the prior True.
            cl_tss = [ts for m in cl["members"] for ts in fp_tss.get(m, [])]
            # E-0036: resolve a resolved case's done fix-task (cited by case-id, not the canonical fp)
            # as a synthetic done owner so the boundary engages instead of a false REGRESSED.
            cl_err = _with_by_design((cl["error"], cl["status"]), error_by_design)
            cl_r_owners = _resolved_case_fix_owner(cl_err, cl_owners, error_fix_task, boundaries,
                                                   error_root_fix_at)
            cl_recurs = _recurs_after_close(cl_r_owners, cl_tss, boundaries, True)
            cl_unresolvable = (bool(cl_err) and cl_err[1] == "resolved"
                               and not _fix_boundaries(cl_r_owners, boundaries))   # T-11897
            cl_currency, _r = _currency_status(cl_r_owners, cl_err, cl_recurs, None, cl_unresolvable)
            print(f"        currency_status: {cl_currency}    "
                  f"into-work: {'YES' if cl_currency in _INTO_WORK else 'no'}")
            _print_boundary_gate(cl_err, cl_unresolvable)   # T-11897
            # STALE flag (T-0460, D-0086 §PROMOTE): an open/reopened root recurring N>=2 with no owning
            # fix-task is file-or-waive-overdue (the E-0013/14/15 limbo) — surface it explicitly. STALE
            # keys on the N>=2 OVERDUE threshold (cl total >= 2), NOT the broader surfaced-cluster recurs:
            # a total=1 known-root alias-singleton is `linked`, not `overdue`.
            if _stale_open_ownerless(cl["status"], cl["total"] >= 2, cl_owners,
                                     error_fix_task.get(cl["error"])):
                print("        ⚠ STALE file-or-waive-overdue — open N>=2 with no owner/fix-task "
                      "(SPEC-0056 §1: file a fix-task or waive with a reason; do not leave in limbo)")
        # then standalone (un-clustered) recurring fingerprints — prior per-fingerprint disposition
        for fp in sorted(recurring, key=lambda f: (-recurring[f], f)):
            e = _with_by_design(err_idx.get(fp), error_by_design)
            owners = cites_idx.get(fp, [])
            rel = next((c["relates_to"] for c in captures if c["fp"] == fp and c["relates_to"]), "")
            # E-file wins; else a cites-owned fp is already LINKED (a disposition), NOT a promotion
            # candidate (§5 step-5 / LINK RULE — mirrors the A-section suggested-route); only a truly
            # un-owned fp with no case file is a promotion candidate (T-0162).
            if e:
                tail = f"  -> {e[0]} ({e[1]})"
            elif owners:
                tail = "  -> linked (cites-owned, no case file)"
            elif mention_idx.get(fp):
                # T-11898: NOT a bare promotion candidate — an existing artifact names this fingerprint
                # in body text without citing it, so "no case file" is the LINK RULE's blind spot here,
                # not evidence of new work. Still un-owned (the marker links nothing, SPEC-0068); the
                # detail + the remedy print below via `_print_unlinked_mention_flag`.
                tail = (f"  (no case file — UNLINKED MENTION in {len(mention_idx[fp])} artifact(s), "
                        f"see below — NOT a bare promotion candidate)")
            else:
                tail = "  (no case file — promotion candidate)"
            owned = f"  cites-owned-by {', '.join(i for i, _, _ in owners)}" if owners else ""
            print(f"  {recurring[fp]}x  {fp}{tail}{owned}")
            # standalone recurring fp (N>=2 by construction). R-A (SPEC-0061): a done-owner here is
            # REGRESSED only if a capture post-dates its closed_at; else ALREADY-FIXED. No done-owner
            # closed_at → the prior True (still recurring N>=2) stands as the fallback.
            remedy = _resolve_remedy(                                    # T-11675: sweep record wins
                fp, next((c["remedy"] for c in captures if c["fp"] == fp and c.get("remedy")), None),
                remedy_sweeps)
            retest_absent, retest_reason = _resolve_retest(fp, remedy_retests)   # T-11936
            # E-0036: resolve a resolved case's done fix-task (cited by case-id, not the fp) as a
            # synthetic done owner so the boundary engages instead of a false REGRESSED.
            r_owners = _resolved_case_fix_owner(e, owners, error_fix_task, boundaries,
                                                error_root_fix_at)
            # T-11903: the same third boundary carrier as Section A. THIS is the loop the measured
            # entries surfaced in — 32 mention-carrying rows here rendered a bare TRULY-NEW, of which
            # 22 (54 occurrences) were already fixed and 6 (22 occurrences) were POST-CLOSURE
            # recurrences hidden as fresh ideas. Same helper, same gates, same comparator.
            m_owners = _mention_derived_boundary_owners(r_owners, e, mention_idx.get(fp), boundaries)
            mention_derived = bool(m_owners)
            r_owners = r_owners + m_owners
            recurs = _recurs_after_close(r_owners, fp_tss.get(fp, []), boundaries, True)
            unresolvable = bool(e) and e[1] == "resolved" and not _fix_boundaries(r_owners, boundaries)
            currency, _r = _currency_status(r_owners, e, recurs, remedy, unresolvable,
                                            mention_derived, retest_absent)
            print(f"        currency_status: {currency}    "
                  f"into-work: {'YES' if currency in _INTO_WORK else 'no'}")
            _print_remedy_gate(currency, remedy, retest_reason)   # T-0500 / T-11936
            _print_boundary_gate(e, unresolvable)  # T-11897
            # T-10372: the same landed-fix-in-class flag Section A carries (T-10340). This loop resolved
            # owners by EXACT string, so a recurring capture whose CLASS already has a landed fix showed
            # nothing here. Same pure helper, same advisory posture — never a currency/route change.
            _print_landed_fix_flag(currency, fp, cites_idx)
            # T-11898: the same unlinked-mention advisory Section A carries — this loop is the OTHER
            # place a TRULY-NEW renders, and it is the one the measured entries surfaced in.
            # T-11903: fires for a mention-DERIVED verdict too, so the prose the boundary rests on
            # stays on screen once the row is no longer TRULY-NEW.
            _print_unlinked_mention_flag(currency, fp, mention_idx, mention_derived)
            # STALE flag (T-0460): an open/reopened standalone-recurring fp with no owning fix-task is
            # the same file-or-waive-overdue limbo.
            if e and _stale_open_ownerless(e[1], True, owners, error_fix_task.get(e[0])):
                print("        ⚠ STALE file-or-waive-overdue — open N>=2 with no owner/fix-task "
                      "(SPEC-0056 §1: file a fix-task or waive with a reason; do not leave in limbo)")
            if rel:
                print(f"        lens: {rel}")
    print()
    print("  currency_status (SPEC-0056 §5): ALREADY-FIXED | OWNED-IN-FLIGHT | REGRESSED | TRULY-NEW "
          "| ALREADY-BUILT; into-work = TRULY-NEW + REGRESSED only (ALREADY-BUILT = an analog remedy "
          "already exists — confirm it, do NOT file; T-0500)")
    print()

    # ---- Section B2: DISCOVERY stem-clusters — uncited near-synonym families (T-0458) ----
    # A SIBLING of the cited-rollup (Section B): the cited-rollup rolls up fingerprints a case file
    # ALREADY cites (§9 LINK RULE); this surfaces UNCITED families whose spellings fragment a single
    # root so it stays below N>=2 per-spelling. DISCOVERY only — confirm a shared cause (one 5-whys,
    # §6) then cite the members under one E-XXXX; or DISBAND if no cause emerges (false roots are a
    # defect). The verb does NOT mutate cases.
    print(f"== B2. Discovery stem-clusters: {len(discovery)} uncited family(ies) "
          f"(shared root-stem: token-prefix / significant-token overlap / a DECLARED `<root>:` — "
          f"confirm-cause-or-disband, SPEC-0056 §2; NOT the cited-rollup) ==")
    if not discovery:
        print("  (none — no uncited fingerprint family of >=2 near-synonym spellings)")
    else:
        for stem in sorted(discovery, key=lambda s: (-discovery[s]["total"], s)):
            cl = discovery[stem]
            rel = next((c["relates_to"] for c in captures
                        if c["fp"] in cl["members"] and c["relates_to"]), "")
            print(f"  {cl['total']}x  {stem}  [discovery: {len(cl['members'])} uncited spellings, "
                  f"shared root-stem]")
            if rel:
                print(f"        lens: {rel}")
            print(f"        members: {', '.join(cl['members'])}")
            print("        route: confirm a shared cause (one 5-whys, SPEC-0056 §2) → cite the members under "
                  "ONE E-XXXX (SPEC-0055 LINK RULE); else DISBAND")

    # ---- Section C: the 4 routes + §5 checklist + how to route via existing verbs ----
    print("== C. The 4 routes (SPEC-0056 §4) ==")
    print("  event-only · linked · promote-to-fix-task · promote-to-E-XXXX")
    print()
    print("== SPEC-0056 §1 analysis, in order (AI/owner performs — the verb gathers, does not judge) ==")
    print("  1. recurrence/reopen — done at capture (a recurring fp reopens a resolved/waived E-XXXX)")
    print("  2. how-to-fix (ALWAYS) · already-known/fixed? (ALWAYS) · why/root-cause (BY THRESHOLD:")
    print("     reopened / high-blast-radius / unclear / systemic → use `audit pre` external auditor)")
    print("  3. root-clustering — cluster by a CONFIRMED shared cause; disband false buckets (SPEC-0056 §2)")
    print("  4. null != clean — no cause found → classify no-problem vs no-data; no-data → an")
    print("     `audit run --aspect <a> --kind improvement` capture, relates_to: blind-spot (name the gap)")
    print("  5. active-queue + REMEDY-EXISTENCE check — a fix-task/decision already cites the fp → `linked`,")
    print("     never duplicate; AND for a TRULY-NEW candidate sweep code/verb/pattern/spec for an analog")
    print("     REMEDY (T-0500) — if one already exists ⇒ ALREADY-BUILT (confirm it, do NOT file new);")
    print("     record the verdict with `yitc-v2 triage remedy --fp <fp> --remedy <ref> | --absent`")
    print("     (T-11675 — the triage-time carrier; a ref ⇒ ALREADY-BUILT, --absent ⇒ swept-clean")
    print("     genuinely-new. It records against an EXISTING fingerprint and changes NO recurrence count.)")
    print("  6. coverage-both-ways — spec→code dead anchors via `graph build` stderr; code→spec via D-0044 admission")
    print()
    print("== route via EXISTING verbs (this verb does NOT mutate cases — D-0050 ONE command + judgement) ==")
    print("  linked:            add the fingerprint string to a fix-task/decision `cites:` (SPEC-0055 LINK RULE)")
    print("  promote-to-E-XXXX: yitc-v2 error file --kind <k> --fingerprint <fp> ...   (then `error promote`)")
    print("  promote-to-fix:    yitc-v2 error promote E-XXXX --to-task --owner <who> --due <YYYY-MM-DD>")
    print("  event-only:        no action — the capture stands as the record")
    print()
    print("then close the run:  yitc-v2 triage run --complete --routed N --linked N --promoted N")


def cmd_triage_sweep(args: argparse.Namespace, *, DECISIONS_DIR, REPO_ROOT, SPECS_DIR, _append_event, _audit_route_is_escalation, _audit_target_is_terminal, _closed_task_ids, _commit_worktree, _displacement_retention_sweep, _git_mv_tracked, _require_writing_worktree) -> None:
    """Displacement-retention DRAIN (T-0527 / SPEC-0052, extended T-9727) — the backstop half of the
    sweep. git-mv every CLOSED task's audit YAMLs AND every terminal adhoc/gate/consult audit YAML
    still in active decisions/ into the routine/escalation archive (idempotent; in-flight audits NEVER
    moved). The eventual-consistency net behind the at-closure drain in `task close`. `--dry-run`
    previews (mutates nothing); a real run commits the move in a writing worktree. The fired-unacted
    CHECK half is the view: `yitc-v2 graph query displacement-retention`."""
    if getattr(args, "dry_run", False):
        # preview: classify in place, move nothing (a plain rename closure that we DON'T call)
        import yaml
        preview = []
        for tid in _closed_task_ids():
            for src in sorted(DECISIONS_DIR.glob(f"{tid}-audit-*.yaml")):
                try:
                    rec = state.load_str(src.read_text(encoding="utf-8"))
                except (yaml.YAMLError, OSError):
                    rec = None
                lane = "audit-escalation" if _audit_route_is_escalation(rec) else "audit-routine"
                preview.append((str(src.relative_to(REPO_ROOT)), lane))
        # T-9727 — also preview the NON-task-keyed adhoc/gate/consult YAMLs of TERMINAL targets.
        for src in sorted(DECISIONS_DIR.glob("*-audit-*.yaml")):
            try:
                rec = state.load_str(src.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError):
                rec = None
            if not _audit_target_is_terminal(rec):
                continue
            lane = "audit-escalation" if _audit_route_is_escalation(rec) else "audit-routine"
            preview.append((str(src.relative_to(REPO_ROOT)), lane))
        print(f"# triage sweep --dry-run (SPEC-0052) — {len(preview)} audit YAML(s) would be archived")
        for relsrc, lane in preview:
            print(f"  {relsrc}  ->  decisions/archive/{lane}/")
        if not preview:
            print("  (none — every drainable audit YAML is already archived; idempotent no-op)")
        return

    _require_writing_worktree()   # a real move commits — needs an isolated worktree (D-0037/D-0051)
    summary = _displacement_retention_sweep(git_mv=_git_mv_tracked)
    if not summary["moved"]:
        print("triage sweep (SPEC-0052): nothing to archive — every drainable audit YAML is already "
              "in decisions/archive/ (idempotent no-op).")
        return
    # `from:` grounds in the governing rule (SPEC-0052), not the archive PATH (audit-post F2).
    spec_from = next((str(p.relative_to(REPO_ROOT)) for p in SPECS_DIR.glob("SPEC-0052-*.yaml")),
                     "SPEC-0052")
    _, short = _commit_worktree(
        spec_from,
        f"chore(triage): displace {len(summary['moved'])} terminal audit "
        f"YAML(s) to in-git archive (SPEC-0052 backstop)")
    _append_event("audit_yamls_archived", None, {
        "commit": short, "moved": len(summary["moved"]), "trigger": "backstop-sweep",
        "tasks_swept": summary["tasks_swept"], "nontask_swept": summary.get("nontask_swept", 0),
        "routine": summary["routine"], "escalation": summary["escalation"]})
    print(f"triage sweep (SPEC-0052): archived {len(summary['moved'])} audit YAML(s) — "
          f"{summary['tasks_swept']} closed task(s) + {summary.get('nontask_swept', 0)} terminal "
          f"adhoc/gate/consult — {summary['routine']} routine, {summary['escalation']} escalation "
          f"({short}).")
    print(f"  active decisions/*-audit-*.yaml now: {len(list(DECISIONS_DIR.glob('*-audit-*.yaml')))}")


# ── T-10339: the triage-watermark + capture-scan derivation, converged HERE as the single lib home.
# Moved byte-identical from the host bin/yitc-v2 (the _stem_family_key precedent — host re-exports
# `_last_triage_watermark = triage._last_triage_watermark` / `_scan_captures = triage._scan_captures`),
# so bin/lib/task.py#_unrouted_captures now CALLS these instead of re-deriving them inline (the
# T-10300 workaround, unblocked once T-10297 landed — fp triage-watermark-derivation-duplicated-in-task-py).
# Pure but for the one journal read; both read only stdlib.
def _last_triage_watermark(events_path) -> "str | None":
    """The routed-boundary ts of the latest NON-probe `triage_run_completed`, or None (bootstrap →
    sweep from journal start). A `data.probe: true` watermark is a schema-probe, NOT a real routing
    boundary (T-0151), so it is excluded from the window computation (AGENTS §events.jsonl-schema).

    BASIS = `data.window_through`, NOT the completion-event `ts` (T-0542). `window_through` is the max
    ts of the deviation_captured the completing run actually OBSERVED (the window it drained). Keying
    the closed `ts > prior` boundary off it — instead of off `ts` (= the second `triage run --complete`
    ran in) — closes the same-second SILENT-LOSS class: a capture emitted in a LATER second than the
    run's max-observed capture (incl. the same wall-clock second `--complete` ran in, but after it) had
    `ts == completion_ts` ⇒ `> prior` False ⇒ excluded from EVERY future window ⇒ lost forever. With a
    1-second ts and NO per-event tie-break key (journal physical order is not stable after union-merge,
    SPEC-0002), the completion ts cannot distinguish same-second-BEFORE (routed) from same-second-AFTER
    (unrouted); window_through can, because it never advances past a capture the run did not see.
    **Residual (deferred to T-0533):** a capture at the EXACT same second as the run's max-observed
    capture, arriving after the read, is the irreducible 1-second tie — closable only by T-0533's
    per-capture routed-marker, which now inherits THIS safe boundary. **Back-compat:** a pre-T-0542
    watermark (no `window_through`) falls back to the event `ts` — identical to the old behaviour."""
    latest = None
    if not events_path.exists():
        return None
    for line in journal_mod.segment_lines(events_path):  # T-11444: segment-aware fold (SPEC-0190 r4)
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "triage_run_completed":
            continue
        data = e.get("data") or {}
        if data.get("probe") is True:
            continue
        # The routed boundary is window_through (the max capture ts the run drained); fall back to the
        # completion-event ts for pre-T-0542 watermarks that did not record it.
        boundary = data.get("window_through") or e.get("ts")
        # `latest` tracks the most-recent watermark by its COMPLETION ts (chronology of runs), but the
        # value returned is that watermark's BOUNDARY (window_through). A no-op `--complete` (empty
        # window) records window_through == prior, so the boundary never regresses.
        ts = e.get("ts")
        if ts and (latest is None or ts > latest):
            latest = ts
            latest_boundary = boundary
    return latest_boundary if latest is not None else None


# T-12204 (SPEC-0190 rule 10) — the RESULT memo the `graph query` seam's ReadScope installs.
#
# THE SHAPE IT REMOVES, MEASURED ON THIS REPO 2026-09-07: `graph query --type error --recurring`
# composes THREE views — `_capture_fingerprint_counts`, `_capture_cluster_counts` and
# `_discovery_stem_clusters` — and the second and third each call the first internally. Every one of
# them streams the WHOLE logical journal through `_scan_captures` -> `journal.segment_lines`, so ONE
# request folded all 98 segments THREE times: folds 294 / segments 98 = folds_per_segment 3.000,
# against a bound of one physical read per artifact. The live `cli_invoked` maximum for the verb that
# day was 296/98 — the same shape, in production, not a sandbox artefact.
#
# WHY A RESULT MEMO AND NOT THE PARSED-ROWS LANE. `journal_mod.rows_memo` — the memo
# `_debt_echo_lines` / `_advisory_read_scope` / `graph conformance` install — holds the bound here
# too, but `segment_lines` streams precisely so a 325 MB journal is never materialised, and inside
# this scope nothing else has materialised it: measured on the real corpus (98 segments / 644k rows)
# it took peak RSS 153 MB -> 657 MB for wall 16.7s -> 14.6s. This memo holds the same bound at
# 152 MB (flat) and 16.7s -> 10.9s, so it wins on both axes it does not tie on. That is the
# `followup.fold_memo` shape rule 10 already sanctions for a fold defined over RAW LINES which
# cannot consume the parsed-rows lane (T-12031) — which is exactly what `_scan_captures` is. The
# deliberate NON-installation of `rows_memo` here follows the measured-omission precedent T-12144 set
# at the sibling `journal query` seam: a ReadScope is only free where the reader was going to read
# the whole declared journal anyway.
#
# IT IS ONE SCOPE, NOT A PER-VIEW CACHE (rule 10's named retirement (a)): the obligation lands on the
# PRIMITIVE, so every view built on captures serves from the one scope the wiring site declares.
#
# SCOPE DISCIPLINE, taken verbatim from `followup.fold_memo`: the prior value is SAVED and RESTORED.
# A nested scope SHADOWS the outer one — the inner body folds once on its own, the outer memo is
# neither read nor written while it is installed, and on exit it is restored EXACTLY as it was.
# Shadowing is deliberate rather than a limitation: an inner scope that inherited outer entries would
# serve a caller rows folded under a different request. An exception raised inside the body can never
# leave a stale snapshot installed for a later, unrelated verb. OUTSIDE a scope `_scan_captures` is a
# plain pass-through, so every one of its 15 call sites is byte-identical.
_CAPTURE_SCAN_MEMO = None


@contextlib.contextmanager
def capture_scan_memo():
    """Serve `_scan_captures` from ONE physical fold per journal path for the duration of the scope."""
    global _CAPTURE_SCAN_MEMO
    prior = _CAPTURE_SCAN_MEMO
    _CAPTURE_SCAN_MEMO = {}
    try:
        yield
    finally:
        _CAPTURE_SCAN_MEMO = prior


def _capture_scan_key(events_path):
    """The entry key: the RESOLVED path, the `JournalRowsMemo._key` shape. Falls back to the raw
    string on OSError, so an unresolvable path still keys deterministically instead of raising."""
    try:
        return str(Path(events_path).resolve())
    except OSError:
        return str(events_path)


def _scan_captures(events_path) -> list:
    """Read every nonconformity capture from events.jsonl — BOTH the current `deviation_captured`
    (D-0086 rename) AND the legacy read-only `friction_captured` (append-only, P5-safe: the rename
    never resets recurrence). Returns normalized rows
    {ts,type,fp,relates_to,via,kind,impact,finding,task_id,remedy}.
    Single scan reused by the recurring counter, the routing window, and the cluster set.

    MEMO-SERVED inside a `capture_scan_memo()` scope, a plain physical fold outside one (T-12204).
    Pass-through by default, so no caller outside a scope moves. A memo HIT performs no physical read
    and therefore records none — the same reason `segment_lines` skips `note_fold` on its
    scope-served branch (T-12035) and `state.load_path` counts misses, not hits. Counting a hit would
    report amplification exactly where the collapse succeeded.

    THE MEMO IS AN EARLY RETURN IN THIS FUNCTION, deliberately NOT the front-door/`_uncached` SPLIT
    that `followup._fold` uses. The T-11442 journal-consumer census records a reader by its
    (file, FUNCTION NAME, kind) triple, so extracting the fold into `_scan_captures_uncached` MOVES
    the recorded site: the census then reports 1 recorded-but-not-enumerated + 1 live-but-unrecorded,
    its reconciler pairs neither (`moved=0`), and regenerating needs `--allow-shrink` — a flag that
    asserts the population SHRANK, which would be untrue here. Keeping ONE function name keeps the
    census site identical and the artifact untouched, which is also the smaller change (CHARTER §P1
    F3). `followup._fold` can afford the split because its physical read lives in a helper the census
    already records under its own name."""
    memo = _CAPTURE_SCAN_MEMO
    key = None
    if memo is not None:
        key = _capture_scan_key(events_path)
        if key in memo:
            return memo[key]
    out: list = []
    if not events_path.exists():
        if memo is not None:
            memo[key] = out
        return out
    for line in journal_mod.segment_lines(events_path):  # T-11444: segment-aware fold (SPEC-0190 r4)
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") not in ("deviation_captured", "friction_captured"):
            continue
        d = e.get("data") or {}
        if d.get("probe") is True:
            # schema-probe capture (a `deviation_captured` emitted only to demonstrate the event
            # shape, the way T-0151 emitted a probe WATERMARK) — NOT real data. Excluded here so it
            # never pollutes the routing window OR the cluster counts, symmetric with the watermark
            # probe-exclusion in `_last_triage_watermark` (audit-post T-0152 F1).
            continue
        out.append({"ts": e.get("ts") or "", "type": e.get("type"), "fp": d.get("fingerprint"),
                    "relates_to": d.get("relates_to") or "", "via": d.get("captured_via") or "",
                    "kind": d.get("kind"), "impact": d.get("impact") or "",   # T-10339: impact folded so
                    "finding": d.get("finding") or "", "task_id": e.get("task_id"),  # a row-text fold reads it
                    "actor": d.get("actor"),   # T-10410: WHO captured it (stamped at emit) — the row-text
                                               # fold surfaces it; a pre-T-10410 capture simply has None
                    # T-11158 (SPEC-0178 rule 5): the HAND-SUPPLIED end of the audit-post case
                    # attribution — the belt for a capture with no task id or one pointing elsewhere.
                    # The DERIVED case is computed from the closure record instead (the canonical path,
                    # `task.py#_case_attribution`); this field is only what the capture itself claimed.
                    # Additive normalized field, the `actor` precedent: a capture that carries none
                    # simply has None, which is the ordinary case.
                    "exempted_case": d.get("exempted_case"),
                    # T-11890: the NORMALIZED capture content, folded off the RAW payload by the ONE
                    # reader-owned accessor (`journal.capture_content`). Without it the alias keys the
                    # measurement found — what / note / why_it_matters / why / where / summary / detail
                    # / evidence / fix on 276 of the 431 rows carrying no usable `impact` — do not
                    # survive this scan, and every downstream reader is blind whatever field it asks
                    # for, because this is the single capture-scan home. ADDITIVE: `impact` and
                    # `finding` below are untouched, so no existing consumer moves.
                    "content": journal_mod.capture_content(d),
                    "remedy": d.get("remedy_ref")})   # T-0500: the remedy-existence sweep verdict (D-0086 §5)
    if memo is not None:
        memo[key] = out
    return out


def _remedy_sweep_index(events_path) -> dict:
    """`(refs, retests)` folded from the TRIAGE-TIME remedy sweep rows (`remedy_swept`,
    T-11675 / X-1131). The SECOND read input to the SPEC-0063 §1 remedy-existence 3-state, beside
    the capture-time `data.remedy_ref` that `_scan_captures` normalizes.

    WHY A SECOND INPUT AT ALL. The capture-time field is writable ONLY at capture time — the fold
    above reads it off `deviation_captured` / `friction_captured` rows — but the sweep it records is
    by nature a TRIAGE-time act over an ACCUMULATED BACKLOG, so the sanctioned field was unwritable
    at exactly the moment the rule demanded it. Measured: zero `remedy_ref` rows existed in the
    kernel's OR aiseller's entire journal history since T-0500 shipped the classifier and the gate —
    the write side had never once been used, in either repo.

    WHY A DISTINCT EVENT TYPE, and this is the load-bearing part. The only retroactive route the old
    shape left was emitting a SECOND capture carrying the same fingerprint — which bumps
    `counts[fp]` to 2 and flips `recurs` True, converting genuinely-new singletons into FABRICATED
    recurring promote-candidates. So the sanctioned field could not be filled without falsifying the
    recurrence signal. `remedy_swept` is NOT a capture event, so `_scan_captures` never sees it and
    `_capture_fingerprint_counts` never counts it: the recurrence inputs are untouched BY
    CONSTRUCTION, not by care (tests/test_triage.py asserts it differentially).

    LATEST WINS — a later sweep CORRECTS an earlier verdict (rows are folded in ts order, so the
    last recorded verdict for a fingerprint is the live one). Rows carrying no fingerprint or no
    `remedy_ref` are ignored: they record nothing readable.

    CONSUMER-SHAPE COMPATIBLE (AC3): this reads exactly the shape aiseller's 252 backlogged verdicts
    were already written in (`data.{fingerprint,verdict,remedy_ref,...}`, every row carrying a
    non-empty `remedy_ref` — `absent` on the REMEDY-ABSENT ones), so that history is consumable
    without re-emitting any of it.

    T-11936 — THE SECOND RETURNED MAP, `{fp: {"retested": .., "reason": ..}}`, carries the RE-TEST
    PROVENANCE: whether the recorder re-ran the ORIGINAL FAILING INPUT, or named why they could not.
    Folded in the SAME pass over the SAME rows, latest-wins in lockstep with `refs`, so no second
    journal pass is added and the two can never disagree about which row is live. A row whose own
    recorded `verdict` is REMEDY-UNSWEPT (the `--no-retest` shape) contributes NO ref — it records
    that an artifact was FOUND without clearing the candidate.

    HISTORY IS NOT REWRITTEN. The neutralization keys on the row's OWN recorded `verdict`, so every
    pre-T-11936 row (verdict ALREADY-BUILT, no `retested` — including aiseller's 252 backlogged
    verdicts) keeps reading exactly as it does today; the R-D AC3 consumer-shape promise is intact.
    What makes those legacy verdicts legible is the READ-side mark `_currency_status(retest_absent=)`,
    which annotates rather than reclassifies."""
    idx: dict = {}
    retests: dict = {}
    if not events_path.exists():
        return idx, retests
    for line in journal_mod.segment_lines(events_path):  # segment-aware fold (SPEC-0190 rule 4)
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "remedy_swept":
            continue
        d = e.get("data") or {}
        fp, ref = d.get("fingerprint"), d.get("remedy_ref")
        if not (fp and ref is not None and str(ref).strip()):
            continue
        fp = str(fp)
        # T-11936 — the RE-TEST provenance, folded in the SAME pass over the SAME rows, so the two
        # maps can never disagree about which row is live.
        retests[fp] = {"retested": (str(d["retested"]).strip() or None) if d.get("retested") else None,
                       "reason": (str(d["retest_absent_reason"]).strip() or None)
                                 if d.get("retest_absent_reason") else None}
        if str(d.get("verdict") or "").strip().upper() == "REMEDY-UNSWEPT":
            # An un-re-tested sweep contributes NO ref: it never clears the fingerprint. A later
            # REMEDY-UNSWEPT row therefore also WITHDRAWS an earlier clearance (latest-row-wins is
            # honoured in both directions — otherwise a correction could not correct).
            idx.pop(fp, None)
            continue
        idx[fp] = str(ref)               # later row wins — a re-sweep corrects an earlier verdict
    return idx, retests


def _error_root_fix_landed_at(events_path, case_ids) -> dict:
    """{E-id: ts} — the DATABLE instant a `root_fix_landed` case file's root fix was attested landed,
    folded from the journal's own `error_resolved` rows (T-11897, SPEC-0061 R-A second shape).

    WHY THE JOURNAL AND NOT THE CASE FILE, which is the load-bearing choice here. A case resolved by
    `error resolve --root-fix` records `resolution.root_fix` as PROSE — a sentence naming the carrier —
    and the YAML carries NO date field for it anywhere. So there is no on-disk datable boundary to
    read; the `error_resolved` transition row IS the record of when the landing was attested, and its
    own `ts` is that instant. Same reasoning, and the same carrier choice, as
    `bin/lib/task.py#_case_closure_index` ("the closure instant is the event's own ts").

    HONEST BOUND ON WHAT THIS TIMESTAMP MEANS. It is an UPPER bound on the landing: the case is
    attested resolved at or after the fix actually lands, so a capture falling in the gap between the
    true landing and the attestation reads as pre-fix. That is the SAME direction R-A already takes for
    a task boundary ("captures at or before the boundary are the same incident, caught while the fix
    was being built"), so this shape is not treated more permissively than the shape it joins — but the
    gap is real and is named here rather than left for a reader to discover.

    RESTRICTED to `case_ids` — the caller passes EXACTLY the resolved cases carrying
    `resolution.kind: root_fix_landed`. A case resolved through the fix_task shape has a real
    `closed_at` boundary and must keep using it, so its `error_resolved` row is deliberately not read
    here. LATEST ROW WINS (a re-resolve after a reopen corrects an earlier attestation). Segment-aware
    (SPEC-0190 rule 4) — the same fold idiom as `_remedy_sweep_index`; no new store, no new index."""
    idx: dict = {}
    if not case_ids or not events_path.exists():
        return idx
    wanted = set(case_ids)
    for line in journal_mod.segment_lines(events_path):  # segment-aware fold (SPEC-0190 rule 4)
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "error_resolved":
            continue
        eid, ts = e.get("task_id"), e.get("ts")
        if eid in wanted and ts:
            idx[str(eid)] = str(ts)     # later row wins — a re-resolve corrects an earlier attestation
    return idx


def _resolve_remedy(fp: str, capture_time, sweeps: dict):
    """The SINGLE resolution of the SPEC-0063 §1 remedy value for a fingerprint, read by BOTH
    `triage run` sections (T-11675). A recorded TRIAGE-TIME verdict (`triage remedy`) WINS over the
    capture-time `remedy_ref`: it is the deliberate later act, made with the backlog in view. Absent
    one, the capture-time field stands — so every pre-T-11675 behaviour is preserved exactly."""
    return sweeps.get(fp) or capture_time


def _resolve_retest(fp: str, retests: dict) -> "tuple[bool, str | None]":
    """`(retest_absent, reason)` for a fingerprint's live remedy verdict (T-11936) — read from the
    SAME latest-wins map `_remedy_sweep_index` folds alongside the refs.

    `retest_absent` is True when the live verdict rests on an ARTIFACT ALONE: no re-run of the
    original failing input was recorded. That is the state BOTH 2026-08 incidents were made of, and
    it is the DEFAULT for everything written before this rule existed — a capture-time `remedy_ref`
    (no sweep row at all) and every legacy `remedy_swept` row alike. Saying so is the honest reading;
    inferring a re-test nobody recorded is not.

    `reason` is the recorder's own account of why the input could not be re-run (`--no-retest`), when
    they gave one — surfaced verbatim so the reader gets the account rather than a bare flag."""
    rec = (retests or {}).get(fp)
    if not rec:
        return True, None                       # no sweep row: nothing was re-tested, by construction
    return (not rec.get("retested")), rec.get("reason")
