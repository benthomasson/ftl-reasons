"""Dependency network with automatic truth value propagation.

Implements Doyle's (1979) TMS algorithm:
- Nodes have justifications (SL or CP)
- Truth values propagate automatically through the dependency graph
- Retraction cascades: when a node goes OUT, dependents are recomputed
- Restoration: when a node comes back IN, dependents are recomputed
- Retracted nodes stay in the network (enables restoration without rederivation)
"""

from collections import deque
from datetime import datetime

from . import Node, Justification, Nogood


class Network:
    """The dependency network — core data structure of the RMS."""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.nogoods: list[Nogood] = []
        self.log: list[dict] = []  # propagation audit trail

    def add_node(
        self,
        id: str,
        text: str,
        justifications: list[Justification] | None = None,
        source: str = "",
        source_hash: str = "",
        date: str = "",
        metadata: dict | None = None,
    ) -> Node:
        """Add a node to the network and propagate.

        If no justifications are provided, the node is a premise (IN by default).
        If justifications are provided, truth value is computed from them.
        """
        if id in self.nodes:
            raise ValueError(f"Node '{id}' already exists")

        node = Node(
            id=id,
            text=text,
            justifications=justifications or [],
            source=source,
            source_hash=source_hash,
            date=date,
            metadata=metadata or {},
        )

        # Register as dependent of antecedents (inlist) and outlist nodes.
        # Both can affect this node's truth value when they change.
        for j in node.justifications:
            for ant_id in j.antecedents:
                if ant_id in self.nodes:
                    self.nodes[ant_id].dependents.add(id)
            for out_id in j.outlist:
                if out_id in self.nodes:
                    self.nodes[out_id].dependents.add(id)

        self.nodes[id] = node

        # Compute initial truth value
        if node.justifications:
            node.truth_value = self._compute_truth(node)
        else:
            # Premise — IN by default
            node.truth_value = "IN"

        self._log("add", id, node.truth_value)
        return node

    def retract(self, node_id: str) -> list[str]:
        """Mark a node OUT and propagate the retraction cascade.

        Returns list of all node IDs whose truth value changed.
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node '{node_id}' not found")

        node = self.nodes[node_id]
        if node.truth_value == "OUT":
            return []

        node.truth_value = "OUT"
        changed = [node_id]
        self._log("retract", node_id, "OUT")

        # Propagate to dependents
        changed.extend(self._propagate(node_id))
        return changed

    def assert_node(self, node_id: str) -> list[str]:
        """Mark a node IN and propagate restoration.

        Returns list of all node IDs whose truth value changed.
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node '{node_id}' not found")

        node = self.nodes[node_id]
        if node.truth_value == "IN":
            return []

        node.truth_value = "IN"
        changed = [node_id]
        self._log("assert", node_id, "IN")

        # Propagate to dependents
        changed.extend(self._propagate(node_id))
        return changed

    def add_nogood(self, node_ids: list[str]) -> list[str]:
        """Record a contradiction and retract the least entrenched node.

        Returns list of all node IDs whose truth value changed.
        """
        # Verify all nodes exist
        for nid in node_ids:
            if nid not in self.nodes:
                raise KeyError(f"Node '{nid}' not found")

        nogood_id = f"nogood-{len(self.nogoods) + 1:03d}"
        nogood = Nogood(
            id=nogood_id,
            nodes=list(node_ids),
            discovered=datetime.now().isoformat(timespec="seconds"),
        )
        self.nogoods.append(nogood)
        self._log("nogood", nogood_id, str(node_ids))

        # Check if contradiction is active (all nodes IN)
        all_in = all(self.nodes[nid].truth_value == "IN" for nid in node_ids)
        if not all_in:
            return []

        # Retract the node with fewest dependents (simple heuristic)
        # A real AGM implementation would use entrenchment scoring
        candidates = [(nid, len(self.nodes[nid].dependents)) for nid in node_ids]
        candidates.sort(key=lambda x: x[1])
        victim_id = candidates[0][0]

        return self.retract(victim_id)

    def explain(self, node_id: str) -> list[dict]:
        """Trace why a node is IN or OUT.

        Returns a list of explanation steps tracing back through justifications.
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node '{node_id}' not found")

        node = self.nodes[node_id]
        steps = []

        if not node.justifications:
            steps.append({
                "node": node_id,
                "truth_value": node.truth_value,
                "reason": "premise" if node.truth_value == "IN" else "retracted premise",
            })
            return steps

        if node.truth_value == "IN":
            # Find the valid justification
            for j in node.justifications:
                if self._justification_valid(j):
                    step = {
                        "node": node_id,
                        "truth_value": "IN",
                        "reason": f"{j.type} justification valid",
                        "antecedents": list(j.antecedents),
                        "label": j.label,
                    }
                    if j.outlist:
                        step["outlist"] = list(j.outlist)
                    steps.append(step)
                    # Recurse into antecedents
                    for ant_id in j.antecedents:
                        steps.extend(self.explain(ant_id))
                    break
        else:
            # All justifications invalid — explain why
            for j in node.justifications:
                failed = [
                    a for a in j.antecedents
                    if a in self.nodes and self.nodes[a].truth_value == "OUT"
                ]
                violated_outlist = [
                    o for o in j.outlist
                    if o in self.nodes and self.nodes[o].truth_value == "IN"
                ]
                step = {
                    "node": node_id,
                    "truth_value": "OUT",
                    "reason": f"{j.type} justification invalid",
                    "failed_antecedents": failed,
                    "label": j.label,
                }
                if violated_outlist:
                    step["violated_outlist"] = violated_outlist
                steps.append(step)

        return steps

    def get_belief_set(self) -> list[str]:
        """Return all node IDs currently IN."""
        return [nid for nid, node in self.nodes.items() if node.truth_value == "IN"]

    def _propagate(self, changed_id: str) -> list[str]:
        """BFS propagation of truth value changes through dependents."""
        changed = []
        queue = deque([changed_id])
        visited = {changed_id}

        while queue:
            current_id = queue.popleft()
            current = self.nodes[current_id]

            for dep_id in current.dependents:
                if dep_id in visited:
                    continue

                dep = self.nodes[dep_id]
                old_value = dep.truth_value
                new_value = self._compute_truth(dep)

                if old_value != new_value:
                    dep.truth_value = new_value
                    changed.append(dep_id)
                    self._log("propagate", dep_id, new_value)
                    visited.add(dep_id)
                    queue.append(dep_id)

        return changed

    def _compute_truth(self, node: Node) -> str:
        """Compute truth value from justifications.

        A node is IN if ANY justification is valid.
        """
        if not node.justifications:
            return node.truth_value  # premise — keep current value

        for j in node.justifications:
            if self._justification_valid(j):
                return "IN"
        return "OUT"

    def _justification_valid(self, j: Justification) -> bool:
        """Check if a justification is currently valid.

        SL: all antecedents (inlist) must be IN AND all outlist must be OUT.
        This enables non-monotonic reasoning: "believe X unless Y."
        """
        if j.type in ("SL", "CP"):
            inlist_ok = all(
                a in self.nodes and self.nodes[a].truth_value == "IN"
                for a in j.antecedents
            )
            outlist_ok = all(
                o not in self.nodes or self.nodes[o].truth_value == "OUT"
                for o in j.outlist
            )
            return inlist_ok and outlist_ok
        return False

    def _log(self, action: str, target: str, value: str) -> None:
        """Record a propagation event."""
        self.log.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "target": target,
            "value": value,
        })
