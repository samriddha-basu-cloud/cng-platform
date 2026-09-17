"""The Assumption Register (spec section 62) - Parameter/Value/Unit/Source/
Confidence/Type for every planning number that isn't verified fact. The
data model (app/data/entities.py::Assumption) and demo-seed population have
existed since Phase 1, but had no API route at all until now - this closes
that gap."""
from flask import Blueprint, jsonify, request
from app.data import repo
from app.utils.validation import require_fields, ValidationError

assumption_bp = Blueprint("assumptions", __name__, url_prefix="/api/assumptions")


@assumption_bp.get("/<int:project_id>")
def list_assumptions(project_id):
    project = repo.get_project(project_id)
    return jsonify([a.to_dict() for a in repo.list_assumptions(project)])


@assumption_bp.post("/<int:project_id>")
def create_assumption(project_id):
    project = repo.get_project(project_id)
    data = request.get_json(force=True, silent=True) or {}
    try:
        require_fields(data, ["parameter", "value"])
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    a = repo.add_assumption(
        project, entity_type=data.get("entity_type", ""), entity_code=data.get("entity_code", ""),
        parameter=data["parameter"], value=str(data["value"]), unit=data.get("unit", ""),
        source=data.get("source", "User input"), status=data.get("status", "Assumption"),
        confidence=data.get("confidence", "Medium"), notes=data.get("notes", ""),
    )
    return jsonify(a.to_dict()), 201


@assumption_bp.patch("/<int:project_id>/<int:assumption_id>")
def update_assumption(project_id, assumption_id):
    project = repo.get_project(project_id)
    data = request.get_json(force=True, silent=True) or {}
    a = repo.update_assumption(project, assumption_id, data)
    return jsonify(a.to_dict())


@assumption_bp.delete("/<int:project_id>/<int:assumption_id>")
def delete_assumption(project_id, assumption_id):
    project = repo.get_project(project_id)
    repo.delete_assumption(project, assumption_id)
    return jsonify({"deleted": assumption_id})
