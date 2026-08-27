"""
LaunchPad-AI — GitHub App authentication helper.

Generates short-lived GitHub installation tokens from the App's private key
stored in Secret Manager. The agent's github_tool uses these tokens to open
PRs and issues on the user's repos.

Flow:
  1. Read the .pem private key from Secret Manager (cached).
  2. Generate a short-lived JWT signed with the key (10 min max per GitHub spec).
  3. Exchange the JWT for an installation access token via GitHub API.
  4. Cache the token until 5 min before expiry, then auto-refresh.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

# ── Lazy-initialised state ───────────────────────────────────
_secret_client: secretmanager.SecretManagerServiceClient | None = None
_private_key_pem: bytes | None = None
_cached_token: str | None = None
_token_expires_at: float = 0.0


def _get_private_key() -> bytes:
    """Fetch the GitHub App private key from Secret Manager (cached)."""
    global _secret_client, _private_key_pem
    if _private_key_pem is not None:
        return _private_key_pem

    if _secret_client is None:
        _secret_client = secretmanager.SecretManagerServiceClient()

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    secret_name = f"projects/{project}/secrets/github-app-key/versions/latest"
    response = _secret_client.access_secret_version(request={"name": secret_name})
    _private_key_pem = response.payload.data
    return _private_key_pem


def _generate_jwt() -> str:
    """
    Generate a JWT signed with the GitHub App's private key.
    Valid for 10 minutes (GitHub's maximum).
    """
    app_id = os.environ["GITHUB_APP_ID"]
    pem_bytes = _get_private_key()

    now = int(time.time())
    payload = {
        "iat": now - 60,        # issued at (60s clock skew buffer)
        "exp": now + (10 * 60), # expires in 10 minutes
        "iss": app_id,          # GitHub App ID
    }

    key = RSAKey.import_key(pem_bytes)
    token = jwt.encode({"alg": "RS256"}, payload, key)
    return token


_cached_tokens: dict[str, tuple[str, float]] = {}


def _get_installation_id(jwt_token: str, owner: str | None = None) -> int:
    """
    Get the installation ID for our GitHub App.
    If owner is specified, matches the account login; otherwise falls back to the first installation.
    """
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = httpx.get(
        "https://api.github.com/app/installations",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    installations = resp.json()

    if not installations:
        raise RuntimeError(
            "No GitHub App installations found. "
            "Ask the repo owner to install the app on their account."
        )

    if owner:
        owner_lower = owner.strip().lower()
        for inst in installations:
            account_login = inst.get("account", {}).get("login", "").lower()
            if account_login == owner_lower:
                return inst["id"]
        logger.warning(
            "No installation found specifically for owner '%s'. Falling back to first installation (%s)",
            owner,
            installations[0].get("account", {}).get("login"),
        )

    return installations[0]["id"]


def get_installation_token(owner: str | None = None) -> str:
    """
    Return a valid GitHub installation access token for the given repo owner,
    refreshing if needed. Tokens are valid for 1 hour.
    """
    global _cached_tokens
    cache_key = (owner or "default").strip().lower()
    now = time.time()

    # Return cached token if still valid (with 5 min buffer)
    if cache_key in _cached_tokens:
        token, expires_at = _cached_tokens[cache_key]
        if now < (expires_at - 300):
            return token

    logger.info("Generating new GitHub installation token (owner: %s)...", owner or "default")

    # Step 1: Generate JWT
    jwt_token = _generate_jwt()

    # Step 2: Get installation ID for the owner
    installation_id = _get_installation_id(jwt_token, owner=owner)

    # Step 3: Exchange JWT for installation token
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    token = data["token"]
    _cached_tokens[cache_key] = (token, now + 3600)

    logger.info("GitHub installation token acquired for '%s' (expires in ~1h)", owner or "default")
    return token
