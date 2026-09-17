"""Excel template/sample download and planning-data import (spec sections
37-57): the app generates its own template and sample workbook - the user
is never required to supply an external Excel file."""
import io
from flask import Blueprint, jsonify, request, send_file
from app.data import repo
from app.services import excel_service as xs
from app.utils.usage_logger import log_usage

excel_bp = Blueprint("excel_data", __name__, url_prefix="/api/data")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB - generous for a planning workbook, small enough to reject junk


@excel_bp.get("/<int:project_id>/template")
def download_template(project_id):
    repo.get_project(project_id)  # 404s if the project doesn't exist
    buf = xs.generate_template_workbook()
    log_usage("excel_template_download", project_id)
    return send_file(buf, as_attachment=True, download_name="cng_planning_template.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@excel_bp.get("/<int:project_id>/sample")
def download_sample(project_id):
    repo.get_project(project_id)
    buf = xs.generate_sample_workbook()
    log_usage("excel_sample_download", project_id)
    return send_file(buf, as_attachment=True, download_name="cng_planning_sample.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _read_upload():
    """Returns (parsed_dict, error_response_or_None). Never trusts the
    uploaded filename or extension for anything beyond a friendly message -
    parsing is what actually validates it's a real workbook."""
    file = request.files.get("file")
    if file is None or file.filename == "":
        return None, (jsonify({"error": "No file uploaded. Attach it as multipart field 'file'."}), 400)
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        return None, (jsonify({"error": "Only .xlsx/.xlsm Excel workbooks are accepted."}), 400)
    data = file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return None, (jsonify({"error": "File too large (max 10 MB)."}), 400)
    try:
        parsed = xs.parse_workbook(io.BytesIO(data))
    except Exception as e:
        return None, (jsonify({"error": f"Could not read this as an Excel workbook: {e}"}), 400)
    return parsed, None


@excel_bp.post("/<int:project_id>/validate")
def validate_upload(project_id):
    """Dry run: parses and validates the uploaded workbook against this
    project's context (for the preview's added/updated counts) but writes
    nothing. Safe to call repeatedly while the user fixes issues."""
    project = repo.get_project(project_id)
    parsed, err = _read_upload()
    if err:
        return err
    preview = xs.preview_summary(parsed, project)
    log_usage("excel_validate", project_id, preview["status"])
    return jsonify(preview)


@excel_bp.post("/<int:project_id>/import")
def import_upload(project_id):
    """Re-validates (never trusts a client-side 'it was fine before') then,
    only if there are zero errors, applies the import. mode='replace' (the
    default) upserts into THIS project; to import as a brand-new dataset,
    create a new project first and POST here against its id (mode='create_new')."""
    project = repo.get_project(project_id)
    mode = (request.form.get("mode") or "replace").lower()
    if mode not in ("create_new", "replace"):
        return jsonify({"error": "mode must be 'create_new' or 'replace'"}), 400

    parsed, err = _read_upload()
    if err:
        return err

    preview = xs.preview_summary(parsed, project)
    if preview["error_count"] > 0:
        return jsonify({"error": "Workbook has validation errors and was not imported.", **preview}), 400

    summary = xs.apply_import(project, parsed, mode=mode)
    project.status = "Configured"
    # dataset versioning (spec section 55): every successful import stamps a new version,
    # so the workspace can always say which import produced the currently-active data.
    from datetime import datetime, timezone
    version_tag = f"IMPORT_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    project.dataset_version = version_tag
    project.dataset_imported_at = datetime.now(timezone.utc).isoformat()
    project.dataset_source = request.files.get("file").filename if request.files.get("file") else "excel_upload"
    repo.save_project(project)
    log_usage("excel_import", project_id, f"mode={mode} version={version_tag}")
    return jsonify({**summary, "data_quality": preview["data_quality"], "project_id": project_id,
                     "status": "READY FOR OPTIMIZATION", "dataset_version": version_tag})
