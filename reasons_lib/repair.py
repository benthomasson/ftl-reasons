"""Repair smuggled premises by search-and-link.

Given beliefs flagged invalid by review-beliefs (smuggled premise —
conclusion introduces facts not present in any antecedent), this module:
1. Extracts the specific smuggled claim via LLM
2. Searches the belief network for matching premises
3. Wires found premises as new antecedents via add_justification

Requires two LLM calls per invalid belief (extract + match).
"""

import json
import sys

from .llm import invoke_model
from .review import format_belief_for_review

EXTRACT_PROMPT = """\
You are analyzing a derived belief that was flagged as invalid in a Truth Maintenance System.
The belief's conclusion introduces a factual claim not supported by its antecedents (a smuggled premise).

Your task: identify the specific factual claim that the conclusion smuggles in — the fact it
relies on that is NOT stated or implied by any antecedent.

## Invalid belief

{belief_context}

## Review finding

{review_comment}

Respond with ONLY a single concise factual claim (one sentence, no preamble) that captures
what specific knowledge the conclusion assumes but the antecedents do not provide.
Do NOT restate the conclusion. Extract the missing piece — the gap between what the
antecedents establish and what the conclusion asserts.

Smuggled claim:"""

MATCH_PROMPT = """\
You are matching a smuggled claim against existing premises in a belief network.
The smuggled claim is a factual assertion that was missing from a derivation's antecedents.
Your task: determine which (if any) of the candidate premises below directly supports
this smuggled claim.

## Smuggled claim

{smuggled_claim}

## Candidate premises

{candidates}

Rules:
- A premise "supports" the smuggled claim if it states or directly implies the same fact.
- Do NOT match premises that are merely topically related — they must actually establish
  the smuggled fact.
- If multiple premises jointly support the claim, list all of them.
- If no premise supports the claim, say "none".

Respond with ONLY a JSON object in this exact format:
{{"matched_ids": ["premise-id-1", "premise-id-2"], "rationale": "brief explanation"}}

If no match: {{"matched_ids": [], "rationale": "brief explanation"}}"""


def parse_extract_response(response):
    """Extract the smuggled claim string from LLM response."""
    text = response.strip()
    if not text:
        return ""
    for prefix in ("Smuggled claim:", "smuggled claim:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    if len(text) > 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


def parse_match_response(response, valid_ids):
    """Extract match result JSON from LLM response.

    Uses raw_decode to find JSON object in response text.
    Filters matched_ids to only include IDs in valid_ids.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(response):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(response, i)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        matched = obj.get("matched_ids", [])
        if not isinstance(matched, list):
            matched = []
        filtered = [mid for mid in matched if mid in valid_ids]
        return {
            "matched_ids": filtered,
            "rationale": obj.get("rationale", ""),
        }
    return {"matched_ids": [], "rationale": ""}


def extract_smuggled_claim(belief_context, review_comment, model="claude",
                           timeout=300):
    """LLM call 1: extract the smuggled claim from an invalid belief."""
    prompt = EXTRACT_PROMPT.format(
        belief_context=belief_context,
        review_comment=review_comment,
    )
    response = invoke_model(prompt, model=model, timeout=timeout)
    return parse_extract_response(response)


def find_matching_premises(smuggled_claim, candidates, model="claude",
                           timeout=300):
    """LLM call 2: match smuggled claim against candidate premises.

    Args:
        smuggled_claim: extracted claim string
        candidates: list of {"id": str, "text": str} dicts (IN premises)
    """
    if not candidates:
        return {"matched_ids": [], "rationale": "no candidates found"}

    candidate_lines = "\n".join(
        f"- `{c['id']}`: {c['text']}" for c in candidates
    )
    prompt = MATCH_PROMPT.format(
        smuggled_claim=smuggled_claim,
        candidates=candidate_lines,
    )
    response = invoke_model(prompt, model=model, timeout=timeout)
    valid_ids = {c["id"] for c in candidates}
    return parse_match_response(response, valid_ids)


def repair_smuggled_beliefs(review_results, nodes, model="claude",
                            timeout=300, db_path=None, dry_run=False,
                            search_fn=None):
    """Orchestrate search-and-link repair for invalid beliefs.

    Args:
        review_results: list of review dicts with valid=False
        nodes: full nodes dict from export_network()
        model: LLM model for extract/match calls
        timeout: LLM timeout
        db_path: database path for add_justification
        dry_run: if True, report without applying
        search_fn: callable(query, format, db_path) for search (injectable for tests)

    Returns:
        list of repair result dicts
    """
    from . import api

    if search_fn is None:
        search_fn = lambda query, **kw: api.search(query, **kw)

    invalid = [r for r in review_results if not r.get("valid", True)]
    repairs = []

    for r in invalid:
        belief_id = r["id"]
        result = {
            "id": belief_id,
            "status": "error",
            "smuggled_claim": None,
            "matched_premises": [],
            "rationale": None,
            "error": None,
        }

        try:
            node = nodes.get(belief_id)
            if not node:
                result["error"] = "belief not found in network"
                repairs.append(result)
                continue

            belief_context = format_belief_for_review(belief_id, nodes)
            comment = r.get("comment", "")

            print(f"  Extracting smuggled claim for {belief_id}...",
                  file=sys.stderr)
            claim = extract_smuggled_claim(belief_context, comment,
                                           model=model, timeout=timeout)
            result["smuggled_claim"] = claim

            if not claim:
                result["status"] = "extraction_failed"
                repairs.append(result)
                continue

            existing_ants = set()
            for j in node.get("justifications", []):
                existing_ants.update(j.get("antecedents", []))

            print(f"  Searching for: {claim[:80]}...", file=sys.stderr)
            raw = search_fn(claim, format="json", db_path=db_path)
            try:
                search_results = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                search_results = []

            candidates = []
            for sr in search_results:
                sid = sr.get("id", "")
                if sid == belief_id:
                    continue
                if sid in existing_ants:
                    continue
                if sr.get("truth_value") != "IN":
                    continue
                sr_node = nodes.get(sid)
                if sr_node and sr_node.get("justifications"):
                    continue
                candidates.append({"id": sid, "text": sr.get("text", "")})

            if not candidates:
                result["status"] = "no_candidates"
                repairs.append(result)
                continue

            print(f"  Matching against {len(candidates)} candidate(s)...",
                  file=sys.stderr)
            match = find_matching_premises(claim, candidates,
                                           model=model, timeout=timeout)
            matched_ids = match.get("matched_ids", [])
            result["rationale"] = match.get("rationale", "")

            if not matched_ids:
                result["status"] = "no_match"
                repairs.append(result)
                continue

            result["matched_premises"] = matched_ids

            if not dry_run:
                first_just = node.get("justifications", [{}])[0]
                original_ants = first_just.get("antecedents", [])
                new_ants = list(original_ants) + matched_ids
                api.add_justification(
                    belief_id,
                    sl=",".join(new_ants),
                    label=f"repair-smuggled: {claim[:60]}",
                    db_path=db_path,
                )

            result["status"] = "repaired"

        except Exception as exc:
            result["error"] = str(exc)

        repairs.append(result)

    return repairs
