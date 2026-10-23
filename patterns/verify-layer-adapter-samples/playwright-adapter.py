#!/usr/bin/env python3
"""Sample verify-layer adapter for a Playwright suite — report profile `playwright/1`.

A SAMPLE TO COPY. Put it in your own repository, edit SETTINGS below, name it as the `list`,
`related` and `run` command of the layer's `adapter:` block, and list it under `sources:`
together with the Playwright config. The kernel never imports it; from the copy on it is yours.
The protocol it speaks is described in patterns/verify-layer-adapter-protocol.md.

The kernel starts this script at the repository root with the path of a manifest file in the
environment variable YITC_VERIFY_ADAPTER_MANIFEST; the manifest's `action` says what to do:

  list — every pair of a project and a spec file the config runs, without running a test
      (`playwright test --list --reporter=json`), plus the Playwright version
  related — the pairs the change reaches, again without running one
      (`playwright test --only-changed=<base> --list`: Playwright compares the working tree
      with `<base>`, untracked files included, by itself)
  run — exactly the requested pairs in ONE Playwright run, Playwright's own retries off
      (`--retries=0`), the JUnit report and the JSON report written where the manifest says. When
      every requested pair carries `cases` (a re-run), `--grep` selects those tests by their exact
      titles — but only when, over Playwright's own listing, that selection hits the named tests
      and no other; otherwise the files run whole, which the protocol allows.

A unit is a spec file inside a Playwright project: `file` is repository-relative and `project`
is the project's name. Playwright's JUnit report names a suite by the spec's path relative to
the config's root directory, so every unit carries that name as `report_id`.

One limit to know: a run is asked for by project names and file names, so it executes every
requested file in every requested project that holds it. When the requested pairs are not all
of those combinations, the report names a pair the kernel did not ask for; the kernel then drops
the report and runs the layer's full `command:` instead.

"""
import json
import os
import re
import subprocess
import sys

# SETTINGS — edit these two for your project.
# RUNNER_DIR: the directory of the Playwright config, from the repository root ("" = the root).
# PLAYWRIGHT: how this project starts Playwright inside RUNNER_DIR.
RUNNER_DIR = "e2e"
PLAYWRIGHT = ["npx", "--no-install", "playwright"]

ROOT = os.path.abspath(os.curdir)
HOME = os.path.normpath(os.path.join(ROOT, RUNNER_DIR))


def listed(extra):
    """Ask Playwright for its pairs, with `extra` arguments. Returns (units, errors, version)."""
    proc = subprocess.run([*PLAYWRIGHT, "test", "--list", "--reporter=json", *extra], cwd=HOME,
                          capture_output=True, text=True)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return [], ["playwright --list exited %d and printed no JSON: %s"
                    % (proc.returncode, (proc.stderr or proc.stdout)[-400:])], None
    errors = [str(e.get("message") or e) for e in doc.get("errors") or []]
    if proc.returncode != 0 and not errors:
        errors = ["playwright --list exited %d" % proc.returncode]
    config = doc.get("config") or {}
    root = config.get("rootDir") or HOME
    pairs = []
    queue = list(doc.get("suites") or [])
    while queue:
        suite = queue.pop(0)
        queue.extend(suite.get("suites") or [])
        for spec in suite.get("specs") or []:
            for test in spec.get("tests") or []:
                pair = (test.get("projectName") or "", spec["file"])
                if pair not in pairs:
                    pairs.append(pair)
    units = [{"file": os.path.relpath(os.path.join(root, name), ROOT).replace(os.sep, "/"),
              "project": project, "report_id": name} for project, name in sorted(pairs)]
    return units, errors, config.get("version")


def listed_tests(projects, files):
    """Every test `playwright test --list` finds in `files` for `projects`, as (project, spec name,
    titles, tags). Returns None when the listing cannot be read."""
    proc = subprocess.run([*PLAYWRIGHT, "test", "--list", "--reporter=json",
                           *["--project=" + p for p in projects], *files], cwd=HOME, capture_output=True, text=True)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return None
    tests = []
    queue = [(suite, None) for suite in doc.get("suites") or []]
    while queue:
        suite, titles = queue.pop(0)
        # a top-level suite is the spec file, named by the file; a nested one is a describe block
        inner = [] if titles is None else titles + [suite.get("title") or ""]
        queue.extend((child, inner) for child in suite.get("suites") or [])
        for spec in suite.get("specs") or []:
            for test in spec.get("tests") or []:
                tests.append((test.get("projectName") or "", spec.get("file"), inner + [spec.get("title") or ""],
                              ["@" + tag for tag in spec.get("tags") or []]))
    return tests


def named_cases(units, files):
    """A `--grep` pattern matching exactly the named cases, or None to run the files whole.
    Playwright matches `--grep`, case-insensitively, against the project, the spec's name, the
    titles and the tags joined with spaces, so the pattern ends with the spec's name, the titles
    and any tags. Joining with spaces can make two tests read alike (`sum › adds two` and a test
    titled `sum adds two`), so the pattern is used only when, over Playwright's own listing of
    these files, it matches the named tests and no other."""
    if not units or not all(u.get("cases") for u in units):
        return None
    pattern = "^.* (?:%s)(?: @\\S+)*$" % "|".join(sorted(
        {re.escape(u.get("report_id") or u["file"]) + " " + " ".join(re.escape(p) for p in case.split(" \u203a "))
         for u in units for case in u["cases"]}))
    tests = listed_tests(sorted({u["project"] for u in units if u.get("project")}), files)
    if tests is None:
        return None
    wanted = {(u.get("project") or "", u.get("report_id") or u["file"], case) for u in units for case in u["cases"]}
    grep = re.compile(pattern, re.IGNORECASE)
    hit = {(project, name, " \u203a ".join(titles)) for project, name, titles, tags in tests
           if grep.search(" ".join(["", project, name, *titles, *tags]))}
    return pattern if hit == wanted else None


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
        units, errors, version = listed([])
        return answer(manifest, units, errors, {"playwright": version} if version else None)
    if action == "related":
        units, errors, _version = listed(["--only-changed=" + manifest["base"], "--pass-with-no-tests"])
        return answer(manifest, [{"file": u["file"], "project": u["project"]} for u in units], errors, None)
    if action == "run":
        cmd = [*PLAYWRIGHT, "test", "--retries=0", "--reporter=junit,json"]
        if manifest.get("isolated"):
            # a re-run: the files one at a time
            cmd.append("--workers=1")
        units = manifest.get("units")
        if units is not None:
            for project in sorted({u["project"] for u in units if u.get("project")}):
                cmd.append("--project=" + project)
            # a file argument is a regular expression matched against the spec's full path
            files = sorted({re.escape(os.path.join(ROOT, u["file"])) + "$" for u in units})
            cmd += files
            pattern = named_cases(units, files)
            if pattern is not None:
                cmd.append("--grep=" + pattern)
        env = dict(os.environ, PLAYWRIGHT_JUNIT_OUTPUT_FILE=manifest["report"],
                   PLAYWRIGHT_JSON_OUTPUT_FILE=manifest["second_report"])
        return subprocess.run(cmd, cwd=HOME, env=env).returncode
    print("playwright-adapter: unknown action %r" % action, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
