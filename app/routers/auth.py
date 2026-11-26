from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token

from app.database import db
from app.deps import COOKIE_NAME, current_user, error_response, login_required
from app.models import User
from app.schemas import ValidationError, user_to_dict, validate_login, validate_register
from app.security import create_access_token, hash_password, verify_password
from flask import request, jsonify
import os, secrets, smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from app.models import PasswordReset

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


@auth_bp.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    data = request.get_json(silent=True) or {}
    current = data.get("current_password", "")
    new = data.get("new_password", "")
    confirm = data.get("confirm_password", "")

    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return jsonify({"error": "User not found"}), 404
    if not verify_password(current, user.password_hash):
        return jsonify({"error": "Current password is incorrect"}), 400
    if new != confirm:
        return jsonify({"error": "New passwords do not match"}), 400
    error = validate_password(new)
    if error:
        return jsonify({"error": error}), 400
    if verify_password(new, user.password_hash):
        return jsonify({"error": "New password must be different from the current one"}), 400

    user.password_hash = hash_password(new)
    db.session.commit()
    return jsonify({"message": "Password updated"}), 200






OTP_MINUTES = 10
MAX_OTP_ATTEMPTS = 5
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


def send_reset_email(to_email, otp):
    link = f"{FRONTEND_URL}/reset-password?email={to_email}"
    body = (
        f"Your FocusFlow password reset code is: {otp}\n\n"
        f"It expires in {OTP_MINUTES} minutes.\n"
        f"Enter it here: {link}\n\n"
        "If you didn't ask for this, ignore this email."
    )
    host = os.getenv("SMTP_HOST")
    if not host:                      # dev fallback: no email server configured
        print(f"\n[DEV] Password reset OTP for {to_email}: {otp}\n{link}\n")
        return
    msg = EmailMessage()
    msg["Subject"] = "Your FocusFlow password reset code"
    msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER"))
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
        server.send_message(msg)


@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if user:
        PasswordReset.query.filter_by(user_id=user.id, used=False).update({"used": True})
        otp = f"{secrets.randbelow(1_000_000):06d}"
        db.session.add(PasswordReset(
            user_id=user.id,
            otp_hash=hash_password(otp),
            expires_at=datetime.utcnow() + timedelta(minutes=OTP_MINUTES),
        ))
        db.session.commit()
        try:
            send_reset_email(user.email, otp)
        except Exception as e:
            app_logger = __import__("logging").getLogger(__name__)
            app_logger.exception(e)
    # Same answer whether or not the email exists, so nobody can probe for accounts
    return jsonify({"message": "If that email is registered, a code has been sent."}), 200


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()
    new = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    invalid = jsonify({"error": "Invalid or expired code"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return invalid
    reset = (PasswordReset.query.filter_by(user_id=user.id, used=False)
             .order_by(PasswordReset.created_at.desc()).first())
    if not reset or reset.expires_at < datetime.utcnow() or reset.attempts >= MAX_OTP_ATTEMPTS:
        return invalid

    if not verify_password(otp, reset.otp_hash):
        reset.attempts += 1
        db.session.commit()
        return invalid
    if new != confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    error = validate_password(new)
    if error:
        return jsonify({"error": error}), 400

    user.password_hash = hash_password(new)
    reset.used = True
    db.session.commit()
    return jsonify({"message": "Password reset. You can now log in."}), 200