from datetime import timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.database import db
from app.models import FocusSession, Task
from app.helpers import to_iso, parse_datetime, utc_now, validation_error

focus_bp = Blueprint("focus", __name__)

SESSION_TYPES = ["focus", "short_break", "long_break"]

def session_to_dict(session):
    
    return {
        "id": session.id,
        "task_id": session.task_id,
        "session_type": session.session_type or "focus",
        "duration_minutes": session.duration_min or 0,
        "started_at": to_iso(session.start_time),
        "ended_at": to_iso(session.end_time),
    }

@focus_bp.route("/", methods=["GET"])
@jwt_required()
def get_sessions():
    user_id = int(get_jwt_identity())

    sessions = (
        FocusSession.query.filter_by(user_id=user_id)
        .order_by(FocusSession.start_time.desc())
        .all()
    )

    return jsonify([session_to_dict(s) for s in sessions]), 200

@focus_bp.route("/", methods=["POST"])
@jwt_required()
def save_session():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    errors = {}

    
    session_type = data.get("session_type") or "focus"
    if session_type not in SESSION_TYPES:
        errors["session_type"] = "Must be focus, short_break or long_break"

    
    started_at = parse_datetime(data.get("started_at"))
    ended_at = parse_datetime(data.get("ended_at"))

    if data.get("started_at") and started_at is None:
        errors["started_at"] = "Invalid date"
    if data.get("ended_at") and ended_at is None:
        errors["ended_at"] = "Invalid date"
    if started_at and ended_at and ended_at < started_at:
        errors["ended_at"] = "Must be after started_at"

    
    duration = data.get("duration_minutes")
    if duration is None or duration == "":
        if started_at and ended_at:
            duration = round((ended_at - started_at).total_seconds() / 60)
        else:
            errors["duration_minutes"] = "Required"
    else:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            errors["duration_minutes"] = "Must be a number"
        else:
            if duration < 0 or duration > 1440:
                errors["duration_minutes"] = "Must be between 0 and 1440"

    
    task_id = data.get("task_id")
    if task_id is None or task_id == "":
        task_id = None
    else:
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            errors["task_id"] = "Must be a number"
        else:
            task = Task.query.filter_by(id=task_id, user_id=user_id).first()
            if task is None:
                errors["task_id"] = "Task not found"

    if errors:
        return validation_error(errors)

    
    if ended_at is None:
        if started_at:
            ended_at = started_at + timedelta(minutes=duration)
        else:
            ended_at = utc_now()
    if started_at is None:
        started_at = ended_at - timedelta(minutes=duration)

    session = FocusSession(
        user_id=user_id,
        task_id=task_id,
        session_type=session_type,
        start_time=started_at,
        end_time=ended_at,
        duration_min=duration,
    )
    db.session.add(session)
    db.session.commit()

    return jsonify(session_to_dict(session)), 201
