"""Inspection (ревизия) verb-family for the yitc-v2 CLI — `inspect record` (the thin run-recorder
that emits one `inspection_completed` event per theme run, SPEC-0057 §6 / SPEC-0025 / X-0127, T-9640).

WHY THIS EXISTS: before T-9640 a theme run's `inspection_completed` event was HAND-emitted via the
raw `event` verb with a hand-TYPED `criteria_ref` string — a faked ref defeats the run-mode
checklist-hash freshness idea (re-run a theme when its lens-checklist edits) and a hand-emit is easy
to malform/skip. This verb is the governed emitter (D-0050 — verbs are the control surface): it
computes a REAL checklist-hash `criteria_ref` from the theme's living lens-checklist section in
`patterns/inspection-criteria-roster.md`, so editing that checklist changes the hash and a stale
theme run is detectable. MANUAL-FIRST is preserved (SPEC-0057 §2): the verb is owner-invoked, there is
NO cron / scheduler / register-file — running it by hand IS the cadence.

Identity-agnostic KERNEL module (SPEC-0073 bin/ class-default — bin/ code TRAVELS with the engine; the
inspection construct is engine methodology a consumer pins, SPEC-0057 §9). It imports only stdlib and
NEVER back-imports the host; the host keeps the thin argparse residue + injects the path globals +
collaborators (the triage.py / spec.py precedent), so a `-C` REPO_ROOT rebind stays honored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re

# The fixed theme roster (SPEC-0057 §3 — small, fixed, owner-gated T1–T10). Validated at the verb so a
# typo'd theme is refused rather than emitting a run-event for a non-theme. T10 (real-work observation
# loop, SPEC-0135) was the owner-gated 10th theme (T-10125); the roster stays small/fixed/owner-gated.
THEMES = tuple(f"T{n}" for n in range(1, 11))

# The consumer project-ops carrier (SPEC-0093). Its `inspection.themes[]` (rule 12) declares the
# CONSUMER-LOCAL themes a project grows ON TOP of the kernel T1–T10 roster — the source of truth for
# the `--theme <declared-slug>` relaxation (T-10235 / plan K2, surfaced by trial DP-A). Under a `-C`
# consumer session REPO_ROOT is the consumer, so REPO_ROOT / OPS_YAML_REL resolves the consumer's own
# carrier; the engine's own repo has no yitc-ops.yaml, so a declared-theme lookup there simply misses.
OPS_YAML_REL = "yitc-ops.yaml"

# ── Durable-doc governance probe (SPEC-0120, T-9775) — report-only, NEVER a gate ──────────────
# The T7 revizia carries per-doc SIZE + LANGUAGE metrics over the SPEC-0120 §1 durable-doc set.
# Two REPORT-ONLY axes (CHARTER non-goal #2 — a color/gate is forbidden; this only measures):
#   • SIZE (§3) — the 400–500-line target BAND. over-band = >500 = split CANDIDATE (never a fail);
#     over-ceiling = >=800 = must-split (beyond one bounded read ~25K-token page). The two counts
#     are reported SEPARATELY (§3) as DISJOINT buckets: over_band = (500, 800), over_ceiling = >=800.
#   • LANGUAGE (§2) — a mechanical Cyrillic scan; per-doc count of Cyrillic-bearing lines.
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
OVER_BAND_LINES = 500       # SPEC-0120 §3 — over-band split CANDIDATE trigger (report-only)
OVER_CEILING_LINES = 800    # SPEC-0120 §3 — over-ceiling must-split (one bounded read)

# BYTE axis (SPEC-0120 §3, T-10313) — the LINE axis alone under-reads a DENSE doc. The §3 band was
# grounded on ~25 tok/line, but T-10217 live-measured ~39.8 tok/line on the generated worker seed and
# T-10219 measured a 1.7x density spread ACROSS the seed docs (CHARTER ~102 B/line vs AGENTS ~163
# B/line). So a doc can sit in-band on LINES while its token weight nears the reader's one-bounded-read
# page cap — i.e. line-clean but single-read-UNSAFE. The byte axis is deterministic (`wc -c`) and
# needs no tokenizer; est_tokens is a derived REPORT figure, never a gate input.
BYTES_PER_TOKEN = 2.52      # calibrated from T-10217's live reader measurement
PAGE_CAP_TOKENS = 25000     # the reader's one-bounded-read page cap (SPEC-0120 §3 functional ceiling)
OVER_CEILING_BYTES = 63000  # 25000 * 2.52 — the byte-axis analog of OVER_CEILING_LINES
# The byte BAND mirrors the line band's proportion of its own ceiling (500/800 = 0.625): 0.625*63000.
OVER_BAND_BYTES = 40000     # over-band split CANDIDATE on the byte axis (report-only)

# The handbook files are the FULL generated HANDBOOK_READ_ORDER set (SPEC-0120 §1), injected by the
# host as `canonical_docs` — the set grows by splitting, so this module never hardcodes it (T-10356).
# Scanned as methodology ONLY in the ENGINE's own checkout — in a `-C` consumer the same-named
# CHARTER.md/README.md are PRODUCT docs, owner-language-allowed by convention (§2 consumer variant);
# the finding-2 path rule realised in code. The methodology dirs (specs/patterns/lessons/scenarios)
# are methodology in EVERY realm, so they are always scanned. specs/ carries BOTH governed shapes —
# the *.yaml spec cards AND governed *.md docs that live there (the SPEC-0165 rule-test ledger is
# specs/<PROJECT>-rule-test-ledger.md), so mapping specs to *.yaml alone left every such .md doc out
# of the swept set entirely — structurally invisible on every axis, not merely under-measured
# (T-10836; the T-10834 differential isolated the cause to this mapping, not to the size logic).
_METHODOLOGY_DIRS = (("specs", "*.yaml"), ("specs", "*.md"), ("patterns", "*.md"),
                     ("lessons", "*.md"), ("scenarios", "*.md"))


# ══════════════════════════════════════════════════════════════════════════════════════════════
# THE INSPECTION RESULT CONTRACT (SPEC-0173 rules 1+2) — THE ONE DEFINITION SITE.
#
# Everything between this banner and the closing banner is the SOLE place the kernel says what a
# graded inspection theme RESULT carries. No other site — in this module, in a renderer, or in a
# sibling card's surface — spells this vocabulary in its own words; a printing surface calls the
# renderers below, a producing surface calls `result_contract`. That single-site property is not a
# style preference: X-0593 is exactly the shape where two cards define one surface differently, and
# it is asserted by `tests/test_t9775_durable_doc_metrics.py` (the AC3 single-definition legs).
#
# WHY IT EXISTS (the P3-run-1 grounds, journaled 2026-08-08). The durable-doc result key set had NO
# exclusion field at all. Narrowing the scan set moved `swept` 274 -> 166 while the KEY SET stayed
# byte-identical, so the narrowing was legible only as a smaller count — and a reader of ONE result,
# which is how a theme verdict is actually consumed, could not see it. `swept` counts what WAS looked
# at; it can never surface what was unreachable BY CONSTRUCTION, which is precisely the class this
# contract makes visible. A consumer's SPEC-0165 rule-test ledger measured 93,857 bytes against a
# 63,000-byte ceiling while the run that should have flagged it reported its over-ceiling set EMPTY.
#
# A clean verdict is the dangerous artifact: a missing check announces itself, a false clean does not.
# ══════════════════════════════════════════════════════════════════════════════════════════════

# The contract's field names, named ONCE (SPEC-0173 rule 2 = swept + excluded; rule 1 = no_data).
RESULT_CONTRACT_FIELDS = ("swept", "excluded", "no_data")

# SPEC-0120 §1 declares these NEVER durable docs. Until now that declaration lived only as PROSE in
# `_iter_durable_docs`'s docstring; these constants make the same statement machine-readable so the
# result can NAME its exemptions instead of a reader having to know them (CHARTER §P1 F1 — extend the
# existing analog, F2 — a derived view over the existing surface, no new store / event / node type).
_EXEMPT_DIRS = ("tasks", "plans", "decisions")
_EXEMPT_ROOT_FILES = ("MEMORY.md", "events.jsonl")
_DURABLE_DOC_SUFFIXES = (".md", ".yaml")

# The three REASONS an excluded class carries. They are kept DISTINCT on purpose: collapsing them
# would hide the one distinction that matters — a deliberate exemption vs a blind spot the scan set
# cannot reach. `unscanned` is the blind-spot class, and it is where the SPEC-0165 ledger lives
# (`specs/<PROJECT>-rule-test-ledger.md`, invisible while `specs/` maps to `*.yaml` alone).
EXCLUSION_REASON_EXEMPT = "exempt"            # SPEC-0120 §1 declares the class never-durable
EXCLUSION_REASON_OUT_OF_REALM = "out-of-realm"  # present on disk, skipped because repo != engine
EXCLUSION_REASON_UNSCANNED = "unscanned"      # durable-doc-shaped, present, NO scan rule reaches it

_HANDBOOK_CLASS = "<handbook read-order>"     # the canonical_docs set, rendered as one class


def structural_exclusions(repo_root, engine_root, canonical_docs, swept_rels):
    """The classes the durable-doc scan CANNOT reach, derived AGAINST the scan set (SPEC-0173 rule 2).

    Returns a deterministically-ordered list of rows `{class, reason, files, bytes}` — one row per
    CLASS, never per file, so the block stays bounded on a corpus of any size while still carrying the
    WEIGHT of what is unseen (the ledger incident is a byte-size incident, so `bytes` is load-bearing).

    Computed as the repo's own top-level durable-doc surface MINUS `swept_rels` (the paths the scan
    REACHED — the yielded ones plus, since T-10839, any it reached and could not READ: those are named
    as degrades and must not double-report here as a blind spot the scan set cannot reach). Deriving it against the scan set — rather than restating the scan set — is what
    makes it move when the scan set moves: narrow `_METHODOLOGY_DIRS` and the classes that fall out
    appear here as `unscanned`, which is the AC2 differential and the whole point of rule 2.

    BOUND, stated rather than left implicit: DIRECT children only, mirroring the non-recursive globs of
    `_iter_durable_docs`. A nested `<dir>/<sub>/x.md` is reported by neither, exactly as today; this
    contract describes the scan that exists, it does not silently widen it.
    """
    swept = set(swept_rels)
    handbook = set(canonical_docs or ())
    groups: dict = {}

    def _record(cls, reason, path):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        row = groups.setdefault((cls, reason), [0, 0])
        row[0] += 1
        row[1] += size

    try:
        entries = sorted(repo_root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith("."):           # dotdirs are not the durable-doc surface
            continue
        if entry.is_dir():
            sub = entry.name
            try:
                children = sorted(entry.iterdir())
            except OSError:
                continue
            for p in children:
                if p.suffix not in _DURABLE_DOC_SUFFIXES or not p.is_file():
                    continue
                if f"{sub}/{p.name}" in swept:
                    continue
                if sub in _EXEMPT_DIRS:
                    _record(f"{sub}/*{p.suffix}", EXCLUSION_REASON_EXEMPT, p)
                elif p.name.startswith("_"):     # _template.* / scaffolds (SPEC-0120 §1)
                    _record(f"{sub}/_*{p.suffix}", EXCLUSION_REASON_EXEMPT, p)
                else:
                    _record(f"{sub}/*{p.suffix}", EXCLUSION_REASON_UNSCANNED, p)
        elif entry.is_file():
            if entry.name in swept:
                continue
            # A DECLARED root exemption is matched BEFORE the durable-doc suffix gate. `events.jsonl`
            # is named exempt by SPEC-0120 §1 yet is neither `.md` nor `.yaml`, so gating on the
            # suffix first would silently drop it and the declaration would describe something the
            # result never reports — a declared-but-unhandled exemption, which is the same false-clean
            # shape one level down (audit-post finding, T-10835).
            if entry.name in _EXEMPT_ROOT_FILES:
                _record(entry.name, EXCLUSION_REASON_EXEMPT, entry)
            elif entry.suffix not in _DURABLE_DOC_SUFFIXES:
                continue                         # neither durable-doc-shaped nor a declared exemption
            elif entry.name.startswith("_"):     # a root scaffold is exempt exactly as a nested one
                _record(f"_*{entry.suffix}", EXCLUSION_REASON_EXEMPT, entry)
            elif entry.name in handbook:
                # A `-C` consumer skips the handbook by design (SPEC-0120 §2) — realm-conditional, so
                # it is neither a permanent exemption nor a defect, and it gets its own reason.
                _record(_HANDBOOK_CLASS, EXCLUSION_REASON_OUT_OF_REALM, entry)
            else:
                _record(f"*{entry.suffix}", EXCLUSION_REASON_UNSCANNED, entry)
    return [{"class": cls, "reason": reason, "files": n, "bytes": b}
            for (cls, reason), (n, b) in sorted(groups.items())]


def no_data_fields(no_data) -> dict:
    """THE WRITE side of rule 1's discriminator — the ONE place a producer spells the field.

    Every surface that RECORDS a run (the durable-doc result below, `inspect record`'s
    `inspection_completed`, the saved audit verdict) merges this in rather than writing the key
    itself, so there is exactly one spelling of "did this run produce a verdict at all". The field is
    written ALWAYS, never only on the no-data branch: a clean run that simply OMITS it is
    indistinguishable from a legacy record that could not express it, which is the same
    zero-findings ambiguity rule 1 exists to end, one level down.
    """
    return {"no_data": bool(no_data)}


def is_no_data(record) -> bool:
    """THE READ side of the same discriminator — for a consuming surface folding recorded results.

    An ABSENT field reads as NOT no-data (a completed run). That is a reader's judgement, not a
    parser's: records written before the field existed are ordinary completed runs, and the fold must
    not retroactively re-grade them (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`).
    A run that genuinely produced nothing now SAYS so — which is the whole point of writing the field
    unconditionally above.
    """
    if not isinstance(record, dict):
        return False
    return bool(record.get("no_data"))


def no_data_note(cause: str) -> str:
    """THE one rendered NO-DATA face, given the CAUSE that produced no verdict.

    Rule 1 is a RENDERING rule, so the rendered words live at the definition site too: a surface that
    must show no-data calls this, it never composes its own sentence. The cause is the only variable
    part — 0 surfaces swept, an aborted external audit, a crashed probe — and it is carried in the
    line rather than left for the reader to infer from a zero somewhere else on the screen.
    """
    return f"NO-DATA ({cause} — this run produced no verdict; NOT a clean result)"


# ─── TRACK COVERAGE (T-11043, SPEC-0057 §Run-mode dual-track) ────────────────────────────────────
# The RUN-COVERAGE discriminator, built to the same three-part shape as the `no_data` contract above
# (write / read / render), because it answers the same KIND of question about a run one axis over:
# `no_data` says whether the run produced a verdict AT ALL; this says WHICH OF THE DECLARED TRACKS
# produced it. SPEC-0057 §Run-mode requires each theme to run DUAL-TRACK — a primary track and an
# independent external track, compared only after both finish — and that discipline is the
# load-bearing half of the method: the run that filed T-11043 produced 7 findings only the external
# track surfaced, 3 of them defects in the primary sweep itself. Yet the event named theme,
# findings_count, high_count, lenses_covered, criteria_ref and no_data, and NOTHING about tracks — so
# `inspect record` was emitted for T1..T10 while only T5 and T7 had a second track, and those eight
# events are indistinguishable in the journal from converged ones. A run without a second track now
# SAYS SO.

TRACKS = ("primary", "external")
"""The declared track vocabulary — the two names SPEC-0057 §Run-mode already fixes, in a stable order.

Not coined here: `patterns/inspection-criteria-roster-run-and-lenses.md` §Run-mode names exactly a
**primary track** and an **external track**. One spelling, one order, so a recorded coverage list is
comparable across runs and a typo cannot enter the journal as a third track name.
"""


def track_coverage_fields(tracks) -> dict:
    """THE WRITE side of the coverage discriminator — the ONE place a producer spells the field.

    Normalised to `TRACKS` order so two runs with the same coverage record the same bytes, and written
    ALWAYS — never only when a track ran. A run that simply OMITS the key is indistinguishable from a
    record written before the field existed, which is the same silence the field exists to end (the
    `no_data_fields` argument, one axis over).

    COVERAGE ONLY (SPEC-0057 §4, unchanged): a list of track names is not a colour, a score, a band or
    a grade. In particular it does NOT record CONVERGENCE — whether the two tracks' finding sets agreed
    is a judgement the run-mode doctrine assigns to the operator's compare-after-both-finish step, and
    recording it here would turn a coverage record into the per-theme verdict §4 forbids.
    """
    given = set(tracks or ())
    return {"tracks_covered": [t for t in TRACKS if t in given]}


def tracks_covered(record) -> list:
    """THE READ side of the same discriminator — for a consuming surface folding recorded runs.

    An ABSENT field reads as UNRECORDED (`[]`), never as "both tracks ran". That is the reader's
    judgement, not the parser's (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): runs
    written before the field existed genuinely did not say what their coverage was, and inventing
    coverage for them would put a stronger claim in the record than anyone ever made. Unrecorded and
    single-track are therefore both distinct from dual-track, and neither is silently upgraded.
    """
    if not isinstance(record, dict):
        return []
    got = record.get("tracks_covered")
    if not isinstance(got, (list, tuple)):
        return []
    return [t for t in TRACKS if t in set(got)]


def track_coverage_note(covered) -> str:
    """THE one rendered coverage face — a surface that shows coverage calls this, never its own words.

    Three DISTINCT lines, because three distinct things happened: the run did not say; the run ran one
    track and the other did not; every declared track ran. A single-track line NAMES the track that did
    not run, so the gap is readable without the reader holding `TRACKS` in their head.

    Rendering only — no colour, no score, and deliberately never the word "converged" (see
    `track_coverage_fields`).
    """
    covered = [t for t in TRACKS if t in set(covered or ())]
    if not covered:
        return ("track coverage: NOT RECORDED — this run did not say which tracks ran; absence is NOT "
                "a claim that both did (SPEC-0057 §Run-mode dual-track)")
    missing = [t for t in TRACKS if t not in covered]
    if missing:
        return (f"track coverage: SINGLE-TRACK — {'+'.join(covered)} only; "
                f"{'+'.join(missing)} did NOT run (SPEC-0057 §Run-mode dual-track)")
    return f"track coverage: {'+'.join(covered)} — every declared track ran"


# ─── SEMAPHORE STANDING (T-12063, SPEC-0119 rule 10 / X-1262) ───────────────────────────────────
# The THIRD discriminator on this run, built to the same write/read/render shape as the two above,
# because it answers the same KIND of question one axis over: `no_data` says whether the run produced
# a verdict at all; `tracks_covered` says which tracks produced it; this says whether the run COUNTS
# AS A REVIEW for the review-due semaphore (views._view_review_due).
#
# WHY IT IS NOT `no_data` (asked and answered at Analysis, worth keeping): `no_data` is
# OPERATOR-DECLARED via `--no-data` and is fail-closed against a findings count. A zero-file sweep is
# MACHINE-DERIVED from the checkout and needs no operator at all. Auto-setting `no_data` would
# rewrite the meaning of an operator flag and collide with its own contradiction guard. So the two
# CAUSES stay distinct and the CONSEQUENCE is unified here: the fold gains ONE predicate rather than a
# lengthening chain of skip-reasons, and a later cause joins by making this field false.
#
# THE INCIDENT (X-1262, MEASURED on aiseller 2026-09-04): `init --declare-theme` accepted a surfaces
# value matching ZERO files, wrote it, and `inspect record` then reported matched 0 / surfaces_bytes 0
# — and RESET the cadence. Left alone every later run would record a 0-byte sweep and re-anchor the
# clock, so the review-due surface would read GREEN while inspecting nothing. That is the dead-cache
# shape the graph cache reports its own 0% hit rate to avoid: a mechanism whose failure is silent and
# whose silence is indistinguishable from success.


def semaphore_fields(counted) -> dict:
    """THE WRITE side of the semaphore discriminator — the ONE place a producer spells the field.

    Written on EVERY run, never only on the uncounted branch — the `no_data_fields` argument exactly:
    a run that simply OMITS the key is indistinguishable from a record written before the key
    existed, which is the same silence the field exists to end, one level down.
    """
    return {"semaphore_counted": bool(counted)}


def counts_for_semaphore(record) -> bool:
    """THE READ side — for a consuming surface folding recorded runs (views._view_review_due).

    An ABSENT field reads TRUE (the run anchors its subject's clock). That is the reader's judgement,
    not the parser's (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`), and here the
    fail-safe direction is the OPPOSITE of a gate's: every `inspection_completed` row written before
    this field existed records a review that genuinely HAPPENED, so reading absence as uncounted would
    retroactively un-review the entire journal and nag the reader to redo reviews they already did.
    A surface that cries wolf about real work is one the reader learns to skim — which would cost
    exactly the attention this field exists to direct at the runs that really did sweep nothing.
    """
    if not isinstance(record, dict):
        return True
    got = record.get("semaphore_counted")
    if got is None:
        return True
    return bool(got)


def semaphore_note(cause: str) -> str:
    """THE one rendered UNCOUNTED face — a surface showing it calls this, never its own sentence.

    Names the CAUSE and the CONSEQUENCE together, because the consequence is the non-obvious half: a
    reader who sees only "0 files" has to know the semaphore exists to understand what follows.
    """
    return (f"NOT COUNTED AS A REVIEW ({cause}) — this run is RECORDED, but it does NOT mark the "
            f"subject reviewed and does NOT reset its review-due clock; the subject stays DUE "
            f"(SPEC-0119 rule 10)")


def result_contract(swept, excluded):
    """THE definition of what a graded inspection theme result carries (SPEC-0173 rules 1+2).

    Three fields, produced together because they are one statement — "here is what this run looked at,
    here is what it could not reach, and here is whether it produced a verdict at all":

      swept:    how many surfaces were ACTUALLY looked at (the rule-2 (a) half, already shipped).
      excluded: the `structural_exclusions` rows — the rule-2 (b) half. A bare "none found" without
                this is not a clean result, it is an UNQUALIFIED one, and rule 2 makes it inadmissible
                as a theme verdict.
      no_data:  rule 1 — a run that swept nothing produced no verdict. Zero findings from a run that
                did not reach anything must NEVER take the same shape as zero findings from a run that
                did, so this is carried as its own field and rendered distinctly, never inferred by a
                reader from a zero count.

    Pure and directly unit-testable. Producing surfaces call THIS instead of writing the keys — which
    is what the AC3 monkeypatch leg proves: swap this function out and the produced artifact changes,
    so the fields are genuinely produced here and not merely spelled the same elsewhere.
    """
    return {"swept": swept, "excluded": list(excluded), **no_data_fields(swept == 0)}


def result_contract_headline(rc) -> str:
    """THE one-line rendering of the contract — rule 1's distinct NO-DATA face lives here.

    A run that reached nothing reads NO-DATA, never `swept=0` sitting beside a row of zero buckets
    that a reader parses as clean. Report-only: the caller prints this and PROCEEDS."""
    if is_no_data(rc):
        head = no_data_note("0 surfaces swept")
    else:
        head = f"swept={rc['swept']}"
    rows = rc["excluded"]
    if not rows:
        return f"{head} excluded=none"
    return (f"{head} excluded={len(rows)} class(es)/"
            f"{sum(r['files'] for r in rows)} file(s)/{sum(r['bytes'] for r in rows)}B")


def result_contract_exclusion_rows(rc, indent="    ") -> list:
    """THE per-class rendering of the excluded set — one line per class, deterministically ordered.

    Kept beside the headline so no printing surface ever re-spells the vocabulary: a renderer that
    wants to show exclusions calls this, it does not reach into the field itself."""
    return [f"{indent}excluded {r['class']} [{r['reason']}] "
            f"{r['files']} file(s) {r['bytes']}B" for r in rc["excluded"]]


# ══════════════════════════════ END OF THE RESULT CONTRACT ════════════════════════════════════


# ══════════════════════════════ THE NAMED DEGRADE (SPEC-0173 rule 4) ═══════════════════════════
# An observation filter in rule 4's CLOSED set emits on the FAILURE of its WATCHED SUBJECT, not only
# on its success. A filter that is silent when its subject breaks is false-green by the same argument
# as rules 1-3, one level up: its silence is read as "nothing was wrong".
#
# THE SET IS CLOSED AND ENUMERABLE — that is the rule's load-bearing property, and this region does
# NOT widen it. Exactly three classes: (a) inspection RESULT RENDERERS (`durable_doc_metrics` +
# `cmd_inspect_record` below), (b) AUDIT-VERDICT RENDERING (`audit.verdict_render`, which renders
# through THIS face), (c) ROSTER CHECKLIST REPORTING prose (patterns/inspection-criteria-roster-run-
# and-lenses.md §Run-mode). Wrapper monitors and ad-hoc session-authored checks are EXPLICITLY OUT by
# the owner decision of 2026-08-08: an unbounded set makes rule 4's own discharge condition — each
# filter in scope has been run against a broken subject — unverifiable by construction. That class is
# real (four ad-hoc session filters misreported during this plan's own trial) and is governed as a
# HABIT, not as a contract clause.
#
# SHAPE — INHERITED, not invented (CHARTER §P1 F1). The corpus already holds the correct answer: the
# SPEC-0160 rule 23 live-revision adapter surfaces a NAMED degrade (`live_revision_source:
# "adapter-degraded"` + `live_revision_degrade: "<why>"`) and RETAINS its fallback baseline instead of
# zeroing, because a broken adapter is itself visible debt and never a silent pass. Same shape here:
# a row NAMING the subject and the cause, rendered beside the result — no new store, no new event, no
# new reporting path. This is the DEGRADE face only; the RESULT vocabulary stays defined above and is
# not extended (`degraded` is reported BESIDE the contract fields, never merged into them).
# ══════════════════════════════════════════════════════════════════════════════════════════════

DEGRADE_SOURCE = "read-degraded"     # the `adapter-degraded` sibling token, for a source-naming caller


def degrade_row(subject: str, cause: str) -> dict:
    """ONE degrade record — the SUBJECT that could not be read and the CAUSE, named together.

    Both halves are load-bearing: the subject without the cause is unactionable, and the cause without
    the subject cannot be located. Mirrors the live-revision adapter's `{"error": "<detail>"}` return,
    with the subject carried explicitly because a scan reports MANY subjects, not one."""
    return {"subject": str(subject), "cause": str(cause)}


def degrade_note(subject: str, cause: str) -> str:
    """THE one rendered DEGRADE face — sibling of `no_data_note`, and spelled in exactly one place.

    Rule 4 is a rendering obligation like rule 1, so the rendered words live at the definition site:
    a surface that must show a degrade calls this, it never composes its own sentence. The wording
    states what a reader must not conclude — a broken instrument is not a clean subject — because that
    inference is precisely the failure mode the rule exists to close."""
    return (f"DEGRADED ({subject} could not be read: {cause} — the watched subject is broken; "
            f"NOT a clean result)")


def degrade_rows(rows, indent="    ") -> list:
    """THE per-subject rendering of a degrade set, deterministically ordered by subject.

    Kept beside the face so no printing surface re-spells it, exactly as
    `result_contract_exclusion_rows` sits beside the headline."""
    return [f"{indent}{degrade_note(r['subject'], r['cause'])}"
            for r in sorted(rows, key=lambda r: r["subject"])]


# ══════════════════════════════ END OF THE NAMED DEGRADE ═══════════════════════════════════════


# ═════════════════ THE REVISION-PROPOSAL CONTRACT (SPEC-0178 rules 7+9) — ONE DEFINITION SITE ══════
# Everything between this banner and its close is the SOLE place the kernel says what a revision
# proposal CARRIES and how it READS. The producing fold lives in bin/lib/task.py (it owns the
# `audit_scrutiny` case vocabulary and both journal ends); it IMPORTS the tokens below rather than
# spelling them, and every printing surface calls the renderers below. Same single-site property the
# result contract above holds, and for the same reason: X-0593 is exactly the shape where two sites
# define one surface differently, and a four-field format whose fourth field is an HONESTY label is
# precisely where a second spelling would do damage.
#
# WHY THE FOUR FIELDS (rule 7). "The periodic review does not compute whether to loosen. Each proposal
# it produces names four things: the CASE, the ACTION, the BASIS (the specific records), and the
# STRENGTH of that basis — either direct observation or absence of observation. Absence of observation
# is labelled as such and is never presented as evidence of safety."
#
# THE ABSENCE LABEL IS LOAD-BEARING, not a caption (rule 5's cycle-15 measurement). On all three
# consumers the automatic restoration chain collapses to ZERO at the `kind: defect` triage hop across
# their entire history, so wherever that judgement is not made the review IS the restoration carrier —
# and the only evidence it has is an absence. An absence rendered as a clean result would re-promise
# exactly the safeguard the measurement withdrew (`lessons/a-presence-count-is-not-a-liveness-probe`:
# a count of records is not a probe of the thing that produces them).
PROPOSAL_FIELDS = ("case", "action", "basis", "strength")

# The action vocabulary, verbatim from rule 7. `widen` is in the vocabulary for a HUMAN and is never
# machine-proposed — the rule says the review does not compute whether to loosen, so the fold that
# produces these rows has no branch that reaches it.
PROPOSAL_ACTIONS = ("restore", "narrow", "widen", "leave")

# The two STRENGTHS, spelled exactly as rule 7 words them.
STRENGTH_DIRECT = "direct observation"
STRENGTH_ABSENCE = "absence of observation"


def absence_note() -> str:
    """THE one rendered ABSENCE-OF-OBSERVATION face — the sibling of `no_data_note` / `degrade_note`,
    and spelled in exactly one place.

    Like those two, the wording states what a reader must NOT conclude, because that inference is the
    whole failure mode: nothing was recorded, and the two explanations for that are not
    distinguishable from the record. Rule 7 forbids presenting it as evidence of safety, so the label
    carries the ambiguity itself rather than leaving a reader to supply the charitable half.

    WHAT IS ABSENT IS THE JUDGEMENT, NOT NECESSARILY THE RECORDS — worded precisely, because the
    proposal's own basis may simultaneously name case-linked captures that exist. Captures with no
    `kind` are exactly the population this label is about: something WAS noticed and nobody decided
    whether it was a defect. Saying "nothing was recorded" there would contradict the basis printed
    two lines below it, and would quietly re-describe an unexamined pile as an empty one."""
    return (f"{STRENGTH_ABSENCE} — no case-linked capture was JUDGED a defect over the window. This "
            f"is NOT evidence of safety: it means EITHER nothing escaped OR nobody made the call, "
            f"and the record cannot tell those apart")


def proposal_rows(review, indent="    ") -> list:
    """THE per-proposal rendering — one line per case, four fields, deterministic order.

    Kept beside the tokens so no printing surface re-spells the vocabulary, exactly as
    `result_contract_exclusion_rows` sits beside its headline. The BASIS is rendered as its own
    indented sub-lines because it names RECORDS (counts of captures, out-of-path rows, the covered
    share) and collapsing several records onto one line is how a basis stops being checkable."""
    out: list = []
    for p in (review or {}).get("proposals") or []:
        out.append(f"{indent}case '{p['case']}' -> ACTION {p['action']} | STRENGTH {p['strength']}")
        if p["strength"] == STRENGTH_ABSENCE:
            out.append(f"{indent}  {absence_note()}")
        for b in p["basis"]:
            out.append(f"{indent}  basis: {b}")
    return out


def case_review_headline(review) -> str:
    """THE one-line rendering of a revision run (rules 7+9).

    A project that declares NO case SAYS so rather than printing nothing: silence is
    indistinguishable from a fold that never ran, and this block's absence would be read as its
    emptiness.

    DELIBERATELY NOT `no_data_note`, though the shape invites it. Zero declared cases is not a
    measurement that failed — it is the COMPLETE answer, and the safest state the mechanism has: with
    no case declared every substantive card takes audit-post, rule 1's fail-closed default. Wearing
    the no-data face would mark the healthiest possible reading as a broken instrument, which is
    rule 1's own error run backwards. The one place absence IS dangerous here is a case that exists
    and has no records against it, and that is labelled at the proposal (`absence_note`), where it
    belongs."""
    n = len((review or {}).get("proposals") or [])
    if not n:
        return ("0 declared audit_scrutiny case(s) — every substantive card takes audit-post, the "
                "rule 1 fail-closed default; nothing to revise")
    return f"{n} declared case(s) reviewed"


def case_review_report(review, indent="    ") -> list:
    """THE whole printed face of a revision run — the ONE composition both print sites call.

    Two sites render this (the `--dry-run` wiring proof and the real emit), and a second spelling
    across them would let the dry-run advertise a shape the real run does not print. The trailer
    restates the report-only contract at the point of reading, because rule 9's number is the one a
    reader is most likely to mistake for a threshold."""
    lines = [f"  exemption-case revision (SPEC-0178 rules 7+9, report-only): "
             f"{case_review_headline(review)}"]
    lines.extend(proposal_rows(review, indent))
    if (review or {}).get("proposals"):
        lines.append(f"{indent}(report-only — rule 9 sets NO ceiling and NO threshold and refuses "
                     f"nothing; the ACTION is a candidate for a human, never an applied change, and "
                     f"`widen` is never machine-proposed — rule 7: the review does not compute "
                     f"whether to loosen)")
    return lines


# ═════════════════ END OF THE REVISION-PROPOSAL CONTRACT ══════════════════════════════════════════


def _iter_durable_docs(repo_root, engine_root, canonical_docs):
    """Yield (rel, Path) for every governed durable doc (SPEC-0120 §1), deterministically ordered.

    GOVERNED: specs/*.yaml, specs/*.md, patterns/*.md, lessons/*.md, scenarios/*.md (methodology in
    EVERY realm — specs/ contributes BOTH its spec cards and its governed .md docs, T-10836) +
    the `canonical_docs` handbook set ONLY in engine-self (repo_root == engine_root). EXEMPT (never
    yielded, §1): MEMORY.md, events.jsonl, tasks/, plans/, decisions/, and `_*` template scaffolds. The
    handbook is skipped under `-C` because a consumer's same-named CHARTER.md/README.md are PRODUCT
    docs (§2). `canonical_docs` = the host's HANDBOOK_READ_ORDER-derived CANONICAL_DOCS (T-10356) — it
    is passed in, never guessed, so a SPEC-0120 split part can never fall out of the scan."""
    for sub, pat in _METHODOLOGY_DIRS:
        d = repo_root / sub
        if not d.exists():
            continue
        for p in sorted(d.glob(pat)):
            if p.name.startswith("_"):        # _template.* / scaffolds are not durable docs
                continue
            yield (f"{sub}/{p.name}", p)
    if engine_root is not None and repo_root == engine_root:
        for name in canonical_docs:
            p = repo_root / name
            if p.exists():
                yield (name, p)


def durable_doc_metrics(repo_root, engine_root, canonical_docs):
    """Report-only per-doc SIZE (two axes) + Cyrillic-line counts over the SPEC-0120 §1 durable set.
    NEVER a gate (CHARTER non-goal #2) — it measures, it does not block. Returns a dict the
    inspection_completed event carries as report-only fields:

      docs:         [{path, lines, bytes, est_tokens, cyrillic_lines}] — EVERY swept durable doc (the
                    authoritative per-doc record; `lines`/`bytes` are the two SIZE axes, `est_tokens`
                    is derived from bytes, `cyrillic_lines` = count of Cyrillic-bearing lines; all keys
                    are distinct and never collide, SPEC-0120 finding-2).
      over_band:    [path,...] — docs in (500, 800) lines: report-only split CANDIDATES (§3).
      over_ceiling: [path,...] — docs >=800 lines: must-split (one bounded read, §3). DISJOINT from
                    over_band so the two counts stay reported SEPARATELY (§3).
      over_band_bytes:    [path,...] — docs in (40000, 63000) bytes: byte-axis split CANDIDATES.
      over_ceiling_bytes: [path,...] — docs >=63000 bytes (~the 25K-token page cap): must-split.
                    DISJOINT from over_band_bytes — the byte axis mirrors the line axis exactly, and
                    the two AXES are independent: a doc line-clean but byte-heavy (a DENSE doc) is
                    flagged on the byte axis alone. That differential is the whole point (T-10313).
      cyrillic:     [path,...] — language CANDIDATES (§2): docs with >=1 Cyrillic-bearing line, flagged
                    ONLY in the KERNEL realm (repo_root == engine_root). A `-C` consumer's own
                    methodology docs are owner-language-allowed and NEVER language-flagged; English
                    re-binds when a doc is promoted INTO the engine's methodology (T-10114). The
                    per-doc `cyrillic_lines` count above is recorded in EVERY realm regardless.
      est_tokens:   corpus-total estimated tokens (sum of the per-doc figures) — report context only.
      degraded:     [{subject, cause}] — the durable docs this scan COULD NOT READ (SPEC-0173 rule 4,
                    T-10839). Reported BESIDE the result contract, never inside it: an unreadable doc
                    is not swept and is not clean, it is a broken WATCHED SUBJECT, and it is named
                    rather than dropped. A readable corpus carries an empty list (written ALWAYS, the
                    `no_data` discipline: a result that simply OMITS the key is indistinguishable from
                    one that could not express it).

    PLUS the three RESULT-CONTRACT fields — `swept` / `excluded` / `no_data` — merged in from the ONE
    definition site above (`result_contract`), NEVER written here. `swept` alone was half of SPEC-0173
    rule 2; the `excluded` half now names the classes this scan cannot reach BY CONSTRUCTION, and
    `no_data` keeps a run that reached nothing from wearing the shape of a clean one (rule 1)."""
    docs, over_band, over_ceiling, cyr = [], [], [], []
    over_band_bytes, over_ceiling_bytes = [], []
    degraded = []   # SPEC-0173 rule 4 — the docs this instrument could not READ (see the loop below)
    # LANGUAGE (§2) is a KERNEL-realm rule (SPEC-0120 §2, T-10114/X-0208): English-only binds a doc
    # only in the traveling/kernel realm. A `-C` consumer's OWN project-local methodology docs are
    # owner-language-allowed, so their Cyrillic is NOT flagged; English re-binds when a doc crosses
    # INTO the engine's own methodology (repo_root == engine_root — the promotion destination, which
    # IS scanned here). The SIZE axis (over_band/over_ceiling) and the per-doc cyrillic_lines record
    # stay scanned in EVERY realm — only the CANDIDATES bucket is realm-gated.
    kernel_realm = engine_root is not None and repo_root == engine_root
    for rel, p in _iter_durable_docs(repo_root, engine_root, canonical_docs):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            # SPEC-0173 rule 4 (T-10839) — the WATCHED SUBJECT broke. Before this the read was
            # swallowed with a bare `continue`: the doc vanished from `swept`, from every bucket and
            # from the printed report, so an unreadable corpus rendered as a SMALLER CLEAN one and the
            # instrument's silence was read as the subject's health. It is NOT counted as swept (it
            # was never read, and pretending otherwise would be a false CLEAN one level down) — it is
            # NAMED, in the live-revision adapter's shape: keep going, report the degrade.
            degraded.append(degrade_row(rel, f"{type(e).__name__}: {e}"))
            continue
        lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        # `wc -c` equivalent: the doc's on-disk utf-8 byte weight. est_tokens is a derived REPORT
        # figure (bytes / ~2.52), never a stored source of truth and never a gate input.
        n_bytes = len(text.encode("utf-8"))
        est_tokens = round(n_bytes / BYTES_PER_TOKEN)
        cyrillic_lines = sum(1 for ln in text.splitlines() if CYRILLIC_RE.search(ln))
        docs.append({"path": rel, "lines": lines, "bytes": n_bytes, "est_tokens": est_tokens,
                     "cyrillic_lines": cyrillic_lines})
        if lines >= OVER_CEILING_LINES:
            over_ceiling.append(rel)
        elif lines > OVER_BAND_LINES:
            over_band.append(rel)
        # The BYTE axis is scanned in EVERY realm, exactly like the line axis (only LANGUAGE is
        # realm-gated). Buckets are disjoint and reported separately, mirroring the line axis.
        if n_bytes >= OVER_CEILING_BYTES:
            over_ceiling_bytes.append(rel)
        elif n_bytes > OVER_BAND_BYTES:
            over_band_bytes.append(rel)
        if cyrillic_lines and kernel_realm:
            cyr.append(rel)
    metrics = {"docs": docs, "over_band": over_band, "over_ceiling": over_ceiling,
               "over_band_bytes": over_band_bytes, "over_ceiling_bytes": over_ceiling_bytes,
               "cyrillic": cyr, "est_tokens": sum(d["est_tokens"] for d in docs),
               # Reported BESIDE the result-contract fields, never merged into them: rule 4 is about
               # the INSTRUMENT, rules 1+2 are about the RESULT, and collapsing the two would put a
               # broken subject back inside a clean-looking count.
               "degraded": degraded}
    # The result-contract fields come from the ONE definition site, merged in — this function does not
    # spell them itself (SPEC-0173 rule 2; the AC3 legs in tests/test_t9775_durable_doc_metrics.py).
    # A DEGRADED doc counts as REACHED for the exclusion derivation (audit-pre finding, T-10839).
    # `structural_exclusions` reports what the scan cannot reach BY CONSTRUCTION; a doc the scan found,
    # opened and failed to READ was reached, so leaving it out of this set would file it under
    # `unscanned` — a blind-spot class it does not belong to — and report the same subject TWICE under
    # two contradictory reasons. It is excluded from `swept` (never read) and named in `degraded`; the
    # exclusion rows stay a statement about the SCAN SET, which is what makes rule 2's differential
    # move when the scan set moves.
    metrics.update(result_contract(
        len(docs),
        structural_exclusions(repo_root, engine_root, canonical_docs,
                              [d["path"] for d in docs] + [r["subject"] for r in degraded])))
    return metrics


# ── The SERVED roster parts (T-11179, SPEC-0120 §3) ───────────────────────────────────────────
# The roster is ONE living home SPLIT across several files for loadability (SPEC-0120 §3
# SPLIT-never-delete). Until now the three readers below only ever saw the PARENT file, because the
# caller bound exactly one filename — so a section could not be relocated into a sibling part without
# disappearing from the reader, and every prior split had to route AROUND the living criteria to keep
# `criteria_ref` / `parse_cadence` working. That is the constraint T-11029 (the next must-split) cannot
# satisfy: part 1 is over BOTH ceilings and the largest relocatable block is smaller than the shortfall.
#
# THE CARRIER, and why it is a DECLARED tuple rather than a glob: `HANDBOOK_READ_ORDER` (bin/yitc-v2)
# is the existing analog — SPEC-0120 §3's "Seed-file split serves all parts at startup … the read-order
# lists EVERY part" names it, and it is an explicit ORDERED list from which every read-order surface is
# generated (CHARTER §P1 F1 — extend the existing shape, do not invent a second one). Order matters
# HERE too, and a glob's order is an accident of byte-comparison: `patterns/inspection-criteria-roster*`
# sorts `-navigation-map.md` BEFORE `roster.md` (`-` 0x2D < `.` 0x2E), i.e. exactly wrong.
#
# WHAT IS DECLARED — the parts the freshness-hashed LIVING CRITERIA may live in. The parent is implicit
# at index 0; `-run-and-lenses` (T-10367) carries the run-mode + cross-theme method + the
# architecture-drift lens, and `-themes-delivery-outcome-adoption` (T-11029) carries the T2 / T4 / T5 /
# T6 / T8 lens-checklists — moved out VERBATIM when the parent re-crossed both ceilings at 914 lines /
# 82867 bytes. That move is the first EXERCISE of this tuple, and the reason it exists: before T-11179
# a theme could not leave the parent at all. A future split appends its suffix HERE, in the order the
# parts are meant to be resolved — a part on disk that this tuple does not name is invisible to every
# reader below, and its sections resolve NOWHERE (verified as a RED-before-GREEN differential at
# T-11029: with part 3 written but this line unchanged, `'### T2'` and `'### T8'` raised
# "no … section in any served roster part").
#
# WHICH SECTIONS LIVE WHERE IS NOT ARBITRARY — the parent keeps every section a TEST pins to its own
# filename (the `<!--CADENCE-->` block + the weekly tier via tests/test_review_due.py; T3 via
# tests/test_t10935_t3_merge_filter_case_insensitive.py; T7 via tests/test_t10027_worker_seed_inspection.py;
# T9 + T10 via tests/test_t10125_inspection_theme10.py; the T1 note scanned in-place by
# tests/test_t11049_validate_before_report_realm_agnostic.py). Moving one of those would mean editing a
# pinned test to chase the content, so the split seam was drawn around them.
#
# WHAT IS DECLARED OUT, and why it is not an oversight: the umbrella navigation map
# (`-navigation-map`). MEASURED 2026-08-16 (T-11179 analysis): it carries `### Tier — Operational
# hygiene (weekly) → part 1` — a SIX-LINE POINTER STUB whose body says "lives in part 1 … Read it
# there" — and that heading matches `tier_checklist_text`'s regex exactly as part 1's real 36-row
# checklist does. Serving it would let an INDEX ENTRY shadow the living checklist and emit a
# criteria_ref hashing six lines of pointer prose: the hollowed-hash regression this whole change
# exists to prevent. Its own frontmatter settles the classification — "This is a navigation/index doc
# — it POINTS, it does not restate rules". So the exclusion reads the corpus's own declaration.
#
# Parts are resolved as SIBLINGS OF THE PARENT (`<stem><suffix><ext>`), never as absolute repo paths:
# a `-C` consumer rebinds REPO_ROOT and must carry its OWN parts, and a scratch parent with no
# siblings then resolves to the parent ALONE — byte-identical to the pre-T-11179 single-file reader.
ROSTER_CRITERIA_PART_SUFFIXES = ("-run-and-lenses", "-themes-delivery-outcome-adoption")


def _sibling_rel(roster_rel: str, suffix: str) -> str:
    """`patterns/x.md` + `-part2` -> `patterns/x-part2.md`. A rel with no extension just gets the
    suffix appended (defensive: the rel is a declared constant, never user input)."""
    base, dot, ext = roster_rel.rpartition(".")
    return f"{base}{suffix}.{ext}" if dot else f"{roster_rel}{suffix}"


def served_roster_parts(roster_path, roster_rel: str) -> list:
    """The SERVED roster parts as ordered `[(rel, text)]` — the parent first, then each declared
    continuation part that EXISTS, in declared order.

    BEST-EFFORT BY CONTRACT: a part that is missing or unreadable is SKIPPED, never raised on. Two
    callers depend on that in opposite directions — `cmd_inspect_record` wants the parent's own
    absence reported by its existing `ROSTER_PATH.exists()` guard (a nicer message than an OSError),
    and `_review_due_view` is a report-only session-start view that must never break on a doc. A part
    that cannot be READ is simply not served; the criteria it would have carried then resolve
    elsewhere or fail closed at the reader, which is the correct place for that judgement
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`)."""
    parts = []
    for rel, path in [(roster_rel, roster_path)] + [
            (_sibling_rel(roster_rel, sfx),
             roster_path.with_name(f"{roster_path.stem}{sfx}{roster_path.suffix}"))
            for sfx in ROSTER_CRITERIA_PART_SUFFIXES]:
        try:
            parts.append((rel, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return parts


def resolve_roster_part(parts, extract, subject: str):
    """The ONE part carrying `subject`, as `(rel, part_text)`. `extract` is a reader that returns the
    section text or raises ValueError when this part does not carry it.

    THE SELECTOR IS EXACTLY-ONE, NOT FIRST-HIT-WINS — a deliberate narrowing, recorded here because
    it is the load-bearing half of this change:

      0 hits  -> ValueError naming the subject AND every part searched (the pre-existing fail-closed
                 floor, widened only in WHERE it looked — the caller's message is unchanged).
      2+ hits -> ValueError naming every part that claims the subject. Two parts claiming one section
                 is a contradiction between durable artifacts, and CHARTER §Principle 7 says do NOT
                 silently choose: taking hit #1 would emit a criteria_ref naming ONE part while the
                 criteria a reader follows live in another — a ref that hashes a section its own path
                 does not point at, which is the hollowed-hash regression this module must not ship.
                 Refusing costs nothing on any run that exists today (measured: the declared parts
                 hold zero duplicate subjects); it is a tripwire armed for the next split, so that
                 leaving a same-heading pointer stub behind a moved section fails LOUDLY at the next
                 run instead of silently re-hashing the stub.
      1 hit   -> that part.

    The DECLARED ORDER still governs (it is what makes resolution deterministic and reproducible, and
    `resolved_cadence` below still selects on it) — what the order no longer does is quietly pick a
    winner where the corpus is self-contradictory."""
    hits = []
    for rel, text in parts:
        try:
            extract(text)
        except ValueError:
            continue
        hits.append((rel, text))
    searched = ", ".join(rel for rel, _ in parts) or "(no served part readable)"
    if not hits:
        raise ValueError(f"no {subject} section in any served roster part ({searched})")
    if len(hits) > 1:
        claimed = ", ".join(rel for rel, _ in hits)
        raise ValueError(
            f"{subject} section resolves in MORE THAN ONE served roster part ({claimed}) — one "
            f"section, one home. Refusing rather than picking one: hashing a section that another "
            f"part also claims would emit a criteria_ref whose path is not where the living criteria "
            f"are read (CHARTER §Principle 7). Keep the section in exactly one part, and write any "
            f"cross-part pointer WITHOUT re-using its heading")
    return hits[0]


def resolved_checklist_criteria_ref(parts, theme: str) -> str:
    """The theme criteria_ref, resolved across the served parts — `<winning part's rel>#<theme>@<hash
    of THAT part's section bytes>`.

    DELEGATES to `checklist_criteria_ref` with the winning part's text + rel rather than re-deriving
    a hash here. That is what makes the honesty property structural instead of asserted: there is
    exactly ONE section-hashing site, so the ref cannot name one part while hashing another, and a
    whole-part hash is impossible by construction."""
    rel, text = resolve_roster_part(
        parts, lambda t: theme_checklist_text(t, theme), f"'### {theme}' lens-checklist")
    return checklist_criteria_ref(text, theme, rel)


def resolved_tier_criteria_ref(parts, tier: str) -> str:
    """The weekly-tier criteria_ref, resolved across the served parts (the tier sibling of
    `resolved_checklist_criteria_ref`, delegating to `tier_criteria_ref` for the same reason)."""
    rel, text = resolve_roster_part(
        parts, tier_checklist_text, "'### … Operational hygiene'")
    return tier_criteria_ref(text, tier, rel)


def resolved_cadence(parts) -> dict:
    """The cadence values, resolved across the served parts: the first part carrying a parseable
    `<!--CADENCE-->` block wins; `{}` when no part does.

    DELIBERATELY ASYMMETRIC with the two criteria_ref resolvers above — this one is FAIL-SAFE and
    never refuses, including on a duplicate. The asymmetry is the point, not an omission: a
    criteria_ref GUARDS artifact integrity, so an unanswerable input must fail closed; cadence feeds
    the review-due semaphore, a report-only session-start debt echo whose own documented contract is
    "an absent or malformed block returns {} — the semaphore then suppresses, never nags on unknown".
    Refusing there would break the session-start echo over a doc edit, which is strictly worse than an
    unresolved cadence. Same rule, opposite direction, per
    `lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate` (guarding an action ->
    fail closed; describing a state -> fail toward the reading that does not break the reader) and
    `lessons/fail-closed-belongs-to-the-reader-not-the-parser` (the USE SITE owns the judgement, which
    is why `parse_cadence` itself stays an unchanged, faithful parser)."""
    for _rel, text in parts:
        cadence = parse_cadence(text)
        if cadence:
            return cadence
    return {}


def theme_checklist_text(roster_text: str, theme: str) -> str:
    """Extract the THEME's living lens-checklist section from the roster markdown — the `### T<n> — …`
    heading line through (but not including) the next `### ` / `## ` heading or EOF. This section is the
    freshness SUBJECT: its bytes are what the checklist-hash covers, so an edit to the theme's checklist
    changes the hash. Returns the section text (heading included). Raises ValueError when the theme has
    no `### T<n>` section (a roster that lost the theme, or a bad --theme that slipped the THEMES guard)."""
    # Match the heading `### T1 — …` / `### T1 …` exactly (word-boundary on the theme id so T1 never
    # matches inside T10-style ids — e.g. `T1\b` never matches inside `T10`; keeps the roster honest).
    lines = roster_text.splitlines()
    start = None
    head_re = re.compile(rf"^###\s+{re.escape(theme)}\b")
    for i, ln in enumerate(lines):
        if head_re.match(ln):
            start = i
            break
    if start is None:
        raise ValueError(f"no '### {theme}' lens-checklist section in the roster")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        s = lines[j]
        if s.startswith("### ") or s.startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).rstrip() + "\n"


def checklist_criteria_ref(roster_text: str, theme: str, roster_rel: str) -> str:
    """The freshness-bearing `criteria_ref` for a theme run: `<roster_rel>#<theme>@<sha256[:12]>` — the
    living-criteria LOCATION plus a content hash of the theme's lens-checklist section. A later run-mode
    freshness check re-computes this and compares: a differing hash ⇒ the checklist edited since the
    recorded run ⇒ that theme run is STALE (re-run warranted). Raises ValueError via theme_checklist_text
    when the theme section is absent."""
    section = theme_checklist_text(roster_text, theme)
    digest = hashlib.sha256(section.encode("utf-8")).hexdigest()[:12]
    return f"{roster_rel}#{theme}@{digest}"


# ── Consumer-declared theme subject (T-10235, plan K2 — surfaced by trial DP-A) ────────────────
# A `--theme <slug>` that is NOT a kernel roster theme (T1–T10) is accepted IFF the CONSUMER declares
# it in its `yitc-ops.yaml inspection.themes[]` (SPEC-0093 rule 12 — the shape landed by K1/T-10233).
# An undeclared, non-roster slug stays REFUSED fail-closed (the caller `_die`s). This lets a consumer
# run emit the EXISTING `inspection_completed` for a product-realm sweep theme (e.g. design-canon-health)
# — no new event kind / runner / cron / sink (SPEC-0057 §6 schema unchanged).
def declared_themes(ops_yaml) -> list:
    """Every CONSUMER-declared inspection theme ENTRY, in declaration order — the parsed yitc-ops.yaml
    `inspection.themes[]` (SPEC-0093 rule 12). Fail-safe over a malformed / partial carrier: a
    non-mapping root, a missing `inspection:` section, a non-list `themes:`, a non-mapping entry, or an
    entry carrying no `theme:` slug all yield nothing — an unnamed theme is never a subject. Never
    raises. This is the ONE traversal of the carrier: the `inspect record` slug lookup
    (`declared_theme_entry`) and the review-due semaphore (`views._view_review_due`, T-10238) both read
    the declared themes through it."""
    if not isinstance(ops_yaml, dict):
        return []
    insp = ops_yaml.get("inspection")
    if not isinstance(insp, dict):
        return []
    themes = insp.get("themes")
    if not isinstance(themes, list):
        return []
    return [e for e in themes if isinstance(e, dict) and str(e.get("theme") or "").strip()]


def declared_theme_entry(ops_yaml, theme: str):
    """Return the CONSUMER-declared inspection theme ENTRY whose `theme:` slug == `theme`, else None
    (fail-closed: an undeclared slug is refused by the caller). A lookup over `declared_themes`."""
    for entry in declared_themes(ops_yaml):
        if str(entry.get("theme") or "").strip() == theme:
            return entry
    return None


def declared_theme_criteria_ref(entry: dict, theme: str, ops_rel: str) -> str:
    """The freshness-bearing `criteria_ref` for a CONSUMER-declared theme run:
    `<ops_rel>#<theme>@<sha256[:12]>` — the content hash of the theme's DECLARED entry (its probe shape)
    in yitc-ops.yaml. The declared-theme analog of `checklist_criteria_ref`: editing the declared probe
    (e.g. the sweep `checks`) changes the hash, so a stale declared-theme run stays detectable. Hashes a
    canonical (sort-keyed) rendering so carrier key-order never perturbs the ref."""
    canonical = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"{ops_rel}#{theme}@{digest}"


# ── Weekly operational-hygiene tier subject (T-10134, owner design 2026-07-05) ────────────────
# The review-due semaphore needs a journal ANCHOR for the WEEKLY operational-hygiene sweep, the same
# way each T1-T10 theme run has one. So `inspect record` gains a TIER-level subject (--tier weekly):
# it emits inspection_completed with a criteria_ref hashing the roster's Operational-hygiene section
# (SPEC-0057 §3 — subject identity is now THEME or TIER). MANUAL-FIRST is unchanged (SPEC-0057 §2):
# running the weekly sweep by hand + recording it IS the cadence — no cron, no auto-run.
TIERS = ("weekly",)


def tier_checklist_text(roster_text: str) -> str:
    """Extract the roster's `### Tier — Operational hygiene …` section (heading through the next
    `### `/`## ` or EOF) — the freshness SUBJECT for the weekly-tier criteria_ref, mirroring
    theme_checklist_text. Raises ValueError when the section is absent (a roster that lost it)."""
    lines = roster_text.splitlines()
    start = None
    head_re = re.compile(r"^###\s+.*Operational hygiene", re.IGNORECASE)
    for i, ln in enumerate(lines):
        if head_re.match(ln):
            start = i
            break
    if start is None:
        raise ValueError("no '### … Operational hygiene' section in the roster")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("### ") or lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).rstrip() + "\n"


def tier_criteria_ref(roster_text: str, tier: str, roster_rel: str) -> str:
    """The freshness-bearing criteria_ref for a weekly-tier run: `<roster_rel>#<tier>@<sha256[:12]>` —
    the operational-hygiene section's content hash (the tier analog of checklist_criteria_ref)."""
    section = tier_checklist_text(roster_text)
    digest = hashlib.sha256(section.encode("utf-8")).hexdigest()[:12]
    return f"{roster_rel}#{tier}@{digest}"


def parse_cadence(roster_text: str) -> dict:
    """Parse the roster's machine-readable `<!--CADENCE … -->` block — the SINGLE parseable home for the
    per-tier cadence day-values (SPEC-0093/AC3: the CLI reads the roster source, code holds NO cadence
    literal). stdlib-only key:int lines (no yaml — this module imports only stdlib). Fail-safe: an absent
    or malformed block returns {} (the review-due semaphore then suppresses — never nags on unknown)."""
    m = re.search(r"<!--\s*CADENCE\b(.*?)-->", roster_text, re.DOTALL)
    if not m:
        return {}
    out = {}
    for ln in m.group(1).splitlines():
        km = re.match(r"\s*([A-Za-z_]+)\s*:\s*(\d+)\s*$", ln)
        if km:
            out[km.group(1)] = int(km.group(2))
    return out


# ── Consumer sweep-payload budget (T-10369, grow-on-pull X-0275) — REPORT-ONLY, NEVER a gate ──────
# A CONSUMER-declared `probe.sweep` theme (SPEC-0093 rule 12) names a `surfaces:` glob (+ an optional
# `against:` canon file). Running that revizia by hand — or inlining those surfaces into an `audit
# adhoc` consult (the launch runbook path) — risks the SAME payload-timeout that X-0275 hit on the
# SIBLING adhoc path (boomrocket inlined 80838B of sweeps and ABORTed past the auditor's 300s wall).
# The `audit adhoc` fix is `bin/lib/audit.py:_adhoc_payload_budget_warn` (report-only, env-tunable,
# never a gate). inspection.py is stdlib-only + identity-agnostic (it never back-imports the host or a
# sibling leaf — §module header), so we MIRROR that report-only pattern locally rather than import it,
# and the metric rides the EXISTING `inspection_completed` as an additive report-only field — exactly
# the `durable_docs` (SPEC-0120) precedent. NO new event kind / runner / cron / classifier / sink
# (the parent plan's HARD anti-complexity blockers held).
SWEEP_PAYLOAD_WARN_BYTES = 64 * 1024      # matches audit.py ADHOC_INLINE_PAYLOAD_WARN_BYTES (X-0275)


def _sweep_payload_warn_threshold() -> int:
    """The inspection sweep-payload WARN threshold in bytes. Env `YITC_INSPECT_SWEEP_PAYLOAD_WARN_BYTES`
    overrides SWEEP_PAYLOAD_WARN_BYTES. Disjoint cases, one rule each (the audit.py
    `_adhoc_payload_warn_threshold` analog, X-0275): unset/blank → default; MALFORMED (non-int) →
    default; 0 or NEGATIVE → returned as-is (`sweep_payload_metrics` reads `<= 0` as DISABLED — the
    deliberate operator opt-out); positive → verbatim. An env typo never crashes the verb — the metric
    is an advisory, not a gate."""
    raw = os.environ.get("YITC_INSPECT_SWEEP_PAYLOAD_WARN_BYTES", "").strip()
    if not raw:
        return SWEEP_PAYLOAD_WARN_BYTES
    try:
        return int(raw)
    except ValueError:
        return SWEEP_PAYLOAD_WARN_BYTES


def _expand_braces(pattern: str) -> list:
    """Expand a SINGLE `{a,b,c}` alternation group in a glob pattern into one pattern per alternative
    (pathlib.Path.glob does NOT expand braces, but the canonical consumer sweep example declares
    `backend/app/services/{tracking,scoring,virality}.py`). Only the FIRST group is expanded — enough
    for the observed declarations, and this is a REPORT-ONLY estimate, so an exotic multi-group pattern
    that under-counts is acceptable (it is advisory, never a gate). No group → the pattern unchanged."""
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    pre, post = pattern[:m.start()], pattern[m.end():]
    alts = [a.strip() for a in m.group(1).split(",")]
    return [f"{pre}{a}{post}" for a in alts if a]


def expand_sweep_surfaces(repo_root, surfaces) -> list:
    """THE ONE expansion of a `probe.sweep` `surfaces:` value against a checkout — the single globber.

    `surfaces` is one-or-more WHITESPACE-separated globs; each may carry a single `{a,b}` alternation
    group (`_expand_braces`). Returns the matched FILES, deduped by path string, in per-token sorted
    order — the exact behaviour `sweep_payload_metrics` inlined before T-12063 lifted it out here.

    IT IS SHARED BY THREE READERS ON PURPOSE, and that is the whole reason it is a function: the
    payload-budget metric below, the zero-match reader beside it, and — through that reader — the
    `init --declare-theme` WRITE-TIME warning. A second globber written for the declare seam could
    disagree with this one about what a declaration matches, and the two answers would then be about
    the same declaration at the same instant. There is one expansion, so there is one answer.

    Fail-safe like every surface it feeds: an unusable pattern contributes nothing and never raises
    (`repo_root.glob` refuses some inputs outright). Directories are skipped — a sweep reads FILES."""
    matched: list = []
    seen: set = set()
    for token in str(surfaces or "").split():
        for pat in _expand_braces(token):
            try:
                hits = sorted(repo_root.glob(pat))
            except (ValueError, OSError):
                hits = []
            for hit in hits:
                rp = str(hit)
                if rp in seen or not hit.is_file():
                    continue
                seen.add(rp)
                matched.append(hit)
    return matched


def sweep_matched_zero(repo_root, sweep) -> bool:
    """Does this declared `probe.sweep` match ZERO files in `repo_root`? (T-12063, X-1262)

    TRUE only on a POSITIVE reading: the probe IS a sweep, it names a non-empty `surfaces:` value,
    the checkout is known, and the expansion above returns nothing. Every other shape — a `view:`
    probe, a malformed entry, an unknown repo_root — answers FALSE, because "we could not look" is
    not "we looked and found nothing" (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`).

    DELIBERATELY NOT DERIVED FROM `sweep_payload_metrics`, though that block already reports
    `matched`. Those metrics return None when the payload budget is DISABLED
    (`YITC_INSPECT_SWEEP_PAYLOAD_WARN_BYTES <= 0` — an operator opt-out about auditor payload size).
    Reading zero-match off that block would make whether a run counts as a review depend on an
    unrelated telemetry switch: two byte-identical runs over the same empty surfaces would land
    differently in the journal according to one env var. The question here is about the CHECKOUT, so
    it is asked of the expansion directly."""
    if not isinstance(sweep, dict) or repo_root is None:
        return False
    surfaces = str(sweep.get("surfaces") or "").strip()
    if not surfaces:
        return False
    return not expand_sweep_surfaces(repo_root, surfaces)


def sweep_payload_metrics(repo_root, sweep):
    """REPORT-ONLY pre-flight: measure the total byte-size a CONSUMER sweep theme would inline (the
    `surfaces:` glob matches + the optional `against:` canon file), resolved against `repo_root`.
    Returns an additive report-only dict (attached to the `inspection_completed` event, printed as an
    advisory) or None when DISABLED (threshold <= 0), when there is no measurable surface, or when the
    inputs are unusable. Fail-safe: an unreadable/missing file contributes 0 bytes and never raises —
    this is telemetry, not a gate (CHARTER non-goal #2; the X-0275 report-only contract).

    dict shape: {surfaces, matched, surfaces_bytes, against, against_bytes, payload_bytes, budget,
    over_budget}. `over_budget` is a REPORT-ONLY boolean — the caller prints trim guidance and PROCEEDS;
    it is never an exit/verdict/gate."""
    if not isinstance(sweep, dict) or repo_root is None:
        return None
    budget = _sweep_payload_warn_threshold()
    if budget <= 0:
        return None                       # operator opt-out
    surfaces = str(sweep.get("surfaces") or "").strip()
    if not surfaces:
        return None                       # a `sweep` with no surfaces has nothing to measure
    matched = expand_sweep_surfaces(repo_root, surfaces)
    surfaces_bytes = 0
    for p in matched:
        try:
            surfaces_bytes += p.stat().st_size
        except OSError:
            pass                          # unreadable → 0 bytes, never raises (report-only)
    against = str(sweep.get("against") or "").strip() or None
    against_bytes = 0
    if against:
        ap = repo_root / against
        try:
            if ap.is_file():
                against_bytes = ap.stat().st_size
        except OSError:
            pass
    payload_bytes = surfaces_bytes + against_bytes
    return {
        "surfaces": surfaces,
        "matched": len(matched),
        "surfaces_bytes": surfaces_bytes,
        "against": against,
        "against_bytes": against_bytes,
        "payload_bytes": payload_bytes,
        "budget": budget,
        "over_budget": payload_bytes >= budget,
    }


def sweep_payload_advisory(sp: dict) -> str:
    """REPORT-ONLY human advisory for a `sweep_payload` metric block. The under-budget line is a plain
    telemetry read; the over-budget line carries the X-0275 trim guidance. Report-only by contract — the
    caller prints this and PROCEEDS (no verdict/exit/gate). Pure — directly unit-testable."""
    head = (f"  sweep-payload budget (T-10369, report-only): {sp['payload_bytes']}B "
            f"(surfaces {sp['surfaces_bytes']}B over {sp['matched']} file(s) + against "
            f"{sp['against_bytes']}B) vs budget {sp['budget']}B")
    if not sp["over_budget"]:
        return head + " — within budget."
    return (
        head + " — OVER budget.\n"
        f"  # WARN: a hand-run revizia (or inlining these surfaces into an `audit adhoc` consult) may\n"
        f"  #   overrun the auditor's per-invocation timeout and ABORT after burning a full-model run\n"
        f"  #   (X-0275). Splitting per-theme does NOT bound this — payload SIZE is independent of theme\n"
        f"  #   COUNT. Trim `surfaces:` to the RELEVANT files/regions, or narrow `against:`.\n"
        f"  #   Report-only — proceeding. Tune/disable via YITC_INSPECT_SWEEP_PAYLOAD_WARN_BYTES (<=0 disables)."
    )


def cmd_inspect_record(args: argparse.Namespace, *, ROSTER_PATH, ROSTER_REL, _append_event, _die,
                       REPO_ROOT=None, ENGINE_ROOT=None, _read_yaml=None, CANONICAL_DOCS=None,
                       _case_review=None) -> None:
    """Emit exactly ONE `inspection_completed` event for a theme run (SPEC-0057 §6 proof-of-performance,
    even on zero findings) with a REAL checklist-hash `criteria_ref`. Owner-invoked, manual-first — no
    cron. The emit is an append-only journal write (the D-0049 no-worktree exception), so this verb runs
    from any checkout.

    For a **T7** run the event ALSO carries the report-only `durable_docs` block (SPEC-0120, T-9775) —
    per-doc size + Cyrillic-line counts over the durable-doc set — computed against the injected
    REPO_ROOT/ENGINE_ROOT (a `-C` rebind is honoured; the handbook is scanned only engine-self), over
    the injected CANONICAL_DOCS handbook set (the host's one HANDBOOK_READ_ORDER carrier — T-10356).
    The host residue injects those roots + that set; they default None so the identity-agnostic module
    never back-imports the host and a caller omitting them simply skips the durable scan.

    For a **T8** run the event ALSO carries the report-only `case_review` block (SPEC-0178 rules 7+9,
    T-11159) — one four-field revision proposal per declared `audit_scrutiny` case, each with its
    covered share over the case's OWN `window_days`. The producing fold is INJECTED as the zero-arg
    `_case_review` collaborator (bin/lib/task.py owns the case vocabulary and both journal ends); it
    defaults None on the same identity-agnostic contract as the roots above, so a caller omitting it
    simply skips the block. Report-only exactly like `durable_docs` / `sweep_payload`: additive event
    field + printed advisory, never a gate (SPEC-0057 §2 — an inspection SCANS, it does not block, and
    rule 9 sets no ceiling, no threshold, and refuses nothing)."""
    theme = (args.theme or "").strip()
    tier = (getattr(args, "tier", None) or "").strip()
    # Subject identity is a THEME (T1-T10) XOR a TIER (weekly) — exactly one (SPEC-0057 §3, T-10134).
    if bool(theme) == bool(tier):
        _die("give exactly one of --theme (T1..T10) or --tier (weekly) — a run records ONE subject "
             "(SPEC-0057 §3)")
    if tier and tier not in TIERS:
        _die(f"--tier must be one of {', '.join(TIERS)} (SPEC-0057 §9 recordable tiers); got {tier!r}")
    # A --theme is EITHER a kernel roster theme (T1–T10, checklist-hash criteria_ref) OR a
    # CONSUMER-declared theme slug (T-10235 / plan K2) — validated against this consumer's
    # yitc-ops.yaml inspection.themes[] (SPEC-0093 rule 12). An undeclared, non-roster slug is REFUSED
    # fail-closed; the T1–T10 roster path is UNCHANGED.
    declared_entry = None
    if theme and theme not in THEMES:
        ops_yaml = None
        if REPO_ROOT is not None and _read_yaml is not None:
            ops_path = REPO_ROOT / OPS_YAML_REL
            if ops_path.exists():
                ops_yaml = _read_yaml(ops_path)
        declared_entry = declared_theme_entry(ops_yaml, theme)
        if declared_entry is None:
            _die(f"--theme {theme!r} is neither a kernel roster theme ({', '.join(THEMES)}, the fixed "
                 f"SPEC-0057 §3 roster) nor a theme declared in this consumer's "
                 f"{OPS_YAML_REL} inspection.themes[] (SPEC-0093 rule 12) — an undeclared theme slug is refused")
    # criteria_ref subject: a declared theme hashes its yitc-ops.yaml entry (its declared probe shape);
    # a kernel theme / tier hashes the roster checklist section. Only the latter needs the roster read.
    if declared_entry is not None:
        criteria_ref = declared_theme_criteria_ref(declared_entry, theme, OPS_YAML_REL)
    else:
        if not ROSTER_PATH.exists():
            _die(f"inspection roster not found: {ROSTER_PATH} (expected the living T1–T10 lens-checklists)")
        # T-11179: the subject resolves across the SERVED roster parts, not the parent file alone —
        # so a section RELOCATED into a sibling part (SPEC-0120 §3 SPLIT-never-delete) still resolves,
        # and the ref then names THAT part and hashes THAT part's section bytes. The existing
        # fail-closed handling below is UNCHANGED: an absent section still reaches the same `_die` with
        # the same message shape and the same nonzero exit — only WHERE it looked has widened.
        parts = served_roster_parts(ROSTER_PATH, ROSTER_REL)
        try:
            criteria_ref = (resolved_tier_criteria_ref(parts, tier) if tier
                            else resolved_checklist_criteria_ref(parts, theme))
        except ValueError as e:
            _die(f"inspect record: {e}")
    subject_label = tier if tier else theme
    # T-10837 (SPEC-0173 rule 1): a run that produced NO VERDICT — an aborted theme sweep, a crashed
    # or unstarted probe, an external audit that never ran — says so. Before this the verb had no
    # field for it, so such a run was recordable ONLY as `--findings-count 0`, byte-identical to a run
    # that completed and found nothing (the P2-run-2 failing input). FAIL-CLOSED on the contradiction:
    # a run that produced no data cannot also report findings, and silently keeping both would put the
    # ambiguity straight back into the record.
    # The CLI dest is deliberately NOT the contract's field name: the field vocabulary is spelled at
    # the ONE contract site above and nowhere else (the T-10835 single-definition guard), so this verb
    # carries the operator's INTENT under its own name and lets the contract name the recorded field.
    no_verdict = bool(getattr(args, "run_no_verdict", False))
    if no_verdict and (int(args.findings_count or 0) or int(args.high_count or 0)):
        _die("--no-data records a run that produced NO verdict — it cannot also carry a findings "
             "count. Drop --no-data (the run DID produce findings) or record 0 findings "
             "(SPEC-0173 rule 1)")
    lenses = [s.strip() for s in (args.lenses or "").split(",") if s.strip()]
    # T-11043 (SPEC-0057 §Run-mode) — WHICH TRACKS RAN. Parsed in the `--lenses` shape (the shipped
    # analog, CHARTER §P1 F1) and validated fail-closed against the ONE declared vocabulary: a typo
    # silently dropped would put the very silence this field ends straight back into the record, one
    # level down. `getattr` because every pre-existing caller predates the flag.
    tracks = [s.strip() for s in (getattr(args, "tracks", None) or "").split(",") if s.strip()]
    unknown = [t for t in tracks if t not in TRACKS]
    if unknown:
        _die(f"--tracks: unknown track name(s) {', '.join(repr(u) for u in unknown)} — a run's tracks "
             f"are {', '.join(TRACKS)} (the SPEC-0057 §Run-mode dual-track vocabulary). An unrecognised "
             f"name is refused rather than dropped, so a typo cannot record as missing coverage.")
    data = {
        # Subject key: `theme` for a T1-T10 run, `tier` for a weekly-tier run (SPEC-0057 §3). The
        # review-due semaphore (views._view_review_due) folds on whichever key is present.
        ("tier" if tier else "theme"): subject_label,
        "findings_count": int(args.findings_count or 0),
        "high_count": int(args.high_count or 0),
        "lenses_covered": lenses,
        "criteria_ref": criteria_ref,
    }
    # The rule-1 discriminator, spelled through the ONE contract site (never written here) and carried
    # on EVERY run, so a clean event explicitly says it produced a verdict and an aborted one is no
    # longer byte-identical to it.
    data.update(no_data_fields(no_verdict))
    # ...and the RUN-COVERAGE discriminator beside it, on EVERY run, spelled through its own ONE
    # contract site (T-11043). Recording it does NOT gate anything: unlike `no_data`, a single-track
    # run still anchors its subject's review-due clock, because suppressing it would derive a quality
    # judgement from a track count — the SPEC-0057 §4 fence this field is built to respect.
    data.update(track_coverage_fields(tracks))
    durable = None
    if theme == "T7" and REPO_ROOT is not None and CANONICAL_DOCS is not None:
        durable = durable_doc_metrics(REPO_ROOT, ENGINE_ROOT, CANONICAL_DOCS)
        data["durable_docs"] = durable          # report-only fields (SPEC-0120 §4) — additive, P5-safe
    # SPEC-0178 rules 7+9 (T-11159) — the exemption-case REVISION block on a T8 run. T8 ("Adoption —
    # done = adopted") is the theme that already asks whether a shipped mechanism is actually alive,
    # and it already hosts a report-only sub-lens of this exact shape (reverse-adoption), so the
    # revision EXTENDS the roster rather than adding a review surface (CHARTER §P1 F1/F2; SPEC-0057 §3
    # keeps the theme set small / fixed / owner-gated, which is why this is a sub-lens and not a T11).
    # The block is attached WHENEVER the fold ran — including for a project that declares no case, which
    # records "0 declared" rather than vanishing: an absent block and an empty one must not read alike.
    case_review = None
    if theme == "T8" and _case_review is not None:
        case_review = _case_review()
        data["case_review"] = case_review       # report-only, additive, P5-safe (the durable_docs shape)
    # Consumer sweep-payload budget (T-10369, grow-on-pull X-0275) — REPORT-ONLY. A CONSUMER-declared
    # theme whose probe is a `sweep` carries the byte-size its surfaces would inline, so a run that
    # would overrun the auditor's payload budget warns HERE instead of ABORTing after the 300s wall
    # (the X-0275 class on the sibling `audit adhoc` path). Additive event field + advisory print,
    # NEVER a gate — the `durable_docs` precedent exactly.
    sweep_payload = None
    zero_sweep = False
    if declared_entry is not None and REPO_ROOT is not None:
        probe = declared_entry.get("probe")
        sweep = probe.get("sweep") if isinstance(probe, dict) else None
        sweep_payload = sweep_payload_metrics(REPO_ROOT, sweep)
        if sweep_payload is not None:
            data["sweep_payload"] = sweep_payload   # additive report-only field, P5-safe
        # T-12063 (X-1262) — a sweep that reached NOTHING is not a review. Asked of the expansion
        # directly, never of `sweep_payload` above: that block is None when the payload budget is
        # disabled, and semaphore standing must not hinge on an unrelated telemetry opt-out.
        zero_sweep = sweep_matched_zero(REPO_ROOT, sweep)
    # The SEMAPHORE-STANDING discriminator, on EVERY run, spelled through its own ONE contract site.
    # Both causes of "this run did not review anything" converge on the one field the review-due fold
    # reads, so that fold keeps ONE predicate instead of a growing chain of skip-reasons. The event
    # still EMITS either way — proof-of-performance is unchanged (SPEC-0057 §6); only its standing is.
    uncounted_cause = ("0 files matched the declared `surfaces:` glob" if zero_sweep
                       else (f"{'tier' if tier else 'theme'} {subject_label} aborted / crashed / "
                             "never started") if no_verdict else None)
    data.update(semaphore_fields(uncounted_cause is None))
    # --dry-run (T-10125): READ-ONLY wiring proof — compute + PRINT the exact inspection_completed
    # payload shape (theme accepted by the §3 guard + a real checklist-hash criteria_ref) WITHOUT
    # appending the event. Proves a theme is wired (e.g. the T10 observation-loop theme at THIS
    # closure) without emitting a non-real inspection run into the journal (the card wants wiring
    # proven now, the real ревизия soak stays PLAN postcheck). Mutates nothing (D-0049-safe).
    if getattr(args, "dry_run", False):
        import json as _json
        print(f"inspection_completed (DRY-RUN — NOT emitted) {'tier' if tier else 'theme'}={subject_label} "
              f"findings={data['findings_count']} high={data['high_count']} criteria_ref={criteria_ref}")
        if no_verdict:
            print("  " + no_data_note(f"{'tier' if tier else 'theme'} {subject_label} aborted / crashed / never started"))
        # Rendered from the coverage contract's own renderer — this surface never composes the line
        # itself, so the dry-run and the real emit below can never drift apart (T-11043).
        print("  " + track_coverage_note(tracks_covered(data)))
        if uncounted_cause is not None:
            # The preview shows semaphore standing for the same reason it shows no_data: a wiring
            # proof that hid the one thing this run would NOT do would prove the wrong thing.
            print("  " + semaphore_note(uncounted_cause))
        print("payload: " + _json.dumps(data, ensure_ascii=False, sort_keys=True))
        print("  (--dry-run: read-only wiring proof — payload shape shown, no journal write; drop "
              "--dry-run to emit the real run-event, SPEC-0057 §6)")
        if sweep_payload is not None:
            print(sweep_payload_advisory(sweep_payload))
        if case_review is not None:
            for _line in case_review_report(case_review):
                print(_line)
        return
    # --task (T-10320): tie the run to a task id so a card whose AC names an inspection_completed
    # probe renders its proof in the audit-post packet (_ac_probe_evidence_events_for ties by
    # task_id == the audited task). Omitted → None (back-compat: an untied run, unchanged).
    task_id = (getattr(args, "task", None) or "").strip() or None
    _append_event("inspection_completed", task_id, data)
    print(f"inspection_completed emitted — {'tier' if tier else 'theme'}={subject_label} "
          f"findings={data['findings_count']} high={data['high_count']} criteria_ref={criteria_ref}")
    # T-11043 — every run SAYS its track coverage, from the contract's own renderer. Printed
    # unconditionally, including the NOT-RECORDED case: a run that stays silent about its coverage is
    # exactly the run this card exists to stop reading like a converged one.
    print("  " + track_coverage_note(tracks_covered(data)))
    if zero_sweep:
        # Rendered from the ONE semaphore face — this surface never spells its own sentence. Printed
        # for the zero-sweep cause only: the no_verdict cause already says the same thing in its own
        # words just below, and saying it twice would read as two separate problems.
        print("  " + semaphore_note("0 files matched the declared `surfaces:` glob"))
        print("  (the declared `surfaces:` value matches nothing in this checkout — fix the glob, "
              "then re-run; `init --declare-theme` warns about this at declare time, T-12063/X-1262)")
    if no_verdict:
        # Rendered from the contract's own renderer — this surface never spells the face itself.
        print("  " + no_data_note(f"{'tier' if tier else 'theme'} {subject_label} aborted / crashed / never started"))
        print("  (recorded as NO-DATA: it does NOT mark the subject reviewed and does NOT reset its "
              "review-due clock — re-run the sweep when the cause clears, SPEC-0173 rule 1)")
    print("  (one run-event per subject, even on zero findings; criteria_ref carries the checklist-hash "
          "so a later checklist edit makes this run detectably stale — SPEC-0057 §6)")
    if sweep_payload is not None:
        print(sweep_payload_advisory(sweep_payload))
    if case_review is not None:
        # Rendered from the ONE contract site above — this surface never spells the vocabulary itself.
        for _line in case_review_report(case_review):
            print(_line)
    if durable is not None:
        # The swept / excluded / no-data half of this line is RENDERED by the result contract's own
        # renderer (SPEC-0173 rules 1+2) — this surface never re-spells that vocabulary itself.
        print(f"  durable-doc probe (SPEC-0120, report-only): {result_contract_headline(durable)} "
              f"est-tokens={durable['est_tokens']} "
              f"over-band={len(durable['over_band'])} over-ceiling={len(durable['over_ceiling'])} "
              f"over-band-bytes={len(durable['over_band_bytes'])} "
              f"over-ceiling-bytes={len(durable['over_ceiling_bytes'])} "
              f"cyrillic={len(durable['cyrillic'])}")
        # Per-doc rows for every doc flagged on EITHER size axis (SPEC-0120 §3 "per durable doc"). The
        # full per-doc record stays in the event's `durable_docs.docs`; printing all of it would be
        # noise, not a report. A clean corpus prints the swept line above and no rows (F-#2).
        _flags = {}
        for _bucket, _tag in (("over_ceiling", "over-ceiling(lines)"), ("over_band", "over-band(lines)"),
                              ("over_ceiling_bytes", "over-ceiling(bytes)"),
                              ("over_band_bytes", "over-band(bytes)")):
            for _rel in durable[_bucket]:
                _flags.setdefault(_rel, []).append(_tag)
        if _flags:
            _by_path = {d["path"]: d for d in durable["docs"]}
            for _rel in sorted(_flags, key=lambda r: -_by_path[r]["bytes"]):
                _d = _by_path[_rel]
                print(f"    {_rel} lines={_d['lines']} bytes={_d['bytes']} "
                      f"est_tokens={_d['est_tokens']} [{', '.join(_flags[_rel])}]")
        # The structural exclusions print BESIDE the flagged rows, from the contract's own renderer
        # (SPEC-0173 rule 2): the reader sees what was reached AND what could not be, in one result.
        for _line in result_contract_exclusion_rows(durable):
            print(_line)
        # SPEC-0173 rule 4 (T-10839) — the operator-facing half of the same filter. A doc the scan
        # could not READ is neither swept nor excluded-by-construction, so it appears in NEITHER block
        # above; without this it left the report silently and the run read as a smaller clean corpus.
        # Rendered from the ONE degrade face — this surface never spells it either.
        for _line in degrade_rows(durable["degraded"]):
            print(_line)
        print("  (report-only CANDIDATES — never a gate, CHARTER non-goal #2; TWO size axes, reported "
              "separately — SPEC-0120 §3: lines over-band=split-candidate (>500) / over-ceiling="
              "must-split (>=800); bytes over-band (>40000) / over-ceiling (>=63000 ~ the 25K-token "
              "one-bounded-read page cap). A DENSE doc can pass the line axis and still be "
              "single-read-unsafe — the byte axis catches it.)")
