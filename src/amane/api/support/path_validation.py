"""``safe_dirs is None`` (``AMANE_SAFE_DIRS=ALLOW_ALL``) 跳过边界层;
空列表表示未配置可用根, 无法校验.
"""

from pathlib import Path

from fastapi import HTTPException, status

from ...utils.path import is_any_descendant
from ...utils.threads import in_thread


def _resolve_under_safe_dirs(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    """``safe_dirs is None`` 表示无限制; 空列表表示未配置可用根, 无法校验."""
    if not raw_path or not raw_path.strip():
        raise ValueError("Path cannot be empty.")

    p = Path(raw_path.strip())
    try:
        resolved = p.expanduser().resolve()
    except OSError as e:
        raise ValueError(f"Path resolution failed: {e}") from e

    # 安全边界; None 表示不限制
    if safe_dirs is not None:
        if not safe_dirs:
            raise ValueError("No safe directories configured; cannot validate path.")
        if not is_any_descendant(resolved, *safe_dirs):
            raise ValueError(f"Path '{raw_path}' is outside the configured safe directories.")

    if not resolved.exists():
        raise ValueError(f"Path does not exist: {raw_path}")

    return resolved


@in_thread
def check_directory_path(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    """失败抛 ``ValueError``."""
    resolved = _resolve_under_safe_dirs(raw_path, safe_dirs)
    if not resolved.is_dir():
        raise ValueError(f"Not a directory: {raw_path}")
    return resolved


@in_thread
def check_plugin_install_path(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    resolved = _resolve_under_safe_dirs(raw_path, safe_dirs)
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.suffix.casefold() == ".zip":
        return resolved
    raise ValueError("只接受插件目录或 zip 文件")


def _http_from_path_error(exc: ValueError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("No safe directories"):
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
    if "outside the configured safe directories" in msg:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
    if msg.startswith("Path does not exist"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


async def validate_directory_path(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    try:
        return await check_directory_path(raw_path, safe_dirs)
    except ValueError as exc:
        raise _http_from_path_error(exc) from exc


@in_thread
def check_image_path(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    resolved = _resolve_under_safe_dirs(raw_path, safe_dirs)
    if not resolved.is_file():
        raise ValueError("图片路径必须是文件")
    return resolved


async def validate_image_path(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    try:
        return await check_image_path(raw_path, safe_dirs)
    except ValueError as exc:
        raise _http_from_path_error(exc) from exc


async def validate_plugin_install_path(raw_path: str, safe_dirs: list[Path] | None) -> Path:
    try:
        return await check_plugin_install_path(raw_path, safe_dirs)
    except ValueError as exc:
        raise _http_from_path_error(exc) from exc
