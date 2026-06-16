from __future__ import annotations

import httpx

_VALID_STATUSES = {"fixed", "resolved"}


class GloriaService:
    _NOTIFY_PATH = "/gamification/"

    def __init__(self, gloria_base_url: str | None) -> None:
        self._base_url = gloria_base_url

    async def notify_rescan_result(
        self,
        *,
        team_id: str,
        alert_id: str,
        user_id: str,
        status: str,
        points: int,
        penalty_so_far: int = 0,
    ) -> None:
        if not self._base_url:
            return

        is_valid = status in _VALID_STATUSES
        if is_valid:
            message = f"Alert {alert_id} resolved: {user_id} earned {points} points."
        elif status == "already_resolved":
            message = f"Alert {alert_id} was already resolved. No additional points awarded."
        elif penalty_so_far > 0:
            message = (
                f"Alert {alert_id} not resolved yet for {user_id}. "
                f"Accumulated penalty: -{penalty_so_far} pts (will reduce your resolution reward)."
            )
        else:
            message = f"Alert {alert_id} marked as invalid for user {user_id}. No points awarded."
        payload = {
            "alert_id": alert_id,
            "team_id": team_id,
            "user_id": user_id,
            "points_awarded": is_valid,
            "points": points,
            "message": message,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self._base_url}{self._NOTIFY_PATH}", json=payload)
            response.raise_for_status()
