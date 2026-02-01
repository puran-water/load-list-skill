#!/usr/bin/env python3
"""
Transformer Sizing Module
Size transformers based on demand load with motor starting validation.

Includes:
- Demand-based transformer sizing
- Motor starting voltage dip analysis
- Standard size selection (ANSI/IEC)
- Loading percentage calculations

Author: Load List Skill
Standards: ANSI/IEEE C57.12, IEC 60076
"""

import math
from pathlib import Path
from typing import Optional, Literal

import yaml


# Standard transformer sizes
ANSI_STANDARD_KVA = [15, 25, 37.5, 50, 75, 100, 112.5, 150, 167, 200, 225, 300, 500, 750, 1000, 1500, 2000, 2500]
IEC_STANDARD_KVA = [16, 25, 40, 63, 100, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500]


def load_transformer_catalog() -> dict:
    """Load transformer catalog."""
    catalogs_dir = Path(__file__).parent.parent / "catalogs"
    path = catalogs_dir / "transformers.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def get_typical_impedance(kva: float, transformer_type: str = "dry_type") -> float:
    """
    Get typical transformer impedance for given kVA.

    Args:
        kva: Transformer kVA rating
        transformer_type: dry_type or oil_filled

    Returns:
        Typical impedance percentage
    """
    # Typical impedance ranges
    if transformer_type == "dry_type":
        if kva <= 50:
            return 3.0
        elif kva <= 150:
            return 4.5
        elif kva <= 300:
            return 5.0
        elif kva <= 750:
            return 5.5
        else:
            return 5.75
    else:  # oil_filled
        if kva <= 100:
            return 2.5
        elif kva <= 333:
            return 4.0
        elif kva <= 750:
            return 5.0
        else:
            return 5.5


def size_transformer(
    connected_kva: float,
    demand_kva: float,
    future_growth_pct: float = 20,
    standard: Literal["ANSI", "IEC"] = "ANSI",
    max_loading_pct: float = 85
) -> dict:
    """
    Size transformer based on demand load with growth allowance.

    Args:
        connected_kva: Total connected load (kVA)
        demand_kva: Demand load after diversity (kVA)
        future_growth_pct: Future growth allowance percentage
        standard: ANSI or IEC for standard sizes
        max_loading_pct: Maximum acceptable loading percentage

    Returns:
        dict with transformer sizing results
    """
    # Calculate required capacity with growth
    required_kva = demand_kva * (1 + future_growth_pct / 100)

    # Account for maximum loading preference
    minimum_kva = required_kva / (max_loading_pct / 100)

    # Select standard size
    standard_sizes = ANSI_STANDARD_KVA if standard == "ANSI" else IEC_STANDARD_KVA

    selected_kva = None
    for size in standard_sizes:
        if size >= minimum_kva:
            selected_kva = size
            break

    if selected_kva is None:
        selected_kva = standard_sizes[-1]
        notes = f"Warning: Demand exceeds largest standard size ({standard_sizes[-1]} kVA)"
    else:
        notes = None

    # Calculate loading percentages
    loading_at_demand = (demand_kva / selected_kva) * 100
    loading_with_growth = (required_kva / selected_kva) * 100
    spare_capacity_pct = 100 - loading_with_growth

    # Get typical impedance
    impedance_pct = get_typical_impedance(selected_kva)

    return {
        "connected_kva": round(connected_kva, 1),
        "demand_kva": round(demand_kva, 1),
        "future_growth_pct": future_growth_pct,
        "required_kva": round(required_kva, 1),
        "selected_kva": selected_kva,
        "loading_at_demand_pct": round(loading_at_demand, 1),
        "loading_with_growth_pct": round(loading_with_growth, 1),
        "spare_capacity_pct": round(spare_capacity_pct, 1),
        "typical_impedance_pct": impedance_pct,
        "standard": standard,
        "sizing_basis": (
            f"Demand {demand_kva:.1f} kVA × (1 + {future_growth_pct}% growth) = "
            f"{required_kva:.1f} kVA → {selected_kva} kVA ({loading_with_growth:.0f}% loading)"
        ),
        "notes": notes
    }


def calc_motor_starting_kva(
    motor_hp: Optional[float] = None,
    motor_kw: Optional[float] = None,
    lra_multiplier: float = 6.0,
    power_factor_starting: float = 0.30
) -> dict:
    """
    Calculate motor starting kVA for voltage dip analysis.

    Args:
        motor_hp: Motor horsepower (provide one of hp or kw)
        motor_kw: Motor kilowatts
        lra_multiplier: LRA/FLA ratio (typically 6.0 for Design B)
        power_factor_starting: Power factor during starting (0.25-0.35 typical)

    Returns:
        dict with starting kVA
    """
    # Convert HP to kW if needed
    if motor_kw is None and motor_hp is not None:
        motor_kw = motor_hp * 0.746

    if motor_kw is None:
        return {"error": "Must provide either motor_hp or motor_kw"}

    # Estimate running kVA (assuming 0.85 pf at full load)
    motor_kva_running = motor_kw / 0.85

    # Starting kVA = Running kVA × LRA multiplier × (running pf / starting pf)
    # Simplified: Starting kVA ≈ Running kVA × LRA multiplier
    starting_kva = motor_kva_running * lra_multiplier

    return {
        "motor_kw": motor_kw,
        "motor_kva_running": round(motor_kva_running, 1),
        "lra_multiplier": lra_multiplier,
        "starting_kva": round(starting_kva, 1),
        "power_factor_starting": power_factor_starting,
        "notes": f"{motor_kw} kW motor starting kVA ≈ {starting_kva:.0f} kVA"
    }


def calc_voltage_dip_during_start(
    starting_kva: float,
    transformer_kva: float,
    transformer_impedance_pct: float = 5.75,
    system_impedance_pu: float = 0.0
) -> dict:
    """
    Calculate voltage dip during motor start.

    Simplified formula:
    Vdip ≈ (Starting kVA / Transformer kVA) × Z%

    More accurate with system impedance:
    Vdip ≈ Starting kVA × (Z_xfmr + Z_system) / (Transformer kVA × 100)

    Args:
        starting_kva: Motor starting kVA
        transformer_kva: Transformer kVA rating
        transformer_impedance_pct: Transformer impedance (%)
        system_impedance_pu: System/utility impedance (pu on transformer base)

    Returns:
        dict with voltage dip analysis
    """
    # Total impedance in percent on transformer base
    total_z_pct = transformer_impedance_pct + (system_impedance_pu * 100)

    # Voltage dip calculation
    # Vdip% ≈ (Starting kVA / Transformer kVA) × Z%
    vdip_pct = (starting_kva / transformer_kva) * total_z_pct

    # Assess impact
    if vdip_pct <= 10:
        impact = "LOW"
        recommendation = "No issues expected"
    elif vdip_pct <= 15:
        impact = "MODERATE"
        recommendation = "Acceptable for most applications"
    elif vdip_pct <= 20:
        impact = "HIGH"
        recommendation = "Consider soft starter or VFD, or larger transformer"
    else:
        impact = "EXCESSIVE"
        recommendation = "Soft starter/VFD required, or larger transformer"

    return {
        "starting_kva": starting_kva,
        "transformer_kva": transformer_kva,
        "transformer_z_pct": transformer_impedance_pct,
        "system_z_pu": system_impedance_pu,
        "total_z_pct": round(total_z_pct, 2),
        "voltage_dip_pct": round(vdip_pct, 1),
        "voltage_during_start_pct": round(100 - vdip_pct, 1),
        "impact": impact,
        "recommendation": recommendation,
        "target_max_dip_pct": 15,
        "compliant": vdip_pct <= 15
    }


def check_motor_starting(
    motors: list[dict],
    transformer_kva: float,
    transformer_impedance_pct: float = 5.75
) -> dict:
    """
    Check if transformer can handle largest motor start.

    Args:
        motors: List of motor dicts with 'rated_kw' or 'hp'
        transformer_kva: Transformer kVA rating
        transformer_impedance_pct: Transformer impedance

    Returns:
        dict with motor starting analysis
    """
    if not motors:
        return {"error": "No motors provided"}

    # Find largest motor
    largest_kw = 0
    largest_tag = ""

    for motor in motors:
        kw = motor.get("rated_kw", motor.get("installed_kw", 0))
        if motor.get("hp"):
            kw = max(kw, motor["hp"] * 0.746)

        if kw > largest_kw:
            largest_kw = kw
            largest_tag = motor.get("equipment_tag", motor.get("tag", ""))

    # Calculate starting kVA
    starting = calc_motor_starting_kva(motor_kw=largest_kw)
    starting_kva = starting["starting_kva"]

    # Calculate voltage dip
    vdip = calc_voltage_dip_during_start(
        starting_kva=starting_kva,
        transformer_kva=transformer_kva,
        transformer_impedance_pct=transformer_impedance_pct
    )

    # Determine if sequential starting needed
    sequential_required = vdip["voltage_dip_pct"] > 15

    return {
        "largest_motor_kw": largest_kw,
        "largest_motor_tag": largest_tag,
        "largest_starting_kva": starting_kva,
        "transformer_kva": transformer_kva,
        "voltage_dip_pct": vdip["voltage_dip_pct"],
        "voltage_during_start_pct": vdip["voltage_during_start_pct"],
        "impact": vdip["impact"],
        "sequential_start_required": sequential_required,
        "recommendation": vdip["recommendation"],
        "compliant": vdip["compliant"],
        "notes": (
            f"Largest motor {largest_kw} kW ({largest_tag}) causes {vdip['voltage_dip_pct']:.1f}% dip. " +
            ("Interlock large motor starts." if sequential_required else "Direct start OK.")
        )
    }


def size_transformer_with_motor_check(
    connected_kva: float,
    demand_kva: float,
    motors: list[dict],
    future_growth_pct: float = 20,
    standard: Literal["ANSI", "IEC"] = "ANSI",
    max_voltage_dip_pct: float = 15
) -> dict:
    """
    Size transformer considering both demand and motor starting.

    May select larger transformer if motor starting causes excessive voltage dip.

    Args:
        connected_kva: Total connected load
        demand_kva: Demand load after diversity
        motors: List of motor dicts
        future_growth_pct: Growth allowance
        standard: ANSI or IEC
        max_voltage_dip_pct: Maximum acceptable voltage dip during motor start

    Returns:
        dict with transformer sizing including motor start check
    """
    # Initial sizing based on demand
    demand_sizing = size_transformer(
        connected_kva, demand_kva, future_growth_pct, standard
    )
    selected_kva = demand_sizing["selected_kva"]

    # Check motor starting
    motor_check = check_motor_starting(
        motors, selected_kva, demand_sizing["typical_impedance_pct"]
    )

    # If motor starting causes excessive dip, try larger transformer
    upsized = False
    standard_sizes = ANSI_STANDARD_KVA if standard == "ANSI" else IEC_STANDARD_KVA

    while motor_check["voltage_dip_pct"] > max_voltage_dip_pct:
        # Try next size up
        current_idx = standard_sizes.index(selected_kva) if selected_kva in standard_sizes else -1

        if current_idx < len(standard_sizes) - 1:
            selected_kva = standard_sizes[current_idx + 1]
            upsized = True

            # Recalculate motor starting check
            motor_check = check_motor_starting(
                motors, selected_kva, get_typical_impedance(selected_kva)
            )
        else:
            # Can't upsize further
            break

    # Recalculate loading with final size
    loading_at_demand = (demand_kva / selected_kva) * 100
    required_kva = demand_kva * (1 + future_growth_pct / 100)
    loading_with_growth = (required_kva / selected_kva) * 100

    return {
        "connected_kva": round(connected_kva, 1),
        "demand_kva": round(demand_kva, 1),
        "future_growth_pct": future_growth_pct,
        "required_kva_demand": round(required_kva, 1),
        "selected_kva": selected_kva,
        "loading_at_demand_pct": round(loading_at_demand, 1),
        "loading_with_growth_pct": round(loading_with_growth, 1),
        "typical_impedance_pct": get_typical_impedance(selected_kva),
        "upsized_for_motor_start": upsized,
        "motor_starting_check": motor_check,
        "standard": standard,
        "sizing_basis": (
            f"Demand {demand_kva:.1f} kVA → {selected_kva} kVA" +
            (f" (upsized from {demand_sizing['selected_kva']} kVA for motor starting)" if upsized else "") +
            f", {loading_with_growth:.0f}% loading"
        )
    }


if __name__ == "__main__":
    print("Testing transformer_sizing module...")
    print("=" * 60)

    # Test basic sizing
    print("\n1. Basic Transformer Sizing")
    result = size_transformer(
        connected_kva=850,
        demand_kva=600,
        future_growth_pct=20,
        standard="ANSI"
    )
    print(f"   Connected: {result['connected_kva']} kVA")
    print(f"   Demand: {result['demand_kva']} kVA")
    print(f"   Required (with growth): {result['required_kva']} kVA")
    print(f"   Selected: {result['selected_kva']} kVA")
    print(f"   Loading: {result['loading_with_growth_pct']}%")

    # Test motor starting kVA
    print("\n2. Motor Starting kVA")
    starting = calc_motor_starting_kva(motor_kw=110)
    print(f"   110 kW motor starting kVA: {starting['starting_kva']}")

    # Test voltage dip
    print("\n3. Voltage Dip During Motor Start")
    vdip = calc_voltage_dip_during_start(
        starting_kva=780,  # 110 kW × ~7 multiplier
        transformer_kva=1000,
        transformer_impedance_pct=5.75
    )
    print(f"   Starting kVA: {vdip['starting_kva']}")
    print(f"   Transformer: {vdip['transformer_kva']} kVA")
    print(f"   Voltage dip: {vdip['voltage_dip_pct']}%")
    print(f"   Impact: {vdip['impact']}")
    print(f"   Recommendation: {vdip['recommendation']}")

    # Test with motor check
    print("\n4. Transformer Sizing with Motor Start Check")
    motors = [
        {"equipment_tag": "200-B-01A", "rated_kw": 110},
        {"equipment_tag": "200-B-01B", "rated_kw": 110},
        {"equipment_tag": "200-AG-01", "rated_kw": 22},
        {"equipment_tag": "200-P-01A", "rated_kw": 37}
    ]
    result = size_transformer_with_motor_check(
        connected_kva=850,
        demand_kva=600,
        motors=motors,
        standard="ANSI"
    )
    print(f"   Selected: {result['selected_kva']} kVA")
    print(f"   Upsized for motor start: {result['upsized_for_motor_start']}")
    print(f"   Largest motor dip: {result['motor_starting_check']['voltage_dip_pct']}%")
    print(f"   Sequential start required: {result['motor_starting_check']['sequential_start_required']}")

    print("\n" + "=" * 60)
    print("All tests completed!")
