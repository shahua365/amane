import asyncio
from typing import TYPE_CHECKING

import pytest

from amane.aggregate import ALL_FIELDS, CrawlerLike, aggregate
from amane.crawlers.models import FetchOptions, MediaMetadata, SearchQuery
from amane.enums import MetadataField
from amane.handlers.file import _acquire_first_local
from amane.media.artwork import rescue_artwork
from tests.artwork_support import ImageHTTP, image_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from amane.media import ResourceStore


@pytest.mark.asyncio
@pytest.mark.parametrize("head", [200, 405, 501])
async def test_head_get_cache_and_organize(resource_store: ResourceStore, image_http: ImageHTTP, head: int) -> None:
    url = "https://images.example/valid"
    image_http.add(url, head=head)
    local = await resource_store.acquire_image(url, image_http.client)
    assert local is not None and local.read_bytes() == image_bytes()
    assert image_http.calls == [("HEAD", url), ("GET", url)]
    # 前置失效候选也不能使整理重新出站.
    organized = await _acquire_first_local(["https://dead.example/image", url], resource_store, image_http.client)
    assert organized == local
    assert len(image_http.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"<html>not an image</html>", image_bytes()[:40]])
async def test_invalid_bytes_never_cached(resource_store: ResourceStore, image_http: ImageHTTP, body: bytes) -> None:
    bad, good = "https://images.example/bad.jpg", "https://images.example/good.jpg"
    image_http.add(bad, body=body)
    image_http.add(good)
    selected = await resource_store.acquire_first_image([bad, bad, good], image_http.client)
    assert selected.used_url == good and selected.failed == [bad]
    assert await resource_store.resolve(bad) is None
    assert len(await resource_store.list_all()) == 1
    assert image_http.calls == [("HEAD", bad), ("GET", bad), ("HEAD", good), ("GET", good)]
    assert not list((resource_store.data_dir / "resources").glob("*.tmp"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("head", "get"), [(403, 200), (200, 403)])
async def test_blocked_image_host_stops_candidates(
    resource_store: ResourceStore, image_http: ImageHTTP, head: int, get: int
) -> None:
    blocked = "https://blocked.example/one"
    alternative = "https://other.example/good"
    image_http.add(blocked, head=head, get=get)
    image_http.add(alternative)
    selected = await resource_store.acquire_first_image(
        [blocked, "https://blocked.example/two", alternative], image_http.client
    )
    assert selected.used_url == alternative
    expected = [("HEAD", blocked)] + ([("GET", blocked)] if head == 200 else [])
    assert image_http.calls == [*expected, ("HEAD", alternative), ("GET", alternative)]


@pytest.mark.asyncio
async def test_concurrent_image_and_manual_import(
    resource_store: ResourceStore, image_http: ImageHTTP, tmp_path: Path
) -> None:
    url = "https://images.example/same"
    image_http.add(url)
    paths = await asyncio.gather(*(resource_store.acquire_image(url, image_http.client) for _ in range(3)))
    assert all(path == paths[0] and path is not None for path in paths)
    assert len(image_http.calls) == 2 and len(await resource_store.list_all()) == 1
    source = tmp_path / "manual.png"
    source.write_bytes(image_bytes())
    internal = await resource_store.import_image(source)
    source.unlink()
    selected = await resource_store.acquire_first_image([internal], image_http.client)
    assert selected.path is not None and selected.path.read_bytes() == image_bytes()
    assert len(image_http.calls) == 2
    record = await resource_store.get_by_url_hash(internal.rsplit("/", 1)[-1])
    assert record is not None and str(tmp_path) not in str(record[0].meta)
    source.write_text("invalid image", encoding="utf-8")
    with pytest.raises(ValueError, match="解码"):
        await resource_store.import_image(source)


@pytest.mark.asyncio
async def test_malformed_candidate_skips_without_network(resource_store: ResourceStore, image_http: ImageHTTP) -> None:
    url = "https://images.example/valid"
    image_http.add(url)
    result = await resource_store.acquire_first_image(
        ["", "file:///local/image", "https://", "https://[invalid", url], image_http.client
    )
    assert result.used_url == url
    assert image_http.calls == [("HEAD", url), ("GET", url)]


class ArtworkCrawler:
    def __init__(self, data: MediaMetadata | None) -> None:
        self.data = data
        self.calls = 0

    async def fetch(self, query: SearchQuery, options: FetchOptions | None = None) -> MediaMetadata | None:
        self.calls += 1
        return self.data


@pytest.mark.asyncio
@pytest.mark.parametrize("main_valid", [False, True])
async def test_artwork_only_source_cannot_overwrite_metadata(
    resource_store: ResourceStore, image_http: ImageHTTP, main_valid: bool
) -> None:
    url = "https://images.example/good"
    image_http.add(url)
    main = ArtworkCrawler(MediaMetadata(number="TEST-001", title="Confirmed", poster_urls=[url] if main_valid else []))
    fallback = ArtworkCrawler(MediaMetadata(number="TEST-001", title="Untrusted", tags=["wrong"], poster_urls=[url]))
    crawlers: dict[str, CrawlerLike] = {"primary": main, "fallback": fallback}
    priorities = {field: ["primary"] for field in ALL_FIELDS}
    priorities[MetadataField.POSTER_URLS] = ["primary", "fallback"]
    result = await aggregate(SearchQuery("TEST-001"), crawlers, priorities, defer_artwork=True)
    before = result.metadata.title, result.metadata.tags, result.field_sources.copy(), result.raw.copy()
    assert main.calls == 1 and fallback.calls == 0
    art = await rescue_artwork(
        SearchQuery("TEST-001"), result, crawlers, priorities, resource_store, image_http.client, thumb=False
    )
    assert art.poster_urls == [url]
    assert fallback.calls == (0 if main_valid else 1)
    assert (result.metadata.title, result.metadata.tags, result.field_sources, result.raw) == before
    assert await resource_store.resolve(url) is not None


@pytest.mark.asyncio
async def test_artwork_independent_priorities_and_blacklist(
    resource_store: ResourceStore, image_http: ImageHTTP
) -> None:
    a, b = "https://images.example/a", "https://images.example/b"
    image_http.add(a)
    image_http.add(b)
    main = ArtworkCrawler(MediaMetadata(number="TEST-001", title="Confirmed"))
    first = ArtworkCrawler(MediaMetadata(number="TEST-001", poster_urls=[a], thumb_urls=[a]))
    second = ArtworkCrawler(MediaMetadata(number="TEST-001", poster_urls=[b], thumb_urls=[b]))
    excluded = ArtworkCrawler(MediaMetadata(number="TEST-001", poster_urls=["https://excluded.example/i"]))
    crawlers: dict[str, CrawlerLike] = {"primary": main, "first": first, "second": second, "excluded": excluded}
    priorities = {field: ["primary"] for field in ALL_FIELDS}
    priorities[MetadataField.POSTER_URLS] = ["primary", "first", "second"]
    priorities[MetadataField.THUMB_URLS] = ["primary", "second", "first"]
    query = SearchQuery("TEST-001")
    result = await aggregate(query, crawlers, priorities, defer_artwork=True)
    art = await rescue_artwork(query, result, crawlers, priorities, resource_store, image_http.client)
    assert art.poster_urls == [a] and art.thumb_urls == [b]
    assert first.calls == second.calls == 1 and excluded.calls == 0
    assert image_http.calls == [("HEAD", a), ("GET", a), ("HEAD", b), ("GET", b)]


@pytest.mark.asyncio
async def test_same_failed_candidate_not_retried_across_fields(
    resource_store: ResourceStore, image_http: ImageHTTP
) -> None:
    bad, good = "https://images.example/bad", "https://images.example/good"
    image_http.add(bad, body=b"not an image")
    image_http.add(good)
    main = ArtworkCrawler(MediaMetadata(number="TEST-001", title="Confirmed", poster_urls=[bad], thumb_urls=[bad]))
    fallback = ArtworkCrawler(MediaMetadata(number="TEST-001", poster_urls=[good], thumb_urls=[good]))
    crawlers: dict[str, CrawlerLike] = {"primary": main, "fallback": fallback}
    priorities = {field: ["primary", "fallback"] for field in ALL_FIELDS}
    query = SearchQuery("TEST-001")
    result = await aggregate(query, crawlers, priorities, defer_artwork=True)
    art = await rescue_artwork(query, result, crawlers, priorities, resource_store, image_http.client)
    assert art.poster_urls == art.thumb_urls == [good, bad]
    assert image_http.calls == [("HEAD", bad), ("GET", bad), ("HEAD", good), ("GET", good)]
