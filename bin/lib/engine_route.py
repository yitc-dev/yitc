"""T-13192 (SPEC-1003) — on-server engine serving: which kernel checkout serves a consumer call.

A consumer is served by an IMMUTABLE detached kernel checkout, `<kernel main>/.yitc/promoted-engines/
<sha>`, chosen by its registry-declared ROLE: `.yitc/canary-engine` for the one declared canary,
`.yitc/promoted-engine` for every other registered consumer. Nothing a land does moves such a checkout,
so the sha a served run stamps on its `cli_invoked` row names the code that actually ran.

This module is STDLIB-ONLY AT IMPORT, and it must stay that way: `route` runs from the entry shim
BEFORE `lib.cli` is imported, so a broken live CLI body cannot keep a consumer off its served copy,
and it runs on every invocation. The registry parser (`lib.state`), the journal reader (`lib.journal`)
and the host-home resolver (`lib.host_paths`) are imported inside the slow paths only.

It only CHOOSES a directory. Nothing it loads survives into the served run: `route` re-execs the whole
process into the chosen checkout, so every module the served run imports comes from there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROMOTED_DIR = (".yitc", "promoted-engines")
POINTERS = {"canary": ".yitc/canary-engine", "promoted": ".yitc/promoted-engine"}
REFUSAL_PREFIX = "yitc-v2: engine-route:"
_HEX = frozenset("0123456789abcdef")


class RegistryError(Exception):
    """The host registry exists but cannot be read or parsed — the routing state is undecidable."""


class RouteRefused(Exception):
    """A consumer call whose serving engine cannot be established. Never a fall-through to main."""


def _is_sha(s: str) -> bool:
    return len(s) == 40 and set(s) <= _HEX


def code_root() -> Path:
    """The checkout the RUNNING code was loaded from: `<root>/bin/lib/engine_route.py` -> `<root>`."""
    return Path(__file__).resolve().parent.parent.parent


def _gitdir(root: Path) -> "Path | None":
    """`root/.git` as a directory, or the directory a `gitdir:` file names. Pure filesystem."""
    g = root / ".git"
    try:
        if g.is_dir():
            return g
        if g.is_file():
            text = g.read_text(encoding="utf-8").strip()
            if text.startswith("gitdir:"):
                p = Path(text[len("gitdir:"):].strip())
                return p if p.is_absolute() else (root / p)
    except OSError:
        return None
    return None


def _common_dir(path) -> "Path | None":
    """The git COMMON dir of the repository `path` sits in (a linked worktree resolves to its main
    repository's), found by walking up to the first `.git`. None when `path` is in no repository.
    Pure filesystem — no git subprocess on the per-invocation path."""
    try:
        p = Path(path).resolve()
    except (OSError, RuntimeError):
        return None
    for d in (p, *p.parents):
        if not (d / ".git").exists():
            continue
        gd = _gitdir(d)
        if gd is None:
            return None
        try:
            cf = gd / "commondir"
            if cf.is_file():
                c = Path(cf.read_text(encoding="utf-8").strip())
                return (c if c.is_absolute() else gd / c).resolve()
            return gd.resolve()
        except OSError:
            return None
    return None


def served_sha(root) -> "str | None":
    """The sha a PER-SHA checkout serves, else None (SPEC-1003 rule 3).

    Non-None ONLY when `root` is `<X>/.yitc/promoted-engines/<40-hex>` AND its HEAD is that same
    detached sha — the one shape in which one commit provably served the whole run. The live kernel
    checkout, a task worktree, a checkout whose HEAD moved: all None, so a row never names a sha the
    checkout does not provably serve."""
    root = Path(root)
    if (root.parent.name, root.parent.parent.name) != (PROMOTED_DIR[1], PROMOTED_DIR[0]):
        return None
    if not _is_sha(root.name):
        return None
    gd = _gitdir(root)
    if gd is None:
        return None
    try:
        head = (gd / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return root.name if head == root.name else None


def is_clean(root) -> bool:
    """Is the checkout exactly its commit? `git status --porcelain --untracked-files=all` exits 0 with
    no output: no modified tracked file AND no added non-ignored file (an injected `bin/lib/x.py` is
    caught). Any git failure reads as NOT clean (fail-closed)."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and not r.stdout.strip()


_RUNNING: list = []


def running_served_sha() -> "str | None":
    """The `engine_sha` stamp source (SPEC-1003 rule 3): `served_sha` of the code that is RUNNING, and
    only while that checkout is clean (`is_clean`) — a modified or extended copy never earns a stamp. Read from
    this module's own location, never from ENGINE_ROOT, so no later rebind can make the stamp name a
    checkout other than the one that served. Memoized once per process (one `git status`, and only in a
    process that runs from a per-sha checkout)."""
    if not _RUNNING:
        root = code_root()
        sha = served_sha(root)
        _RUNNING.append(sha if sha and is_clean(root) else None)
    return _RUNNING[0]


def live_engine_root(root) -> Path:
    """The live kernel checkout for `root`: `<X>` when `root` is a served per-sha checkout of `<X>`,
    else `root` unchanged (SPEC-1003 rule 4 — where kernel RUNTIME STATE resolves)."""
    root = Path(root)
    return root.parent.parent.parent if served_sha(root) else root


def registry_path(live: Path, environ=None) -> Path:
    """The host registry — `YITC_REGISTRY`, else `<host home>/registry.yaml` (the cli.py rule)."""
    env = os.environ if environ is None else environ
    if env.get("YITC_REGISTRY"):
        return Path(env["YITC_REGISTRY"]).resolve()
    from lib import host_paths
    return host_paths.host_home(engine_root=live) / "registry.yaml"


def _registry_text(path: Path) -> "str | None":
    """The registry's text; None when there is no registry file (it declares nothing)."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise RegistryError(f"the host registry {path} cannot be read ({e.__class__.__name__}: {e})")


def registry_entries(path, text: "str | None" = None) -> list:
    """Every registry project as {name, methodology, path, canary}; [] when there is no registry.

    Parsed with the ONE parser (`lib.state.load_path`, CHARTER §P5). A relative `path` resolves against
    the registry file's directory, as `nightly._v2_projects` does. Unreadable / unparseable ->
    RegistryError: an undecidable state is never read as "nothing declared"."""
    path = Path(path)
    if text is None:
        text = _registry_text(path)
    if text is None:
        return []
    from lib import state
    errors: list = []
    data = state.load_path(path, errors=errors)
    if errors or not isinstance(data, dict):
        raise RegistryError(f"the host registry {path} does not parse as a YAML mapping")
    projects = data.get("projects") or {}
    if not isinstance(projects, dict):
        raise RegistryError(f"the host registry {path} has a non-mapping `projects:`")
    reg_dir = path.resolve().parent
    out = []
    for name, meta in projects.items():
        if not isinstance(meta, dict):
            continue
        raw = meta.get("path")
        p = None
        if raw:
            p = Path(str(raw))
            p = p if p.is_absolute() else reg_dir / p
        out.append({"name": str(name), "methodology": meta.get("methodology"), "path": p,
                    "canary": meta.get("engine_canary") is True})
    return out


def declared_canaries(entries: list) -> list:
    return [e for e in entries if e["canary"]]


def _install_act(live: Path, role: str) -> str:
    """The act that installs a missing `role` pointer, as admitted in the state that is missing it."""
    if not any(os.path.lexists(live / p) for p in POINTERS.values()):
        return (f"initialize both pointers at the kernel's main HEAD: `{live}/bin/yitc-v2 work tag --tag <name> "
                f"--sha <main HEAD> --serve canary` (admitted in exactly this state)")
    if role == "promoted":
        return (f"promote a sha the canary has already run: `{live}/bin/yitc-v2 work tag --tag <name> "
                f"--sha <sha> --serve promoted`")
    return f"serve the canary: `{live}/bin/yitc-v2 work tag --tag <name> --sha <sha> --serve canary`"


def _c_target(args: list) -> "str | None":
    """The global `-C` / `--directory` value, from the LEADING options only (argparse takes the
    global flag before the verb). Accepts `-C X`, `-CX`, `-C=X`, `--directory X`, `--directory=X`."""
    for i, tok in enumerate(args):
        if not tok.startswith("-") or tok == "-" or tok == "--":
            return None
        if tok.startswith("--"):
            name, eq, val = tok[2:].partition("=")
            if name and "directory".startswith(name):   # argparse admits any unique prefix
                return val if eq else (args[i + 1] if i + 1 < len(args) else None)
            continue
        if tok == "-C":
            return args[i + 1] if i + 1 < len(args) else None
        if tok.startswith("-C"):
            v = tok[2:]
            return v[1:] if v.startswith("=") else v
    return None


def _pointer_target(live: Path, role: str) -> Path:
    """The per-sha checkout a role pointer names — resolved, validated; RouteRefused otherwise."""
    ptr = live / POINTERS[role]
    if not os.path.lexists(ptr):
        raise RouteRefused(f"an engine canary is declared but the `{role}` pointer {ptr} is not installed "
                           f"— {_install_act(live, role)}")
    real = Path(os.path.realpath(ptr))
    home = Path(os.path.realpath(live.joinpath(*PROMOTED_DIR)))
    if real.parent != home or served_sha(real) is None or not (real / "bin" / "yitc-v2").is_file():
        raise RouteRefused(f"the `{role}` pointer {ptr} does not name a per-sha checkout under {home} "
                           f"(-> {real}) — re-point it with `{live}/bin/yitc-v2 work tag --tag <name> "
                           f"--sha <sha> --serve {role}`")
    return real


def resolve_serving_root(argv: list, *, environ=None, cwd=None) -> "Path | None":
    """The checkout that SHOULD serve this invocation, or None when the invoked engine serves it.

    SPEC-1003 rule 2. The routing STATE is read from the REGISTRY — no pointer-existence shortcut
    precedes that read. Raises RouteRefused for every state in which an enabled canary's consumer
    cannot be served by its pointer."""
    env = os.environ if environ is None else environ
    target = _c_target(list(argv[1:]))
    if not target or not os.path.isabs(target):
        return None                                   # no -C, or a relative one the CLI refuses
    running = code_root()
    engine_common = _common_dir(running)
    if engine_common is None:
        return None
    target_common = _common_dir(target)
    if target_common is None or target_common == engine_common:
        return None                                   # the kernel (or one of its worktrees)
    if cwd is None:
        try:
            cwd = Path.cwd()
        except OSError:
            cwd = None
    if cwd is not None and _common_dir(cwd) == engine_common:
        return None                                   # a kernel session reading a consumer
    live = live_engine_root(running)
    reg = registry_path(live, env)
    try:
        text = _registry_text(reg)
        if text is None or "engine_canary" not in text:
            return live                               # INERT: nothing declared
        entries = registry_entries(reg, text)
    except RegistryError as e:
        raise RouteRefused(f"{e} — the routing state is undecidable; restore the registry")
    me = [e for e in entries if e["methodology"] == "yitc_v2" and e["path"] is not None
          and _common_dir(e["path"]) == target_common]
    if not me:
        return None                                   # not a registered consumer
    canaries = declared_canaries(entries)
    if not canaries:
        return live                                   # INERT
    if len(canaries) > 1:
        raise RouteRefused(f"{len(canaries)} registry entries declare `engine_canary: true` "
                           f"({', '.join(e['name'] for e in canaries)}) — exactly one may; remove the others")
    if canaries[0]["methodology"] != "yitc_v2":
        raise RouteRefused(f"`engine_canary: true` is declared on {canaries[0]['name']!r}, which is not a "
                           f"yitc_v2 consumer — declare it on a registered consumer")
    return _pointer_target(live, "canary" if me[0]["canary"] else "promoted")


def route(name: str) -> None:
    """The entry-shim hook (SPEC-1003 rule 2): re-exec this process into the checkout that should
    serve it. IDEMPOTENT — a process already running from that checkout proceeds; a per-sha path
    invoked directly is re-routed to the current pointer. Refusal: one stderr line, exit 3, and
    `lib.cli` is never imported."""
    if name != "__main__":
        return
    try:
        want = resolve_serving_root(sys.argv)
        if want is None:
            return
        want = Path(os.path.realpath(want))
        if want == code_root():
            if served_sha(want) and running_served_sha() is None:
                raise RouteRefused(f"the served checkout {want} is modified (a changed or added file) — "
                                   f"it is no longer the commit it names; remove it ({removal_recipe(want)}) "
                                   f"and re-run the serve act that installed it")
            return
        entry = want / "bin" / "yitc-v2"
        try:
            os.execv(sys.executable, [sys.executable, str(entry), *sys.argv[1:]])
        except OSError as e:
            raise RouteRefused(f"cannot exec the serving engine {entry} ({e})")
    except RouteRefused as e:
        print(f"{REFUSAL_PREFIX} {e}", file=sys.stderr)
        raise SystemExit(3)


# ── the serve acts' helpers (`work tag --serve`, SPEC-1003 rules 5-7) ─────────────────────────────

def canary_served(journal_path, sha: str) -> bool:
    """Does the canary's journal (segment-aware) hold a `cli_invoked` row stamped with exactly `sha`?
    A read-only fold of the consumer's journal — SPEC-0078 guards writes, and none happens here."""
    from lib import journal
    for row in journal.segment_rows(Path(journal_path), types={"cli_invoked"}):
        data = row.get("data") if isinstance(row, dict) else None
        if isinstance(data, dict) and data.get("engine_sha") == sha:
            return True
    return False


def serve_recorded(journal_path, tag: str, sha: str, role: str) -> bool:
    """Does the kernel journal (segment-aware) hold a `release_tagged` row for exactly this tag, sha and
    serve role — the recorded serve attempt (record-before-serve) that alone admits a resume past the
    initialization main-HEAD gate? A tag + prepared copy without it proves nothing."""
    from lib import journal
    for row in journal.segment_rows(Path(journal_path), types={"release_tagged"}):
        data = row.get("data") if isinstance(row, dict) else None
        if isinstance(data, dict) and (data.get("tag"), data.get("sha"), data.get("serve")) == (tag, sha, role):
            return True
    return False


def checkout_dir(live: Path, sha: str) -> Path:
    return Path(live).joinpath(*PROMOTED_DIR, sha)


def prepare_checkout(live: Path, sha: str, run_git) -> Path:
    """The per-sha checkout for `sha`, created as a DETACHED kernel worktree if absent. An existing
    directory is reused only when it already serves exactly `sha`. Returns the path; raises
    RouteRefused (reused as the act's refusal type) on any other state."""
    d = checkout_dir(live, sha)
    if d.exists():
        if served_sha(d) == sha and is_clean(d):
            return d
        raise RouteRefused(f"{d} exists but is not a clean detached checkout of {sha[:12]} — inspect it "
                           f"and remove it by hand ({removal_recipe(d)}) before serving {sha[:12]}")
    d.parent.mkdir(parents=True, exist_ok=True)
    r = run_git(["worktree", "add", "--detach", str(d), sha], live)
    if r.returncode != 0 or served_sha(d) != sha:
        raise RouteRefused(f"`git worktree add --detach {d} {sha[:12]}` failed — "
                           f"{(r.stderr or r.stdout or '').strip()}")
    make_read_only(d)
    return d


def make_read_only(root: Path) -> None:
    """Seal a served copy (SPEC-1003 rule 1): pre-compile its bytecode, so a served run never needs to
    write, then drop the write bits on EVERY file and EVERY directory of the tree. No write path —
    replacing a module through its parent directory, adding an importable file, rewriting a `.pyc` —
    remains without first deliberately undoing the mode bits. The worktree's git admin dir lives in the
    main repository's `.git/worktrees/` and stays writable. `is_clean` VERIFIES the seal at serve time."""
    import subprocess
    subprocess.run([sys.executable, "-m", "compileall", "-q", str(Path(root) / "bin")],
                   capture_output=True, text=True)
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in [*filenames, *dirnames]:
            p = os.path.join(dirpath, name)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode & ~0o222)
    os.chmod(root, os.stat(root).st_mode & ~0o222)


def removal_recipe(d) -> str:
    """How to remove a sealed served copy by hand — nothing deletes one automatically (rule 7)."""
    return f"`chmod -R u+w {d} && git worktree remove --force {d}`"


def swap_pointer(live: Path, role: str, target: Path) -> None:
    """Atomically point `role` at `target`: a temporary symlink renamed over the pointer."""
    ptr = Path(live) / POINTERS[role]
    tmp = ptr.with_name(f".{ptr.name}.tmp-{os.getpid()}")
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(str(target), str(tmp))
    os.replace(str(tmp), str(ptr))


def pointed_sha(live: Path, role: str) -> "str | None":
    ptr = Path(live) / POINTERS[role]
    if not os.path.lexists(ptr):
        return None
    return served_sha(Path(os.path.realpath(ptr)))


def unreferenced_checkouts(live: Path) -> list:
    """Per-sha checkouts no pointer names — listed for a manual `git worktree remove` (rule 7)."""
    home = Path(live).joinpath(*PROMOTED_DIR)
    named = {pointed_sha(live, r) for r in POINTERS}
    try:
        return sorted(p for p in home.iterdir() if p.is_dir() and p.name not in named)
    except OSError:
        return []
