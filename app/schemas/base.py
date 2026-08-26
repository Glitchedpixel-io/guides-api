"""Base model, timestamp handling, and shared mixins for the API schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

Timestamp = Annotated[datetime, AwareDatetime]


class UTCBaseModel(BaseModel):
    """Base schema that normalises every aware datetime to UTC.

    Mixed offsets reaching the renderer would print two different edition dates for the
    same instant, so coercion happens once, here, rather than at each call site.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_utc(cls, data: Any) -> Any:
        """Convert aware datetimes on the incoming payload to UTC.

        Args:
            data: The raw input, which may be a mapping or an arbitrary object.

        Returns:
            Any: The input, with aware datetimes converted to UTC.
        """
        if not isinstance(data, dict):
            return data
        for key, value in data.items():
            if isinstance(value, datetime) and value.tzinfo is not None:
                data[key] = value.astimezone(timezone.utc)
        return data


class IDMixin(BaseModel):
    """Adds the surrogate primary key to a read schema."""

    id: int


class TimestampsMixin(BaseModel):
    """Adds the server-maintained timestamps to a read schema."""

    created_at: Timestamp
    updated_at: Timestamp


class OrderedItem(BaseModel):
    """A single entry in a reorder request.

    Attributes:
        id: The row being placed.
        position: Its new 1-based position.
    """

    id: int
    position: int


class ReorderRequest(UTCBaseModel):
    """A complete reordering of a collection.

    The list must name every member exactly once — a partial reorder is ambiguous about
    where the omitted rows go, and silently guessing is how orders drift.
    """

    items: list[OrderedItem]
