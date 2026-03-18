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
        label: Justification label
        source: Provenance (repo:path)
        db_path: Path to RMS database

    Returns: {"node_id": str, "truth_value": str, "type": str}
    """
    justifications = []
    if sl:
        antecedents = [a.strip() for a in sl.split(",")]
        justifications.append(Justification(type="SL", antecedents=antecedents, label=label))
    elif cp:
        antecedents = [a.strip() for a in cp.split(",")]
        justifications.append(Justification(type="CP", antecedents=antecedents, label=label))

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
                {"type": j.type, "antecedents": j.antecedents, "label": j.label}
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


def add_nogood(node_ids: list[str], db_path: str = DEFAULT_DB) -> dict:
    """Record a contradiction and retract the least entrenched node.

    Returns: {"nogood_id": str, "nodes": list[str], "changed": list[str]}
    """
    with _with_network(db_path, write=True) as net:
        changed = net.add_nogood(node_ids)
        ng = net.nogoods[-1]
        return {"nogood_id": ng.id, "nodes": ng.nodes, "changed": changed}


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
                        {"type": j.type, "antecedents": j.antecedents, "label": j.label}
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
