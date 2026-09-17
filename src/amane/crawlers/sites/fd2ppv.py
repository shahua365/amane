import re
from urllib.parse import urljoin

from parsel import Selector

from ...enums import SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery, film_actors
from ..parsing import extract_all_texts, extract_text


class FD2PPVCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(name=SiteName.FD2PPV, base_url="https://fd2ppv.cc")

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        if query.number.isdigit():
            return None
        number = self._clean_number(query.number)
        if not number:
            return None
        return f"{self.base_url}/articles/{number}"

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        text = await self.client.get_html(url, headers=self.headers, cookies=self.cookies)
        if not text:
            return None

        html = Selector(text=text)
        match = re.search(r"/articles/(\d+)", url)
        raw_number = match.group(1) if match else ""
        title = self._title(html, raw_number)
        if not raw_number or not title:
            return None

        actors = self._unique(
            extract_all_texts(
                html,
                '//*[contains(concat(" ", normalize-space(@class), " "), " artist-info-card ")]'
                '//a[contains(@href,"/actresses/")]//text()',
                '//main//*[contains(concat(" ", normalize-space(@class), " "), " artist-name ")]'
                '//a[contains(@href,"/actresses/")]//text()',
            )
        )
        if not actors:
            actors = self._unique(extract_all_texts(html, '//a[contains(@href,"/actresses/")]//text()'))

        studio = extract_text(
            html,
            '//*[contains(concat(" ", normalize-space(@class), " "), " work-meta-label ") '
            'and (contains(normalize-space(.),"賣家") or contains(normalize-space(.),"卖家") '
            'or contains(normalize-space(.),"販売者"))]/following-sibling::*[1]//a/text()',
            '//a[contains(@href,"/channels/")]/text()',
        )
        tags = self._unique(extract_all_texts(html, '//a[contains(@href,"/tags/articles/")]//text()'))

        page_text = " ".join(html.xpath("//body//text()").getall())
        release = self._parse_release(page_text)
        runtime = self._parse_runtime(page_text)

        images = self._image_urls(html)
        cover = images[0] if images else None

        return MediaMetadata(
            number=f"FC2-PPV-{raw_number}",
            title=title,
            actors=film_actors(actors),
            studio=studio or None,
            publisher="FC2",
            release=release,
            runtime=runtime,
            tags=tags,
            poster_urls=[cover] if cover else [],
            thumb_urls=[cover] if cover else [],
            extrafanart=images,
            source_url=url,
            external_id=url,
        )

    @staticmethod
    def _clean_number(number: str) -> str:
        cleaned = re.sub(r"(?i)^(FC2-?PPV-?|FC2-?)", "", number).strip("-_ ")
        return cleaned if cleaned.isdigit() else ""

    @staticmethod
    def _title(html: Selector, number: str) -> str | None:
        title = extract_text(
            html,
            '//*[contains(concat(" ", normalize-space(@class), " "), " work-brief ")]//text()',
            '//*[contains(concat(" ", normalize-space(@class), " "), " work-title ")]//text()',
            '//meta[@property="og:title"]/@content',
            "//title/text()",
        )
        return FD2PPVCrawler._clean_title(title, number)

    @staticmethod
    def _clean_title(title: str, number: str) -> str | None:
        if not title:
            return None
        title = title.split("|")[0].strip()
        if title.lower() in {"login", "log in", "sign in", "fd2ppv", "ログイン", "登入", "登录"}:
            return None
        if number:
            title = re.sub(rf"(?i)^\s*FC2\s*(?:PPV\s*)?0*{re.escape(number)}\s*", "", title).strip()
        return title or None

    @staticmethod
    def _parse_release(text: str) -> str | None:
        match = re.search(
            r"(?:發佈日期|发布日期|發售日|発売日|公開日|Release\s*Date)\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            text,
            re.IGNORECASE,
        )
        return match.group(1).replace("/", "-") if match else None

    @staticmethod
    def _parse_runtime(text: str) -> int | None:
        match = re.search(
            r"(?:片長|片长|収録時間|再生時間|Runtime)\s*[:：]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        first = int(match.group(1))
        second = int(match.group(2))
        return first * 60 + second if match.group(3) is not None else first

    def _image_urls(self, html: Selector) -> list[str]:
        image_base = '//*[contains(concat(" ", normalize-space(@class), " "), " carousel-slide ")]//img'
        values = html.xpath(
            f"{image_base}/@data-src | {image_base}/@data-original | {image_base}/@data-lazy-src | {image_base}/@src"
        ).getall()
        images: list[str] = []
        for value in values:
            normalized = self._normalize_image(value)
            if normalized and normalized not in images:
                images.append(normalized)
        return images

    def _normalize_image(self, value: str) -> str | None:
        src = value.strip()
        if not src or src.startswith("data:") or "pixel.gif" in src or "error_cover" in src:
            return None
        src = urljoin(self.base_url + "/", src)
        prefix = "https://contents-thumbnail2.fc2.com/w480/"
        if src.lower().startswith(prefix) and "storage" in src[len(prefix) :] and ".contents.fc2.com/" in src:
            return "https://" + src[len(prefix) :]
        return src

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result
