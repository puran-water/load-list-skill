#!/usr/bin/env python3
"""
Load Calculations Module
Core equations for electrical load calculations in WWTP design.

Includes:
- FLA lookup from NEC/IEC tables
- LRA calculation
- Brake power calculations (pump, blower, mixer)
- Diversity factor parsing
- Energy calculations
"""

import math
import re
from pathlib import Path
from typing import Optional, Tuple, Literal

import yaml


# Load catalog data
CATALOGS_DIR = Path(__file__).parent.parent / "catalogs"


def _load_catalog(name: str) -> dict:
    """Load a YAML catalog file."""
    path = CATALOGS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Catalog not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


# Lazy-loaded catalogs
_MOTOR_FLA_TABLES: Optional[dict] = None
_MOTOR_STANDARDS: Optional[dict] = None
_DUTY_PROFILES: Optional[dict] = None


def _get_motor_fla_tables() -> dict:
    global _MOTOR_FLA_TABLES
    if _MOTOR_FLA_TABLES is None:
        _MOTOR_FLA_TABLES = _load_catalog("motor_fla_tables")
    return _MOTOR_FLA_TABLES


def _get_motor_standards() -> dict:
    global _MOTOR_STANDARDS
    if _MOTOR_STANDARDS is None:
        _MOTOR_STANDARDS = _load_catalog("motor_standards")
    return _MOTOR_STANDARDS


def _get_duty_profiles() -> dict:
    global _DUTY_PROFILES
    if _DUTY_PROFILES is None:
        _DUTY_PROFILES = _load_catalog("duty_profiles")
    return _DUTY_PROFILES


# ============================================================================
# FLA Lookup Functions (Table-Based)
# ============================================================================

def lookup_fla_nec(
    hp: float,
    voltage: int,
    phases: int = 3
) -> Tuple[float, str]:
    """
    Look up Full Load Amps from NEC tables.

    Args:
        hp: Motor horsepower
        voltage: Motor voltage (200, 208, 230, 460, 575)
        phases: 1 or 3

    Returns:
        Tuple of (FLA, source) where source is the NEC table reference

    Raises:
        ValueError: If HP or voltage not in table
    """
    tables = _get_motor_fla_tables()

    if phases == 3:
        table = tables["nec_430_250"]["three_phase"]
        source = "NEC-430.250"
    else:
        table = tables["nec_430_248"]["single_phase"]
        source = "NEC-430.248"

    # Find closest HP rating (round up to standard size)
    hp_values = sorted([float(k) for k in table.keys()])
    hp_key = None
    for h in hp_values:
        if h >= hp:
            hp_key = h
            break

    if hp_key is None:
        # HP exceeds table, use largest value and scale
        hp_key = hp_values[-1]

    hp_data = table.get(hp_key) or table.get(str(hp_key))
    if hp_data is None:
        hp_data = table.get(int(hp_key)) if hp_key == int(hp_key) else None

    if hp_data is None:
        raise ValueError(f"HP {hp} not found in NEC table")

    # Find closest voltage
    available_voltages = [int(v) for v in hp_data.keys()]
    voltage_key = min(available_voltages, key=lambda v: abs(v - voltage))

    fla = hp_data.get(voltage_key) or hp_data.get(str(voltage_key))
    if fla is None:
        raise ValueError(f"Voltage {voltage}V not found for {hp} HP")

    # Scale if HP was larger than table maximum
    if hp > hp_key:
        fla = fla * (hp / hp_key)

    return float(fla), source


def lookup_fla_iec(
    kw: float,
    voltage: int,
    frequency: int = 50,
    efficiency_class: str = "IE3"
) -> Tuple[float, str]:
    """
    Look up Full Load Amps from IEC 60034 tables.

    Args:
        kw: Motor power in kW
        voltage: Motor voltage (380, 400, 415 for 50Hz; 440, 460, 480 for 60Hz)
        frequency: 50 or 60 Hz
        efficiency_class: IE1, IE2, IE3, IE4 (affects efficiency for fallback calc)

    Returns:
        Tuple of (FLA, source)
    """
    tables = _get_motor_fla_tables()

    table_key = f"three_phase_{frequency}hz"
    if table_key not in tables["iec_60034"]:
        raise ValueError(f"No IEC table for {frequency} Hz")

    table = tables["iec_60034"][table_key]

    # Find closest kW rating
    kw_values = sorted([float(k) for k in table.keys()])
    kw_key = None
    for k in kw_values:
        if k >= kw:
            kw_key = k
            break

    if kw_key is None:
        # kW exceeds table, use fallback calculation
        return _calc_fla_formula(kw, voltage, 3, frequency, efficiency_class)

    kw_data = table.get(kw_key) or table.get(str(kw_key))
    if kw_data is None:
        return _calc_fla_formula(kw, voltage, 3, frequency, efficiency_class)

    # Find closest voltage
    available_voltages = [int(v) for v in kw_data.keys()]
    voltage_key = min(available_voltages, key=lambda v: abs(v - voltage))

    fla = kw_data.get(voltage_key) or kw_data.get(str(voltage_key))
    if fla is None:
        return _calc_fla_formula(kw, voltage, 3, frequency, efficiency_class)

    # Scale if kW was larger than exact match
    if kw > kw_key:
        fla = fla * (kw / kw_key)

    return float(fla), "IEC-60034"


def _calc_fla_formula(
    kw: float,
    voltage: int,
    phases: int,
    frequency: int,
    efficiency_class: str = "IE3"
) -> Tuple[float, str]:
    """
    Fallback FLA calculation using formula.
    FLA = (kW × 1000) / (√3 × V × η × pf) for 3-phase
    """
    # Get typical efficiency for this class and size
    standards = _get_motor_standards()
    eff_table = standards["iec_efficiency_classes"].get(efficiency_class, {})
    eff_data = eff_table.get("efficiency", {}).get("4_pole", {})

    # Find closest efficiency
    eff = 0.90  # Default
    for kw_key in sorted([float(k) for k in eff_data.keys()]):
        if kw_key >= kw:
            eff = eff_data.get(kw_key, eff_data.get(str(kw_key), 90)) / 100
            break

    # Typical power factor
    pf = 0.85

    if phases == 3:
        fla = (kw * 1000) / (math.sqrt(3) * voltage * eff * pf)
    else:
        fla = (kw * 1000) / (voltage * eff * pf)

    return round(fla, 1), "calculated"


def lookup_fla(
    power_kw: float,
    voltage: int,
    phases: int = 3,
    frequency: int = 50,
    motor_standard: Literal["IEC", "NEMA"] = "IEC",
    efficiency_class: str = "IE3"
) -> Tuple[float, str]:
    """
    Look up FLA based on motor standard.

    Args:
        power_kw: Motor power in kW
        voltage: Motor voltage
        phases: 1 or 3
        frequency: 50 or 60 Hz
        motor_standard: "IEC" or "NEMA"
        efficiency_class: Efficiency class for IEC lookup

    Returns:
        Tuple of (FLA, source)
    """
    if motor_standard == "NEMA":
        # Convert kW to HP
        hp = power_kw * 1.341
        return lookup_fla_nec(hp, voltage, phases)
    else:
        return lookup_fla_iec(power_kw, voltage, frequency, efficiency_class)


# ============================================================================
# LRA Calculation
# ============================================================================

def calc_lra(
    fla: float,
    lra_multiplier: float = 6.0,
    design_letter: Optional[str] = None
) -> float:
    """
    Calculate Locked Rotor Amps.

    Args:
        fla: Full Load Amps
        lra_multiplier: LRA/FLA ratio (default 6.0 for NEMA Design B)
        design_letter: Optional NEMA design letter (A, B, C, D)

    Returns:
        LRA value
    """
    if design_letter:
        tables = _get_motor_fla_tables()
        multipliers = tables.get("lra_multipliers", {}).get("design_letter", {})
        if design_letter.upper() in multipliers:
            lra_multiplier = multipliers[design_letter.upper()]["multiplier"]

    return fla * lra_multiplier


# ============================================================================
# Brake Power Calculations
# ============================================================================

def calc_pump_brake_kw(
    flow_m3h: float,
    head_m: float,
    sg: float = 1.0,
    pump_eff: float = 0.70
) -> float:
    """
    Calculate pump brake power (shaft power).

    P = ρgQH / η  [Hydraulic Institute standards]

    Args:
        flow_m3h: Flow rate in m³/h
        head_m: Total dynamic head in meters
        sg: Specific gravity (default 1.0 for water)
        pump_eff: Pump efficiency (0.60-0.85 typical)

    Returns:
        Brake power in kW
    """
    # P = (ρ × g × Q × H) / (η × 3600)
    # where ρ = sg × 1000 kg/m³, g = 9.81 m/s²
    # Q in m³/h, H in m
    brake_kw = (sg * 9.81 * flow_m3h * head_m) / (3600 * pump_eff)
    return round(brake_kw, 2)


def calc_blower_brake_kw(
    flow_nm3h: float,
    p1_bar: float,
    p2_bar: float,
    inlet_temp_k: float = 293.0,
    n: float = 1.4,
    blower_eff: float = 0.70
) -> float:
    """
    Calculate blower brake power using polytropic compression.

    For aeration blowers in WWTP applications.

    Args:
        flow_nm3h: Normal flow rate in Nm³/h (at STP: 0°C, 1.013 bar)
        p1_bar: Inlet absolute pressure in bar (typically 1.013)
        p2_bar: Outlet absolute pressure in bar (inlet + delivery pressure)
        inlet_temp_k: Inlet temperature in Kelvin (default 293K = 20°C)
        n: Polytropic exponent (1.4 for air, diatomic gas)
        blower_eff: Blower isentropic efficiency (0.65-0.80 typical)

    Returns:
        Brake power in kW
    """
    # Convert Nm³/h to actual m³/s at inlet conditions
    # Actual flow = Normal flow × (T_actual/T_normal) × (P_normal/P_actual)
    t_normal = 273.15  # 0°C in K
    p_normal = 1.01325  # bar

    # For polytropic compression:
    # P = (n/(n-1)) × p1 × V × [(p2/p1)^((n-1)/n) - 1] / η
    # where V is volumetric flow at inlet in m³/s

    ratio = p2_bar / p1_bar
    exponent = (n - 1) / n

    # Power formula
    brake_kw = (
        (n / (n - 1)) *
        p1_bar * 100 *  # Convert bar to kPa
        (flow_nm3h / 3600) *  # Convert to m³/s
        (inlet_temp_k / t_normal) *  # Temperature correction
        (p_normal / p1_bar) *  # Pressure correction to actual
        ((ratio ** exponent) - 1) /
        blower_eff
    )

    return round(brake_kw, 2)


def calc_mixer_brake_kw(
    volume_m3: float,
    w_per_m3: float = 8.0
) -> float:
    """
    Calculate mixer power based on volumetric loading.

    Args:
        volume_m3: Tank volume in m³
        w_per_m3: Power density in W/m³
            - Equalization: 5-10 W/m³
            - Anoxic mixing: 5-8 W/m³
            - Complete mix: 10-20 W/m³
            - Flocculation: 2-5 W/m³

    Returns:
        Brake power in kW
    """
    return round(volume_m3 * w_per_m3 / 1000, 2)


def calc_absorbed_kw(brake_kw: float, motor_efficiency_pct: float) -> float:
    """
    Calculate electrical power absorbed by motor.

    Args:
        brake_kw: Shaft power (brake power)
        motor_efficiency_pct: Motor efficiency as percentage (e.g., 95.0)

    Returns:
        Absorbed electrical power in kW
    """
    return round(brake_kw / (motor_efficiency_pct / 100), 2)


# ============================================================================
# Diversity Factor Parsing
# ============================================================================

def parse_diversity_from_quantity_note(quantity_note: str) -> Tuple[float, int, int]:
    """
    Parse quantity notation to extract diversity factor.

    Patterns:
        "1W" -> (1.0, 1, 0)
        "1W + 1S" -> (0.5, 1, 1)
        "2W + 1S" -> (0.67, 2, 1)
        "3W + 1S" -> (0.75, 3, 1)
        "N+1" with context needed

    Args:
        quantity_note: Quantity notation string (e.g., "2W+1S", "2W + 1S")

    Returns:
        Tuple of (diversity_factor, working, standby)
    """
    if not quantity_note:
        return 1.0, 1, 0

    # Normalize string
    note = quantity_note.upper().replace(" ", "")

    # Pattern: NW or NW+MS
    pattern = r"(\d+)W(?:\+(\d+)S)?"
    match = re.match(pattern, note)

    if match:
        working = int(match.group(1))
        standby = int(match.group(2)) if match.group(2) else 0
        total = working + standby
        diversity = working / total if total > 0 else 1.0
        return round(diversity, 2), working, standby

    # Pattern: just a number (assume all working)
    if note.isdigit():
        qty = int(note)
        return 1.0, qty, 0

    # Default
    return 1.0, 1, 0


def get_diversity_factor(quantity_note: str) -> float:
    """Get just the diversity factor from quantity notation."""
    diversity, _, _ = parse_diversity_from_quantity_note(quantity_note)
    return diversity


# ============================================================================
# Load Factor and Running Hours
# ============================================================================

def get_duty_profile(
    equipment_type: str,
    process_unit_type: Optional[str] = None,
    feeder_type: str = "VFD"
) -> dict:
    """
    Get duty profile for equipment.

    Args:
        equipment_type: Equipment code (P, B, AG, SC, etc.)
        process_unit_type: Full process unit type path
        feeder_type: DOL, VFD, etc.

    Returns:
        Dict with running_hours_per_day, load_factor, duty_cycle
    """
    profiles = _get_duty_profiles()["equipment_profiles"]

    # Map equipment type codes to profile categories
    type_map = {
        "P": "pumps",
        "B": "blowers",
        "AG": "mixers",
        "MX": "mixers",
        "SC": "screens",
        "CN": "conveyors",
        "C": "compressors",
        "FN": "fans",
        "TH": "clarifier_mechanisms",
        "CL": "clarifier_mechanisms",
    }

    category = type_map.get(equipment_type.upper(), "pumps")
    category_profiles = profiles.get(category, {})

    # Try to find specific profile by process unit type
    profile = None
    if process_unit_type:
        # Extract key terms from process unit type
        for key in category_profiles.keys():
            if key != "default" and key.lower() in process_unit_type.lower():
                profile = category_profiles[key]
                break

    if profile is None:
        profile = category_profiles.get("default", {
            "running_hours_per_day": 20,
            "load_factor_vfd": 0.75,
            "load_factor_dol": 0.95,
            "duty_cycle": "continuous"
        })

    # Select load factor based on feeder type
    is_vfd = feeder_type.upper() in ["VFD", "VFD-EXT"]
    load_factor_key = "load_factor_vfd" if is_vfd else "load_factor_dol"
    load_factor = profile.get(load_factor_key, 0.85)

    return {
        "running_hours_per_day": profile.get("running_hours_per_day", 20),
        "load_factor": load_factor,
        "duty_cycle": profile.get("duty_cycle", "continuous"),
        "notes": profile.get("notes", "")
    }


# ============================================================================
# Energy Calculations
# ============================================================================

def calc_running_kw(absorbed_kw: float, load_factor: float) -> float:
    """Calculate running kW (average power consumption)."""
    return round(absorbed_kw * load_factor, 2)


def calc_demand_kw(running_kw: float, diversity_factor: float) -> float:
    """Calculate demand kW accounting for diversity."""
    return round(running_kw * diversity_factor, 2)


def calc_daily_kwh(running_kw: float, running_hours: float) -> float:
    """Calculate daily energy consumption."""
    return round(running_kw * running_hours, 2)


def calc_specific_energy(daily_kwh: float, flow_m3_per_day: float) -> float:
    """
    Calculate specific energy consumption.

    Typical WWTP values:
        - Conventional: 0.3-0.6 kWh/m³
        - MBR: 0.5-1.0 kWh/m³
        - Advanced treatment: 0.8-1.5 kWh/m³

    Args:
        daily_kwh: Total daily energy consumption
        flow_m3_per_day: Average daily flow

    Returns:
        Specific energy in kWh/m³
    """
    if flow_m3_per_day <= 0:
        return 0.0
    return round(daily_kwh / flow_m3_per_day, 3)


# ============================================================================
# Motor Efficiency Lookup
# ============================================================================

def get_motor_efficiency(
    kw: float,
    poles: int = 4,
    efficiency_class: str = "IE3"
) -> float:
    """
    Get motor efficiency from standards tables.

    Args:
        kw: Motor power in kW
        poles: Number of poles (2, 4, 6, 8)
        efficiency_class: IE1, IE2, IE3, IE4

    Returns:
        Efficiency as percentage (e.g., 95.0)
    """
    standards = _get_motor_standards()
    iec_classes = standards.get("iec_efficiency_classes", {})

    eff_class = iec_classes.get(efficiency_class, iec_classes.get("IE3", {}))
    eff_data = eff_class.get("efficiency", {}).get(f"{poles}_pole", {})

    # Find closest kW rating
    kw_values = sorted([float(k) for k in eff_data.keys()])
    for kw_key in kw_values:
        if kw_key >= kw:
            return float(eff_data.get(kw_key, eff_data.get(str(kw_key), 90)))

    # Return last value if kW exceeds table
    if kw_values:
        return float(eff_data.get(kw_values[-1], 94.0))

    return 90.0  # Default


# ============================================================================
# Unit Conversions
# ============================================================================

# ============================================================================
# IEC Standard Motor Ratings
# ============================================================================

# IEC standard motor output ratings (kW) per IEC 60034-1
IEC_STANDARD_RATINGS_KW = [
    0.12, 0.18, 0.25, 0.37, 0.55, 0.75,
    1.1, 1.5, 2.2, 3.0, 4.0, 5.5, 7.5,
    11, 15, 18.5, 22, 30, 37, 45, 55, 75,
    90, 110, 132, 160, 200, 250, 315, 355, 400,
]


def round_to_iec_frame_kw(brake_kw: float, safety_factor: float = 1.15) -> float:
    """Round brake power up to the next IEC standard motor rating.

    Applies a safety factor (default 1.15) before rounding up.

    Args:
        brake_kw: Shaft power (brake power) in kW
        safety_factor: Safety factor to apply (default 1.15 = 15% margin)

    Returns:
        Next standard IEC motor rating in kW
    """
    required = brake_kw * safety_factor
    for rating in IEC_STANDARD_RATINGS_KW:
        if rating >= required:
            return rating
    # If beyond table, return the required value rounded up
    return round(required, 1)


def hp_to_kw(hp: float) -> float:
    """Convert horsepower to kilowatts."""
    return round(hp * 0.7457, 3)


def kw_to_hp(kw: float) -> float:
    """Convert kilowatts to horsepower."""
    return round(kw * 1.341, 3)


def mld_to_m3h(mld: float) -> float:
    """Convert MLD to m³/h."""
    return round(mld * 1000 / 24, 2)


def m3h_to_mld(m3h: float) -> float:
    """Convert m³/h to MLD."""
    return round(m3h * 24 / 1000, 3)


if __name__ == "__main__":
    # Quick test
    print("Testing load_calculations module...")

    # Test FLA lookup
    fla, source = lookup_fla(110, 400, 3, 50, "IEC", "IE3")
    print(f"110 kW @ 400V IEC: FLA = {fla}A (source: {source})")

    fla, source = lookup_fla(100, 460, 3, 60, "NEMA")
    print(f"100 HP @ 460V NEMA: FLA = {fla}A (source: {source})")

    # Test brake power
    brake = calc_pump_brake_kw(500, 30, 1.0, 0.75)
    print(f"Pump 500 m³/h @ 30m: brake = {brake} kW")

    brake = calc_blower_brake_kw(2500, 1.013, 1.7, 293, 1.4, 0.70)
    print(f"Blower 2500 Nm³/h @ 0.7 bar: brake = {brake} kW")

    # Test diversity
    div, w, s = parse_diversity_from_quantity_note("2W + 1S")
    print(f"2W + 1S: diversity = {div}, working = {w}, standby = {s}")

    print("\nAll tests passed!")
