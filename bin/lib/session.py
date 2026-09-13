"""Session verb-family for the yitc-v2 CLI — `session start` (the startup-protocol activation:
the `session_started` journal markup + read-order / seed echo + the NON-MUTATING type-dispatch,
D-0041 / D-0052 / T-0510) plus its read-only startup helpers. The sixth layer-2 verb-family
extraction (after scenario.py / error.py / gates.py / spec.py / dispatch.py), plan
`layer-2-tail-remainder-decomposition-of-bin-yitc-v` wave-2a card T-9336.

bin/yitc-v2 keeps the thin argparse residue cmd_session_start (the `set_defaults(func=…)` entrypoint,
wiring unchanged) which delegates here, injecting the host collaborators + host globals it reads — the
spec.py / dispatch.py verb-family precedent (family bodies in lib, host thin residue + injected host
deps), so a `-C` REPO_ROOT rebind and every `monkeypatch.setattr(yitc, …)` stay honored at call time.
The cross-called movers (_session_build_dispatch / _session_controller_dispatch / _print_task_resume /
_waiting_on_owner_lines) are ALSO injected into cmd_session_start (so a test that patches a HOST
residue name and drives THROUGH cmd_session_start is honored — the dispatch.py registry precedent).
T-9698: the Build|Review interactive type CHOICE is retired — `--type build` is the dispatched Worker,
no `--type` is the interactive Controller; _session_controller_dispatch REPLACES _session_review_dispatch
(both frame the SAME _session_build_dispatch resume-or-await body, per posture).

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
stdlib + the already-extracted lower leaves lib.state / lib.cross / lib.views; it NEVER back-imports the
host. (lib.views imports only stdlib — no cycle.) Behaviour is byte-identical to the inline originals —
the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
from pathlib import Path

from lib import state
from lib import cross
from lib import graph   # T-10219: `worker_seed_part_files` — the ONE home that derives the seed part chain
from lib import views   # SPEC-0115 §1: the SINGLE transcript-usage parse home (usage_token_classes)
from lib import observe  # SPEC-0135 / T-10121: the observation-loop capture-field composers
from lib import init     # T-10912: `declared_neutral_home` — the ONE SPEC-0125 home resolution


def cmd_session_start(args: argparse.Namespace, *, _resolve_or_mint_identity,
                      _worker_identity_self_check, _append_event, _session_config_descriptor,
                      _is_consumer_build, _seed_howto, _filing_reference_howto,
                      _main_worktree, _session_build_dispatch, _session_controller_dispatch,
                      REPO_ROOT, ENGINE_ROOT, RELEASE_VIEW_DIR, HANDBOOK_READ_ORDER,
                      CROSS_LOG_PATH, _cross_linked_ids=None, _cross_peer_aliases=None,
                      _read_yaml=None,
                      _debt_echo_lines=None, _receipt_only=False,
                      _write_runtime_record=None, _provider_kind=None, _provider_session_id=None,
                      _controller_acting_holder=None) -> "tuple[str, str]":
    """Session activation (per D-0041): durable journal MARKUP + startup-protocol ECHO.

    Returns the session's AUTHORITATIVE `(resolved_session_ref, source_kind)` (T-10246; the provenance
    added by T-10318) — the id the `session_started` anchor was emitted under, which the caller re-uses to
    stamp the `cli:seed` receipt, PAIRED with the selector class that produced it. Both are already
    computed here by `_resolve_or_mint_identity`; handing the pair back is the same "never let the caller
    re-derive it" move T-10246 made for the id alone (re-derivation is what split the two ids), and it lets
    the seed receipt record its REAL selector instead of an `explicit` collapse-bucket.

    (1) Emits `session_started` so the session TYPE (controller|build) is durable + queryable
        (`journal query --type session_started`), replacing the ephemeral chat «📍 …» line.
        session_ref/agent are envelope fields added by _append_event — NOT duplicated in data.
    (2) Echoes the handbook read-order + a `--help` rescan reminder (cold-start aid) — the
        useful work that justifies a verb over a bare marker (D-0033). NOT an enforcement gate
        (CHARTER non-goal #7 — session-switch control is post-hoc via `journal query`)."""
    # T-0376: session_config — the verbatim/opaque configuration descriptor (SPEC-0025; the
    # benchmarking key for PART-3 same-task-different-config comparison).
    # T-0557 / T-10152: collapse-forensic — record HOW this session's identity was established.
    # `_resolve_or_mint_identity` (SPEC-0137 Rule 1) either RESOLVES an explicit carried/worker id via
    # the untouched forensic reader (source_kind `env:YITC_SESSION_REF` | `arg`, modeled) OR, for a fresh
    # interactive session with no carried id, MINTS a fresh v2-owned uuid (source_kind `minted_self_ref`
    # — a NON-carrier provenance, recorded verbatim). resolved_session_ref + source_kind are produced
    # TOGETHER so the pair is coherent (ref ↔ its provenance). No provider env carrier is read (Rule 8b).
    resolved_ref, source_kind = _resolve_or_mint_identity(getattr(args, "session_ref", None))
    # T-0561 part 1: worker fail-closed identity self-check — runs on the CARRIER-resolved ref BEFORE
    # the session_started emit + any claim/worktree. GATED on YITC_EXPECTED presence (interactive
    # unaffected); a worker whose resolved ref != launcher-assigned expected (or a blank expected)
    # ABORTs here, emitting worker_identity_refused from the pre-claim state.
    _worker_identity_self_check(args, resolved_ref, source_kind)
    # T-9698: the Build|Review interactive type CHOICE is retired (T-9697 / CHARTER §6). `--type` is
    # now OPTIONAL: omitted => the interactive Controller posture; `--type build` => the dispatched
    # Worker's flow (set by `bin/yitc-v2 dispatch`). Record the durable session TYPE as the posture
    # name — "controller" when no --type, else the worker's "build" — so `journal query` stays
    # meaningful (the Controller + Worker taxonomy, not a null type).
    _sess_type = args.type or "controller"
    # T-10121 (SPEC-0135 §1/§3, SPEC-0025): capture #1 — the normalized worker-side
    # provider×model×effort triple (the LINCHPIN slice key) + best-effort host facts, DERIVED from
    # the SAME opaque descriptor recorded verbatim as `session_config` (raw provenance). Additive /
    # OPTIONAL — the triple is always present ("unknown" fallback), host facts OMITTED when unknown.
    _cfg = _session_config_descriptor()
    _base_data = {"type": _sess_type, "project": REPO_ROOT.name,
                  "session_config": _cfg,
                  "resolved_session_ref": resolved_ref,
                  "source_kind": source_kind,
                  **observe.session_started_fields(_cfg)}
    # SPEC-0137 Rule 1 bootstrap-exemption (T-10149): emit UNDER the explicit `resolved_ref`. `session
    # start` is the SOLE verb that resolves-or-mints WITHOUT a pre-existing record — it is the record's
    # WRITER, so it must NOT route this anchor through the fail-closed rediscovery resolver (which would
    # _die on a fresh session that has no record/anchor yet). `resolved_ref` is byte-identical to what the
    # pre-T-10149 resolver returned interactively (the first-present carrier), so the anchor's session_ref
    # is unchanged; this only stops the bootstrap from depending on the very record it is about to create.
    # T-12306: ONE computation feeds BOTH the recorded key and the printed line. It must run BEFORE
    # the emit (the journal is append-only, so the dispatch below could not add the key afterwards),
    # and only for the interactive Controller — a dispatched Worker's foreign-stamp BLOCK is
    # untouched. A truthy ref rides the EXISTING `session_started` row as a key (no new event type).
    _acting_holder = None
    if _sess_type != "build" and _controller_acting_holder is not None:
        _acting_holder = _controller_acting_holder()
        if _acting_holder:
            _base_data["controller_acting_in_worktree"] = _acting_holder
    _append_event("session_started", None, _base_data, session_ref=resolved_ref)
    # The DURABLE marker is the session_started event (queryable via `journal query`); this is
    # only a plain confirmation — NOT the ephemeral «📍 …» chat line D-0041 replaces.
    #
    # T-11994 (X-1231): the line NAMES THE CHECKOUT THE ANCHOR WAS WRITTEN TO, not only its basename.
    # `project=` is REPO_ROOT.name — a BARE directory name — and in the worktree layout every checkout's
    # basename is a task id, so an engine worktree (`T-11942`) and a consumer worktree (`T-0460`) print
    # echoes of IDENTICAL SHAPE carrying no repo identity at all. An aiseller worker read a foreign-looking
    # id off this line and reported it as a misdirected `-C` anchor; the journal shows both of its runs
    # anchored correctly (aiseller/events.jsonl#ts=2026-09-02T12:27:05Z and #ts=2026-09-02T12:27:27Z, both
    # project=T-0460) and no engine-side row was ever written. Nothing was mis-anchored — the echo simply
    # could not be checked against anything, which is the harm the deviation records ("a worker that
    # trusted the first echo would believe it had anchored the wrong repo, or worse, not notice").
    #
    # So the ANSWER is put in the line: the absolute REPO_ROOT the `_append_event` just above resolved its
    # journal from. Same expression, same process, adjacent statements — the printed checkout and the
    # written row cannot disagree. `project=` is kept verbatim (existing readers + the cli-line-directive
    # catalog row), the payload is untouched (`data.project` stays the basename — SPEC-0025 schema-stable),
    # and this adds NO new state, verb or gate: it renders a value the function already holds.
    print(f"session_started emitted: type={_sess_type} project={REPO_ROOT.name} "
          f"anchored-in={REPO_ROOT}")
    # T-10153: birth-write the v2-owned runtime record for THIS session, capturing the FORENSIC
    # provider_meta (SPEC-0137 Rule 2.5) = the transcript-provider KIND, so a later provider-blind
    # lookup (`_session_log_path`) resolves the transcript from v2 STATE, not only the live provider
    # env — the codex-worker-on-the-stand driver. NARROW forensic capture: it does NOT touch the
    # resolver (identity resolution stays T-10149's rediscovery chain); the record is inert until
    # consumed. Best-effort — a runtime-home/FS quirk must never break session start (broad-except).
    if _write_runtime_record is not None:
        try:
            # T-12400: capture the provider's OWN session id beside the KIND. The kind alone only
            # ORDERS the descriptor scan; the id is what NAMES the transcript file — and since T-10152
            # `resolved_ref` is a MINTED uuid that names none, without this a later verb whose env no
            # longer carries the provider var cannot join this session's transcript at all (the
            # structurally-inert implicit `journal sync` this card fixes). Forensic-only, exactly like
            # provider_meta: recorded here, read back by the transcript join, NEVER by identity
            # resolution (SPEC-0137 Rule 4 stays provider-free).
            _write_runtime_record(resolved_ref,
                                  provider_meta=(_provider_kind() if _provider_kind else None),
                                  provider_session_id=(_provider_session_id() if _provider_session_id
                                                       else None))
        except Exception:
            pass
    # T-10152 (SPEC-0137 Rule 1/8, option-A): a FRESH interactive session MINTED its v2-owned identity
    # (source_kind == "minted_self_ref") above — the session_started anchor + the runtime record are
    # already written UNDER the minted id. Here we PRINT the carry hint so the agent carries the id on
    # every later CLI call (env does NOT cross the harness's separate Bash subprocesses — the agent is the
    # stable carrier, the interactive analog of a worker's frozen YITC_EXPECTED; the runtime-record locus
    # `getsid` is NOT stable across those subprocesses, so the carry is the reliable selector-1 anchor).
    # This RETIRES the fragile T-10137 mint-and-carry CONVENTION: a MISS is now SAFE — the fail-closed
    # keyer degrades a missing carry to record rediscovery, or fails closed cleanly, NEVER landing a
    # receipt under a drifting PROVIDER key (the retired X-0158 failure mode). A WORKER (--type build,
    # frozen YITC_EXPECTED) and a re-run carrying its own YITC_SESSION_REF RESOLVED instead of minting →
    # no carry hint (already anchored). NOT a new store/gate — the anchor + record are the existing ones.
    if source_kind == "minted_self_ref":
        print(f"session self-ref (SPEC-0137): carry  YITC_SESSION_REF={resolved_ref}  as an env prefix on "
              "EVERY `bin/yitc-v2 …` call this session (incl. re-running `session start`). It is your "
              "v2-owned, provider-neutral session identity under the harness's per-call subprocesses. A "
              "missed carry is SAFE — a later verb rediscovers your session record or fails closed cleanly, "
              "never under a provider key.")
    # T-10246: this checkout is a STAMPED worktree, so the identity leg ADOPTED the stamp's ref instead of
    # minting a second id (SPEC-0137 Rule 3 — the stamp is the write-phase authority, "a PROJECTION of the
    # one identity ... NOT a second id"). Announce it: the adoption is explicit, never silent. The printed
    # ref is now the SAME id both gate-bearing emits land under and the id the read-gate keys on, so obeying
    # this instruction actually satisfies the gate — before T-10246 the printed ref was a fresh mint the
    # gate never saw. The stamp itself is NOT re-written: a re-stamp IS an adoption of the worktree and
    # stays reserved to the explicit, confirmed-dead-gated `worktree adopt` (T-0362).
    elif source_kind == "worktree_stamp":
        print(f"session self-ref (SPEC-0137 Rule 3): ADOPTED this worktree's stamped session ref — carry  "
              f"YITC_SESSION_REF={resolved_ref}  as an env prefix on EVERY `bin/yitc-v2 …` call. The stamp "
              "written at `worktree new` is the write-phase authority here, so no second id was minted and "
              "the stamp was not re-written.")
    # Bootstrap-floor delivery (SPEC-0007 §5, T-0240): the always-loaded seed = the MANDATORY
    # handbook (topological, CHARTER first — pedagogical pin) + the derived floor trigger-map. The
    # RETRIEVED tier is NOT loaded; it is delivered deterministically at stage-entry (`stage <NAME>`,
    # T-0289) or fetched on demand via `graph query` — no startup count-nudge (retired T-0292). ONE
    # canonical read-order — DERIVED from the single carrier HANDBOOK_READ_ORDER (T-0671, SPEC-0007
    # §5b), the SAME source the AGENTS §At-session-start / §Bootstrap-floor / §Three-phase regions are
    # generated from (a SURFACE rendering the home — SPEC-0067 Probe-5), so it cannot diverge.
    # T-0861: a -C consumer LACKS the handbook locally (pre-extraction) — bare filenames would point it
    # at missing files. Echo the per-file ENGINE-resolved paths (reuse the T-0860 _kernel_content_file
    # own-wins-else-engine resolver) + a kernel-provided note so the consumer can actually READ
    # CHARTER/AGENTS/LIFECYCLE/QUEUE/GRAPH + voice the anchors. (T-9698: the engine self-start no longer
    # echoes a read-order line at all — it is Phase-1-redundant and RETIRED for the engine; `_render_read_order`
    # still backs the AGENTS.md GEN regions + drift-check, just no longer called here. The consumer read-order
    # echo below STAYS — it carries genuinely-new engine-resolved paths the consumer lacks.) Re-deliver
    # co-design: SPEC-0007 §5b (AGENTS §At-session-start + §After-/compact + the yitc.md twins carry the consumer clause).
    if _is_consumer_build():
        # T-0996 (F-002): the methodology handbook seed resolves ENGINE-ALWAYS via _kernel_handbook_file
        # (NOT _kernel_content_file's own-wins) — a consumer's own CHARTER.md is its PRODUCT charter and
        # must NOT shadow the methodology CHARTER. The label is explicit (audit-pre finding 1). This stays
        # INSIDE the consumer branch; the engine `else` echo below is byte-unchanged (no-regression probe).
        # T-9191: render compactly — state the engine release-view root ONCE as a prefix, then the
        # handbook files by short name (the SAME `<stem>.md` the engine-self echo uses). All paths
        # stay resolvable (root + short name), without repeating the long absolute prefix per file
        # (owner dogfood flag, kupiclub -C session 2026-06-17). The floor-map line below reuses the
        # same root via a "(same engine release-view root)" note rather than re-printing it.
        _hb_root = ENGINE_ROOT / RELEASE_VIEW_DIR
        # T-10097 (SPEC-0127 §4 + SPEC-0074 §7) + T-10216 (SPEC-0007 §5c): audience-aware, from the
        # engine's IDENTITY-AGNOSTIC release-view. Worker: the assembled core+worker seed, IN PLACE OF the
        # full handbook files. Controller: the SOURCE parts DIRECTLY in the read-order
        # (each single-read-safe; no assembled monolith — controller-supplement stays a derived
        # reference view). All named files are cut into the release-view via _release_view_docs
        # (`land` regenerates it, T-9513); the E6 equivalence test asserts their release-view presence.
        # T-10219: the worker seed is a CHAIN of size-bounded parts — echo EVERY part (naming part 1 alone
        # would hand a `-C` Worker a truncated seed). Short names under the ALREADY-stated release-view
        # root, so the root still prints exactly once (the T-9191 compact-echo shape).
        _seed_parts = graph.worker_seed_part_files(ENGINE_ROOT / RELEASE_VIEW_DIR / "graph")
        _views = (" + ".join(f"graph/{p}" for p in _seed_parts)
                  + (" (read ALL parts — the chain IS your seed, SPEC-0120 §3)" if len(_seed_parts) > 1 else "")
                  if _sess_type == "build"
                  else "CHARTER.md + AGENTS.md + AGENTS-SESSIONS.md + AGENTS-PROTOCOL.md + "
                       "LIFECYCLE.md + QUEUE.md + GRAPH.md (source parts, read directly in this order"
                       " — SPEC-0007 §5c)")
        print("read-order (topological — CHARTER first, pedagogical pin) — kernel METHODOLOGY handbook, "
              "kernel-provided (pre-extraction; this -C consumer authors none of it — these are the ENGINE's "
              "files; your own CHARTER.md, if any, is your PRODUCT charter = separate project-context, NOT "
              f"this methodology seed — read your audience seed + voice the anchors). engine release-view ({_hb_root}/): "
              + _views)
        # T-9469: name the consumer's OWN backbone at startup. CONVENIENCE over durable on-disk
        # state; re-derived directly post-`/compact`, never by re-running
        # session start (SPEC-0007 §5b consumer-echo extension). Guarded inside the consumer branch
        # so the engine self-start neither scans nor changes output (no-regression bound).
        # T-9800: the active-spec-COUNT echo was REMOVED from every start (AI-orientation-only, near-
        # zero owner value — the startup-echo=noise class, X-0149/X-0157). The count stays obtainable
        # ON-DEMAND via `<eng> -C <repo> graph query --type spec` (no new mechanism), so nothing is lost.
        # T-10912 (X-0708): the home is RESOLVED through the SPEC-0125 declaration (the shared
        # `init.declared_neutral_home` — the same resolution `adapter_conformance` judges), NOT the
        # hardcoded `CHARTER.md` this echo used to test for. A consumer whose declared home is
        # `AGENTS.md` was silently told NOTHING about its own rules (the exists()-guard swallowed the
        # line), so its project rules went unread. Absence is now STATED, never silent and never a
        # made-up filename.
        _eng_cli = f"{ENGINE_ROOT}/bin/yitc-v2 -C {REPO_ROOT}"
        _home, _home_basis = init.declared_neutral_home(REPO_ROOT)
        if _home is not None:
            print(f"project context (this consumer's OWN — separate from the methodology seed above): its "
                  f"product backbone is {REPO_ROOT / _home} — read it for THIS project's charter/non-goals.")
        else:
            print(f"project context: this consumer declares NO SPEC-0125 operating-context home — no "
                  f"{' / '.join(init.NEUTRAL_HOME_ORDER)} is declared, so there are no OWN project "
                  f"rules to read at start (the methodology seed above is all you have). Declare one "
                  f"via the governed `{_eng_cli} init`.")
        # T-9580: deliver the kernel-signaling reflex to EVERY consumer session (new + already-migrated).
        # The reflex EXISTS engine-side (patterns/error-friction-tracking.md §3 / SPEC-0085 §3, T-9353)
        # but was NEVER surfaced to a consumer — so consumers never learned the marking, and some product
        # CHARTERs even framed the kernel hand-off as owner-gated (the OPPOSITE of the auto-fire). This
        # kernel-RENDERED echo reaches every consumer with NO consumer-repo edit (kernel territory only),
        # which is exactly why the per-charter texts diverged. Wording kept COHERENT with pattern §3: the
        # bugfix subclass auto-fires, a --kind task ask stays owner-gated. CONSUMER-ONLY (the kernel's own
        # land short-circuits realm:kernel to itself, so the auto-route framing is consumer-specific).
        # T-10248 (X-0253): the echo teaches the ENUMERATED `realm`, not the free-text `relates_to` — an
        # echo that keeps teaching the prose carrier is what made the drop believable as a delivery.
        print("kernel-signaling reflex (consumer->kernel, NO owner reminder): when a deviation is an "
              "ENGINE/KERNEL problem, mark it `realm: kernel` + `target: yitc-v2` on capture "
              "(`deviation_captured`) — at your next `land` it AUTO-ROUTES to the kernel as a "
              "`cross request --kind bugfix --to yitc-v2` (idempotent by fingerprint), with NO owner "
              "gate. `realm` is the ENUMERATED routable half (kernel | v2-self | project); your prose "
              "aspect stays in free-text `relates_to` and NEVER routes on its own — a kernel-shaped "
              "aspect with no `realm: kernel` is WARNED at land, not routed (X-0253). The legacy exact "
              "`relates_to: kernel` marker still routes. A kernel FEATURE / improvement ASK "
              "(`--kind task`) stays owner-gated. "
              f"Full: `{graph.spec_query_hint('SPEC-0085', is_consumer=True, cli=_eng_cli)}` / "
              f"patterns/error-friction-tracking.md §3.")
    # T-9698: the ENGINE (non -C) interactive echo is TRIMMED to a lean start. The seed-confirmation
    # cross-check header + read-order repeat (the engine `else` below) AND the CLI-rescan / MEMORY.md /
    # floor-map / lifecycle-stage-entry reminders (the shared block) are ALL Phase-1-redundant for an
    # engine session — it just read the full handbook seed (CHARTER…GRAPH + floor-map + `--help`) in
    # Phase 1 — so they are RETIRED from the engine echo (per-line disposition, NO silent drop). The
    # RETAINED startup-only surfaces (_seed_howto SPEC-0051/0087, _filing_reference_howto SPEC-0060,
    # the cross-coord counts, the resume/await dispatch) still print below for BOTH branches. Post-
    # /compact re-delivery is UNCHANGED — it rides AGENTS §After-/compact prose (re-read, never re-run
    # `session start`), so trimming the fresh-start echo touches no post-compact story (the retained
    # lines keep their own re-derivation). A `-C` CONSUMER is DIFFERENT: it has NONE of the handbook
    # locally, so these lines carry genuinely-NEW engine-resolved info — they STAY, scoped to the
    # consumer branch (the consumer read-order echo above is already its own `if` block, untouched).
    if _is_consumer_build():
        # T-9469: a consumer has NO local bin/yitc-v2 — show the engine `-C` verb-invocation form.
        # T-11409 (X-1049): SHOW the session-ref carry this line mandates. The `--help` fetch-receipt
        # is SESSION-TIED (credited only inside a window anchored by THIS session's `session_started`,
        # gates._require_help_read), so a rescan run without the carry is not credited and the first
        # gated verb refuses — the line that ORDERS the rescan must carry its own precondition.
        print(f"rescan CLI surface: YITC_SESSION_REF={resolved_ref} {ENGINE_ROOT}/bin/yitc-v2 "
              f"-C {REPO_ROOT} --help  (a consumer has no local bin/yitc-v2 — invoke the ENGINE CLI "
              "with -C <path>; the receipt is session-tied, so carry the ref or the scan is not credited)")
        # T-9757: a dispatched WORKER (`--type build`, SPEC-0039 audience `background`) does NOT
        # auto-read the MEMORY.md buffer — its startup read-set is the mandatory handbook seed + the
        # active stage bundle only. The buffer's cross-session-continuity content is controller-
        # oriented (continuation seeds / near-term to-dos) — irrelevant to a task-bounded worker AND a
        # confabulation source (real incident 2026-07-01: a worker read the boomrocket seed and
        # confabulated a FOREIGN-scenario land-halt). So this MEMORY read-nudge fires for the
        # Controller path only. Normative home: SPEC-0039 §0 (worker exemption).
        if _sess_type != "build":
            print("also auto-read project buffer: MEMORY.md (non-authoritative cross-session scratch, SPEC-0007 §6)")
        # T-9191: the floor-map sits at the engine release-view root named once in the read-order line above.
        print("always-loaded seed also: graph/floor-trigger-map.md (same engine release-view root) "
              "(the STAGE-AGNOSTIC before-rule-change trigger — read before authoring/editing a spec)")
        print("lifecycle-scoped content is delivered at STAGE-ENTRY (T-0289): run `yitc-v2 stage <NAME> "
              "--task T-XXXX` to receive that stage's bundle (specs + work-verbs); re-run after /compact")
    print(_seed_howto())
    # T-0602 (SPEC-0059 Filing carve-out): the Filing-stage authoring-doctrine REFERENCE (availability,
    # no gate) — Filing has no `stage` entry verb, so its doctrine surfaces here for BOTH session types
    # (filing happens in Build decomposition AND Review). The `task file` read-check is the CHECK leg.
    _filing_ref = _filing_reference_howto()
    if _filing_ref:
        print(_filing_ref)
        # T-11845: the ONE clause the reference was missing — WHERE the fetch receipt is recorded.
        # The read-gate scans a SINGLE journal, the CURRENT checkout's (gates._fetched_spec_ids), so
        # a `graph query` run in another checkout of the same repo credits nothing here; a worktree's
        # events.jsonl is a branch copy that main's appends reach only at `land`. Homed HERE, on the
        # line that already states the fetch rule, rather than in a second home. The RULE lives here;
        # the ready-to-run COMMANDS live at the `worktree new` filing seam — that seam arrives at the
        # acting moment but is invisible to whoever re-enters an EXISTING worktree or returns after a
        # /compact, while this line is read too early to act on. Each covers what the other cannot.
        print("  ^ the read receipt is recorded in the CHECKOUT WHERE THE COMMAND RAN — fetch from "
              "the checkout you will file from (a run in another checkout of the same repo, e.g. "
              "main while you file from a worktree, does not credit the filing here)")
    # (2b) [REMOVED at the T-9293 cutover] The SPEC-0079 per-repo `cross-log:` inbound COUNT surface was
    # retired here when SPEC-0079 → superseded (replaced by SPEC-0085/0086). Its successor is the (2c)
    # shared-coordination-log fold-view below (`cross-coord:`), which is identity-agnostic and covers both
    # the inbound inbox and the author-side outbox. Cutover invariant (test_t9293_cutover_invariant.py):
    # session start prints NO `cross-log:` line and DOES print the `cross-coord:` surface.
    # (2c) Shared coordination-log surface (SPEC-0086 rule 4, T-9289): report-only fold-view COUNTS over
    # the kernel-owned SHARED coordination log — the author-side OUTBOX (from:me items a peer FINISHED
    # and that now await MY close — "fixed→verify at start", the done-criterion surface) + the inbound
    # INBOX needing a DECISION (T-9400: requested AND not yet tracked by a local task via resolves_cross,
    # NOT the full non-terminal to:me set — done/picked/task-linked items no longer inflate the count;
    # the kernel→consumer intake direction the retired SPEC-0079 §6 once held).
    # The SPEC-0079 §2b inbound count above was REMOVED at the T-9293 cutover (SPEC-0079 superseded); this
    # is now the SOLE cross surface. BOTH session types incl `-C`: the shared log is identity-agnostic (every
    # participant folds the SAME out-of-repo log; self = the STABLE main-checkout id `_cross_self`, not
    # the worktree leaf). Report-only, NO auto-pull (surfacing ≠ queue-scan — the LOG-vs-queue line
    # holds). REUSES cross.fold via the cross.{outbox_awaiting_close,inbox_actionable}_rows predicates (one
    # fold, no second state model — SPEC-0086 rule 2). BOTH surfaces are ACTIONABLE SUBSETS, not the full
    # views: the OUTBOX surface is the done-awaiting-close subset (requested/picked await the receiver;
    # rejected is an FSM terminal — T-9289 audit-pre F1), and the INBOX surface is the needs-decision
    # subset (requested & not task-linked — T-9400); `cross outbox`/`cross inbox` render the full SUPERSETS.
    # Post-`/compact` re-delivery co-designed in AGENTS §After-`/compact` + §Three-phase (SPEC-0007 §5b):
    # re-surface by RE-FOLDING (`cross outbox` / `cross inbox` — both SUPERSET re-folds of their start
    # subset), NOT by re-running session start. INLINED (rides `cross` + `print`, no new startup primitive).
    # `_cross_peer_aliases` is the host-COMPUTED VALUE {alias -> canonical} (T-10260) — referenced,
    # NEVER called, exactly like `_cross_linked_ids` below, so this function gains no new bare-name Call
    # and stays inside the D-0052 F5 startup AST-allowlist. `cross.*` are attribute calls (out of scan).
    # T-12116, WIDENED by T-12207: RECEIPT-ONLY runs skip this fold and the SPEC-0119 debt echo below.
    # `_receipt_only` is the host-COMPUTED VALUE (derived in the residue by `_receipt_only_session_start`
    # — since T-12207 simply: THIS CHECKOUT IS A WORKTREE), injected and REFERENCED here, NEVER called,
    # exactly like `_debt_echo_lines` / `_cross_linked_ids` above — so this function gains NO new
    # bare-name Call and stays inside the D-0052 F5 startup AST-allowlist.
    # WHAT IS SKIPPED, and on what ground: both surfaces are report-only echoes whose session-start seam
    # is the MAIN CHECKOUT (SPEC-0119 rule 2a), and both name their own on-demand re-fold verb (the same
    # verbs AGENTS §After-`/compact` already prescribes). T-12116 justified the skip as RE-DELIVERY (the
    # session had already received the echo on main); T-12207 measured the case that argument does not
    # reach — a FIRST-in-checkout anchor holding no receipt, which paid 7.8s of predicate plus a 28.5s
    # 18-line fold inside a worktree — and re-grounded the skip on AUDIENCE+SEAM instead, the reasoning
    # SPEC-0039 §0 already uses to exempt a dispatched worker from the MEMORY.md buffer.
    # The skip is at the READ: `cross.read_events` below is not called at all, and the residue computes
    # neither `_cross_linked_ids` nor `_cross_peer_aliases`. The downstream rendering then runs over an
    # EMPTY list — deliberate and costless (O(0), prints nothing); guarding it too would add a second
    # condition that buys no time (audit-pre F2, absorbed).
    # NOTHING about the SPEC-0050 seed floor moves — the `session_started` anchor, the audience-seed echo,
    # the posture dispatch and the `cli:seed` receipt emit all run unchanged, which is why a worktree run
    # remains a valid stamp of its own receipt.
    if _receipt_only:
        print("session start: RECEIPT-ONLY — this is a WORKTREE, and the debt echo (SPEC-0119) and the "
              "cross-coord fold (SPEC-0086) are main-checkout session-start surfaces, so both were "
              "SKIPPED here; this checkout's own receipt is still stamped and the seed floor is "
              "unchanged. Neither echo gates anything, the land-tail debt seam is unconditional, and "
              "both re-fold on demand: `bin/yitc-v2 debt` / `bin/yitc-v2 cross outbox` / `cross inbox`.")
    try:
        _coord_events = [] if _receipt_only else cross.read_events(CROSS_LOG_PATH, _cross_peer_aliases)
    except OSError:
        _coord_events = []   # fail-soft — an unreadable shared log must not break/suppress startup
    # == `_cross_self()` (the canonical participant-id home) INLINED here on purpose: the startup
    # AST-allowlist guard (test_session_dispatch.py, D-0052 F5) scans bare-name calls, and a brand-new
    # `_cross_self` call cannot land atomically with its own allowlist entry under SPEC-0077 pinned-verify
    # (the last-green verifier vets the candidate). `_main_worktree` is ALREADY allowlisted read-only, so
    # inlining its one-line body keeps the guard green without a two-phase land. (cross.* fold calls are
    # namespaced attribute calls, out of the bare-name scan.)
    # T-10260: canonicalize the inlined basename to the registry key, else this echo counts a DIFFERENT
    # peer than `cross inbox`/`outbox` do (the X-0259 split — 3 live inbound items counted by neither).
    _coord_self = cross.canonical_peer((_main_worktree(REPO_ROOT) or REPO_ROOT).name, _cross_peer_aliases)
    _coord_outbox_n = len(cross.outbox_awaiting_close_rows(_coord_events, _coord_self))
    # T-9400: the INBOX startup surface is the NEEDS-DECISION subset (requested AND not yet tracked by a
    # local task via resolves_cross), NOT the full non-terminal `to:me` set — done/picked/task-linked
    # items no longer inflate the count. `_cross_linked_ids` is the host-COMPUTED VALUE (the OWN-repo
    # resolves_cross id set), injected by the residue — referenced here, NEVER called, so this function
    # gains NO new bare-name Call and stays inside the D-0052 F5 startup AST-allowlist (the call is in the
    # host residue, which is not AST-scanned — the `_cross_self` inlining precedent, avoiding a two-phase
    # land vs the SPEC-0077 pinned/last-green verifier). None (a caller that omits it) → no link-exclusion;
    # `()` is a tuple literal, no Call. `cross inbox` stays the full SUPERSET re-fold.
    _coord_linked_ids = _cross_linked_ids or ()
    _coord_inbox_n = len(cross.inbox_actionable_rows(_coord_events, _coord_self,
                                                     linked_cross_ids=_coord_linked_ids))
    if _coord_outbox_n:
        print(f"cross-coord: {_coord_outbox_n} outbox item(s) from:{_coord_self} fixed by a peer and "
              f"awaiting YOUR close (fixed→verify) — report-only (a LOG, not a queue, SPEC-0086). "
              f"See `bin/yitc-v2 cross outbox` (then `cross close <id>` once verified).")
    if _coord_inbox_n:
        print(f"cross-coord: {_coord_inbox_n} inbox item(s) to:{_coord_self} needing a decision "
              f"(requested, not yet picked or tracked by a local task) — report-only (SPEC-0086). "
              f"See `bin/yitc-v2 cross inbox` (the full non-terminal SUPERSET).")
    # T-11202 — the ACCEPTED-BUT-UNTRACKED echo, the MIRROR of the needs-decision line above. The
    # T-9400 cut counts an item only while it is `requested` AND untracked, so PICKING one is the act
    # that removes it from the only surface naming it, while LINKING a task — what would restore
    # visibility — is exactly what has not happened; the system is quietest about the items it has
    # already promised to do. Measured 2026-08-16: 8/8 picked items read `task: (none)`, and by this
    # task's Stage 1 the requested cut had fallen to ZERO while six picked items were tracked by
    # nothing — the line above fully silent over a live blind spot. Harm confirmed on X-0595, picked
    # and fully delivered yet left at `picked` with no resolution note, so its reporter was never told
    # (closed by hand ~10 days late). Reuses the SAME single fold, self and linked-id VALUE already in
    # scope — no second read, no new host scan, and no new bare-name Call (the D-0052 F5 startup
    # AST-allowlist is untouched; `cross.*` is an attribute call, out of that scan). Report-only and
    # SUPPRESSED-WHEN-CLEAN like both lines above: no event, no status change, no exit-code move, no
    # auto-pull and no auto-link (a LOG, not a queue — SPEC-0086; linking is a judgement about intent).
    # Names the ids, because the whole point is that going to look is what does not happen. Post-
    # `/compact` re-delivery is the SAME `cross inbox` re-fold the sibling echoes already name.
    _coord_picked_untracked = cross.inbox_picked_untracked_rows(_coord_events, _coord_self,
                                                                linked_cross_ids=_coord_linked_ids)
    if _coord_picked_untracked:
        _picked_ids = ", ".join(it["id"] for it in _coord_picked_untracked)
        print(f"cross-coord: {len(_coord_picked_untracked)} inbox item(s) to:{_coord_self} ACCEPTED "
              f"(picked) but tracked by NO local task — {_picked_ids} — report-only (SPEC-0086). "
              f"Picking removed them from the needs-decision line above; nothing else names them. "
              f"See `bin/yitc-v2 cross show <id>`, then either declare a local carrier — a card "
              f"(`task file … --resolves-cross <id>`) or a non-terminal PLAN's frontmatter "
              f"`resolves_cross:` (T-11585), both of which silence this line — or answer it "
              f"(`cross done`/`cross ack <id>`).")
    # T-10844 read-degrade: ALL THREE echoes above are suppressed-when-clean (T-11202 added the third),
    # so a coordination item lost to a line a concurrent peer append tore mid-JSON would leave this surface silent and indistinguishable
    # from a genuinely clean fold. Name the loss on the SAME single read (`cross.*` is an attribute call,
    # outside the D-0052 F5 startup bare-name AST allowlist — no allowlist entry needed). Report-only.
    _coord_damaged = cross.unparseable_count(_coord_events)
    if _coord_damaged:
        print(f"cross-coord: WARN — {_coord_damaged} unparseable line(s) in the shared coordination log "
              f"({CROSS_LOG_PATH}) were skipped, so the counts above may be MISSING item(s) and their "
              f"silence does NOT mean clean (SPEC-0084 r4). Re-fold with `bin/yitc-v2 cross inbox` / "
              f"`cross outbox` for the detail.")
    # (2d) Proactive-debt echo (SPEC-0119 / T-9754): the 3 DERIVED debt views (not-adopted /
    # open-followups / overdue-rechecks) surfaced report-only beside the cross-coord echo,
    # SUPPRESSED-WHEN-CLEAN. `_debt_echo_lines` is the host-COMPUTED VALUE (a list of already-rendered
    # `debt: …` lines), injected by the residue — REFERENCED here, NEVER called, so this function gains
    # NO new bare-name Call and stays inside the D-0052 F5 startup AST-allowlist (the `_cross_linked_ids`
    # value-injection precedent, avoiding a two-phase land vs the SPEC-0077 pinned/last-green verifier).
    # None (a caller that omits it) → no debt surface. The post-`/compact` re-fold is `bin/yitc-v2 debt`
    # (AGENTS §After-`/compact`) — this echo is evicted like the cross-coord echo, re-surfaced by re-fold.
    for _debt_ln in (_debt_echo_lines or ()):
        print(_debt_ln)
    # (3) Posture-dispatch (per D-0052, amended T-9698): a NON-MUTATING startup SUMMARY. The
    # Build|Review interactive type CHOICE is retired (T-9697 / CHARTER §6) — `--type build` is the
    # dispatched Worker (build-framed resume-or-await); NO `--type` is the interactive Controller
    # (the SAME resume-or-await, framed as controller + a lean posture line). Reads/reports only;
    # never changes task status/stage (the FSM/enforcement creep CHARTER non-goal #7 forbids).
    if args.type == "build":
        _session_build_dispatch()
    else:
        _session_controller_dispatch(acting_holder=_acting_holder)
    # T-10246: hand the AUTHORITATIVE id back to the caller. The host residue passes it straight to the
    # `cli:seed` receipt emit, so the receipt is stamped under the SAME ref the `session_started` anchor
    # above was emitted under — one id for both gate-bearing emits, by construction rather than by two
    # independent derivations happening to agree (they did not, inside a stamped worktree).
    # T-10318: hand its `source_kind` back alongside — the same reason, one field wider. The receipt then
    # records the selector that actually produced the id (`arg` | `env:<carrier>` | `worktree_stamp` |
    # `minted_self_ref`), rather than the residue re-deriving one or collapsing to `explicit`.
    return resolved_ref, source_kind


def _print_task_resume(t: dict, label: str = "build") -> None:
    """Print a task's resume contract (the non-mutating resume report). Factored (T-0140) so the
    branch-identified resume and the single-in-progress resume share one shape. T-9698: `label`
    frames the line per posture (controller|build) — the interactive Controller resumes own work
    too (resume triggers off worktree/own-stamp STATE, not the type label)."""
    print(f"{label}: RESUME in-progress {t.get('id')} — {t.get('title') or '(no title)'}")
    print(f"  stage={t.get('current_stage') or '?'} | resume_from={t.get('resume_from') or 'start'}")
    if t.get("next_action"):
        print(f"  next_action: {t.get('next_action')}")
    print("  (read-only report — the verb did NOT resume/mutate; continue the task yourself)")


def _print_await(label: str, show_posture: bool) -> None:
    """T-9698: the await-owner line + (for the interactive Controller) the lean posture line. The
    posture line is the read-leaning, dispatch-by-default reminder the retired _session_review_dispatch
    carried — kept LEAN (NO 9-stage enumeration; the executing flow detail is the Worker's, homed in
    LIFECYCLE, not spelled out at the start moment). A Worker (show_posture=False) gets the bare await."""
    print(f"{label}: {label.capitalize()} ready — awaiting owner cue (which task to take/resume).")
    if show_posture:
        print("  read-leaning start-posture, broad across projects — DEFAULT is dispatch-by-default: "
              "delegate the batch to background Build workers (Orchestrate posture); self-execute a "
              "task yourself only on owner say-so. Weekly audits are owner-invoked.")


def _waiting_on_owner_lines(*, TASKS_DIR, _read_yaml, _awaits_arrived=None) -> list:
    """T-0381: the read-only WAITING-ON-OWNER surfacing — in-progress tasks paused with
    reason==owner-wait + paused_at set. Closes the run-9 gap (a halted owner-wait task looked
    like ordinary concurrent work from main; parent plan to-fix #8). The DURABLE acceptance-#1
    state-check is the committed paused_reason/paused_at in the task YAML on main (grep / `task
    list`) — session-type independent; these startup lines are the convenience surfacing over
    that same committed state. Called by BOTH the build AND review startup dispatch (audit-pre
    F2 — a fresh non-build session also reads main).

    T-12407 GENERALISED IT FROM ONE REASON TO ONE QUESTION — «what ends this wait, and has it
    happened?» The pre-T-12407 body selected on `paused_reason == "owner-wait"` and read NO artifact
    state, so a card whose awaited item had ALREADY closed kept printing WAITING-ON-OWNER forever:
    measured on kupiclub X-1322, where T-0422 advertised a wait for 8 days after the item it actually
    awaited was terminal, and three sessions read that line and believed it. A line that can be WRONG
    about the thing it exists to report is worse than no line.

    So a card that DECLARES what it awaits (`task pause --awaits` → `paused_awaits`) has its wait
    RESOLVED here rather than asserted. `_awaits_arrived` is an INJECTED pure predicate
    `(ref) -> (arrived: bool, at: str|None)`, built by the host from the readers that already decide
    this question elsewhere (`followup.arrived_ids` + `event_after_arrived`, the pair
    `views._deferred_probe_due` composes) — this leaf learns nothing about where the journal, the
    task corpus or the shared coordination store live.

    TWO INVARIANTS, both load-bearing:
      (1) A card WITHOUT `paused_awaits` renders BYTE-IDENTICALLY to the pre-T-12407 line. That is the
          whole existing population, and `tests/test_t0381_task_pause_resume.py` pins it.
      (2) The resolver FAILS OPEN TO «not arrived» — an absent injection, an unreadable store, an
          unclassifiable ref all leave the card reading WAITING. A false WAITING is visible and one
          command from disposition; a false RESUMABLE tells an operator to re-enter work that is
          still blocked, which is the very assertion-without-evidence this change removes. The
          direction is the same one `_terminal_cross_ids` fails in, for the same reason."""
    out = []
    for p in state.scan_tasks(TASKS_DIR):
        # T-12030 — ask the STATUS first, and read the card only for the ones this view can report.
        # The subject here is `in-progress` cards alone, so materialising all 3,319 cards (a deepcopy
        # each, done cards included) to find them is a read this view never needed. `card_is_open` is
        # a view over the SAME memo `_read_yaml` fills — no second parse path — and it fails SAFE: an
        # unreadable or status-less card still reaches the guards below exactly as before, so this
        # can narrow the READ without ever narrowing the ANSWER.
        if not state.card_is_open(p):
            continue
        d = _read_yaml(p)
        if not isinstance(d, dict) or not d.get("id"):
            continue
        reason = d.get("paused_reason") or ""
        if (d.get("status") or "") != "in-progress" or not d.get("paused_at") \
                or reason not in ("owner-wait", "artifact-wait"):
            continue
        tid, title = d.get("id"), d.get("title") or "(no title)"
        awaits = d.get("paused_awaits")
        # The UNDECLARED case, unchanged char-for-char (invariant 1 above). `artifact-wait` cannot
        # reach it — the verb refuses that reason without an `--awaits` — so this branch stays the
        # owner-wait line it has always been.
        if not awaits:
            line = f"  WAITING-ON-OWNER {tid} — {title} (paused {d.get('paused_at')}"
            if d.get("next_action"):
                line += f"; next: {d.get('next_action')}"
            out.append(line + ")")
            continue
        arrived, at = False, None
        if _awaits_arrived is not None:
            try:
                arrived, at = _awaits_arrived(awaits)
            except Exception:
                arrived, at = False, None   # fail-open to WAITING (invariant 2)
        if arrived:
            # `closed <ts>` ONLY where the reader actually HAS a timestamp. A terminal task carries
            # its `closed_at`; a coordination item's fold carries a status and no terminal ts, and
            # inventing one — or standing up a second terminality scan to find it — would be a
            # fabricated field or a second source of truth (CHARTER §P5) for a cosmetic gain.
            line = f"  RESUMABLE {tid} — {title} — awaited {awaits} closed" \
                   + (f" {at}" if at else "") + f" (paused {d.get('paused_at')}"
        else:
            line = f"  WAITING-ON-{'ARTIFACT' if reason == 'artifact-wait' else 'OWNER'} {tid} — " \
                   f"{title} — awaits {awaits} (open) (paused {d.get('paused_at')}"
        if d.get("next_action"):
            line += f"; next: {d.get('next_action')}"
        out.append(line + ")")
    return out


def _controller_acting_holder(*, REPO_ROOT, TASKS_DIR, _read_yaml, _run_git_cap,
                              _read_worktree_stamp, _stamp_is_own, _session_proc_alive) -> "str | None":
    """PURE READER (T-12306): the CONFIRMED-DEAD holder ref of THIS task worktree, else None.

    Returns a session_ref ONLY when every condition holds: this checkout is a `task/T-NNNN`
    worktree, that card is `in-progress`, the worktree stamp is FOREIGN (`not _stamp_is_own`), the
    stamp carries a non-empty `session_ref`, and `_session_proc_alive(ref)` is False — the SAME
    SPEC-0133 confirmed-dead predicate `worktree recover-land` uses on its axis 2 (reused, never a
    second one). Everything else — an unstamped or ref-less worktree, a live holder, any read
    failure — returns None, so the T-0362 BLOCK leg is what happens by default (fail-closed).

    NO write, NO emit, NO re-stamp: this only lets the Controller's startup ECHO say «acting in»
    where it used to say «do NOT continue this task here». Admission is keyed on the STAMP, which
    this never touches, so the execution verbs keep refusing exactly as before — adopting is still
    the explicit `worktree adopt --confirm-dead`, out of this seam's scope.
    """
    try:
        br = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], REPO_ROOT).stdout.strip()
        m = re.fullmatch(r"task/(T-\d{4,})", br)
        if not m:
            return None
        tid = m.group(1)
        status = None
        for path in state.scan_tasks(TASKS_DIR):
            if not state.card_is_open(path):
                continue
            d = _read_yaml(path)
            if isinstance(d, dict) and d.get("id") == tid:
                status = (d.get("status") or "")
                break
        if status != "in-progress":
            return None
        stamp = _read_worktree_stamp(REPO_ROOT)
        if not isinstance(stamp, dict) or _stamp_is_own(stamp):
            return None
        ref = (stamp.get("session_ref") or "").strip()
        if not ref or _session_proc_alive(ref):
            return None
        return ref
    except Exception:
        # Fail-closed: an unreadable card / stamp / git head is NOT proof of death — BLOCK stands.
        return None


def _session_build_dispatch(*, TASKS_DIR, _read_yaml, _waiting_on_owner_lines, _run_git_cap,
                            REPO_ROOT, _read_worktree_stamp, _stamp_is_own, _print_task_resume,
                            _main_worktree, EVENTS_PATH, _foreign_hold_report,
                            label="build", show_posture=False, acting_holder=None) -> None:
    """NON-MUTATING resume-or-await startup report (per D-0052 Phase 3 + T-0510; concurrency-aware
    per D-0083 §4). T-9698: ONE resume-or-await body serves BOTH postures — `label` frames every
    line ("build" for the dispatched Worker, "controller" for the interactive Controller) and
    `show_posture` adds the lean Controller posture line on the await paths (the read-leaning
    posture that the retired _session_review_dispatch used to carry). The resume halves are posture-
    INDEPENDENT: they trigger off worktree/own-stamp STATE, so the Controller resumes own work too.

    Reads tasks/ and REPORTS — never mutates status/stage/anything. **No auto-picker (T-0510):**
    the dispatch stops auto-scanning the queue after startup; it only RESUMES work you
    already own, otherwise it awaits an explicit owner cue. This AMENDS D-0052's resume-or-pick
    (the `pick` half is superseded-in-part by AGENTS §Three-phase startup). Resolution order
    (precedence is unambiguous — the own-stamp / foreign branch check runs FIRST and RETURNS before
    any count logic, so a NEW-task posture never suppresses an own-stamped resume):
      - **branch-identified resume (own-stamp only, T-0362)** — if THIS checkout is a `task/T-XXXX`
        worktree and that task is in-progress, resume THAT task ONLY when the worktree's session
        stamp is THIS session's; a FOREIGN- or un-stamped worktree is NEVER auto-resumed — the
        report BLOCKS with «already held by session X (last journal event T)» (advisory liveness
        from the existing journal; adoption is explicit, never auto). Resume is otherwise
        regardless of how many OTHER tasks are in-progress (each foreign in-progress task is held
        by another concurrent session's worktree — D-0083).
      - else by `status: in-progress` count: 1 → resume it (resume of existing work, NOT a
        queue-scan); **0 or >1 → await an owner cue, NO candidate** (>1 first prints a brief
        concurrent note — D-0083). The pre-T-0510 picker (ready scan / live-claim exclusion / PICK /
        next-ready) is REMOVED.
    Reuses existing read-only primitives only (_read_yaml / TASKS_DIR / _run_git_cap). NO capacity /
    monitor-arm / release-debt / aggregate-counter logic — the v1 continuation-rehydrate battery
    D-0052 EXPLICITLY does not import."""
    tasks = []
    for p in state.scan_tasks(TASKS_DIR):
        # T-12030 — the same open-only narrowing as `_waiting_on_owner_lines` above, and for the same
        # reason: EVERY use of `tasks` below is about non-terminal work (the `in-progress` count, the
        # branch-identified resume, which checks `in-progress` before resuming). A done card could
        # never have changed an outcome here, so skipping the read of 3,319 of them changes nothing
        # but the time. Fail-safe in the same direction — an unreadable card is still read.
        if not state.card_is_open(p):
            continue
        d = _read_yaml(p)
        if isinstance(d, dict) and d.get("id"):
            tasks.append(d)
    in_progress = [t for t in tasks if (t.get("status") or "") == "in-progress"]
    # T-0381: surface owner-wait paused tasks FIRST (a halted owner-wait task is otherwise
    # indistinguishable from active concurrent work — run-9 gap, parent plan to-fix #8).
    for ln in _waiting_on_owner_lines():
        print(f"{label}:" + ln)
    # Branch-identified resume (D-0083 §4): cwd-independent read of THIS checkout's branch.
    br = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], REPO_ROOT).stdout.strip()
    m = re.fullmatch(r"task/(T-\d{4,})", br)
    if m:
        bt = next((t for t in tasks if t.get("id") == m.group(1)), None)
        if bt and (bt.get("status") or "") == "in-progress":
            # T-0362: resume ONLY an OWN-stamped worktree. FOREIGN/UNKNOWN → BLOCK report (still
            # read-only — this verb never mutates): presence alone is NOT orphanhood (the
            # 2026-06-05 T-0351 double-claim — a live hold read as a resumable orphan).
            stamp = _read_worktree_stamp(REPO_ROOT)
            if _stamp_is_own(stamp):
                _print_task_resume(bt, label)
                return
            # T-12306: a Controller startup whose foreign holder is CONFIRMED DEAD reports the
            # hold instead of BLOCKing it. `acting_holder` is computed ONCE by
            # `_controller_acting_holder` before the `session_started` emit and handed in, so the
            # printed line and the recorded key cannot disagree; it is re-matched against THIS
            # stamp's ref here so a stamp that changed between the two reads falls back to BLOCK.
            # A Worker never passes it (`--type build`), and a LIVE holder never produces one — both
            # take the T-0362 BLOCK below, byte-unchanged. Nothing is adopted, resumed or stamped.
            if acting_holder and acting_holder == ((stamp or {}).get("session_ref") or "").strip():
                print(f"{label}: acting in {m.group(1)} (holder {acting_holder} confirmed dead; "
                      f"task NOT resumed — ceiling/audit verbs admitted, execution verbs still refuse)")
                print("  (read-only report — the verb did NOT adopt/resume/mutate; the worktree "
                      "stamp is unchanged, so every execution verb still refuses on it)")
                return
            main_wt = _main_worktree(REPO_ROOT)
            journals = [EVENTS_PATH, (main_wt / "events.jsonl") if main_wt else None]
            print(f"{label}: BLOCK — " + _foreign_hold_report(m.group(1), stamp, journals, REPO_ROOT))
            print("  (read-only report — the verb did NOT resume/mutate; do not continue this task here)")
            return
        # branch's task not in-progress / not found → fall through to the count logic (rare edge).
    if len(in_progress) == 1:
        _print_task_resume(in_progress[0], label)
        return
    if len(in_progress) > 1:
        # D-0083 §4: concurrent sessions make >1 in-progress NORMAL (foreign tasks, each held by
        # another worktree). From a non-task checkout we own none → NOTE the concurrency, then
        # await an owner cue (T-0510 — no auto-pick of a NEW ready task; resume of an OWN task is
        # already handled by the branch-identified path above, which returns before reaching here).
        ids = ", ".join(t.get("id") or "?" for t in in_progress)
        print(f"{label}: {len(in_progress)} task(s) in-progress in other sessions ({ids}) — concurrent, "
              f"not a dissonance (D-0083); none owned here.")
        _print_await(label, show_posture)
        return
    # 0 in-progress, non-task checkout: NO auto-picker (T-0510 — stop auto-scanning the queue after
    # startup; this AMENDS D-0052's resume-or-pick, the `pick` half now superseded-in-part by
    # AGENTS §Three-phase startup). The session awaits an explicit owner cue rather than scanning
    # `tasks/` for a ready candidate; the owner then claims via `yitc-v2 worktree new --task T-XXXX`
    # (the worktree creation IS the claim, T-0124 / D-0037 option B).
    _print_await(label, show_posture)


# _session_review_dispatch RETIRED (T-9698): the Build|Review interactive type CHOICE is gone
# (T-9697 / CHARTER §6). Its read-leaning start-posture reminder folds into the lean Controller
# posture line (_print_await show_posture=True); its waiting-on-owner surfacing + await line are
# already in _session_build_dispatch, which now serves BOTH the Worker (label="build") and the
# Controller (label="controller", via _session_controller_dispatch). One resume-or-await body, two
# posture framings — a REMOVAL + reuse, not a parallel path (CHARTER §P1 F3).


# ── session context — the context-window utilization sensor (SPEC-0115) ──────────────────────────
# Read-only, deterministic, PRINT-ONLY (emits NO journal event — SPEC-0115 §8). The SINGLE
# parse+compare home (§1); the seam verbs (T-9707) reuse context_tail_for_current_session(), they
# never re-parse. A LEAF: it calls no seam verb, so there is no recursion (§7).

def _context_occupancy(path):
    """Last-completed-turn occupancy from a provider transcript. Walk the jsonl, keep the LAST record
    carrying a message.usage dict (a completed assistant turn), then extract its token classes via the
    SINGLE parser views.usage_token_classes (P5). occupied = the INPUT-SIDE classes only (input +
    cache_read + cache_write_5m + cache_write_1h) — what the window carries into the next turn; the
    last turn's own output is excluded by design (SPEC-0115 §2; the ≤1-turn gap §3 names + accepts).
    Returns {occupied, model} or None when there is no transcript / no completed turn (§3)."""
    if path is None or not Path(path).exists():
        return None
    last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") or {}
                u = msg.get("usage")
                if isinstance(u, dict):
                    last = (msg.get("model") or "unknown", u)
    except OSError:
        return None
    if last is None:
        return None
    model, u = last
    c = views.usage_token_classes(u)
    occupied = (c["input_tokens"] + c["cache_read_tokens"]
                + c["cache_write_5m_tokens"] + c["cache_write_1h_tokens"])
    return {"occupied": occupied, "model": model}


def session_epoch(session_ref, *, _session_log_path) -> int:
    """The current CONTEXT EPOCH of a session (T-10082, SPEC-0050 §8): the count of `/compact`
    boundaries recorded in the provider transcript so far — 0 at a fresh session, +1 per compaction.
    A monotonic integer signal (NOT a timestamp) the seed-read gate compares against the epoch stamped
    on a seed_read receipt at emit: a receipt from an EARLIER epoch (a pre-compact read) no longer
    credits, forcing a post-compact re-read + `session start` refresh.

    Derived from the SAME best-effort provider log `session context` reads (`_context_occupancy`): the
    Claude Code transcript writes one `{"type":"system","subtype":"compact_boundary",...}` record per
    compaction. Cheap: a substring pre-filter (`compact_boundary` is rare) then json-validate ONLY the
    candidate lines (so a user message that merely contains the literal string is not miscounted).

    FAIL-SAFE (mirrors `_context_occupancy`'s broad-except contract): no transcript / unreadable /
    parse hiccup → 0. The gate must never break a governed verb on a provider-log quirk — 0 is the
    honest "no compaction observed" floor (it can only UNDER-count, which fails toward crediting a
    present receipt, never toward a spurious stale-refusal)."""
    try:
        path = _session_log_path(session_ref)
        if path is None or not Path(path).exists():
            return 0
        n = 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"compact_boundary"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "system" and rec.get("subtype") == "compact_boundary":
                    n += 1
        return n
    except Exception:
        return 0


def _context_measure(path, cfg):
    """Compare occupancy against the configured per-model window + refresh threshold (SPEC-0115 §4/§5).
    Returns a structured measurement: state ∈ {ok, no_turn}; window None ⇒ unknown (verdict suppressed,
    never guessed — mirrors the pricing table's unpriced-model discipline).

    T-10495: window None has TWO causes and the LINE must not conflate them — an empty cfg means the
    config was never READ, which is not evidence that the model is unmapped. Carry `cfg_read` so the
    reader (_context_line) owns that missing-value judgement instead of the shared branch answering it
    once, centrally, and getting one of the two cases wrong (lessons/fail-closed-belongs-to-the-reader-
    not-the-parser.md).

    T-10749 (X-0588, boomrocket): a session whose model is ABSENT from the `context_window` map cannot
    be measured — but this function used to report it as `state: "ok"` with `verdict: None`, i.e. the
    only two machine-readable fields a consumer has BOTH read as "measured, and not over the bound".
    That is how the threshold went dark for an hour with nothing saying so, leaving AI self-estimation
    (SPEC-0114 forbids relying on it) as the only signal — off by ~380K tokens. The reader-not-parser
    lesson above catches this from its other end: a parser may stay neutral, but it must never ASSERT
    an answer it does not have. So every non-measurement now says so IN BAND: `state: "no_data"`,
    `verdict: "no-data"`, and a machine-readable `no_data_reason` naming WHICH cause. `window`/`pct`
    stay None — the SPEC-0115 §5 "NEVER guessed" clause is unchanged; a fallback default window would
    reintroduce exactly the confidently-wrong number this defect cost us."""
    cfg = cfg if isinstance(cfg, dict) else {}
    cfg_read = bool(cfg)
    windows = cfg.get("context_window") or {}
    threshold = cfg.get("context_refresh_threshold_pct")
    if not isinstance(threshold, (int, float)):
        threshold = 55
    occ = _context_occupancy(path)
    if occ is None:
        # `state: "no_turn"` is kept as the (single) reader-facing discriminator _context_line
        # branches on; the no-data marks ride ALONGSIDE it so every unmeasured state answers the
        # same machine question the same way.
        return {"state": "no_turn", "verdict": "no-data", "no_data_reason": "no-completed-turn"}
    model = occ["model"]
    window = windows.get(model) if isinstance(windows, dict) else None
    if not isinstance(window, (int, float)) or window <= 0:
        return {"state": "no_data", "occupied": occ["occupied"], "model": model,
                "window": None, "pct": None, "verdict": "no-data", "threshold": threshold,
                "cfg_read": cfg_read,
                "no_data_reason": "model-unmapped" if cfg_read else "config-unread"}
    pct = round(occ["occupied"] * 100.0 / window, 1)
    verdict = "refresh due" if pct >= threshold else "ok"
    return {"state": "ok", "occupied": occ["occupied"], "model": model,
            "window": window, "pct": pct, "verdict": verdict, "threshold": threshold}


def _ktok(n):
    """Token count → compact 'NNNK' (whole-K at/above 1000, exact below)."""
    return f"{n / 1000:.0f}K" if n >= 1000 else str(n)


def _context_line(m):
    """The one-line human string for a measurement (SPEC-0115 §1 output).

    An UNMAPPED model is fail-VISIBLE (T-10489): the measure still fails SAFE (window/pct/verdict stay
    None — never guessed), but the LINE names the model + the config key to map it, because a silently
    suppressed verdict silently disables the SPEC-0114 refresh proposal (claude-fable-5 ran unmapped for
    a full day at ~66% occupancy and never proposed a refresh).

    An UNREADABLE config is a DIFFERENT state and says so (T-10495): with no config there is no evidence
    about ANY model, so blaming the live model — and pointing the reader at a config key that is very
    likely already correct — is a false accusation, not a fail-visible warning. Both stay fail-VISIBLE;
    they just name the fault that is actually there."""
    if m.get("state") == "no_turn":
        return "context: unavailable — no completed turn"
    if m.get("window") is None and not m.get("cfg_read", True):
        return (f"context: {_ktok(m['occupied'])} tokens / window: unknown — "
                f"WARN: the model-config (bin/pricing-config.yaml) could not be READ, so no model window "
                f"resolves and the refresh-due verdict is SUPPRESSED; the live model "
                f"('{m['model']}') is NOT necessarily unmapped")
    if m.get("window") is None:
        return (f"context: {_ktok(m['occupied'])} tokens / window: unknown — "
                f"WARN: model '{m['model']}' is not mapped in context_window "
                f"(bin/pricing-config.yaml); the refresh-due verdict is SUPPRESSED until it is added")
    return (f"context: {_ktok(m['occupied'])} / {_ktok(m['window'])} tokens "
            f"({m['pct']}%) — {m['verdict']} (threshold {m['threshold']}%)")


def _load_pricing_cfg(_kernel_content_file, _read_yaml, ENGINE_ROOT=None):
    """Load the engine-owned pricing/model config (SPEC-0115 §5 config home). `{}` ⇒ NOT READ.

    T-10495: `bin/pricing-config.yaml` is engine-owned DATA, so it is resolved from ENGINE_ROOT when the
    own path is absent. `_kernel_content_file` alone is NOT enough at the LAND TAIL: `-C <worktree> land`
    rebinds REPO_ROOT to the worktree, `_land_integrate` REMOVES that worktree, and only THEN prints the
    §7 seam tail — so the own path is a directory that no longer exists. Its ENGINE_ROOT fallback fires
    only for a CONSUMER build, and an engine worktree is correctly not one (same git common-dir, T-0952 —
    a verdict already CACHED from before the removal). The config therefore read as `{}` and EVERY model
    landed in the unmapped branch below, printing a WARN that blamed a model the config maps fine.
    ENGINE_ROOT is captured at import and never rebound by `-C`, so it survives the removal."""
    cfg_path = _kernel_content_file("bin/pricing-config.yaml")
    if not cfg_path.exists() and ENGINE_ROOT is not None:
        engine_cfg = Path(ENGINE_ROOT) / "bin" / "pricing-config.yaml"
        if engine_cfg.exists():
            cfg_path = engine_cfg
    return _read_yaml(cfg_path) if cfg_path.exists() else {}


def current_context_pct(*, _provider_session_ref, _session_log_path,
                         _kernel_content_file, _read_yaml, ENGINE_ROOT=None) -> "float | None":
    """The current session's context-window occupancy PERCENT (SPEC-0115), or None when it cannot be
    measured (no completed turn / unknown model window / any read hiccup). Reuses the SINGLE sensor
    (_context_measure) — no re-parse. Best-effort by contract (T-10121): the caller (the stage_entered
    ctx_pct capture) OMITS the field on None; this never raises.

    T-10137: the transcript path is resolved from the PROVIDER session id (`_provider_session_ref`), NOT
    the read-gate discriminator — the minted/self ref names no transcript. None (provider-less) → the
    sensor fail-safes to None."""
    try:
        cfg = _load_pricing_cfg(_kernel_content_file, _read_yaml, ENGINE_ROOT)
        path = _session_log_path(_provider_session_ref())
        m = _context_measure(path, cfg)
        pct = m.get("pct")
        return pct if isinstance(pct, (int, float)) else None
    except Exception:
        return None


def current_context_no_data_reason(*, _provider_session_ref, _session_log_path,
                                    _kernel_content_file, _read_yaml, ENGINE_ROOT=None) -> "str | None":
    """WHY the current session has no context percent — `"model-unmapped"` / `"config-unread"` /
    `"no-completed-turn"` — or None when a real percent exists (T-10749, X-0588).

    The narrow companion to `current_context_pct`, and deliberately a second VIEW over the SAME single
    sensor (`_context_measure`), never a second parse — SPEC-0115 §1 keeps one parse+compare home.
    It exists because `current_context_pct` answers "what percent?" with None for three different
    reasons, so its caller can only omit the field silently; with this the caller can report NO-DATA
    and say which cause, instead of being indistinguishable from a session comfortably below the
    bound. `current_context_pct`'s own "percent or None" contract is deliberately UNCHANGED.

    Best-effort by the same contract as its sibling: never raises; an unreadable transcript or any
    hiccup degrades to the honest `"no-completed-turn"` floor rather than a fabricated reason."""
    try:
        cfg = _load_pricing_cfg(_kernel_content_file, _read_yaml, ENGINE_ROOT)
        path = _session_log_path(_provider_session_ref())
        m = _context_measure(path, cfg)
        if isinstance(m.get("pct"), (int, float)):
            return None
        reason = m.get("no_data_reason")
        return reason if isinstance(reason, str) else "no-completed-turn"
    except Exception:
        return "no-completed-turn"


def context_tail_for_current_session(*, _provider_session_ref, _session_log_path,
                                     _kernel_content_file, _read_yaml, ENGINE_ROOT=None):
    """The seam-reuse entry (SPEC-0115 §7) the T-9707 seam verbs CALL to print their one-line tail —
    the SINGLE compute home, so the seam verbs never re-parse. Returns the line string (always a line;
    a no-turn / unknown-window case still yields its honest line).

    T-10137: the transcript path keys on the PROVIDER session id (`_provider_session_ref`), decoupled
    from the read-gate discriminator (which is now the minted/self ref that names no transcript).

    T-10495: ENGINE_ROOT is passed through to the config load — THIS is the land-tail caller, and by the
    time land prints the tail it has already removed the worktree REPO_ROOT points at."""
    cfg = _load_pricing_cfg(_kernel_content_file, _read_yaml, ENGINE_ROOT)
    path = _session_log_path(_provider_session_ref())
    return _context_line(_context_measure(path, cfg))


def cmd_session_context(args, *, _provider_session_ref, _session_log_path,
                        _kernel_content_file, _read_yaml, ENGINE_ROOT=None) -> None:
    """`session context [transcript]` — print the current session's (or an explicit transcript's)
    context-window occupancy + threshold verdict. Read-only, deterministic, PRINT-ONLY (no journal
    event — SPEC-0115 §8); exits 0. A LEAF — calls no seam verb (recursion guard, §7).

    T-10137: the current-session transcript path keys on the PROVIDER session id (`_provider_session_ref`),
    decoupled from the read-gate discriminator (the minted/self ref names no transcript)."""
    cfg = _load_pricing_cfg(_kernel_content_file, _read_yaml, ENGINE_ROOT)
    explicit = getattr(args, "transcript", None)
    path = Path(explicit) if explicit else _session_log_path(_provider_session_ref())
    print(_context_line(_context_measure(path, cfg)))


def _default_startup_check_run(command, cwd) -> bool:
    """Run a declared startup-check command; return True iff it FLAGS (non-zero exit). Cheap + fail-safe:
    a short timeout, shell string, cwd=repo root, output discarded. A launch error / timeout is treated
    as NOT-flagged (a broken or slow check must never NAG the report-only echo — the SPEC-0119 rule-1
    never-nag-on-the-unknown principle). A command-not-found returns 127 (non-zero) → flags, a truthful
    "this check could not confirm clean"."""
    import subprocess
    try:
        r = subprocess.run(command, shell=True, cwd=str(cwd), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        return r.returncode != 0
    except Exception:
        return False


def startup_check_lines(repo_root, _read_yaml, *, _run_check=None) -> list:
    """SPEC-0152 rule 17 / SPEC-0119 rule 7 (T-10049, X-0191) — the OPT-IN consumer startup-check echo.

    Reads `<repo_root>/yitc-ops.yaml` `startup_checks:` (a list of {label, command, detail}), RUNS each
    declared cheap report-only command, and returns ONE aggregated REPORT-ONLY line — count + per-check
    `label (detail)` — when any check FLAGS (non-zero exit), else `[]` (SUPPRESSED-WHEN-CLEAN). It is
    APPENDED to the SPEC-0119 debt-echo output by the host residue (`_debt_echo_lines`), so it inherits
    the 3 seams (session-start / land-tail / `debt` re-fold) + suppression verbatim — no new mechanism.

    TOKEN-FRUGAL: count + pointer only, never the checks' stdout. BEST-EFFORT / fail-safe: an absent
    carrier or section, a malformed entry, an unreadable file, or a command that errors/times-out is
    SKIPPED — a report-only surface must never break startup (SPEC-0152 rule 17 fail-safe reader). The
    engine's own repo has no `yitc-ops.yaml`, so this returns `[]` there. `_run_check(command, cwd) ->
    bool` (True iff the check FLAGS) is injected for tests; the default is `_default_startup_check_run`."""
    try:
        ops_path = Path(repo_root) / "yitc-ops.yaml"
        if _read_yaml is None or not ops_path.exists():
            return []
        ops = _read_yaml(ops_path)
        checks = ops.get("startup_checks") if isinstance(ops, dict) else None
        if not isinstance(checks, list):
            return []
        run = _run_check or _default_startup_check_run
        flagged = []
        for c in checks:
            if not isinstance(c, dict):
                continue
            label = c.get("label")
            command = c.get("command")
            detail = c.get("detail")
            if not (isinstance(label, str) and label.strip()
                    and isinstance(command, str) and command.strip()):
                continue                                  # malformed entry → skip (fail-safe, un-swept)
            try:
                flags = run(command, Path(repo_root))
            except Exception:
                continue                                  # a broken runner never breaks the echo
            if flags:
                ptr = detail.strip() if isinstance(detail, str) and detail.strip() else "no pointer"
                flagged.append(f"{label.strip()} ({ptr})")
        if not flagged:
            return []
        return ["startup-check: " + str(len(flagged)) + " declared check(s) flagged — "
                + "; ".join(flagged)
                + ". Report-only (yitc-ops.yaml startup_checks; SPEC-0093 r17 / SPEC-0119)."]
    except Exception:
        return []


def frontend_error_echo_lines(repo_root, _read_yaml, fe, *, as_of, cli_hint,
                              _read_rows=None, events_path=None,
                              carrier_events_path=None) -> list:
    """SPEC-0171 (T-10776) — the CONSUMER session-start frontend-error ECHO, report-only and
    SUPPRESSED-WHEN-CLEAN. The delivery half of the SPEC-0170 conveyor.

    Reads THIS repo's `yitc-ops.yaml` adoption of SPEC-0170 (`extensions.adopts[]`, the declaration
    T-10774/T-10775 already gate — no second declaration path), folds the declared source READ-ONLY
    into confirmed clusters and returns AT MOST ONE line. Three outcomes, and the middle one is the
    reason this is not a bare `if clusters` :

      * not adopted / no carrier (the engine's own repo, every non-adopting consumer) → `[]`;
      * adopted over a source that does NOT qualify → the reason line, naming the failing properties
        (SPEC-0171 §Scenario: a non-adopting consumer must never be served the HEALTHY consumer's
        silence, because that silence would then read identically for "nothing is broken" and "I
        cannot see anything at all");
      * adopted + qualifying → the confirmed-cluster line, or `[]` when the fold is empty.

    BEST-EFFORT: every failure path returns `[]` — an informational surface must never break session
    start (the `_debt_echo_lines` / `startup_check_lines` precedent). `fe` is the frontend_errors
    module and `_read_rows` the source reader, both INJECTED so this leaf stays I/O-free under test.

    Post-`/compact` re-delivery is CO-DESIGNED with this echo (SPEC-0007 §5b — an echo without its
    re-fold is incoherent and must not pass): a `/compact` evicts this line and re-reading the seed
    does NOT restore it, so it is re-surfaced by RE-FOLDING with the SAME view verb the line points
    at — `bin/yitc-v2 [-C <repo>] frontend-errors`, invoked BARE (it resolves the same declared
    source). Documented beside its `debt` / `cross outbox` analogs in AGENTS §After-`/compact`.
    """
    try:
        ops_path = Path(repo_root) / "yitc-ops.yaml"
        if _read_yaml is None or not ops_path.exists():
            return []                                   # no carrier (the engine's own repo) → silent
        source, violations = fe.declared_source(_read_yaml(ops_path))
        if source is None and not violations:
            return []                                   # never adopted → owes nothing → silent
        if violations:
            return list(fe.not_qualifying_lines(violations, cli_hint=cli_hint))
        # T-10803 (AC4, SPEC-0165) — the CADENCE-NOT-FIRED tripwire, computed BEFORE the fold and
        # emitted even when the fold is clean. This echo is suppressed-when-clean by design, which is
        # right while the standing sweep is running and finding nothing — and indistinguishable from a
        # sweep that died months ago. `carrier_events_path` is the CARRIER's journal, not this repo's
        # (SPEC-0110 r3): the nightly writes its run record engine-side, so grading a consumer's own
        # journal would call every healthy cadence dead. Absent ⇒ no liveness claim is made at all.
        dead = list(fe.cadence_not_fired_lines(
            fe.cadence_liveness(carrier_events_path, as_of=as_of),
            cli_hint=cli_hint)) if carrier_events_path else []
        rows = (_read_rows or fe.read_rows)(**fe.read_kwargs(source))
        # T-10777 — the ACK marker: an already-JUDGED cluster leaves this line until it RECURS. The
        # acks are FOLDED from the journal (SPEC-0095 shape, no store), so suppression is re-derived
        # here on every session start rather than remembered; `events_path=None` (no journal to read)
        # simply suppresses nothing, which is the safe direction. The fold→ack→apply sequence has ONE
        # home since T-10803 (`fe.visible_clusters`) — shared with the on-demand verb and the cadence.
        visible, _muted, _stats = fe.visible_clusters(rows, as_of=as_of, events_path=events_path)
        return dead + list(fe.echo_lines(visible, cli_hint=cli_hint))
    except Exception:
        return []


_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _capability_executable(command: str, _which) -> "str | None":
    """Return the leading executable token of a declared shell command, or None if it can't be parsed.

    A declared command is a shell string (`pytest -q tests/`, `npx playwright test`, an absolute path
    `<host-home>/.codex-unconfined/bin/codex`). The cheap, read-only per-user capability signal is whether
    that LEADING executable resolves for the current user — NOT running the command (which would be the
    minutes-long test suite). `shlex.split()` tokenizes; a shell metacharacter / empty parse yields None
    (skip — a heuristic must never false-flag on something it can't cleanly read).

    LEADING ENV-ASSIGNMENT PREFIXES ARE SKIPPED (X-0529). Per shell semantics a command may carry one or
    more `VAR=VALUE` assignment prefixes before the executable (`YITC_VERIFY_TEST_TIMEOUT=900 pytest -q`,
    `FOO=bar BAZ=qux ./run.sh`). Those tokens are NOT the executable — probing `VAR=VALUE` for PATH
    resolvability invents a phantom capability gap (`VAR=VALUE` never resolves) for tooling already
    present. Skip every leading token matching `NAME=` (a valid shell identifier followed by `=`) and
    return the first token that is NOT an assignment — the genuine executable. If the command is ONLY
    assignments (no executable follows) → None (nothing to probe; the negative arm stays silent there,
    while a genuine missing-binary AFTER the prefix still trips loudly).

    This only EXTRACTS the token; `_resolve_declared_executable` decides how to resolve it (a
    repo-relative token is answered against repo_root, never via PATH — T-10587)."""
    try:
        parts = shlex.split(command)
    except Exception:
        return None
    for tok in parts:
        if _ENV_ASSIGN_RE.match(tok):
            continue                                  # env-assignment prefix — not the executable
        return tok
    return None                                       # empty parse, or only env assignments → skip


#: T-10910 (X-0719) — leading tokens that DECLARE the absence of a runnable command rather than name one.
_PROSE_SENTINELS = frozenset({
    "none", "n/a", "na", "no", "not", "nothing", "tbd", "todo", "manual", "manually",
    "see", "pending", "unknown", "ask", "various", "-", "--", "—", "–",
})

#: English FUNCTION WORDS — the positive prose marker P3 requires. A shell command line is built from
#: program names, flags and paths; it does not contain a bare `via` / `by` / `the`. Requiring one keeps
#: P3 off a flagless real command like `npx playwright test` (three tokens, zero function words), which
#: must keep reporting a gap when `npx` is genuinely absent for this user.
_PROSE_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "by", "in", "on", "at", "of", "to", "for", "with", "via",
    "from", "into", "as", "per", "yet", "still", "only", "is", "are", "was", "were", "be", "will",
    "this", "that", "it", "its", "we", "no", "not", "nothing", "none", "manually", "hand", "planned",
    "needed", "currently", "instead", "before", "after", "during", "inside", "outside", "there",
})

#: A token that carries COMMAND shape: a flag (`-q`, `--full`), a path (`bin/x`, `./run.sh`), an
#: assignment (`FOO=bar`), a dotted extension (`run.sh`), or a shell metacharacter. Prose carries none.
_COMMAND_SHAPED_RE = re.compile(r"^-|[/\\=|&;<>$*`]|\.[A-Za-z0-9]+$")


def _has_bare_parenthesis(command: str) -> bool:
    """Does the RAW command string carry a `(` or `)` OUTSIDE any quoting? Such a string is a shell
    SYNTAX ERROR, so it provably cannot be run as written — positive evidence of prose, not a guess.

    Scanned on the RAW string, never on `shlex.split` tokens: shlex STRIPS quotes, so a token-level
    test cannot tell prose from a REAL command carrying a quoted paren argument (`missing-tool "("`)
    and would suppress a genuine capability gap (audit-pre finding, T-10910). A tiny left-to-right walk
    tracking single/double-quote state is enough; a backslash escapes the next character outside quotes."""
    try:
        quote = None
        escaped = False
        for ch in command:
            if escaped:
                escaped = False
                continue
            if quote is None and ch == "\\":
                escaped = True
            elif quote is not None:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch in "()":
                return True
        return False
    except Exception:
        return False


def _reads_as_prose(command: str) -> bool:
    """T-10910 (X-0719) — does a DECLARED `command:` value read as PROSE rather than as a shell command?

    `yitc-ops.yaml tests.classes[].command` is a human-authored carrier field, so it legitimately carries
    a DECLARATIVE value instead of an executable: `none`, `TBD`, `manual smoke via browser`, or aiseller's
    recorded input `run by scripts/deploy.sh step 5 (in-container)`. Prose has no executable, so probing
    its leading token for PATH resolvability manufactures a gap the operator can never close (there is no
    `run` / `no` binary to provision). A permanently-flagged gap trains readers to ignore the whole line —
    the exact signal-erosion the report-only echo exists to avoid (SPEC-0119 rule 15).

    Three POSITIVE non-command signals — this reader demands EVIDENCE of prose and defaults to False, so
    an unrecognised string stays a command and keeps its gap (the never-false-flag posture, in the same
    narrowing family as X-0529's env-assignment prefixes and T-10587/X-0436's repo-relative resolution):
      P2 a BARE (unquoted) parenthesis — the string cannot parse as a shell command at all;
      P1 a SENTINEL leading token (`none`, `TBD`, `manual`, `see`, … — see `_PROSE_SENTINELS`);
      P3 SENTENCE SHAPE — three or more tokens, NONE of them command-shaped (no flag, no path, no
         assignment, no extension, no metacharacter) AND at least one English FUNCTION WORD, e.g.
         `no automated tests yet`. The function-word requirement is what keeps P3 off a flagless REAL
         command: `npx playwright test` is three plain tokens too, and it must keep reporting a gap when
         `npx` is genuinely absent — so shape alone is not enough evidence, prose has to read like prose.

    CALLER-PLACEMENT CONTRACT (the safety property, do not move the call): this is consulted ONLY inside
    the `not resolved` arm of `capability_preflight_lines`, so it can only ever SUPPRESS an
    already-failing probe — never flag a new one, never reclassify a command whose executable resolves.
    A lone unresolvable token (`missing-tool`) and a flag-bearing one
    (`definitely-absent-binary-xyz --run`) match no signal → still reported."""
    if not isinstance(command, str) or not command.strip():
        return False
    if _has_bare_parenthesis(command):
        return True                                   # P2 — provably not runnable as written
    try:
        parts = shlex.split(command)
    except Exception:
        return False                                  # unparseable → the caller's own skip owns it
    if not parts:
        return False
    head = parts[0].strip("\"'").rstrip(".,:;!").lower()
    if head in _PROSE_SENTINELS:
        return True                                   # P1 — a declaration of absence, not a program
    if (len(parts) >= 3
            and not any(_COMMAND_SHAPED_RE.search(tok) for tok in parts)
            and any(tok.strip("\"'").rstrip(".,:;!").lower() in _PROSE_FUNCTION_WORDS for tok in parts)):
        return True                                   # P3 — an English sentence, no command shape at all
    return False


def _resolve_declared_executable(exe: str, repo_root, run) -> "tuple[str | None, bool]":
    """T-10587 (X-0436) — resolve a DECLARED command's leading executable, repo-root-aware.

    Returns `(resolved_path_or_None, is_repo_relative)`.

    A declared command comes from the SUBJECT repo's `yitc-ops.yaml`, so its executable legitimately
    takes THREE shapes — and only two of them are PATH/cwd-independent:
      - a bare name (`pytest`)            → PATH lookup, via the injected `run` (unchanged);
      - an absolute path (`/usr/bin/x`)   → checked as-is, via `run` (`shutil.which` handles it);
      - a REPO-RELATIVE path (`bin/verify-hermetic.sh`) → resolved against `repo_root`, HERE.

    The repo-relative leg exists because `shutil.which` consults PATH only for a BARE name: handed a
    token containing a path separator it checks that literal path against the PROCESS cwd and never
    consults PATH. So the pre-T-10587 reader called a repo-relative command unrunnable whenever the
    engine ran via `-C` from any cwd but the repo root — contradicting the `-C` contract (operate on
    the NAMED repo regardless of cwd) and inventing provisioning gaps for tooling already present
    (X-0436: boomrocket's `bin/verify-hermetic.sh` + `bin/verify-alembic-topology.sh` read as 2 gaps
    from `/home/dev`, 0 from the repo root — the same call).

    A repo-relative token therefore resolves ONLY against `repo_root/<token>` (exists + executable),
    with NO fallback to `run`: that fallback IS the defect, since `which` on a path-with-sep answers
    from cwd, not PATH. `is_repo_relative` lets the caller word the gap accurately ("not found in the
    repo") instead of the inaccurate "not on your PATH". Fail-safe: any resolution hiccup ⇒
    (None, …) — the caller reports a gap rather than breaking the echo (the rule-15 posture)."""
    try:
        is_repo_relative = bool(exe) and not os.path.isabs(exe) and os.sep in exe
    except Exception:
        is_repo_relative = False
    if not is_repo_relative:
        return run(exe), False
    try:
        candidate = Path(repo_root) / exe
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate), True
    except Exception:
        pass
    return None, True


_PLAYWRIGHT_RE = re.compile(r"(?:^|[\s/])playwright(?:[\s]|$)")


def _invokes_playwright(command: str) -> bool:
    """T-10528: does a declared command INVOKE playwright? Matches `npx playwright test`, `playwright test`,
    `python -m playwright ...` — playwright as a whole token, never a substring of an unrelated word. A
    non-match is simply not a playwright command (the heuristic must never false-flag)."""
    return isinstance(command, str) and bool(_PLAYWRIGHT_RE.search(command))


def _playwright_browsers_missing(env=None, home=None) -> "bool | None":
    """T-10528 (SPEC-0119 rule 15, X-0364) — best-effort per-user probe: is the Playwright browser CACHE
    absent for the invoking user? Returns True (missing), False (present), or None (undeterminable — NEVER
    false-flag). READ-ONLY (never installs, never runs a command).

    The cache dir is `$PLAYWRIGHT_BROWSERS_PATH` when set, else the Linux default `~/.cache/ms-playwright`.
    The special value `PLAYWRIGHT_BROWSERS_PATH=0` means browsers live under the project's node_modules (a
    layout this general reader deliberately does not probe) → None (skip). An absent OR empty cache dir ⇒
    missing; a populated dir ⇒ present; any read hiccup ⇒ None (the fail-safe posture, like every other
    leg of this preflight)."""
    try:
        env = env if env is not None else os.environ
        override = env.get("PLAYWRIGHT_BROWSERS_PATH")
        if isinstance(override, str) and override.strip():
            if override.strip() == "0":
                return None                       # node_modules layout — not the ~/.cache probe (skip)
            cache = Path(override.strip())
        else:
            cache = Path(home if home is not None else Path.home()) / ".cache" / "ms-playwright"
        if not cache.is_dir():
            return True                           # no cache dir at all → browsers not installed
        return not any(cache.iterdir())           # an empty cache dir is still "not installed"
    except Exception:
        return None                               # undeterminable → skip, never false-flag


def capability_preflight_lines(repo_root, _read_yaml, *, _which=None, audit_binary=None,
                               audit_auth_present=None, _pw_cache_probe=None,
                               _in_hermetic_child=None) -> list:
    """T-10503 (SPEC-0119 rule 15, X-0364) — the per-user CAPABILITY preflight echo.

    Sibling of `startup_check_lines`: where that runs a project's user-DECLARED `startup_checks:`, THIS
    reads the commands the lifecycle ALREADY declares — `verify.layers[].command` (the land-verify gate)
    + `tests.classes[].command` (Stage-6 tests) in `<repo_root>/yitc-ops.yaml`, plus the external auditor
    (`audit_binary` + `audit_auth_present`, Stage-4/8) — and reports which the CURRENT user cannot run.
    TWO per-user capability signals are checked, both READ-ONLY (it NEVER runs a command):
      - EXECUTABILITY of each command's leading executable — PATH names AND absolute paths via
        `shutil.which`, REPO-RELATIVE paths (`bin/verify-hermetic.sh`) against `repo_root`
        (`_resolve_declared_executable`, T-10587/X-0436: `which` answers a path-with-sep from the
        PROCESS cwd, so resolving one via PATH made the verdict cwd-dependent and false-flagged a
        `-C` consumer's own scripts as missing);
      - the external auditor's SUBSCRIPTION AUTH presence (`audit_auth_present`, injected) — the actual
        per-user auditor blocker is a missing `codex login`, not just a missing binary (X-0364 / <collaborator>
        T-10421 — a second developer with the binary on PATH still can't run the owner-bound auditor).
    Returns ONE aggregated plain-language report-only line naming each capability the invoking user lacks
    + a pointer to the provisioning checklist, else `[]` (SUPPRESSED-WHEN-CLEAN). Appended to the
    SPEC-0119 debt-echo by the host residue (`_debt_echo_lines`), so it rides the same 3 seams
    (session-start / land-tail / `debt` re-fold) + suppression — no new mechanism, no gate (report-only;
    CHARTER non-goal #7).

    SCOPE (executable + auth + the Playwright browser-CACHE leg): the general reader stays bounded, but
    the ONE tool-specific depth T-10503 deferred (finding 2) is now filled (T-10528) — a declared command
    that INVOKES playwright is ALSO checked for the browser CACHE (`$PLAYWRIGHT_BROWSERS_PATH` /
    `~/.cache/ms-playwright`), which is absent even when `npx`/`playwright` resolves (the X-0364 class).
    That leg is best-effort + report-only (undeterminable ⇒ skip, never false-flag); no deeper per-tool
    internals are taught here (anti-complexity). The checklist pattern names the remaining bound.

    PROSE SUPPRESSION (T-10910, X-0719): a declared `command:` is human-authored, so it may DECLARE the
    absence of a runnable command (`none`, `manual smoke via browser`, `run by scripts/deploy.sh step 5
    (in-container)`) instead of naming one. `_reads_as_prose` is consulted ONLY inside the unresolved arm
    below — so it can only ever drop a gap nobody could close, never silence a real one.

    TOKEN-FRUGAL: names the label + reason + pointer, never a command's output. BEST-EFFORT / fail-safe:
    an absent carrier/section, a malformed entry, an unparseable command, or an unreadable file is SKIPPED
    — a report-only surface must never break startup (the `startup_check_lines` fail-safe posture). The
    engine's own repo has no `yitc-ops.yaml`, so only the injected auditor signals are checked there.
    `_which(exe) -> str|None` is injected for tests; the default is `shutil.which`. It resolves PATH
    names + absolute paths only — a repo-relative command never reaches it (it is answered against
    `repo_root`, T-10587). `audit_auth_present`
    is True|False|None (None ⇒ undeterminable ⇒ the auth leg is skipped, never false-flagged).

    `_in_hermetic_child()` (T-11473) is the INJECTED containment discriminator the playwright leg asks
    before it speaks — see that leg for why. It is injected rather than imported because this module is
    identity-agnostic KERNEL (stdlib + lib.state / lib.cross / lib.views only, never a back-import of
    `lib.worktree`, which is where the one existing discriminator lives). Absent ⇒ PRODUCTION ⇒ the leg
    behaves exactly as before, which is what every direct caller and the whole T-10503 suite get."""
    try:
        run = _which or shutil.which
        # (label, command) pairs the lifecycle DECLARES — collected fail-safe from the ops carrier.
        declared = []
        try:
            ops_path = Path(repo_root) / "yitc-ops.yaml"
            if _read_yaml is not None and ops_path.exists():
                ops = _read_yaml(ops_path)
                if isinstance(ops, dict):
                    verify = ops.get("verify")
                    if isinstance(verify, dict) and isinstance(verify.get("layers"), list):
                        for ly in verify["layers"]:
                            if isinstance(ly, dict) and isinstance(ly.get("command"), str) and ly["command"].strip():
                                lyid = ly.get("layer") if isinstance(ly.get("layer"), str) else "?"
                                declared.append((f"verify:{lyid}", ly["command"]))
                    tests = ops.get("tests")
                    if isinstance(tests, dict) and isinstance(tests.get("classes"), list):
                        for c in tests["classes"]:
                            if isinstance(c, dict) and isinstance(c.get("command"), str) and c["command"].strip():
                                cid = c.get("class") if isinstance(c.get("class"), str) else "?"
                                declared.append((f"tests:{cid}", c["command"]))
        except Exception:
            declared = declared  # carrier read failure → only the auditor (if any) is preflighted
        # The external auditor (Stage-4/8) — engine-resolved binary, injected by the host so a consumer
        # session preflights the SAME auditor it will actually invoke (SPEC-0093 per-user surface).
        if isinstance(audit_binary, str) and audit_binary.strip():
            declared.append(("audit", audit_binary.strip()))

        cannot = []
        for label, command in declared:
            exe = _capability_executable(command, run)
            if exe is None:
                continue                                  # unparseable → skip (fail-safe, never false-flag)
            try:
                resolved, repo_relative = _resolve_declared_executable(exe, repo_root, run)
            except Exception:
                continue                                  # a broken resolver never breaks the echo
            if not resolved:
                # PROSE leg (T-10910, X-0719): a human-authored `command:` may DECLARE the absence of a
                # runnable command (`none`, `manual smoke via browser`, aiseller's
                # `run by scripts/deploy.sh step 5 (in-container)`). Probing its leading token invents a
                # gap nobody can close. Consulted HERE and only here — inside the failing arm — so it can
                # only suppress a phantom, never silence a command whose executable actually resolves.
                if _reads_as_prose(command):
                    continue
                cannot.append(f"{label}: `{exe}` not found (or not executable) in the repo"
                              if repo_relative else
                              f"{label}: `{exe}` not on your PATH")
        # Playwright browser-CACHE leg (T-10528, X-0364 class): a declared command that INVOKES playwright
        # reads as capable when `npx`/`playwright` resolves above, yet nothing runs if the browser CACHE is
        # absent (aiseller's e2e browsers never installed). Probe the cache ONCE (per-user,
        # command-independent) the first time a playwright command is seen; report-only, best-effort,
        # undeterminable ⇒ skip. The depth T-10503 deferred (finding 2), now filled.
        _pw_probed = False
        _pw_missing = None
        for label, command in declared:
            if not _invokes_playwright(command):
                continue
            if not _pw_probed:
                _pw_missing = (_pw_cache_probe or _playwright_browsers_missing)()
                # T-11473 — INSIDE A HERMETIC VERIFY CHILD THIS QUESTION HAS NO ANSWER, so give the
                # honest one. This is the propagation site T-11472 found and deliberately left for its
                # own card; the mechanism is IDENTICAL, not a lookalike. `_playwright_browsers_missing`
                # resolves its cache at `$PLAYWRIGHT_BROWSERS_PATH` else `~/.cache/ms-playwright` —
                # rooted at the USER'S HOME, exactly like the auditor-auth leg was. SPEC-0131 Rule 1
                # gives every verify child a PRIVATE mkdtemp HOME, and `hermetic_child_env` scrubs
                # neither PLAYWRIGHT_BROWSERS_PATH nor CODEX_HOME — so the probe is HALF-hermetic: with
                # the ambient var inherited it answers from the launcher's real cache, without it from
                # an empty box HOME that has no `.cache/ms-playwright` at all, and `not cache.is_dir()`
                # returns True. That True is a POSITIVE claim — "run `npx playwright install`" — about a
                # REAL operator's machine, derived from a directory belonging to the harness.
                #
                # WHY IT MATTERS DESPITE HAVING NOT BITTEN THE ENGINE. The leg fires only for a DECLARED
                # command that INVOKES playwright, and the engine repo declares none, so the engine's own
                # sandboxed folds never reach it (which is exactly why no kernel-suite green can speak to
                # this — the condition has to be CONSTRUCTED, and tests/test_t11473_* constructs it). The
                # population is real and named: aiseller declares `class: e2e-playwright`, BLOCKING on
                # deploy; kupiclub routes playwright specs too. A confident false gap there stops a deploy.
                #
                # THE FIX IS THE LEG'S OWN DOCUMENTED FAIL-SAFE, not a new one — `_playwright_browsers_missing`
                # already defines None as UNDETERMINABLE ⇒ skip, NEVER false-flag, and inside a hermetic
                # child the answer genuinely IS undeterminable: there is no user whose provisioning could
                # be reported. So None is the honest value, not a suppression. The discriminator is the
                # EXISTING positive one (`worktree._in_hermetic_verify_child`, T-11288), INJECTED by the
                # host because this module is kernel-pure; never a hand-rolled second containment read
                # (the T-11133 mirrored-copy drift). Asked ONLY when the probe came back True (a gap is
                # about to be emitted), so the provisioned path is untouched, and ONLY this leg — the
                # repo-derived legs keep speaking inside the sandbox, which `test_t10503::test_d1` needs.
                if _pw_missing is True and _in_hermetic_child is not None:
                    try:
                        if _in_hermetic_child():
                            _pw_missing = None
                    except Exception:
                        pass                      # a broken discriminator never breaks the echo
                _pw_probed = True
            if _pw_missing is True:
                cannot.append(f"{label}: playwright browsers not installed (run `npx playwright install`)")
        # Auditor SUBSCRIPTION-AUTH leg — the real per-user auditor blocker (finding 1). Only when the
        # host could determine it (False = no auth.json found anywhere); None ⇒ skip, never false-flag.
        if audit_auth_present is False:
            cannot.append("audit: no codex subscription login found (run `codex login`)")
        if not cannot:
            return []
        return ["capability-preflight: " + str(len(cannot))
                + " capability gap(s) for you (this user) — " + "; ".join(cannot)
                + ". You'll hit this at the matching lifecycle stage; provision them — "
                + "see patterns/per-user-provisioning-checklist.md. "
                + "Report-only (SPEC-0119 r15 / SPEC-0093)."]
    except Exception:
        return []


def born_skew_check_line(repo_root, _read_yaml, _carrier_skew) -> list:
    """SPEC-0119 rule 8 (T-10077) — the per-consumer born-schema-SKEW self-check.

    Computes whether THIS repo's own `yitc-ops.yaml` carrier is BEHIND the current kernel born schema
    — the born sections / nested subfields a re-`bin/yitc-v2 -C <repo> init` WOULD deliver — and returns
    ONE report-only line naming the `init` adopt action, else `[]` (SUPPRESSED-WHEN-CLEAN). It is
    APPENDED to the SPEC-0119 debt-echo output by the host residue (`_debt_echo_lines`), so it inherits
    the 3 seams (session-start / land-tail / `debt` re-fold) + suppression verbatim — no new mechanism.

    This REPLACES the retired engine-side registry sweep (the kernel enumerating every registry
    consumer on their behalf, removed by T-10077): each project now watches AND updates ITSELF at its
    own seams (owner directive 2026-07-03). The skew set is computed by the INJECTED `_carrier_skew(ops)`
    — `init._consumer_carrier_skew`, the SAME detector the init UPDATE path uses to decide what to
    deliver — so the report can never claim a skew the update would not deliver (ONE SoT).

    BEST-EFFORT / fail-safe: the engine's own repo has no `yitc-ops.yaml`, and a pre-init / unreadable /
    non-mapping carrier is NOT a schema-skew row (fail-open) — all yield `[]` (a report-only surface must
    never break startup). `_carrier_skew(ops) -> list[str]` is injected for tests + host-decoupling."""
    try:
        ops_path = Path(repo_root) / "yitc-ops.yaml"
        if _read_yaml is None or not ops_path.exists():
            return []                                     # engine's own repo has no carrier → suppressed
        ops = _read_yaml(ops_path)
        if not isinstance(ops, dict):
            return []                                     # pre-init / unreadable / non-mapping → not a skew row
        missing = _carrier_skew(ops)
        if not missing:
            return []                                     # fresh/current carrier → suppressed-when-clean
        return ["debt: this project is behind the kernel schema — re-run "
                "`bin/yitc-v2 -C <repo> init` to deliver the missing born section(s)/subfield(s), "
                "report-only (SPEC-0119 / SPEC-0123). Behind: "
                + ", ".join(str(m) for m in missing) + "."]
    except Exception:
        return []
