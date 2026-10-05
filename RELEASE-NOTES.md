# Release v2.3.0

Source commit: `47e7c012daee70023a86378780f328d88184f540`

## Proposals this release answers

The proposals below were re-authored in the workshop and ship in this release (the contribution policy, `CONTRIBUTING.md`, step 4).

```yaml
answers:
  - 'yitc-dev/yitc#1'
  - 'yitc-dev/yitc#10'
  - 'yitc-dev/yitc#11'
  - 'yitc-dev/yitc#12'
  - 'yitc-dev/yitc#13'
  - 'yitc-dev/yitc#14'
  - 'yitc-dev/yitc#15'
  - 'yitc-dev/yitc#16'
  - 'yitc-dev/yitc#17'
  - 'yitc-dev/yitc#18'
  - 'yitc-dev/yitc#19'
  - 'yitc-dev/yitc#2'
  - 'yitc-dev/yitc#20'
  - 'yitc-dev/yitc#21'
  - 'yitc-dev/yitc#22'
  - 'yitc-dev/yitc#23'
  - 'yitc-dev/yitc#24'
  - 'yitc-dev/yitc#25'
  - 'yitc-dev/yitc#26'
  - 'yitc-dev/yitc#27'
  - 'yitc-dev/yitc#28'
  - 'yitc-dev/yitc#29'
  - 'yitc-dev/yitc#3'
  - 'yitc-dev/yitc#4'
  - 'yitc-dev/yitc#5'
  - 'yitc-dev/yitc#6'
  - 'yitc-dev/yitc#7'
  - 'yitc-dev/yitc#8'
  - 'yitc-dev/yitc#9'
  - 'yitc-dev/yitc-archive-2026-10-02#1'
  - 'yitc-dev/yitc-archive-2026-10-02#10'
  - 'yitc-dev/yitc-archive-2026-10-02#11'
  - 'yitc-dev/yitc-archive-2026-10-02#12'
  - 'yitc-dev/yitc-archive-2026-10-02#18'
  - 'yitc-dev/yitc-archive-2026-10-02#24'
  - 'yitc-dev/yitc-archive-2026-10-02#25'
  - 'yitc-dev/yitc-archive-2026-10-02#26'
  - 'yitc-dev/yitc-archive-2026-10-02#27'
  - 'yitc-dev/yitc-archive-2026-10-02#29'
  - 'yitc-dev/yitc-archive-2026-10-02#3'
  - 'yitc-dev/yitc-archive-2026-10-02#30'
  - 'yitc-dev/yitc-archive-2026-10-02#31'
  - 'yitc-dev/yitc-archive-2026-10-02#32'
  - 'yitc-dev/yitc-archive-2026-10-02#33'
  - 'yitc-dev/yitc-archive-2026-10-02#34'
  - 'yitc-dev/yitc-archive-2026-10-02#35'
  - 'yitc-dev/yitc-archive-2026-10-02#36'
  - 'yitc-dev/yitc-archive-2026-10-02#4'
  - 'yitc-dev/yitc-archive-2026-10-02#5'
  - 'yitc-dev/yitc-archive-2026-10-02#7'
  - 'yitc-dev/yitc-archive-2026-10-02#8'
  - 'yitc-dev/yitc-archive-2026-10-02#9'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#1'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#10'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#11'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#12'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#13'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#14'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#15'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#16'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#17'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#18'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#2'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#20'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#21'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#24'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#25'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#26'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#27'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#29'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#3'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#4'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#5'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#6'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#7'
  - 'yitc-dev/yitc-archive-2026-10-02-v2-2-0#9'
```

See `CONTRIBUTING.md` for what happens to a proposal, and `release-manifest.yaml` for this release's provenance and digest.

## What changed

62 task(s) closed since the previous release tag, in close order:

- T-13486 — Make session pick show a project whose folder is gone as missing and refuse it with a plain message (fix) — events.jsonl#ts=2026-10-03T20:25:41Z
- T-13488 — Install the home picker command with a stable engine path, never a linked-worktree engine's (fix) — events.jsonl#ts=2026-10-03T20:33:35Z
- T-13491 — Make the home picker command ask in plain chat text and say which language to use before the person writes (fix) — events.jsonl#ts=2026-10-03T20:43:17Z
- T-13485 — Let the adopter release verbs run from any checkout without letting a bare call journal into the kernel (fix) — events.jsonl#ts=2026-10-03T21:08:38Z
- T-13484 — Repo-qualify every answers id and refuse a bare (fix) — events.jsonl#ts=2026-10-03T21:24:29Z
- T-13487 — Resolve the capture-routing view's owning specs against the kernel in a -C consumer session and mark them (fix) — events.jsonl#ts=2026-10-03T21:32:41Z
- T-13490 — Move the MCP reconcile from session start to before the first MCP use, and report extras instead of disabling them (fix) — events.jsonl#ts=2026-10-03T21:50:08Z
- T-13489 — Make the followup pair fold drop repeated archive lines by exact digest lookup, so task file with promotes stops burning ~24 min of CPU (fix) — events.jsonl#ts=2026-10-03T21:52:33Z
- T-13465 — Refuse abbreviated long options on every SPEC-0209 guarded verb (fix) — events.jsonl#ts=2026-10-03T22:15:01Z
- T-13454 — Read only production-target deploy_completed rows as the live revision in the not-adopted lens and the auto-rollback target (fix) — events.jsonl#ts=2026-10-03T22:33:24Z
- T-13460 — Resolve a same-second owner-directive locator by coverage, never by file order, in audit decide --directive and hostapply --confirmed-by (fix) — events.jsonl#ts=2026-10-03T22:46:24Z
- T-13457 — Revive the t11451 journal-coupling instrument in the nightly quiet lane and surface a failing quiet-lane instrument on the debt echo (fix) — events.jsonl#ts=2026-10-03T23:19:55Z
- T-13492 — Ship the release-view AGENTS part under a name the AI tool does not auto-attach, so a consumer start loads it once (fix) — events.jsonl#ts=2026-10-04T01:13:59Z
- T-13459 — Keep the audit evidence fold one-pass for audit consult, audit pre --on-decisions and an audit post that a land overlaps (7.7-10.4 GB peaks) (refactor) — events.jsonl#ts=2026-10-04T06:59:30Z
- T-13463 — Guard the graph conformance, live-node graft and debt-echo card walks with one shared card-shape check (fix) — events.jsonl#ts=2026-10-04T07:13:04Z
- T-13504 — Tell the person how to come back once, through the Start station, not at every picker start (fix) — events.jsonl#ts=2026-10-04T07:16:04Z
- T-13458 — Let worktree park retire a done card's worktree whose only commits ahead of main are merges of main and land bookkeeping (fix) — events.jsonl#ts=2026-10-04T07:28:08Z
- T-13479 — Derive worktree-leg archive identity from the `_verified_archive_blobs` shape, keeping linked-worktree admission (fix) — events.jsonl#ts=2026-10-04T07:29:40Z
- T-13456 — Make the remaining main-checkout self-commits commit by pathspec so another session's staged entry is never swept in (fix) — events.jsonl#ts=2026-10-04T07:53:59Z
- T-13467 — Make the read-contract exemption and skip-count reports truthful (fix) — events.jsonl#ts=2026-10-04T08:29:54Z
- T-13503 — Make the start report's owner-cued lines say "show and wait", so a fresh session stops after its rules, commands and debt (fix) — events.jsonl#ts=2026-10-04T08:35:15Z
- T-13475 — Carry journal-edge selection narrowing to main with a live-read class that requires a resolved journal read (infra) — events.jsonl#ts=2026-10-04T09:02:23Z
- T-13512 — Stop the echoed audit packet from labelling an auditor ABORT an outage (fix) — events.jsonl#ts=2026-10-04T09:20:50Z
- T-13507 — Clear the ended pause's resume_from and next_action when a task is resumed (fix) — events.jsonl#ts=2026-10-04T09:39:53Z
- T-13508 — Warn at emit when a task-tied event will not reach the audit packet, from one shared fold rule (fix) — events.jsonl#ts=2026-10-04T09:40:48Z
- T-13509 — Make spec edit refuse or correct a block-body edit whose written result means something other than the asked edit (fix) — events.jsonl#ts=2026-10-04T10:00:35Z
- T-13505 — Ship every continuation part of a split spec with its base, and refuse a publish that would drop one (fix) — events.jsonl#ts=2026-10-04T10:24:12Z
- T-13513 — Keep an auditor ABORT's failure cause readable after the next pass rewrites the verdict file (fix) — events.jsonl#ts=2026-10-04T11:04:35Z
- T-13506 — Make release update remove an engine path the new release dropped, and name it in the update report (fix) — events.jsonl#ts=2026-10-04T12:38:20Z
- T-13391 — Stream the auto-sync RECOVERY source-ref fold instead of materialising every journal line (refactor) — events.jsonl#ts=2026-10-04T12:41:33Z
- T-13515 — Classify a code land into a cost zone per changed function, with the cheap allowlist and the L/N/R gate-class knobs — not wired into land (infra) — events.jsonl#ts=2026-10-04T12:43:56Z
- T-13501 — Stop tests/_read_gate.py storing the live journal path so the events.jsonl selection family stops covering its 483 importers (infra) — events.jsonl#ts=2026-10-04T12:45:56Z
- T-13464 — Contain a raise from any per-project nightly check, and grade corpus staleness by content instead of file mtimes (fix) — events.jsonl#ts=2026-10-04T12:56:09Z
- T-13511 — Record each consumer verify layer's timeout in force, and count a timeout change as a rewired layer (fix) — events.jsonl#ts=2026-10-04T13:19:07Z
- T-13516 — Freeze the cost-zone cohort floor — the global baseline and census tests plus a derived verb-to-tests mapping (infra) — events.jsonl#ts=2026-10-04T13:35:57Z
- T-13510 — Deliver a stage's contract bodies once per context epoch, and stop telling the reader to fetch them again (fix) — events.jsonl#ts=2026-10-04T13:51:25Z
- T-13514 — Run the declared pre-deploy dump on an owner-approved Class C2 deploy and say so when none is declared (feature) — events.jsonl#ts=2026-10-04T14:10:11Z
- T-13519 — Let a local candidate verify anchor the inert first-attempt land skip, keeping the any-author floor on every skipped land (fix) — events.jsonl#ts=2026-10-04T15:12:45Z
- T-13525 — Make the pinned last-green verify leg switchable for the engine like for a project, and switch it off (infra) — events.jsonl#ts=2026-10-04T15:28:56Z
- T-13528 — Let a yitc-ops.yaml change that leaves the verification sections equal stop disabling every layer's subject skip at land (fix) — events.jsonl#ts=2026-10-04T16:10:56Z
- T-13526 — Show a card held by a live dispatched worker as held at session start, not as waiting on the owner or as an own-resume (fix) — events.jsonl#ts=2026-10-04T16:18:17Z
- T-13524 — Add a third pass to the born test-class intake — split a heavy, narrow-subject group into its own subject-scoped layer (docs) — events.jsonl#ts=2026-10-04T17:03:39Z
- T-13523 — Ask about the opt-in verify capabilities at the stage where a card declares or changes verify.layers (fix) — events.jsonl#ts=2026-10-04T17:45:55Z
- T-13527 — Name the moment to send the start line — as its own message right after session start returns, before the read (fix) — events.jsonl#ts=2026-10-04T17:50:20Z
- T-13522 — Signal a consumer verify layer's duration growth at the land tail, from the per-layer durations land already records (fix) — events.jsonl#ts=2026-10-04T17:55:06Z
- T-13533 — Skip a consumer's subject-disjoint verify layers at Stage 6 as land does, against the base land will use (fix) — events.jsonl#ts=2026-10-04T18:15:18Z
- T-13517 — Record the cost-zone shadow decision on every code land's land_completed row, acting on nothing (infra) — events.jsonl#ts=2026-10-04T18:51:27Z
- T-13531 — Let a consumer tests/** change force only the verify layers that own it, keeping shared test files on the full run (fix) — events.jsonl#ts=2026-10-04T19:49:23Z
- T-13538 — Render every task-tied tests_passed row since the claim in the audit-post packet's Stage-6 section, not only the latest (fix) — events.jsonl#ts=2026-10-04T20:19:27Z
- T-13541 — Follow an npm run <script> layer command into the package.json script text in the verify-layer registry resolver (fix) — events.jsonl#ts=2026-10-04T20:36:00Z
- T-13536 — Point a worker's scratch logs at a directory that exists: $YITC_SCRATCH_DIR first, the worktree's.yitc/ only after mkdir -p (fix) — events.jsonl#ts=2026-10-04T20:45:00Z
- T-13535 — Measure what the heaviest test files spend their time on and say per file what can go without weakening the check (docs) — events.jsonl#ts=2026-10-04T20:46:27Z
- T-13543 — Remove the cost-zone shadow machinery of the cancelled risk-cohort plan from the land path (refactor) — events.jsonl#ts=2026-10-04T20:53:10Z
- T-13539 — Name the arming session and time of a live watcher in the duplicate-watch refusal, and list the hand-off author's live watchers at session handoff take (fix) — events.jsonl#ts=2026-10-04T21:01:24Z
- T-13532 — Count a runner-produced Stage-6 green on the same tree as the land's candidate verdict when main has not moved (feature) — events.jsonl#ts=2026-10-04T21:11:15Z
- T-13540 — Count a re-dispatch into an existing task worktree once in the dispatch-readiness workers line (fix) — events.jsonl#ts=2026-10-04T21:13:45Z
- T-13544 — State in SPEC-0207 and SPEC-0152 that verify.independent_layers is the project's own declared risk judgement, admissible without owns: (docs) — events.jsonl#ts=2026-10-04T21:56:05Z
- T-13545 — Re-run a failed consumer verify layer once alone and record it as a flaky retry instead of aborting the land (infra) — events.jsonl#ts=2026-10-04T22:29:25Z
- T-13537 — Halt a dispatched worker at a terminal --on-decisions RED with the terminal exits, and point its audit-ceiling pause and recovery hint at those exits (fix) — events.jsonl#ts=2026-10-04T22:53:27Z
- T-13471 — Make audit decide and task close derive a late finding's ceiling_ref from the same carrier, so a finding on a counterless post row can be decided (fix) — events.jsonl#ts=2026-10-05T07:46:42Z
- T-13470 — Stop three debt lines over-reporting: late findings that block no close, overdue observations on wont-do cards, and interactive holders read as not seen (fix) — events.jsonl#ts=2026-10-05T08:06:21Z
- T-13468 — Give an event-class awaits one row predicate so unrelated rows of the awaited type stop firing followups and probe moments (fix) — events.jsonl#ts=2026-10-05T08:20:55Z

## Trust surfaces

GENERATED by `yitc-v2 work publish`; do not edit in the mirror.

* artifact tree digest: see `tree_digest` in `release-manifest.yaml` — its single home
* signature target: `release-manifest.yaml` (detached signature: `release-manifest.yaml.sig`)
* trust root: `trust-root.yaml` · revocations: `revoked-keys.yaml` (anchor-signed:
  `revoked-keys.yaml.sig`) · policy: `SECURITY.md`

## Verifying entrypoint inventory

Every entrypoint below verifies the signed manifest against the trust root — anchored out of band —
BEFORE it writes anything. Driving any of them with a tampered artifact refuses. A path that
installs or updates this release and is NOT listed here is a gap in this inventory (SPEC-0195
rule 6).

- `release verify` — `yitc-v2 release verify <dest> --anchor <fingerprint>`
  Verify a published release in place. Never writes into the release being verified, and never creates a journal — it is the gate itself. (On a checkout that already has a governed journal it appends one `release_verified` provenance row there, on refusal as well as on success; on a clean adopter machine there is no such journal and it writes nothing at all.)
- `release install` — `yitc-v2 release install <dest> --into <path> --anchor <fingerprint>`
  Install a verified release into <path>. A refused install writes no RELEASE CONTENT into <path> — the gate reaches its verdict before <path> is opened, and a refused install never creates <path> or a journal in it. (If <path> is a governed checkout that ALREADY has a journal, one `release_installed` provenance row is appended there, on refusal as well as on success; the release being installed FROM is never written to.)
- `release update` — `yitc-v2 release update <dest> --into <path> --anchor <fingerprint> [--from-release <pinned-release-N tree>]`
  Move an EXISTING install at <path> from release N to N+1. The gate reaches its verdict BEFORE <path> is opened, so a refused update writes NOTHING into <path> and leaves it byte-identical (SPEC-0195 rule 6, 'BEFORE any write', read literally). On the SUCCESS path only upstream-owned and template-owned paths are written: consumer-owned paths — the project's own files, which no release shipped — are reported and never written, and a template-owned file both sides moved is reported as a CONFLICT rather than guessed (rule 8). A path the PREVIOUS release shipped and this one no longer carries is REMOVED when the `--from-release` tree verifies against the same anchor and the installed copy is still that release's bytes; it is KEPT and named when it was changed locally or that tree does not verify, and with no `--from-release` nothing is removed. (If <path> already has a journal, one `release_updated` provenance row is appended there, on refusal as well as on success; the release being updated FROM is never written to.)

### Running these on a clean machine

Both entrypoints run on a machine that has never used this system: no session, no journal, no
prior setup of any kind. Run them straight out of the clone, using the engine the release itself
ships:

```
python3 <dest>/bin/yitc-v2 release verify <dest> --anchor SHA256:<fingerprint>
python3 <dest>/bin/yitc-v2 release install <dest> --into <path> --anchor SHA256:<fingerprint>
```

`<dest>` is your local clone of this mirror; the anchor fingerprint comes from a channel
INDEPENDENT of the mirror. Nothing else needs to exist first.

What `release verify` writes, stated exactly: NOTHING into `<dest>`, and it never CREATES a
journal anywhere — so on a clean machine it writes nothing at all, which is what makes it safe to
run before you have decided to trust this release. The one thing it may write is a single
`release_verified` provenance row, appended on refusal as well as on success, and ONLY to a
governed journal that ALREADY EXISTS on some checkout OTHER than the release itself. A journal
found inside `<dest>` is never written to, whatever it contains — so running the command from
inside your clone, as above, still writes nothing into it. A clean adopter machine has no such
journal anywhere, so no row is written and the command says so on stderr.

These two are the only commands that run without any prior setup: every other command in this
engine requires a set-up working copy and will tell you so.

## Bootstrap order on a clean machine

`onboarding/bootstrap-order.md` (in this release) carries the order the primary AI reads on a machine that
has nothing on it yet: prerequisites with their check commands, clone -> `release verify` ->
`release install`, `init`, the `yitc-ops.yaml` kernel pin, the external-auditor install + binding,
and the first session. Take the anchor and the three commands above from the org-profile README --
the independent channel -- not from this mirror.

## External auditor setup

The lifecycle runs an EXTERNAL auditor at Audit-pre and Audit-post; `audit pre|post` refuses rather
than running unaudited when it cannot find one. The auditor binary is a PER-MACHINE binding — this
release ships no path to one — so bind it once on each machine, by whichever of these fits:

- install an external auditor CLI so its executable is on `PATH`, and log the CLI in to your own
  subscription. This is the ordinary route and needs no configuration in this release at all;
- point `YITC_CODEX_AUDIT_BIN` at the executable, for an auditor deliberately installed off `PATH`.

Both routes are MACHINE-scoped, and deliberately so. `bin/audit-config.yaml` also carries a
`codex_binary:` key, read as a last resort, but it is NOT the route to reach for: that file travels
in every release, so a path written there is inherited by everyone who adopts your copy of it — and
a per-user path is rejected by this release's own host-literal check.

Unbound, the resolver names both routes in its refusal rather than failing obscurely at spawn.
The tier bindings in `bin/audit-config.yaml` (which auditor, which model, which effort) are this
release's defaults and are yours to change; the lifecycle's normative text names no provider.

## Updating from the previous release

An update needs TWO trees on disk at once: this release, and the release you run today as the
`--from-release` merge base. One clone cannot be both, so keep the release you run today as a
worktree BESIDE the clone, then move the clone forward (rehearsed v2.0.5 -> v2.0.6 on a clean
environment):

```
git -C <dest> worktree add <dest>-<old-tag> <old-tag>
git -C <dest> fetch --tags
git -C <dest> checkout <new-tag>
python3 <dest>/bin/yitc-v2 release verify <dest> --anchor SHA256:<fingerprint>
python3 <dest>/bin/yitc-v2 release update <dest> --into <engine-dir> --anchor SHA256:<fingerprint> --from-release <dest>-<old-tag>
```

`<dest>` is the clone you installed from, `<old-tag>` the release you run today, `<new-tag>` this
release, `<engine-dir>` your existing install. Keep `<dest>-<old-tag>` until the update is settled:
it is the merge base and your way back. Afterwards move the `kernel:` pin in each project's
`yitc-ops.yaml` to `<new-tag>` and run `yitc-v2 -C <project> init`, which adds only what is missing.

What the version digits tell you (SPEC-0195 rule 10): LAST digit (v2.1.0 -> v2.1.1) = fixes only,
you do nothing on update; MIDDLE digit (v2.0.6 -> v2.1.0) = behaviour or what `init` writes changes,
or you are asked to act — read these notes first; FIRST digit = a new methodology generation.
