"""Machine-scoped settings — the tunable INVENTORY, the two-class split, and the override file
(T-11967).

WHAT THIS IS. Every runtime tunable the engine reads — the `YITC_*` environment knobs plus the
hardcoded module constants of the same nature — is enumerated ONCE here, and each entry carries a
CLASS. The class decides one thing: whether the value may live in the machine-scoped settings file,
which belongs to the MACHINE and not to any repo checkout.

THE THREE CLASSES (mechanical, fail-closed).
  PERFORMANCE — the value changes how FAST or how CONCURRENTLY work runs, and can never change
                whether it passes: parallelism, poll intervals, batch/page sizes, heartbeat cadence.
  BINDING     — a LOCATOR the operator declares: WHICH external tool runs on THIS machine
                (SPEC-0202 rule 1). It is neither cadence nor a threshold a refusal reads — it
                changes WHO judges, never whether a judged thing passes. A CLOSED, enumerated set:
                `auditor.<tier>.provider|binary|home|model` for tier `routine` | `full`, and nothing
                else. Anything else under `auditor.*` — `auditor.routine.effort` included — is
                unclassified and therefore GATE.
  GATE        — the value participates in a pass/fail verdict: a verify/test timeout whose expiry
                aborts a land, an audit timeout, any threshold a refusal reads.
Classification is FAIL-CLOSED: anything that cannot be confidently classified is GATE. That is why
the four dynamic PREFIX stems (`YITC_AUDIT_`, `YITC_CLI__`, `YITC_RUNNER__`, `YITC_EXPECTED`) are
GATE — a stem names an OPEN family, so it cannot be classified at all, and the fail-closed reading is
the only honest one.

WHY GATE-CLASS IS REFUSED HARD. A gate-class value in a machine file would make a VERDICT
machine-dependent: the same branch would pass on one host and abort on another, and the abort would
be attributable to a file nobody read. SPEC-0132 forbids exactly that (a gate may not become load- or
machine-dependent), and the owner directive of 2026-09-02 makes the refusal HARD — no bypass flag, no
environment escape. Changing a gate-class value stays what it always was: a TASK, with a lifecycle and
an audit. The refusal therefore lives on BOTH sides of the file: `set_value` refuses to WRITE a
gate-class key, and `load`/`get_value` DROP one that reached the file some other way (a hand edit).
The BINDING class does not touch that refusal at all: it widens WHAT MAY BE WRITTEN by exactly eight
enumerated keys, and leaves every gate-class key refused on both sides.
A one-sided refusal would be theatre — the write path is not the only door (see ENTRYPOINTS).

WHERE THE FILE LIVES. Outside any repo checkout, for the same reason the shared coordination store is
(`cross.resolve_log_path`): it belongs to the machine, not to a repo — so editing it is not a repo
write and needs no worktree, no land and no lifecycle. The resolution SHAPE is copied from that
precedent (one resolution site; an env override that wins, realpath'd; otherwise a default). Its
DEFECT is deliberately NOT copied: `cross.CANONICAL_LOG_PATH` is a literal host path, and minting a
SECOND host literal here would double a wrong that is already tracked elsewhere. Instead the default
is DERIVED from that one already-governed out-of-repo location — the settings file is the sibling of
the coordination store — so it inherits its placement decision and its `YITC_CROSS_LOG` override
without restating either.

ABSENT-FILE BEHAVIOUR. A missing, unreadable or malformed file yields NO overrides at all: every
reader falls back to its built-in default. The file is an OVERRIDE LAYER, never a prerequisite — no
verb may start to require it.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# ── Classes ───────────────────────────────────────────────────────────────────────────────────
PERFORMANCE = "performance"
BINDING = "binding"                    # SPEC-0202 rule 1 — a machine-declared LOCATOR
GATE = "gate"

MACHINE_SETTINGS_ENV = "YITC_MACHINE_SETTINGS"
SETTINGS_FILENAME = "machine-settings.json"


class SettingsRefused(Exception):
    """A `config set` refusal — raised for an unknown key, a gate-class key, or a bad value."""


class Knob:
    """One runtime tunable: its name, its CLASS, and enough to validate a value for it.

    `name` is the machine-file KEY: the environment variable's own name for an env knob, and
    `module.SYMBOL` for a hardcoded constant of the same nature (those are inventoried too — the card
    asks for the tunables, not merely the env-readable ones).

    `bounds` is an OPTIONAL inclusive `(lo, hi)` a numeric knob's value must fall within, or None
    (every knob that does not declare one — so no existing knob's behaviour moves). It exists so a
    knob whose READ SITE ignores out-of-range values does not also have a SETTER that happily stores
    them: without it, `config set` would persist and `config list` would display a number nobody
    reads, which is exactly the shape rule 4's drop-side exists to prevent (T-12224, audit-pre
    finding 1). It is an EXTENSION of the one validator `coerce` already is, not a second validation
    path — and it does not reach the environment layer, which never passes through `coerce` at all
    (rule 7 makes env the top layer), so a read site declaring a range still keeps its own check.
    """

    __slots__ = ("name", "cls", "kind", "default", "read_site", "why", "bounds")

    def __init__(self, name, cls, kind, default, read_site, why, bounds=None):
        self.name, self.cls, self.kind = name, cls, kind
        self.default, self.read_site, self.why = default, read_site, why
        self.bounds = bounds

    @property
    def is_performance(self) -> bool:
        return self.cls == PERFORMANCE

    @property
    def is_settable(self) -> bool:
        """May this knob live in the machine file at all? PERFORMANCE and BINDING may; GATE never
        may (SPEC-0193 rule 3, as amended by SPEC-0202 rule 1). Deliberately a SECOND property rather
        than a widened `is_performance`: the class question «is this a cadence value» is asked by
        read sites and by tests that pin a knob's classification, and answering it `True` for a
        binding locator would quietly make those claims false."""
        return self.cls in (PERFORMANCE, BINDING)


def _p(name, kind, default, read_site, why, bounds=None):
    return Knob(name, PERFORMANCE, kind, default, read_site, why, bounds)


def _b(name, read_site, why):
    """A BINDING-class locator. Always a string, and its default is ALWAYS the empty string —
    «nothing bound on this machine» — because the fallback for an unbound locator is the
    resolution order at the read site (env → this file → PATH → repo config), never a value
    restated here."""
    return Knob(name, BINDING, "str", "", read_site, why)


def _g(name, kind, default, read_site, why):
    return Knob(name, GATE, kind, default, read_site, why)


# ── THE INVENTORY ─────────────────────────────────────────────────────────────────────────────
# Every runtime tunable, each with exactly one class. Kept SORTED by name so a new entry lands in an
# obvious place and a diff reads as one line. `tests/test_config_inventory.py` asserts the RULE —
# every `YITC_*` name reachable in bin/ appears here — so an unlisted knob is a red, not a silence.
INVENTORY: "tuple[Knob, ...]" = (
    # ---- BINDING: WHICH external auditor this machine runs (SPEC-0202 rule 1). Exactly these
    # EIGHT keys — four per tier — and no more: the class is a CLOSED enumeration, so every other
    # `auditor.*` name (`auditor.routine.effort` included) stays unclassified and is therefore GATE,
    # refused by `set_value` and dropped on read exactly as before. These are LOCATORS: they decide
    # WHO judges, never whether a judged thing passes, which is why they may be machine-scoped at all
    # while a gate value may not (SPEC-0132). Measured need: T-12176's pre-claim refusal (2026-09-06)
    # found the auditor binary GATE-class, so binding an auditor per machine was impossible without
    # this class. The READ SITES named below are wired by the sibling card T-12350 — this card adds
    # the class and the settable surface only, so a listed read site is where the value is CONSUMED
    # once that card lands, not a claim that it is consumed today.
    _b("auditor.full.binary", "bin/lib/audit.py#resolve_codex_binary",
       "the full-tier auditor CLI's path on THIS machine — a locator, not a threshold"),
    _b("auditor.full.home", "bin/lib/audit.py#resolve_codex_binary",
       "the full-tier auditor provider's auth/config HOME dir on THIS machine — a locator"),
    _b("auditor.full.model", "bin/lib/audit.py#resolve_audit_provider",
       "the full-tier auditor's model id. In the binding because an adopter on a non-default "
       "provider must be able to name one without editing the engine tree (a tracked-file edit is "
       "refused by `release verify`, T-12174); honest because every verdict STAMPS the model that "
       "ran (SPEC-0202 rule 2a) and a bound-vs-default difference is named at session start (2b)"),
    _b("auditor.full.provider", "bin/lib/audit.py#resolve_audit_provider",
       "WHICH adapter judges at full tier on THIS machine — an adapter name the registry knows "
       "(SPEC-0036 §Auditor selection / bin/audit-config.yaml); a locator, not a verdict input"),
    _b("auditor.routine.binary", "bin/lib/audit.py#resolve_codex_binary",
       "the routine-tier auditor CLI's path on THIS machine — a locator, not a threshold"),
    _b("auditor.routine.home", "bin/lib/audit.py#resolve_codex_binary",
       "the routine-tier auditor provider's auth/config HOME dir on THIS machine — a locator"),
    _b("auditor.routine.model", "bin/lib/audit.py#resolve_audit_provider",
       "the routine-tier auditor's model id — admitted into the binding under the same two guards "
       "as its full-tier twin (SPEC-0202 rule 2: the verdict stamp + the session-start naming)"),
    _b("auditor.routine.provider", "bin/lib/audit.py#resolve_audit_provider",
       "WHICH adapter judges at routine tier on THIS machine — an adapter name the registry knows "
       "(SPEC-0036 §Auditor selection / bin/audit-config.yaml); a locator, not a verdict input"),

    # ---- PERFORMANCE: cadence + concurrency only. Nothing here can flip a verdict. ----
    _p("YITC_AUDIT_HEARTBEAT_SECS", "float", 20.0, "bin/lib/audit.py#_audit_heartbeat_interval",
       "seconds between dispatched-worker audit progress heartbeats — an EMIT cadence; the audit "
       "verdict is computed by the auditor and is untouched by how often progress is printed"),
    _p("YITC_GC_LOOSE_THRESHOLD", "int", 256, "bin/git-maintenance.sh",
       "loose-object count above which maintenance repacks — how often housekeeping runs, never "
       "whether any check passes"),
    _p("YITC_VENUE_MAX_REQUESTS", "int", 1, "bin/lib/remote_verify.py#venue_max_requests",
       "the MACHINE-WIDE cap on how many verify REQUESTS are admitted to the venue box at once "
       "(SPEC-0203 rule 4, T-12241). THE UNIT IS THE REQUEST, NEVER THE LEG: one land is cand + "
       "pinned = 2 leases, and both legs of one request are admitted TOGETHER and never wait on "
       "each other. It bounds the axis nothing else does — the land reservation and the SPEC-0132 "
       "slot pool are BOTH keyed per repo (`_verify_slot_dir` hashes realpath(main_wt)), so neither "
       "sees a second checkout landing onto the same box. PERFORMANCE: it changes WHEN a pass is "
       "admitted, never which files run or how they conclude. THE FAIL-SAFE DIRECTION IS INVERTED "
       "relative to YITC_VERIFY_WORKERS, deliberately: there a malformed value is ignored so it "
       "cannot UNBOUND the width, here a blank / non-numeric / non-positive value falls back to the "
       "BUILT-IN 1, so a malformed value can never DISABLE the cap. Admissible 1..4, declared at "
       "both doors since T-12261: the floor is 1 because 0 would admit nothing rather than "
       "serialize harder, and the ceiling is 4 because the unit is the REQUEST and one land is two "
       "legs — at 4 the box already carries up to 8 full-width verify legs, and the owner's "
       "standing shape for this knob points the other way entirely (serialize at 1 rather than "
       "shrink the per-leg width, directive 2026-09-07T14:46:36Z), so a higher number is a typo "
       "rather than a policy",
       bounds=(1, 4)),
    _g("YITC_VENUE_RECORD", "str", None, "bin/lib/venue.py#resolve_record_path",
       "WHICH verify-venue record is read/written (SPEC-0203 rule 1) — a placement/identity input of "
       "exactly the same nature as YITC_MACHINE_SETTINGS, whose sibling file it is. GATE because the "
       "record decides WHERE a kernel verify pass executes, and rule 7 forbids a silent local "
       "fallback: pointing it at another file changes which box a verdict came from"),
    _p("YITC_VENUE_STAGE6_NICE", "int", 19, "bin/lib/remote_verify.py#venue_stage6_nice",
       "the box-side scheduler nice a LOWER-PRIORITY (Stage-6, `task test --run`) venue pass runs "
       "its runner at (SPEC-0203 rule 5's lower-priority arm, T-12218). The default 19 is the "
       "minimum priority: such a pass receives CPU only when the land legs leave it idle, because "
       "`land` is the box's primary client and a background worker's suite can wait. A LAND leg is "
       "NOT tunable and never reaches this read site — its 0 is a literal at the route seam. "
       "Admissible 1..19; anything else is ignored and the default stands. PERFORMANCE: it changes "
       "how fast a Stage-6 pass finishes, never which files run or how they conclude — the verdict "
       "is the envelope's, and the leg records `nice_in_effect` so the priority is measured. The "
       "1..19 band this row already described is ENFORCED at the setter door since T-12261 — before "
       "that, `config set` stored a 25 the resolver ignored. The floor is 1, not 0, on two grounds "
       "that agree: 0 is the LAND leg's priority, so admitting it would let a knob erase the "
       "ordering this arm exists to create, and `coerce` refuses any numeric knob <= 0 anyway",
       bounds=(1, 19)),
    _p("YITC_VENUE_STAGE6_MAX_CONCURRENT", "int", 4,
       "bin/lib/remote_verify.py#venue_stage6_max_concurrent",
       "how many LOWER-PRIORITY (Stage-6, `task test --run`) venue passes may hold the box at once "
       "(SPEC-0203 rule 4's by-class admission, T-12259). THE STAGE-6 HALF ONLY: a LAND is admitted "
       "by YITC_VENUE_MAX_REQUESTS, which stays the sole carrier of the land cap — there is "
       "deliberately no second land cap to keep in step with it. The default 4 is the owner's figure "
       "and the measurement behind it: a Stage-6 pass runs on HALF the derived width (12 of 48 cores "
       "on ccx63) at nice 19 and alone moves load1 to 1-11, so four fit inside the box a single land "
       "peaks at 25-45 for two or three minutes. Admissible 1..16 — 0 would DISABLE Stage-6 "
       "admission rather than slow it, and past 16 the headroom test does all the work anyway; "
       "anything else is ignored and the default stands. PERFORMANCE: it changes WHEN a Stage-6 pass "
       "is admitted, never which files run or how they conclude",
       bounds=(1, 16)),
    _p("YITC_VENUE_STAGE6_HEADROOM_LOAD1", "float", 36.0,
       "bin/lib/remote_verify.py#venue_stage6_headroom_load1",
       "the box load1 a LOWER-PRIORITY (Stage-6) venue pass must be BELOW to be admitted (SPEC-0203 "
       "rule 4, T-12259). It is the SECOND half of the Stage-6 question and both halves are needed: "
       "the concurrency count alone would admit four passes onto a box a land is already saturating, "
       "the headroom alone would admit an unbounded number onto an idle one. UNSET, IT IS DERIVED "
       "rather than assumed — `cores - cores//4` from the fingerprint of the box the pass was routed "
       "to (the rule-5 width cap is cores//legs and the Stage-6 arm halves it again, so cores//4 is "
       "the width one Stage-6 pass occupies), which on the 48-core box is 48-12 = 36; the 36.0 "
       "recorded here is that same figure as the built-in for the case where no fingerprint is "
       "available. Admissible 1.0..1024.0 — at or below one runnable process nothing would ever be "
       "admitted, and above the ceiling is a typo rather than a policy; anything else is ignored and "
       "the derivation stands. PERFORMANCE: it changes WHEN a Stage-6 pass is admitted, never which "
       "files run or how they conclude",
       bounds=(1.0, 1024.0)),
    _p("YITC_VENUE_STAGE6_WORKERS_FRACTION", "float", 0.5,
       "bin/lib/remote_verify.py#venue_stage6_workers_fraction",
       "the fraction of the DERIVED remote width a LOWER-PRIORITY (Stage-6, `task test --run`) venue "
       "pass runs at (SPEC-0203 rule 5's lower-priority arm, T-12261). It is the WIDTH half of that "
       "arm; YITC_VENUE_STAGE6_NICE is the PRIORITY half, and until this card only the priority half "
       "was tunable — the width was the literal `// 2` at the route seam. THE DEFAULT 0.5 IS THAT "
       "LITERAL, so an unset machine derives the same width it always did, and the identity is "
       "arithmetic rather than a hope: 0.5 is exactly representable in binary and W*0.5 is exact for "
       "every W the venue can derive, so int(W*0.5) == W//2 for every reachable W. THE MEASUREMENT "
       "BEHIND THE HALF: a Stage-6 pass at half the derived width — 12 of the 48 cores on ccx63 — at "
       "nice 19 moves the box's load1 to 1-11 on its own, which is what makes four of them fit "
       "inside the box a single land peaks at 25-45 on; both YITC_VENUE_STAGE6_MAX_CONCURRENT's "
       "default of 4 and the `cores - cores//4` headroom derivation are computed FROM that half, "
       "which is exactly why it belongs here rather than in an expression. A LAND leg is NOT tunable "
       "by it and never reaches the read site: it takes the full derived W. Admissible (0, 1] — "
       "declared as the inclusive pair 0.0..1.0 because `coerce` already refuses any numeric knob "
       "<= 0 BEFORE the bounds test, so the pair IS the exclusive-at-zero interval and no second "
       "validation path is added for it; above 1 a Stage-6 pass would be asking for MORE width than "
       "the land it must yield to. PERFORMANCE: it changes how fast a Stage-6 pass finishes, never "
       "which files run or how they conclude — the leg records the width it actually ran at",
       bounds=(0.0, 1.0)),
    _p("YITC_VERIFY_WORKER_NICE", "int", 19, "bin/lib/verify_runner.py#_verify_child_nice",
       "the scheduler nice a DISPATCHED WORKER's per-file test child is spawned at on the LOCAL host "
       "(T-12224). The default 19 is the minimum priority: such a child receives CPU only when the "
       "land verifies leave it idle, because `land` is what the system's throughput rides on and a "
       "background worker's Stage-6 suite can wait. THE PAIR — one owner directive, two hosts: this "
       "is the LOCAL key, its box-side twin is YITC_VENUE_STAGE6_NICE. A LAND leg is NOT tunable by "
       "either and never reaches this read site: it declares itself and returns 0 unconditionally. "
       "Admissible 1..19 at BOTH doors — declared here so `config set` refuses exactly what the "
       "resolver would ignore. PERFORMANCE: it changes how fast a worker's Stage-6 finishes, never "
       "which files run or how they conclude",
       bounds=(1, 19)),
    _p("YITC_VERIFY_RETRY_MAX_FILES", "int", 3,
       "bin/lib/verify_runner.py#_verify_retry_max_files",
       "how many failing files a land-verify leg may re-run ONCE in isolation before it stops "
       "trying and aborts as it always did (T-12357). When a leg stops on failures and the failing "
       "set is within this bound, each named file is re-run alone in a single subprocess outside "
       "the contended pool, on the SAME tree; ALL pass -> the leg resumes over its not-yet-run "
       "files, ANY fails -> the abort is unchanged. THE DEFAULT 3 IS A MEASURED DATUM, not a "
       "hypothesis: over the 14 days to 2026-09-10 this repo took 224 verify-failed land aborts and "
       "186 of them (83%) named at most three files. Admissible 0..20 — 0 DISABLES the retry "
       "entirely and is a real setting rather than a degenerate one, and past 20 a leg would be "
       "re-running a set large enough that the pool is not what is wrong; anything else is ignored "
       "and the default stands. PERFORMANCE: it changes how many load-only flakes a leg absorbs "
       "before giving up, never which files run or how they conclude — a file is cleared ONLY by "
       "PASSING in isolation, so no value here can admit a failing check",
       bounds=(0, 20)),
    _p("YITC_LAND_TAIL_TRIPWIRE_BUDGET_S", "int", 120,
       "bin/lib/worktree.py#_land_tail_tripwire_budget_s",
       "the WALL BUDGET, in seconds, for ONE post-ff tail writer's admission run — the tests that "
       "READ what the writer wrote, run in parallel on the written tree before the bookkeeping "
       "commit (SPEC-0188 rule 7, T-12420). Over the budget the write is WITHHELD and re-derived by "
       "the next land, never committed unproven. THE DEFAULT 120 IS MEASURED: on this repo the two "
       "governed writers' derived reader sets run ~11.4s (the load-sensitive lane's 5) and ~13.3s "
       "(the duration table's 13) in parallel on a 48-core venue, so 120 is ~9x the observed worst "
       "case — wide enough that the budget expires only on a genuinely stuck reader. Admissible "
       "10..900; anything else is ignored and the default stands. THERE IS DELIBERATELY NO DISABLE "
       "VALUE: this is a fail-closed admission gate, and a knob that turned it off would be a hole "
       "in it. The budget is also the DEADLOCK BOUND — the run happens inside the land's ff lock, "
       "so a reader that hangs against that lock expires into a withhold rather than wedging it. "
       "SAFETY-NEUTRAL: no value can admit a write whose readers failed, only change how long a "
       "slow reader is given before its write is withheld",
       bounds=(10, 900)),
    _p("YITC_FLAKY_SENSITIVE_ENTER", "int", 3,
       "bin/lib/worktree.py#_flaky_sensitive_enter",
       "how many ISOLATED-PASS `flaky_retry` rows a test file needs inside the window for `land` to "
       "ENTER it automatically into the declared load-sensitive set `tests/load-sensitive.txt` "
       "(T-12358). A listed file is excluded from the concurrent verify pool and runs AFTER it, one "
       "at a time, on both legs; its pass or fail decides the verdict exactly as a pool result does. "
       "THE DEFAULT 3 IS A MEASURED DATUM, not a hypothesis: over the 14 days to 2026-09-10 this "
       "repo's journal held 22 files that failed >= 5 times against 126 that failed exactly once, so "
       "3 separates the recidivists from the one-offs with room on both sides. Admissible 1..100 — "
       "0 would enter every file on its first flake, which is the owner's stated concern («will all "
       "tests become sensitive»), and past 100 no file would ever enter; anything else is ignored "
       "and the default stands. PERFORMANCE: it changes WHERE a file runs, never WHETHER its verdict "
       "counts — no value can admit a failing check or excuse a file from the verdict. EXIT is never "
       "automatic at any value: a line leaves the carrier only by a card",
       bounds=(1, 100)),
    _p("YITC_FLAKY_SENSITIVE_WINDOW_DAYS", "int", 14,
       "bin/lib/worktree.py#_flaky_sensitive_window_days",
       "the window, in days back from the landing moment, over which `land` folds isolated-pass "
       "`flaky_retry` rows per file to decide automatic ENTRY into the declared load-sensitive set "
       "(T-12358) — the other half of YITC_FLAKY_SENSITIVE_ENTER's question. THE DEFAULT 14 IS THE "
       "WINDOW THE SEEDING FOLD WAS MEASURED OVER (22 recidivists >= 5 in 14 d vs 126 one-offs), so "
       "the two defaults describe one measurement. Admissible 1..365 — below a day the fold sees at "
       "most one land, above a year it is no longer a window; anything else is ignored and the "
       "default stands. PERFORMANCE on the same terms as its sibling: it changes WHERE a file runs, "
       "never whether its verdict counts",
       bounds=(1, 365)),
    _p("YITC_VERIFY_HEARTBEAT_SECS", "float", 20.0,
       "bin/lib/verify_runner.py#_verify_heartbeat_interval",
       "seconds between land-verify progress heartbeats — an EMIT cadence on stderr; the verify "
       "VERDICT, its per-file timeout and the SPEC-0077 gate are all untouched (T-9601). THE WIRED "
       "READ SITE (AC4): env > machine file > built-in default"),
    _p("YITC_VERIFY_WORKERS", "int", None, "bin/lib/remote_verify.py#remote_workers_override",
       "the OVERRIDE CEILING on the DERIVED REMOTE verify width (SPEC-0203 rule 5, T-12195). The "
       "venue derives W per pass from the duration table and the box's cores; this only ever LOWERS "
       "it. REMOTE-ONLY BY DESIGN: the local width stays the code constant _VERIFY_WORKER_CEILING, "
       "because a second LOCAL knob would make the shared host's width machine-dependent. (Until "
       "T-12195 this row named a read site in bin/lib/worktree.py that never existed — the card that "
       "was to build it, T-11436, is wont-do — so it read nowhere: T-12183 F2.) PERFORMANCE: it "
       "changes how fast the suite finishes, not which files it runs or how they conclude. "
       "Admissible 1..1024 since T-12261, and the CEILING IS DELIBERATELY STATIC AND "
       "MACHINE-INDEPENDENT rather than the box's core count: the per-box cap already lives one "
       "layer down in `derive_remote_w` as `cores // legs`, and this override is applied there as "
       "`if override < workers` — it only ever LOWERS, so any value above the box's own cap is "
       "INERT BY CONSTRUCTION and no band here could add a bound the derivation does not already "
       "enforce. The floor 1 is exactly what the read site enforces today (a non-positive value "
       "resolves to None, and `coerce` refuses <= 0), so the doors already agreed there; the "
       "ceiling exists to refuse a typo, not to restate the cap. No resolver-side range is added "
       "for the same reason — it would be a behaviour change bought for nothing",
       bounds=(1, 1024)),
    _p("lib.audit.AUDIT_HEARTBEAT_DEFAULT_SECS", "float", 20.0, "bin/lib/audit.py",
       "the built-in default behind YITC_AUDIT_HEARTBEAT_SECS — same cadence nature"),
    _p("lib.audit.AUDIT_INSPECTION_TIMEOUT_SECONDS", "int", 540,
       "bin/lib/audit.py#_audit_timeout_seconds",
       "T-12233 — the INSPECTION-class (consult / adhoc) auditor wall-clock budget in seconds. "
       "PERFORMANCE only BECAUSE of the same card's SPEC-0200 no-answer case: the expiry of THIS "
       "budget now produces NO verdict, NO round, NO resolution and NO episode terminal — the round "
       "is recorded `outcome: no-answer` and the episode stays open and re-runnable — so the value "
       "changes how long the auditor may think and nothing about what passes. Rule 2's operative "
       "test («does the value participate in a pass/fail verdict?») is what this row answers; the "
       "rule's illustrative «an audit timeout» example was written against the pre-T-12233 world "
       "where a timeout WAS folded as a malformed response and could end an episode. DELIBERATELY "
       "NOT REGISTERED beside it: AUDIT_TIMEOUT_SECONDS (the 300s Stage-4/8 + plan-gate GATE budget) "
       "and the env YITC_AUDIT_TIMEOUT_SECONDS, which spans BOTH classes and therefore stays GATE — "
       "registering either would make a GATE audit machine-dependent (SPEC-0132). Measured need: "
       "T-12220, 2026-09-07, where the hand `YITC_AUDIT_TIMEOUT_SECONDS=1200` env dance was the only "
       "reachable lever and its expiry still ended the episode"),
    _p("lib.audit.CONSULT_PACKET_MAX_BYTES", "int", 450_000,
       "bin/lib/audit.py#consult_packet_max_bytes",
       "T-12233 — the byte bound on an ASSEMBLED consult packet. It is a SOFT, RECORDED target and "
       "by construction cannot change what the auditor is asked to judge: over the bound at a RETEST "
       "it chooses the DELTA SINCE THE BASELINE REVISION instead of the full subject diff — the two "
       "admit the SAME judgement by SPEC-0200 rule 4's own terms, since a retest judges only the "
       "open blocking ids and regressions the fix introduced, and rule 4 forbids a whole-subject "
       "survey there — and when the packet is STILL over the bound it is sent WHOLE and UNTRUNCATED "
       "with `packet_over_bound: true` and the measured size recorded. It NEVER truncates and NEVER "
       "refuses a round, which is exactly what keeps it out of GATE. DELIBERATELY NOT REACHED BY IT: "
       "the pre-existing AUDIT_MAX_DIFF_LINES / AUDIT_MAX_DIFF_BYTES diff truncation stays an "
       "unregistered CODE CONSTANT, so no `config set` on any machine can change what an auditor "
       "sees. Authority: owner_directive events.jsonl#ts=2026-09-07T23:44:44Z (OPTION A)"),
    _p("lib.journal.MAX_FLEET_WIDTH", "int", 8, "bin/lib/journal.py#dispatch_readiness_report",
       "T-12219 — the per-SERVER owner bound on concurrent workers. PERFORMANCE and unusually "
       "clearly so: SPEC-0133 §6 forbids it from EVER clamping `recommended_wave_ceiling` («never a "
       "coded cap»), so by its own governing rule it can decide nothing — the printers echo it as a "
       "SUGGESTED bound the controller judges against. It is per-server by definition, which is "
       "exactly what the machine file is for"),
    _p("lib.nightly.VENUE_IDLE_BUFFER_MIN", "float", 15.0,
       "bin/lib/nightly.py#venue_idle_report",
       "T-12219 — how long every repo on this machine must have NO in-progress task before the "
       "compute-controller session unpublishes and deletes the box. SPEC-0203 rule 6 and its "
       "§Parameters ALREADY name this a machine-scoped performance tunable under `config`; it had "
       "never been registered, so the spec described a knob that did not exist. It changes when an "
       "IDLE box is torn down — never whether any pass concludes"),
    _p("lib.nightly._QUIET_LANE_RETRY_INTERVAL", "int", 60,
       "bin/lib/nightly.py#_quiet_lane_measure",
       "T-12219 — seconds between quiet-lane retries while waiting for enough free slots. A retry "
       "CADENCE inside a window bounded separately by _QUIET_LANE_RETRY_WINDOW (gate): it changes "
       "WHEN an attempt is made, never what the attempt concludes"),
    _p("lib.remote_verify.REMOTE_VERIFY_WORKERS", "int", 24,
       "bin/lib/remote_verify.py#remote_workers_cap",
       "T-12219 — the remote verify WIDTH fallback/cap. The operator OVERRIDE over this value "
       "(YITC_VERIFY_WORKERS) has been performance-registered since T-12195; this is the half of "
       "that pair that was left in code, so a machine could lower the width but not raise its own "
       "baseline. Parallelism changes how fast the suite finishes, not which files it runs or how "
       "they conclude — the same reading its own override row already carries"),
    _p("lib.venue.WAIT_READY_INTERVAL", "int", 5, "bin/lib/venue.py#wait_ready",
       "T-12219 — how often `venue raise` re-probes a booting box for ssh. Pure latency: the "
       "readiness VERDICT is the probe itself, and the bound on waiting is the separate "
       "WAIT_READY_TIMEOUT, which stays GATE"),
    _p("lib.verify_runner._ADMISSION_POLL_SEC", "float", 1.0, "bin/lib/worktree.py",
       "how often a blocked land re-tests for a freed verify-admission slot — pure latency; the "
       "admission DECISION is the flock, not the poll"),
    _p("lib.worktree._LAND_BACKOFF_CAP_SECONDS", "float", 3.0,
       "bin/lib/worktree.py#_land_retry_backoff",
       "T-12219 — the CAP on the ff-race retry backoff: how long a land that lost the race sleeps "
       "before retrying. The retry COUNT (_LAND_MAX_RETRIES) is what decides whether the land "
       "eventually gives up and is GATE; this only spaces the attempts out"),
    _p("lib.worktree._LAND_RESERVATION_POLL_SEC", "float", 0.1, "bin/lib/worktree.py",
       "how often a land re-tests for a freed reservation — pure latency, same nature as the "
       "admission poll (the two cadences are deliberately divergent; T-11275)"),
    _p("lib.worktree._LIVENESS_WATCHDOG_POLL_SECS", "float", 5.0,
       "bin/lib/worktree.py#_land_liveness_watchdog",
       "T-12219 — how often the SPEC-0180 held-turn liveness watchdog re-tests its subject. Pure "
       "latency; the watchdog's VERDICT is `kill -0` on the claimed pid, not the interval it asks "
       "at"),
    _p("lib.worktree._VERIFY_HEARTBEAT_DEFAULT_SECS", "float", 20.0, "bin/lib/worktree.py",
       "the built-in default behind YITC_VERIFY_HEARTBEAT_SECS — same cadence nature"),

    # ---- GATE: everything else. Unclassifiable is GATE by construction, not by omission. ----

    # ---- GATE: everything else. Unclassifiable is GATE by construction, not by omission. ----
    _g("YITC_ACTOR", "str", None, "bin/lib/grants.py",
       "actor provenance — the identity a governed refusal reads (SPEC-0169)"),
    _g("YITC_ADHOC_PAYLOAD_WARN_BYTES", "int", None, "bin/lib/audit.py",
       "a THRESHOLD a report reads; a threshold is gate-shaped even when its current use is a WARN"),
    _g("YITC_ALLOW_MAIN_WRITE", "str", None, "bin/lib/worktree_lifecycle.py",
       "the worktree-before-write guard's escape hatch — a refusal switch"),
    _g("YITC_AS_USER", "str", None, "bin/lib/grants.py", "identity input to the grants check"),
    _g("YITC_AUDIT_", "str", None, "bin/lib/verify_runner.py",
       "a dynamic PREFIX STEM naming an OPEN family — unclassifiable, therefore GATE (fail-closed)"),
    _g("YITC_AUDIT_EFFORT", "str", None, "bin/lib/audit.py",
       "selects the auditor's effort tier — changes what the audit CONCLUDES"),
    _g("YITC_AUDIT_MODEL", "str", None, "bin/lib/audit.py",
       "selects the auditing model — changes what the audit CONCLUDES"),
    _g("YITC_AUDIT_PROVIDER", "str", None, "bin/lib/audit.py",
       "selects the auditor — changes what the audit CONCLUDES"),
    _g("YITC_AUDIT_TIMEOUT_SECONDS", "int", 300, "bin/lib/audit.py",
       "the card's own named example: expiry ABORTS the audit, so the value participates in the "
       "verdict"),
    _g("YITC_CANARY_RUN", "str", None, "bin/lib/cli.py", "opt-in gate for the canary test arm"),
    _g("YITC_CLI__", "str", None, "bin/lib/graph.py",
       "a dynamic PREFIX STEM (render token family) — unclassifiable, therefore GATE"),
    _g("YITC_CODEX_AUDIT_BIN", "str", None, "bin/lib/audit.py",
       "which auditor binary runs — a refuse-before-spawn input"),
    _g("YITC_CODEX_WORKER_BIN", "str", None, "bin/lib/audit.py",
       "which worker binary runs — a refuse-before-spawn input"),
    _g("YITC_CONVERGENCE_BUDGET_S", "int", 120, "bin/lib/deploy.py",
       "a BUDGET whose exhaustion is a failure verdict"),
    _g("YITC_CORPUS_GUARD_ROOT", "str", None, "bin/lib/state.py",
       "corpus-integrity guard root — a refusal reads it"),
    _g("YITC_CORPUS_ROOT_DEFAULT", "str", None, "bin/lib/state.py",
       "which corpus is read — changes what every governed check sees"),
    _g("YITC_CROSS_BACKUP_DIR", "str", None, "bin/verify-backup.sh",
       "where the backup verification looks — its verdict reads it"),
    _g("YITC_CROSS_BACKUP_RETAIN", "int", 42, "bin/verify-backup.sh",
       "retention count the backup verification asserts against"),
    _g("YITC_CROSS_LOG", "str", None, "bin/lib/cross.py#resolve_log_path",
       "WHICH shared store is read/written — an identity/placement input, not a speed one"),
    _g("YITC_DEBT_ABORT_BREADTH_MIN_BRANCHES", "int", 2, "bin/lib/cli.py",
       "a debt-surfacing FLOOR — a threshold a report's decision reads"),
    _g("YITC_DEBT_ABORT_BREADTH_WINDOW_HOURS", "int", None, "bin/lib/cli.py",
       "a debt reading HORIZON — a threshold"),
    _g("YITC_DEBT_AHEAD_BRANCH_FLOOR_HOURS", "int", None, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_BEHIND_BRANCH_FLOOR_COMMITS", "int", 200, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_BRANCH_BURN_MIN_ATTEMPTS", "int", 4, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_DEAD_LAND_FLOOR_MINUTES", "int", None, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_DISPATCH_MONITOR_FLOOR_MINUTES", "int", 90, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_FOLLOWUP_FLOOR", "int", 5, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_MEASUREMENT_MARGIN", "float", 0.10, "bin/lib/cli.py", "a debt MARGIN threshold"),
    _g("YITC_DEBT_PREQUEUE_REFUSAL_WINDOW_DAYS", "int", None, "bin/lib/cli.py", "a debt HORIZON"),
    _g("YITC_DEBT_SECURITY_FINDING_FLOOR_DAYS", "int", 30, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_TEST_CLASS_STALE_FLOOR_DAYS", "int", 30, "bin/lib/cli.py", "a debt FLOOR"),
    _g("YITC_DEBT_UNCARRIED_P8_WINDOW_HOURS", "int", 168, "bin/lib/cli.py", "a debt HORIZON"),
    _g("YITC_DEPLOY_VERB", "str", None, "bin/lib/deploy.py", "the deploy-run marker a guard reads"),
    _g("YITC_DISPATCH_PROVIDER", "str", "claude", "bin/lib/dispatch.py",
       "which provider a dispatched worker runs on — changes what the work CONCLUDES"),
    _g("YITC_EVENTS_GUARD_ROOT", "str", None, "bin/lib/events.py",
       "journal-write guard root — a refusal reads it"),
    _g("YITC_EVENTS_PATH_DEFAULT", "str", None, "bin/lib/events.py", "WHICH journal is written"),
    _g("YITC_EVENTS_SINK", "str", None, "bin/lib/events.py", "the journal quarantine target"),
    _g("YITC_EXPECTED", "str", None, "bin/lib/plan.py",
       "a PREFIX STEM of the dispatched-worker marker family — unclassifiable, therefore GATE"),
    _g("YITC_EXPECTED_SESSION_REF", "str", None, "bin/lib/plan.py",
       "the dispatched-worker marker an owner-gated refusal reads"),
    _g("YITC_FE_SRC", "str", None, "bin/lib/frontend_errors.py", "a query input, not a cadence"),
    _g("YITC_GC_PRUNE_EXPIRE", "str", "7.days", "bin/git-maintenance.sh",
       "how long unreachable objects survive — DATA RETENTION, not speed"),
    _g("YITC_GRAPH_CACHE", "str", None, "bin/lib/cli.py",
       "looks like speed but is not: the cache decides whether a STALE graph is served, so it can "
       "change what a governed read sees. Fail-closed"),
    _g("YITC_GRAPH_VERBOSE", "str", None, "bin/lib/cli.py",
       "report verbosity — not a cadence/concurrency value, so not PERFORMANCE by the definition"),
    _g("YITC_HOST_LABEL", "str", None, "bin/lib/observe.py", "recorded identity"),
    _g("YITC_IDENTITY", "str", None, "bin/lib/grants.py", "identity input to the grants check"),
    _g("YITC_ID_RESERVATION_DIR", "str", None, "bin/lib/cli.py",
       "where id reservations live — collision-safety, not speed"),
    _g("YITC_INSPECT_SWEEP_PAYLOAD_WARN_BYTES", "int", None, "bin/lib/inspection.py",
       "a THRESHOLD a report reads"),
    _g("YITC_ISOLATED_VERIFY", "str", None, "bin/lib/cli.py", "selects the verify ISOLATION mode"),
    _g("YITC_LAND_HELD_TURN_PID", "str", None, "bin/lib/dispatch.py",
       "the SPEC-0180 held-turn CLAIM, verified server-side — a refusal input"),
    _g("YITC_LAND_KEEP_PROCESS_GROUP", "str", None, "bin/lib/worktree.py",
       "process-group teardown behaviour — a safety switch"),
    _g("YITC_LAND_QUEUED_PREMERGE", "str", None, "bin/lib/worktree.py#_queued_premerge_enabled",
       "`0` disables the T-12150 queued pre-merge AND the step-2 consumption that reads its record — "
       "a behaviour switch, the same nature as YITC_LAND_KEEP_PROCESS_GROUP. GATE rather than "
       "PERFORMANCE because it decides WHETHER a merge conflict is met while the branch is still "
       "queued or first at acquisition, which is what the land's `reservation_disposition` records"),
    _g("YITC_LAND_QUEUED_PREMERGE_MIN_WAIT", "float", 120.0,
       "bin/lib/worktree.py#_queued_premerge_min_wait",
       "the wait a land must already have served before its FIRST queued pre-merge tick. GATE by the "
       "fail-closed rule: the floor exists to leave the SHORT contended wait — the regime where "
       "acquisition ordering is actually in play — byte-identical, so lowering it changes behaviour "
       "in exactly the regime the card deliberately left untouched. A <=0 value falls back to the "
       "default, so the floor cannot be removed"),
    _g("YITC_LAND_QUEUED_PREMERGE_SECS", "float", 120.0,
       "bin/lib/worktree.py#_queued_premerge_interval",
       "seconds between T-12150 queued pre-merge ticks while a land is parked on the reservation. "
       "GATE, not PERFORMANCE, by the same fail-closed reading as its two siblings: the cadence "
       "decides WHETHER a conflict with main is surfaced while the branch is still queued or first "
       "met at acquisition, and that difference is what the land's `reservation_disposition` records "
       "— stretching the interval past a wait suppresses the queued surfacing entirely, so it is not "
       "merely timing. A <=0 or non-numeric value falls back to the default, so it can never be "
       "turned into an unthrottled loop"),
    _g("YITC_LAND_PARK_REQUEUE_MAX", "int", 2, "bin/lib/worktree.py#_land_park_requeue_max",
       "the T-12393 cap on automatic park-bound REQUEUES for one land process. GATE on the SAME "
       "ground as `_LAND_MAX_RETRIES` and as the park limit it extends: the number decides whether "
       "the land eventually gives up and HALTS, which is a verdict, not a cadence"),
    _g("YITC_LAND_RESERVATION_PARK_LIMIT_SECS", "float", None, "bin/lib/worktree.py",
       "the SPEC-0132 park BOUND: expiry degrades the land, so it is a verdict input (and is "
       "explicitly written never to be disableable)"),
    _g("YITC_LOAD_SENSITIVE_MAX_FILES", "int", 25, "bin/lib/debt.py#load_sensitive_max_files",
       "the FILE-COUNT half of the SPEC-0132 §3 serial-lane watch-point as EXTENDED to the declared "
       "load-sensitive lane (T-12360): past this many files in `tests/load-sensitive.txt` the weekly "
       "review must dispose a NAMED global-rework question instead of filing another per-file card. "
       "THE DEFAULT 25 IS NOT A NEW NUMBER — it is the value the watch-point has stated since it was "
       "written («OR 25 files»), reused as-is, which is why this card introduced no hypothesis "
       "figure. GATE-class by the module's fail-closed rule, and deliberately so even though nothing "
       "refuses on it: it is a governance THRESHOLD, and a threshold that read differently per "
       "machine would make the same lane over-bound on one host and clean on another. Admissible "
       "1..1000 — below 1 no lane could ever be under bound, and past 1000 the lane would exceed "
       "this repo's whole recorded corpus; anything else is ignored and the default stands. "
       "REPORT-ONLY: it changes what the weekly review is asked to DISPOSE, never which tests run, "
       "where they run, or how any verdict concludes"),
    _g("YITC_LOAD_SENSITIVE_SHARE_PCT", "int", 10, "bin/lib/debt.py#load_sensitive_share_pct",
       "the SHARE-OF-VERIFY-WALL half of the same extended watch-point (T-12360), in percent of the "
       "duration table's own total per-file work (T-11316): past this share the lane's serialized "
       "tail is long enough that the weekly review must dispose the global-rework question. THE "
       "DEFAULT 10 IS LIKEWISE THE WATCH-POINT'S OWN STATED VALUE («exceeds 10% of verify wall "
       "time»), reused rather than re-derived. GATE-class on the same reading as its sibling above. "
       "Admissible 1..100 — 0 would report every non-empty lane as over bound and past 100 no lane "
       "could be; anything else is ignored and the default stands. REPORT-ONLY on the same terms",
       ),
    _g("YITC_MACHINE_SETTINGS", "str", None, "bin/lib/machine_settings.py#resolve_settings_path",
       "WHICH machine settings file is read/written — a placement/identity input, the same nature as "
       "YITC_CROSS_LOG. Pointing it at another file cannot smuggle a gate-class value in: the READ "
       "path drops gate-class keys whatever file they came from"),
    _g("YITC_MAINTENANCE_NO_LOCK", "str", None, "bin/git-maintenance.sh",
       "skips the maintenance reservation — a safety switch"),
    _g("YITC_NIGHTLY_SANDBOX_MIN_AGE_HOURS", "int", None, "bin/lib/nightly.py",
       "an age FLOOR deciding what the nightly sweep DELETES"),
    _g("YITC_NIGHTLY_SANDBOX_PREFIXES", "str", None, "bin/lib/nightly.py",
       "which paths the nightly sweep considers for deletion"),
    _g("YITC_NIGHTLY_SANDBOX_TMP_BASE", "str", None, "bin/lib/nightly.py",
       "where the nightly sweep looks — a deletion input"),
    _g("YITC_PINNED_FIRST", "str", None, "bin/lib/worktree.py",
       "T-12151 — restores the pinned-LAST verify order. GATE, not PERFORMANCE, by the fail-closed "
       "rule: it looks like pure ordering, and it does not change WHICH checks run or the "
       "pass-iff-empty verdict, but it does decide whether a land spends the candidate leg before a "
       "certain pinned refusal — i.e. it changes what a refusing land has actually verified. It "
       "exists as the differential control for tests/test_t12151_pinned_first.py, not as an operator "
       "knob"),
    _g("YITC_PROFILE_SNAPSHOT_TIMEOUT", "int", 60, "bin/security-audit",
       "a TIMEOUT whose expiry is a failure verdict"),
    _g("YITC_REGISTRY", "str", None, "bin/lib/v1_quiesce.py",
       "which registry is read — peer identity + fail-closed membership read it"),
    _g("YITC_REPO_ROOT", "str", None, "bin/lib/nightly.py", "which checkout is operated on"),
    _g("YITC_RUNNER__", "str", None, "bin/lib/init.py",
       "a dynamic PREFIX STEM (render token family) — unclassifiable, therefore GATE"),
    _g("YITC_RUN_AS", "str", None, "bin/lib/grants.py", "identity input to the grants check"),
    _g("YITC_SECURITY_AUDIT_SEAM_BUDGET_S", "int", 600, "bin/lib/deploy.py",
       "a BUDGET whose exhaustion is a failure verdict"),
    _g("YITC_SECURITY_DEP_AUDIT_TIMEOUT", "int", 120, "bin/security-audit",
       "a TIMEOUT whose expiry is a failure verdict"),
    _g("YITC_SECURITY_HOOK_TIMEOUT", "int", 60, "bin/security-audit",
       "a TIMEOUT whose expiry is a failure verdict"),
    _g("YITC_SELECTION_GOVERN", "str", None, "bin/lib/worktree.py",
       "switches the selection governor — a refusal input"),
    _g("YITC_SESSION_REF", "str", None, "bin/lib/rebaseline_currency.py",
       "the session ref carried into provenance and read by currency refusals"),
    _g("YITC_SYNCHRONOUS_LAND", "str", None, "bin/lib/dispatch.py",
       "the synchronous-to-LAND marker a dispatched worker's discipline reads"),
    _g("YITC_TEST_JOURNAL_GUARD", "str", None, "bin/lib/events.py",
       "the live-journal guard set — a refusal reads it"),
    _g("YITC_V2_PATH", "str", None, "bin/lib/verify_runner.py", "which CLI a test invokes"),
    _g("YITC_VENUE_LAND_OVERLAP_FILE", "str", None,
       "bin/lib/verify_runner.py#_run_verify_tests",
       "T-12260 — the venue leg's land-overlap SIDECAR: the file the box leg script writes the "
       "intervals a foreign land-class lease was live into, and the per-file land-verify bound "
       "reads to uncharge itself for that time (SPEC-0071 rule 1 / SPEC-0203 rule 4). It is set "
       "ONLY by the leg script and is unset everywhere else, so an unset value is the ordinary "
       "local land and credits nothing. Classified GATE, fail-closed as the rule requires: it is a "
       "SOURCE the verdict-bearing timeout reads, not a cadence or a worker count — a value "
       "pointing at a file naming intervals that never happened would extend a bound a hang should "
       "have hit, which is exactly the thing a reader must be able to see classified"),
    _g("YITC_VERIFY_QUIET_BARRIER_DIR", "str", None,
       "bin/lib/verify_runner.py#_run_verify_tests",
       "T-12377 — the QUIET-POINT barrier dir the venue leg script exports so a leg's T-12357 "
       "isolated re-run waits until the SIBLING leg's pool has drained (marker `<leg>.pool-drained`). "
       "Set ONLY by the box leg script on a two-leg pass; unset everywhere else = today's retry "
       "ordering. GATE, fail-closed: it decides WHEN a verdict-bearing retry runs, never a cadence"),
    _g("YITC_VERIFY_QUIET_LEG", "str", None, "bin/lib/verify_runner.py#_run_verify_tests",
       "T-12377 — THIS leg's name under the quiet-point barrier (`cand`/`pinned`); set only by the "
       "box leg script beside YITC_VERIFY_QUIET_BARRIER_DIR. GATE, same reasoning"),
    _g("YITC_VERIFY_QUIET_SIBLING", "str", None, "bin/lib/verify_runner.py#_run_verify_tests",
       "T-12377 — the SIBLING leg's name under the quiet-point barrier (names the marker + pidfile "
       "the wait resolves); set only by the box leg script. GATE, same reasoning"),
    _g("YITC_VERIFY_QUIET_SIBLING_PID", "str", None, "bin/lib/verify_runner.py#_run_verify_tests",
       "T-12377 — the sibling leg's pid when the box leg script already knew it (else the runner "
       "reads `<dir>/<sibling>.pid` at wait time); the wait releases when it exits. GATE"),
    _g("YITC_VERIFY_OUTCOMES_DIR", "str", None,
       "bin/lib/verify_runner.py#_per_file_outcomes_export",
       "T-12190 — where the per-file verify OUTCOME sidecar is written (the box-side/executor "
       "override). UNSET, the default is OFF the checkout: `<tempfile.gettempdir()>/"
       "yitc-verify-outcomes/`, which follows the same temp base YITC_VERIFY_TMPDIR moves. It is "
       "deliberately NOT inside the verified tree — an in-tree export is land-blocking dirt in any "
       "repo whose .gitignore does not cover it. The export is report-only "
       "and cannot move a verdict, but this is a DESTINATION, not a cadence or a worker count — and "
       "the classification is fail-closed, so it is GATE: a value pointing the export somewhere "
       "unwritable or shared is a thing a reader must be able to see classified"),
    _g("YITC_VERIFY_TEST_TIMEOUT", "float", 300.0, "bin/lib/cli.py",
       "the card's own named example: expiry ABORTS the land, so the value participates in the "
       "verdict"),
    _g("YITC_VERIFY_TMPDIR", "str", None, "bin/lib/verify_runner.py#_install_verify_tmpdir",
       "T-12185 — relocates the verify run's temp base (e.g. a tmpfs), which BOTH the sandbox "
       "mkdtemp and the SPEC-0132 Rule 1 disk/inode statvfs follow. GATE, not PERFORMANCE, and "
       "therefore NOT settable in the machine settings file: the relocated filesystem is measured by "
       "`_host_resource_headroom`, whose bound REFUSES a land at zero — so the value participates in "
       "an admission verdict. It stays an invocation-scoped env var precisely because a fail-closed "
       "refusal input must not be pinned machine-wide by a settings file"),
    _g("YITC_WATCH_KEEP_PROCESS_GROUP", "str", None, "bin/lib/dispatch.py",
       "process-group teardown behaviour — a safety switch"),
    _g("lib.audit.AUDIT_TIMEOUT_SECONDS", "int", 300, "bin/lib/audit.py",
       "the built-in default behind YITC_AUDIT_TIMEOUT_SECONDS — a verdict input"),
    _g("lib.cli._VERIFY_TEST_TIMEOUT_DEFAULT", "float", 300.0, "bin/lib/cli.py",
       "the built-in default behind YITC_VERIFY_TEST_TIMEOUT — a verdict input"),
    _g("lib.worktree._LAND_RESERVATION_PARK_WALLS", "float", 20.0, "bin/lib/worktree.py",
       "the park bound in units of a verify wall — a SAFETY bound, so a verdict input"),
    _g("lib.worktree._VERIFY_WALL_SECONDS", "float", 448.4, "bin/lib/worktree.py",
       "the verify wall the park bound is expressed in — a verdict input by inheritance. (The "
       "declared default was None until T-12219: gate-class, so nothing was ever settable and no "
       "verdict moved, but `config list` printed a built-in default no unset machine observes. The "
       "T-12219 drift check now asserts every `lib.<module>.<SYMBOL>` default against the live "
       "constant, so this class cannot recur silently.)"),
)

BY_NAME = {k.name: k for k in INVENTORY}


# ── AC3: THE ENTRYPOINT INVENTORY ─────────────────────────────────────────────────────────────
# Stated as an INVENTORY on purpose. Proving that «no bypass EXISTS» is an unfalsifiable universal
# negative; an UNENUMERATED entrypoint, by contrast, is a findable gap. So every supported way to
# reach the setter is DECLARED here as data, and `tests/test_config_verb.py` enumerates this tuple
# and drives each member with a gate-class key. Adding a new door without adding it here is the one
# failure mode this shape is designed to make visible — and a door added here without a refusal reds
# immediately.
ENTRYPOINTS = (
    ("cli", "bin/yitc-v2 config set <key> <value> — the verb"),
    ("api", "lib.machine_settings.set_value(...) — the module API every caller routes through"),
    ("file", "a HAND-EDITED settings file (incl. one selected by $YITC_MACHINE_SETTINGS) — the "
             "READ path drops gate-class keys, so hand-editing one in is not a door either"),
)


# ── Path resolution (the `cross.resolve_log_path` shape; NOT its literal-path defect) ──────────
def resolve_settings_path(env=None) -> Path:
    """The ONE resolution site for the machine settings file.

    `YITC_MACHINE_SETTINGS` (owner-tunable infra config) wins, realpath'd; otherwise the file sits
    beside the shared coordination store, whose out-of-repo placement is already governed
    (SPEC-0084 rule 3). Deriving rather than restating means there is no second host-literal path to
    keep in sync — and the store's own env override is inherited for free.
    """
    env = os.environ if env is None else env
    override = (env.get(MACHINE_SETTINGS_ENV) or "").strip()
    if override:
        return Path(os.path.realpath(override))
    from lib import cross      # deferred: cross pulls in the journal stack; the read path stays cheap
    return Path(cross.resolve_log_path(env)).parent / SETTINGS_FILENAME


# ── Inventory rule check (AC1) ────────────────────────────────────────────────────────────────
def scan_env_knobs(root) -> "set[str]":
    """Every `YITC_*` name that appears anywhere under `root` (the engine's bin/). Text scan on
    purpose: a knob mentioned only in a comment is still a knob somebody will reach for.

    SOURCE only: compiled `__pycache__` artifacts are skipped, because a marshalled constant pool
    concatenates adjacent strings and the scan reads the join as a knob (`YITC_SESSION_REFT`) — a
    phantom name that no source file contains. This module itself is skipped too: it lists every
    knob by construction, so scanning it would make the rule self-satisfying.
    """
    import re
    pat = re.compile(r"YITC_[A-Z0-9_]+")
    found: set[str] = set()
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.name == "machine_settings.py":
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        try:
            found.update(pat.findall(path.read_text(errors="ignore")))
        except OSError:
            continue
    return found


def unlisted_knobs(names) -> "list[str]":
    """The RULE: every knob name is in the inventory. Returns the sorted names that are NOT —
    empty means the rule holds. Pure, so a test can feed it a seeded name and watch it red."""
    return sorted(n for n in names if n not in BY_NAME)


# ── The file: read side ───────────────────────────────────────────────────────────────────────
def _raw_load(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}                      # missing / unreadable / malformed → NO overrides (AC5)
    return data if isinstance(data, dict) else {}


def load(env=None) -> dict:
    """The EFFECTIVE overrides: performance- and binding-class keys only, each coerced to its
    declared type (SPEC-0193 rule 3, as amended by SPEC-0202 rule 1).

    Gate-class and unknown keys present in the file are DROPPED — silently for the reader (whose
    correct behaviour is its built-in default) and visibly for `config list`, which reports them.
    This is the second half of the hard refusal: a hand-edited file is an entrypoint too.
    """
    out = {}
    for key, raw in _raw_load(resolve_settings_path(env)).items():
        knob = BY_NAME.get(key)
        if knob is None or not knob.is_settable:
            continue
        try:
            out[key] = coerce(knob, raw)
        except SettingsRefused:
            continue                   # a malformed value is an absent value, never a crash
    return out


def get_value(name, env=None):
    """The machine-file value for `name`, or None when there is none.

    Returns None for a gate-class or unknown key BY CONSTRUCTION — a read site for a gate-class value
    can therefore never become machine-dependent even if someone wires one up by mistake.
    """
    knob = BY_NAME.get(name)
    if knob is None or not knob.is_settable:
        return None
    return load(env).get(name)


# ── The file: write side ──────────────────────────────────────────────────────────────────────
def coerce(knob: Knob, raw):
    """Validate + convert `raw` for `knob`, or raise SettingsRefused. Numeric knobs must be finite
    and > 0: every numeric performance knob here is a cadence or a worker count, and zero/negative
    would not be a slower engine but a disabled or nonsensical one."""
    try:
        if knob.kind == "int":
            value = int(raw)
        elif knob.kind == "float":
            value = float(raw)
        else:
            value = str(raw)
    except (TypeError, ValueError):
        raise SettingsRefused(f"{knob.name}: expected {knob.kind}, got {raw!r}")
    if knob.kind in ("int", "float"):
        if value != value or value in (float("inf"), float("-inf")):     # NaN / inf
            raise SettingsRefused(f"{knob.name}: {raw!r} is not a finite {knob.kind}")
        if value <= 0:
            raise SettingsRefused(f"{knob.name}: must be > 0 (got {value})")
        if knob.bounds is not None:
            lo, hi = knob.bounds
            if not (lo <= value <= hi):
                raise SettingsRefused(
                    f"{knob.name}: must be within {lo}..{hi} inclusive (got {value}) — the read site "
                    f"IGNORES a value outside that range, so storing this one would put a number in "
                    f"the file that nobody reads")
    return value


def _refuse_gate(name: str) -> None:
    """THE HARD REFUSAL (owner directive 2026-09-02 + SPEC-0132). Deliberately takes no override
    argument: there is no flag and no environment value that reaches this, because a parameter here
    is exactly the second door AC3 exists to keep shut."""
    raise SettingsRefused(
        f"{name} is a GATE-class value and CANNOT be set in the machine settings file — refused.\n"
        f"  WHY: a gate participates in a pass/fail verdict, so putting it here would make that "
        f"verdict machine-dependent (SPEC-0132) — the same branch would pass on one host and abort "
        f"on another, blamed on a file nobody read.\n"
        f"  There is no bypass flag and no environment escape: this refusal is hard by owner "
        f"directive (2026-09-02).\n"
        f"  CHANGING IT IS A TASK: file one (`bin/yitc-v2 task file ...`) so the change gets a "
        f"lifecycle and an audit."
    )


def set_value(name, raw, env=None):
    """Set a PERFORMANCE- or BINDING-class knob in the machine file. Returns (old, new, dropped).

    Refuses — writing NOTHING — an unknown key (rather than storing a typo nobody will ever read)
    and a gate-class key (hard, see `_refuse_gate`). The write is atomic (temp file + replace), so a
    refusal or a crash can never leave a half-written file behind. `dropped` names any inert
    non-settable (gate-class or unknown) keys the write removed (see below).
    """
    knob = BY_NAME.get(name)
    if knob is None:
        raise SettingsRefused(
            f"unknown key {name!r} — not in the tunable inventory, so it would be a value nobody "
            f"reads. `bin/yitc-v2 config list` prints every knob and its class."
        )
    if not knob.is_settable:
        _refuse_gate(name)
    value = coerce(knob, raw)
    path = resolve_settings_path(env)
    data = _raw_load(path)
    old = data.get(name)
    # A governed write LEAVES THE FILE HONEST (audit-pre finding 2). Whatever else the file was
    # carrying — a hand-added gate-class key, a key retired from the inventory — the read path
    # already drops, so keeping it on disk only preserves the illusion that it does something. Drop
    # it here, at the one moment a governed writer has the file open, and report what went. This is
    # not a second refusal: the refusal already fired above; this is the same rule applied to the
    # bytes.
    dropped = sorted(k for k in data
                     if k != name and (k not in BY_NAME or not BY_NAME[k].is_settable))
    data = {k: v for k, v in data.items() if k not in dropped}
    data[name] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".machine-settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return old, value, dropped


def resolve(name, default, env=None):
    """THE READ-SITE RESOLVER for a module-constant tunable (one with no `YITC_*` env twin).

    Returns the machine-file value when one applies, else the CALLER's own `default` — which is
    always the live module constant. Two properties follow, and both are the reason this exists
    beside `effective()` rather than being folded into it (T-12219):

      - THE MODULE CONSTANT STAYS THE LIVE DEFAULT. `effective()` answers from `INVENTORY.default`,
        which is the same number written a second time for `config list` to print. A read site
        answering from THAT would observe the copy, not the constant — so a test that patches the
        constant, and a card that edits it, would both be silently ignored. Here the copy is only
        ever displayed, and `tests/test_system_parameters_inventory.py` asserts the two agree.
      - IT NEVER RAISES. A missing, unreadable or malformed file, an unknown or gate-class name, a
        value that will not coerce — every one of them yields `default`. SPEC-0193 rule 6: the file
        is an OVERRIDE LAYER, never a prerequisite, so no read site may come to require it.

    The ENV layer, where a knob has one, still sits ABOVE this (rule 7) and is applied by the read
    site itself — see `verify_runner._verify_heartbeat_interval`.
    """
    try:
        value = get_value(name, env)
    except Exception:                  # noqa: BLE001 — a settings fault is never a caller's problem
        return default
    return default if value is None else value


def effective(name, env=None):
    """What a reader would see for `name` right now: the machine-file value if one applies, else the
    inventoried built-in default. (The ENV layer sits above both at each read site — see
    `_verify_heartbeat_interval` — and is deliberately not restated here.)"""
    value = get_value(name, env)
    return BY_NAME[name].default if value is None else value
