"""Tests for the functional Python API."""

from unittest.mock import patch

import pytest

from reasons import api


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


class TestPropagate:

    def test_no_changes(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        result = api.propagate(db_path=db_path)
        assert result["changed"] == []

    def test_with_changes(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Derived B", sl="a", db_path=db_path)
        assert api.show_node("b", db_path=db_path)["truth_value"] == "IN"
        api.retract_node("a", reason="test", db_path=db_path)
        api.assert_node("a", db_path=db_path)
        from reasons.storage import Storage
        store = Storage(db_path)
        net = store.load()
        net.nodes["b"].truth_value = "OUT"
        store.save(net)
        store.close()
        result = api.propagate(db_path=db_path)
        assert "b" in result["changed"]
        assert api.show_node("b", db_path=db_path)["truth_value"] == "IN"


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


    def test_explain_circular_dependency(self, db_path):
        api.add_node("p", "Premise", db_path=db_path)
        api.add_node("x", "Derived X", sl="p", db_path=db_path)
        api.add_justification("x", sl="y", db_path=db_path)
        api.add_node("y", "Derived Y", sl="x", db_path=db_path)
        api.retract_node("p", db_path=db_path)
        result = api.explain_node("x", db_path=db_path)
        reasons = [s["reason"] for s in result["steps"]]
        assert any("circular" in r for r in reasons)

    def test_explain_diamond_no_false_circular(self, db_path):
        api.add_node("root", "Root premise", db_path=db_path)
        api.add_node("left", "Left", sl="root", db_path=db_path)
        api.add_node("right", "Right", sl="root", db_path=db_path)
        api.add_node("top", "Top", sl="left,right", db_path=db_path)
        result = api.explain_node("top", db_path=db_path)
        reasons = [s["reason"] for s in result["steps"]]
        assert not any("circular" in r for r in reasons)


class TestAddNogood:

    def test_nogood(self, db_path):
        api.add_node("a", "Premise A", db_path=db_path)
        api.add_node("b", "Premise B", db_path=db_path)
        result = api.add_nogood(["a", "b"], db_path=db_path)
        assert result["nogood_id"] == "nogood-a-b"
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

    def test_list_by_label(self, db_path):
        api.add_node("a", "Node A", db_path=db_path)
        api.add_node("b", "Node B", sl="a", label="WARNING", db_path=db_path)
        api.add_node("c", "Node C", sl="a", label="INFO", db_path=db_path)

        result = api.list_nodes(label="WARNING", db_path=db_path)
        ids = [n["id"] for n in result["nodes"]]
        assert ids == ["b"]

    def test_list_by_label_no_match(self, db_path):
        api.add_node("a", "Node A", db_path=db_path)
        api.add_node("b", "Node B", sl="a", label="INFO", db_path=db_path)

        result = api.list_nodes(label="WARNING", db_path=db_path)
        assert result["count"] == 0

    def test_list_by_label_premise_excluded(self, db_path):
        api.add_node("a", "Premise", db_path=db_path)
        api.add_node("b", "Derived", sl="a", label="WARNING", db_path=db_path)

        result = api.list_nodes(label="WARNING", db_path=db_path)
        ids = [n["id"] for n in result["nodes"]]
        assert "a" not in ids
        assert "b" in ids


class TestFtsSearch:

    def test_porter_stemming(self, db_path):
        api.add_node("a", "sandbox access is auto-deactivated after 21 days", db_path=db_path)
        result = api.search("deactivation", db_path=db_path)
        assert "a" in result

    def test_porter_stemming_plural(self, db_path):
        from reasons.api import _fts_search
        api.add_node("a", "max 250 jobs per pipeline", db_path=db_path)
        results = _fts_search("job", db_path)
        assert "a" in results

    def test_progressive_relaxation(self, db_path):
        api.add_node("a", "sandbox access expires after 21 days", db_path=db_path)
        result = api.search("sandbox access duration expiration", db_path=db_path)
        assert "a" in result

    def test_two_term_no_relaxation(self, db_path):
        api.add_node("a", "sandbox access expires", db_path=db_path)
        result = api.search("sandbox quantum", db_path=db_path, format="compact")
        assert "a" not in result

    def test_no_false_positives(self, db_path):
        api.add_node("a", "the quick brown fox", db_path=db_path)
        result = api.search("quantum computing blockchain", db_path=db_path, format="compact")
        assert "a" not in result

    def test_stop_words_filtered(self, db_path):
        from reasons.api import _fts_search
        api.add_node("a", "propagation uses BFS algorithm", db_path=db_path)
        results = _fts_search("What is the propagation algorithm?", db_path)
        assert "a" in results

    def test_all_stop_words_falls_back_to_raw(self, db_path):
        from reasons.api import _fts_search
        api.add_node("a", "the system is working", db_path=db_path)
        results = _fts_search("what is the", db_path)
        assert "a" in results

    def test_single_char_words_only_returns_empty(self, db_path):
        from reasons.api import _fts_search
        api.add_node("a", "some content", db_path=db_path)
        results = _fts_search("a b c", db_path)
        assert results == []

    def test_natural_language_question(self, db_path):
        api.add_node("a", "retraction cascades through dependent nodes", db_path=db_path)
        result = api.search("How does retraction work in the system?",
                            db_path=db_path, format="compact")
        assert "a" in result

    def test_punctuation_in_query(self, db_path):
        from reasons.api import _fts_search
        api.add_node("a", "propagation uses BFS", db_path=db_path)
        results = _fts_search("propagation? (BFS)", db_path)
        assert "a" in results

    def test_long_query_does_not_explode(self, db_path):
        from reasons.api import _fts_search, _fts_query
        from unittest.mock import patch as mock_patch
        api.add_node("a", "alpha beta gamma delta", db_path=db_path)
        query = " ".join(f"term{i}" for i in range(20))
        call_count = [0]
        original_fts_query = _fts_query

        def counting_fts_query(conn, terms):
            call_count[0] += 1
            return original_fts_query(conn, terms)

        with mock_patch("reasons.api._fts_query", side_effect=counting_fts_query):
            _fts_search(query, db_path)
        assert call_count[0] <= 51

    def test_depth_1_includes_direct_antecedents(self, db_path):
        api.add_node("premise", "Propagation uses BFS", db_path=db_path)
        api.add_node("derived", "Propagation is safe", sl="premise", db_path=db_path)
        result = api.search("safe", db_path=db_path, format="compact", depth=1)
        assert "premise" in result

    def test_depth_2_includes_transitive_antecedents(self, db_path):
        api.add_node("root", "BFS traversal algorithm", db_path=db_path)
        api.add_node("mid", "Propagation uses BFS", sl="root", db_path=db_path)
        api.add_node("leaf", "Propagation is safe", sl="mid", db_path=db_path)
        result_d1 = api.search("safe", db_path=db_path, format="compact", depth=1)
        result_d2 = api.search("safe", db_path=db_path, format="compact", depth=2)
        assert "root" not in result_d1
        assert "root" in result_d2

    def test_depth_0_no_expansion(self, db_path):
        api.add_node("premise", "Propagation uses BFS", db_path=db_path)
        api.add_node("derived", "Propagation is safe", sl="premise", db_path=db_path)
        result = api.search("safe", db_path=db_path, format="compact", depth=0)
        assert "premise" not in result
        assert "derived" in result


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


class TestListNegative:

    def test_empty_db(self, db_path):
        with patch("reasons.llm.invoke_model") as mock_llm:
            result = api.list_negative(db_path=db_path)
            assert result == {"negative": [], "count": 0, "candidates": 0, "total": 0}
            mock_llm.assert_not_called()

    def test_no_keyword_matches(self, db_path):
        api.add_node("a", "The sky is blue", db_path=db_path)
        api.add_node("b", "Water flows downhill", db_path=db_path)
        with patch("reasons.llm.invoke_model") as mock_llm:
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 0
            assert result["candidates"] == 0
            assert result["total"] == 2
            mock_llm.assert_not_called()

    def test_classifies_negatives(self, db_path):
        api.add_node("a", "The auth module has a bug in token refresh", db_path=db_path)
        api.add_node("b", "Error handling logs all failures", db_path=db_path)
        api.add_node("c", "The sky is blue", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='["a"]'):
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 1
            assert result["candidates"] == 2
            assert result["total"] == 3
            assert result["negative"][0]["id"] == "a"

    def test_llm_filters_all(self, db_path):
        api.add_node("a", "Error handling is comprehensive", db_path=db_path)
        api.add_node("b", "Failure modes are well documented", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='[]'):
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 0
            assert result["candidates"] == 2
            assert result["total"] == 2

    def test_multiline_json_response(self, db_path):
        api.add_node("a", "There is a critical bug here", db_path=db_path)
        api.add_node("b", "This has a missing check", db_path=db_path)
        multiline = '[\n  "a",\n  "b"\n]'
        with patch("reasons.llm.invoke_model", return_value=multiline):
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 2

    def test_malformed_llm_response(self, db_path):
        api.add_node("a", "There is a critical bug here", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value="Sorry, I cannot do that."):
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 0

    def test_llm_returns_unknown_ids(self, db_path):
        api.add_node("a", "There is a critical bug here", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='["a", "nonexistent", "also-fake"]'):
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 1
            assert result["negative"][0]["id"] == "a"

    def test_prose_with_brackets_before_json(self, db_path):
        api.add_node("a", "There is a critical bug here", db_path=db_path)
        response = 'Based on [the analysis], here are the negative beliefs: ["a"]'
        with patch("reasons.llm.invoke_model", return_value=response):
            result = api.list_negative(db_path=db_path)
            assert result["count"] == 1
            assert result["negative"][0]["id"] == "a"

    def test_claude_not_found_propagates(self, db_path):
        api.add_node("a", "There is a critical bug here", db_path=db_path)
        with patch("reasons.llm.invoke_model", side_effect=FileNotFoundError("'claude' CLI not found in PATH")):
            with pytest.raises(FileNotFoundError):
                api.list_negative(db_path=db_path)

    def test_visible_to(self, db_path):
        api.add_node("a", "Auth has a critical bug", access_tags=["internal"], db_path=db_path)
        api.add_node("b", "API has a missing validation", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='["b"]') as mock_llm:
            result = api.list_negative(visible_to=["public"], db_path=db_path)
            assert result["count"] == 1
            assert result["total"] == 1
            assert result["negative"][0]["id"] == "b"
            prompt = mock_llm.call_args[0][0]
            assert "critical bug" not in prompt

    def test_single_batch_calls_llm_once(self, db_path):
        for i in range(5):
            api.add_node(f"bug-{i}", f"There is a bug in module {i}", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='["bug-0"]') as mock_llm:
            result = api.list_negative(db_path=db_path)
            assert mock_llm.call_count == 1
            assert result["count"] == 1

    def test_batching_large_set(self, db_path):
        for i in range(120):
            api.add_node(f"bug-{i:03d}", f"There is a bug in module {i}", db_path=db_path)

        call_count = [0]

        def mock_invoke(prompt, model="claude"):
            call_count[0] += 1
            if call_count[0] == 1:
                return '["bug-010", "bug-020"]'
            elif call_count[0] == 2:
                return '["bug-060"]'
            else:
                return '[]'

        with patch("reasons.llm.invoke_model", side_effect=mock_invoke):
            result = api.list_negative(db_path=db_path)
        assert call_count[0] == 3
        assert result["count"] == 3
        assert result["candidates"] == 120
        found_ids = {n["id"] for n in result["negative"]}
        assert found_ids == {"bug-010", "bug-020", "bug-060"}

    def test_expanded_terms_match(self, db_path):
        api.add_node("a", "The migration is stalled due to schema conflicts", db_path=db_path)
        api.add_node("b", "There is a regression in the auth flow", db_path=db_path)
        api.add_node("c", "The API docs are undocumented for v2", db_path=db_path)
        api.add_node("d", "Everything works fine", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='["a", "b", "c"]'):
            result = api.list_negative(db_path=db_path)
            assert result["candidates"] == 3
            assert result["total"] == 4

    def test_issue_false_positive_excluded(self, db_path):
        api.add_node("jira-ref", "The child issue was closed last sprint", db_path=db_path)
        api.add_node("real-neg", "There is a known issue in the auth module", db_path=db_path)
        with patch("reasons.llm.invoke_model", return_value='["real-neg"]') as mock_llm:
            result = api.list_negative(db_path=db_path)
            assert result["candidates"] == 1
            assert result["negative"][0]["id"] == "real-neg"

    def test_skip_llm(self, db_path):
        api.add_node("a", "There is a critical bug here", db_path=db_path)
        api.add_node("b", "Everything is fine", db_path=db_path)
        with patch("reasons.llm.invoke_model") as mock_llm:
            result = api.list_negative(skip_llm=True, db_path=db_path)
            mock_llm.assert_not_called()
            assert result["count"] == 1
            assert result["candidates"] == 1
            assert result["negative"][0]["id"] == "a"


class TestSupersedeWithText:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Original text", db_path=db)
        api.add_node("b", "Premise B", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="a,b",
                      label="combined", db_path=db)
        return db

    def test_supersede_with_text(self, db_path):
        result = api.supersede_with_text("a", "Updated text", db_path=db_path)
        assert result["old_id"] == "a"
        new_id = result["new_id"]
        old = api.show_node("a", db_path=db_path)
        new = api.show_node(new_id, db_path=db_path)
        assert old["truth_value"] == "OUT"
        assert new["text"] == "Updated text"
        assert new["truth_value"] == "IN"

    def test_supersede_with_text_custom_id(self, db_path):
        result = api.supersede_with_text("a", "New text", new_id="a-fixed",
                                          db_path=db_path)
        assert result["new_id"] == "a-fixed"
        node = api.show_node("a-fixed", db_path=db_path)
        assert node["text"] == "New text"

    def test_supersede_with_text_copies_access_tags(self, tmp_path):
        db = str(tmp_path / "tagged.db")
        api.add_node("secret", "Classified info", access_tags=["finance"],
                      db_path=db)
        result = api.supersede_with_text("secret", "Updated classified info",
                                          db_path=db)
        new_node = api.show_node(result["new_id"], db_path=db)
        assert new_node["metadata"].get("access_tags") == ["finance"]

    def test_supersede_with_text_no_tags_no_metadata(self, db_path):
        result = api.supersede_with_text("a", "Updated text", db_path=db_path)
        new_node = api.show_node(result["new_id"], db_path=db_path)
        assert "access_tags" not in new_node.get("metadata", {})


class TestWhatIfSupersede:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Original text", db_path=db)
        api.add_node("b", "Premise B", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="a,b",
                      label="combined", db_path=db)
        return db

    def test_basic_supersede(self, db_path):
        result = api.what_if_supersede("a", "Updated text", db_path=db_path)
        assert result["old_id"] == "a"
        assert result["new_id"] == "a-v2"
        assert result["already_out"] is False
        assert not any(r["id"] == "a" for r in result["retracted"])
        assert result["total_affected"] >= 1
        # Database should not be modified
        node = api.show_node("a", db_path=db_path)
        assert node["truth_value"] == "IN"
        assert "a-v2" not in [n["id"] for n in api.get_status(db_path=db_path)["nodes"]]

    def test_cascade_to_dependents(self, db_path):
        result = api.what_if_supersede("a", "Updated text", db_path=db_path)
        retracted_ids = [r["id"] for r in result["retracted"]]
        assert "a" not in retracted_ids
        assert "derived-ab" in retracted_ids

    def test_custom_new_id(self, db_path):
        result = api.what_if_supersede("a", "Updated text", new_id="a-fixed",
                                        db_path=db_path)
        assert result["new_id"] == "a-fixed"

    def test_already_out(self, db_path):
        api.retract_node("a", db_path=db_path)
        result = api.what_if_supersede("a", "Updated text", db_path=db_path)
        assert result["already_out"] is True
        assert result["retracted"] == []
        assert result["total_affected"] == 0

    def test_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.what_if_supersede("nonexistent", "text", db_path=db_path)

    def test_does_not_mutate_db(self, db_path):
        before = api.get_status(db_path=db_path)
        api.what_if_supersede("a", "Updated text", db_path=db_path)
        after = api.get_status(db_path=db_path)
        assert before["in_count"] == after["in_count"]
        assert before["total"] == after["total"]

    def test_auto_id_increments(self, db_path):
        api.add_node("a-v2", "Existing v2", db_path=db_path)
        result = api.what_if_supersede("a", "Updated text", db_path=db_path)
        assert result["new_id"] == "a-v3"


class TestSetMetadata:

    def test_sets_key(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "A belief", db_path=db)
        result = api.set_metadata("a", "source_file", "src/foo.py", db_path=db)
        assert result == {"node_id": "a", "key": "source_file"}
        node = api.show_node("a", db_path=db)
        assert node["metadata"]["source_file"] == "src/foo.py"

    def test_overwrites_existing_key(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "A belief", db_path=db)
        api.set_metadata("a", "k", "v1", db_path=db)
        api.set_metadata("a", "k", "v2", db_path=db)
        node = api.show_node("a", db_path=db)
        assert node["metadata"]["k"] == "v2"

    def test_nonexistent_raises(self, tmp_path):
        db = str(tmp_path / "test.db")
        with pytest.raises(KeyError):
            api.set_metadata("nope", "k", "v", db_path=db)


class TestListClusters:

    @pytest.fixture
    def db_with_beliefs(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.init_db(db_path=db)
        for i in range(10):
            api.add_node(f"in-{i}", f"Active belief {i}", db_path=db)
        for i in range(5):
            api.add_node(f"out-{i}", f"Retracted belief {i}", db_path=db)
            api.retract_node(f"out-{i}", db_path=db)
        return db

    def test_filters_by_status(self, db_with_beliefs):
        mock_result = {"clusters": [{"id": 0, "beliefs": []}], "n_clusters": 1, "embedding_model": "test"}
        with patch("reasons.cluster.list_clusters", return_value=mock_result) as mock_lc:
            api.list_clusters(status="IN", db_path=db_with_beliefs)
            beliefs_arg = mock_lc.call_args[0][0]
            assert all(k.startswith("in-") for k in beliefs_arg)
            assert len(beliefs_arg) == 10

    def test_filters_out_status(self, db_with_beliefs):
        mock_result = {"clusters": [{"id": 0, "beliefs": []}], "n_clusters": 1, "embedding_model": "test"}
        with patch("reasons.cluster.list_clusters", return_value=mock_result) as mock_lc:
            api.list_clusters(status="OUT", db_path=db_with_beliefs)
            beliefs_arg = mock_lc.call_args[0][0]
            assert all(k.startswith("out-") for k in beliefs_arg)
            assert len(beliefs_arg) == 5

    def test_empty_network(self, tmp_path):
        db = str(tmp_path / "empty.db")
        api.init_db(db_path=db)
        result = api.list_clusters(db_path=db)
        assert result["clusters"] == []
        assert result["n_clusters"] == 0

    def test_passes_seed(self, db_with_beliefs):
        mock_result = {"clusters": [], "n_clusters": 0, "embedding_model": "test"}
        with patch("reasons.cluster.list_clusters", return_value=mock_result) as mock_lc:
            api.list_clusters(seed=42, db_path=db_with_beliefs)
            assert mock_lc.call_args[1]["seed"] == 42

    def test_passes_n_clusters(self, db_with_beliefs):
        mock_result = {"clusters": [], "n_clusters": 0, "embedding_model": "test"}
        with patch("reasons.cluster.list_clusters", return_value=mock_result) as mock_lc:
            api.list_clusters(n_clusters=3, db_path=db_with_beliefs)
            assert mock_lc.call_args[1]["n_clusters"] == 3


try:
    from reasons.cluster import HAS_CLUSTER_DEPS
except ImportError:
    HAS_CLUSTER_DEPS = False

skip_no_cluster = pytest.mark.skipif(
    not HAS_CLUSTER_DEPS,
    reason="sentence-transformers and scikit-learn not installed"
)


@skip_no_cluster
class TestDeduplicateSemantic:

    @pytest.fixture
    def db_with_similar(self, tmp_path):
        db = str(tmp_path / "sim.db")
        api.init_db(db_path=db)
        api.add_node("input-validation-at-boundaries",
                      "The system validates all inputs at system boundaries",
                      db_path=db)
        api.add_node("boundary-input-checking",
                      "Input validation occurs at system edges and boundaries",
                      db_path=db)
        api.add_node("database-query-performance",
                      "Database queries are optimized for read-heavy workloads",
                      db_path=db)
        return db

    def test_semantic_finds_similar_text(self, db_with_similar):
        result = api.deduplicate(threshold=0.5, semantic=True, db_path=db_with_similar)
        assert len(result["clusters"]) >= 1
        cluster_ids = {b["id"] for b in result["clusters"][0]["beliefs"]}
        assert "input-validation-at-boundaries" in cluster_ids
        assert "boundary-input-checking" in cluster_ids

    def test_semantic_skips_dissimilar(self, db_with_similar):
        result = api.deduplicate(threshold=0.8, semantic=True, db_path=db_with_similar)
        for cluster in result["clusters"]:
            ids = {b["id"] for b in cluster["beliefs"]}
            assert not ({"input-validation-at-boundaries", "database-query-performance"} <= ids)

    def test_semantic_auto_retracts(self, db_with_similar):
        result = api.deduplicate(threshold=0.5, semantic=True, auto=True,
                                  db_path=db_with_similar)
        retracted_set = set(result["retracted"])
        similar_pair = {"input-validation-at-boundaries", "boundary-input-checking"}
        assert len(retracted_set & similar_pair) == 1
        assert "database-query-performance" not in retracted_set

    def test_semantic_empty_network(self, tmp_path):
        db = str(tmp_path / "empty.db")
        api.init_db(db_path=db)
        result = api.deduplicate(threshold=0.5, semantic=True, db_path=db)
        assert result["clusters"] == []
        assert result["retracted"] == []

    def test_jaccard_mode_unchanged(self, db_with_similar):
        result = api.deduplicate(threshold=0.5, semantic=False, db_path=db_with_similar)
        assert result["retracted"] == []


class TestLifecycleTimestamps:

    def test_add_node_sets_created_at(self, db_path):
        api.add_node("ts-a", "Timestamped node", db_path=db_path)
        node = api.show_node("ts-a", db_path=db_path)
        assert node["created_at"] != ""
        assert node["updated_at"] != ""
        assert node["created_at"] == node["updated_at"]

    def test_set_metadata_sets_updated_at(self, db_path):
        api.add_node("ts-c", "Meta node", db_path=db_path)
        original = api.show_node("ts-c", db_path=db_path)
        api.set_metadata("ts-c", "key", "value", db_path=db_path)
        updated = api.show_node("ts-c", db_path=db_path)
        assert updated["updated_at"] >= original["updated_at"]

    def test_retract_sets_retracted_at(self, db_path):
        api.add_node("ts-d", "To retract", db_path=db_path)
        api.retract_node("ts-d", db_path=db_path)
        node = api.show_node("ts-d", db_path=db_path)
        assert node["retracted_at"] != ""
        assert node["truth_value"] == "OUT"

    def test_show_node_includes_all_timestamps(self, db_path):
        api.add_node("ts-e", "Full timestamps", db_path=db_path)
        node = api.show_node("ts-e", db_path=db_path)
        for key in ("created_at", "updated_at", "reviewed_at", "verified_at", "retracted_at"):
            assert key in node

    def test_export_includes_timestamps(self, db_path):
        api.add_node("ts-f", "Exported node", db_path=db_path)
        result = api.export_network(db_path=db_path)
        node_data = result["nodes"]["ts-f"]
        assert "created_at" in node_data
        assert node_data["created_at"] != ""

    def test_import_roundtrips_timestamps(self, tmp_path, db_path):
        api.add_node("ts-g", "Roundtrip node", db_path=db_path)
        api.retract_node("ts-g", reason="testing", db_path=db_path)
        export = api.export_network(db_path=db_path)

        import json
        json_path = str(tmp_path / "export.json")
        with open(json_path, "w") as f:
            json.dump(export, f)

        db2 = str(tmp_path / "imported.db")
        api.init_db(db_path=db2)
        api.import_json(json_path, db_path=db2)
        node = api.show_node("ts-g", db_path=db2)
        assert node["created_at"] == export["nodes"]["ts-g"]["created_at"]
        assert node["retracted_at"] == export["nodes"]["ts-g"]["retracted_at"]
        assert node["updated_at"] == export["nodes"]["ts-g"]["updated_at"]

    def test_assert_clears_retracted_at(self, db_path):
        api.add_node("ts-h", "Retract then restore", db_path=db_path)
        api.retract_node("ts-h", db_path=db_path)
        retracted = api.show_node("ts-h", db_path=db_path)
        assert retracted["retracted_at"] != ""
        assert retracted["truth_value"] == "OUT"

        api.assert_node("ts-h", db_path=db_path)
        restored = api.show_node("ts-h", db_path=db_path)
        assert restored["retracted_at"] == ""
        assert restored["truth_value"] == "IN"
        assert restored["updated_at"] >= retracted["updated_at"]

    def test_cascade_does_not_set_retracted_at_on_dependents(self, db_path):
        api.add_node("ts-root", "Root premise", db_path=db_path)
        api.add_node("ts-dep", "Depends on root", sl="ts-root", db_path=db_path)
        api.retract_node("ts-root", db_path=db_path)

        root = api.show_node("ts-root", db_path=db_path)
        dep = api.show_node("ts-dep", db_path=db_path)
        assert root["retracted_at"] != ""
        assert dep["truth_value"] == "OUT"
        assert dep["retracted_at"] == ""

    def test_verified_at_preserved_through_export_import(self, tmp_path, db_path):
        from datetime import datetime, timezone
        api.add_node("ts-ver", "Verified node", db_path=db_path)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        from reasons.storage import Storage
        store = Storage(db_path)
        net = store.load()
        net.nodes["ts-ver"].verified_at = now
        store.save(net)
        store.close()

        export = api.export_network(db_path=db_path)
        assert export["nodes"]["ts-ver"]["verified_at"] == now

        import json
        json_path = str(tmp_path / "verified.json")
        with open(json_path, "w") as f:
            json.dump(export, f)

        db2 = str(tmp_path / "verified_import.db")
        api.init_db(db_path=db2)
        api.import_json(json_path, db_path=db2)
        node = api.show_node("ts-ver", db_path=db2)
        assert node["verified_at"] == now


class TestProposeRetraction:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Original text", db_path=db)
        api.add_node("b", "Premise B", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="a,b",
                      label="combined", db_path=db)
        return db

    def test_basic_propose(self, db_path):
        result = api.propose_retraction("a", reason="Stale finding",
                                         proposer="worker-bee", db_path=db_path)
        assert result["proposal_id"].startswith("prop-a-retract-")
        assert result["target_id"] == "a"
        assert result["action"] == "retract"
        assert result["status"] == "pending"
        assert result["impact"]["total_affected"] >= 1

    def test_no_truth_change(self, db_path):
        api.propose_retraction("a", db_path=db_path)
        node = api.show_node("a", db_path=db_path)
        assert node["truth_value"] == "IN"

    def test_target_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.propose_retraction("nonexistent", db_path=db_path)

    def test_target_already_out(self, db_path):
        api.retract_node("a", db_path=db_path)
        with pytest.raises(ValueError, match="already OUT"):
            api.propose_retraction("a", db_path=db_path)

    def test_auto_stales_older_pending(self, db_path):
        r1 = api.propose_retraction("a", reason="first", db_path=db_path)
        r2 = api.propose_retraction("a", reason="second", db_path=db_path)
        assert r1["proposal_id"] in r2["staled"]
        p1 = api.show_proposal(r1["proposal_id"], db_path=db_path)
        assert p1["status"] == "stale"
        p2 = api.show_proposal(r2["proposal_id"], db_path=db_path)
        assert p2["status"] == "pending"

    def test_list_proposals(self, db_path):
        api.propose_retraction("a", proposer="bee-1", db_path=db_path)
        api.propose_retraction("b", proposer="bee-2", db_path=db_path)
        result = api.list_proposals(db_path=db_path)
        assert result["count"] == 2
        ids = [p["id"] for p in result["proposals"]]
        assert any("a" in pid for pid in ids)
        assert any("b" in pid for pid in ids)

    def test_list_proposals_filter_by_proposer(self, db_path):
        api.propose_retraction("a", proposer="bee-1", db_path=db_path)
        api.propose_retraction("b", proposer="bee-2", db_path=db_path)
        result = api.list_proposals(proposer="bee-1", db_path=db_path)
        assert result["count"] == 1
        assert result["proposals"][0]["proposer"] == "bee-1"

    def test_show_proposal(self, db_path):
        r = api.propose_retraction("a", reason="Stale", basis="source-divergence",
                                    evidence="file changed", proposer="bee",
                                    db_path=db_path)
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert p["action"] == "retract"
        assert p["reason"] == "Stale"
        assert p["basis"] == "source-divergence"
        assert p["evidence"] == "file changed"
        assert p["proposer"] == "bee"
        assert p["snapshot"]["truth_value"] == "IN"

    def test_show_proposal_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.show_proposal("prop-nonexistent", db_path=db_path)

    def test_proposal_ids_increment(self, db_path):
        r1 = api.propose_retraction("a", reason="first", db_path=db_path)
        r2 = api.propose_retraction("a", reason="second", db_path=db_path)
        assert r1["proposal_id"] == "prop-a-retract-1"
        assert r2["proposal_id"] == "prop-a-retract-2"


class TestProposeSupersession:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Original text", db_path=db)
        api.add_node("b", "Premise B", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="a,b",
                      label="combined", db_path=db)
        return db

    def test_basic_propose(self, db_path):
        result = api.propose_supersession("a", "Updated text",
                                           proposer="worker-bee",
                                           db_path=db_path)
        assert result["proposal_id"].startswith("prop-a-supersede-")
        assert result["target_id"] == "a"
        assert result["new_id"] == "a-v2"
        assert result["action"] == "supersede"
        assert result["status"] == "pending"

    def test_no_truth_change(self, db_path):
        api.propose_supersession("a", "Updated text", db_path=db_path)
        node = api.show_node("a", db_path=db_path)
        assert node["truth_value"] == "IN"
        status = api.get_status(db_path=db_path)
        assert not any(n["id"] == "a-v2" for n in status["nodes"])

    def test_custom_new_id(self, db_path):
        result = api.propose_supersession("a", "Updated text",
                                           new_id="a-fixed", db_path=db_path)
        assert result["new_id"] == "a-fixed"

    def test_target_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.propose_supersession("nonexistent", "text", db_path=db_path)

    def test_target_already_out(self, db_path):
        api.retract_node("a", db_path=db_path)
        with pytest.raises(ValueError, match="already OUT"):
            api.propose_supersession("a", "text", db_path=db_path)

    def test_new_id_already_exists(self, db_path):
        with pytest.raises(ValueError, match="already exists"):
            api.propose_supersession("a", "text", new_id="b", db_path=db_path)

    def test_auto_stales_older_pending(self, db_path):
        r1 = api.propose_supersession("a", "first", db_path=db_path)
        r2 = api.propose_supersession("a", "second", db_path=db_path)
        assert r1["proposal_id"] in r2["staled"]
        p1 = api.show_proposal(r1["proposal_id"], db_path=db_path)
        assert p1["status"] == "stale"

    def test_show_proposal_has_proposed_text(self, db_path):
        r = api.propose_supersession("a", "Updated text", db_path=db_path)
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert p["proposed_text"] == "Updated text"
        assert p["new_id"] == "a-v2"

    def test_different_actions_dont_stale_each_other(self, db_path):
        r1 = api.propose_retraction("a", db_path=db_path)
        r2 = api.propose_supersession("a", "new text", db_path=db_path)
        assert r2["staled"] == []
        p1 = api.show_proposal(r1["proposal_id"], db_path=db_path)
        assert p1["status"] == "pending"


class TestProposeAddition:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Premise A", db_path=db)
        api.add_node("b", "Premise B", db_path=db)
        return db

    def test_basic_propose(self, db_path):
        result = api.propose_addition("new-belief", "A new belief",
                                       proposer="worker-bee", db_path=db_path)
        assert result["proposal_id"].startswith("prop-new-belief-add-")
        assert result["node_id"] == "new-belief"
        assert result["action"] == "add"
        assert result["status"] == "pending"

    def test_no_network_change(self, db_path):
        api.propose_addition("new-belief", "A new belief", db_path=db_path)
        status = api.get_status(db_path=db_path)
        assert not any(n["id"] == "new-belief" for n in status["nodes"])

    def test_node_already_exists(self, db_path):
        with pytest.raises(ValueError, match="already exists"):
            api.propose_addition("a", "duplicate", db_path=db_path)

    def test_with_justification(self, db_path):
        result = api.propose_addition("derived-c", "Derived from A and B",
                                       sl="a,b", label="combined",
                                       db_path=db_path)
        p = api.show_proposal(result["proposal_id"], db_path=db_path)
        assert p["proposed_text"] == "Derived from A and B"
        snapshot = p["snapshot"]
        assert snapshot["sl"] == "a,b"
        assert snapshot["label"] == "combined"

    def test_auto_stales_older_pending(self, db_path):
        r1 = api.propose_addition("new-belief", "first draft", db_path=db_path)
        r2 = api.propose_addition("new-belief", "second draft", db_path=db_path)
        assert r1["proposal_id"] in r2["staled"]
        p1 = api.show_proposal(r1["proposal_id"], db_path=db_path)
        assert p1["status"] == "stale"

    def test_shows_in_list(self, db_path):
        api.propose_addition("new-belief", "A belief", db_path=db_path)
        result = api.list_proposals(db_path=db_path)
        assert result["count"] == 1
        assert result["proposals"][0]["action"] == "add"

    def test_with_source(self, db_path):
        r = api.propose_addition("sourced", "From a file",
                                  source="repo:src/foo.py",
                                  source_url="https://example.com",
                                  db_path=db_path)
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        snapshot = p["snapshot"]
        assert snapshot["source"] == "repo:src/foo.py"
        assert snapshot["source_url"] == "https://example.com"

    def test_different_actions_independent(self, db_path):
        r1 = api.propose_retraction("a", db_path=db_path)
        r2 = api.propose_addition("new-belief", "new", db_path=db_path)
        assert r2["staled"] == []
        result = api.list_proposals(db_path=db_path)
        assert result["count"] == 2


class TestAcceptProposal:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Original text", db_path=db)
        api.add_node("b", "Premise B", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="a,b",
                      label="combined", db_path=db)
        return db

    def test_accept_retraction(self, db_path):
        r = api.propose_retraction("a", reason="Stale", db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], voter="reviewer",
                                      db_path=db_path)
        assert result["applied"] is True
        assert result["status"] == "accepted"
        assert result["action"] == "retract"
        node = api.show_node("a", db_path=db_path)
        assert node["truth_value"] == "OUT"

    def test_accept_retraction_cascades(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.accept_proposal(r["proposal_id"], db_path=db_path)
        derived = api.show_node("derived-ab", db_path=db_path)
        assert derived["truth_value"] == "OUT"

    def test_accept_supersession(self, db_path):
        r = api.propose_supersession("a", "Updated text", db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], voter="reviewer",
                                      db_path=db_path)
        assert result["applied"] is True
        assert result["action"] == "supersede"
        old = api.show_node("a", db_path=db_path)
        assert old["truth_value"] == "OUT"
        new = api.show_node("a-v2", db_path=db_path)
        assert new["text"] == "Updated text"
        assert new["truth_value"] == "IN"

    def test_accept_addition(self, db_path):
        r = api.propose_addition("new-belief", "A new belief",
                                  sl="a,b", label="derived",
                                  db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is True
        assert result["action"] == "add"
        node = api.show_node("new-belief", db_path=db_path)
        assert node["text"] == "A new belief"
        assert node["truth_value"] == "IN"

    def test_accept_addition_premise(self, db_path):
        r = api.propose_addition("new-premise", "A premise",
                                  db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is True
        node = api.show_node("new-premise", db_path=db_path)
        assert node["truth_value"] == "IN"

    def test_accept_marks_proposal_accepted(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.accept_proposal(r["proposal_id"], voter="rev", db_path=db_path)
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert p["status"] == "accepted"
        assert p["resolved_by"] == "rev"
        assert p["resolved_at"] != ""

    def test_accept_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.accept_proposal("prop-nonexistent", db_path=db_path)

    def test_accept_already_resolved(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.reject_proposal(r["proposal_id"], db_path=db_path)
        with pytest.raises(ValueError, match="not pending"):
            api.accept_proposal(r["proposal_id"], db_path=db_path)

    def test_drift_target_already_out(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.retract_node("a", db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is False
        assert result["status"] == "stale"
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert p["status"] == "stale"

    def test_drift_target_deleted(self, db_path):
        r = api.propose_supersession("b", "new B", db_path=db_path)
        api.retract_node("b", db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is False
        assert result["status"] == "stale"

    def test_drift_add_node_already_exists(self, db_path):
        r = api.propose_addition("new-belief", "text", db_path=db_path)
        api.add_node("new-belief", "someone added it first", db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is False
        assert result["status"] == "stale"

    def test_drift_supersede_new_id_collision(self, db_path):
        r = api.propose_supersession("a", "Updated", new_id="a-fixed",
                                      db_path=db_path)
        api.add_node("a-fixed", "someone used this id", db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is False
        assert result["status"] == "stale"


class TestRejectProposal:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Premise A", db_path=db)
        return db

    def test_reject(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        result = api.reject_proposal(r["proposal_id"], voter="reviewer",
                                      reason="Not convinced", db_path=db_path)
        assert result["status"] == "rejected"
        assert result["reason"] == "Not convinced"

    def test_reject_no_truth_change(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.reject_proposal(r["proposal_id"], db_path=db_path)
        node = api.show_node("a", db_path=db_path)
        assert node["truth_value"] == "IN"

    def test_reject_marks_proposal(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.reject_proposal(r["proposal_id"], voter="rev", db_path=db_path)
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert p["status"] == "rejected"
        assert p["resolved_by"] == "rev"

    def test_reject_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.reject_proposal("prop-nonexistent", db_path=db_path)

    def test_reject_already_resolved(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.accept_proposal(r["proposal_id"], db_path=db_path)
        with pytest.raises(ValueError, match="not pending"):
            api.reject_proposal(r["proposal_id"], db_path=db_path)


class TestWithdrawProposal:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("a", "Premise A", db_path=db)
        return db

    def test_withdraw(self, db_path):
        r = api.propose_retraction("a", proposer="bee", db_path=db_path)
        result = api.withdraw_proposal(r["proposal_id"], proposer="bee",
                                        db_path=db_path)
        assert result["status"] == "withdrawn"

    def test_withdraw_no_truth_change(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.withdraw_proposal(r["proposal_id"], db_path=db_path)
        node = api.show_node("a", db_path=db_path)
        assert node["truth_value"] == "IN"

    def test_withdraw_marks_proposal(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.withdraw_proposal(r["proposal_id"], proposer="bee",
                               db_path=db_path)
        p = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert p["status"] == "withdrawn"
        assert p["resolved_by"] == "bee"

    def test_withdraw_not_found(self, db_path):
        with pytest.raises(KeyError):
            api.withdraw_proposal("prop-nonexistent", db_path=db_path)

    def test_withdraw_already_resolved(self, db_path):
        r = api.propose_retraction("a", db_path=db_path)
        api.reject_proposal(r["proposal_id"], db_path=db_path)
        with pytest.raises(ValueError, match="not pending"):
            api.withdraw_proposal(r["proposal_id"], db_path=db_path)


class TestProposeNogood:

    def test_basic(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        api.add_node("y", "Y", db_path=db_path)
        r = api.propose_nogood(["x", "y"], reason="contradictory",
                               proposer="bee", db_path=db_path)
        assert r["action"] == "nogood"
        assert r["status"] == "pending"
        assert sorted(r["node_ids"]) == ["x", "y"]
        assert r["proposal_id"].startswith("prop-")

    def test_requires_two_nodes(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        with pytest.raises(ValueError, match="at least 2"):
            api.propose_nogood(["x"], db_path=db_path)

    def test_missing_node(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        with pytest.raises(KeyError, match="not found"):
            api.propose_nogood(["x", "missing"], db_path=db_path)

    def test_no_network_change(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        api.add_node("y", "Y", db_path=db_path)
        api.propose_nogood(["x", "y"], db_path=db_path)
        nx = api.show_node("x", db_path=db_path)
        ny = api.show_node("y", db_path=db_path)
        assert nx["truth_value"] == "IN"
        assert ny["truth_value"] == "IN"

    def test_accept_nogood(self, db_path):
        api.add_node("p", "P", db_path=db_path)
        api.add_node("q", "Q", db_path=db_path)
        r = api.propose_nogood(["p", "q"], db_path=db_path)
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is True
        assert result["status"] == "accepted"

    def test_accept_nogood_missing_node(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        api.add_node("b", "B", db_path=db_path)
        r = api.propose_nogood(["a", "b"], db_path=db_path)
        api.retract_node("a", db_path=db_path)
        with api._with_network(db_path, write=True) as net:
            del net.nodes["a"]
        result = api.accept_proposal(r["proposal_id"], db_path=db_path)
        assert result["applied"] is False
        assert result["status"] == "stale"

    def test_auto_stale(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        api.add_node("y", "Y", db_path=db_path)
        r1 = api.propose_nogood(["x", "y"], db_path=db_path)
        r2 = api.propose_nogood(["x", "y"], db_path=db_path)
        detail = api.show_proposal(r1["proposal_id"], db_path=db_path)
        assert detail["status"] == "stale"
        detail2 = api.show_proposal(r2["proposal_id"], db_path=db_path)
        assert detail2["status"] == "pending"

    def test_show_in_list(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        api.add_node("y", "Y", db_path=db_path)
        api.propose_nogood(["x", "y"], db_path=db_path)
        result = api.list_proposals(db_path=db_path)
        assert result["count"] == 1
        assert result["proposals"][0]["action"] == "nogood"


class TestProposalTags:

    def test_retract_with_tags(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        r = api.propose_retraction("a", tags=["infra", "stale"],
                                    db_path=db_path)
        detail = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert detail["tags"] == ["infra", "stale"]

    def test_supersede_with_tags(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        r = api.propose_supersession("a", "A updated", tags=["review"],
                                      db_path=db_path)
        detail = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert detail["tags"] == ["review"]

    def test_add_with_tags(self, db_path):
        r = api.propose_addition("new-node", "New", tags=["draft"],
                                  db_path=db_path)
        detail = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert detail["tags"] == ["draft"]

    def test_nogood_with_tags(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        api.add_node("y", "Y", db_path=db_path)
        r = api.propose_nogood(["x", "y"], tags=["contradiction"],
                                db_path=db_path)
        detail = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert detail["tags"] == ["contradiction"]

    def test_no_tags_default_empty(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        r = api.propose_retraction("a", db_path=db_path)
        detail = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert detail["tags"] == []

    def test_list_filter_by_tag(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        api.add_node("b", "B", db_path=db_path)
        api.propose_retraction("a", tags=["infra"], db_path=db_path)
        api.propose_retraction("b", tags=["review"], db_path=db_path)
        infra = api.list_proposals(tag="infra", db_path=db_path)
        assert infra["count"] == 1
        assert infra["proposals"][0]["target_id"] == "a"
        review = api.list_proposals(tag="review", db_path=db_path)
        assert review["count"] == 1
        assert review["proposals"][0]["target_id"] == "b"

    def test_tags_sorted(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        r = api.propose_retraction("a", tags=["z-tag", "a-tag"],
                                    db_path=db_path)
        detail = api.show_proposal(r["proposal_id"], db_path=db_path)
        assert detail["tags"] == ["a-tag", "z-tag"]

    def test_tags_in_list_response(self, db_path):
        api.add_node("a", "A", db_path=db_path)
        api.propose_retraction("a", tags=["infra"], db_path=db_path)
        result = api.list_proposals(db_path=db_path)
        assert result["proposals"][0]["tags"] == ["infra"]


class TestStoreLlmProposals:

    def test_stores_retract(self, db_path):
        api.add_node("a", "A is true", db_path=db_path)
        llm_result = {
            "proposals": [{
                "id": "a",
                "action": "retract",
                "proposed_text": None,
                "failure_mode": "stale",
                "basis": "prior-knowledge",
                "evidence": "outdated",
                "comment": "No longer valid",
            }],
        }
        result = api.store_llm_proposals(llm_result, proposer="test-llm",
                                         db_path=db_path)
        assert result["count"] == 1
        assert result["stored"][0]["action"] == "retract"
        assert result["stored"][0]["node_id"] == "a"
        props = api.list_proposals(db_path=db_path)
        assert props["count"] == 1
        assert props["proposals"][0]["action"] == "retract"

    def test_stores_update_as_supersede(self, db_path):
        api.add_node("b", "B is true", db_path=db_path)
        llm_result = {
            "proposals": [{
                "id": "b",
                "action": "update",
                "proposed_text": "B is actually false",
                "failure_mode": "contradicted-by-source",
                "basis": "source-divergence",
                "evidence": "Source changed",
                "comment": "Source disagrees",
            }],
        }
        result = api.store_llm_proposals(llm_result, proposer="test-llm",
                                         db_path=db_path)
        assert result["count"] == 1
        assert result["stored"][0]["action"] == "supersede"
        assert result["stored"][0]["new_id"] != ""

    def test_skips_update_without_text(self, db_path):
        api.add_node("c", "C is true", db_path=db_path)
        llm_result = {
            "proposals": [{
                "id": "c",
                "action": "update",
                "proposed_text": None,
                "failure_mode": "",
                "basis": "prior-knowledge",
                "evidence": "",
                "comment": "",
            }],
        }
        result = api.store_llm_proposals(llm_result, db_path=db_path)
        assert result["count"] == 0
        assert len(result["skipped"]) == 1
        assert "no proposed_text" in result["skipped"][0]["reason"]

    def test_skips_missing_node(self, db_path):
        llm_result = {
            "proposals": [{
                "id": "nonexistent",
                "action": "retract",
                "proposed_text": None,
                "failure_mode": "stale",
                "basis": "prior-knowledge",
                "evidence": "",
                "comment": "",
            }],
        }
        result = api.store_llm_proposals(llm_result, db_path=db_path)
        assert result["count"] == 0
        assert len(result["skipped"]) == 1

    def test_mixed_batch(self, db_path):
        api.add_node("x", "X", db_path=db_path)
        api.add_node("y", "Y", db_path=db_path)
        llm_result = {
            "proposals": [
                {
                    "id": "x",
                    "action": "retract",
                    "proposed_text": None,
                    "failure_mode": "stale",
                    "basis": "prior-knowledge",
                    "evidence": "",
                    "comment": "Stale",
                },
                {
                    "id": "y",
                    "action": "update",
                    "proposed_text": "Y revised",
                    "failure_mode": "smuggled-premise",
                    "basis": "prior-knowledge",
                    "evidence": "",
                    "comment": "Fixed assumption",
                },
                {
                    "id": "missing",
                    "action": "retract",
                    "proposed_text": None,
                    "failure_mode": "",
                    "basis": "prior-knowledge",
                    "evidence": "",
                    "comment": "",
                },
            ],
        }
        result = api.store_llm_proposals(llm_result, db_path=db_path)
        assert result["count"] == 2
        assert len(result["skipped"]) == 1
        actions = {s["action"] for s in result["stored"]}
        assert actions == {"retract", "supersede"}

    def test_empty_proposals(self, db_path):
        result = api.store_llm_proposals({"proposals": []}, db_path=db_path)
        assert result["count"] == 0
        assert result["stored"] == []
        assert result["skipped"] == []

    def test_proposals_are_pending(self, db_path):
        api.add_node("d", "D is true", db_path=db_path)
        llm_result = {
            "proposals": [{
                "id": "d",
                "action": "retract",
                "proposed_text": None,
                "failure_mode": "stale",
                "basis": "source-divergence",
                "evidence": "file changed",
                "comment": "outdated",
            }],
        }
        result = api.store_llm_proposals(llm_result, proposer="my-llm",
                                         db_path=db_path)
        proposal_id = result["stored"][0]["proposal_id"]
        detail = api.show_proposal(proposal_id, db_path=db_path)
        assert detail["status"] == "pending"
        assert detail["proposer"] == "my-llm"
        assert detail["basis"] == "source-divergence"


class TestOrSearch:

    def test_search_with_pipes_or_logic(self, db_path):
        api.add_node("alpha", "Finance report", db_path=db_path)
        api.add_node("beta", "Legal review", db_path=db_path)
        api.add_node("gamma", "Technical docs", db_path=db_path)
        result = api.search("Finance|Legal", db_path=db_path)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" not in result

    def test_search_with_pipes_returns_union(self, db_path):
        api.add_node("a", "Apple tree", db_path=db_path)
        api.add_node("b", "Banana fruit", db_path=db_path)
        api.add_node("c", "Cherry blossom", db_path=db_path)
        result = api.search("Apple|Banana", db_path=db_path)
        assert "a" in result
        assert "b" in result
        assert "c" not in result

    def test_pipes_with_spaces(self, db_path):
        api.add_node("x", "Xray data", db_path=db_path)
        api.add_node("y", "Yellow note", db_path=db_path)
        result = api.search("Xray | Yellow", db_path=db_path)
        assert "x" in result
        assert "y" in result


class TestRegexSearch:

    def test_regex_pattern_matching(self, db_path):
        api.add_node("test-plan-a", "Test plan A", db_path=db_path)
        api.add_node("test-plan-b", "Test plan B", db_path=db_path)
        api.add_node("validate-x", "Validate X", db_path=db_path)
        result = api.search("test.*plan", regex=True, db_path=db_path)
        assert "test-plan-a" in result
        assert "test-plan-b" in result
        assert "validate-x" not in result

    def test_regex_case_insensitive(self, db_path):
        api.add_node("node1", "SNOWFLAKE validation", db_path=db_path)
        api.add_node("node2", "snowflake test", db_path=db_path)
        result = api.search("snowflake", regex=True, db_path=db_path)
        assert "node1" in result
        assert "node2" in result

    def test_regex_invalid_pattern_raises(self, db_path):
        api.add_node("test", "Test node", db_path=db_path)
        with pytest.raises(ValueError):
            api.search("[invalid(regex", regex=True, db_path=db_path)

    def test_regex_alternation(self, db_path):
        api.add_node("a", "ANSTRAT-2311 issue", db_path=db_path)
        api.add_node("b", "ValidX status", db_path=db_path)
        api.add_node("c", "Other thing", db_path=db_path)
        result = api.search("ANSTRAT|ValidX", regex=True, db_path=db_path)
        assert "a" in result
        assert "b" in result
        assert "c" not in result


class TestNamesOnlyFormat:

    def test_search_names_only(self, db_path):
        api.add_node("alpha", "Alpha belief", db_path=db_path)
        api.add_node("beta", "Beta belief", db_path=db_path)
        result = api.search("belief", format="names-only", db_path=db_path)
        lines = result.strip().split("\n")
        assert "alpha" in lines
        assert "beta" in lines
        assert all(":" not in line and "[" not in line for line in lines)

    def test_search_names_only_no_results(self, db_path):
        result = api.search("nonexistent", format="names-only", db_path=db_path)
        assert result == "No results found."

    def test_compact_names_only(self, db_path):
        api.add_node("node-a", "Node A text", db_path=db_path)
        api.add_node("node-b", "Node B text", db_path=db_path)
        result = api.compact(format="names-only", db_path=db_path)
        lines = result.strip().split("\n")
        assert "node-a" in lines
        assert "node-b" in lines

    def test_compact_names_only_respects_budget(self, db_path):
        for i in range(20):
            api.add_node(f"belief-{i}", f"Belief number {i}", db_path=db_path)
        result = api.compact(format="names-only", budget=10, db_path=db_path)
        lines = result.strip().split("\n")
        assert len(lines) < 20
        assert len(lines) > 0

    def test_compact_names_only_excludes_out(self, db_path):
        api.add_node("in-node", "Stays in", db_path=db_path)
        api.add_node("out-node", "Goes out", db_path=db_path)
        api.retract_node("out-node", db_path=db_path)
        result = api.compact(format="names-only", db_path=db_path)
        lines = result.strip().split("\n")
        assert "in-node" in lines
        assert "out-node" not in lines

    def test_lookup_names_only(self, db_path):
        api.add_node("gamma", "Gamma is great", db_path=db_path)
        api.add_node("delta", "Delta is great", db_path=db_path)
        result = api.lookup("great", format="names-only", db_path=db_path)
        lines = result.strip().split("\n")
        assert "gamma" in lines
        assert "delta" in lines

    def test_lookup_names_only_no_results(self, db_path):
        result = api.lookup("nonexistent", format="names-only", db_path=db_path)
        assert "No beliefs found" in result


class TestSearchPagination:

    def test_limit(self, db_path):
        for i in range(10):
            api.add_node(f"node-{i}", f"Test node {i}", db_path=db_path)
        result = api.search("node test", format="names-only", limit=3,
                            db_path=db_path)
        lines = [l for l in result.strip().split("\n") if l]
        assert len(lines) == 3

    def test_offset(self, db_path):
        for i in range(5):
            api.add_node(f"item-{i}", f"Searchable item {i}", db_path=db_path)
        all_result = api.search("item searchable", format="names-only",
                                db_path=db_path)
        offset_result = api.search("item searchable", format="names-only",
                                   offset=2, db_path=db_path)
        all_lines = all_result.strip().split("\n")
        offset_lines = offset_result.strip().split("\n")
        assert len(offset_lines) == len(all_lines) - 2

    def test_limit_and_offset(self, db_path):
        for i in range(10):
            api.add_node(f"entry-{i}", f"Entry number {i}", db_path=db_path)
        result = api.search("entry number", format="names-only", limit=3,
                            offset=2, db_path=db_path)
        lines = [l for l in result.strip().split("\n") if l]
        assert len(lines) == 3

    def test_no_limit_returns_all(self, db_path):
        for i in range(10):
            api.add_node(f"belief-{i}", f"Test belief {i}", db_path=db_path)
        result = api.search("belief test", format="names-only",
                            db_path=db_path)
        lines = [l for l in result.strip().split("\n") if l]
        assert len(lines) == 10


class TestStatusPagination:

    def test_offset(self, db_path):
        for i in range(5):
            api.add_node(f"s-{i}", f"Status node {i}", db_path=db_path)
        result_all = api.get_status(db_path=db_path)
        result_off = api.get_status(offset=2, db_path=db_path)
        assert len(result_off["nodes"]) == len(result_all["nodes"]) - 2

    def test_limit_and_offset(self, db_path):
        for i in range(10):
            api.add_node(f"p-{i}", f"Page node {i}", db_path=db_path)
        result = api.get_status(limit=3, offset=2, db_path=db_path)
        assert len(result["nodes"]) == 3
        assert result["total"] == 10


class TestNodeTags:

    def test_add_tags(self, db_path):
        api.add_node("tagged-node", "A tagged node", db_path=db_path)
        result = api.add_tags("tagged-node", ["topic:networking", "access:internal"], db_path=db_path)
        assert result["node_id"] == "tagged-node"
        assert "topic:networking" in result["tags"]
        assert "access:internal" in result["tags"]

    def test_add_tags_idempotent(self, db_path):
        api.add_node("n1", "Node", db_path=db_path)
        api.add_tags("n1", ["topic:x"], db_path=db_path)
        result = api.add_tags("n1", ["topic:x"], db_path=db_path)
        assert result["tags"].count("topic:x") == 1

    def test_add_tags_missing_node(self, db_path):
        with pytest.raises(KeyError):
            api.add_tags("nonexistent", ["topic:x"], db_path=db_path)

    def test_remove_tags(self, db_path):
        api.add_node("n2", "Node", db_path=db_path)
        api.add_tags("n2", ["topic:a", "topic:b", "topic:c"], db_path=db_path)
        result = api.remove_tags("n2", ["topic:b"], db_path=db_path)
        assert "topic:b" not in result["tags"]
        assert "topic:b" in result["removed"]
        assert "topic:a" in result["tags"]

    def test_remove_nonexistent_tag(self, db_path):
        api.add_node("n3", "Node", db_path=db_path)
        result = api.remove_tags("n3", ["topic:nope"], db_path=db_path)
        assert result["removed"] == []

    def test_get_tags(self, db_path):
        api.add_node("n4", "Node", db_path=db_path)
        api.add_tags("n4", ["access:secret", "topic:auth"], db_path=db_path)
        result = api.get_tags("n4", db_path=db_path)
        assert "access:secret" in result["tags"]
        assert "topic:auth" in result["tags"]

    def test_get_tags_empty(self, db_path):
        api.add_node("n5", "Node", db_path=db_path)
        result = api.get_tags("n5", db_path=db_path)
        assert result["tags"] == []

    def test_show_node_includes_tags(self, db_path):
        api.add_node("show-tags", "Has tags", db_path=db_path)
        api.add_tags("show-tags", ["topic:test"], db_path=db_path)
        node = api.show_node("show-tags", db_path=db_path)
        assert "tags" in node
        assert "topic:test" in node["tags"]

    def test_access_tags_migrated_on_add(self, db_path):
        api.add_node("at-node", "Access tagged", access_tags=["internal", "security"], db_path=db_path)
        result = api.get_tags("at-node", db_path=db_path)
        assert "access:internal" in result["tags"]
        assert "access:security" in result["tags"]


class TestNodeSources:

    def test_add_source(self, db_path):
        api.add_node("src-node", "Has sources", db_path=db_path)
        result = api.add_source("src-node", "repo:path/file.md", source_type="code", db_path=db_path)
        assert result["node_id"] == "src-node"
        assert result["source_id"] > 0

    def test_add_source_missing_node(self, db_path):
        with pytest.raises(KeyError):
            api.add_source("nonexistent", "repo:file.md", db_path=db_path)

    def test_add_multiple_sources(self, db_path):
        api.add_node("multi-src", "Multiple sources", db_path=db_path)
        api.add_source("multi-src", "repo:a.md", source_type="code", db_path=db_path)
        api.add_source("multi-src", "repo:b.md", source_type="document", db_path=db_path)
        node = api.show_node("multi-src", db_path=db_path)
        assert len(node["sources"]) == 2

    def test_show_node_includes_sources(self, db_path):
        api.add_node("show-src", "With source", source="repo:main.py", db_path=db_path)
        node = api.show_node("show-src", db_path=db_path)
        assert "sources" in node
        assert len(node["sources"]) >= 1
        assert node["sources"][0]["source_ref"] == "repo:main.py"
