"""EPC assessor recommendations -> our retrofit enum (README P3.3 labels) + old-boiler signal.

EPC recommendations use a fixed IMPROVEMENT_ID vocabulary (RdSAP improvement codes). We map by ID,
which is exact, and fall back to summary-text regex only for heat pumps (newer RdSAP versions) and
unknown ids. Measures outside our 7-retrofit catalogue (floor insulation, lighting, solar water
heating, cylinder insulation, draught proofing, storage heaters, ...) are ignored; this is documented.

Old-boiler signal: EPC open data does not record whether a gas boiler is condensing, and the
MAINHEAT_ENERGY_EFF label is "Good" for ~99.6% of gas boilers, so it cannot be used. An assessor
recommending improvement 20 ("Replace boiler with new condensing boiler") is direct evidence that
the existing gas boiler is non-condensing, so we use it to set heating_system = gas_boiler_old.
"""
from __future__ import annotations

import pandas as pd

ID_TO_RETROFIT = {
    "5": "loft_insulation",              # Increase loft insulation to 270 mm
    "46": "loft_insulation",             # Room-in-roof insulation
    "6": "cavity_wall_insulation",       # Cavity wall insulation
    "7": "solid_wall_insulation",        # 50 mm internal or external wall insulation
    "8": "double_glazing",               # Replace single glazed windows with low-E double glazing
    "56": "double_glazing",              # Replacement glazing units
    "11": "smart_thermostat", "12": "smart_thermostat", "13": "smart_thermostat",
    "14": "smart_thermostat", "15": "smart_thermostat", "17": "smart_thermostat",
    "18": "smart_thermostat",            # Upgrade heating controls (variants)
    "16": "smart_thermostat",            # Time and temperature zone control
    "34": "solar_pv",                    # Solar photovoltaic panels
}
OLD_BOILER_IDS = {"20"}                  # Replace boiler with new condensing boiler
TEXT_FALLBACK = [
    (r"air source heat pump|ground source heat pump|heat pump", "air_source_heat_pump"),
    (r"solar photovoltaic|\bpv\b", "solar_pv"),
    (r"cavity wall", "cavity_wall_insulation"),
    (r"internal or external wall insulation|solid wall", "solid_wall_insulation"),
    (r"loft insulation|room-in-roof", "loft_insulation"),
    (r"double glaz", "double_glazing"),
    (r"heating controls|zone control|thermostat", "smart_thermostat"),
]


def map_retrofit(rec: pd.DataFrame) -> pd.Series:
    rid = rec["IMPROVEMENT_ID"].astype("string").str.strip()
    out = rid.map(ID_TO_RETROFIT)
    text = rec["IMPROVEMENT_SUMMARY_TEXT"].astype("string").str.lower().fillna("")
    for pat, val in TEXT_FALLBACK:
        hit = out.isna() & text.str.contains(pat, regex=True)
        # heat pumps always come from text; other text matches only for ids we have not mapped
        if val != "air_source_heat_pump":
            hit &= ~rid.isin(ID_TO_RETROFIT.keys())
        out[hit] = val
    return out


def build_labels(rec: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return (long labels: CERT_ID, retrofit, assessor_order, indicative_cost), old-boiler cert ids."""
    rec = rec.copy()
    rec["retrofit"] = map_retrofit(rec)
    rec["order"] = pd.to_numeric(rec["IMPROVEMENT_ITEM"], errors="coerce")
    old_boiler = rec.loc[rec["IMPROVEMENT_ID"].astype("string").isin(OLD_BOILER_IDS), "CERT_ID"].drop_duplicates()
    lab = (rec.dropna(subset=["retrofit"]).sort_values("order")
              .groupby(["CERT_ID", "retrofit"], as_index=False)
              .agg(assessor_order=("order", "min"), indicative_cost=("INDICATIVE_COST", "first")))
    return lab, old_boiler
