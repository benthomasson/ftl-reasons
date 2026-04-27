"""Tests for the ask module (FTS5 search + LLM synthesis)."""

import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from reasons_lib.ask import extract_tool_call, build_ask_prompt, ask, _invoke_claude
from reasons_lib.cli import main


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


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


class TestExtractToolCall:

    def test_valid_tool_call(self):
        text = 'Some preamble text\n{"tool": "search_beliefs", "query": "propagation"}\nMore text'
        result = extract_tool_call(text)
        assert result == {"tool": "search_beliefs", "query": "propagation"}

    def test_no_tool_call(self):
        text = "This is just a plain answer with no JSON."
        result = extract_tool_call(text)
        assert result is None

    def test_json_without_tool_key(self):
        text = '{"name": "test", "value": 42}'
        result = extract_tool_call(text)
        assert result is None

    def test_malformed_json_skipped(self):
        text = '{bad json}\n{"tool": "search_beliefs", "query": "test"}'
        result = extract_tool_call(text)
        assert result == {"tool": "search_beliefs", "query": "test"}

    def test_first_tool_call_wins(self):
        text = '{"tool": "search_beliefs", "query": "first"}\n{"tool": "search_beliefs", "query": "second"}'
        result = extract_tool_call(text)
        assert result["query"] == "first"

    def test_non_json_lines_skipped(self):
        text = "Hello\nWorld\n  not json\n"
        result = extract_tool_call(text)
        assert result is None

    def test_empty_string(self):
        result = extract_tool_call("")
        assert result is None


class TestBuildAskPrompt:

    def test_contains_question_and_context(self):
        prompt = build_ask_prompt("What is BFS?", "Some belief context")
        assert "What is BFS?" in prompt
        assert "Some belief context" in prompt

    def test_no_tool_history(self):
        prompt = build_ask_prompt("question", "context")
        assert "Additional search results" not in prompt

    def test_with_tool_history(self):
        history = [
            {"query": "propagation", "result": "Found: propagation-is-bfs"},
            {"query": "retraction", "result": "Found: retraction-cascades"},
        ]
        prompt = build_ask_prompt("question", "context", tool_history=history)
        assert "Additional search results" in prompt
        assert "propagation" in prompt
        assert "retraction" in prompt

    def test_tool_definition_in_prompt(self):
        prompt = build_ask_prompt("question", "context")
        assert "search_beliefs" in prompt
        assert '"tool"' in prompt


class TestAskNoSynth:

    def test_no_synth_returns_search_results(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "prop-bfs", "Propagation uses breadth-first search", db_path=db_path)
        run_cli("add", "prop-cascade", "Propagation cascades through dependents", db_path=db_path)

        result = ask("propagation", db_path=db_path, no_synth=True)
        assert "prop-bfs" in result or "prop-cascade" in result

    def test_no_synth_no_results(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "alpha", "Alpha belief", db_path=db_path)

        result = ask("zzzznonexistent", db_path=db_path, no_synth=True)
        assert "No results" in result


class TestCmdAskNoSynth:

    def test_cli_ask_no_synth(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "test-belief", "The system uses BFS for propagation", db_path=db_path)
        out, err, code = run_cli("ask", "BFS propagation", "--no-synth", db_path=db_path)
        assert code == 0
        assert "test-belief" in out

    def test_cli_ask_no_synth_no_results(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("ask", "nothing matches", "--no-synth", db_path=db_path)
        assert code == 0
        assert "No results" in out


class TestInvokeClaude:

    def test_claude_not_in_path(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="claude"):
                _invoke_claude("test prompt")


class TestAskWithMockedLLM:

    def test_direct_answer(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Alpha belief", db_path=db_path)

        with patch("reasons_lib.ask._invoke_claude", return_value="The answer is alpha."):
            result = ask("what is alpha?", db_path=db_path)
        assert result == "The answer is alpha."

    def test_tool_call_then_answer(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Alpha belief", db_path=db_path)
        run_cli("add", "b", "Beta belief about retraction", db_path=db_path)

        responses = [
            '{"tool": "search_beliefs", "query": "retraction"}',
            "Retraction cascades through dependents [b].",
        ]
        call_count = [0]

        def mock_invoke(prompt, timeout=300):
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx]

        with patch("reasons_lib.ask._invoke_claude", side_effect=mock_invoke):
            result = ask("how does retraction work?", db_path=db_path)
        assert "retraction" in result.lower() or "Retraction" in result
        assert call_count[0] == 2

    def test_max_iterations_forces_answer(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Alpha", db_path=db_path)

        def always_tool_call(prompt, timeout=300):
            return '{"tool": "search_beliefs", "query": "more"}'

        with patch("reasons_lib.ask._invoke_claude", side_effect=always_tool_call):
            result = ask("question", db_path=db_path)
        assert "search_beliefs" in result

    def test_timeout_returns_search_results(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Alpha belief", db_path=db_path)

        with patch("reasons_lib.ask._invoke_claude",
                    side_effect=subprocess.TimeoutExpired("claude", 300)):
            result = ask("alpha", db_path=db_path)
        assert "a" in result

    def test_error_returns_search_results(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Alpha belief", db_path=db_path)

        with patch("reasons_lib.ask._invoke_claude",
                    side_effect=RuntimeError("claude crashed")):
            result = ask("alpha", db_path=db_path)
        assert "a" in result

    def test_unknown_tool_returns_response(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Alpha", db_path=db_path)

        with patch("reasons_lib.ask._invoke_claude",
                    return_value='{"tool": "unknown_tool", "query": "x"}'):
            result = ask("question", db_path=db_path)
        assert "unknown_tool" in result
