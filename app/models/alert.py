from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AlertRecord(BaseModel):
    alert_id: str
    guild_id: str
    channel_id: str | None = None
    severity: str | None = None
    source: str | None = None
    description: str | None = None
    status: str = "open"
    resolved_by: str | None = None
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None

    def to_document(self) -> dict[str, Any]:
        return self.model_dump()
