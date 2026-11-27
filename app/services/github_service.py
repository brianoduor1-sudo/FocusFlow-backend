import httpx
from app.security import decrypt_token

class GitHubServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

class GitHubService:
    BASE_URL = "https://api.github.com"

    def __init__(self, encrypted_token: str | None = None, raw_token: str | None = None):
        token = None
        if raw_token:
            token = raw_token
        elif encrypted_token and encrypted_token != "public_only":
            token = decrypt_token(encrypted_token)

        self.has_token = bool(token)
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FocusFlow-App",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _request(self, method: str, path: str, params: dict | None = None):
        with httpx.Client(timeout=10.0) as client:
            response = client.request(
                method=method,
                url=f"{self.BASE_URL}{path}",
                headers=self.headers,
                params=params,
            )

        if response.status_code == 401:
            raise GitHubServiceError("GitHub token is invalid or expired.", 401)
        if response.status_code == 403:
            raise GitHubServiceError("GitHub API rate limit exceeded. Try again shortly or add a token.", 403)
        if response.status_code == 404:
            raise GitHubServiceError("GitHub user or repository not found.", 404)
        if response.status_code >= 400:
            raise GitHubServiceError("GitHub API request failed.", response.status_code)

        return response.json()

    def verify_user(self, github_username: str | None = None) -> dict:
        if self.has_token and not github_username:
            data = self._request("GET", "/user")
        elif github_username:
            data = self._request("GET", f"/users/{github_username}")
        else:
            raise GitHubServiceError("Please provide a GitHub username.", 400)

        return {
            "github_username": data.get("login"),
            "name": data.get("name"),
            "bio": data.get("bio"),
            "avatar_url": data.get("avatar_url"),
            "profile_url": data.get("html_url"),
            "public_repos": data.get("public_repos", 0),
            "followers": data.get("followers", 0),
        }

    def list_repositories(self, github_username: str, per_page: int = 30) -> list[dict]:
        if self.has_token:
            repos = self._request(
                "GET",
                "/user/repos",
                params={"sort": "updated", "affiliation": "owner,collaborator", "per_page": per_page},
            )
        else:
            repos = self._request(
                "GET",
                f"/users/{github_username}/repos",
                params={"sort": "updated", "type": "owner", "per_page": per_page},
            )
        return [
            {
                "id": repo["id"],
                "name": repo["name"],
                "full_name": repo["full_name"],
                "description": repo.get("description"),
                "private": repo["private"],
                "language": repo.get("language"),
                "stargazers_count": repo.get("stargazers_count", 0),
                "open_issues_count": repo.get("open_issues_count", 0),
                "html_url": repo["html_url"],
                "updated_at": repo["updated_at"],
            }
            for repo in repos
        ]

    def get_repo_commits(self, owner: str, repo: str, per_page: int = 15) -> list[dict]:
        commits = self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits",
            params={"per_page": per_page},
        )
        return [
            {
                "sha": item["sha"][:7],
                "full_sha": item["sha"],
                "message": item["commit"]["message"].splitlines()[0],
                "author_name": item["commit"]["author"]["name"],
                "author_username": item["author"]["login"] if item.get("author") else None,
                "date": item["commit"]["author"]["date"],
                "html_url": item["html_url"],
            }
            for item in commits
        ]

    def list_open_issues(self, github_username: str, per_page: int = 15) -> list[dict]:
        data = self._request(
            "GET",
            "/search/issues",
            params={
                "q": f"author:{github_username} is:issue is:open",
                "sort": "updated",
                "order": "desc",
                "per_page": per_page,
            },
        )
        return [
            {
                "id": issue["id"],
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "repository": issue["repository_url"].split("/repos/")[-1],
                "labels": [lbl["name"] for lbl in issue.get("labels", [])],
                "created_at": issue["created_at"],
                "updated_at": issue["updated_at"],
                "html_url": issue["html_url"],
            }
            for issue in data.get("items", [])
        ]

    def list_pull_requests(self, github_username: str, per_page: int = 15) -> list[dict]:
        data = self._request(
            "GET",
            "/search/issues",
            params={
                "q": f"author:{github_username} is:pr is:open",
                "sort": "updated",
                "order": "desc",
                "per_page": per_page,
            },
        )
        return [
            {
                "id": pr["id"],
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "draft": pr.get("draft", False),
                "repository": pr["repository_url"].split("/repos/")[-1],
                "created_at": pr["created_at"],
                "updated_at": pr["updated_at"],
                "html_url": pr["html_url"],
            }
            for pr in data.get("items", [])
        ]
