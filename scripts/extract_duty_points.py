#!/usr/bin/env python3
"""
Extract Duty Points Module
Extracts equipment duty points from Tier 1 sizing artifacts.

Sources:
- mcp-outputs/*/sizing.json (pump curves, blower sizing)
- Process datasheets
- Equipment list with capacity data
"""

import json
import re
from pathlib import Path
from typing import Any, Optional

import yaml


def find_sizing_artifacts(project_dir: Path) -> list[Path]:
    """
    Find all sizing artifact files in a project.

    Searches for:
    - mcp-outputs/*/sizing.json
    - sizing/*.json
    - *-sizing.yaml

    Args:
        project_dir: Project root directory

    Returns:
        List of paths to sizing files
    """
    artifacts = []

    # Look for MCP outputs
    mcp_outputs = project_dir / "mcp-outputs"
    if mcp_outputs.exists():
        artifacts.extend(mcp_outputs.glob("*/sizing.json"))
        artifacts.extend(mcp_outputs.glob("**/sizing.json"))

    # Look for sizing directory
    sizing_dir = project_dir / "sizing"
    if sizing_dir.exists():
        artifacts.extend(sizing_dir.glob("*.json"))
        artifacts.extend(sizing_dir.glob("*.yaml"))

    # Look for sizing files in various locations
    artifacts.extend(project_dir.glob("*-sizing.yaml"))
    artifacts.extend(project_dir.glob("*-sizing.json"))

    return sorted(set(artifacts))


def load_artifact(path: Path) -> dict:
    """Load a sizing artifact file."""
    with open(path) as f:
        if path.suffix in [".yaml", ".yml"]:
            return yaml.safe_load(f)
        else:
            return json.load(f)


def extract_pump_duty_points(artifact: dict, equipment_tag: str) -> Optional[dict]:
    """
    Extract pump duty point from sizing artifact.

    Looks for flow, head, efficiency data.

    Returns:
        Dict with flow_m3h, head_m, pump_eff, brake_kw or None
    """
    # Try different structures
    pumps = artifact.get("pumps", artifact.get("pump_sizing", []))
    if isinstance(pumps, dict):
        pumps = [pumps]

    for pump in pumps:
        tag = pump.get("tag", pump.get("equipment_tag", ""))
        if tag and (equipment_tag in tag or tag in equipment_tag):
            return {
                "flow_m3h": pump.get("flow_m3h", pump.get("flow", 0)),
                "head_m": pump.get("head_m", pump.get("head", pump.get("tdh", 0))),
                "pump_eff": pump.get("efficiency", pump.get("pump_eff", 0.70)),
                "brake_kw": pump.get("brake_kw", pump.get("power_kw", None)),
                "source": str(pump.get("_source", "sizing_artifact"))
            }

    # Check for general equipment
    equipment = artifact.get("equipment", [])
    for eq in equipment:
        tag = eq.get("tag", "")
        if tag and (equipment_tag in tag or tag in equipment_tag):
            if eq.get("flow") and eq.get("head"):
                return {
                    "flow_m3h": eq.get("flow"),
                    "head_m": eq.get("head"),
                    "pump_eff": eq.get("efficiency", 0.70),
                    "brake_kw": eq.get("brake_kw"),
                    "source": "equipment_list"
                }

    return None


def extract_blower_duty_points(artifact: dict, equipment_tag: str) -> Optional[dict]:
    """
    Extract blower duty point from sizing artifact.

    Looks for airflow, pressure data.

    Returns:
        Dict with flow_nm3h, p1_bar, p2_bar, blower_eff, brake_kw or None
    """
    # Try aeration-specific structures
    aeration = artifact.get("aeration", artifact.get("blower_sizing", {}))
    if isinstance(aeration, dict):
        blowers = aeration.get("blowers", [aeration])
    else:
        blowers = aeration

    for blower in blowers:
        tag = blower.get("tag", blower.get("equipment_tag", ""))
        if tag and (equipment_tag in tag or tag in equipment_tag):
            # Get pressure data
            p1 = blower.get("inlet_pressure_bar", 1.013)
            p2 = blower.get("outlet_pressure_bar",
                           p1 + blower.get("delivery_pressure_bar", 0.5))

            return {
                "flow_nm3h": blower.get("airflow_nm3h", blower.get("flow_nm3h", 0)),
                "p1_bar": p1,
                "p2_bar": p2,
                "blower_eff": blower.get("efficiency", blower.get("blower_eff", 0.70)),
                "brake_kw": blower.get("brake_kw", blower.get("power_kw", None)),
                "source": str(blower.get("_source", "sizing_artifact"))
            }

    # Check for air demand data
    if "air_demand" in artifact:
        air = artifact["air_demand"]
        total_flow = air.get("total_nm3h", air.get("design_airflow", 0))
        if total_flow:
            return {
                "flow_nm3h": total_flow,
                "p1_bar": 1.013,
                "p2_bar": air.get("discharge_pressure", 1.6),
                "blower_eff": 0.70,
                "brake_kw": None,
                "source": "air_demand"
            }

    return None


def extract_mixer_duty_points(artifact: dict, equipment_tag: str) -> Optional[dict]:
    """
    Extract mixer duty point from sizing artifact.

    Looks for tank volume, power density data.

    Returns:
        Dict with volume_m3, w_per_m3, brake_kw or None
    """
    # Try mixer-specific structures
    mixers = artifact.get("mixers", artifact.get("agitators", []))
    if isinstance(mixers, dict):
        mixers = [mixers]

    for mixer in mixers:
        tag = mixer.get("tag", mixer.get("equipment_tag", ""))
        if tag and (equipment_tag in tag or tag in equipment_tag):
            return {
                "volume_m3": mixer.get("volume_m3", mixer.get("tank_volume", 0)),
                "w_per_m3": mixer.get("power_density", mixer.get("w_per_m3", 8)),
                "brake_kw": mixer.get("brake_kw", mixer.get("power_kw", None)),
                "source": str(mixer.get("_source", "sizing_artifact"))
            }

    # Check tanks for mixing requirements
    tanks = artifact.get("tanks", [])
    for tank in tanks:
        if "mixer" in tank.get("tag", "").lower() or equipment_tag in tank.get("tag", ""):
            return {
                "volume_m3": tank.get("volume_m3", 0),
                "w_per_m3": tank.get("mixing_intensity", 8),
                "brake_kw": None,
                "source": "tank_data"
            }

    return None


def extract_duty_point(
    equipment_tag: str,
    equipment_type: str,
    sizing_artifacts: list[Path],
    fallback_data: Optional[dict] = None
) -> dict:
    """
    Extract duty point for equipment from available sources.

    Args:
        equipment_tag: Equipment tag (e.g., "200-B-01")
        equipment_type: Equipment type code (P, B, AG, etc.)
        sizing_artifacts: List of paths to sizing artifacts
        fallback_data: Optional fallback data (e.g., from equipment list)

    Returns:
        Dict with duty point data including source field
    """
    result = {
        "equipment_tag": equipment_tag,
        "equipment_type": equipment_type,
        "duty_point_found": False,
        "source": None
    }

    # Determine extraction function based on equipment type
    type_upper = equipment_type.upper()
    if type_upper in ["P", "PU"]:
        extractor = extract_pump_duty_points
    elif type_upper in ["B", "BL"]:
        extractor = extract_blower_duty_points
    elif type_upper in ["AG", "MX"]:
        extractor = extract_mixer_duty_points
    else:
        extractor = None

    # Search artifacts
    if extractor:
        for artifact_path in sizing_artifacts:
            try:
                artifact = load_artifact(artifact_path)
                duty_point = extractor(artifact, equipment_tag)
                if duty_point and any(v for k, v in duty_point.items() if k != "source" and v):
                    result.update(duty_point)
                    result["duty_point_found"] = True
                    result["source"] = str(artifact_path)
                    return result
            except Exception as e:
                continue

    # Use fallback data if provided
    if fallback_data:
        fallback_source = fallback_data.pop("_source", "equipment_list")
        result.update(fallback_data)
        result["duty_point_found"] = bool(fallback_data)
        result["source"] = fallback_source

    return result


def parse_capacity_string(capacity_str: str) -> dict:
    """Parse a free-text capacity string into structured fields.

    Serves as a defensive fallback when capacity_value/capacity_unit are not present.

    Patterns:
      - "{flow} m3/hr @ {head} m w.c." -> flow_m3h + head_m
      - "{flow} m3/hr @ {pressure} bar g" -> flow_m3h + pressure_bar_g
      - "{flow} m3/hr" -> flow_m3h
      - "{flow} Nm3/hr" -> flow_nm3h
      - "{volume} m3" -> volume_m3
      - "{flow} m3/day" -> flow_m3h (converted)

    Returns:
        Dict with parsed fields (may be empty if no match)
    """
    if not capacity_str:
        return {}

    text = str(capacity_str).strip()
    result = {}

    # flow @ head in m w.c.
    m = re.search(r"([\d.]+)\s*m3/hr?\s*@\s*([\d.]+)\s*m\s*w\.?c\.?", text, re.I)
    if m:
        result["flow_m3h"] = float(m.group(1))
        result["head_m"] = float(m.group(2))
        return result

    # flow @ pressure in bar
    m = re.search(r"([\d.]+)\s*m3/hr?\s*@\s*([\d.]+)\s*bar\s*g?", text, re.I)
    if m:
        result["flow_m3h"] = float(m.group(1))
        result["p1_bar"] = 1.013
        result["p2_bar"] = 1.013 + float(m.group(2))
        return result

    # flow in Nm3/hr
    m = re.search(r"([\d.]+)\s*[Nn]m3/hr?", text)
    if m:
        result["flow_nm3h"] = float(m.group(1))
        return result

    # flow in m3/day
    m = re.search(r"([\d.]+)\s*m3/[Dd]ay?", text, re.I)
    if m:
        result["flow_m3h"] = float(m.group(1)) / 24
        return result

    # flow in m3/hr (plain)
    m = re.search(r"([\d.]+)\s*m3/hr?", text, re.I)
    if m:
        result["flow_m3h"] = float(m.group(1))
        return result

    # volume in m3
    m = re.search(r"([\d.]+)\s*m3(?!\s*/)", text, re.I)
    if m:
        result["volume_m3"] = float(m.group(1))
        return result

    return result


def extract_all_duty_points(
    equipment_list: list[dict],
    project_dir: Path
) -> dict[str, dict]:
    """
    Extract duty points for all equipment in list.

    Args:
        equipment_list: List of equipment dicts with tag, type, capacity
        project_dir: Project directory to search for sizing artifacts

    Returns:
        Dict mapping equipment_tag to duty point data
    """
    artifacts = find_sizing_artifacts(project_dir)
    results = {}

    for eq in equipment_list:
        tag = eq.get("tag", eq.get("equipment_tag"))
        eq_type = eq.get("equipment_type", "")

        # Extract type code from tag if not provided
        if not eq_type and tag:
            # Pattern: NNN-XXX-NN or XNNN-XXX-NN where XXX is the type
            match = re.match(r"[A-Z]?\d{3,4}-([A-Z]{1,5})-\d+", tag)
            if match:
                eq_type = match.group(1)

        # Prepare fallback data from equipment list
        fallback = {}

        # Try structured capacity fields first
        if eq.get("capacity_value") and eq.get("capacity_unit"):
            unit = str(eq["capacity_unit"]).lower()
            value = float(eq["capacity_value"])

            if "m3/h" in unit or "m³/h" in unit:
                fallback["flow_m3h"] = value
            elif "m3/d" in unit or "m³/d" in unit:
                fallback["flow_m3h"] = value / 24
            elif "nm3/h" in unit or "nm³/h" in unit:
                fallback["flow_nm3h"] = value
            elif "m3" in unit or "m³" in unit:
                fallback["volume_m3"] = value
            fallback["_source"] = "capacity_structured"
        else:
            # Fallback: parse free-text capacity string
            cap_str = eq.get("capacity", "")
            if cap_str:
                parsed = parse_capacity_string(cap_str)
                if parsed:
                    fallback.update(parsed)
                    fallback["_source"] = "capacity_parsed"

        # If still no capacity data, try parsing from description field
        # (P&ID callout text often embedded in description, e.g.
        #  "Biogas Recirculation Blower (FRP fan type, 500 m3/h, 37 kW)")
        has_flow = "flow_m3h" in fallback or "flow_nm3h" in fallback or "volume_m3" in fallback
        if not has_flow:
            desc = eq.get("description", "")
            if desc:
                parsed = parse_capacity_string(str(desc))
                if parsed:
                    fallback.update(parsed)
                    fallback["_source"] = "description_parsed"

        # Read head_m and pressure_bar_g directly from equipment entry
        if eq.get("head_m"):
            fallback["head_m"] = float(eq["head_m"])
        if eq.get("pressure_bar_g"):
            fallback["p1_bar"] = 1.013
            fallback["p2_bar"] = 1.013 + float(eq["pressure_bar_g"])

        # For blowers, treat m3/h as Nm3/h (P&ID convention)
        if eq_type.upper() in ("B", "BL") and "flow_m3h" in fallback and "flow_nm3h" not in fallback:
            fallback["flow_nm3h"] = fallback.pop("flow_m3h")

        if eq.get("power_kw") or eq.get("power_kW"):
            fallback["installed_kw"] = eq.get("power_kw") or eq.get("power_kW")

        duty_point = extract_duty_point(tag, eq_type, artifacts, fallback)
        results[tag] = duty_point

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: extract_duty_points.py <project_dir>")
        print("\nSearches for sizing artifacts and extracts duty points.")
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    if not project_dir.exists():
        print(f"Error: Directory not found: {project_dir}")
        sys.exit(1)

    # Find artifacts
    artifacts = find_sizing_artifacts(project_dir)
    print(f"Found {len(artifacts)} sizing artifacts:")
    for a in artifacts:
        print(f"  - {a}")

    # Example extraction
    if artifacts:
        artifact = load_artifact(artifacts[0])
        print(f"\nFirst artifact keys: {list(artifact.keys())}")
