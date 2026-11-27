import re
from datetime import date, timezone

class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        self.message = next(iter(errors.values())) if errors else "Invalid data"
        super().__init__(self.message)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

def _clean_email(value):
    return value.strip().lower() if isinstance(value, str) else ""

def validate_register(data):
    errors = {}
    name = data.get("name") or data.get("username")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        errors["name"] = "Name is required"
    elif len(name) > 100:
        errors["name"] = "Name must be 100 characters or fewer"

    email = _clean_email(data.get("email"))
    if not email:
        errors["email"] = "Email is required"
    elif len(email) > 254 or not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address"

    password = data.get("password")
    if not isinstance(password, str) or not password:
        errors["password"] = "Password is required"
    elif len(password) < MIN_PASSWORD_LENGTH:
        errors["password"] = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    elif len(password) > MAX_PASSWORD_LENGTH:
        errors["password"] = f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer"

    if errors:
        raise ValidationError(errors)
    return {"name": name, "email": email, "password": password}

def validate_login(data):
    errors = {}
    email = _clean_email(data.get("email"))
    password = data.get("password")
    if not email:
        errors["email"] = "Email is required"
    if not isinstance(password, str) or not password:
        errors["password"] = "Password is required"
    if errors:
        raise ValidationError(errors)
    return {"email": email, "password": password}

PRIORITIES = ("low", "medium", "high")
STATUSES = ("todo", "in_progress", "in_review", "done")
ISSUE_TYPES = ("epic", "story", "task", "bug")

_STATUS_ALIASES = {
    "todo": "todo",
    "to_do": "todo",
    "pending": "todo",
    "in_progress": "in_progress",
    "inprogress": "in_progress",
    "doing": "in_progress",
    "in_review": "in_review",
    "inreview": "in_review",
    "review": "in_review",
    "done": "done",
    "complete": "done",
    "completed": "done",
}

def normalize_status(value):
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _STATUS_ALIASES.get(key)

def normalize_priority(value):
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    return key if key in PRIORITIES else None

def normalize_issue_type(value):
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    return key if key in ISSUE_TYPES else None

def parse_due_date(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) < 10:
        raise ValueError("bad date")
    return date.fromisoformat(value[:10])

def parse_project_id(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bad project id")
    return int(value)

def _present(data, *names):
    for name in names:
        if name in data:
            return True, data[name]
    return False, None

def validate_task(data, partial=False):
    cleaned, errors = {}, {}

    found, title = _present(data, "title")
    if found or not partial:
        title = title.strip() if isinstance(title, str) else ""
        if not title:
            errors["title"] = "Title is required"
        elif len(title) > 200:
            errors["title"] = "Title must be 200 characters or fewer"
        else:
            cleaned["title"] = title

    found, description = _present(data, "description")
    if found:
        if description is None:
            cleaned["description"] = ""
        elif isinstance(description, str) and len(description.strip()) <= 2000:
            cleaned["description"] = description.strip()
        else:
            errors["description"] = "Description must be text of 2000 characters or fewer"
    elif not partial:
        cleaned["description"] = ""

    found, priority = _present(data, "priority")
    if found:
        normalized = normalize_priority(priority)
        if normalized is None:
            errors["priority"] = "Priority must be low, medium or high"
        else:
            cleaned["priority"] = normalized
    elif not partial:
        cleaned["priority"] = "medium"

    found, status = _present(data, "status")
    if found:
        normalized = normalize_status(status)
        if normalized is None:
            errors["status"] = "Status must be todo, in_progress, in_review or done"
        else:
            cleaned["status"] = normalized
    elif not partial:
        cleaned["status"] = "todo"

    found, division = _present(data, "division", "epic")
    if found:
        cleaned["division"] = (str(division).strip() if division else "General")[:80] or "General"
    elif not partial:
        cleaned["division"] = "General"

    found, issue_type = _present(data, "issue_type", "issueType", "type")
    if found:
        normalized_type = normalize_issue_type(issue_type)
        if normalized_type is None:
            errors["issue_type"] = "Issue type must be epic, story, task or bug"
        else:
            cleaned["issue_type"] = normalized_type
    elif not partial:
        cleaned["issue_type"] = "task"

    found, points = _present(data, "story_points", "storyPoints", "points")
    if found:
        try:
            pts = int(points) if points not in (None, "") else 1
            cleaned["story_points"] = max(1, min(pts, 100))
        except (TypeError, ValueError):
            errors["story_points"] = "Story points must be a number"
    elif not partial:
        cleaned["story_points"] = 1

    found, due = _present(data, "due_date", "dueDate")
    if found:
        try:
            cleaned["due_date"] = parse_due_date(due)
        except ValueError:
            errors["due_date"] = "Due date must be in YYYY-MM-DD format"
    elif not partial:
        cleaned["due_date"] = None

    found, project_id = _present(data, "project_id", "projectId")
    if found:
        try:
            cleaned["project_id"] = parse_project_id(project_id)
        except (TypeError, ValueError):
            errors["project_id"] = "Project id must be a number"
    elif not partial:
        cleaned["project_id"] = None

    if errors:
        raise ValidationError(errors)
    return cleaned

def _iso_datetime(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def task_to_dict(task):
    project = getattr(task, "project", None)
    key_prefix = (getattr(project, "project_key", None) or "FF").upper() if project else "FF"
    return {
        "id": task.id,
        "issue_key": f"{key_prefix}-{task.id}",
        "title": task.title,
        "description": getattr(task, "description", "") or "",
        "division": getattr(task, "division", "General") or "General",
        "issue_type": getattr(task, "issue_type", "task") or "task",
        "story_points": getattr(task, "story_points", 1) or 1,
        "priority": task.priority,
        "status": task.status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "completed_at": _iso_datetime(task.completed_at),
        "project_id": task.project_id,
        "project_name": project.title if project is not None else None,
        "created_at": _iso_datetime(getattr(task, "created_at", None)),
        "updated_at": _iso_datetime(getattr(task, "updated_at", None)),
    }

def user_to_dict(user):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
