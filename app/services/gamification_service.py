from __future__ import annotations

from app.database.connection import AlertAlreadyResolvedError, AlertNotFoundError, points_for_severity
from app.models.alert import AlertRecord
from app.models.point_log import PointLogRecord
from app.schemas.common import AlertPayload, RescanResultPayload


class GamificationService:
    def __init__(self, alert_repository, player_repository, point_log_repository) -> None:
        self.alert_repository = alert_repository
        self.player_repository = player_repository
        self.point_log_repository = point_log_repository

    async def handle_alert(self, payload: AlertPayload) -> dict:
        alert = AlertRecord(
            alert_id=payload.alert_id,
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            severity=payload.severity,
            source=payload.source,
            description=payload.description,
        )
        await self.alert_repository.upsert_alert(alert)
        return {"status": "received", "alert_id": payload.alert_id}

    async def handle_rescan_result(self, payload: RescanResultPayload) -> dict:
        alert = await self.alert_repository.get_alert(payload.alert_id)
        if alert is None:
            raise AlertNotFoundError(payload.alert_id)
        if alert.get("status") == "resolved":
            raise AlertAlreadyResolvedError(payload.alert_id)

        if payload.status != "valid":
            return {"status": "no_points", "alert_id": payload.alert_id}

        severity = alert.get("severity")
        guild_id = alert.get("guild_id")
        points = points_for_severity(severity)

        await self.player_repository.add_points(payload.user_id, guild_id, points)
        await self.alert_repository.resolve_alert(payload.alert_id, resolved_by=payload.user_id)
        await self.point_log_repository.add_log(
            PointLogRecord(
                user_id=payload.user_id,
                guild_id=guild_id,
                alert_id=payload.alert_id,
                points=points,
            )
        )

        return {"status": "points_awarded", "points": points, "alert_id": payload.alert_id}

    async def get_player_detail(self, guild_id: str, user_id: str) -> dict | None:
        player = await self.player_repository.get_player(user_id, guild_id)
        if player is None:
            return None

        leaderboard = await self.player_repository.get_leaderboard(guild_id)
        rank = next(
            (idx + 1 for idx, p in enumerate(leaderboard) if p["user_id"] == user_id),
            len(leaderboard),
        )

        logs = await self.point_log_repository.get_logs_for_user(user_id, guild_id)
        return {
            "user_id": user_id,
            "guild_id": guild_id,
            "points": player["points"],
            "rank": rank,
            "point_logs": [
                {"alert_id": l["alert_id"], "points": l["points"], "timestamp": l["timestamp"].isoformat() if hasattr(l["timestamp"], "isoformat") else str(l["timestamp"])}
                for l in logs
            ],
        }

    async def get_leaderboard(self, guild_id: str) -> list[dict]:
        players = await self.player_repository.get_leaderboard(guild_id)
        return [
            {"user_id": p["user_id"], "points": p["points"], "rank": idx + 1}
            for idx, p in enumerate(players)
        ]
