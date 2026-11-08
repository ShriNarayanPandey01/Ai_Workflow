from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ai_workflow_rag.config.settings import Settings


class ServiceAuthProvider(Protocol):
    def authorization_header(self) -> str: ...


class StaticServiceAuth:
    def __init__(self, token: str) -> None:
        self._token = token

    def authorization_header(self) -> str:
        return f"Bearer {self._token}"


def build_service_auth(settings: Settings) -> ServiceAuthProvider | None:
    token = settings.internal_auth_token
    if not token:
        return None
    return StaticServiceAuth(token)
