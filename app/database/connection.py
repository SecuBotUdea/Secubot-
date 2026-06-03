from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.models.player import PlayerRecord
from app.models.point_log import PointLogRecord
from app.models.remediation import RemediationRecord

logger = logging.getLogger(__name__)

_POINTS_BY_SEVERITY: dict[str, int] = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
}


def points_for_severity(severity: str | None) -> int:
    if severity:
        return _POINTS_BY_SEVERITY.get(severity.lower(), 10)
    return 10


class InMemoryPlayerRepository:
    def __init__(self) -> None:
        self._players: dict[str, dict[str, Any]] = {}

    def _key(self, user_id: str, team_id: str) -> str:
        return f"{user_id}:{team_id}"

    async def add_points(self, user_id: str, team_id: str, points: int) -> None:
        key = self._key(user_id, team_id)
        now = datetime.now(timezone.utc)
        if key not in self._players:
            self._players[key] = PlayerRecord(
                user_id=user_id, team_id=team_id, points=0
            ).to_document()
            self._players[key]["created_at"] = now
        self._players[key]["points"] += points
        self._players[key]["updated_at"] = now

    async def get_player(self, user_id: str, team_id: str) -> dict[str, Any] | None:
        return self._players.get(self._key(user_id, team_id))

    async def get_leaderboard(self, team_id: str) -> list[dict[str, Any]]:
        guild_players = [p for p in self._players.values() if p["team_id"] == team_id]
        return sorted(guild_players, key=lambda p: p["points"], reverse=True)


class InMemoryPointLogRepository:
    def __init__(self) -> None:
        self._logs: list[dict[str, Any]] = []

    async def add_log(self, log: PointLogRecord) -> None:
        self._logs.append(log.to_document())

    async def get_logs_for_user(self, user_id: str, team_id: str) -> list[dict[str, Any]]:
        return [l for l in self._logs if l["user_id"] == user_id and l["team_id"] == team_id]


class MongoPlayerRepository:
    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def add_points(self, user_id: str, team_id: str, points: int) -> None:
        now = datetime.now(timezone.utc)
        await self._collection.update_one(
            {"user_id": user_id, "team_id": team_id},
            {
                "$inc": {"points": points},
                "$set": {"updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def get_player(self, user_id: str, team_id: str) -> dict[str, Any] | None:
        return await self._collection.find_one({"user_id": user_id, "team_id": team_id})

    async def get_leaderboard(self, team_id: str) -> list[dict[str, Any]]:
        cursor = self._collection.find({"team_id": team_id}).sort("points", -1).limit(10)
        return await cursor.to_list(length=10)


class MongoPointLogRepository:
    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def add_log(self, log: PointLogRecord) -> None:
        await self._collection.insert_one(log.to_document())

    async def get_logs_for_user(self, user_id: str, team_id: str) -> list[dict[str, Any]]:
        cursor = self._collection.find({"user_id": user_id, "team_id": team_id}).sort("timestamp", -1)
        return await cursor.to_list(length=100)


_VALID_STATUSES = {"fixed", "resolved"}


class InMemoryRemediationRepository:
    def __init__(self) -> None:
        self._remediations: list[dict[str, Any]] = []

    async def add_remediation(self, remediation: RemediationRecord) -> None:
        self._remediations.append(remediation.to_document())

    async def get_remediations_for_user(self, user_id: str, team_id: str) -> list[dict[str, Any]]:
        return [r for r in self._remediations if r["user_id"] == user_id and r["team_id"] == team_id]

    async def count_invalid_attempts(self, alert_id: str, user_id: str) -> int:
        return sum(
            1 for r in self._remediations
            if r["alert_id"] == alert_id and r["user_id"] == user_id and r["status"] not in _VALID_STATUSES
        )


class MongoRemediationRepository:
    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def add_remediation(self, remediation: RemediationRecord) -> None:
        await self._collection.insert_one(remediation.to_document())

    async def get_remediations_for_user(self, user_id: str, team_id: str) -> list[dict[str, Any]]:
        cursor = self._collection.find({"user_id": user_id, "team_id": team_id}).sort("attempted_at", -1)
        return await cursor.to_list(length=100)

    async def count_invalid_attempts(self, alert_id: str, user_id: str) -> int:
        return await self._collection.count_documents({
            "alert_id": alert_id,
            "user_id": user_id,
            "status": {"$nin": list(_VALID_STATUSES)},
        })


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.client: AsyncIOMotorClient | None = None
        self.player_repository: InMemoryPlayerRepository | MongoPlayerRepository = InMemoryPlayerRepository()
        self.point_log_repository: InMemoryPointLogRepository | MongoPointLogRepository = InMemoryPointLogRepository()
        self.remediation_repository: InMemoryRemediationRepository | MongoRemediationRepository = InMemoryRemediationRepository()
        self.database_connected: bool = False
        self.using_fallback: bool = True

    async def _connect_mongo(self) -> None:
        self.client = AsyncIOMotorClient(self.database_url, serverSelectionTimeoutMS=3000)
        await self.client.admin.command("ping")

    async def connect(self) -> None:
        if self.database_url.startswith("memory://"):
            logger.warning("Using in-memory database backend")
            self.database_connected = True
            self.using_fallback = True
            return

        try:
            await self._connect_mongo()
            db = self.client.get_default_database()
            self.player_repository = MongoPlayerRepository(db["players"])
            self.point_log_repository = MongoPointLogRepository(db["point_logs"])
            self.remediation_repository = MongoRemediationRepository(db["remediations"])
            self.database_connected = True
            self.using_fallback = False
        except Exception as exc:  # pragma: no cover
            logger.exception("Database connection failed, switching to fallback backend: %s", exc)
            self.player_repository = InMemoryPlayerRepository()
            self.point_log_repository = InMemoryPointLogRepository()
            self.database_connected = True
            self.using_fallback = True
