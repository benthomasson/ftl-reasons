"""Functional Python API for the Reason Maintenance System.

This module provides standalone functions that any Python caller can use
(CLI, LangGraph tools, scripts) without dealing with Storage lifecycle
or argparse. Each function opens the database, operates, saves, and closes.

All functions return dicts suitable for JSON serialization.
"""

from pathlib import Path

from . import Justification
from .network import Network
from .storage import Storage


DEFAULT_DB = "rms.db"


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


def add_node(
    node_id: str,
    text: str,
    sl: str = "",
    cp: str = "",
    unless: str = "",
    label: str = "",
    source: str = "",
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
        db_path: Path to RMS database

    Returns: {"node_id": str, "truth_value": str, "type": str}
    """
    outlist = [o.strip() for o in unless.split(",") if o.strip()] if unless else []
    justifications = []
    if sl:
        antecedents = [a.strip() for a in sl.split(",")]
        justifications.append(Justification(type="SL", antecedents=antecedents, outlist=outlist, label=label))
    elif cp:
        antecedents = [a.strip() for a in cp.split(",")]
        justifications.append(Justification(type="CP", antecedents=antecedents, outlist=outlist, label=label))
    elif outlist:
        # Outlist-only justification (no inlist) — premise that holds unless something is believed
        justifications.append(Justification(type="SL", antecedents=[], outlist=outlist, label=label))

    with _with_network(db_path, write=True) as net:
        node = net.add_node(
            id=node_id,
            text=text,
            justifications=justifications or None,
            source=source,
        )
        jtype = justifications[0].type if justifications else "premise"
        return {"node_id": node_id, "truth_value": node.truth_value, "type": jtype}


def retract_node(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Retract a node and cascade.

    Returns: {"changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        changed = net.retract(node_id)
        return {"changed": changed}


def assert_node(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Assert a node and cascade restoration.

    Returns: {"changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        changed = net.assert_node(node_id)
        return {"changed": changed}


def get_status(db_path: str = DEFAULT_DB) -> dict:
    """Get all nodes with truth values.

    Returns: {"nodes": list[dict], "in_count": int, "total": int}
    """
    with _with_network(db_path) as net:
        nodes = []
        for nid, node in sorted(net.nodes.items()):
            nodes.append({
                "id": nid,
                "text": node.text,
                "truth_value": node.truth_value,
                "justification_count": len(node.justifications),
            })
        in_count = sum(1 for n in nodes if n["truth_value"] == "IN")
        return {"nodes": nodes, "in_count": in_count, "total": len(nodes)}


def show_node(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Get full details for a node.

    Returns: dict with id, text, truth_value, source, justifications, dependents
    """
    with _with_network(db_path) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")
        node = net.nodes[node_id]
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


def explain_node(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Explain why a node is IN or OUT.

    Returns: {"steps": list[dict]}
    """
    with _with_network(db_path) as net:
        steps = net.explain(node_id)
        return {"steps": steps}


def trace_assumptions(node_id: str, db_path: str = DEFAULT_DB) -> dict:
    """Trace backward to find all premises a node rests on.

    Returns: {"node_id": str, "premises": list[str]}
    """
    with _with_network(db_path) as net:
        premises = net.trace_assumptions(node_id)
        return {"node_id": node_id, "premises": premises}


def find_culprits(node_ids: list[str], db_path: str = DEFAULT_DB) -> dict:
    """Find premises that could be retracted to resolve a contradiction.

    Returns: {"culprits": list[dict]}
    """
    with _with_network(db_path) as net:
        culprits = net.find_culprits(node_ids)
        return {"culprits": culprits}


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


def export_network(db_path: str = DEFAULT_DB) -> dict:
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
                    "metadata": n.metadata,
                }
                for nid, n in sorted(net.nodes.items())
            },
            "nogoods": [
                {"id": ng.id, "nodes": ng.nodes, "discovered": ng.discovered, "resolution": ng.resolution}
                for ng in net.nogoods
            ],
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
            nogoods_imported += 1

        return {"nodes_imported": nodes_imported, "nogoods_imported": nogoods_imported}


def export_markdown(db_path: str = DEFAULT_DB) -> str:
    """Export the network as beliefs.md-compatible markdown.

    Returns: the markdown string
    """
    from .export_markdown import export_markdown as _export

    with _with_network(db_path) as net:
        return _export(net)


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


def compact(budget: int = 500, truncate: bool = True, db_path: str = DEFAULT_DB) -> str:
    """Generate a token-budgeted belief state summary.

    Returns: the compact summary string
    """
    from .compact import compact as _compact

    with _with_network(db_path) as net:
        return _compact(net, budget=budget, truncate=truncate)


def search(query: str, db_path: str = DEFAULT_DB) -> dict:
    """Search nodes by text or ID substring (case-insensitive).

    Returns: {"results": list[dict], "count": int}
    """
    q = query.lower()
    with _with_network(db_path) as net:
        results = []
        for nid, node in sorted(net.nodes.items()):
            if q in nid.lower() or q in node.text.lower():
                results.append({
                    "id": nid,
                    "text": node.text,
                    "truth_value": node.truth_value,
                    "justification_count": len(node.justifications),
                    "dependent_count": len(node.dependents),
                })
        return {"results": results, "count": len(results)}


def list_nodes(
    status: str | None = None,
    premises_only: bool = False,
    has_dependents: bool = False,
    challenged: bool = False,
    db_path: str = DEFAULT_DB,
) -> dict:
    """List nodes with optional filters.

    Returns: {"nodes": list[dict], "count": int}
    """
    with _with_network(db_path) as net:
        nodes = []
        for nid, node in sorted(net.nodes.items()):
            if status and node.truth_value != status:
                continue
            if premises_only and node.justifications:
                continue
            if has_dependents and not node.dependents:
                continue
            if challenged and not node.metadata.get("challenges"):
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
