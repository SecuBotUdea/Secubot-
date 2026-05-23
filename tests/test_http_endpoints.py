import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.database.connection import DatabaseManager
from app.http import create_app
from app.schemas.common import AlertPayload, RescanResultPayload


class FakeGamificationService:
    def __init__(self) -> None:
        self.alert_payloads: list[AlertPayload] = []
        self.rescan_payloads: list[RescanResultPayload] = []
        self.raise_not_found: bool = False
        self.raise_already_resolved: bool = False

    async def handle_alert(self, payload: AlertPayload) -> dict:
        self.alert_payloads.append(payload)
        return {"status": "received", "alert_id": payload.alert_id}

    async def handle_rescan_result(self, payload: RescanResultPayload) -> dict:
        from app.database.connection import AlertAlreadyResolvedError, AlertNotFoundError
        if self.raise_not_found:
            raise AlertNotFoundError(payload.alert_id)
        if self.raise_already_resolved:
            raise AlertAlreadyResolvedError(payload.alert_id)
        self.rescan_payloads.append(payload)
        if payload.status == "valid":
            return {"status": "points_awarded", "points": 75, "alert_id": payload.alert_id}
        return {"status": "no_points", "alert_id": payload.alert_id}

    async def get_player_detail(self, guild_id: str, user_id: str) -> dict | None:
        if user_id == "unknown":
            return None
        return {
            "user_id": user_id,
            "guild_id": guild_id,
            "points": 100,
            "rank": 1,
            "point_logs": [{"alert_id": "a1", "points": 100, "timestamp": "2026-01-01T00:00:00+00:00"}],
        }

    async def get_leaderboard(self, guild_id: str) -> list[dict]:
        return [{"user_id": "user_1", "points": 100, "rank": 1}]


@pytest.fixture
def api_client() -> tuple[TestClient, FakeGamificationService, DatabaseManager]:
    settings = Settings.model_validate(
        {"DATABASE_URL": "memory://test", "HTTP_PORT": 8000}
    )
    db = DatabaseManager(settings.database_url)
    db.database_connected = True
    service = FakeGamificationService()
    app = create_app(settings, db, service)
    return TestClient(app), service, db


def test_health_endpoint(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["database_connected"] is True


def test_receive_alert_endpoint(api_client) -> None:
    client, service, _ = api_client
    response = client.post(
        "/events/alert",
        json={
            "alert_id": "alert_123",
            "guild_id": "111",
            "severity": "high",
            "source": "wazuh",
            "description": "Suspicious login",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "received", "alert_id": "alert_123"}
    assert service.alert_payloads[0].alert_id == "alert_123"


def test_rescan_result_valid(api_client) -> None:
    client, service, _ = api_client
    response = client.post(
        "/events/rescan_result",
        json={
            "alert_id": "alert_123",
            "user_id": "user_456",
            "status": "valid",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "points_awarded"
    assert body["points"] == 75


def test_rescan_result_invalid(api_client) -> None:
    client, service, _ = api_client
    response = client.post(
        "/events/rescan_result",
        json={
            "alert_id": "alert_123",
            "user_id": "user_456",
            "status": "invalid",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "no_points"


def test_rescan_result_unknown_alert_returns_404(api_client) -> None:
    client, service, _ = api_client
    service.raise_not_found = True
    response = client.post(
        "/events/rescan_result",
        json={"alert_id": "unknown", "user_id": "u1", "status": "valid"},
    )
    assert response.status_code == 404


def test_rescan_result_already_resolved_returns_409(api_client) -> None:
    client, service, _ = api_client
    service.raise_already_resolved = True
    response = client.post(
        "/events/rescan_result",
        json={"alert_id": "alert_123", "user_id": "u1", "status": "valid"},
    )
    assert response.status_code == 409


def test_player_detail_endpoint(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/teams/111/players/user_1")

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user_1"
    assert body["points"] == 100
    assert body["rank"] == 1
    assert len(body["point_logs"]) == 1
    assert body["point_logs"][0]["alert_id"] == "a1"


def test_player_detail_not_found(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/teams/111/players/unknown")
    assert response.status_code == 404


def test_leaderboard_endpoint(api_client) -> None:
    client, _, _ = api_client
    response = client.get("/teams/111/leaderboard")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["user_id"] == "user_1"
    assert body[0]["rank"] == 1


@pytest.mark.asyncio
async def test_database_connection_fallback(monkeypatch) -> None:
    manager = DatabaseManager("mongodb://localhost:27017/test")

    async def failing_connect() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(manager, "_connect_mongo", failing_connect)
    await manager.connect()

    assert manager.database_connected is True
    assert manager.using_fallback is True


@pytest.mark.asyncio
async def test_gamification_awards_points_by_severity() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryAlertRepository, InMemoryPlayerRepository, InMemoryPointLogRepository

    alerts = InMemoryAlertRepository()
    players = InMemoryPlayerRepository()
    logs = InMemoryPointLogRepository()
    service = GamificationService(alerts, players, logs)

    await service.handle_alert(
        AlertPayload(alert_id="a1", guild_id="g1", severity="critical")
    )
    result = await service.handle_rescan_result(
        RescanResultPayload(alert_id="a1", user_id="u1", status="valid")
    )

    assert result["status"] == "points_awarded"
    assert result["points"] == 100

    player = await players.get_player("u1", "g1")
    assert player["points"] == 100

    user_logs = await logs.get_logs_for_user("u1", "g1")
    assert len(user_logs) == 1
    assert user_logs[0]["points"] == 100
    assert user_logs[0]["alert_id"] == "a1"


@pytest.mark.asyncio
async def test_gamification_no_points_on_invalid() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryAlertRepository, InMemoryPlayerRepository, InMemoryPointLogRepository

    alerts = InMemoryAlertRepository()
    players = InMemoryPlayerRepository()
    logs = InMemoryPointLogRepository()
    service = GamificationService(alerts, players, logs)

    await service.handle_alert(
        AlertPayload(alert_id="a2", guild_id="g1", severity="high")
    )
    result = await service.handle_rescan_result(
        RescanResultPayload(alert_id="a2", user_id="u1", status="invalid")
    )

    assert result["status"] == "no_points"
    player = await players.get_player("u1", "g1")
    assert player is None


@pytest.mark.asyncio
async def test_gamification_unknown_alert_raises() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        AlertNotFoundError,
        InMemoryAlertRepository,
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
    )

    service = GamificationService(
        InMemoryAlertRepository(), InMemoryPlayerRepository(), InMemoryPointLogRepository()
    )
    with pytest.raises(AlertNotFoundError):
        await service.handle_rescan_result(
            RescanResultPayload(alert_id="ghost", user_id="u1", status="valid")
        )


@pytest.mark.asyncio
async def test_gamification_already_resolved_alert_raises() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        AlertAlreadyResolvedError,
        InMemoryAlertRepository,
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
    )

    alerts = InMemoryAlertRepository()
    service = GamificationService(
        alerts, InMemoryPlayerRepository(), InMemoryPointLogRepository()
    )

    await service.handle_alert(AlertPayload(alert_id="a3", guild_id="g1", severity="low"))
    await service.handle_rescan_result(RescanResultPayload(alert_id="a3", user_id="u1", status="valid"))

    with pytest.raises(AlertAlreadyResolvedError):
        await service.handle_rescan_result(
            RescanResultPayload(alert_id="a3", user_id="u2", status="valid")
        )
