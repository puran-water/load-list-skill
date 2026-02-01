#!/usr/bin/env python3
"""
MCC Bucket Schedule Module
Generate engineering-grade MCC bucket-level schedules.

Creates detailed bucket schedules for panel builder specifications including:
- Protection device sizing per NEC 430
- Starter/controller sizing
- Cable termination requirements
- SCCR validation
- Physical layout data

Author: Load List Skill
Standards: NEC 2023 Article 430, UL 845, IEC 61439
"""

import math
from pathlib import Path
from typing import Optional, Literal

import yaml

from branch_circuit_sizing import (
    calc_branch_conductor_ampacity,
    select_branch_scpd,
    get_recommended_fuse_class
)
from overload_sizing import size_overload_relay
from vfd_sizing import size_vfd_circuit
from feeder_sizing import size_mcc_feeder, select_standard_bus_rating, select_main_breaker


def load_catalog(name: str) -> dict:
    """Load a YAML catalog file."""
    catalogs_dir = Path(__file__).parent.parent / "catalogs"
    path = catalogs_dir / f"{name}.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f)


def determine_unit_type(feeder_type: str) -> str:
    """Map feeder type to MCC unit type."""
    feeder_upper = feeder_type.upper()

    if "VFD" in feeder_upper:
        return "VFD"
    elif "SOFT" in feeder_upper:
        return "SOFT_STARTER"
    elif "REV" in feeder_upper:
        return "FVR"  # Full Voltage Reversing
    elif feeder_upper in ["DOL", "FVNR"]:
        return "FVNR"  # Full Voltage Non-Reversing
    elif "VENDOR" in feeder_upper:
        return "FEEDER"  # Vendor-supplied package
    else:
        return "FVNR"


def select_starter_frame(
    motor_kw: float,
    motor_flc: float,
    voltage: float,
    motor_standard: str = "IEC"
) -> dict:
    """
    Select IEC contactor or NEMA starter frame.

    Args:
        motor_kw: Motor power in kW
        motor_flc: Motor Full Load Current
        voltage: System voltage
        motor_standard: IEC or NEMA

    Returns:
        dict with starter frame selection
    """
    catalog = load_catalog("starter_sizing")

    if motor_standard == "IEC":
        frames = catalog.get("iec_contactors", {}).get("frames", {})
        for frame_id, frame_data in frames.items():
            max_fla = frame_data.get("max_fla_400v", 0)
            # Adjust for voltage
            if voltage != 400:
                derating = catalog.get("iec_contactors", {}).get("voltage_derating", {})
                factor = derating.get(f"{int(voltage)}V", 1.0)
                max_fla = max_fla / factor

            if max_fla >= motor_flc:
                return {
                    "frame": frame_id,
                    "frame_type": "IEC",
                    "max_fla": max_fla,
                    "typical_contactors": frame_data.get("typical_contactors", []),
                    "motor_kw": motor_kw,
                    "motor_flc": motor_flc
                }

    else:  # NEMA
        # Convert kW to HP for NEMA lookup
        hp = motor_kw * 1.341
        sizes = catalog.get("nema_starters", {}).get("sizes", {})

        for size_id, size_data in sizes.items():
            phase_data = size_data.get("three_phase", {})
            max_hp = phase_data.get(str(int(voltage)), 0) or phase_data.get(int(voltage), 0)

            if max_hp and max_hp >= hp:
                return {
                    "frame": size_id,
                    "frame_type": "NEMA",
                    "max_hp": max_hp,
                    "motor_hp": hp,
                    "motor_kw": motor_kw
                }

    return {"frame": "special", "frame_type": motor_standard, "notes": "Exceeds standard range"}


def estimate_bucket_height(
    unit_type: str,
    motor_kw: float,
    withdrawable: bool = False
) -> int:
    """
    Estimate bucket height in standard units.

    Standard unit = 6" (152mm)
    Typical heights: 1 unit (small DOL), 2 units (medium), 3-4 units (large VFD)

    Args:
        unit_type: FVNR, VFD, SOFT_STARTER, etc.
        motor_kw: Motor power in kW
        withdrawable: Whether bucket is withdrawable type

    Returns:
        Height in standard units (1-4)
    """
    base_height = 1

    if unit_type == "VFD":
        if motor_kw <= 5.5:
            base_height = 1
        elif motor_kw <= 22:
            base_height = 2
        elif motor_kw <= 90:
            base_height = 3
        else:
            base_height = 4
    elif unit_type == "SOFT_STARTER":
        if motor_kw <= 22:
            base_height = 2
        else:
            base_height = 3
    elif unit_type in ["FVNR", "FVR"]:
        if motor_kw <= 7.5:
            base_height = 1
        elif motor_kw <= 37:
            base_height = 2
        else:
            base_height = 3

    # Withdrawable adds height
    if withdrawable and base_height < 4:
        base_height += 1

    return min(base_height, 4)


def generate_bucket(
    load: dict,
    panel_tag: str,
    bucket_number: int,
    voltage: float = 400,
    motor_standard: str = "IEC",
    available_fault_ka: float = 18,
    scpd_type: str = "dual_element_fuse",
    withdrawable: bool = False
) -> dict:
    """
    Generate complete MCC bucket specification for a single motor.

    Args:
        load: Load dict with motor data (from load list)
        panel_tag: Parent MCC panel tag
        bucket_number: Sequential bucket number within panel
        voltage: System voltage
        motor_standard: IEC or NEMA
        available_fault_ka: Available fault current at MCC bus
        scpd_type: Branch circuit protective device type
        withdrawable: Whether bucket is withdrawable type

    Returns:
        dict with complete bucket specification per mcc-bucket.schema.yaml
    """
    tag = load.get("equipment_tag", "")
    motor_kw = load.get("rated_kw", load.get("installed_kw", 0))
    flc_table = load.get("flc_table_a", load.get("fla", 0))
    fla_nameplate = load.get("fla_nameplate_a", flc_table * 0.95)  # Estimate if not provided
    lra = load.get("lra", flc_table * 6)
    feeder_type = load.get("feeder_type", "DOL")
    service_factor = load.get("service_factor", 1.0 if motor_standard == "IEC" else 1.15)

    # Generate bucket ID
    bucket_id = f"{panel_tag}-{bucket_number:02d}"
    unit_type = determine_unit_type(feeder_type)

    # Initialize bucket
    bucket = {
        "bucket_id": bucket_id,
        "panel_tag": panel_tag,
        "position": f"{(bucket_number - 1) // 10 + 1}{chr(65 + (bucket_number - 1) % 10)}",
        "unit_type": unit_type,
        "motor_tag": tag,
        "motor_description": load.get("description", ""),
        "motor_rated_kw": motor_kw,
        "flc_table_a": round(flc_table, 1),
        "fla_nameplate_a": round(fla_nameplate, 1),
        "lra": round(lra, 0),
        "service_factor": service_factor
    }

    # Branch circuit sizing depends on unit type
    if unit_type == "VFD":
        # VFD-specific sizing
        vfd_result = size_vfd_circuit(
            motor_kw=motor_kw,
            motor_flc=flc_table,
            voltage=voltage,
            vfd_input_current=load.get("vfd_input_current_a"),
            vfd_max_scpd=load.get("vfd_max_ocpd_a"),
            device_type=scpd_type
        )

        bucket.update({
            "branch_scpd_type": scpd_type.upper(),  # Keep underscore format per schema enum
            "branch_scpd_rating_a": vfd_result["branch_scpd_rating_a"],
            "branch_scpd_sizing_basis": vfd_result["scpd_sizing"]["sizing_basis"],
            "overload_type": "VFD_INTEGRAL",
            "overload_setting_a": round(fla_nameplate, 1),
            "overload_class": load.get("overload_class", "10"),
            "vfd_input_current_a": vfd_result["vfd_input_current_a"],
            "vfd_frame": load.get("vfd_frame"),
            "vfd_manufacturer": load.get("vfd_manufacturer"),
            "vfd_model": load.get("vfd_model"),
            "conductor_min_ampacity_a": vfd_result["conductor_min_ampacity_a"]
        })

    else:
        # DOL/Soft Starter sizing
        conductor = calc_branch_conductor_ampacity(flc_table)
        scpd = select_branch_scpd(
            motor_flc=flc_table,
            motor_lra=lra,
            device_type=scpd_type
        )
        overload = size_overload_relay(
            fla_nameplate=fla_nameplate,
            service_factor=service_factor,
            starting_time_sec=load.get("starting_time_sec", 8),
            load_type=load.get("equipment_type"),
            vfd_application=False
        )

        bucket.update({
            "branch_scpd_type": scpd_type.upper(),  # Keep underscore format per schema enum
            "branch_scpd_rating_a": scpd["selected_rating_a"],
            "branch_scpd_sizing_basis": scpd["sizing_basis"],
            "overload_type": overload["protection_type"],
            "overload_setting_a": round(overload["recommended_setting_a"], 1),
            "overload_class": overload["overload_class"],
            "overload_sizing_basis": overload["sizing_basis"],
            "conductor_min_ampacity_a": conductor["min_ampacity_a"]
        })

        # Starter frame for DOL
        if unit_type in ["FVNR", "FVR"]:
            starter = select_starter_frame(motor_kw, flc_table, voltage, motor_standard)
            bucket["starter_frame"] = starter["frame"]
            bucket["contactor_rating"] = f"AC-3 {int(flc_table)}A {int(voltage)}V"

        # Soft starter frame
        elif unit_type == "SOFT_STARTER":
            bucket["soft_starter_frame"] = load.get("soft_starter_frame", "")

    # SCCR rating
    fuse_class = get_recommended_fuse_class(available_fault_ka)
    bucket.update({
        "sccr_ka": load.get("sccr_ka", 65 if fuse_class == "J" else 35),
        "sccr_source": load.get("sccr_source", "preliminary_estimate"),
        "branch_scpd_fuse_class": fuse_class if "fuse" in scpd_type.lower() else None
    })

    # Physical layout
    bucket.update({
        "bucket_height_units": estimate_bucket_height(unit_type, motor_kw, withdrawable),
        "withdrawable": withdrawable,
        "construction": "WITHDRAWABLE" if withdrawable else "FIXED",
        "control_voltage": load.get("control_voltage", 120 if motor_standard == "NEMA" else 230)
    })

    # Coordination data for future studies
    bucket["coordination_data"] = {
        "device_type": "fuse" if "fuse" in scpd_type.lower() else "mccb",
        "curve_family": "dual_element" if "dual" in scpd_type.lower() else "inverse_time",
        "inrush_multiple": round(lra / flc_table, 1) if flc_table > 0 else 6.0,
        "expected_start_time_sec": load.get("starting_time_sec", 8),
        "available_fault_at_bucket_ka": available_fault_ka
    }

    # Provenance
    bucket["provenance"] = {
        "source": "calculated",
        "selection_stage": "preliminary_generic",
        "verified": False,
        "notes": f"Generated from load list, {motor_standard} basis"
    }

    bucket["assumption_flags"] = {
        "cable_length_assumed": True,
        "fault_current_assumed": load.get("fault_current_source") != "verified",
        "motor_data_from_nameplate": load.get("fla_source") == "nameplate"
    }

    return bucket


def generate_mcc_schedule(
    loads: list[dict],
    panel_tag: str,
    voltage: float = 400,
    motor_standard: str = "IEC",
    available_fault_ka: float = 18,
    scpd_type: str = "dual_element_fuse",
    withdrawable: bool = False,
    include_spares: int = 2
) -> dict:
    """
    Generate complete MCC schedule with all buckets.

    Args:
        loads: List of load dicts (filtered to this panel)
        panel_tag: MCC panel tag
        voltage: System voltage
        motor_standard: IEC or NEMA
        available_fault_ka: Available fault current
        scpd_type: Branch circuit protective device type
        withdrawable: Whether buckets are withdrawable
        include_spares: Number of spare buckets to include

    Returns:
        dict with MCC schedule including panel summary and all buckets
    """
    # Generate buckets for each load
    buckets = []
    bucket_number = 1

    for load in loads:
        bucket = generate_bucket(
            load=load,
            panel_tag=panel_tag,
            bucket_number=bucket_number,
            voltage=voltage,
            motor_standard=motor_standard,
            available_fault_ka=available_fault_ka,
            scpd_type=scpd_type,
            withdrawable=withdrawable
        )
        buckets.append(bucket)
        bucket_number += 1

    # Add spare buckets
    for i in range(include_spares):
        buckets.append({
            "bucket_id": f"{panel_tag}-{bucket_number:02d}",
            "panel_tag": panel_tag,
            "position": f"{(bucket_number - 1) // 10 + 1}{chr(65 + (bucket_number - 1) % 10)}",
            "unit_type": "SPARE",
            "bucket_height_units": 2,
            "withdrawable": withdrawable,
            "notes": "Spare bucket for future use"
        })
        bucket_number += 1

    # Calculate feeder sizing
    motor_data = [
        {
            "flc_table_a": b.get("flc_table_a", 0),
            "branch_scpd_rating_a": b.get("branch_scpd_rating_a", 0),
            "tag": b.get("motor_tag", "")
        }
        for b in buckets if b.get("unit_type") != "SPARE"
    ]

    feeder = size_mcc_feeder(motor_data, voltage)
    main_breaker = select_main_breaker(
        feeder["feeder_ocpd_max_a"],
        feeder["feeder_conductor_min_a"]
    )
    bus_rating = select_standard_bus_rating(feeder["feeder_conductor_min_a"])

    # Calculate lineup SCCR (preliminary - min of bucket SCCRs)
    bucket_sccrs = [b.get("sccr_ka", 0) for b in buckets if b.get("sccr_ka")]
    lineup_sccr = min(bucket_sccrs) if bucket_sccrs else 0
    sccr_compliant = lineup_sccr >= available_fault_ka if lineup_sccr > 0 else False

    # Aggregate loads
    connected_kw = sum(b.get("motor_rated_kw", 0) for b in buckets if b.get("unit_type") != "SPARE")
    total_height = sum(b.get("bucket_height_units", 2) for b in buckets) * 6  # Convert to inches

    # Build panel summary
    panel_summary = {
        "panel_tag": panel_tag,
        "supply_voltage": voltage,
        "motor_standard": motor_standard,

        # Load aggregation
        "connected_kw": round(connected_kw, 1),
        "bucket_count": len([b for b in buckets if b.get("unit_type") != "SPARE"]),
        "spare_bucket_count": include_spares,

        # NEC-compliant sizing
        "feeder_conductor_min_a": feeder["feeder_conductor_min_a"],
        "feeder_ocpd_max_a": feeder["feeder_ocpd_max_a"],
        "main_breaker_a": main_breaker["selected_rating_a"],
        "bus_rating": bus_rating,

        # SCCR
        "available_fault_current_ka": available_fault_ka,
        "lineup_sccr_ka": lineup_sccr,
        "sccr_source": "preliminary_worst_case",
        "sccr_compliant": sccr_compliant,

        # Physical
        "total_height_inches": total_height,
        "total_height_mm": round(total_height * 25.4, 0),
        "unit_type": "WITHDRAWABLE" if withdrawable else "FIXED"
    }

    if not sccr_compliant:
        panel_summary["sccr_warning"] = (
            f"Lineup SCCR ({lineup_sccr} kA) < available fault current ({available_fault_ka} kA). "
            "Review bucket SCCR ratings or add current-limiting protection."
        )

    return {
        "panel_summary": panel_summary,
        "buckets": buckets,
        "feeder_sizing": feeder,
        "code_references": ["NEC 430.22", "NEC 430.24", "NEC 430.32", "NEC 430.52", "NEC 430.62", "UL 845"]
    }


def generate_all_mcc_schedules(
    loads: list[dict],
    voltage: float = 400,
    motor_standard: str = "IEC",
    available_fault_ka: float = 18,
    scpd_type: str = "dual_element_fuse",
    withdrawable: bool = False,
    spares_per_panel: int = 2
) -> dict:
    """
    Generate MCC schedules for all panels in load list.

    Args:
        loads: Complete load list
        voltage: System voltage
        motor_standard: IEC or NEMA
        available_fault_ka: Available fault current
        scpd_type: Branch circuit protective device type
        withdrawable: Whether buckets are withdrawable
        spares_per_panel: Number of spare buckets per panel

    Returns:
        dict with all MCC schedules
    """
    # Group loads by panel
    panels = {}
    for load in loads:
        panel = load.get("mcc_panel", "MCC-UNASSIGNED")
        if panel not in panels:
            panels[panel] = []
        panels[panel].append(load)

    # Generate schedule for each panel
    schedules = {}
    for panel_tag, panel_loads in sorted(panels.items()):
        schedules[panel_tag] = generate_mcc_schedule(
            loads=panel_loads,
            panel_tag=panel_tag,
            voltage=voltage,
            motor_standard=motor_standard,
            available_fault_ka=available_fault_ka,
            scpd_type=scpd_type,
            withdrawable=withdrawable,
            include_spares=spares_per_panel
        )

    return {
        "mcc_schedules": schedules,
        "panel_count": len(schedules),
        "total_buckets": sum(len(s["buckets"]) for s in schedules.values()),
        "generation_basis": {
            "voltage": voltage,
            "motor_standard": motor_standard,
            "available_fault_ka": available_fault_ka,
            "scpd_type": scpd_type
        }
    }


if __name__ == "__main__":
    print("Testing mcc_bucket_schedule module...")
    print("=" * 60)

    # Sample loads
    sample_loads = [
        {
            "equipment_tag": "200-B-01A",
            "description": "Aeration Blower #1",
            "rated_kw": 110,
            "flc_table_a": 195,
            "fla_nameplate_a": 188,
            "lra": 1170,
            "feeder_type": "VFD",
            "service_factor": 1.0,
            "mcc_panel": "MCC-200",
            "vfd_input_current_a": 207,
            "vfd_max_ocpd_a": 300
        },
        {
            "equipment_tag": "200-AG-01",
            "description": "Anoxic Mixer #1",
            "rated_kw": 22,
            "flc_table_a": 41,
            "fla_nameplate_a": 39,
            "lra": 246,
            "feeder_type": "VFD",
            "service_factor": 1.0,
            "mcc_panel": "MCC-200"
        },
        {
            "equipment_tag": "200-P-01A",
            "description": "RAS Pump #1",
            "rated_kw": 37,
            "flc_table_a": 68,
            "fla_nameplate_a": 65,
            "lra": 408,
            "feeder_type": "DOL",
            "service_factor": 1.0,
            "mcc_panel": "MCC-200"
        }
    ]

    # Generate single bucket
    print("\n1. Single Bucket Generation")
    bucket = generate_bucket(
        sample_loads[0], "MCC-200", 1,
        voltage=400, motor_standard="IEC",
        available_fault_ka=18
    )
    print(f"   Bucket ID: {bucket['bucket_id']}")
    print(f"   Unit Type: {bucket['unit_type']}")
    print(f"   SCPD: {bucket['branch_scpd_rating_a']}A")
    print(f"   Overload: {bucket['overload_setting_a']}A Class {bucket['overload_class']}")

    # Generate MCC schedule
    print("\n2. Complete MCC Schedule")
    schedule = generate_mcc_schedule(
        sample_loads, "MCC-200",
        voltage=400, motor_standard="IEC",
        available_fault_ka=18,
        include_spares=2
    )
    print(f"   Panel: {schedule['panel_summary']['panel_tag']}")
    print(f"   Buckets: {schedule['panel_summary']['bucket_count']} + {schedule['panel_summary']['spare_bucket_count']} spares")
    print(f"   Connected: {schedule['panel_summary']['connected_kw']} kW")
    print(f"   Main breaker: {schedule['panel_summary']['main_breaker_a']}A")
    print(f"   Bus rating: {schedule['panel_summary']['bus_rating']}")
    print(f"   Lineup SCCR: {schedule['panel_summary']['lineup_sccr_ka']} kA")
    print(f"   SCCR Compliant: {schedule['panel_summary']['sccr_compliant']}")

    # List buckets
    print("\n   Bucket Schedule:")
    for b in schedule["buckets"]:
        if b.get("unit_type") != "SPARE":
            print(f"   {b['bucket_id']}: {b['motor_tag']} - {b['unit_type']} {b.get('motor_rated_kw', 0)} kW, "
                  f"SCPD {b.get('branch_scpd_rating_a', 0)}A")
        else:
            print(f"   {b['bucket_id']}: SPARE")

    print("\n" + "=" * 60)
    print("All tests completed!")
