"""curl_cffi TLS 指纹模拟 + 限速 + 重试; 爬虫 / 图片 / Emby 等对外 HTTP 统一经此模块."""

import asyncio
import os
import random
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import aiofiles
import httpx2 as httpx
import structlog
from aiolimiter import AsyncLimiter
from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Response

from .errors import FailureKind, RequestError, RequestFailure
from .recording import get_bound_http_recorder, reset_skip_http_body, set_skip_http_body

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from curl_cffi.requests.session import HttpMethod

    from ..config import SiteConfig

logger = structlog.get_logger()


@contextmanager
def _skip_body_recording() -> Iterator[None]:
    """get_bytes / download 跳过 body 落盘 (仅记 meta)."""
    token = set_skip_http_body(True)
    try:
        yield
    finally:
        reset_skip_http_body(token)


_IMPERSONATE_OPTIONS: tuple[BrowserTypeLiteral, ...] = (
    "chrome123",
    "chrome124",
    "chrome131",
    "chrome136",
    "firefox133",
    "firefox135",
)

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class RateLimiters:
    """严格平滑限流: ``AsyncLimiter(1, 1/rate)``, 桶容量 1, 完全无突发."""

    _BUILTIN_HOSTS = frozenset({"127.0.0.1", "localhost"})
    _LOCALHOST_RATE = 300.0

    def __init__(self, default_rate: float = 5):
        self._default_rate = default_rate
        self._limiters: dict[str, AsyncLimiter] = {
            "127.0.0.1": _make_limiter(self._LOCALHOST_RATE),
            "localhost": _make_limiter(self._LOCALHOST_RATE),
        }

    @classmethod
    def from_config(
        cls,
        network_rate_limits: Mapping[str, float],
        site_configs: Mapping[str, SiteConfig],
        site_urls: Mapping[str, list[str]],
        *,
        source_rates: Mapping[str, float | None] | None = None,
        default_rate: float = 5,
    ) -> RateLimiters:
        """优先级: 全局 network.rate_limits > site_config.rate_limit > 默认."""
        instance = cls(default_rate=default_rate)

        # site_config.rate_limit (低优先级)
        for site_name, cfg in site_configs.items():
            if cfg.rate_limit is None:
                continue
            base_urls = list(site_urls.get(str(site_name), []))
            if cfg.base_url:
                base_urls.append(cfg.base_url)
            for url in base_urls:
                host = httpx.URL(url).host
                if host:
                    existing = instance._limiters.get(host)
                    rate = min(cfg.rate_limit, 1 / existing.time_period) if existing else cfg.rate_limit
                    instance._limiters[host] = _make_limiter(rate)

        # Plugin descriptors can provide a source-level default without being
        # forced into the core SiteConfig model.
        for source_name, rate in (source_rates or {}).items():
            if rate is None:
                continue
            for url in site_urls.get(str(source_name), []):
                host = httpx.URL(url).host
                if host and host not in instance._limiters:
                    instance._limiters[host] = _make_limiter(rate)

        # network.rate_limits (高优先级, 覆盖上一层)
        for host, rate in network_rate_limits.items():
            instance._limiters[host] = _make_limiter(rate)

        configured = len(instance._limiters) - len(cls._BUILTIN_HOSTS)
        if configured:
            logger.info("rate_limiters.created", configured_hosts=configured)

        return instance

    def get(self, host: str, *, rate: float | None = None) -> AsyncLimiter:
        if host not in self._limiters:
            self._limiters[host] = _make_limiter(rate or self._default_rate)
        return self._limiters[host]

    def set_rate(self, host: str, rate: float) -> None:
        self._limiters[host] = _make_limiter(rate)


def _make_limiter(rate: float) -> AsyncLimiter:
    """``AsyncLimiter(1, 1/rate)``: 桶容量 1, 无突发."""
    return AsyncLimiter(1, 1 / rate)


def _retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    if value.strip().isdigit():
        return float(value)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except ValueError, TypeError, OverflowError:
        return 0.0


def _failure_body(resp: Response | None) -> bytes | None:
    if resp is None:
        return None
    try:
        content = resp.content
    except Exception:
        return None
    return content[:_FAILURE_BODY_LIMIT]


# 失败响应正文保留上限 (防大响应驻留内存)
_FAILURE_BODY_LIMIT = 64 * 1024


class WebClient:
    def __init__(
        self,
        *,
        proxy: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_clients: int = 50,
        limiters: RateLimiters,
        retry_backoff: float = 2.0,
        retry_max_wait: float = 60.0,
        request_jitter: float = 0.3,
        host_concurrency: int = 1,
        negative_cache_ttl: float = 43200.0,
    ):
        self._proxy = proxy
        self._timeout = timeout
        self._max_retries = max_retries
        self._limiters = limiters
        self._retry_backoff = retry_backoff
        self._retry_max_wait = retry_max_wait
        self._request_jitter = request_jitter
        self._host_concurrency = host_concurrency
        self._host_slots: dict[str, asyncio.Semaphore] = {}
        self._host_cooldown: dict[str, float] = {}
        self._not_found: dict[str, float] = {}
        self._negative_cache_ttl = negative_cache_ttl
        self._session = AsyncSession(
            max_clients=max_clients,
            verify=False,
            max_redirects=20,
            timeout=timeout,
            impersonate=random.choice(_IMPERSONATE_OPTIONS),
        )

    async def request(
        self,
        method: HttpMethod,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        data: Any | None = None,
        json: Any | None = None,
        use_proxy: bool = True,
        timeout: float | None = None,
        allow_redirects: bool = True,
        ok_statuses: frozenset[int] | None = None,
    ) -> Response:
        """``ok_statuses`` 额外视为成功 (例如 RSS 304), 不重试、不当失败. 重试用尽后抛 ``RequestError``."""
        host = httpx.URL(url).host.rstrip(".")
        if host == "fc2ppvdb.com" or host.endswith(".fc2ppvdb.com"):
            raise RequestError(url, RequestFailure(kind=FailureKind.HTTP_STATUS, status=410, message="retired source"))
        if method == "GET" and self._not_found.get(url, 0) > time.monotonic():
            raise RequestError(
                url, RequestFailure(kind=FailureKind.HTTP_STATUS, status=404, message="cached not found")
            )

        t0 = time.monotonic()
        failure: RequestFailure | None = None
        last_resp: Response | None = None
        attempts = max(1, self._max_retries)
        for attempt in range(attempts):
            should_retry = False
            try:
                resp = await self._request_hops(
                    method,
                    url,
                    headers=headers,
                    cookies=cookies,
                    data=data,
                    json=json,
                    use_proxy=use_proxy,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                )
                last_resp = resp
                if method == "GET" and resp.status_code == 404 and self._negative_cache_ttl:
                    now = time.monotonic()
                    self._not_found = {key: expiry for key, expiry in self._not_found.items() if expiry > now}
                    self._not_found[url] = now + self._negative_cache_ttl

                extra_ok = ok_statuses or frozenset()
                if (
                    resp.status_code < 300
                    or resp.status_code in extra_ok
                    or (resp.status_code in (301, 302, 307, 308) and resp.headers.get("Location"))
                ):
                    self._record_exchange(method, resp.url or url, resp=resp, error=None, t0=t0)
                    return resp

                failure = RequestFailure(
                    kind=FailureKind.HTTP_STATUS,
                    status=resp.status_code,
                    message=f"HTTP {resp.status_code}",
                    body=_failure_body(resp),
                )
                should_retry = resp.status_code in _RETRYABLE_STATUS_CODES

            except RequestError:
                raise
            except CurlError as e:
                failure = RequestFailure(kind=FailureKind.CURL, message=f"curl error: {e}")
                should_retry = True
                last_resp = None
            except TimeoutError:
                failure = RequestFailure(kind=FailureKind.TIMEOUT, message="timeout")
                should_retry = True
                last_resp = None
            except Exception as e:
                failure = RequestFailure(kind=FailureKind.UNEXPECTED, message=f"unexpected: {type(e).__name__}: {e}")
                last_resp = None

            if not should_retry:
                break

            if attempt < attempts - 1:
                retry_after = _retry_after(last_resp.headers.get("Retry-After")) if last_resp else 0.0
                if retry_after > self._retry_max_wait:
                    break
                wait = max(retry_after, min(self._retry_max_wait, self._retry_backoff * 2**attempt))
                logger.warning(
                    "request retry",
                    method=method,
                    url=url,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    error=failure.message,
                    retry_in=wait,
                )
                await asyncio.sleep(wait)

        log_failed = logger.debug if get_bound_http_recorder() is not None else logger.error
        log_failed(
            "request failed",
            method=method,
            url=url,
            error=failure.message if failure else None,
            attempts=attempt + 1,
            duration_s=round(time.monotonic() - t0, 2),
        )
        self._record_exchange(
            method, url, resp=last_resp, error=failure.message if failure else None, t0=t0, attempts=attempt + 1
        )
        raise RequestError(url, failure)

    async def _request_hops(
        self,
        method: HttpMethod,
        url: str,
        *,
        headers: dict[str, str] | None,
        cookies: dict[str, str] | None,
        data: Any,
        json: Any,
        use_proxy: bool,
        timeout: float | None,
        allow_redirects: bool,
    ) -> Response:
        for _ in range(21):
            host = (urlsplit(url).hostname or "").rstrip(".")
            if host == "fc2ppvdb.com" or host.endswith(".fc2ppvdb.com"):
                raise RequestError(
                    url, RequestFailure(kind=FailureKind.HTTP_STATUS, status=410, message="retired source")
                )
            slots = self._host_slots.setdefault(host, asyncio.Semaphore(self._host_concurrency))
            async with slots:
                remaining = self._host_cooldown.get(host, 0) - time.monotonic()
                if remaining > 0:
                    raise RequestError(
                        url, RequestFailure(kind=FailureKind.HTTP_STATUS, status=429, message="host cooling down")
                    )
                limiter = self._limiters.get(host)
                # 抖动围绕额外等待变化, 不突破最短请求间隔.
                if self._request_jitter:
                    await asyncio.sleep(random.uniform(0, 2 * self._request_jitter) * limiter.time_period)
                await limiter.acquire()
                if self._host_cooldown.get(host, 0) > time.monotonic():
                    raise RequestError(
                        url, RequestFailure(kind=FailureKind.HTTP_STATUS, status=429, message="host cooling down")
                    )
                resp = await self._session.request(
                    method,
                    url,
                    headers=headers,
                    cookies=cookies,
                    data=data,
                    json=json,
                    proxy=self._proxy if use_proxy else None,
                    timeout=timeout or self._timeout,
                    allow_redirects=False,
                )
                if resp.status_code == 429:
                    delay = max(_retry_after(resp.headers.get("Retry-After")), self._retry_backoff)
                    self._host_cooldown[host] = time.monotonic() + delay
            location = resp.headers.get("Location")
            if not allow_redirects or resp.status_code not in (301, 302, 303, 307, 308) or not location:
                return resp
            target = urljoin(url, location)
            target_host = urlsplit(target).hostname or ""
            self._limiters.get(target_host, rate=1 / self._limiters.get(host).time_period)
            if urlsplit(target).hostname != host:
                cookies = None
                headers = {
                    key: value
                    for key, value in (headers or {}).items()
                    if key.lower() not in {"cookie", "authorization", "proxy-authorization"}
                }
            if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
                method, data, json = "GET", None, None
            url = target
        raise RequestError(url, RequestFailure(kind=FailureKind.UNEXPECTED, message="redirect limit exceeded"))

    def _record_exchange(
        self,
        method: str,
        url: str,
        *,
        resp: Response | None,
        error: str | None,
        t0: float,
        attempts: int | None = None,
    ) -> None:
        rec = get_bound_http_recorder()
        if rec is None:
            return
        content_type: str | None = None
        status: int | None = None
        body: bytes | None = None
        if resp is not None:
            status = resp.status_code
            content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
            try:
                body = resp.content
            except Exception:
                body = None
        rec.record_http(
            method=str(method),
            url=url,
            status=status,
            error=error,
            content_type=content_type,
            body=body,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            attempts=attempts,
        )

    async def get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        encoding: str = "utf-8",
        use_proxy: bool = True,
    ) -> str:
        resp = await self.request("GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy)
        try:
            resp.encoding = encoding
            return resp.text
        except Exception as e:
            raise RequestError(url, RequestFailure(kind=FailureKind.UNEXPECTED, message=f"decode error: {e}")) from e

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
    ) -> Any:
        resp = await self.request("GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy)
        try:
            return resp.json()
        except Exception as e:
            raise RequestError(
                url, RequestFailure(kind=FailureKind.UNEXPECTED, message=f"JSON parse error: {e}")
            ) from e

    async def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
    ) -> bytes:
        with _skip_body_recording():
            resp = await self.request("GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy)
        return resp.content

    async def post_text(
        self,
        url: str,
        *,
        data: Any | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        encoding: str = "utf-8",
        use_proxy: bool = True,
    ) -> str:
        resp = await self.request(
            "POST", url, data=data, json=json, headers=headers, cookies=cookies, use_proxy=use_proxy
        )
        try:
            resp.encoding = encoding
            return resp.text
        except Exception as e:
            raise RequestError(url, RequestFailure(kind=FailureKind.UNEXPECTED, message=f"decode error: {e}")) from e

    async def post_json(
        self,
        url: str,
        *,
        data: Any | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
    ) -> Any:
        resp = await self.request(
            "POST", url, data=data, json=json, headers=headers, cookies=cookies, use_proxy=use_proxy
        )
        try:
            return resp.json()
        except Exception as e:
            raise RequestError(
                url, RequestFailure(kind=FailureKind.UNEXPECTED, message=f"JSON parse error: {e}")
            ) from e

    async def get_filesize(self, url: str, *, use_proxy: bool = True) -> int | None:
        try:
            resp = await self.request("HEAD", url, use_proxy=use_proxy)
        except RequestError:
            return None
        if resp.status_code >= 400:
            return None
        try:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
        except ValueError, TypeError:
            return None

    async def download(
        self,
        url: str,
        dest: Path,
        *,
        use_proxy: bool = True,
        chunked_threshold: int = 2 * 1024**2,
        chunk_size: int = 1 * 1024**2,
        download_concurrency: int = 10,
    ) -> bool:
        """大于 chunked_threshold 时分块并发下载. 失败返回 False."""
        file_size = await self.get_filesize(url, use_proxy=use_proxy)

        if file_size and file_size > chunked_threshold:
            return await self._download_chunked(
                url, dest, file_size, use_proxy=use_proxy, chunk_size=chunk_size, concurrency=download_concurrency
            )

        try:
            content = await self.get_bytes(url, use_proxy=use_proxy)
        except RequestError as e:
            logger.error("download failed", url=url, error=e.message)
            return False

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(dest, "wb") as f:
                await f.write(content)
            return True
        except Exception as e:
            logger.error("file write failed", path=str(dest), error=str(e))
            return False

    async def _download_chunked(
        self,
        url: str,
        dest: Path,
        file_size: int,
        *,
        use_proxy: bool = True,
        chunk_size: int = 1 * 1024**2,
        concurrency: int = 10,
    ) -> bool:
        parts = [(s, min(s + chunk_size - 1, file_size - 1)) for s in range(0, file_size, chunk_size)]

        logger.info("chunked download started", url=url, chunks=len(parts), size=file_size)

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(dest, "wb") as f:
                await f.truncate(file_size)
        except Exception as e:
            logger.error("file create failed", path=str(dest), error=str(e))
            return False

        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch_chunk(start: int, end: int) -> str:
            async with semaphore:
                try:
                    resp = await self.request(
                        "GET", url, headers={"Range": f"bytes={start}-{end}"}, use_proxy=use_proxy
                    )
                except RequestError as e:
                    return e.message
                async with aiofiles.open(dest, "rb+") as f:
                    await f.seek(start)
                    await f.write(resp.content)
                return ""

        results = await asyncio.gather(*[_fetch_chunk(s, e) for s, e in parts], return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("chunk download failed", chunk=i, url=url, error=str(result))
                return False
            if result:  # 非空错误字符串
                logger.error("chunk download failed", chunk=i, url=url, error=result)
                return False

        logger.info("chunked download complete", url=url)
        return True

    async def close(self) -> None:
        try:
            await self._session.close()
        except Exception as e:
            logger.debug("session close error (ignored)", error=str(e))


class BrowserClient:
    """延迟初始化: 浏览器仅在首次使用时启动."""

    def __init__(self, *, headless: bool = True, default_timeout: float = 30000):
        self._headless = headless
        self._default_timeout = default_timeout
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        async with self._lock:
            if self._browser is not None:
                return
            from patchright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                channel="chrome",
                headless=self._headless if os.getenv("AMANE_SHOW_BROWSER") is None else False,
                args=["--disable-blink-features=AutomationControlled"],
            )

    async def get_page(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str | None, str]:
        """成功返回 ``(html, "")``, 失败返回 ``(None, 错误信息)``."""
        effective_timeout = timeout if timeout is not None else self._default_timeout
        try:
            await self._ensure_browser()
            assert self._browser is not None  # _ensure_browser 已保证
            page = await self._browser.new_page()
            try:
                await page.goto(url, timeout=effective_timeout, wait_until="domcontentloaded")
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=effective_timeout)
                content = await page.content()
                return content, ""
            finally:
                await page.close()
        except Exception as e:
            logger.error("browser page fetch failed", url=url, error=str(e))
            return None, str(e)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
