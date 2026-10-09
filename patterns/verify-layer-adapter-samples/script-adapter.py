#!/usr/bin/env python3
"""Sample verify-layer adapter for a script-style suite — report profile `script/1`.

A script-style suite has no test runner: every test file is a program of its own, and the file
passed when it exits 0. This sample runs each file as its own process and writes the report a
runner would have written.

A SAMPLE TO COPY. Put it in your own repository, edit SETTINGS below, name it as the `list` and
`run` command of the layer's `adapter:` block, and list it under `sources:`. The kernel never
imports it; from the copy on it is yours.
The protocol it speaks is described in patterns/verify-layer-adapter-protocol.md.

The kernel starts this script at the repository root with the path of a manifest file in the
environment variable YITC_VERIFY_ADAPTER_MANIFEST; the manifest's `action` says what to do:

  list — the files matching TEST_GLOBS: a listing of names, nothing is run
  run — each requested file as one process, one after another, and a JUnit report with one
      suite for each file written where the manifest says: a file that exits nonzero is a
      failed unit and the end of what it printed is its failure text

A script-style suite has nothing that names the files a change reaches, so this sample answers
no `related`: leave that key out of the `adapter:` block. The layer then keeps its per-file
report, per-file re-run and rescue.

A unit's `file` is repository-relative and the report names each suite by that same path, so no
`report_id` is needed.
"""
import datetime
import glob
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

# SETTINGS — edit these for your project.
# TEST_GLOBS: the files the layer's `command:` runs, from the repository root.
# command_for: how ONE test file is run.
TEST_GLOBS = ["tests/test_*.py"]


def command_for(path):
    return [sys.executable, path]


def printable(text):
    """XML carries no control characters: keep tab, newline and everything printable."""
    return "".join(ch for ch in text if ch in "\t\n" or ch >= " ")


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
        root = ET.Element("testsuites")
        failed = 0
        for path in wanted:
            began = datetime.datetime.now(datetime.timezone.utc)
            proc = subprocess.run(command_for(path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors="replace")
            ended = datetime.datetime.now(datetime.timezone.utc)
            took = "%.3f" % ((ended - began) / datetime.timedelta(seconds=1))
            suite = ET.SubElement(root, "testsuite", name=path, timestamp=began.isoformat("T"), tests="1",
                                  time=took, failures="1" if proc.returncode else "0")
            case = ET.SubElement(suite, "testcase", classname=path, name=path, time=took)
            if proc.returncode:
                failed += 1
                sys.stdout.write("== %s exited %d ==\n%s\n" % (path, proc.returncode, proc.stdout))
                mark = ET.SubElement(case, "failure", message="exit %d" % proc.returncode)
                mark.text = printable(proc.stdout[-2000:])
        ET.ElementTree(root).write(manifest["report"], encoding="utf-8", xml_declaration=True)
        return 1 if failed else 0
    print("script-adapter: unknown action %r" % action, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
