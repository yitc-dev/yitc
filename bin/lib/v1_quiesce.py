"""cmd_v1_quiesce verb — the governed gate-2 v1-shutdown seam (SPEC-0130).

GOVERNING SPEC: SPEC-0130 ("Consumer v1-quiesce — the governed gate-2 v1-shutdown seam"). That spec is
`proposed`, activated by T-10009's `task close` (the work-first pattern, SPEC-0005 rule 4 / T-0199): the
implementing code here lands while the spec is proposed, the spec activates at this task's closure.

`bin/yitc-v2 -C <consumer> quiesce` is the SOLE governed path for the gate-2 v1-shutdown of a
consumer being migrated onto YITC v2. On run it, idempotently:

  1. Sets the consumer's registry entry `active: false` in the host registry (REGISTRY_PATH, default
     <host-home>/registry.yaml; YITC_REGISTRY-overridable) — a comment-preserving in-place LINE edit, so
     the registry's human comments/formatting survive. The consumer is the registry entry whose
     resolved `path` == the session's REPO_ROOT. This STOPS the host V1 AI-Team from operating on the
     project; it does NOT remove `methodology: yitc_v2`, so the v2 nightly still enumerates the consumer.
  2. Ensures `.no-v1-hooks` is present at REPO_ROOT (writes the born marker body if absent — reuses the
     `init` _BORN_NO_V1_HOOKS constant, one carrier). PRESENCE is the signal the host V1 hook walk-up
     detects; the body is documentary. A no-op when `init` already delivered it.
  3. Emits one `v1_quiesced` event {project, registry_active_set, no_v1_hooks_written,
     registry_already_false} — the governed evidence the hand-edit lacked. Emitted on EVERY run.

Runtime operational seam, NOT a repo-source cross-territory write (D-0019 governs a V2 *session's*
source/artifact writes into another repo, not a governed verb's runtime host/consumer mutation) — the
same operational class as cmd_init / cmd_deploy / cmd_host_apply.

Like cmd_deploy / cmd_live_probe / cmd_host_apply, this module back-imports NOTHING: every host
global/helper it reads is INJECTED as a keyword-only param by the host residue wrapper at call time, so
monkeypatches on the host names (REGISTRY_PATH via the arg, EVENTS_PATH via _append_event) stay honored.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from lib import state  # CHARTER §P5 one parser library — the registry reader (T-9740)

NO_V1_HOOKS_MARKER = ".no-v1-hooks"


def _resolve_entry_name(registry_path: Path, repo_root: Path) -> "str | None":
    """Return the registry entry NAME whose resolved `path` == repo_root, else None.

    Path resolution mirrors nightly._v2_projects (T-9796): a RELATIVE `path` resolves against the
    registry FILE's directory, NOT the process cwd, so the same consumer is found regardless of the
    invocation cwd. Read-only over the registry (the WRITE is the targeted line edit below)."""
    try:
        data = state.load_str(registry_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    projects = data.get("projects") or {}
    if not isinstance(projects, dict):
        return None
    reg_dir = registry_path.resolve().parent
    target = repo_root.resolve()
    for name, meta in projects.items():
        if not isinstance(meta, dict):
            continue
        raw = meta.get("path")
        if not raw:
            continue
        p = Path(str(raw))
        resolved = (p if p.is_absolute() else reg_dir / p).resolve()
        if resolved == target:
            return name
    return None


def _set_registry_active_false(registry_path: Path, name: str) -> "tuple[bool, bool]":
    """Comment-preserving in-place LINE edit: set `active: false` on the `name:` project entry.

    Returns (changed, already_false):
      - already_false: the entry already carried `active: false` (no write needed).
      - changed: the file was rewritten (an `active:` line was flipped, or one was inserted).
    The entry header is `  <name>:` (2-space indent); its fields are 4-space indented. The block runs
    until the next 2-space-or-shallower key (the next project / a top-level key) or EOF. An existing
    `active:` line (any value) is flipped to `false`; if none exists, `    active: false` is inserted
    right after the header line."""
    lines = registry_path.read_text(encoding="utf-8").splitlines(keepends=True)
    header_re = re.compile(r"^  " + re.escape(name) + r":\s*$")
    header_idx = next((i for i, ln in enumerate(lines) if header_re.match(ln)), None)
    if header_idx is None:
        return (False, False)
    # Block = header line's following lines up to the next 2-space-or-shallower non-blank key line.
    block_end = len(lines)
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        # a line indented <= 2 spaces that is not deeper block content = end of this entry
        if re.match(r"^ {0,2}\S", ln):
            block_end = j
            break
    active_re = re.compile(r"^(\s+)active:\s*.*$")
    for j in range(header_idx + 1, block_end):
        m = active_re.match(lines[j])
        if m:
            already_false = lines[j].split("active:", 1)[1].strip() == "false"
            if already_false:
                return (False, True)
            lines[j] = f"{m.group(1)}active: false\n"
            registry_path.write_text("".join(lines), encoding="utf-8")
            return (True, False)
    # No `active:` line in the entry — insert one at 4-space indent right after the header.
    lines.insert(header_idx + 1, "    active: false\n")
    registry_path.write_text("".join(lines), encoding="utf-8")
    return (True, False)


def cmd_v1_quiesce(args: argparse.Namespace, *, REPO_ROOT, ENGINE_ROOT, REGISTRY_PATH,
                   _BORN_NO_V1_HOOKS, _append_event, _main_worktree, write_text_atomic, _die) -> None:
    """`bin/yitc-v2 -C <consumer> quiesce` — the governed gate-2 v1-shutdown seam (SPEC-0130)."""
    repo_root = Path(_main_worktree(REPO_ROOT) or REPO_ROOT).resolve()
    if repo_root == Path(ENGINE_ROOT).resolve():
        _die("quiesce: refusing to quiesce the ENGINE itself — this is a CONSUMER verb "
             "(`-C <consumer> quiesce`); the kernel is not a v1-incumbent (SPEC-0130).")
    registry_path = Path(REGISTRY_PATH)
    if not registry_path.exists():
        _die(f"quiesce: registry not found at {registry_path} — cannot set `active: false` "
             f"(YITC_REGISTRY overrides the path; SPEC-0130).")
    name = _resolve_entry_name(registry_path, repo_root)
    if not name:
        _die(f"quiesce: no registry entry whose `path` resolves to {repo_root} in {registry_path} "
             f"— register the consumer (or fix its `path`) before quiescing (SPEC-0130).")

    # (1) registry active:false (comment-preserving line edit).
    registry_active_set, registry_already_false = _set_registry_active_false(registry_path, name)

    # (2) ensure .no-v1-hooks present (reuse the init born marker — one carrier).
    marker = repo_root / NO_V1_HOOKS_MARKER
    no_v1_hooks_written = not marker.exists()
    if no_v1_hooks_written:
        write_text_atomic(marker, _BORN_NO_V1_HOOKS)

    # (3) governed evidence — one v1_quiesced event on EVERY run (idempotent).
    _append_event("v1_quiesced", None, {
        "project": name,
        "registry_active_set": registry_active_set,
        "no_v1_hooks_written": no_v1_hooks_written,
        "registry_already_false": registry_already_false,
    })

    reg_note = ("already active:false" if registry_already_false
                else "set active:false" if registry_active_set else "unchanged")
    hooks_note = "wrote .no-v1-hooks" if no_v1_hooks_written else ".no-v1-hooks present"
    print(f"quiesce: {name} — registry {reg_note}; {hooks_note} | v1_quiesced emitted (SPEC-0130)")
