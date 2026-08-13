from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_workflow_rag.api.deps import ReadinessChecker
from ai_workflow_rag.api.routes import health
from ai_workflow_rag.config.settings import Settings, load_settings
from ai_workflow_rag.health.checks import check_readiness


def create_app(
    settings: Settings | None = None,
    *,
    readiness_checker: ReadinessChecker | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    checker = readiness_checker or check_readiness

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.readiness_checker = checker
        yield

    app = FastAPI(title="AI Workflow RAG Service", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.readiness_checker = checker
    app.include_router(health.router)
    return app
