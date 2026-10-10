"""Plain-English text for every contract enum value and every flag / issue / reason code.

Owned by P5. One copy shared by the UI (ui/labels.py re-exports it) and the LLM layer (P4), so the screens
and the explanations always use the same words. Display only: never send a label back to the API.

"Not sure" is not an enum member: the UI shows NOT_SURE and sends None.
Flags and issues also carry their own `message` from the engine; these are short titles for chips and facts.
A new enum value or code needs an entry here (tests/unit/p5/test_core_labels.py fails otherwise).
"""

NOT_SURE = "Not sure"

LABELS: dict[str, dict[str, str]] = {
    "PropertyType": {
        "detached": "Detached house",
        "semi_detached": "Semi-detached house",
        "terraced": "Terraced house",
        "flat": "Flat",
        "bungalow": "Bungalow",
        "maisonette": "Maisonette",
    },
    "AgeBand": {
        "pre_1900": "Before 1900",
        "1900_1929": "1900–1929",
        "1930_1949": "1930–1949",
        "1950_1966": "1950–1966",
        "1967_1982": "1967–1982",
        "1983_1995": "1983–1995",
        "1996_2006": "1996–2006",
        "2007_onwards": "2007 or later",
    },
    "Region": {
        "north_east": "North East",
        "north_west": "North West",
        "yorkshire_humber": "Yorkshire and the Humber",
        "east_midlands": "East Midlands",
        "west_midlands": "West Midlands",
        "east_of_england": "East of England",
        "london": "London",
        "south_east": "South East",
        "south_west": "South West",
        "wales": "Wales",
    },
    "EnergyRating": {r: r for r in "ABCDEFG"},
    "RoofType": {
        "pitched_loft": "Pitched roof with a loft",
        "flat_roof": "Flat roof",
        "room_in_roof": "Room in the roof",
        "dwelling_above": "No roof – another home above",
    },
    "RoofInsulation": {
        "none": "None",
        "low": "A bit (under 10 cm)",
        "medium": "Some (10–20 cm)",
        "full": "Thick (20 cm or more)",
    },
    "WallType": {
        "cavity": "Cavity walls",
        "solid": "Solid walls (brick or stone)",
        "timber_or_system": "Timber frame or system-built",
    },
    "WallInsulation": {
        "none": "None",
        "partial": "Partly insulated",
        "full": "Fully insulated (incl. filled cavity)",
    },
    "Glazing": {
        "single": "Single glazing",
        "partial_double": "Some double glazing",
        "secondary": "Secondary glazing",
        "double": "Double glazing",
        "triple": "Triple glazing",
    },
    "HeatingSystem": {
        "heat_pump": "Heat pump",
        "gas_boiler_condensing": "Modern gas boiler (condensing)",
        "gas_boiler_old": "Older gas boiler",
        "electric_storage": "Electric storage heaters",
        "electric_direct": "Electric heaters (direct)",
        "other_fuel_boiler": "Oil, LPG or solid-fuel boiler",
    },
    "MainFuel": {
        "mains_gas": "Mains gas",
        "electricity": "Electricity",
        "other": "Other (oil, LPG, solid fuel…)",
    },
    "Renewables": {
        "none": "None",
        "solar_thermal": "Solar water heating",
        "solar_pv": "Solar panels (electricity)",
        "solar_pv_battery": "Solar panels with a battery",
    },
    "SmartControls": {
        "none": "No controls",
        "timer_only": "Timer only",
        "programmer_thermostat": "Programmer and room thermostat",
        "programmer_thermostat_trvs": "Programmer, thermostat and radiator valves",
        "smart_thermostat": "Smart thermostat",
        "smart_zoned": "Smart zoned control",
    },
    "Retrofit": {
        "loft_insulation": "Loft insulation",
        "cavity_wall_insulation": "Cavity wall insulation",
        "solid_wall_insulation": "Solid wall insulation",
        "double_glazing": "Double glazing",
        "air_source_heat_pump": "Air source heat pump",
        "solar_pv": "Solar panels",
        "smart_thermostat": "Smart thermostat",
    },
    "Feasibility": {
        "feasible": "Feasible",
        "needs_survey": "Needs a survey",
        "infeasible": "Not suitable",
    },
    "Suitability": {"high": "High", "medium": "Medium", "low": "Low"},
    "ScoreClass": {
        "highly_efficient": "Highly efficient",
        "good": "Good",
        "moderate": "Moderate",
        "poor": "Poor",
        "very_poor": "Very poor",
    },
    "Provenance": {
        "user": "You told us",
        "example": "From the example home",
        "imputed": "Estimated by a model",
        "assumed": "Assumed (typical for similar homes)",
        "derived": "Calculated from your answers",
    },
    "FlagSeverity": {"info": "Note", "warning": "Warning", "error": "Problem"},
    "Split": {"train": "Training", "val": "Validation", "test": "Test"},
}

YES_NO = {"yes": "Yes", "no": "No"}  # listed_or_conservation, outdoor_space

SCORE_COMPONENT: dict[str, str] = {
    "energy_efficiency": "Energy efficiency (EPC rating)",
    "consumption_intensity": "Energy use per m²",
    "insulation": "Insulation",
    "heating": "Heating system",
    "glazing": "Windows and glazing",
    "renewables": "Renewable energy",
    "smart_controls": "Smart energy management",
}

# DataFlag.code (README P2.2 + P2.5)
FLAG_TEXT: dict[str, str] = {
    "MISSING_FIELD": "Answer missing",
    "IMPUTED_FIELD": "Estimated value used",
    "LOW_COVERAGE_ANNUALISATION": "Some months missing – yearly use estimated",
    "INSUFFICIENT_MONTHLY_DATA": "Too few months of readings",
    "CONFLICT_ANNUAL_VS_MONTHLY": "Yearly total and monthly readings disagree",
    "CONFLICT_HEATING_VS_GAS": "Heating type and gas use don't match",
    "CONFLICT_RATING_VS_USAGE": "EPC rating and actual use disagree",
    "CONFLICT_AGE_VS_INSULATION": "Insulation unusual for the home's age",
    "CONFLICT_ROOF_VS_TYPE": "Roof answer doesn't fit the property type",
    "OUTLIER_AREA_PER_BEDROOM": "Unusual floor area for the number of bedrooms",
    "OUTLIER_INTENSITY": "Unusual energy use per m²",
    "OUTLIER_VALUE": "Unusual property value",
    "ENERGY_FROM_TYPICAL_HOMES": "Energy use estimated from similar homes",
    "OUT_OF_SCOPE_FUEL": "Savings not available for this fuel",
    "INSUFFICIENT_INFO_SCORE": "Not enough information for a score",
    "INSUFFICIENT_INFO_SAVINGS": "Not enough information for savings",
    "INSUFFICIENT_INFO_VALUE": "Not enough information for a value estimate",
}

# Issue.code (README P2.6)
ISSUE_TEXT: dict[str, str] = {
    "HIGH_INTENSITY": "High energy use for a home this size",
    "LOW_RATING": "Low EPC rating",
    "POOR_ROOF_INSULATION": "Little or no roof insulation",
    "POOR_WALL_INSULATION": "Uninsulated walls",
    "SINGLE_GLAZING": "Single glazing",
    "OLD_HEATING": "Inefficient heating system",
    "NO_RENEWABLES": "No renewable generation",
    "NO_SMART_CONTROLS": "Basic or no heating controls",
}

# RetrofitRecommendation.reasons / RejectedRetrofit.reason (README P2.7)
REASON_TEXT: dict[str, str] = {
    "ALREADY_INSTALLED": "You already have this.",
    "NO_LOFT_DWELLING_ABOVE": "There's another home above, so there's no loft to insulate.",
    "FLAT_ROOF_INSULATION_DIFFERENT_MEASURE": "Flat roofs need a different kind of insulation.",
    "WRONG_WALL_TYPE": "This doesn't apply to your type of walls.",
    "LISTED_OR_CONSERVATION": (
        "Listed building or conservation area: permission or a different product may be needed."
    ),
    "NO_SUITABLE_ROOF": "No suitable roof for panels.",
    "NEEDS_OUTDOOR_SPACE_CHECK": "Needs a check that there's outdoor space for the unit.",
    "UNKNOWN_INPUT_SURVEY": "We don't know enough about your home – a survey would confirm it.",
    "INSULATE_FIRST": "Works best after insulating the home first.",
    "HIGH_COST_LOW_SAVING": "Expensive for the saving it gives.",
    "HIGH_SAVING": "Large estimated saving.",
    "QUICK_WIN_LOW_COST": "Low cost quick win.",
    "ELECTRICITY_RISES_GAS_FALLS": "Electricity use goes up while gas use goes down.",
    "ASSESSORS_OFTEN_RECOMMEND": "Energy assessors often recommend this for similar homes.",
    "CUSTOMER_EXCLUDED": "You said you don't want this.",
    "CUSTOMER_DECLINED_BEFORE": "You declined this before, so it's ranked lower.",
    "OVER_BUDGET": "Doesn't fit within your budget.",
    "OUT_OF_SCOPE_FUEL": "Savings can't be estimated for your heating fuel.",
}


def label(enum_name: str, value: str | None) -> str:
    """Label for an enum value; None → NOT_SURE; unknown value → the raw value (never crash the UI)."""
    if value is None:
        return NOT_SURE
    return LABELS.get(enum_name, {}).get(value, value)


def code_text(table: dict[str, str], code: str) -> str:
    return table.get(code, code)
