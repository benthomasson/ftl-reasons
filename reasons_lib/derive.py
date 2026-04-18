"""Derive deeper reasoning chains from existing beliefs.

Analyzes the belief network for opportunities to combine existing
conclusions into higher-level claims, and to connect positive and
negative chains via outlist semantics (GATE beliefs).

When agent-namespaced nodes are present (from import-agent), groups
beliefs by agent and encourages cross-agent derivations.
"""

import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from . import api


DERIVE_PROMPT = """\
You are a reasoning architect analyzing a belief network. Your task is to \
identify opportunities for deeper derived conclusions by combining existing beliefs.

{domain_context}

## Background

A Reason Maintenance System (RMS) tracks beliefs with justifications and automatic retraction \
cascades. There are three kinds of nodes:

1. **Base premises** (depth-0): Observable facts with no justifications
2. **Derived conclusions** (depth-1+): Justified by antecedents via SL (support-list) rules
3. **Outlist-gated conclusions**: Justified by antecedents UNLESS certain nodes are IN \
   (the conclusion is OUT while the outlist node is IN, and flips IN when it goes OUT)

When a base premise is retracted, all derived conclusions that depend on it cascade OUT \
automatically. This is the key value — maintaining consistency without manual intervention.

## Your Task

Given the existing beliefs and derived conclusions below, propose NEW derived conclusions that:

1. **Combine existing conclusions** into higher-level claims (depth N+1 from depth N)
2. **Group related base beliefs** into thematic conclusions (new depth-1)
3. **Connect positive and negative chains** via outlist semantics — where a positive claim \
   should only hold when a negative claim (bug/issue/gap) is OUT
{cross_agent_task}

## Rules

- Each proposed conclusion must have at least 2 antecedents
- Antecedents must be existing belief IDs from the list below
- Prefer combining existing derived beliefs (deeper chains) over just grouping base beliefs
- For outlist-gated beliefs: the antecedent should be a positive claim, the unless should be \
  a negative claim (bug, gap, issue, fragility)
- Don't propose conclusions that merely restate a single antecedent
- Don't propose conclusions whose antecedents are unrelated (no forced connections)
- Each conclusion should represent a genuine emergent property or insight

## Output Format

For each proposed conclusion, output EXACTLY this format:

### DERIVE <belief-id-in-kebab-case>
<one-line claim text>
- Antecedents: <comma-separated list of existing belief IDs>
- Label: <brief justification rationale>

For outlist-gated conclusions:

### GATE <belief-id-in-kebab-case>
<one-line claim text>
- Antecedents: <comma-separated list of existing belief IDs>
- Unless: <comma-separated list of belief IDs that must be OUT>
- Label: <brief justification rationale>

---

## Existing Beliefs

{beliefs_section}

## Existing Derived Conclusions

{derived_section}

## Statistics

- Total IN beliefs: {total_in}
- Existing derived: {total_derived}
- Max depth: {max_depth}
{agents_stats}
"""

CROSS_AGENT_TASK = """
4. **Derive cross-agent beliefs** that combine knowledge from different agents. \
   These are especially valuable — they represent architectural knowledge that \
   spans multiple codebases or domains. A cross-agent belief is IN only when \
   ALL contributing agents agree."""


def _get_depth(node_id, nodes, derived, memo=None):
    """Compute the depth of a node in the reasoning chain."""
    if memo is None:
        memo = {}
    if node_id in memo:
        return memo[node_id]
    if node_id not in derived:
        memo[node_id] = 0
        return 0
    memo[node_id] = 0  # cycle guard
    max_d = 0
    for j in derived[node_id].get("justifications", []):
        for a in j.get("antecedents", []):
            max_d = max(max_d, _get_depth(a, nodes, derived, memo))
    memo[node_id] = max_d + 1
    return max_d + 1


def _detect_agents(nodes):
    """Detect agent namespaces from node IDs.

    Returns dict of agent_name -> list of node IDs.
    Agent nodes have IDs like 'agent-name:belief-id' and metadata
    with an 'agent' field.
    """
    agents = defaultdict(list)
    for nid, node in nodes.items():
        if ":" in nid:
            agent = nid.split(":")[0]
            # Skip the :active premise nodes
            if nid.endswith(":active"):
                continue
            agents[agent].append(nid)
    return dict(agents)


def _filter_by_topic(nodes, topic):
    """Filter nodes by keyword matching on ID and text.

    Returns only nodes whose ID or text contains any of the
    space-separated keywords (case-insensitive).
    """
    keywords = topic.lower().split()
    filtered = {}
    for nid, node in nodes.items():
        searchable = f"{nid} {node.get('text', '')}".lower()
        if any(kw in searchable for kw in keywords):
            filtered[nid] = node
    return filtered


def _sample_beliefs(belief_ids, budget, rng=None):
    """Randomly sample up to budget belief IDs.

    Uses reservoir sampling to get a uniform random subset.
    """
    if len(belief_ids) <= budget:
        return belief_ids
    if rng is None:
        rng = random.Random()
    return rng.sample(belief_ids, budget)


def _build_beliefs_section(nodes, derived, agents=None, max_beliefs=300,
                           sample=False, seed=None):
    """Build a compact beliefs section for the derive prompt.

    Args:
        max_beliefs: Maximum number of beliefs to include (budget).
        sample: If True, randomly sample beliefs instead of alphabetical truncation.
        seed: Random seed for reproducible sampling.
    """
    lines = []
    rng = random.Random(seed) if sample else None
    in_nodes = {k: v for k, v in nodes.items()
                if v.get("truth_value") == "IN" and k not in derived}

    if agents:
        # Allocate budget proportionally across agents
        total_agent_beliefs = sum(
            len([k for k in in_nodes if k.startswith(f"{a}:")])
            for a in agents
        )
        non_agent = {k: v for k, v in in_nodes.items() if ":" not in k}
        total_all = total_agent_beliefs + len(non_agent)

        count = 0
        for agent_name in sorted(agents, key=lambda a: -len(agents[a])):
            agent_beliefs = {k: v for k, v in in_nodes.items()
                            if k.startswith(f"{agent_name}:")}
            if not agent_beliefs:
                continue

            # Proportional budget per agent
            if total_all > 0:
                agent_budget = max(5, int(max_beliefs * len(agent_beliefs) / total_all))
            else:
                agent_budget = max_beliefs

            belief_ids = sorted(agent_beliefs.keys())
            if sample:
                belief_ids = _sample_beliefs(belief_ids, agent_budget, rng)
                belief_ids.sort()
            else:
                belief_ids = belief_ids[:agent_budget]

            lines.append(f"\n### Agent: {agent_name} ({len(agent_beliefs)} beliefs, "
                         f"showing {len(belief_ids)})")
            for belief_id in belief_ids:
                text = agent_beliefs[belief_id]["text"][:120]
                lines.append(f"- `{belief_id}`: {text}")
                count += len(belief_ids)

        # Non-agent beliefs
        if non_agent:
            remaining = max(5, max_beliefs - count)
            local_ids = sorted(non_agent.keys())
            if sample:
                local_ids = _sample_beliefs(local_ids, remaining, rng)
                local_ids.sort()
            else:
                local_ids = local_ids[:remaining]
            lines.append(f"\n### Local beliefs ({len(non_agent)} beliefs, "
                         f"showing {len(local_ids)})")
            for belief_id in local_ids:
                text = non_agent[belief_id]["text"][:120]
                lines.append(f"- `{belief_id}`: {text}")
    else:
        # Group by prefix (original code-expert behavior)
        groups = defaultdict(list)
        for k, v in in_nodes.items():
            prefix = k.split("-")[0] if "-" in k else k
            groups[prefix].append((k, v["text"][:120]))

        if sample:
            # Flatten, sample, regroup for display
            all_items = [(k, text) for items in groups.values() for k, text in items]
            sampled_keys = set(k for k, _ in _sample_beliefs(all_items, max_beliefs, rng))
            count = 0
            for prefix in sorted(groups, key=lambda p: -len(groups[p])):
                prefix_items = [(k, t) for k, t in groups[prefix] if k in sampled_keys]
                if not prefix_items:
                    continue
                lines.append(f"\n### {prefix} ({len(groups[prefix])} beliefs, "
                             f"showing {len(prefix_items)})")
                for belief_id, text in sorted(prefix_items):
                    lines.append(f"- `{belief_id}`: {text}")
                    count += 1
        else:
            count = 0
            for prefix in sorted(groups, key=lambda p: -len(groups[p])):
                if count >= max_beliefs:
                    break
                lines.append(f"\n### {prefix} ({len(groups[prefix])} beliefs)")
                for belief_id, text in sorted(groups[prefix]):
                    if count >= max_beliefs:
                        break
                    lines.append(f"- `{belief_id}`: {text}")
                    count += 1

    return "\n".join(lines)


def _build_derived_section(nodes, derived):
    """Build the derived conclusions section for the derive prompt."""
    memo = {}
    lines = []
    for k in sorted(derived, key=lambda x: -_get_depth(x, nodes, derived, memo)):
        depth = _get_depth(k, nodes, derived, memo)
        text = nodes[k]["text"][:150]
        justs = derived[k]["justifications"]
        antes = justs[0].get("antecedents", []) if justs else []
        outlist = justs[0].get("outlist", []) if justs else []
        status = nodes[k].get("truth_value", "?")

        lines.append(f"\n#### [{status}] depth-{depth}: `{k}`")
        lines.append(text)
        lines.append(f"- Antecedents: {', '.join(antes)}")
        if outlist:
            lines.append(f"- Unless: {', '.join(outlist)}")

    return "\n".join(lines) if lines else "(No derived conclusions yet)"


def parse_proposals(response):
    """Parse DERIVE and GATE proposals from LLM response.

    Supports two formats:
    - New (v0.10+): ### DERIVE belief-id
    - Old (v0.9):   ### DERIVE: `belief-id`  /  ### GATE (outlist): `belief-id`
    """
    proposals = []

    # New format: ### DERIVE id  or  ### GATE id
    new_pattern = re.compile(
        r"### (DERIVE|GATE) (\S+)\n"
        r"(.+?)\n"
        r"- Antecedents: (.+?)\n"
        r"(?:- Unless: (.+?)\n)?"
        r"- Label: (.+?)(?:\n|$)",
    )
    for match in new_pattern.finditer(response):
        proposal = {
            "kind": match.group(1).lower(),
            "id": match.group(2).strip("`"),
            "text": match.group(3).strip(),
            "antecedents": [a.strip().strip("`") for a in match.group(4).split(",")],
            "unless": [u.strip().strip("`") for u in match.group(5).split(",")]
                      if match.group(5) else [],
            "label": match.group(6).strip(),
        }
        proposals.append(proposal)

    if proposals:
        return proposals

    # Old format: ### DERIVE: `id`  or  ### GATE (outlist): `id`
    old_pattern = re.compile(
        r"### (?:DERIVE|GATE(?: \(outlist\))?):? `(\S+?)`\s*\n+"
        r"(.+?)\n+"
        r"- \*\*Antecedents\*\*: (.+?)\n"
        r"(?:- \*\*Unless\*\*: (.+?)\n)?"
        r"- \*\*Label\*\*: (.+?)(?:\n|$)",
    )
    for match in old_pattern.finditer(response):
        # Detect kind from the header text before the colon
        header_start = response[max(0, match.start() - 30):match.start() + 30]
        kind = "gate" if "GATE" in header_start else "derive"
        proposal = {
            "kind": kind,
            "id": match.group(1),
            "text": match.group(2).strip(),
            "antecedents": [a.strip().strip("`") for a in match.group(3).split(",")],
            "unless": [u.strip().strip("`") for u in match.group(4).split(",")]
                      if match.group(4) else [],
            "label": match.group(5).strip(),
        }
        proposals.append(proposal)

    return proposals


def build_prompt(nodes, domain=None, topic=None, budget=300, sample=False,
                 seed=None, min_depth=None, max_depth_filter=None,
                 premises_only=False, has_dependents=False):
    """Build the full derive prompt from a network's nodes dict.

    Args:
        nodes: Dict of node_id -> node data from export_network.
        domain: Optional domain description for context.
        topic: Optional keyword filter — only include beliefs matching these keywords.
        budget: Maximum number of beliefs to include in the prompt (default: 300).
        sample: If True, randomly sample beliefs instead of alphabetical truncation.
        seed: Random seed for reproducible sampling.
        min_depth: Only include beliefs at this depth or deeper.
        max_depth_filter: Only include beliefs at this depth or shallower.

    Returns: (prompt_text, stats_dict)
    """
    # Apply topic filter before anything else
    if topic:
        nodes = _filter_by_topic(nodes, topic)

    # Compute depth and dependency info from the full graph before filtering
    all_derived = {k: v for k, v in nodes.items()
                   if v.get("justifications") and len(v["justifications"]) > 0}
    memo = {}
    max_depth = max((_get_depth(k, nodes, all_derived, memo) for k in all_derived), default=0)

    referenced = set()
    for v in nodes.values():
        for j in v.get("justifications", []):
            referenced.update(j.get("antecedents", []))
            referenced.update(j.get("outlist", []))

    # Apply all filters
    need_depth = min_depth is not None or max_depth_filter is not None
    if premises_only or has_dependents or need_depth:
        filtered = {}
        for k, v in nodes.items():
            if premises_only and v.get("justifications"):
                continue
            if has_dependents and k not in referenced:
                continue
            if need_depth:
                d = _get_depth(k, nodes, all_derived, memo)
                if min_depth is not None and d < min_depth:
                    continue
                if max_depth_filter is not None and d > max_depth_filter:
                    continue
            filtered[k] = v
        nodes = filtered

    derived = {k: v for k, v in nodes.items()
               if v.get("justifications") and len(v["justifications"]) > 0}
    in_nodes = {k: v for k, v in nodes.items() if v.get("truth_value") == "IN"}
    if min_depth is not None or max_depth_filter is not None:
        max_depth = max((_get_depth(k, nodes, all_derived, memo) for k in derived), default=0)

    agents = _detect_agents(nodes)

    # Domain context
    if domain:
        domain_context = f"The beliefs in this network are about: {domain}"
    elif agents:
        agent_list = ", ".join(sorted(agents.keys()))
        domain_context = (
            f"This network contains beliefs from multiple agents: {agent_list}. "
            f"Each agent is an expert on a different codebase or domain."
        )
    else:
        domain_context = ""

    if topic:
        domain_context += f"\n\nFiltered to beliefs matching: {topic}"

    # Cross-agent task instructions
    cross_agent_task = CROSS_AGENT_TASK if agents else ""

    # Agent stats
    agents_stats = ""
    if agents:
        parts = [f"- Agents: {len(agents)}"]
        for name in sorted(agents):
            parts.append(f"  - {name}: {len(agents[name])} beliefs")
        agents_stats = "\n".join(parts)

    beliefs_section = _build_beliefs_section(
        nodes, derived, agents, max_beliefs=budget,
        sample=sample, seed=seed,
    )
    derived_section = _build_derived_section(nodes, derived)

    prompt = DERIVE_PROMPT.format(
        domain_context=domain_context,
        beliefs_section=beliefs_section,
        derived_section=derived_section,
        total_in=len(in_nodes),
        total_derived=len(derived),
        max_depth=max_depth,
        cross_agent_task=cross_agent_task,
        agents_stats=agents_stats,
    )

    stats = {
        "total_in": len(in_nodes),
        "total_derived": len(derived),
        "max_depth": max_depth,
        "agents": len(agents),
        "agent_names": sorted(agents.keys()) if agents else [],
    }
    if topic:
        stats["topic"] = topic
    if min_depth is not None:
        stats["min_depth"] = min_depth
    if max_depth_filter is not None:
        stats["max_depth_filter"] = max_depth_filter
    stats["budget"] = budget
    stats["sample"] = sample

    return prompt, stats


def _tokenize_id(node_id):
    """Split a belief ID into a set of lowercase tokens."""
    return set(node_id.lower().replace(":", "-").split("-"))


def _jaccard(a, b):
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_similar_out(proposal_id, nodes, threshold=0.5):
    """Find OUT beliefs whose ID is similar to the proposed ID.

    Returns list of (out_id, similarity) above threshold, sorted by similarity desc.
    """
    p_tokens = _tokenize_id(proposal_id)
    matches = []
    for nid, node in nodes.items():
        if node.get("truth_value") != "OUT":
            continue
        sim = _jaccard(p_tokens, _tokenize_id(nid))
        if sim >= threshold:
            matches.append((nid, sim))
    matches.sort(key=lambda x: -x[1])
    return matches


def validate_proposals(proposals, nodes):
    """Validate proposals against the network. Returns (valid, skipped)."""
    valid = []
    skipped = []
    for p in proposals:
        missing = [a for a in p["antecedents"] if a not in nodes]
        missing_unless = [u for u in p["unless"] if u not in nodes]
        if missing or missing_unless:
            skipped.append((p, f"missing nodes: {missing + missing_unless}"))
            continue
        if p["id"] in nodes:
            skipped.append((p, "already exists"))
            continue
        similar = find_similar_out(p["id"], nodes)
        if similar:
            best_id, best_sim = similar[0]
            skipped.append((p, f"similar to retracted belief: {best_id} ({best_sim:.0%} overlap)"))
            continue
        valid.append(p)
    return valid, skipped


def apply_proposals(valid, db_path="reasons.db"):
    """Add valid proposals to the reasons database.

    Returns list of (proposal, result_dict_or_error_string).
    """
    results = []
    for p in valid:
        try:
            sl = ",".join(p["antecedents"])
            unless = ",".join(p["unless"]) if p["unless"] else ""
            result = api.add_node(
                node_id=p["id"],
                text=p["text"],
                sl=sl,
                unless=unless,
                label=p["label"],
                db_path=db_path,
            )
            results.append((p, result))
        except Exception as e:
            results.append((p, str(e)))
    return results


def write_proposals_file(valid, output_path):
    """Write proposals to a markdown file for human review.

    Uses the same ### DERIVE / ### GATE format that parse_proposals() can read,
    so `reasons accept` can parse the file directly.
    """
    with open(output_path, "w") as f:
        f.write("# Proposed Derivations\n\n")
        f.write("Review each proposal below. Delete any you don't want, then run:\n")
        f.write("  reasons accept proposed-derivations.md\n\n")
        f.write("---\n\n")

        for p in valid:
            kind = "DERIVE" if p["kind"] == "derive" else "GATE"
            f.write(f"### {kind} {p['id']}\n")
            f.write(f"{p['text']}\n")
            f.write(f"- Antecedents: {', '.join(p['antecedents'])}\n")
            if p["unless"]:
                f.write(f"- Unless: {', '.join(p['unless'])}\n")
            f.write(f"- Label: {p['label']}\n\n")

    return output_path
