"""Map raw EPC certificate fields (mostly free text) to the contract enums (BUILD_GUIDE section 7.2).

Design rules
  * Rules are case-insensitive regexes applied in a fixed priority order; first match wins.
  * Anything we cannot map confidently becomes None (= unknown). We never guess.
  * Each parse_* function takes a DataFrame of raw EPC columns and returns a Series of enum
    strings (or None), so the whole table is parsed vectorised.
  * Welsh-language descriptions (Cardiff etc.) are covered for the common phrases.
  * unmatched_report() lists the most frequent unmapped raw strings, so coverage can be
    iterated until >= 95% per field.
"""

from __future__ import annotations

import re
import warnings

import pandas as pd

# NB: "None" is NOT a null marker: in MAINHEATCONT_DESCRIPTION it means "no heating controls".
NULLS = {"", "NO DATA!", "INVALID!", "NODATA!", "N/A", "NAN", "NOT DEFINED", "NOT RECORDED"}
SYSTEM_START = (
    r"Boiler|Room heaters|Electric (?:storage|underfloor|ceiling|heaters|boiler)|"
    r"Air source|Ground source|Water source|Warm air|Community|"
    r"No system|Portable|Micro|Exhaust|Heat pump|Solar|Bwyler|Gwresogyddion|Pwmp"
)


def _clean(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    return s.mask(s.str.upper().isin(NULLS))


def _rules(s: pd.Series, rules: list[tuple[str, str | None]]) -> pd.Series:
    """Apply (regex, value) rules in order; first match wins; no match -> None."""
    s = _clean(s).fillna("")
    out = pd.Series([None] * len(s), index=s.index, dtype="object")
    done = pd.Series(False, index=s.index)
    for pat, val in rules:
        with warnings.catch_warnings():  # groups in patterns are for alternation only
            warnings.simplefilter("ignore", UserWarning)
            hit = s.str.contains(pat, flags=re.IGNORECASE, regex=True) & ~done
        out[hit] = val
        done |= hit
    return out


def _first_system(s: pd.Series) -> pd.Series:
    """EPC lists several systems separated by ', '; keep the first (main) one. Split only where a new
    system name starts, so 'Room heaters, LPG' or 'Boiler and radiators, mains gas' stay whole."""
    return _clean(s).str.split(rf",\s(?=(?:{SYSTEM_START}))", n=1, regex=True).str[0]


# ---------------------------------------------------------------- property type / age / fuel


def parse_property_type(df: pd.DataFrame) -> pd.Series:
    pt = _clean(df["PROPERTY_TYPE"]).str.lower().fillna("")
    bf = _clean(df["BUILT_FORM"]).str.lower().fillna("")
    out = pd.Series([None] * len(df), index=df.index, dtype="object")
    out[pt.eq("flat")] = "flat"
    out[pt.eq("maisonette")] = "maisonette"
    out[pt.eq("bungalow")] = "bungalow"
    house = pt.eq("house")
    out[house & bf.eq("detached")] = "detached"
    out[house & bf.eq("semi-detached")] = "semi_detached"
    out[house & bf.str.contains("terrace")] = "terraced"
    return out  # park homes and houses with unknown built form -> None


AGE_RULES = [
    (r"before 1900", "pre_1900"),
    (r"1900\s*-\s*1929", "1900_1929"),
    (r"1930\s*-\s*1949", "1930_1949"),
    (r"1950\s*-\s*1966", "1950_1966"),
    (r"1967\s*-\s*1975|1976\s*-\s*1982", "1967_1982"),
    (r"1983\s*-\s*1990|1991\s*-\s*1995", "1983_1995"),
    (r"1996\s*-\s*2002|2003\s*-\s*2006", "1996_2006"),
    (r"2007\s*-\s*2011|2007 onwards|2012 onwards|2012\s*-\s*2021|2022 onwards", "2007_onwards"),
]


def parse_age_band(df: pd.DataFrame) -> pd.Series:
    raw = _clean(df["CONSTRUCTION_AGE_BAND"])
    out = _rules(raw, AGE_RULES)
    # some new-build certificates store a plain year instead of a band
    year = pd.to_numeric(raw.str.extract(r"^\s*(\d{4})\s*$")[0], errors="coerce")
    bins = [
        (0, 1899, "pre_1900"),
        (1900, 1929, "1900_1929"),
        (1930, 1949, "1930_1949"),
        (1950, 1966, "1950_1966"),
        (1967, 1982, "1967_1982"),
        (1983, 1995, "1983_1995"),
        (1996, 2006, "1996_2006"),
        (2007, 2100, "2007_onwards"),
    ]
    for lo, hi, band in bins:
        out[out.isna() & year.between(lo, hi)] = band
    return out


FUEL_RULES = [
    (r"(?<!not )community", "other"),  # "(not community)" is an individual system
    (r"mains gas|^gas:|nwy prif", "mains_gas"),
    (r"electric|trydan", "electricity"),
    (
        r"oil|lpg|bottled|coal|anthracite|wood|pellet|biomass|biogas|biodiesel|b30k|"
        r"dual fuel|smokeless|peat|bioethanol",
        "other",
    ),
    (r"no heating/hot-water system", "other"),
]


def parse_main_fuel(df: pd.DataFrame) -> pd.Series:
    return _rules(df["MAIN_FUEL"], FUEL_RULES)


# ---------------------------------------------------------------- roof


def parse_roof(
    df: pd.DataFrame, age_band: pd.Series, property_type: pd.Series
) -> tuple[pd.Series, pd.Series]:
    raw = _clean(df["ROOF_DESCRIPTION"]).fillna("")
    low = raw.str.lower()
    roof_type = _rules(
        raw,
        [
            (
                r"another dwelling above|other premises above|annedd arall uwchben|eiddo arall uwchben",
                "dwelling_above",
            ),
            (r"roof room|ystafell\(oedd\) to", "room_in_roof"),
            (r"^flat|^to gwastad|^gwastad", "flat_roof"),
            (r"^pitched|loft|thatch|ar oleddf|llofft", "pitched_loft"),
        ],
    )
    # SAP new-build certificates give only a U-value; for houses/bungalows that is a pitched roof
    u_only = low.str.contains("average thermal transmittance|trawsyriannedd thermol")
    house = property_type.isin(["detached", "semi_detached", "terraced", "bungalow"])
    roof_type[roof_type.isna() & u_only & house] = "pitched_loft"
    # flats on a non-top floor with no roof description -> dwelling above
    top = _clean(df.get("FLAT_TOP_STOREY", pd.Series(index=df.index, dtype="string"))).str.upper()
    is_flat = property_type.isin(["flat", "maisonette"])
    roof_type[roof_type.isna() & is_flat & top.eq("N")] = "dwelling_above"

    # insulation level
    mm = pd.to_numeric(low.str.extract(r"(\d+)\s*\+?\s*mm")[0], errors="coerce")
    u = pd.to_numeric(low.str.extract(r"average thermal transmittance\s*([0-9.]+)")[0], errors="coerce")
    ins = pd.Series([None] * len(df), index=df.index, dtype="object")
    ins[mm.notna() & (mm < 100)] = "low"
    ins[mm.notna() & mm.between(100, 199)] = "medium"
    ins[mm.notna() & (mm >= 200)] = "full"
    ins[ins.isna() & u.notna() & (u <= 0.20)] = "full"  # new-build U-value style
    ins[ins.isna() & u.notna() & u.between(0.2001, 0.35)] = "medium"
    ins[ins.isna() & u.notna() & (u > 0.35)] = "low"
    ins[ins.isna() & low.str.contains(r"no insulation|dim inswleiddio")] = "none"
    ins[ins.isna() & low.str.contains(r"limited insulation|inswleiddio cyfyngedig")] = "low"
    insulated = ins.isna() & low.str.contains(r"insulated|inswleiddiwyd|wedi'i inswleiddio|ceiling insulated")
    recent = age_band.isin(["1996_2006", "2007_onwards"])
    ins[insulated & recent] = "full"
    ins[insulated & ~recent] = "medium"  # "insulated (assumed)" on older homes: assume partial thickness
    ins[roof_type.eq("dwelling_above")] = None  # not applicable; roof excluded from score
    return roof_type, ins


# ---------------------------------------------------------------- walls


def parse_walls(df: pd.DataFrame, age_band: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = _clean(df["WALLS_DESCRIPTION"]).fillna("")
    low = raw.str.lower()
    wall_type = _rules(
        raw,
        [
            (r"cavity|ceudod", "cavity"),
            (
                r"solid brick|sandstone|limestone|granite|whinstone|cob|stone|"
                r"brics solet|tywodfaen|calchfaen|gwenithfaen",
                "solid",
            ),
            (r"timber|system built|park home|ffrâm bren|wedi'i adeiladu drwy system", "timber_or_system"),
        ],
    )
    ins = pd.Series([None] * len(df), index=df.index, dtype="object")
    full = low.str.contains(
        r"filled cavity|with internal insulation|with external insulation|additional insulation|"
        r"ceudod wedi'i lenwi|inswleiddio mewnol|inswleiddio allanol"
    )
    partial = low.str.contains(r"partial insulation|inswleiddio rhannol")
    none_ = low.str.contains(r"no insulation|dim inswleiddio")
    insulated = low.str.contains(r"insulated|wedi'i inswleiddio|inswleiddiwyd")
    ins[full] = "full"
    ins[ins.isna() & partial] = "partial"
    ins[ins.isna() & none_] = "none"
    ins[ins.isna() & insulated] = "full"
    # "as built" with no further qualifier: building regs required wall insulation from ~1983
    as_built = ins.isna() & low.str.contains(r"as built|fel y'i hadeiladwyd")
    newer = age_band.isin(["1983_1995", "1996_2006", "2007_onwards"])
    ins[as_built & newer] = "full"
    ins[as_built & age_band.notna() & ~newer] = "none"
    # SAP new-build style: "Average thermal transmittance 0.28 W/m-K"
    u = pd.to_numeric(low.str.extract(r"average thermal transmittance\s*([0-9.]+)")[0], errors="coerce")
    ins[ins.isna() & u.notna() & (u <= 0.45)] = "full"
    ins[ins.isna() & u.notna() & u.between(0.4501, 1.0)] = "partial"
    ins[ins.isna() & u.notna() & (u > 1.0)] = "none"
    return wall_type, ins


# ---------------------------------------------------------------- glazing


def parse_glazing(df: pd.DataFrame) -> pd.Series:
    win = _clean(df["WINDOWS_DESCRIPTION"]).fillna("")
    out = _rules(
        win,
        [
            (r"triple|gwydr triphlyg", "triple"),
            (r"secondary|eilaidd", "secondary"),
            (r"single|gwydr sengl", "single"),
            (r"partial|some|mostly|rhannol|peth", "partial_double"),
            (
                r"fully double|full double|double glaz|multiple glazing throughout|high performance|"
                r"gwydr dwbl llawn|gwydrau lluosog ym mhob",
                "double",
            ),
        ],
    )
    # fall back to GLAZED_TYPE when WINDOWS_DESCRIPTION is blank
    gt = _rules(
        df["GLAZED_TYPE"],
        [
            (r"triple", "triple"),
            (r"secondary", "secondary"),
            (r"single", "single"),
            (r"double", "double"),
        ],
    )
    out = out.where(out.notna(), gt)
    # "mostly double" with >= 80% multi-glazed counts as double
    prop = pd.to_numeric(df.get("MULTI_GLAZE_PROPORTION"), errors="coerce")
    out[(out == "partial_double") & (prop >= 80)] = "double"
    out[(out == "double") & (prop < 80) & win.str.lower().str.contains("partial|some|mostly")] = (
        "partial_double"
    )
    return out


# ---------------------------------------------------------------- heating & controls


def parse_heating(df: pd.DataFrame, main_fuel: pd.Series) -> pd.Series:
    main = _first_system(df["MAINHEAT_DESCRIPTION"]).fillna("")
    low = main.str.lower()
    eff = _clean(df["MAINHEAT_ENERGY_EFF"]).str.lower().fillna("")
    out = pd.Series([None] * len(df), index=df.index, dtype="object")

    community = low.str.contains(r"(?<!not )community|cymunedol")
    hp = low.str.contains(r"heat pump|pwmp gwres")
    storage = low.str.contains(r"storage heater|electricaire|gwresogyddion stôr|gwresogyddion storio")
    elec_direct = low.str.contains(
        r"room heaters, electric|electric underfloor|electric ceiling|"
        r"electric heaters assumed|portable electric|boiler and radiators, electric|"
        r"electric boiler|warm air, electric|gwresogyddion ystafell, trydan|"
        r"no system present|room heaters, radiators, electric"
    )
    gas = low.str.contains(r"mains gas|nwy prif")
    other_fuel = low.str.contains(
        r"oil|lpg|bottled gas|coal|anthracite|wood|pellet|dual fuel|biomass|"
        r"smokeless|peat|olew"
    )
    boilerish = low.str.contains(r"boiler|bwyler|warm air|room heaters|micro-cogeneration")

    out[hp] = "heat_pump"
    out[out.isna() & storage] = "electric_storage"
    out[out.isna() & elec_direct] = "electric_direct"
    gas_sys = out.isna() & gas & boilerish
    good = eff.isin(["good", "very good", "da", "da iawn"])
    # condensing proxy: RdSAP rates condensing gas boilers Good/Very Good; non-condensing Average/Poor.
    # Gas room heaters / warm air are inefficient -> grouped with old boilers (documented).
    out[gas_sys & good & low.str.contains("boiler|bwyler")] = "gas_boiler_condensing"
    out[gas_sys & out.isna()] = "gas_boiler_old"
    out[out.isna() & other_fuel & boilerish] = "other_fuel_boiler"
    out[community] = None  # community heating: out of scope (dropped by the scope filter)
    return out


CONTROL_RULES = [
    (r"time and temperature zone control|rheolaeth parthau amser a thymheredd", "smart_zoned"),
    (r"smart|clyfar", "smart_thermostat"),
    (r"no room thermostat", "timer_only"),
    (
        r"programmer.*room thermostat.*trv|programmer.*trv.*room thermostat|"
        r"rhaglennydd.*thermostat ystafell.*(trv|falfiau)",
        "programmer_thermostat_trvs",
    ),
    (
        r"programmer.*(room thermostat|trv)|programmer and appliance thermostat|rhaglennydd.*thermostat",
        "programmer_thermostat",
    ),
    (r"high heat retention|celect", "programmer_thermostat"),
    (r"temperature zone control", "programmer_thermostat"),
    (r"no time or thermostatic|no thermostatic control|^none$|^dim$|dim rheolaeth", "none"),
    (r"rheolaeth amser a rheolaeth parthau tymheredd", "smart_zoned"),
    (r"rheoli.r t.l . llaw", "none"),
    (r"manual charge control", "none"),
    (
        r"programmer|timer|automatic charge control|room thermostat|trv|appliance thermostat|"
        r"rhaglennydd|thermostat",
        "timer_only",
    ),
]


def parse_controls(df: pd.DataFrame) -> pd.Series:
    return _rules(df["MAINHEATCONT_DESCRIPTION"], CONTROL_RULES)


def parse_renewables(df: pd.DataFrame) -> pd.Series:
    pv = pd.to_numeric(_clean(df.get("PHOTO_SUPPLY")), errors="coerce")
    swh = _clean(df.get("SOLAR_WATER_HEATING_FLAG")).str.upper()
    out = pd.Series(["none"] * len(df), index=df.index, dtype="object")
    out[swh.eq("Y")] = "solar_thermal"
    out[pv > 0] = "solar_pv"  # EPC has no battery field -> solar_pv_battery never comes from EPC
    out[pv.isna() & swh.isna()] = None
    return out


# ---------------------------------------------------------------- driver


def parse_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of contract-enum feature columns, index-aligned with df."""
    ptype = parse_property_type(df)
    age = parse_age_band(df)
    fuel = parse_main_fuel(df)
    roof_type, roof_ins = parse_roof(df, age, ptype)
    wall_type, wall_ins = parse_walls(df, age)
    return pd.DataFrame(
        {
            "property_type": ptype,
            "age_band": age,
            "main_fuel": fuel,
            "roof_type": roof_type,
            "roof_insulation": roof_ins,
            "wall_type": wall_type,
            "wall_insulation": wall_ins,
            "glazing": parse_glazing(df),
            "heating_system": parse_heating(df, fuel),
            "smart_controls": parse_controls(df),
            "renewables": parse_renewables(df),
        },
        index=df.index,
    )


RAW_FOR = {
    "property_type": "PROPERTY_TYPE",
    "age_band": "CONSTRUCTION_AGE_BAND",
    "main_fuel": "MAIN_FUEL",
    "roof_type": "ROOF_DESCRIPTION",
    "roof_insulation": "ROOF_DESCRIPTION",
    "wall_type": "WALLS_DESCRIPTION",
    "wall_insulation": "WALLS_DESCRIPTION",
    "glazing": "WINDOWS_DESCRIPTION",
    "heating_system": "MAINHEAT_DESCRIPTION",
    "smart_controls": "MAINHEATCONT_DESCRIPTION",
    "renewables": "PHOTO_SUPPLY",
}


def coverage(parsed: pd.DataFrame) -> pd.Series:
    """Share of rows with a usable value; roof insulation counts as covered when not applicable."""
    ok = parsed.notna()
    ok["roof_insulation"] |= parsed["roof_type"].eq("dwelling_above")
    return ok.mean().sort_values()


def unmatched_report(raw: pd.DataFrame, parsed: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    rows = []
    for col, src in RAW_FOR.items():
        miss = raw.loc[parsed[col].isna(), src].astype("string").fillna("<null>")
        for val, n in miss.value_counts().head(top).items():
            rows.append({"field": col, "raw_value": val, "count": int(n)})
    return pd.DataFrame(rows)
