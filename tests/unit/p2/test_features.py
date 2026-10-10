from __future__ import annotations

import math

import pandas as pd
import pytest
from conftest import home_input, make_clean

from greenhome.config import get_config
from greenhome.contracts import Retrofit
from greenhome.core.features import FEATURE_COLUMNS, build_model_features

HIDDEN_FACTORS = (
    "setpoint_factor", "occupancy_factor", "true_scop", "pv_orientation_factor", "self_consumption_frac",
)


def test_columns_are_fixed_and_ordered():
    df = build_model_features([make_clean(), make_clean(home_input(region="london"))])
    assert list(df.columns) == FEATURE_COLUMNS
    assert len(df) == 2
    assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))


def test_dtypes_stable_between_batches():
    a = build_model_features([make_clean()])
    other = home_input(property_type="flat", region=None, heating_system=None)
    b = build_model_features([make_clean(other), make_clean(gas_kwh=None)])
    empty = build_model_features([])
    assert a.dtypes.equals(b.dtypes) and a.dtypes.equals(empty.dtypes)
    for c in a.columns:
        if isinstance(a[c].dtype, pd.CategoricalDtype):
            assert list(a[c].cat.categories) == list(b[c].cat.categories)
    assert list(a["property_type"].cat.categories)[0] == "detached"


def test_values_for_p10001():
    row = build_model_features([make_clean()]).iloc[0]
    cfg = get_config()
    assert row["property_type"] == "semi_detached"
    assert row["energy_rating"] == cfg.quality_order("energy_rating").index("E")
    assert row["log_floor_area"] == pytest.approx(math.log(85))
    assert row["insulation_sub_score"] == pytest.approx(26)
    assert row["hdd_factor"] == cfg.regions["east_midlands"].hdd_factor
    assert row["baseline_purchased_kwh"] == 16800
    assert row["elec_share"] == pytest.approx(4800 / 16800)
    assert (row["listed_or_conservation"], row["outdoor_space"]) == (0.0, 1.0)


def test_missing_becomes_nan_not_zero():
    home = home_input(
        region=None, bedrooms=None, glazing=None, heating_system=None, outdoor_space=None, floor_area_m2=None
    )
    row = build_model_features([make_clean(home, gas_kwh=None)]).iloc[0]
    for c in ("bedrooms", "glazing", "outdoor_space", "floor_area_m2", "log_floor_area", "baseline_gas_kwh",
              "baseline_purchased_kwh", "intensity_kwh_m2", "elec_share"):
        assert math.isnan(row[c]), c
    assert pd.isna(row["heating_system"])
    assert row["hdd_factor"] == get_config().national.hdd_factor
    zero = build_model_features([make_clean(electricity_kwh=0.0, gas_kwh=0.0)]).iloc[0]
    assert math.isnan(zero["elec_share"])


def test_retrofit_flags_from_packages():
    df = build_model_features(
        [make_clean(), make_clean()], [frozenset({"loft_insulation", Retrofit.solar_pv}), frozenset()]
    )
    flags = [f"r_{r.value}" for r in Retrofit]
    assert flags == [c for c in FEATURE_COLUMNS if c.startswith("r_")]
    assert df.loc[0, flags].tolist() == [1, 0, 0, 0, 0, 1, 0]
    assert df.loc[1, flags].sum() == 0
    assert (build_model_features([make_clean()])[flags] == 0).all(axis=None)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        build_model_features([make_clean()], [frozenset(), frozenset()])


def test_no_hidden_factors_or_model_outputs():
    for name in (*HIDDEN_FACTORS, "sap_estimate"):
        assert name not in FEATURE_COLUMNS
