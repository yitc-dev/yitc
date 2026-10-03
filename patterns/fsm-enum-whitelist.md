---
name: fsm-enum-whitelist
class: architecture
sourced_from: <host-home>/knowledge/patterns/fsm-enum-whitelist.md
applies_to: business entities with >2 statuses, multi-step lifecycles, or where invalid status transitions must be blocked at the domain layer
---

# FSM via Enum + Whitelist Transitions

## Problem

Business entities pass via a chain of statuses (order, task, document). Without explicit transition control:
- Code permits invalid transitions (e.g. «completed» → «draft»)
- Transition logic is smeared across services + endpoints
- No single place to understand the entity's lifecycle
- Cannot build a transition audit trail

## Solution

Two components separated by responsibility:

1. **Enum + whitelist dict** (domain layer) — defines ALL valid statuses and ALL valid transitions. Pure data, no logic.
2. **FSM service** (domain service) — validates the transition against the whitelist, applies it, sets side-effect timestamps, returns the audit record.

Key principle: **whitelist, not blacklist**. If a transition is not in the dict, it is forbidden. Terminal statuses = empty `set`.

## Example

**Enum + whitelist:**

```python
from enum import StrEnum

class OrderStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.ACTIVE, OrderStatus.CANCELLED},
    OrderStatus.ACTIVE: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set, # terminal
    OrderStatus.CANCELLED: set, # terminal
}
```

Rules:
- Each enum value MUST appear as a key in the transitions dict — otherwise `.get` returns `set` and silently blocks all transitions
- Terminal statuses = `set`, not absent
- One enum, one dict, stored side-by-side

**FSM service:**

```python
class InvalidTransitionError(Exception):
    def __init__(self, entity: str, current: str, target: str):
        super.__init__(f"{entity}: transition {current} -> {target} is not allowed")

def transition_order(order, target, reason=None, user_id=None) -> StatusTransition:
    current = OrderStatus(order.status)
    if target not in ORDER_TRANSITIONS.get(current, set):
        raise InvalidTransitionError("Order", current, target)

    now = datetime.now(timezone.utc)
    from_status = order.status
    order.status = target

    if target == OrderStatus.ACTIVE:
        order.activated_at = now
    elif target == OrderStatus.COMPLETED:
        order.completed_at = now

    return StatusTransition(
        entity_type="order",
        entity_id=order.id,
        from_status=from_status,
        to_status=target.value,
        reason=reason,
        created_by=user_id)
```

**Single audit table:**

```python
class StatusTransition(Base, UUIDPrimaryKey, TenantMixin):
    __tablename__ = "status_transitions"
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    from_status: Mapped[str]
    to_status: Mapped[str]
    reason: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now")
```

One table for all entities (filter by `entity_type`). No per-entity transition tables.

## Anti-pattern

- Plain `Enum` instead of `StrEnum` — values stored as integers/objects, not strings; queries break
- Missing key in transitions dict — `.get` returns `set`; all transitions silently blocked
- Putting side-effect timestamps in endpoints — duplicate logic, easy to forget on new entry-points
- Generic transition function across all entity types — side-effects differ per entity; abstraction premature

## When NOT to apply

- Only 2 statuses (active/inactive) — a boolean column is enough
- No business rules around transitions + no audit need — plain update suffices

## Cites

- v1 source: domain enums + FSM service from a production CMS project
- Related: `audit-trail-field-level` (field-level audit complements transition audit), `soft-delete` («deleted» as terminal status — alternative encoding)
