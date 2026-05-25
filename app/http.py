from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.common import HealthResponse, LeaderboardEntry, PlayerDetail, RescanResultPayload


def create_app(settings, database_manager, gamification_service) -> FastAPI:
    app = FastAPI(title="Secubot Microservice", version="1.0.0")

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["POST", "GET"],
            allow_headers=["Content-Type", "Authorization"],
        )

    @app.post("/events/rescan_result")
    async def receive_rescan_result(payload: RescanResultPayload) -> dict:
        try:
            return await gamification_service.handle_rescan_result(payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to process rescan result: {exc}") from exc

    @app.get("/teams/{team_id}/players/{user_id}", response_model=PlayerDetail)
    async def player_detail(team_id: str, user_id: str) -> PlayerDetail:
        try:
            detail = await gamification_service.get_player_detail(team_id, user_id)
            if detail is None:
                raise HTTPException(status_code=404, detail=f"Player '{user_id}' not found in guild '{team_id}'")
            return PlayerDetail(**detail)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to get player detail: {exc}") from exc

    @app.get("/teams/{team_id}/leaderboard", response_model=list[LeaderboardEntry])
    async def leaderboard(team_id: str) -> list[LeaderboardEntry]:
        try:
            entries = await gamification_service.get_leaderboard(team_id)
            return [LeaderboardEntry(**e) for e in entries]
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to get leaderboard: {exc}") from exc

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        db_connected = bool(database_manager.database_connected)
        status = "healthy" if db_connected else "degraded"
        return HealthResponse(
            status=status,
            database_connected=db_connected,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    return app
