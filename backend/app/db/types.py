"""Shared column types."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Dialect, Enum
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """`timestamptz` that only accepts timezone-aware datetimes and always returns UTC.

    Every instant is stored in UTC; conversion to APP_TIMEZONE happens in the service layer.
    Wall-clock values (a weekly class at 09:00) are stored as `time`/`date`, not here.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Naive datetime {value!r} is not allowed; use an aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def str_enum[E: StrEnum](enum_cls: type[E], name: str) -> Enum:
    """VARCHAR + CHECK constraint (no native PG enum: adding values needs no ALTER TYPE)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum_cls),
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
