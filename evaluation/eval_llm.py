"""LLM-layer evaluation (README P4.6): `make eval` → reports/llm_eval.md + reports/llm_eval_raw.jsonl.

Runs every item of evaluation/llm_scenarios.jsonl through the real path (engine → explain/chat → checker)
and the 50 what-if parse items through the parser. Targets: numeric groundedness ≥ 90 %, factual accuracy
≥ 90 %, unsupported claim rate < 5 % (the last one from human annotation, see evaluation/annotate.py).

"Before vs after the checker" (README P4.6): *before* = the model's raw first attempt; *after* = the
answer actually shown (passed check, retried, or template fallback).

The LLM is the uncached inner client, so latencies are real. With no LLM the script exits non-zero unless
`--allow-no-llm`, which writes a clearly marked dry run (reports/llm_eval_dryrun.md) and never touches a
real report.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import socket
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from greenhome.contracts import CONTRACT_VERSION, ChatRequest, HomeInput, Scenario
from greenhome.core.orchestrator import Engine
from greenhome.llm._labels import label
from greenhome.llm.chat import chat
from greenhome.llm.checker import banned_phrases, extract_numbers
from greenhome.llm.client import make_client
from greenhome.llm.explainer import AnswerTrace, explain_traced
from greenhome.llm.settings import get_llm_settings
from greenhome.llm.whatif_parser import parse_whatif

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evaluation" / "llm_scenarios.jsonl"
GOLD = ROOT / "evaluation" / "whatif_parse_gold.jsonl"
FIXTURES = ROOT / "tests" / "fixtures"
REPORTS = ROOT / "reports"
TARGETS = {"groundedness": 90.0, "accuracy": 90.0, "unsupported_claims": 5.0}

# must_mention code → phrase the final answer must contain (case-insensitive)
PHRASES: dict[str, str] = {
    "ESTIMATED": r"\bestimat",
    "INDICATIVE": r"\bindicative\b",
    "NOT_GUARANTEED": r"not (?:a )?guarantee|no guarantee|not guaranteed|isn't guaranteed",
    "LOW_COVERAGE": r"part of the year|months? (?:are |is )?missing|scaled up|some months",
    "ESTIMATED_ANSWERS": r"estimat|answers not given|not provided|assumed|unknown",
    "TYPICAL_HOMES": r"typical similar homes|similar homes",
    "RATING_VS_USAGE": r"unusual for this rating|rating and actual use|both are kept",
    "HEATING_VS_GAS": r"does not match|doesn't match|don't match",
    "AGE_VS_INSULATION": r"since 2007|insulated walls",
    "VALUE_OUTLIER": r"outside the expected range|unusual property value",
    "REASON_NO_LOFT": r"another home above|no loft",
    "REASON_NO_ROOF": r"no suitable roof",
    "REASON_WALL_TYPE": r"type of walls|wall type|doesn't apply",
    "REASON_LISTED": r"listed|conservation",
    "REASON_FLAT_ROOF": r"flat roofs?",
    "REASON_ALREADY": r"already have",
    "ELEC_RISES": r"electricity (?:use )?(?:goes|go|will go|would go|could go) up|electricity[^.]{0,40}"
    r"(?:rise|rises|increase|goes up)|(?:rise|increase) in electricity",
    "INSULATE_FIRST": r"insulat\w*[^.]{0,30}first|after insulating",
    "INSUFFICIENT": r"not enough information|isn't enough information|can't give|can't estimate|"
    r"don't have enough",
    "SURVEY": r"survey",
    "OUT_OF_SCOPE_FUEL": r"only modelled|mains gas or electricity|can't be estimated for your heating fuel",
}
_NEGATED_REC = re.compile(
    r"not suitable|isn't suitable|not possible|can't|cannot|doesn't apply|no loft|another home "
    r"above|already have|left out|not recommended|different kind|no suitable",
    re.IGNORECASE,
)
_RECOMMEND = re.compile(
    r"\b(?:recommend\w*|you should|worth (?:doing|installing|it)|go for|install it)\b", re.IGNORECASE
)
_ADVICE = re.compile(
    r"\byou should (?:re)?mortgage|\btake out a loan\b|\bborrow (?:money|against)\b", re.IGNORECASE
)


# ---------- scoring helpers (pure, unit-tested) ----------
def mentions(answer: str, codes: list[str]) -> dict[str, bool]:
    return {c: bool(re.search(PHRASES[c], answer, re.IGNORECASE)) for c in codes}


def violations(answer: str, codes: list[str]) -> list[str]:
    """must_not codes the answer violates."""
    out = []
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    for code in codes:
        if code == "GUARANTEE" and banned_phrases(answer):
            out.append(code)
        elif code == "ADVICE" and _ADVICE.search(answer):
            out.append(code)
        elif code == "NUMBERS" and extract_numbers(answer):
            out.append(code)
        elif code.startswith("RECOMMENDS:"):
            name = label("Retrofit", code.split(":", 1)[1]).lower()
            if any(
                name in s.lower() and _RECOMMEND.search(s) and not _NEGATED_REC.search(s) for s in sentences
            ):
                out.append(code)
    return out


def scenario_matches(got: Scenario | None, expected: dict | None) -> bool | None:
    if expected is None:
        return None
    if got is None:
        return False
    return got.mode == expected["mode"] and (
        got.mode != "custom" or list(got.retrofits) == expected["retrofits"]
    )


def pct(n: float, d: float) -> float | None:
    return None if d == 0 else 100.0 * n / d


def p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def stratified_sample(records: list[dict], n: int, seed: int = 42) -> list[dict]:
    """Up to n records, spread over categories in proportion; LLM-written answers first."""
    import random

    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r)
    for rows in by_cat.values():
        rng.shuffle(rows)
        rows.sort(key=lambda r: r["fallback_reason"] is not None)  # LLM-written first
    total = len(records)
    quota = {c: max(1, round(n * len(rows) / total)) for c, rows in by_cat.items()} if total else {}
    picked = [r for c, rows in by_cat.items() for r in rows[: quota[c]]]
    rest = [r for c, rows in by_cat.items() for r in rows[quota[c] :]]
    picked += rest[: max(0, n - len(picked))]
    return sorted(picked[:n], key=lambda r: r["id"])


# ---------- running ----------
def _home(item: dict) -> HomeInput:
    data = json.loads((FIXTURES / f"home_input_{item['home']}.json").read_text())
    return HomeInput.model_validate({**data, **item.get("overrides", {})})


def _trace_fields(trace: AnswerTrace | None) -> dict:
    if trace is None:
        return {
            "raw_first": None,
            "attempts": 0,
            "fallback_reason": "template",
            "prompt_tokens": None,
            "completion_tokens": None,
            "facts": None,
        }
    first = trace.attempts[0] if trace.attempts else None
    toks_in = [a.prompt_tokens for a in trace.attempts if a.prompt_tokens is not None]
    toks_out = [a.completion_tokens for a in trace.attempts if a.completion_tokens is not None]
    return {
        "raw_first": None
        if first is None
        else {
            "text": first.text,
            "passed": first.report.passed,
            "numbers_found": first.report.numbers_found,
            "unsupported": first.report.unsupported,
            "banned": first.report.banned_phrases,
            "seconds": first.seconds,
        },
        "attempts": len(trace.attempts),
        "fallback_reason": trace.fallback_reason,
        "prompt_tokens": sum(toks_in) if toks_in else None,
        "completion_tokens": sum(toks_out) if toks_out else None,
        "facts": trace.sheet.lines(),
        "notes": trace.sheet.notes,
    }


def run_item(item: dict, engine: Engine, llm, settings) -> dict:
    home = _home(item)
    base = engine.analyse(home)
    rec: dict[str, Any] = {
        "id": item["id"],
        "category": item["category"],
        "call": item["call"],
        "message": item["turns"][-1] if item["turns"] else f"[explain {item['section']}]",
    }
    if item["call"] == "explain":
        t0 = time.monotonic()
        trace = explain_traced(base, item["section"], llm, settings=settings)
        rec.update(
            seconds=time.monotonic() - t0,
            answer=trace.text,
            check=trace.check.model_dump(),
            intent=None,
            scenario=None,
            **_trace_fields(trace),
        )
    else:
        current = None
        for msg in item["turns"]:
            traces: list = []
            t0 = time.monotonic()
            resp = chat(
                ChatRequest(session_id=item["id"], home=home, message=msg, current_scenario=current),
                engine,
                llm,
                None,
                base,
                settings=settings,
                traces=traces,
            )
            seconds = time.monotonic() - t0
            current = resp.scenario
        rec.update(
            seconds=seconds,
            answer=resp.answer,
            check=resp.check.model_dump(),
            intent=resp.intent,
            scenario=None if resp.scenario is None else resp.scenario.model_dump(),
            **_trace_fields(traces[-1] if traces else None),
        )
    rec["intent_ok"] = None if item["expected_intent"] is None else rec["intent"] == item["expected_intent"]
    sc = Scenario.model_validate(rec["scenario"]) if rec["scenario"] else None
    rec["scenario_ok"] = scenario_matches(sc, item["expected_scenario"])
    rec["must_mention"] = mentions(rec["answer"], item["must_mention"])
    rec["violations"] = violations(rec["answer"], item["must_not"])
    return rec


def parse_eval(llm, settings) -> dict:
    gold = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    out: dict[str, Any] = {"n": len(gold), "rules": 0, "rules_llm": 0 if llm else None, "llm_used": 0}
    from greenhome.contracts import AnalysisResult
    from greenhome.llm.budget import Deadline

    for g in gold:
        home = HomeInput.model_validate_json((FIXTURES / f"home_input_{g['home']}.json").read_text())
        base = AnalysisResult.model_validate_json(
            (FIXTURES / f"analysis_result_{g['home']}.json").read_text()
        )
        current = Scenario.model_validate(g["current_scenario"]) if g["current_scenario"] else None

        def ok(res, g=g) -> bool:
            if g["expected"] is None:
                return res.scenario is None
            e = g["expected"]
            return res.scenario is not None and (
                res.scenario.mode,
                list(res.scenario.retrofits) if res.scenario.mode == "custom" else [],
                res.scenario.overrides,
            ) == (e["mode"], e["retrofits"], e["overrides"])

        out["rules"] += ok(parse_whatif(g["message"], home, base, current))
        if llm is not None:
            res = parse_whatif(
                g["message"],
                home,
                base,
                current,
                llm=llm,
                deadline=Deadline(settings.answer_budget_s),
                settings=settings,
            )
            out["llm_used"] += res.method == "llm"
            out["rules_llm"] += ok(res)
    return out


def summarise(records: list[dict], parse: dict) -> dict:
    llm_recs = [r for r in records if r["raw_first"] is not None]
    nums_found = sum(len(r["check"]["numbers_found"]) for r in records)
    nums_bad = sum(len([u for u in r["check"]["unsupported"] if not u.endswith(")")]) for r in records)
    mm = [v for r in records for v in r["must_mention"].values()]
    intents = [r["intent_ok"] for r in records if r["intent_ok"] is not None]
    scen = [r["scenario_ok"] for r in records if r["scenario_ok"] is not None]
    reasons: dict[str, int] = {}
    for r in records:
        reasons[str(r["fallback_reason"])] = reasons.get(str(r["fallback_reason"]), 0) + 1
    secs = [r["seconds"] for r in records]
    toks = [r["completion_tokens"] for r in records if r["completion_tokens"] is not None]
    return {
        "n": len(records),
        "llm_answers": len(llm_recs),
        "groundedness_before": pct(sum(r["raw_first"]["passed"] for r in llm_recs), len(llm_recs)),
        "groundedness_after": pct(sum(r["check"]["passed"] for r in records), len(records)),
        "numeric_accuracy": pct(nums_found - nums_bad, nums_found),
        "must_mention": pct(sum(mm), len(mm)),
        "violations": sum(len(r["violations"]) for r in records),
        "intent_accuracy": pct(sum(intents), len(intents)),
        "scenario_accuracy": pct(sum(scen), len(scen)),
        "fallback": reasons,
        "latency_median": statistics.median(secs) if secs else None,
        "latency_p95": p95(secs),
        "tokens_per_answer": statistics.mean(toks) if toks else None,
        "parse": parse,
    }


# ---------- report ----------
def _f(x: float | None, unit: str = "%") -> str:
    return "—" if x is None else (f"{x:.1f}{unit}" if unit == "%" else f"{x:.2f}{unit}")


def run_info(llm, settings) -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
    except OSError:
        commit = "unknown"
    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "commit": commit,
        "contract": CONTRACT_VERSION,
        "llm": getattr(llm, "name", None) or "none (templates only)",
        "budget_s": settings.answer_budget_s,
    }


def write_report(path: Path, info: dict, summ: dict, records: list[dict], dry_run: bool) -> None:
    by_cat: dict[str, list[dict]] = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r)
    L = ["# LLM layer evaluation", ""]
    if dry_run:
        L += [
            "> **PIPELINE TEST, not results.** No LLM was available, so every answer is a template. The",
            "> numbers below only show that the evaluation runs; the real report comes from `make eval` on",
            "> the demo laptop.",
            "",
        ]
    L += ["## Run", "", "| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in info.items()] + [""]
    p = summ["parse"]
    L += [
        "## Summary vs targets (README P4.6)",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        "| Numeric groundedness, raw LLM first attempt (before checker) | "
        f"{_f(summ['groundedness_before'])} | — |",
        f"| Numeric groundedness, answer shown (after checker) | {_f(summ['groundedness_after'])} | ≥ 90% |",
        "| Numeric accuracy (numbers in shown answers that match a fact) | "
        f"{_f(summ['numeric_accuracy'])} | ≥ 90% |",
        f"| `must_mention` satisfied | {_f(summ['must_mention'])} | ≥ 90% |",
        f"| `must_not` violations | {summ['violations']} | 0 |",
        f"| Intent accuracy (chat) | {_f(summ['intent_accuracy'])} | — |",
        f"| Scenario accuracy (what-if) | {_f(summ['scenario_accuracy'])} | — |",
        f"| What-if parse, rules only | {p['rules']}/{p['n']} | — |",
        f"| What-if parse, rules + LLM | "
        f"{'—' if p['rules_llm'] is None else str(p['rules_llm']) + '/' + str(p['n'])} "
        f"(LLM used {p['llm_used']}) | — |",
        f"| Latency per answer, median / p95 | {_f(summ['latency_median'], ' s')} / "
        f"{_f(summ['latency_p95'], ' s')} "
        f"| ≤ {info['budget_s']:.0f} s |",
        f"| Output tokens per LLM answer (mean) | {_f(summ['tokens_per_answer'], '')} | — |",
        "| Cost | £0 (local model) | — |",
        "| Unsupported claim rate (human annotation) | see `reports/llm_annotation.md` | < 5% |",
        "",
    ]
    L += [
        "Answers by source: "
        + ", ".join(f"{k}: {v}" for k, v in sorted(summ["fallback"].items()))
        + " (`None` = LLM answer shown).",
        "",
    ]
    L += [
        "## By category",
        "",
        "| Category | n | Shown answer passes | Raw first attempt passes | must_mention | Violations |",
        "|---|---|---|---|---|---|",
    ]
    for cat, rows in by_cat.items():
        raw = [r for r in rows if r["raw_first"]]
        mm = [v for r in rows for v in r["must_mention"].values()]
        L.append(
            f"| {cat} | {len(rows)} | {_f(pct(sum(r['check']['passed'] for r in rows), len(rows)))} | "
            f"{_f(pct(sum(r['raw_first']['passed'] for r in raw), len(raw)))} | "
            f"{_f(pct(sum(mm), len(mm)))} | "
            f"{sum(len(r['violations']) for r in rows)} |"
        )
    fails = [r for r in records if r["raw_first"] and not r["raw_first"]["passed"]][:10]
    L += ["", "## What the checker caught (raw first attempts that failed)", ""]
    L += [
        f"- **{r['id']}** ({r['category']}): unsupported {r['raw_first']['unsupported']}, banned "
        f"{r['raw_first']['banned']} → shown: "
        f"{'retry' if r['fallback_reason'] is None else r['fallback_reason']}"
        for r in fails
    ] or ["- none"]
    misses = [
        r
        for r in records
        if not all(r["must_mention"].values())
        or r["violations"]
        or r["intent_ok"] is False
        or r["scenario_ok"] is False
    ][:15]
    L += ["", "## Misses", ""]
    L += [
        f"- **{r['id']}** ({r['category']}) `{r['message']}`: intent {r['intent']} "
        f"(ok={r['intent_ok']}), scenario ok={r['scenario_ok']}, missing "
        f"{[k for k, v in r['must_mention'].items() if not v]}, violations {r['violations']}"
        for r in misses
    ] or ["- none"]
    L += [
        "",
        "## Limitations",
        "",
        "- Engine numbers come from the models configured at run time (`model_versions` in the raw file).",
        "- `must_mention` uses phrase patterns, so a correct answer worded differently counts as a miss.",
        "- Latency is measured on the machine named above; the uncached client is used.",
        "",
    ]
    path.write_text("\n".join(L))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-no-llm", action="store_true", help="run with templates only (dry run)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N scenarios")
    ap.add_argument(
        "--annotation", type=int, default=40, help="responses to export for human annotation (0: none)"
    )
    args = ap.parse_args(argv)

    settings = get_llm_settings()
    client = make_client(warm_up="blocking")
    llm = getattr(client, "inner", client)  # uncached: real latencies
    dry_run = llm is None
    if dry_run and not args.allow_no_llm:
        print(
            "No LLM available (LLM_PROVIDER unset, model not pinned, or Ollama unreachable). "
            "Start Ollama and set "
            ".env, or pass --allow-no-llm for a pipeline test.",
            file=sys.stderr,
        )
        return 2
    engine = Engine.from_config()
    items = [json.loads(line) for line in SCENARIOS.read_text().splitlines() if line.strip()][: args.limit]
    records = []
    for i, item in enumerate(items, 1):
        records.append(run_item(item, engine, llm, settings))
        print(
            f"[{i}/{len(items)}] {item['id']} {item['category']}: {records[-1]['seconds']:.1f} s", flush=True
        )
    summ = summarise(records, parse_eval(llm, settings))
    info = run_info(llm, settings) | {"engine models": engine.cfg.global_.models}
    stem = "llm_eval_dryrun" if dry_run else "llm_eval"
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{stem}_raw.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    write_report(REPORTS / f"{stem}.md", info, summ, records, dry_run)
    print(f"wrote reports/{stem}.md")
    if args.annotation and not dry_run:
        from evaluation.annotate import export

        export(stratified_sample(records, args.annotation), info)
        print("wrote evaluation/annotation/ (send annotator_P1.csv / annotator_P2.csv + RESPONSES.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
