# Release v2.2.1

Source commit: `242b8c4c4a394c60f7fd9cb99cec6a4ebdc62d56`

## Proposals this release answers

The proposals below were re-authored in the workshop and ship in this release (the contribution policy, `CONTRIBUTING.md`, step 4).

```yaml
answers:
  - '#1'
  - '#10'
  - '#11'
  - '#12'
  - '#13'
  - '#14'
  - '#15'
  - '#16'
  - '#17'
  - '#18'
  - '#2'
  - '#20'
  - '#21'
  - '#24'
  - '#25'
  - '#26'
  - '#27'
  - '#29'
  - '#3'
  - '#30'
  - '#31'
  - '#32'
  - '#33'
  - '#34'
  - '#35'
  - '#36'
  - '#4'
  - '#5'
  - '#6'
  - '#7'
  - '#8'
  - '#9'
```

See `CONTRIBUTING.md` for what happens to a proposal, and `release-manifest.yaml` for this release's provenance and digest.

## What changed

68 task(s) closed since the previous release tag, in close order:

- T-13364 — Serve audit decide's whole-history own leg from the segment index instead of holding every journal row in memory (fix) — events.jsonl#ts=2026-10-02T09:34:47Z
- T-13352 — Answer graph conformance's two whole-history journal report views from an index instead of a whole-journal fold (fix) — events.jsonl#ts=2026-10-02T09:37:10Z
- T-13280 — State the X/Y/Z partial hand-off rules in SPEC-0205 and the spike-mode runbook (docs) — events.jsonl#ts=2026-10-02T10:16:14Z
- T-13379 — Make the audit pre/post read gate fold the journal once on the refused path (1.5x, ~50 s, 4 GB) (refactor) — events.jsonl#ts=2026-10-02T11:16:30Z
- T-13281 — Make the spike hint and the declared-spike land refusal state the SPEC-0205 route (fix) — events.jsonl#ts=2026-10-02T11:31:32Z
- T-13371 — Make session start read each journal segment at most once and cut its peak memory (1.05x, 4.9 GB) (refactor) — events.jsonl#ts=2026-10-02T11:55:12Z
- T-13381 — Serve audit post's whole-history journal readers from the segment index (fix) — events.jsonl#ts=2026-10-02T12:08:29Z
- T-13366 — Make dispatch read each journal segment at most once (4.3x folds per segment measured) (refactor) — events.jsonl#ts=2026-10-02T12:09:34Z
- T-13380 — Find why seven verbs peak at 1.4-7.7 GB resident memory and cut the worst (refactor) — events.jsonl#ts=2026-10-02T12:39:21Z
- T-13390 — Point the SPEC-0145 record-at hint at security.audit, the place the sweep reads (fix) — events.jsonl#ts=2026-10-02T13:04:22Z
- T-13384 — Install the /yitc-projects start command at release install and let it create the first project (fix) — events.jsonl#ts=2026-10-02T13:05:46Z
- T-13282 — Print two advisory stand-role lines in deploy from one pure tolerant role reader (feature) — events.jsonl#ts=2026-10-02T13:30:04Z
- T-13388 — Keep init --dry-run from writing the journal by exempting it from the CLI journal auto-sync (fix) — events.jsonl#ts=2026-10-02T13:37:32Z
- T-13382 — Make the release identity guard catch registered names inside compound tokens and in the publish commit identity (fix) — events.jsonl#ts=2026-10-02T13:53:19Z
- T-13389 — Make the bootstrap-order engine pin template name the local mirror clone path, and check what a resolved pin bakes into project files (fix) — events.jsonl#ts=2026-10-02T13:54:14Z
- T-13373 — Give the followup verbs (list, drop, unarm, show) a horizon-bounded or indexed journal read (1.4 GB, whole history) (refactor) — events.jsonl#ts=2026-10-02T14:04:37Z
- T-13368 — Make stage read each journal segment at most once and only within its horizon (2.1x measured) (refactor) — events.jsonl#ts=2026-10-02T14:13:31Z
- T-13372 — Bound task file's journal read to a declared horizon instead of whole history (12 s of reads) (refactor) — events.jsonl#ts=2026-10-02T14:16:57Z
- T-13369 — Make worktree new read each journal segment at most once (2.0x measured) (refactor) — events.jsonl#ts=2026-10-02T14:16:58Z
- T-13392 — Stop dispatched workers paying a read-gate refusal round trip after discarding a stage bundle or truncating a contract fetch (fix) — events.jsonl#ts=2026-10-02T14:27:55Z
- T-13393 — Exclude the filing checkout's own branch from the in-flight intent overlap advisory under -C (fix) — events.jsonl#ts=2026-10-02T16:33:52Z
- T-13394 — Split newcomer station [L] by host state so it tells the truth where no kernel is registered (docs) — events.jsonl#ts=2026-10-02T16:47:38Z
- T-13403 — State at session handoff write when a hand-off may be written and that it is not re-written while work continues (fix) — events.jsonl#ts=2026-10-02T17:02:21Z
- T-13385 — Install the start command for every AI tool from an extendable tool list — the AI tool and <external-auditor> by default, more per machine without a card (fix) — events.jsonl#ts=2026-10-02T17:29:13Z
- T-13283 — Rewrite onboarding, README and the org page in the DEV and ACCEPTANCE stand words (docs) — events.jsonl#ts=2026-10-02T17:31:15Z
- T-13395 — Say in a consumer session that a read-amplified seam is the kernel's cost, not a BLOCKING item of the project (fix) — events.jsonl#ts=2026-10-02T17:47:36Z
- T-13397 — Refuse worktree park while a spike sandbox serves live code from that worktree (fix) — events.jsonl#ts=2026-10-02T18:02:19Z
- T-13396 — Make the dispatch watch loop read only the appended journal tail per poll instead of re-folding it (fix) — events.jsonl#ts=2026-10-02T18:08:37Z
- T-13400 — Give audit pre past a GREEN ceiling row one route to re-audit a Controller-amended plan (fix) — events.jsonl#ts=2026-10-02T18:22:12Z
- T-13410 — Make a box leg's `session start` receipt-only by recognising a linked checkout of a bare clone that has no main checkout (fix) — events.jsonl#ts=2026-10-02T18:51:46Z
- T-13409 — Exclude the archive segments land's JSON gate already proved from its conflict-marker grep, and fail closed when that grep errors (fix) — events.jsonl#ts=2026-10-02T19:13:02Z
- T-13411 — Run the merged-base runner on the remote pinned leg and validate each leg against its own runner digest (fix) — events.jsonl#ts=2026-10-02T19:52:11Z
- T-13386 — Give the agent one start order and a guide to the clean-machine pitfalls, and answer in the person's language (fix) — events.jsonl#ts=2026-10-02T19:52:16Z
- T-13398 — Journal a deploy that changed production and then failed its gate or was interrupted (fix) — events.jsonl#ts=2026-10-02T20:17:32Z
- T-13374 — Bound grants trail's journal read to a declared horizon or the index (7 s whole history) (refactor) — events.jsonl#ts=2026-10-02T22:24:34Z
- T-13415 — Take the land reservation before a queue-jump mark commits to main, so the mark never discards a mid-verify land (fix) — events.jsonl#ts=2026-10-02T22:35:05Z
- T-13417 — Cut a derived scenario id at a word boundary and let scenario new take an explicit --slug (fix) — events.jsonl#ts=2026-10-02T23:05:29Z
- T-13412 — Make validate_envelope classify a remote leg whose runner raised as INDETERMINATE venue-fault, never GREEN (fix) — events.jsonl#ts=2026-10-02T23:13:31Z
- T-13418 — Tell helper subagents of a started session to skip the born adapter's start routine (fix) — events.jsonl#ts=2026-10-02T23:39:21Z
- T-13378 — Bound audit canary-backstop's journal read to a declared horizon (whole history) (refactor) — events.jsonl#ts=2026-10-03T00:12:03Z
- T-13376 — Bound profile's journal read to a declared horizon or the index (whole history) (refactor) — events.jsonl#ts=2026-10-03T00:36:27Z
- T-13408 — Make land's post-ff evidence-custody report read the committed journal once and only from the counted rows' earliest date (custody measured at 40-58 s per task land) (fix) — events.jsonl#ts=2026-10-03T00:38:13Z
- T-13413 — Run the rule-8 local-probe leg concurrently with the venue box legs instead of after them (fix) — events.jsonl#ts=2026-10-03T00:59:42Z
- T-13419 — Make audit pre's RED-verdict exit read each journal segment at most once (249 folds, 7.4 GiB measured) (refactor) — events.jsonl#ts=2026-10-03T01:22:20Z
- T-13370 — Make worktree sweep read each journal segment once within a declared horizon (1.2x, whole history) (refactor) — events.jsonl#ts=2026-10-03T01:28:21Z
- T-13416 — Resolve a same-second ts locator to its one citable row and stop suggesting an unrelated row as from (fix) — events.jsonl#ts=2026-10-03T01:53:58Z
- T-13420 — Bound audit post --plan's journal read to a declared horizon or the index (whole history, 4.7 GiB measured) (refactor) — events.jsonl#ts=2026-10-03T01:55:29Z
- T-13407 — Decide the fail-closed edge before deriving the coverage map in _shadow_select, and record each box leg's post-run seconds (fix) — events.jsonl#ts=2026-10-03T01:58:39Z
- T-13375 — Bound memory consume and memory seed journal reads (whole history, 1.0-3.6 GB) (refactor) — events.jsonl#ts=2026-10-03T05:24:01Z
- T-13426 — Remove the stale DRAFT sentence and the principle-N placeholder cite from active SPEC-0171 (fix) — events.jsonl#ts=2026-10-03T06:15:51Z
- T-13365 — Make land read each journal segment at most once (8.5x folds per segment measured) (refactor) — events.jsonl#ts=2026-10-03T06:38:06Z
- T-13434 — Align SPEC-0005 rule 7 with the graph dangling check — implements alone no longer declares delivery (fix) — events.jsonl#ts=2026-10-03T06:45:32Z
- T-13425 — Scope the AGENTS manifest paragraph's assembled-view note to the Worker and list AGENTS.md in the numbered read-order (fix) — events.jsonl#ts=2026-10-03T06:46:36Z
- T-13430 — Let a post-ceiling card-only repair close by making audit decide and audit post --on-decisions name the same subject (fix) — events.jsonl#ts=2026-10-03T06:47:07Z
- T-13422 — Deliver each seed spec at session start as a one-sentence cue plus a pointer instead of a bare title (fix) — events.jsonl#ts=2026-10-03T07:19:17Z
- T-13427 — Keep file paths and URLs intact when the release view strips provider names, and check named paths exist (fix) — events.jsonl#ts=2026-10-03T07:24:51Z
- T-13428 — Build the shipped graph index from the redacted release sources so index and spec agree (fix) — events.jsonl#ts=2026-10-03T07:24:52Z
- T-13429 — Refresh an unmodified engine-written /yitc-projects command on release install and update (fix) — events.jsonl#ts=2026-10-03T07:31:17Z
- T-13433 — Journal the AI tool auto-attached release-view AGENTS.md and stop a consumer start reading it a second time (fix) — events.jsonl#ts=2026-10-03T08:06:56Z
- T-13431 — Make an unbound echo of a decided ceiling residual loud instead of a silent fresh RED (fix) — events.jsonl#ts=2026-10-03T08:07:51Z
- T-13377 — Bound work commit's journal read to a declared horizon (whole history, 6 s) (refactor) — events.jsonl#ts=2026-10-03T08:23:19Z
- T-13432 — Bound how many Stage-6 suites run at once on the published verify venue (infra) — events.jsonl#ts=2026-10-03T09:07:01Z
- T-13436 — Stop the venue admission wait from consuming a Stage-6 leg's execution timeout (fix) — events.jsonl#ts=2026-10-03T09:17:04Z
- T-13435 — End the session-start report with a startup-done line and mark every non-seed echo line report-only, owner-cued or on-demand (fix) — events.jsonl#ts=2026-10-03T10:05:48Z
- T-13438 — Let task update --awaits set parked_awaits on an already-parked card as a field repair (fix) — events.jsonl#ts=2026-10-03T11:43:03Z
- T-13439 — Let a governed deploy's passing security probe keep the land floor's probe verdict fresh (fix) — events.jsonl#ts=2026-10-03T12:15:57Z
- T-13441 — Carry venue pre-ship to main with the AC3 shipped-identity check validating merge parentage (infra) — events.jsonl#ts=2026-10-03T12:53:55Z
- T-13440 — Carry land-proof archive passes to main with AC3's threat model bounded to honest engine drift (infra) — events.jsonl#ts=2026-10-03T13:02:30Z

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
  Move an EXISTING install at <path> from release N to N+1. The gate reaches its verdict BEFORE <path> is opened, so a refused update writes NOTHING into <path> and leaves it byte-identical (SPEC-0195 rule 6, 'BEFORE any write', read literally). On the SUCCESS path only upstream-owned and template-owned paths are written: consumer-owned paths — every path the release does not ship — are reported and never written, and a template-owned file both sides moved is reported as a CONFLICT rather than guessed (rule 8). (If <path> already has a journal, one `release_updated` provenance row is appended there, on refusal as well as on success; the release being updated FROM is never written to.)

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
