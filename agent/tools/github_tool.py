"""
LaunchPad-AI — GitHub tool (agent/tools/github_tool.py).

Implements the github_* tool signatures frozen in CLAUDE.md. Auth is via a
GitHub App: a short-lived JWT signed with the App's private key (fetched from
Secret Manager, secret `github-app-key`) is exchanged for an installation
access token, which is what actually calls the REST API. No token is ever
hardcoded — env vars only name *which* app/installation, never a secret.

Required env vars: GOOGLE_CLOUD_PROJECT, GITHUB_APP_ID.
Optional: GITHUB_APP_INSTALLATION_ID (skips the installations lookup call).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any

import requests
from google.auth import crypt, jwt
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_JWT_TTL_SECONDS = 8 * 60  # GitHub caps App JWTs at 10 minutes; leave margin.
_TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60  # refresh before GitHub's ~1hr expiry

_secret_client: secretmanager.SecretManagerServiceClient | None = None
_app_private_key: str | None = None
_installation_token: str | None = None
_installation_token_expires_at: float = 0.0


def _get_secret_client() -> secretmanager.SecretManagerServiceClient:
    global _secret_client
    if _secret_client is None:
        _secret_client = secretmanager.SecretManagerServiceClient()
    return _secret_client


def _get_app_private_key() -> str:
    """Fetches the GitHub App's PEM private key from Secret Manager (cached)."""
    global _app_private_key
    if _app_private_key is not None:
        return _app_private_key
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    name = f"projects/{project}/secrets/github-app-key/versions/latest"
    response = _get_secret_client().access_secret_version(request={"name": name})
    _app_private_key = response.payload.data.decode("utf-8")
    return _app_private_key


def _build_app_jwt() -> str:
    app_id = os.environ["GITHUB_APP_ID"]
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + _JWT_TTL_SECONDS, "iss": app_id}
    signer = crypt.RSASigner.from_string(_get_app_private_key())
    return jwt.encode(signer, payload).decode("utf-8")


_installation_tokens: dict[str, tuple[str, float]] = {}


def _get_installation_id(jwt_token: str, owner: str | None = None) -> str:
    override = os.environ.get("GITHUB_APP_INSTALLATION_ID")
    if override:
        return override

    resp = requests.get(
        f"{_GITHUB_API}/app/installations",
        headers={"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    )
    resp.raise_for_status()
    installations = resp.json()
    if not installations:
        raise RuntimeError("GitHub App has no installations — install it on the target account.")

    if owner:
        owner_lower = owner.strip().lower()
        for inst in installations:
            if inst.get("account", {}).get("login", "").lower() == owner_lower:
                return str(inst["id"])

    return str(installations[0]["id"])


def _get_installation_token(owner: str | None = None) -> str:
    """Returns a cached installation access token, refreshing it once it's near expiry."""
    global _installation_tokens
    cache_key = (owner or "default").strip().lower()
    now = time.time()

    if cache_key in _installation_tokens:
        token, expires_at = _installation_tokens[cache_key]
        if now < expires_at:
            return token

    jwt_token = _build_app_jwt()
    installation_id = _get_installation_id(jwt_token, owner=owner)
    resp = requests.post(
        f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["token"]
    expires_at = now + (60 * 60) - _TOKEN_REFRESH_MARGIN_SECONDS
    _installation_tokens[cache_key] = (token, expires_at)
    return token


def _auth_headers(owner: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_installation_token(owner=owner)}",
        "Accept": "application/vnd.github+json",
    }


_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<url>[^)\s]+)")


def _extract_images(readme_text: str) -> list[str]:
    return _IMAGE_RE.findall(readme_text)


def _get_headers_for_owner(owner: str | None = None) -> dict[str, str]:
    try:
        return _auth_headers(owner)
    except TypeError:
        return _auth_headers()


def github_get_repo(repo: str) -> dict[str, Any]:
    """Fetches repo metadata, README, languages, and top-level tree.

    Returns: {name, description, readme, langs, tree, images[]}
    """
    owner = repo.split("/")[0] if "/" in repo else None
    headers = _get_headers_for_owner(owner)

    repo_resp = requests.get(f"{_GITHUB_API}/repos/{repo}", headers=headers, timeout=10)
    repo_resp.raise_for_status()
    repo_data = repo_resp.json()

    readme_text = ""
    readme_resp = requests.get(f"{_GITHUB_API}/repos/{repo}/readme", headers=headers, timeout=10)
    if readme_resp.status_code == 200:
        content = readme_resp.json().get("content", "")
        readme_text = base64.b64decode(content).decode("utf-8", errors="replace")

    langs_resp = requests.get(f"{_GITHUB_API}/repos/{repo}/languages", headers=headers, timeout=10)
    langs_resp.raise_for_status()
    langs = list(langs_resp.json().keys())

    tree_resp = requests.get(f"{_GITHUB_API}/repos/{repo}/contents", headers=headers, timeout=10)
    tree = [item["name"] for item in tree_resp.json()] if tree_resp.status_code == 200 else []

    return {
        "name": repo_data.get("name", repo),
        "description": repo_data.get("description") or "",
        "homepage": repo_data.get("homepage") or "",
        "readme": readme_text,
        "langs": langs,
        "tree": tree,
        "images": _extract_images(readme_text),
    }


def github_get_file(repo: str, path: str, ref: str | None = None) -> str | None:
    """Fetches a file's raw text content from `repo` at `path` (optionally at
    a specific ref/branch). Returns None if the file doesn't exist (404).
    """
    owner = repo.split("/")[0] if "/" in repo else None
    headers = _get_headers_for_owner(owner)
    params = {"ref": ref} if ref else {}
    resp = requests.get(
        f"{_GITHUB_API}/repos/{repo}/contents/{path}", headers=headers, params=params, timeout=10
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    content = resp.json().get("content", "")
    return base64.b64decode(content).decode("utf-8", errors="replace")


def github_open_pr(repo: str, branch: str, title: str, body: str, files: dict[str, str]) -> str:
    """Creates `branch` off the default branch, commits `files` (path -> content)
    onto it, and opens a PR into the default branch. Returns the PR URL.

    Each file is created or updated as appropriate: GitHub's Contents API
    requires the current file's `sha` to overwrite an existing file (and
    rejects it entirely for a brand-new one), so each path is checked on the
    new branch first.
    """
    owner = repo.split("/")[0] if "/" in repo else None
    headers = _get_headers_for_owner(owner)

    repo_resp = requests.get(f"{_GITHUB_API}/repos/{repo}", headers=headers, timeout=10)
    repo_resp.raise_for_status()
    default_branch = repo_resp.json()["default_branch"]

    ref_resp = requests.get(
        f"{_GITHUB_API}/repos/{repo}/git/ref/heads/{default_branch}", headers=headers, timeout=10
    )
    ref_resp.raise_for_status()
    base_sha = ref_resp.json()["object"]["sha"]

    branch_resp = requests.post(
        f"{_GITHUB_API}/repos/{repo}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        timeout=10,
    )
    branch_resp.raise_for_status()

    for path, content in files.items():
        existing_resp = requests.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{path}",
            headers=headers,
            params={"ref": branch},
            timeout=10,
        )
        payload = {
            "message": f"LaunchPad-AI: update {path}",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if existing_resp.status_code == 200:
            payload["sha"] = existing_resp.json()["sha"]

        put_resp = requests.put(
            f"{_GITHUB_API}/repos/{repo}/contents/{path}", headers=headers, json=payload, timeout=10
        )
        put_resp.raise_for_status()

    pr_resp = requests.post(
        f"{_GITHUB_API}/repos/{repo}/pulls",
        headers=headers,
        json={"title": title, "body": body, "head": branch, "base": default_branch},
        timeout=10,
    )
    pr_resp.raise_for_status()
    return pr_resp.json()["html_url"]


_SHALLOW_LISTING_EXTENSIONS = (".json", ".md", ".jsx", ".tsx", ".html", ".astro")


def _is_relevant_shallow_listing_file(name: str) -> bool:
    if name.endswith(_SHALLOW_LISTING_EXTENSIONS):
        return True
    lower = name.lower()
    return "config" in lower and lower.endswith((".js", ".mjs", ".ts", ".cjs"))


def github_list_repo_shallow(repo: str, max_files: int = 40) -> list[str]:
    """Lists up to `max_files` relevant (source/data/config) file paths from
    the repo's root and one level into its subdirectories — root + one
    level, NOT a full recursive tree walk, to keep this cheap and
    read-only. Returns relative paths. GET calls only; never writes.
    """
    headers = _auth_headers()
    paths: list[str] = []

    root_resp = requests.get(f"{_GITHUB_API}/repos/{repo}/contents", headers=headers, timeout=10)
    if root_resp.status_code != 200:
        return paths
    root_items = root_resp.json()

    subdirs: list[str] = []
    for item in root_items:
        if len(paths) >= max_files:
            return paths[:max_files]
        if item["type"] == "file" and _is_relevant_shallow_listing_file(item["name"]):
            paths.append(item["path"])
        elif item["type"] == "dir" and not item["name"].startswith("."):
            subdirs.append(item["path"])

    for dir_path in subdirs:
        if len(paths) >= max_files:
            break
        dir_resp = requests.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{dir_path}", headers=headers, timeout=10
        )
        if dir_resp.status_code != 200:
            continue
        for item in dir_resp.json():
            if len(paths) >= max_files:
                break
            if item["type"] == "file" and _is_relevant_shallow_listing_file(item["name"]):
                paths.append(item["path"])

    return paths[:max_files]


def github_merge_pr(repo: str, pr_number: int) -> dict[str, Any]:
    """Merges pull request `pr_number` on `repo`. Returns {merged: bool, sha: str | None}.

    Raises on failure (not mergeable, branch protection, permissions, a
    conflicting head change, etc.) rather than reporting a failed merge as
    successful — the caller decides how to degrade (leave the PR open).
    Automatically deletes the temporary remote feature branch upon successful merge.
    """
    owner = repo.split("/")[0] if "/" in repo else None
    headers = _get_headers_for_owner(owner)

    # Fetch PR details to obtain the head branch ref
    branch_ref = None
    try:
        pr_resp = requests.get(
            f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}",
            headers=headers,
            timeout=10,
        )
        if pr_resp.status_code == 200:
            branch_ref = pr_resp.json().get("head", {}).get("ref")
    except Exception:
        pass

    resp = requests.put(
        f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/merge",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    # Automatically delete the temporary feature branch on successful merge
    if data.get("merged") and branch_ref and branch_ref.startswith("launchpad-ai/"):
        try:
            requests.delete(
                f"{_GITHUB_API}/repos/{repo}/git/refs/heads/{branch_ref}",
                headers=headers,
                timeout=10,
            )
        except Exception:
            logger.warning("Could not delete merged branch %s on %s", branch_ref, repo)

    return {"merged": bool(data.get("merged", False)), "sha": data.get("sha")}


def github_list_installation_repos() -> list[dict[str, Any]]:
    """Lists repos accessible to this GitHub App installation (raw GitHub
    repo objects — callers pick the fields they need)."""
    resp = requests.get(
        f"{_GITHUB_API}/installation/repositories", headers=_auth_headers(), timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("repositories", [])


def github_open_issue(repo: str, title: str, body: str) -> str:
    """Opens an issue on `repo`. Returns the issue URL."""
    resp = requests.post(
        f"{_GITHUB_API}/repos/{repo}/issues",
        headers=_auth_headers(),
        json={"title": title, "body": body},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["html_url"]
