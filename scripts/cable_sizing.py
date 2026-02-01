#!/usr/bin/env python3
"""
Cable Sizing Module
Cable ampacity selection per NEC 310 and IEC 60364-5-52.

Implements cable sizing for motor circuits including:
- Ampacity lookup from code tables
- Ambient temperature derating
- Conduit fill/grouping derating
- Size selection based on required ampacity

Author: Load List Skill
Standards: NEC 2023 Article 310, IEC 60364-5-52
"""

import math
from pathlib import Path
from typing import Optional, Literal

import yaml


def load_cable_catalog() -> dict:
    """Load cable ampacity catalog."""
    catalogs_dir = Path(__file__).parent.parent / "catalogs"
    path = catalogs_dir / "cable_ampacity.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f)


# Cache for catalog
_CABLE_CATALOG: Optional[dict] = None


def get_cable_catalog() -> dict:
    """Get cached cable catalog."""
    global _CABLE_CATALOG
    if _CABLE_CATALOG is None:
        _CABLE_CATALOG = load_cable_catalog()
    return _CABLE_CATALOG


def select_cable_nec(
    required_ampacity: float,
    conductor_temp_rating: int = 75,
    ambient_temp_c: float = 30,
    conductors_in_raceway: int = 3
) -> dict:
    """
    Select cable size per NEC 310.16.

    Args:
        required_ampacity: Required conductor ampacity (A)
        conductor_temp_rating: Conductor temperature rating (75 or 90°C)
        ambient_temp_c: Ambient temperature (°C)
        conductors_in_raceway: Number of current-carrying conductors

    Returns:
        dict with selected cable size and ampacity
    """
    catalog = get_cable_catalog()
    nec = catalog.get("nec_310", {})

    # Select ampacity table
    if conductor_temp_rating == 90:
        table = nec.get("table_310_16_90c_copper", {}).get("ampacities", {})
    else:
        table = nec.get("table_310_16_75c_copper", {}).get("ampacities", {})

    # Get correction factors
    ambient_correction = get_ambient_correction_nec(ambient_temp_c, conductor_temp_rating)
    fill_correction = get_conduit_fill_correction_nec(conductors_in_raceway)

    total_derating = ambient_correction * fill_correction

    # Required ampacity before derating
    ampacity_required = required_ampacity / total_derating if total_derating > 0 else required_ampacity

    # Find smallest cable that meets requirement
    selected_size = None
    selected_ampacity = 0

    # Parse sizes in order (AWG then kcmil)
    awg_order = ["14 AWG", "12 AWG", "10 AWG", "8 AWG", "6 AWG", "4 AWG", "3 AWG",
                 "2 AWG", "1 AWG", "1/0 AWG", "2/0 AWG", "3/0 AWG", "4/0 AWG",
                 "250 kcmil", "300 kcmil", "350 kcmil", "400 kcmil", "500 kcmil",
                 "600 kcmil", "700 kcmil", "750 kcmil", "800 kcmil", "900 kcmil", "1000 kcmil"]

    for size in awg_order:
        if size in table:
            ampacity = table[size]
            if ampacity >= ampacity_required:
                selected_size = size
                selected_ampacity = ampacity
                break

    if selected_size is None:
        selected_size = "Exceeds table"
        selected_ampacity = 0

    # Calculate derated ampacity
    derated_ampacity = selected_ampacity * total_derating

    return {
        "selected_size": selected_size,
        "table_ampacity_a": selected_ampacity,
        "derated_ampacity_a": round(derated_ampacity, 1),
        "required_ampacity_a": required_ampacity,
        "ambient_temp_c": ambient_temp_c,
        "ambient_correction": round(ambient_correction, 2),
        "conductors_in_raceway": conductors_in_raceway,
        "fill_correction": round(fill_correction, 2),
        "total_derating": round(total_derating, 2),
        "conductor_temp_rating_c": conductor_temp_rating,
        "standard": "NEC",
        "table_reference": f"NEC 310.15(B)(16), {conductor_temp_rating}°C copper"
    }


def select_cable_iec(
    required_ampacity: float,
    insulation_type: str = "XLPE",
    installation_method: str = "B",
    ambient_temp_c: float = 30,
    grouped_circuits: int = 1
) -> dict:
    """
    Select cable size per IEC 60364-5-52.

    Args:
        required_ampacity: Required current-carrying capacity Ib (A)
        insulation_type: PVC or XLPE
        installation_method: A, B, C, D, E, F, G per IEC
        ambient_temp_c: Ambient temperature (°C)
        grouped_circuits: Number of grouped circuits

    Returns:
        dict with selected cable size and ampacity
    """
    catalog = get_cable_catalog()
    iec = catalog.get("iec_60364", {})

    # Select ampacity table
    if insulation_type.upper() == "XLPE":
        if installation_method.upper() in ["E", "F"]:
            table = iec.get("table_b_52_3_tray", {}).get("ampacities_3phase", {})
            table_ref = "IEC 60364 Table B.52.3"
            temp_rating = 90
        else:
            table = iec.get("table_b_52_5_xlpe_conduit", {}).get("ampacities_3phase", {})
            table_ref = "IEC 60364 Table B.52.5"
            temp_rating = 90
    else:  # PVC
        table = iec.get("table_b_52_4_pvc_conduit", {}).get("ampacities_3phase", {})
        table_ref = "IEC 60364 Table B.52.4"
        temp_rating = 70

    # Get correction factors
    ambient_correction = get_ambient_correction_iec(ambient_temp_c, temp_rating)
    grouping_correction = get_grouping_correction_iec(grouped_circuits)

    total_derating = ambient_correction * grouping_correction

    # Required ampacity before derating
    ampacity_required = required_ampacity / total_derating if total_derating > 0 else required_ampacity

    # Find smallest cable that meets requirement
    selected_size = None
    selected_ampacity = 0

    # Parse sizes in order
    mm2_order = ["1.5 mm²", "2.5 mm²", "4 mm²", "6 mm²", "10 mm²", "16 mm²",
                 "25 mm²", "35 mm²", "50 mm²", "70 mm²", "95 mm²", "120 mm²",
                 "150 mm²", "185 mm²", "240 mm²", "300 mm²"]

    for size in mm2_order:
        if size in table:
            ampacity = table[size]
            if ampacity >= ampacity_required:
                selected_size = size
                selected_ampacity = ampacity
                break

    if selected_size is None:
        selected_size = "Exceeds table"
        selected_ampacity = 0

    # Calculate derated ampacity (Iz)
    derated_ampacity = selected_ampacity * total_derating

    return {
        "selected_size": selected_size,
        "table_ampacity_a": selected_ampacity,
        "derated_ampacity_a": round(derated_ampacity, 1),
        "required_ampacity_a": required_ampacity,
        "insulation_type": insulation_type,
        "installation_method": installation_method,
        "ambient_temp_c": ambient_temp_c,
        "ambient_correction": round(ambient_correction, 2),
        "grouped_circuits": grouped_circuits,
        "grouping_correction": round(grouping_correction, 2),
        "total_derating": round(total_derating, 2),
        "conductor_temp_rating_c": temp_rating,
        "standard": "IEC",
        "table_reference": table_ref
    }


def get_ambient_correction_nec(
    ambient_temp_c: float,
    conductor_temp_rating: int = 75
) -> float:
    """Get ambient temperature correction factor per NEC."""
    catalog = get_cable_catalog()
    factors = catalog.get("nec_310", {}).get("ambient_correction", {})

    key = f"factors_{conductor_temp_rating}c"
    factor_table = factors.get(key, {})

    # Find appropriate range
    for range_str, factor in factor_table.items():
        if "-" in str(range_str):
            low, high = map(int, str(range_str).split("-"))
            if low <= ambient_temp_c <= high:
                return factor

    # Default to 1.0 if not found
    return 1.0


def get_conduit_fill_correction_nec(conductors: int) -> float:
    """Get conduit fill adjustment factor per NEC 310.15(C)(1)."""
    catalog = get_cable_catalog()
    factors = catalog.get("nec_310", {}).get("conduit_fill_adjustment", {}).get("factors", {})

    for range_str, factor in factors.items():
        if "-" in str(range_str):
            parts = str(range_str).split("-")
            low = int(parts[0])
            high = int(parts[1]) if parts[1].isdigit() else 1000
            if low <= conductors <= high:
                return factor
        elif "+" in str(range_str):
            threshold = int(str(range_str).replace("+", ""))
            if conductors >= threshold:
                return factor

    return 1.0


def get_ambient_correction_iec(
    ambient_temp_c: float,
    conductor_temp_rating: int = 70
) -> float:
    """Get ambient temperature correction factor per IEC."""
    catalog = get_cable_catalog()
    factors = catalog.get("iec_60364", {}).get("ambient_correction", {})

    key = f"factors_{conductor_temp_rating}c"
    factor_table = factors.get(key, {})

    # Find closest temperature
    temps = sorted([int(t) for t in factor_table.keys()])

    for temp in temps:
        if temp >= ambient_temp_c:
            return factor_table.get(temp, factor_table.get(str(temp), 1.0))

    # Return factor for highest temperature if exceeded
    if temps:
        return factor_table.get(temps[-1], factor_table.get(str(temps[-1]), 1.0))

    return 1.0


def get_grouping_correction_iec(circuits: int) -> float:
    """Get grouping correction factor per IEC."""
    catalog = get_cable_catalog()
    factors = catalog.get("iec_60364", {}).get("grouping_correction", {}).get("single_layer_touching", {})

    if circuits <= 1:
        return 1.0

    if circuits in factors:
        return factors[circuits]

    # For more than 6, use 0.57 × (6/n)^0.5
    if circuits > 6:
        return round(0.57 * math.sqrt(6 / circuits), 2)

    return 0.5  # Conservative default


def select_motor_branch_cable(
    motor_flc: float,
    cable_standard: str = "NEC",
    ambient_temp_c: float = 30,
    **kwargs
) -> dict:
    """
    Select cable for motor branch circuit per NEC 430.22 or IEC equivalent.

    Args:
        motor_flc: Motor Full Load Current from tables
        cable_standard: NEC or IEC
        ambient_temp_c: Ambient temperature
        **kwargs: Additional parameters for cable selection

    Returns:
        dict with cable selection
    """
    # Per NEC 430.22: Branch circuit conductors ≥ 125% of motor FLC
    required_ampacity = 1.25 * motor_flc

    if cable_standard.upper() == "NEC":
        result = select_cable_nec(
            required_ampacity,
            conductor_temp_rating=kwargs.get("conductor_temp_rating", 75),
            ambient_temp_c=ambient_temp_c,
            conductors_in_raceway=kwargs.get("conductors_in_raceway", 3)
        )
    else:
        result = select_cable_iec(
            required_ampacity,
            insulation_type=kwargs.get("insulation_type", "XLPE"),
            installation_method=kwargs.get("installation_method", "B"),
            ambient_temp_c=ambient_temp_c,
            grouped_circuits=kwargs.get("grouped_circuits", 1)
        )

    result["application"] = "motor_branch_circuit"
    result["motor_flc_a"] = motor_flc
    result["sizing_basis"] = f"125% × {motor_flc}A FLC = {required_ampacity}A (NEC 430.22)"

    return result


def select_vfd_supply_cable(
    vfd_input_current: float,
    cable_standard: str = "NEC",
    ambient_temp_c: float = 30,
    harmonic_derating: float = 1.0,
    **kwargs
) -> dict:
    """
    Select cable for VFD supply per NEC 430.122.

    Args:
        vfd_input_current: VFD rated input current
        cable_standard: NEC or IEC
        ambient_temp_c: Ambient temperature
        harmonic_derating: Additional derating for harmonics
        **kwargs: Additional parameters

    Returns:
        dict with cable selection
    """
    # Per NEC 430.122: Supply conductors ≥ 125% of VFD input current
    required_ampacity = 1.25 * vfd_input_current * harmonic_derating

    if cable_standard.upper() == "NEC":
        result = select_cable_nec(
            required_ampacity,
            conductor_temp_rating=kwargs.get("conductor_temp_rating", 75),
            ambient_temp_c=ambient_temp_c,
            conductors_in_raceway=kwargs.get("conductors_in_raceway", 3)
        )
    else:
        result = select_cable_iec(
            required_ampacity,
            insulation_type=kwargs.get("insulation_type", "XLPE"),
            installation_method=kwargs.get("installation_method", "B"),
            ambient_temp_c=ambient_temp_c,
            grouped_circuits=kwargs.get("grouped_circuits", 1)
        )

    result["application"] = "vfd_supply"
    result["vfd_input_current_a"] = vfd_input_current
    result["harmonic_derating"] = harmonic_derating
    result["sizing_basis"] = f"125% × {vfd_input_current}A × {harmonic_derating} = {required_ampacity:.1f}A (NEC 430.122)"

    return result


def select_feeder_cable(
    feeder_ampacity: float,
    cable_standard: str = "NEC",
    ambient_temp_c: float = 30,
    **kwargs
) -> dict:
    """
    Select cable for motor feeder per NEC 430.24.

    Args:
        feeder_ampacity: Required feeder ampacity (calculated per 430.24)
        cable_standard: NEC or IEC
        ambient_temp_c: Ambient temperature
        **kwargs: Additional parameters

    Returns:
        dict with cable selection
    """
    if cable_standard.upper() == "NEC":
        result = select_cable_nec(
            feeder_ampacity,
            conductor_temp_rating=kwargs.get("conductor_temp_rating", 75),
            ambient_temp_c=ambient_temp_c,
            conductors_in_raceway=kwargs.get("conductors_in_raceway", 3)
        )
    else:
        result = select_cable_iec(
            feeder_ampacity,
            insulation_type=kwargs.get("insulation_type", "XLPE"),
            installation_method=kwargs.get("installation_method", "B"),
            ambient_temp_c=ambient_temp_c,
            grouped_circuits=kwargs.get("grouped_circuits", 1)
        )

    result["application"] = "motor_feeder"
    result["sizing_basis"] = f"Feeder ampacity {feeder_ampacity}A per NEC 430.24"

    return result


if __name__ == "__main__":
    print("Testing cable_sizing module...")
    print("=" * 60)

    # Test NEC cable selection
    print("\n1. NEC Cable Selection (75°C)")
    result = select_cable_nec(100, conductor_temp_rating=75, ambient_temp_c=40)
    print(f"   Required: 100A @ 40°C")
    print(f"   Selected: {result['selected_size']}")
    print(f"   Table ampacity: {result['table_ampacity_a']}A")
    print(f"   Derated: {result['derated_ampacity_a']}A")
    print(f"   Ambient correction: {result['ambient_correction']}")

    # Test IEC cable selection
    print("\n2. IEC Cable Selection (XLPE)")
    result = select_cable_iec(100, insulation_type="XLPE", installation_method="B", ambient_temp_c=40)
    print(f"   Required: 100A @ 40°C")
    print(f"   Selected: {result['selected_size']}")
    print(f"   Table ampacity: {result['table_ampacity_a']}A")
    print(f"   Derated: {result['derated_ampacity_a']}A")

    # Test motor branch cable
    print("\n3. Motor Branch Cable (NEC 430.22)")
    result = select_motor_branch_cable(65, cable_standard="NEC")
    print(f"   Motor FLC: 65A")
    print(f"   Required: {result['required_ampacity_a']}A (125% × FLC)")
    print(f"   Selected: {result['selected_size']}")
    print(f"   Sizing basis: {result['sizing_basis']}")

    # Test VFD supply cable
    print("\n4. VFD Supply Cable (NEC 430.122)")
    result = select_vfd_supply_cable(207, cable_standard="NEC", harmonic_derating=1.1)
    print(f"   VFD input: 207A with 1.1 harmonic derating")
    print(f"   Required: {result['required_ampacity_a']}A")
    print(f"   Selected: {result['selected_size']}")

    # Test with conduit fill derating
    print("\n5. Cable with Conduit Fill Derating")
    result = select_cable_nec(100, conductors_in_raceway=6)
    print(f"   Required: 100A with 6 conductors")
    print(f"   Fill correction: {result['fill_correction']}")
    print(f"   Selected: {result['selected_size']}")
    print(f"   Table ampacity: {result['table_ampacity_a']}A")

    print("\n" + "=" * 60)
    print("All tests completed!")
