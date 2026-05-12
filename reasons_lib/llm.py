"""Shared LLM invocation via CLI subprocesses and API providers.

Supports named models (claude, gemini), Claude submodels via
'claude:<model>' syntax, ollama models via 'ollama:<model>',
and API-based providers via 'api:<model>' and 'vertex:<model>'.

CLI-based models pipe prompts to stdin and read responses from stdout.
API-based models use LangChain adapters with optional Langfuse tracing.
"""

import os
import shutil
import subprocess

try:
    from langchain_anthropic import ChatAnthropic
    _HAS_LANGCHAIN_ANTHROPIC = True
except ImportError:
    ChatAnthropic = None
    _HAS_LANGCHAIN_ANTHROPIC = False

try:
    from langchain_google_vertexai.model_garden import ChatAnthropicVertex
    _HAS_LANGCHAIN_VERTEX = True
except ImportError:
    ChatAnthropicVertex = None
    _HAS_LANGCHAIN_VERTEX = False

try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    _HAS_LANGFUSE = True
except ImportError:
    LangfuseCallbackHandler = None
    _HAS_LANGFUSE = False


MODEL_COMMANDS = {
    "claude": ["claude", "-p"],
    "gemini": ["gemini", "--skip-trust", "-p", ""],
}

_langfuse_handler = None
_langfuse_checked = False


def _get_langfuse_handler():
    global _langfuse_handler, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_handler
    _langfuse_checked = True
    if not _HAS_LANGFUSE:
        return None
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return None
    _langfuse_handler = LangfuseCallbackHandler()
    return _langfuse_handler


def resolve_model_cmd(model: str) -> list[str]:
    """Resolve a model name to a CLI command list.

    Supports named models ('claude', 'gemini'), Claude submodels
    via 'claude:<model>' (e.g. 'claude:sonnet'), Gemini submodels
    via 'gemini:<model>' (e.g. 'gemini:gemini-2.5-flash'), and
    ollama models via 'ollama:<model>' syntax (e.g. 'ollama:gemma3:4b').

    API-based models ('api:<model>', 'vertex:<model>') are handled
    by _invoke_api() and should not reach this function.
    """
    if model in MODEL_COMMANDS:
        return MODEL_COMMANDS[model]
    if model.startswith("claude:"):
        submodel = model.split(":", 1)[1]
        return ["claude", "-p", "--model", submodel]
    if model.startswith("gemini:"):
        submodel = model.split(":", 1)[1]
        return ["gemini", "--skip-trust", "-m", submodel, "-p", ""]
    if model.startswith("ollama:"):
        ollama_model = model.split(":", 1)[1]
        return ["ollama", "run", ollama_model]
    available = (
        list(MODEL_COMMANDS)
        + ["claude:<model>", "gemini:<model>", "ollama:<model>",
           "api:<model>", "vertex:<model>"]
    )
    raise ValueError(f"Unknown model: {model}. Available: {available}")


def _invoke_api(prompt: str, model: str, timeout: int = 300) -> str:
    """Invoke an LLM via LangChain API adapter. Returns response text."""
    prefix, name = model.split(":", 1)

    if prefix == "api":
        if not _HAS_LANGCHAIN_ANTHROPIC:
            raise ImportError(
                "langchain-anthropic is required for api: models. "
                "Install with: pip install 'ftl-reasons[api]'"
            )
        llm = ChatAnthropic(model=name, timeout=float(timeout))
    elif prefix == "vertex":
        if not _HAS_LANGCHAIN_VERTEX:
            raise ImportError(
                "langchain-google-vertexai is required for vertex: models. "
                "Install with: pip install 'ftl-reasons[vertex]'"
            )
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT environment variable is required "
                "for vertex: models"
            )
        location = os.environ.get("GOOGLE_CLOUD_REGION", "us-east5")
        llm = ChatAnthropicVertex(
            model_name=name, project=project, location=location,
            request_timeout=float(timeout),
        )
    else:
        raise ValueError(f"Unknown API prefix: {prefix}")

    config = {}
    handler = _get_langfuse_handler()
    if handler:
        config["callbacks"] = [handler]

    try:
        response = llm.invoke(prompt, config=config)
    except Exception as exc:
        exc_name = type(exc).__name__
        if "timeout" in exc_name.lower() or "timeout" in str(exc).lower():
            raise subprocess.TimeoutExpired(model, timeout) from exc
        raise RuntimeError(f"{model} failed: {exc}") from exc

    return response.content


def invoke_model(prompt: str, model: str = "claude", timeout: int = 300) -> str:
    """Invoke an LLM via CLI subprocess or API. Returns response text.

    Raises FileNotFoundError if the model binary is not in PATH (CLI models).
    Raises ImportError if API dependencies are not installed (API models).
    Raises RuntimeError if the model exits non-zero or API call fails.
    Raises subprocess.TimeoutExpired on timeout.
    """
    if model.startswith("api:") or model.startswith("vertex:"):
        return _invoke_api(prompt, model, timeout)

    cmd = resolve_model_cmd(model)
    binary = cmd[0]
    if not shutil.which(binary):
        raise FileNotFoundError(f"'{binary}' CLI not found in PATH")

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{model} failed: {result.stderr}")
    output = result.stdout
    # Fragile: ollama thinking markers may change across versions
    if model.startswith("ollama:") and "Thinking...\n" in output:
        parts = output.split("...done thinking.\n", 1)
        if len(parts) == 2:
            output = parts[1]
    return output
