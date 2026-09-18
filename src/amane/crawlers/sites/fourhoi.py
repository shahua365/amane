import re

from ...enums import MetadataField, SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery


class FourhoiCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(
            name=SiteName.FOURHOI,
            base_url="https://fourhoi.com",
            headers={"Referer": "https://fourhoi.com/"},
            provided_fields=frozenset(
                {MetadataField.POSTER_URLS, MetadataField.THUMB_URLS, MetadataField.TRAILER_URLS}
            ),
        )

    async def fetch(self, query: SearchQuery, options: FetchOptions | None = None) -> MediaMetadata | None:
        match = re.fullmatch(r"FC2-PPV-(\d+)", query.number, re.IGNORECASE)
        if not match:
            return None
        number = match.group(1).zfill(7)
        root = f"{self.base_url}/fc2-ppv-{number}"
        cover = f"{root}/cover.jpg"
        return MediaMetadata(
            number=f"FC2-PPV-{match.group(1)}",
            poster_urls=[cover],
            thumb_urls=[cover],
            trailer_urls=[f"{root}/preview.mp4"],
            source_url=root + "/",
            external_id=root + "/",
        )

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        return None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        return None
