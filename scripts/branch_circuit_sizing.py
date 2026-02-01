#!/usr/bin/env python3
"""
Branch Circuit Sizing Module
NEC 430.22 (conductor) and NEC 430.52 (SCPD) calculations.

Implements motor branch circuit sizing per:
- NEC 430.22: Branch circuit conductor sizing
- NEC 430.52: Branch circuit short-circuit and ground-fault protection

Key Distinction (NEC 430.6(A)(1)):
- Use TABLE FLC (from NEC 430.250) for conductor and SCPD sizing
- Use NAMEPLATE FLA for overload settings (see overload_sizing.py)

Author: Load List Skill
Standards: NEC 2023 Article 430
"""

import math
from pathlib import Path
from typing import Optional, Literal

import yaml


# Standard OCPD sizes per NEC 240.6
STANDARD_OCPD_SIZES = [
    15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100,
    110, 125, 150, 175, 200, 225, 250, 300, 350, 400,
    450, 500, 600, 700, 800, 1000, 1200, 1600, 2000,
    2500, 3000, 4000, 5000, 6000
]


def load_catalog(name: str) -> dict:
    """Load a YAML catalog file."""
    catalogs_dir = Path(__file__).parent.parent / "catalogs"
    path = catalogs_dir / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Catalog not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def calc_branch_conductor_ampacity(motor_flc: float) -> dict:
    """
    Calculate minimum branch circuit conductor ampacity per NEC 430.22(A).

    NEC 430.22(A): Branch-circuit conductors supplying a single motor
    shall have an ampacity not less than 125% of the motor FLC.

    Args:
        motor_flc: Motor Full Load Current from NEC tables (430.247-430.250)
                   NOT nameplate FLA

    Returns:
        dict with:
        - min_ampacity_a: Minimum conductor ampacity
        - motor_flc_a: Input FLC value
        - multiplier: 1.25 (125%)
        - code_reference: "NEC 430.22(A)"
    """
    min_ampacity = 1.25 * motor_flc

    return {
        "min_ampacity_a": round(min_ampacity, 1),
        "motor_flc_a": motor_flc,
        "multiplier": 1.25,
        "code_reference": "NEC 430.22(A)",
        "notes": "Branch conductor ampacity ≥ 125% × motor FLC (table value)"
    }


def calc_branch_scpd_max(
    motor_flc: float,
    device_type: Literal[
        "dual_element_fuse",
        "non_time_delay_fuse",
        "inverse_time_cb",
        "instantaneous_trip_cb"
    ] = "dual_element_fuse",
    use_exception: bool = False,
    design_b_energy_efficient: bool = False
) -> dict:
    """
    Calculate maximum branch circuit SCPD rating per NEC 430.52.

    NEC 430.52: Maximum ratings based on percentage of motor FLC,
    with next-size-up rule per 430.52(C)(1) Exception 1.

    Args:
        motor_flc: Motor Full Load Current from NEC tables
        device_type: Type of protective device
        use_exception: Use higher percentage if standard is insufficient for starting
        design_b_energy_efficient: For instantaneous-trip, motor is Design B energy-efficient

    Returns:
        dict with:
        - max_rating_a: Maximum SCPD rating
        - calculated_a: Raw calculated value before standard size selection
        - motor_flc_a: Input FLC
        - device_type: Device type used
        - percentage: Percentage applied
        - code_reference: NEC section reference
    """
    # Device type percentages per NEC Table 430.52
    device_limits = {
        "dual_element_fuse": {
            "max_pct": 175,
            "exception_pct": 225,
            "description": "Dual-element time-delay fuse"
        },
        "non_time_delay_fuse": {
            "max_pct": 300,
            "exception_pct": 400,
            "description": "Non-time-delay fuse"
        },
        "inverse_time_cb": {
            "max_pct": 250,
            "exception_pct": 400,
            "description": "Inverse time circuit breaker"
        },
        "instantaneous_trip_cb": {
            "max_pct": 800,
            "exception_pct": 1100,
            "exception_pct_design_b": 1300,
            "description": "Instantaneous trip circuit breaker (MCP)"
        }
    }

    limits = device_limits.get(device_type, device_limits["dual_element_fuse"])

    # Select percentage
    if device_type == "instantaneous_trip_cb":
        if use_exception:
            pct = limits["exception_pct_design_b"] if design_b_energy_efficient else limits["exception_pct"]
        else:
            pct = limits["max_pct"]
    else:
        pct = limits["exception_pct"] if use_exception else limits["max_pct"]

    # Calculate raw value
    calculated = motor_flc * (pct / 100)

    # Apply next-size-up rule (430.52(C)(1) Exception 1)
    # Does NOT apply to instantaneous-trip devices
    if device_type != "instantaneous_trip_cb":
        max_rating = next((s for s in STANDARD_OCPD_SIZES if s >= calculated), calculated)
    else:
        # For MCP, rating is adjustable - return calculated max
        max_rating = calculated

    return {
        "max_rating_a": round(max_rating, 0),
        "calculated_a": round(calculated, 1),
        "motor_flc_a": motor_flc,
        "device_type": device_type,
        "device_description": limits["description"],
        "percentage": pct,
        "use_exception": use_exception,
        "next_size_up_applied": device_type != "instantaneous_trip_cb",
        "code_reference": "NEC 430.52, Table 430.52",
        "notes": f"{pct}% × {motor_flc}A FLC = {calculated:.1f}A"
    }


def select_branch_scpd(
    motor_flc: float,
    motor_lra: Optional[float] = None,
    device_type: Literal[
        "dual_element_fuse",
        "non_time_delay_fuse",
        "inverse_time_cb",
        "instantaneous_trip_cb"
    ] = "dual_element_fuse",
    vfd_max_scpd: Optional[float] = None,
    try_exception_if_needed: bool = True
) -> dict:
    """
    Select branch circuit SCPD rating considering all constraints.

    Selection logic:
    1. Calculate maximum per NEC 430.52
    2. Check if VFD manufacturer limit is lower
    3. Verify selected size can handle starting inrush
    4. Apply exception if needed and permitted

    Args:
        motor_flc: Motor FLC from NEC tables
        motor_lra: Motor Locked Rotor Amps (for starting check)
        device_type: Type of protective device
        vfd_max_scpd: VFD manufacturer maximum SCPD (if VFD application)
        try_exception_if_needed: Allow exception percentage if standard insufficient

    Returns:
        dict with selected SCPD rating and sizing basis
    """
    # Calculate maximum per 430.52 (without exception first)
    result = calc_branch_scpd_max(motor_flc, device_type, use_exception=False)
    max_rating = result["max_rating_a"]

    # Check VFD limit
    vfd_limited = False
    if vfd_max_scpd and vfd_max_scpd < max_rating:
        max_rating = vfd_max_scpd
        vfd_limited = True

    # Select from standard sizes
    selected = next((s for s in STANDARD_OCPD_SIZES if s >= motor_flc and s <= max_rating), max_rating)

    # Check if starting inrush is a concern
    starting_concern = False
    exception_used = False

    if motor_lra and device_type != "instantaneous_trip_cb":
        # For time-delay fuses and inverse-time breakers,
        # verify selection can handle motor starting
        # Rule of thumb: SCPD should be > 50% of LRA for reliable starting
        if selected < motor_lra * 0.5:
            starting_concern = True

            if try_exception_if_needed and not vfd_limited:
                # Try with exception
                result_exc = calc_branch_scpd_max(motor_flc, device_type, use_exception=True)
                max_with_exc = result_exc["max_rating_a"]
                selected_exc = next((s for s in STANDARD_OCPD_SIZES if s >= motor_lra * 0.5 and s <= max_with_exc), None)

                if selected_exc:
                    selected = selected_exc
                    exception_used = True
                    result = result_exc

    return {
        "selected_rating_a": int(selected),
        "max_allowed_a": int(result["max_rating_a"]),
        "motor_flc_a": motor_flc,
        "motor_lra_a": motor_lra,
        "device_type": device_type,
        "vfd_limited": vfd_limited,
        "vfd_max_scpd_a": vfd_max_scpd,
        "exception_used": exception_used,
        "starting_concern": starting_concern,
        "code_reference": "NEC 430.52",
        "sizing_basis": f"NEC 430.52: {result['percentage']}% × {motor_flc}A FLC = {result['calculated_a']}A, "
                       f"selected {selected}A" + (" (VFD limited)" if vfd_limited else "") +
                       (" (exception applied)" if exception_used else "")
    }


def select_branch_scpd_for_vfd(
    motor_flc: float,
    vfd_input_current: float,
    vfd_max_scpd: Optional[float] = None,
    device_type: Literal["dual_element_fuse", "inverse_time_cb"] = "dual_element_fuse"
) -> dict:
    """
    Select branch circuit SCPD for VFD application per NEC 430.130.

    NEC 430.130: The SCPD shall be sized based on motor FLC per 430.52,
    unless the VFD is marked with specific requirements.

    Args:
        motor_flc: Motor FLC from NEC tables
        vfd_input_current: VFD rated input current
        vfd_max_scpd: VFD manufacturer maximum SCPD (from VFD marking)
        device_type: Type of protective device

    Returns:
        dict with VFD SCPD selection
    """
    # Per 430.52, use motor FLC for sizing
    result = calc_branch_scpd_max(motor_flc, device_type, use_exception=False)
    max_nec = result["max_rating_a"]

    # VFD manufacturer limit takes precedence
    if vfd_max_scpd:
        max_rating = min(max_nec, vfd_max_scpd)
        limited_by = "vfd_marking" if vfd_max_scpd < max_nec else "nec_430_52"
    else:
        max_rating = max_nec
        limited_by = "nec_430_52"

    # Select from standard sizes
    selected = next((s for s in STANDARD_OCPD_SIZES if s >= vfd_input_current and s <= max_rating), max_rating)

    return {
        "selected_rating_a": int(selected),
        "max_per_nec_a": int(max_nec),
        "max_per_vfd_a": vfd_max_scpd,
        "limited_by": limited_by,
        "motor_flc_a": motor_flc,
        "vfd_input_current_a": vfd_input_current,
        "device_type": device_type,
        "code_reference": "NEC 430.130, 430.52",
        "sizing_basis": f"NEC 430.130/430.52: Max {max_rating}A, selected {selected}A for VFD input {vfd_input_current}A"
    }


def get_recommended_fuse_class(
    sccr_required_ka: float,
    current_limiting_required: bool = True
) -> str:
    """
    Recommend fuse class based on SCCR requirements.

    Args:
        sccr_required_ka: Required SCCR rating in kA
        current_limiting_required: Whether current limitation is required

    Returns:
        Recommended fuse class
    """
    if sccr_required_ka >= 100 or current_limiting_required:
        return "J"  # Class J provides best current limitation
    elif sccr_required_ka >= 50:
        return "RK1"  # Class RK1 time-delay, current-limiting
    else:
        return "RK5"  # Class RK5 time-delay


def validate_branch_circuit(
    motor_flc: float,
    conductor_ampacity: float,
    scpd_rating: float,
    device_type: str
) -> dict:
    """
    Validate branch circuit sizing against NEC requirements.

    Args:
        motor_flc: Motor FLC from NEC tables
        conductor_ampacity: Installed conductor ampacity
        scpd_rating: Installed SCPD rating
        device_type: Type of SCPD

    Returns:
        dict with validation results
    """
    issues = []

    # Check conductor sizing (430.22)
    min_conductor = calc_branch_conductor_ampacity(motor_flc)
    if conductor_ampacity < min_conductor["min_ampacity_a"]:
        issues.append({
            "code": "430.22",
            "issue": f"Conductor ampacity {conductor_ampacity}A < required {min_conductor['min_ampacity_a']}A",
            "severity": "violation"
        })

    # Check SCPD sizing (430.52)
    max_scpd = calc_branch_scpd_max(motor_flc, device_type, use_exception=True)
    if scpd_rating > max_scpd["max_rating_a"]:
        issues.append({
            "code": "430.52",
            "issue": f"SCPD rating {scpd_rating}A > maximum {max_scpd['max_rating_a']}A",
            "severity": "violation"
        })

    # Check SCPD ≥ conductor ampacity relationship
    # Note: SCPD can be larger than conductor per 430.52/430.22 interaction

    return {
        "motor_flc_a": motor_flc,
        "conductor_ampacity_a": conductor_ampacity,
        "scpd_rating_a": scpd_rating,
        "device_type": device_type,
        "compliant": len(issues) == 0,
        "issues": issues
    }


if __name__ == "__main__":
    print("Testing branch_circuit_sizing module...")
    print("=" * 60)

    # Test conductor sizing
    print("\n1. Branch Conductor Sizing (NEC 430.22)")
    cond = calc_branch_conductor_ampacity(65)  # 50 HP @ 460V
    print(f"   50 HP motor, FLC = 65A")
    print(f"   Min conductor ampacity: {cond['min_ampacity_a']}A")
    print(f"   Reference: {cond['code_reference']}")

    # Test SCPD sizing - dual element fuse
    print("\n2. Branch SCPD - Dual Element Fuse (NEC 430.52)")
    scpd = calc_branch_scpd_max(65, "dual_element_fuse")
    print(f"   50 HP motor, FLC = 65A")
    print(f"   175% × 65A = {scpd['calculated_a']}A")
    print(f"   Max rating (next size up): {scpd['max_rating_a']}A")

    # Test SCPD sizing - inverse time breaker
    print("\n3. Branch SCPD - Inverse Time Breaker")
    scpd = calc_branch_scpd_max(65, "inverse_time_cb")
    print(f"   250% × 65A = {scpd['calculated_a']}A")
    print(f"   Max rating (next size up): {scpd['max_rating_a']}A")

    # Test SCPD selection with LRA check
    print("\n4. SCPD Selection with Starting Check")
    sel = select_branch_scpd(65, motor_lra=390, device_type="dual_element_fuse")
    print(f"   Selected: {sel['selected_rating_a']}A")
    print(f"   Exception used: {sel['exception_used']}")
    print(f"   Sizing basis: {sel['sizing_basis']}")

    # Test VFD application
    print("\n5. VFD Application (NEC 430.130)")
    vfd = select_branch_scpd_for_vfd(
        motor_flc=195,
        vfd_input_current=207,
        vfd_max_scpd=300,
        device_type="dual_element_fuse"
    )
    print(f"   110 kW motor, VFD input 207A, max SCPD 300A")
    print(f"   Selected: {vfd['selected_rating_a']}A")
    print(f"   Limited by: {vfd['limited_by']}")

    # Test validation
    print("\n6. Branch Circuit Validation")
    val = validate_branch_circuit(
        motor_flc=65,
        conductor_ampacity=85,
        scpd_rating=125,
        device_type="dual_element_fuse"
    )
    print(f"   Compliant: {val['compliant']}")
    if val['issues']:
        for issue in val['issues']:
            print(f"   Issue: {issue['issue']}")

    print("\n" + "=" * 60)
    print("All tests completed!")
