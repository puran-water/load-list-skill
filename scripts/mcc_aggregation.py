#!/usr/bin/env python3
"""
MCC Aggregation Module
Panel rollup calculations for Motor Control Centers.

Aggregates loads by panel and calculates:
- Connected load (sum of installed kW)
- Running load (sum of running kW)
- Demand load (with diversity factors)
- Main breaker sizing
- Bus rating selection
"""

import math
from collections import defaultdict
from pathlib import Path
from typing import Optional

import yaml


# Standard bus bar ratings (A)
STANDARD_BUS_RATINGS = [400, 630, 800, 1000, 1600, 2000, 2500, 3200]

# Standard main breaker ratings (A)
STANDARD_BREAKER_RATINGS = [
    100, 125, 160, 200, 250, 315, 400, 500, 630,
    800, 1000, 1250, 1600, 2000, 2500, 3200, 4000
]


def _load_catalog(name: str) -> dict:
    """Load a YAML catalog file."""
    catalogs_dir = Path(__file__).parent.parent / "catalogs"
    path = catalogs_dir / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Catalog not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def get_panel_diversity_factor(
    feeder_count: int,
    process_type: Optional[str] = None
) -> float:
    """
    Get diversity factor for panel based on number of feeders.

    Args:
        feeder_count: Number of feeders in panel
        process_type: Optional process type for specific factors

    Returns:
        Diversity factor (0.65-0.90)
    """
    profiles = _load_catalog("duty_profiles")
    panel_div = profiles.get("panel_diversity", {})

    # Check process type specific factors
    if process_type:
        by_process = panel_div.get("by_process_type", {})
        for key, data in by_process.items():
            if key.lower() in process_type.lower():
                return data.get("diversity", 0.80)

    # Use feeder count based factors
    by_feeder = panel_div.get("by_feeder_count", [])
    for item in by_feeder:
        range_min, range_max = item.get("feeder_range", [0, 100])
        if range_min <= feeder_count <= range_max:
            return item.get("diversity", 0.80)

    # Default
    return 0.80


def select_bus_rating(demand_amps: float, margin: float = 1.25) -> str:
    """
    Select standard bus bar rating.

    Args:
        demand_amps: Calculated demand current
        margin: Safety margin (default 1.25 = 25%)

    Returns:
        Bus rating string (e.g., "630A")
    """
    required = demand_amps * margin

    for rating in STANDARD_BUS_RATINGS:
        if rating >= required:
            return f"{rating}A"

    # Exceeds standard range
    return f">{STANDARD_BUS_RATINGS[-1]}A"


def select_main_breaker(demand_amps: float, margin: float = 1.25) -> float:
    """
    Select standard main breaker rating.

    Args:
        demand_amps: Calculated demand current
        margin: Safety margin (default 1.25 = 25%)

    Returns:
        Breaker rating in Amps
    """
    required = demand_amps * margin

    for rating in STANDARD_BREAKER_RATINGS:
        if rating >= required:
            return float(rating)

    # Exceeds standard range
    return float(STANDARD_BREAKER_RATINGS[-1])


def calculate_demand_amps(
    demand_kva: float,
    voltage: float,
    phases: int = 3
) -> float:
    """
    Calculate demand current.

    Args:
        demand_kva: Demand power in kVA
        voltage: Line voltage
        phases: 1 or 3

    Returns:
        Current in Amps
    """
    if phases == 3:
        return (demand_kva * 1000) / (math.sqrt(3) * voltage)
    else:
        return (demand_kva * 1000) / voltage


def aggregate_by_panel(
    loads: list[dict],
    voltage: float = 400,
    phases: int = 3
) -> list[dict]:
    """
    Aggregate loads by MCC/panel assignment.

    Args:
        loads: List of load item dicts with mcc_panel, installed_kw,
               running_kw, demand_kw, feeder_type, pf
        voltage: Panel voltage
        phases: Number of phases

    Returns:
        List of panel summary dicts
    """
    # Group loads by panel
    panels = defaultdict(lambda: {
        "loads": [],
        "connected_kw": 0,
        "running_kw": 0,
        "demand_kw": 0,
        "feeder_counts": defaultdict(int),
        "pf_weighted_sum": 0
    })

    for load in loads:
        panel_tag = load.get("mcc_panel", "MCC-UNASSIGNED")
        panels[panel_tag]["loads"].append(load)
        panels[panel_tag]["connected_kw"] += load.get("installed_kw", 0)
        panels[panel_tag]["running_kw"] += load.get("running_kw", 0)
        panels[panel_tag]["demand_kw"] += load.get("demand_kw", 0)

        # Count feeder types
        feeder = load.get("feeder_type", "DOL").upper()
        if "VFD" in feeder:
            panels[panel_tag]["feeder_counts"]["vfd"] += 1
        elif "SOFT" in feeder:
            panels[panel_tag]["feeder_counts"]["soft_starter"] += 1
        elif "VENDOR" in feeder:
            panels[panel_tag]["feeder_counts"]["vendor"] += 1
        else:
            panels[panel_tag]["feeder_counts"]["dol"] += 1

        # Weighted power factor
        pf = load.get("pf", 0.85)
        power = load.get("running_kw", 0)
        panels[panel_tag]["pf_weighted_sum"] += pf * power

    # Build panel summaries
    results = []
    for panel_tag, data in sorted(panels.items()):
        feeder_count = sum(data["feeder_counts"].values())

        # Apply panel diversity
        panel_diversity = get_panel_diversity_factor(feeder_count)
        demand_with_diversity = data["demand_kw"] * panel_diversity

        # Calculate average power factor
        avg_pf = 0.85
        if data["running_kw"] > 0:
            avg_pf = data["pf_weighted_sum"] / data["running_kw"]
            avg_pf = max(0.7, min(1.0, avg_pf))  # Clamp to reasonable range

        # Calculate kVA and amps
        demand_kva = demand_with_diversity / avg_pf if avg_pf > 0 else demand_with_diversity
        demand_amps = calculate_demand_amps(demand_kva, voltage, phases)

        # Select equipment
        main_breaker = select_main_breaker(demand_amps)
        bus_rating = select_bus_rating(demand_amps)

        # Extract area from panel tag (e.g., MCC-200 -> 200)
        area = None
        if panel_tag:
            import re
            match = re.search(r"(\d{3})", panel_tag)
            if match:
                area = int(match.group(1))

        results.append({
            "panel_tag": panel_tag,
            "area": area,
            "supply_voltage": voltage,
            "connected_kw": round(data["connected_kw"], 1),
            "running_kw": round(data["running_kw"], 1),
            "demand_kw": round(data["demand_kw"], 1),
            "panel_diversity": panel_diversity,
            "demand_with_diversity_kw": round(demand_with_diversity, 1),
            "average_pf": round(avg_pf, 2),
            "demand_kva": round(demand_kva, 1),
            "demand_amps": round(demand_amps, 1),
            "feeder_counts": dict(data["feeder_counts"]),
            "feeder_count": feeder_count,
            "main_breaker_a": main_breaker,
            "bus_rating": bus_rating,
            "load_tags": [l.get("equipment_tag") for l in data["loads"]]
        })

    return results


def calculate_plant_totals(panels: list[dict]) -> dict:
    """
    Calculate plant-wide totals from panel summaries.

    Args:
        panels: List of panel summary dicts

    Returns:
        Dict with plant totals
    """
    total_connected = sum(p.get("connected_kw", 0) for p in panels)
    total_running = sum(p.get("running_kw", 0) for p in panels)
    total_demand = sum(p.get("demand_with_diversity_kw", 0) for p in panels)

    # Apply plant-level diversity (typical 0.85)
    plant_diversity = 0.85
    plant_demand = total_demand * plant_diversity

    # Count feeders
    total_feeders = {
        "dol": sum(p.get("feeder_counts", {}).get("dol", 0) for p in panels),
        "vfd": sum(p.get("feeder_counts", {}).get("vfd", 0) for p in panels),
        "soft_starter": sum(p.get("feeder_counts", {}).get("soft_starter", 0) for p in panels),
        "vendor": sum(p.get("feeder_counts", {}).get("vendor", 0) for p in panels)
    }

    return {
        "total_connected_kw": round(total_connected, 1),
        "total_running_kw": round(total_running, 1),
        "total_demand_kw": round(total_demand, 1),
        "plant_diversity": plant_diversity,
        "plant_demand_kw": round(plant_demand, 1),
        "panel_count": len(panels),
        "total_feeder_counts": total_feeders,
        "total_feeders": sum(total_feeders.values())
    }


def assign_panels_by_area(
    loads: list[dict],
    panel_prefix: str = "MCC"
) -> list[dict]:
    """
    Assign loads to panels based on area code.

    Creates one MCC per area (e.g., MCC-100, MCC-200).

    Args:
        loads: List of load dicts with area field
        panel_prefix: Panel naming prefix

    Returns:
        Updated loads with mcc_panel assigned
    """
    for load in loads:
        if not load.get("mcc_panel"):
            area = load.get("area", 100)
            load["mcc_panel"] = f"{panel_prefix}-{area}"

    return loads


def split_large_panels(
    loads: list[dict],
    max_feeders: int = 30,
    max_connected_kw: float = 500
) -> list[dict]:
    """
    Split large panels into multiple smaller ones.

    Args:
        loads: List of loads with mcc_panel assigned
        max_feeders: Maximum feeders per panel
        max_connected_kw: Maximum connected kW per panel

    Returns:
        Updated loads with split panel assignments
    """
    # Group by current panel
    panels = defaultdict(list)
    for load in loads:
        panels[load.get("mcc_panel", "MCC-UNASSIGNED")].append(load)

    # Check each panel
    for panel_tag, panel_loads in panels.items():
        feeder_count = len(panel_loads)
        connected_kw = sum(l.get("installed_kw", 0) for l in panel_loads)

        if feeder_count > max_feeders or connected_kw > max_connected_kw:
            # Split panel
            suffix = "A"
            current_feeders = 0
            current_kw = 0

            for load in sorted(panel_loads, key=lambda x: x.get("installed_kw", 0)):
                if (current_feeders >= max_feeders or
                    current_kw + load.get("installed_kw", 0) > max_connected_kw):
                    suffix = chr(ord(suffix) + 1)
                    current_feeders = 0
                    current_kw = 0

                load["mcc_panel"] = f"{panel_tag}{suffix}"
                current_feeders += 1
                current_kw += load.get("installed_kw", 0)

    return loads


if __name__ == "__main__":
    # Test with sample data
    sample_loads = [
        {
            "equipment_tag": "200-B-01A",
            "installed_kw": 110,
            "running_kw": 77,
            "demand_kw": 51.6,
            "feeder_type": "VFD",
            "pf": 0.88,
            "mcc_panel": "MCC-200",
            "area": 200
        },
        {
            "equipment_tag": "200-B-01B",
            "installed_kw": 110,
            "running_kw": 77,
            "demand_kw": 51.6,
            "feeder_type": "VFD",
            "pf": 0.88,
            "mcc_panel": "MCC-200",
            "area": 200
        },
        {
            "equipment_tag": "200-AG-01",
            "installed_kw": 22,
            "running_kw": 18.7,
            "demand_kw": 18.7,
            "feeder_type": "VFD",
            "pf": 0.85,
            "mcc_panel": "MCC-200",
            "area": 200
        },
        {
            "equipment_tag": "100-SC-01",
            "installed_kw": 3.7,
            "running_kw": 2.2,
            "demand_kw": 1.1,
            "feeder_type": "DOL",
            "pf": 0.80,
            "mcc_panel": "MCC-100",
            "area": 100
        }
    ]

    print("Testing MCC Aggregation...")
    print("=" * 60)

    panels = aggregate_by_panel(sample_loads, voltage=400)
    for panel in panels:
        print(f"\nPanel: {panel['panel_tag']}")
        print(f"  Connected: {panel['connected_kw']} kW")
        print(f"  Running: {panel['running_kw']} kW")
        print(f"  Demand: {panel['demand_with_diversity_kw']} kW")
        print(f"  Amps: {panel['demand_amps']} A")
        print(f"  Main Breaker: {panel['main_breaker_a']} A")
        print(f"  Bus Rating: {panel['bus_rating']}")
        print(f"  Feeders: {panel['feeder_counts']}")

    totals = calculate_plant_totals(panels)
    print("\n" + "=" * 60)
    print("Plant Totals:")
    print(f"  Connected: {totals['total_connected_kw']} kW")
    print(f"  Running: {totals['total_running_kw']} kW")
    print(f"  Plant Demand: {totals['plant_demand_kw']} kW")
    print(f"  Panels: {totals['panel_count']}")
    print(f"  Total Feeders: {totals['total_feeders']}")
