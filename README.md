# Load List Skill

Claude Code skill for generating engineering-grade electrical load lists with NEC/IEC-compliant protection sizing, MCC schedules, and cable schedules.

## Quick Start

### Prerequisites

1. Equipment list from `equipment-list-skill` with `power_kw` and `feeder_type` fields

### Basic Workflow

1. Load equipment list from QMD/YAML
2. Generate load list: `python scripts/generate_load_list.py`
3. Convert to Excel: `python scripts/yaml_to_xlsx.py`

## Documentation

See [SKILL.md](SKILL.md) for complete documentation including:

- Tiered output system (Tier 1/2/3)
- NEC/IEC calculation methods
- FLC vs FLA distinction
- MCC panel sizing rules
- Catalog references

## Files

| Path | Description |
|------|-------------|
| `SKILL.md` | Full skill documentation |
| `schemas/` | Load list and MCC schemas |
| `scripts/` | Generation and conversion scripts |
| `catalogs/` | Motor tables, duty profiles, protection sizing |
| `references/` | NEC/IEC code references |

## Workflow Integration

This skill is part of the puran-water electrical engineering workflow:

```
┌─────────────────────────┐     ┌──────────────────────────┐     ┌─────────────────────┐
│  equipment-list-skill   │ ──► │    load-list-skill       │ ──► │ electrical-         │
│  (equipment + power_kw) │     │    (this skill)          │     │ distribution-skill  │
└─────────────────────────┘     └──────────────────────────┘     │ (SLD generation)    │
                                             │                   └─────────────────────┘
                                             │
                                             ▼
                                ┌──────────────────────────┐
                                │ Outputs:                 │
                                │ - load-list.yaml         │
                                │ - load-list.xlsx         │
                                │ - MCC bucket schedules   │
                                │ - Cable schedules        │
                                └──────────────────────────┘
```

## Related

### Upstream
- [equipment-list-skill](https://github.com/puran-water/equipment-list-skill) - Equipment lists with power ratings

### Downstream
- [electrical-distribution-skill](https://github.com/puran-water/electrical-distribution-skill) - Single line diagram generation
- [plantuml-sld-mcp-server](https://github.com/puran-water/plantuml-sld-mcp-server) - SLD MCP server

## License

MIT License - Puran Water
