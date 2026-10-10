"""Carbon saving from a fuel saving (README P2.8 item 7): ΔC = Δelec × EF_elec + Δgas × EF_gas, kg CO2e.

Sign follows the saving (positive = reduction). Emission factors come from config/emission_factors.yaml.
"""

from __future__ import annotations

from greenhome.config import get_config
from greenhome.contracts import CarbonResult, FuelSaving


def compute_carbon(saving: FuelSaving) -> CarbonResult:
    efs = get_config().emission_factors
    elec, gas = efs["electricity"], efs["gas"]
    electricity_kg = saving.electricity_kwh * elec.kg_co2e_per_kwh
    gas_kg = saving.gas_kwh * gas.kg_co2e_per_kwh
    return CarbonResult(
        electricity_kg=electricity_kg,
        gas_kg=gas_kg,
        total_kg=electricity_kg + gas_kg,
        ef_electricity=elec.kg_co2e_per_kwh,
        ef_gas=gas.kg_co2e_per_kwh,
        ef_source=f"electricity: {elec.source} ({elec.year}); gas: {gas.source} ({gas.year})",
    )
