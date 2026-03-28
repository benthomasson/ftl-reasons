"""Tests for import-agent: multi-agent belief tracking."""

import os
import tempfile

import pytest

from reasons_lib import api


SAMPLE_BELIEFS = """\
## Beliefs

### alpha-fact [IN] OBSERVATION
Alpha is the first letter of the Greek alphabet
- Source: alphabet.md
- Date: 2026-03-28

### beta-depends-alpha [IN] DERIVED
Beta follows alpha in the alphabet
- Source: alphabet.md
- Date: 2026-03-28
- Depends on: alpha-fact

### gamma-stale [STALE] OBSERVATION
Gamma is the fourth letter
- Source: old.md
- Stale reason: gamma is actually third
"""

SAMPLE_NOGOODS = """\
### nogood-001: gamma-stale contradicts ordering
- Discovered: 2026-03-28
- Affects: alpha-fact, gamma-stale
"""


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "reasons.db")
    api.init_db(db_path=db_path)
    return db_path


@pytest.fixture
def beliefs_file(tmp_path):
    p = tmp_path / "beliefs.md"
    p.write_text(SAMPLE_BELIEFS)
    nogoods = tmp_path / "nogoods.md"
    nogoods.write_text(SAMPLE_NOGOODS)
    return str(p)


def test_import_agent_basic(db, beliefs_file):
    result = api.import_agent("test-agent", beliefs_file, db_path=db)

    assert result["agent"] == "test-agent"
    assert result["prefix"] == "test-agent:"
    assert result["active_node"] == "test-agent:active"
    assert result["created_premise"] is True
    assert result["claims_imported"] == 3
    assert result["claims_retracted"] == 1  # gamma-stale


def test_import_agent_creates_premise(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)

    node = api.show_node("test-agent:active", db_path=db)
    assert node["truth_value"] == "IN"
    assert node["metadata"]["agent"] == "test-agent"
    assert node["metadata"]["role"] == "agent_premise"


def test_import_agent_namespaces_beliefs(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)

    node = api.show_node("test-agent:alpha-fact", db_path=db)
    assert node["truth_value"] == "IN"
    assert node["metadata"]["agent"] == "test-agent"
    assert node["metadata"]["original_id"] == "alpha-fact"


def test_import_agent_remaps_dependencies(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)

    node = api.show_node("test-agent:beta-depends-alpha", db_path=db)
    assert node["truth_value"] == "IN"

    # Should depend on both the agent premise and the remapped alpha
    j = node["justifications"][0]
    assert "test-agent:active" in j["antecedents"]
    assert "test-agent:alpha-fact" in j["antecedents"]


def test_import_agent_retract_premise_cascades(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)

    result = api.what_if_retract("test-agent:active", db_path=db)
    # All IN beliefs (alpha-fact, beta-depends-alpha) should cascade OUT
    # gamma-stale is already OUT so not affected
    assert result["total_affected"] == 2


def test_import_agent_retract_premise_actually_cascades(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)

    result = api.retract_node("test-agent:active", db_path=db)
    # active + alpha-fact + beta-depends-alpha
    assert len(result["changed"]) == 3

    # Verify they're all OUT now
    alpha = api.show_node("test-agent:alpha-fact", db_path=db)
    assert alpha["truth_value"] == "OUT"
    beta = api.show_node("test-agent:beta-depends-alpha", db_path=db)
    assert beta["truth_value"] == "OUT"


def test_import_agent_restore_premise_cascades(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)
    api.retract_node("test-agent:active", db_path=db)

    # Re-assert the premise — beliefs should come back
    result = api.assert_node("test-agent:active", db_path=db)
    assert "test-agent:alpha-fact" in result["changed"]
    assert "test-agent:beta-depends-alpha" in result["changed"]


def test_import_agent_skip_duplicates(db, beliefs_file):
    api.import_agent("test-agent", beliefs_file, db_path=db)
    result = api.import_agent("test-agent", beliefs_file, db_path=db)

    assert result["claims_imported"] == 0
    assert result["claims_skipped"] == 3
    assert result["created_premise"] is False


def test_import_agent_only_in(db, beliefs_file):
    result = api.import_agent("test-agent", beliefs_file, only_in=True, db_path=db)

    assert result["claims_imported"] == 2  # alpha-fact, beta-depends-alpha
    assert result["claims_retracted"] == 0  # gamma-stale excluded

    with pytest.raises(KeyError):
        api.show_node("test-agent:gamma-stale", db_path=db)


def test_import_multiple_agents(db, beliefs_file):
    api.import_agent("agent-a", beliefs_file, db_path=db)
    api.import_agent("agent-b", beliefs_file, db_path=db)

    status = api.get_status(db_path=db)
    # 2 premises + 2 * 3 beliefs = 8 total
    assert status["total"] == 8

    # Both agents have their own alpha-fact
    a = api.show_node("agent-a:alpha-fact", db_path=db)
    b = api.show_node("agent-b:alpha-fact", db_path=db)
    assert a["truth_value"] == "IN"
    assert b["truth_value"] == "IN"

    # Retracting agent-a doesn't affect agent-b
    api.retract_node("agent-a:active", db_path=db)
    a = api.show_node("agent-a:alpha-fact", db_path=db)
    b = api.show_node("agent-b:alpha-fact", db_path=db)
    assert a["truth_value"] == "OUT"
    assert b["truth_value"] == "IN"


def test_import_agent_nogoods(db, beliefs_file):
    result = api.import_agent("test-agent", beliefs_file, db_path=db)
    assert result["nogoods_imported"] == 1
