from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Protocol
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({80, 443, None})


class SsrfError(ValueError):
    """Raised when a URL or resolved address is not permitted."""


class Resolver(Protocol):
    async def __call__(self, hostname: str) -> list[str]: ...


def is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True when an IP must be blocked for outbound requests."""
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
        if ip == ipaddress.ip_address("169.254.169.254"):
            return True
    return False


async def _default_resolve(hostname: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        msg = f"DNS resolution failed for {hostname!r}"
        raise SsrfError(msg) from exc
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            addresses.append(str(sockaddr[0]))
    if not addresses:
        msg = f"No addresses resolved for {hostname!r}"
        raise SsrfError(msg)
    return addresses


def _validate_parsed_url(parsed) -> str:
    if not parsed.scheme or parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        msg = f"URL scheme not allowed: {parsed.scheme!r}"
        raise SsrfError(msg)

    if not parsed.hostname:
        msg = "URL missing hostname"
        raise SsrfError(msg)

    if parsed.username or parsed.password:
        msg = "URL userinfo is not permitted"
        raise SsrfError(msg)

    if parsed.fragment:
        msg = "URL fragments are not supported"
        raise SsrfError(msg)

    port = parsed.port
    if port is not None and port not in _ALLOWED_PORTS:
        msg = f"URL port not allowed: {port}"
        raise SsrfError(msg)

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname

    if is_disallowed_ip(ip):
        msg = f"Disallowed IP address: {ip}"
        raise SsrfError(msg)
    return hostname


async def validate_url(url: str, *, resolver: Resolver | None = None) -> None:
    """Parse, resolve DNS, and reject disallowed outbound targets."""
    parsed = urlparse(url)
    hostname = _validate_parsed_url(parsed)

    resolve = resolver or _default_resolve
    for address in await resolve(hostname):
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            msg = f"Invalid resolved address for {hostname!r}: {address!r}"
            raise SsrfError(msg) from exc
        if is_disallowed_ip(ip):
            msg = f"Disallowed resolved address for {hostname!r}: {ip}"
            raise SsrfError(msg)


def fake_resolver(mapping: dict[str, list[str]]) -> Resolver:
    """Build a deterministic resolver for tests."""

    async def _resolve(hostname: str) -> list[str]:
        key = hostname.lower().rstrip(".")
        if key not in mapping:
            return await _default_resolve(hostname)
        return list(mapping[key])

    return _resolve
