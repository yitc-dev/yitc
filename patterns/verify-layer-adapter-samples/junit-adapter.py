#!/usr/bin/env python3
"""Sample verify-layer adapter for ANY runner that writes JUnit XML — report profile `junit/1`.

pytest, jest (jest-junit), vitest, playwright, mocha, phpunit, go test through gotestsum: each can
write a JUnit XML report. This sample runs the runner through a command template, then makes sure
every test case in the report names the test FILE it lives in, and leaves the report where the
manifest says. With `junit/1` the kernel reads one row per test case, so a red land is compared
with main test by test.

A SAMPLE TO COPY. Put it in your own repository, edit SETTINGS below, name it as the `list` and
`run` command of the layer's `adapter:` block, and list it under `sources:`. The kernel never
imports it; from the copy on it is yours.
The protocol it speaks is described in patterns/verify-layer-adapter-protocol.md.

The kernel starts this script at the repository root with the path of a manifest file in the
environment variable YITC_VERIFY_ADAPTER_MANIFEST; the manifest's `action` says what to do:

  list — the files matching TEST_GLOBS: a listing of names, nothing is run
  run — RUN_COMMAND with the requested files and the report path filled in, then each test case
      without a `file` attribute is given one by `resolve_file` (below); the runner's exit code
      is this script's exit code.

HOW `junit/1` NAMES A UNIT. A case's unit is its own `file` attribute, else its suite's `file`,
else the suite name. pytest (`-o junit_family=xunit1`) writes the case `file`; jest-junit and
vitest write the suite `file` or name the suite by its path; gotestsum writes neither — its
`classname` is the Go package — so for Go `resolve_file` finds the `*_test.go` file of that
package that declares `func <TestName>(`. A case it cannot resolve to exactly one file is left
alone: the report then names a unit nobody requested, the kernel drops the report, and the
layer's own `command:` decides. A guess never names a file.
"""
import glob
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

# SETTINGS — edit these for your project.
# TEST_GLOBS: the files the layer's `command:` runs, from the repository root.
# RUN_COMMAND: the runner invocation; "{report}" becomes the report path, "{files}" the files.
#   pytest (the default):  [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
#                           "-o", "junit_family=xunit1", "--junitxml={report}", "{files}"]
#   jest + jest-junit:     ["npx", "jest", "--ci", "--reporters=default", "--reporters=jest-junit",
#                           "{files}"]  with JEST_JUNIT_OUTPUT_FILE={report} and
#                           JEST_JUNIT_ADD_FILE_ATTRIBUTE=true in RUN_ENV
#   go via gotestsum:      ["gotestsum", "--junitfile", "{report}", "--", "./..."]
# GO_MODULE: the module path of go.mod, so a Go package name maps to its directory ("" = not Go).
TEST_GLOBS = ["tests/test_*.py"]
RUN_COMMAND = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "junit_family=xunit1",
               "--junitxml={report}", "{files}"]
RUN_ENV = {}
GO_MODULE = ""


def resolve_file(case, suite):
    """The repository-relative test file of one case that names none, or None when it is not
    exactly one file. Go: the package directory's `*_test.go` declaring `func <Name>(`."""
    if not GO_MODULE:
        return None
    package = case.get("classname") or suite.get("name") or ""
    if package != GO_MODULE and not package.startswith(GO_MODULE + "/"):
        return None
    folder = package[len(GO_MODULE):].lstrip("/") or "."
    name = (case.get("name") or "").split("/")[0]
    if not re.fullmatch(r"\w+", name):
        return None
    found = []
    for path in sorted(glob.glob(os.path.join(folder, "*_test.go"))):
        with open(path, encoding="utf-8", errors="replace") as handle:
            if re.search(r"^func\s+%s\s*\(" % re.escape(name), handle.read(), re.M):
                found.append(os.path.normpath(path).replace(os.sep, "/"))
    return found[0] if len(found) == 1 else None


def enrich(report):
    """Give every case the `file` it lives in, where the runner wrote none."""
    tree = ET.parse(report)
    for suite in tree.getroot().iter("testsuite"):
        for case in suite.findall("testcase"):
            if not case.get("file") and not suite.get("file"):
                path = resolve_file(case, suite)
                if path:
                    case.set("file", path)
    tree.write(report, encoding="utf-8", xml_declaration=True)


def main(argv):
    with open(os.environ["YITC_VERIFY_ADAPTER_MANIFEST"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    action = manifest["action"]
    files = sorted({path.replace(os.sep, "/") for pattern in TEST_GLOBS
                    for path in glob.glob(pattern, recursive=True)})
    if action == "list":
        doc = {"schema": 1, "units": [{"file": path} for path in files], "errors": [],
               "versions": {"python": "%d.%d.%d" % sys.version_info[:3]}}
        with open(manifest["output"], "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
        return 0
    if action == "run":
        units = manifest.get("units")
        wanted = files if units is None else [u["file"] for u in units]
        command = []
        for word in RUN_COMMAND:
            if word == "{files}":
                command += wanted
            else:
                command.append(word.replace("{report}", manifest["report"]))
        env = dict(os.environ, **{k: v.replace("{report}", manifest["report"]) for k, v in RUN_ENV.items()})
        code = subprocess.run(command, env=env).returncode
        if os.path.exists(manifest["report"]):
            enrich(manifest["report"])
        return code
    print("junit-adapter: unknown action %r" % action, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
