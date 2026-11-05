from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_workflow.api.deps import ReadinessChecker
from ai_workflow.api.routes import health
from ai_workflow.config.settings import Settings, load_settings, require_service_role
from ai_workflow.health.checks import check_readiness
from ai_workflow.runtime.registry import build_runtime_registry



def create_app(
    settings: Settings | None = None,
    *,
    readiness_checker: ReadinessChecker | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    require_service_role(resolved_settings, "execution-api")
    checker = readiness_checker or check_readiness

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.readiness_checker = checker
        app.state.registry = build_runtime_registry(
            contracts_root=resolved_settings.contracts_root,
            strict_catalog=False,
        )
        yield

    app = FastAPI(title="AI Workflow Execution Engine", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.readiness_checker = checker
    app.include_router(health.router)
    return app
