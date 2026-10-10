"""Home catalogue for the web app's landing page: the demo homes as presentable listing cards.

Names follow estate-agent conventions (era + built form + feature), never internal labels. Scores come from
the engine (real models), computed once and cached for the life of the process.
"""

import logging
from pathlib import Path
from threading import Lock
from typing import Any

from greenhome.config import get_config
from greenhome.contracts import HomeInput
from greenhome.labels import label

log = logging.getLogger("greenhome.api")

# Curated display names for the committed demo homes (data/examples); others get a generated name.
NAMES: dict[str, tuple[str, str]] = {  # id → (name, one-line summary)
    "P10001": (
        "Post-war semi-detached house",
        "E-rated, single glazed and gas heated, with a lot of room to improve",
    ),
    "P347548": (
        "1930s semi-detached house",
        "Older gas boiler and single glazing in a classic inter-war semi",
    ),
    "P1014307": (
        "Modern detached family home",
        "A large, well-built house that still uses a lot of energy in total",
    ),
    "P1024619": ("Victorian conversion flat", "A one-bedroom flat with another home above it"),
    "P1001332": ("Inter-war terraced house", "Solid walls and gas heating; some winter meter readings are missing"),
    "P1011233": ("1970s purpose-built flat", "A good EPC rating, but energy use far above similar flats"),
    "P1033772": ("New-build bungalow with heat pump", "Already electric and well insulated"),
    "P1007007": ("1970s bungalow with solar panels", "Generates some of its own electricity"),
    "P1223173": ("Edwardian flat with storage heaters", "Electric storage heating and solid walls"),
    "P1122209": ("Victorian terraced house", "Solid brick walls and an older gas boiler"),
    "P1002021": ("Large 1970s detached house", "A five-bedroom family home with some gas readings missing"),
}
HIDDEN = {"P1000205_minimal"}  # too little information to make a useful catalogue card

_ERA = {
    "pre_1900": "Victorian",
    "1900_1929": "Edwardian",
    "1930_1949": "Inter-war",
    "1950_1966": "Post-war",
    "1967_1982": "1970s",
    "1983_1995": "1980s",
    "1996_2006": "Modern",
    "2007_onwards": "New-build",
}
_FORM = {
    "detached": "detached house",
    "semi_detached": "semi-detached house",
    "terraced": "terraced house",
    "flat": "flat",
    "bungalow": "bungalow",
    "maisonette": "maisonette",
}


def generated_name(home: HomeInput) -> str:
    era = _ERA.get(home.age_band or "", "")
    form = _FORM.get(home.property_type or "", "home")
    return f"{era} {form}".strip().capitalize() if era else form.capitalize()


def highlights(home: HomeInput) -> list[str]:
    """Short, factual feature tags for the card (at most three)."""
    tags = []
    if home.heating_system == "heat_pump":
        tags.append("Heat pump")
    elif home.heating_system == "electric_storage":
        tags.append("Storage heaters")
    elif home.heating_system == "gas_boiler_old":
        tags.append("Older gas boiler")
    if home.renewables in ("solar_pv", "solar_pv_battery"):
        tags.append("Solar panels")
    if home.wall_type == "solid" and home.wall_insulation in (None, "none"):
        tags.append("Solid walls")
    if home.glazing == "single":
        tags.append("Single glazing")
    if home.roof_type == "dwelling_above":
        tags.append("Home above")
    return tags[:3]


class Catalogue:
    """Cards for every demo home, analysed once by the engine (lazily, thread-safe)."""

    def __init__(self, examples_dir: Path | None = None) -> None:
        self.examples_dir = examples_dir or get_config().examples_dir
        self._cards: list[dict[str, Any]] | None = None
        self._lock = Lock()

    def homes(self) -> list[HomeInput]:
        out = []
        for path in sorted(self.examples_dir.glob("P*.json")):
            if path.stem in HIDDEN:
                continue
            out.append(HomeInput.model_validate_json(path.read_text("utf-8")))
        return out

    def cards(self, engine: Any) -> list[dict[str, Any]]:
        with self._lock:
            if self._cards is None:
                self._cards = [self._card(h, engine) for h in self.homes()]
                order = list(NAMES)  # curated order first (the reference home leads)
                self._cards.sort(
                    key=lambda c: (order.index(c["id"]) if c["id"] in order else len(order), c["id"])
                )
                log.info("catalogue ready: %d homes", len(self._cards))
            return self._cards

    def _card(self, home: HomeInput, engine: Any) -> dict[str, Any]:
        pid = home.property_id or ""
        name, summary = NAMES.get(pid, (generated_name(home), ""))
        r = engine.analyse(home)
        return {
            "id": pid,
            "name": name,
            "summary": summary,
            "reference": pid == "P10001",
            "location": label("Region", home.region) if home.region else None,
            "property_type": label("PropertyType", home.property_type) if home.property_type else None,
            "era": label("AgeBand", home.age_band) if home.age_band else None,
            "bedrooms": home.bedrooms,
            "floor_area_m2": home.floor_area_m2,
            "epc_rating": home.energy_rating,
            "heating": label("HeatingSystem", home.heating_system) if home.heating_system else None,
            "highlights": highlights(home),
            "score": r.score.score,
            "score_class": r.score.score_class,
            "score_after": r.score_after.score if r.score_after and r.score.status == "ok" else None,
            "improvement_potential_pct": r.savings.improvement_potential_pct,
        }
