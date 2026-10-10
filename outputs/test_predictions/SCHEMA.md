# Held-out test predictions (deliverable I)

Predictions of the four trained models on the **test split** only: properties grouped by synthetic customer,
never seen in training or tuning (`data/processed/splits.parquet`, seed 42). Files are gzip-compressed CSV
(`zcat file.csv.gz | head`, or `pandas.read_csv(path)` reads them directly). Units: kWh per year, GBP, SAP
points (1–100). Missing values are empty cells, never zero.

How each file is produced: `training/train_*.py` (`make train`). Model details and metrics:
[`docs/MODELS.md`](../../docs/MODELS.md), [`reports/evaluation.md`](../../reports/evaluation.md). Label
sources: [`docs/DATA.md`](../../docs/DATA.md).

## `rating_test.csv.gz`: M4 EPC rating (434k certificates)

| Column | Type | Meaning |
|---|---|---|
| `cert_id` | str | Hashed EPC certificate id (no real EPC keys are published) |
| `property_id` | str | Synthetic property id |
| `sap_true` | float | **Label:** SAP points on the real EPC certificate |
| `sap_pred` | float | Model prediction from the home's features |
| `band_true`, `band_pred` | A–G | EPC band of the true and predicted SAP points |
| `sap_baseline` | float | Baseline: median SAP for the same age band × property type (train split) |

## `energy_test.csv.gz`: M1 energy per fuel after a retrofit package (46k home × package rows)

| Column | Type | Meaning |
|---|---|---|
| `property_id` | str | Synthetic property id |
| `package_id` | int | Package number within the home (0, 1, …) |
| `package` | str | Retrofits in the package, `+`-separated (e.g. `air_source_heat_pump+loft_insulation`) |
| `elec_before`, `gas_before` | float | Annual grid electricity and gas before the retrofits (the home's baseline) |
| `elec_after_ref`, `gas_after_ref` | float | **Label:** simulator outcome after the package, including hidden household factors the model cannot see |
| `elec_after_pred`, `gas_after_pred` | float | Model prediction from observable features only |

The reference values are synthetic (no public post-retrofit data exists); agreement with them does not by
itself establish real-world accuracy. `reports/energy_performance_gap.csv` compares predicted savings with
NEED's observed savings.

## `recommender_test.csv.gz`: M2 retrofit relevance (1.05M certificate × retrofit rows)

Only rows where the retrofit is physically feasible for the home (rule-based feasibility) are included.

| Column | Type | Meaning |
|---|---|---|
| `cert_id`, `property_id` | str | Certificate and property ids |
| `retrofit` | str | One of the seven retrofits (`loft_insulation`, …, `smart_thermostat`) |
| `assessor_recommended` | bool | **Label:** the real EPC assessor recommended this retrofit on this certificate |
| `assessor_order` | int / empty | The assessor's order for recommended retrofits (1 = first) |
| `p` | float | Model probability that an assessor would recommend it |
| `p_popularity` | float | Baseline: recommendation rate for the same property type (train split) |
| `predicted_suitability_input` | float | `p` rounded to 4 dp, the value the engine's suitability score uses |

## `value_test.csv.gz`: M3 property value (93k real sales)

| Column | Type | Meaning |
|---|---|---|
| `property_id` | str | Synthetic property id |
| `sale_date` | date | Land Registry transfer date |
| `price_true` | float | **Label:** real sale price (HM Land Registry Price Paid) |
| `price_pred` | float | Median of the 20-model ensemble at the sale month |
| `price_p10`, `price_p90` | float | 10th and 90th percentile across the ensemble |
| `price_baseline` | float | Baseline: region × type £/m² (train sales, HPI-indexed) × floor area |
| `rating_at_sale` | A–G | Rating of the latest EPC lodged **before** the sale (no look-ahead) |

## `value_uplift_test.csv.gz`: indicative value change for a rating improvement (143k rows)

| Column | Type | Meaning |
|---|---|---|
| `property_id` | str | Synthetic property id |
| `rating_before`, `rating_after` | A–G | Current band and an improved band |
| `band_steps` | int | Number of bands improved (1 = one band) |
| `uplift_pct_low`, `uplift_pct_mid`, `uplift_pct_high` | float | 10th / 50th / 90th percentile of the % value change across the 20 models |

Uplifts are associational, from a hedonic model on past sales: indicative, not a causal effect of a retrofit.
`reports/value_repeat_sales_check.csv` compares them with real repeat sales.

## Not included

- **Green Home Score and improvement potential on the test split.** These are deterministic outputs of the
  engine, not trained models; they are reproducible with `make portfolio`, which ranks the test split by
  improvement potential (needs the processed data from `make data`).
