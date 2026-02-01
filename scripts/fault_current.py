#!/usr/bin/env python3
"""
Fault Current Calculation Module
Compute preliminary available fault current from transformer data.

Per Codex Plan P0 Requirements:
- Compute fault current from assumed transformer when utility data unavailable
- Default to WORST-CASE (higher) for SCCR validation when unknown
- Flag all preliminary values with appropriate warnings

Standards:
- IEEE 141 (Red Book) - Industrial power systems
- IEEE 242 (Buff Book) - Protection and coordination
- NEC 110.24 - Available fault current marking

Author: Load List Skill
"""

import math
from typing import Optional


def calc_preliminary_fault_current(
    transformer_kva: float,
    transformer_z_pct: float,
    secondary_voltage: float,
    phases: int = 3
) -> dict:
    """
    Compute preliminary available fault current from assumed transformer.

    This provides a CONSERVATIVE (higher) estimate for SCCR validation
    when utility coordination data is not available.

    Args:
        transformer_kva: Transformer kVA rating
        transformer_z_pct: Transformer impedance percentage (typical 5.5-6.0%)
        secondary_voltage: Transformer secondary voltage (V)
        phases: Number of phases (default 3)

    Returns:
        dict with:
        - available_fault_ka: Calculated fault current in kA
        - transformer_kva: Input transformer size
        - transformer_z_pct: Input impedance
        - i_rated_a: Transformer rated current (A)
        - source: "calculated_from_assumed_transformer"
        - warning: Disclaimer text

    Example:
        >>> result = calc_preliminary_fault_current(1000, 5.75, 480)
        >>> print(f"Available fault: {result['available_fault_ka']} kA")
        Available fault: 20.9 kA
    """
    # Calculate transformer rated current
    if phases == 3:
        i_rated = (transformer_kva * 1000) / (math.sqrt(3) * secondary_voltage)
    else:
        i_rated = (transformer_kva * 1000) / secondary_voltage

    # Calculate short-circuit current (infinite bus assumption)
    # I_sc = I_rated / (Z% / 100)
    # This IGNORES utility impedance, giving HIGHER (conservative) value
    z_pu = transformer_z_pct / 100
    i_sc = i_rated / z_pu

    # Convert to kA
    i_sc_ka = i_sc / 1000

    return {
        "available_fault_ka": round(i_sc_ka, 1),
        "transformer_kva": transformer_kva,
        "transformer_z_pct": transformer_z_pct,
        "secondary_voltage": secondary_voltage,
        "i_rated_a": round(i_rated, 1),
        "source": "calculated_from_assumed_transformer",
        "calculation_method": "infinite_bus",
        "warning": "PRELIMINARY - verify with utility coordination study",
        "notes": (
            "Calculation assumes infinite bus (zero utility impedance). "
            "Actual fault current may be lower. Use for preliminary SCCR validation only."
        )
    }


def calc_fault_current_with_utility(
    transformer_kva: float,
    transformer_z_pct: float,
    secondary_voltage: float,
    utility_fault_mva: Optional[float] = None,
    utility_fault_ka: Optional[float] = None,
    primary_voltage: Optional[float] = None,
    phases: int = 3
) -> dict:
    """
    Calculate fault current including utility source impedance.

    More accurate than infinite bus method when utility data is available.

    Args:
        transformer_kva: Transformer kVA rating
        transformer_z_pct: Transformer impedance percentage
        secondary_voltage: Transformer secondary voltage (V)
        utility_fault_mva: Utility available fault MVA at primary (optional)
        utility_fault_ka: Utility available fault kA at primary (optional)
        primary_voltage: Transformer primary voltage (V) - needed if using utility_fault_ka
        phases: Number of phases

    Returns:
        dict with fault current calculation results
    """
    # Calculate transformer rated current (secondary)
    if phases == 3:
        i_rated = (transformer_kva * 1000) / (math.sqrt(3) * secondary_voltage)
    else:
        i_rated = (transformer_kva * 1000) / secondary_voltage

    # Calculate transformer base impedance
    z_base = (secondary_voltage ** 2) / (transformer_kva * 1000)

    # Transformer impedance in ohms
    z_xfmr_ohms = (transformer_z_pct / 100) * z_base

    # Convert transformer impedance to per-unit on transformer base
    z_xfmr_pu = transformer_z_pct / 100

    # Calculate utility impedance if data provided
    z_utility_pu = 0.0
    utility_source = "infinite_bus"

    if utility_fault_mva:
        # Z_utility (pu) = S_base / S_fault
        s_base_mva = transformer_kva / 1000
        z_utility_pu = s_base_mva / utility_fault_mva
        utility_source = "utility_fault_mva"

    elif utility_fault_ka and primary_voltage:
        # Convert utility kA at primary to MVA
        if phases == 3:
            utility_fault_mva_calc = math.sqrt(3) * primary_voltage * utility_fault_ka / 1000
        else:
            utility_fault_mva_calc = primary_voltage * utility_fault_ka / 1000

        s_base_mva = transformer_kva / 1000
        z_utility_pu = s_base_mva / utility_fault_mva_calc
        utility_source = "utility_fault_ka"

    # Total impedance (pu)
    z_total_pu = z_xfmr_pu + z_utility_pu

    # Short-circuit current
    i_sc = i_rated / z_total_pu
    i_sc_ka = i_sc / 1000

    return {
        "available_fault_ka": round(i_sc_ka, 1),
        "transformer_kva": transformer_kva,
        "transformer_z_pct": transformer_z_pct,
        "transformer_z_pu": round(z_xfmr_pu, 4),
        "utility_z_pu": round(z_utility_pu, 4),
        "total_z_pu": round(z_total_pu, 4),
        "secondary_voltage": secondary_voltage,
        "i_rated_a": round(i_rated, 1),
        "source": f"calculated_with_{utility_source}",
        "warning": (
            "PRELIMINARY - verify with detailed short-circuit study"
            if utility_source == "infinite_bus"
            else "Based on utility data - verify study assumptions"
        )
    }


def get_default_fault_current(
    location: str = "mcc_bus"
) -> dict:
    """
    Get default (worst-case) fault current when no data available.

    Per Codex Plan: Default to WORST-CASE (higher) for SCCR validation.

    Args:
        location: Point in distribution system
            - "service_entrance": Utility service point
            - "transformer_secondary": After main transformer
            - "main_switchboard": Main distribution
            - "mcc_bus": At MCC

    Returns:
        dict with default fault current and warnings
    """
    # Conservative defaults (higher values for SCCR validation)
    defaults = {
        "service_entrance": {
            "available_fault_ka": 65,
            "typical_range": "35-100 kA",
            "notes": "Varies widely by utility - always verify"
        },
        "transformer_secondary": {
            "available_fault_ka": 50,
            "typical_range": "22-65 kA",
            "notes": "Based on 1000-2500 kVA, 5.75% Z typical"
        },
        "main_switchboard": {
            "available_fault_ka": 42,
            "typical_range": "18-50 kA",
            "notes": "After main breaker impedance"
        },
        "mcc_bus": {
            "available_fault_ka": 50,  # Conservative (high) per plan - for SCCR validation
            "typical_range": "14-50 kA",
            "notes": "Conservative default per plan: 50 kA for SCCR validation"
        }
    }

    if location not in defaults:
        location = "mcc_bus"

    result = defaults[location].copy()
    result.update({
        "location": location,
        "source": "conservative_default",
        "verified": False,
        "warning": (
            "DEFAULT VALUE - NOT FOR FINAL VALIDATION. "
            "Conservative (high) value for preliminary SCCR check only. "
            "Actual value requires utility coordination and/or short-circuit study."
        ),
        "sccr_ready": False,
        "takeoff_ready": False
    })

    return result


def validate_sccr(
    available_fault_ka: float,
    equipment_sccr_ka: float,
    equipment_tag: str = ""
) -> dict:
    """
    Validate equipment SCCR against available fault current.

    Args:
        available_fault_ka: Available fault current at equipment location (kA)
        equipment_sccr_ka: Equipment short-circuit current rating (kA)
        equipment_tag: Equipment identifier for reporting

    Returns:
        dict with validation result and recommendations
    """
    compliant = equipment_sccr_ka >= available_fault_ka
    margin_pct = ((equipment_sccr_ka - available_fault_ka) / available_fault_ka) * 100

    result = {
        "equipment_tag": equipment_tag,
        "available_fault_ka": available_fault_ka,
        "equipment_sccr_ka": equipment_sccr_ka,
        "compliant": compliant,
        "margin_ka": round(equipment_sccr_ka - available_fault_ka, 1),
        "margin_pct": round(margin_pct, 1)
    }

    if compliant:
        result["status"] = "PASS"
        result["notes"] = f"SCCR adequate with {result['margin_pct']}% margin"
    else:
        result["status"] = "FAIL"
        result["shortfall_ka"] = round(available_fault_ka - equipment_sccr_ka, 1)
        result["recommendation"] = (
            f"Equipment SCCR ({equipment_sccr_ka} kA) is less than "
            f"available fault current ({available_fault_ka} kA). "
            "Options: (1) Select higher SCCR equipment, "
            "(2) Add current-limiting protection, "
            "(3) Verify actual fault current with study"
        )

    return result


def calc_cable_impedance_reduction(
    cable_length_m: float,
    cable_size_mm2: float,
    upstream_fault_ka: float,
    voltage: float = 400,
    phases: int = 3
) -> dict:
    """
    Calculate fault current reduction due to cable impedance.

    Useful for estimating fault current at equipment downstream of long cables.

    Args:
        cable_length_m: Cable length in meters
        cable_size_mm2: Cable conductor size in mm²
        upstream_fault_ka: Fault current at upstream point (kA)
        voltage: System voltage (V)
        phases: Number of phases

    Returns:
        dict with downstream fault current estimate
    """
    # Copper resistivity at 75°C: 0.0214 Ω·mm²/m
    # Typical reactance for XLPE: 0.08 mΩ/m (approximate)
    resistivity = 0.0214  # Ω·mm²/m

    # Calculate cable resistance (one way)
    r_cable = resistivity * cable_length_m / cable_size_mm2  # Ohms per conductor

    # For 3-phase, use 2× for loop impedance (out and back via fault)
    if phases == 3:
        z_cable = 2 * r_cable * math.sqrt(3) / 3  # Simplified for balanced fault
    else:
        z_cable = 2 * r_cable

    # Calculate upstream impedance from fault current
    if phases == 3:
        z_upstream = voltage / (math.sqrt(3) * upstream_fault_ka * 1000)
    else:
        z_upstream = voltage / (upstream_fault_ka * 1000)

    # Total impedance
    z_total = z_upstream + z_cable

    # Downstream fault current
    if phases == 3:
        i_downstream = voltage / (math.sqrt(3) * z_total)
    else:
        i_downstream = voltage / z_total

    downstream_fault_ka = i_downstream / 1000

    return {
        "upstream_fault_ka": upstream_fault_ka,
        "cable_length_m": cable_length_m,
        "cable_size_mm2": cable_size_mm2,
        "cable_impedance_ohms": round(z_cable, 4),
        "downstream_fault_ka": round(downstream_fault_ka, 1),
        "reduction_pct": round((1 - downstream_fault_ka / upstream_fault_ka) * 100, 1),
        "notes": "Simplified calculation - ignores reactance and temperature effects"
    }


# Standard transformer impedances (typical values)
STANDARD_TRANSFORMER_IMPEDANCES = {
    # Dry-type transformers (ANSI/IEEE C57.12.01)
    "dry_type": {
        15: 3.0,
        25: 3.5,
        37.5: 4.0,
        50: 4.5,
        75: 5.0,
        100: 5.0,
        112.5: 5.0,
        150: 5.0,
        167: 5.0,
        200: 5.0,
        225: 5.5,
        300: 5.5,
        500: 5.75,
        750: 5.75,
        1000: 5.75,
        1500: 5.75,
        2000: 5.75,
        2500: 6.0,
    },
    # Oil-filled transformers
    "oil_filled": {
        25: 2.5,
        37.5: 3.0,
        50: 3.5,
        75: 4.0,
        100: 4.0,
        167: 4.5,
        250: 4.5,
        333: 5.0,
        500: 5.0,
        750: 5.5,
        1000: 5.75,
        1500: 5.75,
        2000: 5.75,
        2500: 6.0,
        3333: 6.5,
        5000: 7.0,
    }
}


def get_typical_transformer_impedance(
    kva: float,
    transformer_type: str = "dry_type"
) -> float:
    """
    Get typical transformer impedance for given kVA rating.

    Args:
        kva: Transformer kVA rating
        transformer_type: "dry_type" or "oil_filled"

    Returns:
        Typical impedance percentage
    """
    impedances = STANDARD_TRANSFORMER_IMPEDANCES.get(transformer_type, {})

    # Find closest rating
    kva_ratings = sorted(impedances.keys())
    for rating in kva_ratings:
        if rating >= kva:
            return impedances[rating]

    # Return highest if exceeds table
    if kva_ratings:
        return impedances[kva_ratings[-1]]

    return 5.75  # Default


if __name__ == "__main__":
    print("Testing fault_current module...")
    print("=" * 60)

    # Test preliminary calculation
    result = calc_preliminary_fault_current(1000, 5.75, 480)
    print(f"\n1000 kVA, 5.75% Z @ 480V:")
    print(f"  Available fault: {result['available_fault_ka']} kA")
    print(f"  Rated current: {result['i_rated_a']} A")
    print(f"  Warning: {result['warning']}")

    # Test with utility data
    result2 = calc_fault_current_with_utility(
        transformer_kva=1000,
        transformer_z_pct=5.75,
        secondary_voltage=480,
        utility_fault_mva=500
    )
    print(f"\nWith 500 MVA utility:")
    print(f"  Available fault: {result2['available_fault_ka']} kA")
    print(f"  Transformer Z: {result2['transformer_z_pu']} pu")
    print(f"  Utility Z: {result2['utility_z_pu']} pu")

    # Test default values
    default = get_default_fault_current("mcc_bus")
    print(f"\nDefault at MCC bus:")
    print(f"  Available fault: {default['available_fault_ka']} kA")
    print(f"  Typical range: {default['typical_range']}")

    # Test SCCR validation
    sccr_check = validate_sccr(22, 65, "MCC-200-01A")
    print(f"\nSCCR validation (22 kA vs 65 kA SCCR):")
    print(f"  Status: {sccr_check['status']}")
    print(f"  Margin: {sccr_check['margin_pct']}%")

    # Test cable impedance
    cable_result = calc_cable_impedance_reduction(100, 95, 22, 400)
    print(f"\n100m of 95mm² from 22 kA source:")
    print(f"  Downstream fault: {cable_result['downstream_fault_ka']} kA")
    print(f"  Reduction: {cable_result['reduction_pct']}%")

    print("\n" + "=" * 60)
    print("All tests completed!")
