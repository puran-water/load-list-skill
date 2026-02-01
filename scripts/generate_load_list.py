#!/usr/bin/env python3
"""
Generate Load List
Main generator script for creating electrical load lists from equipment lists.

Workflow:
1. Load equipment list from QMD/YAML
2. Extract duty points from Tier 1 sizing artifacts
3. Apply duty profiles (running hours, load factors)
4. Calculate FLA, brake power, energy
5. Aggregate by MCC panel
6. Output YAML load list

Usage:
    python generate_load_list.py \
        --equipment equipment-list.qmd \
        --output electrical/load-list.yaml \
        --project-dir ./project \
        --motor-standard IEC \
        --voltage 400 \
        --frequency 50
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

# Import local modules
from load_calculations import (
    lookup_fla,
    calc_lra,
    calc_pump_brake_kw,
    calc_blower_brake_kw,
    calc_mixer_brake_kw,
    calc_absorbed_kw,
    calc_running_kw,
    calc_demand_kw,
    calc_daily_kwh,
    calc_specific_energy,
    get_motor_efficiency,
    get_duty_profile,
    parse_diversity_from_quantity_note,
)
from extract_duty_points import extract_all_duty_points
from mcc_aggregation import (
    aggregate_by_panel,
    calculate_plant_totals,
    assign_panels_by_area,
)

# Import modules for full output generation
try:
    from mcc_bucket_schedule import generate_mcc_schedule
    from generate_cable_schedule import generate_cable_schedule as gen_cable_schedule
    from plant_load_summary import calc_plant_load_summary
    from transformer_sizing import size_transformer
    from motor_starting import check_sequential_starting
    from fault_current import get_default_fault_current, calc_preliminary_fault_current
    MCC_MODULES_AVAILABLE = True
except ImportError:
    MCC_MODULES_AVAILABLE = False


def get_fault_current_config(metadata: dict, voltage: int) -> dict:
    """
    Get fault current configuration from metadata or calculate conservative default.

    Args:
        metadata: Project metadata dict
        voltage: System voltage

    Returns:
        dict with fault current configuration including:
        - at_mcc_bus_ka: Available fault current at MCC bus
        - source: Where the value came from
        - verified: Whether value is verified (for Tier 3)
        - warning: Any applicable warnings
    """
    # Check if user provided verified fault current
    user_fault_ka = metadata.get("available_fault_ka")
    fault_source = metadata.get("fault_current_source", "assumption")
    fault_verified = fault_source == "verified"

    if user_fault_ka is not None:
        return {
            "at_mcc_bus_ka": user_fault_ka,
            "source": fault_source,
            "verified": fault_verified,
            "warning": None if fault_verified else "User-provided value - verify with utility coordination"
        }

    # Try to calculate from transformer data if available
    xfmr_kva = metadata.get("transformer_kva")
    xfmr_z = metadata.get("transformer_z_pct", 5.75)

    if xfmr_kva and MCC_MODULES_AVAILABLE:
        result = calc_preliminary_fault_current(xfmr_kva, xfmr_z, voltage)
        return {
            "at_mcc_bus_ka": result["available_fault_ka"],
            "source": "calculated_from_transformer",
            "verified": False,
            "transformer_kva": xfmr_kva,
            "transformer_z_pct": xfmr_z,
            "warning": result["warning"]
        }

    # Use conservative default (worst-case higher value)
    if MCC_MODULES_AVAILABLE:
        default = get_default_fault_current("mcc_bus")
        return {
            "at_mcc_bus_ka": default["available_fault_ka"],
            "source": "conservative_default",
            "verified": False,
            "warning": default["warning"]
        }

    # Fallback if modules not available
    return {
        "at_mcc_bus_ka": 35,  # Conservative default per plan
        "source": "conservative_default",
        "verified": False,
        "warning": "DEFAULT VALUE - verify with utility coordination study"
    }


# Required fields for each output tier
TIER_REQUIRED_FIELDS = {
    1: {  # Tier 1: Load Study - basic load data
        "load": ["equipment_tag", "rated_kw", "demand_kw"],
        "percentage": 100  # Always Tier 1
    },
    2: {  # Tier 2: Preliminary Schedule - motor data ≥80% complete
        "load": ["equipment_tag", "rated_kw", "flc_table_a", "feeder_type", "mcc_panel"],
        "percentage": 80  # 80% of loads must have all required fields
    },
    3: {  # Tier 3: Code-Compliant - all inputs complete + verified
        "load": ["equipment_tag", "rated_kw", "flc_table_a", "fla_nameplate_a",
                 "feeder_type", "mcc_panel", "efficiency_pct", "service_factor"],
        # Tier 3 requires verified fault current AND verified cable lengths
        "metadata_required": ["fault_current_verified", "cable_lengths_verified"],
        "percentage": 100  # All loads must be complete
    }
}


def calculate_load_completeness(load: dict, tier: int) -> dict:
    """
    Calculate completeness of a single load for given tier.

    Args:
        load: Load dict to check
        tier: Target tier (1, 2, or 3)

    Returns:
        dict with completeness info
    """
    required = TIER_REQUIRED_FIELDS[tier]["load"]
    present = []
    missing = []

    for field in required:
        val = load.get(field)
        if val is not None and val != "" and val != 0:
            present.append(field)
        else:
            missing.append(field)

    complete = len(missing) == 0
    completeness_pct = (len(present) / len(required) * 100) if required else 100

    return {
        "complete": complete,
        "completeness_pct": round(completeness_pct, 1),
        "present_fields": present,
        "missing_fields": missing
    }


def calculate_tier_eligibility(
    loads: list[dict],
    metadata: dict = None,
    panels: list[dict] = None
) -> dict:
    """
    Calculate which output tier the dataset qualifies for.

    Args:
        loads: List of load dicts
        metadata: Project metadata dict (for Tier 3 verification checks)
        panels: List of panel dicts (optional, not used for gating)

    Returns:
        dict with tier eligibility and completeness metrics
    """
    if metadata is None:
        metadata = {}

    if not loads:
        return {
            "eligible_tier": 1,
            "tier_name": "Load Study",
            "overall_completeness_pct": 0,
            "tier_gates": {1: True, 2: False, 3: False},
            "load_completeness": []
        }

    # Check each load for each tier
    tier_results = {tier: [] for tier in [1, 2, 3]}

    for load in loads:
        for tier in [1, 2, 3]:
            result = calculate_load_completeness(load, tier)
            result["equipment_tag"] = load.get("equipment_tag", "")
            tier_results[tier].append(result)

    # Calculate tier eligibility based on load completeness
    tier_gates = {}

    for tier in [1, 2, 3]:
        threshold = TIER_REQUIRED_FIELDS[tier]["percentage"]
        complete_count = sum(1 for r in tier_results[tier] if r["complete"])
        complete_pct = (complete_count / len(loads) * 100) if loads else 0
        tier_gates[tier] = complete_pct >= threshold

    # Check metadata requirements for Tier 3 (verified fault current AND cable lengths)
    if tier_gates[3]:
        metadata_required = TIER_REQUIRED_FIELDS[3].get("metadata_required", [])
        for req in metadata_required:
            if req == "fault_current_verified":
                # Fault current must be verified, not assumed
                if metadata.get("fault_current_source") != "verified":
                    tier_gates[3] = False
                    break
            elif req == "cable_lengths_verified":
                # Cable lengths must be from layout, not estimated
                if not metadata.get("cable_lengths_verified", False):
                    tier_gates[3] = False
                    break

    # Determine highest eligible tier
    if tier_gates[3]:
        eligible_tier = 3
        tier_name = "Code-Compliant"
    elif tier_gates[2]:
        eligible_tier = 2
        tier_name = "Preliminary Schedule"
    else:
        eligible_tier = 1
        tier_name = "Load Study"

    # Calculate overall completeness for display
    tier2_results = tier_results[2]
    avg_completeness = sum(r["completeness_pct"] for r in tier2_results) / len(tier2_results)

    return {
        "eligible_tier": eligible_tier,
        "tier_name": tier_name,
        "overall_completeness_pct": round(avg_completeness, 1),
        "tier_gates": tier_gates,
        "tier_2_complete_loads": sum(1 for r in tier2_results if r["complete"]),
        "total_loads": len(loads),
        "tier_2_threshold_pct": TIER_REQUIRED_FIELDS[2]["percentage"],
        "load_completeness": tier2_results  # For detailed reporting
    }


def load_equipment_list(path: Path) -> tuple[dict, list[dict]]:
    """
    Load equipment list from QMD or YAML file.

    Args:
        path: Path to equipment list file

    Returns:
        Tuple of (metadata, equipment_list)
    """
    with open(path) as f:
        content = f.read()

    # Check for QMD format (YAML frontmatter between ---)
    if path.suffix in [".qmd", ".md"]:
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1])
            return frontmatter, frontmatter.get("equipment", [])

    # Plain YAML
    data = yaml.safe_load(content)
    if isinstance(data, list):
        return {}, data
    return data, data.get("equipment", data.get("loads", []))


def extract_equipment_type(tag: str) -> str:
    """Extract equipment type code from tag."""
    match = re.match(r"\d{3}-([A-Z]{1,5})-\d+", tag)
    if match:
        return match.group(1)
    return ""


def process_load(
    equipment: dict,
    duty_point: dict,
    motor_standard: str,
    voltage: int,
    frequency: int
) -> dict:
    """
    Process a single equipment item into a load entry.

    Args:
        equipment: Equipment dict from equipment list
        duty_point: Duty point data from sizing artifacts
        motor_standard: IEC or NEMA
        voltage: System voltage
        frequency: System frequency (50 or 60)

    Returns:
        Processed load dict
    """
    tag = equipment.get("tag", equipment.get("equipment_tag", ""))
    eq_type = equipment.get("equipment_type", extract_equipment_type(tag))
    installed_kw = equipment.get("power_kw", equipment.get("power_kW", equipment.get("installed_kw", 0)))
    feeder_type = equipment.get("feeder_type", "DOL")
    process_unit = equipment.get("process_unit_type", "")

    # Get motor parameters
    poles = equipment.get("motor_poles", 4)
    efficiency_class = equipment.get("efficiency_class", "IE3" if motor_standard == "IEC" else "NEMA-PREMIUM")

    # Look up FLC from tables (for conductor/SCPD sizing per NEC 430.6(A)(1))
    flc_table, flc_source = lookup_fla(
        installed_kw,
        voltage,
        3,  # phases
        frequency,
        motor_standard,
        efficiency_class
    )

    # Get motor efficiency (needed for FLA estimation)
    efficiency_pct = equipment.get("efficiency_pct")
    if not efficiency_pct:
        efficiency_pct = get_motor_efficiency(installed_kw, poles, efficiency_class)

    # FLA from nameplate (for overload settings per NEC 430.32)
    # If not provided, estimate from rated power and efficiency
    fla_nameplate = equipment.get("fla_nameplate_a")
    if fla_nameplate is None:
        # Estimate: FLA = (kW × 1000) / (√3 × V × η × pf)
        import math
        eff = efficiency_pct / 100 if efficiency_pct else 0.90
        pf_est = equipment.get("pf", 0.85)
        fla_nameplate = (installed_kw * 1000) / (math.sqrt(3) * voltage * eff * pf_est)

    # Calculate LRA from table FLC
    lra = calc_lra(flc_table, 6.0)

    # Calculate brake power based on equipment type
    brake_kw = duty_point.get("brake_kw")
    if brake_kw is None:
        if eq_type in ["P", "PU"]:
            flow = duty_point.get("flow_m3h", 0)
            head = duty_point.get("head_m", 0)
            pump_eff = duty_point.get("pump_eff", 0.70)
            if flow and head:
                brake_kw = calc_pump_brake_kw(flow, head, 1.0, pump_eff)
        elif eq_type in ["B", "BL"]:
            flow = duty_point.get("flow_nm3h", 0)
            p1 = duty_point.get("p1_bar", 1.013)
            p2 = duty_point.get("p2_bar", 1.6)
            blower_eff = duty_point.get("blower_eff", 0.70)
            if flow:
                brake_kw = calc_blower_brake_kw(flow, p1, p2, 293, 1.4, blower_eff)
        elif eq_type in ["AG", "MX"]:
            volume = duty_point.get("volume_m3", 0)
            w_per_m3 = duty_point.get("w_per_m3", 8)
            if volume:
                brake_kw = calc_mixer_brake_kw(volume, w_per_m3)

    # If still no brake power, estimate from rated power
    # FIXED: brake_kw is MECHANICAL output, not electrical input
    # Formula: brake_kw = rated_kw * load_factor (where load_factor accounts for partial loading)
    # NOT: brake_kw = installed_kw * efficiency * 0.85 (this was incorrect - double-counting)
    if brake_kw is None:
        # For motors, rated_kw IS the brake power at full load
        # Apply typical load factor for partial loading estimate
        typical_load_factor = 0.85  # Typical pump/blower loading
        brake_kw = installed_kw * typical_load_factor

    # Calculate absorbed power
    absorbed_kw = calc_absorbed_kw(brake_kw, efficiency_pct)

    # Get duty profile
    profile = get_duty_profile(eq_type, process_unit, feeder_type)
    running_hours = profile["running_hours_per_day"]
    load_factor = profile["load_factor"]
    duty_cycle = profile["duty_cycle"]

    # Parse diversity from quantity note
    quantity_note = equipment.get("quantity_note", "")
    quantity = equipment.get("quantity", 1)
    diversity_factor, working, standby = parse_diversity_from_quantity_note(quantity_note)
    if not quantity_note and quantity > 1:
        diversity_factor = 1.0  # All running if no standby specified

    # Calculate energy values
    running_kw = calc_running_kw(absorbed_kw, load_factor)
    demand_kw = calc_demand_kw(running_kw, diversity_factor)
    daily_kwh = calc_daily_kwh(running_kw, running_hours)

    # Power factor estimate
    pf = equipment.get("pf", 0.85)

    # Build load entry
    load = {
        # Equipment Identity
        "equipment_tag": tag,
        "description": equipment.get("description", ""),
        "process_unit_type": process_unit,
        "area": equipment.get("area", 100),
        "equipment_type": eq_type,

        # Motor Nameplate
        "rated_kw": installed_kw,  # New semantic term
        "installed_kw": installed_kw,  # Deprecated but kept for compatibility
        "voltage_v": voltage,
        "phases": 3,
        "frequency_hz": frequency,
        "motor_poles": poles,
        "efficiency_pct": efficiency_pct,
        "pf": pf,
        "efficiency_class": efficiency_class,
        "service_factor": 1.0 if motor_standard == "IEC" else 1.15,

        # FLC vs FLA Distinction (NEC 430.6(A)(1))
        "flc_table_a": round(flc_table, 1),  # From code tables - for conductor/SCPD sizing
        "fla_nameplate_a": round(fla_nameplate, 1),  # From nameplate - for overload settings
        "fla": round(flc_table, 1),  # Deprecated - kept for compatibility
        "lra": round(lra, 1),
        "lra_multiplier": 6.0,
        "fla_source": flc_source,
        "flc_provenance": {
            "source": "table" if "table" in flc_source.lower() or "nec" in flc_source.lower() or "iec" in flc_source.lower() else "calculated",
            "selection_stage": "preliminary_generic",
            "verified": False,
            "notes": f"From {flc_source}"
        },

        # Feeder/Starter
        "feeder_type": feeder_type,

        # Duty Point
        "brake_kw": round(brake_kw, 2) if brake_kw else None,
        "absorbed_kw": round(absorbed_kw, 2),
        "duty_cycle": duty_cycle,
        "running_hours_per_day": running_hours,
        "load_factor": load_factor,
        "diversity_factor": diversity_factor,
        "quantity": quantity,
        "quantity_note": quantity_note or f"{quantity}W",
        "running_kw": round(running_kw, 2),
        "demand_kw": round(demand_kw, 2),
        "daily_kwh": round(daily_kwh, 2),

        # Panel
        "mcc_panel": equipment.get("mcc_panel", f"MCC-{equipment.get('area', 100)}"),

        # Traceability
        "duty_point_source": duty_point.get("source"),
    }

    return load


def generate_load_list(
    equipment_path: Path,
    project_dir: Path,
    motor_standard: str = "IEC",
    voltage: int = 400,
    frequency: int = 50,
    capacity_mld: Optional[float] = None
) -> dict:
    """
    Generate complete load list from equipment list.

    Args:
        equipment_path: Path to equipment list file
        project_dir: Project directory for finding sizing artifacts
        motor_standard: IEC or NEMA
        voltage: System voltage
        frequency: System frequency
        capacity_mld: Plant capacity in MLD (for specific energy calc)

    Returns:
        Complete load list dict
    """
    # Load equipment list
    metadata, equipment_list = load_equipment_list(equipment_path)
    project_id = metadata.get("project_id", "UNKNOWN")

    if capacity_mld is None:
        capacity_mld = metadata.get("capacity_mld", 10)

    # Filter to only motorized equipment
    motorized_types = ["P", "PU", "B", "BL", "AG", "MX", "SC", "CN", "C", "FN", "TH", "CF", "BF"]
    motor_equipment = []
    for eq in equipment_list:
        tag = eq.get("tag", eq.get("equipment_tag", ""))
        eq_type = eq.get("equipment_type", extract_equipment_type(tag))
        if eq_type in motorized_types and eq.get("power_kw", eq.get("power_kW", eq.get("installed_kw", 0))) > 0:
            motor_equipment.append(eq)

    # Extract duty points
    duty_points = extract_all_duty_points(motor_equipment, project_dir)

    # Process each equipment
    loads = []
    for eq in motor_equipment:
        tag = eq.get("tag", eq.get("equipment_tag", ""))
        duty_point = duty_points.get(tag, {})
        load = process_load(eq, duty_point, motor_standard, voltage, frequency)
        loads.append(load)

    # Assign panels if not already assigned
    loads = assign_panels_by_area(loads)

    # Aggregate by panel
    panels = aggregate_by_panel(loads, voltage, 3)

    # Calculate totals
    totals = calculate_plant_totals(panels)

    # Calculate specific energy
    daily_kwh = sum(l.get("daily_kwh", 0) for l in loads)
    flow_m3_per_day = capacity_mld * 1000
    specific_energy = calc_specific_energy(daily_kwh, flow_m3_per_day)

    # Get fault current configuration (conservative default if not provided)
    fault_current_config = get_fault_current_config(metadata, voltage)
    available_fault_ka = fault_current_config["at_mcc_bus_ka"]

    # Calculate tier eligibility based on data completeness
    tier_eligibility = calculate_tier_eligibility(loads, metadata, panels)
    eligible_tier = tier_eligibility["eligible_tier"]
    tier_name = tier_eligibility["tier_name"]
    completeness_pct = tier_eligibility["overall_completeness_pct"]

    # Build tier disclaimers based on eligibility
    disclaimers = []
    if eligible_tier == 1:
        disclaimers = [
            "PRELIMINARY - FOR PLANNING PURPOSES ONLY",
            "Protection sizing requires Tier 2 output (≥80% motor data complete)",
            "Cable schedules not available at this tier"
        ]
    elif eligible_tier == 2:
        disclaimers = [
            "PRELIMINARY SCHEDULE - VERIFY MOTOR DATA BEFORE PROCUREMENT",
            "Code-compliant output requires verified fault current data"
        ]
    else:
        disclaimers = ["Code-compliant output ready for detailed engineering"]

    # Build base output (always included)
    output = {
        "version": "2.0.0",
        "project_id": project_id,
        "electrical_basis": {
            "code_basis": {
                "standard": "NEC" if motor_standard == "NEMA" else "IEC",
                "nec_edition": "2023" if motor_standard == "NEMA" else None,
                "iec_basis": "IEC 60364" if motor_standard == "IEC" else None
            },
            "motor_standard": motor_standard,
            "cable_standard": "NEC" if motor_standard == "NEMA" else "IEC",
            "voltage_system": {
                "lv_voltage": voltage,
                "frequency": frequency
            },
            "available_fault_current": {
                "at_mcc_bus_ka": fault_current_config["at_mcc_bus_ka"],
                "source": fault_current_config["source"],
                "verified": fault_current_config.get("verified", False),
                "warning": fault_current_config.get("warning")
            }
        },
        "output_tier": {
            "tier": eligible_tier,
            "tier_name": tier_name,
            "completeness_pct": completeness_pct,
            "tier_gates": tier_eligibility["tier_gates"],
            "disclaimers": disclaimers
        },
        "assumption_tracking": {
            # Cable lengths are assumed unless user provides cable_routes.yaml
            "cable_lengths_assumed": not metadata.get("cable_lengths_verified", False),
            "cable_lengths_source": metadata.get("cable_lengths_source", "estimated"),
            "fault_current_assumed": not fault_current_config.get("verified", False),
            "fault_current_source": fault_current_config["source"],
            "motor_data_verified": eligible_tier >= 3,
            # takeoff_ready requires verified cable lengths (for contractor costing)
            "takeoff_ready": eligible_tier >= 2 and metadata.get("cable_lengths_verified", False),
            # sccr_ready requires verified fault current
            "sccr_ready": eligible_tier >= 3 and fault_current_config.get("verified", False),
            "notes": [
                note for note in [
                    "Cable lengths are ESTIMATED - verify against final plant layout" if not metadata.get("cable_lengths_verified", False) else None,
                    "Fault current values require utility coordination letter" if not fault_current_config.get("verified", False) else None
                ] if note
            ]
        },
        "loads": loads,
        "mcc_panels": [
            {
                "panel_tag": p["panel_tag"],
                "area": p["area"],
                "supply_voltage": p["supply_voltage"],
                "connected_kw": p["connected_kw"],
                "running_kw": p["running_kw"],
                "demand_kw": p["demand_with_diversity_kw"],
                "panel_diversity": p["panel_diversity"],
                "demand_kva": p["demand_kva"],
                "demand_amps": p["demand_amps"],
                "feeder_counts": p["feeder_counts"],
                "main_breaker_a": p["main_breaker_a"],
                "bus_rating": p["bus_rating"]
            }
            for p in panels
        ],
        "energy_summary": {
            "total_connected_kw": totals["total_connected_kw"],
            "total_running_kw": totals["total_running_kw"],
            "total_demand_kw": totals["plant_demand_kw"],
            "daily_kwh": round(daily_kwh, 1),
            "specific_energy_kwh_m3": specific_energy
        }
    }

    # Generate Tier 2+ outputs (MCC buckets, cable schedule) if eligible
    if eligible_tier >= 2 and MCC_MODULES_AVAILABLE:
        # Use the conservative fault current value from earlier calculation
        # (available_fault_ka was set from fault_current_config)

        # Generate MCC bucket schedules for each panel
        mcc_buckets = []
        nec_panel_summaries = {}  # Store NEC panel data for merging

        for panel in panels:
            panel_tag = panel["panel_tag"]
            panel_loads = [l for l in loads if l.get("mcc_panel") == panel_tag]

            if panel_loads:
                mcc_schedule = generate_mcc_schedule(
                    loads=panel_loads,
                    panel_tag=panel_tag,
                    voltage=voltage,
                    motor_standard=motor_standard,
                    available_fault_ka=available_fault_ka,
                    scpd_type="dual_element_fuse",
                    withdrawable=False,
                    include_spares=2
                )
                mcc_buckets.extend(mcc_schedule.get("buckets", []))
                # Store NEC panel summary for merging into mcc_panels
                if "panel_summary" in mcc_schedule:
                    nec_panel_summaries[panel_tag] = mcc_schedule["panel_summary"]

        output["mcc_buckets"] = mcc_buckets

        # Merge NEC feeder sizing fields into mcc_panels
        for panel_data in output["mcc_panels"]:
            panel_tag = panel_data.get("panel_tag")
            if panel_tag in nec_panel_summaries:
                nec_summary = nec_panel_summaries[panel_tag]
                # Add NEC-compliant sizing fields from Phase 4
                panel_data["feeder_conductor_min_a"] = nec_summary.get("feeder_conductor_min_a")
                panel_data["feeder_ocpd_max_a"] = nec_summary.get("feeder_ocpd_max_a")
                panel_data["lineup_sccr_ka"] = nec_summary.get("lineup_sccr_ka")
                panel_data["sccr_compliant"] = nec_summary.get("sccr_compliant")
                panel_data["bucket_count"] = nec_summary.get("bucket_count")
                panel_data["unit_type"] = nec_summary.get("unit_type")

        # Generate cable schedule (structured per schema)
        from generate_cable_schedule import generate_all_cable_schedules
        cable_schedule_data = generate_all_cable_schedules(
            loads=loads,
            voltage=voltage,
            cable_standard="IEC" if motor_standard == "IEC" else "NEC"
        )
        # Flatten cables for xlsx compatibility while keeping full structure
        all_cables = []
        for panel_schedule in cable_schedule_data.get("cable_schedules", {}).values():
            all_cables.extend(panel_schedule.get("cables", []))
        output["cable_schedule"] = {
            "cables": all_cables,
            "total_cables": cable_schedule_data.get("total_cables", len(all_cables)),
            "total_length_m": cable_schedule_data.get("total_length_m", 0),
            "size_summary": cable_schedule_data.get("size_summary", {}),
            "generation_basis": cable_schedule_data.get("generation_basis", {}),
            "disclaimers": cable_schedule_data.get("disclaimers", [])
        }

        # Generate plant load summary
        plant_summary = calc_plant_load_summary(
            process_loads=loads,
            non_process_allowance_pct=15,
            future_growth_pct=20,
            power_factor=0.85
        )
        output["plant_load_summary"] = plant_summary

        # Generate transformer sizing
        total_demand_kva = totals["plant_demand_kw"] / 0.85  # Estimated pf
        transformer = size_transformer(
            connected_kva=totals["total_connected_kw"] / 0.85,
            demand_kva=total_demand_kva,
            future_growth_pct=20,
            standard="ANSI" if motor_standard == "NEMA" else "IEC"
        )
        output["transformers"] = [{
            "transformer_tag": "TX-001",
            "primary_voltage": "11kV" if motor_standard == "IEC" else "13.8kV",
            "secondary_voltage": f"{voltage}V",
            **transformer
        }]

        # Motor starting analysis
        motor_list = [
            {
                "rated_kw": l.get("rated_kw", 0),
                "equipment_tag": l.get("equipment_tag"),
                "feeder_type": l.get("feeder_type", "DOL")
            }
            for l in loads
        ]
        transformer_kva = transformer.get("selected_kva", 1000)
        transformer_z = transformer.get("typical_impedance_pct", transformer.get("impedance_pct", 5.75))
        starting_analysis = check_sequential_starting(
            motors=motor_list,
            source_kva=transformer_kva,
            source_impedance_pct=transformer_z,
            max_voltage_dip_pct=15,
            voltage=voltage
        )
        output["motor_starting_analysis"] = starting_analysis

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Generate electrical load list from equipment list"
    )
    parser.add_argument(
        "--equipment", "-e",
        type=Path,
        required=True,
        help="Path to equipment list (QMD or YAML)"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Output path for load list YAML"
    )
    parser.add_argument(
        "--project-dir", "-p",
        type=Path,
        default=Path("."),
        help="Project directory for finding sizing artifacts"
    )
    parser.add_argument(
        "--motor-standard", "-m",
        choices=["IEC", "NEMA"],
        default="IEC",
        help="Motor standard (default: IEC)"
    )
    parser.add_argument(
        "--voltage", "-v",
        type=int,
        default=400,
        help="System voltage (default: 400)"
    )
    parser.add_argument(
        "--frequency", "-f",
        type=int,
        choices=[50, 60],
        default=50,
        help="System frequency (default: 50)"
    )
    parser.add_argument(
        "--capacity-mld",
        type=float,
        help="Plant capacity in MLD (for specific energy)"
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.equipment.exists():
        print(f"Error: Equipment list not found: {args.equipment}")
        sys.exit(1)

    # Generate load list
    print(f"Generating load list from {args.equipment}...")
    print(f"  Motor standard: {args.motor_standard}")
    print(f"  Voltage: {args.voltage}V")
    print(f"  Frequency: {args.frequency}Hz")

    load_list = generate_load_list(
        args.equipment,
        args.project_dir,
        args.motor_standard,
        args.voltage,
        args.frequency,
        args.capacity_mld
    )

    # Create output directory if needed
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Write output
    with open(args.output, "w") as f:
        yaml.dump(load_list, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Print summary
    print(f"\nGenerated load list: {args.output}")
    print(f"  Loads: {len(load_list['loads'])}")
    print(f"  Panels: {len(load_list['mcc_panels'])}")
    print(f"  Connected: {load_list['energy_summary']['total_connected_kw']} kW")
    print(f"  Running: {load_list['energy_summary']['total_running_kw']} kW")
    print(f"  Demand: {load_list['energy_summary']['total_demand_kw']} kW")
    print(f"  Daily Energy: {load_list['energy_summary']['daily_kwh']} kWh")
    print(f"  Specific Energy: {load_list['energy_summary']['specific_energy_kwh_m3']} kWh/m³")


if __name__ == "__main__":
    main()
