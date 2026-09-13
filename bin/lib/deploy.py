"""cmd_deploy verb — the governed deploy / rollback seam (SPEC-0094 §1).

GOVERNING SPEC: SPEC-0094 §1 ("The `deploy` verb + the `deploy_completed` event"). That spec is
`proposed` (status), activated by T-9395 once the whole deploy-adoption mechanism is in — the
work-first pattern (SPEC-0005 rule 4 / T-0199): the implementing code lands while the spec is
proposed, the spec activates at the mechanism's closure. This card (T-9390) ships SPEC-0094's intended
`bin/lib/deploy.py#cmd_deploy` build anchor; the audit-pre YELLOW that flagged "no active governing
spec in the coverage table" is answered HERE — the verb is governed by the proposed SPEC-0094, not
spec-less.

`bin/yitc-v2 [-C <path>] deploy [--rollback]` runs the project-declared `deploy:` (or `rollback:`)
command from `yitc-ops.yaml` (the SPEC-0093 ops-contract carrier). That project command IS the
executable deploy-seam gate: it runs the project's own smoke/health check inline and exits non-zero if
the new revision is not actually serving — so a broken revision is NEVER left live (SPEC-0094 §1). On
exit-0 the verb emits a `deploy_completed` journal event (SPEC-0025 catalog) carrying
`{revision, project, kind}` — emitted on EVERY deploy AND every rollback (a rollback is a deploy of the
prior revision, recorded `kind: "rollback"`), so the current-live revision is always the latest
`deploy_completed` event's `revision`. A non-zero command exit leaves NO event (the broken revision is
not recorded live). Hand-running the deploy command without this verb is the forbidden hand-work
(AGENTS §Verb-execution discipline) — only the verb leaves the governed `deploy_completed` evidence.

Like cmd_init (T-9380), this module back-imports NOTHING: every host global/helper it reads is INJECTED
as a keyword-only param by the host residue wrapper at call time, so monkeypatches on the host names
stay honored.
"""
from __future__ import annotations

import argparse
import os
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
from lib import events as events_mod   # T-11444: the SPEC-0190 segment-set resolver
from lib import journal as journal_mod  # T-11444: the SPEC-0190 segment-aware journal folds

CONSUMER_OPS_CONTRACT = "yitc-ops.yaml"   # SPEC-0093 rule 1 — one carrier file at the repo root

# The governed-deploy RUN-MARKER (SPEC-0094 §1, X-0160). cmd_deploy EXPORTS this env var into the
# project deploy:/rollback: command's environment (its value = the resolved revision — distinctive +
# useful, but the guard only checks PRESENCE). A consumer's hand-runnable deploy.sh embeds the
# DEPLOY_GUARD_SNIPPET below, which REFUSES a raw hand-run (marker ABSENT) — closing the hand-run hole
# (fp=offered-raw-deploy-sh-instead-of-governed-deploy-verb): a raw run silently skips the class-gate +
# pg_dump + the deploy_completed evidence emit. Only the verb sets the marker, so only a verb-invoked
# deploy passes the guard.
DEPLOY_RUN_MARKER_ENV = "YITC_DEPLOY_VERB"

# The canonical guard preamble a deploying consumer pastes at the TOP of its hand-runnable deploy.sh
# (delivered to consumers via a cross — cross-territory, never edited here). It refuses a raw hand-run
# unless the governed verb set the run-marker. Homed HERE (single-SoT) so the marker name + the
# run-via-verb guidance cannot drift from what the verb actually exports; the T-9785 test writes a
# deploy.sh from this exact snippet to prove behaviors 2 & 3. Keep POSIX-sh portable (`sh`, not `bash`).
#
# TWO FLAVOURS, one builder (T-10736, X-0597). `cmd_deploy` exports the run-marker for BOTH kinds, so a
# consumer legitimately embeds this guard in its `rollback:` command script too — and the guard's refusal
# is a RECOVERY INSTRUCTION. A forward-flavour refusal met on the ROLLBACK path hands the operator the
# WRONG verb form on the emergency path, where a wrong instruction costs the most and the operator has
# the least slack to notice it (boomrocket, X-0597). So the invocation form + the "what a raw run skips"
# line are parameterized by `kind` — one builder, so the marker name and the run-via-verb guidance still
# cannot drift between flavours. The forward text is UNCHANGED (byte-identical, pinned by T-9785).
def _guard_snippet(kind: str) -> str:
    """Build the governed-run guard preamble for `kind` ("deploy" | "rollback").

    The two flavours differ ONLY in the recovery instruction, because the two paths genuinely skip
    different things: a forward hand-run skips the class-gate + the Class-C1 pg_dump + the
    deploy_completed emit; a rollback runs NEITHER gate (a rollback redeploys a prior, already-gated
    image — SPEC-0155 rule 1), so what a raw rollback hand-run silently skips is the evidence emit that
    records WHICH revision was left live. Naming the forward gates there would be false as well as
    misdirecting."""
    if kind == "rollback":
        script, what = "rollback.sh", "rollback"
        invocation = "deploy --rollback <rev>"
        skips = ("a raw hand-run skips deploy_completed, so the journal keeps reading the "
                 "PRE-rollback revision as live")
        governed = ("# This rollback script is GOVERNED: it must be run through the deploy verb, which\n"
                    "# resolves + validates the target revision and emits the deploy_completed evidence\n"
                    f"# recording what is now live, exporting {DEPLOY_RUN_MARKER_ENV}.")
    else:
        script, what = "deploy.sh", "deploy"
        invocation = "deploy --class {A|S|C1|C2}"
        skips = ("a raw hand-run skips the class-gate, the Class-C1 pg_dump + deploy_completed")
        governed = ("# This deploy script is GOVERNED: it must be run through the deploy verb, which\n"
                    "# runs the class-gate (and, for Class C1, the declared pre-deploy pg_dump backup)\n"
                    f"# and emits the deploy_completed evidence, exporting {DEPLOY_RUN_MARKER_ENV}.")
    return (
        "# --- yitc-v2 governed-deploy guard (SPEC-0094 §1) ------------------------------\n"
        f"{governed}\n"
        "# A raw hand-run silently skips ALL of that — refuse it.\n"
        f'if [ -z "${{{DEPLOY_RUN_MARKER_ENV}:-}}" ]; then\n'
        f'  echo "{script}: REFUSED — this {what} is governed and must run via the verb." >&2\n'
        f'  echo "  run via bin/yitc-v2 -C <path> {invocation}" >&2\n'
        f'  echo "  ({skips} — SPEC-0094 §1)" >&2\n'
        "  exit 1\n"
        "fi\n"
        "# --- end yitc-v2 governed-deploy guard -----------------------------------------\n"
    )


DEPLOY_GUARD_SNIPPET = _guard_snippet("deploy")
DEPLOY_ROLLBACK_GUARD_SNIPPET = _guard_snippet("rollback")

# The kernel-owned deploy-class vocabulary (SPEC-0097 §2). UNIFORM for every deploying consumer — a
# project NEVER redefines it (it owns only the per-class VALUES on the carrier). Surfaced as the
# `--class` argparse choices in the host parser.
DEPLOY_CLASSES = ("A", "S", "C1", "C2")

# The host-config dimension (SPEC-0097 §10) — its OWN class, ORTHOGONAL to the A/S/C1/C2 reversibility
# vocabulary above (deliberately NOT a member of DEPLOY_CLASSES — a host nginx / vhost change is a
# previously-uncovered case: it was never `kind==deploy`-classified). A host config is NOT image-
# reversible (host conf is not an image), so it is never autonomously image-deployed; it rides the
# human-apply seam (SPEC-0111) and its per-class evidence is {apply-confirmation, server-wide health
# sweep, reconciliation}, enforced at task-close (SPEC-0094). Kernel-owned + uniform like A/S/C1/C2.
HOST_CONFIG_CLASS = "host-config"


def _read_host_config(deploy_section) -> "dict | None":
    """Read the project's declared `deploy.host_config` block as PROJECT ops config (SPEC-0093 rule 14).

    The HOST deploy surface — the owned vhost file(s), the host `live_base_url`, and the human-gated
    apply recipe — is per-project ops config the deploy/apply verbs READ as config, NEVER a kernel-read
    governance scalar (SPEC-0093 §Parameters non-whitelist; the spec stays `consumed: false`). This is a
    pure, NON-behavioral read: it returns the DECLARED mapping (a `vhost_files`-bearing block) or None
    when the subfield is ABSENT or WAIVED. It does NOT gate, refuse, or alter any deploy/rollback
    outcome — the apply ACTION that consumes these values is SPEC-0111's seam (a later card), not here.
    The carrier sweep (`init`, _sweep_ops_carrier) already fail-closes a malformed/unanswered block, so a
    DECLARED block reaching here carries the rule-14 shape."""
    if not isinstance(deploy_section, dict):
        return None
    hc = deploy_section.get("host_config")
    if not isinstance(hc, dict) or "vhost_files" not in hc:
        return None   # absent or waived — no declared host-config surface
    return hc


class _GateDecision(NamedTuple):
    """The deploy-autonomy gate's verdict (SPEC-0097 §5/§8). PURE data — no side effects — so the
    routing is unit-testable in isolation from git/subprocess (the T-9415 structural AC)."""
    proceed: bool            # True ⇒ the deploy may run; False ⇒ ESCALATE (refuse, no deploy_completed)
    mode: str                # 'pre-policy' | 'autonomous' | 'owner-approved' | 'escalate'
    deploy_class: "str | None"
    evidence: "dict | None"  # the SELECTED per-class evidence requirement (carrier classes.<X>), or None
    message: str             # human-facing reason (printed by cmd_deploy)


def _classify_deploy_gate(policy, deploy_class, owner_approved) -> _GateDecision:
    """Classify a deploy A/S/C1/C2 + route the per-class evidence-requirement SELECTION (SPEC-0097).

    This is the WHEN-layer the deploy verb reads at deploy time — the policy/WHEN layer SPEC-0094 §4
    explicitly DEFERRED to SPEC-0097 (it re-homes NO SPEC-0094 verb mechanic). It DECIDES whether the
    existing, explicitly-invoked `deploy` verb may proceed without an extra owner ceremony (SPEC-0097 §8
    — a GATE, never an auto-trigger). It SELECTS each class's evidence requirement from the carrier;
    EXECUTING that evidence is a separate step, mirroring SPEC-0094 §3's declaration-gate-vs-execution-gate
    split. For Class C1 the execution lives in `cmd_deploy` → `_run_c1_backup` (the pre-deploy pg_dump,
    T-10259/X-0261 — previously the block was selected here and then dropped, so no dump was ever taken).
    For Class S it lives in `cmd_deploy` → `_run_class_s_security_probe` (the pre-deploy security probe,
    T-10279 — same selected-then-dropped shape: nothing executed the probe, so a violated or un-probeable
    security property still deployed autonomously).

    STILL NOT EXECUTED ANYWHERE (T-10279's audit, grep-proven — do not assume otherwise): C1's
    `restore_drill` and its delayed re-check. Those remain declaration-only; a follow-up task carries them.
    An `evidence:` prose string is never executable by anything — only the named runnable keys are
    (`classes.C1.pg_dump`, `classes.S.security_probe`).

    Args:
      policy: the carrier `deploy.policy` mapping (`ops['deploy']['policy']`), or None when absent.
      deploy_class: the explicit `--class` value (one of DEPLOY_CLASSES) or None. Classification is
        EXPLICIT — never an auto-detector (AGENTS §"When NOT to add a mechanism" forbids a new behavioral
        detector); a deploy ships many changes (SPEC-0094 §4) so the class cannot come from one task YAML.
      owner_approved: True when `--owner-approved` was passed (the owner took the escalation decision).

    Fail-closed routing (SPEC-0097 §2/§5/§6/§9)."""
    # 0. HOST-CONFIG dimension (SPEC-0097 §10) — recognized FIRST and returned EARLY, so the A/S/C1/C2
    #    routing below is byte-for-byte UNCHANGED for every other class (the additive-only AC). A host
    #    nginx / vhost change is its OWN class, ORTHOGONAL to the A/S/C1/C2 autonomy policy: a host conf
    #    is NOT image-reversible (host conf is not an image, SPEC-0097 §10), so the image `deploy` verb
    #    NEVER applies it autonomously — it rides the human-apply seam (SPEC-0111) and its per-class
    #    evidence {apply-confirmation, server-wide health sweep, reconciliation} is enforced at task-close
    #    (SPEC-0094). The gate therefore REFUSES an image deploy of it (proceed=False, mode=host-config),
    #    routing the operator to the apply seam — INDEPENDENT of the project's deploy.policy autonomy
    #    stance (evidence=None: the three-evidence requirement is fixed in the spec / close-gate, not a
    #    carrier-selected RTO/RPO risk, so cmd_deploy renders no spurious risk line).
    if deploy_class == HOST_CONFIG_CLASS:
        return _GateDecision(False, "host-config", HOST_CONFIG_CLASS, None,
                             "Class host-config (a host nginx / vhost change) is NOT image-deployable "
                             "autonomously — a host config is not an image, so an image rollback cannot "
                             "undo it (SPEC-0097 §10). Apply it via the human-apply seam (SPEC-0111); its "
                             "evidence {apply-confirmation, server-wide health sweep, reconciliation} is "
                             "enforced at task-close (SPEC-0094). No deploy_completed via the image verb.")
    # 1. ABSENT policy (None — a pre-policy carrier has no `deploy.policy` key) ⇒ PRE-POLICY: the verb
    #    proceeds exactly as it did before the policy existed (SPEC-0097 §9 — the owner-gated discipline
    #    is out-of-band: the AI asked the owner before invoking). The autonomous CLASS path is NOT
    #    exposed. Keeps every pre-policy carrier (T-9390 tests) + a fresh born-WAIVED consumer working.
    if policy is None:
        return _GateDecision(True, "pre-policy", deploy_class, None,
                             "no deploy.policy block — pre-policy deploy (owner-gated discipline is "
                             "out-of-band; the verb proceeds, SPEC-0097 §9).")
    # 1b. MALFORMED policy (PRESENT but not a mapping — a hand-corrupted carrier) ⇒ FAIL-CLOSED escalate.
    #     A safety gate must NEVER be silently BYPASSED by a corrupt config: "present-but-wrong-type" is
    #     NOT "absent" (distinguished from None above so back-compat still proceeds). The init sweep
    #     (T-9413) is the other guard; the deploy verb fail-closes too (SPEC-0097 §9 fail-closed).
    if not isinstance(policy, dict):
        return _GateDecision(False, "escalate", deploy_class, None,
                             f"deploy.policy is MALFORMED (expected a mapping, got "
                             f"{type(policy).__name__}) — fail-closed (SPEC-0097 §9): a corrupt policy "
                             f"must REFUSE, never silently bypass the gate. Fix yitc-ops.yaml (re-run "
                             f"`init`). No deploy_completed.")
    classes = policy.get("classes")
    # 1c. MALFORMED classes (PRESENT but not a mapping) ⇒ FAIL-CLOSED escalate (same reasoning as 1b).
    if classes is not None and not isinstance(classes, dict):
        return _GateDecision(False, "escalate", deploy_class, None,
                             f"deploy.policy.classes is MALFORMED (expected a mapping, got "
                             f"{type(classes).__name__}) — fail-closed (SPEC-0097 §9); refusing. Fix "
                             f"yitc-ops.yaml (re-run `init`). No deploy_completed.")
    # 1d. WAIVED / no autonomous classes (absent or an empty mapping) ⇒ PRE-POLICY proceed: no autonomous
    #     path is exposed (SPEC-0097 §9). An empty `classes: {}` is not "declared" (init's sweep rejects
    #     it standalone); at deploy time there is no class to gate against — the waived-equivalent.
    if not classes:
        return _GateDecision(True, "pre-policy", deploy_class, None,
                             "deploy.policy is waived — no autonomous path (owner-gated, the pre-policy "
                             "default, SPEC-0097 §9); the verb proceeds.")

    # 2. Autonomous opt-in (`classes:` declared) ⇒ each deploy MUST be classified (fail-closed): without
    #    a class there is no per-class evidence requirement to select (SPEC-0097 §5).
    if deploy_class is None:
        return _GateDecision(False, "escalate", None, None,
                             "deploy.policy declares autonomous classes — `--class {A|S|C1|C2}` is "
                             "REQUIRED to select the per-class evidence requirement (SPEC-0097 §5). "
                             "Refusing an unclassified autonomous deploy (no deploy_completed).")

    # 3. Class C2 (destructive / irreversible / cannot meet restore budget) ⇒ NO autonomous deploy
    #    (SPEC-0097 §2/§5). The sole remaining real owner decision: escalate with the RTO/RPO risk,
    #    UNLESS the owner already took the decision (`--owner-approved` — then it is an owner-gated, NOT
    #    autonomous, deploy and DOES record the live revision).
    if deploy_class == "C2":
        if owner_approved:
            return _GateDecision(True, "owner-approved", "C2", classes.get("C2"),
                                 "Class C2 (destructive / irreversible) deploy proceeding under explicit "
                                 "--owner-approved — the owner took the RTO/RPO decision. NOT autonomous "
                                 "(SPEC-0097 §5).")
        return _GateDecision(False, "escalate", "C2", classes.get("C2"),
                             "Class C2 (destructive / irreversible / cannot meet restore budget) — NOT "
                             "deployable autonomously (SPEC-0097 §2/§5). ESCALATE to the owner with the "
                             "concrete RTO/RPO risk; re-run with --owner-approved only after the owner "
                             "takes the decision. No deploy_completed.")

    # 4. Class A/S/C1 ⇒ autonomous IFF its evidence requirement is DECLARED (declare-or-waive, §6).
    if deploy_class not in classes:
        # Fail-closed: opted into autonomous deploys but this class is undeclared — escalate (§6 — a
        # class is made non-applicable ONLY by an explicit waiver, never by silent omission).
        return _GateDecision(False, "escalate", deploy_class, None,
                             f"Class {deploy_class} is not declared in deploy.policy.classes for this "
                             f"project — fail-closed (SPEC-0097 §6 declare-or-waive). Declare "
                             f"classes.{deploy_class} (its evidence requirement) or waive it; escalating "
                             f"to the owner meanwhile. No deploy_completed.")
    spec = classes.get(deploy_class)
    if isinstance(spec, dict) and "waiver" in spec:
        # The project DECLARED this class non-applicable (an explicit per-class waiver, §6) ⇒ owner-gated.
        return _GateDecision(False, "escalate", deploy_class, spec,
                             f"Class {deploy_class} is declared NON-APPLICABLE (per-class waiver) for "
                             f"this project (SPEC-0097 §6) — a {deploy_class} deploy stays owner-gated; "
                             f"escalating. No autonomous deploy_completed.")
    return _GateDecision(True, "autonomous", deploy_class, spec,
                         f"Class {deploy_class} — autonomous deploy; SELECTED the per-class evidence "
                         f"requirement from deploy.policy.classes.{deploy_class} (SPEC-0097 §5). "
                         f"cmd_deploy EXECUTES the runnable half before deploying: C1's `pg_dump` "
                         f"(T-10259) and S's `security_probe` (T-10279). C1's `restore_drill` + delayed "
                         f"re-check are NOT executed by this verb — they stay operator-owned.")


def _build_source_violation(branch, dirty_paths, *, _is_ignorable_dirt, require_main_line=True) -> str:
    """Build-source discipline (SPEC-0094 §6). A FORWARD deploy builds the WORKING TREE, so that tree
    MUST be the landed+audited `main` line — else deploy ships un-landed / un-audited RUNTIME code (the
    incident: a non-main auto-session branch held the live code while `main` silently drifted 186 commits,
    and `deploy` built the tree with no branch/clean guard).

    PURE data (no git / no side effects) so the routing is unit-testable in isolation (the `_GateDecision`
    structural-AC pattern, T-9415). Returns a non-empty REFUSAL reason when the build source is unsafe,
    or "" when it is safe (HEAD on 'main' AND no un-landed RUNTIME dirt).

    Unsafe = HEAD not on 'main' (a feature/work branch OR a detached HEAD — `branch` empty) OR any
    un-landed RUNTIME-SOURCE dirt. `_is_ignorable_dirt(path) -> bool` (injected) decides what is NOT
    deployed runtime: non-runtime methodology/paperwork surfaces (the SPEC-0094 §3 allowlist — tasks/
    specs/ tests/ *.md events.jsonl graph/ …) AND transient operational churn (`journal-sync-state/`,
    `.yitc/` session state) the system folds/gitignores everywhere. Reusing §3's own allowlist keeps the
    deploy gate consistent with the live_probe gate — neither treats paperwork as deployable (no new
    classification).

    `require_main_line=False` (T-12066 / SPEC-0094 §6, X-1261) drops the MAIN-LINE half ONLY — the
    caller passes it for a target positively declared `targets.<name>.production: false`. A
    non-production target EXISTS to exercise code that is not yet on `main`, and SPEC-0049 rule 3
    requires that sandbox be deployed THROUGH this governed verb; asserting the landed main line there
    made the two rules contradict (measured on aiseller: T-0466 closed with both probes DEFERRED).
    The RUNTIME-SOURCE DIRT half is deliberately NOT scoped and still refuses on such a target: an
    un-landed COMMIT is the reviewable artifact a sandbox is meant to prove, while an uncommitted
    working tree is not an artifact at all — nothing names what shipped. Default True keeps every
    other caller, and every refusal string, byte-identical."""
    problems: list[str] = []
    if require_main_line and branch != "main":
        where = "detached (no branch)" if not branch else f"branch '{branch}'"
        problems.append(f"HEAD is on {where}, not 'main' — a forward deploy must build the landed "
                        f"'main' line (run from main / `land` first)")
    source_dirt = sorted(p for p in dirty_paths if not _is_ignorable_dirt(p))
    if source_dirt:
        shown = ", ".join(source_dirt[:8])
        more = "" if len(source_dirt) <= 8 else f" (+{len(source_dirt) - 8} more)"
        problems.append(f"working tree has uncommitted RUNTIME-SOURCE changes: {shown}{more} — commit + "
                        f"`land` them before deploying (non-runtime paperwork + journal/derived churn is "
                        f"ignored)")
    return "; ".join(problems)


class _JournalFold(NamedTuple):
    """The leg-1 fold decision at the ROLLBACK seam. PURE data (mirrors `_GateDecision`), so the
    routing is unit-testable in isolation from git/subprocess."""
    fold: bool
    reason: str          # why we are folding / why we are skipping — always printed, never silent


def _journal_fold_plan(kind, branch, ev_dirty, valid_append, merge_in_progress) -> _JournalFold:
    """Leg 1 of the journal-aware rollback (T-10633 / X-0479): may we FOLD a dirty `events.jsonl` into a
    scoped direct-to-main commit before the rollback command switches the tree?

    THE PROBLEM. For mounted-code delivery the real reversal path IS the code checkout (SPEC-0097 §2 —
    an image rollback reverses nothing there), so the project's `rollback:` command runs `git checkout
    <rev>`. git REFUSES that checkout while `events.jsonl` is dirty — and D-0049 SANCTIONS exactly that
    dirt (no-worktree journal appends on the main checkout: deviation captures, session receipts). So the
    system's own discipline hands the reversal a tree it cannot switch. X-0479 (boomrocket, 2026-07-16
    drill): 2 stash pushes, `stash pop` then refused on the dirty file, forcing a HAND union-merge of
    journal lines mid-drill. Folding first makes the tree clean, so the reversal simply runs.

    NEVER A GATE — the load-bearing constraint. A rollback is the ALWAYS-AVAILABLE reversal (SPEC-0097
    §2: "you must always be able to roll back"). This helper exists to REMOVE an obstacle, so it must
    never become one: every not-fold answer here is a SKIP with a printed reason, never a refusal, and
    the caller proceeds to the reversal regardless. That is the deliberate posture DIFFERENCE from
    `_scoped_selfcommit_preflight` (bin/yitc-v2), which `_die`s on these same conditions: its callers
    (`memory consume` / `memory seed`) are bookkeeping and MUST fail closed, whereas a journal-hygiene
    helper must never block a reversal. The RULE is shared (the caller injects that module's
    `_journal_dirt_is_valid_append` — one home for the append-only VALIDITY boundary, T-10494/X-0361);
    only the failure POSTURE is local.

    Fold requires ALL of:
      - `kind == "rollback"` — the only seam that switches the tree (a forward deploy builds it in
        place, and `_build_source_violation` already classifies journal dirt as ignorable there).
      - `branch == "main"` — a scoped direct-to-main commit is main-only, per the sanctioned exception
        (AGENTS-SESSIONS §Writes happen in a worktree); off main we must not author history.
      - `ev_dirty` — nothing to fold otherwise.
      - `valid_append` — the delta is purely appended, parseable JSON event lines. The FAIL-CLOSED
        strand/corruption boundary, identical to the other two legs: a delta that rewrites or removes a
        committed line is NEVER committed by this path. It is skipped, not refused — leg 2 still keeps
        every line, and the reversal still runs.
      - `not merge_in_progress` — an ambiguous/conflicted tree is never committed by this path.
    """
    if kind != "rollback":
        return _JournalFold(False, "not a rollback — the forward deploy builds the tree in place")
    if not ev_dirty:
        return _JournalFold(False, "events.jsonl is clean — nothing to fold")
    if branch != "main":
        return _JournalFold(False, f"HEAD is on '{branch or 'detached (no branch)'}', not 'main' — a "
                                   f"scoped direct-to-main fold applies on main only; leaving the "
                                   f"journal untouched (the rollback still runs)")
    if merge_in_progress:
        return _JournalFold(False, "an in-progress merge (MERGE_HEAD present) makes the tree ambiguous "
                                   "— not folding (the rollback still runs)")
    if not valid_append:
        return _JournalFold(False, "events.jsonl is NOT a valid append-only delta (a committed line is "
                                   "modified/removed, or an added line is blank/unparseable) — not "
                                   "folding it into a commit (fail-closed, T-10494/X-0361). The rollback "
                                   "still runs and the union-restore below still preserves every line; "
                                   "inspect it with `git diff HEAD -- events.jsonl`")
    return _JournalFold(True, "folding the sanctioned append-only journal dirt (D-0049) so the reversal's "
                              "checkout is not blocked by it (X-0479)")


def _journal_union_restore(snapshot, current, *, _dedup_events) -> "list[str] | None":
    """Leg 2 of the journal-aware rollback (T-10633 / X-0479): UNION the pre-rollback journal snapshot
    with whatever the tree holds after the command, deduped. Returns the restored lines, or None when
    the journal already holds everything (nothing to write).

    WHY LEG 1 IS NOT ENOUGH (audit-pre pass-1 RED, absorbed mode-(a)). Folding only unblocks the
    checkout — it does not survive it. `git checkout <older-rev>` REPLACES the working `events.jsonl`
    with the TARGET revision's older copy, so the lines just folded (including this session's own
    receipt) vanish from the LIVE file: the session ref then reads UNBACKED and the deploy verb refuses
    mid-drill — exactly the X-0479 symptom this card's AC2 pins. The commit preserves them in HISTORY;
    this restores them to the WORKING FILE.

    This is not a new mechanism: it is the SAME union+dedup `land` performs at its own tree-switch seam
    (SPEC-0002), applied at the one other seam that switches the tree — the card's own "reuse the
    existing land union-merge discipline". The caller injects `land`'s `_dedup_events`, so there is one
    home for the dedup key (CHARTER §P5).

    PURE (no git / no I/O) so the union logic is unit-testable in isolation. Order: the snapshot's lines
    first (the journal is append-only, and the pre-rollback file is the longer/newer line of history),
    then anything the checked-out copy holds that the snapshot lacks — no line from EITHER side is ever
    dropped, which is what makes "no journal line lost" structural rather than best-guess."""
    restored = _dedup_events(list(snapshot) + list(current))
    return None if restored == list(current) else restored


class _BackupPlan(NamedTuple):
    """The Class-C1 pre-deploy backup, read out of the SELECTED evidence block. PURE data, so the
    precondition is unit-testable in isolation from git/subprocess (mirrors `_GateDecision`)."""
    command: "str | None"
    budget_seconds: "int | None"
    error: "str | None"      # None ⇒ usable; else the fail-closed reason to print + refuse on
    expected_database: "str | None" = None   # SPEC-0148 §3 — declared ⇒ the dump's own header must name
                                             # it; absent ⇒ identity recorded, never enforced


PG_DUMP_SHAPES = ("`classes.C1.pg_dump: {command: <cmd>, dump_budget_s: <positive int>}` or "
                  "`classes.C1.pg_dump: <cmd>` + `classes.C1.pg_dump_budget_seconds: <positive int>`")


def _positive_budget(value) -> bool:
    """The ONE budget predicate, shared by the deploy boundary and init's birth guard (CHARTER §P5).
    `bool` is an `int` subclass — `True` must never read as a 1-second budget."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _normalize_pg_dump(evidence: dict):
    """The ONE carrier adapter: map EITHER accepted `pg_dump` shape onto the same `(command, budget)`
    pair. Returns `(command, budget, shape_error)` — the pair is raw; the single validation ladder in
    `_backup_precondition` judges it. Only the carrier TYPE is judged here.

    Two shapes exist because the kernel minted its contract (`pg_dump: <string>` +
    `pg_dump_budget_seconds`) from the ONE consumer that matched it, long after two others had already
    shipped the nested `{command, dump_budget_s}` mapping (boomrocket 448d066f, social-parser 510a370 —
    there was no shape contract when they were authored). The kernel minted it, so the kernel absorbs it
    HERE — at ONE boundary, never as two behavioral paths downstream (T-10286 / X-0267). A THIRD shape
    cannot appear silently: init's `deploy_policy_shape` hook refuses it where the carrier is BORN, and
    it shares this adapter — a birth check that diverged from the deploy check would let a carrier pass
    init and refuse at deploy, the declare-vs-execute gap this card closes."""
    raw = evidence.get("pg_dump")
    if isinstance(raw, dict):
        return raw.get("command"), raw.get("dump_budget_s"), None
    if raw is None or isinstance(raw, str):
        return raw, evidence.get("pg_dump_budget_seconds"), None
    return None, None, (f"`classes.C1.pg_dump` is a {type(raw).__name__}, which is not an accepted "
                        f"carrier shape — declare {PG_DUMP_SHAPES}")


def _backup_precondition(evidence) -> _BackupPlan:
    """PURE — extract the Class-C1 `pg_dump` command + its duration budget from the carrier block the
    gate SELECTED into `_GateDecision.evidence` (SPEC-0097 §4 «pg_dump preconditions»).

    THE SINGLE NORMALIZING BOUNDARY. Both accepted carrier shapes converge here onto ONE internal
    `_BackupPlan`; nothing below this function reads the raw carrier shape, so widening the carrier adds
    an adapter, never a second behavioral path (T-10286).

    FAIL CLOSED. A C1 deploy without a runnable backup is not a C1 deploy: an absent/blank command or a
    missing/non-positive budget REFUSES, it never degrades to «no backup was wanted». The budget is what
    makes §4's «a dump over budget ⇒ Class C2 (escalate), never assumed reversible» enforceable, so a
    dump with no budget cannot be run at all — there would be nothing to exceed."""
    if not isinstance(evidence, dict):
        return _BackupPlan(None, None, "the carrier declares no `classes.C1` block to back up from")
    command, budget, shape_error = _normalize_pg_dump(evidence)
    if shape_error:
        return _BackupPlan(None, None, shape_error)
    if not isinstance(command, str) or not command.strip():
        return _BackupPlan(None, None, f"`classes.C1.pg_dump` is absent or blank — no backup command to "
                                       f"run (declare {PG_DUMP_SHAPES})")
    if not _positive_budget(budget):
        return _BackupPlan(None, None, f"the `classes.C1` pg_dump budget is absent or not a positive "
                                       f"integer — without a budget the SPEC-0097 §4 over-budget ⇒ C2 "
                                       f"rule cannot be enforced (declare {PG_DUMP_SHAPES})")
    # OPTIONAL `expected_database` (SPEC-0148 §3) — read HERE, at the one carrier boundary, so no second
    # reader of the raw carrier appears downstream (the T-10286 invariant). ABSENT ⇒ None ⇒ record-only:
    # enforcement is opt-in per carrier, so this never re-blocks a consumer that declares no expectation.
    # PRESENT-BUT-MALFORMED is not ABSENT: a corrupt safety declaration REFUSES rather than silently
    # degrade to «no expectation was wanted» (the §1b/§1c malformed-policy precedent).
    expected = evidence.get("expected_database")
    if expected is not None and (not isinstance(expected, str) or not expected.strip()):
        return _BackupPlan(None, None, f"`classes.C1.expected_database` is declared but is not a non-blank "
                                       f"string (got {type(expected).__name__}) — a corrupt identity "
                                       f"expectation must refuse, never silently disable the check "
                                       f"(SPEC-0148 §3)")
    return _BackupPlan(command.strip(), budget, None, expected.strip() if expected else None)


# ---------------------------------------------------------------------------------------------
# SPEC-0149 — the post-deploy proof-obligation WINDOW: resolved + stamped HERE, at deploy time.
# ---------------------------------------------------------------------------------------------
RECHECK_WINDOW_UNITS = {"m": 60, "h": 3600, "d": 86400}
RECHECK_WINDOW_SHAPE = ("`recheck_within: <positive int><unit>` where unit is m|h|d "
                        "(e.g. `90m`, `24h`, `7d`)")


def _parse_recheck_window(raw):
    """PURE — parse a declared `recheck_within` into seconds. Returns `(seconds, error)`.

    FAITHFUL, NOT fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`). The
    three outcomes are kept DISTINCT because they mean different things to the caller:
      * `(None, None)`  — ABSENT. No obligation was declared. Legitimately open: a carrier that never
                          opted into a proof window owes nothing, which is what keeps this feature
                          from silently charging every deploy in the system.
      * `(None, "…")`   — DECLARED BUT MALFORMED. A corrupt proof declaration.
      * `(int, None)`   — a resolved window.
    A parser that collapsed the first two into "refuse" would refuse every deploy on every carrier
    that never declared a window; one that collapsed them into "no window" would silently disable a
    proof the carrier DID ask for. Only the reader (`cmd_deploy`) knows which is which — it holds the
    fail-closed judgement, exactly as `_backup_precondition`'s `expected_database` does.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, str) or not raw.strip():
        return None, (f"`recheck_within` is declared but is not a non-blank string (got "
                      f"{type(raw).__name__}) — declare {RECHECK_WINDOW_SHAPE}")
    token = raw.strip()
    unit = token[-1].lower()
    if unit not in RECHECK_WINDOW_UNITS:
        return None, (f"`recheck_within: {token}` has no recognized unit suffix — declare "
                      f"{RECHECK_WINDOW_SHAPE}")
    try:
        magnitude = int(token[:-1])
    except ValueError:
        return None, (f"`recheck_within: {token}` does not carry a positive integer magnitude — "
                      f"declare {RECHECK_WINDOW_SHAPE}")
    if magnitude <= 0:
        return None, (f"`recheck_within: {token}` is not a POSITIVE duration — a zero/negative "
                      f"observation window cannot express «re-check after the window» (SPEC-0097 §3); "
                      f"declare {RECHECK_WINDOW_SHAPE}")
    return magnitude * RECHECK_WINDOW_UNITS[unit], None


def _recheck_window(policy, evidence):
    """PURE — THE SINGLE RESOLUTION BOUNDARY for the obligation window (SPEC-0149 §1).

    Returns `(seconds, raw_declaration, error)`. This is the ONLY place the carrier's window
    declaration is read; nothing below it — and emphatically not the `debt.py` fold — resolves or
    defaults. That IS the ONE-WINDOW RULE: the stamping step resolves the declaration (including the
    class default) into the absolute value recorded on the event, and the fold reads only that.

    Resolution order (first hit wins):
      1. `classes.<X>.recheck_within` — this deploy class's explicit window.
      2. `policy.recheck_within`      — the CLASS DEFAULT: one policy-level declaration standing in
                                        for every class that does not override it.
      3. absent                       — no window, no obligation, ever.

    The class default is a CARRIER declaration, never a kernel-invented duration. A duration the
    kernel picked would charge every future autonomous C1/S deploy an obligation nobody asked for —
    the fold-side default's retro-charge failure (39 lines / 3 consumers, trial 2026-07-09) moved one
    layer up, where it would be no less wrong for being applied at write time. A consumer that wants
    the guard declares it; one that does not is unchanged (SPEC-0097 §9's pre-policy posture).

    Class-agnostic BY CONSTRUCTION (`lessons/proof-card-after-wiring-card.md`): resolution is written
    ONCE, so the Class-S half cannot silently miss what the Class-C1 half gets — the
    selected-then-dropped defect that recurred across sibling branches at X-0261.
    """
    for source in (evidence, policy):
        if isinstance(source, dict) and source.get("recheck_within") is not None:
            seconds, error = _parse_recheck_window(source.get("recheck_within"))
            return seconds, source.get("recheck_within"), error
    return None, None, None


def _discard_backup_artifact(artifact: Path) -> None:
    """Remove a dump that must NOT be trusted. An invalid archive sitting at a plausible filename is worse
    than no archive at all — the next operator restores from it. If it cannot be removed, rename it so the
    name itself carries the warning, and say so loudly. Never raises (it runs on the refusal path)."""
    try:
        artifact.unlink()
        return
    except FileNotFoundError:
        return
    except OSError as exc:
        quarantined = artifact.with_name(artifact.name + ".INVALID")
        try:
            artifact.replace(quarantined)
            print(f"deploy: could NOT delete the failed dump ({exc}); renamed it to {quarantined} — "
                  f"DO NOT RESTORE FROM IT.", file=sys.stderr)
        except OSError as exc2:
            print(f"deploy: could NOT delete or rename the failed dump at {artifact} ({exc}; {exc2}) — "
                  f"DO NOT RESTORE FROM IT.", file=sys.stderr)


def _create_new_artifact(backups: Path, revision, stamp) -> "tuple[Path, int]":
    """Create a FRESH dump file and return (path, open fd). NEVER opens an existing path.

    The name carries only a revision + a one-second stamp, so two deploys of the SAME revision inside the
    SAME second collide. That is not cosmetic: a later FAILED run would truncate the earlier VALID dump on
    write, and then DELETE it on its refusal cleanup — the backup gate would destroy the very artifact it
    exists to produce. `O_CREAT|O_EXCL` makes creation the collision test; on a taken name we try the next
    suffix. Exhausting the suffixes REFUSES the deploy (never silently reuses a name)."""
    base = f"pg_dump-{revision[:12]}-{stamp}"
    for n in range(100):
        artifact = backups / (f"{base}.dump" if n == 0 else f"{base}.{n}.dump")
        try:
            fd = os.open(artifact, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        return artifact, fd
    print(f"deploy: REFUSED — cannot create a fresh backup artifact: 100 names starting at "
          f"{base}.dump already exist in {backups}. Refusing rather than overwriting an existing dump. "
          f"No deploy_completed emitted.", file=sys.stderr)
    sys.exit(3)


BACKUP_KEEP_LAST = 3   # how many pre-deploy dumps this path retains per project (T-10974 / X-0819)

# The EXACT naming shape `_create_new_artifact` writes, anchored end to end. This regex is the SCOPE
# BOUND of the prune below: it is the only thing that decides what may be deleted, so it must match
# what this path creates and NOTHING else. `revision` reaches `_create_new_artifact` from
# `_git_resolve_sha`, so those 12 chars are always lowercase hex; the optional suffix is the
# `.1`..`.99` collision counter of the `range(100)` loop above.
#
# A PREFIX GLOB IS PROVABLY INSUFFICIENT — this is not a stylistic preference. Two artifacts observed
# in a real consumer's `.yitc/backups` on 2026-08-12 are destroyed by the obvious shortcuts:
# `pre-first-apply-drain-20260805T070013Z.dump` (killed by `*.dump`) and
# `pg_dump-T0181-apply-20260714T173243Z.dump` — a HAND-MADE operator dump that shares the `pg_dump-`
# prefix but carries a task id where this path always writes 12 hex (killed by `pg_dump-*.dump`).
# Neither was created here, and deleting either is data loss the deploy never asked for.
_PRE_DEPLOY_DUMP_RE = re.compile(
    r"^pg_dump-(?P<rev>[0-9a-f]{12})-(?P<stamp>\d{8}T\d{6}Z)(?:\.(?P<n>\d{1,2}))?\.dump$")


def _prune_old_backups(backups: Path, *, keep: int = BACKUP_KEEP_LAST, protect: Path = None) -> dict:
    """Retain the newest `keep` pre-deploy dumps THIS path created; delete the older ones. Returns
    `{"pruned", "pruned_bytes", "kept", "failed"}` and JUDGES NOTHING about the deploy — the caller
    owns that (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`).

    Every deploy added a dump and nothing ever removed one, so four consumers reached 20.5 GB over
    ~4 months (X-0819). The growth is SILENT: no mechanism fails closed before the disk does.

    SELECTION is by `_PRE_DEPLOY_DUMP_RE` only — see its comment for why a prefix glob is not merely
    inelegant but provably destructive. `.INVALID` quarantine files (`_discard_backup_artifact`'s
    rename path) fall outside the regex and are therefore SPARED, deliberately: that name exists to
    warn the next operator away from an untrustworthy archive, and silently deleting a warning is
    the very harm this bound exists to prevent. Under-selecting here leaves a stale file; over-
    selecting destroys a backup. The asymmetry decides every ambiguous case.

    ORDERING is by the parsed `(stamp, n)` key, NOT by filename and NOT by mtime. A plain name sort
    is chronologically WRONG because the revision sorts before the stamp — `pg_dump-fff...-<old>`
    would outrank `pg_dump-000...-<new>`. mtime is wrong because a copy, an rsync, or a restore
    rewrites it, which would make the retention silently depend on how the files were moved.

    `protect` (the artifact the running deploy just created) is never deleted whatever the ordering
    says — the cheap guard against the prune eating the backup it was in the middle of taking. It
    COUNTS TOWARD `keep` rather than occupying an extra slot, so the post-condition is
    unconditionally «at most `keep` matching dumps remain» (audit-pre finding, T-10974). Normally
    protect IS the newest and the two readings coincide; they diverge only under clock skew, which
    is exactly when an extra-slot reading would leak an N+1.

    A retention failure NEVER refuses a deploy: the backup this run depends on has already been
    taken and verified by the time we are called, so an undeletable stale file is a housekeeping
    problem, not a reversibility one. Per-file `OSError` is counted into `failed` and reported."""
    entries = []
    try:
        listing = list(backups.iterdir())
    except OSError as exc:
        return {"pruned": 0, "pruned_bytes": 0, "kept": 0, "failed": [f"cannot list {backups}: {exc}"]}

    for path in listing:
        match = _PRE_DEPLOY_DUMP_RE.match(path.name)
        if not match or not path.is_file():
            continue
        # int(n or 0): the unsuffixed name is the FIRST of its second, so it must sort before `.1`.
        entries.append((match.group("stamp"), int(match.group("n") or 0), path))

    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)   # newest first

    protected = None
    if protect is not None:
        protected = next((e for e in entries if e[2] == protect), None)

    retained = [protected] if protected is not None else []
    for entry in entries:
        if len(retained) >= keep:
            break
        if entry is not protected:
            retained.append(entry)

    retained_paths = {e[2] for e in retained}
    pruned = pruned_bytes = 0
    failed = []
    for _stamp, _n, path in entries:
        if path in retained_paths:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        try:
            path.unlink()
        except FileNotFoundError:
            continue          # a concurrent deploy already reclaimed it — the desired end state
        except OSError as exc:
            failed.append(f"{path.name}: {exc}")
            continue
        pruned += 1
        pruned_bytes += size

    # `kept` is COUNTED FROM DISK, never derived as `len(entries) - pruned`. A concurrent deploy that
    # already reclaimed a file leaves a FileNotFoundError that is deliberately not counted as our own
    # prune, so the arithmetic form would over-report by exactly those races (audit-post finding).
    try:
        kept = sum(1 for p in backups.iterdir()
                   if _PRE_DEPLOY_DUMP_RE.match(p.name) and p.is_file())
    except OSError as exc:
        failed.append(f"cannot re-count {backups}: {exc}")
        kept = len(entries) - pruned

    # The post-condition the audit-pre finding pins: `protect` must not push the retained set past
    # `keep`. REPORTED, never raised — an `assert` here would abort a deploy whose backup has already
    # been taken and verified, which is precisely the "a retention failure never refuses a deploy"
    # rule this function is built on (and asserts vanish under -O, so it would not even be reliable).
    if kept > keep:
        failed.append(f"post-condition: {kept} dumps remain with keep={keep} "
                      f"(concurrent deploy, or a file that could not be deleted)")
    return {"pruned": pruned, "pruned_bytes": pruned_bytes, "kept": kept, "failed": failed}


PGDMP_MIN_VERSION = (1, 10)   # below this the header carries no dbname/remote-version pair to read
PGDMP_MAX_VERSION = (1, 16)   # K_VERS_MAX as of PG17 — a NEWER archive has a layout we have not verified


def _parse_pgdmp_header(artifact: Path) -> dict:
    """PURE + read-only: decode the identity a `pg_dump -Fc` archive carries in its own header — the
    SOURCE database name + the server version (SPEC-0148 §1). Identity is read FROM the artifact the
    server wrote, NEVER from the carrier or the command string (those are forgeable: a carrier can claim
    any database while the command dumps another).

    Layout (postgres src/bin/pg_dump/pg_backup_archiver.c `ReadHead`): magic `PGDMP`, then vmaj/vmin/vrev,
    intSize, offSize, format — one byte each. Then the COMPRESSION field, whose width is
    ARCHIVE-VERSION-DEPENDENT: from K_VERS_1_15 (PG16) it is ONE byte (`compression_algorithm`); before
    that it is an archiver int (the compression level). Then 7 timestamp ints, then the connection dbname,
    the remote (server) version, and the pg_dump version — each a length-prefixed string. Archiver ints are
    a sign byte followed by `intSize` little-endian bytes; a negative string length means NULL.

    This function JUDGES NOTHING (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): it
    returns `{"readable": True, ...identity}` or `{"readable": False, "reason": <why>}` and leaves the
    fail-closed decision to its caller, which alone knows whether an expectation was declared. An archive
    version outside the KNOWN band is `readable: False` — an unverified layout must fail toward
    visibility, never toward a GUESSED identity that could green-light a wrong-database deploy."""
    try:
        with open(artifact, "rb") as fh:
            buf = fh.read(4096)
    except OSError as exc:
        return {"readable": False, "reason": f"cannot read the archive ({exc})"}

    if buf[:5] != b"PGDMP":
        return {"readable": False, "reason": "no PGDMP magic — not a pg_dump custom-format (-Fc) archive"}
    if len(buf) < 11:
        return {"readable": False, "reason": "truncated header"}

    vmaj, vmin, vrev = buf[5], buf[6], buf[7]
    int_size = buf[8]
    version = f"{vmaj}.{vmin}.{vrev}"
    if not PGDMP_MIN_VERSION <= (vmaj, vmin) <= PGDMP_MAX_VERSION:
        return {"readable": False, "reason": f"unsupported archive version {version} — this parser has "
                                             f"verified the header layout only for "
                                             f"{'.'.join(map(str, PGDMP_MIN_VERSION))}–"
                                             f"{'.'.join(map(str, PGDMP_MAX_VERSION))}; refusing to guess "
                                             f"an identity from an unknown layout"}
    if not 1 <= int_size <= 8:
        return {"readable": False, "reason": f"implausible header intSize {int_size}"}

    pos = 11

    def read_int() -> int:
        nonlocal pos
        sign = buf[pos]
        pos += 1
        val = 0
        for i in range(int_size):
            val |= buf[pos] << (8 * i)
            pos += 1
        return -val if sign else val

    def read_str() -> "str | None":
        nonlocal pos
        length = read_int()
        if length < 0:
            return None
        if pos + length > len(buf):
            raise IndexError("string runs past the header buffer")
        out = buf[pos:pos + length].decode("utf-8", "replace")
        pos += length
        return out

    try:
        if (vmaj, vmin) >= (1, 15):
            pos += 1        # compression_algorithm — a single byte (K_VERS_1_15+, PG16+)
        else:
            read_int()      # compression level — an archiver int (pre-1.15)
        for _ in range(7):  # sec, min, hour, mday, mon, year, isdst
            read_int()
        database = read_str()
        server_version = read_str()
        pg_dump_version = read_str()
    except IndexError:
        return {"readable": False, "reason": "truncated header"}

    if not database:
        return {"readable": False, "reason": "header parsed but carries no source database name"}
    return {"readable": True, "database": database, "server_version": server_version,
            "pg_dump_version": pg_dump_version, "archive_format_version": version}


def _run_c1_backup(plan: _BackupPlan, *, revision, project, REPO_ROOT, deploy_env, _append_event) -> None:
    """Execute the declared Class-C1 pre-deploy `pg_dump` (SPEC-0097 §4/§5) BEFORE the project deploy
    command runs — a backup taken after the deploy is worthless. On success emit `deploy_backup_taken`.

    Any failure REFUSES the deploy: over budget (the §4 ⇒ Class C2 rule), a non-zero exit, or an empty
    archive on exit 0. Every refusal discards the artifact and exits 3 (the gate-refusal exit code), so
    the project deploy command never runs and no `deploy_completed` is emitted.

    Same `subprocess.run(..., cwd, shell=True, env=deploy_env)` shape as the project-command run below;
    the ONE difference is that the declared dump writes its archive to STDOUT (`pg_dump -Fc`), so stdout
    is redirected to the artifact instead of inherited."""
    backups = Path(REPO_ROOT) / ".yitc" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact, fd = _create_new_artifact(backups, revision, stamp)

    print(f"deploy: Class C1 — taking the declared pre-deploy backup (budget {plan.budget_seconds}s), "
          f"the deploy does NOT run until it succeeds:")
    print(f"  $ {plan.command}")
    print(f"  → {artifact}")

    started = time.monotonic()
    try:
        with os.fdopen(fd, "wb") as fh:
            result = subprocess.run(plan.command, cwd=str(REPO_ROOT), shell=True, env=deploy_env,
                                    stdout=fh, timeout=plan.budget_seconds)
    except subprocess.TimeoutExpired:
        _discard_backup_artifact(artifact)
        print(f"deploy: REFUSED — the pre-deploy pg_dump exceeded its {plan.budget_seconds}s budget "
              f"(SPEC-0097 §4). A dump that cannot meet the restore budget makes this a Class C2 deploy: "
              f"it is never assumed reversible. Escalate to the owner "
              f"(`deploy --class C2 --owner-approved`). The deploy did NOT run; no deploy_completed.",
              file=sys.stderr)
        sys.exit(3)
    duration = time.monotonic() - started

    if result.returncode != 0:
        _discard_backup_artifact(artifact)
        print(f"deploy: REFUSED — the pre-deploy pg_dump exited {result.returncode} (SPEC-0097 §5 requires "
              f"a PRODUCED dump). The deploy did NOT run; no deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)

    size = artifact.stat().st_size if artifact.exists() else 0
    if size == 0:
        _discard_backup_artifact(artifact)
        print("deploy: REFUSED — the pre-deploy pg_dump exited 0 but produced an EMPTY archive. A dump "
              "that produced nothing is not a dump (SPEC-0097 §5). The deploy did NOT run; no "
              "deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)

    # IDENTITY (SPEC-0148) — a fat archive proves a dump RAN, never that it ran on the intended database.
    # Read the identity out of the artifact itself, AFTER the empty-archive gate (an empty file is not an
    # identity question). THE READER OWNS THE FAIL-CLOSED JUDGEMENT: `unreadable` means REFUSE when an
    # expectation is declared and RECORD-THE-REASON when it is not — a distinction the parser cannot make.
    identity = _parse_pgdmp_header(artifact)
    expected = plan.expected_database
    if expected:
        if not identity["readable"]:
            _discard_backup_artifact(artifact)
            print(f"deploy: REFUSED — `classes.C1.expected_database` declares `{expected}`, but the "
                  f"produced archive's identity is UNREADABLE ({identity['reason']}), so nothing proves "
                  f"the dump ran on that database (SPEC-0148 §3). An unverifiable backup is not a backup. "
                  f"The deploy did NOT run; no deploy_completed, no deploy_backup_taken emitted.",
                  file=sys.stderr)
            sys.exit(3)
        if identity["database"] != expected:
            _discard_backup_artifact(artifact)
            print(f"deploy: REFUSED — the pre-deploy dump landed on the WRONG database: expected "
                  f"`{expected}` (`classes.C1.expected_database`), the archive's own header names "
                  f"`{identity['database']}` (SPEC-0148 §3). The dump exited 0 and produced {size} bytes — "
                  f"it is simply not a backup OF the database being deployed. The deploy did NOT run; no "
                  f"deploy_completed, no deploy_backup_taken emitted.", file=sys.stderr)
            sys.exit(3)

    # RETENTION (T-10974 / X-0819) — runs only after every gate above passed, so a dump that was
    # refused never triggers a prune, and the artifact we just took is protected by name. Reported on
    # the EXISTING deploy_backup_taken payload rather than a new event type (CHARTER §P1 filter 2 —
    # a view over the existing carrier, not a new entity).
    retention = _prune_old_backups(backups, protect=artifact)

    payload = {"revision": revision, "project": project, "path": str(artifact), "bytes": size,
               "duration_seconds": round(duration, 3), "budget_seconds": plan.budget_seconds,
               "database": identity.get("database"), "server_version": identity.get("server_version"),
               # Written UNCONDITIONALLY by this code path, so the ABSENCE of these keys reads as
               # "this build predates the prune" while a zero reads as "the prune ran, nothing was
               # old enough" — the two are not confusable (the T-10974 differential).
               "backups_pruned": retention["pruned"],
               "backups_pruned_bytes": retention["pruned_bytes"],
               "backups_kept": retention["kept"]}
    if retention["failed"]:
        payload["backups_prune_failed"] = retention["failed"]
    if not identity["readable"]:
        # No expectation declared (an expectation would have refused above) ⇒ record, never enforce.
        payload["identity_unreadable"] = identity["reason"]
    _append_event("deploy_backup_taken", None, payload)
    if retention["pruned"]:
        print(f"deploy: retention — pruned {retention['pruned']} older pre-deploy dump(s) "
              f"({retention['pruned_bytes'] / 1e9:.2f} GB), {retention['kept']} kept "
              f"(keep-last {BACKUP_KEEP_LAST}).")
    if retention["failed"]:
        print(f"deploy: retention — could NOT delete {len(retention['failed'])} old dump(s): "
              f"{'; '.join(retention['failed'])}. The backup itself is unaffected.", file=sys.stderr)
    if identity["readable"]:
        checked = f", matches the declared `{expected}`" if expected else " (no expected_database declared)"
        print(f"deploy: backup OK — {size} bytes in {duration:.1f}s (budget {plan.budget_seconds}s) of "
              f"database `{identity['database']}` (server {identity['server_version']}){checked}; "
              f"deploy_backup_taken emitted.")
    else:
        print(f"deploy: backup OK — {size} bytes in {duration:.1f}s (budget {plan.budget_seconds}s); "
              f"identity UNREADABLE ({identity['reason']}) — recorded, not enforced (declare "
              f"`classes.C1.expected_database` to make this a refusal); deploy_backup_taken emitted.")


class _SecurityProbePlan(NamedTuple):
    """The Class-S pre-deploy security probe, read out of the SELECTED evidence block. PURE data, so the
    precondition is unit-testable in isolation from git/subprocess (mirrors `_BackupPlan`)."""
    command: "str | None"
    budget_seconds: "int | None"
    unprobeable: "str | None"   # declared reason the property cannot be asserted read-only ⇒ escalate
    error: "str | None"         # None ⇒ usable; else the fail-closed reason to print + refuse on


def _security_probe_precondition(evidence) -> _SecurityProbePlan:
    """PURE — extract the Class-S security probe command + its duration budget from the carrier block the
    gate SELECTED into `_GateDecision.evidence` (SPEC-0097 §2 «autonomous ONLY with a mandatory security
    live-probe … if the property is not probeable read-only → escalate»).

    FAIL CLOSED, with one ASYMMETRY vs `_backup_precondition`: an un-probeable property is a FIRST-CLASS
    declared outcome, not an error — §2 names escalation as its correct route, so the project declares
    `unprobeable: <reason>` and the deploy escalates carrying that reason to the owner. Everything else
    (absent/blank command, missing/non-positive budget) is a plain fail-closed error: Class-S autonomy is
    granted ONLY against a probe that can actually run. `unprobeable` is checked FIRST, so a project that
    declares it need not also write a command it has just said it cannot write. The key REUSES the
    SPEC-0098 §2 vocabulary (`live_probe.py#cmd_live_probe`); it is not a second dialect."""
    if not isinstance(evidence, dict):
        return _SecurityProbePlan(None, None, None,
                                  "the carrier declares no `classes.S` block to probe from")
    if "unprobeable" in evidence:
        reason = evidence.get("unprobeable")
        if not isinstance(reason, str) or not reason.strip():
            return _SecurityProbePlan(None, None, None,
                                      "`classes.S.unprobeable` is present but blank — an un-probeable "
                                      "security property must carry a REASON for the owner (SPEC-0097 §2)")
        return _SecurityProbePlan(None, None, reason.strip(), None)
    command = evidence.get("security_probe")
    if not isinstance(command, str) or not command.strip():
        return _SecurityProbePlan(None, None, None,
                                  "`classes.S.security_probe` is absent or blank — no security probe "
                                  "command to run")
    budget = evidence.get("security_probe_budget_seconds")
    # bool is an int subclass — `True` must never read as a 1-second budget (same guard as C1).
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        return _SecurityProbePlan(None, None, None,
                                  "`classes.S.security_probe_budget_seconds` is absent or not a positive "
                                  "integer — a security probe with no budget could hang the deploy seam")
    return _SecurityProbePlan(command.strip(), budget, None, None)


# ── The DOWN-surface carve-out (T-10582, X-0434 — owner ruling 2026-07-16, option 1) ────────────────
#
# The circularity it closes: the Class-S pre-probe asserts the security property against the LIVE surface,
# so during an outage-RESTORE (backend crash-looping, every endpoint 502/conn-refused) it can NEVER pass —
# 502 != 401 — and the deploy it refuses is the only thing that would bring the surface back up. boomrocket
# hit this twice on 2026-07-16.
#
# Why the carve-out is sound rather than a weakening: the pre-probe's whole justification is EXPOSURE (see
# `_run_class_s_security_probe` below). On a DOWN surface that justification is VACUOUS — a surface serving
# nothing exposes nothing, so the failed probe carries no exposure signal at all; it measured the absence of
# a server, not the presence of a hole. The carve-out fires ONLY where the property the refusal protects
# cannot be at risk, and it still REFUSES on a 200-serving surface with a broken property (unchanged).
#
# THE CLOSED LIVENESS VOCABULARY. The kernel cannot itself tell a 502 from a 401: the security probe is an
# arbitrary shell string and only its `returncode` is visible. So the DOWN answer is DECLARED, by a second
# read-only command, against a vocabulary the KERNEL owns (the project owns only the mapping from its own
# surface onto it — the same split the carrier uses everywhere):
#
#     exit 0         ⇒ UP       — the surface is serving
#     exit 1         ⇒ DOWN     — positively observed 5xx / connection-refused
#     any other exit ⇒ UNKNOWN  — the probe did not answer the question
#     timeout        ⇒ UNKNOWN
#
# «Any non-zero ⇒ DOWN» would be a BYPASS, and the cheapest possible one: the runner's OWN error codes are
# non-zero (127 command-not-found, 126 not-executable, 128+N signalled), so a typo'd or missing liveness
# command would read as "the surface is down" and open the carve-out — the exact inverse of fail-closed, on
# a security gate. The closed vocabulary excludes that whole class structurally (127 != 1 ⇒ REFUSE) without
# the kernel enumerating error codes. Caught by this card's audit-pre, so the naive read is pinned RED by
# the runner-error leg in tests/test_t10582_class_s_down_surface.py — never re-introduce it.
_LIVENESS_UP_EXIT = 0      # the surface IS serving ⇒ a failing security probe means the property is broken
_LIVENESS_DOWN_EXIT = 1    # positively DOWN ⇒ the ONLY answer that opens the carve-out


class _LivenessProbePlan(NamedTuple):
    """The Class-S liveness probe — the DOWN-vs-property-broken discriminator (SPEC-0097 §2a, T-10582).
    PURE data, so the precondition is unit-testable in isolation from git/subprocess (mirrors
    `_SecurityProbePlan`)."""
    command: "str | None"
    budget_seconds: "int | None"
    declared: bool              # False ⇒ the carrier never opted in; the carve-out simply does not exist
    error: "str | None"         # None ⇒ usable; else the fail-closed reason to print + refuse on


def _liveness_probe_precondition(evidence) -> _LivenessProbePlan:
    """PURE — extract the OPT-IN Class-S liveness probe + its budget from the SELECTED `classes.S` block.

    The PARSER does NOT decide what an ABSENT `liveness_probe` MEANS: it returns `declared=False` and the
    READER (the failing-security-probe branch) owns that judgement — there, absent ⇒ REFUSE exactly as
    before this card, because the carve-out is opt-in. Keeping the missing-value judgement at the one
    reader with the context is `lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`; answering it
    centrally here would hand the same answer to every future caller whose correct answer differs.

    Everything DECLARED-but-malformed is a plain fail-closed error (mirroring `_security_probe_precondition`):
    a carve-out this consequential is never granted against a probe that cannot actually run."""
    if not isinstance(evidence, dict) or "liveness_probe" not in evidence:
        return _LivenessProbePlan(None, None, False, None)
    command = evidence.get("liveness_probe")
    if not isinstance(command, str) or not command.strip():
        return _LivenessProbePlan(None, None, True,
                                  "`classes.S.liveness_probe` is present but blank — no liveness probe "
                                  "command to run")
    budget = evidence.get("liveness_probe_budget_seconds")
    # bool is an int subclass — `True` must never read as a 1-second budget (same guard as C1 / the
    # security probe).
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        return _LivenessProbePlan(None, None, True,
                                  "`classes.S.liveness_probe_budget_seconds` is absent or not a positive "
                                  "integer — a liveness probe with no budget could hang the deploy seam")
    return _LivenessProbePlan(command.strip(), budget, True, None)


def _liveness_verdict(returncode: "int | None") -> str:
    """PURE — map a liveness probe's exit onto the closed kernel vocabulary. `None` = timed out.

    Returns "up" | "down" | "unknown". ONLY "down" opens the carve-out; "up" and "unknown" both REFUSE,
    and they are DISTINCT because they mean opposite things to whoever reads the refusal: "up" says your
    security property is genuinely broken on a serving surface (go fix the property), "unknown" says your
    liveness probe did not answer (go fix the probe). Collapsing them would send an operator to fix the
    wrong thing — and, on the naive «non-zero ⇒ down» reading, would send them nowhere at all while the
    pre-probe was silently bypassed."""
    if returncode is None:
        return "unknown"
    if returncode == _LIVENESS_UP_EXIT:
        return "up"
    if returncode == _LIVENESS_DOWN_EXIT:
        return "down"
    return "unknown"


class _RollbackCapability(NamedTuple):
    """The auto-rollback the DOWN-surface carve-out PROMISES, resolved BEFORE anything ships (T-10582)."""
    command: "str | None"
    target: "str | None"        # the revision to roll back TO = the latest deploy_completed (SPEC-0094 §1)
    error: "str | None"


def _rollback_capability(ops, *, project, _iter_events) -> _RollbackCapability:
    """Resolve the auto-rollback the carve-out is CONDITIONED on: the carrier's `rollback.command` + the
    revision to roll back TO.

    WHY THIS IS A PRE-DEPLOY PRECONDITION. The owner ruling grants «proceed on a DOWN surface» BECAUSE a
    mandatory post-probe + auto-rollback backstops it. If the rollback cannot actually run, that condition
    is UNMET — proceeding would grant autonomy without the safety net that justified it. So this resolves
    before the deploy command, and a missing capability REFUSES (never «proceed and hope»).

    THE TARGET is the latest `deploy_completed` revision for this project (SPEC-0094 §1: «the current-live
    revision is the latest deploy_completed»; a rollback is itself a `deploy_completed`, so the latest
    record is always the live one — the same fold as `views.py#_view_not_adopted`, done locally because
    this module back-imports NOTHING and reads the journal ONLY through the injected `_iter_events`).

    Note what the target MEANS during an outage-restore, because it looks wrong until you name the trade:
    the prior revision is the CRASH-LOOPING one, so an auto-rollback RESTORES THE OUTAGE. That is correct.
    A DOWN surface exposes nothing; an EXPOSED surface does. Down is strictly safer than exposed, and the
    escalation event brings the owner in immediately."""
    section = ops.get("rollback") if isinstance(ops, dict) else None
    command = section.get("command") if isinstance(section, dict) else None
    if not isinstance(command, str) or not command.strip():
        return _RollbackCapability(None, None,
                                   "the carrier declares no runnable `rollback: {command: <cmd>}` "
                                   "(SPEC-0094 §1), so the auto-rollback this carve-out promises could "
                                   "not run")
    target, target_ts = None, None
    for e in _iter_events():
        if e.get("type") != "deploy_completed":
            continue
        d = e.get("data") or {}
        if d.get("project") != project:
            continue
        ts = e.get("ts") or ""
        if target_ts is None or ts >= target_ts:   # latest by ts (ties → later in file wins; append-order)
            target_ts, target = ts, d.get("revision")
    if not target:
        return _RollbackCapability(None, None,
                                   f"no prior `deploy_completed` is on record for `{project}`, so there "
                                   f"is no revision to roll back TO (SPEC-0094 §1)")
    return _RollbackCapability(command.strip(), target, None)


class _DownSurfaceCarveOut(NamedTuple):
    """The decision to proceed with a Class-S deploy onto a DOWN surface, carried from the pre-probe to the
    MANDATORY post-probe (T-10582). Truthy ⇒ the carve-out fired; `None` ⇒ the ordinary path."""
    security_probe: _SecurityProbePlan
    pre_exit: int
    liveness_exit: "int | None"
    rollback: _RollbackCapability


def _run_class_s_security_probe(plan: _SecurityProbePlan, *, revision, project, REPO_ROOT, deploy_env,
                                _append_event, evidence=None, ops=None,
                                _iter_events=None) -> "_DownSurfaceCarveOut | None":
    """Execute the declared Class-S security probe (SPEC-0097 §2) BEFORE the project deploy command runs.
    On success emit `deploy_security_probe_passed`; a failure REFUSES the deploy (exit 3) — EXCEPT on a
    provably DOWN surface, where it returns a `_DownSurfaceCarveOut` and the caller MUST run the post-deploy
    probe (§2a, T-10582). Returns None on the ordinary pass ⇒ no post-probe owed.

    WHY PRE-DEPLOY. A kernel probe refusing AFTER the project command exited 0 would leave the new revision
    LIVE with no `deploy_completed` — live state changed, journal silent, breaking SPEC-0094 §1 («the
    current-live revision is the latest deploy_completed»). Post-deploy health/smoke already lives INSIDE
    the project's deploy command, which owns auto-rollback; that is why a non-zero command exit can safely
    leave no event. And SPEC-0097 §2's deeper reason: Class-S's failure mode is «EXPOSURE, which an image
    rollback does NOT undo» — exposure being unrollbackable is exactly why §2 routes an un-assertable
    property to ESCALATE, because the decision belongs BEFORE the deploy.

    WHY THE DOWN CARVE-OUT DOES NOT BREAK THAT (§2a, the owner ruling of 2026-07-16 on X-0434). Both
    reasons above are conditioned on a premise that a DOWN surface makes FALSE. (1) The journal invariant
    holds because the carve-out's post-probe failure ROLLS BACK: the prior revision is left live and no
    `deploy_completed` is emitted, so «latest deploy_completed == current-live» stays TRUE — the invariant
    breaks only WITHOUT a rollback, which is why the ruling pairs the two and why `_rollback_capability`
    is a PRE-deploy precondition here. (2) The exposure reason is vacuous on a surface that serves nothing:
    a 502 is not a hole. So the carve-out is scoped to exactly the case where the original reasoning does
    not apply, and leaves every serving-surface refusal untouched.

    SCOPE — claim no more than this proves. A pass means the declared probe is present, runnable, and the
    security property HOLDS on the live surface immediately before the new revision ships; an absent,
    unrunnable, over-budget, or un-probeable probe REFUSES autonomy. It does NOT prove the NEW revision
    preserves the property — that post-deploy assertion remains the per-change `liveprobe` verb at the
    seam (SPEC-0094 §4), unchanged. (The carve-out's post-probe is narrower still: it re-asserts the SAME
    property on the new revision ONLY because the pre-probe could not be measured at all.)

    Same `subprocess.run(..., cwd, shell=True, env=deploy_env, timeout=...)` shape as `_run_c1_backup`;
    stdout/stderr are INHERITED (unlike the C1 dump, which redirects stdout into its archive) — a security
    probe's own output is the operator's evidence and must be seen live."""
    print(f"deploy: Class S — running the declared security probe (budget {plan.budget_seconds}s); "
          f"the deploy does NOT run until it passes:")
    print(f"  $ {plan.command}")

    started = time.monotonic()
    try:
        result = subprocess.run(plan.command, cwd=str(REPO_ROOT), shell=True, env=deploy_env,
                                timeout=plan.budget_seconds)
    except subprocess.TimeoutExpired:
        # UNTOUCHED by the carve-out, deliberately: a timed-out security probe did not observe a DOWN
        # surface, it observed NOTHING. Only a positive liveness answer may open the carve-out, and this
        # leg has no probe result to pair one with.
        print(f"deploy: REFUSED — the Class-S security probe exceeded its {plan.budget_seconds}s budget "
              f"(SPEC-0097 §2). A security property that cannot be asserted read-only within budget is "
              f"not autonomously deployable — escalate to the owner. The deploy did NOT run; no "
              f"deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)
    duration = time.monotonic() - started

    if result.returncode != 0:
        carve, refusal = _class_s_down_surface_carve_out(
            plan, pre_exit=result.returncode, evidence=evidence, ops=ops, project=project,
            REPO_ROOT=REPO_ROOT, deploy_env=deploy_env, _iter_events=_iter_events)
        if carve is not None:
            return carve
        # ONE refusal message, composed by the leg that actually decided (audit-post finding 1). The
        # carve-out's legs do NOT all mean «the property is broken» — an UNKNOWN liveness answer or an
        # unavailable rollback means we never ESTABLISHED that — so printing the §2 property-broken text
        # underneath them would contradict the specific diagnosis and send the operator to fix the wrong
        # thing, mid-outage. Each leg owns its whole message; the caller only prints it.
        print(refusal, file=sys.stderr)
        sys.exit(3)

    _append_event("deploy_security_probe_passed", None,
                  {"revision": revision, "project": project, "command": plan.command,
                   "duration_seconds": round(duration, 3), "budget_seconds": plan.budget_seconds,
                   "phase": "pre"})
    print(f"deploy: security probe OK in {duration:.1f}s (budget {plan.budget_seconds}s); "
          f"deploy_security_probe_passed emitted.")
    return None


def _property_broken_refusal(pre_exit: int) -> str:
    """The §2 refusal: the security probe failed on a surface we know is SERVING, so the declared property
    really is broken. The ONLY leg entitled to this claim — see `_class_s_down_surface_carve_out`."""
    return (f"deploy: REFUSED — the Class-S security probe exited {pre_exit}: the declared security "
            f"property does NOT hold on the live surface (SPEC-0097 §2). Class-S autonomy requires it to "
            f"hold — the failure mode is EXPOSURE, which an image rollback does not undo. Escalate to the "
            f"owner. The deploy did NOT run; no deploy_completed emitted.")


def _class_s_down_surface_carve_out(plan: _SecurityProbePlan, *, pre_exit, evidence, ops, project,
                                    REPO_ROOT, deploy_env,
                                    _iter_events) -> "tuple[_DownSurfaceCarveOut | None, str | None]":
    """Decide whether a FAILED Class-S pre-probe is the outage-restore case that may proceed (§2a, T-10582).
    Returns `(carve_out, None)` ONLY when all three conditions hold POSITIVELY; otherwise `(None, refusal)`
    where `refusal` is the COMPLETE message the caller prints before exiting 3.

    WHY EACH LEG OWNS ITS WHOLE MESSAGE (audit-post finding 1). The legs below do NOT all mean the same
    thing, and only ONE of them is entitled to say «the security property does NOT hold»: the UP leg, where
    the surface is provably serving. On an UNKNOWN liveness answer, or when the rollback backstop is
    unavailable, we never ESTABLISHED that the property is broken — we established that we could not tell.
    Emitting a specific diagnosis and then falling through to the §2 property-broken text underneath it
    contradicts the diagnosis and sends the operator to fix the wrong thing, at exactly the moment (mid
    outage-restore) when that costs the most. So the refusal is composed HERE, once, by whichever leg
    actually decided.

    The three conditions are independent on purpose — a carve-out on a security gate should need positive
    evidence on every axis, never an absence of objections:
      1. the carrier OPTED IN by declaring a runnable `classes.S.liveness_probe` (+ budget), AND
      2. that probe positively answers DOWN (exit 1) within budget — not UP, not UNKNOWN, not timed out, AND
      3. the auto-rollback the carve-out promises can actually run (a declared `rollback.command` + a prior
         `deploy_completed` to roll back TO)."""
    liveness = _liveness_probe_precondition(evidence)
    if not liveness.declared:
        # The carrier never opted in. NOT a malformation — a stance, so this keeps the pre-T-10582 refusal
        # verbatim and merely APPENDS how to opt in: this is the exact moment an operator is staring at the
        # circularity, and the carve-out is not seeded into the born template, so this message IS its
        # discoverability surface.
        return None, (
            _property_broken_refusal(pre_exit) + "\n"
            f"deploy:   (NOTE: no `classes.S.liveness_probe` is declared, so this deploy cannot tell a DOWN "
            f"surface from a serving one with a broken property — if the surface is in fact DOWN, the "
            f"message above is overclaiming and the SPEC-0097 §2a outage-restore carve-out is what you "
            f"want. It is opt-in: declare a read-only `liveness_probe` exiting {_LIVENESS_UP_EXIT}=serving "
            f"/ {_LIVENESS_DOWN_EXIT}=down plus a positive `liveness_probe_budget_seconds`.)")
    if liveness.error:
        # DECLARED but unusable ⇒ UNKNOWN, not property-broken: a malformed discriminator tells us nothing
        # about the surface.
        return None, (
            f"deploy: REFUSED — the Class-S security probe exited {pre_exit}, and the declared liveness "
            f"probe is unusable, so the deploy CANNOT tell a DOWN surface from a serving one with a broken "
            f"property: {liveness.error} (SPEC-0097 §2a). A malformed discriminator must never open the "
            f"carve-out, and it is NOT evidence that your security property is broken — fix the liveness "
            f"declaration. The deploy did NOT run; no deploy_completed emitted.")

    print(f"deploy: Class S — the security probe exited {pre_exit}; asking the declared liveness probe "
          f"whether the surface is SERVING or DOWN (budget {liveness.budget_seconds}s):")
    print(f"  $ {liveness.command}")
    try:
        result = subprocess.run(liveness.command, cwd=str(REPO_ROOT), shell=True, env=deploy_env,
                                timeout=liveness.budget_seconds)
        liveness_exit = result.returncode
    except subprocess.TimeoutExpired:
        liveness_exit = None
    verdict = _liveness_verdict(liveness_exit)

    if verdict == "up":
        # The regression leg the ruling explicitly preserves: a 200-serving surface with a failing security
        # property still REFUSES pre-deploy, exactly as T-10279 shipped it. The ONE leg that has actually
        # established a broken property, and so the one entitled to say so.
        return None, (
            _property_broken_refusal(pre_exit) + "\n"
            f"deploy:   (confirmed by the declared liveness probe: the surface is SERVING (exit "
            f"{_LIVENESS_UP_EXIT}), so this is a REAL broken property on a live surface, not an outage. "
            f"The SPEC-0097 §2a carve-out does not apply.)")
    if verdict == "unknown":
        # DISTINCT from "up" on purpose, and deliberately NOT paired with the property-broken text: this is
        # «your probe did not answer», not «your property is broken».
        shown = "timed out" if liveness_exit is None else f"exited {liveness_exit}"
        return None, (
            f"deploy: REFUSED — the Class-S security probe exited {pre_exit}, and the declared liveness "
            f"probe {shown} — that is neither {_LIVENESS_UP_EXIT} (serving) nor {_LIVENESS_DOWN_EXIT} "
            f"(down), so it did NOT answer whether the surface is up (SPEC-0097 §2a). An UNANSWERED "
            f"liveness probe is not proof of an outage, so the carve-out stays closed. This is your "
            f"LIVENESS probe failing to answer — it is NOT a finding that your security property is "
            f"broken; the deploy does not know either way. Fix the liveness probe. The deploy did NOT "
            f"run; no deploy_completed emitted.")

    rollback = _rollback_capability(ops, project=project, _iter_events=_iter_events)
    if rollback.error:
        # The surface IS provably down, so the property was never observed broken — do not claim it is.
        return None, (
            f"deploy: REFUSED — the surface is DOWN (liveness exit {_LIVENESS_DOWN_EXIT}), so the "
            f"SPEC-0097 §2a outage-restore carve-out would apply, BUT {rollback.error}. §2a grants the "
            f"deploy only BECAUSE a mandatory post-deploy probe + auto-rollback backstops it — with no "
            f"rollback there is no backstop, so the grant's own condition is unmet. (The failing security "
            f"probe here is NOT evidence your property is broken: nothing is being served.) The deploy did "
            f"NOT run; no deploy_completed emitted.")

    print(f"deploy: Class S — the surface is DOWN (liveness exit {_LIVENESS_DOWN_EXIT}), so the failed "
          f"security probe carries NO exposure signal: nothing is being served (SPEC-0097 §2a, owner "
          f"ruling 2026-07-16 on X-0434). PROCEEDING, and the SAME security probe will run MANDATORILY "
          f"immediately after the deploy command — if it fails, `rollback:` runs automatically to "
          f"{rollback.target[:12]} and the owner is escalated.")
    return _DownSurfaceCarveOut(security_probe=plan, pre_exit=pre_exit, liveness_exit=liveness_exit,
                                rollback=rollback), None


def _run_post_deploy_security_probe(carve: _DownSurfaceCarveOut, *, revision, project, REPO_ROOT,
                                    deploy_env, _append_event) -> dict:
    """The MANDATORY post-deploy leg the DOWN-surface carve-out promised (§2a, T-10582). Runs IMMEDIATELY
    after the project deploy command exits 0. On pass, emits `deploy_security_probe_passed` (phase=post)
    and returns the evidence the caller stamps onto `deploy_completed`. On failure it auto-rolls-back,
    emits `deploy_security_probe_post_failed` (the owner escalation), and exits 3 WITHOUT a
    `deploy_completed` — so the journal keeps saying the PRIOR revision is live, which is what a rollback
    makes true (SPEC-0094 §1).

    WHY IMMEDIATELY, i.e. BEFORE the §11 convergence verify. A convergence failure exits 5 and would SKIP
    this probe entirely, leaving a possibly-EXPOSED revision live with no security assertion at all.
    Security evidence must not be contingent on convergence passing.

    A NON-zero deploy command exit never reaches here: the revision was never left live (the project
    command owns its own rollback), so there is nothing to re-assert — that leg is unchanged."""
    plan = carve.security_probe
    print(f"deploy: Class S — the pre-deploy surface was DOWN, so re-running the declared security probe "
          f"now, against the revision just deployed (MANDATORY, budget {plan.budget_seconds}s):")
    print(f"  $ {plan.command}")

    started = time.monotonic()
    try:
        result = subprocess.run(plan.command, cwd=str(REPO_ROOT), shell=True, env=deploy_env,
                                timeout=plan.budget_seconds)
        post_exit = result.returncode
    except subprocess.TimeoutExpired:
        post_exit = None
    duration = time.monotonic() - started

    if post_exit == 0:
        evidence = {"command": plan.command, "duration_seconds": round(duration, 3),
                    "budget_seconds": plan.budget_seconds}
        _append_event("deploy_security_probe_passed", None,
                      {"revision": revision, "project": project, "phase": "post",
                       "down_surface_pre": True, "pre_exit": carve.pre_exit, **evidence})
        print(f"deploy: security probe OK in {duration:.1f}s (budget {plan.budget_seconds}s) — the "
              f"security property HOLDS on the restored surface; deploy_security_probe_passed "
              f"(phase=post) emitted.")
        return evidence

    # The property does NOT hold on the revision just deployed (or could not be asserted). Roll back FIRST,
    # then record — the surface is possibly EXPOSED right now and that is what the ruling's backstop is for.
    shown = f"timed out after {plan.budget_seconds}s" if post_exit is None else f"exited {post_exit}"
    print(f"deploy: POST-DEPLOY SECURITY PROBE FAILED — the probe {shown} against the revision just "
          f"deployed. Auto-rolling-back to {carve.rollback.target[:12]} (SPEC-0097 §2a):", file=sys.stderr)
    print(f"  $ {carve.rollback.command} {carve.rollback.target}", file=sys.stderr)
    rollback_proc = subprocess.run(f"{carve.rollback.command} {carve.rollback.target}",
                                   cwd=str(REPO_ROOT), shell=True, env=deploy_env)
    rollback_ok = rollback_proc.returncode == 0

    _append_event("deploy_security_probe_post_failed", None,
                  {"revision": revision, "project": project, "phase": "post",
                   "command": plan.command, "post_exit": post_exit,
                   "budget_seconds": plan.budget_seconds, "down_surface_pre": True,
                   "pre_exit": carve.pre_exit, "liveness_exit": carve.liveness_exit,
                   "rollback_command": carve.rollback.command, "rollback_target": carve.rollback.target,
                   "rollback_exit": rollback_proc.returncode, "rollback_succeeded": rollback_ok,
                   "escalation": "owner decision REQUIRED: a Class-S deploy onto a DOWN surface failed "
                                 "its mandatory post-deploy security probe"})
    if rollback_ok:
        print(f"deploy: REFUSED — rolled back to {carve.rollback.target[:12]}; the deployed revision is "
              f"NOT live and no deploy_completed was emitted, so the journal still reads the prior "
              f"revision as live (SPEC-0094 §1). ESCALATED to the owner: the restore deploy "
              f"{revision[:12]} does not hold the declared security property. "
              f"deploy_security_probe_post_failed emitted.", file=sys.stderr)
    else:
        # NEVER claim a rollback that did not happen. The surface may be live AND exposed right now.
        print(f"deploy: REFUSED — and THE AUTO-ROLLBACK ITSELF FAILED (exit {rollback_proc.returncode}). "
              f"The revision {revision[:12]} may be LIVE and EXPOSED right now, and the kernel could not "
              f"reverse it. OWNER ACTION REQUIRED IMMEDIATELY — roll back by hand "
              f"(`bin/yitc-v2 deploy --rollback {carve.rollback.target[:12]}`) or take the surface down. "
              f"No deploy_completed emitted; deploy_security_probe_post_failed records "
              f"rollback_succeeded=false.", file=sys.stderr)
    sys.exit(3)


# ── SPEC-0155 rule 1 — the deploy-seam security-producer run + base pre-deploy gate ──────────────────
# A generous SAFETY timeout for the seam producer run — NOT a governance scalar (SPEC-0093 §Parameters
# non-whitelist): a run-away producer must never hang the deploy seam indefinitely. Env-overridable for
# a slow surface / a test seam; the value itself governs nothing (the freshness bound the GATE judges by
# is the carrier `security.audit.freshness_sla`, single-sourced in SPEC-0145 §6 — this is only a hang-cap).
_SECURITY_AUDIT_SEAM_BUDGET_S = int(os.environ.get("YITC_SECURITY_AUDIT_SEAM_BUDGET_S", "600"))


class _SecurityAuditPlan(NamedTuple):
    """The declared `security.audit` producer read out of the ops carrier top-level `security:` block.
    PURE data (no subprocess/git) so the precondition is unit-testable in isolation (mirrors
    `_BackupPlan` / `_SecurityProbePlan`)."""
    runner: "str | None"        # the declared runner command (SPEC-0145 §6) — None when skipped/error
    skip_reason: "str | None"   # SKIP (fail-open) — no producer declared; deploy proceeds as before
    error: "str | None"         # None ⇒ usable; else the fail-closed reason to print + refuse on


def _security_audit_precondition(security_section) -> _SecurityAuditPlan:
    """PURE — extract the declared `security.audit.runner` from the ops carrier `security:` block
    (SPEC-0145 §6). Three outcomes, mirroring the reader-owns-fail-closed discipline
    (lessons/fail-closed-belongs-to-the-reader-not-the-parser.md):
      * SKIP (skip_reason set) — no `security.audit` mapping, or a waived block, or no `runner:` declared.
        A project that has NOT declared a security producer deploys EXACTLY as before this spec
        (fail-OPEN, the pre-policy analog): there is nothing to run and nothing to gate.
      * ERROR (error set) — a `runner:` is present but not a non-blank string: a malformed config must
        REFUSE, never silently degrade to "no producer" (the silent-disable class SPEC-0148 §3 closed).
      * USABLE (runner set) — the declared runner command to execute at the seam."""
    audit = security_section.get("audit") if isinstance(security_section, dict) else None
    if not isinstance(audit, dict):
        return _SecurityAuditPlan(None, "no `security.audit` block declared (SPEC-0145 §6) — "
                                  "no deploy-seam security producer to run", None)
    if "runner" not in audit:
        # A waived / cadence-only carrier (declare-or-waive) that never declared a runner ⇒ nothing to run.
        return _SecurityAuditPlan(None, "`security.audit` declares no `runner:` (waived / cadence-only) "
                                  "— no deploy-seam producer to run", None)
    runner = audit.get("runner")
    if not isinstance(runner, str) or not runner.strip():
        return _SecurityAuditPlan(None, None,
                                  f"`security.audit.runner` is present but is not a non-blank string "
                                  f"(got {type(runner).__name__}) — a malformed producer declaration "
                                  f"must refuse, never silently skip the pre-deploy security gate")
    return _SecurityAuditPlan(runner.strip(), None, None)


# ── SPEC-0155 rule 7 — the OWNER-INVOKED, JOURNALED outage-recovery override of the security gate ─────
#
# THE INCIDENT (X-0362 / X-0363, 2026-07-13). aiseller's governed deploy was BLOCKED by a build-time dep
# advisory (a vite dev-server GHSA — not reachable from prod; fix = a 3-major upgrade) DURING a live prod
# auth outage. The gate is fail-closed by design and had NO exception path fast enough for an outage: the
# only outs were a pre-authored fingerprint waiver or a report edit the TAMPER check (correctly) refuses.
# So the GOVERNED restore path was unavailable and recovery ran in emergency mode — the machinery pushed
# the operator OUT of governance exactly when governance mattered most.
#
# THE RULE (and why it is NOT a gate weakening — SPEC-0121). The default is UNCHANGED: with no override
# flags, every reject refuses exactly as before, byte-identically. The override is:
#   * OWNER-INVOKED   — it exists only as an explicit flag pair on the command line; nothing infers it,
#                       no config enables it, no env turns it on.
#   * REASON-BEARING  — a non-blank reason is REQUIRED; a half-declared pair (ids without a reason, or a
#                       reason without ids) REFUSES rather than silently degrading to "no override".
#   * CLASS-BOUNDED   — admissible ONLY for the SEVERITY-blocking reject class (open critical/high
#                       findings). Every other class (tampered / incomplete / stale / scope-mismatch /
#                       identity-mismatch / missing / foreign-producer / config) means the EVIDENCE ITSELF
#                       is untrustworthy or does not cover the deployed code — overriding there deploys
#                       BLIND, so it stays unconditionally fail-closed. A failed PRODUCER (no evidence at
#                       all) is never reachable by the override either: it refuses before the gate runs.
#   * TRUTHFUL        — the override must NAME every blocking finding (`_override_covers`), by EXACT
#                       advisory-id / fingerprint token, never a loose substring. An unnamed blocking
#                       finding REFUSES. So the journaled record cannot claim to bypass one advisory while
#                       actually bypassing three, and the event carries the GATE's own finding records —
#                       not the operator's claim about them.
#   * JOURNALED       — it emits its own `deploy_security_gate_overridden` event (reason + advisory ids +
#                       the bypassed findings), and it NEVER emits `deploy_security_gate_passed`: the gate
#                       did not pass, and the journal must not say it did. Frequency is debt-visible
#                       (SPEC-0119) — a habit of overriding surfaces itself.
# Prior-art extended (CHARTER §P1 F1): the SPEC-0097 §5 Class-C2 `--owner-approved` flag — the established
# shape of an owner-invoked, journaled deploy escalation. This is that shape applied to the gate leg.

# The PINNED advisory-id shapes an override may name a finding by. A supplied id MUST match one of these:
# a free-text token (`vite`, `high`, `e`) is REFUSED as malformed, so it can never satisfy coverage by
# accident (the audit-pre pass-2 HIGH: broad substrings would let an operator bypass findings they never
# named). Matching is EXACT + case-insensitive over a finding's token set — never a substring scan.
_ADVISORY_ID_RE = re.compile(
    r"^(?:GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|CVE-\d{4}-\d{4,}|[0-9a-f]{16})$", re.IGNORECASE)
# The same shapes, extracted from a finding's free text (`what`) at TOKEN BOUNDARIES — this is how a real
# GHSA/CVE id in a finding's description becomes an identity the override can name it by.
_ADVISORY_TOKEN_RE = re.compile(
    r"\b(?:GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|CVE-\d{4}-\d{4,}|[0-9a-f]{16})\b", re.IGNORECASE)


class _SecurityOverride(NamedTuple):
    """An owner-invoked security-gate override (SPEC-0155 rule 7). PURE data — the flags as given."""
    advisories: tuple      # the advisory ids the owner names as the bypass subject (≥1, id-shaped)
    reason: str            # the non-blank why (journaled verbatim)


def _security_override_precondition(advisories, reason) -> "tuple[_SecurityOverride | None, str | None]":
    """PURE — validate the override flag PAIR. Returns `(override, error)`; exactly one is set, or both
    are None when no override was requested at all. Three outcomes (the reader-owns-fail-closed shape of
    `_security_audit_precondition`):
      * NONE requested (no ids, no reason) → (None, None): the deploy behaves exactly as before.
      * ERROR → a half-declared pair (ids without a reason / a reason without ids), a blank reason, or an
        advisory id that is not advisory-id-SHAPED. Each REFUSES the deploy. A malformed override must
        never silently degrade to "no override" — that would turn an owner's intent to bypass into a
        surprise refusal, and (worse) an operator's malformed id into an accidental pass.
      * OVERRIDE → the validated pair.
    """
    ids = [str(a).strip() for a in (advisories or []) if str(a).strip()]
    why = str(reason or "").strip()
    if not ids and not why:
        return None, None
    if not ids:
        return None, ("`--security-override-reason` was supplied without any "
                      "`--security-override-advisory <ID>` — an override must NAME the advisory it "
                      "bypasses (SPEC-0155 rule 7)")
    if not why:
        return None, ("`--security-override-advisory` was supplied without a "
                      "`--security-override-reason <WHY>` — an override is reason-bearing by contract "
                      "(SPEC-0155 rule 7)")
    malformed = [i for i in ids if not _ADVISORY_ID_RE.match(i)]
    if malformed:
        return None, (f"advisory id(s) {', '.join(malformed)} are not advisory-id-shaped — an override "
                      f"names a finding by an EXACT id (GHSA-xxxx-xxxx-xxxx / CVE-YYYY-NNNN / the "
                      f"finding's 16-hex fingerprint), never a free-text word: a loose token could "
                      f"'cover' findings you never looked at (SPEC-0155 rule 7)")
    return _SecurityOverride(tuple(ids), why), None


def _advisory_tokens(finding: dict) -> set:
    """PURE — the EXACT identity tokens a blocking finding may be named by: its `fingerprint`, its own
    advisory-id fields when the producer records them, and every advisory-id-SHAPED token appearing in its
    free text at a token boundary. Lower-cased for case-insensitive equality. Never a substring scan."""
    tokens = set()
    for key in ("fingerprint", "advisory", "id", "cve", "ghsa"):
        val = str(finding.get(key, "") or "").strip().lower()
        if val:
            tokens.add(val)
    for key in ("what", "fingerprint"):
        for m in _ADVISORY_TOKEN_RE.findall(str(finding.get(key, "") or "")):
            tokens.add(m.lower())
    return tokens


def _override_covers(blocking: list, advisories) -> list:
    """PURE — the blocking findings the override does NOT name. An override is admissible only when this
    is EMPTY: every finding the gate blocked on must be named by an EXACT supplied id (SPEC-0155 rule 7).
    This is what keeps the journaled bypass record TRUE — an operator cannot name one advisory and
    silently ship past three."""
    named = {str(a).strip().lower() for a in (advisories or []) if str(a).strip()}
    return [f for f in (blocking or []) if isinstance(f, dict) and not (_advisory_tokens(f) & named)]


def _run_security_audit_seam(plan: _SecurityAuditPlan, *, revision, project, REPO_ROOT, deploy_env,
                             _append_event, override: "_SecurityOverride | None" = None,
                             deploy_class: "str | None" = None) -> None:
    """SPEC-0155 rule 1 — run the DECLARED security producer at the deploy seam, THEN judge the fresh
    report with the pre-deploy gate, BEFORE the project deploy command runs. Mirrors the C1 pg_dump
    (T-10259) and Class-S security_probe (T-10279) selected-then-executed seam steps: any failure
    REFUSES the deploy (exit 3) from inside, so the project command never runs, nothing goes live, and
    no `deploy_completed` is emitted.

    WHY PRE-DEPLOY. The gate must judge evidence produced FROM the code being deployed, not whatever
    vintage the cron last wrote (the T-0134 stale-block: 13 already-fixed npm HIGHs held two C1
    deploys). Running the producer here regenerates the report from the deploy candidate; the gate then
    accepts/rejects the FRESH report. Cadence runs are unchanged (SPEC-0142) — this is additive
    deploy-time freshness guaranteed by the verb, not operator habit.

    IDENTITY (SPEC-0155 §4, T-10467). The gate is invoked with the deploy candidate's commit in
    `SECURITY_DEPLOY_COMMIT`, which ARMS its identity-match judgement: the report must PROVE it covers
    this candidate (its `commit_identity` + declared lockfile hashes must match the deploy checkout), else
    the gate REFUSES. That binding exists ONLY here, at the seam — a cadence/CI run supplies no candidate,
    so cadence acceptance is unchanged. No second producer identity — the seam runs the ONE declared
    `security.audit.runner` (SPEC-0145 §6), the same one cron uses, so a seam-produced report matches the
    candidate by construction and the match only ever fails on genuinely non-covering evidence.

    PROFILE SCOPE (SPEC-0145 §4/§5, T-12445). The gate ALSO judges whether the report's declared
    check-set is still the CURRENT one — a project whose risk profile has widened owes more checks than
    the report ran. That judgement is class-split, so the seam passes the deploy class it is running
    under in `SECURITY_DEPLOY_CLASS`, exactly as it passes the candidate commit: class A (code-only,
    trivially reversible — SPEC-0097 §2) WARNS and PROCEEDS, and this seam journals one
    `security_audit_scope_stale` row naming what it proceeded over; every other class REFUSES inside the
    gate, on the ordinary non-zero-exit path above. The cadence path supplies no class and no candidate,
    and reports scope-stale regardless."""
    command = plan.runner
    print(f"deploy: running the declared security producer at the seam (SPEC-0155 rule 1); the gate "
          f"judges the FRESH report before the deploy runs:")
    print(f"  $ {command}")
    started = time.monotonic()
    try:
        # Same shell-on-the-command-string shape as the Class-S probe seam (audit-pre YELLOW absorbed).
        result = subprocess.run(command, cwd=str(REPO_ROOT), shell=True, env=deploy_env,
                                timeout=_SECURITY_AUDIT_SEAM_BUDGET_S)
    except subprocess.TimeoutExpired:
        print(f"deploy: REFUSED — the deploy-seam security producer exceeded its "
              f"{_SECURITY_AUDIT_SEAM_BUDGET_S}s budget (SPEC-0155 rule 1). A producer that cannot "
              f"produce fresh evidence within budget cannot gate the deploy. The deploy did NOT run; "
              f"no deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)
    duration = time.monotonic() - started
    if result.returncode != 0:
        print(f"deploy: REFUSED — the deploy-seam security producer exited {result.returncode} "
              f"(SPEC-0155 rule 1): no fresh security report was produced from the deploy candidate, so "
              f"the pre-deploy gate has nothing trustworthy to judge. The deploy did NOT run; no "
              f"deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)
    _append_event("deploy_security_audit_produced", None,
                  {"revision": revision, "project": project, "runner": command,
                   "duration_seconds": round(duration, 3)})
    print(f"deploy: security producer OK in {duration:.1f}s; deploy_security_audit_produced emitted. "
          f"Judging the fresh report with the pre-deploy gate:")

    # THE PRE-DEPLOY GATE — the deterministic, provider-independent v2-security-gate judges the fresh
    # report (freshness-by-SLA / completeness / open critical-high). Engine-resolved path so it works in
    # a `-C <consumer>` session (the gate is a KERNEL script, next to this module's parent bin/); the
    # PROJECT under judgement is REPO_ROOT, passed as argv[0]. stdout/stderr are INHERITED — the gate's
    # PASS/FAIL verdict is the operator's evidence and must be seen live. A non-zero gate exit REFUSES
    # the deploy (exit 3): the fresh report did not pass, so the revision must not ship.
    # SECURITY_DEPLOY_COMMIT arms the gate's SPEC-0155 §4 identity match (see IDENTITY above): the
    # candidate `revision` is the sha this deploy ships (HEAD; the seam is deploy-only, never rollback),
    # so it IS the code the report must prove it covers.
    # SECURITY_GATE_VERDICT_FILE (SPEC-0155 rule 7) publishes the gate's verdict — its reject CLASS and,
    # on a blocking reject, the finding RECORDS — into a run-scoped temp file. It is what lets the
    # owner-override be BOUNDED (severity-blocking only) and TRUTHFUL (it must name every blocked
    # finding). An absent/unparseable verdict simply means "no override possible" below, so this channel
    # can only ever make the seam stricter than the bare exit code — never laxer.
    gate_path = Path(__file__).resolve().parent.parent / "v2-security-gate"
    with tempfile.TemporaryDirectory(prefix="yitc-gate-verdict-") as _vdir:
        verdict_path = Path(_vdir) / "verdict.json"
        gate_env = {**deploy_env, "SECURITY_DEPLOY_COMMIT": str(revision),
                    "SECURITY_GATE_VERDICT_FILE": str(verdict_path)}
        # SPEC-0145 §5 class split. Set ONLY when a class is known: its ABSENCE is the cadence/no-class
        # path, which the gate reads as "reject scope-stale regardless of class". Threading an empty
        # string would be indistinguishable from a class the gate does not soften for, so it is omitted.
        if deploy_class:
            gate_env["SECURITY_DEPLOY_CLASS"] = str(deploy_class)
        gate = subprocess.run([sys.executable, str(gate_path), str(REPO_ROOT)],
                              cwd=str(REPO_ROOT), env=gate_env)
        verdict = _read_gate_verdict(verdict_path)

    if gate.returncode != 0:
        if override is not None:
            _apply_security_gate_override(override, verdict, gate_exit=gate.returncode,
                                          revision=revision, project=project, _append_event=_append_event)
            return       # overridden — the deploy proceeds; NO gate_passed event (the gate did not pass)
        print(f"deploy: REFUSED — the pre-deploy security gate REJECTED the fresh report "
              f"(v2-security-gate exit {gate.returncode}, SPEC-0155 rule 1). The deploy did NOT run; "
              f"no deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)
    _append_event("deploy_security_gate_passed", None, {"revision": revision, "project": project})
    print(f"deploy: pre-deploy security gate PASSED on the fresh report; deploy_security_gate_passed "
          f"emitted.")
    # SPEC-0145 §5 — the class-A scope-stale WARN. The gate PASSED, so the deploy proceeds; what must
    # not be silent is that it proceeded over a report produced under a NARROWER profile than the
    # project now carries. The row's PRESENCE is the signal (SPEC-0025). Read off the gate's OWN
    # published verdict — never re-derived here — so the record is the gate's judgement, and an
    # absent/unparseable verdict simply emits nothing (it can only ever under-report, never fabricate).
    scope_stale = (verdict or {}).get("scope_stale") or {}
    if isinstance(scope_stale, dict) and scope_stale:
        _append_event("security_audit_scope_stale", None, {
            "class": scope_stale.get("class"),
            "report_hash": scope_stale.get("report_hash"),
            "current_check_set_hash": scope_stale.get("current_check_set_hash"),
        })
        print(f"deploy: WARN — the security report's profile check-set is a strict SUBSET of the "
              f"CURRENT required set ({scope_stale.get('detail', '')}). Class A is code-only and "
              f"trivially reversible (SPEC-0097 §2), so the deploy PROCEEDS; "
              f"security_audit_scope_stale emitted.", file=sys.stderr)


# ── SPEC-0097 §11 — the POST-exit-0 convergence verification (T-10510, X-0374) ───────────────────────
# A generous SAFETY default for asking a service what revision it runs — NOT a governance scalar
# (SPEC-0093 §Parameters non-whitelist): it only stops an unresponsive service from hanging the seam
# forever. A project may override it per-carrier with `deploy.convergence.budget_seconds`.
_CONVERGENCE_BUDGET_S = int(os.environ.get("YITC_CONVERGENCE_BUDGET_S", "120"))

# The shortest revision token that may be accepted as a match. A service legitimately reports an
# ABBREVIATED sha (`git rev-parse --short` → 7-12 chars), so a prefix match is the honest comparison —
# but an EMPTY or 1-char report prefix-matches everything, which is a false green wearing a match's
# clothes. Below this length a report is not a revision claim at all and the service is NOT converged.
_MIN_REVISION_TOKEN = 7


class _ConvergencePlan(NamedTuple):
    """The declared `deploy.convergence` block — which running services must report the deployed
    revision, and which are declared out of scope. PURE data (no subprocess/git), so the precondition is
    unit-testable in isolation (mirrors `_BackupPlan` / `_SecurityProbePlan` / `_SecurityAuditPlan`)."""
    services: "dict | None"       # {service name: command PRINTING the revision that service RUNS}
    budget_seconds: "int | None"  # per-service timeout for asking
    out_of_scope: dict            # {service name: WHY it is not verified} — declared, never silent
    skip_reason: "str | None"     # SKIP (fail-open) — nothing declared; deploy exactly as before
    error: "str | None"           # None ⇒ usable; else the fail-closed reason to print + refuse on
    # T-11356 — {service name: the repo-relative paths that service is BUILT FROM}. Present ONLY for a
    # service that declared them; a service absent from this map is judged by STRICT equality with the
    # deployed revision, exactly as before (which is why it defaults to empty: an undeclared project is
    # byte-unchanged). Kept BESIDE `services` rather than folded into its values so the declaration's
    # shape stays one-command-per-service for every existing reader.
    service_paths: dict = {}


def _convergence_precondition(deploy_section) -> _ConvergencePlan:
    """PURE — extract the declared `deploy.convergence` block (SPEC-0097 §11). Three outcomes, the same
    reader-owns-fail-closed discipline as `_security_audit_precondition`
    (lessons/fail-closed-belongs-to-the-reader-not-the-parser.md):

      * SKIP — no `convergence:` block, or a waived one. A project that has NOT declared its services
        deploys EXACTLY as before this spec (fail-OPEN on ABSENCE — a kernel mechanism must not ambush
        every existing consumer's deploy at the seam the day it ships). What makes the absence VISIBLE
        instead of silent is elsewhere by design: the declare-or-waive init sweep (SPEC-0093 rule 3,
        registry-driven) demands an answer in the carrier, and SPEC-0156 surfaces a declared-but-
        undemonstrated check as UNPROVEN debt.
      * ERROR — a PRESENT but malformed declaration. A corrupt check declaration must REFUSE, never
        silently degrade to «no convergence was wanted» (the silent-disable class SPEC-0148 §3 closed):
        that degradation is precisely how a service escapes verification unnoticed.
      * USABLE — the services to ask + the budget to ask them within.

    Called BEFORE the deploy command runs (with `_recheck_window`), so a malformed carrier refuses with
    NOTHING live — even though the verification itself necessarily runs AFTER (§11)."""
    convergence = deploy_section.get("convergence") if isinstance(deploy_section, dict) else None
    if not isinstance(convergence, dict):
        return _ConvergencePlan(None, None, {}, "no `deploy.convergence` block declared (SPEC-0097 §11) "
                                "— no in-scope services to verify", None)
    if isinstance(convergence.get("waiver"), dict):
        reason = str(convergence["waiver"].get("reason") or "").strip() or "no reason given"
        return _ConvergencePlan(None, None, {},
                                f"`deploy.convergence` is waived ({reason}) — no in-scope services to "
                                f"verify", None)

    services = convergence.get("services")
    if not isinstance(services, dict) or not services:
        return _ConvergencePlan(None, None, {}, None,
                                "`deploy.convergence.services` is absent, empty, or not a mapping — "
                                "declare `{<service>: <command printing the revision it RUNS>}`, or "
                                "`waiver: {reason: <why>}` to stay unverified")
    clean: dict = {}
    paths_by_service: dict = {}
    for name, declared in services.items():
        # T-11356 — TWO accepted forms. The bare string is the original and stays exactly what it was.
        # The mapping form adds `paths:` — the sources the service is BUILT FROM — which is what lets a
        # service that was legitimately NOT rebuilt (its own sources did not move) be judged CURRENT
        # instead of stale. A mapping with no `paths:` is simply the bare form spelled longer.
        paths = None
        if isinstance(declared, dict):
            command = declared.get("command")
            paths = declared.get("paths")
        else:
            command = declared
        if not isinstance(command, str) or not command.strip():
            return _ConvergencePlan(None, None, {}, None,
                                    f"`deploy.convergence.services[{name}]` is not a non-blank command "
                                    f"string — every in-scope service needs a command that PRINTS the "
                                    f"revision it is running")
        clean[str(name)] = command.strip()
        if paths is None:
            continue
        # Fail-closed on a MALFORMED `paths:` — a declaration that cannot be read must refuse BEFORE the
        # deploy runs, never degrade into "no paths were declared". That degradation would silently
        # restore the strict rule for a service the project believed it had scoped, which is the
        # silent-disable class SPEC-0148 §3 closed, one level down.
        if not isinstance(paths, list) or not paths:
            return _ConvergencePlan(None, None, {}, None,
                                    f"`deploy.convergence.services[{name}].paths` is present but not a "
                                    f"NON-EMPTY list — declare the repo-relative source paths this "
                                    f"service is built from, or omit `paths:` to require the deployed "
                                    f"revision exactly")
        clean_paths = []
        for entry in paths:
            if not isinstance(entry, str) or not entry.strip():
                return _ConvergencePlan(None, None, {}, None,
                                        f"`deploy.convergence.services[{name}].paths` carries a blank / "
                                        f"non-string entry — every source path must be a repo-relative "
                                        f"path string")
            entry = entry.strip()
            # A path that leaves the repo cannot be compared between two revisions of it, and an
            # absolute path is a host fact rather than a repo one — both are refusals, not silent drops.
            if entry.startswith("/") or entry == ".." or entry.startswith("../") or "/../" in entry:
                return _ConvergencePlan(None, None, {}, None,
                                        f"`deploy.convergence.services[{name}].paths` entry `{entry}` is "
                                        f"absolute or escapes the repository — a service's sources must "
                                        f"be repo-relative paths that two revisions can be compared over")
            clean_paths.append(entry)
        paths_by_service[str(name)] = tuple(clean_paths)

    budget = convergence.get("budget_seconds", _CONVERGENCE_BUDGET_S)
    # bool is an int subclass — `True` must never read as a 1-second budget (same guard as C1 / Class-S).
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        return _ConvergencePlan(None, None, {}, None,
                                "`deploy.convergence.budget_seconds` is present but not a positive "
                                "integer — a service probe with no budget could hang the deploy seam")

    # `out_of_scope` is the DECLARE-OR-WAIVE half: a service deliberately not verified names itself and
    # WHY. It is never probed — but it IS printed and journalled, so the exemption is auditable rather
    # than an unrecorded gap. A blank reason is the silent omission this key exists to prevent.
    out_of_scope = convergence.get("out_of_scope", {})
    if out_of_scope is None:
        out_of_scope = {}
    if not isinstance(out_of_scope, dict):
        return _ConvergencePlan(None, None, {}, None,
                                "`deploy.convergence.out_of_scope` is present but not a mapping — "
                                "declare `{<service>: <why it is not verified>}`")
    waived: dict = {}
    for name, reason in out_of_scope.items():
        if not isinstance(reason, str) or not reason.strip():
            return _ConvergencePlan(None, None, {}, None,
                                    f"`deploy.convergence.out_of_scope[{name}]` carries no reason — a "
                                    f"service excluded from convergence must say WHY (declare-or-waive, "
                                    f"SPEC-0093 rule 3); a blank exemption is a silent gap")
        waived[str(name)] = reason.strip()

    return _ConvergencePlan(clean, budget, waived, None, None, paths_by_service)


def _convergence_section_for_target(deploy_section, dtarget) -> "tuple[dict | None, str | None]":
    """PURE — WHICH declaration's `convergence:` block governs THIS deploy (SPEC-0097 §11 per-target axis,
    T-11996/X-1234). Returns `(section_to_read, skip_reason)`; exactly one of the two is ever set.

    THE DEFECT THIS CLOSES. `--target` (SPEC-0094 §1) gave the verb many surfaces, but the §11 convergence
    plan was still built from the TOP-LEVEL `deploy.convergence` block regardless of the resolved target —
    so a sandbox deploy was verified against the PRODUCTION containers (aiseller 2026-09-02, X-1234). The
    services a project runs are a property of the SURFACE, not of the project: two surfaces have two sets.

    IT SELECTS A DECLARATION; IT NEVER PARSES ONE. `_convergence_precondition` stays the SOLE parser and is
    NOT taught about targets, so the per-target block reuses the SAME schema (services / paths /
    budget_seconds / out_of_scope / waiver) and the SAME SKIP / ERROR / USABLE outcomes — one schema, one
    parser, one set of verdicts (CHARTER §P1 F1/F2). In particular a MALFORMED per-target block refuses
    before anything is live, exactly as a malformed top-level one does.

    THE READER OWNS THE MISSING-VALUE JUDGEMENT (lessons/fail-closed-belongs-to-the-reader-not-the-
    parser.md). An ABSENT `convergence:` key means DIFFERENT things per class, which is precisely why the
    decision cannot live inside the shared parser:

      * no `--target` at all — the top-level block governs, and the `targets:` block is not consulted.
        Byte-identical to before this rule, which is the back-compatibility guarantee, not a courtesy.
      * the target declares its OWN block — that block governs. The whole point of the axis.
      * a PRODUCTION target with no own block — the top-level block governs. It has always described the
        production services, so reading it here is what it already meant.
      * a NON-PRODUCTION target with no own block — NOTHING governs: SKIP, with a reason NAMING the
        target. The top-level block describes production's services, and silently probing THEM for a
        sandbox deploy is the X-1234 defect itself. Fail-OPEN on absence is §11's own discipline for an
        undeclared surface (a kernel mechanism must not ambush a consumer at the seam), but the absence is
        STATED — an unverified surface that says so is not the same thing as one verified against the
        wrong services.

    THE DISCRIMINATOR IS A POSITIVE DECLARATION, and that is the whole safety of the last leg
    (lessons/carving-an-exception-into-a-fail-closed-gate.md). The SKIP is opened ONLY by
    `production is False`, and `production:` is a MANDATORY boolean `_resolve_deploy_target` has already
    validated — an absent, null or non-boolean stance REFUSES the entire deploy before any side effect,
    and a target's NAME is never read as evidence. So a BROKEN declaration can never reach the lighter
    path; only a positive `production: false` can.

    `--target` is DEPLOY-ONLY (refused with `--rollback`, T-11932), so a rollback always takes the first
    leg and its convergence read is unchanged."""
    if dtarget is None or dtarget.name is None:
        # The DEFAULT path, untouched — `targets:` is not consulted at all.
        return deploy_section, None

    targets = deploy_section.get("targets") if isinstance(deploy_section, dict) else None
    entry = targets.get(dtarget.name) if isinstance(targets, dict) else None
    if isinstance(entry, dict) and "convergence" in entry:
        # The target's OWN declaration governs — parsed by the same function, so its malformed shapes
        # refuse and its waiver/absence outcomes read exactly as the top-level block's do.
        return entry, None

    if dtarget.production is False:
        return None, (f"target `{dtarget.name}` declares no `convergence:` block of its own and is "
                      f"NON-PRODUCTION (`targets.{dtarget.name}.production: false`), so the top-level "
                      f"`deploy.convergence` block — which describes the PRODUCTION services — is NOT "
                      f"read for it (SPEC-0097 §11, X-1234): verifying this deploy against another "
                      f"surface's services would be worse than not verifying it. Declare "
                      f"`deploy.targets.{dtarget.name}.convergence` (same schema) to verify it")

    # A PRODUCTION target with no block of its own: the top-level block is exactly what describes it.
    return deploy_section, None


def _revision_converged(reported: "str | None", revision: str) -> bool:
    """Does `reported` name the SAME revision as `revision`? PURE + total.

    A prefix match in EITHER direction, because an abbreviated sha (`git rev-parse --short`) is a
    legitimate way for a service to report itself. The `_MIN_REVISION_TOKEN` floor is what keeps that
    leniency from becoming the very false-green it guards: an empty / near-empty report is a prefix of
    every sha, so without the floor a service that answers with a blank line would read as CONVERGED."""
    token = (reported or "").strip().lower()
    if len(token) < _MIN_REVISION_TOKEN:
        return False
    target = revision.strip().lower()
    return target.startswith(token) or token.startswith(target)


def _service_sources_unchanged(reported: "str | None", revision: str, paths, *,
                               REPO_ROOT) -> "tuple[bool, str | None]":
    """T-11356 — is the code this service RUNS identical, over its OWN declared sources, to the code the
    deployed revision says it should run? Returns `(unchanged, reason_it_is_not)`.

    THE QUESTION §11 WAS MISSING. Convergence asks every declared service to report the DEPLOYED sha. That
    is the right question for a service this deploy rebuilt, and the wrong one for a service it did not:
    aiseller's frontend-only deploy left five backend services on the prior sha — byte-identical backend
    code, simply not rebuilt — and the guard called that a non-convergence, which it was not. The honest
    test is not «did you come up on HEAD» but «is what you run the same code HEAD would build you from»,
    and that is decidable from the REPOSITORY, with nobody's word taken for it.

    WHY IT IS MEASURED AGAINST THE REPO AND NOT AGAINST A DECLARED RUN-SCOPE. The other candidate shape
    was to let the deploy RUN declare which services it touched. But the only actor that knows a run's
    scope is the project's deploy command — the very actor whose self-grading X-0374 proved untrustworthy,
    and which this whole seam exists to CHECK («exit-0 is the project's REPORT; convergence is the
    kernel's CHECK of it», SPEC-0097 §11). aiseller's script, whose «smart affected-service detection»
    skipped celery-worker-long, would have declared celery-worker-long out of that run's scope and gone
    GREEN on the exact incident. Scope taken from the checked party is not a narrowing of the check, it is
    a hole in it. The repository cannot be talked into an answer.

    FAIL-CLOSED, three edges. An unresolvable reported revision, a declared path that names NOTHING at
    either compared revision, or a git that answers anything other than a clean same/differ, is NOT
    unchanged: an un-comparable service is un-verified, and un-verified has never been evidence of a pass —
    the same rule `_ask_service_revision`'s callers already hold.

    THE THIRD EDGE IS THE ONE THAT LOOKED LIKE A PASS (T-11671, aiseller X-1125). `_convergence_precondition`
    validates only the SHAPE of a declared path — non-empty list, non-blank string, repo-relative, no escape
    — never its EXISTENCE, and `git diff --quiet` accepts an unmatched pathspec SILENTLY: `git diff --quiet
    HEAD~1 HEAD -- no/such/path.txt` exits 0. So before this check a TYPO read as UNCHANGED and the service
    was recorded CURRENT — a silent false-pass of the same silent-disable class SPEC-0148 §3 closed, one
    level down, and the worst possible shape for it: the declaration LOOKS like scoping and does nothing.
    Existence is resolved against the COMPARED REVISIONS, never the working tree — a path can exist in the
    checkout and not in the revision being compared, and it is the revisions that are being diffed. EITHER
    revision suffices, not both: a source tree legitimately ADDED or DELETED between the two exists at one
    of them and is genuinely comparable, so demanding both would refuse honest declarations."""
    token = (reported or "").strip()
    if len(token) < _MIN_REVISION_TOKEN:
        return False, (f"the reported revision `{token}` is too short to identify a commit "
                       f"(< {_MIN_REVISION_TOKEN} chars)")
    resolved = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{token}^{{commit}}"],
                              cwd=str(REPO_ROOT), capture_output=True, text=True)
    if resolved.returncode != 0 or not resolved.stdout.strip():
        return False, (f"the reported revision `{token}` is not a commit in this repository, so the "
                       f"sources it was built from cannot be compared")
    base = resolved.stdout.strip()
    for entry in paths:
        # Ask the REPOSITORY whether this entry names anything at either revision being compared. `ls-tree`
        # is the right instrument because it matches what `git diff`'s pathspec matches — a file, a
        # directory, or a glob — so an entry this accepts is exactly an entry the diff below can be about.
        matched = False
        for rev in (base, revision):
            listed = subprocess.run(["git", "ls-tree", "-r", "--name-only", rev, "--", entry],
                                    cwd=str(REPO_ROOT), capture_output=True, text=True)
            if listed.returncode != 0:
                # Un-answerable is not evidence of existence — same fail-closed floor as the two edges
                # above, rather than an optimistic "assume it is there".
                return False, (f"its declared source path `{entry}` could not be resolved at "
                               f"{rev[:12]} (git ls-tree exited {listed.returncode}), so this "
                               f"declaration cannot be verified")
            if listed.stdout.strip():
                matched = True
                break
        if not matched:
            return False, (f"its declared source path `{entry}` names NOTHING at either compared "
                           f"revision ({base[:12]} or {revision[:12]}) — most likely a typo. An "
                           f"unmatched pathspec is SILENTLY UNCHANGED to `git diff`, so leaving it "
                           f"unchecked would record this service as CURRENT on a declaration that "
                           f"verifies nothing; correct the path in "
                           f"`deploy.convergence.services.<service>.paths`")
    diff = subprocess.run(["git", "diff", "--quiet", base, revision, "--", *paths],
                          cwd=str(REPO_ROOT), capture_output=True, text=True)
    if diff.returncode == 0:
        return True, None
    if diff.returncode == 1:
        return False, (f"its declared sources ({', '.join(paths)}) CHANGED between {base[:12]} and "
                       f"{revision[:12]} — this service needed rebuilding and was not rebuilt")
    detail = (diff.stderr or diff.stdout or "").strip().splitlines()
    return False, (f"comparing its declared sources exited {diff.returncode}"
                   + (f": {detail[-1][:200]}" if detail else ""))


def _ask_service_revision(command: str, *, budget_seconds, REPO_ROOT, deploy_env) -> "tuple[str | None, str | None]":
    """Ask ONE service what revision it is running. Returns `(reported, error)` — exactly one is set.

    stdout is CAPTURED (unlike the smoke/probe seams, whose output IS the operator's evidence): here the
    output is a VALUE the kernel must compare, not a verdict to display. The reported revision is the LAST
    non-blank line of stdout, so a command that prints a banner before the sha still answers usefully.
    stderr is captured too and surfaced only on failure — a service that cannot be asked is a FAILURE to
    report, never a pass."""
    try:
        result = subprocess.run(command, cwd=str(REPO_ROOT), shell=True, env=deploy_env,
                                capture_output=True, text=True, timeout=budget_seconds)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {budget_seconds}s (the service did not answer)"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return None, (f"the revision command exited {result.returncode}"
                      + (f": {detail[-1][:200]}" if detail else ""))
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None, "the revision command printed nothing — the service reported no revision"
    return lines[-1], None


def _verify_convergence(plan: _ConvergencePlan, *, revision, project, kind, REPO_ROOT, deploy_env,
                        _append_event) -> dict:
    """SPEC-0097 §11 — verify that EVERY in-scope running service actually converged to `revision`, AFTER
    the project deploy command exited 0 and BEFORE `deploy_completed` is emitted. Returns the convergence
    payload to stamp onto that event; on ANY non-convergence it emits `deploy_convergence_failed` and
    EXITS 5 — so `deploy_completed` is never emitted for a revision that is not actually live.

    WHY THIS ONE IS POST-DEPLOY, AND WHY THAT DOES NOT CONTRADICT THE PRE-DEPLOY SIBLINGS. The C1 backup,
    the Class-S probe and the SPEC-0155 security gate all run BEFORE the command, because each asserts a
    property `deploy_completed` does NOT itself claim, and a kernel refusal AFTER exit-0 would leave the
    revision live with the journal silent (`_run_class_s_security_probe` §WHY PRE-DEPLOY). Convergence is
    different in KIND: it IS `deploy_completed`'s own claim — «this revision is live». It therefore cannot
    be asked before the deploy (there is nothing yet to converge TO), and emitting the event without asking
    is what X-0374 did: aiseller's deploy script skipped celery-worker-long by «smart affected-service
    detection», the worker kept running old source-mounted code and kept printing the credential the deploy
    claimed to have redacted, while `deploy_completed` asserted the revision live. The «journal silent»
    objection is answered NOT by emitting a false green but by RECORDING the non-convergence: this is the
    only refusal in this verb that leaves prod MUTATED, so it is the only one that emits an event when it
    refuses, and it exits 5 (not 3/4 — those are pre-deploy refusals where nothing ran) to say exactly
    that: APPLIED, NOT CONVERGED — an operator's call, not a retry.

    Fail-closed per service: a service that cannot be ASKED (non-zero, timeout, empty answer) is NOT
    converged. «We could not check» has never been evidence of a pass — treating it as one is the same
    false-green this whole seam exists to end."""
    if plan.out_of_scope:
        for name, reason in sorted(plan.out_of_scope.items()):
            print(f"deploy: convergence — `{name}` is declared OUT OF SCOPE ({reason}); not verified "
                  f"(SPEC-0097 §11 declare-or-waive).")
    print(f"deploy: verifying convergence of {len(plan.services)} in-scope service(s) to "
          f"{revision[:12]} (budget {plan.budget_seconds}s each) — deploy_completed is NOT emitted "
          f"until every one of them reports it:")

    converged: dict = {}
    current: dict = {}
    stale: dict = {}
    # T-11577 — the names that went stale on the NO-DECLARED-SOURCES fallback, kept as a LOCAL and never
    # a payload key: this card changes what the refusal SAYS, never what the event RECORDS. It exists so
    # the summary sentence below can be conditional — guidance that printed on every refusal would be
    # noise on exactly the refusals where the service is honestly stale.
    undeclared_stale: list = []
    for name, command in sorted(plan.services.items()):
        paths = plan.service_paths.get(name) or ()
        reported, error = _ask_service_revision(command, budget_seconds=plan.budget_seconds,
                                                REPO_ROOT=REPO_ROOT, deploy_env=deploy_env)
        if error is not None:
            stale[name] = {"error": error}
            print(f"  ✗ {name}: COULD NOT VERIFY — {error}", file=sys.stderr)
        elif _revision_converged(reported, revision):
            converged[name] = reported
            print(f"  ✓ {name}: {reported} — converged")
        elif not paths:
            # No declared sources ⇒ the ORIGINAL rule, verbatim: report the deployed revision or be stale.
            #
            # T-11577 — SAY WHY THIS SERVICE COULD NOT TAKE THE CURRENT BRANCH. The verdict is unchanged;
            # what was missing is that the operator could not SEE the cure T-11356 shipped. A service is
            # judged on its OWN sources only when it DECLARES them, and this branch is by definition the
            # one where it did not — so a project-side declaration gap reads, at the refusal, as a kernel
            # defect (aiseller X-1102; the same unreadable-cure class as X-1101). The paths-declared
            # STALE arm below is deliberately NOT given this line: that service IS honestly stale, and
            # printing the declaration hint there would make it blanket noise.
            stale[name] = {"reported": reported}
            print(f"  ✗ {name}: reports {reported} — STALE (expected {revision[:12]}); it declares NO "
                  f"source paths, so it can only be judged by whether it reports the DEPLOYED revision. "
                  f"If this service was legitimately not rebuilt, declare its sources as "
                  f"`deploy.convergence.services.{name}.paths` in yitc-ops.yaml — it is then judged on "
                  f"whether ITS OWN sources changed between the two revisions (SPEC-0097 §11).",
                  file=sys.stderr)
            undeclared_stale.append(name)
        else:
            unchanged, why = _service_sources_unchanged(reported, revision, paths, REPO_ROOT=REPO_ROOT)
            if unchanged:
                # RECORDED AS ITS OWN CATEGORY, never folded into `converged`. The event must not claim
                # this service reports the deployed sha — it does not, and saying so would be the same
                # class of comfortable inaccuracy the seam exists to refuse. It says the true thing
                # instead: this service runs OTHER code that is IDENTICAL over the sources it is built
                # from, so there was nothing for this deploy to rebuild.
                current[name] = {"reported": reported, "paths": list(paths)}
                print(f"  ✓ {name}: {reported} — CURRENT (not rebuilt; its declared sources "
                      f"({', '.join(paths)}) are unchanged at {revision[:12]})")
            else:
                stale[name] = {"reported": reported, "sources": list(paths), "why": why}
                print(f"  ✗ {name}: reports {reported} — STALE: {why}", file=sys.stderr)

    payload = {"revision": revision, "project": project, "kind": kind,
               "converged": converged, "current": current, "out_of_scope": plan.out_of_scope}
    if stale:
        payload["stale"] = stale
        _append_event("deploy_convergence_failed", None, payload)
        names = ", ".join(sorted(stale))
        print(f"deploy: REFUSED — the {kind} command exited 0, but {len(stale)} of "
              f"{len(plan.services)} in-scope service(s) did NOT converge to {revision[:12]}: {names} "
              f"(SPEC-0097 §11). NO deploy_completed emitted — this revision is NOT live everywhere, and "
              f"recording it as live is the false green X-0374 shipped. The {kind} IS APPLIED BUT NOT "
              f"CONVERGED: prod has changed, so this is not a retry — an operator must converge or roll "
              f"back the listed service(s). deploy_convergence_failed emitted (the partial apply is on "
              f"the record, never silent).", file=sys.stderr)
        if undeclared_stale:
            # ONE sentence, and only when the fallback actually fired: a service legitimately not
            # rebuilt is DECLARED with source paths, and an undeclared one cannot be judged that way.
            print(f"deploy: {len(undeclared_stale)} of the service(s) above "
                  f"({', '.join(sorted(undeclared_stale))}) declare no `paths`, so converging or rolling "
                  f"back is not the only resolution: a service that this deploy legitimately did not "
                  f"rebuild is declared with its own source paths under "
                  f"`deploy.convergence.services.<service>.paths`, and only a service that declares them "
                  f"can be judged CURRENT on unchanged sources instead of stale (SPEC-0097 §11).",
                  file=sys.stderr)
        sys.exit(5)

    print(f"deploy: convergence OK — {len(converged)} in-scope service(s) report {revision[:12]}"
          + (f"; {len(current)} run other revision(s) whose declared sources are IDENTICAL at "
             f"{revision[:12]} (nothing to rebuild)." if current else "."))
    return {"verified": converged, "current": current, "out_of_scope": plan.out_of_scope}


def _read_gate_verdict(path: Path) -> "dict | None":
    """The gate's published verdict, or None when it is absent/unreadable/malformed. None is the
    fail-closed value: the override caller treats it as "not provably a blocking reject" and REFUSES."""
    try:
        with open(path, encoding="utf-8") as f:
            verdict = json.load(f)
    except (OSError, ValueError):
        return None
    return verdict if isinstance(verdict, dict) else None


def _apply_security_gate_override(override: _SecurityOverride, verdict: "dict | None", *, gate_exit,
                                  revision, project, _append_event) -> None:
    """SPEC-0155 rule 7 — admit the owner's override of a REJECTED gate, or REFUSE (exit 3). Returns only
    on an ADMITTED override; every refusal path exits, so a caller that returns is provably overridden.

    Four conditions, ALL required (any failure ⇒ refuse, and say exactly which):
      1. the gate published a verdict we can read (else we cannot know WHAT we would be bypassing);
      2. its reject class is `blocking` — the open-critical/high SEVERITY class, the only overridable one
         (every other class means the evidence is untrustworthy or does not cover the deployed code);
      3. it names ≥1 blocking finding (a `blocking` verdict with no records is incoherent — fail closed);
      4. the override NAMES every one of them (`_override_covers` residue empty).
    """
    reason_class = str((verdict or {}).get("reason") or "")
    blocking = (verdict or {}).get("blocking") or []

    if verdict is None:
        print(f"deploy: REFUSED — the security gate rejected (exit {gate_exit}) and published no readable "
              f"verdict, so the override has nothing to act on: it cannot be proven that the rejection is "
              f"the overridable SEVERITY-blocking class, nor WHICH findings would be bypassed. An override "
              f"is never granted on an unknown (SPEC-0155 rule 7). The deploy did NOT run.", file=sys.stderr)
        sys.exit(3)
    if reason_class != "blocking":
        print(f"deploy: REFUSED — the security gate rejected with class `{reason_class}`, which is NOT "
              f"overridable (SPEC-0155 rule 7). The override covers ONLY the SEVERITY-blocking class (open "
              f"critical/high findings). A `{reason_class}` rejection means the evidence itself is "
              f"untrustworthy or does not cover the code being deployed — overriding it would deploy BLIND. "
              f"Fix the evidence (re-run the security producer); the deploy did NOT run.", file=sys.stderr)
        sys.exit(3)
    if not blocking:
        print(f"deploy: REFUSED — the security gate reported a `blocking` rejection but named no findings; "
              f"an override cannot be proven to name what it bypasses (SPEC-0155 rule 7). The deploy did "
              f"NOT run.", file=sys.stderr)
        sys.exit(3)

    uncovered = _override_covers(blocking, override.advisories)
    if uncovered:
        named = ", ".join(f"{f.get('fingerprint') or '?'} ({str(f.get('what') or '?')[:60]})"
                          for f in uncovered)
        print(f"deploy: REFUSED — the override does NOT name {len(uncovered)} of the {len(blocking)} "
              f"blocking finding(s): {named}. An override must name EVERY finding it bypasses, by exact "
              f"advisory id or fingerprint (SPEC-0155 rule 7) — otherwise the journaled record would claim "
              f"a bypass it does not describe. Supply an `--security-override-advisory <ID>` for each, or "
              f"fix the finding. The deploy did NOT run.", file=sys.stderr)
        sys.exit(3)

    # ADMITTED. Loud by design: an override is a governed exception, never a routine step — it must be
    # impossible to perform quietly, both on the terminal (here) and in the record (the event below).
    print("deploy: " + "=" * 72, file=sys.stderr)
    print(f"deploy: SECURITY GATE OVERRIDDEN — owner-invoked (SPEC-0155 rule 7). The gate REJECTED this "
          f"revision on {len(blocking)} open critical/high finding(s) and the deploy is proceeding ANYWAY:",
          file=sys.stderr)
    for f in blocking:
        print(f"deploy:   · [{f.get('severity') or '?'}] {f.get('fingerprint') or '?'} — "
              f"{str(f.get('what') or '?')[:100]}", file=sys.stderr)
    print(f"deploy:   advisories named: {', '.join(override.advisories)}", file=sys.stderr)
    print(f"deploy:   reason: {override.reason}", file=sys.stderr)
    print(f"deploy:   this is JOURNALED as deploy_security_gate_overridden and surfaces in `bin/yitc-v2 "
          f"debt` — the findings above remain OPEN and still need fixing.", file=sys.stderr)
    print("deploy: " + "=" * 72, file=sys.stderr)

    # The event carries the GATE's own finding records — not the operator's claim about them (the record
    # of what was bypassed must be the judge's, or it is not evidence). NO deploy_security_gate_passed is
    # emitted anywhere on this path: the gate did NOT pass.
    _append_event("deploy_security_gate_overridden", None, {
        "revision": revision,
        "project": project,
        "reason": override.reason,
        "advisories": list(override.advisories),
        "blocking": blocking,
        "gate_reject_class": reason_class,
        "gate_exit": gate_exit,
    })


# ── Named deploy TARGETS (T-11932, SPEC-0094 §1 / SPEC-0097 §12) ───────────────────────────────
# WHY. A project whose only governed deploy path is the bare `deploy.command` can record ONLY the
# target that command happens to address — in practice PRODUCTION. A project that also runs a
# sandbox (kupiclub `scripts/deploy.sh --target sandbox`) therefore has SPEC-0094 evidence for the
# surface it deploys RARELY and none for the one it deploys OFTEN — which is also where a
# collaborator's change lands first (X-1201). The fix EXTENDS the one verb rather than letting each
# consumer grow a second deploy-recording path (CHARTER §P5 forbids a parallel path by name).
#
# SHAPE. `deploy.targets.<name>: {command: <cmd>, production: true|false}`. Absent `--target` never
# reads this block at all, so a consumer declaring no targets is byte-identical to before.


class _DeployTarget(NamedTuple):
    """The RESOLVED invocation: which command runs, under which name, at which production stance.
    PURE data (mirrors `_BackupPlan` / `_GateDecision`), so the resolver is unit-testable alone."""
    command: "str | None"
    name: "str | None"          # None ⇒ no --target given; the default `command:` is what runs
    production: "bool | None"   # None ⇒ no --target given (the default command's stance is undeclared)
    error: "str | None"


def _resolve_deploy_target(section: dict, requested: "str | None") -> _DeployTarget:
    """PURE — resolve `--target <name>` against the carrier's `<kind>.targets` block.

    FAIL-CLOSED IN ONE DIRECTION THAT MATTERS MOST: an unknown name NEVER falls back to the default
    `command:`. On a project whose default command is production, a silent fallback would turn a
    typo into a PRODUCTION deploy — so every unresolvable name is an error the caller refuses on,
    before any side effect and with no `deploy_completed` emitted.

    `production:` is a MANDATORY, POSITIVELY-DECLARED boolean on every target entry. It is never
    inferred from the target's NAME ("sandbox" is a string, not a proof) and never defaulted from
    absence: SPEC-0097 §8 requires classification to be EXPLICIT, never an auto-detector, and
    `lessons/carving-an-exception-into-a-fail-closed-gate.md` records what happens when an exception
    to a fail-closed gate can be opened by a broken declaration rather than a positive one.

    THE READER OWNS THE MISSING-VALUE JUDGEMENT (lessons/fail-closed-belongs-to-the-reader-not-the-
    parser.md): an absent `--target` and an absent `production:` inside a named target mean opposite
    things — "use the default command, read nothing" versus "malformed, refuse" — so this function
    reports what it read and `cmd_deploy` decides, rather than answering both centrally here.
    """
    if requested is None:
        # The DEFAULT path, untouched: `targets:` is not even consulted, so a carrier that declares
        # none (or declares a malformed one) behaves exactly as it did before this rule existed.
        return _DeployTarget(section.get("command"), None, None, None)

    targets = section.get("targets")
    if not isinstance(targets, dict) or not targets:
        return _DeployTarget(None, requested, None,
                             f"`--target {requested}` was given but the carrier declares no "
                             f"`targets:` block — declare `targets: {{{requested}: {{command: <cmd>, "
                             f"production: true|false}}}}` in {CONSUMER_OPS_CONTRACT} (SPEC-0094 §1)")
    if requested not in targets:
        known = ", ".join(sorted(str(k) for k in targets))
        return _DeployTarget(None, requested, None,
                             f"`--target {requested}` names no declared target — the carrier declares: "
                             f"{known}. REFUSING rather than falling back to the default `command:`: a "
                             f"fallback here would deploy the DEFAULT target (in practice PRODUCTION) "
                             f"on a typo")

    entry = targets[requested]
    if not isinstance(entry, dict):
        return _DeployTarget(None, requested, None,
                             f"`targets.{requested}` is not a mapping (expected `{{command: <cmd>, "
                             f"production: true|false}}`)")

    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        return _DeployTarget(None, requested, None,
                             f"`targets.{requested}.command` is absent or blank — there is nothing "
                             f"to run for this target")

    production = entry.get("production")
    if not isinstance(production, bool):
        # NOT a nit: this value decides whether the SPEC-0097 §5 class gate applies, so an absent or
        # fuzzy one ("no", "0", null) would let a malformed declaration choose the weaker path.
        return _DeployTarget(None, requested, None,
                             f"`targets.{requested}.production` is absent or not a boolean (got "
                             f"{production!r}) — every target must DECLARE its production stance "
                             f"explicitly (SPEC-0097 §8: classification is explicit, never inferred). "
                             f"A target whose stance is missing is not read as non-production")

    return _DeployTarget(command.strip(), requested, production, None)


def cmd_deploy(args: argparse.Namespace, *, REPO_ROOT, _append_event, _main_worktree,
               _git_resolve_sha, _die, _run_git_cap, _worktree_dirty_paths,
               _is_ignorable_dirt, _iter_events, _journal_dirt_is_valid_append, _dedup_events) -> None:
    """Run the project-declared deploy/rollback command (the executable gate) + emit deploy_completed
    on exit-0 (SPEC-0094 §1). `--rollback` selects the `rollback:` section + records `kind: rollback`.

    A `--rollback <rev>` carries a TARGET revision (T-9407): the project rollback command needs a target
    to roll back TO (e.g. `scripts/rollback.sh` with `REV=${1:?usage}`), and the rolled-to revision —
    not HEAD — is the one left live, so it is what `deploy_completed` must record. The target is resolved
    to a canonical sha (validating it exists BEFORE anything runs), passed to the rollback command as a
    positional arg, AND recorded as the event `revision`. A `--rollback` with no `<rev>` is refused with
    a usage error and emits NO event (the broken argless run the carrier's `REV=${1:?usage}` would reject).
    A plain deploy ships HEAD and takes no `<rev>` (supplying one is an error — it is rollback-only).

    The project command's own stdout/stderr is INHERITED (not captured): its smoke/health output IS the
    gate's verdict, the owner/AI must see it live. A non-zero exit is propagated as the verb's exit code
    with NO event emitted (the broken revision is never recorded live)."""
    # --print-guard: emit the canonical guard snippet a consumer embeds in its deploy.sh (SPEC-0094 §1,
    # X-0160) + exit. A pure delivery surface — needs no ops carrier / -C context / git, so it is handled
    # FIRST, before any of the deploy machinery below.
    # `--rollback` selects the ROLLBACK FLAVOUR here (T-10736, X-0597): a consumer's rollback script
    # embeds this same guard, and its refusal is an EMERGENCY-path recovery instruction — it must name
    # the rollback verb form, never the forward one. No `<rev>` is needed (nothing is run), so this
    # stays above the rollback target-required refusal below, unchanged.
    if getattr(args, "print_guard", False):
        sys.stdout.write(DEPLOY_ROLLBACK_GUARD_SNIPPET if getattr(args, "rollback", False)
                         else DEPLOY_GUARD_SNIPPET)
        return

    kind = "rollback" if getattr(args, "rollback", False) else "deploy"
    rev = getattr(args, "rev", None)
    if kind == "deploy" and rev:
        _die(f"deploy: a target revision (`{rev}`) is only accepted with --rollback — a plain deploy "
             f"ships HEAD. Did you mean `deploy --rollback {rev}`?")

    # SPEC-0155 rule 7 — the security-gate override flag PAIR, validated BEFORE anything runs: a
    # malformed pair must refuse up front, not after the producer has already run (and never by silently
    # degrading to "no override"). A VALID override is merely CARRIED here — it grants nothing yet: it is
    # admitted only against a gate verdict that is provably the severity-blocking class AND fully named
    # (`_apply_security_gate_override`). An override on a deploy the gate would have PASSED changes
    # nothing at all.
    security_override, override_error = _security_override_precondition(
        getattr(args, "security_override_advisory", None),
        getattr(args, "security_override_reason", None))
    if override_error:
        print(f"deploy: REFUSED — {override_error}. No deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)
    if security_override is not None and kind == "rollback":
        print(f"deploy: REFUSED — a security-gate override is meaningless on a --rollback: a rollback "
              f"redeploys a PRIOR, already-gated image and never runs the pre-deploy security gate "
              f"(SPEC-0155 rule 1). Drop the override flags. No deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)
    # T-11932 — `--target` is DEPLOY-ONLY, refused up front (before any carrier read or side effect).
    # A named non-production ROLLBACK needs its OWN contract (a `rollback.targets` block + the question
    # of what "roll back a sandbox" even means), which this card deliberately fenced out rather than
    # absorbing; the sibling is FILED. Refusing loudly here is the honest boundary — silently deploying
    # a rollback to the DEFAULT target while the operator named a sandbox is the failure to avoid.
    deploy_target_name = getattr(args, "deploy_target", None)
    if deploy_target_name is not None and kind == "rollback":
        print(f"deploy: REFUSED — `--target {deploy_target_name}` is not accepted with --rollback: the "
              f"named-target axis is declared under `deploy.targets` and covers FORWARD deploys only "
              f"(SPEC-0094 §1). A rollback runs the carrier's single `rollback:` command. No "
              f"deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)

    if kind == "rollback" and not rev:
        # AC3 — a rollback needs a target to roll back TO (the carrier's `REV=${1:?usage}` contract).
        # Refuse BEFORE any side-effect so NO deploy_completed is emitted (SPEC-0094 §1).
        _die("deploy --rollback: a target revision is REQUIRED — `deploy --rollback <rev>` (the "
             "revision to roll back TO). Refusing an argless rollback (no deploy_completed emitted).")

    ops_path = REPO_ROOT / CONSUMER_OPS_CONTRACT
    if not ops_path.exists():
        _die(f"deploy: {CONSUMER_OPS_CONTRACT} not found at {REPO_ROOT} — the ops-contract carrier "
             f"(SPEC-0093) must declare a `{kind}:` command; run `bin/yitc-v2 init` to seed it.")
    try:
        ops = state.load_ops(ops_path)
    except yaml.YAMLError as e:  # noqa: BLE001 — fail-closed on an unparseable carrier
        _die(f"deploy: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); fix the carrier and retry.")
    if not isinstance(ops, dict):
        _die(f"deploy: {CONSUMER_OPS_CONTRACT} is not a mapping — the ops-contract carrier (SPEC-0093) "
             f"must declare-or-waive its sections; re-run `bin/yitc-v2 init` to re-seed it.")

    section = ops.get(kind)
    if not isinstance(section, dict):
        _die(f"deploy: {CONSUMER_OPS_CONTRACT} has no `{kind}:` section — declare `{kind}: {{ command: "
             f"<cmd> }}` in the carrier (SPEC-0093) before running `deploy`.")

    # HOST-config surface (SPEC-0093 rule 14) — read the project's declared `deploy.host_config` block as
    # PROJECT ops config and surface it INFORMATIONALLY (a non-behavioral read: it never gates/alters this
    # deploy — the apply ACTION that consumes these values is SPEC-0111's seam). host_config rides the
    # `deploy:` section regardless of kind (deploy/rollback).
    host_config = _read_host_config(ops.get("deploy"))
    if host_config:
        _vhosts = ", ".join(str(v) for v in host_config.get("vhost_files") or [])
        print(f"deploy: project declares a HOST-config surface (SPEC-0093 rule 14) — owned vhost(s): "
              f"{_vhosts}; host live_base_url: {host_config.get('live_base_url')} (apply via the "
              f"host-config seam, SPEC-0111 — NOT performed by this verb).")
    command = section.get("command")
    if not command or not str(command).strip():
        # A waived section (declare-or-waive) has no command — there is nothing to run.
        reason = ""
        waiver = section.get("waiver")
        if isinstance(waiver, dict) and waiver.get("reason"):
            reason = f" (waived: {str(waiver['reason']).strip()})"
        _die(f"deploy: `{kind}:` declares no `command:`{reason} — nothing to run. Declare a "
             f"`command:` in {CONSUMER_OPS_CONTRACT} (SPEC-0093) to enable `{kind}`.")

    # T-11932 / SPEC-0094 §1 — RESOLVE the named target NOW, before ANY side effect (no gate, no dump,
    # no probe, no command has run). With no `--target` this is the identity: `command` is unchanged and
    # the `targets:` block is never read, so a consumer declaring none deploys byte-identically to
    # before this rule. Every failure REFUSES — an unknown name never degrades to the default command.
    dtarget = _resolve_deploy_target(section, deploy_target_name)
    if dtarget.error:
        print(f"deploy: REFUSED — {dtarget.error}. The deploy did NOT run; no deploy_completed "
              f"emitted.", file=sys.stderr)
        sys.exit(3)
    command = dtarget.command
    # A NON-PRODUCTION target may not ALSO assert a production deploy class. The SPEC-0097 §5 per-class
    # evidence gate measures a PRODUCTION worst case (§1: reversibility within the project's RTO/RPO), so
    # accepting `--class` here would stamp a class onto a record nothing measured — the card's own
    # «worse than no record». Refusing the combination is what makes §12's answer EXPLICIT rather than
    # inherited: there is no way to assert a production class for a non-production target.
    if dtarget.production is False and getattr(args, "deploy_class", None):
        print(f"deploy: REFUSED — `--class {args.deploy_class}` is not accepted with the "
              f"non-production target `{dtarget.name}` (`targets.{dtarget.name}.production: false`). "
              f"The A/S/C1/C2 classes measure a PRODUCTION worst case (SPEC-0097 §1/§5); a "
              f"non-production deploy carries NO class, and its record says so "
              f"(`deploy_completed.target.deploy_class: null`, SPEC-0097 §12). Drop --class. No "
              f"deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)

    # A deploy ships HEAD; a rollback ships the operator-named TARGET <rev> (T-9407). Resolve to a
    # canonical sha — this BOTH validates the ref exists (fail-closed BEFORE running anything, so an
    # unknown rollback target emits no event) AND is the value left live, hence what deploy_completed
    # records (SPEC-0094 §1: revision = "git-sha left live + verified"; for a rollback that is the
    # rolled-to target, NOT HEAD).
    target_ref = rev if kind == "rollback" else "HEAD"
    revision = _git_resolve_sha(target_ref)
    if not revision:
        if kind == "rollback":
            _die(f"deploy --rollback: cannot resolve revision `{rev}` at {REPO_ROOT} — it is not a "
                 f"known commit/ref. Refusing (no deploy_completed emitted).")
        _die(f"deploy: cannot resolve HEAD revision at {REPO_ROOT} — is it a git repository with a "
             f"commit?")
    project = (_main_worktree(REPO_ROOT) or REPO_ROOT).name

    # EXPORT the governed-deploy RUN-MARKER (SPEC-0094 §1, X-0160): a consumer's hand-runnable deploy.sh
    # embeds DEPLOY_GUARD_SNIPPET, which refuses a raw hand-run unless this marker is present — so ONLY a
    # verb-invoked deploy (which ran the class-gate + will emit deploy_completed) passes the guard. Value =
    # the resolved revision (distinctive + useful; the guard only checks presence). Set for BOTH deploy AND
    # rollback so a guarded script is runnable as either the deploy: or rollback: command.
    # BOUND HERE, above the C1 backup below, because that backup runs a carrier command with this same env
    # (one env, two subprocesses). `revision` is already resolved; nothing else moved.
    deploy_env = {**os.environ, DEPLOY_RUN_MARKER_ENV: revision}

    # SPEC-0149 — the proof-obligation window this deploy will STAMP onto `deploy_completed`. Resolved
    # below (deploy-only); a rollback owes no forward proof, so it stays window-less here.
    recheck_seconds, recheck_raw = None, None

    # SPEC-0097 §2a (T-10582) — set ONLY by the Class-S branch below, and only on the DOWN-surface
    # carve-out. Bound here so every other path (rollback, non-S class, pre-policy carrier) carries the
    # SAME «nothing owed» value without a getattr dance.
    down_surface = None

    # T-11932 — the SPEC-0097 class decision, bound at function scope so every path carries a value.
    # It stays None on a rollback (never gated, §8) and on a non-production target (no class applies,
    # §12); the `deploy_completed` payload reads it directly rather than re-deriving the distinction.
    gate = None

    # SPEC-0097 §11 (T-10510, X-0374) — RESOLVE the convergence declaration NOW, before any side effect.
    # The verification itself necessarily runs AFTER the command (it asks what the services actually ended
    # up running). Read off the `deploy:` section for BOTH kinds — like `host_config`, the services a
    # project runs are a property of the project, not of this invocation, and the `rollback:` section
    # carries no services of its own.
    #
    # BOTH KINDS ARE VERIFIED, but the MALFORMED-block refusal is DEPLOY-ONLY, and that asymmetry is
    # load-bearing (audit-post finding 1). A rollback is the always-available reversal (SPEC-0097 §2 — "you
    # must always be able to roll back"); a broken convergence DECLARATION must never prevent a reversal
    # from running. So a malformed block pre-exits a DEPLOY here (nothing live yet), but for a rollback it
    # is carried PAST the command and turned into an applied-but-unverified refusal below — the reversal
    # runs, and we still never record a false green. This is why convergence is not "a second gate on
    # rollback": for a deploy it can gate the run (the deploy is gated anyway); for a rollback it only ever
    # gates whether the verb RECORDS the revision as live.
    #
    # T-11996 / X-1234 — WHICH declaration is read is resolved from the TARGET first. Before this, the
    # plan was built from the top-level block regardless of `--target`, so a sandbox deploy was
    # convergence-checked against the PRODUCTION containers. `_convergence_section_for_target` SELECTS the
    # governing declaration (target's own > top-level for production > an explicit SKIP naming a
    # non-production target that declares none); `_convergence_precondition` remains the sole PARSER, so
    # there is one schema and one set of SKIP / ERROR / USABLE outcomes. With no `--target` the selector is
    # the identity and this seam is byte-identical to before. Exit codes and the report-only posture are
    # untouched — only the declaration that is read moves.
    _convergence_section, _convergence_skip = _convergence_section_for_target(ops.get("deploy"), dtarget)
    if _convergence_skip:
        convergence = _ConvergencePlan(None, None, {}, _convergence_skip, None)
    else:
        convergence = _convergence_precondition(_convergence_section)
    if convergence.error and kind == "deploy":
        print(f"deploy: REFUSED — the declared convergence check is unreadable: {convergence.error} "
              f"(SPEC-0097 §11). A corrupt check declaration must refuse, never silently degrade to "
              f"«no convergence was wanted» — that degradation is how a service escapes verification "
              f"unnoticed. The deploy did NOT run; no deploy_completed emitted.", file=sys.stderr)
        sys.exit(3)

    # DEPLOY-AUTONOMY GATE (SPEC-0097 §8 — a GATE on this explicitly-invoked verb, never an auto-trigger).
    # Applies to a forward DEPLOY only: a rollback is the always-available reversal (SPEC-0097 §2 —
    # "rollback = redeploy the prior image"), so it is NEVER gated (you must always be able to roll back).
    # Reads the carrier `deploy.policy` (T-9413 subfield), classifies the deploy A/S/C1/C2 from --class,
    # and selects the per-class evidence requirement. An ESCALATE verdict refuses BEFORE running anything,
    # so no deploy_completed is emitted (the escalated deploy is not recorded live, SPEC-0097 §5).
    if kind == "deploy":
        # BUILD-SOURCE DISCIPLINE (SPEC-0094 §6) — a forward deploy builds the WORKING TREE, so it MUST be
        # the landed+audited `main` line. Assert HEAD==main AND no real source dirt BEFORE anything runs;
        # an unsafe source REFUSES fail-closed with NO deploy_completed (the broken source is not recorded
        # live — same shape as the autonomy-gate ESCALATE). A rollback redeploys a prior image and is NEVER
        # gated (always-available reversal), so this is deploy-only — placed FIRST in the deploy block.
        #
        # T-12066 / X-1261 — the MAIN-LINE half is scoped BY TARGET, reading the SAME positively
        # declared discriminator the class-conditional block below reads (`_resolve_deploy_target`
        # makes `production:` mandatory, so an ABSENT value can never open this path; `production is
        # None` is the no-`--target` default and keeps the assertion). For a target declared
        # `production: false` the landed-main-line assertion did not merely over-refuse — it
        # CONTRADICTED SPEC-0049 rule 3, which requires the sandbox be deployed through this very
        # verb: a non-production target exists to exercise code that is not yet on `main`. This is a
        # per-target SCOPE, not an override flag (§6 still has none) and not a relaxation of anything
        # else: the RUNTIME-SOURCE dirt half, the security-audit gate and the convergence check all
        # keep running on such a target, unchanged. The skip is STATED, never silent.
        branch = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], REPO_ROOT).stdout.strip()
        main_line_required = dtarget.production is not False
        bad_source = _build_source_violation(
            branch, _worktree_dirty_paths(), _is_ignorable_dirt=_is_ignorable_dirt,
            require_main_line=main_line_required)
        if not main_line_required:
            print(f"deploy: target `{dtarget.name}` is declared NON-PRODUCTION "
                  f"(`targets.{dtarget.name}.production: false`) — the SPEC-0094 §6 landed-`main`-line "
                  f"assertion does NOT apply and is SKIPPED; this deploy builds "
                  f"{('branch ' + branch) if branch else 'a detached HEAD'}. The un-landed-RUNTIME-SOURCE "
                  f"half of §6 still refuses, as do the security-audit and convergence gates. The record "
                  f"carries `build_source` + the target's declared stance.")
        if bad_source:
            print(f"deploy: REFUSED — unsafe build source (SPEC-0094 §6): {bad_source}. "
                  f"No deploy_completed emitted.", file=sys.stderr)
            sys.exit(4)

        # T-11932 / SPEC-0097 §12 — the CLASS-CONDITIONAL block runs for a PRODUCTION deploy only.
        # SPEC-0097 §1 scopes the whole autonomy policy to a worst case "NOT acceptably reversible
        # within the project's stated RTO/RPO", and each leg below is defined by that production blast
        # radius: the A/S/C1/C2 gate, the Class-C1 pg_dump, the Class-S security live-probe, and the
        # §5 proof-obligation window. A non-production target has no such worst case, so these do not
        # merely PASS there — they do not DESCRIBE that deploy, and running them would stamp a
        # production class onto a record nothing measured (the X-1201 «worse than no record»).
        #
        # THIS REMOVES NO EXISTING GATE. The discriminator is a positively-declared
        # `targets.<name>.production: false` (never inferred, never opened by an absent value —
        # `_resolve_deploy_target`), which no deploy could carry before this change; `production is
        # None` is the no-`--target` default and takes the production path unchanged. Every
        # CLASS-INDEPENDENT gate stays OUTSIDE this scope and keeps running on a non-production
        # target exactly as on a production one: the SPEC-0155 rule-1 security-audit producer/gate
        # below, and the SPEC-0097 §11 convergence verification after the command. The skip is
        # STATED, never silent.
        #
        # AMENDED (T-12066): this comment previously named the SPEC-0094 §6 build-source discipline
        # above as applying "unchanged" here. That is no longer true of its landed-`main`-line half,
        # which is now scoped by the SAME discriminator (X-1261) — see the block above. §6's
        # un-landed-RUNTIME-SOURCE half IS still class-independent and still refuses here.
        if dtarget.production is False:
            print(f"deploy: target `{dtarget.name}` is declared NON-PRODUCTION "
                  f"(`targets.{dtarget.name}.production: false`) — the SPEC-0097 A/S/C1/C2 class gate "
                  f"and its per-class evidence (C1 pg_dump / Class-S live-probe / proof-obligation "
                  f"window) do not apply and are SKIPPED (SPEC-0097 §12). The build-source, "
                  f"security-audit and convergence gates still apply, unchanged.")
        else:
            gate = _classify_deploy_gate(section.get("policy"),
                                         getattr(args, "deploy_class", None),
                                         bool(getattr(args, "owner_approved", False)))
            if not gate.proceed:
                print(f"deploy: GATE refused (class={gate.deploy_class}) — {gate.message}", file=sys.stderr)
                # Surface the SELECTED concrete per-project risk to the owner (SPEC-0097 §2 "escalate with the
                # CONCRETE risk, not a bare yes/no" / §5 "an owner escalation WITH the RTO/RPO risk"). The gate
                # SELECTS the carrier's `classes.<X>` block into gate.evidence but the message above is only the
                # generic reason — so render the concrete declared risk (its rto/rpo/note/restore_budget and any
                # other declared keys) here, when present, so the owner sees the actual RTO/RPO risk to decide on.
                if isinstance(gate.evidence, dict) and gate.evidence:
                    risk = "; ".join(f"{k}={v}" for k, v in gate.evidence.items())
                    print(f"deploy:   concrete RTO/RPO risk (deploy.policy.classes.{gate.deploy_class}): {risk}",
                          file=sys.stderr)
                sys.exit(3)
            print(f"deploy: gate {gate.mode} (class={gate.deploy_class}) — {gate.message}")

            # SPEC-0149 §1 — RESOLVE the proof-obligation window at the ONE boundary, BEFORE any side
            # effect (no dump, no probe, no deploy command has run yet). A DECLARED-BUT-MALFORMED window
            # REFUSES: a corrupt proof declaration must never degrade to «no proof was wanted» — the
            # silent-disable class SPEC-0148 §3 closed for `expected_database`. An ABSENT window is not a
            # malformation: it simply owes nothing, and the deploy proceeds exactly as before this spec
            # (the reader owns that distinction, not the parser —
            # `lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`).
            recheck_seconds, recheck_raw, recheck_error = _recheck_window(section.get("policy"),
                                                                          gate.evidence)
            if recheck_error:
                print(f"deploy: REFUSED — the declared post-deploy proof obligation is unreadable: "
                      f"{recheck_error} (SPEC-0149 §1). A corrupt obligation declaration must refuse, "
                      f"never silently disable the delayed re-check it asked for. The deploy did NOT "
                      f"run; no deploy_completed emitted.", file=sys.stderr)
                sys.exit(3)

            # SOFT, NON-BLOCKING migration reminder (SPEC-0097 §2 — T-9772, X-0145). A Class-C1 deploy is by
            # definition a backward-compatible (expand/contract) MIGRATION deploy; the kernel deliberately
            # delegates the deploy COMMAND to the project (it does not run migrations itself), so a project's
            # deploy command can silently omit the migrate step and ship schema-dependent code ahead of the
            # prod schema (the boomrocket near-miss: prod ~10 migrations behind code). This WARN reminds the
            # operator to confirm the command APPLIES the migrations. It is ADVISORY ONLY — it does NOT
            # sys.exit, does NOT alter gate.proceed, and does NOT change the exit code (owner-approved SOFT
            # warn, NO hard gate). Rollback is never classified (never reaches this deploy-only block).
            if gate.deploy_class == "C1":
                print("deploy: WARN — Class C1 (expand/contract migration): confirm this deploy command "
                      "APPLIES the DB migrations (e.g. `alembic upgrade head` / `python manage.py migrate`) — "
                      "shipping schema-dependent code without applying its migrations will break prod "
                      "(X-0145). This MIGRATION reminder is advisory, not a gate — but the declared "
                      "pre-deploy pg_dump backup below IS a gate and must pass before the deploy runs.",
                      file=sys.stderr)

                # EXECUTE the C1 evidence the gate SELECTED, instead of selecting-then-dropping it (X-0261).
                # SPEC-0097 §4/§5 require a PRODUCED dump within budget, not a DECLARED one; the declaration
                # is checked by the gate above (declare-or-waive), the production is checked here. Runs BEFORE
                # the project deploy command — a backup taken after the deploy is worthless. Any failure exits
                # 3 from inside, so the deploy command never runs and no deploy_completed is emitted.
                #
                # Keyed on gate.mode, NOT on the class alone (T-10284) — the same guard the Class-S branch
                # below carries. `gate.evidence` is SELECTED only on the autonomous path; every pre-policy
                # return (absent / waived / empty-`classes:` policy — and born-WAIVED is a fresh consumer's
                # DEFAULT stance) carries evidence=None. Keying on the class alone therefore handed
                # _backup_precondition(None) an absent block and REFUSED `--class C1` on a carrier that never
                # opted into the policy — contrary to SPEC-0097 §8/§9 (a pre-policy / waived carrier IGNORES
                # `--class` and proceeds exactly as before the policy existed; its owner-gating is
                # out-of-band). Absent evidence means two different things by carrier class — "malformed C1
                # block, refuse" when autonomous, "no autonomy stance declared, nothing to back up" when
                # pre-policy — so the READER that knows the mode owns that judgement, not the shared
                # precondition (lessons/fail-closed-belongs-to-the-reader-not-the-parser.md).
                if gate.mode == "autonomous":
                    backup = _backup_precondition(gate.evidence)
                    if backup.error:
                        print(f"deploy: REFUSED — a Class-C1 deploy needs a runnable pre-deploy backup, but "
                              f"{backup.error} (SPEC-0097 §4). Declare it under `deploy.policy.classes.C1`, or "
                              f"route this change as Class C2 and escalate. No deploy_completed emitted.",
                              file=sys.stderr)
                        sys.exit(3)
                    _run_c1_backup(backup, revision=revision, project=project, REPO_ROOT=REPO_ROOT,
                                   deploy_env=deploy_env, _append_event=_append_event)

            # EXECUTE the Class-S evidence the gate SELECTED, instead of selecting-then-dropping it (T-10279).
            # SPEC-0097 §2 grants Class-S autonomy ONLY against a mandatory security live-probe, and routes an
            # un-probeable property to ESCALATE. Until now the gate checked only that classes.S was DECLARED
            # (deploy.py#_classify_deploy_gate) and nothing ever ran it — the same selected-then-dropped shape
            # as the C1 pg_dump (X-0261). Runs BEFORE the project deploy command: every refusal below exits 3
            # from inside, so the command never runs, nothing goes live, and no deploy_completed is emitted.
            #
            # Keyed on gate.mode, NOT on deploy_class alone: only the AUTONOMOUS path is what §2 conditions on
            # the probe. A pre-policy / waived carrier stays owner-gated out-of-band (§9) and must proceed
            # exactly as before, and a per-class waiver already escalated at the gate (proceed=False). (The C1
            # branch above once keyed on the class alone and so refused a pre-policy `--class C1` — the §9
            # divergence this branch deliberately did not reproduce; T-10284 closed it, and both evidence-
            # execution branches now carry the same mode guard.)
            if gate.mode == "autonomous" and gate.deploy_class == "S":
                probe = _security_probe_precondition(gate.evidence)
                if probe.unprobeable:
                    print(f"deploy: REFUSED — Class S, but the declared security property is NOT assertable "
                          f"by a read-only probe: {probe.unprobeable}. SPEC-0097 §2 routes an un-probeable "
                          f"security property to an OWNER ESCALATION, never a silent autonomous deploy (the "
                          f"failure mode is EXPOSURE, which an image rollback does not undo). The deploy did "
                          f"NOT run; no deploy_completed emitted.", file=sys.stderr)
                    sys.exit(3)
                if probe.error:
                    print(f"deploy: REFUSED — a Class-S deploy needs a runnable security probe, but "
                          f"{probe.error} (SPEC-0097 §2). Declare `security_probe` + "
                          f"`security_probe_budget_seconds` under `deploy.policy.classes.S`, or declare "
                          f"`unprobeable: <reason>` to escalate. No deploy_completed emitted.",
                          file=sys.stderr)
                    sys.exit(3)
                # Returns a carve-out ONLY on the §2a DOWN-surface path (T-10582); None ⇒ the probe passed and
                # no post-probe is owed. Every other outcome still exits 3 from inside, so the deploy command
                # below never runs.
                down_surface = _run_class_s_security_probe(
                    probe, revision=revision, project=project, REPO_ROOT=REPO_ROOT, deploy_env=deploy_env,
                    _append_event=_append_event, evidence=gate.evidence, ops=ops, _iter_events=_iter_events)

        # SPEC-0155 rule 1 — the DEPLOY-SEAM SECURITY-PRODUCER RUN + the pre-deploy gate. Runs the
        # project's DECLARED `security.audit.runner` (SPEC-0145 §6) at the seam so the gate judges a
        # report produced FROM the deploy candidate, not whatever vintage the cron last wrote (the
        # T-0134 stale-block class). Class-INDEPENDENT: unlike the C1 backup / Class-S probe above (each
        # conditioned on a deploy CLASS), the security-audit freshness gate applies to EVERY forward
        # deploy. Deploy-only (a rollback redeploys a prior, already-gated image). A project that never
        # declared a producer SKIPS (fail-open — deploys exactly as before this spec). Any failure exits
        # 3 from inside, so the deploy command never runs and no deploy_completed is emitted.
        audit_plan = _security_audit_precondition(ops.get("security"))
        if audit_plan.error:
            print(f"deploy: REFUSED — {audit_plan.error} (SPEC-0155 rule 1). Fix the "
                  f"`security.audit.runner` declaration in {CONSUMER_OPS_CONTRACT}, or waive the block. "
                  f"No deploy_completed emitted.", file=sys.stderr)
            sys.exit(3)
        if audit_plan.skip_reason:
            print(f"deploy: {audit_plan.skip_reason} — skipping the deploy-seam security producer/gate "
                  f"(SPEC-0155 rule 1).")
        else:
            _run_security_audit_seam(audit_plan, revision=revision, project=project, REPO_ROOT=REPO_ROOT,
                                     deploy_env=deploy_env, _append_event=_append_event,
                                     override=security_override,
                                     deploy_class=(gate.deploy_class if gate is not None else None))

    # For a rollback, pass the resolved target sha to the rollback command as a positional arg, so the
    # project script (e.g. `scripts/rollback.sh "$REV"`) knows WHAT to roll back to (AC1). The value is
    # a `[0-9a-f]` sha (resolved above), so appending it to the shell string carries no injection surface.
    run_command = str(command)
    if kind == "rollback":
        run_command = f"{run_command} {revision}"

    # JOURNAL-AWARE ROLLBACK, leg 1 — FOLD (T-10633 / X-0479). A mounted-code reversal is a `git
    # checkout <rev>` (SPEC-0097 §2), which git refuses while events.jsonl is dirty — dirt D-0049
    # SANCTIONS (no-worktree journal appends on main). Fold it into a scoped direct-to-main commit so the
    # reversal is not blocked by the system's own discipline. BEST-EFFORT THROUGHOUT: every skip — and
    # even a FAILED commit — prints a reason and proceeds, because a rollback must ALWAYS be available
    # (SPEC-0097 §2) and this helper exists to remove an obstacle, never to add one.
    journal_snapshot: "list[str]" = []
    ev_path = REPO_ROOT / "events.jsonl"
    if kind == "rollback":
        ev_rel = "events.jsonl"
        ev_dirty = _run_git_cap(["diff", "--quiet", "HEAD", "--", ev_rel], REPO_ROOT).returncode != 0
        branch = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], REPO_ROOT).stdout.strip()
        merge_in_progress = _run_git_cap(
            ["rev-parse", "-q", "--verify", "MERGE_HEAD"], REPO_ROOT).returncode == 0
        plan = _journal_fold_plan(
            kind, branch, ev_dirty,
            # Only ASK the validity question when there is dirt to judge (the predicate shells git).
            _journal_dirt_is_valid_append(ev_rel) if ev_dirty else False,
            merge_in_progress)
        if ev_dirty:
            print(f"deploy: journal-aware rollback — {plan.reason}.")
        if plan.fold:
            _run_git_cap(["add", "--", ev_rel], REPO_ROOT)
            rv = _run_git_cap(["commit", "-q", "-m",
                               "chore: fold journal dirt before rollback checkout (T-10633)"], REPO_ROOT)
            if rv.returncode != 0:
                # NEVER fatal — see above. The reversal proceeds; if the dirt does block the project's
                # checkout, its own non-zero exit reports that honestly (no deploy_completed).
                print(f"deploy: journal fold did not commit ({(rv.stderr or rv.stdout).strip()}) — "
                      f"proceeding with the rollback anyway (a rollback is always available, "
                      f"SPEC-0097 §2).", file=sys.stderr)
            else:
                print(f"deploy: journal folded to main @ "
                      f"{_run_git_cap(['rev-parse', '--short', 'HEAD'], REPO_ROOT).stdout.strip()} — "
                      f"the reversal's checkout is no longer blocked by it.")
        # SNAPSHOT for leg 2, taken AFTER the fold — this is the journal as it stands going INTO the
        # tree switch, and every one of these lines must still be present coming out of it.
        if ev_path.exists():
            # T-11444 / SPEC-0190 rules 3+4 — DELIBERATELY THE LIVE SEGMENT ONLY, declared through
            # `events.live_segment` rather than left implicit. This snapshot exists to be UNION-WRITTEN
            # BACK into `ev_path` below, and that write targets ONE physical file: folding the archive
            # in here would restore archived rows INTO the live segment and undo segmentation — the
            # hazard rule 3 names, and the same reason land's step-3 dedup rewrites per segment. What
            # the rollback checkout replaces is the tracked live file, which is exactly what this pair
            # protects; restoring archive segments across a tree switch is the rotation writer's
            # (A5/T-11448), and it owns the per-segment write this guard must not invent.
            journal_snapshot = list(journal_mod.fold_lines(events_mod.live_segment(ev_path)))

    print(f"deploy: running `{kind}:` command for {project} @ {revision[:12]} — "
          f"the project command IS the smoke/health gate (non-zero ⇒ NO deploy_completed: the kernel "
          f"records nothing live and performs no rollback):")
    print(f"  $ {run_command}")
    # INHERIT stdout/stderr: the project command runs its own smoke/health check inline and its output
    # is the gate's verdict — the owner/AI must see it live (never captured/swallowed). shell=True so a
    # project may declare a pipeline / multi-step command string in the carrier.
    result = subprocess.run(run_command, cwd=str(REPO_ROOT), shell=True, env=deploy_env)

    # JOURNAL-AWARE ROLLBACK, leg 2 — UNION-RESTORE (T-10633 / X-0479). The checkout above replaced
    # events.jsonl with the TARGET revision's older copy, dropping the lines the live journal had
    # (including this session's receipt → `session_ref` UNBACKED, the X-0479 mid-drill refusal). Union
    # the snapshot back in, deduped — `land`'s own discipline (SPEC-0002) at the other tree-switch seam.
    # Runs on EVERY exit path, BEFORE the returncode branch below: a FAILED rollback can have switched
    # the file just as a successful one can, and a lost journal line is not made acceptable by the
    # command having failed. Never touches the exit code.
    if kind == "rollback" and journal_snapshot:
        try:
            current = list(journal_mod.fold_lines(events_mod.live_segment(ev_path)))   # live-only: see the snapshot above
            restored = _journal_union_restore(journal_snapshot, current, _dedup_events=_dedup_events)
            if restored is not None:
                ev_path.write_text("\n".join(restored) + "\n")
                print(f"deploy: journal union-restored across the rollback checkout — "
                      f"{len(restored) - len(current)} line(s) the switch had dropped are back "
                      f"(no journal line lost; T-10633).")
        except OSError as e:  # noqa: BLE001 — journal hygiene must never break a reversal
            print(f"deploy: could not union-restore the journal after the rollback ({e}) — the "
                  f"rollback itself is unaffected; re-check events.jsonl.", file=sys.stderr)

    if result.returncode != 0:
        # The gate FAILED. Withhold the RECORD — no deploy_completed, so the broken revision is never
        # recorded live (SPEC-0094 §1) — and say ONLY that. The kernel does NOT un-serve the revision
        # here: between this branch and the exit below there is no rollback, no checkout and no probe,
        # and a project whose deploy recreates containers BEFORE its gate runs has already served the
        # new code (kupiclub 2026-08-27, X-1149 / T-11744 — an operator read the old wording as «not
        # serving» while /version returned exactly this revision). Nor may we swap that for the
        # opposite assertion: we did not observe the runtime either. So state the record as FACT and
        # the runtime as UNKNOWN, and name the next step — the discipline
        # `_property_broken_refusal` already carries one branch over (only the leg that ESTABLISHED a
        # fact may assert it, T-10582). Propagate the command's exit code.
        print(f"deploy: `{kind}:` command exited {result.returncode} — the deploy-seam gate FAILED.\n"
              f"  RECORD (fact): no deploy_completed was emitted, so the kernel's live-revision "
              f"record is UNCHANGED — it still names the previous revision, and {revision[:12]} has no "
              f"governed provenance.\n"
              f"  RUNTIME (UNKNOWN — not checked): the kernel neither observed what is serving nor "
              f"changed it, and it ran NO rollback. If this project's `{kind}:` command serves the new "
              f"code before it gates (build/migrate/recreate, then smoke), {revision[:12]} may be "
              f"SERVING RIGHT NOW, unrecorded. Do not read this failure as a reversal.\n"
              f"  NEXT: check what is actually live, then either roll back — "
              f"`bin/yitc-v2 -C {project} deploy --rollback <rev>` — or fix and re-run the deploy. "
              f"Either way it must not be left live-but-unrecorded.",
              file=sys.stderr)
        sys.exit(result.returncode)

    # MANDATORY post-deploy security probe — the second half of the §2a DOWN-surface carve-out (T-10582).
    # Runs IMMEDIATELY on the command's exit-0 and BEFORE the convergence verify below, because a
    # convergence failure exits 5 and would otherwise SKIP this probe entirely — leaving a possibly-EXPOSED
    # revision live with no security assertion at all. Security evidence must not be contingent on
    # convergence passing. A failure inside rolls back + escalates + exits 3 (no deploy_completed).
    # `down_surface` is None on every other path, so nothing here fires for an ordinary deploy/rollback.
    post_probe_evidence = None
    if down_surface is not None:
        post_probe_evidence = _run_post_deploy_security_probe(
            down_surface, revision=revision, project=project, REPO_ROOT=REPO_ROOT,
            deploy_env=deploy_env, _append_event=_append_event)

    # Exit-0: the project's own smoke/health gate passed. That is NOT yet «the revision is live» — it is
    # only «the command reported success» (SPEC-0097 §11 / X-0374: aiseller's command exited 0 having
    # skipped a service, which kept running old code). VERIFY CONVERGENCE before recording anything: a
    # non-converged service exits 5 from inside, emitting `deploy_convergence_failed` and NO
    # deploy_completed. A project that declared nothing SKIPS (fail-open — it deploys exactly as before
    # this spec; the init sweep + the SPEC-0156 unproven-check debt are what make that absence visible).
    convergence_payload = None
    if convergence.skip_reason:
        print(f"deploy: {convergence.skip_reason} — skipping the post-deploy convergence check "
              f"(SPEC-0097 §11).")
    elif convergence.error:
        # Only reachable for a ROLLBACK (a deploy pre-exited on this above): the reversal has RUN — the
        # §2 always-available guarantee is honoured — but the convergence declaration is malformed, so
        # there is nothing trustworthy to verify against. We must not record a false green, so this is
        # APPLIED-BUT-UNVERIFIED: emit the failure event and exit 5, exactly like a stale service. A
        # broken declaration never blocks the reversal, and never launders an unverifiable one into a
        # deploy_completed.
        print(f"deploy: rollback APPLIED but its convergence check is unreadable: {convergence.error} "
              f"(SPEC-0097 §11). The reversal RAN (a rollback is always available, §2), but a malformed "
              f"declaration cannot be verified — recording applied-but-unverified. NO deploy_completed; "
              f"fix the `deploy.convergence` block, then re-verify.", file=sys.stderr)
        _append_event("deploy_convergence_failed", None,
                      {"revision": revision, "project": project, "kind": kind, "converged": {},
                       "unverified": {"reason": convergence.error}})
        sys.exit(5)
    else:
        convergence_payload = _verify_convergence(
            convergence, revision=revision, project=project, kind=kind, REPO_ROOT=REPO_ROOT,
            deploy_env=deploy_env, _append_event=_append_event)

    # Convergence verified (or nothing declared): the revision is live. Emit the governed adoption record.
    payload = {"revision": revision, "project": project, "kind": kind}

    # T-12066 / SPEC-0094 §6 — WHAT SOURCE this forward deploy built. Since the landed-main-line
    # assertion is now scoped by target, a record that omits this cannot be read for the one question
    # the scoping raises: did this deploy ship the landed line, or a branch? `"main"` | `"branch"` is
    # the whole added answer — the EXACT code is already pinned by `revision` above, so the branch
    # name would be a second, weaker copy of it. The target's declared stance is NOT duplicated here —
    # it is already carried by `target.production` below (T-11932), and a second copy is exactly the
    # parallel storage CHARTER §P5 forbids.
    #
    # Present on exactly the records where the answer is NOT already implied: a forward deploy that
    # NAMED a target. A rollback is never build-source gated (§6), and a TARGET-LESS deploy always
    # takes the unscoped assertion — it cannot have built anything but `main`, or it would have been
    # refused — so adding the field there would state a constant while moving a record shape that the
    # T-11932 guard deliberately holds byte-identical for a consumer declaring no targets.
    if kind == "deploy" and dtarget.name is not None:
        payload["build_source"] = "main" if branch == "main" else "branch"

    # T-11932 / SPEC-0094 §1 — WHICH TARGET this record is about. Absent entirely when no `--target`
    # was named, so no existing record's shape moves and a consumer declaring no targets is
    # byte-identical to before. Present, it carries the whole answer the journal needs to tell two
    # surfaces apart: the NAME, the declared production stance, and the deploy CLASS — which is
    # `None` on a non-production target and SAYS SO, rather than being omitted (an omitted class is
    # indistinguishable from a forgotten one; a null class states that none was carried, SPEC-0097
    # §12). A payload FIELD on the existing event, never a second success event (CHARTER §P1 F2).
    if dtarget.name is not None:
        payload["target"] = {
            "name": dtarget.name,
            "production": dtarget.production,
            "deploy_class": (gate.deploy_class if kind == "deploy" and gate is not None else None),
        }

    # SPEC-0097 §11 — carry the PROOF, not just the claim: which services were verified, what each
    # reported, and which were declared out of scope. A payload FIELD on the existing event, never a
    # second success event (CHARTER §P1 F2 — a view over the existing entity). Absent ⇒ this project
    # declared no convergence check, which the field's absence says honestly.
    if convergence_payload:
        payload["convergence"] = convergence_payload

    # SPEC-0097 §2a (T-10582) — the DOWN-surface MARKER. This deploy shipped onto a surface that was
    # provably down, so its Class-S evidence has a different SHAPE from an ordinary Class-S deploy: the
    # pre-probe could not be measured (it recorded the outage, not the property), and the property was
    # asserted AFTER the fact by the mandatory post-probe instead. Stamping it makes that difference
    # READABLE on the record rather than leaving a `deploy_completed` that silently looks pre-proven. A
    # payload FIELD on the existing event, never a second success event (CHARTER §P1 F2 — a view over the
    # existing entity), and absent entirely on every ordinary deploy, so no existing record's shape moves.
    if down_surface is not None:
        payload["security_probe"] = {
            "down_surface_pre": True,
            "pre_exit": down_surface.pre_exit,
            "liveness_exit": down_surface.liveness_exit,
            "post_probe": post_probe_evidence,
        }

    # SPEC-0149 §1 — STAMP the resolved obligation window into the event, and ONLY when one resolved.
    # `recheck_by` is an ABSOLUTE UTC deadline computed HERE, at deploy time; the debt fold reads that
    # value and nothing else. Stamping the absolute deadline (not the duration) is what makes the
    # one-window rule structural: the fold is handed no duration to re-resolve and no carrier to
    # default from, so window-less history can never be retro-charged. `recheck_within` rides along as
    # provenance — which declaration produced this deadline — and is never re-interpreted downstream.
    if recheck_seconds:
        deadline = datetime.now(timezone.utc) + timedelta(seconds=recheck_seconds)
        payload["recheck_within"] = recheck_raw
        payload["recheck_by"] = deadline.isoformat(timespec="seconds").replace("+00:00", "Z")

    _append_event("deploy_completed", None, payload)
    print(f"deploy: {kind} OK — {project} @ {revision[:12]} is live; deploy_completed emitted "
          f"(kind={kind}).")
    if recheck_seconds:
        # Say it at the seam: this deploy is APPLIED but not yet PROVEN (SPEC-0097 §5). Until the
        # recheck lands, `bin/yitc-v2 debt` will surface it once the deadline passes.
        print(f"deploy: PROOF OBLIGATION — this deploy owes a delayed re-check within "
              f"{payload['recheck_within']} (by {payload['recheck_by']}). Applied is not proven. "
              f"Discharge it with `bin/yitc-v2 event deploy_recheck_completed --data "
              f"'{{\"project\": \"{project}\", \"revision\": \"{revision}\"}}'` once the re-check "
              f"passes; past the deadline it surfaces in `bin/yitc-v2 debt` (SPEC-0149).")
        # T-11169: name the OTHER exit at the seam that creates the obligation — this print is the only
        # place the operator is told how to discharge one, so a discharge it never mentions is one
        # nobody finds. If the window is later missed outright, the honest close is a recorded miss, NOT
        # a late `deploy_recheck_completed`: that would assert a proof nobody performed.
        print(f"deploy: if that window is later MISSED outright, do NOT record the re-check late — "
              f"discharge it honestly with `bin/yitc-v2 event deploy_recheck_missed --data "
              f"'{{\"project\": \"{project}\", \"revision\": \"{revision}\", \"judgement\": \"why a "
              f"late re-check is or is not meaningful\"}}'`. The judgement is required and the miss "
              f"stays counted (SPEC-0149).")
