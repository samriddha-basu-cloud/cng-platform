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
    penalty_base = data.get("penalty_base")  # None -> engine falls back to the project's unmet_demand_penalty_base

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


@optimize_bp.post("/<int:project_id>/multiperiod")
def optimize_multiperiod(project_id):
    """Genuinely time-indexed 12-month (or project.monthly_horizon-month) MILP -
    see app/optimization/model_builder.py::build_time_indexed_model. Not a loop of
    independent single-period solves (that's app/simulation/timeline.py)."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    scenario_id = data.get("scenario_id")
    overrides = data.get("overrides", {}) or {}
    penalty_base = data.get("penalty_base")

    scenario = None
    if scenario_id:
        scenario = next((s for s in project.scenarios if s.id == scenario_id), None)
        if scenario is None:
            return jsonify({"error": "Scenario not found in this project."}), 404
        overrides = {**scenario_to_overrides(scenario), **overrides}

    nd = mb.snapshot_network(project)
    nd = mb.apply_overrides(nd, overrides)
    result = engine.solve_multiperiod(nd, penalty_base=penalty_base)

    if result["status"] == "infeasible":
        result["diagnostics"] = diagnostics.diagnose_multiperiod(nd, nd.months)

    run = repo.save_run(project_id, scenario_id, "multiperiod", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    if result["status"] == "optimal":
        project.status = "Optimized"
        repo.save_project(project)
    log_usage("optimize_multiperiod", project_id, result.get("status"))
    return jsonify(result)


@optimize_bp.post("/<int:project_id>/multiperiod/lexicographic")
def optimize_lexicographic(project_id):
    """Lexicographic priority allocation (spec section 14, Mode B) - protect
    tier 1 fully before tier 2, tier 2 before tier 3, etc., then minimize
    cost among what's left. Distinct from the standard multiperiod solve's
    weighted-penalty policy (Mode A, priority_class.penalty_weight)."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    nd = mb.snapshot_network(project)
    result = engine.solve_lexicographic(nd)
    if result["status"] == "infeasible":
        result.setdefault("diagnostics", diagnostics.diagnose_multiperiod(nd, nd.months))
    run = repo.save_run(project_id, None, "lexicographic", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    log_usage("optimize_lexicographic", project_id, result.get("status"))
    return jsonify(result)


@optimize_bp.post("/<int:project_id>/rolling-horizon")
def optimize_rolling_horizon(project_id):
    """Rolling-horizon re-optimization (spec section 25) - distinct from the
    static 12-month plan: solves a look-ahead window at each month and
    commits only that month, re-solving forward. See engine.solve_rolling_horizon."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    window_size = int(data.get("window_size", 3))
    if window_size < 1:
        return jsonify({"error": "window_size must be >= 1."}), 400

    nd = mb.snapshot_network(project)
    result = engine.solve_rolling_horizon(nd, window_size=window_size)
    run = repo.save_run(project_id, None, "rolling_horizon", "HiGHS", result)
    result["run_id"] = run["id"]
    log_usage("optimize_rolling_horizon", project_id, result.get("status"))
    return jsonify(result)


@optimize_bp.post("/<int:project_id>/investment/min-capex")
def optimize_min_capex(project_id):
    """Minimum CAPEX to hit a target aggregate service level (spec section 22/84)."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    target = float(data.get("target_service_level", 0.95))
    if not (0 <= target <= 1):
        return jsonify({"error": "target_service_level must be between 0 and 1."}), 400

    nd = mb.snapshot_network(project)
    result = engine.solve_min_investment_for_service(nd, target_service_level=target)
    if result["status"] == "infeasible":
        result["diagnostics"] = diagnostics.diagnose_multiperiod(nd, nd.months)
        result["note"] = (f"No combination of expansion within each facility's own max_expansion "
                           f"can reach {target*100:.0f}% aggregate service level. Raise max_expansion "
                           f"on the binding facilities (see the Bottlenecks analysis) and retry.")
    result["target_service_level"] = target
    run = repo.save_run(project_id, None, "investment_min_capex", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    log_usage("optimize_min_capex", project_id, result.get("status"))
    return jsonify(result)


@optimize_bp.post("/<int:project_id>/investment/max-service")
def optimize_max_service(project_id):
    """Maximum achievable service level for a fixed CAPEX budget (spec section 22/84)."""
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    budget = float(data.get("budget", 0))
    if budget < 0:
        return jsonify({"error": "budget must be >= 0."}), 400

    nd = mb.snapshot_network(project)
    result = engine.solve_max_service_for_budget(nd, budget=budget)
    if result["status"] == "infeasible":
        result["diagnostics"] = diagnostics.diagnose_multiperiod(nd, nd.months)
    result["budget"] = budget
    run = repo.save_run(project_id, None, "investment_max_service", result.get("solver_name"), result)
    result["run_id"] = run["id"]
    log_usage("optimize_max_service", project_id, result.get("status"))
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
    penalty_base = data.get("penalty_base")  # None -> engine falls back to the project's unmet_demand_penalty_base

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


_COMPARE_METRICS = [
    ("total_cost", lambda r: r.get("total_cost") if r.get("total_cost") is not None else r.get("objective_value")),
    ("service_level", lambda r: (r.get("kpis") or {}).get("overall_service_level")
                                  or (r.get("kpis") or {}).get("demand_fulfilment_pct")),
    ("shortage", lambda r: (r.get("kpis") or {}).get("total_shortage")
                             or (r.get("kpis") or {}).get("total_unmet_demand")),
    ("expansion_capex", lambda r: r.get("expansion_capex")),
    ("cgs_open_count", lambda r: (r.get("kpis") or {}).get("cgs_open_count")),
    ("station_open_count", lambda r: (r.get("kpis") or {}).get("station_open_count")),
]


@runs_bp.get("/compare")
def compare_runs():
    """Run A vs Run B (spec section 60) - pass ?run_a=<id>&run_b=<id>.
    Every metric is read straight from each run's stored result payload,
    whatever run_type it was (deterministic/multiperiod/investment/etc.) -
    metrics that don't apply to a given run's type simply come back null."""
    run_a_id = request.args.get("run_a", type=int)
    run_b_id = request.args.get("run_b", type=int)
    if not run_a_id or not run_b_id:
        return jsonify({"error": "Provide both run_a and run_b query params (run ids)."}), 400

    run_a, run_b = repo.get_run(run_a_id), repo.get_run(run_b_id)
    result_a, result_b = run_a.get("result") or {}, run_b.get("result") or {}

    rows = []
    for key, getter in _COMPARE_METRICS:
        a, b = getter(result_a), getter(result_b)
        delta = (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        rows.append({"metric": key, "run_a": a, "run_b": b, "delta": round(delta, 4) if delta is not None else None})

    return jsonify({
        "run_a": {"id": run_a["id"], "run_type": run_a["run_type"], "created_at": run_a["created_at"],
                   "status": run_a["status"]},
        "run_b": {"id": run_b["id"], "run_type": run_b["run_type"], "created_at": run_b["created_at"],
                   "status": run_b["status"]},
        "comparison": rows,
    })
