"""Consistent UTC JSON timestamps, including SQLite's timezone-naive UTC values."""

from datetime import UTC, datetime

from pydantic import BaseModel, field_serializer


class UtcSchema(BaseModel):
    @field_serializer("*", when_used="json")
    def serialize_utc_timestamp(self, value: object) -> object:
        if isinstance(value, datetime):
            # All persisted timestamps are written in UTC; SQLite drops timezone metadata.
            timestamp = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            return timestamp.isoformat()
        return value
