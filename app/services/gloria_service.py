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
    ) -> None:
        if not self._base_url:
            return

        is_valid = status in _VALID_STATUSES
        message = (
            f"Alert {alert_id} resolved: {user_id} earned {points} points."
            if is_valid
            else f"Alert {alert_id} marked as invalid. No points awarded."
        )
        payload = {
            "alert_id": alert_id,
            "team_id": team_id,
            "points_awarded": is_valid,
            "points": points,
            "message": message,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self._base_url}{self._NOTIFY_PATH}", json=payload)
            response.raise_for_status()
