#!/usr/bin/env python3
"""
Overload Protection Sizing Module
NEC 430.32 motor overload protection calculations.

Implements motor overload protection sizing per:
- NEC 430.32: Continuous-Duty Motors overload protection
- IEC 60947-4-1: Overload relay trip classes

Key Distinction (NEC 430.6(A)(1)):
- Use NAMEPLATE FLA for overload settings (this module)
- Use TABLE FLC for conductor and SCPD sizing (branch_circuit_sizing.py)

Author: Load List Skill
Standards: NEC 2023 Article 430, IEC 60947-4-1
"""

from typing import Optional, Literal


def calc_overload_max_setting(
    fla_nameplate: float,
    service_factor: float = 1.0,
    temp_rise_40c_or_less: bool = False
) -> dict:
    """
    Calculate maximum overload relay setting per NEC 430.32.

    NEC 430.32(A)(1): The overload device shall be selected to trip at
    no more than the following percentages of motor nameplate FLA:

    - SF ≥ 1.15 OR temp rise ≤ 40°C: 125% of nameplate FLA
    - All other motors: 115% of nameplate FLA

    Args:
        fla_nameplate: Motor nameplate Full Load Amps (NOT NEC table value)
        service_factor: Motor service factor (1.0 for IEC, 1.15 typical NEMA)
        temp_rise_40c_or_less: Whether motor temp rise marking is ≤40°C

    Returns:
        dict with:
        - max_setting_a: Maximum overload trip setting
        - fla_nameplate_a: Input nameplate FLA
        - percentage: 115% or 125%
        - basis: Which criterion applies
    """
    # Determine applicable percentage
    if service_factor >= 1.15 or temp_rise_40c_or_less:
        percentage = 125
        basis = "SF ≥ 1.15" if service_factor >= 1.15 else "Temp rise ≤ 40°C"
    else:
        percentage = 115
        basis = "SF < 1.15 and temp rise > 40°C"

    max_setting = fla_nameplate * (percentage / 100)

    return {
        "max_setting_a": round(max_setting, 1),
        "fla_nameplate_a": fla_nameplate,
        "service_factor": service_factor,
        "percentage": percentage,
        "basis": basis,
        "code_reference": "NEC 430.32(A)(1)",
        "notes": f"{percentage}% × {fla_nameplate}A = {max_setting:.1f}A maximum"
    }


def calc_overload_exception_setting(
    fla_nameplate: float,
    service_factor: float = 1.0,
    temp_rise_40c_or_less: bool = False
) -> dict:
    """
    Calculate overload setting using exception per NEC 430.32(C).

    NEC 430.32(C): If the overload relay selected in accordance with
    430.32(A)(1) is not sufficient to start the motor or to carry
    the load, higher values are permitted:

    - SF ≥ 1.15 OR temp rise ≤ 40°C: Up to 140% of nameplate FLA
    - All other motors: Up to 130% of nameplate FLA

    Args:
        fla_nameplate: Motor nameplate Full Load Amps
        service_factor: Motor service factor
        temp_rise_40c_or_less: Whether motor temp rise marking is ≤40°C

    Returns:
        dict with exception limit values
    """
    if service_factor >= 1.15 or temp_rise_40c_or_less:
        percentage = 140
        basis = "SF ≥ 1.15 (exception)"
    else:
        percentage = 130
        basis = "SF < 1.15 (exception)"

    max_setting = fla_nameplate * (percentage / 100)

    return {
        "max_setting_a": round(max_setting, 1),
        "fla_nameplate_a": fla_nameplate,
        "percentage": percentage,
        "basis": basis,
        "code_reference": "NEC 430.32(C)",
        "notes": f"Exception: {percentage}% × {fla_nameplate}A = {max_setting:.1f}A maximum",
        "warning": "Use only if standard setting does not allow motor to start or carry load"
    }


def select_overload_setting(
    fla_nameplate: float,
    service_factor: float = 1.0,
    temp_rise_40c_or_less: bool = False,
    use_exception: bool = False,
    vfd_application: bool = False
) -> dict:
    """
    Select appropriate overload relay setting.

    Args:
        fla_nameplate: Motor nameplate Full Load Amps
        service_factor: Motor service factor
        temp_rise_40c_or_less: Whether motor temp rise is ≤40°C
        use_exception: Use 430.32(C) exception limits
        vfd_application: Motor is driven by VFD

    Returns:
        dict with selected overload setting
    """
    if use_exception:
        result = calc_overload_exception_setting(
            fla_nameplate, service_factor, temp_rise_40c_or_less
        )
    else:
        result = calc_overload_max_setting(
            fla_nameplate, service_factor, temp_rise_40c_or_less
        )

    # For VFD applications, typically set to nameplate FLA
    if vfd_application:
        result["recommended_setting_a"] = fla_nameplate
        result["notes"] += "\nVFD application: Set VFD motor current parameter to nameplate FLA."
    else:
        # Set to max allowed or slightly below
        result["recommended_setting_a"] = result["max_setting_a"]

    return result


def select_overload_class(
    starting_time_sec: float,
    load_type: Optional[str] = None
) -> dict:
    """
    Select overload relay trip class per IEC 60947-4-1.

    Class indicates maximum trip time at 7.2× FLA from cold:
    - Class 5: ≤5 seconds (submersible, hermetic)
    - Class 10: ≤10 seconds (general purpose - default)
    - Class 20: ≤20 seconds (high inertia)
    - Class 30: ≤30 seconds (very high inertia)

    Args:
        starting_time_sec: Expected motor starting time in seconds
        load_type: Type of load (pump, blower, mixer, conveyor, crusher)

    Returns:
        dict with selected overload class
    """
    # Load type based recommendations
    load_type_classes = {
        "submersible": "5",
        "hermetic": "5",
        "compressor_hermetic": "5",
        "pump": "10",
        "blower": "10",
        "fan": "10",
        "mixer": "20",
        "agitator": "20",
        "conveyor": "20",
        "crusher": "30",
        "ball_mill": "30",
        "grinder": "30"
    }

    # Select based on load type if provided
    if load_type and load_type.lower() in load_type_classes:
        recommended_class = load_type_classes[load_type.lower()]
        basis = f"Load type: {load_type}"
    # Otherwise select based on starting time
    elif starting_time_sec <= 5:
        recommended_class = "10"
        basis = f"Starting time {starting_time_sec}s ≤ 5s"
    elif starting_time_sec <= 10:
        recommended_class = "10"
        basis = f"Starting time {starting_time_sec}s ≤ 10s"
    elif starting_time_sec <= 20:
        recommended_class = "20"
        basis = f"Starting time {starting_time_sec}s ≤ 20s"
    else:
        recommended_class = "30"
        basis = f"Starting time {starting_time_sec}s > 20s"

    class_descriptions = {
        "5": "Fast trip - submersible pumps, hermetic compressors",
        "10": "Standard - general purpose motors",
        "20": "Extended - high inertia loads (conveyors, mixers)",
        "30": "Long - very high inertia loads (crushers, mills)"
    }

    return {
        "recommended_class": recommended_class,
        "max_trip_time_sec": int(recommended_class),
        "starting_time_sec": starting_time_sec,
        "load_type": load_type,
        "basis": basis,
        "description": class_descriptions.get(recommended_class, ""),
        "standard": "IEC 60947-4-1"
    }


def size_overload_relay(
    fla_nameplate: float,
    service_factor: float = 1.0,
    starting_time_sec: float = 5.0,
    load_type: Optional[str] = None,
    vfd_application: bool = False,
    use_exception: bool = False
) -> dict:
    """
    Complete overload relay sizing including setting and class selection.

    Args:
        fla_nameplate: Motor nameplate Full Load Amps
        service_factor: Motor service factor (1.0 IEC, 1.15 NEMA)
        starting_time_sec: Expected motor starting time
        load_type: Type of load for class selection
        vfd_application: Motor is VFD driven
        use_exception: Use 430.32(C) exception if needed

    Returns:
        dict with complete overload sizing
    """
    # Get setting
    setting_result = select_overload_setting(
        fla_nameplate, service_factor,
        use_exception=use_exception,
        vfd_application=vfd_application
    )

    # Get class
    class_result = select_overload_class(starting_time_sec, load_type)

    # Determine protection type
    if vfd_application:
        protection_type = "VFD_INTEGRAL"
        protection_notes = "VFD provides integral overload protection"
    else:
        protection_type = "ELECTRONIC" if fla_nameplate > 100 else "THERMAL"
        protection_notes = "Separate overload relay required"

    return {
        "fla_nameplate_a": fla_nameplate,
        "service_factor": service_factor,
        "max_setting_a": setting_result["max_setting_a"],
        "recommended_setting_a": setting_result["recommended_setting_a"],
        "overload_class": class_result["recommended_class"],
        "protection_type": protection_type,
        "vfd_application": vfd_application,
        "sizing_basis": setting_result["notes"],
        "class_basis": class_result["basis"],
        "code_reference": "NEC 430.32, IEC 60947-4-1",
        "notes": protection_notes
    }


def configure_vfd_overload(
    fla_nameplate: float,
    overload_class: str = "10",
    motor_thermal_time_constant_sec: Optional[float] = None
) -> dict:
    """
    Configure VFD integral overload protection settings.

    Args:
        fla_nameplate: Motor nameplate Full Load Amps
        overload_class: Desired overload class (5, 10, 20, 30)
        motor_thermal_time_constant_sec: Motor thermal time constant if known

    Returns:
        dict with VFD overload configuration parameters
    """
    # Standard VFD overload parameters
    config = {
        "motor_rated_current_a": fla_nameplate,
        "overload_level_pct": 100,  # Trip at 100% of rated
        "overload_class": overload_class,
        "i2t_protection": True,
        "motor_thermal_time_constant_sec": motor_thermal_time_constant_sec or 600,
        "stall_detection": True,
        "stall_current_pct": 150,  # Stall at >150% current
        "stall_time_sec": 30,  # Stall trip after 30 seconds
    }

    config["notes"] = (
        f"Configure VFD motor current parameter to {fla_nameplate}A.\n"
        f"Set overload class to {overload_class}.\n"
        "Enable I²t thermal model and stall detection."
    )

    return config


def validate_overload_protection(
    fla_nameplate: float,
    overload_setting: float,
    service_factor: float = 1.0
) -> dict:
    """
    Validate overload protection setting against NEC 430.32.

    Args:
        fla_nameplate: Motor nameplate Full Load Amps
        overload_setting: Installed overload trip setting
        service_factor: Motor service factor

    Returns:
        dict with validation results
    """
    # Get maximum allowed
    max_normal = calc_overload_max_setting(fla_nameplate, service_factor)
    max_exception = calc_overload_exception_setting(fla_nameplate, service_factor)

    issues = []

    if overload_setting > max_exception["max_setting_a"]:
        issues.append({
            "code": "430.32",
            "issue": f"Overload setting {overload_setting}A exceeds maximum {max_exception['max_setting_a']}A (even with exception)",
            "severity": "violation"
        })
    elif overload_setting > max_normal["max_setting_a"]:
        issues.append({
            "code": "430.32(C)",
            "issue": f"Overload setting {overload_setting}A exceeds standard maximum {max_normal['max_setting_a']}A - exception required",
            "severity": "warning"
        })

    return {
        "fla_nameplate_a": fla_nameplate,
        "overload_setting_a": overload_setting,
        "max_standard_a": max_normal["max_setting_a"],
        "max_exception_a": max_exception["max_setting_a"],
        "compliant": len([i for i in issues if i["severity"] == "violation"]) == 0,
        "issues": issues
    }


if __name__ == "__main__":
    print("Testing overload_sizing module...")
    print("=" * 60)

    # Test overload setting calculation
    print("\n1. Overload Setting - NEMA Motor (SF=1.15)")
    setting = calc_overload_max_setting(62, service_factor=1.15)
    print(f"   50 HP motor, FLA = 62A, SF = 1.15")
    print(f"   Max setting: {setting['max_setting_a']}A ({setting['percentage']}%)")
    print(f"   Basis: {setting['basis']}")

    # Test IEC motor
    print("\n2. Overload Setting - IEC Motor (SF=1.0)")
    setting = calc_overload_max_setting(188, service_factor=1.0)
    print(f"   110 kW motor, FLA = 188A, SF = 1.0")
    print(f"   Max setting: {setting['max_setting_a']}A ({setting['percentage']}%)")

    # Test exception
    print("\n3. Overload Exception (NEC 430.32(C))")
    exc = calc_overload_exception_setting(62, service_factor=1.15)
    print(f"   Exception max: {exc['max_setting_a']}A ({exc['percentage']}%)")

    # Test class selection
    print("\n4. Overload Class Selection")
    for load in ["pump", "mixer", "crusher"]:
        cls = select_overload_class(10, load)
        print(f"   {load}: Class {cls['recommended_class']} - {cls['description']}")

    # Test complete sizing
    print("\n5. Complete Overload Sizing")
    sizing = size_overload_relay(
        fla_nameplate=188,
        service_factor=1.0,
        starting_time_sec=8,
        load_type="blower",
        vfd_application=True
    )
    print(f"   110 kW blower with VFD:")
    print(f"   Max setting: {sizing['max_setting_a']}A")
    print(f"   Recommended: {sizing['recommended_setting_a']}A")
    print(f"   Class: {sizing['overload_class']}")
    print(f"   Protection: {sizing['protection_type']}")

    # Test VFD configuration
    print("\n6. VFD Overload Configuration")
    vfd_config = configure_vfd_overload(188, "10")
    print(f"   Motor current: {vfd_config['motor_rated_current_a']}A")
    print(f"   Class: {vfd_config['overload_class']}")

    # Test validation
    print("\n7. Overload Validation")
    val = validate_overload_protection(62, 75, 1.15)
    print(f"   Setting 75A vs max {val['max_standard_a']}A")
    print(f"   Compliant: {val['compliant']}")
    if val['issues']:
        for issue in val['issues']:
            print(f"   {issue['severity']}: {issue['issue']}")

    print("\n" + "=" * 60)
    print("All tests completed!")
