from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "informational", "unknown"]


class RescanResultPayload(BaseModel):
    alert_id: str
    source_type: str | None = None
    source_id: str | None = None
    title: str | None = None
    severity: Severity | None = None
    status: str = Field(description="'fixed' o 'resolved' otorgan puntos; cualquier otro valor se trata como inválido")
    component: str | None = None
    location: str | None = None
    external_references_score: float | None = None
    normalized_payload: dict = Field(default_factory=dict)
    team_id: str
    team_name: str | None = None
    user_id: str | None = None


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
    team_id: str
    points: int
    rank: int
    point_logs: list[PointLogEntry]


class HealthResponse(BaseModel):
    status: str = Field(description="healthy / degraded")
    database_connected: bool
    timestamp: str
