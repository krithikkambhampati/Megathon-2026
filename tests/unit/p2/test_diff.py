"""diff_results (CR-2): all 10 rows in order, deltas = new − base, no maths for class/rating."""

from __future__ import annotations

from typing import get_args

import pytest
from conftest import home_input

from greenhome.contracts import DiffKey, Scenario
from greenhome.core.diff import diff_results
from greenhome.core.orchestrator import Engine


@pytest.fixture(scope="module")
def pair():
    engine = Engine.from_config()
    base = engine.analyse(home_input())
    loft_only = Scenario(name="loft", mode="custom", retrofits=["loft_insulation"])
    new = engine.run_scenario(home_input(), loft_only)
    return base, new


def test_rows_cover_every_key_in_order(pair) -> None:
    assert [r.key for r in diff_results(*pair).rows] == list(get_args(DiffKey))


def test_numeric_delta_is_new_minus_base(pair) -> None:
    base, new = pair
    rows = {r.key: r for r in diff_results(base, new).rows}
    assert rows["net_kwh"].delta == new.savings.saving.net_kwh - base.savings.saving.net_kwh
    assert rows["score"].delta == new.score.score - base.score.score
    assert rows["score_class"].delta is None and rows["rating_after"].delta is None


def test_retrofits_added_and_removed(pair) -> None:
    base, new = pair
    d = diff_results(base, new)
    assert d.retrofits_added == []
    assert "loft_insulation" not in d.retrofits_removed
    assert set(d.retrofits_removed) == set(base.savings.retrofits) - {"loft_insulation"}
    assert (d.base_analysis_id, d.new_analysis_id) == (base.analysis_id, new.analysis_id)


def test_missing_side_gives_no_delta() -> None:
    engine = Engine.from_config()
    base = engine.analyse(home_input())
    new = engine.analyse(home_input(heating_system=None, energy={}))  # savings insufficient
    rows = {r.key: r for r in diff_results(base, new).rows}
    assert rows["net_kwh"].new is None and rows["net_kwh"].delta is None
