"""rebaseline_currency — the SPEC-0077 pinned last-green verify and its §3a AUDIT-CURRENCY /
REBASELINE-ADMISSION arm, extracted byte-identical from `bin/lib/worktree.py` (T-11523, plan
`split-worktree-py-along-its-own-spec-seams-runner-`).

WHAT IS IN HERE, AND WHY THE BOUNDARY IS THE ONE IT IS. The move-set is the TRANSITIVE-EXCLUSIVE
closure rooted at this subject's OWN entry points — the pinned last-green verify (`_run_pinned_verify`
and its verdict cache), the audit-currency check (`_change_is_audited`, the in-land re-audit, the
audited-diff footprint split) and the rebaseline-admission / waive-coverage arm (the step-4a
preflight, the backstop admission, the supersession notice) — where a helper moves iff EVERY top-level
caller of it is already in the move-set. Rooting at the subject rather than at a borrowed
discriminator is the expensive lesson of the runner cut two cards back
(`lessons/library-extraction.md` §"Root the closure at the SUBJECT's own entry point"); requiring
exclusivity is what leaves the land path's shared helpers — `_surface_failing_assertions`, `_shell_dq`,
`_waive_qualifier_key`, `_pinned_entry_core`, `_pinned_baseline_parts`, `_consumer_zero_probe_guard`
and the rest of `cmd_land`'s tree — in the host BY CONSTRUCTION, rather than by an exclusion list
someone has to remember to write.

NOT IN HERE, and each falls out of that same construction rather than by a judgement: `cmd_land` and
`_land_integrate` (the land seam), the batch-landing tree (SPEC-0184) — INCLUDING
`_land_prequeue_currency_refusal`, `_land_rebaselining_branches` and `_land_pinned_supersession_branches`,
which ask rebaseline-shaped questions but are anchored by SPEC-0184 as pre-queue / batch-formation
members and belong to that cut — evidence custody (SPEC-0168), the verify runner (already in
`bin/lib/verify_runner.py`) and the worktree lifecycle (already in `bin/lib/worktree_lifecycle.py`).

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM
from the original source — never `ast.unparse` — and every non-stdlib free name (host stayers, host
globals, AND moved siblings via their host residue) arrives as a keyword-only injected parameter,
computed with `symtable` over each function's scope SUBTREE. No moved signature carries a default that
NAMES a host symbol (mechanically verified over all 24 defaults in the move-set), so the T-11522
default-rebinding case does not arise here and every default is byte-identical. The host keeps a
`functools.wraps` residue under every historical name, so the tests and the `bin/lib` modules that
reach these symbols through `worktree.<sym>` keep resolving and stay out of this diff.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib; it NEVER
back-imports the host.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from pathlib import Path


def _materialize_pinned_engine_bin(W: Path, merged_base: str, *, _run_git_cap):
    """Materialize the LAST-GREEN (committed `main` HEAD = merged_base) engine `bin/` tree (yitc-v2 +
    lib/**) into a fresh temp dir so the pinned verify RUNNER can run in a SUBPROCESS with a CLEAN
    sys.modules — the only correct isolation across the layered bin/lib package (SPEC-0077 §1/§3; an
    in-process load resolves `from lib import worktree` from the LIVE sys.modules cache, running LIVE
    verify logic — the T-9348 defeat). Returns the temp dir (it contains `bin/`), or None when merged_base
    carries NO `bin/yitc-v2` (a `-C` consumer / a test repo): there the engine binary is the already-PINNED,
    consumer-immutable engine (§6b), so the current in-process runner IS the pinned verifier. Raises on a
    genuine git failure — the caller treats that fail-closed (a pinned gate that cannot be established must
    abort the land, never silently skip)."""
    import shutil
    import tarfile
    import tempfile
    # Distinguish TRUE absence (bin/yitc-v2 not tracked at merged_base — a -C consumer / test repo, the
    # legit current-runner fallback) from a genuine git FAILURE (a bad rev, a corrupt repo) — the latter
    # must FAIL-CLOSED (raise → the caller aborts the land), never silently fall through to the candidate's
    # own runner (audit-post F2). `ls-tree` is the clean existence probe: exit 0 + empty output == genuinely
    # absent; a nonzero exit is a real error.
    ls = _run_git_cap(["ls-tree", "--name-only", merged_base, "--", "bin/yitc-v2"], W)
    if ls.returncode != 0:
        raise RuntimeError(
            f"_materialize_pinned_engine_bin: `git ls-tree {merged_base} -- bin/yitc-v2` failed — cannot "
            f"establish the pinned verifier (fail-closed): {ls.stderr or ls.stdout}")
    if not ls.stdout.strip():
        return None   # TRUE absence — consumer / test repo: the current runner IS the pinned engine (§6b).
    root = Path(tempfile.mkdtemp(prefix="yitc-pinned-engine-"))
    # `git archive -o <tar>` writes the bin/ subtree to a FILE (binary stays off the text-captured stdout
    # of _run_git_cap), then extract — materializing merged_base bin/yitc-v2 + bin/lib/** under root/bin.
    # T-9532 (source-leak fix): `root` is OWNED by this function until it is RETURNED to the caller, so ANY
    # failure between mkdtemp and `return root` must rmtree it HERE — otherwise the caller's `pinned_root`
    # stays None (the assignment never completed) and its `finally` cannot clean it, leaking one
    # /tmp/yitc-pinned-engine-* dir per failed materialization (the Jun-23/24 residual leak). The whole body
    # is wrapped so the extractall / unlink / any other raise is covered, not only the archive-returncode branch.
    try:
        tar_path = root / "_engine.tar"
        arch = _run_git_cap(["archive", "-o", str(tar_path), merged_base, "--", "bin"], W)
        if arch.returncode != 0:
            raise RuntimeError(
                f"_materialize_pinned_engine_bin: `git archive {merged_base} -- bin` failed despite bin/yitc-v2 "
                f"present (fail-closed): {arch.stderr or arch.stdout}")
        with tarfile.open(tar_path) as tf:
            tf.extractall(root)
        tar_path.unlink()
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root

def _rebaseline_kind_required_text(*, REBASELINE_KINDS=None, _REBASELINE_KIND_MEANING=None) -> str:
    """T-10898: the ONE text both required-at-grant refusals paste. Single-SoT on purpose — an operator
    must not learn a DIFFERENT vocabulary depending on which of the two sites caught the omission, and
    a refusal that names the flag without naming what each kind MEANS just moves the guess one step."""
    _opts = "\n".join(f"  --rebaseline-kind {k}   — {_REBASELINE_KIND_MEANING[k]}"
                      for k in REBASELINE_KINDS)
    return (f"--rebaseline requires --rebaseline-kind <{'|'.join(REBASELINE_KINDS)}> "
            f"(SPEC-0077 §3a / T-10898). The record must say WHY the pinned check is waived, and the "
            f"kind is NEVER inferred: there is no default, because a defaulted kind would recreate the "
            f"very conflation the declaration removes.\n{_opts}\n"
            f"The kind LABELS the grant, it does not extend it: every eligibility rule is unchanged — "
            f"the A-prime authority, the `>=30-char` --rebaseline-reason, the current-state audit-post, "
            f"and the per-assertion --rebaseline-waive declaration all still apply exactly as before, "
            f"to both kinds alike.")

def _rebaseline_policy_off_text() -> str:
    """T-11374 (SPEC-0186 rule 8 / SPEC-0188 rule 4): the ONE text both policy-off refusals paste.

    The sibling of `_rebaseline_kind_required_text` above and single-SoT for the identical reason —
    an operator must not learn a different vocabulary depending on WHICH of the two placements caught
    the ack. SPEC-0188 rule 4 is the harder obligation the shape satisfies: a check placed at more
    than one point has ONE implementation. The RESOLUTION is shared by both arms calling
    `task_mod._verify_policy_pinned_last_green` (the one carrier reader, SPEC-0186 rule 3), and the
    DIAGNOSIS is shared by both arms calling this — so neither half of the check exists twice."""
    return ("land: --rebaseline REFUSED — this project declares "
            "`verify_policy.pinned_last_green: never` in its yitc-ops.yaml, so the SPEC-0077 "
            "pinned last-green leg did NOT run on this land. A re-baseline waives a superseded "
            "pinned check, and where nothing ran there is nothing to waive (SPEC-0186 rule 8).\n"
            "RECOVERY: land WITHOUT `--rebaseline` — the flag is only for a pinned check your "
            "change deliberately supersedes, and this project pays no such check. If you meant "
            "to re-enable the leg, change the declaration first (that edit takes both audits, "
            "SPEC-0186 rule 5) and land it; the new value applies from the NEXT land (rule 4).")

def _pinned_verify_cache_dir(W: Path, *, _run_git_cap, _PINNED_VERIFY_CACHE_DIRNAME=None) -> "Path | None":
    """The machine-local, per-repo pinned-verdict cache dir under the git COMMON dir (shared by
    every worktree of the repo, never committed). None on any git failure → caller forces a MISS."""
    r = _run_git_cap(["rev-parse", "--git-common-dir"], W)
    if r.returncode != 0:
        return None
    raw = (r.stdout or "").strip()
    if not raw:
        return None
    common = Path(raw)
    if not common.is_absolute():
        common = (W / common).resolve()
    return common / _PINNED_VERIFY_CACHE_DIRNAME

def _pinned_verify_cache_key(W: Path, merged_base: str, *, _run_git_cap, _pinned_baseline_parts=None) -> "str | None":
    """SPEC-0077 / T-10078 — content-addressed identity of a pinned last-green verdict:
      • candidate SUBJECT  = W's `HEAD^{tree}` object id (the whole tree the pinned checks run over);
      • pinned VERIFIER    = the merged_base object ids of the verify CODE surfaces the pinned re-run
                             overlays/runs — `bin`, `tests`, the consumer verify contract (each
                             `<absent>` when the path is missing at merged_base, so presence↔absence
                             still moves the key) — PLUS the live-engine code hash (the §6b fallback's
                             actual verifier);
      • host               = the interpreter version (a green suite is interpreter-specific).
    A verifier-code OR tree change therefore moves the key → MISS → re-run (no stale-green). None on
    any git failure → caller forces a MISS (fail-safe: never a false HIT)."""
    import hashlib
    head = _run_git_cap(["rev-parse", "HEAD^{tree}"], W)
    if head.returncode != 0 or not (head.stdout or "").strip():
        return None
    # T-11517 — the BASELINE half is now its own reader (`_pinned_baseline_parts`), because
    # T-11517 needs that half ALONE to identify the baseline a batch is judged against. The
    # composition here is UNCHANGED: `subject=` first, then exactly the parts that reader returns,
    # in the same order, joined by the same NUL and hashed the same way — so this key's VALUE is
    # byte-identical to the pre-split one and no cached green is invalidated.
    parts = ["subject=" + head.stdout.strip()] + _pinned_baseline_parts(
        W, merged_base, _run_git_cap=_run_git_cap)
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

def _pinned_cache_get(W: Path, key: "str | None", *, _run_git_cap, _pinned_verify_cache_dir=None) -> bool:
    """True iff a GREEN pinned verdict for `key` is already cached (→ skip the re-run). A None key /
    any error → False (a MISS: fail-safe toward RE-RUNNING, never a false skip)."""
    if not key:
        return False
    d = _pinned_verify_cache_dir(W, _run_git_cap=_run_git_cap)
    if d is None:
        return False
    try:
        return (d / key).exists()
    except OSError:
        return False

def _pinned_cache_put(W: Path, key: "str | None", *, _run_git_cap, _pinned_verify_cache_dir=None) -> None:
    """Record a GREEN pinned verdict for `key` (a zero-byte content-addressed marker). Best-effort:
    a cache-write failure NEVER fails the land (the verdict already stands, the cache is an optimization)."""
    if not key:
        return
    d = _pinned_verify_cache_dir(W, _run_git_cap=_run_git_cap)
    if d is None:
        return
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / key).touch()
    except OSError:
        pass

def _pinned_verify_subprocess_env(SUBENV_SCRUB_CARRIERS=None) -> dict:
    """T-10329 — the env handed to the pinned LAST-GREEN re-run SUBPROCESS (`_run_pinned_verify` below),
    scrubbed of the session-ref CARRIERS so an ambient/foreign launcher `YITC_SESSION_REF` (+ the D-0030
    provider carriers) can NEVER leak into the hermetic pinned re-verification. This is the mirror, one
    level UP, of the T-0579/T-0585 `EXPECTED_SESSION_REF_ENV` scrub in `_run_verify_tests`: the pinned
    re-run is a re-verification of LAST-GREEN code with NO legitimate running session, so post-T-10137
    (carrier-precedence-first + fail-closed `_resolve_session_ref`) an inherited launcher carrier would
    resolve a FOREIGN identity in the driver + its allowlisted test children (or fail-close on an unbacked
    carry) → pinned false-RED → LAND ABORT. Scrubbing the carriers lets resolution fall through to the
    pinned worktree's own v2-owned stamp (T-10155) / per-box minted ids as designed. NON-carrier env
    (PATH/HOME/…) is preserved. In normal use (no ambient carrier) the result is byte-identical to
    `os.environ` (no-op) — same discipline as the T-0579/T-9555 scrubs. Carrier set is INJECTED
    (`_SUBENV_SCRUB_CARRIERS`, single-SoT) with a hardcoded mirror fallback only if unset."""
    _carriers = (SUBENV_SCRUB_CARRIERS
                 or ("YITC_SESSION_REF", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"))
    return {k: v for k, v in os.environ.items() if k not in _carriers}

def _pinned_candidate_added_paths(W: Path, merged_base: str, sub: str, *, _run_git_cap) -> list:
    """T-11253 (SPEC-0077 §3, X-0979) — the TRACKED paths under check surface `sub` that exist at the
    candidate HEAD but are ABSENT at `merged_base`: exactly what the pinned overlay must PRUNE for its
    check surface to be last-green.

    THE DEFECT THIS CLOSES. `_run_pinned_verify` overlays each check surface with
    `git checkout <merged_base> -- <sub>`, which RESTORES the base's paths but DELETES none — so a file
    the candidate ADDED under that surface survives into the pinned tree. The pinned leg's check
    surface was therefore (last-green UNION candidate-added), never last-green, with two consequences:
      • the candidate's OWN new checks ran inside the leg that exists to apply only OLD ones; and
      • for any project whose last-green checks include a COMPLETENESS sweep of its test dir, the
        overlay manufactured an inconsistent pair — the new suite FILE present, the last-green script
        that would register it restored without it — so the base sweep correctly reported a
        declared-but-executed-by-nothing suite and the land ABORTED. Measured on kupiclub (X-0979):
        `tests/test_declared_vs_executed.py`, registered by `scripts/verify-static.sh`, RED on
        task/T-0348 and task/T-0331 with "<X>.py is inside a declared verify subject but NO layer
        command names it". Every card that registers a new suite paid at least one land abort.

    DIRECTIONAL, exactly like `_is_candidate_added_bin_module`: a path present at merged_base and
    absent at HEAD is NOT returned — the checkout restores it and the pinned leg must keep running it,
    so a deletion-weakening can never be pruned away. Only the ADDED direction is returned, so this can
    only ever REMOVE candidate-authored checks, never last-green ones.

    Pure git, no filesystem: the caller owns the unlinking. Raises `RuntimeError` on a git failure so
    the caller can fail CLOSED (SPEC-0077 §3 — a setup failure is a pinned failure, never a silent skip)."""
    def _ls(ref: str) -> set:
        r = _run_git_cap(["ls-tree", "-r", "--name-only", "-z", ref, "--", sub], W)
        if r.returncode != 0:
            raise RuntimeError(f"git ls-tree {ref} -- {sub}: {r.stderr or r.stdout}")
        return {n for n in (r.stdout or "").split("\0") if n}

    return sorted(_ls("HEAD") - _ls(merged_base))

def _pinned_env_dockerignore_fence(pinned_wt: Path, rel: str, *, _run_git_cap) -> None:
    """T-11205 (X-0954 / X-0949) — keep a path `_pinned_env_prime` just SYMLINKED out of every docker
    BUILD CONTEXT that could receive it, by writing the exclusion into the pinned tree's own ignore
    files. Never raises: the fence is best-effort belt on top of the link, never a new failure mode.

    THE FAILURE THIS ENDS. A symlink is a FILE to docker's `COPY`. kupiclub's Dockerfile stage 1
    creates `/spa/node_modules` as a real DIRECTORY (`npm ci`) before `COPY frontend/ ./`, so the
    context transfer is asked to replace a directory with a file and BuildKit refuses the whole build:
    "cannot replace to directory .../cachemounts/buildkit*/spa/node_modules with file". The pinned leg
    then cannot build AT ALL — five aborts on a fully green T-0318 (X-0954) and seven more blocking
    EVERY land in that repo for ~2h (X-0949). WHAT MAKES IT INTERMITTENT IS NOT ESTABLISHED — and
    resist filling that gap, because the plausible story here is wrong. Concurrency is neither
    necessary nor sufficient: nine of kupiclub's 13 recorded faults ran at land-concurrency 1 (mean
    1.31 against a 1.44 window base rate), the failure reproduces verbatim on a single build with
    nothing else on the host, and three concurrent builds pass clean once the context is fenced. The
    `cachemounts/buildkit<N>` path in the message reads like a shared cache but is an EPHEMERAL
    per-operation mount: the 13 lands quote 24 distinct ids with none shared between any two, whereas
    three genuinely concurrent identical builds all quote ONE. So a cache-contention reading is
    refuted, not merely unproven — and no substitute cause is offered here, because the recorded data
    does not carry one. Evidence: kupiclub/events.jsonl#ts=2026-08-21T11:23:34Z and
    kupiclub/docs/t0462-buildkit-cause-and-demonstration.md.

    WHY NOT "SKIP PRIMING WHEN THE LAYER IS A DOCKER BUILD" (the filed hypothesis — REFUTED at this
    card's Analysis, and the reason this function exists at all). That condition is not decidable from
    the declaration: kupiclub's layers are `bash scripts/verify-{static,frontend,stack}.sh` and the
    build is a `docker compose build` INSIDE verify-stack.sh. A command-inspection gate would have
    skipped nothing on the very repo that filed both reports — a silent no-op — and the same holds for
    any script-, make- or npm-script-wrapped build. So the engine stops PREDICTING the build and
    instead states the fact that has to hold whoever runs it: this link never travels in a context.

    WHICH FILES, AND WHY THAT SET IS COMPLETE. A `.dockerignore` pattern is always CONTEXT-relative,
    and `_PINNED_ENV_DEP_MAX_DEPTH` is 2, so a primed link can only sit inside a context rooted at the
    pinned ROOT or at its own PARENT — those two are the complete set, and each gets the anchoring it
    needs (see the ANCHORING note in the body: the anchorings are NOT written interchangeably, because
    a bare basename in a root-context file could alias a directory priming never created). The
    governing file itself is
    `<context>/.dockerignore` — UNLESS a companion `<dockerfile-path>.dockerignore` exists, which
    REPLACES it outright rather than adding to it (measured: a root `.dockerignore` naming the path
    builds clean, and re-fails verbatim the moment an EMPTY `Dockerfile.dockerignore` appears beside
    it; likewise for `docker build -f docker/Dockerfile .` with a `docker/Dockerfile.dockerignore`).
    So every TRACKED `*.dockerignore` companion anywhere in the tree is fenced too. Enumerated with
    `git ls-files`, not a filesystem walk: it is one call, and it cannot descend into the very symlink
    being fenced. Tracked-only is exhaustive here — the pinned tree is a tracked-only checkout plus the
    links this priming just made.

    SCOPE. Writes ONLY inside the THROWAWAY pinned worktree, and names ONLY paths this priming itself
    created. The consumer's repo is never touched (D-0019), so a consumer needs to add nothing."""
    parent = Path(rel).parent.as_posix()
    base = Path(rel).name
    at_root = parent in (".", "")
    # WHICH ANCHORING GOES WHERE, and why it is not simply "both everywhere" (audit-post finding 1).
    # A pattern is CONTEXT-relative, so the same link needs `frontend/node_modules` under a ROOT
    # context and a bare `node_modules` under a `frontend/` context. But a bare basename written into
    # a file that turns out to govern the ROOT context would match a ROOT-level directory of that name
    # — and if the project TRACKS one and ships it in the image, the fence would exclude content the
    # build needs: a NEW pinned-only RED, i.e. exactly the failure class this card exists to end. So
    # the basename form is confined to the files that can only plausibly be read with the primed
    # path's own parent as context, and is dropped outright whenever a root-level entry of that name
    # exists to alias with. Never a blanket `**/node_modules`, for the same reason.
    # `<parent>/.dockerignore` is UNAMBIGUOUS and needs no guard at all: docker reads a
    # `.dockerignore` from the CONTEXT ROOT, so that file is read ONLY when the context IS `<parent>`,
    # where the bare basename denotes exactly the primed link and nothing else. A COMPANION living in
    # `<parent>/` is the only ambiguous case — it may equally be used with `-f <parent>/Dockerfile .`,
    # i.e. a ROOT context — so there the basename is withheld only when it could actually alias
    # something the build needs: a root-level entry of that name that the project TRACKS (an untracked
    # one is either a primed link, already fenced by its own rel path, or ignored junk no COPY wants).
    def _tracked_root_alias() -> bool:
        try:
            return _run_git_cap(["ls-files", "--error-unmatch", "-z", "--", base],
                                pinned_wt).returncode == 0
        except Exception:
            return True                        # unknown → withhold (fail-safe: the pre-change state)
    ambiguous_ok = (not at_root) and not _tracked_root_alias()
    root_targets = [pinned_wt / ".dockerignore"]
    parent_targets = [] if at_root else [pinned_wt / parent / ".dockerignore"]
    companion_parent_targets: list = []
    try:
        ls = _run_git_cap(["ls-files", "-z", "--", "*.dockerignore"], pinned_wt)
        if ls.returncode == 0:
            for name in (ls.stdout or "").split("\0"):
                name = name.strip()
                if not name:
                    continue
                # A companion `<Dockerfile>.dockerignore` REPLACES the context file outright, so it
                # has to be fenced wherever it lives. One INSIDE the primed path's parent is the only
                # one that can plausibly be read with that parent as context.
                if not at_root and Path(name).parent.as_posix() == parent:
                    companion_parent_targets.append(pinned_wt / name)
                else:
                    root_targets.append(pinned_wt / name)
    except Exception:
        pass                                   # no git / unreadable index → the two `.dockerignore`
                                               # targets above still stand (fail-safe, never raise)
    seen = set()
    for t, pats in ([(t, [rel]) for t in root_targets]
                    + [(t, [rel, base]) for t in parent_targets]
                    + [(t, ([rel, base] if ambiguous_ok else [rel]))
                       for t in companion_parent_targets]):
        key = str(t)
        if key in seen:
            continue
        seen.add(key)
        try:
            existing = t.read_text(encoding="utf-8") if t.exists() else ""
            lines = {ln.strip() for ln in existing.splitlines()}
            add = [p for p in pats if p not in lines]
            if not add:
                continue
            t.parent.mkdir(parents=True, exist_ok=True)
            sep = "" if (not existing or existing.endswith("\n")) else "\n"
            t.write_text(existing + sep
                         + f"# yitc pinned-verify fence (T-11205): a primed dependency link must never\n"
                           f"# enter a docker build context — BuildKit cannot replace a built directory\n"
                           f"# with the link (X-0954 / X-0949).\n"
                         + "".join(f"{p}\n" for p in add), encoding="utf-8")
        except Exception:
            continue                           # fail-safe: an unfenced entry is the pre-change

def _pinned_env_prime(W: Path, pinned_wt: Path, *, _run_git_cap, _PINNED_ENV_DEP_DIRS=None, _PINNED_ENV_DEP_MAX_DEPTH=None, _pinned_env_dockerignore_fence=None) -> list:
    """SPEC-0077 §3 (T-11182 / X-0934) — make the PINNED leg's environment COMPARABLE to the CANDIDATE
    leg's, by linking the candidate worktree's untracked DEPENDENCY TREES into the pinned tree.

    THE ASYMMETRY THIS CLOSES. The pinned tree is `git worktree add --detach`, so it materializes ONLY
    TRACKED content and is re-created EMPTY on every land; the candidate leg runs the same declared
    `verify.layers` in the long-lived task worktree W, which accumulates UNTRACKED host state across a
    worker session (a worker that hits a missing-dependency gate installs it and moves on — the
    reporter measured 5 of 11 live kupiclub worktrees carrying `frontend/node_modules`). A layer whose
    command needs such a dependency was therefore GREEN-candidate / RED-pinned BY CONSTRUCTION, on
    every land, forever. SPEC-0077 §2 re-pinning cannot reach it: re-pinning resets CONTENT staleness
    by moving the baseline, and the pinned ENVIRONMENT is re-created empty regardless — which is why
    three `--rebaseline` grants in one evening did not stick. A self-regenerating condition that
    consumes an owner ack per land is the reported harm, so the environment is fixed, not the ledger.

    NOT A ROUTE AROUND `prep:`. SPEC-0152 rule 16 already makes a layer that DECLARES its dependency
    prep symmetric — `_run_layer_prep` runs inside whichever worktree `_consumer_zero_probe_guard` is
    evaluating, pinned tree included, installing from the lockfile in BOTH legs. That declared path
    stays strictly better (reproducible, bounded, audited) and the printed note below says so. This
    covers the layer that does NOT declare one and leans on a hand-installed host dependency.

    WHY IT CANNOT BLIND THE PINNED LEG — the only way this could be a wrong fix. The pin's protection
    lives entirely in TRACKED content: the last-green `tests/`, the last-green `yitc-ops.yaml`, the
    T-11184 declared check surfaces, and the materialized merged_base engine. A git-IGNORED directory
    is, by the project's own declaration, derived artifact; combined with `_PINNED_ENV_DEP_DIRS` it is
    lockfile-derived dependency, so it is never a CHECK surface and never the SUBJECT (the subject is
    the candidate's tracked source, which the pinned tree already carries at HEAD). Priming can also
    never DISPLACE an overlay: an entry whose relative path already exists in the pinned tree is
    skipped, and an ignored path is absent from the last-green index so no overlay ever writes it. The
    pinned leg keeps seeing the candidate change; what it stops seeing is the absence of `npm install`.

    SYMLINK, NOT COPY. A `node_modules` is routinely GBs; copying one per land would add a new
    wall-clock tax to every land in the repo. The pinned leg only READS the dependency tree, so a link
    is the honest representation of "the same installed dependency both legs saw".

    …AND A SYMLINK IS A FILE TO `docker COPY` (T-11205 / X-0954 / X-0949). That is the one place the
    link is not free: a Dockerfile that builds the dependency tree itself cannot have the context
    replace the directory it just made with a link, and BuildKit fails the ENTIRE build. So every
    entry primed here is immediately fenced out of any build context by
    `_pinned_env_dockerignore_fence` — read that docstring for why the fence, and not a
    "skip priming when the layer is a docker build" condition, is what actually closes it.

    FAIL-SAFE TOWARD TODAY'S BEHAVIOUR, never toward a new abort: every entry is guarded and every
    failure mode (unreadable dir, no git, OSError on the link) SKIPS that entry, so the worst case is
    exactly the pre-change RED. This function never raises and never returns a `bad` reason — it is
    not a gate. Returns the sorted list of primed relative paths; the caller NAMES them on stdout, so
    an inherited environment is auditable per land rather than implied."""
    primed: list = []
    # A DEPTH-BOUNDED walk for the allow-listed names, NOT `git status --ignored`: that command
    # refuses `--untracked-files=no` outright ("Unsupported combination of ignored and untracked-files
    # arguments", measured) and enumerating a candidate worktree's untracked files to find them costs
    # a full scan of the very dependency trees being looked for. The walk visits at most the repo root
    # plus its immediate subdirectories and NEVER descends into a matched tree.
    cands = set()
    try:
        roots = [W] + sorted(p for p in W.iterdir()
                             if p.is_dir() and not p.is_symlink() and p.name != ".git")
    except OSError:
        return primed
    for root in roots:
        try:
            children = sorted(p for p in root.iterdir() if p.name in _PINNED_ENV_DEP_DIRS)
        except OSError:
            continue
        for p in children:
            rel = p.relative_to(W).as_posix()
            if 1 <= len(Path(rel).parts) <= _PINNED_ENV_DEP_MAX_DEPTH:
                cands.add(rel)
    for rel in sorted(cands):
        src = W / rel
        dst = pinned_wt / rel
        try:
            if not src.is_dir() or src.is_symlink():
                continue                       # a FILE (or a link) under one of these names is not a
                                               # dependency tree we are willing to inherit
            # `git check-ignore` is the authority on "the project itself declares this DERIVED".
            # Without it the walk would prime a directory the project TRACKS under one of these names
            # (a real vendored `vendor/`), which the pinned tree already carries correctly at HEAD —
            # and re-pointing THAT at the candidate's copy would replace tracked subject content.
            if _run_git_cap(["check-ignore", "-q", "--", rel], W).returncode != 0:
                continue
            if dst.exists() or dst.is_symlink():
                continue                       # NEVER displace tracked content or an overlaid check
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src, target_is_directory=True)
        except Exception:
            continue                           # fail-safe: skip → the pre-change (RED) behaviour
        # T-11205 (X-0954/X-0949) — the link exists; now keep it OUT of every docker build context
        # that could receive it. Done per entry, immediately after the link, so the fence and the
        # thing it fences can never drift apart. Never raises (see the helper).
        _pinned_env_dockerignore_fence(pinned_wt, rel, _run_git_cap=_run_git_cap)
        primed.append(rel)
    return primed

def _timing_lane_pin_selection(discovered, only, refused):
    """T-12039 (audit-post finding 1, high) — the pinned leg's file selection AFTER the timing-lane
    refusal, and whether the narrowing may be applied at all. Returns
    `(new_only, applied, applied_names)`.

    T-12109 (fu_192d51d8f5d0) — `applied_names` is the THIRD element: the refused names that were
    ACTUALLY removed, i.e. `SELECTED ∩ refused`. It is returned rather than re-derived by the caller
    because it is NOT recoverable from `(refused, new_only)` alone: on a MIXED `only` selection a
    declared name can sit OUTSIDE the selection, so it appears in `refused`, is absent from
    `new_only`, and yet narrowed nothing away. The call site used to report `set(refused) -
    set(new_only)` per refusal and `len(refused)` in its summary; the first over-reports on exactly
    that mixed shape and the second over-reports on every one, and the two could disagree with each
    other. Both now read this one value, which is computed where SELECTED is defined — the reason
    this is a returned value and not a second copy of the selection rule at the call site.
    Report-only: no verdict, gate or selection reads it, and the NARROWING is unchanged.

    THE DEFECT THIS CLOSES, in the auditor's own words and its own differential input. The first
    version computed its all-refused guard over the WHOLE discovered sweep while the narrowing was
    applied to the INCOMING `only` selection — two different sets. With
    `only={'test_slow_budget.py'}`, that one file declared timing-sensitive, and `test_ordinary.py`
    also present in the sweep, the guard saw a non-empty keep set (`test_ordinary.py`) and let the
    narrowing through, leaving `only = set()`. An EMPTY `only` runs NOTHING in the in-process runner,
    whose verdict is pass-iff-empty — so the pinned leg would have read GREEN having executed no
    check. That is the exact false green SPEC-0077 exists to end, reintroduced by this card's own
    optimisation. The guard must therefore be computed on the EFFECTIVE selection, never on the sweep.

    THE RULES, in one place so the two sets cannot drift apart again:
      • SELECTED = what would run TODAY — `only ∩ discovered` when a caller supplied `only`
        (a name `only` asks for that the glob never discovered is already absent), else `discovered`.
      • EFFECTIVE = SELECTED minus the refused names.
      • APPLIED is False — the narrowing is DROPPED and the leg runs unchanged — when EFFECTIVE is
        empty (it would silently green the leg, above) OR when the refusal touches nothing that was
        going to run anyway (no narrowing to do, and printing refusals for files outside the
        selection is noise the operator cannot act on).
    Dropping the narrowing is always the fail-SAFE direction: the pinned leg then runs MORE, which
    costs flakiness in a configuration the project fixes with a `timing_lane_waiver`, never a
    false green. Pure and total."""
    _disc = set(discovered or ())
    _ref = set(refused or ())
    selected = (set(only) & _disc) if only else set(_disc)
    applied_names = _ref & selected          # what a narrowing would ACTUALLY remove
    if not applied_names:
        return (only, False, frozenset())    # nothing that was going to run is refused
    effective = selected - _ref
    if not effective:
        # would run NOTHING, which reads GREEN — refuse to apply. Nothing was removed, so the
        # applied set is EMPTY here too: the caller prints nothing on this branch.
        return (only, False, frozenset())
    return (effective, True, frozenset(applied_names))


def _timing_lane_pin_refusals(ops: "dict | None", test_paths, *, _expand_declared_glob=None) -> dict:
    """T-12039 (SPEC-0160 rule 10 / SPEC-0093 rule 10) — WHICH of the pinned sweep's test files the
    project has DECLARED timing-sensitive and has NOT waived, keyed by BASENAME, each mapped to the
    refusal text the pinned leg prints. `{}` when the project declares nothing.

    THE DEFECT THIS CLOSES. The SPEC-0077 pinned last-green leg re-runs a project's OLD checks
    against the NEW tree, INSIDE a land, beside every other land's verify. A check whose verdict is a
    function of WALL CLOCK — a duration assertion, a rate, a timeout margin — is there measuring the
    HOST, not the change: it flips on load, ABORTS the land, and re-queues it. That class caused 8 of
    15 verify-aborts on 2026-09-04. The kernel cannot GUESS which checks those are (the same
    guess-vs-declaration split `_pinned_declared_check_paths_by_layer` and `declared_test_globs`
    already resolved in favour of the declaration), so the project DECLARES them and this predicate
    reads that declaration.

    WHAT IS RETURNED. `{basename: refusal-text}` for every path a declared `timing_lane:` glob
    matches and no VALID sibling `timing_lane_waiver:` re-admits. The refusal text names the MATCHING
    GLOB and the WAIVER ROUTE — never a silent omission (the never-silent partial-pin discipline this
    leg already holds). Keyed by basename because the runner's whole downstream surface is name-keyed
    (`_run_verify_tests(only=...)`, `_verify_failing_test_names`, the `--rebaseline-waive` matcher),
    and a duplicate basename across two swept dirs already fails the run closed there.

    SCOPE. Per CLASS: a waiver re-admits only within the class that declares it, because that is the
    entry whose `timing_lane:` it sits beside. Matching is this codebase's ONE path-vs-glob idiom —
    `task_mod._expand_declared_glob` then `fnmatch`, where `*` spans `/` — the SAME reader the sibling
    `tests.classes[].globs` field goes through (`task.declared_test_globs`), never a second engine.

    FAIL DIRECTIONS, deliberately asymmetric and stated because they are not symmetric:
      • A MALFORMED or absent `timing_lane:` refuses NOTHING — fail-SAFE toward pinning MORE. Refusing
        on a declaration nobody can read would silently SHRINK the pinned set, which is the false
        green SPEC-0077 exists to end.
      • A MALFORMED `timing_lane_waiver:` (missing/empty/non-list `globs:`, missing/empty `reason:`)
        waives NOTHING and the refusal STANDS — fail-CLOSED, the direction every other waiver in the
        catalog fails. An unreadable waiver must not quietly buy a pin.

    Pure and total: no git, no filesystem, no carrier read. The CALLER supplies both the already-read
    LAST-GREEN carrier (never the candidate's — SPEC-0077 §3 self-approval) and the repo-relative
    paths.

    `_expand_declared_glob` is the host's `task._expand_declared_glob`, arriving on this module's
    keyword-INJECTION seam because this module imports only stdlib and never back-imports the host.
    Absent (a direct caller that injected nothing), each glob is used AS WRITTEN — which is the same
    fail-SAFE direction as everything else here: an unexpanded `{a,b}` or zero-depth `**/` matches
    FEWER files, so it refuses fewer and pins MORE."""
    import fnmatch
    _expand = _expand_declared_glob if _expand_declared_glob is not None else (lambda g: [g])
    classes = None
    if isinstance(ops, dict):
        tests = ops.get("tests")
        if isinstance(tests, dict):
            classes = tests.get("classes")
    if not isinstance(classes, list):
        return {}
    rels = [str(p).strip().lstrip("./") for p in (test_paths or ())]
    rels = [r for r in rels if r]
    if not rels:
        return {}
    out: dict = {}
    for c in classes:
        if not isinstance(c, dict):
            continue
        lane = c.get("timing_lane")
        if not (isinstance(lane, list) and len(lane) > 0):
            continue                       # absent OR malformed → refuses nothing (fail-SAFE)
        lane_globs = [str(g).strip() for g in lane if isinstance(g, str) and str(g).strip()]
        if not lane_globs:
            continue
        waiver_globs: list = []
        waiver = c.get("timing_lane_waiver")
        if isinstance(waiver, dict):
            wg = waiver.get("globs")
            reason = waiver.get("reason")
            if (isinstance(wg, list) and len(wg) > 0
                    and isinstance(reason, str) and reason.strip()):
                for g in wg:
                    if isinstance(g, str) and g.strip():
                        waiver_globs.extend(_expand(g.strip()))
        cname = str(c.get("class") or "").strip() or "(unnamed class)"
        for raw in lane_globs:
            for g in _expand(raw):
                for rel in rels:
                    if not fnmatch.fnmatch(rel, g):
                        continue
                    if any(fnmatch.fnmatch(rel, wg) for wg in waiver_globs):
                        continue           # an explicit waiver RE-ADMITS this file to the pinned set
                    name = Path(rel).name
                    out.setdefault(name, (
                        f"NOT PINNED: {rel} is declared TIMING-SENSITIVE by "
                        f"`tests.classes[{cname}].timing_lane` glob {raw!r} — a wall-clock check run "
                        f"inside a land measures the host, not the change (SPEC-0160 rule 10 / "
                        f"T-12039). It still runs in the ordinary candidate verify. To pin it anyway, "
                        f"declare a sibling `timing_lane_waiver: {{globs: [{raw!r}], reason: \"<who "
                        f"accepted the flake risk, and why>\"}}` on that class in yitc-ops.yaml."))
    return out


_PINNED_LEG_CENSUS_MARKER = "# yitc: pinned-leg: census"
# T-12307 (SPEC-0077 §3) — the ONE spelling of the opt-in census declaration, so the reader below and
# the files that adopt it cannot drift. Matched as a PREFIX of a stripped line anywhere in the file
# (a docstring line carrying it counts — the declaration is the marker's PRESENCE, not its position),
# which is what lets a file put it beside the sentence explaining why it is census-class.


def _pinned_census_marker_refusals(pinned_wt: Path, rels) -> dict:
    """T-12307 (SPEC-0077 §3) — WHICH of the pinned sweep's test files DECLARE themselves
    census/inventory-class, and are therefore NOT re-run in the pinned last-green leg. Returns
    `{basename: (rel, "census", refusal-text)}`; `{}` when nothing declares.

    THE DEFECT THIS CLOSES. A CENSUS test asserts «every enumerated member carries a disposition» —
    every journal reader is segment-aware, every verb appears in the catalog, every reader is
    dispositioned. Run as a LAST-GREEN copy against a NEW tree, such a check fails the moment the
    candidate ADDS a member, which is not a regression signal but the definition of the assertion:
    the last-green census cannot know about a member that did not exist when it was written. Measured
    over the journal segment 2026-09-02..09-09 (the Controller's 2026-09-09 fold, 814 `land_completed`
    rows): 95 of 208 verify aborts were pinned-only, and 73 of those branches later landed via
    `--rebaseline --rebaseline-kind broken` — i.e. the pin was stale BY CONSTRUCTION. Three census
    files account for most of them (tests/test_t11444_segment_aware_readers.py,
    tests/test_t11449_reader_multiset_identity.py, tests/test_uncovered_journal_reader_dispositions.py).

    WHOSE TREE THE MARKER IS READ FROM, and why that is not negotiable. `pinned_wt` — the LAST-GREEN
    overlay — never the candidate tree. This is the SPEC-0077 §3 self-approval boundary the sibling
    `_pinned_declared_check_paths_by_layer` (T-11184) and `_timing_lane_pin_refusals` (T-12039) both
    hold: reading the CANDIDATE copy would let the very commit that weakens a check also declare that
    check census-class and so dodge its own pin. CONSEQUENCE, stated rather than hidden: a file that
    ADOPTS the marker in card X is still pinned on X's own land and narrows only from the land after.
    That one-land lag is the same one `timing_lane:` already carries, and it is the fail-SAFE direction.

    OPT-IN, NEVER INFERRED. There is no heuristic for "this looks like a census" and none is wanted:
    the same guess-vs-declaration split resolved in favour of the declaration for `verify.layers`
    check paths and for `timing_lane:`. An UNMARKED census simply stays pinned exactly as today, and
    `graph conformance` gains no check to hunt for unmarked ones (card §CHANGES (d)).

    FAIL DIRECTION, single and deliberate: an unreadable file refuses NOTHING — fail-SAFE toward
    pinning MORE. Refusing on a file we could not read would silently SHRINK the pinned set, which is
    the false green SPEC-0077 exists to end.

    IDENTITY. Detection is by repo-relative POSIX path (the caller's `rels`, resolved against
    `pinned_wt`); the RETURN is keyed by basename because that is the vocabulary of the one seam that
    consumes it — `_run_verify_tests(only=...)` — and the rel path travels in the VALUE so the report
    can name the file unambiguously (audit-pre finding 1). Non-recursive discovery plus the runner's
    own duplicate-basename fail-closed make the key total at that seam.

    Pure filesystem read on a THROWAWAY tree: no git, no carrier, no mutation."""
    out: dict = {}
    for rel in (rels or ()):
        rel = str(rel).strip()
        if not rel:
            continue
        try:
            text = (pinned_wt / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue                       # fail-SAFE: unreadable declares nothing → stays pinned
        if not any(ln.strip().startswith(_PINNED_LEG_CENSUS_MARKER) for ln in text.splitlines()):
            continue
        out[Path(rel).name] = (rel, "census", (
            f"{rel} is NOT re-run in the pinned last-green leg — the LAST-GREEN copy declares itself "
            f"census/inventory-class (`{_PINNED_LEG_CENSUS_MARKER}`), and a census asserts «every "
            f"enumerated member carries a disposition», so any change that ADDS a member fails the "
            f"old copy by definition rather than as a regression (SPEC-0077 §3, T-12307). It still "
            f"runs in the ordinary candidate verify. To pin it again, delete the marker line."))
    return out


def _pinned_touched_is_weakening(pinned_wt: Path, W: Path, rel: str) -> bool:
    """T-12307 (SPEC-0077 §3) — is the CANDIDATE copy of `rel` a WEAKENING of its LAST-GREEN copy?

    `True` keeps the file PINNED (the touched-exclusion does not apply to it); `False` lets the
    exclusion apply. The whole guard is two counts over two text blobs: the candidate must still
    EXIST and must carry no fewer `def test_` nodes and no fewer `assert` statements than the
    last-green copy. Rationale, the fence it protects and the shape it deliberately does not catch:
    see `_pinned_touched_refusals`.

    EVERY failure path returns `True` — an unreadable last-green copy, an absent or unreadable
    candidate copy, any exception at all. There is exactly ONE fail direction here and it is toward
    pinning MORE, because the alternative — silently shrinking the pinned set on a read we could not
    make — is the false green this whole leg exists to prevent."""
    try:
        last_green = (pinned_wt / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True                        # cannot read the last-green copy → stays pinned
    try:
        candidate = (W / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True                        # REMOVED on the branch, or unreadable → stays pinned
    for token in ("def test_", "assert"):
        if candidate.count(token) < last_green.count(token):
            return True
    return False


_PINNED_FIRST_ATTEMPT_SURFACE = "tests/"      # the pinned test surface this preflight selects over


def _pinned_touched_weakened_keys(W: Path, merged_base: str, *, _run_git_cap) -> list:
    """T-12325 (SPEC-0077 §3a) — the basenames of the pinned test files THIS branch's own diff both
    TOUCHED and WEAKENED, in diff order and de-duplicated. `[]` when there are none.

    THIS IS THE COMPLEMENT OF `_pinned_touched_refusals`, AND THE COMPLEMENT IS THE POINT. That
    sibling builds the EXCLUSION set — touched AND *not* weakening, dropped from the pinned leg
    because the last-green copy would be asserting behaviour the card deliberately supersedes. What
    is left PINNED on purpose is the weakening case: the SPEC-0077 self-approval fence, where a
    candidate that hollows out a registered check must still face the copy that would have bitten it.
    That set is therefore exactly the population whose pinned copies are about to RED — and the whole
    of what a first, undeclared land pays a full two-leg verify to discover. Running just those files
    answers the question in seconds instead.

    THE WEAKENING JUDGEMENT IS NOT MADE HERE. It is `_pinned_touched_is_weakening`, called UNCHANGED,
    so the two-count rule (`def test_` / `assert`), its documented blind spot, and its fail-safe
    directions all keep exactly ONE home. This function only SELECTS what to ask it about and
    materializes the last-green blob it needs — because at this seam, before any pinned overlay
    worktree exists, there is no `pinned_wt` to hand it. The blob it is given is the SAME content the
    overlay would have carried (`<merged_base>:<rel>`, the last-green copy), so the predicate is
    answering its own question about its own two trees, not a re-derived approximation of it.

    THE DISCOVERY BOUND IS COPIED FROM THE RUNNER, AND THE COUPLING IS THE REAL CONTENT OF THIS NOTE.
    `_run_pinned_verify` discovers its sweep with `<dir>.glob("test_*.py")` — NON-recursive — so this
    selects `tests/test_*.py` with exactly one path separator and nothing deeper. Widening it to
    `rglob` would name files the pinned leg never runs, which would refuse a land on a check that was
    never going to execute. If the runner's discovery ever goes recursive, THIS must follow in the
    same change, or a weakened nested test silently stops being preflighted.

    FAIL DIRECTION: TOWARD ADMITTING — and it is the OPPOSITE of the sibling's, deliberately. Any git
    failure, any unreadable blob, any exception at all returns `[]`: no keys, so no preflight, so the
    land proceeds into the full verify exactly as it does today. In `_pinned_touched_refusals` a
    failure must not SHRINK the pinned leg, so it fails toward pinning MORE; here a failure must not
    INVENT a refusal, so it fails toward admitting — the T-11479 preflight's own fail-open rule,
    inherited rather than re-decided. Both directions are the same rule ("never a false green"):
    there, admitting less; here, refusing less. Neither can let a broken check through, because the
    full pinned leg still runs on every land this function stays silent about.

    Git for the diff and for each last-green blob; no carrier read, no mutation, no admission slot."""
    import tempfile

    try:
        r = _run_git_cap(["diff", "--name-only", f"{merged_base}..HEAD"], W)
        if getattr(r, "returncode", 1) != 0:
            return []
        touched = [n.strip().lstrip("./") for n in (r.stdout or "").splitlines() if n.strip()]
    except Exception:                      # noqa: BLE001 — a fact about the checker, never a verdict
        return []

    cands = []
    for rel in touched:
        # The runner's NON-recursive `tests/*.py` glob, restated as a path shape (see the note above).
        if not rel.startswith(_PINNED_FIRST_ATTEMPT_SURFACE) or rel.count("/") != 1:
            continue
        name = Path(rel).name
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        if rel not in cands:
            cands.append(rel)
    if not cands:
        return []

    keys = []
    try:
        with tempfile.TemporaryDirectory(prefix="yitc-pinned-firstattempt-") as td:
            base = Path(td)
            for rel in cands:
                blob = _run_git_cap(["show", f"{merged_base}:{rel}"], W)
                if getattr(blob, "returncode", 1) != 0:
                    # The file does not exist at last-green — this branch ADDED it. An added file has
                    # no last-green copy to weaken and the pinned leg's own prune drops it, so it is
                    # not a candidate here either. Skipping it is the fact, not a fail-open.
                    continue
                dst = base / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(blob.stdout or "", encoding="utf-8")
                if _pinned_touched_is_weakening(base, W, rel):
                    k = Path(rel).name
                    if k not in keys:
                        keys.append(k)
    except Exception:                      # noqa: BLE001 — fail toward ADMITTING (see above)
        return []
    return keys


def _pinned_touched_refusals(W: Path, merged_base: str, rels, *, pinned_wt: Path, _run_git_cap) -> dict:
    """T-12307 (SPEC-0077 §3) — WHICH of the pinned sweep's test files THIS branch's own diff TOUCHED,
    and are therefore NOT re-run as their LAST-GREEN copy. Returns
    `{basename: (rel, "touched", refusal-text)}`; `{}` when the diff touches no swept test file.

    THE DEFECT THIS CLOSES. When a card deliberately CHANGES a test — a mirror it must move with the
    thing mirrored, an assertion whose subject the card supersedes — the pinned leg re-runs the OLD
    copy of that very file against the NEW code and REDs. That is the change working as declared, not
    a regression: the class showed up as t9340 on the venue (T-12300) and as the pinned copy of
    tests/test_t12247_venue_per_request_refs.py against T-12296's deliberately changed mirror. The
    NEW copy is not skipped — the CANDIDATE leg runs it, in full, on every one of these lands. So what
    is lost is the old copy of a file the card is on record as having rewritten, and the guard against
    a card that edits a test to HIDE a regression is audit-post's diff review, which reads that edit
    directly, not a pin whose signal here is indistinguishable from the intended change.

    WHOSE TREE, and why this one is the CANDIDATE's while the census marker's is the last-green's.
    The two are not the same question. «Is this file census-class?» is a DECLARATION, and a
    declaration read from the candidate would let a commit exempt itself (see the sibling). «Did this
    branch touch this file?» is not a declaration at all — it is the DIFF, the fact itself, and it can
    only ever be read from the candidate because that is where the fact lives. It cannot be gamed
    without actually editing the file, which is precisely the condition being detected.

    DIRECTIONAL SCOPE: intersected with the caller's `rels` — the files the pinned sweep would
    actually discover and run — so a touched file outside the swept surface refuses nothing, and the
    ADDED direction (already pruned by `_pinned_candidate_added_paths`) is simply idempotent here.

    FAIL DIRECTION: raises `RuntimeError` on a git failure so the caller fails CLOSED, exactly as the
    sibling prune does — a diff we could not resolve must never be read as "touched nothing" (that
    would keep the leg WHOLE, which is safe) NOR as "touched everything" (which would silently
    disable it). Raising leaves the choice where SPEC-0077 §3 puts it: a setup failure is a pinned
    failure, never a silent skip.

    THE WEAKENING GUARD — why "touched" is NOT sufficient on its own (Controller decision
    2026-09-10, `owner_directive` events.jsonl#ts=2026-09-10T03:54:35Z; card AC2 as amended).
    An UNCONDITIONAL touched-exclusion silences the SPEC-0077 self-approval fence in its canonical
    shape: a candidate that NEUTERS a registered check has, by that very act, "touched" the file, so
    excluding every touched file would let the commit that removes a check's teeth also remove the
    last-green copy that would have bitten it — exactly what
    tests/test_pinned_verify_2.py::test_t11253_weakening_and_removal_still_abort_the_pinned_leg
    exists to catch, in BOTH its weaken and remove arms. So the exclusion applies ONLY when the
    candidate copy is NOT a WEAKENING of the last-green copy: the file still EXISTS on the branch AND
    carries no fewer `def test_` nodes AND no fewer `assert` statements than the last-green copy.
    Two counts over two text blobs — the cheapest measurement that separates «the card rewrote this
    check» from «the card hollowed it out», and deliberately not a semantic one: a real analysis of
    what an assertion MEANS is not a thing a verify-time guard can do, and pretending otherwise would
    be the false green SPEC-0077 exists to end. What it therefore does NOT catch is stated rather
    than hidden: a rewrite that keeps both counts while weakening what they assert still narrows,
    and that shape stays where the card puts it — audit-post's diff review.

    FAIL-SAFE IN ONE DIRECTION, always toward PINNING MORE: an unreadable last-green copy, an
    unreadable or ABSENT candidate copy, and any exception whatever leave the file PINNED. A removal
    is the absent-candidate case and needs no separate branch — it is the fail-safe path taken on
    purpose.

    WHOSE TREE EACH COUNT COMES FROM: the last-green copy from `pinned_wt` (the overlay the pinned
    leg would have run) and the candidate copy from `W` (the branch worktree the diff was read
    from) — the same two trees this function and its census sibling already read, so the guard adds
    no third source of truth and no new git call.

    Git for the diff, plain filesystem reads for the two blobs; no carrier read, no mutation."""
    r = _run_git_cap(["diff", "--name-only", f"{merged_base}..HEAD"], W)
    if r.returncode != 0:
        raise RuntimeError(f"git diff --name-only {merged_base}..HEAD: {r.stderr or r.stdout}")
    touched = {n.strip().lstrip("./") for n in (r.stdout or "").splitlines() if n.strip()}
    out: dict = {}
    for rel in (rels or ()):
        rel = str(rel).strip().lstrip("./")
        if not rel or rel not in touched:
            continue
        if _pinned_touched_is_weakening(pinned_wt, W, rel):
            continue                       # fail-SAFE: weakened, removed or unreadable → stays pinned
        out[Path(rel).name] = (rel, "touched", (
            f"{rel} is NOT re-run in the pinned last-green leg — THIS branch's own diff changed it, so "
            f"the last-green copy would be asserting the behaviour this card deliberately supersedes "
            f"(SPEC-0077 §3, T-12307). The CANDIDATE leg runs the NEW copy in full on this same land; "
            f"a test edited to hide a regression is caught by audit-post's diff review, not by the pin."))
    return out


def pinned_leg_narrowing(W: Path, merged_base: str, pinned_wt: Path, rels, *,
                         _run_git_cap) -> tuple:
    """T-12313 (SPEC-0077 §3) — THE ONE COMPUTER of the T-12307 pinned-leg narrowing. Returns
    `(meta, refused)`: `meta = {basename: (rel, reason)}` for the REPORT and
    `refused = {basename: refusal-text}` for the SELECTION — the two dicts `_run_pinned_verify`
    already built inline, moved out VERBATIM so a SECOND driver can reach the same computation.

    WHY IT MOVED, measured. T-12307 shipped these two exclusions inside `_run_pinned_verify`, which
    a ROUTED land (SPEC-0203) NEVER CALLS: `_land_integrate` reaches the local driver only under
    `_venue_routed is None`, and the box leg computes only `discovered - excluded - not_pinned`. So
    on 2026-09-10 every one of the day's venue lands printed ZERO `land[pinned/last-green]:` skip
    lines and wrote no `pinned_skipped` key, and each then ABORTED on a stale pinned copy and paid a
    full rebaseline round — the exact cost T-12307 exists to remove. The fix is ONE computer with
    TWO drivers (this function), not a second implementation box-side: a narrowing spelled twice is
    the drift T-12109 closed, and AC2's «the box list is byte-identical to the host selection» is
    then true BY CONSTRUCTION rather than by comparison.

    WHOSE TREE EACH HALF READS is unchanged and is not this function's choice to make: the CENSUS
    marker from `pinned_wt` (a declaration must not be self-granted) and the TOUCHED fact from the
    candidate diff — see each helper for the SPEC-0077 §3 self-approval boundary that fixes them.

    IT RAISES rather than deciding a fail direction. The two drivers want OPPOSITE ones — the local
    driver fails CLOSED (an unresolvable input aborts the land, because it owns the pinned verdict)
    and the routed entry fails SAFE (narrow nothing, so the box runs MORE) — so the direction is the
    CALLER's and this function only reports what it could not resolve."""
    meta: dict = {}                        # basename -> (rel, reason), for the REPORT only
    refused: dict = {}                     # basename -> refusal text, for the selection
    sources = dict(_pinned_census_marker_refusals(pinned_wt, rels))
    sources.update(_pinned_touched_refusals(
        W, merged_base, rels, pinned_wt=pinned_wt, _run_git_cap=_run_git_cap))
    for bn, (rel, why, text) in sources.items():
        meta[bn] = (rel, why)
        refused[bn] = text
    return meta, refused


def routed_pinned_narrowing(W: Path, merged_base: str, *, _run_git_cap, sweep_dirs) -> tuple:
    """T-12313 (SPEC-0077 §3 / SPEC-0203) — the HOST-side routed driver of `pinned_leg_narrowing()`.
    Returns `(names, meta)`: the BASENAMES the routed pinned leg must not re-run, and the same
    `{basename: (rel, reason)}` meta the local driver reports from. `sweep_dirs` are the
    repo-relative test-sweep directories (the `verify.layers` carrier's, resolved by the caller —
    this module never reads the host carrier itself).

    THE HOST IS THE SINGLE COMPUTER (card CHANGES (b)). The box never rebuilds this selection: it
    receives the names and applies them. That is what makes AC2 a comparison of one function against
    ITSELF, and it is the same shape SPEC-0181 R1's governed selection already uses — decided by the
    caller, carried to the leg, bound box-side.

    HOW THE LAST-GREEN TREE IS OBTAINED, and why NOT a text pipe. `pinned_leg_narrowing()` needs a
    `pinned_wt` to read the census marker out of, and on the routed path no pinned worktree exists
    host-side. So the last-green test files are materialized into a THROWAWAY tempdir with
    `git archive --format=tar -o <file>` + stdlib `tarfile`: the archive is written to a FILE, so
    there is no stdout capture, no shell pipe and NO DECODING STEP anywhere between git and the
    bytes on disk. A source tree carrying arbitrary or non-UTF-8 bytes therefore round-trips
    UNCHANGED and the narrowing is computed off the same bytes the box will overlay, rather than off
    a re-encoded copy. (The only decoding is inside the T-12307 helpers themselves, which already
    read `errors="replace"` and count ASCII tokens — unchanged, and identical to what the local
    driver decodes.)

    DISCOVERY MIRRORS THE RUNNER'S, non-recursively (`test_*.py` per swept dir), for the reason the
    local driver's own enumeration note states at length: the runner discovers exactly that set, so
    a wider glob would refuse files the leg never runs and report a narrowing that never happened.

    FAIL-SAFE, ONE DIRECTION. ANY failure — the archive, the extract, the glob, the narrowing itself
    — returns `([], {})`: narrow NOTHING, so the box runs MORE, never fewer. This is the OPPOSITE
    direction from the local driver's fail-CLOSED, deliberately: there an unresolvable input can
    abort the land, but here the leg still runs whole on the box, so the safe answer is «no
    narrowing» rather than «no verdict»."""
    import tarfile
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="yitc-routed-narrowing-") as _td:
            base = Path(_td) / "lastgreen"
            base.mkdir(parents=True, exist_ok=True)
            rels: list = []
            for d in (sweep_dirs or ()):
                d = str(d).strip().strip("/")
                if not d:
                    continue
                tar_path = Path(_td) / f"{d.replace('/', '_')}.tar"
                # The archive goes to a FILE (`-o`), never through the capture path: `_run_git_cap`
                # is used exactly as every other git call here is, and the TAR never travels through
                # it — that is the whole binary-safety property this function rests on.
                r = _run_git_cap(["archive", "--format=tar", "-o", str(tar_path),
                                  merged_base, "--", d], W)
                if r.returncode != 0:
                    continue               # a dir absent at last-green declares nothing here
                with tarfile.open(tar_path) as tf:
                    tf.extractall(base)     # noqa: S202 — our own `git archive` output, not input
                for f in sorted((base / d).glob("test_*.py")):
                    rels.append(f.relative_to(base).as_posix())
            if not rels:
                return [], {}
            meta, refused = pinned_leg_narrowing(
                W, merged_base, base, rels, _run_git_cap=_run_git_cap)
            return sorted(refused), meta
    except Exception:
        return [], {}                      # fail-SAFE: narrow nothing → the box runs MORE


def _run_pinned_verify(W: Path, main_wt: Path, merged_base: str, branch: str,
                       workers: "int | None" = None, admission_slots: "int | None" = None, *,
                       _run_git_cap, _consumer_zero_probe_guard, _materialize_pinned_engine_bin, _run_verify_tests,
                       _read_worktree_stamp, _worktree_stamp_path, _utc_now_iso,
                       SUBENV_SCRUB_CARRIERS=None, _consumer_tests_delegation=None,
                       _delegated_tests_execution_gap=None,
                       admission_wait_out=None, _try_resolve_session_ref=None,
                       only: "set[str] | None" = None, excluded_out: "list | None" = None, skipped_out: "list | None" = None, CONSUMER_OPS_CONTRACT=None, _PINNED_PREFIX=None, _PINNED_VERIFY_DRIVER=None, _in_hermetic_verify_child=None, _load_ops_carrier_text=None, _pinned_candidate_added_paths=None, _pinned_declared_check_paths_by_layer=None, _pinned_env_prime=None, _pinned_verify_subprocess_env=None, _render_tests_delegation_note=None, _verify_admission=None, _declared_test_sweep_paths=None, _ROOT_TEST_SWEEP_DIR=None, _expand_declared_glob=None) -> list:
    """SPEC-0077 §2-§3 — the pinned LAST-GREEN both-must-pass re-run for a verify-implementation-touch
    land. Returns [] (pass) or [<reason>, ...] (the SAME shape `_run_verify_tests` uses → folded into
    `bad` → LAND: ABORT). Construction: a throwaway DETACHED worktree of the candidate HEAD (the SUBJECT
    being verified), with the verify CHECK surfaces (`tests/` + the consumer verify contract) OVERLAID
    from merged_base — so the OLD checks apply to the NEW subject. The overlay is COMPLETE in BOTH
    directions (T-11253): base content is RESTORED over the candidate's, AND paths the candidate ADDED
    under an overlaid tree are PRUNED, so the pinned check surface EQUALS last-green rather than
    (last-green UNION candidate-added) — a `git checkout <base> -- <sub>` alone deletes nothing. The ENGINE checks run with the OLD
    verifier LOGIC + RUNNER in an ISOLATED SUBPROCESS against a MATERIALIZED merged_base bin/ tree (T-9348
    — a fresh interpreter with clean sys.modules, so `from lib import worktree` resolves to the merged_base
    lib.* across the layered package, NOT the live one; an in-process load would run LIVE logic). So a
    candidate that weakens the verify CODE/RUNNER (not only a test), INCLUDING runner logic now resident in
    bin/lib/**, cannot self-approve. FAIL-CLOSED: any setup / subprocess / result-parse failure returns a bad
    reason (never silently skip the pinned gate).

    T-11182 (X-0934) — that detached construction also makes the pinned ENVIRONMENT tracked-only and
    empty on every land, while the candidate leg runs in the long-lived W. `_pinned_env_prime` links
    the candidate's git-IGNORED dependency trees in (allow-listed by name) so an UNdeclared host
    dependency cannot be GREEN-candidate / RED-pinned forever. Orthogonal to the overlay above: it
    adds only ignored paths no overlay writes, so WHICH CHECKS apply is unchanged.

    T-10977 (SPEC-0077 §3a) — COMPLETE-SET REPORTING. What this function returns is not merely read as a
    verdict: on a re-baseline attempt `_rebaseline_waive_coverage` matches the operator's
    `--rebaseline-waive` declaration against it ENTRY BY ENTRY, exact in BOTH directions. A fail-fast
    SUBSET therefore made the required declaration MOVE between runs (an entry absent from run A refuses
    as uncovered in run B; a token written from run A binds nothing in run B and refuses as `no-match`),
    which is the coin flip that cost 8 land aborts on T-10956 in one day. So the test-runner leg now asks
    for its COMPLETE failing set (`fail_fast=False` on the in-process §6b path; capability-probed in
    `_PINNED_VERIFY_DRIVER` for the subprocess path, since that runner is merged_base code). The consumer
    leg (`_consumer_zero_probe_guard`) already ran EVERY declared layer and needed no change. Nothing about
    WHICH checks run, or the pass-iff-empty verdict, changes — only how much of the failing set is told."""
    import shutil
    import subprocess
    import tempfile
    pinned_wt = Path(tempfile.mkdtemp(prefix="yitc-pinned-verify-"))
    shutil.rmtree(pinned_wt, ignore_errors=True)   # `git worktree add` needs a NON-existent path
    pinned_root = None
    try:
        add = _run_git_cap(["worktree", "add", "--detach", str(pinned_wt), "HEAD"], W)
        if add.returncode != 0:
            return [f"[pinned/last-green] setup FAILED (worktree add @last-green): {add.stderr or add.stdout}"]
        # T-10155 (SPEC-0077 locus-1, auditor GREEN): STAMP this detached verify worktree with a real
        # v2-owned {session_ref, started_at} stamp so a test that carries an UNBACKED YITC_SESSION_REF
        # falls THROUGH to a legitimate stamped locus (the same premise the candidate verify's task/T-XXXX
        # worktree already meets) instead of `_resolve_session_ref` (SPEC-0137 Rule 5) `_die`-ing on a
        # stampless locus. Scoped to pinned_wt (the ambient cwd) ONLY — per-test-created loci stay
        # untouched, so identity tests still construct stampless loci deliberately. The resolver is NOT
        # modified (fail-closed behaviour preserved: it still `_die`s where no v2-owned artifact exists).
        # RESOLVER-INDEPENDENT: reuse the SOURCE worktree W's OWN owner stamp ref (W = the task/work
        # worktree being landed) rather than calling the fail-closed keyer `_resolve_session_ref` here —
        # that would itself `_die` in the very stampless/unbacked contexts this stamp exists to serve
        # (the T-10155 test_pinned_verify regression). The stamp VALUE is inert to the ~40 fall-through
        # tests (they assert no specific ref).
        #
        # T-11288 — W IS NOT ALWAYS STAMPED, and the fallback may not INVENT an identity. T-10155 wrote
        # the fixed literal `pinned-verify-locus` when `_read_worktree_stamp(W)` came back empty, on the
        # premise that W is always stamped. That premise is false for exactly the path the handbook
        # sanctions: a RAW-GIT recreation of a worktree (`git worktree add`, the recovery escape hatch —
        # AGENTS-SESSIONS §Writes-happen-in-a-worktree) leaves W with no stamp. The literal is a string no
        # session record backs, so it made this locus a SECOND, unbacked id — precisely what SPEC-0137
        # Rule 3 forbids ("the worktree stamp is a PROJECTION of the one identity into the write locus,
        # NOT a second id"), and the failure then surfaced as an opaque identity error deep inside a
        # pinned test rather than as a statement about the worktree. So the fallback now PROJECTS a real
        # identity or REFUSES, in this order:
        #   (i)  W's own stamp — unchanged, the ordinary path;
        #   (ii) the CALLER's own resolved ref, via the NON-DYING keyer twin `_try_resolve_session_ref`
        #        (never `_resolve_session_ref`: it `_die`s, per above). In production this is always
        #        available — `land` is a governed verb whose own gates already resolved the identity;
        #   (iii) neither, and this is PRODUCTION → RETURN a setup-FAILED reason NAMING the unstamped
        #         source worktree. Same `bad`-reason shape every other setup failure here returns
        #         (→ LAND: ABORT, fail-closed) — the gate getting STRICTER, no check skipped or relaxed;
        #   (iv)  neither, and this is a HERMETIC VERIFY CHILD → write NO stamp at all.
        #
        # WHY (iv) EXISTS — MEASURED, 2026-08-19 (this card's own first land ABORTed on it). The premise
        # under (ii) — "in production the caller's ref is always available" — is TRUE, and that is exactly
        # why (iii) alone was wrong: the only population that can reach a double-absence is the one where
        # identity is scrubbed BY DESIGN. `_run_pinned_verify` runs the LAST-GREEN tests, and the pinned
        # suite DELIBERATELY constructs stampless loci as fixtures (the comment above says so: per-test
        # loci stay untouched so identity tests can build them), inside subprocesses whose session-ref
        # carriers `_pinned_verify_subprocess_env` / `hermetic_child_env` shed for hermeticity. So (iii)
        # fired on 9 last-green files' FIXTURES, never on a real worktree — a false ABORT whose predictable
        # next move is an owner-gated `--rebaseline` spent on tests that are not broken. Patching the
        # fixtures cannot fix it either: the pinned leg runs LAST-GREEN tests, which no candidate-side
        # edit can reach.
        #
        # THE DISCRIMINATOR IS POSITIVE, and it is about the CALLER, not the locus
        # (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §1): `_in_hermetic_verify_child()`
        # answers "am I a test subprocess of the verify runner?" by resolving THIS process's OWN TMPDIR
        # to a real directory inside a verify sandbox — never by "this path looks like a fixture", never
        # by "some error happened". Its full rationale, including why a marker written by THIS engine
        # cannot serve a rule read inside the pinned leg, is at the helper's own definition. Not resolving
        # ⇒ production ⇒ (iii) refuses, so the fail-closed direction is unchanged for every real land. All
        # three inputs are POSITIVE and total: `_read_worktree_stamp` normalizes
        # absent/unreadable/malformed/no-session_ref to None, the non-dying twin returns None (never
        # raises) when identity is unresolvable, and the containment read resolves or it does not.
        #
        # WHY (iv) WRITES NOTHING rather than falling back to a marker: SPEC-0137 Rule 3 makes the stamp a
        # PROJECTION of the one identity. Where no identity exists there is nothing to project, so honest
        # ABSENCE is the only answer that is not an invented id — the whole point of this card. The
        # T-10155 fall-through belt is untouched by this: it protects the PRODUCTION pinned locus, whose
        # land always resolves an identity at (i) or (ii) and is therefore always stamped. MEASURED: with
        # (iv) writing nothing, all 9 last-green files that (iii) had failed pass (candidate bin/ +
        # last-green tests/, the pinned leg's exact shape).
        _sp = _worktree_stamp_path(pinned_wt)
        if _sp is not None:
            _ref = (_read_worktree_stamp(W) or {}).get("session_ref")
            if not _ref and _try_resolve_session_ref is not None:
                _ref = _try_resolve_session_ref()
            if _ref:
                _sp.write_text(json.dumps({"session_ref": _ref,
                                           "started_at": _utc_now_iso()}) + "\n", encoding="utf-8")
            elif not _in_hermetic_verify_child():
                return [f"[pinned/last-green] setup FAILED (session identity for the pinned locus): the "
                        f"SOURCE worktree {W} carries NO session stamp — it was created by raw git, not by "
                        f"`bin/yitc-v2 worktree new` — and this session's own identity is unresolvable "
                        f"either, so the pinned locus has no real ref to be stamped with. Refusing rather "
                        f"than stamping it with an invented marker no session record backs (SPEC-0137 "
                        f"Rule 3 — the stamp is a projection of the ONE identity, never a second id; "
                        f"T-11288). Re-open the worktree with `bin/yitc-v2 worktree new --task/--work` (or "
                        f"`bin/yitc-v2 worktree adopt`) so it carries a stamp, then re-run `land`."]
        # Overlay the LAST-GREEN CHECK surfaces over the candidate SUBJECT: tests/ (the engine checks) +
        # the consumer verify home (§6b — the carrier `verify.layers`, yitc-ops.yaml; the migrated
        # single-home, SPEC-0152 rule 5/16, T-9719). bin/** stays candidate — it is the SUBJECT the
        # pinned checks examine; the pinned verifier LOGIC comes from the materialized merged_base run below.
        # `_overlaid_trees` collects the TREE surfaces actually overlaid, for the T-11253 prune below.
        # A BLOB surface (the carrier itself, or a declared file operand) never needs pruning — the
        # checkout overwrites it in place — so only trees are collected.
        _overlaid_trees: list = []
        for sub in ("tests", CONSUMER_OPS_CONTRACT):
            _t = _run_git_cap(["cat-file", "-t", f"{merged_base}:{sub}"], W)
            _kind = (_t.stdout or "").strip() if _t.returncode == 0 else ""
            if _kind in ("blob", "tree"):
                co = _run_git_cap(["checkout", merged_base, "--", sub], pinned_wt)
                if co.returncode != 0:
                    return [f"[pinned/last-green] setup FAILED (checkout {sub}@last-green): {co.stderr or co.stdout}"]
                if _kind == "tree":
                    _overlaid_trees.append(sub)
        # T-11184 (X-0938) — ALSO overlay the check surfaces the consumer's DECLARATION names, so a
        # project whose tests are not at a root-level `tests/` actually gets its OLD checks applied to
        # the NEW tree (the loop above alone swapped only the carrier for such a project — a false green;
        # see `_pinned_declared_check_paths`).
        #
        # WHICH CARRIER THE PINNED LEG READS — the OLD (last-green) one, and ONLY it. This is decided
        # here BY CONSTRUCTION: the carrier is read from `pinned_wt` AFTER the loop above has checked the
        # last-green `yitc-ops.yaml` out over it, so a candidate that FLIPS the ops carrier — deletes a
        # layer, or rewrites its `command:` to something weaker — cannot thereby narrow which checks the
        # pinned leg applies to it. Reading the NEW carrier would let the same commit that weakens a
        # check also choose its own audit, which is precisely the self-approval SPEC-0077 §3 exists to
        # stop; reading BOTH would import candidate-declared operands that have no last-green counterpart
        # while widening the subject-overlay risk for no gain. (The T-10811 delegation-ROUTING read from
        # the CANDIDATE carrier below is a DIFFERENT question — which layer RUNS, not which checks apply —
        # and is deliberately unchanged.)
        _declared_overlaid: list = []
        _declared_ops = _load_ops_carrier_text(
            (pinned_wt / CONSUMER_OPS_CONTRACT).read_text(encoding="utf-8")
            if (pinned_wt / CONSUMER_OPS_CONTRACT).exists() else None)
        _by_layer = _pinned_declared_check_paths_by_layer(_declared_ops)
        for sub in sorted({p for ps in _by_layer.values() for p in ps}):
            t = _run_git_cap(["cat-file", "-t", f"{merged_base}:{sub}"], W)
            kind = (t.stdout or "").strip() if t.returncode == 0 else ""
            if len(Path(sub).parts) < 2:
                # ROOT-LEVEL operands are SKIPPED, files as well as directories. A top-level TREE is
                # subject-scale (`frontend`, `backend`) and overlaying it would replace the candidate
                # tree and BLIND the pinned leg — the same false green, inverted. A top-level FILE is
                # skipped on measured evidence, not caution: the existing consumer fixture declares
                # `command: grep -q INVARIANT-OK subject.txt`, where the operand IS the subject under
                # test — overlaying it reverted the subject and the weakened-contract arm stopped
                # aborting (caught by tests/test_pinned_verify.py at this task's Stage 6). A check
                # surface a project keeps at its repo ROOT is already covered by the `tests/` + carrier
                # overlay above, so this costs nothing that pair does not already pin.
                continue
            if kind not in ("blob", "tree"):
                continue                        # absent at last-green (or unreadable) → nothing to pin
            co = _run_git_cap(["checkout", merged_base, "--", sub], pinned_wt)
            if co.returncode != 0:
                return [f"[pinned/last-green] setup FAILED (checkout {sub}@last-green): {co.stderr or co.stdout}"]
            _declared_overlaid.append(sub)
            if kind == "tree":
                _overlaid_trees.append(sub)
        if _declared_ops is not None:
            # NEVER SILENT (the auditable-skip discipline the subject_globs skip already follows): state
            # exactly which last-green check surfaces were pinned, so a PARTIAL pin is visible per land
            # instead of reading as full protection.
            # The unresolved set is reported PER LAYER, not as one global line: in a MIXED carrier
            # (one layer resolved, another not) a global "all clear" would read as full protection for
            # the layer that pinned nothing — the exact shape of the defect this card fixes.
            _unresolved = sorted(n for n, ps in _by_layer.items()
                                 if not any(p in _declared_overlaid for p in ps))
            if _declared_overlaid:
                print(f"land[pinned/last-green]: declared check surfaces overlaid from last-green: "
                      f"{', '.join(_declared_overlaid)} (SPEC-0077 §3 — resolved from the LAST-GREEN "
                      f"{CONSUMER_OPS_CONTRACT} `verify.layers`, T-11184)")
            if _unresolved:
                print(f"land[pinned/last-green]: NO last-green check surface resolved for declared "
                      f"layer(s): {', '.join(_unresolved)} — for these, this land's pinned leg applies "
                      f"only the root `tests/` + carrier overlay, so treat their pin as PARTIAL. If a "
                      f"layer's checks live elsewhere, name them in its `command:` (T-11184).")
        # T-11253 (X-0979) — COMPLETE THE OVERLAY. A checkout RESTORES the base's paths but deletes
        # none, so every file the candidate ADDED under an overlaid tree survived and the pinned check
        # surface was (last-green UNION candidate-added). Prune the added ones so it is last-green, no
        # more and no less. This is the SAME axis as the overlay above (WHICH CHECKS apply) and its
        # missing half — not a relaxation: by SPEC-0077 §3 the candidate's legitimately new/stronger
        # checks execute in the CANDIDATE leg, and a check the candidate REMOVED or WEAKENED is
        # restored by the checkout and still runs here (`_pinned_candidate_added_paths` is directional).
        # Placed after EVERY overlay (so the tree list is complete) and before the priming below (which
        # adds only git-IGNORED paths, and so cannot interact with this tracked-only prune).
        _pruned: list = []
        for sub in _overlaid_trees:
            try:
                _added = _pinned_candidate_added_paths(W, merged_base, sub, _run_git_cap=_run_git_cap)
            except Exception as e:
                # FAIL-CLOSED like every other setup step: never fall through to a run whose check
                # surface we could not establish.
                return [f"{_PINNED_PREFIX}setup FAILED (resolve candidate-added paths under {sub}): {e}"]
            for rel in _added:
                try:
                    (pinned_wt / rel).unlink()
                except FileNotFoundError:
                    continue                     # already absent — idempotent, nothing to prune
                except OSError as e:
                    return [f"{_PINNED_PREFIX}setup FAILED (prune candidate-added {rel}): {e}"]
                _pruned.append(rel)
        if _pruned and excluded_out is not None:
            # T-12250 (SPEC-0077 §3) — SURFACE the prune to the caller, so the LOCAL driver reports
            # the same narrowing the ROUTED one does, under the ONE key
            # `land_completed.data.verify_metrics.pinned_excluded_not_pinned`. This is REPORTING
            # ONLY: the prune, its derivation, its fail-closed directions and the printed line above
            # are all untouched — the caller simply gets the names it already had no way to read.
            # The BARE NAMES (never the rel paths), because that is the vocabulary the runner
            # discovers and executes files under, and it is what the box leg's own
            # `excluded_not_pinned` records — two drivers describing one narrowing must spell it the
            # same way or the key means two things.
            excluded_out.extend(sorted({Path(rel).name for rel in _pruned
                                        if Path(rel).name.startswith("test_")
                                        and rel.endswith(".py")}))
        if _pruned:
            # NEVER SILENT — the same auditable discipline the two overlay notes above follow: what the
            # pinned leg did NOT run must be visible per land, never implied.
            print(f"land[pinned/last-green]: candidate-added check file(s) pruned from the pinned "
                  f"tree: {', '.join(_pruned)} (SPEC-0077 §3 — the pinned leg applies the LAST-GREEN "
                  f"checks only; these are the candidate's OWN new checks and they run in the "
                  f"CANDIDATE leg, T-11253/X-0979)")
        # T-11182 (X-0934) — ENVIRONMENT comparability, a DIFFERENT axis from the overlay above (which
        # decides WHICH CHECKS apply). Placed HERE, after every overlay and before any check runs: the
        # overlay owns the tracked paths first, so priming can only ever add what no overlay wrote.
        _primed_env = _pinned_env_prime(W, pinned_wt, _run_git_cap=_run_git_cap)
        if _primed_env:
            # NEVER SILENT (the same auditable discipline the partial-pin note above follows): an
            # INHERITED environment must be visible per land, never implied.
            #
            # T-11205 (X-0949) — WHAT THIS NOTE MAY NOT SAY. It used to close with "the durable fix
            # is a declared `prep:`", flatly. A consumer hitting the docker-context abort read that
            # as "declare a prep: and this link goes away" and it is NOT TRUE: priming runs BEFORE
            # any layer, so the link is already there when the prep's `npm ci` executes — which then
            # installs THROUGH the link into the OTHER leg's tree, and leaves the link exactly where
            # it was. The engine's own printed remedy therefore entrenched the failure it was quoted
            # against. The text below names the DIFFERENT failures separately and claims a fix only
            # where one exists.
            print(f"land[pinned/last-green]: candidate dependency tree(s) linked into the pinned "
                  f"environment: {', '.join(_primed_env)} (SPEC-0077 §3 — the pinned tree is "
                  f"tracked-only by construction, so an UNdeclared host dependency would RED it on "
                  f"every land; T-11182/X-0934. Each link is fenced out of any docker build context "
                  f"via this throwaway tree's own .dockerignore files, so it cannot break a build "
                  f"here — NOTHING is needed in your repo for that, T-11205/X-0954/X-0949. For the "
                  f"UNDECLARED-dependency inheritance itself the better route is a declared `prep:` "
                  f"on the layer — SPEC-0152 rule 16, installing from the lockfile in BOTH legs — "
                  f"noting it does NOT remove this link: a prep runs after priming and installs "
                  f"through it.)")
        bad = []
        # T-11204 (SPEC-0185 §1(a)) — WHICH DIRECTORIES THE PINNED SWEEP RUNS, and from WHOSE carrier.
        # Resolved from `_declared_ops` — the LAST-GREEN (`pinned_wt`) carrier read above, never the
        # candidate's — for exactly the reason that block already states: reading the NEW carrier
        # would let the same commit that weakens a check also choose which checks apply to it. So a
        # candidate that ADDS a `verify.layers` entry pointing its tests somewhere new does not
        # thereby move the pinned sweep; that only takes effect once the entry is itself last-green.
        # Existence is judged in `pinned_wt`, the tree these dirs are swept in. Falls back to the
        # root literal for the engine's own build and for any carrier that declares nothing.
        # The resolver is INJECTED by the host residue (this module never back-imports the host).
        _pinned_sweep_dirs = (_declared_test_sweep_paths(pinned_wt, _declared_ops)
                              if _declared_test_sweep_paths is not None
                              else [pinned_wt / (_ROOT_TEST_SWEEP_DIR or "tests")])
        # T-12039 (SPEC-0160 rule 10) — a test the project DECLARED timing-sensitive is NOT PINNED.
        # Read from the SAME `_declared_ops` LAST-GREEN carrier the sweep dirs came from, and for the
        # same T-11204/T-11184 reason: reading the CANDIDATE carrier would let the commit that declares
        # a lane also choose which checks apply to it. So a newly declared `timing_lane:` takes effect
        # on the land AFTER the one that declares it.
        #
        # The refusal is applied by NARROWING the EXISTING `only=` selection — no new runner parameter
        # (T-11479 already established this seam, and it is the one both the in-process §6b path and
        # the merged_base subprocess driver read). NEVER SILENT: every refusal prints its own
        # `land[pinned/last-green]:` line naming the matching glob and the waiver route, beside the
        # partial-pin report this leg already prints.
        #
        # DEGENERATE CASE, named rather than hidden: if EVERY discovered pinned test is refused, the
        # narrowing is NOT applied and the leg runs whole. An empty selection is not expressible to the
        # merged_base driver (its argv reads "" and "None" alike as "sweep everything", and that driver
        # is LAST-GREEN code this change cannot reach), and — more importantly — an empty `only` reads
        # GREEN in the in-process runner, which would turn a project's declaration into a silent
        # disabling of the whole pinned leg. Leaving it whole is the fail-SAFE direction: the cost is
        # flakiness in a configuration the project fixes with a waiver, never a false green.
        # THE ENUMERATION MIRRORS THE RUNNER'S OWN DISCOVERY, DELIBERATELY (audit-post finding 2,
        # medium — recorded as REFUTED-AND-PINNED rather than fixed). `_run_verify_tests` discovers
        # its files with exactly `_d.glob("test_*.py")` per swept dir — NON-recursive — so this is
        # the complete set of files the pinned leg can execute. A nested `tests/sub/test_x.py` is
        # therefore not "missed and still pinned": the runner never discovers it either, so there is
        # nothing here to refuse. Widening this to `rglob` would refuse files the leg does not run,
        # which reports a narrowing that never happened. The COUPLING is the real content of this
        # note: if the runner's discovery ever goes recursive, THIS must follow in the same change,
        # or the two sets drift and a declared timing test silently re-enters the pinned leg.
        _lane_rels: list = []
        for _d in _pinned_sweep_dirs:
            try:
                _found = sorted(Path(_d).glob("test_*.py"))
            except OSError:
                continue                          # an unreadable sweep dir declares nothing here
            for _f in _found:
                try:
                    _lane_rels.append(_f.relative_to(pinned_wt).as_posix())
                except ValueError:
                    _lane_rels.append(_f.name)
        _lane_refused = _timing_lane_pin_refusals(
            _declared_ops, _lane_rels, _expand_declared_glob=_expand_declared_glob) or {}
        # T-12307 (SPEC-0077 §3) — TWO MORE REFUSAL SOURCES, computed at verify time from durable
        # state (the marker line the LAST-GREEN copy carries; this branch's own diff), never from a
        # hand list. They feed the SAME `only=` narrowing seam T-12039 established, through the SAME
        # `_timing_lane_pin_selection` — so the empty-selection fail-SAFE, the applied-vs-declared
        # accounting and the never-silent per-refusal line are REUSED, not re-implemented. Merged
        # into ONE refusal dict because the selection helper is already generic over one, and a
        # second selection pass over a second dict is exactly the drift T-12109 closed.
        # The CENSUS half is read from `pinned_wt` (a declaration must not be self-granted) and the
        # TOUCHED half from the candidate diff (a fact that lives nowhere else) — see each helper.
        # T-12313 — the COMPUTATION itself now lives in the module-level `pinned_leg_narrowing()`,
        # because a ROUTED land (SPEC-0203) never enters this function and so computed these two
        # exclusions NOWHERE. ONE computer, two drivers: this local one and the routed host-side
        # entry `routed_pinned_narrowing()` both call it, so the two paths cannot drift (which is
        # exactly what AC2's byte-identity asks of them). The FAIL-CLOSED handling stays HERE, at
        # the driver, because this is where the pinned-leg VERDICT is owned — the routed entry
        # fails SAFE instead, for the reason stated in its own docstring.
        try:
            _narrow_meta, _narrow_refused = pinned_leg_narrowing(
                W, merged_base, pinned_wt, _lane_rels, _run_git_cap=_run_git_cap)
        except Exception as e:
            # FAIL-CLOSED, like every other setup step in this function: a narrowing input we could
            # not resolve is a setup failure, never a silent skip (SPEC-0077 §3).
            return [f"{_PINNED_PREFIX}setup FAILED (resolve pinned-leg narrowing inputs): {e}"]
        # Merged INTO `_lane_refused` under its existing name, rather than beside it: that name is
        # what the per-refusal loop, the summary and the not-applied `elif` below all read, and
        # tests/test_t12039_timing_lane_declaration.py pins those three expressions by source. One
        # dict keeps the reporting and the selection describing the SAME set — two would be the
        # exact drift T-12109 closed.
        _lane_refused = {**_lane_refused, **_narrow_refused}
        _lane_only, _lane_applied, _lane_applied_names = _timing_lane_pin_selection(
            (Path(r).name for r in _lane_rels), only, _lane_refused)
        if _lane_applied:
            # Print the refusals this run ACTUALLY applied — a refused name outside the effective
            # selection was not going to run anyway, and reporting it would be noise the operator
            # cannot act on. T-12109: that set comes from the selection helper, which computes it
            # where SELECTED is defined; the former `set(_lane_refused) - set(_lane_only)` was an
            # approximation that over-reported on a mixed `only` selection.
            for _n in sorted(_lane_applied_names):
                print(f"land[pinned/last-green]: {_lane_refused[_n]}")
            only = _lane_only
            # T-12307 — NEVER SILENT, and never only on stdout: the skips this run APPLIED also reach
            # the caller's sink, which the land site writes to `land_completed.data.verify_metrics.
            # pinned_skipped`. Same pass-through-sink shape `excluded_out` already uses (T-12250): no
            # new store, no new event type, no second emit. Only `_lane_applied_names` — the set the
            # lines above print — so the row and the log can never describe two different narrowings.
            # The REL PATH, never the bare name: two swept dirs could in principle spell one basename,
            # and a report the operator cannot resolve to a file is not a report (audit-pre finding 1).
            if skipped_out is not None:
                skipped_out.extend(sorted(
                    ({"file": _narrow_meta[_n][0], "reason": _narrow_meta[_n][1]}
                     for _n in _lane_applied_names if _n in _narrow_meta),
                    key=lambda d: d["file"]))
            # T-12109 — the summary counts the refusals APPLIED (the same set the lines above print),
            # not every DECLARED match: on a mixed `only` selection the two differ and the summary
            # over-stated the narrowing (fu_192d51d8f5d0).
            # T-12109 (fu_192d51d8f5d0) — the summary counts the refusals APPLIED, taken from the
            # SAME `_lane_applied_names` the per-refusal lines above print, never `len(_lane_refused)`.
            # A declared name outside the effective selection narrowed nothing away, so counting it
            # showed the operator a LARGER narrowing than happened and contradicted those very lines.
            print(f"land[pinned/last-green]: pinned sweep narrowed to {len(only)} file(s) — "
                  f"{len(_lane_applied_names)} declared timing-sensitive and not waived, "
                  f"census-class, or touched by this branch — each named above. They still run in "
                  f"the candidate verify (SPEC-0160 rule 10, T-12039; SPEC-0077 §3, T-12307).")
        elif _lane_refused:
            print(f"land[pinned/last-green]: {len(_lane_refused)} pinned-leg refusal(s) matched "
                  f"(declared timing-sensitive, census-class, or touched by this branch), but the "
                  f"narrowing is NOT applied — it would leave the pinned selection EMPTY (which "
                  f"reads GREEN, silently disabling this leg) or it touches nothing this run was "
                  f"going to execute. The pinned leg runs UNCHANGED (SPEC-0160 rule 10, T-12039; "
                  f"SPEC-0077 §3, T-12307).")
        # Every pinned failure carries the `[pinned/last-green] ` prefix. Prefix AT SOURCE (each append/
        # extend), not once at the return: this is robust to a future early-`return bad` and makes the
        # contract locally obvious at each branch (audit-post — the prefix must never be droppable). The
        # early setup-failure returns above prefix inline for the same reason.
        pfx = "[pinned/last-green] "
        # ENGINE checks with the LAST-GREEN verifier LOGIC + RUNNER (SPEC-0077 §1/§3), SUBPROCESS-ISOLATED
        # against the materialized merged_base bin/ tree (T-9348). merged_base lacking bin/yitc-v2 (a -C
        # consumer / test repo) → the current in-process runner (the consumer-immutable pinned engine, §6b).
        try:
            pinned_root = _materialize_pinned_engine_bin(W, merged_base)
        except Exception as e:
            return [f"{pfx}setup FAILED (could not materialize last-green engine verifier): {e}"]
        # SPEC-0132 Rule 1 (T-10074): the pinned re-run runs its worker-spawning tests INSIDE the SAME
        # verify-admission slot the candidate verify uses (audit-pre P2-F2 — else the pinned run would
        # spawn its own default-capped worker pool concurrently with peer lands, breaking the shared
        # bound). Candidate + pinned run SEQUENTIALLY within a land, so a land holds ≤ 1 slot at a time.
        # `admission_slots is None` (a direct/test caller that did not opt in) → nullcontext, byte-identical.
        # T-10972: the pinned re-run takes its OWN slot sequentially, so its queue time is part of the
        # same land's wall — it appends into the SAME per-attempt accumulator as the candidate verify.
        _adm = (_verify_admission(main_wt, admission_slots, wait_out=admission_wait_out)
                if admission_slots is not None else contextlib.nullcontext())
        with _adm:
            if pinned_root is None:
                # §6b consumer/test-repo: the current in-process runner IS the consumer-immutable pinned engine.
                # T-10438: the SAME tests-sweep delegation as the candidate verify — evaluated on pinned_wt,
                # whose tests/ + yitc-ops.yaml are the LAST-GREEN overlay. Required for coherence, not an
                # extra: the pinned re-run fires exactly when the diff touches tests/** or yitc-ops.yaml
                # (_VERIFY_IMPLEMENTATION_GLOBS), i.e. on precisely the change a delegating consumer makes
                # most — un-delegated here, the rule would collapse for its own test edits. The last-green
                # layers still run over the candidate tree below, so SPEC-0077's old-checks-over-new-subject
                # intent holds.
                # T-10811 (X-0657): when the LAST-GREEN carrier does not itself delegate, read the
                # delegation ROUTING from the CANDIDATE carrier (W) — honoured only for a layer the
                # pinned carrier will actually RUN, so a candidate that delegates away to nothing still
                # falls through to the sweep and ABORTs. The pinned CHECKS stay last-green either way.
                _pdeleg = (_consumer_tests_delegation(pinned_wt) if _consumer_tests_delegation is not None else None)
                _routed = None
                if _pdeleg is None and _consumer_tests_delegation is not None:
                    _routed = _consumer_tests_delegation(pinned_wt, routing_from=W)
                if _pdeleg or _routed:
                    # T-11073 (X-0860): same trust-boundary + registry-gap report as the candidate site.
                    # The gap is read from `pinned_wt` — the tree whose tests/ this delegation skips and
                    # whose layers this path runs. Report-only; the pinned verdict is unchanged.
                    print(_render_tests_delegation_note(
                        _pdeleg or _routed,
                        "land[pinned/last-green]" if _pdeleg else
                        "land[pinned/last-green; ROUTING read from the CANDIDATE carrier, layer runs "
                        "in last-green — T-10811]",
                        _delegated_tests_execution_gap(pinned_wt, _pdeleg or _routed)
                        if _delegated_tests_execution_gap is not None else None))
                else:
                    # T-10977: `fail_fast=False` — the pinned failing set is what the per-assertion
                    # `--rebaseline-waive` declaration is matched against token-by-token, so it must be
                    # COMPLETE and STABLE, not a run-varying fail-fast subset. (The candidate verify in
                    # `_land_integrate` keeps the default fast abort — it is judged as a verdict, not
                    # matched as a set.)
                    bad.extend(f"{pfx}{b}" for b in _run_verify_tests(_pinned_sweep_dirs, pinned_wt, workers=workers, journal_path=main_wt / "events.jsonl", fail_fast=False, land_verify=True, only=only))   # T-11456: the pinned re-run is PART OF the land — NORMAL priority, same as the sweep above (T-11479: `only` is None on every land path). T-11204: the sweep dirs come from the LAST-GREEN carrier (`_pinned_sweep_dirs`), never the literal `tests`
            else:
                # Run merged_base's `_run_verify_tests` in a FRESH interpreter whose sys.path[0] is the
                # materialized merged_base bin/ (clean sys.modules → merged_base lib.*). The bad-list returns via
                # a DEDICATED RESULT FILE — NOT stdout (the verifier + its test subprocesses write to stdout/
                # stderr freely, so stdout is not a clean channel — audit-pre F1). FAIL-CLOSED on any anomaly.
                # T-10074: the admitted cap `workers` is passed as the 6th argv (backward-compatible None).
                driver = pinned_root / "_pinned_driver.py"
                driver.write_text(_PINNED_VERIFY_DRIVER, encoding="utf-8")
                result = pinned_root / "_pinned_result.json"
                proc = subprocess.run(
                    # T-11204 (SPEC-0185 §1(a)): argv[2] is the COMMA-JOINED sweep-dir list resolved
                    # from the LAST-GREEN carrier, not the root literal. Comma-joined rather than a
                    # widened runner parameter because the driver calls the LAST-GREEN
                    # `_run_verify_tests`, which takes one directory — the driver LOOPS it (same
                    # capability discipline as the `workers` / `fail_fast` / `only` argv). For the
                    # one-directory case every project has today this is byte-identical.
                    [sys.executable, str(driver), str(pinned_root / "bin"),
                     ",".join(str(d) for d in _pinned_sweep_dirs),
                     str(pinned_wt), str(main_wt / "events.jsonl"), str(result), str(workers),
                     # T-11479: OPTIONAL 7th argv = the file selection, comma-joined. Absent / "None"
                     # → today's whole-directory sweep, so every existing land path is unchanged.
                     (",".join(sorted(only)) if only else "None")],
                    capture_output=True, text=True,
                    env=_pinned_verify_subprocess_env(SUBENV_SCRUB_CARRIERS))
                if proc.returncode != 0:
                    bad.append(f"{pfx}pinned-engine subprocess FAILED (exit {proc.returncode}): "
                               f"{(proc.stderr or proc.stdout or '')[-2000:]}")
                elif not result.exists():
                    bad.append(f"{pfx}pinned-engine subprocess produced no result file (fail-closed)")
                else:
                    try:
                        bad.extend(f"{pfx}{b}" for b in json.loads(result.read_text(encoding="utf-8")))
                    except Exception as e:
                        bad.append(f"{pfx}pinned-engine result unreadable (fail-closed): {e}")
            # CONSUMER contract: the engine binary running a -C verify is the consumer's PINNED engine
            # (consumer-immutable §6b), so the CURRENT module's guard IS the pinned verifier; it runs the
            # OVERLAID (last-green) yitc-ops.yaml `verify.layers` over the candidate subject (the migrated
            # verify home, SPEC-0152 rule 16 / T-9719). Inert on the engine's own land.
            bad.extend(f"{pfx}{b}" for b in _consumer_zero_probe_guard(pinned_wt)["bad"])
        return bad
    finally:
        # CLEANUP (audit-F3) — `worktree remove --force` already deletes the dir; prune the registration,
        # then rmtree only if anything survives. Every call is non-raising, so `finally` never converts a
        # successful pinned verdict into a false abort. The materialized pinned engine root is a plain temp
        # dir — rmtree it too.
        _run_git_cap(["worktree", "remove", "--force", str(pinned_wt)], W)
        _run_git_cap(["worktree", "prune"], W)
        if pinned_wt.exists():
            shutil.rmtree(pinned_wt, ignore_errors=True)
        if pinned_root is not None:
            shutil.rmtree(pinned_root, ignore_errors=True)

def _closure_blob(path: str, W: "Path", rev: str, _run_git_cap, _blobs) -> "str | None":
    """ONE fetch seam for the two closure shape checks (T-11503). With no reader this is the literal
    `git show` both checks did before; with one it is the memoized read. Kept as a function rather
    than duplicated at four call sites so the two checks cannot drift into reading blobs differently."""
    if _blobs is not None:
        return _blobs.read(rev, path)
    r = _run_git_cap(["show", f"{rev}:{path}"], W)
    return (r.stdout or "") if r.returncode == 0 else None

def _closure_spec_status_flip(path: str, W: Path, audit_commit: str, *, _run_git_cap, _blobs=None, _CLOSURE_SPEC_STATUS_RE=None, _CLOSURE_SPEC_TRANSITIONS=None, _closure_blob=None) -> "tuple | None":
    """AXIS (b) — EXACT DIFF SHAPE. Return `(old_status, new_status)` iff the ENTIRE change to `path`
    between `audit_commit` and HEAD is ONE `status:` line replaced by another AND that pair is in the
    closed `_CLOSURE_SPEC_TRANSITIONS` vocabulary; else `None`.

    Compares the two BLOBS line-by-line rather than parsing a unified diff. That is not a style choice:
    a unified diff's own `---`/`+++` headers are indistinguishable from a removed/added content line
    whose text is `--`/`++` (a YAML document separator is exactly that), so a textual diff parse could
    silently under-count the changed lines — i.e. read a two-line edit as the one-line flip. Reading the
    blobs has no such ambiguity, and it makes the added/deleted-file cases fall out for free (`git show`
    fails on the side where the file does not exist).

    Split on `\\n` rather than `splitlines()` so a trailing-newline change shows up as a length
    mismatch instead of vanishing. FAIL-CLOSED at every step — a non-zero git exit, a length mismatch,
    zero or >1 differing lines, an unparseable status line on either side, or a transition outside the
    closed set all return `None`, which means "not a closure side-effect" and leaves the path refused."""
    old = _closure_blob(path, W, audit_commit, _run_git_cap, _blobs)
    new = _closure_blob(path, W, "HEAD", _run_git_cap, _blobs)
    if old is None or new is None:
        return None
    old_lines, new_lines = old.split("\n"), new.split("\n")
    if len(old_lines) != len(new_lines):
        return None
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    if len(changed) != 1:
        return None
    mo = _CLOSURE_SPEC_STATUS_RE.match(old_lines[changed[0]])
    mn = _CLOSURE_SPEC_STATUS_RE.match(new_lines[changed[0]])
    if not mo or not mn:
        return None
    pair = (mo.group(1), mn.group(1))
    return pair if pair in _CLOSURE_SPEC_TRANSITIONS else None

def _closure_spec_binding_block(lines, *, _CLOSURE_SPEC_BINDING_KEY_RE=None, _CLOSURE_SPEC_TOPLEVEL_KEY_RE=None) -> set:
    """The line indices of the top-level `binding:` declaration in `lines` (empty when there is none).
    Runs from the `^binding:` line to the next line beginning at column 0, exclusive — so the key line,
    its list items, any comment indented under it and the blank lines inside it are all in the block,
    while the next top-level key is not. Only the FIRST `binding:` is taken: a second one is not a
    well-formed spec file, and treating it as a second block would widen what the caller admits."""
    out: set = set()
    start = next((i for i, ln in enumerate(lines) if _CLOSURE_SPEC_BINDING_KEY_RE.match(ln)), None)
    if start is None:
        return out
    out.add(start)
    for i in range(start + 1, len(lines)):
        if lines[i] and _CLOSURE_SPEC_TOPLEVEL_KEY_RE.match(lines[i]):
            break
        out.add(i)
    return out

def _closure_spec_binding_declaration(path: str, W: Path, audit_commit: str, *, _run_git_cap, _blobs=None, _CLOSURE_BINDING_STATUS_TRANSITION=None, _CLOSURE_SPEC_STATUS_RE=None, _closure_blob=None, _closure_spec_binding_block=None, state=None) -> bool:
    """T-11072 (X-0859) — AXIS (b) for the OTHER shape `task close` prescribes. True iff the ENTIRE change
    to `path` between `audit_commit` and HEAD is the top-level `binding:` declaration, optionally together
    with the single `status: proposed → active` flip of the same closure; False otherwise.

    WHY THIS SHAPE EXISTS AT ALL. `task close` does not only WRITE the activation flip — when the spec it
    just activated carries no valid `binding:` token it PRESCRIBES, in its own output, a `spec edit` to
    declare one and a pre-land `work commit` of that edit, and calls this «part of the ACCEPTED closure
    contract». That prescribed content is, by construction, content no audit saw, so the currency gate
    refused the very sequence closure printed (X-0859: the only exit was a full re-audit for a one-line
    residency token that changes no behaviour). This predicate is what stops the two rules contradicting
    each other — and NOTHING wider: the population it can admit is bounded by the caller's provenance
    axis to specs THIS close activated.

    TWO INDEPENDENT CONFINEMENT CHECKS, BOTH REQUIRED (a conjunction — `lessons/carving-an-exception-into-
    a-fail-closed-gate` §1: positive evidence on every axis, never an absence of objections):
      (i)  TEXTUAL — DELETE that side's `binding:` block and `status:` line from each blob; what remains
           must be BYTE-IDENTICAL, line for line, in order. Compares the two BLOBS rather than parsing a
           unified diff for the same reason `_closure_spec_status_flip` does (a diff's own `---`/`+++`
           headers are indistinguishable from content lines that read `--`/`++`). Deliberately NOT a
           `difflib` opcode-range test: declaring a binding CHANGES the line count, and a matcher is then
           free to pick any of several equivalent alignments — one of which sweeps an untouched
           neighbouring blank line into the changed range and refuses a clean edit. Removing the allowed
           regions and comparing the remainder asks the same question with no alignment to be wrong about.
      (ii) SEMANTIC — parsed as YAML, the keys whose values differ (plus any key present on only one side)
           are a SUBSET of {binding, status} and CONTAIN `binding`. The `contain` half is the positive
           evidence: a change that is confined to the block but does not actually change the declaration
           is not the prescribed edit. If `status` differs too, the pair must be exactly proposed→active.
    Each check is the other's belt: a mis-computed block range is caught by the key-level compare, and a
    change YAML cannot see (a comment inside the declaration) is still bounded by the textual range. A
    comment edit ELSEWHERE in the file is invisible to (ii) and caught by (i) — which is the whole reason
    both run.

    FAIL-CLOSED at every step: a non-zero git exit, an unreadable blob, a YAML parse failure, a non-mapping
    document, a change touching anything outside the two allowed regions, or an out-of-vocabulary status
    transition all return False, i.e. «not a closure side-effect», leaving the path refused exactly as
    today. There is no third value to route because here «did not answer» and «no» are the same answer."""
    old_text = _closure_blob(path, W, audit_commit, _run_git_cap, _blobs)
    new_text = _closure_blob(path, W, "HEAD", _run_git_cap, _blobs)
    if old_text is None or new_text is None:
        return False
    old_lines, new_lines = old_text.split("\n"), new_text.split("\n")
    allowed_old = _closure_spec_binding_block(old_lines)
    allowed_new = _closure_spec_binding_block(new_lines)
    if not allowed_new:
        return False                      # nothing was declared — there is no binding declaration to admit
    for idx, lines in ((allowed_old, old_lines), (allowed_new, new_lines)):
        st = next((i for i, ln in enumerate(lines) if _CLOSURE_SPEC_STATUS_RE.match(ln)), None)
        if st is not None:
            idx.add(st)
    if ([ln for i, ln in enumerate(old_lines) if i not in allowed_old]
            != [ln for i, ln in enumerate(new_lines) if i not in allowed_new]):
        return False
    try:
        import yaml  # noqa: F401  (state.load_str raises yaml errors; imported for the except clause)
        old_rec, new_rec = state.load_str(old_text), state.load_str(new_text)
    except Exception:
        return False
    if not isinstance(old_rec, dict) or not isinstance(new_rec, dict):
        return False
    _MISSING = object()
    differing = {k for k in set(old_rec) | set(new_rec)
                 if old_rec.get(k, _MISSING) != new_rec.get(k, _MISSING)}
    if "binding" not in differing or differing - {"binding", "status"}:
        return False
    if "status" in differing:
        pair = (old_rec.get("status"), new_rec.get("status"))
        if pair != _CLOSURE_BINDING_STATUS_TRANSITION:
            return False
    return True

def _governed_closure_side_effects(paths, W: Path, audit_commit: "str | None", tid: "str | None", *,
                                   _run_git_cap, EVENTS_PATH, _blobs=None, _CLOSURE_LESSON_NOTE_RE=None, _CLOSURE_SPEC_PATH_RE=None, _ClosureBlobReader=None, _closure_spec_binding_declaration=None, _closure_spec_status_flip=None, _read_land_events=None) -> set:
    """T-10998 — the SUBSET of `paths` PROVEN to be exact deterministic governed closure side-effects,
    i.e. post-audit writes the lifecycle itself REQUIRES and that therefore do not stale the audit.
    Everything else is absent from the subset and stays refused exactly as today.

    Returns a SUBSET, never a verdict — which is what makes the whole extension fail-closed by
    CONSTRUCTION: an empty return reproduces the pre-change behaviour byte-for-byte, so every failure
    mode of this helper (a broken git, an unreadable journal, an unrecognised shape) degrades to the
    old refusal rather than to an admission. There is no reserved "did not answer" value to route,
    because "did not answer" and "no" are the same value here
    (`lessons/carving-an-exception-into-a-fail-closed-gate` §1).

    THE THREE AXES — a CONJUNCTION, positive evidence required on each; no axis is an absence of
    objections and none is sufficient alone:
      (a) PATH CLASS.
          - `lessons/<slug>.md` → exempt on path class ALONE. This is T-9526's own reasoning, unchanged
            and now applied SYMMETRICALLY: a lesson is a flat local-craft NOTE (SPEC-0090), never
            executable or behavioural, so it cannot stale a CODE audit — while the verify still runs
            the full suite over HEAD, so exempting it here skips no verification. What T-9526 got wrong
            was not the reasoning but its SCOPE: it lived only on the post-close `scoped=False` path,
            so the identical note on an ordinary task branch still refused. That asymmetry is the
            carveout this card RETIRES; the reasoning survives it.
          - `specs/SPEC-NNNN[-slug].yaml` → a CANDIDATE only; it must still clear (b) and (c).
          - anything else → not exempt, full stop.
      (b) EXACT DIFF SHAPE — ONE of the TWO shapes `task close` itself produces or prescribes, each
          measured over the WHOLE change to the file against the audited commit:
            - `_closure_spec_status_flip` — the single `status:` line moving along a closed vocabulary
              (the flip close WRITES). A body edit, a second changed line, an added/deleted file or any
              git failure fails here.
            - `_closure_spec_binding_declaration` (T-11072 / X-0859) — the top-level `binding:`
              declaration, optionally with the same closure's proposed→active flip (the token close
              PRESCRIBES, then tells the author to `work commit` PRE-LAND as part of the accepted closure
              contract). Anything riding along with it fails, on either the textual or the semantic
              confinement check.
      (c) GOVERNED-VERB PROVENANCE — a `spec_activated` row (SPEC-0161) in THIS task's id slot naming
          THIS spec: `data.spec_id` for the `→ active` flip AND for the T-11072 binding declaration
          (which is prescribed only for the spec this close ACTIVATED, so the target route below is
          deliberately unreachable for it), or `data.supersedes` + a matching
          `data.supersedes_status` for the target flip. That row is emitted by ONE writer reached from
          ONE verb (`task close`), so it attests the flip came from the governed closure and not from a
          hand-edit — but ONLY ever as the LAST conjunct. A hand-emitted row cannot admit a path whose
          shape failed (b), and a genuine flip whose row is missing is refused: provenance confirms an
          already-mechanically-proven shape, it never grants trust on its own."""
    out: set = set()
    if not paths or not audit_commit:
        return out
    candidates = {}
    for raw in paths:
        p = str(raw).strip()
        if p.startswith("./"):
            p = p[2:]
        if _CLOSURE_LESSON_NOTE_RE.match(p):
            out.add(raw)                       # axis (a) alone — the T-9526 reasoning, made symmetric
            continue
        m = _CLOSURE_SPEC_PATH_RE.match(p)
        if m and tid:
            candidates[raw] = (p, m.group(1))
    if not candidates:
        return out
    # T-11503 — ONE reader for this whole call. A caller that walks MANY audit commits passes its own
    # (so the `HEAD:` side is read once for the whole walk, not once per candidate); a caller that does
    # not still gets the within-call wins, because the binding check below re-reads exactly the two
    # blobs the status-flip check above already fetched. The prefetch resolves both sides of the
    # candidate set in two `cat-file --batch` calls instead of one `show` per (rev, path) — and on the
    # multi-candidate walk the HEAD half is already cached, so it costs one. Best-effort throughout: a
    # failed prefetch just leaves `read` to fall back to `show`.
    if _blobs is None:
        _blobs = _ClosureBlobReader(W, _run_git_cap=_run_git_cap)
    _cand_paths = [p for (p, _sid) in candidates.values()]
    _blobs.prefetch(audit_commit, _cand_paths)
    _blobs.prefetch("HEAD", _cand_paths)
    shaped = {}
    for raw, (p, sid) in candidates.items():
        pair = _closure_spec_status_flip(p, W, audit_commit,
                                         _run_git_cap=_run_git_cap, _blobs=_blobs)         # axis (b)
        if pair is not None:
            shaped[raw] = (sid, pair[1], False)
        elif _closure_spec_binding_declaration(p, W, audit_commit,
                                               _run_git_cap=_run_git_cap, _blobs=_blobs):
            # T-11072 — the OTHER shape the SAME closure prescribes (its `binding:` declaration, X-0859).
            # Recorded as a distinct shape rather than folded into the status vocabulary because it earns
            # its admission through the STRICTER provenance branch below: only a spec THIS close ACTIVATED
            # can carry a prescribed binding token, so the `supersedes:`-target route is unreachable here.
            shaped[raw] = (sid, "active", True)
    if not shaped:
        return out
    activated: set = set()
    superseded: set = set()
    try:                                                                                  # axis (c)
        for e in _read_land_events(EVENTS_PATH):
            if e.get("type") != "spec_activated" or e.get("task_id") != tid:
                continue
            d = e.get("data") or {}
            if d.get("spec_id"):
                activated.add(str(d["spec_id"]))
            if d.get("supersedes"):
                superseded.add((str(d["supersedes"]), str(d.get("supersedes_status") or "")))
    except Exception:
        return out             # no readable journal ⇒ no provenance ⇒ nothing spec-shaped is exempted
    for raw, (sid, new_status, is_binding) in shaped.items():
        if is_binding:
            proven = sid in activated                        # T-11072 — the activation this close performed,
                                                             # and ONLY that: a binding declaration on a spec
                                                             # this close did not activate is not prescribed
                                                             # by anything, so it stays refused.
        elif new_status == "active":
            proven = sid in activated                        # the activation this close performed
        else:
            proven = (sid, new_status) in superseded         # the target flip it performed with it
        if proven:
            out.add(raw)
    return out

def _observable_subtree_oids(revs, W: Path, *, _run_git_cap, _REBASELINE_PREFILTER_SUBTREES=None) -> "dict | None":
    """T-11505 — resolve the `bin` + `tests` SUBTREE OIDs for MANY revisions in ONE git subprocess.

    Returns `{rev: (bin_oid_or_None, tests_oid_or_None)}` — `None` for a path absent from that tree —
    or **`None` for the WHOLE call** on any failure, which the caller reads as "no prefilter available"
    and falls back to the unfiltered walk.

    WHY ONE CALL. The caller's cost is one git subprocess PER historical audit candidate, and the
    candidate set grows with history and does not decay (~+900/month, measured 2026-08-24). A per-rev
    `ls-tree` would be flat-per-rev but still O(N) processes; `cat-file --batch-check` answers the
    whole list from STDIN in a single process, so the walk's subprocess count stops growing with the
    length of the journal. That STDIN query list is why `_run_git_cap` needed its `input=` seam.

    WHY A DIFFERING SUBTREE OID IS A PROOF, NOT A HEURISTIC. Git is content-addressed: two trees have
    the same OID iff their entire recursive content is identical. So a candidate whose `bin` (or
    `tests`) subtree OID differs from HEAD's necessarily has at least one changed path under that
    prefix; that path is OBSERVABLE and — per `_REBASELINE_PREFILTER_SUBTREES` above — provably not
    exemptible, so the candidate CANNOT be inert and the caller may reject it without any diff. This
    is exact equality, not an approximation, and it is ONE-SIDED by construction: differing proves
    NOT-inert, while EQUAL proves nothing and falls through to the real `_delta_inert` diff (a
    candidate differing only in `specs/`, `patterns/` or a root `*.md` can still legitimately qualify
    via the closure-side-effect subtraction, and must still be asked properly).

    Contrast with the bound this DELIBERATELY is not: bounding the walk by POSITION in history is not
    verdict-exact, because a tree diff is not monotone in history distance — a path changed and later
    changed BACK does not appear in the older candidate's diff — so a position bound can refuse a
    rebaseline that legitimately succeeds today. The same non-monotonicity rules out deriving the
    filter from `git rev-list -- bin tests`. Tree-OID equality has no such failure mode.

    FAIL-SAFE, not fail-closed — and the distinction matters: this helper never decides a verdict, it
    only removes candidates the caller would have rejected anyway, so losing it costs speed and can
    never change an answer. Hence a broad `return None` on every failure shape (nonzero rc, a
    truncated or over-long response, any exception) rather than a partial result the caller would have
    to reason about."""
    revs = list(dict.fromkeys(str(r) for r in revs if r))
    if not revs:
        return {}
    try:
        query = "".join(f"{r}:{sub}\n" for r in revs for sub in _REBASELINE_PREFILTER_SUBTREES)
        r = _run_git_cap(["cat-file", "--batch-check"], W, input=query)
        if r.returncode != 0:
            return None
        lines = (r.stdout or "").splitlines()
        width = len(_REBASELINE_PREFILTER_SUBTREES)
        if len(lines) != len(revs) * width:
            return None            # one line per query is the contract; anything else is unparseable
        out = {}
        for i, rev in enumerate(revs):
            entry = []
            for j in range(width):
                parts = lines[i * width + j].split()
                # `<oid> <type> <size>` for a resolved path; `<input> missing` (or `... ambiguous`)
                # otherwise — the failure shapes carry no oid, so they map to None.
                entry.append(parts[0] if len(parts) == 3 and parts[1] == "tree" else None)
            out[rev] = tuple(entry)
        return out
    except Exception:
        return None

def _change_is_audited(branch: str, W: Path, main_base: "str | None" = None, *, _run_git_cap, EVENTS_PATH, _classify_inert_paths, _read_land_events, _merged_tree_delta_paths, _concurrent_merge_churn_only=None, _ClosureBlobReader=None, _governed_closure_side_effects=None, _observable_subtree_oids=None) -> "tuple[bool, str | None, dict | None]":
    """T-9307 (SPEC-0077 §3a): is the change being landed AUDITED, tied to the CURRENT source tree?
    The eligibility gate for the owner-acked re-baseline path (a candidate-GREEN / pinned-RED audited
    behaviour change). Returns (audited, reason_if_not, honored) where honored={task,commit} names the
    GREEN/YELLOW audit-post being honored (None when not audited). Never raises (fail-closed).

    TASK branch (`task/T-NNNN`) — the precise per-task lookup (the audit-pre T-9307 MEDIUM tightening;
    task_id alone would let a STALE audit legitimize a later unaudited change):
      (a) the LATEST `audit_post_completed` for the branch's task is GREEN/YELLOW (journal-based, so it
          is archive-move-proof — the decisions/ YAML drains to decisions/archive/ at close);
      (b) that audit's recorded commit is an ANCESTOR of HEAD (the audit is on THIS branch's history);
      (c) no post-audit OBSERVABLE change to a file in the BRANCH'S NET FOOTPRINT vs main landed after
          the audit (T-9457 SCOPED staleness — see `_delta_inert(..., scoped=True)`). An observable change
          confined to files merged in UNRELATED from main no longer invalidates the audit.

    NON-task branch (`work/<slug>`) — the POST-CLOSE case (T-9368, X-0040). A DONE task cannot be
    claimed as a `task/T-NNNN` worktree, so the owner re-baselines from a `work/<slug>` branch. Rather
    than refuse (the deadlock that forced `--no-tests`), accept an ANCESTOR audit-post whose SOURCE
    delta to HEAD is EMPTY: scan all GREEN/YELLOW `audit_post_completed`, keep those whose commit is an
    ANCESTOR of HEAD AND whose delta `commit..HEAD` is INERT (the current source byte-equals that
    audited source — the audit genuinely covers it), and honor the MOST RECENT. None qualifying -> NOT
    audited, so a NON-empty source delta stays REFUSED (does not loosen the real audit requirement).

    `main_base` is the integration base (the merged `main` tip) the SCOPED task-branch check needs to
    derive the branch footprint; the work/<slug> path does not use it (scoped=False)."""
    # T-11503 — ONE blob reader for this ENTIRE pass. The `work/<slug>` leg below walks every
    # GREEN/YELLOW audit-post in the journal (~170 candidates), and each candidate asks the closure
    # shape checks for the SAME `HEAD:<spec>` blobs. Built here, the HEAD side of the walk is read
    # once in total rather than once per candidate — the single largest of the three multipliers the
    # card measured. The lifetime is exactly this call, which is read-only (no commit, no ref move,
    # no checkout), which is what makes caching under the unresolved name "HEAD" sound.
    _blobs = _ClosureBlobReader(W, _run_git_cap=_run_git_cap)

    def _delta_inert(commit, scoped=False, tid=None):
        """Did a post-audit OBSERVABLE source/test change land after the audit? -> (clean, why_observable).
        `commit` must already be an ANCESTOR of HEAD (callers verify). A git/diff failure is fail-closed
        -> NOT clean. Inlined here (NOT a module helper) so `_change_is_audited` stays the SINGLE land-side
        consumer of the SPEC-0064 inert authority (the T-0631 one-authority invariant — no new consumer).

        scoped=False (work/<slug> post-close path, T-9368): clean iff the WHOLE `commit..HEAD` delta is
        INERT (only closure bookkeeping — events/graph/tasks/decisions/plans/ideas/errors) ∪ the proven
        deterministic governed CLOSURE SIDE-EFFECTS (T-10998). ANY OTHER observable post-audit path
        (bin/tests/specs/patterns/root-md) -> NOT clean.

        T-10998 RETIREMENT: the closure-side-effect subtraction below REPLACES the T-9526
        `lessons/`-only filter that used to live on THIS leg alone. That carveout's reasoning was right
        and is preserved verbatim inside `_governed_closure_side_effects` axis (a); what is retired is
        its ASYMMETRY — the identical closure note on the scoped=True task branch still refused, and the
        spec activation flip `task close` writes by construction refused on BOTH. One rule now runs on
        both legs, so there is no path-specific carveout left to drift.

        scoped=True (task-branch path, T-9457): clean iff no observable post-audit path falls in the
        BRANCH'S NET FOOTPRINT vs main — `_merged_tree_delta_paths(W, main_base)` = every file whose HEAD
        content DIFFERS from the merged main tip. That footprint captures the task's whole multi-commit
        change, any post-audit branch edit/new file, AND conflict-resolution edits made in the merge
        commit; a file IDENTICAL to main (unrelated already-audited concurrent work that land's own
        update-from-main merged in) is NOT in it -> ignored (resolves the T-9445 rebaseline livelock).
        The SAFETY INVARIANT is preserved: a stale audit still cannot legitimize a later change to what
        the audit reviewed. FAIL-CLOSED: a missing `main_base` or any failure deriving the footprint keeps
        the original any-observable refusal (ambiguity never weakens the gate)."""
        d = _run_git_cap(["diff", "--name-only", commit, "HEAD"], W)
        if d.returncode != 0:
            return (False, f"could not diff {commit}..HEAD to check for post-audit changes")
        post_audit = [ln.strip() for ln in d.stdout.splitlines() if ln.strip()]
        pa_verdict, pa_cls = _classify_inert_paths(post_audit)
        if pa_verdict != "observable":
            return (True, None)
        # T-10998 — SUBTRACT the paths PROVEN to be exact deterministic governed closure side-effects,
        # then re-classify the REDUCED set through the ONE `_classify_inert_paths` authority. That
        # re-classify-a-reduced-set shape is exactly what T-9526's `lessons/` filter and the scoped=True
        # footprint filter below already do, so the T-0631 one-authority invariant is untouched: this
        # adds no second inert encoding, it only narrows what is handed to the one that exists. Applied
        # to BOTH legs (the retirement described in the docstring), and BEFORE the scoped=True footprint
        # filter — a closure side-effect must be gone before the footprint question is asked, or a path
        # that happens to sit outside the footprint would mask the ordering error rather than expose it.
        exempt = _governed_closure_side_effects(post_audit, W, commit, tid,
                                                _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH,
                                                _blobs=_blobs)
        if exempt:
            post_audit = [p for p in post_audit if p not in exempt]
            pa_verdict, pa_cls = _classify_inert_paths(post_audit)
            if pa_verdict != "observable":
                return (True, None)
        if not scoped:
            return (False, f"an OBSERVABLE change ({pa_cls}) landed AFTER the audit ({commit[:7]})")
        # SCOPED (T-9457): keep the refusal ONLY for observable changes inside the branch's footprint vs main.
        # T-10592 (SPEC-0124 concurrent-merge axis, PORTED to the LAND currency seam): before refusing on
        # footprint drift, consult the T-9543 CONCURRENT-MERGE-CHURN classifier. Under fleet load land's OWN
        # mandatory update-from-main fold merges already-landed-AND-audited sibling commits into the branch —
        # hot shared files (kernel-vs-self-manifest.md, bin/yitc-v2, graph artifacts) that the branch ALSO
        # touched land back in the footprint, so every post-audit re-audit is re-staled by the next sibling
        # land → the rebaseline-currency LIVELOCK (3 incidents 2026-07-16: T-10582 x2, T-10589 x1 with a 3x
        # repeated-abort halt; fp rebaseline-currency-livelock-hot-shared-file-2026-07-16). The audit side
        # ALREADY classifies this class (`_concurrent_merge_churn_only`, E-0041); reuse the SAME classifier
        # here. When HEAD is byte-identical to the clean re-merge of the audited commit with the merged main
        # snapshot except for inert bookkeeping, the drift is ENTIRELY merge-fold commits of already-landed
        # main history (each covered by its own task's land/audit) → the audit genuinely still covers the
        # branch's own diff. FAIL-CLOSED: any branch-OWN post-audit source edit makes HEAD differ from the
        # clean re-merge → the classifier returns False → refuse exactly as today (never widened past
        # churn-only merge-fold of already-landed history).
        if _concurrent_merge_churn_only is not None and _concurrent_merge_churn_only(commit, "HEAD", W, _classify_inert_paths):
            return (True, None)
        if not main_base:
            return (False, f"an OBSERVABLE change ({pa_cls}) landed AFTER the audit ({commit[:7]}); "
                           f"no integration base to scope it to the branch footprint (fail-closed)")
        try:
            footprint = set(_merged_tree_delta_paths(W, main_base))
        except Exception:
            return (False, f"an OBSERVABLE change ({pa_cls}) landed AFTER the audit ({commit[:7]}); "
                           f"could not derive the branch footprint vs main to scope it (fail-closed)")
        sv, sc = _classify_inert_paths([p for p in post_audit if p in footprint])
        if sv == "observable":
            return (False, f"an OBSERVABLE change ({sc}) to a file in the branch's audited footprint "
                           f"landed AFTER the audit ({commit[:7]})")
        return (True, None)

    m = re.fullmatch(r"task/(T-\d{4,})", branch or "")
    if not m:
        # POST-CLOSE work/<slug> case ONLY (audit-post T-9368 MEDIUM): scope the new scan to the `work/`
        # write-branch class (the sole non-task write branch, D-0037) — any OTHER branch keeps the
        # original fail-closed refusal so the gate is not widened beyond the intended post-close case.
        if not re.fullmatch(r"work/.+", branch or ""):
            return (False, "not a task/T-NNNN or work/<slug> branch — the re-baseline path is for "
                           "audited task behaviour changes", None)
        # accept an ancestor audit-post with an EMPTY source delta to HEAD.
        candidates = []   # (event_order_index, task, commit) for GREEN/YELLOW audits carrying a commit
        for i, e in enumerate(_read_land_events(EVENTS_PATH)):
            if e.get("type") != "audit_post_completed":
                continue
            d = e.get("data") or {}
            if d.get("verdict") in ("GREEN", "YELLOW") and d.get("commit"):
                candidates.append((i, e.get("task_id"), d.get("commit")))
        # T-11505 — BOUND THE WALK. Without this, a run where NOTHING qualifies pays one
        # `merge-base` AND one `git diff --name-only` per historical candidate, and the candidate set
        # grows with the journal forever (measured +900/month, never decaying) — an accumulating cost
        # nothing fails closed on, because the VERDICT stays correct while only the price rises.
        # Resolve every candidate's observable subtree OIDs against HEAD's in ONE subprocess, then
        # skip the candidates that provably cannot be inert. See `_observable_subtree_oids` for why a
        # differing subtree OID is a PROOF of non-inertness and why the filter is one-sided.
        # The surviving walk below is UNCHANGED — same reverse order, same first-inert-wins, same
        # `merge-base` ancestry precondition `_delta_inert` documents, same returned tuple.
        oids = _observable_subtree_oids(["HEAD"] + [c for _i, _t, c in candidates], W,
                                        _run_git_cap=_run_git_cap)
        head_oids = (oids or {}).get("HEAD")
        for _i, tid, commit in reversed(candidates):    # MOST RECENT qualifying wins
            if oids is not None and head_oids is not None and oids.get(commit) != head_oids:
                continue                     # an observable, never-exemptible subtree differs → not inert
            if _run_git_cap(["merge-base", "--is-ancestor", commit, "HEAD"], W).returncode != 0:
                continue
            inert, _why = _delta_inert(commit, tid=tid)
            if inert:
                return (True, None, {"task": tid, "commit": commit})
        return (False, "no GREEN/YELLOW audit-post with an EMPTY source delta to HEAD covers this "
                       "work/<slug> re-baseline — re-baseline waives the superseded old-behaviour check, "
                       "so the CURRENT source must be byte-identical to an ancestor audited tree (T-9368/X-0040)",
                None)
    tid = m.group(1)
    verdict, commit = None, None
    for e in _read_land_events(EVENTS_PATH):        # LAST wins (the most recent audit-post for the task)
        if e.get("type") == "audit_post_completed" and e.get("task_id") == tid:
            d = e.get("data") or {}
            verdict, commit = d.get("verdict"), d.get("commit")
    if verdict not in ("GREEN", "YELLOW"):
        return (False, f"no GREEN/YELLOW audit_post_completed in the journal for {tid} (latest verdict: {verdict!r})", None)
    if not commit:
        return (False, f"the audit_post_completed for {tid} carries no commit ref", None)
    if _run_git_cap(["merge-base", "--is-ancestor", commit, "HEAD"], W).returncode != 0:
        return (False, f"the audited commit {commit} is not an ancestor of HEAD — the audit is not on this branch", None)
    inert, why = _delta_inert(commit, scoped=True, tid=tid)
    if not inert:
        return (False, f"{why} — re-audit the current tree before re-baselining", None)
    return (True, None, {"task": tid, "commit": commit})

def _branch_task_status(W: Path, tid: str) -> "str | None":
    """The `status:` of `tid`'s card AS IT STANDS IN THE WORKTREE `W` (not on main).

    Deliberately a line regex rather than a YAML load: `_land_integrate` is not injected with a
    yaml reader, this reads ONE top-level scalar, and every failure mode must return None (the
    caller reads None as "not applicable" and behaves exactly as land does today). Adding a reader
    injection for one scalar would be more code for identical behaviour."""
    try:
        for p in sorted((W / "tasks").glob(f"{tid}-*.yaml")):
            m = re.search(r"^status:\s*(\S+)\s*$", p.read_text(encoding="utf-8", errors="replace"),
                          re.MULTILINE)
            if m:
                return m.group(1).strip().strip("\"'")
    except Exception:                    # noqa: BLE001 — unreadable card ⇒ not applicable, never a grant
        return None
    return None

def _latest_task_audit_post(tid: str, EVENTS_PATH, _read_land_events) -> "tuple[str | None, str | None]":
    """(verdict, commit) of the LAST `audit_post_completed` for `tid` — the SAME last-wins read
    `_change_is_audited`'s task-branch leg performs, so the two sites cannot disagree about which
    record is current. Returns (None, None) on any failure (the caller's fail-closed direction)."""
    verdict, commit = None, None
    try:
        for e in _read_land_events(EVENTS_PATH):
            if e.get("type") == "audit_post_completed" and e.get("task_id") == tid:
                d = e.get("data") or {}
                verdict, commit = d.get("verdict"), d.get("commit")
    except Exception:                    # noqa: BLE001
        return (None, None)
    return (verdict, commit)

# ── T-11718 (SPEC-0077 §3a × SPEC-0188 rule 1) — THE AUTHORIZATION PREDICATE AT LAND ENTRY ─────────
#
# MEASURED (T-11674's own journal rows, 2026-08-27): land attempt 1 queued at 16:11:04Z and waited
# 501s, its queue position reset, attempt 2 waited a further 200s, and the land then refused
# `rebaseline-unauthorized` at 16:25:04Z — 14.2 minutes of wall clock, of which NONE was verify. The
# T-10850 step-4a preflight had already moved this arm off the expensive path; what it did not move
# it off is the QUEUE. The predicate that decided the refusal is a pure journal read, so it consumes
# nothing the admission slot provides and its answer cannot change by waiting. The SPEC-0119
# abort-cost view counts the [authorization] arm 21x/7d and marks it GROWING.
#
# ONLY CLAUSE (a) MOVES, AND THAT IS THE WHOLE DESIGN. `_change_is_audited` answers four questions
# and only the first is invariant at entry: (a) is there a GREEN/YELLOW `audit_post_completed` for
# this task AT ALL; (b) is its commit an ancestor of HEAD; (c) is the post-audit delta inside the
# branch footprint inert — which needs `merged_base`, i.e. the tree AFTER step-2 merged main; and
# (d) T-11483's in-land re-audit, which can MINT a fresh GREEN row DURING the land. (b)/(c)/(d) read
# state that does not exist here or that the land itself produces, so they stay exactly where they
# are. `_change_is_audited` is NOT edited, NOT re-derived and remains the sole admitter.
#
# FAIL-OPEN ON EVERY INPUT THAT IS NOT PROVEN — a preflight whose job is to make a refusal CHEAPER
# must never be able to invent one. Every disarm below returns None, which is today's behaviour
# unchanged, and the late gate still refuses whatever it refuses today.
#
# NO NEW VOCABULARY: the EXISTING `rebaseline-unauthorized` class and the EXISTING `abort_preflight`
# row shape (T-10850) — which is also what keeps this cheap refusal exempt from the T-0655 streak.
#
# THE OTHER ARM IS UNTOUCHED, and that bound is load-bearing: the T-10754 [waive-coverage] refusal
# reads `pinned_bad` after the full pinned run, and nothing here runs before it or short-circuits it.
# Making that arm cheap is a different problem with a different answer (T-11479 moved the half that
# could move); short-circuiting it here would turn a real coverage check into an unrun one.


def _rebaseline_unaudited_refusal_text(branch: str, why: str) -> str:
    """The COMPLETE §3a unaudited-re-baseline refusal — the head line plus the BRANCH-KIND-AWARE
    recovery. ONE authority for the two placements that raise it (the T-11718 land-ENTRY preflight
    and the T-10850 step-4a preflight), so the operator's diagnosis is byte-identical wherever it is
    raised and neither site can be re-authored into drift (the T-10850 (iii) discipline, CHARTER §P5).

    Moved here VERBATIM from `bin/lib/worktree.py`'s step-4a site; the T-11255 branch-kind fork and
    the byte-identical TASK-branch text are carried unchanged."""
    if re.fullmatch(r"task/(T-\d{4,})", branch or ""):
        recovery = ("RECOVERY: run `audit post --task T-XXXX` over the current tree, then re-run "
                    "`land --rebaseline --rebaseline-reason '<why>'`. If the task is already "
                    "status:done (a post-close re-baseline), the ordinary audit-post refuses it — "
                    "use `audit post --reaudit-after-close --task T-XXXX` instead (X-0040/T-9412), "
                    "then re-run land --rebaseline.")
    else:
        recovery = ("RECOVERY (this is a `work/<slug>` batch, so the audit-post routes below do "
                    "NOT apply to it): a work batch carries FILINGS, not deliverables — it has no "
                    "task, so it can never earn the Stage-8 audit-post a re-baseline requires, and "
                    "no re-run of anything will change that. Two routes, in order:\n"
                    "  1. If this batch does NOT actually need a re-baseline, land it WITHOUT "
                    "`--rebaseline` — the flag is only for a pinned check your change deliberately "
                    "supersedes.\n"
                    "  2. Otherwise REFILE THE FIX AS A CARD: `yitc-v2 task file` it, land THIS "
                    "batch (the filing is its deliverable), then claim the card with `yitc-v2 "
                    "worktree new --task T-XXXX` and take the fix through the 9 stages. Its "
                    "audit-post is what authorizes the waive — this is the route, not a "
                    "workaround, and it is why the refusal above is correct.")
    return (f"land: --rebaseline REFUSED — {why}. Re-baseline waives the superseded "
            f"old-behaviour pinned check, so it requires a GREEN/YELLOW audit-post for this "
            f"branch's task covering the CURRENT tree (SPEC-0077 §3a / T-9307).\n" + recovery)


def _entry_provable_verify_footprint(W: Path, *, _run_git_cap) -> "list[str] | None":
    """A PROVABLE SUBSET of the post-merge branch footprint, computed pre-merge. `None` = could not
    prove one (every caller disarms on it).

    WHY A SUBSET AND NOT THE FOOTPRINT ITSELF. The step-4a gate is scoped by `_verify_path_touch`
    over `_merged_tree_delta_paths(W, merged_base)` — the paths whose HEAD content differs from the
    MERGED main tip. That tree does not exist at entry, and the obvious pre-merge stand-in (HEAD vs
    main's tip) is a SUPERSET: it also contains every file main moved that this branch has not
    merged yet, so arming on it would refuse lands the late gate admits. Wrong direction.

    So: take the branch's OWN delta since the merge-base, and SUBTRACT every path main moved since
    that same base. For a path in the remainder, main's content IS the merge-base content and the
    branch's differs from it, so after the merge the branch's content still differs from main's —
    the path is in the post-merge footprint by construction. Conflict-resolution edits and paths
    both sides touched are simply excluded, which only ever makes this arm quieter.

    Any git failure returns None. This never widens the population the late gate judges."""
    try:
        mb = _run_git_cap(["merge-base", "main", "HEAD"], W)
        if getattr(mb, "returncode", 1) != 0 or not mb.stdout.strip():
            return None
        base = mb.stdout.strip()
        mine = _run_git_cap(["diff", "--name-only", base, "HEAD"], W)
        theirs = _run_git_cap(["diff", "--name-only", base, "main"], W)
        if mine.returncode != 0 or theirs.returncode != 0:
            return None
        moved = {ln.strip() for ln in theirs.stdout.splitlines() if ln.strip()}
        return [ln.strip() for ln in mine.stdout.splitlines() if ln.strip() and ln.strip() not in moved]
    except Exception:                    # noqa: BLE001 — an unreadable tree proves nothing
        return None


def _land_entry_authorization_refusal(branch: str, W: Path, main_wt, *, _run_git_cap, EVENTS_PATH,
                                      _read_land_events, _latest_task_audit_post, _branch_task_status,
                                      _declared_check_surface_touch, _is_verify_implementation_touch=None,
                                      _verify_policy_pinned_last_green=None,
                                      _ops_contract=None) -> "str | None":
    """The `_change_is_audited` clause (a) verdict, PROVED AT LAND ENTRY. Returns the `why` string
    for `_rebaseline_unaudited_refusal_text` when — and ONLY when — the refusal is already fixed and
    cannot change for the rest of this land; None ADMITS (today's behaviour, unchanged).

    Called only with `--rebaseline` given and tests enabled. The four disarms, each of which exists
    because the answer is NOT yet fixed there:

      `work/<slug>`  — judged by a DIFFERENT leg of `_change_is_audited` that scans EVERY audit-post
                       in the journal for an ancestor with an empty source delta, so
                       absence-for-this-task is not its predicate at all.
      `status: done` — T-11483's in-land re-audit runs `audit post --reaudit-after-close` exactly
                       there and can mint the GREEN row this predicate is looking for, MID-LAND.
      policy `never` — that state earns `rebaseline-policy-off`, a DIFFERENT class raised by its own
                       P0 arm; this must not pre-empt it with the wrong diagnosis.
      no proven verify touch — the late gate is scoped by `_verify_path_touch`; entry can only prove
                       a SUBSET of it (see `_entry_provable_verify_footprint`), so an unproven touch
                       falls through rather than guessing. The DECLARED surface is read from `main`,
                       never from HEAD, for the SPEC-0186 rule 4 reason: a diff must not get to
                       widen or narrow the surface that judges it.

    The `why` is derived from `_latest_task_audit_post`, the SAME last-wins read the task leg of
    `_change_is_audited` performs, so the two sites cannot disagree about which record is current or
    describe it differently. Never raises: any exception ADMITS."""
    try:
        m = re.fullmatch(r"task/(T-\d{4,})", branch or "")
        if not m:
            return None
        tid = m.group(1)
        if _branch_task_status(W, tid) == "done":
            return None
        verdict, _commit = _latest_task_audit_post(tid, EVENTS_PATH, _read_land_events)
        if verdict in ("GREEN", "YELLOW"):
            return None                  # clause (a) satisfied — (b)/(c) are the late gate's to judge
        if _verify_policy_pinned_last_green is not None and main_wt is not None:
            if _verify_policy_pinned_last_green(Path(main_wt), ops_contract=_ops_contract) == "never":
                return None
        if _is_verify_implementation_touch is None:
            # The host did not hand the globs-bound predicate down (a caller assembled before
            # T-11718's inject seam existed). The touch is then UNPROVEN, so this admits — the same
            # direction every other disarm takes.
            return None
        paths = _entry_provable_verify_footprint(W, _run_git_cap=_run_git_cap)
        if not paths:
            return None
        if not (_is_verify_implementation_touch(paths)
                or _declared_check_surface_touch(paths, W, "main", _run_git_cap=_run_git_cap)):
            return None
        return f"no GREEN/YELLOW audit_post_completed in the journal for {tid} (latest verdict: {verdict!r})"
    except Exception:                    # noqa: BLE001 — never raise into the land; never refuse on a guess
        return None


def _land_inland_reaudit(branch: str, W: Path, *, _run_git_cap, EVENTS_PATH, _classify_inert_paths,
                         _read_land_events, _inland_audit_post, _branch_task_status=None, _latest_task_audit_post=None,
                         _minted_out=None, _at_post_ceiling=None, _on_decisions_admission=None) -> dict:
    """Take the rebaseline audit-post INSIDE the land, over the MERGED tree. Returns a record dict
    carrying `outcome`, one of a CLOSED five-value vocabulary — and NOTHING else decides anything:

      `not-applicable` — not a `task/T-NNNN` branch, or the branch card is not `status: done`.
                         `--reaudit-after-close` requires a done card (bin/lib/audit.py §5608) and
                         it is the only audit-post form that targets HEAD by construction AND
                         self-commits its verdict YAML (T-10724/E-0056), which is what keeps the
                         worktree land-clean mid-land. A live in-progress card keeps today's
                         behaviour byte-identical, which is a refusal it already earns.
      `covered`        — the latest GREEN/YELLOW audit-post is an ANCESTOR of HEAD and its delta to
                         HEAD is entirely INERT through the one `_classify_inert_paths` authority.
                         That is TREE-LEVEL proof the record already IS an audit of the merged tree,
                         so re-running the auditor would re-read the same source and cost a pass for
                         nothing. NOTE WHAT THIS IS NOT: it is not "the drift looks benign" — the
                         thing AC2 forbids — it is "there is no source drift at all". This is the
                         STRICT unscoped leg: no footprint scoping, no churn carve-out, no waiver.
      `reaudited`      — the auditor RAN over the merged tree and a NEW `audit_post_completed` row
                         for this task appeared. Its VERDICT is not read here: a RED one falls
                         through to the gate and is refused exactly as before.
      `could-not-run`  — the invocation produced no new row. The caller composes its OWN complete
                         refusal from this; it is never a grant.
      `ceiling-refused`— (T-12320) the stage is AT or PAST the SPEC-0124 ceiling and the SPEC-0204
                         rule-3 admission REFUSED the one bounded pass. NO auditor was invoked and NO
                         pass was spent: this returns strictly before the `n_before` count and the
                         `_inland_audit_post` call. `rec["on_decisions"]` carries the ladder's own
                         refusal verbatim and the caller composes its OWN complete refusal from it.
                         IT IS NOT `could-not-run`, and folding the two would be a real defect rather
                         than an untidiness (`lessons/carving-an-exception-into-a-fail-closed-gate`
                         §2): `could-not-run` establishes «no verdict was recorded at all», whose
                         remedy is to re-run the auditor — which is EXACTLY the command this ladder
                         just refused. The remedy here is `audit decide`.

    THE DISCRIMINATOR IS THE JOURNAL ROW, NEVER THE EXIT CODE, and that is the whole safety
    argument (`lessons/carving-an-exception-into-a-fail-closed-gate` §1 — "what does the runner
    return when MY OWN plumbing is broken?"). `verdict_exit_code` maps YELLOW to 1 and `_die` also
    exits 1, so rc cannot separate a verdict from a refusal; a two-valued reading of it would make
    an auditor that failed to start indistinguishable from one that returned YELLOW. So the run's
    rc is recorded and NOT acted on, and what proves the audit happened is a new row keyed on this
    task that was not in the journal before the invocation.

    Every exception returns `could-not-run` (fail-closed). This function takes no admission
    decision, so there is no path through it that can widen the gate.

    `rec["reaudit_subject"]` (T-12370) — the commit the verdict was OFFERED to be recorded at (the
    branch tip this land merged), or None when it could not be resolved and the route records at
    HEAD as before. REPORTING ONLY: no outcome, no gate and no admission reads it, and the VERB
    re-derives its own ancestor + inert-delta guard over whatever is offered.

    `_minted_out` (T-12235 AC1) — the OPTIONAL rollback-identity handshake list. `audit post
    --reaudit-after-close` SELF-COMMITS its verdict YAML (T-10724/E-0056 — that self-commit is what
    keeps the worktree land-clean mid-land), so an in-land re-audit leaves a commit on the branch
    that THIS land caused. `_land_rollback_bookkeeping_to_entry` decides eligibility BY IDENTITY —
    a commit it cannot recognise is `skipped`, LOUD, branch untouched — and it recognises a minted
    sha only if someone RECORDED it. Nobody did, so on an abort the branch stayed above its entry
    sha and the printed remedy (`reset --mixed`) was the WRONG one: it also discards the catch-up
    merges. Recording the shas here is what lets the rollback return `restored` instead.

    RECORDING ONLY, in the reporting direction only. An unreadable HEAD or a failed walk records
    NOTHING, which leaves the rollback behaving exactly as it does today; an un-injected caller is
    byte-identical to today; and no outcome, no gate and no admission decision reads this list.

    WHAT THE RANGE RESTS ON, stated rather than assumed (audit-post YELLOW, absorbed mode-a
    2026-09-08). The range is `<head read HERE, before the invocation>..<head read HERE, after it>`,
    and the claim that everything in it is a commit THIS land caused is NOT proven by the two reads
    alone — it is EXCLUSIVITY: `W` is the land's own `task/T-NNNN` worktree, one worktree is one
    task's writer (D-0037/D-0083, which is why the per-write worktree is mandatory), and
    `_inland_audit_post` is a BLOCKING call, so nothing else in this process touches the branch
    between the reads. Where that assumption would matter most it is also not the last line of
    defence: a mis-recorded sha does not authorise a discard on its own, because
    `_land_rollback_bookkeeping_to_entry` still resets ONLY to an entry sha that is an ancestor of
    HEAD and still consults its own topological guards. The narrower alternative — record only the
    shas the re-audit operation itself returns — is not available: the injected runner returns an
    exit code, and reading identity off a commit's SUBJECT is exactly what T-11467 refuses."""
    rec = {"outcome": "not-applicable", "task": None, "prior_audit_commit": None,
           "prior_verdict": None, "drift_paths": [], "audit_commit": None, "rc": None}
    try:
        m = re.fullmatch(r"task/(T-\d{4,})", branch or "")
        if not m:
            return rec                   # a work/<slug> batch has no task and can never earn one
        tid = m.group(1)
        rec["task"] = tid
        if _branch_task_status(W, tid) != "done":
            return rec
        verdict, commit = _latest_task_audit_post(tid, EVENTS_PATH, _read_land_events)
        rec["prior_audit_commit"], rec["prior_verdict"] = commit, verdict
        if verdict in ("GREEN", "YELLOW") and commit:
            anc = _run_git_cap(["merge-base", "--is-ancestor", commit, "HEAD"], W)
            if getattr(anc, "returncode", 1) == 0:
                d = _run_git_cap(["diff", "--name-only", commit, "HEAD"], W)
                if d.returncode != 0:
                    # UNDETERMINABLE, not clean. The delta could not be read, so nothing is proven
                    # about what the record covers — fail closed rather than re-audit on a guess.
                    rec["outcome"] = "could-not-run"
                    return rec
                delta = [ln.strip() for ln in d.stdout.splitlines() if ln.strip()]
                dv, dcls = _classify_inert_paths(delta)
                if dv != "observable":
                    rec["outcome"] = "covered"
                    return rec
                rec["drift_paths"] = delta
                rec["drift_class"] = dcls
        # T-12320 — SPEC-0204 rule 3, consulted at the ONE point it can matter: the record does not
        # cover the merged tree, so a pass is about to be taken, and if the stage is at/past the
        # SPEC-0124 ceiling the ORDINARY `audit post` below would be refused BY the ceiling with no
        # way forward. The two injected callables are deliberately SEPARATE rather than one gate:
        # `_at_post_ceiling` is the ONLY consult trigger, so BELOW the ceiling the admission is never
        # called at all and that leg stays byte-identical (provably — the injected admission records
        # zero calls). An UN-INJECTED caller is byte-identical too, which is what keeps every existing
        # seam working unchanged.
        _on_decisions = False
        if _at_post_ceiling is not None and _on_decisions_admission is not None \
                and _at_post_ceiling(tid):
            _od = _on_decisions_admission(tid)
            rec["on_decisions"] = _od
            if not (isinstance(_od, dict) and _od.get("admitted")):
                # Refused BEFORE any auditor invocation and before the pass accounting below — the
                # whole point of asking here rather than letting the subprocess's ceiling refuse.
                rec["outcome"] = "ceiling-refused"
                return rec
            _on_decisions = True
        # The record does not cover the merged tree (drifted, absent, non-ancestor, or RED) — take
        # the audit HERE, over the tree that is about to reach main.
        try:
            n_before = sum(1 for e in _read_land_events(EVENTS_PATH)
                           if e.get("type") == "audit_post_completed" and e.get("task_id") == tid)
        except Exception:                # noqa: BLE001 — an unreadable journal proves nothing
            rec["outcome"] = "could-not-run"
            return rec
        _head_before = None
        if _minted_out is not None:
            try:
                _head_before = (_run_git_cap(["rev-parse", "HEAD"], W).stdout or "").strip() or None
            except Exception:            # noqa: BLE001 — recording is best-effort; see the docstring
                _head_before = None
        # T-12370 — THE SUBJECT THE VERDICT IS RECORDED AT: the branch tip THIS land merged, not the
        # land's own `land: bookkeeping` self-commit that HEAD is sitting on. An aborting land takes
        # that commit back off the branch (`_land_rollback_bookkeeping_to_entry`), so a row recorded
        # there names a commit NO BRANCH CONTAINS and every later admission refuses
        # `unresolvable subject-commit-mismatch` — a done, twice-green card wedged by its own
        # bookkeeping (T-12315, 2026-09-10T23:46:24Z).
        #
        # RESOLVED BY SHA IDENTITY, NEVER BY SUBJECT LINE — the T-11467 discipline this module's
        # rollback already holds, reusing the SAME `minted_shas` handshake list that rollback reads
        # (it already carries the step-1b bookkeeping sha by the time this seam runs). Walk HEAD
        # down while the commit is one THIS land minted; the first commit that is not is the tip.
        #
        # BEST-EFFORT AND OFFERED, NEVER ASSERTED: an unreadable HEAD, a failed walk, or no minted
        # list at all leaves `_subject` None and the route records at HEAD exactly as today, and the
        # VERB re-derives its own ancestor + inert-delta guard over whatever is offered, so nothing
        # here can widen what is recorded. HONEST BOUND: when this land ALSO made a catch-up merge,
        # that merge is itself rolled back, so NO commit carries the merged tree afterwards — the
        # `stale` reading of such a row (T-12370, `row_residual_fingerprints`) is what covers that
        # residue. The two halves are complementary, not redundant.
        _subject = None
        _minted = {str(s).strip() for s in (_minted_out or ()) if str(s).strip()}
        if _minted:
            try:
                _cur = (_run_git_cap(["rev-parse", "HEAD"], W).stdout or "").strip()
                _seen = set()
                while _cur and _cur in _minted and _cur not in _seen:
                    _seen.add(_cur)
                    _parent = _run_git_cap(["rev-parse", f"{_cur}^"], W)
                    if getattr(_parent, "returncode", 1) != 0:
                        _cur = None
                        break
                    _cur = (_parent.stdout or "").strip()
                _subject = _cur or None
            except Exception:            # noqa: BLE001 — records at HEAD, exactly as before
                _subject = None
        rec["reaudit_subject"] = _subject
        # OFFERED ONLY WHEN RESOLVED: the keyword is passed iff a subject was found, so an injected
        # runner that predates it (every fixture runner that fakes `_inland_audit_post` with the
        # two-argument shape) is called exactly as before on every path that offers nothing —
        # the same additive shape `on_decisions` took in T-12320.
        if _subject:
            rec["rc"] = _inland_audit_post(tid, W, on_decisions=_on_decisions, subject=_subject)
        else:
            rec["rc"] = (_inland_audit_post(tid, W, on_decisions=True) if _on_decisions
                         else _inland_audit_post(tid, W))
        if _minted_out is not None and _head_before:
            # The re-audit's own self-commit(s), recorded for the T-11467 rollback identity. Bounded
            # by `_head_before`, which THIS process read before the invocation.
            try:
                _head_after = (_run_git_cap(["rev-parse", "HEAD"], W).stdout or "").strip()
                if _head_after and _head_after != _head_before:
                    _w = _run_git_cap(["log", "--format=%H", f"{_head_before}..{_head_after}"], W)
                    if getattr(_w, "returncode", 1) == 0:
                        for _ln in (_w.stdout or "").splitlines():
                            _s = _ln.strip()
                            if _s:
                                _minted_out.append(_s)
            except Exception:            # noqa: BLE001 — records nothing; rollback behaves as today
                pass
        try:
            n_after = sum(1 for e in _read_land_events(EVENTS_PATH)
                          if e.get("type") == "audit_post_completed" and e.get("task_id") == tid)
        except Exception:                # noqa: BLE001
            rec["outcome"] = "could-not-run"
            return rec
        if n_after <= n_before:
            rec["outcome"] = "could-not-run"
            return rec
        _v, _c = _latest_task_audit_post(tid, EVENTS_PATH, _read_land_events)
        rec["outcome"], rec["audit_commit"] = "reaudited", _c
        rec["verdict"] = _v
        return rec
    except Exception:                    # noqa: BLE001 — never raise into the land; never grant
        rec["outcome"] = "could-not-run"
        return rec

def _inland_reaudit_refusal_text(rec: dict) -> str:
    """The COMPLETE refusal for a `could-not-run` in-land re-audit — composed here in full and
    printed by the caller as the ONE message the operator sees.

    `lessons/carving-an-exception-into-a-fail-closed-gate` §2: a branch that established "I could
    not tell" must not print that above a fall-through to a branch that asserts something else. The
    currency gate's own message ("an OBSERVABLE change landed AFTER the audit") is a claim about a
    STALE audit; here there is no audit verdict at all, which is a different diagnosis about a
    different fact, so this branch owns its own text and the gate is never reached."""
    _t = rec.get("task") or "<task>"
    return ("land: --rebaseline REFUSED — the in-land audit-post could not be taken over the merged "
            "tree, so nothing covers the tree about to reach main (SPEC-0077 §3a / T-11483). "
            "Worktree intact, main untouched.\n"
            "This is NOT a stale-audit refusal: no audit verdict was recorded at all, so the "
            "auditor either could not run or a gate refused it — read its output above.\n"
            f"RECOVERY: re-run the audit yourself — `yitc-v2 audit post --reaudit-after-close "
            f"--task {_t}` — then re-run this land.\n"
            "If the auditor cannot RUN at all, do NOT force this land: escalate with "
            f"`yitc-v2 blocked-on-land {_t} <reason>` (worktree intact) — that escalation is the "
            "CORRECT outcome (SPEC-0103 / SPEC-0121 default-under-uncertainty is STOP). There is "
            "deliberately no flag that waives this: `--no-tests` skips TESTS, never the audit.")

def _inland_reaudit_ceiling_refusal_text(rec: dict) -> str:
    """The COMPLETE refusal for a `ceiling-refused` in-land re-audit — T-12320.

    The SIBLING of `_inland_reaudit_refusal_text`, and a separate function for the same reason that
    one is separate from the currency gate's message (`lessons/carving-an-exception-into-a-fail-closed-gate`
    §2): three branches, three different established facts, three messages. That one says «no audit
    verdict was recorded at all» and its recovery is to run `audit post --reaudit-after-close` — which
    here is precisely the command the ladder just refused, so printing it would hand the operator a
    remedy that cannot work.

    The ladder's OWN `kind` and `message` are pasted VERBATIM rather than re-summarised: the message
    already NAMES each undecided residual fingerprint, or the split evidence revisions, or the read
    error — and rule 3 requires the refusal to name them (an aggregate cannot say which residual
    lacked which decision). Re-composing it here would be a second wording of the same fact, free to
    drift from the one the CLI arm prints for the identical refusal."""
    _t = rec.get("task") or "<task>"
    _od = rec.get("on_decisions") if isinstance(rec.get("on_decisions"), dict) else {}
    _ref = _od.get("refusal") if isinstance(_od.get("refusal"), dict) else {}
    _kind = _ref.get("kind") or "<kind>"
    _msg = (_ref.get("message") or "").strip()
    _cref = _od.get("ceiling_ref") or f"{_t}/post/pass-<N>"
    return ("land: --rebaseline REFUSED — the in-land audit-post over the MERGED tree is AT or PAST "
            "the SPEC-0124 audit-loop ceiling, and the SPEC-0204 rule-3 admission REFUSED the one "
            f"bounded pass ({_kind}). Worktree intact, main untouched.\n"
            "NO auditor was invoked and NO pass was spent — this is not an auditor failure and not a "
            "stale-audit refusal.\n"
            f"\n{_msg}\n"
            f"\nRECOVERY: record ONE typed decision per residual of {_cref}, then re-run this land "
            "(the land takes the admitted pass itself — you do NOT need to run the audit by hand):\n"
            f"  yitc-v2 audit decide --task {_t} --stage post --finding <fingerprint> \\\n"
            "      --disposition fix|accept|defer --reason <why> --directive <events.jsonl#ts=...> "
            "[--receiving T-YYYY] [--evidence <revision>]\n"
            "Decisions are Controller-only and are a no-worktree journal append (SPEC-0204 rules 2-3, "
            "D-0049) — a dispatched Worker is refused at that verb by design.\n"
            "If you cannot resolve the residuals, do NOT force this land: escalate with "
            f"`yitc-v2 blocked-on-land {_t} <reason>` (worktree intact) — that escalation is the "
            "CORRECT outcome (SPEC-0103 / SPEC-0121 default-under-uncertainty is STOP). There is "
            "deliberately no flag that waives this: `--no-tests` skips TESTS, never the audit.")

def _pinned_failures_are_additive_layout_mismatch(pinned_bad: list, W: Path, merged_base: str, *, _is_candidate_added_bin_module, _pinned_import_failure_module):
    """SPEC-0077 §3 / T-9246: classify a NON-empty pinned-verify failure list. Returns the sorted list of
    excused module names iff EVERY reason is a `No module named '<X>'` import failure AND every such `<X>`'s
    top-level name is a candidate-added bin/ module (`_is_candidate_added_bin_module`) — a purely-additive
    engine-LAYOUT change the stale pinned FIXTURE could not provision. Returns None (do NOT excuse → abort)
    the moment ANY reason is a non-import failure (an assertion → a real check-relaxation) or names a
    non-additive module (a removed/renamed/non-bin surface). ALL-OR-NOTHING + directional = the §3
    circular-trust guard stays intact."""
    if not pinned_bad:
        return None
    modules = set()
    for reason in pinned_bad:
        top = _pinned_import_failure_module(reason)   # exact-shape terminal-line match (audit-post F1)
        if top is None:
            return None                                  # a non-import failure (assertion) → NOT excusable
        if not _is_candidate_added_bin_module(top, W, merged_base):
            return None                                  # not a purely-additive new bin/ module → NOT excusable
        modules.add(top)
    return sorted(modules)

def _unmarked_layer_failure_id_of(assertion, *, _NO_ASSERTION_CONTEXT_SEP=None, _UNMARKED_LAYER_FAILURE_PREFIX=None, _UNMARKED_LAYER_ID_ALPHABET=None) -> "str | None":
    """T-11346: read a surfaced assertion back → the identifier it LEADS with, or None. The two
    classifiers (`_pinned_entry_waive_record` grant-side, `_recorded_pinned_waive_records`
    backstop-side) both key a synthesised entry's `match_text` on the ID ALONE, never on the whole
    surfaced line: the line carries the tail's last output line behind the shared context separator,
    and that text is run-varying by nature (X-0683). Quoting it into the pasted token is what made a
    suggestion unwritable before the run — the id is the part that is stable."""
    text = str(assertion or "").strip()
    if not text.startswith(_UNMARKED_LAYER_FAILURE_PREFIX):
        return None
    ident = text.split(_NO_ASSERTION_CONTEXT_SEP, 1)[0].strip()
    # T-11622 — SHAPE, not merely prefix. The prefix test alone accepts any text that happens to LEAD
    # with it, so an id-shaped-but-not-an-id line was read back as an identifier and keyed a waive
    # entry's `match_text`. What `_unmarked_layer_failure_id` emits is the prefix followed by EXACTLY
    # 16 characters drawn from `_UNMARKED_LAYER_ID_ALPHABET` (a 64-bit digest re-alphabeted); anything
    # else is not one of ours, and the fail-closed answer for it is None — the same answer this
    # function already gives an unrecognised line. Deliberately NOT tightened further: the digest
    # length and the alphabet are read from the emitter's own constants, so the two stay in step.
    digest = ident[len(_UNMARKED_LAYER_FAILURE_PREFIX):]
    if len(digest) != 16 or not set(digest) <= set(_UNMARKED_LAYER_ID_ALPHABET):
        return None
    return ident or None

def _rebaseline_waive_suggested_token(rec, *, _waive_qualifier_key=None) -> "str | None":
    """T-10820: the ONE builder of the `--rebaseline-waive` token the refusal message pastes, over an
    entry record produced by `_rebaseline_waive_coverage`. `None` for a C3 entry — it can never be
    covered, so offering a token would hand the operator a confident remedy that cannot bind (the
    T-10794 rule, kept and now keyed off the CLASS in exactly one place).

    The qualifier is the NORMALIZED assertion (`_waive_qualifier_key`), truncated — so what is pasted
    is what the matcher compares.

    T-11782 — WHAT "STABLE" MEANS HERE, stated as a BOUND rather than as the blanket claim this
    docstring used to make. The claim matters because the refusal message tells the operator to paste
    this token VERBATIM; on 2026-08-28 three consecutive land attempts on ONE unchanged tree each
    REFUSED the token the previous attempt had pasted (run 1 → X, run 2 refused X and pasted Y, run 3
    refused Y and pasted X), so following the tool's own instruction could not converge.

    The cause is a HARD WRAP in the captured tail, upstream of the truncation. A wrapped
    `FAILED <path>::<name>` line reaches `cli.py#_extract_failing_assertion` rule 0b as TWO physical
    lines; the head still matches the short-summary regex and is kept as a whole `"; "`-item, while the
    continuation matches nothing and is DISCARDED. `match_text` therefore leads with a fragment whose
    length is the moving wrap column, and the 60-char cut lands a character apart between runs.

    So the wrap is DETECTED, positively, and the damaged text is not what gets quoted: an item that
    starts with `FAILED ` but carries NO `::` cannot be a whole nodeid line, and is therefore a wrap
    head whose continuation was dropped. On that signature the token quotes the FIRST structurally
    COMPLETE sibling item for THIS entry's own file — the wrap-immune substring a T-11727 operator had
    to hand-declare — and when the signature fires with NO complete item left, it offers NO token at
    all rather than an unstable one. A single item
    is a CONTIGUOUS substring of the entry key, so the quoted item still binds through the unchanged
    substring matcher; nothing here widens what the matcher accepts. Text carrying no wrap signature
    is quoted exactly as before, so no previously-stable input changes answer.

    KNOWN RESIDUAL, named because a docstring that over-promised is what this card came back to fix:
    a wrap landing inside the quoted nodeid's trailing TEST-NAME (`…py::test_the_c`, with
    `losure_key_…` dropped) leaves a head that still carries `::` and still names this file, so it
    presents NO signature this function can see — rule 0b discarded the continuation before the record
    ever reaches here. Such a head still BINDS (a nodeid prefix is a substring of the intact line) but
    is not byte-stable, and repairing it needs the un-wrapped tail, one layer up."""
    key = rec.get("test_file")
    if rec.get("class") == "C3" or not key:
        return None
    if rec.get("class") == "C2":
        return str(key)                       # provably file-level: the bare key is the sanctioned form
    # T-10892: the token quotes the text the MATCHER judges (`match_text`), never the marker/label prose
    # the block may wrap it in — same single-source discipline this function exists for, one layer in.
    text = rec.get("match_text")
    if text is None:
        text = str(rec.get("assertion", "")).split(f"{key}: ", 1)[-1]
    if not str(text).strip():
        return None                           # nothing bindable to quote → offer no token (see above)
    quoted = _waive_qualifier_key(text)
    # T-11782 — the wrap signature, POSITIVELY defined, in the enumerated style of `_WAIVE_VOLATILE_RES`
    # and never "looks unstable": a whole pytest short-summary item is `FAILED <path>::<name>[ - <msg>]`
    # and a nodeid ALWAYS carries `::`, so an item opening with the `FAILED ` marker and carrying none
    # can only be the part of such a line that preceded a hard wrap. Any other shape — a runner `FAIL:`
    # line, an AssertionError, a self-reported summary — is not this shape and is not judged here.
    items = [i.strip() for i in quoted.split(";") if i.strip()]
    is_wrap_head = lambda i: i.startswith("FAILED ") and "::" not in i   # noqa: E731
    if any(is_wrap_head(i) for i in items):
        # Quote the first item that is a COMPLETE summary line FOR THIS ENTRY. The file anchor is what
        # keeps a sibling file's failure out of this entry's token: the qualified-token rule exists to
        # stop a token waiving whatever same-key failure happened to surface, so the selection must be
        # at least as specific as the entry it is built for. None left ⇒ nothing wrap-immune to quote.
        base = str(key).rsplit("/", 1)[-1]
        quoted = next((i for i in items
                       if i.startswith("FAILED ") and not is_wrap_head(i)
                       and i[len("FAILED "):].split("::", 1)[0].rsplit("/", 1)[-1] == base), None)
        if quoted is None:
            return None                       # wrap-damaged with nothing intact left → offer no token
    return f"{key}::{quoted[:60]}"

# T-12149 (SPEC-0077 §3a) — the digit-bearing WORD, and the coarseness floor a stable token must clear.
# Split out as module constants rather than inlined so the two bounds below are readable as the rule
# they are, and so a reader of the builder sees WHAT is being cut and WHAT is being refused.
_WAIVE_STABLE_DIGIT_WORD_RE = re.compile(r"\S*\d\S*")   # a whitespace-delimited word carrying a digit
_WAIVE_STABLE_MIN_CHARS = 12                             # a run shorter than this is not an identity
_WAIVE_STABLE_MIN_WORDS = 2                              # ...nor is a single bare word (`FAIL`)


def _rebaseline_waive_stable_token(rec, *, _rebaseline_waive_suggested_token=None) -> "str | None":
    """T-12149 (SPEC-0077 §3a): the SECOND `--rebaseline-waive` token shape offered beside the exact
    one — the pinned KEY plus the assertion's STABLE IDENTIFYING SPAN — or `None` when this entry has
    no stable shape distinct from its exact token. Pure: no git, no I/O.

    WHY THIS EXISTS (the measured incident: task/T-11944, 2026-09-04T22:57:38Z). `_waive_qualifier_key`
    stabilizes a token against RUN-varying spans (timestamps, pids, temp paths). It deliberately does
    NOT touch a plain number, because the letter-bearing-word condition is what keeps an assertion's own
    numeric VALUE exact (`assert '200-000' == '200-000-000'`) — a token naming a different number must
    not bind. But a pinned assertion can carry a value that is MAIN-varying rather than run-varying: a
    count or roster the corpus itself keeps moving (`expected 29 concern born blocks, got 30` read 29,
    then 30, then 31 within one day as T-12046 and T-12080 added concerns). A token minted on one `main`
    is then `no-match` on the next, and the refusal — which instructs the operator to paste it VERBATIM
    — pastes a FRESH count-bearing token, re-arming the identical staleness. That is a re-mint-and-
    re-queue loop costing one land attempt and one queue position per turn; T-11944's single refusal
    shows both halves of it (three rejected count-bearing tokens, three fresh count-bearing suggestions).

    THE MATCHER IS NOT THE DEFECT AND IS NOT TOUCHED. `_waive_coverage_over_records` already tests the
    qualifier by SUBSTRING containment, so a digit-free span of the assertion ALREADY binds across the
    moving value. What was missing is that no sanctioned surface ever OFFERED such a span, so the only
    token an operator could paste was the volatile one. This widens WHAT IS OFFERED and nothing else:
    the C1/C2/C3 vocabulary, the mandatory qualifier for an assertion-bearing entry, the mechanical tie
    in `--rebaseline-reason`, the fresh-GREEN-audit-post condition and every fail-closed axis are
    UNCHANGED.

    DERIVED FROM THE EXACT BUILDER'S OWN OUTPUT, never from `rec` directly — so every guard already
    lives in ONE place and cannot drift: a C3 entry yields `None` there, a C2 entry yields the bare key
    (no `::`, so no qualifier to stabilize), the T-11782 wrap repair has already run, and the 60-char
    truncation has already been applied — which is also what keeps a long moving DATA TAIL (the sorted
    section list trailing the born-generation assertion) out of the span.

    THE SPAN IS THE FIRST DIGIT-FREE RUN THAT CLEARS THE FLOOR — first, not longest. The leading run is
    the assertion's identifying HEAD; the longest is as likely to be its moving data tail. The floor
    (`>= 2` words AND `>= 12` chars) is load-bearing rather than cosmetic: it is what refuses
    `FAIL test_ac2_existing_truth_table_is_untouched_by_this_card`, whose first digit-bearing word is
    the TEST NAME and whose head would be the bare word `FAIL` — a token as coarse as the bare-key
    token §3a already refuses for a C1 entry. The same floor excludes a wrap-repaired
    `FAILED <path>::<name>` by construction. There is no fallback to a shorter run: fail closed and
    offer nothing rather than something plausible-but-overbroad.

    NOT the exception TYPE, though that is the shape a reader reaches for first (and the shape an
    external auditor proposed at this card's audit-pre). `<file>::AssertionError` is strictly COARSER:
    it matches EVERY assertion in that file, which is the over-broadening the identifying span exists
    to avoid. Measured over the three real T-11944 assertions — all `AssertionError:` — the type token
    covers all three, while each span token covers its own and refuses both siblings.

    BINDING IS GUARANTEED BY CONSTRUCTION, never by a second matcher. The exact qualifier is
    `_waive_qualifier_key(match_text)[:60]`, a prefix of the entry key `_waive_coverage_over_records`
    builds; a stripped contiguous run of that prefix is a contiguous substring of the entry key, hence
    it binds. `_waive_qualifier_key` is idempotent, so re-normalizing the emitted token at match time
    is a no-op.

    NAMED RESIDUAL, stated rather than papered over: two DISTINCT numeric assertions in the SAME file
    could share an identifying head. The runner appends AT MOST ONE entry per file per run, so at most
    one can be present in the failing set a declaration is judged against; and were two ever present,
    the matcher's EXISTING `ambiguous` axis refuses the token. No new fail-open path is introduced —
    the bound is carried by a gate that already exists."""
    exact = _rebaseline_waive_suggested_token(rec)
    if not exact or "::" not in exact:
        return None                       # C3 (None) or C2 (the bare key) — no qualifier to stabilize
    key, qual = exact.split("::", 1)
    if not _WAIVE_STABLE_DIGIT_WORD_RE.search(qual):
        return None                       # already stable: a second identical line would be noise
    for run in _WAIVE_STABLE_DIGIT_WORD_RE.split(qual):
        run = run.strip()
        if len(run) >= _WAIVE_STABLE_MIN_CHARS and len(run.split()) >= _WAIVE_STABLE_MIN_WORDS:
            return f"{key}::{run}"
    return None                           # nothing clears the floor → offer nothing (fail closed)


def _rebaseline_waive_paste_lines(recs, *, indent, _shell_dq=None,
                                  _rebaseline_waive_suggested_token=None) -> list:
    """T-12149: the ONE composer of `--rebaseline-waive <token>` paste lines for every refusal in THIS
    module. Returns the lines for `recs` in order — the EXACT token first (byte-identical to what each
    renderer pasted before this card, and in the same order), then the STABLE token when one exists.
    `indent` is the leading whitespace the calling refusal already used. Pure: no git, no I/O.

    A record that yields NO exact token (C3 — never coverable) contributes NO line here; a renderer
    that wants to say something about such an entry says it itself, as `_environmental_broken_refusal_text`
    does with its `(not waivable — ...)` line. That split is deliberate: this composer's job is the
    bindable tokens, and offering a confident remedy that cannot bind is the failure
    `lessons/carving-an-exception-into-a-fail-closed-gate.md` §2 names.

    WHY A COMPOSER AND NOT FOUR CALL SITES. Each renderer used to build its own
    `"  --rebaseline-waive " + _shell_dq(tok)` line. That is four places for the paste to drift — the
    X-0685 class, where a refusal offered a token its own matcher then rejected — and it is why
    `tests/test_t11347_first_rebaseline_refusal_offers_token.py` AC4 has to ASSERT that two refusals
    stay byte-identical. With one composer that identity is STRUCTURAL rather than tested-for, and the
    second (stable) shape reaches all four refusals by construction instead of by four edits.

    SCOPE BOUND, explicit: this is the one composer for THIS MODULE, never for the repo. A fifth
    renderer — the uncovered-entry scope refusal in `bin/lib/worktree.py` — still composes its own
    exact-only line; it is outside this card's declared footprint and is tracked as an open followup.

    `_rebaseline_waive_stable_token` is called DIRECTLY rather than injected, unlike the host symbols
    above. The injection seam exists so a HOST collaborator stays rebindable (`-C` re-binding,
    `monkeypatch.setattr(yitc, ...)`) through its residue; that sibling is born in THIS module and has
    no historical host name, so there is no residue to honour and nothing to rebind. It is reached from
    the roots through this composer, so it is inside the extraction closure by construction (T-11523)."""
    lines = []
    for rec in (recs or []):
        exact = _rebaseline_waive_suggested_token(rec)
        if exact is None:
            continue
        lines.append(f"{indent}--rebaseline-waive " + _shell_dq(exact))
        stable = _rebaseline_waive_stable_token(
            rec, _rebaseline_waive_suggested_token=_rebaseline_waive_suggested_token)
        if stable is not None and stable != exact:
            lines.append(f"{indent}--rebaseline-waive " + _shell_dq(stable))
    return lines

def _pinned_assertion_delta(diff_text, *, _PINNED_ASSERTION_RE=None, _PINNED_TEST_SURFACE_PREFIX=None):
    """Per-file `{path: {"removed": [...], "added": [...]}}` assertion lines over a unified diff,
    restricted to the pinned test surface. Split out so the parse is testable on its own and so the
    notice below reads as intent rather than as diff-walking."""
    per, cur = {}, None
    for line in str(diff_text or "").splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            # `/dev/null` (a deletion's `+++`) never matches the surface prefix, so a wholly-deleted
            # test file is attributed to no path and cannot produce a notice. Deliberate: removing a
            # test file outright is a different act with its own gates, not a superseded assertion.
            cur = path if path.startswith(_PINNED_TEST_SURFACE_PREFIX) else None
            if cur is not None:
                per.setdefault(cur, {"removed": [], "added": []})
            continue
        if line.startswith("--- ") or cur is None:
            continue
        if line.startswith("-") and _PINNED_ASSERTION_RE.match(line[1:]):
            per[cur]["removed"].append(line[1:].strip())
        elif line.startswith("+") and _PINNED_ASSERTION_RE.match(line[1:]):
            per[cur]["added"].append(line[1:].strip())
    return per

def pinned_supersession_entries(diff_text, *, _pinned_assertion_delta=None) -> list:
    """T-11262 — the superseded assertions a diff names, `[(path, assertion_text)]` in source order,
    empty when it names none. PURE: unified-diff text in, list out.

    Split out of `pinned_supersession_notice` (which now calls it) so ONE authority answers "which
    assertions does this diff supersede". The notice PRINTS that answer and the `commit_landed` row
    RECORDS it; computing it twice is how the printed advisory and the recorded row would come to
    disagree, and a row that disagrees with what the author was told is worse than no row. Same
    discipline as T-11258, where the eviction cause is copied off the record the classifier wrote
    rather than recomputed at the emitter (CHARTER §P5 — one question, one authority).

    A removed assertion whose text reappears VERBATIM among the same file's added lines is dropped
    here, so the move/reindent exemption is shared by both consumers by construction."""
    per = _pinned_assertion_delta(diff_text)
    superseded = []                                    # [(path, assertion_text)], source order
    for path in sorted(per):
        added = set(per[path]["added"])
        for text in per[path]["removed"]:
            if text not in added:
                superseded.append((path, text))
    return superseded

def pinned_supersession_event_keys(entries, *, _PINNED_SUPERSESSION_EVENT_EXCERPT=None, _PINNED_SUPERSESSION_EVENT_MAX=None) -> dict:
    """T-11262 — the ADDITIVE `commit_landed` keys for a fired supersession notice, or `{}` for a
    commit that fired none. PURE: list in, dict out.

    Returns `{}` — not a zero-valued key — when nothing was superseded. That asymmetry IS the AC2
    tripwire: a row carrying the key claims the notice fired, so an add-only test diff must produce
    NO key at all rather than `count: 0`. An absent key means "did not fire"; it never means "fired
    and found nothing", because those two are the difference between counting the mechanism and
    fabricating it.

    Called by the HOST (`bin/yitc-v2 _commit_worktree`), which already imports both this module and
    `lib.task`, so the finished payload reaches BOTH `commit_landed` emitters without `lib/task.py`
    importing this module — that direction is the acyclic one (this module imports `task`, not the
    reverse; audit-pre finding, T-11262).

    Recording is not enforcing. Nothing reads these keys to make a decision — they exist so a later
    reader can COUNT firings and join them against the branches that went on to re-baseline, which is
    what gives T-11257's 39.9% historical precision a field figure to be checked against."""
    rows = list(entries or [])
    if not rows:
        return {}
    payload = {"count": len(rows),
               "assertions": [{"file": str(p), "assertion": str(t)[:_PINNED_SUPERSESSION_EVENT_EXCERPT]}
                              for p, t in rows[:_PINNED_SUPERSESSION_EVENT_MAX]]}
    if len(rows) > _PINNED_SUPERSESSION_EVENT_MAX:
        payload["truncated"] = True
    return {"pinned_supersession": payload}

def pinned_supersession_notice(diff_text, *, limit=3, _PINNED_ASSERTION_MSG_RE=None, _shell_dq=None, _waive_qualifier_key=None, pinned_supersession_entries=None) -> "str | None":
    """T-11257 — the advisory text for a diff that probably supersedes a pinned last-green assertion,
    or None when it probably does not. PURE: unified-diff text in, text out. No git, no I/O, no
    journal, no clock — so the caller's fail-open wrapper is a belt, not the only line of defence.

    Returns None — no notice — for every diff that only ADDS assertions, BY CONSTRUCTION rather than
    by a threshold: with no removed assertion line there is nothing to report. That is the AC2 leg,
    and it is what keeps this off the ~90% of branches that merely touch `tests/`.

    A removed assertion whose text reappears VERBATIM among the same file's added lines is dropped: a
    move or a reindent supersedes nothing. (This is the STRICT variant that was measured; it is worth
    the two lines — it is a third of a point of precision, but it is also the difference between an
    author being told the truth and being told off for running a formatter.)

    The token it pastes is built through the SAME `_waive_qualifier_key` normalizer and `_shell_dq`
    quoting the real `--rebaseline-waive` matcher uses, so what is offered here binds there. It is a
    STARTING POINT, not a promise: the authoritative token is the one `land` itself pastes from the
    actual failing entry (`_rebaseline_waive_suggested_token`), which can only exist after a run."""
    superseded = pinned_supersession_entries(diff_text)
    if not superseded:
        return None

    out = ["NOTICE: this commit rewrites or removes %d existing assertion(s) in the pinned test "
           "surface, which OFTEN means it supersedes a pinned last-green check (T-11257 / "
           "SPEC-0077 §3a):" % len(superseded)]
    for path, text in superseded[:limit]:
        excerpt = text if len(text) <= 140 else text[:137] + "..."
        out.append(f"  {path}: {excerpt}")
    if len(superseded) > limit:
        out.append(f"  ... and {len(superseded) - limit} more.")
    out.append(
        "  If it does, the pinned last-green verify will FAIL at `land` and you will pay a SECOND "
        "full verify pass to re-land with the waive declared. Declaring it up front costs one pass:\n"
        "    bin/yitc-v2 land --task T-XXXX --rebaseline --rebaseline-kind broken \\\n"
        "        --rebaseline-reason \"<why this old-behaviour check is superseded>\" --rebaseline-waive <token>")
    # The `<token>` slot is filled ONLY from an assertion whose MESSAGE literal we can read, because
    # the message is what surfaces as the failure text the matcher judges. With no message there is
    # nothing bindable to quote, so we offer NO token and say so — the same fail-closed choice
    # `_rebaseline_waive_suggested_token` makes for an entry it cannot key (a declaration that does
    # not bind is not an ack, and a confident un-bindable suggestion is worse than none: X-0685).
    suggestions = []
    for path, text in superseded[:limit]:
        m = _PINNED_ASSERTION_MSG_RE.search(text)
        if m:
            suggestions.append(f"{path.rsplit('/', 1)[-1]}::{_waive_qualifier_key(m.group(2))[:60]}")
    if suggestions:
        out.append("  <token>, composed from the assertion message(s) — a STARTING POINT, not the "
                   "failing entry:")
        for tok in suggestions:
            out.append(f"      --rebaseline-waive {_shell_dq(tok)}")
        out.append("  `land` pastes the AUTHORITATIVE token from the real failing entry if it does "
                   "fail; prefer that one. A re-baseline still requires a GREEN/YELLOW audit-post "
                   "over the current tree — nothing here grants it.")
    else:
        out.append("  No <token> is suggested: these assertions carry no message literal, and the "
                   "waive matcher compares the SURFACED failure text, which only the run produces. "
                   "Take the token `land` pastes if it fails. A re-baseline still requires a "
                   "GREEN/YELLOW audit-post over the current tree — nothing here grants it.")
    out.append(
        "  ADVISORY ONLY — this changes no exit code, no land outcome, and no admission decision, and "
        "it is a heuristic, not a verdict: measured on this repo's own history it is right about 2 "
        "times in 5, and it stays SILENT for about 2 of every 5 real supersessions (one carried by a "
        "fixture or helper change edits no assertion line and is invisible to it). Silence here is "
        "not proof your change supersedes nothing.")
    return "\n".join(out) + "\n"

def _pinned_failure_test_file(entry, *, _consumer_verify_layer_key=None, _pinned_entry_core=None) -> "str | None":
    """T-10754 (SPEC-0077 §3a): the KEY a pinned verify-failure entry belongs to, or None when the entry
    has no key at all — a pinned setup / pinned-engine-subprocess / consumer-guard SETUP fault, or any
    unparseable first line (`_run_pinned_verify`'s unrecognised returns). A None key is the class-C3
    "cannot tell whose check this is" value, and the caller routes it to REFUSE: an infrastructure fault
    is never a "superseded old-behaviour check" (SPEC-0077 §3a fires on a real ASSERTION failure).
    Mirrors `_surface_failing_assertions`' own first-line parse, so the two agree on what an entry IS.

    TWO KEYED SHAPES, one per runner (T-10794 / X-0634 widened the second in):
      • the kernel sweep      → the test FILE  (`test failed: <file>`, `_run_verify_tests`)
      • a delegating CONSUMER → the LAYER NAME (`land(consumer): verify layer '<name>' FAILED
        (exit N): …`, `_consumer_zero_probe_guard` — SPEC-0152 rule 16)
    Keyed is NOT coverable: what an entry's key BUYS is the caller's judgement (see
    `_rebaseline_waive_coverage`), and the two shapes deliberately differ there."""
    core = _pinned_entry_core(entry)
    if core.startswith("test failed: "):
        return core[len("test failed: "):].strip() or None
    return _consumer_verify_layer_key(core)

def _rebaseline_waive_coverage(pinned_bad: list, declared, *, _surface_failing_assertions, _pinned_entry_waive_record=None, _waive_coverage_over_records=None) -> tuple:
    """T-10754 (SPEC-0077 §3a) — split a NON-empty pinned failing set into what the operator's
    `--rebaseline-waive` declaration COVERS and what it does not. Returns
    `(covered, uncovered, bad_tokens)`; the caller grants the re-baseline ONLY when both `uncovered`
    and `bad_tokens` are empty.

    WHY THIS EXISTS (T-10731, fingerprint `rebaseline-waives-pinned-failures-its-reason-never-named`):
    the grant used to be ALL-OR-NOTHING — the ack + reason + audit gated the PATH, then the WHOLE
    failing set was recorded as superseded, whatever was in it. On 2026-08-06 a reason naming ONE
    superseded layout guard also waived an unrelated `UnicodeDecodeError`, and because the next land
    re-pins THIS now-green main as last-green by construction (SPEC-0077 §2), an unnamed failure is
    absorbed into the new baseline. The declaration is now the ONLY positive evidence: there is no
    implicit, derived, or fallback coverage source of any kind (an earlier branch-footprint fallback —
    "the branch revised this test file" — was REJECTED at audit-pre as a property of the CHANGE rather
    than a statement by the OPERATOR).

    THE CLOSED THREE-CLASS VOCABULARY (every entry lands in exactly one class; "cannot tell" refuses):
      C1 ASSERTION-BEARING — a test-file key AND real surfaced assertion text. Covered ONLY by a
         QUALIFIED token `<file>::<substring>` whose non-empty substring occurs (case-sensitively) in
         that entry's surfaced assertion. A BARE `<file>` token is INSUFFICIENT here — file scope would
         waive whatever same-file failure happened to surface, which is the defect this closes.
      C2 FILE-LEVEL — a test-file key but NO extractable assertion text (`(no assertion captured)`).
         This is the only PROVABLY file-level entry, so a bare `<file>` token covers it.
      C3 UNKEYED — no key (`_pinned_failure_test_file` → None), OR a consumer verify-LAYER key with
         no captured text (see below). NEVER coverable.
    This runner is NOT pytest, so there is no node id to key on: `_run_verify_tests` runs each
    `tests/test_*.py` as one subprocess and appends AT MOST ONE `test failed: <tf.name>` entry per file.
    The surfaced assertion TEXT is the only sub-file identity the pipeline actually has, which is what
    the mandatory qualifier keys on.

    T-10794 (X-0634) — WHAT AN ABSENT ASSERTION MEANS IS THIS READER'S JUDGEMENT, PER ENTRY CLASS.
    `_pinned_failure_test_file` stays a faithful parser and now keys a delegating consumer's verify-LAYER
    failure too (SPEC-0152 rule 16); it does NOT decide coverability. Absence of assertion text means two
    different things here, so the shared parse cannot carry the decision
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`):
      • kernel `test failed: <file>` — ONE test file run as ONE subprocess, so "nothing captured" is a
        PROVABLY file-level failure → C2, and a bare `<file>` token legitimately covers it;
      • consumer `verify layer '<name>'` — a WHOLE harness behind one name, so "nothing captured" proves
        nothing: a superseded old-behaviour check and a setup fault are indistinguishable → C3, refuse.
    So the widening is over what can be KEYED, never over what counts as COVERED: a keyed layer failure
    still needs a QUALIFIED `<layer>::<substring>` token (C1), exactly as a keyed test file does.

    TOKEN VALIDATION — fail-closed on every axis, because a declaration that does not bind is not an
    ack (never a silent no-op): a token binding to NO entry is `no-match`; one whose file part binds to
    MORE THAN ONE entry is `ambiguous`; a bare token against a C1 entry is `insufficient-bare-token`.
    Pure function over already-computed data — no git, no I/O.

    T-11002 — THE JUDGING HALF IS FACTORED OUT into `_waive_coverage_over_records`, and this function
    keeps the CLASSIFYING half (raw pinned entry -> record). Nothing about either half's behaviour
    changes; the split exists so the land backstop's pre-verify admission pre-check can judge a
    declaration against the assertions ALREADY RECORDED in the journal through the SAME judging
    authority, instead of growing a second matcher that could drift from this one (CHARTER §P5)."""
    return _waive_coverage_over_records(
        [_pinned_entry_waive_record(entry, _surface_failing_assertions=_surface_failing_assertions)
         for entry in (pinned_bad or [])],
        declared)

def _waive_coverage_over_records(records, declared, *, _waive_coverage_judge=None, _waive_qualifier_key=None) -> tuple:
    """T-11002 — the JUDGING core of `_rebaseline_waive_coverage`, over already-classified records
    (`{assertion, test_file, class, match_text}`). Returns `(covered, uncovered, bad_tokens)`; a
    caller grants ONLY when both `uncovered` and `bad_tokens` are empty.

    ONE judging authority, TWO record producers: `_pinned_entry_waive_record` (a raw pinned failing
    entry, the grant path) and `_recorded_pinned_waive_records` (a journaled `failing_assertions` row,
    the backstop admission pre-check). The token vocabulary, the mandatory qualifier for a C1 entry,
    the normalizer, and every fail-closed axis are therefore identical on both paths BY CONSTRUCTION —
    which is the whole reason this is a split rather than a copy. Pure: no git, no I/O."""
    toks = []
    for raw in (declared or []):
        t = str(raw).strip()
        if not t:
            continue
        f, sep, qual = t.partition("::")
        # T-10820: the key is held BOTH verbatim and basenamed, and either form binds. `os.path.basename`
        # alone was correct for the kernel `test failed: <file>` key and WRONG for a consumer verify-LAYER
        # name, which is not a path: a layer called `docker/pytest` was pasted verbatim by the refusal and
        # then path-mangled to `pytest` by this line — the matcher rejecting its own suggestion (X-0685).
        _f = f.strip()
        toks.append({"token": t, "file": os.path.basename(_f), "file_raw": _f,
                     "qual": qual if sep else None, "matches": [], "file_hits": []})

    # Pass 1 — record for EACH token the entries it actually COVERS (`matches`) separately from the
    # entries whose FILE part it merely binds (`file_hits`). Keeping the
    # two apart is what makes token validation faithful: a token is judged on its OWN coverage, never on
    # whether some SIBLING token happened to cover the same failure (audit-post F1 — a wrong qualifier or
    # a bare C1 token used to be silently accepted whenever another valid token covered that entry, so
    # `bad_tokens` was not a real validator).
    entries = list(records or [])
    for rec in entries:
        tf, klass, match_text = rec["test_file"], rec["class"], rec["match_text"]
        if klass == "C3":
            continue                              # unkeyed: no token can bind or cover it
        # T-10820: normalized ONCE per entry, over the text a token is judged against (`match_text` —
        # T-10892), never over the marker/label prose the block wraps it in.
        entry_key = _waive_qualifier_key(match_text) if match_text else ""
        for tok in toks:
            if tf not in (tok["file"], tok["file_raw"]):
                continue
            tok["file_hits"].append(rec)
            if tok["qual"] is not None:
                # T-10820: both sides through the SAME normalizer, so a token written from an earlier
                # run of this same failing state binds (X-0683 — the pid+hash in a Docker-wrapped
                # layer's tail). An empty qualifier still binds nothing (`tok["qual"]` falsy).
                if tok["qual"] and _waive_qualifier_key(tok["qual"]) in entry_key:
                    tok["matches"].append(rec)
            elif klass == "C2":                   # bare token: legal ONLY for a provably file-level entry
                tok["matches"].append(rec)
    return _waive_coverage_judge(entries, toks)

def _pinned_entry_waive_record(entry, *, _surface_failing_assertions, _NO_ASSERTION_CAPTURED=None, _NO_ASSERTION_CONTEXT_SEP=None, _consumer_verify_layer_key=None, _pinned_entry_core=None, _pinned_failure_test_file=None, _unmarked_layer_failure_id_of=None) -> dict:
    """T-11002 (factored out of `_rebaseline_waive_coverage`, behaviour unchanged): CLASSIFY one raw
    pinned failing entry into the record `_waive_coverage_over_records` judges. The C1/C2/C3
    vocabulary + every reader-judgement note lives in `_rebaseline_waive_coverage`'s docstring, which
    is still this classification's single home — do not restate it here."""
    tf = _pinned_failure_test_file(entry)
    surfaced = (_surface_failing_assertions([entry]) or [str(entry).splitlines()[0].strip()])[0]
    assertion = surfaced.split(f"{tf}: ", 1)[1] if (tf and f"{tf}: " in surfaced) else ""
    # T-10892: PREFIX, not equality — the no-assertion marker now carries the tail's last line
    # behind it as labelled CONTEXT (`_surface_failing_assertions`), so "the block named no
    # assertion" is read off the marker and the context is split back out at the shared separator.
    unnamed = assertion.strip().startswith(_NO_ASSERTION_CAPTURED)
    _, _sep, _ctx = assertion.partition(_NO_ASSERTION_CONTEXT_SEP)
    context = _ctx.strip() if (unnamed and _sep) else ""
    is_layer = _consumer_verify_layer_key(_pinned_entry_core(entry)) is not None
    # T-10892 — WHAT AN UNNAMED ENTRY IS COVERABLE BY SPLITS BY KEY KIND, which is T-10794's own
    # reader-judgement rule applied to the honest no-assertion marker rather than to bare absence:
    #   • kernel `test failed: <file>` — ONE file as ONE subprocess, so "no failure marker" is a
    #     PROVABLY file-level failure → C2, covered by the BARE token, and a QUALIFIED token gets an
    #     EMPTY key below so it binds NOTHING. That is AC4: the block presented no assertion, so the
    #     labelled context (an alembic INFO line, a timeout note) must not be tie-able as if it were
    #     one — X-0698's meaningless tie that still cleared the `>=30-char` reason check.
    #   • consumer verify LAYER — a whole harness behind one name, where file scope proves nothing
    #     and the captured line is the ONLY sub-layer identity the pipeline has. It stays C1 on that
    #     line (identity byte-identical to before this card), because refusing it outright is what
    #     re-opens X-0683/X-0685: the operator gets no bindable token at all and the measured outcome
    #     was neutralizing the check on main by hand. Captured NOTHING at all is still C3 — that is
    #     the case where a superseded check and a setup fault are genuinely indistinguishable.
    # T-11346: a SYNTHESISED layer identifier (`_unmarked_layer_failure_id`) is judged FIRST and on
    # the ID ALONE. It is assertion-bearing by construction — stable for this failure, different for
    # another — so it is C1; and the id is the whole of `match_text` because the context line behind
    # it is run-varying (X-0683), and a token quoting THAT could not be written before the run.
    synth_id = _unmarked_layer_failure_id_of(assertion)
    if tf is not None and synth_id:
        klass, match_text = "C1", synth_id
    elif tf is None or (unnamed and is_layer and not context):
        klass = "C3"                       # unkeyed, or a layer that captured nothing (see docstring)
        match_text = ""
    elif unnamed and is_layer:
        klass, match_text = "C1", context
    elif unnamed:
        klass, match_text = "C2", ""
    else:
        klass, match_text = "C1", (assertion or surfaced)
    return {"assertion": surfaced, "test_file": tf, "class": klass, "match_text": match_text}

def _waive_coverage_judge(entries, toks) -> tuple:
    """T-11002 — pass 2 of `_waive_coverage_over_records` (factored only for readability of that
    function; behaviour byte-identical to its origin)."""
    # Pass 2 — judge each token on its OWN coverage, then take the VALID tokens as the coverage set.
    bad_tokens, valid = [], []
    for tok in toks:
        if len(tok["matches"]) > 1:
            bad_tokens.append({"token": tok["token"], "why": "ambiguous"})
        elif len(tok["matches"]) == 1:
            valid.append(tok)
        elif tok["qual"] is None and any(r["class"] == "C1" for r in tok["file_hits"]):
            # Bare token aimed at an assertion-bearing failure — REJECTED even if a sibling qualified
            # token covers that same failure (file scope is exactly what this gate refuses to grant).
            bad_tokens.append({"token": tok["token"], "why": "insufficient-bare-token"})
        elif len(tok["file_hits"]) > 1:
            bad_tokens.append({"token": tok["token"], "why": "ambiguous"})
        else:
            # Binds nothing it can cover: an unknown file, or a qualifier naming an assertion this run
            # never raised. A declaration that does not bind is not an ack — never a silent no-op.
            bad_tokens.append({"token": tok["token"], "why": "no-match"})

    covered, uncovered = [], []
    for rec in entries:
        hit = next((t for t in valid if t["matches"][0] is rec), None)
        if hit is not None:
            rec["covered_by"] = {"source": "declared", "ref": hit["token"]}
            covered.append(rec)
        else:
            uncovered.append(rec)
    return covered, uncovered, bad_tokens

def _recorded_pinned_waive_records(assertions, *, _NO_ASSERTION_CAPTURED=None, _PINNED_PREFIX=None, _unmarked_layer_failure_id_of=None) -> "list | None":
    """T-11002: rebuild the waive RECORDS from a `land_completed{abort}.failing_assertions` row — the
    surfaced `[pinned/last-green] <key>: <assertion>` one-liners `_surface_failing_assertions` wrote.
    Returns records for `_waive_coverage_over_records` (the SAME judging authority the grant uses), or
    `None` when this row cannot be judged, which the caller reads as "do not admit".

    FAIL-CLOSED, deliberately narrower than the grant-path classifier: the raw entry is gone, so the
    file-vs-layer distinction that decides what an UNNAMED entry is coverable by (T-10794 / T-10892) is
    not recoverable here. Rather than guess it, this reader admits ONLY provably assertion-bearing (C1)
    pinned entries and returns None for everything else. Narrower is safe by construction — the only
    thing admission buys is REACHING the verify that the full classifier then judges."""
    recs = []
    for raw in (assertions or []):
        s = str(raw)
        if not s.startswith(_PINNED_PREFIX):
            return None                    # a CANDIDATE (or unprefixed) failure — never re-baselineable
        key, sep, text = s[len(_PINNED_PREFIX):].partition(": ")
        key, text = key.strip(), text.strip()
        if not sep or not key or not text or text.startswith(_NO_ASSERTION_CAPTURED):
            return None                    # unkeyed / textless / the honest no-assertion marker → C2|C3
        # T-11346: a row whose text LEADS with a synthesised layer identifier is provably C1 — the id
        # is assertion-bearing by construction, and unlike the raw entry it survives journaling
        # intact, so the file-vs-layer distinction this reader cannot recover is not needed to judge
        # it. `match_text` is the ID ALONE for the same reason the grant-side classifier uses it: the
        # context behind it is run-varying, and the hint pastes `match_text` verbatim.
        recs.append({"assertion": s, "test_file": key, "class": "C1",
                     "match_text": _unmarked_layer_failure_id_of(text) or text})
    return recs or None                    # an EMPTY recorded set proves nothing → do not admit

def _land_last_abort_assertions(events: list, branch: str, key: "str | None", *, _land_abort_key) -> list:
    """T-11002: the `failing_assertions` of the MOST RECENT `land_completed{abort}` row for `branch`
    whose cause key equals `key` — i.e. the row that formed the streak the backstop is about to refuse
    on. Joins on the key `_land_repeated_abort_count` ITSELF returned, so this reader cannot drift from
    the streak walk (it never re-derives which rows counted). Pure; `[]` when there is no such row."""
    if not key:
        return []
    for e in reversed(events or []):
        if e.get("type") != "land_completed":
            continue
        d = e.get("data") or {}
        if d.get("branch") != branch or d.get("status") != "abort":
            continue
        if _land_abort_key(d) == key:
            return [str(a) for a in (d.get("failing_assertions") or [])]
    return []

def _rebaseline_admits_past_backstop(recorded_assertions, declared, *, owner_rebaseline: bool,
                                     rebaseline_kind, rebaseline_reason, min_reason_chars: int, REBASELINE_KINDS=None, _recorded_pinned_waive_records=None, _waive_coverage_over_records=None) -> bool:
    """T-11002: does THIS invocation carry a qualifying §3a re-baseline that TREATS the counted cause?
    Pure (no git, no verify, no I/O) — this is what makes it safe to evaluate BEFORE the backstop.

    All of: the ack (`--rebaseline` — SPEC-0077 §3a authority A/A-prime; there is no separate
    `--owner-authorized` on this path, unlike `--no-tests`), a valid `--rebaseline-kind`, a recorded
    `>=min_reason_chars` reason, a NON-EMPTY declaration, a judgeable pinned recorded set, and FULL
    coverage of it — `uncovered` AND `bad_tokens` both empty, the SAME both-empty rule the grant
    applies. Anything else → False → today's refusal, byte-identical.

    The remaining grant prerequisite, `_change_is_audited`, is deliberately NOT re-asked here: it needs
    the update-from-main merged base, so asking it would put git work ahead of the backstop. It costs
    nothing to omit — T-10850 already made that check a PREFLIGHT that refuses an unaudited ack BEFORE
    the admission slot and the suite, and marks the row `preflight: True` so it is streak-exempt too.
    An admitted-but-unaudited declaration therefore pays a cheap refusal, never the verify."""
    if not owner_rebaseline:
        return False
    if rebaseline_kind not in REBASELINE_KINDS:
        return False
    if len(str(rebaseline_reason or "").strip()) < min_reason_chars:
        return False
    if not [t for t in (declared or []) if str(t).strip()]:
        return False
    recs = _recorded_pinned_waive_records(recorded_assertions)
    if recs is None:
        return False
    _covered, uncovered, bad_tokens = _waive_coverage_over_records(recs, declared)
    return not uncovered and not bad_tokens

def _backstop_rebaseline_hint(recorded_assertions, *, REBASELINE_KINDS=None, _rebaseline_waive_suggested_token=None, _recorded_pinned_waive_records=None, _shell_dq=None) -> str:
    """T-11002 (the card's shape (c), folded into the same change): when the counted cause IS a pinned
    last-green assertion failure, the backstop refusal must NAME the narrow re-baseline as the
    resolution — the reporter confirms this alone would have avoided the bypass request. Returns the
    block to append, or `""` when the cause is not of that kind (nothing plausible-but-wrong is ever
    offered — `lessons/carving-an-exception-into-a-fail-closed-gate.md` §2).

    The pasted token comes from `_rebaseline_waive_suggested_token`, the ONE builder the matcher's own
    records feed (T-10820) — never a second inline composer, which is the drift that made the matcher
    reject its own suggestion (X-0685)."""
    recs = _recorded_pinned_waive_records(recorded_assertions)
    if not recs:
        return ""
    # T-12149: the paste lines come from the ONE composer for this module, so the second
    # (stable, main-varying-value-immune) token shape reaches this refusal by construction.
    paste = "\n".join(_rebaseline_waive_paste_lines(
        recs, indent="    ", _shell_dq=_shell_dq,
        _rebaseline_waive_suggested_token=_rebaseline_waive_suggested_token))
    if not paste:
        return ""
    return (
        "\n\nTHIS STREAK'S CAUSE IS A PINNED LAST-GREEN ASSERTION FAILURE — and `--ack-repeated-abort` "
        "is NOT what it needs (T-11002). If you deliberately revised the old behaviour those assertions "
        "encode, the sanctioned resolution is the NARROW per-assertion re-baseline, which this backstop "
        "ADMITS AUTOMATICALLY once your declaration covers every recorded assertion — no counter-clearing "
        "bypass, no broad flag:\n"
        "  bin/yitc-v2 land --rebaseline --rebaseline-kind <" + "|".join(REBASELINE_KINDS) + "> \\\n"
        "    --rebaseline-reason \"<>=30 chars, tied to the assertion(s) below + the change that "
        "obsoletes them>\" \\\n" + paste + "\n"
        "  (It still requires a fresh GREEN/YELLOW audit-post over the current tree, and the candidate "
        "verify still gates — SPEC-0077 §3a. If you CANNOT tie the reason mechanically to those "
        "assertions, this is a REAL failure: fix it, or escalate — do not re-baseline it.)")

def _preflight_waive_keys(declared) -> list:
    """T-11479: the KEY half of each non-empty `--rebaseline-waive` token, in declaration order and
    de-duplicated. The key is the text before the first `::` — the same split
    `_waive_coverage_over_records` performs, kept in one shape so the preflight cannot address a
    different file from the one the matcher will judge. Pure."""
    keys = []
    for raw in (declared or []):
        t = str(raw).strip()
        if not t:
            continue
        k = t.partition("::")[0].strip()
        if k and k not in keys:
            keys.append(k)
    return keys

def _preflight_acquire_pinned_entries(keys, W, main_wt, merged_base, branch, *,
                                      _run_pinned_verify, _run_git_cap,
                                      _pinned_failure_test_file, _PREFLIGHT_ACQUIRE_INCONCLUSIVE=None,
                                      entries=None) -> "tuple | None":
    """T-11479: obtain the pinned failing entries for ONLY the last-green test file(s) `keys` names.

    T-12254 — `entries` is the ALREADY-ACQUIRED failing set: when it is not None the local
    `_run_pinned_verify` is NOT spawned and that list is used in its place. Its one caller is the
    routed land (SPEC-0203), whose ONE box request already ran the FULL pinned leg and whose envelope
    therefore carries a SUPERSET of what a narrowed local re-run could have said. Everything else on
    this path is unchanged and deliberately so — the runnable-key existence probe, the inconclusive
    fail-open, and the scoping filter all still run, in this one home, so a routed judgement and a
    local one differ in the entries' PROVENANCE and in nothing else. `entries=[]` is a real answer
    ("the pinned leg named no failures"), not an absent one, and is honoured as such.

    Returns `(entries, runnable_keys)`, or **None** when the acquisition could not be established —
    which the caller reads as ADMIT (fail-open, per the block comment above).

    WHY THE CALLER MUST CHECK EXISTENCE, AND WHY IT IS CHECKED HERE. `_run_verify_tests`'s own `only`
    contract says it NARROWS the discovered set and never widens it, so a name the glob did not
    discover is simply absent — an empty selection returns `[]`, which reads as GREEN. This function is
    the caller that owes that check: a key is `runnable` only when `tests/<key>` EXISTS at
    `merged_base` (the last-green tree the pinned leg overlays). Keys that do not resolve are NOT
    judged at all — a consumer verify-LAYER key is a legitimate token that names no file, and refusing
    it here on an unproven basis is exactly the invented refusal the fail-open rule forbids.

    ONE FILE, NO ADMISSION SLOT. `admission_slots=None` and `workers=1`: this runs a single test file
    in a single subprocess and therefore does not enter the shared SPEC-0132 verify-admission bound the
    ~24-worker candidate/pinned pools are bounded by. That is the point — the judgement must be reached
    BEFORE the slot, or it has not moved at all.

    Everything else about the pinned construction is UNCHANGED and is not re-derived here: the same
    `_run_pinned_verify` builds the same detached worktree, applies the same last-green overlay + prune,
    and materializes the same merged_base engine. Only the FILE SET is narrowed."""
    runnable = []
    for k in keys:
        try:
            probe = _run_git_cap(["cat-file", "-e", f"{merged_base}:tests/{k}"], W)
        except Exception:                      # noqa: BLE001 — a fact about the checker, never a verdict
            return None
        if getattr(probe, "returncode", 1) == 0:
            runnable.append(k)
    if not runnable:
        return None                            # nothing this run could speak about → admit
    if entries is None:
        try:
            out = _run_pinned_verify(W, main_wt, merged_base, branch, workers=1, admission_slots=None,
                                     only=set(runnable))
        except Exception:                      # noqa: BLE001 — the runner itself could not run
            return None
    else:
        out = entries                          # T-12254: the routed land's envelope, already acquired
    entries = [str(e) for e in (out or [])]
    if any(any(m in e for m in _PREFLIGHT_ACQUIRE_INCONCLUSIVE) for e in entries):
        return None                            # a statement about the CHECKER → admit
    # Keep only what this narrowed run can speak about. The consumer zero-probe guard runs regardless
    # of `only` and may contribute layer entries whose key was never asked for; judging a token against
    # those would be judging it against a set this call did not scope.
    return ([e for e in entries if _pinned_failure_test_file(e) in runnable], runnable)

def _preflight_waive_coverage_refusal(declared, acquired, *, _rebaseline_waive_coverage,
                                      _surface_failing_assertions) -> list:
    """T-11479: the preflight's waive verdict — the `bad_tokens` of the SAME
    `_rebaseline_waive_coverage(entries, tokens)` call the grant makes, or `[]` (admit).

    `acquired` is `_preflight_acquire_pinned_entries`'s return: `None` → admit, else
    `(entries, runnable_keys)`. Only tokens whose KEY is in `runnable_keys` are judged, for the reason
    stated there. `covered` / `uncovered` are DISCARDED BY CONTRACT — see the block comment: this
    refuses on token binding alone, which is a strict subset of what the grant refuses.

    Pure apart from the injected authority. Nothing here decides coverage; if this function ever grows
    a matching rule of its own, that is the second matcher the split exists to prevent."""
    if acquired is None:
        return []
    entries, runnable = acquired
    toks = [str(t).strip() for t in (declared or []) if str(t).strip()]
    toks = [t for t in toks if t.partition("::")[0].strip() in set(runnable or [])]
    if not toks:
        return []
    _covered, _uncovered, bad_tokens = _rebaseline_waive_coverage(
        entries, toks, _surface_failing_assertions=_surface_failing_assertions)
    return bad_tokens

def _environmental_waive_bindings(bad_tokens, acquired, recorded_assertions, recorded_locator, *,
                                  _pinned_failure_test_file=None,
                                  _recorded_pinned_waive_records=None) -> tuple:
    """T-12033 (SPEC-0077 §3a): the TWO-PART binding the `environmental` waive kind — and ONLY that
    kind — is granted on. Returns `(bad_tokens, bindings, broken_keys)`.

    THE PROBLEM IT SOLVES, measured (task/T-12008, 2026-09-03). A pinned test that fails under the
    ~1295-file parallel verify and PASSES 16/16 in isolation is a LOAD flake. The T-11479 preflight
    re-runs the named file alone to judge the operator's token cheaply — so for exactly this class the
    isolated re-run passes, the token binds NOTHING, and an owner-ACKed waive is refused `no-match`.
    The flake signature itself defeated the binding; the same cause refused 4 branches in 24h, and the
    ack had no representable form at all (the only paths left were re-running the gate, which
    CHARTER §P7 forbids, or waiting on the de-flake card).

    THE CONJUNCTION, fail-closed on EACH part — a token binds here only when BOTH hold:
      (i)  the isolated preflight of EVERY named-and-runnable file PASSED, and
      (ii) the token's key is named by this branch's most recent RECORDED land abort, AND that row
           yields a LOCATOR — a row with no `ts` is not bindable evidence (see below).
    (i) says the check is healthy HERE; (ii) says the full run really did record it failing. Neither
    alone is evidence of a load flake: (i) alone is just a green file, and (ii) alone is a failure
    with no proof it is environmental.

    (i) IS EVALUATED FIRST AND IS ALL-OR-NOTHING (audit-pre finding, 2026-09-04). If the isolated run
    produced a failing entry for ANY named-and-runnable key, this returns IMMEDIATELY with
    `bad_tokens` UNCHANGED, `bindings` EMPTY, and `broken_keys` naming every such key — NO token is
    cleared by (ii) in that return, not even one for a DIFFERENT key that would otherwise bind. The
    ordering is load-bearing, not cosmetic: `environmental` asserts "healthy and runnable HERE", so a
    single file failing isolated refutes the KIND for the whole declaration, and a multi-token ack
    must not be able to smuggle a prior-abort clearance past a provably broken file. The caller turns
    a non-empty `broken_keys` into a refusal naming `broken` as the honest kind.

    A token failing (ii) alone simply STAYS in `bad_tokens` as `no-match`, and its siblings are
    unaffected — that asymmetry is deliberate: (i) refutes the KIND, (ii) merely fails to find
    evidence for ONE token.

    `acquired is None` (the acquisition could not be established) returns the inputs UNCHANGED —
    nothing was proven, so nothing is cleared AND nothing is refused. That is the T-11479 preflight's
    own fail-open rule, unchanged: this arm may only make a refusal reachable or cheaper, never
    invent one from an unestablished fact.

    THE RECORDED SIDE IS READ THROUGH THE EXISTING FAIL-CLOSED CLASSIFIER
    (`_recorded_pinned_waive_records`), never a fresh string match — so the prior-abort row is parsed
    by the SAME authority the land backstop's admission pre-check uses, and a row that reader refuses
    to judge (candidate-suite, unkeyed, textless, or the honest no-assertion marker) admits NOTHING
    here either. A `None` from it means "this row cannot be judged" and therefore binds nothing.

    WHY THIS DOES NOT REINTRODUCE THE T-10977 COIN FLIP. That rule requires a token not to "move
    between runs". Both conjuncts are STABLE facts about this branch — a recorded journal row that
    does not change, and an isolated verdict taken in a single subprocess outside the contended pool.
    Neither is the re-rolled full-run outcome whose instability is the whole problem being solved.

    Pure: no git, no I/O, no clock. The caller supplies the recorded row AND its locator, so this
    function never decides WHICH row is "the most recent" (that is
    `_recorded_pinned_failure_row`'s one job)."""
    if acquired is None:
        return bad_tokens, [], []
    entries, runnable = acquired
    runnable = set(runnable or [])

    # Conjunct (i), FIRST and ALL-OR-NOTHING. `entries` is already narrowed by
    # `_preflight_acquire_pinned_entries` to keys this run asked about, but the membership test is
    # kept explicit so the rule reads off this function rather than off a caller's invariant.
    broken_keys = []
    for e in (entries or []):
        k = _pinned_failure_test_file(e)
        if k in runnable and k not in broken_keys:
            broken_keys.append(k)
    if broken_keys:
        return bad_tokens, [], broken_keys

    # Conjunct (ii). Only `no-match` tokens are candidates: `ambiguous` and
    # `insufficient-bare-token` are defects of the TOKEN's own shape, which no amount of prior-abort
    # evidence repairs, and clearing them here would widen the C1/C2/C3 vocabulary this card leaves
    # untouched.
    # THE LOCATOR IS PART OF CONJUNCT (ii), NOT DECORATION (audit-post finding, 2026-09-04). A row
    # carrying no `ts` yields no locator, and binding on it would record a `waive_binding` whose
    # `locator` is null — a grant that cannot be traced back to the evidence that justified it, which
    # is precisely the accountability this kind's record exists to provide (and which SPEC-0077 §3a
    # states as part of the rule). `_recorded_pinned_failure_row`'s own contract already says "a
    # locator is evidence, and an absent timestamp is not evidence of a row"; this is that sentence
    # enforced rather than merely asserted. Fail-closed: no locator, no bind, token stays `no-match`.
    recs = _recorded_pinned_waive_records(recorded_assertions) if recorded_locator else None
    recorded_keys = {r["test_file"] for r in (recs or [])}
    remaining, bindings = [], []
    for t in (bad_tokens or []):
        key = str(t.get("token", "")).partition("::")[0].strip()
        if t.get("why") == "no-match" and key in runnable and key in recorded_keys:
            bindings.append({"token": t.get("token"), "key": key, "mode": "prior-abort",
                             "locator": recorded_locator, "isolated": "pass", "full_run": None})
        else:
            remaining.append(t)
    return remaining, bindings, []


def _environmental_broken_refusal_text(broken_keys, entries, *, _rebaseline_waive_suggested_token=None,
                                       _pinned_entry_waive_record=None,
                                       _surface_failing_assertions=None, _shell_dq=None) -> str:
    """T-12033: the COMPLETE refusal for an `environmental` declaration whose named file FAILS its
    isolated preflight. This branch is the only one that established what happened, so exactly one
    diagnosis reaches the operator and it is composed here, never as a fragment printed above
    someone else's conclusion (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §2).

    It names the honest kind (`broken`), states WHY the declaration is refuted rather than merely
    unproven, and pastes the bindable token(s) from the ONE builder the matcher's own records feed
    (`_rebaseline_waive_suggested_token`) — never a second inline composer, which is the drift that
    once made the matcher reject its own suggestion (X-0685)."""
    _keys = ", ".join(broken_keys)
    _paste = []
    for e in (entries or []):
        rec = _pinned_entry_waive_record(e, _surface_failing_assertions=_surface_failing_assertions)
        if rec["test_file"] not in broken_keys:
            continue
        # T-12149: the bindable lines come from the ONE composer for this module; the not-waivable
        # note stays HERE, because a C3 entry has no token to offer and saying so is this refusal's
        # own judgement, not the composer's (see `_rebaseline_waive_paste_lines`).
        _lines = _rebaseline_waive_paste_lines(
            [rec], indent="  ", _shell_dq=_shell_dq,
            _rebaseline_waive_suggested_token=_rebaseline_waive_suggested_token)
        if not _lines:
            _paste.append(f"  (not waivable — not a test assertion: {rec['assertion'][:80]})")
        else:
            _paste.extend(_lines)
    _paste_txt = ("\n".join(_paste) or "  (nothing bindable was produced by the isolated run)")
    return ("land: --rebaseline REFUSED — you declared `--rebaseline-kind environmental`, which "
            "asserts the pinned check is HEALTHY and RUNNABLE here and failed only under the "
            "FULL-run load. It is not: re-run ALONE, outside the contended pool, the named file "
            f"still FAILS ({_keys}). A check that fails in isolation is not environmental — "
            "THAT IS `broken` (SPEC-0077 §3a / T-12033).\n"
            "This refusal is ALL-OR-NOTHING BY DESIGN: one named file failing isolated refutes the "
            "KIND for the WHOLE declaration, so no sibling token was cleared either, even one a "
            "recorded prior abort would otherwise have bound.\n"
            "RECOVERY — pick the honest one:\n"
            "  * the failure is REAL and your change supersedes that assertion → re-land with "
            "`--rebaseline-kind broken` and the token(s) below;\n"
            "  * the failure is REAL and your change does NOT supersede it → it is a true signal. "
            "FIX it. Do not waive it under any kind.\n"
            f"Bindable token(s) for the `broken` route — paste as-is, do not compose your own:\n{_paste_txt}")


def _preflight_waive_refusal_text(bad_tokens, entries, *, _rebaseline_waive_suggested_token,
                                  _pinned_entry_waive_record, _surface_failing_assertions, _shell_dq=None) -> str:
    """T-11479: the COMPLETE refusal this branch owes the operator — it is the only branch that
    established what happened, so exactly one diagnosis reaches them and it is composed here, never as
    a fragment printed above someone else's conclusion
    (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §2).

    It states what was actually run (the named file(s), not the suite), names each rejected token WITH
    its `why`, and pastes the bindable token(s) built by `_rebaseline_waive_suggested_token` — the ONE
    builder the matcher's own records feed (T-10820), never a second inline composer, which is the
    drift that once made the matcher reject its own suggestion (X-0685). When nothing bindable exists
    it offers NOTHING rather than something plausible-but-wrong."""
    toks = ("REJECTED --rebaseline-waive TOKEN(S):\n- "
            + "\n- ".join(f"{t['token']}  ({t['why']})" for t in bad_tokens) + "\n\n")
    recs = [_pinned_entry_waive_record(e, _surface_failing_assertions=_surface_failing_assertions)
            for e in (entries or [])]
    # T-12149: the ONE composer for this module. This is the renderer that carried the MEASURED
    # incident (task/T-11944, 2026-09-04T22:57:38Z) — it rejected three count-bearing tokens and then
    # pasted three FRESH count-bearing ones — so the stable shape lands here first of all.
    lines = _rebaseline_waive_paste_lines(
        recs, indent="  ", _shell_dq=_shell_dq,
        _rebaseline_waive_suggested_token=_rebaseline_waive_suggested_token)
    if lines:
        paste = ("THE PINNED FAILURE(S) THAT FILE ACTUALLY PRODUCED, AS BINDABLE TOKEN(S) — built by "
                 "the SAME builder the matcher's own records feed (T-10820), so paste them VERBATIM "
                 "rather than composing one by hand:\n" + "\n".join(lines) + "\n")
    elif recs:
        paste = ("That file DID fail, but on nothing this matcher can bind a token to (an unkeyed or "
                 "assertion-less failure). A re-baseline cannot waive it — fix it, or escalate.\n")
    else:
        paste = ("That file produced NO pinned failure at all, so there is nothing for a waive to "
                 "cover. Either your change does not need `--rebaseline`, or the check you meant to "
                 "waive is reported under a different key — the key is the text before the first "
                 "`: ` in a FAILING ASSERTION(S) line, i.e. the test FILE for the kernel sweep or the "
                 "verify LAYER name for a consumer that delegates.\n")
    return ("land: --rebaseline REFUSED — your --rebaseline-waive declaration does not bind "
            "(SPEC-0077 §3a / T-10754 / T-11479). This is the SAME verdict the grant reaches after "
            "the pinned run; it is reached HERE instead, before the verify-admission slot and before "
            "the suite, by running ONLY the pinned file(s) your token names — so a token that binds "
            "to nothing costs seconds rather than a full verify. A re-baseline waives ONLY the "
            "SUPERSEDED old-behaviour check; anything else failing is a real signal and must be "
            "FIXED, not absorbed into the next last-green baseline.\n" + toks + paste)

def _first_attempt_preflight_refusal_text(entries, keys, *, _rebaseline_waive_suggested_token,
                                          _pinned_entry_waive_record, _surface_failing_assertions,
                                          REBASELINE_KINDS=None, _shell_dq=None) -> str:
    """T-12325 (SPEC-0077 §3a) — the COMPLETE refusal a FIRST, UNDECLARED land attempt is owed when the
    pinned copies of the files it touched AND weakened already fail. This branch is the only one that
    established what happened, so exactly one diagnosis reaches the operator and it is composed here,
    never as a fragment above someone else's conclusion
    (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §2).

    IT IS A RENDERER AND IT CAN NEVER ADMIT A LAND. The caller has already decided to refuse — on
    `entries` being non-empty, i.e. on a pinned copy having actually FAILED — before this is called.
    Nothing computed here can reverse that, and in particular the availability of a bindable token
    does not: when the composer yields no line (a C3 / unkeyed / assertion-less failure) this text says
    the `--rebaseline` route is UNAVAILABLE for that failure and routes to fix-or-escalate, which is a
    firmer refusal than the tokenful one, not a softer one. What is withheld in that case is the PASTE
    LINE alone — offering a token that cannot bind is the X-0685 drift, and offering nothing is the
    honest answer (audit-pre finding 1, 2026-09-10).

    THE TOKEN LINES COME FROM THE ONE COMPOSER, AT ONE CALL SITE.
    `_rebaseline_waive_paste_lines` is called ONCE from this function, and no `--rebaseline-waive`
    line is spelled anywhere else in it — that is what keeps this refusal and the post-verify one
    byte-identical BY CONSTRUCTION rather than by a test that has to assert it (T-12149 / T-10850
    (iii)). The surrounding command block is pasted in the shape `_backstop_rebaseline_hint` already
    uses, for the same reason: a recovery line that prints a command the next preflight refuses is not
    a recovery.

    THE A-PRIME AUTHORITY IS NOT TOUCHED, AND IS RESTATED RATHER THAN ASSUMED. This text tells the
    operator WHAT to declare; it does not declare it, and it does not lower what a declaration must
    satisfy — the kind, the `>=30-char` reason MECHANICALLY TIED to the assertions below, and a fresh
    GREEN/YELLOW audit-post over the current tree. It closes with the same
    if-you-cannot-tie-it-this-is-REAL / escalate clause `_pinned_recovery_hint` carries, because a
    refusal that arrives EARLIER must not read as permission that came easier.

    Pure apart from the injected builders: no git, no I/O, no clock."""
    recs = [_pinned_entry_waive_record(e, _surface_failing_assertions=_surface_failing_assertions)
            for e in (entries or [])]
    # THE ONE COMPOSER FOR THIS MODULE, ONE CALL SITE (T-12149). Do NOT spell a `--rebaseline-waive`
    # line anywhere else in this function — that is exactly the drift this composer exists to prevent.
    lines = _rebaseline_waive_paste_lines(
        recs, indent="    ", _shell_dq=_shell_dq,
        _rebaseline_waive_suggested_token=_rebaseline_waive_suggested_token)
    failing = _surface_failing_assertions(list(entries or [])) or []
    lead = ("FAILING ASSERTION(S) — from the pinned/last-green copies of the file(s) YOUR OWN diff "
            "weakened:\n- " + "\n- ".join(failing) + "\n\n") if failing else ""
    if lines:
        remedy = (
            "IF YOUR CHANGE DELIBERATELY SUPERSEDES THOSE ASSERTION(S), this is the declared "
            "re-baseline — paste it VERBATIM (the token(s) are built by the SAME builder the "
            "matcher's own records feed, T-10820, so do NOT compose one by hand):\n"
            "  bin/yitc-v2 land --rebaseline --rebaseline-kind <"
            + "|".join(REBASELINE_KINDS or ()) + "> \\\n"
            "    --rebaseline-reason \"<>=30 chars, tied to the assertion(s) above + the change that "
            "obsoletes them>\" \\\n" + "\n".join(lines) + "\n")
    else:
        remedy = (
            "THOSE FAILURE(S) CANNOT BE RE-BASELINED. They bind no waive token (an unkeyed or "
            "assertion-less failure), so `--rebaseline` would have nothing to waive and declaring it "
            "would be refused as well. This is a REAL signal: FIX it, or escalate.\n")
    return ("land: REFUSED before the verify — the pinned/last-green copies of the test file(s) this "
            "branch both TOUCHED and WEAKENED already FAIL (SPEC-0077 §3 / §3a, T-12307 / T-12325). "
            "Only those file(s) were run — " + ", ".join(keys or []) + " — in a single subprocess "
            "taking no verify-admission slot, so this verdict cost seconds instead of the full "
            "two-leg verify a first attempt used to pay to learn it. The CANDIDATE leg was NOT run "
            "and its result for this branch is UNKNOWN, not passing.\n\n" + lead + remedy +
            "\nAUTHORITY (SPEC-0077 §3a A-prime) IS UNCHANGED BY THIS EARLIER REFUSAL: the owner "
            "ACKs, OR a dispatched Worker SELF-CLEARS — the latter ONLY when candidate verify is "
            "GREEN, a FRESH audit-post for this branch's task is GREEN, `--no-tests` is absent, the "
            "`>=30-char` reason is recorded, AND that reason is MECHANICALLY TIED to the EXACT "
            "assertion(s) above plus the declared behaviour/harness change that obsoletes them. "
            "Free-form 'this looks stale' is NOT sufficient.\n"
            "IF YOU CANNOT MAKE THAT TIE: ESCALATE — `blocked-on-land <task> <reason>`, worktree "
            "intact. That escalation is the CORRECT outcome, not a failure: SPEC-0121's "
            "default-under-uncertainty is STOP, and hearing this sooner never overrides it.\n")


def _recorded_pinned_failure_assertions(events, branch) -> list:
    """T-11686: the assertion strings of the MOST RECENT recorded pinned failure for `branch`, over
    BOTH shapes the journal records one in. `[]` when nothing of either shape is recorded.

    THE SECOND SOURCE, AND WHY IT IS NEEDED. Until this reader existed the offer scanned ONLY
    `land_completed` rows with `status == "abort"` for this branch. A branch that reddens as a
    DISSOLVED BATCH MEMBER never emits such a row at all: its pinned failures land on
    `land_member_verdict.red_assertions` (SPEC-0184). So a member-reddened branch — REQUIRED to
    declare a re-baseline, and forbidden to compose the token by hand — was structurally denied the
    tokens (measured on task/T-11596 as a member of bat-79790f94cfa8, 2026-08-27T04:17:25Z; its land
    was stopped by hand twice). The member row's entries are ALREADY the surfaced
    `[pinned/last-green] <key>: <assertion>` one-liners `_recorded_pinned_waive_records` reads back,
    so this adds a SOURCE of already-recorded data, never a new format or a new classifier.

    MOST-RECENT WINS ACROSS THE TWO SHAPES, not per shape — one reverse walk, first match returns.
    That is the only reading under which the offer keeps quoting the branch's LATEST recorded
    failure once a second shape can carry one.

    NOTHING IS JUDGED HERE. This returns raw strings; whether they are re-baselineable stays with
    the fail-closed `_recorded_pinned_waive_records` (which returns None for a candidate-suite,
    unkeyed, textless or `(no assertion captured)` row) and with `_rebaseline_waive_suggested_token`.
    No attribution gate is widened and no blame moves — this only chooses WHICH recorded list to
    hand over. Pure: journal rows in, list out; no git, no I/O.

    The `main` / no-branch guard lives HERE rather than in the caller so a later reader inherits it.

    T-12033 — THE WALK ITSELF MOVED into `_recorded_pinned_failure_row` and this is now its thin
    wrapper, returning the assertions half. Nothing about WHICH row is chosen changed, and no caller
    of this function sees a behaviour difference; the split exists because the T-12033 environmental
    waive needs the SAME row's LOCATOR to record what it bound to, and a second reverse walk could
    disagree with this one about what "the branch's most recent recorded pinned failure" is
    (CHARTER §P5 — the T-11002 one-authority idiom applied one seam over)."""
    return _recorded_pinned_failure_row(events, branch)[0]


def _recorded_pinned_failure_row(events, branch) -> tuple:
    """T-12033: the ONE walk behind `_recorded_pinned_failure_assertions` — returns
    `(assertions, locator)` for the MOST RECENT recorded pinned failure on `branch`, or `([], None)`.

    The body is `_recorded_pinned_failure_assertions`' own, carried over VERBATIM: both recorded
    shapes (`land_completed{abort}.failing_assertions` and `land_member_verdict.red_assertions`),
    MOST-RECENT-WINS ACROSS the two shapes (one reverse walk, first match returns), and the
    `main` / no-branch guard. The ONLY addition is the locator — `events.jsonl#ts=<ISO>`, the
    D-0030 materialized-journal citation form — so a consumer can record WHICH row it read rather
    than asserting that one existed. `None` when the row carries no `ts`; a locator is evidence, and
    an absent timestamp is not evidence of a row.

    NOTHING IS JUDGED HERE (unchanged): raw strings out. Whether they are re-baselineable stays with
    the fail-closed `_recorded_pinned_waive_records`. Pure: journal rows in, tuple out; no git, no I/O."""
    if not branch or branch == "main":
        return [], None
    for e in reversed(events or []):
        d = e.get("data") or {}
        if d.get("branch") != branch:
            continue
        t = e.get("type")
        if t == "land_completed":
            if d.get("status") != "abort":
                continue
            found = [str(a) for a in (d.get("failing_assertions") or [])]
        elif t == "land_member_verdict":
            found = [str(a) for a in (d.get("red_assertions") or [])]
        else:
            continue
        if found:
            ts = e.get("ts")
            return found, (f"events.jsonl#ts={ts}" if ts else None)
    return [], None


def _first_attempt_rebaseline_offer(events, branch, *, _rebaseline_waive_suggested_token=None, _recorded_pinned_waive_records=None, _recorded_pinned_failure_assertions=None, _shell_dq=None) -> str:
    """T-11347: the tokens for the FIRST `--rebaseline` attempt, offered by the PARSE-TIME refusal.

    Two refusals could quote a waive token and only one did. `_backstop_rebaseline_hint` pastes them,
    but only past `LAND_REPEATED_ABORT_THRESHOLD` — the REPEATED-abort path. The parse-time refusal
    (`--rebaseline` with no `--rebaseline-waive`) explained the FORMAT and quoted nothing, so on a
    first attempt the caller hand-composed the token from the abort output. Four captures in twelve
    days came off that one path: two hand-composed tokens that came out WRONG (a token quoting a
    PASSING assertion, 2026-08-08; one degenerating to a pass-count for a script-style test file,
    2026-08-09) and two reports of the absence itself (2026-08-17, 2026-08-20).

    NOTHING NEW IS COMPUTED. This reads the rows the journal ALREADY recorded, through the SAME two
    builders — `_recorded_pinned_waive_records` then
    `_rebaseline_waive_suggested_token`, the ONE builder the matcher's own records feed (T-10820).
    Never a second inline composer: that drift is what made the matcher reject its own suggestion
    (X-0685). Reachable at parse time because the `--task/--branch` re-exec happens EARLIER, so `HEAD`
    already resolves to the task branch by the time the refusal is composed.

    T-11686 WIDENED THE SOURCE, NEVER THE JUDGEMENT. Collection is delegated to
    `_recorded_pinned_failure_assertions`, which returns the most recent recorded pinned failure over
    BOTH row shapes — `land_completed{abort}.failing_assertions` AND
    `land_member_verdict.red_assertions`, so a branch that reddened as a dissolved batch member (which
    emits no abort row of its own) can obtain its tokens. The backstop is UNCHANGED and still receives
    its assertions as a parameter from `cmd_land` via `_land_last_abort_assertions`, which joins on the
    repeated-abort streak cause key: only this site collects, so only this site delegates.

    FAIL-CLOSED AT EVERY STEP, returning `""` (the message then degrades to its format-only text, the
    honest answer when nothing has yet recorded a pinned failure): no branch or `main`; no recorded row
    of either shape carrying assertions; a row `_recorded_pinned_waive_records` refuses (candidate-suite,
    unkeyed, or the `(no assertion captured)` marker); no bindable token. Nothing plausible-but-wrong is
    ever offered (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §2).

    THIS CHANGES WHAT IS PRINTED, NEVER WHETHER THE LAND REFUSES — the caller still has to declare the
    waive, and an empty declaration still covers nothing (SPEC-0077 §3a / T-10754)."""
    recs = _recorded_pinned_waive_records(_recorded_pinned_failure_assertions(events, branch))
    if not recs:
        return ""
    # T-12149: same ONE composer as `_backstop_rebaseline_hint`, so the two refusals stay
    # byte-identical STRUCTURALLY (what T-11347 AC4 previously had to assert) and both gain the
    # stable token shape in one place.
    paste = "\n".join(_rebaseline_waive_paste_lines(
        recs, indent="    ", _shell_dq=_shell_dq,
        _rebaseline_waive_suggested_token=_rebaseline_waive_suggested_token))
    if not paste:
        return ""
    return (
        "\n\nTHE TOKEN(S) FOR THIS BRANCH'S LAST RECORDED PINNED FAILURE(S) — built here by the SAME "
        "builder the matcher's own records feed (T-10820), so paste them VERBATIM rather than composing "
        "one by hand (T-11347):\n" + paste + "\n"
        "  (Check they name the assertion(s) THIS change supersedes before declaring them: they come "
        "from the last recorded pinned failure of THIS branch — an abort of its own, or the "
        "member verdict of a batch it reddened in — and a re-baseline waives ONLY the superseded "
        "old-behaviour check — anything else failing is a REAL signal to fix or escalate.)")

def _in_hermetic_verify_child(*, _VERIFY_SANDBOX_PREFIX=None) -> bool:
    """True iff THIS process is a test subprocess spawned by the land-verify runner — i.e. its own
    TMPDIR resolves to a REAL directory at or under a `_VERIFY_SANDBOX_PREFIX` sandbox root."""
    raw = os.environ.get("TMPDIR", "").strip()
    if not raw:
        return False
    try:
        resolved = Path(raw).resolve()
        if not resolved.is_dir():
            return False
    except OSError:
        return False
    return any(part.startswith(_VERIFY_SANDBOX_PREFIX) for part in resolved.parts)

def _uncovered_path_provenance(paths, W: Path, merged_base: "str | None", *, _run_git_cap) -> dict:
    """T-11001 (X-0823) — for each path the currency gate is about to REFUSE on, state whether its
    content is IDENTICAL to the merged main tip or AUTHORED BY THIS BRANCH. Returns `{path: verdict}`
    over a closed three-value vocabulary.

    WHY THIS EXISTS, given the answer is architecturally knowable. kupiclub reported (X-0823) a land
    that aborted naming two spec files they believed carried nothing but content merged in from main.
    Reproduction (7 shapes, recorded on T-11001) showed the mechanism was RIGHT: a path identical to
    the merged main tip is not in the observable footprint at all — `_merged_tree_delta_paths` selects
    exactly the paths whose HEAD content DIFFERS from that tip — so it can never reach the refusing
    bucket. But the refusal said only "a post-audit edit or a conflict resolution", which made the
    reporter's reading UNFALSIFIABLE from the output: they could not tell "the gate considered these
    and found them branch-authored" from "the gate never asked whether they were imports", and the only
    way to find out was to diff by hand. A true-but-SILENT invariant is what cost them that time. So
    this MEASURES the fact instead of leaving the operator to infer it from the footprint's
    construction — and the measurement, not the inference, is the deliverable.

    EXISTENCE IS PROBED SEPARATELY FROM CONTENT (audit-pre finding, absorbed). `git cat-file -e` answers
    "is the path present at this rev", so a legitimately ABSENT blob is never confused with a git
    FAILURE. Presence first, then content:
      `identical-to-main` — present on BOTH sides, blobs byte-equal. The pure merge import.
      `branch-authored`   — present on both sides with DIFFERING blobs, OR present on exactly ONE side.
                            The one-sided case is branch-authored in BOTH directions and that symmetry
                            is deliberate: present-at-HEAD-only is a file this branch ADDED, and
                            present-at-tip-only is one it DELETED. A deletion does reach the uncovered
                            set (`git diff --name-only` reports deletions), and calling it "unknown"
                            would under-report the branch's own work at exactly the moment the operator
                            is asking what the branch did.
      `unknown`           — the existence probe itself errored, or a blob could not be read where the
                            probe said it exists. The reserved did-not-answer value
                            (`lessons/carving-an-exception-into-a-fail-closed-gate` §1): reported as
                            such and NEVER collapsed into either claim.

    REPORT-ONLY. Nothing reads this to decide anything: the offending set stays `own_post_audit +
    unclassified` and is byte-identical with or without this map. It costs two `git` calls per path,
    on a land that is already refusing — off the hot path entirely. Pure: never raises."""
    out: dict = {}
    if not paths:
        return out

    # THE PROBE IS THREE-STATE, NOT A BOOLEAN (audit-post finding, absorbed). A bare
    # `git cat-file -e <rev>:<path>` returns nonzero for BOTH "the path is absent at this rev" and
    # "git could not answer at all" (an unresolvable rev, a broken repo) — so reading it as a boolean
    # puts a PLUMBING FAILURE inside the success vocabulary, and a one-sided failure would then be
    # reported as `branch-authored`: a claim about the branch's work derived from our own breakage.
    # That is precisely `lessons/carving-an-exception-into-a-fail-closed-gate` §1, and the three-value
    # OUTPUT vocabulary does not help unless the MEASUREMENT underneath is three-valued too.
    # Resolved in two steps: first prove the rev itself resolves; only then is a nonzero lookup
    # genuinely "not in that tree". Rev validity is resolved ONCE per rev, not per path.
    def _rev_ok(rev):
        return _run_git_cap(["rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}"], W).returncode == 0

    def _present(rev, path):
        """True / False / None — None means the probe could not answer, never 'absent'."""
        if not _rev_valid.get(rev):
            return None
        return _run_git_cap(["rev-parse", "--verify", "--quiet", f"{rev}:{path}"], W).returncode == 0

    _rev_valid = {}
    if merged_base:
        try:
            _rev_valid = {"HEAD": _rev_ok("HEAD"), merged_base: _rev_ok(merged_base)}
        except Exception:
            _rev_valid = {}

    for raw in paths:
        p = str(raw).strip()
        if p.startswith("./"):
            p = p[2:]
        if not merged_base:
            out[raw] = "unknown"          # nothing to compare against — never guess a provenance
            continue
        try:
            at_head, at_tip = _present("HEAD", p), _present(merged_base, p)
            if at_head is None or at_tip is None:
                out[raw] = "unknown"              # the probe itself failed — claim NEITHER side
                continue
            if at_head != at_tip:
                out[raw] = "branch-authored"      # added on this branch, or deleted by it
                continue
            if not at_head:
                out[raw] = "unknown"              # absent on BOTH sides — nothing measurable
                continue
            h = _run_git_cap(["show", f"HEAD:{p}"], W)
            b = _run_git_cap(["show", f"{merged_base}:{p}"], W)
            if h.returncode != 0 or b.returncode != 0:
                out[raw] = "unknown"              # present per the probe, unreadable in fact
                continue
            out[raw] = "identical-to-main" if h.stdout == b.stdout else "branch-authored"
        except Exception:
            out[raw] = "unknown"
    return out

def _land_preflight_currency_lines(W: Path, branch: str, base_rev: "str | None", *, _run_git_cap,
                                   EVENTS_PATH, _classify_inert_paths,
                                   _DERIVED_MERGE_ARTIFACTS=None,
                                   _anchor_signature_of_text=None,
                                   _header: "str | None" = None,
                                   _split_out: "dict | None" = None, _land_audited_footprint_lines=None, _land_audited_footprint_split=None, _merged_tree_delta_paths=None) -> "list[str]":
    """T-11313 — PHASE 2 of the pre-flight: the MEASURED audit-currency blocker, asked AFTER
    update-from-main. Returns `[]` when nothing is reportable.

    THE ORDER IS THE SUBTLETY AND IT IS COUNTER-INTUITIVE (the card's AC2 fence). Currency is judgeable
    only AFTER the merge, because THE MERGE IS WHAT BREAKS IT: a conflict resolution is content the
    recorded audit never reviewed, so post-merge HEAD goes beyond the clean re-merge of the audited
    commit. Asked BEFORE the merge the same question answers GREEN, and a pre-flight that reported
    that would be confidently wrong. T-11332 SPLIT that sentence by class without changing the
    ordering fact: a HAND-made resolution (and any resolution whose mechanical re-derivation differs
    or cannot be computed) still lands in `own_post_audit` and is still reported here, while one
    PROVEN byte-identical to what `_classify_land_merge_conflicts` itself produces from the two sides
    lands in `mechanical_resolve` and is NOT a blocker. The ordering is unchanged — which bucket a
    path falls into is STILL only knowable after the merge — so this phase still cannot be moved
    ahead of it.

    NO SECOND ORACLE: it runs the currency gate's OWN primitives, in the gate's own order —
    `_merged_tree_delta_paths`, the `_classify_inert_paths` narrowing, `_land_audited_footprint_split`,
    `_land_audited_footprint_lines` — against the same `merged_base` land itself passes. REPORT-ONLY:
    it refuses nothing, raises nothing, and a classifier that could not answer simply reports the
    did-not-answer bucket land already refuses on.

    THE `behind == 0` BASE IS DELIBERATE. There `base_rev` is the current main sha, so the delta is the
    branch's WHOLE diff vs main — which is EXACTLY what land passes as `merged_base` at its own gate
    (land's merged_base IS the main tip it merged). `_land_audited_footprint_split` does not read that
    delta as changed-since-the-audit content: it intersects the footprint with
    `git diff --name-only <audit_commit> HEAD`, so every audited path lands in the `as_audited` COUNT
    and reaches no blocking bucket. Suppressing the report at `behind == 0` would delete the T-11309
    case, which refused on audit currency with the branch 0 behind and nothing merged at all.

    `_header` REPLACES THE FIRST LINE AND NOTHING ELSE (T-11391). The second consumer — the pre-queue
    REFUSAL `_land_prequeue_currency_refusal` — needs this verdict under a different sentence: it is
    not a `worktree sync` report and it is not measured after update-from-main. Rendering it a second
    way would be the second renderer this whole file argues against, so the one line that is
    site-specific becomes a parameter. Default None reproduces the `worktree sync` line
    byte-for-byte, so that caller is unchanged; the COMPUTATION is not parameterised at all.

    `_split_out`, when a dict is supplied, is UPDATED with the computed split — the same
    single-computation discipline applied to the MACHINE record: the refusal consumer needs the
    verdict's `abort_detail` as well as its text, and re-deriving the split beside this call to get
    it would be the second computation everything here exists to prevent. It is written only when
    the split was actually obtained, so an unsupplied or untouched sink means "nothing was
    computed", never "computed empty". Report-only for the default caller (None ⇒ ignored)."""
    if not base_rev:
        return []
    # EVERY step is inside the fail-open boundary (audit-post finding, absorbed). Only
    # `_merged_tree_delta_paths` was wrapped before, so a raising inert classifier or split could
    # still propagate out of a REPORT and abort a sync that had already merged successfully — a
    # report is never entitled to fail the operation it is describing.
    try:
        delta = _merged_tree_delta_paths(W, base_rev, _run_git_cap=_run_git_cap)
        observable = [p for p in delta if _classify_inert_paths([p])[0] == "observable"]
        split = _land_audited_footprint_split(W, branch, base_rev, observable,
                                              _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH,
                                              merged_delta=delta,
                                              # T-11332 — the pre-flight PREDICTS the gate, so it must
                                              # be handed the gate's own injections; un-injected it
                                              # would report a re-audit the gate no longer requires.
                                              _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                                              _anchor_signature_of_text=_anchor_signature_of_text)
    except Exception:                          # noqa: BLE001 — not a post-merge tree, or a step that
        return []                              # could not answer: report nothing, abort nothing
    if not split:
        return []
    if _split_out is not None:
        _split_out.update(split)               # T-11391 — the ONE computation, published once
    if not ((split.get("own_post_audit") or []) or (split.get("unclassified") or [])):
        return []                              # suppressed-when-clean: no blocker, no noise
    return [_header or
            ("worktree sync: PRE-FLIGHT BLOCKER — A RE-AUDIT WILL BE REQUIRED before this branch can land "
             "(SPEC-0077 §3a audited-diff currency), measured AFTER update-from-main:"),
            *(f"  {ln}" for ln in _land_audited_footprint_lines(split))]

def _mechanically_resolved_conflicts(paths, W: Path, audit_commit: "str | None",
                                    merged_base: "str | None", *, _run_git_cap,
                                    _DERIVED_MERGE_ARTIFACTS=None,
                                    _anchor_signature_of_text=None, _classify_land_merge_conflicts=None, _merge_tree_conflict_stages=None, _merged_tree_oid_anchor_signer=None) -> set:
    """T-11332 — the SUBSET of `paths` PROVEN to be exact MECHANICAL auto-resolutions of a merge
    conflict, i.e. content `_classify_land_merge_conflicts` itself produced from the two sides and
    that this function RE-DERIVES and compares. Everything else is absent from the subset and stays
    refused exactly as today.

    WHY THIS CLASS IS NOT UNAUDITED CONTENT. `own_post_audit` is documented as "a post-audit edit OR a
    conflict resolution", and the sibling pre-flight adds that the resolution may be "hand-made or one
    of `_classify_land_merge_conflicts`'s four mechanical classes". So content the TOOL produced,
    deterministically, from two already-audited sides was refused identically to content a human
    authored — and an external auditor, a system-wide single point of failure, was then asked to
    review a string no human chose. That is the same claim `closure_side_effect` (T-10998) makes one
    step earlier in the same function: the merge the lifecycle REQUIRES cannot be the thing that makes
    the lifecycle unauditable. Measured cohort (2026-08-19/20, 162 merge-conflict land aborts): the two
    `_ROW_APPEND_LEDGERS` — `specs/yitc-v2-rule-test-ledger.md` (24) and `kernel-vs-self-manifest.md`
    (23) — plus the `specs/*.yaml` `implements_signature:` class. `graph/index.json` (~43) is INERT and
    never reaches a blocking bucket at all, so it is not part of this cohort.

    Returns a SUBSET, never a verdict — which is what makes the whole extension fail-closed by
    CONSTRUCTION, exactly as `_governed_closure_side_effects`: an empty return reproduces the
    pre-change behaviour byte-for-byte, so every failure mode here (a git that would not run, an
    unparsable stream, a classifier that raised, an absent injection, an unreadable blob) degrades to
    the old refusal rather than to an admission. There is no reserved "did not answer" value to route,
    because "did not answer" and "no" are the SAME value here
    (`lessons/carving-an-exception-into-a-fail-closed-gate` §1).

    THE THREE AXES — a CONJUNCTION, positive evidence required on each; no axis is an absence of
    objections and none is sufficient alone:
      (a) CONFLICT-MARKED in `merge-tree --write-tree -z <audit_commit> <merged_base>` — the clean
          3-way re-merge of the AUDITED commit with the main tip this attempt merged, which is the
          EXACT comparison `_land_audited_footprint_split` buckets against (and the same command its
          pre-flight sibling `_land_preflight_conflict_audit_lines` runs for its conjunct (iii)), so
          NO second oracle is introduced. This is positive evidence that a conflict existed AT ALL at
          this path: a path whose re-merge is CLEAN and whose HEAD nevertheless differs is a
          post-audit EDIT, never a resolution, and must stay refused.
      (b) `_classify_land_merge_conflicts` — THE one admission authority (T-11216) — RESOLVES the path
          to a `("text", <str>)` verdict, asked over that SAME stream through the index-free
          `_show_stage` seam (plus `_merged_tree_oid_anchor_signer` for the T-11291 same-anchor
          re-derivation). Two ways to fail: the classifier leaves the path `unresolved`, or it returns
          a kind carrying NO text payload (`ours` / `journal`). The second is the
          `lessons/fail-closed-belongs-to-the-reader-not-the-parser` point: to the MERGE path a
          payload-less kind means "resolvable"; to THIS reader it means "no 3-way content to compare",
          and that missing-value judgement belongs at this use site, not in the shared authority.
          Those two kinds are inert paths anyway (`_DERIVED_MERGE_ARTIFACTS` / `.yitc/` state) and so
          cannot reach `own_post_audit` — the branch is a belt, not a load-bearer.
      (c) HEAD's content for the path is BYTE-IDENTICAL to that re-derived text. THE LABEL IS NEVER
          TRUSTED: nothing here reads a marker, a commit subject, or a record claiming a resolution
          happened — the resolution is RE-DERIVED from the two sides and the CONTENT compared. This is
          also what makes the axis sound in REVERSE, which is why a hand-made resolution needs no
          separate exclusion: a hand-typed string byte-equal to the mechanical output IS the
          mechanical output, and any hand resolution that differs by even one byte fails here.

    WHAT IS DELIBERATELY NOT WIDENED. A path whose re-derivation differs from HEAD — because the
    branch merged main more than once, or carries its own post-audit edit to the same file — is a
    MISSED exemption, never a false admission: it stays in `own_post_audit` and the land refuses,
    which is exactly the pre-change outcome. The fail-closed direction is toward the old behaviour on
    every edge.

    PURE + CLASSIFYING ONLY: it decides nothing, refuses nothing and never raises."""
    out: set = set()
    if not paths or not audit_commit or not merged_base or _DERIVED_MERGE_ARTIFACTS is None:
        return out             # no injection ⇒ the ONE authority cannot be asked ⇒ nothing is proven
    want: dict = {}
    for raw in paths:
        p = str(raw).strip()
        if p.startswith("./"):
            p = p[2:]
        if p:
            want.setdefault(p, raw)
    if not want:
        return out
    try:                                                                                  # axis (a)
        mt = _run_git_cap(["merge-tree", "--write-tree", "-z", audit_commit, merged_base], W)
    except Exception:                          # noqa: BLE001 — git could not run: nothing is proven
        return out
    tree, marked, stages = _merge_tree_conflict_stages(getattr(mt, "stdout", "") or "")
    if not tree:
        return out                             # the re-merge did not answer → claim nothing
    conflicted = [p for p in marked if p in want]
    if not conflicted:
        return out                             # nothing here was conflicted at all → not a resolution

    def _stage_blob(path: str, stage: int) -> "str | None":
        """One conflict stage's CONTENT, by oid — the index-free `git show :<n>:<path>`, identical in
        contract to the SPEC-0184 probe's reader. A stage the merge did not produce (add/add has no
        base, modify/delete has no content side) is no 3-way basis, so the resolver refuses."""
        oid = (stages.get(path) or {}).get(int(stage))
        if not oid:
            return None
        try:
            b = _run_git_cap(["cat-file", "blob", oid], W)
        except Exception:                      # noqa: BLE001
            return None
        return b.stdout if getattr(b, "returncode", 1) == 0 else None

    try:                                                                                  # axis (b)
        resolved, _unresolved = _classify_land_merge_conflicts(
            conflicted, W, _run_git_cap=_run_git_cap,
            _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
            _show_stage=lambda stage, path: _stage_blob(path, stage),
            _merged_anchor_signature=(
                _merged_tree_oid_anchor_signer(
                    tree, W, _run_git_cap=_run_git_cap,
                    _anchor_signature_of_text=_anchor_signature_of_text)
                if _anchor_signature_of_text is not None else None))
    except Exception:                          # noqa: BLE001 — could not classify: not an admission
        return out
    for p, verdict in (resolved or {}).items():
        if p not in want:
            continue
        kind, payload = (verdict if isinstance(verdict, tuple) and len(verdict) == 2
                         else (None, None))
        if kind != "text" or not isinstance(payload, str):
            continue                           # resolvable, but with NO content to compare — see (b)
        try:                                                                              # axis (c)
            head = _run_git_cap(["show", f"HEAD:{p}"], W)
        except Exception:                      # noqa: BLE001
            continue
        if getattr(head, "returncode", 1) != 0:
            continue                           # HEAD's content could not be read → never admitted
        if head.stdout == payload:
            out.add(want[p])
    return out

# ── T-11754 (SPEC-0077 §3a × X-1153) — WAS THE REFUSED DRIFT PRODUCED BY LAND'S OWN MERGE? ──────
#
# THE MEASURED PROBLEM, re-confirmed in this repo's own journal before anything was written:
# `audited-diff-stale` fired five times in the three days to 2026-08-28 (task/T-11700, T-11799,
# T-11805, T-11810, T-11813). T-11483 built the fix the reporter asks for — take the audit INSIDE
# the land, over the MERGED tree, so no peer landing during the queue wait can invalidate it — and
# wired it to ONE arm: `_land_integrate` guards it with `owner_rebaseline and _verify_path_touch`.
# The ORDINARY land's currency gate (T-10896) has no in-land re-audit at all, so it still judges a
# record taken PRE-QUEUE on the PRE-MERGE tree. That is X-1153's loop: re-audit off-queue, re-queue,
# lose the race to the next sibling, re-audit again — no ceiling passes burned (T-9543), but
# unbounded wall clock.
#
# WHY `merge_inherited` DOES NOT ALREADY COVER IT (measured, not assumed): a sibling landing a CLEAN
# change into a file the branch also touched classifies as `merge_inherited` and admits today, and
# still admits after a second sibling and a second merge. What the queue wait manufactures is the
# CONFLICTED sub-case. Re-derived from the real objects of the 2026-08-28 18:12 refusal (audit
# T-11805@7ae7667, main 61d758c, branch c4a51d9): the clean re-merge CONFLICTS on the generated
# `<!--GEN:spec-code-map-->` block of kernel-vs-self-manifest.md, no resolver in
# `_classify_land_merge_conflicts` covers that block, HEAD carries the union of the two anchor lists,
# and the path lands in `own_post_audit`. The branch authored nothing there after its audit — but
# `_land_audited_footprint_split` compares HEAD only against the clean re-merge and so cannot say so.
#
# THIS FUNCTION SUPPLIES THE MISSING COMPARISON, and NOTHING ELSE. It never admits anything: it
# answers one question — did this branch AUTHOR content for these paths after its audit? — and it
# answers it from HISTORY SHAPE, which is the one form of the question that has the same meaning at
# every site that needs it. A change to a path can enter a branch two ways: a NON-MERGE commit,
# which is the branch's own authored work, or a MERGE, which is what land's update-from-main
# produces (a conflict resolution is recorded IN the merge commit, which is exactly why it must
# count as merge-produced). So `git log --no-merges <audit_commit>..HEAD -- <path>` EMPTY, for every
# offending path, is the proof: the branch authored none of that content, and whatever HEAD carries
# for those paths this land's own merge put there.
#
# `main_snapshot` IS PART OF THE QUESTION, not a convenience. `<audit_commit>..<branch_tip>` is
# everything reachable from the branch and not from the audit — which includes MAIN'S OWN commits,
# the sibling lands this whole card is about. Left in, they are commits touching the offending path
# and the proof never succeeds (measured against the fixture: the predicate answered False for a
# path no branch commit had ever touched). Excluding them with `^<main_snapshot>` is what narrows
# the walk to the BRANCH'S OWN authored commits, which is the question. The snapshot is the exact
# main the caller is judging against — `merged_base` at the gate, the one `main_rev` at the
# pre-queue predictor — so it can never be a second, differently-timed read of a moving ref (the
# T-10014 discipline).
#
# `branch_tip` IS WHY MERGE COMMITS ARE NOT EXEMPTED, and this is the audit-post RED (2026-08-29,
# high) that shaped the final form. The first cut walked `--no-merges` to HEAD, reasoning that a
# change arriving through a merge must be land's own update-from-main. IT IS NOT: a worker whose
# land died `merge-non-union-conflict` resolves the conflict BY HAND and commits it as a MERGE, and
# that resolution is unaudited content this branch authored — precisely what the rule exists to
# refuse. Skipping merges admitted it. So NO commit is exempted by kind; instead the walk STOPS at
# `branch_tip`, and the caller chooses which tip makes its claim true:
#   - the in-lock gate passes the branch tip captured immediately BEFORE its own step-2
#     `_update_from_main`, so the ONLY merge that can have produced the content is this land's own;
#   - the pre-queue predictor has no such tip and passes the branch ref itself, so a branch that has
#     merged AT ALL since its audit is not proven here and simply queues — the fail-open direction,
#     one queue position, and the gate decides with the strict tip in hand.
#
# UNIVERSAL, NOT MAJORITY — the whole safety argument in one word. A MIXED set (one merge-produced
# path beside one genuinely branch-authored one) returns False, so a real post-audit edit can never
# ride in beside merge drift. FAIL-CLOSED on every unproven input: no paths, no audited commit, any
# git failure → False → today's refusal, byte-identical.
def _offending_drift_is_merge_produced(paths, W: Path, audit_commit: "str | None",
                                       main_snapshot: "str | None", branch_tip: "str | None", *,
                                       _run_git_cap) -> bool:
    """True iff NO branch commit of ANY kind, between `audit_commit` and `branch_tip` and outside
    `main_snapshot`'s history, touched ANY path in `paths`.

    PURE + CLASSIFYING ONLY: decides nothing, refuses nothing, never raises. See the block above for
    why history shape is the right question, why `main_snapshot` and `branch_tip` are both part of
    it, and why the answer must be universal over `paths`."""
    if not paths or not audit_commit or not main_snapshot or not branch_tip:
        return False
    try:
        for p in paths:
            r = _run_git_cap(["log", "--format=%H", "-1",
                              f"{audit_commit}..{branch_tip}", f"^{main_snapshot}", "--", p], W)
            if getattr(r, "returncode", 1) != 0:
                return False                 # git could not answer → nothing is proven
            if (r.stdout or "").strip():
                return False                 # the branch AUTHORED it after its audit
        return True
    except Exception:                        # noqa: BLE001 — never raise into the land; never admit
        return False

def _land_audited_footprint_split(W: Path, branch: str, merged_base: "str | None",
                                  observable_footprint: "list | None", *,
                                  _run_git_cap, EVENTS_PATH, merged_delta: "list | None" = None,
                                  _DERIVED_MERGE_ARTIFACTS=None,
                                  _anchor_signature_of_text=None, _AUDITED_FOOTPRINT_LIST_CAP=None, _governed_closure_side_effects=None, _last_audit_post_for_task=None, _mechanically_resolved_conflicts=None, _uncovered_path_provenance=None, _read_land_events=None) -> "dict | None":
    """T-10896 (X-0738 / X-0696) — PARTITION the branch's OBSERVABLE footprint by PROVENANCE against
    the commit its own audit-post reviewed. This is the primitive both halves of the card need: the
    footprint was computed as a FLAT path set, so nothing could say which part of what is about to
    land the audit actually covered.

    Returns `None` when the branch CLAIMS no task audit coverage — a `work/<slug>` batch (the
    post-close case stays SPEC-0077 §3a's, untouched), no GREEN/YELLOW `audit_post_completed` for the
    task, or an audited commit that is not an ancestor of HEAD. Otherwise:

        {"task", "audit_commit", "base", "as_audited": <int>,
         "merge_inherited": [...], "own_post_audit": [...], "closure_side_effect": [...],
         "mechanical_resolve": [...], "unclassified": [...],
         "truncated": {<bucket>: <exact full count>}}      # only when a listing was cut

    `merge_imports` (T-11059) is present when it could be MEASURED — the number of changed-since-the-
    audit paths whose content is identical to the merged main tip, i.e. the pure merge imports the
    footprint excludes BEFORE any classification runs. It completes T-11001's qualitative note ("a
    merge import cannot be named here") with the quantity, so a reporter facing the refusal sees their
    own changed files ACCOUNTED FOR rather than only being told the excluded category exists.
    It is drawn from `merged_delta` — the caller's RAW `_merged_tree_delta_paths` list, the SAME call
    the observable footprint is derived from — so the count and the exclusion cannot drift. That list,
    and NOT `observable_footprint`, is the right measure: the footprint is TWO composed exclusions, and
    only the raw-delta one means "identical to the merged main tip"; the inert narrowing drops
    bookkeeping paths whose content DIFFERS from that tip (a changed `events.jsonl`, a rebuilt
    `graph/index.json`), which are not imports and must not be counted. Absent when `merged_delta` is
    not supplied or the changed set could not be derived — a count that was not measured is never
    claimed. REPORT-ONLY: nothing branches on it.

    `observable_footprint` is the branch's net footprint vs `merged_base`, ALREADY narrowed to the
    OBSERVABLE paths by the caller. It is passed IN rather than derived here on purpose: the inert
    verdict has exactly ONE authority (`_classify_inert_paths`, SPEC-0064 §4 / T-0631) and a bounded
    set of SANCTIONED consumers, and `_land_integrate` — this function's only caller — is already one
    of them. Growing the consumer set for a pure provenance classifier would be the wrong direction;
    taking the narrowed set as an argument keeps the authority where it is and leaves this function
    doing exactly one thing. `None` here means the caller could not derive the footprint at all
    (a non-post-merge tree) — there is then nothing to partition, so this returns `None` too.

    THE THREE BUCKETS (over that observable footprint — bookkeeping never reaches here):
      - `as_audited` (a count)  — HEAD's content for the path IS the audited content.
      - `merge_inherited`       — the path changed since the audit, but HEAD's content is EXACTLY the
                                  clean 3-way re-merge of the audited commit with the main tip this
                                  attempt merged. Every contributing commit is therefore already-landed
                                  main history, each covered by its OWN task's land+audit.
      - `own_post_audit`        — HEAD's content goes BEYOND that clean re-merge, so this branch put it
                                  there: a post-audit edit OR a conflict resolution. No audit covers it.
      - `closure_side_effect`   — (T-10998, extended T-11072) this branch put it there TOO, but it is
                                  PROVEN to be an exact deterministic governed closure side-effect — the
                                  spec activation flip `task close` writes, the `binding:` declaration it
                                  PRESCRIBES for that spec, or a `lessons/` closure note. Split out of
                                  `own_post_audit` by `_governed_closure_side_effects` (path + exact
                                  diff shape + the already-recorded governed-verb provenance, a
                                  conjunction). NOT a blocker: the closure the lifecycle REQUIRES cannot
                                  be the thing that makes the lifecycle unlandable. Everything that
                                  fails ANY of the three axes stays in `own_post_audit` and refuses.
      - `mechanical_resolve`    — (T-11332) this branch put it there too, but it is PROVEN to be an
                                  exact MECHANICAL auto-resolution: content
                                  `_classify_land_merge_conflicts` — the ONE admission authority —
                                  itself produces from the two sides, RE-DERIVED here and compared
                                  BYTE-FOR-BYTE against HEAD. Split out of `own_post_audit` by
                                  `_mechanically_resolved_conflicts` (conflict-marked in the gate's
                                  own re-merge + resolved by that authority to a text payload +
                                  identical content, a conjunction). NOT a blocker: the merge the
                                  lifecycle REQUIRES cannot be the thing that makes the lifecycle
                                  unauditable, and no audit can review a string no human chose. A
                                  HAND-made resolution differing by one byte, and any path whose
                                  re-derivation cannot be computed, stay in `own_post_audit`.
      - `unclassified`          — the clean re-merge could not be obtained at all. The reserved
                                  "did not answer" value (`lessons/carving-an-exception-into-a-fail-
                                  closed-gate` §1): the classifier may not know, it may never PRETEND
                                  to know, and the caller routes this to REFUSE like `own_post_audit`.

    WHY A CONTENT TEST AND NOT A HISTORY PROXY (audit-pre pass 2, RED). Asking "did a non-merge branch
    commit touch this path" is blind to content a MERGE commit introduced, so a conflict RESOLUTION —
    genuinely unaudited content — read as merge-inherited and kept the admit path open. Comparing HEAD
    against the clean re-merge asks the real question and has no such gap, while keeping the T-10592
    position as a CONSEQUENCE rather than a carve-out: a clean auto-merge of the branch's edit with an
    already-landed sibling's edit to the SAME file reproduces exactly, so it stays admitted (verified
    against a repo carrying the `events.jsonl merge=union` driver, which does not defeat the compare).

    Same primitive + same baseline discipline as `_concurrent_merge_churn_only` (T-9543/T-10592), read
    at PATH level instead of tree level. `merged_base` is the right baseline BY CONSTRUCTION: land's
    step 2 merged exactly it, so it is an ancestor of HEAD — the local equivalent of T-10014's "the
    main HEAD actually merged, never the live ref".

    PURE + CLASSIFYING ONLY: it decides nothing, refuses nothing and never raises. The refusal is
    composed at its ONE call site, so no waive/skip/bypass can hide in here.
    """
    m = re.fullmatch(r"task/(T-\d{4,})", branch or "")
    if not m or not merged_base or observable_footprint is None:
        return None
    tid = m.group(1)
    verdict, commit = _last_audit_post_for_task(tid, EVENTS_PATH)
    if verdict not in ("GREEN", "YELLOW") or not commit:
        return None            # includes the unreadable-journal case ⇒ no audit claim to check (the
                               # caller's own fail-closed paths still govern; this view invents nothing)
    if _run_git_cap(["merge-base", "--is-ancestor", commit, "HEAD"], W).returncode != 0:
        return None

    # T-11059 — set once the changed-since-the-audit set is known; stays None on every fail-closed exit
    # above it, so `_pack` reports the count only where it was actually measured.
    _imports: "int | None" = None

    def _pack(as_audited, inherited, own, unclassified, closure=(), mechanical=()):
        out = {"task": tid, "audit_commit": str(commit)[:7], "base": str(merged_base)[:7],
               "as_audited": int(as_audited)}
        if _imports is not None:
            out["merge_imports"] = int(_imports)
        truncated = {}
        for key, vals in (("merge_inherited", inherited), ("own_post_audit", own),
                          ("closure_side_effect", closure), ("mechanical_resolve", mechanical),
                          ("unclassified", unclassified)):
            vals = sorted(vals)
            if len(vals) > _AUDITED_FOOTPRINT_LIST_CAP:
                truncated[key] = len(vals)          # the EXACT count, so the cap is never silent
                vals = vals[:_AUDITED_FOOTPRINT_LIST_CAP]
            out[key] = vals
        if truncated:
            out["truncated"] = truncated
        # T-11001 (X-0823) — a REPORT field over exactly the paths the caller refuses on. Computed from
        # the packed (possibly capped) lists so what is reported is what is SHOWN — a verdict for a path
        # the operator cannot see would be noise. Nothing branches on it; the offending set is unchanged.
        out["uncovered_provenance"] = _uncovered_path_provenance(
            out["own_post_audit"] + out["unclassified"], W, merged_base, _run_git_cap=_run_git_cap)
        # T-12365 — CITE THE HAND RESOLUTION, do not exempt it. This record is what explains the SHIFT
        # that forces a re-audit, and until now the loudest cause of that shift — a human resolving a
        # non-union conflict and committing it as a merge — was recorded NOWHERE, so the record named
        # the paths without ever being able to name WHY they moved. `worktree sync --resolved` now
        # writes a `merge_resolved_by_hand` row per resolution; this folds the rows whose merge commit
        # lies in `<audit_commit>..HEAD` and names them beside the buckets.
        # REPORT-ONLY, and that is the load-bearing half. Nothing branches on this key: every bucket,
        # every verdict and every refusal is byte-identical with or without it. A hand resolution is
        # AUTHORED CONTENT — `_offending_drift_is_merge_produced` says so in as many words, and it is
        # exactly what the rule exists to refuse — so making the shift ATTRIBUTABLE must not make it
        # EXCUSABLE. A future change that read this key to admit such a path would invert the rule.
        # FAIL-SAFE: absent whenever it could not be measured (no reader injected, an unreadable
        # journal, a git that would not answer). An absent key is never a claimed empty set.
        if _read_land_events is not None:
            try:
                rl = _run_git_cap(["rev-list", f"{commit}..HEAD"], W)
                if rl.returncode == 0:
                    since = {ln.strip() for ln in (rl.stdout or "").splitlines() if ln.strip()}
                    rows = []
                    for e in _read_land_events(EVENTS_PATH):
                        if e.get("type") != "merge_resolved_by_hand":
                            continue
                        d = e.get("data") or {}
                        if d.get("branch") != branch or (d.get("merge_commit") or "") not in since:
                            continue
                        rows.append({"merge_commit": str(d.get("merge_commit") or "")[:7],
                                     "resolved": sorted(d.get("resolved") or []),
                                     "resolved_source": d.get("resolved_source")})
                    out["hand_resolved"] = rows
            except Exception:                  # noqa: BLE001 — a report never fails the gate it describes
                pass
        return out

    footprint = list(observable_footprint)
    try:
        if not footprint:
            return _pack(0, [], [], [])
        d = _run_git_cap(["diff", "--name-only", commit, "HEAD"], W)
        if d.returncode != 0:
            return _pack(0, [], [], footprint)          # cannot tell what changed → fail-closed
        since = {ln.strip() for ln in d.stdout.splitlines() if ln.strip()}
        # T-11059 — the pure merge imports: changed since the audit, yet absent from the RAW merged-tree
        # delta, which is precisely the set of paths whose HEAD content equals the merged main tip. Read
        # off the caller's own list (never re-derived here) so this can never disagree with the footprint.
        if merged_delta is not None:
            _md = set(merged_delta)
            _imports = len([p for p in since if p not in _md])
        changed = [p for p in footprint if p in since]
        as_audited = len(footprint) - len(changed)
        if not changed:
            return _pack(as_audited, [], [], [])
        # The clean 3-way re-merge of the AUDITED tree with the main tip this attempt merged. On a
        # CONFLICT `--write-tree` still prints the tree on line 1 (with conflict-marked content for the
        # conflicted paths) — use it, so a conflicted path lands in `own_post_audit` (the correct
        # verdict for resolution content) WITHOUT dragging its cleanly-merged neighbours down with it.
        mt = _run_git_cap(["merge-tree", "--write-tree", commit, merged_base], W)
        tree = ((mt.stdout or "").strip().splitlines() or [""])[0].strip()
        if not re.fullmatch(r"[0-9a-f]{7,64}", tree or ""):
            return _pack(as_audited, [], [], changed)   # no tree at all → fail-closed
        bd = _run_git_cap(["diff", "--name-only", tree, "HEAD"], W)
        if bd.returncode != 0:
            return _pack(as_audited, [], [], changed)   # fail-closed
        beyond = {ln.strip() for ln in bd.stdout.splitlines() if ln.strip()}
        own = [p for p in changed if p in beyond]
        # T-10998 — of the paths this branch demonstrably put there, split out the ones PROVEN to be
        # exact deterministic governed closure side-effects. Only `own_post_audit` is partitioned:
        # `merge_inherited` already never refuses (the settled T-10592 position, untouched here), and
        # `unclassified` is the reserved did-not-answer value, which must never be reclassified by a
        # helper that also could not answer. A helper failure yields an empty set → nothing moves.
        closure = _governed_closure_side_effects(own, W, commit, tid,
                                                 _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH)
        # T-11332 — the OTHER proven-exempt class, on the SAME standard and with the same
        # subset-never-a-verdict shape: content the merge classifier itself produces, re-derived here
        # and compared byte-for-byte. Partitioned out of `own_post_audit` ONLY, for the identical
        # reasons: `merge_inherited` already never refuses, and `unclassified` is the reserved
        # did-not-answer value, which must never be reclassified by a helper that also could not
        # answer. Closure is subtracted first so the two exempt buckets stay DISJOINT — a path can be
        # reported under exactly one head, never two.
        mechanical = {p for p in _mechanically_resolved_conflicts(
            own, W, commit, merged_base, _run_git_cap=_run_git_cap,
            _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
            _anchor_signature_of_text=_anchor_signature_of_text) if p not in closure}
        return _pack(as_audited,
                     [p for p in changed if p not in beyond],   # merge_inherited
                     [p for p in own if p not in closure and p not in mechanical],  # own_post_audit
                     [],
                     [p for p in own if p in closure],          # closure_side_effect
                     [p for p in own if p in mechanical])       # mechanical_resolve
    except Exception as exc:
        # Never a silent pass: an unexpected failure is reported as "did not answer", which the caller
        # routes to REFUSE exactly like an own-post-audit change.
        return _pack(0, [], [], [f"<classifier-error: {type(exc).__name__}>"])

def _land_audited_footprint_abort_detail(split: "dict | None") -> dict:
    """T-11391 — THE MACHINE RECORD of a currency refusal, as `_emit_land_abort`'s `abort_detail`.

    Factored out of the in-lock gate's `_die(...)` call so the PRE-QUEUE refusal writes the SAME
    record rather than a second one composed beside it. The gate already had the rule that ONE
    diagnosis reaches the operator whichever side answers (T-11218's message-verbatim reuse); this
    extends it to the row a later reader folds, which by then cannot re-derive anything from the
    repo. Value-for-value identical to what the gate composed inline — a pure projection of `split`,
    deciding nothing. `{}` for a split that does not exist, so a caller with no verdict records no
    claim."""
    if not split:
        return {}
    return {"audit": {"task": split.get("task"), "commit": split.get("audit_commit")},
            "own_post_audit": split.get("own_post_audit") or [],
            "unclassified": split.get("unclassified") or [],
            "closure_side_effect": split.get("closure_side_effect") or [],
            "mechanical_resolve": split.get("mechanical_resolve") or [],
            "uncovered_provenance": split.get("uncovered_provenance") or {},
            "merge_imports": split.get("merge_imports"),
            "merge_inherited": split.get("merge_inherited") or []}

def _land_audited_footprint_lines(split: "dict | None", *, _AUDITED_FOOTPRINT_LIST_CAP=None) -> "list[str]":
    """T-10896 — the operator-readable render of `_land_audited_footprint_split`, naming which class
    each path is in AND why. This is the surface X-0696's second half asks for: facing a land seam, the
    operator can tell what this branch did from what main handed it, mechanically, instead of making a
    fresh judgement call (and escalating it) every time.

    Returns `[]` when there is nothing to report — no split, or the audit covers the whole observable
    footprint. Suppressed-when-clean, so an ordinary non-concurrent land's output is byte-unchanged;
    nothing is dropped by that silence, because the durable row is emitted regardless."""
    if not split:
        return []
    inherited = split.get("merge_inherited") or []
    own = split.get("own_post_audit") or []
    unknown = split.get("unclassified") or []
    closure = split.get("closure_side_effect") or []
    mechanical = split.get("mechanical_resolve") or []
    provenance = split.get("uncovered_provenance") or {}
    if not (inherited or own or unknown or closure or mechanical):
        return []
    truncated = split.get("truncated") or {}
    lines = [f"land: audited-diff footprint — audit {split.get('task')}@{split.get('audit_commit')} "
             f"vs main {split.get('base')}: {split.get('as_audited')} observable file(s) ship EXACTLY "
             f"as audited."]

    def _block(paths, key, head, annotate=None):
        if not paths:
            return
        total = truncated.get(key, len(paths))
        lines.append(f"  {head} ({total}):")
        # T-11001 — the per-path MEASURED provenance rides on the path line itself, so the operator
        # reads the file and the answer to "is this mine or main's?" in one place instead of diffing
        # by hand (X-0823). Absent from a block that has no verdicts, so nothing else changes shape.
        lines.extend(f"    {p}" + (f"  [{annotate[p]}]" if annotate and p in annotate else "")
                     for p in paths)
        if total > len(paths):
            lines.append(f"    … and {total - len(paths)} more (listing capped at "
                         f"{_AUDITED_FOOTPRINT_LIST_CAP}; the count above is exact)")

    _block(inherited, "merge_inherited",
           "MERGE-INHERITED — already-landed main history that land's own update-from-main folded "
           "in. Each is covered by its OWN task's land+audit, so it is NOT this branch's work and "
           "NOT a blocker here")
    # T-11001 (audit-post finding, absorbed) — the own-post-audit head ASSERTS authorship ("THIS
    # BRANCH'S OWN content … NO audit covers it"). A path whose provenance could not be MEASURED is not
    # entitled to that assertion, and printing it under that head would be exactly the §2 defect in
    # `lessons/carving-an-exception-into-a-fail-closed-gate`: a qualification printed underneath a
    # conclusion that contradicts it. The fix is structural, not textual — the unmeasured paths get
    # their OWN complete head, so each line the operator reads states only what was actually
    # established. Bucket MEMBERSHIP is untouched: both listings are `own_post_audit` and both refuse,
    # which is why the truncation key stays the same for both.
    _measured = [p for p in own if provenance.get(p) != "unknown"]
    _unmeasured = [p for p in own if provenance.get(p) == "unknown"]
    # `_own_key` carries the truncation footnote to whichever listing is the WHOLE bucket. When both
    # listings are non-empty the bucket was split, so neither one's length is the bucket's count — the
    # footnote is then emitted once below, against the bucket, rather than twice with a count that
    # describes neither listing (a capped listing must never be silent, T-10896).
    _own_key = "own_post_audit" if not (_measured and _unmeasured) else None
    _block(_measured, _own_key,
           "THIS BRANCH'S OWN content since its audit-post — a post-audit edit or a conflict "
           "resolution. NO audit covers it", annotate=provenance)
    _block(_unmeasured, _own_key,
           "CHANGED SINCE THE AUDIT, PROVENANCE NOT MEASURABLE — HEAD's content goes beyond the clean "
           "re-merge, so no audit covers it, but git could not answer whether it matches the merged "
           "main tip. NOT claimed as this branch's authorship; refused fail-closed on the unaudited "
           "content alone")
    if _own_key is None and "own_post_audit" in truncated:
        lines.append(f"    … the two listings above are one bucket of {truncated['own_post_audit']} "
                     f"path(s); the listing was capped at {_AUDITED_FOOTPRINT_LIST_CAP} and that count "
                     f"is exact")
    # T-10998 — its OWN complete diagnosis, never a qualifier printed under a contradicting one
    # (`lessons/carving-an-exception-into-a-fail-closed-gate` §2): this class is authored by the branch,
    # so it must not read as merge-inherited, and it is not unaudited work, so it must not read as
    # own-post-audit. It says what it is and that it is not the blocker, in one place.
    _block(closure, "closure_side_effect",
           "GOVERNED CLOSURE SIDE-EFFECT — written by `task close` itself (the spec activation flip, or "
           "a `lessons/` closure note) or PRESCRIBED by it (the activated spec's `binding:` declaration, "
           "which closure tells you to `spec edit` + `work commit` PRE-land), proven by path + exact diff "
           "shape + the recorded `spec_activated` provenance. The lifecycle REQUIRES this write after "
           "audit-post, so it is NOT a stale-audit signal and NOT a blocker here")
    # T-11332 — again its OWN complete diagnosis, never a qualifier printed under a contradicting one
    # (`lessons/carving-an-exception-into-a-fail-closed-gate` §2). This class is authored by the branch
    # in the sense that the branch's merge wrote it, so it must not read as merge-inherited; and it is
    # not content a human chose, so it must not read as own-post-audit. It says what it is, how that
    # was PROVEN, and that it is not the blocker, in one place.
    _block(mechanical, "mechanical_resolve",
           "MECHANICAL AUTO-RESOLUTION — written by land's own update-from-main, not by a human: the "
           "resolution `_classify_land_merge_conflicts` produces from the two sides was RE-DERIVED "
           "here from the audited commit and the merged main tip, and HEAD's content matches it "
           "BYTE-FOR-BYTE. No label was trusted; the content was compared. An audit cannot review a "
           "string no human chose, so this is NOT a stale-audit signal and NOT a blocker here. A "
           "hand-made resolution, or one whose re-derivation differs by a single byte or cannot be "
           "computed at all, is NOT in this class and still refuses")
    _block(unknown, "unclassified",
           "UNCLASSIFIED — the clean re-merge could not be derived, so provenance is UNPROVEN and is "
           "treated as unaudited (fail-closed)", annotate=provenance)
    if provenance:
        # T-11001 (X-0823) — the vocabulary, plus the fact that makes the verdicts above non-vacuous.
        # Without this line "everything is branch-authored" reads as a tautology; with it, the operator
        # can see the import reading was CONSIDERED and ruled out, which is the question kupiclub had to
        # answer by hand. Stated as one coherent note, never as a qualifier contradicting a block head.
        lines.append(
            "  [provenance] measured per path against the merged main tip: `branch-authored` = this "
            "branch put the content there (its content DIFFERS from the tip, or it exists on only one "
            "side — added or deleted here); `identical-to-main` = a pure merge import; `unknown` = git "
            "could not answer, claimed as neither. If you expected a merge import to be named above, "
            "note that one CANNOT be: a file whose content equals the merged main tip is excluded from "
            "this footprint before any classification runs, so its absence here is the scoping working, "
            "not the scoping being skipped (X-0823).")
    # T-11059 — the QUANTITY beside T-11001's qualitative note. That note tells the operator a merge
    # import cannot be NAMED above; on its own that still leaves their own changed files unaccounted
    # for, so this states how many of them the exclusion actually took. Rendered only on a MEASURED,
    # non-zero count: a number that always appeared would say nothing, and an unmeasured one must not
    # be invented. Report-only — nothing branches on `merge_imports` — and it sits inside the same
    # suppressed-when-clean guard, so an ordinary land's output is byte-unchanged.
    _imports = split.get("merge_imports")
    if isinstance(_imports, int) and not isinstance(_imports, bool) and _imports > 0:
        lines.append(
            f"  [merge-imports] {_imports} path(s) changed since the audit are identical to the merged "
            f"main tip (pure merge imports, excluded from this footprint before classification) — "
            f"accounted for, and NOT part of the {len(own) + len(unknown)} path(s) refused above.")
    return lines
