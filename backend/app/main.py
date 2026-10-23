from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.artifact_api import router as artifact_router
from app.chat import ChatService, router as chat_router
from app.database import Database
from app.llm import LLMProvider, LLMSettings, OpenAIProvider
from app.retrieval import EmbeddingProvider, RetrievalService
from app.sessions import router as session_router
from app.style import router as style_router


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data/profiles/echo.db"


def create_app(
    database_path: Path = DEFAULT_DATABASE, *, embedder: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(database_path)
        database.initialize()
        application.state.database = database
        application.state.retrieval = RetrievalService(database, embedder)
        provider = llm_provider or OpenAIProvider(LLMSettings.load(Path(__file__).resolve().parents[1] / ".env"))
        application.state.chat = ChatService(application.state.retrieval, provider)
        try:
            yield
        finally:
            database.engine.dispose()

    application = FastAPI(title="Echo API", version="0.8.0", lifespan=lifespan)
    application.include_router(router)
    application.include_router(artifact_router)
    application.include_router(chat_router)
    application.include_router(session_router)
    application.include_router(style_router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Confirm that the API is running and can handle requests."""
        return {"status": "ok"}

    return application


app = create_app()
