# Calculation Basis

Engineering basis for load list calculations.

## Full Load Amps (FLA)

### NEC Tables (NEMA Motors)
- **NEC 430.250**: Three-phase AC motors
- **NEC 430.248**: Single-phase AC motors
- Table values include typical efficiency and power factor
- Use for protective device sizing, not actual current

### IEC 60034 (IEC Motors)
- Approximate values for IE3 class motors
- Typical power factor 0.85
- Verify with manufacturer data for critical applications

### Formula Fallback
When table lookup fails:
```
FLA = (kW × 1000) / (√3 × V × η × pf)
```
Where:
- V = line voltage
- η = efficiency (0.90-0.96 typical)
- pf = power factor (0.85 typical)

## Locked Rotor Amps (LRA)

LRA = FLA × multiplier

| NEMA Design | Multiplier |
|-------------|------------|
| B (typical) | 6.0 |
| A | 7.5 |
| C | 6.5 |
| D | 6.0 |

## Pump Brake Power

Hydraulic Institute standard:
```
P = ρgQH / (η × 3600)
```
Where:
- P = brake power (kW)
- ρ = density (kg/m³) = SG × 1000
- g = 9.81 m/s²
- Q = flow (m³/h)
- H = head (m)
- η = pump efficiency (0.60-0.85)

Typical efficiencies:
- Small pumps (<10 kW): 0.60-0.70
- Medium pumps (10-100 kW): 0.70-0.80
- Large pumps (>100 kW): 0.75-0.85

## Blower Brake Power

Polytropic compression for aeration blowers:
```
P = (n/(n-1)) × p1 × V × [(p2/p1)^((n-1)/n) - 1] / η
```
Where:
- n = polytropic exponent (1.4 for air)
- p1 = inlet pressure (bar abs)
- p2 = outlet pressure (bar abs)
- V = volumetric flow at inlet (m³/s)
- η = blower isentropic efficiency (0.65-0.80)

Typical operating conditions:
- Inlet: atmospheric (1.013 bar) + losses
- Outlet: inlet + 0.4-0.7 bar delivery
- Turn-down ratio with VFD: 40-100%

## Mixer Power

Volumetric power density:
```
P = V × W / 1000
```
Where:
- P = power (kW)
- V = tank volume (m³)
- W = power density (W/m³)

Typical power densities:
| Application | W/m³ |
|-------------|------|
| Flocculation | 2-5 |
| Equalization | 5-10 |
| Anoxic mixing | 5-8 |
| Complete mix | 10-20 |
| Digester mixing | 5-10 |

## Motor Efficiency

IEC 60034-30-1 efficiency classes:
- **IE1**: Standard efficiency
- **IE2**: High efficiency
- **IE3**: Premium efficiency (mandatory EU/US)
- **IE4**: Super premium

Efficiency lookup by kW and poles from motor_standards.yaml

## Absorbed Power

Electrical power drawn by motor:
```
Absorbed kW = Brake kW / (η / 100)
```

## Running Power

Average power consumption:
```
Running kW = Absorbed kW × Load Factor
```

Load factor depends on:
- VFD applications: 0.60-0.80 (speed varies)
- DOL applications: 0.90-0.95 (near full load)

## Demand Power

Power accounting for diversity:
```
Demand kW = Running kW × Diversity Factor
```

Diversity factor from quantity notation:
| Notation | Diversity |
|----------|-----------|
| 1W | 1.0 |
| 1W + 1S | 0.50 |
| 2W + 1S | 0.67 |
| 3W + 1S | 0.75 |

## Daily Energy

```
kWh/day = Running kW × Hours/day
```

## Specific Energy

```
kWh/m³ = Daily kWh / (Flow MLD × 1000)
```

Typical WWTP values:
- Conventional activated sludge: 0.3-0.6 kWh/m³
- Extended aeration: 0.4-0.7 kWh/m³
- MBR: 0.5-1.0 kWh/m³
- Advanced treatment (RO): 0.8-1.5 kWh/m³

## Panel Diversity

Additional factor applied at MCC level:
| Feeders | Diversity |
|---------|-----------|
| 1-5 | 0.90 |
| 6-10 | 0.85 |
| 11-20 | 0.80 |
| 21-50 | 0.75 |
| >50 | 0.70 |

## References

1. NEC 2023 - Article 430 (Motors)
2. IEC 60034-1 (Rotating electrical machines)
3. IEC 60034-30-1 (Efficiency classes)
4. Hydraulic Institute Standards
5. IEEE 141-1993 (Red Book) - Industrial power systems
6. IEEE 399-1997 (Brown Book) - Power system analysis
