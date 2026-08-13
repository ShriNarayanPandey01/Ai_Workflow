from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request

from ai_workflow_rag.config.settings import Settings

ReadinessChecker = Callable[[Settings], Awaitable[tuple[bool, dict[str, str]]]]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_readiness_checker(request: Request) -> ReadinessChecker:
    return request.app.state.readiness_checker
