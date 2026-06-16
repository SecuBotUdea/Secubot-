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
    # 2 intentos inválidos previos → penalización 40 pts sobre base 25 → mínimo 1
    assert logs[2]["points_awarded"] == 1


@pytest.mark.asyncio
async def test_speed_bonus_under_6h() -> None:
    from datetime import timedelta
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    players = InMemoryPlayerRepository()
    service = GamificationService(players, InMemoryPointLogRepository())

    from datetime import datetime, timezone
    opened_at = datetime.now(timezone.utc) - timedelta(hours=2)

    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a7",
            severity="high",
            status="fixed",
            team_id="g1",
            user_id="u1",
            opened_at=opened_at,
        )
    )

    # high (75) × 1.5 (< 6h) = 112
    assert result["status"] == "points_awarded"
    assert result["points"] == 112
    assert result["breakdown"]["speed_multiplier"] == 1.5


@pytest.mark.asyncio
async def test_speed_no_bonus_after_72h() -> None:
    from datetime import timedelta, datetime, timezone
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    service = GamificationService(InMemoryPlayerRepository(), InMemoryPointLogRepository())

    opened_at = datetime.now(timezone.utc) - timedelta(hours=80)
    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a8",
            severity="high",
            status="fixed",
            team_id="g1",
            user_id="u1",
            opened_at=opened_at,
        )
    )

    assert result["points"] == 75
    assert result["breakdown"]["speed_multiplier"] == 1.0


@pytest.mark.asyncio
async def test_score_multiplier_high() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    service = GamificationService(InMemoryPlayerRepository(), InMemoryPointLogRepository())

    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a9",
            severity="high",
            status="fixed",
            team_id="g1",
            user_id="u1",
            external_references_score=0.85,
        )
    )

    # high (75) × 1.5 (score >= 0.7) = 112
    assert result["points"] == 112
    assert result["breakdown"]["score_multiplier"] == 1.5


@pytest.mark.asyncio
async def test_score_multiplier_medium() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    service = GamificationService(InMemoryPlayerRepository(), InMemoryPointLogRepository())

    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a10",
            severity="medium",
            status="fixed",
            team_id="g1",
            user_id="u1",
            external_references_score=0.55,
        )
    )

    # medium (50) × 1.2 (score 0.4-0.7) = 60
    assert result["points"] == 60
    assert result["breakdown"]["score_multiplier"] == 1.2


@pytest.mark.asyncio
async def test_penalty_reduces_points_on_valid_after_invalid() -> None:
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

    base = dict(alert_id="a11", severity="critical", team_id="g1", user_id="u1")
    await service.handle_rescan_result(RescanResultPayload(**base, status="open"))
    result = await service.handle_rescan_result(RescanResultPayload(**base, status="fixed"))

    # critical (100) - penalización 1 intento (20) = 80
    assert result["points"] == 80
    assert result["breakdown"]["penalty"] == 20


@pytest.mark.asyncio
async def test_penalty_capped_at_max() -> None:
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

    base = dict(alert_id="a12", severity="critical", team_id="g1", user_id="u1")
    for _ in range(5):
        await service.handle_rescan_result(RescanResultPayload(**base, status="open"))
    result = await service.handle_rescan_result(RescanResultPayload(**base, status="fixed"))

    # penalización capped en 60 pts → 100 - 60 = 40
    assert result["breakdown"]["penalty"] == 60
    assert result["points"] == 40


@pytest.mark.asyncio
async def test_penalty_minimum_one_point() -> None:
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

    base = dict(alert_id="a13", severity="low", team_id="g1", user_id="u1")
    for _ in range(5):
        await service.handle_rescan_result(RescanResultPayload(**base, status="open"))
    result = await service.handle_rescan_result(RescanResultPayload(**base, status="fixed"))

    # low (25) - cap 60 = -35, pero mínimo 1
    assert result["points"] == 1


@pytest.mark.asyncio
async def test_combined_speed_and_score_multipliers() -> None:
    from datetime import timedelta, datetime, timezone
    from app.services.gamification_service import GamificationService
    from app.database.connection import InMemoryPlayerRepository, InMemoryPointLogRepository

    service = GamificationService(InMemoryPlayerRepository(), InMemoryPointLogRepository())

    opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
    result = await service.handle_rescan_result(
        RescanResultPayload(
            alert_id="a14",
            severity="critical",
            status="fixed",
            team_id="g1",
            user_id="u1",
            opened_at=opened_at,
            external_references_score=0.9,
        )
    )

    # critical (100) × 1.5 (< 6h) × 1.5 (score >= 0.7) = 225
    assert result["points"] == 225
    assert result["breakdown"]["speed_multiplier"] == 1.5
    assert result["breakdown"]["score_multiplier"] == 1.5


@pytest.mark.asyncio
async def test_duplicate_rescan_no_extra_points() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
        InMemoryRemediationRepository,
    )

    players = InMemoryPlayerRepository()
    remediations = InMemoryRemediationRepository()
    service = GamificationService(players, InMemoryPointLogRepository(), remediation_repository=remediations)

    payload = RescanResultPayload(
        alert_id="dup_alert",
        severity="high",
        status="fixed",
        team_id="g1",
        user_id="u1",
    )

    first = await service.handle_rescan_result(payload)
    assert first["status"] == "points_awarded"
    assert first["points"] == 75

    second = await service.handle_rescan_result(payload)
    assert second["status"] == "already_resolved"

    player = await players.get_player("u1", "g1")
    assert player["points"] == 75


@pytest.mark.asyncio
async def test_duplicate_rescan_different_user_no_extra_points() -> None:
    from app.services.gamification_service import GamificationService
    from app.database.connection import (
        InMemoryPlayerRepository,
        InMemoryPointLogRepository,
        InMemoryRemediationRepository,
    )

    players = InMemoryPlayerRepository()
    remediations = InMemoryRemediationRepository()
    service = GamificationService(players, InMemoryPointLogRepository(), remediation_repository=remediations)

    await service.handle_rescan_result(
        RescanResultPayload(alert_id="shared_alert", severity="high", status="fixed", team_id="g1", user_id="u1")
    )

    result = await service.handle_rescan_result(
        RescanResultPayload(alert_id="shared_alert", severity="high", status="fixed", team_id="g1", user_id="u2")
    )
    assert result["status"] == "already_resolved"

    p2 = await players.get_player("u2", "g1")
    assert p2 is None
