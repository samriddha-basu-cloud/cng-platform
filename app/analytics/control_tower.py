"""Executive Control Tower: KPIs + rule-based alerts computed from a real
multi-period MILP solve (spec sections 34-36, 63, 85). Every number here
is read back off an actual solve result or bottleneck analysis - nothing
is a hard-coded threshold applied to a number that was never computed.
"""
from app.optimization import model_builder as mb, engine
from app.analytics import bottlenecks as bottlenecks_mod

PIPELINE_CRITICAL_UTIL = 0.95
PIPELINE_WARNING_UTIL = 0.85
SINGLE_SOURCE_DEPENDENCY_WARNING = 0.60
LOW_UTILIZATION_INFO = 0.30


def _tier_service_levels(nd, result):
    """Aggregates monthly_allocation (spec section 16's table) by priority
    tier across the whole horizon, and compares against that tier's own
    minimum_service_level (PriorityClass.min_fulfilment_pct) - the actual
    floor configured on the Network tab, not an assumed 95/90/80 split."""
    by_tier = {}
    for row in result.get("monthly_allocation", []):
        tier_name = row["priority"]
        agg = by_tier.setdefault(tier_name, {"demand": 0.0, "allocated": 0.0})
        agg["demand"] += row["demand"]
        agg["allocated"] += row["allocated"]

    tier_meta = {pc["name"]: pc for pc in nd.priority_by_zone.values() if pc}
    out = []
    for name, agg in by_tier.items():
        service_level = agg["allocated"] / agg["demand"] if agg["demand"] else 1.0
        meta = tier_meta.get(name)
        out.append({
            "tier": name,
            "rank": meta["rank"] if meta else None,
            "service_level": round(service_level, 4),
            "target": meta["min_fulfilment_pct"] if meta else None,
            "demand": round(agg["demand"], 4), "allocated": round(agg["allocated"], 4),
            "below_target": bool(meta and service_level < meta["min_fulfilment_pct"] - 1e-6),
        })
    out.sort(key=lambda r: (r["rank"] is None, r["rank"]))
    return out


def _source_dependency(nd, result):
    total = 0.0
    by_source = {}
    for month_flows in (result.get("flows_by_month") or {}).values():
        for f in month_flows.get("source_to_cgs", []):
            by_source[f["from"]] = by_source.get(f["from"], 0.0) + f["flow"]
            total += f["flow"]
    if total <= 0:
        return None
    top_source, top_flow = max(by_source.items(), key=lambda kv: kv[1])
    return {"source": top_source, "share": round(top_flow / total, 4)}


def build_alerts(nd, result, bottleneck_analysis, tier_levels, dependency):
    alerts = []

    for c in bottleneck_analysis["critical"]:
        if c["asset_type"] != "corridor":
            continue
        if c["max_utilization"] >= PIPELINE_CRITICAL_UTIL:
            alerts.append({
                "severity": "CRITICAL", "asset": c["asset_code"], "metric": "pipeline_utilization",
                "value": c["max_utilization"],
                "reason": f"Corridor {c['asset_code']} reaches {c['max_utilization']*100:.0f}% utilization "
                          f"({c['months_binding']} of the months binding).",
                "recommended_action": "Evaluate expansion or an alternate supply path for this corridor.",
            })
        elif c["max_utilization"] >= PIPELINE_WARNING_UTIL:
            alerts.append({
                "severity": "WARNING", "asset": c["asset_code"], "metric": "pipeline_utilization",
                "value": c["max_utilization"],
                "reason": f"Corridor {c['asset_code']} reaches {c['max_utilization']*100:.0f}% utilization.",
                "recommended_action": "Monitor; consider expansion if demand keeps growing.",
            })

    for c in bottleneck_analysis["critical"]:
        if c["asset_type"] not in ("cgs", "station"):
            continue
        if c["max_utilization"] >= PIPELINE_CRITICAL_UTIL:
            alerts.append({
                "severity": "CRITICAL", "asset": c["asset_code"], "metric": f"{c['asset_type']}_utilization",
                "value": c["max_utilization"],
                "reason": f"{c['asset_type'].upper()} {c['asset_code']} reaches {c['max_utilization']*100:.0f}% "
                          f"utilization ({c['months_binding']} months binding).",
                "recommended_action": "Evaluate capacity expansion (see Investment Analysis).",
            })

    for tier in tier_levels:
        if tier["below_target"]:
            alerts.append({
                "severity": "CRITICAL", "asset": tier["tier"], "metric": "tier_service_level",
                "value": tier["service_level"],
                "reason": f"{tier['tier']} service level is {tier['service_level']*100:.1f}%, below its "
                          f"{tier['target']*100:.0f}% floor over the planning horizon.",
                "recommended_action": "Re-run with expansion/storage enabled, or re-prioritize allocation policy.",
            })

    if dependency and dependency["share"] >= SINGLE_SOURCE_DEPENDENCY_WARNING:
        alerts.append({
            "severity": "WARNING", "asset": dependency["source"], "metric": "single_source_dependency",
            "value": dependency["share"],
            "reason": f"{dependency['source']} supplies {dependency['share']*100:.0f}% of total flow across the horizon.",
            "recommended_action": "Diversify supply or increase contracted volume at a secondary source.",
        })

    open_cgs = {f["code"] for f in result["facilities"]["cgs"] if f["open"]}
    open_stations = {f["code"] for f in result["facilities"]["stations"] if f["open"]}
    low_util_seen = set()
    for r in bottleneck_analysis["records"]:
        if r["asset_type"] not in ("cgs", "station"):
            continue
        key = (r["asset_type"], r["asset_code"])
        if key in low_util_seen:
            continue
        asset_open = r["asset_code"] in (open_cgs if r["asset_type"] == "cgs" else open_stations)
        if asset_open and r["capacity"] > 0:
            same_asset_util = [rr["utilization"] for rr in bottleneck_analysis["records"]
                                if rr["asset_type"] == r["asset_type"] and rr["asset_code"] == r["asset_code"]]
            if same_asset_util and max(same_asset_util) < LOW_UTILIZATION_INFO:
                low_util_seen.add(key)
                alerts.append({
                    "severity": "INFO", "asset": r["asset_code"], "metric": f"{r['asset_type']}_low_utilization",
                    "value": round(max(same_asset_util), 4),
                    "reason": f"{r['asset_type'].upper()} {r['asset_code']} never exceeds "
                              f"{max(same_asset_util)*100:.0f}% utilization across the horizon.",
                    "recommended_action": "Additional demand could be routed here before expanding elsewhere.",
                })

    kpis = result.get("kpis", {})
    if kpis.get("months_with_shortage", 0) > 0:
        alerts.append({
            "severity": "CRITICAL" if kpis.get("overall_service_level", 1) < 0.95 else "WARNING",
            "asset": "network", "metric": "months_with_shortage", "value": kpis.get("months_with_shortage"),
            "reason": f"{kpis.get('months_with_shortage')} of {kpis.get('horizon_months')} months have unmet demand "
                      f"(overall service level {kpis.get('overall_service_level', 0)*100:.1f}%).",
            "recommended_action": "Review Investment Analysis for the minimum expansion needed to close the gap.",
        })

    severity_rank = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(key=lambda a: severity_rank.get(a["severity"], 3))
    return alerts


def build_control_tower(project) -> dict:
    nd = mb.snapshot_network(project)
    result = engine.solve_multiperiod(nd)
    if result["status"] != "optimal":
        return {"status": result["status"], "diagnostics": result.get("diagnostics"),
                "kpis": {}, "alerts": [], "critical_bottlenecks": [], "tier_service_levels": []}

    bottleneck_analysis = bottlenecks_mod.analyze_bottlenecks(nd, result)
    tier_levels = _tier_service_levels(nd, result)
    dependency = _source_dependency(nd, result)
    alerts = build_alerts(nd, result, bottleneck_analysis, tier_levels, dependency)

    kpis = result.get("kpis", {})
    total_demand = kpis.get("total_demand", 0)
    total_supply_available = sum(row["supply_available"] for row in result["monthly_breakdown"]) / max(1, len(result["monthly_breakdown"]))

    return {
        "status": "optimal",
        "kpis": {
            "total_demand": kpis.get("total_demand"),
            "total_shortage": kpis.get("total_shortage"),
            "overall_service_level": kpis.get("overall_service_level"),
            "months_with_shortage": kpis.get("months_with_shortage"),
            "horizon_months": kpis.get("horizon_months"),
            "total_cost": result.get("objective_value"),
            "shortage_penalty_cost": result.get("cost_breakdown", {}).get("shortage_penalty"),
            "expansion_capex": result.get("expansion_capex"),
            "cgs_open_count": kpis.get("cgs_open_count"),
            "station_open_count": kpis.get("station_open_count"),
            "critical_bottleneck_count": sum(1 for c in bottleneck_analysis["critical"] if c["severity"] == "HIGH"),
            "avg_monthly_supply_available": round(total_supply_available, 4),
        },
        "tier_service_levels": tier_levels,
        "source_dependency": dependency,
        "alerts": alerts,
        "critical_bottlenecks": bottleneck_analysis["critical"][:10],
    }
