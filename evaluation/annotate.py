"""Human annotation (README P4.6): export 40 answers for two annotators, then score their labels.

- `export(records, info)` (called by eval_llm): writes evaluation/annotation/RESPONSES.md (each answer with
  the fact sheet it was written from, split into numbered sentences), responses.json, and one CSV per
  annotator with the SAME sentences in a DIFFERENT shuffled order.
- `uv run python -m evaluation.annotate score`: reads both filled-in CSVs and writes reports/llm_annotation.md
  (unsupported claim rate per annotator and pooled, Cohen's κ on the sentence labels).

Rubric: evaluation/annotation/RUBRIC.md. Message for P1/P2: evaluation/annotation/MESSAGE.md.
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "evaluation" / "annotation"
ANNOTATORS = {"P1": 1, "P2": 2}  # annotator → shuffle seed
LABELS = ("supported", "partly", "unsupported", "not_a_claim")
COLUMNS = [
    "row",
    "response_id",
    "sentence_id",
    "sentence",
    "label",
    "claims",
    "unsupported_claims",
    "comment",
]
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9£\-])|\n+")


def sentences(text: str) -> list[str]:
    return [s.strip(" -") for s in _SPLIT.split(text) if s.strip(" -")]


def export(records: list[dict], info: dict, out: Path = DIR) -> None:
    out.mkdir(parents=True, exist_ok=True)
    responses, rows = [], []
    md = [
        "# Responses to annotate",
        "",
        f"Model: {info.get('llm')} · run {info.get('date')} on {info.get('host')} · "
        f"commit {info.get('commit')}",
        "",
        "Label each sentence in your own CSV (see RUBRIC.md). "
        "Do not discuss labels with the other annotator.",
        "",
    ]
    for n, r in enumerate(records, 1):
        rid = f"R{n:02d}"
        sents = sentences(r["answer"])
        responses.append(
            {
                "response_id": rid,
                "item_id": r["id"],
                "category": r["category"],
                "llm_written": r["fallback_reason"] is None,
                "model": info.get("llm"),
                "sentences": sents,
            }
        )
        md += [
            f"## {rid}",
            "",
            f"**Question:** {r['message']}",
            "",
            "**FACTS the answer had to use:**",
            "",
            "```",
            r.get("facts") or "(no numeric facts)",
            "```",
            "",
        ]
        if r.get("notes"):
            md += ["**DATA_NOTES:** " + " ".join(r["notes"]), ""]
        md += ["**Answer, by sentence:**", ""]
        for i, s in enumerate(sents, 1):
            md.append(f"- `{rid}.{i}` {s}")
            rows.append({"response_id": rid, "sentence_id": f"{rid}.{i}", "sentence": s})
        md.append("")
    (out / "RESPONSES.md").write_text("\n".join(md))
    (out / "responses.json").write_text(json.dumps(responses, indent=1, ensure_ascii=False))
    for who, seed in ANNOTATORS.items():
        order = rows[:]
        random.Random(seed).shuffle(order)
        with (out / f"annotator_{who}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for i, row in enumerate(order, 1):
                w.writerow(
                    {"row": i, **row, "label": "", "claims": "", "unsupported_claims": "", "comment": ""}
                )


def _read(path: Path) -> dict[str, dict]:
    with path.open(newline="") as f:
        return {r["sentence_id"]: r for r in csv.DictReader(f)}


def cohens_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's κ for two raters over the same items."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    cats = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def claim_rate(rows: list[dict]) -> tuple[int, int, float | None]:
    claims = sum(int(r["claims"] or 0) for r in rows)
    bad = sum(int(r["unsupported_claims"] or 0) for r in rows)
    return bad, claims, (100.0 * bad / claims if claims else None)


def score(out: Path = DIR, report: Path = ROOT / "reports" / "llm_annotation.md") -> dict:
    sheets = {who: _read(out / f"annotator_{who}.csv") for who in ANNOTATORS}
    ids = sorted(set.intersection(*(set(s) for s in sheets.values())))
    labelled = [i for i in ids if all(sheets[w][i]["label"].strip() for w in sheets)]
    bad_labels = [
        (w, i, sheets[w][i]["label"])
        for w in sheets
        for i in labelled
        if sheets[w][i]["label"].strip() not in LABELS
    ]
    if bad_labels:
        raise ValueError(f"unknown labels (use {LABELS}): {bad_labels[:5]}")
    a, b = ([sheets[w][i]["label"].strip() for i in labelled] for w in ANNOTATORS)
    kappa = cohens_kappa(a, b)
    per = {w: claim_rate([sheets[w][i] for i in labelled]) for w in sheets}
    pooled_bad = sum(v[0] for v in per.values())
    pooled_claims = sum(v[1] for v in per.values())
    pooled = 100.0 * pooled_bad / pooled_claims if pooled_claims else None
    lines = [
        "# Human annotation of LLM answers",
        "",
        f"{len(labelled)} sentences labelled by both annotators (of {len(ids)}). Rubric: "
        "`evaluation/annotation/RUBRIC.md`.",
        "",
        "| | Unsupported claims | Claims | Rate |",
        "|---|---|---|---|",
    ]
    for w, (bad, claims, rate) in per.items():
        lines.append(f"| {w} | {bad} | {claims} | {'—' if rate is None else f'{rate:.1f}%'} |")
    lines += [
        f"| **Pooled** | {pooled_bad} | {pooled_claims} | {'—' if pooled is None else f'{pooled:.1f}%'} |",
        "",
        f"Cohen's κ on sentence labels: **{'—' if kappa is None else f'{kappa:.2f}'}** "
        "(target unsupported rate < 5%).",
        "",
    ]
    report.write_text("\n".join(lines))
    return {"kappa": kappa, "pooled_rate": pooled, "n": len(labelled)}


if __name__ == "__main__":
    if sys.argv[1:] == ["score"]:
        print(score())
    else:
        print("usage: python -m evaluation.annotate score   (export runs from evaluation.eval_llm)")
