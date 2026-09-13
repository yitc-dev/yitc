# Release v2.0.4

Source commit: `b15e4ac96e3add597e023020227f6a5adbf634cf`

## Proposals this release answers

This release answers no outside proposal.

```yaml
answers: []
```

An empty list is stated rather than omitted, so that it reads as an answer and not as a missing link-back.

See `CONTRIBUTING.md` for what happens to a proposal, and `release-manifest.yaml` for this release's provenance and digest.

## What changed

53 task(s) closed since the previous release tag, in close order:

- T-12352 — Re-word the bootstrap-order doc paragraph 6 from required-different-provider to recommended-with-a-stamped-fallback, pointing at the binding file, once CHARTER §4a is amended (docs)
- T-12382 — Give the SPEC-0204 decision route a PLAN-GATE arm — a plan gate whose consult episode ended terminal takes Controller decisions + ONE --on-decisions pass, and a malformed auditor response spends no plan-gate budget (successor of) (feature)
- T-12384 — land verify surfaces the pytest failure tail on an unmarked layer failure instead of the container teardown output (fix)
- T-12383 — audit decide refuses fail-closed when subject_revision is unresolvable and resolves it from the ceiling row, never from a worktree-only verdict file (fix)
- T-12386 — The P8-adoption floor machine-refutes an adoption-gap finding on a NON-infra card — CHARTER §8 binds infra-class only (fix)
- T-12385 — audit decide journals the RESOLVED full evidence sha and on-decisions admission compares resolved revisions — a short-sha --evidence no longer strands the pass (fix)
- T-12351 — A worker that stopped after task close under the controller-lands regime reads as the CONTRACTED completion — dispatch-status, the watcher and the debt views name it «closed, awaiting the Controller's land», never land-dead / halt / recovery (fix)
- T-12414 — Close the SPEC-0161 payload-key residual — after a branch that introduced NO key still reddens on test_spec0161_payload_key_refresh in the venue candidate leg while passing locally; find the shape of the un-named key and make the introducing-branch check (or the attribution) catch it (fix)
- T-12413 — A yield-offer is never written to a branch whose LAND HAS NOT STARTED — the writer stamps an addressee land pid or writes no offer, and a governed verb clears a stale one (the fourth yield-offer hole; fleet-wide park 2026-09-11) (fix)
- T-12400 — Interactive Controller transcript auto-sync joins on the provider session id, and a dispatch preamble is never journaled as an owner_directive (fix)
- T-12410 — Add task commit --reship — the GREEN-audited second in-scope ship leg, sibling of --absorb and --fix-red (feature)
- T-12394 — A post-sync smoke before the verify slot — after update-from-main the land runs the affected selection plus the always-run tripwires on the MERGED tree locally and refuses BEFORE queueing for the venue (feature)
- T-12412 — Under -C credit SPEC-0161 names from the kernel record and route a consumer's unnamed keys to cross request instead of a forbidden spec edit (fix)
- T-12396 — The debt abort lines count a land-reservation park-limit eviction APART from a failed attempt — «evicted from the queue N» beside the abort count, never inside it (fix)
- T-12393 — A land evicted by the reservation park bound re-queues ITSELF while the holder keeps changing, and stops only when ONE holder sat out the whole bound — the narrow auto-requeue, attempt-capped (feature)
- T-12425 — Route a Stage-6 task test --run to the venue on a SNAPSHOT of the working tree, never the committed HEAD (fix)
- T-12424 — Make the audit-decide concurrency tripwire green at its measured cause — tests/test_ceiling_decisions_decide.py::test_concurrent_decisions_are_serialized_to_one_row is red 11/12 on the engine host and flaky on the venue, aborting green lands on the pinned leg (fix)
- T-12428 — De-pin the two wall-clock timing legs (t11451 coupled bite-proof, t11808 AC3 leg 2) — phase 2, re-filed as its own card: the legs leave the per-land pinned discovery set by name and run only in the SPEC-0105 nightly quiet lane (feature)
- T-12427 — Pair the verifier-locator exemption across the SAME FINDING, not only inside one recorded value — a structured criterion_ref plus the test path in fix: is a locator, not an authored-defect path ( card-repair refusal) (fix)
- T-12416 — Correct the copyright holder in LICENSE to Sergey Dodonov (MIT unchanged, no email) (hygiene)
- T-12397 — spec new under -C warns when the next id is kernel-owned and cited bare in this corpus, and accepts an explicit --id (feature)
- T-12422 — SPEC-0204 admission survives the mandatory post-ceiling commits — a re-audit-after-close gets its own pass row, and subject/evidence pins are checked by ANCESTRY, not equality (the / / ledger deadlocks) (fix)
- T-12404 — Order the accepted-stage work before the accept-gate check and name the freshness basis in the stale plan-check refusal (docs)
- T-12392 — Land prints the currently-unresolved cross-branch abort cause(s) BEFORE running verify (SPEC-0119 rule-26 fold read at land head) (feature)
- T-12411 — Charge a branch for a SPEC-0161 governing key only when no structural readback of it existed in bin at the merge-base (fix)
- T-12430 — Strip sentence-final punctuation from a repo-path token in _repo_path_tokens — a verifier path followed by a period is the same path, not an authored-defect path (the card-repair residual measured) (fix)
- T-12398 — Drop the stale kupiclub waive examples from SPEC-0109 §5 and SPEC-0110 rule 1 and add a named-consumer-example conformance probe (docs)
- T-12401 — Name the covering-directive route at the moment of use — the directive-not-covering refusal, audit decide --help, the halt marker, SPEC-0204 rule 2 (docs)
- T-12403 — task pick and dispatch preflight refuse a cut card of a pre-executing plan by name (SPEC-0070 §5 claim-block parity) (fix)
- T-12433 — Skip in card-record part (1) a repo-path token the CITED acceptance criterion names verbatim — an AC-quoted CLI invocation (`bin/yitc-v2 -C <repo> debt`) is the card's own text, not an authored-defect path (the window-only repair does not reach) (fix)
- T-12432 — Retire the post-sync presmoke — it re-runs the SAME governed selection the candidate leg runs, inside the serialized land reservation (4–9 min per kernel land, 0 refusals since it), so even a narrow-bounded smoke is a duplicate run; remove the block, its keys and its tests, record the retirement (fix)
- T-12435 — Classify a later-pass finding whose located content is byte-identical to the pass-1 subject as a LATE finding mechanically — today the rule-8 split trusts the auditor's `causality` declaration and fails closed on its absence, so one omitted field on an unchanged test node turned rule-3 pass into a card-terminal RED (2026-09-12) (fix)
- T-12434 — Re-home the further-ship route onto a fresh ceiling row — its deliverable is built and green on branch task/ (2b30f47: empty-set ancestry arm + repin ceiling exemption + SPEC-0204/0124 amendments) but its audit-post went card-terminal on an auditor-omitted `causality` for an UNCHANGED AC2 probe; port the branch content, reshape the one AC2 terminal-bound probe through the new `--on-decisions` arm, ship (fix)
- T-12407 — task pause --awaits with an artifact-wait reason so the startup echo says RESUMABLE once the awaited item closes (feature)
- T-12420 — Post-ff land bookkeeping never breaks the invariants of the tree it just verified — the tail's writes are verified before the ff or cannot fail a test (fix)
- T-12155 — Cut the share of kernel lands forced onto the full suite by the R1 bin/** self-guard, naming the refusing path on the record first (infra)
- T-12387 — Adopter-facing entry docs for the public mirror: rewrite the stale README, add an on-demand overview the AI voices to the person, and explain the anchor fingerprint in plain words on all three entry surfaces (docs)
- T-12388 — Wire the shipped `release update` into the CLI and into the verifying-entrypoint inventory so an adopter can move a pinned project from release N to N+1 (infra)
- T-12439 — Fold an audit-post pass whose EVERY finding is machine-refuted to GREEN (canonical verdict), keeping `verdict_as_returned: RED` + the verbatim refutations — the rule-8 late-only fold applied to the two machine-decidable refutation classes ( blocked with no exit; external consult GREEN, option A) (fix)
- T-12423 — The SPEC-0161 unnamed-key preflight attributes a key from ADDED CODE, not from an emitted row — so the branch that introduces an emitter is refused at its OWN land (fix)
- T-12389 — Add the read-only `release check`: tell a pinned project whether a newer release exists on its mirror, naming the tags and their release notes, writing nothing (feature)
- T-12444 — A GREEN ceiling row with zero residuals must not strand a legitimate second in-scope ship: task commit --reship opens a NEW Stage-8 ceiling row for the new commit (one bounded first pass), instead of leaving audit-post unreachable (fix)
- T-12441 — Port the aiseller report-mode fix into the kernel `bin/security-audit` scaffold — 0664 group-shared publish + an UNREADABLE-vs-FOREIGN refusal arm — so `init --refresh-scaffolds` on aiseller loses nothing (fix)
- T-12406 — Read a consumer verify-layer TIMEOUT as its own verify-failed layer-timeout arm in the debt echo, never as a caught defect (fix)
- T-12408 — A consumer-side adoption ask must name a catalogued event key and must not promise no-nag that the receiver's echo contradicts (fix)
- T-12445 — Make the SPEC-0145 security audit report's profile snapshot drive the gate — a `status: present` report whose check_set_hash is a strict subset of the CURRENT required set is NOT FRESH (successor of the parked, same claim, fresh ceiling) (infra)
- T-12390 — Adopter troubleshooting-and-updates doc: what to do when the kernel misbehaves, how to check for and install an update, how to roll back — one page the AI voices to the person (docs)
- T-12438 — Move the verify wiring out of bin/lib/cli.py into a module that already refuses R1 — `_run_verify_tests` / `_run_pinned_verify` / the selection root `_is_verify_implementation_touch` / `_VERIFY_IMPLEMENTATION_GLOBS` — so cli.py's argparse bulk (125 sole R1 refusals in 2 weeks, the single largest refuser) becomes admissible under SPEC-0181 R1 without freeing any verify participant (infra)
- T-12402 — Exclude non-defect severity-pass rows from the ceiling-row residual set so a plan-gate on-decisions pass needs decisions only on real findings (fix)
- T-12405 — Give the audit prompt a class_id vocabulary and let the recorder derive a class before refusing a RED finding as malformed (fix)
- T-12447 — Make tests/test_t_land_head_abort_breadth.py deterministic on the verify venue under load — it failed the candidate leg 2/2 in the isolated retest at load1 15.5 with NO assertion captured, passed locally 8/8 and on the same tree one attempt later; find the load/isolation dependence of its real-cmd_land sandbox, fix the cause, and make the venue runner record a failing file's output tail so the next such flake is diagnosable from the journal (fix)
- T-12391 — Release notes carry a human-readable change list: the tasks closed between the previous release tag and this one, generated by the publish writer from the journal (feature)
- T-12448 — Auto-resolve a land / worktree-sync merge conflict in kernel-vs-self-manifest.md that is confined to its GEN-managed sentinel regions — take-ours + regenerate at the step-3 graph build, the FIFTH auto-resolvable class beside derived artifacts and the spec implements_signature block (: 2 of 4 conflict-aborts named it) (fix)

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
