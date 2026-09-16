import asyncio
import time
from itertools import pairwise
from unittest.mock import AsyncMock

import pytest
from curl_cffi.requests import Response

from amane.net.errors import RequestError
from amane.net.http import RateLimiters, WebClient, _retry_after
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


@pytest.mark.parametrize("status", [403, 404, 429, 503])
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
