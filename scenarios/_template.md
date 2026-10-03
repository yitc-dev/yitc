---
scenario: <slug> # kebab-case id (REQUIRED explicit key — a file without it is not indexed)
actor: <who walks this path> # product: the end-user role; v2-self: controller | worker
# status: OMITTED while live — draft|building|live are a COMPUTED view (derived from cited-spec FSM +
# the binding test, SPEC-0076 §3), NEVER stored. Set `status: retired` ONLY to retire the path; any
# stored draft|building|live is REJECTED at graph build (exit 2). So: leave `status` absent normally.
cites: [] # frontmatter ROLLUP of the binding specs/anchors this path passes through
covers: [] # OPTIONAL: code/anchors this path drives (resolved against today's graph anchor-space)
---

# Scenario — <human-legible title>

<!-- Authoring format governed by SPEC-0076 §5 (step-annotated cites + role gloss + error-branch
     shape). A scenario is ZERO-NORMATIVE (SPEC-0076 §2): narration + `cites` only — every rule
     lives in the cited spec, never here. Fetch: `bin/yitc-v2 graph query SPEC-0076`. -->

<One line: the value this user-path delivers. Human terms, no jargon.>

## How it should happen (user-path)

<Numbered steps. Each step is annotated with its ONE governing anchor + a one-line role gloss.
 Convention (so the integrity queries can read it): a step line ends with
   → `<ANCHOR>` — <gloss>
 where <ANCHOR> is the governing spec/decision/handbook section, OR the literal `(ungoverned)`
 for a deliberately ungoverned step (e.g. a recognized non-goal). The gloss POINTS at the rule;
 it never RESTATES it (zero-normative — P5 content boundary).>

1. **<block-id>** <step text> → `<ANCHOR>` — <gloss>
2....

### Error / negative branches (if any)

<Alternate branches for "how it must NOT work" — descriptive narration only. Each branch step
 `cites` the spec whose `## Verification` carries the enforceable negative check (the oracle).>

## Reusable blocks

<The shared blocks this path composes (factored out so other scenarios reuse them).>

## Notes (non-normative glue)

<Optional human glue. NEVER a rule. If you find yourself writing "must"/"always"/"never" as an
 enforceable constraint, extract it to a spec and `cite` it instead.>
