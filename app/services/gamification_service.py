from __future__ import annotations

import logging

from app.database.connection import points_for_severity
from app.models.point_log import PointLogRecord
from app.models.remediation import RemediationRecord
from app.schemas.common import RescanResultPayload

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"fixed", "resolved"}


class GamificationService:
    def __init__(self, player_repository, point_log_repository, gloria_service=None, remediation_repository=None) -> None:
        self.player_repository = player_repository
        self.point_log_repository = point_log_repository
        self.remediation_repository = remediation_repository
        self._gloria = gloria_service

    async def handle_rescan_result(self, payload: RescanResultPayload) -> dict:
        team_id = payload.team_id
        is_valid = payload.status in _VALID_STATUSES

        if not is_valid:
            await self._log_remediation(
                alert_id=payload.alert_id,
                user_id=payload.user_id,
                team_id=team_id,
                status=payload.status,
                points_awarded=0,
            )
            await self._notify_gloria(
                team_id=team_id,
                alert_id=payload.alert_id,
                user_id=payload.user_id,
                status=payload.status,
                points=0,
            )
            return {"status": "no_points", "alert_id": payload.alert_id}

        points = points_for_severity(payload.severity)

        await self.player_repository.add_points(payload.user_id, team_id, points)
        await self.point_log_repository.add_log(
            PointLogRecord(
                user_id=payload.user_id,
                team_id=team_id,
                alert_id=payload.alert_id,
                points=points,
            )
        )
        await self._log_remediation(
            alert_id=payload.alert_id,
            user_id=payload.user_id,
            team_id=team_id,
            status=payload.status,
            points_awarded=points,
        )
        await self._notify_gloria(
            team_id=team_id,
            alert_id=payload.alert_id,
            user_id=payload.user_id,
            status=payload.status,
            points=points,
        )

        return {"status": "points_awarded", "points": points, "alert_id": payload.alert_id}

    async def _log_remediation(self, alert_id: str, user_id: str, team_id: str, status: str, points_awarded: int) -> None:
        if self.remediation_repository is None:
            return
        await self.remediation_repository.add_remediation(
            RemediationRecord(
                alert_id=alert_id,
                user_id=user_id,
                team_id=team_id,
                status=status,
                points_awarded=points_awarded,
            )
        )

    async def _notify_gloria(self, **kwargs) -> None:
        if self._gloria is None:
            return
        try:
            await self._gloria.notify_rescan_result(**kwargs)
        except Exception:
            logger.exception("Failed to notify Gloria; rescan result was already persisted")

    async def get_player_detail(self, team_id: str, user_id: str) -> dict | None:
        player = await self.player_repository.get_player(user_id, team_id)
        if player is None:
            return None

        leaderboard = await self.player_repository.get_leaderboard(team_id)
        rank = next(
            (idx + 1 for idx, p in enumerate(leaderboard) if p["user_id"] == user_id),
            len(leaderboard),
        )

        logs = await self.point_log_repository.get_logs_for_user(user_id, team_id)
        return {
            "user_id": user_id,
            "team_id": team_id,
            "points": player["points"],
            "rank": rank,
            "point_logs": [
                {"alert_id": l["alert_id"], "points": l["points"], "timestamp": l["timestamp"].isoformat() if hasattr(l["timestamp"], "isoformat") else str(l["timestamp"])}
                for l in logs
            ],
        }

    async def get_leaderboard(self, team_id: str) -> list[dict]:
        players = await self.player_repository.get_leaderboard(team_id)
        return [
            {"user_id": p["user_id"], "points": p["points"], "rank": idx + 1}
            for idx, p in enumerate(players)
        ]
