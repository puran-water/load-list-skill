# NEC Motor Circuit Sizing Reference

## Quick Reference: NEC Article 430

This document summarizes NEC motor circuit sizing rules implemented in this skill.

### Key Distinction: FLC vs FLA

| Term | Source | Use |
|------|--------|-----|
| **FLC (Full Load Current)** | NEC Tables 430.248/250 | Branch circuit, feeder, SCPD sizing |
| **FLA (Full Load Amps)** | Motor nameplate | Overload relay sizing |

**Critical**: NEC 430.6(A)(1) requires using **table values** (FLC) for circuit sizing, not nameplate values.

---

## Branch Circuit Sizing (NEC 430.22)

### Conductor Ampacity
**Formula**: Conductor ampacity ≥ 125% × Motor FLC

```
Example: 37 kW motor @ 400V, FLC = 68A
Minimum conductor ampacity = 1.25 × 68A = 85A
Select: 25 mm² Cu (101A @ 30°C) or 3 AWG (100A @ 75°C)
```

### Implementation
```python
# scripts/branch_circuit_sizing.py
def calc_branch_conductor_ampacity(motor_flc: float) -> float:
    return 1.25 * motor_flc
```

---

## Branch Circuit Protection (NEC 430.52)

### Maximum SCPD Ratings (% of FLC)

| Device Type | Maximum | Exception |
|-------------|---------|-----------|
| Dual-element time-delay fuse | 175% | 225% |
| Non-time-delay fuse | 300% | 400% |
| Inverse-time CB | 250% | 400% |
| Instantaneous-trip CB (MCP) | 800% | 1100%* |

*1300% for Design B energy-efficient motors

### Standard Sizes (NEC 240.6)
15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 110, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500, 600, 700, 800, 1000, 1200, 1600, 2000, 2500, 3000, 4000, 5000, 6000 A

### Standard Size Selection Rule
If calculated maximum doesn't correspond to a standard size, select the **next standard size up** that does not exceed the calculated maximum. If no standard size is at or below the calculated maximum, use the next larger standard size per NEC 240.4(B) exception for motor circuits.

```
Example: 37 kW motor, FLC = 68A, using MCCB
Maximum = 250% × 68A = 170A
Standard sizes: ...150, 175, 200...
Select: 150A (next standard ≤170A)
```

### Implementation
```python
# scripts/branch_circuit_sizing.py
def calc_branch_scpd_max(motor_flc: float, device_type: str) -> float:
    percentages = {
        "dual_element_fuse": 175,
        "non_time_delay_fuse": 300,
        "inverse_time_cb": 250,
        "instantaneous_cb": 800
    }
    return motor_flc * (percentages[device_type] / 100)
```

---

## Overload Protection (NEC 430.32)

### Maximum Overload Setting (% of nameplate FLA)

| Motor Characteristic | Maximum |
|---------------------|---------|
| SF ≥ 1.15 or temp rise ≤ 40°C | 125% |
| All other motors | 115% |

### Exception
If 115%/125% insufficient for motor starting:
- SF ≥ 1.15: May use up to 140%
- Other motors: May use up to 130%

```
Example: Motor nameplate FLA = 65A, SF = 1.15
Maximum OL setting = 125% × 65A = 81.25A
```

### Overload Relay Class (IEC 60947-4-1)

| Class | Trip Time @ 7.2×FLA | Application |
|-------|---------------------|-------------|
| 5 | ≤5 sec | Submersible pumps, hermetic compressors |
| 10 | ≤10 sec | General purpose (default) |
| 20 | ≤20 sec | High inertia (conveyors, mixers) |
| 30 | ≤30 sec | Very high inertia (crushers) |

### Implementation
```python
# scripts/overload_sizing.py
def calc_overload_max_setting(fla_nameplate: float, service_factor: float) -> float:
    if service_factor >= 1.15:
        return 1.25 * fla_nameplate
    else:
        return 1.15 * fla_nameplate
```

---

## Feeder Sizing (NEC 430.24, 430.62)

### Feeder Conductor (NEC 430.24)
**Formula**: Ampacity ≥ 125% × (largest motor FLC) + Σ(other motor FLCs) + continuous loads × 125%

```
Example: MCC with 110 kW (195A), 37 kW (68A), 22 kW (41A)
Feeder ampacity = 1.25 × 195 + 68 + 41 = 352.75A
Select: 185 mm² Cu (341A) → Need 240 mm² (400A)
```

### Feeder OCPD (NEC 430.62)
**Formula**: Max rating = (largest motor branch SCPD) + Σ(other motor FLCs)

**Note**: No "next-size-up" rule at feeder level - must not exceed calculated maximum.

```
Example: Same MCC, largest motor SCPD = 300A (MCCB)
Feeder OCPD max = 300 + 68 + 41 = 409A
Select: 400A (standard size ≤409A)
```

### Implementation
```python
# scripts/feeder_sizing.py
def calc_feeder_conductor_ampacity(motors: list[dict]) -> float:
    flcs = sorted([m['flc_table_a'] for m in motors], reverse=True)
    return 1.25 * flcs[0] + sum(flcs[1:])

def calc_feeder_ocpd_max(motors: list[dict]) -> float:
    largest_scpd = max(m['branch_scpd_rating'] for m in motors)
    other_flcs = sum(m['flc_table_a'] for m in motors) - max(m['flc_table_a'] for m in motors)
    return largest_scpd + other_flcs
```

---

## VFD Circuits (NEC Article 430 Part X)

### VFD Supply Conductors (NEC 430.122)
**Formula**: Ampacity ≥ 125% × VFD rated input current

**Note**: Use VFD nameplate/catalog input current, not motor FLC.

### VFD Branch Protection (NEC 430.130)
- Default: Per 430.52 using motor FLC
- Exception: Per manufacturer if drive marked "Suitable for Output Motor Conductor Protection"

### Implementation
```python
# scripts/vfd_sizing.py
def calc_vfd_supply_conductor_ampacity(vfd_input_current: float) -> float:
    return 1.25 * vfd_input_current
```

---

## Common Mistakes to Avoid

1. **Using nameplate FLA for circuit sizing** - Use NEC table FLC
2. **Next-size-up at feeder level** - Not permitted; must not exceed calculated max
3. **Sizing overload from FLC** - Use nameplate FLA
4. **Ignoring VFD input current** - VFD input ≠ motor FLC × efficiency
5. **LRA for breaker sizing** - SCPD sized from FLC percentage, not LRA

---

## Code References

| Section | Topic |
|---------|-------|
| 430.6(A)(1) | Use table FLC for calculations |
| 430.22 | Branch circuit conductors |
| 430.24 | Feeder conductors |
| 430.32 | Overload protection |
| 430.52 | Branch circuit SCPD |
| 430.62 | Feeder OCPD |
| 430.122 | VFD supply conductors |
| 430.130 | VFD branch protection |
| 240.6 | Standard OCPD sizes |

---

## IEC Equivalent Standards

| NEC | IEC Equivalent |
|-----|----------------|
| 430 Motor Circuits | IEC 60364-5-52 (Wiring), IEC 60947-4-1 (Starters) |
| 240 OCPD | IEC 60947-2 (Circuit Breakers) |
| 310 Conductors | IEC 60364-5-52 Annex B (Ampacity) |

---

*Last updated: 2026-02-01*
*Version: 2.0.0*
