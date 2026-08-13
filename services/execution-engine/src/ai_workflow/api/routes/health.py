from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from ai_workflow.api.deps import ReadinessChecker, get_readiness_checker, get_settings
from ai_workflow.config.settings import Settings

router = APIRouter(prefix="/actuator/health", tags=["health"])


@router.get("/liveness")
async def liveness() -> dict[str, str]:
    return {"status": "UP"}


@router.get("/readiness")
async def readiness(
    settings: Settings = Depends(get_settings),
    readiness_checker: ReadinessChecker = Depends(get_readiness_checker),
) -> Response:
    ready, components = await readiness_checker(settings)
    body: dict[str, Any] = {"status": "UP" if ready else "DOWN", "components": components}
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=body, status_code=code)
