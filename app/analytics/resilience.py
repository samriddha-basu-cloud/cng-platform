"""
Resilience score (spec section 21). Deliberately NOT a black box: every
component is computed from real solve results and the weights are
returned alongside the score so the UI can show the breakdown, and a
caller can pass different weights entirely.

Default weights mirror the spec's example:
  40% Service Continuity   - probability-weighted fulfilment across default scenarios
  25% Supply Diversification - 1 - HHI concentration of source capacity shares
  20% Capacity Slack        - average unused capacity fraction across open facilities (normal scenario)
  15% Network Redundancy    - average number of viable station paths per demand zone, normalized
"""
from app.optimization import model_builder as mb, engine
from app.services.scenario_service import scenario_to_overrides

DEFAULT_WEIGHTS = {
    "service_continuity": 0.40,
    "supply_diversification": 0.25,
    "capacity_slack": 0.20,
    "network_redundancy": 0.15,
}


def _service_continuity(project, base_nd) -> float:
    scenarios = [s for s in project.scenarios if s.is_default] or project.scenarios
    if not scenarios:
        result = engine.solve_network(base_nd)
        return result["kpis"]["demand_fulfilment_pct"] if result["status"] == "optimal" else 0.0
    total_prob = sum(s.probability or 0 for s in scenarios) or 1.0
    weighted = 0.0
    for s in scenarios:
        nd = mb.apply_overrides(base_nd, scenario_to_overrides(s))
        result = engine.solve_network(nd)
        fulfilment = result["kpis"]["demand_fulfilment_pct"] if result["status"] == "optimal" else 0.0
        weighted += (s.probability or 0) / total_prob * fulfilment
    return weighted


def _supply_diversification(base_nd) -> float:
    caps = [s["max_capacity"] for s in base_nd.sources.values() if s["max_capacity"] > 0]
    total = sum(caps)
    if total <= 0 or not caps:
        return 0.0
    hhi = sum((c / total) ** 2 for c in caps)  # 1/n (diversified) .. 1.0 (single source)
    n = len(caps)
    hhi_min = 1.0 / n
    # normalize so perfectly even split across n sources -> 1.0, single source -> 0.0
    if n == 1:
        return 0.0
    return max(0.0, min(1.0, (1 - hhi) / (1 - hhi_min)))


def _capacity_slack(base_nd) -> float:
    result = engine.solve_network(base_nd)
    if result["status"] != "optimal":
        return 0.0
    utils = [f["utilization"] for f in result["facilities"]["cgs"] if f["open"]] + \
            [f["utilization"] for f in result["facilities"]["stations"] if f["open"]]
    if not utils:
        return 0.0
    avg_util = sum(utils) / len(utils)
    return max(0.0, 1 - avg_util)


def _network_redundancy(base_nd) -> float:
    from collections import defaultdict
    paths_per_zone = defaultdict(int)
    for (k, d) in base_nd.kd_arcs:
        paths_per_zone[d] += 1
    if not base_nd.demand_zones:
        return 0.0
    counts = [paths_per_zone.get(d, 0) for d in base_nd.demand_zones]
    avg_paths = sum(counts) / len(counts)
    # normalize against a "3 viable stations per zone" reference ceiling
    return max(0.0, min(1.0, avg_paths / 3.0))


def compute_resilience(project, weights: dict = None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    base_nd = mb.snapshot_network(project)

    components = {
        "service_continuity": round(_service_continuity(project, base_nd), 4),
        "supply_diversification": round(_supply_diversification(base_nd), 4),
        "capacity_slack": round(_capacity_slack(base_nd), 4),
        "network_redundancy": round(_network_redundancy(base_nd), 4),
    }
    score = sum(components[k] * weights.get(k, 0) for k in components) * 100
    return {
        "score": round(score, 1),
        "weights": weights,
        "components": components,
        "component_labels": {
            "service_continuity": "Service Continuity",
            "supply_diversification": "Supply Diversification",
            "capacity_slack": "Capacity Slack",
            "network_redundancy": "Network Redundancy",
        },
    }
