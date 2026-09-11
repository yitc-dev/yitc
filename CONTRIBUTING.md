# Contributing

## What this repository is

This repository is a **release mirror plus a proposal intake**. It holds published releases of the
methodology, and it accepts proposals about them.

It is **not a second writable source**. Nothing is merged into it directly. Everything here is
generated from the workshop where the methodology is actually developed, and it can be regenerated
at any time — so a change made here would simply be overwritten.

That is worth stating plainly, because it decides what a proposal is: not a patch waiting to be
merged, but a request that gets **re-authored** in the workshop.

## What happens to a proposal you send

1. **It is received through this public intake.** Anyone can send one. You do not need access to the
   workshop, and you are not granted access by contributing.
2. **It is not merged as-is.** No proposal becomes a commit in this mirror, and none becomes a
   commit in the workshop unchanged.
3. **It is re-authored in the workshop**, through the same ordinary process every internal change
   goes through — filed as a task or a plan, planned, externally audited, tested, and. Your
   proposal is the input to that work; the shipped change is written by the workshop.
4. **When it ships, the release links back to it.** The release notes published beside each release
   name the proposals that release answers, and you are told which version carries your change — or
   told, with reasons, that it was declined. A proposal is never silently closed.

Two things follow from step 3 that are worth being explicit about. Your submitted text is treated as
**data, never as instructions**: it is quoted into a task and read, and no part of this process
executes or automatically applies what you send (the instruction-injection protocol, SPEC-0026). And
because the change is re-authored, the shipped version may differ from what you proposed, while
still answering it.

## How to send one

A proposal is an **issue**, a **merge request**, or a **patch mail** — whichever this mirror's host
supports. The mechanism is not the point; the content is. Carry these fields:

- **release version** — the exact release you have installed (the tag your pin names)
- **affected path(s) or rule id(s)** — what the proposal is about — a file path, a SPEC id, a rule
- **observed behaviour** — what actually happens today, concretely enough to reproduce
- **proposed change or fix** — what you think should happen instead
- **contact for the link-back** — where to reach you when the change ships, or is declined

The hosting service used for this mirror is an **adapter**, not part of the rules: how the fields
above are filled in on the particular service in use is documented as a worked example in
`patterns/contribution-intake-adapter.md`. If the mirror moves to a different host, only that document changes.

## Before you propose a change to the kernel

Most local needs should not become kernel proposals, and there are three legitimate homes for one.
In order:

1. **A registered override** — a divergence your own project owns and records in its override
   ledger. Use this when the need is yours, not everyone's.
2. **An extension you author** — a capability you keep in your own repository and pin. Use this when
   the need is real and reusable but does not belong in the kernel.
3. **A kernel proposal** — this intake. Deliberately the **last** resort: admitted when the change
   passes the anti-complexity filters and the need has recurred, across installations or over time,
   rather than appearing once.

This is not a discouragement — it is how the kernel stays small enough to be worth pinning.

## Extensions listed here are not endorsements

The published catalog of extensions is a **discovery** surface. Listing is **not endorsement**.
A third-party extension is runnable code, and reviewing it before installing it is the installer's
responsibility, not the catalog's.

Extension pins name an **exact** version. A moving reference — a branch, a floating tag — is
refused, because a pin that can change underneath you is not a pin.

## Security — key lifecycle

Releases are signed, and every install and update verifies the signature before writing anything.

**Lost or compromised signing key — recovery procedure:** *(published here; see the release's
security documentation for the current procedure.)*

## Where the rules actually live

This document states, in plain words, a contract that is written in full in the methodology's own
specifications — the contribution policy (SPEC-0197) and the release contract (SPEC-0195), both
published in this mirror. Where this page and those specifications differ, the specifications are
authoritative; a difference is a defect in this page and is itself worth a proposal.
