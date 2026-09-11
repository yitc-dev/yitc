---
name: soft-delete
class: architecture
sourced_from: <host-home>/knowledge/patterns/soft-delete.md
applies_to: any database entity where deletion needs audit trail, recoverability, or referential preservation; mandatory if business reports include past periods
---

# Soft Delete + Partial Unique Index

## Problem

Hard-deleting rows is irreversible. For business systems that breaks:
- Audit (who deleted what and when)
- Recovery
- Historical reports that aggregate past periods
- Cascading hard-deletes can lose linked data unexpectedly

## Solution

Mixin pattern: `SoftDeleteMixin` adds nullable `deleted_at` timestamp. Deletion = set timestamp. Every SELECT filters `WHERE deleted_at IS NULL`.

**Critical companion rule:** every unique constraint on a soft-deletable table MUST be expressed as a **partial unique index** with `WHERE deleted_at IS NULL`. Plain `UniqueConstraint` blocks recreation after soft-delete — user deletes record, can't recreate with same key, gets 409.

## Example

**Mixin:**

```python
class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True)
```

**Partial unique index (correct form):**

```python
__table_args__ = (
    Index(
        "ix_channel_handle_active",
        "tenant_id", "handle",
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL")))
```

**Soft-delete operation:**

```python
async def soft_delete(session, entity, *, tenant_id, user_id=None):
    entity.deleted_at = datetime.now(timezone.utc)
    await audit_delete(session, entity, tenant_id=tenant_id, user_id=user_id)
```

**Cascading soft-delete:**

```python
async def soft_delete_parent(session, parent, *, tenant_id, user_id):
    parent.deleted_at = datetime.now(timezone.utc)
    stmt = (
        update(ChildLink)
.where(ChildLink.parent_id == parent.id, ChildLink.deleted_at.is_(None))
.values(deleted_at=datetime.now(timezone.utc))
)
    await session.execute(stmt)
```

## Anti-pattern

- Plain `UniqueConstraint("tenant_id", "handle")` on a soft-deletable table — blocks recreation after delete, user gets 409 Conflict trying to recreate the same key
- Forgetting `.where(Model.deleted_at.is_(None))` on a SELECT — ghost rows leak into lists, dropdowns, aggregations
- Calling `session.delete(entity)` instead of soft-delete — bypasses the entire mechanism
- Skipping cascade — orphan children with active `deleted_at IS NULL` reference a deleted parent

## When NOT to apply

- Append-only log/event tables — deletion not expected
- High-churn tables (millions of rows, frequent delete) — soft-deleted rows bloat indexes; use partitioning or archival instead

## Adoption checklist

- [ ] Add `SoftDeleteMixin` to the model
- [ ] **Convert ALL `UniqueConstraint` to partial unique `Index` with `postgresql_where`**
- [ ] Add `.where(Model.deleted_at.is_(None))` to every SELECT
- [ ] DELETE endpoints → soft-delete (set `deleted_at`, never `session.delete`)
- [ ] Cascade soft-delete on dependent rows
- [ ] Record `action="delete"` audit entry
- [ ] Alembic migration: add column + recreate constraints as partial indexes
- [ ] Aggregate queries (SUM/COUNT) — exclude soft-deleted

## Cites

- v1 incident: a production CMS project's B-376 — soft-delete without partial unique index → user deletes a channel, cannot recreate it, sees 409
- Related: `audit-trail-field-level` (records deletion as audit entry), `timezone-utc-database` (`deleted_at` uses `DateTime(timezone=True)`), `fsm-enum-whitelist` (alternative: «deleted» as terminal FSM state)
