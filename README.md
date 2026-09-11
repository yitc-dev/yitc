# YITC v2

Minimal AI-assisted development methodology для one-developer setup.

## What this is

- **One developer** (owner) + **primary AI agent** shipping production projects
- **One external auditor** (different AI provider) catching blind spots
- **Two session types**: Build (do work) + Review (plan / audit / decide)
- **No pipeline, no role-split, no hook cascade**

## Install on a clean machine

Bootstrap order (prerequisites → clone/verify/install → `init` → kernel pin → external auditor →
first session): [`onboarding/bootstrap-order.md`](onboarding/bootstrap-order.md). Take the anchor
fingerprint and the three release commands from the org-profile README, not from a mirror.

## Quick start

```bash
# Read in this order:
cat CHARTER.md # 8 principles + non-goals (why V2 exists, what it WON'T become)
cat <vendor-adapter>.md # AI session protocol — what AI reads at start, how it works
cat LIFECYCLE.md # 9-stage task lifecycle (one continuous workflow per task)
cat QUEUE.md # queue model (active / done / parking-lot)
cat GRAPH.md # specs ↔ code linking (minimal)
```

CLI (`bin/`) ships Day 3-4. Until then everything is markdown + manual.

## Repo structure

```
yitc-v2/
├── CHARTER.md # principles + non-goals (read first)
├── <vendor-adapter>.md # AI session protocol
├── LIFECYCLE.md # 9-stage task lifecycle
├── QUEUE.md # queue model
├── GRAPH.md # specs ↔ code linking
├── PATTERNS.md # catalog of imported patterns (from v1)
├── tasks/<id>.yaml # one task per file, machine-managed
├── decisions/<id>.yaml # one decision per file
├── specs/<id>.yaml # one spec per file
├── patterns/<name>.md # extracted patterns (one.md per pattern)
├── graph/index.json # derived spec ↔ code graph (built by tool, committed)
├── events.jsonl # ONE append-only event log
└── bin/ # CLI tools (Day 3)
```

## Versus v1

V1 lives at `<v1-archive>/` — frozen as archive + reference. Knowledge patterns, decision history, and learned mistakes from v1 are valuable and accessible there. Active development is V2.

## License

See `LICENSE`.
