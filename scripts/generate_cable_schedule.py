#!/usr/bin/env python3
"""
Cable Schedule Generation Module
Generate cable schedules for contractor costing.

Creates cable schedules with:
- Cable sizes based on ampacity requirements
- Voltage drop calculations
- Estimated lengths (with assumptions flagged)
- Quantity takeoffs

Author: Load List Skill
"""

from pathlib import Path
from typing import Optional

import yaml

from cable_sizing import select_motor_branch_cable, select_vfd_supply_cable, select_feeder_cable
from voltage_drop import calc_voltage_drop_pct


# Default cable route length assumptions
DEFAULT_CABLE_LENGTHS = {
    "mcc_to_local_motor": 30,       # Same building, typical process area
    "mcc_to_remote_motor": 75,      # Outdoor, typical tank/basin distance
    "mcc_to_remote_building": 150,  # Different building
    "transformer_to_mcc": 15,       # Adjacent electrical room
}


def estimate_cable_length(
    from_location: str,
    to_location: str,
    equipment_type: Optional[str] = None,
    area_code: Optional[int] = None
) -> dict:
    """
    Estimate cable length based on location types.

    Args:
        from_location: Source (e.g., "MCC-200")
        to_location: Destination (e.g., "200-B-01A")
        equipment_type: Equipment type code
        area_code: Area code for location estimation

    Returns:
        dict with estimated length and basis
    """
    # Default to local motor distance
    length = DEFAULT_CABLE_LENGTHS["mcc_to_local_motor"]
    basis = "Typical same-building motor"

    # Adjust based on equipment type (some equipment is typically farther)
    if equipment_type:
        eq_upper = equipment_type.upper()
        if eq_upper in ["B", "BL"]:  # Blowers often in separate blower room
            length = 45
            basis = "Typical blower room distance"
        elif eq_upper in ["P", "PU"]:  # Pumps may be in basins
            length = 50
            basis = "Typical pump station distance"
        elif eq_upper in ["TH", "CL"]:  # Clarifier mechanisms
            length = 75
            basis = "Typical clarifier mechanism distance"
        elif eq_upper in ["SC"]:  # Screens at headworks
            length = 60
            basis = "Typical headworks distance"

    return {
        "estimated_length_m": length,
        "basis": basis,
        "assumed": True,
        "warning": "ESTIMATED - Verify against final plant layout"
    }


def generate_cable_entry(
    load: dict,
    panel_tag: str,
    cable_number: int,
    voltage: float = 400,
    cable_standard: str = "IEC",
    ambient_temp_c: float = 30
) -> dict:
    """
    Generate cable schedule entry for a single motor.

    Args:
        load: Load dict with motor data
        panel_tag: Source panel tag
        cable_number: Sequential cable number
        voltage: System voltage
        cable_standard: NEC or IEC
        ambient_temp_c: Ambient temperature for cable sizing

    Returns:
        dict with cable schedule entry
    """
    tag = load.get("equipment_tag", "")
    motor_kw = load.get("rated_kw", load.get("installed_kw", 0))
    flc = load.get("flc_table_a", load.get("fla", 0))
    feeder_type = load.get("feeder_type", "DOL")
    eq_type = load.get("equipment_type", "")

    # Generate cable tag
    cable_tag = f"C-{panel_tag.replace('MCC-', '')}-{cable_number:02d}"

    # Estimate cable length
    length_info = estimate_cable_length(panel_tag, tag, eq_type)
    length_m = load.get("cable_length_m", length_info["estimated_length_m"])
    length_assumed = load.get("cable_length_m") is None

    # Size cable based on feeder type
    if "VFD" in feeder_type.upper():
        vfd_input = load.get("vfd_input_current_a", flc * 1.1)
        cable_result = select_vfd_supply_cable(
            vfd_input, cable_standard=cable_standard,
            ambient_temp_c=ambient_temp_c
        )
        cable_type = "VFD Supply"
    else:
        cable_result = select_motor_branch_cable(
            flc, cable_standard=cable_standard,
            ambient_temp_c=ambient_temp_c
        )
        cable_type = "Motor Branch"

    # Calculate voltage drop
    cable_size_mm2 = extract_mm2_from_size(cable_result["selected_size"])
    current = load.get("vfd_input_current_a", flc) if "VFD" in feeder_type.upper() else flc

    vd_result = calc_voltage_drop_pct(
        current_a=current,
        length_m=length_m,
        cable_size_mm2=cable_size_mm2,
        voltage=voltage,
        phases=3,
        power_factor=load.get("pf", 0.85)
    )

    # Determine cable construction
    if cable_standard == "IEC":
        cable_construction = f"3C+E Cu XLPE/SWA/PVC {cable_result['selected_size']}"
    else:
        cable_construction = f"3#{cable_result['selected_size']} + #10 GND Cu THHN"

    return {
        "cable_tag": cable_tag,
        "from_panel": panel_tag,
        "to_equipment": tag,
        "equipment_description": load.get("description", ""),
        "motor_kw": motor_kw,
        "cable_type": cable_type,
        "cable_construction": cable_construction,
        "cable_size": cable_result["selected_size"],
        "cable_size_mm2": cable_size_mm2,
        "length_m": length_m,
        "length_assumed": length_assumed,
        "length_basis": length_info["basis"] if length_assumed else "From layout/user input",
        "voltage_drop_pct": vd_result["voltage_drop_pct"],
        "voltage_drop_compliant": vd_result["compliant_branch"],
        "current_a": current,
        "sizing_basis": cable_result["sizing_basis"],
        "ambient_temp_c": ambient_temp_c,
        "quantity": 1,
        "notes": load.get("cable_notes", "")
    }


def extract_mm2_from_size(size_str: str) -> float:
    """Extract mm² value from size string."""
    size_str = str(size_str).upper()

    # Direct mm² format
    if "MM²" in size_str or "MM2" in size_str:
        try:
            return float(size_str.replace("MM²", "").replace("MM2", "").strip())
        except ValueError:
            pass

    # AWG/kcmil to mm² conversion
    awg_to_mm2 = {
        "14 AWG": 2.08, "12 AWG": 3.31, "10 AWG": 5.26, "8 AWG": 8.37,
        "6 AWG": 13.30, "4 AWG": 21.15, "3 AWG": 26.67, "2 AWG": 33.62,
        "1 AWG": 42.41, "1/0 AWG": 53.49, "2/0 AWG": 67.43, "3/0 AWG": 85.01,
        "4/0 AWG": 107.2, "250 KCMIL": 126.7, "300 KCMIL": 152.0,
        "350 KCMIL": 177.3, "400 KCMIL": 202.7, "500 KCMIL": 253.4
    }

    for awg, mm2 in awg_to_mm2.items():
        if awg in size_str:
            return mm2

    return 25  # Default fallback


def generate_cable_schedule(
    loads: list[dict],
    panel_tag: str,
    voltage: float = 400,
    cable_standard: str = "IEC",
    ambient_temp_c: float = 30
) -> dict:
    """
    Generate cable schedule for an MCC panel.

    Args:
        loads: List of load dicts for this panel
        panel_tag: Panel tag
        voltage: System voltage
        cable_standard: NEC or IEC
        ambient_temp_c: Ambient temperature

    Returns:
        dict with cable schedule
    """
    cables = []
    cable_number = 1

    for load in loads:
        cable = generate_cable_entry(
            load=load,
            panel_tag=panel_tag,
            cable_number=cable_number,
            voltage=voltage,
            cable_standard=cable_standard,
            ambient_temp_c=ambient_temp_c
        )
        cables.append(cable)
        cable_number += 1

    # Calculate totals
    total_length = sum(c["length_m"] for c in cables)
    assumed_count = sum(1 for c in cables if c["length_assumed"])
    vd_issues = [c for c in cables if not c["voltage_drop_compliant"]]

    return {
        "panel_tag": panel_tag,
        "cable_count": len(cables),
        "total_length_m": total_length,
        "cables_with_assumed_length": assumed_count,
        "cables_with_vd_issues": len(vd_issues),
        "cables": cables,
        "disclaimers": [
            "Cable lengths are ESTIMATED based on typical WWTP layouts." if assumed_count > 0 else None,
            "Verify against final plant layout drawings before procurement.",
            "Voltage drop calculations use assumed lengths - recalculate with actual routes." if assumed_count > 0 else None
        ],
        "standard": cable_standard,
        "ambient_temp_c": ambient_temp_c
    }


def generate_all_cable_schedules(
    loads: list[dict],
    voltage: float = 400,
    cable_standard: str = "IEC",
    ambient_temp_c: float = 30
) -> dict:
    """
    Generate cable schedules for all panels.

    Args:
        loads: Complete load list
        voltage: System voltage
        cable_standard: NEC or IEC
        ambient_temp_c: Ambient temperature

    Returns:
        dict with all cable schedules
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
        schedules[panel_tag] = generate_cable_schedule(
            loads=panel_loads,
            panel_tag=panel_tag,
            voltage=voltage,
            cable_standard=cable_standard,
            ambient_temp_c=ambient_temp_c
        )

    # Calculate overall totals
    total_cables = sum(s["cable_count"] for s in schedules.values())
    total_length = sum(s["total_length_m"] for s in schedules.values())

    # Summarize by cable size for procurement
    size_summary = {}
    for schedule in schedules.values():
        for cable in schedule["cables"]:
            size = cable["cable_size"]
            if size not in size_summary:
                size_summary[size] = {"count": 0, "total_length_m": 0}
            size_summary[size]["count"] += 1
            size_summary[size]["total_length_m"] += cable["length_m"]

    return {
        "cable_schedules": schedules,
        "panel_count": len(schedules),
        "total_cables": total_cables,
        "total_length_m": total_length,
        "size_summary": size_summary,
        "generation_basis": {
            "voltage": voltage,
            "cable_standard": cable_standard,
            "ambient_temp_c": ambient_temp_c
        },
        "disclaimers": [
            "NOTE: Cable lengths are ESTIMATED based on typical WWTP layouts.",
            "Verify against final plant layout drawings before procurement.",
            "Voltage drop calculations use assumed lengths - recalculate with actual routes."
        ]
    }


def export_cable_schedule_summary(schedule: dict) -> str:
    """
    Export cable schedule as text summary for quick review.

    Args:
        schedule: Cable schedule dict

    Returns:
        Formatted text summary
    """
    lines = []
    lines.append("=" * 80)
    lines.append("CABLE SCHEDULE SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Total Cables: {schedule['total_cables']}")
    lines.append(f"Total Length: {schedule['total_length_m']} m")
    lines.append("")

    lines.append("SIZE SUMMARY (for procurement):")
    lines.append("-" * 40)
    for size, data in sorted(schedule.get("size_summary", {}).items()):
        lines.append(f"  {size}: {data['count']} cables, {data['total_length_m']} m")

    lines.append("")
    lines.append("DISCLAIMERS:")
    for disclaimer in schedule.get("disclaimers", []):
        if disclaimer:
            lines.append(f"  * {disclaimer}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing generate_cable_schedule module...")
    print("=" * 60)

    # Sample loads
    sample_loads = [
        {
            "equipment_tag": "200-B-01A",
            "description": "Aeration Blower #1",
            "rated_kw": 110,
            "flc_table_a": 195,
            "feeder_type": "VFD",
            "vfd_input_current_a": 207,
            "equipment_type": "B",
            "mcc_panel": "MCC-200",
            "pf": 0.88
        },
        {
            "equipment_tag": "200-AG-01",
            "description": "Anoxic Mixer #1",
            "rated_kw": 22,
            "flc_table_a": 41,
            "feeder_type": "VFD",
            "equipment_type": "AG",
            "mcc_panel": "MCC-200",
            "pf": 0.85
        },
        {
            "equipment_tag": "200-P-01A",
            "description": "RAS Pump #1",
            "rated_kw": 37,
            "flc_table_a": 68,
            "feeder_type": "DOL",
            "equipment_type": "P",
            "mcc_panel": "MCC-200",
            "pf": 0.85
        }
    ]

    # Generate cable schedule
    print("\nGenerating Cable Schedule for MCC-200...")
    schedule = generate_cable_schedule(
        sample_loads, "MCC-200",
        voltage=400, cable_standard="IEC"
    )

    print(f"\nPanel: {schedule['panel_tag']}")
    print(f"Cable Count: {schedule['cable_count']}")
    print(f"Total Length: {schedule['total_length_m']} m")
    print(f"Cables with assumed length: {schedule['cables_with_assumed_length']}")

    print("\nCable Details:")
    for cable in schedule["cables"]:
        print(f"  {cable['cable_tag']}: {cable['to_equipment']}")
        print(f"    Size: {cable['cable_size']}")
        print(f"    Length: {cable['length_m']} m {'(assumed)' if cable['length_assumed'] else ''}")
        print(f"    VD: {cable['voltage_drop_pct']}%")

    # Generate all schedules
    print("\n" + "=" * 60)
    print("Generating All Cable Schedules...")
    all_schedules = generate_all_cable_schedules(sample_loads, voltage=400)
    print(export_cable_schedule_summary(all_schedules))

    print("\n" + "=" * 60)
    print("All tests completed!")
