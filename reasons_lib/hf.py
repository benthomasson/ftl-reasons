"""Download belief networks from HuggingFace repos."""

import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


HF_BASE = "https://huggingface.co"


def _resolve_token(token: str | None = None) -> str | None:
    """Resolve HuggingFace token: explicit > HF_TOKEN env > cached file."""
    if token:
        return token
    token = os.environ.get("HF_TOKEN")
    if token:
        return token
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.exists():
        return token_path.read_text().strip()
    return None


def _parse_repo_id(repo_id: str) -> str:
    """Extract user/repo from a repo ID or HuggingFace URL."""
    repo_id = repo_id.rstrip("/")
    if repo_id.startswith(("http://", "https://")):
        # https://huggingface.co/user/repo -> user/repo
        parts = repo_id.split("huggingface.co/", 1)
        if len(parts) == 2:
            return parts[1]
        raise ValueError(f"Not a HuggingFace URL: {repo_id}")
    return repo_id


def download_network(repo_id: str, token: str | None = None) -> str:
    """Download network.json from a HuggingFace repo.

    Args:
        repo_id: HuggingFace repo ID (user/repo) or full URL
        token: Optional auth token (falls back to HF_TOKEN env or cached token)

    Returns:
        JSON string of the network
    """
    parsed_id = _parse_repo_id(repo_id)
    url = f"{HF_BASE}/{parsed_id}/resolve/main/network.json"

    resolved_token = _resolve_token(token)
    headers = {}
    if resolved_token:
        headers["Authorization"] = f"Bearer {resolved_token}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as e:
        if e.code == 401:
            raise RuntimeError(
                f"Authentication required for {parsed_id}. "
                "Run 'huggingface-cli login' or pass --token."
            ) from e
        if e.code == 404:
            raise RuntimeError(
                f"Repository or file not found: {parsed_id}/network.json"
            ) from e
        raise
