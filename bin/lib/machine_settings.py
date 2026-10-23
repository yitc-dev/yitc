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
                `auditor.<tier>.provider|binary|home|model|effort|reserve.model|reserve.effort|timeout`
                for tier `routine` | `full`, and nothing else (effort + the reserve PAIR: T-12853, so
                either door switches per machine; `timeout`: T-13205, the bound auditor's wall-clock,
                whose expiry is a no-answer, never a verdict). Anything
                else under `auditor.*` is unclassified and therefore GATE.
  GATE        — the value participates in a pass/fail verdict: a verify/test timeout whose expiry
                aborts a land, an audit timeout's code default and env knob, any threshold a refusal
                reads. (A machine's per-tier `auditor.<tier>.timeout` is BINDING: its expiry is a
                no-answer that yields no verdict — SPEC-0202 rules 1 and 6, T-13205.)
  An ADMISSION value — one that decides only WHEN a governed run may start, e.g. the deploy load
  window (T-13962) — is PERFORMANCE even where its expiry refuses the run, under the three conditions
  SPEC-0193 rule 2 states (no judgement of the subject, nothing started and no row, re-runnable
  unchanged or skipped by a recorded flag). That rule is the home; this is a pointer.
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
The BINDING class does not touch that refusal at all: it widens WHAT MAY BE WRITTEN by exactly sixteen
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

THE TWO OPENED CLASSES (SPEC-1031 rules 2-5, 7; built by T-13966, first keys opened by T-13969). A
key a card OPENS leaves GATE for one of two classes: BUDGET — a wall-clock limit whose expiry ends a
run as stuck, set on the MACHINE (environment > this file > built-in default, settable only with a
declared band, the band checked at set and at file read) — or THRESHOLD — a number a verdict or a
signal compares against that describes the PROJECT, set in the project's `yitc-ops.yaml`
`thresholds:` section and never on the machine (the environment is not read, `set_value` refuses it
and `load` drops it). A key no card opened stays GATE, refused on every door. `in_force` names the
value applied and its source, for a run row or a signal.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# ── Classes ───────────────────────────────────────────────────────────────────────────────────
PERFORMANCE = "performance"
BINDING = "binding"                    # SPEC-0202 rule 1 — a machine-declared LOCATOR
BUDGET = "budget"                      # SPEC-1031 rule 2 — an OPENED machine wall-clock limit (T-13966)
THRESHOLD = "threshold"                # SPEC-1031 rule 2 — an OPENED project number (T-13966)
GATE = "gate"
#: Every class name an entry may carry (SPEC-1031 rule 2). An entry is BUDGET or THRESHOLD only once a
#: card opened it (SPEC-1031 rule 3); an unclassified name reads as GATE.
CLASSES = (PERFORMANCE, BINDING, BUDGET, THRESHOLD, GATE)
#: The project ops-carrier section a THRESHOLD is set in (SPEC-1031 rule 5).
THRESHOLDS_SECTION = "thresholds"

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

    `escape` (T-13967) marks a knob whose ENVIRONMENT value is an escape hatch its own spec puts above
    every other source whatever the knob's class — the land-verify per-file bound, whose
    `YITC_VERIFY_TEST_TIMEOUT` heads the SPEC-0152 chain. `applied` reads that value first, as it does
    for a budget, so `config get` and `config list` show the value the read site applies. It opens
    nothing: a GATE knob with `escape` is still refused on every door.
    """

    __slots__ = ("name", "cls", "kind", "default", "read_site", "why", "bounds", "escape")

    def __init__(self, name, cls, kind, default, read_site, why, bounds=None, escape=False):
        self.name, self.cls, self.kind = name, cls, kind
        self.default, self.read_site, self.why = default, read_site, why
        self.bounds = bounds
        self.escape = escape

    @property
    def is_performance(self) -> bool:
        return self.cls == PERFORMANCE

    @property
    def is_settable(self) -> bool:
        """May this knob live in the machine file at all? PERFORMANCE and BINDING may; GATE never
        may (SPEC-0193 rule 3, as amended by SPEC-0202 rule 1). Deliberately a SECOND property rather
        than a widened `is_performance`: the class question «is this a cadence value» is asked by
        read sites and by tests that pin a knob's classification, and answering it `True` for a
        binding locator would quietly make those claims false.

        A BUDGET may too, but ONLY with a declared band (SPEC-1031 rule 3(a)): an unbanded one is
        treated as GATE, fail-closed. A THRESHOLD never may — it belongs to the project (rule 4)."""
        if self.cls == BUDGET:
            return self.bounds is not None
        return self.cls in (PERFORMANCE, BINDING)


def _p(name, kind, default, read_site, why, bounds=None):
    return Knob(name, PERFORMANCE, kind, default, read_site, why, bounds)


def _b(name, read_site, why):
    """A BINDING-class locator. Always a string, and its default is ALWAYS the empty string —
    «nothing bound on this machine» — because the fallback for an unbound locator is the
    resolution order at the read site (env → this file → PATH → repo config), never a value
    restated here."""
    return Knob(name, BINDING, "str", "", read_site, why)


def _u(name, kind, default, read_site, why, bounds, escape=False):
    """A BUDGET-class knob a card OPENED (SPEC-1031 rule 3): a wall-clock limit set on the machine,
    always with its declared band (rule 3(a))."""
    return Knob(name, BUDGET, kind, default, read_site, why, bounds, escape)


def _t(name, kind, default, read_site, why, bounds):
    """A THRESHOLD-class knob a card OPENED (SPEC-1031 rule 3): a number set in a project's
    yitc-ops.yaml `thresholds:` section, always with its declared band (rule 3(a))."""
    return Knob(name, THRESHOLD, kind, default, read_site, why, bounds)


def _g(name, kind, default, read_site, why, bounds=None, escape=False):
    """A GATE-class knob. `bounds` and `escape` (T-13967) prepare a key a later card opens
    (SPEC-1031 rule 3): the band is declared and the environment escape hatch is shown where it
    applies, while the class, and with it the refusal on every door, stays GATE."""
    return Knob(name, GATE, kind, default, read_site, why, bounds, escape)


# ── THE INVENTORY ─────────────────────────────────────────────────────────────────────────────
# Every runtime tunable, each with exactly one class. Kept SORTED by name so a new entry lands in an
# obvious place and a diff reads as one line. `tests/test_config_inventory.py` asserts the RULE —
# every `YITC_*` name reachable in bin/ appears here — so an unlisted knob is a red, not a silence.
INVENTORY: "tuple[Knob, ...]" = (
    # ---- BINDING: WHICH external auditor this machine runs (SPEC-0202 rule 1). Exactly these
    # SIXTEEN keys — eight per tier — and no more: the class is a CLOSED enumeration, so every other
    # `auditor.*` name stays unclassified and is therefore GATE,
    # refused by `set_value` and dropped on read exactly as before. These are LOCATORS: they decide
    # WHO judges, never whether a judged thing passes, which is why they may be machine-scoped at all
    # while a gate value may not (SPEC-0132). Measured need: T-12176's pre-claim refusal (2026-09-06)
    # found the auditor binary GATE-class, so binding an auditor per machine was impossible without
    # this class. The READ SITES named below are wired by the sibling card T-12350 — this card adds
    # the class and the settable surface only, so a listed read site is where the value is CONSUMED
    # once that card lands, not a claim that it is consumed today.
    _b("auditor.full.binary", "bin/lib/audit.py#resolve_codex_binary",
       "the full-tier auditor CLI's path on THIS machine — a locator, not a threshold"),
    _b("auditor.full.effort", "bin/lib/audit.py#resolve_audit_effort",
       "T-12853 — the full-tier PRIMARY pair's effort on THIS machine. A pair half, not a threshold: "
       "the verdict stamps the pair that ran (SPEC-0202 rule 6), so a switched effort is on record"),
    _b("auditor.full.home", "bin/lib/audit.py#resolve_codex_binary",
       "the full-tier auditor provider's auth/config HOME dir on THIS machine — a locator"),
    _b("auditor.full.model", "bin/lib/audit.py#resolve_audit_provider",
       "the full-tier auditor's model id. In the binding because an adopter on a non-default "
       "provider must be able to name one without editing the engine tree (a tracked-file edit is "
       "refused by `release verify`, T-12174); honest because every verdict STAMPS the model that "
       "ran (SPEC-0202 rule 2a) and a bound-vs-default difference is named at session start (2b)"),
    _b("auditor.full.provider", "bin/lib/audit.py#resolve_audit_provider",
       "WHICH adapter judges at full tier on THIS machine — an adapter name the registry knows "
       "(SPEC-1040 §Auditor selection / bin/audit-config.yaml); a locator, not a verdict input"),
    _b("auditor.full.reserve.effort", "bin/lib/audit.py#resolve_audit_reserve",
       "T-12853 — the full-tier RESERVE pair's effort (SPEC-0202 rule 6); overrides the repo "
       "config's `full.reserve.effort` per machine"),
    _b("auditor.full.reserve.model", "bin/lib/audit.py#resolve_audit_reserve",
       "T-12853 — the full-tier RESERVE pair's model: the second door used ONCE when the primary "
       "does not answer. Per machine so the door switches without a repo edit; a value equal to "
       "the tier's primary model is warned at `config set` and shown SAME AS PRIMARY by `audit status`"),
    _b("auditor.full.timeout", "bin/lib/audit.py#audit_timeout_resolution",
       "T-13205 — the full-tier audit wall-clock (seconds) on THIS machine. A hang guard: expiry "
       "yields NO verdict (a no-answer, SPEC-0202 rule 6), so it decides how long the bound auditor "
       "may take, never whether a judged thing passes. The env YITC_AUDIT_TIMEOUT_SECONDS still wins"),
    _b("auditor.routine.binary", "bin/lib/audit.py#resolve_codex_binary",
       "the routine-tier auditor CLI's path on THIS machine — a locator, not a threshold"),
    _b("auditor.routine.effort", "bin/lib/audit.py#resolve_audit_effort",
       "T-12853 — the routine-tier PRIMARY pair's effort on THIS machine (see its full-tier twin)"),
    _b("auditor.routine.home", "bin/lib/audit.py#resolve_codex_binary",
       "the routine-tier auditor provider's auth/config HOME dir on THIS machine — a locator"),
    _b("auditor.routine.model", "bin/lib/audit.py#resolve_audit_provider",
       "the routine-tier auditor's model id — admitted into the binding under the same two guards "
       "as its full-tier twin (SPEC-0202 rule 2: the verdict stamp + the session-start naming)"),
    _b("auditor.routine.provider", "bin/lib/audit.py#resolve_audit_provider",
       "WHICH adapter judges at routine tier on THIS machine — an adapter name the registry knows "
       "(SPEC-1040 §Auditor selection / bin/audit-config.yaml); a locator, not a verdict input"),
    _b("auditor.routine.reserve.effort", "bin/lib/audit.py#resolve_audit_reserve",
       "T-12853 — the routine-tier RESERVE pair's effort (see its full-tier twin)"),
    _b("auditor.routine.reserve.model", "bin/lib/audit.py#resolve_audit_reserve",
       "T-12853 — the routine-tier RESERVE pair's model (see its full-tier twin)"),
    _b("auditor.routine.timeout", "bin/lib/audit.py#audit_timeout_resolution",
       "T-13205 — the routine-tier audit wall-clock (seconds) on THIS machine (see its full-tier twin)"),

    # ---- PERFORMANCE: cadence + concurrency only. Nothing here can flip a verdict. ----
    _p("YITC_AUDIT_HEARTBEAT_SECS", "float", 20.0, "bin/lib/audit.py#_audit_heartbeat_interval",
       "seconds between dispatched-worker audit progress heartbeats — an EMIT cadence; the audit "
       "verdict is computed by the auditor and is untouched by how often progress is printed"),
    _p("YITC_GC_LOOSE_THRESHOLD", "int", 256, "bin/git-maintenance.sh",
       "loose-object count above which maintenance repacks — how often housekeeping runs, never "
       "whether any check passes"),
    _p("YITC_VENUE_MAX_REQUESTS", "int", 1, "bin/lib/remote_verify.py#venue_max_requests",
       "the MACHINE-WIDE cap on how many verify REQUESTS are admitted to the venue box at once "
       "(SPEC-1029 rule 4, T-12241). THE UNIT IS THE REQUEST, NEVER THE LEG: one land is cand + "
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
    _p("YITC_DEPLOY_ADMISSION_MAX_WAIT_S", "int", 600,
       "bin/lib/deploy.py#deploy_admission_settings",
       "how long a forward `deploy` waits, at most, for the host load1 to drop under "
       "YITC_DEPLOY_HEADROOM_LOAD1 before it refuses (SPEC-0094 §9, T-13962). The verb re-reads the "
       "load every 15 s inside this bound; when it expires the deploy refuses with nothing run, and "
       "`deploy --now` skips the wait. Admissible 1..7200 seconds; anything else is ignored and the "
       "default stands. PERFORMANCE: it changes WHEN a deploy starts, never which gates it runs or "
       "how they conclude",
       bounds=(1, 7200)),
    _p("YITC_DEPLOY_HEADROOM_LOAD1", "float", 36.0,
       "bin/lib/deploy.py#deploy_admission_settings",
       "the host load1 a forward `deploy` must be BELOW before it runs the project's deploy command "
       "(SPEC-0094 §9, T-13962): the command runs its own smoke tests, and on a host busy with verify "
       "runs those tests flake. The default is the Stage-6 venue headroom built-in "
       "(YITC_VENUE_STAGE6_HEADROOM_LOAD1, 36.0), the one load figure the engine already admits work "
       "under. Admissible 1.0..1024.0; anything else is ignored and the default stands. PERFORMANCE: "
       "it changes WHEN a deploy starts, never which gates it runs or how they conclude",
       bounds=(1.0, 1024.0)),
    _g("YITC_DISPATCH_LAUNCHER", "str", None, "bin/lib/worktree_lifecycle.py#_dispatch_launcher_pid",
       "T-12830 — the dispatch launcher's <pid>:<starttime>; spares it from the live-holder refusal"),
    _g("YITC_VENUE_RECORD", "str", None, "bin/lib/venue.py#resolve_record_path",
       "WHICH verify-venue record is read/written (SPEC-1029 rule 1) — a placement/identity input of "
       "exactly the same nature as YITC_MACHINE_SETTINGS, whose sibling file it is. GATE because the "
       "record decides WHERE a kernel verify pass executes, and rule 7 forbids a silent local "
       "fallback: pointing it at another file changes which box a verdict came from"),
    _g("YITC_VENUE_CONFIG", "str", None, "bin/lib/venue.py#resolve_config_path",
       "WHICH verify-venue provider binding is read (SPEC-1029 rule 6, T-13000) — a placement/identity "
       "input like YITC_VENUE_RECORD. GATE because an absent binding decides that routing ignores any "
       "record and every kernel pass runs locally: pointing it elsewhere changes where a verdict comes from"),
    _p("YITC_VENUE_STAGE6_NICE", "int", 19, "bin/lib/remote_verify.py#venue_stage6_nice",
       "the box-side scheduler nice a LOWER-PRIORITY (Stage-6, `task test --run`) venue pass runs "
       "its runner at (SPEC-1029 rule 5's lower-priority arm, T-12218). The default 19 is the "
       "minimum priority: such a pass receives CPU only when the land legs leave it idle, because "
       "`land` is the box's primary client and a background worker's suite can wait. A LAND leg is "
       "NOT tunable and never reaches this read site — its 0 is a literal at the route seam; the "
       "Stage-6 pass of a card carrying a live queue-jump mark is sent at 0 as well (SPEC-1029 rule 5). "
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
       "(SPEC-1029 rule 4's by-class admission, T-12259). THE STAGE-6 HALF ONLY: a LAND is admitted "
       "by YITC_VENUE_MAX_REQUESTS, which stays the sole carrier of the land cap — there is "
       "deliberately no second land cap to keep in step with it. The default 4 is the owner's figure "
       "and the measurement behind it: a Stage-6 pass runs on HALF the derived width (12 of 48 cores "
       "on ccx63) at nice 19 and alone moves load1 to 1-11, so four fit inside the box a single land "
       "peaks at 25-45 for two or three minutes. Admissible 1..16 — 0 would DISABLE Stage-6 "
       "admission rather than slow it, and past 16 the headroom test does all the work anyway; "
       "anything else is ignored and the default stands. ON THE LOCAL HOST TOO WHEN SET (T-13806): with no venue published, a value set "
       "in the environment or this file also bounds the local Stage-6 arm; UNSET, the local arm keeps "
       "its built-in behaviour (no Stage-6 cap, full width) — the default shown here is the BOX's. PERFORMANCE: it changes WHEN a Stage-6 pass "
       "is admitted, never which files run or how they conclude",
       bounds=(1, 16)),
    _p("YITC_VENUE_PRESHIP_MAX_CONCURRENT", "int", 1,
       "bin/lib/remote_verify.py#venue_preship_max_concurrent",
       "how many PARKED lands on this machine may pre-ship their branch to the venue box at once "
       "(SPEC-1029 rule 3 / SPEC-0184 rule 15, T-13424). A pre-ship runs ONE `git pack-objects` over "
       "the branch's journal versions, measured at 3.4-4.0 GB peak RSS on a ~190 MB journal, so the "
       "default 1 is the host-memory bound; every admission ALSO sums the reservations of the live "
       "pre-ships against MemAvailable, so a larger value can never admit past free memory. "
       "Admissible 1..4 — the ceiling is the number of slot files every admission probes; anything "
       "else is ignored and the default stands. PERFORMANCE: it changes WHEN a parked land pre-ships, "
       "never what its verify runs or how it concludes — the verify-time push is unchanged",
       bounds=(1, 4)),
    _p("YITC_VENUE_STAGE6_HEADROOM_LOAD1", "float", 36.0,
       "bin/lib/remote_verify.py#venue_stage6_headroom_load1",
       "the box load1 a LOWER-PRIORITY (Stage-6) venue pass must be BELOW to be admitted (SPEC-1029 "
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
       "pass runs at (SPEC-1029 rule 5's lower-priority arm, T-12261). It is the WIDTH half of that "
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
       "by it and never reaches the read site: it takes the full derived W; nor does the Stage-6 "
       "pass of a card carrying a live queue-jump mark take it (SPEC-1029 rule 5). Admissible (0, 1] — "
       "declared as the inclusive pair 0.0..1.0 because `coerce` already refuses any numeric knob "
       "<= 0 BEFORE the bounds test, so the pair IS the exclusive-at-zero interval and no second "
       "validation path is added for it; above 1 a Stage-6 pass would be asking for MORE width than "
       "the land it must yield to. ON THE LOCAL HOST TOO WHEN SET (T-13806): with no venue published, a value set "
       "in the environment or this file also bounds the local Stage-6 arm; UNSET, the local arm keeps "
       "its built-in behaviour (no Stage-6 cap, full width) — the default shown here is the BOX's. PERFORMANCE: it changes how fast a Stage-6 pass finishes, never "
       "which files run or how they conclude — the leg records the width it actually ran at",
       bounds=(0.0, 1.0)),
    _p("YITC_STAGE6_LOAD_BOUND", "float", None, "bin/lib/task.py#_stage6_load_settings",
       "the CPU busy share (a fraction, 0 to 1) the LOCAL host must be UNDER before the next local "
       "Stage-6 run starts (SPEC-1029 rule 5's opt-in load hold, T-14023). It applies inside the local "
       "Stage-6 slot, so it needs YITC_VENUE_STAGE6_MAX_CONCURRENT set too. UNSET (the default) = no "
       "hold and nothing read from the host — admission exactly as before. The share is read over "
       "YITC_STAGE6_LOAD_WINDOW_S from two /proc/stat samples, on a window that began at or after the "
       "newest local Stage-6 start; an unreadable reading holds the run. Admissible (0, 1] — the "
       "inclusive pair 0.0..1.0 with `coerce` refusing 0. PERFORMANCE: it changes WHEN a Stage-6 run "
       "starts, never which files run or how they conclude (an admission value, SPEC-0193 rule 2)",
       bounds=(0.0, 1.0)),
    _p("YITC_STAGE6_LOAD_WINDOW_S", "float", 5.0, "bin/lib/task.py#_stage6_load_settings",
       "the seconds between the two /proc/stat samples the YITC_STAGE6_LOAD_BOUND busy share is read "
       "over (T-14023). 5 s smooths a one-tick spike yet answers within a few admission polls. "
       "Admissible 1..60. Read only while the bound is set. PERFORMANCE: it changes WHEN a Stage-6 run "
       "starts, never how it concludes",
       bounds=(1.0, 60.0)),
    _p("YITC_STAGE6_LOAD_SPACING_S", "float", 60.0, "bin/lib/task.py#_stage6_load_settings",
       "the seconds that must pass after the newest local Stage-6 start before the next one may start "
       "under YITC_STAGE6_LOAD_BOUND (T-14023): a suite needs time to load the host before a reading "
       "shows it — T-13810 measured three runs started on one quiet reading. The start time is kept "
       "after the run ends, so a short run still spaces the next start. Admissible 1..3600. Read only "
       "while the bound is set. PERFORMANCE: it changes WHEN a Stage-6 run starts, never how it concludes",
       bounds=(1.0, 3600.0)),
    _p("YITC_STAGE6_LOAD_CPU_SET", "str", "", "bin/lib/task.py#_stage6_load_settings",
       "the CPUs the YITC_STAGE6_LOAD_BOUND busy share is read over, as a list like `0-15,32-47` "
       "(T-14023); empty (the default) = every online CPU (the aggregate /proc/stat line). A list "
       "naming a CPU the host does not have, or one that does not parse, is an unreadable reading and "
       "holds the run. Read only while the bound is set. PERFORMANCE: it changes WHEN a Stage-6 run "
       "starts, never how it concludes"),
    _p("YITC_VERIFY_WORKER_NICE", "int", 19, "bin/lib/verify_runner.py#_verify_child_nice",
       "the scheduler nice a DISPATCHED WORKER's per-file test child is spawned at on the LOCAL host "
       "(T-12224). The default 19 is the minimum priority: such a child receives CPU only when the "
       "land verifies leave it idle, because `land` is what the system's throughput rides on and a "
       "background worker's Stage-6 suite can wait. THE PAIR — one owner directive, two hosts: this "
       "is the LOCAL key, its box-side twin is YITC_VENUE_STAGE6_NICE. A LAND leg is NOT tunable by "
       "either and never reaches this read site: it declares itself and returns 0 unconditionally. "
       "The Stage-6 run of a card carrying a live queue-jump mark takes neither (SPEC-1029 rule 5). "
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
       "PASSING in isolation, so no value here can admit a failing check. THE SAME BOUND IS THE "
       "SWITCH FOR THE CONSUMER LAYER RE-RUN (T-13545, SPEC-0152 rule 16): any value >= 1 admits "
       "the isolated re-run of ONE sole failed verify layer (never more than one, whatever the "
       "value), and 0 turns that re-run off as well — one switch, no second knob. AND FOR THE "
       "PER-UNIT RE-RUN of an adapter-backed layer (T-13607, SPEC-1035 rule 10): any value >= 1 "
       "admits it under that rule's own bounds, and 0 turns it off too, so a failed unit's first "
       "failure blocks",
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
       "automatic at any value: a line leaves the carrier only by a card. The SAME threshold decides "
       "the per-unit lane of a consumer's adapter-backed verify layers (T-13609, SPEC-1035 rule 11): "
       "that many RESCUED per-unit re-runs inside the window enter a unit into that project's "
       "`yitc-load-sensitive-units.txt`, on the same terms",
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
       "never whether its verdict counts. The SAME window bounds the per-unit entry of a consumer's "
       "adapter-backed layers (T-13609, SPEC-1035 rule 11)",
       bounds=(1, 365)),
    _g("YITC_VERIFY_ADAPTER_MANIFEST", "str", None,
       "bin/lib/land_verify_legs.py#_VERIFY_ADAPTER_MANIFEST_ENV",
       "NOT an input the kernel reads: the path of the manifest file the kernel writes for ONE "
       "adapter invocation of an adapter-backed verify layer, WRITTEN into that `list` / `run` "
       "command's env so the project's adapter knows what to enumerate or run and where to write "
       "its report (T-13606, SPEC-1035 rules 3-4). GATE by the fail-closed default, on the same "
       "terms as YITC_VERIFY_LAYER_WORKERS: setting it by hand changes nothing the kernel decides, "
       "and it is never read back"),
    _p("YITC_VERIFY_HEARTBEAT_SECS", "float", 20.0,
       "bin/lib/verify_runner.py#_verify_heartbeat_interval",
       "seconds between land-verify progress heartbeats — an EMIT cadence on stderr; the verify "
       "VERDICT, its per-file timeout and the SPEC-0077 gate are all untouched (T-9601). THE WIRED "
       "READ SITE (AC4): env > machine file > built-in default"),
    _g("YITC_VERIFY_LAYER_WORKERS", "int", None, "bin/lib/worktree.py#_VERIFY_LAYER_WORKERS_ENV",
       "NOT an input the kernel reads: the governor's ADMITTED per-verify worker count, WRITTEN into "
       "each consumer verify layer command's env (and Stage-6's) so a layer can size its runner to "
       "its share (T-12589, SPEC-0132 Rule 2). Deliberately distinct from YITC_VERIFY_WORKERS (the "
       "machine input). GATE by the fail-closed default: setting it by hand changes nothing the "
       "kernel decides, and it is never read back"),
    _p("YITC_VERIFY_WORKERS", "int", None, "bin/lib/remote_verify.py#remote_workers_override",
       "the OVERRIDE CEILING on the DERIVED REMOTE verify width (SPEC-1029 rule 5, T-12195). The "
       "venue derives W per pass from the duration table and the box's cores; this only ever LOWERS "
       "it. REMOTE-ONLY BY DESIGN: the LOCAL width's ceiling is its own row, "
       "lib.worktree._VERIFY_WORKER_CEILING (T-13806), so this key never reads on the local path. (Until "
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
    _p("lib.audit.AUDITOR_NO_ANSWER_WAIT_SECONDS", "int", 60,
       "bin/lib/audit.py#invoke_auditor_tiered",
       "T-12606 — the pause between two attempts at a tier PRIMARY that is not answering while that "
       "tier declares NO reserve pair (SPEC-0202 rule 6). Pure CADENCE: it paces how often the "
       "primary is re-asked. The wait ENDS when the primary answers or the caller interrupts it, "
       "never on a counter, so no value of this key can turn a verdict into a refusal — which is "
       "exactly what rule 2 asks of a performance key",
       bounds=(1, 3600)),
    _p("lib.audit.AUDITOR_BREAKER_THRESHOLD", "int", 3,
       "bin/lib/audit.py#invoke_auditor_tiered",
       "T-13109 — how many CONSECUTIVE primary non-answers (on the same resolved pair, inside the "
       "K17-2 window) trip a tier's breaker so its RESERVE runs first (SPEC-0202 rule 6). "
       "PERFORMANCE: the breaker only REORDERS the two declared pairs — a verdict is still whatever "
       "the answering pair returns, and a tier with no reserve never trips — so no value of it can "
       "turn a verdict into a refusal",
       bounds=(1, 1000)),
    _p("lib.audit.AUDITOR_BREAKER_FULL_THRESHOLD", "int", 1,
       "bin/lib/audit.py#invoke_auditor_tiered",
       "T-13450 — the FULL tier's breaker threshold (every consult, every default/--full ad-hoc, "
       "every full gate audit): its FIRST primary non-answer trips it, so a big audit pays at most "
       "one long budget per cool-down. PERFORMANCE for the same reason as the routine threshold: "
       "the breaker only REORDERS the two declared pairs",
       bounds=(1, 1000)),
    _p("lib.audit.AUDITOR_BREAKER_COOLDOWN_SECONDS", "int", 3600,
       "bin/lib/audit.py#invoke_auditor_tiered",
       "T-13109 — how long a tripped tier breaker runs its RESERVE first before probing the primary "
       "again (SPEC-0202 rule 6). Pure CADENCE of the probe: it changes which declared pair is asked "
       "first, never what either pair's verdict means",
       bounds=(60, 604800)),
    _p("lib.dispatch.LAUNCH_ANSWER_PROBE_SECONDS", "int", 45,
       "bin/lib/dispatch.py#_probe_launch_answer",
       "T-12607 — the window a freshly spawned worker launch is watched for before it counts as "
       "HAVING ANSWERED (SPEC-0072 rule 7). Sized to the FAST causes only: a capacity/overload "
       "refusal and an auth death print and exit within seconds, while a real bootstrap runs for "
       "minutes — so a live process at the end of the window is an ANSWER. Pure CADENCE: the probe "
       "returns the moment the reading is decidable and returns ANSWERED when the window elapses, so "
       "no value of this key can turn a healthy launch into a refusal",
       bounds=(1, 600)),
    _p("lib.dispatch.LAUNCH_NO_ANSWER_WAIT_SECONDS", "int", 60,
       "bin/lib/dispatch.py#launch_worker_with_pair",
       "T-12607 — the pause between two attempts at an effort tier's PRIMARY worker pair that is not "
       "coming up while that tier declares NO reserve pair (SPEC-0072 rule 7). Pure CADENCE: it paces "
       "how often the primary is re-launched. The wait ENDS when the primary comes up or the operator "
       "interrupts it, never on a counter, so no value of this key can turn a launch into a refusal — "
       "which is exactly what rule 2 asks of a performance key",
       bounds=(1, 3600)),
    _p("lib.audit.AUDIT_INSPECTION_TIMEOUT_SECONDS", "int", 1320,
       "bin/lib/audit.py#_audit_timeout_seconds",
       "T-12233 — the INSPECTION-class (consult / adhoc) auditor wall-clock budget in seconds. "
       "PERFORMANCE only BECAUSE of the same card's no-answer case (written for the now-retired "
       "ceiling-consult episodes of the superseded SPEC-0200, and kept by the consult engine): the expiry of THIS "
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
       "it chooses the DELTA SINCE THE BASELINE REVISION instead of the full subject diff. A retest "
       "round exists only inside a ceiling-consult episode, and those episodes are retired "
       "(SPEC-0204 rule 6). Under the superseded SPEC-0200 rule 4 of those retired episodes a retest "
       "judged only the open blocking ids and regressions the fix introduced, which is why the two "
       "scopes were equivalent there — and when the packet is STILL over the bound it is sent WHOLE and UNTRUNCATED "
       "with `packet_over_bound: true` and the measured size recorded. It NEVER truncates and NEVER "
       "refuses a round, which is exactly what keeps it out of GATE. DELIBERATELY NOT REACHED BY IT: "
       "the pre-existing AUDIT_MAX_DIFF_LINES / AUDIT_MAX_DIFF_BYTES diff truncation stays an "
       "unregistered CODE CONSTANT, so no `config set` on any machine can change what an auditor "
       "sees. Authority: owner_directive events.jsonl#ts=2026-09-07T23:44:44Z (OPTION A)"),
    _p("lib.journal.WATCH_MAX_RUNTIME_SECS", "int", 1500, "bin/lib/journal.py#watch_max_runtime_secs",
       "T-14002 — how long an armed `dispatch --watch` (and the launch's self-armed watch) runs with no "
       "wake condition before it exits `WATCH: TIMEOUT` with its re-arm cue. PERFORMANCE: the watcher "
       "is read-only observability — its expiry judges nothing, records no verdict and stops no run, "
       "so it changes only how often a controller re-arms. Measured need (yitc#137 item 2): workers "
       "run 1-3 h and the 1500 s bound was re-armed by hand about ten times a day. Band: one poll "
       "interval to 3 h; a value above the wrapper ceiling of the harness that runs the watcher is "
       "the operator's choice (patterns/background-session-monitoring.md §Watcher)",
       bounds=(60, 10800)),
    _p("lib.journal.MAX_FLEET_WIDTH", "int", 8, "bin/lib/journal.py#dispatch_readiness_report",
       "T-12219 — the per-SERVER owner bound on concurrent workers. PERFORMANCE and unusually "
       "clearly so: SPEC-0133 §6 forbids it from EVER clamping `recommended_wave_ceiling` («never a "
       "coded cap»), so by its own governing rule it can decide nothing — the printers echo it as a "
       "SUGGESTED bound the controller judges against. It is per-server by definition, which is "
       "exactly what the machine file is for"),
    _p("lib.nightly.VENUE_IDLE_BUFFER_MIN", "float", 15.0,
       "bin/lib/nightly.py#venue_idle_report",
       "T-12219 — how long every repo on this machine must have NO in-progress task before the "
       "compute-controller session unpublishes and deletes the box. SPEC-1029 rule 6 and its "
       "§Parameters ALREADY name this a machine-scoped performance tunable under `config`; it had "
       "never been registered, so the spec described a knob that did not exist. It changes when an "
       "IDLE box is torn down — never whether any pass concludes"),
    _p("lib.nightly._QUIET_LANE_RETRY_INTERVAL", "int", 60,
       "bin/lib/nightly.py#_quiet_lane_measure",
       "T-12219 — seconds between quiet-lane retries while waiting for enough free slots. A retry "
       "CADENCE inside a window bounded separately by _QUIET_LANE_RETRY_WINDOW (gate): it changes "
       "WHEN an attempt is made, never what the attempt concludes"),
    _p("lib.nightly.TRANSCRIPT_RAW_RETENTION_DAYS", "int", 45,
       "bin/lib/nightly.py#transcript_raw_retention_days",
       "T-12491 — days a raw provider transcript stays in `.yitc/transcript-archive/` after its last "
       "modification before the nightly may prune it. Pruning is DIGEST-GATED: a file goes only when "
       "its SPEC-0206 digest matches the file byte-for-byte, so this changes WHEN the forensic raw copy "
       "leaves, never whether a verified usage record survives or any verdict moves. Default 45 per the "
       "2026-09-13 external consult (15 days of margin past the provider's ~30-day expiry). "
       "Admissible 1..3650",
       bounds=(1, 3650)),
    _p("lib.nightly.TRANSCRIPT_TMP_RETENTION_DAYS", "int", 14,
       "bin/lib/nightly.py#transcript_tmp_retention_days",
       "T-12491 — the same window for sandbox sessions (archive dirs starting `-tmp`), shorter because "
       "they are throwaway worktree runs. Digest-gated on the same terms as its sibling. Default 14 per "
       "the same consult. Admissible 1..3650",
       bounds=(1, 3650)),
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
    _p("lib.batch_landing._LAND_BATCH_MAX", "int", 4, "bin/lib/batch_landing.py#_land_batch_max",
       "T-13991 (SPEC-0184 §Parameters) — how many queued lands share ONE verify. PERFORMANCE: it "
       "changes how many lands one verify pass carries, never a member's verdict — a red batch "
       "re-queues every member (SPEC-0184 rule 4), it fails none. 1 forms every land alone, which is "
       "batching off. Owner decision 2026-10-17 (option A): the right size depends on the machine "
       "and the project. Admissible 1..8 (SPEC-0184's measured basis: 8+ inverts the all-green trade)",
       bounds=(1, 8)),
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
       "T-12219 — how often the SPEC-1028 held-turn liveness watchdog re-tests its subject. Pure "
       "latency; the watchdog's VERDICT is `kill -0` on the claimed pid, not the interval it asks "
       "at"),
    _p("lib.worktree._VERIFY_HEARTBEAT_DEFAULT_SECS", "float", 20.0, "bin/lib/worktree.py",
       "the built-in default behind YITC_VERIFY_HEARTBEAT_SECS — same cadence nature"),
    _p("lib.worktree._VERIFY_WORKER_CEILING", "int", 13, "bin/lib/worktree.py#_verify_worker_ceiling",
       "T-13806 — the per-verify worker CEILING on the LOCAL host: a verify's width is "
       "min(host resource bound, this value), and the SPEC-0132 admission slots follow from it "
       "(bound // width). The module constant stays the built-in default, so an unset machine runs "
       "exactly as before; a host or a fork with a different core count sets its own. PERFORMANCE: "
       "it changes how wide (and so how fast) a verify runs and how many run at once, never which "
       "files run or how they conclude — the governor's resource bound still caps it, so no value "
       "can oversubscribe the host. Distinct from YITC_VERIFY_WORKERS, which lowers the DERIVED "
       "REMOTE width only. Owner directive events.jsonl#ts=2026-10-09T13:28:02Z. Admissible 1..1024",
       bounds=(1, 1024)),
    _p("lib.worktree._VERIFY_WIDTH_FLOOR", "int", 4, "bin/lib/worktree.py#_verify_width_budget",
       "T-13971 (SPEC-0132 §1c) — the fewest test workers an ADAPTIVE verify runs at, however loaded "
       "the host reads at its start. PERFORMANCE: it changes how wide a verify runs, never which files "
       "run or how they conclude; the host resource bound still caps it. Admissible 1..1024",
       bounds=(1, 1024)),
    _p("lib.worktree._VERIFY_WIDTH_MAX", "int", None, "bin/lib/worktree.py#_verify_width_budget",
       "T-13971 (SPEC-0132 §1c) — the most test workers an ADAPTIVE verify runs at; unset = the host's "
       "processor count. PERFORMANCE, as the floor. Admissible 1..1024",
       bounds=(1, 1024)),
    _p("lib.worktree._VERIFY_WIDTH_MODE", "str", "adaptive", "bin/lib/worktree.py#_verify_width_budget",
       "T-13971 (SPEC-0132 §1c) — `adaptive` sizes each verify at its start by the host's free cores "
       "(load1 read once, under one host-wide lock, with the widths of verifies that started within "
       "the last minute counted as load); `fixed` runs every verify at "
       "lib.worktree._VERIFY_WORKER_CEILING, as before this card. PERFORMANCE: width only. "
       "Admissible: adaptive | fixed",
       bounds=("adaptive", "fixed")),
    _p("lib.worktree._VERIFY_WIDTH_SHARE", "float", 0.8, "bin/lib/worktree.py#_verify_width_budget",
       "T-13971 (SPEC-0132 §1c) — the share of the host's free cores (processor count - load1 - "
       "recently started widths) an ADAPTIVE verify takes. PERFORMANCE, as the floor. "
       "Admissible 0.05..1.0",
       bounds=(0.05, 1.0)),

    # ---- BUDGET and THRESHOLD: the keys a card OPENED (SPEC-1031 rule 3; T-13969). Each declares
    # its band; a BUDGET is set on the machine, a THRESHOLD in a project's yitc-ops.yaml `thresholds:`.
    _u("YITC_VERIFY_TEST_TIMEOUT", "float", 300.0, "bin/lib/cli.py#_verify_test_timeout_seconds",
       "the land-verify per-file wall-clock bound (SPEC-0071): expiry ends the run as stuck and aborts "
       "the land. ONE key (T-13967 folded the former second name lib.cli._VERIFY_TEST_TIMEOUT_DEFAULT "
       "in); its built-in default lives here and nowhere else. A BUDGET (T-13969): a machine sets it "
       "with `config set` inside its band; its environment value is the SPEC-0152 escape hatch above "
       "every other source, a project's declared layer / section bound comes next, and the machine "
       "file takes the place just above this default (SPEC-1031 rule 4)",
       bounds=(60.0, 3600.0), escape=True),
    _t("YITC_LOAD_SENSITIVE_MAX_FILES", "int", 25, "bin/lib/debt.py#load_sensitive_max_files",
       "the FILE-COUNT half of the SPEC-0132 §3 serial-lane watch-point as EXTENDED to the declared "
       "load-sensitive lane (T-12360): past this many files in `tests/load-sensitive.txt` the weekly "
       "review must dispose a NAMED global-rework question instead of filing another per-file card. "
       "The default is the value the watch-point stated when it was written, reused as-is. A "
       "THRESHOLD (T-13969): one value per project, set in its yitc-ops.yaml `thresholds:` section, "
       "so the same lane reads the same bound on every machine. Admissible 1..1000 — below 1 no lane "
       "could ever be under bound, and past 1000 the lane would exceed this repo's whole recorded "
       "corpus. REPORT-ONLY: it changes what the weekly review is asked to DISPOSE, never which tests "
       "run, where they run, or how any verdict concludes",
       bounds=(1, 1000)),
    _t("YITC_LOAD_SENSITIVE_SHARE_PCT", "int", 10, "bin/lib/debt.py#load_sensitive_share_pct",
       "the SHARE-OF-VERIFY-WALL half of the same extended watch-point (T-12360), in percent of the "
       "duration table's own total per-file work (T-11316): past this share the lane's serialized "
       "tail is long enough that the weekly review must dispose the global-rework question. The "
       "default is likewise the watch-point's own stated value. A THRESHOLD on the same reading as its "
       "sibling above. Admissible 1..100 — 0 would report every non-empty lane as over bound and past "
       "100 no lane could be. REPORT-ONLY on the same terms",
       bounds=(1, 100)),
    _t("lib.cli.LAND_REPEATED_ABORT_THRESHOLD", "int", 2, "bin/lib/cli.py#cmd_land",
       "the T-0655 repeated-abort backstop: a land is refused once this many consecutive same-cause "
       "aborts are on record, so it decides whether a land runs. A THRESHOLD (T-13969): one value "
       "per project, set in its yitc-ops.yaml `thresholds:` section; the band's lower end keeps one "
       "transient abort from ever blocking. Read through `in_force`, and the abort it decides names "
       "value and source on its row (T-13968)",
       bounds=(2, 10)),
    _t("lib.cli._LAND_MAX_RETRIES", "int", 5, "bin/lib/cli.py#_land_integrate",
       "the concurrent-land ff-race bound (D-0083 §3d): the number of integration attempts a land "
       "makes, the first one included, before it aborts `retries-exhausted`, so it decides whether "
       "a land completes. A THRESHOLD (T-13969): one value per project, set in its yitc-ops.yaml "
       "`thresholds:` section; the band's lower end keeps one retry. Read through `in_force`, and the "
       "abort it decides names value and source on its row (T-13968)",
       bounds=(2, 20)),
    _t("pre_deploy_move_min_window_days", "int", 14, "bin/lib/cli.py#_verify_cost_reading",
       "SPEC-1042 rule 7 (T-14111): the weekly verify-cost reading proposes moving a costly zero-catch "
       "unit into a pre-deploy class only on a window covering at least this many days — a short quiet "
       "window is not a zero-catch record (the plan's 4-day reading missed catches a two-week one "
       "showed). A THRESHOLD: one value per project, set in its yitc-ops.yaml `thresholds:` section. "
       "Admissible 1..365. REPORT-ONLY: it decides what the reading PROPOSES, never what runs or moves",
       bounds=(1, 365)),
    _t("pre_deploy_move_min_runs", "int", 100, "bin/lib/cli.py#_verify_cost_reading",
       "SPEC-1042 rule 7 (T-14111): the run count at its place (land + Stage-6) a unit needs inside the "
       "window before the weekly reading proposes moving it into a pre-deploy class. A THRESHOLD on the "
       "same reading as its sibling above. Admissible 1..100000. REPORT-ONLY on the same terms",
       bounds=(1, 100000)),

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
    _g("YITC_C2_BACKUP_HANG_CAP_S", "int", 3600, "bin/lib/deploy.py",
       "T-13514: the owner-approved Class-C2 dump's hang-cap — its expiry REFUSES the deploy "
       "(SPEC-0097 §5), so the value participates in the verdict"),
    _g("YITC_CANARY_RUN", "str", None, "bin/lib/cli.py", "opt-in gate for the canary test arm"),
    _g("YITC_CANARY_BUDGET_SECS", "float", 180.0, "bin/lib/audit.py",
       "T-12481: the backstop canary's suite-run budget — it decides which probes run, so it shapes "
       "the verdict's coverage"),
    _g("YITC_CANARY_COVERAGE_FILE", "str", None, "bin/lib/audit.py",
       "T-12481: the backstop->canary coverage-report handoff path — set per run, never an operator knob"),
    _g("YITC_CANARY_RESUME_AT", "str", None, "bin/lib/audit.py",
       "T-12881: the backstop->canary rotation resume point (a probe name read from the last run) — "
       "set per run, never an operator knob"),
    _g("YITC_CLI__", "str", None, "bin/lib/graph.py",
       "a dynamic PREFIX STEM (render token family) — unclassifiable, therefore GATE"),
    _g("YITC_CODEX_AUDIT_BIN", "str", None, "bin/lib/audit.py",
       "which auditor binary runs — a refuse-before-spawn input"),
    _g("YITC_CODEX_WORKER_BIN", "str", None, "bin/lib/audit.py",
       "which worker binary runs — a refuse-before-spawn input"),
    _g("YITC_COMPACTION_ENTRY", "str", None, "bin/lib/cli.py#cmd_session_start",
       "set by the in-repository post-compaction entry (T-13790, SPEC-1024 rule 12); when present the "
       "stamping `session start` REFUSES — a refusal input, not a tunable"),
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
    _g("YITC_DISPATCH_LOG_RETENTION_DAYS", "int", 30, "bin/git-maintenance.sh",
       "how many days .yitc/dispatch-logs files survive before maintenance deletes them — DATA "
       "RETENTION, not speed (T-12502)"),
    _g("YITC_FE_SRC", "str", None, "bin/lib/frontend_errors.py", "a query input, not a cadence"),
    _g("YITC_GC_PRUNE_EXPIRE", "str", "7.days", "bin/git-maintenance.sh",
       "how long unreachable objects survive — DATA RETENTION, not speed"),
    _g("YITC_RELEASE_START_TIMEOUT", "float", None, "bin/lib/release.py#_start_check_timeout",
       "the bound on the consumer session-start newer-release ls-remote (T-13223); its expiry turns an "
       "answerable question into silence, so it changes what the start SAYS. Fail-closed to gate"),
    _g("YITC_GRAPH_CACHE", "str", None, "bin/lib/cli.py",
       "looks like speed but is not: the cache decides whether a STALE graph is served, so it can "
       "change what a governed read sees. Fail-closed"),
    _g("YITC_JOURNAL_INDEX", "str", None, "bin/lib/journal.py#_index_store",
       "looks like speed but is not, for YITC_GRAPH_CACHE's reason: the whole-history index decides "
       "whether a SUMMARY answers instead of the segment's own fold, so it can change what a governed "
       "read sees (T-13356). Fail-closed"),
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
       "the SPEC-1028 held-turn CLAIM, verified server-side — a refusal input"),
    _g("YITC_LAND_KEEP_PROCESS_GROUP", "str", None, "bin/lib/worktree.py",
       "process-group teardown behaviour — a safety switch"),
    _g("YITC_LAND_SESSION_ESCAPED", "str", None, "bin/lib/worktree.py#_escape_into_own_session",
       "an INTERNAL marker the T-12675 detach sets (the carrying land's session id) so its own "
       "`--task/--branch` re-exec child does not detach a second time — process topology, not a tunable"),
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
       "the T-12393 cap on automatic park-bound REQUEUES for one land process. GATE on the same "
       "ground as the park limit it extends: the number decides whether the land eventually gives "
       "up and HALTS, which is a verdict, not a cadence; no card opened it (SPEC-1031 rule 3)"),
    _g("YITC_LAND_RESERVATION_PARK_LIMIT_SECS", "float", None, "bin/lib/worktree.py",
       "the SPEC-0132 park BOUND: expiry degrades the land, so it is a verdict input (and is "
       "explicitly written never to be disableable)"),
    _g("YITC_MACHINE_SETTINGS", "str", None, "bin/lib/machine_settings.py#resolve_settings_path",
       "WHICH machine settings file is read/written — a placement/identity input, the same nature as "
       "YITC_CROSS_LOG. Pointing it at another file cannot smuggle a gate-class value in: the READ "
       "path drops gate-class keys whatever file they came from"),
    _g("YITC_MAINTENANCE_NO_LOCK", "str", None, "bin/git-maintenance.sh",
       "skips the maintenance reservation — a safety switch"),
    _g("YITC_MAINTENANCE_NO_INCREMENTAL", "str", None, "bin/git-maintenance.sh",
       "skips the deferred window's loose-pack leg (T-13290 control arm) — decides whether a "
       "starved repo is collected at all"),
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
    _g("YITC_SCRATCH_DIR", "str", None, "bin/lib/dispatch.py",
       "a dispatched worker's own scratch root, which its land/park DELETES — a deletion target, "
       "not a tunable (T-13203)"),
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
    _g("YITC_T12186_HELP_SURFACE_CHANGE", "str", None, "bin/lib/remote_verify.py#venue_declaration_env",
       "T-12529 — declares an intentional --help surface change to the T-12186 tripwire; the one "
       "allowlisted declaration carried to venue legs. GATE: it flips a test verdict"),
    _g("YITC_TEST_JOURNAL_GUARD", "str", None, "bin/lib/events.py",
       "the live-journal guard set — a refusal reads it"),
    _g("YITC_V2_PATH", "str", None, "bin/lib/verify_runner.py", "which CLI a test invokes"),
    _g("YITC_VENUE_LAND_OVERLAP_FILE", "str", None,
       "bin/lib/verify_runner.py#_run_verify_tests",
       "T-12260 — the venue leg's land-overlap SIDECAR: the file the box leg script writes the "
       "intervals a foreign land-class lease was live into, and the per-file land-verify bound "
       "reads to uncharge itself for that time (SPEC-0071 rule 1 / SPEC-1029 rule 4). It is set "
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
    _g("YITC_PINNED_SUITE_EDIT_PREAUDIT", "str", None, "tests/_pinned_suite_edit.py#_admits",
       "T-13226 — the pinned-suite-edit PRE-AUDIT marker (value = the running card's id). Set ONLY "
       "by `task test --run` for its own verify and forwarded to the box on the Stage-6 kind only; "
       "`land` scrubs it. It defers axis (d) for that declaring card alone. GATE, fail-closed: it "
       "decides whether a guard admits, never a cadence — never set it in a machine file"),
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
    _g("YITC_VERIFY_TMPDIR", "str", None, "bin/lib/verify_runner.py#_install_verify_tmpdir",
       "T-12185 — relocates the verify run's temp base (e.g. a tmpfs), which BOTH the sandbox "
       "mkdtemp and the SPEC-0132 Rule 1 disk/inode statvfs follow. GATE, not PERFORMANCE, and "
       "therefore NOT settable in the machine settings file: the relocated filesystem is measured by "
       "`_host_resource_headroom`, whose bound REFUSES a land at zero — so the value participates in "
       "an admission verdict. It stays an invocation-scoped env var precisely because a fail-closed "
       "refusal input must not be pinned machine-wide by a settings file"),
    _g("YITC_WATCH_KEEP_PROCESS_GROUP", "str", None, "bin/lib/dispatch.py",
       "process-group teardown behaviour — a safety switch"),
    _g("lib.audit.AUDIT_FULL_TIMEOUT_SECONDS", "int", 2160, "bin/lib/audit.py#audit_timeout_resolution",
       "T-13205 — the full-tier built-in default behind YITC_AUDIT_TIMEOUT_SECONDS; a machine moves "
       "it only through the BINDING key auditor.full.timeout"),
    _g("lib.audit.AUDIT_TIMEOUT_SECONDS", "int", 300, "bin/lib/audit.py",
       "the built-in default behind YITC_AUDIT_TIMEOUT_SECONDS — a verdict input"),
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
    ("project", "bin/yitc-v2 config set --project <key> <value> — the PROJECT door (T-14056): "
                "THRESHOLD keys only, into the project's yitc-ops.yaml `thresholds:` section, through "
                "`set_project_threshold`, which refuses a GATE key with the same `_refuse_gate`"),
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
    """The EFFECTIVE overrides: settable keys only (`Knob.is_settable` — performance and binding,
    and a banded budget), each coerced to its declared type and band (SPEC-0193 rule 3, as amended
    by SPEC-0202 rule 1; SPEC-1031 rule 7 for a budget).

    Gate-class, threshold-class and unknown keys present in the file are DROPPED — silently for the reader (whose
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
def coerce(knob: Knob, raw, *, banded=True):
    """Validate + convert `raw` for `knob`, or raise SettingsRefused. Numeric knobs must be finite
    and > 0: every numeric performance knob here is a cadence or a worker count, and zero/negative
    would not be a slower engine but a disabled or nonsensical one.

    A boolean is never a number here, and an integer knob takes no fractional value: a hand-written
    `true` or `2.5` is refused rather than read as 1 or 2 (T-13966). `banded=False` skips the band
    and nothing else — the environment layer of a budget, which SPEC-1031 rule 4 puts above the band
    exactly as SPEC-0193 rule 7 puts it above the file."""
    if knob.kind in ("int", "float") and isinstance(raw, bool):
        raise SettingsRefused(f"{knob.name}: expected {knob.kind}, got {raw!r}")
    if knob.kind == "int" and isinstance(raw, float) and not raw.is_integer():
        raise SettingsRefused(f"{knob.name}: expected int, got {raw!r}")
    try:
        if knob.kind == "int":
            value = int(raw)
        elif knob.kind == "float":
            value = float(raw)
        else:
            value = str(raw)
    except (TypeError, ValueError):
        raise SettingsRefused(f"{knob.name}: expected {knob.kind}, got {raw!r}")
    if knob.kind == "str" and knob.bounds is not None and value not in knob.bounds:
        # T-13971 — a str knob's `bounds` is the CLOSED set of values its read site acts on.
        raise SettingsRefused(f"{knob.name}: must be one of {' | '.join(knob.bounds)} (got {value!r})")
    if knob.kind in ("int", "float"):
        if value != value or value in (float("inf"), float("-inf")):     # NaN / inf
            raise SettingsRefused(f"{knob.name}: {raw!r} is not a finite {knob.kind}")
        if value <= 0:
            raise SettingsRefused(f"{knob.name}: must be > 0 (got {value})")
        if banded and knob.bounds is not None:
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
    is exactly the second door AC3 exists to keep shut.

    A THRESHOLD is refused here too (SPEC-1031 rule 7), with its own reason: it is the PROJECT's
    value, so the refusal names where it is set instead of calling it a gate."""
    knob = BY_NAME.get(name)
    if knob is not None and knob.cls == THRESHOLD:
        raise SettingsRefused(
            f"{name} is a THRESHOLD-class value and CANNOT be set in the machine settings file — "
            f"refused.\n"
            f"  WHY: a threshold describes the PROJECT, so every machine verifying one project must "
            f"read one value (SPEC-1031 rule 4).\n"
            f"  SET IT in that project's yitc-ops.yaml, section `{THRESHOLDS_SECTION}:`, key {name}.")
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
    """Set a settable knob (`Knob.is_settable`) in the machine file. Returns (old, new, dropped).

    Refuses — writing NOTHING — an unknown key (rather than storing a typo nobody will ever read),
    a gate-class or threshold-class key (hard, see `_refuse_gate`), and a value outside the knob's
    band (`coerce`). The write is atomic (temp file + replace), so a
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


# ── T-13966: the THRESHOLD section reader and the value-in-force helper (SPEC-1031 rules 4-6) ────
def project_thresholds(ops) -> "tuple[dict, list[str]]":
    """The project's `thresholds:` section (SPEC-1031 rule 5) as `({name: value}, notes)`.

    `ops` is the project's ops carrier as already parsed by its caller (this module reads no repo
    file). Only a THRESHOLD-class knob that declares a band is read, its value coerced and checked
    against that band. Every other entry is IGNORED with exactly ONE report-only line naming it:
    an unknown name, a name of another class (a GATE key is never read from here — rule 7), an
    unbanded threshold, a value that will not coerce or lies outside the band. A section that is not
    a mapping is ignored whole with one line, and so is a carrier its caller could not read (any
    `ops` that is neither None nor a mapping — the reader's unreadable answer). An absent carrier
    (None), an absent section or an absent key contributes nothing and says nothing (rule 8). A line says only that the
    entry is ignored, never which value applies instead: that is the reader's answer (`applied`),
    and for a key of another class it is not the built-in default. Never raises: nothing in this
    section can fail a run."""
    if ops is None:
        return {}, []
    if not isinstance(ops, dict):
        return {}, [f"{THRESHOLDS_SECTION}: not read — the project's ops carrier could not be read"]
    if ops.get(THRESHOLDS_SECTION) is None:
        return {}, []
    section = ops[THRESHOLDS_SECTION]
    if not isinstance(section, dict):
        return {}, [f"{THRESHOLDS_SECTION}: ignored — the section is a {type(section).__name__}, not a "
                    f"mapping; none of its entries is read"]
    values, notes = {}, []
    for key, raw in section.items():
        knob = BY_NAME.get(key) if isinstance(key, str) else None
        if knob is None:
            why = "not in the tunable inventory"
        elif knob.cls != THRESHOLD:
            why = f"a {knob.cls}-class key, never read from this section"
        elif knob.bounds is None:
            why = "a threshold that declares no band"
        else:
            try:
                value = coerce(knob, raw, banded=False)
            except SettingsRefused as exc:
                why = str(exc)
            else:
                lo, hi = knob.bounds
                if lo <= value <= hi:
                    values[key] = value
                    continue
                why = f"{value!r} is outside its band {lo}..{hi}"
        notes.append(f"{THRESHOLDS_SECTION}: {key!r} ignored — {why}")
    return values, notes


def set_project_threshold(name, raw, text):
    """THE PROJECT DOOR (T-14056, SPEC-1031 rule 7): set THRESHOLD key `name` to `raw` in the text of a
    project's `yitc-ops.yaml`. Pure — it reads and writes no file; the caller owns the write, the
    journal row and the commit. Returns `(old, new, new_text)`; `new_text` is None when the section
    already holds that value (a repeat run changes nothing).

    Refuses — raising SettingsRefused, so the caller writes nothing — an unknown key; a GATE key, by
    the SAME `_refuse_gate` every other door uses (no override here either); a key of a machine class
    (PERFORMANCE, BINDING, BUDGET), which belongs in the machine file; a threshold declaring no band,
    which the section reader would ignore (rule 5); a value `coerce` refuses, its band included; and a
    carrier this edit cannot change safely: unparseable, not a mapping, a `thresholds:` that is not a
    mapping or is a non-empty flow mapping, or one that repeats the section or the key.

    WHERE IT EDITS COMES FROM THE PARSER, never from a pattern over lines (audit-pre T-14056: a line
    pattern lost an inline comment, normalized line endings and missed a quoted section key). The
    composed node of the section — and of the key, when present — gives the exact character span to
    change: an existing key's VALUE span is replaced and nothing around it; a new key is one line
    inserted after the section's last entry, in the section's indentation and the file's own line
    ending; a missing section is appended, keeping a file that ends without a newline that way. Every
    other byte stays as it was, and the result is then PROVED by parsing both texts: the new carrier
    must equal the old one with `thresholds.<name>` set and nothing else changed, and hold the section
    and the key once each, or the edit is refused."""
    import re
    import yaml
    knob = BY_NAME.get(name)
    if knob is None:
        raise SettingsRefused(
            f"unknown key {name!r} — not in the tunable inventory, so it would be a value nobody "
            f"reads. `bin/yitc-v2 config list` prints every knob and its class.")
    if knob.cls != THRESHOLD:
        if not knob.is_settable:
            _refuse_gate(name)
        raise SettingsRefused(
            f"{name} is a {knob.cls.upper()}-class value — it belongs to the MACHINE, not the project: "
            f"set it with `bin/yitc-v2 config set {name} <value>` (without --project).")
    if knob.bounds is None:
        raise SettingsRefused(f"{name} is a threshold that declares no band — the `{THRESHOLDS_SECTION}:` "
                              f"reader ignores it (SPEC-1031 rule 5), so writing it would change nothing")
    value = coerce(knob, raw)

    def refuse(why):
        raise SettingsRefused(f"the project's yitc-ops.yaml {why} — nothing was written")

    def nodes(src):
        """(root mapping node or None, [(key, value) node pairs of the section], section value node)."""
        root = yaml.compose(src)
        if root is None:
            return None, [], None
        if not isinstance(root, yaml.MappingNode):
            refuse("is not a mapping")
        heads = [(k, v) for k, v in root.value if isinstance(k, yaml.ScalarNode) and k.value == THRESHOLDS_SECTION]
        if len(heads) > 1:
            refuse(f"declares `{THRESHOLDS_SECTION}:` {len(heads)} times — fix it first")
        if not heads:
            return root, [], None
        key, sect = heads[0]
        # The section must be WRITTEN at its own key: an alias (`thresholds: *x`) resolves to a node
        # written elsewhere, so an edit by its marks would change that other field (audit-post T-14056).
        if sect.start_mark.index < key.end_mark.index:
            refuse(f"`{THRESHOLDS_SECTION}:` is an alias of a node written elsewhere — this door edits "
                   f"only a section written in place; change it by a card")
        pairs = list(sect.value) if isinstance(sect, yaml.MappingNode) else []
        if pairs and sect.flow_style:
            refuse(f"`{THRESHOLDS_SECTION}:` section is written in flow style — this door edits only a "
                   f"block mapping")
        if sum(isinstance(k, yaml.ScalarNode) and k.value == name for k, _ in pairs) > 1:
            refuse(f"declares `{THRESHOLDS_SECTION}.{name}` more than once — fix it first")
        return root, pairs, sect

    try:
        ops = yaml.safe_load(text) if text.strip() else {}
        _root, pairs, sect = nodes(text)
    except yaml.YAMLError as exc:
        refuse(f"does not parse ({exc.__class__.__name__}) — fix the carrier first")
    ops = {} if ops is None else ops
    if not isinstance(ops, dict):
        refuse("is not a mapping")
    section = ops.get(THRESHOLDS_SECTION)
    if section is not None and not isinstance(section, dict):
        refuse(f"`{THRESHOLDS_SECTION}:` section is a {type(section).__name__}, not a mapping — fix it first")
    old = (section or {}).get(name)
    if name in (section or {}) and old == value and type(old) is type(value):
        return old, value, None

    eol = "\r\n" if "\r\n" in text else "\n"
    rendered = repr(value) if isinstance(value, float) else str(value)
    entry = f"{name}: {rendered}"

    def line_end(src, i):
        """The index just past the line terminator of the line holding index `i` (or the end)."""
        j = src.find("\n", i)
        return len(src) if j < 0 else j + 1

    def insert_line(src, at, line):
        if at == len(src) and src and not src.endswith("\n"):
            return src + eol + line                   # a file ending without a newline still does
        return src[:at] + line + eol + src[at:]

    def span(node):
        return text[node.start_mark.index:node.end_mark.index]

    def as_written(node):
        """True when the node's span is ONLY the scalar, on one line: plain and equal to its value, or
        quoted. A block scalar (its span holds the `|`/`>` header and its comment), a multi-line plain
        scalar, an anchor or a tag would each change bytes outside the value — refused. An alias
        (`k: *v`) resolves to the anchored node, whose span carries its `&v`, so it is refused too."""
        s = span(node)
        if not isinstance(node, yaml.ScalarNode) or "\n" in s or "\r" in s:
            return False
        if node.style is None:
            return s == node.value
        return node.style in ("'", '"') and len(s) >= 2 and s[0] == s[-1] == node.style

    hit = next(((k, v) for k, v in pairs if isinstance(k, yaml.ScalarNode) and k.value == name), None)
    if sect is None:
        new_text = insert_line(text, len(text), f"{THRESHOLDS_SECTION}:{eol}  {entry}")
    elif hit is not None:
        v = hit[1]
        if not as_written(v):
            refuse(f"writes `{THRESHOLDS_SECTION}.{name}` as {span(v)!r} — not a one-line plain or quoted "
                   f"scalar (a block or multi-line scalar, an anchor or a tag), so this door cannot change "
                   f"its value alone; change it by a card")
        new_text = text[:v.start_mark.index] + rendered + text[v.end_mark.index:]
    elif pairs:                                   # a block mapping (`nodes` refused a flow one)
        last = pairs[-1][1]
        at = line_end(text, max(last.start_mark.index, last.end_mark.index - 1))
        new_text = insert_line(text, at, " " * pairs[0][0].start_mark.column + entry)
    elif not pairs:
        # an empty section: `thresholds:` (implicit null), `thresholds: ~` / `null`, `thresholds: {}`
        if not (span(sect).strip() in ("", "~", "null", "Null", "NULL")
                or re.fullmatch(r"\{\s*\}", span(sect))):
            refuse(f"writes an empty `{THRESHOLDS_SECTION}:` as {span(sect)!r} (a tag or another form) — "
                   f"this door edits `{THRESHOLDS_SECTION}:`, `~`, `null` or `{{}}` only; change it by a card")
        s, e = sect.start_mark.index, sect.end_mark.index
        stripped = text[:s] + text[e:]
        new_text = insert_line(stripped, line_end(stripped, s), f"  {entry}")
    expected = dict(ops)
    expected[THRESHOLDS_SECTION] = {**(section or {}), name: value}

    def typed(obj):
        """`obj` with every scalar paired with its type, so `5` and `5.0` (or `1` and `true`) differ."""
        if isinstance(obj, dict):
            return ("dict", sorted(((typed(k), typed(v)) for k, v in obj.items()), key=repr))
        if isinstance(obj, list):
            return ("list", [typed(v) for v in obj])
        return (type(obj).__name__, obj)

    try:
        proved = typed(yaml.safe_load(new_text)) == typed(expected)
        _r2, pairs2, _s2 = nodes(new_text)
        proved = proved and sum(isinstance(k, yaml.ScalarNode) and k.value == name for k, _ in pairs2) == 1
    except (yaml.YAMLError, SettingsRefused):
        proved = False
    if not proved:
        raise SettingsRefused(f"the edit of `{THRESHOLDS_SECTION}.{name}` would change more of "
                              f"yitc-ops.yaml than that one key — refused; nothing was written")
    return old, value, new_text


_NOTES_SAID: "set[str]" = set()


def say_notes(notes, stream=None) -> None:
    """Print each report-only `thresholds:` line (SPEC-1031 rule 5) ONCE per process, on stderr — the
    one way a THRESHOLD reader with no listing of its own surfaces what `in_force` returned in
    `notes`, so no read ignores an entry silently and two reads of one section never repeat a line.
    `config list` prints its own block instead."""
    import sys
    out = sys.stderr if stream is None else stream
    for line in notes:
        if line not in _NOTES_SAID:
            _NOTES_SAID.add(line)
            print(f"yitc-v2: {line} (report-only)", file=out)


def applied(knob: Knob, env, file_values, section_values):
    """`(value, source)` — the value a reader applies for `knob` and where it came from, given the
    three layers already read (`env` a mapping, `file_values` what `load` returned, `section_values`
    what `project_thresholds` returned). The one place the per-class order lives (SPEC-1031 rule 4):

      BUDGET    — environment (type-checked, not banded) > machine file > built-in default.
      escape    — a knob declaring `escape` (T-13967) reads its environment value first the same way,
                  whatever its class: its own spec puts that value on top as an escape hatch.
      THRESHOLD — the project section > built-in default; the environment and the file are not read.
      others    — machine file > built-in default, as `effective` answers: the environment layer of a
                  performance knob is applied by its own read site and not restated here, and a
                  GATE key has no file value, so it reads its built-in default.

    Sources: `env`, `machine-file`, `yitc-ops.yaml` (the project's `thresholds:` section),
    `built-in`."""
    if knob.cls == THRESHOLD:
        if knob.name in section_values:
            return section_values[knob.name], "yitc-ops.yaml"
        return knob.default, "built-in"
    if knob.escape or (knob.cls == BUDGET and knob.is_settable):  # an unbanded budget reads as GATE
        raw = env.get(knob.name)
        if raw is not None and str(raw).strip():
            try:
                return coerce(knob, raw, banded=False), "env"
            except SettingsRefused:
                pass                   # a malformed environment value is an absent one
    if knob.name in file_values:
        return file_values[knob.name], "machine-file"
    return knob.default, "built-in"


def in_force(name, *, env=None, ops=None) -> dict:
    """The value in force for inventory key `name` and its source, as the fields a run row or a
    signal records (SPEC-1031 rule 6): `{"key", "value", "source", "notes"}`. `ops` is the project's
    parsed ops carrier (read only for a THRESHOLD). `notes` carries, for a THRESHOLD, every
    report-only line the `thresholds:` section produced (SPEC-1031 rule 5) — so a read through this
    helper never ignores a bad entry silently; the caller prints them once (`say_notes`, or its own
    listing) — and is empty for any
    other class. A settings fault never raises — the file is an override layer (SPEC-0193 rule 6);
    an unknown `name` is a caller's error and raises KeyError."""
    knob = BY_NAME[name]
    env_map = os.environ if env is None else env
    try:
        file_values = load(env) if knob.is_settable else {}
    except Exception:                  # noqa: BLE001 — a settings fault is never a caller's problem
        file_values = {}
    section_values, notes = project_thresholds(ops) if knob.cls == THRESHOLD else ({}, [])
    value, source = applied(knob, env_map, file_values, section_values)
    return {"key": name, "value": value, "source": source, "notes": notes}


# ── T-13831: the first-install LOAD RECOMMENDATION ───────────────────────────────────────────
def layer_share_allotment_note(key, old, new, cores, share_sum=None) -> "list[str]":
    """T-13876 (SPEC-0152 rule 16 §layer_worker_shares) — what `config set` says when the per-verify
    worker ceiling CHANGES, for projects that declare `verify.layer_worker_shares`.

    The ceiling bounds the allotment every verify layer reads whole; a project that declares shares
    scales its runners by it, and the sum of its shares is the project's own and unchecked. So a
    change here multiplies what such a project asks for by new/old, and this is the one line that
    says so at the moment of the change.

    `share_sum` is the sum of the shares the project THIS CALL RUNS IN declares (None when it
    declares none or the call cannot read it): with it the lines carry that project's numbers;
    without it they carry the plain statement — machine settings are host-wide, and a `config set`
    knows at most the one project it runs in. `old` None is an unset key, shown as its default.

    Returns [] for any other key, for a value that did not change, and for a non-positive or
    non-int `new`. Pure: no I/O, nothing raised. REPORT-ONLY — the caller prints the lines after
    the write it has already made; nothing is refused on them."""
    name = "lib.worktree._VERIFY_WORKER_CEILING"
    if key != name or isinstance(new, bool) or not isinstance(new, int) or new <= 0:
        return []
    before = BY_NAME[name].default if old is None else old
    if isinstance(before, bool) or not isinstance(before, int) or before == new:
        return []
    host = (f"this host has {cores} cores" if isinstance(cores, int) and not isinstance(cores, bool)
            and cores > 0 else "this host's processor count could not be read")
    lines = [f"  note: every verify layer reads the worker allotment whole — now up to {new}, before "
             f"up to {before}. A project that declares `verify.layer_worker_shares` scales its runners "
             f"by it, so shares that sum to S ask for up to S x {new} worker slots when those layers "
             f"run at the same time; {host}."]
    if isinstance(share_sum, (int, float)) and not isinstance(share_sum, bool) and share_sum > 0:
        lines.append(f"  this project declares shares that sum to {share_sum:.4g}: up to "
                     f"{share_sum * before:.4g} worker slots before, up to {share_sum * new:.4g} now.")
    lines.append("  Report-only: the sum stays each project's to choose and nothing is refused "
                 "(SPEC-0152 rule 16).")
    return lines


def recommend_load_settings(cores, mem_total_mb=None, *, per_worker_mem_mb=None):
    """Starting values for how a host that has set NONE of them shares its cores between a land and
    the Stage-6 runs (T-13831, owner directive events.jsonl#ts=2026-10-10T04:21:15Z). PURE: host
    facts in, a recommendation out — it reads no file and writes nothing. `init` shows the result
    and writes it through `set_value` only on the person's yes.

    THE FORMULA (worked out with the owner for a 32-core host):
      reserve      = max(2, cores // 8)           cores a land does not take. There is no reserve
                                                  setting: it is the gap between the cores and the
                                                  land ceiling.
      land ceiling = cores - reserve              a land gets everything else, for land speed.
      Stage-6 runs = clamp((cores + 5) // 10, 1, 4)   cores / 10 rounded half up.
      Stage-6 share = 0.75 / runs                 so all simultaneous runs together take about 3/4
                                                  of the land ceiling (one run's width is
                                                  int(ceiling * share), floored at 1 — the
                                                  arithmetic of `task._stage6_local_workers`).
      Stage-6 nice = 19                           the lowest CPU priority, so a Stage-6 run yields
                                                  the processor to a land (CPU only: it does not
                                                  remove contention for memory or disk).
      fleet width  = runs + 1                     one worker per Stage-6 run, plus one landing.
    32 cores -> 4 / 28 / 3 / 0.25 / 19 / 4;  8 cores -> 2 / 6 / 1 / 0.75 / 19 / 2.

    Returns None when `cores` is not an integer >= 3: below that the reserve of 2 leaves no core
    for a land, so there is nothing to recommend and the built-in defaults stand.

    MEMORY. `mem_total_mb` is the machine's INSTALLED memory, not the amount free at this moment:
    the recommendation describes the machine, and the caller's output has to be the same on two runs
    on one host (a figure that moves between runs would make it differ). `per_worker_mem_mb` is what
    the caller's governor budgets per verify worker; the peak is a land at its ceiling plus every
    Stage-6 run at its width, all five values being the recommended ones (the caller offers them
    only as a whole set). `mem_short` is True only when both figures are known and the installed
    memory is below that peak — an unknown figure is reported as unknown (None), never as enough.
    """
    try:
        cores = int(cores)
    except (TypeError, ValueError):
        return None
    if cores < 3:
        return None
    reserve = max(2, cores // 8)
    ceiling = min(cores - reserve, BY_NAME["lib.worktree._VERIFY_WORKER_CEILING"].bounds[1])
    runs = min(4, max(1, (cores + 5) // 10))
    share = 0.75 / runs
    stage6_width = max(1, int(ceiling * share))
    peak_workers = ceiling + runs * stage6_width
    try:
        mem_needed_mb = peak_workers * int(per_worker_mem_mb) if per_worker_mem_mb else None
    except (TypeError, ValueError):
        mem_needed_mb = None
    try:
        mem_total_mb = None if mem_total_mb is None else int(mem_total_mb)
    except (TypeError, ValueError):
        mem_total_mb = None
    mem_short = (None if mem_needed_mb is None or mem_total_mb is None
                 else mem_total_mb < mem_needed_mb)
    return {
        "cores": cores, "reserve": reserve, "stage6_width": stage6_width,
        "peak_workers": peak_workers, "mem_needed_mb": mem_needed_mb,
        "mem_total_mb": mem_total_mb, "mem_short": mem_short,
        "settings": [
            ("lib.worktree._VERIFY_WORKER_CEILING", ceiling,
             f"a land runs up to {ceiling} test workers on the {cores} cores, leaving {reserve} "
             f"core(s) that a land does not take"),
            ("YITC_VENUE_STAGE6_MAX_CONCURRENT", runs,
             f"at most {runs} Stage-6 test run(s) at the same time"),
            ("YITC_VENUE_STAGE6_WORKERS_FRACTION", share,
             f"each Stage-6 run uses up to {stage6_width} test worker(s), so {runs} at once use up "
             f"to {runs * stage6_width} against a land's {ceiling}"),
            ("YITC_VERIFY_WORKER_NICE", 19,
             "Stage-6 tests run at the lowest CPU priority, so they yield the processor to a land"),
            ("lib.journal.MAX_FLEET_WIDTH", runs + 1,
             "suggested number of workers at once: one per Stage-6 run plus one landing"),
        ],
    }
