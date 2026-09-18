import re
from urllib.parse import urljoin

from parsel import Selector

from ...enums import MetadataField, SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery, film_actors
from ..parsing import extract_all_texts, extract_text


class FC2DBCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(
            name=SiteName.FC2DB,
            base_url="https://fc2db.net",
            provided_fields=frozenset(
                {
                    MetadataField.TITLE,
                    MetadataField.ACTORS,
                    MetadataField.POSTER_URLS,
                    MetadataField.THUMB_URLS,
                }
            ),
        )

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        match = re.fullmatch(r"FC2-PPV-(\d+)", query.number, re.IGNORECASE)
        return f"{self.base_url}/work/{match.group(1)}/" if match else None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        match = re.search(r"/work/(\d+)/?", url)
        if not match:
            return None
        number = match.group(1)
        page = Selector(text=await self.client.get_html(url, headers=self.headers, cookies=self.cookies))
        title = extract_text(
            page,
            "//h2[contains(concat(' ',normalize-space(@class),' '),' text-xl ') and "
            "contains(concat(' ',normalize-space(@class),' '),' font-extrabold ')]//text()",
            "//main//h1//text()",
            "//main//h2//text()",
            '//meta[@property="og:title"]/@content',
            "//title/text()",
        )
        title = re.sub(rf"(?i)^\s*FC2[-_ ]?(?:PPV[-_ ]?)?0*{re.escape(number)}\s*", "", title).strip()
        if not title:
            return None
        actors = list(dict.fromkeys(extract_all_texts(page, '//a[contains(@href,"/actress/")]//text()')))
        poster = extract_text(
            page,
            '//img[contains(concat(" ",normalize-space(@class)," ")," wp-post-image ")]/@src',
            '//meta[@property="og:image"]/@content',
            "//main//article//img[1]/@src",
        )
        covers = [urljoin(url, poster)] if poster and not poster.startswith("data:") else []
        official = extract_text(
            page,
            '//div[contains(concat(" ",normalize-space(@class)," ")," grid ")]/div[1]'
            '//a[contains(@href,"fc2.com/article/")]/@href',
            '//a[contains(@href,"contents.fc2.com/article/")]/@href',
        )
        return MediaMetadata(
            number=f"FC2-PPV-{number}",
            title=title,
            actors=film_actors(actors),
            poster_urls=covers,
            thumb_urls=covers,
            source_url=url,
            external_id=urljoin(url, official) if official else url,
        )
