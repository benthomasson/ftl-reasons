"""Tests for the PostgreSQL-native storage backend."""

import json

import pytest

from tests.conftest import skip_no_pg

pytestmark = [pytest.mark.pg, skip_no_pg]


class TestAddNode:

    def test_add_premise(self, pg_api):
        result = pg_api.add_node("a", "Alpha premise")
        assert result["node_id"] == "a"
        assert result["truth_value"] == "IN"
        assert result["type"] == "premise"

    def test_add_derived_in(self, pg_api):
        pg_api.add_node("a", "Alpha premise")
        result = pg_api.add_node("b", "Beta derived", sl="a")
        assert result["truth_value"] == "IN"
        assert result["type"] == "derived"

    def test_add_derived_out(self, pg_api):
        pg_api.add_node("a", "Alpha premise")
        pg_api.retract_node("a")
        result = pg_api.add_node("b", "Beta derived", sl="a")
        assert result["truth_value"] == "OUT"

    def test_add_with_outlist(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("blocker", "Blocker node")
        result = pg_api.add_node("c", "C unless blocker", sl="a", unless="blocker")
        assert result["truth_value"] == "OUT"

    def test_add_with_outlist_out(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("blocker", "Blocker node")
        pg_api.retract_node("blocker")
        result = pg_api.add_node("c", "C unless blocker", sl="a", unless="blocker")
        assert result["truth_value"] == "IN"

    def test_add_duplicate_raises(self, pg_api):
        pg_api.add_node("a", "Alpha")
        with pytest.raises(Exception):
            pg_api.add_node("a", "Alpha again")

    def test_add_with_access_tags(self, pg_api):
        pg_api.add_node("a", "Alpha", access_tags=["billing", "aws"])
        result = pg_api.show_node("a")
        assert result["metadata"]["access_tags"] == ["aws", "billing"]

    def test_access_tag_inheritance(self, pg_api):
        pg_api.add_node("a", "Alpha", access_tags=["billing"])
        pg_api.add_node("b", "Beta", access_tags=["aws"])
        pg_api.add_node("c", "Gamma derived", sl="a,b")
        result = pg_api.show_node("c")
        assert set(result["metadata"]["access_tags"]) == {"aws", "billing"}


class TestRetractNode:

    def test_retract_premise(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.retract_node("a")
        assert "a" in result["changed"]
        assert "a" in result["went_out"]
        status = pg_api.show_node("a")
        assert status["truth_value"] == "OUT"

    def test_retract_already_out(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.retract_node("a")
        result = pg_api.retract_node("a")
        assert result["changed"] == []

    def test_retract_cascade(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma", sl="b")
        result = pg_api.retract_node("a")
        assert "a" in result["went_out"]
        assert "b" in result["went_out"]
        assert "c" in result["went_out"]

    def test_retract_with_reason(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.retract_node("a", reason="obsolete")
        result = pg_api.show_node("a")
        assert result["metadata"].get("retract_reason") == "obsolete"

    def test_retract_not_found(self, pg_api):
        with pytest.raises(KeyError):
            pg_api.retract_node("nonexistent")


class TestAssertNode:

    def test_assert_restores(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.retract_node("a")
        result = pg_api.assert_node("a")
        assert "a" in result["changed"]
        assert "a" in result["went_in"]
        status = pg_api.show_node("a")
        assert status["truth_value"] == "IN"

    def test_assert_already_in(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.assert_node("a")
        assert result["changed"] == []

    def test_assert_restores_cascade(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma", sl="b")
        pg_api.retract_node("a")
        result = pg_api.assert_node("a")
        assert "a" in result["went_in"]
        assert "b" in result["went_in"]
        assert "c" in result["went_in"]


class TestPropagation:

    def test_diamond_dependency(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma", sl="a")
        pg_api.add_node("d", "Delta", sl="b,c")
        result = pg_api.retract_node("a")
        assert set(result["went_out"]) == {"a", "b", "c", "d"}

    def test_diamond_restoration(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma", sl="a")
        pg_api.add_node("d", "Delta", sl="b,c")
        pg_api.retract_node("a")
        result = pg_api.assert_node("a")
        assert "b" in result["went_in"]
        assert "c" in result["went_in"]
        assert "d" in result["went_in"]

    def test_outlist_blocks(self, pg_api):
        pg_api.add_node("x", "X premise")
        pg_api.add_node("y", "Y blocker")
        pg_api.add_node("z", "Z unless Y", sl="x", unless="y")
        status = pg_api.show_node("z")
        assert status["truth_value"] == "OUT"

    def test_outlist_unblocks(self, pg_api):
        pg_api.add_node("x", "X premise")
        pg_api.add_node("y", "Y blocker")
        pg_api.add_node("z", "Z unless Y", sl="x", unless="y")
        pg_api.retract_node("y")
        status = pg_api.show_node("z")
        assert status["truth_value"] == "IN"

    def test_outlist_reblocks(self, pg_api):
        pg_api.add_node("x", "X premise")
        pg_api.add_node("y", "Y blocker")
        pg_api.add_node("z", "Z unless Y", sl="x", unless="y")
        pg_api.retract_node("y")
        pg_api.assert_node("y")
        status = pg_api.show_node("z")
        assert status["truth_value"] == "OUT"

    def test_multiple_justifications(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.add_node("c", "Gamma", sl="a")
        pg_api.add_justification("c", sl="b")
        pg_api.retract_node("a")
        status = pg_api.show_node("c")
        assert status["truth_value"] == "IN"

    def test_retracted_pin_skipped(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.retract_node("b")
        pg_api.retract_node("a")
        pg_api.assert_node("a")
        status = pg_api.show_node("b")
        assert status["truth_value"] == "OUT"


class TestGetStatus:

    def test_empty(self, pg_api):
        result = pg_api.get_status()
        assert result["nodes"] == []
        assert result["total"] == 0

    def test_with_nodes(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.retract_node("b")
        result = pg_api.get_status()
        assert result["total"] == 2
        assert result["in_count"] == 1

    def test_visible_to_filter(self, pg_api):
        pg_api.add_node("a", "Alpha", access_tags=["secret"])
        pg_api.add_node("b", "Beta")
        result = pg_api.get_status(visible_to=["public"])
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "b"


class TestShowNode:

    def test_show_premise(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.show_node("a")
        assert result["id"] == "a"
        assert result["truth_value"] == "IN"
        assert result["justifications"] == []

    def test_show_derived(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a", label="test")
        result = pg_api.show_node("b")
        assert len(result["justifications"]) == 1
        assert result["justifications"][0]["antecedents"] == ["a"]
        assert result["justifications"][0]["label"] == "test"

    def test_show_dependents(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        result = pg_api.show_node("a")
        assert "b" in result["dependents"]

    def test_show_not_found(self, pg_api):
        with pytest.raises(KeyError):
            pg_api.show_node("nonexistent")

    def test_show_access_denied(self, pg_api):
        pg_api.add_node("a", "Alpha", access_tags=["secret"])
        with pytest.raises(PermissionError):
            pg_api.show_node("a", visible_to=["public"])


class TestSearch:

    def test_search_by_text(self, pg_api):
        pg_api.add_node("a", "Propagation uses breadth-first search")
        pg_api.add_node("b", "Retraction cascades through dependents")
        result = pg_api.search("propagation")
        assert "propagation" in result.lower() or "a" in result

    def test_search_by_id(self, pg_api):
        pg_api.add_node("prop-bfs", "Propagation uses BFS")
        result = pg_api.search("prop-bfs")
        assert "prop-bfs" in result

    def test_search_no_results(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.search("zzzznonexistent")
        assert "No results" in result

    def test_search_compact_format(self, pg_api):
        pg_api.add_node("a", "Alpha belief")
        result = pg_api.search("alpha", format="compact")
        assert "[IN] a" in result

    def test_search_json_format(self, pg_api):
        pg_api.add_node("a", "Alpha belief")
        result = pg_api.search("alpha", format="json")
        data = json.loads(result)
        assert any(d["id"] == "a" for d in data)

    def test_search_with_neighbors(self, pg_api):
        pg_api.add_node("a", "Alpha premise")
        pg_api.add_node("b", "Beta depends on alpha", sl="a")
        result = pg_api.search("beta", format="compact")
        assert "b" in result
        assert "a" in result


class TestListNodes:

    def test_list_all(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        result = pg_api.list_nodes()
        assert result["count"] == 2

    def test_list_by_status(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.retract_node("b")
        result = pg_api.list_nodes(status="IN")
        assert result["count"] == 1
        assert result["nodes"][0]["id"] == "a"

    def test_list_premises_only(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        result = pg_api.list_nodes(premises_only=True)
        assert result["count"] == 1
        assert result["nodes"][0]["id"] == "a"

    def test_list_has_dependents(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma")
        result = pg_api.list_nodes(has_dependents=True)
        assert result["count"] == 1
        assert result["nodes"][0]["id"] == "a"

    def test_list_by_namespace(self, pg_api):
        pg_api.add_node("ns1:a", "Alpha")
        pg_api.add_node("ns2:b", "Beta")
        result = pg_api.list_nodes(namespace="ns1")
        assert result["count"] == 1
        assert result["nodes"][0]["id"] == "ns1:a"


class TestGetLog:

    def test_log_after_add(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.get_log()
        assert len(result["entries"]) >= 1
        assert result["entries"][-1]["action"] == "add"

    def test_log_last(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.retract_node("a")
        result = pg_api.get_log(last=1)
        assert len(result["entries"]) == 1


class TestAddJustification:

    def test_add_justification_changes_truth(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.retract_node("b")
        result = pg_api.add_justification("b", sl="a")
        assert result["old_truth_value"] == "OUT"
        assert result["new_truth_value"] == "IN"

    def test_add_justification_not_found(self, pg_api):
        with pytest.raises(KeyError):
            pg_api.add_justification("nonexistent", sl="a")


class TestNogood:

    def test_add_nogood_active(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        result = pg_api.add_nogood(["a", "b"])
        assert result["backtracked_to"] is not None
        # One of a or b should be retracted
        a = pg_api.show_node("a")
        b = pg_api.show_node("b")
        assert a["truth_value"] == "OUT" or b["truth_value"] == "OUT"

    def test_add_nogood_inactive(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.retract_node("b")
        result = pg_api.add_nogood(["a", "b"])
        assert result["backtracked_to"] is None
        assert result["changed"] == []

    def test_add_nogood_not_found(self, pg_api):
        with pytest.raises(KeyError):
            pg_api.add_nogood(["nonexistent"])


class TestFindCulprits:

    def test_find_culprits(self, pg_api):
        pg_api.add_node("premise-a", "Alpha", source="code.py")
        pg_api.add_node("premise-b", "Beta")
        pg_api.add_node("derived", "Gamma", sl="premise-a,premise-b")
        result = pg_api.find_culprits(["premise-a", "premise-b"])
        assert len(result["culprits"]) >= 1
        # premise-b should be less entrenched (no source)
        assert result["culprits"][0]["premise"] == "premise-b"


class TestExplainNode:

    def test_explain_premise(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.explain_node("a")
        assert result["steps"][0]["reason"] == "premise"

    def test_explain_derived_in(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a", label="test")
        result = pg_api.explain_node("b")
        assert result["steps"][0]["truth_value"] == "IN"
        assert "SL" in result["steps"][0]["reason"]
        assert result["steps"][0]["antecedents"] == ["a"]

    def test_explain_derived_out(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.retract_node("a")
        result = pg_api.explain_node("b")
        assert result["steps"][0]["truth_value"] == "OUT"
        assert "a" in result["steps"][0]["failed_antecedents"]


class TestTraceAssumptions:

    def test_trace_premise(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.trace_assumptions("a")
        assert result["premises"] == ["a"]

    def test_trace_chain(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma", sl="b")
        result = pg_api.trace_assumptions("c")
        assert "a" in result["premises"]

    def test_trace_diamond(self, pg_api):
        pg_api.add_node("p1", "Premise 1")
        pg_api.add_node("p2", "Premise 2")
        pg_api.add_node("d1", "Derived 1", sl="p1")
        pg_api.add_node("d2", "Derived 2", sl="p2")
        pg_api.add_node("top", "Top", sl="d1,d2")
        result = pg_api.trace_assumptions("top")
        assert set(result["premises"]) == {"p1", "p2"}


class TestMultiTenancy:

    def test_projects_isolated(self, pg_api):
        import os
        import uuid
        from reasons_lib.pg import PgApi

        pg_api.add_node("shared-id", "Project 1 data")

        project2 = str(uuid.uuid4())
        api2 = PgApi(os.environ["DATABASE_URL"], project2)
        api2.init_db()

        try:
            result = api2.get_status()
            assert result["total"] == 0

            api2.add_node("shared-id", "Project 2 data")
            p1 = pg_api.show_node("shared-id")
            p2 = api2.show_node("shared-id")
            assert p1["text"] == "Project 1 data"
            assert p2["text"] == "Project 2 data"
        finally:
            with api2.conn.cursor() as cur:
                for table in ("rms_propagation_log", "rms_justifications",
                              "rms_nogoods", "rms_network_meta", "rms_nodes"):
                    cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project2,))
            api2.conn.commit()
            api2.close()
