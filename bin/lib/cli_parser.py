"""cli_parser — the argparse GRAMMAR of `bin/yitc-v2`: `build_parser` (the whole verb inventory,
ONE function relocated whole), the top-level `_HelpInventoryAction` (the fetch-receipt `--help`) and
its `_warn_help_receipt_uncredited` sibling — extracted BYTE-IDENTICAL out of `bin/lib/cli.py`
(T-12699, plan `extract-the-13-over-budget-bin-lib-modules-into-le` C10, lessons/library-extraction.md).

WHY THIS LEAF EXISTS. `build_parser` was the single largest function in the host (3 580 lines at the
claim merge-base) and the 2026-09-13 architecture lens named the host over budget; the grammar is a
cohesive subsystem that reads the host only through NAMES (the `cmd_*` verb callables, the parser-facing
vocabulary and a handful of host constants), so it moves as ONE accept-unit with no behaviour change.

SEAM (the full inject-residue shape, T-9340 / T-9341). Every non-stdlib, non-moved free name of
`build_parser` is a KEYWORD-ONLY parameter, supplied by the host residue `cli.py#build_parser` from the
host's LIVE globals at call time — so `-C` rebinds and `monkeypatch.setattr(yitc, "cmd_*", ...)` stay
honoured, and the body is byte-identical to its host original. `BUILD_PARSER_INJECTS` is DERIVED from
that signature (never a second hand-list).

CLASS MOVER (plan Done criterion 1 amendment (c), 2026-09-17). `_HelpInventoryAction` is constructed
and invoked by argparse itself (`action=`), so it cannot take injections: its four host collaborators
(`_CountingTee`, `_emit_cli_invoked`, `_rebind_repo_root`, `_resolve_c_flag`) are module-local
TRAMPOLINES that resolve the host name AT CALL TIME through the resolver `bind_host(resolve)` installs —
called ONCE by the host with its live-globals lookup, so a monkeypatch on the host is still honoured.
The zero-arg sibling `_warn_help_receipt_uncredited()` the class calls BARE stays zero-arg; its one
free name, the host constant `SELF_REF_ENV`, is host-BOUND into this module by the same call.

Identity-agnostic KERNEL leaf (SPEC-0073 bin/ HARD class): stdlib + the `lib.vocab` leaf only; it NEVER
back-imports the host (`tests/test_bin_lib_leaf_no_host_import.py`). Spec-less by design (SPEC-0005
admission: a byte-identical relocation mints no rule) — the governing specs keep their homes and
repoint their `implements:` anchors here.
"""
from __future__ import annotations

import argparse
import functools
import inspect
import shlex
import sys

from lib import vocab  # the argparse vocabulary leaf (parser-facing constants) — read as `vocab.<NAME>`


# T-13105 (SPEC-0078 §5) — a verb's `--read-only` posture is DECLARED on its own `set_defaults`, the
# ONE admission authority `bin/lib/cli.py#_read_only_admission` reads (it replaced the hand list
# `READ_ONLY_ADMITTED_VERBS`). Two keys, each either `<reason>` (verb-scoped) or `(<flag dest>, <reason>)`
# (flag-scoped — the `_zero_write_view` keying: it applies only when that PARSED flag is set):
#   `read_only_admit`  — runs under `-C <repo> --read-only`; the value says WHY it is safe there;
#   `read_only_refuse` — a writer refused BY NAME; the value is the reason the refusal prints.
# An unmarked verb is refused (fail-closed). The `cli_invoked_verb` read marker does NOT admit on its
# own: some writers wear it (deviation `cli-invoked-verb-marker-set-on-writing-verbs`), so each read is
# marked here too. The reason vocabulary — the two reasons the old list's comment carried, plus two:
RO_EVIDENCE = ("journal-append-only evidence verb: its rows are redirected to the reader's own journal "
               "and it touches no file in the target")
RO_RECEIPT = ("no write and no event of its own: its only row is the cli_invoked invocation receipt "
              "(T-12846), which goes to the reader's own journal")
RO_READ = "pure read (the cli_invoked_verb read marker): its receipt goes to the reader's own journal"
RO_VIEW = "pure view: folds durable state and prints, emitting nothing"
RO_ZERO_WRITE = "zero-write form of the verb: prints and returns before any write or run"


# ---------------------------------------------------------------------------
# Host binding seam — the CLASS-mover rule (plan Done criterion 1 (c)). The host calls
# `bind_host(lambda name: globals()[name])` ONCE at import; until then every trampoline (and the
# host-bound constant) is loudly unbound rather than silently defaulted.
# ---------------------------------------------------------------------------
def _unbound(name: str):
    raise RuntimeError(f"cli_parser: host name {name!r} requested before `cli_parser.bind_host()` — "
                       "the host (bin/lib/cli.py) binds its live globals lookup at import (T-12699)")


_resolve_host = _unbound


def bind_host(resolve) -> None:
    """Install the host's live-globals lookup (`resolve(name) -> object`) behind the trampolines and
    bind the host constant(s) a bare-called zero-arg mover reads. Called ONCE by `bin/lib/cli.py`."""
    global _resolve_host, SELF_REF_ENV
    _resolve_host = resolve
    SELF_REF_ENV = resolve("SELF_REF_ENV")


def _CountingTee(*a, **kw):
    return _resolve_host("_CountingTee")(*a, **kw)


def _emit_cli_invoked(*a, **kw):
    return _resolve_host("_emit_cli_invoked")(*a, **kw)


def _rebind_repo_root(*a, **kw):
    return _resolve_host("_rebind_repo_root")(*a, **kw)


def _resolve_c_flag(*a, **kw):
    return _resolve_host("_resolve_c_flag")(*a, **kw)


class _HelpInventoryAction(argparse.Action):
    """Top-level `--help`/`-h` that ALSO emits a session fetch-receipt (T-9786 / X-0158): scanning the
    verb inventory is the read the `_require_help_read` gate requires at `worktree new` / `task file` /
    `land`. Replaces argparse's default help action on the TOP-LEVEL parser ONLY (subcommand `--help`
    stays the plain argparse help — a subcommand's help is NOT the inventory). Reuses the existing
    `cli_invoked` emit (node_id == the help sentinel) — NO new event/store (P1 F1)."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        # Rebind to the -C target (if any) FIRST so the receipt lands in THAT checkout's journal — the
        # same journal the -C session's later worktree new / task file / land gate reads (git -C
        # prior-art). Best-effort: a bad -C must never stop --help from printing. (`-C` precedes
        # `--help` on the command line in normal usage, so namespace.directory is already set here.)
        read_only = getattr(namespace, "read_only", False) or "--read-only" in sys.argv[1:]
        emit_ok = True
        try:
            directory = getattr(namespace, "directory", None)
            if directory:
                emit_ok = not read_only  # fail CLOSED: a -C read-only receipt emits only once redirected
                _rebind_repo_root(_resolve_c_flag(directory))
                # T-13006 (SPEC-0078 §5): under `--read-only` the receipt must NOT land in the -C
                # target — pin the append side to the reader's journal exactly as main() would. The
                # raw-argv token covers `--help` placed BEFORE `--read-only` (not yet parsed here).
                if read_only:
                    _resolve_host("_enter_read_only_mode")()
                emit_ok = True
        except Exception:
            pass
        # Tee print_help so the receipt records the inventory's real stdout size (parity with the T-0113
        # read-verb path), then emit the fetch-receipt (best-effort — help has already printed, so a
        # journal hiccup must not turn a --help into a non-zero exit).
        real_stdout = sys.stdout
        tee = _CountingTee(real_stdout)
        sys.stdout = tee
        try:
            parser.print_help()
        finally:
            sys.stdout = real_stdout
        if not emit_ok:
            parser.exit()  # read-only redirect failed — skip the receipt rather than write the target
        try:
            # T-10784 (X-0615): the emit hands back the ref it stamped the GATE-BEARING receipt under.
            # None ⇒ identity was unresolvable ⇒ `_require_help_read` will refuse later, so SAY SO NOW,
            # at the scan, instead of letting the first gated verb be the first signal. Inside the same
            # best-effort guard: a journal hiccup must never turn a `--help` into a non-zero exit.
            if _emit_cli_invoked("--help", sys.argv[1:], tee.nbytes, tee.nlines, 0) is None:
                _warn_help_receipt_uncredited()
        except Exception:
            pass
        parser.exit()


def build_parser(*, EFFORT_TIERS, PAUSE_REASONS, PLACEMENT_REALMS, PLAN_CONSULT_GATES, PLAN_STATUSES, RESERVED_DATA_KEYS, STAGE_AXIS_NAMES, TASK_CLASSES, TASK_FILING_STATUSES, TASK_LIST_STATUSES, TASK_PRIORITIES, TRIAGE_CONTENT_EVENT_TYPES, _HelpInventoryAction, _NO_TESTS_MIN_REASON_CHARS, _SELF, _absorb_trailing_reason_words, _worktree_parent_leaf, cmd_audit, cmd_audit_adhoc, cmd_audit_canary_backstop, cmd_audit_consult, cmd_audit_decide, cmd_audit_run, cmd_audit_status, cmd_blocked_on_land, cmd_cage_preflight, cmd_config_get, cmd_config_list, cmd_config_set, cmd_cross_ack, cmd_cross_close, cmd_cross_dispute, cmd_cross_done, cmd_cross_inbox, cmd_cross_intake_draft, cmd_cross_outbox, cmd_cross_pick, cmd_cross_reject, cmd_cross_request, cmd_cross_show, cmd_debt, cmd_decision_new, cmd_deploy, cmd_dispatch, cmd_error_file, cmd_error_list, cmd_error_promote, cmd_error_resolve, cmd_error_show, cmd_event, cmd_followup_add, cmd_followup_arm, cmd_followup_drop, cmd_followup_list, cmd_followup_promote, cmd_followup_show, cmd_followup_unarm, cmd_frontend_errors, cmd_grants_authorize, cmd_grants_exercise, cmd_grants_identity, cmd_grants_reach, cmd_grants_report, cmd_grants_trail, cmd_graph_build, cmd_graph_conformance, cmd_graph_query, cmd_graph_release_view, cmd_host_apply, cmd_init, cmd_inspect_record, cmd_journal_query, cmd_journal_redact, cmd_journal_sync, cmd_land, cmd_live_probe, cmd_memory_consume, cmd_memory_seed, cmd_nightly, cmd_plan_check, cmd_plan_draft, cmd_plan_file, cmd_plan_list, cmd_plan_show, cmd_plan_stage, cmd_plan_to_idea, cmd_profile, cmd_release_check, cmd_release_install, cmd_release_update, cmd_release_verify, cmd_retire_read_site, cmd_scenario_list, cmd_scenario_new, cmd_scenario_show, cmd_session_context, cmd_session_handoff, cmd_session_pick, cmd_session_start, cmd_spec_edit, cmd_spec_ledger_label, cmd_spec_new, cmd_spec_reverify, cmd_stage, cmd_task_analyze, cmd_task_claim_landed, cmd_task_close, cmd_task_commit, cmd_task_execute, cmd_task_file, cmd_task_intake, cmd_task_list, cmd_task_pause, cmd_task_pick, cmd_task_plan, cmd_task_reclaim, cmd_task_refuse, cmd_task_resume, cmd_task_show, cmd_task_test, cmd_task_update, cmd_triage_remedy, cmd_triage_run, cmd_triage_sweep, cmd_v1_quiesce, cmd_venue_delete, cmd_venue_publish, cmd_venue_raise, cmd_venue_seed, cmd_venue_show, cmd_venue_unpublish, cmd_verify_durations, cmd_work_commit, cmd_work_publish, cmd_work_tag, cmd_worktree_adopt, cmd_worktree_clear_yield_offer, cmd_worktree_new, cmd_worktree_park, cmd_worktree_recover_land, cmd_worktree_sweep, cmd_worktree_sync, cross, deploy_mod, grants, inspection, journal_mod) -> argparse.ArgumentParser:
    # add_help=False + a custom top-level help action (T-9786): the inventory --help emits a fetch-receipt.
    p = argparse.ArgumentParser(prog="yitc-v2", description="V2 self-tooling CLI", add_help=False)
    p.add_argument("-h", "--help", action=_HelpInventoryAction,
                   help="show this help (the verb inventory) and record a session fetch-receipt (T-9786)")
    # T-0334: global `-C <path>` — operate on the given checkout regardless of caller cwd (git's
    # `git -C` / make's `make -C` prior-art). Resolves to that checkout's git toplevel and rebinds
    # the single REPO_ROOT anchor in main() BEFORE the verb runs, so land / work commit / task
    # commit (and every other worktree-bound verb) run cwd-independently. Explicit path ONLY — no
    # auto-detect of "the single open worktree" (concurrent sessions make that inference wrong).
    p.add_argument("-C", "--directory", metavar="PATH",
                   help="operate on the checkout at PATH regardless of cwd (git -C prior-art); "
                        "resolves to that checkout's git toplevel. Explicit ABSOLUTE path only — no "
                        "auto-detect, and a relative path is REFUSED (it would resolve against the "
                        "caller's cwd, so the same command text names a different repo — T-11763).")
    # T-10859 (SPEC-0078 §5): the READ-ONLY companion to `-C`. A bare `-C` means "become that repo",
    # which is correct for a consumer-OPERATING verb (init / deploy / quiesce / land) where writing
    # into the target IS the point — unchanged. What was missing beside it was a way to READ a repo for
    # evidence without appending anything to it: a kernel session could not even `-C <consumer> graph
    # query` without leaving a cli_invoked row there (the T-10840 territory breach).
    p.add_argument("--read-only", action="store_true", dest="read_only",
                   help="with -C: gather EVIDENCE from that checkout without writing to it — journal "
                        "appends go to this session's own journal, and any write resolving inside the "
                        "target is refused (SPEC-0078 §5). Admits pure reads plus `session start` / "
                        "`inspect record`. Named invocation: "
                        "`bin/yitc-v2 -C <consumer> --read-only inspect record --theme T7 --task T-XXXX`.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("event", help="Append event to events.jsonl")
    ev.add_argument("type", help="event type (snake_case)")
    ev.add_argument("--task", help="task / decision / spec / phase ID")
    # T-10735 (X-0603): the reserved set is INTERPOLATED from the same constant the runtime check
    # reads — never hand-copied, so --help cannot drift from the refusal.
    ev.add_argument("--data",
                    help="JSON object merged into event.data. Reserved top-level keys (refused, "
                         "envelope-owned): " + ", ".join(sorted(RESERVED_DATA_KEYS))
                         + " — the refusal names where each value belongs instead. TRIAGEABLE (what "
                           "the WARN checks, T-11417/T-11666): for a triage-class type ("
                         + ", ".join(TRIAGE_CONTENT_EVENT_TYPES)
                         + ") the payload must carry at least ONE non-blank value you supplied; "
                           "verb-stamped keys (actor, --commit, --stage, derived wait_reason/realm/"
                           "disposition) do not count. A second WARN (T-11775) notices a payload "
                           "that is not empty but still has no SUBJECT: an `impact` you supplied "
                           "that is blank or a bare severity word (low/medium/high) reads as a "
                           "description and is not one. A descriptive `fingerprint` alone still "
                           "PASSES with no WARN — the bar is not prose length. What triage actually "
                           "needs: what happened, where, what it cost, "
                           "and a stable `fingerprint` (without one the row cannot be "
                           "recurrence-matched or root-clustered and drops out of triage — its own "
                           "WARN). Validate a payload without writing a row: --check. Compose a payload "
                           "too long to inline under a per-invocation temp file in the gitignored `.scratch/` dir "
                           "(`" + vocab.SCRATCH_TEMPFILE_RECIPE + "`) — never the checkout root, "
                           "where a commit verb's add-all would stage it (T-12930), and never a "
                           "fixed shared temp name: concurrent "
                           "sessions share that namespace and a substitution can read another "
                           "session's file (T-11676 / X-1132). Given-but-EMPTY is REFUSED; to emit "
                           "no payload, omit the flag. For an `owner_directive` two payload keys "
                           "are READ by the SPEC-0204 rule-2 resolver (T-12401): `cards` — a list of "
                           "T-NNNN ids (or a plan slug) this directive covers, which is how a row "
                           "covers a card it does not name in prose; and `captured_via` — the value "
                           "`controller-delegated` marks a Controller-written row standing in for a "
                           "verbatim owner cue, which resolves ONLY through the owner row its `text` "
                           "cites (`events.jsonl#ts=<ISO>`), and that row must already exist and "
                           "precede it. Full recipe: `yitc-v2 audit decide --help`.")
    ev.add_argument("--commit", help="git SHA, written to data.commit")
    ev.add_argument("--stage", type=int, help="lifecycle stage 1-9, written to data.stage")
    ev.add_argument("--source-ref",
                    help="source locator written to event.source_ref. PERSISTS FOR ANY EVENT TYPE "
                         "(T-11741) — an explicitly given value is stored, or the emit REFUSES naming "
                         "the reason; it is never accepted-and-dropped. Refused: an empty value (the "
                         "flag ASSERTS a locator — omit it to emit none) and one containing "
                         "whitespace (uncitable — `events.jsonl#source_ref=<ref>` takes a "
                         "whitespace-free ref). Otherwise opaque and stored verbatim, so it can be "
                         "cited as `events.jsonl#source_ref=<ref>` wherever that locator form is "
                         "accepted (a `task close` probe settlement, a commit `from:` trailer) — "
                         "which is what lets a citation stay UNIQUE when several rows share a "
                         "second. For an owner_directive it is additionally an "
                         "owner-transcript locator <transcript-path>[#uuid:<entry-uuid>] and "
                         "REQUIRED-by-resolution (T-10600): when omitted it is derived from this "
                         "session's provider transcript, and registration REFUSES if it cannot be "
                         "resolved or does not open on disk.")
    ev.add_argument("--check", action="store_true",
                    help="NO-WRITE validation (T-11666): run every pre-append check on the REAL emit "
                         "path — same refusals, same exit codes, same WARNs — print a verdict, and "
                         "append NOTHING (the journal is left byte-identical). Use it to exercise the "
                         "payload contract without authoring a permanent row in an append-only "
                         "journal. Not judged: the recurrence reopen + kernel-bound cross auto-file, "
                         "which run only on a row that exists.")
    ev.set_defaults(func=cmd_event, read_only_refuse="appends a journal row — capture from your own checkout, "
                                                    "without -C --read-only")

    # T-0995 — consumer born-empty delivery. Idempotent; intended via the `-C <path>` global flag.
    initp = sub.add_parser("init", help="Idempotently deliver a consumer its born-empty scaffolds "
                                        "(MEMORY.md, yitc-ops.yaml, .no-v1-hooks, .gitignore) — use with -C <path>")
    # T-9492 / X-0083 — the conscious-waive for a pre-existing NON-EMPTY legacy CROSS-TASKS.md (the
    # retired per-repo cross surface). Without it, init REFUSES on detecting content beyond the born-empty
    # template (it would silently orphan an un-migrated item); the flag VALUE is the recorded waive reason.
    initp.add_argument("--waive-legacy-cross-tasks", dest="waive_legacy_cross_tasks", metavar="REASON",
                       default=None,
                       help="consciously waive the legacy-CROSS-TASKS.md guard (T-9492): proceed past a "
                            "pre-existing non-empty CROSS-TASKS.md, recording REASON in the consumer_init "
                            "event. Default: refuse + require migrate-or-waive.")
    # T-9490 / SPEC-0093 rule 13 / SPEC-0101 §4 — the GOVERNED adopt path: declare+cite a SHARED `adoptable`
    # extension in this consumer's yitc-ops.yaml `extensions.adopts`. OPT-IN (no flag = adopts nothing).
    # Refuses a missing / non-adoptable SPEC-XXXX (write-time cite-resolution); idempotent. Repeatable.
    initp.add_argument("--adopt-extension", dest="adopt_extension", metavar="SPEC-XXXX",
                       action="append", default=None,
                       help="adopt+cite a shared `adoptable` extension into this consumer's yitc-ops.yaml "
                            "extensions.adopts (SPEC-0093 rule 13). Refuses a missing/non-adoptable spec; "
                            "idempotent. Repeat to adopt several. Discover via `graph query --extension`.")
    # T-10775 / SPEC-0170 — the source declaration an extension's own qualifying-source contract demands.
    # A MODIFIER of --adopt-extension (no mode of its own): without it, adopting such an extension writes a
    # bare cite that the carrier's next sweep fail-closes on, wedging the carrier the verb just wrote.
    initp.add_argument("--extension-source", dest="extension_source", metavar="SPEC-XXXX:K=V,K=V",
                       action="append", default=None,
                       help="declare the qualifying SOURCE for an adopted extension that requires one "
                            "(currently SPEC-0170, the frontend-error conveyor), e.g. "
                            "`SPEC-0170:kind=postgres-table,container=app-db-1,table=system_errors,"
                            "window_field=occurred_at,row_id_field=id,message_field=message,"
                            "retention_days=90,classes=code-defect|server-defect|unhandled-rejection|"
                            "http-client-error`. The adopt is REFUSED, with the failing property NAMED, "
                            "unless the source qualifies. Repeat once per adopted spec.")
    # T-10171 / SPEC-0093 / SPEC-0143 Rule 2 — the GOVERNED per-concern adoption-record path: write a
    # {status, version, owner, at} entry PER kernel concern into this consumer's yitc-ops.yaml `adoption:`
    # section. OPT-IN (no flag = no adoption section touched; absence = not-yet-adopted, surfaced later as
    # drift). Resolves the concern SECTION + records its derived registry version at write-time; idempotent.
    initp.add_argument("--adopt-concern", dest="adopt_concern", metavar="SECTION:STATUS:OWNER",
                       action="append", default=None,
                       help="record a per-concern adoption entry in this consumer's yitc-ops.yaml "
                            "adoption: section (SPEC-0143 Rule 2), e.g. `coverage:adopt:sergey`. STATUS is "
                            "adopt/waive/na; the concern-version is looked up from the kernel registry; "
                            "idempotent. Repeat to record several. Concerns: graph/concern-registry.json.")
    # T-11985 / SPEC-0189 rule 8 — the BIRTH-RATIFICATION confirmation. A born declaration that RELAXES
    # a control is written only against an explicit owner confirmation, recorded as that declaration's
    # ratification provenance; this flag is how a NONINTERACTIVE birth carries one. Without it (and with
    # no TTY to prompt on) the relaxing declaration is NOT written and the section is left absent, which
    # reads fail-closed — scripted creation supplying neither gets a PROTECTED project, by design.
    initp.add_argument("--confirm-born-permissive", dest="confirm_born_permissive", metavar="SECTION:OWNER",
                       action="append", default=None,
                       help="confirm, for THIS birth, that a concern whose born value is declared "
                            "PERMISSIVE (`born_stance: permissive`) may be written with its relaxing "
                            "declaration live — e.g. `audit_scrutiny:sergey`. OWNER is the confirming "
                            "handle, recorded as the declaration's RATIFICATION PROVENANCE (an "
                            "`adoption:` record under that handle, never the `init` sentinel), so the "
                            "project is born declined AND ratified in one act (SPEC-0189 rule 8). "
                            "Without a confirmation the section is left ABSENT and reads fail-closed. "
                            "Repeat once per concern; refused for a concern with no permissive born "
                            "value.")
    # T-10535 / X-0401 / SPEC-0093 rule 12 — the GOVERNED inspection-theme declare path: append a theme to
    # this consumer's yitc-ops.yaml `inspection.themes[]` as a SURGICAL TEXT edit that preserves every
    # existing byte, incl. the kernel contract delivered through the carrier's COMMENTS. It exists because
    # the only prior path was a hand-edit, and <project>'s `yaml.safe_load`->`yaml.dump` round-trip
    # destroyed all 436 comment lines of its carrier. OPT-IN, idempotent, repeatable.
    initp.add_argument("--declare-theme", dest="declare_theme", metavar="SLUG:CADENCE:PROBE",
                       action="append", default=None,
                       help="declare a local inspection (ревизия) theme in this consumer's yitc-ops.yaml "
                            "inspection.themes[] (SPEC-0093 rule 12) — a comment-preserving TEXT append, "
                            "never a YAML round-trip. CADENCE is weekly|monthly|quarterly; PROBE is EXACTLY "
                            "ONE KIND — `view=<graph-query-lens>` OR "
                            "`sweep=<surfaces>|<check>[|<check>...][|against=<x>]`. E.g. "
                            "`ui-drift:monthly:view=ui-surfaces` or "
                            "`secret-leak:weekly:sweep=bin/**|no plaintext secret`. Retires the born "
                            "`inspection:` waiver on the first declare + mirrors the adoption stance; "
                            "idempotent. Repeat to declare several.")
    # T-10982 / SPEC-0093 rule 11 — the GOVERNED carrier-BACKFILL path: hand an EXISTING consumer a
    # top-level section that became MANDATORY after it was init'ed. It exists because the rule-11 update
    # path skips mandatory sections by construction, so re-running init could never deliver one — and a
    # delivery attempted inside the ordinary init is rewound by the T-10688 sweep-atomicity rollback,
    # since an UNANSWERED section makes that sweep refuse by construction. Delivery-ONLY: no scaffold,
    # no sweep, nothing answered. OPT-IN, idempotent.
    # T-12475 / SPEC-0119 — rewrite a stale kernel contract-comment citation (a kernel spec re-home) to its
    # current home, comment lines only, from the re-home candidate `debt` already names. OPT-IN, idempotent.
    initp.add_argument("--rehome-contract-comments", dest="rehome_contract_comments", action="store_true",
                       help="rewrite stale kernel contract-comment citations in this consumer's "
                            "yitc-ops.yaml to their current spec home (the re-home candidates `debt` "
                            "names) — COMMENT lines only, prose and values byte-identical; a fully "
                            "stripped carrier is never touched. Idempotent: a second run is a no-op.")
    initp.add_argument("--backfill-mandatory", dest="backfill_mandatory", action="store_true",
                       help="deliver into this consumer's yitc-ops.yaml any TOP-LEVEL section that "
                            "became MANDATORY after it was init'ed — as the born GUIDANCE with the born "
                            "ANSWER STRIPPED (SPEC-0093 rule 11). DELIVERY-ONLY: it seeds no scaffold, "
                            "runs NO declare-or-waive sweep and answers NOTHING on the project's behalf "
                            "(back-delivering the born waiver would assert an unverified fact about "
                            "this project). A zero exit does NOT mean conformant — THE NEXT ORDINARY "
                            "`init` WILL REFUSE until each delivered section is declared or waived, "
                            "which is the point. Never rewrites a section already present; idempotent.")
    # T-10271 / X-0243 — a bare init commits its scaffold + adoption-record set straight to `main` (the
    # sanctioned bootstrap-commit exception); this previews that set first. A pure read-path over the SAME
    # planning code (cmd_init's mutation seams swapped for recorders), never a second planner.
    initp.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="fully read-only preview: print the exact file set (write + remove) and "
                            "adoption records a real init would deliver, WITHOUT writing anything, "
                            "emitting any event, or making the bootstrap commit to main")
    # T-10498 / X-0358 / X-0365 — init NEVER silently rewrites an EXISTING scaffold. A drifted
    # kernel-managed scaffold (bin/security-audit, the engine-owned templates) is REPORTED as a pending
    # refresh (the staleness signal) and applied only under THIS flag. Bootstrap of a MISSING scaffold
    # is unaffected — it still writes flag-free (the T-9463 chicken-and-egg).
    initp.add_argument("--refresh-scaffolds", dest="refresh_scaffolds", action="store_true",
                       help="APPLY the pending kernel-scaffold refreshes a bare init only reports "
                            "(T-10498): re-derive drifted kernel-managed scaffolds from the engine. "
                            "Without it an EXISTING scaffold is never rewritten. This is the "
                            "DESTRUCTIVE leg only — the additive half (missing born sections, absent "
                            "scaffolds) is delivered by a BARE flag-free init and never needs this. "
                            "A re-derive that would DELETE lines the local copy carries is REFUSED "
                            "(T-10886) and init exits non-zero. Composes with --dry-run (previews the "
                            "refresh set, writes nothing).")
    # T-10886 / X-0713 — the per-file acknowledgement. Refuse-by-default protects consumer-landed lines;
    # this is how an operator who has READ the printed diff adopts the kernel copy anyway, one named path
    # at a time (never a blanket --force, which would restore the silent-deletion shape wholesale).
    initp.add_argument("--accept-scaffold-loss", dest="accept_scaffold_loss", action="append",
                       metavar="PATH", default=[],
                       help="acknowledge, for ONE named repo-relative scaffold, that "
                            "--refresh-scaffolds may DELETE lines your local copy carries, and take the "
                            "kernel copy anyway (repeatable; only meaningful with --refresh-scaffolds)")
    initp.set_defaults(func=cmd_init, read_only_refuse="births the target — writes its scaffolds and commits them")

    # T-9390 / SPEC-0094 §1 — the governed deploy / rollback seam. Runs the project-declared
    # deploy:/rollback: command (yitc-ops.yaml, SPEC-0093) — that command IS the executable smoke/health
    # gate — and emits deploy_completed{revision,project,kind} on exit-0 (none on a non-zero gate).
    dep = sub.add_parser("deploy", help="Run the project-declared deploy:/rollback: command (the "
                                        "executable smoke gate) + emit deploy_completed on exit-0 "
                                        "(SPEC-0094 §1) — use with -C <path>")
    dep.add_argument("--rollback", action="store_true",
                     help="run the rollback: section instead of deploy: (records kind=rollback)")
    dep.add_argument("rev", nargs="?", default=None,
                     help="target revision to roll back TO (REQUIRED with --rollback; T-9407, "
                          "SPEC-0094 §1) — resolved to a sha, passed positionally to the rollback: "
                          "command, and recorded as the live revision in deploy_completed. Ignored "
                          "by a plain deploy (which ships HEAD); supplying it without --rollback errs.")
    # T-9415 / SPEC-0097 — the deploy-autonomy GATE. `--class` classifies the deploy at deploy time
    # (kernel-owned A/S/C1/C2 vocabulary); the gate reads the carrier `deploy.policy` + selects the
    # per-class evidence requirement. REQUIRED only on a project that opted into autonomous deploys
    # (declared `deploy.policy.classes`); a pre-policy / waived carrier ignores it (back-compat).
    dep.add_argument("--class", dest="deploy_class",
                     choices=list(deploy_mod.DEPLOY_CLASSES) + [deploy_mod.HOST_CONFIG_CLASS],
                     help="deploy class (SPEC-0097): A=code-only · S=security-surface · C1=expand/"
                          "contract migration · C2=destructive/irreversible · host-config=host nginx/"
                          "vhost change. A/S/C1 select the per-class evidence from deploy.policy.classes; "
                          "C2 escalates to the owner; host-config is NOT image-deployable (it rides the "
                          "human-apply seam SPEC-0111 + the three-evidence task-close gate, §10).")
    # T-11932 / SPEC-0094 §1 (X-1201) — the NAMED-TARGET passthrough. A project whose only governed
    # deploy path is the bare `deploy.command` can record only the surface that command addresses (in
    # practice PRODUCTION), so a sandbox it deploys far more often earns no deploy_completed at all.
    # `--target <name>` resolves a named entry under `deploy.targets`; OMITTING it never reads that
    # block, so every existing consumer is untouched. An unknown name REFUSES fail-closed — it must
    # never fall back to the default command, which on a typo would deploy production.
    dep.add_argument("--target", dest="deploy_target", metavar="NAME",
                     help="deploy the NAMED target declared under `deploy.targets` in yitc-ops.yaml "
                          "(`targets: {<name>: {command: <cmd>, production: true|false}}`) instead of "
                          "the default `deploy.command` (SPEC-0094 §1). The name is resolved BEFORE "
                          "anything runs and an unknown one REFUSES — it never falls back to the "
                          "default command. Each target must DECLARE `production:` explicitly; a "
                          "`production: false` target carries NO A/S/C1/C2 class (--class is refused "
                          "with it) and its deploy_completed records "
                          "`target: {name, production, deploy_class: null}` (SPEC-0097 §12). "
                          "With --rollback <rev>: runs the target's OWN `targets.<name>.rollback: "
                          "{command: <cmd>}` (never the top-level `rollback:`), admitted ONLY for a "
                          "`production: false` target that declares one — any other target REFUSES "
                          "(a production rollback is the unflagged `deploy --rollback <rev>`).")
    dep.add_argument("--owner-approved", dest="owner_approved", action="store_true",
                     help="the owner took the escalation decision — proceed a Class-C2 deploy (NOT "
                          "autonomous; SPEC-0097 §5). The verb first runs the pre-deploy dump the "
                          "carrier declares under `deploy.policy.classes.C1` and REFUSES if it fails; "
                          "with no dump declared it proceeds and prints that no backup is taken. "
                          "No effect on A/S/C1 or a pre-policy/waived project.")
    # T-10502 / SPEC-0155 rule 7 (X-0362/X-0363) — the OWNER-INVOKED, JOURNALED override of a security-gate
    # REJECT. The sibling of --owner-approved above (same owner-invoked, journaled escalation shape),
    # applied to the security-gate leg: during a live prod outage a build-time dep advisory that is not
    # even reachable from prod must not be the thing that keeps the GOVERNED restore path shut. Bounded by
    # construction — see `deploy._apply_security_gate_override`: severity-blocking rejects ONLY, every
    # blocking finding must be NAMED, and the bypass is journaled (never a silent skip).
    dep.add_argument("--security-override-advisory", dest="security_override_advisory", action="append",
                     metavar="ID",
                     help="OWNER-INVOKED (SPEC-0155 rule 7): override the pre-deploy security gate for "
                          "this named advisory — an exact GHSA-xxxx-xxxx-xxxx / CVE-YYYY-NNNN id, or the "
                          "finding's 16-hex fingerprint. REPEAT the flag once per blocking finding: the "
                          "override must name EVERY finding the gate blocked on, or it refuses. Requires "
                          "--security-override-reason. Valid ONLY for an open-critical/high (severity) "
                          "rejection — a stale / tampered / incomplete / identity-mismatched report is "
                          "NEVER overridable (that evidence does not describe the deployed code). Emits "
                          "`deploy_security_gate_overridden` (reason + advisories + the gate's own "
                          "blocking findings) and surfaces in `bin/yitc-v2 debt` — never a silent skip.")
    dep.add_argument("--security-override-reason", dest="security_override_reason", metavar="WHY",
                     help="the WHY for --security-override-advisory (REQUIRED with it; journaled verbatim) "
                          "— e.g. 'prod auth outage: advisory is a build-time dev-server dep, not "
                          "reachable in prod; fix = 3-major upgrade, tracked in T-XXXX'.")
    # T-9785 / SPEC-0094 §1 (X-0160) — print the canonical governed-deploy GUARD snippet a consumer
    # embeds at the top of its hand-runnable deploy.sh so a raw hand-run (which skips the class-gate +
    # pg_dump + deploy_completed) is REFUSED. Discoverable delivery: any consumer runs this to get the
    # exact current guard (single-SoT — DEPLOY_GUARD_SNIPPET in lib/deploy.py). Prints + exits; needs no
    # ops carrier / -C context.
    dep.add_argument("--print-guard", dest="print_guard", action="store_true",
                     help="print the canonical governed-deploy guard snippet (embed it at the top of a "
                          "hand-runnable deploy.sh so a raw hand-run is refused — SPEC-0094 §1) + exit. "
                          "ADD --rollback for the ROLLBACK flavour (T-10736): the snippet for a "
                          "hand-runnable rollback script, whose refusal names `deploy --rollback <rev>` "
                          "instead of the forward-deploy form — a wrong recovery instruction on the "
                          "emergency path is what this flavour exists to prevent (X-0597). No <rev> "
                          "needed: nothing is run.")
    dep.set_defaults(func=cmd_deploy, read_only_admit=("print_guard", RO_ZERO_WRITE))

    # T-9395 / SPEC-0094 §4 — the per-change live_probe RUNNER at the deploy seam. Runs the task-YAML
    # `live_probe` assertion (read-only HTTP GET) against prod using the carrier live_base_url; emits
    # live_probe_passed on a PASS (the per-change adoption proof), nothing + non-zero on a FAIL. GET-only.
    lpr = sub.add_parser("liveprobe", help="Run a task's per-change live_probe GET against prod "
                                           "(SPEC-0094 §4) + emit live_probe_passed on pass — use with -C <path>")
    lpr.add_argument("--task", required=True, help="the task whose per-change live_probe assertion to run (T-NNNN)")
    lpr.add_argument("--base-url", dest="base_url",
                     help="override the carrier live_base_url for this run (e.g. a staging endpoint)")
    # T-11674 (X-1130) — the ATTESTED form's GRADING seam (SPEC-0094 §4b). The kernel grades a proof the
    # PROJECT already runs and issues NO outbound request on this path; `--report` is the reading it
    # grades. Valid ONLY on a card declaring `live_probe: {attested: ...}` — the other three forms are
    # refused, so this can never become a way to hand-declare a GET assertion passed.
    lpr.add_argument("--report", choices=("pass", "fail"),
                     help="ATTESTED form only (SPEC-0094 §4b): record the outcome of the live proof the "
                          "PROJECT itself ran at its own gate. `pass` emits live_probe_passed; `fail` "
                          "emits live_probe_failed and exits non-zero — a reading that did not pass is "
                          "recorded as FAILING, never as missing or stale. No request is issued either way")
    lpr.add_argument("--detail", help="with --report: what the reading said (free text, recorded on the event)")
    lpr.set_defaults(func=cmd_live_probe, read_only_refuse="issues a live GET against production and records the "
                      "target's adoption evidence, which read-only would misfile into the reader's journal")

    # T-9595 / SPEC-0111 — the safety-railed HOST-config apply seam. Performs a host nginx vhost change
    # SAFELY BY CONSTRUCTION (auto-backup · collision REFUSE · nginx -t over the effective config ·
    # server-wide health sweep + auto-rollback · repo-conf-vs-live reconciliation) and emits the three
    # task-scoped evidence events the SPEC-0094 §3 close-gate requires. The system NEVER holds autonomous
    # sudo — the owner runs/approves the helper (--confirm = the human-apply confirmation, §1).
    hap = sub.add_parser("hostapply", help="Safety-railed host-config apply seam (SPEC-0111): backup + "
                                            "collision-refuse + nginx -t + server-wide sweep + "
                                            "auto-rollback + reconciliation; emits the 3 task-close "
                                            "evidences — use with -C <path>")
    hap.add_argument("--task", required=True, help="the host-config task this apply belongs to (T-NNNN); "
                                                   "the three evidence events are task-scoped")
    hap.add_argument("--conf", action="append",
                     help="shipped conf to apply as `src[:target]` (repeatable). Without `:target` the "
                          "target is paired positionally to the carrier deploy.host_config.vhost_files.")
    hap.add_argument("--confirm", action="store_true",
                     help="the OWNER human-apply confirmation (SPEC-0111 §1) — emits apply_confirmed. "
                          "WITHOUT it the apply runs the rails + sweep but the close-gate stays REFUSED.")
    hap.add_argument("--confirmed-by", dest="confirmed_by",
                     help="the AUTHORIZING owner directive / journal ref this --confirm rests on, "
                          "recorded as apply_confirmed.confirmed_by (SPEC-0111 §1). REQUIRED with "
                          "--confirm on the controller-dispatched path (a background session is not "
                          "the owner and may not self-authorize); optional interactively, where the "
                          "owner is at the terminal and the provenance records `owner-interactive`.")
    hap.add_argument("--nginx", default="nginx",
                     help="nginx invocation base for -t/-T (default `nginx`; a SANDBOX test passes "
                          "`<bin> -p <prefix> -c <conf>` so the rails never touch /etc/nginx or 80/443).")
    hap.add_argument("--registry", help="override the registry location for the server-wide domain sweep "
                                        "(default $YITC_REGISTRY or the kernel registry.yaml).")
    hap.set_defaults(func=cmd_host_apply)

    # T-10009 / SPEC-0130 — the governed gate-2 v1-shutdown ("v1-quiesce") seam. Sets the consumer's
    # registry entry `active: false` (comment-preserving line edit) + ensures .no-v1-hooks + emits
    # v1_quiesced. Replaces the hand-done quiesce that left no journal evidence and recurred per
    # v1-incumbent migration. Verb TOKEN is lowercase-alpha `quiesce` (the top-level-verb naming
    # convention — every sibling verb is alpha-only, e.g. liveprobe/hostapply; a digit/hyphen token
    # like `v1-quiesce` is not admissible), func/module keep the descriptive v1_quiesce name
    # (the hostapply/host_apply token≠module precedent).
    v1q = sub.add_parser("quiesce", help="Governed gate-2 v1-shutdown (\"v1-quiesce\") of a consumer "
                                         "(SPEC-0130): set its registry active:false + ensure "
                                         ".no-v1-hooks + emit v1_quiesced — use with -C <path>")
    v1q.set_defaults(func=cmd_v1_quiesce)

    ntl = sub.add_parser("nightly", help="Bounded v2 methodology-nightly RUNNER (SPEC-0105): enumerate "
                                         "registry yitc_v2 projects, run read-only governance/health "
                                         "checks, emit ONE nightly_run_completed; CHECK+REPORT only "
                                         "(no autonomous session — CHARTER §6 fence)")
    ntl.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="fully read-only preview: run the checks + print the report, but emit NO "
                          "nightly_run_completed event and run NO backup-verify snapshot")
    ntl.add_argument("--registry", help="override the registry location (default: $YITC_REGISTRY or "
                                        "<host-home>/registry.yaml)")
    ntl.add_argument("--status", action="store_true",
                     help="READ-ONLY view (SPEC-0105 §1e): print THIS project's verdicts from the "
                          "latest nightly_run_completed row in the ENGINE journal (use with -C "
                          "<consumer>), or 'no nightly verdict for <name>'. Runs no check, writes "
                          "nothing to either journal")
    ntl.set_defaults(func=cmd_nightly, read_only_admit=("status", RO_ZERO_WRITE),
                     read_only_refuse="the bare runner runs every project's checks and emits nightly_run_completed")

    dbt = sub.add_parser("debt", help="Proactive-debt echo ON DEMAND (SPEC-0119): the 3 derived debt "
                                      "views (not-adopted / open-followups / overdue-rechecks) rendered "
                                      "report-only, suppressed-when-clean. Read-only; the post-/compact "
                                      "re-fold surface (analog of `cross outbox`/`cross inbox`). The "
                                      "open-followups line has a configurable floor "
                                      "(env YITC_DEBT_FOLLOWUP_FLOOR, default 5) below which a small "
                                      "backlog is suppressed (T-9789). Its headline counts ACTIONABLE "
                                      "followups only: an ARMED waiter (one carrying a named `trigger`) "
                                      "is reported beside it, and gets its own UNFLOORED line once its "
                                      "trigger fires (T-10309)")
    dbt.add_argument("--explain", nargs="?", const="", default=None, metavar="CLASS",
                     help="Print ONE debt class's full long-form text, verbatim (SPEC-0119 rule 40, "
                          "T-12305) — the home of the rule text the compact session-start "
                          "table points at. Bare `--explain` lists the classes. Bare `debt` (no "
                          "flag) keeps the FULL render of every class, unchanged.")
    dbt.add_argument("--seam-coverage", action="store_true",
                     help="T4.P6 read-counter coverage (T-12854): every PARSER-DERIVED verb leaf, "
                          "split measured / partial / UNMEASURED over the half-open window "
                          "[--since, --until), with each measured verb's worst-per-seam ratio. "
                          "Defaults: --until now, --since until minus 7 days.")
    dbt.add_argument("--since", default=None, metavar="ISO",
                     help="with --seam-coverage: window start (inclusive)")
    dbt.add_argument("--until", default=None, metavar="ISO",
                     help="with --seam-coverage: window end (exclusive)")
    dbt.set_defaults(func=cmd_debt, cli_invoked_receipt="debt", read_only_admit=RO_RECEIPT)  # T-12846: invocation receipt only (not a read marker)

    prf = sub.add_parser("profile", help="Project growth profile ON DEMAND (SPEC-0198): the 10 "
                                        "dimensions RESOLVED from this checkout, its yitc-ops.yaml, "
                                        "its migrations/ORM + dependency manifests and its journal, "
                                        "with the snapshot hash, the check-set hash and the lens set "
                                        "the profile activates. READ-ONLY — no write, no event of its "
                                        "own (only the T-0113 cli_invoked invocation receipt, "
                                        "T-12846), no worktree (the `debt` posture). You do NOT maintain this "
                                        "profile: it is derived. Declare only what the kernel cannot "
                                        "derive (traffic_scale / collaborator_rights), or an OVERRIDE "
                                        "you want shown as yours, under `profile.override` in "
                                        "yitc-ops.yaml; an override renders as `(override)`")
    prf.add_argument("--json", action="store_true",
                     help="emit the resolution as ONE line of JSON instead of the human table "
                          "(T-12165) — the machine form a deterministic, byte-copied consumer-side "
                          "producer parses. Same resolution, second render; no second derivation")
    prf.set_defaults(func=cmd_profile, cli_invoked_receipt="profile", read_only_admit=RO_RECEIPT)  # T-12846: invocation receipt only

    vdur = sub.add_parser("verify-durations",
                          help="Verify-suite duration table (T-11316 / SPEC-0132 §6) — the FIXED "
                               "per-repo record the land-verify runner schedules against "
                               "(longest-first). BARE = the divergence REPORT (unrecorded / "
                               "no-longer-existing files), read-only, no run, no event of its own "
                               "(only the cli_invoked invocation receipt, T-12846), the `debt` "
                               "posture. `--rebuild` = measure the suite ONCE through the same "
                               "runner and rewrite the table — the ONLY thing that ever rewrites it, "
                               "so dispatch order is immobile between explicit rebuilds. An absent "
                               "or stale table is a PERFORMANCE question, never a correctness one: "
                               "it schedules worse, it cannot change the verdict. DELEGATED TESTS "
                               "(T-11389): where a declared verify layer's `covers:` names tests/, "
                               "`--rebuild` REFUSES (the bare-host route does not run that suite, and "
                               "the kernel skips the sweep the table would schedule) and the BARE "
                               "report names any existing table SUSPECT")
    vdur.add_argument("--rebuild", action="store_true",
                      help="run the suite (fail_fast=False, every file to its own verdict) and "
                           "REWRITE tests/verify-durations.json. ALL-OR-NOTHING: refuses to write "
                           "unless every discovered file carries a recorded attempt (a partial table "
                           "mis-ranks exactly the files it is missing, and looks correct doing it). "
                           "REFUSED OUTRIGHT where a declared layer covers tests/: measuring "
                           "`python3 <file>` on the host would record the cost of failing to start")
    vdur.set_defaults(func=cmd_verify_durations, cli_invoked_receipt="verify-durations", read_only_admit=RO_RECEIPT,
                      read_only_refuse=("rebuild", "--rebuild runs the whole suite and rewrites tests/verify-durations.json in the target"))  # T-12846

    rrs = sub.add_parser("retire-read-site",
                         help="Retire a TRACKED root-cwd read-site (T-11779 / SPEC-0192) — the "
                              "covering verb for a card whose declared work IS the removal. It "
                              "names specific previously-tracked sites, PROVES each absent by "
                              "re-running the instrument over the current tree, regenerates the "
                              "affected `dev-utilities/root-cwd-read-sets-*.{json,md}` FROM that "
                              "measurement, and records a retirement entry tied to task + "
                              "fingerprint + reason. It replaces the per-removal owner-ACKed "
                              "`land --rebaseline` round-trip for THIS case and nothing else: no "
                              "report field edits, no threshold changes, no new-site acceptance, "
                              "no baseline sweep, no force flag. The retired set is always a set "
                              "you NAMED, and the reconciliation never reads the retirement record "
                              "— so a rotted report still reddens")
    rrs.add_argument("--task", required=True, help="the task retiring the site(s)")
    rrs.add_argument("--site", action="append", required=True, metavar="KEY|FILE:LINE",
                     help="a previously-tracked site: its exact `site_key`, else its `file:line` "
                          "label. REPEATABLE — the whole named set retires ATOMICALLY, which is "
                          "what a multi-site removal needs (retiring one of two leaves the other "
                          "stale and is refused). An ambiguous selector is REFUSED, never guessed")
    rrs.add_argument("--reason", required=True,
                     help="REQUIRED, recorded on the retirement entry and the journal event: WHY "
                          "the site was removed. An unexplained retirement is indistinguishable "
                          "from the drift it must stay distinguishable from")
    rrs.add_argument("--fingerprint", help="the deviation fingerprint this retirement discharges")
    rrs.add_argument("--report", action="append",
                     help="restrict to a specific ledger json (repeatable). Default: every "
                          "dev-utilities/root-cwd-read-sets-*.json carrying a named site")
    rrs.set_defaults(func=cmd_retire_read_site)

    cg = sub.add_parser("cage", help="Spike-cage checks (SPEC-0172). `cage preflight`: the READ-ONLY "
                                     "host collision preflight (rule 9) — no write, no event, no "
                                     "worktree (the `debt` posture)")
    cg_sub = cg.add_subparsers(dest="cage_cmd", required=True)
    cgp = cg_sub.add_parser("preflight",
                            help="fold the RUNNING stacks off `docker ps` and compare a declared stack "
                                 "identity: REFUSE (exit 1) only an exact compose-project-name match "
                                 "with a FOREIGN running stack; REPORT a port a foreign holder "
                                 "publishes; `host preflight: skipped — <reason>` (exit 0) when docker "
                                 "cannot be read. No registry, no reservation, never reaps")
    cgp.add_argument("--project", required=True, help="the DECLARED compose project name of the stack "
                                                      "about to come up")
    cgp.add_argument("--port", type=int, action="append", default=[],
                     help="a host port the declared stack publishes (repeatable)")
    cgp.add_argument("--own", action="append", default=[],
                     help="a compose project that is this project's OWN (its production / spike "
                          "project) — never counted foreign (repeatable)")
    cgp.set_defaults(func=cmd_cage_preflight, cli_invoked_receipt="cage preflight")  # T-13087

    fe = sub.add_parser("frontend-errors",
                        help="Frontend-error triage conveyor, ON DEMAND (SPEC-0170): fold a "
                             "qualifying project-side error source READ-ONLY into CONFIRMED "
                             "clusters and print them. Clusters are a DERIVED view — nothing is "
                             "copied or stored, consumer-side or kernel-side; no event of its own "
                             "(only the cli_invoked invocation receipt, T-12846), no "
                             "worktree, no mutation (the `debt` posture). The confirm gate is the "
                             "error KIND, never volume (transport NEVER confirms); the fingerprint "
                             "is kind + normalized message with HTTP status/error codes exempt from "
                             "digit-normalization, and the endpoint is cluster METADATA, never part "
                             "of the key. The 30-day window and the confirm-threshold 2 are settled "
                             "parameters, not flags — --as-of/--all-time only POSITION the window")
    fe.add_argument("--pg-container",
                    help="docker container running the consumer's Postgres — the AD-HOC shape. OMIT "
                         "it to run the verb BARE, resolving the source this repo DECLARES under "
                         "`extensions.adopts[] spec: SPEC-0170` (T-10776): that bare form is the "
                         "SPEC-0171 post-/compact RE-FOLD of the session-start error echo, the "
                         "`debt` / `cross outbox` precedent")
    fe.add_argument("--table", default="system_errors",
                    help="source table (default system_errors); validated fail-closed against "
                         "[schema.]identifier — an identifier cannot be parameterized")
    fe.add_argument("--source-value", default="frontend",
                    help="value of the store's `source` column selecting frontend rows (default "
                         "frontend); bound as a psql variable, never interpolated into the SQL")
    fe.add_argument("--as-of", help="position the rolling window's END at this ISO date/timestamp "
                                    "(default: now) — the window LENGTH stays the settled 30 days")
    fe.add_argument("--all-time", action="store_true",
                    help="fold the whole history instead of the rolling window (diagnostic: this is "
                         "what reproduces the trial's all-time cluster record)")
    fe.add_argument("--json", action="store_true",
                    help="machine view incl. each cluster's source `row_ids` (the provenance chain)")
    fe.add_argument("--ack", metavar="CLUSTER",
                    help="ACK an already-judged cluster by LABEL or FINGERPRINT (T-10777): it leaves "
                         "the session-start echo UNTIL IT RECURS, and the first occurrence after the "
                         "ack brings it back by itself. The marker is one append-only journal event "
                         "folded at read time (the SPEC-0095 followup shape) — no store, no table, no "
                         "status; suppression is a COMPARISON against the cluster's newest occurrence, "
                         "so an ack can never become a permanent mute over a live defect. No worktree "
                         "(D-0049)")
    fe.add_argument("--promote", metavar="CLUSTER",
                    help="PROMOTE a confirmed cluster by LABEL or FINGERPRINT into the EXISTING "
                         "`followup` carrier (SPEC-0095), which then becomes a task card via "
                         "`followup promote <id> --into T-XXXX` (T-10779). An explicit OWNER/SESSION "
                         "act and the only way anything is ever promoted — the sweep triages and "
                         "reports, it never promotes work on its own (CHARTER §6). The capture "
                         "carries the cluster FINGERPRINT, and the later `--into` REFUSES a card "
                         "that does not name it: provenance survives the hand-off or the hand-off "
                         "does not happen. Acked clusters are promotable too (a mute is not an "
                         "un-know). No new verb, no new store")
    fe.add_argument("--acked", action="store_true",
                    help="list what the acks are currently suppressing, with each ack's date beside "
                         "the cluster's last occurrence (an ack the owner cannot list is a mute with "
                         "no audit surface)")
    fe.set_defaults(func=cmd_frontend_errors, cli_invoked_receipt="frontend-errors")  # T-12846

    task = sub.add_parser("task", help="Task operations")
    task_sub = task.add_subparsers(dest="task_action", required=True)
    tf = task_sub.add_parser("file", help="File a new task (auto-ID + schema validation)")
    # T-10547: the three PROSE-bearing flags steer to --from-stdin (the shell-proof path — a stdin
    # YAML mapping never rides argv). Prose carries backticks; argv rides the shell, which substitutes
    # `...` BEFORE this verb runs, so the card stores the damage silently.
    # T-10720 (E-0054): the steer is per-VERB text now — `task close` and the two commit verbs reuse
    # the identical wording with their own verb name, so the one sentence has one home.
    def _PROSE_STEER_FOR(verb: str) -> str:
        return ("prose with backticks? send this field via --from-stdin — argv rides the shell, "
                f"which substitutes `...` before {verb} runs (T-10547/E-0054)")
    _PROSE_STEER = _PROSE_STEER_FOR("task file")
    tf.add_argument("--title", help=f"one-line imperative title ({_PROSE_STEER})")
    tf.add_argument("--class", dest="cls", help=f"one of {list(TASK_CLASSES)}")
    tf.add_argument("--priority", help=f"one of {list(TASK_PRIORITIES)} (default medium)")
    tf.add_argument("--scope", action="append", help=f"scope bullet (repeatable) ({_PROSE_STEER})")
    tf.add_argument("--acceptance", action="append",
                    help=f"acceptance criterion (repeatable) ({_PROSE_STEER})")
    # T-10901 (X-0725): metavar ID (not the argparse-default CITES/REQUIRES) + the repeated form spelled
    # out — the `--cites CITES` rendering is what taught an operator to pass ONE comma-joined value.
    tf.add_argument("--cites", action="append", metavar="ID",
                    help="cite ID — REPEATABLE, one id per flag (--cites T-0099 --cites T-0092); "
                         "NOT a comma-joined list")
    tf.add_argument("--requires", action="append", metavar="ID",
                    help="blocking dep ID — REPEATABLE, one id per flag (--requires T-0099 "
                         "--requires T-0092); NOT a comma-joined list")
    tf.add_argument("--decomposed-from", dest="decomposed_from",
                    help="OPTIONAL cut-membership marker (SPEC-0070 §5): the plan-slug this card was cut "
                         "FROM by the decomposition cut. NARROW structural relation (the claim-block reads "
                         "it — a card is refused while its plan is pre-`executing`); the SOLE authoritative "
                         "writer is this verb. NOT `--cites` (broad informational linkage). The plan must "
                         "exist. Omit for a non-cut card.")
    tf.add_argument("--imported-from", dest="imported_from",
                    help="OPTIONAL migration-provenance ref (T-10702; SPEC-0028 / SPEC-0166): the "
                         "legacy-backlog id/link this card was imported FROM. A free scalar reference "
                         "(NOT a plan slug — no existence check). Stored only when given; absent = not "
                         "an imported card. SCHEMA carrier only — the premise-verify pass that consumes "
                         "it ships in SPEC-0166 (T-10703).")
    tf.add_argument("--prototype-ref", dest="prototype_ref", default=None, metavar="spike/<slug>",
                    help="OPTIONAL (T-12571, SPEC-0205 rule 5 / SPEC-0028): the prototype this card builds "
                         "on — an ANNOTATED spike/* tag written by `worktree park`. Refused unless it "
                         "resolves as one. audit pre inlines its diff; audit post cites its identity share.")
    tf.add_argument("--expected-touch", dest="expected_touch", action="append",
                    help="OPTIONAL dispatch-selection forecast: a coarse touch unit "
                         "(file path | doc#section | test-target bucket | hand-named function "
                         "e.g. bin/yitc-v2#_run_view) (repeatable; absent = no forecast)")
    tf.add_argument("--resolves-cross", dest="resolves_cross", action="append", metavar="X-NNNN",
                    help="OPTIONAL structured task→cross link (T-9362): the coordination item(s) this "
                         "task resolves (repeatable; X-NNNN). The receiver auto-emits cross_done for "
                         "each linked item it owns + that is picked: at `land` for a worktree close "
                         "(the close defers it), at `task close` only for a close already on main "
                         "(SPEC-0085 §3, T-9588).")
    tf.add_argument("--promotes", dest="promotes", action="append", metavar="fu_XXXXXXXXXXXX",
                    help="OPTIONAL structured task→followup link (T-11056): the OPEN followup(s) this "
                         "card CARRIES (repeatable; fu_<12 hex>). Each is promoted at filing — a "
                         "followup_promoted --into this task, in the same command — so work that has "
                         "been filed stops reading as open debt without a second manual act. The "
                         "followup-axis mirror of --resolves-cross. DECLARED, never inferred: the "
                         "overlap advisory may name candidates, but only this flag mutates state "
                         "(SPEC-0095). Fail-closed — an unknown / already-terminal / malformed id is "
                         "refused before anything is written.")
    tf.add_argument("--effort-tier", dest="effort_tier", choices=EFFORT_TIERS,
                    help="OPTIONAL filing-time STAKES tier (SPEC-0072): normal (default) | critical. "
                         "Routes the background-dispatch worker's model/effort via "
                         "bin/effort-routing-config.yaml. Set `critical` when the change is irreversible "
                         "/ wide-blast / critical. Omit (or `normal`) for the cheap default. A TIER, never "
                         "a model id (provider-neutral). Stored only when != normal.")
    tf.add_argument("--critical", action="store_true",
                    help="shorthand for --effort-tier critical (SPEC-0072). --effort-tier wins if both given.")
    tf.add_argument("--host-config", dest="host_config", action="store_true",
                    help="OPTIONAL host-config-class opt-in marker (SPEC-0028 / SPEC-0111): set when this "
                         "task changes HOST-level config (outside the app image). The SPEC-0094 §3 close-gate "
                         "then REFUSES closure until the evidence this change's KIND requires is recorded "
                         "(--host-config-kind). Omit for a normal task.")
    tf.add_argument("--host-config-kind", dest="host_config_kind", choices=list(vocab.HOST_CONFIG_KINDS),
                    help="WHICH host surface this change touches (T-10261; requires --host-config). "
                         "`nginx-vhost` (the default when omitted) demands the three SPEC-0111 apply-seam "
                         "evidences (apply_confirmed + host_health_sweep_passed + host_reconciliation_recorded). "
                         "`cron` / `systemd-unit` / `other` demand apply_confirmed alone — the server-wide "
                         "sweep + reconciliation probe the shared nginx control plane and do not apply.")
    tf.add_argument("--created-by", dest="created_by", default=None,
                    help="ai-agent | owner | external | a provisioned actor name (e.g. <collaborator>). OMIT IT: the "
                         "author is DERIVED from the launch context (T-10405) — the owner-role host user "
                         "files as ai-agent, a named provisioned user files as themselves. Pass it only to "
                         "override (owner / external).")
    tf.add_argument("--status", help=f"one of {list(TASK_FILING_STATUSES)} (default ready). "
                    "parked requires --parked-reason. Canonical wont-do form per D-0018.")
    tf.add_argument("--parked-reason", dest="parked_reason",
                    help="required (non-empty) when --status parked; ignored otherwise")
    tf.add_argument("--return-trigger", dest="return_trigger",
                    help="optional condition that would unpark; ignored when status != parked")
    tf.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read task fields as a YAML mapping from stdin. Carries the WHOLE field set: "
                         "combining it with a content flag (--resolves-cross / --cites / --scope / ...) "
                         "is REFUSED (T-10437) — put the field in the stdin mapping instead. It used to "
                         "drop such a flag silently (X-0304).")
    tf.add_argument("--skeleton", action="store_true",
                    help="emit the fillable task-authoring skeleton (SPEC-0060 prompts + the "
                         "tasks/_template.yaml schema) to stdout and exit — fill it and pipe back via "
                         "--from-stdin (no worktree, no gate; the availability leg of SPEC-0059 Filing)")
    tf.set_defaults(func=cmd_task_file, cli_invoked_receipt="task file")  # T-13071: attempt receipt

    tc = task_sub.add_parser("close", help="Atomic Stage 9 closure (D-0015 ordering + SPEC-0001 self-test)")
    tc.add_argument("task", help="T-NNNN id of task being closed (positional — aligns with task pick/execute/test/plan/commit)")
    tc.add_argument("--commit", help="git ref (default HEAD); resolved and verified via git rev-parse")
    tc.add_argument("--probe", action="append",
                    help="probe result in form 'AC1:pass' (split on first colon; repeatable; >=1 required per Principle 3)")
    tc.add_argument("--probe-deferred", dest="probe_deferred", action="append",
                    help="probe deferred to later, WITH THE MOMENT IT RETURNS (repeatable) — form "
                         "'<AC>:<moment>', value auto-set to 'deferred'. The moment takes one of the "
                         "two forms the corpus already has: an ISO DATE 'AC2:2026-09-20' (the "
                         "post_ship_observation shape) or an AWAITS ref 'AC2:T-1234' / 'AC2:X-0042' / "
                         "'AC2:events.jsonl#type=<t>[@after=<ISO ts>]' (the SPEC-0095 armed shape, "
                         "admitted by the SAME grammar the followup fire predicate reads) or "
                         "'AC2:events.jsonl#type=<t>@after=land' (the first such row AFTER THIS "
                         "CARD'S OWN land_completed — probe moments only, T-12851). A BARE key "
                         "is REFUSED naming both forms (T-12076): a deferral with no moment can only "
                         "read as due NOW, so it headlines the debt echo from the day it is recorded "
                         "until someone settles it. Deferring still gates nothing.")
    tc.add_argument("--closes-fp", dest="closes_fp", action="append",
                    help="fingerprint(s) this task remediated — folded into the task `cites:` (the §9 "
                         "LINK-RULE carrier, SPEC-0069); human-asserted, NOT derived from task_id. "
                         "Repeatable. Also accepted on a done re-run (late linkage).")
    tc.add_argument("--settle-probe", dest="settle_probe", action="append",
                    help="settle a probe a PRIOR close recorded as `deferred`, on an ALREADY-DONE card "
                         "(T-11107) — form 'AC2:pass', repeatable; requires one --settle-evidence per "
                         "--settle-probe. For the SPEC-0036 variant-(d) family whose acceptance event "
                         "`land` emits at Stage 9, AFTER the pre-land audit-post, so --probe-deferred "
                         "was the only honest close. NOT a reopen: status/commit/closed_at/probe_passed "
                         "are untouched. FAIL-CLOSED — refuses a probe that was never deferred (no "
                         "back-dating, and no re-settling behind different evidence), a result outside "
                         "the settleable vocabulary, and an evidence locator that resolves to no "
                         "journal row. TWO NON-PASS TERMINALS (T-11657): 'AC2:unreachable' (a proof "
                         "that can never arrive) and 'AC2:falsified' (a reading that arrived and came "
                         "back negative) — each takes --settle-reason instead of --settle-evidence. A "
                         "run is homogeneous: passes OR terminals, never both. A bare 'fail' stays "
                         "refused. NEITHER terminal satisfies CHARTER Principle 8 adoption evidence.")
    tc.add_argument("--settle-evidence", dest="settle_evidence", action="append",
                    help="the NAMED proof for the correspondingly-positioned --settle-probe: a "
                         "materialized-journal locator `events.jsonl#ts=<ISO>` or "
                         "`events.jsonl#source_ref=<ref>` (the D-0030 citation form). Must RESOLVE to a "
                         "real journal row (worktree+main fold) — the evidence is named, never asserted. "
                         "For a `pass` settlement only; a non-pass TERMINAL takes --settle-reason.")
    tc.add_argument("--settle-reason", dest="settle_reason", action="append",
                    help="the MANDATORY, non-empty FREE-TEXT reason for the correspondingly-positioned "
                         "NON-PASS TERMINAL --settle-probe ('unreachable' / 'falsified', T-11657): WHY "
                         "the proof can never arrive, or WHAT the negative reading was. FREE TEXT and "
                         "not an enum on purpose — the measured unreachable causes are structurally "
                         "different (evidence living in a consumer repo; a before/after whose baseline "
                         "was never recorded; a measure unobservable in principle), so a fixed cause "
                         "list would be wrong on day one. An empty reason is REFUSED and nothing is "
                         "written. Not accepted on a `pass` settlement — that names its proof with "
                         "--settle-evidence. SECOND CARRIER (T-11950): it also carries the reason for "
                         "a TERMINAL `--settle-observation unreachable|falsified`, where exactly one "
                         "is required — a run may not mix that with --settle-probe, since one reason "
                         "list cannot be positionally owned by two carriers.")
    # T-11413 (SPEC-0094 §3 / <project> X-1081+X-1082) — the FOURTH late-linkage mode on the done
    # branch, after --closes-fp / --pv-* / --settle-probe. A `live_probe` waiver is authored to satisfy
    # THIS verb's close-gate, so a waiver that can be SETTLED is by construction on a card already done
    # — and `task update --live-probe-*` refuses every terminal card outright (measured on six <project>
    # cards). It lands here rather than as a terminal carve-out on `task update` because `task update`
    # is the verb BEFORE the gate (D-0033): it writes DIRTY for `task close` to fold, and on a done card
    # there is no close left to fold it, so the write would wedge every later land (the X-0274 class).
    # This branch already owns that posture fork (T-11162) and the close-gate's own resolver.
    tc.add_argument("--settle-live-probe-evidence", dest="settle_live_probe_evidence",
                    help="settle the `live_probe` WAIVER of an ALREADY-DONE card (T-11413, SPEC-0094 "
                         "§3) — the NAMED proof its debt was discharged by a real (non-GET) probe: a "
                         "materialized-journal locator `events.jsonl#ts=<ISO>` or "
                         "`events.jsonl#source_ref=<ref>`, which must RESOLVE to a real probe-evidence "
                         "row. The HONEST discharge, versus re-dating recheck_by or flipping "
                         "user_facing:false. NOT a reopen: status/commit/closed_at/probes are "
                         "untouched. FAIL-CLOSED — refuses a card carrying no waiver, a re-settle "
                         "behind DIFFERENT evidence (an identical re-run is an idempotent no-op), and "
                         "a locator resolving to no probe-evidence row. Requires "
                         "--settle-live-probe-probed-at + --settle-live-probe-method")
    tc.add_argument("--settle-live-probe-probed-at", dest="settle_live_probe_probed_at",
                    help="WHEN the discharging probe was run, an ISO date (YYYY-MM-DD). Part of the "
                         "--settle-live-probe-* triple (T-11413)")
    # T-11748 (X-1163) — THE TERMINAL DISCHARGE, the sibling of `--settle-probe <AC>:unreachable|
    # falsified` one carrier over (T-11657). The triple above is DISCHARGE-BY-PROOF; <project> measured
    # four waivers (of twenty drained) for which no probe-evidence row can EVER exist — a differential
    # needing a WRITE, or data that is not on prod — leaving only the two exits the kernel itself calls
    # dishonest. These two flags are the honest third: mutually exclusive with the triple, reason
    # MANDATORY, and never P8 adoption evidence.
    # NO `choices=` here, deliberately (T-11320): the vocabulary lives in `bin/lib/task.py`, and
    # reaching it at PARSER-BUILD time would import the task hub on every `--help` — the deferred-load
    # boundary that file's tripwire pins. The value is refused by the ONE grammar SoT instead
    # (`_live_probe_settled_grammar_error`, which names the allowed pair), so an out-of-vocabulary
    # terminal still dies before any write — one home for the vocabulary, not two.
    tc.add_argument("--settle-live-probe-terminal", dest="settle_live_probe_terminal",
                    metavar="unreachable|falsified",
                    help="Discharge this DONE card's live_probe waiver as a TERMINAL instead of by "
                         "proof (T-11748, SPEC-0094 §3): `unreachable` — the differential can NEVER be "
                         "read (it needs a write, or data that does not exist on prod); `falsified` — "
                         "the reading ARRIVED and came back negative. REQUIRES "
                         "--settle-live-probe-reason, is MUTUALLY EXCLUSIVE with "
                         "--settle-live-probe-evidence/-probed-at/-method, moves the waiver off the "
                         "ACTIONABLE overdue-recheck set onto its OWN counted floor set, and NEVER "
                         "satisfies CHARTER Principle 8 adoption evidence")
    tc.add_argument("--settle-live-probe-reason", dest="settle_live_probe_reason",
                    help="WHY the waiver reached that terminal — non-empty free text, MANDATORY with "
                         "--settle-live-probe-terminal (T-11748). The reason IS the record: an empty "
                         "one discharges the debt while saying nothing, and is refused before any write")
    tc.add_argument("--settle-live-probe-method", dest="settle_live_probe_method",
                    help="HOW it was probed — non-empty text (docker-exec import / prod SQL invariant "
                         "/ served-bundle marker / live-container differential). Part of the "
                         "--settle-live-probe-* triple (T-11413)")
    # T-11674 (X-1130) — the SIXTH late-linkage mode: RECORDING an ATTESTED live proof's reading. The
    # sibling of --settle-live-probe-* above, with the one asymmetry the card exists for: a settle only
    # ever says PAID, while this records `passing` OR `failing` — and a `failing` reading is recorded,
    # visible and NOT a discharge, so bad news is never filed as no data (SPEC-0094 §4b).
    tc.add_argument("--live-probe-outcome-result", dest="live_probe_outcome_result",
                    choices=("passing", "failing"),
                    help="record the reading of the ATTESTED live proof this card declares (SPEC-0094 "
                         "§4b): `passing` discharges the debt; `failing` records a real negative "
                         "reading and KEEPS the card on the overdue-recheck lens. Requires "
                         "--live-probe-outcome-evidence + --live-probe-outcome-probed-at")
    tc.add_argument("--live-probe-outcome-evidence", dest="live_probe_outcome_evidence",
                    help="WHICH proof run says so — the materialized-journal locator "
                         "`events.jsonl#ts=<ISO>` that `bin/yitc-v2 liveprobe` printed when it graded "
                         "the reading. Must RESOLVE to that row, and its type must match the result "
                         "(a failure may never certify a pass). Part of the triple")
    tc.add_argument("--live-probe-outcome-probed-at", dest="live_probe_outcome_probed_at",
                    help="WHEN the project ran its proof — an ISO date (YYYY-MM-DD). Part of the triple")
    tc.add_argument("--live-probe-outcome-detail", dest="live_probe_outcome_detail",
                    help="OPTIONAL free text: what the reading said (recorded on the card beside the result)")
    # T-12328 (X-1331 / X-1351) — the WRITER half of the same SPEC-0094 §4b pair, and the SEVENTH
    # late-linkage mode on the done branch. T-11674 shipped both halves of the READING path but no verb
    # writes the DECLARATION onto a card whose closure has LANDED: `task update --old/--new` refuses a
    # terminal card and neither of its carve-outs reaches one, so the conversion X-1171 asked for was
    # reachable only by hand-editing governed YAML (which skips the emit) — measured on <project> T-0602.
    # X-1351 is the same gap from the waiver side: a project keeps taking dated `none` waivers while a
    # real live proof runs at its deploy gate with nowhere to be DECLARED.
    tc.add_argument("--settle-live-probe-attested", dest="settle_live_probe_attested",
                    action="store_true",
                    help="write an ATTESTED `live_probe` declaration onto an ALREADY-DONE card whose "
                         "closure is ON `main` (T-12328, SPEC-0094 §4b) — the WRITER half of the "
                         "attested pair, whose reading half (`liveprobe --report` + "
                         "--live-probe-outcome-*) already ships. Requires --attested + --runs-at + "
                         "--asserts + --recheck-by. CONVERTS an UNSETTLED `none` waiver in place (the "
                         "X-1331/X-1351 case: a real proof exists, so filing 'no data' is no longer the "
                         "honest answer); NOT a reopen — status/commit/closed_at/probes are untouched. "
                         "FAIL-CLOSED — refuses a card whose closure is NOT on `main` (derived from "
                         "what `main` SAYS about the card, never asserted; undeterminable refuses), a "
                         "non-done card, preexisting card dirt, a SETTLED waiver (replacing it would "
                         "erase a recorded discharge), a DIFFERENT existing attested declaration (the "
                         "family's no-back-dating bound) and a `url` assertion / `unprobeable` "
                         "escalation. An IDENTICAL re-run is an idempotent no-op. Inside a writing "
                         "worktree it writes no commit and rides that batch (T-12120).")
    tc.add_argument("--attested", dest="attested",
                    help="WHICH instrument the project itself runs (e.g. `authenticated-post-probe` / "
                         "`headless-browser-gate` / `served-bundle-marker`). Part of the "
                         "--settle-live-probe-attested quartet (T-12328)")
    tc.add_argument("--runs-at", dest="runs_at",
                    help="WHERE that instrument is gated (e.g. `scripts/deploy.sh`). Part of the "
                         "--settle-live-probe-attested quartet (T-12328)")
    tc.add_argument("--asserts", dest="asserts",
                    help="WHAT it proves live — the assertion, in the project's own terms. Part of the "
                         "--settle-live-probe-attested quartet (T-12328)")
    tc.add_argument("--recheck-by", dest="recheck_by",
                    help="the dated, surfaced non-adoption debt this UNGRADED declaration owes until "
                         "its reading is recorded — an ISO date (YYYY-MM-DD). REQUIRED: the SPEC-0094 "
                         "§3 P3 honesty floor is not weakened by the attested form, it merely gains a "
                         "real exit (record the reading with `liveprobe --task <id> --report "
                         "pass|fail`, then `task close --live-probe-outcome-*`) instead of a recheck "
                         "with no better instrument. Part of the quartet (T-12328)")
    # T-11529 (SPEC-0119 / T-10916) — the FIFTH late-linkage mode on the done branch. The
    # `post_ship_observation.settled_by` field was read by the debt lens, the audit-post overlay guard
    # and the audit prompt, and written by nothing — so the session-start debt echo instructed its
    # reader to settle a field no verb could set, leaving a hand-edit of governed YAML (which skips the
    # emit) as the only route. It lands HERE, on the done branch, for the T-11413 reason: the variant-(e)
    # carve-out defers the proof precisely because the reading cannot exist before the ship, so every
    # settleable observation is by construction on a card already closed (all 37 in this checkout).
    tc.add_argument("--settle-observation", dest="settle_observation",
                    help="settle the `post_ship_observation` of an ALREADY-DONE card (T-11529, T-10916 "
                         "/ SPEC-0036 variant (e)) — the locator naming WHERE the recorded reading "
                         "landed: `events.jsonl#ts=<ISO>` or `events.jsonl#source_ref=<ref>` (the "
                         "D-0030 citation form), which must RESOLVE to a real journal row. Scoped to "
                         "the JOURNAL: the T-11297 `coordination.jsonl#cross=` form is deliberately "
                         "NOT admitted — no case names an observation settled from the shared store, "
                         "and admitting one would open a second reader of it. This "
                         "clears the observation from `graph query "
                         "overdue-recheck` — time passing never does. VALUE OVERLOAD (T-11950), the "
                         "shape `--settle-probe <AC>:unreachable` already has: pass the literal "
                         "`unreachable` (the declared reading can NEVER arrive — the specimen is gone, "
                         "the baseline was never recorded, the mechanism is pre-empted) or `falsified` "
                         "(the reading ARRIVED and came back negative) INSTEAD of a locator, with a "
                         "MANDATORY non-empty --settle-reason and NO --settle-evidence (an unreachable "
                         "reading has no evidence row by definition). A terminal moves the observation "
                         "off the ACTIONABLE overdue-recheck counts onto its OWN counted set and NEVER "
                         "satisfies CHARTER Principle 8 adoption evidence. NOT a reopen: "
                         "status/commit/closed_at/probes are untouched. FAIL-CLOSED — refuses a card "
                         "declaring no observation, a malformed declaration, a re-settle behind "
                         "DIFFERENT evidence (an identical re-run is an idempotent no-op), an "
                         "id-shaped citation that names WORK rather than the READING, and a locator "
                         "resolving to no row.")
    tc.add_argument("--reverify", action="append",
                    help="SPEC-NNNN the AUTHOR asserts is STILL ACCURATE despite this task's diff "
                         "changing its anchored code — re-stamps its content-signature, FOLDED into the "
                         "closure-commit (no separate `spec reverify`; SPEC-0015 §Reverify-at-close, T-1177). "
                         "Repeatable. FAIL-CLOSED: honoured ONLY for a spec THIS diff left possibly-stale "
                         "(the touched-anchor drift set) — not a blanket rubber-stamp. A genuine behaviour "
                         "change → `spec edit`, NOT --reverify.")
    tc.add_argument("--hygiene-fast-path", dest="hygiene_fast_path", action="store_true",
                    help="skip audit-post precondition (hygiene tasks per LIFECYCLE §Hygiene Fast-Path); probes still required")
    tc.add_argument("--batch-close", dest="batch_close", action="store_true",
                    help="low-ceremony in-place close for a HYGIENE-class work-batch-filed task (T-0590): "
                         "claim a stranded `ready` hygiene task + close it from inside its work/<slug> batch "
                         "worktree (no per-task worktree); implies --hygiene-fast-path. REFUSES a non-hygiene "
                         "task (→ `worktree new --task`), a task already on main, and uncommitted batch dirt")
    tc.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the probes block from stdin as a YAML mapping with two optional keys — "
                         "`probes:` a MAPPING of <probe-key>: <result> (result one of pass|fail|deferred; "
                         "evidence goes in the commit body, not the result slot) and `probes_deferred:` a "
                         "LIST of probe-key strings. A list-shaped probes: or a scalar probes_deferred: is "
                         "refused with a shape error (T-10711). ALSO carries the PROSE fields "
                         "(T-10720/E-0054) — `pv_criterion`, `pv_signal`, `pv_waive`, `prop_nowhere`, and "
                         "(T-12643) the four late-linkage prose flags `settle_reason` (a LIST, positionally "
                         "matching --settle-probe), `asserts`, `live_probe_outcome_detail`, "
                         "`settle_live_probe_reason` — the SHELL-PROOF path for prose carrying backticks; "
                         "passing any of them on argv alongside --from-stdin is REFUSED, and a SURVIVING "
                         "BACKTICK on any of them on argv is refused pre-parse by the argv-prose seam "
                         "(SPEC-0209). The probe flags still merge")
    # T-0667 (SPEC-0053) — forward-propagation disposition carrier: record EXACTLY one of three
    # outcomes into task_closed.data.propagation_disposition. OPTIONAL at this stage (no presence-gate;
    # the required-for-infra gate is T-0669 — instrument-before-policy). The three flags are mutually
    # exclusive (refused loudly by _build_propagation_disposition); no flag → field absent.
    tc.add_argument("--prop-follow-up", dest="prop_follow_ups", action="append",
                    help="propagation_disposition = follow_ups_filed: the id(s) carrying the "
                         "consequent 'apply elsewhere' work — a T-NNNN task id OR a `fu_`+12-hex "
                         "followup id, the kernel's own carrier for such work (repeatable; SPEC-0053 "
                         "§The disposition, widened by T-11408 / X-1083: do not file a card merely to "
                         "mint an id this flag accepts)")
    tc.add_argument("--prop-deferred-idea", dest="prop_deferred_idea",
                    help="propagation_disposition = deferred_to_idea: the ideas/<slug> capturing a REAL "
                         "but not-yet-actionable forward concern (SPEC-0053 §The disposition)")
    tc.add_argument("--prop-nowhere", dest="prop_nowhere",
                    help="propagation_disposition = nowhere_else_applies: a non-empty REASON asserting "
                         "the mechanism has no other application site (SPEC-0053 §The disposition). "
                         f"{_PROSE_STEER_FOR('task close')}")
    # T-0409 — SPEC-0038 post_verification carrier: author the per-task soak criterion AT closure
    # (the moment of best understanding) instead of an out-of-band hand-edit. Fill-or-waive contract:
    # --pv-criterion + --pv-signal TOGETHER write {criterion, signal}; --pv-waive REASON writes
    # {none: REASON}; the two modes are mutually exclusive (refused loudly). No flags → unchanged
    # WARN + gap marker (non-blocking, non-goal #7). class:hygiene still auto-waives.
    tc.add_argument("--pv-criterion", dest="pv_criterion",
                    help="SPEC-0038 post_verification.criterion — what counts as 'it worked in real "
                         "operation' (positive + observable); requires --pv-signal; XOR --pv-waive. "
                         f"{_PROSE_STEER_FOR('task close')}")
    tc.add_argument("--pv-signal", dest="pv_signal",
                    help="SPEC-0038 post_verification.signal — the event/state/measurable that proves "
                         "the criterion; requires --pv-criterion; XOR --pv-waive. "
                         f"{_PROSE_STEER_FOR('task close')}")
    tc.add_argument("--pv-waive", dest="pv_waive",
                    help="explicitly waive post_verification with a REASON — writes "
                         "post_verification: {none: REASON}; mutually exclusive with "
                         f"--pv-criterion/--pv-signal. {_PROSE_STEER_FOR('task close')}")
    tc.set_defaults(func=cmd_task_close, cli_invoked_receipt="task close")  # T-13071: attempt receipt

    # T-0056 lifecycle transition verbs (per D-0033). Per D-0049 they auto-sync the journal
    # by default; they do NOT rebuild the graph (heavier verbs do).
    tp = task_sub.add_parser("pick", help="Stage 1: ready→in-progress, validate requires, set stage, emit task_picked, print context")
    tp.add_argument("task", help="T-NNNN id to pick")
    tp.set_defaults(func=cmd_task_pick, cli_invoked_verb="task pick", read_only_admit=RO_READ)  # T-0310: read-only inspector — observability parity with sibling read verbs
    # T-11305 (X-1002) — the NO-WORKTREE claim, admitted ONLY for a card whose deliverable is
    # DEMONSTRABLY already on `main` (DERIVED from main, fail-closed, no assert-flag by design). The
    # ordinary claim path is untouched: `worktree new --task` stays the sole route for ordinary work.
    tcl = task_sub.add_parser("claim-landed", help="Write ready→in-progress + task_picked WITHOUT a "
                              "worktree, for a card whose deliverable is DEMONSTRABLY already on main "
                              "(derived from main's own delivery record, fail-closed; scoped "
                              "direct-to-main self-commit, idempotent) — T-11305/X-1002")
    tcl.add_argument("task", help="T-NNNN id — must be `ready` on main AND carry a main-side delivery "
                                  "proof (a SUCCESSFUL land_completed for task/<id>, or a task_closed); "
                                  "anything else REFUSES")
    tcl.set_defaults(func=cmd_task_claim_landed, cli_invoked_verb="task claim-landed")
    # T-11307 (X-1008): the RECOVERY entry to the one claim mutator — for a claim a path-scoped
    # `git checkout` reverted inside the task's own worktree. Narrower admission than the ordinary
    # claim in every direction (own worktree only, `ready` on main only, no other live holder).
    trc = task_sub.add_parser("reclaim", help="Restore a claim that a path-scoped `git checkout` of "
                              "the task card silently reverted, INSIDE that task's own worktree — "
                              "instead of hand-editing status/current_stage (idempotent; refuses "
                              "fail-closed anywhere else) — T-11307/X-1008")
    trc.add_argument("task", help="T-NNNN id — the card must read `ready` in THIS task/<id> worktree "
                                  "AND `ready` on main, with no other live worktree holding it; "
                                  "anything else REFUSES")
    trc.set_defaults(func=cmd_task_reclaim, cli_invoked_verb="task reclaim")
    tx = task_sub.add_parser("execute", help="Stage 5: requires current_stage==Execution (set via `stage Execution`) + scope reminder + plan recap")
    tx.add_argument("task", help="T-NNNN id")
    tx.set_defaults(func=cmd_task_execute, cli_invoked_receipt="task execute")  # T-13071: attempt receipt
    tt = task_sub.add_parser("test", help="Stage 6: requires current_stage==Tests (set via `stage Tests`) + print ACs checklist (no auto-run); --evidence records tests_passed")
    tt.add_argument("task", help="T-NNNN id")
    tt.add_argument("--run", action="store_true",
                    help="run land's CANDIDATE verify leg only — this worktree's tests/test_*.py, each via python3, exit 0 = pass — catching script-style __main__ tests that `pytest tests/` skips (T-10097) — and, in the mirror direction, failing loudly as `zero-collect-script-run:<file>` on a pytest-style file with `def test_*` but no __main__ driver, which exits 0 here having executed nothing (T-12764). A green here is NOT the land verdict: `land` verifies TWO legs (SPEC-0077) and the pinned last-green leg is NOT run here; composes with --evidence (run-then-record)")
    tt.add_argument("--full", action="store_true",
                    help="T-11987: with --run, the explicit FULL-SUITE escape — run every discovered test_*.py, opting OUT of the SPEC-0181 affected-test selection that otherwise governs this run exactly as it governs land's candidate leg. Use it when you want the whole enumeration regardless of the diff; without it the run prints `selection: affected (n of N)` or `selection: full (fail-closed)` and records the mode on tests_passed")
    tt.add_argument("--evidence", help="record Stage-6 result: emit a tests_passed event with this evidence summary (T-0123) — call after tests are green")
    tt.add_argument("--duration-ms", type=int, dest="duration_ms",
                    help="T-0375: test-run wall (author-reported, with --evidence) — all-or-nothing with --passed/--failed")
    tt.add_argument("--passed", type=int,
                    help="T-0375: passed count (author-reported, with --evidence) — all-or-nothing with --duration-ms/--failed")
    tt.add_argument("--failed", type=int,
                    help="T-0375: failed count (author-reported, with --evidence) — all-or-nothing with --duration-ms/--passed")
    tt.set_defaults(func=cmd_task_test, cli_invoked_receipt="task test")  # T-13071: attempt receipt
    tan = task_sub.add_parser("analyze", help="Stage 1: --finalize validates the analysis: decision-record + checks SPEC-0032/0046 read; requires current_stage==Analysis (T-0600 — does not set stage)")
    tan.add_argument("task", help="T-NNNN id")
    tan.add_argument("--finalize", action="store_true", help="finalize the Analysis decision-record (Stage 1 → emit analysis_finalized; Plan-entry then requires it)")
    # T-10586 (X-0440): the CONFIRMATION source for the Stage-1 expected_touch write-back. The write-back
    # no longer regexes the analysis prose (a mention is not a declaration); it takes this flag, or an
    # `expected_touch:` line in the analysis record, and validates in-repo file-or-glob (fail-closed).
    tan.add_argument("--expected-touch", dest="expected_touch", action="append", default=None,
                     metavar="PATH", help="confirm a smallest-concrete-edit file this task will touch (repeatable; in-repo file or explicit glob) — written back to the card when it carries none. Replaces the prose-derived guess (X-0440)")
    # T-11251 (X-0971): the EXPLICIT amendment of a forecast the card ALREADY carries — its own mode,
    # not combinable with --finalize/--expected-touch, running the SAME fail-closed admissibility
    # validation as the seeding path. The T-10586 wins-untouched rule for the implicit write-back is
    # unchanged; this is the governed route that was missing beside it.
    tan.add_argument("--amend-expected-touch", dest="amend_expected_touch", action="append",
                     default=None, metavar="PATH",
                     help="AMEND MODE (T-11251): amend an expected_touch forecast the card already carries — it AMENDS only, never SEEDS (a card with no forecast is refused and routed to --expected-touch). Repeatable; the flags state the COMPLETE amended set (a replace, so a wrong entry can be withdrawn — the added/removed diff is printed and journaled). Same in-repo file-or-glob validation as --expected-touch, fail-closed, but applied to the ADDED entries ONLY (T-12329): an entry the card ALREADY carries, restated unchanged in the complete set, is admitted whatever its shape — it authorizes nothing new — so one legacy bare-directory entry no longer walls off every unrelated correction (X-1333). Admitted at current_stage Analysis or Plan ONLY; from Audit-pre onward a widened scope is an escalation (SPEC-0103/SPEC-0121). Its own mode — not combinable with --finalize/--expected-touch")
    # T-11358 (X-1023, <project>): the NARROW Stage-8 CORRECTION arm of the amend mode above. It is a
    # SEPARATE admission, deliberately — widening `_AMEND_TOUCH_STAGES` to include Audit-post would admit
    # an unrestricted post-audit amendment, which is the scope CHANGE SPEC-0121 §5 reserves for
    # escalation. What this admits is strictly narrower: a forecast the SHIP DIFF shows was never
    # touched authorizes nothing that happened, so withdrawing it REMOVES authority; and an added entry
    # must match a path the diff DID touch, so it grants none either. Both flags REFINE the amend mode —
    # they do not constitute one (the --live-probe-recheck-by precedent).
    tan.add_argument("--forecast-correction", dest="forecast_correction", action="store_true",
                     help="CORRECTION MODE (T-11358): with --amend-expected-touch, correct a wrong forecast at current_stage Audit-post ONLY — the seam where the external auditor actually catches a mistyped path. Requires --reason. FENCED against the diff of the RECORDED audit commit: you may WITHDRAW only an entry that diff never touched, and ADD only an entry it did (so the correction can never authorize an edit that has not already shipped and been audited); an undeterminable commit/diff REFUSES fail-closed. It moves NOTHING about the audit — the verdict and its pinned `commit:` are never opened, nothing is committed, and a RED stays RED. It records that the forecast was wrong; it does not make the ship right. POST-CLOSE (T-11931): also admitted on a status:done card whose closure is PROVEN still branch-local (derived from what `main` says about the card, never asserted — the T-11458 admission), the sanctioned rework-in-place of QUEUE §Prematurely-closed; there the fence reads the commit the LATEST audit-post record shows the auditor GRADED, since the post-close re-audit grades the current tree rather than the recorded ship. A closure that LANDED is refused — it has no reopen")
    tan.add_argument("--reason", dest="correction_reason", metavar="TEXT",
                     help="why the forecast was wrong — REQUIRED with --forecast-correction and recorded on the task_amended row. A correction carrying no ground is indistinguishable from a silent post-audit edit of a scope-boundary field, which is exactly what the stage lock exists to catch (the same none-with-reason discipline the waiver legs of `task update` apply)")
    tan.set_defaults(func=cmd_task_analyze, cli_invoked_receipt="task analyze")  # T-13071: attempt receipt
    tpl = task_sub.add_parser("plan", help="Stage 3: --finalize validates implementation_plan (≤45 lines, soft); requires current_stage==Plan (T-0288 — does not set stage)")
    tpl.add_argument("task", help="T-NNNN id")
    tpl.add_argument("--finalize", action="store_true", help="finalize the plan (Stage 3 → Audit-pre)")
    tpl.set_defaults(func=cmd_task_plan, cli_invoked_receipt="task plan")  # T-13071: attempt receipt
    # T-13103: no long-option ABBREVIATION — the SPEC-0209 argv seam scans exact tokens, so an accepted
    # `--mess=...` would carry the message past it. Set for EVERY guarded row at the end of this
    # function, derived from the seam registry (T-13465), not per subparser here.
    tcm = task_sub.add_parser("commit", help="Stage 7: git-wrapper commit (auto from:/Co-Authored-By), callable ×N")
    tcm.add_argument("task", help="T-NNNN id")
    # T-10720 (E-0054): no longer argparse-`required` — a `--from-stdin` caller supplies the message in
    # the stdin mapping instead; presence is re-checked AFTER ingest, so an omitted message still refuses.
    tcm.add_argument("-m", "--message",
                     help="commit message (subject + optional body). "
                          f"{_PROSE_STEER_FOR('task commit')}")
    tcm.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the commit message from stdin as a YAML mapping with the single key "
                          "`message:` — the SHELL-PROOF path for a message body carrying backticks "
                          "(stdin bytes never ride the shell; T-10720/E-0054). Passing -m/--message "
                          "alongside it is REFUSED (fail-closed, T-10437/X-0304). Feeding it from a file? "
                          "Make the file in the gitignored `.scratch/` dir — `"
                          + vocab.SCRATCH_TEMPFILE_RECIPE + "`, then `< \"$f\"` — never "
                          "the checkout root, which this verb's add-all would commit (T-12930)")
    tcm.add_argument("--from", dest="from_ref", help="override from: trailer (default tasks/T-XXXX-*.yaml)")
    tcm.add_argument("--absorb", action="store_true",
                     help="Stage-8 mode-a carve-out (T-0370): commit an inline absorption of audit-post "
                          "findings, folding the superseded verdict in (never hand-delete it); the "
                          "follow-up `audit post --commit <new>` is REQUIRED (re-pins custody, "
                          "carries the passes trail). Refused outside the mode-a hazard state.")
    tcm.add_argument("--fix-red", dest="fix_red", action="store_true",
                     help="Stage-8 RED IN-SCOPE-FIX leg (T-11600): commit a fix for the cause a RED "
                          "audit-post named, when that cause is inside this task's declared scope — "
                          "the route the --absorb-on-RED refusal already prescribes. Same cycle as "
                          "--absorb (the superseded verdict is folded in, never hand-deleted) and the "
                          "follow-up `audit post --commit <new>` is EQUALLY REQUIRED, but admitted on "
                          "a different basis: a RED verdict PLUS positive proof this commit carries "
                          "AUTHORED content. A bookkeeping-only commit is REFUSED — that is the "
                          "T-11550 shape. Not combinable with --absorb; the YELLOW cycle stays "
                          "--absorb's. SCOPE BOUND: this leg is for a fix that SHIPS. If the RED "
                          "cause's only fix is a correction to the task's OWN records (its card, its "
                          "audit YAML), that is bookkeeping and cannot earn custody on its own — add "
                          "--card-repair (T-11991), which admits exactly that shape on its own "
                          "positive proof, or let the correction ride a commit that ALSO carries "
                          "authored work. When the cause is OUTSIDE scope, is environmental, or has "
                          "no shipping fix: escalate with `blocked-on-land` (SPEC-0103).")
    tcm.add_argument("--reship", dest="reship", action="store_true",
                     help="Stage-8 GREEN SECOND-SHIP leg (T-12410): commit a FURTHER in-scope ship "
                          "after audit-post came back GREEN and something still has to change — a "
                          "verify layer that reddened on the shipped code, say, whose fix is itself "
                          "a ship. The THIRD Stage-8 cycle, completing one flag per admitting "
                          "verdict (--absorb YELLOW, --fix-red RED, --reship GREEN). Same mechanics "
                          "as its siblings (the superseded verdict is folded in, never hand-deleted) "
                          "and the follow-up `audit post --commit <new>` is EQUALLY REQUIRED — the "
                          "GREEN you hold covers the OLD commit, so without it `task close` "
                          "fail-closes. Admitted on a GREEN verdict PLUS positive proof this commit "
                          "carries AUTHORED content; a bookkeeping-only commit is REFUSED (the "
                          "T-11550 shape), as is any non-GREEN verdict, an audit-PRE hazard, and an "
                          "absent hazard state. Not combinable with --absorb / --fix-red / "
                          "--card-repair. Nothing further to ship? The GREEN stands — leave the "
                          "audit YAML dirty and go to Stage 9 (`task close`), which commits it "
                          "without re-shifting custody. No owner-reset arm: past the ceiling the "
                          "route is `audit decide` + `audit post --on-decisions` (SPEC-0204).")
    tcm.add_argument("--card-repair", dest="card_repair", action="store_true",
                     help="ARM of --fix-red (T-11991), never a leg of its own — pass BOTH. It admits "
                          "the ONE shape --fix-red's SCOPE BOUND above otherwise sends to escalation: "
                          "the RED cause's only honest fix is a correction to this task's OWN card "
                          "record. Admitted on a DIFFERENT positive proof, not a relaxed one — the "
                          "staged set is exactly the task's own lifecycle records WITH the card among "
                          "them, AND the commit the superseded RED verdict covers provably carries "
                          "authored content. Custody is earned by that audited ship, not by the "
                          "repair: the REQUIRED `audit post --commit <new>` grades the CUMULATIVE "
                          "range (ship + repair together), so the auditor receives strictly more than "
                          "on the RED pass and nothing is weakened. Refused when the staged set "
                          "carries authored content (use --fix-red plain), when the covered commit "
                          "carries none, or when git cannot answer — fail-closed. Not combinable with "
                          "--absorb.")
    tcm.add_argument("--owner-reset", dest="owner_reset", action="store_true",
                     help="OWNER-AUTHORIZED (T-9403/E-0030): with --absorb, grant ONE continuation that "
                          "COMMITS a late-surfacing legit finding's fix past an EXHAUSTED audit-post "
                          "ceiling (when even the owner-reset re-audit budget is spent), so the "
                          "ceiling-convergence consult has a committed subject to govern (re-pin custody "
                          "via `audit post --commit <new> --owner-reset`). Pass only on owner "
                          "authorization; recorded owner_reset:true on commit_landed. Mirrors `audit "
                          "--owner-reset` — the BOOTSTRAP that materializes a committed subject, "
                          "structurally non-stackable (a second escape is refused until the "
                          "consult-governed re-pin), NOT a blanket ceiling disable.")
    tcm.add_argument("--reverify", action="append",
                     help="SPEC-NNNN the AUTHOR asserts is STILL ACCURATE despite this task's diff "
                          "moving its anchored code — re-stamps ONLY the anchors this diff moved and "
                          "ships the re-stamp in THIS commit, beside the code (the one-commit route; "
                          "SPEC-0015 §Reverify-at-commit, T-13056). Repeatable. FAIL-CLOSED: honoured "
                          "ONLY for a spec THIS diff left possibly-stale — refused before anything is "
                          "written otherwise. A genuine behaviour change → `spec edit`, NOT --reverify.")
    tcm.set_defaults(func=cmd_task_commit, cli_invoked_receipt="task commit")  # T-13071: attempt receipt

    tl = task_sub.add_parser("list", help="List tasks with status/priority filters (picker UX parity with bare grep)")
    tl.add_argument("--status", action="append", choices=list(TASK_LIST_STATUSES),
                    help=f"filter by status (repeatable; default = all). Choices: {list(TASK_LIST_STATUSES)}")
    tl.add_argument("--priority", action="append", choices=list(TASK_PRIORITIES),
                    help=f"filter by priority (repeatable; default = all). Choices: {list(TASK_PRIORITIES)}")
    tl.set_defaults(func=cmd_task_list, cli_invoked_verb="task list", read_only_admit=RO_READ)  # T-0113 observability

    # Read-only re-orientation (analog of `plan show`, T-0682; fixes E-0040): NO cli_invoked_verb
    # marker — mutates nothing, emits nothing of its own.
    tsh = task_sub.add_parser("show", help="Read-only re-orientation for a task: status/stage/requires/"
                              "cites + resume contract (the task analog of `plan show`)")
    tsh.add_argument("task", help="T-NNNN id to show")
    tsh.set_defaults(func=cmd_task_show, read_only_admit=RO_VIEW)

    # T-0368 — status-transition + amendment verb (closes the hand-edit gap; QUEUE §State transitions).
    tu = task_sub.add_parser("update", help="Status transition (park / unpark / wont-do per QUEUE "
                             "§State transitions), amendment note, field-edit, or RECLASSIFY (--class) "
                             "on an EXISTING task — the verbed replacement for the status/class hand-edit "
                             "(T-0368 / T-9745)")
    tu.add_argument("task", help="T-NNNN id to update")
    tu.add_argument("--class", dest="new_class", choices=list(TASK_CLASSES),
                    help="RECLASSIFY mode (T-9745): the governed route to change a task's `class` "
                         "(emits task_reclassified). `class` keys the stage-FSM / Fast-Path eligibility "
                         "(SPEC-0027); its own mode (mutually exclusive with --status/--note/--old/--new); "
                         "the class hand-edit is retired. Refused on terminal (done/wont-do) cards.")
    # T-11547 (SPEC-0072 rules 1 + 6): the EFFORT-TIER mode. `--effort-tier` existed on `task file`
    # ONLY, so the field was writable exactly once, at birth — while SPEC-0072 rule 1 declares it
    # OVERRIDABLE data the owner may change while the card is active, and rule 6 REQUIRES an
    # escalating worker to bump it to `critical` mid-flight. `choices=EFFORT_TIERS` is the SAME
    # vocabulary constant `task file` validates against and `dispatch` fails closed on — one SoT,
    # never a second list (CHARTER §P5).
    tu.add_argument("--effort-tier", dest="effort_tier", choices=list(EFFORT_TIERS),
                    help="EFFORT-TIER mode (T-11547, SPEC-0072 rules 1+6): the governed route to change "
                         "a task's `effort_tier` AFTER filing (emits task_amended(field_edit, field: "
                         "effort_tier)). The vocabulary is CLOSED — the same normal|critical set `task "
                         "file` writes and `dispatch` fails closed on — so an out-of-vocabulary value is "
                         "refused and NOTHING is written. Setting `normal` REMOVES the key (the "
                         "omit-when-default storage convention `task file` established), so a corrected "
                         "card is byte-identical to one filed that way. Its own mode (mutually exclusive "
                         "with --status/--class/--note/--old/--new/--pv-*/--live-probe-*/--evidence); "
                         "admitted while the card is NON-TERMINAL, refused on done/wont-do (frozen "
                         "history, and the tier is inert there — dispatch never launches a terminal "
                         "card). The --old/--new text-surgery route to this field is retired.")
    tu.add_argument("--status", choices=list(TASK_FILING_STATUSES),
                    help="transition target: parked (from ready|in-progress; needs --reason) | "
                         "ready (unpark, from parked only) | wont-do (from any active; needs --reason). "
                         "ready→in-progress is `worktree new --task` (the claim); in-progress→done is `task close`.")
    # T-12895 (<project> X-1545): the three prose flags below are INGESTED by --from-stdin
    # (PROSE_BEARING_UPDATE_FIELDS) but were the only ones on this verb whose help did not say so —
    # so an author reading --note's help had no way to learn the escape existed, wrote the note on
    # argv, and the shell ate its backticked spans. Same one-home steer the other prose flags carry.
    tu.add_argument("--reason", help="required for --status parked (→ parked_reason) and "
                                     "--status wont-do (→ wont_do_reason). "
                                     f"{_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--return-trigger", dest="return_trigger",
                    help="optional unpark condition recorded when parking (→ return_trigger). "
                         "ALSO its own REPAIR mode on a card that is ALREADY parked (T-12652): pass "
                         "it ALONE — no --status, no other flag — to write the return condition a "
                         "park left missing. That is a FIELD EDIT (task_amended), not a transition: "
                         "the status and the park record are untouched, so the repair never reads as "
                         "a fresh park. On any NON-parked card it is still refused (T-0388). "
                         f"{_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--awaits", dest="awaits",
                    help="with --status parked ONLY: the awaited artifact whose arrival ends this park "
                         "→ parked_awaits (T-13084). Same grammar as `task pause --awaits`: T-NNNN / "
                         "X-NNNN / events.jsonl#type=<t>; an unresolvable ref is refused before any "
                         "write. Session start lists a parked card once its awaited item has arrived "
                         "(UNPARKABLE). The prose --return-trigger stays the human-readable condition.")
    tu.add_argument("--note", help="with --status ready: unpark note (→ unparked_note); without "
                                   "--status: amendment note appended to amend_notes + task_amended "
                                   "event. WHERE IT IS SEEN (T-11733): amend_notes is rendered to the "
                                   "external auditor in the NEXT audit pass for this task and nowhere "
                                   "else in the packet — so this is the route for ANSWERING an audit "
                                   "finding, but a note written before a card's first pass is read by "
                                   "no gate. To change what the audit judges the work against, edit "
                                   "the field itself (--old/--new). "
                                   f"{_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--old", help="FIELD-EDIT mode (T-1164): exact existing text in the card to "
                                  "replace (scope/acceptance/requires/any field); mirrors `spec edit`; "
                                  "mutually exclusive with --status/--note; 0 or >1 match dies. "
                                  "A --new that SUPERSETS --old ADDS a field — this is the governed "
                                  "post-filing route for the host-config marker (T-13573): --old "
                                  "'<a line the card has>' --new '<that line>' plus the new lines "
                                  "`host_config: true` and, optionally, `host_config_kind: <kind>`; "
                                  "the result passes the same three checks the filing seam applies")
    tu.add_argument("--new", help="FIELD-EDIT mode: replacement text (needs --old)")
    tu.add_argument("--replace-all", dest="replace_all", action="store_true",
                    help="FIELD-EDIT mode: replace ALL occurrences of --old (default: unique match)")
    # T-12409 (<project> X-1338): the ADD-ACCEPTANCE mode — the governed APPEND to `acceptance`. The
    # field-edit route above could only ever CORRECT an existing criterion: its documented superset ADD
    # substitutes raw text, so a newline-led item aimed at a list the emitter WRAPPED is absorbed into
    # the open quoted scalar (valid YAML, flat length, exit 0 — the glued AC). This mode appends through
    # the YAML emitter instead, and the field-edit arm now refuses that superset pointing here.
    tu.add_argument("--add-acceptance", dest="add_acceptance", metavar="TEXT",
                    help="ADD-ACCEPTANCE mode (T-12409, closes a consumer's X-1338): APPEND one acceptance "
                         "criterion to a NON-TERMINAL card, written through the YAML emitter (emits "
                         "task_amended(field_edit) carrying added_acceptance: ACn). The TEXT must START "
                         "with the card's NEXT `ACn:` label, DERIVED from the card and GAPLESS — "
                         "`task close --probe ACn` keys on that label, so an unlabelled, out-of-sequence "
                         "or already-taken label is refused and NOTHING is written. Its own mode "
                         "(mutually exclusive with --status/--note/--return-trigger/--reason/--class/"
                         "--effort-tier/--old/--new). Use --old/--new to CORRECT existing criterion "
                         f"text; this flag only ever adds. {_PROSE_STEER_FOR('task update')}")
    # T-13172: the STRUCTURED-EDIT modes — replace ONE acceptance item, or set a whole list/multiline
    # field, from a FILE (or stdin), written through the YAML emitter. The --old/--new raw-text
    # matcher cannot carry quotes/newlines into a wrapped quoted list scalar; these never splice text.
    tu.add_argument("--replace-acceptance", dest="replace_acceptance", metavar="ACn",
                    help="STRUCTURED-EDIT mode (T-13172): REPLACE the one acceptance criterion labelled "
                         "ACn (`ACn: …` or, as a plain YAML scalar must read, `ACn …` — T-13248) with "
                         "the text read from --from-file (which must lead with the same `ACn:` "
                         "label). Other criteria are untouched; emits ONE task_amended(field_edit). Its "
                         "own mode; refused on done/wont-do cards.")
    tu.add_argument("--set-field", dest="set_field", metavar="KEY",
                    help="STRUCTURED-EDIT mode (T-13172): SET a list/multiline field to the YAML value "
                         "read from --from-file. KEY is one of scope/acceptance/cites/requires/"
                         "expected_touch/answers (a YAML list of strings; answers = SPEC-0197 "
                         "link-back ids like 'yitc-dev/yitc#8', also settable on a done card — T-13221) or description/analysis/"
                         "implementation_plan (a string) or probe_moments (a mapping {ACn: {awaits|due_by: <moment>}}, "
                         "keys must name this card's criteria — T-13247) or resolves_cross (a YAML list of X-NNNN "
                         "ids — ADD-only; each added id must exist, be addressed to this project and not be "
                         "linked to another live card — T-13339); every verb-owned field (status, class, "
                         "effort_tier, id, …) is refused — host_config / host_config_kind too: their "
                         "route is the --old/--new superset above. Emits ONE task_amended(field_edit). Its own "
                         "mode; refused on done/wont-do cards EXCEPT for answers.")
    tu.add_argument("--from-file", dest="from_file", metavar="PATH",
                    help="with --replace-acceptance / --set-field ONLY: read the value from PATH "
                         "(`-` = stdin), so no shell quoting touches it.")
    # T-11663 (SPEC-0184 rule 9) — the OPT-IN emergency place in the land-admission order. Its own
    # mode on this verb, for the same reason every other field-setter here is: the mark is set on an
    # EXISTING stuck card, and the alternative was hand-editing governed state. The REASON is the
    # flag's own argument, so «a mark with no stated blockage» is unrepresentable in argv and the
    # blank case is refused explicitly by `state.queue_jump_write_error`.
    tu.add_argument("--queue-jump", dest="queue_jump", metavar="REASON",
                    help="QUEUE-JUMP mode (T-11663, SPEC-0184 rule 9): give THIS card an emergency "
                         "place at the FRONT of the land-admission order, naming the BLOCKAGE it "
                         "clears (the reason is required — it is what the firing record names). "
                         "ORDER OF SERVICE ONLY: batch membership is untouched. It EXPIRES with the "
                         "card (a terminal card grants no precedence), and each firing that actually "
                         "reorders admission is journaled and surfaced on `debt`. Its own mode.")
    tu.add_argument("--queue-jump-clear", dest="queue_jump_clear", action="store_true",
                    help="QUEUE-JUMP mode: remove the queue-jump mark from this card (idempotent).")
    # T-10722 — SPEC-0038 post_verification carrier on the OTHER terminal closure. `--status wont-do`
    # already WARNs on the fill-or-waive gap (T-0532), but exposed NO setter, so the WARN told the
    # author to fill a field no governed path could then write (the catch-22 captured 2026-06-23 +
    # T-10345). Same three flags, same dest names, same EXISTING `_author_post_verification` helper +
    # `_post_verification_gap` predicate as `task close` (P5 — one authoring path, one predicate).
    # wont-do ONLY: park is REVERSIBLE, so its eventual close authors the field at the right moment.
    tu.add_argument("--pv-criterion", dest="pv_criterion",
                    help="SPEC-0038 post_verification.criterion — with --status wont-do ONLY: what "
                         "counts as 'it worked in real operation'; requires --pv-signal; XOR --pv-waive. "
                         f"{_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--pv-signal", dest="pv_signal",
                    help="SPEC-0038 post_verification.signal — with --status wont-do ONLY: the "
                         "event/state/measurable that proves the criterion; requires --pv-criterion; "
                         f"XOR --pv-waive. {_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--pv-waive", dest="pv_waive",
                    help="with --status wont-do ONLY: explicitly waive post_verification with a REASON "
                         "— writes post_verification: {none: REASON}, silencing the SPEC-0038 WARN + gap "
                         "marker; mutually exclusive with --pv-criterion/--pv-signal. "
                         f"{_PROSE_STEER_FOR('task update')}")
    # T-11223 (SPEC-0094 §3/§4 / X-0964): the live-probe ASSERTION setter — its OWN mode on this verb.
    # Before it, `live_probe` had NO writer after filing, so a deploying project's closure gate could
    # only be satisfied by hand-editing the governed card (five <project> cards did exactly that) — the
    # SAME catch-22 the --pv-* family above closed for `post_verification`, which is the analog this
    # mirrors. Structured values, written through the YAML emitter — so the --old/--new apostrophe trap
    # is not reintroduced. The WAIVER leg (`--live-probe-none`) followed as the sibling card T-11209,
    # landing in the flag slot T-11223 left free for it — the two shapes of ONE field on ONE verb.
    tu.add_argument("--live-probe-url", dest="live_probe_url",
                    help="LIVE-PROBE mode (T-11223, SPEC-0094 §3/§4): the path (or absolute URL) of the "
                         "read-only GET run at the DEPLOY seam, joined to the yitc-ops.yaml "
                         "live_probe.live_base_url. Requires --live-probe-expect-status; its own mode "
                         "(not combinable with --status/--class/--note/--old/--new/--pv-*). Writes "
                         "live_probe: {url, expect_status, …} and emits task_live_probe_declared")
    tu.add_argument("--live-probe-expect-status", dest="live_probe_expect_status", type=int,
                    help="LIVE-PROBE mode: the HTTP status the probe GET must return (int). Requires "
                         "--live-probe-url — the assertion is the pair, never half of it")
    tu.add_argument("--live-probe-body-contains", dest="live_probe_body_contains",
                    help="LIVE-PROBE mode (optional): a substring the probe response body must contain")
    tu.add_argument("--live-probe-expect-location", dest="live_probe_expect_location",
                    help="LIVE-PROBE mode (optional): the expected `Location` header of an IMMEDIATE "
                         "redirect (the SPEC-0094 §4 no-follow dialect) — requires a redirect "
                         "--live-probe-expect-status (301/302/303/307/308)")
    # T-13231 (SPEC-0098 §1 / yitc#35): the SECURITY dialect of the same assertion. The grammar
    # (`_security_dialect_error`) and the runner already existed; the writer did not, so the one route
    # to a security probe was a hand edit of the governed card. Passed WITH --live-probe-url/-expect-
    # status they ride the declaration; passed ALONE they amend the card's existing assertion.
    tu.add_argument("--live-probe-property", dest="live_probe_property",
                    help="LIVE-PROBE SECURITY (T-13231, SPEC-0098 §1): the security property this "
                         "assertion proves (e.g. hsts) — the label its security_live_probe_passed row "
                         "carries; must match the yitc-ops.yaml security.probes[] entry it vouches for. "
                         "Needs at least one --live-probe-assert-*. Alone (no --live-probe-url) it "
                         "AMENDS the card's existing assertion and emits task_amended")
    tu.add_argument("--live-probe-assert-header-present", dest="live_probe_assert_header_present",
                    action="append",
                    help="LIVE-PROBE SECURITY: a response header that must be PRESENT (repeatable)")
    tu.add_argument("--live-probe-assert-header-absent", dest="live_probe_assert_header_absent",
                    action="append",
                    help="LIVE-PROBE SECURITY: a response header that must be ABSENT (repeatable)")
    tu.add_argument("--live-probe-assert-cookie-flags", dest="live_probe_assert_cookie_flags",
                    action="append", metavar="NAME=FLAG[,FLAG]",
                    help="LIVE-PROBE SECURITY: a cookie and the flags its Set-Cookie must carry "
                         "(Secure / HttpOnly / HostOnly), e.g. session=Secure,HttpOnly (repeatable)")
    # T-11209 (SPEC-0094 §3 / X-0955, the confirmed duplicate of X-0964): the WAIVER leg of the same
    # mode — the governed way to record that a card legitimately has NO live probe. The grammar
    # (`{none: <reason>, user_facing: <bool?>, recheck_by: <ISO-date?>}`) and the P3 honesty floor
    # already existed in `_live_probe_declaration_error`; what was missing was the WRITER, so the
    # close-gate's refusal could only be satisfied by hand-editing the governed card — which is what
    # five <project> cards did, at the pinned-custody closure seam. Extends T-11223's mode rather than
    # opening a parallel path (CHARTER §P1 filter 1), and lands on `task update` — the verb BEFORE the
    # gate (D-0033) — so the write needs no standalone commit and cannot shift the audited commit.
    tu.add_argument("--live-probe-none", dest="live_probe_none",
                    help="LIVE-PROBE WAIVER mode (T-11209, SPEC-0094 §3): record that this card "
                         "legitimately has NO live probe, with the REASON as the value. Writes "
                         "live_probe: {none: REASON, …} and emits task_live_probe_declared "
                         "(form: waiver). Fail-closed — an empty reason is REFUSED, as is a bare "
                         "--live-probe-recheck-by / --live-probe-not-user-facing with no reason: a "
                         "waiver carrying no ground is indistinguishable from forgetting to declare "
                         "one. Mutually exclusive with the --live-probe-url assertion above. "
                         f"{_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--live-probe-recheck-by", dest="live_probe_recheck_by",
                    help="LIVE-PROBE WAIVER mode: the ISO date (YYYY-MM-DD) by which the waived probe "
                         "is revisited — a dated, surfaced non-adoption debt. REQUIRED for a "
                         "USER-FACING waiver (the SPEC-0094 §3 P3 honesty floor); needs "
                         "--live-probe-none")
    # T-11722 (SPEC-0036 variant (e) / T-10916) — the DECLARATION writer for `post_ship_observation`,
    # the mirror image of `task close --settle-observation` one seam earlier. T-11529 gave the field's
    # `settled_by` a writer; the DECLARATION itself still had none after birth, and the filing path
    # dropped a piped one silently — so a card that learns mid-lifecycle that its proof can only exist
    # AFTER it lands could not acquire the declaration at all, leaving the fail-closed Stage-8
    # `--post-ship-observation` overlay unreachable for exactly the cards that need it. Lands on `task
    # update` — the verb BEFORE the gate (D-0033) — so the write needs no standalone commit and cannot
    # shift the audited commit (the --live-probe-none / --evidence siting argument, verbatim).
    tu.add_argument("--prototype-ref", dest="prototype_ref", default=None, metavar="spike/<slug>",
                    help="PROTOTYPE-REF mode (T-12571, SPEC-0205 rule 5): declare the annotated spike/* tag "
                         "this card builds on; emits task_amended(field_edit). Refuses a non-spike tag, a "
                         "terminal card, and a silent overwrite; idempotent on the same value.")
    tu.add_argument("--observation", dest="observation",
                    help="POST-SHIP OBSERVATION mode (T-11722, SPEC-0036 variant (e) / T-10916): DECLARE "
                         "a deferred proof on a card whose acceptance evidence can only exist AFTER it "
                         "lands — the concrete reading as the value (e.g. 'the daily error count is flat "
                         "or falling over 7 days'). Writes post_ship_observation: {observation: VALUE, "
                         "due_by: …} and emits task_amended(field_edit). REQUIRES --observation-due: a "
                         "deferred proof with no due window is an undated debt, which is how deferred "
                         "adoption becomes never-adopted. Fail-closed — REFUSES a terminal card, a card "
                         "already carrying a recorded `probe_passed` (its proof ARRIVED, nothing is "
                         "deferred), and a card that ALREADY carries a declaration (an identical re-run "
                         "is an idempotent no-op; re-declaring behind a DIFFERENT observation or date is "
                         "refused, since it would change what a later settle discharges out from under "
                         "the audit that read the first one). This verb DECLARES the proof and never "
                         "DISCHARGES one — that is `task close --settle-observation <locator>`, the only "
                         "thing that clears it from `graph query overdue-recheck`. "
                         f"{_PROSE_STEER_FOR('task update')}")
    tu.add_argument("--observation-due", dest="observation_due",
                    help="POST-SHIP OBSERVATION mode: the ISO date (YYYY-MM-DD) by which the deferred "
                         "reading is taken — the WHEN half of the declaration, REQUIRED (T-10916 / "
                         "X-0710). Needs --observation; half a declaration defers nothing.")
    # T-12733 (<project> X-1491): the WRITER for the field the `task close` sensitivity prompt names.
    # Before it the prompt's only remedy was a hand edit of the card — the verb-execution discipline
    # forbids exactly that, and an identical re-run of the pair above is an idempotent no-op, so the
    # field was unreachable through any verb. The key↔flag map is homed ONCE in
    # `lib.task_closure_evidence.POST_SHIP_OBSERVATION_FLAGS`; the prompt names this flag from it.
    tu.add_argument("--observation-sensitivity", dest="observation_sensitivity",
                    help="POST-SHIP OBSERVATION mode (T-12733): the SENSITIVITY evidence — a PAST "
                         "occurrence the declared predicate would have caught (a dated incident, a "
                         "journal locator, an earlier non-empty reading), proving it FIRES when the "
                         "defect IS present (T-11672 / X-1126). Pass it WITH --observation/"
                         "--observation-due on first declaration, or ALONE to add it to a declaration "
                         "the card already carries (the field `task close` prompts for). Refuses a card "
                         "with no declaration, an already-SETTLED one, a terminal card, and a silent "
                         "overwrite of a DIFFERENT value; an identical re-run is an idempotent no-op.")
    # T-11408 leg (a) (SPEC-0015 §Shared-store evidence spelling / <project> X-1053): the WRITER for the
    # `evidence:` field the closure gate READS. Same shape and same seam as the live-probe mode above —
    # `task update` is the verb BEFORE the gate (D-0033), so the write needs no standalone commit and
    # cannot shift the audited commit. Without it the gate's only satisfaction path was the hand edit
    # the verb-execution discipline otherwise forbids.
    tu.add_argument("--evidence", dest="evidence", action="append",
                    help="EVIDENCE mode (T-11408, SPEC-0015 §Shared-store evidence spelling): record "
                         "the `evidence:` row(s) this card's state-check actually READ — the "
                         "coordination item id(s) (`X-NNNN`), plus the `cross_*` event ts where the "
                         "row proved is a TRANSITION rather than the item's existence (`yitc-v2 cross "
                         "show <X-NNNN>` prints both). Repeatable; the flags state the COMPLETE row "
                         "set (a replace). Its own mode (not combinable with "
                         "--status/--class/--note/--old/--new/--pv-*/--live-probe-*), refused on a "
                         "terminal card, and FAIL-CLOSED through the same grammar the close-gate uses "
                         "— rows that would not satisfy the gate are refused here, where they can "
                         "still be fixed. Emits task_amended(field_edit, field: evidence)")
    # T-11413 (SPEC-0094 §3 / <project> X-1081+X-1082): the SETTLED-discharge leg of the same waiver
    # mode. `settled_by` was validated by `_live_probe_settled_grammar_error`, resolved by
    # `_live_probe_settled_evidence_unresolved` and read by the overdue-recheck lens — and written by
    # NOTHING, so the honest discharge SPEC-0094 §3 defines needed a hand-edit of governed YAML while
    # the two exits the kernel itself calls dishonest (re-dating --live-probe-recheck-by, flipping
    # --live-probe-not-user-facing) were fully verbed. These three refine a WAIVER, exactly as
    # --live-probe-recheck-by does, so they ride that leg rather than opening a mode. The DONE-card
    # sibling is `task close --settle-live-probe-*` (a waiver is authored AT close, so a settleable one
    # is almost always on a closed card — the X-1082 measurement).
    tu.add_argument("--live-probe-settled-evidence", dest="live_probe_settled_evidence",
                    help="LIVE-PROBE WAIVER mode (T-11413, SPEC-0094 §3): the NAMED proof this "
                         "waiver's debt was DISCHARGED by a real (non-GET) probe — a "
                         "materialized-journal locator `events.jsonl#ts=<ISO>` or "
                         "`events.jsonl#source_ref=<ref>` (the D-0030 citation form). Must RESOLVE to "
                         "a real PROBE-EVIDENCE row (live_probe_passed / security_live_probe_passed / "
                         "live_trigger_evidence / consumer_read_evidence): the evidence is NAMED, "
                         "never asserted. Writes live_probe.settled_by and CLEARS the overdue-recheck "
                         "debt — the honest alternative to re-dating it. Requires "
                         "--live-probe-settled-probed-at + --live-probe-settled-method (a partial "
                         "triple is REFUSED) and --live-probe-none (it refines a waiver)")
    tu.add_argument("--live-probe-settled-probed-at", dest="live_probe_settled_probed_at",
                    help="LIVE-PROBE WAIVER mode (T-11413): WHEN the discharging probe was run, an ISO "
                         "date (YYYY-MM-DD). Part of the --live-probe-settled-* triple")
    tu.add_argument("--live-probe-settled-method", dest="live_probe_settled_method",
                    help="LIVE-PROBE WAIVER mode (T-11413): HOW it was probed — non-empty text "
                         "(docker-exec import / prod SQL invariant / served-bundle marker / "
                         "live-container differential). Part of the --live-probe-settled-* triple")
    # T-11748 (X-1163) — the PRE-CLOSE half of the terminal discharge, riding the same waiver leg as
    # the triple above (the `task close --settle-live-probe-terminal` sibling is the DONE-card half).
    # NO `choices=` — the same deferred-import boundary as the `task close` sibling above (T-11320).
    tu.add_argument("--live-probe-settled-terminal", dest="live_probe_settled_terminal",
                    metavar="unreachable|falsified",
                    help="LIVE-PROBE WAIVER mode (T-11748, SPEC-0094 §3): discharge the waiver as a "
                         "TERMINAL rather than by proof — `unreachable` (the differential can NEVER be "
                         "read: it needs a write, or data absent from prod) or `falsified` (the "
                         "reading arrived and came back NEGATIVE). REQUIRES "
                         "--live-probe-settled-reason, MUTUALLY EXCLUSIVE with "
                         "--live-probe-settled-evidence/-probed-at/-method, and NEVER satisfies "
                         "CHARTER Principle 8 adoption evidence")
    tu.add_argument("--live-probe-settled-reason", dest="live_probe_settled_reason",
                    help="LIVE-PROBE WAIVER mode (T-11748): WHY the waiver reached that terminal — "
                         "non-empty free text, MANDATORY with --live-probe-settled-terminal. The "
                         "reason IS the record; an empty one is refused before any write")
    tu.add_argument("--live-probe-not-user-facing", dest="live_probe_not_user_facing",
                    action="store_true", default=False,
                    help="LIVE-PROBE WAIVER mode: mark the waiver `user_facing: false` — for a change "
                         "with NO live serving surface, where --live-probe-recheck-by may be omitted. "
                         "Omitted, a waiver reads as user-facing (fail-closed); needs "
                         "--live-probe-none")
    # T-11165 (E-0054): the flag the three steers above have been RECOMMENDING all along. Until now
    # `task update --from-stdin` died at argparse with "unrecognized arguments", so the documented
    # workaround was unrunnable, not merely absent — and the fields it steers to stdin are exactly the
    # ones a shell eats. Mirrors `task close --from-stdin` (T-10720), including the fail-closed refusal
    # of an argv content flag alongside it (T-10437/X-0304 — a silently dropped flag is the failure
    # that rule exists to prevent).
    tu.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the PROSE fields as a YAML mapping on stdin (reason / note / "
                         "return_trigger / pv_criterion / pv_signal / pv_waive / live_probe_none) — "
                         "the shell-proof path, since a stdin mapping never rides argv. "
                         "--status/--class stay on argv (enums, no prose); any of the seven PROSE "
                         "flags on argv alongside --from-stdin is REFUSED, as is --old/--new "
                         "(field-edit is its own mode)")
    tu.set_defaults(func=cmd_task_update)

    # T-0381: pause / resume — the resume-contract writer + re-entry verbs (parent plan
    # fresh-session-task-dispatch-context-economics-hand §Halt + resume-pointer).
    tpa = task_sub.add_parser("pause", help="Record a HALT on the in-progress task: write+commit the "
                              "resume-contract metadata (paused_at/paused_reason/resume_from/next_action) "
                              "with a trigger-typed reason; emits task_paused (T-0381)")
    tpa.add_argument("task", help="T-NNNN id to pause (must be in-progress)")
    tpa.add_argument("--reason", required=True, choices=list(PAUSE_REASONS),
                     help="trigger-typed halt reason → paused_reason (owner-wait surfaces at session start)")
    # T-12407 — the DECLARED awaited artifact. A reference, never prose and never inferred, so it
    # stays on argv beside --reason (the same cut --from-stdin already makes). REQUIRED with
    # --reason artifact-wait, ALLOWED with owner-wait, refused with any other reason. The shape is
    # validated by the ONE grammar home, `followup.awaits_kind` (T-11964) — no second grammar.
    tpa.add_argument("--awaits", dest="awaits",
                     help="the awaited artifact whose arrival ENDS this pause → paused_awaits, so "
                          "the session-start echo reads RESUMABLE once it closes instead of "
                          "asserting a wait it cannot check. Three resolvable shapes (the SAME "
                          "grammar `followup arm --awaits` uses): T-NNNN (a task reaching a "
                          "terminal status) | X-NNNN (a shared-coordination item reaching a "
                          "terminal status) | events.jsonl#type=<t>[@after=<ISO>] (a journal row "
                          "of that class). REQUIRED with --reason artifact-wait; allowed with "
                          "owner-wait; refused with any other reason. Cleared by `task resume`")
    tpa.add_argument("--resume-from", dest="resume_from",
                     help="optional step within the current stage to resume from (→ resume_from)")
    tpa.add_argument("--next-action", dest="next_action",
                     help=f"optional one-line concrete next step (→ next_action) "
                          f"({_PROSE_STEER_FOR('task pause')})")
    # T-11165 (E-0054): same escape as `task update`. --reason is a closed enum and stays on argv.
    tpa.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the resume-contract PROSE as a YAML mapping on stdin (resume_from / "
                          "next_action) — the shell-proof path (mirrors `task update --from-stdin`); "
                          "--reason stays on argv (a closed enum, no prose), and either prose flag "
                          "on argv alongside --from-stdin is REFUSED")
    tpa.set_defaults(func=cmd_task_pause)
    tre = task_sub.add_parser("resume", help="Re-enter a paused in-progress task WITHOUT re-claim "
                              "(validates own/orphan worktree stamp per T-0362); emits task_resumed (T-0381)")
    tre.add_argument("task", help="T-NNNN id to resume (must be in-progress + paused)")
    tre.set_defaults(func=cmd_task_resume)

    # T-10291 (X-0271): the PRE-claim refusal — `task pause`'s sibling for a dispatched worker that
    # analyzed a READY task and correctly refuses it. Journal-only (no worktree, D-0049); reuses the
    # bg_dispatch_halted marker with a `kind: refused` discriminator, so `--fleet-verdict` reads
    # `halted` / needs-decision instead of conflating it with a dead bootstrap (launch-stall).
    trf = task_sub.add_parser("refuse", help="Record a PRE-CLAIM refusal of a ready task (a dispatched "
                              "worker that analyzed it and cannot claim it): journal-only, no worktree; "
                              "emits bg_dispatch_halted(kind=refused) so --fleet-verdict reads halted / "
                              "needs-decision, NOT launch-stall (T-10291)")
    trf.add_argument("task", help="T-NNNN id to refuse (must be ready — an in-progress task uses `task pause`)")
    # T-11165 (E-0054): no longer argparse-`required` — a `--from-stdin` caller supplies the reason in
    # the stdin mapping, and cmd_task_refuse's own non-empty check enforces it from EITHER channel
    # (the `task commit -m` precedent, T-10720). The refusal for a missing reason is unchanged.
    trf.add_argument("--reason",
                     help=f"free-text: WHY the task cannot be claimed (carried verbatim into the "
                          f"fleet-verdict basis, so the controller routes without re-grepping) "
                          f"({_PROSE_STEER_FOR('task refuse')})")
    # T-11679 — the governed EXIT from the card-carried refusal block. The block is fail-closed (the
    # card is not offered by the picker / claim / dispatch), so a card whose blocker genuinely
    # resolved needs a door that is not a terminal status it does not deserve.
    trf.add_argument("--clear", action="store_true",
                     help="CLEAR a pre-claim refusal this card already carries (T-11679) — the "
                          "governed exit once the blocker is resolved or the acceptance was "
                          "re-authored. Writes no status and chooses no disposition; --reason states "
                          "WHAT CHANGED and is journaled as task_amended(refusal_cleared)")
    trf.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the refusal reason as a YAML mapping on stdin (`reason: <text>`) — "
                          "the shell-proof path (mirrors `task update --from-stdin`); an argv "
                          "--reason alongside it is REFUSED")
    trf.set_defaults(func=cmd_task_refuse)

    # SPEC-0166 (T-10703): the premise-verify INTAKE pass — re-checks each imported migration card's
    # premise against today's code (the Stage-1 anti-reinvention grep, moved to the cheap intake
    # moment) and writes premise: via the existing `task update` route. Only a `premise: verified`
    # imported card is dispatchable (the gate in `worktree new` / `dispatch` / `task pick`).
    tin = task_sub.add_parser("intake", help="SPEC-0166 premise-verify intake pass over imported "
                              "(`imported_from:`) ready cards: classify each card's premise against "
                              "today's code (verified|already-done|stale) and route already-done->wont-do "
                              "/ stale->parked via `task update` (verified stays dispatchable)")
    ing = tin.add_mutually_exclusive_group(required=True)
    ing.add_argument("--task", help="T-NNNN — verify ONE imported ready card")
    ing.add_argument("--all", action="store_true", help="verify EVERY imported ready card without a premise yet")
    tin.add_argument("--recheck", action="store_true",
                     help="re-verify a card that already carries a premise (default: skip already-marked cards)")
    tin.set_defaults(func=cmd_task_intake, cli_invoked_receipt="task intake")  # T-12846: a WRITE verb — receipt, never a read marker

    # T-0287 (AU-3a): the lifecycle stage-ENTRY verb — top-level (not nested under `task`). Records
    # current_stage + delivers the stage bundle + emits stage_entered. Auto-syncs the journal (D-0049).
    st = sub.add_parser("stage", help="Enter a lifecycle stage: record current_stage + deliver the "
                                      "stage bundle (specs + work-verbs) + emit stage_entered (T-0287)")
    st.add_argument("name", help=f"stage name — one of: {', '.join(STAGE_AXIS_NAMES)}")
    st.add_argument("--task", required=True, help="T-NNNN id whose stage is being entered")
    st.set_defaults(func=cmd_stage, cli_invoked_receipt="stage")  # T-13071: attempt receipt

    audit = sub.add_parser("audit", help="External auditor invocation (codex wrapper + V2 lens)")
    audit_sub = audit.add_subparsers(dest="audit_action", required=True)
    for stage_name in ("pre", "post"):
        ap = audit_sub.add_parser(stage_name, help=f"Run audit-{stage_name} via external auditor")
        tgt = ap.add_mutually_exclusive_group(required=True)
        tgt.add_argument("--task", help="T-NNNN id of task being audited")
        tgt.add_argument("--decision", help="D-NNNN id of decision being audited (per D-0055)")
        tgt.add_argument("--plan", help="<plan-slug> for the plan-finalization aggregate audit-post — the plan as standing successor of `decision finalize` (post only — Part B/T-0193)")
        if stage_name == "post":
            ap.add_argument("--commit", help="git ref (default HEAD) for audit-post diff context (task audits only)")
            ap.add_argument("--focus", help="(--plan targets ONLY) owner/session question block appended "
                            "AFTER the stage overlay (never replaces it); recorded VERBATIM in the "
                            "saved verdict notes (SPEC-0036)")
            # T-0393: event-emit-only carve-out (--task only). The task's adoption probe IS a
            # Stage-9-recorded P8 event (the emission is the closure substance), so it legitimately
            # does NOT yet exist at audit-post — tell the auditor its absence here is EXPECTED, never
            # a defect (closes the N>=3 false-RED class T-0030/T-0382/T-0391; patterns/event-emit-only-audit-post.md).
            ap.add_argument("--event-emit-only", dest="event_emit_only", action="store_true",
                            help="(--task only) the task's adoption probe IS a Stage-9-recorded P8 event "
                                 "(event-emit-only ship); adds an overlay telling the auditor the event's "
                                 "absence at audit-post is EXPECTED, never a defect (T-0393)")
            # T-9393 (SPEC-0094 §5): serve/deploy carve-out (--task only). SIBLING of --event-emit-only
            # in the same deferred-adoption family. A live deploy is an ACTION, not a code diff —
            # live-adoption is recorded at Stage-9 Closure (the live_probe evidence), so its absence at
            # the diff-only audit-post is EXPECTED, never a defect (removes the X-0039 owner-reset burn).
            ap.add_argument("--serve-deploy", dest="serve_deploy", action="store_true",
                            help="(--task only) this task's ship is a serve/deploy ACTION (not a code "
                                 "diff); live-adoption is deferred to Stage-9 Closure (live_probe). Adds "
                                 "an overlay telling the auditor adoption-absent at audit-post is "
                                 "EXPECTED, never a defect (T-9393, SPEC-0094 §5)")
            # T-9585 (SPEC-0094 §7): external-action carve-out (--task only). THIRD SIBLING of
            # --serve-deploy / --event-emit-only in the same deferred-adoption family. The ship is an
            # EXTERNAL OWNER ACTION (webmaster/registrar panel, DNS-TXT), proven by an owner-confirmation
            # probe recorded at Stage-9 Closure — so the AC probe RESULTS are absent from the diff-only
            # audit-post (the X-0099 false-RED "AC probes not in the diff" that forced a Stage-9 hand-edit).
            ap.add_argument("--external-action", dest="external_action", action="store_true",
                            help="(--task only) this task's ship is an EXTERNAL OWNER ACTION (not a code "
                                 "diff); its owner-confirmation proof is deferred to Stage-9 Closure. Adds "
                                 "an overlay telling the auditor the AC-probe-results-absent / not-in-diff "
                                 "category at audit-post is EXPECTED, never a defect (T-9585, SPEC-0094 §7)")
            # T-9621 (SPEC-0094 §3 / SPEC-0111): host-config carve-out (--task only). FOURTH SIBLING of
            # --external-action / --serve-deploy / --event-emit-only in the same deferred-adoption family.
            # A host-config task's adoption proof is the 3 hostapply evidences (apply_confirmed /
            # host_health_sweep_passed / host_reconciliation_recorded) recorded by the SPEC-0111 apply seam
            # at Stage-9 Closure — so their absence at the diff-only audit-post is EXPECTED, never a defect
            # (removes the X-0117 false-RED "adoption missing" on a host-config ship pre-Stage-9).
            ap.add_argument("--host-config", dest="host_config", action="store_true",
                            help="(--task only) this task's adoption proof is the 3 host-config apply "
                                 "evidences recorded at Stage-9 Closure (SPEC-0111). Adds an overlay "
                                 "telling the auditor adoption-absent at audit-post is EXPECTED, never a "
                                 "defect (T-9621, SPEC-0094 §3)")
            # T-10045 (SPEC-0036 / X-0188): land-emitted-event carve-out (--task only). FIFTH SIBLING of
            # --host-config / --external-action / --serve-deploy / --event-emit-only in the same
            # deferred-adoption family — the GENERALIZATION of --event-emit-only to a NON-P8 event. A
            # task whose acceptance probe is a land-Stage-9-emitted NON-P8 event (e.g. verify_layer_prep)
            # has that event legitimately absent at the diff-only pre-land audit-post; the P8-specific
            # --event-emit-only overlay does not cover it → the base overlay false-REDs (X-0188).
            ap.add_argument("--land-emitted-event", dest="land_emitted_event", action="store_true",
                            help="(--task only) this task's acceptance probe is a NON-P8 event emitted by "
                                 "`land` at Stage 9 (e.g. verify_layer_prep). Adds an overlay telling the "
                                 "auditor that event's absence at the diff-only audit-post is EXPECTED, "
                                 "never a defect (T-10045, SPEC-0036 / X-0188)")
            # T-10062 (SPEC-0036 / X-0201): pre-shipped-deliverable carve-out (--task only). SIXTH SIBLING
            # of --land-emitted-event / --host-config / … in the same deferred-adoption family. A re-claimed
            # task whose deliverable ALREADY LANDED in a PRIOR session (<project>, X-0201) has a re-claim
            # diff of gate-proof + closure bookkeeping ONLY (no deliverable) → the base overlay false-REDs
            # "nothing shipped". The prior deliverable commit is DERIVED from durable task-linked
            # `commit_landed` journal state (_recorded_commit_sha) — nothing user-supplied, nothing to spoof
            # — and the cmd_audit guard fails closed when no such record exists (so the flag cannot exempt
            # an arbitrary empty diff). No commit arg by design.
            ap.add_argument("--preshipped-deliverable", dest="preshipped_deliverable", action="store_true",
                            help="(--task only) this re-claimed task's deliverable ALREADY LANDED in a "
                                 "PRIOR session; the re-claim diff is gate-proof + closure ONLY. Adds an "
                                 "overlay telling the auditor the deliverable-absent / nothing-shipped "
                                 "category is EXPECTED, never a defect. Fail-closed on the task's durable "
                                 "`commit_landed` record (the derived prior commit) — no arbitrary empty "
                                 "diff can be exempted (T-10062, SPEC-0036 / X-0201)")
            # T-10916 (SPEC-0036 / X-0710): post-ship-observation carve-out (--task only). EIGHTH SIBLING
            # of --preshipped-deliverable / --land-emitted-event / … in the same deferred-adoption family.
            # A task whose acceptance probe is a MULTI-DAY POST-SHIP PRODUCTION OBSERVATION («the daily
            # count is flat or falling over 7 days») cannot have that reading at the pre-land, diff-only
            # audit-post — the window opens only after the ship — and no existing overlay covers it, so
            # the worker had to misuse a non-matching flag or halt (X-0710). Like --preshipped-deliverable,
            # NOT taken on the flag's word: the cmd_audit guard refuses unless the CARD declares a
            # well-formed, unsettled `post_ship_observation: {observation, due_by}` — which is also what
            # keeps the deferral TRACKED on the overdue-recheck debt view until it is recorded.
            ap.add_argument("--post-ship-observation", dest="post_ship_observation", action="store_true",
                            help="(--task only) this task's acceptance proof is a MULTI-DAY POST-SHIP "
                                 "PRODUCTION OBSERVATION whose window opens only after the ship. Adds an "
                                 "overlay telling the auditor that reading's absence at the pre-land "
                                 "audit-post is EXPECTED, never a defect. Fail-closed on the card's own "
                                 "`post_ship_observation: {observation, due_by}` declaration, which keeps "
                                 "the deferred proof on the overdue-recheck debt view until a `settled_by` "
                                 "names where it landed (T-10916, SPEC-0036 / X-0710)")
            # T-11014 (SPEC-0176): activation-gated blast-radius carve-out (--task only). NINTH SIBLING
            # of --post-ship-observation / --preshipped-deliverable / --land-emitted-event / … in the
            # same deferred-proof family. When a card's own CLOSURE flips a `proposed` spec that
            # registers a CONCERN, the registry answers only for ALREADY-ACTIVE specs — so the fixtures
            # that activation invalidates are structurally invisible while the card is being planned and
            # audited, and the auditor faults the card for a forecast nobody could have written (T-10866
            # burned 4 audit passes, 2 owner resets and a full convergence consult on exactly that).
            # Anchored HARDER than any sibling, because the thing being deferred is scope fidelity
            # itself: `_require_activation_gated_radius` proves an OBJECTIVE STRUCTURAL PREDICATE from
            # corpus state, still demands an ordinary `expected_touch` forecast, and VERIFIES the card's
            # measured reconciliation against the real diff. It defers WHEN the evidence exists; it never
            # waives the check.
            ap.add_argument("--activation-gated-radius", dest="activation_gated_radius",
                            action="store_true",
                            help="(--task only) this card's own closure performs a concern ACTIVATION "
                                 "whose affected fixtures are hidden by live-active-only registry "
                                 "gating, so no up-front touched-file forecast could exist for them. "
                                 "Adds an overlay telling the auditor to judge scope fidelity against "
                                 "the card's MEASURED post-activation reconciliation for those paths "
                                 "ONLY — every other path stays under the ordinary forecast. Fail-closed "
                                 "on a structural eligibility predicate (the card must actually own such "
                                 "a proposed spec), on a still-required non-empty `expected_touch`, and "
                                 "on the reconciliation matching the real diff (T-11014, SPEC-0176)")
            # T-11753 (SPEC-0036 / X-1147): settlement-sweep carve-out (--task only). TENTH SIBLING
            # of --activation-gated-radius / --post-ship-observation / --preshipped-deliverable / … in
            # the same deferred-adoption family. A card whose WHOLE deliverable is settling deferred
            # probes on OTHER cards can never present it to its own audit-post: `task close
            # --settle-probe` self-commits each settlement immediately and journals it under the
            # SETTLED card's id, so the sweep card's own ship is card YAML + audit records +
            # events.jsonl — the exact set T-11405 stops as carrying NO authored content. Like
            # --preshipped-deliverable and UNLIKE the pure trust-model siblings, NOT taken on the
            # flag's word: `_require_settlement_sweep` proves every DECLARED swept card against the
            # journal (session-tied, in-window, integrated) and refuses fail-closed otherwise.
            ap.add_argument("--settlement-sweep", dest="settlement_sweep", action="store_true",
                            help="(--task only) this card's deliverable is a set of deferred-probe "
                                 "SETTLEMENTS written onto OTHER cards, each self-committed at the "
                                 "moment it was made — so this card's own ship is lifecycle "
                                 "bookkeeping by construction. Adds an overlay naming those "
                                 "settlement commits and telling the auditor their absence from THIS "
                                 "diff is the NORMAL ordering for this ship, never a defect. "
                                 "Fail-closed on --settled-task: every named card must have a "
                                 "journal-proven settlement made by THIS card's run (T-11753, "
                                 "SPEC-0036 / X-1147)")
            ap.add_argument("--settled-task", dest="settled_task", action="append", metavar="T-NNNN",
                            help="(with --settlement-sweep, repeatable) a card this sweep settled. "
                                 "The enumeration IS the claim and is verified against the journal: "
                                 "a named card with no session-tied, in-window, integrated "
                                 "settle-link `commit_landed` refuses the whole call (T-11753)")
            ap.add_argument("--zero-ship-diff", dest="zero_ship_diff", action="store_true",
                            help="(--task only) this is an already-live task being CLOSED with a ZERO "
                                 "ship-diff (nothing authored after lifecycle bookkeeping — the delivery "
                                 "IS the record of an existing fact). Adds a WAIVE overlay: there is 0 "
                                 "diff-facing content to audit, so the 'no diff / nothing shipped' "
                                 "category is never a defect (T-10059, SPEC-0036)")
            ap.add_argument("--evidence-locator", dest="evidence_locator", default="",
                            help="(with --zero-ship-diff) locator of the pre-existing immutable "
                                 "record/probe this no-diff close rests on (e.g. an events.jsonl ts / a "
                                 "probe id). REQUIRED by the fail-closed guard (T-10060) and recorded in "
                                 "the verdict YAML so `task close` re-verifies it at the close seam")
            # T-9412 (SPEC-0036/SPEC-0050 re-audit-after-close carve-out, X-0040 non-empty-delta half):
            # re-audit a DONE task's CURRENT tree (HEAD) so a post-close `land --rebaseline` no longer
            # deadlocks into the blunt `--no-tests`. --task only, status:done only, audits HEAD (no
            # --commit). Bypasses the stage/read gate (a done task cannot enter `stage Audit-post`).
            ap.add_argument("--reaudit-after-close", dest="reaudit_after_close", action="store_true",
                            help="(--task only) re-audit a status:done task's CURRENT tree (HEAD) for a "
                                 "post-close `land --rebaseline` when legitimate post-audit-post source "
                                 "changes made the original audit no longer cover the tree (X-0040/T-9412)")
            # T-12370 — WHICH COMMIT THE CURRENCY RE-AUDIT RECORDS ITSELF AT. The route audits HEAD
            # and that is unchanged; this names the commit the verdict is RECORDED at when HEAD is
            # this land's own `land: bookkeeping` self-commit, which an aborting land takes back off
            # the branch (`_land_rollback_bookkeeping_to_entry`) — leaving the row naming a commit no
            # branch contains and wedging the card (T-12315, measured 2026-09-10T23:46:24Z). Accepted
            # ONLY with `--reaudit-after-close`, and FAIL-CLOSED: the named sha must be an
            # ancestor-or-equal of HEAD AND its delta to HEAD must classify INERT, so it can only
            # ever name a commit carrying the SAME audited content. Internal — `land` passes it; a
            # hand caller has no reason to.
            ap.add_argument("--reaudit-subject", dest="reaudit_subject", metavar="SHA", default=None,
                            help="(with --reaudit-after-close) record this currency re-audit's verdict "
                                 "at SHA instead of HEAD — the branch tip the land merged, below this "
                                 "land's own bookkeeping self-commit. Refused unless SHA is an "
                                 "ancestor-or-equal of HEAD whose delta to HEAD is entirely INERT "
                                 "(T-12370)")
            # T-10567 (SPEC-0015 / X-0422): the SHIP-CUSTODY RE-PIN recovery (--task only, REQUIRES
            # --commit). NOT a deferred-adoption overlay like the siblings above — it re-pins the
            # audit-post COMMIT BINDING itself, so it is guarded by `_require_ship_custody_repin`'s four
            # fail-closed legs rather than by an auditor-prompt overlay. Registered on the `post`
            # subparser ONLY (structurally absent on `pre` — the --zero-ship-diff precedent).
            ap.add_argument("--repin-ship", dest="repin_ship", action="store_true",
                            help="(--task only, requires --commit) re-pin audit custody to this task's "
                                 "LANDED ship commit after a bookkeeping self-commit (park/pause/wont-do) "
                                 "displaced it — the wedge where audit-post can only audit the park diff "
                                 "(green-by-vacuity) and `task close` stays RED-blocked. Evidence-checked "
                                 "+ fail-closed: custody must be genuinely bookkeeping-shifted, --commit "
                                 "must EQUAL the displaced ship (an untied/older sha is REFUSED), every "
                                 "displacing record must be diff-limited to bookkeeping, and the ship must "
                                 "be an ancestor of main. Journal-evidenced, never a blind override "
                                 "(T-10567, SPEC-0015 / X-0422)")
        ap.add_argument("--full", action="store_true",
                        help="use full-capability model (big-plan/architectural); default routine per "
                             "bin/audit-config.yaml. NOTE: a --plan target is ALWAYS full regardless of "
                             "this flag (SPEC-0034 §Audit posture — plan-lifecycle audits never run routine).")
        ap.add_argument("--prompt-extra", dest="prompt_extra",
                        help="extra context appended to prompt")
        ap.add_argument("--from-file", dest="from_file",
                        help="path to file containing extra prompt content (appended after --prompt-extra)")
        # T-11407 (SPEC-0036 §Packet preview / X-1060, owner-authorized 2026-08-21). The asymmetry
        # this closes, measured at <project> T-0435: the only way to learn what the auditor will
        # actually SEE was to invoke it — which costs a ceiling pass, and past the ceiling costs an
        # owner grant. So the one question whose answer prevents the failure ("is my packet right?")
        # was gated behind the resource the failure consumes, and three RED passes plus an owner
        # grant were each spent discovering something a look at the packet answers for free.
        # Registered on BOTH stages (inside the shared pre/post loop) — the defect class is the same
        # at Stage 4 and Stage 8.
        ap.add_argument("--preview", dest="preview", action="store_true",
                        help="ASSEMBLE AND PRINT the audit packet, then STOP. No auditor is "
                             "invoked, no ceiling pass is consumed, no verdict is written and no "
                             "stage gate is satisfied — the only record is a read receipt "
                             "(audit_packet_previewed). It is this same verb stopping one step "
                             "earlier, so what it prints IS the packet the next real invocation "
                             "assembles. Carries two ADVISORY observations (declared-vs-audited "
                             "touch; no-journal-row-since-the-previous-RED) that gate nothing. "
                             "Ceiling-neutral by construction: it runs AT or PAST the audit-loop "
                             "ceiling, because a preview has no pass for the ceiling to bound. "
                             "Not combinable with --on-decisions"
                             # T-11165's help-honesty scan: `--absorb` is registered on the `pre`
                             # parser ONLY, so naming it in the `post` help would recommend a flag
                             # that verb does not accept.
                             + (" or --absorb" if stage_name == "pre" else " or --followup")
                             + " (T-11407, X-1060)")
        # SPEC-0204 rule 6 (T-12290) — `--owner-reset` is RETIRED on `audit pre|post` and is therefore
        # NOT registered here: an owner grant is no longer how a pass past the audit-loop ceiling is
        # admitted. Its replacement is `--on-decisions` directly below, whose basis is the Controller's
        # recorded `ceiling_decision` rows (`yitc-v2 audit decide`). The literal token is caught by the
        # PRE-PARSE shim in `main()` (`audit.retired_audit_surface_refusal`), so a caller holding a
        # pre-retirement brief gets the route rather than argparse's `unrecognized arguments`. Of the
        # two separately-registered flags of the same name, `task commit --absorb --owner-reset`
        # (E-0030) is OUTSIDE this retirement and still admitted at the commit door, while `plan stage
        # --owner-reset` (the plan-GATE reset, T-9286) was retired AFTER this comment was written, by
        # the plan-gate arm of the same rule (T-12335): it stays registered only as a refusal shim.
        # T-12289 (SPEC-0204 rules 3-5) — the DECISION-GOVERNED continuation, registered BESIDE
        # `--owner-reset` on BOTH stages because it is that flag's SIBLING: the same ONE bounded pass
        # past the audit-loop ceiling, admitted on a DIFFERENT basis. `--owner-reset` is an OWNER
        # grant; this is admitted by the engine ITSELF once every residual of the ceiling row carries
        # a recorded `ceiling_decision` (`yitc-v2 audit decide`, rule 2). The two are not combinable —
        # a pass admitted by one must not record the other as its basis.
        ap.add_argument("--on-decisions", dest="on_decisions", action="store_true",
                        help="Run the SPEC-0204 rule-3 pass: the ONE bounded audit pass PAST the "
                             "2-pass ceiling, governed by the Controller's recorded `ceiling_decision` "
                             "rows instead of by an owner reset. ADMITTED only when EVERY residual of "
                             "the ceiling row (its findings plus any rule-8 late findings) carries a "
                             "decision on that ceiling_ref AND the subject is the one revision those "
                             "decisions name; otherwise REFUSED `residual-undecided` / "
                             "`decisions-not-for-this-revision` / `evidence-revision-split` with no "
                             "auditor invoked and no pass spent. The auditor is asked to VERIFY each "
                             "`fix` at that revision, to treat `accept`/`defer` as settled, and to put "
                             "`echo_of: <fingerprint>` on every finding re-raising a residual (the "
                             "ENGINE verifies it). A RED here is TERMINAL for this (task, stage). "
                             "--task only; not combinable with --preview.")
        # T-13632 (SPEC-0036 §Absorption sweep) — the same-class sweep statement, on BOTH stages: with
        # `--absorb` (pre) it rides the mode-(b) record; on a re-audit pass (pre or post) it rides the
        # mode-(a) `audit_finding_absorbed` row. Absent → that row records `sweep: not stated`.
        # The help names only flags THIS stage's parser accepts (`--absorb` is pre-only — the
        # T-11165 help-vs-parser tripwire reads them together).
        ap.add_argument("--sweep", dest="sweep", metavar="TEXT",
                        help="the ABSORPTION SWEEP statement (SPEC-0036 §Absorption sweep): where you "
                             "searched the whole audited subject for the same defect class, and what "
                             "you found (a sweep that found nothing included). Recorded on the "
                             "audit_finding_absorbed row — "
                             + ("beside --absorb (mode b), or on the re-audit pass after a plan edit "
                                "(mode a). " if stage_name == "pre" else
                                "on the re-audit pass after an absorbing commit (mode a). ")
                             + "Without it the absorption still proceeds and records `sweep: not "
                               "stated` (T-13632)")
        if stage_name == "pre":
            # T-10770 (SPEC-0036 / LIFECYCLE Stage 4) — the MODE-(b) ABSORPTION route: a field-edit over
            # the audit-pre record THIS verb wrote, modelled on the shipped `task update --old/--new` /
            # `spec edit` field-edit analogs (D-0033: extend the verb already BEFORE the action rather
            # than add a new one). Before this, doctrine prescribed mode (b) — record the residual in the
            # existing verdict YAML's absorbed:/notes: WITHOUT re-planning and WITHOUT burning a ceiling
            # pass — while NO verb wrote those fields, so the only route was a hand-edit of a governed
            # YAML (forbidden by AGENTS §Verb-execution discipline, and journal-invisible).
            # PRE-ONLY BY CONSTRUCTION (audit-pre F1): LIFECYCLE Stage 4 is the only doctrine that
            # authorizes mode (b) — Stage 8 does not — so the flag is structurally ABSENT on `post`
            # (the --zero-ship-diff / --repin-ship stage-scoping precedent), never merely rejected there.
            # T-12734 (X-1500) — REPEATABLE. argparse's default `store` kept only the LAST of two
            # `--absorb` values and exited 0, so the first absorption text vanished from the record
            # (measured by <project>). `append` makes N occurrences N ordered entries; the values are
            # normalized ONCE in `audit.py#absorb_texts` (the one home both consumer seams read).
            ap.add_argument("--absorb", dest="absorb", metavar="TEXT", action="append",
                            help="MODE-(b) ABSORPTION (LIFECYCLE Stage 4): record a residual YELLOW "
                                 "finding into the EXISTING saved audit-pre record's absorbed:/notes: "
                                 "WITHOUT re-planning — a field-edit, not an audit. Runs NO auditor, "
                                 "leaves verdict:/passes:/plan_fingerprint: untouched (ceiling-neutral) "
                                 "and emits audit_finding_absorbed so the absorption is journal-visible "
                                 "cross-session. Refused on a non-YELLOW record and on a record whose "
                                 "custody was re-pinned (T-10770). With `--plan <slug> --gate <id>` it "
                                 "absorbs into that PLAN GATE's verdict instead, on the same terms "
                                 "(T-11167, SPEC-0124 §Audit-loop ceiling / X-0928). REPEATABLE: "
                                 "every occurrence is recorded, in order, as its own entry — a "
                                 "second --absorb is never silently dropped (T-12734)")
            # T-11167 (X-0928) — the plan-gate half of --absorb. REUSES SPEC-0124's existing gate
            # identity (PLAN_CONSULT_GATES, the same tokens `audit consult --plan --gate` takes) rather
            # than inventing a second vocabulary; registered on `pre` only, beside the flag it qualifies.
            # T-12987 — accept the stage name `plan stage` prints (e.g. gate-specs) as an alias, mapped
            # through the ONE template->gate-id table (plan.py#_PLAN_TEMPLATE_TO_GATE_ID) via the
            # injected host handle, never an import. Unknown values pass through, so `choices` refuses.
            ap.add_argument("--gate", dest="gate", choices=PLAN_CONSULT_GATES,
                            type=lambda s: _SELF._PLAN_TEMPLATE_TO_GATE_ID.get(s, s),
                            help="(with --absorb --plan) which ceiling-bearing PLAN GATE's verdict holds "
                                 "the residual being absorbed. Same SPEC-0124 gate identity as `audit "
                                 "consult --plan --gate` (T-11167). The stage name `plan stage` prints "
                                 "(gate-specs, gate-trial, gate-accepted, gate-executing) is accepted "
                                 "as an alias of its gate id (T-12987). "
                                 # T-11993 (X-1229) — the naming line, consumed from its one home so
                                 # the help and the two refusals cannot drift apart.
                                 + _SELF.PLAN_ACCEPT_GATE_NAMING)
        if stage_name == "post":
            # T-13542 (LIFECYCLE Stage 8 / SPEC-0036 §Saved audit result) — the FOLLOW-UP RECORD route,
            # the post-side sibling of `--absorb` above. Stage 8 closes a YELLOW as «file follow-up
            # task for findings, proceed» and the saved verdict carries `followups:` for those ids,
            # but the audit writers only ever wrote the empty list — so the record the doctrine names
            # was reachable by hand-editing a governed YAML alone. POST-ONLY BY CONSTRUCTION, the
            # mirror of `--absorb` being pre-only: structurally absent on `pre`, never merely
            # rejected there. REPEATABLE (`append`, the T-12734 lesson: `store` keeps the last value
            # and drops the rest silently); values are normalized in `audit.py#followup_ids`.
            ap.add_argument("--followup", dest="followup", metavar="ID", action="append",
                            help="RECORD A FILED FOLLOW-UP (LIFECYCLE Stage 8): add the id of the "
                                 "follow-up filed for a residual YELLOW finding — a task id (T-NNNN) "
                                 "or a followup id (fu_ + 12 hex) — to the EXISTING saved audit-post "
                                 "record's followups: — a field-edit, not an audit. --task only. Runs "
                                 "NO auditor, leaves verdict:/passes:/commit: untouched "
                                 "(ceiling-neutral) and emits audit_finding_absorbed (mode: followup) "
                                 "so the record is journal-visible cross-session. Refused when there "
                                 "is no saved record, the verdict is not YELLOW, or the id does not "
                                 "resolve, with nothing written. REPEATABLE: every id is recorded, in "
                                 "order; an id already recorded is skipped. Not combinable with any "
                                 "audit-run flag. `task close` does not require it (T-13542)")
        ap.set_defaults(func=cmd_audit, cli_invoked_receipt=f"audit {stage_name}")  # T-13071: attempt receipt
    # T-0361: open-form (ad-hoc) consult — one verb instead of hand-reconstructed codex invocations.
    aa = audit_sub.add_parser("adhoc",
                              help="Run an open-form (ad-hoc) external-audit consult: free-form prompt "
                                   "+ V2 lens; FULL model by default (--routine opts down); saves "
                                   "decisions/<slug>-audit-adhoc.yaml (stage: ad-hoc) + emits events")
    aa.add_argument("--slug", required=True,
                    help="filename-safe consult id ([A-Za-z0-9][A-Za-z0-9-]*) — names "
                         "decisions/<slug>-audit-adhoc.yaml; a T-NNNN/D-NNNN slug records that "
                         "node as the audited target")
    aa.add_argument("--prompt", help="the free-form request text (combined with -f/--from-file if both given)")
    aa.add_argument("-f", "--from-file", dest="from_file",
                    help="path to a file containing the request (REPO_ROOT-relative or absolute); "
                         "stdin is the fallback when neither --prompt nor -f given")
    aa.add_argument("--routine", action="store_true",
                    help="use the routine-tier model instead of the FULL default (an open-form "
                         "consult defaults to full-capability per bin/audit-config.yaml)")
    aa.add_argument("--read-corpus", dest="read_corpus", action="store_true",
                    help="corpus-READING consult: AUTO-INLINE the corpus files referenced in the "
                         "request into the prompt (fail-closed under REPO_ROOT, size/count-capped) "
                         "so the auditor never hits the no-read-tooling ABORT (T-9318; the auditor "
                         "declines `-s read-only` tooling — F-020). Falls back to read-only tooling "
                         "when no referenced file is inlinable. Opt-in; default off (prompt-only).")
    aa.add_argument("--sweep-file", dest="sweep_file", action="append", metavar="PATH",
                    help="inline an EXPLICIT pre-computed mechanical sweep file (journal/git output) "
                         "into the prompt — the sibling channel to --read-corpus for journal/git DATA "
                         "(T-9637 / X-0125). Repeatable. Read from ANY path (NOT REPO_ROOT-fenced — "
                         "sweeps live in scratch / outside the engine root under -C); a missing sweep "
                         "fails LOUD so a -C external blind pass never silently returns NO-DATA on "
                         "journal/git-grounded themes. Inlined as raw DATA, not the primary track's "
                         "findings (SPEC-0057 §1(c) independence).")
    # T-13495 (SPEC-0124 §Audit-loop ceiling) — the AD-HOC arm of the mode-(b) absorption field edit,
    # the third registration beside `audit pre --task` (T-10770) and `audit pre --plan --gate`
    # (T-11167). `append` for the T-12734 reason: `store` keeps the last of two values and drops the
    # first silently; the values are normalized in the same one home, `audit.py#absorb_texts`.
    aa.add_argument("--absorb", dest="absorb", metavar="TEXT", action="append",
                    help="MODE-(b) ABSORPTION: record a finding of the SAVED ad-hoc consult for "
                         "--slug as absorbed — a field-edit of that record's absorbed:/notes:, not a "
                         "consult. Runs NO auditor, leaves verdict:/passes:/findings: untouched and "
                         "emits audit_finding_absorbed (target_kind adhoc), so a later audit reading "
                         "the record sees what was absorbed. Finds the record in decisions/ or in "
                         "its archive. Refused, with nothing written, when there is no saved record "
                         "for the slug, the record does not parse, or its verdict is not YELLOW. "
                         "REPEATABLE: every occurrence is recorded, in order, as its own entry. Not "
                         "combinable with --prompt, -f/--from-file, --routine, --read-corpus or "
                         "--sweep-file (T-13495)")
    aa.set_defaults(func=cmd_audit_adhoc)
    # T-0429: ceiling-convergence triage consult (SPEC-0124 §Audit-loop ceiling) — a NAMED audit
    # subcommand mechanizing the pass-3 triage. Refuses below the ceiling; saves a structured
    # survivors/recommendation verdict that `audit pre|post --owner-reset` verifies as the basis.
    ac = audit_sub.add_parser("consult",
                              help="Adversarial consult: submit >=2 resolution options and the "
                                   "external auditor names survivors + a single recommendation. Saves "
                                   "decisions/<tid>-audit-consult-<key>.yaml. TWO live forms: the "
                                   "BELOW-ceiling technical-fork pick (--on-demand --task) and the "
                                   "PLAN-GATE consult (--plan --gate), which is the basis `plan stage` "
                                   "verifies for its own gate continuation. The TASK --task --stage "
                                   "ceiling-adjudication form is RETIRED (SPEC-0204 rule 6) and "
                                   "REFUSES with a pointer to `audit decide`.")
    ac.add_argument("--task", help="T-NNNN id of the task at its audit-loop ceiling (with --stage). "
                                   "Mutually exclusive with --plan/--gate.")
    ac.add_argument("--stage", choices=("pre", "post"),
                    help="the TASK audit stage this triage is for (pre = plan-quality ceiling, post = "
                         "ship-quality ceiling). REQUIRED with --task; task-only (use --gate for a plan).")
    ac.add_argument("--plan", help="T-9286 — plan slug at a plan-gate ceiling (with --gate). The "
                                   "PLAN-target consult (SPEC-0124 §Plan-target parity).")
    ac.add_argument("--gate", choices=PLAN_CONSULT_GATES,
                    help="REQUIRED with --plan — the ceiling-bearing plan gate this triage is for "
                         "(reuses SPEC-0124's existing gate identity: draft-specs | specs-trial | "
                         "trial-accepted | decomposition-executing | finalization).")
    ac.add_argument("--option", action="append",
                    help="a candidate resolution option (repeatable; >=2 required). May also be given "
                         "one-per-line via -f/--from-file or stdin.")
    ac.add_argument("-f", "--from-file", dest="from_file",
                    help="path to a file with one resolution option per line (REPO_ROOT-relative or "
                         "absolute); stdin is the fallback when neither --option nor -f given")
    ac.add_argument("--full", action="store_true",
                    help="(default ON for a consult — the triage is the architectural/full class per "
                         "SPEC-0036 audit posture; flag retained for surface parity)")
    # T-10094 — post-close rebaseline consult carve-out (mirror `audit post --reaudit-after-close`,
    # T-9412/X-0040). A status:done task's post-close `land --rebaseline` re-audits HEAD, so the
    # ceiling-convergence consult that authorizes it MUST bind its basis to HEAD too — else the
    # consult basis (pinned to the last commit_landed) diverges from HEAD once HEAD moves via a
    # non-task-commit path (raw-git / land-bookkeeping / rebaseline) and the converged consult can
    # never re-open the owner-reset (the T-10081 dead-end). --task --stage post only.
    ac.add_argument("--reaudit-after-close", dest="reaudit_after_close", action="store_true",
                    help="(--task --stage post only) pin the consult basis to HEAD rather than to the "
                         "last recorded commit, for a status:done task re-baselining post-close "
                         "(X-0040/T-9412, T-10094). INERT since SPEC-0204 rule 6 retired the --task "
                         "--stage consult form: every invocation that could carry this flag is refused "
                         "by that retirement first. Kept registered only so the refusal a live caller "
                         "meets is the retirement pointer, not an unknown-flag error.")
    ac.add_argument("--on-demand", dest="on_demand", action="store_true",
                    help="T-9684 (lever #6) — BELOW-ceiling ON-DEMAND technical-fork variant-pick (with "
                         "--task + >=2 --option). The auditor ratifies TECHNICAL merit (escalates a "
                         "value/draft fork); fail-closed single-survivor; the owner keeps a lightweight "
                         "ratify/veto. NOT retired by SPEC-0204 rule 6 and unchanged by it: it is a "
                         "BELOW-ceiling design-fork pick on its own distinct consult key, never a "
                         "post-ceiling basis. Not for --plan/--gate (SPEC-0124 §On-demand technical-fork "
                         "consult).")
    # SPEC-0204 rule 6 (T-12290) — `--reopen` (and its `--reason` grant locator) is RETIRED and is
    # therefore NOT registered: there are no consult EPISODES left to re-open, so nothing can allocate
    # an episode n+1. A residual past the ceiling is settled by ONE typed `ceiling_decision`
    # (`yitc-v2 audit decide`) and verified by ONE `audit pre|post --on-decisions` pass. The literal
    # token is caught by the PRE-PARSE shim in `main()` so a pre-retirement caller gets that route.
    # `--on-demand` above and the `--plan --gate` target are NOT retired and are unchanged.
    ac.set_defaults(func=cmd_audit_consult)
    # T-12287 (SPEC-0204 rule 2) — `audit decide`: ONE append-only `ceiling_decision` journal row
    # per residual, Controller-only, the authorizing owner directive RESOLVED at write. No worktree
    # (D-0049 journal append, folded at land).
    ad = audit_sub.add_parser("decide",
                              help="Record ONE typed Controller decision for ONE residual of a "
                                   "ceiling row (SPEC-0204 rule 2): appends a single append-only "
                                   "`ceiling_decision` journal row — no worktree, no store, no "
                                   "auditor, no pass. TWO target kinds on one ladder: a TASK "
                                   "(--task --stage) and a PLAN GATE (--plan --gate). REFUSED in a "
                                   "dispatched-worker context and below the audit-loop ceiling.")
    # T-12335 (SPEC-0204 plan-gate arm) — the two target forms are MUTUALLY EXCLUSIVE and neither is
    # argparse-`required`: the pair-completeness and either/or checks are GOVERNED refusals in the verb
    # (with a journal row) rather than bare usage errors, which is the shape `--directive` below
    # already takes and the reason it is not `required` either.
    _adt = ad.add_mutually_exclusive_group(required=True)
    _adt.add_argument("--task", help="T-NNNN id whose (task, stage) reached the ceiling (with --stage)")
    _adt.add_argument("--plan", help="plan slug whose GATE reached the ceiling (with --gate). The "
                                     "PLAN-target decision (SPEC-0204 plan-gate arm) — its ONE bounded "
                                     "pass is `plan stage <NEXT> --on-decisions`, not `audit pre`")
    ad.add_argument("--stage", choices=("pre", "post"),
                    help="the TASK audit stage the ceiling row belongs to — REQUIRED with --task; use "
                         "--gate for a plan")
    ad.add_argument("--gate", choices=PLAN_CONSULT_GATES,
                    help="REQUIRED with --plan — the ceiling-bearing plan gate the ceiling row belongs "
                         "to (the SAME SPEC-0124 gate identity `audit pre --plan --gate` takes: "
                         + " | ".join(PLAN_CONSULT_GATES) + ")")
    ad.add_argument("--finding", required=True, metavar="FP",
                    help="ONE residual per call: the key the ENGINE assigned to the residual being "
                         "decided — a residual of the ceiling row, or a recorded late finding at that "
                         "stage. A ceiling carrying N residuals takes N `audit decide` calls, one "
                         "--finding each, so no decision ever stands for more than one (X-1554). The "
                         "key is `fp1:` for a finding carrying criterion_ref + locator + "
                         "failing_input, else the read-time `fp1d:` key over what + where (the usual "
                         "plan-gate shape). Copy it from a refusal that lists the residuals — never "
                         "recompute `finding_fingerprint()` by hand")
    # `_SELF.audit` (not a bare `audit`): inside build_parser the name `audit` is the audit
    # SUB-PARSER local. The module attribute keeps the disposition vocabulary single-sourced
    # in bin/lib/audit.py rather than re-spelled here (CHARTER §P5).
    ad.add_argument("--disposition", required=True,
                    choices=_SELF.audit.CEILING_DECISION_DISPOSITIONS,
                    help="fix (a change follows — needs --evidence) | accept (the residual stands; "
                         "the reason MUST quote the authorizing words) | defer (the work rides a "
                         "named card — needs --receiving)")
    # T-12617 (E-0054, X-1427) — `required=True` REMOVED: the reason may arrive in the --from-stdin
    # mapping instead, and `stdin_argv_flag_conflicts` REFUSES it on both routes at once. Its
    # absence is therefore a GOVERNED refusal inside the verb (with a journal row), exactly the
    # posture `--directive` below already takes, rather than a bare argparse usage error.
    ad.add_argument("--reason",
                    help="why this disposition (non-empty). For `accept` it MUST quote the "
                         "authorizing words verbatim from the resolved directive. REQUIRED but not "
                         "an argparse requirement — pass it here or as `reason:` in the "
                         "--from-stdin mapping; its absence is a governed refusal. An argv reason "
                         "carrying a BACKTICK is REFUSED (the shell substitutes `...` before this "
                         "verb runs, and the row it lands in is append-only) — use --from-stdin")
    # T-12401 (X-1369) — the help names HOW a row covers the card. Three shapes and no fourth, the
    # `data.cards` arm by name (it appeared in no doc at all), and the delegated route for a verbatim
    # owner cue that does not name the card. The full recipe lives in the refusal
    # (`audit.DIRECTIVE_COVERAGE_HELP`); the rule is homed in SPEC-0204 rule 2.
    ad.add_argument("--directive", metavar="LOCATOR",
                    help="the owner-directive locator `events.jsonl#ts=<ISO>` authorizing this "
                         "decision. REQUIRED and RESOLVED at write — deliberately not an argparse "
                         "requirement, so its absence is a GOVERNED `directive-missing` refusal with "
                         "a journal row rather than a bare usage error. The row must COVER this card "
                         "in one of THREE token-exact shapes (SPEC-0204 rule 2): the task id is an "
                         "element of its `cards` list (the BATCH shape — `data.cards`); the id "
                         "appears as a whole token in its prose; or the slug the card is "
                         "`decomposed_from` appears in either. When the owner's own row names no "
                         "card, capture a covering `owner_directive` row first (see `yitc-v2 event "
                         "--help` for that verb's flags): mark it `captured_via: controller-delegated`, "
                         "list this card in its `cards`, and have its text CITE the owner row by "
                         "`events.jsonl#ts=<ISO>` — the cited owner row must already exist, must not "
                         "itself be delegated, and must PRECEDE it. The refusal on a non-covering "
                         "directive prints the whole route, argv included")
    ad.add_argument("--receiving", metavar="T-YYYY",
                    help="(defer) the FILED, non-terminal card the deferred work rides. A followup "
                         "id is not a card")
    ad.add_argument("--evidence", metavar="REVISION",
                    help="(fix) the revision carrying the change — at post a STRICT descendant of "
                         "the audited commit, at pre the card's CURRENT plan fingerprint, at a plan "
                         "gate the plan body's CURRENT signature. At the decomposition-executing gate "
                         "`fix` IS admitted: its subject is the filed card set, so the evidence is the "
                         "CURRENT card-set fingerprint of the repaired cut (SPEC-0204 rule 9(d)). At "
                         "the finalization gate `fix` is refused by name (its corpus_signature is not "
                         "computable at decide time) — use accept or defer there")
    # T-12617 (E-0054, X-1427) — the shell-proof route the prose-bearing siblings already carry
    # (`task file`, `task update`, `followup add`, `task commit`, `work commit`, `blocked-on-land`,
    # `worktree park`). It matters MOST here: `--reason` is prose and the `ceiling_decision` row is
    # append-only (SPEC-0204 rule 4), so an argv reason the shell rewrote is uncorrectable.
    ad.add_argument("--from-stdin", action="store_true",
                    help="read the decision's CONTENT fields as a YAML mapping on stdin (`reason:`, "
                         "`directive:`, `receiving:`, `evidence:`) instead of on argv — the "
                         "SHELL-PROOF route: stdin never rides the shell, so a reason carrying "
                         "backticks round-trips into the append-only row VERBATIM (it is not even "
                         "whitespace-stripped). The TARGET flags (--task/--plan/--stage/--gate/"
                         "--finding/--disposition) stay on argv and keep working alongside it; "
                         "sending one in the mapping is refused by name. Passing a content field "
                         "BOTH ways is refused before anything is written")
    ad.set_defaults(func=cmd_audit_decide, cli_invoked_receipt="audit decide")  # T-13071: attempt receipt
    # T-0068 (D-0035): aspect-audit runner — AI-performed checklist + findings into the errors channel.
    ar = audit_sub.add_parser("run", help="Run an aspect-audit (--aspect); record findings into the errors channel")
    ar.add_argument("--aspect", required=True,
                    help="doc-conformance|doc-health|cli-vs-manual|resource|ai-failure-class|meta")
    ar.add_argument("--finding", action="append",
                    help="a finding to record as a deviation_captured event (repeatable)")
    ar.add_argument("--kind", help="optional kind (defect|friction|improvement) — decided in triage if omitted (SPEC-0056 §1)")
    ar.add_argument("--impact", help="low|med|high (or cost bucket) for recorded findings")
    ar.add_argument("--fingerprint", help="stable recurrence key for recorded findings")
    ar.add_argument("--error", help="E-XXXX to tag findings with / ref the --external verdict back into")
    ar.add_argument("--external", action="store_true",
                    help="get an external opinion at the promotion boundary (folds the confirm step)")
    ar.set_defaults(func=cmd_audit_run)
    # T-0633 (SPEC-0066 §3): the weekly-Review BACKSTOP for the conditional per-land host-leak canary.
    # A thin run-and-emit verb (no args) — runs the canary once on main, confirms green, emits
    # canary_backstop_ran. Invoked by the QUEUE §Re-review-triggers weekly line; nets the per-land
    # skip's single residual (a SPEC-0064 classifier misclassification).
    # T-12380 (SPEC-0202 rule 4): the read-only auditor-resolution view — the post-/compact RE-FOLD of
    # the session-start external-auditor hint (SPEC-0201 rule 3). No args, no write, no event of its own
    # (T-12846: only the T-0113 cli_invoked invocation receipt, via the receipt-only marker).
    ast_ = audit_sub.add_parser("status",
                                help="READ-ONLY: the resolved external auditor per tier (provider / "
                                     "binary / home / model + which layer answered: env → machine "
                                     "binding → PATH → repo config), its independence (external | "
                                     "same-provider), the bound-vs-shipped-default model and the "
                                     "same-provider verdict count. The post-/compact RE-FOLD of the "
                                     "session-start hint (AGENTS §After-/compact); STATES its silence "
                                     "when an external provider resolves. No write, no event of its "
                                     "own (only the cli_invoked invocation receipt, T-12846)")
    ast_.set_defaults(func=cmd_audit_status, cli_invoked_receipt="audit status")  # T-12846
    cb = audit_sub.add_parser("canary-backstop",
                              help="Weekly-Review backstop (SPEC-0066 §3): run the host-leak canary "
                                   "once on main, confirm green, emit canary_backstop_ran")
    cb.set_defaults(func=cmd_audit_canary_backstop,
                    read_only_refuse="runs the host-leak canary and emits canary_backstop_ran")

    # T-9640 (SPEC-0057 §6 / X-0127): the inspection (ревизия) run-recorder — emits ONE
    # inspection_completed per theme run with a REAL checklist-hash criteria_ref. Manual-first, owner-
    # invoked, NO cron (SPEC-0057 §2). Replaces the hand-`event inspection_completed` faked-ref emit.
    insp = sub.add_parser("inspect", help="Inspection (revizia) run-recorder — emit inspection_completed with a checklist-hash criteria_ref (SPEC-0057 §6)")
    insp_sub = insp.add_subparsers(dest="inspect_action", required=True)
    inr = insp_sub.add_parser("record", help="Emit one inspection_completed for a theme run (real checklist-hash criteria_ref; manual-first, owner-invoked)")
    inr.add_argument("--theme", help="the run's theme — one of T1..T10 (the fixed SPEC-0057 §3 roster; T10 = real-work observation loop, SPEC-0135) OR a consumer-declared theme slug from this consumer's yitc-ops.yaml inspection.themes[] (SPEC-0093 rule 12; an undeclared slug is refused, T-10235). Give this XOR --tier.")
    inr.add_argument("--tier", help="record a TIER-level run instead of a theme — currently `weekly` (the operational-hygiene sweep, SPEC-0057 §9). Give this XOR --theme (T-10134).")
    inr.add_argument("--task", help="tie this run to a task id (T-NNNN) — records it in the emitted event's task_id slot so a card whose AC names an inspection_completed probe renders that proof in its audit-post packet (T-10320). Omit for an untied run (task_id=None, the default, unchanged).")
    inr.add_argument("--findings-count", type=int, default=0, help="number of findings the run surfaced (default 0 — a zero-findings run still records, SPEC-0057 §6)")
    inr.add_argument("--high-count", type=int, default=0, help="number of HIGH-severity findings (default 0)")
    inr.add_argument("--no-data", dest="run_no_verdict", action="store_true", help="the run produced NO VERDICT — aborted / crashed / never started (SPEC-0173 rule 1, T-10837). Records the run as NO-DATA: it does NOT mark the subject reviewed and does NOT reset its review-due clock. Refused together with a nonzero --findings-count/--high-count (a run that produced no data cannot report findings)")
    inr.add_argument("--dry-run", dest="dry_run", action="store_true", help="READ-ONLY wiring proof: compute + print the inspection_completed payload shape (theme accepted + real criteria_ref) WITHOUT emitting the event (T-10125)")
    inr.add_argument("--lenses", help="comma-separated lenses covered this run (e.g. doc-anchor-resolve,rule-extraction)")
    inr.add_argument("--tracks", help=f"comma-separated TRACKS that actually ran this run — {', '.join(inspection.TRACKS)} (the SPEC-0057 §Run-mode dual-track vocabulary; an unrecognised name is refused, not dropped). Recorded as `tracks_covered` on the event and rendered on every run, so a SINGLE-TRACK run reads differently from one where both tracks ran (T-11043). COVERAGE ONLY — it is not a colour, score or grade, and it does not record whether the tracks CONVERGED (SPEC-0057 §4 fence). Omit it and the run records as coverage NOT RECORDED, which is not a claim that both tracks ran")
    inr.add_argument("--notes", help="free-text findings of this run — the selected units with their measured numbers, each finding's source or HYPOTHESIS label, and the ids it was routed to (T-12595). Recorded as `notes` on the event; omitted when not given")
    inr.set_defaults(func=cmd_inspect_record, read_only_admit=RO_EVIDENCE)

    # T-10264 (SPEC-0147 §1/§2): consume-on-encounter — the ONE governed seam that retires a voiced
    # onboarding station. Delete + emit in one step, so the buffer's consume-once discipline (SPEC-0039
    # §5b, prose-only distributed enforcement until now) cannot be half-done by a forgetful session.
    mem = sub.add_parser("memory", help="MEMORY.md buffer operations (the SPEC-0039 consume-once buffer)")
    mem_sub = mem.add_subparsers(dest="memory_action", required=True)
    mc = mem_sub.add_parser("consume", help="Consume-on-encounter: a voiced onboarding station retires — delete its [onboarding:<id>] pointer + emit onboarding_station_consumed (SPEC-0147 §1/§2)")
    # T-10306 (X-0273): `--station` is the CANONICAL form — it is what every seam prints
    # (memory.seam_nudge / memory.pointer_digest), so a session obeying the printed hint verbatim
    # now succeeds. The positional survives (nargs="?") for backward compatibility. Separate dests
    # are required: a positional and an optional sharing dest `station` do NOT compose — the
    # positional is parsed last and its None default clobbers a value the flag already set.
    mc.add_argument("station", nargs="?", help="the station id whose pointer was just VOICED at its work-juncture (historical positional form; --station is canonical)")
    mc.add_argument("--station", dest="station_flag", metavar="ID", help="the station id whose pointer was just VOICED at its work-juncture — the canonical form every seam hint prints")
    mc.add_argument("--user", help="the recipient (default: this session's provisioned user identity). A pointer addressed to another person is never drained.")
    # T-13217 (SPEC-0147 rule 10): a due repeat of the full body / the person's «I know it» — one journal row each.
    mc.add_argument("--repeat", action="store_true", help="record a DUE repeat of this station's full body (refused when not due; no MEMORY.md write)")
    mc.add_argument("--known", action="store_true", help="the person said «I know it» — one idempotent ack row; this station never repeats again")
    mc.set_defaults(func=cmd_memory_consume, read_only_refuse="rewrites the target's MEMORY.md and commits it")

    # T-10275 (SPEC-0147 §7): the seed half of the same buffer discipline. The ONE governed
    # seed-write path, shared in-process with project `init`. Host-invocable as
    # `<engine>/bin/yitc-v2 -C <project> memory seed --user <name>` — which is how the host's
    # provision-user.sh (EXTERNAL territory, never edited from here) grants a person their stations.
    ms = mem_sub.add_parser("seed", help="Seed a person's onboarding station pointers into this project's MEMORY.md, tagged user(<name>) — idempotent; emits onboarding_seeded (SPEC-0147 §7)")
    ms.add_argument("--user", help="the recipient (default: this session's provisioned user identity). Host/access-grant callers pass the provisioned name explicitly.")
    ms.set_defaults(func=cmd_memory_seed)

    # T-0152 (D-0086 §3/§5): the triage run — slow-lane sweep riding the Review re-review scan.
    # SWEEP + REPORT + WATERMARK scaffold; routing is via existing verbs (the verb does not mutate cases).
    triage = sub.add_parser("triage", help="Triage run — sweep un-routed captures, report routes + checklist, emit watermark (SPEC-0055)")
    triage_sub = triage.add_subparsers(dest="triage_action", required=True)
    trr = triage_sub.add_parser("run", help="Sweep deviation_captured since last watermark; print routes + SPEC-0056 §1 checklist. --complete emits the watermark")
    trr.add_argument("--complete", action="store_true",
                     help="emit the triage_run_completed watermark (closes this run's window)")
    trr.add_argument("--through", metavar="TS",
                     help="T-0542 gap-free: pin window_through to the READ run's max ts (the `triage run` "
                          "read prints the value). With --complete. Omitted = best-effort rescan-max "
                          "(read→complete-gap residual deferred to T-0533).")
    trr.add_argument("--event-only", nargs="+", action="append", metavar="FP",
                     help="T-13015: with --complete, RECORD an explicit event-only disposition for the "
                          "window's carrier-less captures of these fingerprints (fail-closed on a miss)")
    trr.add_argument("--event-only-rest", action="store_true",
                     help="T-13015: with --complete, record event-only for EVERY remaining carrier-less "
                          "window capture (incl. no-fingerprint). Without it they stay queued.")
    trr.add_argument("--routed", type=int, help="DEPRECATED (T-9639): routed is now DERIVED from the per-capture route set; this flag no longer overrides the recorded count")
    trr.add_argument("--linked", type=int, help="DEPRECATED (T-9639): linked is now DERIVED (cites-owned subset); this flag no longer overrides the recorded count")
    trr.add_argument("--promoted", type=int, help="count promoted to fix-task/E-XXXX (with --complete)")
    trr.set_defaults(func=cmd_triage_run, read_only_refuse="routes the target's captures and --complete writes its triage watermark")
    # T-11675 (X-1131): record a remedy-existence verdict against an ALREADY-CAPTURED fingerprint.
    # SPEC-0063 §1 requires the verdict before a TRULY-NEW is promoted, but the capture-time
    # `remedy_ref` is unwritable at triage time — which is exactly when the backlog sweep happens.
    trm = triage_sub.add_parser("remedy",
                                help="Record a remedy-existence verdict for an already-captured "
                                     "fingerprint (SPEC-0063 §1 sweep; clears ⚠ REMEDY-UNSWEPT "
                                     "without touching any recurrence count). --remedy must state "
                                     "its re-test direction: --retested (a real clearance) or "
                                     "--no-retest (the artifact is recorded, the candidate is not "
                                     "cleared)")
    trm.add_argument("--fp", required=True, metavar="FINGERPRINT",
                     help="the ALREADY-CAPTURED fingerprint this verdict is about (fail-closed: an "
                          "uncaptured fingerprint is refused)")
    trm.add_argument("--remedy", metavar="REF",
                     help="the analog remedy that ALREADY EXISTS (a path / verb / spec / task id) "
                          "⇒ ALREADY-BUILT — confirm it covers this, do NOT file a duplicate")
    trm.add_argument("--absent", action="store_true",
                     help="the sweep RAN and found NO analog ⇒ REMEDY-ABSENT — a genuinely-new "
                          "TRULY-NEW the sweep cleared into-work")
    trm.add_argument("--retested", metavar="TEXT",
                     help="the ORIGINAL FAILING INPUT you re-ran against the remedy, and what it did "
                          "(T-11936) — this is what turns --remedy into an ALREADY-BUILT CLEARANCE. "
                          "Required with --remedy unless --no-retest is given")
    trm.add_argument("--no-retest", dest="no_retest", metavar="WHY",
                     help="WHY the original failing input cannot be re-run (T-11936) — the artifact "
                          "found is still recorded, but the verdict is REMEDY-UNSWEPT, NOT a built "
                          "verdict: an un-re-tested sweep does not clear a candidate")
    trm.add_argument("--swept", metavar="TEXT", help="WHAT was swept (provenance for the next reader)")
    trm.add_argument("--found", metavar="TEXT", help="WHAT the sweep found (the reasoning, not just the verdict)")
    trm.add_argument("--task", metavar="T-NNNN", help="the task this sweep was performed under (optional)")
    trm.set_defaults(func=cmd_triage_remedy)
    # T-0527/SPEC-0052: the displacement-retention DRAIN (backstop) — git-mv every closed task's
    # audit YAMLs out of active decisions/ into the routine/escalation archive. The eventual-
    # consistency net behind the at-closure drain. --dry-run reports what would move, mutates nothing.
    trs = triage_sub.add_parser("sweep", help="Displacement-retention drain (SPEC-0052): archive closed-task audit YAMLs into decisions/archive/; idempotent. --dry-run to preview.")
    trs.add_argument("--dry-run", action="store_true", help="report what would be archived; move nothing")
    trs.set_defaults(func=cmd_triage_sweep, read_only_admit=("dry_run", RO_ZERO_WRITE))

    graph = sub.add_parser("graph", help="Spec↔code graph operations")
    graph_sub = graph.add_subparsers(dest="graph_action", required=True)
    gb = graph_sub.add_parser("build", help="Build graph/index.json from artifacts (specs/patterns/plans/errors + rules)")
    gb.set_defaults(func=cmd_graph_build, read_only_refuse="rewrites the target's graph/index.json — read it with `graph query`")
    gc = graph_sub.add_parser("conformance",
                              help="Binding-coverage conformance self-test (T-0284): RED if any active "
                                   "spec lacks a valid binding token; graph build stays non-validating")
    gc.set_defaults(func=cmd_graph_conformance, cli_invoked_verb="graph conformance", read_only_admit=RO_READ)  # T-0310: journal the verdict (exit_code + additive verdict key); stays report-only, NOT a gate
    grv = graph_sub.add_parser("release-view",
                               help="Generate the identity-agnostic release view of the handbook "
                                    "(T-0866 / SPEC-0074): a clean DERIVED view cut from the single "
                                    "engine source into release-view/. Engine-only (refused under -C).")
    grv.set_defaults(func=cmd_graph_release_view)
    gq = graph_sub.add_parser("query", help="Query node by ID or --type")
    gq.add_argument("id", nargs="?", help="SPEC-XXXX | T-XXXX | D-XXXX | E-XXXX | file path | <view-name>")
    gq.add_argument("arg", nargs="?", help="optional target for a saved view lens that takes one (e.g. `graph query task-scorecard T-XXXX`); ignored by other queries")
    gq.add_argument("--type", help="list nodes of type: spec|pattern|plan|error|scenario|rule|view (view = saved-lens catalog)")
    gq.add_argument("--recurring", action="store_true",
                    help="with --type error: list friction fingerprints recurring N>=2 (promotion threshold)")
    gq.add_argument("--extension", action="store_true",
                    help="with --type spec (SPEC-0101 rule 1, T-9488): list ONLY the extension marker-bearing specs, each annotated with its adoptability state (adoptable|internal-only); unmarked specs absent")
    gq.add_argument("--as-of", dest="as_of", metavar="COMMIT|DATE",
                    help="reconstruct the graph as of a past commit-ish or ISO date (reads that commit's committed graph/index.json; legacy index.yaml for pre-switch history) — point-in-time rule-set, per D-0046")
    gq.add_argument("--projected", "--diff", dest="projected", action="store_true",
                    help="«what-will-be» spec projection (active − superseded-by-proposed + proposed) with structural flags — pure f(graph), per D-0047 B4. Composes only with --as-of.")
    gq.add_argument("--include-draft", dest="include_draft", metavar="PLAN-SLUG",
                    help="with --projected: ALSO include that plan's draft specs (plan-local what-if, T-0186). Default excludes all drafts.")
    gq.add_argument("--carve-out", dest="carve_out", action="store_true",
                    help="read-only parallel-dispatch carve-out selection (SPEC-0044, T-0425): requires-ordered chains + singletons + waits (with release predicates) + a P7 clash report, computed from the projection + git worktree list + the ready set. Pure f(graph, queue, worktree-list). Mutually exclusive with --type / --recurring / id / --as-of (strictly current-state — it reads the live worktree frontier).")
    gq.add_argument("--kernel", action="store_true",
                    help="kernel-prefixed (realm-explicit) retrieval (SPEC-0092; T-9363 specs, T-10748 errors): force the KERNEL node + body for this SPEC or E id even when a -C consumer owns the same id (the X-0038 / X-0583 kernel/consumer collision). Composes ONLY with a spec-id or error-id point-lookup. Use when reading a handbook retrieved-tier pointer or a kernel-authored `cites: E-XXXX` under -C.")
    gq.add_argument("--since", dest="since", metavar="ISO-DATE|TS",
                    help="window start (inclusive) for a windowed view-lens (trend-report, T-0396; discipline-ratio + outcome-ratio, T-10361) — ISO date or timestamp, UTC-normalized; ignored by non-windowed lenses")
    gq.add_argument("--until", dest="until", metavar="ISO-DATE|TS",
                    help="window end (exclusive) for a windowed view-lens (trend-report, T-0396; discipline-ratio + outcome-ratio, T-10361) — ISO date or timestamp, UTC-normalized; ignored by non-windowed lenses")
    gq.set_defaults(func=cmd_graph_query, cli_invoked_verb="graph query", read_only_admit=RO_READ)  # T-0113 observability

    # T-0068 (D-0035): error/friction case-file verbs. file=open a case (NOT promotion);
    # promote=forced file-or-waive resolution. All four auto-sync the journal by default (D-0049).
    error = sub.add_parser("error", help="Error/friction case files (errors/E-XXXX.yaml, per D-0035)")
    error_sub = error.add_subparsers(dest="error_action", required=True)
    ef = error_sub.add_parser("file", help="Open a case file (records the synthesis; NOT the promotion)")
    ef.add_argument("--title", required=True, help="one-line: what deviated (intent vs actual)")
    ef.add_argument("--kind", required=True, help="defect|friction|improvement")
    ef.add_argument("--severity", help="low|medium|high (default medium)")
    ef.add_argument("--fingerprint", help="stable dedup/recurrence key")
    ef.add_argument("--relates-to", dest="relates_to", help="CHARTER failure-class id and/or aspect")
    ef.add_argument("--ref", action="append",
                    help="evidence anchor (repeatable): events.jsonl#ts=... | decisions/... | git-sha")
    ef.set_defaults(func=cmd_error_file)
    el = error_sub.add_parser("list", help="List case files (filter --status / --kind)")
    el.add_argument("--status", help="open|investigating|resolved|reopened|waived (SPEC-0056 §4 FSM)")
    el.add_argument("--kind", help="defect|friction|improvement")
    el.set_defaults(func=cmd_error_list, cli_invoked_verb="error list", read_only_admit=RO_READ)  # T-0113 observability
    es = error_sub.add_parser("show", help="Print a case file")
    es.add_argument("id", help="E-XXXX")
    es.set_defaults(func=cmd_error_show, cli_invoked_verb="error show", read_only_admit=RO_READ)  # T-0113 observability
    ep = error_sub.add_parser("promote", help="Forced file-or-waive resolution (D-0035 §PROMOTE)")
    ep.add_argument("id", help="E-XXXX")
    ep.add_argument("--to-task", dest="to_task", action="store_true",
                    help="spawn a fix task (owner/due OPTIONAL for solo — T-0460)")
    ep.add_argument("--existing-task", dest="existing_task", metavar="T-XXXX",
                    help="(--to-task only) LINK this already-filed card as the fix task instead of "
                         "filing a new one (SPEC-0056, T-12844)")
    ep.add_argument("--owner", help="fix-task owner (OPTIONAL — recorded if given; SPEC-0056 §4 solo)")
    ep.add_argument("--due", help="fix-task due date YYYY-MM-DD (OPTIONAL — recorded if given)")
    ep.add_argument("--waive", action="store_true", help="waive instead (requires --reason)")
    ep.add_argument("--reason", help="waiver reason (required with --waive)")
    ep.add_argument("--prevention", help="root-fix / preventive measure recorded on resolve|waive (SPEC-0056 §2)")
    ep.add_argument("--by-design-residual", dest="by_design_residual", action="store_true",
                    help="(--waive only) this waive EXPECTS its residual to keep recurring — a later "
                         "capture SURFACES (error_residual_recurrence) instead of reopening the case "
                         "(SPEC-0056 §4, T-10924)")
    ep.set_defaults(func=cmd_error_promote)
    er = error_sub.add_parser("resolve",
                              help="Mark an in-flight case resolved AFTER its root-fix landed (SPEC-0056 §4) — journals error_resolved")
    er.add_argument("id", help="E-XXXX")
    er.add_argument("--prevention", help="root-fix / preventive measure that stops recurrence (SPEC-0056 §2)")
    er.add_argument("--root-fix", dest="root_fix",
                    help="attest a LANDED root-fix carried by a NON-fix_task (a plan slug / spec / verb "
                         "change) — resolves an open/investigating/reopened case with no promoted "
                         "fix-task; REQUIRES --prevention (SPEC-0056 §4, T-9746)")
    er.set_defaults(func=cmd_error_resolve)

    # cross coordination verbs (SPEC-0085/0086) — the shared kernel-owned coordination log. `archive`
    # (rule 1) is DEFERRED to a follow-up plan; the other 8 ship here. These verbs auto-sync like every
    # non-excluded verb (D-0049 default-on; only `journal sync` + `land` opt out) — the coordination
    # WRITE rides cross_emit→CROSS_LOG_PATH, orthogonal to the session-log→events.jsonl auto-sync.
    cfgp = sub.add_parser("config", help="Machine-scoped settings (T-11967): get/set/list the "
                                        "PERFORMANCE-class tunables of THIS machine. Gate-class "
                                        "values are refused — changing one is a task.")
    cfg_sub = cfgp.add_subparsers(dest="config_action", required=True)

    cfgl = cfg_sub.add_parser("list", help="every knob with its class + effective value (read-only)")
    cfgl.set_defaults(func=cmd_config_list, cli_invoked_verb="config list", read_only_admit=RO_READ)
    cfgg = cfg_sub.add_parser("get", help="the effective value of one knob (read-only)")
    cfgg.add_argument("key", help="knob name (see `config list`)")
    cfgg.set_defaults(func=cmd_config_get, cli_invoked_verb="config get", read_only_admit=RO_READ)
    cfgs = cfg_sub.add_parser("set", help="set a PERFORMANCE-class knob in the machine settings file; "
                                          "a GATE-class key is REFUSED (no bypass flag exists)")
    cfgs.add_argument("key", help="knob name (see `config list`)")
    cfgs.add_argument("value", help="the new value — type/range validated against the inventory")
    cfgs.set_defaults(func=cmd_config_set)

    # The verify venue (SPEC-0203 rule 6, T-12197) — placed beside `config`, the analog it copies:
    # a thin argparse+journal residue over `lib/venue.py`, with NO worktree gate, because the venue
    # record lives OUTSIDE every checkout exactly as the machine settings file does.
    vnp = sub.add_parser("venue", help="The remote verify venue (SPEC-0203): raise the box from the "
                                       "seed snapshot, publish it as this machine's verify venue, "
                                       "unpublish (break-glass), delete, show.")
    vn_sub = vnp.add_subparsers(dest="venue_action", required=True)

    vnr = vn_sub.add_parser("raise", help="create the box from the seed SNAPSHOT, wait for it and run "
                                          "the readiness probe (tears the box down on a refusal — a "
                                          "started hour is billed whole). Writes NO record.")
    vnr.add_argument("--from-image", default=None,
                     help="the SEED SNAPSHOT id (rule 3: a bare image is for seeding only, never a "
                          "pass). OPTIONAL since T-12668: absent, the raise reads the recorded "
                          "canonical seed (`venue seed`) and REFUSES when none is recorded; given, "
                          "it WINS over the record (verify a NEW snapshot before promoting it)")
    vnr.add_argument("--name", default="yitc-venue", help="provider server name")
    vnr.add_argument("--task", help="the card this raise acts under (ties the external_action row)")
    vnr.add_argument("--ready-timeout", type=float, default=None,
                     help="bounded-wait ceiling in seconds for raise->ready (default: the measured band)")
    vnr.add_argument("--keep-box", action="store_true",
                     help="do NOT tear the box down on a refusal (you then own the bill)")
    vnr.set_defaults(func=cmd_venue_raise, cli_invoked_verb="venue raise")

    vnseed = vn_sub.add_parser("seed", help="the canonical seed-snapshot record `venue raise` defaults "
                                            "to: `--snapshot-id ID` RECORDS it (the record's only "
                                            "writer — promotion is explicit); bare, SHOWS it or "
                                            "states its absence (read-only)")
    vnseed.add_argument("--snapshot-id", default=None,
                        help="the snapshot id to record as canonical (a raise from it verified)")
    vnseed.add_argument("--candidate", default=None,
                        help="record an UNVERIFIED new snapshot (the teardown refresh leg's image) as "
                             "the seed CANDIDATE: the next bare `venue raise` raises from it and "
                             "promotes it to canonical on a GREEN readiness probe (T-12885)")
    vnseed.add_argument("--main-sha", default=None,
                        help="the clone's main sha the snapshot carries (provenance, optional)")
    vnseed.add_argument("--note", default=None, help="one line of provenance (optional)")
    vnseed.add_argument("--task", help="the card this promotion acts under")
    vnseed.set_defaults(func=cmd_venue_seed, cli_invoked_verb="venue seed")

    vnpub = vn_sub.add_parser("publish", help="write the venue record after re-measuring the live box; "
                                              "REFUSED when the readiness probe fails")
    vnpub.add_argument("--box", required=True, help="the box address (ipv4)")
    vnpub.add_argument("--server-id", required=True, help="the provider server id")
    vnpub.add_argument("--snapshot-id", required=True, help="the seed snapshot it was raised from")
    vnpub.add_argument("--checkout-root", default=None, help="box-side checkout root (default: the venue dir)")
    vnpub.add_argument("--task", help="the card this publish acts under")
    vnpub.set_defaults(func=cmd_venue_publish, cli_invoked_verb="venue publish")

    vnu = vn_sub.add_parser("unpublish", help="remove the record (the explicit break-glass of rule 7, "
                                              "and the first step of every delete)")
    vnu.add_argument("--reason", required=True, help="why the venue is being withdrawn (journaled)")
    vnu.add_argument("--task", help="the card this unpublish acts under")
    vnu.set_defaults(func=cmd_venue_unpublish, cli_invoked_verb="venue unpublish")

    vnd = vn_sub.add_parser("delete", help="unpublish the record, then DESTROY the box (rule 6 order)")
    vnd.add_argument("--server-id", default=None,
                     help="the provider server id — required only when no record names one")
    vnd.add_argument("--reason", default=None, help="why (journaled on the unpublish step)")
    vnd.add_argument("--task", help="the card this delete acts under")
    vnd.set_defaults(func=cmd_venue_delete, cli_invoked_verb="venue delete")

    vns = vn_sub.add_parser("show", help="print the published venue record, or state its absence (read-only)")
    vns.set_defaults(func=cmd_venue_show, cli_invoked_verb="venue show", read_only_admit=RO_READ)

    crossp = sub.add_parser("cross", help="Cross-project coordination log (SPEC-0085/0086): "
                                          "request/inbox/outbox/show/pick/done/reject/close/ack")
    cross_sub = crossp.add_subparsers(dest="cross_action", required=True)

    cr = cross_sub.add_parser("request", help="File a coordination item (allocates the immutable id; "
                                              "emits cross_requested). The AUTHOR verb.")
    # T-10719 (E-0054): the three field flags are no longer argparse-`required` — a `--from-stdin`
    # filing supplies them in the stdin mapping instead. The fail-closed check is UNCHANGED in
    # strength, only relocated: `cmd_cross_request` already dies on a missing/empty --to, an
    # out-of-enum --kind and an empty --brief, and that ONE handler now serves both input modes.
    cr.add_argument("--to", help="receiver peer (project id) — must not be self")
    cr.add_argument("--kind", help=f"one of {list(cross.CROSS_KINDS)} "
                                   "(note=one-way info; task/bugfix=two-party w/ verify)")
    cr.add_argument("--brief",
                    help="one-line what (prose with backticks? send this field via --from-stdin — argv "
                         "rides the shell, which substitutes `...` before cross request runs, and the "
                         "damaged brief is PUBLISHED to the peer; T-10719 / E-0054)")
    cr.add_argument("--origin-fp", dest="origin_fp", help="the originating deviation fingerprint — a "
                                                          "provenance LINK, never the join key. REQUIRED "
                                                          "for --kind bugfix (SPEC-0085 §3); optional otherwise")
    cr.add_argument("--origin-ref", dest="origin_ref",
                    help="originating events.jsonl SOURCE ref (e.g. <consumer>/events.jsonl#<id>) — "
                         "REQUIRED for --kind bugfix; carried verbatim into the kernel intake mirror's "
                         "`mirrored_from` (SPEC-0085 rule 6)")
    # T-11747 (X-1152, <project>): the AUTHOR-side card link. A card declares INBOUND coordination via
    # `task file --resolves-cross`, but a request filed IN SERVICE OF a card had no equivalent — the
    # item carried no task at all, so the audit packet of the very card whose acceptance required it
    # rendered nothing. Written here, at the one moment both ids are in hand, rather than back onto
    # the card: the acceptance-text tie cannot work for an outbound item even in principle, because
    # the item's id does not exist when the acceptance is written.
    cr.add_argument("--task", help="the T-NNNN card this request is filed IN SERVICE OF (T-11747) — "
                                   "recorded as birth meta on cross_requested, so the item is folded "
                                   "into THAT card's audit-post evidence section. Optional; a request "
                                   "that serves no card simply omits it")
    cr.add_argument("--force", action="store_true",
                    help="override the known-participant fail-closed check (T-9587) — file to a "
                         "genuinely-new not-yet-registered peer whose checkout basename is not in the "
                         "registry or the shared log yet")
    cr.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the request fields as a YAML mapping from stdin (keys: to, kind, brief, "
                         "origin_fp, origin_ref, task) — the SHELL-PROOF path for a brief carrying backticks, "
                         "since stdin never rides the shell. Carries the WHOLE field set: combining it "
                         "with a content flag (--brief / --to / --kind / --origin-* / --task) is REFUSED "
                         "(T-10719, mirroring task file's T-10437) — put the field in the stdin mapping "
                         "instead")
    cr.set_defaults(func=cmd_cross_request, read_only_refuse="appends the shared coordination store")

    ci = cross_sub.add_parser("inbox", help="Non-terminal items addressed to:me (fold-derived, read-only)")
    ci.set_defaults(func=cmd_cross_inbox, cli_invoked_verb="cross inbox", read_only_admit=RO_READ)
    co = cross_sub.add_parser("outbox", help="Non-terminal items from:me awaiting my action (read-only)")
    co.set_defaults(func=cmd_cross_outbox, cli_invoked_verb="cross outbox", read_only_admit=RO_READ)
    cid = cross_sub.add_parser("intake-draft", help="Render this project's pending kernel-bound captures "
                                                    "as ONE public-intake issue draft (SPEC-0197 fields; "
                                                    "read-only, NOT sent — T-12950)")
    cid.set_defaults(func=cmd_cross_intake_draft, cli_invoked_verb="cross intake-draft", read_only_admit=RO_READ)
    csh = cross_sub.add_parser("show", help="Inspect ONE item: event chain, linked task, resolution "
                                            "note (read-only; fails closed on an unknown id)")
    csh.add_argument("id", help="X-NNNN coordination id")
    csh.set_defaults(func=cmd_cross_show, cli_invoked_verb="cross show", read_only_admit=RO_READ)

    cpk = cross_sub.add_parser("pick", help="RECEIVER accepts a task/bugfix (emits cross_picked)")
    cpk.add_argument("id", help="X-NNNN coordination id")
    cpk.add_argument("--force", action="store_true",
                     help="override the T-9362 intake-staleness REFUSAL (a DONE local task already "
                          "resolves this item); use when re-picking a legitimately reopened item")
    cpk.set_defaults(func=cmd_cross_pick)
    cdn = cross_sub.add_parser("done", help="RECEIVER finishes (emits cross_done; may carry --task/--note)")
    cdn.add_argument("id", help="X-NNNN coordination id")
    cdn.add_argument("--task", help="OPTIONAL receiver-side T-NNNN that did the work")
    cdn.add_argument("--note", help="what you actually did — recorded on cross_done, shown by `cross show` "
                                    "as the resolution note (optional; pass it when the outcome DIVERGES "
                                    "from the request, so the author need not re-file the ask) "
                                    f"({_PROSE_STEER_FOR('cross done')})")
    # T-12690 (E-0054, X-1452): the shell-proof route on every prose-publishing verb of the family.
    cdn.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the done PROSE as a YAML mapping on stdin (note) — the SHELL-PROOF path "
                          "(mirrors `cross close --from-stdin`); an argv --note alongside it is REFUSED. "
                          "The X-NNNN id and --task stay on argv")
    cdn.set_defaults(func=cmd_cross_done)
    crj = cross_sub.add_parser("reject", help="RECEIVER declines with reason (terminal; emits cross_rejected)")
    crj.add_argument("id", help="X-NNNN coordination id")
    # T-12690 (E-0054): `required=True` REMOVED — the reason may arrive in the --from-stdin mapping;
    # the verb already dies on an empty reason, on both routes.
    crj.add_argument("--reason", help=f"why declined ({_PROSE_STEER_FOR('cross reject')})")
    crj.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the reject PROSE as a YAML mapping on stdin (reason / re_entry / "
                          "re_entry_awaits / no_re_entry) — the SHELL-PROOF path (mirrors `cross close "
                          "--from-stdin`); an argv content flag alongside it is REFUSED. The X-NNNN id "
                          "stays on argv")
    # T-11180 — the SAME conditional-decline disposition the author's `close` carries, on the
    # RECEIVER's terminal. On a reject the author never gets a close to be gated at, so the condition
    # is captured HERE or nowhere; the waiter lands in YOUR (the receiver's) debt echo — see
    # `bin/lib/cross.py#_re_entry_disposition` for why that party and not the author's.
    crj.add_argument("--re-entry", dest="re_entry",
                     help="the re-entry condition this reject leaves behind, IN YOUR WORDS — arms a "
                          "followup waiter carrying it, so it returns to YOUR debt echo instead of "
                          "dying as prose in a terminal item (SPEC-0095). Never parsed from your reason")
    crj.add_argument("--re-entry-awaits", dest="re_entry_awaits",
                     help="OPTIONAL with --re-entry: the local artifact (T-NNNN) whose closure IS the "
                          "condition arriving — the SOLE fire key. Omit it for a condition about the "
                          "OTHER party's repo state: the waiter then stays visible but cannot auto-fire")
    crj.add_argument("--no-re-entry", dest="no_re_entry",
                     help="record that this reject leaves NOTHING to come back on, and why — the "
                          "explicit alternative to --re-entry (rides the terminal event's "
                          "re_entry_dismissed key)")
    crj.set_defaults(func=cmd_cross_reject)
    cdp = cross_sub.add_parser("dispute", help="AUTHOR records that a peer-declared `done` fix does "
                                               "NOT reach the case (done -> back to picked, carrying "
                                               "the disproof; emits cross_disputed). `cross close` "
                                               "still means VERIFIED — use this instead of closing "
                                               "one that is not fixed")
    cdp.add_argument("id", help="X-NNNN coordination id")
    # T-12690 (E-0054, X-1452 / X-1453): `required=True` REMOVED — the reason may arrive in the
    # --from-stdin mapping; the verb already dies on an empty reason, on both routes. This is the verb
    # the incident hit: four locating identifiers in backticks eaten by the shell, published immutably.
    cdp.add_argument("--reason",
                     help="the disproof — WHAT you verified and how the fix still fails the case "
                          f"({_PROSE_STEER_FOR('cross dispute')})")
    cdp.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the dispute PROSE as a YAML mapping on stdin (reason) — the SHELL-PROOF "
                          "path (mirrors `cross close --from-stdin`); an argv --reason alongside it is "
                          "REFUSED. The X-NNNN id stays on argv")
    cdp.set_defaults(func=cmd_cross_dispute)
    cak = cross_sub.add_parser("ack", help="RECEIVER acknowledges a note (terminal; emits cross_acked)")
    cak.add_argument("id", help="X-NNNN coordination id")
    cak.add_argument("--note", help="your substantive RETURN on this note — recorded on cross_acked, "
                                    "shown by `cross show` as the resolution note (optional on the "
                                    "first ack; REQUIRED when re-acking an already-acked item, which "
                                    "is a note-attach)")
    # T-11180 — the SAME conditional-decline disposition the author's `close` carries, on the
    # RECEIVER's terminal. On a ack the author never gets a close to be gated at, so the condition
    # is captured HERE or nowhere; the waiter lands in YOUR (the receiver's) debt echo — see
    # `bin/lib/cross.py#_re_entry_disposition` for why that party and not the author's.
    cak.add_argument("--re-entry", dest="re_entry",
                     help="the re-entry condition this ack leaves behind, IN YOUR WORDS — arms a "
                          "followup waiter carrying it, so it returns to YOUR debt echo instead of "
                          "dying as prose in a terminal item (SPEC-0095). Never parsed from your reason")
    cak.add_argument("--re-entry-awaits", dest="re_entry_awaits",
                     help="OPTIONAL with --re-entry: the local artifact (T-NNNN) whose closure IS the "
                          "condition arriving — the SOLE fire key. Omit it for a condition about the "
                          "OTHER party's repo state: the waiter then stays visible but cannot auto-fire")
    cak.add_argument("--no-re-entry", dest="no_re_entry",
                     help="record that this ack leaves NOTHING to come back on, and why — the "
                          "explicit alternative to --re-entry (rides the terminal event's "
                          "re_entry_dismissed key)")
    # T-12690 (E-0054, X-1452): the shell-proof route on every prose-publishing verb of the family.
    cak.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the ack PROSE as a YAML mapping on stdin (note / re_entry / "
                          "re_entry_awaits / no_re_entry) — the SHELL-PROOF path (mirrors `cross close "
                          "--from-stdin`); an argv content flag alongside it is REFUSED. The X-NNNN id "
                          "stays on argv")
    cak.set_defaults(func=cmd_cross_ack)
    ccl = cross_sub.add_parser("close", help="AUTHOR finalizes own item: cross_closed (work done+verified) "
                                             "OR --out-of-band (delivered outside the peer return path) "
                                             "OR --withdraw (retract; emits cross_withdrawn)")
    ccl.add_argument("id", help="X-NNNN coordination id")
    ccl.add_argument("--withdraw", action="store_true", help="retract a not-done item (requires --reason)")
    # T-12322 — the AUTHOR-side sibling of `cross done --task`. It stays on argv (not in the
    # --from-stdin mapping below): that channel carries the closure PROSE, and this is an id.
    ccl.add_argument("--task", help="YOUR OWN T-NNNN card — the one whose acceptance cites this item. "
                                    "Recorded as cross_closed.data.task, the field `task close "
                                    "--settle-evidence coordination.jsonl#cross=X-NNNN` resolves "
                                    "against, so the card that OWNS the item can settle its criterion "
                                    "(NOT `cross done --task`, which is the RECEIVER's card). On an "
                                    "item that is ALREADY closed, pass it ALONE: an idempotent naming "
                                    "amend that re-states whose card the item served and leaves the "
                                    "terminal state untouched")
    ccl.add_argument("--out-of-band", action="store_true", dest="out_of_band",
                     help="close an item whose substance was delivered OUTSIDE the peer return path "
                          "(no cross_done to wait for); requires --reason, which is recorded on the "
                          "cross_closed as the resolution note")
    ccl.add_argument("--reason", help="retract reason (required with --withdraw) / out-of-band close "
                                      "reason (required with --out-of-band) "
                                      f"({_PROSE_STEER_FOR('cross close')})")
    ccl.add_argument("--note", help="what you verified — recorded on cross_closed, shown by `cross show` "
                                    "as the resolution note (optional; not for --withdraw, which takes "
                                    f"--reason) ({_PROSE_STEER_FOR('cross close')})")
    # T-11582 (E-0054, X-1111): the shell-proof path its two siblings (`cross request` / `work commit`)
    # already carry. A close is TERMINAL — the recorded text can never be corrected — so this is the
    # one place the argv-only channel costs the most.
    ccl.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the closure PROSE as a YAML mapping on stdin (reason / note / "
                          "re_entry / re_entry_awaits / no_re_entry) — the SHELL-PROOF path (mirrors "
                          "`cross request --from-stdin`); an argv content flag alongside it is REFUSED. "
                          "The X-NNNN id and the mode flags (--withdraw / --out-of-band) stay on argv")
    # T-11116 — the conditional-decline disposition. When the item's resolution NAMES a re-entry
    # condition ("re-entry: ... when X"), the close REFUSES until one of these two is declared.
    ccl.add_argument("--re-entry", dest="re_entry",
                     help="the re-entry condition this closure leaves behind, IN YOUR WORDS — arms a "
                          "followup waiter carrying it, so it returns to YOUR debt echo instead of "
                          "dying as prose in a terminal item (SPEC-0095). Never parsed from the note")
    ccl.add_argument("--re-entry-awaits", dest="re_entry_awaits",
                     help="OPTIONAL with --re-entry: the local artifact (T-NNNN) whose closure IS the "
                          "condition arriving — the SOLE fire key. Omit it for a condition about a "
                          "PEER's repo state: the waiter then stays visible but cannot auto-fire")
    ccl.add_argument("--no-re-entry", dest="no_re_entry",
                     help="record that this closure leaves NOTHING to come back on, and why — the "
                          "explicit alternative to --re-entry (rides cross_closed.re_entry_dismissed)")
    ccl.set_defaults(func=cmd_cross_close)

    fup = sub.add_parser("followup", help="Followup capture (SPEC-0095): one-command no-worktree capture "
                                          "of a small follow-up; 2-state open->promoted|dropped, folded from the journal. "
                                          "An OPEN followup may carry a `trigger` ATTRIBUTE (arm/unarm) — an ARMED waiter "
                                          "leaves the actionable headline and returns when its trigger fires, i.e. when "
                                          "its AWAITED artifact (`--awaits`) closes — never when its `--relates-to` "
                                          "provenance ref closes")
    fup_sub = fup.add_subparsers(dest="followup_action", required=True)
    fadd = fup_sub.add_parser("add", help="Capture a followup in ONE command, NO worktree (emits followup_added)")
    # T-11244 (E-0054): --text is no longer argparse-`required` — a --from-stdin caller supplies it in
    # the mapping, and cmd_followup_add's own non-empty check enforces it from EITHER channel, so the
    # refusal for a missing text is unchanged in shape and wording (the `task refuse` precedent).
    fadd.add_argument("--text", help=f"one-line what (the follow-up) ({_PROSE_STEER_FOR('followup add')})")
    fadd.add_argument("--relates-to", dest="relates_to", help="OPTIONAL PROVENANCE ref — what this followup "
                                                              "is ABOUT (T-NNNN / fingerprint / file). NEVER a "
                                                              "fire key; use --awaits for that "
                                                              f"({_PROSE_STEER_FOR('followup add')})")
    fadd.add_argument("--trigger", help="capture it ARMED: the NAMED future moment it waits for "
                                        "(e.g. 'T-1234 closes'). An armed followup does not inflate the "
                                        "actionable debt headline. REQUIRES --awaits (T-11863) — omit BOTH "
                                        "to capture an ordinary actionable followup "
                                        f"({_PROSE_STEER_FOR('followup add')})")
    fadd.add_argument("--awaits", help="the AWAITED ARTIFACT whose closure fires this followup "
                                       "(e.g. T-1234) — the SOLE fire key. REQUIRED TOGETHER with --trigger, "
                                       "in both directions: a bare future event with no checkable artifact "
                                       "is captured ACTIONABLE (visible), never armed into silence "
                                       f"({_PROSE_STEER_FOR('followup add')})")
    fadd.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                      help="read the capture fields as a YAML mapping on stdin (text / relates_to / "
                           "trigger / awaits) — the SHELL-PROOF path for prose carrying backticks "
                           "(mirrors `task update --from-stdin`); any of those four on argv alongside "
                           "--from-stdin is REFUSED")
    fadd.set_defaults(func=cmd_followup_add)
    fpr = fup_sub.add_parser("promote", help="Promote an OPEN followup into a real task, authored reference note OR plan (emits followup_promoted)")
    fpr.add_argument("id", help="fu_XXXXXXXXXXXX followup id")
    fpr.add_argument("--into", help="REQUIRED carrier the followup became — a task id (T-NNNN), an "
                                    "AUTHORED REFERENCE NOTE (a repo-relative lessons/<name>.md or "
                                    "patterns/<name>.md, the lightest carrier SPEC-0140 names) or a "
                                    "PLAN slug (the plans/ or ideas/ draft that carries it). A note "
                                    "path or plan slug that does not resolve is REFUSED (promote is "
                                    "terminal)")
    fpr.set_defaults(func=cmd_followup_promote)
    fdr = fup_sub.add_parser("drop", help="Drop an OPEN followup (emits followup_dropped)")
    fdr.add_argument("id", help="fu_XXXXXXXXXXXX followup id")
    fdr.add_argument("--reason", help=f"OPTIONAL why dropped ({_PROSE_STEER_FOR('followup drop')})")
    fdr.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the drop reason as a YAML mapping on stdin (`reason: <text>`) — the "
                          "SHELL-PROOF path (mirrors `task update --from-stdin`); an argv --reason "
                          "alongside it is REFUSED. The `id` positional stays on argv")
    fdr.set_defaults(func=cmd_followup_drop)
    farm = fup_sub.add_parser("arm", help="Mark an OPEN followup as ARMED — awaiting a NAMED trigger, so it "
                                          "leaves the actionable headline (emits followup_armed). NOT a status "
                                          "change: it sets attributes; promote/drop still apply. Re-arming a "
                                          "wrongly-FIRED followup RETURNS it to armed with the real condition")
    farm.add_argument("id", help="fu_XXXXXXXXXXXX followup id")
    # T-11244 (E-0054): --trigger is no longer argparse-`required` for the same reason --text is not
    # (above) — cmd_followup_arm's own non-empty refusal is what enforces it, from EITHER channel.
    farm.add_argument("--trigger", help="REQUIRED the NAMED future moment awaited (non-empty) "
                                        f"({_PROSE_STEER_FOR('followup arm')})")
    farm.add_argument("--awaits", help="REQUIRED the AWAITED ARTIFACT whose closure fires this followup "
                                       "(e.g. T-1234) — the SOLE fire key, distinct from --relates-to "
                                       "provenance. An arm with no awaited artifact is unfireable AND out of "
                                       "the headline, so it is REFUSED (T-11863): leave such an item "
                                       "actionable, or `followup drop` it "
                                       f"({_PROSE_STEER_FOR('followup arm')})")
    farm.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                      help="read the awaited condition as a YAML mapping on stdin (trigger / awaits) — "
                           "the SHELL-PROOF path for a trigger phrase naming a verb or path in "
                           "backticks (mirrors `task update --from-stdin`); either flag on argv "
                           "alongside it is REFUSED. The `id` positional stays on argv")
    farm.set_defaults(func=cmd_followup_arm)
    funarm = fup_sub.add_parser("unarm", help="Clear an OPEN followup's trigger AND awaited artifact, returning "
                                              "it to the actionable headline (emits followup_armed with "
                                              "trigger:null, awaits:null). For a waiter whose trigger went MOOT")
    funarm.add_argument("id", help="fu_XXXXXXXXXXXX followup id")
    funarm.set_defaults(func=cmd_followup_unarm)
    fsh = fup_sub.add_parser("show", help="Read ONE followup by id (fold-derived, read-only) — the "
                                          "read-one counterpart of `list`, so resuming a handoff that "
                                          "names followups by id stops needing list-plus-grep. Fails "
                                          "closed on an unknown id; mutates nothing")
    fsh.add_argument("id", help="fu_XXXXXXXXXXXX followup id")
    fsh.set_defaults(func=cmd_followup_show, read_only_admit=RO_VIEW)
    fls = fup_sub.add_parser("list", help="List followups by status (fold-derived, read-only). The open lenses "
                                          "actionable|armed|fired are DERIVED views, not stored statuses")
    fls.add_argument("--status",
                     choices=["open", "actionable", "armed", "fired", "promoted", "dropped", "all"],
                     default="open",
                     help="filter (default open — prints the three-way partition: actionable · "
                          "armed-with-fired-trigger · armed-awaiting-trigger)")
    fls.set_defaults(func=cmd_followup_list, read_only_admit=RO_VIEW)

    journal = sub.add_parser("journal", help="Session-log journal sync (per D-0030 + SPEC-0004)")
    journal_sub = journal.add_subparsers(dest="journal_action", required=True)
    js = journal_sub.add_parser("sync", help="Materialize chat-class events from the session log")
    js.add_argument("--session-ref", dest="session_ref",
                    help="session id to sync (default = current, fail-closed resolved). "
                         "Use a prior session id for orphan-tail recovery.")
    js.set_defaults(func=cmd_journal_sync, no_autosync=True)   # EXCLUDED — this IS the sync (no recursion, D-0049)

    # T-12779 (SPEC-0163 rule 4c) — the governed route OUT for a branch-written journal row that
    # arms the any-author secrets floor. The journal is append-only, so this is the ONE verb that
    # rewrites a row, and it is bounded by construction: journal paths only, branch-written rows
    # only, `main` never rewritten, one journaled receipt per redaction.
    jr = journal_sub.add_parser("redact",
        help="Redact a credential-shaped token out of a JOURNAL row THIS BRANCH wrote, so a land "
             "the kernel-floor secrets atom refuses has a governed route out (SPEC-0163 rule 4c)")
    jr.add_argument("--ts", required=True,
                    help="the envelope `ts` of the offending journal ROW (the floor's refusal "
                         "prints it). A `ts` is NOT a unique row id: when more than one "
                         "branch-written row carries it the verb REFUSES and names each candidate — "
                         "pin it with --path / --line.")
    jr.add_argument("--atom", required=True,
                    help="the kernel-floor atom whose token(s) to redact. Only `secrets` names "
                         "token SHAPES; `dependencies` / `probes` are whole-file checks with "
                         "nothing in a row to redact, and are refused by name.")
    jr.add_argument("--path", dest="path",
                    help="OPTIONAL disambiguator — the repo-relative journal segment holding the "
                         "row (`events.jsonl` or `archive/events-*.jsonl`). A NON-journal path is "
                         "refused: this verb never touches a source file.")
    jr.add_argument("--line", dest="line", type=int,
                    help="OPTIONAL disambiguator — the 1-based line number within --path")
    jr.set_defaults(func=cmd_journal_redact, cli_invoked_verb="journal redact")

    jq = journal_sub.add_parser("query", help="Query events.jsonl (read-only; peer to `graph query`, per D-0039)")
    jq.add_argument("--type", help="filter by event type (exact match)")
    # T-11743 — REPEATABLE, the shape the sibling `dispatch --task` already uses. A plain (scalar)
    # binding made a repeated flag last-occurrence-wins, so a controller reading a fleet of three
    # workers with one command got a SILENT partial answer whose natural next move is a re-dispatch
    # onto live worktrees (the T-0351 double-claim). Every requested id is reported.
    jq.add_argument("--task", action="append",
                    help="filter by task_id (exact match). REPEATABLE: pass --task once per id — "
                         "with --dispatch-status each requested id gets its own section (an id with "
                         "no dispatch rows is NAMED as unanswerable, never silently omitted)")
    # T-13571 — the table prints `session_ref[:8]`, so the value a reader copies is a PREFIX.
    jq.add_argument("--session",
                    help="filter by envelope session_ref: a FULL ref (exact match), or a PREFIX of one "
                         "— e.g. the 8 characters the table prints. A prefix must name exactly ONE "
                         "ref; one shared by several is REFUSED with the full refs listed (never "
                         "their union). Both are judged on the journal segments THIS query reads "
                         "(its --since/--until/--task horizon), not the whole history — a ref with "
                         "no row there is read as a prefix")
    jq.add_argument("--grep", help="case-insensitive substring over the decoded event (cross-language safe)")
    jq.add_argument("--since", help="keep events with ts >= this ISO string")
    jq.add_argument("--until", help="keep events with ts <= this ISO string")
    jq.add_argument("--limit", type=int, default=50, help="keep the last N (tail) after ts-sort; <=0 = all (default 50)")
    jq.add_argument("--json", action="store_true", help="emit one JSON object per line (for piping)")
    jq.add_argument("--coordination", action="store_true",
                    help="read the SHARED coordination log (CROSS_LOG_PATH) instead of this repo's "
                         "events.jsonl, via the SAME parser — the one-parser/one-query read contract "
                         "(SPEC-0084 r4); no second reader path.")
    # Both helps RENDER the class vocabulary from the single journal.py carrier (T-10253) — never a
    # hand-restated list. `halted` is fleet-verdict-only; its own gloss says so, so one rendering
    # serves both surfaces without a per-surface subset to drift.
    jq.add_argument("--dispatch-status", dest="dispatch_status", action="store_true",
                    help="dispatch-status reader (T-0391, read-only): classify dispatched task(s) by "
                         "the dispatch CLASS vocabulary [" + _SELF._dispatch_class_vocab_prose() +
                         "], plus an ADVISORY "
                         "identity field (T-0559: clean | COLLAPSED | not-yet-started) for a "
                         "launcher-dispatched worker. With --task: ONE task. Without: the wave view "
                         "(seeded from boundary events; --since/--until bound the wave, default last "
                         "24h). Honors --json.")
    jq.add_argument("--fleet-verdict", dest="fleet_verdict", action="store_true",
                    help="fleet-verdict surface (SPEC-0133, §6-safe read-only): per IN-FLIGHT worker "
                         "(keyed on session_ref), emit session_ref + task_ids (drain sequence) + class "
                         "+ evidence (last journal ts/type, proc-alive, active child proc "
                         "auditor|test|land, worktree land-readiness) + verdict (alive|dead|"
                         "needs-decision) + verdict_basis, and NO recommended_action. The CLASS "
                         "vocabulary [" + _SELF._dispatch_class_vocab_prose() + "]. Discriminates a "
                         "warm-worker IDLE-between-lands (proc alive, task done) from a hung/dead one. "
                         "Pure current-state → report: no state/loop/mutate/re-invoke/kill/land/adopt. "
                         "--since/--until bound the window (default last 24h). Honors --json. "
                         "With --task (repeatable): ONLY the worker records whose task_ids include a "
                         "requested id (a warm worker's WHOLE record), and each requested id no "
                         "in-flight worker record holds is NAMED — --json: an object carrying "
                         "held_by_in_flight_worker=false; text: one line pointing at "
                         "--dispatch-status --task <id>. Without --task: the whole fleet.")
    jq.add_argument("--dispatch-readiness", dest="dispatch_readiness", action="store_true",
                    help="dispatch-readiness / wave-sizing ADVISOR (SPEC-0133 CARD-2, §6-safe "
                         "read-only): emit {headroom (nproc/loadavg/free_slots), live_worker_count "
                         "(EVERY live worker across ALL sessions task/+work/), recommended_wave_ceiling "
                         "(advisory), sole_controller, in_flight_land} from CURRENT host/proc/journal "
                         "state. A pure numbers report — NEVER a gate/cap/scheduler, performs NO "
                         "admission control (prints numbers you may ignore). --since/--until bound the "
                         "controller-detection window (default last 24h). Honors --json.")
    jq.add_argument("--dispatch-plan", dest="dispatch_plan", action="store_true",
                    help="dispatch-plan / Axis-B batch-planning ADVISOR (SPEC-0136, §6-safe read-only): "
                         "propose which ready cards pack into which warm workers, in what order, how wide, "
                         "WITHIN an owner-authorized batch, + a `next:` Handback of the judgement it cannot "
                         "make. CONSUMES `graph query --carve-out` (SPEC-0044) + `--dispatch-readiness` "
                         "(SPEC-0133) + the per-model warm cap (max_tasks_per_warm_worker, "
                         "bin/effort-routing-config.yaml). SCOPE (bucket 0, REQUIRED — a bare unscoped call "
                         "REFUSES): --plan <slug> (that plan's cut cards) | --tasks T-…,… (a named set) | "
                         "--whole-ready-queue (the EXPLICIT owner cue). PURE/stateless — proposes only, "
                         "NEVER launches/mutates/gates/auto-picks; you authorize the wave. The per-model "
                         "warm-cap constants are calibrated for the CURRENTLY-CONFIGURED worker model; a "
                         "different-window model must be re-calibrated in config (provider-neutral: brands/"
                         "numbers live in config, not here). Honors --json.")
    jq.add_argument("--plan", dest="plan", help="[--dispatch-plan scope] propose within this plan's cut cards (decomposed_from == slug)")
    jq.add_argument("--tasks", dest="tasks", help="[--dispatch-plan scope] propose within this comma/space-separated set of T-ids")
    jq.add_argument("--whole-ready-queue", dest="whole_ready_queue", action="store_true",
                    help="[--dispatch-plan scope] the EXPLICIT owner cue to propose over the WHOLE ready queue (SPEC-0136 §0)")
    jq.add_argument("--lifecycle-integrity", dest="lifecycle_integrity", action="store_true",
                    help="lifecycle-integrity report (T-9365, read-only, no gate): flag any DISPATCHED "
                         "worker that reached a land/close terminal WITHOUT its governed "
                         "worktree_created + task_picked + audit chain (the X-0044 bypass shape). "
                         "Three tiers (T-11021): BYPASS (claim evidence wholly absent, or a claim "
                         "marker missing with NO audit) / claim-gap (one claim marker absent but the "
                         "other AND the audit present) / advisory (audit only). "
                         "Judges the KERNEL locus AND each registry consumer journal separately "
                         "(T-11022 — a `-C` dispatch's events live in the CONSUMER journal, so a "
                         "kernel-only read was blind to them; loci are never merged, since task ids "
                         "are per-project). Each row names its locus; --json rows carry `project`. "
                         "Report-only backstop for the dispatch preamble; used in the QUEUE weekly "
                         "Re-review sweep. --since/--until bound the window (default ~8 days, matching "
                         "the weekly cadence — T-9367). Honors --json.")
    jq.set_defaults(func=cmd_journal_query, cli_invoked_verb="journal query", read_only_admit=RO_READ)   # D-0049: read-only but auto-syncs (default-on); T-0113 observability

    session = sub.add_parser("session", help="Session activation — journal markup + startup protocol (per D-0041)")
    session_sub = session.add_subparsers(dest="session_action", required=True)
    ss = session_sub.add_parser("start", help="Emit session_started + echo startup protocol (markup, NOT a gate)")
    ss.add_argument("--type", required=False, default=None, choices=["build"],
                    help="session type — OMIT for the interactive Controller (the default posture, "
                         "T-9698); `build` is the dispatched Worker's 9-stage flow (set by "
                         "`bin/yitc-v2 dispatch`). The Build|Review interactive type choice was "
                         "retired (T-9697 / CHARTER §6).")
    # T-13371: `cli_invoked_self` — the verb writes its OWN measured invocation record (the `cli:seed`
    # receipt, `cmd_session_start`), so `main` adds none; the read-contract tripwire reads the marker.
    ss.set_defaults(func=cmd_session_start, read_only_admit=RO_EVIDENCE,   # D-0049: auto-syncs (default-on)
                    cli_invoked_self="session start")
    # session context — the context-window utilization sensor (SPEC-0115 / T-9704). Read-only,
    # deterministic, PRINT-ONLY (no journal event — §8); NOT a gate. Optional positional transcript
    # (defaults to the current session's log).
    sc = session_sub.add_parser("context", help="Print this session's context-window occupancy + refresh verdict (SPEC-0115; read-only, print-only)")
    sc.add_argument("transcript", nargs="?", help="optional transcript .jsonl path (defaults to the current session's log)")
    sc.set_defaults(func=cmd_session_context, read_only_admit=RO_VIEW)
    # session pick — the project picker (T-12960, SPEC-0086 rule 6f). A read-only VIEW over the host
    # registry: lists the registered projects; on a choice it runs that project's own `session start`.
    # Deliberately NO cli_invoked marker — a list-only run writes nothing (zero-write view, cli.py).
    sp = session_sub.add_parser("pick", help="List the projects on this machine and start a session in the one you choose (read-only view over the host registry; SPEC-0086 rule 6f)")
    sp.add_argument("choice", nargs="?", help="the project's number or name; omit to see the list (asked once when interactive)")
    sp.set_defaults(func=cmd_session_pick)
    # session handoff — the per-project hand-off store (SPEC-1004 §4, T-13250). Writes only
    # `<git-common-dir>/yitc/handoffs/` (no worktree); refused in a dispatched-worker context.
    sh = session_sub.add_parser("handoff", help="Per-project session hand-off store: write (stdin body) / list / take / drop (SPEC-1004; interactive only)")
    sh_sub = sh.add_subparsers(dest="handoff_action", required=True)
    shw = sh_sub.add_parser(
        "write", help="save a hand-off (body on stdin) → H-<N>",
        description="Save a hand-off (body on stdin) → H-<N>. Write one ONLY on the owner's refresh cue "
                    "(«обновим сессию» / «refresh session»), or on the owner's go on a proposal you made at "
                    "a telemetry crossing (`session context`) — never on your own estimate. One hand-off per "
                    "trigger: while work continues in this session, do not re-write it; the owner's next "
                    "refresh cue replaces it (SPEC-1004 §1/§3/§6).")
    shw.add_argument("--title", required=True, help="one line, <=120 UTF-8 bytes, no credential")
    shw.set_defaults(func=cmd_session_handoff)
    shl = sh_sub.add_parser("list", help="open hand-offs: id, title, short author ref, age")
    shl.set_defaults(func=cmd_session_handoff)
    sht = sh_sub.add_parser("take", help="load a hand-off: print its body, then delete it")
    sht.add_argument("handoff_id", metavar="H-N")
    sht.set_defaults(func=cmd_session_handoff)
    shd = sh_sub.add_parser("drop", help="delete a hand-off without loading it")
    shd.add_argument("handoff_id", metavar="H-N")
    shd.set_defaults(func=cmd_session_handoff)

    # Plan/idea lifecycle verbs (per D-0034, renamed draft→plan by T-0114). Per D-0049 they
    # auto-sync the journal by default; they do NOT rebuild the graph.
    plan = sub.add_parser("plan", help="Planning-artifact lifecycle (plans/ + ideas/) per D-0034")
    plan_sub = plan.add_subparsers(dest="plan_action", required=True)

    df = plan_sub.add_parser("file", help="Create a plan (or an idea with --idea)")
    df.add_argument("--title", required=True, help="one-line title (→ slug id)")
    df.add_argument("--idea", action="store_true", help="file into ideas/ (flat, minimal frontmatter, no FSM)")
    df.add_argument("--source", help="idea provenance note (ignored for plans)")
    df.set_defaults(func=cmd_plan_file)

    # T-0601 (R7) — the DRAFT-stage check-carrier work-verb (SPEC-0059 §First-stage-check-carrier-gap;
    # plan-axis mirror of `task analyze --finalize`). The draft's END verb.
    ddr = plan_sub.add_parser("draft",
        help="Draft-stage check-carrier (T-0601): --finalize read-checks the draft bundle "
             "[SPEC-0043, SPEC-0034], reports front-load section-fill (advisory), and records the "
             "FRESH draft-worked-through proof that `plan stage specs` requires (non-skippable).")
    ddr.add_argument("slug", help="plan slug")
    ddr.add_argument("--finalize", action="store_true", help="finalize the draft (the draft-stage END verb)")
    ddr.set_defaults(func=cmd_plan_draft, cli_invoked_receipt="plan draft")  # T-13071: attempt receipt

    # T-0316 — the AUTHORITATIVE gated plan-lifecycle transition verb (mirrors `task stage`); it is the
    # SOLE writer of the plan FSM (the accept/close/reject compat shims were retired at T-0321).
    # One step along draft→specs→trial→accepted→decomposition→executing→postcheck→realized (+ terminals).
    dst = plan_sub.add_parser("stage",
        help="Advance a plan ONE stage along draft→specs→trial→accepted→decomposition→executing→postcheck→realized (+ terminals "
             "partial|rejected|cancelled): gates the prior stage, delivers the stage bundle, emits "
             "plan_stage_entered. `trial` (SPEC-0035) is owner-invoked for trial-eligible plans; `accepted` "
             "also accepts the `specs→accepted` skip for non-eligible plans. The SOLE writer of the plan "
             "FSM (accept/close/reject are realized via `accepted` / `realized|partial --into` / `rejected "
             "--reason`).")
    dst.add_argument("name", help="target stage — one of: draft, specs, trial, accepted, decomposition, executing, postcheck, realized (+ terminals partial, rejected, cancelled)")
    dst.add_argument("slug", help="plan slug")
    dst.add_argument("--into", action="append",
                     help="artifact ID(s) the plan became — required for realized|partial (comma or repeat)")
    dst.add_argument("--deferred", help="remainder plan slug (required for partial)")
    dst.add_argument("--reason", help="why abandoned (required for rejected|cancelled)")
    dst.add_argument("--despite-live-state", dest="despite_live_state", action="store_true",
                     help="T-12845 — cancel a plan that is still LIVE (in postcheck, or with an unresolved "
                          "retire-on-proof return trigger); without it `cancelled` refuses. Journaled on "
                          "plan_stage_entered as despite_live_state.")
    dst.add_argument("--note", help="optional closing note (realized|partial)")
    dst.add_argument("--by-record", dest="by_record", action="store_true",
                     help="T-9369 — realized-by-record terminal (SPEC-0034 §Realized-by-record): close a "
                          "trial/record plan whose prototype shipped+soaked+handed-off OUTSIDE its own "
                          "decomposition to `realized` from ANY active stage, bypassing the build-oriented "
                          "finalization gate (audit post --plan) — GATED on EXISTING soak-proof + handoff "
                          "evidence. Requires --into, --soak-evidence, --handoff. Retires the draft-blockquote workaround.")
    dst.add_argument("--soak-evidence", dest="soak_evidence",
                     help="T-9369 — ref to the EXISTING soak/real-data proof (journal ref / cross-task ID / "
                          "artifact); REQUIRED with --by-record (recorded in soak_evidence:).")
    dst.add_argument("--handoff",
                     help="T-9369 — ref to the EXISTING handoff (the productization that took the prototype "
                          "outside this plan's decomposition); REQUIRED with --by-record (recorded in handoff:).")
    dst.add_argument("--owner-reset", dest="owner_reset", action="store_true",
                     help="RETIRED (SPEC-0204 rule 6, plan-gate arm — T-12335): its basis was a "
                          "converged plan-gate consult, and that consult is retired with the episodes it "
                          "opened. Kept registered ONLY so a caller holding a pre-retirement brief meets "
                          "the replacement route instead of an unknown-flag error. Use `audit decide "
                          "--plan <slug> --gate <id>` per residual, then --on-decisions below.")
    # T-12335 (SPEC-0204 rule 3, plan-gate arm) — registered on THIS verb, beside the flag it replaces.
    # T-12927 — the RED clause states rule 9(f)'s plan-gate budget (`audit.PLAN_GATE_BUDGET`), not the
    # TASK arm's rule-4 terminal; the below-ceiling refusal is T-12928's.
    dst.add_argument("--on-decisions", dest="on_decisions", action="store_true",
                     help="Run the SPEC-0204 rule-3 pass at this stage's mandatory-blocking plan GATE: "
                          "ONE bounded audit pass PAST the 2-pass ceiling, governed by the "
                          "Controller's recorded `ceiling_decision` rows (`audit decide --plan <slug> "
                          "--gate <id>`). Below the ceiling (or at an advisory gate) REFUSED "
                          "`below-ceiling` / `ceiling-not-reached`. ADMITTED only when EVERY residual of "
                          "the gate's LATEST ceiling row carries a decision on that ceiling_ref AND the "
                          "plan body is the one revision those decisions name; otherwise REFUSED "
                          "`residual-undecided` / `decisions-not-for-this-revision` / "
                          "`evidence-revision-split`. Every refusal: no auditor invoked, no pass spent. "
                          "GREEN/YELLOW-absorbed → the gate passes and the FSM ADVANCES. The plan-gate "
                          "budget is decision-bounded (SPEC-0204 rule 9(f)): a RED here is the gate's NEW "
                          "ceiling row, and the next --on-decisions round is re-admitted once EVERY "
                          "residual of that row carries a fresh `ceiling_decision`. The plan's own FSM "
                          "terminals (rejected / cancelled / the partial split) stay available when the "
                          "Controller chooses not to decide another round. Not combinable with "
                          "--owner-reset.")
    dst.set_defaults(func=cmd_plan_stage, cli_invoked_receipt="plan stage")  # T-13071: attempt receipt

    dck = plan_sub.add_parser("check", help="Accept-gate verification (external audit; big-plan-checklist if large). Records verdict + content hash, no status change")
    dck.add_argument("slug")
    dck.add_argument("--full", action="store_true", help="no-op: `plan check` is a plan-lifecycle "
                     "audit and ALWAYS runs the full-capability auditor (SPEC-0034 §Audit posture); "
                     "flag kept for backward-compat")
    dck.add_argument("--focus", help="owner/session question block appended AFTER the stage template "
                     "(never replaces it); recorded VERBATIM in the saved verdict notes (SPEC-0036)")
    # T-11986 — mode-(b) absorption on the accept-gate verdict (SPEC-0034 §accept-gate / SPEC-0124
    # §Audit-loop ceiling): the plan-check-shaped spelling of the route that already exists as
    # `audit pre --plan <slug> --gate trial-accepted --absorb`, delegating to the SAME writer.
    # T-12734 — repeatable on this arm too, so the three registrations cannot disagree (AC3).
    dck.add_argument("--absorb", metavar="TEXT", action="append",
                     help="record a YELLOW residual INTO the existing accept-gate verdict "
                          "(absorbed:/notes:) instead of editing the plan body: runs NO auditor, leaves "
                          "verdict/content_hash/accept_freshness_hash byte-identical (so `plan stage "
                          "accepted` still accepts) and burns NO ceiling pass. Refuses a non-YELLOW "
                          "record and a body edited since the check — a body edit still forces a fresh "
                          "check (SPEC-0034 §accept-gate, T-11986). REPEATABLE: every occurrence is "
                          "recorded in order as its own entry (T-12734)")
    # T-13632 — the sweep statement beside --absorb, the same value `audit pre --absorb` takes.
    dck.add_argument("--sweep", metavar="TEXT",
                     help="(with --absorb) the ABSORPTION SWEEP statement — where you looked for the "
                          "same defect class and what you found (SPEC-0036 §Absorption sweep). Absent → "
                          "the record says `sweep: not stated` (T-13632)")
    dck.set_defaults(func=cmd_plan_check)

    dti = plan_sub.add_parser("to-idea", help="Move an active plan → ideas/ (out of the FSM)")
    dti.add_argument("slug")
    dti.set_defaults(func=cmd_plan_to_idea)

    dls = plan_sub.add_parser("list", help="List plans (default active: draft|accepted)")
    dls.add_argument("--status", action="append", choices=list(PLAN_STATUSES),
                     help="filter by status (repeatable)")
    dls.add_argument("--ideas", action="store_true", help="also list ideas/")
    dls.set_defaults(func=cmd_plan_list, cli_invoked_verb="plan list", read_only_admit=RO_READ)  # T-0113 observability

    # T-0682 — the read-only PLAN re-orientation surface (plan analog of the task resume-contract,
    # SPEC-0027). Pure VIEW; NO cli_invoked_verb marker on purpose — it must emit nothing of its own
    # (acceptance #1 «mutates nothing»: no cli_invoked append, no FSM write).
    dsh = plan_sub.add_parser("show",
        help="Read-only re-orientation for a plan (T-0682): current status + FSM position, the next "
             "stage + its entry-gate + the spec bundle bound to it, and (at decomposition) the cut "
             "task cards. A VIEW re-derived from existing state — mutates nothing.")
    dsh.add_argument("slug", help="plan (or idea) slug")
    dsh.set_defaults(func=cmd_plan_show)

    # T-1134 — scenario authoring verb-namespace (the analog of `spec new` / `plan file` + `plan show`
    # for the 7th graph node, the scenario doctrine SPEC-0076). `new` writes (worktree-gated); `list` /
    # `show` are read-only views over the in-memory graph build (current derived status, SPEC-0076 §3).
    scenario = sub.add_parser("scenario", help="Scenario authoring (scenarios/<slug>.md, the 7th graph node — SPEC-0076)")
    scenario_sub = scenario.add_subparsers(dest="scenario_action", required=True)

    scn = scenario_sub.add_parser("new", help="Scaffold scenarios/<slug>.md from the template + emit scenario_filed (the analog of `spec new` / `plan file`)")
    scn.add_argument("--title", required=True, help="one-line human title (→ slug id)")
    scn.add_argument("--actor", help="who walks this path (product: end-user role; v2-self: review-session|build-session)")
    scn.add_argument("--slug", help="explicit scenario id (kebab-case, <=50 chars, refused when taken); default: derived from --title, cut at a word boundary")
    scn.set_defaults(func=cmd_scenario_new)

    scl = scenario_sub.add_parser("list", help="List scenarios with their DERIVED status (SPEC-0076 §3); read-only")
    scl.add_argument("--status", action="append", choices=["draft", "building", "retired"],
                     help="filter by derived status (repeatable)")   # T-11004: `live` retired (SPEC-0076 §3)
    scl.set_defaults(func=cmd_scenario_list, cli_invoked_verb="scenario list", read_only_admit=RO_READ)  # read-view observability (parity with plan/error list)

    # Read-only re-orientation (analog of `plan show`, T-0682): NO cli_invoked_verb marker — mutates nothing.
    scs = scenario_sub.add_parser("show", help="Read-only re-orientation for a scenario: node + actor + derived status + cites/covers")
    scs.add_argument("slug", help="scenario slug (the frontmatter `scenario:` key)")
    scs.set_defaults(func=cmd_scenario_show)

    # T-10759 — grant-state reader verb-namespace (SPEC-0169 rule 6). READ-ONLY by construction: the
    # governed system validates + reports grant state and may NEVER write the carrier (rule 5 —
    # separation of duties; the write is an OWNER action). The carrier is an installation PARAMETER
    # (rule 10): default = REGISTRY_PATH ($YITC_REGISTRY else the server registry), `--carrier` points
    # a single run at a fixture with no code edit. `identity` (T-10760), `reach` (T-10762) and
    # `authorize` (T-10761) joined it as further READ-ONLY inspections under the same rule-5 bound —
    # `authorize` DECIDES and REPORTS, it performs no gated operation. The attributable trail
    # (T-10763), the policy switch that makes a gated verb call `authorize` (T-10765), and any grant
    # WRITE (never) are deliberately NOT here.
    grants_p = sub.add_parser("grants",
        help="Grant-state reader (SPEC-0169): READ-ONLY schema+semantic validation and reporting of "
             "collaborator grant state. Never writes the carrier — grant writes are an owner action (rule 5)")
    grants_sub = grants_p.add_subparsers(dest="grants_action", required=True)
    gr = grants_sub.add_parser("report",
        help="Validate + report live grant state read-only (exit 0 well-formed / 1 not well-formed / "
             "2 carrier unreadable); emits grant_state_reported")
    gr.add_argument("--carrier", help="grant-carrier path for THIS run (the rule-10 installation "
                                      "parameter; default $YITC_REGISTRY or the server registry) — "
                                      "point it at a fixture to validate that instead, no code edit")
    gr.add_argument("--json", action="store_true", help="emit the validation report as JSON")
    gr.set_defaults(func=cmd_grants_report, cli_invoked_verb="grants report", read_only_admit=RO_READ)  # read-view observability
    gi = grants_sub.add_parser("identity",
        help="Report the SERVER-ISSUED acting identity + its grants, read-only (SPEC-0169 rules 3-4, 6). "
             "Exit 0 proceed / 2 caller-supplied actor input refused / 3 identity refused / 4 grant-set "
             "refused; emits acting_identity_derived or acting_identity_refused")
    gi.add_argument("--carrier", help="grant-carrier path for THIS run (the rule-10 installation "
                                      "parameter; default $YITC_REGISTRY or the server registry)")
    gi.add_argument("--json", action="store_true", help="emit the identity report as JSON")
    gi.set_defaults(func=cmd_grants_identity, cli_invoked_verb="grants identity", read_only_admit=RO_READ)  # read-view observability

    ga = grants_sub.add_parser("authorize",
        help="Decide + report whether the SERVER-ISSUED acting identity holds a right on a project "
             "(SPEC-0169 rules 1-2, 4, 6-7). READ-ONLY — it decides and reports, performing no gated "
             "operation. Exit 0 permitted / 2 caller-supplied actor input refused / 3 identity "
             "refused / 4 grant-set refused / 5 NOT AUTHORIZED / 6 bad request (unknown --cause, "
             "or not exactly one of --right/--cause); emits authorization_decided or "
             "authorization_refused")
    ga.add_argument("--right",
                    help=f"which SEPARATELY-grantable right to decide (rule 2 closed set: "
                         f"{', '.join(grants.RIGHTS)}) — an unrecognised value is REFUSED, not "
                         f"passed through. Exactly one of --right / --cause per invocation; "
                         f"neither, or both, is REFUSED rather than guessed")
    ga.add_argument("--cause",
                    help=f"SPEC-0191 §5a — ask the DOCTRINE question instead: may this session "
                         f"DECIDE this AUTHORITY-class cause on this project? Closed vocabulary: "
                         f"{', '.join(grants.AUTHORITY_CLASS_CAUSES)}. Decided by "
                         f"{grants.DECISION_RIGHT!r} on that project; an unrecognised cause is "
                         f"REFUSED (exit 6), never admitted. Admission is AUTHORITY, not capability "
                         f"— it confers no execution (SPEC-0169 rule 2)")
    ga.add_argument("--project", required=True,
                    help="which project the right is claimed on (rule 1 — a grant names its project "
                         "explicitly; there is no all-projects default)")
    ga.add_argument("--carrier", help="grant-carrier path for THIS run (the rule-10 installation "
                                      "parameter; default $YITC_REGISTRY or the server registry) — "
                                      "point it at a fixture for a grant/revoke probe (rule 6)")
    ga.add_argument("--json", action="store_true", help="emit the decision as JSON")
    ga.set_defaults(func=cmd_grants_authorize, cli_invoked_verb="grants authorize", read_only_admit=RO_READ)  # read-view observability

    grc = grants_sub.add_parser("reach",
        help="Classify each actor's reach (enforcement / advisory-audit) from MEASURED host "
             "escalation capability and report any disagreement with what the carrier declares "
             "(SPEC-0169 rule 8; exit 0 no mismatch / 1 mismatch / 2 carrier unreadable); emits "
             "grant_reach_reported. Reports only — never enforces, never writes the carrier")
    grc.add_argument("--carrier", help="grant-carrier path for THIS run (the rule-10 installation "
                                       "parameter; default $YITC_REGISTRY or the server registry)")
    grc.add_argument("--json", action="store_true", help="emit the reach report as JSON")
    grc.set_defaults(func=cmd_grants_reach, cli_invoked_verb="grants reach", read_only_admit=RO_READ)  # read-view observability

    gt = grants_sub.add_parser("trail",
        help="Inspect the APPEND-ONLY attributable trail of right exercises and verify its integrity "
             "(SPEC-0169 rules 6 + 9; exit 0 clean / 1 tampering findings / 2 journal unreadable). "
             "The trail RIDES the existing journal — there is no second store. Delivers "
             "tamper-EVIDENCE against a named threat model, NEVER tamper-proofness")
    gt.add_argument("--verify", action="store_true",
                    help="the default action — recompute every record digest, resolve every back-link "
                         "and check every anchored prefix")
    gt.add_argument("--anchor", action="store_true",
                    help="journal an ANCHOR: the head digest of the trail, recorded as a "
                         "grant_trail_anchored OBSERVATION held OUTSIDE the trail it anchors (never a "
                         "trail record, never the grant carrier)")
    gt.add_argument("--json", action="store_true", help="emit the verification / anchor as JSON")
    gt.set_defaults(func=cmd_grants_trail, cli_invoked_verb="grants trail", read_only_admit=RO_READ)  # read-view observability

    ge = grants_sub.add_parser("exercise",
        help=f"EXERCISE the {grants.EXERCISABLE_HERE!r} right through the grant gate, leaving the "
             f"rule-9 record (SPEC-0169 rules 2 + 9). Restricted to that one right — the rule-2 right "
             f"defined as no writes and no production row touched; performing a GATED operation is the "
             f"policy switch (T-10765), not this surface. Exit 0 permitted+recorded / 2 caller-supplied "
             f"actor input refused / 3 identity refused / 4 grant-set refused / 5 NOT AUTHORIZED / "
             f"6 record unwritable so the exercise was REFUSED / 7 that right is not exercisable here")
    ge.add_argument("--project", required=True,
                    help="which project the right is exercised on (rule 1 — a grant names its project "
                         "explicitly; there is no all-projects default)")
    ge.add_argument("--right", default=grants.EXERCISABLE_HERE,
                    help=f"the right to exercise (only {grants.EXERCISABLE_HERE!r} is exercisable here)")
    ge.add_argument("--carrier", help="grant-carrier path for THIS run (the rule-10 installation "
                                      "parameter; default $YITC_REGISTRY or the server registry) — "
                                      "point it at a fixture for a probe (rule 6)")
    ge.add_argument("--json", action="store_true", help="emit the outcome as JSON")
    ge.set_defaults(func=cmd_grants_exercise, cli_invoked_verb="grants exercise")  # read-view observability

    # T-0063 — auto-ID allocation for decisions + specs (symmetry with `task file`).
    # auto-syncs by default (D-0049, like every non-excluded verb); no graph rebuild (indexed next build).
    decision = sub.add_parser("decision",
        help="Decision class — FROZEN history; authors/transitions nothing. `new` is RETIRED (author "
             "rules via `spec new`); the backlog ops accept/finalize/withdraw are RETIRED too (T-0564, "
             "backlog fully terminal). `new` (refuse-only) is the sole remaining subcommand. "
             "Per CHARTER §Decision lifecycle")
    decision_sub = decision.add_subparsers(dest="decision_action", required=True)
    dn = decision_sub.add_parser("new",
        help="RETIRED (Phase-1 cut) — author a NEW standing rule as a spec (`spec new`); decisions "
             "are frozen history. Invoking this refuses + points at the spec route.")
    dn.add_argument("--title", help="(ignored — `decision new` is retired; use `spec new`)")
    dn.add_argument("--type", choices=["Process", "Architectural", "Informational"],
                    help="decision type (default Process from template)")
    dn.add_argument("--from", dest="from_ref", help="durable-artifact ref for from: (CHARTER §Principle 2)")
    dn.set_defaults(func=cmd_decision_new)

    # T-10792 — the COVERING VERB for the escalation SPEC-0103 §3 + the dispatch preamble prescribe, in
    # the EXACT form they name: `blocked-on-land <task> <reason>`. Registered TOP-LEVEL (not under
    # `task`) because that literal form is what doctrine tells a blocked worker to return, and a worker
    # reaching for it must find it where it was told to. The reason is POSITIONAL (nargs=*) so the bare
    # doctrine form parses, with an equivalent --reason for callers that prefer a flag. Sibling of the
    # PRE-claim `task refuse`; emits the same existing bg_dispatch_halted marker, no new event family.
    bol = sub.add_parser("blocked-on-land",
                         help="Escalate a POST-claim block to the controller (SPEC-0103 §3): the worker "
                              "stopped rather than force a land, worktree left INTACT. Journal-only, no "
                              "worktree needed; emits bg_dispatch_halted(blocked_on_land) so "
                              "--fleet-verdict reads halted / needs-decision carrying YOUR reason "
                              "instead of a silent death (T-10792)")
    bol.add_argument("task", help="T-NNNN id you hold and cannot land (must be in-progress — a "
                                  "pre-claim refusal of a ready task is `task refuse`)")
    bol.add_argument("reason_words", nargs="*", metavar="reason",
                     help="WHY you are blocked, in the bare doctrine form `blocked-on-land T-XXXX "
                          "<reason>`: the out-of-scope file, environmental fault, or repeated-abort "
                          "cause. Carried VERBATIM into the fleet-verdict basis (prose with backticks? "
                          "send the reason via --from-stdin — argv rides the shell, T-11008/E-0054)")
    bol.add_argument("--reason", dest="reason_flag",
                     help="the same reason as a flag (equivalent to the positional form; if both are "
                          "given the flag wins). Prose with backticks? send it via --from-stdin — argv "
                          "rides the shell")
    # T-11008 (E-0054): the shell-proof route the sibling prose-bearing verbs already carry. An
    # escalation reason naturally names verbs/paths/commands in backticks, and argv hands those to the
    # shell first — <project> lost three fragments that way. Mirrors `task commit --from-stdin`.
    bol.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                     help="read the reason from a stdin YAML mapping (`reason: <text>`) instead of "
                          "argv — the shell-proof path for prose containing backticks (mirrors `task "
                          "commit --from-stdin`); an argv reason alongside it is REFUSED")
    bol.add_argument("--stage", default="land",
                     help="the stage you were blocked AT (default: land) — recorded for context only")
    bol.add_argument("--rung", type=int, choices=(1, 2, 3),
                     help="REQUIRED unless --unclassified (T-12468): the SPEC-0191 §5 rung this block "
                          "reached — 1 mechanical self-evidence, 2 external-auditor consult, 3 authority "
                          "dead-end. Written to the halt row as block_classification")
    bol.add_argument("--unclassified", action="store_true",
                     help="the explicit escape when no rung was climbed — journaled as "
                          "block_classification=unclassified, never a silent blank")
    bol.set_defaults(func=cmd_blocked_on_land)
    _absorb_trailing_reason_words(bol)

    land = sub.add_parser("land", help="Integrate a writing worktree's branch into main (D-0037 control-point)")
    land.add_argument("--no-tests", action="store_true",
                      help="OWNER-GATED (T-9306): skip the test-suite verification step (events/markers/"
                           "graph still checked). REFUSED unless BOTH --owner-authorized AND --no-tests-reason "
                           "are given — it is the owner-authorized emergency-bypass of the tests-green gate "
                           "(CHARTER §P2 / SPEC-0077 §2), NOT a free agent self-clear.")
    land.add_argument("--owner-authorized", action="store_true",
                      help="OWNER authorization marker REQUIRED with --no-tests (T-9306) — the explicit, "
                           "recorded 'the owner sanctioned skipping tests' assertion, modeled on the "
                           "CHARTER §P2 emergency marker. Pass only on owner authorization.")
    land.add_argument("--no-tests-reason",
                      help=f"REQUIRED with --no-tests (T-9306): the recorded justification (>="
                           f"{_NO_TESTS_MIN_REASON_CHARS} chars incl. the owner-directive context). Recorded "
                           f"on the land_completed event so every test-skip is surfaced + frequency-auditable.")
    land.add_argument("--rebaseline", action="store_true",
                      help="OWNER-ACKED graceful re-baseline (T-9307, SPEC-0077 §3): land an AUDITED "
                           "behaviour change whose CANDIDATE verify is GREEN but whose pinned LAST-GREEN "
                           "tests fail ON PURPOSE (the old behaviour they encode is the one you changed). "
                           "Unlike --no-tests it KEEPS the full candidate verify — only the superseded "
                           "old-behaviour pinned check is waived. Requires --rebaseline-reason + a "
                           "GREEN/YELLOW audit-post for THIS branch's task.")
    land.add_argument("--rebaseline-reason",
                      help=f"REQUIRED with --rebaseline (T-9307): the recorded justification (>="
                           f"{_NO_TESTS_MIN_REASON_CHARS} chars). Recorded on land_completed.rebaseline_reason.")
    land.add_argument("--rebaseline-kind", choices=vocab.REBASELINE_KINDS,
                      help="REQUIRED with --rebaseline (T-10898/T-12033, SPEC-0077 3a): DECLARE WHY the "
                           "pinned check is waived, over a CLOSED three-value vocabulary. `broken` = its "
                           "failure is REAL in this checkout (the superseded old-behaviour assertion your "
                           "change obsoletes, or a genuinely broken check). `unrunnable-here` = the check "
                           "is HEALTHY but cannot RUN here at all (its two-leg verify is unreachable in "
                           "this checkout) — waiving it says NOTHING about whether it would pass, and "
                           "does NOT make it runnable. `environmental` = the check is HEALTHY and "
                           "RUNNABLE here but failed under the FULL-run load (a load flake), so the "
                           "waive attributes the FULL-run failure to load rather than to the check. "
                           "Never inferred: a kindless --rebaseline is REFUSED rather than defaulted, "
                           "because a default would recreate the conflation the declaration removes. The "
                           "kind is RECORDED on land_completed.rebaseline_kind. "
                           "ELIGIBILITY — the honest difference, which is exactly ONE: `broken` and "
                           "`unrunnable-here` are pure LABELS read by no gate, widening nothing, with "
                           "every eligibility rule applying identically to both. `environmental` is NOT "
                           "a label — it selects a BINDING MODE, and it is the only value that changes "
                           "what a token may bind to. It buys a bind ONLY on a two-part conjunction, "
                           "fail-closed on each part: (i) the isolated preflight of EVERY named file "
                           "PASSES — one that FAILS isolated is `broken`, and refutes this kind for the "
                           "WHOLE declaration, granting no sibling token either — AND (ii) the key is "
                           "named by this branch\'s most recent RECORDED land abort (absent -> "
                           "no-match, never inferred). The waived file is STILL RUN in the full verify "
                           "and its result recorded on land_completed.waive_binding beside the binding\'s "
                           "prior-abort locator: the waive moves the VERDICT gate only, never what runs, "
                           "so a flake stays counted. Every OTHER eligibility rule — the A-prime "
                           "authority, the >=30-char --rebaseline-reason, the current-state audit-post, "
                           "and the per-assertion --rebaseline-waive coverage — applies identically to "
                           "all three values.")
    land.add_argument("--expect-rebaseline", action="store_true",
                      help="DECLARE, WITH NO WAIVE TOKEN AND NO PRIOR FAILURE, that this branch expects "
                           "to supersede a pinned last-green assertion — so this land is VERIFIED ALONE "
                           "this round instead of inside a batch (T-11801, SPEC-0184 rule 4). It exists "
                           "because --rebaseline conflates two separable things: the DECLARATION of that "
                           "intent (a batch-formation input) and the GRANT of a waive (which needs a "
                           "`KEY::ASSERTION` token only a live pinned failure produces). Reaching the "
                           "declaration only through the grant's door meant a branch had to REDDEN a "
                           "batch — costing every peer a shared verify pass — before it could learn the "
                           "token that would have kept it out of one. This flag is the declaration "
                           "alone. IT GRANTS NOTHING: the full candidate verify, the pinned last-green "
                           "suite, the --rebaseline-waive matcher and the audit-currency gate are all "
                           "untouched, and a pinned assertion that fails still REFUSES this land exactly "
                           "as today — you then read the token off your OWN solo refusal and re-land "
                           "with --rebaseline, having cost no peer anything. It is ATTEMPT-SCOPED, not a "
                           "quarantine: it rides this land\'s queue-wait heartbeat rows, so it expires "
                           "with the queue freshness window and a later land that omits it is batched "
                           "normally. Needs no --rebaseline-reason / --rebaseline-kind / "
                           "--rebaseline-waive; harmless (and redundant) alongside --rebaseline, which "
                           "already implies it.")
    land.add_argument("--merge-invalid-acceptance", action="store_true",
                      help="DECLARE that this branch carries an ACCEPTANCE ASSERTION THAT IS NOT VALID "
                           "INSIDE A MERGED TREE -- so this land is VERIFIED ALONE this round instead of "
                           "inside a batch (T-11939, SPEC-0184 rule 4). This is the declare->exclude->solo "
                           "chain's SECOND explicit ground, named by the external auditor 2026-08-28, and "
                           "it exists because the first one does not fit: a branch in this position "
                           "supersedes NO pinned assertion and has NOTHING to waive, so declaring "
                           "--rebaseline (or --expect-rebaseline) would be a FALSE STATEMENT -- in prose "
                           "and in two machine-readable places, the wait-row key and the exclusion reason. "
                           "The canonical shape (T-11760, the ground's first real instance): an acceptance "
                           "probe that lists the branch's own changed files against `main` (reaching "
                           "HEAD) and asserts a file set, "
                           "which inside a batch measures the PEERS' files and reddens the combined "
                           "candidate through no fault of this branch. "
                           "IT GRANTS NOTHING, and NOTHING about the rebaseline gate is relaxed by it: the "
                           "full candidate verify, the pinned last-green suite, the --rebaseline-waive "
                           "matcher and the audit-currency gate are all untouched; a branch that "
                           "supersedes a pinned assertion still needs its OWN --rebaseline declaration and "
                           "still fails closed without one, and this flag CANNOT substitute for it. It is "
                           "ATTEMPT-SCOPED, not a quarantine: it rides this land's queue-wait heartbeat "
                           "rows, so it expires with the queue freshness window and a later land that "
                           "omits it is batched normally. REQUIRES --merge-invalid-assertion.")
    land.add_argument("--merge-invalid-assertion", action="append", metavar="NAME",
                      help="REQUIRED with --merge-invalid-acceptance, REPEATABLE (T-11939): NAME each "
                           "acceptance assertion that is not valid inside a merged tree. A bare "
                           "declaration naming nothing is REFUSED at argument-parse time -- before the "
                           "reservation, before the queue read, with `main` untouched -- the same "
                           "fail-closed door T-11242 put on an empty --rebaseline-waive. The names are "
                           "RECORDED on the queue-wait rows and on "
                           "land_completed.merge_invalid_assertions, so a declaration is attributable "
                           "and frequency-auditable rather than quietly granted. Nothing INFERS this "
                           "ground from the diff: an inferred ground would be exactly the positional "
                           "guessing the retired red-batch culprit probe was removed for.")
    land.add_argument("--rebaseline-waive", action="append", metavar="KEY::ASSERTION",
                      help="REQUIRED with --rebaseline, REPEATABLE (T-10754, SPEC-0077 3a): DECLARE each "
                           "pinned last-green assertion the re-baseline waives. The ack is scoped to what "
                           "you name here — any failing pinned assertion NOT covered keeps the land "
                           "REFUSED, so an unrelated failure can no longer ride in on an authorization "
                           "given for a different check (T-10731). An assertion-BEARING failure needs the "
                           "QUALIFIED form `<key>::<substring of the surfaced assertion>`; the bare "
                           "`<key>` form is accepted only when the runner captured no assertion text "
                           "at all. `<key>` is the name the failing check is REPORTED under, which is "
                           "NOT always a test file (T-10794/T-11003): the kernel sweep keys on the test "
                           "FILE, while a consumer that DELEGATES tests/ to a declared verify layer keys "
                           "on the LAYER NAME. Read it off the refusal — it is exactly the text before "
                           "the first `: ` in that failure's FAILING ASSERTION(S) line, and exactly what "
                           "the tokens the refusal pastes use; paste those rather than composing your "
                           "own. A token that matches nothing, matches ambiguously, or is bare against "
                           "an assertion-bearing failure is REJECTED (fail-closed). "
                           "Recorded on land_completed.rebaseline_waived.")
    land.add_argument("--ack-repeated-abort", action="store_true",
                      help="T-0655: consciously continue past the repeated-abort convergence backstop "
                           "(structurally the land analog of audit --owner-reset) — use after resolving "
                           "the cause that aborted N× in a row, or to escalate. NOT OWNER-GATED (T-10788): "
                           "unlike --no-tests this flag demands no --owner-authorized, and the halt it "
                           "clears escalates to the CONTROLLER (SPEC-0103 §3), which is who decides here")
    land_tgt = land.add_mutually_exclusive_group()
    land_tgt.add_argument("--task", help="land THIS task's worktree (task/T-XXXX) — run from main so the "
                          "caller is never inside the removed dir (T-0131)")
    land_tgt.add_argument("--branch", help="land THIS branch's worktree (e.g. work/<slug>) — run from main (T-0131)")
    # T-12318 (U4 of the T-12243 split) — the withdrawal MODE. Registered OUTSIDE `land_tgt` on
    # purpose: that group is the TARGET vocabulary (`--task` xor `--branch`), and `--withdraw` is a
    # MODE that must COMPOSE with a target. Putting it inside the group would make the very form
    # this flag exists for — `land --withdraw --task T-XXXX` — an argparse mutual-exclusion error.
    land.add_argument("--withdraw", action="store_true",
                      help="WITHDRAW YOUR OWN QUEUED LAND instead of landing: record a withdrawal "
                           "request for the land attempt currently queued on the named branch, so "
                           "it withdraws itself at its admission seam without running its verify. "
                           "COMPOSES WITH A TARGET and requires one — `land --withdraw --task "
                           "T-XXXX` or `land --withdraw --branch work/<slug>`; a bare --withdraw is "
                           "refused, because a withdrawal must name what it withdraws. Proves the "
                           "branch worktree is YOURS before writing anything, and refuses rather "
                           "than acting on unproven state. NEVER LANDS and never prints a `LAND:` "
                           "token — a watcher keyed on that token must not read this as a land "
                           "verdict. THREE OUTCOMES, and the third is why the exit status matters: "
                           "exit 0 = CONFIRMED, or an idempotent nothing-to-withdraw; exit 1 = "
                           "REFUSED (nothing was done); exit 2 = REQUESTED BUT NOT YET CONFIRMED "
                           "(the request WAS written and cannot yet be proven consumed — re-run "
                           "this same command to resolve it). An ADMITTED land is never "
                           "interrupted.")
    land.set_defaults(func=cmd_land, no_autosync=True)   # EXCLUDED — land does its own events reconcile (D-0049). NO T-13071 attempt receipt: it would append into the worktree land just removed

    wt = sub.add_parser("worktree", help="Worktree creation control-point (D-0051) — inverse of land")
    wt_sub = wt.add_subparsers(dest="worktree_action", required=True)
    wn = wt_sub.add_parser("new", help="Create a writing worktree+branch off main; prints `cd <path>`")
    wn_grp = wn.add_mutually_exclusive_group(required=True)
    wn_grp.add_argument("--task", help=f"T-NNNN → branch task/T-NNNN + worktree ../{_worktree_parent_leaf()}/T-NNNN")
    wn_grp.add_argument("--work", help=f"slug → branch work/<slug> + worktree ../{_worktree_parent_leaf()}/<slug>")
    wn.add_argument("--spike", action="store_true",
                    help="DECLARE this `--work` batch a disposable SPIKE (T-11071, SPEC-0172 rule 5): "
                         "a throwaway exploration whose exit is the parked prototype ref spike/<slug> "
                         "that a later card names as its prototype (SPEC-0205), never landed code. Recorded on the worktree's own stamp, and `land` refuses a "
                         "worktree carrying it. This DECLARATION is the only thing that makes a batch a "
                         "spike — the `work/spike-` slug prefix no longer does (X-0857: it refused a "
                         "governed batch that was merely NAMED after the kernel's own `spike_sandbox` "
                         "ask). Invalid with --task.")
    wn.set_defaults(func=cmd_worktree_new, cli_invoked_receipt="worktree new")   # D-0049: auto-syncs (default-on); main dirt folded by land (T-0099)
    wa = wt_sub.add_parser("adopt",
                           help="Controller takeover of a CONFIRMED-DEAD holder's orphan worktree "
                                "(T-1117) — re-stamp + emit worktree_adopted (inverse of the hand "
                                "stamp edit), in the SAME two shapes as `worktree new` / `park`. "
                                "--task T-XXXX: a dead worker's task/T-XXXX worktree. --work <slug> "
                                "(T-11284): a work/<slug> filing batch left unstamped/foreign — "
                                "without it such a batch had NO governed way back in (2026-08-17). "
                                "Requires --confirm-dead (Confirmed-dead GATE asserted).")
    wa_grp = wa.add_mutually_exclusive_group(required=True)
    wa_grp.add_argument("--task", help="T-NNNN — the dead worker's orphan task/T-NNNN worktree to adopt")
    wa_grp.add_argument("--work", help="slug — the work/<slug> batch worktree to adopt (T-11284)")
    wa.add_argument("--confirm-dead", action="store_true",
                    help="ASSERT the §Abnormal Confirmed-dead GATE held (quiescent + no live "
                         "`--session-id` proc). REQUIRED — a foreign worktree is never auto-adopted (T-0362).")
    wa.set_defaults(func=cmd_worktree_adopt)
    wr = wt_sub.add_parser("recover-land",
                           help="GOVERNED, FAIL-CLOSED, IDEMPOTENT recovery of unlanded work, in TWO "
                                "shapes. --task T-XXXX: a CONFIRMED-DEAD worker's completed-but-UNLANDED "
                                "build (the closed_pending_land class — the T-10130 death: land lost to a "
                                "turn-yield); mechanizes the §Recovery-trigger dance (land-dead + "
                                "proc-dead gate → adopt → land) into ONE verb and re-verifies liveness "
                                "IN-CODE (fail-closed even on a mistaken assertion). --work <slug> "
                                "(T-11385): a work/<slug> batch branch ahead of main whose WORKTREE IS "
                                "GONE — the shape no other verb can take; restores the worktree via the "
                                "covering verb `worktree new --work`, then lands it. Both reuse the "
                                "existing `land` engine (with -C repo binding).")
    wr_grp = wr.add_mutually_exclusive_group(required=True)
    wr_grp.add_argument("--task", help="T-NNNN — the dead worker's closed_pending_land worktree")
    wr_grp.add_argument("--work", help="slug — a work/<slug> batch branch carrying commits main does "
                                       "not have, INCLUDING the case its worktree is GONE (T-11385): "
                                       "restores the worktree via `worktree new --work` (never raw "
                                       "git), then lands it with `land --branch`. The one shape no "
                                       "other verb can take — `land --branch` needs the worktree and "
                                       "`adopt --work` re-stamps one that still exists. A batch that "
                                       "STILL has its worktree is untouched and simply landed.")
    wr.add_argument("--confirm-dead", action="store_true",
                    help="OPTIONAL controller provenance assertion (recorded on worktree_adopted). The "
                         "in-code liveness gate — NOT this flag — is the enforcer, so it is not required.")
    wr.add_argument("--batch-residue", action="store_true",
                    help="T-11559 — the KILLED-LAND arm: return the branch named by --task/--work to "
                         "its PRE-BATCH tip after a land process was KILLED (a harness cap) rather "
                         "than gracefully ABORTED, leaving a half-formed SPEC-0184 batch — a peer's "
                         "content merged into this branch plus the land's bookkeeping. The graceful "
                         "ABORT path already undoes this from a `finally`; a kill runs no `finally`, "
                         "and until now the shipped detector's only remedy was raw git. IDEMPOTENT "
                         "(a second run is a no-op) and FAIL-CLOSED: the pre-batch tip is READ from "
                         "`land_batch_formed.member_tips` (T-11517), a PROVEN-live land refuses, a "
                         "merge no formation row attests is NEVER unwound, and an authored commit "
                         "above the tip refuses instead of being discarded. Composes with either "
                         "--task or --work — a batch head may be a work/<slug> branch.")
    wr.set_defaults(func=cmd_worktree_recover_land)
    wc = wt_sub.add_parser("clear-yield-offer",
                           help="GOVERNED, IDEMPOTENT, FAIL-CLOSED clearing of a STALE land-reservation "
                                "YIELD OFFER (T-12413, SPEC-0184 rule 9) — the verb the 2026-09-11 "
                                "14:50Z hand `mv` did not have. An offer names the branch a yielding "
                                "land handed the reservation to; only that branch's LIVE land may "
                                "consume it, so an offer naming a land that is gone — or one that "
                                "never started, the measured case — parks every land in the repo with "
                                "the reservation flock UNHELD until somebody removes the file. "
                                "REFUSED while the recorded addressee land pid is ALIVE (it will "
                                "consume the offer itself, and taking it away mid-handover destroys "
                                "the evidence the handover rests on); a no-op that records NOTHING "
                                "when there is no offer. Clears via journal append only — no worktree "
                                "needed (D-0049).")
    wc.add_argument("--reason", required=True,
                    help="REQUIRED — the recorded justification, journaled on yield_offer_cleared. It "
                         "is what a hand `mv` cannot leave behind: the next reader of a repo-wide "
                         "park needs to know WHO removed the offer and WHY, not just that it is gone.")
    wc.set_defaults(func=cmd_worktree_clear_yield_offer)
    ws = wt_sub.add_parser("sweep",
                           help="v2-NATIVE stale-worktree hygiene backstop (T-9532) — remove STALE "
                                "worktrees + leaked /tmp/yitc-pinned-{verify,engine}-* temp dirs "
                                "age+liveness-safely. NEVER the main checkout / a task/T-XXXX worktree / "
                                "a live/own/recent one. Host cron: `*/30 * * * * cd <repo> && "
                                "bin/yitc-v2 worktree sweep` (host territory, D-0019).")
    ws.add_argument("--dry-run", action="store_true",
                    help="list WOULD-remove + skip-reasons; act on NOTHING")
    ws.add_argument("--max-age-hours", type=float, default=24.0,
                    help="retention floor — never sweep anything younger (default 24). A HARD 1h minimum "
                         "is always enforced (a lower value is clamped UP to 1h) so an unstamped pinned "
                         "temp dir can never be swept while its land is still in-flight.")
    ws.set_defaults(func=cmd_worktree_sweep)
    wp = wt_sub.add_parser("park",
                           help="Gracefully TEAR DOWN a worktree+branch instead of leaving an orphan — the "
                                "inverse of `worktree new`, in the SAME two shapes. --task T-XXXX: by the "
                                "card's status on main — `ready` (T-9583, an auditor-OUTAGE block; REFUSED "
                                "when the worktree carries UN-LANDED work unless --force --reason, "
                                "T-11330) → the "
                                "task stays cleanly re-dispatchable; `wont-do` (T-10565, the card DIED under "
                                "the worker) → the claim is moot, so the worktree is DISCARDED; `done` "
                                "(T-11414, the LANDED-DONE retirement — claim, diff and closure all reached "
                                "main and the worktree holds nothing un-landed: clean, and 0 ahead or "
                                "(T-13458) ahead only by merges of main and journal / own-card "
                                "bookkeeping, which the worker_parked row then names — so nothing can "
                                "adopt/resume/land it) → RETIRED, and REFUSED without a `--force` option "
                                "if that worktree still carries un-landed work; any other status is "
                                "refused; emits worker_parked. "
                                "--work <slug> (T-10589): DISCARD a work/<slug> batch (the duplicate-"
                                "discovered-post-filing exit, X-0438) — refuses on UNCOMMITTED SUBSTANTIVE "
                                "dirt unless --force --reason; emits work_batch_discarded. Own-stamp only "
                                "unless --confirm-dead.")
    wp_grp = wp.add_mutually_exclusive_group(required=True)
    wp_grp.add_argument("--task", help="T-NNNN — the worker's task/T-NNNN worktree to park")
    wp_grp.add_argument("--work", help="slug — the work/<slug> batch worktree to DISCARD")
    # T-12369 (E-0054, X-1340): the park reason is the ONLY durable record of WHY a build was
    # discarded, and it naturally names verbs in backticks — which the shell substitutes away on
    # argv before this verb runs. Same steer + stdin route as `task refuse` (T-11165).
    wp.add_argument("--reason", default=None,
                    help="why it is being parked/discarded (recorded on the event). --task: defaults to the "
                         "branch taken — `unspecified` on a `ready` card (T-11414/X-1080: a default must "
                         "never ASSERT a cause the verb cannot know), card-died on a `wont-do` one, "
                         "landed-done on a `done` one (both READ from the verified card status). "
                         "--work: defaults to `abandoned`, and is REQUIRED with --force. "
                         f"({_PROSE_STEER_FOR('worktree park')})")
    wp.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the park reason as a YAML mapping on stdin (`reason: <text>`) — the "
                         "shell-proof path (mirrors `task refuse --from-stdin`, T-12369/X-1340); an argv "
                         "--reason alongside it is REFUSED")
    wp.add_argument("--force", action="store_true",
                    help="tear down over held work — BOTH shapes. --work: a batch carrying UNCOMMITTED "
                         "SUBSTANTIVE work. --task (T-11330): a worktree carrying UN-LANDED work (a commit "
                         "above main, or any uncommitted path beyond the re-derivable claim footprint); "
                         "without it such a park is REFUSED and points at `land` / `blocked-on-land`. NOT "
                         "admitted on the `done` retirement branch — there a held build is the "
                         "prematurely-closed shape, never a discard (T-11414). "
                         "REQUIRES --reason on both (a forced teardown is journal-evidenced, never silent).")
    wp.add_argument("--confirm-dead", action="store_true",
                    help="park a CONFIRMED-DEAD foreign orphan (controller takeover symmetry with `worktree "
                         "adopt`). A foreign worktree is never auto-parked without it (T-0362).")
    wp.add_argument("--declare-spike", dest="declare_spike", action="store_true",
                    help="--work only (T-12568, SPEC-0205 rule 8): ADOPT a legacy spike batch created WITHOUT "
                         "the spike declaration — journal `spike_declared_late` (branch, tip, session) and tag its tip "
                         "`spike/<slug>` before teardown. REFUSED for an already-declared batch or a branch "
                         "whose content already landed.")
    wp.set_defaults(func=cmd_worktree_park)
    wy = wt_sub.add_parser("sync",
                           help="Bring a writing worktree UP TO DATE with main IN PLACE, and STOP "
                                "(T-10821, X-0681) — the standalone update-from-main for the "
                                "SPEC-0094 / LIFECYCLE Stage-8(b) PRE-LAND DEPLOY SEAM, where a task "
                                "branch behind main would otherwise deploy stale code for every file "
                                "the task did not touch (and report success). It is a SYNC, NOT a "
                                "LAND: main is NEVER advanced and the worktree is NEVER removed — it "
                                "runs land's OWN two steps (fold trailing bookkeeping + "
                                "update-from-main, incl. the same fail-closed auto-resolve classes) "
                                "and nothing else. Already current = a clean no-op, not an error; "
                                "emits worktree_synced. Integrate later with `land`, as usual.")
    wy_grp = wy.add_mutually_exclusive_group(required=True)
    wy_grp.add_argument("--task", help="T-NNNN — sync the task/T-NNNN worktree from main")
    wy_grp.add_argument("--work", help="slug — sync the work/<slug> batch worktree from main")
    wy.add_argument("--resolved", action="store_true",
                    help="THE HAND-RESOLVED ARM (T-12365). Run it INSIDE the worktree with the merge "
                         "from main IN PROGRESS, after YOU resolved the conflicted files and `git "
                         "add`ed them — it is the covering verb for the raw-git `git commit` that "
                         "used to finish a non-union conflict by hand, leaving no journal row naming "
                         "what was resolved. It verifies no conflict marker remains and nothing is "
                         "left unstaged (fail-closed: it refuses naming the path, commits nothing and "
                         "emits nothing), commits the merge with git's own prepared merge message, "
                         "emits ONE merge_resolved_by_hand row, and re-runs the SAME conflict proof "
                         "`land` runs before the queue. TWO BOUNDS: it resolves NOTHING itself (the "
                         "resolution is yours), and it is still a SYNC — main is never advanced. It "
                         "is NOT an audit-currency exemption: a hand resolution is authored content, "
                         "so SPEC-0077 §3a still requires the re-audit — the row makes the shift "
                         "attributable, not excused.")
    wy.set_defaults(func=cmd_worktree_sync, cli_invoked_receipt="worktree sync")  # T-13071: attempt receipt

    work = sub.add_parser("work", help="Non-task work-batch operations (D-0051)")
    work_sub = work.add_subparsers(dest="work_action", required=True)
    wc = work_sub.add_parser("commit", help="Commit a non-task write batch (shares task commit's staging core)")
    wc.add_argument("--from", dest="from_ref", required=True, help="durable artifact for from: (CHARTER §Principle 2)")
    # T-10720 (E-0054) — the same shell-proof escape as `task commit` (same message field, same core).
    wc.add_argument("-m", "--message",
                    help="commit message (subject + optional body). "
                         f"{_PROSE_STEER_FOR('work commit')}")
    wc.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the commit message from stdin as a YAML mapping with the single key "
                         "`message:` — the SHELL-PROOF path for a message body carrying backticks "
                         "(T-10720/E-0054). Passing -m/--message alongside it is REFUSED. Feeding it from a "
                         "file? Make the file in the gitignored `.scratch/` dir — `"
                         + vocab.SCRATCH_TEMPFILE_RECIPE + "`, then `< \"$f\"` — never the "
                         "checkout root, which this verb's add-all would commit (T-12930)")
    wc.set_defaults(func=cmd_work_commit)   # D-0049: auto-syncs (default-on), parallels task commit
    wtag = work_sub.add_parser("tag",
                               help="GOVERNED release-tag (T-10501): create an annotated git tag on a "
                                    "LANDED main commit + emit release_tagged {tag,sha,project} so a "
                                    "release is journal-visible. Run FROM main (no worktree). The sole "
                                    "sanctioned path — raw `git tag -a` is the X-0354 untracked-release gap.")
    wtag.add_argument("--tag", required=True, help="the release tag name (e.g. v1.2.0)")
    wtag.add_argument("--sha", help="the commit to tag (default: main HEAD, the just-landed commit). "
                                    "Must be reachable from main — a release tags a landed commit.")
    wtag.add_argument("-m", "--message", help="annotation message (default: `Release <tag>`)")
    wtag.add_argument("--serve", choices=("canary", "promoted"),
                      help="ENGINE-ONLY on-server serving act (T-13192, SPEC-1003): prepare the sealed "
                           "per-sha checkout `.yitc/promoted-engines/<sha>`, record the release_tagged row, "
                           "THEN point the role at it. `canary` advances the one registry-declared canary "
                           "(only when BOTH pointers are absent or zero canaries are declared does it "
                           "INITIALIZE both pointers, admitted only at main HEAD; otherwise it advances the "
                           "canary pointer alone); `promoted` moves every other consumer and "
                           "is refused unless the canary's journal holds a cli_invoked row stamped with "
                           "exactly that sha. Requires --sha.")
    wtag.set_defaults(func=cmd_work_tag)   # D-0049: auto-syncs (default-on); main-checkout event folds into next land

    wpub = work_sub.add_parser("publish",
                               help="ENGINE-ONLY release publish (T-12042, SPEC-0195 rules 1+5): cut "
                                    "the kernel-realm slice at a governed `work tag` tag into --dest "
                                    "as a single history-free commit + annotated tag, both written "
                                    "as the fixed neutral release identity (never the host's; host "
                                    "hooks off; read back), beside a release MANIFEST "
                                    "(source ref / tree digest / signature target / rebuild command / "
                                    "template-owned surface) + emit release_published. Every byte is "
                                    "read from the tag's PEELED COMMIT, so the same tag always "
                                    "publishes the same digest. REFUSES a dirty workshop, a tree whose "
                                    "engine code carries a host absolute path (SPEC-0074 rule 4, code "
                                    "side), a project of this host in a value or in the commit/tag "
                                    "metadata (rule 4b), and any invocation under -C.")
    wpub.add_argument("--tag", required=True,
                      help="the governed release tag to cut (created by `yitc-v2 work tag`); resolved "
                           "to its peeled commit — a tag that does not resolve is REFUSED")
    wpub.add_argument("--dest", required=True,
                      help="the destination checkout the snapshot is written into (must already "
                           "exist). A destination only: no tasks, no journal, no lifecycle — "
                           "regenerable from the workshop at any time")
    wpub.add_argument("--signing-key",
                      help="path to the maintainer's PRIVATE signing key (T-12043, SPEC-0195 rule "
                           "6). The manifest is signed with it into `release-manifest.yaml.sig` — "
                           "the signature target that covers every published byte through the "
                           "tree digest. WITHOUT it the publish still runs but says so LOUDLY: an "
                           "unsigned artifact is REFUSED by every verifying entrypoint, so it is "
                           "installable by nobody, this machine included")
    wpub.add_argument("--trust-root",
                      help="path to the trust-root file published into the mirror (SPEC-0195 rule "
                           "7): the currently valid keys, exactly one of them the `role: anchor` "
                           "the out-of-band fingerprint pins. Copied verbatim — maintainer-held "
                           "key material a publish never invents; refused if it does not parse")
    wpub.add_argument("--revocations",
                      help="path to the revocation list published beside the trust root (SPEC-0195 "
                           "rule 7). A release signed by a revoked key is refused on the ordinary "
                           "install path, naming the revocation")
    wpub.add_argument("--dry-run", action="store_true",
                      help="run every step and guard (cut, strip, identity/host refusals, commit/tag "
                           "metadata check, install smoke, signing) but write NOTHING to --dest and "
                           "journal nothing (T-13382)")
    wpub.set_defaults(func=cmd_work_publish)   # run FROM main like `work tag` — no writing worktree

    release_p = sub.add_parser("release",
                               help="CONSUMER-side release verbs (T-12043, SPEC-0195 rules 6+7) — "
                                    "the ENUMERATED verifying entrypoints. Every one of them "
                                    "verifies the signed manifest against the trust root, anchored "
                                    "OUT OF BAND, BEFORE it writes anything; a tampered artifact, "
                                    "a tampered trust root and a revoked signing key are each "
                                    "refused by name. The publishing side is `work publish`.")
    release_sub = release_p.add_subparsers(dest="release_cmd", required=True)

    rver = release_sub.add_parser("verify",
                                  help="verify a published release IN PLACE against the out-of-band "
                                       "anchor: trust root -> manifest signature -> tree digest. "
                                       "Writes nothing under any outcome — it IS the gate.")
    rver.add_argument("dest", help="the published release directory (a local clone of the mirror)")
    rver.add_argument("--anchor", required=True,
                      help="the OUT-OF-BAND trust-root key fingerprint (`SHA256:...`), taken from a "
                           "channel INDEPENDENT of this mirror. Required: without it the mirror "
                           "would vouch for itself, which is the one thing the anchor prevents")
    # T-12173: EXCLUDED from `_auto_sync` (the D-0049 knob `journal sync` / `land` already use).
    # _auto_sync materializes the session log into `events.jsonl` and writes `journal-sync-state/`
    # BEFORE the verb runs — on an adopter's freshly-cloned mirror that is a WRITE performed by a
    # verb whose whole contract is "writes nothing under any outcome". Inert here by construction
    # rather than by luck.
    rver.set_defaults(func=cmd_release_verify, no_autosync=True)

    rins = release_sub.add_parser("install",
                                  help="install a VERIFIED release into --into. The gate runs to a "
                                       "verdict before the target is opened, so a refused install "
                                       "leaves the destination byte-identical (SPEC-0195 rule 6, "
                                       "'BEFORE any write', read literally).")
    rins.add_argument("dest", help="the published release directory (a local clone of the mirror)")
    rins.add_argument("--into", required=True,
                      help="the directory the verified release is installed into")
    rins.add_argument("--anchor", required=True,
                      help="the OUT-OF-BAND trust-root key fingerprint (`SHA256:...`) — see "
                           "`release verify --anchor`")
    # T-12173: EXCLUDED from `_auto_sync` for the same reason as `release verify` above — the only
    # write an install may make is INTO `--into`, never into the mirror it reads.
    rins.set_defaults(func=cmd_release_install, no_autosync=True)

    rchk = release_sub.add_parser("check",
                                  help="is there a NEWER release? Read-only report for a project "
                                       "that PINS its engine (`-C <project>`): pinned vN · newest "
                                       "vM · behind by K, plus the head of each newer release's "
                                       "notes. Writes nothing, journals nothing, exits 0 always — "
                                       "a report, not a gate. Moving the pin is `release update`.")
    # NO arguments: `-C <project>` already names the project, and the mirror + the tag both come
    # from that project's own `kernel.engine` pin (SPEC-0195 rule 3). A `--release-repo` override
    # would let the report be run against a mirror the project does not pin, which answers a
    # different question than the one the verb exists for.
    #
    # `no_autosync=True` for the `release verify` / `release install` reason above (T-12173):
    # `_auto_sync` materialises `events.jsonl` + `journal-sync-state/` in the target checkout BEFORE
    # the verb runs, which for a writes-nothing verb is a write performed on its behalf.
    # DELIBERATELY NO `cli_invoked_verb` MARKER: that marker is what emits the T-0113 read-verb
    # observability row — precisely the journal append this verb promises never to make — so the
    # ergonomic seed-gate allowlist it buys is unavailable here and the explicit exemption in
    # `_require_seed_read_chokepoint` clause (d) is taken instead.
    rchk.set_defaults(func=cmd_release_check, no_autosync=True)
    rupd = release_sub.add_parser("update",
                                  help="move an EXISTING install from release N to N+1 (SPEC-0195 "
                                       "rule 8). Upstream-owned paths are replaced wholesale from "
                                       "the gate's own verified snapshot, template-owned paths are "
                                       "three-way merged, and consumer-owned paths are never "
                                       "written; every divergence is reported rather than guessed. "
                                       "Same ordering as `install`: the gate reaches its verdict "
                                       "before --into is opened, so a refused update leaves the "
                                       "destination byte-identical.")
    rupd.add_argument("dest", help="the published release directory to update FROM (release N+1)")
    rupd.add_argument("--into", required=True,
                      help="the EXISTING install being moved forward. Must already exist: the "
                           "FIRST install is `release install`, and back-filling newly-added "
                           "scaffolds is `init` — there is no second scaffold path")
    rupd.add_argument("--anchor", required=True,
                      help="the OUT-OF-BAND trust-root key fingerprint (`SHA256:...`) — see "
                           "`release verify --anchor`")
    rupd.add_argument("--from-release",
                      help="the pinned release-N tree, as the MERGE BASE. Optional, and the verb "
                           "says out loud what is lost without it: with no base a local edit cannot "
                           "be told apart from an out-of-date file, so every differing path is "
                           "REPORTED and left untouched — a legal, useful read, but not an update")
    # T-12173: EXCLUDED from `_auto_sync` for the same reason as `release verify` / `release install`
    # above — an adopter drives this out of a freshly-cloned mirror, and materializing a session log
    # there would be a write performed BEFORE a verb whose whole ordering contract is that nothing is
    # written until every decision is made.
    rupd.set_defaults(func=cmd_release_update, no_autosync=True)

    dispatch = sub.add_parser("dispatch",
                              help="THIN dispatch launcher (T-0558, list-extended T-0580) — fresh "
                                   "session id + scrub-ALL identity carriers + spawn background "
                                   "worker(s) + emit a dispatch event per task carrying the assigned "
                                   "`expected` ref. Repeat --task to launch SEVERAL sequentially in "
                                   "one invocation (serialized appends, no concurrent-append race). "
                                   "NOT an orchestrator (no selection/ordering/retry — non-goal #7); "
                                   "after a launch it CONTINUES INTO ITS OWN READ-ONLY WATCH in the "
                                   "same process (T-12637), which is observation, not orchestration — "
                                   "the `--watch` loop has always blocked; what moved is that no "
                                   "separate arming call is left to skip. Owner-invoked, trial.")
    # T-10699 (X-0552) — the dispatch verb has THREE distinct modes and a flat option list hid the
    # split (an operator mixed a LAUNCH brief with --watch and burned 2 invocations). Group the flags
    # by mode so `--help` renders LAUNCH / WATCH / STOP as titled sections; --task is shared (every
    # mode names its target tasks) so it stays at the parser level. Help-text only, no behavior change.
    dispatch.add_argument("--task", action="append", required=True,
                          help="T-NNNN target task(s) — SHARED by all three modes below (REPEATABLE — "
                               "one worker per id in LAUNCH mode, launched in the given order)")
    dispatch_launch = dispatch.add_argument_group(
        "LAUNCH mode (the default) — spawn background worker(s)",
        "--task + --brief/-f. These flags are LAUNCH-ONLY; passing them with --watch or --stop is "
        "refused (those modes launch nothing).")
    dispatch_watch = dispatch.add_argument_group(
        "WATCH mode (--watch) — monitor existing worker(s), launches NOTHING",
        "polls the §6-safe read-only readers over --task and exits on a `WATCH:` token. The --watch-* "
        "flags are WATCH-ONLY; they do nothing (and are refused) without --watch.")
    dispatch_stop = dispatch.add_argument_group(
        "STOP mode (--stop) — governed stop of a dispatched worker, launches NOTHING",
        "TWO arms: bare --stop stops a CLAIM-LESS rogue/dead worker; --stop --defer stops a CLAIMED, "
        "LIVE worker to take it out of the wave and re-run it later. --restore-path/--defer are "
        "STOP-ONLY.")
    dispatch_launch.add_argument("--brief", action="append",
                          help="the worker's spawn prompt (REPEATABLE — one per --task, in order)")
    dispatch_launch.add_argument("-f", "--brief-file", dest="brief_file", action="append",
                          help="path to a file containing the brief (REPO_ROOT-relative or absolute); "
                               "REPEATABLE — one per --task, in order. stdin is the single-task "
                               "fallback when neither --brief nor -f given. Mix --brief and -f NOT "
                               "allowed (ambiguous pairing).")
    dispatch_launch.add_argument("--brief-raw", dest="brief_raw", action="store_true",
                          help="T-12303: send the brief(s) VERBATIM as the whole prompt — skip the "
                               "COMPOSED preamble `dispatch` otherwise derives from durable state "
                               "(the card's acceptance, the covering owner_directive rows, what the "
                               "`requires` shipped, the stop/land contract, the venue line). No "
                               "composed brief file is written and the bg_dispatch_launched row "
                               "carries no `brief` locator. For the rare hand-crafted case.")
    dispatch_launch.add_argument("--controller-lands", dest="controller_lands", action="store_true",
                          help="T-12373: dispatch this wave under the CONTROLLER-LANDS regime — the "
                               "worker runs every stage through `task close`, reports the CLOSING "
                               "SHA, and STOPS; the CONTROLLER lands from main. DEFAULT (flag "
                               "absent) is the CANON (CHARTER §6): the WORKER lands itself and must "
                               "reach the `LAND: OK <sha>` token in its own turn. Exactly ONE of the "
                               "two regimes is stated per brief — under this flag the composed STOP "
                               "/ LAND CONTRACT block is its one home and preamble point 1 renders a "
                               "neutral synchronous-to-CLOSE head; without it point 1 carries the "
                               "synchronous-to-LAND rule and no stop/land block is appended. Also "
                               "recorded as `bg_dispatch_launched.data.land_regime`, which the "
                               "stage-entry reminder reads, so a worker is never told both. Replaces "
                               "hand-typing «DO NOT LAND YOURSELF» into the brief delta.")
    dispatch_launch.add_argument("--model",
                          help="OPTIONAL effort-tier escape hatch (SPEC-0072): override the worker "
                               "model for ALL dispatched tasks, winning over the effort_tier->model map. "
                               "Default: each task's effort_tier resolves the model via "
                               "bin/effort-routing-config.yaml (no human model choice at launch).")
    dispatch_launch.add_argument("--effort",
                          help="OPTIONAL effort-tier escape hatch (SPEC-0072): override the worker "
                               "effort level for ALL dispatched tasks, winning over the map.")
    dispatch_launch.add_argument("--no-self-arm-watch", dest="self_arm_watch", action="store_false",
                          default=True,
                          help="LAUNCH MODE (T-12637) — OPT OUT of the launch continuing into its own "
                               "watch. By DEFAULT a launch that launched anything self-arms the "
                               "§Watcher over exactly the launched ids IN THIS PROCESS and ends on the "
                               "`WATCH:` token, so there is no separate `dispatch --watch` call for the "
                               "Controller to type in the orphaning shape (X-1443 / X-1440: `cmd > log "
                               "2>&1 &` inside a foreground call orphans the watcher) or to skip "
                               "altogether (five unwatched workers, 2026-09-16). With this flag the "
                               "launch ends on `DISPATCH:` and prints the hand-arming cue instead; "
                               "arming by hand is then YOUR duty. A `--watch` over ids that already "
                               "have a LIVE watcher is refused as a duplicate (one watcher per task); "
                               "a watcher that has ENDED never blocks a re-arm.")
    dispatch_launch.add_argument("--force", action="store_true",
                          help="override the in-flight-dispatch SKIP guard (X-0131 escape) — launch even "
                               "when a recent bg_dispatch_launched without a live worktree is detected.")
    dispatch_launch.add_argument("--resume", action="store_true",
                          help="LAUNCH MODE (T-12304) — relaunch a task whose worker STOPPED CLEANLY as "
                               "cued and recorded it with `task pause --reason controller-wait`. Heads "
                               "the worker\'s task-specific brief with that row\'s RECORDED RESUME "
                               "CONTRACT (paused_at / stage / resume_from / next_action) — read from "
                               "the JOURNAL, never controller memory — and stamps `resume_of: <pause "
                               "ts>` on the ordinary bg_dispatch_launched. --brief/-f become OPTIONAL "
                               "and carry only a DELTA amending the contract. Needs no --force (the "
                               "in-flight guard yields to that pause row). Fail-closed: refuses when "
                               "no live controller-wait pause newer than the newest launch exists. Serves "
                               "ONLY reason=controller-wait: every other pause or halt (audit-ceiling, "
                               "blocked-on-land, ...) re-enters via the ordinary `dispatch --task` "
                               "(resume mode, T-12332).")
    dispatch_stop.add_argument("--stop", action="store_true",
                          help="STOP MODE (T-10376) — governed controller stop of a CLAIM-LESS rogue/dead "
                               "worker. Takes exactly one --task and LAUNCHES NOTHING: stops the launched "
                               "pid (verified by --session-id, never a stale-pid blind kill), captures a "
                               "main-checkout evidence diff BEFORE any restore, reverts ONLY the "
                               "operator-named --restore-path files (fail-closed), and emits the terminal "
                               "bg_dispatch_halted the in-flight guard consumes so the task is "
                               "redispatchable without --force. Idempotent + refuses a claimed/settled "
                               "dispatch. Stateless (target derived from journal+git; CHARTER §6). Rule "
                               "home: patterns/background-session-monitoring.md §Abnormal. To stop a "
                               "CLAIMED, LIVE worker instead — take it out of the wave and re-run it "
                               "later — add --defer (the claimed-worker arm; T-11548).")
    dispatch_stop.add_argument("--restore-path", dest="restore_path", action="append", metavar="PATH",
                          help="[--stop] a tracked+dirty main-checkout SOURCE path to revert to HEAD "
                               "(REPEATABLE). ONLY explicitly-named paths are restored — unattributable "
                               "dirt (a concurrent session's WIP) is never blanket-reverted; the journal "
                               "(events.jsonl) is refused as a target. Omit to restore nothing (evidence "
                               "is still captured + the dirty set reported).")
    dispatch_stop.add_argument("--defer", action="store_true",
                          help="[--stop] DEFER ARM (T-11548) — the CLAIMED-worker arm of the governed "
                               "stop: take a LIVE, CLAIMED worker OUT OF THE WAVE to re-run it later, "
                               "the case the bare --stop refuses (it recovers a claim-less rogue only, "
                               "and the verbs it points at — `worktree adopt` / `worktree recover-land` "
                               "— are FINISH paths that drive the work to completion). Reuses every "
                               "--stop rail: verified-pid stop (never a "
                               "stale-pid blind kill), evidence capture before any restore, and the "
                               "terminal bg_dispatch_halted (kind=controller_defer). It then WAITS, "
                               "bounded, for the worker to actually stop and REFUSES rather than emit "
                               "terminality over a still-live claimed worker. Worktree disposal follows "
                               "the SPEC-0103 pause-shape fork, delegated to the park core: "
                               "bookkeeping-only -> torn down, task `ready` and cleanly re-dispatchable; "
                               "WORK-CARRYING -> PRESERVED intact (re-enter via `task resume`), and the "
                               "output + the journal row say which of the two it did. It NEVER discards "
                               "a build; discarding a preserved worktree stays the separate explicit "
                               "act of `worktree park` (the exact command is printed in the preserved "
                               "outcome, where an operator acts on it). Explicit and "
                               "owner-cued: no auto-defer, no queue-state machinery, no policy about "
                               "WHEN to defer (CHARTER \u00a76).")
    dispatch_watch.add_argument("--watch", action="store_true",
                          help="WATCH MODE (T-10347) — the blessed controller watcher. LAUNCHES NOTHING "
                               "(and never consumes stdin): polls the §6-safe read-only readers over the "
                               "given --task ids and EXITS with a contracted terminal token as its final "
                               "stdout line — `WATCH: WAKE|ALL_TERMINAL|ANY_TERMINAL|TIMEOUT <reason>` (match "
                               "`^WATCH: (WAKE|ALL_TERMINAL|ANY_TERMINAL|TIMEOUT)\\b`; parse the TOKEN, not the shell "
                               "exit — the `LAND:` contract analog). Run it under the harness Monitor "
                               "primitive (the persistent watch-until-condition wrapper, NOT a plain "
                               "background job — a plainly-backgrounded long wait can be SWEPT before it "
                               "reports, silently leaving no monitor armed) and let your harness's "
                               "completion notification re-invoke you: that exit IS the wake, but key "
                               "recovery off the JOURNAL, never the wrapper's process lifetime. "
                               "ARMING FORM IS NOW CLASSIFIED AT ARM TIME (T-12641, X-1440): armed as a "
                               "plain shell background job with its output REDIRECTED AWAY from your own "
                               "(`... > log 2>&1 &`) the watcher is ORPHANED — it polls correctly and "
                               "writes its token to a log nothing reads — so the verb prints a LOUD banner "
                               "into YOUR OWN output window, records `watch_armed(reachability=...)`, and "
                               "WITHHOLDS the SPEC-0119 rule-12 monitoring credit. Only the NEGATIVE is "
                               "provable: everything else records `unproven`, which is NOT a delivery "
                               "attestation (a bare `&` inherits your stdout and is still orphaned). Wakes on an "
                               "actionable verdict (dead / needs-decision) OF A WATCHED TASK only once "
                               "CONFIRMED across --watch-confirm-ticks consecutive ticks (never a single "
                               "transient snapshot); ALSO wakes on a PAUSED card: a watched task reading "
                               "`paused(<reason>)` is over but never a clean completion (SPEC-0133 rule "
                               "5d), so it turns the all-terminal exit into WAKE and never exits "
                               "ANY_TERMINAL — an `artifact-wait` pause waits on the artifact its card "
                               "declares, any other on the decision its reason names; "
                               "NEVER wakes on a `working` heartbeat; NEVER wakes on "
                               "a worker OUTSIDE the --task set (that is another watcher's business — "
                               "T-10402; use --watch-fleet to opt in); proves completion "
                               "POSITIVELY off each task's parsed class=TERMINAL token, never off a "
                               "task's absence from a report; exits per-worker (naming the finished "
                               "task) only under the explicit --watch-any-terminal opt-in. "
                               "Read-only: it mutates nothing and never "
                               "kills/adopts/lands/respawns/schedules (CHARTER §6; SPEC-0133 rule 1). "
                               "Rule home: patterns/background-session-monitoring.md §Watcher.")
    dispatch_watch.add_argument("--watch-fleet", dest="watch_fleet", action="store_true",
                          help="[--watch] OPT IN to fleet-wide waking (T-10402): wake on ANY in-flight "
                               "worker's confirmed actionable verdict, not just the workers holding a "
                               "watched --task. OFF by default — a watcher answers for the tasks it was "
                               "armed over, and a foreign verdict used to burn the batch monitor + a "
                               "controller turn (7 phantom wakes, 2026-07-11). Independent of the wake "
                               "SCOPE, a wake always REPORTS the whole fleet, so siblings are never "
                               "abandoned (T-0680) — this flag only widens what may WAKE you.")
    dispatch_watch.add_argument("--watch-any-terminal", dest="watch_any_terminal", action="store_true",
                          help="[--watch] OPT IN to a PER-WORKER exit (T-11829): return as soon as ANY "
                               "ONE watched task reaches a positive class=TERMINAL(done) confirmed "
                               "across --watch-confirm-ticks, exiting `WATCH: ANY_TERMINAL` (rc 3) with "
                               "a reason NAMING that task — while its siblings keep working. This is "
                               "what an N-slot refill queue needs («start a replacement AS EACH worker "
                               "lands, not in waves»): the default all-at-once ALL_TERMINAL cannot "
                               "express it, and the workaround was one single-task watcher process per "
                               "worker, hand-re-armed after every land. OFF by default — the unflagged "
                               "exit contract (ALL_TERMINAL / WAKE / TIMEOUT) is unchanged. The early "
                               "exit still REPORTS the whole fleet, so siblings are never abandoned "
                               "(T-0680); an early terminal whose detail is recovery-bearing (halt / "
                               "wont-do / blocked_on_land / a paused card) exits WAKE instead, as it "
                               "does today.")
    dispatch_watch.add_argument("--watch-interval", dest="watch_interval", type=int,
                          default=journal_mod.WATCH_POLL_INTERVAL_SECS, metavar="SEC",
                          help=f"[--watch] seconds between ticks (default {journal_mod.WATCH_POLL_INTERVAL_SECS}, "
                               f"the sanctioned WATCH_POLL_INTERVAL_SECS per §Watcher).")
    dispatch_watch.add_argument("--watch-timeout", dest="watch_timeout", type=int,
                          default=journal_mod.WATCH_MAX_RUNTIME_SECS, metavar="SEC",
                          help=f"[--watch] give up after this long with no wake condition and exit "
                               f"`WATCH: TIMEOUT` (default {journal_mod.WATCH_MAX_RUNTIME_SECS}, the sanctioned "
                               f"WATCH_MAX_RUNTIME_SECS). Bounded by construction — the watcher never "
                               f"loops forever.")
    dispatch_watch.add_argument("--watch-confirm-ticks", dest="watch_confirm_ticks", type=int, default=2,
                          metavar="N",
                          help="[--watch] consecutive ticks an actionable verdict (or an all-terminal "
                               "read) must persist before the watcher acts on it (default 2 — the "
                               "§Recovery-trigger (b) >=2-tick confirmation rule, T-0693: a `land` in "
                               "flight flickers and a live worker's pid flaps).")
    dispatch.set_defaults(func=cmd_dispatch)

    spec = sub.add_parser("spec", help="Spec operations (per GRAPH §Schema)")
    spec_sub = spec.add_subparsers(dest="spec_action", required=True)
    sn = spec_sub.add_parser("new", help="Allocate next SPEC-NNNN (flock) + scaffold from _template.yaml")
    sn.add_argument("--title", required=True, help="short statement")
    sn.add_argument("--travels", choices=[*PLACEMENT_REALMS, "default"],
                    help="REQUIRED placement decision (the corpus-wide placement contract, T-0888): "
                         "kernel|v2-self|project, or `default` to affirm the spec class-default (kernel). "
                         "Fails closed when omitted; a body marker is written only for a non-default exception.")
    sn.add_argument("--draft", action="store_true",
                    help="birth a DRAFT spec (status: draft, plan-local; SPEC-0005 §4 FSM). Requires --proposed-by.")
    sn.add_argument("--proposed-by", dest="proposed_by", metavar="PLAN-SLUG",
                    help="the plan that authors this draft (MANDATORY with --draft; must exist in plans/).")
    sn.add_argument("--id", dest="id", metavar="SPEC-NNNN",
                    help="allocate THIS id instead of the next sequential one (T-12397). Admitted only "
                         "INSIDE this repo's spec-id zone (T-12839, SPEC-0092: the kernel allocates "
                         "SPEC-1000..4999, every consumer SPEC-5000..9999; nothing new below 1000) AND "
                         "STRICTLY ABOVE the current max, so an out-of-zone, taken or reserved id is "
                         "refused with no file written and no id burned; the next plain `spec new` "
                         "continues after it.")
    sn.set_defaults(func=cmd_spec_new)

    sl = spec_sub.add_parser("ledger-label",
                             help="Allocate the next rule↔test ledger ROW LABEL in a section "
                                  "(flock — the SAME allocator task/spec ids use; T-10888)")
    sl.add_argument("--section", required=True, metavar="LETTER",
                    help="ledger section letter (e.g. A, H, I) — the label is unique within it")
    sl.add_argument("--ledger", default="specs/yitc-v2-rule-test-ledger.md",
                    help="repo-relative ledger path (default: this repo's kernel ledger)")
    sl.set_defaults(func=cmd_spec_ledger_label, cli_invoked_receipt="spec ledger-label")  # T-12846: allocates — receipt, never a read marker

    se = spec_sub.add_parser("edit", help="In-place edit of an EXISTING active/proposed spec — the "
                                          "before-rule-change chokepoint (T-0273); mirrors the Edit primitive",
                             formatter_class=argparse.RawDescriptionHelpFormatter,
                             epilog=f"cue (T-10159): {_SELF.SPEC_BODY_EDIT_CUE}")
    se.add_argument("id", help="SPEC-NNNN id of the spec to edit (must be active or proposed)")
    se.add_argument("--old", help="exact existing text to replace, matched against the RAW file text "
                                  "first (0 or >1 match dies). Text that reads as the parsed body "
                                  "(what `graph query` prints, without the block indent) is found "
                                  "too, and is then edited AS body text. A ONE-LINE --old written "
                                  "without its block indent is found BOTH ways: with a multi-line "
                                  "--new whose continuation lines all carry the block indent the "
                                  "two readings write different bodies, so the verb refuses and "
                                  "names both forms (T-13600). Every successful edit prints the "
                                  "reading it took (`reading: raw replacement` / `reading: edited "
                                  "as body text`). CLI mode; mutually exclusive with "
                                  "--from-file/--from-stdin")
    se.add_argument("--new", help="replacement text (CLI mode; needs --old). When --old is text of "
                                  "the parsed body, write --new as it should read in the body: its "
                                  "lines land at the nesting you type, and the verb refuses rather "
                                  "than write a body that means something else (T-13509) — "
                                  "unless every continuation line starts at or past the block "
                                  "indent, which is the both-ways case under --old. When "
                                  "--old is copied WITH the file's own indentation, the edit is a "
                                  "raw replacement and every line of --new must carry that "
                                  "indentation itself")
    se.add_argument("--from-file", dest="from_file",
                    help="read the edit as a YAML mapping {old, new, replace_all?} from this file — "
                         "carries multi-line/full-section body replacements the flat --old/--new cannot "
                         "(mirrors `task file --from-stdin`); the verb, not a hand-edit (T-10051)")
    se.add_argument("--from-stdin", dest="from_stdin", action="store_true",
                    help="read the edit as a YAML mapping {old, new, replace_all?} from stdin "
                         "(same shape as --from-file)")
    se.add_argument("--replace-all", dest="replace_all", action="store_true",
                    help="replace ALL occurrences of --old (default: require a single unique match)")
    se.add_argument("--bless", action="store_true",
                    help="BLESS an ALREADY-MADE in-place edit of an ACTIVE spec (T-10135): derive its "
                         "diff vs `main`, emit a DIFF-BOUND spec_edited (base/new sha + fingerprint + "
                         "fields), and clear the T-9730 land guard for it — ONLY if the final base..HEAD "
                         "diff matches the fingerprint. Fires the before-rule-change gate (SPEC-0005 read "
                         "receipt). Mutually exclusive with --old/--new/--from-file/--from-stdin")
    se.set_defaults(func=cmd_spec_edit, cli_invoked_receipt="spec edit")  # T-13071: attempt receipt

    sr = spec_sub.add_parser("reverify", help="Record the durable content-signature freshness "
                                              "baseline for a spec's anchors (T-0506, E-0019 kind-B)")
    sr.add_argument("id", help="SPEC-NNNN id to reverify (must be active or proposed)")
    sr.add_argument("--anchor", action="append",
                    help="Re-sign ONLY this declared `implements:` anchor (repeatable). Every other "
                         "anchor's baseline is left byte-identical — use this to bless exactly the "
                         "code you re-read the spec against (T-10324). Naming an anchor ASSERTS you "
                         "verified it, so the untouched-anchor guard does not apply to a named scope: "
                         "this is the escape for re-signing an accuracy-verified drifted anchor a "
                         "verification-only task never moved (T-10374)")
    sr.add_argument("--include-untouched", action="store_true",
                    help="Re-sign the WHOLE spec, INCLUDING anchors this branch's diff never touched "
                         "that have already drifted. Without it such a re-sign is REFUSED: it silently "
                         "re-baselines pre-existing drift onto an unrelated diff (T-10300, T-10318). "
                         "Assert this only after re-reading the spec against ALL its anchored code")
    sr.set_defaults(func=cmd_spec_reverify)

    # T-13465 (SPEC-0209 bound (e)) — every GUARDED verb takes exact option spellings only. The seam's
    # flag scan is exact-token, so a prefix argparse resolved (`task close --pv-crit=...`) would carry
    # the prose past it. Derived from the seam registry, read through the host at call time, so a row
    # added there is covered here by construction — no second list of guarded verbs to keep in step.
    for verb_tokens, flags, *_ in _SELF.textutil.ARGV_PROSE_SEAMS:
        guarded = p
        for tok in verb_tokens:
            guarded = next(a for a in guarded._actions
                           if isinstance(a, argparse._SubParsersAction)).choices[tok]
        guarded.allow_abbrev = False
        # A variadic positional swallows what argparse would otherwise reject (`blocked-on-land`'s
        # reason words, T-11058), so there the prefix would be RECORDED as text rather than refused.
        if any(a.nargs in ("*", "+", argparse.REMAINDER) for a in guarded._actions if not a.option_strings):
            _refuse_guarded_flag_prefixes(guarded, [f for f, _key in flags if f.startswith("--")])

    _stamp_derived_receipts(p)
    return p


def _refuse_guarded_flag_prefixes(parser: argparse.ArgumentParser, flags: list) -> None:
    """T-13465 — on `parser`, a `--token` that is no registered option but IS a prefix of one of the
    guarded `flags` is a parser error (exit 2), checked BEFORE the parse so a variadic positional
    cannot absorb it as text. Narrow on purpose: any other unknown token is left to the parser, so
    `blocked-on-land`'s accepted consequence (a mistyped flag becomes reason text, T-11058) stands
    for every token that never resolved to a guarded flag. Tokens after a bare `--` are positional."""
    inner = parser.parse_known_args

    @functools.wraps(inner)
    def parse_known_args(args=None, namespace=None):
        for tok in (sys.argv[1:] if args is None else args):
            if tok == "--":
                break
            name = tok.split("=", 1)[0]
            if not name.startswith("--") or name in parser._option_string_actions:
                continue
            full = [f for f in flags if f.startswith(name)]
            if full:
                parser.error(f"abbreviated option {name}: spell {' / '.join(full)} in full — this verb "
                             f"takes exact option spellings only (SPEC-0209), or send the value via "
                             f"--from-stdin")
        return inner(args, namespace)

    parser.parse_known_args = parse_known_args


# The leaves that take NO derived receipt, each with its reason (T-13305):
_WRITES_OWN_RECEIPT = {
    # its body writes its OWN gate-bearing receipt; a derived second row would duplicate it (and stamp
    # the seed sentinel twice). Its missing duration is its own card (T-13303).
    "session start": "writes its own gate-bearing seed receipt (T-13303 owns its duration)",
    # the journal's own materialiser (the hook-driven transcript sync): a receipt per sync would be the
    # journal observing itself — the T-0113 self-observation exclusion `test_c_journal_sync_excluded` pins.
    "journal sync": "self-observation exclusion (T-0113): the journal materialiser records no receipt of itself",
    # owner-approved AC1 exclusions (events.jsonl#ts=2026-10-01T17:33:10Z): a pinned no-append contract.
    "init": "self-committing bootstrap (init family incl. --adopt-concern): a clean tree after its own commit",
    "followup show": "byte-identical view contract (test_followup)",
    "session pick": "zero-write project picker (T-12960 'no marker')",
}


def _stamp_derived_receipts(parser) -> None:
    """T-13305 — every parser leaf that carries neither `cli_invoked_verb` nor `cli_invoked_receipt` is
    registered for the T-12846 invocation RECEIPT under its own `<group> <leaf>` label, so no verb runs
    unmeasured (reads counters + duration + peak RSS, SPEC-0190 rule 10: the one emit site, no per-verb
    mechanism). Parser-derived (the same two-level walk as `_live_cli_verbs`), never a list; a deeper
    parser inherits its two-level label. `cli_invoked_derived` marks the stamp so the dispatch envelope can
    keep a verb's explicit no-append FORM (`cli.py#_promises_no_append`) — a marked receipt is untouched."""
    for act in (parser._subparsers._group_actions if parser._subparsers else []):
        for grp, sub in (getattr(act, "choices", {}) or {}).items():
            acts = sub._subparsers._group_actions if getattr(sub, "_subparsers", None) else []
            leaves = [(f"{grp} {leaf}", lp) for a2 in acts for leaf, lp in (getattr(a2, "choices", {}) or {}).items()]
            for label, lp in (leaves or [(grp, sub)]):
                if lp._defaults.get("cli_invoked_verb") or lp._defaults.get("cli_invoked_receipt"):
                    continue
                if label in _WRITES_OWN_RECEIPT:
                    continue
                lp.set_defaults(cli_invoked_receipt=label, cli_invoked_derived=True)


def _warn_help_receipt_uncredited() -> None:
    """The at-the-scan signal for an UNCREDITABLE `--help` verb-inventory scan (T-10784 / X-0615).

    Printed when `_emit_cli_invoked`'s `--help` leg resolved NO session identity — i.e.
    `_try_resolve_session_ref_with_source()` returned (None, None), so the fetch-receipt fell back to
    the best-effort envelope and `_require_help_read` (which keys on the FAIL-CLOSED
    `_resolve_session_ref`, the twin's dying mirror) will NOT credit it.

    Why a warning and not a fix: that refusal is CORRECT and stays (crediting an anonymous receipt would
    make the gate satisfiable by any process on the host — the X-0158 anti-fix). What was defective is
    that the scan was SILENT: it exits 0, so the operator only learns at a DISTANCE, when the first gated
    verb (`worktree new` / `task file` / `land`) refuses "verb inventory not scanned" for a scan they
    demonstrably performed — and then debugs the wrong thing. This closes the gap SPEC-0137's "a missed
    carry is SAFE — a later verb rediscovers your session record or fails closed cleanly" promise leaves
    open at THIS surface: `--help` neither rediscovered nor failed closed, it succeeded uncredited.

    STDERR only, exit status untouched (the scan itself DID succeed and the inventory DID print) — so no
    `--help`-parsing consumer is affected. Both remediation lines are reconstructed from the LIVE
    invocation, never a hardcoded `bin/yitc-v2` prefix: an absolute-engine or `-C <consumer>` call must
    read back the command the operator can actually paste (audit-pre F2)."""
    argv = list(sys.argv)
    exe = argv[0] if argv else "bin/yitc-v2"
    # The `-C <path>` pair, when given, belongs on the `session start` line too — it selects WHICH
    # checkout's journal the anchor lands in, the same journal this receipt just went to.
    prefix = [exe]
    for i, tok in enumerate(argv[1:], start=1):
        if tok in ("-C", "--directory") and i + 1 < len(argv):
            prefix += [tok, argv[i + 1]]
            break
        if tok.startswith("-C") and len(tok) > 2:
            prefix.append(tok)
            break
        if tok.startswith("--directory="):
            prefix.append(tok)
            break
    lines = [
        "yitc-v2: WARNING — this --help scan is NOT credited to any session (no session identity "
        f"resolved; missing carry: {SELF_REF_ENV}, and no v2 session record was rediscoverable for "
        "this process either).",
        "  consequence: your next `worktree new` / `task file` / `land` will REFUSE «verb inventory "
        "not scanned» — for the scan you just performed. The gate is correct; this receipt is anonymous.",
        "  fix — start the session, then re-run this exact scan carrying the ref it prints:",
        f"    {shlex.join(prefix + ['session', 'start'])}",
        f"    {SELF_REF_ENV}=<ref printed above> {shlex.join(argv)}",
    ]
    print("\n".join(lines), file=sys.stderr)


# T-13520 (public issue #16) — what `task test --run` executes for a CONSUMER (`-C`). The engine text
# inside `build_parser` describes the engine's own run (its tests/ sweep) and stays byte-unchanged;
# a consumer's run is its DECLARED verify layers, so its help says that instead.
TASK_TEST_RUN_CONSUMER_HELP = (
    "run land's CANDIDATE verify leg only, for this project: every verify layer its yitc-ops.yaml "
    "declares under `verify.layers` — each layer's command, one after another unless the project "
    "names them under `verify.independent_layers`; a layer whose `subject_globs` match none of this "
    "working tree's changes against the merge-base with main is SKIPPED, the skip `land` decides on "
    "the same diff, and any doubt runs every layer (SPEC-0152 rule 16) — plus the project's test "
    "sweep (its test directory's test_*.py, each via python3, exit 0 = pass) where such a directory "
    "exists and no declared layer covers it. The result line names the layers that ran and the ones "
    "skipped or waived. A green here is NOT the land verdict: `land` reaches its own, and it also "
    "runs the SPEC-0077 pinned last-green leg unless the project's "
    "`verify_policy.pinned_last_green` is `never` (SPEC-0186); composes with --evidence "
    "(run-then-record)")


def install_consumer_help(parser) -> bool:
    """T-13520 — put `TASK_TEST_RUN_CONSUMER_HELP` on the `task test --run` flag of a BUILT parser.
    Called by the host ONLY for a parser built for a consumer `-C` root (`cli.py#_build_cli_parser`),
    so `build_parser` and the engine's help are untouched. Returns whether the flag was found; a
    parser without it is left as built (help text must never break a parse)."""
    def _sub(p, name):
        for act in p._actions:
            if isinstance(act, argparse._SubParsersAction) and name in act.choices:
                return act.choices[name]
        return None
    task = _sub(parser, "task")
    test = _sub(task, "test") if task is not None else None
    for act in (test._actions if test is not None else ()):
        if "--run" in act.option_strings:
            act.help = TASK_TEST_RUN_CONSUMER_HELP
            return True
    return False


# The keyword-only inject roster of `build_parser`, DERIVED from its signature — the host residue reads
# each name from its live globals at call time (never a second hand-maintained list).
BUILD_PARSER_INJECTS: tuple = tuple(
    p.name for p in inspect.signature(build_parser).parameters.values() if p.kind is p.KEYWORD_ONLY)
