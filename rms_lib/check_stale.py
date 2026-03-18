"""Detect stale nodes by comparing source file hashes.

A node is stale when the file it was sourced from has changed since
the node was created. This is detected by comparing the stored
source_hash against the current SHA-256 hash of the source file.
"""

import hashlib
from pathlib import Path

from .network import Network


def hash_file(path: Path) -> str:
    """SHA-256 hash of file content, first 16 hex chars."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def resolve_source_path(source: str, repos: dict[str, Path] | None = None) -> Path | None:
    """Resolve a source string like 'repo-name/path/to/file.md' to an absolute path.

    If repos is provided, uses it as a mapping of repo names to paths.
    Otherwise tries ~/git/<repo-name>/path/to/file.md.
    """
    if not source:
        return None

    parts = source.split("/", 1)
    if len(parts) < 2:
        # No slash — treat as a bare filename in current directory
        p = Path(source)
        return p if p.exists() else None

    repo_name, rel_path = parts

    if repos and repo_name in repos:
        p = repos[repo_name] / rel_path
    else:
        p = Path.home() / "git" / repo_name / rel_path

    return p if p.exists() else None


def check_stale(
    network: Network,
    repos: dict[str, Path] | None = None,
) -> list[dict]:
    """Check all IN nodes for source staleness.

    Returns a list of dicts for each stale node:
        {"node_id": str, "old_hash": str, "new_hash": str, "source": str}
    """
    results = []

    for nid, node in sorted(network.nodes.items()):
        if node.truth_value != "IN":
            continue
        if not node.source or not node.source_hash:
            continue

        path = resolve_source_path(node.source, repos)
        if path is None:
            continue

        current_hash = hash_file(path)
        if current_hash != node.source_hash:
            results.append({
                "node_id": nid,
                "old_hash": node.source_hash,
                "new_hash": current_hash,
                "source": node.source,
                "source_path": str(path),
            })

    return results
