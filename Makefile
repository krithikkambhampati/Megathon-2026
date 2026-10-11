# Owned by P5. Each part implements the module its target calls (roadmap.md §5.6).
# Targets whose module does not exist yet print "TODO <owner>" instead of failing.

.PHONY: setup data-raw data train portfolio portfolio-examples eval llm-bench test lint api api-fixture ui all

# .env (if present) holds LLM settings etc.; every target below loads it
UV_ENV := $(if $(wildcard .env),--env-file .env,)

# $(call run_mod,<module>,<args>,<owner>)
define run_mod
	@if uv run python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$(1)') else 1)" 2>/dev/null; \
	then uv run $(UV_ENV) python -m $(1) $(2); \
	else echo "TODO $(3): module $(1) not implemented yet"; fi
endef

setup:
	uv sync
	mkdir -p data/raw data/interim data/processed data/examples models outputs reports

# EPC certificates are a manual download (GOV.UK One Login): see data_pipeline/download/README.md
data-raw:
	$(call run_mod,data_pipeline.download.download_public,,P1)
	$(call run_mod,data_pipeline.download.ons_lad_region,,P1)

data:
	$(call run_mod,data_pipeline.run_all,,P1)

# P3's order (docs/MODELS.md): rating, energy, recommender, value (~30 min total)
train:
	$(call run_mod,training.train_rating,,P3)
	$(call run_mod,training.train_energy,,P3)
	$(call run_mod,training.train_recommender,,P3)
	$(call run_mod,training.train_value,,P3)

portfolio:
	$(call run_mod,api.build_portfolio,--split test,P5)

# Portfolio from the committed demo homes (no processed data needed)
portfolio-examples:
	$(call run_mod,api.build_portfolio,--source examples,P5)

# Groq free tier: 8000 tokens/min per model, so the LLM eval is paced (≈35 min). EVAL_TPM=0 for Ollama.
EVAL_TPM ?= 6000

eval:
	$(call run_mod,training.model_sizes,,P3)
	$(call run_mod,training.evaluation_report,,P3)
	$(call run_mod,evaluation.eval_llm,--tpm $(EVAL_TPM),P4)

# P4's model benchmark against the configured provider (.env; Ollama path only for LLM_PROVIDER=ollama)
llm-bench:
	$(call run_mod,evaluation.llm_bench,,P4)

test:
	uv run pytest -q

lint:
	uv run ruff check .

# uvicorn loads .env itself (python-dotenv ships with uvicorn[standard])
ENV_FILE := $(if $(wildcard .env),--env-file .env,)

api:
	uv run uvicorn api.main:app --port 8000 $(ENV_FILE)

api-fixture:
	GREENHOME_ENGINE_MODE=fixture uv run uvicorn api.main:app --port 8000 $(ENV_FILE)

ui:
	uv run streamlit run ui/app.py

all: data train portfolio eval test
