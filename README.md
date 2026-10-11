# Green Home Score & Retrofit Engine

Megathon X: Singularity · Problem Statement 2 (Lloyds) · Team 37

## Requirements

- Linux, macOS, or Windows with WSL2; about 2 GB of free disk
- [uv](https://docs.astral.sh/uv/) ≥ 0.4 (it installs Python 3.11 for you)
- Optional: a free [Groq](https://console.groq.com/keys) API key, for AI-written explanations

## Setup

```bash
pip install --user uv          # or the installer at https://docs.astral.sh/uv/
                               # make calls uv, so ~/.local/bin must be on PATH (open a new terminal)
git clone <this repository> && cd <repository folder>
make setup                     # Python 3.11 + every pinned package from uv.lock into .venv
cp .env.example .env           # then edit .env (see "Language model" below)
```

## Run

```bash
make api
```

Open **http://localhost:8000**, create an account (email + password), open an example home and click
**See the report**. API documentation is at http://localhost:8000/docs.

The trained models and example homes are included, so no data download is needed to run the app.

`make ui` starts an optional older dashboard (Streamlit) on http://localhost:8501; run `make api` first.

### Language model (optional)

Without a key the app still works: explanations and chat use template answers. To turn the hosted model on,
set these in `.env`:

```
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=<your Groq key>
```

Restart `make api`; its log should say `llm: on`. Offline alternative with a local model (Ollama): see
`docs/LLM.md` §10.

## Test

```bash
make test        # unit + integration tests
make lint        # ruff
```

## Rebuild the data and models (optional)

Only needed to reproduce the data pipeline and training; the app runs without it.

```bash
make data-raw    # public downloads (EPC certificates are a manual download, see below)
make data        # processed data, generated config, example homes (~5 min after downloads)
make train       # rating, energy, recommender and value models (~30 min)
make portfolio   # lender ranking of the held-out test split (or: make portfolio-examples)
make eval        # evaluation reports in reports/
```

EPC certificates must be downloaded by hand: see `data_pipeline/download/README.md`. Every download is logged
with URL, checksum and time in `data/raw/DOWNLOADS.json`.

| Dataset (external) | Link |
|---|---|
| EPC domestic certificates + recommendations | https://get-energy-performance-data.communities.gov.uk/ |
| HM Land Registry Price Paid Data | https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads |
| UK House Price Index | https://www.gov.uk/government/statistical-data-sets/uk-house-price-index-data-downloads-july-2026 |
| DESNZ NEED consumption tables | https://www.gov.uk/government/collections/national-energy-efficiency-data-need-framework |
| DESNZ greenhouse gas conversion factors 2026 | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting |
| Met Office regional monthly temperatures | https://www.metoffice.gov.uk/research/climate/maps-and-data/uk-and-regional-series |
| EU JRC PVGIS v5.2 | https://re.jrc.ec.europa.eu/pvg_tools/en/ |
| UKPN Low Carbon London smart meter data | https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households |
| ONS local authority to region lookups | https://geoportal.statistics.gov.uk/ |

## Documentation

`docs/RUN.md` (full run guide and troubleshooting), `docs/ARCHITECTURE.md`, `docs/SCORING.md`,
`docs/DATA.md`, `docs/MODELS.md`, `docs/LLM.md`, `docs/RESPONSIBLE_AI.md`, `reports/`.

## Credits

**Data** (see `docs/DATA.md` for use and limitations): EPC data (MHCLG, Open Government Licence v3; address
data © Royal Mail/OS, used only for joining and never stored in processed data). Contains HM Land Registry
data © Crown copyright and database right (OGL v3). UK HPI, DESNZ NEED and conversion factors, Met Office
HadUK-Grid series and ONS Open Geography lookups (all OGL v3). EU JRC PVGIS (free use with attribution).
UKPN Low Carbon London smart meter data (CC BY).

**Language models:** `openai/gpt-oss-120b` and `openai/gpt-oss-20b` (Apache-2.0), served by the Groq API.
Optional offline: Qwen2.5-7B-Instruct (Apache-2.0) via Ollama.

**Libraries:** LightGBM, scikit-learn, statsmodels, pandas, NumPy, PyArrow, Polars, pydantic, FastAPI,
Uvicorn, httpx, Jinja2, PyYAML, RapidFuzz, openpyxl, Streamlit, Plotly, joblib, requests, tabulate, the
`openai` and `ollama` Python clients (versions pinned in `pyproject.toml` / `uv.lock`); pytest, Hypothesis and
Ruff for testing. Web app: React 18 (MIT) and htm (Apache-2.0), vendored in `web/vendor/`; Geist and Geist
Mono fonts (SIL Open Font License 1.1), in `web/fonts/`.

AI coding assistants were used during development.

## License

MIT: see [LICENSE](LICENSE).
