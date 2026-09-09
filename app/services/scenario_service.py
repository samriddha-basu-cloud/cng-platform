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

    # sources flagged as upstream/GAIL-style national-grid supply - the ones
    # the "GAIL upstream interruption" preset targets specifically, using
    # each source's own configured interruption_probability where set
    gail_sources = [s for s in project.sources if s.is_active and getattr(s, "is_upstream_gail", False)]
    gail_availability = {
        s.code: max(0.0, 1 - (s.interruption_probability if s.interruption_probability else 0.5))
        for s in gail_sources
    }

    # industrial demand zones - the ones the "industrial demand variability"
    # preset swings using each zone's own configured demand_variability_pct
    industrial_zones = [d for d in project.demand_zones if d.demand_type == "Industrial"]
    industrial_swing = {
        d.code: 1 + (d.demand_variability_pct if d.demand_variability_pct else 0.15)
        for d in industrial_zones
    }

    # average logistics cost-variation band configured on corridors, used by
    # the "logistics cost spike" preset when no per-corridor value is set
    variable_corridors = [c for c in project.corridors if c.is_active]
    avg_variation = (sum((c.cost_variation_pct or 0) for c in variable_corridors) / len(variable_corridors)
                      if variable_corridors else 0.20)

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
        "gail_upstream_interruption": {"source_availability": gail_availability} if gail_availability else {},
        "industry_demand_variability": {"demand_zone_multiplier": industrial_swing} if industrial_swing else {},
        "logistics_cost_spike": {"transport_cost_multiplier": 1 + avg_variation},
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
    "gail_upstream_interruption": "GAIL/Upstream Supply Interruption",
    "industry_demand_variability": "Industrial Demand Variability",
    "logistics_cost_spike": "Logistics Cost Spike",
}

PRESET_HINTS = {
    "normal": "Runs the network exactly as configured - a baseline to compare every other preset against.",
    "shortage_20": "Every active source's availability factor drops to 80% - a broad, moderate supply squeeze.",
    "shortage_40": "Every active source's availability factor drops to 60%.",
    "shortage_60": "Every active source's availability factor drops to 40% - a severe, near-crisis supply cut.",
    "demand_surge": "All demand zones scale up 25% at once - tests whether current capacity holds under a spike.",
    "pipeline_failure": "Takes the first active corridor fully offline - a single-point-of-failure stress test.",
    "combined_crisis": "Stacks a supply cut, a demand surge, and reduced pipeline capacity at once.",
    "gail_upstream_interruption": "Cuts availability only on sources flagged 'Upstream (GAIL)' in Network -> Sources, "
                                   "using each source's own Interruption probability field (defaults to 50% if unset) - "
                                   "models a national-grid supply disruption rather than a uniform shock.",
    "industry_demand_variability": "Scales only Industrial-type demand zones, by each zone's own Demand variability "
                                    "field (defaults to +15% if unset) - industrial offtake swings with production "
                                    "cycles in a way household/commercial demand doesn't.",
    "logistics_cost_spike": "Raises transport cost across every corridor using the average Cost variation field "
                             "set on corridors (defaults to +20% if none set) - a fuel-price or freight-rate shock.",
}
