# LLM benchmark on cachyos-x8664

2026-10-10 20:11 UTC · Ollama at http://localhost:11434 · pass bar: p95 answer ≤ 12 s (no deadline), Scenario JSON ≥ 90%, fully on GPU.

| Model | num_ctx | Cold load s | First answer s | Answer p50 / p95 s | Attempt p95 s | tok/s | First-attempt checker pass | JSON adherence | Parse accuracy | GPU | Idle check | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:7b-instruct-q4_K_M | 4096 | 3.2 | 4.5 | 3.5 / 6.7 | 6.2 | 37 | 81.2% | 100.0% | 70.0% | 1.00 | — | PASS |
| qwen2.5:7b-instruct-q4_K_M | 8192 | 16.7 | 4.5 | 3.6 / 6.7 | 6.2 | 37 | 81.2% | 100.0% | 70.0% | 1.00 | — | PASS |
| llama3.1:8b-instruct-q4_K_M | 4096 | 7.1 | 7.5 | 5.6 / 9.1 | 8.3 | 28 | 94.4% | 100.0% | 67.5% | 0.89 | — | fail: only 0.8856254308295782 on GPU |
| llama3.1:8b-instruct-q4_K_M | 8192 | 4.7 | 8.4 | 6.5 / 11.3 | 11.3 | 25 | 94.4% | 100.0% | 65.0% | 0.83 | — | fail: only 0.8320769292994655 on GPU |
| qwen2.5:3b-instruct-q4_K_M | 4096 | 3.0 | 3.3 | 1.4 / 3.9 | 3.6 | 76 | 77.8% | 100.0% | 42.5% | 1.00 | — | PASS |
| qwen2.5:3b-instruct-q4_K_M | 8192 | 3.0 | 3.3 | 1.8 / 4.3 | 3.3 | 77 | 68.4% | 100.0% | 37.5% | 1.00 | — | PASS |

## Recommendation

Pin `model: qwen2.5:7b-instruct-q4_K_M` and `num_ctx: 4096` in `config/llm.yaml`, and set `min_retry_s: 7` (p95 time of one LLM attempt).

Raw rows:

```json
[
 {
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "num_ctx": 4096,
  "cold_load_s": 3.185215072000574,
  "ollama_load_s": null,
  "gpu_fraction": 1.0,
  "first_answer_s": 4.5239562560018385,
  "answers": 16,
  "answer_p50_s": 3.548062107001897,
  "answer_p95_s": 6.650485199999821,
  "attempt_p95_s": 6.200074895998114,
  "tokens_per_s": 37.00816499088204,
  "first_pass_pct": 81.25,
  "json_adherence_pct": 100.0,
  "parse_accuracy_pct": 70.0
 },
 {
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "num_ctx": 8192,
  "cold_load_s": 16.655189340002835,
  "ollama_load_s": null,
  "gpu_fraction": 1.0,
  "first_answer_s": 4.525657399004558,
  "answers": 16,
  "answer_p50_s": 3.5582702539977618,
  "answer_p95_s": 6.661443914999836,
  "attempt_p95_s": 6.162997550003638,
  "tokens_per_s": 36.973982012471566,
  "first_pass_pct": 81.25,
  "json_adherence_pct": 100.0,
  "parse_accuracy_pct": 70.0
 },
 {
  "model": "llama3.1:8b-instruct-q4_K_M",
  "num_ctx": 4096,
  "cold_load_s": 7.138929526001448,
  "ollama_load_s": null,
  "gpu_fraction": 0.8856254308295782,
  "first_answer_s": 7.541943595002522,
  "answers": 18,
  "answer_p50_s": 5.577188907001982,
  "answer_p95_s": 9.071592211999814,
  "attempt_p95_s": 8.310098026995547,
  "tokens_per_s": 27.845038147470397,
  "first_pass_pct": 94.44444444444444,
  "json_adherence_pct": 100.0,
  "parse_accuracy_pct": 67.5
 },
 {
  "model": "llama3.1:8b-instruct-q4_K_M",
  "num_ctx": 8192,
  "cold_load_s": 4.723713077997672,
  "ollama_load_s": null,
  "gpu_fraction": 0.8320769292994655,
  "first_answer_s": 8.352630787005182,
  "answers": 18,
  "answer_p50_s": 6.4508323639965965,
  "answer_p95_s": 11.271820125999511,
  "attempt_p95_s": 11.27173361700261,
  "tokens_per_s": 24.682793801782136,
  "first_pass_pct": 94.44444444444444,
  "json_adherence_pct": 100.0,
  "parse_accuracy_pct": 65.0
 },
 {
  "model": "qwen2.5:3b-instruct-q4_K_M",
  "num_ctx": 4096,
  "cold_load_s": 3.0340551839981345,
  "ollama_load_s": null,
  "gpu_fraction": 1.0,
  "first_answer_s": 3.266971522003587,
  "answers": 18,
  "answer_p50_s": 1.351344466995215,
  "answer_p95_s": 3.93379061199812,
  "attempt_p95_s": 3.638266736001242,
  "tokens_per_s": 75.58626615017252,
  "first_pass_pct": 77.77777777777777,
  "json_adherence_pct": 100.0,
  "parse_accuracy_pct": 42.5
 },
 {
  "model": "qwen2.5:3b-instruct-q4_K_M",
  "num_ctx": 8192,
  "cold_load_s": 3.0313671920011984,
  "ollama_load_s": null,
  "gpu_fraction": 1.0,
  "first_answer_s": 3.327335572997981,
  "answers": 19,
  "answer_p50_s": 1.782089990003442,
  "answer_p95_s": 4.274110732003464,
  "attempt_p95_s": 3.27773230800085,
  "tokens_per_s": 76.5617047101512,
  "first_pass_pct": 68.42105263157895,
  "json_adherence_pct": 100.0,
  "parse_accuracy_pct": 37.5
 }
]
```
