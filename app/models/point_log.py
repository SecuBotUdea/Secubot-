from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PointLogRecord(BaseModel):
    user_id: str
    team_id: str
    alert_id: str
    points: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_document(self) -> dict[str, Any]:
        return self.model_dump()
