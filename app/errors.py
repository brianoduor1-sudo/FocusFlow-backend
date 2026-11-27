from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from app.services.github_service import GitHubAPIError

def register_error_handlers(app: Flask) -> None:
    

    @app.errorhandler(GitHubAPIError)
    def handle_github_api_error(err: GitHubAPIError):
        return jsonify({
            "error": {
                "type": "GitHubAPIError",
                "message": err.message,
                "status_code": err.status_code,
            }
        }), err.status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        return jsonify({
            "error": {
                "type": err.name,
                "message": err.description,
                "status_code": err.code,
            }
        }), err.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(err: Exception):
        return jsonify({
            "error": {
                "type": "InternalServerError",
                "message": "An unexpected server error occurred.",
                "status_code": 500,
            }
        }), 500
