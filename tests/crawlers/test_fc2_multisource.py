from unittest.mock import AsyncMock

import pytest

from amane.aggregate import aggregate, compile_priority
from amane.config import HotSettings
from amane.crawlers import registry
from amane.crawlers.base import Crawler
from amane.crawlers.http import HttpClient
from amane.crawlers.models import MediaMetadata, SearchQuery
from amane.crawlers.sites.fc2 import FC2Crawler
from amane.crawlers.sites.fc2cmadb import FC2CMADBCrawler
from amane.crawlers.sites.fd2ppv import FD2PPVCrawler
from amane.crawlers.sites.javarchive import JavArchiveCrawler
from amane.enums import MetadataField
from amane.net.errors import SourceError
from amane.parsing import ContentType, infer_content_type


@pytest.mark.parametrize("number", ["FC2-PPV-4972410", "FC2PPV-4972410", "FC2-4972410", "4972410"])
def test_query_canonical_fc2(number: str) -> None:
    assert SearchQuery(number, content_type=ContentType.FC2).number == "FC2-PPV-4972410"
    assert infer_content_type("4972410") != ContentType.FC2


@pytest.mark.parametrize("crawler_type", [FC2Crawler, FC2CMADBCrawler, FD2PPVCrawler, JavArchiveCrawler])
@pytest.mark.asyncio
async def test_untyped_numeric_does_not_request(
    crawler_type: type[Crawler], http_client: HttpClient, mock_web_client: AsyncMock
) -> None:
    assert await crawler_type(http_client).fetch(SearchQuery("4972410")) is None
    mock_web_client.get_text.assert_not_called()


@pytest.mark.parametrize("base_url", ["", "https://fc2ppvdb.com", "https://www.fc2ppvdb.com/articles/1"])
def test_legacy_config_cannot_request_old_host(base_url: str) -> None:
    hot = HotSettings.model_validate(
        {
            "scraping": {
                "site_config": {"fc2ppvdb": {"base_url": base_url, "cookie": {"placeholder": "test"}}},
                "content_routes": {"fc2": ["fc2ppvdb", "fc2cmadb"]},
                "field_priority": {"title": ["fc2ppvdb"]},
                "field_blacklist": {"tags": ["fc2ppvdb"]},
            }
        }
    )
    assert hot.scraping.content_routes[ContentType.FC2] == ["fc2cmadb"]
    assert hot.scraping.site_config["fc2cmadb"].base_url in ("", "https://fc2cmadb.com")
    assert hot.scraping.site_config["fc2cmadb"].cookie == {}
    assert hot.scraping.field_priority[MetadataField.TITLE] == ["fc2cmadb"]
    assert hot.scraping.field_blacklist[MetadataField.TAGS] == ["fc2cmadb"]
    assert registry.get("fc2ppvdb") is None


@pytest.mark.asyncio
async def test_javarchive_fixture_flow(http_client: HttpClient, mock_web_client: AsyncMock) -> None:
    mock_web_client.get_text.side_effect = [
        '<a href="/12-FC2-PPV-49745560-other.html">wrong</a><a href="/13-FC2-PPV-4974556-test.html">match</a>',
        '<div class="news"><div class="Recipepod"><span class="name">FC2-PPV-4974556 Sample title</span>'
        '<img itemprop="image" src="https://images.example/cover.jpg"></div>'
        "日期：2026/09/11 <br>时长：01:54:32 <br>卖家：Sample studio  <br>"
        '<ul class="highslide-gallery"><li><img src="https://images.example/sample.jpg"></li></ul></div>',
    ]
    result = await JavArchiveCrawler(http_client).fetch(SearchQuery("FC2-4974556"))
    assert result is not None
    assert result.title == "Sample title"
    assert result.release == "2026-09-11"
    assert result.runtime == 114
    assert result.studio == "Sample studio"
    assert result.poster_urls == ["https://images.example/cover.jpg"]
    assert result.extrafanart == ["https://images.example/sample.jpg"]
    assert result.actors == []


@pytest.mark.parametrize(
    "html", ["", "<html>unrelated</html>", '<div class="Recipepod"><span class="name">Other work</span></div>']
)
@pytest.mark.asyncio
async def test_javarchive_invalid_page(html: str, http_client: HttpClient, mock_web_client: AsyncMock) -> None:
    mock_web_client.get_text.return_value = html
    if not html:
        with pytest.raises(SourceError):
            await JavArchiveCrawler(http_client)._scrape("https://javarchive.com/test")
        return
    assert await JavArchiveCrawler(http_client)._scrape("https://javarchive.com/test") is None


@pytest.mark.asyncio
async def test_fc2_priority_fallback_and_tag_union() -> None:
    first, second, failed = AsyncMock(), AsyncMock(), AsyncMock()
    first.fetch.return_value = MediaMetadata(
        number="FC2-PPV-1234567", title="Official", tags=["tag A"], studio="Official studio"
    )
    second.fetch.return_value = MediaMetadata(
        number="FC2-PPV-1234567", title="Fallback", tags=["tag A", "tag B"], studio="Other", runtime=90
    )
    failed.fetch.side_effect = TimeoutError("fixture timeout")
    result = await aggregate(
        SearchQuery("FC2-1234567"),
        {"fc2": first, "javarchive": second, "fd2ppv": failed},
        compile_priority(["fc2", "javarchive", "fd2ppv"], {}),
        {},
    )
    assert result.metadata.title == "Official"
    assert result.metadata.studio == "Official studio"
    assert result.metadata.runtime == 90
    assert result.metadata.tags == ["tag A", "tag B"]
    assert "fd2ppv" in result.failed_sites
