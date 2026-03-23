"""Token-budgeted belief state summary for context injection.

Produces a compact summary of the network state suitable for inclusion
in CLAUDE.md files or LLM context windows. Prioritizes nogoods and
OUT nodes, then fills remaining budget with IN nodes.
"""

from datetime import date

from .network import Network


def estimate_tokens(text: str) -> int:
    """Rough token estimate — word count."""
    return len(text.split())


def compact(
    network: Network,
    budget: int = 500,
    truncate: bool = True,
) -> str:
    """Generate a token-budgeted belief state summary.

    Priority order:
    1. Nogoods (never dropped — these are the most critical)
    2. OUT nodes (need review)
    3. IN nodes by dependent count (most-depended-on first)

    Args:
        network: The RMS network
        budget: Maximum token budget (word count)
        truncate: If True, truncate node text to 80 chars
    """
    in_nodes = []
    out_nodes = []
    for node in network.nodes.values():
        if node.truth_value == "IN":
            in_nodes.append(node)
        else:
            out_nodes.append(node)

    # Sort IN nodes by dependent count (most depended on first)
    in_nodes.sort(key=lambda n: len(n.dependents), reverse=True)

    today = date.today().isoformat()
    in_count = len(in_nodes)
    out_count = len(out_nodes)
    total = in_count + out_count
    nogood_count = len(network.nogoods)

    lines = [
        f"# Belief State Summary ({today})",
        f"# {total} nodes tracked | {nogood_count} nogoods | {in_count} IN | {out_count} OUT",
        "",
    ]

    def _text(node):
        t = node.text
        if truncate and len(t) > 80:
            t = t[:77] + "..."
        return t

    # Section 1: Nogoods (never dropped)
    if network.nogoods:
        lines.append("## Nogoods")
        for ng in network.nogoods:
            res = f" — {ng.resolution}" if ng.resolution else ""
            lines.append(f"- {ng.id}: {', '.join(ng.nodes)}{res}")
        lines.append("")

    # Section 2: OUT nodes (need review)
    if out_nodes:
        lines.append("## OUT (retracted)")
        for node in out_nodes:
            reason = ""
            if node.metadata.get("stale_reason"):
                reason = f" (stale: {node.metadata['stale_reason'][:60]})"
            elif node.metadata.get("superseded_by"):
                reason = f" (superseded by: {node.metadata['superseded_by']})"
            lines.append(f"- {node.id}: {_text(node)}{reason}")
        lines.append("")

    # Section 3: IN nodes (budget-limited)
    # Use summaries to replace covered nodes when available
    if in_nodes:
        # Find which nodes are covered by summaries
        covered_by_summary: set[str] = set()
        summary_nodes = []
        regular_nodes = []
        for node in in_nodes:
            summarizes = node.metadata.get("summarizes")
            if summarizes:
                summary_nodes.append(node)
                # Only cover nodes if the summary is IN
                for covered_id in summarizes:
                    covered_by_summary.add(covered_id)
            else:
                regular_nodes.append(node)

        # Filter out covered nodes, keep summaries and uncovered nodes
        visible_nodes = summary_nodes + [
            n for n in regular_nodes if n.id not in covered_by_summary
        ]
        # Re-sort by dependent count
        visible_nodes.sort(key=lambda n: len(n.dependents), reverse=True)

        hidden_count = len(in_nodes) - len(visible_nodes)

        lines.append("## IN (active)")
        added = 0
        current_tokens = estimate_tokens("\n".join(lines))

        for node in visible_nodes:
            # Build the line
            is_summary = bool(node.metadata.get("summarizes"))
            prefix = "[summary] " if is_summary else ""
            deps = ""
            for j in node.justifications:
                if j.antecedents and j.label != "summarizes":
                    deps = f" <- {', '.join(j.antecedents)}"
                    break
            dep_count = len(node.dependents)
            dep_info = f" ({dep_count} dependents)" if dep_count else ""
            summarizes = node.metadata.get("summarizes", [])
            sum_info = f" (covers {len(summarizes)} nodes)" if summarizes else ""
            line = f"- {prefix}{node.id}: {_text(node)}{deps}{dep_info}{sum_info}"

            line_tokens = estimate_tokens(line)
            if current_tokens + line_tokens > budget:
                remaining = len(visible_nodes) - added
                lines.append(f"  ... ({remaining} more IN nodes omitted)")
                break

            lines.append(line)
            current_tokens += line_tokens
            added += 1

        if hidden_count:
            lines.append(f"  ({hidden_count} nodes hidden by summaries)")
        lines.append("")

    token_count = estimate_tokens("\n".join(lines))
    lines.append(f"Token count: ~{token_count} / {budget} budget")

    return "\n".join(lines)
