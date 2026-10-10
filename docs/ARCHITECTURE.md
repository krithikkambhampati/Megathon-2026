# Architecture

Green Home Score & Retrofit Engine (Megathon X, Problem Statement 2, Lloyds). This page describes the system
as built. A static image of the main diagram is in [`architecture.png`](architecture.png).

**Core rule:** every number comes from a documented model or formula. The language model only explains
numbers the engine has already computed, and a deterministic checker verifies every number it writes.

## 1. Components

```mermaid
flowchart LR
  subgraph P1["Part 1 · Data foundation (data_pipeline/)"]
    RAW[("Public data<br/>EPC · Land Registry · UK HPI<br/>NEED · DESNZ · Met Office · PVGIS")] --> ING[ingest + parse<br/>text → enums]
    ING --> SYN[calibrated synthetic<br/>monthly energy]
    SYN --> SIM[retrofit simulator<br/>hidden household factors]
    SIM --> PROC[("data/processed/*.parquet<br/>labels · splits")]
    ING --> CFG[("config/*.yaml<br/>catalogue · emission factors · regions<br/>config/generated/ imputation · bounds")]
  end
  subgraph P3["Part 3 · Models (training/, greenhome/ml/)"]
    PROC --> TRAIN[LightGBM training<br/>M4 rating · M1 energy<br/>M2 recommender · M3 value]
    FEAT[[greenhome.ml.features<br/>one feature builder]] --> TRAIN
    TRAIN --> ART[("models/*<br/>model.txt · features.json · manifest")]
    ART --> REG[registry.load_models]
    FEAT --> REG
  end
  subgraph P2["Part 2 · Core engine (greenhome/)"]
    CON[[contracts.py<br/>pydantic models v1.1.0]]
    VAL[validate + annualise<br/>imputation, flags] --> SCO[Green Home Score]
    VAL --> ISS[issues · poor flag]
    VAL --> FEA[feasibility rules]
    FEA --> ORC[Engine<br/>analyse · run_scenario · portfolio]
    SCO --> ORC
    ISS --> ORC
    REG --> ORC
    CFG --> VAL
    ORC --> CAR[carbon] & VAL2[value range] & DIF[diff_results]
    FMT[[format.py<br/>the only number formatter]]
  end
  subgraph P4["Part 4 · LLM layer (greenhome/llm/)"]
    FACTS[fact sheet] --> LLM[gpt-oss-120b on Groq<br/>OpenAI-compatible API<br/>Ollama optional offline]
    LLM --> CHK{number checker}
    CHK -- fails twice --> TPL[template answer]
    RT[router + what-if parser<br/>rules first, LLM JSON fallback]
  end
  subgraph P5["Part 5 · Product (api/, web/, ui/)"]
    API[FastAPI<br/>/v1/*] --> UI[React web app<br/>served at /, login]
    API --> ST[Streamlit dashboard<br/>secondary, no login]
    CACHE[(result cache<br/>LRU 512)]
    AUTH[(SQLite<br/>accounts + sessions)]
    API --> AUTH
  end
  ORC --> API
  API --> CACHE
  API --> FACTS
  RT --> ORC
  CHK -- verified --> API
  TPL --> API
  FMT -.-> FACTS
  FMT -.-> UI
```

| Layer | Owner | Code | What it does |
|---|---|---|---|
| Data | P1 | `data_pipeline/` | Downloads public data, parses EPC text into enums, joins Land Registry sales, generates calibrated monthly energy and simulator labels, writes splits and configs |
| Models | P3 | `training/`, `greenhome/ml/` | Trains four LightGBM models; `greenhome.ml.features` is the single feature builder for training and inference; `registry.load_models()` serves them |
| Engine | P2 | `greenhome/` | Contracts, validation and annualisation, score, issues, feasibility, ordering, savings, carbon, value range, scenarios, diffs; `format.py` is the only formatter |
| LLM | P4 | `greenhome/llm/`, `evaluation/` | Fact sheets, prompts, number checker, templates, router, what-if parser, chat, memory proposals, benchmark and evaluation |
| Product | P5 | `api/`, `web/`, `ui/`, `greenhome/labels.py` | HTTP API, accounts, the React web app (main UI), the Streamlit dashboard (secondary), shared plain-English labels, packaging |

## 2. Request flow: "analyse my home"

```mermaid
sequenceDiagram
  actor U as User
  participant UI as Web app
  participant API as FastAPI
  participant E as Engine (P2)
  participant M as Models (P3)
  U->>UI: answers questions ("Not sure" → null)
  UI->>API: POST /v1/analyse {home}
  API->>E: analyse(home, ctx)
  E->>E: validate, annualise monthly energy, impute unknowns, flag conflicts
  E->>E: score + range, issues, feasibility
  E->>M: batched predictions (rating, energy per fuel, recommender, value ensemble)
  M-->>E: SAP, kWh after, probabilities, log prices
  E->>E: suitability + order, incremental savings, carbon, value range, score after
  E-->>API: AnalysisResult (contract 1.1.0)
  API->>API: cache by analysis_id, NaN → null
  API-->>UI: JSON
  UI->>U: screens (numbers formatted by format.py only)
```

## 3. What-if and explanation flow

```mermaid
sequenceDiagram
  actor U as User
  participant API as FastAPI
  participant C as chat / explainer (P4)
  participant E as Engine (P2)
  participant L as LLM (Groq)
  U->>API: POST /v1/chat "what if I only install solar?"
  API->>E: base = analyse(home)
  API->>C: chat(req, engine, llm, ctx, base)
  C->>C: router + parser (rules first) → Scenario
  C->>E: run_scenario(home, scenario)  — models rerun, infeasible items rejected with a reason
  E-->>C: scenario result
  C->>C: diff_results(base, scenario) → fact sheet of formatted numbers
  C->>L: explain using FACTS only (25 s budget for the whole answer)
  L-->>C: draft
  C->>C: number checker (numbers, money claims, promises, increase-as-saving)
  alt fails
    C->>L: retry once with the problems listed
    C->>C: still failing or out of time → template answer from the same facts
  end
  C-->>API: ChatResponse {answer, scenario, result, diff, check}
  API-->>U: answer + "checked" / "standard summary" badge
```

The LLM never sees a question without the recomputed results attached, and the app works with the LLM off:
explanations and chat then use the template answers.

## 4. HTTP API

| Method & path | Purpose |
|---|---|
| `POST /v1/auth/signup`, `/login`, `/logout`, `GET /v1/auth/me` | Accounts and login sessions (httpOnly cookie, SQLite) |
| `GET /v1/health` | Status, contract version, model mode (stub / real / fixture) and versions, live LLM check |
| `GET /v1/labels` | Plain-English labels for every enum, issue, reason and flag |
| `GET /v1/catalogue` | The demo homes as cards (name, score, class), scored once at start-up |
| `GET /v1/examples`, `GET /v1/examples/{id}` | Demo homes |
| `POST /v1/analyse` | Full analysis of a home |
| `POST /v1/scenario` | Analysis under a chosen set of retrofits or changed answers |
| `POST /v1/diff` | Code-computed comparison of two cached results |
| `POST /v1/explain` | Checked explanation of one section (score, recommendations, savings, value) |
| `POST /v1/chat` | What-if and explanation chat |
| `GET /v1/portfolio` | Homes ranked by improvement potential (precomputed) |
| `GET /v1/methodology` | Score weights, sub-score tables, catalogue and emission factors, read from config |

Errors are `{"error": {"code", "message"}}`; validation failures are 422. Responses never contain NaN.
With `GREENHOME_REQUIRE_AUTH=1` every `/v1` route except auth, health and labels needs a session (off by
default so the Streamlit dashboard, which has no login, keeps working).
Interactive documentation is served at `/docs`.

## 5. Shared contracts

| Contract | Where | Guards against |
|---|---|---|
| Pydantic models and enums (`extra="forbid"`) | `greenhome/contracts.py` | Misspelt enums, unknown fields, wrong units |
| One feature builder | `greenhome/ml/features.py` | Train/serve skew (models check their columns at load) |
| One state-change function | `greenhome/core/transitions.py::apply_retrofits` | Different "after retrofit" homes in simulator and app |
| One formatter | `greenhome/format.py` | The UI and the LLM showing different numbers for one fact |
| One label set | `greenhome/labels.py` | Screens and explanations wording codes differently |
| One split file | `data/processed/splits.parquet` (by customer) | Leakage between train, validation and test |

Units: kWh per year, kg CO2e per year, GBP. Savings are positive for a reduction; an increase is shown as an
increase. Missing values are `null`, never zero.

## 6. Deployment (demo)

```mermaid
flowchart LR
  B[Browser] -->|:8000| UV[uvicorn + FastAPI<br/>make api<br/>serves web/ at /]
  B2[Browser, optional] -->|:8501| ST[Streamlit<br/>make ui]
  ST -->|HTTP :8000| UV
  UV --> ENG[Engine + models<br/>loaded once at start-up]
  UV -->|HTTPS| GQ[Groq API<br/>gpt-oss-120b, failover gpt-oss-20b]
  UV --> DB[(data/app.sqlite<br/>accounts + sessions)]
  ENG --> FS[(config/ · models/ · data/)]
```

Everything except the language model runs on one laptop, with no personal data. The LLM is a hosted
open-weight model on Groq; only the fact sheet of already-computed, formatted numbers and the user's question
are sent to it. Without a key (or with `LLM_PROVIDER=ollama` and a local model) the app still works. Models and
the LLM client are loaded once at start-up, never per request. The trained models are committed under `models/`
(compressed, 59 MB) and used by default (`config/global.yaml: models: real`); the test suite pins stand-in
models with `GREENHOME_MODELS=stub`, so tests don't depend on training.

## 7. Reproducibility

| Step | Command | Output |
|---|---|---|
| Install | `make setup` | `.venv` from the pinned `uv.lock` (Python 3.11) |
| Data | `make data-raw`, `make data` | `data/processed/`, `config/generated/` |
| Models | `make train` | `models/` |
| Evaluation | `make eval`, `make llm-bench` | `reports/` |
| Tests | `make test` | unit + integration tests |
| Run | `make api` (`make ui` optional) | Web app and API on :8000; Streamlit dashboard on :8501 |

Every script reads the seed (42) from `config/global.yaml`; LightGBM runs deterministically.
