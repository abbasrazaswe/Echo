from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.artifact_api import router as artifact_router
from app.database import Database
from app.retrieval import EmbeddingProvider, RetrievalService


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data/profiles/echo.db"


def create_app(database_path: Path = DEFAULT_DATABASE, *, embedder: EmbeddingProvider | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(database_path)
        database.initialize()
        application.state.database = database
        application.state.retrieval = RetrievalService(database, embedder)
        try:
            yield
        finally:
            database.engine.dispose()

    application = FastAPI(title="Echo API", version="0.4.0", lifespan=lifespan)
    application.include_router(router)
    application.include_router(artifact_router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Confirm that the API is running and can handle requests."""
        return {"status": "ok"}

    return application


app = create_app()
