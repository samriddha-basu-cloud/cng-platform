from flask import Blueprint, jsonify, request
from app.data import repo
from app.simulation.timeline import run_timeline
from app.utils.validation import validate_network
from app.utils.usage_logger import log_usage

simulation_bp = Blueprint("simulation", __name__, url_prefix="/api/simulate")


@simulation_bp.post("/<int:project_id>")
def simulate(project_id):
    project = repo.get_project(project_id)
    errors = [i for i in validate_network(project) if i["level"] == "error"]
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    data = request.get_json(force=True, silent=True) or {}
    num_periods = int(data.get("num_periods", project.num_periods or 5))
    shocks = {int(k): v for k, v in (data.get("shocks") or {}).items()}

    result = run_timeline(project, num_periods, shocks)
    log_usage("simulate_run", project_id, f"{num_periods} periods")
    return jsonify(result)
