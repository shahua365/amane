from unittest.mock import AsyncMock

import pytest

from amane.aggregate import ALL_FIELDS, aggregate
from amane.crawlers.base import Crawler
from amane.crawlers.http import HttpClient
from amane.crawlers.models import MediaMetadata, SearchQuery, film_actors
from amane.crawlers.sites.fc2db import FC2DBCrawler
from amane.crawlers.sites.fourhoi import FourhoiCrawler
from amane.crawlers.sites.paipancon import PaipanconCrawler
from amane.crawlers.sites.ppvdatabank import PPVDataBankCrawler
from amane.enums import MetadataField
from amane.net.errors import FailureKind, RequestError, RequestFailure
from amane.parsing import ContentType

PPVDATABANK_HTML = """
<html><head><meta property="og:image" content="/article/1234567/img/main.webp"></head><body>
<article><h1>FC2-PPV-1234567 Sample title</h1>
<ul><li>販売日 : 2026/09/01</li><li>再生時間 : 01:23:45</li><li>販売者 : Sample seller</li></ul>
<a href="https://adult.contents.fc2.com/article/1234567/">FC2</a>
<h2>サンプル画像</h2><div><img src="img/sample-1.webp"><img data-src="/sample-2.jpg"></div>
<h2>サンプル動画</h2><img src="/unrelated.jpg">
</article></body></html>
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["FC2-PPV-1234567", "FC2-1234567", "1234567"])
async def test_ppvdatabank_complete_fixture(number: str, http_client: HttpClient, mock_web_client: AsyncMock) -> None:
    mock_web_client.get_text.return_value = PPVDATABANK_HTML
    result = await PPVDataBankCrawler(http_client).fetch(SearchQuery(number, content_type=ContentType.FC2))
    assert result is not None
    assert result.title == "Sample title"
    assert result.release == "2026-09-01"
    assert result.runtime == 83
    assert result.studio == "Sample seller"
    assert result.publisher == "FC2"
    assert result.external_id == "https://adult.contents.fc2.com/article/1234567/"
    assert result.poster_urls == [
        "https://ppvdatabank.com/article/1234567/img/main.webp",
        "https://ppvdatabank.com/article/1234567/img/thumb.webp",
    ]
    assert result.extrafanart == [
        "https://ppvdatabank.com/article/1234567/img/sample-1.webp",
        "https://ppvdatabank.com/sample-2.jpg",
    ]


@pytest.mark.asyncio
async def test_ppvdatabank_missing_main_uses_known_candidate(
    http_client: HttpClient, mock_web_client: AsyncMock
) -> None:
    mock_web_client.get_text.return_value = """
    <article><h1>FC2-PPV-1234567 Title</h1><p>販売日: 2026-09-01</p>
    <h2>サンプル画像</h2></article>
    """
    result = await PPVDataBankCrawler(http_client).fetch(SearchQuery("FC2-1234567"))
    assert result is not None
    assert result.poster_urls == ["https://ppvdatabank.com/article/1234567/img/thumb.webp"]
    assert result.extrafanart == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tailwind", [True, False])
async def test_fc2db_selector_fallbacks(tailwind: bool, http_client: HttpClient, mock_web_client: AsyncMock) -> None:
    title = '<h2 class="text-xl font-extrabold">FC2-PPV-1234567 Main title</h2>' if tailwind else "<h1>Main title</h1>"
    poster = (
        '<img class="wp-post-image" src="/cover.jpg">' if tailwind else '<meta property="og:image" content="/og.jpg">'
    )
    mock_web_client.get_text.return_value = f"""
    <main>{title}<article>{poster}<a href="/actress/a">Actor A</a><a href="/actress/a">Actor A</a></article>
    <div class="grid"><div><a href="https://adult.contents.fc2.com/article/1234567/">official</a></div></div>
    </main>
    """
    result = await FC2DBCrawler(http_client).fetch(SearchQuery("FC2-1234567"))
    assert result is not None
    assert result.title == "Main title"
    assert [actor.name for actor in result.actors] == ["Actor A"]
    assert result.poster_urls == [f"https://fc2db.net/{'cover.jpg' if tailwind else 'og.jpg'}"]
    assert result.external_id == "https://adult.contents.fc2.com/article/1234567/"


@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["FC2-PPV-1234567", "FC2-1234567", "1234567"])
async def test_fourhoi_is_candidate_only(number: str, http_client: HttpClient, mock_web_client: AsyncMock) -> None:
    result = await FourhoiCrawler(http_client).fetch(SearchQuery(number, content_type=ContentType.FC2))
    assert result is not None
    assert result.poster_urls == ["https://fourhoi.com/fc2-ppv-1234567/cover.jpg"]
    assert result.trailer_urls == ["https://fourhoi.com/fc2-ppv-1234567/preview.mp4"]
    mock_web_client.get_text.assert_not_called()
    assert FourhoiCrawler.profile().headers == {"Referer": "https://fourhoi.com/"}


@pytest.mark.asyncio
async def test_paipancon_relative_images_dedupe_ads_and_trailer(
    http_client: HttpClient, mock_web_client: AsyncMock
) -> None:
    mock_web_client.get_text.return_value = """
    <img src="../data/FC2-PPV-1234567/scene-1.jpg">
    <img data-src="/fc2daily/data/FC2-PPV-1234567/scene-1.jpg">
    <img src="/fc2daily/data/FC2-PPV-1234567/moechat_ads.jpg">
    <img src="https://mc.yandex.ru/fc2-ppv-1234567.gif">
    <img src="/fc2daily/data/FC2-PPV-7654321/other.jpg">
    <video><source src="../data/FC2-PPV-1234567/preview.mp4"></video>
    """
    result = await PaipanconCrawler(http_client).fetch(SearchQuery("FC2-1234567"))
    assert result is not None
    assert result.poster_urls == ["https://paipancon.com/fc2daily/data/FC2-PPV-1234567/cover.jpg"]
    assert result.extrafanart == ["https://paipancon.com/fc2daily/data/FC2-PPV-1234567/scene-1.jpg"]
    assert result.trailer_urls == ["https://paipancon.com/fc2daily/data/FC2-PPV-1234567/preview.mp4"]
    assert PaipanconCrawler.profile().headers == {"Referer": "https://paipancon.com/"}


class _Primary:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, query: SearchQuery, options: object = None) -> MediaMetadata:
        self.calls += 1
        return MediaMetadata(number=query.number, title="Primary", actors=[], runtime=None)


class _Fallback:
    def __init__(self, result: MediaMetadata | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def fetch(self, query: SearchQuery, options: object = None) -> MediaMetadata | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_fc2_field_fallback_fills_empty_without_overwrite() -> None:
    primary = _Primary()
    fallback = _Fallback(
        MediaMetadata(number="FC2-PPV-1234567", title="Lower", actors=film_actors(["Actor"]), runtime=90)
    )
    priority = {field: ["primary", "fallback"] for field in ALL_FIELDS}
    result = await aggregate(
        SearchQuery("FC2-1234567"),
        {"primary": primary, "fallback": fallback},
        priority,
        defer_artwork=True,
        fallback_on_empty=frozenset({MetadataField.TITLE, MetadataField.ACTORS, MetadataField.RUNTIME}),
    )
    assert result.metadata.title == "Primary"
    assert [actor.name for actor in result.metadata.actors] == ["Actor"]
    assert result.metadata.runtime == 90
    assert result.field_sources[MetadataField.TITLE] == "primary"
    assert result.field_sources[MetadataField.ACTORS] == "fallback"
    assert primary.calls == fallback.calls == 1


@pytest.mark.asyncio
async def test_failed_frontier_can_revisit_source_placed_in_earlier_static_wave() -> None:
    primary = _Fallback(error=RuntimeError("primary failed"))
    middle = _Fallback(MediaMetadata(number="FC2-PPV-1234567", title="Recovered"))
    last = _Fallback(MediaMetadata(number="FC2-PPV-1234567", title="Too late"))
    priority = {field: ["primary", "middle", "last"] for field in ALL_FIELDS}
    priority[MetadataField.EXTRAFANART] = ["middle", "primary", "last"]

    result = await aggregate(
        SearchQuery("FC2-PPV-1234567"),
        {"primary": primary, "middle": middle, "last": last},
        priority,
        defer_artwork=True,
        fallback_on_empty=frozenset({MetadataField.TITLE}),
    )

    assert result.metadata.title == "Recovered"
    assert primary.calls == middle.calls == 1
    assert last.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 403, 429, 503])
async def test_low_priority_http_failure_does_not_fail_primary_metadata(status: int) -> None:
    primary = _Primary()
    failure = RequestError(
        "https://fallback.example/work/1234567",
        RequestFailure(kind=FailureKind.HTTP_STATUS, status=status, message=f"HTTP {status}"),
    )
    fallback = _Fallback(error=failure)
    priority = {field: ["primary"] for field in ALL_FIELDS}
    priority[MetadataField.ACTORS] = ["primary", "fallback"]
    result = await aggregate(
        SearchQuery("FC2-1234567"),
        {"primary": primary, "fallback": fallback},
        priority,
        defer_artwork=True,
        fallback_on_empty=frozenset({MetadataField.TITLE, MetadataField.ACTORS}),
    )
    assert result.metadata.title == "Primary"
    assert result.failed_sites == ["fallback"]
    assert fallback.calls == 1


@pytest.mark.parametrize("crawler_type", [FC2DBCrawler, FourhoiCrawler, PaipanconCrawler])
@pytest.mark.asyncio
async def test_untyped_numeric_does_not_request_new_sources(
    crawler_type: type[Crawler], http_client: HttpClient, mock_web_client: AsyncMock
) -> None:
    assert await crawler_type(http_client).fetch(SearchQuery("1234567")) is None
    mock_web_client.get_text.assert_not_called()
