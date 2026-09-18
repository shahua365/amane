import re
from urllib.parse import urljoin

from parsel import Selector

from ...enums import MetadataField, SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery
from ..parsing import extract_text


class PPVDataBankCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(
            name=SiteName.PPVDATABANK,
            base_url="https://ppvdatabank.com",
            provided_fields=frozenset(
                {
                    MetadataField.TITLE,
                    MetadataField.RELEASE,
                    MetadataField.RUNTIME,
                    MetadataField.STUDIO,
                    MetadataField.PUBLISHER,
                    MetadataField.POSTER_URLS,
                    MetadataField.THUMB_URLS,
                    MetadataField.EXTRAFANART,
                }
            ),
        )

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        number = self._numeric_id(query.number)
        return f"{self.base_url}/article/{number}/" if number else None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        match = re.search(r"/article/(\d+)/?", url)
        if not match:
            return None
        number = match.group(1)
        page = Selector(text=await self.client.get_html(url, headers=self.headers, cookies=self.cookies))
        title = extract_text(
            page,
            "//article//h1//text()",
            '//*[contains(concat(" ",normalize-space(@class)," ")," entry-title ")]//text()',
            '//meta[@property="og:title"]/@content',
            "//title/text()",
        )
        title = self._clean_title(title, number)
        if not title:
            return None

        release = self._labeled_value(page, "販売日")
        runtime = self._runtime(self._labeled_value(page, "再生時間"))
        seller = self._labeled_value(page, "販売者")
        official = extract_text(page, '//a[contains(@href,"contents.fc2.com/article/")]/@href')
        official = urljoin(url, official) if official else None

        samples = self._sample_images(page, url)
        main = self._main_image(page, url, samples)
        fallback = f"{self.base_url}/article/{number}/img/thumb.webp"
        covers = list(dict.fromkeys(value for value in (main, fallback) if value))
        return MediaMetadata(
            number=f"FC2-PPV-{number}",
            title=title,
            release=release,
            runtime=runtime,
            studio=seller or None,
            publisher="FC2",
            poster_urls=covers,
            thumb_urls=covers,
            extrafanart=samples,
            source_url=url,
            external_id=official or url,
        )

    @staticmethod
    def _numeric_id(number: str) -> str:
        match = re.fullmatch(r"(?:FC2[-_ ]?(?:PPV[-_ ]?)?)?(\d+)", number.strip(), re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _clean_title(title: str, number: str) -> str:
        value = title.split("|")[0].strip()
        return re.sub(rf"(?i)^\s*FC2[-_ ]?(?:PPV[-_ ]?)?0*{re.escape(number)}\s*", "", value).strip()

    @staticmethod
    def _labeled_value(page: Selector, label: str) -> str:
        nodes = page.xpath(
            f'//*[self::li or self::p or self::div or self::dt or self::dd][contains(normalize-space(.),"{label}")]'
        )
        texts = [" ".join(part.strip() for part in node.xpath(".//text()").getall() if part.strip()) for node in nodes]
        for text in sorted((value for value in texts if value), key=len):
            match = re.search(rf"{re.escape(label)}\s*[:：]?\s*(.+)", text)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _runtime(value: str) -> int | None:
        match = re.search(r"(\d{1,3}):(\d{2})(?::(\d{2}))?", value)
        if not match:
            return None
        first, second = int(match.group(1)), int(match.group(2))
        return first * 60 + second if match.group(3) is not None else first

    @staticmethod
    def _image_values(node: Selector) -> list[str]:
        return node.xpath("@data-src | @data-original | @data-lazy-src | @src").getall()

    @classmethod
    def _sample_images(cls, page: Selector, base_url: str) -> list[str]:
        images = page.xpath(
            '//img[preceding::*[self::h2 or self::h3 or self::h4][1][contains(normalize-space(.),"サンプル画像")]]'
        )
        values: list[str] = []
        for image in images:
            for src in cls._image_values(image):
                absolute = urljoin(base_url, src.strip())
                if src.strip() and not src.startswith("data:") and absolute not in values:
                    values.append(absolute)
        return values

    @classmethod
    def _main_image(cls, page: Selector, base_url: str, samples: list[str]) -> str | None:
        candidates = page.xpath(
            '//meta[@property="og:image"]/@content | //img[contains(@class,"wp-post-image")]'
            '/@data-src | //img[contains(@class,"wp-post-image")]/@src | //article//img/@data-src | //article//img/@src'
        ).getall()
        for src in candidates:
            absolute = urljoin(base_url, src.strip())
            lower = absolute.lower()
            if (
                src.strip()
                and not src.startswith("data:")
                and absolute not in samples
                and not any(marker in lower for marker in ("logo", "avatar", "banner", "ads"))
            ):
                return absolute
        return None
