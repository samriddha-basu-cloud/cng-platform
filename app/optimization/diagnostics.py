"""
When a solve comes back infeasible, a bare "Optimization failed" is
useless. This module runs a handful of cheap, explainable checks against
the same NetworkData snapshot the optimizer used, and returns human
-readable causes + suggestions (spec section 34). This is a heuristic
screen, not a formal IIS/conflict-refiner - it flags the classic causes
(insufficient supply, unreachable demand, impossible service level) that
account for the overwhelming majority of infeasible network-design
instances.
"""
from app.optimization import model_builder as mb


def diagnose(nd: mb.NetworkData, month: int = None) -> dict:
    """month: when given (spec section 76), evaluates supply/demand totals at that
    specific month of the time-indexed model (nd.sources[s]["monthly_availability"][t]
    / nd.demand_zones[d]["monthly_demand"][t]) instead of the flat single-period
    scalars, and every finding is labeled with which month it applies to."""
    findings = []

    if month is not None:
        total_supply = sum(s["monthly_availability"].get(month, s["base_availability"] * s["max_capacity"])
                            for s in nd.sources.values())
        total_demand = sum(d["monthly_demand"].get(month, d["base_demand"]) for d in nd.demand_zones.values())
    else:
        total_supply = sum(s["base_availability"] * s["max_capacity"] for s in nd.sources.values())
        total_demand = sum(d["base_demand"] for d in nd.demand_zones.values())
    if total_supply < total_demand:
        findings.append({
            "cause": "Insufficient total supply",
            "month": month,
            "detail": f"Total available supply ({total_supply:,.1f}) is less than total demand ({total_demand:,.1f})"
                      f"{f' in month {month}' if month else ''}.",
            "suggestions": ["Increase source availability/capacity", "Add another source",
                             "Lower demand assumptions", "Relax minimum service-level requirements"],
        })

    # zones with no reachable station at all
    reachable_zones = {d for (_, d) in nd.kd_arcs}
    for d, info in nd.demand_zones.items():
        if d not in reachable_zones:
            findings.append({
                "cause": "Disconnected demand zone",
                "detail": f"Demand zone '{d}' has no CNG station within its service radius - it cannot be served at all.",
                "suggestions": [f"Add a station within range of {d}", "Increase the service radius of a nearby station"],
                "affected_zone": d,
            })

    # CGS with no inbound corridor
    fed_cgs = {j for (_, j) in [(c["origin"], c["destination"]) for c in nd.corridors.values()]}
    for j in nd.cgs:
        if j not in fed_cgs:
            findings.append({
                "cause": "Unfed CGS",
                "detail": f"CGS '{j}' has no inbound corridor from any source.",
                "suggestions": [f"Add a corridor into {j}"],
                "affected_facility": j,
            })

    # aggregate minimum-service-level feasibility (necessary, not sufficient, condition)
    if month is not None:
        min_required = sum(d["monthly_demand"].get(month, d["base_demand"]) * d["min_service_level"]
                            for d in nd.demand_zones.values())
    else:
        min_required = sum(d["base_demand"] * d["min_service_level"] for d in nd.demand_zones.values())
    if min_required > total_supply:
        findings.append({
            "cause": "Minimum service-level requirement exceeds available supply",
            "detail": f"Meeting every zone's minimum service level would require {min_required:,.1f} units, "
                      f"more than the {total_supply:,.1f} available.",
            "suggestions": ["Lower minimum service-level requirements for lower-priority zones",
                             "Increase supply", "Add buffer/virtual-pipeline capacity"],
        })

    # capacity bottleneck: total CGS or station capacity below total demand
    total_cgs_cap = sum(c["capacity"] for c in nd.cgs.values())
    total_station_cap = sum(s["capacity"] for s in nd.stations.values())
    if total_cgs_cap < total_demand:
        findings.append({
            "cause": "Insufficient total CGS capacity",
            "detail": f"Combined CGS capacity ({total_cgs_cap:,.1f}) is less than total demand ({total_demand:,.1f}).",
            "suggestions": ["Expand an existing CGS", "Open a candidate CGS", "Add more CGS"],
        })
    if total_station_cap < total_demand:
        findings.append({
            "cause": "Insufficient total CNG station capacity",
            "detail": f"Combined station capacity ({total_station_cap:,.1f}) is less than total demand ({total_demand:,.1f}).",
            "suggestions": ["Expand an existing station", "Open a candidate station", "Add more stations"],
        })

    if not findings:
        findings.append({
            "cause": "Unclear - no single dominant cause detected",
            "detail": "Aggregate supply, capacity, and connectivity all look sufficient in isolation; "
                      "the infeasibility likely comes from how per-arc corridor capacities or "
                      "per-zone minimum service levels interact.",
            "suggestions": ["Try relaxing minimum service levels zone by zone",
                             "Check individual corridor capacities against the sources feeding them",
                             "Run network validation for structural issues"],
        })

    return {"is_infeasible": True, "findings": findings}


def diagnose_multiperiod(nd: mb.NetworkData, months: list) -> dict:
    """For the time-indexed model: runs diagnose() per month and returns the
    per-month results plus which month(s) look tightest, so an infeasible
    12-month solve names the actual bottleneck month(s) rather than a single
    flat (and therefore misleading) aggregate diagnosis."""
    per_month = {}
    worst_month, worst_gap = None, None
    for t in months:
        d = diagnose(nd, month=t)
        per_month[t] = d
        supply = sum(s["monthly_availability"].get(t, 0) for s in nd.sources.values())
        demand = sum(z["monthly_demand"].get(t, 0) for z in nd.demand_zones.values())
        gap = demand - supply
        if worst_gap is None or gap > worst_gap:
            worst_gap, worst_month = gap, t
    return {"is_infeasible": True, "worst_month": worst_month, "per_month": per_month}
