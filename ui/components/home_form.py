"""The Your home form: widgets ↔ HomeInput JSON. "Not sure" and empty fields always become None (BUILD_GUIDE P5
hazard 2), never "", "unknown" or 0."""

import math
from datetime import date

import pandas as pd
import streamlit as st

from labels import LABELS, YES_NO, label

# (field, question, kind, enum name). Order = order on screen.
PROPERTY = [
    ("property_type", "Property type", "enum", "PropertyType"),
    ("age_band", "When was it built?", "enum", "AgeBand"),
    ("floor_area_m2", "Floor area (m²)", "number", None),
    ("bedrooms", "Bedrooms", "int", None),
    ("region", "Region", "enum", "Region"),
    ("energy_rating", "EPC rating", "enum", "EnergyRating"),
    ("current_value_gbp", "Your estimate of its value (£)", "number", None),
]
FEATURES = [
    ("roof_type", "Roof", "enum", "RoofType"),
    ("roof_insulation", "Is your loft insulated?", "enum", "RoofInsulation"),
    ("wall_type", "Walls", "enum", "WallType"),
    ("wall_insulation", "Wall insulation", "enum", "WallInsulation"),
    ("glazing", "Windows", "enum", "Glazing"),
    ("heating_system", "Main heating", "enum", "HeatingSystem"),
    ("main_fuel", "Main heating fuel", "enum", "MainFuel"),
    ("renewables", "Renewables", "enum", "Renewables"),
    ("smart_controls", "Heating controls", "enum", "SmartControls"),
    ("listed_or_conservation", "Listed building or conservation area?", "yesno", None),
    ("outdoor_space", "Outdoor space for a heat pump unit?", "yesno", None),
]
FIELDS = PROPERTY + FEATURES
ENERGY_MODES = ["Yearly totals", "Monthly readings", "Not sure"]
MONTH_COLS = ["month", "electricity_kwh", "gas_kwh"]


def key(field: str) -> str:
    return f"f_{field}"


# ---------- pure conversion (unit-tested) ----------
def clean(v):
    """None for anything that means 'no answer'."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def build_home_input(
    values: dict, energy_mode: str, annual: dict, monthly_rows: list[dict], ids: dict | None = None
) -> dict:
    """Widget values → HomeInput JSON.

    Rows with no reading at all are dropped; missing months stay missing (never zero)."""
    home: dict = {
        "property_id": (ids or {}).get("property_id"),
        "customer_id": (ids or {}).get("customer_id"),
    }
    for field, _, kind, _ in FIELDS:
        v = clean(values.get(field))
        if v is not None and kind == "number":
            v = float(v)
        if v is not None and kind == "int":
            v = int(v)
        home[field] = v
    if energy_mode == "Yearly totals":
        energy = {
            k: (None if clean(annual.get(k)) is None else float(annual[k]))
            for k in ("annual_electricity_kwh", "annual_gas_kwh")
        }
    elif energy_mode == "Monthly readings":
        rows = []
        for r in monthly_rows:
            month = clean(r.get("month"))
            e, g = clean(r.get("electricity_kwh")), clean(r.get("gas_kwh"))
            if month and (e is not None or g is not None):
                rows.append(
                    {
                        "month": str(month),
                        "electricity_kwh": None if e is None else float(e),
                        "gas_kwh": None if g is None else float(g),
                    }
                )
        energy = {"monthly": rows or None}
    else:
        energy = {}
    home["energy"] = energy
    return home


def last_12_months(today: date | None = None) -> list[str]:
    """The 12 calendar months ending with the last full month."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(12):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return out[::-1]


def monthly_frame(monthly: list[dict] | None) -> pd.DataFrame:
    if monthly:
        return pd.DataFrame([{c: r.get(c) for c in MONTH_COLS} for r in monthly], columns=MONTH_COLS)
    return pd.DataFrame({"month": last_12_months(), "electricity_kwh": [None] * 12, "gas_kwh": [None] * 12})


# ---------- session state ----------
def load_into_state(home: dict) -> None:
    """Put a HomeInput (e.g. an example home) into the form widgets."""
    for field, _, _, _ in FIELDS:
        st.session_state[key(field)] = home.get(field)
    st.session_state["f_ids"] = {
        "property_id": home.get("property_id"),
        "customer_id": home.get("customer_id"),
    }
    energy = home.get("energy") or {}
    if energy.get("monthly"):
        st.session_state["f_energy_mode"] = "Monthly readings"
    elif energy.get("annual_electricity_kwh") is not None or energy.get("annual_gas_kwh") is not None:
        st.session_state["f_energy_mode"] = "Yearly totals"
    else:
        st.session_state["f_energy_mode"] = "Not sure"
    st.session_state["f_annual_electricity_kwh"] = energy.get("annual_electricity_kwh")
    st.session_state["f_annual_gas_kwh"] = energy.get("annual_gas_kwh")
    st.session_state["f_monthly_df"] = monthly_frame(energy.get("monthly"))
    st.session_state["f_editor_version"] = st.session_state.get("f_editor_version", 0) + 1


# ---------- widgets ----------
def _unset(k: str) -> dict:
    """value=None only for a fresh widget; a value already in session state (a loaded example) wins."""
    return {} if k in st.session_state else {"value": None}


def _widget(field: str, question: str, kind: str, enum: str | None) -> None:
    k = key(field)
    if kind == "enum":
        st.selectbox(question, [None, *LABELS[enum]], key=k, format_func=lambda v, e=enum: label(e, v))
    elif kind == "yesno":
        st.selectbox(
            question, [None, "yes", "no"], key=k, format_func=lambda v: "Not sure" if v is None else YES_NO[v]
        )
    elif kind == "int":
        st.number_input(
            question, min_value=0, max_value=20, step=1, key=k, placeholder="Not sure", **_unset(k)
        )
    else:
        st.number_input(
            question,
            min_value=0.0,
            key=k,
            placeholder="Not sure",
            step=1000.0 if field == "current_value_gbp" else 1.0,
            **_unset(k),
        )


def render() -> dict | None:
    """Draw the form. Returns HomeInput JSON on submit, else None."""
    st.session_state.setdefault("f_energy_mode", "Yearly totals")
    st.session_state.setdefault("f_monthly_df", monthly_frame(None))
    mode = st.radio("How do you know your energy use?", ENERGY_MODES, key="f_energy_mode", horizontal=True)
    with st.form("home_form", border=False):
        st.subheader("Property")
        cols = st.columns(3)
        for i, spec in enumerate(PROPERTY):
            with cols[i % 3]:
                _widget(*spec)
        st.subheader("Features")
        cols = st.columns(3)
        for i, spec in enumerate(FEATURES):
            with cols[i % 3]:
                _widget(*spec)
        st.subheader("Energy use")
        rows: list[dict] = []
        if mode == "Yearly totals":
            c1, c2 = st.columns(2)
            for col, k, q in (
                (c1, "f_annual_electricity_kwh", "Electricity per year (kWh)"),
                (c2, "f_annual_gas_kwh", "Gas per year (kWh)"),
            ):
                col.number_input(q, min_value=0.0, key=k, placeholder="Not sure", step=100.0, **_unset(k))
        elif mode == "Monthly readings":
            st.caption(
                "Leave a month empty if you don't have that reading. "
                "Missing months are never counted as zero."
            )
            edited = st.data_editor(
                st.session_state["f_monthly_df"],
                key=f"f_monthly_editor_{st.session_state.get('f_editor_version', 0)}",
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                column_config={
                    "month": st.column_config.TextColumn(
                        "Month (YYYY-MM)", validate=r"^\d{4}-(0[1-9]|1[0-2])$"
                    ),
                    "electricity_kwh": st.column_config.NumberColumn("Electricity (kWh)", min_value=0),
                    "gas_kwh": st.column_config.NumberColumn("Gas (kWh)", min_value=0),
                },
            )
            rows = edited.to_dict("records")
        else:
            st.caption("We'll estimate typical use for a home like yours and flag the estimate.")
        submitted = st.form_submit_button("Analyse my home", type="primary")
    if not submitted:
        return None
    values = {field: st.session_state.get(key(field)) for field, _, _, _ in FIELDS}
    annual = {k: st.session_state.get(f"f_{k}") for k in ("annual_electricity_kwh", "annual_gas_kwh")}
    return build_home_input(values, mode, annual, rows, st.session_state.get("f_ids"))
