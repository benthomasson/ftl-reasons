"""Tests for the shared LLM invocation module."""

from unittest.mock import patch

import pytest

from reasons_lib.llm import invoke_model, resolve_model_cmd


class TestResolveModelCmd:

    def test_resolve_claude(self):
        assert resolve_model_cmd("claude") == ["claude", "-p"]

    def test_resolve_gemini(self):
        assert resolve_model_cmd("gemini") == ["gemini", "-p", ""]

    def test_resolve_ollama_model(self):
        assert resolve_model_cmd("ollama:gemma3:4b") == ["ollama", "run", "gemma3:4b"]

    def test_resolve_ollama_with_tag(self):
        assert resolve_model_cmd("ollama:qwen3.5:27b") == ["ollama", "run", "qwen3.5:27b"]

    def test_resolve_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown model"):
            resolve_model_cmd("gpt-4")


class TestInvokeModel:

    def test_missing_binary_raises(self):
        with patch("reasons_lib.llm.shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="not found in PATH"):
                invoke_model("hello", model="claude")

    def test_invokes_subprocess(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": "response", "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result) as mock_run:
            result = invoke_model("hello", model="claude", timeout=60)
            assert result == "response"
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == ["claude", "-p"]
            assert args[1]["input"] == "hello"
            assert args[1]["timeout"] == 60

    def test_nonzero_exit_raises(self):
        mock_result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "error msg"})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="claude failed"):
                invoke_model("hello", model="claude")

    def test_ollama_command(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": "ollama response", "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/ollama"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result) as mock_run:
            result = invoke_model("hello", model="ollama:gemma3:4b")
            assert result == "ollama response"
            args = mock_run.call_args
            assert args[0][0] == ["ollama", "run", "gemma3:4b"]

    def test_strips_claudecode_env(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result) as mock_run, \
             patch.dict("os.environ", {"CLAUDECODE": "1", "HOME": "/home/test"}):
            invoke_model("hello", model="claude")
            env = mock_run.call_args[1]["env"]
            assert "CLAUDECODE" not in env
            assert "HOME" in env
