"""
Time-series simulation (spec section 37 / 19). For each period
T0..Tn, applies each demand zone's own growth_rate compounded from its
base_demand, plus any shocks scheduled for that period, and solves a
deterministic snapshot.

Simplification, stated plainly: this is a sequence of independent
per-period deterministic solves, not a single multi-period MILP with
inventory/storage carryover between periods (that full formulation -
the I_t variable in the reference project's spec - is a larger, separate
piece of work). Each period's numbers are still real optimizer output;
what's simplified is that periods don't share inventory state.
"""
from app.optimization import model_builder as mb, engine


def run_timeline(project, num_periods: int, shocks: dict = None):
    """shocks: {period_index: overrides_dict} - e.g. {2: {"demand_multiplier": 1.25}}"""
    shocks = shocks or {}
    base_nd = mb.snapshot_network(project)

    periods = []
    for t in range(num_periods):
        growth_overrides = {
            "demand_zone_multiplier": {
                code: (1 + info["growth_rate"]) ** t for code, info in base_nd.demand_zones.items()
            }
        }
        overrides = dict(growth_overrides)
        if t in shocks:
            shock = shocks[t]
            # merge demand_zone_multiplier if the shock also specifies one
            if "demand_multiplier" in shock:
                overrides["demand_multiplier"] = shock["demand_multiplier"]
            for k, v in shock.items():
                if k != "demand_multiplier":
                    overrides[k] = v

        nd = mb.apply_overrides(base_nd, overrides)
        result = engine.solve_network(nd)

        row = {
            "period": t,
            "status": result["status"],
            "shock_applied": shocks.get(t, {}),
        }
        if result["status"] == "optimal":
            row.update({
                "total_cost": result["objective_value"],
                "total_demand": result["kpis"]["total_demand"],
                "total_supply_available": result["kpis"]["total_supply_available"],
                "unmet_demand": result["kpis"]["total_unmet_demand"],
                "fulfilment_pct": result["kpis"]["demand_fulfilment_pct"],
                "avg_cgs_utilization": result["kpis"]["avg_cgs_utilization"],
                "avg_station_utilization": result["kpis"]["avg_station_utilization"],
            })
        periods.append(row)

    return {"num_periods": num_periods, "periods": periods}
