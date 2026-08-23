from flask import Blueprint, jsonify
from app.optimization.solver_registry import detect_solvers, get_active_solver

meta_bp = Blueprint("meta", __name__, url_prefix="/api/meta")


@meta_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@meta_bp.get("/solvers")
def solvers():
    detected = detect_solvers()
    active = get_active_solver()
    return jsonify({
        "active_solver": active.display_name,
        "active_solver_key": active.key,
        "solvers": [
            {"key": s.key, "name": s.display_name, "available": s.available,
             "kind": s.kind, "detail": s.detail}
            for s in detected
        ],
    })
