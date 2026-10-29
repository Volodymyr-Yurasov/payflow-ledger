"""The part of an event every type shares. Failing this means we can't even identify
the event (no id to dedupe on), so the request is answered with 400."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints

EventId = Annotated[StrictStr, StringConstraints(min_length=1, max_length=255)]


class Envelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: EventId
    type: EventId
    # Validated per type (see schemas/events.py): unknown types may shape these freely.
    created_at: Any = None
    data: Any = None
