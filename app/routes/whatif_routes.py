from flask import Blueprint, jsonify, request
from app.data import repo
from app.optimization import model_builder as mb, engine, diagnostics
from app.services.scenario_service import build_preset_overrides
from app.utils.validation import validate_network
from app.utils.usage_logger import log_usage

whatif_bp = Blueprint("whatif", __name__, url_prefix="/api/whatif")


def _summarize(result):
    if result["status"] != "optimal":
        return {"status": result["status"]}
    return {
        "status": "optimal",
        "total_cost": result["objective_value"],
        "cost_breakdown": result["cost_breakdown"],
        "fulfilment_pct": result["kpis"]["demand_fulfilment_pct"],
        "unmet_demand": result["kpis"]["total_unmet_demand"],
        "cgs_open": f"{result['kpis']['cgs_open_count']}/{result['kpis']['cgs_total_count']}",
        "stations_open": f"{result['kpis']['station_open_count']}/{result['kpis']['station_total_count']}",
        "avg_cgs_utilization": result["kpis"]["avg_cgs_utilization"],
        "avg_station_utilization": result["kpis"]["avg_station_utilization"],
    }


@whatif_bp.post("/<int:project_id>")
def run_whatif(project_id):
    project = repo.get_project(project_id)
    errors = [i for i in validate_network(project) if i["level"] == "error"]
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    preset_key = data.get("preset")
    overrides = data.get("overrides", {}) or {}
    if preset_key:
        try:
            overrides = {**build_preset_overrides(project, preset_key), **overrides}
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    base_nd = mb.snapshot_network(project)
    baseline_result = engine.solve_network(base_nd)
    scenario_nd = mb.apply_overrides(base_nd, overrides)
    scenario_result = engine.solve_network(scenario_nd)

    payload = {
        "overrides_applied": overrides,
        "before": _summarize(baseline_result),
        "after": _summarize(scenario_result),
    }
    if scenario_result["status"] == "infeasible":
        payload["after"]["diagnostics"] = diagnostics.diagnose(scenario_nd)["findings"]

    if baseline_result["status"] == "optimal" and scenario_result["status"] == "optimal":
        payload["delta"] = {
            "cost_change": round(scenario_result["objective_value"] - baseline_result["objective_value"], 4),
            "cost_change_pct": round(
                (scenario_result["objective_value"] - baseline_result["objective_value"]) / baseline_result["objective_value"] * 100, 2
            ) if baseline_result["objective_value"] else None,
            "fulfilment_change_pct_points": round(
                (scenario_result["kpis"]["demand_fulfilment_pct"] - baseline_result["kpis"]["demand_fulfilment_pct"]) * 100, 2
            ),
            "unmet_demand_change": round(
                scenario_result["kpis"]["total_unmet_demand"] - baseline_result["kpis"]["total_unmet_demand"], 4
            ),
        }
        before_by_zone = {d["code"]: d for d in baseline_result["demand_results"]}
        after_by_zone = {d["code"]: d for d in scenario_result["demand_results"]}
        payload["zone_deltas"] = [
            {"code": code, "before_unmet": before_by_zone[code]["unmet"], "after_unmet": after_by_zone[code]["unmet"],
             "before_fulfilment": before_by_zone[code]["fulfilment_pct"], "after_fulfilment": after_by_zone[code]["fulfilment_pct"]}
            for code in before_by_zone
        ]

    log_usage("whatif_run", project_id, preset_key or "custom")
    return jsonify(payload)
