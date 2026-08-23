from flask import Blueprint, jsonify, request
from app.data import repo
from app.optimization import model_builder as mb, engine, diagnostics
from app.services.scenario_service import scenario_to_overrides
from app.utils.validation import validate_network
from app.utils.usage_logger import log_usage

optimize_bp = Blueprint("optimize", __name__, url_prefix="/api/optimize")
runs_bp = Blueprint("runs", __name__, url_prefix="/api/runs")


def _blocking_errors(project):
    issues = validate_network(project)
    return [i for i in issues if i["level"] == "error"]


@optimize_bp.post("/<int:project_id>")
def optimize_deterministic(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    scenario_id = data.get("scenario_id")
    overrides = data.get("overrides", {}) or {}
    penalty_base = data.get("penalty_base", mb.DEFAULT_UNMET_PENALTY_BASE)

    scenario = None
    if scenario_id:
        scenario = next((s for s in project.scenarios if s.id == scenario_id), None)
        if scenario is None:
            return jsonify({"error": "Scenario not found in this project."}), 404
        overrides = {**scenario_to_overrides(scenario), **overrides}

    nd = mb.snapshot_network(project)
    nd = mb.apply_overrides(nd, overrides)
    result = engine.solve_network(nd, penalty_base=penalty_base)

    if result["status"] == "infeasible":
        result["diagnostics"] = diagnostics.diagnose(nd)

    run = repo.save_run(project_id, scenario_id, "deterministic", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    if result["status"] == "optimal":
        project.status = "Optimized"
        repo.save_project(project)
    log_usage("optimize_deterministic", project_id, result.get("status"))
    return jsonify(result)


@optimize_bp.post("/<int:project_id>/compare-scenarios")
def compare_scenarios(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    scenarios = [s for s in project.scenarios if s.is_default] or project.scenarios
    if not scenarios:
        return jsonify({"error": "No scenarios defined for this project."}), 400

    base_nd = mb.snapshot_network(project)
    comparison = []
    for sc in scenarios:
        nd = mb.apply_overrides(base_nd, scenario_to_overrides(sc))
        result = engine.solve_network(nd)
        row = {
            "scenario_id": sc.id, "scenario_name": sc.name, "probability": sc.probability,
            "status": result["status"],
        }
        if result["status"] == "optimal":
            row.update({
                "total_cost": result["objective_value"],
                "cost_breakdown": result["cost_breakdown"],
                "fulfilment_pct": result["kpis"]["demand_fulfilment_pct"],
                "unmet_demand": result["kpis"]["total_unmet_demand"],
                "avg_cgs_utilization": result["kpis"]["avg_cgs_utilization"],
                "avg_station_utilization": result["kpis"]["avg_station_utilization"],
            })
            repo.save_run(project_id, sc.id, "deterministic", result.get("solver_name"), result)
        else:
            row["diagnostics"] = diagnostics.diagnose(nd)["findings"] if result["status"] == "infeasible" else None
        comparison.append(row)

    log_usage("scenario_compare", project_id, f"{len(comparison)} scenarios")
    return jsonify({"comparison": comparison})


@optimize_bp.post("/<int:project_id>/stochastic")
def optimize_stochastic(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    penalty_base = data.get("penalty_base", mb.DEFAULT_UNMET_PENALTY_BASE)

    scenarios = [s for s in project.scenarios if s.is_default] or project.scenarios
    if not scenarios:
        return jsonify({"error": "No scenarios defined for this project."}), 400

    total_prob = sum(s.probability or 0 for s in scenarios)
    if total_prob <= 0:
        return jsonify({"error": "Scenario probabilities must sum to a positive value."}), 400
    probabilities = {s.name: (s.probability or 0) / total_prob for s in scenarios}

    base_nd = mb.snapshot_network(project)
    scenario_nds = {s.name: mb.apply_overrides(base_nd, scenario_to_overrides(s)) for s in scenarios}

    result = engine.solve_stochastic(base_nd, scenario_nds, probabilities, penalty_base=penalty_base)
    if result.get("status") == "infeasible":
        tightest = min(scenario_nds.values(),
                        key=lambda nd: sum(s["base_availability"] * s["max_capacity"] for s in nd.sources.values()))
        result["diagnostics"] = diagnostics.diagnose(tightest)
        result["diagnostics"]["note"] = ("Diagnosed against the scenario with the least available supply, since "
                                          "facility decisions are shared across all scenarios in a stochastic model.")
    run = repo.save_run(project_id, None, "stochastic", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    log_usage("optimize_stochastic", project_id, result.get("status"))
    return jsonify(result)


@optimize_bp.post("/<int:project_id>/robust")
def optimize_robust(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode", "balanced")
    lo, hi = data.get("supply_range", [0.6, 1.0])

    posture_quantile = {"conservative": 0.0, "balanced": 0.5, "aggressive": 1.0}
    if mode not in posture_quantile:
        return jsonify({"error": f"mode must be one of {list(posture_quantile.keys())}"}), 400
    factor = lo + (hi - lo) * posture_quantile[mode]

    base_nd = mb.snapshot_network(project)
    overrides = {"source_availability": {code: min(factor, s["base_availability"]) for code, s in base_nd.sources.items()}}
    nd = mb.apply_overrides(base_nd, overrides)
    result = engine.solve_network(nd)
    result["robust_mode"] = mode
    result["applied_availability_factor"] = round(factor, 4)
    result["supply_range"] = [lo, hi]
    if result["status"] == "infeasible":
        result["diagnostics"] = diagnostics.diagnose(nd)

    run = repo.save_run(project_id, None, "robust", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    log_usage("optimize_robust", project_id, f"{mode}:{result.get('status')}")
    return jsonify(result)


@runs_bp.get("/<int:project_id>")
def list_runs(project_id):
    repo.get_project(project_id)
    runs = repo.list_runs(project_id)
    return jsonify([{k: v for k, v in r.items() if k != "result"} for r in runs])


@runs_bp.get("/detail/<int:run_id>")
def run_detail(run_id):
    run = repo.get_run(run_id)
    payload = dict(run.get("result") or {})
    payload["run_meta"] = {k: v for k, v in run.items() if k != "result"}
    return jsonify(payload)
