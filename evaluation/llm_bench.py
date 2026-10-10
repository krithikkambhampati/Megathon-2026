"""Model benchmark for the demo laptop (docs/archive/ROADMAP_P4.md P4-11): which Ollama model to pin.

Run on the machine that will give the demo, with Ollama running and the candidates pulled:
    uv run python -m evaluation.llm_bench                 # candidates from config/llm.yaml
    uv run python -m evaluation.llm_bench --models qwen2.5:7b-instruct-q4_K_M --num-ctx 4096,8192
Writes reports/llm_bench_<host>.md.

Per model × num_ctx: every loaded model is unloaded first (keep_alive 0), so the cold load is real. Then:
cold-load time (incl. Ollama's load_duration), GPU fit (/api/ps), first answer after warm-up, answer time
p50/p95 over 4 sections × 5 fixtures with NO deadline (raw speed), tokens/s, first-attempt checker pass rate,
Scenario JSON adherence on the 50 parse items, and optionally whether the model is still loaded after an idle
wait. Pass bar: p95 answer ≤ the answer cap, JSON adherence ≥ 90 %, fully on GPU. Winner: best first-attempt
checker pass rate among models that pass.
"""

from __future__ import annotations

import argparse
import json
import socket
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from greenhome.contracts import AnalysisResult, Scenario
from greenhome.llm.budget import Deadline
from greenhome.llm.client import LLMError, OllamaClient
from greenhome.llm.explainer import explain_traced, render
from greenhome.llm.settings import LLMSettings, get_llm_settings
from greenhome.llm.whatif_parser import RETROFITS, SCENARIO_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GOLD = ROOT / "evaluation" / "whatif_parse_gold.jsonl"
IDS = ["P10001", "P90002", "P90003", "P90004", "P90005"]
SECTIONS = ["score", "recommendations", "savings", "value"]
JSON_BAR, GPU_BAR = 90.0, 0.999


def p(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def verdict(row: dict, answer_cap_s: float) -> tuple[bool, list[str]]:
    """Pass bar for one model × num_ctx row; returns (passes, reasons it fails)."""
    why = []
    if row.get("error"):
        return False, [row["error"]]
    if row["answer_p95_s"] is None or row["answer_p95_s"] > answer_cap_s:
        why.append(f"p95 answer {row['answer_p95_s']} s > {answer_cap_s} s")
    if row["json_adherence_pct"] is None or row["json_adherence_pct"] < JSON_BAR:
        why.append(f"JSON adherence {row['json_adherence_pct']}% < {JSON_BAR}%")
    if row["gpu_fraction"] is None or row["gpu_fraction"] < GPU_BAR:
        why.append(f"only {row['gpu_fraction']} on GPU")
    return not why, why


def pick_winner(rows: list[dict], answer_cap_s: float) -> dict | None:
    passing = [r for r in rows if verdict(r, answer_cap_s)[0]]
    return max(passing, key=lambda r: (r["first_pass_pct"] or 0, -(r["answer_p95_s"] or 1e9)), default=None)


def _ollama(s: LLMSettings, path: str, method: str = "GET", **kw) -> dict:
    r = httpx.request(method, f"{s.base_url.rstrip('/')}{path}", timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def unload_all(s: LLMSettings) -> None:
    for m in _ollama(s, "/api/ps").get("models", []):
        OllamaClient(s.model_copy(update={"model": m.get("name")})).unload()
    for _ in range(20):
        if not _ollama(s, "/api/ps").get("models"):
            return
        time.sleep(0.5)


def _results() -> list[AnalysisResult]:
    return [
        AnalysisResult.model_validate_json((FIXTURES / f"analysis_result_{fx}.json").read_text())
        for fx in IDS
    ]


def json_adherence(client: OllamaClient, s: LLMSettings) -> tuple[float, float | None]:
    """% of the 50 parse items with valid Scenario JSON, and % of retrofit-only items parsed right."""
    gold = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    base = {
        fx: AnalysisResult.model_validate_json((FIXTURES / f"analysis_result_{fx}.json").read_text())
        for fx in {g["home"] for g in gold}
    }
    valid = right = scored = 0
    for g in gold:
        b = base[g["home"]]
        cur = g["current_scenario"]
        system = render(
            "whatif_parse.j2",
            retrofits={r: r for r in RETROFITS},
            base_package=list(b.savings.retrofits),
            current=cur["retrofits"] if cur else None,
        )
        try:
            data = json.loads(
                client.generate(
                    system,
                    [{"role": "user", "content": g["message"]}],
                    SCENARIO_SCHEMA,
                    s.tokens("whatif_parse", 200),
                    timeout_s=60,
                )
            )
            sc = Scenario(
                name="bench",
                mode=data["mode"],
                retrofits=data["retrofits"] if data["mode"] == "custom" else [],
            )
            valid += 1
        except (LLMError, ValueError, KeyError, TypeError):
            sc = None
        e = g["expected"]
        if e is not None and not e["overrides"]:
            scored += 1
            right += (
                sc is not None
                and sc.mode == e["mode"]
                and (sc.mode != "custom" or sc.retrofits == e["retrofits"])
            )
    return 100.0 * valid / len(gold), (100.0 * right / scored if scored else None)


def bench_one(tag: str, num_ctx: int, s0: LLMSettings, idle_s: float) -> dict:
    s = s0.model_copy(
        update={
            "provider": "ollama",
            "model": tag,
            "num_ctx": num_ctx,
            "call_cap_s": {},
            "call_timeout_s": 300.0,
            "answer_budget_s": 1e9,
            "min_retry_s": 0.0,
        }
    )
    row: dict = {"model": tag, "num_ctx": num_ctx}
    client = OllamaClient(s)
    if not client.ping():
        return row | {"error": f"Ollama not reachable at {s.base_url}"}
    if not client.has_model():
        return row | {"error": f"not pulled (run: ollama pull {tag})"}
    unload_all(s)
    try:
        row["cold_load_s"] = client.warm_up()
        row["ollama_load_s"] = client.last_usage.load_seconds if client.last_usage else None
    except LLMError as e:
        return row | {"error": f"warm-up failed: {e}"}
    row["gpu_fraction"] = client.gpu_fraction()
    results = _results()
    t0 = time.monotonic()
    explain_traced(results[0], "savings", client, deadline=Deadline(1e9), settings=s)
    row["first_answer_s"] = time.monotonic() - t0
    answers, attempts, first_ok, tps = [], [], [], []
    for r in results:
        for sec in SECTIONS:
            t = explain_traced(r, sec, client, deadline=Deadline(1e9), settings=s)
            if t.attempts:
                answers.append(t.seconds)
                first_ok.append(t.attempts[0].report.passed)
                for a in t.attempts:
                    attempts.append(a.seconds)
                    if a.completion_tokens and a.seconds > 0:
                        tps.append(a.completion_tokens / a.seconds)
    row |= {
        "answers": len(answers),
        "answer_p50_s": p(answers, 0.5),
        "answer_p95_s": p(answers, 0.95),
        "attempt_p95_s": p(attempts, 0.95),
        "tokens_per_s": statistics.median(tps) if tps else None,
        "first_pass_pct": 100.0 * sum(first_ok) / len(first_ok) if first_ok else None,
    }
    row["json_adherence_pct"], row["parse_accuracy_pct"] = json_adherence(client, s)
    if idle_s > 0:
        time.sleep(idle_s)
        row["still_loaded_after_idle"] = bool(client.gpu_fraction() is not None)
    client.unload()
    return row


def _fmt(x, nd: int = 1, suffix: str = "") -> str:
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x)) + suffix


def write_report(rows: list[dict], s: LLMSettings, path: Path) -> dict | None:
    cap = s.cap("answer")
    win = pick_winner(rows, cap)
    L = [
        f"# LLM benchmark on {socket.gethostname()}",
        "",
        f"{datetime.now(UTC):%Y-%m-%d %H:%M UTC} · Ollama at {s.base_url} · "
        f"pass bar: p95 answer ≤ {cap:.0f} s "
        f"(no deadline), Scenario JSON ≥ {JSON_BAR:.0f}%, fully on GPU.",
        "",
        "| Model | num_ctx | Cold load s | First answer s | Answer p50 / p95 s | Attempt p95 s | tok/s | "
        "First-attempt checker pass | JSON adherence | Parse accuracy | GPU | Idle check | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ok, why = verdict(r, cap)
        L.append(
            f"| {r['model']} | {r['num_ctx']} | {_fmt(r.get('cold_load_s'))} | "
            f"{_fmt(r.get('first_answer_s'))} | "
            f"{_fmt(r.get('answer_p50_s'))} / {_fmt(r.get('answer_p95_s'))} | "
            f"{_fmt(r.get('attempt_p95_s'))} | "
            f"{_fmt(r.get('tokens_per_s'), 0)} | {_fmt(r.get('first_pass_pct'), 1, '%')} | "
            f"{_fmt(r.get('json_adherence_pct'), 1, '%')} | {_fmt(r.get('parse_accuracy_pct'), 1, '%')} | "
            f"{_fmt(r.get('gpu_fraction'), 2)} | {r.get('still_loaded_after_idle', '—')} | "
            f"{'PASS' if ok else 'fail: ' + '; '.join(why)} |"
        )
    L += [""]
    if win:
        retry = max(3.0, round((win.get("attempt_p95_s") or 8.0) + 0.5))
        L += [
            "## Recommendation",
            "",
            f"Pin `model: {win['model']}` and `num_ctx: {win['num_ctx']}` in `config/llm.yaml`, and set "
            f"`min_retry_s: {retry:.0f}` (p95 time of one LLM attempt).",
            "",
        ]
    else:
        L += [
            "## Recommendation",
            "",
            "No candidate passed. Per the roadmap: explanations default to templates, "
            "the LLM is used only in chat, and the pin falls back to the best 3–4B model or the "
            "hosted endpoint.",
            "",
        ]
    L += ["Raw rows:", "", "```json", json.dumps(rows, indent=1), "```", ""]
    path.write_text("\n".join(L))
    return win


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark Ollama models for the P4 LLM layer")
    ap.add_argument("--models", help="comma-separated tags (default: config/llm.yaml candidates)")
    ap.add_argument("--num-ctx", default="4096,8192", help="comma-separated context sizes")
    ap.add_argument(
        "--idle-check", type=float, default=0, help="seconds to wait, then check the model is loaded"
    )
    args = ap.parse_args(argv)
    s = get_llm_settings()
    models = args.models.split(",") if args.models else s.candidates
    rows = []
    for tag in models:
        for ctx in (int(x) for x in args.num_ctx.split(",")):
            print(f"benchmarking {tag} num_ctx={ctx} …", flush=True)
            rows.append(bench_one(tag.strip(), ctx, s, args.idle_check))
            print(f"  {rows[-1]}", flush=True)
    out = ROOT / "reports" / f"llm_bench_{socket.gethostname()}.md"
    out.parent.mkdir(exist_ok=True)
    win = write_report(rows, s, out)
    print(
        f"wrote {out}" + (f"; winner {win['model']} num_ctx={win['num_ctx']}" if win else "; no model passed")
    )
    return 0 if any("error" not in r for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
