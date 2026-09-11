# Per-user provisioning checklist — what a NEW developer must install before the lifecycle runs

> **Born:** 2026-07-13 (X-0364). The engine DECLARES commands the invoking user is assumed to
> be able to run — the land-verify suite, the Stage-6 test classes, the external auditor. But those tools
> are provisioned **per user**, and a **second developer** (not the owner) routinely has none of them:
> `pytest` lives only in the owner's home, the external auditor is bound to the owner's personal ChatGPT
> subscription, playwright browsers are absent. The person discovers this only AFTER doing the work —
> stalled mid-lifecycle (aiseller X-0364: a PROD FIX stuck at stage 4/9 on the auditor; <collaborator> incident
>). This checklist is the provisioning home; the **`capability-preflight` session-start
> line** (SPEC-0119 rule 15) is the automated early warning that points here.

## What the preflight tells you

At session-start / land-tail / `bin/yitc-v2 debt`, if any DECLARED command's leading executable is not
on **your** PATH, you'll see one report-only line, e.g.:

```
capability-preflight: 2 capability gap(s) for you (this user) — verify:backend: `pytest` not on your
PATH; audit: no <external-auditor> subscription login found (run `<external-auditor> login`). You'll hit this at the matching
lifecycle stage; provision them — see patterns/per-user-provisioning-checklist.md. Report-only
(SPEC-0119 r15 / SPEC-0093).
```

It is **report-only** — never a gate (CHARTER non-goal #7), never *runs* a command, stays silent when
everything is fine (suppressed-when-clean). It checks **two** per-user capability signals over the
DECLARED lifecycle commands:
- **executability** — is each command's leading tool on YOUR PATH (`yitc-ops.yaml`
  `verify.layers[].command` + `tests.classes[].command`, plus the engine-resolved external-auditor binary);
- **auditor subscription auth** — does a <external-auditor> `auth.json` exist for you (the REAL per-user auditor
  blocker: the binary can be on PATH yet the auditor still can't run without your own `<external-auditor> login`).

**Known limitation (scope bound —).** It checks a command's *leading executable* + the auditor
auth, NOT deeper per-tool provisioning. Notably, Playwright's browser **cache** can be missing even when
`npx`/`playwright` resolves — that browser-cache depth is tracked separately (a followup filed at
), not taught to this general reader. Use the Playwright row below regardless of what the line says.

## The checklist — provision these before you rely on the lifecycle

Work down the list; each row names the tool, the lifecycle stage that needs it, and the fix.

- **`verify.layers[].command` executables (land-verify — every `land`).** The commands your project's
  `yitc-ops.yaml` declares as its land gate (commonly `pytest`, `npx`, a project script). Install the
  tool into **your** environment (e.g. `pip install pytest` in a venv you own, `npm ci` for `npx`
  targets). If it lives only in another user's home, you cannot `land` until you have your own.
- **`tests.classes[].command` executables (Stage 6 — Tests).** Same as above for any test class whose
  `moment` is not `verify`. Provision the runner locally.
- **The external auditor (`<external-auditor>`) (Stage 4 Audit-pre + Stage 8 Audit-post).** The governed auditor runs
  ONLY on ChatGPT **subscription** auth (never an API key — bin/audit-config.yaml). A second developer
  needs their OWN <external-auditor> binary AND their OWN subscription auth:
  - Install the unconfined <external-auditor> the auditor expects (bin/audit-config.yaml `codex_binary`), or point
    `YITC_CODEX_AUDIT_BIN` at your <external-auditor> executable.
  - Provide subscription auth via `CODEX_HOME` (bin/audit-config.yaml `codex_home`, default
    `~/snap/<external-auditor>/current`). Without it, Audit-pre/post ABORT — surface to the owner, do not proceed
    without a verdict.
- **Playwright browsers (if a project's verify/test layer drives a browser).** `npx playwright install`
  downloads the browsers into your home; absent, the browser-driven layer fails (X-0364 class). Note the
  preflight does NOT detect this (it sees only that `npx`/`playwright` resolves) — run the install once
  per user regardless.

## Related

- The automated surface: SPEC-0119 rule 15 (`bin/yitc-v2 graph query SPEC-0119`) — the `capability-preflight`
  debt-echo line; `bin/lib/session.py#capability_preflight_lines`.
- The per-user-surface doctrine: SPEC-0093 (the per-user provisioning realm this checklist serves).
- Sibling on a DIFFERENT axis: records per-user-surface *staleness* (entry-skill / permission
  allowlist rot) — that is about surfaces going stale, this is about tools not being installed.
- Onboarding a whole person: `patterns/onboarding-a-person-onto-yitc.md`.
