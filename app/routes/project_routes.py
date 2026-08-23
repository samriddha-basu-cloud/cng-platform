from flask import Blueprint, jsonify, request
from app.data import repo
from app.data.demo_seed import seed_demo_project_simple, seed_demo_project_advanced
from app.utils.validation import require_fields, ValidationError
from app.utils.usage_logger import log_usage

project_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


@project_bp.get("")
def list_projects():
    return jsonify([p.to_dict() for p in repo.list_projects()])


@project_bp.post("")
def create_project():
    data = request.get_json(force=True, silent=True) or {}
    try:
        require_fields(data, ["name"])
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    project = repo.create_project(data)
    log_usage("project_created", project.id, project.name)
    return jsonify(project.to_dict()), 201


@project_bp.post("/demo")
def create_demo_project():
    variant = (request.args.get("variant") or "simple").lower()
    if variant == "advanced":
        project = seed_demo_project_advanced()
    else:
        project = seed_demo_project_simple()
    log_usage("demo_loaded", project.id, variant)
    return jsonify(project.to_dict()), 201


@project_bp.get("/<int:project_id>")
def get_project(project_id):
    project = repo.get_project(project_id)
    return jsonify(project.to_dict())


@project_bp.delete("/<int:project_id>")
def delete_project(project_id):
    repo.delete_project(project_id)
    log_usage("project_deleted", project_id)
    return jsonify({"deleted": project_id})


@project_bp.patch("/<int:project_id>")
def update_project(project_id):
    project = repo.get_project(project_id)
    data = request.get_json(force=True, silent=True) or {}
    editable = [
        "name", "description", "region", "currency", "gas_unit", "demand_unit",
        "time_granularity", "planning_horizon_years", "num_periods",
        "num_scenarios", "status",
    ]
    project = repo.update_project(project, data, editable)
    return jsonify(project.to_dict())
