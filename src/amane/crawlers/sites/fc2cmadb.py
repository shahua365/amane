import html as html_lib
import json
import re
from typing import Any
from urllib.parse import urljoin

from parsel import Selector

from ...enums import SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery, film_actors
from ..parsing import extract_all_texts, extract_text


class FC2CMADBCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(name=SiteName.FC2CMADB, base_url="https://fc2cmadb.com")

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        if query.number.isdigit():
            return None
        number = self._clean_number(query.number)
        if not number:
            return None
        url = f"{self.base_url}/articles/{number}"
        text = await self.client.get_html(url, headers=self.headers, cookies=self.cookies)
        if not text:
            return None
        page = Selector(text=text)
        payload = self._inertia_page(page)
        if self._inertia_status(payload) == 404:
            return None
        return url if self._title(page, self._article(payload), number) else None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        text = await self.client.get_html(url, headers=self.headers, cookies=self.cookies)
        if not text:
            return None

        page = Selector(text=text)
        payload = self._inertia_page(page)
        if self._inertia_status(payload) == 404:
            return None
        article = self._article(payload)
        match = re.search(r"/articles/(\d+)", url)
        number = match.group(1) if match else ""
        title = self._title(page, article, number)
        if not number or not title:
            return None

        actors = self._names(article, "actresses", "actors")
        if not actors:
            actors = self._unique(extract_all_texts(page, '//a[contains(@href,"/actresses/")]//text()'))

        writer = self._first_name(article, "writer", "seller", "author") or extract_text(
            page, '//a[contains(@href,"/writers/")]//text()'
        )
        tags = self._names(article, "tags", "genres")
        if not tags:
            tags = self._unique(extract_all_texts(page, '//a[contains(@href,"/tags/")]//text()'))

        release = self._first_string(article, "release_date", "released_at", "published_at", "date")
        if not release:
            release = self._labeled_text(page, "販売日", "発売日", "公開日")
        runtime = self._runtime(self._first_value(article, "runtime", "duration", "length"))
        if runtime is None:
            runtime = self._runtime(self._labeled_text(page, "収録時間", "再生時間"))

        cover = self._first_string(article, "cover_url", "image_url", "cover", "image", "thumbnail")
        if not cover:
            cover = extract_text(
                page,
                '//main//img[contains(@class,"object-cover")]/@src',
                '//meta[@property="og:image"]/@content',
            )
        cover = self._absolute_url(cover)

        return MediaMetadata(
            number=f"FC2-PPV-{number}",
            title=title,
            actors=film_actors(actors),
            studio=writer or None,
            publisher="FC2",
            release=release,
            runtime=runtime,
            tags=tags,
            poster_urls=[cover] if cover else [],
            thumb_urls=[cover] if cover else [],
            source_url=url,
            external_id=url,
        )

    @staticmethod
    def _clean_number(number: str) -> str:
        cleaned = re.sub(r"(?i)^FC2[-_]?(?:PPV[-_]?)?", "", number).strip("-_ ")
        return cleaned if cleaned.isdigit() else ""

    @staticmethod
    def _inertia_page(page: Selector) -> dict[str, Any]:
        raw = page.xpath('//script[@data-page="app"]/text()').get()
        if raw:
            parsed = FC2CMADBCrawler._decode_json(raw)
            if parsed:
                return parsed
        for value in page.xpath('//*[@data-page and @data-page!="app"]/@data-page').getall():
            parsed = FC2CMADBCrawler._decode_json(html_lib.unescape(value))
            if parsed:
                return parsed
        return {}

    @staticmethod
    def _decode_json(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _inertia_status(payload: dict[str, Any]) -> int | None:
        props = payload.get("props")
        if not isinstance(props, dict):
            return None
        try:
            return int(props["status"])
        except KeyError, TypeError, ValueError:
            return None

    @staticmethod
    def _article(payload: dict[str, Any]) -> dict[str, Any]:
        props = payload.get("props")
        if not isinstance(props, dict):
            return {}
        for key in ("article", "video", "work"):
            value = props.get(key)
            if isinstance(value, dict):
                data = value.get("data")
                return data if isinstance(data, dict) else value
        return {}

    @staticmethod
    def _first_value(article: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = article.get(key)
            if value is not None and value != "":
                return value
        return None

    @classmethod
    def _first_string(cls, article: dict[str, Any], *keys: str) -> str:
        value = cls._first_value(article, *keys)
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, int | float):
            return str(value)
        return ""

    @classmethod
    def _first_name(cls, article: dict[str, Any], *keys: str) -> str:
        value = cls._first_value(article, *keys)
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("name", "title", "label"):
                name = value.get(key)
                if isinstance(name, str) and name.strip():
                    return name.strip()
        return ""

    @classmethod
    def _names(cls, article: dict[str, Any], *keys: str) -> list[str]:
        value = cls._first_value(article, *keys)
        values = value if isinstance(value, list) else [value]
        names: list[str] = []
        for item in values:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                name = cls._first_name(item, "name", "title", "label")
            else:
                name = ""
            if name and name not in names:
                names.append(name)
        return names

    @classmethod
    def _title(cls, page: Selector, article: dict[str, Any], number: str) -> str:
        title = cls._first_string(article, "title", "name") or extract_text(
            page,
            "//main//h1//text()",
            "//main//h2//text()",
            '//meta[@property="og:title"]/@content',
            "//title/text()",
        )
        title = title.split("|")[0].strip()
        if title.lower() in {"login", "log in", "sign in", "fc2cmadb", "ログイン", "登入", "登录"}:
            return ""
        if number:
            title = re.sub(rf"(?i)^\s*FC2\s*(?:PPV\s*)?[-_ ]?0*{re.escape(number)}\s*", "", title).strip()
        return title

    @staticmethod
    def _labeled_text(page: Selector, *labels: str) -> str:
        for label in labels:
            value = extract_text(
                page,
                f'//*[self::dt or self::th or self::div or self::span][normalize-space(.)="{label}"]/'
                "following-sibling::*[1]//text()",
                f'//*[self::dt or self::th][contains(normalize-space(.),"{label}")]/following-sibling::*[1]//text()',
            )
            if value:
                return value
        return ""

    @staticmethod
    def _runtime(value: Any) -> int | None:
        if isinstance(value, int | float):
            return int(value)
        if not isinstance(value, str):
            return None
        clock = re.search(r"(\d{1,3}):(\d{2})(?::(\d{2}))?", value)
        if clock:
            if clock.group(3) is not None:
                return int(clock.group(1)) * 60 + int(clock.group(2))
            return int(clock.group(1))
        minutes = re.search(r"(\d+)\s*(?:分|minutes?|mins?)", value, re.IGNORECASE)
        return int(minutes.group(1)) if minutes else None

    def _absolute_url(self, value: str) -> str | None:
        if not value or value.startswith("data:"):
            return None
        return urljoin(self.base_url + "/", value)

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result
