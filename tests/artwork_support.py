"""合成图片与内存 HTTP 响应, 不访问外部站点."""

from io import BytesIO
from unittest.mock import AsyncMock

from curl_cffi.requests import Response
from PIL import Image

from amane.net.http import RateLimiters, WebClient


def image_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (40, 60), "blue").save(buf, format="PNG")
    return buf.getvalue()


class ImageHTTP:
    def __init__(self) -> None:
        self.client = WebClient(limiters=RateLimiters(default_rate=10000), max_retries=3, request_jitter=0)
        self.responses: dict[tuple[str, str], tuple[int, bytes, dict[str, str]]] = {}
        self.calls: list[tuple[str, str]] = []
        self.client._session.request = AsyncMock(side_effect=self.send)

    async def send(self, method: str, url: str, **kwargs: object) -> Response:
        self.calls.append((method, url))
        status, body, headers = self.responses.get((method, url), (404, b"", {}))
        response = Response()
        response.status_code, response.content, response.url = status, body, url
        response.headers.update(headers)
        return response

    def add(self, url: str, *, head: int = 200, get: int = 200, body: bytes | None = None) -> None:
        self.responses["HEAD", url] = head, b"", {}
        self.responses["GET", url] = get, body if body is not None else image_bytes(), {}
