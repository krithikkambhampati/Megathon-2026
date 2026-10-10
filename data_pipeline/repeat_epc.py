"""Real retrofit history from repeat EPCs of the same property (README P1.5).

For consecutive certificates of one property, an element that improves maps to a retrofit:
  roof_insulation up             -> loft_insulation      (pitched loft / room in roof)
  wall none/partial -> full      -> cavity_wall_insulation or solid_wall_insulation (by wall type)
  glazing single/partial/secondary -> double/triple -> double_glazing
  heating -> heat_pump           -> air_source_heat_pump
  renewables -> solar_pv         -> solar_pv
  controls up to >= smart_thermostat -> smart_thermostat
completion_date = the later certificate's lodgement date ("observed by"; the true date is earlier).

Noise guard: assessors differ, so a pair where >= 2 elements got WORSE is treated as inconsistent
and discarded. Pairs are also discarded if floor area changed by > 15% (likely extension/re-measure).

Outputs: data/processed/retrofit_history.parquet  (property_id, retrofit, completion_date, sap_before,
         sap_after, delta_sap, source='epc_repeat')
         reports/retrofit_history_summary.csv  (counts + median delta SAP per retrofit)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

ORD = {
    "roof_insulation": {"none": 0, "low": 1, "medium": 2, "full": 3},
    "wall_insulation": {"none": 0, "partial": 1, "full": 2},
    "glazing": {"single": 0, "partial_double": 1, "secondary": 2, "double": 3, "triple": 4},
    "smart_controls": {"none": 0, "timer_only": 1, "programmer_thermostat": 2, "programmer_thermostat_trvs": 3,
                       "smart_thermostat": 4, "smart_zoned": 5},
    "renewables": {"none": 0, "solar_thermal": 1, "solar_pv": 2, "solar_pv_battery": 3},
}


def main() -> None:
    c = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet")
    c = c.sort_values(["property_id", "lodgement_date", "cert_id"])
    multi = c["property_id"].duplicated(keep=False)
    c = c[multi].reset_index(drop=True)
    prev = c.groupby("property_id").shift(1)
    pair = prev["cert_id"].notna()
    a, b = prev[pair], c[pair]
    print(f"properties with >= 2 certificates: {c.property_id.nunique():,}; consecutive pairs: {int(pair.sum()):,}")

    worse = pd.Series(0, index=b.index)
    better = {}
    for col, m in ORD.items():
        x, y = a[col].map(m), b[col].map(m)
        worse += (y < x).fillna(False).astype(int)
        better[col] = (y > x).fillna(False)
    hs_worse = (a["heating_system"].eq("heat_pump") & b["heating_system"].ne("heat_pump")).astype(int)
    worse += hs_worse
    area_ok = (b["floor_area_m2"] / a["floor_area_m2"] - 1).abs() <= 0.15
    ok = (worse < 2) & area_ok

    events = []

    def add(mask, retrofit):
        m = mask & ok
        events.append(pd.DataFrame({"property_id": b.loc[m, "property_id"], "retrofit": retrofit,
                                    "completion_date": b.loc[m, "lodgement_date"],
                                    "sap_before": a.loc[m, "sap_score"], "sap_after": b.loc[m, "sap_score"]}))

    add(better["roof_insulation"] & b["roof_type"].isin(["pitched_loft", "room_in_roof"]), "loft_insulation")
    wall_up = a["wall_insulation"].isin(["none", "partial"]) & b["wall_insulation"].eq("full")
    add(wall_up & b["wall_type"].eq("cavity"), "cavity_wall_insulation")
    add(wall_up & b["wall_type"].eq("solid"), "solid_wall_insulation")
    add(a["glazing"].isin(["single", "partial_double", "secondary"]) & b["glazing"].isin(["double", "triple"]),
        "double_glazing")
    add(a["heating_system"].ne("heat_pump") & a["heating_system"].notna() & b["heating_system"].eq("heat_pump"),
        "air_source_heat_pump")
    add(~a["renewables"].isin(["solar_pv", "solar_pv_battery"]) & b["renewables"].isin(["solar_pv", "solar_pv_battery"]),
        "solar_pv")
    add(a["smart_controls"].map(ORD["smart_controls"]).lt(4) & b["smart_controls"].map(ORD["smart_controls"]).ge(4),
        "smart_thermostat")

    h = pd.concat(events, ignore_index=True)
    h["delta_sap"] = h["sap_after"] - h["sap_before"]
    h["source"] = "epc_repeat"
    h = h.sort_values(["property_id", "completion_date", "retrofit"]).reset_index(drop=True)
    h.to_parquet(PROCESSED / "retrofit_history.parquet", index=False)
    summ = h.groupby("retrofit").agg(events=("property_id", "size"), median_delta_sap=("delta_sap", "median"),
                                     share_sap_improved=("delta_sap", lambda d: float((d > 0).mean())))
    summ["single_change_median_delta_sap"] = (
        h[~h.duplicated(["property_id", "completion_date"], keep=False)].groupby("retrofit")["delta_sap"].median())
    REPORTS.mkdir(exist_ok=True)
    summ.round(3).to_csv(REPORTS / "retrofit_history_summary.csv")
    print(f"pairs discarded as inconsistent: {int((~ok).sum()):,} of {int(pair.sum()):,}")
    print(summ.round(2).to_string())


if __name__ == "__main__":
    main()
