"""Draws docs/architecture.png (deliverable F), the static version of the main diagram in ARCHITECTURE.md.

Run: uv run --with pillow python docs/architecture_png.py
(Pillow is a one-off tool, not a project dependency.)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("architecture.png")
W, H = 2300, 1200
BG, INK, MUTED, LINE = "#ffffff", "#16201c", "#5a6a63", "#9aa8a2"
LANES = [  # title, owner, fill, edge
    ("Data foundation", "Part 1 · data_pipeline/", "#eef4fb", "#2f6db0"),
    ("Models", "Part 3 · training/, greenhome/ml/", "#f4eefb", "#6d4bb3"),
    ("Core engine", "Part 2 · greenhome/", "#eaf5ef", "#0d6a50"),
    ("LLM layer", "Part 4 · greenhome/llm/", "#fdf3e6", "#b8741a"),
    ("Product", "Part 5 · api/, web/, ui/", "#fbeceb", "#b03a2e"),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = [
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for base in [
        "/usr/share/fonts/liberation/",
        "/usr/share/fonts/TTF/",
        "/usr/share/fonts/truetype/dejavu/",
        "",
    ]:
        for n in names:
            try:
                return ImageFont.truetype(base + n, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


F_TITLE, F_LANE, F_OWN, F_BOX, F_SMALL = font(40, True), font(27, True), font(19), font(20, True), font(17)
F_TAG = font(15, True)
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

d.text((60, 36), "Green Home Score & Retrofit Engine: architecture", font=F_TITLE, fill=INK)
d.text(
    (60, 92),
    "Every number comes from a documented model or formula. The LLM only explains computed numbers, "
    "and a checker verifies each one.",
    font=F_SMALL,
    fill=MUTED,
)

lane_w, gap, top, bottom = 378, 72, 150, 975
lane_x = [60 + i * (lane_w + gap) for i in range(5)]
CHANNEL_Y = 1010  # cross-lane connectors that skip a lane run along here, below the lanes
for x, (title, owner, fill, edge) in zip(lane_x, LANES, strict=True):
    d.rounded_rectangle((x, top, x + lane_w, bottom), radius=18, fill=fill, outline=edge, width=3)
    d.text((x + 20, top + 16), title, font=F_LANE, fill=edge)
    d.text((x + 20, top + 52), owner, font=F_OWN, fill=MUTED)

boxes: dict[str, tuple[int, int, int, int]] = {}


def box(key: str, lane: int, y: int, title: str, lines: list[str], h: int = 0, store: bool = False) -> None:
    x0 = lane_x[lane] + 18
    x1 = x0 + lane_w - 36
    h = h or 46 + 24 * len(lines)
    edge = LANES[lane][3]
    if store:  # data store: double top line
        d.rounded_rectangle((x0, y, x1, y + h), radius=10, fill="#ffffff", outline=edge, width=2)
        d.line((x0 + 10, y + 8, x1 - 10, y + 8), fill=edge, width=2)
    else:
        d.rounded_rectangle((x0, y, x1, y + h), radius=10, fill="#ffffff", outline=edge, width=2)
    d.text((x0 + 14, y + 12), title, font=F_BOX, fill=INK)
    for i, line in enumerate(lines):
        d.text((x0 + 14, y + 42 + 24 * i), line, font=F_SMALL, fill=MUTED)
    boxes[key] = (x0, y, x1, y + h)


def arrow(a: str, b: str, label: str = "", side: str = "h", dashed: bool = False) -> None:
    ax0, ay0, ax1, ay1 = boxes[a]
    bx0, by0, bx1, by1 = boxes[b]
    if side == "h":
        p, q = (ax1, (ay0 + ay1) // 2), (bx0, (by0 + by1) // 2)
    else:  # vertical, a above b
        p, q = ((ax0 + ax1) // 2, ay1), ((bx0 + bx1) // 2, by0)
    if dashed:
        n = 14
        for i in range(0, n, 2):
            t0, t1 = i / n, (i + 1) / n
            d.line(
                (
                    p[0] + (q[0] - p[0]) * t0,
                    p[1] + (q[1] - p[1]) * t0,
                    p[0] + (q[0] - p[0]) * t1,
                    p[1] + (q[1] - p[1]) * t1,
                ),
                fill=LINE,
                width=3,
            )
    else:
        d.line((p, q), fill=LINE, width=3)
    import math

    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    for s in (-0.45, 0.45):
        d.line((q, (q[0] - 16 * math.cos(ang + s), q[1] - 16 * math.sin(ang + s))), fill=LINE, width=3)
    if label:
        mx, my = (p[0] + q[0]) // 2, (p[1] + q[1]) // 2
        tw = d.textlength(label, font=F_SMALL)
        d.rectangle((mx - tw / 2 - 4, my - 22, mx + tw / 2 + 4, my - 2), fill=BG)
        d.text((mx - tw / 2, my - 22), label, font=F_SMALL, fill=MUTED)


def gutter(left_lane: int, offset: int = 0) -> int:
    """x in the gap to the right of `left_lane`."""
    return lane_x[left_lane] + lane_w + gap // 2 + offset


def head(p: tuple[float, float], q: tuple[float, float]) -> None:
    import math

    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    for s_ in (-0.45, 0.45):
        d.line((q, (q[0] - 15 * math.cos(ang + s_), q[1] - 15 * math.sin(ang + s_))), fill=LINE, width=3)


def tag(x: float, y: float, text: str) -> None:
    tw = d.textlength(text, font=F_TAG)
    d.rounded_rectangle(
        (x - tw / 2 - 6, y - 11, x + tw / 2 + 6, y + 11), radius=6, fill="#ffffff", outline=LINE
    )
    d.text((x - tw / 2, y - 9), text, font=F_TAG, fill=INK)


def route(points: list[tuple[float, float]], label: str = "", at: int = 0) -> None:
    """Right-angled connector through gutters / the bottom channel; arrowhead at the last point."""
    d.line(points, fill=LINE, width=3, joint="curve")
    head(points[-2], points[-1])
    if label:
        (x0, y0), (x1, y1) = points[at], points[at + 1]
        tag((x0 + x1) / 2, (y0 + y1) / 2, label)


def mid_y(k: str) -> int:
    return (boxes[k][1] + boxes[k][3]) // 2


# Part 1
box(
    "raw",
    0,
    245,
    "Public data (real)",
    [
        "EPC certificates + recommendations",
        "Land Registry sales · UK HPI",
        "NEED · DESNZ factors · Met Office",
    ],
    store=True,
)
box("ing", 0, 420, "Ingest + parse", ["EPC text → contract enums", "sales joined by address"])
box("syn", 0, 545, "Synthetic metering", ["monthly energy, calibrated to NEED", "documented missingness"])
box("sim", 0, 670, "Retrofit simulator", ["hidden household factors", "energy labels per package"])
box(
    "proc",
    0,
    795,
    "Processed data + config",
    ["parquet: homes, labels, splits", "catalogue · emission factors", "imputation · intensity bounds"],
    store=True,
)
# Part 3
box("feat", 1, 245, "greenhome.ml.features", ["the one feature builder,", "training and inference"])
box(
    "train",
    1,
    380,
    "Training (LightGBM)",
    [
        "M4 rating: 2.9M real EPCs",
        "M1 energy: simulator labels",
        "M2 recommender: assessor labels",
        "M3 value: 618k real sales",
    ],
)
box(
    "art",
    1,
    575,
    "Model artefacts",
    ["model.txt · features.json", "manifest (versions, metrics)"],
    store=True,
)
box("reg", 1, 700, "registry.load_models()", ["implements P2's protocols", "loaded once at start-up"])
# Part 2
box(
    "con",
    2,
    245,
    "contracts.py  ·  format.py",
    ["pydantic models, contract 1.1.0", "the only number formatter"],
)
box("val", 2, 370, "Validate + annualise", ["seasonal annualisation", "imputation · conflict flags"])
box(
    "sco",
    2,
    495,
    "Score · issues · feasibility",
    ["fixed weights, score range", "deterministic rules + reasons"],
)
box(
    "eng",
    2,
    620,
    "Engine",
    ["analyse · run_scenario · portfolio", "savings per fuel · carbon", "value range · score after · diff"],
)
# Part 4
box("rt", 3, 245, "Router + what-if parser", ["rules first,", "LLM JSON as fallback"])
box("facts", 3, 370, "Fact sheet", ["numbers pre-formatted", "exactly as the screens show"])
box("llm", 3, 495, "LLM: gpt-oss-120b (Groq)", ["explains FACTS only", "25 s budget per answer"])
box("chk", 3, 620, "Number checker", ["numbers · money claims", "promises · increase-as-saving"])
box("tpl", 3, 745, "Template answer", ["if the check fails twice", "or the LLM is off"])
# Part 5
box(
    "api",
    4,
    370,
    "FastAPI  /v1/*",
    ["analyse · scenario · diff", "explain · chat · portfolio", "methodology · health"],
)
box("cache", 4, 545, "Result cache", ["LRU by analysis_id"], store=True)
box(
    "ui",
    4,
    660,
    "Web app (React, login)",
    [
        "home form ('Not sure' = null)",
        "score · issues · recommendations",
        "savings · value · what-if · portfolio",
    ],
)

for up, down in [
    ("raw", "ing"),
    ("ing", "syn"),
    ("syn", "sim"),
    ("sim", "proc"),
    ("feat", "train"),
    ("train", "art"),
    ("art", "reg"),
    ("val", "sco"),
    ("sco", "eng"),
    ("facts", "llm"),
    ("llm", "chk"),
    ("chk", "tpl"),
    ("api", "cache"),
    ("cache", "ui"),
]:
    arrow(up, down, side="v")

R = {k: v for k, v in boxes.items()}
# P1 processed data -> P3 training (adjacent lanes, gutter 0|1)
g = gutter(0)
route(
    [(R["proc"][2], mid_y("proc")), (g, mid_y("proc")), (g, mid_y("train")), (R["train"][0], mid_y("train"))],
    "labels, splits",
    at=1,
)
# P1 config -> P2 validation (skips P3: bottom channel, then gutter 1|2)
g = gutter(1, -12)
px = (R["proc"][0] + R["proc"][2]) // 2
route(
    [(px, R["proc"][3]), (px, CHANNEL_Y), (g, CHANNEL_Y), (g, mid_y("val")), (R["val"][0], mid_y("val"))],
    "config",
    at=1,
)
# P3 registry -> P2 engine (gutter 1|2)
g = gutter(1, 12)
route(
    [(R["reg"][2], mid_y("reg")), (g, mid_y("reg")), (g, mid_y("eng")), (R["eng"][0], mid_y("eng"))],
    "predictions",
    at=1,
)
# P4 router -> P2 engine (gutter 2|3, pointing left)
g = gutter(2, 12)
route(
    [(R["rt"][0], mid_y("rt")), (g, mid_y("rt")), (g, mid_y("eng") + 20), (R["eng"][2], mid_y("eng") + 20)],
    "Scenario",
    at=1,
)
# P2 engine -> P5 API (skips P4: bottom channel, then gutter 3|4)
g = gutter(3, -14)
ex = (R["eng"][0] + R["eng"][2]) // 2
route(
    [
        (ex, R["eng"][3]),
        (ex, CHANNEL_Y + 18),
        (g, CHANNEL_Y + 18),
        (g, mid_y("api") + 14),
        (R["api"][0], mid_y("api") + 14),
    ],
    "AnalysisResult",
    at=1,
)
# P5 API -> P4 fact sheet (gutter 3|4, pointing left)
g = gutter(3, 0)
route(
    [
        (R["api"][0], mid_y("api") - 18),
        (g, mid_y("api") - 18),
        (g, mid_y("facts")),
        (R["facts"][2], mid_y("facts")),
    ]
)
# P4 checker -> P5 dashboard (gutter 3|4)
g = gutter(3, 14)
route([(R["chk"][2], mid_y("chk")), (g, mid_y("chk")), (g, mid_y("ui")), (R["ui"][0], mid_y("ui"))])
tag(gutter(3), (mid_y("chk") + mid_y("ui")) // 2 + 8, "checked text")

d.text(
    (60, 1095),
    "Units: kWh/year, kg CO2e/year, GBP. Savings are positive for a reduction; increases are shown "
    "as increases. Unknown answers are null, never zero.",
    font=F_SMALL,
    fill=MUTED,
)
d.text(
    (60, 1125),
    "Runs on one laptop: browser → FastAPI :8000 (web app + API) → engine + models; LLM hosted on Groq "
    "(sees only computed facts). No personal data. Streamlit :8501 optional.",
    font=F_SMALL,
    fill=MUTED,
)
img.save(OUT, optimize=True)
print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
