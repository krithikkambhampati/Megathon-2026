"""Property value uplift range from the value-model ensemble (README P2.8 step 8).

Quantiles and the minimum half-width come from `engine.yaml: value`. Indicative, not causal.
"""

from __future__ import annotations

import numpy as np

from greenhome.config import get_config
from greenhome.contracts import ValueResult


def assemble_value(
    *,
    current_value_gbp: float | None,
    rating_before: str | None,
    rating_after: str | None,
    sap_before: float | None,
    sap_after: float | None,
    log_prices: np.ndarray | None,
) -> ValueResult:
    """log_prices shape (n_ensemble, 2): column 0 = before, 1 = after. None → status "insufficient"."""
    common = {
        "rating_before": rating_before,
        "rating_after": rating_after,
        "sap_before": sap_before,
        "sap_after": sap_after,
    }
    if log_prices is None:
        return ValueResult(
            status="insufficient",
            current_value_gbp=current_value_gbp,
            current_value_source=None if current_value_gbp is None else "user",
            uplift_pct_low=None,
            uplift_pct_mid=None,
            uplift_pct_high=None,
            value_low_gbp=None,
            value_high_gbp=None,
            **common,
        )
    cfg = get_config().engine.value
    uplift = 100 * np.expm1(log_prices[:, 1] - log_prices[:, 0])
    low, mid, high = (float(q) for q in np.percentile(uplift, cfg.quantiles))
    # no false precision: at least ±min_half_width_pct around mid
    low = min(low, mid - cfg.min_half_width_pct)
    high = max(high, mid + cfg.min_half_width_pct)
    if current_value_gbp is not None:
        base, source = current_value_gbp, "user"
    else:
        base, source = float(np.exp(np.median(log_prices[:, 0]))), "model"
    return ValueResult(
        status="ok",
        current_value_gbp=base,
        current_value_source=source,
        uplift_pct_low=low,
        uplift_pct_mid=mid,
        uplift_pct_high=high,
        value_low_gbp=base * (1 + low / 100),
        value_high_gbp=base * (1 + high / 100),
        **common,
    )
