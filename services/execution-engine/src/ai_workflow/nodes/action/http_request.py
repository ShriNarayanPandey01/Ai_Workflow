from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.action_keys import (
    ActionKeyConflictError,
    ActionKeyStore,
    canonical_json,
)
from ai_workflow.security.http_client import SafeHttpClient
from ai_workflow.security.redaction import redact_value

if TYPE_CHECKING:
    from ai_workflow.security.credentials import CredentialResolver

_VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# Verbs the action node is permitted to issue. Mirrors the catalog manifest's
# config_schema enum so the executor refuses disallowed methods (TRACE, CONNECT,
# etc.) even if a config reaches it without semantic validation.
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


class HttpRequestNodeExecutor:
    node_type = "action.http-request@1"

    def __init__(
        self,
        *,
        http_client: SafeHttpClient,
        action_key_store: ActionKeyStore | None = None,
        credential_resolver: CredentialResolver | None = None,
    ) -> None:
        self._http_client = http_client
        self._action_key_store = action_key_store
        self._credential_resolver = credential_resolver

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        method = config.get("method")
        url_template = config.get("url_template")
        timeout_seconds = config.get("timeout_seconds")
        max_response_bytes = config.get("max_response_bytes")
        max_redirects = config.get("max_redirects")

        if not isinstance(method, str) or not method:
            msg = "action.http-request@1 requires config.method"
            raise ValueError(msg)
        normalized_method = method.upper()
        if normalized_method not in _ALLOWED_METHODS:
            allowed = ", ".join(sorted(_ALLOWED_METHODS))
            msg = f"action.http-request@1 method {method!r} not allowed (permitted: {allowed})"
            raise ValueError(msg)
        method = normalized_method
        if not isinstance(url_template, str) or not url_template:
            msg = "action.http-request@1 requires config.url_template"
            raise ValueError(msg)
        if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
            msg = "action.http-request@1 requires config.timeout_seconds >= 1"
            raise ValueError(msg)
        if not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            msg = "action.http-request@1 requires config.max_response_bytes >= 1"
            raise ValueError(msg)
        if not isinstance(max_redirects, int) or max_redirects < 0:
            msg = "action.http-request@1 requires config.max_redirects >= 0"
            raise ValueError(msg)

        url_variables = inputs.get("url_variables")
        variables: dict[str, JsonValue] = {}
        if url_variables is not None:
            if not isinstance(url_variables, dict):
                msg = "url_variables must be an object"
                raise ValueError(msg)
            variables = url_variables

        url = _render_template(url_template, variables)
        headers = _as_string_dict(inputs.get("headers"), field="headers")
        query = _as_string_dict(inputs.get("query"), field="query")
        body = inputs.get("body")

        await _merge_credentials(
            context=context,
            credential_resolver=self._credential_resolver,
            headers=headers,
            query=query,
        )

        attempt = context.attempt or 1
        item_key = context.runtime.get("_foreach_item")
        item_suffix = ""
        if isinstance(item_key, dict) and item_key.get("item_key") is not None:
            item_suffix = f":{item_key['item_key']}"
        action_key = context.idempotency_key or f"{context.run_id}:{context.node_id}{item_suffix}"

        idempotency_header = config.get("idempotency_header")
        if isinstance(idempotency_header, str) and idempotency_header:
            headers[idempotency_header] = action_key

        # Fingerprint the request up front so a replay under the same action key
        # can be checked for input drift before any side effect is (re-)issued.
        fingerprint = _request_fingerprint(method=method, url=url, body=body)

        store = self._action_key_store
        if store is not None:
            cached = await store.get(action_key=action_key)
            if cached is not None:
                if cached.fingerprint != fingerprint:
                    msg = (
                        f"Action key {action_key} replayed with a different request "
                        f"fingerprint; refusing to reuse the cached response"
                    )
                    raise ActionKeyConflictError(msg)
                return NodeResult(outputs={"response": cached.response})

        header_allowlist = config.get("header_allowlist")
        allowlist = None
        if isinstance(header_allowlist, list):
            allowlist = [str(item) for item in header_allowlist]

        json_body = body if isinstance(body, (dict, list)) else None
        response = await self._http_client.request(
            method,
            url,
            headers=headers,
            params=query or None,
            json_body=json_body,
            timeout_seconds=float(timeout_seconds),
            max_response_bytes=max_response_bytes,
            max_redirects=max_redirects,
            header_allowlist=allowlist,
        )

        shaped = _shape_response(response.body_bytes, response.status_code, response.headers)
        redacted = redact_value(shaped)
        if not isinstance(redacted, dict):
            msg = "HTTP response shaping produced a non-object payload"
            raise ValueError(msg)

        if store is not None:
            await store.put(
                action_key=action_key,
                run_id=context.run_id,
                node_id=context.node_id,
                attempt=attempt,
                fingerprint=fingerprint,
                response=redacted,
            )

        return NodeResult(outputs={"response": redacted})


def _render_template(template: str, variables: dict[str, JsonValue]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            return ""
        value = variables[name]
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            msg = f"Template variable {name!r} must be a scalar"
            raise ValueError(msg)
        return str(value)

    return _VAR_PATTERN.sub(replace, template)


def _as_string_dict(value: JsonValue | None, *, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = f"{field} must be an object"
        raise ValueError(msg)
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if item is None:
            continue
        if isinstance(item, (dict, list)):
            msg = f"{field}.{key} must be a scalar"
            raise ValueError(msg)
        result[key] = str(item)
    return result


async def _merge_credentials(
    *,
    context: ExecutionContext,
    credential_resolver: CredentialResolver | None,
    headers: dict[str, str],
    query: dict[str, str],
) -> None:
    if not context.credential_refs:
        return
    resolver = context.credential_resolver or credential_resolver
    if resolver is None:
        msg = "Credential references present but no credential resolver configured"
        raise ValueError(msg)

    slots = list(context.credential_refs.keys())
    resolved = await resolver.resolve(
        run_id=context.run_id,
        node_id=context.node_id,
        workflow_version_id=context.workflow_version_id,
        slots=slots,
    )

    if "header_auth" in resolved:
        _apply_header_auth(headers, resolved["header_auth"])
    if "query_auth" in resolved:
        _apply_query_auth(query, resolved["query_auth"])


def _apply_header_auth(headers: dict[str, str], value: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        headers["Authorization"] = value
        return
    if isinstance(parsed, dict):
        name = parsed.get("name", "Authorization")
        header_value = parsed.get("value")
        if isinstance(name, str) and header_value is not None:
            headers[name] = str(header_value)
            return
    headers["Authorization"] = value


def _apply_query_auth(query: dict[str, str], value: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        query["api_key"] = value
        return
    if isinstance(parsed, dict):
        name = parsed.get("name")
        param_value = parsed.get("value")
        if isinstance(name, str) and param_value is not None:
            query[name] = str(param_value)
            return
    query["api_key"] = value


def _shape_response(
    body_bytes: bytes,
    status_code: int,
    headers: dict[str, str],
) -> dict[str, JsonValue]:
    text = body_bytes.decode("utf-8", errors="replace")
    body: JsonValue | None = None
    body_text: str | None = text
    if body_bytes:
        try:
            body = json.loads(text)
            body_text = None
        except json.JSONDecodeError:
            body = None
    return {
        "status_code": status_code,
        "headers": headers,
        "body": body,
        "body_text": body_text,
    }


def _request_fingerprint(*, method: str, url: str, body: JsonValue | None) -> str:
    payload = f"{method.upper()}\0{url}\0{canonical_json(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
