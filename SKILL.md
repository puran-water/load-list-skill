---
name: load-list-skill
description: |
  Generate electrical load lists with NEC/IEC-compliant protection sizing, MCC bucket schedules,
  and cable schedules for contractor costing.

  Use when: (1) Equipment list is complete and need electrical load data,
  (2) Generating engineering-grade MCC schedules per NEC 430/IEC 60364,
  (3) Calculating energy consumption (kWh/day),
  (4) Need FLC/FLA for cable and protection sizing,
  (5) Transformer sizing and motor starting analysis.

  IMPORTANT DISTINCTIONS:
  - "Load Summary" vs "MCC Schedule" - different outputs, different purposes
  - "Preliminary Sizing" vs "Code-Compliant Sizing" - different calculations
  - NEC and IEC are SEPARATE code pathways - do not imply dual-compliance
---

# Load List Skill

Generate engineering-grade electrical load lists from equipment lists, with NEC/IEC-compliant
motor circuit sizing, MCC bucket schedules, and cable takeoffs.

## Scope Guardrails

### What This Skill Does (In Scope)

| Output | Description | Tier |
|--------|-------------|------|
| Load Summary | kW totals, energy, preliminary transformer | Tier 1 |
| MCC Schedule | Bucket-level detail with protection sizing | Tier 2/3 |
| Cable Schedule | Cable sizes and quantities for costing | Tier 2/3 |
| Transformer Sizing | kVA selection with motor starting check | Tier 2 |
| Plant Load Summary | Total loads with non-process allowances | Tier 1 |

### What This Skill Does NOT Do (Out of Scope)

- **Short-circuit study** - Requires ETAP/SKM/EasyPower
- **Protection coordination** - Requires TCC analysis software
- **Arc flash study** - Requires IEEE 1584 calculation (placeholders provided)
- **Detailed voltage drop** - Provided as estimate, verify with design software
- **Cable routing/layout** - Requires plant layout drawings

### Regional Code Adoption Caveat

NEC edition adoption varies by Authority Having Jurisdiction (AHJ):
- NEC 2023 is current reference edition
- NEC 2026 effective dates vary by jurisdiction
- Always verify with local AHJ requirements

IEC adoption varies by country:
- IEC 60364 with national variations (BS 7671, AS/NZS 3000, etc.)
- Verify specific national requirements

## Tiered Output System

### Tier 1: Load Study (Always Available)
- kW totals and energy summary
- Preliminary transformer sizing
- Load list summary
- **Disclaimer**: "PRELIMINARY - FOR PLANNING PURPOSES ONLY"

### Tier 2: Preliminary Schedule (Motor data ≥80% complete)
- MCC bucket schedule (flagged preliminary)
- Starter and VFD frame sizing
- Preliminary cable sizing
- **Disclaimer**: "PRELIMINARY - VERIFY BEFORE PROCUREMENT"

### Tier 3: Code-Compliant (All inputs verified)
- Final MCC schedule per NEC 430/IEC 60364
- Cable takeoff for contractor pricing
- SCCR validation report
- **No disclaimers** - suitable for construction

## Workflow

1. Load equipment list from QMD/YAML
2. Extract duty points from Tier 1 sizing artifacts
3. Look up FLC from NEC/IEC tables (for conductor/SCPD sizing)
4. Determine FLA from nameplate (for overload settings)
5. Calculate brake power (pump/blower/mixer equations)
6. Apply duty profiles (running hours, load factors)
7. Parse diversity from quantity notation
8. Size branch circuit protection per NEC 430.52
9. Size overload protection per NEC 430.32
10. Aggregate loads by MCC panel
11. Size feeder conductors per NEC 430.24
12. Size feeder OCPD per NEC 430.62
13. Generate YAML load list + Excel outputs

## Key NEC/IEC Calculations

### FLC vs FLA Distinction (NEC 430.6(A)(1))

| Value | Source | Used For |
|-------|--------|----------|
| **FLC (Table)** | NEC 430.250/IEC 60034 | Conductor sizing (430.22), SCPD sizing (430.52) |
| **FLA (Nameplate)** | Motor nameplate | Overload settings (430.32) |

### Power Semantics

| Term | Definition | Use |
|------|------------|-----|
| `rated_kw` | Motor nameplate kW (mechanical output) | FLC table lookup |
| `brake_kw` | Shaft power at duty point | Actual load calculation |
| `absorbed_kw` | Electrical input = brake_kw / efficiency | Running load, energy |

**Note**: `installed_kw` is DEPRECATED - use `rated_kw`

## Quick Start

```bash
python scripts/generate_load_list.py \
  --equipment submittals/equipment-list.qmd \
  --output electrical/load-list.yaml \
  --project-dir . \
  --motor-standard IEC \
  --voltage 400 \
  --frequency 50

python scripts/yaml_to_xlsx.py \
  --input electrical/load-list.yaml \
  --output electrical/load-list.xlsx
```

## Input Requirements

### Equipment List
Source: `equipment-list-skill` output

Required fields:
- `tag` - Equipment tag (e.g., 200-B-01)
- `power_kw` - Installed motor power
- `feeder_type` - DOL/VFD/SOFT-STARTER/VENDOR

Optional fields:
- `process_unit_type` - For duty profile lookup
- `quantity_note` - For diversity (e.g., "2W+1S")
- `mcc_panel` - Panel assignment

### Project Configuration
Set motor standard via CLI flag or project config:
- `motor_standard`: IEC or NEMA
- `voltage`: 380/400/415 (IEC) or 460/480 (NEMA)
- `frequency`: 50 or 60 Hz

## Output Artifacts

| Artifact | Path | Description |
|----------|------|-------------|
| YAML | `electrical/load-list.yaml` | Source of truth |
| Excel | `electrical/load-list.xlsx` | Full load list + MCC sheets |

## Calculations & Duty Profiles

See `references/calculation-basis.md` when validating or modifying:
- FLC lookup methods (NEC 430.250 / IEC 60034)
- Brake power equations (pump, blower, mixer)
- Diversity factor parsing rules
- Energy calculation formulas

See `references/nec-motor-sizing.md` for NEC Article 430 code summary.

See `catalogs/duty_profiles.yaml` for equipment-specific running hours and load factors.

## MCC Panel Sizing (NEC-Compliant)

### Feeder Conductor Sizing (NEC 430.24)
```
Ampacity ≥ 125% × (largest motor FLC) + Σ(other motor FLCs)
         + 125% × continuous non-motor + non-continuous non-motor
```

### Feeder OCPD Sizing (NEC 430.62)
```
Max Rating = (largest motor branch SCPD per 430.52) + Σ(other motor FLCs)
```
Select standard rating that does NOT exceed calculated maximum.

### Main Breaker Selection
- Must not exceed feeder_ocpd_max per 430.62
- Round DOWN to standard size (no "next size up" at feeder level)

### Bus Rating Selection
- Must be ≥ feeder_conductor_min_a
- Standard sizes: 400A, 630A, 800A, 1000A, 1600A, 2000A, 2500A, 3200A

## Bundled Resources

### Scripts
- `generate_load_list.py` - Main generator
- `load_calculations.py` - Core equations (FLC lookup, brake power)
- `extract_duty_points.py` - Tier 1 integration
- `mcc_aggregation.py` - Panel rollup
- `yaml_to_xlsx.py` - Excel conversion
- `fault_current.py` - Preliminary fault current calculation
- `branch_circuit_sizing.py` - NEC 430.22/430.52 sizing
- `overload_sizing.py` - NEC 430.32 sizing
- `feeder_sizing.py` - NEC 430.24/430.62 sizing
- `vfd_sizing.py` - NEC 430.122/430.130 VFD sizing
- `cable_sizing.py` - Cable ampacity and derating
- `voltage_drop.py` - Voltage drop calculation
- `transformer_sizing.py` - Transformer selection
- `motor_starting.py` - Motor starting voltage dip analysis
- `plant_load_summary.py` - Plant totals with non-process loads
- `sccr_validation.py` - SCCR validation with warnings
- `generate_cable_schedule.py` - Cable takeoff for costing
- `mcc_bucket_schedule.py` - Bucket-level MCC output

### Catalogs
- `motor_fla_tables.yaml` - NEC/IEC FLC tables
- `motor_standards.yaml` - Efficiency classes
- `starter_sizing.yaml` - IEC/NEMA starters
- `duty_profiles.yaml` - Running hours, load factors
- `branch_circuit_protection.yaml` - NEC 430.52 tables
- `overload_protection.yaml` - NEC 430.32 rules
- `cable_ampacity.yaml` - NEC 310/IEC 60364 tables
- `transformers.yaml` - Standard sizes
- `non_process_loads.yaml` - Allowance percentages
- `vfd_catalog.yaml` - VFD manufacturer data

### References
- `calculation-basis.md` - Engineering equations
- `nec-motor-sizing.md` - NEC Article 430 code summary

### Schemas
- `load-list.schema.yaml` - Main data model (v2.0.0)
- `electrical-basis.schema.yaml` - Code basis and fault current
- `output-tier.schema.yaml` - Tiered output definitions
- `mcc-bucket.schema.yaml` - MCC bucket model
- `mcc-panel.schema.yaml` - MCC panel summary
- `cable-schedule.schema.yaml` - Cable takeoff model
- `protection-device.schema.yaml` - Coordination hooks
- `arc-flash.schema.yaml` - Arc flash placeholders

## Integration

### Upstream
- `equipment-list-skill` - Equipment list with power_kw
- Tier 1 sizing artifacts - Duty points (flow, head)

### Downstream
- `sld-skill` - Single line diagram generation
- `cable-schedule-skill` - Cable sizing
- `control-philosophy-skill` - Control narratives

## Validation

See `references/calculation-basis.md` for typical WWTP specific energy ranges.
If calculated values fall outside expected ranges, review duty profiles, equipment sizing, and diversity factors.

## Dependencies

Python packages:
- `pyyaml` - YAML parsing
- `openpyxl` - Excel generation
