"""Import another agent's beliefs into the local RMS network.

Creates namespaced nodes (agent:belief-id) so beliefs from multiple agents
can coexist without collision. Each agent gets a premise node (agent:active)
and a relay node (agent:inactive) that provides a kill switch — retracting
agent:active makes agent:inactive go IN, which cascades OUT every belief
from that agent via outlist.

The agent:active premise is NOT placed in antecedents (which would provide
an always-valid fallback defeating per-belief retraction). Instead,
agent:inactive is placed in the outlist of each imported belief.

Usage:
    reasons import-agent aap-expert ~/git/aap-expert/beliefs.md
    reasons import-agent rhel-expert ~/git/rhel-expert/network.json
    reasons import-agent rhel-expert ~/git/rhel-expert/beliefs.md --only-in
"""

from pathlib import Path

from . import Justification, Nogood
from .import_beliefs import parse_beliefs, parse_nogoods
from .network import Network


def _fixup_dependents(network):
    """Re-register dependents for all nodes.

    Outlist nodes may have been added after the nodes that reference them,
    so add_node couldn't register the dependency at creation time.
    """
    for node in network.nodes.values():
        for j in node.justifications:
            for ant_id in j.antecedents:
                if ant_id in network.nodes:
                    network.nodes[ant_id].dependents.add(node.id)
            for out_id in j.outlist:
                if out_id in network.nodes:
                    network.nodes[out_id].dependents.add(node.id)


def _ensure_agent_nodes(network, agent_name, source_path=""):
    """Create agent:active and agent:inactive nodes if they don't exist.

    Returns (active_id, inactive_id, created_premise).
    """
    active_id = f"{agent_name}:active"
    inactive_id = f"{agent_name}:inactive"

    created_premise = False
    if active_id not in network.nodes:
        network.add_node(
            id=active_id,
            text=f"Agent '{agent_name}' beliefs are trusted",
            source=source_path,
            metadata={"agent": agent_name, "role": "agent_premise"},
        )
        created_premise = True

    if inactive_id not in network.nodes:
        network.add_node(
            id=inactive_id,
            text=f"Agent '{agent_name}' kill switch — IN when active is OUT",
            justifications=[Justification(type="SL", antecedents=[], outlist=[active_id])],
            source=source_path,
            metadata={"agent": agent_name, "role": "agent_inactive"},
        )

    return active_id, inactive_id, created_premise


def import_agent(
    network: Network,
    agent_name: str,
    beliefs_text: str,
    nogoods_text: str | None = None,
    only_in: bool = False,
    source_path: str = "",
) -> dict:
    """Import another agent's beliefs into the network with namespacing.

    Each belief is prefixed with 'agent_name:' to avoid ID collisions.
    A premise node 'agent_name:active' is created along with a relay node
    'agent_name:inactive' (IN when active is OUT). Imported beliefs have
    inactive in their outlist — retracting active cascades everything OUT.

    Beliefs that are OUT/STALE in the source are imported as bare premises
    with no justification, so recompute_all cannot resurrect them.

    Args:
        network: The local RMS network to import into.
        agent_name: Name of the agent (used as namespace prefix).
        beliefs_text: Contents of the agent's beliefs.md file.
        nogoods_text: Contents of the agent's nogoods.md file (optional).
        only_in: If True, only import beliefs with status IN.
        source_path: Path to the beliefs file (for provenance).

    Returns:
        Summary dict with counts.
    """
    prefix = f"{agent_name}:"
    active_id, inactive_id, created_premise = _ensure_agent_nodes(
        network, agent_name, source_path
    )

    claims = parse_beliefs(beliefs_text)

    if only_in:
        claims = [c for c in claims if c["status"] == "IN"]

    # Build claim lookup for dependency resolution
    claim_by_id = {c["id"]: c for c in claims}

    # Topological sort so dependencies are added before dependents
    ordered = []
    added = set()
    remaining = list(claims)

    max_passes = len(remaining) + 1
    for _ in range(max_passes):
        if not remaining:
            break
        next_remaining = []
        for c in remaining:
            deps_in_registry = [d for d in c["depends_on"] if d in claim_by_id]
            if all(d in added for d in deps_in_registry):
                ordered.append(c)
                added.add(c["id"])
            else:
                next_remaining.append(c)
        if len(next_remaining) == len(remaining):
            ordered.extend(next_remaining)
            break
        remaining = next_remaining

    imported = 0
    skipped = 0
    retracted = 0
    retract_after = []

    for claim in ordered:
        node_id = f"{prefix}{claim['id']}"

        if node_id in network.nodes:
            skipped += 1
            continue

        is_out = claim["status"] in ("STALE", "OUT")

        if is_out:
            justifications = []
        else:
            antecedents = []
            for dep_id in claim["depends_on"]:
                prefixed_dep = f"{prefix}{dep_id}"
                if dep_id in claim_by_id:
                    antecedents.append(prefixed_dep)

            outlist = [inactive_id]
            for out_id in claim.get("unless", []):
                prefixed_out = f"{prefix}{out_id}"
                if out_id in claim_by_id:
                    outlist.append(prefixed_out)

            justifications = [
                Justification(
                    type="SL",
                    antecedents=antecedents,
                    outlist=outlist,
                    label=f"imported from agent: {agent_name}",
                )
            ]

        metadata = {
            "agent": agent_name,
            "original_id": claim["id"],
            "imported_from": source_path,
        }
        if claim["type"]:
            metadata["beliefs_type"] = claim["type"]

        network.add_node(
            id=node_id,
            text=claim["text"],
            justifications=justifications if justifications else None,
            source=claim["source"],
            source_hash=claim["source_hash"],
            date=claim["date"],
            metadata=metadata,
        )
        imported += 1

        if is_out:
            retract_after.append(node_id)

    # Import nogoods (remapped to prefixed IDs)
    nogoods_imported = 0
    if nogoods_text:
        nogoods = parse_nogoods(nogoods_text)
        for ng in nogoods:
            prefixed_nodes = [f"{prefix}{a}" for a in ng["affects"]]
            valid_nodes = [n for n in prefixed_nodes if n in network.nodes]
            nogood_id = f"{prefix}{ng['id']}"
            existing_ids = {n.id for n in network.nogoods}
            if len(valid_nodes) >= 2 and nogood_id not in existing_ids:
                nogood = Nogood(
                    id=nogood_id,
                    nodes=valid_nodes,
                    discovered=ng["discovered"],
                    resolution=ng["resolution"],
                )
                network.nogoods.append(nogood)
                nogoods_imported += 1

    _fixup_dependents(network)
    propagated = len(network.recompute_all())

    for node_id in retract_after:
        network.retract(node_id)
        retracted += 1

    return {
        "agent": agent_name,
        "prefix": prefix,
        "active_node": active_id,
        "created_premise": created_premise,
        "claims_imported": imported,
        "claims_skipped": skipped,
        "claims_retracted": retracted,
        "claims_propagated": propagated,
        "nogoods_imported": nogoods_imported,
    }


def import_agent_json(
    network: Network,
    agent_name: str,
    data: dict,
    only_in: bool = False,
    source_path: str = "",
) -> dict:
    """Import an agent's beliefs from JSON export with namespacing.

    JSON format preserves full justification structure including outlists,
    providing lossless import of non-monotonic relationships.

    Uses agent:inactive in outlist (not agent:active in antecedents) so
    per-belief retraction works. OUT beliefs are imported as bare premises.
    """
    prefix = f"{agent_name}:"
    active_id, inactive_id, created_premise = _ensure_agent_nodes(
        network, agent_name, source_path
    )

    nodes = data.get("nodes", {})

    if only_in:
        nodes = {k: v for k, v in nodes.items() if v.get("truth_value") == "IN"}

    # Topological sort by antecedent references
    ordered = []
    added = set()
    remaining = dict(nodes)

    max_passes = len(remaining) + 1
    for _ in range(max_passes):
        if not remaining:
            break
        next_remaining = {}
        for nid, ndata in remaining.items():
            all_antes = []
            for j in ndata.get("justifications", []):
                all_antes.extend(j.get("antecedents", []))
            deps_in_set = [a for a in all_antes if a in nodes]
            if all(d in added for d in deps_in_set):
                ordered.append((nid, ndata))
                added.add(nid)
            else:
                next_remaining[nid] = ndata
        if len(next_remaining) == len(remaining):
            ordered.extend(next_remaining.items())
            break
        remaining = next_remaining

    imported = 0
    skipped = 0
    retracted = 0
    retract_after = []

    for nid, ndata in ordered:
        node_id = f"{prefix}{nid}"

        if node_id in network.nodes:
            skipped += 1
            continue

        is_out = ndata.get("truth_value") == "OUT"

        if is_out:
            justifications = []
        else:
            justifications = []
            for j in ndata.get("justifications", []):
                antecedents = [f"{prefix}{a}" for a in j.get("antecedents", [])]
                outlist = [inactive_id]
                outlist.extend(
                    f"{prefix}{o}" for o in j.get("outlist", []) if o in nodes
                )
                justifications.append(Justification(
                    type=j.get("type", "SL"),
                    antecedents=antecedents,
                    outlist=outlist,
                    label=j.get("label", f"imported from agent: {agent_name}"),
                ))

            if not justifications:
                justifications = [Justification(
                    type="SL",
                    antecedents=[],
                    outlist=[inactive_id],
                    label=f"imported from agent: {agent_name}",
                )]

        metadata = ndata.get("metadata", {}).copy()
        metadata.update({
            "agent": agent_name,
            "original_id": nid,
            "imported_from": source_path,
        })

        network.add_node(
            id=node_id,
            text=ndata.get("text", ""),
            justifications=justifications if justifications else None,
            source=ndata.get("source", ""),
            source_hash=ndata.get("source_hash", ""),
            date=ndata.get("date", ""),
            metadata=metadata,
        )
        imported += 1

        if is_out:
            retract_after.append(node_id)

    # Import nogoods
    nogoods_imported = 0
    for ng in data.get("nogoods", []):
        prefixed_nodes = [f"{prefix}{n}" for n in ng.get("nodes", [])]
        valid_nodes = [n for n in prefixed_nodes if n in network.nodes]
        nogood_id = f"{prefix}{ng['id']}"
        existing_ids = {n.id for n in network.nogoods}
        if len(valid_nodes) >= 2 and nogood_id not in existing_ids:
            network.nogoods.append(Nogood(
                id=nogood_id,
                nodes=valid_nodes,
                discovered=ng.get("discovered", ""),
                resolution=ng.get("resolution", ""),
            ))
            nogoods_imported += 1

    _fixup_dependents(network)
    propagated = len(network.recompute_all())

    for node_id in retract_after:
        network.retract(node_id)
        retracted += 1

    return {
        "agent": agent_name,
        "prefix": prefix,
        "active_node": active_id,
        "created_premise": created_premise,
        "claims_imported": imported,
        "claims_skipped": skipped,
        "claims_retracted": retracted,
        "claims_propagated": propagated,
        "nogoods_imported": nogoods_imported,
    }
