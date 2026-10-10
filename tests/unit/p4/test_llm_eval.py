from __future__ import annotations

import csv
import json

import pytest

import evaluation.eval_llm as ev
from evaluation import annotate, llm_bench
from evaluation.build_llm_scenarios import ITEMS
from greenhome.contracts import Scenario

# ---------- scenario set ----------


def test_scenario_set_matches_readme_counts_and_codes() -> None:
    counts: dict[str, int] = {}
    for i in ITEMS:
        counts[i["category"]] = counts.get(i["category"], 0) + 1
    assert counts == {
        "normal": 20,
        "missing_data": 10,
        "conflict": 10,
        "infeasible": 10,
        "heat_pump": 10,
        "insufficient": 8,
        "multi_turn": 8,
        "adversarial": 4,
    }
    committed = [json.loads(line) for line in ev.SCENARIOS.read_text().splitlines()]
    assert committed == ITEMS  # the jsonl is regenerated from the builder
    for i in ITEMS:
        assert all(c in ev.PHRASES for c in i["must_mention"])
        assert all(
            c in ("GUARANTEE", "ADVICE", "NUMBERS") or c.startswith("RECOMMENDS:") for c in i["must_not"]
        )
        assert (i["call"] == "explain") == bool(i["section"] and not i["turns"])


# ---------- scoring helpers ----------


def test_mentions_and_violations() -> None:
    ans = "Electricity use goes up while gas falls. This is indicative and not guaranteed."
    assert ev.mentions(ans, ["ELEC_RISES", "INDICATIVE", "NOT_GUARANTEED", "SURVEY"]) == {
        "ELEC_RISES": True,
        "INDICATIVE": True,
        "NOT_GUARANTEED": True,
        "SURVEY": False,
    }
    assert ev.violations(ans, ["GUARANTEE", "NUMBERS"]) == []
    assert ev.violations("We guarantee 5 savings.", ["GUARANTEE", "NUMBERS"]) == ["GUARANTEE", "NUMBERS"]
    assert ev.violations("You should remortgage.", ["ADVICE"]) == ["ADVICE"]


def test_recommends_violation_ignores_explained_refusals() -> None:
    code = ["RECOMMENDS:loft_insulation"]
    assert ev.violations("We recommend loft insulation first.", code) == code
    assert ev.violations("Loft insulation is not suitable: there's another home above.", code) == []
    assert ev.violations("We recommend solar panels. Loft insulation is not possible.", code) == []


def test_scenario_matches() -> None:
    sc = Scenario(name="x", mode="custom", retrofits=["solar_pv"])
    assert ev.scenario_matches(sc, {"mode": "custom", "retrofits": ["solar_pv"]})
    assert not ev.scenario_matches(sc, {"mode": "custom", "retrofits": ["air_source_heat_pump"]})
    assert ev.scenario_matches(None, None) is None and ev.scenario_matches(None, {"mode": "none"}) is False


def test_stratified_sample_spreads_categories_and_prefers_llm_answers() -> None:
    recs = [
        {
            "id": f"S{i:02d}",
            "category": "a" if i < 60 else "b",
            "fallback_reason": None if i % 2 else "no_llm",
        }
        for i in range(80)
    ]
    pick = ev.stratified_sample(recs, 40)
    assert len(pick) == 40 and {r["category"] for r in pick} == {"a", "b"}
    assert sum(r["category"] == "b" for r in pick) == 10
    assert all(r["fallback_reason"] is None for r in pick if r["category"] == "a")
    assert ev.stratified_sample(recs, 40) == pick  # seeded


def test_p95() -> None:
    assert ev.p95([]) is None and ev.p95([3.0]) == 3.0 and ev.p95([float(i) for i in range(1, 101)]) == 95.0


# ---------- end to end (templates only) ----------


def test_eval_refuses_to_run_without_an_llm(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ev, "REPORTS", tmp_path)
    assert ev.main([]) == 2 and not list(tmp_path.iterdir())


def test_eval_dry_run_writes_a_marked_report(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ev, "REPORTS", tmp_path)
    assert ev.main(["--allow-no-llm", "--limit", "12"]) == 0
    report = (tmp_path / "llm_eval_dryrun.md").read_text()
    assert "PIPELINE TEST, not results" in report and not (tmp_path / "llm_eval.md").exists()
    raw = [json.loads(line) for line in (tmp_path / "llm_eval_dryrun_raw.jsonl").read_text().splitlines()]
    assert len(raw) == 12 and all(r["check"]["passed"] for r in raw)


# ---------- annotation ----------


def _records(n: int = 3) -> list[dict]:
    return [
        {
            "id": f"S{i}",
            "category": "normal",
            "message": "Why?",
            "fallback_reason": None,
            "answer": f"Your score is {30 + i}. It is Poor.\n- These are estimates.",
            "facts": "F1 Score: 3x",
            "notes": [],
        }
        for i in range(n)
    ]


def test_export_gives_both_annotators_the_same_rows_in_different_orders(tmp_path) -> None:
    annotate.export(_records(), {"llm": "ollama:test"}, out=tmp_path)
    sheets = {}
    for who in ("P1", "P2"):
        with (tmp_path / f"annotator_{who}.csv").open() as f:
            sheets[who] = [r["sentence_id"] for r in csv.DictReader(f)]
    assert sorted(sheets["P1"]) == sorted(sheets["P2"]) and len(sheets["P1"]) == 9
    assert sheets["P1"] != sheets["P2"]
    assert "R01.2" in (tmp_path / "RESPONSES.md").read_text()
    assert json.loads((tmp_path / "responses.json").read_text())[0]["model"] == "ollama:test"


def test_cohens_kappa_known_values() -> None:
    assert annotate.cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert annotate.cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert annotate.cohens_kappa([], []) is None
    assert annotate.cohens_kappa(["x"] * 3, ["x"] * 3) == 1.0


def test_score_reads_both_sheets(tmp_path) -> None:
    annotate.export(_records(2), {"llm": "t"}, out=tmp_path)
    for who in ("P1", "P2"):
        path = tmp_path / f"annotator_{who}.csv"
        with path.open() as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            r.update(label="supported", claims="2", unsupported_claims="0")
        rows[0].update(label="partly", unsupported_claims="1")
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=annotate.COLUMNS)
            w.writeheader()
            w.writerows(rows)
    res = annotate.score(out=tmp_path, report=tmp_path / "ann.md")
    assert res["n"] == 6 and 0 < res["pooled_rate"] < 20
    assert "Cohen's κ" in (tmp_path / "ann.md").read_text()


def test_score_rejects_unknown_labels(tmp_path) -> None:
    annotate.export(_records(1), {"llm": "t"}, out=tmp_path)
    for who in ("P1", "P2"):
        path = tmp_path / f"annotator_{who}.csv"
        text = path.read_text().replace(",,,,", ",yes,1,0,", 1)
        path.write_text(text)
    with pytest.raises(ValueError):
        annotate.score(out=tmp_path, report=tmp_path / "ann.md")


# ---------- benchmark ----------


def _row(**kw) -> dict:
    return {
        "model": "m",
        "num_ctx": 4096,
        "answer_p95_s": 9.0,
        "json_adherence_pct": 96.0,
        "gpu_fraction": 1.0,
        "first_pass_pct": 80.0,
        "attempt_p95_s": 7.2,
    } | kw


def test_bench_verdict_and_winner() -> None:
    assert llm_bench.verdict(_row(), 12)[0]
    ok, why = llm_bench.verdict(_row(answer_p95_s=15.0, gpu_fraction=0.6), 12)
    assert not ok and len(why) == 2
    assert not llm_bench.verdict({"model": "m", "num_ctx": 1, "error": "not pulled"}, 12)[0]
    rows = [
        _row(model="a", first_pass_pct=70.0),
        _row(model="b", first_pass_pct=90.0),
        _row(model="c", first_pass_pct=99.0, gpu_fraction=0.5),
    ]
    assert llm_bench.pick_winner(rows, 12)["model"] == "b"
    assert llm_bench.pick_winner([_row(json_adherence_pct=50.0)], 12) is None


def test_bench_report_recommends_a_pin(tmp_path) -> None:
    from greenhome.llm.settings import load_llm_settings

    out = tmp_path / "bench.md"
    win = llm_bench.write_report([_row(model="qwen:7b")], load_llm_settings(env={}), out)
    text = out.read_text()
    assert win["model"] == "qwen:7b" and "Pin `model: qwen:7b`" in text and "min_retry_s: 8" in text
