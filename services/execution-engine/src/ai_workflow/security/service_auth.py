from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ai_workflow.config.settings import Settings


class ServiceAuthProvider(Protocol):
    """Provides Authorization headers for internal service-to-service calls."""

    def authorization_header(self) -> str: ...
  

class StaticServiceAuth:
    """Bearer-token auth backed by a fixed internal service token."""

    def __init__(self, token: str) -> None:
        self._token = token

    def authorization_header(self) -> str:
        return f"Bearer {self._token}"


def build_service_auth(settings: Settings) -> ServiceAuthProvider | None:
    """Build internal service auth when an auth token is configured."""
    token = settings.internal_auth_token
    if not token:
        return None
    return StaticServiceAuth(token)
