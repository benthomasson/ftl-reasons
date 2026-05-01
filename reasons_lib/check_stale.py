"""Detect stale nodes by comparing source file hashes.

A node is stale when the file it was sourced from has changed since
the node was created. This is detected by comparing the stored
source_hash against the current SHA-256 hash of the source file.
"""

import hashlib
from pathlib import Path

from .network import Network


def hash_file(path: Path) -> str:
    """Full SHA-256 hash of file content (64 hex chars)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_source_path(
    source: str,
    repos: dict[str, Path] | None = None,
    db_dir: Path | None = None,
    agent: str | None = None,
) -> Path | None:
    """Resolve a source string like 'repo-name/path/to/file.md' to an absolute path.

    Tries agent repo first (for agent-imported beliefs where source is relative
    to the agent's repo), then db_dir (for expert repos where sources live next
    to reasons.db), then repos dict by first path component, then ~/git/ fallback.
    """
    if not source:
        return None

    if agent and repos and agent in repos:
        p = repos[agent] / source
        if p.exists():
            return p

    if db_dir:
        p = db_dir / source
        if p.exists():
            return p

    parts = source.split("/", 1)
    if len(parts) < 2:
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
    db_dir: Path | None = None,
    upgrade_hashes: bool = False,
) -> tuple[list[dict], int]:
    """Check all IN nodes for source staleness.

    If upgrade_hashes=True, truncated hashes that are a prefix of the
    current full hash are upgraded in place (caller must save the network).

    Returns (stale_results, upgraded_count).
    """
    if repos is None and network.repos:
        repos = {k: Path(v) for k, v in network.repos.items()}

    results = []
    upgraded = 0

    for nid, node in sorted(network.nodes.items()):
        if node.truth_value != "IN":
            continue
        if not node.source or not node.source_hash:
            continue

        agent = node.metadata.get("agent") if node.metadata else None
        path = resolve_source_path(node.source, repos, db_dir, agent=agent)
        if path is None:
            results.append({
                "node_id": nid,
                "old_hash": node.source_hash,
                "new_hash": None,
                "source": node.source,
                "source_path": None,
                "reason": "source_deleted",
            })
            continue

        current_hash = hash_file(path)
        if current_hash != node.source_hash:
            if len(node.source_hash) == 16 and current_hash.startswith(node.source_hash):
                if upgrade_hashes:
                    node.source_hash = current_hash
                    upgraded += 1
                    continue
                results.append({
                    "node_id": nid,
                    "old_hash": node.source_hash,
                    "new_hash": current_hash,
                    "source": node.source,
                    "source_path": str(path),
                    "reason": "truncated_hash",
                })
                continue
            results.append({
                "node_id": nid,
                "old_hash": node.source_hash,
                "new_hash": current_hash,
                "source": node.source,
                "source_path": str(path),
                "reason": "content_changed",
            })

    return results, upgraded


def hash_sources(
    network: Network,
    repos: dict[str, Path] | None = None,
    force: bool = False,
    db_dir: Path | None = None,
) -> list[dict]:
    """Backfill source hashes for nodes that have a source path but no stored hash.

    If force=True, re-hashes all nodes with sources (even those that already
    have a hash). Use after confirming a source change is expected.

    Returns a list of dicts for each node that was hashed:
        {"node_id": str, "source": str, "hash": str, "was_empty": bool}
    """
    if repos is None and network.repos:
        repos = {k: Path(v) for k, v in network.repos.items()}

    results = []

    for nid, node in sorted(network.nodes.items()):
        if not node.source:
            continue
        if node.source_hash and not force:
            continue

        agent = node.metadata.get("agent") if node.metadata else None
        path = resolve_source_path(node.source, repos, db_dir, agent=agent)
        if path is None:
            continue

        new_hash = hash_file(path)
        was_empty = not node.source_hash
        node.source_hash = new_hash
        results.append({
            "node_id": nid,
            "source": node.source,
            "hash": new_hash,
            "was_empty": was_empty,
        })

    return results
