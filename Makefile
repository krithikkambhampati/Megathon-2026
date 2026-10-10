# Owned by P5. Each part implements the module its target calls (roadmap.md §5.6).
# Targets whose module does not exist yet print "TODO <owner>" instead of failing.

.PHONY: setup data-raw data train portfolio eval test lint api api-fixture ui all

# $(call run_mod,<module>,<args>,<owner>)
define run_mod
	@if uv run python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$(1)') else 1)" 2>/dev/null; \
	then uv run python -m $(1) $(2); \
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

train:
	$(call run_mod,training.train_all,,P3)

portfolio:
	$(call run_mod,api.build_portfolio,--split test,P5)

eval:
	$(call run_mod,evaluation.eval_ml,,P3)
	$(call run_mod,evaluation.eval_llm,,P4)

test:
	uv run pytest -q

lint:
	uv run ruff check .

api:
	uv run uvicorn api.main:app --port 8000

api-fixture:
	GREENHOME_ENGINE_MODE=fixture uv run uvicorn api.main:app --port 8000

ui:
	uv run streamlit run ui/app.py

all: data train portfolio eval test
