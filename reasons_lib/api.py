"""Functional Python API for the Reason Maintenance System.

This module provides standalone functions that any Python caller can use
(CLI, LangGraph tools, scripts) without dealing with Storage lifecycle
or argparse. Each function opens the database, operates, saves, and closes.

All functions return dicts suitable for JSON serialization.
"""

import json
import re
from pathlib import Path

from . import Justification
from .network import Network
from .storage import Storage


DEFAULT_DB = "reasons.db"


def _is_visible(node, visible_to: list[str]) -> bool:
    """Check if a node is visible given the caller's access tags.

    A node is visible if its access_tags are all contained in visible_to.
    Nodes with no access_tags are always visible.
    """
    tags = node.metadata.get("access_tags", [])
    if not tags:
        return True
    visible_set = set(visible_to)
    return all(t in visible_set for t in tags)


def _resolve_namespace(node_id: str, namespace: str | None) -> str:
    """Prefix node_id with namespace if provided and not already namespaced.

    Skips prefixing if the node_id already contains a ':' (already namespaced,
    possibly from a different namespace for cross-namespace references).
    """
    if namespace and ":" not in node_id:
        return f"{namespace}:{node_id}"
    return node_id


def _with_network(db_path: str, write: bool = False):
    """Context manager pattern for load/operate/save."""
    class _Ctx:
        def __init__(self):
            self.store = Storage(db_path)
            self.network = self.store.load()

        def __enter__(self):
            return self.network

        def __exit__(self, exc_type, exc_val, exc_tb):
            if write and exc_type is None:
                self.store.save(self.network)
            self.store.close()
            return False

    return _Ctx()


def init_db(db_path: str = DEFAULT_DB, force: bool = False) -> dict:
    """Initialize a new RMS database.

    Returns: {"db_path": str, "created": bool}
    """
    p = Path(db_path)
    if p.exists() and not force:
        raise FileExistsError(f"Database already exists: {db_path}")
    if p.exists() and force:
        p.unlink()
    store = Storage(db_path)
    store.close()
    return {"db_path": str(p), "created": True}


def ensure_namespace(namespace: str, db_path: str = DEFAULT_DB) -> dict:
    """Ensure a namespace premise node exists (namespace:active).

    Creates the premise if it doesn't exist. This is the node that all
    beliefs in this namespace depend on — retracting it cascades OUT
    every belief from this namespace.

    Returns: {"namespace": str, "active_node": str, "created": bool}
    """
    active_id = f"{namespace}:active"
    with _with_network(db_path, write=True) as net:
        created = False
        if active_id not in net.nodes:
            net.add_node(
                id=active_id,
                text=f"Agent '{namespace}' beliefs are trusted",
                metadata={"agent": namespace, "role": "agent_premise"},
            )
            created = True
        return {"namespace": namespace, "active_node": active_id, "created": created}


def list_namespaces(db_path: str = DEFAULT_DB) -> dict:
    """List all namespaces (agents) in the database.

    Detects namespaces by looking for nodes with ':active' suffix
    that have agent_premise role in metadata.

    Returns: {"namespaces": list[dict]}
    """
    with _with_network(db_path) as net:
        namespaces = []
        for nid, node in sorted(net.nodes.items()):
            if nid.endswith(":active") and node.metadata.get("role") == "agent_premise":
                ns = nid[:-len(":active")]
                # Count beliefs in this namespace
                count = sum(1 for n in net.nodes if n.startswith(f"{ns}:") and n != nid)
                in_count = sum(
                    1 for n, nd in net.nodes.items()
                    if n.startswith(f"{ns}:") and n != nid and nd.truth_value == "IN"
                )
                namespaces.append({
                    "namespace": ns,
                    "active_node": nid,
                    "active": node.truth_value == "IN",
                    "total_beliefs": count,
                    "in_beliefs": in_count,
                })
        return {"namespaces": namespaces}


def add_node(
    node_id: str,
    text: str,
    sl: str = "",
    cp: str = "",
    unless: str = "",
    label: str = "",
    source: str = "",
    namespace: str | None = None,
    any_mode: bool = False,
    access_tags: list[str] | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Add a node to the network.

    Args:
        node_id: Node identifier
        text: Node text
        sl: Comma-separated antecedent IDs for SL justification
        cp: Comma-separated antecedent IDs for CP justification
        unless: Comma-separated outlist IDs (must be OUT for justification to hold)
        label: Justification label
        source: Provenance (repo:path)
        namespace: Optional namespace prefix (auto-creates ns:active premise)
        any_mode: If True, expand SL into one justification per antecedent (OR)
        access_tags: Data source provenance tags for access control
        db_path: Path to RMS database

    Returns: {"node_id": str, "truth_value": str, "type": str, "premise_count": int}
    """
    outlist = [o.strip() for o in unless.split(",") if o.strip()] if unless else []
    justifications = []
    if sl:
        antecedents = [a.strip() for a in sl.split(",")]
        if any_mode and len(antecedents) > 1:
            for a in antecedents:
                justifications.append(Justification(type="SL", antecedents=[a], outlist=outlist, label=label))
        else:
            justifications.append(Justification(type="SL", antecedents=antecedents, outlist=outlist, label=label))
    elif cp:
        antecedents = [a.strip() for a in cp.split(",")]
        justifications.append(Justification(type="CP", antecedents=antecedents, outlist=outlist, label=label))
    elif outlist:
        # Outlist-only justification (no inlist) — premise that holds unless something is believed
        justifications.append(Justification(type="SL", antecedents=[], outlist=outlist, label=label))

    with _with_network(db_path, write=True) as net:
        # Namespace support: prefix node_id and add dependency on ns:active
        if namespace:
            node_id = _resolve_namespace(node_id, namespace)
            active_id = f"{namespace}:active"

            # Ensure the namespace premise exists
            if active_id not in net.nodes:
                net.add_node(
                    id=active_id,
                    text=f"Agent '{namespace}' beliefs are trusted",
                    metadata={"agent": namespace, "role": "agent_premise"},
                )

            # Add ns:active as antecedent to the justification
            if justifications:
                # Prepend active_id to existing antecedents
                j = justifications[0]
                if active_id not in j.antecedents:
                    j.antecedents.insert(0, active_id)
            else:
                # No explicit justification — create SL depending on ns:active
                justifications.append(Justification(
                    type="SL",
                    antecedents=[active_id],
                    outlist=outlist,
                    label=label or f"added by agent: {namespace}",
                ))

            # Also resolve namespace in antecedent references
            for j in justifications:
                j.antecedents = [_resolve_namespace(a, namespace) for a in j.antecedents]
                j.outlist = [_resolve_namespace(o, namespace) for o in j.outlist]

        metadata = {}
        if access_tags:
            metadata["access_tags"] = sorted(set(access_tags))

        node = net.add_node(
            id=node_id,
            text=text,
            justifications=justifications or None,
            source=source,
            metadata=metadata or None,
        )
        jtype = justifications[0].type if justifications else "premise"
        max_premises = max((len(j.antecedents) for j in justifications), default=0)
        return {
            "node_id": node_id,
            "truth_value": node.truth_value,
            "type": jtype,
            "premise_count": max_premises,
        }


def add_justification(
    node_id: str,
    sl: str = "",
    cp: str = "",
    unless: str = "",
    label: str = "",
    namespace: str | None = None,
    any_mode: bool = False,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Add a new justification to an existing node.

    Args:
        node_id: Node to add justification to
        sl: Comma-separated antecedent IDs for SL justification
        cp: Comma-separated antecedent IDs for CP justification
        unless: Comma-separated outlist IDs (must be OUT for justification to hold)
        label: Justification label
        namespace: Optional namespace prefix
        any_mode: If True, expand SL into one justification per antecedent (OR)
        db_path: Path to RMS database

    Returns: {"node_id", "old_truth_value", "new_truth_value", "changed", "premise_count"}
    """
    outlist = [o.strip() for o in unless.split(",") if o.strip()] if unless else []

    if sl:
        antecedents = [a.strip() for a in sl.split(",")]
        jtype = "SL"
    elif cp:
        antecedents = [a.strip() for a in cp.split(",")]
        jtype = "CP"
    elif outlist:
        antecedents = []
        jtype = "SL"
    else:
        raise ValueError("Must provide --sl, --cp, or --unless")

    with _with_network(db_path, write=True) as net:
        if namespace:
            node_id = _resolve_namespace(node_id, namespace)
            antecedents = [_resolve_namespace(a, namespace) for a in antecedents]
            outlist = [_resolve_namespace(o, namespace) for o in outlist]

        if any_mode and jtype == "SL" and len(antecedents) > 1:
            result = None
            for a in antecedents:
                j = Justification(type="SL", antecedents=[a], outlist=outlist, label=label)
                result = net.add_justification(node_id, j)
            result["premise_count"] = 1
            return result

        justification = Justification(
            type=jtype, antecedents=antecedents, outlist=outlist, label=label,
        )
        result = net.add_justification(node_id, justification)
        result["premise_count"] = len(antecedents)
        return result


def retract_node(node_id: str, reason: str = "", db_path: str = DEFAULT_DB) -> dict:
    """Retract a node and cascade.

    Args:
        node_id: Node to retract
        reason: Why this node is being retracted
        db_path: Path to database

    Returns: {"changed", "went_out", "went_in", "restoration_hints"}
    """
    with _with_network(db_path, write=True) as net:
        before = {nid: n.truth_value for nid, n in net.nodes.items()}
        changed = net.retract(node_id, reason=reason)
        went_out = [nid for nid in changed if before.get(nid) == "IN" and net.nodes[nid].truth_value == "OUT"]
        went_in = [nid for nid in changed if before.get(nid) == "OUT" and net.nodes[nid].truth_value == "IN"]

        hints = []
        for nid in went_out:
            if nid == node_id:
                continue
            node = net.nodes[nid]
            for j in node.justifications:
                if j.type == "SL" and len(j.antecedents) >= 2:
                    still_in = [a for a in j.antecedents if a in net.nodes and net.nodes[a].truth_value == "IN"]
                    if still_in:
                        hints.append({
                            "node_id": nid,
                            "all_premises": j.antecedents,
                            "surviving_premises": still_in,
                        })
                    break

        return {"changed": changed, "went_out": went_out, "went_in": went_in, "restoration_hints": hints}


def what_if_retract(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Simulate retracting a node without mutating the database.

    Loads the network read-only, performs the retraction in memory,
    and returns the cascade effects. The database is not modified.
    Tracks both nodes that go OUT (cascade) and nodes that go IN
    (restoration from outlist — gated beliefs whose blocker is removed).

    Returns: {"node_id": str, "retracted": list[dict], "restored": list[dict], ...}
    """
    with _with_network(db_path, write=False) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")

        node = net.nodes[node_id]
        if node.truth_value == "OUT":
            return {
                "node_id": node_id,
                "already_out": True,
                "retracted": [],
                "restored": [],
                "total_affected": 0,
            }

        # Snapshot truth values before
        before = {nid: n.truth_value for nid, n in net.nodes.items()}

        # Perform retraction in memory (not saved)
        changed = net.retract(node_id)

        # Separate into retracted (went OUT) and restored (went IN)
        retracted = []
        restored = []
        for nid in changed:
            if nid == node_id:
                continue
            n = net.nodes[nid]
            info = {
                "id": nid,
                "text": n.text,
                "depth": _cascade_depth(net, nid, node_id),
                "dependents": len(n.dependents),
            }
            if before[nid] == "IN" and n.truth_value == "OUT":
                retracted.append(info)
            elif before[nid] == "OUT" and n.truth_value == "IN":
                restored.append(info)

        retracted.sort(key=lambda c: (c["depth"], c["id"]))
        restored.sort(key=lambda c: (c["depth"], c["id"]))

        return {
            "node_id": node_id,
            "already_out": False,
            "retracted": retracted,
            "restored": restored,
            "total_affected": len(retracted) + len(restored),
        }


def what_if_assert(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Simulate asserting (restoring) a node without mutating the database.

    Shows what would change if a currently-OUT node were asserted back to IN.
    Tracks both nodes that go IN (restoration cascade) and nodes that go OUT
    (outlist-gated beliefs that lose their justification when this node goes IN).

    Returns: {"node_id": str, "retracted": list[dict], "restored": list[dict], ...}
    """
    with _with_network(db_path, write=False) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")

        node = net.nodes[node_id]
        if node.truth_value == "IN":
            return {
                "node_id": node_id,
                "already_in": True,
                "retracted": [],
                "restored": [],
                "total_affected": 0,
            }

        # Snapshot truth values before
        before = {nid: n.truth_value for nid, n in net.nodes.items()}

        # Perform assertion in memory (not saved)
        changed = net.assert_node(node_id)

        # Separate into restored (went IN) and retracted (went OUT)
        retracted = []
        restored = []
        for nid in changed:
            if nid == node_id:
                continue
            n = net.nodes[nid]
            info = {
                "id": nid,
                "text": n.text,
                "depth": _cascade_depth(net, nid, node_id),
                "dependents": len(n.dependents),
            }
            if before[nid] == "IN" and n.truth_value == "OUT":
                retracted.append(info)
            elif before[nid] == "OUT" and n.truth_value == "IN":
                restored.append(info)

        retracted.sort(key=lambda c: (c["depth"], c["id"]))
        restored.sort(key=lambda c: (c["depth"], c["id"]))

        return {
            "node_id": node_id,
            "already_in": False,
            "retracted": retracted,
            "restored": restored,
            "total_affected": len(retracted) + len(restored),
        }


def _cascade_depth(net, target_id: str, retracted_id: str) -> int:
    """Find the shortest justification path from retracted node to target."""
    from collections import deque
    visited = {retracted_id}
    queue = deque([(retracted_id, 0)])
    while queue:
        current_id, depth = queue.popleft()
        current = net.nodes[current_id]
        for dep_id in current.dependents:
            if dep_id in visited:
                continue
            if dep_id == target_id:
                return depth + 1
            visited.add(dep_id)
            queue.append((dep_id, depth + 1))
    return 0


def assert_node(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Assert a node and cascade restoration.

    Returns: {"changed": list[str], "went_out": list[str], "went_in": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        before = {nid: n.truth_value for nid, n in net.nodes.items()}
        changed = net.assert_node(node_id)
        went_out = [nid for nid in changed if before.get(nid) == "IN" and net.nodes[nid].truth_value == "OUT"]
        went_in = [nid for nid in changed if before.get(nid) == "OUT" and net.nodes[nid].truth_value == "IN"]
        return {"changed": changed, "went_out": went_out, "went_in": went_in}


def get_status(visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Get all nodes with truth values.

    Returns: {"nodes": list[dict], "in_count": int, "total": int}
    """
    with _with_network(db_path) as net:
        nodes = []
        for nid, node in sorted(net.nodes.items()):
            if visible_to is not None and not _is_visible(node, visible_to):
                continue
            nodes.append({
                "id": nid,
                "text": node.text,
                "truth_value": node.truth_value,
                "justification_count": len(node.justifications),
            })
        in_count = sum(1 for n in nodes if n["truth_value"] == "IN")
        return {"nodes": nodes, "in_count": in_count, "total": len(nodes)}


def show_node(node_id: str, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Get full details for a node.

    Returns: dict with id, text, truth_value, source, justifications, dependents
    Raises PermissionError if node's access_tags are not a subset of visible_to.
    """
    with _with_network(db_path) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")
        node = net.nodes[node_id]
        if visible_to is not None and not _is_visible(node, visible_to):
            raise PermissionError(
                f"Node '{node_id}' requires access tags not in {visible_to}"
            )
        return {
            "id": node.id,
            "text": node.text,
            "truth_value": node.truth_value,
            "source": node.source,
            "source_hash": node.source_hash,
            "justifications": [
                {"type": j.type, "antecedents": j.antecedents, "outlist": j.outlist, "label": j.label}
                for j in node.justifications
            ],
            "dependents": sorted(node.dependents),
            "metadata": node.metadata,
        }


def explain_node(node_id: str, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Explain why a node is IN or OUT.

    Returns: {"steps": list[dict]}
    Raises PermissionError if node's access_tags are not a subset of visible_to.
    """
    with _with_network(db_path) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")
        if visible_to is not None and not _is_visible(net.nodes[node_id], visible_to):
            raise PermissionError(
                f"Node '{node_id}' requires access tags not in {visible_to}"
            )
        steps = net.explain(node_id)
        return {"steps": steps}


def trace_assumptions(node_id: str, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Trace backward to find all premises a node rests on.

    Returns: {"node_id": str, "premises": list[str]}
    Raises PermissionError if node's access_tags are not a subset of visible_to.
    Filters returned premises by visible_to.
    """
    with _with_network(db_path) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")
        if visible_to is not None and not _is_visible(net.nodes[node_id], visible_to):
            raise PermissionError(
                f"Node '{node_id}' requires access tags not in {visible_to}"
            )
        premises = net.trace_assumptions(node_id)
        if visible_to is not None:
            premises = [p for p in premises if p in net.nodes and _is_visible(net.nodes[p], visible_to)]
        return {"node_id": node_id, "premises": premises}


def trace_access_tags(node_id: str, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Trace backward through dependency chains and return union of all access_tags.

    Returns: {"node_id": str, "access_tags": list[str]}
    Raises PermissionError if node's access_tags are not a subset of visible_to.
    """
    with _with_network(db_path) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")
        if visible_to is not None and not _is_visible(net.nodes[node_id], visible_to):
            raise PermissionError(
                f"Node '{node_id}' requires access tags not in {visible_to}"
            )
        tags = net.trace_access_tags(node_id)
        return {"node_id": node_id, "access_tags": tags}


def find_culprits(node_ids: list[str], db_path: str = DEFAULT_DB) -> dict:
    """Find premises that could be retracted to resolve a contradiction.

    Returns: {"culprits": list[dict]}
    """
    with _with_network(db_path) as net:
        culprits = net.find_culprits(node_ids)
        return {"culprits": culprits}


def convert_to_premise(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Strip justifications from a node, making it a premise (IN by default).

    Returns: {"node_id": str, "old_justifications": int, "truth_value": str, "changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        return net.convert_to_premise(node_id)


def summarize(
    summary_id: str,
    text: str,
    over: list[str],
    source: str = "",
    db_path: str = DEFAULT_DB,
) -> dict:
    """Create a summary node that abstracts over a group of nodes.

    Returns: {"summary_id": str, "over": list[str], "truth_value": str}
    """
    with _with_network(db_path, write=True) as net:
        return net.summarize(summary_id, text, over, source=source)


def supersede(old_id: str, new_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Mark old_id as superseded by new_id. Old goes OUT when new is IN.

    Returns: {"old_id": str, "new_id": str, "changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        return net.supersede(old_id, new_id)


def challenge(
    target_id: str,
    reason: str,
    challenge_id: str | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Challenge a node — creates a challenge node and the target goes OUT.

    Returns: {"challenge_id": str, "target_id": str, "changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        return net.challenge(target_id, reason, challenge_id=challenge_id)


def defend(
    target_id: str,
    challenge_id: str,
    reason: str,
    defense_id: str | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Defend a node against a challenge — neutralises the challenge, target restored.

    Returns: {"defense_id": str, "challenge_id": str, "target_id": str, "changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        return net.defend(target_id, challenge_id, reason, defense_id=defense_id)


def add_nogood(node_ids: list[str], db_path: str = DEFAULT_DB) -> dict:
    """Record a contradiction and use backtracking to resolve.

    Returns: {"nogood_id": str, "nodes": list[str], "changed": list[str], "backtracked_to": str | None}
    """
    with _with_network(db_path, write=True) as net:
        # Find culprits before retraction for reporting
        all_in = all(
            nid in net.nodes and net.nodes[nid].truth_value == "IN"
            for nid in node_ids
        )
        culprits = net.find_culprits(node_ids) if all_in else []
        backtracked_to = culprits[0]["premise"] if culprits else None

        changed = net.add_nogood(node_ids)
        ng = net.nogoods[-1]
        return {
            "nogood_id": ng.id,
            "nodes": ng.nodes,
            "changed": changed,
            "backtracked_to": backtracked_to,
        }


def get_belief_set(db_path: str = DEFAULT_DB) -> list[str]:
    """Return all node IDs currently IN."""
    with _with_network(db_path) as net:
        return net.get_belief_set()


def get_log(last: int | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Get propagation history.

    Returns: {"entries": list[dict]}
    """
    with _with_network(db_path) as net:
        entries = net.log
        if last:
            entries = entries[-last:]
        return {"entries": entries}


def export_network(visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Export the entire network as a dict.

    Returns: {"nodes": dict, "nogoods": list}
    """
    with _with_network(db_path) as net:
        return {
            "nodes": {
                nid: {
                    "text": n.text,
                    "truth_value": n.truth_value,
                    "justifications": [
                        {"type": j.type, "antecedents": j.antecedents, "outlist": j.outlist, "label": j.label}
                        for j in n.justifications
                    ],
                    "source": n.source,
                    "source_hash": n.source_hash,
                    "date": n.date,
                    "metadata": {k: v for k, v in n.metadata.items() if not k.startswith("_")},
                }
                for nid, n in sorted(net.nodes.items())
                if visible_to is None or _is_visible(n, visible_to)
            },
            "nogoods": [
                {"id": ng.id, "nodes": ng.nodes, "discovered": ng.discovered, "resolution": ng.resolution}
                for ng in net.nogoods
                if visible_to is None or all(n in net.nodes and _is_visible(net.nodes[n], visible_to) for n in ng.nodes)
            ],
            "repos": dict(net.repos),
        }


def import_beliefs(
    beliefs_file: str,
    nogoods_file: str | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Import a beliefs.md registry into the RMS network.

    Returns: {"claims_imported": int, "claims_skipped": int, "claims_retracted": int, "nogoods_imported": int}
    """
    from .import_beliefs import import_into_network

    beliefs_path = Path(beliefs_file)
    if not beliefs_path.exists():
        raise FileNotFoundError(f"File not found: {beliefs_file}")

    beliefs_text = beliefs_path.read_text()

    nogoods_text = None
    if nogoods_file:
        nogoods_path = Path(nogoods_file)
        if not nogoods_path.exists():
            raise FileNotFoundError(f"Nogoods file not found: {nogoods_file}")
        nogoods_text = nogoods_path.read_text()
    else:
        auto_nogoods = beliefs_path.parent / "nogoods.md"
        if auto_nogoods.exists():
            nogoods_text = auto_nogoods.read_text()

    with _with_network(db_path, write=True) as net:
        return import_into_network(net, beliefs_text, nogoods_text)


def import_agent(
    agent_name: str,
    beliefs_file: str,
    nogoods_file: str | None = None,
    only_in: bool = False,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Import another agent's beliefs into the local RMS with namespacing.

    Accepts beliefs.md (markdown) or network.json (JSON export) files.
    JSON files preserve full justification structure including outlists.

    Each belief is prefixed with 'agent_name:' and depends on a premise
    node 'agent_name:active'. Retracting that premise cascades OUT all
    beliefs from that agent.

    Returns: {"agent": str, "claims_imported": int, "claims_skipped": int, ...}
    """
    beliefs_path = Path(beliefs_file)
    if not beliefs_path.exists():
        raise FileNotFoundError(f"File not found: {beliefs_file}")

    if beliefs_path.suffix == ".json":
        from .import_agent import import_agent_json as _import_agent_json
        import json as json_mod

        data = json_mod.loads(beliefs_path.read_text())

        with _with_network(db_path, write=True) as net:
            return _import_agent_json(
                net,
                agent_name=agent_name,
                data=data,
                only_in=only_in,
                source_path=str(beliefs_path),
            )

    from .import_agent import import_agent as _import_agent

    beliefs_text = beliefs_path.read_text()

    nogoods_text = None
    if nogoods_file:
        nogoods_path = Path(nogoods_file)
        if not nogoods_path.exists():
            raise FileNotFoundError(f"Nogoods file not found: {nogoods_file}")
        nogoods_text = nogoods_path.read_text()
    else:
        auto_nogoods = beliefs_path.parent / "nogoods.md"
        if auto_nogoods.exists():
            nogoods_text = auto_nogoods.read_text()

    with _with_network(db_path, write=True) as net:
        return _import_agent(
            net,
            agent_name=agent_name,
            beliefs_text=beliefs_text,
            nogoods_text=nogoods_text,
            only_in=only_in,
            source_path=str(beliefs_path),
        )


def sync_agent(
    agent_name: str,
    beliefs_file: str,
    nogoods_file: str | None = None,
    only_in: bool = False,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Sync another agent's beliefs into the local RMS (remote wins).

    Accepts beliefs.md (markdown) or network.json (JSON export) files.
    Updates existing beliefs, adds new ones, retracts removed ones.

    Returns: {"agent": str, "beliefs_added": int, "beliefs_updated": int, ...}
    """
    beliefs_path = Path(beliefs_file)
    if not beliefs_path.exists():
        raise FileNotFoundError(f"File not found: {beliefs_file}")

    if beliefs_path.suffix == ".json":
        from .import_agent import sync_agent_json as _sync_agent_json
        import json as json_mod

        data = json_mod.loads(beliefs_path.read_text())

        with _with_network(db_path, write=True) as net:
            return _sync_agent_json(
                net,
                agent_name=agent_name,
                data=data,
                only_in=only_in,
                source_path=str(beliefs_path),
            )

    from .import_agent import sync_agent as _sync_agent

    beliefs_text = beliefs_path.read_text()

    nogoods_text = None
    if nogoods_file:
        nogoods_path = Path(nogoods_file)
        if not nogoods_path.exists():
            raise FileNotFoundError(f"Nogoods file not found: {nogoods_file}")
        nogoods_text = nogoods_path.read_text()
    else:
        auto_nogoods = beliefs_path.parent / "nogoods.md"
        if auto_nogoods.exists():
            nogoods_text = auto_nogoods.read_text()

    with _with_network(db_path, write=True) as net:
        return _sync_agent(
            net,
            agent_name=agent_name,
            beliefs_text=beliefs_text,
            nogoods_text=nogoods_text,
            only_in=only_in,
            source_path=str(beliefs_path),
        )


def import_json(json_file: str, db_path: str = DEFAULT_DB) -> dict:
    """Import a network from a JSON file (produced by export).

    Reconstructs the full network: nodes with justifications, truth values,
    metadata, and nogoods. This is a lossless round-trip with export.

    Returns: {"nodes_imported": int, "nogoods_imported": int}
    """
    import json as json_mod

    json_path = Path(json_file)
    if not json_path.exists():
        raise FileNotFoundError(f"File not found: {json_file}")

    data = json_mod.loads(json_path.read_text())

    with _with_network(db_path, write=True) as net:
        # Topological sort: add nodes whose antecedents are already in the network first
        remaining = dict(data.get("nodes", {}))
        added = set(net.nodes.keys())
        nodes_imported = 0
        skipped = 0

        max_passes = len(remaining) + 1
        for _ in range(max_passes):
            if not remaining:
                break
            next_remaining = {}
            for nid, ndata in remaining.items():
                if nid in added:
                    skipped += 1
                    continue
                # Check if all antecedents and outlist deps are available
                all_deps = set()
                for j in ndata.get("justifications", []):
                    all_deps.update(j.get("antecedents", []))
                    all_deps.update(j.get("outlist", []))
                deps_in_data = {d for d in all_deps if d in data.get("nodes", {})}
                if all(d in added for d in deps_in_data):
                    # Ready to add
                    justifications = None
                    jlist = ndata.get("justifications", [])
                    if jlist:
                        justifications = [
                            Justification(
                                type=j["type"],
                                antecedents=j.get("antecedents", []),
                                outlist=j.get("outlist", []),
                                label=j.get("label", ""),
                            )
                            for j in jlist
                        ]
                    node = net.add_node(
                        id=nid,
                        text=ndata.get("text", ""),
                        justifications=justifications,
                        source=ndata.get("source", ""),
                        source_hash=ndata.get("source_hash", ""),
                        date=ndata.get("date", ""),
                        metadata=ndata.get("metadata", {}),
                    )
                    # Restore exact truth value (may differ from computed if retracted)
                    target_tv = ndata.get("truth_value", "IN")
                    if node.truth_value != target_tv:
                        if target_tv == "OUT":
                            net.retract(nid)
                        else:
                            net.assert_node(nid)
                    added.add(nid)
                    nodes_imported += 1
                else:
                    next_remaining[nid] = ndata
            if len(next_remaining) == len(remaining):
                # No progress — add remaining anyway
                for nid, ndata in next_remaining.items():
                    if nid in added:
                        continue
                    justifications = None
                    jlist = ndata.get("justifications", [])
                    if jlist:
                        justifications = [
                            Justification(
                                type=j["type"],
                                antecedents=j.get("antecedents", []),
                                outlist=j.get("outlist", []),
                                label=j.get("label", ""),
                            )
                            for j in jlist
                        ]
                    net.add_node(
                        id=nid,
                        text=ndata.get("text", ""),
                        justifications=justifications,
                        source=ndata.get("source", ""),
                        source_hash=ndata.get("source_hash", ""),
                        date=ndata.get("date", ""),
                        metadata=ndata.get("metadata", {}),
                    )
                    target_tv = ndata.get("truth_value", "IN")
                    if net.nodes[nid].truth_value != target_tv:
                        if target_tv == "OUT":
                            net.retract(nid)
                        else:
                            net.assert_node(nid)
                    added.add(nid)
                    nodes_imported += 1
                break
            remaining = next_remaining

        # Import nogoods

        from . import Nogood
        nogoods_imported = 0
        for ng_data in data.get("nogoods", []):
            nogood = Nogood(
                id=ng_data["id"],
                nodes=ng_data.get("nodes", []),
                discovered=ng_data.get("discovered", ""),
                resolution=ng_data.get("resolution", ""),
            )
            net.nogoods.append(nogood)
            m = re.fullmatch(r"nogood-(\d+)", nogood.id)
            if m:
                net._next_nogood_id = max(net._next_nogood_id, int(m.group(1)) + 1)
            nogoods_imported += 1

        # Import repos
        for name, path in data.get("repos", {}).items():
            net.repos[name] = path

        return {"nodes_imported": nodes_imported, "nogoods_imported": nogoods_imported}


def derive_prompt(domain: str | None = None, db_path: str = DEFAULT_DB) -> dict:
    """Build a derive prompt from the current network.

    Returns: {"prompt": str, "stats": dict}
    """
    from .derive import build_prompt

    data = export_network(db_path=db_path)
    nodes = data.get("nodes", {})
    if not nodes:
        raise ValueError("No nodes in the network")

    prompt, stats = build_prompt(nodes, domain=domain)
    return {"prompt": prompt, "stats": stats}


def derive_apply(proposals: list[dict], db_path: str = DEFAULT_DB) -> dict:
    """Apply validated derive proposals to the network.

    Returns: {"added": list[dict], "failed": list[dict]}
    """
    from .derive import apply_proposals
    results = apply_proposals(proposals, db_path=db_path)

    added = []
    failed = []
    for p, result in results:
        if isinstance(result, dict):
            added.append({"id": p["id"], "truth_value": result["truth_value"]})
        else:
            failed.append({"id": p["id"], "error": result})

    return {"added": added, "failed": failed}


def add_repo(name: str, path: str, db_path: str = DEFAULT_DB) -> dict:
    """Add a repo to the network.

    Returns: {"name": str, "path": str}
    """
    with _with_network(db_path, write=True) as net:
        net.repos[name] = path
        return {"name": name, "path": path}


def list_repos(db_path: str = DEFAULT_DB) -> dict:
    """List all repos.

    Returns: {"repos": dict[str, str]}
    """
    with _with_network(db_path) as net:
        return {"repos": dict(net.repos)}


def export_markdown(visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> str:
    """Export the network as beliefs.md-compatible markdown.

    Returns: the markdown string
    """
    from .export_markdown import export_markdown as _export

    with _with_network(db_path) as net:
        if visible_to is not None:
            from .network import Network
            filtered = Network()
            for nid, node in net.nodes.items():
                if _is_visible(node, visible_to):
                    filtered.nodes[nid] = node
            filtered.nogoods = [ng for ng in net.nogoods if all(n in filtered.nodes for n in ng.nodes)]
            filtered.repos = net.repos
            return _export(filtered, repos=filtered.repos)
        return _export(net, repos=net.repos)


def check_stale(
    repos: dict[str, str] | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Check all IN nodes for source file staleness.

    Returns: {"stale": list[dict], "checked": int, "stale_count": int}
    """
    from .check_stale import check_stale as _check

    repo_paths = None
    if repos:
        from pathlib import Path as P
        repo_paths = {k: P(v) for k, v in repos.items()}

    with _with_network(db_path) as net:
        in_with_source = sum(
            1 for n in net.nodes.values()
            if n.truth_value == "IN" and n.source and n.source_hash
        )
        results = _check(net, repo_paths)
        return {
            "stale": results,
            "checked": in_with_source,
            "stale_count": len(results),
        }


def hash_sources(
    force: bool = False,
    repos: dict[str, str] | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Backfill source hashes for nodes with source paths but no stored hash.

    Returns: {"hashed": list[dict], "count": int}
    """
    from .check_stale import hash_sources as _hash

    repo_paths = None
    if repos:
        from pathlib import Path as P
        repo_paths = {k: P(v) for k, v in repos.items()}

    with _with_network(db_path, write=True) as net:
        results = _hash(net, repo_paths, force=force)
        return {"hashed": results, "count": len(results)}


def compact(budget: int = 500, truncate: bool = True, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> str:
    """Generate a token-budgeted belief state summary.

    Returns: the compact summary string
    """
    from .compact import compact as _compact

    with _with_network(db_path) as net:
        if visible_to is not None:
            from .network import Network
            filtered = Network()
            for nid, node in net.nodes.items():
                if _is_visible(node, visible_to):
                    filtered.nodes[nid] = node
            filtered.nogoods = [ng for ng in net.nogoods if all(n in filtered.nodes for n in ng.nodes)]
            return _compact(filtered, budget=budget, truncate=truncate)
        return _compact(net, budget=budget, truncate=truncate)


def lookup(query: str, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB) -> str:
    """Simple all-terms search over the full belief block — ID, text, source,
    dependencies, and metadata. Matches the same search corpus and output
    format as lookup_beliefs on a flat beliefs.md file.

    Args:
        query: search terms (all must appear, case-insensitive)
        visible_to: only return nodes whose access_tags are a subset
        db_path: path to RMS database

    Returns: formatted string with matching beliefs (full blocks)
    """
    with _with_network(db_path) as net:
        query_terms = query.lower().split()
        matches = []
        for nid, node in sorted(net.nodes.items()):
            if visible_to is not None and not _is_visible(node, visible_to):
                continue
            # Build the full searchable block — same fields as beliefs.md
            block_parts = [nid, node.text]
            if node.source:
                block_parts.append(node.source)
            if node.source_hash:
                block_parts.append(node.source_hash)
            if node.date:
                block_parts.append(node.date)
            for j in node.justifications:
                block_parts.extend(j.antecedents)
            for dep_id in node.dependents:
                block_parts.append(dep_id)
            block_lower = " ".join(block_parts).lower()
            if all(term in block_lower for term in query_terms):
                matches.append(node)

        if not matches:
            return f"No beliefs found matching '{query}'"

        parts = [f"Found {len(matches)} matching belief(s):", ""]
        for node in matches[:20]:
            parts.append(f"### {node.id} [{node.truth_value}]")
            parts.append(node.text)
            if node.source:
                parts.append(f"- Source: {node.source}")
            if node.source_hash:
                parts.append(f"- Source hash: {node.source_hash}")
            if node.date:
                parts.append(f"- Date: {node.date}")
            deps = []
            for j in node.justifications:
                deps.extend(j.antecedents)
            if deps:
                parts.append(f"- Depends on: {', '.join(deps)}")
            parts.append("")

        return "\n".join(parts)


def search(query: str, visible_to: list[str] | None = None, db_path: str = DEFAULT_DB, format: str = "markdown") -> str:
    """Search nodes using full-text search with neighbor expansion.

    Uses SQLite FTS5 for ranked all-terms matching. Returns matched nodes
    plus their immediate neighbors (dependencies and dependents) formatted
    as readable markdown.

    Falls back to substring matching if FTS5 table is not available.

    Args:
        query: search terms (FTS5 matches all terms in any order)
        visible_to: only return nodes whose access_tags are a subset
        db_path: path to RMS database
        format: output format — "markdown" (default), "json", or "minimal"

    Returns: formatted string with matched nodes and neighbors
    """
    with _with_network(db_path) as net:
        matched_ids = _fts_search(query, db_path)

        # Fallback to substring if FTS returned nothing or isn't available
        if not matched_ids:
            matched_ids = _substring_search(query, net)

        if not matched_ids:
            return "No results found."

        # Apply access filtering
        if visible_to is not None:
            matched_ids = [
                nid for nid in matched_ids
                if nid in net.nodes and _is_visible(net.nodes[nid], visible_to)
            ]
            if not matched_ids:
                return "No results found."

        # Expand to include neighbors (1-hop in dependency graph)
        neighbor_ids = set()
        for nid in matched_ids:
            if nid in net.nodes:
                node = net.nodes[nid]
                # Dependencies (antecedents from justifications)
                for j in node.justifications:
                    for ant_id in j.antecedents:
                        if ant_id in net.nodes:
                            neighbor_ids.add(ant_id)
                # Dependents (nodes that depend on this one)
                for dep_id in node.dependents:
                    if dep_id in net.nodes:
                        neighbor_ids.add(dep_id)

        # Remove already-matched nodes from neighbors
        neighbor_ids -= set(matched_ids)

        # Apply access filtering to neighbors too
        if visible_to is not None:
            neighbor_ids = {
                nid for nid in neighbor_ids
                if nid in net.nodes and _is_visible(net.nodes[nid], visible_to)
            }

        if format == "json":
            return _format_json(net, matched_ids, neighbor_ids)
        elif format == "minimal":
            return _format_minimal(net, matched_ids, neighbor_ids)
        elif format == "compact":
            return _format_compact(net, matched_ids, neighbor_ids)
        else:
            return _format_markdown(net, matched_ids, neighbor_ids)


def _fts_search(query: str, db_path: str) -> list[str]:
    """Search using FTS5 full-text index."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        # FTS5 match: all terms must appear (implicit AND)
        # Quote each term to avoid FTS syntax issues
        terms = query.strip().split()
        fts_query = " ".join(f'"{t}"' for t in terms if t)
        if not fts_query:
            conn.close()
            return []
        cursor = conn.execute(
            "SELECT id FROM nodes_fts WHERE nodes_fts MATCH ? ORDER BY rank LIMIT 20",
            (fts_query,),
        )
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        # FTS table doesn't exist or query failed
        return []


def _substring_search(query: str, net) -> list[str]:
    """Fallback: substring matching on node id and text."""
    q = query.lower()
    results = []
    for nid, node in sorted(net.nodes.items()):
        if q in nid.lower() or q in node.text.lower():
            results.append(nid)
    return results


def _format_markdown(net, matched_ids: list[str], neighbor_ids: set[str]) -> str:
    """Format results as readable markdown with neighbors."""
    parts = []
    for nid in matched_ids:
        node = net.nodes[nid]
        parts.append(f"### {nid}")
        parts.append(f"**Status:** {node.truth_value}")
        parts.append(f"{node.text}")
        if node.source:
            parts.append(f"**Source:** {node.source}")
        if node.justifications:
            deps = []
            for j in node.justifications:
                deps.extend(j.antecedents)
            if deps:
                parts.append(f"**Depends on:** {', '.join(deps)}")
        if node.dependents:
            parts.append(f"**Depended on by:** {', '.join(sorted(node.dependents))}")
        parts.append("")

    if neighbor_ids:
        parts.append("---")
        parts.append("**Related nodes:**\n")
        for nid in sorted(neighbor_ids):
            node = net.nodes[nid]
            parts.append(f"- **{nid}** ({node.truth_value}): {node.text}")
        parts.append("")

    return "\n".join(parts)


def _format_json(net, matched_ids: list[str], neighbor_ids: set[str]) -> str:
    """Format results as JSON."""
    import json
    results = []
    for nid in matched_ids:
        node = net.nodes[nid]
        results.append({
            "id": nid,
            "text": node.text,
            "truth_value": node.truth_value,
            "source": node.source,
            "match": True,
        })
    for nid in sorted(neighbor_ids):
        node = net.nodes[nid]
        results.append({
            "id": nid,
            "text": node.text,
            "truth_value": node.truth_value,
            "source": node.source,
            "match": False,
            "relation": "neighbor",
        })
    return json.dumps(results, indent=2)


def _format_minimal(net, matched_ids: list[str], neighbor_ids: set[str]) -> str:
    """Format results as plain text, claims only."""
    parts = []
    for nid in matched_ids:
        parts.append(net.nodes[nid].text)
    if neighbor_ids:
        parts.append("")
        for nid in sorted(neighbor_ids):
            parts.append(net.nodes[nid].text)
    return "\n".join(parts)


def _format_compact(net, matched_ids: list[str], neighbor_ids: set[str]) -> str:
    """Format results as one line per belief: [STATUS] id — text."""
    lines = []
    for nid in matched_ids:
        node = net.nodes[nid]
        lines.append(f"[{node.truth_value}] {nid} — {node.text}")
    for nid in sorted(neighbor_ids):
        node = net.nodes[nid]
        lines.append(f"[{node.truth_value}] {nid} — {node.text}")
    return "\n".join(lines) if lines else "No results found."


def _node_depth(nid, net, memo=None):
    """Compute depth of a node: 0 for premises, max(antecedent depths)+1 for derived."""
    if memo is None:
        memo = {}
    if nid in memo:
        return memo[nid]
    node = net.nodes.get(nid)
    if not node or not node.justifications:
        memo[nid] = 0
        return 0
    memo[nid] = 0  # cycle guard
    max_d = 0
    for j in node.justifications:
        for a in j.antecedents:
            max_d = max(max_d, _node_depth(a, net, memo))
    memo[nid] = max_d + 1
    return max_d + 1


def list_nodes(
    status: str | None = None,
    premises_only: bool = False,
    has_dependents: bool = False,
    challenged: bool = False,
    namespace: str | None = None,
    min_depth: int | None = None,
    max_depth: int | None = None,
    visible_to: list[str] | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """List nodes with optional filters.

    Returns: {"nodes": list[dict], "count": int}
    """
    with _with_network(db_path) as net:
        memo = {} if (min_depth is not None or max_depth is not None) else None
        nodes = []
        for nid, node in sorted(net.nodes.items()):
            if namespace and not nid.startswith(f"{namespace}:"):
                continue
            if status and node.truth_value != status:
                continue
            if premises_only and node.justifications:
                continue
            if has_dependents and not node.dependents:
                continue
            if challenged and not node.metadata.get("challenges"):
                continue
            if visible_to is not None and not _is_visible(node, visible_to):
                continue
            if memo is not None:
                d = _node_depth(nid, net, memo)
                if min_depth is not None and d < min_depth:
                    continue
                if max_depth is not None and d > max_depth:
                    continue
            nodes.append({
                "id": nid,
                "text": node.text,
                "truth_value": node.truth_value,
                "justification_count": len(node.justifications),
                "dependent_count": len(node.dependents),
                "challenges": node.metadata.get("challenges", []),
            })
        return {"nodes": nodes, "count": len(nodes)}


def list_gated(
    visible_to: list[str] | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Find OUT nodes blocked by IN outlist nodes (active gates).

    Returns: {"blockers": {blocker_id: {"text": str, "gated": [{"id": str, "text": str}]}},
              "gated_count": int, "blocker_count": int}
    """
    with _with_network(db_path) as net:
        blockers: dict[str, dict] = {}
        for nid, node in sorted(net.nodes.items()):
            if node.truth_value != "OUT":
                continue
            if node.metadata.get("superseded_by"):
                continue
            if visible_to is not None and not _is_visible(node, visible_to):
                continue
            for j in node.justifications:
                for outlist_id in j.outlist:
                    if outlist_id not in net.nodes:
                        continue
                    out_node = net.nodes[outlist_id]
                    if out_node.truth_value != "IN":
                        continue
                    if outlist_id not in blockers:
                        blockers[outlist_id] = {
                            "text": out_node.text,
                            "gated": [],
                        }
                    if not any(g["id"] == nid for g in blockers[outlist_id]["gated"]):
                        blockers[outlist_id]["gated"].append({
                            "id": nid,
                            "text": node.text,
                        })
        gated_count = sum(len(b["gated"]) for b in blockers.values())
        return {"blockers": blockers, "gated_count": gated_count, "blocker_count": len(blockers)}


NEGATIVE_TERMS = [
    'bug', 'defect', 'missing', 'fail', 'error', 'broken', 'incorrect',
    'wrong', 'risk', 'gap', 'lack', 'vulnerable', 'insecure', 'stale',
    'outdated', 'deprecated', 'fragile', 'brittle', 'hack', 'workaround',
    'technical debt', 'tech debt', 'not implemented', 'unimplemented',
    'incomplete', 'inconsistent', 'unclear', 'confusing', 'problem',
    'issue', 'concern', 'warning', 'danger', 'threat', 'weakness',
    'limitation', 'constraint', 'bottleneck', 'blocker', 'obstacle',
    'undermines', 'concentrated', 'single point of failure', 'no tests',
    'untested', 'not tested', 'hard-coded', 'hardcoded', 'tight coupling',
    'tightly coupled', 'monolithic', 'legacy', 'unmaintained',
]

NEGATIVE_CLASSIFY_PROMPT = """\
You are classifying beliefs from a Truth Maintenance System.
Each belief below passed a keyword filter for negative terms.
Identify which are GENUINELY NEGATIVE — they assert something is
a problem, defect, risk, gap, limitation, or concern.

EXCLUDE beliefs that merely DESCRIBE error handling, failure modes,
or warning mechanisms as part of normal system behavior.

Return ONLY a JSON array of the IDs of genuinely negative beliefs.
Example: ["belief-1", "belief-3"]
If none are genuinely negative, return: []

## Candidates

{candidates}"""


def list_negative(
    visible_to: list[str] | None = None,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Find IN beliefs that describe problems, defects, or risks.

    Uses keyword pre-filtering then LLM classification via claude -p.

    Returns: {"negative": [{"id": str, "text": str}, ...],
              "count": int, "candidates": int, "total": int}
    """
    from . import ask

    with _with_network(db_path) as net:
        in_nodes = []
        for nid, node in sorted(net.nodes.items()):
            if node.truth_value != "IN":
                continue
            if visible_to is not None and not _is_visible(node, visible_to):
                continue
            in_nodes.append((nid, node.text))

        total = len(in_nodes)
        empty = {"negative": [], "count": 0, "candidates": 0, "total": total}

        if not in_nodes:
            return empty

        candidates = []
        for nid, text in in_nodes:
            text_lower = text.lower()
            if any(term in text_lower for term in NEGATIVE_TERMS):
                candidates.append((nid, text))

        if not candidates:
            return empty

        lines = [f"- [{nid}] `{text}`" for nid, text in candidates]
        prompt = NEGATIVE_CLASSIFY_PROMPT.format(candidates="\n".join(lines))

        response = ask._invoke_claude(prompt)

        negative_ids = set()
        for match in re.finditer(r"\[.*?\]", response, re.DOTALL):
            try:
                ids = json.loads(match.group())
                if isinstance(ids, list):
                    negative_ids = set(ids)
                    break
            except json.JSONDecodeError:
                continue

        candidate_map = {nid: text for nid, text in candidates}
        negative = [
            {"id": nid, "text": candidate_map[nid]}
            for nid in negative_ids
            if nid in candidate_map
        ]
        negative.sort(key=lambda x: x["id"])

        return {
            "negative": negative,
            "count": len(negative),
            "candidates": len(candidates),
            "total": total,
        }


def _rewrite_dependents(net, old_id: str, new_id: str):
    """Rewrite justifications that reference old_id to point at new_id.

    Updates both the justification antecedents/outlist and the dependents
    reverse index so that derived beliefs survive deduplication.
    """
    old_node = net.nodes[old_id]
    new_node = net.nodes[new_id]
    for dep_id in list(old_node.dependents):
        dep = net.nodes[dep_id]
        for j in dep.justifications:
            if old_id in j.antecedents:
                j.antecedents = [new_id if a == old_id else a for a in j.antecedents]
                new_node.dependents.add(dep_id)
            if old_id in j.outlist:
                j.outlist = [new_id if o == old_id else o for o in j.outlist]
                new_node.dependents.add(dep_id)
        old_node.dependents.discard(dep_id)


def deduplicate(
    threshold: float = 0.5,
    auto: bool = False,
    db_path: str = DEFAULT_DB,
) -> dict:
    """Find clusters of IN beliefs with similar IDs (likely duplicates).

    Uses Jaccard similarity on ID tokens to detect beliefs that say the
    same thing under slightly different IDs.

    Args:
        threshold: Minimum Jaccard similarity to consider a pair (default: 0.5)
        auto: If True, retract all but the most-connected belief in each cluster
        db_path: Path to database

    Returns: {"clusters": list[dict], "retracted": list[str]}
    """
    from .derive import _tokenize_id, _jaccard

    with _with_network(db_path, write=auto) as net:
        in_nodes = [(nid, n) for nid, n in sorted(net.nodes.items())
                    if n.truth_value == "IN"]

        # Build token sets once
        tokens = {nid: _tokenize_id(nid) for nid, _ in in_nodes}

        # Union-find to group similar beliefs
        parent = {nid: nid for nid, _ in in_nodes}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i, (nid_a, _) in enumerate(in_nodes):
            for nid_b, _ in in_nodes[i + 1:]:
                if _jaccard(tokens[nid_a], tokens[nid_b]) >= threshold:
                    union(nid_a, nid_b)

        # Collect clusters (only groups of 2+)
        from collections import defaultdict
        groups = defaultdict(list)
        for nid, _ in in_nodes:
            groups[find(nid)].append(nid)

        clusters = []
        retracted = []
        for members in groups.values():
            if len(members) < 2:
                continue
            cluster = {
                "beliefs": [
                    {"id": nid, "text": net.nodes[nid].text,
                     "dependents": len(net.nodes[nid].dependents)}
                    for nid in sorted(members)
                ],
                "size": len(members),
            }
            keep = max(members, key=lambda nid: (len(net.nodes[nid].dependents), nid))
            cluster["kept"] = keep
            clusters.append(cluster)

            if auto:
                for nid in members:
                    if nid != keep:
                        _rewrite_dependents(net, old_id=nid, new_id=keep)
                        net.retract(nid)
                        retracted.append(nid)

        clusters.sort(key=lambda c: -c["size"])
        return {"clusters": clusters, "retracted": retracted}


def write_dedup_plan(clusters: list[dict], output_path: str) -> str:
    """Write a dedup plan file for human review.

    Format is parseable by parse_dedup_plan(). Each cluster lists the
    kept belief and the beliefs to retract. Remove clusters or lines
    you disagree with before accepting.
    """
    path = Path(output_path)
    with open(path, "w") as f:
        f.write("# Deduplication Plan\n\n")
        f.write("Review each cluster below. Delete any cluster you want to skip,\n")
        f.write("or change which belief is KEEP vs RETRACT. Then run:\n")
        f.write("  reasons deduplicate --accept proposed-dedup.md\n\n")
        f.write("---\n\n")

        for i, cluster in enumerate(clusters, 1):
            f.write(f"## Cluster {i} ({cluster['size']} beliefs)\n\n")
            kept = cluster.get("kept")
            for b in cluster["beliefs"]:
                action = "KEEP" if b["id"] == kept else "RETRACT"
                deps = f"  ({b['dependents']} dependents)" if b["dependents"] else ""
                f.write(f"- [{action}] `{b['id']}`{deps}\n")
                f.write(f"  {b['text']}\n")
            f.write("\n")

    return str(path)


def parse_dedup_plan(plan_text: str) -> list[dict]:
    """Parse a dedup plan file into actionable clusters.

    Returns list of {"keep": str, "retract": list[str]} dicts.
    """
    import re
    clusters = []
    current_keep = None
    current_retract = []

    for line in plan_text.splitlines():
        if line.startswith("## Cluster"):
            if current_keep and current_retract:
                clusters.append({"keep": current_keep, "retract": current_retract})
            current_keep = None
            current_retract = []
            continue

        m = re.match(r"- \[(KEEP|RETRACT)\] `(\S+?)`", line)
        if m:
            action, node_id = m.group(1), m.group(2)
            if action == "KEEP":
                current_keep = node_id
            else:
                current_retract.append(node_id)

    if current_keep and current_retract:
        clusters.append({"keep": current_keep, "retract": current_retract})

    return clusters


def apply_dedup_plan(
    plan: list[dict],
    db_path: str = DEFAULT_DB,
) -> dict:
    """Apply a reviewed dedup plan: rewrite justifications and retract duplicates.

    Args:
        plan: list of {"keep": str, "retract": list[str]} from parse_dedup_plan
        db_path: Path to database

    Returns: {"applied": int, "retracted": list[str], "errors": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        retracted = []
        errors = []
        for cluster in plan:
            keep = cluster["keep"]
            if keep not in net.nodes:
                errors.append(f"keep node not found: {keep}")
                continue
            for old_id in cluster["retract"]:
                if old_id not in net.nodes:
                    errors.append(f"retract node not found: {old_id}")
                    continue
                if net.nodes[old_id].truth_value == "OUT":
                    continue
                _rewrite_dependents(net, old_id=old_id, new_id=keep)
                net.retract(old_id)
                retracted.append(old_id)
        return {"applied": len(plan), "retracted": retracted, "errors": errors}
