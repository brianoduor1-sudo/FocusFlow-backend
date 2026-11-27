from datetime import date, datetime, timezone
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_

from app.database import db
from app.models import Project, Task
from app.schemas import (
    ValidationError,
    normalize_priority,
    normalize_status,
    task_to_dict,
    validate_task,
)

tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

def _now():
    return datetime.now(timezone.utc)

def _current_user_id():
    return int(get_jwt_identity())

def _project_belongs_to_user(project_id, user_id):
    if project_id is None:
        return True
    return Project.query.filter_by(id=project_id, user_id=user_id).first() is not None

def _get_owned_task(task_id, user_id):
    return Task.query.filter_by(id=task_id, user_id=user_id).first()

def _apply_status(task, new_status):
    old_status = task.status
    task.status = new_status
    if new_status == "done" and old_status != "done":
        task.completed_at = _now()
    elif new_status != "done" and old_status == "done":
        task.completed_at = None

def _bad_request(err):
    return jsonify({"error": err.message, "errors": err.errors}), 400

@tasks_bp.route("", methods=["GET"])
@jwt_required()
def list_tasks():
    user_id = _current_user_id()
    query = Task.query.filter_by(user_id=user_id)

    status = request.args.get("status")
    if status:
        normalized = normalize_status(status)
        if not normalized:
            return jsonify({"error": "Invalid status filter"}), 400
        query = query.filter(Task.status == normalized)

    priority = request.args.get("priority")
    if priority:
        normalized = normalize_priority(priority)
        if not normalized:
            return jsonify({"error": "Invalid priority filter"}), 400
        query = query.filter(Task.priority == normalized)

    project_id = request.args.get("project_id") or request.args.get("projectId")
    if project_id:
        try:
            query = query.filter(Task.project_id == int(project_id))
        except ValueError:
            return jsonify({"error": "Invalid project_id filter"}), 400

    search = (request.args.get("search") or "").strip()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(Task.title.ilike(pattern), Task.description.ilike(pattern))
        )

    tasks = query.all()
    tasks.sort(
        key=lambda t: (
            t.status == "done",
            t.due_date or date.max,
            PRIORITY_ORDER.get(t.priority, 1),
            -t.id,
        )
    )
    return jsonify([task_to_dict(t) for t in tasks]), 200

@tasks_bp.route("", methods=["POST"])
@jwt_required()
def create_task():
    user_id = _current_user_id()
    data = request.get_json(silent=True) or {}

    try:
        cleaned = validate_task(data)
    except ValidationError as err:
        return _bad_request(err)

    if not _project_belongs_to_user(cleaned["project_id"], user_id):
        return jsonify({"error": "Project not found"}), 404

    task = Task(
        user_id=user_id,
        title=cleaned["title"],
        description=cleaned["description"],
        division=cleaned["division"],
        issue_type=cleaned["issue_type"],
        story_points=cleaned["story_points"],
        priority=cleaned["priority"],
        status=cleaned["status"],
        due_date=cleaned["due_date"],
        project_id=cleaned["project_id"],
        completed_at=_now() if cleaned["status"] == "done" else None,
    )
    db.session.add(task)
    db.session.commit()
    return jsonify(task_to_dict(task)), 201

@tasks_bp.route("/<int:task_id>", methods=["GET"])
@jwt_required()
def get_task(task_id):
    task = _get_owned_task(task_id, _current_user_id())
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task_to_dict(task)), 200

@tasks_bp.route("/<int:task_id>", methods=["PUT", "PATCH"])
@jwt_required()
def update_task(task_id):
    user_id = _current_user_id()
    task = _get_owned_task(task_id, user_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        cleaned = validate_task(data, partial=True)
    except ValidationError as err:
        return _bad_request(err)

    if "project_id" in cleaned and not _project_belongs_to_user(cleaned["project_id"], user_id):
        return jsonify({"error": "Project not found"}), 404

    if "status" in cleaned:
        _apply_status(task, cleaned.pop("status"))

    for field, value in cleaned.items():
        setattr(task, field, value)

    db.session.commit()
    return jsonify(task_to_dict(task)), 200

@tasks_bp.route("/<int:task_id>", methods=["DELETE"])
@jwt_required()
def delete_task(task_id):
    task = _get_owned_task(task_id, _current_user_id())
    if not task:
        return jsonify({"error": "Task not found"}), 404
    db.session.delete(task)
    db.session.commit()
    return "", 204
