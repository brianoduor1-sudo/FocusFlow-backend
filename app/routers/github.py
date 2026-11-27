from datetime import datetime
from flask import Blueprint, jsonify, request

from app.database import db
from app.deps import current_user, error_response, login_required
from app.models import GitHubAccount
from app.security import encrypt_token
from app.services.github_service import GitHubService, GitHubServiceError

github_bp = Blueprint("github", __name__)

def _clean_github_username(raw: str) -> str:
    val = (raw or "").strip().rstrip("/")
    if "github.com/" in val:
        val = val.split("github.com/")[-1].split("/")[0]
    return val.lstrip("@")

def _get_user_github_account(user_id: int) -> GitHubAccount | None:
    return GitHubAccount.query.filter_by(user_id=user_id).first()

@github_bp.errorhandler(GitHubServiceError)
def handle_github_error(err: GitHubServiceError):
    return jsonify({"error": err.message}), err.status_code

@github_bp.route("/status", methods=["GET"])
@login_required
def github_connection_status():
    user_id = current_user().id
    account = _get_user_github_account(user_id)
    if not account:
        return jsonify({"connected": False}), 200

    service = GitHubService(encrypted_token=account.access_token_encrypted)
    profile = service.verify_user(github_username=account.github_username)
    return jsonify({
        "connected": True,
        "github_username": account.github_username,
        "connected_at": account.connected_at.isoformat() if account.connected_at else None,
        "profile": profile,
    }), 200

@github_bp.route("/connect", methods=["POST"])
@login_required
def connect_github_account():
    user_id = current_user().id
    data = request.get_json() or {}
    github_username = _clean_github_username(data.get("github_username", ""))
    access_token = (data.get("access_token") or "").strip()

    if not github_username and not access_token:
        return error_response("Please enter your GitHub username.", 400)

    gh_service = GitHubService(raw_token=access_token or None)
    gh_profile = gh_service.verify_user(github_username=github_username or None)

    resolved_username = gh_profile["github_username"]
    encrypted = encrypt_token(access_token) if access_token else "public_only"

    account = _get_user_github_account(user_id)
    if account:
        account.github_username = resolved_username
        account.access_token_encrypted = encrypted
        account.connected_at = datetime.utcnow()
    else:
        account = GitHubAccount(
            user_id=user_id,
            github_username=resolved_username,
            access_token_encrypted=encrypted,
            connected_at=datetime.utcnow(),
        )
        db.session.add(account)

    db.session.commit()
    return jsonify({
        "connected": True,
        "github_username": account.github_username,
        "connected_at": account.connected_at.isoformat(),
        "profile": gh_profile,
    }), 201

@github_bp.route("/disconnect", methods=["DELETE"])
@login_required
def disconnect_github_account():
    user_id = current_user().id
    account = _get_user_github_account(user_id)
    if not account:
        return error_response("No connected GitHub account found.", 404)

    db.session.delete(account)
    db.session.commit()
    return jsonify({"connected": False, "message": "GitHub account disconnected successfully."}), 200

@github_bp.route("/repositories", methods=["GET"])
@login_required
def list_github_repositories():
    user_id = current_user().id
    account = _get_user_github_account(user_id)
    if not account:
        return error_response("GitHub account is not connected.", 404)

    service = GitHubService(encrypted_token=account.access_token_encrypted)
    repositories = service.list_repositories(github_username=account.github_username)
    return jsonify({"github_username": account.github_username, "repositories": repositories}), 200

@github_bp.route("/repositories/<owner>/<repo>/commits", methods=["GET"])
@login_required
def get_repository_commits(owner: str, repo: str):
    user_id = current_user().id
    account = _get_user_github_account(user_id)
    if not account:
        return error_response("GitHub account is not connected.", 404)

    service = GitHubService(encrypted_token=account.access_token_encrypted)
    commits = service.get_repo_commits(owner=owner, repo=repo)
    return jsonify({"repository": f"{owner}/{repo}", "commits": commits}), 200

@github_bp.route("/issues", methods=["GET"])
@login_required
def list_github_issues():
    user_id = current_user().id
    account = _get_user_github_account(user_id)
    if not account:
        return error_response("GitHub account is not connected.", 404)

    service = GitHubService(encrypted_token=account.access_token_encrypted)
    issues = service.list_open_issues(github_username=account.github_username)
    return jsonify({"github_username": account.github_username, "issues": issues}), 200

@github_bp.route("/pulls", methods=["GET"])
@login_required
def list_github_pull_requests():
    user_id = current_user().id
    account = _get_user_github_account(user_id)
    if not account:
        return error_response("GitHub account is not connected.", 404)

    service = GitHubService(encrypted_token=account.access_token_encrypted)
    pulls = service.list_pull_requests(github_username=account.github_username)
    return jsonify({"github_username": account.github_username, "pulls": pulls}), 200
