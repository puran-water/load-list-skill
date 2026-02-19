#!/usr/bin/env python3
"""
Feeder Sizing Module
NEC 430.24 (conductor) and NEC 430.62 (OCPD) calculations.

Implements motor feeder circuit sizing per:
- NEC 430.24: Feeder conductor sizing (ampacity)
- NEC 430.62: Feeder OCPD sizing (short-circuit/ground-fault protection)

These formulas apply to feeders supplying multiple motors (e.g., MCC incoming).

Author: Load List Skill
Standards: NEC 2023 Article 430
"""

from typing import Optional

# Standard OCPD sizes per NEC 240.6
STANDARD_OCPD_SIZES = [
    15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100,
    110, 125, 150, 175, 200, 225, 250, 300, 350, 400,
    450, 500, 600, 700, 800, 1000, 1200, 1600, 2000,
    2500, 3000, 4000, 5000, 6000
]


def calc_feeder_conductor_ampacity(
    motors: list[dict],
    non_motor_continuous_a: float = 0,
    non_motor_noncontinuous_a: float = 0
) -> dict:
    """
    Calculate minimum feeder conductor ampacity per NEC 430.24.

    NEC 430.24 Formula:
    Ampacity ≥ 125% × (largest motor FLC)
             + Σ(all other motor FLCs)
             + 125% × (non-motor continuous loads)
             + (non-motor non-continuous loads)

    Args:
        motors: List of motor dicts with 'flc_table_a' field
                Each dict should have: {'flc_table_a': float, 'tag': str (optional)}
        non_motor_continuous_a: Non-motor continuous load current (A)
        non_motor_noncontinuous_a: Non-motor non-continuous load current (A)

    Returns:
        dict with:
        - min_ampacity_a: Minimum feeder conductor ampacity
        - largest_motor_flc_a: Largest motor FLC
        - sum_other_motors_a: Sum of other motor FLCs
        - code_reference: "NEC 430.24"
    """
    if not motors:
        return {
            "min_ampacity_a": 0,
            "largest_motor_flc_a": 0,
            "sum_other_motors_a": 0,
            "motor_count": 0,
            "code_reference": "NEC 430.24",
            "calculation": "No motors",
            "notes": "No motors in feeder"
        }

    # Extract FLCs and sort descending
    motor_flcs = sorted(
        [(m.get('flc_table_a', 0), m.get('tag', 'unknown')) for m in motors],
        key=lambda x: x[0],
        reverse=True
    )

    largest_flc, largest_tag = motor_flcs[0]
    other_flcs = sum(flc for flc, _ in motor_flcs[1:])

    # NEC 430.24 formula
    min_ampacity = (
        1.25 * largest_flc +
        other_flcs +
        1.25 * non_motor_continuous_a +
        non_motor_noncontinuous_a
    )

    calculation_parts = [f"125% × {largest_flc}A (largest)"]
    if other_flcs > 0:
        calculation_parts.append(f"+ {other_flcs}A (other motors)")
    if non_motor_continuous_a > 0:
        calculation_parts.append(f"+ 125% × {non_motor_continuous_a}A (continuous)")
    if non_motor_noncontinuous_a > 0:
        calculation_parts.append(f"+ {non_motor_noncontinuous_a}A (non-continuous)")

    return {
        "min_ampacity_a": round(min_ampacity, 1),
        "largest_motor_flc_a": largest_flc,
        "largest_motor_tag": largest_tag,
        "sum_other_motors_a": other_flcs,
        "non_motor_continuous_a": non_motor_continuous_a,
        "non_motor_noncontinuous_a": non_motor_noncontinuous_a,
        "motor_count": len(motors),
        "code_reference": "NEC 430.24",
        "calculation": " ".join(calculation_parts) + f" = {min_ampacity:.1f}A",
        "notes": "Feeder conductor ampacity - use TABLE FLC values, not nameplate FLA"
    }


def calc_feeder_ocpd_max(
    motors: list[dict],
    non_motor_continuous_a: float = 0,
    non_motor_noncontinuous_a: float = 0
) -> dict:
    """
    Calculate maximum feeder OCPD rating per NEC 430.62(A).

    NEC 430.62(A) Formula:
    Max OCPD = (largest motor branch SCPD per 430.52)
             + Σ(all other motor FLCs)
             + non-motor loads

    The feeder OCPD must NOT exceed this calculated value.
    Select standard size that does NOT exceed (no "next size up" at feeder level).

    Args:
        motors: List of motor dicts with:
                - 'flc_table_a': Motor FLC from tables
                - 'branch_scpd_rating_a': Branch circuit SCPD rating per 430.52
                Each should have: {'flc_table_a': float, 'branch_scpd_rating_a': float}
        non_motor_continuous_a: Non-motor continuous load current (A)
        non_motor_noncontinuous_a: Non-motor non-continuous load current (A)

    Returns:
        dict with:
        - max_rating_a: Maximum feeder OCPD rating
        - selected_rating_a: Recommended standard size (≤ max)
        - code_reference: "NEC 430.62(A)"
    """
    if not motors:
        return {
            "max_rating_a": 0,
            "selected_rating_a": 0,
            "largest_motor_scpd_a": 0,
            "sum_other_motors_a": 0,
            "motor_count": 0,
            "code_reference": "NEC 430.62(A)",
            "calculation": "No motors",
            "notes": "No motors in feeder"
        }

    # Find largest motor by branch SCPD rating per NEC 430.62
    motor_data = sorted(
        [(m.get('flc_table_a', 0), m.get('branch_scpd_rating_a', 0), m.get('tag', 'unknown'))
         for m in motors],
        key=lambda x: x[1],
        reverse=True
    )

    largest_flc, largest_scpd, largest_tag = motor_data[0]

    # Sum of OTHER motor FLCs (not SCPDs)
    other_flcs = sum(flc for flc, _, _ in motor_data[1:])

    # Non-motor loads (add at 100%, not 125% for OCPD)
    non_motor_total = non_motor_continuous_a + non_motor_noncontinuous_a

    # NEC 430.62(A) formula
    max_rating = largest_scpd + other_flcs + non_motor_total

    # Select standard size that does NOT exceed max
    # Note: Unlike 430.52, there is NO "next size up" rule for feeders
    selected = max((s for s in STANDARD_OCPD_SIZES if s <= max_rating), default=STANDARD_OCPD_SIZES[0])

    calculation_parts = [f"{largest_scpd}A (largest motor SCPD)"]
    if other_flcs > 0:
        calculation_parts.append(f"+ {other_flcs}A (other motor FLCs)")
    if non_motor_total > 0:
        calculation_parts.append(f"+ {non_motor_total}A (non-motor)")

    return {
        "max_rating_a": round(max_rating, 1),
        "selected_rating_a": int(selected),
        "largest_motor_flc_a": largest_flc,
        "largest_motor_scpd_a": largest_scpd,
        "largest_motor_tag": largest_tag,
        "sum_other_motors_a": other_flcs,
        "non_motor_total_a": non_motor_total,
        "motor_count": len(motors),
        "code_reference": "NEC 430.62(A)",
        "calculation": " ".join(calculation_parts) + f" = {max_rating:.1f}A max",
        "notes": "Feeder OCPD - select standard size ≤ calculated max (NO next-size-up rule)"
    }


def size_mcc_feeder(
    motors: list[dict],
    voltage: float = 480,
    phases: int = 3,
    power_factor: float = 0.85,
    demand_diversity: float = 1.0
) -> dict:
    """
    Complete MCC feeder sizing per NEC 430.24 and 430.62.

    Args:
        motors: List of motor dicts with flc_table_a and branch_scpd_rating_a
        voltage: System voltage (V)
        phases: Number of phases
        power_factor: Average power factor
        demand_diversity: Panel diversity factor (for informational comparison)

    Returns:
        dict with complete feeder sizing
    """
    import math

    # Calculate conductor ampacity per 430.24
    conductor_result = calc_feeder_conductor_ampacity(motors)

    # Calculate OCPD max per 430.62
    ocpd_result = calc_feeder_ocpd_max(motors)

    # Calculate total motor FLC for reference
    total_flc = sum(m.get('flc_table_a', 0) for m in motors)

    # Calculate approximate kVA and kW
    if phases == 3:
        kva = (conductor_result['min_ampacity_a'] * math.sqrt(3) * voltage) / 1000
    else:
        kva = (conductor_result['min_ampacity_a'] * voltage) / 1000
    kw = kva * power_factor

    return {
        "feeder_conductor_min_a": conductor_result['min_ampacity_a'],
        "feeder_ocpd_max_a": ocpd_result['max_rating_a'],
        "feeder_ocpd_selected_a": ocpd_result['selected_rating_a'],
        "largest_motor_flc_a": conductor_result['largest_motor_flc_a'],
        "largest_motor_tag": conductor_result.get('largest_motor_tag'),
        "largest_motor_scpd_a": ocpd_result['largest_motor_scpd_a'],
        "total_motor_flc_a": total_flc,
        "motor_count": len(motors),
        "voltage_v": voltage,
        "estimated_kva": round(kva, 1),
        "estimated_kw": round(kw, 1),
        "conductor_sizing": conductor_result,
        "ocpd_sizing": ocpd_result,
        "code_references": ["NEC 430.24", "NEC 430.62(A)"]
    }


def select_standard_bus_rating(min_ampacity: float) -> str:
    """
    Select standard bus bar rating for MCC.

    Args:
        min_ampacity: Minimum required ampacity

    Returns:
        Standard bus rating string
    """
    standard_bus_ratings = [400, 630, 800, 1000, 1600, 2000, 2500, 3200]

    for rating in standard_bus_ratings:
        if rating >= min_ampacity:
            return f"{rating}A"

    return f">{standard_bus_ratings[-1]}A"


def select_main_breaker(
    feeder_ocpd_max: float,
    feeder_conductor_min: float
) -> dict:
    """
    Select main breaker rating for MCC.

    Selection rules:
    1. Must not exceed feeder_ocpd_max per NEC 430.62
    2. Should be adequate for feeder conductor protection
    3. Select from standard sizes

    Args:
        feeder_ocpd_max: Maximum OCPD per 430.62
        feeder_conductor_min: Minimum conductor ampacity per 430.24

    Returns:
        dict with main breaker selection
    """
    # Select largest standard size that doesn't exceed max
    selected = max((s for s in STANDARD_OCPD_SIZES if s <= feeder_ocpd_max), default=STANDARD_OCPD_SIZES[0])

    # Check if selected breaker is adequate for conductor
    conductor_adequate = selected >= feeder_conductor_min * 0.8  # Allow some margin

    return {
        "selected_rating_a": int(selected),
        "max_allowed_a": round(feeder_ocpd_max, 0),
        "conductor_min_a": round(feeder_conductor_min, 0),
        "conductor_adequate": conductor_adequate,
        "notes": (
            "Main breaker ≤ 430.62 max. "
            "Bus rating should be ≥ conductor min ampacity."
        )
    }


def validate_mcc_feeder(
    motors: list[dict],
    installed_main_breaker_a: float,
    installed_bus_rating_a: float,
    installed_conductor_ampacity_a: float
) -> dict:
    """
    Validate MCC feeder installation against NEC requirements.

    Args:
        motors: List of motor dicts
        installed_main_breaker_a: Installed main breaker rating
        installed_bus_rating_a: Installed bus bar rating
        installed_conductor_ampacity_a: Installed conductor ampacity

    Returns:
        dict with validation results
    """
    # Calculate requirements
    conductor_req = calc_feeder_conductor_ampacity(motors)
    ocpd_req = calc_feeder_ocpd_max(motors)

    issues = []

    # Check conductor ampacity (430.24)
    if installed_conductor_ampacity_a < conductor_req['min_ampacity_a']:
        issues.append({
            "code": "430.24",
            "issue": f"Conductor ampacity {installed_conductor_ampacity_a}A < required {conductor_req['min_ampacity_a']}A",
            "severity": "violation"
        })

    # Check OCPD rating (430.62)
    if installed_main_breaker_a > ocpd_req['max_rating_a']:
        issues.append({
            "code": "430.62",
            "issue": f"Main breaker {installed_main_breaker_a}A > maximum {ocpd_req['max_rating_a']}A",
            "severity": "violation"
        })

    # Check bus rating (should match or exceed conductor requirement)
    if installed_bus_rating_a < conductor_req['min_ampacity_a']:
        issues.append({
            "code": "bus_rating",
            "issue": f"Bus rating {installed_bus_rating_a}A < conductor requirement {conductor_req['min_ampacity_a']}A",
            "severity": "warning"
        })

    return {
        "installed_main_breaker_a": installed_main_breaker_a,
        "installed_bus_rating_a": installed_bus_rating_a,
        "installed_conductor_ampacity_a": installed_conductor_ampacity_a,
        "required_conductor_min_a": conductor_req['min_ampacity_a'],
        "required_ocpd_max_a": ocpd_req['max_rating_a'],
        "compliant": len([i for i in issues if i['severity'] == 'violation']) == 0,
        "issues": issues
    }


if __name__ == "__main__":
    print("Testing feeder_sizing module...")
    print("=" * 60)

    # Sample motors for testing
    motors = [
        {"tag": "200-B-01A", "flc_table_a": 195, "branch_scpd_rating_a": 350},
        {"tag": "200-B-01B", "flc_table_a": 195, "branch_scpd_rating_a": 350},
        {"tag": "200-B-01C", "flc_table_a": 195, "branch_scpd_rating_a": 350},
        {"tag": "200-AG-01", "flc_table_a": 41, "branch_scpd_rating_a": 80},
        {"tag": "200-AG-02", "flc_table_a": 41, "branch_scpd_rating_a": 80},
        {"tag": "200-P-01A", "flc_table_a": 65, "branch_scpd_rating_a": 125},
        {"tag": "200-P-01B", "flc_table_a": 65, "branch_scpd_rating_a": 125},
    ]

    # Test conductor sizing
    print("\n1. Feeder Conductor Sizing (NEC 430.24)")
    cond = calc_feeder_conductor_ampacity(motors)
    print(f"   Motor count: {cond['motor_count']}")
    print(f"   Largest motor: {cond['largest_motor_flc_a']}A ({cond['largest_motor_tag']})")
    print(f"   Other motors sum: {cond['sum_other_motors_a']}A")
    print(f"   Min conductor ampacity: {cond['min_ampacity_a']}A")
    print(f"   Calculation: {cond['calculation']}")

    # Test OCPD sizing
    print("\n2. Feeder OCPD Sizing (NEC 430.62)")
    ocpd = calc_feeder_ocpd_max(motors)
    print(f"   Largest motor SCPD: {ocpd['largest_motor_scpd_a']}A")
    print(f"   Other motors FLC: {ocpd['sum_other_motors_a']}A")
    print(f"   Max OCPD: {ocpd['max_rating_a']}A")
    print(f"   Selected: {ocpd['selected_rating_a']}A")
    print(f"   Calculation: {ocpd['calculation']}")

    # Test complete feeder sizing
    print("\n3. Complete MCC Feeder Sizing")
    feeder = size_mcc_feeder(motors, voltage=480)
    print(f"   Conductor min: {feeder['feeder_conductor_min_a']}A")
    print(f"   OCPD max: {feeder['feeder_ocpd_max_a']}A")
    print(f"   OCPD selected: {feeder['feeder_ocpd_selected_a']}A")
    print(f"   Estimated kVA: {feeder['estimated_kva']}")

    # Test bus and breaker selection
    print("\n4. Bus and Main Breaker Selection")
    bus = select_standard_bus_rating(feeder['feeder_conductor_min_a'])
    print(f"   Bus rating: {bus}")
    main = select_main_breaker(feeder['feeder_ocpd_max_a'], feeder['feeder_conductor_min_a'])
    print(f"   Main breaker: {main['selected_rating_a']}A")

    # Test validation
    print("\n5. Installation Validation")
    val = validate_mcc_feeder(
        motors,
        installed_main_breaker_a=1000,
        installed_bus_rating_a=1600,
        installed_conductor_ampacity_a=1000
    )
    print(f"   Compliant: {val['compliant']}")
    if val['issues']:
        for issue in val['issues']:
            print(f"   {issue['severity']}: {issue['issue']}")

    print("\n" + "=" * 60)
    print("All tests completed!")
