# Running the project

Everything needed to run the app is in the repo: code, the trained models (`models/`, compressed), the demo
homes (`data/examples/`) and a prebuilt portfolio. You only need the raw public data to *rebuild* the data
or retrain the models.

## 1. Quick start (about 5 minutes, no data needed)

Requirements: Linux, macOS or Windows with WSL2; about 2 GB of disk. A GPU is only needed for the optional
language model.

1. Install uv (≥ 0.4): `pip install --user uv`, or the installer at https://docs.astral.sh/uv/.
2. `git clone https://github.com/krithikkambhampati/Megathon-2026.git && cd Megathon-2026`
3. `make setup`: installs Python 3.11 if needed and every pinned package from `uv.lock` into `.venv`.
4. `make test`: the whole suite should pass.
5. In one terminal `make api` (API on http://localhost:8000, interactive docs at `/docs`).
   In another `make ui` (dashboard on http://localhost:8501).
6. On **Your home**, pick an example home, click **Load example**, then **Analyse my home**.

Without a language model the app is complete: explanations and chat use template answers built from the same
computed numbers (shown as "Template answer").

Run every Python command through `uv run …` or a `make` target, never with a system `python`.

## 2. Language model (hosted on Groq)

Explanations and chat use a hosted open-weight model on Groq: `openai/gpt-oss-120b`, pinned in
`config/llm.yaml`. No GPU or Ollama needed.

1. `cp .env.example .env` and put your Groq key (https://console.groq.com/keys) in it as `LLM_API_KEY=...`.
   Leave `LLM_MODEL=` empty to use the pinned model. `.env` is gitignored: never commit the key.
2. `make api`. The log shows `LLM on: openai_compat:openai/gpt-oss-120b` and its warm-up time (~0.5 s);
   `/v1/health` shows `"llm_ok": true` and the dashboard's sidebar says "LLM: on". Answers then show
   "✓ all N numbers verified" when the checker passes.

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
and survives API restarts. Each account's open home, report and chat are kept in the browser per account.
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

| Case | Home (Your home → example) | What the app shows |
|---|---|---|
| Too little information | Almost no information | "Not enough information" for score, savings and value; no numbers |
| Missing meter readings | Missing winter meter readings / Gas meter data missing | A note that the year was scaled up, or estimated from similar homes |
| Conflicting answers | Good rating, very high usage | "High energy use for a home this size" despite a good rating |
| Infeasible retrofits | Flat with a dwelling above | Loft insulation and solar under "Not suitable", with reasons; rejected in What-if |
| Interacting retrofits | PS2 example home (P10001) | Heat pump comes after insulation ("do after …"); without insulation it is Low with "Works best after insulating the home first" |
| Electricity rises after a heating change | P10001 → What-if → only Air source heat pump | Electricity saving shown in red as an increase, gas saving, and the explanation says so |
| Off-gas heating | (API test home P90005) | Score shown; savings "out of scope" |
| Large ≠ inefficient | Large but efficient detached | Good class despite high total use |

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Sidebar says "API unreachable" | Start `make api` first; the dashboard expects it on `GREENHOME_API_URL` (default `http://localhost:8000`) |
| "Address already in use" | Something is on port 8000/8501: stop it, or run uvicorn/streamlit with another `--port` |
| `VIRTUAL_ENV … does not match` warning | Harmless: an outer virtual environment (e.g. pyenv) is active; uv uses the project's `.venv` |
| Explanations say "Template answer" | The language model is off, slow or rate limited (25 s budget per answer): check `LLM_API_KEY` in `.env` and `/v1/health` |
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
