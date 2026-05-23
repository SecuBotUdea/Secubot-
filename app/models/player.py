from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PlayerRecord(BaseModel):
    user_id: str
    guild_id: str
    points: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_document(self) -> dict[str, Any]:
        return self.model_dump()
