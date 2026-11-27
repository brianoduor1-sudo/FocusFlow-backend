from datetime import datetime, time, timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.database import db
from app.models import FocusSession, Task, Project, Note
from app.helpers import utc_now

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")

def get_focus_sessions(user_id, since=None):
    query = FocusSession.query.filter(
        FocusSession.user_id == user_id,
        FocusSession.start_time.isnot(None),
    )
    if since is not None:
        query = query.filter(FocusSession.start_time >= since)

    sessions = query.all()
    return [s for s in sessions if (getattr(s, "session_type", None) or "focus") == "focus"]

def calculate_streaks(active_days, today):
    if not active_days:
        return 0, 0

    longest = 0
    run = 0
    previous = None
    for day in sorted(active_days):
        if previous is not None and (day - previous).days == 1:
            run += 1
        else:
            run = 1
        if run > longest:
            longest = run
        previous = day

    current = 0
    day = today if today in active_days else today - timedelta(days=1)
    while day in active_days:
        current += 1
        day = day - timedelta(days=1)

    return current, longest

@analytics_bp.route("/summary", methods=["GET"])
@jwt_required()
def get_summary():
    user_id = int(get_jwt_identity())
    today = utc_now().date()
    week_start = today - timedelta(days=6)

    sessions = get_focus_sessions(user_id)
    tasks = Task.query.filter_by(user_id=user_id).all()
    projects = Project.query.filter_by(user_id=user_id).all()
    notes_count = Note.query.filter_by(user_id=user_id).count()

    total_minutes = 0
    today_minutes = 0
    week_minutes = 0
    sessions_today = 0
    active_days = set()

    for s in sessions:
        minutes = s.duration_min or 0
        day = s.start_time.date()
        total_minutes += minutes
        active_days.add(day)
        if day == today:
            today_minutes += minutes
            sessions_today += 1
        if day >= week_start:
            week_minutes += minutes

    completed_today = 0
    for t in tasks:
        if t.status == "done" and t.completed_at:
            c_day = t.completed_at.date()
            active_days.add(c_day)
            if c_day == today:
                completed_today += 1

    current_streak, longest_streak = calculate_streaks(active_days, today)

    todo = len([t for t in tasks if t.status == "todo"])
    in_progress = len([t for t in tasks if t.status in ("in_progress", "in_review")])
    done = len([t for t in tasks if t.status == "done"])
    overdue = len([
        t for t in tasks
        if t.due_date and t.due_date < today and t.status != "done"
    ])
    total_points = sum((t.story_points or 1) for t in tasks)
    done_points = sum((t.story_points or 1) for t in tasks if t.status == "done")

    return jsonify({
        "focus_minutes_total": total_minutes,
        "focus_minutes_today": today_minutes,
        "focus_minutes_week": week_minutes,
        "sessions_total": len(sessions),
        "sessions_today": sessions_today,
        "tasks_total": len(tasks),
        "tasks_todo": todo,
        "tasks_in_progress": in_progress,
        "tasks_completed": done,
        "tasks_completed_today": completed_today,
        "tasks_overdue": overdue,
        "points_total": total_points,
        "points_completed": done_points,
        "notes_total": notes_count,
        "projects_total": len(projects),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
    }), 200

@analytics_bp.route("/trends", methods=["GET"])
@jwt_required()
def get_trends():
    user_id = int(get_jwt_identity())
    days = max(1, min(request.args.get("days", 7, type=int), 90))

    today = utc_now().date()
    first_day = today - timedelta(days=days - 1)
    since = datetime.combine(first_day, time.min)

    sessions = get_focus_sessions(user_id, since)
    tasks = Task.query.filter_by(user_id=user_id).all()
    projects = Project.query.filter_by(user_id=user_id).all()

    daily = {}
    for i in range(days):
        day = first_day + timedelta(days=i)
        daily[day] = {
            "date": day.isoformat(),
            "label": day.strftime("%a"),
            "focus_minutes": 0,
            "sessions": 0,
            "tasks_completed": 0,
            "points_completed": 0,
        }

    task_project = {t.id: t.project_id for t in tasks}
    project_names = {p.id: p.title for p in projects}
    project_keys = {p.id: (p.project_key or "FF") for p in projects}

    minutes_by_project = {}
    for s in sessions:
        minutes = s.duration_min or 0
        day = s.start_time.date()
        if day in daily:
            daily[day]["focus_minutes"] += minutes
            daily[day]["sessions"] += 1
        pid = task_project.get(s.task_id)
        minutes_by_project[pid] = minutes_by_project.get(pid, 0) + minutes

    for t in tasks:
        if t.status == "done" and t.completed_at:
            c_day = t.completed_at.date()
            if c_day in daily:
                daily[c_day]["tasks_completed"] += 1
                daily[c_day]["points_completed"] += (t.story_points or 1)

    by_project = []
    all_project_ids = set(minutes_by_project.keys()) | {p.id for p in projects}
    for pid in all_project_ids:
        p_tasks = [t for t in tasks if t.project_id == pid]
        p_done = sum(1 for t in p_tasks if t.status == "done")
        p_total = len(p_tasks)
        if pid is None and p_total == 0 and minutes_by_project.get(None, 0) == 0:
            continue
        by_project.append({
            "project_id": pid,
            "project_key": project_keys.get(pid, "PERS"),
            "name": project_names.get(pid, "Personal / Unassigned"),
            "focus_minutes": minutes_by_project.get(pid, 0),
            "tasks_total": p_total,
            "tasks_done": p_done,
            "completion_rate": round((p_done / p_total) * 100) if p_total else 0,
        })
    by_project.sort(key=lambda r: (r["focus_minutes"], r["tasks_total"]), reverse=True)

    return jsonify({
        "days": days,
        "daily": list(daily.values()),
        "by_project": by_project,
    }), 200

@analytics_bp.route("/log-focus", methods=["POST"])
@jwt_required()
def log_quick_focus():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    duration_min = max(1, min(int(data.get("duration_min", 25)), 480))

    now = utc_now()
    session = FocusSession(
        user_id=user_id,
        task_id=int(task_id) if task_id else None,
        start_time=now - timedelta(minutes=duration_min),
        end_time=now,
        duration_min=duration_min,
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        "message": f"Logged {duration_min}m focus session",
        "duration_min": duration_min,
        "task_id": session.task_id,
    }), 201
