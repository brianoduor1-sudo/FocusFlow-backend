from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.database import db
from app.models import Note

try:  
    from app.models import Project
except ImportError:  
    Project = None

notes_bp = Blueprint("notes", __name__, url_prefix="/notes")

MAX_TITLE = 150
MAX_CONTENT = 10000

def _error(message, status=400, errors=None):
    body = {"error": message}
    if errors:
        body["errors"] = errors
    return jsonify(body), status

def _now():
    
    return datetime.now(timezone.utc).replace(tzinfo=None)

def _iso(value):
    
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def note_to_dict(note):
    return {
        "id": note.id,
        "title": note.title or "",
        "content": note.content or "",
        "project_id": note.project_id,
        "task_id": note.task_id,
        "created_at": _iso(note.created_at),
        "updated_at": _iso(note.updated_at or note.created_at),
    }

def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def _user_id():
    return int(get_jwt_identity())

def _check_project(user_id, value):
    
    if value is None or value == "":
        return None, None
    try:
        project_id = int(value)
    except (TypeError, ValueError):
        return None, "Project id must be a number"
    if Project is None or Project.query.filter_by(id=project_id, user_id=user_id).first() is None:
        return None, "Project not found"
    return project_id, None

def _clean_text(data, key, limit, current=""):
    
    if key not in data:
        return current, None
    value = data[key]
    if value is None:
        return "", None
    if not isinstance(value, str):
        return current, f"{key.capitalize()} must be text"
    if len(value) > limit:
        return current, f"{key.capitalize()} must be {limit} characters or fewer"
    return value, None

def _commit():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

@notes_bp.route("", methods=["GET"], strict_slashes=False)
@jwt_required()
def get_notes():
    user_id = _user_id()
    query = Note.query.filter_by(user_id=user_id)

    project_id = request.args.get("project_id")
    if project_id not in (None, ""):
        try:
            query = query.filter_by(project_id=int(project_id))
        except ValueError:
            return _error("Invalid project_id filter", 400)

    notes = query.all()
    
    notes.sort(key=lambda n: n.updated_at or n.created_at or datetime.min, reverse=True)
    return jsonify([note_to_dict(n) for n in notes]), 200

@notes_bp.route("", methods=["POST"], strict_slashes=False)
@jwt_required()
def create_note():
    user_id = _user_id()
    data = _json_body()
    errors = {}

    title, err = _clean_text(data, "title", MAX_TITLE)
    if err:
        errors["title"] = err
    content, err = _clean_text(data, "content", MAX_CONTENT)
    if err:
        errors["content"] = err
    title = title.strip()

    if not errors and not title and not content.strip():
        errors["title"] = "Add a title or some content"

    project_id, project_error = _check_project(user_id, data.get("project_id"))
    if project_error:
        errors["project_id"] = project_error

    if errors:
        return _error(next(iter(errors.values())), 400, errors)

    now = _now()
    note = Note(
        user_id=user_id,
        title=title or None,
        content=content,
        project_id=project_id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(note)
    _commit()
    return jsonify(note_to_dict(note)), 201

@notes_bp.route("/<int:note_id>", methods=["PUT", "PATCH"])
@jwt_required()
def update_note(note_id):
    user_id = _user_id()
    note = Note.query.filter_by(id=note_id, user_id=user_id).first()
    if note is None:
        return _error("Note not found", 404)

    data = _json_body()
    errors = {}

    title, err = _clean_text(data, "title", MAX_TITLE, current=note.title or "")
    if err:
        errors["title"] = err
    content, err = _clean_text(data, "content", MAX_CONTENT, current=note.content or "")
    if err:
        errors["content"] = err
    title = title.strip()

    project_id = note.project_id
    if "project_id" in data:
        project_id, project_error = _check_project(user_id, data["project_id"])
        if project_error:
            errors["project_id"] = project_error

    if not errors and not title and not content.strip():
        errors["title"] = "Add a title or some content"

    if errors:
        return _error(next(iter(errors.values())), 400, errors)

    note.title = title or None
    note.content = content
    note.project_id = project_id
    note.updated_at = _now()
    _commit()
    return jsonify(note_to_dict(note)), 200

@notes_bp.route("/<int:note_id>", methods=["DELETE"])
@jwt_required()
def delete_note(note_id):
    user_id = _user_id()
    note = Note.query.filter_by(id=note_id, user_id=user_id).first()
    if note is None:
        return _error("Note not found", 404)

    db.session.delete(note)
    _commit()
    return jsonify({"message": "Note deleted"}), 200
