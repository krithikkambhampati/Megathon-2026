"""web/js/format.js must format every number exactly like greenhome/format.py (the web app's only formatter).

Runs the JS with Deno when it is installed; skipped otherwise (the Python side is covered by its own tests).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from greenhome import format as F

FORMAT_JS = Path(__file__).resolve().parents[3] / "web" / "js" / "format.js"
DENO = shutil.which("deno")

VALUES = [None, 0, 0.04, -0.04, 0.05, 0.15, 1, 4.5, 5, 9.99, 14.95, 29.5, -29.5, 99.95, 249, 250, 251, 1234.5,
          -1234.5, 4999, 5000, 12345.678, -12345.678, 249999, 250000, 1e6 + 0.5]
SINGLE = {  # JS name → Python function
    "fmtKwh": F.fmt_kwh, "fmtKwhSaving": F.fmt_kwh_saving, "fmtKg": F.fmt_kg, "fmtKgSaving": F.fmt_kg_saving,
    "fmtTonnes": F.fmt_tonnes, "fmtGbpValue": F.fmt_gbp_value, "fmtGbpCost": F.fmt_gbp_cost, "fmtPct": F.fmt_pct,
    "fmtPoints": F.fmt_points, "fmtIntensity": F.fmt_intensity, "fmtArea": F.fmt_area, "fmtScore": F.fmt_score,
    "fmtSap": F.fmt_sap,
}
UNITS = ["score", "sap", "kwh_per_year", "kg_per_year", "pct"]
RANGES = [(10, 20), (10.04, 10.01), (None, 5), (-3, 7.25)]


def _cases():
    cases, expected = [], []
    for name, fn in SINGLE.items():
        for v in VALUES:
            cases.append([name, [v]])
            expected.append(fn(v))
    for unit in UNITS:
        for v in VALUES:
            cases.append(["fmtDelta", [v, unit]])
            expected.append(F.fmt_delta(v, unit))
    for lo, hi in RANGES:
        cases.append(["fmtRange", [lo, hi]])
        expected.append(F.fmt_range(lo, hi))
    return cases, expected


@pytest.mark.skipif(DENO is None, reason="deno not installed")
def test_format_js_matches_format_py(tmp_path):
    cases, expected = _cases()
    script = tmp_path / "run.mjs"
    script.write_text(
        f"import * as F from {json.dumps(FORMAT_JS.as_uri())};\n"
        f"const cases = {json.dumps(cases)};\n"
        "console.log(JSON.stringify(cases.map(([n, a]) => F[n](...a))));\n"
    )
    out = subprocess.run([DENO, "run", "--quiet", "--allow-read", str(script)], capture_output=True, text=True,
                         timeout=60, check=True).stdout
    got = json.loads(out)
    mismatches = [(c, e, g) for c, e, g in zip(cases, expected, got, strict=True) if e != g]
    assert not mismatches, "\n".join(f"{c}: python {e!r} != js {g!r}" for c, e, g in mismatches[:20])
