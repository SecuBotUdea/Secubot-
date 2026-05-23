import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.database.connection import InMemoryAlertRepository, InMemoryPlayerRepository, InMemoryPointLogRepository
from app.schemas.common import AlertPayload, RescanResultPayload
from app.services.gamification_service import GamificationService
from app.services.gloria_service import GloriaService


class FakeGloriaService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.should_raise: bool = False

    async def notify_rescan_result(self, **kwargs) -> None:
        if self.should_raise:
            raise RuntimeError("Gloria unreachable")
        self.calls.append(kwargs)


def _make_service(gloria=None):
    return GamificationService(
        InMemoryAlertRepository(),
        InMemoryPlayerRepository(),
        InMemoryPointLogRepository(),
        gloria_service=gloria,
    )


@pytest.mark.asyncio
async def test_gloria_called_on_valid_rescan() -> None:
    gloria = FakeGloriaService()
    service = _make_service(gloria)

    await service.handle_alert(AlertPayload(alert_id="a1", guild_id="g1", channel_id="c1", severity="high"))
    await service.handle_rescan_result(RescanResultPayload(alert_id="a1", user_id="u1", status="valid"))

    assert len(gloria.calls) == 1
    call = gloria.calls[0]
    assert call["guild_id"] == "g1"
    assert call["channel_id"] == "c1"
    assert call["alert_id"] == "a1"
    assert call["user_id"] == "u1"
    assert call["status"] == "valid"
    assert call["points"] == 75


@pytest.mark.asyncio
async def test_gloria_called_on_invalid_rescan() -> None:
    gloria = FakeGloriaService()
    service = _make_service(gloria)

    await service.handle_alert(AlertPayload(alert_id="a2", guild_id="g1", channel_id="c1", severity="low"))
    await service.handle_rescan_result(RescanResultPayload(alert_id="a2", user_id="u1", status="invalid"))

    assert len(gloria.calls) == 1
    assert gloria.calls[0]["status"] == "invalid"
    assert gloria.calls[0]["points"] == 0


@pytest.mark.asyncio
async def test_gloria_failure_does_not_break_points_award() -> None:
    gloria = FakeGloriaService()
    gloria.should_raise = True
    service = _make_service(gloria)

    await service.handle_alert(AlertPayload(alert_id="a3", guild_id="g1", channel_id="c1", severity="critical"))
    result = await service.handle_rescan_result(RescanResultPayload(alert_id="a3", user_id="u1", status="valid"))

    assert result["status"] == "points_awarded"
    assert result["points"] == 100

    player = await service.player_repository.get_player("u1", "g1")
    assert player["points"] == 100


@pytest.mark.asyncio
async def test_no_gloria_call_without_service() -> None:
    service = _make_service(gloria=None)

    await service.handle_alert(AlertPayload(alert_id="a4", guild_id="g1", severity="medium"))
    result = await service.handle_rescan_result(RescanResultPayload(alert_id="a4", user_id="u1", status="valid"))

    assert result["status"] == "points_awarded"


@pytest.mark.asyncio
async def test_gloria_service_no_op_without_url() -> None:
    gloria = GloriaService(gloria_base_url=None)
    await gloria.notify_rescan_result(
        guild_id="g1", channel_id="c1", alert_id="a1", user_id="u1", status="valid", points=75
    )


@pytest.mark.asyncio
async def test_gloria_service_sends_correct_payload() -> None:
    gloria = GloriaService(gloria_base_url="http://gloria:8001")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.gloria_service.httpx.AsyncClient", return_value=mock_client):
        await gloria.notify_rescan_result(
            guild_id="g1", channel_id="c1", alert_id="a1", user_id="u1", status="valid", points=75
        )

    mock_client.post.assert_called_once()
    url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
    assert url == "http://gloria:8001/events/notify"
    payload = kwargs["json"]
    assert payload["source"] == "secubot"
    assert payload["event_type"] == "rescan_valid"
    assert payload["guild_id"] == "g1"
    assert payload["channel_id"] == "c1"


@pytest.mark.asyncio
async def test_gloria_service_event_type_invalid() -> None:
    gloria = GloriaService(gloria_base_url="http://gloria:8001")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.gloria_service.httpx.AsyncClient", return_value=mock_client):
        await gloria.notify_rescan_result(
            guild_id="g1", channel_id="c1", alert_id="a1", user_id="u1", status="invalid", points=0
        )

    payload = mock_client.post.call_args[1]["json"]
    assert payload["event_type"] == "rescan_invalid"
