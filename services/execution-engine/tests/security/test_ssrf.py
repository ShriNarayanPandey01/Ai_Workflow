from __future__ import annotations

import pytest

from ai_workflow.security.ssrf import SsrfError, fake_resolver, validate_url


@pytest.mark.asyncio
async def test_ssrf_blocks_localhost() -> None:
    with pytest.raises(SsrfError):
        await validate_url("http://127.0.0.1/path")


@pytest.mark.asyncio
async def test_ssrf_blocks_private_ip_literal() -> None:
    with pytest.raises(SsrfError):
        await validate_url("http://10.0.0.1/")


@pytest.mark.asyncio
async def test_ssrf_blocks_metadata_ip() -> None:
    with pytest.raises(SsrfError):
        await validate_url("http://169.254.169.254/latest/meta-data")


@pytest.mark.asyncio
async def test_ssrf_blocks_ipv6_loopback() -> None:
    with pytest.raises(SsrfError):
        await validate_url("http://[::1]/")


@pytest.mark.asyncio
async def test_ssrf_blocks_non_http_scheme() -> None:
    with pytest.raises(SsrfError):
        await validate_url("ftp://example.com")


@pytest.mark.asyncio
async def test_ssrf_blocks_userinfo() -> None:
    with pytest.raises(SsrfError):
        await validate_url("http://user:pass@example.com")


@pytest.mark.asyncio
async def test_ssrf_blocks_dns_to_private() -> None:
    resolver = fake_resolver({"example.com": ["10.0.0.5"]})
    with pytest.raises(SsrfError):
        await validate_url("http://example.com", resolver=resolver)


@pytest.mark.asyncio
async def test_ssrf_allows_public_host() -> None:
    resolver = fake_resolver({"example.com": ["93.184.216.34"]})
    await validate_url("https://example.com", resolver=resolver)
