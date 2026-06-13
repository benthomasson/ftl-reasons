"""Build a static wiki from the belief network.

Exports beliefs as interlinked markdown pages grouped by topic
(word-frequency) or semantic cluster.
"""

import os
import re


_TOPIC_STOP_WORDS = {
    "the", "is", "in", "to", "of", "and", "or", "not", "as", "by",
    "via", "can", "with", "from", "than", "that", "this", "be", "has",
    "have", "it", "its", "no", "do", "if", "so", "up", "out", "all",
    "but", "get", "set", "only", "per", "use", "may", "one", "two",
    "new", "any", "each", "must", "when", "how", "also", "into",
    "over", "more", "both", "same", "own", "used", "using", "based",
    "does", "then", "for",
}


def _assign_topics(node_ids, topics):
    """Assign each node to its best-matching topic based on ID segments.

    Returns {topic_label: [node_id, ...], ...} with "Other" for unmatched.
    """
    topic_set = {t["topic"] for t in topics}
    groups = {t["topic"]: [] for t in topics}
    groups["Other"] = []

    for nid in node_ids:
        words = [w for w in re.split(r'[-._:]', nid) if w and len(w) > 2]
        matched = False
        for word in words:
            if word in topic_set:
                groups[word].append(nid)
                matched = True
                break
        if not matched:
            groups["Other"].append(nid)

    return {k: v for k, v in groups.items() if v}


def _page_name(label):
    """Sanitize a topic/cluster label to a valid markdown filename."""
    safe = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')
    return safe or "other"


def _format_node(node_id, node_detail, node_to_page):
    """Render one node as markdown with cross-reference links."""
    lines = []
    lines.append(f"### {node_id}")
    lines.append(f"**Status:** {node_detail['truth_value']}")
    lines.append("")
    lines.append(node_detail["text"])
    lines.append("")

    antecedents = set()
    for j in node_detail.get("justifications", []):
        for a in j.get("antecedents", []):
            antecedents.add(a)

    if antecedents:
        links = []
        for a in sorted(antecedents):
            page = node_to_page.get(a)
            if page:
                links.append(f"[{a}]({page}#{a})")
            else:
                links.append(a)
        lines.append(f"**Depends on:** {', '.join(links)}")

    dependents = node_detail.get("dependents", [])
    if dependents:
        links = []
        for d in sorted(dependents):
            page = node_to_page.get(d)
            if page:
                links.append(f"[{d}]({page}#{d})")
            else:
                links.append(d)
        lines.append(f"**Supports:** {', '.join(links)}")

    lines.append("")
    return "\n".join(lines)


def build_wiki(node_details, groups, output_dir):
    """Write index.md and per-group pages to output_dir.

    Args:
        node_details: {node_id: show_node dict}
        groups: {group_label: [node_id, ...]}
        output_dir: directory to write markdown files into
    """
    os.makedirs(output_dir, exist_ok=True)

    node_to_page = {}
    for label, nids in groups.items():
        page_file = _page_name(label) + ".md"
        for nid in nids:
            node_to_page[nid] = page_file

    index_lines = ["# Belief Wiki", ""]
    index_lines.append("| Topic | Beliefs |")
    index_lines.append("|-------|---------|")
    for label in sorted(groups, key=lambda l: (-len(groups[l]), l)):
        page_file = _page_name(label) + ".md"
        count = len(groups[label])
        index_lines.append(f"| [{label}]({page_file}) | {count} |")
    index_lines.append("")

    total = sum(len(nids) for nids in groups.values())
    index_lines.append(f"*{total} beliefs across {len(groups)} pages*")
    index_lines.append("")

    with open(os.path.join(output_dir, "index.md"), "w") as f:
        f.write("\n".join(index_lines))

    for label, nids in groups.items():
        page_file = _page_name(label) + ".md"
        page_lines = [f"# {label}", ""]
        page_lines.append(f"[Back to index](index.md)")
        page_lines.append("")
        for nid in sorted(nids):
            detail = node_details.get(nid)
            if detail:
                page_lines.append(_format_node(nid, detail, node_to_page))
        with open(os.path.join(output_dir, page_file), "w") as f:
            f.write("\n".join(page_lines))

    return {"output_dir": output_dir, "pages": len(groups), "total_nodes": total}
