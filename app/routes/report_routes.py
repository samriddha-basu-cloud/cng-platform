import os
from flask import Blueprint, jsonify, send_file, current_app
from app.data import repo
from app.services import report_service as rs
from app.utils.validation import validate_network
from app.utils.usage_logger import log_usage

report_bp = Blueprint("report", __name__, url_prefix="/api/report")


def _blocking_errors(project):
    return [i for i in validate_network(project) if i["level"] == "error"]


@report_bp.get("/<int:project_id>/executive")
def executive_report(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    return jsonify(rs.build_report_payload(project))


@report_bp.get("/<int:project_id>/technical")
def technical_report(project_id):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400
    return jsonify(rs.build_technical_payload(project))


@report_bp.get("/<int:project_id>/export/<fmt>")
def export_report(project_id, fmt):
    project = repo.get_project(project_id)
    errors = _blocking_errors(project)
    if errors:
        return jsonify({"error": "Network has blocking validation errors.", "issues": errors}), 400

    exporters = {"json": rs.export_json, "csv": rs.export_csv, "excel": rs.export_excel, "pdf": rs.export_pdf}
    if fmt not in exporters:
        return jsonify({"error": f"Unknown format '{fmt}'. Use one of {list(exporters.keys())}."}), 400

    try:
        path = exporters[fmt](current_app, project)
    except Exception as e:
        return jsonify({"error": f"Export failed: {e}"}), 500

    log_usage("report_export", project_id, fmt)
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))
