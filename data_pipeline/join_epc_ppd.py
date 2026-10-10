"""Join Land Registry sales to EPC properties by address (README P1.6) -> real sales history.

Matching, within the same postcode only:
  1. exact key: (postcode, PAON, SAON) where EPC PAON/SAON are extracted from ADDRESS1/2/3
  2. fuzzy fallback: rapidfuzz token_set_ratio >= 92 on the full normalised address string,
     accepted only if the best candidate is unique and >= 3 points ahead of the runner-up
A PPD address may map to at most one property and vice versa (ambiguous ones are dropped).

energy_rating_at_sale = rating of the latest EPC lodged ON OR BEFORE the sale date (else null).
This is the leakage guard for the value model: never use a later certificate for an earlier sale.

Outputs
  data/processed/sales_history.parquet   property_id, sale_date, price_gbp, energy_rating_at_sale,
                                         sap_at_sale, cert_id_at_sale (features valid at sale, join to
                                         epc_certificates_model), ppd_property_type, new_build, tenure, source
  reports/ppd_match_report.csv
Addresses never leave this script.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

SAON_RE = re.compile(r"\b(FLAT|APARTMENT|APT|UNIT|MAISONETTE)\s+([0-9]+[A-Z]?)\b")
PAON_RE = re.compile(r"^\s*([0-9]+[A-Z]?(?:\s*-\s*[0-9]+[A-Z]?)?)\b")


def norm(s: pd.Series) -> pd.Series:
    return (s.fillna("").str.upper().str.replace(r"[^A-Z0-9 ]", " ", regex=True)
            .str.replace(r"\s+", " ", regex=True).str.strip())


def epc_address_keys(e: pd.DataFrame) -> pd.DataFrame:
    a1, a2, a3 = norm(e["ADDRESS1"]), norm(e["ADDRESS2"]), norm(e["ADDRESS3"])
    full = (a1 + " " + a2 + " " + a3).str.strip()
    saon = full.str.extract(SAON_RE)[1].fillna("")
    # PAON: leading number of the first line that isn't the flat designation
    line = np.where(a1.str.match(SAON_RE.pattern) & a2.ne(""), a2, a1)
    line = pd.Series(line, index=e.index).str.replace(SAON_RE, "", regex=True).str.strip()
    paon = line.str.extract(PAON_RE)[0].fillna("").str.replace(" ", "")
    # named buildings ("ROSE COTTAGE") have no number: use the first line itself
    paon = paon.where(paon.ne(""), line)
    return pd.DataFrame({"property_id": e["property_id"], "postcode": e["POSTCODE"].str.upper()
                         .str.replace(r"\s+", " ", regex=True).str.strip(),
                         "paon": paon, "saon": saon, "full": full})


def main() -> None:
    certs = pd.read_parquet(INTERIM / "epc_certs_parsed.parquet",
                            columns=["property_id", "cert_id", "POSTCODE", "ADDRESS1", "ADDRESS2", "ADDRESS3",
                                     "lodgement_date", "energy_rating", "sap_score"])
    addr = epc_address_keys(certs.drop_duplicates("property_id", keep="last")).reset_index(drop=True)
    postcodes = addr["postcode"].unique().tolist()

    ppd = (pl.scan_parquet(INTERIM / "ppd_clean.parquet")
             .filter(pl.col("postcode").is_in(postcodes)).collect().to_pandas())
    ppd["paon"] = ppd["paon_norm"].str.replace(" ", "")
    ppd["saon"] = ppd["saon_norm"].str.extract(r"([0-9]+[A-Z]?)\s*$")[0].fillna(ppd["saon_norm"])
    ppd["full"] = (ppd["saon_norm"] + " " + ppd["paon_norm"] + " " + ppd["street_norm"]).str.strip()
    ppd["addr_id"] = ppd.groupby(["postcode", "paon_norm", "saon_norm"], sort=False).ngroup()

    # 1. exact
    exact = ppd[["addr_id", "postcode", "paon", "saon"]].drop_duplicates("addr_id").merge(
        addr[["property_id", "postcode", "paon", "saon"]], on=["postcode", "paon", "saon"])
    exact = exact[~exact["addr_id"].duplicated(keep=False) & ~exact["property_id"].duplicated(keep=False)]
    matched = exact[["addr_id", "property_id"]].assign(method="exact")

    # 2. fuzzy within postcode for what's left
    left_ppd = ppd.drop_duplicates("addr_id")
    left_ppd = left_ppd[~left_ppd["addr_id"].isin(matched["addr_id"])]
    left_epc = addr[~addr["property_id"].isin(matched["property_id"])]
    by_pc = left_epc.groupby("postcode")
    fuzzy = []
    for pc, grp in left_ppd.groupby("postcode"):
        if pc not in by_pc.groups:
            continue
        cand = by_pc.get_group(pc)
        choices = cand["full"].tolist()
        for _, r in grp.iterrows():
            res = process.extract(r["full"], choices, scorer=fuzz.token_set_ratio, limit=2)
            if not res or res[0][1] < 92:
                continue
            if len(res) > 1 and res[0][1] - res[1][1] < 3:
                continue
            fuzzy.append((r["addr_id"], cand.iloc[res[0][2]]["property_id"]))
    fz = pd.DataFrame(fuzzy, columns=["addr_id", "property_id"])
    fz = fz[~fz["addr_id"].duplicated(keep=False) & ~fz["property_id"].duplicated(keep=False)]
    matched = pd.concat([matched, fz.assign(method="fuzzy")])
    matched = matched[~matched["property_id"].duplicated(keep=False)]

    sales = ppd.merge(matched, on="addr_id")[["property_id", "date_of_transfer", "price_gbp",
                                              "ppd_property_type", "new_build", "tenure", "method"]]
    sales = sales.rename(columns={"date_of_transfer": "sale_date", "method": "match_method"})
    sales["sale_date"] = pd.to_datetime(sales["sale_date"]).astype("datetime64[ns]")

    # rating at sale: latest EPC lodged on/before the sale date
    c = certs[["property_id", "cert_id", "lodgement_date", "energy_rating", "sap_score"]].copy()
    c["lodgement_date"] = pd.to_datetime(c["lodgement_date"]).astype("datetime64[ns]")
    c = c.sort_values("lodgement_date")
    sales = sales.sort_values("sale_date")
    sales = pd.merge_asof(sales, c, left_on="sale_date", right_on="lodgement_date", by="property_id",
                          direction="backward")
    sales = sales.rename(columns={"energy_rating": "energy_rating_at_sale", "sap_score": "sap_at_sale",
                                  "cert_id": "cert_id_at_sale",
                                  "lodgement_date": "epc_date_used"})
    sales["source"] = "ppd_matched"
    sales = sales.sort_values(["property_id", "sale_date"]).reset_index(drop=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    sales.drop(columns=["epc_date_used"]).to_parquet(PROCESSED / "sales_history.parquet", index=False)

    n_props = addr["property_id"].nunique()
    rep = pd.Series({
        "epc_properties": n_props,
        "ppd_addresses_in_epc_postcodes": int(ppd["addr_id"].nunique()),
        "matched_exact": int((matched["method"] == "exact").sum()),
        "matched_fuzzy": int((matched["method"] == "fuzzy").sum()),
        "property_match_rate": round(matched["property_id"].nunique() / n_props, 4),
        "sales_rows": len(sales),
        "sales_with_rating_at_sale": int(sales["energy_rating_at_sale"].notna().sum()),
    })
    REPORTS.mkdir(exist_ok=True)
    rep.to_csv(REPORTS / "ppd_match_report.csv")
    print(rep.to_string())


if __name__ == "__main__":
    main()
