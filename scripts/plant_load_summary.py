#!/usr/bin/env python3
"""
Plant Load Summary Module
Calculate total plant electrical load with non-process allowances.

Generates comprehensive load summary for:
- Transformer sizing
- Generator sizing
- Utility coordination

Author: Load List Skill
"""

import math
from pathlib import Path
from typing import Optional, Literal

import yaml


def load_non_process_catalog() -> dict:
    """Load non-process allowances catalog."""
    catalogs_dir = Path(__file__).parent.parent / "catalogs"
    path = catalogs_dir / "non_process_loads.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def calc_non_process_allowance(
    process_demand_kw: float,
    allowance_pct: float = 15,
    breakdown: Optional[dict] = None
) -> dict:
    """
    Calculate non-process load allowance.

    Args:
        process_demand_kw: Total process demand load
        allowance_pct: Total allowance percentage
        breakdown: Optional dict with individual allowance percentages

    Returns:
        dict with non-process load calculations
    """
    if breakdown is None:
        # Use default breakdown
        breakdown = {
            "hvac": 5,
            "lighting": 3,
            "small_power": 2,
            "instrumentation": 2,
            "control_power": 1,
            "security": 0.5,
            "misc": 1.5
        }

    # Calculate individual components
    components = {}
    total_breakdown_pct = 0

    for category, pct in breakdown.items():
        kw = process_demand_kw * (pct / 100)
        components[category] = {
            "allowance_pct": pct,
            "demand_kw": round(kw, 1)
        }
        total_breakdown_pct += pct

    # Total non-process load
    total_non_process_kw = process_demand_kw * (allowance_pct / 100)

    return {
        "process_demand_kw": process_demand_kw,
        "allowance_pct": allowance_pct,
        "total_non_process_kw": round(total_non_process_kw, 1),
        "components": components,
        "notes": f"Non-process allowance: {allowance_pct}% of {process_demand_kw:.0f} kW process demand"
    }


def calc_plant_load_summary(
    process_loads: list[dict],
    non_process_allowance_pct: float = 15,
    future_growth_pct: float = 20,
    power_factor: float = 0.85,
    include_standby: bool = False
) -> dict:
    """
    Calculate complete plant electrical load summary.

    Args:
        process_loads: List of process load dicts
        non_process_allowance_pct: Non-process load percentage
        future_growth_pct: Future growth allowance
        power_factor: Overall power factor assumption
        include_standby: Include standby/spare equipment in connected

    Returns:
        dict with complete plant load summary
    """
    # Calculate process load totals
    process_connected_kw = 0
    process_demand_kw = 0
    motor_count = 0
    largest_motor_kw = 0
    largest_motor_tag = ""

    for load in process_loads:
        # Get rated kW (may be from different fields)
        rated_kw = load.get("rated_kw", load.get("installed_kw", 0))

        # Check if standby
        is_standby = load.get("duty", "").upper() in ["STANDBY", "SPARE", "S"]
        is_standby = is_standby or load.get("standby", False)

        # Add to connected
        if include_standby or not is_standby:
            process_connected_kw += rated_kw

        # Add to demand (non-standby only)
        if not is_standby:
            demand_kw = load.get("demand_kw", rated_kw * load.get("load_factor", 0.8))
            process_demand_kw += demand_kw

        # Track motors
        if load.get("load_type", "").upper() == "MOTOR":
            motor_count += 1
            if rated_kw > largest_motor_kw:
                largest_motor_kw = rated_kw
                largest_motor_tag = load.get("equipment_tag", "")

    # Non-process loads
    non_process = calc_non_process_allowance(
        process_demand_kw,
        non_process_allowance_pct
    )
    non_process_connected_kw = process_connected_kw * (non_process_allowance_pct / 100)
    non_process_demand_kw = non_process["total_non_process_kw"]

    # Totals
    total_connected_kw = process_connected_kw + non_process_connected_kw
    total_demand_kw = process_demand_kw + non_process_demand_kw

    # Convert to kVA
    total_connected_kva = total_connected_kw / power_factor
    total_demand_kva = total_demand_kw / power_factor

    # Future growth
    future_demand_kw = total_demand_kw * (1 + future_growth_pct / 100)
    future_demand_kva = future_demand_kw / power_factor

    # Diversity factor (demand/connected)
    diversity_factor = total_demand_kw / total_connected_kw if total_connected_kw > 0 else 1.0

    return {
        "summary": {
            "process_connected_kw": round(process_connected_kw, 1),
            "process_demand_kw": round(process_demand_kw, 1),
            "non_process_allowance_pct": non_process_allowance_pct,
            "non_process_connected_kw": round(non_process_connected_kw, 1),
            "non_process_demand_kw": round(non_process_demand_kw, 1),
            "total_connected_kw": round(total_connected_kw, 1),
            "total_demand_kw": round(total_demand_kw, 1),
            "total_connected_kva": round(total_connected_kva, 1),
            "total_demand_kva": round(total_demand_kva, 1),
            "diversity_factor": round(diversity_factor, 3),
            "power_factor": power_factor,
        },
        "future_growth": {
            "growth_pct": future_growth_pct,
            "future_demand_kw": round(future_demand_kw, 1),
            "future_demand_kva": round(future_demand_kva, 1),
        },
        "transformer_sizing": {
            "minimum_kva": round(future_demand_kva, 0),
            "recommended_kva": round(future_demand_kva * 1.1, 0),  # 10% margin
            "notes": f"Minimum {future_demand_kva:.0f} kVA for {future_growth_pct}% future growth"
        },
        "motor_statistics": {
            "motor_count": motor_count,
            "largest_motor_kw": largest_motor_kw,
            "largest_motor_tag": largest_motor_tag,
        },
        "non_process_breakdown": non_process["components"],
        "assumptions": [
            f"Non-process allowance: {non_process_allowance_pct}% of process demand",
            f"Future growth: {future_growth_pct}%",
            f"Power factor: {power_factor}",
            "Standby equipment excluded from demand" if not include_standby else "Standby equipment included"
        ]
    }


def calc_transformer_requirement(
    plant_summary: dict,
    standard: Literal["ANSI", "IEC"] = "ANSI",
    max_loading_pct: float = 85
) -> dict:
    """
    Determine transformer requirement from plant load summary.

    Args:
        plant_summary: Output from calc_plant_load_summary
        standard: ANSI or IEC for standard sizes
        max_loading_pct: Maximum acceptable loading percentage

    Returns:
        dict with transformer sizing recommendation
    """
    # Standard transformer sizes
    ansi_sizes = [15, 25, 37.5, 50, 75, 100, 112.5, 150, 167, 200, 225, 300,
                  500, 750, 1000, 1500, 2000, 2500, 3333, 5000]
    iec_sizes = [16, 25, 40, 63, 100, 160, 200, 250, 315, 400, 500, 630,
                 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]

    sizes = ansi_sizes if standard == "ANSI" else iec_sizes

    # Get required kVA
    future_demand_kva = plant_summary["future_growth"]["future_demand_kva"]

    # Account for loading limit
    minimum_kva = future_demand_kva / (max_loading_pct / 100)

    # Find next standard size
    selected_kva = None
    for size in sizes:
        if size >= minimum_kva:
            selected_kva = size
            break

    if selected_kva is None:
        selected_kva = sizes[-1]
        multiple_required = True
        count = math.ceil(minimum_kva / sizes[-1])
    else:
        multiple_required = False
        count = 1

    # Calculate loading
    loading_pct = (future_demand_kva / selected_kva) * 100

    return {
        "future_demand_kva": round(future_demand_kva, 1),
        "minimum_kva_at_loading_limit": round(minimum_kva, 1),
        "max_loading_pct": max_loading_pct,
        "selected_kva": selected_kva,
        "standard": standard,
        "loading_pct": round(loading_pct, 1),
        "spare_capacity_pct": round(100 - loading_pct, 1),
        "multiple_transformers_required": multiple_required,
        "transformer_count": count,
        "recommendation": (
            f"{count}× {selected_kva} kVA transformer" if multiple_required
            else f"{selected_kva} kVA transformer @ {loading_pct:.0f}% loading"
        )
    }


def calc_generator_requirement(
    plant_summary: dict,
    emergency_load_pct: float = 30,
    critical_motors: Optional[list[dict]] = None
) -> dict:
    """
    Calculate emergency/standby generator requirement.

    Args:
        plant_summary: Output from calc_plant_load_summary
        emergency_load_pct: Percentage of demand for emergency loads
        critical_motors: List of critical motor dicts that must run

    Returns:
        dict with generator sizing recommendation
    """
    total_demand_kw = plant_summary["summary"]["total_demand_kw"]
    largest_motor_kw = plant_summary["motor_statistics"]["largest_motor_kw"]

    # Base emergency load
    emergency_kw = total_demand_kw * (emergency_load_pct / 100)

    # Add critical motors if specified
    critical_motor_kw = 0
    critical_starting_kw = 0
    if critical_motors:
        for motor in critical_motors:
            kw = motor.get("rated_kw", motor.get("installed_kw", 0))
            critical_motor_kw += kw
        # Largest critical motor starting kVA
        largest_critical = max(m.get("rated_kw", m.get("installed_kw", 0))
                               for m in critical_motors) if critical_motors else 0
        critical_starting_kw = largest_critical * 6 / 0.85  # LRA ≈ 6× FLC, 0.3 pf

    # Generator must handle running load + motor starting
    running_kw = max(emergency_kw, critical_motor_kw)

    # Motor starting consideration (largest motor start while others running)
    # Assume 25% voltage dip acceptable for generator
    # kW_generator = Starting kVA / 0.25 (simplified)
    starting_allowance_kw = largest_motor_kw * 6 / 0.85 * 0.30  # 30% pf during start
    starting_requirement_kw = running_kw + starting_allowance_kw

    # Select larger of running or starting requirement
    required_kw = max(running_kw, starting_requirement_kw * 0.7)  # Allow some dip

    # Standard generator sizes (kW)
    gen_sizes = [30, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 500,
                 600, 750, 800, 1000, 1250, 1500, 2000, 2500, 3000]

    selected_kw = None
    for size in gen_sizes:
        if size >= required_kw:
            selected_kw = size
            break

    if selected_kw is None:
        selected_kw = gen_sizes[-1]

    return {
        "total_plant_demand_kw": round(total_demand_kw, 1),
        "emergency_load_pct": emergency_load_pct,
        "emergency_load_kw": round(emergency_kw, 1),
        "critical_motor_kw": round(critical_motor_kw, 1),
        "largest_motor_kw": largest_motor_kw,
        "motor_starting_allowance_kw": round(starting_allowance_kw, 1),
        "minimum_generator_kw": round(required_kw, 1),
        "selected_generator_kw": selected_kw,
        "loading_pct": round((running_kw / selected_kw) * 100, 1),
        "recommendation": f"{selected_kw} kW standby generator",
        "notes": [
            f"Emergency loads: {emergency_load_pct}% of plant demand",
            f"Largest motor starting considered: {largest_motor_kw} kW",
            "Generator must handle motor inrush (voltage dip)"
        ]
    }


def format_load_summary_report(summary: dict) -> str:
    """
    Format plant load summary as text report.

    Args:
        summary: Output from calc_plant_load_summary

    Returns:
        Formatted text report
    """
    lines = []
    lines.append("=" * 70)
    lines.append("PLANT ELECTRICAL LOAD SUMMARY")
    lines.append("=" * 70)
    lines.append("")

    s = summary["summary"]
    lines.append("LOAD SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Process Connected:     {s['process_connected_kw']:>8.1f} kW")
    lines.append(f"  Process Demand:        {s['process_demand_kw']:>8.1f} kW")
    lines.append(f"  Non-Process ({s['non_process_allowance_pct']}%):    {s['non_process_demand_kw']:>8.1f} kW")
    lines.append(f"  {'─' * 36}")
    lines.append(f"  TOTAL CONNECTED:       {s['total_connected_kw']:>8.1f} kW")
    lines.append(f"  TOTAL DEMAND:          {s['total_demand_kw']:>8.1f} kW")
    lines.append(f"  TOTAL DEMAND (kVA):    {s['total_demand_kva']:>8.1f} kVA @ pf={s['power_factor']}")
    lines.append(f"  Diversity Factor:      {s['diversity_factor']:>8.3f}")
    lines.append("")

    fg = summary["future_growth"]
    lines.append("FUTURE GROWTH")
    lines.append("-" * 40)
    lines.append(f"  Growth Allowance:      {fg['growth_pct']:>8}%")
    lines.append(f"  Future Demand (kW):    {fg['future_demand_kw']:>8.1f} kW")
    lines.append(f"  Future Demand (kVA):   {fg['future_demand_kva']:>8.1f} kVA")
    lines.append("")

    ts = summary["transformer_sizing"]
    lines.append("TRANSFORMER SIZING")
    lines.append("-" * 40)
    lines.append(f"  Minimum kVA:           {ts['minimum_kva']:>8.0f} kVA")
    lines.append(f"  Recommended kVA:       {ts['recommended_kva']:>8.0f} kVA")
    lines.append("")

    ms = summary["motor_statistics"]
    lines.append("MOTOR STATISTICS")
    lines.append("-" * 40)
    lines.append(f"  Total Motors:          {ms['motor_count']:>8}")
    lines.append(f"  Largest Motor:         {ms['largest_motor_kw']:>8.1f} kW ({ms['largest_motor_tag']})")
    lines.append("")

    lines.append("NON-PROCESS BREAKDOWN")
    lines.append("-" * 40)
    for category, data in summary["non_process_breakdown"].items():
        lines.append(f"  {category.replace('_', ' ').title():20s} {data['allowance_pct']:>3}%  {data['demand_kw']:>6.1f} kW")
    lines.append("")

    lines.append("ASSUMPTIONS")
    lines.append("-" * 40)
    for assumption in summary["assumptions"]:
        lines.append(f"  • {assumption}")
    lines.append("")

    lines.append("=" * 70)
    lines.append("NOTE: This is a PRELIMINARY estimate. Verify with detailed design.")
    lines.append("=" * 70)

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing plant_load_summary module...")
    print("=" * 60)

    # Sample process loads
    sample_loads = [
        {"equipment_tag": "200-B-01A", "rated_kw": 110, "demand_kw": 95,
         "load_type": "MOTOR", "duty": "DUTY"},
        {"equipment_tag": "200-B-01B", "rated_kw": 110, "demand_kw": 0,
         "load_type": "MOTOR", "duty": "STANDBY"},
        {"equipment_tag": "200-AG-01", "rated_kw": 22, "demand_kw": 18,
         "load_type": "MOTOR", "duty": "DUTY"},
        {"equipment_tag": "200-AG-02", "rated_kw": 22, "demand_kw": 18,
         "load_type": "MOTOR", "duty": "DUTY"},
        {"equipment_tag": "200-P-01A", "rated_kw": 37, "demand_kw": 30,
         "load_type": "MOTOR", "duty": "DUTY"},
        {"equipment_tag": "200-P-01B", "rated_kw": 37, "demand_kw": 0,
         "load_type": "MOTOR", "duty": "STANDBY"},
        {"equipment_tag": "200-SC-01", "rated_kw": 7.5, "demand_kw": 6,
         "load_type": "MOTOR", "duty": "DUTY"},
        {"equipment_tag": "200-TH-01", "rated_kw": 15, "demand_kw": 12,
         "load_type": "MOTOR", "duty": "DUTY"},
    ]

    # Calculate plant load summary
    summary = calc_plant_load_summary(
        process_loads=sample_loads,
        non_process_allowance_pct=15,
        future_growth_pct=20,
        power_factor=0.85
    )

    # Print formatted report
    print(format_load_summary_report(summary))

    # Calculate transformer requirement
    print("\n" + "=" * 60)
    print("TRANSFORMER SIZING RECOMMENDATION")
    print("=" * 60)
    xfmr = calc_transformer_requirement(summary, standard="ANSI")
    print(f"  Future Demand: {xfmr['future_demand_kva']} kVA")
    print(f"  Selected: {xfmr['recommendation']}")
    print(f"  Loading: {xfmr['loading_pct']}%")
    print(f"  Spare Capacity: {xfmr['spare_capacity_pct']}%")

    # Calculate generator requirement
    print("\n" + "=" * 60)
    print("GENERATOR SIZING RECOMMENDATION")
    print("=" * 60)
    gen = calc_generator_requirement(summary, emergency_load_pct=30)
    print(f"  Emergency Load ({gen['emergency_load_pct']}%): {gen['emergency_load_kw']} kW")
    print(f"  Largest Motor Starting: {gen['largest_motor_kw']} kW")
    print(f"  Selected: {gen['recommendation']}")
    print(f"  Loading: {gen['loading_pct']}%")

    print("\n" + "=" * 60)
    print("All tests completed!")
