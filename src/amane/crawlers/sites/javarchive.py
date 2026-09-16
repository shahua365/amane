import re
from urllib.parse import quote, urljoin, urlsplit

from parsel import Selector

from ...enums import SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery


class JavArchiveCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(name=SiteName.JAVARCHIVE, base_url="https://javarchive.com")

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        match = re.fullmatch(r"FC2-PPV-(\d+)", query.number)
        if not match:
            return None
        number = match.group(1)
        text = await self.client.get_html(
            f"{self.base_url}/search?q={quote(query.number)}", headers=self.headers, cookies=self.cookies
        )
        for href in Selector(text=text).xpath("//a/@href").getall():
            url = urljoin(self.base_url, href)
            if urlsplit(url).hostname != urlsplit(self.base_url).hostname:
                continue
            if re.search(rf"/\d+-FC2(?:-?PPV)?[-_ ]?{re.escape(number)}(?=\D|$)", href, re.IGNORECASE):
                return url
        return None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        text = await self.client.get_html(url, headers=self.headers, cookies=self.cookies)
        page = Selector(text=text)
        title = "".join(page.css(".Recipepod .name::text").getall()).strip()
        match = re.match(r"FC2(?:[-_ ]?PPV)?[-_ ]?(\d+)\s*", title, re.IGNORECASE)
        if not match or not title[match.end() :].strip():
            return None
        article = page.css(".news")
        # 仅详情正文提供的作品标签有效; 边栏及文章列表日期不参与解析.
        body = " ".join(article.xpath("./text()").getall())
        release = re.search(r"日期[：:]\s*(\d{4}/\d{1,2}/\d{1,2})", body)
        duration = re.search(r"时长[：:]\s*(\d+):(\d{2}):(\d{2})", body)
        seller = re.search(r"卖家[：:]\s*([^\r\n<]+?)(?=\s{2,}|$)", body)
        images = list(
            dict.fromkeys(
                urljoin(self.base_url, src)
                for src in article.css(".highslide-gallery img::attr(src)").getall()
                if src and not src.startswith("data:")
            )
        )
        cover = article.css('.Recipepod img[itemprop="image"]::attr(src)').get()
        if not cover:
            cover = article.css(".fisrst_sc img::attr(src)").get()
        covers = [urljoin(self.base_url, cover)] if cover else []
        return MediaMetadata(
            number=f"FC2-PPV-{match.group(1)}",
            title=title[match.end() :].strip(),
            studio=seller.group(1).strip() if seller else None,
            release=release.group(1) if release else None,
            runtime=int(duration.group(1)) * 60 + int(duration.group(2)) if duration else None,
            poster_urls=covers,
            thumb_urls=covers,
            extrafanart=images,
            source_url=url,
            external_id=url,
        )
