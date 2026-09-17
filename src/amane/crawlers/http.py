"""爬虫 HTTP 封装. ``get_html`` / ``get_rendered`` 命中拦截页抛 ``SourceError``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from ..config import SiteConfig
    from ..net.http import BrowserClient, WebClient

from ..net.errors import RequestError, SourceError, classify_block


class HttpClient:
    """构造函数注入 WebClient / BrowserClient. ``get_json`` 不做 HTML 拦截启发式."""

    def __init__(
        self,
        web: WebClient,
        browser: BrowserClient | None = None,
        *,
        source_id: str | None = None,
        bound_headers: dict[str, str] | None = None,
        bound_cookies: dict[str, str] | None = None,
    ):
        self._web = web
        self._browser = browser
        self._source_id = source_id
        self._bound_headers = bound_headers or {}
        self._bound_cookies = bound_cookies or {}

    def for_source(
        self,
        source_id: str,
        config: SiteConfig | None,
        *,
        default_headers: dict[str, str] | None = None,
        default_cookies: dict[str, str] | None = None,
    ) -> HttpClient:
        headers = dict(default_headers or {})
        cookies = dict(default_cookies or {})
        if config is not None:
            headers.update(config.headers)
            if config.user_agent:
                headers["User-Agent"] = config.user_agent
            cookies.update(config.cookie)
        self._web.register_source(source_id, config, headers=headers, cookies=cookies)
        return HttpClient(
            self._web,
            self._browser,
            source_id=source_id,
            bound_headers=headers,
            bound_cookies=cookies,
        )

    def _request_headers(self, headers: dict[str, str] | None) -> dict[str, str] | None:
        return None if headers == self._bound_headers else headers

    def _request_cookies(self, cookies: dict[str, str] | None) -> dict[str, str] | None:
        return None if cookies == self._bound_cookies else cookies

    @property
    def web_client(self) -> WebClient:
        """Shared low-level client exposed to trusted source plugins."""
        return self._web

    async def get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        return await self._web.get_text(
            url,
            headers=self._request_headers(headers),
            cookies=self._request_cookies(cookies),
            encoding=encoding,
            source_id=self._source_id,
        )

    async def get_html(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        text = await self._web.get_text(
            url,
            headers=self._request_headers(headers),
            cookies=self._request_cookies(cookies),
            encoding=encoding,
            source_id=self._source_id,
            expected_content_types=("text/html", "application/xhtml+xml", "text/plain"),
        )
        reason = classify_block(text)
        if reason is not None:
            raise SourceError(reason, detail=url)
        return text

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> Any:
        return await self._web.get_json(
            url,
            headers=self._request_headers(headers),
            cookies=self._request_cookies(cookies),
            source_id=self._source_id,
        )

    async def get_bytes(self, url: str, *, headers: dict[str, str] | None = None) -> bytes:
        return await self._web.get_bytes(url, headers=self._request_headers(headers), source_id=self._source_id)

    async def post_json(
        self,
        url: str,
        *,
        json: Any,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._web.post_json(
            url, json=json, headers=self._request_headers(headers), source_id=self._source_id
        )

    async def get_rendered(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        timeout: float = 30000,
    ) -> str:
        # 未配置浏览器或抓取失败抛 RequestError; 拦截页抛 SourceError.
        if self._browser is None:
            raise RequestError(url, "BrowserClient not configured")
        html, err = await self._browser.get_page(url, wait_for=wait_for, timeout=timeout)
        if html is None:
            raise RequestError(url, err)
        reason = classify_block(html)
        if reason is not None:
            raise SourceError(reason, detail=url)
        return html

    async def download(self, url: str, dest: Path) -> bool:
        # 失败返回 False, 不抛异常.
        return await self._web.download(url, dest)
