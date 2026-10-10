# Data: sources, schema, generation and labels (Part 1)

This document covers submission items **B** (data scripts), **I** (schema and label documentation) and the
data-quality part of **G**. Reproduce everything with:

```bash
python -m data_pipeline.download.download_public     # public files (≈2 GB)
python -m data_pipeline.download.ons_lad_region       # LA -> region lookup
python -m data_pipeline.download.epc_bulk             # EPC (needs EPC_API_TOKEN in .env, ≈8.3 GB)
python -m data_pipeline.run_all                       # ≈5 min after downloads; deterministic (seed 42)
pytest tests/unit/p1                                  # 118 tests
```

## 1. What is real and what is synthetic

| Need | Source | Real? |
|---|---|---|
| Property features, EPC band, SAP points (2.9M certificates, 1.84M properties) | EPC register, 11 local authorities, 2008–2026 | **Real** |
| Retrofit relevance labels (10.3M assessor recommendations) | EPC recommendations | **Real** |
| Retrofit history (322k events) | Feature changes between repeat EPCs of the same property | **Real** (noisy) |
| Sale prices (633k sales, 2015–2025) | HM Land Registry Price Paid, joined to EPC by address | **Real** |
| Market index | UK House Price Index (to 2026-07) | **Real** |
| Monthly metered electricity & gas per home | No public property-level source | **Synthetic**, calibrated to NEED |
| Post-retrofit energy | Does not exist publicly | **Synthetic** (simulator) |
| Customers (who owns which property) | — | **Synthetic** |

Agreement between our models and synthetic targets **does not establish real-world accuracy**. Where real
evidence exists we compare against it (NEED observed savings, repeat-EPC ΔSAP, real sale prices).

## 2. Sources and licences
All downloads are logged with URL, sha256 and access time in `data/raw/DOWNLOADS.json`.

| Dataset | Use | Licence / attribution |
|---|---|---|
| EPC domestic certificates + recommendations (MHCLG, Get energy performance of buildings data) | properties, ratings, labels | OGL v3. Addresses © Royal Mail/OS: used only for the Land Registry join, **never written to `data/processed`** |
| HM Land Registry Price Paid Data 2015–2025 | sale prices | OGL v3. "Contains HM Land Registry data © Crown copyright and database right." |
| UK House Price Index (full file, July 2026) | re-index prices; market conditions | OGL v3 |
| DESNZ NEED consumption tables 2026 (data year 2024) | calibration targets; benchmarks | OGL v3 |
| DESNZ GHG conversion factors 2026 (flat file v1.2) | emission factors | OGL v3 |
| Met Office HadUK-Grid regional monthly mean temperature | degree days | OGL v3 |
| EU JRC PVGIS v5.2 | PV yield by region | free use with attribution |
| UKPN Low Carbon London smart meters (2013) | monthly electricity shape | CC BY |
| ONS Open Geography LAD→region lookups (2015–2025) | region mapping | OGL v3 |

**Local authorities sampled** (`config/data_pipeline.yaml`): Manchester, Leeds, Newcastle, Birmingham, Nottingham,
Norwich, Bristol, Cornwall (off-gas heavy), Cardiff, Camden, Brighton & Hove, covering all 10 regions.

## 3. Pipeline (`data_pipeline/run_all.py`)
| Step | Script | Output |
|---|---|---|
| NEED tables | `ingest_need.py` | `reference/need_headline.parquet`, `need_multi.parquet` |
| Emission factors | `ingest_ghg.py` | `config/emission_factors.yaml` (looked up by DESNZ factor ID) |
| Smart-meter profile | `ingest_lcl.py` | `reference/lcl_monthly_profile.parquet` |
| Regional climate | `build_regions.py` | `config/regions.yaml` |
| HPI / PPD | `ingest_hpi.py`, `ingest_ppd.py` | tidy index; cleaned sales (interim) |
| EPC ingest | `ingest_epc.py` | streams the 98 GB national zip one file at a time, keeps target LAs |
| Parse + ids + labels | `build_properties.py` | `epc_certificates_model.parquet`, `labels/recommender_labels.parquet` |
| Sales join | `join_epc_ppd.py` | `sales_history.parquet` |
| Retrofit history | `repeat_epc.py` | `retrofit_history.parquet` |
| Product dataset | `build_dataset.py` | `properties` (pre-value), `energy_monthly`, `splits`, `sim_hidden`, energy labels, score helpers |
| Value baseline | `value_baseline.py` | `properties.parquet` |
| Demo homes | `make_examples.py` | `data/examples/*.json` |
| Imputation tables | `imputation_tables.py` | `config/generated/imputation.yaml` |
| Validation | `manifest.py` | `MANIFEST.json` + contract checks |
| Data report | `data_report.py` | `reports/data_report.md` + `reports/figures/` (validation charts) |

## 4. Schema (`data/processed/`, all parquet; enums exactly as README §7.2; `null` = unknown)

**`properties.parquet`**: 50,000 product homes (stratified sample of in-scope properties by LA × type)
`property_id, customer_id, local_authority_code, epc_lodgement_date, data_source, property_type, age_band,
floor_area_m2, habitable_rooms, bedrooms, region, roof_type, roof_insulation, wall_type, wall_insulation, glazing,
heating_system, main_fuel, renewables, smart_controls, gas_connected, listed_or_conservation, outdoor_space,
energy_rating, sap_score, current_value_gbp, current_value_source, annual_electricity_kwh, annual_gas_kwh,
missingness_pattern`
- `current_value_gbp` is the **baseline estimate at 2026-07**, not a sale price (see §6).
- `annual_*_kwh` are only filled for the `annual_only` pattern (a customer who knows annual totals, not months).
- `missingness_pattern` documents the injected gap type (§5); it is metadata, **not a model feature**.

**`energy_monthly.parquet`**: `property_id, month (YYYY-MM), electricity_kwh (grid import), gas_kwh`.
12 months ending 2026-06. **A fully missing month has no row**; a missing fuel is `null`, never 0. Gas is a
true 0 only for homes without gas.

**`epc_certificates_model.parquet`**: every valid certificate (2,887,962) for every property, for the rating
and recommender models. `cert_id` (hashed), `property_id`, `lodgement_date`, features, `energy_rating`, `sap_score`.
**Excluded on purpose:** energy consumption, CO2, cost and "potential" columns (derived from the SAP
calculation, so they would leak the label).

**`sales_history.parquet`**: `property_id, sale_date, price_gbp, ppd_property_type, new_build, tenure,
match_method, energy_rating_at_sale, sap_at_sale, cert_id_at_sale, source`. The rating/features at sale come
from the latest EPC lodged **on or before** the sale date (tested).

**`retrofit_history.parquet`**: `property_id, retrofit, completion_date ("observed by" date), sap_before,
sap_after, delta_sap, source='epc_repeat'`.

**`splits.parquet`**: `property_id, customer_id, split, in_product_sample` for **all 1,840,458 properties**.
70/15/15 by customer. **Every model must use this file.**

**`sim_hidden.parquet`**: simulator-only household factors. ⚠️ **Never a model feature.**

**`labels/`**
| File | Rows | Meaning |
|---|---|---|
| `energy_scenarios.parquet` | 305,441 | per home × retrofit package: annual elec/gas before & after (simulated with hidden factors), `r_<retrofit>` flags |
| `improvement_potential_ref.parquet` | 49,931 | % purchased-energy cut of the full feasible package + rank within split |
| `recommender_labels.parquet` | 9.6M | per certificate × retrofit: `rule_feasible`, `assessor_recommended`, `assessor_order` (rows neither feasible nor recommended dropped) |
| `true_annual_energy.parquet` | 50,000 | noiseless annual totals: evaluation of annualisation only |

**`reference/`**: aggregated public statistics (NEED, HPI, LCL profile). **`config/generated/`**:
`intensity_bounds.yaml` (i_best 85, i_worst 230 kWh/m², train P5/P95), `peer_percentiles.parquet`
(P10/P50/P75/P90 intensity by property type × floor-area band, train only) and `imputation.yaml` for
"not sure" answers: median floor area by type × bedrooms, the most common feature value (with its share) by
age × type, and typical annual energy (NEED medians by floor area for gas homes; synthetic medians for
electrically heated homes). All from train data.

## 5. How the synthetic parts were generated

**EPC text → enums** (`parse_epc_features.py`): ordered regex rules incl. Welsh-language certificates; unknown →
null, never guessed. Coverage on 2.89M certificates: glazing 99.9%, property type 99.9%, controls 99.8%,
wall insulation 99.7%, roof insulation 99.7%, roof type 98.7%, age 98.9%, fuel 98.5%, heating 94.9% (community
heating deliberately out of scope), wall type 89.9% and renewables 89.9% (new-build U-value-only and
pre-2012 certificates). See `reports/epc_parse_coverage.csv` and `reports/epc_unmatched_values.csv`.

**Condensing vs old gas boiler**: EPC open data does not record it and labels 99.6% of gas boilers "Good",
so that field is unusable. We use the assessor's recommendation 20 *"Replace boiler with new condensing
boiler"* as evidence of a non-condensing boiler: 21% of gas boilers.

**Bedrooms**: EPC records habitable rooms, not bedrooms, and no fixed rule works (a semi with 4 habitable
rooms is usually a 3-bed with a through-lounge, sometimes a 2-bed). Within each property type we rank homes by
(habitable rooms, floor area) and assign bedrooms by quantile-matching to NEED's national bedroom mix for that
type: monotone, and the mix matches NEED by construction. (`rooms - 1` had put more 4-bed than 3-bed semis.)

**Physics model** (`physics.py`): space heat = floor area × base × built-form factor × fabric index (walls 0.35,
roof 0.25, glazing 0.15, ventilation-by-age 0.25) × regional HDD factor × controls factor × hidden setpoint ×
hidden exposure (floor position / exposed walls: spread 0.30 for flats, 0.12 for houses);
hot water from bedrooms × hidden occupancy; appliances from floor area × hidden occupancy × hidden appliance use;
boilers 88%/75% efficient, heat pump at hidden SCOP (catalogue range, −0.3 for poor fabric); PV from PVGIS yield ×
system size × hidden orientation, self-consumption capped at 35% of demand (60% with battery).

**Calibration to NEED** (`calibrate.py`): multiplicative factors per property type × age group (gas) and
property type × bedrooms (electricity), fitted on **train** homes only, against NEED 2024 medians (≈16M real
homes), jointly with a per-EPC-band **prebound** factor. Real F/G homes use no more gas per m² than D/E homes
(occupants heat less; RdSAP overstates old-fabric heat loss). Uncorrected, our physics made F/G homes ~40–55%
too hungry and would have overstated their savings. The band factor fits only the *shape* of NEED's gas/m²-by-band
curve: fitted factors E 0.88, F/G 0.74 (G borrows F, too few homes). It stays with the household after a
retrofit, so savings for poor homes are conservative. Result: every cell median within **0.8%** of NEED, band
curve relative to D within 0.4% for A–F; spread (IQR) 84% of NEED's for electricity and 74% for gas (flats
47–70%), so synthetic homes are still somewhat more alike than real ones. See `reports/calibration_*.csv` and
`reports/data_report.md`.

**Monthly profiles**: gas = 75% heating (HDD, Hitchin formula on Met Office 2016–2025 temperatures) + 25% hot
water; electricity shape from 3,936 London smart-meter households (2013); PV monthly from PVGIS. ±3% monthly
measurement noise.

**Missingness** (seeded): 70% complete, 15% 1–3 random months missing, 7% 4–8 consecutive months missing, 3% gas
column missing although gas-heated, 2% annual totals only, 3% no energy data.

**Retrofit simulator** (`simulator.py`): effects act on end uses. Fabric, glazing and control savings are drawn
per home within the catalogue range for the starting state and **compound multiplicatively**; a heat pump moves
space heat + hot water to electricity at the home's SCOP *after* fabric changes (so insulating first shrinks the
electricity rise); solar only cuts grid imports; cooking gas remains after a heat pump. Up to 8 packages per home
(all singles, the full feasible package, random subsets). Tested in `tests/unit/p1/test_simulator.py`.

**Customers**: 85% own 1 property, 12% own 2, 3% own 3–5, within one region.

## 6. Property value baseline
`ppd_indexed` (29%): last real sale × HPI(LA, type, 2026-07)/HPI(LA, type, sale month).
`area_model` (71%): LA × type median indexed £/m² from **train-split** sales × floor area.
Median £277k (indexed sales) / £226k (area model).

## 7. Leakage controls
- One split file, grouped by synthetic customer, covering every property; historic certificates and sales share
  their property's split.
- Calibration, intensity bounds, peer percentiles and the £/m² value model use **train** data only.
- Hidden simulator factors are in a separate file and are checked against `properties.parquet`.
- SAP-derived EPC columns are excluded from model data.
- Ratings at sale never come from a certificate lodged after the sale (tested).

## 8. Known limitations and biases
- **City-heavy sample**: 34% flats (England & Wales ≈ 22%). The rating mix matches national NEED within ~4 points
  (C 38% vs 36%, D 37% vs 41%).
- **EPC is not a random sample of homes**: certificates are triggered by sale, letting or new build.
- **Assessor noise**: 23% of repeat-certificate pairs were discarded as inconsistent.
- **Heat pumps are never recommended** in the EPC recommendations here, so a heat-pump relevance label does not exist.
  Solar, cavity and solid wall labels are recommended in 95–97% of feasible cases (low information).
- **Synthetic energy** is calibrated on medians and the EPC-band shape, not on full joint distributions; its
  spread is ~74–84% of real data (flats narrowest).
- **Bedrooms are estimated** (EPC has habitable rooms only) by quantile-matching to NEED.
- **Fuel scope**: oil/LPG/solid fuel and community heating homes are excluded (≈9% of properties).
- **England & Wales only.** Values are associational and indicative, not causal.

## 9. Facts the other parts need
| For | Fact |
|---|---|
| P2 carbon | electricity **0.13096**, gas **0.18231** kg CO2e/kWh (DESNZ 2026); the README's ~0.2 was wrong |
| P2 score | intensity bounds 85 / 230 kWh/m² (train P5/P95); NEED shows small homes have the highest gas/m², so compare with size-banded peers |
| P2 annualisation | seasonal shares per region in `config/regions.yaml` (`gas_monthly_share`, `elec_monthly_share`) |
| P2 stubs, P3 rating | real median ΔSAP for single-change repeat EPCs: solid wall +11, heat pump +10, cavity +8, solar +8, loft +7, glazing +6, controls +4 |
| P3 recommender | heat pump has no assessor labels; feasible-rule agreement with assessors 97–100% |
| P3 value | 618k sales with rating at sale; use `cert_id_at_sale` for features at sale time |
| P2, P3 kernels | `data_pipeline/kernels_tmp.py` holds temporary copies of `apply_retrofits` / `feasible_set`; swap to Part 2's versions when they land |
| P2 imputation | `config/generated/imputation.yaml`: floor area by type × bedrooms, feature modes by age × type, typical energy |
| P2 ranking | `config/retrofit_catalogue.yaml` costs: solid wall, glazing, heat pump and controls verified from Energy Saving Trust pages (May–Sep 2026); loft, cavity and solar from secondary sources |
