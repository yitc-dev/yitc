---
name: test-file-wall-attribution
class: observation
binding: []
sourced_from: <durable artifact> (measurement of this repo's own suite, 2026-10-04) — per-file walls from three single-leg land rows of events.jsonl (18:10Z / 18:27Z / 19:07Z, after), one sampled run of the 175 heaviest files under the land-verify runner's own child environment, a cProfile pass over the 94 in-process-heavy ones, and a per-file reading of the sources
applies_to: deciding where test-suite time can be cut without weakening a check — which causes are worth a card, which are not, and what a per-file cut does and does not do to the suite's wall. Consumed by the owner's decision on followups fu_058acc949384, fu_83a583a4e5f8, fu_54839bd6fbb5, fu_743b567bc071, fu_389fc69d291e, fu_379c8b9b3603, fu_ccf294fd0f51, fu_6e1913294c93, fu_579fccdcf654, fu_49c6b2ae7e9a, fu_7e261a3b7299, fu_8066154b09aa, fu_ecb2fc47c4f0.
---

# Observation — the heaviest test files spend their time inside their own process, not in git fixtures, worktrees or lands

> **Reading, not a fix.** Produced. No test was edited and no card was filed; the thirteen
> groups in §5 are followups for the owner to decide on.

## §1 — Verdict in one line

Across the 174 measured files of the 176 heaviest (54 % of all test work), **56 % of the wall is
in-process work of the test itself**, 12 % is re-running other test files, 12 % other CLI children,
12 % other child processes — and a real `land` is **1.2 %**, worktree operations **1.5 %**, git
fixture commands **5.6 %**. The cuts that keep every check intact remove **about 14 % of total test
work (1946 s of 13765 s)**; the owner's target — the git-fixture group at 4 s per file and the suite
at half its time — is **not reachable by trimming tests**, and §6 says what is.

## §2 — Method

### 2a. Three recorded inputs and one reading

The instrument and its three recorded inputs live in this repository's workshop instruments directory
— a surface a release does not carry (SPEC-0195 rule 1a) — so they are named here as the provenance
of these figures, not as tools that travel with this pattern. The method is stated in full below.

| # | Input | What it gives | How it was produced |
|---|---|---|---|
| A | `test-file-wall-durations-.json` | each file's wall on the verify venue, per land, and each land's worker count, leg wall and serialized tail | `extract` over the logical journal: the green single-leg (`verify_mode candidate_policy_off`) full-suite `land_completed` rows since. Three rows qualify; per file the lower median is used |
| B | `test-file-wall-sample-.json` | for one run of each heavy file: every child process and in-process copy the test process opened, timed | `sample`: each file spawned as the runner spawns it (`python <file>`, cwd = the checkout, env = `verify_runner.hermetic_child_env`), with a shim timing `subprocess.Popen` and `shutil.copytree` |
| C | `test-file-wall-dispositions-.json` | per file: what it proves, the cause class of its dominant cost, whether that cost can go and how, the removable share | a reading of each source against B (and against a cProfile of the 94 files whose wall is mostly in-process — the existing recipe `measure-land-verify-attribution.py profile`) |

A's file names are re-derived per row from the tree the land **verified** — the row's recorded
candidate tree (`venue_cand_tree`); only a row that records none is judged against its branch commit
— and a row is accepted only when the name count equals the series count, never retried against
another tree. The branch commit alone matched one row in four on this day
(main moves under a queued branch), which is why the recorded candidate tree is the judge; the fourth
row's series (2022 walls) does not match its candidate tree (2083 files) and is skipped.

### 2b. The attribution rule — exclusive

Only intervals the **test process itself** opened take part. Each has one class, by its argv: real
land, nested suite, nested test file, worktree operation, other CLI, git fixture, other process,
in-process copy. The run is cut at every interval boundary and each piece goes to exactly one class
— the first active one in that order — or to the **in-process remainder** when none is active. So a
file's shares sum to 100 % whatever overlaps, and what a child does inside itself is never counted
twice. Shares are ratios inside one file's own run and are applied to its **recorded venue wall**;
the sample's own seconds are never quoted as a cost.

### 2c. Controls

- **Positive control:** a file is attributed only if it exited 0 under the collector — 174 of 176.
- **Cross-check:** sample wall / recorded wall per file — median 0.58, p10 0.47, p90 0.97. The local
  runs are faster than the venue's (48 files at once there, 4 here), which is why only ratios cross.
- **Profiles:** all 94 profiled totals are at least 30 % of the file's sampled wall. A first profile
  pass was discarded: its temp boxes sat inside the checkout and one file bailed out in 0.1 s — an
  apparatus artifact (`lessons/a-measurement-taken-outside-its-harness-measures-the-harness.md`).
- **The removable share is capped by the measurement:** no file claims more than the measured share
  of the classes its cause can touch.

### 2d. Three quantities that must not be mixed

**Aggregate file-seconds** is the sum of per-file walls — work, what a cut removes. **Leg wall** is
what the suite takes: 48 workers over the pool, then the serialized tail one file at a time. The
runner's own schedule model (greedy, longest first) reproduces the three observed leg walls within
1–4 % (§3.1), so it is used for the after-cut figure. **Observed verify wall** adds push, admission
and post-run, which no test cut touches (522 s against a 384 s leg on the 18:27Z land).

## §3 — The measurement

Printed by `attribute-test-file-wall-.py --top 176` (workshop instruments directory) at the commit that
ships this reading. `marks` is a text read of the source (G git fixture · W worktree · L land ·
S nested suite · T another test file · C the CLI) — what a file MENTIONS; the attribution column is
what it SPENDS. The two disagree often, which is the finding.

# 1. Recorded durations
window: since until verify_mode candidate_policy_off · skipped rows (count mismatch): 1
land 4405c42 files 2083 workers 48 · aggregate 13909.7 s · observed leg wall 446.9 s · modelled leg wall 442.5 s · model/observed 0.99 · tail files 11
land 669179b files 2083 workers 48 · aggregate 10940.0 s · observed leg wall 384.1 s · modelled leg wall 379.7 s · model/observed 0.99 · tail files 11
land 1833e56 files 2084 workers 48 · aggregate 14004.5 s · observed leg wall 460.3 s · modelled leg wall 444.1 s · model/observed 0.96 · tail files 11
files 2084 · aggregate file-seconds (per-file median) 13764.8 s
heaviest 50: 3938.2 s = 28.6% · the 50th file 53.3 s
heaviest 100: 5910.8 s = 42.9% · the 100th file 27.7 s
heaviest 170: 7457.8 s = 54.2% · the 170th file 17.8 s
heaviest 250: 8719.0 s = 63.3% · the 250th file 14.3 s
heaviest 500: 11167.4 s = 81.1% · the 500th file 6.3 s
heaviest 1000: 13035.8 s = 94.7% · the 1000th file 1.9 s

# 2. The 176 heaviest files
| # | file | wall s | attribution (exclusive shares of the sampled run) | marks | cause | removable | saving s | basis | what it proves — and what can go, or why nothing can |
|---:|---|---:|---|---|---|---|---:|---|---|
| 1 | test_publish_surface_boundary.py | 199.1 | in-process remainder 91% · other process 8% · git fixture 1% | C | I2-repeated-derivation | partly | 49.8 | sampled | The published surface excludes exempt paths and the real work-publish refuses planted… — Share the strip of the identical clean tree between the two clean-differential calls (lines ~432 and ~570) by caching strip… |
| 2 | test_t11030_sweep_construction_rules.py | 161.4 | in-process remainder 100% | TC | I2-repeated-derivation | partly | 72.6 | sampled | The three revizia sweep-construction rules each report the problem while the pre-fix… — Memoize REF.derive_event_map per (root, consumer) at module level so the identical REPO_ROOT derivation runs once and every… |
| 3 | test_t13330_task_close_memory.py | 144.2 | nested test file 91% · in-process remainder 8% · git fixture 1% | C | R2-self-child-harness | no | 0.0 | sampled | task close peak RSS stays far below the journal bulk it reads, versus a materialising… — ru_maxrss is a per-process high-water mark, so each arm must be a fresh child over the large bulk. The children are the… |
| 4 | test_t12232_introducing_branch_names_the_key.py | 115.5 | other process 43% · nested test file 39% · in-process remainder 17% · git fixture 2% | GWL | R1-reruns-suite-member | partly | 40.4 | sampled | A SPEC-0161 payload key is charged to the branch that introduces it, checked with… — Drop the live-checkout subprocess run of test_event_catalog_completeness.py, since the suite already runs it; keep the… |
| 5 | test_t11113_coverage_map_evidence.py | 110.6 | in-process remainder 100% | S | I3-engine-hot-path | partly | 44.2 | sampled | Every test reading a mapped source family is covered by the effective coverage map's… — Precompile each family's target globs once with re.compile(fnmatch.translate(t)), or test exact names with a set first,… |
| 6 | test_t12208_session_start_read_scope.py | 109.9 | in-process remainder 92% · other process 6% · git fixture 1% · worktree op 1% | GWC | X-subject-inherent | no | 0.0 | sampled | session start installs one request-scoped ReadScope, collapsing journal and card… — The assertions count the physical reads the real composed session start performs, so running it (counter on) is the proof;… |
| 7 | test_t12155_selection_refusal_path.py | 104.8 | in-process remainder 99% · nested test file 1% | ST | I1-corpus-derivation | yes | 41.9 | sampled | A refused land records the matched path beside the matched glob, and each freed bin… — Memoize the whole-corpus reader derivation, keyed on the content of tests/ and bin/. Every T6 iteration then reuses one… |
| 8 | test_t11474_tests_coverage_map_entry.py | 103.5 | in-process remainder 100% | - | I1-corpus-derivation | partly | 56.9 | sampled | The real SPEC-0181 coverage map frees a leaf-test diff, keeps infra/delete/rename/bin… — Take the derived (readers, always) pair from a content-keyed per-run cache or precomputed artifact instead of deriving at… |
| 9 | test_t12937_publish_install_smoke.py | 100.4 | in-process remainder 58% · other CLI 17% · other process 16% · git fixture 9% | G | I1-corpus-derivation | partly | 20.1 | sampled | work publish refuses a candidate whose install smoke (session start, init) fails, and… — Memoise strip_published_text/strip_and_index by tree content so the broken-template publish reuses the good arm's stripped… |
| 10 | test_release_verify_clean_machine.py | 96.1 | in-process remainder 56% · other CLI 23% · git fixture 13% · other process 6% | GWC | I2-repeated-derivation | partly | 38.4 | sampled | release verify/install/update run on a clean adopter machine without a session, yet… — Memoize host_literal_violations by content hash of the cut (or build the Mirror once per file and copy it per arm); the… |
| 11 | test_t12232_introducing_branch_names_the_key_2.py | 93.4 | nested test file 100% | - | R1-reruns-suite-member | yes | 88.7 | sampled | Two other gate test files (event catalog completeness, spec0161 payload-key refresh)… — Drop the child runs; the suite run already runs both files on their own, and a red there reds the same land. Keep a check… |
| 12 | test_t11511_bin_periphery_allowlist.py | 91.6 | in-process remainder 100% | SC | I1-corpus-derivation | partly | 32.1 | sampled | The bin/** verifier-touch rule frees only an explicit allowlist and still forces the… — Serve the coverage map and reader derivation from a content-keyed cache or per-run precomputed artifact; keep every… |
| 13 | test_t11449_reader_multiset_identity.py | 88.2 | in-process remainder 99% · git fixture 1% | G | I1-corpus-derivation | partly | 13.2 | sampled | Every journal reader returns the same event multiset before and after real rotation,… — Obtain the live census from a shared content-keyed per-run cache instead of rebuilding the enumerator over bin/ here; the… |
| 14 | test_tail_loadsens_reader_agreement.py | 81.1 | nested test file 99% | - | R1-reruns-suite-member | partly | 16.2 | sampled | The land-tail verdict withholds or admits a fresh load-sensitive entry according to… — Memoize the first green run of test_load_sensitive_set.py for the unmodified, same-budget green case and reuse it. The… |
| 15 | test_load_sensitive_set.py | 80.8 | in-process remainder 70% · nested test file 30% | S | I3-engine-hot-path | yes | 36.4 | sampled | the load-sensitive carrier is only ever appended to, never removed, and the runner… — In _carrier_writers, derive segments from the pre-split `lines` list using node lineno/col_offset slicing instead of… |
| 16 | test_t11883_anchor_read_is_a_family_read.py | 79.3 | in-process remainder 100% | TC | I1-corpus-derivation | partly | 23.8 | sampled | A read through an anchor variable counts as a read of that path's family in the… — Take the live readers map and the rel=None per-file analysis from a shared content-keyed cache computed once per run,… |
| 17 | test_engine_canary_immutable.py | 76.6 | other process 56% · other CLI 27% · git fixture 10% · worktree op 4% | GWC | C3-slow-verb-is-subject | partly | 15.3 | sampled | Served engine runs use an immutable per-sha kernel checkout; the canary advances first… — Inject a no-op or shared precompile dep in the serve acts of tests that do not assert bytecode; only the AC2 sealing test… |
| 18 | test_t12497_selection_read_vs_mention_pairs.py | 75.2 | in-process remainder 100% | ST | I1-corpus-derivation | partly | 22.6 | sampled | Each of the 45 READ pairs is selected, and each MENTION pair is not, by the real… — Take the coverage map from a content-keyed cache or per-run artifact keyed on tests plus derivation source; keep the 17… |
| 19 | test_task_test_run_complete_failing_set.py | 75.2 | nested test file 88% · in-process remainder 8% · git fixture 3% · worktree op 1% | GWSC | R3-fixture-suite-run | partly | 22.6 | sampled | task test --run reports the complete failing set, while the land verify still stops at… — Lower WAIT_CAP from 10s to about 4s so correct code finishes sooner. Leave the uncapped AC3 gate and the real land unchanged. |
| 20 | test_t12666_emitter_branch_is_charged.py | 74.9 | nested test file 99% · git fixture 1% · in-process remainder 1% | G | X-subject-inherent | no | 0.0 | sampled | A branch shipping an uncatalogued emitter is charged on its own branch; a rows-only… — The real gate's exit code and AC1 arm line on each mutated fixture ARE the assertions; each run uses distinct fixture… |
| 21 | test_t11848_selection_anchor_derivation.py | 73.6 | in-process remainder 100% | TC | I1-corpus-derivation | partly | 14.7 | sampled | the selection coverage map resolves Path(__file__) loader anchors, with a pre-fix scan… — Share the per-file _selection_analyse result through a content-keyed on-disk or per-run cache across arms and sibling… |
| 22 | test_views.py | 72.0 | in-process remainder 98% · git fixture 2% · other process 1% | TC | I3-engine-hot-path | partly | 21.6 | sampled | Every shipped view runs through graph query and yields non-empty output of its lens… — Cache _read_yaml/state.load_path results keyed on (path, mtime, size) in the engine so repeated queries stop re-parsing the… |
| 23 | test_followup.py | 71.7 | other CLI 93% · in-process remainder 3% · other process 2% · git fixture 2% | GWC | C1-cli-per-case | partly | 14.3 | sampled | The followup capture verbs (add/promote/drop/list/show) fold correctly in-process and… — Where `followup list` is only an observer of post-state (read-only check, show tests), read the sink fold in-process or… |
| 24 | test_t13138_land_journal_memory.py | 71.6 | other process 86% · in-process remainder 8% · git fixture 6% · worktree op 1% | - | P1-python-child-snippet | no | 0.0 | sampled | A whole production land over a large synthetic journal stays within a memory budget,… — The claim is the peak memory of a real land process, which needs a separate process and a real journal. An in-process run… |
| 25 | test_t11329_seed_gate_window_parity.py | 71.3 | in-process remainder 100% | - | X-subject-inherent | no | 0.0 | sampled | The cheaper seed-read gate reaches the identical accept/refuse verdict as the pinned… — The gate's read volume and verdict over real-shaped journals is the thing compared; shrinking or memoizing the parse would… |
| 26 | test_t11475_hermetic_decidability.py | 70.9 | in-process remainder 100% | - | I1-corpus-derivation | yes | 42.5 | sampled | tests/_hermetic.py is statically decidable and the documented always-run share equals… — Read derived readers, the always-run set and per-file is_corpus from a shared content-keyed cache of the selection… |
| 27 | test_event_catalog_completeness.py | 70.2 | in-process remainder 100% | C | I2-repeated-derivation | partly | 24.6 | sampled | no live-emitter event type introduced by the diff lacks a spec home, and the recorded… — Parse the journal once (shared segment_lines pass) and reuse the parsed rows for live_types, the key census and the third… |
| 28 | test_t13297_worktree_new_one_pass.py | 70.2 | in-process remainder 89% · git fixture 10% · worktree op 1% | C | I3-engine-hot-path | partly | 28.1 | sampled | worktree new --task reads each journal segment at most once, within its horizon, with… — Memoise the spec YAML load (state.load_str or _stage_bundle_specs) per run in the test, or fix it in the engine; the… |
| 29 | test_consumer_land_verify_metrics_verdict.py | 68.3 | in-process remainder 66% · real land 34% · git fixture 1% | GWLC | I3-engine-hot-path | yes | 34.1 | sampled | A consumer land's verify_metrics fail_class and verify_wall_ms describe the declared… — Precompute line offsets once, or use ast.unparse(node), instead of ast.get_source_segment(src, n) per node. |
| 30 | test_release_spec_closure.py | 67.3 | in-process remainder 84% · git fixture 15% | G | I1-corpus-derivation | partly | 10.1 | sampled | The published spec set carries every spec id its init and seed surfaces name, and… — Speed the engine strip (reuse the parsed spec, or use a C dumper) while still stripping the full tree per sha. |
| 31 | test_t12438_cli_verify_wiring_moved.py | 67.2 | in-process remainder 100% | ST | I1-corpus-derivation | yes | 40.3 | sampled | cli.py derives as periphery and is freed from the full suite after the verify wiring… — Take the reader map from a content-keyed shared cache or a per-run artifact. The three shadow_select calls then only do… |
| 32 | test_t10471_unmonitored_dispatches.py | 65.3 | git fixture 74% · other CLI 23% · in-process remainder 3% | GC | I3-engine-hot-path | partly | 19.6 | sampled | The unmonitored-dispatch debt fold fires per task, stays silent when clean, and never… — Stub or inject the git-history reader behind the debt/dispatch-status calls (the file already injects the other seams) and… |
| 33 | test_t12262_venue_refs_immutable_under_suite.py | 65.1 | in-process remainder 83% · other process 16% · git fixture 1% | GSC | P2-waiting | partly | 6.5 | sampled | a verify leg cannot move the shared venue refs; the shipped leg guard restores main… — Possibly a sub-second VENUE_OVERLAP_POLL_S, if the leg script accepts fractional values. Not verified, so only a small… |
| 34 | test_t13452_journal_family_narrowing.py | 63.8 | in-process remainder 85% · other process 15% | T | I1-corpus-derivation | yes | 35.1 | sampled | The events.jsonl reader family is measured and classified, with no reader excluded… — Take the derived (readers, always) pair from a content-keyed cache or per-run precomputed artifact of… |
| 35 | test_t13398_deploy_failed_row.py | 62.2 | other CLI 99% · other process 1% | GC | C3-slow-verb-is-subject | no | 0.0 | sampled | A deploy that starts and then fails or is interrupted leaves exactly one deploy_failed… — The real deploy verb's exit-code propagation, SIGTERM handling and journal row are the assertions; an in-process call would… |
| 36 | test_t13330_task_close_one_pass.py | 59.1 | nested test file 65% · in-process remainder 17% · git fixture 15% · in-process copy 2% | G | R2-self-child-harness | partly | 8.9 | sampled | A task close folds each journal segment at most once, within its horizon, with… — Run the cases that need no process isolation in-process, resetting module state, and keep children only where counters or… |
| 37 | test_t13288_verb_read_contract.py | 58.5 | nested test file 99% · in-process remainder 1% | GW | R2-self-child-harness | no | 0.0 | sampled | Every verb invocation folds each journal segment and card at most once within its… — Each probe must be a fresh real invocation, preamble and body, to count folds and peak memory; in-process calls would… |
| 38 | test_verify_implementation_rule_narrowed.py | 58.4 | in-process remainder 100% | - | I1-corpus-derivation | yes | 35.0 | sampled | The verify-implementation rule frees residue, still refuses runner edits, and guards… — Obtain the coverage-map families from a shared content-keyed or per-run precomputed selection coverage map instead of… |
| 39 | test_t0952_worktree_not_consumer.py | 58.0 | worktree op 87% · other CLI 13% | GWC | X-subject-inherent | no | 0.0 | sampled | an engine git worktree is not treated as a consumer, so concurrent worktree graph… — The race repro needs N real worktrees of the real engine with real graph builds. The unit arms already use small fixture… |
| 40 | test_ceiling_decisions_retirements.py | 57.9 | other CLI 99% · in-process remainder 1% | C | C2-corpus-graph-build | yes | 23.2 | sampled | The post-ceiling consult and owner-reset machinery is retired behind shims that refuse… — Memoise _spec_body per spec_id so each of the five specs is queried once. |
| 41 | test_t11442_journal_consumer_census.py | 57.2 | in-process remainder 65% · other process 35% | C | I2-repeated-derivation | partly | 14.3 | sampled | The committed journal-consumer census equals a live re-run of the enumeration and the… — Have the AC5 arm render from the live build result already computed in test_census_is_closed, instead of launching the… |
| 42 | test_t9307_pinned_rebaseline.py | 56.7 | git fixture 41% · in-process remainder 35% · nested test file 19% · worktree op 5% | GWLSTC | R3-fixture-suite-run | no | 0.0 | sampled | The re-baseline land path, its waive scoping and its fail-closed refusals, through… — Land verify over the fixture tests dir (candidate and pinned legs) is exactly what the rebaseline and waive assertions are… |
| 43 | test_t12232_consumer_root_reads_kernel_record.py | 56.5 | in-process remainder 98% · git fixture 2% | GLC | I2-repeated-derivation | partly | 22.6 | sampled | Under -C the SPEC-0161 record is read from the kernel, and an unnamed key routes to a… — In the AC4 test, share one journal scan across the helper calls (spec0161_branch_unnamed and the engine record lookup).… |
| 44 | test_t13501_read_gate_no_stored_journal.py | 56.0 | in-process remainder 100% | - | I1-corpus-derivation | partly | 30.8 | sampled | tests/_read_gate.py stores no journal path, guards by resolved equality, and its… — Obtain the derived readers map from a shared content-keyed per-run cache instead of deriving it here; keep… |
| 45 | test_t12375_dead_holder_children_reaped.py | 55.5 | other process 67% · in-process remainder 31% · git fixture 2% | GC | P3-external-tool | yes | 33.3 | sampled | worktree park --confirm-dead reaps a dead holder's orphan children and refuses a live… — Pass an injected docker=lambda p, **kw: ([], None) in the arms that do not test the docker read; the file already injects… |
| 46 | test_land_late_gate_inventory.py | 55.4 | in-process remainder 100% | S | I2-repeated-derivation | partly | 19.4 | sampled | Every refusal reachable after the verify at land is dispositioned and coherent with… — Memoize _derive/land_path_functions and the per-test ast.parse of the engine sources once per module (functools.cache or… |
| 47 | test_t12585_independent_verify_layers.py | 55.4 | in-process remainder 69% · other process 31% | C | P2-waiting | no | 0.0 | sampled | Layers declared independent run overlapped in the land verify guard, with fail-fast,… — The overlap claim is measured as a ratio against real layer wall time. The serial differential has already been deduped to… |
| 48 | test_close_post_verification_warn.py | 54.4 | in-process remainder 94% · in-process copy 3% · worktree op 2% · git fixture 2% | C | I3-engine-hot-path | partly | 21.8 | sampled | A non-hygiene task close without a post_verification criterion or waive is refused,… — Memoize _build_binding_views and the spec parse in the engine, keyed on corpus path, mtime and size. The sandbox copy still… |
| 49 | test_t12942_machine_read_files_keep_values_through_strip.py | 53.4 | in-process remainder 81% · other process 15% · git fixture 4% | - | I2-repeated-derivation | partly | 13.3 | sampled | The release strip leaves machine-read yaml/json values intact and every published file… — Strip the full published tree once and derive the machine-read subset from that result instead of stripping the subset… |
| 50 | test_t11446_archive_admission.py | 53.3 | in-process remainder 99% · git fixture 1% | GSC | I3-engine-hot-path | partly | 13.3 | sampled | The repo admits an archive journal segment through the merge attribute, housekeeping… — Speed up _event_dedup_key / _keys in the engine (cheaper canonical key, or hash key caching). The test stays unchanged. |
| 51 | test_t10547_shell_substitution_artifact.py | 50.8 | in-process remainder 87% · git fixture 11% · worktree op 2% | GWC | I3-engine-hot-path | partly | 15.2 | sampled | shell-eaten substitution residue in prose fields warns, safe shapes stay silent, and… — Inject a stub for the spec0161_branch_unnamed seam in the _run_work_commit kwargs, as the other seams already are, or… |
| 52 | test_t12779_journal_redact_refusals.py | 49.1 | other CLI 97% · git fixture 2% · in-process remainder 1% | C | C2-corpus-graph-build | partly | 19.6 | sampled | journal redact refuses fail-closed with bytes untouched, and SPEC-0163 states the rule… — Take the CONFORMANCE: GREEN verdict from a shared per-run, content-keyed conformance result instead of building the corpus… |
| 53 | test_t11339_derived_coverage_map.py | 49.0 | in-process remainder 100% | - | I1-corpus-derivation | partly | 24.5 | sampled | The affected-test coverage map is derived from what each test reads: new readers are… — Take the real-corpus map from a content-keyed cache or per-run precomputed artifact shared with t11113, keeping the small… |
| 54 | test_ceiling_decisions_conformance.py | 48.9 | in-process remainder 96% · git fixture 4% | C | C2-corpus-graph-build | partly | 12.2 | sampled | graph conformance goes RED on retired audit flags in help text, passes with the check… — Share the yaml tree parse across the 8 conformance runs (content-keyed memo of the corpus load); keep every real-seam run. |
| 55 | test_t11112_shared_fail_closed_edge.py | 48.7 | in-process remainder 100% | TC | I1-corpus-derivation | yes | 39.0 | sampled | The layer-skip and file-skip mechanisms share one fail-closed edge carrier, which a… — Share one content-keyed reader derivation across the 22 calls, or stub the derivation, since the arms judge only edge rungs… |
| 56 | test_t13424_venue_preship.py | 47.8 | other process 67% · git fixture 22% · in-process remainder 10% · worktree op 1% | GC | P1-python-child-snippet | no | 0.0 | sampled | A parked land pre-ships its branch to the venue box and its exit mirrors main,… — The e2e arms drive a real parked land against a local bare box; the process lifecycle is what AC2/AC3/AC4 assert. The… |
| 57 | test_audit_status_reserve_pair.py | 46.7 | other CLI 98% · in-process remainder 1% · in-process copy 1% | C | C1-cli-per-case | partly | 23.4 | sampled | audit status names each tier's reserve pair and is honest when no second door exists — Mint the seed_read receipt directly, or batch arms per engine fixture sharing a session; keep the real `audit status` CLI… |
| 58 | test_t10349_seed_budget_warn.py | 46.7 | in-process remainder 94% · git fixture 5% · worktree op 1% | GC | I3-engine-hot-path | partly | 16.3 | sampled | The seed-growth WARN fires on a grown seed doc and stays silent otherwise, and the… — Cache parsed spec YAML by content in state.load_str/_stage_bundle_specs so the nine stage deliveries and the fold do not… |
| 59 | test_t13333_inert_first_attempt_skip.py | 46.3 | git fixture 70% · in-process remainder 24% · worktree op 5% | GWSTC | G1-git-churn | no | 0.0 | sampled | A first-attempt land whose delta from a venue-green tree is inert skips verify, and… — The git-derived inertness decision, via the real _land_integrate over real git trees, is what is asserted. Most git… |
| 60 | test_spike_mode_hint.py | 45.9 | other CLI 53% · in-process remainder 17% · worktree op 15% · real land 11% | GWLC | C1-cli-per-case | partly | 6.9 | sampled | The report-only spike hint appears on the three work verbs when a spike worktree is… — Share one built consumer fixture for the read-only CLI arms, or copy a prebuilt born consumer, instead of rerunning init… |
| 61 | test_t13291_audit_post_one_pass.py | 45.8 | in-process remainder 47% · other process 40% · git fixture 10% · worktree op 3% | GW | X-subject-inherent | no | 0.0 | sampled | audit post folds each journal segment and card once within its horizon, behaviour… — One-pass, behaviour parity and peak-RSS claims need real audit runs, and the memory arm needs a fresh process per run, so… |
| 62 | test_t10901_cites_joined_id_list.py | 45.5 | in-process remainder 94% · git fixture 5% · worktree op 1% | C | I1-corpus-derivation | yes | 27.3 | sampled | task file refuses a comma-joined --cites value while admitting repeated flags, prose… — Load the cards with yaml.CSafeLoader when available, or read cites/requires from a shared parsed-corpus cache, and keep the… |
| 63 | test_t10637_kernel_tests_are_consumer_independent.py | 45.2 | in-process remainder 99% · git fixture 1% | GTC | I2-repeated-derivation | partly | 11.3 | sampled | no kernel test reads another project's live files, and no dated-fixture time bombs… — Parse each tests/*.py once into a module-level {path: tree} cache and have collect and the date-bomb collectors reuse it. |
| 64 | test_t12301_venue_main_mirror_not_clobber.py | 44.9 | in-process remainder 83% · other process 16% · git fixture 1% | GSC | P2-waiting | partly | 4.5 | sampled | A fast-forward of the box clone's main ref is classified as a mirror, while a… — Lower any remaining leg-script poll knobs (for example VENUE_CORE_SPLIT_POLL_S) to 1 via env, as was already done for… |
| 65 | test_t10597_spec_edit_bypass_family.py | 44.7 | in-process remainder 100% | C | I3-engine-hot-path | partly | 22.4 | sampled | The raw-spec-edit bypass family is cited under one case file and the real discovery… — Fix _stem_family_key in the engine (memoize per stem or remove the quadratic len-comparison loop); the test is unchanged. |
| 66 | test_t0687_stage_worker_sync_reminder.py | 44.6 | in-process remainder 98% · worktree op 2% · git fixture 1% | C | I3-engine-hot-path | yes | 26.8 | sampled | cmd_stage re-delivers the sync-to-land reminder to dispatched workers at the… — Memoise the bundled-spec YAML parse in the engine (mtime-keyed), or stub _stage_bundle_specs in the sandbox, since the… |
| 67 | test_t12080_profile_resolver.py | 44.3 | in-process remainder 100% | GC | I3-engine-hot-path | partly | 15.5 | sampled | The SPEC-0198 growth profile is derived deterministically with overrides, a single… — Run the cap-boundary arms with profile._OPS_READ_BYTE_CAP monkeypatched to a few KB. Keep one assertion on the real 4 MiB… |
| 68 | test_t12641_watch_arming_reachability.py | 43.1 | other process 99% · in-process remainder 1% | - | P1-python-child-snippet | partly | 12.9 | sampled | An arming that cannot reach the Controller emits a loud banner at arm time, with a… — Memoize _run_arm's default arms (redirect=True and redirect=False, no stub) within the file and share the results across… |
| 69 | test_spec0178_rule7_review_and_rule9_share.py | 43.0 | in-process remainder 94% · git fixture 5% | GC | I3-engine-hot-path | partly | 12.9 | sampled | the rule 7 review proposal, the rule 9 share and SPEC-0178 activation behave… — Cache _ownership_chain_break's source reads and regex scans by file content, or hoist graph_build_index into a shared… |
| 70 | test_t12979_scaffold_templates_ship.py | 42.8 | other CLI 79% · worktree op 14% · git fixture 5% · in-process remainder 2% | GWC | C3-slow-verb-is-subject | no | 0.0 | sampled | Scenario and spec scaffold templates ship in a release cut, so scenario new and spec… — The proof is that these real verbs succeed end to end on an installed cut, and fail with the templates removed… |
| 71 | test_t12944_published_graph_index.py | 42.6 | in-process remainder 43% · other process 38% · git fixture 13% · other CLI 5% | GC | C2-corpus-graph-build | partly | 5.1 | sampled | A release published and installed carries graph/index.json so `graph query --kernel`… — The second test ignores its Mirror (_m), so build the Mirror only for the first test. Its publish with an index build is… |
| 72 | test_t11593_key_census_fold_reads_segments.py | 41.2 | nested test file 100% | T | R1-reruns-suite-member | partly | 24.7 | sampled | The spec0161 key census reads archived journal segments, via in-process differentials… — Keep ONE foreign-cwd run of the sibling suite (shared by the files that each re-run it) and drop the rest; the suite run… |
| 73 | test_venue_pinned_leg_merged_base_runner.py | 40.6 | in-process remainder 83% · other process 16% · git fixture 1% | GSC | P2-waiting | no | 0.0 | sampled | The venue's pinned leg runs the merged base's strict runner, fails closed without one,… — The real shipped leg script run end to end is the subject; a stubbed leg could not show which runner the pinned leg called |
| 74 | test_consumer_conformance.py | 40.4 | other CLI 65% · real land 20% · worktree op 13% · in-process remainder 2% | GWLC | C3-slow-verb-is-subject | no | 0.0 | sampled | A synthetic blank -C consumer runs the full methodology lifecycle through the real… — The file is the executable conformance contract: it asserts each real verb works end-to-end for a consumer, so the CLI and… |
| 75 | test_flaky_retry_waits_for_sibling_pool.py | 40.1 | other process 54% · nested test file 44% · in-process remainder 2% | S | P2-waiting | partly | 6.0 | sampled | the isolated retry waits for the sibling leg's pool to drain, bounded, and allows… — Shorten the fixture holder/sleeper durations to the minimum that still keeps the sibling pool live across the retry point. |
| 76 | test_t11128_root_cwd_closure.py | 40.0 | in-process remainder 99% · other process 1% | GTC | I1-corpus-derivation | partly | 14.0 | sampled | Every re-derived root-cwd child-read site in the live tests tree has a recorded… — Get the enumerate_sites(ROOT) result from a shared content-keyed per-run cache, since test_t11120 computes the identical… |
| 77 | test_t13123_t12626_checkout_hermetic.py | 38.9 | nested test file 81% · in-process remainder 10% · git fixture 9% | S | R1-reruns-suite-member | no | 0.0 | sampled | Running three profile test files through the shipped runner in a private clone leaves… — It does not assert the targets are green. It asserts they write nothing into the checkout, which needs the real run in a… |
| 78 | test_ceiling_decisions_on_decisions.py | 38.7 | in-process remainder 88% · git fixture 12% · worktree op 1% | GC | I3-engine-hot-path | partly | 9.7 | sampled | audit --on-decisions admits one bounded past-ceiling pass only when every residual has… — Add a content-keyed YAML parse memo in the audit read path, or share the parsed sandbox corpus across cmd_audit calls. |
| 79 | test_t10116_sentinel_isolation.py | 38.1 | nested test file 87% · in-process remainder 10% · git fixture 3% | G | R1-reruns-suite-member | partly | 15.2 | sampled | Seed helpers refuse the real journal, and the previously leaking test files add no… — Have the suite runner give every file a private YITC_EVENTS_PATH_DEFAULT and assert it stays empty. This probe would then… |
| 80 | test_task_scorecard_view.py | 37.4 | in-process remainder 100% | C | I3-engine-hot-path | partly | 5.6 | sampled | The task-scorecard view is listed, prints its fixed field set for a real closed task,… — Reuse one journal fold for the view's three graph-query calls, or speed up the journal scan inside _view_task_scorecard. |
| 81 | test_t10379_task_test_run_graph_parity.py | 37.2 | in-process remainder 53% · other CLI 31% · in-process copy 14% · nested test file 1% | LSC | C2-corpus-graph-build | partly | 5.6 | sampled | task test --run does the same pre-verify graph rebuild as land, so stale derived views… — Reuse a cached prebuilt index for the temp-copy baseline instead of a fresh graph build child. The two real rebuilds stay. |
| 82 | test_update_ledger.py | 37.0 | other CLI 56% · git fixture 18% · other process 17% · in-process remainder 9% | - | C1-cli-per-case | yes | 18.5 | sampled | update plus the override ledger preserve consumer-owned paths, preserve registered… — Pass the existing _task_closed_rows seam to cmd_work_publish in Mirror.publish (fixed empty rows); generate the three keys… |
| 83 | test_t11442_census_regeneration.py | 36.8 | other process 54% · in-process remainder 46% | - | I2-repeated-derivation | partly | 11.0 | sampled | The journal-reader census generator reproduces its recorded population or refuses… — Compute the live build once in-process and share it between AC1's green check and AC2. Keep the planted-tree CLI runs… |
| 84 | test_t12220_venue_request_keyed_isolation.py | 35.6 | in-process remainder 60% · other process 39% | GSC | P2-waiting | no | 0.0 | sampled | Two overlapping venue requests each keep their own lease and run dir, and the shipped… — The proof is the real concurrency and reaping behaviour of the shipped bash. Waiting on those processes is the observation,… |
| 85 | test_land_2.py | 35.3 | git fixture 35% · other process 23% · real land 18% · in-process remainder 16% | WLSTC | G1-git-churn | partly | 3.5 | sampled | Land control points (token, cwd, dirt, decision guard, e2e) behave correctly through… — Build the base fixture repo once and clone or copy it per case instead of re-running init/add/commit in every case |
| 86 | test_t12232_introducing_branch_names_the_key_3.py | 35.3 | in-process remainder 100% | - | I2-repeated-derivation | partly | 15.9 | sampled | Attributing unnamed keys to the introducing branch leaves the floor gate's governing… — Wrap debtmod._spec0161_inputs in a memoizing wrapper for the test so the identical corpus read happens once and is shared… |
| 87 | test_t12630_preflight_abort_reservation_wait_and_arms.py | 34.9 | in-process remainder 69% · other process 17% · git fixture 13% · worktree op 1% | WT | I2-repeated-derivation | partly | 8.7 | sampled | abort_preflight rows carry reservation_wait_ms as an int and the refused-site set is… — Parse each bin/lib file once per root (keyed by root and file content) and share the trees across _refusal_sites and… |
| 88 | test_t11120_root_cwd_read_tracer.py | 34.7 | in-process remainder 88% · other process 11% | GTC | I1-corpus-derivation | partly | 12.1 | sampled | The root-cwd child-read tracer fails closed and its shipped report covers every… — Share the enumerate_sites(ROOT) result with test_t11128 through a content-keyed per-run cache; strace arms are untouched. |
| 89 | test_t10498_init_pending_scaffold_refresh.py | 34.6 | other CLI 86% · other process 11% · git fixture 3% · in-process remainder 1% | GC | C1-cli-per-case | partly | 5.2 | sampled | init reports a pending scaffold refresh instead of silently rewriting an existing… — Where init only builds a consumer to drift (setup), copy a prebuilt initialised fixture instead of running init again; the… |
| 90 | test_t12250_pinned_leg_excludes_branch_only.py | 33.5 | in-process remainder 82% · other process 17% · git fixture 1% | GSC | P3-external-tool | no | 0.0 | sampled | The shipped box pinned-leg script excludes candidate-added tests and runs both legs… — The real leg script run against real git is the thing proved, and the differential arm needs the real ImportError. |
| 91 | test_session_start_delivers_stage_bundle.py | 32.7 | in-process remainder 68% · other CLI 28% · git fixture 2% · worktree op 2% | GWC | I3-engine-hot-path | partly | 11.4 | sampled | An in-worktree session start delivers the card's stage bundle after its anchor, so the… — Memoize the spec YAML parse (state.load_str) within the run. Keep the real session start, stage and task analyze CLI calls. |
| 92 | test_t12675_land_session_escape.py | 31.7 | other process 63% · in-process remainder 37% | C | P1-python-child-snippet | no | 0.0 | sampled | A non-worker land survives its wrapper's expiry kill (timeout and session kill),… — Surviving a real SIGTERM, session kill or descendant walk is the claim; each leg runs a frozen and a shipped escape for the… |
| 93 | test_t11839_root_cwd_registry_drift.py | 30.7 | in-process remainder 100% | TC | I1-corpus-derivation | partly | 9.2 | sampled | every root-cwd read-set ledger reconciles with the live site corpus (one drift check… — Serve enumerate_sites(ROOT) from a content-keyed per-run cache shared with test_t11128 and test_t11120, which derive the… |
| 94 | test_release_install_exec_bit.py | 29.4 | in-process remainder 68% · git fixture 17% · other process 9% · other CLI 6% | C | I2-repeated-derivation | partly | 11.8 | sampled | release install writes the verified tree's file modes so the installed bin/yitc-v2 is… — Memoize host_literal_violations by cut-content hash, or build one _ExecMirror per file and copy it per arm; install and… |
| 95 | test_pinned_verify_2.py | 29.0 | other process 39% · in-process remainder 22% · nested test file 19% · git fixture 18% | GSTC | R3-fixture-suite-run | no | 0.0 | sampled | The pinned last-green verify leg is stable across repeats, excuses additive layout… — The pinned runner's behaviour on fixture suites is the subject; each assertion reads the runner's own output, so nothing… |
| 96 | test_t0296_work_verb_conformance.py | 28.9 | in-process remainder 100% | C | I2-repeated-derivation | yes | 10.1 | sampled | No work-verb carries a routing payload and every stage-bound verb calls its… — Memoize _module_tree for the default path, and _func_nodes per tree object, at module level. Synthetic trees still use… |
| 97 | test_worktree_new.py | 28.9 | in-process remainder 89% · git fixture 9% · worktree op 2% | GWC | I3-engine-hot-path | partly | 8.7 | sampled | worktree new creates task and work worktrees, rejects bad input, and emits… — Memoize _stage_bundle_specs by SPECS_DIR content or mtime fingerprint, as tests/_read_gate.py already does for its seeder |
| 98 | test_t12151_pinned_first.py | 28.5 | nested test file 55% · in-process remainder 21% · git fixture 21% · worktree op 3% | GWSC | R3-fixture-suite-run | no | 0.0 | sampled | The pinned last-green leg runs first and aborts fast, with both legs still run on… — The ordering and early exit of the verify legs is the subject, so the fixture-suite runs that make the legs execute are the… |
| 99 | test_t12621_deploy_mutual_exclusion.py | 28.4 | other CLI 91% · in-process remainder 8% · git fixture 1% | GWC | C3-slow-verb-is-subject | no | 0.0 | sampled | concurrent deploys on one project serialize and name the holder, while different… — The real deploy CLI's lock and exit contract under real concurrency is the proof. The sleeps create the overlap window it… |
| 100 | test_controller_acting_in_worktree.py | 27.7 | in-process remainder 91% · git fixture 6% · worktree op 3% | GWLC | I3-engine-hot-path | partly | 11.1 | sampled | Controller session start in a worktree with a confirmed-dead foreign holder acts… — Memoise the spec YAML load (state.load_str or _stage_bundle_specs) per run in the test, or fix it in the engine; keep real… |
| 101 | test_t13517_cost_zone_shadow_record.py | 27.4 | UNMEASURED | ? | - | - | 0.0 | static-only | - — - |
| 102 | test_t0861_consumer_session_start_echo.py | 26.9 | other CLI 91% · in-process remainder 8% · git fixture 1% | GWLC | C1-cli-per-case | no | 0.0 | sampled | A consumer's session start echoes the engine handbook paths with a kernel-provided… — The claim is the real CLI's stdout contract for each consumer or engine posture. Calling the renderer in-process would skip… |
| 103 | test_t12570_spike_content_refusal_switch.py | 26.9 | git fixture 75% · in-process remainder 18% · worktree op 7% | GW | G1-git-churn | no | 0.0 | sampled | The spike-content refusal arm aborts land on every identity row when the switch is ON… — Each row x flag x switch cell is a real land whose outcome is asserted; the file already dedups cells, so the git churn is… |
| 104 | test_t12165_profile_snapshot_scaffold_delivery.py | 26.6 | other process 64% · other CLI 29% · in-process remainder 7% · git fixture 1% | GC | P3-external-tool | no | 0.0 | sampled | The profile-snapshot scaffold is delivered to a byte-copied consumer by init, and the… — The claim is that the real delivered producer and the real init work on the consumer layout, so running them is the proof. |
| 105 | test_t11890_capture_content_accessor.py | 26.5 | other CLI 99% · in-process remainder 1% | C | C1-cli-per-case | no | 0.0 | sampled | Capture content has one reader-owned accessor, and legacy-key captures are still… — AC3 asserts the real CLI accepted the row (exit 0) and that it exists in the journal; calling the validator in-process… |
| 106 | test_t11232_journal_settle.py | 26.2 | in-process remainder 74% · git fixture 23% · worktree op 2% | GWC | X-subject-inherent | no | 0.0 | sampled | a journal-committing verb settles its own append so the next git merge succeeds, with… — The cost is tiny git fixtures with a real merge, which is the proof. Nothing identifiable to substitute. |
| 107 | test_t12260_stage6_overlap_deadline.py | 26.0 | other process 63% · in-process remainder 20% · nested test file 17% | GSC | P2-waiting | partly | 3.9 | sampled | A Stage-6 venue leg is not killed for time a foreign land held the box, while the… — Shrink the fake-run seconds and bounds proportionally in the fixture legs, keeping the bound/wall ratios the arms depend on |
| 108 | test_t9442_project_dimension_floor.py | 25.9 | other CLI 87% · in-process copy 10% · in-process remainder 3% | C | C2-corpus-graph-build | partly | 3.9 | sampled | The project-dimension floor trigger is registered and rendered, and `graph build`… — Build #1 only supplies the first render and the seeded journal. Obtain it from a content-keyed shared sandbox build; keep… |
| 109 | test_live_index_not_rewritten.py | 25.7 | other CLI 84% · in-process copy 12% · in-process remainder 4% | SC | C2-corpus-graph-build | no | 0.0 | sampled | A real graph build under the YITC_REPO_ROOT override and the shared build sandbox… — The claim is that a real graph build respects the redirect and the helper builds in a private copy, so the real build is… |
| 110 | test_t12259_venue_class_admission_3.py | 25.6 | other process 75% · in-process remainder 25% | - | P2-waiting | no | 0.0 | sampled | A degraded venue load reading is refused reversibly and admitted only once the load… — The file states every wait is sized to one poll cycle of the shipped loop and going below that is forbidden, so the wait is… |
| 111 | test_bootstrap_order_doc.py | 25.4 | git fixture 94% · in-process remainder 6% | C | I2-repeated-derivation | partly | 11.4 | sampled | The bootstrap-order doc travels in the kernel-realm release cut, its bytes carry every… — Memoize _throwaway_commit and _cut(sha, resolve=None) at module level so the throwaway tree and its cut are built once… |
| 112 | test_t9457_rebaseline_staleness_scope.py | 25.3 | git fixture 61% · in-process remainder 26% · nested test file 7% · worktree op 5% | GWC | G1-git-churn | partly | 2.5 | sampled | the rebaseline audit-staleness check scopes to the branch's net footprint, so… — Share one prebuilt base repo via cp -r per case instead of re-init and commit per test, and batch rev-parse calls. |
| 113 | test_box_leg_post_run_s.py | 25.0 | other process 57% · in-process remainder 42% · git fixture 1% | S | P2-waiting | partly | 2.5 | sampled | Every box leg records post_run_s, the runner work outside verify_wall_ms, and it… — Possibly shorten RUN_S/EXTRA_S slightly, keeping the margin between EXTRA and EXTRA+RUN*0.5 clear of scheduling noise. |
| 114 | test_t0284_stage_axis_conformance.py | 25.0 | in-process remainder 83% · git fixture 17% | C | C2-corpus-graph-build | no | 0.0 | sampled | The stage-axis binding vocabulary is valid and graph conformance goes GREEN or RED… — Each conformance run takes a different spec set and its exit code is the assertion. The real-corpus index is already built… |
| 115 | test_t10246_session_start_worktree_stamp_adoption.py | 25.0 | in-process remainder 55% · other CLI 36% · git fixture 4% · worktree op 4% | GWC | I2-repeated-derivation | partly | 6.2 | sampled | session start in a stamped worktree emits its anchor and seed receipt under one… — Stub or share the debt-echo derivation in the two in-process drives; keep the real-subprocess e2e P2 arm unchanged. |
| 116 | test_t10332_unchanged_head_audit_post.py | 24.8 | in-process remainder 92% · git fixture 6% · worktree op 2% | C | I3-engine-hot-path | partly | 8.7 | sampled | A same-commit audit-post cannot bank GREEN after a prior RED or YELLOW, but… — Memoize state.load_str (YAML text to data) across the 25 audit runs, in the test harness or the engine. |
| 117 | test_corpus_read_bounds.py | 24.7 | in-process remainder 93% · git fixture 7% | - | X-subject-inherent | no | 0.0 | sampled | Tests needing only a slice of specs/ or tasks/ do not read the whole corpus, enforced… — No single hot call site is evident; the pinned-corpus slice and git checks are what the bound rules assert. |
| 118 | test_t11897_root_fix_landed_boundary.py | 23.8 | in-process remainder 100% | - | I1-corpus-derivation | partly | 8.3 | sampled | a root_fix_landed case resolves a currency boundary later than its captures, so false… — In the test's own scan, skip json.loads unless the line contains a target fingerprint; optionally share one journal pass… |
| 119 | test_t11631_nightly_filesystem_headroom.py | 23.6 | other CLI 87% · in-process remainder 13% | GC | C3-slow-verb-is-subject | no | 0.0 | sampled | The nightly reports filesystem headroom (free bytes, percent) on its line and payload… — AC1 asserts the real CLI nightly prints the filesystem-headroom line and rides the payload; that is the slow verb itself. |
| 120 | test_t9577_bare_invocation_foreign_corpus_guard.py | 23.5 | other CLI 52% · in-process remainder 37% · git fixture 7% · other process 3% | GC | C1-cli-per-case | partly | 2.4 | sampled | A bare yitc-v2 call from a foreign corpus is refused and leaves the kernel journal… — The two no-refusal arms that use `graph query SPEC-0078` could share one run or use a cheaper read-only verb. The refusal… |
| 121 | test_t11592_known_broken_fold_reads_segments.py | 23.4 | nested test file 99% · in-process remainder 1% | T | R1-reruns-suite-member | partly | 14.0 | sampled | The known-broken-on-main fold reads archived journal segments, via in-process… — Keep ONE foreign-cwd run of the sibling suite (shared by the files that each re-run it) and drop the rest; the suite run… |
| 122 | test_argv_prose_seam.py | 23.3 | in-process remainder 91% · in-process copy 4% · git fixture 4% · worktree op 1% | GWC | I2-repeated-derivation | yes | 8.2 | sampled | The argv prose seam refuses a backtick in guarded prose flags before parsing, over… — Copy the specs once per file or key the _read_gate bundle memo by spec content so each sandbox hits the cache |
| 123 | test_t0317_plan_lifecycle_spec.py | 23.3 | other CLI 75% · in-process remainder 14% · in-process copy 10% | C | C2-corpus-graph-build | partly | 7.0 | sampled | SPEC-0034 plan lifecycle is authored correctly and wired to the plan-stage-entry… — Reuse a content-keyed shared temp index and corpus copy from _graph_build_sandbox instead of rebuilding per file. Keep… |
| 124 | test_killed_batch_recovery.py | 23.2 | nested test file 92% · git fixture 5% · in-process remainder 2% | GW | R1-reruns-suite-member | partly | 13.9 | sampled | worktree recover-land --batch-residue restores a killed land's half-formed batch,… — Keep ONE foreign-cwd run of the sibling suite (shared by the files that each re-run it) and drop the rest; the suite run… |
| 125 | test_t11578_watch_lifetime_decoupled.py | 23.2 | nested test file 70% · other process 28% · in-process remainder 2% | - | R1-reruns-suite-member | yes | 15.1 | sampled | A dispatch --watch watcher survives its launching shell's process group, and the… — Drop the subprocess run of the two owning suites; the suite run already executes both files. |
| 126 | test_spec0161_payload_key_refresh.py | 23.0 | in-process remainder 100% | C | I1-corpus-derivation | partly | 9.2 | sampled | The SPEC-0161 record names every governing payload-key pair, and excising the eight… — Take the corpus input from a shared content-keyed or per-run journal-scan cache that other readers (debt, event catalog)… |
| 127 | test_t12150_queued_land_branch_freshness_2.py | 23.0 | other process 84% · git fixture 13% · in-process remainder 2% · worktree op 1% | - | P1-python-child-snippet | no | 0.0 | sampled | A queued land is held or refused by branch freshness against a live reservation holder… — A live separate process holding the real reservation is what the queued-land arms are about; an in-process holder would not… |
| 128 | test_deploy_convergence.py | 22.9 | other CLI 90% · git fixture 6% · in-process remainder 3% · in-process copy 1% | GC | C3-slow-verb-is-subject | no | 0.0 | sampled | A service left on old code is caught by the real deploy convergence check, and… — The deploy verb's real behaviour and exit and journal contract is the subject, and each arm needs its own fixture deploy. |
| 129 | test_t11591_gate_override_fold_reads_segments.py | 22.9 | nested test file 99% · in-process remainder 1% | T | R1-reruns-suite-member | partly | 13.7 | sampled | The security-gate-override fold reads every archive segment in its 30-day window, with… — Keep ONE foreign-cwd run of the sibling suite (shared by the files that each re-run it) and drop the rest; the suite run… |
| 130 | test_c2_owner_approved_backup.py | 22.7 | other CLI 96% · git fixture 3% · in-process remainder 1% | GC | C1-cli-per-case | partly | 4.5 | sampled | an owner-approved C2 deploy takes the declared pre-deploy dump, refuses on a broken or… — Drive the non-process-lifecycle refusal and message cases through cmd_deploy in-process. Keep the hang-cap and child-kill… |
| 131 | test_t13459_audit_seam_one_pass.py | 22.6 | in-process remainder 53% · other process 34% · git fixture 11% · worktree op 2% | L | X-subject-inherent | no | 0.0 | sampled | Audit seam evidence reads fold each journal segment at most once across consult, pre… — Each run is a distinct mode (scoped, legacy, no-renew, with and without mid-run change) and observes real segment-open… |
| 132 | test_raw_journal_reader_sweep.py | 22.5 | in-process remainder 100% | TC | I1-corpus-derivation | partly | 5.6 | sampled | Every raw or single-file-fold journal reader in kernel source and repo-rooted tests is… — Back the memo with a per-run or on-disk cache keyed on source text and detector version, so the AST scan of unchanged files… |
| 133 | test_worker_synchronous_land_guard.py | 22.5 | in-process remainder 60% · other process 40% | LC | P2-waiting | partly | 3.4 | sampled | A dispatched worker's detached or backgrounded land is refused or killed, and the… — Shorten the watchdog poll interval and window through the test-only knob the watchdog exposes, if any, or poll on a file or… |
| 134 | test_t11919_delivery_proof_reads_segments.py | 22.4 | nested test file 99% · in-process remainder 1% | C | R1-reruns-suite-member | partly | 13.4 | sampled | The claim-landed delivery-proof reader reads archive segments, and the reader census… — Keep ONE foreign-cwd run of the sibling suite (shared by the files that each re-run it) and drop the rest; the suite run… |
| 135 | test_nightly_corpus_content_check.py | 22.0 | other CLI 52% · in-process remainder 37% · in-process copy 11% | - | C2-corpus-graph-build | partly | 6.6 | sampled | The nightly grades corpus staleness by content, so card status edits are ok while… — Take the sandbox copy and built index from a shared content-keyed cache so the real graph build and copytree are paid once… |
| 136 | test_t12938_born_recommended_defaults.py | 22.0 | in-process remainder 91% · other CLI 7% · in-process copy 1% | GC | I3-engine-hot-path | partly | 6.6 | sampled | every mandatory init question carries a recommended default that init only displays,… — Use yaml.CSafeLoader and CSafeDumper where available, or load the live spec corpus once and share it across the AC tests. |
| 137 | test_t13286_tripwire_reader_wall.py | 22.0 | nested test file 97% · in-process remainder 2% · other process 1% | G | R1-reruns-suite-member | no | 0.0 | sampled | The tripwire's reader test_t12259 runs green inside half the tripwire budget, and its… — The claim is the reader's wall under the tripwire's own hermetic env against a budget, which a normal suite run does not… |
| 138 | test_t12592_custody_sha_unambiguous.py | 21.9 | in-process remainder 96% · git fixture 4% | GW | I2-repeated-derivation | partly | 8.8 | sampled | A recorded custody sha names exactly one commit, and every custody writer records… — Parse bin/lib once per file and reuse the trees; each bypass mutation re-parses only its one mutated file. |
| 139 | test_t11444_segment_aware_readers.py | 21.7 | in-process remainder 99% · git fixture 1% | GWC | I1-corpus-derivation | partly | 3.3 | sampled | Every journal reader is segment-aware and byte-equal to the pre-change path over a… — Reuse a content-keyed per-run census build for the live population; keep the reader-equality runs. |
| 140 | test_t12634_run_scoped_resource_rule.py | 21.7 | other CLI 72% · in-process remainder 16% · in-process copy 12% | C | C2-corpus-graph-build | partly | 2.2 | sampled | The run-scoped resource rule is delivered through SPEC-0041 section 1c with a… — Take the binding report from a shared per-run graph build artifact. Alternatively copy only the spec and decision files the… |
| 141 | test_t12991_venue_publish_reservation_precedence.py | 21.6 | other process 99% · in-process remainder 1% | L | P1-python-child-snippet | no | 0.0 | sampled | A waiting venue publish takes the land reservation at the next release, with a… — Precedence among real separate processes on a real flock is the claim; the poll period is part of the differential design. |
| 142 | test_t0295_one_source_delivery.py | 21.3 | in-process remainder 92% · git fixture 8% | C | I2-repeated-derivation | partly | 6.4 | sampled | the one-source delivery invariant helpers and cmd_graph_conformance verdicts hold, and… — Bound or memoise the report-only _test_building_warnings in the sandbox runs, as did for the journal sweep.… |
| 143 | test_t12259_venue_class_admission.py | 21.2 | other process 98% · in-process remainder 2% | GLC | P2-waiting | no | 0.0 | sampled | The shipped venue-lease prologue admits or waits per request class (Stage-6 vs land)… — The shipped shell text's own sleep/poll admission loop is what is exercised. Shortening the sleep would change the text… |
| 144 | test_t9373_ui_tests_sections_carrier.py | 20.6 | other CLI 96% · git fixture 2% · in-process remainder 2% | GC | C1-cli-per-case | partly | 7.2 | sampled | `init` seeds ui:/tests: sections declare-or-waive and fail-closed rejects malformed… — The first `init` only seeds a repo whose carrier is then overwritten. Seed once, then copytree the seeded consumer per… |
| 145 | test_t12259_venue_class_admission_2.py | 20.5 | other process 99% · in-process remainder 1% | L | P2-waiting | no | 0.0 | sampled | The shipped venue prologue counts a legacy classless lease in both pools and refuses… — The proof is the shipped bash wait and admit behaviour, whose wait bound is one poll cycle. Going below it is explicitly… |
| 146 | test_close_warn_consumer_land_truth.py | 20.4 | other CLI 67% · real land 17% · worktree op 14% · in-process remainder 1% | WLC | C3-slow-verb-is-subject | partly | 2.0 | sampled | A consumer task close warns without promising a land abort, through one real -C… — Replace the 12 read-gate-seeding graph query children (3.0s) with in-process seeding of the read receipts, as other tests… |
| 147 | test_t11153_scheduled_maintenance.py | 20.4 | in-process remainder 51% · other process 42% · git fixture 7% | G | P3-external-tool | no | 0.0 | sampled | The shipped scheduled-maintenance script beats auto-gc, serializes against itself and… — The shipped bash script's real behaviour (gc efficacy, flock deferral, object survival) is exactly what the assertions are… |
| 148 | test_release_view_no_dead_paths.py | 20.3 | in-process remainder 84% · git fixture 15% | C | I1-corpus-derivation | partly | 10.2 | sampled | the published release seed cites no path that the id-stripping release view turned… — Take the published tree from a per-run content-keyed cache shared with test_release_spec_closure instead of recomputing the… |
| 149 | test_carve_selection.py | 20.2 | other CLI 86% · worktree op 6% · git fixture 5% · in-process remainder 3% | GWTC | C1-cli-per-case | no | 0.0 | sampled | graph query --carve-out selection clashes, orders and waits correctly, and is… — The CLI-level read-only trace (git status clean after a real run) and the concurrent isolation are the claims, so the real… |
| 150 | test_t12626_profile_read_only_admission.py | 20.2 | other CLI 71% · in-process remainder 20% · other process 8% · git fixture 1% | GSC | C1-cli-per-case | no | 0.0 | sampled | `profile` is admitted as a pure read under --read-only and writes nothing into the… — Admission under --read-only and the no-write guarantee are properties of the real CLI path (gate plus child process), so… |
| 151 | test_land_3.py | 20.1 | git fixture 31% · real land 27% · other process 25% · in-process remainder 10% | WLC | G1-git-churn | no | 0.0 | sampled | A shard of the land control-point tests: real lands, the abort paths and… — The real land behaviour on real git worktrees is the proof, and the shard was already balanced with no assertion changes. |
| 152 | test_t12451_adopt_reaps_dead_holder_children.py | 20.1 | in-process remainder 50% · other process 48% · git fixture 2% | - | P3-external-tool | yes | 8.0 | sampled | worktree adopt --confirm-dead reaps a dead holder's lingering children like park does,… — Inject _docker_cwd_holders=lambda p, **kw: ([], None) into cmd_worktree_adopt, as the sibling t12375 arms already do for… |
| 153 | test_t13525_engine_pinned_policy.py | 19.9 | in-process remainder 50% · other CLI 35% · git fixture 12% · nested test file 2% | GC | I3-engine-hot-path | partly | 3.0 | sampled | The engine's pinned last-green switch is read from the base tree, validated, and the… — Cut the repeated YAML loads in state.load_path inside cmd_nightly's contract checks (engine-side), or reuse one fixture… |
| 154 | test_t12966_published_cite_fixpoint.py | 19.8 | in-process remainder 86% · git fixture 14% | - | I1-corpus-derivation | partly | 5.9 | sampled | the stripped published cut of the current tree names no SPEC id the release lacks,… — Share the published tree via a content-keyed per-run cache with test_release_spec_closure. Skip yaml re-dump when a spec… |
| 155 | test_deploy_stand_role_advisory.py | 19.5 | other process 92% · git fixture 6% · in-process remainder 2% | GC | C1-cli-per-case | partly | 3.9 | sampled | The stand role feeds exactly two advisory deploy lines, with output and I/O identical… — Batch the twin comparisons so one wrapper process runs several cases and emits per-case results, keeping the audit-hook I/O… |
| 156 | test_t12150_queued_land_branch_freshness.py | 19.3 | other process 84% · git fixture 12% · in-process remainder 3% · worktree op 1% | GWC | P2-waiting | no | 0.0 | sampled | A queued land keeps its branch fresh by pre-merging main during the reservation wait,… — The wait is the observed queued tick in a real land against a real holder process. Most waits are already polled,… |
| 157 | test_task_verbs.py | 19.3 | UNMEASURED (rc 6) | C | I3-engine-hot-path | no | 0.0 | static-only | The task pick, execute and test verbs and the claim behave (state, events… — No measurable repeated derivation is identifiable without a profile, so no substitution is claimed. |
| 158 | test_t12382_plan_gate_decisions.py | 19.0 | in-process remainder 95% · git fixture 5% | - | C2-corpus-graph-build | partly | 3.8 | sampled | The plan-gate ceiling-decision route, bounded on-decisions pass and retirements work,… — Share the real-corpus conformance derivation between the planted-probe run and the clean run; only the patched probe… |
| 159 | test_t9532_worktree_sweep_2.py | 19.0 | other process 70% · in-process remainder 30% | - | P1-python-child-snippet | no | 0.0 | sampled | The worktree sweep reaps sandbox and orphan-resident dirs and its process-floor… — The sweep decides based on really running processes and held dirs, so the real holder processes are the subject. Faking… |
| 160 | test_spec0178_rule5_automatic_restoration.py | 18.9 | in-process remainder 92% · worktree op 4% · git fixture 4% | GC | I3-engine-hot-path | partly | 7.6 | sampled | the audit-post exemption restores automatically after K attributed defects in the… — Memoise state.load_str by content hash, or stage the bundled spec set once per file instead of per sandbox. CSafeLoader is… |
| 161 | test_t10128_admission_heartbeat.py | 18.8 | real land 93% · in-process remainder 7% | GWLC | L1-real-land | no | 0.0 | sampled | A land blocked on the verify-admission slot emits a heartbeat and is recognised alive,… — The two-lands-serialising and free-slot-pays-nothing claims are about real lands contending on the real admission gate. |
| 162 | test_t13131_venue_tag_push_not_clobber.py | 18.8 | in-process remainder 87% · other process 12% · git fixture 1% | - | P2-waiting | no | 0.0 | sampled | A tag pushed or moved mid-run is not reported as venue-refs-clobbered, while a moved… — The shipped leg script and the fake box are what the clobber classification is asserted on. The source does not show a… |
| 163 | test_remote_leg_runner_exception_not_green.py | 18.7 | in-process remainder 86% · other process 13% · git fixture 1% | GSC | P3-external-tool | no | 0.0 | sampled | A remote leg whose runner raised is classed as an indeterminate venue-fault and never… — The end-to-end arm is the test of the real leg template wrapping a raising runner; the unit arm already covers the… |
| 164 | test_t9799_land_bookkeeping_commit.py | 18.7 | git fixture 56% · in-process remainder 40% · worktree op 4% | GWS | G1-git-churn | no | 0.0 | sampled | An aborted land leaves the branch at its entry sha and loses no journal rows, via the… — The claim is about real git branch topology and sha identity after a real abort path, so the git work is the proof. |
| 165 | test_t13432_venue_stage6_bound.py | 18.4 | other process 99% · in-process remainder 1% | - | P2-waiting | no | 0.0 | sampled | The Stage-6 venue bound is derived from cores and suite width, and waits are journaled… — The real admission prologue running concurrently, with one process waiting, is exactly what is asserted; shortening the… |
| 166 | test_land_reservation_park_bound.py | 18.2 | other process 97% · git fixture 2% · in-process remainder 1% | - | P2-waiting | no | 0.0 | sampled | the land-reservation park bound serves a 4-deep queue yet stays finite, by waiting… — The elapsed wait against the park bound is the thing under test. Shrinking the margin would weaken the finite-bound… |
| 167 | test_t13274_land_tail_dirt_superseded_member.py | 18.2 | other process 70% · git fixture 17% · in-process remainder 9% · nested test file 3% | GWST | P2-waiting | partly | 1.8 | sampled | A land-tail carrier in flight on the shared main does not make a concurrent land or… — Use the existing fake clock/_sleep seams in the remaining real-time marker arms, if any |
| 168 | test_audit_status_hint.py | 17.9 | other CLI 87% · in-process remainder 12% | GC | C3-slow-verb-is-subject | no | 0.0 | sampled | `session start` (engine and -C consumer) prints the external-auditor hint only when no… — The file proves the wiring of the hint into both real session-start paths (audit-pre finding 1) and against a mutant… |
| 169 | test_t13415_queue_jump_waits_for_land_reservation.py | 17.9 | other process 95% · git fixture 3% · in-process remainder 1% | GC | P1-python-child-snippet | no | 0.0 | sampled | A main-route queue-jump mark takes the land reservation before writing, so no land is… — The claim is real cross-process reservation ordering, which an in-process stand-in cannot observe. The differentials rely… |
| 170 | test_t0263_query_only.py | 17.8 | in-process remainder 69% · git fixture 31% | C | C2-corpus-graph-build | partly | 4.5 | sampled | The real spec corpus has no dangling specs and the build door still flags a new… — Take the real-corpus index from a shared content-keyed per-run cache; keep the sandbox build with the planted intruder spec |
| 171 | test_t10270_cadence_declare_type.py | 17.7 | in-process remainder 100% | - | I2-repeated-derivation | yes | 12.4 | sampled | The security_audit concern declares a string cadence and no mapping-shaped cadence… — Compute the real-corpus hits once. For the three planted/hidden/ok teeth probes, run the line scan over only the injected… |
| 172 | test_t10438_consumer_tests_sweep_delegation.py | 17.7 | real land 56% · other process 28% · in-process remainder 13% · nested test file 2% | GWLSC | L1-real-land | no | 0.0 | sampled | a declared verify layer covering tests/ delegates the bare sweep, with the same… — The land verdict on delegated and non-delegated fixtures is the subject. Only a real land exercises the routing and the… |
| 173 | test_t12757_layer_overlap_ratio.py | 17.7 | real land 80% · in-process remainder 20% | GWLC | L1-real-land | no | 0.0 | sampled | A real land with independent_layers records layer_overlap_ratio and prints one… — The real-land arms are declared the primary evidence so a correct helper plus a formatting test cannot pass; the cost is… |
| 174 | test_engine_code_host_path_guard.py | 17.6 | in-process remainder 98% · other process 2% | C | I2-repeated-derivation | partly | 3.5 | sampled | No engine module under bin/** and no kernel YAML holds a host absolute path in a… — Parse each bin module once and share the tree between hard_scan, soft_scan and the soft-arm test; walk it once, collecting… |
| 175 | test_land.py | 17.6 | git fixture 49% · in-process remainder 25% · other process 19% · worktree op 5% | GWC | G1-git-churn | no | 0.0 | sampled | The land control-point on real git worktrees: happy fast-forward, no-partial-land on… — The assertions are about real land outcomes on real worktrees, so the git operations are the proof. |
| 176 | test_t0530_handbook_prose_drift.py | 17.6 | in-process remainder 96% · git fixture 3% | C | C2-corpus-graph-build | partly | 3.5 | sampled | cmd_graph_conformance goes RED on handbook verb or mirror drift and is GREEN on the… — Memoize the _read_yaml/load_path file reads across the three conformance runs. The monkeypatched RED arms and the GREEN arm… |

# 3. Where the sampled files' recorded wall goes
sampled 174 of 176 · recorded wall of the sampled files 7517.0 s
real land 93.0 s 1.2%
nested suite 0.0 s 0.0%
nested test file 903.1 s 12.0%
worktree op 109.3 s 1.5%
other CLI 866.9 s 11.5%
git fixture 422.6 s 5.6%
other process 876.0 s 11.7%
in-process copy 24.3 s 0.3%
in-process remainder 4221.7 s 56.2%
cross-check — sample wall / recorded land wall per file: p10 0.47 · median 0.58 · p90 0.97
UNMEASURED (no attribution claimed): test_t13517_cost_zone_shadow_record.py, test_task_verbs.py

# 4. Groups by cause (sampled files with a recorded disposition)
| cause | files | recorded wall s | expected saving s | what it is |
|---|---:|---:|---:|---|
| I1-corpus-derivation | 26 | 1479.9 | 587.8 | an in-process derivation over the whole real corpus, recomputed in every file that needs its value |
| I3-engine-hot-path | 24 | 1119.3 | 400.5 | an engine helper that is slow on real data (repeated YAML loads of the same specs, a quadratic helper) |
| I2-repeated-derivation | 21 | 1112.0 | 380.8 | the same expensive in-process derivation recomputed several times inside one file |
| R1-reruns-suite-member | 12 | 545.3 | 255.6 | re-runs another suite member as a child process, although the same suite run already runs it |
| C2-corpus-graph-build | 14 | 433.7 | 97.1 | graph build / conformance / query over the real corpus, repeated per file or per case |
| C1-cli-per-case | 13 | 416.0 | 86.3 | one CLI child per case; setup-only calls (seeding init, receipt-minting session start) can be shared or copied |
| P3-external-tool | 6 | 174.8 | 41.3 | docker / ssh / bash scripts; the removable part is a default docker probe the test does not assert on |
| P2-waiting | 17 | 515.4 | 28.6 | wall spent waiting: sleeps, poll cycles, timeouts under test |
| R3-fixture-suite-run | 4 | 189.4 | 22.6 | runs the verify runner over a generated fixture tests dir — the runner is the subject |
| C3-slow-verb-is-subject | 9 | 335.2 | 17.4 | a few inherently slow CLI verbs whose real behaviour is the subject |
| P1-python-child-snippet | 8 | 275.7 | 12.9 | python -c children that import the engine (lock holders, measurement children) |
| R2-self-child-harness | 3 | 261.8 | 8.9 | re-executes itself in a child mode per case (per-process memory / one-pass probes) |
| G1-git-churn | 7 | 190.2 | 6.1 | hundreds to thousands of git children building or inspecting fixture repos |
| L1-real-land | 3 | 54.2 | 0.0 | a real land child — the land verdict is the subject |
| X-subject-inherent | 8 | 433.4 | 0.0 | the cost is the proof |
summed expected saving 1945.7 s of 13764.8 s aggregate file-seconds = 14.1%

# 5. The git-fixture group (static marker G over ALL files)
files 768 · aggregate 6499.9 s = 47.2% of all · mean 8.5 s · median 3.5 s
sampled members 83 · their expected saving 571.8 s · group mean after the cuts 7.7 s per file (unsampled members carried at zero saving)
to reach a 4 s mean the group must shed 3427.9 s; the claimed saving covers 17% of that

# 6. Schedule model — aggregate file-seconds versus leg wall
workers 48 · serialized tail files 11
before: aggregate 13764.8 s · modelled leg wall 438.4 s · floor 438.3 s · longest file 199.1 s · tail 154.8 s
after : aggregate 11819.1 s · modelled leg wall 383.5 s · floor 383.4 s · longest file 149.3 s · tail 140.1 s
aggregate falls 14.1% · modelled leg wall falls 12.5%

## §4 — What the columns say

- **The starting hypothesis is refuted.** The 2026-10-04 text read had worktrees at 41 % and a real
  land at 27 % of the git-fixture group. Measured on the heavy files: 1.5 % and 1.2 %. Files mention
  those words far more than they pay for them.
- **In-process time is three different things** (the profile pass): a whole-corpus derivation
  recomputed in every file that needs its value — the selection coverage map alone costs 20–55 s in
  each of some fifteen files (`I1`); the same derivation repeated inside one file (`I2`); and engine
  helpers slow on real data — the same spec YAML parsed tens of thousands of times per file (`I3`).
  The third is not a test problem: the real verbs pay it too.
- **Twelve files re-run other suite members** as child processes; ten of them carry a removable share — they assert only that the
  member is green, which the same suite run already proves (`R1`).
- **Most child-process cost is the proof.** Lock holders, real lands, shipped bash under test,
  poll-cycle waits: 58 of the 175 judged files carry no removable share at all.
- **The recorded table lags.** `tests/verify-durations.json` is a 5-land median with a write
  threshold, so it still showed 13294 s when this was measured; the per-land rows are the fresh source.
  Single-leg lands did not make files cheaper (13.8k s aggregate) — they made the leg shorter.

## §5 — The proposed cut

One followup per group, each naming its files, its one cause and its expected saving:

| cause | files | expected saving s | followup |
|---|---:|---:|---|
| I1-corpus-derivation | 26 | 587.8 | `fu_058acc949384` |
| I3-engine-hot-path | 23 | 400.5 | `fu_83a583a4e5f8` |
| I2-repeated-derivation | 21 | 380.8 | `fu_54839bd6fbb5` |
| R1-reruns-suite-member | 10 | 255.6 | `fu_743b567bc071` |
| C2-corpus-graph-build | 12 | 97.1 | `fu_389fc69d291e` |
| C1-cli-per-case | 9 | 86.3 | `fu_379c8b9b3603` |
| P3-external-tool | 2 | 41.3 | `fu_ccf294fd0f51` |
| P2-waiting | 7 | 28.6 | `fu_6e1913294c93` |
| R3-fixture-suite-run | 1 | 22.6 | `fu_579fccdcf654` |
| C3-slow-verb-is-subject | 2 | 17.4 | `fu_49c6b2ae7e9a` |
| P1-python-child-snippet | 1 | 12.9 | `fu_7e261a3b7299` |
| R2-self-child-harness | 1 | 8.9 | `fu_8066154b09aa` |
| G1-git-churn | 2 | 6.1 | `fu_ecb2fc47c4f0` |

**Sum of the thirteen groups: 1946 s of 13765 s aggregate file-seconds = 14.1 %** — every saving
counted anywhere in this reading (the §3 table, the group sums, the schedule model) belongs to one of
these followups; no cut is claimed outside them. The first eight carry 1878 s (13.6 %); the last five
are single-cause residues of 68 s together, captured so the sum has no unowned part. Of the 117 files
with a removable share, the reading is high-confidence for 10, medium for 42, low for 65 — the sum is
an estimate, not a promise.

## §6 — The owner's target

**«The git-fixture group from 8 s to about 4 s per file» — not reachable by test cuts.** The group
(768 files that create a git repository, 6500 s, 47 % of all test work) averages 8.5 s per file with
a median of 3.5 s. Reaching a 4 s mean means shedding 3428 s; the cuts found cover 572 s — 17 % of
that — and take the mean to 7.7 s. The reason is measured: the group's weight sits in its heavy
members, and their time is not the fixture. Git commands are 5.6 % of the heavy files' wall.

**«The suite at about half its time» — not reachable by test cuts; about −12 % is.**

| | aggregate file-seconds | modelled leg wall |
|---|---:|---:|
| today (three-land median) | 13765 s | 438 s |
| after every cut in §3 | 11819 s (−14.1 %) | 384 s (−12.5 %) |
| today, with the 11 tail files run in the pool | 13765 s | 287 s (−35 %) |
| both | 11819 s | 246 s (−44 %) |

The leg is the pool (work ÷ 48 workers, never less than the longest file — 199 s today) plus **155 s
of serialized tail: eleven files run one at a time are 35 % of the leg**. That is a scheduling
question, not a test-cost one, and it is the sibling followup `fu_5bc5d0a56c0c`; the two rows that
pool the tail are model arithmetic over recorded walls, not a claim that those files may safely
leave the tail. Honest reading: half is in sight only by combining both, and the larger half of the
gain is the tail.

## §7 — Bounds

- **Not attributed:** the in-process remainder is one class to the instrument — imports, engine calls
  and assertions are not separated by it. The split in §4 comes from cProfile on 94 files and is a
  reading aid, not a column.
- **Not measured at all:** `test_t13517_cost_zone_shadow_record.py` (landed during the study, absent
  from the sampled checkout) and `test_task_verbs.py` (exits 6 under the collector).
- **Not examined:** the 1908 lighter files — 46 % of test work. Shared-cache and engine-side remedies
  (`I1`, `I3`, `C2`) would reach them too; that gain is real and is not in any sum here.
- **Semantic overlap between tests** — different tests proving the same behaviour — is out of reach
  of this method and is not estimated.
- **Three lands, one afternoon.** Per-file walls moved ±25 % between them; the median absorbs one
  outlier, not a trend.
- **The model holds each file's wall fixed.** Less work means less contention on the venue, which it
  cannot; the after-cut leg wall is an estimate.
- **Removable shares are judgements** made from the source with the measurement in hand, by analysis
  agents, with the highest-saving `R1` claims re-checked by hand (which lowered five of them: the
  child is run from a foreign working directory, so one shared run must stay).
- **Children the shim cannot see:** a process started by `os.fork`/`os.exec` without `subprocess`, or
  never waited for, has no row; its time falls into the remainder.

## §8 — Re-deriving

```
python3 <workshop-instruments-dir>/attribute-test-file-wall-.py --top 176
```

Read-only over the three recorded files and the test sources: no journal read, no process started,
nothing written. `extract --since --until ` regenerates
input A from the journal; `sample` regenerates input B and must be launched with the session
carriers removed, which it enforces. Probe: `tests/test_t13535_attribute_test_file_wall.py`.
