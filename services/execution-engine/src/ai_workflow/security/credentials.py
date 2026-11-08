from __future__ import annotations

from typing import Protocol
from uuid import UUID

import httpx

from ai_workflow.security.http_client import create_async_client
from ai_workflow.security.service_auth import ServiceAuthProvider

# Production workers should set AIW_CONTROL_PLANE_INTERNAL_URL so
# build_credential_resolver returns HttpCredentialResolver
# (POST /internal/v1/executions/{runId}/credentials:resolve). Secrets exist
# only for the duration of resolve() plus the provider call.
# EnvCredentialResolver is a local-dev fallback when no control-plane URL is
# configured: it can supply only the provider slot from a ZenMux-compatible key.


class CredentialResolver(Protocol):
    """Resolves credential slot names to secret values for a node execution."""

    async def resolve(
        self,
        *,
        run_id: UUID,
        node_id: UUID,
        workflow_version_id: UUID | None,
        slots: list[str],
    ) -> dict[str, str]: ...


class StaticCredentialResolver:
    """Test helper that returns fixed slot values."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    async def resolve(
        self,
        *,
        run_id: UUID,
        node_id: UUID,
        workflow_version_id: UUID | None,
        slots: list[str],
    ) -> dict[str, str]:
        del run_id, node_id, workflow_version_id
        missing = [slot for slot in slots if slot not in self._values]
        if missing:
            msg = f"Missing credential slots: {', '.join(missing)}"
            raise ValueError(msg)
        return {slot: self._values[slot] for slot in slots}


class EnvCredentialResolver:
    """Dev fallback: ZenMux-compatible API key for the provider slot only."""

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    async def resolve(
        self,
        *,
        run_id: UUID,
        node_id: UUID,
        workflow_version_id: UUID | None,
        slots: list[str],
    ) -> dict[str, str]:
        del run_id, node_id, workflow_version_id
        result: dict[str, str] = {}
        for slot in slots:
            if slot == "provider":
                if not self._api_key:
                    msg = "Credential slot 'provider' is not configured"
                    raise ValueError(msg)
                result[slot] = self._api_key
            else:
                msg = f"Credential slot '{slot}' is not available via env fallback"
                raise ValueError(msg)
        return result


class HttpCredentialResolver:
    """Fetches credential values from the control plane internal API."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        service_auth: ServiceAuthProvider | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._service_auth = service_auth

    async def resolve(
        self,
        *,
        run_id: UUID,
        node_id: UUID,
        workflow_version_id: UUID | None,
        slots: list[str],
    ) -> dict[str, str]:
        if not slots:
            return {}
        url = f"{self._base_url}/internal/v1/executions/{run_id}/credentials:resolve"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._service_auth is not None:
            headers["Authorization"] = self._service_auth.authorization_header()
        body = {
            "nodeId": str(node_id),
            "slots": slots,
            "workflowVersionId": str(workflow_version_id) if workflow_version_id else None,
        }
        response = await self._client.post(url, json=body, headers=headers)
        if response.status_code >= 400:
            msg = f"Credential resolve failed with status {response.status_code}"
            raise ValueError(msg)
        data = response.json()
        if not isinstance(data, dict):
            msg = "Credential resolve returned non-object response"
            raise ValueError(msg)
        credentials = data.get("credentials")
        if not isinstance(credentials, dict):
            msg = "Credential resolve response missing credentials object"
            raise ValueError(msg)
        result: dict[str, str] = {}
        for slot in slots:
            value = credentials.get(slot)
            if not isinstance(value, str) or not value:
                msg = f"Credential slot '{slot}' was not resolved"
                raise ValueError(msg)
            result[slot] = value
        return result


def build_credential_resolver(
    *,
    control_plane_url: str | None,
    internal_auth_token: str | None,
    chat_api_key: str | None,
    client: httpx.AsyncClient | None = None,
) -> CredentialResolver:
    """Choose HTTP (control-plane) or env fallback credential resolution.

    HTTP is used whenever ``control_plane_url`` is set. The env fallback only
    covers slot ``provider`` from ZenMux-compatible key settings for local LLM
    without a control plane.
    """
    if control_plane_url:
        from ai_workflow.security.service_auth import StaticServiceAuth

        auth = StaticServiceAuth(internal_auth_token) if internal_auth_token else None
        http_client = client or create_async_client()
        return HttpCredentialResolver(
            base_url=control_plane_url,
            client=http_client,
            service_auth=auth,
        )
    return EnvCredentialResolver(chat_api_key)
