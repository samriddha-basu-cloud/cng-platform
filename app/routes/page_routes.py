from flask import Blueprint, render_template

page_bp = Blueprint("pages", __name__)


@page_bp.get("/")
def home():
    return render_template("index.html")


@page_bp.get("/project/<int:project_id>")
def project_workspace(project_id):
    return render_template("workspace.html", project_id=project_id)
