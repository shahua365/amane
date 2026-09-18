import re
from urllib.parse import urljoin

from parsel import Selector

from ...enums import MetadataField, SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery

_EXCLUDED_IMAGE_MARKERS = ("moechat_ads.jpg", "mc.yandex.ru", "linglan_ad1.jpg")


class PaipanconCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(
            name=SiteName.PAIPANCON,
            base_url="https://paipancon.com",
            headers={"Referer": "https://paipancon.com/"},
            provided_fields=frozenset(
                {
                    MetadataField.POSTER_URLS,
                    MetadataField.THUMB_URLS,
                    MetadataField.TRAILER_URLS,
                    MetadataField.EXTRAFANART,
                }
            ),
        )

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        match = re.fullmatch(r"FC2-PPV-(\d+)", query.number, re.IGNORECASE)
        if not match:
            return None
        number = match.group(1).zfill(7)
        return f"{self.base_url}/fc2daily/detail/FC2-PPV-{number}"

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        match = re.search(r"FC2-PPV-(\d+)", url, re.IGNORECASE)
        if not match:
            return None
        number = match.group(1).zfill(7)
        page = Selector(text=await self.client.get_html(url, headers=self.headers, cookies=self.cookies))
        work_marker = f"fc2-ppv-{number}".lower()
        images: list[str] = []
        for src in page.xpath("//img/@data-src | //img/@data-original | //img/@src").getall():
            absolute = urljoin(url, src.strip())
            lower = absolute.lower()
            if (
                src.strip()
                and not src.startswith("data:")
                and work_marker in lower
                and not any(marker in lower for marker in _EXCLUDED_IMAGE_MARKERS)
                and absolute not in images
            ):
                images.append(absolute)

        trailers: list[str] = []
        for src in page.xpath("//video/@src | //video/source/@src").getall():
            absolute = urljoin(url, src.strip())
            if src.strip() and not src.startswith("data:") and absolute not in trailers:
                trailers.append(absolute)

        cover = f"{self.base_url}/fc2daily/data/FC2-PPV-{number}/cover.jpg"
        return MediaMetadata(
            number=f"FC2-PPV-{match.group(1)}",
            poster_urls=[cover],
            thumb_urls=[cover],
            trailer_urls=trailers,
            extrafanart=images,
            source_url=url,
            external_id=url,
        )
