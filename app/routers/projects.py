import re
from datetime import date
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.database import db
from app.models import Project, Task, Note, FocusSession
from app.schemas import task_to_dict
from app.helpers import to_iso, error, validation_error

projects_bp = Blueprint("projects", __name__, url_prefix="/projects")

def _derive_key(title, custom_key=None):
    if custom_key and custom_key.strip():
        cleaned = re.sub(r"[^A-Za-z0-9]", "", custom_key.strip()).upper()
        if cleaned:
            return cleaned[:8]
    words = re.findall(r"[A-Za-z0-9]+", title or "")
    if len(words) >= 2:
        return "".join(w[0] for w in words[:4]).upper()
    if words:
        return words[0][:4].upper()
    return "PRJ"

def _parse_divisions(raw):
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        items = []
    return items or ["Architecture", "Backend API", "Frontend UI", "QA & Testing"]

def project_to_dict(project, include_tasks=False):
    tasks = Task.query.filter_by(project_id=project.id, user_id=project.user_id).all()
    divisions_list = _parse_divisions(project.divisions)

    for t in tasks:
        div = (t.division or "General").strip()
        if div and div not in divisions_list:
            divisions_list.append(div)

    total = len(tasks)
    todo_count = sum(1 for t in tasks if t.status == "todo")
    in_progress_count = sum(1 for t in tasks if t.status == "in_progress")
    in_review_count = sum(1 for t in tasks if t.status == "in_review")
    done_count = sum(1 for t in tasks if t.status == "done")
    total_points = sum((t.story_points or 1) for t in tasks)
    done_points = sum((t.story_points or 1) for t in tasks if t.status == "done")

    today = date.today()
    overdue_count = sum(
        1 for t in tasks if t.due_date and t.due_date < today and t.status != "done"
    )

    task_ids = [t.id for t in tasks]
    focus_minutes = 0
    if task_ids:
        sessions = FocusSession.query.filter(FocusSession.task_id.in_(task_ids)).all()
        focus_minutes = sum((s.duration_min or 0) for s in sessions)

    division_breakdown = []
    for div in divisions_list:
        div_tasks = [t for t in tasks if (t.division or "General") == div]
        div_done = sum(1 for t in div_tasks if t.status == "done")
        div_total = len(div_tasks)
        division_breakdown.append({
            "name": div,
            "total": div_total,
            "done": div_done,
            "in_progress": sum(1 for t in div_tasks if t.status in ("in_progress", "in_review")),
            "todo": sum(1 for t in div_tasks if t.status == "todo"),
            "progress": round((div_done / div_total) * 100) if div_total else 0,
        })

    data = {
        "id": project.id,
        "name": project.title,
        "project_key": project.project_key or _derive_key(project.title),
        "description": project.description or "",
        "github_repo": project.github_repo,
        "status": project.status,
        "divisions": divisions_list,
        "division_breakdown": division_breakdown,
        "insights": {
            "total_issues": total,
            "todo": todo_count,
            "in_progress": in_progress_count,
            "in_review": in_review_count,
            "done": done_count,
            "completion_rate": round((done_count / total) * 100) if total else 0,
            "total_points": total_points,
            "done_points": done_points,
            "overdue": overdue_count,
            "focus_hours": round(focus_minutes / 60, 1),
        },
        "created_at": to_iso(project.created_at),
    }
    if include_tasks:
        data["tasks"] = [task_to_dict(t) for t in tasks]
    return data

def check_project_data(data):
    errors = {}
    name = (data.get("name") or "").strip()
    if name == "":
        errors["name"] = "Required"
    elif len(name) > 150:
        errors["name"] = "Maximum 150 characters"

    repo = (data.get("github_repo") or "").strip()
    if repo != "" and repo.count("/") != 1:
        errors["github_repo"] = "Use the format owner/repo"

    return errors

@projects_bp.route("", methods=["GET"], strict_slashes=False)
@jwt_required()
def get_projects():
    user_id = int(get_jwt_identity())
    projects = (
        Project.query.filter_by(user_id=user_id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return jsonify([project_to_dict(p, include_tasks=True) for p in projects]), 200

@projects_bp.route("", methods=["POST"], strict_slashes=False)
@jwt_required()
def create_project():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    errors = check_project_data(data)
    if errors:
        return validation_error(errors)

    divisions = _parse_divisions(data.get("divisions"))
    project = Project(
        user_id=user_id,
        title=data["name"].strip(),
        project_key=_derive_key(data["name"], data.get("project_key")),
        description=data.get("description"),
        github_repo=(data.get("github_repo") or "").strip() or None,
        divisions=",".join(divisions),
    )
    db.session.add(project)
    db.session.commit()

    return jsonify(project_to_dict(project, include_tasks=True)), 201

@projects_bp.route("/<int:project_id>", methods=["PUT"], strict_slashes=False)
@jwt_required()
def update_project(project_id):
    user_id = int(get_jwt_identity())
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    if project is None:
        return error("Project not found", 404)

    data = request.get_json(silent=True) or {}
    merged = {
        "name": data.get("name", project.title),
        "description": data.get("description", project.description),
        "github_repo": data.get("github_repo", project.github_repo),
    }
    errors = check_project_data(merged)
    if errors:
        return validation_error(errors)

    project.title = merged["name"].strip()
    if "project_key" in data:
        project.project_key = _derive_key(project.title, data.get("project_key"))
    project.description = merged["description"]
    project.github_repo = (merged["github_repo"] or "").strip() or None
    if "divisions" in data:
        project.divisions = ",".join(_parse_divisions(data.get("divisions")))
    if "status" in data and data["status"]:
        project.status = data["status"]

    db.session.commit()
    return jsonify(project_to_dict(project, include_tasks=True)), 200

@projects_bp.route("/<int:project_id>", methods=["DELETE"], strict_slashes=False)
@jwt_required()
def delete_project(project_id):
    user_id = int(get_jwt_identity())
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    if project is None:
        return error("Project not found", 404)

    Task.query.filter_by(project_id=project.id).update({"project_id": None})
    Note.query.filter_by(project_id=project.id).update({"project_id": None})

    db.session.delete(project)
    db.session.commit()
    return jsonify({"message": "Project deleted"}), 200
