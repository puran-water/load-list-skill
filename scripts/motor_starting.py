#!/usr/bin/env python3
"""
Motor Starting Analysis Module
Analyze motor starting voltage dip and system impact.

Includes:
- Motor starting kVA calculation
- Voltage dip estimation
- Sequential start requirement detection
- Generator sizing impact
- Starting method recommendations

Author: Load List Skill
Standards: IEEE 141 (Red Book), IEEE 399 (Brown Book)
"""

import math
from typing import Optional


def calc_motor_starting_current(
    motor_kw: float,
    voltage: float,
    efficiency: float = 0.90,
    power_factor: float = 0.85,
    lra_multiplier: float = 6.0,
    phases: int = 3
) -> dict:
    """
    Calculate motor starting (locked rotor) current.

    Args:
        motor_kw: Motor rated kW
        voltage: System voltage
        efficiency: Motor efficiency
        power_factor: Motor running power factor
        lra_multiplier: LRA/FLA ratio (typically 6.0 for Design B)
        phases: Number of phases

    Returns:
        dict with FLA, LRA, and starting characteristics
    """
    # Calculate Full Load Amps
    if phases == 3:
        fla = (motor_kw * 1000) / (math.sqrt(3) * voltage * efficiency * power_factor)
    else:
        fla = (motor_kw * 1000) / (voltage * efficiency * power_factor)

    # Locked Rotor Amps
    lra = fla * lra_multiplier

    # Starting power factor (typically 0.25-0.35)
    starting_pf = 0.30

    # Starting kVA
    if phases == 3:
        starting_kva = (math.sqrt(3) * voltage * lra) / 1000
    else:
        starting_kva = (voltage * lra) / 1000

    return {
        "motor_kw": motor_kw,
        "voltage_v": voltage,
        "fla_a": round(fla, 1),
        "lra_a": round(lra, 0),
        "lra_multiplier": lra_multiplier,
        "starting_kva": round(starting_kva, 0),
        "starting_pf": starting_pf,
        "phases": phases
    }


def calc_voltage_dip(
    starting_kva: float,
    source_kva: float,
    source_impedance_pct: float,
    cable_impedance_pct: float = 0
) -> dict:
    """
    Calculate voltage dip during motor starting.

    Formula: Vdip% ≈ (Starting kVA / Source kVA) × Total Z%

    Args:
        starting_kva: Motor starting kVA
        source_kva: Source capacity (transformer or generator kVA)
        source_impedance_pct: Source impedance (%)
        cable_impedance_pct: Additional cable impedance (%)

    Returns:
        dict with voltage dip analysis
    """
    total_impedance = source_impedance_pct + cable_impedance_pct

    # Voltage dip calculation
    vdip_pct = (starting_kva / source_kva) * total_impedance

    # Voltage during starting
    voltage_during_start = 100 - vdip_pct

    return {
        "starting_kva": starting_kva,
        "source_kva": source_kva,
        "source_impedance_pct": source_impedance_pct,
        "cable_impedance_pct": cable_impedance_pct,
        "total_impedance_pct": total_impedance,
        "voltage_dip_pct": round(vdip_pct, 1),
        "voltage_during_start_pct": round(voltage_during_start, 1)
    }


def assess_voltage_dip_impact(
    voltage_dip_pct: float,
    application: str = "general"
) -> dict:
    """
    Assess impact of voltage dip on system.

    Args:
        voltage_dip_pct: Calculated voltage dip percentage
        application: Application type (general, critical, lighting)

    Returns:
        dict with impact assessment
    """
    # Impact thresholds
    if application == "critical":
        thresholds = {"low": 8, "moderate": 12, "high": 15}
    elif application == "lighting":
        thresholds = {"low": 5, "moderate": 8, "high": 10}
    else:  # general
        thresholds = {"low": 10, "moderate": 15, "high": 20}

    if voltage_dip_pct <= thresholds["low"]:
        impact = "LOW"
        effects = ["No perceptible effect on most equipment"]
        action = "None required"
    elif voltage_dip_pct <= thresholds["moderate"]:
        impact = "MODERATE"
        effects = [
            "Visible light flicker",
            "May affect sensitive electronic loads",
            "Contactors may drop out if below 85%"
        ]
        action = "Verify no sensitive loads on same bus"
    elif voltage_dip_pct <= thresholds["high"]:
        impact = "HIGH"
        effects = [
            "Significant light flicker",
            "Risk of contactor dropout",
            "PLC/drives may fault",
            "Running motors may stall"
        ]
        action = "Consider soft starter, VFD, or larger source"
    else:
        impact = "EXCESSIVE"
        effects = [
            "Equipment malfunction likely",
            "Contactors will drop out",
            "System instability",
            "Starting motor may not accelerate"
        ]
        action = "Mitigation required - soft starter/VFD mandatory"

    return {
        "voltage_dip_pct": voltage_dip_pct,
        "impact_level": impact,
        "effects": effects,
        "recommended_action": action,
        "threshold_used": thresholds,
        "application": application,
        "acceptable": voltage_dip_pct <= thresholds["moderate"]
    }


def analyze_motor_starting(
    motor_kw: float,
    voltage: float,
    source_kva: float,
    source_impedance_pct: float,
    starting_method: str = "DOL",
    lra_multiplier: float = 6.0,
    application: str = "general"
) -> dict:
    """
    Complete motor starting analysis.

    Args:
        motor_kw: Motor rated kW
        voltage: System voltage
        source_kva: Source (transformer/generator) kVA
        source_impedance_pct: Source impedance (%)
        starting_method: DOL, Soft Starter, VFD, Star-Delta, etc.
        lra_multiplier: LRA/FLA ratio
        application: Application type for impact assessment

    Returns:
        dict with complete starting analysis
    """
    # Calculate motor starting current
    motor = calc_motor_starting_current(
        motor_kw, voltage, lra_multiplier=lra_multiplier
    )

    # Adjust for starting method
    starting_method_factors = {
        "DOL": 1.0,
        "STAR_DELTA": 0.33,  # 1/3 of DOL current
        "AUTOTRANSFORMER_65": 0.42,  # 65% tap
        "AUTOTRANSFORMER_80": 0.64,  # 80% tap
        "SOFT_STARTER": 0.40,  # Typical 40% starting current
        "VFD": 0.0  # No inrush with VFD
    }

    method_factor = starting_method_factors.get(starting_method.upper().replace("-", "_").replace(" ", "_"), 1.0)
    effective_starting_kva = motor["starting_kva"] * method_factor

    # Calculate voltage dip
    vdip = calc_voltage_dip(
        effective_starting_kva, source_kva, source_impedance_pct
    )

    # Assess impact
    impact = assess_voltage_dip_impact(vdip["voltage_dip_pct"], application)

    return {
        "motor_kw": motor_kw,
        "motor_fla_a": motor["fla_a"],
        "motor_lra_a": motor["lra_a"],
        "starting_method": starting_method,
        "method_current_factor": method_factor,
        "effective_starting_kva": round(effective_starting_kva, 0),
        "source_kva": source_kva,
        "source_impedance_pct": source_impedance_pct,
        "voltage_dip_pct": vdip["voltage_dip_pct"],
        "voltage_during_start_pct": vdip["voltage_during_start_pct"],
        "impact_level": impact["impact_level"],
        "effects": impact["effects"],
        "recommended_action": impact["recommended_action"],
        "acceptable": impact["acceptable"]
    }


def recommend_starting_method(
    motor_kw: float,
    voltage: float,
    source_kva: float,
    source_impedance_pct: float,
    max_voltage_dip_pct: float = 15,
    load_type: str = "pump"
) -> dict:
    """
    Recommend motor starting method based on voltage dip limits.

    Args:
        motor_kw: Motor rated kW
        voltage: System voltage
        source_kva: Source kVA
        source_impedance_pct: Source impedance
        max_voltage_dip_pct: Maximum acceptable voltage dip
        load_type: Type of load (pump, fan, conveyor, etc.)

    Returns:
        dict with starting method recommendation
    """
    # Test each starting method
    methods_to_test = ["DOL", "SOFT_STARTER", "VFD"]

    # Add star-delta for suitable applications
    if motor_kw >= 7.5:  # Star-delta typically for larger motors
        methods_to_test.insert(1, "STAR_DELTA")

    results = []
    recommended = None

    for method in methods_to_test:
        analysis = analyze_motor_starting(
            motor_kw, voltage, source_kva, source_impedance_pct,
            starting_method=method
        )

        results.append({
            "method": method,
            "voltage_dip_pct": analysis["voltage_dip_pct"],
            "acceptable": analysis["voltage_dip_pct"] <= max_voltage_dip_pct
        })

        if recommended is None and analysis["voltage_dip_pct"] <= max_voltage_dip_pct:
            recommended = method

    # Load-type specific recommendations
    load_recommendations = {
        "pump": "VFD preferred for centrifugal pumps (energy savings, soft start)",
        "fan": "VFD preferred for variable flow (energy savings)",
        "conveyor": "Soft starter good for high inertia loads",
        "compressor": "Soft starter or VFD depending on type",
        "mixer": "Soft starter for high inertia, VFD for variable speed"
    }

    return {
        "motor_kw": motor_kw,
        "source_kva": source_kva,
        "max_voltage_dip_pct": max_voltage_dip_pct,
        "recommended_method": recommended or "VFD",
        "analysis_results": results,
        "load_type": load_type,
        "load_recommendation": load_recommendations.get(load_type.lower(), ""),
        "notes": (
            f"DOL starting causes {results[0]['voltage_dip_pct']:.1f}% dip. " +
            (f"{recommended} recommended." if recommended else "VFD required to meet voltage dip limit.")
        )
    }


def check_sequential_starting(
    motors: list[dict],
    source_kva: float,
    source_impedance_pct: float,
    max_voltage_dip_pct: float = 15,
    voltage: float = 400
) -> dict:
    """
    Check if sequential starting is required for multiple large motors.

    Args:
        motors: List of motor dicts with 'rated_kw' and optionally 'starting_method'
        source_kva: Source kVA
        source_impedance_pct: Source impedance
        max_voltage_dip_pct: Maximum acceptable voltage dip
        voltage: System voltage

    Returns:
        dict with sequential starting analysis
    """
    if not motors:
        return {"error": "No motors provided"}

    # Analyze each motor
    motor_analyses = []
    total_starting_kva = 0
    largest_motor = None
    largest_kw = 0

    for motor in motors:
        kw = motor.get("rated_kw", motor.get("installed_kw", 0))
        method = motor.get("starting_method", motor.get("feeder_type", "DOL"))

        if "VFD" in method.upper():
            method = "VFD"
        elif "SOFT" in method.upper():
            method = "SOFT_STARTER"
        else:
            method = "DOL"

        analysis = analyze_motor_starting(
            kw, voltage, source_kva, source_impedance_pct,
            starting_method=method
        )

        motor_analyses.append({
            "tag": motor.get("equipment_tag", motor.get("tag", "")),
            "rated_kw": kw,
            "starting_method": method,
            "starting_kva": analysis["effective_starting_kva"],
            "individual_voltage_dip_pct": analysis["voltage_dip_pct"]
        })

        total_starting_kva += analysis["effective_starting_kva"]

        if kw > largest_kw:
            largest_kw = kw
            largest_motor = motor_analyses[-1]

    # Check if largest motor alone exceeds limit
    largest_exceeds = largest_motor["individual_voltage_dip_pct"] > max_voltage_dip_pct if largest_motor else False

    # Sort by starting kVA for prioritization
    motor_analyses.sort(key=lambda x: x["starting_kva"], reverse=True)

    # Determine starting sequence
    # Motors are grouped by starting capability - multiple motors can start together
    # if their combined starting kVA doesn't exceed source capacity
    sequence = []
    current_group = 1
    group_kva_used = 0
    max_group_kva = source_kva * (max_voltage_dip_pct / 100) / (source_impedance_pct / 100)

    for motor in motor_analyses:
        # VFD motors have minimal starting impact - can always start together
        if motor["starting_method"] == "VFD":
            sequence.append({"motor": motor["tag"], "group": current_group, "starting_method": "VFD"})
        elif motor["starting_kva"] + group_kva_used <= max_group_kva:
            # Motor fits in current group
            sequence.append({"motor": motor["tag"], "group": current_group})
            group_kva_used += motor["starting_kva"]
        else:
            # Need new starting group
            current_group += 1
            group_kva_used = motor["starting_kva"]
            sequence.append({"motor": motor["tag"], "group": current_group, "wait_required": True})

    # Sequential starting required if multiple groups OR largest motor exceeds limit
    num_groups = len(set(s.get("group", 1) for s in sequence))
    sequential_required = num_groups > 1 or largest_exceeds

    return {
        "motor_count": len(motors),
        "source_kva": source_kva,
        "max_voltage_dip_pct": max_voltage_dip_pct,
        "largest_motor_kw": largest_kw,
        "largest_motor_tag": largest_motor["tag"] if largest_motor else "",
        "largest_motor_dip_pct": largest_motor["individual_voltage_dip_pct"] if largest_motor else 0,
        "total_starting_kva": round(total_starting_kva, 0),
        "sequential_start_required": sequential_required,
        "motor_analyses": motor_analyses,
        "recommended_sequence": sequence if sequential_required else None,
        "notes": (
            f"Largest motor {largest_kw} kW causes {largest_motor['individual_voltage_dip_pct']:.1f}% dip. " +
            ("Sequential starting required." if sequential_required else "Simultaneous starting OK.")
        )
    }


if __name__ == "__main__":
    print("Testing motor_starting module...")
    print("=" * 60)

    # Test motor starting current
    print("\n1. Motor Starting Current")
    motor = calc_motor_starting_current(110, 400)
    print(f"   110 kW motor @ 400V:")
    print(f"   FLA: {motor['fla_a']}A")
    print(f"   LRA: {motor['lra_a']}A")
    print(f"   Starting kVA: {motor['starting_kva']}")

    # Test voltage dip calculation
    print("\n2. Voltage Dip Calculation")
    vdip = calc_voltage_dip(780, 1000, 5.75)
    print(f"   780 kVA starting on 1000 kVA transformer (5.75% Z):")
    print(f"   Voltage dip: {vdip['voltage_dip_pct']}%")

    # Test impact assessment
    print("\n3. Voltage Dip Impact")
    impact = assess_voltage_dip_impact(18, "general")
    print(f"   18% dip impact: {impact['impact_level']}")
    print(f"   Effects: {impact['effects'][0]}")
    print(f"   Action: {impact['recommended_action']}")

    # Test complete analysis
    print("\n4. Complete Motor Starting Analysis")
    analysis = analyze_motor_starting(
        motor_kw=110,
        voltage=400,
        source_kva=1000,
        source_impedance_pct=5.75,
        starting_method="DOL"
    )
    print(f"   DOL starting: {analysis['voltage_dip_pct']}% dip - {analysis['impact_level']}")

    analysis_ss = analyze_motor_starting(
        motor_kw=110,
        voltage=400,
        source_kva=1000,
        source_impedance_pct=5.75,
        starting_method="SOFT_STARTER"
    )
    print(f"   Soft starter: {analysis_ss['voltage_dip_pct']}% dip - {analysis_ss['impact_level']}")

    # Test starting method recommendation
    print("\n5. Starting Method Recommendation")
    rec = recommend_starting_method(
        motor_kw=110,
        voltage=400,
        source_kva=750,
        source_impedance_pct=5.75,
        max_voltage_dip_pct=15
    )
    print(f"   Recommended: {rec['recommended_method']}")
    print(f"   Notes: {rec['notes']}")

    # Test sequential starting check
    print("\n6. Sequential Starting Check")
    motors = [
        {"equipment_tag": "200-B-01A", "rated_kw": 110, "feeder_type": "VFD"},
        {"equipment_tag": "200-B-01B", "rated_kw": 110, "feeder_type": "VFD"},
        {"equipment_tag": "200-P-01A", "rated_kw": 37, "feeder_type": "DOL"},
        {"equipment_tag": "200-AG-01", "rated_kw": 22, "feeder_type": "VFD"},
    ]
    seq = check_sequential_starting(motors, 1000, 5.75, 15, 400)
    print(f"   Sequential required: {seq['sequential_start_required']}")
    print(f"   Largest motor dip: {seq['largest_motor_dip_pct']}%")

    print("\n" + "=" * 60)
    print("All tests completed!")
