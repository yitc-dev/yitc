---
name: audit-trail-field-level
class: architecture
sourced_from: <host-home>/knowledge/patterns/audit-trail-field-level.md
applies_to: business entities where users need to answer «who changed field X on entity Y, when, and to what»; pair with `fsm-enum-whitelist` for status changes
---

# Field-Level Audit Trail

## Problem

Need to know who changed what and when. Row-level audit (JSON snapshot of whole row before/after) is bloated and hard to query — answering «who changed `email` on this account?» requires parsing JSON diffs across hundreds of rows.

## Solution

One audit table at **field granularity**:

- `entity_type` + `entity_id` — which entity
- `field_name` — which field
- `old_value` / `new_value` — serialized to Text
- `action` — `update` or `delete`
- `user_id` — who did it
- timestamps via `TimestampMixin`

A service function `audit_update(entity, updates_dict)` compares old vs new per field, calls `setattr`, and creates one `AuditRecord` per actually-changed field (skips equality + skips auto-managed fields).

## Example

**Model:**

```python
class AuditRecord(Base, UUIDPrimaryKey, TenantMixin, TimestampMixin):
    __tablename__ = "audit_records"
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    field_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(10)) # "update", "delete"
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
```

**Service:**

```python
_SKIP_FIELDS = frozenset({"updated_at", "created_at"})

def _serialize(value):
    if value is None: return None
    if isinstance(value, uuid.UUID): return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)

async def audit_update(session, entity, updates, *, tenant_id, user_id=None):
    changed = []
    for field, new_value in updates.items:
        if field in _SKIP_FIELDS:
            continue
        old_value = getattr(entity, field, None)
        if old_value == new_value:
            continue
        setattr(entity, field, new_value)
        session.add(AuditRecord(
            tenant_id=tenant_id, user_id=user_id,
            entity_type=entity.__tablename__.rstrip("s"),
            entity_id=entity.id, field_name=field, action="update",
            old_value=_serialize(old_value), new_value=_serialize(new_value)))
        changed.append(field)
    return changed

async def audit_delete(session, entity, *, tenant_id, user_id=None):
    session.add(AuditRecord(
        tenant_id=tenant_id, user_id=user_id,
        entity_type=entity.__tablename__.rstrip("s"),
        entity_id=entity.id, field_name="*", action="delete"))
```

**Endpoint usage:**

```python
changed = await audit_update(
    session, account, updates,
    tenant_id=current_user.tenant_id,
    user_id=current_user.id)
# changed == ["email", "phone"] — only fields that actually changed
```

## Separation from FSM audit

| What | Table | Pattern |
|---|---|---|
| arbitrary field changes | `audit_records` | this pattern |
| status transitions | `status_transitions` | `fsm-enum-whitelist` |
| soft-delete event | `audit_records` (action=delete, field_name="*") | this pattern |

## Anti-pattern

- Row-level JSON snapshots — bloat, hard to query, replicates the entire row even on single-field changes
- Audit in the same transaction as business logic for external-cost work — rollback erases proof of paid call; see `batch-operation-resilience` for the separate-transaction discipline
- Skip equality check — generates empty no-op audit rows, dilutes the trail
- Skip auto-managed fields (`updated_at`, `created_at`) — every update generates 2 noise rows
- Direct `setattr` in endpoints, bypassing the audit service — gradually accumulates untracked changes

## When NOT to apply

- Very high-throughput tables (thousands of updates / second) — per-field overhead becomes a bottleneck
- Fields with no business meaning (caches, counters)

## Cites

- v1 source: audit model + audit service in a production CMS project
- Related: `fsm-enum-whitelist` (status changes go through separate `status_transitions` table), `soft-delete` (delete recorded as audit entry with `field_name="*"`)
