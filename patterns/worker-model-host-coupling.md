---
name: worker-model-host-coupling
class: observation
sourced_from: split from [[background-session-dispatch]] (per SPEC-0120 §3 per-doc size band — the dispatch file crossed the 63,000 B one-bounded-read ceiling); the section is moved verbatim except its F1 line, reworded to name its new location. Substance — the 2026-09-23 fleet-wide bootstrap death (X-1550 / X-1551 / X-1553).
applies_to: changing the worker model id in `bin/effort-routing-config.yaml`, and diagnosing dispatched workers that die at bootstrap leaving no journal rows. Sibling of [[background-session-dispatch]] (the launcher contract this craft is about).
---

# Worker model host coupling

> **Split sibling (per SPEC-0120 §3 per-doc size band).** This section was carved verbatim
> from `patterns/background-session-dispatch.md` (only its F1 line reworded for the new location),
> which keeps the launcher contract it is about.
> Split relocates content — it removes nothing.

## §The worker model is a HOST-coupled dependency, not a config value (craft — no guard)

**The lesson, in one line: the model id in `bin/effort-routing-config.yaml` is resolved by a client
BINARY whose version lives outside this repo, so changing it commits the whole host to a
compatibility claim the repo cannot check for you.**

<!-- cli-version-history -->
**What happened (2026-09-23).** Kernel commit `528b4eed6d` set `models.primary` to
`<provider-model>[1m]`. The AI tool installed on the host was 2.1.278, which refuses that id
(`[the AI provider-code:unrecognized_model]`, then `400 … version 2.1.280 or newer is required`). From
12:21:52Z **every dispatched worker, for every consumer project, died at bootstrap.** Three projects
reported it independently within two hours (X-1550 <project>, X-1551 <project>, X-1553 <project>).
Resolved by updating the host client to 2.1.280 — not by any repo change.
<!-- /cli-version-history -->

**Why it was expensive to SEE, which is the real lesson.** Every surface a controller normally trusts
read NORMAL: `dispatch` printed `LAUNCHED` and exited 0, the journal carried `session_started`, and
the card stayed `ready`. The 400 existed in exactly one place — the per-worker dispatch log — and the
launch-stall reader does not recognise that signature, so it classified as an unexplained death. The
documented recovery for that class is «re-bootstrap a fresh worker», which loops forever against this
cause: each retry dies identically, silently, at the same cost. One project burned ~2 hours before a
human opened the log.

**The craft, four points.**
1. **Treat the model id as host-coupled.** It is not a value you set, it is a claim about the binary
   on the machine. The repo has no way to be right about it.
2. **Change it by running it, once, before landing.** A single real dispatch on the host settles the
   question that no amount of config review can.
3. **`dispatch --model <id>` (SPEC-0072) is the working escape** and it is per-field. Reach for it the
   moment workers die at bootstrap across MORE THAN ONE project — a cross-project symptom is a host
   symptom, and no card-level theory will explain it.
4. **When a worker leaves NO journal rows at all, open its dispatch log before concluding anything.**
   An empty journal is not evidence of a hang, a stall, or a death; it is evidence that the worker
   never reached the code that journals. The log is the only witness for that window. **Since
   ** a bootstrap that dies INSIDE the launch probe window (this incident's shape: seconds) is
   no longer silent — `dispatch` reports `refused(reason=bootstrap-died)`, exits non-zero when nothing
   came up, and journals the log tail on a `premature_exit` halt. A death AFTER the probe window still
   reads `still-booting` until the bootstrap grace passes — for that window this point stands.
   **Since ** the reader also RECOGNISES this signature: once that grace passes, the row reads
   `launch-stall(unsupported-model)` with a fix-the-mismatch remedy instead of «re-bootstrap», and the
    `premature_exit` row's `cause` names it too.

**No guard was added, deliberately (owner ruling, 2026-09-23).** The reporters proposed a pre-launch
check that the resolved model is runnable by the installed client. The owner declined it and asked for
this lesson instead. The reasoning holds up on the §P1 filters: the path already has a working escape
hatch (point 3) and a one-line diagnosis (point 4), so the guard would buy earlier detection of a
condition a human must fix anyway, at the cost of a new pre-spawn verification step on every launch
forever. What was missing that day was not a check — it was knowing where to look.

**Anti-complexity (CHARTER §P1) — why this earns its place.** **F1 existing analog?** It was written
into `patterns/background-session-dispatch.md`, the dispatch-mechanics home that carries the launcher
contract this lesson is about — extended, not duplicated; it moved to this sibling file only by the
SPEC-0120 §3 size split, which relocates text and adds no rule. **F2 new entity or view?** Prose in an existing section
file: no verb, gate, store or mechanism. **F3 what gets removed?** The assumption that a config-only
change is repo-local, and the reflex to re-dispatch a worker that left no rows. **F4 real incident?**
Measured the same day across three projects, with the commit, the client versions, the verbatim error
and the fleet-wide onset time all recorded above.
