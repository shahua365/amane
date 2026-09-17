import asyncio
import time
from itertools import pairwise
from unittest.mock import AsyncMock

import pytest
from curl_cffi.requests import Response
from structlog.testing import capture_logs

from amane.config import SiteConfig
from amane.crawlers.http import HttpClient
from amane.net.errors import FailureReason, RequestError, SourceError
from amane.net.http import RateLimiters, WebClient, _retry_after
from amane.net.recording import reset_retry_budget, set_retry_budget
from tests.artwork_support import ImageHTTP


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "headers"),
    [
        (403, b"Forbidden", {}),
        (200, b"Just a moment cloudflare", {}),
        (503, b"Just a moment cloudflare", {}),
        (200, b"challenge", {"cf-mitigated": "challenge"}),
        (200, b"<html>cf-error ray-id</html>", {}),
    ],
)
async def test_blocked_host_no_retry_or_redirect_reentry(
    image_http: ImageHTTP, status: int, body: bytes, headers: dict[str, str]
) -> None:
    origin, target = "https://origin.example/page", "https://blocked.example/challenge"
    image_http.responses["GET", origin] = 302, b"", {"Location": target}
    image_http.responses["GET", target] = status, body, headers
    with pytest.raises(RequestError) as err:
        await image_http.client.request("GET", origin)
    assert err.value.blocked
    for url in [origin, "https://origin.example/another", target, "https://blocked.example/another"]:
        with pytest.raises(RequestError):
            await image_http.client.request("GET", url)
    assert image_http.calls == [("GET", origin), ("GET", target)]


@pytest.mark.asyncio
async def test_queued_request_stops_after_block(image_http: ImageHTTP) -> None:
    image_http.client._limiters.set_rate("blocked.example", 100)
    for n in range(3):
        image_http.responses["GET", f"https://blocked.example/{n}"] = 403, b"", {}
    results = await asyncio.gather(
        *(image_http.client.request("GET", f"https://blocked.example/{n}") for n in range(3)),
        return_exceptions=True,
    )
    assert all(isinstance(result, RequestError) and result.blocked for result in results)
    assert len(image_http.calls) == 1


@pytest.mark.parametrize(
    ("value", "expected"), [("15", 15), (None, 0), ("invalid", 0), ("-2", 0), ("Wed, 21 Oct 2015 07:28:00 GMT", 0)]
)
def test_retry_after_parse(value: str | None, expected: float) -> None:
    assert _retry_after(value) == expected


@pytest.mark.parametrize("status", [403, 404, 410, 429, 503])
@pytest.mark.asyncio
async def test_retry_boundaries(status: int) -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=2, request_jitter=0, retry_backoff=0.001)
    response = Response()
    response.status_code = status
    response.headers["Retry-After"] = "120"
    client._session.request = AsyncMock(return_value=response)
    try:
        with pytest.raises(RequestError) as err:
            await client.request("GET", "https://example.com/item")
        assert err.value.http_status == status
        assert client._session.request.call_count == 1
        if status == 429:
            with pytest.raises(RequestError) as cooldown:
                await client.request("GET", "https://example.com/other-item")
            assert cooldown.value.http_status == 429
            assert client._session.request.call_count == 1
        if status == 404:
            with pytest.raises(RequestError):
                await client.request("GET", "https://example.com/item")
            assert client._session.request.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_source_secret_is_redacted_from_logs_and_exception() -> None:
    secret = "abcdef-cookie-secret"
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=1, request_jitter=0)
    client.register_source("javdb", SiteConfig(cookie={"session": secret}), cookies={"session": secret})
    response = Response()
    response.status_code = 503
    response._content = f"temporary failure {secret}".encode()
    client._source_session("javdb").request = AsyncMock(return_value=response)
    try:
        with capture_logs() as logs, pytest.raises(RequestError) as err:
            await client.request("GET", f"https://example.com/?token={secret}", source_id="javdb")
        assert secret not in str(logs)
        assert secret not in str(err.value)
        assert "***" in str(logs)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_workers_and_retries_share_host_budget() -> None:
    client = WebClient(
        limiters=RateLimiters(default_rate=25),
        max_retries=2,
        request_jitter=0.3,
        retry_backoff=0.001,
        host_concurrency=3,
    )
    times: list[float] = []

    async def send(*args: object, **kwargs: object) -> Response:
        times.append(time.monotonic())
        response = Response()
        response.status_code = 503 if len(times) == 1 else 200
        return response

    client._session.request = AsyncMock(side_effect=send)
    try:
        await asyncio.gather(*(client.request("GET", f"https://example.com/{n}") for n in range(3)))
        assert len(times) == 4
        assert all(b - a >= 0.035 for a, b in pairwise(times))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retired_redirect_never_sent() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=1, request_jitter=0)
    response = Response()
    response.status_code = 302
    response.headers["Location"] = "https://fc2ppvdb.com/articles/1"
    client._session.request = AsyncMock(return_value=response)
    try:
        with pytest.raises(RequestError) as err:
            await client.request("GET", "https://example.com/item")
        assert err.value.http_status == 410
        assert client._session.request.call_count == 1
        with pytest.raises(RequestError):
            await client.request("GET", "https://fc2ppvdb.com/articles/1")
        assert client._session.request.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_queued_worker_respects_new_cooldown() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=25), max_retries=1, request_jitter=0, host_concurrency=3)

    async def send(*args: object, **kwargs: object) -> Response:
        await asyncio.sleep(0.01)
        response = Response()
        response.status_code = 429
        response.headers["Retry-After"] = "120"
        return response

    client._session.request = AsyncMock(side_effect=send)
    try:
        results = await asyncio.gather(
            *(client.request("GET", f"https://example.com/{n}") for n in range(3)), return_exceptions=True
        )
        assert all(isinstance(result, RequestError) and result.http_status == 429 for result in results)
        assert client._session.request.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_source_sessions_are_isolated_and_persistent() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=1, request_jitter=0)
    client.register_source(
        "alpha",
        SiteConfig(user_agent="UA-alpha", cookie={"session": "alpha-secret"}),
        headers={"User-Agent": "UA-alpha"},
        cookies={"session": "alpha-secret"},
    )
    client.register_source(
        "beta",
        SiteConfig(user_agent="UA-beta", cookie={"session": "beta-secret"}),
        headers={"User-Agent": "UA-beta"},
        cookies={"session": "beta-secret"},
    )
    try:
        alpha = client._source_session("alpha")
        beta = client._source_session("beta")
        assert alpha is client._source_session("alpha")
        assert alpha is not beta
        assert alpha.headers["User-Agent"] == "UA-alpha"
        assert beta.headers["User-Agent"] == "UA-beta"
        assert alpha.cookies.get("session") == "alpha-secret"
        assert beta.cookies.get("session") == "beta-secret"
        alpha.cookies.set("rotated", "updated")
        assert client._source_session("alpha").cookies.get("rotated") == "updated"
        assert beta.cookies.get("rotated") is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_identical_gets_are_coalesced() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=1, request_jitter=0)
    response = Response()
    response.status_code = 200

    async def send(*args: object, **kwargs: object) -> Response:
        await asyncio.sleep(0.01)
        return response

    client._session.request = AsyncMock(side_effect=send)
    try:
        results = await asyncio.gather(
            client.request("GET", "https://example.com/same"),
            client.request("GET", "https://example.com/same"),
        )
        assert results == [response, response]
        assert client._session.request.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_timeout_and_server_error_retry_within_bound() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=2, request_jitter=0, retry_backoff=0.001)
    ok = Response()
    ok.status_code = 200
    server_error = Response()
    server_error.status_code = 503
    try:
        client._session.request = AsyncMock(side_effect=[TimeoutError(), ok])
        assert await client.request("GET", "https://example.com/timeout") is ok
        assert client._session.request.call_count == 2
        client._session.request = AsyncMock(side_effect=[server_error, ok])
        assert await client.request("GET", "https://example.com/server") is ok
        assert client._session.request.call_count == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_task_retry_budget_caps_requests_across_retry_loop() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=5, request_jitter=0, retry_backoff=0.001)
    response = Response()
    response.status_code = 503
    client._session.request = AsyncMock(return_value=response)
    token = set_retry_budget(1)
    try:
        with pytest.raises(RequestError):
            await client.request("GET", "https://example.com/budget")
        assert client._session.request.call_count == 2
    finally:
        reset_retry_budget(token)
        await client.close()


@pytest.mark.asyncio
async def test_html_rejects_unexpected_content_type() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=1, request_jitter=0)
    http = HttpClient(client).for_source("mime", SiteConfig())
    response = Response()
    response.status_code = 200
    response.headers["Content-Type"] = "image/png"
    response.content = b"not html"
    client._source_session("mime").request = AsyncMock(return_value=response)
    try:
        with pytest.raises(SourceError) as err:
            await http.get_html("https://example.com/page")
        assert err.value.reason == FailureReason.INVALID_CONTENT_TYPE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_blocked_source_cooldown_does_not_block_other_source() -> None:
    client = WebClient(limiters=RateLimiters(default_rate=100), max_retries=1, request_jitter=0)
    client.register_source("blocked", SiteConfig(blocked_cooldown=60))
    client.register_source("healthy", SiteConfig())
    blocked_response = Response()
    blocked_response.status_code = 503
    blocked_response.content = b"<html>Just a moment cloudflare cf-chl-test</html>"
    healthy_response = Response()
    healthy_response.status_code = 200
    blocked_session = client._source_session("blocked")
    healthy_session = client._source_session("healthy")
    blocked_session.request = AsyncMock(return_value=blocked_response)
    healthy_session.request = AsyncMock(return_value=healthy_response)
    try:
        with pytest.raises(RequestError) as err:
            await client.request("GET", "https://example.com/blocked", source_id="blocked")
        assert err.value.blocked
        with pytest.raises(RequestError) as cooldown:
            await client.request("GET", "https://example.com/again", source_id="blocked")
        assert cooldown.value.reason.value == "cooldown"
        assert blocked_session.request.call_count == 1
        client._source_health["blocked"].cooldown_until = time.monotonic() - 1

        async def probe(*args: object, **kwargs: object) -> Response:
            await asyncio.sleep(0.01)
            return healthy_response

        blocked_session.request = AsyncMock(side_effect=probe)
        probes = await asyncio.gather(
            client.request("GET", "https://example.com/probe-a", source_id="blocked"),
            client.request("GET", "https://example.com/probe-b", source_id="blocked"),
            return_exceptions=True,
        )
        assert sum(result is healthy_response for result in probes) == 1
        assert sum(isinstance(result, RequestError) for result in probes) == 1
        assert blocked_session.request.call_count == 1
        assert await client.request("GET", "https://example.com/ok", source_id="healthy") is healthy_response
    finally:
        await client.close()
