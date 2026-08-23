from flask import Blueprint, jsonify, request
from app.data import repo
from app.services.scenario_service import build_preset_overrides, PRESET_LABELS

scenario_bp = Blueprint("scenarios", __name__, url_prefix="/api/scenarios")


@scenario_bp.get("/<int:project_id>")
def list_scenarios(project_id):
    project = repo.get_project(project_id)
    return jsonify([s.to_dict() for s in project.scenarios])


@scenario_bp.post("/<int:project_id>")
def create_scenario(project_id):
    project = repo.get_project(project_id)
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "Scenario name is required"}), 400
    sc = repo.add_scenario(project, data)
    return jsonify(sc.to_dict()), 201


@scenario_bp.patch("/<int:project_id>/<int:scenario_id>")
def update_scenario(project_id, scenario_id):
    project = repo.get_project(project_id)
    data = request.get_json(force=True, silent=True) or {}
    sc = repo.update_scenario(project, scenario_id, data)
    return jsonify(sc.to_dict())


@scenario_bp.delete("/<int:project_id>/<int:scenario_id>")
def delete_scenario(project_id, scenario_id):
    project = repo.get_project(project_id)
    repo.delete_scenario(project, scenario_id)
    return jsonify({"deleted": scenario_id})


@scenario_bp.get("/<int:project_id>/presets")
def list_presets(project_id):
    repo.get_project(project_id)
    return jsonify([{"key": k, "label": v} for k, v in PRESET_LABELS.items()])


@scenario_bp.get("/<int:project_id>/presets/<preset_key>")
def preview_preset(project_id, preset_key):
    project = repo.get_project(project_id)
    try:
        overrides = build_preset_overrides(project, preset_key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"key": preset_key, "label": PRESET_LABELS[preset_key], "overrides": overrides})
