"""bin/lib/observe.py — SPEC-0135 real-work observation-loop CAPTURE helpers (T-10121).

Pure, dependency-free builders for the OPTIONAL raw observation fields that ride the EXISTING
anchor events (the SPEC-0025 §Raw observation-loop fields + §Resource-summary + §Normalized
provider×model×effort vocabulary catalogue amended by T-10120). SPEC-0135 §1: capture is CHEAP,
always-on, and rides existing emit points — this module adds NO new event type / store / parser /
journal / daemon (SPEC-0135 §6 additive-only fence).

DISCIPLINE (CHARTER §P5/§P7, T-0358): every builder returns ONLY the keys it could actually
resolve — an unmeasurable host fact / resource reading is OMITTED (never a fabricated 0/None),
so an emitter that supplies none writes the byte-unchanged legacy payload. The one documented
EXCEPTION is the provider×model×effort triple, whose SPEC-0025 fallback is the LITERAL "unknown"
(a whole-triple resolution failure sets all three to "unknown"; absent ≡ "unknown", one bucket).

This is the CAPTURE half; the read-time DERIVED cost view (token-rollup × pricing-config) stays
elsewhere — usage/cost are NEVER captured here (SPEC-0135 §3 Single-SoT fence). A pure leaf like
`textutil` / `events`: no host-verb dependency, so the read-time observation view (T-10123) reuses
`normalize_triple` without pulling in the CLI.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess

# ── the normalized provider×model×effort triple (SPEC-0025 §Normalized …vocabulary) ──────────────
# EXTENSIBLE, not a closed enum (the spec-wide append-only stance, D-0009): a new value is admitted
# by simply appearing. These alias tables map the RAW descriptor tokens (the AI_AGENT env value the
# worker/session sets, or the audit-config adapter name) onto the gen_ai.system-aligned vendor.
_PROVIDER_ALIASES = {
    "claude": "anthropic", "anthropic": "anthropic",
    "codex": "openai", "openai": "openai", "gpt": "openai",
    "gemini": "google", "google": "google",
}

# the explicit, documented fallback for an axis that cannot be resolved (SPEC-0025 §vocab).
UNKNOWN = "unknown"


def normalize_provider(raw: "str | None") -> str:
    """RAW provider/adapter token → the normalized vendor (gen_ai.system aligned). An unmapped but
    PRESENT value passes through lowercased (extensible vocab); absent/blank → the "unknown" fallback.

    A worker's AI_AGENT descriptor embeds the harness version — `claude-code_2-1-205_agent` — which
    never matches a bare alias KEY, so every CLI patch bump silently forked its own provider slice
    (defeating the SPEC-0135 §6 cross-fork/pair comparability the triple exists for — fu_096baef57558).
    So strip the harness version/suffix before the alias lookup: test the LEADING separator-delimited
    token (`claude-code_2-1-205_agent` → `claude` → anthropic). ONLY the leading token counts — a
    `proxy_claude` is NOT anthropic. The raw descriptor stays untouched provenance (session_config)."""
    if not raw:
        return UNKNOWN
    key = str(raw).strip().lower()
    if not key:
        return UNKNOWN
    # leading-vendor-token strip: the first NON-EMPTY alphanumeric token (skipping any leading
    # separators), mapped iff it is a known vendor alias.
    lead = next((t for t in re.split(r"[^a-z0-9]+", key) if t), "")
    if lead in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[lead]
    # no leading vendor token — exact-key alias else verbatim passthrough (byte-identical to before).
    return _PROVIDER_ALIASES.get(key, key)


def _parse_descriptor(session_config: "str | None") -> dict:
    """The opaque `session_config` descriptor is a space-joined list of `k=v` parts (the
    `_session_config_descriptor` shape: `AI_AGENT=… CLAUDE_EFFORT=… model=…`). Parse it into a
    {k: v} map for read-time triple derivation. A blank / "unknown" descriptor → empty map."""
    out: dict = {}
    if not session_config:
        return out
    s = str(session_config).strip()
    if not s or s == UNKNOWN:
        return out
    for part in s.split():
        if "=" in part:
            k, v = part.split("=", 1)
            if k and v:
                out[k] = v
    return out


def normalize_triple(session_config: "str | None") -> dict:
    """Derive the normalized {provider, model, effort} slice key from the opaque `session_config`
    descriptor (SPEC-0135 §6 — the SOLE cross-session slice key; a READ-TIME derivation, the raw
    descriptor stays raw provenance). ALWAYS returns all three keys; an axis with no signal → the
    literal "unknown" (never null, never inferred). A whole-descriptor miss → all three "unknown"."""
    kv = _parse_descriptor(session_config)
    provider = normalize_provider(kv.get("AI_AGENT"))
    model = kv.get("model") or UNKNOWN
    # effort: the reasoning tier when the harness exposes one (CLAUDE_EFFORT); else the "unknown"
    # fallback (absent ≡ unknown, one bucket — SPEC-0025 §vocab). Passed VERBATIM (extensible).
    effort = kv.get("CLAUDE_EFFORT") or UNKNOWN
    return {"provider": provider, "model": model, "effort": effort}


def auditor_triple(provider: "str | None", model: "str | None", effort: "str | None") -> dict:
    """The auditor-side normalized triple for external_audit_completed (SPEC-0135 §4 — observe the
    external-auditor role when present, roll worker×auditor up to the PAIR). `provider` is the
    audit-config ADAPTER name (codex|claude) mapped to the vendor; `model`/`effort` ride verbatim.
    Each key OMITTED when the auditor config yields no signal (identity-only; no usage/cost)."""
    out: dict = {}
    p = normalize_provider(provider)
    if p != UNKNOWN:
        out["provider"] = p
    if model:
        out["model"] = str(model)
    if effort:
        out["effort"] = str(effort)
    return out


# ── host facts + resource summary (SPEC-0025 §session_started host facts / §Resource-summary) ─────

def host_facts() -> dict:
    """Best-effort host join-keys the loop uses to size minimum hardware per project class
    (SPEC-0135 §Scenario): cores (logical CPUs), mem_gb (total RAM), host_label (a stable host id
    — the YITC_HOST_LABEL override else the hostname). Each key OMITTED when unavailable (T-0358)."""
    out: dict = {}
    try:
        cores = os.cpu_count()
        if isinstance(cores, int) and cores > 0:
            out["cores"] = cores
    except Exception:
        pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if isinstance(pages, int) and isinstance(page_size, int) and pages > 0 and page_size > 0:
            out["mem_gb"] = round(pages * page_size / (1024 ** 3), 1)
    except (ValueError, OSError, AttributeError):
        pass
    try:
        label = os.environ.get("YITC_HOST_LABEL", "").strip() or socket.gethostname()
        if label:
            out["host_label"] = label
    except Exception:
        pass
    return out


def resource_summary() -> dict:
    """Best-effort host-load raw summary for an ok land_completed (SPEC-0025 §Resource-summary): the
    1-minute load average + peak verify-subprocess memory. Each key OMITTED when the platform can't
    measure it — so on a --no-tests / inert-retry land (no verify children) peak_mem is naturally
    absent (ru_maxrss of RUSAGE_CHILDREN is 0), while load1 rides every ok land. Raw host facts only
    — no usage/cost (SPEC-0135 §3)."""
    out: dict = {}
    try:
        out["load1"] = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        pass
    try:
        import resource as _res  # POSIX-only; absent → peak_mem omitted
        peak = _res.getrusage(_res.RUSAGE_CHILDREN).ru_maxrss
        # ru_maxrss is KB on Linux; 0 == no children reaped (no suite ran) → omit (T-0358).
        if isinstance(peak, int) and peak > 0:
            out["peak_mem"] = peak
    except Exception:
        pass
    return out



# ── which CHECKOUT a verb's artifact read rests on (T-11249 / kupiclub X-0970) ────────────────────
# Every artifact path derives from ONE anchor, REPO_ROOT — module-load `__file__`-derived, or
# rebound wholesale by the global `-C <path>` flag. That resolution is correct by design: the verb
# reads the tree the invocation named. What was missing is that it never SAID which tree, so a
# controller whose fixes lived in a worktree while the invocation named the main checkout read a
# refusal quoting field values absent from the file in front of them, three cycles running. This is
# the diagnostic half: a builder, in the same shape as `host_facts` above (best-effort, every key
# OMITTED when it cannot be resolved — never a fabricated value, T-0358), plus its one-line render.
# repo_root is a PARAMETER, never a global read: this leaf stays host-uncoupled.

def _git_field(repo_root, args) -> "str | None":
    """`git -C <repo_root> <args>` -> stripped stdout, or None on ANY failure. A DIAGNOSTIC must
    never be able to fail the verb it decorates, so every error path degrades to None."""
    try:
        r = subprocess.run(["git", "-C", str(repo_root), *args],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def checkout_provenance(repo_root) -> dict:
    """Which checkout `repo_root` names, as far as git can be asked (T-11249).

    `path` is ALWAYS present — it is the one fact that cannot fail, and it is the fact the reader
    needs. `branch` / `head` / `linked_worktree` are omitted when git cannot resolve them (a
    non-git sandbox, a detached or unborn HEAD), never guessed. `linked_worktree` reuses the same
    git-dir != git-common-dir test as `_in_writing_worktree` (anti-cx F1: one definition of "a
    linked worktree"), but as a pure fact with no branch-namespace condition — this answers "which
    tree", not "may I write here"."""
    out: dict = {"path": str(repo_root)}
    branch = _git_field(repo_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if branch:
        out["branch"] = branch
    head = _git_field(repo_root, ["rev-parse", "--short", "HEAD"])
    if head:
        out["head"] = head
    gd = _git_field(repo_root, ["rev-parse", "--git-dir"])
    cgd = _git_field(repo_root, ["rev-parse", "--git-common-dir"])
    if gd and cgd:
        out["linked_worktree"] = (gd != cgd)
    return out


def checkout_provenance_line(repo_root, *, verb: str) -> str:
    """The one diagnostic line a governed artifact-reading verb prints before it reads (T-11249).

    Names the resolved checkout so the caller never has to guess which tree a verdict rests on. On
    the PRIMARY checkout it also states what that tree cannot see — a worktree's uncommitted or
    unlanded edits — because that is the exact case the reporter lost three cycles to, and a
    message that only names a path leaves the reader to infer the consequence themselves
    (lessons/a-refusal-remedy-must-name-which-locus-it-repairs: name the locus AND the case)."""
    p = checkout_provenance(repo_root)
    linked = p.get("linked_worktree")
    kind = "checkout" if linked is None else ("linked worktree" if linked else "primary checkout")
    parts = [f"# {verb}: reading {kind} {p['path']}"]
    if p.get("branch"):
        parts.append(f"branch {p['branch']}")
    if p.get("head"):
        parts.append(f"@{p['head']}")
    line = " ".join(parts)
    if linked is False:
        line += " — a worktree's uncommitted or unlanded edits are NOT seen"
    return line


# ── the normalized wait/block reason (SPEC-0025 §wait_reason, SPEC-0135 §5) ───────────────────────
# EXTENSIBLE vocabulary (D-0009), the named canonical values; anything outside → the "other" fallback.
WAIT_REASON_VOCAB = frozenset({
    "owner-wait", "auditor-abort", "audit-ceiling", "env-fault", "dep-wait", "session-end",
})
WAIT_REASON_OTHER = "other"


def normalize_wait_reason(raw: "str | None") -> "str | None":
    """Categorize a pause/block reason into the SPEC-0135 §5 enum so the loop can find where time is
    lost. Takes the prefix before ':' (the bg_dispatch_halted reason is `audit-ceiling: <detail>`),
    lowercases, and maps to a canonical value or the "other" fallback. Returns None on a blank input
    (so the caller OMITS the field), never a fabricated value (T-0358)."""
    if not raw:
        return None
    head = str(raw).split(":", 1)[0].strip().lower()
    if not head:
        return None
    return head if head in WAIT_REASON_VOCAB else WAIT_REASON_OTHER


# ── composers (merged into the emit payloads at each anchor site) ─────────────────────────────────

def session_started_fields(session_config: "str | None") -> dict:
    """The capture-#1 LINCHPIN bundle for session_started (SPEC-0025): the normalized worker-side
    triple (ALWAYS present, "unknown" fallback) + the best-effort host facts (each OMITTED when
    unavailable). Cheap, always-on (SPEC-0135 §1)."""
    return {**normalize_triple(session_config), **host_facts()}


def outcome_fields(task: "dict | None", *, tid: "str | None", repo_root, events_path) -> dict:
    """Raw OUTCOME facts for task_closed (SPEC-0025 §Outcome observation fields, SPEC-0135 §3/§5 —
    counts/join-keys only, NEVER a composite score): `class` (the task's class:, when set),
    `audited` (whether the external-audit stages ran — an audit-post verdict YAML exists), and
    `audit_passes` (the audit-loop pass count reached, counted from the audit_{pre,post}_completed
    events in this checkout's journal). Best-effort: any resolution failure just OMITS its key."""
    out: dict = {}
    task = task or {}
    cls = task.get("class")
    if cls:
        out["class"] = str(cls)
    if not tid or repo_root is None:
        return out
    try:
        from pathlib import Path
        audit_post = Path(repo_root) / "decisions" / f"{tid}-audit-post.yaml"
        out["audited"] = bool(audit_post.exists())
    except Exception:
        return out
    if out.get("audited"):
        passes = _count_audit_passes(tid, events_path)
        if passes > 0:
            out["audit_passes"] = passes
    return out


def _count_audit_passes(tid: str, events_path) -> int:
    """Count the task's completed external-audit passes from the checkout journal — the
    audit_{pre,post}_completed rows whose top-level task_id is `tid`. Best-effort (unreadable /
    missing journal → 0, never a fabricated positive)."""
    import json
    from pathlib import Path
    n = 0
    try:
        p = Path(events_path)
        if not p.exists():
            return 0
        from lib import journal as journal_mod   # T-11444: LOCAL import — this module is loaded
                                                 # STANDALONE by its own tests (by file path, no
                                                 # `bin/` on sys.path), so a module-level import
                                                 # would break that load (the worktree.py idiom).
        for line in journal_mod.segment_lines(p, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
            if "audit_pre_completed" not in line and "audit_post_completed" not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") in ("audit_pre_completed", "audit_post_completed") \
                    and e.get("task_id") == tid:
                n += 1
    except Exception:
        return n
    return n
