"""The compact per-unit table of a verify layer's adapter record (T-14568, SPEC-1046).

A layer row's `adapter` record (SPEC-1046) carries the per-test-file results of a run — `units`, one
dict per unit — and lists naming units by identity: `selection.would_run`, `partial.left_out`, ... .
They are most of a test-run row's bytes. This module writes them ONCE per record as one lossless table
and reads them back in the old shape; nothing else changes and nothing moves out of the row.

THE TABLE (`adapter["unit_table"]`, version 1):
  files  every unit identity the record names, ONCE: `[k, rest]` or `[k, rest, project]`, where the
         file is the previous entry's file cut to its first `k` characters followed by `rest`
         (front coding). The units come first, in (project, file) order, then the identities only a
         list names, in the same order.
  n      present when the record had a `units` list: the units are `files[0:n]`.
  cols   the units' other fields, one column per key (`duration_ms`, `status`, `failed_tests`, ...):
         `{"v": [value per unit]}` or `{"d": default, "x": [[i, value], ...]}` — the smaller one —
         plus `"a": [i, ...]` naming the units that lack the key. Nothing is defaulted that a unit
         does not carry.
  refs   `[[section, key, [entry, ...]], ...]` — the record's unit lists (REF_LISTS); an entry is the
         index of its identity in `files`, or `[index, {other keys}]` when it carries more than one.
An identity is the unit's `file` plus its `project` when that is a non-empty string; any other
project value travels as an ordinary field. A list or a unit that is not a dict with a string `file`
is left in the record as it is.

`expand(record)` returns the record in the shape it had before `encode` (unit order aside: the
table holds the units in (project, file) order, and no reader reads their order — SPEC-0190 rule 5).
Rows written before this table, and records without one, are returned unchanged, so a reader calls
`expand` on every adapter record it reads from the journal.

`ENABLED` switches the writer side: off, `encode` returns the record unchanged (the disabled arm of
the C7 differential: the journal-measure replay utility's `replay --no-unit-table`)."""
from __future__ import annotations

import json

KEY = "unit_table"
VERSION = 1
ENABLED = True
# The adapter record's unit lists, by (section, key). `pre_deploy_skip` is not here: its membership
# and identity are T-14569's (SPEC-1051 rule 2) — the SKIP-SET section at the end of this module.
REF_LISTS = (("selection", "would_run"), ("selection", "would_credit"), ("selection", "would_omit"),
             ("partial", "ran"), ("partial", "left_out"), ("partial", "not_reached"),
             ("partial", "credited"), ("credit", "would_rerun"), ("credit", "would_credit"))
_SEP = (",", ":")


def _ident(entry):
    """(project, file) of a unit or list entry, project "" when it is not part of the identity; None
    when the entry names no unit (not a dict, or no string file)."""
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        return None
    proj = entry.get("project")
    return (proj if isinstance(proj, str) and proj else "", entry["file"])


def _rest(entry, ident) -> dict:
    """The entry's keys beyond its identity."""
    return {k: v for k, v in entry.items() if k != "file" and not (k == "project" and ident[0])}


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=_SEP))


def _column(values: list, absent: list) -> dict:
    """One field of the units: dense `v`, or a default `d` with exceptions `x` — whichever is
    smaller — plus `a`, the units lacking the field."""
    gone = set(absent)
    present = [(i, v) for i, v in enumerate(values) if i not in gone]
    dense = {"v": values}
    counts: dict = {}
    for _, v in present:
        k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        counts[k] = counts.get(k, 0) + 1
    best = max(counts, key=lambda k: (counts[k], k))
    sparse = {"d": json.loads(best), "x": [[i, v] for i, v in present
                                           if json.dumps(v, sort_keys=True, ensure_ascii=False) != best]}
    if not sparse["x"]:
        del sparse["x"]
    col = sparse if _size(sparse) < _size(dense) else dense
    if absent:
        col["a"] = absent
    return col


def encode(record):
    """The adapter record with its units and unit lists written as one table; the record itself
    (never a copy of it) when there is nothing to write or ENABLED is off. Pure."""
    if not ENABLED:
        return record
    return _encode(record)


def _encode(record):
    """`encode` without the ENABLED switch (the pre-deploy skip record has its own, SKIP). Pure."""
    if not isinstance(record, dict):
        return record
    record = expand(record)
    if KEY in record:
        return record                          # a table this version cannot read: kept as found
    units = record.get("units")
    unit_ids = [_ident(u) for u in units] if isinstance(units, list) else None
    if unit_ids is not None and any(i is None for i in unit_ids):
        unit_ids = None                        # a unit naming no file: the list stays as it is
    lists = []
    for sect, key in REF_LISTS:
        sub = record.get(sect)
        val = sub.get(key) if isinstance(sub, dict) else None
        if isinstance(val, list) and val and all(_ident(e) is not None for e in val):
            lists.append((sect, key, val))
    if unit_ids is None and not lists:
        return record
    order = sorted(range(len(unit_ids)), key=lambda i: unit_ids[i]) if unit_ids is not None else []
    files = [unit_ids[i] for i in order]
    at: dict = {}
    for i, ident in enumerate(files):
        at.setdefault(ident, i)
    extra = sorted({_ident(e) for _, _, val in lists for e in val} - set(at))
    for ident in extra:
        at[ident] = len(files)
        files.append(ident)
    table: dict = {"v": VERSION}
    coded, prev = [], ""
    for proj, f in files:
        k = 0
        while k < len(prev) and k < len(f) and prev[k] == f[k]:
            k += 1
        coded.append([k, f[k:], proj] if proj else [k, f[k:]])
        prev = f
    table["files"] = coded
    out = {k: v for k, v in record.items() if k != "units"} if unit_ids is not None else dict(record)
    if unit_ids is not None:
        table["n"] = len(order)
        rows = [_rest(units[i], unit_ids[i]) for i in order]
        names: list = []
        for r in rows:
            names.extend(k for k in r if k not in names)
        cols = {}
        for name in names:
            absent = [j for j, r in enumerate(rows) if name not in r]
            cols[name] = _column([r.get(name) for r in rows], absent)
        if cols:
            table["cols"] = cols
    if lists:
        refs = []
        for sect, key, val in lists:
            entries = []
            for e in val:
                ident = _ident(e)
                rest = _rest(e, ident)
                entries.append([at[ident], rest] if rest else at[ident])
            refs.append([sect, key, entries])
            out[sect] = {k: v for k, v in out[sect].items() if k != key}
        table["refs"] = refs
    out[KEY] = table
    return out


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _valid(table) -> bool:
    """Whether a v1 table is whole: every index in range, every column covering exactly the units, every
    front code inside the previous name. `expand` decodes only a table that passes (audit-pre F2) — a
    table that does not is never read into evidence."""
    files = table.get("files")
    if not isinstance(files, list):
        return False
    prev_len = 0
    for ent in files:
        if not (isinstance(ent, list) and len(ent) in (2, 3) and _int(ent[0]) and isinstance(ent[1], str)
                and 0 <= ent[0] <= prev_len and (len(ent) == 2 or (isinstance(ent[2], str) and ent[2]))):
            return False
        prev_len = ent[0] + len(ent[1])
    n = table.get("n")
    if "n" in table and not (_int(n) and 0 <= n <= len(files)):
        return False
    cols = table.get("cols", {})
    if not isinstance(cols, dict) or (cols and "n" not in table):
        return False
    for col in cols.values():
        if not isinstance(col, dict) or ("v" in col) == ("d" in col) or not set(col) <= {"v", "d", "x", "a"}:
            return False
        if "v" in col and not (isinstance(col["v"], list) and len(col["v"]) == n and "x" not in col):
            return False
        x = col.get("x", [])
        if not (isinstance(x, list) and all(isinstance(e, list) and len(e) == 2 and _int(e[0])
                                            and 0 <= e[0] < n for e in x)
                and len({e[0] for e in x}) == len(x)):
            return False
        a = col.get("a", [])
        if not (isinstance(a, list) and all(_int(i) and 0 <= i < n for i in a) and len(set(a)) == len(a)):
            return False
        # each unit's field is defined exactly once: an absent unit has no exception and no dense value
        if set(a) & {e[0] for e in x} or ("v" in col and any(col["v"][i] is not None for i in a)):
            return False
    # nor is an identity field redefined: no `file` column, and a `project` column only on units whose
    # identity carries no project (a project-qualified unit is absent from it)
    if "file" in cols:
        return False
    if "project" in cols:
        gone = set(cols["project"].get("a", []))
        if any(len(files[j]) == 3 and j not in gone for j in range(n)):
            return False
    refs = table.get("refs", [])
    if not isinstance(refs, list):
        return False
    seen = set()
    for ref in refs:
        if not (isinstance(ref, list) and len(ref) == 3 and tuple(ref[:2]) in REF_LISTS
                and tuple(ref[:2]) not in seen and isinstance(ref[2], list)):
            return False
        seen.add(tuple(ref[:2]))
        for e in ref[2]:
            i = e if _int(e) else (e[0] if isinstance(e, list) and len(e) == 2 and _int(e[0])
                                   and isinstance(e[1], dict) else None)
            if i is None or not 0 <= i < len(files):
                return False
            if isinstance(e, list) and ("file" in e[1] or ("project" in e[1] and len(files[i]) == 3)):
                return False
    return set(table) <= {"v", "files", "n", "cols", "refs"}


def expand(record):
    """The adapter record in its written-out shape: `units` and the unit lists rebuilt from its
    table. A record without a table — every row written before T-14568 — is returned as it is; so
    is one whose table this version cannot read or that is not whole (`_valid`). Pure."""
    if not isinstance(record, dict):
        return record
    table = record.get(KEY)
    if not isinstance(table, dict) or table.get("v") != VERSION or not _valid(table):
        return record
    files, prev = [], ""
    for ent in table["files"]:
        f = prev[:ent[0]] + ent[1]
        files.append((ent[2] if len(ent) > 2 else "", f))
        prev = f

    def _named(ident, rest):
        out = {"project": ident[0], "file": ident[1]} if ident[0] else {"file": ident[1]}
        out.update(rest)
        return out
    out = {k: v for k, v in record.items() if k != KEY}
    if "n" in table:
        n = table["n"]
        rows = [{} for _ in range(n)]
        for name, col in (table.get("cols") or {}).items():
            absent = set(col.get("a") or ())
            if "v" in col:
                for j, v in enumerate(col["v"]):
                    if j not in absent:
                        rows[j][name] = v
            else:
                for j in range(n):
                    if j not in absent:
                        rows[j][name] = col["d"]
                for j, v in col.get("x") or ():
                    rows[j][name] = v
        out["units"] = [_named(files[j], rows[j]) for j in range(n)]
    for sect, key, entries in table.get("refs") or ():
        if not isinstance(out.get(sect, {}), dict):
            return record                      # the section is no longer a dict: not this table's record
        sub = dict(out.get(sect) or {})
        sub[key] = [_named(files[e], {}) if _int(e) else _named(files[e[0]], e[1]) for e in entries]
        out[sect] = sub
    return out


def encode_layers(layers):
    """A `consumer_verify_layers` list with every layer's adapter record encoded (the list itself
    when nothing changes)."""
    if not ENABLED or not isinstance(layers, list):
        return layers
    out, changed = [], False
    for ly in layers:
        rec = ly.get("adapter") if isinstance(ly, dict) else None
        new = encode(rec) if isinstance(rec, dict) else rec
        if new is not rec:
            ly, changed = {**ly, "adapter": new}, True
        out.append(ly)
    return out if changed else layers


def expand_layer(layer):
    """A layer row with its adapter record expanded (the row itself when it has no table)."""
    rec = layer.get("adapter") if isinstance(layer, dict) else None
    new = expand(rec)
    return layer if new is rec else {**layer, "adapter": new}


def expand_row(row):
    """A journal row (`{type, data, ...}`) — or a row's `data` — with every `consumer_verify_layers`
    layer row expanded; the object itself when nothing changes. For a reader that takes whole rows."""
    if not isinstance(row, dict):
        return row
    data = row.get("data") if isinstance(row.get("data"), dict) else None
    host = data if data is not None else row
    layers = host.get("consumer_verify_layers")
    if not isinstance(layers, list):
        return row
    new = [expand_layer(ly) for ly in layers]
    if all(a is b for a, b in zip(new, layers)):
        return row
    host = {**host, "consumer_verify_layers": new}
    return {**row, "data": host} if data is not None else host


# ───────── T-14569 — THE PRE-DEPLOY SKIP RECORD: one versioned identity, membership kept (SPEC-1051 rule 2) ─────────
#
# A run's skip-set record (`land_verify_legs._pre_deploy_skip_set` / `_pre_deploy_close_skip`) is compared
# by ONE identity — `pds1:<state>:<n>:<sha256 of the sorted files of units + held as one JSON list>` —
# so two records with the same count and different members never compare equal, and a record that carries
# only an identity (a land request, a hash-only summary) compares by that identity instead of reading as
# an empty set. The identity serves EQUALITY only: a journal row keeps the COMPLETE membership, its `units`
# and `kept` written as the lossless table above (`units_table` / `kept_table`), `held` as it is.
# `SKIP` switches the writer side: off, every record is written as it always was (the disabled arm of the
# C7 differential: the journal-measure replay utility's `replay --no-skip-identity`). Readers read both.

SKIP = True
SKIP_IDENTITY_VERSION = "pds1"
#: the identity of a record that cannot be read — never equal to anything, itself included
SKIP_UNAVAILABLE = "unavailable"
_SKIP_TABLES = (("units", "units_table"), ("kept", "kept_table"))


def _canon_hash(names) -> str:
    """sha256 of a list of names as one compact JSON array — an encoding no file name can forge (a
    separator inside a name is escaped, never a boundary). Pure."""
    import hashlib
    return hashlib.sha256(json.dumps(list(names), ensure_ascii=False, separators=_SEP).encode("utf-8")).hexdigest()


def _skip_identity_of(state, files) -> str:
    names = sorted(files)
    return f"{SKIP_IDENTITY_VERSION}:{state}:{len(names)}:{_canon_hash(names)}"


def expand_skip(rec):
    """The skip record in its written-out shape: `units` / `kept` rebuilt from their tables. A record
    without a table is returned as it is; a table that does not read STAYS in the record in place of
    its list (so the record, expanded again or not, keeps reading unavailable). Pure."""
    if not isinstance(rec, dict) or not any(tk in rec for _k, tk in _SKIP_TABLES):
        return rec
    out = dict(rec)
    for key, tk in _SKIP_TABLES:
        if tk in rec:
            got = expand({KEY: rec[tk]}) if isinstance(rec[tk], dict) else None
            if isinstance(got, dict) and isinstance(got.get("units"), list) and KEY not in got:
                del out[tk]
                out[key] = got["units"]
    return out


def _files_of(entries):
    """The file names of a membership list, or None when an entry names no file. Pure."""
    out = []
    for u in entries or ():
        if not (isinstance(u, dict) and isinstance(u.get("file"), str)):
            return None
        out.append(u["file"])
    return out


def skip_identity(rec):
    """What two skip-set records are compared by (SPEC-1051 rule 2, SPEC-0065 §Bound (4)). None for no
    record (no listed class); else the versioned identity string, read from:
      a record with its membership (written out, or as tables) — computed over `units` + `held`, and
        SKIP_UNAVAILABLE when a stored `identity` disagrees with it or a table does not read;
      a request form `{state, key: [state, files]}` (written before T-14569) — computed over the key;
      a form carrying only `identity` (a land request, a hash-only summary) — that identity;
      a record with none of these — the empty set of its state, as it always read.
    Any malformed shape — a key that is not `[state, [file, ...]]`, a stored identity that is not a
    versioned string, a membership entry naming no file, a table that does not read — is
    SKIP_UNAVAILABLE, never a normalized set. Pure."""
    if not isinstance(rec, dict):
        return None
    stored = rec.get("identity")                           # validated FIRST: every form below may carry one
    if "identity" in rec and not (isinstance(stored, str) and stored.startswith(SKIP_IDENTITY_VERSION + ":")):
        return SKIP_UNAVAILABLE
    if "key" in rec:                                       # the request form written before T-14569
        key = rec["key"]
        if not (isinstance(key, list) and len(key) == 2 and isinstance(key[1], list)
                and all(isinstance(f, str) for f in key[1])):
            return SKIP_UNAVAILABLE
        got = _skip_identity_of(key[0], key[1])
        return SKIP_UNAVAILABLE if stored is not None and stored != got else got
    full = expand_skip(rec)
    if any(tk in full for _k, tk in _SKIP_TABLES):         # a table that does not read
        return SKIP_UNAVAILABLE
    if any(k in full for k in ("units", "held", "kept")):
        if any(k in full and not isinstance(full[k], list) for k in ("units", "held", "kept")):
            return SKIP_UNAVAILABLE
        files = [_files_of(full.get(k)) for k in ("units", "held")]
        if None in files:
            return SKIP_UNAVAILABLE
        got = _skip_identity_of(full.get("state"), files[0] + files[1])
        return SKIP_UNAVAILABLE if stored is not None and stored != got else got
    if stored is not None:
        return stored
    return _skip_identity_of(rec.get("state"), [])


def skip_same(a, b) -> bool:
    """Do two skip-set records (any of `skip_identity`'s forms) name the same set? Never when either
    reads unavailable. Pure."""
    ia, ib = skip_identity(a), skip_identity(b)
    return SKIP_UNAVAILABLE not in (ia, ib) and ia == ib


def skip_request(rec):
    """The request form of a skip record (`{state, identity}`; `{state, key}` with SKIP off), None for
    no record. Pure."""
    if not isinstance(rec, dict):
        return None
    if not SKIP:
        files = sorted(str(u.get("file")) for k in ("units", "held") for u in expand_skip(rec).get(k) or ()
                       if isinstance(u, dict))
        return {"state": rec.get("state"), "key": [rec.get("state"), files]}
    return {"state": rec.get("state"), "identity": skip_identity(rec)}


def encode_skip(rec):
    """The skip record as a journal row writes it: `identity` beside it, `units` and `kept` as tables
    (a list that is empty, or whose entries do not all name a file, stays as it is). The record itself
    when SKIP is off, it is not a dict, or it is already written so. Pure."""
    if not SKIP or not isinstance(rec, dict) or "identity" in rec:
        return rec
    out = dict(rec)
    for key, tk in _SKIP_TABLES:
        val = rec.get(key)
        if isinstance(val, list) and val and all(_ident(e) is not None for e in val):
            got = _encode({"units": val})
            if isinstance(got, dict) and isinstance(got.get(KEY), dict) and "units" not in got:
                out.pop(key)
                out[tk] = got[KEY]
    out["identity"] = skip_identity(rec)
    return out


def _skip_names(rec) -> list:
    """The test file names a skip record leaves out on a remote venue — the rule of
    `remote_verify.pre_deploy_skip_names` (a `tests/<name>` unit of a `skipping` record), restated
    here only because this leaf cannot import that module. Pure."""
    rec = expand_skip(rec)
    if not isinstance(rec, dict) or rec.get("state") != "skipping":
        return []
    out = set()
    for u in rec.get("units") or ():
        f = u.get("file") if isinstance(u, dict) else None
        if isinstance(f, str) and f.startswith("tests/") and "/" not in f[6:] and f[6:]:
            out.add(f[6:])
    return sorted(out)


def _names_ref(names) -> dict:
    return {"as": "pre_deploy_skip", "n": len(names), "sha256": _canon_hash(names)}


def venue_skipped_names(vm):
    """The names a venue's candidate leg left out, from a row's `verify_metrics` in either shape: the
    list (`venue_pre_deploy_skipped`), or the reference to the same row's skip record
    (`venue_pre_deploy_skipped_ref`) resolved and VERIFIED by its count and hash. None when absent;
    SKIP_UNAVAILABLE when the reference does not verify. Pure."""
    if not isinstance(vm, dict):
        return None
    if isinstance(vm.get("venue_pre_deploy_skipped"), list):
        return vm["venue_pre_deploy_skipped"]
    ref = vm.get("venue_pre_deploy_skipped_ref")
    if ref is None:
        return None
    names = _skip_names(vm.get("pre_deploy_skip"))
    return names if isinstance(ref, dict) and ref == _names_ref(names) else SKIP_UNAVAILABLE


def encode_skip_row(data):
    """A journal row's data with its skip evidence written compactly (SKIP on): `verify_metrics`'
    `pre_deploy_skip` by `encode_skip`; its `venue_pre_deploy_skipped` list replaced by a verified
    reference to that same record when the two name the same files; and `verify_forecast.request`'s
    skip key by its identity. The data itself when nothing changes. Pure."""
    if not SKIP or not isinstance(data, dict):
        return data
    out = data
    vm = data.get("verify_metrics")
    if isinstance(vm, dict):
        new = dict(vm)
        if isinstance(vm.get("pre_deploy_skip"), dict):
            new["pre_deploy_skip"] = encode_skip(vm["pre_deploy_skip"])
        names = vm.get("venue_pre_deploy_skipped")
        if isinstance(names, list) and names and isinstance(vm.get("pre_deploy_skip"), dict) \
                and sorted(names) == names and names == _skip_names(vm["pre_deploy_skip"]):
            del new["venue_pre_deploy_skipped"]
            new["venue_pre_deploy_skipped_ref"] = _names_ref(names)
        if new != vm:
            out = {**out, "verify_metrics": new}
    vf = data.get("verify_forecast")
    req = vf.get("request") if isinstance(vf, dict) else None
    pds = req.get("pre_deploy_skip") if isinstance(req, dict) else None
    if isinstance(pds, dict) and "key" in pds:
        out = {**out, "verify_forecast": {**vf, "request": {**req, "pre_deploy_skip": {
            "state": pds.get("state"), "identity": skip_identity(pds)}}}}
    return out


def encode_skip_detail(detail):
    """An `admission_step` detail list with each answer's `request.pre_deploy_skip` key written as its
    identity (SKIP on) — the credit answer's request is the same request a land row carries. The
    detail itself when nothing changes. Pure."""
    if not SKIP or not isinstance(detail, list):
        return detail
    out, changed = [], False
    for ans in detail:
        req = ans.get("request") if isinstance(ans, dict) else None
        pds = req.get("pre_deploy_skip") if isinstance(req, dict) else None
        if isinstance(pds, dict) and "key" in pds:
            ans = {**ans, "request": {**req, "pre_deploy_skip": {"state": pds.get("state"),
                                                                 "identity": skip_identity(pds)}}}
            changed = True
        out.append(ans)
    return out if changed else detail
