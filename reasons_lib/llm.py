"""Shared LLM invocation via CLI subprocesses.

Supports named models (claude, gemini) and ollama models via
'ollama:<model>' syntax. All invocations pipe prompts to stdin
and read responses from stdout.
"""

import os
import shutil
import subprocess


MODEL_COMMANDS = {
    "claude": ["claude", "-p"],
    "gemini": ["gemini", "-p", ""],
}


def resolve_model_cmd(model: str) -> list[str]:
    """Resolve a model name to a CLI command list.

    Supports named models ('claude', 'gemini') and ollama models
    via 'ollama:<model>' syntax (e.g. 'ollama:gemma3:4b').
    """
    if model in MODEL_COMMANDS:
        return MODEL_COMMANDS[model]
    if model.startswith("ollama:"):
        ollama_model = model.split(":", 1)[1]
        return ["ollama", "run", ollama_model]
    available = list(MODEL_COMMANDS) + ["ollama:<model>"]
    raise ValueError(f"Unknown model: {model}. Available: {available}")


def invoke_model(prompt: str, model: str = "claude", timeout: int = 300) -> str:
    """Invoke an LLM via CLI subprocess. Returns response text.

    Raises FileNotFoundError if the model binary is not in PATH.
    Raises RuntimeError if the model exits non-zero.
    Raises subprocess.TimeoutExpired on timeout.
    """
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
    return result.stdout
