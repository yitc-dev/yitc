"""cmd_live_probe verb — the per-change live_probe RUNNER at the deploy seam (SPEC-0094 §4).

GOVERNING SPEC: SPEC-0094 §4 ("Declarative read-only live_probe runner — ONE home, no parallel SoT").
This card (T-9395) is SPEC-0094's `activation_owner_task`: closing it flips SPEC-0094 proposed → active.

`bin/yitc-v2 [-C <path>] liveprobe --task T-XXXX` runs the task's PER-CHANGE `live_probe` assertion
(the SPEC-0028 task-YAML field) against PRODUCTION, using the carrier `live_base_url` (the project-level
default from `yitc-ops.yaml`, SPEC-0093). It is a DECLARATIVE READ-ONLY assertion — an HTTP **GET**
asserting status / body-contains — never an arbitrary script, never a write. A non-GET spec is REJECTED
(SPEC-0094 §4 — "an HTTP GET", read-only by construction).

SEAM (SPEC-0094 §4): the GET runs AT/AFTER `deploy` (the moment the change is live), NOT at `task close`
(§3 is a static declaration check). A PASSING per-change probe proves the LIVENESS of exactly what it
asserts (its declared status/body) — it is the executed per-change ADOPTION PROOF (the P3 "done = adopted"
evidence, recorded as a `live_probe_passed` journal event) ONLY to the extent that assertion exercises the
CRITICAL USER PATH (SPEC-0094 §4a). A `/healthz`-class PROCESS-liveness assertion proves only that the web
process answers, NEVER that the product works — X-0371: aiseller's /healthz probe returned 200 through 8h
of total auth death — so a passing probe is product-health evidence only when its critical-user-path
assertion carries a recorded SPEC-0156 failing demonstration (report-only debt otherwise; this runner adds
no gate). A FAILING probe (status mismatch / body mismatch / unreachable) emits NO event and exits
non-zero: the change is NOT confirmed live, so it stays, for adoption purposes, not-adopted (the
honest read — never a silent pass). The not-adopted commit-ancestry surface (§2 / T-9392) is cleared by
the `deploy_completed` advance; this runner is its per-change confirmation, not a second SoT for it.

The home split is FIXED (SPEC-0094 §4): the carrier (`yitc-ops.yaml`) holds the PROJECT-LEVEL default
`live_base_url`; the PER-CHANGE assertion lives on the TASK YAML. The carrier never stores a per-task
probe; the task YAML never re-declares the base url.

Like cmd_deploy (T-9390) + cmd_init (T-9380), this module back-imports NOTHING: every host global/helper
it reads is INJECTED as a keyword-only param by the host residue wrapper at call time, so monkeypatches
on the host names stay honored.
"""
from __future__ import annotations

import argparse
import urllib.error
import urllib.request

import yaml

from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)

CONSUMER_OPS_CONTRACT = "yitc-ops.yaml"   # SPEC-0093 rule 1 — one carrier file at the repo root
_GET_TIMEOUT_S = 15                       # bounded read; a hung prod endpoint must not block forever


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect handler that REFUSES to follow — `redirect_request` returning None makes urllib raise
    the 3xx as an HTTPError instead of resolving it to the final response (SPEC-0094 §4 no-follow dialect).
    This lets the runner assert the IMMEDIATE redirect status + its `Location` header."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ARG002
        return None


def _no_redirect_opener() -> "urllib.request.OpenerDirector":
    """Build a GET opener that does NOT follow redirects (SPEC-0094 §4). Read-only by construction —
    same GET method as the default path; it only suppresses the redirect-follow."""
    return urllib.request.build_opener(_NoRedirect)


#: T-12087 (SPEC-0093 `verify.floor.probes`) — the CANONICAL identity of a declared
#: `security.probes[]` entry. The land-time any-author floor accepts a historical
#: `security_live_probe_passed` row as vouching for a candidate's declared probe ONLY when the row was
#: written under the SAME definition; the digest is what makes that comparison a single equality
#: instead of a carrier-history walk. The canonical form is sorted-key JSON over the entry's DECLARED
#: fields (property/assertion/url plus any further scalar keys the entry carries), so a change to ANY
#: declared component — including `assertion`, which the event payload does not record — moves the
#: digest. SINGLE SOURCE: `bin/lib/worktree.py#_floor_probe_definition_digest` imports THIS function
#: rather than re-implementing the canonicalisation (two spellings of a digest are two digests).
_PROBE_DEFINITION_DIGEST_FIELDS = ("property", "assertion", "url")


def probe_definition_digest(entry) -> "str | None":
    """sha256 over the sorted-key JSON of a declared `security.probes[]` ENTRY, or None when the entry
    is not a usable mapping. Fail-closed by construction: an unusable entry yields NO digest, and the
    floor's reader treats a missing digest as "not watermarked" (its bounded legacy fallback), never as
    a match."""
    import hashlib
    import json
    if not isinstance(entry, dict):
        return None
    canon = {}
    for k in sorted(entry):
        v = entry.get(k)
        if isinstance(v, (str, int, float, bool)) or v is None:
            canon[str(k)] = v
    if not any(canon.get(f) for f in _PROBE_DEFINITION_DIGEST_FIELDS):
        return None
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _declared_probe_entry(repo_root, prop: str):
    """The carrier `security.probes[]` entry whose `property` is `prop`, or None. Never raises — a
    missing/unparseable carrier simply yields no entry, and the emit path below then records no
    `definition_digest` (additive-optional; the floor falls back)."""
    ops_path = repo_root / CONSUMER_OPS_CONTRACT
    if not ops_path.exists():
        return None
    try:
        ops = state.load_ops(ops_path)
    except Exception:  # noqa: BLE001 — a watermark is best-effort; never fail a real probe on it
        return None
    sec = ops.get("security") if isinstance(ops, dict) else None
    probes = sec.get("probes") if isinstance(sec, dict) else None
    if not isinstance(probes, list):
        return None
    for e in probes:
        if isinstance(e, dict) and str(e.get("property") or "").strip() == prop:
            return e
    return None


def _probe_entry_exercised(entry, *, target: str, expect_s, base_url) -> bool:
    """Did the run that is about to be recorded actually EXERCISE this carrier entry's definition?

    THE WATERMARK MUST PROVE EXECUTION, NOT MERELY SELECTION (audit-post r3 finding 7). The carrier
    entry is looked up by `property` ALONE, but what the runner just executed is the TASK CARD's
    `live_probe` — a different artifact that may name a different url or a different expectation. The
    row was nonetheless stamped with the carrier's digest, and the land-time floor treats that digest
    as an equality proof and then reads NEITHER the row's url NOR its expectation. So a probe run
    against `https://staging.example/health`, under a card whose `property` matches, minted a
    watermark vouching for the carrier's `https://prod.example/admin` — precisely the "a pass cannot
    vouch for a definition it never exercised" claim the digest exists to make.

    So the digest is emitted ONLY when the entry's own declared definition MATCHES what ran:
      * `url` — resolved through the SAME absolute/relative + `live_base_url` join the runner used, so
        a carrier declaring a relative path and a card declaring the absolute equivalent still agree;
      * `expect` — REQUIRED, and equal. An entry declaring NO `expect` gets NO watermark (r4
        consult finding). Comparing the url alone was not enough: what the runner executes is the
        CARD's probe, and the carrier entry's own `assertion` is FREE TEXT that is never executed,
        so at one url two different assertions are indistinguishable here. Without a declared
        `expect` there is nothing that binds the run to THIS entry's meaning, and minting the digest
        anyway hands the floor an equality proof that suppresses the legacy leg — the one leg whose
        history conjunct would have caught the assertion change. So an `assertion`-only entry is
        unprovable at this seam and is left to that leg, exactly as an entry with no url is.

    A MISMATCH OMITS THE WATERMARK RATHER THAN FAILING THE PROBE. The probe itself genuinely passed;
    what cannot be claimed is that it exercised the carrier's definition. Omission is the fail-closed
    direction: the floor then takes its LEGACY leg, which compares the row's url/expect against the
    candidate declaration and refuses on exactly this disagreement. An entry with NO url declared is
    likewise unprovable here and gets no watermark."""
    if not isinstance(entry, dict):
        return False
    declared_url = str(entry.get("url") or "").strip()
    if not declared_url:
        return False
    if declared_url.lower().startswith(("http://", "https://")):
        resolved = declared_url
    elif base_url:
        resolved = base_url.rstrip("/") + "/" + declared_url.lstrip("/")
    else:
        return False
    if resolved != target:
        return False
    # FAIL-CLOSED on an entry that declares no `expect` (r4 consult finding): the carrier's
    # `assertion` is free text the runner never executes, so at a matching url a DIFFERENT assertion
    # would otherwise mint this entry's digest. No declared expectation = nothing binds the run to
    # this entry's meaning = no watermark; the floor's legacy leg (url/expect equality + the carrier
    # history conjunct) judges those properties instead, and it refuses on exactly this change.
    if entry.get("expect") is None:
        return False
    if str(entry["expect"]) != str(expect_s):
        return False
    return True


def _carrier_base_url(repo_root, _die) -> "str | None":
    """Read the project-level `live_probe.live_base_url` from the ops-contract carrier (SPEC-0093/0094
    §4). Returns the url string, or None when the section is waived / absent (a probe with an ABSOLUTE
    url needs no base, so absence is not fatal here — the caller decides). Fail-closed on a malformed
    carrier (the SPEC-0093 sweep is the guard for carrier malformedness)."""
    ops_path = repo_root / CONSUMER_OPS_CONTRACT
    if not ops_path.exists():
        return None
    try:
        ops = state.load_ops(ops_path)
    except yaml.YAMLError as e:  # noqa: BLE001 — fail-closed on an unparseable carrier
        _die(f"live-probe: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); fix the carrier and retry.")
    if not isinstance(ops, dict):
        return None
    section = ops.get("live_probe")
    if not isinstance(section, dict):
        return None
    base = section.get("live_base_url")
    return base.strip() if isinstance(base, str) and base.strip() else None


def cmd_live_probe(args: argparse.Namespace, *, REPO_ROOT, ENGINE_ROOT, _append_event, _find_task_yaml,
                   _is_consumer_build=None,
                   _find_kernel_task_yaml, _git_resolve_sha, _main_worktree,
                   _live_probe_declaration_error, _redirect_statuses, _die) -> None:
    """Run a task's per-change live_probe GET against prod + emit live_probe_passed on a PASS (SPEC-0094
    §4). GET-only; a non-GET spec is rejected. A FAIL emits no event and exits non-zero.

    The live_probe SHAPE is validated by the SINGLE grammar SoT — `_live_probe_declaration_error` (the
    T-9391 close-gate validator, injected) — so the runner NEVER re-defines the assertion/waiver schema
    (audit-pre F2: no parallel grammar). The runner adds only its RUN-time concerns on top: the GET-only
    method guard + the waiver-has-nothing-to-run short-circuit + the base-url join."""
    tid = (getattr(args, "task", "") or "").strip()
    if not tid:
        _die("live-probe: --task T-XXXX is required (the per-change probe is a TASK-YAML field, SPEC-0094 §4).")

    # KEYING (SPEC-0094 §4): the probe is keyed on the task that GOVERNS the change — usually the deploying
    # project's own card, but a consumer deploy may be governed by a KERNEL card (X-0343: aiseller's prod
    # deploy ran under kernel T-10428 with no consumer-side task, so the probe refused and the evidence went
    # unrecorded). Resolve in TWO realms, own-first (the SPEC-0092 order): the session's OWN corpus, then —
    # in a `-C` consumer session ONLY — the kernel corpus (a read; SPEC-0078 guards consumer→engine WRITES).
    # T-11027: "a `-C` consumer session" is the CANONICAL `_is_consumer_build()` (common-dir), never a bare
    # REPO_ROOT != ENGINE_ROOT — that path test also admits the engine's OWN linked worktrees, which are the
    # engine (T-0952), so the second realm would open where own IS the kernel and the message would name a
    # "kernel corpus" that is the same repo. Not injected → the pre-existing path inequality (degraded, same
    # fallback `_is_consumer_build` itself takes in a non-git sandbox).
    _consumer = (_is_consumer_build() if _is_consumer_build is not None
                 else REPO_ROOT != ENGINE_ROOT)
    task_realm = None
    task_path = _find_task_yaml(tid)
    if task_path is None and _consumer:
        task_path = _find_kernel_task_yaml(tid)
        if task_path is not None:
            task_realm = "kernel"
    if task_path is None:
        searched = f"{REPO_ROOT}/tasks" + (f" and the kernel corpus {ENGINE_ROOT}/tasks"
                                           if _consumer else "")
        _die(f"live-probe: task YAML not found for {tid} (or ambiguous match) — searched {searched}.")
    try:
        task = state.load_str(task_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:  # noqa: BLE001
        _die(f"live-probe: {task_path.name} failed to parse ({e}).")
    if not isinstance(task, dict):
        _die(f"live-probe: {task_path.name} did not parse as a mapping.")

    lp = task.get("live_probe")
    if lp is None:
        _die(f"live-probe: {tid} declares NO `live_probe` — nothing to run (SPEC-0094 §4). Declare an "
             f"assertion {{url, expect_status}} on the task YAML, or it is not a probeable change.")
    # Validate against the ONE grammar SoT (the T-9391 close-gate validator) — never a second schema.
    grammar_err = _live_probe_declaration_error(lp)
    if grammar_err is not None:
        _die(f"live-probe: {tid} `live_probe` is malformed — {grammar_err} (SPEC-0094 §3/§4 grammar, "
             f"validated by the single close-gate SoT).")

    # T-11674 — `--report` IS ATTESTED-ONLY, and that is enforced HERE, before any form branch. Put
    # inside the attested branch it would only ever be checked when the card was already attested, so
    # `--report` on a `url` assertion fell through to the GET runner: a flag documented as "no request
    # is issued" would have issued one, and a reading the operator meant to REPORT would have been
    # silently replaced by a kernel GET. Refuse it up front instead, for every non-attested form.
    if (getattr(args, "report", None) or "").strip() and "attested" not in lp:
        _form = ("an assertion (`url`)" if "url" in lp else
                 "a waiver (`none`)" if "none" in lp else
                 "an escalation (`unprobeable`)" if "unprobeable" in lp else "no recognized form")
        _die(f"live-probe: --report is valid ONLY for the ATTESTED form (SPEC-0094 §4b), and {tid} "
             f"declares {_form}. --report records the reading of a proof the PROJECT ran; it can never "
             f"hand-declare a kernel-run GET passed, and it is not a way to skip running one. Re-run "
             f"without --report to probe the declaration as written.")

    # T-11674 (X-1130) — THE ATTESTED FORM'S GRADING SEAM (SPEC-0094 §4b). The kernel GRADES a proof the
    # PROJECT already runs; it issues NO outbound request of its own on this path. So this branch runs
    # BEFORE every opener/GET concern below and RETURNS — no `urlopen`, no no-follow opener, no base-url
    # join, nothing that could reach the network. That ordering IS the bound, expressed in control flow
    # rather than in a comment.
    #
    # WHY A REPORT AND NOT A RUN: the instruments this form exists for — an authenticated POST probe
    # gated in the project's deploy script, a headless-browser gate against the live origin, a
    # served-bundle-marker fetch — are STRONGER evidence than the anonymous GET the kernel models, and
    # they already run at the project's own deploy gate. What was missing was never a runner; it was a
    # place to record the reading.
    #
    # THE FAILING ARM IS NOT SYMMETRIC WITH `_probe_fail` ABOVE, and the difference is the whole point.
    # A failed kernel GET writes nothing because it must never write an ADOPTION record. A REPORTED
    # failure is different in kind: it is a reading that HAPPENED, and the one thing this card exists to
    # prevent is filing bad news as no data. So it emits `live_probe_failed` — a record of a negative
    # result, never an adoption proof — and exits non-zero. Absence and failure stay distinguishable.
    if "attested" in lp:
        report = (getattr(args, "report", None) or "").strip().lower()
        if not report:
            _die(f"live-probe: {tid} declares the ATTESTED form ({lp['attested']!r}, run at "
                 f"{lp.get('runs_at')!r}) — the kernel GRADES that proof, it does not run it "
                 f"(SPEC-0094 §4b). Run the project's own instrument, then record the reading with "
                 f"`--report pass` or `--report fail`.")
        if report not in ("pass", "fail"):
            _die(f"live-probe: --report must be `pass` or `fail` — got {report!r}. A reading that ran "
                 f"and did not pass is recorded as `fail`; it is NEVER left unrecorded (SPEC-0094 §4b).")
        project = (_main_worktree(REPO_ROOT) or REPO_ROOT).name
        revision = _git_resolve_sha("HEAD")
        detail = (getattr(args, "detail", None) or "").strip()
        payload = {"task": tid, "revision": revision, "project": project,
                   "attested": lp["attested"], "runs_at": lp.get("runs_at"),
                   "asserts": lp.get("asserts"), "reported": True}
        if task_realm is not None:
            payload["task_realm"] = task_realm
        if detail:
            payload["detail"] = detail
        etype = "live_probe_passed" if report == "pass" else "live_probe_failed"
        # The locator the operator hands to the card-writing leg comes from the APPENDED ROW ITSELF.
        # `_append_event` returns the event it wrote, so the `ts` here is byte-identical to the one
        # `_journal_locator_matches` will compare against — a re-derived clock reading could differ by
        # a formatting detail and produce a locator that never resolves. It also means this path never
        # READS the journal, which a raw read of the path could not do correctly anyway: the journal is
        # ONE logical history across bounded physical segments (SPEC-0190 rule 1).
        _row = _append_event(etype, tid, payload)
        _ts = str((_row or {}).get("ts") or "").strip() if isinstance(_row, dict) else ""
        locator = f"events.jsonl#ts={_ts}" if _ts else None
        result = "passing" if report == "pass" else "failing"
        if report == "pass":
            print(f"live-probe: {tid} ATTESTED PASS — {lp['attested']!r} (run at {lp.get('runs_at')!r}) "
                  f"reported passing; {etype} emitted (SPEC-0094 §4b — the kernel graded a proof the "
                  f"project performed; no request was issued).")
        else:
            print(f"live-probe: {tid} ATTESTED FAIL — {lp['attested']!r} (run at {lp.get('runs_at')!r}) "
                  f"reported NOT passing; {etype} emitted. This is a RECORDED FAILING reading, never "
                  f"missing and never stale (SPEC-0094 §4b).")
        if locator:
            print(f"  record it on the card:  bin/yitc-v2 task close {tid} "
                  f"--live-probe-outcome-result {result} "
                  f"--live-probe-outcome-evidence {locator} "
                  f"--live-probe-outcome-probed-at <YYYY-MM-DD>")
        else:
            print(f"  (could not read back the emitted row's locator — find it with "
                  f"`bin/yitc-v2 journal query --type {etype} --task {tid}` and pass it to "
                  f"`task close --live-probe-outcome-evidence`)")
        if report == "fail":
            raise SystemExit(2)
        return

    # A WAIVER (`none` present) is a DECLARATION, not an executable assertion — there is nothing to RUN
    # (the §3 close-gate honors the waiver; the runner cannot confirm adoption for it). `"none" in lp` is
    # the SAME assertion-vs-waiver discriminator the validator + the close-gate use (not a new layout).
    if "none" in lp:
        _die(f"live-probe: {tid} declares a `none` waiver, not an executable assertion — nothing to "
             f"probe (SPEC-0094 §3/§4). The waiver is its declared non-adoption; no live GET to run.")

    # ESCALATION form (SPEC-0098 §2): a NAMED security property the deploy seam CANNOT assert read-only.
    # Fail-closed — un-probeable is NEVER a silent pass: emit security_live_probe_escalated (the owner-
    # escalation adoption-evidence) and exit non-zero (the property is NOT confirmed). No GET is run.
    if "unprobeable" in lp:
        project = (_main_worktree(REPO_ROOT) or REPO_ROOT).name
        _append_event("security_live_probe_escalated", tid,
                      {"property": lp["property"], "project": project, "reason": lp["unprobeable"]})
        print(f"live-probe: {tid} ESCALATED — security property {lp['property']!r} is not assertable by a "
              f"read-only GET ({lp['unprobeable']}); security_live_probe_escalated emitted (escalate to "
              f"the owner, never silent-pass; SPEC-0098 §2).")
        raise SystemExit(3)

    # GET-only (SPEC-0094 §4 — "an HTTP GET"). The assertion grammar has no method field, so it is GET
    # by construction; REJECT an explicit non-GET `method:` (a POST/PUT/DELETE/… would mutate prod).
    method = lp.get("method")
    if method is not None and str(method).strip().upper() != "GET":
        _die(f"live-probe: {tid} declares method={method!r} — the runner is GET-ONLY (read-only, never "
             f"mutates prod; SPEC-0094 §4). Reject a non-GET spec.")

    # The validator already confirmed url (non-empty str) + expect_status (int) + body_contains (str?)
    # + (the no-follow dialect) expect_location (str? requiring a redirect expect_status, SPEC-0094 §4).
    url = lp["url"].strip()
    expect_status = lp["expect_status"]
    body_contains = lp.get("body_contains")
    expect_location = lp.get("expect_location")

    # Resolve the absolute target: an absolute `url:` is used as-is; a relative path is joined onto the
    # carrier `live_base_url` (the project-level default, SPEC-0094 §4 home split). --base-url overrides.
    base_url = (getattr(args, "base_url", None) or "").strip() or _carrier_base_url(REPO_ROOT, _die)
    if url.lower().startswith(("http://", "https://")):
        target = url
    else:
        if not base_url:
            _die(f"live-probe: {tid} has a relative url {url!r} but no `live_base_url` (carrier "
                 f"live_probe section is waived/absent and no --base-url given). SPEC-0094 §4 home split: "
                 f"declare `live_probe: live_base_url: <url>` in {CONSUMER_OPS_CONTRACT}.")
        target = base_url.rstrip("/") + "/" + url.lstrip("/")

    revision = _git_resolve_sha("HEAD")
    project = (_main_worktree(REPO_ROOT) or REPO_ROOT).name

    print(f"live-probe: {tid} — GET {target} (expect_status={expect_status}"
          + (f", body_contains={body_contains!r}" if body_contains else "") + ")")

    # NO-FOLLOW dialect (SPEC-0094 §4): when expect_status is a Location-bearing redirect status, assert
    # the IMMEDIATE 3xx instead of following it (the default opener resolves a 301 to the final 200, the
    # X-0096 / T-0082 failure). A no-follow opener turns the 3xx into an HTTPError, caught below with the
    # immediate status + the Location header intact. Non-redirect statuses keep the follow default — no
    # regression for a plain 200 probe.
    no_follow = expect_status in _redirect_statuses
    open_fn = _no_redirect_opener().open if no_follow else urllib.request.urlopen

    # Read-only GET. method='GET' is explicit (urllib defaults to GET, but we PIN it — never POST/mutate).
    req = urllib.request.Request(target, method="GET")
    try:
        with open_fn(req, timeout=_GET_TIMEOUT_S) as resp:  # noqa: S310 — declared http(s) GET
            actual_status = resp.getcode()
            headers = resp.headers          # http.client.HTTPMessage — case-insensitive, get_all() for repeats
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # An HTTP error response (4xx/5xx) is a real status to compare — not a transport failure.
        actual_status = e.code
        headers = e.headers
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — body unavailable on some error responses
            body = ""
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Transport failure (unreachable / DNS / timeout / bad url) — the change is NOT confirmed live.
        _probe_fail(tid, target, f"request failed ({e})", _append_event=None)
        raise SystemExit(2)

    # Assert status + (optional) body_contains. ANY mismatch = the change is NOT confirmed live.
    if actual_status != expect_status:
        _probe_fail(tid, target, f"status {actual_status} != expected {expect_status}", _append_event=None)
        raise SystemExit(2)
    if body_contains is not None and body_contains not in body:
        _probe_fail(tid, target, f"body does not contain {body_contains!r} (status {actual_status} OK)",
                    _append_event=None)
        raise SystemExit(2)

    # NO-FOLLOW dialect (SPEC-0094 §4): assert the immediate redirect's Location header when declared.
    # `expect_location` is only valid with a redirect expect_status (validator-enforced), so `location`
    # is the immediate 3xx target — a mismatch (or absent header) means the redirect is NOT the declared
    # one = the change is NOT confirmed live.
    location = headers.get("Location")
    if expect_location is not None and location != expect_location:
        _probe_fail(tid, target,
                    f"Location {location!r} != expected {expect_location!r} (status {actual_status} OK)",
                    _append_event=None)
        raise SystemExit(2)

    # SECURITY DIALECT (SPEC-0094 §4 / SPEC-0098 §1): a `property`-bearing assertion proves a named security
    # property via header/cookie evaluation → it emits the SECURITY events, not the generic live_probe_passed.
    if _is_security_probe(lp):
        sec_err, expect_s, actual_s = _evaluate_security_assertions(lp, headers)
        if sec_err is not None:
            # A PROBEABLE property that does NOT hold = a security violation = FAIL (no event, exit non-zero;
            # SPEC-0098 §2 fail-closed). Distinct from the un-probeable→escalate form handled above.
            _probe_fail(tid, target, f"security property {lp['property']!r} violated — {sec_err}",
                        _append_event=None)
            raise SystemExit(2)
        # T-12087: WATERMARK the row with the canonical digest of the CARRIER's declaration of this
        # property (SPEC-0093 `verify.floor.probes`). ADDITIVE-OPTIONAL — absent when the project
        # declares no matching `security.probes[]` entry, exactly like `task_realm`/`location` below,
        # so no existing consumer or pinned payload moves. It is what lets the land-time floor bind a
        # historical pass to the DEFINITION it actually exercised with one equality check.
        _sec_payload = {"property": lp["property"], "url": target, "project": project,
                        "expect": expect_s, "actual": actual_s}
        # BOUND TO THE DEFINITION THIS RUN ACTUALLY EXERCISED (r3 finding 7) — a carrier entry
        # selected by `property` alone proves nothing about what the runner just fetched, so the
        # watermark is withheld unless the entry's own url/expect match the executed target.
        _entry = _declared_probe_entry(REPO_ROOT, lp["property"])
        _digest = (probe_definition_digest(_entry)
                   if _probe_entry_exercised(_entry, target=target, expect_s=expect_s,
                                             base_url=base_url) else None)
        if _digest:
            _sec_payload["definition_digest"] = _digest
        _append_event("security_live_probe_passed", tid, _sec_payload)
        print(f"live-probe: {tid} SECURITY PASS — {target}: property {lp['property']!r} holds "
              f"({actual_s}); security_live_probe_passed emitted (the Class-S adoption proof, SPEC-0098 §3).")
        return

    # PASS — the probe's declared assertion holds live. This is the per-change adoption proof only to the
    # extent it exercises the critical user path (SPEC-0094 §4a); a /healthz-class liveness assertion is
    # process-liveness, never product-health (X-0371). Emit the adoption proof.
    payload = {"task": tid, "revision": revision, "project": project, "url": target,
               "expect_status": expect_status, "actual_status": actual_status}
    if task_realm is not None:
        # The governing card lives in the KERNEL corpus, not this consumer's — record it, so the evidence
        # never silently implies a consumer card that does not exist (SPEC-0094 §4 keying). Additive-optional,
        # like `location` below: a consumer-own run's payload is byte-identical to before.
        payload["task_realm"] = task_realm
    if expect_location is not None:
        # Record the immediate 3xx + matched Location — the no-follow adoption proof (SPEC-0094 §4).
        payload["location"] = location
    _append_event("live_probe_passed", tid, payload)
    print(f"live-probe: {tid} PASS — {target} returned {actual_status}"
          + (f" -> Location {location!r}" if expect_location is not None else "")
          + (f" and body contains {body_contains!r}" if body_contains else "")
          + "; live_probe_passed emitted (the per-change adoption proof, SPEC-0094 §4).")


_SECURITY_DIALECT_FIELDS = ("assert_header_present", "assert_header_absent", "assert_cookie_flags")


def _is_security_probe(lp: dict) -> bool:
    """A live_probe is a SECURITY probe (emits the security_* events) when it carries an ACTUAL header/
    cookie assertion field (SPEC-0098 §1). Branch on the assert_* fields, NOT `property` alone: the
    validator (task.py#_security_dialect_error) couples them (`property` ⟺ ≥1 assert_* on an assertion),
    so a bare `property` can never reach here — keying on the real fields avoids a hollow security pass."""
    return any(f in lp for f in _SECURITY_DIALECT_FIELDS)


def _as_header_list(val) -> list:
    return val if isinstance(val, list) else [val]


def _cookie_flags(set_cookie: str) -> set:
    """Parse the flags present on a single `Set-Cookie:` line → a lowercase flag set. `HostOnly` is
    SYNTHETIC: a cookie is host-only exactly when it carries NO `Domain=` attribute (SPEC-0098 §1)."""
    parts = [p.strip() for p in set_cookie.split(";")]
    flags = set()
    has_domain = False
    for attr in parts[1:]:                     # parts[0] is `name=value`
        low = attr.lower()
        if low == "secure":
            flags.add("secure")
        elif low == "httponly":
            flags.add("httponly")
        elif low.startswith("domain="):
            has_domain = True
    if not has_domain:
        flags.add("hostonly")
    return flags


def _find_set_cookie(set_cookies: list, name: str) -> "str | None":
    """Find the `Set-Cookie` line whose cookie NAME (the token before the first `=`) matches `name`."""
    for sc in set_cookies:
        cname = sc.split("=", 1)[0].strip()
        if cname == name:
            return sc
    return None


def _evaluate_security_assertions(lp: dict, headers) -> "tuple[str | None, str, str]":
    """Evaluate the SPEC-0098 §1 header/cookie security assertions against the response `headers`
    (an http.client.HTTPMessage). Returns (failure_reason | None, expect_summary, actual_summary). A
    None failure means the security property HOLDS. Multi-valued headers (Set-Cookie) are read via
    `headers.get_all(...)` so repeats are never collapsed (audit-pre F2)."""
    expect_parts, actual_parts = [], []
    for h in _as_header_list(lp.get("assert_header_present", []) or []):
        expect_parts.append(f"header {h} present")
        val = headers.get(h)
        if val is None:
            return (f"required header {h!r} is ABSENT", "; ".join(expect_parts), "; ".join(actual_parts))
        actual_parts.append(f"{h}={val}")
    for h in _as_header_list(lp.get("assert_header_absent", []) or []):
        expect_parts.append(f"header {h} absent")
        val = headers.get(h)
        if val is not None:
            return (f"header {h!r} must be ABSENT but is present ({val!r})",
                    "; ".join(expect_parts), "; ".join(actual_parts))
        actual_parts.append(f"{h}=<absent>")
    cookie_flags = lp.get("assert_cookie_flags") or {}
    set_cookies = headers.get_all("Set-Cookie") or []
    for cookie_name, want_flags in cookie_flags.items():
        want = [f.lower() for f in want_flags]
        expect_parts.append(f"cookie {cookie_name} flags {sorted(want_flags)}")
        sc = _find_set_cookie(set_cookies, cookie_name)
        if sc is None:
            return (f"cookie {cookie_name!r} is not Set-Cookie'd",
                    "; ".join(expect_parts), "; ".join(actual_parts))
        present = _cookie_flags(sc)
        missing = [f for f in want if f not in present]
        if missing:
            return (f"cookie {cookie_name!r} missing flag(s) {missing} (has {sorted(present)})",
                    "; ".join(expect_parts), "; ".join(actual_parts))
        actual_parts.append(f"{cookie_name}:{sorted(present)}")
    return (None, "; ".join(expect_parts), "; ".join(actual_parts))


def _probe_fail(tid: str, target: str, why: str, *, _append_event) -> None:
    """Print a probe FAILURE to stderr. Emits NO event (a failed probe leaves no adoption proof — the
    change stays not-adopted; SPEC-0094 §4). `_append_event` is accepted for signature symmetry but is
    intentionally unused: failure must never write an adoption record."""
    import sys
    print(f"live-probe: {tid} FAIL — {target}: {why}. No live_probe_passed emitted; the change is NOT "
          f"confirmed live (stays not-adopted, SPEC-0094 §4).", file=sys.stderr)
