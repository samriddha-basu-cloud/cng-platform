from flask import Blueprint, render_template

page_bp = Blueprint("pages", __name__)


@page_bp.get("/")
def landing():
    return render_template("landing.html")


@page_bp.get("/projects")
def projects_app():
    return render_template("projects.html")


@page_bp.get("/project/<int:project_id>")
def project_workspace(project_id):
    return render_template("workspace.html", project_id=project_id)
