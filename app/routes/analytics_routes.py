from flask import Blueprint, jsonify, request
from app.data import repo
from app.optimization import model_builder as mb, engine
from app.analytics import resilience as resilience_mod
from app.analytics import pareto as pareto_mod
from app.analytics import sensitivity as sensitivity_mod
from app.analytics import bottlenecks as bottlenecks_mod
from app.analytics import control_tower as control_tower_mod
from app.analytics import forecast_actual as forecast_actual_mod
from app.analytics.recommendations import generate_recommendations
from app.services.scenario_service import build_preset_overrides
from app.utils.validation import validate_network

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


def _blocking_errors(project):
    return [i for i in validate_network(project) if i["level"] == "error"]


@analytics_bp.get("/<int:project_id>/resilience")
def resilience(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    weights = None
    for k in resilience_mod.DEFAULT_WEIGHTS:
        v = request.args.get(k)
        if v is not None:
            weights = weights or dict(resilience_mod.DEFAULT_WEIGHTS)
            weights[k] = float(v)
    return jsonify(resilience_mod.compute_resilience(project, weights))


@analytics_bp.get("/<int:project_id>/pareto")
def pareto(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    return jsonify(pareto_mod.compute_pareto(project))


@analytics_bp.get("/<int:project_id>/tornado")
def tornado(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    delta = float(request.args.get("delta_pct", 0.20))
    return jsonify(sensitivity_mod.compute_tornado(project, delta_pct=delta))


@analytics_bp.get("/<int:project_id>/heatmap")
def heatmap(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    x_param = request.args.get("x_param", "supply_availability")
    y_param = request.args.get("y_param", "demand_growth")
    return jsonify(sensitivity_mod.compute_heatmap(project, x_param=x_param, y_param=y_param))


@analytics_bp.get("/<int:project_id>/recommendations")
def recommendations(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    base_nd = mb.snapshot_network(project)
    base_result = engine.solve_network(base_nd)

    severe_result = None
    try:
        overrides = build_preset_overrides(project, "shortage_40")
        severe_nd = mb.apply_overrides(base_nd, overrides)
        r = engine.solve_network(severe_nd)
        if r["status"] == "optimal":
            severe_result = r
    except Exception:
        severe_result = None

    recs = generate_recommendations(base_result, severe_result, base_nd)
    return jsonify({"recommendations": recs, "base_status": base_result["status"]})


@analytics_bp.get("/<int:project_id>/bottlenecks")
def bottlenecks(project_id):
    """Binding-constraint / bottleneck analysis for the time-indexed
    multi-period MILP (spec section 19), plus finite-difference marginal
    value estimates for the top few (spec section 20) unless
    ?marginal=false is passed (each one costs an extra full MILP resolve)."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    nd = mb.snapshot_network(project)
    result = engine.solve_multiperiod(nd)
    if result["status"] != "optimal":
        return jsonify({"error": f"Multi-period solve was not optimal (status={result['status']}).",
                         "diagnostics": result.get("diagnostics")}), 400

    analysis = bottlenecks_mod.analyze_bottlenecks(nd, result)
    payload = {"critical": analysis["critical"], "records": analysis["records"]}
    if request.args.get("marginal", "true").lower() != "false":
        payload["marginal_values"] = bottlenecks_mod.marginal_value_analysis(nd, result, top_n=5)
    return jsonify(payload)


@analytics_bp.get("/<int:project_id>/control-tower")
def control_tower(project_id):
    """Executive KPIs + rule-based alerts + top bottlenecks, all computed
    from a real multi-period solve (spec sections 34-36, 63, 85) - never a
    static/hard-coded number."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    return jsonify(control_tower_mod.build_control_tower(project))


@analytics_bp.get("/<int:project_id>/forecast-vs-actual")
def forecast_vs_actual(project_id):
    """Forecast vs Actual (spec section 31): compares each demand zone's
    planning forecast against its recorded actual_demand. Read-only -
    set actuals via PATCH /api/network/<pid>/demand/<id> {"actual_demand": {"3": 142}}."""
    project = repo.get_project(project_id)
    nd = mb.snapshot_network(project)
    return jsonify(forecast_actual_mod.compute_forecast_vs_actual(nd))


@analytics_bp.get("/<int:project_id>/summary")
def dashboard_summary(project_id):
    """Everything the final one-screen dashboard needs (spec section 59),
    assembled from real solves - not stored/cached fake numbers."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    base_nd = mb.snapshot_network(project)
    normal_result = engine.solve_network(base_nd)

    severe_result = None
    try:
        overrides = build_preset_overrides(project, "shortage_40")
        severe_nd = mb.apply_overrides(base_nd, overrides)
        r = engine.solve_network(severe_nd)
        if r["status"] == "optimal":
            severe_result = r
    except Exception:
        pass

    res = resilience_mod.compute_resilience(project)
    recs = generate_recommendations(normal_result, severe_result, base_nd)

    total_investment = None
    if normal_result["status"] == "optimal":
        total_investment = normal_result["cost_breakdown"]["infrastructure"]

    return jsonify({
        "normal_scenario": {
            "status": normal_result["status"],
            "total_cost": normal_result.get("objective_value"),
            "service_level_pct": normal_result.get("kpis", {}).get("demand_fulfilment_pct"),
        },
        "severe_scenario": {
            "status": severe_result["status"] if severe_result else "not_solved",
            "total_cost": severe_result.get("objective_value") if severe_result else None,
            "service_level_pct": severe_result.get("kpis", {}).get("demand_fulfilment_pct") if severe_result else None,
        },
        "resilience_score": res["score"],
        "total_investment": total_investment,
        "unmet_demand": normal_result.get("kpis", {}).get("total_unmet_demand"),
        "critical_bottlenecks": sum(
            1 for f in (normal_result.get("facilities", {}).get("cgs", []) + normal_result.get("facilities", {}).get("stations", []))
            if f.get("utilization", 0) >= 1.0
        ) if normal_result["status"] == "optimal" else None,
        "top_recommendations": recs[:5],
    })
