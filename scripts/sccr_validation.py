#!/usr/bin/env python3
"""
SCCR Validation Module
Validate Short-Circuit Current Rating (SCCR) for MCC assemblies.

IMPORTANT: This provides PRELIMINARY worst-case estimates only.
Final SCCR must come from manufacturer/UL-tested lineup rating.

Standards Reference:
- UL 845 (North American MCC assembly)
- IEC 61439-1/2 (IEC LV assembly)
- NEC 110.10 (Equipment SCCR requirements)
- NEC 409.110 (Industrial Control Panel SCCR)

Author: Load List Skill
"""

import math
from typing import Optional


def calc_available_fault_current(
    transformer_kva: float,
    transformer_z_pct: float,
    secondary_voltage: float,
    utility_fault_ka: Optional[float] = None,
    cable_length_m: float = 0,
    cable_size_mm2: float = 0
) -> dict:
    """
    Calculate available fault current at a point in the system.

    For preliminary estimates, calculates based on transformer only.
    For more accuracy, includes utility contribution and cable impedance.

    Args:
        transformer_kva: Transformer kVA rating
        transformer_z_pct: Transformer impedance (%)
        secondary_voltage: Secondary voltage (V line-to-line)
        utility_fault_ka: Available fault at transformer primary (kA)
        cable_length_m: Cable length from transformer to point (m)
        cable_size_mm2: Cable conductor size (mm²)

    Returns:
        dict with fault current calculations
    """
    # Transformer base values
    i_base = transformer_kva * 1000 / (math.sqrt(3) * secondary_voltage)
    z_base = secondary_voltage ** 2 / (transformer_kva * 1000)

    # Transformer impedance in ohms
    z_xfmr_ohm = (transformer_z_pct / 100) * z_base

    # Utility impedance (if provided)
    if utility_fault_ka and utility_fault_ka > 0:
        # Utility fault at primary, reflect to secondary
        # Approximate: Z_utility = V²/(√3 × V × I_fault)
        z_utility_pu = (i_base / 1000) / utility_fault_ka
        z_utility_ohm = z_utility_pu * z_base
    else:
        z_utility_ohm = 0  # Assume infinite bus

    # Cable impedance (if provided)
    if cable_length_m > 0 and cable_size_mm2 > 0:
        # Copper resistivity at 75°C: 0.0221 Ω·mm²/m
        r_cable = 0.0221 * cable_length_m / cable_size_mm2
        x_cable = 0.00008 * cable_length_m  # Typical reactance
        z_cable_ohm = math.sqrt(r_cable ** 2 + x_cable ** 2)
    else:
        z_cable_ohm = 0

    # Total impedance
    z_total_ohm = z_xfmr_ohm + z_utility_ohm + z_cable_ohm

    # Available fault current (3-phase symmetrical)
    i_fault_a = secondary_voltage / (math.sqrt(3) * z_total_ohm)
    i_fault_ka = i_fault_a / 1000

    return {
        "transformer_kva": transformer_kva,
        "transformer_z_pct": transformer_z_pct,
        "secondary_voltage_v": secondary_voltage,
        "transformer_z_ohm": round(z_xfmr_ohm, 6),
        "utility_z_ohm": round(z_utility_ohm, 6),
        "cable_z_ohm": round(z_cable_ohm, 6),
        "total_z_ohm": round(z_total_ohm, 6),
        "available_fault_ka": round(i_fault_ka, 1),
        "available_fault_a": round(i_fault_a, 0),
        "calculation_basis": "transformer_only" if z_utility_ohm == 0 else "with_utility",
        "warning": "PRELIMINARY - verify with utility coordination study"
    }


def get_default_sccr_by_device(device_type: str, fuse_class: Optional[str] = None) -> float:
    """
    Get typical SCCR for device types.

    These are conservative estimates - actual SCCR depends on
    specific manufacturer and model.

    Args:
        device_type: Device type (fuse, mccb, mpcb, mcp)
        fuse_class: Fuse class if applicable

    Returns:
        Typical SCCR in kA
    """
    # Fuse SCCR by class
    fuse_sccr = {
        "J": 200,
        "RK1": 200,
        "RK5": 50,
        "CC": 200,
        "T": 200,
        "L": 200,
        "H": 10,
        "K": 50
    }

    # MCCB typical SCCR (varies widely by rating and manufacturer)
    mccb_sccr = {
        "standard": 14,  # Standard MCCB
        "high_interrupt": 65,  # High-interrupt MCCB
        "current_limiting": 100  # Current-limiting MCCB
    }

    if device_type.lower() == "fuse":
        return fuse_sccr.get(fuse_class, 100)
    elif device_type.lower() == "mccb":
        return mccb_sccr["standard"]  # Conservative
    elif device_type.lower() in ["mpcb", "mcp"]:
        return 65  # Typical motor circuit protector
    else:
        return 10  # Conservative default


def validate_bucket_sccr(
    bucket: dict,
    available_fault_ka: float
) -> dict:
    """
    Validate individual bucket SCCR against available fault current.

    Args:
        bucket: Bucket dict with SCCR data
        available_fault_ka: Available fault current at MCC bus

    Returns:
        dict with validation result
    """
    bucket_sccr = bucket.get("sccr_ka", 0)
    bucket_id = bucket.get("bucket_id", "Unknown")

    # If no SCCR specified, estimate from device type
    if bucket_sccr == 0:
        device_type = bucket.get("branch_scpd_type", "mccb")
        fuse_class = bucket.get("fuse_class")
        bucket_sccr = get_default_sccr_by_device(device_type, fuse_class)
        sccr_source = "estimated_from_device_type"
    else:
        sccr_source = "specified"

    compliant = bucket_sccr >= available_fault_ka
    margin_ka = bucket_sccr - available_fault_ka

    return {
        "bucket_id": bucket_id,
        "bucket_sccr_ka": bucket_sccr,
        "sccr_source": sccr_source,
        "available_fault_ka": available_fault_ka,
        "compliant": compliant,
        "margin_ka": round(margin_ka, 1),
        "status": "OK" if compliant else "INADEQUATE",
        "action_required": None if compliant else (
            f"Upgrade SCPD to achieve ≥{available_fault_ka} kA SCCR"
        )
    }


def validate_lineup_sccr(
    mcc_panel: dict,
    available_fault_ka: float
) -> dict:
    """
    Validate MCC lineup SCCR against available fault current.
    Per UL 845 / IEC 61439.

    IMPORTANT: Simple "min of bucket SCCRs" is often wrong.
    Combination ratings and assembly verification matter.
    Final SCCR must come from manufacturer/UL-tested lineup rating.

    Args:
        mcc_panel: MCC panel dict with buckets
        available_fault_ka: Available fault current at MCC bus

    Returns:
        dict with lineup SCCR validation
    """
    buckets = mcc_panel.get("buckets", [])
    panel_tag = mcc_panel.get("panel_tag", "Unknown")

    if not buckets:
        return {
            "panel_tag": panel_tag,
            "error": "No buckets defined",
            "compliant": False
        }

    # Validate each bucket
    bucket_results = []
    bucket_sccrs = []
    non_compliant_buckets = []

    for bucket in buckets:
        result = validate_bucket_sccr(bucket, available_fault_ka)
        bucket_results.append(result)
        bucket_sccrs.append(result["bucket_sccr_ka"])
        if not result["compliant"]:
            non_compliant_buckets.append(result["bucket_id"])

    # Preliminary worst-case: min of individual bucket SCCRs
    # ACTUAL lineup SCCR may differ due to combination ratings
    preliminary_sccr = min(bucket_sccrs) if bucket_sccrs else 0

    # Check if manufacturer lineup rating provided
    manufacturer_sccr = mcc_panel.get("manufacturer_lineup_sccr_ka")
    lineup_sccr = manufacturer_sccr if manufacturer_sccr else preliminary_sccr

    # Overall compliance
    compliant = lineup_sccr >= available_fault_ka

    # Find limiting bucket
    limiting_bucket = min(buckets, key=lambda b: b.get("sccr_ka", 999))
    limiting_bucket_id = limiting_bucket.get("bucket_id", "Unknown")

    return {
        "panel_tag": panel_tag,
        "bucket_count": len(buckets),
        "lineup_sccr_ka": lineup_sccr,
        "sccr_source": "manufacturer_tested" if manufacturer_sccr else "preliminary_worst_case",
        "preliminary_min_sccr_ka": preliminary_sccr,
        "available_fault_ka": available_fault_ka,
        "compliant": compliant,
        "margin_ka": round(lineup_sccr - available_fault_ka, 1),
        "limiting_bucket": limiting_bucket_id,
        "non_compliant_buckets": non_compliant_buckets,
        "bucket_results": bucket_results,
        "warning": (
            None if manufacturer_sccr
            else "SCCR is preliminary worst-case estimate. Verify with manufacturer lineup rating."
        ),
        "recommendation": (
            None if compliant
            else f"Upgrade limiting buckets or obtain manufacturer-tested lineup SCCR ≥{available_fault_ka} kA"
        )
    }


def recommend_sccr_upgrades(
    lineup_validation: dict
) -> list[dict]:
    """
    Recommend SCCR upgrades for non-compliant buckets.

    Args:
        lineup_validation: Output from validate_lineup_sccr

    Returns:
        list of upgrade recommendations
    """
    recommendations = []
    available_fault = lineup_validation["available_fault_ka"]

    for bucket_result in lineup_validation.get("bucket_results", []):
        if not bucket_result["compliant"]:
            bucket_id = bucket_result["bucket_id"]
            current_sccr = bucket_result["bucket_sccr_ka"]
            shortfall = available_fault - current_sccr

            # Recommend upgrade options
            options = []

            # Option 1: Current-limiting fuses
            if shortfall <= 186:  # Class J fuses typically 200 kA
                options.append({
                    "option": "Replace MCCB with Class J fused disconnect",
                    "expected_sccr_ka": 200,
                    "notes": "Class J fuses provide excellent current limiting"
                })

            # Option 2: High-interrupt MCCB
            if shortfall <= 47:  # High-interrupt MCCB typically 65 kA
                options.append({
                    "option": "Replace with high-interrupt MCCB",
                    "expected_sccr_ka": 65,
                    "notes": "Available from most manufacturers"
                })

            # Option 3: Current-limiting MCCB
            if shortfall <= 86:  # Current-limiting MCCB typically 100 kA
                options.append({
                    "option": "Replace with current-limiting MCCB",
                    "expected_sccr_ka": 100,
                    "notes": "Higher cost but compact solution"
                })

            # Option 4: Series rating
            options.append({
                "option": "Use UL-listed series rating combination",
                "expected_sccr_ka": "varies",
                "notes": "Coordinate with manufacturer for tested combinations"
            })

            recommendations.append({
                "bucket_id": bucket_id,
                "current_sccr_ka": current_sccr,
                "required_sccr_ka": available_fault,
                "shortfall_ka": round(shortfall, 1),
                "upgrade_options": options
            })

    return recommendations


def validate_panel_sccr_complete(
    panel: dict,
    transformer_kva: float,
    transformer_z_pct: float,
    secondary_voltage: float
) -> dict:
    """
    Complete SCCR validation workflow for a panel.

    Args:
        panel: MCC panel dict with buckets
        transformer_kva: Upstream transformer kVA
        transformer_z_pct: Transformer impedance (%)
        secondary_voltage: System voltage (V)

    Returns:
        dict with complete SCCR analysis
    """
    # Calculate available fault current
    fault = calc_available_fault_current(
        transformer_kva=transformer_kva,
        transformer_z_pct=transformer_z_pct,
        secondary_voltage=secondary_voltage
    )

    # Validate lineup SCCR
    validation = validate_lineup_sccr(
        mcc_panel=panel,
        available_fault_ka=fault["available_fault_ka"]
    )

    # Get upgrade recommendations if needed
    upgrades = []
    if not validation["compliant"]:
        upgrades = recommend_sccr_upgrades(validation)

    return {
        "panel_tag": panel.get("panel_tag", "Unknown"),
        "fault_current_analysis": fault,
        "sccr_validation": validation,
        "upgrade_recommendations": upgrades,
        "overall_status": "COMPLIANT" if validation["compliant"] else "ACTION REQUIRED",
        "disclaimers": [
            "SCCR validation is PRELIMINARY - for final design only",
            "Actual lineup SCCR requires manufacturer verification",
            "Series ratings and combination ratings may allow higher SCCR",
            "Fault current calculation assumes infinite utility bus unless specified"
        ]
    }


def format_sccr_report(analysis: dict) -> str:
    """
    Format SCCR analysis as text report.

    Args:
        analysis: Output from validate_panel_sccr_complete

    Returns:
        Formatted text report
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"SCCR VALIDATION REPORT - {analysis['panel_tag']}")
    lines.append("=" * 70)
    lines.append("")

    # Fault current
    fc = analysis["fault_current_analysis"]
    lines.append("AVAILABLE FAULT CURRENT")
    lines.append("-" * 40)
    lines.append(f"  Transformer: {fc['transformer_kva']} kVA, {fc['transformer_z_pct']}% Z")
    lines.append(f"  Secondary Voltage: {fc['secondary_voltage_v']} V")
    lines.append(f"  Available Fault: {fc['available_fault_ka']} kA")
    lines.append(f"  Calculation Basis: {fc['calculation_basis']}")
    lines.append("")

    # SCCR validation
    sv = analysis["sccr_validation"]
    lines.append("LINEUP SCCR VALIDATION")
    lines.append("-" * 40)
    lines.append(f"  Lineup SCCR: {sv['lineup_sccr_ka']} kA ({sv['sccr_source']})")
    lines.append(f"  Available Fault: {sv['available_fault_ka']} kA")
    lines.append(f"  Margin: {sv['margin_ka']} kA")
    lines.append(f"  Status: {analysis['overall_status']}")
    if sv["warning"]:
        lines.append(f"  WARNING: {sv['warning']}")
    lines.append("")

    # Non-compliant buckets
    if sv["non_compliant_buckets"]:
        lines.append("NON-COMPLIANT BUCKETS")
        lines.append("-" * 40)
        for bucket_id in sv["non_compliant_buckets"]:
            lines.append(f"  • {bucket_id}")
        lines.append("")

    # Upgrade recommendations
    if analysis["upgrade_recommendations"]:
        lines.append("UPGRADE RECOMMENDATIONS")
        lines.append("-" * 40)
        for rec in analysis["upgrade_recommendations"]:
            lines.append(f"  {rec['bucket_id']}:")
            lines.append(f"    Current SCCR: {rec['current_sccr_ka']} kA")
            lines.append(f"    Required: {rec['required_sccr_ka']} kA")
            lines.append(f"    Options:")
            for opt in rec["upgrade_options"]:
                lines.append(f"      - {opt['option']} ({opt['expected_sccr_ka']} kA)")
        lines.append("")

    # Disclaimers
    lines.append("DISCLAIMERS")
    lines.append("-" * 40)
    for disc in analysis["disclaimers"]:
        lines.append(f"  • {disc}")
    lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing sccr_validation module...")
    print("=" * 60)

    # Test fault current calculation
    print("\n1. Available Fault Current")
    fault = calc_available_fault_current(
        transformer_kva=1000,
        transformer_z_pct=5.75,
        secondary_voltage=480
    )
    print(f"   1000 kVA, 5.75% Z @ 480V")
    print(f"   Available fault: {fault['available_fault_ka']} kA")

    # Test with sample MCC panel
    print("\n2. MCC Lineup SCCR Validation")
    sample_panel = {
        "panel_tag": "MCC-200",
        "buckets": [
            {"bucket_id": "MCC-200-01", "sccr_ka": 65, "branch_scpd_type": "mccb"},
            {"bucket_id": "MCC-200-02", "sccr_ka": 65, "branch_scpd_type": "mccb"},
            {"bucket_id": "MCC-200-03", "sccr_ka": 22, "branch_scpd_type": "mccb"},
            {"bucket_id": "MCC-200-04", "sccr_ka": 65, "branch_scpd_type": "mccb"},
        ]
    }

    validation = validate_lineup_sccr(sample_panel, fault["available_fault_ka"])
    print(f"   Panel: {validation['panel_tag']}")
    print(f"   Lineup SCCR: {validation['lineup_sccr_ka']} kA ({validation['sccr_source']})")
    print(f"   Available Fault: {validation['available_fault_ka']} kA")
    print(f"   Compliant: {validation['compliant']}")
    print(f"   Limiting Bucket: {validation['limiting_bucket']}")

    # Complete analysis
    print("\n3. Complete SCCR Analysis")
    analysis = validate_panel_sccr_complete(
        panel=sample_panel,
        transformer_kva=1000,
        transformer_z_pct=5.75,
        secondary_voltage=480
    )
    print(format_sccr_report(analysis))

    print("\n" + "=" * 60)
    print("All tests completed!")
