"""Tests for derive: reasoning chain derivation."""

import pytest

from reasons_lib import api
from reasons_lib.derive import (
    build_prompt,
    parse_proposals,
    validate_proposals,
    apply_proposals,
    _detect_agents,
    _filter_by_topic,
    _sample_beliefs,
    _get_depth,
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
