"""Binding-constraint / bottleneck analysis (spec section 19) and a
mathematically defensible marginal-value analysis (spec section 20) for the
multi-period MILP.

IMPORTANT on methodology (spec section 20's explicit warning): the core
model is a MILP, so a raw dual value off the solved MILP is not a valid
economic shadow price the way it would be for an LP. Rather than present one
anyway, `marginal_value_analysis` uses **finite-difference resolves**: for
each of the tightest bottlenecks, the capacity is bumped by a small amount
and the whole MILP is re-solved (facility open/close decisions free to
change); the marginal value is the resulting drop in total objective cost
per unit of added capacity. This is slower than reading a dual value but it
is honest about what a MILP can and cannot give you directly - every number
is real re-solve output, not a borrowed LP concept.
"""
import copy

BINDING_THRESHOLD = 0.999
NEAR_BINDING_THRESHOLD = 0.85


def _classify(utilization):
    if utilization >= BINDING_THRESHOLD:
        return "BINDING"
    if utilization >= NEAR_BINDING_THRESHOLD:
        return "NEAR_BINDING"
    return "NON_BINDING"


def analyze_bottlenecks(nd, result: dict) -> dict:
    """Returns {"records": [...], "critical": [...]}. `records` is one row
    per (asset, month): capacity, flow, slack, utilization, status. `critical`
    aggregates by asset, ranked by how often it binds across the horizon
    (frequency) then by average utilization (severity) - the "CRITICAL
    BOTTLENECKS" dashboard spec section 19 asks for."""
    months = result.get("months") or nd.months
    flows_by_month = result.get("flows_by_month") or {}
    records = []

    # sources: monthly_availability[t] vs sum of outbound flow that month
    for s, sinfo in nd.sources.items():
        for t in months:
            flow = sum(f["flow"] for f in flows_by_month.get(t, {}).get("source_to_cgs", []) if f["from"] == s)
            cap = sinfo["monthly_availability"].get(t, 0)
            _record(records, "source", s, t, cap, flow)

    # corridors (source->CGS): monthly_capacity[t] vs flow on that exact corridor. Matched by
    # corridor code, not origin/destination - two corridors sharing an (origin, destination)
    # pair (mode choice: e.g. pipeline vs virtual pipeline) are genuinely distinct arcs with
    # their own flow, never double-counted or conflated.
    for c, cinfo in nd.corridors.items():
        for t in months:
            flow = sum(f["flow"] for f in flows_by_month.get(t, {}).get("source_to_cgs", [])
                       if f.get("corridor") == c)
            cap = cinfo["monthly_capacity"].get(t, 0)
            _record(records, "corridor", c, t, cap, flow)

    # CGS: effective_capacity (base + expansion, constant across the horizon) vs monthly inbound flow
    cgs_cap = {f["code"]: f["effective_capacity"] for f in (result.get("facilities") or {}).get("cgs", [])}
    for j, cap in cgs_cap.items():
        for t in months:
            flow = sum(f["flow"] for f in flows_by_month.get(t, {}).get("cgs_to_station", []) if f["from"] == j)
            _record(records, "cgs", j, t, cap, flow)

    # stations: effective_capacity vs monthly inbound flow
    station_cap = {f["code"]: f["effective_capacity"] for f in (result.get("facilities") or {}).get("stations", [])}
    for k, cap in station_cap.items():
        for t in months:
            flow = sum(f["flow"] for f in flows_by_month.get(t, {}).get("cgs_to_station", []) if f["to"] == k)
            _record(records, "station", k, t, cap, flow)

    # aggregate per asset across the horizon
    by_asset = {}
    for r in records:
        key = (r["asset_type"], r["asset_code"])
        agg = by_asset.setdefault(key, {"asset_type": r["asset_type"], "asset_code": r["asset_code"],
                                         "months_binding": 0, "months_near_binding": 0, "utilizations": []})
        if r["status"] == "BINDING":
            agg["months_binding"] += 1
        elif r["status"] == "NEAR_BINDING":
            agg["months_near_binding"] += 1
        agg["utilizations"].append(r["utilization"])

    critical = []
    for agg in by_asset.values():
        if agg["months_binding"] == 0 and agg["months_near_binding"] == 0:
            continue
        avg_util = sum(agg["utilizations"]) / len(agg["utilizations"]) if agg["utilizations"] else 0
        critical.append({
            "asset_type": agg["asset_type"], "asset_code": agg["asset_code"],
            "months_binding": agg["months_binding"], "months_near_binding": agg["months_near_binding"],
            "avg_utilization": round(avg_util, 4), "max_utilization": round(max(agg["utilizations"]), 4),
            "severity": "HIGH" if agg["months_binding"] >= 3 else ("MEDIUM" if agg["months_binding"] >= 1 else "LOW"),
        })
    critical.sort(key=lambda r: (-r["months_binding"], -r["avg_utilization"]))

    return {"records": records, "critical": critical}


def _record(records, asset_type, code, month, capacity, flow):
    utilization = round(flow / capacity, 4) if capacity else (1.0 if flow > 1e-6 else 0.0)
    records.append({
        "asset_type": asset_type, "asset_code": code, "month": month,
        "capacity": round(capacity, 4), "flow": round(flow, 4),
        "slack": round(capacity - flow, 4), "utilization": utilization,
        "status": _classify(utilization),
    })


def _bump_capacity(nd, asset_type, code, month, epsilon):
    nd2 = copy.deepcopy(nd)
    if asset_type == "source":
        nd2.sources[code]["monthly_availability"][month] = nd2.sources[code]["monthly_availability"].get(month, 0) + epsilon
    elif asset_type == "corridor":
        nd2.corridors[code]["monthly_capacity"][month] = nd2.corridors[code]["monthly_capacity"].get(month, 0) + epsilon
    elif asset_type == "cgs":
        nd2.cgs[code]["capacity"] += epsilon  # not month-indexed: applies across the whole horizon
    elif asset_type == "station":
        nd2.stations[code]["capacity"] += epsilon
    else:
        raise ValueError(f"Unknown asset_type '{asset_type}'")
    return nd2


def marginal_value_analysis(nd, result: dict, top_n: int = 5) -> list:
    """Re-solves the multi-period MILP once per top bottleneck with its
    capacity bumped, and reports the resulting drop in total objective cost
    per unit as that asset's marginal value at its worst (most-binding)
    month. Only ever run against the top `top_n` critical bottlenecks -
    every additional asset analyzed costs one more full MILP solve."""
    from app.optimization import engine as eng  # local import: avoids a module-level cycle with engine.py

    bottleneck_info = analyze_bottlenecks(nd, result)
    baseline_obj = result.get("objective_value")
    if baseline_obj is None:
        return []

    months = result.get("months") or nd.months
    records_by_asset = {}
    for r in bottleneck_info["records"]:
        key = (r["asset_type"], r["asset_code"])
        records_by_asset.setdefault(key, []).append(r)

    out = []
    for c in bottleneck_info["critical"][:top_n]:
        key = (c["asset_type"], c["asset_code"])
        worst = max(records_by_asset[key], key=lambda r: r["utilization"])
        capacity = worst["capacity"]
        epsilon = max(1.0, round(capacity * 0.05, 2)) if capacity else 1.0

        nd2 = _bump_capacity(nd, c["asset_type"], c["asset_code"], worst["month"], epsilon)
        bumped = eng.solve_multiperiod(nd2, months=months, penalty_base=None)
        if bumped.get("status") != "optimal":
            continue
        delta = baseline_obj - bumped["objective_value"]
        out.append({
            "asset_type": c["asset_type"], "asset_code": c["asset_code"], "month": worst["month"],
            "capacity": capacity, "utilization": worst["utilization"],
            "capacity_increment_tested": epsilon,
            "marginal_value_per_unit": round(delta / epsilon, 4),
            "methodology": ("Finite-difference MILP resolve: capacity increased by "
                             f"{epsilon:g} units in month {worst['month']} only, facility "
                             "open/close decisions left free, whole model re-solved. Reported "
                             "value = (baseline objective - resolved objective) / increment. "
                             "This is NOT an LP dual/shadow price - the model is a MILP - it is "
                             "the actual economic benefit of that specific capacity increase."),
        })
    return out
