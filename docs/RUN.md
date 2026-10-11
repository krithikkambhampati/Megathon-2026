# Running the project

Everything needed to run the app is in the repo: code, the trained models (`models/`, compressed), the 19 demo
homes (`data/examples/`) and a prebuilt portfolio. You only need the raw public data to *rebuild* the data
or retrain the models.

## 1. Quick start (about 5 minutes, no data needed)

Requirements: Linux, macOS or Windows with WSL2; about 2 GB of disk. A GPU is only needed for the optional
language model.

1. Install uv (≥ 0.4): `pip install --user uv`, or the installer at https://docs.astral.sh/uv/. `make`
   calls `uv`, so `~/.local/bin` must be on your `PATH` (open a new terminal after installing).
2. `git clone <this repository> && cd <repository folder>`
3. `make setup`: installs Python 3.11 if needed and every pinned package from `uv.lock` into `.venv`.
4. `make test`: the whole suite should pass.
5. `make api`, then open **http://localhost:8000**. That is the web app (API docs at `/docs`).
6. Create an account, open any example home, then click **See the report**.

`make ui` still starts the older Streamlit dashboard on http://localhost:8501, an earlier UI for the same API
with no login; the web app is the one to demo.

Without a language model the app is complete: explanations and chat use template answers built from the same
computed numbers (the web app labels them "Standard summary of your report"; the dashboard says "Template
answer").

Run every Python command through `uv run …` or a `make` target, never with a system `python`.

## 2. Language model (hosted on Groq)

Explanations and chat use a hosted open-weight model on Groq: `openai/gpt-oss-120b`, pinned in
`config/llm.yaml`. No GPU or Ollama needed.

1. `cp .env.example .env` and put your Groq key (https://console.groq.com/keys) in it as `LLM_API_KEY=...`.
   Leave `LLM_MODEL=` empty to use the pinned model. `.env` is gitignored: never commit the key.
2. `make api`. The log shows `LLM on: openai_compat:openai/gpt-oss-120b` and its warm-up time (~0.5 s);
   `/v1/health` shows `"llm_ok": true`. Answers that pass the number checker are labelled "Every figure
   checked against your report" in the web app ("✓ all N numbers verified" in the dashboard).

Free tier: 1000 requests/day and 8000 tokens/min per model. On HTTP 429 the client tries
`openai/gpt-oss-20b` (its own quota), then falls back to the template answer.

**Offline alternative (Ollama):** install Ollama ≥ 0.5, `ollama pull qwen2.5:7b-instruct-q4_K_M` (the demo-laptop
benchmark winner, `reports/llm_bench_cachyos-x8664.md`) and set `LLM_PROVIDER=ollama`,
`LLM_BASE_URL=http://localhost:11434`, `LLM_MODEL=qwen2.5:7b-instruct-q4_K_M` in `.env`. On a 6 GB GPU set
`OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` for the Ollama service.

Every `make` target reads `.env` when it exists.

| Command | What it does | Output |
|---|---|---|
| `make llm-bench` | Compares the candidate models on this machine (JSON adherence, checker pass rate, latency, GPU fit) | `reports/llm_bench_<host>.md` |
| `make eval` | Model sizes, the ML evaluation report, then the LLM evaluation and annotation pack | `reports/` |

## 2b. Accounts (web app)

The web app at http://localhost:8000 asks you to log in or create an account (email + password). Accounts
and login sessions live in one SQLite file, `data/app.sqlite` (gitignored, created on first run; set
`GREENHOME_DB` to move it). Passwords are scrypt-hashed; a session is an httpOnly cookie that lasts 30 days
and survives API restarts. Each account's open home, report and chat are kept in that browser (localStorage, one slot per account).
The `/v1` data API stays open by default because the Streamlit UI has no login; set
`GREENHOME_REQUIRE_AUTH=1` to require a session there too. Behind HTTPS, set `GREENHOME_COOKIE_SECURE=1`.

## 3. Rebuilding the data and models (optional)

| Step | Command | Time | Notes |
|---|---|---|---|
| Raw data | `make data-raw` | minutes | Land Registry, UK HPI, NEED, DESNZ, Met Office, PVGIS, ONS lookups. EPC certificates are a manual download: see `data_pipeline/download/README.md` |
| Processed data | `make data` | ≈5 min after downloads | `data/processed/` (kept local), `config/generated/`, demo homes. Deterministic (seed 42) |
| Models | `make train` | ≈30 min | Rating, energy, recommender, value (`docs/MODELS.md`) |
| Portfolio | `make portfolio` | minutes | Ranks the held-out test split. Without processed data: `make portfolio-examples` (demo homes) |

## 4. Other commands

| Command | What it does |
|---|---|
| `make test` | Unit and integration tests (they run on stand-in models, so they don't depend on training) |
| `make lint` | ruff over the whole repo |
| `make api-fixture` | API serving saved test results: works with no models at all |
| `GREENHOME_MODELS=stub make api` | API on stand-in models instead of the trained ones |

## 5. Demo checks

Each of these Problem Statement test cases has a demo home; `tests/integration/test_ps_scenarios.py` checks
the same things automatically.

| Case | Home (card on the web app's Homes page) | What the app shows |
|---|---|---|
| Too little information | Not on the Homes page: open `http://localhost:8000/#/home/P1000205_minimal` | "Not enough information" for score, savings and value; no numbers |
| Missing meter readings | Inter-war terraced house (winter gaps) / Large 1970s detached house (gas missing) | A note that the year was scaled up, or estimated from similar homes |
| Conflicting answers | 1970s purpose-built flat | "High energy use for a home this size" despite a good rating |
| Infeasible retrofits | Victorian conversion flat | Loft insulation and solar under "Not in this plan", with reasons |
| Interacting retrofits | Post-war semi-detached house (the brief's P10001) or 1930s semi with an empty loft | Insulation before the heat pump ("Best done after …"); without insulation the heat pump is capped with "Works best after insulating the home first" |
| Electricity rises after a heating change | P10001 → report → **Make your own plan** → only Air source heat pump → **Compare with our plan** (or ask "What if I only install a heat pump?") | "Extra electricity" in red, gas saved, and the explanation says so |
| Off-gas heating | (API test home P90005) | Score shown; savings "out of scope" |
| Large ≠ inefficient | Modern detached family home | Good class despite high total use |
| Very poor home | Victorian house with electric heaters | Score 27, Very poor |

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `make: uv: No such file or directory` | uv isn't installed or not on `PATH`: step 1 above, then open a new terminal |
| Web app says it can't reach the service, or the dashboard says "API unreachable" | Start `make api` first; the dashboard expects it on `GREENHOME_API_URL` (default `http://localhost:8000`) |
| "Address already in use" | Something is on port 8000/8501: stop it, or run uvicorn/streamlit with another `--port` |
| `VIRTUAL_ENV … does not match` warning | Harmless: an outer virtual environment (e.g. pyenv) is active; uv uses the project's `.venv` |
| Explanations say "Standard summary" / "Template answer" | The language model is off, slow or rate limited (25 s budget per answer): check `LLM_PROVIDER` and `LLM_API_KEY` in `.env`; the `make api` log says `llm: on` or `llm: off` |
| "Explanations aren't available yet" | `greenhome/llm/` is missing: pull the latest `main` |

## 7. Dependencies (team rule)

**Only the P5 owner adds, removes or upgrades packages.** Everyone shares one `pyproject.toml` and one
`uv.lock`. If five people run `uv add` on their own, the lockfile breaks on every merge.

### If you need a package
1. Post in the team channel:
   `DEP REQUEST: <package> (<version if it matters>), needed by P<n> for <one-line reason>`.
2. P5 adds it within **30 minutes**, pins the exact version, runs `make test`, and pushes a commit to `main`
   titled `deps: add <package> (P<n>)`.
3. Merge `main` into your branch, then run `make setup` (or `uv sync`).

### Rules
- **Don't** run `uv add`, `uv remove`, `uv lock --upgrade` or `pip install` in this project.
- **Don't** edit `uv.lock` by hand.
- Versions in `pyproject.toml` are **exact pins** (`==`). Nobody upgrades during the event.
- Test and lint tools go in the `dev` dependency group. STRETCH-only packages (for example `shap`) go in
  the `stretch` extra (`uv sync --extra stretch`).
- **Merge conflict in `uv.lock`?** Take `main`'s version of both `pyproject.toml` and `uv.lock`, and send
  P5 a request for anything your branch added.
- After any pull that changes `uv.lock`, run `make setup` before anything else.

### For P5: adding a dependency
```
uv add "<package>==<exact version>"        # or: uv add --group dev "<package>==<version>"
make test && make lint
git add pyproject.toml uv.lock
git commit -m "deps: add <package> (P<n>)"
git push origin main
```
Then reply to the request in the channel with the commit hash.
