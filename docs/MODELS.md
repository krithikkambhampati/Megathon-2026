# Models (Part 3)

Submission item **C** (trained models + inference code). All numbers live in
[`reports/evaluation.md`](../reports/evaluation.md) (item **G**), generated from the saved metrics.

## Reproduce
```bash
python -m data_pipeline.run_all          # Part 1 data (docs/DATA.md)
python -m training.train_rating          # M4  ~4 min
python -m training.train_energy          # M1  ~1 min
python -m training.train_recommender     # M2  ~7 min
python -m training.train_value           # M3  ~20 min (20 members)
python -m training.model_sizes           # reports/model_sizes.csv
python -m training.evaluation_report     # reports/evaluation.md
```
CPU only (tested on 16 cores / 15 GB RAM). LightGBM 4.7, seed 42, deterministic mode.
Trained models are committed (deliverable C) as gzip-compressed LightGBM text models: each folder holds
`model.txt.gz` (or `model_XX.txt.gz`), `features.json` (ordered columns, categories, monotone constraints) and
`manifest.json` (version, metrics, data manifest timestamp). Held-out test predictions (deliverable I) are in
`outputs/test_predictions/*.csv.gz`. `python -m training.compress_artifacts` converts plain artefacts.

## Use from the engine
`config/global.yaml: models: real` makes `Engine.from_config()` call
`greenhome.ml.registry.load_models()`, which returns Part 2's `Models` container. Each adapter implements
the matching Protocol in `greenhome/ml/protocols.py`:

| Protocol | Adapter | Returns |
|---|---|---|
| `RatingModel.predict_sap(homes)` | `RealRating` | SAP 1–100 per home (Part 2 anchors to the stated band and uses deltas) |
| `EnergyModel.predict_after(homes, packages)` | `RealEnergy` | `FuelEnergy` per (home, package), anchored to `home.energy`; empty package returns the baseline |
| `RecommenderModel.predict_proba(homes)` | `RealRecommender` | `{Retrofit: P(assessor recommends)}` for all 7 |
| `ValueModel.predict_log_price(homes, ratings, as_of)` | `RealValue` | `(20, n)` ensemble log £ |

Lower-level, DataFrame-based wrappers are in `greenhome/ml/inference.py`. At load time each model's
saved column list is checked against `greenhome/ml/features.py`, so a feature mismatch fails loudly.
`GREENHOME_MODELS_DIR` overrides the model folder.

## The four models

| | M4 Rating | M1 Energy | M2 Recommender | M3 Value |
|---|---|---|---|---|
| Question | What EPC rating (SAP) does this home have / would it have after a retrofit? | Annual grid electricity and gas after a retrofit package? | Would an EPC assessor recommend retrofit *r* for this home? | Value at a rating, today; uplift range for a rating change |
| Data | 2.89M real EPC certificates | 305k simulated (home × package) outcomes, hidden household factors | 9.4M real (certificate × feasible retrofit) assessor labels | 618k real Land Registry sales with the EPC valid at sale |
| Files | 1 | 2 (per fuel) | 7 (per retrofit) | 20 (bootstrap ensemble, for the range) |
| Target | SAP points | after ÷ before, own fuel | recommended (0/1) | log price |
| Monotone | +1 insulation, glazing, controls, renewables, heating rank | gas −1 on every retrofit; elec −1 on all but heat pump | none | +1 rating |
| Baselines | median SAP by age × type | catalogue rule; mean % by type; additive singles | recommend all feasible; popularity by type | region × type £/m² (HPI-indexed) |

**Hyper-parameters** (shared: bagging 0.8, feature fraction 0.9, L2 1.0, early stopping 100 rounds on val):

| | learning rate | leaves / min leaf | max rounds |
|---|---|---|---|
| M4 | 0.08 | 63 / 200 | 4000 |
| M1 | 0.05 | 63 / 100 | 3000 |
| M2 | 0.05 | 63 / 200 | 2000 (≤1M training rows per retrofit) |
| M3 | 0.05 | 127 / 100 | 2000 per member |

## Design decisions worth knowing
- **Why ML on simulated energy labels is not circular.** The simulator uses household factors that cannot be
  observed (thermostat setpoint, occupancy, appliance use, exposure, true heat-pump efficiency, PV orientation,
  per-home retrofit effect draws). M1 sees only what the app knows, so it learns the expected outcome under
  uncertainty and has genuine held-out error.
- **Own-fuel targets.** Normalising both fuels by combined energy leaked errors across fuels (loft insulation
  "raised" electricity). Each fuel is now predicted relative to its own baseline.
- **Heat pumps in M4.** SAP is cost-based, so replacing a condensing gas boiler moves SAP little. Real repeat
  EPCs agree (median +7, a quarter negative). Heating enters M4 as an ordered efficiency rank with a +1
  constraint, so a heat pump never lowers the predicted rating.
- **Heat pumps in M2.** EPC software recommends heat pumps only from RdSAP 10 (2025). The model is trained on
  2025+ certificates only and has learned that assessors recommend heat pumps for electrically heated homes.
- **Smart controls.** EPC has almost no "smart thermostat" level, so for model features it counts as zone control.
- **Value is associational, and a retrofit acts only through the rating.** M3 sees structure, location,
  rating and market conditions only, never retrofit-changeable fields (heating system, insulation, glazing,
  controls, renewables). Seen directly, those carried confounded premiums from sales data (heat-pump homes are
  newer and pricier), which made e.g. a C->C package show +10% value. The uplift is a range from 20 bootstrap
  members and is presented as indicative, never causal. Location is region-level because that is what the app
  receives.

## Features (`greenhome/ml/features.py`)
Home: property type, region, wall type, roof type, heating system, main fuel (not in M4), age (ordinal), floor
area (+ log), bedrooms, ordinals for roof/wall insulation, glazing, controls, renewables, roof exposed, gas
connected, regional HDD factor and PV yield.
M1 adds: log baseline electricity and gas, electricity share, baseline intensity, 7 retrofit flags.
M2 adds: current rating. M3 drops retrofit-changeable fields and adds: rating, months since 2015-01,
regional UK HPI at the valuation month.
