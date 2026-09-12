"""Tests for the MCP server tool functions."""

import json
import os
from unittest.mock import patch

import pytest

pytest.importorskip("mcp")

from reasons import api
from reasons import mcp_server


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    api.init_db(db_path=db_path)
    api.add_node("premise-a", "A is true", db_path=db_path)
    api.add_node("premise-b", "B is true", db_path=db_path)
    api.add_node("derived-c", "C follows from A and B",
                 sl="premise-a,premise-b", db_path=db_path)
    mcp_server._db = db_path
    yield db_path
    mcp_server._db = None


class TestFindDb:

    def test_env_var_takes_precedence(self, tmp_path):
        custom = str(tmp_path / "custom.db")
        with patch.dict(os.environ, {"REASONS_DB": custom}):
            assert mcp_server._find_db() == custom

    def test_walks_up_from_cwd(self, tmp_path):
        db_path = tmp_path / "reasons.db"
        db_path.touch()
        subdir = tmp_path / "sub" / "deep"
        subdir.mkdir(parents=True)
        with patch("os.getcwd", return_value=str(subdir)), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("REASONS_DB", None)
            result = mcp_server._find_db()
            assert result == str(db_path)

    def test_falls_back_to_default(self, tmp_path):
        with patch("os.getcwd", return_value=str(tmp_path)), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("REASONS_DB", None)
            result = mcp_server._find_db()
            assert result == api.DEFAULT_DB


class TestGetDb:

    def test_lazy_discovery(self, tmp_path):
        db_path = tmp_path / "reasons.db"
        db_path.touch()
        mcp_server._db = None
        with patch("os.getcwd", return_value=str(tmp_path)), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("REASONS_DB", None)
            result = mcp_server._get_db()
            assert result == str(db_path)
        mcp_server._db = None

    def test_uses_cached_value(self):
        mcp_server._db = "/some/path.db"
        assert mcp_server._get_db() == "/some/path.db"
        mcp_server._db = None


class TestSearchTool:

    def test_search_returns_results(self, db):
        result = mcp_server.search("true")
        assert "premise-a" in result or "premise-b" in result

    def test_search_json_format(self, db):
        result = mcp_server.search("true", output_format="json")
        data = json.loads(result)
        assert isinstance(data, (list, dict))


class TestShowTool:

    def test_show_existing(self, db):
        result = json.loads(mcp_server.show("premise-a"))
        assert result["text"] == "A is true"
        assert result["truth_value"] == "IN"

    def test_show_missing_returns_error(self, db):
        result = json.loads(mcp_server.show("nonexistent"))
        assert "error" in result


class TestExplainTool:

    def test_explain_existing(self, db):
        result = json.loads(mcp_server.explain("derived-c"))
        assert "steps" in result

    def test_explain_missing_returns_error(self, db):
        result = json.loads(mcp_server.explain("nonexistent"))
        assert "error" in result


class TestListBeliefsTool:

    def test_list_all(self, db):
        result = json.loads(mcp_server.list_beliefs())
        assert len(result["nodes"]) == 3

    def test_list_premises_only(self, db):
        result = json.loads(mcp_server.list_beliefs(premises_only=True))
        ids = [n["id"] for n in result["nodes"]]
        assert "derived-c" not in ids

    def test_list_by_status(self, db):
        api.retract_node("premise-a", db_path=db)
        result = json.loads(mcp_server.list_beliefs(status="OUT"))
        ids = [n["id"] for n in result["nodes"]]
        assert "premise-a" in ids

    def test_empty_status_means_all(self, db):
        result = json.loads(mcp_server.list_beliefs(status=""))
        assert len(result["nodes"]) == 3


class TestAddTool:

    def test_add_premise(self, db):
        result = json.loads(mcp_server.add("new-premise", "Something new"))
        assert result["node_id"] == "new-premise"
        node = api.show_node("new-premise", db_path=db)
        assert node["text"] == "Something new"

    def test_add_derived(self, db):
        result = json.loads(mcp_server.add("new-derived", "Derived thing",
                                           sl="premise-a"))
        assert result["node_id"] == "new-derived"

    def test_add_with_missing_sl_creates_out(self, db):
        result = json.loads(mcp_server.add("bad-derived", "Bad",
                                           sl="nonexistent-node"))
        assert result["node_id"] == "bad-derived"
        assert result["truth_value"] == "OUT"


class TestRetractTool:

    def test_retract(self, db):
        result = json.loads(mcp_server.retract("premise-a", reason="testing"))
        assert "premise-a" in result["changed"]
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "OUT"

    def test_retract_missing_returns_error(self, db):
        result = json.loads(mcp_server.retract("nonexistent"))
        assert "error" in result


class TestAssertBeliefTool:

    def test_assert_retracted(self, db):
        api.retract_node("premise-a", db_path=db)
        result = json.loads(mcp_server.assert_belief("premise-a"))
        assert "premise-a" in result["went_in"]
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "IN"

    def test_assert_missing_returns_error(self, db):
        result = json.loads(mcp_server.assert_belief("nonexistent"))
        assert "error" in result


class TestWhatIfTool:

    def test_what_if_retract(self, db):
        result = json.loads(mcp_server.what_if("premise-a", action="retract"))
        assert result["node_id"] == "premise-a"
        assert "retracted" in result
        assert "total_affected" in result

    def test_what_if_assert(self, db):
        api.retract_node("premise-a", db_path=db)
        result = json.loads(mcp_server.what_if("premise-a", action="assert"))
        assert result["node_id"] == "premise-a"
        assert "restored" in result

    def test_what_if_missing_returns_error(self, db):
        result = json.loads(mcp_server.what_if("nonexistent"))
        assert "error" in result


class TestAddJustificationTool:

    def test_add_justification(self, db):
        result = json.loads(mcp_server.add_justification(
            "derived-c", sl="premise-a", label="extra"))
        assert result["node_id"] == "derived-c"

    def test_add_justification_missing_sl(self, db):
        result = json.loads(mcp_server.add_justification(
            "derived-c", sl="nonexistent"))
        assert result["node_id"] == "derived-c"


class TestNogoodTool:

    def test_nogood(self, db):
        result = json.loads(mcp_server.nogood(["premise-a", "premise-b"]))
        assert "nogood_id" in result

    def test_nogood_missing_returns_error(self, db):
        result = json.loads(mcp_server.nogood(["nonexistent-x", "nonexistent-y"]))
        assert "error" in result


class TestTraceTool:

    def test_trace_derived(self, db):
        result = json.loads(mcp_server.trace("derived-c"))
        assert result["node_id"] == "derived-c"
        assert "premises" in result

    def test_trace_missing_returns_error(self, db):
        result = json.loads(mcp_server.trace("nonexistent"))
        assert "error" in result


class TestCompactTool:

    def test_compact(self, db):
        result = mcp_server.compact(budget=500)
        assert isinstance(result, str)
        assert len(result) > 0


class TestStatusTool:

    def test_status(self, db):
        result = json.loads(mcp_server.status())
        assert "nodes" in result
        assert "in_count" in result
        assert "total" in result


class TestListGatedTool:

    def test_list_gated(self, db):
        result = json.loads(mcp_server.list_gated())
        assert "gated_count" in result


class TestExportMarkdownTool:

    def test_export_markdown(self, db):
        result = mcp_server.export_markdown()
        assert isinstance(result, str)
        assert "premise-a" in result or "A is true" in result


class TestTopicsTool:

    def test_topics(self, db):
        result = json.loads(mcp_server.topics(limit=10))
        assert "topics" in result


class TestWhatIfSupersede:

    def test_what_if_supersede(self, db):
        result = json.loads(mcp_server.what_if(
            "premise-a", action="supersede", text="A is updated"))
        assert result["old_id"] == "premise-a"
        assert "new_id" in result
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "IN"

    def test_what_if_supersede_missing_text(self, db):
        result = json.loads(mcp_server.what_if(
            "premise-a", action="supersede"))
        assert "error" in result

    def test_what_if_supersede_not_found(self, db):
        result = json.loads(mcp_server.what_if(
            "nonexistent", action="supersede", text="something"))
        assert "error" in result


class TestProposeRetractTool:

    def test_propose_retract(self, db):
        result = json.loads(mcp_server.propose_retract(
            "premise-a", reason="outdated", proposer="test-bee"))
        assert result["proposal_id"].startswith("prop-premise-a-retract-")
        assert result["action"] == "retract"
        assert result["status"] == "pending"
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "IN"

    def test_propose_retract_not_found(self, db):
        result = json.loads(mcp_server.propose_retract("nonexistent"))
        assert "error" in result

    def test_propose_retract_already_out(self, db):
        api.retract_node("premise-a", db_path=db)
        result = json.loads(mcp_server.propose_retract("premise-a"))
        assert "error" in result

    def test_propose_retract_with_impact(self, db):
        result = json.loads(mcp_server.propose_retract("premise-a"))
        assert "impact" in result
        assert result["impact"]["total_affected"] >= 1


class TestProposeSupersedeTool:

    def test_propose_supersede(self, db):
        result = json.loads(mcp_server.propose_supersede(
            "premise-a", "A is updated", proposer="test-bee"))
        assert result["proposal_id"].startswith("prop-premise-a-supersede-")
        assert result["action"] == "supersede"
        assert result["status"] == "pending"
        assert "new_id" in result

    def test_propose_supersede_custom_id(self, db):
        result = json.loads(mcp_server.propose_supersede(
            "premise-a", "A revised", new_id="premise-a-revised"))
        assert result["new_id"] == "premise-a-revised"

    def test_propose_supersede_not_found(self, db):
        result = json.loads(mcp_server.propose_supersede(
            "nonexistent", "text"))
        assert "error" in result

    def test_propose_supersede_already_out(self, db):
        api.retract_node("premise-a", db_path=db)
        result = json.loads(mcp_server.propose_supersede(
            "premise-a", "updated"))
        assert "error" in result


class TestProposeAddTool:

    def test_propose_add(self, db):
        result = json.loads(mcp_server.propose_add(
            "new-node", "New belief", proposer="test-bee"))
        assert result["proposal_id"].startswith("prop-new-node-add-")
        assert result["action"] == "add"
        assert result["status"] == "pending"
        result = json.loads(mcp_server.show("new-node"))
        assert "error" in result

    def test_propose_add_already_exists(self, db):
        result = json.loads(mcp_server.propose_add(
            "premise-a", "duplicate"))
        assert "error" in result

    def test_propose_add_with_justification(self, db):
        result = json.loads(mcp_server.propose_add(
            "new-derived", "Derived from A", sl="premise-a",
            label="test-just"))
        assert result["action"] == "add"
        assert result["status"] == "pending"


class TestListProposalsTool:

    def test_list_proposals_empty(self, db):
        result = json.loads(mcp_server.list_proposals())
        assert result["count"] == 0

    def test_list_proposals_after_propose(self, db):
        mcp_server.propose_retract("premise-a", proposer="bee-1")
        result = json.loads(mcp_server.list_proposals())
        assert result["count"] == 1
        assert result["proposals"][0]["target_id"] == "premise-a"

    def test_list_proposals_filter_by_status(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        mcp_server.reject_proposal(prop["proposal_id"], voter="reviewer")
        pending = json.loads(mcp_server.list_proposals(
            proposal_status="pending"))
        assert pending["count"] == 0
        rejected = json.loads(mcp_server.list_proposals(
            proposal_status="rejected"))
        assert rejected["count"] == 1

    def test_list_proposals_all_statuses(self, db):
        mcp_server.propose_retract("premise-a")
        result = json.loads(mcp_server.list_proposals(proposal_status=""))
        assert result["count"] == 1


class TestShowProposalTool:

    def test_show_proposal(self, db):
        prop = json.loads(mcp_server.propose_retract(
            "premise-a", reason="test-reason"))
        detail = json.loads(mcp_server.show_proposal(prop["proposal_id"]))
        assert detail["id"] == prop["proposal_id"]
        assert detail["reason"] == "test-reason"
        assert detail["action"] == "retract"
        assert "snapshot" in detail
        assert "impact" in detail

    def test_show_proposal_not_found(self, db):
        result = json.loads(mcp_server.show_proposal("nonexistent"))
        assert "error" in result


class TestAcceptProposalTool:

    def test_accept_retract(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        result = json.loads(mcp_server.accept_proposal(
            prop["proposal_id"], voter="reviewer"))
        assert result["applied"] is True
        assert result["status"] == "accepted"
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "OUT"

    def test_accept_supersede(self, db):
        prop = json.loads(mcp_server.propose_supersede(
            "premise-a", "A updated"))
        result = json.loads(mcp_server.accept_proposal(
            prop["proposal_id"], voter="reviewer"))
        assert result["applied"] is True
        old = api.show_node("premise-a", db_path=db)
        assert old["truth_value"] == "OUT"

    def test_accept_add(self, db):
        prop = json.loads(mcp_server.propose_add(
            "new-node", "Brand new belief"))
        result = json.loads(mcp_server.accept_proposal(
            prop["proposal_id"], voter="reviewer"))
        assert result["applied"] is True
        node = api.show_node("new-node", db_path=db)
        assert node["truth_value"] == "IN"
        assert node["text"] == "Brand new belief"

    def test_accept_not_found(self, db):
        result = json.loads(mcp_server.accept_proposal("nonexistent"))
        assert "error" in result

    def test_accept_already_resolved(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        mcp_server.reject_proposal(prop["proposal_id"])
        result = json.loads(mcp_server.accept_proposal(prop["proposal_id"]))
        assert "error" in result

    def test_accept_cascade(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        mcp_server.accept_proposal(prop["proposal_id"])
        derived = api.show_node("derived-c", db_path=db)
        assert derived["truth_value"] == "OUT"

    def test_accept_drift_already_out(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        api.retract_node("premise-a", db_path=db)
        result = json.loads(mcp_server.accept_proposal(prop["proposal_id"]))
        assert result["applied"] is False
        assert result["status"] == "stale"


class TestRejectProposalTool:

    def test_reject(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        result = json.loads(mcp_server.reject_proposal(
            prop["proposal_id"], voter="reviewer", reason="not convinced"))
        assert result["status"] == "rejected"
        assert result["reason"] == "not convinced"
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "IN"

    def test_reject_not_found(self, db):
        result = json.loads(mcp_server.reject_proposal("nonexistent"))
        assert "error" in result

    def test_reject_already_resolved(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        mcp_server.accept_proposal(prop["proposal_id"])
        result = json.loads(mcp_server.reject_proposal(prop["proposal_id"]))
        assert "error" in result


class TestWithdrawProposalTool:

    def test_withdraw(self, db):
        prop = json.loads(mcp_server.propose_retract(
            "premise-a", proposer="bee-1"))
        result = json.loads(mcp_server.withdraw_proposal(
            prop["proposal_id"], proposer="bee-1"))
        assert result["status"] == "withdrawn"
        node = api.show_node("premise-a", db_path=db)
        assert node["truth_value"] == "IN"

    def test_withdraw_not_found(self, db):
        result = json.loads(mcp_server.withdraw_proposal("nonexistent"))
        assert "error" in result

    def test_withdraw_already_resolved(self, db):
        prop = json.loads(mcp_server.propose_retract("premise-a"))
        mcp_server.reject_proposal(prop["proposal_id"])
        result = json.loads(mcp_server.withdraw_proposal(
            prop["proposal_id"]))
        assert "error" in result
