"""Undo infrastructure: every mutation made by an agent tool is logged with before/after
snapshots under the change_set_id of the user message that caused it. undo_change_set()
reverts a whole set (all yavers' changes from that message) in reverse order.
"""

import datetime as dt
import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper

from app.db.base import Base
from app.db.models import ChangeLog
from app.db.models.enums import ChangeOp

# Server-managed columns are not restored by undo.
_SKIPPED_COLUMNS = {"updated_at"}


class NothingToUndoError(Exception):
    pass


def _to_json(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    return value


def snapshot(obj: Base) -> dict[str, Any]:
    mapper: Mapper[Any] = inspect(type(obj))
    return {
        attr.key: _to_json(getattr(obj, attr.key))
        for attr in mapper.column_attrs
        if attr.key not in _SKIPPED_COLUMNS
    }


def _from_json(model: type[Base], key: str, value: Any) -> Any:
    if value is None:
        return None
    column_type = inspect(model).columns[key].type
    # TypeDecorators (UTCDateTime) report their type through the wrapped implementation.
    column_type = getattr(column_type, "impl_instance", column_type)
    if isinstance(column_type, SAEnum) and column_type.enum_class is not None:
        return column_type.enum_class(value)
    try:
        python_type = column_type.python_type
    except NotImplementedError:
        return value
    if python_type is dt.datetime:
        return dt.datetime.fromisoformat(value)
    if python_type is dt.date:
        return dt.date.fromisoformat(value)
    if python_type is dt.time:
        return dt.time.fromisoformat(value)
    if python_type in (Decimal, uuid.UUID):
        return python_type(value)
    return value


def _model_for_table(table: str) -> type[Base]:
    for mapper in Base.registry.mappers:
        if mapper.local_table.name == table:  # type: ignore[attr-defined]
            model: type[Base] = mapper.class_
            return model
    raise KeyError(f"no model for table {table!r}")


class ChangeRecorder:
    """Collects changes for one change set inside the caller's transaction."""

    def __init__(self, session: AsyncSession, change_set_id: uuid.UUID) -> None:
        self.session = session
        self.change_set_id = change_set_id
        self.agent_id: str | None = None
        self.entries: list[ChangeLog] = []

    def _add(self, obj: Base, op: ChangeOp, before: dict[str, Any] | None) -> None:
        after = None if op is ChangeOp.DELETE else snapshot(obj)
        entry = ChangeLog(
            change_set_id=self.change_set_id,
            entity=obj.__tablename__,
            entity_id=getattr(obj, "id"),  # noqa: B009 - every model has an int id
            op=op,
            before_json=before,
            after_json=after,
            agent_id=self.agent_id,
        )
        self.session.add(entry)
        self.entries.append(entry)

    async def created(self, obj: Base) -> None:
        """Call after session.add(obj); flushes to get the id and server defaults."""
        await self.session.flush()
        await self.session.refresh(obj)
        self._add(obj, ChangeOp.CREATE, None)

    def before_update(self, obj: Base) -> dict[str, Any]:
        return snapshot(obj)

    async def updated(self, obj: Base, before: dict[str, Any]) -> None:
        await self.session.flush()
        self._add(obj, ChangeOp.UPDATE, before)

    async def deleted(self, obj: Base) -> None:
        before = snapshot(obj)
        await self.session.delete(obj)
        await self.session.flush()
        entry = ChangeLog(
            change_set_id=self.change_set_id,
            entity=obj.__tablename__,
            entity_id=before["id"],
            op=ChangeOp.DELETE,
            before_json=before,
            after_json=None,
            agent_id=self.agent_id,
        )
        self.session.add(entry)
        self.entries.append(entry)


# Fields worth showing on a change card (from the after / before snapshot).
_CARD_FIELDS = (
    "title",
    "kind",
    "weekday",
    "start_time",
    "end_time",
    "date",
    "action",
    "new_start_at",
    "new_end_at",
    "start_at",
    "end_at",
    "all_day",
    "status",
    "content",
    "code",
    "name",
    "absence_limit",
    "week_start",
    "reason",
)


async def describe_changes(session: AsyncSession, entries: list[ChangeLog]) -> list[dict[str, Any]]:
    """Compact, UI-friendly view of a change set; overrides / attendance get the name of the
    block / course they belong to."""
    described = []
    for entry in entries:
        snapshot = entry.after_json or entry.before_json or {}
        data = {key: snapshot[key] for key in _CARD_FIELDS if snapshot.get(key) is not None}
        if entry.entity == "block_overrides" and snapshot.get("block_id"):
            block = await session.get(_model_for_table("recurring_blocks"), snapshot["block_id"])
            data["title"] = getattr(block, "title", None)
        if entry.entity == "attendance" and snapshot.get("course_id"):
            course = await session.get(_model_for_table("courses"), snapshot["course_id"])
            data["course"] = getattr(course, "code", None)
        described.append(
            {
                "entity": entry.entity,
                "op": entry.op.value,
                "agent_id": entry.agent_id,
                "data": data,
                "undone": entry.undone_at is not None,
            }
        )
    return described


async def latest_change_set(
    session: AsyncSession, exclude: uuid.UUID | None = None
) -> uuid.UUID | None:
    """Most recent change set that still has changes not undone."""
    query = (
        select(ChangeLog.change_set_id)
        .where(ChangeLog.undone_at.is_(None))
        .group_by(ChangeLog.change_set_id)
        .order_by(func.max(ChangeLog.id).desc())
        .limit(1)
    )
    if exclude is not None:
        query = query.where(ChangeLog.change_set_id != exclude)
    result: uuid.UUID | None = await session.scalar(query)
    return result


async def undo_change_set(
    session: AsyncSession, change_set_id: uuid.UUID, now: dt.datetime
) -> list[ChangeLog]:
    """Revert every not-yet-undone change of a set, newest first. Returns the entries."""
    entries = list(
        (
            await session.scalars(
                select(ChangeLog)
                .where(ChangeLog.change_set_id == change_set_id, ChangeLog.undone_at.is_(None))
                .order_by(ChangeLog.id.desc())
            )
        ).all()
    )
    if not entries:
        raise NothingToUndoError(str(change_set_id))
    for entry in entries:
        model = _model_for_table(entry.entity)
        current = await session.get(model, entry.entity_id)
        if entry.op is ChangeOp.CREATE:
            if current is not None:
                await session.delete(current)
        elif entry.op is ChangeOp.UPDATE:
            if current is not None and entry.before_json is not None:
                for key, value in entry.before_json.items():
                    setattr(current, key, _from_json(model, key, value))
        elif entry.op is ChangeOp.DELETE and current is None and entry.before_json is not None:
            session.add(model(**{k: _from_json(model, k, v) for k, v in entry.before_json.items()}))
        await session.flush()
        entry.undone_at = now
    await session.flush()
    return entries
