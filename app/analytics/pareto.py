"""
Cost vs. service-level Pareto frontier (spec section 24). For each target
service level, solves the model with that level applied uniformly as the
minimum service level across every demand zone, and records the minimum
achievable cost. Also identifies the cost-optimal, resilience-optimal
(highest feasible service level), and a balanced knee point.
"""
from app.optimization import model_builder as mb, engine


def compute_pareto(project, service_levels=None):
    service_levels = service_levels or [0.90, 0.92, 0.94, 0.96, 0.98, 1.00]
    base_nd = mb.snapshot_network(project)

    points = []
    for sl in service_levels:
        nd = mb.apply_overrides(base_nd, {"service_level_override": sl})
        result = engine.solve_network(nd)
        points.append({
            "service_level": sl,
            "status": result["status"],
            "cost": result.get("objective_value"),
            "unmet_demand": result["kpis"]["total_unmet_demand"] if result["status"] == "optimal" else None,
        })

    feasible = [p for p in points if p["status"] == "optimal"]
    cost_optimal = min(feasible, key=lambda p: p["cost"]) if feasible else None
    resilience_optimal = max(feasible, key=lambda p: p["service_level"]) if feasible else None

    balanced = None
    if len(feasible) >= 2:
        costs = [p["cost"] for p in feasible]
        min_c, max_c = min(costs), max(costs)
        span = max_c - min_c or 1
        # knee point: normalize cost and service level to 0-1, pick the point
        # maximizing (service_level - normalized_cost), a simple, explainable
        # balance rather than a curvature-based knee detector.
        def score(p):
            norm_cost = (p["cost"] - min_c) / span
            return p["service_level"] - norm_cost
        balanced = max(feasible, key=score)

    return {
        "points": points,
        "cost_optimal_point": cost_optimal,
        "resilience_optimal_point": resilience_optimal,
        "balanced_point": balanced,
    }
