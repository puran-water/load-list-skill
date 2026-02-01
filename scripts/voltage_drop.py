#!/usr/bin/env python3
"""
Voltage Drop Calculation Module
Calculate voltage drop for motor circuits per NEC recommendations.

Implements voltage drop calculations for:
- Branch circuits (target ≤3%)
- Feeders (target ≤2% so total ≤5%)
- Long cable runs
- Motor starting (instantaneous)

Author: Load List Skill
Standards: NEC 210.19 Informational Note, IEC 60364-5-52
"""

import math
from typing import Optional


# Copper resistivity at different temperatures (Ω·mm²/m)
COPPER_RESISTIVITY = {
    20: 0.0172,
    70: 0.0214,
    75: 0.0221,
    90: 0.0236
}

# Cable reactance (approximate, Ω/m)
CABLE_REACTANCE = {
    "pvc_conduit": 0.00008,
    "xlpe_conduit": 0.00008,
    "tray": 0.00007,
    "direct_buried": 0.00007
}


def calc_voltage_drop_pct(
    current_a: float,
    length_m: float,
    cable_size_mm2: float,
    voltage: float,
    phases: int = 3,
    power_factor: float = 0.85,
    temperature_c: float = 75,
    installation: str = "conduit"
) -> dict:
    """
    Calculate voltage drop percentage for a cable run.

    Formula (3-phase):
    Vd = √3 × I × L × (R × cos(φ) + X × sin(φ))
    Vd% = (Vd / V) × 100

    For motors, we typically use only resistance (X is small for LV cables).

    Args:
        current_a: Load current in Amps
        length_m: One-way cable length in meters
        cable_size_mm2: Cable conductor cross-section in mm²
        voltage: System voltage (line-to-line for 3-phase)
        phases: Number of phases (1 or 3)
        power_factor: Load power factor (0.85 typical for motors)
        temperature_c: Conductor operating temperature (°C)
        installation: Installation type for reactance lookup

    Returns:
        dict with voltage drop results
    """
    # Get copper resistivity at operating temperature
    resistivity = COPPER_RESISTIVITY.get(temperature_c, COPPER_RESISTIVITY[75])

    # Calculate cable resistance per meter (one conductor)
    r_per_m = resistivity / cable_size_mm2  # Ω/m

    # Get reactance (small for LV cables, but included for completeness)
    x_per_m = CABLE_REACTANCE.get(installation, 0.00008)  # Ω/m

    # Calculate impedance components
    cos_phi = power_factor
    sin_phi = math.sqrt(1 - cos_phi ** 2)

    # Effective impedance per meter
    z_per_m = r_per_m * cos_phi + x_per_m * sin_phi

    # Total cable length (outgoing path)
    # For 3-phase balanced, we use √3 × I × L × Z
    # For single-phase, we use 2 × I × L × Z (out and return)

    if phases == 3:
        vd_volts = math.sqrt(3) * current_a * length_m * z_per_m
    else:
        vd_volts = 2 * current_a * length_m * z_per_m

    vd_pct = (vd_volts / voltage) * 100

    return {
        "voltage_drop_v": round(vd_volts, 2),
        "voltage_drop_pct": round(vd_pct, 2),
        "voltage_at_load_v": round(voltage - vd_volts, 1),
        "current_a": current_a,
        "length_m": length_m,
        "cable_size_mm2": cable_size_mm2,
        "voltage_v": voltage,
        "phases": phases,
        "power_factor": power_factor,
        "resistance_ohm_per_m": round(r_per_m, 6),
        "reactance_ohm_per_m": round(x_per_m, 6),
        "compliant_branch": vd_pct <= 3.0,
        "compliant_feeder": vd_pct <= 2.0,
        "notes": f"Voltage drop {vd_pct:.1f}% " +
                ("OK for branch circuit" if vd_pct <= 3.0 else "EXCEEDS 3% branch circuit recommendation")
    }


def calc_voltage_drop_from_awg(
    current_a: float,
    length_m: float,
    cable_size_awg: str,
    voltage: float,
    phases: int = 3,
    power_factor: float = 0.85
) -> dict:
    """
    Calculate voltage drop using AWG cable size.

    Args:
        current_a: Load current in Amps
        length_m: One-way cable length in meters
        cable_size_awg: Cable size in AWG or kcmil (e.g., "4 AWG", "250 kcmil")
        voltage: System voltage
        phases: Number of phases
        power_factor: Load power factor

    Returns:
        dict with voltage drop results
    """
    # AWG to mm² conversion
    awg_to_mm2 = {
        "14 AWG": 2.08,
        "12 AWG": 3.31,
        "10 AWG": 5.26,
        "8 AWG": 8.37,
        "6 AWG": 13.30,
        "4 AWG": 21.15,
        "3 AWG": 26.67,
        "2 AWG": 33.62,
        "1 AWG": 42.41,
        "1/0 AWG": 53.49,
        "2/0 AWG": 67.43,
        "3/0 AWG": 85.01,
        "4/0 AWG": 107.2,
        "250 kcmil": 126.7,
        "300 kcmil": 152.0,
        "350 kcmil": 177.3,
        "400 kcmil": 202.7,
        "500 kcmil": 253.4,
        "600 kcmil": 304.0,
        "700 kcmil": 354.7,
        "750 kcmil": 380.0,
        "800 kcmil": 405.4,
        "900 kcmil": 456.0,
        "1000 kcmil": 506.7
    }

    cable_size_mm2 = awg_to_mm2.get(cable_size_awg.upper().replace("  ", " "))
    if cable_size_mm2 is None:
        return {"error": f"Unknown cable size: {cable_size_awg}"}

    result = calc_voltage_drop_pct(
        current_a, length_m, cable_size_mm2, voltage, phases, power_factor
    )
    result["cable_size_awg"] = cable_size_awg
    return result


def calc_motor_starting_voltage_drop(
    motor_lra: float,
    length_m: float,
    cable_size_mm2: float,
    voltage: float,
    phases: int = 3
) -> dict:
    """
    Calculate voltage drop during motor starting.

    Motor starting causes high current draw (LRA = 6-8× FLA typically).
    This can cause voltage dip that affects other equipment.

    Target: ≤15-20% voltage dip during motor start.

    Args:
        motor_lra: Motor Locked Rotor Amps
        length_m: Cable length to motor
        cable_size_mm2: Cable size
        voltage: System voltage
        phases: Number of phases

    Returns:
        dict with starting voltage drop analysis
    """
    # Use power factor of 0.25-0.35 during starting (motor is inductive)
    starting_pf = 0.30

    result = calc_voltage_drop_pct(
        motor_lra, length_m, cable_size_mm2, voltage, phases, starting_pf
    )

    # Assess impact
    vd_pct = result["voltage_drop_pct"]

    if vd_pct <= 10:
        impact = "LOW - No issues expected"
        recommendation = "OK for most applications"
    elif vd_pct <= 15:
        impact = "MODERATE - May affect sensitive loads"
        recommendation = "Verify no sensitive loads on same feeder"
    elif vd_pct <= 20:
        impact = "HIGH - May cause issues"
        recommendation = "Consider soft starter or VFD"
    else:
        impact = "EXCESSIVE - Will cause issues"
        recommendation = "Require soft starter, VFD, or larger transformer"

    result.update({
        "application": "motor_starting",
        "motor_lra_a": motor_lra,
        "starting_power_factor": starting_pf,
        "impact": impact,
        "recommendation": recommendation,
        "target_max_pct": 15,
        "compliant": vd_pct <= 15
    })

    return result


def size_cable_for_voltage_drop(
    current_a: float,
    length_m: float,
    voltage: float,
    target_vd_pct: float = 3.0,
    phases: int = 3,
    power_factor: float = 0.85,
    cable_standard: str = "metric"
) -> dict:
    """
    Select minimum cable size to meet voltage drop target.

    Args:
        current_a: Load current
        length_m: Cable length
        voltage: System voltage
        target_vd_pct: Target voltage drop percentage
        phases: Number of phases
        power_factor: Power factor
        cable_standard: "metric" (mm²) or "awg"

    Returns:
        dict with minimum cable size
    """
    if cable_standard.lower() == "awg":
        sizes = [
            ("14 AWG", 2.08), ("12 AWG", 3.31), ("10 AWG", 5.26), ("8 AWG", 8.37),
            ("6 AWG", 13.30), ("4 AWG", 21.15), ("3 AWG", 26.67), ("2 AWG", 33.62),
            ("1 AWG", 42.41), ("1/0 AWG", 53.49), ("2/0 AWG", 67.43), ("3/0 AWG", 85.01),
            ("4/0 AWG", 107.2), ("250 kcmil", 126.7), ("300 kcmil", 152.0),
            ("350 kcmil", 177.3), ("400 kcmil", 202.7), ("500 kcmil", 253.4)
        ]
    else:
        sizes = [
            ("1.5 mm²", 1.5), ("2.5 mm²", 2.5), ("4 mm²", 4), ("6 mm²", 6),
            ("10 mm²", 10), ("16 mm²", 16), ("25 mm²", 25), ("35 mm²", 35),
            ("50 mm²", 50), ("70 mm²", 70), ("95 mm²", 95), ("120 mm²", 120),
            ("150 mm²", 150), ("185 mm²", 185), ("240 mm²", 240), ("300 mm²", 300)
        ]

    for size_name, size_mm2 in sizes:
        result = calc_voltage_drop_pct(
            current_a, length_m, size_mm2, voltage, phases, power_factor
        )
        if result["voltage_drop_pct"] <= target_vd_pct:
            return {
                "selected_size": size_name,
                "selected_size_mm2": size_mm2,
                "voltage_drop_pct": result["voltage_drop_pct"],
                "target_vd_pct": target_vd_pct,
                "current_a": current_a,
                "length_m": length_m,
                "voltage_v": voltage,
                "cable_standard": cable_standard,
                "meets_target": True
            }

    return {
        "selected_size": "Exceeds available sizes",
        "target_vd_pct": target_vd_pct,
        "current_a": current_a,
        "length_m": length_m,
        "meets_target": False,
        "recommendation": "Consider multiple parallel cables or closer transformer"
    }


def calc_total_voltage_drop(
    feeder_vd_pct: float,
    branch_vd_pct: float
) -> dict:
    """
    Calculate total voltage drop (feeder + branch).

    NEC recommendation: Total ≤5%

    Args:
        feeder_vd_pct: Feeder voltage drop percentage
        branch_vd_pct: Branch circuit voltage drop percentage

    Returns:
        dict with total voltage drop assessment
    """
    # Voltage drops are approximately additive for small percentages
    total_vd_pct = feeder_vd_pct + branch_vd_pct

    compliant = total_vd_pct <= 5.0

    return {
        "feeder_vd_pct": feeder_vd_pct,
        "branch_vd_pct": branch_vd_pct,
        "total_vd_pct": round(total_vd_pct, 2),
        "target_max_pct": 5.0,
        "compliant": compliant,
        "notes": (
            f"Total voltage drop {total_vd_pct:.1f}% " +
            ("meets NEC recommendation (≤5%)" if compliant else "EXCEEDS NEC 5% recommendation")
        ),
        "code_reference": "NEC 210.19(A)(1) Informational Note No. 4"
    }


if __name__ == "__main__":
    print("Testing voltage_drop module...")
    print("=" * 60)

    # Test basic voltage drop
    print("\n1. Basic Voltage Drop Calculation")
    result = calc_voltage_drop_pct(
        current_a=100,
        length_m=50,
        cable_size_mm2=35,
        voltage=400,
        phases=3,
        power_factor=0.85
    )
    print(f"   100A, 50m, 35mm² @ 400V")
    print(f"   Voltage drop: {result['voltage_drop_v']}V ({result['voltage_drop_pct']}%)")
    print(f"   Voltage at load: {result['voltage_at_load_v']}V")
    print(f"   Compliant (≤3%): {result['compliant_branch']}")

    # Test AWG cable
    print("\n2. Voltage Drop with AWG Size")
    result = calc_voltage_drop_from_awg(
        current_a=100,
        length_m=50,
        cable_size_awg="4/0 AWG",
        voltage=480,
        phases=3
    )
    print(f"   100A, 50m, 4/0 AWG @ 480V")
    print(f"   Voltage drop: {result['voltage_drop_pct']}%")

    # Test motor starting
    print("\n3. Motor Starting Voltage Drop")
    result = calc_motor_starting_voltage_drop(
        motor_lra=600,
        length_m=100,
        cable_size_mm2=95,
        voltage=400
    )
    print(f"   LRA 600A, 100m, 95mm²")
    print(f"   Starting voltage drop: {result['voltage_drop_pct']}%")
    print(f"   Impact: {result['impact']}")
    print(f"   Recommendation: {result['recommendation']}")

    # Test cable sizing for voltage drop
    print("\n4. Size Cable for Voltage Drop Target")
    result = size_cable_for_voltage_drop(
        current_a=150,
        length_m=100,
        voltage=400,
        target_vd_pct=3.0,
        cable_standard="metric"
    )
    print(f"   150A, 100m, target ≤3%")
    print(f"   Selected: {result['selected_size']}")
    print(f"   Actual VD: {result.get('voltage_drop_pct', 'N/A')}%")

    # Test total voltage drop
    print("\n5. Total Voltage Drop Check")
    result = calc_total_voltage_drop(1.8, 2.5)
    print(f"   Feeder: 1.8%, Branch: 2.5%")
    print(f"   Total: {result['total_vd_pct']}%")
    print(f"   Compliant (≤5%): {result['compliant']}")

    print("\n" + "=" * 60)
    print("All tests completed!")
