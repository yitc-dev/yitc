#!/usr/bin/env python3
"""Sample verify-layer adapter for a pytest suite — report profile `pytest/1`.

A SAMPLE TO COPY. Put it in your own repository, edit SETTINGS below, name it as the `list`,
`related` and `run` command of the layer's `adapter:` block, and list it under `sources:` together
with the pytest configuration. The kernel never imports it; from the copy on it is yours.
The protocol it speaks is described in patterns/verify-layer-adapter-protocol.md.

The kernel starts this script at the repository root with the path of a manifest file in the
environment variable YITC_VERIFY_ADAPTER_MANIFEST; the manifest's `action` says what to do:

  list — the test files under TEST_PATHS, collected without running a test body
      (`pytest --collect-only -q`), plus the pytest version. Collection imports the test
      modules; a module that fails to import is reported as an error.
  related — the test files the manifest's `changed` paths reach, WITHOUT starting pytest: a static
      import graph over the .py files under RUNNER_DIR (see «How `related` decides» below).
  run — exactly the requested files in ONE pytest run, with no rerun plugin, the JUnit report
      written where the manifest says. On a re-run the manifest carries `isolated`, and the
      files then run one at a time: pytest does that by itself unless the pytest-xdist plugin is
      loaded and the project's own options start workers, so in that case the run ends with
      `-n 0`, which overrides those options. A re-run unit that carries `cases` runs as those
      cases' node ids, `<file>::<case>`, so only the named tests of that file run.

How `related` decides. pytest has no command that names the tests a change reaches without
running them, so this sample reads the source instead. Every .py file under RUNNER_DIR is parsed
(nothing is imported or run); a file's module names are its dotted path from RUNNER_DIR, from
RUNNER_DIR/src, and from the first directory above it without an `__init__.py` (where pytest's
default import mode puts a test file's directory on the import path). A file reaches what it
imports — `import`, `from ... import` (relative ones included), a literal `import_module(...)` or
`__import__(...)` argument, and any string naming a module of the tree (a `mock.patch` target, a
`pytest_plugins` entry) — and importing `a.b.c` also runs `a/__init__.py` and `a/b/__init__.py`.
A test file also reaches what pytest loads for it without an import: every `conftest.py` from
RUNNER_DIR down to its directory (one above RUNNER_DIR is outside the graph: the file is then in
every answer), and every module of the tree a pytest configuration file
(pytest.ini, pyproject.toml, setup.cfg, tox.ini, from the repository root to RUNNER_DIR) names.
A changed module reaches every listed test file that reaches it, directly or through other files.
Anything this cannot place answers the WHOLE layer: a changed `conftest.py` (pytest loads it for
every test below it), a changed path that is not a .py file, was deleted, lies outside RUNNER_DIR
or in a skipped directory, a .py file under RUNNER_DIR that does not parse, and a changed module
no listed test reaches (it may still be read in a way the graph cannot see). A test file that
reaches an import the graph cannot read or place is in every answer: a computed or relative name
(`import_module(name)`, `import_module(".x", "pkg")`, `exec`, `runpy`, `spec_from_file_location`),
or an absolute import that is neither a module of the tree nor one the interpreter running this
script finds elsewhere (a `sys.path` edit makes such a name resolve to a file the graph cannot tie it to). Declare `modelled: [".py"]` on the layer: without
it the kernel counts every changed .py path as unknown and runs the full layer before asking.

A unit's `file` is repository-relative. pytest's JUnit report names a test by its module as a
dotted path from pytest's root directory. With RUNNER_DIR empty that is the unit's own path
with dots, which the kernel derives by itself; with pytest rooted in a sub-directory every unit
carries the dotted name as `report_id`.

pytest picks its root directory by itself, from the nearest configuration file at or above the
directory it starts in — a `pytest.ini` at the repository root makes the repository root the
root directory even when pytest is started in a sub-directory, and every test name changes with
it. This sample therefore always passes `--rootdir` naming RUNNER_DIR, so the names in the
listing and in the report are the ones RUNNER_DIR says. The configuration file pytest found is
still read.

One limit to know: the rerun plugin is switched off by name. A project whose own pytest options
carry that plugin's flags has to replace the switch in BASE with `--reruns 0`: with the plugin
off pytest refuses a flag it no longer knows, the listing fails, and the kernel runs the layer's
full `command:` instead.
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys

# SETTINGS — edit these three for your project.
# RUNNER_DIR: pytest's root directory, from the repository root ("" = the root).
# TEST_PATHS: what the layer's `command:` hands pytest, relative to RUNNER_DIR.
# PYTEST: how this project starts pytest inside RUNNER_DIR.
RUNNER_DIR = ""
TEST_PATHS = ["tests"]
PYTEST = [sys.executable, "-m", "pytest"]

ROOT = os.path.abspath(os.curdir)
HOME = os.path.normpath(os.path.join(ROOT, RUNNER_DIR))
BASE = ["--rootdir=" + HOME, "-p", "no:cacheprovider", "-p", "no:rerunfailures"]


def unit_for(name):
    """A test file relative to RUNNER_DIR -> its unit."""
    unit = {"file": os.path.relpath(os.path.join(HOME, name), ROOT).replace(os.sep, "/")}
    if RUNNER_DIR:
        unit["report_id"] = (name[:-3] if name.endswith(".py") else name).replace("/", ".")
    return unit


def listed(paths):
    """Ask pytest for the test files under `paths`. Returns (units, errors)."""
    proc = subprocess.run([*PYTEST, *BASE, "--collect-only", "-q", *paths], cwd=HOME,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return [], ["pytest --collect-only exited %d: %s" % (proc.returncode, (proc.stdout or proc.stderr)[-400:])]
    names = []
    # one node id on each line, `<file>::<test>` — or, when the project's own options add a
    # second `-q`, one file with its test count on each line, `<file>: <count>`
    for line in proc.stdout.split("\n"):
        head, _colon, count = line.rpartition(": ")
        if "::" in line:
            name = line.split("::", 1)[0]
        elif count and not count.strip("0123456789"):
            name = head
        else:
            name = ""
        if name and name not in names and os.path.isfile(os.path.join(HOME, name)):
            names.append(name)
    if not names:
        return [], ["pytest --collect-only listed no test file under %s: %s" % (HOME, proc.stdout[-400:])]
    return [unit_for(name) for name in sorted(names)], []


def node_ids(unit):
    """A unit -> what pytest is handed for it: the file, or one node id per named case. A case is
    named as the report named it, `<name>` or `<Class>::<name>`, a nested class with dots
    (`Outer.Inner::<name>`); in a node id every class is its own `::` step."""
    name = os.path.relpath(os.path.join(ROOT, unit["file"]), HOME).replace(os.sep, "/")
    if not unit.get("cases"):
        return [name]
    ids = []
    for case in unit["cases"]:
        head, bracket, params = case.partition("[")          # a parameter may hold `::` or dots
        classes, sep, test = head.rpartition("::")
        ids.append(name + "::" + (classes.replace(".", "::") + "::" if sep else "") + test + bracket + params)
    return ids


def runner_version(command):
    """The version word of `pytest --version`, which prints `pytest 9.0.2`."""
    proc = subprocess.run([*command, "--version"], cwd=HOME, capture_output=True, text=True)
    words = ((proc.stdout or "") + (proc.stderr or "")).split(None)
    return words[1] if len(words) > 1 else ""


def knows(option):
    """Does this project's pytest know `option`? A plugin's options exist only while it is loaded."""
    proc = subprocess.run([*PYTEST, *BASE, "--help"], cwd=HOME, capture_output=True, text=True)
    return option in (proc.stdout or "")


# `related` reads no file under these directories; a changed path inside one answers the whole layer.
SKIP_DIRS = {"__pycache__", "node_modules", "venv", "env", "build", "dist", "site-packages"}
# Calls whose target the graph cannot read unless it is a literal string.
DYNAMIC = {"import_module", "__import__", "exec", "eval", "run_module", "run_path", "spec_from_file_location"}
# The pytest configuration files whose text may name a plugin module pytest loads for every test.
CONFIG_FILES = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def module_names(path):
    """The dotted names a .py file under RUNNER_DIR imports as, and the package its relative
    imports start from."""
    names = []
    base = os.path.dirname(path)
    while os.path.isfile(os.path.join(base, "__init__.py")) and base != HOME:
        base = os.path.dirname(base)
    for top in (HOME, os.path.join(HOME, "src"), base):
        sub = os.path.relpath(path, top)
        if sub.startswith(".."):
            continue
        parts = sub[:-3].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(p.isidentifier() for p in parts) and ".".join(parts) not in names:
            names.append(".".join(parts))
    package = names[0] if names and path.endswith("__init__.py") else (names[0].rpartition(".")[0] if names else "")
    return names, package


def references(tree, package):
    """(the dotted names a parsed file reaches, the absolute names it imports, whether it holds an
    import it cannot read)."""
    refs, imports, dynamic = set(), set(), False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.update(a.name for a in node.names)
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                if node.level - 1 > len(parts):
                    dynamic = True                         # above the top package: cannot place it
                    continue
                base = ".".join(parts[:len(parts) - (node.level - 1)] + ([base] if base else []))
            elif base:
                imports.add(base)
            if base:
                refs.add(base)
            refs.update((base + "." if base else "") + a.name for a in node.names if a.name != "*")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in DYNAMIC:
                arg = node.args[0] if node.args else None
                relative = len(node.args) > 4 or any(k.arg in ("level", "package") for k in node.keywords) \
                    or (name == "import_module" and len(node.args) > 1)
                if name in ("import_module", "__import__", "run_module") and isinstance(arg, ast.Constant) \
                        and isinstance(arg.value, str) and not arg.value.startswith(".") and not relative:
                    refs.add(arg.value)
                    imports.add(arg.value)
                else:
                    dynamic = True                         # a computed or relative name: cannot place it
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isprintable():
            refs.add(node.value)                           # kept only when it names a module of the tree
    return refs, imports, dynamic


def found_elsewhere(top):
    """Does this interpreter find the top-level module `top` outside the tree (stdlib, installed)?"""
    if top in sys.builtin_module_names or top in getattr(sys, "stdlib_module_names", ()):
        return True
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError):
        return False


def import_graph():
    """{repo-relative .py path: (the paths it reaches, dynamic)} over RUNNER_DIR. A file is dynamic
    when it holds an import the graph cannot read or place — a computed or relative name, or an
    absolute one that is neither a module of the tree nor one this interpreter finds elsewhere (a
    `sys.path` edit, a plugin path). Raises OSError, SyntaxError or ValueError when a file cannot be
    read or parsed."""
    files = []
    for base, dirs, names in os.walk(HOME):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        files += [os.path.join(base, n) for n in names if n.endswith(".py")]
    modules, parsed = {}, {}
    for path in sorted(files):
        names, package = module_names(path)
        for name in names:
            modules.setdefault(name, set()).add(rel(path))
        with open(path, encoding="utf-8") as handle:
            parsed[rel(path)] = references(ast.parse(handle.read(), path), package)
    graph = {}
    for path, (refs, imports, dynamic) in parsed.items():
        reach = set()
        for ref in refs:
            parts = ref.split(".")
            for i in range(1, len(parts) + 1):             # `a.b.c` also runs a/__init__ and a/b/__init__
                reach |= modules.get(".".join(parts[:i]), set())
        reach.discard(path)
        unplaced = any(i.split(".")[0] not in modules and not found_elsewhere(i.split(".")[0]) for i in imports)
        graph[path] = (reach, dynamic or unplaced)
    return graph, modules


def implicit(unit, graph, modules):
    """(what pytest loads for a test file without the file importing it, whether some of it lies
    outside the graph): every `conftest.py` from the repository root down to the file's directory
    — one above RUNNER_DIR is outside the graph — and the modules the pytest configuration names
    (a `-p` plugin, a `pytest_plugins`-style entry) in the config files from the repository root
    to RUNNER_DIR."""
    out, outside = set(), False
    d = os.path.dirname(os.path.join(ROOT, unit))
    while True:
        c = os.path.join(d, "conftest.py")
        if rel(c) in graph:
            out.add(rel(c))
        elif os.path.isfile(c):
            outside = True
        if os.path.normpath(d) == os.path.normpath(ROOT) or not d.startswith(ROOT):
            break
        d = os.path.dirname(d)
    d = HOME
    while True:
        for name in CONFIG_FILES:
            try:
                with open(os.path.join(d, name), encoding="utf-8") as handle:
                    words = set(re.findall(r"[A-Za-z_][\w.]*", handle.read()))
            except OSError:
                continue
            for w in words:
                out |= modules.get(w, set())
        if os.path.normpath(d) == os.path.normpath(ROOT) or not d.startswith(ROOT):
            break
        d = os.path.dirname(d)
    return out, outside


def related(units, changed):
    """The listed units `changed` reaches — every listed unit wherever the graph cannot place a path."""
    whole = [{k: u[k] for k in ("file", "project") if k in u} for u in units]
    if not changed:
        return []
    try:
        graph, modules = import_graph()
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return whole
    for path in changed:
        if os.path.basename(path) == "conftest.py" or path not in graph:
            return whole                                   # non-.py, deleted, outside RUNNER_DIR, skipped
    closures = {}
    for u in units:
        loaded, dynamic = implicit(u["file"], graph, modules)
        seen = {u["file"]} | loaded
        todo = sorted(seen)
        while todo:
            reach, dyn = graph.get(todo.pop(), (set(), True))
            dynamic = dynamic or dyn
            todo += sorted(reach - seen)
            seen |= reach
        closures[u["file"]] = (seen, dynamic)
    if any(not any(p in closures[u["file"]][0] for u in units) for p in changed):
        return whole                                       # a module no listed test reaches
    return [w for u, w in zip(units, whole)
            if closures[u["file"]][1] or closures[u["file"]][0] & set(changed)]


def main(argv):
    with open(os.environ["YITC_VERIFY_ADAPTER_MANIFEST"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    action = manifest["action"]
    if action == "related":
        units = related(manifest.get("units") or [], list(manifest.get("changed") or []))
        with open(manifest["output"], "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "units": units, "errors": []}, handle)
        return 0
    if action == "list":
        units, errors = listed(TEST_PATHS)
        doc = {"schema": 1, "units": units, "errors": errors}
        version = runner_version(PYTEST)
        if version:
            doc["versions"] = {"pytest": version}
        with open(manifest["output"], "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
        return 1 if errors else 0
    if action == "run":
        units = manifest.get("units")
        files = TEST_PATHS if units is None else [node for u in units for node in node_ids(u)]
        cmd = [*PYTEST, *BASE, "-o", "junit_family=xunit2", "--junitxml=" + manifest["report"]]
        if manifest.get("isolated") and knows("--numprocesses"):
            # a re-run with pytest-xdist loaded: no workers, the files one at a time
            cmd += ["-n", "0"]
        return subprocess.run(cmd + list(files), cwd=HOME).returncode
    print("pytest-adapter: unknown action %r" % action, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
