from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv
import uvicorn

from app.config.settings import Settings
from app.database.connection import DatabaseManager
from app.http import create_app
from app.services.gamification_service import GamificationService


async def main() -> None:
    load_dotenv()
    settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    database_manager = DatabaseManager(settings.database_url)
    await database_manager.connect()

    gamification_service = GamificationService(
        alert_repository=database_manager.alert_repository,
        player_repository=database_manager.player_repository,
        point_log_repository=database_manager.point_log_repository,
    )

    app = create_app(settings, database_manager, gamification_service)
    config = uvicorn.Config(app, host="0.0.0.0", port=settings.http_port, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
