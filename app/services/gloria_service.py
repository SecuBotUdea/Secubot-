from __future__ import annotations

import httpx

_VALID_STATUSES = {"fixed", "resolved"}


class GloriaService:
    _NOTIFY_PATH = "/events/notify"

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
        event_type = "rescan_valid" if is_valid else "rescan_invalid"
        message_content = (
            f"Alert {alert_id} resolved: {user_id} earned {points} points."
            if is_valid
            else f"Alert {alert_id} marked as invalid. No points awarded."
        )
        payload = {
            "team_id": team_id,
            "message_content": message_content,
            "embed_data": {
                "alert_id": alert_id,
                "user_id": user_id,
                "points": points,
                "status": status,
            },
            "source": "secubot",
            "event_type": event_type,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self._base_url}{self._NOTIFY_PATH}", json=payload)
            response.raise_for_status()
