# <vendor-adapter>.md — vendor adapter (minimal anti-Forgetting floor)

This file exists because certain AI agents read this exact filename automatically AND re-read it
on every cwd-change into a checkout/worktree. The canonical AI session protocol lives in `AGENTS.md`
(`AGENTS-SESSIONS.md` + `AGENTS-PROTOCOL.md`, split for single-Read safety, SPEC-0120). This adapter
NO LONGER `@`-imports the full audience seed — that re-fired the whole ~1300-line seed on every
`cd`. Instead it carries only the MINIMAL floor below; the FULL seed is delivered + ENFORCED by the
one-time startup read (see the last line). Floor contract: SPEC-0127 §4 + SPEC-0007 §5.

**Two anchors — hold from token 0 (voice both before your first SUBSTANTIVE action — any edit/write, or any mutating/governed command (the read-only startup calls a session's own `session start` needs are exempt)):**
1. **Anti-complexity (CHARTER §Principle 1).** Every addition passes 4 filters (existing analog? ·
   view-over-new-entity? · what gets removed? · real incident/prior-art?). When in doubt, don't add.
2. **Deviation-capture reflex.** The moment something is not as it should be (manual
   fallback, redundant re-read, artifact contradiction) → `bin/yitc-v2 event deviation_captured …`
   immediately. Capture is a reflex, not a judgement. Full procedure: `patterns/error-friction-tracking.md`.

**Audience routing — read your seed, then act:**
- **Dispatched Worker** (`--type build`): your whole startup seed is the generated `core`+`worker` view,
  emitted as single-read-safe PARTS — read **`graph/worker-seed.md` AND every continuation part it chains
  to** (`graph/worker-seed-2.md` …; part 1 names them all) IN PLACE OF the full files. ONE part is NOT the
  seed. Re-read the whole chain after any `/compact`.
- **Interactive Controller:** read the **SOURCE parts DIRECTLY, in the read-order below** — each file is
  single-read-safe, so no assembled monolith is needed (the generated `graph/controller-supplement.md`
  is a derived reference view, not your runtime read); re-read the same parts after any `/compact`.

**Read-order** (the Controller's runtime read AND the generation manifest the Worker's view assembles from, plus the floor):
`CHARTER.md → AGENTS.md → AGENTS-SESSIONS.md → AGENTS-PROTOCOL.md → LIFECYCLE.md → QUEUE.md → GRAPH.md`
(the floor trigger-map `graph/floor-trigger-map.md` + `MEMORY.md` — but `MEMORY.md` is
**Controller/interactive-only**: a DISPATCHED WORKER (audience `background`, `session start --type build`)
does NOT auto-read the buffer at all — its controller-oriented cross-session content is a confabulation
source for a task-bounded worker, SPEC-0039 §0 worker-exemption). Re-read the WHOLE of YOUR
audience's seed after every `/compact` (SPEC-0007 §5b, per-audience coherence).

**No governed action before your seed receipt.** `bin/yitc-v2 session start` delivers your audience
seed AND records the epoch-scoped `seed_read` receipt; every governed/mutating verb REFUSES
(`_require_seed_read`, SPEC-0050 §8) until a receipt fresh for THIS context epoch exists — so this
minimal floor is a belt, and the enforced read is what guarantees the full seed reaches you before
any work. This adapter stays thin (SPEC-0007 §3 plumbing thinness); the normative text lives in the
handbook it routes you to, never here.
