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

    def test_search_dict_format(self, pg_api):
        pg_api.add_node("a", "Alpha belief")
        pg_api.add_node("b", "Beta derived", sl="a")
        result = pg_api.search("alpha", format="dict")
        assert isinstance(result, dict)
        assert result["count"] == 1
        assert result["results"][0]["id"] == "a"
        assert result["results"][0]["truth_value"] == "IN"
        assert len(result["neighbors"]) >= 1

    def test_search_dict_no_results(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.search("zzzznonexistent", format="dict")
        assert result == {"results": [], "count": 0}


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


class TestListGated:

    def test_no_gates(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.list_gated()
        assert result["blockers"] == {}
        assert result["gated_count"] == 0

    def test_active_gate(self, pg_api):
        pg_api.add_node("premise", "Supporting premise")
        pg_api.add_node("blocker", "Defect premise")
        pg_api.add_node("gated", "Conclusion unless blocker", sl="premise", unless="blocker")
        result = pg_api.list_gated()
        assert result["blocker_count"] == 1
        assert result["gated_count"] == 1
        assert "blocker" in result["blockers"]
        assert result["blockers"]["blocker"]["gated"][0]["id"] == "gated"

    def test_satisfied_gate(self, pg_api):
        pg_api.add_node("premise", "Supporting premise")
        pg_api.add_node("blocker", "Defect premise")
        pg_api.add_node("gated", "Conclusion unless blocker", sl="premise", unless="blocker")
        pg_api.retract_node("blocker")
        result = pg_api.list_gated()
        assert result["blockers"] == {}

    def test_multiple_gated_per_blocker(self, pg_api):
        pg_api.add_node("premise", "Supporting premise")
        pg_api.add_node("blocker", "Defect")
        pg_api.add_node("g1", "Gated 1", sl="premise", unless="blocker")
        pg_api.add_node("g2", "Gated 2", sl="premise", unless="blocker")
        result = pg_api.list_gated()
        assert result["blocker_count"] == 1
        assert result["gated_count"] == 2

    def test_blocker_text_included(self, pg_api):
        pg_api.add_node("premise", "Supporting premise")
        pg_api.add_node("bug-123", "Null check missing")
        pg_api.add_node("gated", "X is safe", sl="premise", unless="bug-123")
        result = pg_api.list_gated()
        assert result["blockers"]["bug-123"]["text"] == "Null check missing"


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


class TestWhatIf:

    def test_what_if_retract_cascade(self, pg_api):
        pg_api.add_node("a", "Premise A")
        pg_api.add_node("b", "Derived B", sl="a")
        pg_api.add_node("c", "Derived C", sl="b")
        result = pg_api.what_if_retract("a")
        assert result["already_out"] is False
        assert result["total_affected"] == 2
        ids = [r["id"] for r in result["retracted"]]
        assert "b" in ids
        assert "c" in ids
        assert result["retracted"][0]["depth"] == 1  # b
        assert result["retracted"][1]["depth"] == 2  # c

    def test_what_if_retract_already_out(self, pg_api):
        pg_api.add_node("a", "Premise A")
        pg_api.retract_node("a")
        result = pg_api.what_if_retract("a")
        assert result["already_out"] is True
        assert result["total_affected"] == 0

    def test_what_if_retract_not_found(self, pg_api):
        with pytest.raises(KeyError):
            pg_api.what_if_retract("missing")

    def test_what_if_retract_no_mutation(self, pg_api):
        pg_api.add_node("a", "Premise A")
        pg_api.add_node("b", "Derived B", sl="a")
        pg_api.what_if_retract("a")
        status = pg_api.get_status()
        assert status["in_count"] == 2

    def test_what_if_assert_restores(self, pg_api):
        pg_api.add_node("a", "Premise A")
        pg_api.add_node("b", "Derived B", sl="a")
        pg_api.retract_node("a")
        result = pg_api.what_if_assert("a")
        assert result["already_in"] is False
        assert result["total_affected"] == 1
        assert result["restored"][0]["id"] == "b"
        assert result["restored"][0]["depth"] == 1

    def test_what_if_assert_already_in(self, pg_api):
        pg_api.add_node("a", "Premise A")
        result = pg_api.what_if_assert("a")
        assert result["already_in"] is True
        assert result["total_affected"] == 0

    def test_what_if_retract_with_outlist_restoration(self, pg_api):
        pg_api.add_node("premise", "Supporting premise")
        pg_api.add_node("blocker", "Blocker node")
        pg_api.add_node("gated", "Gated belief", sl="premise", unless="blocker")
        # gated is OUT because blocker is IN
        status = pg_api.show_node("gated")
        assert status["truth_value"] == "OUT"
        result = pg_api.what_if_retract("blocker")
        assert len(result["restored"]) == 1
        assert result["restored"][0]["id"] == "gated"
        # Verify no mutation
        status = pg_api.show_node("gated")
        assert status["truth_value"] == "OUT"


class TestChallenge:

    def test_challenge_premise(self, pg_api):
        pg_api.add_node("a", "Alpha premise")
        result = pg_api.challenge("a", "Alpha is wrong")
        assert result["challenge_id"] == "challenge-a"
        assert result["target_id"] == "a"
        assert "a" in result["changed"]
        status = pg_api.show_node("a")
        assert status["truth_value"] == "OUT"

    def test_challenge_derived(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        result = pg_api.challenge("b", "Beta is wrong")
        assert "b" in result["changed"]
        status = pg_api.show_node("b")
        assert status["truth_value"] == "OUT"

    def test_challenge_already_out(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.retract_node("a")
        result = pg_api.challenge("a", "Alpha is wrong")
        assert result["challenge_id"] == "challenge-a"
        # Target was already OUT, no change
        assert "a" not in result["changed"]

    def test_challenge_custom_id(self, pg_api):
        pg_api.add_node("a", "Alpha")
        result = pg_api.challenge("a", "Alpha is wrong", challenge_id="my-challenge")
        assert result["challenge_id"] == "my-challenge"
        status = pg_api.show_node("my-challenge")
        assert status["truth_value"] == "IN"

    def test_challenge_auto_id_collision(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("challenge-a", "Existing node")
        result = pg_api.challenge("a", "Alpha is wrong")
        assert result["challenge_id"] == "challenge-a-2"

    def test_challenge_not_found(self, pg_api):
        with pytest.raises(KeyError):
            pg_api.challenge("nonexistent", "reason")

    def test_challenge_source(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.challenge("a", "Alpha is wrong")
        challenge = pg_api.show_node("challenge-a")
        assert challenge["source"] == "challenge"

    def test_challenge_metadata(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.challenge("a", "Alpha is wrong")
        # Challenge node has challenge_target metadata
        challenge = pg_api.show_node("challenge-a")
        assert challenge["metadata"]["challenge_target"] == "a"
        # Target has challenges list in metadata
        target = pg_api.show_node("a")
        assert "challenge-a" in target["metadata"]["challenges"]

    def test_challenge_cascade(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.add_node("c", "Gamma", sl="b")
        result = pg_api.challenge("a", "Alpha is wrong")
        assert "a" in result["changed"]
        assert "b" in result["changed"]
        assert "c" in result["changed"]


class TestDefend:

    def test_defend_restores_target(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.challenge("a", "Alpha is wrong")
        assert pg_api.show_node("a")["truth_value"] == "OUT"
        result = pg_api.defend("a", "challenge-a", "Alpha is right")
        assert result["defense_id"] == "defense-challenge-a"
        assert pg_api.show_node("challenge-a")["truth_value"] == "OUT"
        assert pg_api.show_node("a")["truth_value"] == "IN"

    def test_defend_cascade(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta", sl="a")
        pg_api.challenge("a", "Alpha is wrong")
        assert pg_api.show_node("b")["truth_value"] == "OUT"
        pg_api.defend("a", "challenge-a", "Alpha is right")
        assert pg_api.show_node("a")["truth_value"] == "IN"
        assert pg_api.show_node("b")["truth_value"] == "IN"

    def test_defend_metadata(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.challenge("a", "Alpha is wrong")
        pg_api.defend("a", "challenge-a", "Alpha is right")
        defense = pg_api.show_node("defense-challenge-a")
        assert defense["metadata"]["defense_target"] == "challenge-a"
        assert defense["metadata"]["defends"] == "a"

    def test_defend_not_found(self, pg_api):
        pg_api.add_node("a", "Alpha")
        with pytest.raises(KeyError):
            pg_api.defend("a", "nonexistent", "reason")
        with pytest.raises(KeyError):
            pg_api.defend("nonexistent", "a", "reason")

    def test_defend_custom_id(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.challenge("a", "Alpha is wrong")
        result = pg_api.defend("a", "challenge-a", "Alpha is right", defense_id="my-defense")
        assert result["defense_id"] == "my-defense"
        assert pg_api.show_node("my-defense")["truth_value"] == "IN"

    def test_defend_duplicate_id_raises(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("existing", "Existing node")
        pg_api.challenge("a", "Alpha is wrong")
        with pytest.raises(ValueError, match="Defense node"):
            pg_api.defend("a", "challenge-a", "reason", defense_id="existing")

    def test_defend_multiple_challenges(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.challenge("a", "First challenge")
        pg_api.challenge("a", "Second challenge")
        assert pg_api.show_node("a")["truth_value"] == "OUT"
        # Defend against only the first challenge
        pg_api.defend("a", "challenge-a", "First defense")
        # Target should stay OUT because second challenge remains
        assert pg_api.show_node("challenge-a")["truth_value"] == "OUT"
        assert pg_api.show_node("challenge-a-2")["truth_value"] == "IN"
        assert pg_api.show_node("a")["truth_value"] == "OUT"
        # Defend against the second challenge too
        pg_api.defend("a", "challenge-a-2", "Second defense")
        assert pg_api.show_node("a")["truth_value"] == "IN"


class TestCompact:

    def test_compact_empty(self, pg_api):
        result = pg_api.compact()
        assert "0 nodes tracked" in result
        assert "Belief State Summary" in result
        assert "Token count:" in result

    def test_compact_in_nodes(self, pg_api):
        pg_api.add_node("a", "Alpha premise")
        pg_api.add_node("b", "Beta premise")
        pg_api.add_node("c", "Gamma derived", sl="a")
        result = pg_api.compact()
        assert "3 nodes tracked" in result
        assert "## IN (active)" in result
        assert "a" in result
        assert "b" in result
        assert "c" in result

    def test_compact_out_nodes(self, pg_api):
        pg_api.add_node("a", "Alpha premise")
        pg_api.retract_node("a", reason="obsolete")
        result = pg_api.compact()
        assert "## OUT (retracted)" in result
        assert "obsolete" in result

    def test_compact_budget(self, pg_api):
        for i in range(20):
            pg_api.add_node(f"node-{i:02d}", f"This is belief number {i} with some text")
        result_small = pg_api.compact(budget=50)
        result_large = pg_api.compact(budget=5000)
        assert len(result_small) < len(result_large)
        assert "omitted" in result_small or "Token count:" in result_small

    def test_compact_visible_to(self, pg_api):
        pg_api.add_node("public", "Public belief")
        pg_api.add_node("secret", "Secret belief", access_tags=["admin"])
        result = pg_api.compact(visible_to=["user"])
        assert "public" in result
        assert "secret" not in result

    def test_compact_nogoods(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        pg_api.add_nogood(["a", "b"])
        result = pg_api.compact(budget=5000)
        assert "## Nogoods" in result
        assert "nogood-001" in result

    def test_compact_nogoods_filtered_by_visible_to(self, pg_api):
        pg_api.add_node("public", "Public belief")
        pg_api.add_node("secret", "Secret belief", access_tags=["admin"])
        pg_api.add_nogood(["public", "secret"])
        # Nogood references a secret node — should be hidden from non-admin
        result = pg_api.compact(budget=5000, visible_to=["user"])
        assert "Nogoods" not in result
        assert "nogood-001" not in result
        # Admin can see the nogood
        result_admin = pg_api.compact(budget=5000, visible_to=["admin"])
        assert "## Nogoods" in result_admin
        assert "nogood-001" in result_admin

    def test_compact_dependent_count_sorting(self, pg_api):
        pg_api.add_node("root", "Root node")
        pg_api.add_node("d1", "Dep 1", sl="root")
        pg_api.add_node("d2", "Dep 2", sl="root")
        pg_api.add_node("d3", "Dep 3", sl="root")
        pg_api.add_node("leaf", "Leaf node")
        result = pg_api.compact(budget=5000)
        # root has 3 dependents, should appear before leaf (0 dependents)
        root_pos = result.index("root")
        leaf_pos = result.index("leaf")
        assert root_pos < leaf_pos

    def test_compact_summary_nodes(self, pg_api):
        pg_api.add_node("a", "Alpha")
        pg_api.add_node("b", "Beta")
        # Create a summary node that covers a and b
        pg_api.add_node("summary", "Summary of a and b", sl="a,b")
        # Manually set summarizes metadata
        with pg_api.conn.cursor() as cur:
            cur.execute(
                "UPDATE rms_nodes SET metadata = %s WHERE id = %s AND project_id = %s",
                (json.dumps({"summarizes": ["a", "b"]}), "summary", pg_api.project_id),
            )
        pg_api.conn.commit()
        result = pg_api.compact(budget=5000)
        assert "[summary]" in result
        assert "hidden by summaries" in result
