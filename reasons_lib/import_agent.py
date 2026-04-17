"""Import another agent's beliefs into the local RMS network.

Creates namespaced nodes (agent:belief-id) so beliefs from multiple agents
can coexist without collision. Each agent gets a premise node (agent:active)
that all its beliefs depend on — retracting it cascades OUT every belief
from that agent.

This implements multi-agent belief tracking at the file level: read another
agent's beliefs.md or network.json, import them with provenance, and let
the local RMS handle truth maintenance across agents.

Usage:
    reasons import-agent aap-expert ~/git/aap-expert/beliefs.md
    reasons import-agent rhel-expert ~/git/rhel-expert/beliefs.md --only-in
"""

from pathlib import Path

from . import Justification
from .import_beliefs import parse_beliefs, parse_nogoods
from .network import Network


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
    A premise node 'agent_name:active' is created — all imported beliefs
    depend on it via SL justification. Retracting 'agent_name:active'
    cascades OUT every belief from that agent.

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
    active_id = f"{agent_name}:active"

    # Create or reuse the agent premise node
    if active_id not in network.nodes:
        network.add_node(
            id=active_id,
            text=f"Agent '{agent_name}' beliefs are trusted",
            source=source_path,
            metadata={"agent": agent_name, "role": "agent_premise"},
        )
        created_premise = True
    else:
        created_premise = False

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
    updated = 0

    for claim in ordered:
        node_id = f"{prefix}{claim['id']}"

        if node_id in network.nodes:
            skipped += 1
            continue

        # Build antecedents: always include the agent:active premise,
        # plus any remapped depends_on from within this agent's beliefs
        antecedents = [active_id]
        for dep_id in claim["depends_on"]:
            prefixed_dep = f"{prefix}{dep_id}"
            # Only add if the dependency exists in this import set
            if dep_id in claim_by_id:
                antecedents.append(prefixed_dep)

        justifications = [
            Justification(
                type="SL",
                antecedents=antecedents,
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
            justifications=justifications,
            source=claim["source"],
            source_hash=claim["source_hash"],
            date=claim["date"],
            metadata=metadata,
        )
        imported += 1

        # STALE and OUT claims get retracted after adding
        if claim["status"] in ("STALE", "OUT"):
            network.retract(node_id)
            retracted += 1

    # Import nogoods (remapped to prefixed IDs)
    nogoods_imported = 0
    if nogoods_text:
        nogoods = parse_nogoods(nogoods_text)
        from . import Nogood
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

    # Recompute truth values from the justification graph.
    # Imported truth values (IN/OUT) may not match what the justifications
    # actually support, since the source snapshot can diverge from the
    # imported dependency structure.
    propagated = 0
    for node in network.nodes.values():
        if node.justifications:
            old = node.truth_value
            new = network._compute_truth(node)
            if old != new:
                node.truth_value = new
                propagated += 1

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
