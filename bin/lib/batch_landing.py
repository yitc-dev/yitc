"""batch_landing — the SPEC-0184 LAND-VERIFICATION BATCHING mechanism, extracted byte-identical
from `bin/lib/worktree.py` (T-11524, plan `split-worktree-py-along-its-own-spec-seams-runner-`).

WHAT IS IN HERE, AND WHY THE BOUNDARY IS THE ONE IT IS. The move-set is the TRANSITIVE-EXCLUSIVE
closure rooted at this subject's OWN entry points — batch formation and the queue, the reservation and
addressed-yield offer, the four pre-queue refusals, merge-and-evict, the one-verify / atomic-ff /
per-member-verdict set, red-batch dissolution and its isolation oracle, the rule-4 candidate-head
restoration and the rule-8 superseded-member extinguish — where a helper moves iff EVERY top-level
caller of it is already in the move-set. Rooting at the subject rather than at a borrowed
discriminator is the expensive lesson of the runner cut (`lessons/library-extraction.md` §"Root the
closure at the SUBJECT's own entry point"); requiring exclusivity is what leaves the helpers the land
path SHARES — `_git_rev`, `_merge_tree_conflict_stages`, `_land_commits_not_in_base`, the SPEC-0132
admission pair and the consumer verify-LAYER prep tree — in the host BY CONSTRUCTION, rather than by an
exclusion list someone has to remember to write.

NOT IN HERE, AND THIS IS THE SEAM DECISION RATHER THAN AN OMISSION: `cmd_land` and `_land_integrate`,
though SPEC-0184 anchors both. They are the land verb and its integrator — the CALLERS of this
mechanism, not the mechanism. Rooting at them was MEASURED rather than assumed: it takes the closure
from 86 defs to 225 and drags evidence custody (SPEC-0168) along with it, which is attempt-1 of the
T-11519 failure. SPEC-0184 therefore implements across two files after this cut, which is the honest
record — its seam lives at the land verb, its mechanism lives here. Also not here: evidence custody
(SPEC-0168), the verify runner (`bin/lib/verify_runner.py`), the SPEC-0077 pinned verify and its
rebaseline arm (`bin/lib/rebaseline_currency.py`) and the worktree lifecycle
(`bin/lib/worktree_lifecycle.py`).

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 / T-11523 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM from
the original source — never `ast.unparse`, which reformats and loses byte-identity — and every
non-stdlib free name (host stayers, host globals, AND moved siblings via their host residue) arrives as
a keyword-only injected parameter, computed with `symtable` over each function's scope SUBTREE. The
host keeps a `functools.wraps` residue under every historical name, so the tests and the eight
`bin/lib` modules that reach these symbols through `worktree.<sym>` keep resolving and stay out of this
diff — and `inspect.getsource(worktree.<sym>)` unwraps to the REAL body here.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib; it NEVER
back-imports the host.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from lib import graph as graph_mod   # T-11395: the ONE event-catalog predicate the pre-queue
                                     # uncatalogued-type refusal reuses
from lib import host_apply as _host_apply  # T-11280: the ONE home of CONSUMER_OPS_CONTRACT
from lib import journal as journal_mod     # the shared bounded tail-scan journal reader
from lib import lockfile                   # the ONE flock-target open (the reservation seam)
from lib import state
from lib import task as task_mod           # SPEC-0166: the pure premise predicate (single home)
from lib import verify_runner            # T-11204: `_ROOT_TEST_SWEEP_DIR` — the ONE home of the
                                        # root-layout sweep literal (CHARTER §P5), never re-spelled here


# ---------------------------------------------------------------------------
# Constants moved WITH their readers: each is referenced from a moved signature DEFAULT, which is
# evaluated at def time in THIS module, so it cannot arrive by injection. The host keeps a re-export
# alias under each historical name, so `worktree._LAND_BATCH_MAX` and its three siblings still resolve
# for the tests and for `bin/lib/debt.py`.
# ---------------------------------------------------------------------------
_LAND_RESERVATION_POLL_SEC = 0.1
_LAND_DISPOSITION_ADMITTED = "admitted"
_LAND_DISPOSITION_UNACCOUNTED = "unaccounted"
_LAND_MEMBER_VERDICTS = (
    "landed",                    # the member's change reached main in this land
    "evicted-for-conflict",      # rule 3 — merge conflicted with an already-merged peer, pre-verify
    "requeued-after-red-batch",  # rule 4 — the batch was red; NO member landed, this one re-queues
    "dropped-dead-member",       # rule 6 — the member's claim stopped being held; the batch went on
    _LAND_DISPOSITION_UNACCOUNTED,   # T-11322 — declared, then left silent; NOT an outcome
)
_LAND_BATCH_MAX = 4
_LAND_QUEUE_FRESHNESS_SEC = 90
_LAND_QUEUE_TERMINAL_TYPES = ("land_completed", "land_member_verdict")
_LAND_QUEUE_TAIL_BYTES = 512 * 1024

# T-11609 (SPEC-0184 rule 1, the realization exit) — the tail this module reads to answer WHAT A PASS
# COSTS. It is a bound on SPEND and it is MEASURED, never decreed: folded against this repo's own
# journal (77MB live, 2026-08-29), 8MB reaches 67 `land_completed` rows carrying a positive
# `verify_duration_ms` while 512KB — the queue readers' tail — reaches FOUR. A median over four rows
# is not a median anyone should act on, which is why this reader gets its own bound rather than
# borrowing the queue's; and 8MB parses in ~0.05s against a land whose verify runs minutes, so the
# larger read costs nothing that matters here.
#
# THE SAMPLE SIZE IS REPORTED WITH THE ANSWER, which is what keeps this constant honest. A window is
# a judgement about recency and every choice of one is arguable; what must not be arguable is how
# much evidence the reported figure rests on, so the row carries `n` beside the median and a reader
# who distrusts the window can re-fold the journal themselves.
_LAND_VERIFY_WALL_TAIL_BYTES = 8 * 1024 * 1024
_LAND_PHANTOM_LANDED_REASON = "landed-member-still-parked"
_LAND_PHANTOM_UNDATABLE_REASON = "landed-member-wait-undatable"
_LAND_NOT_LIVE_EXCLUSION_REASONS = (
    "stale-wait-row",              # the newest wait row is outside the window: history, not now
    "clock-skewed-wait-row",       # a wait row from the future: not evidence of now either
    "undatable-wait-row",          # a wait row whose ts cannot be read: cannot be proven current
    "liveness-unreadable",         # the terminal fold failed: nobody can be proven still waiting
    "stopped-waiting",             # a terminal row newer than the wait: that land already ended
    "terminal-row-undatable",      # its terminal row cannot be dated: fail closed, not queued
    _LAND_PHANTOM_LANDED_REASON,   # landed, then left parked on its own stale heartbeat
    _LAND_PHANTOM_UNDATABLE_REASON,  # landed, and its wait cannot be dated as a NEW one
)
_LAND_REBASELINING_EXCLUSION_REASON = "rebaselining-pinned-assertion"
# T-11939 (SPEC-0184 rule 4) — the declare->exclude->solo chain's SECOND explicit ground, carrying the
# name the external auditor gave it on 2026-08-28. Its OWN reason, never the rebaseline one above: a
# branch excluded here supersedes no pinned assertion and has nothing to waive, so reporting it under
# `rebaselining-pinned-assertion` would make the journal state something false about it.
_LAND_MERGE_INVALID_EXCLUSION_REASON = "acceptance-assertion-merge-invalid"
_LAND_PINNED_SUPERSESSION_EXCLUSION_REASON = "pinned-supersession-on-latest-commit"
_LAND_PROBE_MERGEABLE = ("clean", "land-resolvable")
_LAND_MEMBER_CLAIM_PID_KEY = "claim_pid"
_LAND_BATCH_DECLARED_KEY = "declared"
_LAND_BATCH_VERDICTED_KEY = "verdicted"
_LAND_BATCH_REMOVED_KEY = "removed"
_LAND_MEMBER_CANDIDATE_MERGE_FAILED = "candidate-merge-failed"
_LAND_MEMBER_ALREADY_ON_CANDIDATE = "already-on-candidate"
_LAND_MEMBER_HEAD_UNRESOLVABLE = "head-unresolvable"
_LAND_MEMBER_ALREADY_ON_MAIN = "already-on-main"
_LAND_MEMBER_NOT_IN_FF = "not-in-landed-history"
_LAND_RESTORE_NOT_NEEDED = "not-needed"
_LAND_RESTORE_DONE = "restored"
_LAND_RESTORE_FAILED = "failed"
_LAND_ROLLBACK_SKIPPED = "skipped"
_LAND_FOREIGN_MERGE_RE = re.compile(r"^Merge branch '([^']+)'(?: into (\S+))?\s*$")
_LAND_PINNED_ENTRY_PREFIX = "[pinned/last-green] "
_LAND_PINNED_ATTRIBUTION_REASON = "pinned-entry-attribution"
_LAND_LAUNCH_FAILURE_MARKER = "could not launch:"
_LAND_TEST_FAILED_PREFIX = "test failed: "
# T-11204 (SPEC-0185 §1(a)) — this constant is now the fail-closed DEFAULT, not the answer. The
# candidate sweep resolves its directories from the consumer's DECLARATION via
# `_declared_test_sweep_dirs` (host-side), and the same resolved names are threaded in as
# `test_subdir` to the two oracles below, so the pair stays in step BY SHARED VALUE rather than by
# two matching literals. ONE definition of the root literal itself, in `verify_runner`.
_LAND_CANDIDATE_TEST_SUBDIR = verify_runner._ROOT_TEST_SWEEP_DIR
_LAND_ATTRIBUTION_OUTCOMES = ("main", "branch", "mixed", "undecidable")

# T-11807 — THE ATTRIBUTION QUARANTINE. A failing assertion may declare, AT ITS OWN SITE, that it is
# quarantined FROM ATTRIBUTION: the land still ABORTS on it exactly as before, but the assertion stops
# producing an `ATTRIBUTION: THIS BRANCH` verdict against whichever branch happened to be landing.
#
# WHY IT EXISTS, MEASURED. Over 2026-08-27..28 one racy assertion in
# `tests/test_dispatch_stop_defer.py` refused SIX distinct branches with that verdict, each paying a
# full verify to rediscover a red that was not its own; `task/T-11732` proved the verdict false by
# landing UNCHANGED 46 minutes after its own refusal. A known-racy assertion should keep guarding its
# safety property and keep failing the land — what it should not do is name an innocent branch. This
# is the narrower of the two remedies (the race's own fix is the other half of T-11807); it is not a
# repair of the merge-base attribution probe in general.
#
# THE DECLARATION LIVES WITH THE ASSERTION, NOT IN THIS FILE. `bin/` is the KERNEL realm (SPEC-0073
# rule 1) — it travels to every consumer as a pin — so a hard-coded list of one repo's flaky test
# names here would ship a v2-self datum inside the kernel export slice. Instead this module carries
# only the identity-agnostic GRAMMAR, and every declaration is written in the quarantined assertion's
# own message, in the repo that owns that test. A consumer's engine copy therefore names no test of
# anyone else's, and the removal condition sits where the reader of the failure already looks.
#
# A DECLARATION MUST NAME ITS OWN EXIT. `[attribution-quarantine: <removal condition>]` with an EMPTY
# condition does NOT quarantine — an exemption with no named exit is how a stopgap becomes permanent,
# so the exit is a CONDITION of the quarantine rather than a decoration on it.
_LAND_ATTRIBUTION_QUARANTINE_RE = re.compile(r"\[attribution-quarantine:(?P<until>[^\]]*)\]")


def _land_attribution_quarantine_reason(pair) -> "str | None":
    """The removal condition a failing `(file, assertion)` pair DECLARES for itself, or None.

    Pure and total: it reads the pair text and nothing else, never raises, and answers only the
    NECESSARY half of the question. Whether a declaration is ADMITTED is decided separately, against
    the merge-base — see `_land_failure_attribution_probe`, which is the only caller that can answer
    it. Splitting the two is the point: this half is a grammar, the other half is a trust boundary,
    and collapsing them would make a branch's own text sufficient to clear its own blame."""
    m = _LAND_ATTRIBUTION_QUARANTINE_RE.search(str(pair or ""))
    if not m:
        return None
    return (m.group("until") or "").strip() or None
_LAND_RED_DECLINE_OUTCOMES = (
    "interaction",              # no member reproduces alone — the red belongs to the MERGED tree
    "partially-explained",      # the union of what members reproduced is SHORT of the failing set
    "undecidable",              # a fail-closed gate — INCLUDING "not applicable" and "never probed"
    "culprits-not-actionable",  # the probe named culprits; the land fork's own conditions refused
)
# T-11710 — the decline outcomes under which NO MEMBER was named the owner of the red. Read by
# `_land_batch_ineligible_branches`, a SUBSET of `_LAND_RED_DECLINE_OUTCOMES` above and never a
# second vocabulary: `interaction` PROVES no member reproduces alone, and `undecidable` is the
# fail-closed gate that named nobody at all (the measured `pinned-entry` case — 8 of 10 decline rows
# on 2026-08-27). The two EXCLUDED outcomes name an owner, or part of one, and are excluded for that
# reason alone: `culprits-not-actionable` names the members the oracle PROVED reproduce alone (the
# land merely may not act on them), and `partially-explained` accounts for SOME of the failing set,
# so a member does own that part. Where an owner is named the red IS somebody's and today's clearing
# is correct — this constant exists so that boundary is stated once, as a set, rather than inferred
# from a reason string at the read site.
_LAND_RED_UNOWNED_DECLINE_OUTCOMES = ("interaction", "undecidable")
_LAND_PEER_RELEASE_REASON = "head-is-culprit"
_LAND_BATCH_INELIGIBLE_TAIL_BYTES = 512 * 1024
# T-11816 — THE BASE SPAN, no longer the whole window. It keeps its value so the quiet-journal case
# costs exactly what it costs today; what changed is that it is now the first PROBE of a read sized by
# the answer's own lifetime, not the bound the answer is silently truncated to.
#
# `_LAND_INELIGIBILITY_HORIZON_SEC` — the DECLARED lifetime of a rule-4/9/12 ineligibility mark, and it
# is MEASURED rather than decreed. Folding this repo's live journal for every `requeued-after-red-batch`
# mark and the marking branch's own next `land_completed` (n=142 marks, 121 resolved, 2026-08-28) gives
# the gap the window has to outlive: p50 30.4 min, p90 195 min, p95 381 min, p99 47.4 h, MAX 49.5 h. 72
# hours covers the measured maximum with margin. It is deliberately UNDER the 7-day live window
# (`JOURNAL_LIVE_WINDOW_DAYS`), which is what keeps this read on the live-segment branch SPEC-0190 rule
# 4 prescribes for a sub-live-window horizon — and the coverage check is that rule's other half, the
# "honour it", finally being performed rather than assumed.
#
# THERE IS NO LONGER A BYTE CEILING ON THIS READ (T-11904), and the removal is the point rather than a
# relaxation. `_LAND_HORIZON_SCAN_CEILING_BYTES = 48MB` was a bound on SPEND that could not bound a
# window declared in TIME: the two are joined only by the write rate, so its coverage of a fixed 72h
# fell on its own as the journal wrote faster. Measured 2026-08-30 — 48MB reached 64.8h, and EVERY
# land watched that day printed the shortfall, so the truncation had become the normal case rather
# than the exception it was introduced as. Raising it would have bought a bigger scan for the same
# answer and re-set the same clock. What made removing it safe is that the read got CHEAPER, not that
# its budget got bigger: `journal.tail_scan_events_covering` now walks backwards in slices and keeps
# only matching rows, so it is bounded by the DECLARED HORIZON in bytes read and by ONE SLICE in
# memory (measured on the same journal: 52.4MB read, 28MB resident, 0.22s — against 120-131MB
# resident for the single 53MB read it replaces).
_LAND_INELIGIBILITY_HORIZON_SEC = 72 * 3600

# `_LAND_PINNED_SUPERSESSION_HORIZON_SEC` (T-11870) — the DECLARED lifetime of a pinned-supersession
# flag, and therefore the window `_land_pinned_supersession_branches` reads over. The two are ONE
# number on purpose: a reader whose declared lifetime and whose read span differ is a reader that
# drops answers silently, which is exactly the defect this constant closes.
#
# THE CLEARING RULE, in full, because this constant is one third of it. A flag is ARMED by a keyed
# `commit_landed` ship row (a commit whose own diff REMOVES an assertion line from the pinned
# surface). It is DISCHARGED by any of THREE events: a later SHIP row that fired no notice; an
# evidence-bound `--rebaseline` declaration naming the assertion (carried OUTSIDE that reader, by the
# precedence subtraction in `_land_batch_members` against `_land_rebaselining_branches`); or EXPIRY,
# this many seconds after the arming row. The third is new. Until T-11870 the rule declared no expiry
# at all — "deliberately still NO freshness window" — while the reader implemented a 512KB byte tail
# covering roughly 36 minutes of a busy journal, so the real lifetime was a write-rate artefact that
# nothing declared and nothing reported.
#
# WHY A BOUNDED LIFETIME IS SOUND, rather than merely convenient. An unbounded lifetime cannot be
# served by a LIVE-SEGMENT read at all: an arming row that rotation moved into an archive segment is
# outside what this read can see, whatever window it declares. T-11904 made that case LOUD rather
# than silent — reaching offset 0 now counts as coverage only when no older segment sits beside the
# journal, so a live segment younger than the declared horizon is REPORTED as the SPEC-0190 rule-4
# archive-branch condition it is. Loudness is not reach, though: the read still cannot ANSWER for
# that history, it can only refuse to pretend it did. Declaring a finite lifetime is the other half
# of the pair — it makes the rule say what the carrier can actually deliver. It can only cost, never mislead: this reader's fail direction is
# fail-OPEN and shared with all three of its siblings — a missed exclusion costs ONE repeated batch,
# a spurious one shrinks batches on bad data — so an expiry can never admit a wrong exclusion. And
# rule 4's red-batch fallback stands unchanged behind it: a branch that really does supersede a
# pinned assertion still reddens its batch, still takes the one-round mark and is still verified
# alone. This reader SAVES that pass; it is not what makes the outcome safe.
#
# THE VALUE IS DECLARED-BY-CARRIER, NOT MEASURED, and a later reader must not treat it as derived.
# The notice has fired ONCE in its recorded life, so there is no arm->discharge distribution to
# measure and reporting one would be a fabricated measurement. What fixes the value instead is the
# CARRIER: this is a live-segment read, and the live window is the longest span such a read can serve
# without the segment-aware archive fold SPEC-0190 rule 4 prescribes for a genuinely archive-spanning
# horizon. Equality with `JOURNAL_LIVE_WINDOW_DAYS` is deliberate and is NOT the trap
# `debt.py#uncarried_p8_warns` documents: there the equal-length window lost its oldest rows
# SILENTLY, which is what forced that reader onto the archive fold. Here a window that cannot reach
# the horizon is REPORTED by `_land_horizon_rows`, and rows past the horizon are discharged BY RULE
# rather than by running out of bytes — so the loss is loud in one direction and defined in the other.
_LAND_PINNED_SUPERSESSION_HORIZON_SEC = 7 * 24 * 3600

# `_LAND_RIDES_WITHOUT_LANDING_SOLO_THRESHOLD` (SPEC-0184 rule 13, T-11817) — how many multi-member
# batch formations a branch may ride, since its last completed verify, before its next attempt is
# verified ALONE.
#
# THE VALUE IS AUTHOR-DECLARED AND REVISABLE, NEVER MEASURED, and a later reader must not treat it as
# derived. The readings it was chosen AGAINST, recorded here so the choice can be re-argued rather
# than rediscovered: `task/T-11803` rode four batches, `task/T-11790` rode six, and the external
# consult (`decisions/land-conveyor-blindspots-audit-adhoc.yaml`, finding 3) proposed one or two
# passenger turn-backs. Three sits between the consult's proposal and the worst observed passenger.
# It is a code constant for the same reason `BATCH_MAX` is (SPEC-0184 §Parameters): ordinary tuning
# that belongs beside the code enforcing it, with a citation back to the spec.
_LAND_RIDES_WITHOUT_LANDING_SOLO_THRESHOLD = 3
_LAND_VERIFY_RAN_ABORT_CLASSES = frozenset({"verify-failed", "verify-timeout"})
_LAND_YIELD_OFFER_NAME = "yield-offer"
_LAND_SUPERSESSION_MARK_EXCLUSION_REASON = "supersession-mark-set"
_LAND_COST_CLASS_EXCLUSION_REASON = "cost-class-not-batch-class"
_LAND_COST_CLASS_UNDECIDABLE_EXCLUSION_REASON = "cost-class-undecidable-candidate"
_LAND_COST_CLASS_UNDECIDABLE_HEAD_EXCLUSION_REASON = "cost-class-undecidable-head"
_LAND_INCOMPATIBLE_EXCLUSION_REASON = "incompatible-with-selected"
_LAND_CORPUS_VIOLATION_EXCLUSION_REASON = "corpus-integrity-violation"
_LAND_HEAD_CORPUS_VIOLATION_REASON = "head-corpus-violation"
_LAND_HEAD_SOLO_EXCLUSION_REASON = "head-batch-ineligible-solo"
_LAND_REQUEUED_INELIGIBLE_EXCLUSION_REASON = "requeued-after-red-batch"
_LAND_OVER_BATCH_CAP_EXCLUSION_REASON = "over-batch-cap"
_LAND_DIRTY_WORKTREE_EXCLUSION_REASON = "uncommitted-worktree-dirt"
_LAND_MEMBER_DIRTY_PATHS_KEY = "dirty_paths"
# T-11804 (SPEC-0184 rule 12) — the ninth reason: this member was dropped so the batch would not be
# the EXACT set that already reddened. It is its own string for the reason every sibling is — a drop
# folded under a neighbouring reason sends its operator looking for a conflict, a cost class or a
# supersession that is not there — and because this is the ONE reason whose subject is the SET rather
# than the branch: nothing is wrong with the member named on the row, and a reader must be able to
# tell that at a glance rather than inferring it from the rule.
_LAND_REPEATED_RED_SET_EXCLUSION_REASON = "exact-set-already-reddened"
_LAND_SUPERSEDED_SKIP = "superseded-nothing-to-integrate"


def _acquire_land_reservation(main_wt: Path, on_wait=None, on_degrade=None,
                              *, superseded_probe=None, superseded_out=None,
                              self_branch=None, _land_consume_yield_offer=None, _land_reservation_held_by_self=None, _land_reservation_park_limit_seconds=None, _land_reservation_path=None, _land_supersession_probe_fired=None, _land_yield_offer_blocks=None) -> "int | None":
    """T-10549 (X-0415) — ESCALATE a verify-paid lander from optimistic retry to an EXCLUSIVE land
    reservation, and return the held fd. The caller keeps that fd for the rest of the process: the
    release IS process exit.

    WHY the livelock needs this. Correctness forbids the cheap fix — the ff-race loser MUST re-verify
    (land never ffs an untested A+B combination), so the loop is merge -> verify(minutes) -> ff. When
    the inter-land arrival interval is shorter than a verify, the lander loses the race EVERY pass and
    exhausts the bounded retries (boomrocket task/T-0192, 5/5 three runs running; and T-10548's own
    land, 2026-07-15, under a 4-lander fleet). `_land_retry_backoff_seconds` (T-0254 + T-10010) only
    shrinks the COLLISION PROBABILITY — under a sustained fleet it stays ~1. This grants what nothing
    else does: a WINDOW in which the verify-paid lander can actually finish. Peers park on it
    (`_await_land_reservation`) at the top of their next attempt, so the holder merges -> verifies ->
    ffs unopposed. Fairness bought with throughput, and ONLY after two lost races prove contention.

    CRASH-SAFE HOLD — the same idiom as the SPEC-0132 verify slots: an exclusive fcntl flock the OS
    auto-releases on process death, so an OOM-killed or aborting lander leaks no reservation (a mutable
    counter would). The caller ALSO releases it explicitly when the land span ends (T-11117): at
    `_LAND_FAIRNESS_ATTEMPT = 1` every land holds one, so waiting for process exit would keep peers
    queued through the whole post-ff teardown — and it deadlocks two in-process lands outright, since
    an flock is per open-file-description and a second land in the SAME process blocks on the first
    one's fd. The OS release stays the belt: explicit release is an optimisation of WHEN, never the
    thing correctness rests on. Two landers serialize HERE (FIFO-ish), never deadlock: the ordering is
    reservation -> verify slot -> repo lock, and a queued peer holds NOTHING.

    `on_wait(waited_s)` is called each un-acquired poll tick (T-10128's observable-wait shape) so a
    blocked acquisition reaches the journal instead of reading as a hang to a headless worker.

    T-11117 — BOUNDED, AND IT LEAVES RATHER THAN QUEUEING FOREVER. Returns the held fd, or **None**
    when it gave the reservation up after `_land_reservation_park_limit_seconds()`. THIS HELPER ONLY
    LEAVES AND REPORTS: it closes the fd, fires `on_degrade` once and returns, and THE CALLER decides
    what that means. T-11117's caller proceeded on the ordinary optimistic path (degrade-to-race);
    since T-11819 (owner decision 2026-08-28) the land caller HALTS instead — but the leaving is
    unchanged and stays this helper's whole contribution, because it is the waiter LEAVING that keeps
    a wedged holder from parking the repo. (See `_await_land_reservation`, which carries the same
    bound for the non-holding shape.) This is the bound that ACTUALLY fires in
    production: at attempt 1 every land comes through HERE, so a live-but-wedged holder — whose flock
    the OS will not release, because the process is hung rather than dead — would otherwise queue every
    land in the repo behind it forever. `on_degrade(waited_s)` fires exactly once on that expiry.

    T-11274 (SPEC-0184 rule 8) — OPTIONAL `superseded_probe` / `superseded_out`: THIS is the park site
    that actually fires. At `_LAND_FAIRNESS_ATTEMPT = 1` every land reaches attempt 1 holding no
    reservation, so it comes through HERE and blocks; `_await_land_reservation` is reached only on the
    degraded/retry shape. Both are wired, because a fix delivered only to the sibling would be delivered
    to the site that does not run. When `superseded_probe()` answers True at a poll tick — one `exists()`
    of a fixed path, the same cost class as the flock test beside it, NEVER a journal read — this STOPS
    PARKING, appends the fact to `superseded_out` and returns None WITHOUT the reservation. Returning
    None is shared with the degrade path, so the caller MUST read the sink to tell the two apart: a
    supersession is not a degradation and must not be journaled as one. `superseded_probe=None` (every
    existing caller and test) → BYTE-IDENTICAL behaviour, probe never called."""
    if _land_supersession_probe_fired(superseded_probe, superseded_out):
        # Already superseded before we even asked for the reservation (the head ff'd while this land was
        # doing its cheap preflight). Take nothing: the whole point is that this land pays for nothing.
        return None
    fd = lockfile.open_flock_target(_land_reservation_path(main_wt))
    # T-11279 — THE FAST PATH ABSTAINS TOO. This uncontended acquire runs BEFORE the park loop, so a
    # fix delivered only to the loop would be delivered to the site that does not run in the common
    # case: the released window is precisely when the lock is FREE, which is exactly when this branch
    # fires. Caught by the AC6 tripwire (the addressee took the slot here and never consumed the
    # offer) and the AC3-part2 one (an abstaining peer took it here outright).
    if not (self_branch and _land_yield_offer_blocks(main_wt, self_branch)):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _land_consume_yield_offer(main_wt, self_branch)   # the addressee's own act
            return fd
        except OSError:
            pass   # a peer holds it (another lander mid-span) — poll so the wait stays observable
    if _land_reservation_held_by_self(main_wt):
        # A NESTED in-process land: we are the holder. Waiting is waiting on ourselves — proceed
        # optimistically at once. Not an `on_degrade`: this is not a wedged peer, it is a shape that
        # cannot arise in a real land process, so it must not be journaled as one.
        os.close(fd)
        return None
    _t0 = time.monotonic()
    _limit = _land_reservation_park_limit_seconds()
    while True:
        # T-11279 — ABSTAIN for this tick while a LIVE offer names somebody else. `self_branch=None`
        # (every pre-change caller and test) never abstains, so the loop is byte-identical without it.
        # The abstention is bounded by the SAME park limit below, and that reuse is exactly why this
        # card adds no bound of its own (ceiling-convergence consult, 2026-08-19).
        if not (self_branch and _land_yield_offer_blocks(main_wt, self_branch)):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _land_consume_yield_offer(main_wt, self_branch)   # the addressee's own act
                return fd
            except OSError:
                pass
        _waited = time.monotonic() - _t0
        if _waited >= _limit:
            # The bound. Give the reservation up and let the CALLER decide (race pre-T-11819, halt
            # since), rather than queue behind a holder that is never going to release. T-11279: an
            # abstaining yielder leaves through HERE too — this is the branch that withdraws an offer
            # nobody ever came for.
            os.close(fd)
            if on_degrade is not None:
                on_degrade(_waited)
            return None
        if _land_supersession_probe_fired(superseded_probe, superseded_out):
            # The holder ff'd our content while we waited — which is the common shape, since the
            # holder marks its members inside the very ff lock it is holding this reservation for.
            # Stop parking and give the reservation up: a land with nothing to integrate must not
            # spend a slot, and must not keep the next peer waiting for one either.
            os.close(fd)
            return None
        if on_wait is not None:
            on_wait(_waited)
        time.sleep(_LAND_RESERVATION_POLL_SEC)

def _await_land_reservation(main_wt: Path, on_wait=None, on_degrade=None,
                            *, superseded_probe=None, superseded_out=None,
                            self_branch=None, _land_consume_yield_offer=None, _land_reservation_held_by_self=None, _land_reservation_park_limit_seconds=None, _land_reservation_path=None, _land_supersession_probe_fired=None, _land_yield_offer_blocks=None) -> bool:
    """T-10549 — the PARK side: block while a peer holds the land reservation, then return WITHOUT
    holding it. Called at the top of each attempt by a lander that has not taken the reservation, so
    the holder gets its clear merge->verify->ff window (see `_acquire_land_reservation`).

    THE FAST PATH IS THE COMMON PATH: with no reservation held this is ONE non-blocking flock
    acquire+release and no sleep — so a single, uncontended land is unchanged (no new waits). The
    caller must NOT hold the reservation afterwards: parking peers hold nothing, which is what keeps
    the holder's verify slot free (the reservation -> slot -> repo-lock ordering).

    T-11117 — BOUNDED, AND IT LEAVES RATHER THAN HANGING. This loop used to be a bare `while True`.
    The flock auto-releases on process DEATH but NOT on process HANG, so ONE live-but-wedged holder
    parked every land in the repo forever; at `_LAND_FAIRNESS_ATTEMPT = 1` every land takes the
    reservation, which turns that from exotic into routine. Past
    `_land_reservation_park_limit_seconds()` the waiter STOPS PARKING and RETURNS — and what happens
    next is THE CALLER'S decision, not this helper's. T-11117's caller fell back to the ordinary
    optimistic path (race for the ff, re-verify if it loses); since T-11819 (owner decision
    2026-08-28) the land caller HALTS on a recorded abort instead. Either way the WAITER LEAVES,
    which is the property this bound exists for and the only one this helper owns. Returns True if
    the reservation was observed FREE, False if the bound fired. THIS HELPER STILL NEVER ABORTS: it
    raises nothing, so a wedged peer cannot fail another land from in here — the halt is taken by the
    land call site, above, with main untouched. NOT a holder-side timed release either: releasing a
    holder mid-verify would destroy the exclusivity this whole mechanism exists to buy, handing back
    the redo waste it was measured to remove.

    `on_degrade(waited_s)` is called EXACTLY ONCE, on that expiry, so the firing reaches the journal
    as a named row (`land_reservation_park_halted`; `land_reservation_park_degraded` before T-11819)
    instead of passing silently — the rate is then measured after the fact rather than guessed. The
    parameter keeps its name: it is the helper's stable seam and the sites that pass it are the
    reservation mechanism, which T-11819 does not touch.

    T-11274 (SPEC-0184 rule 8) — OPTIONAL `superseded_probe` / `superseded_out`, the SAME wiring as
    `_acquire_land_reservation` (which is the site that fires at `_LAND_FAIRNESS_ATTEMPT = 1`; this one
    carries the degraded/retry shape). A probe hit STOPS the park, appends to `superseded_out` and
    returns True — the free-reservation value, not the degraded one, because a superseded land is not
    racing anybody: it is about to establish that it has nothing to integrate at all. The caller reads
    the SINK, never the bool, to tell a supersession from an ordinary free lock. The probe is ONE
    `exists()` — never a journal read; the cost-class contract lives on
    `_land_supersession_marked`. `superseded_probe=None` → BYTE-IDENTICAL behaviour."""
    if _land_supersession_probe_fired(superseded_probe, superseded_out):
        return True            # nothing to integrate — do not park, and do not read as degraded
    fd = lockfile.open_flock_target(_land_reservation_path(main_wt))
    try:
        _t0 = time.monotonic()
        _limit = _land_reservation_park_limit_seconds()
        _self_held = None      # resolved lazily, and only while blocked (see the acquire side)
        while True:
            # T-11279 — the sibling abstention (see `_acquire_land_reservation`). Same fail-open
            # contract, same park-limit bound, byte-identical when `self_branch` is None.
            if not (self_branch and _land_yield_offer_blocks(main_wt, self_branch)):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Free: we hold it only momentarily to PROVE it is free — drop it at once so we do
                    # not become an accidental holder (we have not earned a reservation).
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    _land_consume_yield_offer(main_wt, self_branch)   # the addressee's own act
                    return True
                except OSError:
                    if _self_held is None:
                        _self_held = _land_reservation_held_by_self(main_wt)
                    if _self_held:
                        return True   # nested in-process land: we hold it ourselves, nothing blocks us
            _waited = time.monotonic() - _t0
            if _waited >= _limit:
                # The bound. Stop parking — announce it, then hand the decision back to the caller.
                if on_degrade is not None:
                    on_degrade(_waited)
                return False
            if _land_supersession_probe_fired(superseded_probe, superseded_out):
                return True   # the holder ff'd our content while we waited — stop parking
            if on_wait is not None:
                on_wait(_waited)
            time.sleep(_LAND_RESERVATION_POLL_SEC)
    finally:
        os.close(fd)

def _land_median_verify_wall_ms(events_path: "Path | None", *, _scan=None,
                                max_bytes: int = _LAND_VERIFY_WALL_TAIL_BYTES) -> "tuple[int | None, int]":
    """T-11609 (SPEC-0184 rule 1, the realization exit) — the MEDIAN VERIFY WALL-CLOCK PER PASS, and
    the size of the sample it was taken over. `(None, 0)` when there is no sample.

    WHY A FORMATION ROW NEEDS IT, and why `paying_members` cannot answer it. `paying_members` says
    WHETHER a member would have paid a pass; it never says what a pass COSTS. Batching amortises ONE
    pass, so the entire benefit of forming a batch is the price of that pass times the members who
    would otherwise each have paid it — and until this reader existed the row carried both factors of
    that product except the price. That gap is not academic: the narrowing T-11521 shipped made the
    kernel pass materially cheaper, which moves the benefit of every batch this module forms, and no
    surface would have shown it. A number that changes the value of the mechanism must be visible on
    the mechanism's own record.

    IT IS A REPORT, AND IT DECIDES NOTHING. Nothing reads this back: membership, the cap, the cost
    ladder, the class order and every fail-closed direction are exactly what they were. The figure
    exists so a HUMAN re-folding the journal can see whether the amortisation is still worth the fate
    it binds — which is the judgement this reader informs and never makes.

    THE SOURCE IS `land_completed.data.verify_duration_ms`, the wall-clock a completed land RECORDS
    for its own verify. It is read rather than re-derived, and no other row is consulted: an attempt
    breakdown, a queue wait or an admission wait are different quantities, and folding any of them in
    would answer a question nobody asked with a number that looks like this one.

    BOUNDED, and the bound is on SPEND rather than on the answer (`_LAND_VERIFY_WALL_TAIL_BYTES`,
    whose own comment carries the measurement). It reuses `journal_mod.tail_scan_events`, the SAME
    bounded-tail primitive every other reader in this module uses — a second journal path here would
    be the parallel encoding CHARTER §P1 F1 forbids.

    FAILS OPEN, TO (None, 0), ON EVERYTHING: no path, a path that does not exist, an unreadable or
    unparseable journal, a scan that raises, or a span carrying no usable row. The direction is the
    point — this is a REPORT on a land that is otherwise proceeding normally, so a reader that could
    not answer must cost the land nothing and must say nothing rather than emit a fabricated figure.
    A zero would be read as "a pass is free", which is the one claim this reader exists to refute.

    A ROW MUST CARRY A POSITIVE NUMERIC DURATION TO COUNT. A missing, null, non-numeric, boolean,
    zero or negative value is SKIPPED rather than coerced: those are rows that did not measure a
    verify (a land that ran no tests, an older row, a malformed one), and averaging them in would
    drag the median toward a cost nobody paid.

    THE MEDIAN, NOT THE MEAN, and that is deliberate. Land verify durations are strongly
    right-skewed — this repo's own fold gives a median of ~3 min against a p90 near 11 — so a mean
    would report a typical pass as far dearer than any typical pass actually is.
    """
    if events_path is None:
        return (None, 0)
    scan = _scan or journal_mod.tail_scan_events
    try:
        rows = scan(Path(events_path), "land_completed", max_bytes=int(max_bytes))
    except Exception:                          # noqa: BLE001 — a report that cannot be taken is silent
        return (None, 0)
    vals: "list[float]" = []
    for ev in rows or ():
        if not isinstance(ev, dict) or ev.get("type") != "land_completed":
            continue                           # the byte prescan is a SUPERSET — reject on the field
        # `data` IS TYPE-CHECKED, not merely truthiness-checked (audit-post finding, medium,
        # 2026-08-29). `(ev.get("data") or {}).get(...)` reads as defensive and is not: a TRUTHY
        # non-mapping — a string, a list, whatever a malformed or hand-written row carries — passes
        # the `or` and then raises on `.get`. This function's whole contract is that unparseable
        # journal content costs the land NOTHING, so a malformed row must be SKIPPED here rather
        # than escape as an exception the caller never expected.
        _d = ev.get("data")
        if not isinstance(_d, dict):
            continue
        v = _d.get("verify_duration_ms")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            continue
        vals.append(float(v))
    if not vals:
        return (None, 0)
    vals.sort()
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    return (int(round(med)), len(vals))


def _emit_land_batch_formed(members: "list[dict]", paying: int, *, batch_id: "str | None" = None,
                            engagement: "str | None" = None, batch_max: int = _LAND_BATCH_MAX,
                            queue_excluded: "list | None" = None,
                            queue_snapshot: "dict | None" = None,
                            formation_ids: "dict | None" = None,
                            horizon_truncated: "list | None" = None,
                            _append_event, events_path: "Path | None" = None, _land_live_queue_depth=None, _land_read_ts_iso=None, _median_verify_wall_ms=None) -> int:
    """Journal ONE `land_batch_formed` row for a formed batch — and, at N=1, ONLY when the queue was
    non-empty and its candidates were EXCLUDED.

    The row carries `members` (the count) and `paying_members` SEPARATELY (SPEC-0184's realization
    exit criterion): a reader must be able to see a 4-member batch that saved exactly one pass.

    The N=1 clause lives HERE, inside the emitter, for the same load-bearing reason it lives inside
    `_emit_land_member_verdicts`: rule 1 promises a singleton land is byte-identical to the pre-spec
    path at the EVENT level, and putting the check in the emitter means every later call site
    inherits that guarantee instead of re-deriving it correctly N separate times.

    T-11235 — AT N=1 THE CLAUSE IS A FORK, NOT A BLANKET SILENCE, and the fork is exactly where
    rule 1 draws its own line. Rule 1 scopes byte-identity to a QUIET repo: "a quiet repo forms a
    batch of ONE, which MUST be byte-identical to pre-spec behaviour". A repo whose queue held
    candidates that this formation DROPPED is not quiet, and reading the silence as covering it made
    a formation decision unobservable — "the queue was empty" and "a candidate was excluded for
    reason X" produced identical journals, which is why two solo lands on 2026-08-17 could not be
    classified at all. So:

      * `queue_excluded` EMPTY at N<=1  -> no row, unchanged. The quiet repo keeps its byte-identity,
        and the fix therefore cannot degenerate into a blanket always-emit that reintroduces the
        noise the silence exists to avoid.
      * `queue_excluded` NON-EMPTY at N<=1 -> ONE row carrying the reasons, marked `solo: true` with
        `queue_depth` = the candidates this formation SAW. Same event type, additive keys — no new
        event type and no new store (CHARTER §P1 F2). `members: 1` + `solo: true` keep it filterable
        for a reader counting real formations.

    T-11312 — THE ROW ACCOUNTS FOR EVERY ENUMERATED CANDIDATE, AGAINST THE CLOCK IT WAS READ AT.
    `queue_snapshot` is `{"read_ts", "seen"}` from `_land_batch_members`; when it is ABSENT this
    emitter is byte-identical to before, which is what keeps every existing caller (and the quiet-repo
    promise) untouched. When present the payload grows exactly two keys — no new event type, no new
    store (CHARTER §P1 F2):

      * `read_ts` — when the candidate snapshot was READ, as an ISO-8601 Z string. DISTINCT from the
        row's own `ts`, which the journal stamps at emit: formation runs merge probes and cost
        classification between the two, so a reader correlating this row against wait heartbeats was
        aligning them to the wrong instant. That is not a hypothetical — it is one of the two
        hypotheses the 2026-08-19 consult could not discriminate without this field.
      * `queue_dispositions` — one `{branch, disposition}` per branch the queue source YIELDED:
        `admitted` when it is in the member list, else its `queue_excluded` reason, else
        `unaccounted`. This is the atomic rule and the reason the card exists: at 10:55:02Z that day a
        row carried nine exclusions and one member while task/T-11285 — waiting continuously across
        the instant — appeared in NEITHER, and no reader could tell whether it had been dropped or
        never seen. `unaccounted` makes the next such branch LOUD instead of absent.

    THE DISPOSITIONS RIDE EVERY ROW, NOT ONLY THE SOLO FORK, and that is deliberate rather than
    incidental — dispositions confined to the solo fork would have inherited the inversion T-11312
    found in `queue_depth` and named in place, deferring the repair to its own carrier.

    T-11323 — THAT CARRIER: `queue_depth` COUNTS LIVE PEERS, ON EVERY ROW. It used to be written
    only under the N<=1 branch, as `len(members)-1 + len(queue_excluded)`, so it was silent exactly
    when peers existed and loud exactly when they did not: across 2026-08-19 every multi-member row
    carried it ABSENT — including a members=2 paying=2 formation at 19:27:28Z — while all five solo
    rows carried 8-10, composed ENTIRELY of stale-wait-row ghosts. A field that reads backwards is
    worse than a missing one: three times that evening a reader could not conclude anything from a
    row saying "depth 5, one member", because the number could not be trusted in either direction.
    So the derivation moved to `_land_live_queue_depth` (the admitted peers plus the distinct
    excluded branches the queue reader did NOT judge absent) and the key now rides every row.
    `solo` STAYS gated on N<=1 — it describes the batch, not the queue. NOTHING about admission
    changes: the member set, the sink, the dispositions and the quiet-repo no-row clause are what
    they were, and this card repairs a derived REPORT only.

    THE N=1 CLAUSE WIDENS BY EXACTLY ONE TERM: a formation that SAW candidates emits a row. A repo
    whose queue read yielded nobody stays silent and byte-identical, so rule 1's quiet-repo promise is
    untouched and this is NOT the blanket always-emit T-11235 already refused. The new term matters
    because the ghost case is precisely a formation that saw a candidate and lost it without filling
    the exclusion sink — under the old condition that formation emitted NOTHING at all.

    T-11609 — THE ROW NOW SAYS WHAT A PASS COST, beside how many members covered one. `members` and
    `paying_members` are both counts of MEMBERS; neither is a price, so the row carried both factors
    of the amortisation product except the one that decides its size. `verify_wall_ms_median` (with
    `verify_wall_ms_median_n`, the sample it was taken over) is folded read-only from completed
    lands' own recorded verify wall-clock by `_land_median_verify_wall_ms`.

    IT IS READ AFTER THE N=1 EARLY RETURN, and that position is the contract rather than a tidiness:
    rule 1 promises a quiet repo's solo formation runs no subprocess, reads nothing and writes no
    object, so a formation that emits NO row must not pay a journal read to compute a figure for a
    row that will not exist.

    BOTH KEYS ARE OMITTED WHEN THERE IS NO SAMPLE — never a zero. A zero here reads as "a pass is
    free", which would invert the very argument the figure is reported to inform; an absent key says
    the honest thing, that this land could not measure it. So a hermetic caller passing no
    `events_path` gets the pre-change payload byte-for-byte, exactly as it does for `queue_snapshot`
    and `formation_ids`.

    Returns the number of rows emitted, so a probe can assert the count."""
    _seen = list((queue_snapshot or {}).get("seen") or [])
    if len(members) <= 1 and not queue_excluded and not _seen:
        return 0
    data = {"members": len(members), "paying_members": int(paying), "batch_max": int(batch_max),
            "branches": [m.get("branch") for m in members]}
    # T-11323 — the depth rides EVERY row, and counts LIVE candidates. `solo` stays gated on N<=1
    # because it describes the BATCH; the depth describes the QUEUE, and a queue is exactly what a
    # multi-member formation proves it had.
    data["queue_depth"] = _land_live_queue_depth(members, queue_excluded)
    if len(members) <= 1:
        data["solo"] = True
    if batch_id:
        data["batch_id"] = batch_id
    if engagement:
        data["engagement"] = engagement
    # T-11219 — the branches that LOOKED queued (fresh wait heartbeats) but were not admitted because
    # their land had stopped waiting, each with its reason. Additive key (SPEC-0025 / D-0009 —
    # consumers ignore unknown keys), so no existing reader of this row is affected.
    # T-11235 RETIRED the reading that the N=1 silence governs this key too. That reading was a
    # GAP, not a bound: it made the exclusion's reason unrecordable precisely in the case where it is
    # the whole explanation of what happened. The byte-identity it claimed to protect belongs to a
    # QUIET repo, which a repo with dropped candidates is not — see the N=1 fork in the docstring.
    if queue_excluded:
        data["queue_excluded"] = [dict(x) for x in queue_excluded]
    # T-11312 — the two fields, written together because they answer one question: WHICH candidates
    # this formation saw, and WHEN it saw them. Both are conditional on the snapshot, so a caller that
    # supplies none gets the pre-change payload exactly.
    if queue_snapshot:
        _rts = queue_snapshot.get("read_ts")
        if isinstance(_rts, (int, float)) and not isinstance(_rts, bool):
            data["read_ts"] = _land_read_ts_iso(float(_rts))
        _reason = {}
        for x in (queue_excluded or ()):
            _b = str((x or {}).get("branch") or "")
            if _b and _b not in _reason:        # FIRST reason wins — a branch is excluded once, and a
                _reason[_b] = str((x or {}).get("reason") or "")   # later duplicate must not rename it
        _admitted = {str((m or {}).get("branch") or "") for m in members}
        data["queue_dispositions"] = [
            {"branch": b,
             "disposition": (_LAND_DISPOSITION_ADMITTED if b in _admitted
                             else _reason.get(b) or _LAND_DISPOSITION_UNACCOUNTED)}
            for b in _seen]
    # T-11517 — THE THREE IDS OF THE DECISION, from `_land_batch_formation_ids` (which is where the
    # whole argument for them lives). Additive and CONDITIONAL, exactly like `queue_snapshot` above:
    # a caller that supplies none gets the pre-change payload byte-for-byte, so every hermetic caller
    # and SPEC-0184 rule 1's quiet-repo byte-identity stay untouched. No new event type and no new
    # store (CHARTER §P1 F2) — the row that already announces the membership now also says, in ids
    # that outlive the branches, WHAT it batched, ON WHAT, and AGAINST WHICH baseline.
    if formation_ids:
        for _k in ("member_tips", "base", "pinned_baseline"):
            if formation_ids.get(_k) is not None:
                data[_k] = formation_ids[_k]
    # T-11609 — WHAT A PASS COST, read here and nowhere earlier: this line sits BELOW the N=1 early
    # return, so a quiet repo's solo formation still reads nothing at all (rule 1's byte-identity).
    # Injectable for the hermetic probes; `None` means "no sample", and no sample means NO key —
    # a fabricated zero would read as a free pass and invert the argument the figure informs.
    # T-11904 — WHAT THIS FORMATION COULD NOT SEE, on the row that records what it decided.
    # ADDITIVE and CONDITIONAL, exactly like `queue_snapshot` / `formation_ids` above: a formation
    # whose reads covered their declared horizons — which, after this card, is the ordinary case —
    # carries no key at all and stays byte-identical, so rule 1's quiet-repo promise is untouched.
    # It rides `land_batch_formed` rather than a new event type or a second store (CHARTER §P1 F2)
    # because the fact it carries is a property OF this formation: these members were selected on a
    # read that admitted it could not see all the history it declared, and a later reader
    # re-deriving why a branch was admitted must be able to see that from the row itself rather than
    # from a stderr line nobody kept. Absence of the key is therefore a positive claim — every
    # horizon read this formation made reached back as far as it said it would.
    if horizon_truncated:
        data["horizon_truncated"] = [dict(x) for x in horizon_truncated if isinstance(x, dict)]
    _median_ms, _median_n = (_median_verify_wall_ms or _land_median_verify_wall_ms)(events_path)
    if _median_ms is not None and _median_n > 0:
        data["verify_wall_ms_median"] = int(_median_ms)
        data["verify_wall_ms_median_n"] = int(_median_n)
    _append_event("land_batch_formed", (members[0] or {}).get("task"), data, events_path=events_path)
    return 1

def _emit_land_member_verdicts(members: "list[dict]", verdict: str, *,
                               _append_event, events_path: "Path | None" = None,
                               batch_id: "str | None" = None,
                               batch_size: "int | None" = None,
                               emitted_out: "list | None" = None) -> int:
    """Journal ONE `land_member_verdict` row per batch member — and NOTHING at N=1.

    SPEC-0184 rule 5 requires every member to carry its own verdict, while rule 1 requires a batch
    of one to be byte-identical to the pre-spec path at three levels (events, commits, terminal
    token). Those two do not collide, and the reason is an observation rather than a carve-out: a
    SINGLETON's land ALREADY carries its member's verdict, because the member IS the land — the
    existing `land_completed` row and the `^LAND:` token are that member's outcome in full. So there
    is no new carrier to add at N=1, and per-member rows exist ONLY for N>1, where there is no
    longer a one-to-one land to read a member's verdict from.

    The N=1 clause lives HERE, inside the emitter, and NOT at the call sites. That is the load-
    bearing placement: T-11193 (eviction) and T-11194 (red-batch requeue) each add a call site, and
    putting the check inside means they INHERIT rule 1's byte-identity guarantee instead of having
    to re-derive it correctly four separate times. A call site that wants the row unconditionally is
    the bug this shape prevents.

    An unknown `verdict` RAISES rather than emitting: a typo'd verdict is a row no reader can
    interpret, and SPEC-0025's catalog tolerance (D-0009 — consumers ignore unknown KEYS) does not
    extend to an unknown VALUE in a closed vocabulary a reader must act on. Loud, per SPEC-0165.

    `batch_id` is what lets a member's row be read WITHOUT reconstructing the batch (rule 5's actual
    point). It is not minted here — this is a reporter — but it is no longer merely DEFINED either:
    T-11331 mints one id per formation (`_land_mint_batch_id`, called in `cmd_land` when the formed
    batch has more than one member) and threads it to every call site, so a member's row joins to its
    `land_batch_formed` row by VALUE. Before that, reconstruction by branch-plus-timestamp was the
    only route and it mis-attributed whenever one branch appeared in several batches. Still OPTIONAL
    at this seam: a caller that supplies none writes no key, which is what keeps a singleton's rows
    (and every hermetic probe) byte-identical.

    `batch_size` (T-11193 + T-11196, ADDITIVE — default `None` ⇒ `len(members)`, byte-identical to
    T-11191's behaviour for every existing caller) states the size of the BATCH this call's members
    belong to, which is not always the length of THIS list. Two sibling call sites arrived at the
    same need independently, which is itself the argument for the parameter: eviction
    (`_land_merge_members_in_queue_order`, rule 3) journals the members it removed, and
    `_land_drop_dead_members` (rule 6) journals the dead members of a live batch. Both hand over a
    SUBSET. With the size derived from the list, a lone evicted or dead member of a larger batch
    would be read as `len == 1`, silently swallowed by the N=1 clause below, and its row would carry
    `batch_size: 1` — both wrong for the same reason: rule 1's N=1 identity is a statement about the
    BATCH being a singleton, never about how many members one emit call happens to name. So the
    clause reads the batch, which is what SPEC-0184 rules 1 + 5 actually say, and the check stays
    INSIDE the emitter where T-11191 put it deliberately. It never widens rule 1 — a genuine
    singleton passes 1 (or omits it) and stays silent.

    `emitted_out` (T-11322, ADDITIVE — default `None` ⇒ nothing recorded, byte-identical for every
    existing caller) is a LIST the emitter appends each journaled BRANCH to. It exists because the
    accounting question rule 5 now asks — did every DECLARED member get a row? — can only be
    answered against what was ACTUALLY emitted, and the four call sites each know only their own
    slice. Recording it HERE, inside the one emitter, is the same placement argument the N=1 clause
    makes: a caller that had to remember to report its own emissions is a caller that will one day
    forget, and the forgetting would be invisible. Nothing is appended for a batch the N=1 clause
    silences — a singleton emitted no row and must not be counted as though it had.

    Returns the number of rows emitted (0 when the BATCH is a singleton), so a caller/probe can
    assert the count.
    """
    if verdict not in _LAND_MEMBER_VERDICTS:
        raise ValueError(
            f"land member verdict {verdict!r} is not in the SPEC-0184 rule-5 vocabulary "
            f"{list(_LAND_MEMBER_VERDICTS)} — a verdict outside it is unreadable to every consumer "
            f"(note `evicted-as-culprit` is deliberately absent: an evicted culprit IS "
            f"`requeued-after-red-batch` and carries the eviction as an additive key — T-11335)")
    _size = len(members) if batch_size is None else int(batch_size)
    if _size <= 1:
        # Rule 1 / rule 5 N=1 clause — the land's own rows ARE this member's verdict. Emitting here
        # is what would BREAK byte-identity, so silence is the behaviour, not an omission.
        return 0
    for _m in members:
        _data = {"branch": _m.get("branch"), "verdict": verdict, "batch_size": _size}
        if _m.get("task"):
            _data["task"] = _m["task"]
        if batch_id:
            _data["batch_id"] = batch_id
        # T-11258 — WHY this member was evicted, on the row that already reports THAT it was. The
        # cause is copied off the member record `_land_merge_members_in_queue_order` already marked
        # (rule 3), never recomputed here: the classifier ran once, at the seam that owns the
        # question, and this emitter is a reporter (CHARTER §P5 — one question, one authority).
        # Additive keys on an existing event, per SPEC-0025 / D-0009 (a consumer ignores unknown
        # keys) — no new event type, no new store, and rule 5's four-value verdict vocabulary,
        # `batch_size` and the N=1 clause are all untouched.
        #
        # VERDICT-AGNOSTIC BY CONSTRUCTION, which is why there is no `verdict == "evicted-..."`
        # test here: only the eviction path ever marks a member with these keys, so a `landed`,
        # `requeued-after-red-batch` or `dropped-dead-member` row is byte-identical to pre-change
        # without this emitter having to know which caller it is serving. Gating on the verdict
        # string instead would put a second, drifting answer to «which removals have a cause»
        # beside `_LAND_MEMBER_REMOVAL_EMITS_VERDICT`, which is the one that decides it.
        #
        # ABSENT MEANS UNPROVEN, NEVER ZERO. A member whose eviction came through one of the
        # oracle's fail-closed fallbacks carries neither key, and the row then says nothing about
        # the cause rather than guessing one — a fabricated reason reads as evidence and is worse
        # than a missing one. `_mark` is where that judgement is made and stated in full.
        for _k in ("conflict_blocking", "conflict_auto_resolvable"):
            if _m.get(_k):
                _data[_k] = list(_m[_k])
        # T-11259 — WHICH pinned assertion is attributably THIS member's own, on the row that already
        # reports THAT it was requeued. Same shape and same reasons as the T-11258 block above: the
        # judgement was made once, at `_land_attribute_failing_assertions` (the seam that HAS the
        # failing assertions), and this emitter only REPORTS it — additive keys per SPEC-0025 / D-0009,
        # verdict-agnostic by construction (only the dissolve path ever marks a member), and ABSENT
        # MEANS UNPROVEN rather than «nothing superseded»: every one of that function's four gates
        # fails closed, because a guessed attribution reads as evidence and would send an innocent
        # member to declare a `--rebaseline` waive it does not owe.
        if _m.get("superseded_test_file"):
            _data["superseded_test_file"] = _m["superseded_test_file"]
        if _m.get("superseded_assertions"):
            _data["superseded_assertions"] = list(_m["superseded_assertions"])
        # T-11331 — WHAT KILLED THE BATCH this member was in, on the row that already reports THAT it
        # was requeued. Same additive shape and same argument as the blocks around it: the judgement
        # was made once (the verify produced the failing entries, `_land_dissolve_batch` marks them)
        # and this emitter only REPORTS it. Verdict-agnostic by construction — only the dissolve path
        # marks the key, so no other verdict's row is touched — and additive per SPEC-0025 / D-0009.
        #
        # DISTINCT FROM `superseded_assertions` DIRECTLY ABOVE, and the pair must not be collapsed:
        # that key is an ATTRIBUTION ("this member's own change superseded this pinned assertion"),
        # decided by four fail-closed gates and carried by at most one member. This one is the
        # BATCH's cause, carried by all of them and claiming nothing about whose change it was. A
        # reader that conflated them would read a batch-wide fact as a per-member accusation, which
        # is exactly the authority confusion the attribution gates exist to prevent.
        #
        # ABSENT MEANS UNRECORDED. A red batch whose abort surfaced no assertion text (an unnamed
        # failure, a verify timeout) carries no key rather than an empty list — a fabricated cause
        # reads as evidence.
        if _m.get("red_assertions"):
            _data["red_assertions"] = list(_m["red_assertions"])
        # T-11272 — the one-round batch-ineligibility rule 4 attaches to this requeue, when the
        # dissolve PROVED this member innocent of the red. Copied, never decided here: the judgement
        # is `_land_red_batch_ineligible_members`' and only the dissolve path ever writes the key, so
        # every other verdict's row stays byte-identical. Tested with `is False` rather than
        # truthiness because ABSENT and FALSE mean different things to the reader — absent is
        # "ineligible", the pre-T-11272 behaviour every existing row on main carries — and a
        # truthiness test cannot tell them apart.
        if _m.get("batch_ineligible") is False:
            _data["batch_ineligible"] = False
        # T-11335 — WHY this member, and this member ALONE, was taken out of a red batch while its
        # peers carried on. Same additive, copy-never-decide shape as the three blocks above: the
        # judgement was made once, by `_land_red_isolation_probe` at the seam that holds both the
        # member list and the failing set, and this emitter only REPORTS it. Only the red-isolation
        # eviction path ever writes these keys, so every other row stays byte-identical without this
        # emitter having to know which caller it is serving.
        #
        # THE VERDICT STRING IS DELIBERATELY UNCHANGED — `requeued-after-red-batch`, not a fifth
        # vocabulary value. It is TRUE (the culprit does go back to the queue for its own solo land),
        # it keeps rule 5's vocabulary CLOSED exactly as T-11191/T-11194/T-11322 each pinned it shut,
        # and — load-bearing, not cosmetic — it is what `_land_batch_ineligible_branches` already
        # reads, so the culprit inherits rule 4's one-round batch-ineligibility from the UNCHANGED
        # mechanism instead of needing a second one. What CHANGED is who gets a row at all: the
        # innocent peers no longer get one, because they are not requeued. `red_isolation` carries
        # the evidence (the failing set and the files THIS member reproduced alone), so the row says
        # WHY and not only THAT — and ABSENT MEANS UNPROVEN, never "reproduced nothing".
        if _m.get("evicted_as_culprit"):
            _data["evicted_as_culprit"] = True
        if _m.get("red_isolation"):
            _data["red_isolation"] = dict(_m["red_isolation"])
        # T-11348 — WHY NOBODY was evicted from this red batch, on the rows that already report THAT
        # every member was requeued. The exact mirror of the block above and the same copy-never-
        # decide shape: the judgement was made once (`_land_red_isolation_probe` decided it,
        # `_land_red_decline_record` hands it over verbatim) and this emitter only REPORTS it.
        # Verdict-agnostic by construction — only the dissolve path marks `red_decline`, a key no
        # other path writes — so every `landed` / `evicted-for-conflict` / `dropped-dead-member` /
        # `unaccounted` row stays byte-identical.
        #
        # IT IS THE COMPLEMENT OF `red_isolation` DIRECTLY ABOVE, and the two are mutually exclusive
        # by the fork that produces them: an EVICTION marks `red_isolation` on the culprit alone, a
        # DECLINE marks `red_decline` on every member. Before this, only the first of the two ever
        # reached a reader, so a mechanism that never fires and one that fires correctly were
        # externally identical — which is what fu_b4dfe740d2f9 has been unable to tell apart.
        #
        # ABSENT MEANS THE ANALYSIS WAS NOT HANDED OVER, never "there was no reason". `undecidable`
        # is a PRESENT answer with a named reason and is recorded as one.
        if _m.get("red_decline"):
            _data["red_isolation_decline"] = dict(_m["red_decline"])
        # T-11387 — THIS MEMBER WAS RELEASED, NOT PUNISHED, on the row that already reports THAT it
        # was requeued. Same additive, copy-never-decide shape as every block above: the judgement
        # was made once, by the head-is-culprit arm of the red fork, and this emitter only REPORTS
        # it. Only `_land_release_peers_for_solo_head` marks the key, so every other row stays
        # byte-identical without the emitter having to know which caller it is serving.
        #
        # IT IS WHAT MAKES A RELEASE READABLE AS ONE. The verdict string is deliberately the
        # unchanged `requeued-after-red-batch` (rule 5's vocabulary stays closed), and
        # `batch_ineligible: False` records only the ABSENCE of the penalty — which a dissolve that
        # attributed its red also writes. Without this key a reader could not tell "released because
        # the HEAD was the culprit" from "requeued but proved innocent", and those are different
        # facts about different mechanisms.
        #
        # ABSENT MEANS NOT RELEASED, never "released for no reason".
        if _m.get("released_from_batch"):
            _data["released_from_batch"] = dict(_m["released_from_batch"])
        # T-11495 — WHOSE the red was, on the row that already reports THAT the member was requeued
        # and (since T-11494) WHAT the batch died on. Same additive, copy-never-decide shape as every
        # block above: the judgement was made ONCE by `_land_failure_attribution_probe`, under the
        # admission slot, and this emitter only REPORTS it. Only
        # `_land_release_peers_for_solo_head` marks the key, so every other row stays byte-identical
        # without the emitter having to know which caller it is serving — the T-11322 condition the
        # verdict-agnostic copying rests on.
        #
        # THE ROW KEY IS DELIBERATELY THE ABORT ROW'S OWN `failure_attribution`, not a second
        # spelling. Unlike `red_decline`->`red_isolation_decline` (which had to avoid colliding with
        # the `red_isolation` a reader already knew), this record IS the same record `land_completed`
        # carries, so one vocabulary lets a reader join the two surfaces instead of learning that the
        # member row's name for it differs.
        #
        # ABSENT MEANS THE PROBE'S ANSWER WAS NOT HANDED OVER, never "the red had no owner". A
        # probe-produced `undecidable` is a PRESENT answer with a named reason and is recorded as
        # one; the caller's `not-probed` sentinel is the absence (the marking gate owns that call).
        if _m.get("failure_attribution"):
            _data["failure_attribution"] = dict(_m["failure_attribution"])
        # T-11322 — WHY this member was left without an outcome, on the row that reports THAT it
        # was. Same additive shape and same reasons as the three blocks above: the reason was
        # recorded at the seam that removed the member, and this emitter only copies it. It is the
        # `unaccounted` row's enrichment and BEST-EFFORT by design — ABSENT MEANS UNRECORDED, never
        # "no reason existed", because a reconciler that guessed a reason would be manufacturing
        # exactly the evidence it exists to make honest.
        #
        # THE MEMBER-RECORD KEY IS `unaccounted_reason`, NOT `removal_reason`, AND THAT IS THE WHOLE
        # POINT OF THE SPELLING. Verdict-agnostic copying (the shape the three blocks above rely on)
        # is only sound while ONE path marks the key — and `removal_reason` is already carried by
        # every EVICTED member, so reading it here would grow the eviction row and break T-11258's
        # additive-shape probe. Rather than gate on the verdict string (a second, drifting answer to
        # "which rows carry a cause"), the reconciler marks a key nobody else writes; the ROW key
        # stays `removal_reason`, which is the vocabulary a journal reader already knows.
        if _m.get("unaccounted_reason"):
            _data["removal_reason"] = str(_m["unaccounted_reason"])
        _append_event("land_member_verdict", _m.get("task"), _data, events_path=events_path)
        if emitted_out is not None:
            emitted_out.append(_m.get("branch"))
    return len(members)

def _land_addressee_gone(main_wt: "Path | None", branch: "str | None") -> bool:
    """Is the offer's ADDRESSEE PROVABLY gone — its branch carrying no ref at all in `main_wt`?

    True ONLY on positive proof, exactly like the `os.kill(pid, 0)` writer fence it sits beside: there,
    OSError PROVES the author is gone; here, an absent ref PROVES the addressee is. Every shape this
    predicate does not fully understand answers False — NOT-PROVEN, offer stays live, pre-change
    behaviour. That polarity is load-bearing: a fence that guessed «gone» on a repo it could not read
    would silently switch the whole addressed handover off and return the system to the arrival-order
    lottery T-11279 replaced, which is a far worse failure than the stall this fence removes.

    IT IS NOT A REF RESOLVER AND NOT A SECOND ORACLE FOR GIT. It never resolves a ref to an oid and its
    answer never feeds a git call — it may conclude GONE and nothing else, so there is no reading it can
    get wrong in a way another git call would then act on.

    WHY THE FILESYSTEM AND NOT `git rev-parse`. `_LAND_RESERVATION_POLL_SEC` is 0.1s and this runs on
    that poll tick, so a subprocess here would be ~10 per second per parked lander — the wrong cost
    class for a loop that reads the flock and the clock and nothing else BY DESIGN, and the same class
    the writer fence beside it explicitly refuses. The live case — the common one — costs ONE
    `exists()`, the cost of the flock test next to it; the single `packed-refs` read happens only when
    the loose ref is absent, which is the case that is about to END the abstention anyway. Do not
    "simplify" this back into a subprocess."""
    br = (branch or "").strip()
    if main_wt is None or not br:
        return False
    try:
        git_dir = Path(main_wt) / ".git"
        heads = git_dir / "refs" / "heads"
        if not git_dir.is_dir() or not heads.is_dir():
            # No repo (the tripwire fixtures' bare temp dir), a LINKED worktree whose `.git` is a FILE,
            # or a reftable-format repo whose refs are not files at all. Nothing is proven here.
            return False
        if br.startswith("/") or ".." in br.split("/"):
            return False               # a name that could walk out of refs/heads proves nothing
        if (heads / br).exists():
            return False               # loose ref — the addressee is LIVE
        packed = git_dir / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.endswith(f" refs/heads/{br}"):
                    return False       # packed ref — the addressee is LIVE
        return True                    # no loose ref, no packed ref: PROVABLY gone
    except Exception:                  # noqa: BLE001 — an unreadable repo proves nothing (see docstring)
        return False

def _land_ambient_yitc_overrides() -> list:
    """T-11488 — the NAMES (never the values) of the `YITC_`-prefixed variables set in THIS
    process's environment, sorted. Report-only, and read exactly once, by the attribution line.

    IT EXISTS BECAUSE THE PROBE'S TWO ARMS SHARE THIS ENVIRONMENT. The paired re-run varies the
    DIFF and nothing else, so the reader who has just been told "this red is not attributable to
    your diff" needs the OTHER thing both arms held constant in order to rule it out. Without this
    the advice degenerates to "check your environment", which is a hedge; with it the reader gets
    the actual candidate list and can act on it in one step.

    NAMES ONLY, DELIBERATELY. A value can carry a path, a host or a token, and this string goes
    into an abort message that is journaled and read by others. The name is what identifies the
    stray override (`YITC_VERIFY_TEST_TIMEOUT` was the measured case); the value is not needed to
    spot it, and the reader can read their own environment once pointed at the name."""
    import os as _os
    return sorted(k for k in _os.environ if k.startswith("YITC_"))

# T-11713 — a path-shaped SUBJECT named inside an assertion's own text. Repo-relative posix shape
# only (at least one `/`, a short extension), so a bare identifier, a sentence, a number or a URL
# host never becomes a "path". Distinct + order-preserving; the CALLER decides what a count other
# than one means.
_LAND_ASSERTION_SUBJECT_RE = re.compile(
    r"(?<![\w./-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,6})(?![\w/-])")


def _land_assertion_subject_paths(assertion: str) -> "list[str]":
    """T-11713 — the repo-relative paths an assertion's TEXT names, in order, without repeats.

    THE MEASURED GAP (T-11675, read-only). That card added ONE journal reader —
    `_remedy_sweep_index` in `bin/lib/triage.py` — and reddened a census test it never touched:
    `test_t11449` asserted "78 recorded, 69 driven here, 6 by AC1g, 2 exempt, 1 uncovered". Its
    sibling `test_t11444` said the same and WAS touched, so gate 4 attributed that file and not the
    other. The red became PARTLY unowned, the eviction correctly declined, and three branches were
    requeued for one member's defect. Across 2026-08-27's sample that shape is the single biggest
    lever: 29 of 43 red land batches declined culprit-eviction with reason `pinned-entry`.

    THE EVIDENCE WAS ALREADY PRINTED. Such an assertion NAMES its subject, and a name of this shape
    resolves to a source path — which the SAME one-owner check gate 4 already applies to the test
    file can be run against. This function only EXTRACTS; it decides nothing.

    IT NAMES PATHS, NEVER GUESSES THEM. The shape required is deliberately narrow (a posix
    repo-relative path with a real extension) because the caller feeds the answer to a check that
    can CONVICT a member: a loose matcher that promoted an identifier or a prose fragment to a
    "path" would hand the caller a subject nobody named. Zero matches is the ordinary answer and
    the caller attributes nothing for it.

    THE SUBJECT THE CENSUS PRINTS IS A `(path, symbol)` PAIR, WHICH IS WHY A PATH MATCHER REACHES IT
    (audit-pre finding, absorbed mode-a 2026-08-27 — the finding read the measured subject as a bare
    SYMBOL, `_remedy_sweep_index`). It is not: the census population is keyed by the pair, e.g.
    `tests/test_t11444_segment_aware_readers.py` line 876 records
    `(("bin/lib/triage.py", "_remedy_sweep_index"), True, ...)`, and the uncovered line prints that
    key verbatim. So the path travels WITH the symbol and this matcher finds it inside the tuple
    literal, inside quotes, and in a `path#symbol` qualified form. The probes pin all three shapes.

    A SUBJECT NAMING ONLY A SYMBOL IS A STATED BOUND, not an oversight. Resolving a bare identifier
    to a file would need a symbol->path index this function has no reader for — a NEW reader, i.e. a
    second authority on ownership, which is exactly what gate 5 exists not to be. So a symbol-only
    subject returns nothing and the caller attributes nothing: the fail-closed direction, and the
    same answer as today."""
    seen: "list[str]" = []
    for m in _LAND_ASSERTION_SUBJECT_RE.finditer(str(assertion or "")):
        path = m.group(1)
        if path not in seen:
            seen.append(path)
    return seen

def _land_attribute_failing_assertions(members: "list[dict]", assertions: "list[str] | None", *,
                                       _changed_paths=None, _test_files=None, _NO_ASSERTION_CAPTURED=None) -> int:
    """T-11259 — mark the ONE batch member a pinned failing assertion is UNAMBIGUOUSLY attributable to.
    Returns the number of members marked (0 whenever nothing is provable). Pure: it touches only the
    member dicts it is handed, and `_emit_land_member_verdicts` copies the marks onto the row.

    THE DEFECT (measured 2026-08-17). A red batch journals every member `requeued-after-red-batch` —
    the FACT of the requeue and nothing about the CAUSE. The member whose change actually superseded a
    pinned last-green assertion then re-lands alone and REDISCOVERS that by running the whole suite
    again. Five branches were superseded that day and all five paid that second pass (the 19:56:05Z
    batch died on a `task/T-11232` assertion; T-11232 aborted solo at 20:40:55Z on the same one).
    Median verify was 5.9 min over 52 samples, so the rediscovery costs about one full pass. The
    answer was already in hand at the abort — this carries it to the member so its NEXT land declares
    the waive up front and pays ONE pass.

    WHAT IT DOES NOT DO, stated so it is not oversold: it does NOT save the batch. The batch is already
    dead when the row is written, and re-admission of the culprit is prevented STRUCTURALLY by T-11256
    (the one-round mark must be served by a land whose verify actually ran). This saves the MEMBER its
    own second pass and nothing more.

    RECORD NOTHING RATHER THAN GUESS — the whole shape of this function. A guessed attribution is
    WORSE than silence, because it reads as evidence and would send an innocent member to declare a
    `--rebaseline` waive for a supersession that is not its own: precisely the authority confusion
    SPEC-0077 §3a exists to prevent. Every gate below therefore fails CLOSED, and each one is a
    separate way the answer can fail to be provable:

      1. PINNED ONLY. Only `[pinned/last-green] `-prefixed entries are considered. A CANDIDATE verify
         failure is not a supersession of a last-green assertion, and the member's next land would not
         waive it.
      2. A NAMED ASSERTION ONLY. An entry whose assertion is `_NO_ASSERTION_CAPTURED` names nothing
         (T-10892 made that absence honest rather than plausible-and-wrong); attributing off it would
         re-manufacture exactly the plausible wrong answer that marker exists to refuse.
      3. THE KEY IS A BASENAME, SO RESOLVE IT AGAINST THE TEST-FILE UNIVERSE FIRST (audit-pre finding,
         absorbed mode-a 2026-08-18, twice). `_run_verify_tests` reports `test failed: <tf.name>` — a
         bare basename, which does NOT identify a file. `_test_files` supplies the paths the sweep
         itself runs, and the basename must map to EXACTLY ONE of them. Two known paths sharing a
         basename ⇒ nothing, AND THAT HOLDS EVEN IF ONLY ONE OF THEM WAS TOUCHED by a member: a
         changed-path count cannot break a tie the reported key itself does not break, and letting it
         would name a member for an assertion that may live in the other file. Zero known paths (an
         unknown key, or a consumer verify LAYER name, which is not a file at all) ⇒ nothing. No
         universe supplied ⇒ nothing.
      4. EXACTLY ONE MEMBER MODIFIED THAT PATH. Zero members ⇒ the batch did not cause it and no row
         may claim it. Two or more ⇒ the batch KNOWS it cannot tell which, and saying so by silence is
         the honest record. A member whose diff is unreadable contributes no paths, so it never wins a
         match by accident — it only ever shrinks what is claimed.
      5. T-11713 — THE SUBJECT ROUTE, tried ONLY when 3+4 attributed nothing. Gates 3 and 4 ask who
         authored the TEST FILE, which is why a red can be partly unowned: T-11675 added one reader in
         `bin/lib/triage.py` and reddened a census test it never touched, the eviction declined, and
         three branches were requeued for one member's defect (the shape behind 29 of 43 red batches
         declining with reason `pinned-entry` on 2026-08-27). So when the test file names nobody, the
         path the assertion's own TEXT names (`_land_assertion_subject_paths`) is put through the SAME
         two rules — unambiguous resolution, then exactly one owner — both unchanged and both still
         failing closed. It is the same judgement on a different subject, NOT a relaxation: an
         assertion naming no path and one naming a path two members changed each attribute nothing.
         The subject is deliberately kept OUT of `superseded_test_file` (see that scalar's note below).

    `superseded_test_file` carries the RESOLVED FULL PATH, never the ambiguous basename the failure was
    reported under: the row is read by an operator deciding a waive, and a basename would hand them
    back the same ambiguity gate 3 just refused to guess through. It is a SUMMARY of
    `superseded_assertions` and is written ONLY when it summarises correctly — one member can uniquely
    own pinned failures in several files, and in that case the scalar is WITHHELD rather than set to
    whichever path happened to be resolved last (see the tail of the body).

    REPORT-ONLY (AC3). Nothing here decides anything. The verdict string, `batch_size`, the rule-1 N=1
    clause, batch ineligibility (`_land_batch_ineligible_branches` reads the VERDICT, never these keys)
    and the land's own outcome are all untouched; the caller `_die`s exactly as before. With
    `assertions`/`_changed_paths`/`_test_files` absent this is a no-op, so every existing caller and
    probe stays byte-identical.
    """
    if not members or not assertions or _changed_paths is None or _test_files is None:
        return 0
    try:
        universe = [str(x).strip() for x in (_test_files() or []) if str(x).strip()]
    except Exception:                          # noqa: BLE001 — unreadable universe: attribute nothing
        return 0
    if not universe:
        return 0
    # basename -> the known paths carrying it. A list, not a last-writer-wins dict: gate 3's whole
    # point is that a basename with TWO paths must be detectable as ambiguous.
    by_base: "dict[str, list[str]]" = {}
    for path in universe:
        by_base.setdefault(path.rsplit("/", 1)[-1], []).append(path)   # git reports posix paths

    changed: "dict[int, set]" = {}
    for i, m in enumerate(members):
        try:
            changed[i] = {str(x).strip() for x in (_changed_paths(m) or []) if str(x).strip()}
        except Exception:                      # noqa: BLE001 — undiffable member: matches nothing
            changed[i] = set()

    marked = set()
    owned_paths: "dict[int, list[str]]" = {}
    for entry in assertions:
        text = str(entry)
        if not text.startswith(_LAND_PINNED_ENTRY_PREFIX):
            continue                           # gate 1 — candidate failure, not a pinned supersession
        core = text[len(_LAND_PINNED_ENTRY_PREFIX):]
        key, sep, assertion = core.partition(": ")
        if not sep or not key.strip() or not assertion.strip():
            continue
        if assertion.strip().startswith(_NO_ASSERTION_CAPTURED):
            continue                           # gate 2 — the entry names no assertion
        paths = by_base.get(key.strip(), [])
        owners = []
        if len(paths) == 1:                    # gate 3 — unknown or ambiguous key resolves nothing
            path = paths[0]
            owners = [i for i in range(len(members)) if path in changed.get(i, ())]
        if len(owners) == 1:
            # gate 4 satisfied on the TEST FILE — today's answer, first and unchanged.
            owner = members[owners[0]]
            if not isinstance(owner, dict):
                continue
            owner.setdefault("superseded_assertions", [])
            if core not in owner["superseded_assertions"]:
                owner["superseded_assertions"].append(core)
            _seen = owned_paths.setdefault(owners[0], [])
            if paths[0] not in _seen:
                _seen.append(paths[0])
            marked.add(owners[0])
            continue
        # ── gate 5 (T-11713) — THE SUBJECT ROUTE, reached ONLY when the test-file route above
        # attributed nothing. A member owns a failing pinned test today only if it CHANGED that test
        # FILE. Correct as far as it goes, and it is why T-11675's red went partly unowned: it added
        # one reader in `bin/lib/triage.py` and reddened a census test it never touched, so the
        # eviction declined and three branches were requeued for one member's defect.
        #
        # THIS IS THE SAME JUDGEMENT APPLIED TO A DIFFERENT SUBJECT, never a second authority. The
        # assertion's own text names a path; gate 3's unambiguous-resolution rule and gate 4's
        # exactly-one-owner rule are re-run over THAT path, both unchanged and both still failing
        # closed. Nothing here relaxes either: an unresolvable subject (the ordinary case — most
        # assertions name no path at all) and a subject two members changed BOTH attribute nothing,
        # exactly as a wrong eviction is worse than none — it removes an innocent branch and
        # re-verifies a tree that still contains the broken one.
        #
        # IT DOES NOT FEED `superseded_test_file`. That scalar is read by an operator deciding a
        # `--rebaseline` waive and means "the TEST FILE this member's change superseded"; a
        # `bin/lib/*.py` subject is not one, and writing it there would state something false in the
        # one field a reader trusts to be a test path. The association is carried by the entry in
        # `superseded_assertions`, which leads with its own reported key.
        subjects = _land_assertion_subject_paths(assertion)
        if len(subjects) != 1:
            continue                           # gate 3, on the subject — unnamed or ambiguous
        subj_owners = [i for i in range(len(members)) if subjects[0] in changed.get(i, ())]
        if len(subj_owners) != 1:
            continue                           # gate 4, on the subject — zero, or undecidable
        owner = members[subj_owners[0]]
        if not isinstance(owner, dict):
            continue
        owner.setdefault("superseded_assertions", [])
        if core not in owner["superseded_assertions"]:
            owner["superseded_assertions"].append(core)
        marked.add(subj_owners[0])
    # THE SCALAR IS ONLY WRITTEN WHEN IT IS TRUE (audit-post finding, absorbed mode-a 2026-08-18).
    # One member can uniquely own pinned failures in MORE THAN ONE test file. A scalar assigned inside
    # the loop above would have been overwritten by the LAST resolved path while `superseded_assertions`
    # listed entries from all of them — a row that names one file and evidences several, i.e. exactly
    # the reads-as-evidence-but-is-wrong failure this function exists to refuse. So the scalar is a
    # SUMMARY that is written ONLY when it summarises correctly (one distinct path) and is WITHHELD
    # otherwise. Nothing is lost when it is withheld: every entry in `superseded_assertions` still
    # leads with its own reported key, so the association is carried by the list itself and the row
    # under-claims rather than mis-states.
    for _i, _paths in owned_paths.items():
        if len(_paths) == 1:
            members[_i]["superseded_test_file"] = _paths[0]
    return len(marked)

def _land_attribution_line(rec: "dict | None", *, _land_ambient_yitc_overrides=None) -> str:
    """The one operator-facing line this record earns on the abort — or "" when there is nothing to
    say. Report-only: it is PREPENDED to a message whose gating, class and exit are unchanged.

    THE `main` ARM STATES ITS OWN BOUND (T-11488). Both arms of the paired re-run execute in THIS
    process's environment, so the comparison isolates the DIFF and NOT the environment: a red caused
    by a stray variable, locale or PATH that both arms shared reproduces on both sides BY
    CONSTRUCTION and arrives here as `outcome: main`. The evidence therefore supports "not
    attributable to this branch's diff" and does NOT support "main is broken". The line used to
    assert the stronger claim and then INSTRUCT — "Fix main (or wait for the fix to land)" — and on
    2026-08-23 two branches (T-11452, T-11416) aborted on exactly an ambient `YITC_VERIFY_TEST_TIMEOUT`
    while main was fine; one autonomous session recorded "needs the main-side fix to land" as its
    halt reason, so every later reader inherited a false lead. The cost of that wording is a
    PROPAGATED WRONG DIAGNOSIS, not one lost land.

    WHAT DID NOT CHANGE, AND MUST NOT. The `main` outcome and its `ATTRIBUTION: MAIN` token stay: a
    genuine main-side red is still NAMED as one, because attribution is useful and bounding a claim
    is not deleting the feature. Nothing here gates, waives or downgrades anything — the land aborts
    exactly as loudly as before."""
    outcome = str((rec or {}).get("outcome") or "undecidable")
    # T-11807 — a quarantined pair is attributed to NOBODY, and that is SAID rather than left silent.
    # It is printed on every outcome, and BEFORE the `undecidable` early-return below, because the
    # commonest quarantine case is a red made ENTIRELY of quarantined pairs — which is `undecidable`
    # by construction. Failing to silence there would reproduce exactly the defect T-11612 repaired
    # one surface over: a reader who cannot tell a declined attribution from a solo land.
    _q = [p for p in ((rec or {}).get("quarantined") or []) if str(p).strip()]
    _q_lead = ""
    if _q:
        _q_lead = ("ATTRIBUTION QUARANTINE: the failing assertion(s) below declare themselves "
                   "quarantined from attribution AT THEIR OWN SITE, and that declaration is present "
                   "at the merge-base — so it is not this branch's to make. They are attributed to "
                   "NOBODY and are excluded from any split below:\n"
                   + "\n".join(f"- {p}\n  declared removal condition: "
                                f"{_land_attribution_quarantine_reason(p)}" for p in _q)
                   + "\nTHE LAND STILL ABORTS ON THEM. A quarantine withholds BLAME, never the "
                     "failure — it says only that this red is not evidence about this branch's diff. "
                     "The removal condition above is the declared exit; when it is met, delete the "
                     "declaration.\n\n")
    if outcome not in _LAND_ATTRIBUTION_OUTCOMES or outcome == "undecidable":
        return _q_lead
    if outcome == "main":
        _amb = _land_ambient_yitc_overrides()
        _env_lead = ("  yitc-owned overrides set in this environment (names only): "
                     + ", ".join(_amb) + "\n") if _amb else \
                    ("  (no yitc-owned override is set in this environment, so a stray YITC_* "
                     "variable is not the cause here.)\n")
        return _q_lead + ("ATTRIBUTION: MAIN — i.e. NOT ATTRIBUTABLE TO THIS BRANCH'S DIFF. Every failing "
                "assertion below reproduces at the merge-base (main WITHOUT this branch's diff), "
                "so this red is NOT attributable to this branch's diff:\n- "
                + "\n- ".join(rec.get("at_main") or [])
                + "\nWHAT THIS DOES NOT SAY: both arms ran in THIS process's environment, so the "
                  "re-run compares DIFFS, never ENVIRONMENTS — a red caused by an environment both "
                  "arms shared reproduces on both sides by construction and lands here too. Rule "
                  "that out FIRST, then treat it as main's:\n"
                + _env_lead
                + "  then, if the environment is clean, fix main (or wait for the fix to land) and "
                  "re-land; this branch is unchanged.\n"
                  "The land still ABORTS — attribution names the cause, it never skips it.\n\n")
    if outcome == "branch":
        return _q_lead + ("ATTRIBUTION: THIS BRANCH. None of the failing assertions below reproduces at the "
                "merge-base (main WITHOUT this branch's diff), so this red is this branch's own.\n\n")
    return _q_lead + ("ATTRIBUTION: MIXED. Part of this red predates the branch and part does not.\n"
            "  reproduces at the merge-base (MAIN's):\n- " + "\n- ".join(rec.get("at_main") or [])
            + "\n  does NOT reproduce there (THIS BRANCH's):\n- "
            + "\n- ".join(rec.get("at_branch") or []) + "\n\n")

def _land_batch_attribution_line(members: "list[dict] | None", assertions: "list[str] | None",
                                branch: "str | None") -> str:
    """T-11496 — the operator-facing half of T-11259's per-member attribution: on a red BATCH abort,
    tell the member which failing assertions are a PEER's and which are its own. Returns "" when
    there is nothing new to say. Report-only and pure: it reads the marks already written onto the
    member records and touches nothing.

    THE DEFECT, MEASURED. `_land_attribute_failing_assertions` computes the split correctly and its
    own comment states the gap plainly — "computed once at the seam that HAS the answer, copied by
    the emitter, READ BY NOBODY IN THIS CARD". No reader was ever filed, so the answer reached
    `main`'s journal and never reached the person waiting on the abort. On 2026-08-24T06:51:24Z batch
    `bat-ba30cfefb8e9` (`task/T-11494` + `task/T-11352`) went red on six pinned assertions. The
    member rows carried the true split — four to T-11352, whose diff renamed a keyword-only seam
    parameter its peer had never touched, and two to T-11494. The ABORT MESSAGE T-11494's worker read
    listed all six with no split at all, because the other attribution surface (T-11464's
    `_land_attribution_line`) is `undecidable(pinned-entry)` for pinned entries BY DESIGN. The worker
    could account for two of six and escalated `blocked-on-land` at 06:54:18Z — correctly, under
    SPEC-0121's default-under-uncertainty. That escalation, and the ~64 minutes of land wall-clock
    around it, is the cost of the missing reader; the branch itself was innocent and landed clean.

    IT READS MARKS AND DERIVES NOTHING. Every entry it prints under a peer comes from that member's
    own `superseded_assertions`, written by four gates that all fail closed and that record NOTHING
    rather than guess. This function adds no gate of its own, so it cannot widen that judgement: an
    assertion nobody owns is printed as unattributed, never assigned to the nearest candidate.

    FAIL TOWARD SILENCE, NOT TOWARD ACCUSATION
    (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`). This is a signal about
    WHOSE change something was, so the wrong direction is naming an innocent peer: one false
    accusation and the whole line gets skimmed. Nothing below ever names a member the marks did not.

    AND A DECLINED ATTRIBUTION IS NOT SILENCE (T-11612). Failing toward silence was applied one step
    too widely: this function used to speak ONLY when some assertion was attributed to a PEER, so a
    batch the attribution DECLINED on returned "" — byte-identical to a solo land. Measured
    2026-08-26: batches dissolved twice in one shift leaving every member a `requeued-after-red-batch`
    row with `culprit=null` and `red_isolation=null`, and the cause was recoverable only from one
    worker's prose escalation. The reader of that abort cannot tell a signal about its own diff from
    one it inherited, and re-running the named test alone runs the CURRENT check against the CURRENT
    tree — a DIFFERENT pair from the last-green check over a candidate subject the pinned leg ran — so
    it passes and reads as environmental. A red that looks nondeterministic trains readers to discount
    reds. So an UNNAMED culprit is now SAID, in the same block and under its own heading.

    SAYING "UNNAMED" IS NOT AN ACCUSATION, which is why it does not violate the paragraph above: it
    names nobody, and it removes an inference (this is mine) rather than adding one. The one case
    that stays silent is the one where silence is CORRECT — every failing assertion attributed, and
    to THIS branch. A solo land (`len(members) < 2`) stays silent too: it has no batch question.

    IT NEVER SOFTENS THE ABORT. The land still fails, with the same class, the same full-output tail,
    the same `_pinned_hint` and the same exit. What the block adds is the one thing that block could
    not otherwise say: a peer's superseded assertion is that PEER's to declare on its own land, and
    is not this branch's to `--rebaseline-waive` — which is exactly the shortcut a mixed report
    tempts (SPEC-0077 §3a).

    THE PREFIX IS STRIPPED BEFORE MATCHING, because the two surfaces store the entry differently:
    the abort block carries the `[pinned/last-green] ` prefix and the marks carry the bare core (the
    same asymmetry `_land_red_batch_ineligible_members` already handles). Matching the prefixed form
    against the marks would find nothing and this function would be silently inert — the failure mode
    a presence-only test cannot see."""
    if not assertions or not members or len(members) < 2:
        return ""
    _own = str(branch or "")
    owner_of: "dict[str, str]" = {}
    for m in members:
        if not isinstance(m, dict):
            continue
        _b = str(m.get("branch") or "")
        for core in (m.get("superseded_assertions") or []):
            owner_of.setdefault(str(core), _b)
    # T-11612 — NO early return on an EMPTY mark set. An attribution that named nobody is the
    # DECLINE this block now has to say out loud; short-circuiting here was the whole silence.
    # Every assertion simply falls through to `unattributed` below, which is the truth.
    peers: "list[tuple[str, str]]" = []
    mine: "list[str]" = []
    unattributed: "list[str]" = []
    for entry in assertions:
        text = str(entry)
        core = text[len(_LAND_PINNED_ENTRY_PREFIX):] \
            if text.startswith(_LAND_PINNED_ENTRY_PREFIX) else text
        who = owner_of.get(core)
        if who is None:
            unattributed.append(text)
        elif who == _own:
            mine.append(text)
        else:
            peers.append((who, text))
    if not peers and not unattributed:
        # Nothing this abort does not already say. Every failing assertion IS attributed, and to THIS
        # branch — informationally identical to a solo land, and printing a block there would train
        # the reader to skim the one case that matters.
        return ""
    out = [f"BATCH ATTRIBUTION (SPEC-0184 rule 5 / T-11259 / T-11496 / T-11612): this land verified a "
           f"BATCH of {len(members)} branches, so the failing assertions below belong to the MERGED "
           f"tree and are NOT all this branch's."]
    if peers:
        out.append("  attributable to a PEER — NOT this branch's, and NOT yours to `--rebaseline-waive`:")
        for who, text in peers:
            out.append(f"  - [{who}] {text}")
    if mine:
        out.append(f"  attributable to THIS branch ({_own or '<unknown>'}):")
        out.extend(f"  - {t}" for t in mine)
    if unattributed:
        # T-11612 — SAY THE CULPRIT IS UNNAMED. The predecessor wording ("attributed to NO member")
        # reported the same fact and stopped there, and on the no-peer path this whole block was not
        # printed at all — so a declined attribution reached the reader as SILENCE, which is exactly
        # what a solo land looks like. Name the decline and both of its consequences.
        out.append("  CULPRIT UNNAMED — the attribution DECLINED on these (its four gates fail closed "
                   "and record nothing rather than guess, so NO member was named):")
        out.extend(f"  - {t}" for t in unattributed)
        out.append("  An UNNAMED culprit is NOT evidence the entry is this branch's. The batch could "
                   "not tell whose it is, so do not read the absence of a name as your own ownership, "
                   "and do not `--rebaseline-waive` it on the strength of that silence — a waive needs "
                   "the mechanical tie to YOUR declared behaviour change (SPEC-0077 §3a).")
    if peers:
        out.append("A peer entry is that peer's supersession to declare on ITS OWN land. Re-land when "
                   "the peer has landed or been dropped from the batch; if only peer entries are "
                   "listed above, this branch has nothing to fix.")
    return "\n".join(out) + "\n\n"

def _land_batch_engagement(repo_root: "Path | None", *, _read_ops=None,
                           ops_out: "list | None" = None, CONSUMER_OPS_CONTRACT=None) -> "tuple[bool, str]":
    """SPEC-0184 rule 2 — MAY this land batch at all? Returns `(engaged, reason)`.

    THE PREDICATE IS AUTHORSHIP, NEVER REPO IDENTITY. Nothing here asks "is this repo the kernel" —
    rule 1 forbids naming a repository, and an earlier draft that keyed on the project ops carrier
    alone self-disabled batching for the very repo whose pain motivated the mechanism. What is asked
    is who WROTE the verify this batch is about to run:

      * NO project-authored `verify.layers` (no `yitc-ops.yaml`, no `verify:` section, a
        SECTION-level waiver, or an empty layer list) ⇒ the verify is the KERNEL-AUTHORED pinned
        suite ⇒ ENGAGED with no declaration consulted anywhere. The author of that suite and the
        enforcer of this rule are the same party, so a separate assertion would be the kernel
        telling itself what it already knows.
      * a NON-EMPTY project-authored layer list ⇒ the kernel cannot reason about
        `bash scripts/verify-stack.sh`, so the project must DECLARE its layers combined-candidate
        safe: `verify.combined_candidate_safe: true` (SPEC-0152 rule 16 owns the field's name and
        shape; this function only enforces the consequence).

    FAIL-CLOSED, and the three failing shapes are NOT distinguished in EFFECT — absent, malformed
    (anything that is not the boolean `True`, including the STRING "true") and explicitly `false`
    all mean batches of one. Telling them apart is the defining spec's job; `reason` names which one
    it was for the reader, and nothing branches on it.

    An unreadable / unparseable carrier is likewise NOT engaged — the same posture
    `_consumer_tests_delegation` already takes for this carrier: never widen a gate on a file we
    could not read.
    """
    def _ops():
        if _read_ops is not None:
            try:
                return _read_ops()
            except Exception:  # noqa: BLE001 — an injected reader that fails is an unreadable carrier
                return "unreadable"
        if repo_root is None:
            return None
        try:
            p = Path(repo_root) / CONSUMER_OPS_CONTRACT
            # `state.load_ops` is the ONE ops-carrier read+parse idiom (SPEC-0093) — it RAISES on a
            # malformed carrier rather than swallowing to {}, which is exactly the fail-closed signal
            # this gate needs.
            return state.load_ops(p) if p.exists() else None
        except Exception:      # noqa: BLE001 — unreadable/malformed carrier: fail-closed below
            return "unreadable"
    ops = _ops()
    # T-11278: PUBLISH the mapping this ONE reader already parsed, so a sibling question about the
    # SAME carrier (which declared layers would run for a diff?) is answered without opening it a
    # second time. T-11281's guard forbids a new ops-carrier reader in this file, and it is right to:
    # a second read is the parallel path P5 forbids, and two reads of one carrier can disagree.
    # Out-parameter rather than a widened return, so every existing caller's 2-tuple unpack stands.
    if ops_out is not None and isinstance(ops, dict):
        ops_out.append(ops)
    if ops == "unreadable":
        return (False, "ops-carrier-unreadable")
    if not isinstance(ops, dict):
        return (True, "kernel-authored-verify")      # no carrier at all → the kernel's own suite
    ver = ops.get("verify")
    if not isinstance(ver, dict) or isinstance(ver.get("waiver"), dict):
        # No verify section, or the whole section waived — the declared layers do not run, so the
        # verify in force is the kernel-authored one.
        return (True, "kernel-authored-verify")
    layers = ver.get("layers")
    if not isinstance(layers, list) or not layers:
        return (True, "kernel-authored-verify")
    decl = ver.get("combined_candidate_safe")
    if decl is True:
        return (True, "project-declared-combined-candidate-safe")
    if decl is None:
        return (False, "project-authored-verify-undeclared")
    if decl is False:
        return (False, "project-authored-verify-declared-unsafe")
    return (False, "project-authored-verify-declaration-malformed")

def _land_batch_facts_with_self(facts: dict, self_branch: "str | None", *, attempt, no_tests) -> dict:
    """T-11278 — overlay the HEAD's own raw facts onto the journal-folded ones.

    The queue fold recovers `attempt`/`no_tests` from `waiting_for_*` heartbeats. A land that never
    WAITED emits none — and that is the HEAD by construction, since it holds the slot it would
    otherwise be waiting for. So the head, the one member guaranteed to pay, would read UNKNOWN and
    therefore non-paying, under-counting every batch by exactly one. Its own land knows both values
    as locals; this hands them over rather than asking the journal for something it never wrote.

    PURE, and the overlay is the head ONLY: every peer keeps the fold's answer, because a peer's
    locals are in another process and the journal is the only honest source for it."""
    out = dict(facts or {})
    br = str(self_branch or "").strip()
    if br:
        out[br] = {"attempt": attempt, "no_tests": bool(no_tests)}
    return out

def _land_batch_foreign_merges(branch: str, wt: "Path | None", main_ref: str = "main", *,
                               _run_git_cap=None) -> "list[dict]":
    """The commits on `branch`, not yet on `main_ref`, that merged ANOTHER branch into it — i.e. the
    peers a batch left behind. Returns `[{sha, merged_branch, subject}]`, oldest first.

    THE SHAPE IS THE MEASURED ONE, not a hand-picked stand-in: batching merges peers into the head
    member's own branch, which git records as `Merge branch '<peer>' into <head>` — exactly the two
    commits `task/T-11098` still carries (`7c1db2aad` / `5cd3567ae`, 2026-08-17).

    `Merge branch 'main' into <branch>` is EXCLUDED, and that exclusion is what keeps the read from
    crying wolf on every ordinary land: `_update_from_main` produces one on essentially every branch
    that ever fell behind. Merging `main` is this branch's own act of catching up; merging a PEER is
    something a batch did to it.

    Answers only what git can prove. An unreadable ref / git error returns `[]` — a read that cannot
    see is not evidence of contamination, and this surface must never manufacture a scare.
    """
    if not branch or wt is None or _run_git_cap is None:
        return []
    try:
        r = _run_git_cap(["log", "--merges", "--reverse", "--format=%H%x00%s",
                          f"{main_ref}..{branch}"], wt)
    except Exception:                          # noqa: BLE001 — an unanswered read reports nothing
        return []
    if getattr(r, "returncode", 1) != 0:
        return []
    out = []
    for line in (getattr(r, "stdout", "") or "").splitlines():
        sha, _, subject = line.partition("\x00")
        m = _LAND_FOREIGN_MERGE_RE.match(subject.strip())
        if not m:
            continue
        merged = m.group(1)
        if merged == "main" or merged == branch:
            continue
        out.append({"sha": sha.strip(), "merged_branch": merged, "subject": subject.strip()})
    return out

def _land_batch_formation_ids(members: "list[dict]", main_wt: Path, merged_base: "str | None", *,
                              W: "Path | None" = None, _run_git_cap, _pinned_baseline_identity=None) -> dict:
    """T-11517 — resolve, AT ONE INSTANT, the THREE facts of a formation decision that become
    UNRECOVERABLE afterwards. Returns `{"member_tips", "base", "pinned_baseline"}`.

    WHY A RECORD AND NOT A DERIVATION — and this is a RETRACTION, which is why it is load-bearing.
    On 2026-08-25 two batches were read as having spent a slot on an already-CONTAINED member
    (bat-3237a5a3df33 at 09:13:54Z, bat-afec2e7ba444 at 09:53:23Z). BOTH READINGS WERE WRONG:
    formation itself merges members onto the head member's branch (T-11193/T-11226), and the reflog
    puts each merge exactly ONE SECOND after its formation row. So every observation available at
    that seam — the row, the branch tips, git ancestry, merge-tree — shows POST-merge state, and
    post-merge containment is INDISTINGUISHABLE from pre-existing containment. The error was caught
    only because both branches still existed and a machine-local reflog had not expired; the reflog
    is not in the journal, expires, and is per-checkout. Hence: RECORD WHAT BECOMES UNRECOVERABLE.

    THIS CALL MUST STAY ABOVE `_land_merge_members_in_queue_order`. That position IS the claim — the
    tips it resolves are PRE-merge, which is the only moment they are the fact the decision was made
    on. A sibling that moves this below the merge records the merge's own output and silently
    re-creates the exact confusion above.

    THE THREE, and why each earns a field under RECORD-WHAT-BECOMES-UNRECOVERABLE (derive the rest):
      * `member_tips` — `{branch, task, tip}` per member. `land` DELETES the branch, so after the
        fact the name the row already kept resolves to nothing. A branch that does not resolve is
        recorded with `tip: null` rather than DROPPED: an unresolvable member is itself the fact.
      * `base`        — the `main` commit this batch was formed on. A tip without its base is half a
        fact: main advances continuously, so the pairing is true only at this instant, and without
        it neither per-member distance nor what the merge had to do is answerable.
      * `pinned_baseline` — `_pinned_baseline_identity`, the pinned last-green surface in force. The
        pinned entry is the single largest killer of batches (37 of 57 undecidable isolations,
        T-11515) and the baseline it judges against moves on every rebaseline.
    DELIBERATELY NOT FIELDS, because they are DERIVABLE from those three: containment between
    members, file overlap, per-member distance from main. `batch_id` is out of scope — it was absent
    only on 2026-08-18..20 rows and stopped going missing on its own (T-11331 minted it).

    Pure over the injected reader; no journal, no state, no mutation. Every read is fail-soft: a git
    failure yields a null id, never an exception inside a land."""
    tips = []
    for m in (members or ()):
        br = str((m or {}).get("branch") or "")
        tip = None
        if br:
            try:
                r = _run_git_cap(["rev-parse", "--verify", "--quiet", f"{br}^{{commit}}"], main_wt)
                if r.returncode == 0 and (r.stdout or "").strip():
                    tip = (r.stdout or "").strip()
            except Exception:
                tip = None
        tips.append({"branch": br, "task": (m or {}).get("task"), "tip": tip})
    base = str(merged_base or "").strip() or None
    pinned = None
    if base and W is not None:
        pinned = _pinned_baseline_identity(W, base, _run_git_cap=_run_git_cap)
    return {"member_tips": tips, "base": base, "pinned_baseline": pinned}

def _land_verdict_settled_nothing(data: "dict | None", unowned_red: "set | None") -> bool:
    """T-11710 (SPEC-0184 rule 4) — did this individual verdict RE-OBSERVE the batch's own UNOWNED
    red, i.e. settle nothing about why the batch was red? PURE: takes two payloads, returns a bool,
    touches no disk and journals nothing.

    THE DEFECT THIS ANSWERS, MEASURED ROW BY ROW ON THIS REPO'S JOURNAL (2026-08-27). Rule 4's
    anti-livelock guarantee is that a red batch may NEVER be re-formed identically: its members are
    marked single-verify for ONE ROUND so each reaches an INDIVIDUAL verdict, and the mark is
    discharged by that verdict. When the red is owned by NO member — it lives in the MERGED tree, or
    on `main`, or in a pinned entry the oracle cannot reach — every member's individual verdict fails
    on the SAME assertions, resolves nothing, and discharges its own mark. The composition then
    re-forms and fails identically. `task/T-11676` was requeued at 12:09:10Z carrying
    `red_assertions` {t11444, t11417}; its own solo land ran a full 681s verify and aborted at
    13:41:05Z on EXACTLY {t11444, t11417} — and that abort cleared its round. `task/T-11673` went
    round the same loop four times (requeued 10:52:19Z, 12:09:10Z, 12:48:37Z, 13:28:13Z), and
    `task/T-11676` and `task/T-11671` waited 8362s and 2468s WITHOUT EVER REACHING VERIFY —
    `task/T-11676` behind `main` by ZERO commits. Nobody was at fault: once the composition CHANGED,
    `task/T-11671` and `task/T-11673` landed clean at 14:20:41Z with no fix from anyone.

    THIS IS THE T-11256 QUALIFIER ONE LAYER DEEPER, NOT A SECOND MECHANISM. T-11256 found the mark
    "discharged by an event that resolved nothing" — an abort raised before the suite ever ran — and
    demanded positive evidence that the individual leg RAN. That is necessary and not sufficient: a
    leg that ran, and then re-observed the very assertions the batch was requeued for, resolved
    exactly as little. Both are rule 4's own text ("every member reaches an INDIVIDUAL verdict on its
    own candidate leg") being read, not a new obligation layered on it.

    IT IS NOT A QUARANTINE, and that bound is what keeps it inside rule 4. The branch is not blocked
    and is not penalised: it is verified ALONE, which is the CHEAPEST honest thing left to do with it
    — an ineligible head forms a batch of one, an ineligible peer is dropped before the cap — so it
    reaches its OWN terminal land outcome on every pass instead of being dragged round inside a batch
    that cannot land. The mark self-clears on the FIRST individual verdict that says anything new: a
    green land, or a leg that fails on a different assertion. Nothing here waits for the red to clear.

    TRUE ONLY ON A POSITIVE, MEASURED CONDITION — every other input returns False, i.e. CLEARS exactly
    as today. That direction is inherited deliberately from `_land_completed_verify_ran`'s own
    asymmetry: a wrongly-cleared mark costs ONE repeated batch (which dissolves again and re-marks
    properly), while a wrongly-KEPT one on bad data would turn "one round, not a quarantine" into
    precisely the quarantine rule 4 forbids. So an absent `failing_assertions`, an empty one, a
    non-list, an empty `unowned_red`, a green land — each answers False.

    OVERLAP, NOT CONTAINMENT, and the distinction is load-bearing rather than stylistic. A solo leg
    that failed on the batch's assertion PLUS one of its own has still not settled the batch's
    assertion, and containment would let exactly that row discharge the mark: `task/T-11673`'s
    12:48:37Z leg failed on {t11444, t11524, t11417} against a requeue of {t11444, t11417} — a
    superset, cleared under containment — and the batch re-formed at 13:19 and died again at
    13:28:13Z. One assertion the member cannot answer for is enough.

    WHAT `unowned_red` MEANS is settled by the CALLER, which is the only place the requeue row and its
    decline record are both in hand; this function is deliberately blind to it and merely intersects.
    """
    if not isinstance(data, dict) or not unowned_red:
        return False
    failing = data.get("failing_assertions")
    if not isinstance(failing, (list, tuple)) or not failing:
        return False
    return any(str(a) in unowned_red for a in failing)

def _land_horizon_rows(events_path, token, *, horizon_s, label, truncated_out=None,
                       now=None, base_bytes=None, max_bytes=None, _scan=None,
                       _segment_scan=None):
    """T-11816 — the formation readers' ONE journal read: a window sized by the answer's own lifetime,
    plus the loud report when it could not reach that lifetime.

    WHY THE LOUDNESS LIVES HERE AND NOT IN THE PRIMITIVE. `journal.tail_scan_events_covering` answers
    a mechanical question — did the window reach back this far — and must stay free of any policy
    about what a shortfall MEANS. What it means is this module's: every reader below fails OPEN, so a
    shortfall does not change the answer, it changes how much that answer is worth. Before this card
    those two were the same empty set, which is the whole reason the defect ran unnoticed from the
    read's introduction until T-11814 went looking. Now a shortfall prints ONE named line naming the
    reader, the horizon it could not cover and how far it actually reached, and — when a sink is given
    — records the same fact for a caller that wants to journal it. `truncated_out` is the
    `excluded_out` sink shape this module already uses (T-11219): no new store, no new event type, no
    new entity.

    STDERR, NOT AN EVENT, AND THAT IS DELIBERATE. These readers are PURE and are called from inside
    formation, where emitting would mean writing to the very journal being read; a reader that appends
    while deciding is how a bounded read becomes its own moving target. The line goes where the land's
    other formation diagnostics already go.

    Returns the rows. Fail-open is UNCHANGED and stays each caller's: this raises nothing new, and on
    any failure inside the scan the caller's own `except` sees exactly what it saw before.

    T-11924 — THE ARCHIVE BRANCH, TAKEN WHEN AND ONLY WHEN THE LIVE SEGMENT CANNOT COVER THE HORIZON.
    T-11904 made the shortfall LOUD and this function said so in its own words: a horizon reaching
    past the live window is *"a DEFECT under SPEC-0190 rule 4 (a horizon reaching past the live window
    takes the archive branch)"*. It then returned the truncated rows anyway, because no branch
    existed. It does now: on `covered False` the read continues backwards through the ARCHIVE
    segments via `journal.archive_scan_events_covering`, and the loud line fires only when NEITHER
    live nor archive can reach the declared horizon.

    THE HARM THIS CLOSES IS NOT THE MESSAGE. `_land_pinned_supersession_branches` declares a 7-day
    LIFETIME for a pinned-supersession flag, and T-11870's argument that read and rule are THE SAME
    NUMBER holds only while the read reaches that lifetime. On kupiclub it did not — the live segment
    reached back to 2026-08-26T17:28:41Z against the 7-day declaration, twice in one day (X-1202,
    X-1204) — so an arming row that had rotated into archive was invisible and the branch it should
    have excluded rode the batch.

    THE COVERED CASE COSTS EXACTLY WHAT IT COSTS TODAY. The archive collaborator is not called at all
    when the live read covers, so an ordinary land on an ordinary journal pays one unchanged live read
    against an unchanged `base_bytes` — no ceiling was raised, which T-11904 established only
    postpones the same decay. `_segment_scan` mirrors `_scan` as the injection seam.

    WHAT DOES NOT MOVE: no horizon value, nothing about what any caller ADMITS or excludes, and the
    fail-open direction (an unreadable journal still yields the caller's empty set) — the archive walk
    fails open the same way and contributes whatever it managed to read.
    """
    scan = _scan or journal_mod.tail_scan_events_covering
    seg_scan = _segment_scan or journal_mod.archive_scan_events_covering
    base = _LAND_BATCH_INELIGIBLE_TAIL_BYTES if base_bytes is None else base_bytes
    spend: list = []
    rows, covered = scan(
        events_path, token, horizon_s=horizon_s, now=now,
        base_bytes=base,
        max_bytes=max_bytes, spend_out=spend)
    bytes_read = int(spend[0]) if spend else None
    took_archive = False
    if not covered:
        # SPEC-0190 rule 4 — the horizon outran the live segment, so the read continues into the
        # ARCHIVE rather than reporting a truncated answer. Older rows precede the live ones: one
        # logical history, partition-stable order (rule 5).
        took_archive = True
        arch_spend: list = []
        try:
            older, covered = seg_scan(
                events_path, token, horizon_s=horizon_s, now=now, base_bytes=base,
                max_bytes=max_bytes, spend_out=arch_spend)
        except Exception:                  # noqa: BLE001 — fail-open, exactly as the live read does
            older = []
        if older:
            rows = list(older) + list(rows or ())
        if arch_spend:
            bytes_read = int(arch_spend[0]) + (bytes_read or 0)
    if not covered:
        reached = None
        for ev in rows or ():
            if isinstance(ev, dict) and ev.get("ts"):
                reached = ev.get("ts")
                break
        record = {"reader": label, "token": token, "horizon_s": int(horizon_s),
                  "bytes_read": bytes_read,
                  "archive_branch_taken": took_archive,
                  "oldest_row_reached": reached}
        if isinstance(truncated_out, list):
            truncated_out.append(record)
        print(f"yitc-v2: land formation: {label}: the journal read could NOT cover its declared "
              f"{int(horizon_s)}s horizon — it read {record['bytes_read']} bytes back through the "
              f"live segment AND the archive segments beside it (SPEC-0190 rule 4 archive branch: "
              f"{'TAKEN' if took_archive else 'not taken'}; oldest row reached: "
              f"{reached or 'none'}) and the history it declared is OLDER than the whole journal "
              f"on disk; this answer is TRUNCATED, not empty, and an ineligibility older than that "
              f"is invisible to it. This is a DEFECT — the read is no longer live-segment-bound "
              f"(T-11924 took the archive branch), so the declared horizon now outruns the ENTIRE "
              f"retained journal, not routine output",
              file=sys.stderr, flush=True)
    return rows


def _land_batch_ineligible_branches(events_path: "Path | None", *,
                                    _rows: "list | None" = None, _land_completed_verify_ran=None,
                                    main_wt: "Path | None" = None,
                                    branches=None, _queue_jump_reason=None,
                                    truncated_out: "list | None" = None,
                                    now: "float | None" = None) -> "set[str]":
    """SPEC-0184 rules 4 + 9 — the branches that are batch-INELIGIBLE right now, i.e. must be verified
    ALONE on their next attempt. Rule 4 is the anti-LIVELOCK rule, and it is the whole reason
    dissolution is self-correcting rather than a loop.

    ONE PREDICATE, THREE SOURCES, DELIBERATELY DIFFERENT LIFETIMES (T-11707, owner decision
    2026-08-27; T-11817). A branch is ineligible if ANY holds:
      * the RED-BATCH source (rule 4, below) — ONE ROUND, self-clearing, and the clearing signal is
        the member's own individual verdict;
      * the QUEUE-JUMP MARK source (rule 9) — a candidate whose card carries a LIVE `queue_jump`
        mark. PERSISTENT: it holds while the mark holds and ends when the mark ends, which per rule 9
        safeguard (b) is when the card goes terminal — derived, never swept.
      * the RIDE-COUNT source (rule 13, T-11817) — a branch NAMED in
        `_LAND_RIDES_WITHOUT_LANDING_SOLO_THRESHOLD` or more MULTI-MEMBER `land_batch_formed` rows
        since its last completed verify. SELF-CLEARING like rule 4 and by rule 4's OWN signal: the
        count is RESET by the branch's next `land_completed` whose verify RAN. See the ride-count
        paragraphs below.
      * the REFUTED-BLAME source (rule 14, T-11568) — a peer RELEASED UNPENALISED on a
        `head-is-culprit` red whose HEAD then LANDED OK ALONE, i.e. the blame the release rested on
        was REFUTED. ONE ROUND, and it enters `state` itself rather than being unioned after,
        because its lifetime IS rule 4's: the same one round, cleared by the same individual
        verdict. See the refuted-blame paragraphs below.
    The mark source is NOT a second CARRIER and writes NOTHING: there is no stored solo field to set,
    and emitting a synthetic `requeued-after-red-batch` row to fake one would put a red batch that
    never happened into an append-only history. It is a second SOURCE feeding the ONE existing
    predicate, so every consumer of batch-ineligibility keeps working unchanged.

    THE COST, RECORDED RATHER THAN REDISCOVERED AS AN OBJECTION. A marked head can no longer
    amortise: a green batch of 4 headed by a marked branch forfeits 3 passes. On 2026-08-27 marked
    branches headed two batches (bat-6e225d5f2ee4 n=2, bat-0f20f334cc5c n=4) and BOTH went red, so
    nothing was actually forfeited in either — but two observations are not proof that a marked head
    never carries a green batch. The owner weighed that trade and accepted it: marked cards are rare
    by construction (an opt-in field, rule 9), and making an urgent queue-FIXING land wait inside a
    batch is worse than the time its peers lose landing separately.

    WHY THE MARK SOURCE READS THE CANDIDATES AND NOT THE CORPUS. It is enumerated from `branches` —
    the candidates the caller already holds — never by globbing the whole `tasks/` dir, which would
    put ~1900 YAML parses on every formation. That is the `_land_supersession_marked_branches` shape
    (main_wt + branches -> subset) reused, and it leaves `_land_queue_jump_reason`'s own contract
    (branch -> reason, one glob + one parse) exactly as wide as it already was. The reader is
    INJECTED rather than imported because it lives in `worktree.py`, which imports this module.

    ABSENT ARGUMENTS ANSWER BYTE-IDENTICALLY TO BEFORE. With no `main_wt`, no `branches` or no
    injected reader, this is the pure rule-4 predicate it has always been. That is what lets the
    `_batch_ineligible_at_entry` snapshot in `cmd_land` stay the red-batch-only read it must be: that
    snapshot decides whether an abort writes a CLEARING row, and the mark source is cleared by no
    verdict, so feeding it there would emit a clearing row for something nothing clears.

    WHY "RETURN THEM TO THE QUEUE" IS NOT ENOUGH. After a red batch dissolves, the same members are
    still queued together, so the next slot re-forms the SAME batch, which fails identically —
    forever, learning nothing. A REPEATED IDENTICAL BATCH IS THE FAILURE, NOT A RETRY. Marking the
    members single-verify for one round terminates the loop BY CONSTRUCTION: every member reaches an
    INDIVIDUAL verdict on its own candidate leg, the genuinely red change fails alone and is caught,
    and a PEER-DEPENDENT red — green for every member alone — passes alone and lands. The queue makes
    progress even when nothing about the red is understood, which is exactly why ISOLATING the culprit
    is a cost optimisation ON TOP of this rule rather than a correctness prerequisite. T-11335 built
    that optimisation (`_land_red_isolation_probe`), and THIS function is what bounds it: an evicted
    culprit keeps the `requeued-after-red-batch` verdict precisely so this read still marks it, so an
    isolation can never produce a batch that re-forms identically. (T-11195, the bisection card this
    paragraph used to point at, is closed wont-do — superseded in role by T-11335.)

    ONE ROUND, NOT A QUARANTINE, AND THE CLEARING SIGNAL IS THE INDIVIDUAL VERDICT ITSELF. A branch
    is ineligible iff its LATEST `land_member_verdict` is `requeued-after-red-batch` AND no
    `land_completed` WHOSE VERIFY ACTUALLY RAN (`_land_completed_verify_ran` — T-11256) for that
    branch follows it. Such a `land_completed` IS the individual verdict
    rule 4 requires — at N=1 the land's own row is the member's verdict in full (rule 5's N=1 clause),
    so no new carrier and no new store is needed to express "it has had its solo pass". A member
    evicted for a PEER's red did nothing wrong and must not be disadvantaged beyond that one pass.

    THE RIDE COUNT (SPEC-0184 rule 13, T-11817) — IT COUNTS, IT DOES NOT JUDGE. Every source above,
    and every sibling source formation consults (rule 12's exact red set, a declared rebaseline, a
    supersession mark, a dirty worktree), keys on a VERDICT or a MARK. All of them are silent BY
    CONSTRUCTION in the one case this arm exists for: a red batch whose attribution DECLINES to name
    anyone — measured 2026-08-28, `bat-f2749263764c` reddened with every member requeued, the head
    itself unaccounted, and NO name produced. A COUNT needs no name, so it reaches that case. It reads
    `land_batch_formed`, a row that carries no verdict and no attribution at all; an implementation
    that needed a name would have reproduced the gap under a new name.

    ONE RULE, BOTH SIDES. For a branch that keeps breaking batches this RESTRAINS — it stops burning
    peers. For an innocent eternal passenger it RELEASES: `task/T-11790` rode six batches, was never at
    fault, and landed green on its first solo attempt. One predicate frees one and constrains the other.

    A RIDE IS FORMATION INTO A MULTI-MEMBER BATCH, not "paid a verify as a member". Formation is the
    instant a branch's fate is coupled to its peers', which is what this bounds. The alternative was
    considered and rejected on blast radius: `land_batch_formed` carries `paying_members` as a COUNT,
    never a SET, so per-member payment is not derivable from anything journalled today and would need
    new attribution and a new field. A SOLO formation (`members: 1`, the T-11235 fork) is NEVER a ride,
    so the routing this arm produces can never feed itself.

    IT RESETS; IT DOES NOT MARK — and that is not a stylistic choice. The trigger reads HISTORY and a
    count of past rides can only GROW, so a mark that did not clear would be PERMANENT by construction.
    Solo is the SLOWEST lane (a full verify alone: 8-12 min measured 2026-08-28, against 3-9 s as a
    rider in a green batch), so an unclearing mark would condemn an innocent branch to the expensive
    lane for OTHER branches' defects — `task/T-11790` would have been marked on ride three and never
    released — and every permanently marked branch LEAVES the shared batches, so batching would shrink
    toward nothing while still appearing to run. So the count is zeroed by the branch's own
    `land_completed` WHOSE VERIFY RAN, which is rule 4's clearing signal reused unchanged: once the solo
    attempt COMPLETES, whatever its outcome, the branch is an ordinary candidate again.
    (And by the branch's own `landed` member verdict, since a green batch gives its PEERS only that row
    and its HEAD the `land_completed` — "rides WITHOUT LANDING" means a landing zeroes the count too.)

    IT COSTS NO EXTRA READ, AND INHERITS THE HONEST WINDOW. `land_` is already the SUPERSET prescan
    token and `land_batch_formed` carries it, so those rows are in `rows` today and were simply not
    looked at; the fold below is the SAME single chronological pass. That also settles the window
    question T-11816 reshaped: the count rides the LIFETIME-sized `_land_horizon_rows` read, never a
    byte-bounded tail. Under the former 512KB tail a first ride 630833 bytes from EOF was invisible, so
    a counter built there would have reported two rides forever on exactly the busy days this rule
    exists for — a counter that appears to work and counts nothing.

    THE REFUTED BLAME (SPEC-0184 rule 14, T-11568) — IT FIRES ON THE HEAD'S OWN VERDICT, NEVER ON
    THE RELEASE. When a red batch names the head and releases every peer, those peers are released
    UNPENALISED (`batch_ineligible: False`) on the premise that the head owns the red and they are
    innocent by construction. MEASURED, that premise fails a third of the time: 32/48 = 66.7% coarse
    confirmation over 2026-08-22T06:00:00Z..2026-08-29T00:00:00Z (48 blame events deduped by
    batch_id, 40 heads, 51 peers, 0 unresolved), and 11/30 = 36.7% on the AC1-literal same-assertion
    reading over the carried-verdict population. In the 16 coarse refutations the head passed ALONE,
    so the red came from a peer or from the combination — and the set containing it went back to the
    queue unmarked. That is not theoretical: the fold enumerates 15 recurrence pairs by property,
    across 7 distinct branches, where a peer released unpenalised was blamed itself by the SAME
    assertion within the hour (`T-11435`, `T-11580`, `T-11614`, `T-11589`, `T-11618` — released five
    times before its own turn — `T-11578`, `T-11733`). HONEST BOUND: only 10 of those 15 follow a
    REFUTED blame, so this arm would have marked 10 and left 5 alone — the 5 followed a CONFIRMED
    blame, which it deliberately does not reach, because reaching them means marking on suspicion.
    Full derivation: `dev-utilities/head-blame-refutation-T-11568.md`.

    WHY THE MARK IS CONDITIONAL AND THE DISSOLVE PATH'S IS NOT — the same 66.7% that justifies this
    arm FORBIDS the obvious version of it. Marking every released peer the way a dissolve marks its
    members would tax 32 innocent peer-sets to catch 16 guilty ones. The dissolve path's blanket
    one-round mark is justified for a reason that does NOT transfer: there NO attribution was made at
    all, so there is no innocence to protect. Here an attribution WAS made and the head's own solo
    run either upholds it or overturns it, so the rule consumes that verdict instead of guessing:
    it fires in the 16 and never in the 32. Releasing unpenalised on a CONFIRMED blame stays
    deliberate and correct, exactly as before this arm existed.

    THE HEAD'S FIRST OWN LAND AT-OR-AFTER THE BLAME DECIDES, and the three outcomes are NOT two.
    `ok` REFUTES (the head was fine alone) and marks the peers. An `abort` of class `verify-failed`
    CONFIRMS and marks NOBODY. ANY OTHER abort class — a rebaseline refusal, a stale-diff preflight,
    a merge conflict — is UNRESOLVED: it says nothing about whether the head's code was red, so the
    peers stay PENDING and nothing is decided on it. Collapsing that third case into either answer
    would mark or absolve on evidence that settled nothing, the same defect T-11256 removed from the
    clearing signal one arm below.

    RETROACTIVE, BECAUSE HOLDING THE RELEASE WAS COSTED AND IS WORSE. The peers are released BEFORE
    the head's solo run concludes, so the mark cannot be written at release time; the two shapes were
    measured over the window above rather than argued. HOLDING the release until the head resolves
    costs 2603 peer-minutes across 109 peers in all 48 blames (median gap 7.9 min, max 155.9) — and
    two thirds of that is paid in the CONFIRMED cases where the mark never fires — plus a new held
    state, against rule 1's stateless queue-driven formation. RETROACTIVE (this) costs nothing at
    release time and no new row: the mark simply is not there yet if the peer re-forms inside the
    gap, measured at 23 such formations across the 16 refuted blames' 38 peers. 23 late rounds in the
    refuted cases only beats 2603 peer-minutes paid in every case, so the mark is DERIVED HERE at the
    next formation from rows that already exist.

    IT ENTERS `state`, UNLIKE RULES 9 AND 13, and the difference is lifetime not style. Those two are
    unioned AFTER the fold precisely because `state`'s `land_completed` arm would clear them in one
    round and their lifetimes are longer. This mark's lifetime IS one round — the peer's own next
    individual verdict, rule 4's signal unchanged — so `state` is the correct home and the clearing
    arms below need no new code at all. Writing a second clearing path for an identical lifetime
    would be the duplication, not the reuse.

    FAIL-OPEN TO THE EMPTY SET, always. An unreadable journal, a missing path, an unparseable line:
    every one of them yields "nobody is ineligible", i.e. ordinary formation. That is the direction
    matched to the cost — a missed ineligibility costs one repeated batch (which then dissolves again
    and marks them properly), while a spurious one would permanently shrink batches on bad data.
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return set()
        try:
            p = Path(events_path)
            if not p.exists():
                return set()
            # `land_` is the SUPERSET prescan token (the reader takes ONE token and the parsed type
            # check below decides membership — the same contract `_land_queue_at_slot_free` uses with
            # `waiting_for_`). Both rows this read needs — `land_member_verdict` and
            # `land_completed` — carry it, and any other `land_*` line is rejected on the parsed type.
            # T-11816 — the window is sized by the MARK'S OWN LIFETIME, not by a byte constant.
            # See `_land_horizon_rows`; `land_` stays the SUPERSET prescan token and the parsed type
            # check below still decides membership, so nothing about what this read ADMITS moves.
            rows = _land_horizon_rows(
                p, "land_", horizon_s=_LAND_INELIGIBILITY_HORIZON_SEC,
                label="batch-ineligibility (SPEC-0184 rules 4+9)",
                truncated_out=truncated_out, now=now)
        except Exception:                      # noqa: BLE001 — fail-open: ordinary formation
            return set()
    state: "dict[str, bool]" = {}
    # T-11710 — per branch, the assertions its LATEST marking requeue could not name an owner for.
    # Folded in the SAME single pass as `state` (the journal is append-only, so the newest row
    # governs both) and consulted only by the `land_completed` arm below.
    unowned: "dict[str, set]" = {}
    # T-11710 — per branch, the assertions its LATEST marking requeue could not name an owner for.
    # T-11817 (rule 13) — per branch, multi-member batch formations since its last completed verify.
    # Folded in the SAME chronological pass for the same reason: the journal is append-only, so a row
    # is applied exactly once and in order, and no second read can drift from this one.
    rides: "dict[str, int]" = {}
    # T-11568 (rule 14) — PEER -> the HEAD whose own solo verdict its fate is still waiting on,
    # after that head blamed a red batch and this peer was released UNPENALISED. Folded in the SAME
    # chronological pass as everything above, which is what makes "the head's FIRST own land
    # AT-OR-AFTER the blame" fall out of the ordering rather than needing a second lookup or any
    # timestamp arithmetic: in an append-only journal read in order it is simply the first
    # `land_completed` row for that head reached after the registration. Keyed by PEER and not by
    # head because both of the things that end a registration — the head resolving, and the peer
    # serving its round some other way — are stated most directly that way round.
    #
    # THE VALUE IS A SET OF HEADS, NOT ONE HEAD, and that is load-bearing rather than defensive: a
    # peer is routinely released by SEVERAL blames before ANY of their heads resolves. Measured over
    # 2026-08-22..2026-08-29, `task/T-11618` was released unpenalised by FIVE different heads before
    # its own turn came. A single-head registration would let each release OVERWRITE the last, so a
    # refutation by any but the newest head would mark nobody — the rule would go quiet in exactly
    # the pile-up case the livelock is made of. ANY ONE refutation is enough (each blame is a
    # separate claim about who owned the red, and one being overturned is what this rule fires on),
    # so a head is DISCARDED from the set when its own run CONFIRMS it, and the peer is forgotten
    # only once every blame against it has been confirmed.
    pending: "dict[str, set]" = {}
    for ev in rows or []:
        if not isinstance(ev, dict):
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        if not data:
            continue
        if ev.get("type") == "land_batch_formed":
            # THE RIDE ARM (rule 13) — handled BEFORE the `branch` guard below, because this row names
            # its members in `branches` (plural) and carries no `branch` key at all. MULTI-MEMBER ONLY:
            # a solo formation is not a ride, which is what stops the routing feeding itself. A row
            # whose shape is not the expected one contributes nothing (fail-open, as everywhere here).
            try:
                _n = int(data.get("members") or 0)
            except Exception:              # noqa: BLE001 — fail-open: a malformed row is no ride
                _n = 0
            if _n > 1:
                for _b in (data.get("branches") or ()):
                    _b = str(_b or "").strip()
                    if _b:
                        rides[_b] = rides.get(_b, 0) + 1
            continue
        br = str(data.get("branch") or "").strip()
        if not br:
            continue
        if ev.get("type") == "land_member_verdict":
            # LAST WRITE WINS, over the whole vocabulary — not just over the requeue value. A member
            # requeued in one round and then, say, evicted-for-conflict in the next has had a newer
            # outcome recorded, and reading only the requeue rows would keep it ineligible on a
            # verdict history has moved past. The journal is append-only, so the newest row governs.
            # T-11272: and the requeue must actually have MARKED this member. A dissolve that could
            # attribute the whole red names its culprits and stamps `batch_ineligible: False` on the
            # rest, who are then requeued WITHOUT the one-round penalty — they did nothing and no
            # evidence says otherwise. ABSENT MEANS INELIGIBLE, so every row written before T-11272
            # and every dissolve that could not attribute its red reads exactly as it always did.
            state[br] = (data.get("verdict") == "requeued-after-red-batch"
                         and data.get("batch_ineligible") is not False)
            # RULE 13's OTHER CLEARING SIGNAL — the branch LANDED (T-11817). A green batch gives its
            # PEERS a `land_member_verdict` of `landed` and only its HEAD a `land_completed`, so
            # resetting on `land_completed` alone would leave a landed peer's rides standing. The
            # rule's own text is "rides WITHOUT LANDING", so a landing zeroes the count. This reads
            # the fact THAT the member landed, never a culprit or an attribution — AC2's bound is on
            # what makes the count FIRE, and nothing here needs a name.
            if data.get("verdict") == "landed":
                rides.pop(br, None)
            # RULE 14's REGISTRATION (T-11568). A release row is this branch's own verdict, so it
            # runs in the same arm and AFTER the `state[br]` assignment above — which has just set
            # this peer FALSE (`batch_ineligible is False`), the correct state until and unless the
            # head's own run refutes the blame. Registering here rather than at the head's land is
            # what makes the reading "the head's FIRST own land AT-OR-AFTER the blame": rows before
            # the blame cannot see a registration that does not exist yet.
            _rel = data.get("released_from_batch")
            if (isinstance(_rel, dict)
                    and str(_rel.get("reason") or "") == _LAND_PEER_RELEASE_REASON
                    and data.get("batch_ineligible") is False):
                _head = str(_rel.get("head") or "").strip()
                if _head and _head != br:
                    pending.setdefault(br, set()).add(_head)
            elif data.get("verdict") == "landed":
                # The peer LANDED, so there is no next round of its own to constrain and nothing
                # for a later refutation to mark. Forget it rather than carry a registration whose
                # subject has left the queue — the same reason the ride count zeroes here.
                pending.pop(br, None)
            # T-11710 — REMEMBER WHAT THIS REQUEUE COULD NOT ANSWER FOR. When the row MARKS the
            # branch AND the dissolve's own decline record says NO MEMBER was named the owner of the
            # red (`_LAND_RED_UNOWNED_DECLINE_OUTCOMES`), the assertions the row already carries
            # (T-11331's `red_assertions`) are this branch's UNOWNED red — the failures its own solo
            # leg cannot settle. Read off the two keys the rows already carry: no new event, no new
            # store, no new probe, and no signature change. LAST WRITE WINS here exactly as the mark
            # above does, and for the same reason — any newer verdict for this branch REPLACES what
            # is remembered (or forgets it), so a stale set can never outlive the row that recorded
            # it. A decline that NAMED an owner, an unmarked requeue, or any other verdict all forget:
            # the red is then somebody's and today's clearing is right.
            _decline = data.get("red_isolation_decline")
            _red = data.get("red_assertions")
            if (state[br] and isinstance(_decline, dict)
                    and str(_decline.get("outcome") or "") in _LAND_RED_UNOWNED_DECLINE_OUTCOMES
                    and isinstance(_red, (list, tuple)) and _red):
                unowned[br] = {str(a) for a in _red}
            else:
                unowned.pop(br, None)
        elif ev.get("type") == "land_completed":
            # RULE 14's RESOLUTION (T-11568) — the head's OWN verdict on itself, read BEFORE the
            # clearing arm below so a head that is also a marked peer cannot have this row do both
            # jobs in the wrong order. THREE outcomes, not two: `ok` REFUTES the blame and marks
            # every peer this head released; an `abort/verify-failed` CONFIRMS it and marks NOBODY;
            # ANY OTHER abort class resolved nothing about whether the head's code was red, so the
            # peers stay PENDING and this row decides neither way. The mark goes straight into
            # `state` because its lifetime is rule 4's one round exactly — the clearing arms already
            # present serve it unchanged.
            _blamed = [_p for _p, _hs in pending.items() if br in _hs]
            if _blamed:
                if data.get("status") == "ok":
                    for _peer in _blamed:
                        # REFUTED — one overturned blame is the whole trigger, so the peer is marked
                        # and its remaining registrations are moot: it is already ineligible, and
                        # one blame can only earn one round.
                        state[_peer] = True
                        pending.pop(_peer, None)
                elif str(data.get("abort_class") or "") == "verify-failed":
                    for _peer in _blamed:
                        # CONFIRMED — this head owned its red, so THIS blame marks nobody. Only this
                        # head leaves the set: any OTHER head that also released this peer is still
                        # unresolved and must keep its chance to refute.
                        _hs = pending.get(_peer) or set()
                        _hs.discard(br)
                        if not _hs:
                            pending.pop(_peer, None)
            # The individual verdict landed — ok OR abort, both are that member's OWN solo outcome,
            # BUT ONLY IF ITS CANDIDATE LEG ACTUALLY RAN (T-11256). That qualifier is not a new
            # requirement layered on rule 4; it is rule 4's own text ("every member reaches an
            # INDIVIDUAL verdict on its own candidate leg") finally being read. An abort raised
            # BEFORE the suite — the audited-diff currency gate, a merge conflict, the torn-tree
            # guard, a preflight rebaseline refusal — resolved nothing about why the batch was red,
            # so it cannot be the round. A row that carries no such evidence leaves the state
            # UNTOUCHED: an unmarked branch stays eligible, a marked one keeps its unserved round.
            # T-11710: AND ONLY IF IT SETTLED SOMETHING. A leg that ran and then re-observed the
            # batch's own UNOWNED red discharged a mark on a verdict that resolved exactly as little
            # as the preflight abort T-11256 removed — and that is how a red batch re-forms
            # identically, which rule 4 forbids outright. With nothing remembered for this branch
            # (the ordinary case, and every row written before this card) the predicate is False and
            # this arm is byte-identical to before.
            if _land_completed_verify_ran(data):
                # RULE 14, THE OTHER END OF THE REGISTRATION (T-11568): this PEER has now had its
                # own completed verify, so the round rule 14 would give it has already been served
                # by other means. A later refutation must not hand it a SECOND round for the same
                # release — that would be a quarantine growing out of one blame, which rule 4
                # forbids outright. Gated on the verify having RUN for exactly the T-11256 reason
                # the clearing arm below is: a preflight abort served no round.
                pending.pop(br, None)
                # THE RIDE COUNT RESETS ON THE VERDICT ITSELF (rule 13, T-11817), ok OR abort. This is
                # rule 4's clearing signal reused unchanged, and it is deliberately NOT also gated on
                # `_land_verdict_settled_nothing`: that qualifier answers whether the batch's UNOWNED
                # RED was settled, a question about a verdict. The ride count is about COUPLING — the
                # branch has now had its own uncoupled pass, and that is the whole thing it was owed.
                # Gating it there would make the count unclearable in exactly the unattributed-red case
                # rule 13 exists for, i.e. a permanent quarantine, which rule 4 forbids outright.
                rides.pop(br, None)
                if not _land_verdict_settled_nothing(data, unowned.get(br)):
                    state[br] = False
    out = {br for br, ineligible in state.items() if ineligible}
    # THE THIRD SOURCE (SPEC-0184 rule 13, T-11817). Unioned AFTER the fold for the same structural
    # reason rule 9's mark is: `state` is the red-batch machine, and a ride count entering there would
    # be governed by that machine's own lifetime rather than its own. Its lifetime is the count, and
    # the count is cleared by the reset in the `land_completed` arm above — nothing is stored, nothing
    # is marked, so there is no mark here that could fail to clear.
    out |= {br for br, n in rides.items()
            if n >= _LAND_RIDES_WITHOUT_LANDING_SOLO_THRESHOLD}
    # THE SECOND SOURCE (SPEC-0184 rule 9, T-11707). Unioned AFTER the fold, never into `state`:
    # `state` is the red-batch machine, whose `land_completed` arm sets False to serve the one round.
    # A mark that entered there would be cleared by that same arm and would last exactly one round —
    # the defect this card exists to fix. Unioning here is what makes the mark's lifetime the mark's
    # own. Fail-OPEN per branch, the polarity this whole read already takes: an unreadable card
    # grants no ineligibility, costing at worst one batch a marked branch shared.
    if main_wt is not None and _queue_jump_reason is not None:
        for br in branches or ():
            br = str(br or "").strip()
            if not br or br in out:
                continue
            try:
                if _queue_jump_reason(main_wt, br):
                    out.add(br)
            except Exception:              # noqa: BLE001 — fail-open: ordinary formation
                pass
    return out

def _land_reddened_member_sets(events_path: "Path | None", *,
                              _rows: "list | None" = None,
                              truncated_out: "list | None" = None,
                              now: "float | None" = None) -> "set[frozenset]":
    """SPEC-0184 rule 12 — the exact MULTI-MEMBER compositions that have already produced a red batch.

    WHY THIS IS SET-SHAPED AND ITS FOUR SIBLINGS ARE BRANCH-SHAPED. Every other ineligibility source
    formation consults answers "is THIS CANDIDATE fit to be batched" — a red-batch requeue, a declared
    rebaseline, a recorded supersession notice, a supersession mark, a dirty tree. This one answers a
    question about a COMBINATION, and it cannot be spelled as a branch predicate without becoming a
    different and much worse rule: marking every member of a formerly-red batch permanently unbatchable
    is the quarantine rule 4 spends four paragraphs forbidding. So it is a fifth SOURCE feeding the
    same formation decision, resolved beside `_land_batch_ineligible_branches` and applied at the same
    sink, but its subject is the set and it is therefore consulted where the set exists — AFTER the cap.

    WHAT IT READS, AND WHY NOTHING IS STORED. The journal already carries the whole answer. A dissolve
    (rule 4) journals ONE `land_member_verdict` per member with verdict `requeued-after-red-batch`,
    carrying `batch_id` (T-11331 mints one per formation) and `batch_size`. Grouping those rows by
    `batch_id` therefore RECONSTRUCTS the exact member set of every batch that went red, from rows that
    already exist for another purpose. No composition ledger is written, nothing new is emitted, and
    formation stays queue-driven and stateless (rule 1). A persisted ledger would be the parallel state
    home CHARTER §Principle 1 forbids, and would also be WRONG within a day: the journal rotates, the
    ledger would not, and the two would answer differently about the same history.

    A GROUP IS ACCEPTED ONLY WHEN IT IS PROVABLY COMPLETE, and this is not defensive padding. Two
    emitters write `requeued-after-red-batch`: the dissolve, which names EVERY member, and
    `_land_release_peers_for_solo_head` (T-11387), which names the PEERS ONLY while carrying the whole
    batch's `batch_size`. A group whose row count is short of the `batch_size` its own rows declare is
    therefore a PARTIAL view of some batch, and treating it as a composition would exclude a set that
    never existed. So a group counts iff `len(group) == batch_size` and `batch_size > 1` — the second
    clause is rule 12's anti-loop bound, held HERE as well as at the application site, so a solo red can
    never even ENTER the corpus this reader publishes.

    ROWS WITHOUT A `batch_id` ARE SKIPPED. Before T-11331 a member's row could only be joined to its
    batch by branch-plus-timestamp, which mis-attributes whenever one branch appears in several
    batches — the exact defect that card was filed to end. An unjoinable row therefore contributes
    nothing rather than contributing a guess.

    FAIL-OPEN TO THE EMPTY SET, the polarity every reader on this path takes. An unreadable journal, a
    missing path, an unparseable line: all of them yield "no composition is known to have reddened",
    i.e. ordinary formation. A missed exclusion costs one repeated batch — which then dissolves and is
    recorded, so the next formation has the fact; a spurious one would shrink batches on bad data,
    which is the capacity this whole spec exists to produce.
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return set()
        try:
            p = Path(events_path)
            if not p.exists():
                return set()
            # T-11816 — the SAME lifetime-sized window as rule 4's read, and for the same reason:
            # this reader's subject is the very same `requeued-after-red-batch` rows, grouped by
            # `batch_id` instead of folded per branch, so the measurement that grounds that horizon
            # grounds this one too. A composition whose rows fell past a byte bound was read as "never
            # reddened" — the same silence, one rule over.
            rows = _land_horizon_rows(
                p, "land_member_verdict", horizon_s=_LAND_INELIGIBILITY_HORIZON_SEC,
                label="reddened-member-sets (SPEC-0184 rule 12)",
                truncated_out=truncated_out, now=now)
        except Exception:                      # noqa: BLE001 — fail-open: ordinary formation
            return set()
    groups: "dict[str, set]" = {}
    sizes: "dict[str, int]" = {}
    for ev in rows or []:
        if not isinstance(ev, dict) or ev.get("type") != "land_member_verdict":
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        if not data or data.get("verdict") != "requeued-after-red-batch":
            continue
        bid = str(data.get("batch_id") or "").strip()
        br = str(data.get("branch") or "").strip()
        size = data.get("batch_size")
        if not bid or not br or not isinstance(size, int) or isinstance(size, bool):
            continue
        groups.setdefault(bid, set()).add(br)
        # LAST DECLARATION WINS, exactly as the sibling folds resolve a repeated key: the rows of one
        # batch all carry the same size, so this only ever matters for a malformed history, where
        # taking the newest row is the same rule the append-only journal is read by everywhere else.
        sizes[bid] = size
    return {frozenset(brs) for bid, brs in groups.items()
            if sizes.get(bid, 0) > 1 and len(brs) == sizes[bid]}

def _land_batch_members(branch: str, task: "str | None" = None, *,
                        claim_pid: "int | None" = None,
                        main_wt: "Path | None" = None, repo_root: "Path | None" = None,
                        events_path: "Path | None" = None, now: "float | None" = None,
                        batch_max: int = _LAND_BATCH_MAX,
                        ineligible: "set[str] | None" = None,
                        rebaselining: bool = False,
                        merge_invalid_acceptance: bool = False,
                        merge_invalid_acceptance_branches: "set[str] | None" = None,
                        solo_head: bool = False,
                        rebaselining_branches: "set[str] | None" = None,
                        superseding_branches: "set[str] | None" = None,
                        superseding_events_path=None,
                        marked_superseded_branches: "set[str] | None" = None,
                        dirty_branches: "dict | None" = None,
                        # T-11804 (SPEC-0184 rule 12): the compositions already known to have reddened.
                        # `None` ⇒ DERIVED from the journal, and only when a multi-member batch was
                        # actually formed; an injected value (every hermetic fixture) wins outright.
                        reddened_sets: "set | None" = None,
                        # T-11700: the land's own foldable-bookkeeping notion, PASSED THROUGH to the
                        # derived dirt reader (this module never back-imports the host that composes
                        # it). None ⇒ nothing foldable ⇒ today's answer, byte-identical.
                        _is_foldable_bookkeeping=None,
                        excluded_out: "list | None" = None,
                        # T-11904 — the sink `_land_horizon_rows` has always offered and nothing ever
                        # supplied. A horizon read that could not reach the window it DECLARED was
                        # reported to stderr and nowhere else, so the fact died with the terminal it
                        # printed on. Threaded here beside `excluded_out` because it is the same
                        # pass-through shape (T-11219) for the same reason: the caller that journals
                        # the formation is the one place that can also journal what the formation
                        # could not see.
                        truncated_out: "list | None" = None,
                        snapshot_out: "dict | None" = None,
                        _engagement=None, _queue=None, _changed_paths=None,
                        _classify_inert_paths=None,
                        _verify_touch=None, self_facts=None,
                        main_rev: "str | None" = None, _run_git_cap=None,
                        _DERIVED_MERGE_ARTIFACTS=None, _dedup_events=None,
                        _admitter=None, _corpus_check=None,
                        _decision_guard=None, _CORPUS_VERDICT_ERROR=None, _CORPUS_VERDICT_VIOLATION=None, _LandCompatAdmitter=None, _corpus_integrity_verdict=None, _git_rev=None, _land_batch_engagement=None, _land_batch_ineligible_branches=None, _land_batch_paying_members=None, _land_cost_class=None, _land_dirty_candidate_paths=None, _land_form_batch=None, _land_layer_runs_for=None, _land_member_would_run_suite=None, _land_pinned_supersession_branches=None, _land_queue_at_slot_free=None, _land_queue_jump_reason=None, _land_queue_member_facts=None, _land_rebaselining_branches=None, _land_merge_invalid_acceptance_branches=None, _land_supersession_marked_branches=None) -> "list[dict]":
    """The ordered batch THIS land carries, as member records `{branch, task}` (+ additive keys).

    SPEC-0184 rule 1: when the land slot frees, the batch is EXACTLY the set of lands queued at that
    moment, capped at `BATCH_MAX` — nothing waits to fill one. This land is the head of that queue
    (it holds the slot); `_land_queue_at_slot_free` supplies the peers behind it from the wait
    heartbeats already in the journal.

    THE SHAPE AND THE CALL SITE ARE T-11191's, NOT THIS CARD'S TO REDEFINE. The return stays a list
    of member dicts and the caller inside the ff lock is untouched; formation only replaces this
    BODY, which is exactly what lets T-11193/T-11194/T-11196 extend the same seam in parallel.
    Members carry an ADDITIVE `paying` flag (D-0009 growth), never a changed key.

    NO QUEUE SOURCE ⇒ TODAY'S SINGLETON, unchanged. A caller that passes neither `events_path`/
    `main_wt` nor an injected `_queue` gets `[{branch, task}]` — the honest answer when there is
    nothing to read a queue from, and the reason the existing call site keeps working byte-identically
    while the siblings wire the slot-free moment in.

    T-11194 (SPEC-0184 rule 4, the anti-LIVELOCK half) — `ineligible` is the set of branches that
    must be verified ALONE this round, because their last recorded outcome was a red batch. It is
    read from the journal by `_land_batch_ineligible_branches` when not injected, and it applies at
    the TWO places membership is decided, which is what makes a repeat of the same batch structurally
    unreachable rather than merely unlikely:
      - an ineligible HEAD forms a batch of ONE (it takes the slot it already holds and gets its own
        individual verdict — the very thing the dissolve requeued it for);
      - an ineligible PEER is EXCLUDED before the cap is applied, so it waits for its own slot rather
        than silently consuming a batch place.
    Excluding peers BEFORE the cap is deliberate: filtering after would let ineligible members eat
    the batch budget and shrink an otherwise valid candidate for no reason.

    T-11239 (SPEC-0184 rule 4, the same mechanism) — a land REBASELINING a pinned assertion is
    batch-INELIGIBLE for that attempt, and it enters at exactly the two decision points above rather
    than as a third code path: `rebaselining` (this land's OWN declaration, read from its flags by the
    caller) makes the HEAD a batch of one — as does `solo_head` (T-11387), the caller's own record
    that this land already RELEASED its peers on a head-is-culprit red and must re-verify alone — and `rebaselining_branches` (the PEERS' declarations, read
    from their wait rows by `_land_rebaselining_branches` when not injected) drops those peers BEFORE
    the cap. The difference from rule 4's requeue mark is the SOURCE of the answer, never its effect:
    a red batch is learned AFTER a pass, a rebaseline declaration is knowable BEFORE one.

    T-11267 (SPEC-0184 rule 4, the same mechanism, a THIRD source) — a candidate whose OWN latest
    `commit_landed` row already carries a fired pinned-supersession notice is batch-INELIGIBLE for
    that attempt, and it enters at exactly the same two decision points rather than as a new code
    path: `superseding_branches` (read by `_land_pinned_supersession_branches` when not injected, off
    the journal named by `superseding_events_path` — the LANDING worktree's, which holds this land's
    own commit rows as well as main's) makes such a HEAD a batch of one and drops such PEERS BEFORE
    the cap, each with its own named sink reason. The difference from T-11239 is again only the SOURCE
    of the answer: a declaration is the author SAYING they supersede, this is a notice the system
    already RECORDED that they probably do. n=1 so far — a hypothesis under test, never a measured
    precision (the reader's docstring carries the evidence and its bounds).

    PRECEDENCE: A DECLARED REBASELINE CLEARS THE SUPERSESSION EXCLUSION, and this is stated in the
    code rather than left to the order of two filters. A `--rebaseline` declaration is the AUTHORISED
    way to supersede a pinned assertion (SPEC-0077 §3a), so a candidate that has declared one is not
    excluded BY THIS INPUT at all: the supersession set is reduced by the rebaselining set, and the
    head check asks `not rebaselining`. Such a candidate may still be dropped for that attempt by the
    T-11239 filter above — one round, attempt-scoped, unchanged and not widened here — and it is then
    reported EXACTLY ONCE, by that rule's reason. Reporting it twice would not merely read oddly: the
    sink is what `queue_depth` counts, so a second row would inflate the number of candidates the
    formation claims to have seen.

    T-11276 (SPEC-0184 rule 8, at the FORMATION seam) — a PEER whose supersession MARK is set is not
    taken as a batch candidate at all, and is dropped BEFORE the cap with its own named sink reason,
    exactly like the two filters above. `marked_superseded_branches` is the injection seam; when it is
    None the set is derived from the surviving peers by `_land_supersession_marked_branches` off
    `main_wt`. The difference from T-11239/T-11267 is once again only the SOURCE of the answer: those
    ask whether a candidate would REDDEN the combined pass, this asks whether it has anything left to
    integrate — a marked branch's content is already in `main` via the head's fast-forward.

    THIS RULE IS PEER-SIDE ONLY AND STATES NOTHING ABOUT A MARKED HEAD (controller resolution
    2026-08-18) — deliberately, not by omission. T-11274 handles the head UPSTREAM: a genuinely
    superseded land exits at the park site before it ever takes the reservation this formation runs
    under. Where T-11274 fails closed the marker is OVERRIDDEN and the land carries REAL content, so
    narrowing it to a batch of one would cost a pass for nothing. The head check below is therefore
    UNTOUCHED by this rule.

    THE FILTER RUNS LAST, over the peers the two filters above LEFT, and that order is load-bearing:
    a candidate already dropped for its rebaseline declaration or its recorded supersession notice has
    already been reported ONCE with that rule's reason, and a second sink row would inflate
    `queue_depth` — whose meaning is the candidates this formation SAW. Same one-row-per-candidate
    discipline the `_sup - _reb` precedence subtraction above exists to preserve.

    T-11312 (SPEC-0184 rule 1, the EXHAUSTIVENESS half) — EVERY BRANCH THE QUEUE SOURCE YIELDED LEAVES
    A DISPOSITION, and the reason that needed its own card is that the sinks above are total over the
    filters that OWN a reason, not over the candidate set. Three drops sat outside all of them: the
    HEAD short-circuit below returns `[self_member]` AFTER the peers were enumerated; the rule-4
    requeue filter dropped peers deliberately unreasoned; and `_land_form_batch`'s cap REMAINDER — the
    value that function returns expressly so a member is "never silently lost" — was discarded by this
    caller. Each now writes its own named reason into the SAME `excluded_out` sink, so nothing new is
    invented and a reader consults one list. `snapshot_out`, when given, additionally receives
    `{"read_ts": <epoch the queue was READ at>, "seen": [<every enumerated branch>]}` — an out-sink
    rather than a second return value for exactly the reason `excluded_out` is one: the member-list
    return is T-11191's frozen seam shape and is not this card's to redefine. The read clock is taken
    HERE, at the read, and is NOT the emit clock: `land_batch_formed`'s `ts` is stamped later, so a
    reader asking "what was true when the decision was made" was reading the wrong instant.

    T-11508 (SPEC-0184 rule 11, the same two decision points, a FIFTH source and the first whose
    subject is a WORKING TREE) — a candidate whose own worktree holds UNCOMMITTED changes is
    batch-ineligible for that attempt: such a HEAD forms a batch of ONE, such a PEER is dropped BEFORE
    the cap. `dirty_branches` is the injection seam (`{branch: [paths]}`); when None it is DERIVED
    over the head plus the surviving peers by `_land_dirty_candidate_paths` off `main_wt`, and with no
    `main_wt` (or no git runner) it stays EMPTY — which is what keeps every hermetic caller
    byte-identical.

    IT IS NOT A WIDENING OF RULE 4`S FAMILY, and the distinction is why it is a separate rule rather
    than a fourth entry in `_inel`. Every other source here answers "this candidate is clean but must
    not carry peers" — a COUPLING risk. Dirt is a PRECONDITION failure: the branch aborts identically
    alone or batched, because what refuses it is its own tree and not its company. So the remedy is
    never "give it its own slot"; it is COMMIT, which is why this filter`s row NAMES THE PATHS.

    IT RUNS FIRST AMONG THE PEER FILTERS, deliberately. The one-row-per-candidate discipline means the
    first filter to drop a branch owns the reason a reader will act on — and of the reasons available
    for a dirty branch, this is the only one whose remedy is in its operator`s hands right now.

    THE DERIVATION IS GATED ON AN ENGAGED BATCH WITH AT LEAST ONE PEER, so rule 1's quiet-repo
    byte-identity is untouched: with nothing to select between, the reader is never built and a solo
    or disengaged land runs no extra subprocess (T-11309's `admitter` construction gate, both
    conditions, for the identical promise). An INJECTED `dirty_branches` is never gated — a caller
    that supplies the answer has already paid for it.

    FOLDABLE DIRT DOES NOT EXCLUDE (T-11700). `_is_foldable_bookkeeping` is threaded to the derived
    reader so a candidate whose ENTIRE dirt is what the land folds anyway reads CLEAN. That closes the
    asymmetry the HONEST BOUND below names rather than contradicting it: the head arrives folded, the
    peer never did, and only the peer paid. Non-foldable dirt — and mixed dirt — still exclude,
    unchanged; the reason's remedy stays "commit", and its named paths are now only the ones that
    genuinely need it.

    HONEST BOUND ON THE HEAD ARM, so it is not read as doing more than it does. In `cmd_land` the two
    `_fold_trailing_bookkeeping` calls run BEFORE `_land_integrate`, so a head carrying non-foldable
    dirt has ALREADY aborted by the time formation runs and a head carrying only foldable dirt has
    already been committed clean. The head arm is therefore a FAIL-SAFE for that ordering rather than
    the arm that fires in production today: it is what keeps the rule true for a caller that does not
    fold first, and what stops a head re-dirtied between the fold and formation from silently pulling
    peers into a batch it cannot finish. The PEER arm is where the measured recovery is — a peer's
    tree is folded by nobody, since the head merges it from its committed tip.

    THE DIRTY HEAD REPORTS TOO, on its OWN member record rather than in the sink (audit-pre finding 1,
    high, 2026-08-25). A head that silently returns a solo batch tells its operator nothing, and "the
    abort names the paths later" is the same it-is-explained-elsewhere argument T-11235 and T-11312
    each rejected for a formation row. It is NOT a sink row for the reason the rebaselining head is
    not one either: the head is not a queue candidate, so a sink entry would describe the slot holder
    as one of its own exclusions and would inflate `queue_depth`.

    T-11804 (SPEC-0184 rule 12, and the ONLY source here whose subject is the SET rather than a
    branch) — an exact MULTI-MEMBER composition that already reddened is not RE-FORMED. It is applied
    AFTER the cap, because that is where the selected set exists, and it RECOMPOSES rather than
    refusing: members are dropped, one at a time, until the composition differs — down to a batch of
    one, which this rule NEVER refuses whatever its history. That bound is what keeps the rule from
    becoming a LOCKOUT: a branch whose solo run reddened must still be allowed to run solo, so the
    descent multi-member -> smaller -> solo terminates on a floor that is always eligible. Every
    dropped member leaves through the existing sink with its own named reason and waits for its own
    slot exactly as an over-cap member does, so nothing is left unformed. `reddened_sets` is the
    injection seam; when None the corpus is DERIVED by `_land_reddened_member_sets` off the journal,
    and only when a multi-member batch was actually formed (rule 1's quiet-repo promise).

    THE REBASELINING PEER IS REPORTED, THE REBASELINING HEAD IS NOT — and the asymmetry is exact.
    A dropped PEER goes to `excluded_out` with its own named reason, so the T-11235 N=1 fork emits a
    formation row and a solo land still says why it was solo. The HEAD is not a queue candidate, so
    putting it in the same sink would inflate `queue_depth` — whose meaning is the candidates this
    formation SAW — and describe the slot holder as one of its own exclusions.
    """
    self_member = {"branch": branch, "task": task}
    # T-11196 (SPEC-0180 rule 6): THIS land's claim handle rides its OWN member record. Only the
    # self-member can carry one: the peers come from wait heartbeats, which say a land is queued but
    # not what binding its claimant declared. A peer therefore stays UNBOUND — which is the correct
    # reading, not a gap: an unbound claim is one nothing can process-release, so a peer is never
    # dropped on a liveness signal nobody supplied. Sourcing a peer's handle is a later card's work.
    if claim_pid is not None:
        self_member[_LAND_MEMBER_CLAIM_PID_KEY] = claim_pid
    if _queue is None and events_path is None and main_wt is None:
        return [self_member]
    # Only the BOOLEAN is formation's business. The `reason` half is the METRIC's — a caller that
    # journals the batch asks `_land_batch_engagement` itself and passes it to
    # `_emit_land_batch_formed(engagement=…)`, so the reason has one reader and is never smuggled
    # through the member records.
    _ops_seen: list = []
    _eng = (_engagement() if _engagement is not None
            else _land_batch_engagement(repo_root if repo_root is not None else main_wt,
                                        ops_out=_ops_seen))
    engaged = _eng[0]
    # T-11278: the REASON, consumed here for the paying predicate. Read off the SAME answer `engaged`
    # comes from — never re-derived — so the two can never disagree about who authored the verify.
    _eng_reason = _eng[1] if len(_eng) > 1 else None
    _ep = events_path if events_path is not None else (
        (Path(main_wt) / "events.jsonl") if main_wt is not None else None)
    # T-11312 — the READ CLOCK, taken at the snapshot and never at the emit. `now` is the injected
    # clock every reader below already shares, so the recorded value is the SAME instant the freshness
    # window and the ordering test were judged against — a read_ts derived anywhere else would date a
    # different decision than the one the row describes.
    _read_ts = time.time() if now is None else float(now)
    _seen: "list[str]" = []
    if _queue is not None:
        peers = list(_queue)
        _seen = [str((p or {}).get("branch") or "") for p in peers]
    else:
        # T-11219: `excluded_out` is a pass-through sink for the liveness exclusions the queue read
        # makes, so the caller that journals the batch can also journal WHY a queued-looking branch
        # is not in it. Kept as a sink rather than a second return value because the member list is
        # T-11191's frozen seam shape and is not this card's to redefine.
        peers = [{"branch": b, "task": (b.split("/", 1)[1] if b.startswith("task/") else None)}
                 for b in _land_queue_at_slot_free(
                     _ep, branch, now=now, excluded=excluded_out, seen=_seen,
                     # T-11794 — bound ONLY when both halves of the answer are present. With no
                     # checkout or no git runner the predicate would be UNKNOWN for every branch
                     # anyway, so passing None there keeps one behaviour instead of two.
                     _branch_exists=((lambda _b: _land_queue_branch_resolves(
                         _b, main_wt, _run_git_cap=_run_git_cap))
                         if (main_wt is not None and _run_git_cap is not None) else None))]
    # T-11194 (SPEC-0184 rule 4) — the batch-ineligibility filter. See the docstring: an ineligible
    # HEAD is a batch of one, an ineligible PEER is dropped BEFORE the cap.
    # T-11707 (SPEC-0184 rule 9): the mark source is fed the CANDIDATES this formation already holds
    # — this head plus the peers read above — so the second source costs one card read per candidate
    # and never a corpus walk. An INJECTED `ineligible` still wins outright: that contract means the
    # caller decided the whole set, and this card does not redefine it.
    _inel = (_land_batch_ineligible_branches(
                 _ep, main_wt=main_wt, _queue_jump_reason=_land_queue_jump_reason,
                 truncated_out=truncated_out,
                 branches=[branch] + [str((p or {}).get("branch") or "") for p in peers])
             if ineligible is None else set(ineligible))
    if solo_head:
        # T-11387 (SPEC-0184 rule 4, the head-is-culprit arm) — a land that has ALREADY RELEASED its
        # peers this round must re-form ALONE, because re-admitting the peers it just released would
        # re-form the batch that was red and learn nothing (the livelock rule 4 exists to prevent).
        #
        # IT ENTERS THROUGH `_inel` RATHER THAN AS A FOURTH DISJUNCT ON THE HEAD CHECK BELOW, and
        # that is the honest spelling, not a way around a tripwire: rule 4's ineligibility means
        # exactly "must be verified ALONE on the next attempt", which is precisely this head's state.
        # Reusing the set therefore reuses the head short-circuit, the peer sink reason
        # (`_LAND_HEAD_SOLO_EXCLUSION_REASON`) and the cap ordering with no new formation path
        # (CHARTER §P1 F1/F2). The DIFFERENCE from every other member of this set is only the SOURCE
        # of the answer — this land's own state, not a journal read — the same distinction T-11239
        # and T-11267 each draw for their own sources.
        _inel = set(_inel) | {branch}
    # T-11239: the rebaseline half of the SAME ineligibility question — asked here so the head check
    # and the peer filter below each consult one set, never two competing ones.
    _reb = (_land_rebaselining_branches(_ep, now=now) if rebaselining_branches is None
            else set(rebaselining_branches))
    # T-11267: the third source of the SAME ineligibility question, read off the journal the caller
    # names (the landing worktree's, which carries this land's own commit rows) — asked here beside
    # the other two so all three decision points consult one set each, never competing ones.
    # T-11939 (SPEC-0184 rule 4) — the SECOND GROUND, resolved beside `_reb` so the head check and the
    # peer filter below each consult ONE set, never two competing ones. Same source shape as T-11239 (a
    # declaration read off the wait rows the queue read already consumes); the ONLY difference is which
    # ground it states, which is exactly why it gets its own set and its own sink reason instead of
    # widening `_reb`.
    _mia = (_land_merge_invalid_acceptance_branches(_ep, now=now)
            if merge_invalid_acceptance_branches is None else set(merge_invalid_acceptance_branches))
    _sup = (_land_pinned_supersession_branches(
        superseding_events_path if superseding_events_path is not None else _ep)
        if superseding_branches is None else set(superseding_branches))
    # PRECEDENCE, EXPLICIT: a DECLARED rebaseline is the authorised way to supersede a pinned
    # assertion, so it CLEARS the supersession exclusion — the branch's exclusion, if any, is
    # T-11239's one-round business above, reported once with that rule's reason.
    _sup = _sup - _reb
    # T-11939 — `_mia` IS DELIBERATELY ABSENT FROM THE SUBTRACTION ABOVE, AND THAT ABSENCE IS A FACT,
    # NOT AN OMISSION. The subtraction encodes an AUTHORITY: a declared `--rebaseline` is the
    # sanctioned way to supersede a pinned assertion, so it clears the T-11267 exclusion. A
    # merge-invalid-acceptance declaration carries no such authority — it names a probe that cannot
    # read a merged tree, which says nothing whatever about a pinned assertion — so a branch that both
    # declares this ground AND has a recorded pinned supersession stays excluded on the supersession,
    # and a branch that supersedes a pinned assertion still owes its own `--rebaseline` and still fails
    # closed without one. Adding `_mia` here would weaken the rebaseline safety gate by exactly the
    # byte this card's AC2 forbids, and it would do so invisibly.
    # T-11280 (SPEC-0186 rules 4+9): where THIS project has declared the pinned leg off, the key
    # describes a check that will not run, so it is INERT for class assignment — a member carrying it
    # must not be led alone for nothing. Narrowed HERE, beside the rebaseline narrowing above, because
    # both are the same idea: a set reduced by a higher authority. The policy is read from `main_wt`
    # (the BASE tree) UNCONDITIONALLY — never `repo_root`, which is the merged candidate; see the
    # reader's docstring for why no touch-detector is added. Absent `main_wt` (a direct/test caller
    # that did not inject it) leaves `_sup` untouched — fail-closed, the check keeps applying.
    # T-11283: RESOLVED ONCE, HERE, and consumed TWICE — this supersession-key narrowing and the cost
    # ladder's rung-2 collapse below. Both are the same question ("will that second pass happen?"),
    # so they must read ONE answer; hoisting the read out of the `if _sup` guard is what makes that
    # possible without a second call. `None` records "not resolved" (no base tree to read), which the
    # ladder treats exactly like `all` — fail-closed, the leg keeps counting.
    _policy = None
    if main_wt is not None:
        try:
            _policy = task_mod._verify_policy_pinned_last_green(
                Path(main_wt), ops_contract=_host_apply.CONSUMER_OPS_CONTRACT)
        except Exception:
            _policy = "all"                    # resolver unavailable ⇒ run the leg (fail-closed)
    if _sup and _policy == "never":
        _sup = set()
    # T-11508 (SPEC-0184 rule 11) — the WORKING-TREE precondition, resolved ONCE over the head plus
    # the enumerated peers, before either decision point consults it. Derived here rather than inside
    # the two branches below so both read ONE answer over ONE snapshot of the trees, exactly as the
    # three journal-derived sets above are each resolved once. Read-only by construction: the reader
    # runs a listing and a status and nothing else (AC4).
    # GATED ON AN ACTUAL SELECTION NEED, not merely on having the inputs — the SAME two construction
    # conditions T-11309's admitter takes, and for the same promise: rule 1 guarantees a QUIET repo
    # runs no subprocess and writes no object, and the worktree listing this reader opens with IS a
    # subprocess. Both conditions must hold — the batch must be ENGAGED (a disengaged land is a batch
    # of one by rule 2) and at least one PEER must be present. Nothing is lost by either: with no peer
    # to protect, a dirty head has nobody to drag into a batch it cannot finish and aborts on its own
    # tree exactly as today. Same argument `_land_form_batch` makes for not prefiltering the head —
    # skipping the slot holder is meaningless, it IS the land. An INJECTED `dirty_branches` is never
    # gated: a caller that supplies the answer has already paid for it.
    _dirty = dict(dirty_branches) if dirty_branches is not None else (
        _land_dirty_candidate_paths(
            main_wt, [branch] + [str((p or {}).get("branch") or "") for p in peers],
            _run_git_cap=_run_git_cap,
            # T-11700: without this the reader counts a peer's append-only journal as dirt and drops
            # it from the batch over the one file the land would have folded.
            _is_foldable_bookkeeping=_is_foldable_bookkeeping)
        if (engaged and peers) else {})
    if branch in _dirty:
        # The HEAD's own bounded dirty-path list rides its MEMBER record (additive key, D-0009 growth)
        # — see the docstring for why this is not a sink row.
        self_member[_LAND_MEMBER_DIRTY_PATHS_KEY] = list(_dirty[branch])

    def _publish_snapshot():
        """T-11312 — hand the caller the snapshot this formation actually read. Called on EVERY return
        below the queue read, so a head that short-circuits reports the same enumerated set as one that
        forms a full batch — the asymmetry between those two paths is precisely what hid task/T-11285
        on 2026-08-19."""
        if snapshot_out is not None:
            snapshot_out["read_ts"] = _read_ts
            snapshot_out["seen"] = list(_seen)

    # T-11939 — the SECOND ground joins as a further disjunct and is written LAST, on a continuation
    # line, so this line's PREFIX is byte-identical. That is not cosmetic: T-11335's
    # `test_t11387_the_solo_head_formation_gate_is_the_existing_short_circuit` LOCATES this gate by a
    # `^if branch in _inel or rebaselining or branch in _sup` regex in order to assert something else
    # entirely (that `solo_head` is NOT a disjunct here). Inserting into the middle would redden a
    # tripwire on the one thing it declares it is not checking, so the disjunct goes where the
    # existing locator still finds its anchor. Order is otherwise immaterial — these are OR-ed.
    if branch in _inel or rebaselining or branch in _sup or branch in _dirty \
            or merge_invalid_acceptance:
        # T-11312 — the peers were ALREADY enumerated above, and this return drops every one of them.
        # Before this card they left no trace at all: the queue read's own stale entries still reached
        # the sink (it appends them itself), so the row showed exclusions and a member and simply
        # omitted the admitted peer — the exact shape of the 10:55:02Z row. Reported with the HEAD's
        # reason, not the peer's, because nothing is wrong with the peer: this land is unbatchable and
        # the peer waits for its own slot, unchanged.
        if excluded_out is not None:
            excluded_out.extend({"branch": str((p or {}).get("branch") or ""),
                                 "reason": _LAND_HEAD_SOLO_EXCLUSION_REASON} for p in peers)
        _publish_snapshot()
        return [self_member]
    if _dirty:
        # T-11508 (SPEC-0184 rule 11) — dropped BEFORE the cap, for the reason every sibling is:
        # filtering after would let a candidate that cannot integrate eat the batch budget. The row
        # carries the PATHS as well as the reason, because unlike every other exclusion here the
        # remedy is an action its operator can take immediately, and an exclusion that does not name
        # it sends them back to the queue a second time.
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            if _br in _dirty:
                if excluded_out is not None:
                    excluded_out.append({"branch": _br,
                                         "reason": _LAND_DIRTY_WORKTREE_EXCLUSION_REASON,
                                         _LAND_MEMBER_DIRTY_PATHS_KEY: list(_dirty[_br])})
                continue
            _kept.append(p)
        peers = _kept
    if _inel:
        # T-11312 — dropped WITH a reason now, like every sibling filter below. The T-11194 argument
        # for the silence (the dissolve that wrote the mark already journalled it) explains the
        # JOURNAL, not the formation row, and a reader reconstructing one formation reads the row.
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            if _br in _inel:
                if excluded_out is not None:
                    excluded_out.append({"branch": _br,
                                         "reason": _LAND_REQUEUED_INELIGIBLE_EXCLUSION_REASON})
                continue
            _kept.append(p)
        peers = _kept
    if _reb:
        # Dropped WITH a reason, unlike the rule-4 requeue filter above: that mark was WRITTEN by the
        # dissolve that made it, so the journal already explains it, while this exclusion is decided
        # here and would otherwise leave a solo land unexplained (T-11235's whole point).
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            if _br in _reb:
                if excluded_out is not None:
                    excluded_out.append({"branch": _br,
                                         "reason": _LAND_REBASELINING_EXCLUSION_REASON})
                continue
            _kept.append(p)
        peers = _kept
    if _sup:
        # Dropped WITH a reason, exactly like the rebaseline filter above and deliberately UNLIKE the
        # rule-4 requeue filter: that mark was written by the dissolve that made it, so the journal
        # already explains it, while this exclusion is decided HERE and would otherwise leave a solo
        # land unexplained (T-11235's whole point). Appending is not optional politeness — a drop that
        # writes no row is indistinguishable from a queue that was simply empty, which is the measured
        # defect (2026-08-18) this path must not reproduce.
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            if _br in _sup:
                if excluded_out is not None:
                    excluded_out.append({"branch": _br,
                                         "reason": _LAND_PINNED_SUPERSESSION_EXCLUSION_REASON})
                continue
            _kept.append(p)
        peers = _kept
    if _mia:
        # T-11939 — dropped BEFORE the cap and WITH its own reason, for the two reasons every sibling
        # filter here is: filtering after the cap would let a member that will redden the candidate eat
        # the batch budget, and a drop that writes no row is indistinguishable from a queue that was
        # simply empty (the measured 2026-08-18 defect T-11235 closed).
        #
        # IT RUNS LAST, over what `_reb` and `_sup` LEFT, and that order is load-bearing in a way the
        # sibling orderings above are not — it decides the DIAGNOSIS, not just the count. A candidate
        # carrying BOTH a recorded pinned supersession and this declaration is excluded either way, but
        # only one of the two reasons tells its operator what they still OWE: the supersession is the
        # stronger, UN-CLEARED fact and carries a real obligation (declare `--rebaseline`, SPEC-0077
        # §3a), while this ground grants nothing and clears nothing. Reporting such a branch under THIS
        # reason would read as "handled" and quietly suppress that obligation — the same weakening AC2
        # forbids, arriving through the sink instead of through `_sup - _reb`. Running last also keeps
        # the one-row-per-candidate discipline the siblings hold: `queue_depth` counts this sink.
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            if _br in _mia:
                if excluded_out is not None:
                    excluded_out.append({"branch": _br,
                                         "reason": _LAND_MERGE_INVALID_EXCLUSION_REASON})
                continue
            _kept.append(p)
        peers = _kept
    # T-11276 (SPEC-0184 rule 8): a PEER whose supersession mark is set has nothing left to
    # integrate — the head's ff already carried its content — so it is not a candidate. Derived over
    # the peers the filters ABOVE left, so a candidate dropped there is reported exactly once (a
    # second sink row would inflate `queue_depth`). Dropped BEFORE the cap, for the same reason every
    # sibling is: filtering after would let it eat the batch budget for nothing.
    _msup = (_land_supersession_marked_branches(
        main_wt, [str((p or {}).get("branch") or "") for p in peers])
        if marked_superseded_branches is None else set(marked_superseded_branches))
    if _msup:
        # Dropped WITH a reason, exactly like the two filters above and deliberately UNLIKE the rule-4
        # requeue filter. Appending is not optional politeness: a drop that writes no row is
        # indistinguishable from a queue that was simply empty, which is the measured 2026-08-18
        # defect (`queue_depth` is derived as len(queue_excluded)+members-1, so a silent drop is
        # blind in BOTH directions) this path must not reproduce.
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            if _br in _msup:
                if excluded_out is not None:
                    excluded_out.append({"branch": _br,
                                         "reason": _LAND_SUPERSESSION_MARK_EXCLUSION_REASON})
                continue
            _kept.append(p)
        peers = _kept
    # T-11283 — ONE `git diff` per branch, shared by every reader below. The rank, the paying
    # predicate and the `paying` flag all ask for the SAME member's changed paths; without this memo
    # the ladder's new question would pay a third diff per peer per attempt for an answer already in
    # hand. PURE pass-through otherwise — it holds no rule, only the answer `_changed_paths` gave.
    _cp_memo: dict = {}

    def _cp(_m):
        _b = str((_m or {}).get("branch") or "")
        if _b not in _cp_memo:
            _cp_memo[_b] = list(_changed_paths(_m) or []) if _changed_paths is not None else []
        return _cp_memo[_b]

    # T-11278 / T-11283: the two raw facts each queued member published about its own next verify,
    # folded from the SAME in-window wait rows the peer queue above was read from, and overlaid with
    # the HEAD's own facts (the journal cannot supply them — a land holding the slot never waited).
    # RESOLVED ONCE, HERE, ABOVE the cost filter, because BOTH consumers need it: the rung-0 question
    # the ladder now asks and the per-member `paying` flag below. Two folds would be two answers to
    # one question over a journal that keeps moving.
    _facts = dict(_land_queue_member_facts(_ep, now=now))
    if self_facts:
        _facts[str((self_member or {}).get("branch") or "")] = dict(self_facts)
    # An injected `_engagement` (hermetic callers) publishes no ops, so the consumer half reads
    # UNDECIDABLE there — the fail-closed direction, and byte-identical to those callers' today.
    _runs = (lambda _paths: _land_layer_runs_for(_ops_seen[0] if _ops_seen else None, _paths))

    def _would_run(_m):
        """T-11283 — WOULD THIS MEMBER'S OWN LAND RUN THE SUITE? The T-11278 predicate, bound to the
        inputs this function already computed. One predicate, two readers (the rank here and the
        `paying` flag below) — never a second answer to the question SPEC-0184 rule 1 already owns."""
        _f = _facts.get(str((_m or {}).get("branch") or "")) or {}
        return _land_member_would_run_suite(
            _m, engagement_reason=_eng_reason, attempt=_f.get("attempt"),
            no_tests=bool(_f.get("no_tests")), _changed_paths=_cp,
            _classify_inert_paths=_classify_inert_paths, _layer_runs_for=_runs)

    # T-11273 (SPEC-0184 rule 10) — ONE COST CLASS PER BATCH. The batch class is the HEAD's class:
    # the head is the land that ALREADY HOLDS the slot, so it is in the batch by construction and
    # formation can neither drop nor defer it. Since T-11275 landed the local yield, a head of a more
    # expensive class RELEASES the slot when a strictly cheaper class is queued — so the head IS the
    # cheapest class present by construction, and "batch class = head class" and "cheapest class in
    # the snapshot" coincide rather than compete (the reading that deadlocked audit-pre twice).
    # REUSES `_land_cost_class`, the ranking T-11275 ships (T-11283 rungs: 0 no pass / 1 one pass /
    # 2 two passes / None undecidable) — a SECOND cost helper would be the parallel encoding
    # CHARTER §P1 forbids and would trip `test_t0631`'s sanctioned-consumer guard.
    # T-11283: the rank is handed the SAME `_would_run` oracle and the SAME resolved pinned policy
    # the rest of this function uses, so formation and the metric cannot disagree about what a land
    # would pay. `_classify_inert_paths` is still REQUIRED here — not by the ladder, which no longer
    # asks the inert question, but by the predicate it is passed to.
    # Runs LAST among the peer filters so a branch already dropped above is reported exactly once,
    # and BEFORE the cap so a deferred peer never eats a batch place.
    if (_changed_paths is not None and _classify_inert_paths is not None
            and _verify_touch is not None and peers):
        def _cost_of(_m):
            try:
                return _land_cost_class(_m, _changed_paths=_cp, _verify_touch=_verify_touch,
                                        _would_run_suite=_would_run, pinned_last_green=_policy)
            except Exception:              # noqa: BLE001 — undecidable, handled as None below
                return None
        _head_class = _cost_of(self_member)
        _kept = []
        for p in peers:
            _br = str((p or {}).get("branch") or "")
            _pc = _cost_of(p)
            # FAIL-CLOSED, and the direction is the point: an UNDECIDABLE class on EITHER side never
            # batches. An unreadable candidate must not enter a cheap batch, and an unclassifiable
            # head forms a batch of one — the same bounded cost every sibling filter already pays
            # (one unamortised pass), never a wrong combination verified together.
            if _head_class is None or _pc is None or _pc != _head_class:
                if excluded_out is not None:
                    # T-11545 — THE SAME DROP, RECORDED AS THE THING IT ACTUALLY IS. The condition
                    # above is unchanged and so is every drop it makes; only the reason written is
                    # chosen, because ONE string was covering THREE dispositions and only the third
                    # is what it says. An undecidable classification was recorded as though the
                    # candidate had been READ and found to be of another class, so the rate at which
                    # formation cannot read a candidate was not merely unnamed but mislabelled —
                    # which is why the T-11532 fold over 682 dispositions could report no count at
                    # all and correctly said so rather than reporting zero.
                    #
                    # THE PEER'S OWN UNREADABILITY IS TESTED FIRST, and the order is the substance
                    # rather than style: when BOTH sides are undecidable the fact a fold wants is
                    # that THIS candidate could not be read, which is a property of the row's own
                    # branch. Every sink row names ONE branch and must be true of it — so a peer
                    # dropped because the HEAD is unreadable gets its own reason, since that peer
                    # may itself be perfectly readable and labelling it `undecidable` would
                    # manufacture a count of unreadable candidates out of one unreadable head.
                    #
                    # NO ROW IS ADDED OR REMOVED. The head still gets no sink row of its own — it is
                    # not a queue candidate, and a row there would describe the slot holder as one of
                    # its own exclusions and inflate `queue_depth` (the carrier split rule 11 and the
                    # rebaselining head already settled). Membership, the classification, the fail
                    # direction, the class order and the cap are untouched.
                    _why = (_LAND_COST_CLASS_UNDECIDABLE_EXCLUSION_REASON if _pc is None
                            else _LAND_COST_CLASS_UNDECIDABLE_HEAD_EXCLUSION_REASON
                            if _head_class is None
                            else _LAND_COST_CLASS_EXCLUSION_REASON)
                    excluded_out.append({"branch": _br, "reason": _why})
                continue
            _kept.append(p)
        peers = _kept
    # T-11309 (SPEC-0184 rule 1) — THE CAP IS REACHED BY WALKING, NOT BY SLICING. Every filter above
    # answers "is this candidate eligible at all", a question about ONE branch; this last one answers
    # "can it coexist with what is already selected", which is a question about a PAIR and is the only
    # one nothing else in the system ever asks. It runs LAST, after the per-branch filters, so a
    # candidate already dropped is reported exactly once, and AT the cap rather than before it,
    # because skipping is worth nothing unless the next compatible candidate can take the vacated
    # place. Built ONCE per formation over the snapshot already read (AC4) — never per member per
    # round, and never on the poll path.
    #
    # A caller supplying no git runner (every hermetic test that wants the pre-change shape) gets
    # `admitter=None` and therefore the unchanged slice. That is the honest answer, not a degradation:
    # with nothing to run `merge-tree` with, no compatibility can be proven, and this predictor never
    # invents a skip it could not prove.
    #
    # CONSTRUCTION IS GATED ON AN ACTUAL SELECTION NEED, not merely on having the inputs
    # (audit-post finding 1, high, 2026-08-19). Rule 1 promises a quiet repo byte-identity at the
    # level of "no subprocess, no object written" — and resolving the base rev is itself a `rev-parse`
    # subprocess, so building the admitter for a formation that can never consult it BREAKS that
    # promise even though the probes are lazy. Two conditions must hold before anything is built:
    # the batch must be ENGAGED (a disengaged land is a batch of one by rule 2) and at least one PEER
    # must have survived the filters above. The land call site happens to pass `main_rev=merged_base`,
    # which would mask this — the property must hold by CONSTRUCTION, not by the luck of one caller.
    # ── T-11365 POINT 1, SELECTION — the corpus-integrity question, asked of each candidate ALONE
    # against the current land base, BEFORE anything queues behind it.
    #
    # BUILT HERE, BESIDE THE COMPAT ADMITTER, AND GATED ON THE SAME TWO CONDITIONS — engaged AND at
    # least one surviving PEER. Not a stylistic pairing: SPEC-0184 rule 1 promises a quiet repo
    # byte-identity at the level of "no subprocess, no object written", and resolving the base rev is
    # itself a `rev-parse`. Building this for a formation that can never consult it breaks that
    # promise even though the probes are lazy — the identical defect T-11309's audit-post caught as
    # its finding 1, and the pinned suite catches again if this drifts. It is also SEMANTICALLY the
    # right gate: with no peers there is nobody to protect from a violating head, and the head meets
    # point 2 before the suite regardless.
    #
    # A caller that injects `_corpus_check` (every hermetic fixture) uses that instead. With no git
    # runner and no base rev nothing can be PROVEN, and this predicate never invents a skip it could
    # not prove — the same honesty `_LandCompatAdmitter` holds to.
    _corpus = _corpus_check
    if _corpus is None and _run_git_cap is not None and main_wt is not None and engaged and peers:
        _cbase = main_rev or _git_rev("main", main_wt, _run_git_cap=_run_git_cap)
        if _cbase:
            # T-11397 (X-1072) — THE BASE IS PER-CANDIDATE, and that is the whole fix. The three
            # corpus guards compare `git diff <base> <head>` — a TWO-DOT diff, which is SYMMETRIC:
            # against main's TIP it reports every file where the two trees differ, INCLUDING files
            # MAIN changed after the candidate branched. So a spec body that a spec-touching land
            # already put on main reads, from an unmerged peer's side, as "body moved, no
            # `spec_edited` in this branch" — and the peer's journal, being behind, carries none of
            # main's newer events to clear it. The peer is judged an OFF-PATH SPEC EDITOR for the
            # sole offence of being BEHIND. Measured on this repo's own refs before the fix: the
            # spec-hand-edit guard, asked with base='main' and head='main~K', named 4 offenders for
            # K in 5/10/20 — heads that are ANCESTORS of main and by construction authored nothing.
            # (Named in prose, not as a call: `test_ac8_the_placement_points_call_the_runner_not_
            # the_guards` scans this WHOLE function's source for a direct guard call, comments
            # included, and one implementation per check is the property it protects.)
            #
            # POINT 2 NEVER HAD THIS: it passes `merged_base` with head = the MERGED tree, so its
            # base..head really is "what this branch authored". The merge-base restores exactly that
            # semantics here WITHOUT doing a merge — it is the same question, asked off-queue.
            #
            # AND IT DOES NOT WEAKEN T-9730: a branch that really did edit a spec body off-path
            # carries that edit in its OWN history, above the merge-base, so it is still an offender.
            #
            # UNRESOLVABLE MERGE-BASE → the runner's OWN `error` shape, never a fabricated `clean`
            # and never a silent fallback to the moved base. "An error is a fact about the CHECKER,
            # never a claim about someone's changes" — the runner's doctrine, and the selection gate
            # already admits on error with point 2 + the post-suite guard behind it.
            def _corpus(_br, _base=_cbase):    # noqa: E306 — bound to THIS formation's base
                try:
                    _mb = _run_git_cap(["merge-base", _base, _br], main_wt)
                    _fork = _mb.stdout.strip() if _mb.returncode == 0 else ""
                except Exception as _e:        # noqa: BLE001 — a git that could not run at all
                    return {"status": _CORPUS_VERDICT_ERROR, "bad": [], "warn": [],
                            "error_reason": f"git merge-base {_base}..{_br} raised: "
                                            f"{type(_e).__name__}"}
                if not _fork:
                    return {"status": _CORPUS_VERDICT_ERROR, "bad": [], "warn": [],
                            "error_reason": f"merge-base of {_base!r} and {_br!r} does not resolve "
                                            f"in {main_wt}"}
                return _corpus_integrity_verdict(
                    main_wt, _fork, _run_git_cap=_run_git_cap,
                    _decision_guard=_decision_guard, head=_br)
    # THE HEAD, FIRST AND SEPARATELY (audit-pre finding 1, high, 2026-08-20). The head holds the
    # land slot, so it cannot be skipped — but a VIOLATING head must not drag peers into a batch
    # that is already doomed, which is precisely what "not engaged" already means: rule 2 expresses
    # it as a batch of ONE with everyone else waiting, as a slice on this same path. So a head that
    # PROVABLY violates disengages formation and takes a new named reason in the existing reason
    # vocabulary — no new mechanism, no head exemption. It then lands solo, meets point 2 before
    # the suite, and is told at once; the peers were never members and pay nothing.
    #
    # `violation` ONLY. A `clean` head proceeds; an `error` head ALSO proceeds, because an error is
    # a fact about the checker and disengaging on it would shrink every batch in the repo on bad
    # data — the direction that costs capacity, which is the very thing this card exists to recover.
    #
    # THE HEAD'S OWN DELIVERY needs no carrier here: the head IS this land, so it reads the guard's
    # message from its OWN abort at point 2 — it is the one member that always sees it. What main
    # needs is WHY the batch was solo, and that is the `reason` recorded on the formation row.
    if _corpus is not None and engaged:
        _hv = _corpus(branch)
        if isinstance(_hv, dict) and _hv.get("status") == _CORPUS_VERDICT_VIOLATION:
            engaged = False
            _eng_reason = _LAND_HEAD_CORPUS_VIOLATION_REASON
    _admit = _admitter
    if (_admit is None and _run_git_cap is not None and main_wt is not None
            and engaged and peers):
        _base = main_rev or _git_rev("main", main_wt, _run_git_cap=_run_git_cap)
        if _base:
            _admit = _LandCompatAdmitter(
                main_wt, _base, _run_git_cap=_run_git_cap,
                _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS, _dedup_events=_dedup_events)
    # T-11365 — the per-branch corpus predicate, handed to the walk as `prefilter`. It returns a
    # dict (skip, carrying the guard's own member-directed message) or None (admit). It skips ONLY
    # on `violation`: `clean` admits, and `error` ALSO admits, because the post-suite aggregate
    # guard is still the authority behind this predicate — an unprovable answer therefore costs at
    # most today's outcome, while a spurious skip would punish exactly the innocent neighbours this
    # card exists to protect. That is the polarity `_LandCompatAdmitter` argues for a predictor with
    # a downstream authority, and the direction
    # `lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate` prescribes.
    def _corpus_prefilter(_br, _m):
        if _corpus is None:
            return None
        v = _corpus(_br)
        if not isinstance(v, dict) or v.get("status") != _CORPUS_VERDICT_VIOLATION:
            return None
        return {"cause": list(v.get("bad") or [])}
    members, _remainder = _land_form_batch([self_member] + peers,
                                           batch_max=batch_max, engaged=engaged,
                                           admitter=_admit, excluded_out=excluded_out,
                                           prefilter=(_corpus_prefilter if _corpus is not None
                                                      else None))
    # T-11312 — the REMAINDER is returned by `_land_form_batch` expressly so a member over the cap is
    # "never a silently lost member", and this caller then discarded it. It is a genuine formation
    # decision — this queue was deeper than BATCH_MAX — and a reader could not tell it from a queue
    # that was exactly this long. The head is at index 0 and is never in the remainder, so nothing
    # here can describe the slot holder as one of its own exclusions.
    # T-11309 merge: the two sinks are ORTHOGONAL and both are kept. `_land_form_batch` now records
    # the INCOMPATIBLE skips into `excluded_out` itself (the admitter runs inside formation), while
    # the over-cap REMAINDER is only knowable to this caller, which holds the returned tail. Dropping
    # either one restores a silent disposition the sibling card was filed to end.
    if _remainder and excluded_out is not None:
        excluded_out.extend({"branch": str((m or {}).get("branch") or ""),
                             "reason": _LAND_OVER_BATCH_CAP_EXCLUSION_REASON} for m in _remainder)

    # T-11804 (SPEC-0184 rule 12) — IT RECOMPOSES, IT NEVER BLOCKS. The exact member SET of a batch
    # that already reddened is not formed again; a member is dropped until the composition DIFFERS.
    #
    # IT RUNS HERE, AFTER THE CAP, BECAUSE HERE IS WHERE THE SET EXISTS. Every filter above is a
    # per-branch question and is therefore asked before the cap, so an ineligible candidate never eats
    # a batch place. This one is a question about the SELECTED SET, which does not exist until
    # `_land_form_batch` has walked the candidates and applied the cap — asking it earlier would be
    # asking it of a set that is not the one about to be verified.
    #
    # THE ANTI-LOOP BOUND, AND IT IS THE MOST LOAD-BEARING LINE HERE. The exclusion applies to
    # MULTI-MEMBER sets ONLY: `len(members) > 1` guards both the derivation and every iteration, so a
    # batch of ONE is never refused by this rule whatever its history. A branch whose SOLO run reddened
    # must still be allowed to run solo, because solo is the terminating case every recomposition
    # descends toward. Without the bound this would not be a loop but something strictly worse — a
    # branch that fails alone could never form a batch again and would be permanently unlandable, with
    # no verb to release it. The descent multi-member -> smaller -> solo therefore has a floor that is
    # always eligible, which is why the loop below provably terminates: each pass removes exactly one
    # member and the condition stops at 1.
    #
    # THE LAST MEMBER IS THE ONE DROPPED. The head is at index 0 and holds the land slot, so it can
    # never be dropped; the tail is the lowest-priority queued peer, and it leaves through the SAME
    # sink every other exclusion uses, so it waits for its own slot exactly as an over-cap member does.
    # Nothing is left unformed: the batch that returns is always non-empty, and every dropped peer is
    # still queued with its own land in flight.
    #
    # WHAT THE HONEST CASE IS, recorded here so nobody re-derives it as something stronger. Over
    # 2026-08-21..28 this repo formed 194 multi-member batches in 189 unique compositions — only 5
    # exact repeats, roughly one a day. Of the two informative repeats one went red then GREEN (this
    # rule would have prevented a batch that SUCCEEDED) and one went green then RED. An exact-set
    # repeat therefore does NOT predict the outcome. The case for the rule is CHEAP PREVENTION plus the
    # free bisection recomposition yields — members meet different peers each round, which isolates
    # them across rounds — and it is NEVER predictive power. (A near-miss cohort sharing >=2 members
    # with a red batch reds at 76% against a 57% baseline, but that cohort is CONFOUNDED: a single
    # genuinely-broken branch touring the queue inflates it, so it is not evidence that the
    # COMBINATION causes the red and is not quoted as a rate here.) The owner was shown this and
    # decided to proceed, 2026-08-28.
    #
    # DERIVED, NEVER STORED, and gated so rule 1's quiet-repo promise is untouched: the journal read
    # happens only when a MULTI-MEMBER batch was formed, so a solo formation reads nothing at all.
    if len(members) > 1:
        _red_sets = (_land_reddened_member_sets(_ep, truncated_out=truncated_out)
                     if reddened_sets is None
                     else {frozenset(x) for x in reddened_sets})
        while len(members) > 1 and frozenset(
                str((m or {}).get("branch") or "") for m in members) in _red_sets:
            _dropped = members.pop()
            if excluded_out is not None:
                excluded_out.append(
                    {"branch": str((_dropped or {}).get("branch") or ""),
                     "reason": _LAND_REPEATED_RED_SET_EXCLUSION_REASON})
    if _changed_paths is not None and _classify_inert_paths is not None:
        # T-11278 — THE HEAD KNOWS ITS OWN FACTS, AND THE JOURNAL MAY NOT (audit-post finding). The
        # queue read recovers attempt/no_tests from `waiting_for_*` heartbeats, which a land that
        # never WAITED does not emit — and the head is precisely the land that did not wait, because
        # it holds the slot. Reading it from the journal alone therefore leaves the one member that
        # always pays as UNKNOWN, i.e. non-paying, and under-counts EVERY batch by one. Its caller
        # holds both values as locals, so they are handed in rather than rediscovered. The fold +
        # overlay itself moved ABOVE the cost filter (T-11283) so the rank reads the same answer.
        for m in members:
            m["paying"] = _land_batch_paying_members(
                [m], _changed_paths=_cp,
                _classify_inert_paths=_classify_inert_paths,
                engagement_reason=_eng_reason, member_facts=_facts,
                _layer_runs_for=_runs) == 1
    _publish_snapshot()
    return members

def _land_batch_paying_members(members: "list[dict]", *, _changed_paths=None,
                               _classify_inert_paths=None, engagement_reason=None,
                               member_facts=None, _layer_runs_for=None, _land_member_would_run_suite=None) -> int:
    """SPEC-0184 rule 1 / the realization-exit metric — how many members would have PAID a full suite
    pass on their own (T-11192 AC4).

    A PAYING member is one whose land, run alone, would actually have run the suite — asked of each
    member by `_land_member_would_run_suite` (above), which owns the whole verdict. This function is
    the COUNT over that predicate and nothing else; it holds no rule of its own, so there is exactly
    one place the question is answered.

    THE INERT-PATH PROXY THIS ONCE USED IS RETIRED (T-11278). Reading `_classify_inert_paths` as
    "this member would have skipped its suite" conflated the inert CLASS with a skip that is in fact
    gated on `attempt > 1`, so a first-attempt bookkeeping land — the cheapest and most frequent
    class — was reported as saving nothing while it paid a full pass. `_classify_inert_paths` is
    still the ONE inert authority and is still consumed, but only for the retry cohort that genuinely
    skips.

    WHY THIS MUST BE SEPARABLE FROM `len(members)`. A batch of 4 that carries 1 paying member reads
    as "4.0 lands per pass" on the member count alone while it actually saved ONE pass. Reporting the
    two as one number is exactly the illusion this metric exists to break, so `paying` is counted and
    carried as its OWN key, never folded into the member count.

    UNKNOWN ⇒ NOT PAYING. A member whose changed-path set cannot be read is not counted, so the
    metric UNDER-claims rather than over-claims the saving. That direction is deliberate: this number
    exists to expose a repo assumed to benefit while saving nothing, and a metric that guesses upward
    would manufacture the very reassurance it is supposed to withhold.
    """
    if _changed_paths is None or _classify_inert_paths is None:
        return 0
    facts = member_facts if isinstance(member_facts, dict) else {}
    n = 0
    for m in members:
        f = facts.get(str((m or {}).get("branch") or "")) or {}
        if _land_member_would_run_suite(
                m, engagement_reason=engagement_reason, attempt=f.get("attempt"),
                no_tests=bool(f.get("no_tests")), _changed_paths=_changed_paths,
                _classify_inert_paths=_classify_inert_paths,
                _layer_runs_for=_layer_runs_for) is True:
            n += 1
    return n

def _land_batch_verify_path_touch(members: "list[dict]", *, _touches=None) -> bool:
    """SPEC-0184 rule 7 — does ANY member touch the verify path? FAIL-CLOSED.

    A batch's candidate IS the merged tree, so the SPEC-0077 pinned-leg trigger MUST be evaluated
    over the UNION of the members' diffs. Evaluating it per-member, on the first member, or skipping
    the leg to preserve the amortised saving silently VOIDS SPEC-0077 for every member of the batch:
    member A may weaken the verifier while member B is a bad change, and the candidate leg then runs
    A's weakened verifier over B. The only thing still protecting B's peers is the PINNED leg
    re-running the pre-change verifier over that same combined tree. This is a correctness
    constraint, not tuning — the cost-shifting it causes (one verify-path-touching member imposes the
    doubled regime on peers who touched nothing) is stated in SPEC-0184 rule 7 and licenses nothing.

    FAIL-CLOSED IN BOTH DIRECTIONS THAT MATTER: a member whose diff cannot be read arms the leg, and
    so does any exception from the caller's touch predicate. Over-firing the pinned re-run is cheap;
    under-firing is the circular-trust hole SPEC-0077 exists to close — the same asymmetry the
    single-land trigger already resolves this way.

    AT N<=1 IT RETURNS FALSE, AND THAT IS NOT A HOLE. The self-member's own touch is computed by the
    step-4a preflight (`_verify_path_touch`) and this result is UNIONED with it, so a singleton land's
    trigger is decided exactly where it always was. Returning True here would double-fire nothing and
    returning the self-member's answer would give the same value twice from two authorities (P5).
    """
    if len(members) <= 1 or _touches is None:
        return False
    for m in members[1:]:
        try:
            if _touches(m):
                return True
        except Exception:                      # noqa: BLE001 — unreadable member ⇒ arm the leg
            return True
    return False

def _land_clear_yield_offer(main_wt: "Path | None", *, _land_yield_offer_path=None) -> None:
    """Withdraw the offer. Idempotent — an absent offer IS the success state, so a double withdraw and
    a withdraw that races the addressee's own consumption are both no-ops."""
    path = _land_yield_offer_path(main_wt)
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:                  # noqa: BLE001 — an unremovable offer still expires by liveness
        return

def _land_stale_yield_offer_verdict(main_wt: "Path | None", *, now=None,
                                    _land_read_yield_offer=None, _land_yield_offer_path=None,
                                    _land_pid_is_live=None) -> dict:
    """T-12413 — READ the yield offer on disk and say whether it is CLEARABLE. Pure read; unlinks
    nothing. Returns `{status, addressee, writer_pid, addressee_pid, age_s}`.

    `status` over a CLOSED three-value vocabulary:
      - `absent`               — no offer, or one that does not read. Nothing to clear; the verb's
                                 idempotent no-op path.
      - `addressee-land-alive` — the offer records an addressee land pid and that pid EXISTS. The
                                 REFUSAL: a live land will consume this offer itself, and taking it
                                 away from under one would destroy a handover that is still running.
      - `stale`                — clearable. Either NO addressee pid is recorded (the pre-T-12413
                                 shape, which is exactly the 2026-09-11 fleet park: an offer for a
                                 land that never started, which no process can ever consume) or one
                                 IS recorded and does not exist.

    THE DECISION AND THE ACT ARE SEPARATE, deliberately. The verb must be able to PRINT a refusal
    without having half-performed it, and a reader that unlinked as a side-effect of being asked
    could not be called twice.

    `age_s` IS REPORTED, NEVER A THRESHOLD. Nothing here branches on it — this card adds no TTL,
    timeout or number (the design principle the three sibling fences are built on); the age exists so
    the journal row can say HOW LONG the thing had been parking the fleet, which is what the operator
    and a later reader actually want to know. An unreadable mtime yields None rather than a guess.

    THE WRITER'S OWN LIVENESS IS NOT CONSULTED, and that is the point of a separate verb. A dead
    writer already expires its offer inside `_land_yield_offer_blocks`, so an offer that needs a
    HUMAN is by definition one the automatic fences cannot resolve: what this answers is only whether
    an addressee land is still coming."""
    path = _land_yield_offer_path(main_wt)
    offer = _land_read_yield_offer(main_wt)
    if path is None or offer is None:
        return {"status": "absent", "addressee": None, "writer_pid": None,
                "addressee_pid": None, "age_s": None}
    br, writer_pid, addressee_pid = offer
    try:
        age = int(max(0.0, (time.time() if now is None else now) - path.stat().st_mtime))
    except Exception:                  # noqa: BLE001 — an unreadable mtime is UNKNOWN, never a guess
        age = None
    status = "addressee-land-alive" if (addressee_pid is not None
                                        and _land_pid_is_live(addressee_pid)) else "stale"
    return {"status": status, "addressee": br, "writer_pid": writer_pid,
            "addressee_pid": addressee_pid, "age_s": age}

def _land_completed_verify_ran(data: "dict | None") -> bool:
    """T-11256 (SPEC-0184 rule 4) — does this `land_completed` row EVIDENCE that a candidate leg ran?

    THE DEFECT THIS ANSWERS (measured 2026-08-17, traced row by row). Rule 4 marks a dissolved
    batch's members batch-ineligible for ONE ROUND so each reaches an INDIVIDUAL VERDICT ON ITS OWN
    CANDIDATE LEG — the spec's own words. The reader below discharged that mark on ANY terminal
    `land_completed`, including an abort raised BEFORE the suite. `task/T-11232` was marked at
    19:56:36Z; at 20:15:47Z its land aborted `audited-diff-stale` — a preflight refusal that ran
    nothing — and that row cleared the mark. It was re-admitted into a second batch at 20:24:44Z,
    which died at 20:32:40Z on the same assertion. The round rule 4 promises was never served: the
    anti-livelock guard was discharged by an event that resolved nothing.

    WHY THIS PREDICATE AND NOT THE OTHER TWO CANDIDATES — both were measured over the 7074
    `land_completed` rows on main and REJECTED, so neither is re-proposed later as an obvious
    simplification:
      - "no `abort_preflight` marker" — the marker exists on 10 rows in the whole journal, all
        `rebaseline-unauthorized` (only the two T-10850 `_die` sites set it). The incident's own
        `audited-diff-stale` row has none, nor do `uncommitted-dirt`, `merge-non-union-conflict`,
        `repeated-abort-backstop`, or the E-0035 `concurrent-land-same-worktree` guard. Absence of
        the marker would clear on every one of them.
      - "a present `verify_mode`" — not evidence of a run. The T-10850 preflight sites pass a
        HARDCODED `verify_mode: "pinned+candidate"` in their abort_detail, so rows for a suite that
        never started carry one.
    What IS evidence is either a positive per-row artefact of the run (`verify_metrics` /
    `failing_tests` / `failing_assertions`) or an abort class that can only be reached FROM the run.
    Both legs are load-bearing: the evidence keys alone miss the 51 measured `verify-failed` /
    `verify-timeout` rows that recorded no detail key, while the class list alone would mis-clear the
    116 `rebaseline-unauthorized` rows whose T-10754 waive-coverage refusal DID run the pinned leg
    and which the evidence keys correctly admit.

    A NON-ABORT ROW ALWAYS QUALIFIES. A land that reached `status: ok` is that member's terminal
    individual outcome and takes the branch out of the queue entirely; making the one-round mark
    outlive a successful land could only ever be a quarantine.

    FAIL-OPEN, in the SAME direction as the caller — for every payload that REACHES here. A row whose
    fields are unreadable but whose shape is intact (a garbled `status`, a missing `abort_class`)
    reads as "ran", i.e. it CLEARS. The asymmetry is deliberate and matches the cost: a
    wrongly-cleared mark costs one repeated batch (which dissolves again and re-marks properly),
    while a wrongly-KEPT one on bad data turns "one round, not a quarantine" into exactly the
    quarantine the rule forbids.

    THE NON-DICT LEG IS A BELT, NOT THE READER'S BEHAVIOUR — stated exactly, because the difference
    is load-bearing (audit-post finding, 2026-08-18). `_land_batch_ineligible_branches` guards its
    own payload first (`data = ev.get("data") if isinstance(..., dict) else None; if not data:
    continue`), so a row with a non-dict `data` is SKIPPED before it can reach this predicate: it
    neither crashes nor clears, and a marked branch keeps its mark. That is the reader's pre-existing
    behaviour and this card does not change it — a malformed row carries no readable `branch` either,
    so there is no branch whose mark could be cleared, and inventing one would be fabricating a fact.
    The `isinstance` leg below therefore protects only DIRECT callers of this predicate; it is not a
    claim that the reader fails open on structurally unreadable rows."""
    if not isinstance(data, dict):
        return True                                    # fail-open: never quarantine on bad data
    if str(data.get("status") or "") != "abort":
        return True                                    # an ok land IS the individual verdict
    if any(data.get(k) for k in ("verify_metrics", "failing_tests", "failing_assertions")):
        return True                                    # positive per-row artefact of the run
    return str(data.get("abort_class") or "") in _LAND_VERIFY_RAN_ABORT_CLASSES

def _land_consume_supersession_marker(main_wt: "Path | None", branch: "str | None", *, _land_supersession_marker_path=None) -> None:
    """SPEC-0184 rule 8 — unlink the marker at the moment it is READ, so it cannot go stale.

    A marker is evidence about ONE ff that has already happened. Left in place it would keep answering
    True for a branch name that a later task may legitimately reuse, and a permanently-true hint is how a
    cheap signal turns into a wrong one. Consuming it at the read makes the hint single-use — and because
    the hint never decides anything on its own (the content check does), losing it early is harmless.
    Silent on every failure, for the same reason the write is."""
    try:
        path = _land_supersession_marker_path(main_wt, branch) if main_wt is not None else None
        if path is not None:
            path.unlink(missing_ok=True)
    except Exception:                  # noqa: BLE001 — best-effort, exactly like the write
        pass

def _land_consume_yield_offer(main_wt: "Path | None", self_branch: "str | None", *, _land_clear_yield_offer=None, _land_read_yield_offer=None) -> bool:
    """The ADDRESSEE's own act, mirroring `_land_consume_supersession_marker`: having taken the slot it
    was offered, the addressee withdraws the offer. Consumption belongs to the addressed branch and
    NEVER to the writer — the writer is parked waiting to see it go, so a writer-side consume would
    destroy the very evidence the handover rests on."""
    offer = _land_read_yield_offer(main_wt)
    if offer is None or offer[0] != (self_branch or "").strip():
        return False
    _land_clear_yield_offer(main_wt)
    return True

def _land_contamination_advisory(branch: str, foreign: "list[dict]",
                                 wt: "Path | None" = None) -> "list[str]":
    """Render `_land_batch_foreign_merges` as the stated read AC4 asks for: it NAMES the foreign
    commits and says what to do. Empty list when there is nothing to say — a clean branch prints
    nothing at all, so this can sit on the land preflight without adding noise to the common case."""
    if not foreign:
        return []
    lines = [f"land: WARNING — {branch} carries {len(foreign)} merge commit(s) from OTHER branches "
             "that a land batch left behind (SPEC-0184 rule 4). A batch merges its peers into the "
             "head member's branch and takes them back off when it does not land; a land whose "
             "process was KILLED cannot run that cleanup, so they stay."]
    for f in foreign:
        lines.append(f"land:   {f['sha'][:9]}  {f['subject']}")
    lines.append("land: WHAT THIS COSTS — landing as-is carries another card's commits, and this "
                 "branch inherits their conflicts with main as though they were its own.")
    lines.append(f"land: WHAT TO DO — check `git -C {wt or '<worktree>'} log --oneline "
                 f"main..{branch}`; if the merges above are not yours, drop them "
                 f"(`git -C {wt or '<worktree>'} rebase --onto main` from the last commit that IS "
                 "yours, or reset to the pre-batch sha named in the `land_batch_head_restored` "
                 "journal row). Report-only — this refuses nothing.")
    return lines

def _land_named_culprit_advisory(branch: str, events_path: "Path | None" = None, *,
                                 _rows: "list | None" = None) -> "list[str]":
    """T-11815 — TELL A BRANCH THAT IT WAS NAMED THE CULPRIT OF A RED BATCH, and what to do about
    it. Returns [] whenever nothing is PROVEN, so a clean branch prints nothing at all. PURE over
    injected rows; report-only, refuses nothing, moves no exit code.

    THE DEFECT, MEASURED. A red batch may NAME a member as the culprit; the head then evicts it,
    carries the survivors into a fresh verify (`retry-culprit-evicted`) and the named member goes
    back to the queue. The eviction already writes everything the culprit needs to its
    `land_member_verdict` row ON MAIN — `evicted_as_culprit`, `red_isolation{failing, reproduced}`,
    the batch id — but the ONE sentence anybody prints about it ("land: red batch ISOLATED to ...")
    goes to the HEAD's stderr, because the head is the process that is running. The culprit is a
    PASSENGER and receives nothing. On 2026-08-28 task/T-11803 rode four shared batches, reddened
    all four, was named twice, and was returned to the queue each time without ever learning it was
    the cause — while its own worktree already carried the `--expect-rebaseline` route out
    (T-11801, landed 12:28). Roughly eight shared verify passes were paid by peers with nothing
    wrong with them.

    THE CARRIER IS THE CULPRIT'S OWN NEXT `land`, and that choice IS the card. The branch that
    needs this is ALREADY RUNNING: its brief was written before the mechanism existed and its seed
    was read before that, so no re-dispatch seam re-delivers anything to it. What it MUST do is
    re-invoke `land` (the dispatched-worker rule: hold the turn, re-invoke inline until `LAND: OK`),
    so the land preflight is the one surface a worker in flight reaches without re-reading its brief
    or its seed. A new journal row would have no reader; a marker file in the worktree would be read
    only by a FRESHLY dispatched worker — which is precisely the population this does NOT serve.
    The analog is EXTENDED, not duplicated: `_land_contamination_advisory` directly above is the
    same report-only, silent-when-clean preflight advisory rendered from durable state.

    IT NAMES THE ROUTE, NOT ONLY THE FAULT. A record that says only "you were the culprit" leaves
    the branch exactly where T-11803 was — able to declare and not knowing to. So the block forks on
    the entry class the remedy differs for: a `[pinned/last-green] ` entry is a SUPERSESSION, whose
    sanctioned route is the tokenless pre-failure declaration `--expect-rebaseline`; anything else
    is an ordinary failure this branch fixes IN SCOPE.

    FAIL TOWARD SILENCE, NEVER TOWARD ACCUSATION
    (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`). This is a signal
    about WHOSE change something was, so the wrong direction is telling a branch it was at fault
    when it was not: one false accusation and the whole line gets skimmed. The ONLY key that admits
    a branch here is `evicted_as_culprit`, written at exactly ONE site on the members the isolation
    probe PROVED reproduce the failure alone. Every other disposition reads []: an attribution that
    DECLINED (`red_isolation_decline` on every member and no name anywhere — bat-f2749263764c,
    2026-08-28, four members requeued and none named), a peer RELEASED on a head-is-culprit red,
    `evicted-for-conflict`, `dropped-dead-member`, `landed`, and a branch with no member row at all.
    Newest row wins (the journal is append-only), so a branch whose eviction was superseded by any
    later verdict is told nothing about the old one.

    ONLY THE ASSERTIONS IT REPRODUCED ALONE ARE PRINTED AS ITS OWN. `red_isolation.reproduced` is
    the oracle's per-branch answer; `failing` is the whole BATCH's red and belongs to nobody in
    particular. Printing the batch's red as this branch's would widen the accusation exactly the way
    `_land_batch_attribution_line` refuses to. An empty `reproduced` is reported as NOT RECORDED,
    never as "nothing" — absent means unproven.

    HONEST BOUND, recorded here rather than discovered later. The clearing signal is this branch's
    own next `land_completed`, but an ABORTED land writes that row into the LANDING CHECKOUT's
    journal (T-11241), so main may not carry it and the advisory may repeat on a later land. That is
    the fail-toward-TELLING direction and the statement stays true (still named, still unsettled);
    the alternative — a stored consumed-flag — is a new store for a cosmetic gain.
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return []
        try:
            p = Path(events_path)
            if not p.exists():
                return []
            # The SAME prescan token + tail bound `_land_batch_ineligible_branches` reads these rows
            # with — one reader shape, not a second one. Both types this needs
            # (`land_member_verdict`, `land_completed`) carry `land_`.
            rows = journal_mod.tail_scan_events(
                p, "land_", max_bytes=_LAND_BATCH_INELIGIBLE_TAIL_BYTES)
        except Exception:                      # noqa: BLE001 — fail-open: say nothing
            return []
    _own = str(branch or "").strip()
    if not _own:
        return []
    verdict: "dict | None" = None
    for ev in rows or []:
        if not isinstance(ev, dict):
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        if not data or str(data.get("branch") or "").strip() != _own:
            continue
        if ev.get("type") == "land_member_verdict":
            verdict = data              # append-only: the newest verdict for this branch governs
        elif ev.get("type") == "land_completed":
            # The individual verdict this branch's own solo round produced — the eviction is no
            # longer the last thing that happened to it, so the advisory falls silent.
            verdict = None
    if not isinstance(verdict, dict) or not verdict.get("evicted_as_culprit"):
        return []
    _iso = verdict.get("red_isolation")
    _reproduced = [str(a) for a in (_iso.get("reproduced") or [])] if isinstance(_iso, dict) else []
    _batch = str(verdict.get("batch_id") or "<unrecorded>")
    lines = [f"land: NAMED CULPRIT — {_own} was named the culprit of red batch {_batch} and was "
             "requeued (SPEC-0184 rule 4 / T-11335 / T-11815). The eviction message went to that "
             "batch's HEAD, which is a different process, so this is the first time this branch is "
             "being told. Its peers carried on without it."]
    if _reproduced:
        lines.append("land:   the failing assertion(s) this branch reproduced ALONE:")
        lines.extend(f"land:     - {a}" for a in _reproduced)
    else:
        lines.append("land:   the assertion it reproduced alone was NOT RECORDED on the row — the "
                     "eviction is on record, the per-entry evidence is not.")
    if any(a.startswith(_LAND_PINNED_ENTRY_PREFIX) for a in _reproduced):
        lines.append("land: WHAT TO DO — at least one entry above is a PINNED last-green assertion, "
                     "i.e. your change supersedes it. The sanctioned route is to DECLARE that up "
                     "front on this land: `bin/yitc-v2 land --expect-rebaseline ...` (T-11801). It "
                     "needs NO waive token and no prior failure, and its only effect is that this "
                     "land is verified ALONE instead of inside a batch — so the supersession stops "
                     "costing peers a shared pass. It GRANTS NOTHING: the pinned verify, the waive "
                     "matcher and the audit-currency gate are untouched, and a pinned failure still "
                     "refuses exactly as today. It is not `--rebaseline`.")
    else:
        lines.append("land: WHAT TO DO — fix the named failure IN SCOPE before re-landing; never "
                     "weaken, skip or waive the gate to force it through (SPEC-0103). This land is "
                     "already batch-INELIGIBLE for one round (rule 4), so it verifies alone.")
    lines.append("land: Report-only — this refuses nothing and changes no exit.")
    return lines

def _land_cost_class(member: dict, *, _changed_paths, _verify_touch,
                     _would_run_suite=None, pinned_last_green=None) -> "int | None":
    """SPEC-0184 rule 9 — the COST RANK of one queued branch: how many suite passes its OWN land
    would actually pay. PURE over injected readers.

      0  NO checks at all — this member's own land would not run the suite
      1  ONE pass — the ordinary candidate verify
      2  TWO passes — the candidate verify PLUS the SPEC-0077 pinned last-green leg
      None  UNDECIDABLE

    THE RUNGS COUNT PASSES, AND THAT IS WHAT MAKES THE RANK MEAN ANYTHING (T-11283, owner directive
    2026-08-18). The rank decides which members batch together and who the reservation is YIELDED to,
    so a rung that names a path CLASS rather than a cost hands the slot to whoever is cheapest in
    name only. Both ends of the old ladder were wrong about the cost they claimed to describe:

    RUNG 0 IS "THE SUITE WOULD NOT RUN", NEVER "THE PATHS CLASSIFY INERT". The old rung 0 read
    `_classify_inert_paths(paths) == "inert"` directly, but the inert skip is LEVER B, gated on
    `attempt > 1` — so a FIRST-attempt inert land runs the FULL suite and only its canary is skipped.
    Measured 2026-08-18: work/pinned-layer-project-switch ranked 0 while running a verify of
    422129 ms (reverify_skipped false, attempt_count 1) — ranked the cheapest thing in the repo while
    paying the most frequent full pass, so the slot was yielded TO the expensive branch. The question
    is now asked of `_land_member_would_run_suite`, the ONE predicate T-11278 shipped for it, injected
    pre-bound as `_would_run_suite`; this function no longer touches the inert authority at all (the
    predicate consumes it, for the retry cohort that genuinely skips).

    IN THE KERNEL RUNG 0 IS NEARLY EMPTY BY CONSTRUCTION, and saying so is part of the rule. Attempt 1
    always verifies, so the only free kernel lands are a RETRY whose delta is inert and a land running
    no tests at all. The populated cheap rung lives on CONSUMERS, where a diff disjoint from every
    declared layer's `subject_globs` really does run nothing. Reporting rung 0 as a populated cheap
    class on both sides would be the same over-claim the retired inert proxy made.

    RUNG 2 COLLAPSES TO RUNG 1 WHERE THE PINNED LEG IS OFF. Rung 2 is a SECOND pass, so it is only
    real if that pass will happen: SPEC-0186 lets a project declare `verify_policy.pinned_last_green:
    never`, and there the verify-surface touch buys nothing. `pinned_last_green` is the value the
    caller resolved through T-11280's ONE resolver (`task_mod._verify_policy_pinned_last_green`, read
    from the BASE tree per SPEC-0186 rule 4) — never a second policy reader and never an enum table
    respelled here. FAIL-CLOSED: anything that is not the literal `never` — including an unresolved
    or uninjected policy — leaves the rank at 2, because isolating a member that did not need it costs
    one unamortised pass while batching one that DID need the pinned leg is a false green.

    UNKNOWN NEVER RANKS CHEAPEST. An oracle that was not injected, that raised, or that answered None
    (an unknown attempt during the rollout window, an unreadable ops carrier) falls THROUGH to the
    observable ladder — it never reaches rung 0. That is the same fail-closed direction as the policy
    read, pointed at the defect this card exists to remove: the cost of over-ranking a free branch is
    one un-amortised pass, the cost of under-ranking a paying one is handing it the road.

    UNDECIDABLE IS STILL ITS OWN ANSWER, AND IT STILL NEVER YIELDS ON EITHER SIDE (the T-11274
    two-positive-oracles shape, UNCHANGED by this card). `_land_member_changed_paths` answers `[]`
    both for a branch that is genuinely empty AND for one that cannot be diffed (gone, unborn, git
    error), and those two must not be conflated: reading an UNDIFFABLE branch as class 0 would make it
    look like the cheapest thing in the repo and would hand it the slot it cannot use. So an empty
    answer is None here, and a None on either side of the comparison simply does not yield — the
    fail-closed direction, whose whole cost is one un-yielded slot."""
    paths = _changed_paths(member)
    if not paths:
        return None                          # empty OR undiffable — see docstring; never ranked
    if _would_run_suite is not None:
        try:
            _runs = _would_run_suite(member)
        except Exception:                    # noqa: BLE001 — an oracle that fails is UNKNOWN, not free
            _runs = None
        if _runs is False:
            return 0                         # no suite runs at all — the genuinely free rung
    if not _verify_touch(paths):
        return 1                             # one pass: the ordinary candidate verify
    # A verify-surface touch buys a SECOND pass only where that leg actually runs (SPEC-0186 rule 9).
    return 1 if str(pinned_last_green or "") == "never" else 2

def _land_dirty_candidate_paths(main_wt: "Path | None", branches, *, _run_git_cap=None,
                                max_paths: int = 10,
                                _is_foldable_bookkeeping=None) -> "dict[str, list[str]]":
    """T-11508 (SPEC-0184 rule 11) — of `branches`, the ones whose WORKTREE holds uncommitted changes,
    each mapped to a BOUNDED list of the paths it must commit. A clean branch is simply absent.

    WHY FORMATION ASKS AT ALL, when the land path already refuses a dirty tree. Because it refuses it
    LATER — after the reservation, after the SPEC-0132 admission wait, at the front of a queue whose
    median wait was 12.2 minutes and whose p90 was 225.9 (n=309, week of 2026-08-25). By then the
    candidate has consumed a capped batch place, and if it was the HEAD it takes its peers' verify
    pass down with it. This is the same question the land asks, asked at the one moment when the
    answer is still free: 19 ms per worktree, 0.3 s across all twelve live at filing time.

    IT SEES WHAT THE CONFLICT ORACLE CANNOT. `_land_merge_probe` composes `merge-tree --write-tree`
    over two COMMITS; no commit-vs-commit question can observe a working tree. That is the whole gap
    this reader closes, and it is why this is a per-BRANCH precondition reader and not a second
    conflict authority — it never asks whether two branches can coexist.

    STRICTLY READ-ONLY, and that bound is the rule rather than an implementation nicety (SPEC-0184
    rule 11 / AC4). It runs a listing and a status; it never commits, stashes, checks out, merges, or
    calls `worktree sync` or any other writing sync/update operation on a candidate. Auto-merging into
    another session's LIVE worktree is precisely what the T-0362 worktree-stamp discipline forbids,
    and a candidate's worktree belongs to a session that is not this one.

    BOUNDED OUTPUT. Paths are sorted and truncated to `max_paths` with a trailing `+N more` marker, so
    one pathological tree cannot bloat the journal row this feeds. The truncation is visible rather
    than silent — a reader must be able to tell a 3-path tree from a 300-path one.

    FOLDABLE DIRT IS NOT DIRT (T-11700), and this is a NARROWING back onto the question this reader
    documents itself as asking, not a widening of what gets admitted. The land's question is
    `_fold_trailing_bookkeeping` with `refuse_nonfoldable=True` — "is there NON-foldable dirt?" — and
    this reader was asking a wider one, so an append-only `events.jsonl` excluded a candidate exactly
    like a forgotten source edit. It cost the PEER specifically: a head arrives at formation already
    folded clean by `cmd_land`, a peer is folded by nobody (see `_land_batch_members`'s HONEST BOUND
    ON THE HEAD ARM). Measured 2026-08-27: 9 `uncommitted-worktree-dirt` exclusions across 45
    formations, and task/T-11687 dropped from two consecutive ones over `events.jsonl` alone.

    `_is_foldable_bookkeeping` is INJECTED, never imported — this module is identity-agnostic kernel
    and never back-imports the host, and the notion's ingredients (the host-composed
    `_BOOKKEEPING_ALLOWLIST`) live there. Same shape, and the same reason, as
    `task.py#_require_clean_batch_for_close`'s injected `_is_journal_archive_dirt`. ABSENT ⇒ NOTHING
    IS FOLDABLE ⇒ byte-identical to before for every hermetic caller that injects none: the fail
    direction is toward the OLD, stricter answer, so an un-wired call site can only over-exclude,
    never under-exclude. It NARROWS THE REPORT TOO: what survives is the non-foldable remainder — the
    paths its operator must ACTUALLY commit — because a list naming `events.jsonl` sends them to
    stage a file the land was going to fold. MIXED DIRT STILL READS DIRTY, unchanged and deliberately:
    the remainder is non-empty, so a foldable path can never mask a source one. The T-11508 guard
    keeps every case it was built for.

    FAIL-OPEN TO ABSENT, per branch and in aggregate — a None `main_wt`, an unregistered branch, an
    unreadable tree, a nonzero or raising git, all yield "not dirty". Same direction, and the same
    reason, as `_land_batch_ineligible_branches` / `_land_rebaselining_branches` /
    `_land_supersession_marked_branches`: a missed exclusion costs exactly today's abort, while a
    spurious one would cost the batch capacity this whole spec exists to produce."""
    wanted = {str(b or "").strip() for b in (branches or ())}
    wanted.discard("")
    # NO RUNNER, NO ANSWER — and that is the fail-open direction, not a degradation. This module keeps
    # no module-level git runner (every caller injects one), so a caller that supplies none has given
    # this reader nothing to prove dirt WITH, and an unproven answer admits. Byte-identical to today
    # for every hermetic caller that injects none.
    if main_wt is None or not wanted or _run_git_cap is None:
        return {}
    runner = _run_git_cap
    try:
        listing = runner(["worktree", "list", "--porcelain"], main_wt)
    except Exception:                  # noqa: BLE001 — no listing == nothing proven (fail-open)
        return {}
    if getattr(listing, "returncode", 1) != 0:
        return {}
    # Parse the `worktree <path>` / `branch <ref>` record pairs — the same shape
    # `_own_open_work_batches` reads, and for the same reason: it is what git publishes.
    paths_by_branch: "dict[str, str]" = {}
    cur_path = None
    for line in (listing.stdout or "").splitlines():
        if line.startswith("worktree "):
            cur_path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and cur_path:
            br = line[len("branch "):].strip()
            if br.startswith("refs/heads/"):
                br = br[len("refs/heads/"):]
            if br in wanted:
                paths_by_branch[br] = cur_path
            cur_path = None
    out: "dict[str, list[str]]" = {}
    for br in sorted(paths_by_branch):
        try:
            st = runner(["status", "--porcelain"], Path(paths_by_branch[br]))
        except Exception:              # noqa: BLE001 — unreadable == clean (fail-open)
            continue
        if getattr(st, "returncode", 1) != 0:
            continue
        # porcelain v1 is `XY<space>PATH`, so the path starts at column 3. Do NOT strip the whole
        # line first — that eats the leading status-column space and mis-slices the path (the same
        # trap `_fold_trailing_bookkeeping` documents).
        dirty = sorted({ln[3:].strip() for ln in (st.stdout or "").splitlines() if ln.strip()})
        # T-11700: drop the paths the land would FOLD anyway, leaving the ones its operator must
        # actually commit. An un-injected predicate folds nothing (today's answer, exactly).
        if _is_foldable_bookkeeping is not None:
            dirty = [p for p in dirty if not _is_foldable_bookkeeping(p)]
        if not dirty:
            continue
        cap = max(1, int(max_paths))
        if len(dirty) > cap:
            dirty = dirty[:cap] + [f"+{len(dirty) - cap} more"]
        out[br] = dirty
    return out

def _land_dissolve_batch(members: "list[dict]", *, W: "Path | None" = None,
                         pre_sha: "str | None" = None, _run_git_cap=None,
                         _append_event, events_path: "Path | None" = None,
                         batch_id: "str | None" = None,
                         batch_state: "dict | None" = None,
                         assertions: "list[str] | None" = None,
                         red_isolation: "dict | None" = None,
                         failure_attribution: "dict | None" = None,
                         emitted_out: "list | None" = None,
                         timeout_marker: "str | None" = None,
                         _changed_paths=None, _test_files=None, _emit_land_member_verdicts=None, _land_attribute_failing_assertions=None, _land_mark_red_assertions=None, _land_red_batch_ineligible_members=None, _land_red_decline_record=None, _land_restore_candidate_head=None) -> int:
    """SPEC-0184 rule 4 (the RED half) — the combined candidate was red, so NO member lands and the
    batch DISSOLVES. Returns the number of `requeued-after-red-batch` rows journaled.

    TWO ACTS, AND BOTH ARE REQUIRED:
      1. RESET the candidate worktree back to `pre_sha`, so the peers' commits leave this branch's
         history. Without it a red batch strands other people's changes on a branch whose author
         never asked for them, and a later land of THIS branch would carry them — the exact "main
         holds a combination nothing verified" failure rule 4 forbids, arriving by the back door.
      2. JOURNAL a verdict for EVERY member. `main` is byte-identical because the ff is never
         reached, but a member that silently vanishes has no terminal signal, and T-11196's
         `_land_member_terminal_signal` reads exactly this row. A member re-queued for a PEER's red
         must be able to learn its own fate without reconstructing the batch (rule 5).

    THE MEMBER LIST IS THE MERGED SET, NEVER THE FORMED SET (audit-pre finding, absorbed mode-b
    2026-08-16). A peer dropped at candidate-merge was not in the verified tree, so it was not part
    of this red and must not be requeued for it or made batch-ineligible by it. The caller therefore
    hands over what `_land_merge_batch_into_candidate` returned.

    RESET FAILURE IS NOT MASKED AND NOT FATAL — and "not masked" is now literally true (T-11226).
    The restoration act is delegated to `_land_restore_candidate_head`, the ONE primitive all three
    sites share, which reads the reset's RETURNCODE and journals + prints an unperformable
    restoration instead of swallowing it. It stays NOT FATAL: the land is already aborting (the caller
    `_die`s immediately after), so raising here would replace a precise verify-failure diagnosis with
    a git error. The rows are journaled either way — the record of the dissolve is what the next slot
    reads. What CHANGED is only that a restoration this function's own docstring promises can no
    longer fail in silence; before T-11226 the guard `if pre_sha and ...` plus `except: pass` let it.

    THIS IS NO LONGER THE ONLY RESTORATION SITE, and must not be re-made into one. A red dissolve is
    one of several ways a land ends without landing; the catch-all in `cmd_land` covers the others
    (abort, exception, retries exhausted). This site stays because a dissolve knows its own reason and
    restores BEFORE the verdicts are journaled; it is the specific case, not the general guarantee.

    AT N<=1 IT IS A NO-OP THAT RUNS NO GIT AND EMITS NOTHING (rule 1). A singleton's own
    `land_completed` abort row IS its verdict in full, so there is nothing to dissolve and nothing to
    add; the emitter's own N=1 clause is the belt underneath this.
    """
    if len(members) <= 1:
        return 0
    _head = str((members[0] or {}).get("branch") or "") or None
    _peers = [str((m or {}).get("branch") or "") for m in members[1:]]
    _outcome = _land_restore_candidate_head(
        W, pre_sha, branch=_head, _run_git_cap=_run_git_cap,
        _append_event=_append_event, events_path=events_path,
        reason="red-batch-dissolve", batch_size=len(members), peers=_peers)
    # T-11226: tell the caller the branch is already back, so the catch-all restoration in `cmd_land`
    # does not repeat the act on a path that has just performed it. A repeat would be harmless (the
    # same reset to the same sha) but would journal a second row for one restoration, and a reader
    # counting rows would see two events for one act.
    if _outcome == _LAND_RESTORE_DONE and batch_state is not None:
        # CLEAR THE WHOLE CLAIM, not just the undo target (audit-post consult finding, 2026-08-17).
        # The catch-all is gated on "was a peer merged?" (peers / batch_size) precisely so a missing
        # `pre_sha` cannot silence it — so clearing `pre_sha` ALONE would leave the claim standing and
        # the catch-all would re-fire on a dissolve that had just SUCCEEDED, reporting a bogus FAILED
        # restoration (pre_sha now absent) on every red batch. The state must say what is true: this
        # branch no longer carries peers. Same shape the retry path already uses when it resets.
        batch_state.update({"pre_sha": None, "peers": [], "batch_size": 0})
    # T-11259 — THIRD ACT, and it is REPORT-ONLY. Before the verdicts are journaled, mark the ONE
    # member (if any) the red's pinned assertion is UNAMBIGUOUSLY attributable to, so its row carries
    # the CAUSE and not only the fact. It runs HERE, between the restore and the emit, because this is
    # where the member list is final and the assertions are still in hand; it decides nothing (the
    # member set, the verdict and `main` are all already fixed), and with its inputs absent it is a
    # no-op — so every existing caller and probe stays byte-identical. See
    # `_land_attribute_failing_assertions` for why all four of its gates fail closed.
    _land_attribute_failing_assertions(members, assertions, _changed_paths=_changed_paths,
                                       _test_files=_test_files)
    # T-11272 — FOURTH ACT: decide WHO the requeue makes batch-INELIGIBLE. Every member is still
    # journaled `requeued-after-red-batch` (rule 5's vocabulary, T-11196's terminal signal and the
    # `batch_size` payload are all untouched); what this adds is an explicit `batch_ineligible: False`
    # on the members the attribution PROVED innocent, so rule 4's one-round mark falls on the culprits
    # alone. It runs here, right after the attribution it consumes, because this is the only seam
    # holding both the final member list and the failing entries. The mark is written onto the member
    # RECORD and merely copied by the emitter — the same shape T-11258's eviction cause and T-11259's
    # attribution use, which is also what keeps a direct `_emit_land_member_verdicts` call byte-identical.
    # With no attribution, or with any part of the red unexplained, this marks EVERYONE exactly as
    # before; see `_land_red_batch_ineligible_members` for why the default is the blanket.
    # T-11714 — and the marker, so an ALL-timeout red penalises NOBODY. It is handed over from the
    # caller (which already holds `_VERIFY_TIMEOUT_MARKER` for its own `_timed_out` check) rather
    # than re-spelled here: one definition, CHARTER §P5. Absent, the marking is byte-identical to
    # before — the carve-out cannot open on plumbing that never arrived.
    _ineligible = _land_red_batch_ineligible_members(members, assertions,
                                                     timeout_marker=timeout_marker)
    for _i, _m in enumerate(members):
        if _i not in _ineligible and isinstance(_m, dict):
            _m["batch_ineligible"] = False
    # T-11331 — FIFTH ACT: CARRY THE RED CAUSE TO MAIN. Mark every member record with the failing
    # assertions this abort already surfaced, so the emitter copies them onto rows that are written
    # to MAIN's journal.
    #
    # THE ROWS REACH MAIN AND THE CAUSE DID NOT — that asymmetry is the whole defect. A batch land
    # runs on the HEAD member's branch, so the abort's own `land_completed` row (which HAS carried
    # `failing_assertions` since T-9307) is written to THAT worktree's journal — and a failed land
    # never integrates, so the row stays there forever. The member verdict rows, by contrast, are
    # emitted with `events_path=main_wt / "events.jsonl"`. Measured 2026-08-19T20:07:40Z: main
    # carried three `requeued-after-red-batch` verdicts and not one word of cause, and the three
    # failing assertions were readable only by opening the head member's events.jsonl by hand. A
    # controller on main could not answer "which member poisoned the batch" — the first question
    # triage asks. This copies the answer onto the rows that already make the trip.
    #
    # EVERY MEMBER, and that is the difference from the attribution above. The red is a property of
    # the BATCH: the COMBINED candidate failed, and the batch is explicitly forbidden to name a
    # culprit (`evicted-as-culprit` is absent from the vocabulary by design — bisection is out of
    # SPEC-0184's scope). `superseded_assertions` answers a DIFFERENT and fail-closed question —
    # "which pinned assertion is provably THIS member's own" — and is untouched here: it stays at
    # most one member's, decided by four gates that all fail closed. This key claims nothing about
    # whose change it was; it states what killed the batch every one of these members was in, so
    # ANY ONE of the rows answers the triage question from main alone.
    #
    # A MEMBER-RECORD KEY WRITTEN IN EXACTLY ONE PLACE, for the reason T-11322 spelled out when it
    # chose `unaccounted_reason` over `removal_reason`: the emitter's copying is VERDICT-AGNOSTIC,
    # which is only sound while the set of paths that mark the key is known and small. T-11494 gave
    # the key a SECOND marking ARM — the peers-release, which carried ten of the twelve red batches
    # measured on 2026-08-23/24 — and the soundness argument survives UNCHANGED because the two arms
    # are the two ends of the same red fork and BOTH emit `requeued-after-red-batch`. What holds it
    # is that there is still exactly ONE marking SITE: `_land_mark_red_assertions`, which owns the
    # gate and the honesty argument and is pinned as the sole writer — with its caller set — by the
    # fence in `tests/test_t11331_batch_join_key.py`. So every `landed` / `evicted-for-conflict` /
    # `dropped-dead-member` / `unaccounted` row still stays byte-identical without the emitter
    # having to know which caller it is serving.
    #
    # GATED ON A NON-EMPTY `assertions` (in the helper), so ABSENT MEANS UNRECORDED rather than "no
    # cause existed" — the same honesty the three marks above hold to. Every existing caller and
    # probe that passes no assertions (the whole hermetic suite) is byte-identical.
    _land_mark_red_assertions(members, assertions)
    # T-11348 — SIXTH ACT: CARRY THE ANALYSIS'S DECLINE TO MAIN. Mark every member record with the
    # ALREADY-COMPUTED reason the eviction path evicted nobody, so the emitter copies it onto rows
    # that are written to MAIN's journal.
    #
    # THE SURFACE IS THE POINT, NOT THE CONTENT (AC4). The reason already reaches the head member's
    # own `land_completed` abort row via `_abort_detail` — and that row is written in the HEAD
    # BRANCH's worktree journal, where it stays until that branch lands. Measured 2026-08-20: batch
    # bat-1de6d30605bd went red at 17:10:45Z and its abort rows reached main only at 17:56:08Z, six
    # hours after the controller needed them to decide what to do about the red batch. These verdict
    # rows are emitted with `events_path=main_wt / "events.jsonl"`, so they make the trip NOW — the
    # same asymmetry T-11331 closed for the red CAUSE, closed here for the eviction DECISION.
    #
    # EVERY MEMBER, like `red_assertions` and unlike `superseded_assertions`: a decline is a fact
    # about the ANALYSIS of this batch, claiming nothing about whose change it was. That is also
    # which side of `_land_member_removal_sink`'s line it sits on — a fact about THIS attempt, not a
    # durable claim about a member's changes — which is why it does NOT grow rule 5's verdict
    # vocabulary and every member still reads `requeued-after-red-batch`.
    #
    # A NEW MEMBER-RECORD KEY NOBODY ELSE WRITES (`red_decline`), for the reason T-11322 spelled out
    # when it chose `unaccounted_reason` over `removal_reason`: the emitter's copying is
    # VERDICT-AGNOSTIC, which is only sound while ONE path marks the key. The ROW key is
    # `red_isolation_decline`, beside the `red_isolation` a reader already knows.
    #
    # GATED ON A SUPPLIED RECORD, so ABSENT MEANS UNRECORDED and every existing caller and probe
    # (the whole hermetic suite, which passes none) is byte-identical. What is NOT treated as
    # absence is `undecidable`: the recorder returns it as a NAMED answer, because "the oracle ran
    # and could not decide" and "the oracle never ran" being indistinguishable IS the defect.
    if red_isolation is not None:
        _decline = _land_red_decline_record(red_isolation, members)
        for _m in members:
            if isinstance(_m, dict):
                _m["red_decline"] = dict(_decline)
    # T-11710 — SEVENTH ACT: CARRY WHOSE THE RED WAS, ON THE ROWS THAT REACH MAIN. The decline above
    # says nobody was EVICTED; this says who the failure BELONGED to. `_land_failure_attribution_probe`
    # already computed it this attempt, under the same admission slot, and the caller hands it over
    # VERBATIM — never recomputed here (a second probe run would pay real test subprocesses twice for
    # an answer already in hand). The emitter's copy block is verdict-agnostic and already exists
    # (T-11495): only the MARKING is added.
    #
    # THE ASYMMETRY THIS CLOSES IS T-11495's, ON ITS SIBLING PATH. That card carried the attribution
    # onto the PEERS-RELEASED rows because a released red retries instead of aborting, so no
    # `land_completed` row is written and the verdict never travelled. A DISSOLVE does write one — but
    # in the HEAD MEMBER's worktree journal, where it stays until that branch lands (measured
    # 2026-08-20: six hours). So on main a reader saw four `requeued-after-red-batch` rows naming the
    # failing assertions and the decline, and NOT ONE WORD about whether the red was even a member's:
    # `outcome: main` — the red is `main`'s, no member owns it — was readable only by opening the head
    # member's events.jsonl by hand. That is the same trip T-11331 made for the CAUSE and T-11348 for
    # the eviction DECISION, made here for the OWNER.
    #
    # A SECOND MARKING SITE FOR AN EXISTING KEY, and the T-11322 soundness argument survives for the
    # reason T-11494's second arm did: the two sites are the two ends of the SAME red fork, they mark
    # the SAME record from the SAME producer under the SAME meaning, and both emit
    # `requeued-after-red-batch` — so a reader joining the two surfaces learns no new vocabulary.
    #
    # EVERY MEMBER, like `red_assertions` and the decline: whose the red is, is a fact about the
    # BATCH's failure, claiming nothing about whose CHANGE it was. GATED ON A SUPPLIED RECORD, so
    # ABSENT MEANS NOT HANDED OVER (never "the red had no owner") and every existing caller and probe
    # that passes none — the whole hermetic suite — is byte-identical.
    if failure_attribution:
        for _m in members:
            if isinstance(_m, dict):
                _m["failure_attribution"] = dict(failure_attribution)
    return _emit_land_member_verdicts(members, "requeued-after-red-batch",
                                      _append_event=_append_event, events_path=events_path,
                                      batch_id=batch_id, batch_size=len(members),
                                      emitted_out=emitted_out)

def _land_drop_dead_members(members: "list[dict]", *, _append_event,
                            events_path: "Path | None" = None,
                            batch_id: "str | None" = None,
                            batch_size: "int | None" = None,
                            emitted_out: "list | None" = None,
                            _pid_alive=None, _emit_land_member_verdicts=None, _land_member_claim_held=None) -> "tuple[list[dict], list[dict]]":
    """Partition a batch on `_land_member_claim_held`; journal `dropped-dead-member` for the dead.

    Returns `(survivors, dropped)`. SPEC-0184 rule 6: a dead member is DROPPED, the BATCH IS NOT —
    one claimant's death must not destroy a verify pass carrying uninvolved peers, which would turn
    a safety property into a denial of service. So this removes members; it never aborts the pass.

    The dropped members are journaled with the TRUE batch size, not the size of the dropped subset —
    see `_emit_land_member_verdicts`'s `batch_size` parameter for why that distinction is load-bearing.
    Survivors are NOT journaled here: their verdict is whatever the pass goes on to produce, and
    emitting one now would claim an outcome that has not happened yet.

    T-11870 — AND THE TRUE SIZE HAS TO BE HANDED IN, WHICH IS WHY `batch_size` EXISTS. The paragraph
    above was an assertion this function could not keep on its own: it derived the size from its own
    incoming list, while the production caller hands it a list the ff-carry filter has ALREADY
    narrowed. So every dropped-dead row on the real path recorded the SURVIVING subset under a key
    that names the batch — the docstring and the code disagreed, and the sibling `landed` emit one
    call below was the one telling the truth (it is passed `_batch_at_ff or None`). The size is now
    the CALLER'S to state, from the same expression that sibling uses: one source for the batch size
    on both emits, never two derivations that can drift.
    ABSENT ARGUMENT FALLS BACK TO `len(members)` — today's exact value — so every hermetic caller and
    every direct test call is byte-identical, and a caller that genuinely IS the whole batch (a
    singleton, an unfiltered list) needs to say nothing. `0` and `None` both take the fallback:
    neither is a batch size anything could have had, and the sibling emit spells its own argument
    `_batch_at_ff or None` for the same reason.
    """
    survivors, dropped = [], []
    for _m in members:
        state, _reason = _land_member_claim_held(_m, _pid_alive=_pid_alive)
        (survivors if state == "held" else dropped).append(_m)
    if dropped:
        _emit_land_member_verdicts(dropped, "dropped-dead-member", _append_event=_append_event,
                                   events_path=events_path, batch_id=batch_id,
                                   batch_size=batch_size or len(members), emitted_out=emitted_out)
    return (survivors, dropped)

def _land_failure_attribution_probe(bad: "list | None", *,
                                    main_wt: "Path | None" = None,
                                    merged_base: "str | None" = None,
                                    test_subdir: "str | list[str]" = _LAND_CANDIDATE_TEST_SUBDIR,
                                    workers: "int | None" = None,
                                    _run_git_cap=None, _run_verify_tests=None,
                                    _VERIFY_TIMEOUT_MARKER: "str | None" = None,
                                    _surface_failing_assertions=None,
                                    _run_at_base=None, _land_red_isolation_entries=None, _land_red_isolation_reproduced=None) -> dict:
    """T-11464 — WHOSE failure is this red: MAIN's, or this branch's? Returns a RECORD; decides
    nothing, journals nothing, and gates nothing. The caller reports it beside an abort whose class,
    message tail and exit are unchanged.

    THE QUESTION IS ONE STEP, AND IT WAS BEING DONE BY HAND. On 2026-08-22 T-11442's worker proved a
    land-verify failure was not its own by re-running the failing assertion on an untouched `main`
    checkout — the third of three hand-assembled steps, after which its work still sat unlanded ~18h.
    On 2026-08-23 a pre-existing main breakage made every branch pay a FULL 420-560s verify to
    rediscover the same fact independently. Re-running ONLY the failing files at the merge-base costs
    seconds and answers it mechanically.

    IT NAMES THE CAUSE; IT NEVER SKIPS IT (the owner bound this card was written under). Nothing is
    waived, excluded, retried or weakened on the strength of this record — an `outcome: main` land
    aborts exactly as loudly as it does today, and the recovery for a broken main stays what it was.
    The value is diagnostic time, not a bypass, and a reader who mistakes the two would turn the one
    mechanism that makes a broken main CHEAP TO DIAGNOSE into one that makes it cheap to ignore.

    THE RECORD IS ALWAYS COMPLETE, INCLUDING WHEN IT SAYS NOTHING:
    `{"outcome": ..., "reason": ..., "failing": [...], "at_main": [...], "at_branch": [...]}`.
    A decline is an OUTCOME with a named reason, never an empty return — otherwise "the probe ran and
    could not decide" is indistinguishable from "the probe never ran"
    (`lessons/a-report-only-signals-differential-is-indistinguishability`).

    BOTH DIRECTIONS ARE COMPUTED, PER PAIR, FROM THE SAME RUN (AC1's DIFFERENTIAL). `at_main` holds
    the `(file, assertion)` pairs the merge-base reproduced; `at_branch` holds those it did not. The
    outcome is `main` only when `at_branch` is EMPTY and `branch` only when `at_main` is — so an
    implementation that always blamed main would have to invent reproductions it never observed, and
    one that always blamed the branch would have to discard them.

    THE TREE IS `merged_base`, NOT A SECOND FEED (CHARTER §Principle 5). It is the value this land
    ALREADY resolved for main's tip and hands to `_land_red_isolation_probe` at the same fork; a
    private `merge-base` call could disagree about what "main without this branch" IS, and then
    attribution and isolation would be reasoning about different trees. It is checked out DETACHED
    into a throwaway worktree, removed in a `finally` on every path. `main` and the branch are
    untouched throughout — this probe never merges, commits or moves a ref.

    THE GATES AND THE RUNNER ARE THE ONES ALREADY SHIPPED. `_land_red_isolation_entries` decides
    which reds are answerable at all (a pinned last-green entry, a verify TIMEOUT, a runner launch
    failure, a non-`test failed:` entry and an entry naming no assertion are each refused there, for
    the reasons stated at that function); `_run_verify_tests(..., only=...)` runs them — same
    hermetic per-subprocess sandbox, same per-file timeout, same `test failed:` shape; and
    `_land_red_isolation_reproduced` reads the verdict back at PAIR level. Nothing is journaled here:
    no `journal_path`, no `metrics_out`, so the probe writes no event and no SPEC-0181 shadow record.

    A FAILING FILE THAT DOES NOT EXIST AT THE MERGE-BASE IS THE BRANCH'S, and that is sound rather
    than a guess: the file is there only because this branch added it, so the base cannot fail it. A
    red made ENTIRELY of such files runs nothing and attributes everything to the branch — an answer,
    not a skipped check.

    EVERY GATE FAILS CLOSED TO `undecidable`, which the caller reads as today's behaviour: no
    answerable failing set, no reader (`_run_at_base` is the ONE hermetic injection seam; without it
    the git + runner set is required in full), an unusable merge-base worktree, a runner that could
    not run, or a run that could not be READ as a verdict.
    """
    import shutil
    import tempfile

    rec: dict = {"outcome": "undecidable", "reason": None, "failing": [],
                 "at_main": [], "at_branch": [], "quarantined": []}
    # T-11807 — the pairs whose self-declared attribution quarantine is ADMITTED. Empty until the
    # merge-base tree is in hand, so every path that never reaches it quarantines NOTHING.
    admitted_quarantine: set = set()

    def _undecidable(reason: str) -> dict:
        rec["outcome"] = "undecidable"
        rec["reason"] = reason
        return rec

    if _run_at_base is None and not (main_wt is not None and merged_base
                                     and _run_git_cap is not None and _run_verify_tests is not None):
        return _undecidable("no-attribution-reader")

    failing, refusal = _land_red_isolation_entries(bad, _VERIFY_TIMEOUT_MARKER,
                                                   _surface_failing_assertions)
    if refusal:
        return _undecidable(refusal)
    rec["failing"] = list(failing)
    # The FILE half of each pair, for the two places that address files rather than failures: the
    # presence check against the merge-base tree, and the runner's `only=` selection. Same shape as
    # `_land_red_isolation_probe` — one derivation of "the file this pair lives in", not two.
    failing_files: list = []
    for _pair in failing:
        _n = str(_pair).partition(": ")[0]
        if _n not in failing_files:
            failing_files.append(_n)

    def _decide(reproduced: list) -> dict:
        """The pair-level split, and the ONLY place an outcome other than `undecidable` is chosen.

        T-11807 — QUARANTINED PAIRS ARE PARTITIONED OUT FIRST, into a bucket of their own. They land
        in NEITHER `at_main` nor `at_branch`: a quarantined assertion is evidence about nobody, and
        dropping it into either side would trade the false branch-blame this closes for a false
        main-blame in the other direction. The remainder splits exactly as it did before, so a red
        carrying no quarantined pair is decided byte-for-byte as today.

        A red made ENTIRELY of quarantined pairs is `undecidable` WITH ITS OWN NAMED REASON — not
        `main`, which is what the empty-`at_branch` test below would otherwise conclude from an empty
        remainder, and which would be precisely that other-direction false verdict."""
        rec["quarantined"] = [p for p in failing if p in admitted_quarantine]
        rest = [p for p in failing if p not in admitted_quarantine]
        rec["at_main"] = [p for p in rest if p in reproduced]
        rec["at_branch"] = [p for p in rest if p not in reproduced]
        if not rest:
            rec["outcome"], rec["reason"] = "undecidable", "all-failing-assertions-quarantined"
        elif not rec["at_branch"]:
            rec["outcome"], rec["reason"] = "main", "every-failing-assertion-reproduces-at-merge-base"
        elif not rec["at_main"]:
            rec["outcome"], rec["reason"] = "branch", "no-failing-assertion-reproduces-at-merge-base"
        else:
            rec["outcome"], rec["reason"] = "mixed", "partially-reproduces-at-merge-base"
        return rec

    if _run_at_base is not None:
        try:
            out = _run_at_base(list(failing))
        except Exception as _e:                # noqa: BLE001 — an injected reader that raised
            return _undecidable(f"base-run-error:{type(_e).__name__}")
        reproduced, refusal = _land_red_isolation_reproduced(out, list(failing),
                                                             _VERIFY_TIMEOUT_MARKER,
                                                             _surface_failing_assertions)
        if refusal:
            return _undecidable(refusal)
        return _decide(list(reproduced))

    wt = Path(tempfile.mkdtemp(prefix="yitc-attribution-"))
    shutil.rmtree(wt, ignore_errors=True)      # `git worktree add` needs a NON-existent path
    try:
        add = _run_git_cap(["worktree", "add", "--detach", str(wt), merged_base], main_wt)
        if getattr(add, "returncode", 1) != 0:
            return _undecidable("merge-base-worktree-unavailable")
        # T-11204: `test_subdir` is ONE repo-relative dir (every pre-T-11204 caller) or the SET the
        # candidate sweep actually swept. The oracle MUST look where the sweep looked — a file
        # resolved anywhere else answers a different question than the red it is explaining.
        _subs = [test_subdir] if isinstance(test_subdir, (str, Path)) else list(test_subdir or [])
        _subs = [str(s) for s in _subs] or [_LAND_CANDIDATE_TEST_SUBDIR]
        # T-11807 — ADMIT a self-declared quarantine ONLY when the SAME declaration is already
        # present in the MERGE-BASE's copy of that file: main WITHOUT this branch's diff.
        #
        # WITHOUT THIS THE MECHANISM WOULD BE ITS OWN BYPASS (audit-pre pass 2, high). The marker is
        # read out of the failing assertion's text, which is authored by whatever is in the tree
        # under attribution — so on the text alone a branch could attach a quarantine to its OWN new
        # failing assertion and clear its OWN blame. Requiring the declaration to pre-date the branch
        # makes it a statement main has already accepted, not one the accused writes for itself.
        #
        # It costs no new machinery and no second checkout: `wt` is the detached merge-base tree this
        # probe already has in hand for its re-run, so admission is one read of a file that is right
        # there. FAIL-CLOSED IN EVERY DIRECTION — a file absent at the base, an unreadable one, or a
        # base copy carrying no such marker is NOT admitted and takes ordinary attribution; and a
        # path that never reaches this block (the injected reader, an unusable base) admits nothing
        # at all. The honest consequence, which is correct rather than regrettable: a quarantine
        # takes effect from the land AFTER the one that DECLARES it, so no change can exempt itself.
        for _pair in failing:
            if not _land_attribution_quarantine_reason(_pair):
                continue
            _decl = _LAND_ATTRIBUTION_QUARANTINE_RE.search(str(_pair)).group(0)
            _name = str(_pair).partition(": ")[0]
            for _s in _subs:
                try:
                    if _decl in (wt / _s / _name).read_text(encoding="utf-8", errors="replace"):
                        admitted_quarantine.add(_pair)
                        break
                except OSError:                 # noqa: BLE001 — absent/unreadable = NOT admitted
                    continue
        present = [n for n in failing_files
                   if any((wt / s / n).exists() for s in _subs)]
        if not present:
            # Nothing the merge-base tree even CONTAINS. It cannot fail a file that is not there, so
            # the whole red is this branch's — a positive answer, not an unrun check.
            return _decide([])
        try:
            out = _run_verify_tests([wt / s for s in _subs], wt, workers=workers, only=set(present))
        except Exception as _e:                # noqa: BLE001 — the runner itself could not run
            return _undecidable(f"base-run-error:{type(_e).__name__}")
        _asked = [p for p in failing if str(p).partition(": ")[0] in present]
        reproduced, refusal = _land_red_isolation_reproduced(out, _asked, _VERIFY_TIMEOUT_MARKER,
                                                             _surface_failing_assertions)
        if refusal:
            return _undecidable(refusal)
        # A pair whose FILE is absent from the base was never asked and cannot have reproduced — it
        # falls into `at_branch` by the same soundness argument as the all-absent case above.
        return _decide(list(reproduced))
    finally:
        try:
            _run_git_cap(["worktree", "remove", "--force", str(wt)], main_wt)
        except Exception:                      # noqa: BLE001 — cleanup never masks the verdict
            pass
        shutil.rmtree(wt, ignore_errors=True)
        try:
            _run_git_cap(["worktree", "prune"], main_wt)
        except Exception:                      # noqa: BLE001
            pass

def _land_form_batch(queue: "list[dict]", *, batch_max: int = _LAND_BATCH_MAX,
                     engaged: bool = True, admitter=None,
                     excluded_out: "list | None" = None,
                     prefilter=None) -> "tuple[list[dict], list[dict]]":
    """SPEC-0184 rule 1 + Parameters — cut the candidate queue into `(members, remainder)`.

    `queue` is ONE ordered candidate list whose HEAD is this land (the slot holder), with the queued
    peers behind it. The cap therefore counts the WHOLE membership, which is what makes an off-by-one
    unrepresentable: `len(members) <= batch_max` for every input (audit-pre finding 1, 2026-08-16 —
    an earlier plan added self ON TOP of `batch_max` queued peers, forming batches of five).

    NOT ENGAGED ⇒ a batch of ONE and everyone else waits. That is rule 2's fail-closed consequence,
    and it is expressed HERE as a slice rather than as an early return with its own return shape, so
    the disengaged path is the SAME path — no second code path to choose between (CHARTER §P1).

    The REMAINDER is returned rather than dropped: a queue of `batch_max + 1` forms a full batch PLUS
    a remainder that waits for the next slot — never an oversized batch, and never a silently lost
    member.

    T-11309 — WITH AN `admitter`, THE CAP IS REACHED BY WALKING, NOT BY SLICING. `queue[:n]` takes the
    first `n` candidates whether or not they can coexist, so a candidate proven unmergeable consumed a
    capped place and the replacement behind it was sliced away before rule 3 could discover the
    problem. Measured: batches of 4 landing 3 and 2 with up to EIGHT branches queued. Given an
    admitter this walks the queue IN ORDER instead, admitting a candidate only when the cheap
    predictor says it merges with those already selected, SKIPPING one that does not, and CONTINUING
    down the remainder until the cap or exhaustion. Back-filling after a skip is not a feature added
    here — it is simply what walking does and slicing could not.

    QUEUE ORDER STILL SETS PRIORITY, and this is load-bearing rather than incidental. Members are
    appended in ITERATION order and nothing in this function sorts, ranks, scores or reorders, so
    waiting time — not mergeability — decides who is first, and a skipped branch is first in line in
    a round where nothing selected ahead of it conflicts. A selector that reordered the queue by
    compatibility would satisfy the back-fill goal and be WRONG.

    THE HEAD IS NEVER SKIPPABLE AND IS SEEDED EXPLICITLY. `queue[0]` holds the land slot; it is
    admitted without consulting the oracle, exactly as rule 3 refuses to evict it. But the accumulator
    must PROVABLY hold it before any peer is judged, so the walk calls `admitter.seed(head)` first —
    and only when a peer actually follows, so rule 1's byte-identity for a quiet repo is untouched: a
    queue of one (or a disengaged land, `n == 1`) runs no probe, no subprocess and writes no object.

    A SKIP IS RECORDED OR IT DID NOT HAPPEN. Every skipped candidate appends
    `{branch, reason: _LAND_INCOMPATIBLE_EXCLUSION_REASON}` to `excluded_out`, the same sink the
    cost-class and supersession filters write. A drop that writes no row is indistinguishable from a
    queue that was simply empty — the measured 2026-08-17 blindness — and `queue_depth` is derived
    from this sink, so a silent skip would be wrong in both directions at once.

    WITHOUT AN `admitter` THE BODY IS THE UNCHANGED SLICE, so every hermetic caller that injects none
    keeps today's behaviour byte-for-byte.

    T-11365 — `prefilter` IS AN EXTRA PREDICATE ON THIS EXISTING GATE, NOT AN EJECTION PATH. It
    answers a PER-BRANCH question ("does this candidate's own diff violate a corpus-integrity
    guard?"), which is the shape the cost-class and supersession filters already have, and it is
    consulted BEFORE the pairwise admitter because a candidate ineligible on its own never needs a
    coexistence answer. A returned reason string SKIPS the candidate and records it in
    `excluded_out`; `None` admits. Nothing else changes: the walk, the skip and the back-fill are
    all T-11309's, so the violator's place goes to the next waiter exactly as an incompatible
    candidate's does, and the innocent peers behind it pay nothing.

    MULTIPLE VIOLATORS ARE ALL SKIPPED, and that is sound HERE where it is not for a red batch. A
    corpus violation is a property of ONE candidate's OWN diff computed against the land base — it
    needs no peer and admits no ambiguity — so the two-or-more-owners silence rule that governs
    assertion attribution (`_land_attribute_failing_assertions`, which records nothing rather than
    guess) simply does not apply: nothing is being attributed.

    THE HEAD IS NOT PREFILTERED HERE, and its case is answered ELSEWHERE rather than exempted
    (audit-pre finding 1, high, 2026-08-20). `queue[0]` holds the land slot, so skipping it is
    meaningless — it IS the land. What matters is that a violating head must not DRAG PEERS IN, and
    that is decided one level up by DISENGAGING formation (rule 2 already expresses "not engaged"
    as a batch of one with everyone else waiting, on this same path). By the time a queue reaches
    this function with `engaged=True`, its head has already been cleared.

    `prefilter=None` keeps every current caller byte-for-byte, exactly as `admitter=None` does.
    """
    n = max(1, int(batch_max)) if engaged else 1
    if admitter is None and prefilter is None:
        return (list(queue[:n]), list(queue[n:]))
    members: "list[dict]" = []
    remainder: "list[dict]" = []
    for i, m in enumerate(queue):
        if len(members) >= n:
            remainder.append(m)                # past the cap — waits for the next slot, as today
            continue
        br = str((m or {}).get("branch") or "")
        if i == 0:
            if len(queue) > 1 and admitter is not None:
                admitter.seed(br)              # lazy: a solo formation probes nothing at all
            members.append(m)
            continue
        # T-11365 — the PER-BRANCH predicate runs FIRST: a candidate ineligible on its own diff
        # never needs the pairwise coexistence answer, and asking the cheap question before the
        # expensive one is the same ordering the cost-class filter already uses upstream.
        _pf = prefilter(br, m) if (prefilter is not None and br) else None
        if _pf is not None:
            if excluded_out is not None:
                _row = {"branch": br, "reason": _LAND_CORPUS_VIOLATION_EXCLUSION_REASON}
                # MEMBER-DIRECTED DELIVERY (AC9) — the row carries the guard's OWN message, keyed
                # to the branch that must act. Today a member's land log shows only `WAITING for
                # the land reservation` while the rejection goes to the batch head's process, so
                # the violating branch cannot self-diagnose; carrying the cause on the row that
                # already reaches main is the same answer T-11331 gave for the red-batch cause.
                # NO row is written for an innocent peer, so nobody is told they caused anything.
                if isinstance(_pf, dict):
                    _row.update({k: v for k, v in _pf.items() if k not in ("branch", "reason")})
                else:
                    _row["cause"] = str(_pf)
                excluded_out.append(_row)
            continue
        if not br or admitter is None or admitter.admit(br):
            members.append(m)
            continue
        if excluded_out is not None:
            excluded_out.append({"branch": br,
                                 "reason": _LAND_INCOMPATIBLE_EXCLUSION_REASON})
    return (members, remainder)

def _land_git_is_ancestor(rev: str, desc: str, wt: "Path | None", *,
                          _run_git_cap=None) -> "bool | None":
    """Three-valued ancestry — True / False / None (unresolvable). `merge-base --is-ancestor` exits 0
    for yes and 1 for no; ANY other exit — and any exception — is an UNANSWERED question, never a `no`.

    ONE ancestry idiom for the whole land path (CHARTER §P1 F1/F2 + §P5). The batch-membership test
    (`_land_merge_batch_into_candidate`: is this peer already on the candidate?) and the post-ff
    verdict filter (`_land_members_carried_by_ff`: did THIS ff carry it?) ask the same question of
    different pairs of revisions. They must never drift apart about what "already there" means, and a
    single helper both read is the only shape in which they cannot.
    """
    if _run_git_cap is None or wt is None or not rev or not desc:
        return None
    try:
        r = _run_git_cap(["merge-base", "--is-ancestor", rev, desc], wt)
    except Exception:                          # noqa: BLE001 — unanswered, not answered "no"
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None

def _land_known_broken_establishing_sha(since: str, main_wt: Path, *, _run_git_cap) -> "str | None":
    """T-11469 — the sha main's tip carried when a known-broken record was ESTABLISHED, or None.

    IT IS DERIVED, BECAUSE IT CANNOT BE READ. AC1 asks the refusal to name the establishing sha, and
    the establishing row cannot supply one: a record is established by a land's attribution probe
    reproducing the failure at the merge-base, which happens on an ABORT — an abort fast-forwards
    nothing, so `_emit_land_abort` records no `sha` at all (measured on this repo's own journal: every
    `failure_attribution` row carrying an `at_main` pair has `sha: None`). Reading a key that is
    structurally absent would name nothing; asking main's own history what its tip WAS at that instant
    names the tree the probe actually ran against.

    ONE git call, no journal read — the fold above already did the only journal pass there is.

    None IS AN ANSWER, and the caller prints it as one. A repo whose history does not reach back that
    far, an unparseable stamp, a git that could not run: the refusal still fires (the sha is
    DIAGNOSTIC — the evidence is the record), and the message says the sha could not be resolved
    rather than inventing a plausible one.
    """
    if not since or not str(since).strip():
        return None
    try:
        r = _run_git_cap(["rev-list", "-1", f"--before={str(since).strip()}", "main"], main_wt)
    except Exception:                          # noqa: BLE001 — no git, no answer, no invention
        return None
    out = (r.stdout or "").strip()
    return out if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", out or "") else None

def _land_layer_runs_for(ops, paths: "list[str]", *, _subject_globs_would_skip=None) -> "bool | None":
    """T-11278 — on a project-authored verify, would ANY declared layer actually RUN for these paths?
    `True` at least one layer runs, `False` every layer would be skipped, `None` undecidable.

    PURE OVER AN ALREADY-READ MAPPING, and that is a contract, not a convenience. The ops carrier has
    ONE reader in this file (`_land_batch_engagement`), which publishes what it parsed via `ops_out`;
    opening the carrier again here would be a second read of one file that can disagree with the
    first, and T-11281's guard refuses it by name. So this function never touches disk.

    THE CARRIER IS `subject_globs`, NEVER `covers` (corrected 2026-08-18, owner-surfaced). They are
    different declarations with OPPOSITE defaults: `covers:` names the test surface a layer OWNS
    (SPEC-0152 delegation), while `subject_globs:` is what the verify seam skips on — and a layer
    declaring NO `subject_globs` runs ALWAYS. kupiclub's `stack` declares covers `[tests/**]` and
    subject `[app/**, ...]`, so a change under `app/` really runs it and PAYS while a covers-read
    calls it free: the false consumer saving this cohort exists to prevent, from the other side.

    THE SKIP VERDICT IS NOT RE-DERIVED. `_subject_globs_would_skip` is the pure authority
    `_subject_scoping_skip_layers` uses at the real verify seam; this asks it the same question per
    layer, so the metric and the gate that decides what a land pays cannot answer differently.

    A WAIVED layer, or one with no executable `command:`, runs for nothing whatever its globs say —
    the same executability test `_consumer_tests_delegation` applies. FAIL-CLOSED: an absent or
    section-waived carrier is None, never False, because "no layer runs" and "we could not tell" must
    not collapse into one answer."""
    if not isinstance(ops, dict):
        return None
    ver = ops.get("verify")
    if not isinstance(ver, dict) or isinstance(ver.get("waiver"), dict):
        return None                            # no layers in force — undecidable, never "no"
    layers = ver.get("layers")
    if not isinstance(layers, list) or not layers:
        return None
    if not paths:
        return None                            # no diff to reason a disjoint subject against
    saw_runnable = False
    for ly in layers:
        if not isinstance(ly, dict) or isinstance(ly.get("waiver"), dict):
            continue
        if not str(ly.get("command") or "").strip():
            continue                           # declared but not executable: it runs for nothing
        saw_runnable = True
        if not _subject_globs_would_skip(list(paths), ly.get("subject_globs")):
            return True                        # this layer runs for this diff — the member pays
    return False if saw_runnable else None

def _land_live_queue_depth(members: "list", queue_excluded: "list | None") -> int:
    """T-11323 — `queue_depth`: the LIVE candidates this formation saw, admitted or not.

    Two terms, and both are needed for the number to mean "how loaded was the queue":

      * the admitted PEERS (`len(members) - 1`) — the head holds the slot, it is not queued behind
        itself, which is the same arithmetic the pre-fix derivation used and the reason a solo
        formation contributes zero here;
      * the DISTINCT excluded branches whose reason is not in `_LAND_NOT_LIVE_EXCLUSION_REASONS` —
        candidates that WERE waiting at the read instant and that a downstream filter declined to
        carry. They are load: a reader asking "was there anyone behind me?" is answered yes.

    The two book-keeping rules are exactly the ones `queue_dispositions` already applies to the same
    branches, reused rather than re-derived, so the two fields on one row can never disagree about a
    branch: a branch is counted ONCE however many sink rows it collected (FIRST reason wins — a
    branch excluded twice is one candidate), and a branch in `members` is never also counted as
    queued (admission wins over any sink row that also names it).

    This function decides a REPORT and nothing else. Which branches are admitted, the sink's own
    contents, and the quiet-repo no-row clause are all untouched by it."""
    depth = max(0, len(members) - 1)
    admitted = {str((m or {}).get("branch") or "") for m in (members or ())}
    seen: "set[str]" = set()
    for x in (queue_excluded or ()):
        br = str((x or {}).get("branch") or "")
        if not br or br in admitted or br in seen:
            continue
        seen.add(br)                           # FIRST reason wins, as in the disposition fold
        if str((x or {}).get("reason") or "") not in _LAND_NOT_LIVE_EXCLUSION_REASONS:
            depth += 1
    return depth

def _land_mark_red_assertions(members: "list[dict]", assertions: "list[str] | None") -> int:
    """T-11331 / T-11494 — mark WHAT KILLED THE BATCH onto every member record handed here. Returns
    the number of members marked (0 whenever there is nothing to say). Pure: it touches only the
    member dicts it is given, and `_emit_land_member_verdicts` copies the mark onto the row.

    THIS IS THE ONE PLACE IN THE MODULE THAT WRITES `red_assertions`, and that is a load-bearing
    invariant rather than tidiness. The emitter's copy is VERDICT-AGNOSTIC — it reports the key
    wherever it finds it, without knowing which caller it is serving — which is sound only while the
    set of paths that mark it is known and small. So this function is pinned as the sole writer by
    the structural fence in `tests/test_t11331_batch_join_key.py`, which ALSO pins its callers.

    IT MAY BE CALLED ONLY FROM AN ARM THAT EMITS `requeued-after-red-batch`. Two do, and they are the
    two ends of the same red fork (SPEC-0184 rule 4): `_land_dissolve_batch`, where the batch cannot
    say who broke it and every member is requeued; and `_land_release_peers_for_solo_head`, where the
    red WAS attributed to the head and the peers are released unpenalised. A caller on any other
    verdict would grow the key on a `landed` / `evicted-for-conflict` / `dropped-dead-member` /
    `unaccounted` row, which is exactly what the fence refuses.

    WHY THE RELEASE ARM NEEDS IT (T-11494, measured over this repo's journal 2026-08-23T17:00Z to
    2026-08-24T05:00Z). Twelve multi-member batches went red in those twelve hours. TEN ended on the
    release path and their member rows carried NO cause at all; the two that DISSOLVED carried it.
    The cause was not lost — it reached the head member's own `land_completed` abort row — but that
    row is written in the HEAD BRANCH's worktree journal and stays there until that branch lands, so
    from `main` alone a red batch was undiagnosable. Answering why the 3- and 4-member batches
    collapsed meant opening `events.jsonl` inside each head worktree by hand, and the causes were NOT
    uniform: two heads failed with attribution=branch on different tests, one on a pinned entry, one
    undecidable, three on a single environment-caused assertion. A reader on main could see none of
    that distinction. This is the same asymmetry T-11331 closed for the dissolve, closed for the arm
    that turned out to carry ten of the twelve reds.

    IT CLAIMS NOTHING ABOUT WHOSE CHANGE IT WAS, on either arm. The red is a property of the BATCH:
    the COMBINED candidate failed, and the batch is explicitly forbidden to name a culprit
    (`evicted-as-culprit` is absent from rule 5's vocabulary by design — bisection is out of
    SPEC-0184's scope). `superseded_assertions` answers the DIFFERENT, fail-closed question "which
    pinned assertion is provably THIS member's own" and is untouched by this function. Conflating the
    two would read a batch-wide fact as a per-member accusation, which is the authority confusion the
    attribution gates exist to prevent.

    GATED ON A NON-EMPTY LIST, SO ABSENT MEANS UNRECORDED rather than "no cause existed" — a
    fabricated cause reads as evidence. A red whose abort surfaced no assertion text (an unnamed
    failure, a verify timeout) leaves the key OFF rather than writing an empty list, and every
    existing caller and probe that passes no assertions stays byte-identical.
    """
    _red = [str(a) for a in (assertions or []) if str(a).strip()]
    if not _red:
        return 0
    _marked = 0
    for _m in members or []:
        if isinstance(_m, dict):
            _m["red_assertions"] = list(_red)
            _marked += 1
    return _marked

def _land_mark_superseded(main_wt: "Path | None", members: "list[dict]",
                          self_branch: "str | None", *, _land_supersession_marker_path=None) -> "list[str]":
    """SPEC-0184 rule 8, HEAD SIDE — mark every member this land's ff carried, EXCEPT this land itself.
    Returns the branches marked (for the caller's record).

    Called at the `landed` verdict seam, inside the ff lock, so the mark and the fast-forward that
    justifies it are written at the same instant and a member can never be marked for a ff that did not
    happen. The head's OWN branch is excluded because the head is not parked anywhere — it IS the land
    that just finished; marking it would leave a file with no reader, which is the only way this could
    accumulate stale state.

    BEST-EFFORT BY CONSTRUCTION, and the asymmetry is the whole reason this can be a bare file write: a
    marker that fails to appear costs exactly today's behaviour (the member re-verifies, as all 16
    measured members did), while nothing about it can make a land fail. So every failure here is
    swallowed — a full disk, a permissions fault, a racing peer — and the CONTENT check downstream is
    what actually governs the outcome."""
    marked: "list[str]" = []
    if main_wt is None:
        return marked
    for m in members or []:
        br = str((m or {}).get("branch") or "").strip()
        if not br or br == (self_branch or "").strip():
            continue
        try:
            path = _land_supersession_marker_path(main_wt, br)
            if path is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            marked.append(br)
        except Exception:              # noqa: BLE001 — a marker never fails a land (see docstring)
            continue
    return marked

def _land_member_changed_paths(member: dict, main_wt: Path, *, _run_git_cap) -> "list[str]":
    """The repo-relative paths a batch MEMBER changes against `main` — the input the paying-member
    metric classifies. Uses the three-dot form so the answer is the member's OWN diff, not a
    reflection of how far `main` has moved since it branched.

    Returns `[]` when the branch cannot be diffed (gone, unborn, git error). The metric treats an
    empty answer as NOT paying, so an unreadable member shrinks the recorded saving rather than
    inflating it."""
    br = str((member or {}).get("branch") or "").strip()
    if not br:
        return []
    try:
        r = _run_git_cap(["diff", "--name-only", f"main...{br}"], main_wt)
    except Exception:                          # noqa: BLE001 — undiffable member: not paying
        return []
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

def _land_member_claim_held(member: dict, *, _pid_alive=None) -> "tuple[str, str]":
    """Is this member's CLAIM still held? Returns `('held'|'released', reason)`.

    THE TRIGGER IS CLAIMANT-KIND-AGNOSTIC, AND THAT IS THE WHOLE POINT (SPEC-0184 rule 6, which
    defers this definition here). The obvious implementation — "poll the claimant process, evict on
    exit" — was carried into this card as a HYPOTHESIS TO TEST, not a premise, and testing it kills
    it: AGENTS-SESSIONS §land tells an INTERACTIVE caller to PREFER backgrounding its land, so an
    exit-keyed trigger evicts every interactive member the moment it follows the handbook's own
    recommended posture. The recommended path would be self-defeating.
    The fix is NOT a second branch for interactive claimants — that is a code path selected by
    session label, which CHARTER §P1 and SPEC-0184 rule 1 both forbid, and it would also have to
    decide "which kind is this?" at a seam that deliberately never asks.
    So the question moves from the CLAIMANT to the CLAIM: **a claim is HELD unless the binding the
    claimant ITSELF DECLARED is broken.**
      - A SPEC-0180 held-turn claim DECLARES a process binding (a server-resolved, verified worker
        pid — `_resolve_held_turn_claim`). It is released when that pid stops being alive. This is
        the same binding rule 3 already enforces for the whole land; here it is asked per MEMBER.
      - A claim that declares NO process binding cannot be released by any process exiting. By
        SPEC-0180 rule 2's fail-closed corollary that is exactly the non-dispatched claimant's only
        available shape (no dispatch record ⇒ no held-turn claim is admissible at all), so an
        interactive member that backgrounds its land is untouched — as it must be.
    One predicate, no actor test, and BOTH directions of the trigger fall out of it rather than
    being special-cased. What a reader should NOT conclude is that interactive members are exempt
    from liveness: they are subject to the identical rule, and it simply has nothing to release
    because they bound nothing. An interactive claim that DOES declare a pid is released on the same
    terms as a worker's — the rule never asks who is calling.

    Tri-state, FAIL-CLOSED, reusing `_pid_alive` verbatim so no second liveness model exists in this
    module: 'dead' AND 'unprovable' both RELEASE. A liveness question we cannot answer must not buy
    a member continued membership, exactly as rule 3 states for the admission read.
    """
    alive = _pid_alive if _pid_alive is not None else globals()["_pid_alive"]
    claim_pid = (member or {}).get(_LAND_MEMBER_CLAIM_PID_KEY)
    if claim_pid is None:
        # NOT "unknown, assume alive" — the claim declared no process binding, so there is nothing
        # a process exit could break. Held is the CORRECT answer here, not a lenient one.
        return ("held", "unbound-claim")
    liveness = alive(claim_pid)
    if liveness == "alive":
        return ("held", "bound-claim-alive")
    return ("released", f"bound-claim-{liveness}")

def _land_member_removal_sink(removed: "list[dict] | None", *, _LAND_MEMBER_REMOVAL_EMITS_VERDICT=None) -> "list[dict]":
    """SPEC-0184 rule 5 — the REMOVAL SINK: `{branch, reason}` for every removal the verdict set
    above does NOT cover. PURE, and module-level for the reason T-11275's yield loop is
    (`lessons/a-measurement-taken-outside-its-harness-measures-the-harness.md`): inline in
    `_land_integrate` a test could only drive a RE-IMPLEMENTATION of this filter, which measures the
    fixture. Here the tripwire drives the shipped code.

    A SINK IS NOT A VERDICT, and that is the substance of this function's existence. A verdict is a
    durable claim about a member's CHANGES; `candidate-merge-failed`, `already-on-candidate`,
    `head-unresolvable` and `not-in-landed-history` are facts about THIS ATTEMPT — a ref that moved, a
    git error, work already carried elsewhere. Journaling one AS A VERDICT would invite a reader to
    treat a transient failure as a property of somebody's change, which the audit-absorbed 2026-08-16
    decision refused; that decision STANDS and the verdict set keeps its one entry. What it never
    provided was ANY record: measured 2026-08-18, a member announced into a batch whose head then
    landed ok had its removal reason UNRECOVERABLE from the journal.

    CONFLICTS ARE EXCLUDED ON PURPOSE — they already carry `evicted-for-conflict`, and recording them
    twice would blur exactly the line this docstring draws. A sink entry means the member received NO
    verdict and is still in its own queue.

    FAIL-OPEN TO `[]`: a missing list, a non-dict entry, an unreadable reason — none of them raise on
    the land hot path. A missed sink entry costs one unexplained removal (today's behaviour); an
    exception here would cost a land."""
    out: "list[dict]" = []
    for m in removed or ():
        if not isinstance(m, dict):
            continue
        reason = m.get("removal_reason")
        if reason in _LAND_MEMBER_REMOVAL_EMITS_VERDICT:
            continue                       # already carries a verdict — never both
        out.append({"branch": str(m.get("branch") or ""), "reason": str(reason or "")})
    return out

def _land_member_terminal_signal(member: dict, rows: "list[dict]") -> "dict | None":
    """A MEMBER'S TERMINAL SIGNAL — read from the JOURNAL alone. Returns its verdict row, or None.

    This REPLACES, for a batch member, SPEC-0180 rule 2c's token-or-exit poll of a PERSONAL land
    process (amended there by this card). Under batching a member HAS no personal land process:
    there is one shared batch run, so there is no token to grep and no pid to watch. Polling for a
    signal that structurally cannot arrive is how a member waits forever — the failure AC2 makes
    loud — so the terminal signal becomes the carrier that DOES exist per member: its own journaled
    `land_member_verdict` row (SPEC-0184 rule 5), which is why rule 5 calls itself the seam SPEC-0180
    needs rather than reporting garnish.

    `rows` is the parsed journal (newest-wins, append-only), passed in rather than read here so the
    reader stays hermetic and callable over either journal instance. NONE means NOT YET TERMINAL —
    never "assume terminal", never "assume landed": a member with no row is still in flight, and the
    single most dangerous misreading would be treating silence as an outcome.

    Note the asymmetry with N=1, and do not read it as a gap: a SINGLETON land emits no member row
    at all (rule 5's N=1 clause), because there its `land_completed` row and the `^LAND:` token ARE
    that member's verdict in full and the pre-batching poll works exactly as before. This reader is
    for the N>1 case, where that one-to-one no longer holds.
    """
    branch = (member or {}).get("branch")
    task = (member or {}).get("task")
    found = None
    for ev in rows or []:
        if ev.get("type") != "land_member_verdict":
            continue
        data = ev.get("data") or {}
        if data.get("branch") != branch:
            continue
        if task and data.get("task") not in (None, task):
            continue
        found = ev            # last match wins — the journal is append-only, so the newest governs
    return found

def _land_member_would_run_suite(member: dict, *, engagement_reason, attempt, no_tests,
                                 _changed_paths, _classify_inert_paths,
                                 _layer_runs_for=None) -> "bool | None":
    """T-11278 (SPEC-0184 rule 1) — WOULD THIS MEMBER'S OWN LAND ACTUALLY HAVE RUN THE SUITE?
    `True` pays, `False` does not, `None` is UNDECIDABLE and is never counted as paying.

    THIS REPLACES THE INERT-PATH PROXY, and the proxy was measurably wrong. `_classify_inert_paths`
    answers "is this delta bookkeeping", which the old metric read as "this member would have skipped
    its suite". Those are different questions: the inert skip is LEVER B, gated on `attempt > 1`, so a
    FIRST-attempt inert land runs the full suite and only its canary is skipped. Measured 2026-08-18:
    work/pinned-layer-project-switch was recorded paying_members 0 on the 15:12:46Z formation and then
    ran a verify of 422129 ms with reverify_skipped false and attempt_count 1.

    STEP 0 IS THE READ, AND ITS POSITION IS THE CONTRACT (ceiling-convergence consult 2026-08-18,
    sole surviving option). The changed-path read happens ONCE, before ANY paying branch, and an
    unreadable / undiffable / empty answer returns None immediately. Establishing readability as a
    predicate-wide precondition — rather than guarding one branch — is what makes the under-claim
    invariant structural: a paying branch added later cannot bypass a precondition it never sees.

    ENGAGEMENT DECIDES WHOSE SUITE IT IS, and the question is authorship, never repo identity — the
    same predicate `_land_batch_engagement` already answers, consumed here rather than re-derived:
      * `kernel-authored-verify` — the pinned suite. Attempt 1 ALWAYS verifies, so it PAYS; a retry
        pays only when its delta is not inert (lever B, skip reason `inert-retry-delta`).
      * `project-declared-combined-candidate-safe` — the project's own layers. The member pays only
        if some declared layer would actually RUN for its paths, asked through the SAME
        `subject_globs` authority the verify seam skips on — never through `covers:`, which names a
        different declaration and defaults the opposite way. This is the cohort that keeps a consumer
        honest: a change every declared layer would skip runs nothing, and a kernel-shaped rule would
        over-count it.
      * anything else — NOT ENGAGED, so no batch exists to attribute a saving to: None.

    NOTE THE HONEST CONSEQUENCE. In the kernel every diffable member landing alone is attempt 1, and
    attempt 1 pays — so kernel `paying` converges to kernel `members`. That is not the metric going
    degenerate; it is this repo really paying a full pass per land, which is the cost the batching
    exists to amortise. The separation between "lands per pass" and "paying per pass" carries its
    discriminating power on CONSUMERS, and must not be reported as a kernel-side distinction."""
    # ── STEP 0 — READ FIRST. No paying verdict is reachable above this line. ──────────────────────
    try:
        paths = list(_changed_paths(member) or [])
    except Exception:                          # noqa: BLE001 — unreadable member: never counted
        return None
    if not paths:
        return None                            # empty OR undiffable — indistinguishable, so UNKNOWN
    if no_tests:
        return False                           # a land running no tests runs no suite, so it pays nothing
    if attempt is None:
        return None                            # unknown attempt: refuse to guess (the rollout window)
    if engagement_reason == "kernel-authored-verify":
        if attempt <= 1:
            return True                        # attempt 1 always verifies (`run_tests and attempt > 1`)
        try:
            verdict, _reason = _classify_inert_paths(paths)
        except Exception:                      # noqa: BLE001 — classifier unavailable: UNKNOWN
            return None
        return verdict != "inert"
    if engagement_reason == "project-declared-combined-candidate-safe":
        if _layer_runs_for is None:
            return None                        # no layer reader injected: UNKNOWN, never a guess
        try:
            _hit = _layer_runs_for(paths)
        except Exception:                      # noqa: BLE001 — unreadable carrier: UNKNOWN
            return None
        # THE READER'S OWN None IS PROPAGATED, NOT COLLAPSED. `_land_layer_runs_for` answers None
        # for a carrier it could not use and False only for one it DID read and that covers nothing —
        # a distinction it exists to preserve. `bool()` on the raw answer would fold "we could not
        # tell" into "definitely not paying"; both are non-paying, so the COUNT would not move and the
        # loss would be invisible, which is exactly why it has to be handled here rather than trusted
        # to show up downstream.
        return None if _hit is None else bool(_hit)
    return None

def _land_members_carried_by_ff(members: "list[dict]", main_wt: "Path | None", *,
                                before_sha: "str | None", after_sha: "str | None",
                                _run_git_cap=None, _land_git_is_ancestor=None) -> "tuple[list[dict], list[dict]]":
    """SPEC-0184 rule 5 — partition a batch into `(carried, uncarried)` by what THIS land's
    fast-forward ACTUALLY moved `main` by. The carried set is what may be journaled `landed`.

    THE PREDICATE IS TWO-SIDED, AND THE SECOND SIDE IS THE WHOLE POINT. A member is carried iff its
    branch head is an ancestor of `after_sha` (the sha the ff moved main TO) **and NOT already an
    ancestor of `before_sha`** (the sha main was AT when the ff lock was taken). Ancestry alone is
    NOT sufficient and passing it would have missed the incident this card was cut from: at
    2026-08-17T04:57:21Z a land journaled `landed` for `task/T-11211`, whose commits another land had
    put on main five minutes earlier — an already-landed member IS an ancestor of the new main, so a
    one-sided test reads the phantom as a pass. What went wrong upstream is that
    `_land_merge_batch_into_candidate` reads only the merge EXIT CODE, and an "Already up to date"
    merge exits 0; combined with a queue read that has no liveness check (a land that has STOPPED
    waiting keeps matching its own `waiting_for_*` heartbeats for up to
    `_LAND_QUEUE_FRESHNESS_SEC`), a finished land is picked as a peer, no-op merged, and declared
    landed by a pass that carried none of it.
    So this asks the fast-forward itself rather than any proxy for it: exit codes, queue membership
    and merge bookkeeping can all be true while `main` moved by nothing.

    MEASURED AT VERDICT TIME, INSIDE THE FF LOCK — never after the fact. A ref this land deleted, and
    a branch that legitimately advanced after its verdict, both read "not an ancestor" later while
    meaning nothing of the sort; the two shas are read at the one instant at which the question has
    an answer.

    THREE-VALUED, FAIL-CLOSED TO NOT-CARRIED. A member whose head cannot be resolved (ref gone, git
    error, either sha missing) is `head-unresolvable` and gets NO row — an unprovable claim is not a
    claim. The direction is deliberate and asymmetric: a missing row understates what landed and
    costs a reader one journal query, while a wrong row tells a member it landed when it did not,
    which is the failure this card exists to remove.

    ONE FILTER, BOTH READERS. The result is applied BEFORE `_land_drop_dead_members`, so a phantom
    cannot be journaled `dropped-dead-member` either. Both post-ff readers consume the same list, so
    filtering it once is the whole fix — a second, parallel check for the dead-member reader would be
    two truths about one question (CHARTER §P1 F1/F2).

    AT N<=1 IT RUNS NO GIT AT ALL and returns its input untouched (rule 1's byte-identity: a
    singleton land's own `land_completed` row and `^LAND:` token ARE that member's verdict, and the
    member IS the land, so there is nothing to filter).
    """
    # TWO conditions with OPPOSITE correct answers — never one guard (audit-post medium, 2026-08-17).
    # They were fused into a single early return that answered BOTH with "everything carried", which
    # is right for exactly one of them and is the very claim this function exists to stop making.
    #
    #   N<=1        -> return the input UNTOUCHED. Rule 1 byte-identity: a singleton's own
    #                  `land_completed` row and `^LAND:` token ARE its verdict, so there is nothing
    #                  to filter and no git to run.
    #   cannot ASK  -> carry NOTHING. No git runner, no main worktree, or either ff sha missing means
    #                  the question "did THIS ff carry it?" has no answer here — and the docstring's
    #                  own contract for an unanswerable question is `head-unresolvable`, not a pass.
    #                  `before_sha` belongs in this set for the same reason `after_sha` does: without
    #                  it the two-sided predicate loses its second side, which is what distinguishes a
    #                  member this ff carried from one that was already on main (the 04:57:21Z phantom).
    if len(members) <= 1:
        return (list(members), [])
    if _run_git_cap is None or main_wt is None or not after_sha or not before_sha:
        return ([], [dict(m or {}, removal_reason=_LAND_MEMBER_HEAD_UNRESOLVABLE) for m in members])

    def _is_ancestor(rev: str, desc: str) -> "bool | None":
        """The ONE ancestry idiom (`_land_git_is_ancestor`), bound to this reader's worktree and git
        runner. Delegated rather than spelled a second time (T-11220): the batch-membership test asks
        the same three-valued question of a different pair of revisions, and two copies of it could
        drift apart about what "already there" means."""
        return _land_git_is_ancestor(rev, desc, main_wt, _run_git_cap=_run_git_cap)

    carried, uncarried = [], []
    for m in members:
        br = str((m or {}).get("branch") or "").strip()
        if not br:
            uncarried.append(dict(m or {}, removal_reason=_LAND_MEMBER_HEAD_UNRESOLVABLE))
            continue
        in_after = _is_ancestor(br, after_sha)
        if in_after is None:
            uncarried.append(dict(m, removal_reason=_LAND_MEMBER_HEAD_UNRESOLVABLE))
            continue
        if in_after is False:
            uncarried.append(dict(m, removal_reason=_LAND_MEMBER_NOT_IN_FF))
            continue
        # It is in the landed history — but was it THIS ff that put it there?
        # `before_sha` is guaranteed present by the guard above — the former `if before_sha else
        # False` fallback is REMOVED, not left dead: reading a missing sha as "was not on main" is
        # precisely the fail-OPEN this fix closes, and a dead branch of it invites reinstatement.
        was_before = _is_ancestor(br, before_sha)
        if was_before is None:
            uncarried.append(dict(m, removal_reason=_LAND_MEMBER_HEAD_UNRESOLVABLE))
        elif was_before:
            uncarried.append(dict(m, removal_reason=_LAND_MEMBER_ALREADY_ON_MAIN))
        else:
            carried.append(m)
    return (carried, uncarried)

def _land_merge_batch_into_candidate(W: "Path | None", members: "list[dict]", *,
                                     pre_sha: "str | None" = None,
                                     branch: "str | None" = None,
                                     batch_state: "dict | None" = None,
                                     _run_git_cap=None, _land_git_is_ancestor=None,
                                     _classify_land_merge_conflicts=None,
                                     _DERIVED_MERGE_ARTIFACTS=None,
                                     _apply_land_merge_resolution=None,
                                     _merged_worktree_anchor_signer=None,
                                     _anchor_signature_of_text=None,
                                     _dedup_events=None,
                                     write_text_atomic=None) -> "tuple[list[dict], str | None, list[dict]]":
    """SPEC-0184 rule 4 (the ATOMICITY half) — merge the surviving PEERS into the candidate worktree
    in queue order. Returns `(merged_members, pre_sha, unmerged)`.

    THIS IS WHAT MAKES "ONE VERIFY" AND "ATOMIC FAST-FORWARD" THE SAME EDIT. The land path already
    has exactly one verify (`_verify_under_admission` over `W`) and exactly one ref move (the in-lock
    `merge --ff-only <branch>`). Merging the peers into `W` BEFORE the pass makes that verify a
    COMBINED-candidate verify and that ref move an atomic multi-member fast-forward, without adding a
    second pass, a second ff, or a rollback protocol. Partial application is not merely forbidden
    here — it is UNREPRESENTABLE, because there is no point in the sequence at which some members
    have been applied to `main` and others have not.

    `pre_sha` is the candidate's HEAD BEFORE the first peer merge — captured once, on the first call,
    and THREADED BACK IN by the caller across ff-race retries. It is the dissolve target: on red the
    candidate is reset to it so the peers leave this branch's history. Threading it (rather than
    re-reading HEAD each attempt) is load-bearing: after attempt 1 has merged peers, HEAD is no
    longer pre-batch, so a re-read would make the reset a no-op and strand the peers on the branch.

    A MEMBER IS ONE THE MERGE ACTUALLY MOVED THE CANDIDATE BY — NOT ONE WHOSE MERGE EXITED 0
    (T-11220). An "Already up to date" merge — what a peer whose commits already reached the
    candidate by any route produces — exits 0 while bringing nothing, so the exit code cannot
    distinguish "merged your work" from "there was nothing to merge". Membership is therefore decided
    by the reachability that IS git's own condition for that no-op, asked before the merge; a peer
    already reachable from the candidate is returned in `unmerged` with an explicit
    `already-on-candidate` reason instead of being counted. This matters beyond the `landed` verdicts
    T-11214 already filters: `merged_members` is also what the red-path dissolve requeues and what
    the ineligibility read derives from, so counting a no-op member penalises it for a red it
    contributed nothing to — defeating the dissolve's own stated intent that its list be the MERGED
    set. Sibling T-11219 removes the main SOURCE of such members (a finished land still read as
    queued); this predicate removes the CONSEQUENCE whatever the source.

    A PEER THAT DOES NOT MERGE IS DROPPED, NOT FATAL. T-11193's `merge-tree` dry run already evicted
    the textual conflicts, so a failure here is an attempt-level surprise. The merge is aborted, the
    peer is marked `_LAND_MEMBER_CANDIDATE_MERGE_FAILED` and returned in `unmerged` — the pass goes
    on for everyone else, exactly as rule 6 requires for a dead member. The returned
    `merged_members` is therefore the AUTHORITATIVE batch for every downstream decision (the rule-7
    union, the red-path dissolve, the ineligibility marking, the `landed` verdicts): a member that
    was not in the verified tree is never treated as though it were.

    BUT "AN ATTEMPT-LEVEL SURPRISE" WAS NOT TRUE, AND T-11648 IS WHY. The dry run does not prove the
    peer plain-git-mergeable — it proves it `clean` OR `land-resolvable`, and `_LAND_PROBE_MERGEABLE`
    admits both. `land-resolvable` means `_classify_land_merge_conflicts` resolved every conflict and
    `_land_merge_probe` accumulated its RESOLVED tree. This function then performed NONE of those
    resolutions: it was a bare `git merge` with no classifier and no derived-artifact set, so the
    predictor's admitted case WAS this function's failing case, deterministically, on every retry. A
    peer whose only collision with the candidate is a committed derived artifact both sides rewrote
    (`graph/index.json`; since T-11484 `tests/verify-durations.json`) was selected into batch after
    batch it could not join and then landed SOLO with no merge trouble at all — because a solo land's
    `_update_from_main` IS one of the seams that resolves. Measured: 31 `candidate-merge-failed`
    removals over 21 branches in 11 days, six branches repeating, one of them three times in 41
    minutes. Two oracles for one question, which is what CHARTER §Principle 5 forbids and what
    T-11216 already closed on the EVICTION path — there the probe was stricter than the land path,
    here it was looser than the merge.

    SO THE PEER MERGE NOW RESOLVES WHAT THE PREDICTOR RESOLVED, THROUGH THE SAME AUTHORITY. On a
    nonzero merge, before the abort: read the unmerged paths, ask `_classify_land_merge_conflicts`,
    and ONLY if it RAN and named ZERO unresolved paths, apply its verdict via the shared
    `_apply_land_merge_resolution` (the applier lifted out of `_update_from_main`, one impl, two
    callers) and let the peer merge. FAIL-CLOSED ON EVERY OTHER PATH, and the list is exhaustive: the
    seam not injected, the classifier raised, any path it could not prove mechanical, or a commit
    that failed — each falls through to the pre-existing `merge --abort` + `candidate-merge-failed`.
    The change can therefore only ever ADMIT a peer the land path itself would have resolved; it can
    never reject one that merges today. WITH THE SEAM ABSENT THIS FUNCTION IS BYTE-IDENTICAL to its
    pre-T-11648 self, which is what lets every existing caller and test keep its behaviour unread.

    AT N<=1 IT RUNS NO GIT AT ALL (rule 1). A quiet repo forms a batch of one and this function
    returns its input untouched — no subprocess, no commit, no observable act of any kind, so the
    singleton land stays byte-identical to the pre-spec path at all three levels rule 5 names.
    """
    if len(members) <= 1 or _run_git_cap is None or W is None:
        return (list(members), pre_sha, [])
    if pre_sha is None:
        try:
            r = _run_git_cap(["rev-parse", "HEAD"], W)
            head = (r.stdout or "").strip()
            pre_sha = head if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", head or "") else None
        except Exception:                      # noqa: BLE001
            pre_sha = None
    if pre_sha is None:
        # No dissolve target ⇒ no reversible batch. FAIL-CLOSED to a batch of ONE rather than merging
        # peers we could not undo on red: an irreversible candidate is exactly how a red batch would
        # strand other people's commits on this branch.
        return ([members[0]], None, [dict(m, removal_reason=_LAND_MEMBER_CANDIDATE_MERGE_FAILED)
                                     for m in members[1:]])
    merged, unmerged = [members[0]], []
    # T-11226 — PUBLISH THE UNDO TARGET BEFORE THE FIRST MERGE, AND EACH PEER AS IT IS MERGED.
    # The caller used to publish only after this function RETURNED, which left an uncovered window
    # the ceiling-convergence consult named (2026-08-17): a raise anywhere in the loop below — a git
    # call that dies after peer 1 is already merged — never reaches that publication, so `cmd_land`'s
    # `finally` sees no recorded peers and SKIPS the restoration, silently leaving another card's
    # commit on this branch. That is the exact failure this card exists to close, so the rule "the
    # state a restoration needs must exist before anything that could go wrong" has to hold INSIDE
    # the merging function, not around it.
    #
    # The caller still finalizes the same keys from the returned set; that stays the authoritative
    # value. This is the crash-safety belt underneath it, and the two agree by construction because
    # both derive from `merged`.
    def _publish() -> None:
        if batch_state is None:
            return
        batch_state.update({"pre_sha": pre_sha, "W": W, "branch": branch,
                            "batch_size": len(merged),
                            "peers": [str((x or {}).get("branch") or "") for x in merged[1:]]})
    def _resolve_peer_merge() -> bool:
        """T-11648 — can the FAILED peer merge sitting in `W` be resolved the way `land` itself
        resolves one? True ONLY when it was, and committed. Every uncertainty answers False.

        This asks `_classify_land_merge_conflicts` — THE one admission authority (T-11216) — the same
        question `_land_merge_probe` asked when it admitted this peer, and applies its verdict with
        the same applier `_update_from_main` uses (`_apply_land_merge_resolution`). It forms no
        verdict of its own and widens nothing: `unresolved` non-empty means the classifier RAN and
        named a path it could not prove mechanical, which is a real conflict and stays one.
        """
        if (_classify_land_merge_conflicts is None or _DERIVED_MERGE_ARTIFACTS is None
                or _apply_land_merge_resolution is None):
            return False                       # seam not injected: pre-T-11648 behaviour, unchanged
        try:
            u = _run_git_cap(["diff", "--name-only", "--diff-filter=U"], W)
            unmerged_paths = u.stdout.split() if getattr(u, "returncode", 1) == 0 else []
            if not unmerged_paths:
                # A merge that failed with NO conflicted path is not a conflict at all — a dirty
                # tree, a refused merge, an unreadable ref. Nothing here can speak to it.
                return False
            sig = (_merged_worktree_anchor_signer(
                       W, unmerged_paths, _anchor_signature_of_text=_anchor_signature_of_text)
                   if (_merged_worktree_anchor_signer is not None
                       and _anchor_signature_of_text is not None) else None)
            resolved_map, unresolved = _classify_land_merge_conflicts(
                unmerged_paths, W, _run_git_cap=_run_git_cap,
                _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                _merged_anchor_signature=sig)
            if unresolved:
                return False                   # a proven blocker: this peer really is incompatible
            cc = _apply_land_merge_resolution(
                W, unmerged_paths, resolved_map, _run_git_cap=_run_git_cap,
                _dedup_events=_dedup_events, write_text_atomic=write_text_atomic)
            return getattr(cc, "returncode", 1) == 0
        except Exception:                      # noqa: BLE001 — could not resolve it: not an admission
            return False

    _publish()
    for m in members[1:]:
        br = str((m or {}).get("branch") or "").strip()
        # T-11220 — MEMBERSHIP REQUIRES THAT THE MERGE ACTUALLY BRING SOMETHING. Asked BEFORE the
        # merge, because git's own condition for the no-op "Already up to date" IS this reachability:
        # a peer already reachable from the candidate contributes nothing, and merging it would leave
        # HEAD where it stands while exiting 0. Excluding it here means no merge runs and there is no
        # post-merge state to undo — and, decisively, the phantom never enters the returned set, so
        # the red-path dissolve cannot requeue it for a peer's red (nor make it batch-ineligible,
        # which is derived from exactly those requeue rows) and the rule-7 union is not widened by a
        # diff this candidate does not carry.
        # FALSE or UNRESOLVABLE both fall through to the merge below, unchanged. That asymmetry is
        # deliberate: a real member must never be dropped because git could not answer a question
        # about it (an emptied batch destroys joint landing, which is the whole feature), while after
        # a FALSE the merge necessarily moves HEAD — so the exit-code reading is sound for everything
        # that reaches it.
        if br and _land_git_is_ancestor(br, "HEAD", W, _run_git_cap=_run_git_cap) is True:
            unmerged.append(dict(m, removal_reason=_LAND_MEMBER_ALREADY_ON_CANDIDATE))
            continue
        ok = False
        if br:
            try:
                ok = _run_git_cap(["merge", "--no-edit", br], W).returncode == 0
            except Exception:                  # noqa: BLE001
                ok = False
        if ok:
            merged.append(m)
            _publish()                         # T-11226: recorded the instant the peer is on the branch
            continue
        # T-11648 — THE SAME MECHANICAL RESOLUTION THE PREDICTOR ALREADY ASSUMED. Attempted ONLY
        # here, on a merge that has ALREADY failed, so nothing about a clean merge changes; and only
        # when the caller injected the whole seam, so an un-threaded caller keeps the old behaviour
        # exactly. `_resolve_peer_merge` returns True only on a committed, fully-resolved merge.
        if br and _resolve_peer_merge():
            merged.append(m)
            _publish()                         # the peer is on the branch: same record as a clean merge
            continue
        try:
            _run_git_cap(["merge", "--abort"], W)
        except Exception:                      # noqa: BLE001 — nothing to abort is the ordinary case
            pass
        unmerged.append(dict(m, removal_reason=_LAND_MEMBER_CANDIDATE_MERGE_FAILED))
    return (merged, pre_sha, unmerged)

def _land_rederive_merged_candidate(W: "Path | None", branch: "str | None", *,
                                   bk_sha: "str | None" = None,
                                   member_count: int = 0,
                                   _rebuild_derived=None, _regen_manifest=None,
                                   _regen_root=None,
                                   _derived_paths=(), _run_git_cap=None,
                                   _land_bookkeeping_commit=None) -> "tuple[str | None, list[str], bool]":
    """T-12236 (SPEC-0184 rule 4 / SPEC-0031) — RE-DERIVE the committed DERIVED artifacts on the
    MERGED batch candidate and fold them into the batch head. Returns `(bk_sha, changed_paths)`.

    THE DEFECT THIS CLOSES. A committed derived artifact is a FIXED POINT of its own generator run
    over ONE tree. Two members each regenerate it for THEIR tree; the merge unions the two results,
    and the union is the fixed point of NEITHER. The suite asserts exactly that fixed point
    (`tests/test_t0874_manifest_completeness.py` test_c, `tests/test_t9541_spec_code_map_regen.py`
    test_d), so an individually-green pair reddens the batch through NO MEMBER'S FAULT — and
    `_land_attribute_failing_assertions` correctly declines to name a culprit, because there is none.
    Measured 2026-09-07 13:02Z: `task/T-12210` + `task/T-12222`, both green alone and green on main,
    aborted together with CULPRIT UNNAMED; cost was one routed batch verify plus BOTH members
    re-landing solo.

    NO NEW MECHANISM — THIS IS THE EXISTING SEAM, ASKED AT THE POSITION IT NEVER COVERED. `land`
    already re-derives post-merge: step 3 runs `_auto_rebuild_graph("land")` and folds the result into
    the ONE `land: bookkeeping` commit. But step 3 runs ~1100 lines ABOVE the SPEC-0184 rule-4 merge,
    so nothing regenerates after the peers arrive. Per SPEC-0031 the build is a PURE function of the
    checkout with a CONTENT-EXACT result cache, so running it on a tree nobody has built before is an
    ORDINARY CACHE MISS — not a new determinism claim, not a new artifact, not a new gate.

    POSITION IS THE CLAIM, exactly as it is for the eviction and the merge above it: BELOW
    `_land_merge_batch_into_candidate` (the tree must be complete before it can be a fixed point of
    anything) and ABOVE `_verify_under_admission` (the candidate the box verifies must BE the fixed
    point, and must be the same tree the in-lock `merge --ff-only` then moves `main` by). A sibling
    that moves this under the pass verifies a tree that is not the one that ffs — which is the
    same-shaped error the T-11194 comment guards one screen up.

    AT N<=1 IT RUNS NOTHING AT ALL (SPEC-0184 rule 1). A quiet repo forms a batch of one, whose
    derived artifacts step 3 already re-derived for that exact tree; `member_count <= 1` returns
    immediately, so the singleton land stays byte-identical — no subprocess, no write, no commit.

    FAIL-TOLERANT, LIKE `_auto_rebuild_graph` ITSELF. Any exception WARNs to stderr and returns the
    threaded `bk_sha` unchanged. The re-derivation is an OPTIMISATION OF ATTRIBUTION, never a gate:
    if it cannot run, the candidate verify remains exactly the compensating control it is today, so
    the worst case is the pre-card behaviour rather than a fleet-wide land stop. Every uninjected
    seam is the same answer — a harness driving this without the collaborators gets the no-op.

    THE THIRD RETURN ELEMENT IS THE OUTCOME, AND IT EXISTS TO SAVE THE PASS (audit-pre F1, passes
    1+2). `True` = the candidate is a fixed point of its generators (including every no-op path,
    where it already was). `False` = the re-derivation could NOT run — a raising generator, a regen
    root that is not this candidate, a commit that failed. On `False` we do not merely KNOW LESS, we
    know the candidate is very likely NOT a fixed point, so the batch is very likely to redden. Rule
    4's dissolve would still recover CORRECTNESS (a red batch dissolves and each member is verified
    alone — the declare->exclude->solo chain, terminating by construction), but only after spending
    the full verify pass that this whole spec exists to amortise. That is precisely the argument rule
    3 already makes for putting the eviction BEFORE the pass: "a conflict discovered AFTER a pass
    defeats the purpose even when the eviction itself is correct." So the caller dissolves to a batch
    of ONE here, pre-verify, through rule 4's OWN dissolve target (`_batch_pre_sha`) — no second
    exclusion route is invented, and no member is penalised: each peer simply lands on its own next
    attempt.

    IT COMMITS RATHER THAN MERELY WRITING, and that is not tidiness. The verify reads the WORKING
    TREE, so a bare write would go green — and then the in-lock `merge --ff-only <branch>` would move
    `main` by the branch TIP, which does not carry the regenerated files. `main` would take the stale
    artifact and the NEXT land would redden on it, having moved the defect one land downstream while
    reporting success. The fold uses the SHARED `_land_bookkeeping_commit` (one impl, every land
    bookkeeping site), so no new commit subject and no new event enter the history."""
    if member_count <= 1 or W is None or _run_git_cap is None:
        return (bk_sha, [], True)
    if _rebuild_derived is None or _land_bookkeeping_commit is None:
        return (bk_sha, [], True)
    try:
        # T-12236 (audit-pre F2) — THE REGEN ROOT MUST BE THIS CANDIDATE, PROVEN, NOT ASSUMED. Both
        # generators resolve their inputs from the engine's REPO_ROOT-derived globals rather than from
        # `W`. At land those coincide (`cmd_land` re-execs with `-C <worktree>`, rebinding the whole
        # path set atomically), which is why this works — but a coincidence that nothing checks is
        # exactly the wrong thing to build a fixed point on: regenerating the candidate's manifest
        # from the MAIN checkout's index would MANUFACTURE the cross-tree mismatch this step exists to
        # remove, and would do it silently, on a tree that then fast-forwards `main`. So the root is
        # compared and a disagreement REFUSES the whole step. Fail-safe: refusing leaves the pre-card
        # behaviour (the candidate verify catches any real drift), while proceeding would not.
        if _regen_root is not None:
            _root = _regen_root()
            if Path(_root).resolve() != Path(W).resolve():
                print("land: WARNING — merged-candidate re-derivation (T-12236) SKIPPED: the "
                      f"generators resolve {_root} but the candidate is {W}; refusing to render one "
                      "tree's derived artifacts from another's. (Candidate verify remains the "
                      "control.)", file=sys.stderr)
                return (bk_sha, [], False)
        _rebuild_derived()
        if _regen_manifest is not None:
            _regen_manifest()
        # Stage ONLY the derived paths this step owns — NEVER `git add -A`. A batch candidate is the
        # one tree carrying several authors' work, so a sweeping stage here would fold somebody
        # else's stray file into a commit labelled bookkeeping. Absent paths are filtered rather than
        # passed, so a not-yet-created derived file cannot error the pathspec (the T-0254 / E-0010
        # shape the step-3 staging already handles this way).
        addable = sorted({p for p in _derived_paths if (W / p).exists()})
        if not addable:
            return (bk_sha, [], True)
        _run_git_cap(["add", "--", *addable], W)
        if _run_git_cap(["diff", "--cached", "--quiet"], W).returncode == 0:
            # The merge already left every derived artifact at its fixed point — the common case, and
            # the one that must cost nothing. Nothing staged, so nothing is committed.
            return (bk_sha, [], True)
        changed = [ln for ln in (_run_git_cap(["diff", "--cached", "--name-only"], W).stdout
                                 or "").split() if ln]
        c, new_sha = _land_bookkeeping_commit(W, branch, bk_sha, _run_git_cap)
        if getattr(c, "returncode", 1) != 0:
            print("land: WARNING — re-derived artifacts on the merged batch candidate could not be "
                  f"committed (T-12236): {(getattr(c, 'stderr', '') or getattr(c, 'stdout', '') or '').strip()[:300]} "
                  "— the candidate verify remains the control.", file=sys.stderr)
            return (bk_sha, [], False)
        print(f"land: re-derived on the merged candidate (T-12236): {', '.join(changed)}",
              file=sys.stderr)
        return (new_sha, changed, True)
    except Exception as e:                     # noqa: BLE001 — fail-tolerant; verify is the gate
        print(f"land: WARNING — merged-candidate re-derivation (T-12236) failed to run: {e} "
              "(the candidate verify remains the control).", file=sys.stderr)
        return (bk_sha, [], False)


def _land_merge_members_in_queue_order(members: "list[dict]", main_wt: "Path | None", *,
                                       main_rev: "str | None" = None, _run_git_cap=None,
                                       _merge_probe=None, _DERIVED_MERGE_ARTIFACTS=None,
                                       _dedup_events=None,
                                       _anchor_signature_of_text=None, _git_rev=None, _land_merge_probe=None, _land_probe_advance=None) -> "tuple[list[dict], list[dict]]":
    """SPEC-0184 rule 3 — merge the batch onto the current `main` IN QUEUE ORDER, removing a member
    whose merge conflicts with an ALREADY-MERGED PEER. Returns `(survivors, removed)`.

    THE ORDERING IS THE CLAIM, NOT THE MERGE. A verify pass is the scarce resource the whole batching
    design exists to conserve, so a conflict discovered AFTER a pass defeats the purpose even when the
    eviction itself is correct. This function therefore exists to run BEFORE the admission-wrapped
    verify — its call site's position is as load-bearing as its body, and the T-11193 tests guard that
    position directly. Pre-change the equivalent conflict surfaces at `_land_integrate`'s in-lock
    `merge --no-edit main`, which sits after the verify and whose non-trivial failure `continue`s to a
    retry that re-runs the whole suite: one full pass, spent to learn a fact computable in milliseconds.

    A CONFLICT MEANS WHAT THE LAND PATH SAYS IT MEANS (T-11216). "Conflicts" is judged by
    `_classify_land_merge_conflicts` — the SAME admission `_update_from_main` runs — not by a raw
    `merge-tree` exit. Before this card the probe read ANY conflict as an eviction while the path it
    predicts auto-resolved four mechanical classes, so a pair colliding only on, say,
    `graph/index.json` and an `implements_signature` block was split here although the real merge
    would have landed both (measured 2026-08-17). One question, one authority (CHARTER §Principle 5).

    NOTHING IS CHECKED OUT AND NO REF MOVES. The merges are computed with `merge-tree --write-tree`
    (the idiom already used at `_post_audit_footprint_split`), accumulating through `commit-tree` so
    member N is tested against the peers ALREADY merged ahead of it rather than against bare `main`.
    A land-resolvable merge accumulates its RESOLVED tree (`_probe_resolved_tree`, composed in a
    throwaway `GIT_INDEX_FILE`), so the accumulator never carries a conflict marker into the next
    member's probe. Every object written is unreferenced and unreachable — `main`, the worktrees and
    the members' branches are all untouched, which is what makes this safe to run before anyone has
    agreed to land.

    QUEUE ORDER IS THE WHOLE DETERMINISM MECHANISM (AC2). `members` is an ordered list, iterated in
    order; there is no set or dict iteration and no timestamp anywhere in this path, so a fixed queue
    always removes the same member. `commit-tree` shas do vary run to run — they embed a commit time —
    but no decision reads a sha, only the accumulator identity passed to the next merge.

    THE HEAD IS NEVER EVICTABLE. `members[0]` holds the slot; rule 3 evicts a member that conflicts
    with an ALREADY-MERGED PEER, and the head has none. It merges first purely to establish the
    accumulator. If that merge is not clean the cause is a branch-vs-`main` conflict, which is the
    existing land path's own business and its own abort — so this step degrades to a batch of one and
    reports nothing, rather than inventing a verdict for a condition it does not own.

    AT N<=1 IT IS A NO-OP THAT RUNS NO GIT AT ALL (rule 1). A quiet repo forms a batch of one, and the
    byte-identity rule 1 promises it is not merely "no rows emitted" — it is no subprocess, no object
    written, no observable act of any kind.
    """
    if len(members) <= 1 or _run_git_cap is None or main_wt is None:
        return (list(members), [])

    def _probe(accum: str, branch: str) -> "tuple[str, str | None, dict | None]":
        """This path's view of the SHARED oracle `_land_merge_probe` — `(outcome, tree, detail)`.

        T-11218 moved the oracle's BODY to module scope so the pre-queue refusal can call the same
        one; nothing about the eviction verdict moved with it. T-11258 stops DISCARDING the `detail`
        third element here, and the distinction it turns on is the whole reason the discard was safe
        to end: rule 3 is fail-CLOSED at the level of the DECISION, and the decision below still
        reads `outcome` and nothing else — every unprovable edge still evicts, exactly as before.
        What `detail` adds is not a decision input but the RECORD of one: the classifier's own
        blocking / auto-resolvable split, which this path already computed and then threw away, so
        an eviction reported its fact without its reason and was unanalysable after the fact.
        The fail-OPEN pre-queue consumer still needs the same element to tell proof from
        inability-to-prove; this consumer needs it only to say WHY.

        `_merge_probe` stays the injection seam and is EXTENDED, never broken: a 2-tuple injector
        still works and reads as `detail = None` — which is the correct answer for it, since a seam
        that supplies no classifier verdict has not proven one (AC2).
        """
        if _merge_probe is not None:
            _r = _merge_probe(accum, branch)
            return _r if len(_r) == 3 else (_r[0], _r[1], None)
        return _land_merge_probe(
            accum, branch, main_wt, _run_git_cap=_run_git_cap,
            _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS, _dedup_events=_dedup_events,
            _anchor_signature_of_text=_anchor_signature_of_text)

    def _rev(ref: str) -> "str | None":
        return _git_rev(ref, main_wt, _run_git_cap=_run_git_cap)

    def _advance(accum: str, tree: str, branch: str) -> "str | None":
        """This path's view of the SHARED accumulator step `_land_probe_advance` (T-11309 lifted the
        body to module scope so rule 1's formation admitter can call the same one). Behaviour is
        unchanged value-for-value; only the home moved."""
        return _land_probe_advance(accum, tree, branch, main_wt, _run_git_cap=_run_git_cap)

    def _mark(member: dict, reason: str, detail: "dict | None" = None) -> dict:
        # An ADDITIVE key on the member record — the same D-0009 growth `_land_batch_members` uses for
        # `paying`, never a parallel structure the caller has to keep in step with the member list.
        #
        # T-11258 — the CAUSE travels with the removal, and ONLY when it was actually PROVEN. `detail`
        # is the oracle's third element: `{"resolved": [...], "unresolved": [...]}` when
        # `_classify_land_merge_conflicts` ran to a result, and None on every path where it did not
        # (an unparsable stream, no derived-artifact set, a classifier that raised, a resolved tree
        # that would not compose) — the four fail-closed fallbacks that all land on the pre-change
        # `conflict` verdict. So an eviction reached through a fallback carries NO cause key at all.
        # That absence is the point, not an omission: a FABRICATED reason is worse than a missing one
        # because it reads as evidence, and «the classifier named these paths» and «nothing was read»
        # must never produce the same record. An empty list is likewise not written — «proven empty»
        # is reported by the key being absent rather than by a `[]` a reader could mistake for a
        # blocking set of size zero.
        m = dict(member)
        m["removal_reason"] = reason
        blocking = list((detail or {}).get("unresolved") or [])
        resolvable = list((detail or {}).get("resolved") or [])
        if blocking:
            m["conflict_blocking"] = blocking
        if resolvable:
            m["conflict_auto_resolvable"] = resolvable
        return m

    head, peers = members[0], list(members[1:])
    base = main_rev or _rev("main")
    if not base:
        return ([head], [_mark(m, "unevaluable") for m in peers])

    head_branch = str((head or {}).get("branch") or "").strip()
    outcome, tree, _ = _probe(base, head_branch) if head_branch else ("unevaluable", None, None)
    accum = _advance(base, tree, head_branch) if outcome in _LAND_PROBE_MERGEABLE and tree else None
    if accum is None:
        # The slot holder does not cleanly merge onto `main` (or could not be read). There is no
        # already-merged peer for anyone to conflict WITH, so no eviction is possible or meaningful.
        return ([head], [_mark(m, "head-unmergeable") for m in peers])

    survivors, removed = [head], []
    for m in peers:
        br = str((m or {}).get("branch") or "").strip()
        if not br:
            removed.append(_mark(m, "unevaluable"))
            continue
        outcome, tree, detail = _probe(accum, br)
        if outcome == "conflict":
            # RULE 3, the whole point: this member is incompatible with a peer already merged AHEAD of
            # it in queue order. It leaves the candidate now — before a single second of verify.
            # T-11258: the DECISION still reads `outcome` and nothing else — `detail` is passed for
            # the RECORD only, so this stays report-only and the member set is byte-identical (AC3).
            removed.append(_mark(m, "conflict", detail))
            continue
        nxt = _advance(accum, tree, br) if outcome in _LAND_PROBE_MERGEABLE and tree else None
        if nxt is None:
            # Unreadable, not incompatible. Skipped rather than truncating the batch: dropping the
            # rest as well would let one transient git failure shrink an otherwise valid candidate,
            # and skipping keeps the surviving order exactly as the queue gave it.
            removed.append(_mark(m, "unevaluable"))
            continue
        accum = nxt
        survivors.append(m)
    return (survivors, removed)

def _land_merge_probe(accum: str, branch: str, main_wt: Path, *, _run_git_cap,
                      _DERIVED_MERGE_ARTIFACTS=None,
                      _dedup_events=None,
                      _anchor_signature_of_text=None, _classify_land_merge_conflicts=None, _git_rev=None, _merge_tree_conflict_stages=None, _merged_tree_oid_anchor_signer=None, _probe_resolved_tree=None) -> "tuple[str, str | None, dict | None]":
    """THE conflict oracle of the land path (T-11216 factored it; T-11218 gave it module scope).

    `(outcome, tree, detail)` for merging `branch` onto `accum` — outcome in
    clean|land-resolvable|conflict|unevaluable. ONE DEFINITION, TWO CALL SITES: SPEC-0184 rule 3's
    batch-eviction probe (`_land_merge_members_in_queue_order`) and the PRE-QUEUE refusal
    (`_land_prequeue_merge_refusal`). It lives here rather than nested inside the ordering path
    because a second site cannot call a closure — and the alternative, a second merge-tree feed,
    is precisely the defect the external-auditor consult killed (`land-conflict-check-before-queue`,
    YELLOW/medium, 2026-08-17): a name-only feed makes auto-resolvable spec-signature and
    row-append conflicts read as BLOCKING, so the early path would FALSE-ABORT a land that would
    have succeeded. One question, one authority (CHARTER §Principle 5).

    THE EXIT CODE ALONE IS NOT THE CONFLICT ORACLE, and assuming it is was a real defect T-11216's
    tests caught: `merge-tree --write-tree` exits 1 for a CONFLICT *and* exits 1 for "not something
    we can merge" (a branch that does not resolve). Keying on rc==1 therefore libels an unreadable
    branch as incompatible with its peers — a durable, wrong, public statement about somebody's
    change.

    What actually distinguishes them is the STDOUT: on a conflict git still writes the merged
    tree's oid as line 1 (with conflict-marked content inside — the same behaviour
    `_post_audit_footprint_split` relies on); on a resolution failure it writes an error to stderr
    and no oid at all. So the oracle is `rc + a readable tree oid`, and anything that is not
    provably one of the two named outcomes falls through to `unevaluable`.

    NOR IS A RAW `merge-tree` CONFLICT THE VERDICT. It used to be, and that made the probe STRICTER
    than the very land path it predicts: `_update_from_main` runs `_classify_land_merge_conflicts`,
    which resolves four mechanical classes without a human — committed DERIVED artifacts, the
    foldable journal, a spec conflict confined to the machine-managed `implements_signature` block,
    and the row-append ledgers. Measured 2026-08-17: a pair conflicting ONLY on `graph/index.json`
    and a signature block was split although the real merge resolved both. So a conflict is
    classified by THAT function — the same authority, reading the same three stages from the oids
    `merge-tree` already prints — and a merge whose every conflict it resolves is `land-resolvable`,
    accumulating its RESOLVED tree (never the marked one — see `_probe_resolved_tree`).

    `detail` IS THE THIRD ELEMENT AND IT EXISTS TO SEPARATE PROOF FROM INABILITY-TO-PROVE (T-11218).
    `outcome == "conflict"` is answered in FIVE distinct situations: the classifier RAN and named an
    unresolvable path — and four fallbacks that read nothing (an unparsable stream, no derived-artifact
    set, a classifier that raised, a resolved tree that would not compose). For the EVICTION consumer
    that conflation is correct and deliberate: every fallback lands on the PRE-CHANGE verdict, i.e.
    fail-CLOSED toward evicting. For the PRE-QUEUE consumer it is exactly wrong, because that one is
    fail-OPEN (SPEC-0184 / T-11218 AC5) and must never refuse a land on evidence it did not read. So
    `detail` is `{"resolved": [...], "unresolved": [...]}` — the classifier's OWN verdict — ONLY when
    `_classify_land_merge_conflicts` actually ran to a result, and None on every path where it did
    not. `outcome` and `tree` are unchanged value-for-value on every branch, so the eviction
    consumer's behaviour is byte-identical to T-11216's.
    """
    if _git_rev(branch, main_wt, _run_git_cap=_run_git_cap) is None:
        return ("unevaluable", None, None)     # belt: an unresolvable ref never reaches the oracle
    try:
        r = _run_git_cap(["merge-tree", "--write-tree", "-z", accum, branch], main_wt)
    except Exception:                          # noqa: BLE001 — git could not run: not a conflict
        return ("unevaluable", None, None)
    tree, paths, stages = _merge_tree_conflict_stages(getattr(r, "stdout", "") or "")
    readable = bool(tree)
    if getattr(r, "returncode", 1) == 0:
        # A clean exit with no tree we can read is not a clean merge we can use: fail-closed.
        return ("clean", tree, None) if readable else ("unevaluable", None, None)
    if getattr(r, "returncode", 1) != 1 or not readable:
        return ("unevaluable", None, None)
    if not paths or _DERIVED_MERGE_ARTIFACTS is None:
        return ("conflict", None, None)        # nothing classifiable — the pre-change verdict

    def _stage_blob(path: str, stage: int) -> "str | None":
        """One conflict stage's CONTENT, by oid — the probe's index-free `git show :<n>:<path>`."""
        oid = (stages.get(path) or {}).get(int(stage))
        if not oid:
            return None                        # a stage the merge did not produce: no 3-way basis
        try:
            b = _run_git_cap(["cat-file", "blob", oid], main_wt)
        except Exception:                      # noqa: BLE001
            return None
        return b.stdout if b.returncode == 0 else None

    try:
        # T-11291: the probe reads the same-anchor re-derivation from the tree `merge-tree` produced,
        # so it stays the SAME oracle as `land` (T-11216). Without this the probe would evict every
        # same-anchor pair the land path now resolves — the stricter-second-oracle split again.
        resolved, unresolved = _classify_land_merge_conflicts(
            paths, main_wt, _run_git_cap=_run_git_cap,
            _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
            _show_stage=lambda stage, path: _stage_blob(path, stage),
            _merged_anchor_signature=(
                _merged_tree_oid_anchor_signer(
                    tree, main_wt, _run_git_cap=_run_git_cap,
                    _anchor_signature_of_text=_anchor_signature_of_text)
                if _anchor_signature_of_text is not None else None))
    except Exception:                          # noqa: BLE001 — could not classify: not an admission
        return ("conflict", None, None)
    # From here the classifier HAS spoken, so every return carries its verdict.
    detail = {"resolved": sorted(resolved or {}), "unresolved": list(unresolved or [])}
    if unresolved:
        return ("conflict", None, detail)
    merged_tree = _probe_resolved_tree(tree, resolved, stages, main_wt,
                                       _run_git_cap=_run_git_cap, _dedup_events=_dedup_events)
    # A resolved tree that will not compose is still "nothing was PROVEN unresolvable": the eviction
    # consumer reads the `conflict` outcome (its pre-change verdict, unchanged), while the pre-queue
    # consumer reads the EMPTY `unresolved` and correctly refuses to refuse.
    return ("land-resolvable", merged_tree, detail) if merged_tree else ("conflict", None, detail)

def _land_mint_batch_id() -> str:
    """T-11331 (SPEC-0184 rule 5) — MINT the batch join key. One id per FORMATION, opaque and unique.

    THE SEAM WAS COMPLETE AND THE VALUE WAS NEVER SUPPLIED. `_emit_land_batch_formed`,
    `_emit_land_member_verdicts`, `_land_dissolve_batch` and `_land_reconcile_member_verdicts` have
    all accepted `batch_id` since T-11191, and the emitter's own docstring states what it is for: it
    "lets a member's row be read WITHOUT reconstructing the batch (rule 5's actual point)", with the
    mint deferred to "when formation exists". Formation shipped; the mint did not. Measured over the
    2026-08-16..19 window, `batch_id` was present on 7 of 103 `land_member_verdict` rows and 1 of 229
    `land_batch_formed` rows, so a main-side reader had to reconstruct a batch from branch plus
    timestamp proximity — which MIS-ATTRIBUTES whenever one branch appears in several batches, and
    task/T-11247 appeared in three consecutive batches on 2026-08-19 alone.

    OPAQUE ON PURPOSE. The id joins rows; it must never be PARSED for meaning. A timestamp- or
    branch-derived id would invite exactly the reconstruction-by-inference this key exists to retire,
    and would collide across the concurrent lands the design expects (CHARTER §P6 — concurrent
    sessions are normal). `uuid4` is already this module's minting primitive (the session-ref mint),
    so this reuses it rather than adding a second source of identity.

    Pure: no I/O, no journal, no state. The CALLER decides WHETHER a formation mints one — a
    singleton never does, which is what keeps rule 1's quiet-repo byte-identity untouched."""
    return "bat-" + uuid.uuid4().hex[:12]

def _land_note_batch_declared(batch_state: "dict | None", members: "list[dict] | None") -> None:
    """Record `members` as DECLARED for this land, accumulating across ff-race retries.

    ACCUMULATION IS THE POINT, and it is why this is not a plain assignment. A retry forms a FRESH
    batch (the queue at the new slot-free moment is a different fact), so overwriting would discard
    attempt 1's declarations — and a member declared once and never seen again is precisely the case
    this card exists to catch. Dedup is by BRANCH because a member re-declared on attempt 2 and then
    landed has been accounted for; it is one member, not two.

    AND THE ID TRAVELS WITH THE DECLARATION, NOT WITH THE DICT (T-11653). `batch_state["batch_id"]`
    is RE-MINTED per formation and is `None` for a singleton, so a retry that re-forms — solo after a
    peers-release, or as a different multi-member batch — OVERWRITES it while this list keeps
    accumulating. One id on the dict therefore cannot describe a set gathered across several
    formations: measured 2026-08-26, batch `bat-f87ad4725968` declared four members, a solo
    re-formation blanked the id, and the sweep emitted `unaccounted` for two of them carrying
    `batch_size: 4` and no key at all — the accumulated set, joinable to nothing. Recording the id
    HERE makes it as durable as the declaration it belongs to, which is the same durability the
    member list already has. Dedup-by-branch means a member re-declared by a LATER formation keeps
    the FIRST one's id: the formation that declared it is the row a reader joins to, and the later
    one produced its own verdict row anyway.

    OPTIONAL, so nothing forces the key: a caller whose state carries no id appends today's exact
    record shape, which is what keeps every hermetic probe and the singleton path byte-identical.
    """
    if batch_state is None:
        return
    seen = batch_state.setdefault(_LAND_BATCH_DECLARED_KEY, [])
    known = {(m or {}).get("branch") for m in seen}
    # T-11653 — STAMP THE FORMATION'S JOIN KEY ONTO THE DECLARATION ITSELF. Read off the same
    # `batch_state` this function already receives, because `cmd_land` publishes the freshly minted
    # id there one screen ABOVE the call that brings us here — so at this instant it is precisely
    # the id of the formation making this declaration.
    _bid = batch_state.get("batch_id")
    for m in members or []:
        br = (m or {}).get("branch")
        if br and br not in known:
            known.add(br)
            rec = {"branch": br, "task": (m or {}).get("task")}
            if _bid:
                rec["batch_id"] = _bid
            seen.append(rec)

def _land_declared_members_awaiting_verdict(batch_state: "dict | None") -> "list[dict]":
    """T-11702 — the members THIS land DECLARED and has not yet answered for. Pure; no I/O, no git,
    no queue read.

    THE HOLE IT FILLS. `cmd_land` resets `batch_members` at the top of EVERY attempt, and the whole
    batch apparatus — formation, the id mint, the declaration, `formed_size`, the eviction, the
    candidate merge — sits inside `if do_test_verify:`. An INERT RETRY (`reverify_skipped`) skips
    that block, so an attempt that inherits a batch declared by an EARLIER attempt and then reaches
    the fast-forward arrives at the post-ff `landed` emit with `batch_members` still `None`. The
    emitter is handed an empty list and emits nothing — not because the batch was a singleton (rule
    1) and not because the size was wrong (T-11641 fixed that and its `formed_size` is correctly 2
    here), but because there is no member list left to emit FOR. The `finally` reconciler then reads
    the SAME declaration this function reads, finds no verdict for the head, and correctly sweeps a
    branch that DEMONSTRABLY LANDED as `unaccounted`. Measured 2026-08-27: batch
    `bat-175e41ae8445`, `land_completed` status=ok sha=40195a5 at 10:07:51Z on attempt 2 with
    `reverify_skipped: true`, `40195a5` an ancestor of main — and both members journaled
    `unaccounted` at 10:09:28Z.

    IT IS A READ OF THE RECORD, NOT A RE-DERIVATION — which is the whole reason it may exist at all.
    T-11214 deleted the old `or _land_batch_members(branch)` fallback from that seam and was RIGHT
    to: re-reading the QUEUE post-ff answers a DIFFERENT question (who is waiting NOW) and can
    attribute a verdict to a land that never carried the member. This asks no new question and
    consults no new source. It reads `declared` — the set recorded at the same instant, and from the
    same list, as the `land_batch_formed` row that PUBLISHED the batch — minus `verdicted`, the sink
    the one emitter appends every journaled branch to. Both keys already exist and are already read
    together, in exactly this pairing, by `_land_reconcile_member_verdicts`; extracting the read
    means the `finally` sweep and the post-ff emit share ONE answer to "who is still unanswered?"
    rather than each spelling their own (CHARTER §P5).

    IT CLAIMS NOTHING. The returned list is a set of CANDIDATES, and the caller must pass it through
    `_land_members_carried_by_ff` — the unmodified two-sided, fail-closed filter that asks whether
    THIS fast-forward actually moved `main` by a member — before any of them may be journaled
    `landed`. That ordering is load-bearing and is the reason this function does not itself emit: a
    declared member the ff did not carry has to fall out as `not-in-landed-history` and go on to be
    swept `unaccounted`, because `unaccounted` exists to make a vanished member LOUD. Repairing the
    emit must never be confused with silencing the reconciler.

    ALREADY-VERDICTED MEMBERS ARE EXCLUDED, and by the same key the emitter feeds: a peer evicted on
    attempt 1 has its outcome and must not collect a second row. That makes this idempotent for the
    same reason the reconciler is.

    ORDER IS THE DECLARATION'S OWN, first-declared first — deterministic, and it keeps the head
    (declared first, as `batch_members[0]`) at index 0 for every reader downstream that treats the
    head positionally.

    RETURNS `[]` FOR A LAND THAT DECLARED NOTHING, which is what keeps rule 1's quiet-repo promise
    intact: a `--no-tests` land, a hermetic caller supplying no state, and a `None` state all resolve
    to the empty list the caller already had.
    """
    if batch_state is None:
        return []
    verdicted = set(batch_state.get(_LAND_BATCH_VERDICTED_KEY) or [])
    out: "list[dict]" = []
    for m in batch_state.get(_LAND_BATCH_DECLARED_KEY) or []:
        br = (m or {}).get("branch")
        if not br or br in verdicted:
            continue
        rec = {"branch": br, "task": (m or {}).get("task")}
        # T-11653's key, carried through UNCHANGED: it travels with the DECLARATION, not with the
        # state dict, because `batch_state["batch_id"]` is re-minted per formation while `declared`
        # accumulates across them. The reconciler GROUPS by it; the post-ff emit ignores it and
        # passes its own `batch_id` argument, for which an extra key on a member record is inert.
        if (m or {}).get("batch_id"):
            rec["batch_id"] = m["batch_id"]
        out.append(rec)
    return out

def _land_note_batch_removals(batch_state: "dict | None", removed: "list[dict] | None") -> None:
    """Record `{branch: removal_reason}` for members a filter took out of the batch.

    BEST-EFFORT ENRICHMENT, NEVER THE GUARANTEE. The guarantee is the row `_land_reconcile_member_
    verdicts` emits; this only lets that row say WHY. A future filter that removes members and
    forgets to call this degrades its members to a bare `unaccounted` — still loud, still exactly
    one row — which is the failure direction that keeps the accounting honest instead of silent.
    FIRST reason wins: a member removed at one seam and re-listed at a later one was removed for the
    first cause, and overwriting would report the symptom in place of the cause.
    """
    if batch_state is None:
        return
    seen = batch_state.setdefault(_LAND_BATCH_REMOVED_KEY, {})
    for m in removed or []:
        br = (m or {}).get("branch")
        reason = (m or {}).get("removal_reason")
        if br and reason and br not in seen:
            seen[br] = str(reason)

def _land_pinned_entry_culprits(members: "list[dict]", assertions: "list[str] | None", *,
                                _changed_paths=None, _test_files=None, head_pre_sha: "str | None" = None, _land_attribute_failing_assertions=None, _land_red_batch_ineligible_members=None) -> "dict | None":
    """T-11515 — WHO a PINNED-entry red is attributable to, for the eviction fork. Returns an
    isolation-SHAPED record, or `None` when it has nothing to add and the caller must keep the
    decline it already has.

    THE DEFECT IS AN ORDERING ONE, NOT A MISSING ANSWER (measured 2026-08-25). The re-run oracle
    `_land_red_isolation_probe` refuses a `[pinned/last-green] ` entry at gate 1 and returns
    `undecidable(pinned-entry)` — correctly, because reproducing a pinned entry needs the pinned
    OVERLAY construction (last-green checks over a candidate subject), not a plain re-run of a test
    file. The fork then dissolves and requeues every member. But the batch is NOT ignorant: two calls
    later, inside `_land_dissolve_batch`, `_land_attribute_failing_assertions` names the member that
    uniquely owns the failing pinned assertion, and `_land_red_batch_ineligible_members` decides
    whether that naming accounts for the WHOLE red. The answer existed one call too late to save
    anybody. Folded over this repo's journal: 39 member rows across 13 batches declined
    `pinned-entry` in the five days after T-11335 shipped; on 7 of those batches the attribution
    reached a culprit set that accounts for the whole red and leaves a survivor, and on 4 of them
    that set contains no head — bat-097010c5c4a5, bat-168541e34f09, bat-33576e0b8295,
    bat-92310ac16db5, together 8 innocent peers requeued for a supersession that was already
    attributed to somebody else.

    IT REUSES THE JUDGEMENT, IT DOES NOT MAKE ONE. Both callees are invoked unchanged, and the
    culprit set returned IS `_land_red_batch_ineligible_members`'s own answer. That function's
    POSITIVE discriminator — every failing entry must be a pinned entry some member was attributed
    with — is exactly the condition rule 4 already states before letting the one-round ineligibility
    mark fall on the culprits alone, so this adds no new gate and can widen no existing one. The four
    fail-closed attribution gates (pinned only / a named assertion / a basename resolving to exactly
    one known path / exactly one member having modified it) are untouched; a widened gate would
    manufacture the plausible-wrong answer their whole shape refuses.

    WHY IT IS SOUND TO EVICT ON THIS, WHEN THE MARKS WERE WRITTEN "REPORT-ONLY". Two reasons, and the
    second is the load-bearing one. First, these same marks ALREADY drive a consequential decision:
    since T-11272 they decide which members rule 4 charges a batch-ineligible round to. Second, and
    unlike the re-run oracle, what gate 4 proves is not "this member's code breaks a test" but "this
    member CHANGED the very file whose last-green assertion the merged tree now fails" — which is a
    supersession the member must declare on its OWN land (`--rebaseline-waive`, SPEC-0077 §3a) and
    which no peer may declare for it. Evicting it is therefore not a guess about blame; it is
    routing the branch to the only land that can legitimately resolve its own red.

    IT NEVER CLAIMS A REPRODUCTION. `reproduced` is `{}` and the reason is
    `pinned-entry-attribution`, so a reader can always tell an attributed culprit from a
    re-run-PROVEN one. Recording a reproduction nothing ran would be exactly the fabricated verdict
    SPEC-0184's release arm refuses for `not-probed`.

    IT DECIDES NOTHING BEYOND NAMING. The caller's four conditions are unchanged and apply to this
    record identically — so the HEAD-is-culprit case (3 of the 7 measured batches) still falls
    through to today's dissolve, a no-survivor set still dissolves, and a spent eviction budget still
    dissolves. It returns `None` on every path where it cannot improve on the decline, including
    absent readers, so every caller and probe that supplies none is byte-identical.

    `head_pre_sha` — THE HEAD MEMBER'S DIFF MUST BE READ AT ITS PRE-BATCH SHA, NOT AT ITS BRANCH REF
    (T-11688, measured on bat-d2e75d833e82). Between `_land_merge_batch_into_candidate` and
    `_land_restore_candidate_head` the head member's BRANCH IS THE COMBINED CANDIDATE: the peers'
    commits are on it. This function is called INSIDE that window, and the dissolve's attribution
    runs one call AFTER the restore closes it — so the same `_changed_paths` reader answers two
    different questions at the two seams. At the fork it reports the head as having changed every
    peer's paths, so attribution gate 4 sees TWO owners for every entry, refuses both, marks nobody,
    and this returns `None` at the gate below — while the identical call inside the dissolve names
    the culprit correctly. That is why a mechanism whose every documented precondition was met
    produced ZERO records across all 39 pinned-entry declines since it shipped: the pollution is
    present on EVERY batch red by construction, so the decline was never about the batch's evidence
    at all.

    WHAT IT IS AND WHAT IT IS NOT. It corrects an INPUT that was reading the wrong tree. It is NOT a
    fifth gate and it WIDENS none of the four: the pinned-only, named-assertion, one-resolved-path
    and exactly-one-owner conditions are evaluated unchanged, on a head diff that finally describes
    the head. Nor does it move blame — `_land_red_batch_ineligible_members` stays the sole author of
    the culprit set, and the head is if anything blamed LESS, since it stops being credited with
    changes that are its peers'.

    ONLY MEMBER 0, AND ONLY WHEN SUPPLIED. The merge accumulates onto the head member's branch and no
    other member's ref moves, so every peer is read exactly as before. Absent (the hermetic callers,
    every probe, any future caller holding no pre-batch sha) the reader is passed through untouched
    and behaviour is byte-identical to today — a decline, which is the fail-closed direction: a
    caller that cannot say what the head was before the batch must not be answered as though it had.
    """
    if not members or len(members) < 2 or not assertions:
        return None
    if _changed_paths is None or _test_files is None:
        return None
    # THE HEAD IS RESOLVED AT ITS PRE-BATCH SHA (T-11688) — see the docstring. The substitution is a
    # member RECORD the reader is asked about, not a second differ: `_land_member_changed_paths` asks
    # `main...<branch>` and a sha is a legal right-hand side there, so ONE diff definition still
    # serves every member. Guarded on both the sha and the head being a dict, so an absent sha or a
    # malformed member falls through to today's reader rather than fabricating one.
    _read_paths = _changed_paths
    if head_pre_sha and isinstance(members[0], dict):
        _head_id = id(members[0])
        _head_stub = dict(members[0])
        _head_stub["branch"] = str(head_pre_sha)

        def _read_paths(_m, _inner=_changed_paths, _hid=_head_id, _stub=_head_stub):
            return _inner(_stub if id(_m) == _hid else _m)
    # Marks the member dicts IN PLACE, exactly as the dissolve does — and idempotently, so the
    # dissolve's own later call on a NON-evicting path re-derives the identical marks rather than
    # doubling them (`superseded_assertions` appends only what it does not already carry).
    if not _land_attribute_failing_assertions(members, assertions,
                                              _changed_paths=_read_paths,
                                              _test_files=_test_files):
        return None
    culprits = _land_red_batch_ineligible_members(members, assertions)
    # The blanket IS the decline: "everyone" means the attribution did not account for the whole red,
    # which is the same answer as `undecidable` and must not be dressed up as a culprit set.
    if not culprits or len(culprits) >= len(members):
        return None
    return {"outcome": "culprits",
            "reason": _LAND_PINNED_ATTRIBUTION_REASON,
            "culprit_indices": sorted(int(i) for i in culprits),
            "failing": [str(a) for a in assertions],
            "reproduced": {}}

def _land_pinned_supersession_branches(events_path: "Path | None",
                                       *, _rows: "list | None" = None,
                                       truncated_out: "list | None" = None,
                                       now: "float | None" = None) -> "set[str]":
    """T-11267 (SPEC-0184 rule 4) — the branches whose OWN latest `commit_landed` row already carries
    a fired pinned-supersession notice, and which must therefore be verified ALONE this round.

    WHY THIS IS THE SAME QUESTION RULE 4 ALREADY ASKS, from a THIRD source. Rule 4 learns
    ineligibility from a red batch (AFTER a pass is spent); T-11239 learns it from a `--rebaseline`
    declaration (BEFORE one). This learns it from a signal the system ALREADY WROTE DOWN and then
    ignored: `task commit` / `work commit` records `data.pinned_supersession` on the `commit_landed`
    row when the commit's own diff REMOVES an assertion line from the pinned surface (T-11257 detects
    it, T-11262 records it). A member that probably supersedes a pinned assertion reddens the whole
    combined candidate, and only its own scoped `--rebaseline-waive` declaration could clear that red
    (SPEC-0077 §3a) — so excluding it before the pass costs the batch nothing it could have had.

    A HYPOTHESIS, NOT A MEASURED PRECISION — and the docstring says so because the code cannot. The
    notice has fired EXACTLY ONCE since it began being journaled (2026-08-18T06:03:41Z), and that one
    firing preceded one four-member batch death by 4m47s (T-11253 / T-11259). n=1: one firing
    predicting one death is not a precision measurement and must never be reported as one. What
    supports the rule beyond n=1 is the notice's DESIGN (it fires only on a REMOVED assertion line, so
    it stays off the ~90% of branches that merely touch `tests/`) and undeclared supersession being
    3-for-3 as the cause of post-fix batch deaths (T-11232 / T-11177 / T-11253).

    A MEANINGFUL EVENT DISCHARGES THE FLAG — A ROW'S MERE ARRIVAL DOES NOT (T-11268, tightening
    T-11267). A commit row carrying the notice ARMS the exclusion. Only an event that RESOLVES the
    supersession discharges it, and there are exactly two: an evidence-bound `--rebaseline`
    declaration naming the assertion (carried OUTSIDE this reader, by the precedence subtraction in
    `_land_batch_members` against `_land_rebaselining_branches`), or a later SHIP COMMIT — a
    task-tied row for a real code change-set — that itself fired no notice. Every other row is
    BOOKKEEPING and is PASS-THROUGH here: it neither arms nor discharges, and leaves the branch
    exactly as the last meaningful event left it.

    WHY, MEASURED ON THIS RULE'S OWN FOUNDING CASE. T-11267 shipped "the latest row wins; a later
    keyless row clears", which made this function STRUCTURALLY INERT: the Stage-9 CLOSURE record is a
    commit row the lifecycle emits for every task between its ship commit and its land, so the ship
    commit armed the flag and the closure commit disarmed it before any land could be attempted.
    task/T-11253 — the branch this rule was built from — emitted its keyed ship row at
    2026-08-18T06:40:56Z and a `kind: closure` row at 06:43:05Z, 2m38s BEFORE the 06:45:43Z
    formation. Run against main's journal the shipped version returned an EMPTY SET while the ground
    truth held that one keyed row. Not one unlucky ordering: 2189 of 2376 task ids carry more than
    one `commit_landed` row and 2052 of those rows are closure records.

    THE SHIP TEST IS A POSITIVE TEST, NOT A BOOKKEEPING BLOCKLIST, AND THAT IS THE FAIL DIRECTION.
    `task commit` — the only emitter of a task's ship row — writes no `data.kind`; every bookkeeping
    emitter names one (`closure`, `pause`, `wont-do`, `park`, `closes_fp_link`, `pv_late_link`,
    `probe_settle_link`, `reaudit-after-close`, `history-rewrite-repin`, `plan-*`, and `work` for the
    task-id-less `work commit`). So discharge REQUIRES the absence of a kind: a kind invented by a
    later card cannot discharge by default, and no enumeration has to be kept current for that to
    hold. A missed discharge costs one extra SOLO round; a wrong one admits exactly the member this
    rule exists to keep out. Arming stays unconditional on kind — a substantive notice is a fact
    about a diff whatever row carries it. The judgement that an ABSENT `kind` means "ship" is made
    HERE, in the reader that needs it, and is not pushed into a shared row parser where a sibling
    question would silently inherit it (lessons/fail-closed-belongs-to-the-reader-not-the-parser).

    NON-PERMANENCE SURVIVES, and a branch that declares its waive or ships again cleanly is
    admissible IMMEDIATELY — so this stays a one-round exclusion and never becomes the quarantine
    T-11241 had to repair at the other end.

    THE THIRD DISCHARGE IS EXPIRY, AND IT REPLACES THIS PARAGRAPH'S PREDECESSOR (T-11870). What used
    to stand here was "there is deliberately still NO freshness window", reasoning that a commit row
    is a fact about a commit and does not go stale, and that a window would EXPIRE a live supersession
    in the wrong fail direction. The first half is true and the second was answering the wrong
    question. The claim was never actually kept: the read was a 512KB byte tail covering roughly 36
    minutes of a busy journal, so the operative lifetime was a write-rate artefact — shortest exactly
    when the journal is busiest, which is when the answer is load-bearing — that nothing declared and
    nothing reported. An unbounded lifetime cannot be served by a bounded read AT ALL, and the
    coverage report cannot rescue it either — loudness is not reach. T-11904 made the archive case
    LOUD (reaching offset 0 counts as coverage only when no older segment sits beside the journal, so
    a short live segment is REPORTED as the SPEC-0190 rule-4 condition it is), but a report that the
    answer is truncated is not an answer: an arming row rotation moved into an archive is still
    outside what a live-segment read can see. Declaring a finite lifetime is what makes read and rule
    the same number.
    THE FAIL DIRECTION IS THE ONE THIS FUNCTION ALREADY DECLARES, three paragraphs down: fail-OPEN,
    where a missed exclusion costs ONE repeated batch and a spurious one shrinks batches on bad data.
    An expiry can therefore only cost a pass; it can never admit a wrong exclusion. Rule 4's red-batch
    fallback is untouched behind it — a branch that really does supersede still reddens its batch,
    still takes the one-round mark and is still verified alone. This reader SAVES that pass; it is
    not what makes the outcome safe.
    IT IS ENFORCED AS A RULE, NOT AS AN ARTEFACT OF THE READ. The `ts` test below runs over whatever
    rows arrive — including an INJECTED `_rows` list that no window ever bounded — so a row older than
    the horizon discharges because the rule says so, never because the scan happened to stop short.
    That is the difference between a lifetime and a byte budget, and it is the whole point.

    THE KEY IS READ AS A RECORD, NEVER AS MERE PRESENCE. A row must carry a `pinned_supersession`
    MAPPING with `count >= 1` to flag its branch; `true`, `0`, a string or a malformed value flags
    nothing. Recording the notice as an absent-or-substantive key is T-11262's own contract (an absent
    key means "did not fire", never "fired and found nothing"), and a rule that excluded on presence
    alone would pass its tripwire while acting on a row it never actually read.

    THE BRANCH KEY IS DERIVED FROM `task_id`, so this answers for `task/T-XXXX` branches only. A
    `work/<slug>` batch has no task id on its commit rows and is never flagged — it is admitted as
    today, which is the fail-open direction the whole family takes.

    FAIL-OPEN TO THE EMPTY SET, always — an unreadable journal, a missing path or an unparseable line
    all yield "nobody is superseding", i.e. ordinary formation. Same direction, and for the same
    reason, as `_land_batch_ineligible_branches` and `_land_rebaselining_branches`: a missed exclusion
    costs ONE repeated batch, while a spurious one would shrink batches on bad data.

    WHAT THIS READ CANNOT SEE, stated so the instrument is not overstated (measured 2026-08-18,
    deviation `pinned-supersession-key-on-peer-commit-row-not-visible-from-main-journal-at-batch-
    formation`). A QUEUED PEER's freshest `commit_landed` rows live in its OWN worktree journal until
    its land folds them, so they are not in `main`'s. The caller therefore points this read at the
    LANDING worktree's journal, which by then holds BOTH main's rows (folded at step 2b) and this
    land's own — covering the HEAD, which is the traced T-11253 shape, plus every peer whose
    superseding commit has already reached the read journal. A peer whose supersession is still
    branch-local is NOT seen; that is a bound of the carrier, not of this rule, and it is not repaired
    here.
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return set()
        try:
            p = Path(events_path)
            if not p.exists():
                return set()
            # T-11870 — the LAST of this family off the byte tail. Its three siblings (rules 4+9,
            # rule 12, and T-11239's declared-rebaseline read) moved to `_land_horizon_rows` at
            # T-11816; this one stayed, so the single reader whose exclusion protects a PINNED
            # assertion was also the one whose window shrank fastest under load. The span is now
            # sized by this answer's own DECLARED lifetime, and a window that cannot reach it is
            # REPORTED rather than silently answered short. `base_bytes` keeps the old constant so
            # the quiet-journal case costs exactly what it costs today; `commit_landed` stays the
            # prescan token and the parsed type check below still decides membership, so nothing
            # about what this read ADMITS moves.
            rows = _land_horizon_rows(
                p, "commit_landed", horizon_s=_LAND_PINNED_SUPERSESSION_HORIZON_SEC,
                label="pinned-supersession (SPEC-0184 rule 4, T-11267)",
                truncated_out=truncated_out, now=now,
                base_bytes=_LAND_QUEUE_TAIL_BYTES)
        except Exception:                      # noqa: BLE001 — fail-open: nobody is superseding
            return set()
    _now = time.time() if now is None else float(now)
    _cutoff = _now - float(_LAND_PINNED_SUPERSESSION_HORIZON_SEC)
    state: "dict[str, bool]" = {}
    for ev in rows or []:
        if not isinstance(ev, dict) or ev.get("type") != "commit_landed":
            continue
        # T-11870 — THE EXPIRY DISCHARGE, applied as a rule over every row that arrives. A row older
        # than the declared lifetime neither arms nor discharges: it is simply not evidence about
        # this round any more, exactly as if it had never been in the window. Applied to arming AND
        # discharging rows alike, because dropping only the arming ones would let an aged discharge
        # clear a flag armed inside the window off a fact that predates it.
        # AN UNDATABLE ROW IS KEPT, never discarded: `_land_queue_row_epoch` returning None means the
        # row's AGE is unknown, and this reader is fail-open only about missing an exclusion — it
        # must not invent an expiry it cannot date. The row then governs by position as before.
        _ts = _land_queue_row_epoch(ev.get("ts"))
        if _ts is not None and _ts < _cutoff:
            continue
        tid = str(ev.get("task_id") or "").strip()
        if not tid:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        rec = (data or {}).get("pinned_supersession")
        count = rec.get("count") if isinstance(rec, dict) else None
        fired = (isinstance(count, int) and not isinstance(count, bool) and count >= 1)
        if fired:
            # ARMS, whatever kind the row names: the notice is a fact about a diff.
            state[f"task/{tid}"] = True
        elif (data or {}).get("kind") is None:
            # DISCHARGES: a SHIP row (only `task commit` emits one, and it writes no `kind`) that
            # itself fired no notice. The absence of a kind is the positive ship test — a
            # bookkeeping kind invented later cannot discharge by default.
            state[f"task/{tid}"] = False
        # else: BOOKKEEPING — pass-through. A row that changed no code resolves no supersession, so
        # it neither arms nor discharges; the branch stays as the last meaningful event left it.
        # (The other discharge route — a declared `--rebaseline` — is applied by the caller, which
        # subtracts `_land_rebaselining_branches` from this set. It is not re-derived here.)
    return {br for br, flagged in state.items() if flagged}

def _land_prequeue_currency_refusal(W: Path, branch: str, main_wt: Path, *, _run_git_cap,
                                    EVENTS_PATH, _classify_inert_paths,
                                    owner_rebaseline: bool = False,
                                    _DERIVED_MERGE_ARTIFACTS=None,
                                    _anchor_signature_of_text=None,
                                    _preflight=None, _git_rev=None, _land_audited_footprint_abort_detail=None, _land_preflight_currency_lines=None, _offending_drift_is_merge_produced=None) -> "tuple[str, dict] | None":
    """T-11391 — REFUSE, BEFORE THE QUEUE, a land whose audited diff is provably STALE.
    Returns `(abort MESSAGE, abort_detail)`, or None to proceed. Both halves come from the ONE
    verdict — the text through `_land_audited_footprint_lines`, the machine record through
    `_land_audited_footprint_abort_detail`, the same two projections the in-lock gate uses — so a
    reader of the journal row cannot tell which side answered, which is the point. The SIBLING of `_land_prequeue_merge_refusal`:
    same position, same polarity, same oracle-reuse discipline, a second proven-blocking class.

    THE MEASURED COST. Audit currency refused task/T-11353 once and task/T-11380 twice on 2026-08-21,
    and each refusal came AFTER the reservation — a queue position spent to learn something the
    branch could have been told in milliseconds. The corpus carries the class independently:
    task/T-11232 was marked batch-ineligible and aborted `audited-diff-stale` having run nothing,
    and that row discharged its rule-4 mark, so it was re-admitted into a second batch that died on
    the same assertion. What is MEASURED here is only that the refusal costs a reservation it need
    not cost; that moving it earlier shortens wall-clock is a hypothesis and is not claimed.

    NO SECOND ORACLE. The verdict comes from `_land_preflight_currency_lines` — T-11313's
    computation, unmodified — which is itself a thin caller of `_land_audited_footprint_split` +
    `_land_audited_footprint_lines`, the SAME pair the in-lock gate reaches at `_land_integrate`.
    So all three sites (this probe, the `worktree sync` pre-flight, the gate) answer from one
    definition, and a future edit that forks them changes the call target this card's tests assert.

    THE ADMISSION CONDITION IS THE WHOLE CORRECTNESS ARGUMENT, and it is a PER-PATH PROVABILITY
    TEST — not a property of the branch (T-11402 widened it; read this whole block, the old
    branch-level sentence is now its degenerate case). `_land_preflight_currency_lines`'s own fence
    says currency is judgeable only AFTER update-from-main, because the merge is what breaks it.
    Pre-queue there is no merge yet. In the fail-open direction that is only a MISS — but it can also
    over-refuse: a path BOTH sides touched can, post-merge, land in `mechanical_resolve` (T-11332) or
    `merge_inherited` and stop being a blocker, so a pre-merge verdict is not always the land's
    verdict. Refusing on that would be exactly the false abort SPEC-0184 rule 3 calls worse than a
    slow success.

    So the verdict is computed against the MERGE-BASE of `main` and the branch — which is an ancestor
    of HEAD for EVERY branch, so `_merged_tree_delta_paths`'s fail-closed raise-guard never fires and
    a verdict always EXISTS — and it is acted on ONLY when the pending merge provably cannot change
    it: when EVERY offending path (`own_post_audit` + `unclassified`) is UNTOUCHED on main since that
    merge-base. For such a path the merge takes the branch's content verbatim — no conflict is
    possible, nothing can be inherited from main, so the path's bucket pre-merge IS its bucket
    post-merge. Where even ONE offending path HAS moved on main since the base, the merge genuinely
    can re-bucket it and this refuses nothing: it proceeds and the gate decides.

    THE OLD RULE IS THE DEGENERATE CASE OF THIS ONE, which is why the re-basing regresses nothing.
    When the branch ALREADY CONTAINS main's tip (T-11391's original admission), merge-base == that
    main tip, so (i) the computation's base is byte-identical to what it was — the `behind == 0` path
    T-11313's docstring blesses as "EXACTLY what land passes as merged_base", the shape of the
    measured task/T-11309 refusal — and (ii) `<merge-base>..main` is EMPTY, so the untouched test is
    trivially satisfied and every branch refused before is still refused, on the same verdict. The
    widening ADDS the behind-main-but-provable case and subtracts nothing; the `--is-ancestor` gate
    is REMOVED rather than given a sibling, because it has become a special case of the test above.

    WHY IT EXISTS AT ALL — the measured admission rate. T-11391's tip-containment condition almost
    never held in this repo's land traffic: five consecutive attempts on 2026-08-21, each a `worktree
    sync` immediately followed by `land`, ALL found main advanced again by the time land read it (a
    sync takes ~30s and main moves inside that window), so the probe fail-opened and the branch
    queued exactly as before. The check was correct and rarely reached its verdict.

    ONE MAIN SNAPSHOT, NOT FOUR (audit-pre finding F1, absorbed). `main` moves under this probe, so
    `main_rev` is resolved ONCE and that single sha is what the merge-base, the oracle's base, the
    main-touched diff and the refusal message are all computed from. A second `main` read could prove
    the verdict against one snapshot and its provability against another.

    THE PROVABILITY TEST IS ASKED ONLY OF A VERDICT THAT ALREADY EXISTS (audit-pre finding F2,
    absorbed). The disjointness test runs BELOW the `if not lines` fail-open, never above it — so an
    oracle that answered "nothing stale" can never satisfy the empty-set condition vacuously. That
    ordering is asserted by the tests, because it is silently reversible.

    FAIL-OPEN, the T-11218 polarity, unchanged. The in-lock gate stays the AUTHORITY and stays
    fail-CLOSED; this is a cheap predictor of it. Every answer it cannot prove — an unreadable ref, a
    git that would not run, an unresolvable merge-base, an uncomputable main-touched set, an
    offending path main HAS moved, an absent or unreadable audit record, a split that
    could not answer, any exception raised in here — proceeds into the queue. It never invents a
    refusal it could not prove, and it can never make a land that would have succeeded fail.

    IT RIDES THE EXISTING ABORT. Same wrapped `_die`, same `_AUDITED_DIFF_STALE_ABORT_CLASS` (so the
    T-0655 repeated-abort backstop keeps streaking on an unchanged key), same journal side effects —
    no new abort path, class or event type. The message NAMES the main sha and branch sha it was
    proved against, for the sibling's reason: this is stale-current-state, not a second authority.

    IT MAY ONLY ADD A REFUSAL, NEVER DISPLACE ONE — WHICH IS WHY `--rebaseline` IS EXEMPT. The
    in-lock gate is ordered AFTER the rebaseline preflight ON PURPOSE (T-10850 iii): every
    pre-existing rebaseline refusal is reached FIRST and keeps its exact message and its
    `rebaseline-unauthorized` class byte-identical, so the currency gate can only add a refusal
    where nothing refused before. Moving the same question ABOVE the whole attempt loop would
    silently invert that ordering for a `--rebaseline` land — a post-audit edit to a covered file
    would start aborting `audited-diff-stale` instead of `rebaseline-unauthorized`, which is a
    DIFFERENT diagnosis about a different decision (measured: `test_t9457_rebaseline_staleness_scope`
    caught exactly this). So an `owner_rebaseline` land is not judged here at all; it proceeds and
    the preflight, then the gate, decide in their established order.

    `_preflight` is an INTERNAL test seam ONLY (the verdict computation, injected) — never an env
    gate or an external control surface."""
    try:
        if owner_rebaseline:
            return None                        # the rebaseline preflight owns this land's ordering
        main_rev = _git_rev("main", main_wt, _run_git_cap=_run_git_cap)
        branch_rev = _git_rev(branch, main_wt, _run_git_cap=_run_git_cap) if branch else None
        if not main_rev or not branch_rev:
            return None                        # nothing to prove against: the in-lock gate decides
        # ONE main snapshot (F1): `main_rev` above is the ONLY `main` read in this function, and the
        # merge-base, the oracle's base, the main-touched set and the message all derive from it.
        try:
            mb = _run_git_cap(["merge-base", main_rev, branch_rev], main_wt)
        except Exception:                      # noqa: BLE001 — git could not run: nothing is proven
            return None
        if getattr(mb, "returncode", 1) != 0:
            return None                        # no common ancestor to compute against: proceed
        base_rev = (mb.stdout or "").strip()
        if not base_rev:
            return None
        contains_main_tip = (base_rev == main_rev)   # T-11391's original admission, now a special case
        preflight = _preflight if _preflight is not None else _land_preflight_currency_lines
        split: dict = {}
        lines = preflight(
            W, branch, base_rev, _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH,
            _classify_inert_paths=_classify_inert_paths,
            _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
            _anchor_signature_of_text=_anchor_signature_of_text,
            _header=("land: REFUSED — the diff about to land is NOT the diff that was audited "
                     "(SPEC-0077 §3a audit currency). Worktree intact, main untouched."),
            _split_out=split)
        if not lines:
            return None                        # not proven stale → into the queue (fail-open)
        # THE PROVABILITY TEST, asked ONLY of a verdict that already exists (F2 — this sits BELOW the
        # fail-open above ON PURPOSE, so a clean oracle can never satisfy the empty-set condition
        # vacuously). The offending set is read from the sink the oracle ALREADY published; nothing
        # is re-derived beside it (T-11391 AC3 / T-11216).
        offending = set((split.get("own_post_audit") or []) + (split.get("unclassified") or []))
        if contains_main_tip:
            moved_on_main: set = set()         # merge-base IS the main tip: `base..main` is empty,
        else:                                  # so T-11391's admitted case needs no diff at all
            if not offending:
                return None                    # a verdict whose offending set cannot be NAMED cannot
                                               # be proven immune to the merge either — fail-open
            try:
                d = _run_git_cap(["diff", "--name-only", f"{base_rev}..{main_rev}"], main_wt)
            except Exception:                  # noqa: BLE001 — cannot compute: nothing is provable
                return None
            if getattr(d, "returncode", 1) != 0:
                return None
            moved_on_main = {ln.strip() for ln in (d.stdout or "").splitlines() if ln.strip()}
        if offending & moved_on_main:
            return None                        # the pending merge can still re-bucket it: proceed
        # T-11754 (X-1153) — AND FAIL OPEN WHERE THE GATE CAN NOW CLEAR IT ITSELF. This predictor's
        # ONE contract is "this IS the verdict its own gate would reach"; SPEC-0077 §3a gained a case
        # where it is not. When NO non-merge commit since the audit touched any offending path, the
        # drift is what land's own update-from-main produced, and the in-lock gate takes an in-land
        # re-audit over the merged tree and re-judges. Refusing here would keep raising the very
        # abort the gate no longer raises — and it is raised HERE in practice: all five measured
        # `audited-diff-stale` rows of 2026-08-26..28 say "Refused BEFORE the land queue".
        # SAME PREDICATE as the gate (`_offending_drift_is_merge_produced` — one question, one
        # implementation, CHARTER §P5), asked of the SAME offending set the sink already published.
        # The `branch_tip` it passes is the BRANCH REF, because no pre-merge tip exists here: a
        # branch that has merged at all since its audit is therefore NOT proven at this site and
        # simply queues, and the gate re-asks with the strict tip in hand. That asymmetry is the
        # fail-open polarity doing its job, not a looser rule — this site can only ever proceed.
        # This can only ever ADD a fail-open, which is the polarity this whole function is built on:
        # it never makes a land that would have succeeded fail, and the fail-CLOSED authority
        # downstream is untouched — a branch whose re-audit cannot run, or comes back RED, still
        # aborts there, one queue position later.
        if _offending_drift_is_merge_produced is not None and _offending_drift_is_merge_produced(
                sorted(offending), W, (split.get("audit_commit") or None), main_rev, branch_rev,
                _run_git_cap=_run_git_cap):
            return None
        _why = ("which already contains that main tip, so land's update-from-main is a no-op."
                if contains_main_tip else
                f"whose merge-base with it is {base_rev}. Main has touched NONE of the "
                f"{len(offending)} offending path(s) since that base, so the pending "
                f"update-from-main takes the branch's content for each of them verbatim and "
                f"cannot change their bucket.")
        return ("\n".join(lines)
                + f"\nRefused BEFORE the land queue (SPEC-0184 rule 3 / T-11391, admission widened "
                  f"by T-11402): no reservation taken, no verify slot, no batch membership. Proved "
                  f"against main {main_rev} and branch {branch} {branch_rev}, "
                  f"{_why} So this IS the verdict its own gate would reach."
                + "\nRECOVERY: re-audit the CURRENT tree, then re-land — `audit post --task "
                  "<task>` (or `audit post --reaudit-after-close --task <task>` if the task is "
                  "already status:done — X-0040/T-9412), then re-run this land.\nIf the auditor "
                  "cannot RUN at all, do NOT force this land: escalate with `blocked-on-land "
                  "<task> <reason>` (worktree intact) — that escalation is the CORRECT outcome "
                  "(SPEC-0103 / SPEC-0121 default-under-uncertainty is STOP). There is deliberately "
                  "no flag that waives this: `--no-tests` skips TESTS, never the audit.",
                _land_audited_footprint_abort_detail(split))
    except Exception:                          # noqa: BLE001 — a predictor that raises must not abort
        return None

def _land_prequeue_known_broken_refusal(branch: str, main_wt: Path, *, _run_git_cap,
                                        EVENTS_PATH=None, _VERIFY_IMPLEMENTATION_GLOBS=None,
                                        _known_broken=None, _select=None, _git_rev=None, _land_known_broken_establishing_sha=None, _shadow_select=None) -> "tuple | None":
    """T-11469 — REFUSE, BEFORE THE QUEUE, a land whose verify would only rediscover a breakage main
    is ALREADY KNOWN to carry. Returns `(abort MESSAGE, abort DETAIL)`, or None to proceed — the
    two-part shape its sibling `_land_prequeue_currency_refusal` already returns (T-11799 widened it
    from a bare message; every fail-open path still returns exactly `None`). The family's FOURTH
    member beside `_land_prequeue_merge_refusal` (T-11218), `_land_prequeue_currency_refusal`
    (T-11391) and `_land_prequeue_uncatalogued_type_refusal` (T-11395) — same position, same
    fail-OPEN polarity, same existing abort path.

    THE CLAIM OF THIS CARD IS THE PLACEMENT, NOT THE SAVING. Today's land order is reservation ->
    verify slot -> repo lock (`_acquire_land_reservation`), so a known-broken check placed AFTER the
    reservation still refuses fast and still makes every other land QUEUE BEHIND IT. Measured on
    2026-08-23: a land carrying only YAML, with tests skipped entirely, waited 301s for a reservation
    another session held. Asked HERE — above the attempt loop — the land resolves in seconds and the
    queue never forms. That matters more than the minutes because queued lands must never overflow
    into FORCED ones: both forced paths are reachable (the conscious `--ack-repeated-abort` override,
    and the reservation park DEGRADATION where a waiter past ~37.4 minutes races a concurrent
    same-repo land — 23 recorded, 20 on healthy holders).

    ONE ORACLE, RE-DERIVED NOWHERE (the T-11216 rule). The record is `debt.open_known_broken` — the
    SAME fold T-11468 shipped and the session-start echo already reads (`bin/lib/cli.py`). Nothing
    about what establishes, clears or vacates a record is restated here; this function chooses only
    WHERE the question is asked and what the answer does. Its journal is MAIN's, because the fact is
    about main and is contributed by OTHER branches' lands.

    IT REFUSES; IT NEVER EXCUSES (the owner correction, 2026-08-23). An earlier draft of the plan
    recorded EXCLUDE — let the land through with the broken test excluded. That was inferred, not
    ruled, and the owner corrected it: letting lands through on a knowingly-broken main means main
    accumulates broken state and nobody is obliged to fix it. Nothing here waives, skips or retries
    anything.

    WHY IT CANNOT WEDGE THE REPOSITORY IT PROTECTS — the bound that makes REFUSE safe, and the one
    piece of reasoning this function adds rather than borrows. A record clears ONLY by evidence
    (SPEC-0181 rule 2: a later land observing the test pass on a fresh main), so a refusal firing on
    EVERY branch would forbid the very land that repairs main and the record could never clear. So
    the refusal is narrowed to branches whose diff PROVABLY cannot reach any broken test file, and
    the narrowing is judged by the EXISTING SPEC-0181 ladder `_shadow_select` — the same selector the
    verify itself runs, every unknown state of which resolves to the full suite and therefore, here,
    to PROCEED. A branch that could run the broken test (the repair, or anything touching the
    verifier surface) is admitted, pays its verify, and is exactly the land that produces the
    clearing evidence. This NARROWS the refusal; it weakens nothing.

    FAIL-OPEN, LIKE ITS THREE SIBLINGS. Only a PROVEN pair — a standing record AND a resolvable diff
    the ladder says cannot reach it — refuses. No record, no branch, no merge-base, an empty diff, a
    git that could not run, a fold or a selector that raised: every one of them proceeds and lets the
    verify be the authority. A false abort here is worse than a slow success.

    IT LEAVES A RECORD, AND THE RECORD COSTS NOTHING (T-11799). The refusal used to be invisible to
    every later reader: its abort row is written by `cmd_land` to the LANDING CHECKOUT's journal, and
    a branch's journal reaches MAIN only by LANDING — so a refused branch that is then discarded or
    parked takes the only record of its refusal with it (measured 2026-08-28: the whole journal
    footprint of work/red-main-guard-and-repair-path is three rows, none of them the refusal, and
    main's journal carries zero rows naming this refusal in its entire history). The DETAIL half of
    the return is what fixes that — `cmd_land` puts it on the EXISTING `land_completed` abort row and
    delivers a ts-pinned byte-identical copy to main through the EXISTING T-11241/T-11798 seam. It is
    composed from locals this function has ALREADY computed for the message, so the record is an
    APPEND and never a reservation: no extra git call, no verify slot, no batch membership, and the
    refusal stays above the attempt loop exactly where it was. REPORT-ONLY — it gates nothing, waives
    nothing and excludes nothing; the refusal still REFUSES and NEVER EXCUSES. And it is an ABORT
    RECORD, never a queue entry: whether a refused land should be retried, and by whom, is a separate
    question this shape deliberately does not answer.

    `_known_broken` / `_select` are INTERNAL test seams (the fold and the ladder, injected) — never
    env gates and never an external control surface.
    """
    try:
        from lib import debt as _debt_mod      # lazily — worktree.py is imported by every CLI call
        if not branch:
            return None
        events_path = Path(EVENTS_PATH) if EVENTS_PATH is not None else (main_wt / "events.jsonl")
        fold = _known_broken or (lambda: _debt_mod.open_known_broken(events_path, root=main_wt))
        record = fold() or {}
        broken = [r for r in (record.get("broken") or []) if isinstance(r, dict) and r.get("file")]
        if not broken:
            return None                        # main is not known broken → nothing to say
        base = _run_git_cap(["merge-base", "main", branch], main_wt)
        base_sha = (base.stdout or "").strip() if base.returncode == 0 else ""
        if not base_sha:
            return None                        # no baseline → cannot judge reach → the verify decides
        dif = _run_git_cap(["diff", "--name-only", base_sha, branch], main_wt)
        if dif.returncode != 0:
            return None
        diff_paths = [ln.strip() for ln in (dif.stdout or "").splitlines() if ln.strip()]
        if not diff_paths:
            return None                        # an empty diff is rung R2's fail-closed edge → proceed
        # THE REACH QUESTION, asked of the ladder rather than of a local rule. `test_files` is the
        # BROKEN set alone: `_shadow_select` answers "which of these could this diff break", and the
        # names it selects are the ones this branch might repair. A non-None reason is the ladder
        # refusing to narrow at all (verifier-surface touch, unresolvable diff, unknown mapping) —
        # that land runs everything, so it can reach the break and is not ours to refuse.
        # THE VERIFY-SURFACE GLOBS ARE PASSED IN, NEVER RESTATED HERE. Their single home is the
        # `_VERIFY_IMPLEMENTATION_GLOBS` constant beside the CLI's verify wiring, so this module
        # takes them from the caller (`_land_integrate`, which now forwards them) rather than
        # keeping a second copy that would drift. A caller that supplies none cannot be judged for
        # reach at all — the ladder's own R1 edge would answer `no-verify-globs` — so the probe
        # PROCEEDS, the same fail-open direction as every other unknown here. The wiring itself is
        # asserted by this card's test rather than assumed: an unwired glob set would make the
        # guard silently inert, which is the one failure a fail-open predictor cannot report.
        if not _VERIFY_IMPLEMENTATION_GLOBS:
            return None
        select = _select or _shadow_select
        broken_files = sorted({str(r["file"]) for r in broken})
        would_select, _omit, full_suite_reason = select(
            diff_paths, [str(main_wt / _LAND_CANDIDATE_TEST_SUBDIR / f) for f in broken_files],
            _VERIFY_IMPLEMENTATION_GLOBS)
        if full_suite_reason is not None or would_select:
            return None                        # this branch CAN reach the break → let it verify
        main_rev = _git_rev("main", main_wt, _run_git_cap=_run_git_cap) or "unresolvable"
        lines = []
        # T-11799 — THE RECORD THE ROW WILL CARRY, composed from the SAME locals the message below is
        # composed from and from NOTHING ELSE. That identity is the whole cheapness argument: not one
        # additional git call, fold or file read is made to build it, so recording the refusal costs
        # exactly what printing it already cost. `est` is resolved once and used twice.
        recorded = []
        for rec in sorted(broken, key=lambda r: (str(r.get("since") or ""), str(r.get("pair") or ""))):
            est = _land_known_broken_establishing_sha(str(rec.get("since") or ""), main_wt,
                                                      _run_git_cap=_run_git_cap)
            recorded.append({"pair": rec.get("pair") or rec.get("file"),
                             "file": rec.get("file"),
                             "since": rec.get("since"),
                             "established_by": rec.get("branch"),
                             # NEVER INVENTED (the T-0358 no-fabricated-values discipline): `None`
                             # says main's history does not reach the establishing instant, which is
                             # exactly what the message says in words on the same line.
                             "establishing_sha": est})
            lines.append(
                f"  - {rec.get('pair') or rec.get('file')}\n"
                f"    established {rec.get('since')} by {rec.get('branch') or 'an unnamed branch'}"
                f" (reproduced at the merge-base {rec.get('seen') or 1}x); establishing sha "
                + (est if est else "UNRESOLVED (main's history does not reach that instant — the "
                                  "establishing land ABORTED and recorded no sha of its own)"))
        return (("land: main is KNOWN BROKEN — refused without taking anything (worktree intact, "
                "main untouched).\nBROKEN ON MAIN (SPEC-0181 §Known-broken-on-main), each pair "
                "REPRODUCED at the merge-base by a land's own attribution probe, with no later "
                "evidence of it passing there:\n" + "\n".join(lines)
                + f"\nRefused BEFORE the land queue (SPEC-0184 / T-11469): no reservation taken, no "
                  f"verify slot, no batch membership, no suite run. Judged against main {main_rev} "
                  f"and branch {branch} at merge-base {base_sha}.\n"
                  "WHY THIS BRANCH: the SPEC-0181 coverage ladder maps none of its changed paths to "
                  "the broken test file(s), so its verify could only rediscover main's red at the "
                  "420-570s a full verify costs.\n"
                  "RECOVERY — and note WHICH case this assumes (a branch that CANNOT reach the "
                  "break): fix the named test on main and land THAT. A branch whose diff CAN reach "
                  "a broken test file is NOT refused here, so the repair path is never blocked, and "
                  "the record clears on that land's EVIDENCE — a later run observing the test pass "
                  "on a fresh main — never on elapsed time."),
                {"prequeue_known_broken": {"branch": branch, "pairs": recorded,
                                           "main": main_rev, "merge_base": base_sha}})
    except Exception:                          # noqa: BLE001 — a predictor that raises must not abort
        return None


def _land_prequeue_merge_refusal(branch: str, main_wt: Path, *, _run_git_cap,
                                 _DERIVED_MERGE_ARTIFACTS=None, _dedup_events=None,
                                 _probe=None, _anchor_signature_of_text=None, _git_rev=None, _land_merge_probe=None) -> "str | None":
    """T-11218 — REFUSE, BEFORE THE QUEUE, a land that provably cannot merge with the current main.
    Returns the abort MESSAGE, or None to proceed.

    THE MEASURED INCIDENT. task/T-11212 sat in the land queue 2026-08-17 04:35Z–05:46Z (197
    `waiting_for_land_reservation` rows), was pulled into 7 successive batches and evicted from
    every one, and on reaching the front aborted CORRECTLY on a non-union conflict with main. The
    system held the right, actionable answer the whole time and did not compute it until after the
    wait — because the conflict question is asked in-lock, AFTER the reservation, the verify slot
    and the repo lock. This asks the SAME question, from the SAME oracle, in milliseconds, first.
    SPEC-0184 rule 3's "an evicted member takes its own slot and verifies alone" is true but inert
    for this class: verifying alone fails for exactly the same reason.

    FAIL-OPEN — THE INVERSE POLARITY OF THE IN-LOCK CHECK, DELIBERATELY (AC5, confirmed by the
    consult). `_update_from_main` stays the AUTHORITY and stays fail-CLOSED; this is a cheap
    predictor of it. So a refusal is emitted ONLY on a PROVEN blocking set — the oracle's `detail`
    present AND its `unresolved` non-empty. Every other answer proceeds into the queue and lets the
    in-lock check decide: `clean`, `land-resolvable`, `unevaluable`, an unreadable ref, a git that
    could not run, a stream that would not parse, a classifier that raised, and any exception raised
    in here. A false abort is worse than a slow success; this never invents a refusal it could not
    prove.

    HONEST ABOUT ITS SCOPE (AC4). The message NAMES the main sha and the branch sha it was proved
    against, because the refusal is stale-current-state, not a weaker merge authority: a branch
    refused now may merge cleanly once main advances, and the operator can only know that if the
    refusal says what it is true RELATIVE TO. The message otherwise reproduces `_update_from_main`'s
    own text verbatim — same wording, same blocking-vs-auto-resolvable split — so ONE diagnosis
    reaches the operator whichever side answers, and `_emit_land_abort` (which journals the message
    as `abort_reason`) carries both shas into the row with no additive field and no new event type.

    MERGE DIRECTION IS IMMATERIAL HERE. The in-lock authority merges main INTO the branch; the
    oracle computes `merge-tree <main> <branch>`. This function consumes ONLY the `unresolved` SET,
    never a resolved payload, and every resolver's PROVABILITY is symmetric across the two content
    sides (derived → ours-resolvable either way; the journal → unioned either way; both keyed 3-way
    resolvers refuse a same-key divergence whichever side authored it). So orientation neither
    widens nor narrows the answer acted on.

    `_probe` is an INTERNAL test seam ONLY (the oracle, injected) — never an env gate or an external
    control surface.
    """
    try:
        probe = _probe if _probe is not None else _land_merge_probe
        main_rev = _git_rev("main", main_wt, _run_git_cap=_run_git_cap)
        branch_rev = _git_rev(branch, main_wt, _run_git_cap=_run_git_cap) if branch else None
        if not main_rev or not branch_rev:
            return None                        # nothing to prove against: the in-lock check decides
        # T-11291: the merged-tree signer reaches the REAL oracle only. An injected `_probe` (the
        # existing test seam) keeps its unchanged 3-arg contract — extending a seam must not break it.
        _extra = ({} if _probe is not None
                  else {"_anchor_signature_of_text": _anchor_signature_of_text})
        _outcome, _tree, detail = probe(main_rev, branch, main_wt, _run_git_cap=_run_git_cap,
                                        _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                                        _dedup_events=_dedup_events, **_extra)
        unresolved = (detail or {}).get("unresolved") or []
        if not unresolved:
            return None                        # not proven blocking → into the queue (fail-open)
        resolved = (detail or {}).get("resolved") or []
        extra = ""
        if resolved:
            extra = ("\n(auto-resolvable, NOT blocking — they no longer void the others: "
                     + ", ".join(sorted(resolved)) + ")")
        return ("land: merge from main has non-union conflicts (worktree intact, main untouched):\n"
                + "\n".join(unresolved) + extra
                + f"\nRefused BEFORE the land queue (SPEC-0184 / T-11218): no reservation taken, no "
                  f"verify slot, no batch membership. Proved against main {main_rev} and branch "
                  f"{branch} {branch_rev} — a later main may merge cleanly, so resolve the conflict "
                  f"(or re-run after `worktree sync`) and land again.")
    except Exception:                          # noqa: BLE001 — a predictor that raises must not abort
        return None

def _land_prequeue_uncatalogued_type_refusal(branch: str, main_wt: Path, *, _run_git_cap,
                                             _git_bytes=None, _classify=None,
                                             _findings=None, _rev_journal_types=None) -> "str | None":
    """T-11395 — REFUSE, BEFORE THE QUEUE, a land whose OWN diff introduces an event type the SPEC-0161
    catalog does not name. Returns the abort MESSAGE, or None to proceed. Third member of the pre-queue
    family beside `_land_prequeue_merge_refusal` (T-11218, the merge question) — same position, same
    fail-OPEN polarity, same existing abort path.

    THE MEASURED INCIDENT. `tests/test_event_catalog_completeness.py` AC1/AC1' runs INSIDE the verify,
    i.e. AFTER admission, and in a BATCH the diff it judges is the COMBINED candidate. So ONE member
    carrying an unnamed type fails the WHOLE batch: on 2026-08-21 batch bat-c732b5fabfe1 (14:56:55Z)
    died on `test_event_catalog_completeness.py FAILED (2)` and requeued BOTH members, the innocent one
    having paid a full verify for a defect that was not its own. The same guard family produced the
    04:31-04:54 freeze the same day, where one uncatalogued type refused four branches that each spent
    430-560s discovering it independently. This asks the SAME question, from the SAME oracle, per
    BRANCH, in the milliseconds before anything is reserved.

    WHAT IT MEASURABLY PREVENTS is the innocent peer's wasted verify. That the batch as a whole
    survives more often is a HYPOTHESIS, not a measurement, and this docstring will not claim it.

    ONE ORACLE (the T-11216 rule, applied to a second question). The verdict is
    `graph.classify_event_types` + `graph.uncatalogued_type_findings` — the very functions the
    in-verify gate calls — over inputs materialized by `graph.event_catalog_tree_inputs`, the very
    walk that gate's baseline uses. Nothing about the predicate, or about what AC1' means, is restated
    here; this function only chooses the QUANTIFIER's two sides and the polarity of the answer.

    WHY THE BRANCH-ALONE VIEW CANNOT OVER-REFUSE, BY CONSTRUCTION (not by assertion after the fact).
    The candidate the verify judges is this branch MERGED with main, so two deliberate narrowings keep
    this side of the question strictly weaker than that one:
      * the CURRENT types are read only from the rows THIS BRANCH ADDED vs the merge-base (`git diff
        -U0`), never from main's later rows — a type main grew after the merge-base is not this
        branch's to answer for, and the batch's own combined-diff verdict is not predicted here;
      * the CATALOG both sides are classified against is the UNION of the branch tree and `main`
        (corpus concatenated, code blobs merged), a SUPERSET of the merged candidate's catalog — so a
        spec or emitter that catalogs the type on EITHER side is seen, and the union can only ever
        under-refuse.
    Both err in the same direction: fewer refusals than the verify itself would produce.

    FAIL-OPEN, THE T-11218 POLARITY. The in-verify gate stays the AUTHORITY and stays fail-CLOSED; this
    is a cheap predictor of it. A refusal is emitted ONLY on a PROVEN introduced set. An unresolvable
    merge-base, a git that could not run, an unreadable or unparseable journal, an empty added-row set,
    a classifier that raised, any exception in here — every one of them proceeds into the queue and
    lets the verify decide. A false abort is worse than a slow success.

    COST. One `git merge-base`, one journal `git diff -U0` (measured in this repo: 7ms at zero drift,
    1.8s at 30 commits of it), and — only when the branch actually added rows carrying an
    otherwise-uncatalogued type, which is the rare case — the tree materializations. No merge, no
    verify, no reservation, no slot.

    THE UNCOMMITTED MAIN-CHECKOUT RESIDUE IS NOT THIS BRANCH'S (T-11491), and that narrowing lives at
    the classification, not at the gate: types carried only by UNCOMMITTED rows in the SHARED main
    checkout's journal are folded into the BASE side via `graph.main_checkout_residue_types`, so they
    read `inherited` — the same disposition SPEC-0161 §THE NAMED RESIDUE already gives the COMMITTED
    half of the identical case. Without it, land's own fold of main's dirty journal onto the landing
    branch (the D-0049 fold-promise) makes another session's uncommitted evidence row look
    diff-introduced, and it refused EVERY land in this repo on 2026-08-22/23. The exemption is fenced
    by that function's two attribution guards — ROW IDENTITY against main's uncommitted rows and NAME
    ABSENCE from this branch's non-journal diff — so the diff-scoped quantifier itself is untouched.

    `_git_bytes` / `_classify` / `_findings` are INTERNAL test seams only — never env gates or external
    control surfaces."""
    try:
        classify = _classify or graph_mod.classify_event_types
        findings = _findings or graph_mod.uncatalogued_type_findings
        if not branch:
            return None
        # A PREDICTOR MUST NOT FIRE WHERE THE THING IT PREDICTS DOES NOT EXIST. This probe's whole
        # claim is "the verify would fail this branch on AC1/AC1', so let us say so first". A
        # checkout that does not CARRY that gate would never be asked the question at all, so
        # refusing it invents a verdict rather than predicting one. Measured, not hypothesised: the
        # hermetic land fixtures in `test_land.py` copy a MINIATURE `specs/`+`bin/` corpus that
        # legitimately homes almost nothing, and against it every ordinary type (`session_started`,
        # `cli_invoked`) reads as uncatalogued — the second false-refusal shape this probe's own
        # suite caught. Presence is read on the BRANCH tree, i.e. what would actually be verified.
        gate = _run_git_cap(["cat-file", "-e",
                             f"{branch}:tests/test_event_catalog_completeness.py"], main_wt)
        if gate.returncode != 0:
            return None
        base = _run_git_cap(["merge-base", "main", branch], main_wt)
        base_sha = (base.stdout or "").strip() if base.returncode == 0 else ""
        if not base_sha:
            return None                        # no baseline to attribute against → the verify decides

        # The rows THIS BRANCH ADDED. `-U0` so only added lines appear; each is json-parsed, never
        # pattern-matched, so a line-format change cannot silently widen or narrow the set.
        dif = _run_git_cap(["diff", "--no-color", "-U0", base_sha, branch, "--", "events.jsonl"],
                           main_wt)
        if dif.returncode != 0:
            return None
        branch_added_rows = graph_mod.journal_diff_added_rows(dif.stdout or "")
        added: set = set(branch_added_rows)
        if not added:
            return None                        # nothing introduced → no work at all (rule-1 shape)

        def _real_git_bytes(args, stdin=None):
            import subprocess
            proc = subprocess.run(["git", "-C", str(main_wt), *args], input=stdin,
                                  capture_output=True, check=False)
            return proc.returncode, proc.stdout

        gitb = _git_bytes or _real_git_bytes

        def _tree(rev):
            return graph_mod.event_catalog_tree_inputs(rev, git_bytes=gitb)

        b_corpus, b_code = _tree(branch)
        m_corpus, m_code = _tree("main")
        cur_corpus = m_corpus + b_corpus                       # the UNION catalog (see docstring)
        cur_code = {**m_code, **b_code}
        if not cur_corpus and not cur_code:
            # NOTHING WAS READ, WHICH IS NOT THE SAME AS "NOTHING CATALOGUES IT" — and on a fail-open
            # predictor the difference is the whole verdict. `event_catalog_tree_inputs` returns
            # ("", {}) both when git could not run and when the checkout genuinely has no `specs/`
            # or `bin/`; against an empty catalog EVERY type classifies as uncatalogued, so the probe
            # would refuse every branch it could not read. Measured, not hypothesised: the land
            # fixtures in `test_land.py` / `test_t11192_batch_formation.py` are exactly such
            # checkouts, and the first run of this probe refused them. An unreadable catalog proves
            # nothing; the in-verify gate, which is fail-CLOSED, keeps the strict side.
            return None
        cur_with_emitter, cur_residual = classify(added, cur_corpus, cur_code)
        candidates = set(cur_with_emitter) | set(cur_residual)
        if not candidates:
            return None                        # every added type is catalogued → into the queue

        # The BASE side, over the SAME candidates: a type already uncatalogued at the merge-base is
        # `inherited` — not this branch's to clear — exactly as the in-verify gate reads it.
        base_corpus, base_code = _tree(base_sha)
        if not base_corpus and not base_code:
            return None                        # the base side could not be read → cannot attribute
        base_types = _rev_journal_types(base_sha, candidates, main_wt, _run_git_cap=_run_git_cap)
        base_with_emitter, base_residual = classify(base_types, base_corpus, base_code)

        # T-11491 — THE UNCOMMITTED HALF OF SPEC-0161's NAMED RESIDUE, folded into the BASE side so
        # it reads `inherited` exactly like the COMMITTED half the spec already exempts. `land` folds
        # main's dirty journal onto the landing branch and commits it (the D-0049 fold-promise), so a
        # row that reached the SHARED MAIN CHECKOUT with no worktree and no land arrives in THIS
        # branch's diff-vs-merge-base and, without this, reads as diff-INTRODUCED — which is how three
        # uncommitted `probe_evidence_note` rows refused every land in the repo on 2026-08-22/23. The
        # exemption is fenced by the TWO attribution guards inside `main_checkout_residue_types`:
        # every added row of the type on this branch must be one of main's uncommitted rows VERBATIM
        # (so a row the branch emitted itself is never exempted), and the branch's OWN diff with the
        # journal EXCLUDED must not name the type anywhere (so a branch bringing the EMITTER in is
        # never exempted). A branch that genuinely brings the type in still fails and still
        # self-clears on its own branch — T-11379's quantifier is untouched.
        # Both reads are FAIL-OPEN-COMPATIBLE in the strict direction: a git that cannot run yields no
        # residue and no guard text, i.e. exactly today's behaviour.
        main_dirty_diff = _run_git_cap(["diff", "--no-color", "-U0", "HEAD", "--", "events.jsonl"],
                                      main_wt)
        main_uncommitted_rows = (graph_mod.journal_diff_added_rows(main_dirty_diff.stdout or "")
                                 if main_dirty_diff.returncode == 0 else {})   # {} exempts nothing
        branch_source_diff = _run_git_cap(["diff", "--no-color", base_sha, branch, "--",
                                           ".", ":(exclude)events.jsonl"], main_wt)
        residue = graph_mod.main_checkout_residue_types(
            candidates, main_uncommitted_rows=main_uncommitted_rows,
            branch_added_rows=branch_added_rows,
            # None, NOT "", when the diff could not be read: "" is a genuinely EMPTY diff and would
            # silently disable the name-absence guard, exempting a branch that introduces an emitter
            # on a git failure (T-11491 audit-post). None exempts nothing.
            branch_diff_text=(branch_source_diff.stdout or ""
                              if branch_source_diff.returncode == 0 else None))

        emitter_intro = findings(set(base_with_emitter) | set(residue), cur_with_emitter)["introduced"]
        residual_intro = findings(set(base_residual) | set(residue), cur_residual)["introduced"]
        if not emitter_intro and not residual_intro:
            return None

        arms = []
        if emitter_intro:
            arms.append("AC1 (an emitter in `bin/` but no `specs/` home): "
                        + ", ".join(emitter_intro))
        if residual_intro:
            arms.append("AC1' (no emitter, and not on SPEC-0161's deferral list): "
                        + ", ".join(residual_intro))
        return ("land: this branch's diff introduces an event type the SPEC-0161 catalog does not "
                "name (worktree intact, main untouched):\n"
                + "\n".join(arms)
                + f"\nRefused BEFORE the land queue (SPEC-0184 / T-11395): no reservation taken, no "
                  f"verify slot, no batch membership — so no PEER pays a verify for it. Judged on "
                  f"THIS branch's added journal rows against merge-base {base_sha}, the same "
                  f"AC1/AC1' question `tests/test_event_catalog_completeness.py` asks inside the "
                  f"verify. Home the type in a spec (or name it on SPEC-0161's deferral list) and "
                  f"land again.")
    except Exception:                          # noqa: BLE001 — a predictor that raises must not abort
        return None

def _land_probe_advance(accum: str, tree: str, branch: str, main_wt: "Path | None",
                        *, _run_git_cap, _git_rev=None) -> "str | None":
    """The synthetic merge commit the NEXT candidate is tested against — UNREFERENCED by design.

    ONE DEFINITION, TWO CALL SITES (T-11309 lifted it out of `_land_merge_members_in_queue_order`,
    where it was a closure): SPEC-0184 rule 3's eviction walk and rule 1's FORMATION admitter. A
    closure cannot be called from a second site, and the alternative — a second accumulator feed —
    is precisely the defect the external-auditor consult killed on the sibling seam
    (`land-conflict-check-before-queue`, 2026-08-17): two feeds that can disagree about what "the
    peers merged so far" IS would let formation and eviction answer the same question differently.
    One question, one authority (CHARTER §Principle 5).

    NOTHING IS CHECKED OUT AND NO REF MOVES. `commit-tree` writes an object that nothing references
    and nothing reaches; `main`, the worktrees and the candidate branches are all untouched, which is
    what makes this safe to run before anyone has agreed to land.

    RETURNS None ON EVERY FAILURE — an unreadable branch, a git that could not run, a non-zero exit,
    or output that is not a sha. The two callers read that None with OPPOSITE polarity, which is
    correct and deliberate: the eviction walk treats a dead accumulator as fail-CLOSED, formation as
    fail-OPEN (see `_land_compat_admitter`). This helper takes no position on that; it reports only
    whether it could compute the commit."""
    br = _git_rev(branch, main_wt, _run_git_cap=_run_git_cap)
    if not br:
        return None
    try:
        r = _run_git_cap(["commit-tree", tree, "-p", accum, "-p", br,
                          "-m", "land batch candidate (unreferenced)"], main_wt)
    except Exception:                          # noqa: BLE001
        return None
    out = (r.stdout or "").strip()
    return out if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", out or "") else None

def _land_queue_at_slot_free(events_path: "Path | None", self_branch: "str | None", *,
                             now: "float | None" = None,
                             window_s: int = _LAND_QUEUE_FRESHNESS_SEC,
                             excluded: "list | None" = None,
                             seen: "list | None" = None,
                             _rows: "list | None" = None,
                             _terminal_rows: "list | None" = None,
                             _branch_exists=None,
                             _terminal_epochs=None, _LAND_QUEUE_WAIT_TYPES=None, _land_queue_row_epoch=None, _land_queue_terminal_epochs=None, _land_queue_wait_start=None) -> "list[str]":
    """SPEC-0184 rule 1 — the branches QUEUED at the moment the land slot frees, in queue order.

    Read off the existing journal rows: a land blocked on the SPEC-0132 admission slot or on the
    T-10549 land reservation beats `waiting_for_*` rows carrying its branch. Rows older than
    `window_s` are not "queued now" and are dropped; the surviving branches are deduped and then
    ORDERED BY WAIT START, OLDEST FIRST. `self_branch` — the land holding the slot — is excluded; the
    caller puts it at the head.

    T-11681 — THE ORDER IS AGE, AND IT USED TO BE FIRST-SEEN-IN-TAIL. This function's contract said
    first-seen order "IS queue order (whoever has been waiting longest is ahead)", and TWO consumers
    rest their own correctness on that sentence: `_land_form_batch` ("QUEUE ORDER STILL SETS
    PRIORITY ... waiting time — not mergeability — decides who is first") and `_land_yield_target`
    ("The FIRST queued branch (queue order IS wait order)"). The sentence was FALSE. Every live waiter
    re-emits a heartbeat every ~20s, so within a 90s window first-seen order is heartbeat-emit PHASE
    and is uncorrelated with accumulated age.

    FALSIFIED BY REPLAY, not by argument. Running this reader over the real wait rows at
    2026-08-26T11:18:20Z, first-seen order ranked `work/fix-batch-join-key-on-unaccounted` SECOND of
    five at an age of 307s — the YOUNGEST of the five — ahead of task/T-11652 (1161s), task/T-11582
    (478s) and work/settle-p8-adoption-probes (413s). In the same shift task/T-11525 waited from
    10:44:08Z while TWELVE branches reached `land_completed`.

    AN UNDATABLE AGE KEEPS ITS FIRST-SEEN POSITION rather than being ranked. A branch whose
    `_land_queue_wait_start` cannot be computed is sorted as if its age were its first-seen index, so
    it neither jumps the oldest waiter nor is buried behind every dated one — an age nothing can
    compute must not silently become the best or the worst rank
    (`lessons/a-wait-loop-gated-on-a-signal-that-cannot-flip-is-a-timer.md`). The sort is STABLE, so
    equal ages keep first-seen order and a repo where nothing can be dated is byte-identical to today.

    WHAT THIS DOES NOT DO, stated so the bound is not over-read: queue order does not GRANT the flock.
    The verify-admission slot and the land reservation are non-blocking flock races that consult no
    age at all. What this order governs is batch MEMBERSHIP priority and the rule-9 YIELD target —
    which is how a queued branch actually lands. This makes those two age-true; it does not make the
    flock race itself FIFO.

    NEW ARRIVALS ARE NOT STARVED BY THE CURE — oldest-first is FIFO, and FIFO's whole property is
    that a branch's rank is NON-INCREASING: branches only leave the set ahead of it, never join it,
    because joining later means a younger age. So a branch that arrives with `k` waiters ahead is
    admitted within `k` rounds. That is a BOUND, and it is one the pre-change lottery did not have at
    any value of `k`.

    T-11219 — A FRESH HEARTBEAT IS NOT A LIVENESS PROBE, so a branch is admitted only while it is
    STILL waiting. A heartbeat keeps matching for the whole `window_s` after its land finished,
    aborted or died, and a read that stops at freshness picks that ghost as a peer: it consumes one of
    `BATCH_MAX`'s slots (shrinking the very amortisation this design exists to produce) and, if the
    batch goes red, `_land_dissolve_batch` marks a branch that already landed batch-INELIGIBLE for a
    round it was never part of. So each branch's LATEST terminal row (`_land_queue_terminal_epochs`)
    is compared against its LATEST in-window wait row, and it is admitted only when the wait evidence
    is STRICTLY NEWER.

    ORDERING, NOT PRESENCE, IS THE TEST — and that distinction is the whole reason this is not a
    one-line "has it a terminal row?" check. A member requeued after a red batch gets a terminal
    `land_member_verdict` and then goes straight back to waiting; on a presence test it would be
    excluded forever, silently converting rule 4's one-round penalty into a permanent one. Comparing
    against the newest wait row re-admits it the moment it beats again, which is exactly right.

    T-11263 — THE ORDERING TEST IS NARROWED FOR ONE VERDICT, `landed`, AND FOR NO OTHER. The test
    above assumes a wait row that POSTDATES a terminal row is a NEW wait. For a `landed` member that
    assumption is FALSE: the member's own land is parked in `_await_land_reservation`, a flock poll
    that reads the lock and the clock and NOTHING ELSE — it never opens the journal, so no batch
    verdict can reach it and it keeps beating after its work is already in main. Traced end to end
    on task/T-11234 (2026-08-18): landed at 04:06:13Z, still beating 22 minutes later, announced as
    a member into three later formations and delivering a verdict in NONE of them.

    So for a `landed` verdict — and ONLY for it — the wait evidence must be a NEW WAIT rather than a
    newer heartbeat of the same parked one: `wait_start = row_ts - waited_s` must be at or after the
    verdict. `requeued-after-red-batch`, `evicted-for-conflict`, `dropped-dead-member` and every
    `land_completed` keep the untouched verdict-blind path, which is what keeps rule 4's one-round
    penalty ONE round. THE RE-LAND PATH STAYS OPEN, which is the other half of why this is a
    narrowing and not an exclusion: a branch that genuinely re-lands with new commits parks a NEW
    land, `waited_s` restarts at 0, and its wait start lands AFTER the verdict — task/T-11234,
    task/T-11191 and task/T-11196 all did exactly this and all stay admitted. A PERMANENT exclusion
    after a `landed` verdict would be a regression, and this is not one.

    FAIL-CLOSED ON EVERY UNDECIDABLE CASE, in the direction the cost asymmetry sets: a missed batch
    member costs ONE unamortised pass, while a phantom member wastes a slot and can draw a wrong
    ineligibility. A tie (`terminal >= last wait`) EXCLUDES; an undatable terminal row EXCLUDES; an
    unreadable terminal journal excludes EVERYONE, which lands on the same empty queue this function
    already fails open to, so no second fail direction is introduced.

    `excluded`, when given, is an out-SINK: one `{"branch", "reason"}` dict is appended per exclusion.
    It is a sink rather than a second return value so that every existing caller stays byte-identical,
    and it exists because an exclusion nobody can see is indistinguishable from a queue that was
    simply empty. Its reader journals it onto `land_batch_formed`, where a row exists to carry it.

    `seen`, when given, is a second out-SINK carrying EVERY branch this read ENCOUNTERED — admitted or
    dropped — the fresh ones in queue order, then the history-only ones. It is not a duplicate of
    `excluded`: `excluded` says why a branch did
    not make the list, `seen` says the list of branches an accounting must COVER, and only the second
    can catch a branch that goes missing AFTER this function returned it. T-11312 (measured
    2026-08-19): at 10:55:02Z a formation row carried nine exclusions and one member, and task/T-11285
    — waiting continuously across that instant, admitted by the test below — was in NEITHER list. An
    exclusion sink cannot detect that, because the branch never reached it; only the enumerated set can.
    Populated ABOVE every return that follows the row loop, so all of them report the same set; the two
    pre-read returns (no path, unreadable journal) leave it empty, which is the honest answer for a
    read that saw nothing.

    T-11794 — A BRANCH THAT NO LONGER RESOLVES IS NOT A CANDIDATE AT ALL, and that is a different
    question from row age. `_branch_exists`, when injected, answers "does this branch ref still
    resolve?" for every branch this read encountered; a branch it answers False for is removed from
    the returned list AND from BOTH sinks, because a candidate that cannot exist is not one an
    accounting must cover. Measured (2026-08-28): `work/retire-the-census-differential-once-it-lands`
    was discarded by a governed `worktree park --work` at 07:49Z — worktree removed, branch deleted —
    and was still enumerated as an excluded candidate at 08:03:11Z, three formations later.

    THE DIFFERENTIAL IS EXISTENCE, NOT AGE, and it is the whole point. A stale row naming a branch
    that STILL EXISTS is a session whose holder died, and it must go on being reported as
    `stale-wait-row` — that is the signal by which an abandoned land is noticed at all. Before this
    card the two cases were reported in the SAME words, so a correct teardown and an abandonment were
    indistinguishable in the formation record; after it, the first is absent and the second is named.
    Dropping stale rows generally would have quieted the list by destroying that signal.

    THREE-VALUED, FAILING OPEN TOWARD KEEPING THE ROW. False = provably gone (drop). True = exists
    (unchanged). None — no resolver injected, git unreachable, or the call raised — is UNKNOWN and
    keeps the branch exactly as today. An over-reported ghost costs readability; a wrongly-dropped
    row costs the abandonment signal, so the cost asymmetry sets the fail direction.

    T-11235 — THE SINK IS TOTAL OVER WHAT THIS READ SAW, not just over its liveness verdicts. Every
    branch that appeared in the rows and did not reach the returned list leaves a named reason:
    the liveness drops above, plus `stale-wait-row` / `clock-skewed-wait-row` / `undatable-wait-row`
    for a heartbeat that is not evidence of NOW. Partial was the defect: with the freshness drop
    silent, a queue of nothing but history was byte-identical to a queue of nothing at all, and two
    2026-08-17 solo lands were unclassifiable for exactly that reason (the plan's first real-window
    reading). A branch rescued by a later fresh row is NOT reported — the sink never contradicts the
    member list this function returns.

    NOTHING WAITS TO FILL A BATCH (rule 1). This is a snapshot of who is already there, so a quiet
    repo reads an empty queue and forms a batch of one — byte-identical to the pre-spec path, with no
    flag and no second code path.

    FAIL-OPEN TO `[]`, always. An unreadable journal, an unparseable line, a missing path: every one
    of them yields an EMPTY queue, i.e. a batch of one. That direction is the safe one — a wrong
    batch would verify a combination nobody asked for, while a missed batch merely costs a pass.
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return []
        try:
            p = Path(events_path)
            if not p.exists():
                return []
            # The BOUNDED tail read (T-10897 `journal.tail_scan_events`) — the shared journal reader,
            # not a second journal path: the queue is a NOW question, so only the journal's END can
            # answer it, and a whole-file read of a 100MB+ journal on every land is not affordable.
            # The token is the superset prescan; the parsed type check below decides membership.
            rows = journal_mod.tail_scan_events(p, "waiting_for_",
                                                max_bytes=_LAND_QUEUE_TAIL_BYTES)
        except Exception:                      # noqa: BLE001 — fail-open: no queue, batch of one
            return []
    now = time.time() if now is None else now
    order: "list[str]" = []                    # first-seen = queue order; NOT this card's to redefine
    last_wait: "dict[str, float]" = {}         # branch -> its NEWEST in-window wait row
    wait_start: "dict[str, float | None]" = {}  # T-11263 — when THAT row's wait began (None: can't say)
    _stale: "dict[str, str]" = {}              # T-11235 — branch -> why its wait row was not "now"
    for ev in rows:
        if not isinstance(ev, dict) or ev.get("type") not in _LAND_QUEUE_WAIT_TYPES:
            continue
        br = (ev.get("data") or {}).get("branch") if isinstance(ev.get("data"), dict) else None
        br = str(br).strip() if br else ""
        if not br or br == (self_branch or ""):
            continue
        ts = _land_queue_row_epoch(ev.get("ts"))
        if ts is None or (now - ts) > window_s or (ts - now) > window_s:
            # T-11235 — SINK IT rather than dropping it silently. This is the OTHER drop class, and
            # until now it recorded nothing at ANY batch size, which left the sink partial: a reader
            # could not tell "no branch was ever queued" from "a branch was seen and judged not
            # current". The admitted set is UNCHANGED — this appends beside the same `continue`,
            # never to `order`. Recorded ONCE per branch (first-seen), because a branch with fifty
            # stale heartbeats is one excluded candidate, not fifty. Held in a dict and drained
            # AFTER the loop rather than appended here, because a branch whose stale row is read
            # before its fresh one is ADMITTED — reporting it as excluded would contradict the very
            # member list this function returns.
            _stale.setdefault(br, ("undatable-wait-row" if ts is None
                                   else "clock-skewed-wait-row" if (ts - now) > window_s
                                   else "stale-wait-row"))
            continue                           # stale, or a clock-skewed future row: not queued NOW
        if br not in last_wait:
            order.append(br)
            last_wait[br] = ts
            wait_start[br] = _land_queue_wait_start(ev, ts)
        else:
            # The NEWEST wait evidence, which is what the terminal row is ordered against. The
            # first-seen position above is untouched — freshness and queue position are different
            # questions and this card only answers the first.
            if ts >= last_wait[br]:
                # T-11263 — the wait START is read off THE SAME row that supplies the newest wait
                # evidence, so the two never disagree about which heartbeat is being judged.
                wait_start[br] = _land_queue_wait_start(ev, ts)
            last_wait[br] = max(last_wait[br], ts)
    # T-11794 — the EXISTENCE fold, applied ONCE per encountered branch and ABOVE every sink and
    # every return below, so the returned list, `excluded` and `seen` all describe the same set.
    # Placed after the row loop rather than inside it because a branch appears on many rows and the
    # ref resolves the same for all of them — one `rev-parse` per candidate, not one per heartbeat.
    # It covers `order` as well as `_stale`: a branch deleted seconds after its last heartbeat still
    # carries an IN-WINDOW row, so filtering only the stale drain would leave exactly that branch
    # enumerated (audit-pre pass 1).
    # EVERY encountered branch, de-duplicated in first-seen order: the ones with a fresh row
    # (`order`) and the ones only history spoke for (`_stale`). Spelled as one explicit union
    # rather than a filtered comprehension because the set it must cover is the whole point —
    # a stale-ONLY branch is precisely the measured case (audit-post pass 1 read the earlier
    # spelling as excluding it).
    _encountered = list(order) + [b for b in _stale if b not in order]
    if _branch_exists is not None:
        for _br in _encountered:
            try:
                _ex = _branch_exists(_br)
            except Exception:                  # noqa: BLE001 — an unanswerable ref is UNKNOWN, not gone
                _ex = None
            if _ex is False:                   # PROVABLY gone; None (unknown) keeps today's behaviour
                _stale.pop(_br, None)
                if _br in last_wait:
                    order = [b for b in order if b != _br]
                    last_wait.pop(_br, None)
                    wait_start.pop(_br, None)
    # T-11235 — drain the stale sink for branches NO fresh row rescued. Drained here, ABOVE the
    # empty-queue return, because the all-candidates-stale case is precisely the one that used to
    # read as an empty queue: this is what makes "nobody was there" and "everybody there was
    # history" different answers instead of the same silence.
    if excluded is not None:
        excluded.extend({"branch": b, "reason": r} for b, r in _stale.items() if b not in last_wait)
    # T-11312 — the ENUMERATED set, published before any return below it. `order` is the branches with
    # a fresh row (first-seen = queue order) and `_stale` the ones only history spoke for; their union
    # in first-seen order is what this read SAW, which is what a downstream accounting must cover.
    if seen is not None:
        seen.extend(order)
        seen.extend(b for b in _stale if b not in last_wait)
    if not order:
        return []
    # T-11681 — RANK BY AGE. Applied to `order` HERE, above the liveness fold, so the admitted list
    # and the `seen` sink both describe the same set as before and only its ORDER changes.
    #
    # PERMUTE THE DATED ENTRIES WITHIN THE SLOTS THEY ALREADY OCCUPY. An UNDATABLE branch holds its
    # ABSOLUTE first-seen index and is not moved at all; the dated branches are re-dealt, oldest
    # first, into the indices the dated set collectively held. That is the only shape in which
    # "an undatable row keeps its position" is literally true.
    #
    # A COMPARATOR CANNOT EXPRESS THIS, which is why the sort is a re-deal and not a sort key
    # (audit-post consult, 2026-08-27 — a real defect in this function's first form, named with its
    # input). Ranking an undatable branch by "how many dated branches preceded it" reads correctly
    # at the FRONT of a queue and is wrong in the MIDDLE: for `[young-dated, undatable, old-dated]`
    # it yields `[old, young, undatable]`, silently demoting the undatable row one place — the exact
    # promise this comment makes, broken. Undatability is not an age, so it cannot be ordered
    # AGAINST ages at all (`lessons/a-wait-loop-gated-on-a-signal-that-cannot-flip-is-a-timer.md`);
    # it can only be held still while the ages move around it.
    #
    # Ties among dated branches keep first-seen order (the sort is stable on `_pos`), and a queue in
    # which nothing can be dated is returned untouched.
    _pos = {b: i for i, b in enumerate(order)}
    _slots = [i for i, b in enumerate(order) if wait_start.get(b) is not None]
    if _slots:
        _by_age = sorted((order[i] for i in _slots), key=lambda b: (wait_start[b], _pos[b]))
        order = list(order)
        for _slot, _br in zip(_slots, _by_age):
            order[_slot] = _br
    # T-11219 — the liveness half. `_rows` (the hermetic-caller seam) is the caller's whole journal
    # slice and serves BOTH folds unless `_terminal_rows` overrides it. In PRODUCTION `_rows` is None
    # and the two reads are separate by necessity: the `waiting_` prescan is a superset that
    # structurally cannot contain a `land_completed` line.
    _tr = _terminal_rows if _terminal_rows is not None else _rows
    _fold = _terminal_epochs if _terminal_epochs is not None else _land_queue_terminal_epochs
    terminal = _fold(events_path, _rows=_tr)
    if terminal is None:
        # Unanswerable for every branch → admit none. This is the SAME empty queue (a batch of one)
        # the unreadable-journal path above already yields, so the function keeps ONE fail shape.
        # REACHABLE, not defensive decoration: the wait read and this one are two separate opens of a
        # journal that concurrent lands are appending to and that rotation can move between them, so
        # the first can succeed and the second fail. `_terminal_epochs` is the injection seam that
        # lets a test drive exactly that (the same seam shape `_engagement` / `_pid_alive` use) —
        # a branch nothing can flip is a branch nobody can trust
        # (lessons/a-wait-loop-gated-on-a-signal-that-cannot-flip-is-a-timer.md).
        if excluded is not None:
            excluded.extend({"branch": b, "reason": "liveness-unreadable"} for b in order)
        return []
    out: "list[str]" = []
    for br in order:
        ent = terminal.get(br)
        t, verdict = (None, None) if ent is None else ent
        if t is None or t < last_wait[br]:
            # T-11263 — the ONE verdict the ordering test cannot decide on its own. Everything else
            # falls straight through to the untouched T-11219 admission above.
            if t is not None and verdict == "landed":
                ws = wait_start.get(br)
                if ws is None:
                    if excluded is not None:
                        excluded.append({"branch": br,
                                         "reason": _LAND_PHANTOM_UNDATABLE_REASON})
                    continue                   # a wait we cannot date is not a NEW wait: fail closed
                if ws < t:
                    if excluded is not None:
                        excluded.append({"branch": br, "reason": _LAND_PHANTOM_LANDED_REASON})
                    continue                   # the SAME land, still parked after its own verdict
            out.append(br)                     # never stopped, or beat again after it did
            continue
        if excluded is not None:
            excluded.append({"branch": br,
                             "reason": ("terminal-row-undatable" if t == float("inf")
                                        else "stopped-waiting")})
    return out

def _land_queue_member_facts(events_path: "Path | None", *, now=None,
                             window_s: float = _LAND_QUEUE_FRESHNESS_SEC,
                             _rows: "list | None" = None, _LAND_QUEUE_WAIT_TYPES=None, _land_queue_row_epoch=None) -> "dict[str, dict]":
    """T-11278 — the RAW FACTS a queued land publishes about itself. Returns
    `{branch: {"attempt": int|None, "no_tests": bool, "pid": int|None}}` over the SAME in-window wait
    rows the queue read already scans.

    T-11878 — `pid` IS SUCH A RAW FACT, and it is read HERE rather than by a second fold because this
    function already parses the very row that carries it. It is the queued land PROCESS's own id, the
    one thing that says whether anybody is still alive to come for a handover; `_land_write_yield_offer`
    stamps it into the yield offer so `_land_yield_offer_blocks` can answer the addressee-LAND-liveness
    question with one `os.kill(pid, 0)` instead of a journal read on the 0.1s poll tick (the cost class
    `_land_addressee_gone` and SPEC-0184 rule 9 both refuse there). A missing, non-integer or
    non-positive `pid` yields `None` — UNKNOWN, never a guess, exactly as `attempt` below.

    WHY THESE ARE RAW FACTS AND NOT A VERDICT. The emitting land is the only party that knows its own
    attempt number and its own `--no-tests` switch; it is NOT the party that knows the batch context
    those facts are judged in. So it publishes the facts and `_land_member_would_run_suite` (below)
    draws the conclusion — the same split `rebaselining` already uses, and the reason there is no
    second classifier here.

    LAST WRITE WINS by POSITION over the in-window rows, exactly as `_land_rebaselining_branches`:
    the journal is append-only, so the newest row states the CURRENT attempt's intent, and a later
    flagless row therefore CLEARS an earlier flagged one.

    ABSENT IS NOT ZERO. A branch with no readable row, or a row predating this change, yields
    `attempt: None` — which the predicate reads as UNKNOWN and refuses to count as paying. That is
    what keeps the whole rollout window fail-closed in the under-claim direction."""
    rows = _rows
    if rows is None:
        try:
            if events_path is None:
                return {}
            p = Path(events_path)
            if not p.exists():
                return {}
            rows = journal_mod.tail_scan_events(p, "waiting_for_",
                                                max_bytes=_LAND_QUEUE_TAIL_BYTES)
        except Exception:                      # noqa: BLE001 — unreadable journal: nothing is known
            return {}
    now = time.time() if now is None else now
    out: "dict[str, dict]" = {}
    for ev in rows or []:
        if not isinstance(ev, dict) or ev.get("type") not in _LAND_QUEUE_WAIT_TYPES:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        if not data:
            continue
        br = str(data.get("branch") or "").strip()
        if not br:
            continue
        ts = _land_queue_row_epoch(ev.get("ts"))
        if ts is None or (now - ts) > window_s or (ts - now) > window_s:
            continue                           # not evidence of NOW — the same test the queue applies
        att = data.get("attempt")
        try:
            att = int(att) if att is not None else None
        except (TypeError, ValueError):        # a malformed attempt is UNKNOWN, never a guess
            att = None
        pid = data.get("pid")
        try:
            pid = int(pid) if pid is not None else None
        except (TypeError, ValueError):        # T-11878 — a malformed pid is UNKNOWN, never a guess
            pid = None
        if pid is not None and pid <= 0:
            pid = None                         # 0/negative is not a process id — UNKNOWN
        out[br] = {"attempt": att, "no_tests": bool(data.get("no_tests")), "pid": pid}
    return out

def _land_queue_branch_resolves(br: str, main_wt: "Path | None", *,
                                _run_git_cap=None) -> "bool | None":
    """T-11794 — does `br` still resolve to a commit? True / False / None, where None is UNKNOWN.

    The SAME resolution `_land_batch_formation_ids` already performs per member
    (`rev-parse --verify --quiet <br>^{commit}`), reused rather than re-invented: existence is a git
    question and the module has exactly one way of asking it.

    EVERY UNANSWERABLE CASE IS None, NEVER False — a missing checkout, a missing runner, an empty
    name, or a raised call. Its one consumer drops on False alone, so UNKNOWN preserves the
    pre-existing behaviour instead of quietly deleting a candidate on an infrastructure hiccup. Only
    git ITSELF saying the ref does not resolve is a False."""
    if not br or main_wt is None or _run_git_cap is None:
        return None
    try:
        r = _run_git_cap(["rev-parse", "--verify", "--quiet", f"{br}^{{commit}}"], main_wt)
    except Exception:                          # noqa: BLE001 — unanswerable: UNKNOWN, never "gone"
        return None
    if r is None:
        return None
    return bool(getattr(r, "returncode", 1) == 0 and (getattr(r, "stdout", "") or "").strip())

def _land_queue_row_epoch(ts: "str | None") -> "float | None":
    """The epoch seconds of a journal row's `ts`, or None when it cannot be read. None is treated as
    NOT queued (fail-open to a smaller batch) — a row we cannot date cannot be proven current."""
    if not ts:
        return None
    try:
        import datetime as _dt
        s = str(ts).strip().replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.timestamp()
    except Exception:                          # noqa: BLE001 — undatable row: not evidence of NOW
        return None

def _land_queue_terminal_epochs(events_path: "Path | None", *,
                                _rows: "list | None" = None, _land_queue_row_epoch=None) -> "dict[str, tuple] | None":
    """T-11219 — branch -> `(epoch, verdict)` of its LATEST terminal row, or None when the read could
    not be performed at all.

    T-11263 — THE VERDICT RIDES ALONG BECAUSE THE ORDERING TEST IS NOT ENOUGH FOR ONE OF THEM.
    `verdict` is the `land_member_verdict` row's OWN `data.verdict` (`None` for a `land_completed`,
    which has no member verdict). It is read here rather than in a second fold because it is a field
    of the row this fold ALREADY parses — a view over the existing read, not a second journal path
    (CHARTER §P1 filter 2). Its one consumer, `_land_queue_at_slot_free`, keeps the strictly-newer
    ordering test verdict-BLIND for every value except `landed`; see there for why that one needs
    more. Nothing else changes: same tail, same prescan token, same last-write-wins-by-POSITION
    fold, same `inf`-for-undatable rule, same `None` vs `{}` contract.

    `None` and `{}` MEAN DIFFERENT THINGS and the caller branches on the difference: `{}` is "the
    journal was read and nobody has stopped waiting", while `None` is "the liveness question is
    unanswerable for EVERY branch". Collapsing them would turn an unreadable journal into a
    confident "everyone is still waiting" — the precise substitution
    `lessons/a-presence-count-is-not-a-liveness-probe.md` names: when a probe cannot be written for a
    case, fail LOUD there, not TRUE.

    Modelled directly on `_land_batch_ineligible_branches` — same bounded `land_` tail scan, same
    last-write-wins fold keyed on `data.branch`, same shared `_land_queue_row_epoch` ts reader. This
    is that reader applied to a second question, NOT a second journal path (CHARTER §P1 filter 1).
    `_LAND_QUEUE_TAIL_BYTES` is REUSED rather than duplicated: the span must cover the same freshness
    window the wait rows are read over, and a terminal row is by construction NEWER than the waiting
    rows it supersedes, so any tail holding the latter holds the former.

    AN UNDATABLE TERMINAL ROW YIELDS `inf`, NOT A SKIP. The row proves a terminal event happened; only
    its ORDER against the wait rows is unknown. `inf` makes it un-orderable-and-therefore-newer, so
    the caller excludes — the fail-closed direction the card fixes (a missed batch member costs one
    unamortised pass; a phantom member wastes a slot and can draw a wrong batch-ineligibility).
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return None
        try:
            p = Path(events_path)
            if not p.exists():
                return None
            # `land_` is the SUPERSET prescan token; the parsed type check below decides membership —
            # the same contract `_land_batch_ineligible_branches` uses, and both terminal types carry
            # the token.
            rows = journal_mod.tail_scan_events(p, "land_", max_bytes=_LAND_QUEUE_TAIL_BYTES)
        except Exception:                      # noqa: BLE001 — unanswerable for every branch
            return None
    out: "dict[str, tuple]" = {}
    for ev in rows or []:
        if not isinstance(ev, dict) or ev.get("type") not in _LAND_QUEUE_TERMINAL_TYPES:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        if not data:
            continue
        br = str(data.get("branch") or "").strip()
        if not br:
            continue
        ts = _land_queue_row_epoch(ev.get("ts"))
        ts = float("inf") if ts is None else ts
        vd = data.get("verdict")
        vd = str(vd).strip() if isinstance(vd, str) and str(vd).strip() else None
        # LAST WRITE WINS by POSITION, not by max(ts): the journal is append-only, so the newest row
        # governs even when an earlier row carries a later timestamp (a clock-skewed writer). Taking
        # the max would let one skewed row pin a branch terminal forever.
        out[br] = (ts, vd)
    return out

def _land_queue_wait_start(ev: dict, ts: float) -> "float | None":
    """T-11263 — the epoch at which the wait behind a `waiting_for_*` row STARTED, or None when the
    row cannot say.

    `ts - waited_s`, and `waited_s` is already on BOTH wait carriers (T-10128's admission slot and
    T-10549's land reservation both journal it). MEASURED, not assumed (task/T-11234, 2026-08-18):
    `waited_s` restarts at 0 when a NEW land process parks, and does NOT restart across a `landed`
    verdict — across the 04:06:13Z verdict it ran straight on 460 -> 481 -> ... -> 1805, while the
    genuine re-lands at 03:58:24Z and 04:29:37Z each reset it. So this value distinguishes "a NEW
    land is waiting" from "the SAME land is still parked", which is the one thing a heartbeat's own
    timestamp cannot say.

    None on a missing, non-numeric or negative age: a wait we cannot date is not evidence of a
    NEW wait, and the caller excludes on it (the fail-closed direction this reader already takes for
    every other undecidable case).

    T-11681 — `queued_since_s` IS PREFERRED OVER `waited_s`, and the reason is that `waited_s`
    ANSWERS A NARROWER QUESTION THAN THIS FUNCTION'S NAME. It is seconds parked at THIS seam on THIS
    park, and `_t0` is re-seeded on every entry to `_acquire_land_reservation` — so it restarts at
    every RE-PARK, not merely at a new land. MEASURED on this repo's own journal (task/T-11525,
    2026-08-26): four restarts at 10:44:08, 11:18:21, 11:40:02 and 11:42:39, ALL carrying the SAME
    `pid` 1528467 and the SAME `attempt` 1 — one land process, re-parked four times, reporting itself
    as new each time. `queued_since_s` is seconds since that PROCESS first parked at EITHER seam, so
    it survives a re-park and a dissolution alike, and a genuinely new land still reports only its own.

    THE FALLBACK IS WHAT KEEPS T-11263 AND EVERY FIXTURE BYTE-IDENTICAL. A row without the key —
    every row already in the journal, every hermetic fixture — reads `waited_s` exactly as before.

    T-11263 IS PRESERVED, AND ITS LATENT HOLE CLOSES. The phantom test needs a still-parked `landed`
    member's wait start to PREDATE its verdict: with `queued_since_s` it predates it by MORE, so the
    member is still excluded. A genuine re-land is a NEW PROCESS with a NEW baseline, so its wait
    start still POSTDATES the verdict and it is still admitted. What changes is the case that was
    wrong before: a phantom that re-parks in the same process reported `waited_s=0` and was falsely
    re-admitted as a new wait.
    """
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    # PREFERRED first, then the fallback. Each is validated identically, and an INVALID preferred
    # value falls through to the fallback rather than poisoning the answer — a malformed key must
    # not be able to make a row that CAN be dated read as one that cannot.
    for key in ("queued_since_s", "waited_s"):
        w = data.get(key)
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            continue
        if w != w or w in (float("inf"), float("-inf")) or w < 0:   # NaN / inf / negative: undatable
            continue
        return ts - float(w)
    return None

def _land_read_ts_iso(epoch: float) -> str:
    """T-11312 — an epoch rendered in the journal's OWN `ts` shape (`%Y-%m-%dT%H:%M:%SZ`, UTC).

    The exact INVERSE of `_land_queue_row_epoch` below, and rendered in that shape on purpose: the
    whole value of `read_ts` is that a reader can order it against the `ts` of the wait rows and of
    this row itself, which a second format would make an eyeball exercise. Rendered here rather than
    imported from the `bin/yitc-v2` script's `_utc_now_iso` because this library is imported BY that
    script, not the other way round; the format string is the one thing the two must agree on, and the
    round-trip through `_land_queue_row_epoch` is asserted by the tripwire so they cannot drift apart
    silently."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _land_read_yield_offer(main_wt: "Path | None", *, _land_yield_offer_path=None) -> "tuple | None":
    """`(addressee_branch, writer_pid, addressee_land_pid | None)`, or None.

    Answers None on ANY error or malformation. An unreadable offer is an offer that is not there, and
    being not-there only costs the pre-existing unaddressed behaviour — the same fail-open contract
    `_land_supersession_marked` carries.

    T-11878 — THE THIRD ELEMENT IS OPTIONAL AND ITS ABSENCE IS UNKNOWN, NOT DEAD. A two-line offer (an
    offer written before this change, or one whose writer could not resolve the addressee's land pid)
    reads `None` there, and `_land_yield_offer_blocks` treats `None` as not-proven — the offer stays
    live and the T-11490 branch fence governs alone, exactly as today. A malformed or non-positive
    third line reads `None` for the same reason: a handle we cannot read proves nothing, and this
    predicate must never manufacture a death."""
    path = _land_yield_offer_path(main_wt)
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
        br = (raw[0] if raw else "").strip()
        pid = int((raw[1] if len(raw) > 1 else "0").strip() or 0)
        try:
            apid = int((raw[2] if len(raw) > 2 else "").strip() or 0)
        except (TypeError, ValueError):        # unreadable handle — UNKNOWN, never dead
            apid = 0
        return (br, pid, apid if apid > 0 else None) if br and pid > 0 else None
    except Exception:                  # noqa: BLE001 — see docstring
        return None

def _land_rebaselining_branches(events_path: "Path | None", *, now: "float | None" = None,
                                window_s: int = _LAND_QUEUE_FRESHNESS_SEC,
                                _rows: "list | None" = None, _LAND_QUEUE_WAIT_TYPES=None,
                                _land_queue_row_epoch=None,
                                truncated_out: "list | None" = None,
                                key: str = "rebaselining",
                                label: str = "declared-rebaseline (SPEC-0184 rule 4, T-11239)") -> "set[str]":
    """T-11239 (SPEC-0184 rule 4) — the QUEUED branches whose land is REBASELINING a pinned
    assertion, and which must therefore be verified ALONE this round.

    WHY A REBASELINING MEMBER CANNOT BE BATCHED. A batch verifies ONE combined candidate against the
    pinned last-green suite. A member whose change SUPERSEDES a pinned assertion reddens that whole
    candidate, and the only thing that clears it is a `--rebaseline` declaration scoped to the
    assertions ONE `--rebaseline-waive` set NAMES, authorised by THAT card's own audit-post
    (SPEC-0077 §3a). No other member can carry it, and per-member declarations were put to the owner
    on 2026-08-17 and DECLINED — so such a member reddens every batch it joins, deterministically.
    Excluding it BEFORE the pass costs the batch nothing it could have had and saves the combined
    verify pass its peers would otherwise have burned (measured 2026-08-17: both formations that day
    contained a superseder and both died red).

    THE CARRIER IS THE WAIT ROW THE QUEUE READ ALREADY CONSUMES, NOT A NEW STORE. A land declares
    `--rebaseline` at ARGUMENT-PARSE time — as of T-11242 an empty `--rebaseline-waive` is refused
    right there, so an intending land carries a COMPLETE declaration before the reservation, the queue
    read and formation — and it beats `waiting_for_*` heartbeats while queued. Those rows therefore
    carry an ADDITIVE `rebaselining: true` (absent otherwise, so a non-rebaselining land's rows stay
    byte-identical). No new event type, no second store: this is the same additive-key growth
    `queue_depth` / `solo` already ride (D-0009 / SPEC-0025). The HEAD needs none of this — it knows
    its own flags — so this read answers only the PEER half.

    FRESHNESS IS LOAD-BEARING, NOT DECORATION. Only rows INSIDE the same `window_s` the queue read
    uses count, newest-wins: a branch that rebaselined a PRIOR attempt and is now landing WITHOUT the
    flag beats fresh flagless rows and is admitted normally. Without the window, one past declaration
    would exclude that branch from every future batch — a quarantine, which rule 4 explicitly is not.

    FAIL-OPEN TO THE EMPTY SET, always — an unreadable journal, a missing path, an unparseable line
    all yield "nobody is rebaselining", i.e. ordinary formation. Same direction, and for the same
    reason, as `_land_batch_ineligible_branches`: a missed exclusion costs ONE repeated batch (which
    then dissolves and marks its members properly), while a spurious one would shrink batches on bad
    data.
    """
    rows = _rows
    if rows is None:
        if not events_path:
            return set()
        try:
            p = Path(events_path)
            if not p.exists():
                return set()
            # The SAME bounded tail read + prescan token the queue read uses (`waiting_for_`), over
            # the SAME span: this asks a second question of exactly the rows that answer the first,
            # so re-using the reader is the analog-extension, not a second journal path.
            # T-11816 — this reader ALREADY DECLARES its horizon in time (`window_s`, the freshness
            # window it filters on below); until now nothing checked that the bytes it read actually
            # reached back that far. Passing the declaration to the read is the smallest possible
            # change here: on any ordinary journal the base span covers 90 seconds many times over, so
            # the read never grows — but a journal writing fast enough to bury 90 seconds inside
            # 512KB now SAYS SO instead of quietly answering "nobody is rebaselining".
            rows = _land_horizon_rows(
                p, "waiting_for_", horizon_s=window_s,
                label=label,
                truncated_out=truncated_out, now=now,
                base_bytes=_LAND_QUEUE_TAIL_BYTES)
        except Exception:                      # noqa: BLE001 — fail-open: nobody is rebaselining
            return set()
    now = time.time() if now is None else now
    state: "dict[str, bool]" = {}
    for ev in rows or []:
        if not isinstance(ev, dict) or ev.get("type") not in _LAND_QUEUE_WAIT_TYPES:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else None
        if not data:
            continue
        br = str(data.get("branch") or "").strip()
        if not br:
            continue
        ts = _land_queue_row_epoch(ev.get("ts"))
        if ts is None or (now - ts) > window_s or (ts - now) > window_s:
            continue                           # not evidence of NOW — the same test the queue applies
        # LAST WRITE WINS by POSITION over the in-window rows: the journal is append-only, so the
        # newest row states the CURRENT attempt's intent. A flagless row therefore CLEARS an earlier
        # flagged one, which is what keeps the exclusion attempt-scoped.
        state[br] = bool(data.get(key))
    return {br for br, flagged in state.items() if flagged}


def _land_merge_invalid_acceptance_branches(events_path: "Path | None", **kw) -> "set[str]":
    """T-11939 (SPEC-0184 rule 4) — the QUEUED branches that have DECLARED an acceptance assertion
    which is NOT VALID INSIDE A MERGED TREE, and which must therefore be verified ALONE this round.

    THIS IS THE SECOND EXPLICIT GROUND OF THE declare->exclude->solo CHAIN, named by the external
    auditor on 2026-08-28: «Add a separate ground such as acceptance-assertion-merge-invalid; keep the
    rebaseline declaration, hint behavior, and per-assertion waive-token rule distinct.»

    WHY A SECOND GROUND RATHER THAN REUSING THE FIRST. A batch verifies ONE combined candidate. A
    member whose ACCEPTANCE PROBE measures the tree it is verified in — the canonical shape is a
    `git diff --name-only` of the branch against `main` reaching HEAD, which inside a batch is the
    MERGED tree — reads the PEERS'
    work as its own and reddens the combined candidate deterministically, through no fault of its own.
    That branch supersedes NO pinned assertion and has NOTHING to waive, so `--rebaseline` /
    `--expect-rebaseline` would be a FALSE STATEMENT and T-11760 correctly declined to make it. Today
    that left it no honest way to ask for the solo verify it needs. MEASURED COST OF HAVING NO GROUND
    (T-11760, recorded): 6 batches in ~60 minutes all reddening on ONE assertion — requeues T-11760 x5,
    T-11740 x4, T-11755 x3, T-11733 x2, each a fully paid verify that shipped nothing.

    IT IS A THIN NAMED WRAPPER OVER `_land_rebaselining_branches`, NOT A COPY (CHARTER §P1 F1). The
    freshness window, the newest-wins last-write-wins semantics, the horizon-shortfall reporting and
    the fail-open-to-the-empty-set direction are IDENTICAL questions asked of the SAME rows, and
    forking them is how two readers of one journal drift apart. Only the KEY and the diagnostic LABEL
    differ. The wrapper exists so the call sites and the SPEC-0184 `implements:` anchors read by
    GROUND rather than by parameter value.

    WHAT IT DOES NOT DO, and this is the load-bearing negative (T-11939 AC2). Membership of this set
    GRANTS NOTHING. It never enters `declares_rebaseline`, and it is deliberately absent from the
    `_sup = _sup - _reb` precedence subtraction in `_land_form_members` — a declared REBASELINE is the
    authorised way to supersede a pinned assertion (SPEC-0077 §3a) and so clears the T-11267
    supersession exclusion; a merge-invalid declaration carries no such authority and clears nothing.
    A branch that supersedes a pinned assertion still needs its own `--rebaseline` and still fails
    closed without one.
    """
    kw.setdefault("key", "merge_invalid_acceptance")
    kw.setdefault("label", "declared-merge-invalid-acceptance (SPEC-0184 rule 4, T-11939)")
    return _land_rebaselining_branches(events_path, **kw)

def _land_reconcile_member_verdicts(batch_state: "dict | None", *, _append_event,
                                    events_path: "Path | None" = None,
                                    batch_id: "str | None" = None, _emit_land_member_verdicts=None) -> int:
    """SPEC-0184 rule 5 — journal `unaccounted` for every DECLARED member that got no verdict row.

    THE HOLE THIS CLOSES. Verdicts are emitted from four explicit member LISTS, and until this
    function nothing compared those lists against the set `land_batch_formed` DECLARED. Measured
    2026-08-19T13:24:35Z: a batch declared three members, two rows were emitted, and `task/T-11032`
    received nothing — not landed, not evicted, not requeued, not dropped — then formed its own
    batch a minute later. A member that leaves the declared set with no row is indistinguishable
    from one that was never declared; the atomic rule is that it must not be. This is the MEMBER
    axis of the same accounting T-11312 made true on the CANDIDATE axis one step earlier, and it
    reuses that card's `unaccounted` constant rather than respelling the word.

    `unaccounted` IS NOT A FIFTH OUTCOME. The two decisions rule 5 already carries both stand: the
    removal SINK stays diagnostic and non-terminal, and the four outcome values stay claims about a
    member's CHANGES — which is exactly why the audit-absorbed 2026-08-16 decision refused to
    journal an attempt-level removal reason as one of them. This row claims nothing about the
    member's changes. It states the only fact the land owns about a member it dropped: *this batch
    declared you and produced no outcome for you*. The recorded reason rides along when one exists,
    as enrichment; its ABSENCE means unrecorded, never that no reason existed.

    RULE 1 IS UNTOUCHED, AND NOT BY A SECOND GUARANTEE. The emit routes through
    `_emit_land_member_verdicts`, whose N=1 clause already owns the byte-identity promise: a
    declared set of ONE yields zero rows, no stdout, no staged bytes. `batch_size` is the DECLARED
    size for the same reason every other call site passes a size it did not derive from its own
    list — the clause must ask "was this a batch?", never "how many are silent?".

    IDEMPOTENT BY CONSTRUCTION: the members it emits for are appended to the same `verdicted` sink
    the emitter feeds, so a second call over the same state finds nothing left to say.

    THE KEY COMES FROM THE MEMBER'S OWN DECLARATION, NOT FROM ONE BLANKET VALUE (T-11653). The
    `batch_id` argument is read from the land's state dict at the `finally`, where it holds whatever
    the LAST formation minted — `None` after a solo re-formation, a different id after a second
    multi-member one — while `declared` accumulates across every formation. Stamping that one value
    on all of them answers a question no single value can: it either loses the key outright (42
    `unaccounted` rows after T-11331 closed, measured 2026-08-26) or, worse, silently attributes a
    first-formation member to a batch that never declared it — the very mis-attribution rule 5's key
    exists to retire. So the silent members are GROUPED by the id recorded on their own declaration
    and one emit is made per group. The argument survives as the FALLBACK for a record carrying no id
    (state built before this change, and every probe that supplies none), so a single-formation land
    — the overwhelming majority — makes exactly ONE call with exactly today's payload.

    `batch_size` STAYS `len(declared)` FOR EVERY GROUP, deliberately, and it is not the group's
    length. The emitter's N=1 clause must keep asking "was this a batch?" and never "how many are
    silent in this group?"; a lone silent member of a four-member batch would otherwise be swallowed
    by that clause and lose the row this whole function exists to emit. This is the same reading
    every other call site passes a size it did not derive from its own list for — the semantics are
    untouched.
    """
    if batch_state is None:
        return 0
    declared = batch_state.get(_LAND_BATCH_DECLARED_KEY) or []
    reasons = batch_state.get(_LAND_BATCH_REMOVED_KEY) or {}
    # T-11702 — THE SILENT SET COMES FROM THE ONE READER OF IT. «Declared, minus everyone the
    # emitter already journaled» is now `_land_declared_members_awaiting_verdict`, because the
    # post-ff `landed` emit needs the identical answer on an inert retry that reaches the ff holding
    # no `batch_members` of its own. Two spellings of one question is exactly the drift CHARTER §P5
    # forbids, and it would drift in the direction that matters: this sweep would keep sweeping
    # members the other seam had decided to speak for. `batch_size` below stays `len(declared)` —
    # the size of the BATCH, never of the silent subset — for the reason stated above.
    silent = _land_declared_members_awaiting_verdict(batch_state)
    # T-11653 — GROUP BY THE ID EACH MEMBER WAS DECLARED UNDER, falling back to the argument for a
    # record that carries none. First-seen order, so the emitted sequence is deterministic.
    groups: "dict" = {}
    for rec in silent:
        if reasons.get(rec["branch"]):
            rec["unaccounted_reason"] = reasons[rec["branch"]]
        groups.setdefault(rec.pop("batch_id", None) or batch_id, []).append(rec)
    if not groups:
        return 0
    sink = batch_state.setdefault(_LAND_BATCH_VERDICTED_KEY, [])
    return sum(
        _emit_land_member_verdicts(
            silent, _LAND_DISPOSITION_UNACCOUNTED, _append_event=_append_event,
            events_path=events_path, batch_id=bid, batch_size=len(declared),
            emitted_out=sink)
        for bid, silent in groups.items())

def _land_red_batch_ineligible_members(members: "list[dict]",
                                       assertions: "list[str] | None",
                                       *, timeout_marker: "str | None" = None) -> "set[int]":
    """T-11272 (SPEC-0184 rule 4) — WHICH members of a dissolving batch are marked batch-INELIGIBLE.
    Returns member INDICES. Pure: it reads the member records and the failing entries, and decides
    nothing else — the caller marks, the emitter reports.

    THE DEFECT THIS REMOVES (measured 2026-08-18T06:54:52Z). Rule 4's blanket mark was correct when a
    dissolve could not tell WHO broke the batch. Since T-11259 it often can: the death-time attribution
    names the member that owns the failing pinned assertion. That day a four-member all-paying batch died
    on two assertions BOTH attributed to `task/T-11253`; all four were marked anyway, so rule 4 forced
    each to verify ALONE and the queue paid one red pass PLUS four individual passes — one more than
    doing nothing. Three of those four passes were spent on members with no evidence against them.

    THE BLANKET IS THE DEFAULT AND THE NARROWING IS A CARVE-OUT, WITH A POSITIVE DISCRIMINATOR
    (`lessons/carving-an-exception-into-a-fail-closed-gate`). The question asked is not "did we detect
    ambiguity?" — an absence-shaped test that lets a partially-explained red through — but
    **does the attribution ACCOUNT FOR THE WHOLE RED?** Only then is the batch entitled to say who the
    culprits were. Concretely, EVERY entry the red surfaced must be a pinned entry that some member was
    attributed with. Anything else means part of the red is unexplained:

      * a NON-pinned entry — a candidate-leg failure the attribution says nothing about at all;
      * an entry naming no assertion (`_NO_ASSERTION_CAPTURED`), stopped at attribution gate 2;
      * an entry whose key resolved to no path or to two (gate 3);
      * an entry with zero or with several candidate owners (gate 4).

    Each of those is a way a culprit can exist and go UNNAMED, and an unnamed culprit left eligible
    rejoins the next batch and kills it — the hole the card's dependency T-11271 was to close from the
    admission side and, having closed UNBUILT on a measured zero firing rate for its own arm, did not.
    It is closed HERE instead, at the seam that holds both the final member list and the assertions, and
    it covers the measured population that arm did not: of the 12 pinned entries over the 8 recorded
    dissolves, 10 had exactly one owner and 2 had ZERO — and a zero-owner entry is precisely an
    unexplained red.

    THE ANTI-LIVELOCK FENCE IS THE RETURN VALUE'S OWN SHAPE (T-11194 AC3, rule 4's second half). For
    every red EXCEPT an all-timeout one (see below) this function can never return an EMPTY set for a
    dissolving batch: it either returns >= 1 attributed culprit or it returns every member. So the
    identical batch can never re-form on the next slot — somebody is always still marked, and rule 4's
    peer filter drops them before the cap, leaving a strictly smaller candidate set. A change that
    marked nobody would satisfy "only culprits are marked" and rebuild exactly the failure rule 4
    exists to prevent.

    THE ONE EXCEPTION: AN ALL-TIMEOUT RED MARKS NOBODY (T-11714). The fence above is justified by the
    livelock — after a red dissolve the same members are still queued together, so the next slot would
    re-form the SAME batch and fail IDENTICALLY forever, and marking them single-verify for one round
    terminates that by construction. That argument needs the red to be a VERDICT ABOUT THE MEMBER
    COMBINATION. A verify TIMEOUT is not one: it is an INCONCLUSIVE run, the T-0678 abort class one
    rule over (`_land_red_isolation_entries`) already refuses to convict anybody on. Re-forming the
    same batch under lighter load may well pass, so "it would fail identically" cannot be inferred
    from a timeout at all — the premise the blanket rests on is simply ABSENT, and the blanket
    converts ONE inconclusive run into N full verifies (measured 2026-08-27T15:06:43Z: batch
    bat-621a860a8cbb, four members, BOTH failures reading only `TIMED OUT after 300s`, no culprit
    attributed — correctly, since a timeout belongs to nobody — and all four penalised anyway).

    THE DISCRIMINATOR IS POSITIVE, and it is the whole risk of the carve-out
    (`lessons/carving-an-exception-into-a-fail-closed-gate` §1). The question is NOT "did we fail to
    find a culprit?" — an absence-shaped test that would swallow the rule — but "is EVERY entry the
    red surfaced a timeout?", asked through the isolation probe's OWN predicate
    (`_land_entry_is_verify_timeout`, one detector, two readers). Every other shape therefore falls
    through to the UNCHANGED code below, all three fail-closed toward today's blanket:
      * MIXED (a timeout BESIDE a real failing assertion) — not all-timeout, so the marking applies
        exactly as today. The combination IS implicated by the real assertion, so the livelock the
        fence prevents is live and the guard must not be relaxed;
      * an EMPTY red — caught by the `not assertions` guard above, which runs FIRST and is untouched;
      * an ABSENT/empty `timeout_marker` (this function's own plumbing broken) — the predicate is
        false for every entry, so a failed injection can never open the exception.
    WHAT IS NOT DECIDED HERE, per the card's scope: the 300s timeout VALUE, and whether a timed-out
    batch should be RETRIED. The members still requeue and still journal `requeued-after-red-batch`;
    only the one-round penalty is withheld.

    ONE ROUND, NOT A QUARANTINE — UNCHANGED. This decides WHO is marked and nothing about how long the
    mark lasts or what discharges it: T-11241's clearing copy to main and T-11256's
    verify-actually-ran predicate both stay exactly as they are, and a marked culprit is released by its
    own individual verdict as before.
    """
    everyone = set(range(len(members)))
    if not assertions:
        return everyone                        # a red with no surfaced entry explains nothing
    # T-11714 — the ALL-timeout carve-out, positive and asked before anything else is derived: an
    # inconclusive run is not a verdict about the member combination, so nobody is penalised for it.
    if timeout_marker and all(_land_entry_is_verify_timeout(e, timeout_marker) for e in assertions):
        return set()
    attributed: "set[str]" = set()
    culprits: "set[int]" = set()
    for i, m in enumerate(members):
        if not isinstance(m, dict):
            continue
        owned = m.get("superseded_assertions") or []
        if owned:
            culprits.add(i)
            attributed.update(str(x) for x in owned)
    if not culprits:
        return everyone                        # nobody was named — today's behaviour, retained (AC3)
    for entry in assertions:
        text = str(entry)
        if not text.startswith(_LAND_PINNED_ENTRY_PREFIX):
            return everyone                    # a candidate-leg failure attribution cannot speak to
        if text[len(_LAND_PINNED_ENTRY_PREFIX):] not in attributed:
            return everyone                    # a pinned failure nobody owns — a culprit may be unnamed
    return culprits

def _land_red_decline_record(iso: "dict | None", members: "list | None", *,
                             culprit_indices: "list | None" = None,
                             evictions_spent: int = 0) -> dict:
    """T-11348 — WHY a red batch evicted NOBODY, as an outcome with a named reason. Pure: it decides
    nothing new, journals nothing, and returns `{"outcome", "reason"}` — never `None`, never empty.

    THE JUDGEMENT IS ALREADY MADE; THIS IS A HAND-OFF. `_land_red_isolation_probe` returns a
    COMPLETE record on every path, with three named non-eviction outcomes and a reason for each —
    and its own docstring states the property: a decline must be an OUTCOME with a reason, else "the
    oracle ran and could not decide" is indistinguishable from "the oracle never ran"
    (`lessons/a-report-only-signals-differential-is-indistinguishability`). The defect this closes is
    that the reason was computed and then DROPPED: `_emit_land_member_verdicts` copies
    `red_isolation` / `evicted_as_culprit` only on the EVICTION path, so when the answer is NOBODY
    the row said nothing. So for those three outcomes this function PASSES THE PROBE'S OWN
    outcome+reason THROUGH unchanged — no new vocabulary, no re-derivation, no second authority.

    THE FOURTH OUTCOME IS DERIVED, NOT INVENTED. The probe can answer `culprits` and the land still
    not act, because the fork applies four further conditions (the head is unevictable, a survivor
    must remain, one eviction round per land). Recording a bare `culprits` beside zero evictions
    would rebuild the exact indistinguishability one layer up, so `culprits-not-actionable` names
    WHICH condition refused — read off the SAME conditions the fork evaluates, which is why this
    takes `culprit_indices` and `evictions_spent` as INPUTS rather than recomputing them. The reason
    strings mirror the fork's own order:
      * `no-non-head-culprit` — nothing but the head reproduced (nothing evictable was named);
      * `head-is-culprit`     — the head, and ONLY the head, reproduced: `members[0]` owns the
                                candidate branch the ff pushes, so removing it would rewrite this
                                land's own subject (followup fu_a12b6c0a26b0). Asked AFTER the
                                non-head arms since T-11650 — a set naming the head BESIDE an
                                evictable member is not this decline, it is an eviction;
      * `no-survivor`         — evicting everybody is a dissolve by another name;
      * `eviction-budget-spent` — this land already spent its one round.

    FAIL-CLOSED, BECAUSE `undecidable` IS A REAL ANSWER. An absent record, an unknown outcome or a
    missing reason all become `undecidable` with a NAMED reason (`no-isolation-record` /
    `unknown-outcome:<x>` / `unreported`) rather than silence — recording "the oracle could not
    decide" as though it were absence is precisely the defect this function removes. That also
    covers the two cases amend note 4 measured live and neither the probe nor the fork calls
    special: NOT-APPLICABLE (the red was a spec-edit chokepoint rejection, not a test failure at all
    — the probe's own gate answers `non-test-entry`; a pinned supersession answers `pinned-entry`)
    and NEVER-PROBED (a batch of one, or no admission slot — `not-probed`). Both arrive here as
    ordinary `undecidable` reasons and are recorded as such; neither needs a fifth outcome.

    THE OUTCOME IS ALWAYS IN `_LAND_RED_DECLINE_OUTCOMES`, so a reader can act on a closed set.

    AND THE `culprits-not-actionable` RECORD NAMES THE SET (T-11650). `reason` is a REASON, not a
    roster: on a multi-member culprit set it names one condition and reads as a verdict on one
    branch. The additive `culprits:` key lists EVERY member the oracle proved reproduces alone —
    head included — so the row reports what was found rather than what may be acted on.
    """
    _rec = iso if isinstance(iso, dict) else {}
    _outcome = str(_rec.get("outcome") or "").strip()
    _reason = str(_rec.get("reason") or "").strip()
    if not _rec:
        return {"outcome": "undecidable", "reason": "no-isolation-record"}
    if _outcome == "culprits":
        _ix = [int(i) for i in (culprit_indices if culprit_indices is not None
                                else _rec.get("culprit_indices") or [])]
        _non_head = [i for i in _ix if i > 0]
        # T-11650 — THE HEAD ARM IS ASKED LAST OF THE TWO, NOT FIRST. It used to be `if 0 in _ix`,
        # which ended the derivation the moment the head appeared ANYWHERE in the set — so a record
        # naming the head AND an evictable non-head member returned `head-is-culprit`, the fork
        # released the peers, and the member that could have been acted on was never reached (four
        # consecutive red batches on 2026-08-26; the fork's own comment carries the batch ids). The
        # reason is now what it always claimed to be: the head is the culprit, meaning it is the
        # ONLY one named. A head-plus-non-head record with the budget unspent falls through to
        # `actionable-but-not-acted` below, which is correct AND unreachable in production — the
        # fork acts on exactly that input and never asks for a decline reason.
        if 0 in _ix and not _non_head:
            _why = "head-is-culprit"
        elif not _non_head:
            _why = "no-non-head-culprit"
        elif len(_non_head) >= len(members or []):
            _why = "no-survivor"
        elif int(evictions_spent) >= 1:
            _why = "eviction-budget-spent"
        else:
            # The fork's four conditions all held, so this is not a decline at all. Reaching here
            # means the caller asked the wrong question; say so rather than inventing an excuse.
            _why = "actionable-but-not-acted"
        # T-11650 — AND THE ROW NAMES THE SET, PLURAL. A REASON is not a roster: `head-is-culprit`
        # reads as a verdict on one branch, and a reader took it as an accusation and reasoned from
        # it for hours (2026-08-25/26). The probe already proved, per member, who reproduced the
        # whole red alone, so every one of them is named here — head included, because the head
        # being unevictable is a statement about what the fork MAY DO, never about what the oracle
        # FOUND. Naming one member of a multi-member culprit set would rebuild the same defect one
        # layer up, so the record names all of them or none.
        #
        # ALWAYS EMITTED WHEN INDICES EXIST, never gated on cardinality. A key that appeared only
        # for two-or-more culprits would make "exactly one culprit" indistinguishable from "the set
        # was not recorded" — the very indistinguishability this function was written to remove
        # (lessons/a-report-only-signals-differential-is-indistinguishability). ABSENT therefore
        # means UNRECORDED, and an out-of-range index is DROPPED rather than guessed at.
        _rec_out = {"outcome": "culprits-not-actionable", "reason": _why}
        _names = [str((members[i] or {}).get("branch") or "") for i in _ix
                  if isinstance(members, list) and 0 <= i < len(members)
                  and isinstance(members[i], dict) and (members[i] or {}).get("branch")]
        if _names:
            _rec_out["culprits"] = _names
        return _rec_out
    if _outcome not in _LAND_RED_DECLINE_OUTCOMES:
        return {"outcome": "undecidable", "reason": f"unknown-outcome:{_outcome or 'absent'}"}
    return {"outcome": _outcome, "reason": _reason or "unreported"}

def _land_entry_is_verify_timeout(entry, timeout_marker: "str | None") -> bool:
    """T-11714 — is this surfaced red entry a verify TIMEOUT? THE one timeout detector, two readers.

    The expression is trivial and that is the point: it was already spelled inline in
    `_land_red_isolation_entries`, and `_land_red_batch_ineligible_members` needs the SAME question
    answered one rule over. Spelling it twice would let the two drift — the isolation probe would go
    on declining a timeout while the ineligibility marking convicted the members of one, which is
    precisely the split this card exists to close. So it is a named function with two callers rather
    than a repeated `in` (the card's fifth scope bullet: reuse the predicate, do not write a second
    detector).

    FAIL-CLOSED ON ITS OWN PLUMBING. An absent or empty `timeout_marker` answers FALSE for every
    entry — never TRUE-by-vacuity. Both callers read a TRUE as licence to relax (the probe refuses to
    run, the marking withholds a penalty), so a marker that never arrived must read as "not a
    timeout", leaving each caller on its existing path.
    """
    return bool(timeout_marker) and timeout_marker in str(entry)

def _land_red_isolation_entries(bad: "list | None", timeout_marker: "str | None",
                                _surface_failing_assertions=None, *, _land_red_isolation_surface_one=None) -> "tuple[list, str | None]":
    """The failing CANDIDATE-leg `(test file, assertion)` PAIRS this oracle may re-run — or the reason
    it may not run. Returns `(pairs, refusal_reason)`; exactly one of the two is meaningful.

    THE PAIR, NOT THE FILE, IS THE UNIT OF ATTRIBUTION (audit-post finding, high, 2026-08-20). A file
    name alone is not the thing that went red: a member whose alone-tree fails the SAME FILE on a
    DIFFERENT assertion has reproduced a different problem, and evicting it would convict a branch of
    a failure that is not the batch's. So the assertion is carried from the start, matched exactly,
    and stored on the row — which is also what makes the record name the DECIDING assertion instead
    of merely the file it lived in.

    The assertion text comes from `_surface_failing_assertions` — the SAME surfacer the abort message
    and the `--rebaseline-waive` matcher read (CHARTER §P5, one extractor). Without it injected there
    is no assertion to match on, so the probe refuses rather than falling back to file-level matching:
    a silently weaker match is exactly the guess this oracle exists not to make.

    THE GATE IS A WHITELIST OVER THE WHOLE SET, NOT A FILTER. Every entry the red surfaced must be a
    candidate-leg test-file failure this oracle can actually reproduce; ONE entry it cannot leaves
    part of the red unexplainable, and a member cleared against a partial picture is a member cleared
    on evidence nobody read. The same positive-condition shape `_land_red_batch_ineligible_members`
    uses one rule over. Each refused class is a distinct way the answer fails to be obtainable:

      * a `[pinned/last-green] ` entry — reproducing it needs the pinned OVERLAY construction
        (last-green checks over a candidate subject), not a plain re-run, so this oracle cannot
        answer it and must not pretend to;
      * a verify TIMEOUT — the T-0678 abort class that must NEVER be consumed by a retry. Refusing it
        here is what keeps that guarantee true through this new path, not merely through the text of
        the `_land_integrate` structural check;
      * a runner LAUNCH failure — the runner's own error, never a statement about anyone's changes;
      * anything that is not `test failed: <name>` — a graph-build failure, a conflict-marker line,
        the host-leak canary, a CONSUMER verify-LAYER key (`_consumer_verify_layer_key`, for a project
        that delegates its tests). None of them is a file this runner can be pointed at;
      * an entry naming NO assertion (`_NO_ASSERTION_CAPTURED` — the marker T-10892 introduced so an
        unreadable tail stops being reported as a plausible-but-wrong assertion). There is nothing to
        match a member's run against, and matching on the file alone would be exactly the weaker
        comparison the pair rule above exists to refuse. Same refusal T-11259's gate 2 makes, for the
        same reason.
    """
    if not bad:
        return ([], "no-failing-entries")
    if _surface_failing_assertions is None:
        return ([], "no-assertion-reader")
    pairs: list = []
    for entry in bad:
        s = str(entry)
        first = s.splitlines()[0].strip() if s.strip() else ""
        if first.startswith(_LAND_PINNED_ENTRY_PREFIX):
            return ([], "pinned-entry")
        if _land_entry_is_verify_timeout(entry, timeout_marker):
            return ([], "verify-timeout")
        if _LAND_LAUNCH_FAILURE_MARKER in s:
            return ([], "runner-launch-failure")
        if not first.startswith(_LAND_TEST_FAILED_PREFIX):
            return ([], "non-test-entry")
        name = first[len(_LAND_TEST_FAILED_PREFIX):].strip()
        if not name:
            return ([], "unnamed-test-entry")
        surfaced, why = _land_red_isolation_surface_one(entry, name, _surface_failing_assertions)
        if why:
            return ([], why)
        if surfaced not in pairs:
            pairs.append(surfaced)
    return (pairs, None if pairs else "no-failing-test-files")

def _land_red_isolation_probe(members: "list[dict]", bad: "list | None", *,
                              main_wt: "Path | None" = None,
                              merged_base: "str | None" = None,
                              test_subdir: "str | list[str]" = _LAND_CANDIDATE_TEST_SUBDIR,
                              workers: "int | None" = None,
                              _run_git_cap=None, _run_verify_tests=None,
                              _VERIFY_TIMEOUT_MARKER: "str | None" = None,
                              _DERIVED_MERGE_ARTIFACTS=None, _dedup_events=None,
                              _anchor_signature_of_text=None,
                              _surface_failing_assertions=None,
                              _run_subset=None, _land_merge_probe=None, _land_probe_advance=None, _land_red_isolation_entries=None, _land_red_isolation_reproduced=None) -> dict:
    """SPEC-0184 rule 4 — WHICH members of a red batch reproduce the failure ALONE. Returns a RECORD;
    decides nothing and journals nothing. The caller acts (or does not) and reports.

    THE RECORD IS ALWAYS COMPLETE, INCLUDING WHEN IT SAYS NOTHING. `{"outcome": ..., "reason": ...,
    "failing": [...], "culprits": [...], "culprit_indices": [...], "reproduced": {branch: [...]}}`.
    A decline is an OUTCOME with a named reason, never an empty return — otherwise "the oracle ran
    and could not decide" is indistinguishable from "the oracle never ran"
    (`lessons/a-report-only-signals-differential-is-indistinguishability`), and a mechanism that
    fires on nothing looks exactly like one that fires on everything.

    THE MEMBER-ALONE TREE COMES FROM THE EVICTION PATH'S OWN ORACLE, never a second merge feed:
    `_land_merge_probe(merged_base, branch)` for the tree and `_land_probe_advance` for an
    UNREFERENCED commit over it — the same pair rule 3's eviction walk accumulates through. One
    question, one authority (CHARTER §Principle 5); a second feed that could disagree about what
    "this member on main" IS would let selection and isolation reason about different trees. The
    commit is then checked out DETACHED into a throwaway worktree, which is removed in a `finally` on
    every path. `main`, the candidate and the members' branches are untouched throughout.

    THE TESTS ARE RUN BY THE ONE RUNNER. `_run_verify_tests(..., only=<the failing names>)` — same
    hermetic per-subprocess sandbox, same per-file timeout, same `test failed:` shape. A private
    re-implementation would answer a subtly different question and its disagreement with the verify
    would be invisible. Nothing is journaled: no `journal_path`, no `metrics_out`, no
    `selection_diff_paths`, so the oracle writes no event and no SPEC-0181 shadow record.

    EVERY GATE FAILS CLOSED TO `undecidable`, which the caller reads as today's behaviour:
      * fewer than two members, or any required reader absent (`_run_subset` is the ONE hermetic
        injection seam; without it the git + runner set is required in full);
      * a failing set this oracle cannot reproduce, or one whose assertions it cannot read — see
        `_land_red_isolation_entries`;
      * a member that will not isolate (unmergeable onto `merged_base`, an unwritable commit, a
        worktree that would not add);
      * a member run that could not be READ as a verdict — see `_land_red_isolation_reproduced`.

    PER-MEMBER PROOF, NEVER INFERENCE (audit-pre finding F2, 2026-08-20). A member enters `culprits`
    ONLY by reproducing, on its OWN alone-tree, at least one of the named failing files. Never by
    elimination, never because the union still needs covering, never because a peer was proven. The
    completeness rule below can only SHRINK what the caller may act on; it can never add a member.
    That is what makes "several fail alone -> evict each" exactly as sound as the single-culprit case
    — it is the same proof repeated per member, not a weaker set-level claim.

    COMPLETENESS IS A POSITIVE CONDITION (the `_land_red_batch_ineligible_members` shape): the
    outcome is `culprits` ONLY when the union of what the members reproduced EQUALS the failing set.
      * union EMPTY  -> `interaction`. No member breaks it alone, so the failure belongs to the
        MERGED tree and nobody may be evicted — the third outcome, and it is not optional.
      * union SHORT  -> `partially-explained`. Something in the red is still unaccounted for, so the
        remainder may well contain it; evicting on a partial picture would spend a pass to fail again.
    Both are today's behaviour, and both are recorded DISTINCTLY so the two can be told apart later.

    THE UNIT OF ATTRIBUTION IS THE `(file, assertion)` PAIR, NEVER THE FILE (audit-post finding,
    high, 2026-08-20). A member that reddens the SAME file on a DIFFERENT assertion has not
    reproduced this red, and the probe refuses rather than either convicting it or clearing it — see
    `_land_red_isolation_reproduced`. `failing` and `reproduced` therefore carry
    `"<file>: <assertion>"` lines, which is also what lets the row name the DECIDING assertion.

    A MEMBER WHOSE ALONE-TREE LACKS A FAILING FILE SIMPLY DOES NOT REPRODUCE IT — sound, not a guess:
    the file exists only because some other member added it, so without that member it cannot fail.
    A member for which NONE of the failing files exists runs nothing and reproduces nothing; that is
    an answer, not a skipped check.

    THE HEAD IS NOT SPECIAL-CASED HERE, DELIBERATELY. This function reports the truth about every
    member including `members[0]`; the caller applies the un-evictability of the slot holder, exactly
    as rule 3 keeps that judgement at its own decision site. Mixing the two would hide a real
    isolation result behind a structural constraint that belongs to the ff, not to the evidence.

    ================================================================================================
    DEPRECATED 2026-08-29 (T-11796) — THIS PROBE IS RETIRED-IN-DECISION AND HAS NEVER ONCE DECIDED.
    ================================================================================================
    Everything above still describes what this function DOES, and it still runs. What follows is the
    disposition decided about it, recorded here — in its own docstring — so that the next reader does
    not rediscover the measurement from scratch. This is step 1 (WARN/deprecate) of
    `patterns/retirement-procedure.md`: annotate, leave working and visible. Steps 2-4
    (disable -> analyze -> remove) are NOT done and are filed separately; see REMOVAL-TRIGGER below.

    THE RECORD: 0 ACTIONABLE OUTCOMES IN 161 FIRINGS. Folded over the whole logical journal on
    2026-08-29: 161 `red_isolation_decline` rows, and NOT ONE with `outcome: culprits`. Every firing
    in this probe's recorded life declined. By outcome: undecidable 133, culprits-not-actionable 26,
    interaction 2. By reason: pinned-entry 107, head-is-culprit 18, verify-timeout 13,
    entry-names-no-assertion 11, eviction-budget-spent 8, member-run-assertion-mismatch 2,
    no-member-reproduces-alone 2. Two thirds of all declines are `undecidable/pinned-entry`, which is
    this repo's single most common red — so on the DOMINANT red class this probe cannot name a
    culprit at all, and rule 4's fallback (every member of the red batch serves the solo round) runs
    every time. THE FALLBACK IS CORRECT and is NOT what was questioned: failing closed with no
    attribution is the right answer. What was questioned, and answered, is the probe that never
    supplies one while costing an eviction budget and a decision path on every red batch.

    REPRODUCE IT YOURSELF — AND MIND THE SEGMENTS, THE FOLD IS THE TRAP. The journal is ONE logical
    history across bounded PHYSICAL segments (SPEC-0190 rule 4), so a fold over the `events.jsonl`
    path ALONE reads the LIVE segment only: it returns 121 rows and mis-states every sub-count
    (head-is-culprit 4 rather than 18), which reads as the measurement FAILING to reproduce. The 40
    missing rows are in rotated `archive/events-*.jsonl`. The fold must span both:

        python3 -c 'import json,collections,glob
        c=collections.Counter(); n=0
        for p in sorted(glob.glob("archive/events-*.jsonl"))+["events.jsonl"]:
            for line in open(p):
                if "red_isolation_decline" not in line: continue
                d=(json.loads(line).get("data") or {}).get("red_isolation_decline")
                if isinstance(d,dict): n+=1; c[(d.get("outcome"),d.get("reason"))]+=1
        print(n, "declines;", c[("culprits",None)], "actionable"); print(sorted(c.items()))'

    Counts only GROW with time; the claim that survives any later cut is the one that matters —
    `outcome: culprits` is 0.

    THE DISPOSITION: RETIRE (option (b)), not repair and not keep. Decided at T-11796 Analysis on the
    numbers above plus an external adjudication —
    `decisions/batch-culprit-probe-never-decides-audit-adhoc.yaml` (RED, finding 1, high): retire
    rather than repair the attribution, and remove WITH it both positional head attribution and the
    rotation-invariant idea as a safety net (the rotation check does not survive as a replacement).
    The live incident behind that verdict:
    `decisions/batch-culprit-attribution-rotates-audit-adhoc.yaml` — 6 batches, ONE constant failing
    assertion, and SIX DIFFERENT blamed heads; the branch that OWNED the assertion was never named,
    because it was never the head. That is direct evidence the rule names SLOT POSITION, not owner.
    Grounding principle: CHARTER Principle 8 — 161 firings with 0 actionable outcomes is exactly the
    shipped-but-never-adopted shape that principle exists to detect.

    BEFORE YOU BUILD A REPLACEMENT, CLEAR THE BAR OFFLINE — it is a hard gate, not advice. Any
    ownership-based attribution rule proposed in this probe's place must FIRST be replayed over every
    prior red-batch record in the whole journal, computing whether failing-artifact ownership would
    have named exactly one actionable, non-head, non-interaction culprit that CHANGED formation or
    landing disposition. Threshold: >= 20% actionable decisions overall, zero safety regressions
    against known interactions, and no dependence on positional head ownership. Below that bar,
    abandon it — in the auditor's words, it becomes "the 148th non-decision under a new name".

    REMOVAL-TRIGGER: the removal is PLAN-shaped and is NOT a follow-on edit anyone should make from
    here. It needs (i) the `patterns/retirement-procedure.md` step-3 HIGH-BLAST-RADIUS recorded
    pre-cut CONSUMER INVENTORY — this is a first-class mechanism whose consumers include the
    named-culprit advisory (T-11815), the exonerated-member verdict (T-11797), the peers-release
    attribution carry (T-11495), `_land_red_decline_record`, `_land_pinned_entry_culprits`, and a
    large STRUCTURAL pinned-test surface in `tests/test_t11335_evict_on_test_redness.py` that
    inspects this function by SOURCE — machine-readably gated so the cut cannot start until the
    inventory is done; and (ii) the coupled generalisation of the declare->exclude->solo chain by an
    explicit new ground (that verdict's finding 2), which is a standing-rule change on its own card.
    An unexpected consumer surfacing mid-cut is migrated or blocks — NEVER a silent cut.

    REQUIREMENT (i) IS NOW DISCHARGED, AND THE CUT IS FILED AND GATED (T-11870). The inventory is
    `ideas/pre-cut-consumer-inventory-red-batch-culprit-isolation-probe.md`: 13 consumers, each with
    ONE recorded fate (RETIRE C1-C4 · MIGRATE C5-C7, C11-C13 · KEEP C8-C9 · BLOCKING-FOLLOW-UP C10),
    zero un-triaged, scanned on four independent handles — the symbol, the RECORD KEYS
    (`red_isolation` / `red_isolation_decline`, which outlive the function because they are on
    append-only rows), the private sibling helpers, and the `specs/` prose. The cut is **T-11909**,
    which `requires: T-11870` — that is the machine-readable gate the pattern demands, so the cut
    cannot start until the inventory has landed, and operator memory is not what holds it.
    THREE THINGS THE INVENTORY FOUND that this paragraph did not know: the cut is NOT symmetric (the
    keys must stay READABLE for the 161 rows of history, so `debt.py`'s
    `DEAD_LAND_RED_EVIDENCE_KEYS` must not be tidied away with the function); the structural pinned
    surface must be triaged PIN BY PIN into probe-owned and rule-4-owned rather than deleted as a
    file; and `_land_pinned_entry_culprits` (T-11515) is a DECISION to re-root or retire, not a
    mechanical move — it is reached only through a decline from here, but it is not this probe.
    REQUIREMENT (ii) IS UNTOUCHED AND STILL BLOCKS. Nothing here is cut by T-11870 — it recorded the
    inventory and filed the gate, which is what step 3 asks for; the deletion is T-11909's, behind
    the standing-rule card (ii) still names.

    WHAT IS ALREADY PROVEN SAFE: dissolution does not need this probe. With `red_isolation=None` the
    dissolution path still journals a verdict for every member and still lands rule 4's one-round
    batch-ineligibility mark, so the livelock still terminates —
    `tests/test_t11796_dissolution_without_the_probe.py` pins exactly that, and it is also the
    step-3 "observe that nothing breaks" evidence the cut will need.
    """
    import shutil
    import tempfile

    rec: dict = {"outcome": "undecidable", "reason": None, "failing": [],
                 "culprits": [], "culprit_indices": [], "reproduced": {}}

    def _undecidable(reason: str) -> dict:
        rec["outcome"] = "undecidable"
        rec["reason"] = reason
        return rec

    if not members or len(members) <= 1:
        return _undecidable("batch-of-one")
    if _run_subset is None and not (main_wt is not None and merged_base
                                    and _run_git_cap is not None and _run_verify_tests is not None):
        return _undecidable("no-isolation-reader")

    failing, refusal = _land_red_isolation_entries(bad, _VERIFY_TIMEOUT_MARKER,
                                                   _surface_failing_assertions)
    if refusal:
        return _undecidable(refusal)
    rec["failing"] = list(failing)
    # The FILE half of each pair, for the two places that address files rather than failures: the
    # presence check against a member's tree, and the runner's `only=` selection.
    failing_files = []
    for _pair in failing:
        _n = str(_pair).partition(": ")[0]
        if _n not in failing_files:
            failing_files.append(_n)

    def _run_member(member: dict) -> "tuple[list, str | None]":
        """This member's alone-tree verdict over `failing`: `(reproduced, refusal_reason)`."""
        branch = str((member or {}).get("branch") or "").strip()
        if not branch:
            return ([], "member-without-branch")
        if _run_subset is not None:
            try:
                out = _run_subset(member, list(failing))
            except Exception as _e:            # noqa: BLE001 — an injected reader that raised
                return ([], f"member-run-error:{type(_e).__name__}")
            return _land_red_isolation_reproduced(out, list(failing), _VERIFY_TIMEOUT_MARKER,
                                                  _surface_failing_assertions)
        outcome, tree, _detail = _land_merge_probe(
            merged_base, branch, main_wt, _run_git_cap=_run_git_cap,
            _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS, _dedup_events=_dedup_events,
            _anchor_signature_of_text=_anchor_signature_of_text)
        if outcome not in _LAND_PROBE_MERGEABLE or not tree:
            return ([], f"member-not-isolatable:{branch}")
        sha = _land_probe_advance(merged_base, tree, branch, main_wt, _run_git_cap=_run_git_cap)
        if not sha:
            return ([], f"member-commit-unwritable:{branch}")
        wt = Path(tempfile.mkdtemp(prefix="yitc-red-isolation-"))
        shutil.rmtree(wt, ignore_errors=True)   # `git worktree add` needs a NON-existent path
        try:
            add = _run_git_cap(["worktree", "add", "--detach", str(wt), sha], main_wt)
            if getattr(add, "returncode", 1) != 0:
                return ([], f"member-worktree-unavailable:{branch}")
            # T-11204: `test_subdir` is ONE repo-relative dir (every pre-T-11204 caller) or the SET
            # the candidate sweep actually swept. The oracle MUST look where the sweep looked — a
            # file resolved anywhere else answers a different question than the red it explains.
            _subs = [test_subdir] if isinstance(test_subdir, (str, Path)) else list(test_subdir or [])
            _subs = [str(s) for s in _subs] or [_LAND_CANDIDATE_TEST_SUBDIR]
            present = [n for n in failing_files
                       if any((wt / s / n).exists() for s in _subs)]
            if not present:
                # Nothing this member's tree even CONTAINS. It cannot fail a file that is not there,
                # so it reproduces nothing — a positive answer, not an unrun check.
                return ([], None)
            try:
                out = _run_verify_tests([wt / s for s in _subs], wt, workers=workers, only=set(present))
            except Exception as _e:            # noqa: BLE001 — the runner itself could not run
                return ([], f"member-run-error:{type(_e).__name__}")
            _asked = [p for p in failing if str(p).partition(": ")[0] in present]
            return _land_red_isolation_reproduced(out, _asked, _VERIFY_TIMEOUT_MARKER,
                                                  _surface_failing_assertions)
        finally:
            try:
                _run_git_cap(["worktree", "remove", "--force", str(wt)], main_wt)
            except Exception:                  # noqa: BLE001 — cleanup never masks the verdict
                pass
            shutil.rmtree(wt, ignore_errors=True)
            try:
                _run_git_cap(["worktree", "prune"], main_wt)
            except Exception:                  # noqa: BLE001
                pass

    explained: list = []
    for i, m in enumerate(members):
        reproduced, refusal = _run_member(m if isinstance(m, dict) else {})
        if refusal:
            return _undecidable(refusal)
        branch = str((m or {}).get("branch") or "")
        rec["reproduced"][branch] = list(reproduced)
        if reproduced:
            rec["culprits"].append(branch)
            rec["culprit_indices"].append(i)
        for n in reproduced:
            if n not in explained:
                explained.append(n)

    if not explained:
        rec["outcome"] = "interaction"
        rec["reason"] = "no-member-reproduces-alone"
        rec["culprits"], rec["culprit_indices"] = [], []
        return rec
    if set(explained) != set(failing):
        rec["outcome"] = "partially-explained"
        rec["reason"] = "unexplained:" + ",".join(sorted(set(failing) - set(explained)))
        rec["culprits"], rec["culprit_indices"] = [], []
        return rec
    rec["outcome"] = "culprits"
    return rec

def _land_red_isolation_reproduced(out: "list | None", asked: "list",
                                   timeout_marker: "str | None",
                                   _surface_failing_assertions=None, *, _land_red_isolation_surface_one=None) -> "tuple[list, str | None]":
    """Read ONE member-alone run's output: `(reproduced "<file>: <assertion>" lines, refusal_reason)`.

    A POSITIVE READ, and that is the whole safety of the eviction it feeds. "Non-empty output" is NOT
    read as "this member reproduced the failure": a launch error and a timeout arrive in the same
    shape as an assertion failure, so each is matched and turns the probe undecidable rather than
    convicting the member the run happened to be about.

    THE MATCH IS ON THE PAIR, AND A SAME-FILE / DIFFERENT-ASSERTION RESULT IS UNDECIDABLE — NOT
    "did not reproduce" (audit-post finding, high, 2026-08-20). A member that reddens the same file
    on a DIFFERENT assertion has broken something, just not demonstrably the thing the batch died of.
    Calling that "no reproduction" would be worse than refusing: it would leave that member in the
    candidate while some OTHER member is evicted, so the land would evict the wrong branch and then
    re-verify a tree that still contains a broken one. Refusing is the only answer that is not a
    guess in either direction. An entry naming a file we did not ASK for refuses for the sibling
    reason — the run was not the run we think it was.
    """
    reproduced: list = []
    asked_names = {str(a).partition(": ")[0] for a in asked}
    for entry in out or []:
        s = str(entry)
        first = s.splitlines()[0].strip() if s.strip() else ""
        if timeout_marker and timeout_marker in s:
            return ([], "member-run-timeout")
        if _LAND_LAUNCH_FAILURE_MARKER in s:
            return ([], "member-run-launch-failure")
        if not first.startswith(_LAND_TEST_FAILED_PREFIX):
            return ([], "member-run-unreadable-entry")
        name = first[len(_LAND_TEST_FAILED_PREFIX):].strip()
        if name not in asked_names:
            return ([], "member-run-unasked-file")
        line, why = _land_red_isolation_surface_one(entry, name, _surface_failing_assertions)
        if why:
            return ([], f"member-run-{why}")
        if line not in asked:
            return ([], "member-run-assertion-mismatch")
        if line not in reproduced:
            reproduced.append(line)
    return (reproduced, None)

def _land_red_isolation_surface_one(entry, name: str,
                                    _surface_failing_assertions, *, _NO_ASSERTION_CAPTURED=None) -> "tuple[str | None, str | None]":
    """ONE `bad` entry -> its canonical `"<file>: <assertion>"` line, or a refusal reason.

    Delegated to the shared surfacer and then CHECKED, never trusted blind: the line must actually be
    about the file this entry named, and it must name an assertion. Both checks are refusals rather
    than repairs — a surfacer that answered about a different file, or about nothing, is a surfacer
    this oracle cannot attribute with."""
    try:
        out = _surface_failing_assertions([entry]) or []
    except Exception:                          # noqa: BLE001 — an extractor that raised proves nothing
        return (None, "assertion-unreadable")
    if len(out) != 1:
        return (None, "assertion-unreadable")
    line = str(out[0])
    key, sep, assertion = line.partition(": ")
    if not sep or key.strip() != name or not assertion.strip():
        return (None, "assertion-unreadable")
    if assertion.strip().startswith(_NO_ASSERTION_CAPTURED):
        return (None, "entry-names-no-assertion")
    return (line, None)

def _land_release_peers_for_solo_head(members: "list[dict]", *, reason: str = _LAND_PEER_RELEASE_REASON,
                                      _append_event, events_path: "Path | None" = None,
                                      batch_id: "str | None" = None,
                                      assertions: "list[str] | None" = None,
                                      failure_attribution: "dict | None" = None,
                                      emitted_out: "list | None" = None, _emit_land_member_verdicts=None, _land_mark_red_assertions=None) -> int:
    """SPEC-0184 rule 4, the HEAD-IS-CULPRIT arm — RELEASE the peers and let the head verify ALONE.
    Returns the number of rows journaled. The sibling of `_land_dissolve_batch`, and deliberately the
    SMALLER one: it performs NO git at all.

    WHY THIS IS NOT THE DEFERRED CARRY-THE-SURVIVORS DESIGN. The structural bound is unchanged and is
    not being overcome: `members[0]` owns the candidate branch the fast-forward pushes, so removing it
    would rewrite this land's own subject, which is why the oracle names the head and the fork then
    declines (`culprits-not-actionable` / `head-is-culprit`). Carrying the survivors PAST a red head
    (fu_a12b6c0a26b0) would need a DIFFERENT ff target — a throwaway branch off `merged_base` holding
    only the peers — plus rework of rule 4's atomicity argument and of `_land_members_carried_by_ff`.
    This SIDESTEPS the bound instead: NOBODY lands on this pass either, but the head then fails ALONE,
    which makes its failure unambiguously its own, and the released peers form the NEXT batch without
    it. A solo batch is an already-supported formation shape (`_land_batch_members`' head
    short-circuit), so there is no new ff target, no atomicity rework and no accounting change.

    WHAT IT BUYS, MEASURED. Three consecutive red batches on 2026-08-21 (06:27:46, 06:37:07, 06:44:23)
    requeued twelve member-attempts and landed nothing; two of the three declined as
    `head-is-culprit` — the offender WAS identified and could not be acted on. Under this arm each of
    those becomes one solo head retry plus a clean peer batch.

    A RELEASE IS NOT A PUNISHMENT, AND THE ROW MUST SAY SO. A released peer did nothing: it was not
    shown to be part of the cause, and the head was. So each peer is marked `batch_ineligible: False`
    — the EXISTING key `_land_batch_ineligible_branches` reads (T-11272), so the peer keeps ordinary
    eligibility for the very next formation on the same terms as any other candidate — plus the
    additive `released_from_batch` record naming WHY and WHICH head, so a reader can tell a release
    from the `requeued-after-red-batch` punishment on the row alone rather than by inferring it from
    an absent penalty.

    THE VERDICT STRING IS UNCHANGED — `requeued-after-red-batch`, not a fifth vocabulary value. Same
    argument T-11335's eviction made and for the same three reasons: it is TRUE (the peer does return
    to the queue), it keeps rule 5's vocabulary CLOSED, and it is the value every existing consumer
    already reads. The release rides ADDITIVE keys on that row, the copy-never-decide shape the
    module uses throughout.

    IT RUNS NO GIT, AND THAT IS AC3. The candidate is reset to `_batch_pre_sha` by the retry loop's
    own head — the SAME reset the eviction path relies on — so the peers' commits leave the branch by
    the unchanged mechanism and this function creates no branch, no worktree and no ff target. What
    it owns is the JOURNAL half of the release, nothing else.

    AT N<=1 IT IS A NO-OP THAT EMITS NOTHING (rule 1), like the dissolve: a singleton has no peers to
    release and its own `land_completed` row is its verdict in full.

    AND IT CARRIES WHAT KILLED THE BATCH (T-11494). Measured over this repo's journal
    2026-08-23T17:00Z..2026-08-24T05:00Z: twelve multi-member batches went red, TEN of them ended
    here, and not one of those ten put a cause on any row that reaches `main` — while the two that
    DISSOLVED did. The cause existed: it reached the head's own `land_completed` abort row, which is
    written in the HEAD BRANCH's worktree journal and stays there until that branch lands. So a
    controller reading `main` could not answer the first question triage asks, and the answer took
    opening `events.jsonl` inside each head worktree by hand — where the causes turned out NOT to be
    uniform (branch-attributed on two heads, a pinned entry on one, undecidable on one, a single
    environment-caused assertion on three). These verdict rows are emitted with
    `events_path=main_wt / "events.jsonl"`, so they make the trip NOW. Same asymmetry T-11331 closed
    for the dissolve, closed for the arm that carried ten of the twelve reds.

    THROUGH THE SAME SINGLE MARKING SITE, from the SAME surfaced list, and CLAIMING NOTHING NEW. The
    marking is `_land_mark_red_assertions` — the one function in the module that writes the key, so
    this arm adds no second extractor and no second gate (CHARTER §P5). The list it is handed at the
    call site is the `_assertions` the abort's own FAILING ASSERTION(S) block and both probes are
    built from, so the row states exactly what the operator reads. And it is a BATCH fact, not an
    accusation: the head is the member the red was attributed to, the peer was released precisely
    because nothing was shown about it, and `released_from_batch` on the same row already says so.
    ABSENT still means UNRECORDED — the helper's gate is unchanged, so a release whose red surfaced
    no assertion text carries no key rather than an empty list.

    AND IT CARRIES WHOSE THE RED IS (T-11495) — the OTHER HALF of the paragraph above. `assertions`
    records WHAT killed the batch; `failure_attribution` records the T-11464 probe's verdict on
    WHOSE it was: `{outcome: branch | main | undecidable, reason, failing, at_main, at_branch}`,
    produced by re-running only the failing files at the merge-base. With the cause alone a reader on
    main can see that a head was blamed and on what, but NOT whether that same assertion still fails
    WITHOUT the branch — and on 2026-08-23 evening that distinction was the whole answer: of the
    heads whose worktree journals had to be opened by hand, three later passed alone, one was
    genuinely branch-attributed, and three carried `outcome: main` from an environment cause. Folded
    over this repo's journal at filing time: 327 `land_member_verdict` rows, 40 of them released, and
    ZERO carrying a verdict. The record EXISTS on this attempt — `cmd_land` has already computed it
    for the abort — but a peers-released red does not ABORT, it RETRIES, so no `land_completed` row
    is written for the attempt and the verdict never travels.

    HANDED OVER, NEVER RECOMPUTED. The probe runs inside `_verify_under_admission` (SPEC-0132) and is
    real test subprocesses; paying it a second time here to re-derive an answer this attempt already
    holds would double the one verify load the governor exists to bound. So this arm takes the record
    as an ARGUMENT and never reaches for the probe — a bound asserted both behaviourally and
    structurally by `tests/test_t11495_peers_released_red_attribution.py`.

    THE `not-probed` SENTINEL READS AS ABSENCE HERE, AND THAT IS NOT AN INCONSISTENCY WITH THE ABORT
    ROW. `cmd_land` initialises `_attr` to `{"outcome": "undecidable", "reason": "not-probed"}` for
    the case where no admission slot was held, so the probe never ran; the probe itself never returns
    that reason. The abort row records it deliberately, because there "the probe could not decide"
    and "the probe never ran" are both answers about an attempt the reader is already looking at. On
    a MEMBER row there is no such context: a row that says `undecidable` for a red nobody probed is a
    fabricated verdict, and a fabricated verdict is worse than a missing one. So the gate below drops
    the sentinel and RECORDS a probe-produced `undecidable` — the two share an outcome and differ
    only in reason, which is why the gate keys on the reason and not on the outcome.

    THE VERDICT STRING AND EVERY EXISTING CALLER ARE UNTOUCHED. `assertions` and
    `failure_attribution` both default to None, which marks nothing, so the whole hermetic suite and
    any caller that does not pass them are byte-identical.
    """
    if len(members) <= 1:
        return 0
    _head = str((members[0] or {}).get("branch") or "")
    _peers = [m for m in members[1:] if isinstance(m, dict)]
    for _m in _peers:
        # ABSENT vs FALSE means different things to `_land_batch_ineligible_branches`, so this is
        # written explicitly rather than left off: absent reads as INELIGIBLE (the pre-T-11272
        # behaviour), which is exactly the punishment a release must not carry.
        _m["batch_ineligible"] = False
        _m["released_from_batch"] = {"reason": str(reason), "head": _head}
    # T-11494 — the batch's cause, onto the rows that already report THAT the peer was requeued.
    # Marked through the module's SINGLE marking site, which owns the non-empty gate, so this arm
    # adds no second extractor and `assertions=None` (every pre-existing caller) marks nothing.
    _land_mark_red_assertions(_peers, assertions)
    # T-11495 — AND WHOSE THE RED IS, onto the same rows. The mirror of T-11348's `red_decline` carry
    # on the dissolve arm: a member-record key nobody else writes, marked at ONE site, copied
    # verdict-agnostically by the emitter. The record is the one `cmd_land` ALREADY computed for this
    # attempt's abort — handed over, never recomputed (the probe is admission-slotted).
    #
    # ONE GATE, KEYED ON THE REASON AND NOT THE OUTCOME. `not-probed` is the CALLER's sentinel for
    # "no admission slot was held, so the probe never ran"; the probe never returns it. A
    # probe-produced `undecidable` shares that outcome and IS recorded — dropping both would rebuild
    # exactly the indistinguishability the record exists to remove
    # (lessons/a-report-only-signals-differential-is-indistinguishability). ABSENT MEANS UNRECORDED.
    if failure_attribution and str(failure_attribution.get("reason") or "") != "not-probed":
        for _m in _peers:
            _m["failure_attribution"] = dict(failure_attribution)
    return _emit_land_member_verdicts(_peers, "requeued-after-red-batch",
                                      _append_event=_append_event, events_path=events_path,
                                      batch_id=batch_id, batch_size=len(members),
                                      emitted_out=emitted_out)

def _land_reservation_held_by_self(main_wt: Path, *, _flock_holder=None, _land_reservation_path=None) -> bool:
    """T-11117 — is the land reservation held by THIS VERY PROCESS?

    An fcntl flock is per open-file-description, so a second land inside the same process blocks on the
    FIRST land's own fd — and waits on itself forever. No bound makes that correct; it only delays it.
    Production never nests lands (one land per process, and the span-end release hands the reservation
    on), so a self-held reservation means an IN-PROCESS caller — the shape the land engine's own tests
    drive when they land A from inside B's after-verify seam. Such a caller must proceed on the ordinary
    optimistic path immediately rather than queue behind itself.

    Uses the existing `_flock_holder` (T-11076), which already names the SELF case explicitly. That
    helper is best-effort and NEVER raises: an unresolvable holder answers False and the caller falls
    back to its bounded wait — fail-safe, since a false negative merely means waiting as before."""
    holder = _flock_holder(_land_reservation_path(main_wt))
    return bool(holder) and holder.get("pid") == os.getpid()

def _land_reservation_path(main_wt: Path, *, _verify_slot_dir=None) -> Path:
    """T-10549: the ONE land-fairness reservation flock target for this repo. Lives in the SAME
    off-tree sidecar as the verify-slot pool (keyed on realpath(main_wt) — one reservation per repo,
    never in the working tree, never committed). A distinct filename beside `slot-N`; the slot pool
    opens `slot-{i}` by exact name and globs nothing, so this can never be mistaken for a slot."""
    return _verify_slot_dir(main_wt) / "land-reservation"

def _land_restore_candidate_head(W: "Path | None", pre_sha: "str | None", *,
                                 branch: "str | None" = None, _run_git_cap=None,
                                 _append_event=None, events_path: "Path | None" = None,
                                 reason: str = "", batch_size: int = 0,
                                 peers: "list | None" = None) -> str:
    """SPEC-0184 rule 4 — take the batch's peer merges back off the head member's branch. Returns
    `not-needed` | `restored` | `failed`.

    "NOT-NEEDED" IS DECIDED BY THE RECORDED BATCH STATE, NEVER BY A MISSING `pre_sha` (audit-pre
    finding, absorbed mode-a 2026-08-17). Reading a falsy `pre_sha` as "so there is nothing to undo"
    is the fail-open this function exists to close, stated backwards: it takes the ABSENCE OF THE UNDO
    TARGET as evidence that no undo is due, which is precisely wrong when peers are already on the
    branch. So the question asked first is "was a peer merged at all?" — answered by `peers` /
    `batch_size`, which the caller records AT the merge — and only a proven NO returns `not-needed`.
    `_land_merge_batch_into_candidate` already refuses to merge peers it cannot undo (it fails closed
    to a batch of one when HEAD is unreadable), so a merged batch with no `pre_sha` should be
    unreachable today; that is a reason it must never fire, not a reason to make it silent when it
    does.

    AN UNPERFORMABLE RESTORATION IS LOUD — the second, independent fail-open this replaces. The prior
    code guarded on `if pre_sha and _run_git_cap is not None and W is not None:` and wrapped the reset
    in `except Exception: pass`, while its own docstring promised "the peers' commits leave this
    branch". Both halves failed open, and the second failed open INVISIBLY: `_run_git_cap` RETURNS a
    completed process and does not raise on a nonzero exit, so the `except` never fired on the failure
    that actually matters — a failing `git reset` was discarded without any exception at all. Here the
    RETURNCODE is what is read; an exception is caught, recorded and reported, never `pass`ed. The
    same reading is already the retry path's discipline (`batch-retry-reset-failed`) — this extends
    that in-repo precedent to the other sites rather than inventing a posture.

    NOT FATAL, AND THAT IS NOT THE SAME AS QUIET. Every caller is on a path that is already ending
    (the dissolve `_die`s next; the catch-all runs while an abort propagates), so raising here would
    replace a precise diagnosis with a git error. Loudness is carried instead by the journal row and
    an explicit stderr block naming the branch, the target sha and the hand remedy — which is what
    makes a residue DISCOVERABLE rather than silent.
    """
    _peers = list(peers or [])
    if not _peers and batch_size <= 1:
        # PROVEN nothing to undo: no peer was merged into this candidate, so its history never left
        # its pre-formation state. This is the only silent exit, and it rests on a positive fact.
        return _LAND_RESTORE_NOT_NEEDED

    def _record(outcome: str, error: "str | None" = None) -> str:
        if _append_event is not None:
            data = {"branch": branch, "pre_sha": pre_sha, "outcome": outcome,
                    "reason": reason, "batch_size": batch_size,
                    "peers": [str(p) for p in _peers]}
            if error:
                data["error"] = error
            try:
                _append_event("land_batch_head_restored", data, events_path=events_path)
            except BaseException:              # noqa: BLE001 — the row is evidence, never the gate
                pass
        if outcome == _LAND_RESTORE_FAILED:
            _target = pre_sha or "<unknown — no pre-batch sha was recorded>"
            print(f"land: WARNING — could NOT take the batch's peer merges back off {branch} "
                  f"({reason}). The peers merged into this branch are STILL IN ITS HISTORY: "
                  f"{', '.join(str(p) for p in _peers) or '<unrecorded>'}. "
                  f"Intended pre-batch state: {_target}."
                  + (f" git said: {error}" if error else "")
                  + f"\nland: REMEDY — inspect with `git -C {W} log --oneline` and, once you have "
                    f"confirmed nothing of your own is above it, `git -C {W} reset --hard {_target}`. "
                    "Landing this branch as-is would carry another card's commits (SPEC-0184 rule 4).",
                  file=sys.stderr, flush=True)
        return outcome

    if not pre_sha or _run_git_cap is None or W is None:
        # Peers WERE merged and the undo cannot even be attempted. This is the three-way guard's
        # fail-open, and it is exactly what AC3 makes loud rather than skipping.
        return _record(_LAND_RESTORE_FAILED,
                       "no pre-batch sha recorded" if not pre_sha else "no worktree/git handle")
    try:
        r = _run_git_cap(["reset", "--hard", pre_sha], W)
    except Exception as e:                     # noqa: BLE001 — reported, never swallowed
        return _record(_LAND_RESTORE_FAILED, f"{type(e).__name__}: {e}")
    if getattr(r, "returncode", 1) != 0:
        return _record(_LAND_RESTORE_FAILED, (getattr(r, "stderr", "") or getattr(r, "stdout", "")
                                              or "").strip() or "nonzero exit")
    return _record(_LAND_RESTORE_DONE)

def _land_rollback_bookkeeping_to_entry(W: "Path | None", entry_sha: "str | None", *,
                                        branch: "str | None" = None, _run_git_cap=None,
                                        minted_shas=None, main_ref: str = "main") -> str:
    """T-11467 — ON AN ABORT, LEAVE THE BRANCH AT THE SHA THE LAND STARTED FROM. Returns
    `not-needed` | `restored` | `skipped` | `failed`.

    THE DEFECT. `cmd_land` step-1b creates this land's `land: bookkeeping` commit BEFORE it verifies,
    and an aborting land KEPT it. Measured on `task/T-11457` (2026-08-23): bookkeeping commits at
    04:19:01 / 04:28:32 / 04:46:13 / 04:59:16, each followed by an abort at 04:26:15 / 04:35:43 /
    04:53:16 / 05:05:38 — four attempts, four DIFFERENT candidate trees, whole content 15 journal
    rows. That defeats what T-10977 shipped: `--rebaseline-waive` demands an EXACT match in BOTH
    directions (`_rebaseline_waive_coverage` grants only when `uncovered` AND `bad_tokens` are both
    empty), so a failing set measured on attempt N is consumed against attempt N+1's tree and can
    never be reliably right. Restoring the entry sha is what makes a measured declaration still valid
    on the next attempt.

    WHY ROLL BACK RATHER THAN LET THE NEXT LAND AMEND. T-9799 deliberately identifies its amend target
    by the sha THIS land minted rather than by a forgeable subject; making that identity
    cross-invocation would reopen exactly the hazard it closed. The commit is undone by the invocation
    that made it, so the identity stays in-process.

    ELIGIBILITY IS BY IDENTITY, NEVER BY SUBJECT (audit-pre YELLOW, absorbed mode-a 2026-08-23) — the
    same reasoning one paragraph up, applied to the reset itself. A commit in `entry_sha..HEAD`
    qualifies iff (i) its sha is one THIS land minted (`minted_shas` — every `_land_bookkeeping_commit`
    return, recorded onto the `_batch_state` handshake dict that already crosses
    `cmd_land`/`_land_integrate`), or (ii) it is a two-parent merge whose SECOND parent is an ancestor
    of `main` — a catch-up merge OF main, which `_update_from_main` puts on nearly every branch and
    which git can PROVE topologically — or (iii) the commit ALREADY LIVES ON `main` (what such a merge
    brought in), so resetting past it destroys nothing. Any other commit -> `skipped`, LOUD, branch untouched: an
    authored commit is never destroyed to satisfy this card.

    NOTHING JOURNALED IS LOST (the trap this function is written around). `events.jsonl` is append-only
    and union-merged, so a bare `git reset --hard` — the obvious implementation — would DISCARD the
    rows this land folded and trade one defect for a worse one. The rows are read BEFORE the reset and
    re-appended after it, deduped by exact line (the identity `_dedup_events` uses), landing back as
    ordinary trailing journal dirt — which is precisely what the next land's step-1b fold is FOR.

    NOT FATAL, AND THAT IS NOT THE SAME AS QUIET — the posture of its sibling
    `_land_restore_candidate_head`, reused rather than re-invented: the RETURNCODE is read (a
    `_run_git_cap` failure does not raise), an exception is reported and never `pass`ed, and every
    non-restoring outcome prints branch + target sha + the hand remedy on stderr. The caller is
    already on a path that is ending, so raising here would replace a precise diagnosis with a git
    error.
    """
    import os as _os
    import subprocess as _subprocess

    if not entry_sha or W is None or _run_git_cap is None:
        # No entry sha was recorded, so step-1b never ran and the branch never moved — every preflight
        # refusal ends here. A positive fact about the ordering, not an inference from a missing value.
        return _LAND_RESTORE_NOT_NEEDED

    def _loud(outcome: str, detail: str) -> str:
        print(f"land: WARNING — could NOT return {branch or '<branch>'} to the sha it started from "
              f"({entry_sha}): {detail}. The branch is NOT at its pre-land sha, so a failing set "
              f"measured on this attempt may not describe the tree the next attempt verifies "
              f"(T-11467).\n"
              f"land: REMEDY — inspect with `git -C {W} log --oneline {entry_sha}..HEAD` and, once you "
              f"have confirmed nothing of your own is above it, `git -C {W} reset --mixed {entry_sha}` "
              f"(--mixed, NOT --hard: it keeps the journal rows in the worktree for the next land to "
              f"fold).", file=sys.stderr, flush=True)
        return outcome

    try:
        head = (_run_git_cap(["rev-parse", "HEAD"], W).stdout or "").strip()
    except Exception as e:                     # noqa: BLE001 — reported, never swallowed
        return _loud(_LAND_RESTORE_FAILED, f"{type(e).__name__}: {e}")
    if not head:
        return _loud(_LAND_RESTORE_FAILED, "HEAD is unreadable")
    if head == entry_sha:
        return _LAND_RESTORE_NOT_NEEDED        # the branch never moved — the ordinary silent exit
    if _run_git_cap(["merge-base", "--is-ancestor", entry_sha, head], W).returncode != 0:
        return _loud(_LAND_ROLLBACK_SKIPPED, "the entry sha is not an ancestor of HEAD")

    minted = {str(s) for s in (minted_shas or []) if s}
    walk = _run_git_cap(["log", "--format=%H%x00%P", f"{entry_sha}..{head}"], W)
    if walk.returncode != 0:
        return _loud(_LAND_RESTORE_FAILED, "the commits above the entry sha could not be listed")
    for line in (walk.stdout or "").splitlines():
        sha, _, parents_raw = line.partition("\x00")
        sha = sha.strip()
        if not sha or sha in minted:
            continue
        if _run_git_cap(["merge-base", "--is-ancestor", sha, main_ref], W).returncode == 0:
            # Already ON main — a commit the catch-up merge BROUGHT IN. Resetting the branch past it
            # destroys nothing: main is where it lives, and the next attempt merges it back in.
            continue
        parents = parents_raw.split()
        if len(parents) == 2 and _run_git_cap(
                ["merge-base", "--is-ancestor", parents[1], main_ref], W).returncode == 0:
            continue                            # a catch-up merge OF main — provably this land's own
        return _loud(_LAND_ROLLBACK_SKIPPED,
                     f"{sha[:9]} above it is not a commit this land minted (nor a catch-up merge of "
                     f"{main_ref}) — refusing to discard it")

    journal = Path(W) / "events.jsonl"
    try:
        before = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
    except OSError as e:
        return _loud(_LAND_RESTORE_FAILED, f"the journal could not be read before the reset: {e}")

    try:
        r = _run_git_cap(["reset", "--hard", entry_sha], W)
    except Exception as e:                     # noqa: BLE001 — reported, never swallowed
        return _loud(_LAND_RESTORE_FAILED, f"{type(e).__name__}: {e}")
    if getattr(r, "returncode", 1) != 0:
        return _loud(_LAND_RESTORE_FAILED, (getattr(r, "stderr", "") or getattr(r, "stdout", "")
                                            or "").strip() or "the reset exited nonzero")

    # AC2 — put back every row the reset took off the working file. Append-only + exact-line dedup:
    # a row already carried by the entry-sha version is not duplicated, and one that is not is
    # restored IN ORDER as trailing dirt for the next land's fold.
    restored_rows = 0
    try:
        base = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
        seen = set(base)
        extra = []
        for ln in before:
            if ln.strip() and ln not in seen:
                seen.add(ln)
                extra.append(ln)
        if extra:
            tmp = journal.with_suffix(journal.suffix + ".t11467.tmp")
            tmp.write_text("\n".join(base + extra) + "\n", encoding="utf-8")
            _os.replace(str(tmp), str(journal))
            restored_rows = len(extra)
    except OSError as e:
        # The branch IS at its entry sha; what failed is the row restoration. Say exactly that —
        # reporting it as a clean restore would be the one dishonest outcome available here.
        print(f"land: WARNING — {branch or '<branch>'} was returned to {entry_sha}, but "
              f"{len(before)} journal row(s) read before the reset could NOT be written back: {e}. "
              f"Rows this land folded may be missing from this worktree (they remain wherever they "
              f"were already landed).", file=sys.stderr, flush=True)
        return _LAND_RESTORE_FAILED

    print(f"land: the branch {branch or '<branch>'} is left at {entry_sha} — EXACTLY the sha it "
          f"started from (this land's bookkeeping commit was rolled back"
          + (f"; {restored_rows} journal row(s) preserved as trailing worktree dirt for the next "
             f"land to fold" if restored_rows else "")
          + "). Consecutive attempts on this branch therefore verify the SAME tree (T-11467).",
          file=sys.stderr, flush=True)
    return _LAND_RESTORE_DONE

def _land_superseded_reverify_decision(commits_ahead: "int | None",
                                       delta_verdict: "str | None",
                                       delta_class: "str | None" = None) -> "tuple[str, str]":
    """SPEC-0184 rule 8 — THE decision: does this land skip its verify because it carries nothing that is
    not already in main? Returns `("skip"|"verify", reason)`.

    PURE, and deliberately so: it takes the two oracles' ANSWERS rather than calling them, which makes
    every bound below assertable on an inline fixture with no git and no journal, and keeps the inert
    authority's sanctioned-consumer set (T-0631) unchanged — this function is not a second place that
    decides what "inert" means, it consumes SPEC-0064's one authority via its caller.

    BOTH AXES MUST ANSWER POSITIVELY. `commits_ahead == 0` says the branch carries no history main lacks;
    an INERT delta says the tree this attempt would fast-forward changes nothing the verification
    environment executes or observes. Neither alone is enough — the first without the second would skip a
    land whose own step-2b/step-3 bookkeeping had pulled in observable content, and the second without
    the first is the SPEC-0065 lever-B question, which is bounded to retries for its own reasons and is
    not this one.

    THE SAFETY ARGUMENT is SPEC-0065's, and it is if anything stronger here: `main` advances ONLY via a
    green land, so the base is already verified; a branch that adds no commits to it and no observable
    path on top of it produces a tree that is verification-EQUIVALENT to that already-green base. The
    green-before-ff gate is preserved, not relaxed — there is no untested combination, because there is
    no new combination.

    EVERY OTHER INPUT VERIFIES, and says which one it was, so a land that did NOT skip is diagnosable
    without re-deriving the inputs."""
    if commits_ahead is None:
        return ("verify", "content-undecidable")
    if commits_ahead > 0:
        return ("verify", "carries-unlanded-commits")
    if delta_verdict != "inert":
        return ("verify", f"delta-observable:{delta_class or 'unclassified'}")
    return ("skip", _LAND_SUPERSEDED_SKIP)

def _land_supersession_marked(main_wt: "Path | None", branch: "str | None", *, _land_supersession_marker_path=None) -> bool:
    """SPEC-0184 rule 8, READ SIDE — is THIS branch marked superseded? ONE `exists()`, never raises.

    THIS IS THE COST-CLASS CONTRACT, and it is the reason the mechanism is a marker at all. The park
    loops read the flock and the clock and nothing else BY DESIGN: parsing a large append-only journal
    every poll interval is the wrong cost class, and a journal read here would be exactly the defect that
    makes a cheap loop expensive. A single stat of a fixed path is the same cost class as the
    non-blocking flock test it sits beside, so the poll stays what it was.

    Answers False on ANY error. A marker that cannot be read is a marker that is not there, and being
    not-there only costs the pre-existing behaviour."""
    try:
        path = _land_supersession_marker_path(main_wt, branch) if main_wt is not None else None
        return bool(path is not None and path.exists())
    except Exception:                  # noqa: BLE001 — unreadable == unmarked (see docstring)
        return False

def _land_supersession_marked_branches(main_wt: "Path | None",
                                       branches, *, _land_supersession_marked=None) -> "set[str]":
    """T-11276 (SPEC-0184 rule 8) — of `branches`, the ones whose supersession MARK is set.

    WHY FORMATION ASKS AT ALL, when rule 8's marker already exists for the park path. The mark says
    a batch head's fast-forward already carried that branch's content. Such a branch has nothing to
    integrate, so taking it as a batch CANDIDATE spends a place in `BATCH_MAX` on a member that can
    contribute nothing — the fossil candidate pool measured five times on 2026-08-18 (depth stuck at
    6 while the live queue was 0). This is the same question rule 8 already answers, asked one step
    EARLIER: not "should this land stop paying?" but "is this a candidate at all?".

    PEER SIDE ONLY, and that bound is the rule, not an omission (controller resolution 2026-08-18).
    A marked HEAD is handled UPSTREAM by T-11274 and never reaches formation: a genuinely superseded
    land exits at the park site (`superseded_park_exit`) before it takes the reservation. Where
    T-11274 deliberately FAILS CLOSED — an observable tree delta, or a content oracle that cannot
    answer — the marker is OVERRIDDEN, the land re-takes the reservation and proceeds carrying REAL
    content; narrowing that head to a batch of one would cost a pass for nothing. So there is no
    marked head for formation to exclude, by construction, and this reader answers only the peers.

    READ-ONLY: `_land_supersession_marked` is the existence test, and
    `_land_consume_supersession_marker` is deliberately NOT called here. Consuming is the PARK path's
    act — the marker is that member's own single-use hint, and unlinking it at formation would
    destroy the evidence the member's parked land is about to read, converting a saved verify into a
    paid one. Formation reads; the park path consumes.

    THE COST CLASS IS THE MARKER'S OWN (SPEC-0184 rule 8): ONE `exists()` per candidate, no journal
    parse, and the candidate list is already capped by the queue read. Formation runs once per
    slot-free moment, not per poll, so this is affordable exactly as the card's BOUND requires.

    FAIL-OPEN TO THE EMPTY SET, always — a None `main_wt`, an unreadable sidecar, any error at all
    yields "nobody is marked", i.e. ordinary formation. Same direction, and for the same reason, as
    `_land_batch_ineligible_branches` / `_land_rebaselining_branches` /
    `_land_pinned_supersession_branches`: a missed exclusion costs ONE repeated batch, while a
    spurious one would shrink batches on bad data."""
    if main_wt is None:
        return set()
    out: "set[str]" = set()
    for br in branches or ():
        br = str(br or "").strip()
        if not br:
            continue
        try:
            if _land_supersession_marked(main_wt, br):
                out.add(br)
        except Exception:              # noqa: BLE001 — unreadable == unmarked (fail-open)
            continue
    return out

def _land_supersession_marker_path(main_wt: Path, branch: "str | None", *, _verify_slot_dir=None) -> "Path | None":
    """SPEC-0184 rule 8 — the per-BRANCH supersession marker a batch head writes for each member whose
    content its fast-forward carried, and which that member's own parked land reads.

    Lives in the SAME off-tree, realpath-keyed sidecar as the land reservation flock and the SPEC-0132
    verify slots: never in the working tree, never committed, and auto-scoped to ONE repo. It is a
    SUBDIRECTORY (`superseded/`) rather than a sibling filename so it can never be confused with a slot —
    the slot pool opens `slot-{i}` by exact name and globs nothing, and the reservation is a single file.

    THE NAME IS A HASH OF THE BRANCH, and that is not incidental. A branch name contains `/`
    (`task/T-11274`, `work/close-t11270-wont-do`), so any filename-derived scheme needs a sanitisation
    rule — and a sanitisation rule is a place for two different branches to collide. Hashing removes the
    question. It also keeps the mechanism BY BRANCH: a task-keyed marker would have left 7 of the 16
    measured members (the `work/` ones) uncovered, i.e. nearly half the population.

    Returns None for an empty/absent branch — the caller then simply has no marker to read or write,
    which is the same no-op as a marker that is not there."""
    br = (branch or "").strip()
    if not br:
        return None
    import hashlib
    return _verify_slot_dir(main_wt) / "superseded" / hashlib.sha1(br.encode("utf-8")).hexdigest()[:16]

def _land_supersession_probe_fired(superseded_probe, superseded_out) -> bool:
    """SPEC-0184 rule 8 — run a park loop's optional supersession probe ONCE, and record the hit.

    ONE helper for both park sites, so the two loops cannot drift into asking the question differently
    (the sibling `_land_reservation_held_by_self` shape). No probe ⇒ False without any work, which is
    what keeps `superseded_probe=None` byte-identical for every existing caller and test.

    NEVER RAISES, and answers False on any error. A probe that throws is a probe that did not answer,
    and a park loop is the last place that may fail a land: not-answered means park exactly as before.
    The hit is appended to `superseded_out` rather than returned as a second value, because both loops
    already have a return contract (`fd | None`, `bool`) that a supersession would otherwise have to
    overload — and overloading it is how a supersession would get read as a degradation."""
    if superseded_probe is None:
        return False
    try:
        if not superseded_probe():
            return False
    except Exception:                  # noqa: BLE001 — did not answer ⇒ park as before
        return False
    if superseded_out is not None:
        superseded_out.append(True)
    return True

def _land_pid_is_live(pid: int) -> bool:
    """T-12413 — does `pid` name a process that EXISTS? One `os.kill(pid, 0)`, errno-discriminated.

    EPERM IS LIVE, AND THAT IS NOT A DETAIL. POSIX gives `kill(pid, 0)` exactly one errno that proves
    ABSENCE — ESRCH (`ProcessLookupError`). EPERM (`PermissionError`) is the kernel answering «that
    process exists and you may not signal it», which is what a land running under a DIFFERENT UID on
    this host looks like. Collapsing the two into a bare `except OSError` would read such an addressee
    as dead, suppress the offer it is entitled to, and quietly return that handover to the
    arrival-order lottery T-11279 replaced (audit-pre finding, 2026-09-11, medium).

    WHY THE TWO READER FENCES KEEP THEIR BARE `except OSError` AND THIS DOES NOT — the asymmetry is
    deliberate, not an inconsistency left behind. On the READ side (`_land_yield_offer_blocks`) a
    wrong «dead» only fails OPEN: the offer stops fencing and the repo costs exactly its pre-offer
    behaviour. On the WRITE side a wrong «dead» SUPPRESSES the handover outright. The two sides
    therefore owe opposite care about an unproven errno, and only the write side is this card's
    subject.

    ANYTHING ELSE IS FALSE. An errno neither ESRCH nor EPERM is unproven, and an unproven handle may
    not be published as a promise that somebody will come for the slot."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:         # ESRCH — the ONLY errno that proves absence
        return False
    except PermissionError:            # EPERM — it EXISTS; we merely may not signal it
        return True
    except OSError:                    # unproven — never published as live
        return False
    return True

def _land_write_yield_offer(main_wt: "Path | None", branch: "str | None", *, addressee_pid=None,
                            _land_yield_offer_path=None) -> bool:
    """Publish «the reservation is offered to <branch>», stamped with THIS process id.

    BEST-EFFORT, exactly like `_land_mark_superseded`, and for the same asymmetry: an offer that fails
    to appear costs exactly today's behaviour (an unaddressed race), while nothing about it may fail a
    land. The writer pid is what later makes the offer self-cleaning — see `_land_yield_offer_blocks`.

    T-11878 — THE OPTIONAL THIRD LINE IS THE ADDRESSEE'S OWN LAND PID, and recording it here is the
    whole of that card's design. An offer is consumable ONLY by the addressed branch's live land
    process (`_land_consume_yield_offer`, never the writer), so the condition that makes an offer
    permanently unconsumable is «no live land will come for it» — a question neither shipped fence
    asks. It cannot be asked on the 0.1s poll tick, where a journal read and a subprocess are both
    refused by the cost-class contract (`_land_addressee_gone`; SPEC-0184 rule 9). It CAN be asked
    here for free: the writer picked this addressee out of the queue read, and the same `waiting_for_*`
    rows that queue is folded from already carry the queued land's pid (`_land_queue_member_facts`).
    Stamping it turns the missing check into one more `os.kill(pid, 0)` — the identical syscall and
    cost class as the writer fence beside it.

    T-12413 — AN OFFER IS PUBLISHED ONLY WHEN IT CAN BE PROVEN CONSUMABLE, and that is this card's
    whole claim. T-11878 made the READER able to expire an offer whose addressee land had DIED; it
    left untouched the case where that land had NEVER STARTED. Measured 2026-09-11 13:33Z-14:50Z
    (fingerprint `yield-offer-addressee-land-not-started-parks-fleet`): 17 lands parked on
    `waiting_for_land_reservation` — 4706 heartbeat rows in three hours — with the reservation flock
    UNHELD. The offer named `task/T-12378`, whose worker was ALIVE but in Stage 6: its land had not
    begun, so the wait rows carried no pid, so the offer went out with NO third line, so the T-11878
    fence read UNKNOWN and fell through. Both shipped fences answered correctly and neither fired —
    the writer was alive and parked, the addressee branch existed — and consumption belongs to the
    addressee's live land ALONE (`_land_consume_yield_offer`), so no process in existence could ever
    take the file away. It came off by HAND at 14:50Z.

    So the fix is on the WRITE side, where the question is FREE and has a real answer: the writer
    picked this addressee out of its own queue read, and if that read cannot name a LIVE land pid,
    there is nobody to hand the slot to and NOTHING IS RECORDED (returns False, no file touched). The
    yielder then simply takes the reservation back on its own `retake()` — an unaddressed round,
    which is the pre-T-11279 behaviour for a peer that cannot be named, and strictly better than
    publishing a park nobody can end.

    ABSENT IS STILL UNKNOWN — ON THE READ SIDE, WHICH IS WHERE THAT RULE ALWAYS BELONGED. A two-line
    offer already on disk (written by a pre-T-12413 binary, in flight across the upgrade) still reads
    as NOT-PROVEN in `_land_yield_offer_blocks` and still fences, exactly as before: a reader that
    took absence for death would switch the addressed handover off repo-wide. What changes is only
    that this function no longer CREATES one, so the shape it writes is always T-11878's three-line
    form.

    NO TIMEOUT, TTL, COUNTER OR TUNABLE — one `os.kill(pid, 0)` via `_land_pid_is_live`, the identical
    syscall and cost class as the two fences beside it, asked at the one moment the handle is already
    in hand. The same liveness derivation the three sibling fences are built on, moved to the write
    side."""
    br = (branch or "").strip()
    path = _land_yield_offer_path(main_wt)
    if not br or path is None:
        return False
    try:
        apid = int(addressee_pid) if addressee_pid is not None else None
    except (TypeError, ValueError):    # an unreadable handle is no handle — record nothing
        apid = None
    if apid is not None and apid <= 0:
        apid = None
    if apid is None or not _land_pid_is_live(apid):
        return False                   # T-12413 — nobody is coming for it, so it is not published
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{br}\n{os.getpid()}\n{apid}\n", encoding="utf-8")
        return True
    except Exception:                  # noqa: BLE001 — an offer never fails a land (see docstring)
        return False

def _land_yield_loop(*, target, release, retake, holding, offer=None, withdraw=None,
                     yielded_out=None, offered=None) -> int:
    """SPEC-0184 rule 9 — THE YIELD LOOP ITSELF, module-level so a test can drive the SHIPPED code
    rather than a re-implementation of it (audit-post finding, 2026-08-18: the mutual-yield fixture
    AC4 requires cannot exist while the loop is inlined in `_land_integrate`, and a fixture that
    re-writes the loop measures the fixture — `lessons/a-measurement-taken-outside-its-harness-
    measures-the-harness.md`). Returns how many times the reservation was handed over.

    Four injected seams and no state of its own: `target(offered)` names the branch to yield to (or
    None), `release()` gives the reservation up, `retake()` re-contends through the ONE fairness
    dispatch, `holding()` says whether we hold it.

    THE MIDDLE READ IS TAKEN WHILE HOLDING NOTHING, and that is the whole mechanism. The yielder is
    never made to WAIT — no back-off, no skipped tick (owner amendment 1's prescription is withdrawn)
    — it is only made to stop HOLDING while it thinks, and that unlocked interval IS the window a
    peer polling every `_LAND_RESERVATION_POLL_SEC` can take the slot in.

    TERMINATION IS THE CANDIDATE SET, NOT A COUNTER — and it is LOAD-BEARING, which is not what the
    founding directive assumed. Each candidate is offered the slot at most once (`offered`), so a peer
    that is queued but never contends cannot hold this loop in a release/re-take spin; the bound is
    the FINITE queue the read already produces, and it names no number.

    MEASURED (2026-08-18, deviation `t11275-park-limit-does-not-terminate-mutual-yield`): the
    land-reservation PARK LIMIT does NOT terminate a mutual yield, though T-11275's directive said it
    would. That limit bounds a contender WAITING on a reservation somebody else HOLDS, and a mutual
    yield never waits — each side releases and re-acquires within microseconds, so the limit is never
    approached. Two real contenders with this bookkeeping disabled run forever
    (`test_t11275_ac4_the_mutual_yield_fixture_terminates_through_the_existing_park_limit`, leg 2).
    The conclusion is unchanged and now rests on something true: no livelock ships — the shipped
    ranking is a strict order, so a mutual yield is unreachable to begin with, and offer-once closes
    the residual spin — and no counter, cap or number was added. The park limit is still the bound on
    a contender parked behind a genuinely held reservation (T-11117); it is simply not this one.

    THE CANDIDATE SET MAY BE OWNED BY THE CALLER (`offered`, T-11304), and that is what lets the
    question be asked more than ONCE per attempt without the bound this rule refuses to add. The
    holder re-asks after its pre-verify integrate, so a branch that queued during the merge, the
    journal fold and the graph rebuild becomes eligible — but a candidate that is queued and never
    contends must not be re-offered on every round, or the redo loop above this one would not
    terminate. Passing ONE set through every evaluation of an attempt keeps offer-once meaning
    once-per-ATTEMPT rather than once-per-CALL, so each round consumes at least one previously
    unoffered branch from a FINITE queue read and the rounds stop by themselves. Omitted (`None`)
    the loop owns a fresh set, which is byte-identical to the pre-T-11304 behaviour for every other
    caller and every fixture."""
    offered = set() if offered is None else offered
    yields = 0
    yt = target(offered)
    while yt is not None and holding():
        offered.add(yt)                    # recorded BEFORE the release — no window to re-select in
        if offer is not None:
            offer(yt)                      # T-11279 — publish the ADDRESS before letting go, so the
                                           # window opens already spoken for rather than as a lottery
        if yielded_out is not None:
            yielded_out.append(yt)         # T-11279 AC4 — WHO, not just how many
        release()
        yields += 1
        yt = target(offered)               # decided UNLOCKED — see the docstring
        retake()                           # re-contend; PARKS if a peer took it meanwhile — and while
                                           # OUR offer stands we abstain too, bounded by the existing
                                           # park limit (`_land_yield_offer_blocks`)
        if withdraw is not None:
            withdraw()                     # T-11279 — our window is over, however it ended
        if not holding():
            break                          # degraded (or superseded) — the dispatch owns that path
    if withdraw is not None:
        withdraw()                         # belt: never leave an offer behind on any exit path
    return yields

def _land_yield_offer_blocks(main_wt: "Path | None", self_branch: "str | None", *, _land_addressee_gone=None, _land_read_yield_offer=None) -> bool:
    """Must THIS land abstain from taking the reservation on this poll tick?

    True ONLY when a LIVE offer names somebody else. FIVE fail-open exits, each costing exactly the
    pre-change behaviour: no offer, an unreadable offer, an offer whose WRITER is gone, an offer whose
    addressee BRANCH is gone, or an offer whose addressee's LAND is gone.

    THE ADDRESSEE-LIVENESS FENCE (T-11490) closes a deadlock every other rule here is individually
    right about. A LANDED addressee is strictly WORSE than a dead writer: its offer stays LIVE by the
    writer rule (the yielder is alive and parked), and it is UNCONSUMABLE by the consumption rule
    (`_land_consume_yield_offer` belongs to the addressed branch and never to the writer, deliberately
    — a writer-side consume would destroy the handover evidence), while the yielder is deliberately not
    exempt from its own offer, so it parks too. Measured 2026-08-24 03:10Z: an offer naming a branch
    that had already landed parked three live lands for 26 minutes with the reservation flock UNHELD
    and all four verify slots free, indistinguishable from ordinary contention. It self-healed only
    after twenty full park walls (T-11117) — the wrong instrument for a condition decidable in one
    branch-existence check. Like the writer check this is a LIVENESS derivation, not a timeout: it adds
    no bound, number or tunable, and it fires only on PROOF the branch is gone (`_land_addressee_gone`).

    THE ADDRESSEE-LAND-LIVENESS FENCE (T-11878) closes the THIRD hole, and it is a different hole from
    the two above rather than a recurrence of either. Measured 2026-08-30: no land in this repo
    completed between 05:45:51Z and a recovery ~2h later while six or more sat parked, on ONE offer
    written 05:44Z naming branch task/T-11842 (diagnosis with the full derivation:
    `events.jsonl#ts=2026-08-30T07:35:02Z`). Both shipped fences answered CORRECTLY and neither fired:
    the WRITER was alive and parked in its own poll loop, and the addressee's BRANCH existed with its
    worktree. What was dead was the addressee's LAND — its worker had halted `blocked-on-land` at
    05:43:17Z and no process survived it — and consumption belongs to the addressed branch's live land
    ALONE. So the offer was live, unconsumable and PERMANENT, and the symptom is the one the fence
    above already warns is indistinguishable from contention: the reservation flock UNHELD, all four
    verify slots free, zero pytest processes, every parked land burning about a minute of CPU across
    one to two hours asleep in `hrtimer_nanosleep`. It recovered only when the addressee's own
    `worktree recover-land` made the mechanism consume its own offer.

    THE HANDLE IS RECORDED, NOT DERIVED, and that is what keeps this in the same cost class as the two
    fences beside it. The addressee's land has no ambient handle to probe; deriving one on the poll
    tick would need the journal (`_land_queue_member_facts`) or git, both refused here by
    `_land_addressee_gone`'s cost-class contract and by SPEC-0184 rule 9's «never a journal read». So
    the WRITER records it at offer time, where the queue read it selected the addressee from has the
    pid already folded (`_land_write_yield_offer`), and this becomes one more `os.kill(pid, 0)` —
    literally the writer fence's own syscall asked about the other party. A LIVENESS derivation, not a
    timeout: no bound, number, threshold or tunable, and it fires only on PROOF.

    AN OFFER THAT RECORDS NO ADDRESSEE PID IS NOT SILENTLY FAILED OPEN — it is UNKNOWN, and the check
    is simply not asked. That is the whole difference between closing this hole and deleting the
    fair-queueing the offer exists to provide: a blanket fail-open would pass the deadlock test and
    return the repo to the arrival-order lottery T-11279 replaced.

    THE WRITER-LIVENESS FENCE is what stops an addressed offer from becoming hostage-taking: a yielder
    that dies between publishing the offer and withdrawing it leaves the file behind, and a file nobody
    will ever withdraw would park the whole repo. One `os.kill(pid, 0)` — the same cost class as the
    `exists()` beside it, never a journal read — makes the offer die with its author. It is a LIVENESS
    derivation, not a timeout, so it adds no bound, number or tunable.

    THE YIELDER IS NOT EXEMPT FROM ITS OWN OFFER, and that is the correction the 2026-08-19 audit-pre
    forced (RED, high). Exempting it let the yielder release and instantly re-take, so the addressee
    still missed the very millisecond window this mechanism exists to hand it, and the whole thing
    collapsed back into the lottery it replaces. The yielder therefore abstains like everyone else, and
    its abstention is bounded by the EXISTING land-reservation park limit (T-11117) whose degrade path
    withdraws the offer — the surviving option of the 2026-08-19 ceiling-convergence consult, and the
    reason this card added no new bound of its own."""
    offer = _land_read_yield_offer(main_wt)
    if offer is None:
        return False
    br, pid, addressee_pid = offer
    if br == (self_branch or "").strip():
        return False                   # we ARE the addressee — take it, then consume it
    try:
        os.kill(pid, 0)
    except OSError:
        return False                   # the author is gone — the offer dies with it
    if addressee_pid is not None:
        try:
            os.kill(addressee_pid, 0)
        except OSError:
            return False               # T-11878 — the addressee's LAND is gone; nobody is left to
                                       # consume this offer, and consumption is its act alone
    if _land_addressee_gone(main_wt, br):
        return False                   # the addressee is gone — nobody is left to consume it
    return True

def _land_yield_offer_path(main_wt: "Path | None", *, _verify_slot_dir=None) -> "Path | None":
    """The single off-tree offer file, or None when there is no repo to key it to."""
    if main_wt is None:
        return None
    try:
        return _verify_slot_dir(main_wt) / _LAND_YIELD_OFFER_NAME
    except Exception:                  # noqa: BLE001 — an unresolvable sidecar simply has no offer
        return None

def _land_yield_target(self_class: "int | None", queue, *, _marked, _class_of,
                       already_yielded=None, _jump=None, self_jump: bool = False,
                       _jump_reasons=None) -> "str | None":
    """SPEC-0184 rule 9 — the branch this land should yield the reservation TO, or None.

    The FIRST queued branch (queue order IS wait order) that is (a) NOT supersession-marked and
    (b) of a KNOWN class STRICTLY below ours.

    THE MARK IS TESTED FIRST, and that ordering is the owner's second directive, not an
    optimisation: a branch whose T-11274 supersession mark is set has nothing to integrate and would
    take the slot only to exit, so it must never be ranked at all, let alone won by. The read is
    read-ONLY — consuming a peer's marker here would destroy the evidence that peer is parked waiting
    to read (consumption is the marked branch's own act, `_land_consume_supersession_marker`).

    STRICTLY cheaper, never equal: an equal-class peer is not an improvement, and yielding to one
    would make every quiet repo pay a handover for nothing (AC3's byte-identical complement).

    TERMINATION IS THE CANDIDATE SET, NOT A COUNTER (AC4 — the no-new-bound directive forbids a
    deferral counter or a yield cap, and this is neither). `already_yielded` is the set of branches
    this land has ALREADY handed the slot to on this attempt; they are skipped. Re-evaluating on each
    re-acquisition is amendment 2's own model — a yielder that re-takes the slot and sees a NEW
    cheaper candidate yields again — but a candidate that is queued and never contends must not be
    able to hold the yielder in a release/re-take spin forever. Skipping the already-offered ones
    keeps the re-evaluation and makes the loop terminate on the FINITE queue the read already bounds.
    Mutual yielding remains terminated by the EXISTING land-reservation park limit; nothing here adds
    a second bound.

    T-11663 — THE EMERGENCY PASS, and it is ORDER OF SERVICE ONLY. `_jump(branch)` answers the live
    queue-jump reason a queued card declares (`state.queue_jump_reason`, expiry included). A branch it
    names is served ahead of the PAYING cost classes — that is the whole of the feature: a card that
    FIXES the queue no longer waits behind the congestion it removes (measured 2026-08-26 — T-11544
    blocked while three batches of four dissolved; task/T-11525 overtaken by nine later arrivals
    across 56 minutes, because a dissolved member re-enters with its `waited_s` reset). Nothing about
    batch MEMBERSHIP is touched here: this function has never decided who batches with whom, and it
    still does not.

    T-11706 — THE MARK YIELDS TO A BOOKKEEPING LAND, AND OVERTAKES ONLY PAYING ONES (owner directive
    2026-08-27). The pass once won the scan OUTRIGHT, ahead of EVERY cost class including rung 0. It
    now ranks BETWEEN them: **rung-0 < marked < paying**. Two terms carry it, both inside the ONE
    existing gate and both reading the rank this function was already handed:
      * a rung-0 CANDIDATE is scanned FIRST, so a marked branch does not overtake a land that runs no
        suite at all. Letting one through costs the jumper a fraction of a paying land's wall — it
        gives up seconds, never a verify — while overtaking a PAYING land is where the emergency place
        actually buys something, and that half is UNCHANGED;
      * a rung-0 HOLDER (`self_class == 0`) does not enter the pass at all, for the same reason read
        from the other side: yielding its slot to a paying marked branch would put a bookkeeping land
        behind exactly the wall this narrowing exists to spare it.
    The paying/non-paying distinction is `_land_cost_class`'s own rung 0 ("this member's own land
    would not run the suite") — the SAME answer `_land_batch_paying_members` counts. No second
    predicate, no new field and no new store: a parallel encoding is what CHARTER §P1 forbids.
    WHERE THE PAYOFF LIVES, so its near-absence here is not read as failure: bookkeeping lands are 0
    of 294 batch members in the kernel and 173 of 293 (59%) in the kupiclub consumer (both folded
    read-only from the respective journals, 2026-08-27). This is nearly inert in the kernel and is the
    majority case on a consumer.

    EVERY RULE-9 INVARIANT SURVIVES LITERALLY, which is why the pass sits INSIDE the existing entry
    conditions rather than above them:
      * the supersession mark is still tested FIRST — a branch with nothing to integrate is never
        ranked, jump or no jump (owner directive 2, unchanged);
      * `already_yielded` still applies, so offer-once-per-attempt still bounds the loop on the FINITE
        queue and no counter, cap or timer is added;
      * an UNDECIDABLE holder (`self_class is None`) still yields to nobody;
      * and A JUMPER DOES NOT YIELD TO A JUMPER (`self_jump`). That clause is load-bearing, not
        caution: the ranking's termination argument is that a STRICT order cannot hold A<B and B<A, so
        making the mark a rank below the PAYING classes is safe only while marked branches are EQUAL to
        each other — «strictly cheaper, never equal» is the same clause the cost ladder already
        enforces. Without it two marked cards could hand the slot back and forth across attempts.
        T-11706 narrowed the rank from «below every cost class» to «below the paying classes only»,
        and rung-0 < marked < paying is STILL a strict order — but only because BOTH halves of the
        narrowing shipped: the rung-0 holder is excluded from the pass, so marked < rung-0 can never
        hold alongside rung-0 < marked. That exclusion is the termination argument, not a nicety.
    `_jump=None` (every pre-change caller and every existing fixture) skips the pass entirely, so the
    function is byte-identical without it.

    THIS FUNCTION STAYS PURE, AND THAT IS WHY IT DOES NOT EMIT (audit-post finding, high, 2026-08-26).
    A SELECTION IS NOT A HANDOVER. This is a ranking selector: the loop above it calls it again after
    each release, and may then not hand anything over at all (it stops when it no longer holds the
    reservation). An emit here would journal a firing for a handover that never happened — turning
    safeguard (c) from a reading of real reorderings into a count of times the ranking THOUGHT about
    one, which is exactly the noise the safeguard exists to be free of. So the reason is only
    RECORDED, into the caller-owned `_jump_reasons` map, and the caller emits from the seam where the
    handover was ACTUALLY performed (the addresses `_land_yield_loop` reports through `yielded_out`)."""
    if self_class is None:
        return None
    seen = already_yielded or ()
    # T-11706 — `self_class is not None` is written out even though the guard above already returned
    # on it: the gate then reads correctly on its own line instead of depending on a statement eleven
    # lines up (audit-pre finding, high, absorbed 2026-08-27). `self_class > 0` is the rung-0 HOLDER
    # exclusion — see the docstring; it is the half of the narrowing that keeps the order STRICT.
    if _jump is not None and not self_jump and self_class is not None and self_class > 0:
        for br in queue or ():           # T-11706 — rung-0 outranks the mark, so it is scanned FIRST
            b = str(br or "").strip()
            if not b or b in seen:
                continue
            if _marked(b):               # owner directive 2 — unchanged, and it still comes first
                continue
            if _class_of(b) == 0:        # the SAME non-paying answer `paying_members` counts
                return b
        for br in queue or ():
            b = str(br or "").strip()
            if not b or b in seen:
                continue
            if _marked(b):               # owner directive 2 — unchanged, and it still comes first
                continue
            reason = _jump(b)
            if reason:
                if _jump_reasons is not None:
                    _jump_reasons[b] = reason      # recorded, never emitted — see the docstring
                return b
    for br in queue or ():
        b = str(br or "").strip()
        if not b or b in seen:
            continue
        if _marked(b):                       # owner directive 2 — tested BEFORE the class comparison
            continue
        c = _class_of(b)
        if c is not None and c < self_class:
            return b
    return None

def _pinned_baseline_identity(W: Path, merged_base: str, *, _run_git_cap, _pinned_baseline_parts=None) -> "dict | None":
    """T-11517 — the PINNED LAST-GREEN BASELINE IN FORCE, as a fact a formation row can carry.

    RECOVERABLE, NOT MERELY COMPARABLE (audit-pre finding, absorbed). Returns BOTH:
      * `id`    — `pb-` + the first 16 hex of the sha256 over the baseline parts. Cheap equality:
                  two batches judged against the same baseline carry the same id.
      * `parts` — the parts THEMSELVES, `{name: value}` (`bin`, `tests`, the consumer ops contract,
                  each declared check path, `engine`, `py`). A digest alone would let a reader say
                  THAT two batches were judged differently but never WHICH surface moved, which is
                  precisely the question a rebaseline post-mortem asks.

    NO NEW IDENTIFIER SCHEME (the card's constraint): every value here is one the pinned machinery
    already computes for its own cache key — git object ids at `merged_base`, the running-engine
    code hash, the interpreter version. Two of those are NOT in git, which is also why this is not
    derivable from the recorded `base` commit and therefore earns its own field under the
    record-what-becomes-unrecoverable rule.

    None on any failure — an ABSENT id is visible in the row; a wrong one would not be."""
    try:
        parts = _pinned_baseline_parts(W, merged_base, _run_git_cap=_run_git_cap)
    except Exception:
        return None
    if not parts:
        return None
    import hashlib
    return {"id": "pb-" + hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16],
            "parts": dict(p.split("=", 1) for p in parts)}

def _probe_resolved_tree(conflict_tree: str, resolved: dict, stages: dict, main_wt: Path, *,
                         _run_git_cap, _dedup_events) -> "str | None":
    """The RESOLVED tree for a merge whose every conflict the land path would resolve — or None.

    WHY THIS EXISTS AT ALL, rather than reusing the conflict-marked tree `merge-tree` returned
    (audit-pre finding, 2026-08-17 — a shortcut this card proposed and the external auditor killed).
    Admitting a member means the ACCUMULATOR carries it into the next member's probe. Advance with a
    conflict-MARKED tree and a LATER member that merges cleanly against `main` can conflict against
    the markers — for a spec record the marked YAML no longer parses, so the keyed resolver refuses
    and the member is evicted. That is a member the PRE-CHANGE probe would have KEPT: a regression,
    not a bounded loss, and precisely the class of false eviction this card exists to remove. So
    admission REQUIRES building the resolved tree, and the invariant is absolute rather than
    bounded: THE ACCUMULATOR NEVER CONTAINS A CONFLICT MARKER. Any failure here returns None and the
    member is evicted — today's verdict — so the fail-closed direction is toward the old behaviour,
    never toward a silent admission.

    STILL NOTHING IS CHECKED OUT AND NO REF MOVES, which is what keeps rule 3 safe to run before
    anyone has agreed to land. The composition happens in a THROWAWAY `GIT_INDEX_FILE` under a
    tempdir — the real index, the working tree and every ref are untouched — and the only durable
    side-effect is unreferenced objects, the same class the surrounding `commit-tree` already writes.

    The resolutions are the classifier's own, applied exactly as `_update_from_main` applies them:
      • `ours`    — derived artifacts + take-latest `.yitc/` state: the stage-2 oid is reused
                    VERBATIM. No bytes are invented and nothing is re-serialized.
      • `text`    — the keyed 3-way merge the resolver already computed and returned.
      • `journal` — the union of stages 2 and 3 through the SAME `_dedup_events` the land path uses,
                    so no journal row is dropped.
    """
    import subprocess
    import tempfile
    if not conflict_tree or _dedup_events is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="yitc-land-probe-") as td:
            index = Path(td) / "index"
            env = {**os.environ, "GIT_INDEX_FILE": str(index)}
            if _run_git_cap(["read-tree", conflict_tree], main_wt, env=env).returncode != 0:
                return None
            for path, (kind, payload) in resolved.items():
                if kind == "ours":
                    oid = (stages.get(path) or {}).get(2)
                    if not oid:
                        return None          # no ours-side blob to take: not resolvable here
                else:
                    if kind == "journal":
                        rows: list = []
                        for stage in (2, 3):
                            blob = (stages.get(path) or {}).get(stage)
                            if not blob:
                                continue
                            r = _run_git_cap(["cat-file", "blob", blob], main_wt)
                            if r.returncode != 0:
                                return None
                            rows += (r.stdout or "").splitlines()
                        text = "".join(ln + "\n" for ln in _dedup_events(rows))
                    else:
                        text = payload
                    if text is None:
                        return None
                    src = Path(td) / "blob"
                    src.write_text(text, encoding="utf-8")
                    # `--path` so any attribute-driven filter git would apply to the real path applies
                    # here too — the blob must be the one the real merge would have written.
                    h = _run_git_cap(["hash-object", "-w", "--path", path, str(src)], main_wt)
                    oid = (h.stdout or "").strip()
                    if h.returncode != 0 or not re.fullmatch(r"[0-9a-f]{7,64}", oid or ""):
                        return None
                if _run_git_cap(["update-index", "--add", "--cacheinfo", f"100644,{oid},{path}"],
                                main_wt, env=env).returncode != 0:
                    return None
            w = _run_git_cap(["write-tree"], main_wt, env=env)
            out = (w.stdout or "").strip()
            return out if w.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", out or "") else None
    except TypeError:
        # An injected `_run_git_cap` that does not accept `env` cannot compose the tree. Refusing is
        # the honest answer: without a faithful accumulator there is no admission to be had.
        return None
    except (OSError, subprocess.SubprocessError):
        return None

def _rev_journal_types(rev: str, candidates, main_wt: Path, *, _run_git_cap) -> set:
    """T-11395 — which of `candidates` had a live row in the journal AT `rev`.

    The same shape as the in-verify gate's `base_live_types`: the substring test is only a PREFILTER
    (a row with `type == t` must contain `t` literally) and every prefiltered line is json-parsed and
    confirmed, so no line-format assumption is made. An empty candidate set does no work at all, which
    is the ordinary case. Returns set() on any failure — the CALLER's fail-open direction reads that
    as "nothing was uncatalogued at the base", which is the STRICT side; it is reachable only when the
    branch already carries an otherwise-uncatalogued added type, i.e. when the verify would fail it
    too unless the base carried it as well.

    Streamed, because this repo's journal is ~177MB: `git show` into a pipe, abandoned as soon as
    every candidate is found."""
    candidates = set(candidates)
    if not candidates:
        return set()
    found: set = set()
    import subprocess
    # T-11444 / SPEC-0190 rule 4b — the GIT-REVISION reader class. This reader never touches the
    # shared iterator, so making that iterator segment-aware does not reach it: at a post-rotation
    # revision `<rev>:events.jsonl` is the LIVE SEGMENT ALONE and this would read a truncated journal
    # while looking entirely healthy. Enumerate the segments present AT that revision and stream each.
    # Pre-rotation the enumeration yields exactly `["events.jsonl"]` — unchanged, and the early exit
    # below still abandons the read as soon as every candidate is found.
    # T-11805 — ONE git process for the whole fold where that is safe, instead of one fork per
    # segment. Same segments, same fold order, same bytes, and the early exit below is UNCHANGED:
    # the stream is still abandoned the moment every candidate is found.
    for _argv in journal_mod.revision_segment_show_argvs(rev, main_wt):
        if found == candidates:
            break
        proc = subprocess.Popen(["git", "-C", str(main_wt), *_argv],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                errors="ignore")
        try:
            for line in proc.stdout:
                if found == candidates:
                    break
                hits = [c for c in candidates - found if c in line]
                if not hits:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("type") in hits:
                    found.add(obj["type"])
        finally:
            with contextlib.suppress(Exception):
                proc.stdout.close()
                proc.kill()
                proc.wait()
    return found
