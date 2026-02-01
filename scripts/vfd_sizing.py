#!/usr/bin/env python3
"""
VFD/ASD Sizing Module
NEC 430.122 and 430.130 Variable Frequency Drive sizing calculations.

Implements VFD-specific sizing per:
- NEC 430.122: Single motor VFD supply conductor sizing
- NEC 430.130: Branch circuit SCPD for VFD applications
- VFD manufacturer catalog integration

Key Differences from DOL Motors:
- Conductor sized to VFD INPUT current (not motor FLC)
- SCPD sized per 430.52 using motor FLC (unless VFD marked otherwise)
- Overload protection typically integral to VFD
- Harmonic considerations for conductor sizing

Author: Load List Skill
Standards: NEC 2023 Article 430 Part X
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

# VFD catalog cache
_VFD_CATALOG: Optional[dict] = None


def load_vfd_catalog() -> dict:
    """Load VFD manufacturer catalog."""
    global _VFD_CATALOG
    if _VFD_CATALOG is None:
        catalogs_dir = Path(__file__).parent.parent / "catalogs"
        path = catalogs_dir / "vfd_catalog.yaml"
        if path.exists():
            with open(path) as f:
                _VFD_CATALOG = yaml.safe_load(f)
        else:
            _VFD_CATALOG = {}
    return _VFD_CATALOG


def calc_vfd_supply_conductor_ampacity(
    vfd_input_current: float,
    harmonic_derating: float = 1.0
) -> dict:
    """
    Calculate VFD supply conductor ampacity per NEC 430.122(A).

    NEC 430.122(A): Conductors supplying power conversion equipment
    included as part of an adjustable-speed drive system shall have
    an ampacity not less than 125% of the rated input current.

    Args:
        vfd_input_current: VFD rated input current (from VFD nameplate/catalog)
        harmonic_derating: Additional derating for harmonics (typically 1.0-1.2)

    Returns:
        dict with conductor sizing requirements
    """
    # Base calculation per 430.122(A)
    base_ampacity = 1.25 * vfd_input_current

    # Apply harmonic derating if specified
    min_ampacity = base_ampacity * harmonic_derating

    return {
        "min_ampacity_a": round(min_ampacity, 1),
        "vfd_input_current_a": vfd_input_current,
        "multiplier": 1.25,
        "harmonic_derating": harmonic_derating,
        "code_reference": "NEC 430.122(A)",
        "notes": (
            f"VFD supply conductor ≥ 125% × VFD input current.\n"
            f"125% × {vfd_input_current}A = {base_ampacity:.1f}A"
            + (f"\nWith harmonic derating {harmonic_derating}: {min_ampacity:.1f}A"
               if harmonic_derating != 1.0 else "")
        )
    }


def calc_vfd_branch_scpd(
    motor_flc: float,
    vfd_input_current: float,
    vfd_max_scpd: Optional[float] = None,
    device_type: Literal["dual_element_fuse", "inverse_time_cb"] = "dual_element_fuse"
) -> dict:
    """
    Calculate VFD branch circuit SCPD per NEC 430.130.

    NEC 430.130(A): Branch circuit SCPD shall be determined as follows:
    1. Per 430.52 using motor FLC, unless...
    2. VFD is marked with maximum branch circuit SCPD rating

    Args:
        motor_flc: Motor Full Load Current from NEC tables
        vfd_input_current: VFD rated input current
        vfd_max_scpd: VFD manufacturer maximum SCPD (from marking)
        device_type: Type of SCPD (fuse or breaker)

    Returns:
        dict with SCPD sizing
    """
    # Calculate per 430.52 using motor FLC
    if device_type == "dual_element_fuse":
        max_pct = 175
    else:  # inverse_time_cb
        max_pct = 250

    calculated_per_430_52 = motor_flc * (max_pct / 100)

    # Apply next-size-up rule
    max_per_nec = next((s for s in STANDARD_OCPD_SIZES if s >= calculated_per_430_52), calculated_per_430_52)

    # VFD marking takes precedence if lower
    if vfd_max_scpd:
        max_rating = min(max_per_nec, vfd_max_scpd)
        limited_by = "vfd_marking" if vfd_max_scpd < max_per_nec else "nec_430_52"
    else:
        max_rating = max_per_nec
        limited_by = "nec_430_52"

    # Select appropriate size (must carry VFD input current)
    selected = next((s for s in STANDARD_OCPD_SIZES if s >= vfd_input_current and s <= max_rating), max_rating)

    return {
        "selected_rating_a": int(selected),
        "max_per_nec_a": int(max_per_nec),
        "max_per_vfd_a": vfd_max_scpd,
        "max_effective_a": int(max_rating),
        "limited_by": limited_by,
        "motor_flc_a": motor_flc,
        "vfd_input_current_a": vfd_input_current,
        "device_type": device_type,
        "code_reference": "NEC 430.130, 430.52",
        "sizing_basis": (
            f"NEC 430.130: {max_pct}% × {motor_flc}A FLC = {calculated_per_430_52:.1f}A, "
            f"next size {max_per_nec}A" +
            (f", limited by VFD marking to {vfd_max_scpd}A" if vfd_max_scpd and vfd_max_scpd < max_per_nec else "")
        )
    }


def lookup_vfd_catalog(
    manufacturer: str,
    series: str,
    motor_kw: float,
    voltage_class: str = "400V",
    duty: str = "ND"
) -> Optional[dict]:
    """
    Look up VFD specifications from catalog.

    Args:
        manufacturer: VFD manufacturer (e.g., 'abb', 'siemens', 'rockwell')
        series: VFD series (e.g., 'acs580', 'g120', 'powerflex_755')
        motor_kw: Motor power in kW
        voltage_class: Voltage class (e.g., '400V', '480V')
        duty: Normal Duty (ND) or Heavy Duty (HD)

    Returns:
        VFD specifications dict or None if not found
    """
    catalog = load_vfd_catalog()

    # Construct catalog key
    key = f"{manufacturer.lower()}_{series.lower()}"
    if key not in catalog:
        return None

    vfd_data = catalog[key]
    frames_key = f"frames_{voltage_class.lower()}_{duty.lower()}"

    if frames_key not in vfd_data:
        # Try without duty suffix
        frames_key = f"frames_{voltage_class.lower()}"
        if frames_key not in vfd_data:
            return None

    frames_section = vfd_data[frames_key]

    # Get frames dict - handle both old list format and new dict format
    if isinstance(frames_section, dict):
        frames = frames_section.get('frames', frames_section)
    else:
        frames = frames_section

    # Find appropriate frame for motor kW
    if isinstance(frames, dict):
        # New dict format: frames keyed by frame name
        for frame_name, frame_data in frames.items():
            kw_range = frame_data.get('kw_range', [0, 0])
            if kw_range[0] <= motor_kw <= kw_range[1]:
                return {
                    "manufacturer": manufacturer,
                    "series": series,
                    "frame": frame_name,
                    "voltage_class": voltage_class,
                    "duty": duty,
                    "kw_range": kw_range,
                    "rated_input_current_a": frame_data.get('rated_input_current'),
                    "rated_output_current_a": frame_data.get('rated_output_current'),
                    "max_branch_scpd_a": frame_data.get('max_branch_scpd_a'),
                    "recommended_fuse": frame_data.get('recommended_fuse'),
                    "losses_kw": frame_data.get('losses_kw'),
                    "sccr_ka": frame_data.get('sccr_ka'),
                    "source": "catalog"
                }
    else:
        # Old list format
        for frame in frames:
            kw_range = frame.get('kw_range', [0, 0])
            if kw_range[0] <= motor_kw <= kw_range[1]:
                return {
                    "manufacturer": manufacturer,
                    "series": series,
                    "frame": frame.get('frame'),
                    "voltage_class": voltage_class,
                    "duty": duty,
                    "kw_range": kw_range,
                    "rated_input_current_a": frame.get('rated_input_current'),
                    "rated_output_current_a": frame.get('rated_output_current'),
                    "max_branch_scpd_a": frame.get('max_branch_scpd_a'),
                    "recommended_fuse": frame.get('recommended_fuse'),
                    "losses_kw": frame.get('losses_kw'),
                    "sccr_ka": frame.get('sccr_ka'),
                    "source": "catalog"
                }

    return None


def estimate_vfd_input_current(
    motor_flc: float,
    voltage: float = 400,
    multiplier: float = 1.1
) -> dict:
    """
    Estimate VFD input current when catalog data not available.

    VFD input current is typically 1.05-1.15× motor FLC due to:
    - VFD internal losses (2-5%)
    - Power factor correction (VFD input PF ≈ 0.95-0.98)
    - Harmonic currents

    Args:
        motor_flc: Motor Full Load Current from NEC tables
        voltage: System voltage
        multiplier: Input current multiplier (default 1.1)

    Returns:
        dict with estimated VFD input current
    """
    estimated_input = motor_flc * multiplier

    return {
        "estimated_input_current_a": round(estimated_input, 1),
        "motor_flc_a": motor_flc,
        "multiplier": multiplier,
        "source": "estimate",
        "notes": (
            f"Estimated VFD input = {multiplier}× motor FLC.\n"
            "Verify with actual VFD selection from manufacturer catalog."
        ),
        "warning": "ESTIMATE ONLY - Use actual VFD catalog data when available"
    }


def size_vfd_circuit(
    motor_kw: float,
    motor_flc: float,
    voltage: float = 400,
    manufacturer: Optional[str] = None,
    series: Optional[str] = None,
    vfd_input_current: Optional[float] = None,
    vfd_max_scpd: Optional[float] = None,
    device_type: str = "dual_element_fuse",
    harmonic_derating: float = 1.0
) -> dict:
    """
    Complete VFD circuit sizing per NEC Part X.

    Order of preference for VFD data:
    1. User-provided vfd_input_current and vfd_max_scpd
    2. Catalog lookup by manufacturer/series
    3. Estimation from motor FLC

    Args:
        motor_kw: Motor power in kW
        motor_flc: Motor FLC from NEC tables
        voltage: System voltage
        manufacturer: VFD manufacturer for catalog lookup
        series: VFD series for catalog lookup
        vfd_input_current: Override VFD input current
        vfd_max_scpd: Override VFD max SCPD
        device_type: SCPD type
        harmonic_derating: Conductor harmonic derating factor

    Returns:
        dict with complete VFD circuit sizing
    """
    # Determine VFD specifications
    vfd_data = None
    data_source = "user_provided"

    if vfd_input_current is None:
        # Try catalog lookup
        if manufacturer and series:
            vfd_data = lookup_vfd_catalog(
                manufacturer, series, motor_kw,
                f"{int(voltage)}V"
            )
            if vfd_data:
                vfd_input_current = vfd_data['rated_input_current_a']
                vfd_max_scpd = vfd_data.get('max_branch_scpd_a') or vfd_max_scpd
                data_source = "catalog"

        # Fall back to estimation
        if vfd_input_current is None:
            estimate = estimate_vfd_input_current(motor_flc, voltage)
            vfd_input_current = estimate['estimated_input_current_a']
            data_source = "estimate"

    # Calculate conductor sizing
    conductor = calc_vfd_supply_conductor_ampacity(vfd_input_current, harmonic_derating)

    # Calculate SCPD sizing
    scpd = calc_vfd_branch_scpd(motor_flc, vfd_input_current, vfd_max_scpd, device_type)

    # Determine if VFD provides overload protection
    vfd_overload_integral = True  # Most modern VFDs do

    result = {
        "motor_kw": motor_kw,
        "motor_flc_a": motor_flc,
        "voltage_v": voltage,

        # VFD data
        "vfd_input_current_a": vfd_input_current,
        "vfd_max_scpd_a": vfd_max_scpd,
        "vfd_data_source": data_source,
        "vfd_overload_integral": vfd_overload_integral,

        # Conductor sizing (NEC 430.122)
        "conductor_min_ampacity_a": conductor['min_ampacity_a'],

        # SCPD sizing (NEC 430.130/430.52)
        "branch_scpd_rating_a": scpd['selected_rating_a'],
        "branch_scpd_max_a": scpd['max_effective_a'],
        "branch_scpd_limited_by": scpd['limited_by'],
        "branch_scpd_type": device_type,

        # Overload (integral to VFD)
        "overload_type": "VFD_INTEGRAL",
        "overload_setting_a": motor_flc,  # Program VFD to motor nameplate

        # Sizing basis
        "conductor_sizing": conductor,
        "scpd_sizing": scpd,

        "code_references": ["NEC 430.122", "NEC 430.130", "NEC 430.52"]
    }

    # Add VFD catalog data if available
    if vfd_data:
        result["vfd_catalog_data"] = vfd_data

    # Add warnings for estimates
    if data_source == "estimate":
        result["warning"] = (
            "VFD input current is ESTIMATED. "
            "Verify with actual VFD selection from manufacturer catalog."
        )

    return result


def get_vfd_sccr_with_fuse(
    vfd_base_sccr_ka: float,
    fuse_class: str,
    fuse_rating_a: float
) -> dict:
    """
    Determine VFD assembly SCCR with current-limiting fuse.

    Many VFDs achieve higher SCCR ratings when protected by
    specific current-limiting fuses (typically Class J or RK1).

    Args:
        vfd_base_sccr_ka: VFD standalone SCCR
        fuse_class: Fuse class (J, RK1, etc.)
        fuse_rating_a: Fuse rating in Amps

    Returns:
        dict with enhanced SCCR rating
    """
    # Typical SCCR enhancement with Class J fuses
    # (Actual values are manufacturer-specific, these are representative)
    fuse_sccr_enhancement = {
        "J": 100,  # Class J can provide up to 200kA
        "RK1": 65,
        "RK5": 50,
        "CC": 50,
        "T": 200
    }

    enhanced_sccr = fuse_sccr_enhancement.get(fuse_class.upper(), vfd_base_sccr_ka)
    assembly_sccr = max(vfd_base_sccr_ka, enhanced_sccr)

    return {
        "vfd_base_sccr_ka": vfd_base_sccr_ka,
        "fuse_class": fuse_class,
        "fuse_rating_a": fuse_rating_a,
        "fuse_sccr_contribution_ka": enhanced_sccr,
        "assembly_sccr_ka": assembly_sccr,
        "notes": (
            f"VFD assembly SCCR with Class {fuse_class} fuse: {assembly_sccr} kA.\n"
            "Verify specific combination rating with VFD manufacturer."
        ),
        "warning": "Combination SCCR ratings are manufacturer-specific. Verify with VFD datasheet."
    }


if __name__ == "__main__":
    print("Testing vfd_sizing module...")
    print("=" * 60)

    # Test VFD supply conductor sizing
    print("\n1. VFD Supply Conductor Sizing (NEC 430.122)")
    cond = calc_vfd_supply_conductor_ampacity(207)  # 110 kW VFD
    print(f"   VFD input current: 207A")
    print(f"   Min conductor ampacity: {cond['min_ampacity_a']}A")
    print(f"   Reference: {cond['code_reference']}")

    # Test with harmonic derating
    print("\n2. With Harmonic Derating")
    cond_h = calc_vfd_supply_conductor_ampacity(207, harmonic_derating=1.15)
    print(f"   With 1.15 derating: {cond_h['min_ampacity_a']}A")

    # Test VFD SCPD sizing
    print("\n3. VFD Branch SCPD (NEC 430.130)")
    scpd = calc_vfd_branch_scpd(
        motor_flc=195,
        vfd_input_current=207,
        vfd_max_scpd=300,
        device_type="dual_element_fuse"
    )
    print(f"   Motor FLC: 195A, VFD input: 207A")
    print(f"   Max per NEC: {scpd['max_per_nec_a']}A")
    print(f"   Max per VFD: {scpd['max_per_vfd_a']}A")
    print(f"   Selected: {scpd['selected_rating_a']}A")
    print(f"   Limited by: {scpd['limited_by']}")

    # Test complete VFD circuit sizing
    print("\n4. Complete VFD Circuit Sizing")
    vfd = size_vfd_circuit(
        motor_kw=110,
        motor_flc=195,
        voltage=400,
        vfd_input_current=207,
        vfd_max_scpd=300,
        device_type="dual_element_fuse"
    )
    print(f"   Conductor min: {vfd['conductor_min_ampacity_a']}A")
    print(f"   SCPD rating: {vfd['branch_scpd_rating_a']}A")
    print(f"   Overload: {vfd['overload_type']}")

    # Test estimation fallback
    print("\n5. VFD Input Current Estimation")
    est = estimate_vfd_input_current(195, 400)
    print(f"   Motor FLC: 195A")
    print(f"   Estimated VFD input: {est['estimated_input_current_a']}A")
    print(f"   Warning: {est['warning']}")

    # Test SCCR with fuse
    print("\n6. VFD SCCR with Class J Fuse")
    sccr = get_vfd_sccr_with_fuse(
        vfd_base_sccr_ka=22,
        fuse_class="J",
        fuse_rating_a=250
    )
    print(f"   VFD base SCCR: {sccr['vfd_base_sccr_ka']} kA")
    print(f"   With Class J fuse: {sccr['assembly_sccr_ka']} kA")

    print("\n" + "=" * 60)
    print("All tests completed!")
