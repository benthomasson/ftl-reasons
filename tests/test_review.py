"""Tests for the review module (derived belief validation)."""

import json
import sys
from io import StringIO
from unittest.mock import patch, call

import pytest

from reasons_lib.review import (
    format_belief_for_review,
    parse_review_response,
    review_beliefs,
    REVIEW_BATCH_SIZE,
)
from reasons_lib import api
from reasons_lib.cli import main


def run_cli(*args, db_path=None):
    argv = ["reasons"]
    if db_path:
        argv += ["--db", db_path]
    argv += list(args)
    stdout, stderr = StringIO(), StringIO()
    with patch.object(sys, "argv", argv), \
         patch.object(sys, "stdout", stdout), \
         patch.object(sys, "stderr", stderr):
        try:
            main()
        except SystemExit as e:
            return stdout.getvalue(), stderr.getvalue(), e.code
    return stdout.getvalue(), stderr.getvalue(), 0


def _make_nodes():
    """Build a minimal exported nodes dict for testing."""
    return {
        "premise-a": {
            "text": "A is true",
            "truth_value": "IN",
            "justifications": [],
        },
        "premise-b": {
            "text": "B is true",
            "truth_value": "IN",
            "justifications": [],
        },
        "premise-c": {
            "text": "C is true",
            "truth_value": "IN",
            "justifications": [],
        },
        "derived-ab": {
            "text": "A and B together imply AB",
            "truth_value": "IN",
            "justifications": [{
                "type": "SL",
                "antecedents": ["premise-a", "premise-b"],
                "outlist": [],
                "label": "combined observation",
            }],
        },
        "gated-abc": {
            "text": "ABC holds unless C is present",
            "truth_value": "OUT",
            "justifications": [{
                "type": "SL",
                "antecedents": ["premise-a", "premise-b"],
                "outlist": ["premise-c"],
                "label": "gated on C",
            }],
        },
        "derived-deep": {
            "text": "Deep conclusion from AB",
            "truth_value": "IN",
            "justifications": [{
                "type": "SL",
                "antecedents": ["derived-ab", "premise-c"],
                "outlist": [],
                "label": "deeper reasoning",
            }],
        },
    }


class TestFormatBeliefForReview:

    def test_formats_belief_with_antecedents(self):
        nodes = _make_nodes()
        result = format_belief_for_review("derived-ab", nodes)
        assert "### derived-ab" in result
        assert "A and B together imply AB" in result
        assert "premise-a: A is true" in result
        assert "premise-b: B is true" in result
        assert "Label: combined observation" in result

    def test_includes_outlist(self):
        nodes = _make_nodes()
        result = format_belief_for_review("gated-abc", nodes)
        assert "Unless (must be OUT):" in result
        assert "premise-c: C is true" in result

    def test_missing_antecedent_graceful(self):
        nodes = _make_nodes()
        nodes["derived-ab"]["justifications"][0]["antecedents"] = [
            "premise-a", "nonexistent"
        ]
        result = format_belief_for_review("derived-ab", nodes)
        assert "nonexistent: (not found in network)" in result

    def test_missing_node_returns_empty(self):
        nodes = _make_nodes()
        result = format_belief_for_review("does-not-exist", nodes)
        assert result == ""

    def test_multiple_justifications(self):
        nodes = _make_nodes()
        nodes["multi-just"] = {
            "text": "Supported by two independent paths",
            "truth_value": "IN",
            "justifications": [
                {
                    "type": "SL",
                    "antecedents": ["premise-a", "premise-b"],
                    "outlist": [],
                    "label": "path one",
                },
                {
                    "type": "SL",
                    "antecedents": ["premise-c"],
                    "outlist": [],
                    "label": "path two",
                },
            ],
        }
        result = format_belief_for_review("multi-just", nodes)
        assert "Justification 1/2:" in result
        assert "Justification 2/2:" in result
        assert "premise-a: A is true" in result
        assert "premise-c: C is true" in result
        assert "Label: path one" in result
        assert "Label: path two" in result

    def test_single_justification_no_numbering(self):
        nodes = _make_nodes()
        result = format_belief_for_review("derived-ab", nodes)
        assert "Justification 1/" not in result

    def test_no_justifications(self):
        nodes = _make_nodes()
        result = format_belief_for_review("premise-a", nodes)
        assert "### premise-a" in result
        assert "Antecedents:" not in result


class TestParseReviewResponse:

    def test_parses_valid_json(self):
        response = json.dumps([{
            "id": "derived-ab",
            "valid": True,
            "sufficient": True,
            "necessary": False,
            "unnecessary_antecedents": ["premise-b"],
            "comment": "premise-b is redundant",
        }])
        results = parse_review_response(response)
        assert len(results) == 1
        assert results[0]["id"] == "derived-ab"
        assert results[0]["valid"] is True
        assert results[0]["necessary"] is False
        assert results[0]["unnecessary_antecedents"] == ["premise-b"]

    def test_extracts_from_surrounding_prose(self):
        response = (
            "Here are my findings:\n\n"
            '[{"id": "derived-ab", "valid": false, "sufficient": true, '
            '"necessary": true, "unnecessary_antecedents": [], '
            '"comment": "conclusion does not follow"}]\n\n'
            "Hope this helps!"
        )
        results = parse_review_response(response)
        assert len(results) == 1
        assert results[0]["valid"] is False

    def test_malformed_json_returns_empty(self):
        response = "This is not JSON at all."
        results = parse_review_response(response)
        assert results == []

    def test_missing_fields_get_defaults(self):
        response = json.dumps([{"id": "derived-ab"}])
        results = parse_review_response(response)
        assert len(results) == 1
        assert results[0]["valid"] is True
        assert results[0]["sufficient"] is True
        assert results[0]["necessary"] is True
        assert results[0]["unnecessary_antecedents"] == []
        assert results[0]["comment"] == ""

    def test_skips_items_without_id(self):
        response = json.dumps([
            {"valid": True},
            {"id": "derived-ab", "valid": False},
        ])
        results = parse_review_response(response)
        assert len(results) == 1
        assert results[0]["id"] == "derived-ab"

    def test_prose_brackets_before_json(self):
        response = (
            "I checked [see antecedents] and [the outlist] carefully.\n\n"
            '[{"id": "derived-ab", "valid": false, "sufficient": true, '
            '"necessary": true, "unnecessary_antecedents": [], '
            '"comment": "does not follow"}]'
        )
        results = parse_review_response(response)
        assert len(results) == 1
        assert results[0]["id"] == "derived-ab"
        assert results[0]["valid"] is False

    def test_non_list_json_skipped(self):
        response = '{"id": "derived-ab", "valid": true}'
        results = parse_review_response(response)
        assert results == []


class TestReviewBeliefs:

    def test_reviews_batch(self):
        nodes = _make_nodes()
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            results = review_beliefs(nodes, belief_ids=["derived-ab"], model="claude")
        assert len(results) == 1
        assert results[0]["id"] == "derived-ab"

    def test_empty_derived_returns_empty(self):
        nodes = {
            "premise-a": {
                "text": "A is true",
                "truth_value": "IN",
                "justifications": [],
            },
        }
        results = review_beliefs(nodes)
        assert results == []

    def test_filters_to_existing_ids(self):
        nodes = _make_nodes()
        mock_response = json.dumps([])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            results = review_beliefs(nodes, belief_ids=["nonexistent"])
        assert results == []

    def test_batch_size_respected(self):
        nodes = _make_nodes()
        # derived-ab and derived-deep are the only derived IN beliefs
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result) as mock_run:
            results = review_beliefs(nodes, batch_size=1)
        # 2 derived IN beliefs (derived-ab, derived-deep) = 2 batches
        assert mock_run.call_count == 2

    def test_timeout_passed_through(self):
        nodes = _make_nodes()
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result) as mock_run:
            review_beliefs(nodes, belief_ids=["derived-ab"], timeout=600)
        assert mock_run.call_args[1]["timeout"] == 600

    def test_llm_error_continues(self):
        nodes = _make_nodes()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", side_effect=RuntimeError("LLM failed")):
            results = review_beliefs(nodes, belief_ids=["derived-ab"])
        assert results == []


class TestReviewBeliefsApi:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("premise-a", "A is true", db_path=db)
        api.add_node("premise-b", "B is true", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="premise-a,premise-b",
                      label="combined", db_path=db)
        api.add_node("premise-c", "C is true", db_path=db)
        api.add_node("derived-abc", "ABC combined",
                      sl="derived-ab,premise-c", label="deeper", db_path=db)
        return db

    def test_filters_to_derived_only(self, db_path):
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
            {"id": "derived-abc", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = api.review_beliefs(db_path=db_path)
        assert result["reviewed"] == 2
        assert result["total_derived"] == 2

    def test_min_depth_filter(self, db_path):
        mock_response = json.dumps([
            {"id": "derived-abc", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = api.review_beliefs(min_depth=2, db_path=db_path)
        # derived-abc is depth 2 (depends on derived-ab which is depth 1)
        assert result["reviewed"] == 1

    def test_sample_limits_count(self, db_path):
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = api.review_beliefs(sample=1, db_path=db_path)
        assert result["reviewed"] == 1

    def test_depends_on_filter(self, db_path):
        mock_response = json.dumps([
            {"id": "derived-abc", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = api.review_beliefs(depends_on="derived-ab", db_path=db_path)
        # Only derived-abc depends on derived-ab
        assert result["reviewed"] == 1

    def test_returns_summary_counts(self, db_path):
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": False, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "invalid"},
            {"id": "derived-abc", "valid": True, "sufficient": False,
             "necessary": False, "unnecessary_antecedents": ["premise-c"],
             "comment": "insufficient and unnecessary"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = api.review_beliefs(db_path=db_path)
        assert result["invalid"] == 1
        assert result["insufficient"] == 1
        assert result["unnecessary"] == 1

    def test_visible_to_filter(self, db_path):
        api.add_node("tagged-derived", "tagged belief",
                      sl="premise-a,premise-b", label="tagged",
                      access_tags=["secret"],
                      db_path=db_path)
        mock_response = json.dumps([
            {"id": "derived-ab", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
            {"id": "derived-abc", "valid": True, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [], "comment": "ok"},
        ])
        mock_result = type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = api.review_beliefs(visible_to=["public"], db_path=db_path)
        # tagged-derived requires "secret" tag, so excluded; only 2 untagged derived remain
        assert result["reviewed"] == 2


class TestCmdReviewBeliefs:

    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        api.add_node("premise-a", "A is true", db_path=db)
        api.add_node("premise-b", "B is true", db_path=db)
        api.add_node("derived-ab", "AB combined", sl="premise-a,premise-b",
                      label="combined", db_path=db)
        return db

    def _mock_review(self, response_data):
        mock_response = json.dumps(response_data)
        return type("R", (), {"returncode": 0, "stdout": mock_response, "stderr": ""})()

    def test_auto_retract_retracts_invalid(self, db_path):
        mock_result = self._mock_review([
            {"id": "derived-ab", "valid": False, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [],
             "comment": "conclusion does not follow"},
        ])
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            stdout, stderr, code = run_cli(
                "review-beliefs", "--auto-retract", db_path=db_path)
        assert "RETRACTED derived-ab" in stdout
        # Verify it was actually retracted in the DB
        result = api.show_node("derived-ab", db_path=db_path)
        assert result["truth_value"] == "OUT"

    def test_dry_run_prevents_retraction(self, db_path):
        mock_result = self._mock_review([
            {"id": "derived-ab", "valid": False, "sufficient": True,
             "necessary": True, "unnecessary_antecedents": [],
             "comment": "conclusion does not follow"},
        ])
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            stdout, stderr, code = run_cli(
                "review-beliefs", "--auto-retract", "--dry-run", db_path=db_path)
        assert "RETRACTED" not in stdout
        # Verify it was NOT retracted
        result = api.show_node("derived-ab", db_path=db_path)
        assert result["truth_value"] == "IN"

    def test_output_writes_findings_file(self, db_path, tmp_path):
        output_file = str(tmp_path / "findings.md")
        mock_result = self._mock_review([
            {"id": "derived-ab", "valid": False, "sufficient": True,
             "necessary": False, "unnecessary_antecedents": ["premise-b"],
             "comment": "not valid and unnecessary antecedent"},
        ])
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            stdout, stderr, code = run_cli(
                "review-beliefs", "-o", output_file, db_path=db_path)
        assert f"Wrote findings to {output_file}" in stdout
        with open(output_file) as f:
            content = f.read()
        assert "# Belief Review Findings" in content
        assert "### derived-ab" in content
        assert "- Valid: FAIL" in content
        assert "- Sufficient: PASS" in content
        assert "- Necessary: FAIL" in content
        assert "- Unnecessary antecedents: premise-b" in content
        assert "- Comment: not valid and unnecessary antecedent" in content

    def test_displays_flags_for_issues(self, db_path):
        mock_result = self._mock_review([
            {"id": "derived-ab", "valid": False, "sufficient": False,
             "necessary": False, "unnecessary_antecedents": ["premise-a"],
             "comment": "all three axes fail"},
        ])
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            stdout, stderr, code = run_cli(
                "review-beliefs", "--dry-run", db_path=db_path)
        assert "INVALID" in stdout
        assert "INSUFFICIENT" in stdout
        assert "UNNECESSARY(premise-a)" in stdout
        assert "all three axes fail" in stdout

    def test_no_derived_beliefs_message(self, tmp_path):
        db = str(tmp_path / "empty.db")
        api.add_node("just-a-premise", "simple fact", db_path=db)
        stdout, stderr, code = run_cli("review-beliefs", db_path=db)
        assert "No derived beliefs to review." in stdout
