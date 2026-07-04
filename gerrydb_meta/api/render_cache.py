"""Server-side render cache: GeoPackages on local disk with LRU eviction.

Renders are immutable once produced (a view snapshots its data at `valid_at`,
and later writes only add versions valid after that instant), so a cached
GeoPackage never goes stale; the only reason to drop one is disk pressure.
"""

import os
import shutil
from pathlib import Path

from uvicorn.config import logger as log


def _cache_dir() -> Path:
    cache_dir = Path(
        os.getenv(
            "GERRYDB_RENDER_CACHE_DIR",
            str(Path.home() / ".gerrydb-server" / "render-cache"),
        )
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _max_bytes() -> int:
    return int(float(os.getenv("GERRYDB_RENDER_CACHE_MAX_GB", "20")) * 10**9)


def store(render_id_hex: str, gpkg_path: Path) -> Path:
    """Moves a rendered GeoPackage into the cache, evicting past the size cap.

    Returns the cached path (also the path to serve this response from).
    """
    cache_dir = _cache_dir()
    dest = cache_dir / f"{render_id_hex}.gpkg"
    shutil.move(str(gpkg_path), dest)
    _evict(cache_dir, keep=dest)
    return dest


def _evict(cache_dir: Path, keep: Path) -> None:
    files = [p for p in cache_dir.glob("*.gpkg") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    cap = _max_bytes()
    # Oldest mtime first; serving touches mtime, making this LRU. The file
    # just stored is exempt so a cap smaller than one render still serves.
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= cap:
            break
        if p == keep:
            continue
        try:
            size = p.stat().st_size
            p.unlink()
            total -= size
            log.info("Render cache: evicted %s.", p.name)
        except OSError:  # pragma: no cover
            log.exception("Render cache: failed to evict %s.", p.name)


def cached_file(path_str: str) -> Path | None:
    """Resolves render metadata's path to a servable local file.

    Returns None for remote (gs://) paths and for files that were evicted;
    touches the file so eviction order stays LRU.
    """
    if path_str.startswith("gs://"):
        return None
    path = Path(path_str)
    if not path.is_file():
        return None
    path.touch()
    return path
