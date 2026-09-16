"""URL 级下载缓存. 未被 Metadata 引用的条目由 CLEANUP 回收, 不做 LRU.

派生资源用合成 locator ``derived:{sha256(src)}:{op}:{args}``.
就地超分覆盖原文件, URL 不变, meta 打 ``sr`` 标记.
"""

import asyncio
import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4
from weakref import WeakValueDictionary

import structlog
from PIL import Image
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..db.models import Resource

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine

    from ..net.http import WebClient

logger = structlog.get_logger()


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def derived_locator(src_url: str, op: str, args: str) -> str:
    # 同一 (src_url, op, args) 恒得同一 locator, 无需反推 url.
    inner = hashlib.sha256(src_url.encode()).hexdigest()
    return f"derived:{inner}:{op}:{args}"


def _guess_ext(url: str) -> str:
    path = url.split("?")[0]
    ext = Path(path).suffix.lower()
    if ext and len(ext) <= 5:
        return ext
    return ".bin"


@dataclass
class AcquireResult:
    success: bool
    path: Path | None = None
    used_url: str | None = None
    failed: list[str] | None = None


class ResourceStore:
    def __init__(self, engine: AsyncEngine, base_dir: Path):
        self._engine = engine
        self._base_dir = base_dir
        self._image_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        base_dir.mkdir(parents=True, exist_ok=True)

    def _session(self) -> AsyncSession:
        return AsyncSession(self._engine, expire_on_commit=False)

    def _compute_path(self, url: str, ext: str | None = None) -> Path:
        h = _url_hash(url)
        suffix = ext if ext is not None else _guess_ext(url)
        if suffix and not suffix.startswith("."):
            suffix = f".{suffix}"
        return self._base_dir / h[:2] / f"{h}{suffix}"

    def _relative_path(self, full_path: Path) -> str:
        # 必须用 POSIX 分隔符; 否则 Windows 反斜杠路径与 LIKE '{h[:2]}/{h}.%' 匹配不到.
        return full_path.relative_to(self._base_dir).as_posix()

    def full_path(self, resource: Resource) -> Path:
        return self._base_dir / resource.file_path

    @property
    def data_dir(self) -> Path:
        return self._base_dir.parent

    async def resolve(self, url: str) -> Path | None:
        if url.startswith("/api/resources/"):
            found = await self.get_by_url_hash(url.rsplit("/", 1)[-1])
            return found[1] if found else None
        async with self._session() as session:
            stmt = select(Resource).where(Resource.url == url)
            result = await session.exec(stmt)
            record = result.first()
            if record is None:
                return None

            full_path = self._base_dir / record.file_path
            if not full_path.exists():
                # 文件丢失则删除记录.
                logger.warning("resource file missing, invalidating record", url=url, path=str(full_path))
                await session.delete(record)
                await session.commit()
                return None

            return full_path

    @staticmethod
    def _image_mime(path: Path) -> str | None:
        try:
            if path.stat().st_size > 32 * 1024**2:
                return None
            with Image.open(path) as img:
                if img.width * img.height > 40_000_000:
                    return None
                mime = Image.MIME.get(img.format or "")
                img.verify()
            with Image.open(path) as img:
                img.load()
            return mime
        except OSError, ValueError, SyntaxError, Image.DecompressionBombError:
            return None

    async def acquire_image(self, url: str, client: WebClient) -> Path | None:
        """仅接受可完整解码的图片; 临时文件校验后原子写入 Resource."""
        async with self._image_locks.setdefault(url, asyncio.Lock()):
            cached = await self.resolve(url)
            if cached and await asyncio.to_thread(self._image_mime, cached):
                return cached
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            except ValueError:
                return None
            if not valid:
                return None
            tmp = self._base_dir / f"{uuid4().hex}.tmp"
            try:
                if not await client.download_image(url, tmp):
                    return None
                mime = await asyncio.to_thread(self._image_mime, tmp)
                if mime is None:
                    return None
                ext = mimetypes.guess_extension(mime) or ".img"
                dest = self._compute_path(url, ext)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp.replace(dest)
                async with self._session() as session:
                    result = await session.exec(select(Resource).where(Resource.url == url))
                    record = result.first() or Resource(url=url, file_path=self._relative_path(dest))
                    record.file_path = self._relative_path(dest)
                    record.mime_type = mime
                    record.size = dest.stat().st_size
                    record.content_hash = await asyncio.to_thread(self._hash_file, dest)
                    session.add(record)
                    await session.commit()
                return dest
            except OSError:
                return None
            finally:
                tmp.unlink(missing_ok=True)

    async def resolve_image(self, url: str) -> Path | None:
        cached = await self.resolve(url)
        return cached if cached and await asyncio.to_thread(self._image_mime, cached) else None

    async def acquire_first_image(self, urls: list[str], client: WebClient) -> AcquireResult:
        candidates = list(dict.fromkeys(urls))
        # 全部本地候选优先于任意远端候选, 包含派生和手工导入图片.
        for url in candidates:
            cached = await self.resolve_image(url)
            if cached:
                return AcquireResult(success=True, path=cached, used_url=url, failed=[])
        failed: list[str] = []
        for url in candidates:
            path = await self.acquire_image(url, client)
            if path:
                return AcquireResult(success=True, path=path, used_url=url, failed=failed)
            failed.append(url)
        return AcquireResult(success=False, failed=failed)

    async def import_image(self, path: Path) -> str:
        """调用方校验本地路径边界; 复制后校验, 记录只保存内容散列."""
        tmp = self._base_dir / f"{uuid4().hex}.tmp"
        try:
            await asyncio.to_thread(self._copy_local_image, path, tmp)
            mime = await asyncio.to_thread(self._image_mime, tmp)
            if mime is None:
                raise ValueError("图片无法完整解码")
            digest = await asyncio.to_thread(self._hash_file, tmp)

            async def producer(dest: Path) -> bool:
                await asyncio.to_thread(shutil.copyfile, tmp, dest)
                return True

            async with self._image_locks.setdefault(f"manual:{digest}", asyncio.Lock()):
                record = await self.acquire_derived(
                    f"manual:{digest}", "import", "", producer, ext=mimetypes.guess_extension(mime) or ".img"
                )
            if record is None:
                raise ValueError("图片缓存失败")
            return f"/api/resources/{self.url_hash(record.url)}"
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _copy_local_image(src: Path, dest: Path) -> None:
        if not src.is_file():
            raise ValueError("图片路径必须是文件")
        with src.open("rb") as stream:
            content = stream.read(32 * 1024**2 + 1)
        if len(content) > 32 * 1024**2:
            raise ValueError("图片文件超过 32 MiB")
        dest.write_bytes(content)

    async def acquire(self, url: str, client: WebClient) -> Path | None:
        # 缓存命中且文件存在则直出.
        cached = await self.resolve(url)
        if cached:
            return cached

        dest = self._compute_path(url)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # 下载.
        ok = await client.download(url, dest)
        if not ok:
            return None

        size = dest.stat().st_size if dest.exists() else None
        mime = mimetypes.guess_type(str(dest))[0]
        content_hash = self._hash_file(dest)

        # 写入记录.
        async with self._session() as session:
            record = Resource(
                url=url,
                file_path=self._relative_path(dest),
                content_hash=content_hash,
                size=size,
                mime_type=mime,
            )
            session.add(record)
            await session.commit()

        return dest

    async def get_by_url(self, url: str) -> Resource | None:
        async with self._session() as session:
            result = await session.exec(select(Resource).where(Resource.url == url))
            return result.first()

    async def list_all(self) -> list[Resource]:
        async with self._session() as session:
            result = await session.exec(select(Resource))
            return list(result.all())

    async def get_by_url_hash(self, url_hash: str) -> tuple[Resource, Path] | None:
        # 文件名即 _url_hash(url); 按前缀匹配定位, 无需在 DB 存 hash 列.
        async with self._session() as session:
            pattern = f"{url_hash[:2]}/{url_hash}.%"
            result = await session.exec(select(Resource).where(col(Resource.file_path).like(pattern)))
            record = result.first()
            if record is None:
                return None
            full_path = self._base_dir / record.file_path
            if not full_path.exists():
                return None
            return record, full_path

    @staticmethod
    def url_hash(url: str) -> str:
        return _url_hash(url)

    async def acquire_derived(
        self,
        src_url: str,
        op: str,
        args: str,
        producer: Callable[[Path], Awaitable[bool]],
        *,
        ext: str = ".jpg",
    ) -> Resource | None:
        # 同 (src_url, op, args) 命中已有记录直出. producer 失败返回 None.
        locator = derived_locator(src_url, op, args)
        existing = await self.get_by_url(locator)
        if existing is not None and (self._base_dir / existing.file_path).exists():
            return existing

        dest = self._compute_path(locator, ext=ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = await producer(dest)
        if not ok or not dest.exists():
            logger.warning("derived producer failed", src=src_url, op=op, args=args)
            return None

        size = dest.stat().st_size
        mime = mimetypes.guess_type(str(dest))[0]
        content_hash = self._hash_file(dest)
        meta = {"op": op, "src": src_url, "args": args}

        async with self._session() as session:
            if existing is not None:
                existing.file_path = self._relative_path(dest)
                existing.content_hash = content_hash
                existing.size = size
                existing.mime_type = mime
                existing.meta = meta
                session.add(existing)
                await session.commit()
                return existing
            record = Resource(
                url=locator,
                file_path=self._relative_path(dest),
                content_hash=content_hash,
                size=size,
                mime_type=mime,
                meta=meta,
            )
            session.add(record)
            await session.commit()
            return record

    async def upscale_in_place(
        self,
        resource: Resource,
        sr_args: dict,
        producer: Callable[[Path, Path], Awaitable[bool]],
    ) -> bool:
        # URL 不变. meta 已含 sr 则跳过 (定时任务去重亦依赖此).
        if resource.meta and "sr" in resource.meta:
            return False
        src = self._base_dir / resource.file_path
        if not src.exists():
            logger.warning("upscale source missing", url=resource.url, path=str(src))
            return False

        tmp = src.with_name(f"{src.stem}.sr_tmp{src.suffix}")
        try:
            ok = await producer(src, tmp)
            if not ok or not tmp.exists():
                logger.warning("upscale producer failed", url=resource.url)
                tmp.unlink(missing_ok=True)
                return False
            tmp.replace(src)
        except Exception as e:
            logger.warning("upscale in place error", url=resource.url, error=str(e))
            tmp.unlink(missing_ok=True)
            return False

        size = src.stat().st_size
        content_hash = self._hash_file(src)
        new_meta = dict(resource.meta) if resource.meta else {}
        new_meta["sr"] = sr_args

        async with self._session() as session:
            result = await session.exec(select(Resource).where(Resource.url == resource.url))
            record = result.first()
            if record is None:
                return False
            record.size = size
            record.content_hash = content_hash
            record.meta = new_meta
            session.add(record)
            await session.commit()
        return True

    async def acquire_first(self, urls: list[str], client: WebClient) -> AcquireResult:
        if not urls:
            return AcquireResult(success=False, failed=[])

        for url in urls:
            cached = await self.resolve(url)
            if cached:
                return AcquireResult(success=True, path=cached, used_url=url, failed=[])

        # 逐 URL 尝试, 成功即停.
        failed: list[str] = []
        for url in urls:
            path = await self.acquire(url, client)
            if path:
                return AcquireResult(success=True, path=path, used_url=url, failed=failed)
            failed.append(url)
            logger.debug("download source failed, trying next", url=url)

        logger.warning("all download sources exhausted", urls_tried=len(urls))
        return AcquireResult(success=False, path=None, used_url=None, failed=failed)

    async def acquire_extrafanart(
        self,
        urls_by_site: dict[str, list[str]],
        priority: list[str],
        client: WebClient,
    ) -> list[Path]:
        for site in priority:
            if site not in urls_by_site:
                continue
            results = await asyncio.gather(*[self.acquire(u, client) for u in dict.fromkeys(urls_by_site[site])])
            paths = [p for p in results if p is not None]
            if paths:
                return paths
        return []

    async def invalidate(self, url: str) -> None:
        async with self._session() as session:
            stmt = select(Resource).where(Resource.url == url)
            result = await session.exec(stmt)
            record = result.first()
            if record is None:
                return

            full_path = self._base_dir / record.file_path
            if full_path.exists():
                full_path.unlink()

            await session.delete(record)
            await session.commit()

    async def purge_unreferenced(self, live_urls: set[str], live_hashes: set[str]) -> int:
        # 存活: url 在 live_urls, 或 url_hash 在 live_hashes (内部相对 URL /api/resources/{hash}).
        removed = 0
        for resource in await self.list_all():
            if resource.url in live_urls or _url_hash(resource.url) in live_hashes:
                continue
            await self.invalidate(resource.url)
            removed += 1
        return removed

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
