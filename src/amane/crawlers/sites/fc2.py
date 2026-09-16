import re

from parsel import Selector

from ...enums import SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery
from ..parsing import extract_all_texts, extract_text


class FC2Crawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(name=SiteName.FC2, base_url="https://adult.contents.fc2.com")

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        if query.number.isdigit():
            return None
        number = query.number
        clean_number = self._clean_number(number)
        if not clean_number:
            return None
        return f"{self.base_url}/article/{clean_number}/"

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        text = await self.client.get_html(url, headers=self.headers, cookies=self.cookies)
        if not text:
            return None

        html = Selector(text=text)

        number_match = re.search(r"/article/(\d+)", url)
        raw_number = number_match.group(1) if number_match else ""
        number = f"FC2-PPV-{raw_number}"

        title_parts = html.xpath('//div[@data-section="userInfo"]//h3//text()').getall()
        title = "".join(t.strip() for t in title_parts).strip() if title_parts else None

        if not title:
            return None

        sample_images = html.xpath('//ul[@class="items_article_SampleImagesArea"]/li/a/@href').getall()
        sample_images = [self._ensure_https(u) for u in sample_images]
        cover = sample_images[0] if sample_images else None
        extrafanart = sample_images

        poster_raw = extract_text(html, '//div[@class="items_article_MainitemThumb"]/span/img/@src')
        poster_url = self._ensure_https(poster_raw) if poster_raw else None

        release_raw = extract_text(html, '//div[@class="items_article_Releasedate"]/p/text()')
        if not release_raw:
            release_raw = extract_text(
                html, '//div[@class="items_article_softDevice"]/p[contains(.,"Sale Day")]/text()'
            )
        release = self._parse_release(release_raw)

        studio = extract_text(html, '//div[@class="items_article_headerInfo"]/ul/li[last()]/a/text()')

        tags = extract_all_texts(html, '//a[@class="tag tagTag"]/text()')

        plot = extract_text(html, '//meta[@name="description"]/@content')
        runtime_text = extract_text(html, '//p[@class="items_article_info"]/text()')
        runtime_match = re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", runtime_text.strip())
        runtime = None
        if runtime_match:
            runtime = int(runtime_match.group(1))
            if runtime_match.group(3) is not None:
                runtime = runtime * 60 + int(runtime_match.group(2))

        return MediaMetadata(
            number=number,
            title=title,
            studio=studio or None,
            release=release,
            runtime=runtime,
            tags=tags,
            plot=plot or None,
            poster_urls=[poster_url] if poster_url else [],
            thumb_urls=[cover] if cover else [],
            extrafanart=extrafanart,
            source_url=url,
            external_id=url,
        )

    @staticmethod
    def _clean_number(number: str) -> str:
        cleaned = re.sub(r"(?i)^(FC2-?PPV-?|FC2-?)", "", number)
        cleaned = cleaned.strip("-").strip()
        return cleaned if cleaned.isdigit() else ""

    @staticmethod
    def _ensure_https(url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        return url

    @staticmethod
    def _parse_release(text: str) -> str | None:
        if not text:
            return None
        match = re.search(r"(\d{4}/\d{1,2}/\d{1,2})", text)
        if match:
            return match.group(1).replace("/", "-")
        return None
