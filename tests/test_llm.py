"""Tests for the shared LLM invocation module."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import reasons_lib.llm as llm_module
from reasons_lib.llm import (
    _get_langfuse_handler,
    _invoke_api,
    invoke_model,
    resolve_model_cmd,
)


class TestResolveModelCmd:

    def test_resolve_claude(self):
        assert resolve_model_cmd("claude") == ["claude", "-p"]

    def test_resolve_gemini(self):
        assert resolve_model_cmd("gemini") == ["gemini", "--skip-trust", "-p", ""]

    def test_resolve_gemini_submodel(self):
        assert resolve_model_cmd("gemini:gemini-2.5-flash") == [
            "gemini", "--skip-trust", "-m", "gemini-2.5-flash", "-p", ""
        ]

    def test_resolve_gemini_submodel_short(self):
        assert resolve_model_cmd("gemini:flash") == [
            "gemini", "--skip-trust", "-m", "flash", "-p", ""
        ]

    def test_resolve_ollama_model(self):
        assert resolve_model_cmd("ollama:gemma3:4b") == ["ollama", "run", "gemma3:4b"]

    def test_resolve_ollama_with_tag(self):
        assert resolve_model_cmd("ollama:qwen3.5:27b") == ["ollama", "run", "qwen3.5:27b"]

    def test_resolve_claude_submodel(self):
        assert resolve_model_cmd("claude:sonnet") == ["claude", "-p", "--model", "sonnet"]

    def test_resolve_claude_submodel_full_name(self):
        assert resolve_model_cmd("claude:claude-sonnet-4-6") == ["claude", "-p", "--model", "claude-sonnet-4-6"]

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

    def test_ollama_strips_thinking_output(self):
        thinking = "Thinking...\nsome internal reasoning\n...done thinking.\nThe actual answer."
        mock_result = type("Result", (), {"returncode": 0, "stdout": thinking, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/ollama"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = invoke_model("hello", model="ollama:qwen3:4b")
            assert result == "The actual answer."

    def test_ollama_no_thinking_markers_unchanged(self):
        output = "Just a normal response."
        mock_result = type("Result", (), {"returncode": 0, "stdout": output, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/ollama"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = invoke_model("hello", model="ollama:qwen3:4b")
            assert result == "Just a normal response."

    def test_ollama_incomplete_thinking_unchanged(self):
        output = "Thinking...\nsome reasoning but no end marker"
        mock_result = type("Result", (), {"returncode": 0, "stdout": output, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/ollama"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = invoke_model("hello", model="ollama:qwen3:4b")
            assert result == output

    def test_claude_does_not_strip_thinking(self):
        output = "Thinking...\nsome reasoning\n...done thinking.\nAnswer."
        mock_result = type("Result", (), {"returncode": 0, "stdout": output, "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = invoke_model("hello", model="claude")
            assert result == output

    def test_strips_claudecode_env(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result) as mock_run, \
             patch.dict("os.environ", {"CLAUDECODE": "1", "HOME": "/home/test"}):
            invoke_model("hello", model="claude")
            env = mock_run.call_args[1]["env"]
            assert "CLAUDECODE" not in env
            assert "HOME" in env


class TestResolveModelCmdApiModels:

    def test_api_prefix_not_in_resolve(self):
        with pytest.raises(ValueError, match="Unknown model"):
            resolve_model_cmd("api:claude-sonnet-4-20250514")

    def test_vertex_prefix_not_in_resolve(self):
        with pytest.raises(ValueError, match="Unknown model"):
            resolve_model_cmd("vertex:claude-sonnet-4-20250514")

    def test_error_message_lists_api_models(self):
        with pytest.raises(ValueError, match="api:<model>"):
            resolve_model_cmd("gpt-4")
        with pytest.raises(ValueError, match="vertex:<model>"):
            resolve_model_cmd("gpt-4")


class TestInvokeModelApiDispatch:

    def test_api_prefix_dispatches(self):
        with patch("reasons_lib.llm._invoke_api", return_value="api response") as mock:
            result = invoke_model("hello", model="api:claude-sonnet-4-20250514")
            assert result == "api response"
            mock.assert_called_once_with("hello", "api:claude-sonnet-4-20250514", 300)

    def test_vertex_prefix_dispatches(self):
        with patch("reasons_lib.llm._invoke_api", return_value="vertex response") as mock:
            result = invoke_model("hello", model="vertex:claude-sonnet-4-20250514", timeout=60)
            assert result == "vertex response"
            mock.assert_called_once_with("hello", "vertex:claude-sonnet-4-20250514", 60)

    def test_claude_still_uses_subprocess(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": "cli response", "stderr": ""})()
        with patch("reasons_lib.llm.shutil.which", return_value="/usr/bin/claude"), \
             patch("reasons_lib.llm.subprocess.run", return_value=mock_result):
            result = invoke_model("hello", model="claude")
            assert result == "cli response"


class TestInvokeApi:

    def test_api_invokes_chat_anthropic(self):
        mock_response = MagicMock()
        mock_response.content = "test response"
        mock_model = MagicMock()
        mock_model.invoke.return_value = mock_response

        with patch.object(llm_module, "_HAS_LANGCHAIN_ANTHROPIC", True), \
             patch.object(llm_module, "ChatAnthropic", return_value=mock_model) as MockChat, \
             patch.object(llm_module, "_langfuse_checked", True), \
             patch.object(llm_module, "_langfuse_handler", None):
            result = _invoke_api("hello", "api:claude-sonnet-4-20250514", timeout=120)

        assert result == "test response"
        MockChat.assert_called_once_with(model="claude-sonnet-4-20250514", timeout=120.0)
        mock_model.invoke.assert_called_once_with("hello", config={})

    def test_vertex_invokes_chat_anthropic_vertex(self):
        mock_response = MagicMock()
        mock_response.content = "vertex response"
        mock_model = MagicMock()
        mock_model.invoke.return_value = mock_response

        with patch.object(llm_module, "_HAS_LANGCHAIN_VERTEX", True), \
             patch.object(llm_module, "ChatAnthropicVertex", return_value=mock_model) as MockChat, \
             patch.object(llm_module, "_langfuse_checked", True), \
             patch.object(llm_module, "_langfuse_handler", None), \
             patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-proj", "GOOGLE_CLOUD_REGION": "us-west1"}):
            result = _invoke_api("hello", "vertex:claude-sonnet-4-20250514", timeout=60)

        assert result == "vertex response"
        MockChat.assert_called_once_with(
            model_name="claude-sonnet-4-20250514",
            project="my-proj", location="us-west1",
            request_timeout=60.0,
        )

    def test_vertex_default_region(self):
        mock_response = MagicMock()
        mock_response.content = "ok"
        mock_model = MagicMock()
        mock_model.invoke.return_value = mock_response

        with patch.object(llm_module, "_HAS_LANGCHAIN_VERTEX", True), \
             patch.object(llm_module, "ChatAnthropicVertex", return_value=mock_model) as MockChat, \
             patch.object(llm_module, "_langfuse_checked", True), \
             patch.object(llm_module, "_langfuse_handler", None), \
             patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-proj"}, clear=False):
            os_env = dict(**os.environ)
            os_env.pop("GOOGLE_CLOUD_REGION", None)
            with patch.dict("os.environ", os_env, clear=True):
                _invoke_api("hello", "vertex:claude-sonnet-4-20250514")

        assert MockChat.call_args[1]["location"] == "us-east5"

    def test_api_missing_dep_raises(self):
        with patch.object(llm_module, "_HAS_LANGCHAIN_ANTHROPIC", False):
            with pytest.raises(ImportError, match="langchain-anthropic"):
                _invoke_api("hello", "api:claude-sonnet-4-20250514")

    def test_vertex_missing_dep_raises(self):
        with patch.object(llm_module, "_HAS_LANGCHAIN_VERTEX", False):
            with pytest.raises(ImportError, match="langchain-google-vertexai"):
                _invoke_api("hello", "vertex:claude-sonnet-4-20250514")

    def test_vertex_missing_project_raises(self):
        with patch.object(llm_module, "_HAS_LANGCHAIN_VERTEX", True), \
             patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
                _invoke_api("hello", "vertex:claude-sonnet-4-20250514")

    def test_timeout_reraises_as_timeout_expired(self):
        mock_model = MagicMock()
        mock_model.invoke.side_effect = Exception("Request timed out timeout")

        with patch.object(llm_module, "_HAS_LANGCHAIN_ANTHROPIC", True), \
             patch.object(llm_module, "ChatAnthropic", return_value=mock_model), \
             patch.object(llm_module, "_langfuse_checked", True), \
             patch.object(llm_module, "_langfuse_handler", None):
            with pytest.raises(subprocess.TimeoutExpired):
                _invoke_api("hello", "api:claude-sonnet-4-20250514", timeout=30)

    def test_api_error_reraises_as_runtime_error(self):
        mock_model = MagicMock()
        mock_model.invoke.side_effect = Exception("Authentication failed")

        with patch.object(llm_module, "_HAS_LANGCHAIN_ANTHROPIC", True), \
             patch.object(llm_module, "ChatAnthropic", return_value=mock_model), \
             patch.object(llm_module, "_langfuse_checked", True), \
             patch.object(llm_module, "_langfuse_handler", None):
            with pytest.raises(RuntimeError, match="api:claude-sonnet-4-20250514 failed"):
                _invoke_api("hello", "api:claude-sonnet-4-20250514")

    def test_unknown_prefix_raises(self):
        with pytest.raises(ValueError, match="Unknown API prefix"):
            _invoke_api("hello", "openai:gpt-4")


class TestLangfuseHandler:

    def setup_method(self):
        llm_module._langfuse_handler = None
        llm_module._langfuse_checked = False

    def teardown_method(self):
        llm_module._langfuse_handler = None
        llm_module._langfuse_checked = False

    def test_handler_created_when_env_set(self):
        mock_handler = MagicMock()
        with patch.object(llm_module, "_HAS_LANGFUSE", True), \
             patch.object(llm_module, "LangfuseCallbackHandler", return_value=mock_handler), \
             patch.dict("os.environ", {"LANGFUSE_PUBLIC_KEY": "pk-test"}):
            result = _get_langfuse_handler()
            assert result is mock_handler

    def test_handler_none_when_env_missing(self):
        with patch.object(llm_module, "_HAS_LANGFUSE", True), \
             patch.dict("os.environ", {}, clear=True):
            result = _get_langfuse_handler()
            assert result is None

    def test_handler_none_when_dep_missing(self):
        with patch.object(llm_module, "_HAS_LANGFUSE", False), \
             patch.dict("os.environ", {"LANGFUSE_PUBLIC_KEY": "pk-test"}):
            result = _get_langfuse_handler()
            assert result is None

    def test_handler_singleton(self):
        mock_handler = MagicMock()
        with patch.object(llm_module, "_HAS_LANGFUSE", True), \
             patch.object(llm_module, "LangfuseCallbackHandler", return_value=mock_handler) as MockCB, \
             patch.dict("os.environ", {"LANGFUSE_PUBLIC_KEY": "pk-test"}):
            first = _get_langfuse_handler()
            second = _get_langfuse_handler()
            assert first is second
            MockCB.assert_called_once()

    def test_langfuse_callback_passed_to_invoke(self):
        mock_handler = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "traced response"
        mock_model = MagicMock()
        mock_model.invoke.return_value = mock_response

        with patch.object(llm_module, "_HAS_LANGCHAIN_ANTHROPIC", True), \
             patch.object(llm_module, "ChatAnthropic", return_value=mock_model), \
             patch.object(llm_module, "_langfuse_checked", True), \
             patch.object(llm_module, "_langfuse_handler", mock_handler):
            result = _invoke_api("hello", "api:claude-sonnet-4-20250514")

        assert result == "traced response"
        call_config = mock_model.invoke.call_args[1]["config"]
        assert call_config["callbacks"] == [mock_handler]
