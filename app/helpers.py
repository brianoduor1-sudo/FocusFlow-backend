from datetime import datetime, timezone
from flask import jsonify

def utc_now():
    
    
    return datetime.now(timezone.utc).replace(tzinfo=None)

def to_iso(value):
    
    
    if value is None:
        return None

    return value.isoformat() + "Z"

def parse_datetime(value):
    
    

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

    
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed

def error(message, status):
    return jsonify({"error": message}), status

def validation_error(details):
    return jsonify({
        "error": "Validation failed",
        "details": details
    }), 400
