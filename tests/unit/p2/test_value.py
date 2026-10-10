from __future__ import annotations

import numpy as np
import pytest

from greenhome.core.value import assemble_value

BEFORE = np.log(300_000.0)


def _logs(uplift_pct: np.ndarray) -> np.ndarray:
    before = np.full(len(uplift_pct), BEFORE)
    return np.column_stack([before, before + np.log1p(uplift_pct / 100)])


def _value(log_prices, current_value_gbp=None):
    return assemble_value(
        current_value_gbp=current_value_gbp, rating_before="E", rating_after="C",
        sap_before=46.5, sap_after=70.0, log_prices=log_prices,
    )


def test_percentiles_of_member_uplifts():
    v = _value(_logs(np.linspace(0, 10, 20)))  # P10/P50/P90 of linspace(0, 10, 20) = 1, 5, 9
    assert v.status == "ok"
    assert (v.uplift_pct_low, v.uplift_pct_mid, v.uplift_pct_high) == pytest.approx((1.0, 5.0, 9.0))


def test_range_widened_when_members_agree():
    v = _value(np.column_stack([np.full(20, BEFORE), np.full(20, BEFORE + 0.02)]))
    mid = 100 * (np.exp(0.02) - 1)
    assert v.uplift_pct_mid == pytest.approx(mid)
    assert v.uplift_pct_low == pytest.approx(mid - 0.5)
    assert v.uplift_pct_high == pytest.approx(mid + 0.5)


def test_user_base_value():
    v = _value(_logs(np.linspace(0, 10, 20)), current_value_gbp=350_000.0)
    assert (v.current_value_gbp, v.current_value_source) == (350_000.0, "user")
    assert v.value_low_gbp == pytest.approx(350_000 * 1.01)
    assert v.value_high_gbp == pytest.approx(350_000 * 1.09)


def test_model_base_value_is_exp_median_before():
    v = _value(_logs(np.linspace(0, 10, 20)))
    assert v.current_value_source == "model"
    assert v.current_value_gbp == pytest.approx(300_000.0)
    assert v.value_low_gbp == pytest.approx(300_000 * 1.01)


@pytest.mark.parametrize("user,source", [(None, None), (350_000.0, "user")])
def test_insufficient_when_no_log_prices(user, source):
    v = _value(None, current_value_gbp=user)
    assert v.status == "insufficient"
    assert (v.current_value_gbp, v.current_value_source) == (user, source)
    assert v.uplift_pct_mid is None and v.value_low_gbp is None and v.value_high_gbp is None
    assert (v.rating_before, v.rating_after, v.sap_before, v.sap_after) == ("E", "C", 46.5, 70.0)


def test_returns_plain_floats():
    v = _value(_logs(np.linspace(0, 10, 20)))
    for x in (v.uplift_pct_low, v.uplift_pct_mid, v.uplift_pct_high, v.value_low_gbp, v.value_high_gbp,
              v.current_value_gbp):
        assert type(x) is float
