from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token

from app.database import db
from app.deps import COOKIE_NAME, current_user, error_response, login_required
from app.models import User
from app.schemas import ValidationError, user_to_dict, validate_login, validate_register
from app.security import create_access_token, hash_password, verify_password


import re

def validate_password(password):
    """Returns an error message if the password is weak, otherwise None."""
    if not isinstance(password, str):
        return "Password is required"

    problems = []
    if len(password) < 8:
        problems.append("be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        problems.append("contain an uppercase letter")
    if not re.search(r"[a-z]", password):
        problems.append("contain a lowercase letter")
    if not re.search(r"\d", password):
        problems.append("contain a number")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        problems.append("contain a special character (e.g. ! @ # $ %)")

    if problems:
        return "Password must " + ", ".join(problems)
    return None


auth_bp =Blueprint("auth", __name__, url_prefix="/auth")


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _cookie_options():
    return {
        "path": "/",
        "httponly": True,
        "secure": bool(current_app.config.get("COOKIE_SECURE", False)),
        "samesite": current_app.config.get("COOKIE_SAMESITE", "Lax"),
    }


def _set_auth_cookie(response, token):
    minutes = int(current_app.config.get("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24))
    response.set_cookie(COOKIE_NAME, token, max_age=minutes * 60, **_cookie_options())
    return response


@auth_bp.post("/register")
def register():
    try:
        data = validate_register(_json_body())
    except ValidationError as exc:
        return error_response(exc.message, 400, exc.errors)

    if User.query.filter_by(email=data["email"]).first():
        return error_response(
            "An account with this email already exists",
            409,
            {"email": "An account with this email already exists"},
        )

    password_error = validate_password(data.get("password"))
    if password_error:
         return jsonify({"error": password_error}), 400

    user = User(
        name=data["name"],
        email=data["email"],
        password_hash=hash_password(data["password"]),
    )
    try:
        db.session.add(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Two people registering the same email at the same moment
        if User.query.filter_by(email=data["email"]).first():
            return error_response("An account with this email already exists", 409)
        raise

    return jsonify({"message": "Account created", "user": user_to_dict(user)}), 201


@auth_bp.post("/login")
def login():
    try:
        data = validate_login(_json_body())
    except ValidationError as exc:
        return error_response(exc.message, 400, exc.errors)

    user = User.query.filter_by(email=data["email"]).first()
    # Same message for "no such user" and "wrong password" so emails can't be probed
    if user is None or not verify_password(data["password"], user.password_hash):
        return error_response("Invalid email or password", 401)

    token = create_access_token({"sub": str(user.id), "user_id": user.id})
    response = jsonify({"user": user_to_dict(user)})
    return _set_auth_cookie(response, token)


@auth_bp.post("/logout")
def logout():
    response = jsonify({"message": "Logged out"})
    response.delete_cookie(COOKIE_NAME, **_cookie_options())
    return response


@auth_bp.get("/me")
@login_required
def me():
    return jsonify({"user": user_to_dict(current_user())})

@auth_bp.route("/me", methods=["PUT"])
@jwt_required()
def update_me():

    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    # only allow these fields to be changed
    for field in ["name", "username", "bio", "github", "location", "age", "avatar", "profilePic"]:
        if field in data:
            setattr(user, field, data[field])

    db.session.commit()
    return jsonify({"user": user.to_dict()}), 200


