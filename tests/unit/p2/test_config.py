"""config.py: P1-generated files load, peers read P1's parquet labels, bands match P1's pd.cut edges."""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from greenhome.config import REPO_ROOT, Config, get_config


@pytest.mark.parametrize(("area", "band"), [
    (50.0, "lt50"), (50.1, "50_90"), (90.0, "50_90"), (200.0, "130_200"), (200.1, "gt200"),
])
def test_floor_area_band_upper_edge_inclusive(area, band) -> None:
    assert get_config().floor_area_band(area) == band


def test_national_block_completed_from_regions() -> None:
    cfg = get_config()
    assert cfg.national.hdd_factor == 1.0
    yields = [r.pv_yield_kwh_per_kwp for r in cfg.regions.values()]
    assert cfg.national.pv_yield_kwh_per_kwp == pytest.approx(sum(yields) / len(yields))


def test_peers_read_p1_parquet_labels(tmp_path) -> None:
    root = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", root)
    pd.DataFrame([{"property_type": "semi_detached", "floor_area_band": "50-90",
                   "p10": 1.0, "p50": 2.0, "p75": 3.0, "p90": 4.0, "n": 500}]).to_parquet(
        root / "generated" / "peer_percentiles.parquet")
    cfg = Config(root)
    assert cfg.peers("semi_detached", 85.0) == {"p10": 1.0, "p50": 2.0, "p75": 3.0, "p90": 4.0}
    assert cfg.peers("detached", 85.0) == cfg.engine.peers_fallback["50_90"]  # no row → fallback
