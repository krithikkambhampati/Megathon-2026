# P4 inputs for other owners' documents

Ready-to-paste sections (README §13.2 D15/D16). Figures are from `make llm-bench` and `make eval` on the demo
laptop (`reports/llm_bench_cachyos-x8664.md`, `reports/llm_eval.md`); the human-annotated unsupported-claim
rate is pending. The full detail is in `docs/LLM.md`.

---

## For P3: `reports/evaluation.md`, section "LLM explanations" (by H+26)

> **LLM explanations and what-if parsing.** The LLM never produces a number: it explains engine results
> from a fact sheet of pre-formatted values, and a deterministic number checker verifies every number in
> every reply. A failed check is retried once, then falls back to a template answer. On the 80-item
> scenario set (normal, missing data, conflicting signals, infeasible requests, heat pump, insufficient
> info, multi-turn, adversarial), numeric groundedness was 84.3% for the model's raw first attempt and
> 100% for the answer shown (target ≥ 90%). Factual accuracy was 100%. Two annotators labelled
> 40 answers claim by claim: unsupported claim rate pending (target < 5%), Cohen's κ pending.
> What-if parsing was right on 46/50 with rules only and 44/50 with the LLM fallback. Median
> / p95 latency was 3.3 / 12.9 s on the demo laptop (model qwen2.5:7b-instruct-q4_K_M, local, £0). Details:
> `reports/llm_eval.md`, `docs/LLM.md`.

## For P5: `docs/RESPONSIBLE_AI.md`, section "Hallucination" (by H+28)

> **Hallucination.** A local language model will sometimes invent or round numbers, so it is never trusted
> with one. It is given a fact sheet of numbers already computed by the engine and formatted exactly as the
> screens show them, and is told to copy them and do no arithmetic. Every reply then goes through a number
> checker:
> - every number must match a fact;
> - money claims the tool has no figure for (bill savings, £ value gains) fail;
> - "guarantee"-style promises and mortgage advice fail;
> - an increase described as a saving (e.g. a heat pump's extra electricity) fails.
>
> A failed reply is retried once with the problems listed, then replaced by a deterministic template built
> from the same facts. The user never sees an unchecked number, and each answer shows whether it was
> "verified" or is a "template answer". What-if questions rerun the models before anything is explained,
> and infeasible requests are refused with the engine's reason. Memory changes proposed in chat are never
> stored without the user's confirmation. Measured effect: groundedness 84.3% before vs 100%
> after the checker; human-annotated unsupported claim rate pending (κ pending).

## For P5: `docs/RUN.md`, section "LLM (optional)" (by H+28)

> The app works without an LLM: explanations and chat fall back to template answers. To turn the LLM on:
> 1. Install Ollama ≥ 0.5 and run `ollama pull qwen2.5:7b-instruct-q4_K_M` (the tag pinned in `config/llm.yaml`). On a 6 GB
>    GPU, also set `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0`.
> 2. In `.env`, set `LLM_PROVIDER=ollama` and `LLM_BASE_URL=http://localhost:11434`, and leave `LLM_MODEL=`
>    empty to use the pinned model. A hosted OpenAI-compatible endpoint works too: set
>    `LLM_PROVIDER=openai_compat`, `LLM_BASE_URL=<…/v1>`, `LLM_MODEL=<model>` and `LLM_API_KEY=<key>`
>    (in `.env` only).
> 3. Run `make api`. The log shows "LLM on: …" and the warm-up time, and `/v1/health` shows `llm_ok: true`.
> 4. Optional: `make llm-bench` compares candidate models; `make eval` writes `reports/llm_eval.md`.

## For P5: closing demo slide (README §16 step 10)

| | Before checker | After checker |
|---|---|---|
| Answers with only grounded numbers | 84.3% | 100% |
| Unsupported claims (human-annotated) | — | pending |
| Latency (median / p95) | — | 3.3 / 12.9 s, £0 |
