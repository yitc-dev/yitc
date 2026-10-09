#!/usr/bin/env python3
"""Sample verify-layer adapter for a Vitest suite — report profile `vitest/1`.

A SAMPLE TO COPY. Put it in your own repository, edit SETTINGS below, name it as the `list`,
`related` and `run` command of the layer's `adapter:` block, and list it under `sources:`
together with the Vitest config. The kernel never imports it; from the copy on it is yours.
The protocol it speaks is described in patterns/verify-layer-adapter-protocol.md.

The kernel starts this script at the repository root with the path of a manifest file in the
environment variable YITC_VERIFY_ADAPTER_MANIFEST; the manifest's `action` says what to do:

  list — the test files the layer runs, without running a test body
      (`vitest list --filesOnly --json`), plus the Vitest version
  related — the test files the change reaches, again without running one
      (`vitest list --filesOnly --json --changed <base>`: Vitest diffs `<base>...HEAD` plus
      staged, unstaged and untracked files by itself)
  run — exactly the requested files in ONE Vitest run, Vitest's own retries off (`--retry=0`),
      the JUnit report and the JSON report written where the manifest says

A unit's `file` is repository-relative. Vitest's JUnit report names a suite by its path relative
to Vitest's root directory, so every unit carries that name as `report_id`. The root directory
is the directory of the Vitest config unless the config sets `root` itself; RUNNER_DIR has to
name that root, or the names in the report will not match and the kernel drops the report.

One limit to know: `vitest run` reads a file argument as a filter that matches by substring, so
asking for `a.test.js` beside an existing `a.test.jsx` runs both. The kernel then finds a unit
it did not ask for, drops the report and runs the layer's full `command:` instead.
"""
import json
import os
import subprocess
import sys

# SETTINGS — edit these two for your project.
# RUNNER_DIR: Vitest's root directory, from the repository root ("" = the root) — the directory
# of the Vitest config, or the `root` that config sets.
# VITEST: how this project starts Vitest inside RUNNER_DIR.
RUNNER_DIR = "web"
VITEST = ["npx", "--no-install", "vitest"]

ROOT = os.path.abspath(os.curdir)
HOME = os.path.normpath(os.path.join(ROOT, RUNNER_DIR))


def to_repo(name):
    """A path relative to RUNNER_DIR -> the repository-relative path."""
    return os.path.relpath(os.path.join(HOME, name), ROOT).replace(os.sep, "/")


def to_runner(unit_file):
    """A repository-relative path -> the path relative to RUNNER_DIR."""
    return os.path.relpath(os.path.join(ROOT, unit_file), HOME).replace(os.sep, "/")


def listed(extra):
    """Ask Vitest for its test files, with `extra` arguments. Returns (units, errors)."""
    proc = subprocess.run([*VITEST, "list", "--filesOnly", "--json", *extra], cwd=HOME,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return [], ["vitest list exited %d: %s" % (proc.returncode, (proc.stderr or proc.stdout)[-400:])]
    try:
        rows = json.loads(proc.stdout)
    except ValueError as exc:
        return [], ["vitest list printed no JSON: %s" % exc]
    units = []
    for row in rows:
        name = os.path.relpath(row["file"], HOME).replace(os.sep, "/")
        unit = {"file": to_repo(name), "report_id": name}
        if row.get("projectName"):
            unit["project"] = row["projectName"]
        units.append(unit)
    return sorted(units, key=lambda u: (u.get("project", ""), u["file"])), []


def runner_version(command):
    """The version word of `vitest --version`, which prints `vitest/5.0.3 linux-x64 node-v22`."""
    proc = subprocess.run([*command, "--version"], cwd=HOME, capture_output=True, text=True)
    word = (proc.stdout or "").strip("\n").split(" ")[0]
    return word.split("/", 1)[1] if "/" in word else word


def answer(manifest, units, errors, versions):
    """Write the answer of `list` or `related` where the manifest says. Returns the exit code."""
    doc = {"schema": 1, "units": units, "errors": errors}
    if versions:
        doc["versions"] = versions
    with open(manifest["output"], "w", encoding="utf-8") as handle:
        json.dump(doc, handle)
    return 1 if errors else 0


def main(argv):
    with open(os.environ["YITC_VERIFY_ADAPTER_MANIFEST"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    action = manifest["action"]
    if action == "list":
        units, errors = listed([])
        version = runner_version(VITEST)
        return answer(manifest, units, errors, {"vitest": version} if version else None)
    if action == "related":
        units, errors = listed(["--changed", manifest["base"]])
        return answer(manifest, [{k: u[k] for k in ("file", "project") if k in u} for u in units], errors, None)
    if action == "run":
        cmd = [*VITEST, "run", "--retry=0",
               "--reporter=junit", "--outputFile.junit=" + manifest["report"],
               "--reporter=json", "--outputFile.json=" + manifest["second_report"]]
        if manifest.get("project"):
            cmd += ["--project", manifest["project"]]
        if manifest.get("isolated"):
            # a re-run: the files one at a time
            cmd.append("--no-file-parallelism")
        units = manifest.get("units")
        files = [to_runner(u["file"]) for u in units] if units is not None else []
        return subprocess.run(cmd + files, cwd=HOME).returncode
    print("vitest-adapter: unknown action %r" % action, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
