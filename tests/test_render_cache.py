"""Tests for the server-side render cache (store, LRU eviction, lookup)."""

from gerrydb_meta.api import render_cache


def _make_gpkg(tmp_path, name, size, mtime):
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_store_moves_into_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GERRYDB_RENDER_CACHE_DIR", str(tmp_path / "cache"))
    src = tmp_path / "render.gpkg"
    src.write_bytes(b"data")

    dest = render_cache.store("abc123", src)

    assert dest == tmp_path / "cache" / "abc123.gpkg"
    assert dest.read_bytes() == b"data"
    assert not src.exists()


def test_evict_lru_over_cap(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("GERRYDB_RENDER_CACHE_DIR", str(cache))
    # Cap of 14 bytes; three 6-byte files total 18, so exactly the oldest
    # must be evicted to get back under the cap.
    monkeypatch.setenv("GERRYDB_RENDER_CACHE_MAX_GB", str(14 / 10**9))
    _make_gpkg(cache, "oldest.gpkg", 6, 1_000)
    _make_gpkg(cache, "newer.gpkg", 6, 2_000)

    src = tmp_path / "incoming.gpkg"
    src.write_bytes(b"y" * 6)
    dest = render_cache.store("incoming", src)

    # Oldest evicted; the newer file and the just-stored file survive.
    assert not (cache / "oldest.gpkg").exists()
    assert (cache / "newer.gpkg").exists()
    assert dest.exists()


def test_store_exempts_new_file_from_eviction(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("GERRYDB_RENDER_CACHE_DIR", str(cache))
    # Cap smaller than the new file itself: everything else goes, but the
    # just-stored render survives so the response can still be served.
    monkeypatch.setenv("GERRYDB_RENDER_CACHE_MAX_GB", str(4 / 10**9))
    _make_gpkg(cache, "existing.gpkg", 6, 1_000)

    src = tmp_path / "big.gpkg"
    src.write_bytes(b"z" * 8)
    dest = render_cache.store("big", src)

    assert not (cache / "existing.gpkg").exists()
    assert dest.exists()


def test_cached_file_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("GERRYDB_RENDER_CACHE_DIR", str(tmp_path))
    assert render_cache.cached_file("gs://bucket/blob.gpkg.gz") is None
    assert render_cache.cached_file(str(tmp_path / "missing.gpkg")) is None

    present = tmp_path / "present.gpkg"
    present.write_bytes(b"data")
    assert render_cache.cached_file(str(present)) == present
