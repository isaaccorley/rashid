"""Exact operation counts, and a memory ceiling, over the seeded scenarios.

A performance change that claims to do less work changes a number here. The
change updates the number in the same pull request, so the claim is checked
by CI rather than by a hand-run timer. A change that makes rashid do more work
without saying so fails here.

Each run is measured after one warm-up run over the same tree. The first run
in a process also parses the bundled schemas into ``lru_cache`` registries,
and that one-time cost would make the counts depend on test order.
"""

from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

import rashid
from rashid import _trace
from tests import scenarios

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("scenarios")


def _steady_counts(name: str, size: str, cache_dir: Path) -> dict[str, int]:
    with scenarios.target(name, size, cache_dir=cache_dir) as target:
        rashid.validate(target.location, **target.options)
        with _trace.counting() as delta:
            rashid.validate(target.location, **target.options)
    return delta


def test_metadata_small_counts(cache_dir: Path) -> None:
    # 1 root + 2 collections + 100 items = 103 STAC documents.
    assert _steady_counts("metadata", "small", cache_dir) == {
        "json.parses": 103,
        "rules.checks": 1821,
        "schema.rust_compiles": 3,
        "schema.rust_passes": 103,
    }


def test_metadata_large_counts(cache_dir: Path) -> None:
    # 1 root + 20 collections + 2000 items = 2021. The schema compiles stay
    # at 3: they depend on the schemas in use, not on the object count.
    assert _steady_counts("metadata", "large", cache_dir) == {
        "json.parses": 2021,
        "rules.checks": 35003,
        "schema.rust_compiles": 3,
        "schema.rust_passes": 2021,
    }


def test_data_small_counts(cache_dir: Path) -> None:
    pytest.importorskip("pyarrow")
    pytest.importorskip("rasterio")
    counts = _steady_counts("data", "small", cache_dir)
    # 2 GeoParquet items + 2 COG items + the collection's thumbnail.
    assert counts["data.assets"] == 5
    # Each GeoParquet asset opens its footer 3 times (the GeoParquet, tabular,
    # and vector-column checks), and each COG opens 4 times plus one
    # cog_validate. A change that shares one open per asset lowers these.
    assert counts["parquet.opens"] == 2 * 3
    assert counts["raster.opens"] == 2 * 4
    assert counts["raster.cog_validates"] == 2
    root = scenarios.cached("data", "small", cache_dir=cache_dir)
    on_disk = sum(p.stat().st_size for p in root.rglob("data.*"))
    assert counts["data.bytes_read"] == on_disk
    assert "http.gets" not in counts


def test_remote_small_counts(cache_dir: Path) -> None:
    counts = _steady_counts("remote", "small", cache_dir)
    assert counts["crawl.documents"] == 103
    # The crawl also GETs the 6 AGENTS.md and README.md files it follows.
    assert counts["http.gets"] == 103 + 6
    # One HEAD per asset: 2 per collection and 1 per item. The link check
    # reads the crawl's statuses and sends no HEAD of its own.
    assert counts["live.heads"] == counts["http.heads"] == 2 * 2 + 100
    assert counts["live.known_statuses"] == 109
    assert counts["live.range_probes"] == counts["live.preflights"] == 1
    assert "http.retries" not in counts
    assert "http.urllib_fallbacks" not in counts


def test_metadata_large_traced_memory_ceiling(cache_dir: Path) -> None:
    """The metadata pass over 2021 objects stays under a fixed traced peak.

    tracemalloc sees Python allocations only. jsonschema-rs, Arrow, and GDAL
    allocate outside it, so this ceiling covers the metadata pass, which
    holds every parsed object in ``CatalogGraph.nodes``. Measured in
    October 2026 after a warm-up run: 11.3 MiB for large, 0.6 MiB for small,
    and 5.9 KiB more for each extra object. Each limit leaves about 40%
    headroom. The limit per object guards the slope, which a fixed ceiling
    hides on a small input.
    """
    peaks: dict[str, int] = {}
    for size in scenarios.SIZES:
        root = scenarios.cached("metadata", size, cache_dir=cache_dir)
        rashid.validate(root, data=False)
        tracemalloc.start()
        try:
            rashid.validate(root, data=False)
            peaks[size] = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    assert peaks["large"] < 16 * 2**20
    per_object = (peaks["large"] - peaks["small"]) / (2021 - 103)
    assert per_object < 8 * 1024


def test_timings_cover_every_stage_of_a_url_run(cache_dir: Path) -> None:
    _trace.enable("on")
    with scenarios.target("remote", "small", cache_dir=cache_dir) as target:
        rashid.validate(target.location, **target.options)
    names = [node["name"] for node in _trace.timings()]
    assert names == ["crawl", "load", "rules", "structural", "extensions", "live"]
    crawl = _trace.timings()[0]
    # The crawl's GETs ran on pool threads and still nest under the crawl.
    assert [child["name"] for child in crawl["children"]] == ["http.get"]
    assert crawl["children"][0]["calls"] == 109
