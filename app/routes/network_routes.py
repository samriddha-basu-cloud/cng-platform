from flask import Blueprint, jsonify, request
from app.data import repo
from app.utils.validation import require_fields, ValidationError, validate_network
from app.utils.usage_logger import log_usage

network_bp = Blueprint("network", __name__, url_prefix="/api/network")

ENTITY_REQUIRED = {
    "sources": ["code", "name"],
    "corridors": ["code", "name", "origin_code", "destination_code"],
    "cgs": ["code", "name"],
    "stations": ["code", "name"],
    "demand": ["code", "name"],
    "priorities": ["name"],
}


def _register_crud(entity_key):
    required = ENTITY_REQUIRED[entity_key]

    @network_bp.get(f"/<int:project_id>/{entity_key}", endpoint=f"list_{entity_key}")
    def list_items(project_id):
        project = repo.get_project(project_id)
        return jsonify([i.to_dict() for i in repo.list_entities(project, entity_key)])

    @network_bp.post(f"/<int:project_id>/{entity_key}", endpoint=f"create_{entity_key}")
    def create_item(project_id):
        project = repo.get_project(project_id)
        data = request.get_json(force=True, silent=True) or {}
        try:
            require_fields(data, required)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400

        if "code" in required:
            existing = {i.code for i in repo.list_entities(project, entity_key)}
            if data["code"] in existing:
                return jsonify({"error": f"Duplicate ID '{data['code']}' in {entity_key}."}), 400

        item = repo.add_entity(project, entity_key, data)
        log_usage(f"{entity_key}_created", project_id, getattr(item, "code", getattr(item, "name", "")))
        return jsonify(item.to_dict()), 201

    @network_bp.patch(f"/<int:project_id>/{entity_key}/<int:item_id>", endpoint=f"update_{entity_key}")
    def update_item(project_id, item_id):
        project = repo.get_project(project_id)
        data = request.get_json(force=True, silent=True) or {}
        item = repo.update_entity(project, entity_key, item_id, data)
        return jsonify(item.to_dict())

    @network_bp.delete(f"/<int:project_id>/{entity_key}/<int:item_id>", endpoint=f"delete_{entity_key}")
    def delete_item(project_id, item_id):
        project = repo.get_project(project_id)
        repo.delete_entity(project, entity_key, item_id)
        log_usage(f"{entity_key}_deleted", project_id, str(item_id))
        return jsonify({"deleted": item_id})


for key in ENTITY_REQUIRED:
    _register_crud(key)


@network_bp.get("/<int:project_id>/graph")
def get_network_graph(project_id):
    """Serialize the full network as nodes+edges for the frontend graph/map view."""
    project = repo.get_project(project_id)
    nodes = []
    for s in project.sources:
        nodes.append({"id": s.code, "type": "source", "name": s.name, "lat": s.latitude, "lng": s.longitude,
                       "capacity": s.max_capacity, "active": s.is_active, "infra_status": s.infra_status})
    for c in project.cgs_list:
        nodes.append({"id": c.code, "type": "cgs", "name": c.name, "lat": c.latitude, "lng": c.longitude,
                       "capacity": c.capacity, "active": c.is_active, "infra_status": c.infra_status})
    for st in project.stations:
        nodes.append({"id": st.code, "type": "station", "name": st.name, "lat": st.latitude, "lng": st.longitude,
                       "capacity": st.capacity, "active": st.is_active, "infra_status": st.infra_status})
    for d in project.demand_zones:
        nodes.append({"id": d.code, "type": "demand", "name": d.name, "lat": d.latitude, "lng": d.longitude,
                       "capacity": d.base_demand, "active": True, "infra_status": "existing"})

    edges = []
    for cor in project.corridors:
        edges.append({"id": cor.code, "source": cor.origin_code, "target": cor.destination_code,
                       "capacity": cor.capacity, "distance_km": cor.distance_km,
                       "cost": cor.transport_cost, "type": cor.pipeline_type, "active": cor.is_active})

    import math

    def haversine(lat1, lon1, lat2, lon2):
        if None in (lat1, lon1, lat2, lon2):
            return None
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    for st in project.stations:
        for d in project.demand_zones:
            dist = haversine(st.latitude, st.longitude, d.latitude, d.longitude)
            if dist is not None and dist <= (st.demand_service_radius_km or 0):
                edges.append({"id": f"{st.code}-{d.code}", "source": st.code, "target": d.code,
                               "capacity": None, "distance_km": round(dist, 1),
                               "cost": None, "type": "service", "active": True})

    return jsonify({"nodes": nodes, "edges": edges})


@network_bp.get("/<int:project_id>/validate")
def validate(project_id):
    project = repo.get_project(project_id)
    issues = validate_network(project)
    errors = [i for i in issues if i["level"] == "error"]
    return jsonify({
        "issues": issues,
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(issues) - len(errors),
    })
