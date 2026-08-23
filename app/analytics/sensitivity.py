"""
Sensitivity analysis (spec section 25). Perturbs one parameter at a time
by +/-delta_pct and records the resulting cost, producing tornado-chart
data sorted by impact magnitude. Also produces a 2D scenario heatmap
over two parameters at once (default: supply availability x demand
growth).
"""
from app.optimization import model_builder as mb, engine

PARAMETERS = {
    "supply_availability": {"label": "Supply availability", "override_key": "source_availability_scale"},
    "demand_growth": {"label": "Demand level", "override_key": "demand_multiplier"},
    "transport_cost": {"label": "Transport cost", "override_key": "transport_cost_multiplier"},
    "facility_cost": {"label": "Facility fixed cost", "override_key": "facility_cost_multiplier"},
    "pipeline_capacity": {"label": "Pipeline capacity", "override_key": "corridor_capacity_multiplier"},
    "service_level": {"label": "Service-level requirement", "override_key": "service_level_override"},
}


def _apply_param(base_nd, param_key, multiplier_value, base_service_level=None):
    """Builds the override dict for one parameter perturbation."""
    if param_key == "supply_availability":
        return {"source_availability": {c: s["base_availability"] * multiplier_value
                                         for c, s in base_nd.sources.items()}}
    if param_key == "service_level":
        # multiplier_value here is an absolute service level, not a ratio
        return {"service_level_override": multiplier_value}
    override_key = PARAMETERS[param_key]["override_key"]
    return {override_key: multiplier_value}


def compute_tornado(project, delta_pct=0.20, base_run_result=None):
    base_nd = mb.snapshot_network(project)
    base_result = base_run_result or engine.solve_network(base_nd)
    if base_result["status"] != "optimal":
        return {"error": "Baseline network is not solvable (optimal) - cannot run sensitivity analysis.",
                "base_status": base_result["status"]}
    base_cost = base_result["objective_value"]

    rows = []
    for key, meta in PARAMETERS.items():
        if key == "service_level":
            avg_sl = sum(d["min_service_level"] for d in base_nd.demand_zones.values()) / max(1, len(base_nd.demand_zones))
            low_val, high_val = max(0.0, avg_sl - delta_pct), min(1.0, avg_sl + delta_pct)
        else:
            low_val, high_val = 1 - delta_pct, 1 + delta_pct

        nd_low = mb.apply_overrides(base_nd, _apply_param(base_nd, key, low_val))
        nd_high = mb.apply_overrides(base_nd, _apply_param(base_nd, key, high_val))
        res_low = engine.solve_network(nd_low)
        res_high = engine.solve_network(nd_high)

        cost_low = res_low["objective_value"] if res_low["status"] == "optimal" else None
        cost_high = res_high["objective_value"] if res_high["status"] == "optimal" else None
        deltas = [c - base_cost for c in (cost_low, cost_high) if c is not None]
        impact = max((abs(d) for d in deltas), default=0)

        rows.append({
            "parameter": key, "label": meta["label"],
            "low_value_label": f"-{int(delta_pct*100)}%" if key != "service_level" else f"{low_val:.2f}",
            "high_value_label": f"+{int(delta_pct*100)}%" if key != "service_level" else f"{high_val:.2f}",
            "cost_at_low": cost_low, "cost_at_high": cost_high,
            "cost_delta_low": round(cost_low - base_cost, 2) if cost_low is not None else None,
            "cost_delta_high": round(cost_high - base_cost, 2) if cost_high is not None else None,
            "impact": round(impact, 2),
            "low_status": res_low["status"], "high_status": res_high["status"],
        })

    rows.sort(key=lambda r: r["impact"], reverse=True)
    return {"base_cost": base_cost, "delta_pct": delta_pct, "rows": rows}


def compute_heatmap(project, x_param="supply_availability", y_param="demand_growth",
                     x_values=None, y_values=None):
    x_values = x_values or [0.4, 0.6, 0.8, 1.0]
    y_values = y_values or [1.0, 1.1, 1.2, 1.3]
    base_nd = mb.snapshot_network(project)

    grid = []
    for yv in y_values:
        row = []
        for xv in x_values:
            overrides = {}
            overrides.update(_apply_param(base_nd, x_param, xv))
            overrides.update(_apply_param(base_nd, y_param, yv))
            nd = mb.apply_overrides(base_nd, overrides)
            result = engine.solve_network(nd)
            row.append({
                "x": xv, "y": yv, "status": result["status"],
                "cost": result.get("objective_value"),
                "unmet_demand": result["kpis"]["total_unmet_demand"] if result["status"] == "optimal" else None,
                "fulfilment_pct": result["kpis"]["demand_fulfilment_pct"] if result["status"] == "optimal" else None,
            })
        grid.append(row)

    return {
        "x_param": x_param, "y_param": y_param,
        "x_label": PARAMETERS[x_param]["label"], "y_label": PARAMETERS[y_param]["label"],
        "x_values": x_values, "y_values": y_values, "grid": grid,
    }
