"""
Translates a Scenario row (plus its ScenarioParameter rows) into the
override dict consumed by model_builder.apply_overrides(). Also defines
the one-click experiment presets from spec section 56 - each preset is
just a named override dict, resolved against whatever sources/corridors
actually exist in the project (no hard-coded facility codes).
"""


def scenario_to_overrides(scenario) -> dict:
    overrides = {
        "demand_multiplier": scenario.demand_multiplier or 1.0,
        "corridor_capacity_multiplier": scenario.pipeline_capacity_multiplier or 1.0,
        "transport_cost_multiplier": scenario.transport_cost_multiplier or 1.0,
        "source_availability": {},
    }
    for p in scenario.parameters:
        if p.entity_type == "source" and p.parameter == "availability_factor":
            overrides["source_availability"][p.entity_code] = p.value
        elif p.entity_type == "corridor" and p.parameter == "inactive" and p.value:
            overrides.setdefault("inactive_corridors", []).append(p.entity_code)
        elif p.entity_type == "cgs" and p.parameter == "inactive" and p.value:
            overrides.setdefault("inactive_cgs", []).append(p.entity_code)
        elif p.entity_type == "station" and p.parameter == "inactive" and p.value:
            overrides.setdefault("inactive_stations", []).append(p.entity_code)
    return overrides


def build_preset_overrides(project, preset_key: str) -> dict:
    """One-click experiments (spec section 56). Applies uniformly across
    whatever sources/corridors/facilities exist - never references a
    specific facility code by name."""
    all_source_codes = [s.code for s in project.sources if s.is_active]
    all_corridor_codes = [c.code for c in project.corridors if c.is_active]
    all_cgs_codes = [c.code for c in project.cgs_list if c.is_active]

    presets = {
        "normal": {},
        "shortage_20": {"source_availability": {c: 0.80 for c in all_source_codes}},
        "shortage_40": {"source_availability": {c: 0.60 for c in all_source_codes}},
        "shortage_60": {"source_availability": {c: 0.40 for c in all_source_codes}},
        "demand_surge": {"demand_multiplier": 1.25},
        "pipeline_failure": {"inactive_corridors": all_corridor_codes[:1]} if all_corridor_codes else {},
        "combined_crisis": {
            "source_availability": {c: 0.70 for c in all_source_codes},
            "demand_multiplier": 1.20,
            "corridor_capacity_multiplier": 0.85,
        },
    }
    if preset_key not in presets:
        raise ValueError(f"Unknown preset '{preset_key}'. Valid: {list(presets.keys())}")
    return presets[preset_key]


PRESET_LABELS = {
    "normal": "Normal Operation",
    "shortage_20": "20% Supply Shortage",
    "shortage_40": "40% Supply Shortage",
    "shortage_60": "60% Supply Shortage",
    "demand_surge": "Demand Surge (+25%)",
    "pipeline_failure": "Pipeline Failure (first active corridor)",
    "combined_crisis": "Combined Crisis (supply -30%, demand +20%, pipeline -15%)",
}
