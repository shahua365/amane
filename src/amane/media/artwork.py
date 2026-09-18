"""图片补全独立于标量聚合, 只查询当前路由允许且能提供目标字段的来源."""

import copy
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from ..crawlers.models import MediaMetadata, SearchQuery
from ..enums import MetadataField
from ..observability import current, invoke_source

if TYPE_CHECKING:
    from pathlib import Path

    from ..aggregate import AggregateResult, CrawlerLike
    from ..aggregate.engine import FieldPriority, SourceFields
    from ..net.http import WebClient
    from .resource_store import ResourceStore


class ArtworkResult(BaseModel):
    poster_urls: list[str] = Field(default_factory=list)
    thumb_urls: list[str] = Field(default_factory=list)
    trailer_urls: list[str] = Field(default_factory=list)
    extrafanart_urls: dict[str, list[str]] = Field(default_factory=dict)


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _promote(urls: list[str], selected: str | None) -> list[str]:
    return _dedupe(([selected] if selected else []) + urls)


async def rescue_artwork(
    query: SearchQuery,
    result: AggregateResult,
    crawlers: Mapping[str, CrawlerLike],
    priority: FieldPriority,
    store: ResourceStore,
    client: WebClient,
    *,
    cache: Mapping[str, dict] | None = None,
    source_fields: SourceFields | None = None,
    poster: bool = True,
    thumb: bool = True,
    extrafanart: bool = True,
) -> ArtworkResult:
    posters = _dedupe(result.metadata.poster_urls)
    thumbs = _dedupe(result.metadata.thumb_urls)
    trailers = _dedupe(result.metadata.trailer_urls)
    extras = {site: _dedupe(urls) for site, urls in result.metadata.extrafanart_urls.items() if urls}
    attempted = {key.split(":", 1)[0] for key in result.sites_queried}
    fetched: dict[str, MediaMetadata | None] = {}
    failed_urls: set[str] = set()

    def supports(site: str, field: MetadataField) -> bool:
        return source_fields is None or site not in source_fields or field in source_fields[site]

    def merge_provenance(site: str, data: MediaMetadata) -> None:
        result.raw[site] = data.model_dump()
        if data.external_id and site not in result.metadata.external_ids:
            result.metadata.external_ids[site] = data.external_id
        if data.source_url and site not in result.metadata.source_urls:
            result.metadata.source_urls[site] = data.source_url
        for url in data.trailer_urls:
            if url and url not in trailers:
                trailers.append(url)

    def raw_for(site: str, snapshots: Mapping[str, dict]) -> dict | None:
        for key, raw in snapshots.items():
            if key.split(":", 1)[0] == site:
                return raw
        return None

    async def fetch_artwork(site: str) -> MediaMetadata | None:
        if site in fetched:
            return fetched[site]

        data: MediaMetadata | None = None
        raw = raw_for(site, result.raw)
        if raw is not None:
            try:
                data = MediaMetadata.model_validate(raw)
            except ValidationError:
                data = None
        if data is None and site in attempted:
            fetched[site] = None
            return None
        if data is None and (cached := raw_for(site, cache or {})) is not None:
            try:
                data = MediaMetadata.model_validate(cached)
                current().note_cache_hit(site)
            except ValidationError:
                data = None
        if data is None:
            if site not in crawlers:
                fetched[site] = None
                return None
            q = copy.deepcopy(query)
            q.partial_result = copy.deepcopy(result.metadata)
            q.raw_results = {}
            for key, value in result.raw.items():
                try:
                    q.raw_results[key] = MediaMetadata.model_validate(value)
                except ValidationError:
                    continue

            async def fetch() -> MediaMetadata | None:
                return await crawlers[site].fetch(q)

            data = await invoke_source(site, fetch)
            if site not in result.sites_queried:
                result.sites_queried.append(site)
            if data is None and site not in result.failed_sites:
                result.failed_sites.append(site)
        if data is not None:
            merge_provenance(site, data)
        fetched[site] = data
        return data

    def owner_for(url: str, field: MetadataField) -> str | None:
        raw_field = "extrafanart" if field == MetadataField.EXTRAFANART else str(field)
        for key, raw in result.raw.items():
            values = raw.get(raw_field)
            if isinstance(values, list) and url in values:
                return key.split(":", 1)[0]
        return None

    async def select(urls: list[str], field: MetadataField, *, source_id: str | None = None) -> str | None:
        candidates = [url for url in _dedupe(urls) if url not in failed_urls]
        for url in candidates:
            if await store.resolve_image(url):
                return url
        for url in candidates:
            owner = source_id or owner_for(url, field)
            path = await store.acquire_image(url, client, source_id=owner)
            if path is not None:
                return url
            failed_urls.add(url)
        return None

    async def resolve_field(field: MetadataField, urls: list[str]) -> list[str]:
        selected = await select(urls, field)
        if selected:
            return _promote(urls, selected)
        for source in priority[field]:
            site = str(source)
            if not supports(site, field):
                continue
            data = await fetch_artwork(site)
            if data is None:
                continue
            values = data.poster_urls if field == MetadataField.POSTER_URLS else data.thumb_urls
            candidates = [url for url in values if url not in urls]
            urls.extend(candidates)
            if selected := await select(candidates, field, source_id=site):
                break
        return _promote(urls, selected)

    async def resolve_extrafanart() -> dict[str, list[str]]:
        for source in priority[MetadataField.EXTRAFANART]:
            site = str(source)
            keys = [key for key in extras if key.split(":", 1)[0] == site]
            if not keys and supports(site, MetadataField.EXTRAFANART):
                data = await fetch_artwork(site)
                if data is not None and data.extrafanart:
                    extras[site] = _dedupe(data.extrafanart)
                    keys = [site]
            for key in keys:
                candidates = [url for url in extras[key] if url not in failed_urls]
                paths: list[Path] = await store.acquire_extrafanart({key: candidates}, [key], client)
                if paths:
                    return extras
                failed_urls.update(candidates)
        return extras

    resolved_posters = await resolve_field(MetadataField.POSTER_URLS, posters) if poster else posters
    resolved_thumbs = await resolve_field(MetadataField.THUMB_URLS, thumbs) if thumb else thumbs
    resolved_extras = await resolve_extrafanart() if extrafanart else extras
    return ArtworkResult(
        poster_urls=resolved_posters,
        thumb_urls=resolved_thumbs,
        trailer_urls=trailers,
        extrafanart_urls=resolved_extras,
    )
