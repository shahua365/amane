from unittest.mock import AsyncMock, MagicMock

import pytest

from amane.crawlers.http import HttpClient
from amane.crawlers.models import SearchQuery
from amane.crawlers.sites.fd2ppv import FD2PPVCrawler


def test_fd2ppv_clean_number_variants() -> None:
    assert FD2PPVCrawler._clean_number("FC2-3193265") == "3193265"
    assert FD2PPVCrawler._clean_number("FC2-PPV-3193265") == "3193265"
    assert FD2PPVCrawler._clean_number("FC2PPV3193265") == "3193265"
    assert FD2PPVCrawler._clean_number("FC2-invalid") == ""


def test_fd2ppv_title_from_current_page_title_shape() -> None:
    assert (
        FD2PPVCrawler._clean_title("FC2 PPV 3193265 至高ぷれみあ究極作品！ | 作品 - FD2", "3193265")
        == "至高ぷれみあ究極作品！"
    )
    assert FD2PPVCrawler._clean_title("", "3193265") is None


def test_fd2ppv_release_and_runtime_locales() -> None:
    text = "原創性 舊作重製 發佈日期 2023-02-25 片長 00:40:16 發行商 FC2"
    assert FD2PPVCrawler._parse_release(text) == "2023-02-25"
    assert FD2PPVCrawler._parse_runtime(text) == 40


@pytest.mark.asyncio
async def test_fd2ppv_fetches_detail_once() -> None:
    client = MagicMock(spec=HttpClient)
    client.for_source.return_value = client
    client.get_html = AsyncMock(
        return_value="<html><title>FC2 PPV 2386297 Test title | FD2</title><body>Release Date 2024-01-02</body></html>"
    )
    result = await FD2PPVCrawler(client).fetch(SearchQuery("FC2-2386297"))
    assert result is not None
    assert result.number == "FC2-PPV-2386297"
    client.get_html.assert_awaited_once()
