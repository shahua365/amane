from typing import TYPE_CHECKING

import pytest

from tests.artwork_support import ImageHTTP, image_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI
    from httpx2 import AsyncClient

    from amane.db.repository import Repository


@pytest.mark.asyncio
async def test_manual_artwork_fallback_api(
    client: AsyncClient, app: FastAPI, repo: Repository, safe_path: Path, tmp_path: Path, image_http: ImageHTTP
) -> None:
    app.state.runtime.web_client = image_http.client
    meta = await repo.upsert_metadata(number="TEST-001", title="Confirmed", tags=["confirmed"])
    endpoint = f"metadata/{meta.id}/artwork-fallback"
    source = safe_path / "image.png"
    source.write_bytes(image_bytes())
    for payload in [
        {},
        {"url": "file:///etc/passwd"},
        {"url": "https://example.test/i", "path": str(source)},
        {"path": ""},
    ]:
        response = await client.post(endpoint, json=payload)
        assert response.status_code == 422 and response.json()["detail"]
    forbidden = await client.post(endpoint, json={"path": str(tmp_path / "outside.png")})
    assert forbidden.status_code == 403
    missing = await client.post(endpoint, json={"path": str(safe_path / "missing.png")})
    assert missing.status_code == 404
    source.write_text("<html>invalid</html>", encoding="utf-8")
    invalid = await client.post(endpoint, json={"path": str(source)})
    assert invalid.status_code == 400
    source.write_bytes(image_bytes())
    manual = await client.post(endpoint, json={"path": str(source)})
    assert manual.status_code == 200
    internal = manual.json()["poster_urls"][0]
    assert internal.startswith("/api/resources/")
    source.unlink()
    cached = await client.get(internal.removeprefix("/api/"))
    assert cached.status_code == 200 and cached.content == image_bytes()
    # 本地图片可用时不访问用户提供的最终回退 URL.
    retained = await client.post(endpoint, json={"url": "https://unused.example/image"})
    assert retained.status_code == 200 and retained.json()["poster_urls"] == [internal]
    assert image_http.calls == []
    remote = "https://images.example/image"
    image_http.add(remote)
    imported = await client.post(endpoint, json={"kind": "thumb", "url": remote})
    assert imported.status_code == 200 and imported.json()["thumb_urls"] == [remote]
    assert imported.json()["title"] == "Confirmed" and imported.json()["tags"] == ["confirmed"]
    assert image_http.calls == [("HEAD", remote), ("GET", remote)]
    assert (await client.post("metadata/999999/artwork-fallback", json={"url": remote})).status_code == 404
