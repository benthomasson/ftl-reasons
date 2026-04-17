"""Tests for derive: reasoning chain derivation."""

import pytest

from reasons_lib import api
from reasons_lib.derive import (
    build_prompt,
    parse_proposals,
    validate_proposals,
    apply_proposals,
    write_proposals_file,
    find_similar_out,
    _detect_agents,
    _filter_by_topic,
    _sample_beliefs,
    _get_depth,
    _tokenize_id,
    _jaccard,
)


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "reasons.db")
    api.init_db(db_path=db_path)
    return db_path


@pytest.fixture
def simple_network(db):
    """A small network with premises and one derived node."""
    api.add_node("fact-a", "Alpha is true", db_path=db)
    api.add_node("fact-b", "Beta is true", db_path=db)
    api.add_node("fact-c", "Gamma is a bug", db_path=db)
    api.add_node("derived-ab", "Alpha and Beta combined",
                 sl="fact-a,fact-b", label="test", db_path=db)
    return db


@pytest.fixture
def agent_network(db):
    """A network with two imported agents."""
    # Simulate agent imports by adding namespaced nodes
    api.add_node("agent-a:active", "Agent A is trusted", db_path=db)
    api.add_node("agent-a:knows-auth", "Agent A knows about auth",
                 sl="agent-a:active", label="imported from agent: agent-a",
                 db_path=db)
    api.add_node("agent-a:knows-routing", "Agent A knows about routing",
                 sl="agent-a:active", label="imported from agent: agent-a",
                 db_path=db)

    api.add_node("agent-b:active", "Agent B is trusted", db_path=db)
    api.add_node("agent-b:knows-gateway", "Agent B knows about the gateway",
                 sl="agent-b:active", label="imported from agent: agent-b",
                 db_path=db)
    return db


def test_build_prompt_basic(simple_network):
    data = api.export_network(db_path=simple_network)
    prompt, stats = build_prompt(data["nodes"])

    assert stats["total_in"] == 4
    assert stats["total_derived"] == 1
    assert stats["max_depth"] == 1
    assert stats["agents"] == 0
    assert "fact-a" in prompt
    assert "derived-ab" in prompt


def test_build_prompt_with_domain(simple_network):
    data = api.export_network(db_path=simple_network)
    prompt, _ = build_prompt(data["nodes"], domain="Greek alphabet")

    assert "Greek alphabet" in prompt


def test_build_prompt_detects_agents(agent_network):
    data = api.export_network(db_path=agent_network)
    prompt, stats = build_prompt(data["nodes"])

    assert stats["agents"] == 2
    assert "agent-a" in stats["agent_names"]
    assert "agent-b" in stats["agent_names"]
    assert "cross-agent" in prompt.lower()
    assert "Agent: agent-a" in prompt
    assert "Agent: agent-b" in prompt


def test_detect_agents():
    nodes = {
        "agent-a:active": {},
        "agent-a:belief-1": {},
        "agent-a:belief-2": {},
        "agent-b:active": {},
        "agent-b:belief-1": {},
        "local-belief": {},
    }
    agents = _detect_agents(nodes)
    assert "agent-a" in agents
    assert "agent-b" in agents
    assert len(agents["agent-a"]) == 2  # excludes :active
    assert len(agents["agent-b"]) == 1


def test_get_depth():
    nodes = {
        "a": {"justifications": []},
        "b": {"justifications": []},
        "c": {"justifications": [{"antecedents": ["a", "b"]}]},
        "d": {"justifications": [{"antecedents": ["c"]}]},
    }
    derived = {k: v for k, v in nodes.items() if v["justifications"]}

    assert _get_depth("a", nodes, derived) == 0
    assert _get_depth("c", nodes, derived) == 1
    assert _get_depth("d", nodes, derived) == 2


def test_parse_proposals_derive():
    response = """Here are my proposals:

### DERIVE combined-auth-gateway
Auth tokens flow through the gateway with validation at each layer
- Antecedents: agent-a:knows-auth, agent-b:knows-gateway
- Label: cross-agent authentication flow
"""
    proposals = parse_proposals(response)
    assert len(proposals) == 1
    p = proposals[0]
    assert p["kind"] == "derive"
    assert p["id"] == "combined-auth-gateway"
    assert p["antecedents"] == ["agent-a:knows-auth", "agent-b:knows-gateway"]
    assert p["unless"] == []
    assert p["label"] == "cross-agent authentication flow"


def test_parse_proposals_gate():
    response = """
### GATE feature-ready
Feature X is production-ready
- Antecedents: fact-a, fact-b
- Unless: fact-c
- Label: gated on bug resolution
"""
    proposals = parse_proposals(response)
    assert len(proposals) == 1
    p = proposals[0]
    assert p["kind"] == "gate"
    assert p["unless"] == ["fact-c"]


def test_parse_proposals_multiple():
    response = """
### DERIVE first-one
First derived belief
- Antecedents: a, b
- Label: first

### GATE second-one
Second gated belief
- Antecedents: c
- Unless: d
- Label: second
"""
    proposals = parse_proposals(response)
    assert len(proposals) == 2


def test_validate_proposals_missing_antecedent():
    nodes = {"fact-a": {}, "fact-b": {}}
    proposals = [
        {"id": "new-1", "antecedents": ["fact-a", "fact-b"], "unless": [],
         "text": "ok", "kind": "derive", "label": "test"},
        {"id": "new-2", "antecedents": ["fact-a", "nonexistent"], "unless": [],
         "text": "bad", "kind": "derive", "label": "test"},
    ]
    valid, skipped = validate_proposals(proposals, nodes)
    assert len(valid) == 1
    assert valid[0]["id"] == "new-1"
    assert len(skipped) == 1
    assert "nonexistent" in skipped[0][1]


def test_validate_proposals_already_exists():
    nodes = {"fact-a": {}, "fact-b": {}, "existing": {}}
    proposals = [
        {"id": "existing", "antecedents": ["fact-a", "fact-b"], "unless": [],
         "text": "dup", "kind": "derive", "label": "test"},
    ]
    valid, skipped = validate_proposals(proposals, nodes)
    assert len(valid) == 0
    assert "already exists" in skipped[0][1]


def test_apply_proposals(simple_network):
    proposals = [
        {"id": "new-derived", "text": "New conclusion from a and c",
         "antecedents": ["fact-a", "fact-c"], "unless": [],
         "kind": "derive", "label": "test apply"},
    ]
    results = apply_proposals(proposals, db_path=simple_network)
    assert len(results) == 1
    p, result = results[0]
    assert isinstance(result, dict)
    assert result["truth_value"] == "IN"

    # Verify it was actually added
    node = api.show_node("new-derived", db_path=simple_network)
    assert node["truth_value"] == "IN"
    assert "fact-a" in node["justifications"][0]["antecedents"]


def test_apply_proposals_with_gate(simple_network):
    proposals = [
        {"id": "gated-belief", "text": "A is good unless C is true",
         "antecedents": ["fact-a"], "unless": ["fact-c"],
         "kind": "gate", "label": "test gate"},
    ]
    results = apply_proposals(proposals, db_path=simple_network)
    p, result = results[0]
    # fact-c is IN, so this gated belief should be OUT
    assert result["truth_value"] == "OUT"

    # Retract fact-c — gated belief should come back IN
    api.retract_node("fact-c", db_path=simple_network)
    node = api.show_node("gated-belief", db_path=simple_network)
    assert node["truth_value"] == "IN"


# --- Topic filter tests ---

def test_filter_by_topic():
    nodes = {
        "auth-uses-jwt": {"text": "Auth system uses JWT tokens"},
        "routing-table": {"text": "The routing table is updated"},
        "auth-session": {"text": "Session management for auth"},
        "database-schema": {"text": "The database schema has 5 tables"},
    }
    filtered = _filter_by_topic(nodes, "auth")
    assert "auth-uses-jwt" in filtered
    assert "auth-session" in filtered
    assert "routing-table" not in filtered
    assert "database-schema" not in filtered


def test_filter_by_topic_matches_id_and_text():
    nodes = {
        "firewall-rules": {"text": "Stateless firewall at the perimeter"},
        "network-config": {"text": "Network uses firewall for isolation"},
        "storage-volume": {"text": "Ceph-backed storage volume"},
    }
    filtered = _filter_by_topic(nodes, "firewall")
    assert "firewall-rules" in filtered
    assert "network-config" in filtered  # matches in text
    assert "storage-volume" not in filtered


def test_filter_by_topic_multiple_keywords():
    nodes = {
        "auth-jwt": {"text": "JWT authentication"},
        "tls-config": {"text": "TLS certificate setup"},
        "database-backup": {"text": "Daily database backup"},
    }
    # Any keyword matches (OR semantics)
    filtered = _filter_by_topic(nodes, "auth tls")
    assert "auth-jwt" in filtered
    assert "tls-config" in filtered
    assert "database-backup" not in filtered


def test_build_prompt_with_topic(agent_network):
    data = api.export_network(db_path=agent_network)
    prompt, stats = build_prompt(data["nodes"], topic="auth")

    assert stats.get("topic") == "auth"
    # Only auth-related beliefs should appear
    assert "knows-auth" in prompt
    # Non-matching beliefs should be filtered out
    assert "knows-gateway" not in prompt


# --- Budget tests ---

def test_build_prompt_with_budget(simple_network):
    data = api.export_network(db_path=simple_network)
    prompt_small, stats_small = build_prompt(data["nodes"], budget=2)
    prompt_large, stats_large = build_prompt(data["nodes"], budget=100)

    # Smaller budget should produce shorter prompt
    assert len(prompt_small) < len(prompt_large)
    assert stats_small["budget"] == 2
    assert stats_large["budget"] == 100


# --- Sampling tests ---

def test_sample_beliefs_under_budget():
    ids = ["a", "b", "c"]
    result = _sample_beliefs(ids, budget=10)
    assert result == ids  # all returned when under budget


def test_sample_beliefs_over_budget():
    ids = [f"belief-{i}" for i in range(100)]
    result = _sample_beliefs(ids, budget=10)
    assert len(result) == 10
    assert all(b in ids for b in result)


def test_sample_beliefs_reproducible():
    import random
    ids = [f"belief-{i}" for i in range(100)]
    r1 = _sample_beliefs(ids, budget=10, rng=random.Random(42))
    r2 = _sample_beliefs(ids, budget=10, rng=random.Random(42))
    assert r1 == r2


def test_build_prompt_with_sample(agent_network):
    data = api.export_network(db_path=agent_network)
    prompt, stats = build_prompt(data["nodes"], sample=True, seed=42)

    assert stats["sample"] is True
    # Should still produce a valid prompt
    assert "Agent:" in prompt


# --- Accept (write + re-parse round-trip) tests ---

def test_parse_proposals_old_format():
    """Parse the v0.9 format with backtick IDs and bold field names."""
    response = """# Proposed Derivations

Review each proposal below. To accept, run:

---

### DERIVE: `combined-auth-gateway`

Auth tokens flow through the gateway with validation at each layer

- **Antecedents**: `agent-a:knows-auth`, `agent-b:knows-gateway`
- **Label**: cross-agent authentication flow

### GATE (outlist): `feature-ready`

Feature X is production-ready

- **Antecedents**: `fact-a`, `fact-b`
- **Unless**: `fact-c`
- **Label**: gated on bug resolution
"""
    proposals = parse_proposals(response)
    assert len(proposals) == 2

    p = proposals[0]
    assert p["kind"] == "derive"
    assert p["id"] == "combined-auth-gateway"
    assert p["antecedents"] == ["agent-a:knows-auth", "agent-b:knows-gateway"]
    assert p["label"] == "cross-agent authentication flow"

    p2 = proposals[1]
    assert p2["kind"] == "gate"
    assert p2["id"] == "feature-ready"
    assert p2["unless"] == ["fact-c"]


def test_write_proposals_file_roundtrip(tmp_path):
    """Proposals file can be parsed back by parse_proposals."""
    proposals = [
        {"id": "derived-1", "text": "First conclusion", "kind": "derive",
         "antecedents": ["fact-a", "fact-b"], "unless": [], "label": "test"},
        {"id": "gated-1", "text": "Gated conclusion", "kind": "gate",
         "antecedents": ["fact-a"], "unless": ["fact-c"], "label": "test gate"},
    ]
    out = tmp_path / "proposals.md"
    write_proposals_file(proposals, out)

    text = out.read_text()
    parsed = parse_proposals(text)
    assert len(parsed) == 2
    assert parsed[0]["id"] == "derived-1"
    assert parsed[0]["antecedents"] == ["fact-a", "fact-b"]
    assert parsed[1]["id"] == "gated-1"
    assert parsed[1]["unless"] == ["fact-c"]


def test_accept_applies_proposals(simple_network, tmp_path):
    """Full accept flow: write proposals, parse, apply."""
    proposals = [
        {"id": "accepted-belief", "text": "Accepted from file",
         "antecedents": ["fact-a", "fact-b"], "unless": [],
         "kind": "derive", "label": "accepted"},
    ]
    out = tmp_path / "proposals.md"
    write_proposals_file(proposals, out)

    # Parse and apply (simulating what cmd_accept does)
    text = out.read_text()
    parsed = parse_proposals(text)
    data = api.export_network(db_path=simple_network)
    valid, skipped = validate_proposals(parsed, data["nodes"])
    assert len(valid) == 1

    results = apply_proposals(valid, db_path=simple_network)
    assert len(results) == 1
    _, result = results[0]
    assert result["truth_value"] == "IN"

    node = api.show_node("accepted-belief", db_path=simple_network)
    assert node["truth_value"] == "IN"


# --- Duplicate detection tests ---

def test_tokenize_id():
    assert _tokenize_id("gl108-response-validation-disabled") == {
        "gl108", "response", "validation", "disabled",
    }


def test_tokenize_id_with_namespace():
    assert _tokenize_id("agent-a:gl108-disabled") == {
        "agent", "a", "gl108", "disabled",
    }


def test_jaccard_identical():
    assert _jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint():
    assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial():
    assert _jaccard({"a", "b", "c"}, {"a", "b", "d"}) == pytest.approx(0.5)


def test_jaccard_empty():
    assert _jaccard(set(), {"a"}) == 0.0


def test_find_similar_out_catches_variant_ids():
    nodes = {
        "gl108-safety-validation-disabled": {
            "truth_value": "OUT", "text": "GL-108 safety validation is disabled",
        },
        "fact-a": {"truth_value": "IN", "text": "Alpha"},
    }
    matches = find_similar_out("gl108-response-validation-disabled", nodes)
    assert len(matches) == 1
    assert matches[0][0] == "gl108-safety-validation-disabled"
    assert matches[0][1] >= 0.5


def test_find_similar_out_ignores_in_beliefs():
    nodes = {
        "gl108-safety-validation-disabled": {
            "truth_value": "IN", "text": "GL-108 safety validation is disabled",
        },
    }
    matches = find_similar_out("gl108-response-validation-disabled", nodes)
    assert matches == []


def test_find_similar_out_no_match():
    nodes = {
        "unrelated-network-config": {
            "truth_value": "OUT", "text": "Network config is old",
        },
    }
    matches = find_similar_out("gl108-response-validation-disabled", nodes)
    assert matches == []


def test_validate_proposals_skips_similar_to_retracted():
    """The core bug: variant IDs of retracted beliefs should be caught."""
    nodes = {
        "fact-a": {"truth_value": "IN"},
        "fact-b": {"truth_value": "IN"},
        "gl108-safety-validation-disabled": {
            "truth_value": "OUT",
            "text": "GL-108 safety validation is disabled",
        },
    }
    proposals = [
        {"id": "gl108-response-validation-disabled",
         "antecedents": ["fact-a", "fact-b"], "unless": [],
         "text": "GL-108 response validation is disabled",
         "kind": "derive", "label": "test"},
    ]
    valid, skipped = validate_proposals(proposals, nodes)
    assert len(valid) == 0
    assert len(skipped) == 1
    assert "similar to retracted" in skipped[0][1]
    assert "gl108-safety-validation-disabled" in skipped[0][1]


def test_validate_proposals_allows_unrelated():
    """Proposals unrelated to retracted beliefs should pass through."""
    nodes = {
        "fact-a": {"truth_value": "IN"},
        "fact-b": {"truth_value": "IN"},
        "gl108-safety-validation-disabled": {
            "truth_value": "OUT",
            "text": "GL-108 safety validation is disabled",
        },
    }
    proposals = [
        {"id": "auth-token-rotation-needed",
         "antecedents": ["fact-a", "fact-b"], "unless": [],
         "text": "Auth tokens need rotation",
         "kind": "derive", "label": "test"},
    ]
    valid, skipped = validate_proposals(proposals, nodes)
    assert len(valid) == 1
    assert len(skipped) == 0


# --- Deduplicate tests ---

def test_deduplicate_finds_clusters(db):
    api.add_node("gl108-validation-disabled", "GL-108 validation disabled", db_path=db)
    api.add_node("gl108-safety-validation-disabled", "GL-108 safety validation disabled", db_path=db)
    api.add_node("gl108-response-validation-disabled", "GL-108 response validation disabled", db_path=db)
    api.add_node("unrelated-auth-config", "Auth config is fine", db_path=db)

    result = api.deduplicate(db_path=db)
    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["size"] == 3
    assert result["retracted"] == []


def test_deduplicate_no_clusters(db):
    api.add_node("auth-config", "Auth config", db_path=db)
    api.add_node("network-topology", "Network topology", db_path=db)
    api.add_node("database-schema", "Database schema", db_path=db)

    result = api.deduplicate(db_path=db)
    assert len(result["clusters"]) == 0


def test_deduplicate_auto_retracts(db):
    api.add_node("gl108-validation-disabled", "GL-108 validation disabled", db_path=db)
    api.add_node("gl108-safety-validation-disabled", "GL-108 safety validation disabled", db_path=db)
    api.add_node("gl108-response-validation-disabled", "GL-108 response validation disabled", db_path=db)

    result = api.deduplicate(auto=True, db_path=db)
    assert len(result["clusters"]) == 1
    assert len(result["retracted"]) == 2
    assert result["clusters"][0]["kept"] not in result["retracted"]

    # Verify only one is still IN
    status = api.get_status(db_path=db)
    in_nodes = [n for n in status["nodes"] if n["truth_value"] == "IN"]
    assert len(in_nodes) == 1


def test_deduplicate_rewrites_dependents(db):
    """Derived beliefs that depended on a retracted duplicate survive via rewrite."""
    api.add_node("gl108-validation-disabled", "GL-108 validation disabled", db_path=db)
    api.add_node("gl108-safety-validation-disabled", "GL-108 safety validation disabled", db_path=db)
    # Derived belief depends on one of the duplicates
    api.add_node("safety-pipeline-broken", "Safety pipeline is broken",
                 sl="gl108-validation-disabled", label="derived", db_path=db)

    result = api.deduplicate(auto=True, db_path=db)
    kept = result["clusters"][0]["kept"]

    # The derived belief should still be IN
    node = api.show_node("safety-pipeline-broken", db_path=db)
    assert node["truth_value"] == "IN"
    # Its justification should now point at the kept belief
    assert kept in node["justifications"][0]["antecedents"]


def test_deduplicate_rewrites_outlist(db):
    """Outlist references to retracted duplicates are rewritten."""
    api.add_node("gl108-validation-disabled", "GL-108 validation disabled", db_path=db)
    api.add_node("gl108-safety-validation-disabled", "GL-108 safety validation disabled", db_path=db)
    # Gated belief: IN unless the duplicate is IN
    api.add_node("safe-to-deploy", "Safe to deploy",
                 unless="gl108-validation-disabled", label="gated", db_path=db)

    result = api.deduplicate(auto=True, db_path=db)
    kept = result["clusters"][0]["kept"]

    # The gated belief's outlist should now reference the kept belief
    node = api.show_node("safe-to-deploy", db_path=db)
    assert kept in node["justifications"][0]["outlist"]
