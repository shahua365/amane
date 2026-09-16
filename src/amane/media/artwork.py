"""图片补全独立于标量聚合, 只查询当前路由允许的来源."""

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from ..crawlers.models import MediaMetadata, SearchQuery
from ..enums import MetadataField
from ..observability import current, invoke_source

if TYPE_CHECKING:
    from ..aggregate import AggregateResult, CrawlerLike
    from ..aggregate.engine import FieldPriority
    from ..net.http import WebClient
    from .resource_store import ResourceStore


class ArtworkResult(BaseModel):
    poster_urls: list[str] = Field(default_factory=list)
    thumb_urls: list[str] = Field(default_factory=list)


def _promote(urls: list[str], selected: str | None) -> list[str]:
    return list(dict.fromkeys(([selected] if selected else []) + urls))


async def rescue_artwork(
    query: SearchQuery,
    result: AggregateResult,
    crawlers: Mapping[str, CrawlerLike],
    priority: FieldPriority,
    store: ResourceStore,
    client: WebClient,
    *,
    cache: Mapping[str, dict] | None = None,
    poster: bool = True,
    thumb: bool = True,
) -> ArtworkResult:
    posters = list(dict.fromkeys(result.metadata.poster_urls))
    thumbs = list(dict.fromkeys(result.metadata.thumb_urls))
    attempted = {key.split(":", 1)[0] for key in result.sites_queried}
    fetched: dict[str, MediaMetadata | None] = {}
    failed_urls: set[str] = set()

    async def fetch_artwork(site: str) -> MediaMetadata | None:
        if site in fetched:
            return fetched[site]
        if site in attempted or site not in crawlers:
            return None
        data: MediaMetadata | None = None
        for key, raw in (cache or {}).items():
            if key.split(":", 1)[0] == site:
                try:
                    data = MediaMetadata.model_validate(raw)
                    current().note_cache_hit(site)
                except ValidationError:
                    pass
                break
        if data is None:
            q = copy.deepcopy(query)
            q.partial_result = copy.deepcopy(result.metadata)

            async def fetch() -> MediaMetadata | None:
                return await crawlers[site].fetch(q)

            data = await invoke_source(site, fetch)
        result.sites_queried.append(site)
        if data is None:
            result.failed_sites.append(site)
        # 补图结果不写入 raw 标量快照, 防止下次缓存聚合改变已确认字段.
        fetched[site] = data
        return data

    async def select(urls: list[str]) -> str | None:
        picked = await store.acquire_first_image([url for url in urls if url not in failed_urls], client)
        failed_urls.update(picked.failed or [])
        return picked.used_url

    async def resolve_field(field: MetadataField, urls: list[str]) -> list[str]:
        selected = await select(urls)
        if selected:
            return _promote(urls, selected)
        for source in priority[field]:
            data = await fetch_artwork(str(source))
            if data is None:
                continue
            values = data.poster_urls if field == MetadataField.POSTER_URLS else data.thumb_urls
            candidates = [url for url in values if url not in urls]
            urls.extend(candidates)
            if selected := await select(candidates):
                break
        return _promote(urls, selected)

    return ArtworkResult(
        poster_urls=await resolve_field(MetadataField.POSTER_URLS, posters) if poster else posters,
        thumb_urls=await resolve_field(MetadataField.THUMB_URLS, thumbs) if thumb else thumbs,
    )
