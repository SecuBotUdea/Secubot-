import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.database.connection import DatabaseManager
from app.models.alert import AlertRecord
from app.http import create_app
from app.schemas.common import RescanResultPayload


def _rescan_payload(**overrides) -> dict:
    base = {
        "alert_id": "alert_123",
        "source_type": "dependabot",
        "source_id": "42",
        "title": "Critical vulnerability in lodash",
        "severity": "high",
        "status": "fixed",
        "component": "package.json",
        "team_id": "guild_111",
        "team_name": "Team Alpha",
        "user_id": "user_456",
    }
    base.update(overrides)
    return base


class FakeGamificationService:
    def __init__(self) -> None:
        self.rescan_payloads: list[RescanResultPayload] = []

    async def handle_rescan_result(self, payload: RescanResultPayload) -> dict:
        self.rescan_payloads.append(payload)
        if payload.status in ("fixed", "resolved"):
            return {
                "status": "points_awarded",
                "points": 75,
                "alert_id": payload.alert_id,
                "user_id": payload.user_id,
            }
        return {"status": "no_points", "alert_id": payload.alert_id, "user_id": payload.user_id}

    async def get_player_detail(self, team_id: str, user_id: str) -> dict | None:
        if user_id == "unknown":
            return None
        return {
            "user_id": user_id,
            "team_id": team_id,
            "points": 100,
            "rank": 1,
            "point_logs": [{"alert_id": "a1", "points": 100, "timestamp": "2026-01-01T00:00:00+00:00"}],
        }

    async def get_leaderboard(self, team_id: str) -> list[dict]:
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


def test_rescan_result_fixed_awards_points(api_client) -> None:
    client, service, _ = api_client
    response = client.post("/events/rescan_result", json=_rescan_payload(status="fixed"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "points_awarded"
    assert body["points"] == 75
    assert body["user_id"] == "user_456"
    assert service.rescan_payloads[0].alert_id == "alert_123"


def test_rescan_result_resolved_awards_points(api_client) -> None:
    client, _, _ = api_client
    response = client.post("/events/rescan_result", json=_rescan_payload(status="resolved"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "points_awarded"
    assert body["user_id"] == "user_456"


def test_rescan_result_open_no_points(api_client) -> None:
    client, _, _ = api_client
    response = client.post("/events/rescan_result", json=_rescan_payload(status="open"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_points"
    assert body["user_id"] == "user_456"


def test_rescan_result_dismissed_no_points(api_client) -> None:
    client, _, _ = api_client
    response = client.post("/events/rescan_result", json=_rescan_payload(status="dismissed"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_points"
    assert body["user_id"] == "user_456"


def test_rescan_result_accepts_jugeared_payload_shape(api_client) -> None:
    client, service, _ = api_client
    alert = AlertRecord(
        alert_id="alert_999",
        team_id="guild_111",
        severity="high",
        source_type="dependabot",
        title="Critical vulnerability in lodash",
        status="resolved",
    )
    payload = {
        **alert.model_dump(mode="json"),
        "team_name": "Team Alpha",
        "user_id": "user_456",
    }

    response = client.post("/events/rescan_result", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "points_awarded"
    assert body["user_id"] == "user_456"
    assert service.rescan_payloads[0].alert_id == "alert_999"


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
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    players = InMemoryPlayerRepository()
    logs = InMemoryPointLogRepository()
    service = GamificationService(players, logs)

    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a1",
            source_type="dependabot",
            source_id="42",
            title="Critical vuln",
            severity="critical",
            status="fixed",
            component="package.json",
            team_id="g1",
            team_name="Team Alpha",
            user_id="u1",
        )
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
async def test_gamification_no_points_on_open_status() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    players = InMemoryPlayerRepository()
    logs = InMemoryPointLogRepository()
    service = GamificationService(players, logs)

    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a2",
            source_type="dependabot",
            source_id="42",
            title="High vuln",
            severity="high",
            status="open",
            component="package.json",
            team_id="g1",
            team_name="Team Alpha",
            user_id="u1",
        )
    )

    assert result["status"] == "no_points"
    player = await players.get_player("u1", "g1")
    assert player is None


@pytest.mark.asyncio
async def test_remediation_logged_on_valid_rescan() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
        InMemoryRemediationRepository,
    )

    remediations = InMemoryRemediationRepository()
    service = GamificationService(
        InMemoryPlayerRepository(),
        InMemoryPointLogRepository(),
        remediation_repository=remediations,
    )

    await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a4",
            source_type="dependabot",
            source_id="42",
            title="High vuln",
            severity="high",
            status="fixed",
            component="package.json",
            team_id="g1",
            team_name="Team Alpha",
            user_id="u1",
        )
    )

    logs = await remediations.get_remediations_for_user("u1", "g1")
    assert len(logs) == 1
    assert logs[0]["status"] == "fixed"
    assert logs[0]["points_awarded"] == 75
    assert logs[0]["alert_id"] == "a4"


@pytest.mark.asyncio
async def test_remediation_logged_on_invalid_rescan() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
        InMemoryRemediationRepository,
    )

    remediations = InMemoryRemediationRepository()
    service = GamificationService(
        InMemoryPlayerRepository(),
        InMemoryPointLogRepository(),
        remediation_repository=remediations,
    )

    await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a5",
            source_type="dependabot",
            source_id="42",
            title="Medium vuln",
            severity="medium",
            status="open",
            component="package.json",
            team_id="g1",
            team_name="Team Alpha",
            user_id="u1",
        )
    )

    logs = await remediations.get_remediations_for_user("u1", "g1")
    assert len(logs) == 1
    assert logs[0]["status"] == "open"
    assert logs[0]["points_awarded"] == 0


@pytest.mark.asyncio
async def test_remediation_logs_multiple_attempts() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
        InMemoryRemediationRepository,
    )

    remediations = InMemoryRemediationRepository()
    service = GamificationService(
        InMemoryPlayerRepository(),
        InMemoryPointLogRepository(),
        remediation_repository=remediations,
    )

    base = dict(
        alert_id="a6",
        source_type="dependabot",
        source_id="42",
        title="Low vuln",
        severity="low",
        component="package.json",
        team_id="g1",
        team_name="Team Alpha",
        user_id="u1",
    )
    await service.handle_rescan_result(RescanResultPayload(**base, status="open"))
    await service.handle_rescan_result(RescanResultPayload(**base, status="open"))
    await service.handle_rescan_result(RescanResultPayload(**base, status="fixed"))

    logs = await remediations.get_remediations_for_user("u1", "g1")
    assert len(logs) == 3
    assert logs[0]["status"] == "open"
    assert logs[1]["status"] == "open"
    assert logs[2]["status"] == "fixed"
    assert logs[2]["points_awarded"] == 25
