"""The ONE resolution site for THIS machine's host home (T-12024).

WHAT THIS IS. Several engine defaults are anchored at the home directory of the machine the engine is
installed on: the shared coordination store (`cross.CANONICAL_LOG_PATH`), the external-shared-library
root (`init._external_lib_root`), the project registry (`cli.REGISTRY_PATH`), and the two operands the
release-view stripper abstracts away (`graph._release_view_strip`). Each of those used to spell that
home as a LITERAL, so a copy of the engine taken to another machine inherited this machine's paths by
default — exactly what SPEC-0074 rule 4 already forbids for the handbook docs, unchecked in the code
(deviation `engine-code-host-path-unchecked-while-release-view-strips-docs`, 2026-09-01; the
off-server release plan's seam 3). They now all derive from `host_home()` here, and
`tests/test_engine_code_host_path_guard.py` refuses a new literal from reappearing.

WHY A LEAF MODULE. `cross.py` is imported BY `machine_settings.py`, and `graph.py` deliberately imports
only `lib.state` + stdlib. A helper both of those can read has to sit below them, importing nothing
from the package — the same import-graph reason `lib/vocab.py` exists (T-11320). This module imports
stdlib only and must stay that way.

WHY NOT `Path.home()` ALONE — the constraint that shapes the whole rule. SPEC-0084 rule 1 says the
WHOLE peer-set appends to and reads THE ONE coordination store. A plain `Path.home()` default cannot
satisfy that the moment the peer-set spans OS USERS: each user silently gets their OWN empty store,
inbound items are invisible, outbound requests never arrive, and the two stores allocate X-ids
independently and COLLIDE (X-0663, live once SPEC-0169 opened the collaborator lane). So the answer
here is NOT "whatever $HOME says" — it is "the home the ENGINE lives under", which is one value per
MACHINE rather than one per uid.

THE RULE, in one sentence: the host home is the home directory the engine checkout sits under.
  (1) When the engine is under the caller's own `$HOME`, that IS the answer — the ordinary case, and
      the one that makes a published copy on a foreign machine resolve under ITS owner's home with no
      configuration at all.
  (2) Otherwise the engine belongs to somebody else and the caller is a PEER: the answer is the home
      of the engine checkout's OWNER. This is the uid-independent branch, and it is the one that keeps
      X-0663 closed — every collaborator on this host resolves the one store the owner's home holds.
  (3) Only if neither can be determined does the caller's own home stand in.

NO ENV KNOB HERE, DELIBERATELY. The per-value overrides that already exist (`YITC_CROSS_LOG`,
`YITC_REGISTRY`) stay the environment layer and keep their precedence at their own read sites; a global
host-home override beside them would be a second door onto the same values, and SPEC-0193 rule 1 would
then have to classify it — where a filesystem path is not a performance-class value and would be GATE,
i.e. refused from the machine file anyway. One anchor, no new knob (CHARTER §Principle 1). (The name
such a knob WOULD take is deliberately not spelled anywhere in `bin/`: `machine_settings.scan_env_knobs`
is a TEXT scan, so writing it even in prose mints a phantom the inventory rule must then classify.)
"""
from __future__ import annotations

import os
import pwd
from pathlib import Path

# The per-user pinned release cache's directory-name prefix (T-14455; `init._TAG_RELEASE_CACHE` is this
# prefix + the euid). A tree directly under such a parent is a `git archive` COPY of a pinned release,
# not an install: it is per user and lives in the temp dir, so anchoring on it is anchoring on the
# caller (T-14689 — the X-0663 split store came back through it).
RELEASE_CACHE_PREFIX = "yitc-pinned-release-u"

# Test seam (T-14689 concurrency arm): called inside the sidecar critical section, between the
# validate and the publish. Production leaves it None.
_SIDECAR_WINDOW_HOOK = None


def _engine_root() -> Path:
    """This engine checkout's root: `<engine>/bin/lib/host_paths.py` -> `<engine>`.

    Derived from `__file__` rather than taken from `cli.ENGINE_ROOT` on purpose — this leaf must not
    import the package, and a COPIED engine tree (the verify sandbox, a published copy) has to resolve
    to the copy it is actually running from, which is exactly what `__file__` gives.
    """
    return Path(__file__).resolve().parent.parent.parent


def _is_cache_tree(root) -> bool:
    """Is `root` a tree directly inside a pinned release cache parent?"""
    try:
        return Path(os.path.realpath(str(root))).parent.name.startswith(RELEASE_CACHE_PREFIX)
    except (OSError, ValueError):
        return False


def _sidecar(tree: Path) -> Path:
    """The provenance sidecar of a cache tree: `<parent>/<name>.engine` — OUTSIDE the verified tree."""
    return tree.parent / f"{tree.name}.engine"


def _valid_stable(raw) -> "Path | None":
    """`raw` as a stable engine root when it names an existing engine install that is not a cache."""
    raw = (raw or "").strip()
    if not raw or not os.path.isabs(raw):
        return None
    cand = Path(raw)
    try:
        if cand.is_dir() and (cand / "bin" / "yitc-v2").is_file() and not _is_cache_tree(cand):
            return cand
    except OSError:
        return None
    return None


def _read_sidecar(tree: Path) -> "Path | None":
    try:
        return _valid_stable(_sidecar(tree).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def stable_engine_root(root=None) -> Path:
    """The STABLE engine behind `root` (T-14689): `root` itself unless it is a pinned release cache copy;
    for a copy, the engine its provenance sidecar names, else this module's own engine when that is not a
    copy, else `root` unchanged (nothing better is known). Never raises."""
    root = Path(root) if root is not None else _engine_root()
    if not _is_cache_tree(root):
        return root
    real = Path(os.path.realpath(str(root)))
    named = _read_sidecar(real)
    if named is not None:
        return named
    own = _engine_root()
    if not _is_cache_tree(own):
        return own
    return root


def record_stable_engine(tree, stable) -> bool:
    """Record that cache copy `tree` was made by the stable engine `stable` (T-14689).

    FIRST VALID WRITER WINS: a valid existing sidecar is never replaced, so a copy's provenance cannot
    switch between owners. Validate, invalid-sidecar removal and publish are ONE critical section under
    an exclusive flock on `<parent>/<name>.engine.lock` in the private cache parent, so a second writer
    re-validates after the first and keeps its value. Readers take no lock (`os.replace` is atomic).
    Returns True only when THIS call published. Any failure: no write, never raises."""
    import fcntl
    import tempfile
    try:
        tree = Path(os.path.realpath(str(tree)))
        if _valid_stable(str(stable)) is None:
            return False                       # a cache, or not an engine install: never recorded
        side = _sidecar(tree)
        lock = tree.parent / f"{tree.name}.engine.lock"
        with open(lock, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            if _read_sidecar(tree) is not None:
                return False                   # a valid winner stays
            if _SIDECAR_WINDOW_HOOK is not None:
                _SIDECAR_WINDOW_HOOK()
            try:
                side.unlink()
            except FileNotFoundError:
                pass
            fd, tmp = tempfile.mkstemp(dir=str(tree.parent), prefix=f".{tree.name}.engine.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    out.write(str(stable) + "\n")
                os.replace(tmp, str(side))
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            return True
    except Exception:  # noqa: BLE001 — provenance is best-effort; a reader falls back
        return False


def _caller_home(env) -> "Path | None":
    """The caller's own home, or None when the environment does not name a usable one."""
    raw = (env.get("HOME") or "").strip()
    if raw:
        try:
            return Path(raw).resolve()
        except OSError:      # an unresolvable $HOME is no home at all
            return None
    try:
        return Path(Path.home()).resolve()
    except (RuntimeError, KeyError, OSError):
        return None


def _owner_home(path: Path) -> "Path | None":
    """The home directory of `path`'s owning uid, or None when it cannot be read."""
    try:
        return Path(pwd.getpwuid(os.stat(str(path)).st_uid).pw_dir).resolve()
    except (OSError, KeyError, ValueError):
        return None


def host_home(engine_root=None, env=None) -> Path:
    """THIS machine's host home — the home directory the engine checkout sits under.

    `engine_root` / `env` are injection seams for the verifier; production passes neither. See the
    module docstring for the three branches and why branch (2) is uid-independent (X-0663).
    """
    env = os.environ if env is None else env
    engine = Path(engine_root) if engine_root is not None else _engine_root()
    engine = stable_engine_root(engine)      # a pinned copy anchors on the engine that made it (T-14689)
    try:
        engine = engine.resolve()
    except OSError:
        pass
    home = _caller_home(env)
    # (1) the engine lives under the caller's own home — the ordinary, and the off-host, case.
    if home is not None and (engine == home or home in engine.parents):
        return home
    # (2) a PEER on a host whose engine belongs to someone else — one answer per machine (X-0663).
    owner = _owner_home(engine)
    if owner is not None:
        return owner
    # (3) neither determinable: the caller's own home is the only thing left to stand on.
    return home if home is not None else Path(os.sep)
