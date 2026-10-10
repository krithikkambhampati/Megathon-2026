"""Contract checks on the processed data files (skipped if `make data` has not run)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from data_pipeline.manifest import ENUMS, HIDDEN, check_enums

ROOT = Path(__file__).resolve().parents[3]
PROCESSED = ROOT / "data" / "processed"
EXAMPLES = ROOT / "data" / "examples"
pytestmark = pytest.mark.skipif(
    not (PROCESSED / "properties.parquet").exists(), reason="run the data pipeline first"
)


@pytest.fixture(scope="module")
def props():
    return pd.read_parquet(PROCESSED / "properties.parquet")


def test_properties_contract(props):
    check_enums("properties", props)
    for col in [
        "property_id",
        "customer_id",
        "property_type",
        "age_band",
        "floor_area_m2",
        "region",
        "energy_rating",
        "current_value_gbp",
        "current_value_source",
    ]:
        assert col in props.columns
    assert not HIDDEN & set(props.columns)
    assert props["property_id"].is_unique


def test_no_addresses_anywhere():
    for f in PROCESSED.rglob("*.parquet"):
        cols = {c.upper() for c in pd.read_parquet(f).columns}
        assert not cols & {
            "ADDRESS",
            "ADDRESS1",
            "ADDRESS2",
            "ADDRESS3",
            "POSTCODE",
            "UPRN",
            "PAON",
            "SAON",
        }, f


def test_splits_leak_free_and_cover_product():
    s = pd.read_parquet(PROCESSED / "splits.parquet")
    assert s.groupby("customer_id")["split"].nunique().max() == 1
    props = pd.read_parquet(PROCESSED / "properties.parquet", columns=["property_id"])
    assert props["property_id"].isin(s["property_id"]).all()


def test_missing_months_are_absent_not_zero():
    m = pd.read_parquet(PROCESSED / "energy_monthly.parquet")
    assert not (m["electricity_kwh"].isna() & m["gas_kwh"].isna()).any()


def test_sales_rating_never_from_the_future():
    s = pd.read_parquet(PROCESSED / "sales_history.parquet")
    c = pd.read_parquet(PROCESSED / "epc_certificates_model.parquet", columns=["cert_id", "lodgement_date"])
    j = s.dropna(subset=["cert_id_at_sale"]).merge(c, left_on="cert_id_at_sale", right_on="cert_id")
    assert (pd.to_datetime(j["lodgement_date"]) <= pd.to_datetime(j["sale_date"])).all()


def test_examples_are_valid_home_inputs():
    idx = json.loads((EXAMPLES / "index.json").read_text())
    assert any(e["property_id"] == "P10001" for e in idx)
    for f in EXAMPLES.glob("P*.json"):
        h = json.loads(f.read_text())
        for col, allowed in ENUMS.items():
            if col in h and h[col] is not None:
                assert h[col] in allowed, (f.name, col, h[col])
        for m in h["energy"]["monthly"] or []:
            assert m["electricity_kwh"] is None or m["electricity_kwh"] >= 0
