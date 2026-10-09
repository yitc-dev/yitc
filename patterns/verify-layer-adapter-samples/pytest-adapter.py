#!/usr/bin/env python3
"""Sample verify-layer adapter for a pytest suite — report profile `pytest/1`.

A SAMPLE TO COPY. Put it in your own repository, edit SETTINGS below, name it as the `list` and
`run` command of the layer's `adapter:` block, and list it under `sources:` together with the
pytest configuration. The kernel never imports it; from the copy on it is yours.
The protocol it speaks is described in patterns/verify-layer-adapter-protocol.md.

The kernel starts this script at the repository root with the path of a manifest file in the
environment variable YITC_VERIFY_ADAPTER_MANIFEST; the manifest's `action` says what to do:

  list — the test files under TEST_PATHS, collected without running a test body
      (`pytest --collect-only -q`), plus the pytest version. Collection imports the test
      modules; a module that fails to import is reported as an error.
  run — exactly the requested files in ONE pytest run, with no rerun plugin, the JUnit report
      written where the manifest says. On a re-run the manifest carries `isolated`, and the
      files then run one at a time: pytest does that by itself unless the pytest-xdist plugin is
      loaded and the project's own options start workers, so in that case the run ends with
      `-n 0`, which overrides those options.

pytest has no command that names the tests a change reaches without running them, so this
sample answers no `related`: leave that key out of the `adapter:` block. The layer then keeps
its per-file report, per-file re-run and rescue.

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
import json
import os
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


def runner_version(command):
    """The version word of `pytest --version`, which prints `pytest 9.0.2`."""
    proc = subprocess.run([*command, "--version"], cwd=HOME, capture_output=True, text=True)
    words = ((proc.stdout or "") + (proc.stderr or "")).split(None)
    return words[1] if len(words) > 1 else ""


def knows(option):
    """Does this project's pytest know `option`? A plugin's options exist only while it is loaded."""
    proc = subprocess.run([*PYTEST, *BASE, "--help"], cwd=HOME, capture_output=True, text=True)
    return option in (proc.stdout or "")


def main(argv):
    with open(os.environ["YITC_VERIFY_ADAPTER_MANIFEST"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    action = manifest["action"]
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
        files = TEST_PATHS if units is None else [
            os.path.relpath(os.path.join(ROOT, u["file"]), HOME).replace(os.sep, "/") for u in units]
        cmd = [*PYTEST, *BASE, "-o", "junit_family=xunit2", "--junitxml=" + manifest["report"]]
        if manifest.get("isolated") and knows("--numprocesses"):
            # a re-run with pytest-xdist loaded: no workers, the files one at a time
            cmd += ["-n", "0"]
        return subprocess.run(cmd + list(files), cwd=HOME).returncode
    print("pytest-adapter: unknown action %r" % action, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
