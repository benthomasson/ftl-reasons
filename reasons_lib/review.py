"""Review derived beliefs for validity, sufficiency, and necessity.

Feeds each derived belief and its full justification chain back to an
LLM to evaluate whether the derivation is semantically sound, not just
structurally valid.
"""

import json
import sys

from .llm import invoke_model

REVIEW_BATCH_SIZE = 20

REVIEW_PROMPT = """\
You are auditing derived beliefs in a Truth Maintenance System (TMS).
Each belief below was derived from its antecedents by an earlier LLM pass.
The system validated that the antecedents exist, but did not verify that
the reasoning from antecedents to conclusion is sound.

For each belief, evaluate three axes:

1. **Valid**: Does this conclusion logically follow from its antecedents?
   The antecedent texts are provided. Does the claim represent a sound
   inference, or is it a plausible-sounding leap?

2. **Sufficient**: Are the listed antecedents enough to support this
   conclusion, or does the derivation require additional unstated
   assumptions?

3. **Necessary**: Are all antecedents load-bearing? Could any be removed
   without weakening the conclusion?

Return ONLY a JSON array. For each belief, one object:

```json
[
  {{
    "id": "belief-id",
    "valid": true,
    "sufficient": true,
    "necessary": false,
    "unnecessary_antecedents": ["ant-id-1"],
    "comment": "brief explanation"
  }}
]
```

Rules:
- Return one object per belief reviewed, in the same order as presented.
- A belief may have multiple justifications (alternative support paths).
  It is valid if ANY justification is sound. Evaluate each independently.
- "unnecessary_antecedents" should be empty [] if all are necessary.
- "comment" should be a single sentence explaining the most important finding.
- Be rigorous: a conclusion that sounds reasonable but doesn't follow
  strictly from the antecedents is NOT valid.

## Beliefs to review

{beliefs}"""


def format_belief_for_review(node_id, nodes):
    """Format one derived belief with antecedent texts for LLM review."""
    node = nodes.get(node_id)
    if not node:
        return ""

    lines = [f"### {node_id}"]
    lines.append(f"Claim: {node.get('text', '')}")

    justs = node.get("justifications", [])
    for ji, j in enumerate(justs):
        antecedents = j.get("antecedents", [])
        outlist = j.get("outlist", [])
        label = j.get("label", "")

        if len(justs) > 1:
            lines.append(f"Justification {ji + 1}/{len(justs)}:")

        if antecedents:
            lines.append("Antecedents:")
            for ant_id in antecedents:
                ant_node = nodes.get(ant_id)
                if ant_node:
                    lines.append(f"- {ant_id}: {ant_node.get('text', '')}")
                else:
                    lines.append(f"- {ant_id}: (not found in network)")

        if outlist:
            lines.append("Unless (must be OUT):")
            for out_id in outlist:
                out_node = nodes.get(out_id)
                if out_node:
                    lines.append(f"- {out_id}: {out_node.get('text', '')}")
                else:
                    lines.append(f"- {out_id}: (not found in network)")

        if label:
            lines.append(f"Label: {label}")

    return "\n".join(lines)


def parse_review_response(response):
    """Extract review results JSON array from LLM response.

    Tries json.JSONDecoder.raw_decode at each '[' position to handle
    prose brackets before the JSON array and trailing text after it.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(response):
        if ch != "[":
            continue
        try:
            items, _ = decoder.raw_decode(response, i)
        except json.JSONDecodeError:
            continue
        if not isinstance(items, list):
            continue
        results = []
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                continue
            results.append({
                "id": item["id"],
                "valid": item.get("valid", True),
                "sufficient": item.get("sufficient", True),
                "necessary": item.get("necessary", True),
                "unnecessary_antecedents": item.get("unnecessary_antecedents", []),
                "comment": item.get("comment", ""),
            })
        if results:
            return results
    return []


def review_beliefs(nodes, belief_ids=None, model="claude", timeout=300,
                   batch_size=REVIEW_BATCH_SIZE):
    """Review derived beliefs for validity, sufficiency, and necessity.

    Args:
        nodes: Dict of node_id -> node data from export_network().
        belief_ids: Optional list of specific IDs to review.
            If None, reviews all derived IN beliefs.
        model: LLM model to use for review.
        timeout: LLM timeout in seconds.
        batch_size: Number of beliefs per LLM call.

    Returns: list of review result dicts.
    """
    if belief_ids is None:
        belief_ids = [
            nid for nid, node in sorted(nodes.items())
            if node.get("truth_value") == "IN"
            and node.get("justifications")
            and len(node["justifications"]) > 0
        ]
    else:
        belief_ids = [
            nid for nid in belief_ids
            if nid in nodes
            and nodes[nid].get("justifications")
            and len(nodes[nid]["justifications"]) > 0
        ]

    if not belief_ids:
        return []

    all_results = []
    total_batches = (len(belief_ids) + batch_size - 1) // batch_size

    for i in range(0, len(belief_ids), batch_size):
        batch = belief_ids[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Reviewing batch {batch_num}/{total_batches} "
              f"({len(batch)} beliefs)...", file=sys.stderr)

        beliefs_text = "\n\n".join(
            format_belief_for_review(nid, nodes) for nid in batch
        )
        prompt = REVIEW_PROMPT.format(beliefs=beliefs_text)

        try:
            response = invoke_model(prompt, model=model, timeout=timeout)
            results = parse_review_response(response)
            all_results.extend(results)
        except Exception as e:
            print(f"  WARN: batch {batch_num} failed: {e}", file=sys.stderr)

    return all_results
