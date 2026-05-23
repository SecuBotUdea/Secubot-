from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]


class AlertPayload(BaseModel):
    alert_id: str
    guild_id: str
    channel_id: str | None = None
    severity: Severity | None = None
    source: str | None = None
    description: str | None = None


class RescanResultPayload(BaseModel):
    alert_id: str
    user_id: str
    status: str = Field(description="'valid' si la corrección fue aceptada por el Parser, cualquier otro valor se trata como inválido")


class LeaderboardEntry(BaseModel):
    user_id: str
    points: int
    rank: int


class PointLogEntry(BaseModel):
    alert_id: str
    points: int
    timestamp: str


class PlayerDetail(BaseModel):
    user_id: str
    guild_id: str
    points: int
    rank: int
    point_logs: list[PointLogEntry]


class HealthResponse(BaseModel):
    status: str = Field(description="healthy / degraded")
    database_connected: bool
    timestamp: str
