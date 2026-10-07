---
name: delta-only-recheck-observation
class: observation
binding: []
sourced_from: " — a read-only analysis of this repository's plan-gate audit history (2026-07-08 → 2026-10-05), made 2026-10-06 from the journal and the committed audit records; saved verbatim except for the scratch-path and plan-name notes in §Data and method"
applies_to: "deciding WHAT a gate re-check pass reads (the whole subject or only the change) — the evidence behind methodology Lesson 12 (patterns/methodology-lessons.md). Part 1 of 5: the method, coverage, aggregates, examples, caveats and conclusion; the per-finding table is in patterns/delta-only-recheck-observation-findings-1.md, patterns/delta-only-recheck-observation-findings-2.md, patterns/delta-only-recheck-observation-findings-3.md, patterns/delta-only-recheck-observation-findings-4.md."
---

# Delta-audit evidence: where do later-pass plan-gate findings sit?

Read-only analysis of the yitc-v2 kernel's plan-gate audit history (2026-07-08 → 2026-10-05). Date: 2026-10-06.
Question: when a plan gate is re-run after the plan absorbed findings, are the findings of pass N in text that CHANGED since pass N-1 (A), in unchanged text that DEPENDS on the change (B), or in unchanged text INDEPENDENT of the change — a pre-existing defect earlier passes missed (C)? R = unchanged + independent but already reported in an earlier pass (a repeat, not a miss). U = cannot tell.

## Bottom line

- **About a quarter of the HIGH findings in re-check passes are C**: 35 of 143 (24%). They sit in text that was unchanged since the previous pass and that the change does not touch or reference. Counting the B-vs-C judgement calls (U) as C, the share is up to 36%. For MEDIUM findings the C share is 31%, and up to 45% with U.
- A delta check that reads the change and what depends on it, and also re-verifies the prior findings (A+B+R), would have seen 92 of 143 high findings (64%). Without re-verifying prior findings (A+B only) the figure is 57%.
- **24 of the 61 pass-pairs that produced any high finding (39%) contained at least one C-class high.** These span 16 plans and all four gates. The C share does not fall in later passes: it is 24% at pass 2, 24% at pass 3 and 27% at pass 4+.
- 30 of the 35 C-class highs sit in text that had been there since the gate's FIRST pass, so every earlier full read missed them, including the first. The other 5 sat in text that an earlier absorbing edit introduced and the very next full pass missed, even though that text was inside its delta.
- **Verdict: a delta-only re-check is UNSAFE as the sole re-check.** It is acceptable only as a fast inner loop with two safeguards: (1) escalate to a full read whenever the delta finds a high or medium finding; (2) a full read must produce the closing GREEN (see Conclusion).

## Data and method

- **Passes and findings.**
  - Accept gate (`plan check`, `decisions/<slug>-audit.yaml`): every distinct committed version of the record in git history, matched to its `draft_checked` journal row to get the pass time and index.
  - gate-specs, gate-trial and gate-executing from 2026-09-13 on: the `external_audit_completed` journal rows, which carry the full findings per pass.
  - The same three gates before mid-September: committed versions of `decisions/<slug>-audit-gate-*.yaml` from git history.
- **Audited state at pass N.**
  - Plan file: pinned exactly where the record's `content_hash` (sha256 of the stripped plan body) matched a committed plan body. This held for 121 of 155 pairs (mode E).
  - Draft specs (`proposed_by: <slug>`) and cut cards (`decomposed_from: <slug>`): the latest commit at or before the pass time.
  - Where the absorbing edits were committed in one batch AFTER pass N ran, so that pass N's exact text was never committed (mode W, 28 pairs), the analysis used a window diff: last commit at or before pass N-1 → first commit after pass N. Each hunk was attributed to the pass whose findings it absorbed, using the commit messages and the in-plan absorption notes. Hunks that fixed pass N's own findings were not counted as change.
  - Six pairs used timestamps only (mode T).
  - Thirteen pairs span uncommitted intermediate accept passes whose findings are lost (`+gap`).
- **Classification.**
  - Every finding of pass N was classified against the diff and the full text at pass N, under one written rubric. Ten parallel analyst passes each took a group of plans.
  - Severities were normalized: RED/blocking/HIGH → high, YELLOW/MEDIUM → medium, GREEN/info/LOW → low.
  - Auditor items that were positive observations ("passes", "no change needed") or parse artifacts were marked NA, not defects.
  - Several C classifications were spot-checked against the raw diffs: roll-affected v3 #2, inspection-list gate-executing p2 #4, sandbox-stand gate-specs p5 #2 and ceiling-decisions v2 #4. All held.
- Working files (pair packets, diffs, per-finding JSON) lived in the analysing session's machine-local scratch and are not kept in the repository. The per-finding table (the four findings parts named under §Appendix) is the durable record; every aggregate above recomputes from it.
- Plan names are the plan file names cut to 50 characters, as the journal records them. Two of them are written here with a `*` in place of their tail (`sandbox-stand-roles-*`, `two-sandbox-stands-and-advisory-rules-*` — each matches exactly one file under `plans/`), because the tail repeats a word the published-cut account-name guard counts.

## Coverage

| | count |
|---|---|
| Plans with ≥2 passes on the same gate, 2026-07-08 → 2026-10-05 (journal `draft_checked`) | 63 plans / 123 plan×gate sequences / 242 consecutive pass-pairs |
| **Analysed** | **45 plans / 77 sequences / 155 pass-pairs** (accept 71, gate-executing 49, gate-specs 26, gate-trial 9) |
| Pass-pairs whose pass N had ≥1 finding | 113 (42 pairs had pass N with 0 findings — nothing to classify) |
| Findings classified | 551 = 143 high + 204 medium + 57 low defects, plus 147 NA (positive/info notes, mostly auditor 'low'/'info', and parse artifacts) |
| State reconstruction | 121 pairs exact plan body (E), 28 window (W), 6 timestamp (T); 13 pairs with a gap |
| **Skipped** | 46 sequences (59 pass-pairs). Findings of at most one pass are recoverable there: the gate record is overwritten per pass and only one version was ever committed, and before ~2026-09-13 the journal rows held only verdict and count, not findings. |

Skipped sequences (46, in 31 plans; 18 plans have no analysed sequence at all): anti-false-green-doctrine-differential-proven-chec (accept, executing); apply-the-anti-false-green-differential-rule-to-th (trial); audit-friction-packet-contract-ac-contract-so-pre- (accept); audit-without-episodes-one-typed-ceiling-decision- (specs); audit-without-episodes-re-filed-one-typed-ceiling- (specs); born-permissive-project-defaults-with-review-propo (specs); ceiling-decisions-one-typed-controller-decision-pe (specs, trial); deploy-seam-security-producer-run-fresh-evidence-b (accept, executing); frozen-defect-baseline-at-the-audit-loop-ceiling-d (specs); give-a-dispatched-worker-a-land-path-that-survives (accept, executing, trial); http-reachability-as-an-adoptable-grade-only-offer (accept, executing); inspection-list-refresh-2026-07-delta-recalibratio (accept, executing); journal-storage-shape-keep-one-logical-journal-wit (specs); kernel-reads-project-declared-conventions-instead- (accept); land-throughput-cut-queue-occupancy-and-doomed-lan (specs); loud-failure-principle-one-tripwire-per-silently-b (trial); make-the-land-escalation-path-reachable-diagnosabl (accept); migration-import-safety-provenance-marker-premise- (accept, executing, trial); move-test-scratch-out-of-the-repository-tree-one-v (accept); outcome-invariant-observability-for-unowned-subsys (accept, executing); per-consumer-activation-for-adoptable-offerings-de (accept, executing); production-readiness-by-derived-profile-a-project- (accept, executing); progressive-newcomer-onboarding-seeded-self-retiri (executing, trial); project-declared-audit-post-exemption-cases-plus-t (specs, trial); prove-the-deploy-evidence-chain-acts-on-target-dis (accept); read-contract-for-composed-seams-and-a-quiet-lane- (accept); remote-verify-venue-kernel-verify-passes-on-an-own (accept, specs); split-worktree-py-along-its-own-spec-seams-runner- (accept); surface-ac-to-probe-correspondence-before-the-stag (trial); two-sandbox-stands-and-advisory-rules-* (accept); verify-layer-subject-scoping-diff-relevant-layer-a (executing). Note: the 42 analysed pairs whose pass N had zero findings count in coverage but contribute no findings.

## Aggregates

**All analysed pairs (high and medium)**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 143 | 65 (45%) | 16 (11%) | 35 (24%) | 11 (8%) | 16 (11%) |
| medium | 204 | 71 (35%) | 32 (16%) | 63 (31%) | 9 (4%) | 29 (14%) |

Bounds on C (U counted as not-C → as C):

| sev | C (lower) | C + U with bc=true | C + all U (upper) |
|---|---|---|---|
| high | 35 (24%) | 49 (34%) | 51 (36%) |
| medium | 63 (31%) | 84 (41%) | 92 (45%) |

U composition: high 16 = 14 B-vs-C calls + 1 external change (a SPEC-0204 budget rule landed between passes, making unchanged plan text wrong) + 1 audit-packet artifact; medium 29 = 21 B-vs-C + 8 other (window-unattributable, mixed A+C, cut not committed at the previous pass). Where analysts recorded a lean on a U (10 high+medium items), 9 leaned C and 1 leaned B.

**Sensitivity — only exact-state pairs without gaps (E)**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 103 | 48 (47%) | 12 (12%) | 27 (26%) | 5 (5%) | 11 (11%) |
| medium | 144 | 44 (31%) | 20 (14%) | 55 (38%) | 6 (4%) | 19 (13%) |

**Sensitivity — approximate pairs (W / T / gap)**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 40 | 17 (42%) | 4 (10%) | 8 (20%) | 6 (15%) | 5 (12%) |
| medium | 60 | 27 (45%) | 12 (20%) | 8 (13%) | 3 (5%) | 10 (17%) |

**By gate — gate-accepted**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 53 | 28 (53%) | 5 (9%) | 9 (17%) | 4 (8%) | 7 (13%) |
| medium | 118 | 38 (32%) | 23 (19%) | 39 (33%) | 6 (5%) | 12 (10%) |

**By gate — gate-specs**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 35 | 15 (43%) | 4 (11%) | 10 (29%) | 2 (6%) | 4 (11%) |
| medium | 37 | 17 (46%) | 5 (14%) | 8 (22%) | 1 (3%) | 6 (16%) |

**By gate — gate-trial**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 8 | 3 (38%) | 1 (12%) | 1 (12%) | 2 (25%) | 1 (12%) |
| medium | 8 | 1 (12%) | 1 (12%) | 4 (50%) | 1 (12%) | 1 (12%) |

**By gate — gate-executing**

| sev | n | A | B | C | R | U |
|---|---|---|---|---|---|---|
| high | 47 | 19 (40%) | 6 (13%) | 15 (32%) | 3 (6%) | 4 (9%) |
| medium | 41 | 15 (37%) | 3 (7%) | 12 (29%) | 1 (2%) | 10 (24%) |

**By pass index (pass N)**

| sev | pass N | n | A | B | C | R | U |
|---|---|---|---|---|---|---|---|
| high | 2 | 84 | 43 (51%) | 8 (10%) | 20 (24%) | 6 (7%) | 7 (8%) |
| high | 3 | 33 | 11 (33%) | 4 (12%) | 8 (24%) | 4 (12%) | 6 (18%) |
| high | 4+ | 26 | 11 (42%) | 4 (15%) | 7 (27%) | 1 (4%) | 3 (12%) |
| medium | 2 | 110 | 42 (38%) | 16 (15%) | 28 (25%) | 2 (2%) | 22 (20%) |
| medium | 3 | 29 | 10 (34%) | 4 (14%) | 12 (41%) | 2 (7%) | 1 (3%) |
| medium | 4+ | 65 | 19 (29%) | 12 (18%) | 23 (35%) | 5 (8%) | 6 (9%) |

**Pass-pair level**

| measure | value |
|---|---|
| Pass-pairs analysed / with any finding / with ≥1 high | 155 / 113 / 61 |
| **Pass-pairs with ≥1 C-class high** | **24** (39% of high-bearing pairs; 16 plans). 32 counting U-bc highs |
| …of those 24, pairs where the same pass ALSO had a high that a delta+prior-re-verify would catch (A/B/R high) | 20 |
| …where it had at least an A/B/R high or medium (i.e. a 'escalate on any high/medium' rule would trigger a full read) | 22 |
| …where a delta would have found nothing high/medium (the C-high would pass silently) | 2 (prototype-never accept v4, batch-queued gate-executing v2); 3 with U-high (project-declared accept v11) |
| Pairs where a delta (prior re-verify) finds no high/medium but the full pass found a C/U high or medium | 11 of 62 'delta-clean' pairs |
| Pairs where a PURE delta (no prior re-verify) finds no high/medium | 70, of which 9 hid a C or R high |
| High-bearing pairs where the delta itself would find a high (so escalation would fire) | 54 of 61 |

Other observations from the classification:

- **A is the single largest class.** 45% of highs sit in the text just written to absorb the previous findings: incomplete fixes, new holes, or fixes contradicting other text. A delta check would be productive on these.
- **Sibling instances.** Several C findings are the same defect class that pass N-1 reported for ONE card or section, while the fix touched only that one and the siblings went unreported. Examples: read-contract / AC4 future-bound probes beside the fixed; newcomer / bundling beside the split; prototype-never AC2 beside the pass-1 list. A delta that sweeps for every instance of each absorbed finding's defect class would catch these.
- **Explicitly passed, then failed.** In 3 cases pass N-1 explicitly judged a property correct and pass N, with nothing changed, found it wrong. Examples: external-auditor's `requires` ordering, and collaborator-lane's `requires` link.
- **Re-runs on unchanged text still produce new findings.** In security-audit-cadence accept pass 3 (plan body identical to pass 2) and the project-declared gate-executing v2 (plan body identical; only `expected_touch` lists changed), a re-read of unchanged text yielded new medium and high defects. Single full reads clearly have well under 100% recall.

## Examples of C-class high findings (evidence)

- roll-affected-test-selection — accept gate, pass 3 (E). The plan's External-checks paragraph says the mandatory trial stage was SKIPPED by owner ruling after gate-trial went RED twice; the auditor calls this a governance bypass (a risk acceptance cannot amend a mandatory rule). Evidence: the paragraph «Trial-eligibility (SPEC-0035): NO — the trial stage is SKIPPED (owner ruling, 2026-08-23)…» is verbatim in the audited bodies of passes 1, 2 and 3 and appears in neither diff; the 2→3 edit (abort threshold, heading dedupe) does not reference it. Missed by two full passes. *(pair `acc__roll-affected-test-selection-out-of-shadow-mode-by__v3`, finding #2)*
- sandbox-stand-roles — gate-specs, pass 5 (E). Part D steps 1–2 set the live base L to the repository root on a first deploy and take the range `git rev-list L..R`, which never includes the root commit itself. Evidence: «With no such row (the first governed deploy), L is the repository root.» / «The commits of `git rev-list L..R`» are identical at passes 3, 4 and 5 (they appear only as context lines in the 3→4 and 4→5 diffs); the 4→5 delta changed merges, the identity rule, skip naming and evidence home. Text written at pass 2→3, missed by passes 3 and 4. *(pair `gspecs__sandbox-stand-roles-*__p5`, finding #2)*
- inspection-list-refresh-2026-09 — gate-executing (decomposition fidelity), pass 2 (E). The theme cards' AC3 «Deferrals = none or tracked ids only» ignores the plan's criterion 7 split between VALIDITY-BLOCKING deferrals (must be resolved) and routed ones. Evidence: AC3 on … and plan criterion 7 are both unchanged between pass 1 and pass 2; the 1→2 change only appended AC5 convergence probes and concrete `expected_touch`. In the same pass three more C-class gaps surfaced on unchanged cards (no size checkpoint, no remove-or-replace probe, verifier card V's AC1 missing both tracks). *(pair `gexecuting__inspection-list-refresh-2026-09-delta-recalibratio__p2`, finding #4)*
- migrate-<project> — gate-executing, pass 2 (E, from git). Three plan components (external config deps gspread/Yandex, the <project> contract re-home, tracked frontend/dist) have no card. Evidence: the plan file is not in the 1→2 diff at all; no card at either state mentions these items; the absorbing edits only filled `expected_touch`, added `requires` edges and split host territory. A pure decomposition-coverage miss by pass 1. *(pair `git-gexecuting__migrate-<project>-onto-yitc-v2-v1-incumbent-heavies__v2`, finding #2)*
- session-refresh-hand-off-store — gate-executing, pass 3 (E, on-decisions pass). AC1–AC9 never probe a successful `drop` or `list`. Evidence: AC1–AC9 identical at passes 1, 2 and 3; the 2→3 change on removed AC10, added a definer scope bullet and dropped SPEC-1004 from `expected_touch`. Pass 1's probe-quality finding addressed AC9/AC3 only. *(pair `gexecuting__session-refresh-hand-off-store-per-project-ephemer__p3`, finding #2)*
- risk-cohort-test-selection — gate-specs, pass 2 (W, window attributed). The promised time saving cannot happen because cheap code lands still trigger the full pinned leg. Evidence: «SPEC-0077 / SPEC-0186: unchanged — verifier and selector functions are in the expensive zone…» and the Step-0 savings model («≈ 30-45 min/day») predate pass 1; the pass-1 absorption (D1–D4: qualifying full-green, recovery R, miss counting, build order) touches neither; a journal deviation row at 20:34:16Z later confirmed the model had been wrong from the start. *(pair `gspecs__risk-cohort-test-selection-for-code-lands-backed-b__p2`, finding #1)*

## Caveats

- **Record overwrites:** the accept-gate record is overwritten per pass, so only COMMITTED passes are visible. 13 pairs bridge 1–2 lost passes (`+gap`): an A there may have been changed before the lost pass, and an R/C may have been reported by it. Before ~2026-09-13 the gate-* journal rows carry no findings, so 46 sequences were skipped.
- **State reconstruction:** draft specs and cards are taken at the latest commit at or before the pass time. An edit sitting uncommitted in the worktree when the auditor ran is invisible, which biases toward 'unchanged' and so toward C. Window-mode pairs (28) needed hunk attribution from commit messages and in-plan notes. The approximate subsets show slightly LOWER C for highs (20% vs 26% exact), so the result does not hinge on them.
- **What the auditor saw:** the packet also includes context (parent specs, corpus slices, prior decisions on 'on-decisions' passes, adapters' engine context). 'Changed' was judged on the plan + its draft specs (cards); a few findings were caused by changes OUTSIDE the subject (e.g. landing a new SPEC-0204 budget between passes) — counted as U.
- **Judgement calls:**
  - A vs C when the defect is old but its line was re-worded in the diff ('prex_in_hunk', 6 items: 3 were classed A because a line-level delta would see them, 3 were classed C).
  - B vs C (45 high+medium U items).
  - Positive 'info' notes the auditor labelled low or medium (147 NA).
  - The C count is conservative: doubtful cases went to U, not C. Analysts flagged one medium C, in security-audit-scaffold, as a likely auditor false positive. Validity of findings was not re-judged in general: a C means the auditor raised it on unchanged text, not that it is a real defect.
- **Severity vocabulary** varies by era (RED/YELLOW/GREEN, high/medium/low, blocking, INFO); normalized as above.
- **Auditor model:** recorded in 42 pairs and identical between N-1 and N in all of them. Unknown for the rest, so model switches are not the explanation where known.
- **Side effect:** one read-only `bin/yitc-v2 journal query` run appended its designed `cli_invoked` telemetry row to `events.jsonl`. No other repo file was touched.

## Conclusion

A delta check (the change plus what depends on it) is **unsafe as the only re-check, and risky even with prior-finding re-verification**:

- About one in four high findings in re-check passes (24% certain, up to 36%) is a pre-existing defect in unchanged, independent text.
- That rate does not decay over passes 2, 3 and 4+.
- 24 of the 61 high-bearing re-check passes found at least one such defect.
- Repeated full re-reads are evidently what surfaces these defects: 30 of the 35 C-highs had survived every full read since pass 1.

The data supports a hybrid instead:

1. **Pass 1 at each gate stays a full read.** This is already the case, but it is not sufficient.
2. **A delta pass re-verifies every prior finding and sweeps for sibling instances.** For each absorbed finding it checks the defect class across the whole subject. This turns R and the sibling-type C into catches. With A+B only (no prior re-verification), 70 pairs would come back clean, and 9 of them held a C or R high.
3. **Escalate to a full read whenever the delta finds a high or medium.** That would have triggered in 22 of the 24 C-high pairs, and in 54 of 61 high-bearing pairs. In practice the saving therefore comes only from the quiet late passes.
4. **The closing GREEN must come from a full read.** This catches the residue: in 2–3 C-high pairs and 11 C/U high-or-medium pairs a delta would have come back clean.

With 3 and 4 in place, a delta is a cheap inner loop while absorptions churn, not a replacement for full reads. The quality cost of going further is fewer independent full reads, and the data says each full read keeps finding about a quarter of its highs in text nobody changed.

## Notes on the saved copy

Added when the report was saved (from the audit of that card's plan). They correct two statements of the text above; no number in it was changed.

- **Coverage does not add up.** The coverage table counts 242 consecutive pass-pairs in total, 155 analysed and 59 skipped. That leaves 28 pairs (242 − 155 − 59) that the report neither analysed nor lists as skipped, and it does not say why.
- **What the 36% upper bound counts.** The Bottom line says the high C share is «up to 36%» when the B-vs-C judgement calls are counted as C. That is not exact: the 14 B-vs-C calls give 49 of 143 (34%); 51 of 143 (36%) counts all 16 U highs as C, including the external-change and audit-packet-artifact cases (see «Bounds on C» under Aggregates).

## Appendix — every classified finding

The per-finding table (one row per classified finding, 551 rows) is split by size into four parts, in plan order: `patterns/delta-only-recheck-observation-findings-1.md` (168 rows), `patterns/delta-only-recheck-observation-findings-2.md` (181 rows), `patterns/delta-only-recheck-observation-findings-3.md` (136 rows), `patterns/delta-only-recheck-observation-findings-4.md` (66 rows). Mode: E = exact plan state (content_hash), W = window (batched absorptions), T = timestamp; `+gap` = lost intermediate pass(es). `pass` = previous → N (accept gate: journal accept-pass index; other gates: `passes` counter). Class NA = positive/info note or parse artifact, not a defect.

↺ = repeat of an earlier-pass finding (an A↺ is an incomplete fix inside changed text).
