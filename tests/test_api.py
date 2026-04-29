"""Tests for the functional Python API."""

import pytest

from reasons_lib import api


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "test_reasons.db")
    api.init_db(db_path=p)
    return p


class TestInitDb:

    def test_creates_db(self, tmp_path):
        p = str(tmp_path / "new.db")
        result = api.init_db(db_path=p)
        assert result["created"] is True

    def test_refuses_existing(self, db_path):
        with pytest.raises(FileExistsError):
            api.init_db(db_path=db_path)

    def test_force_overwrites(self, db_path):
        result = api.init_db(db_path=db_path, force=True)
        assert result["created"] is True


class TestAddNode:

    def test_add_premise(self, db_path):
        result = api.add_node("a", "Premise A", db_path=db_path)
        assert result["node_id"] == "a"
        assert result["truth_value"] == "IN"
        assert result["type"] == "premise"

    def test_add_with_sl(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.add_node("b", "Derived B", sl="a", db_path=db_path)
        assert result["truth_value"] == "IN"
        assert result["type"] == "SL"

    def test_add_duplicate_raises(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        with pytest.raises(ValueError):
            api.add_node("a", "Duplicate", db_path=db_path)


class TestRetractNode:

    def test_retract(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.retract_node("a", db_path=db_path)
        assert "a" in result["changed"]

    def test_retract_cascades(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Derived B", sl="a", db_path=db_path)
        result = api.retract_node("a", db_path=db_path)
        assert set(result["changed"]) == {"a", "b"}

    def test_retract_missing_raises(self, db_path):
        with pytest.raises(KeyError):
            api.retract_node("missing", db_path=db_path)

    def test_retract_already_out(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.retract_node("a", db_path=db_path)
        result = api.retract_node("a", db_path=db_path)
        assert result["changed"] == []


class TestAssertNode:

    def test_assert_restores(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Derived B", sl="a", db_path=db_path)
        api.retract_node("a", db_path=db_path)
        result = api.assert_node("a", db_path=db_path)
        assert set(result["changed"]) == {"a", "b"}

    def test_assert_already_in(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.assert_node("a", db_path=db_path)
        assert result["changed"] == []


class TestGetStatus:

    def test_empty(self, db_path):
        result = api.get_status(db_path=db_path)
        assert result["nodes"] == []
        assert result["total"] == 0

    def test_with_nodes(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Premise B", db_path=db_path)
        result = api.get_status(db_path=db_path)
        assert result["total"] == 2
        assert result["in_count"] == 2
        ids = [n["id"] for n in result["nodes"]]
        assert "a" in ids and "b" in ids


class TestShowNode:

    def test_show(self, db_path):
        api.add_node("a", "Premise A", source="repo:file.py", db_path=db_path)
        result = api.show_node("a", db_path=db_path)
        assert result["id"] == "a"
        assert result["text"] == "Premise A"
        assert result["source"] == "repo:file.py"
        assert result["justifications"] == []
        assert result["dependents"] == []

    def test_show_missing_raises(self, db_path):
        with pytest.raises(KeyError):
            api.show_node("missing", db_path=db_path)


class TestExplainNode:

    def test_explain_premise(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.explain_node("a", db_path=db_path)
        assert result["steps"][0]["reason"] == "premise"

    def test_explain_chain(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Derived B", sl="a", db_path=db_path)
        result = api.explain_node("b", db_path=db_path)
        nodes_in_trace = [s["node"] for s in result["steps"]]
        assert "b" in nodes_in_trace
        assert "a" in nodes_in_trace


class TestAddNogood:

    def test_nogood(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Premise B", db_path=db_path)
        result = api.add_nogood(["a", "b"], db_path=db_path)
        assert result["nogood_id"] == "nogood-001"
        assert result["nodes"] == ["a", "b"]
        assert len(result["changed"]) > 0


class TestGetBeliefSet:

    def test_belief_set(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Premise B", db_path=db_path)
        api.retract_node("b", db_path=db_path)
        result = api.get_belief_set(db_path=db_path)
        assert result == ["a"]


class TestGetLog:

    def test_log(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.get_log(db_path=db_path)
        assert len(result["entries"]) > 0

    def test_log_last(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Premise B", db_path=db_path)
        result = api.get_log(last=1, db_path=db_path)
        assert len(result["entries"]) == 1


class TestExportNetwork:

    def test_export(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.export_network(db_path=db_path)
        assert "a" in result["nodes"]
        assert result["nodes"]["a"]["truth_value"] == "IN"


class TestEndToEnd:
    """Full workflow through the API — same scenarios as test_network.py."""

    def test_retract_and_restore_chain(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Derived B", sl="a", db_path=db_path)
        api.add_node("c", "Derived C", sl="b", db_path=db_path)

        # All IN
        status = api.get_status(db_path=db_path)
        assert status["in_count"] == 3

        # Retract A → cascade
        result = api.retract_node("a", db_path=db_path)
        assert set(result["changed"]) == {"a", "b", "c"}

        status = api.get_status(db_path=db_path)
        assert status["in_count"] == 0

        # Assert A → restore
        result = api.assert_node("a", db_path=db_path)
        assert set(result["changed"]) == {"a", "b", "c"}

        status = api.get_status(db_path=db_path)
        assert status["in_count"] == 3


class TestListNodesDepth:

    def test_list_min_depth(self, db_path):
        api.add_node("p1", "premise", db_path=db_path)
        api.add_node("d1", "derived", sl="p1", label="t", db_path=db_path)

        result = api.list_nodes(min_depth=1, db_path=db_path)
        ids = [n["id"] for n in result["nodes"]]
        assert "d1" in ids
        assert "p1" not in ids

    def test_list_max_depth(self, db_path):
        api.add_node("p1", "premise", db_path=db_path)
        api.add_node("d1", "derived", sl="p1", label="t", db_path=db_path)

        result = api.list_nodes(max_depth=0, db_path=db_path)
        ids = [n["id"] for n in result["nodes"]]
        assert "p1" in ids
        assert "d1" not in ids

    def test_list_depth_range(self, db_path):
        api.add_node("p", "premise", db_path=db_path)
        api.add_node("mid", "mid", sl="p", label="t", db_path=db_path)
        api.add_node("top", "top", sl="mid", label="t", db_path=db_path)

        result = api.list_nodes(min_depth=1, max_depth=1, db_path=db_path)
        ids = [n["id"] for n in result["nodes"]]
        assert ids == ["mid"]


class TestListGated:

    def test_no_gates(self, db_path):
        api.add_node("a", "Alpha", db_path=db_path)
        result = api.list_gated(db_path=db_path)
        assert result["blockers"] == {}
        assert result["gated_count"] == 0

    def test_active_gate(self, db_path):
        api.add_node("premise", "Supporting premise", db_path=db_path)
        api.add_node("blocker", "Defect premise", db_path=db_path)
        api.add_node("gated", "Conclusion unless blocker", sl="premise", unless="blocker", db_path=db_path)
        result = api.list_gated(db_path=db_path)
        assert result["blocker_count"] == 1
        assert result["gated_count"] == 1
        assert "blocker" in result["blockers"]
        assert result["blockers"]["blocker"]["gated"][0]["id"] == "gated"

    def test_satisfied_gate(self, db_path):
        api.add_node("premise", "Supporting premise", db_path=db_path)
        api.add_node("blocker", "Defect premise", db_path=db_path)
        api.add_node("gated", "Conclusion unless blocker", sl="premise", unless="blocker", db_path=db_path)
        api.retract_node("blocker", db_path=db_path)
        result = api.list_gated(db_path=db_path)
        assert result["blockers"] == {}

    def test_multiple_gated_per_blocker(self, db_path):
        api.add_node("premise", "Supporting premise", db_path=db_path)
        api.add_node("blocker", "Defect", db_path=db_path)
        api.add_node("g1", "Gated 1", sl="premise", unless="blocker", db_path=db_path)
        api.add_node("g2", "Gated 2", sl="premise", unless="blocker", db_path=db_path)
        result = api.list_gated(db_path=db_path)
        assert result["blocker_count"] == 1
        assert result["gated_count"] == 2
        gated_ids = [g["id"] for g in result["blockers"]["blocker"]["gated"]]
        assert "g1" in gated_ids
        assert "g2" in gated_ids

    def test_superseded_excluded(self, db_path):
        api.add_node("premise", "Supporting premise", db_path=db_path)
        api.add_node("blocker", "Defect", db_path=db_path)
        api.add_node("old", "Old conclusion", sl="premise", unless="blocker", db_path=db_path)
        api.add_node("new", "New conclusion", sl="premise", db_path=db_path)
        api.supersede("old", "new", db_path=db_path)
        result = api.list_gated(db_path=db_path)
        assert result["gated_count"] == 0

    def test_blocker_text_included(self, db_path):
        api.add_node("premise", "Supporting premise", db_path=db_path)
        api.add_node("bug-123", "File X has a null check missing", db_path=db_path)
        api.add_node("gated", "X is safe", sl="premise", unless="bug-123", db_path=db_path)
        result = api.list_gated(db_path=db_path)
        assert result["blockers"]["bug-123"]["text"] == "File X has a null check missing"
