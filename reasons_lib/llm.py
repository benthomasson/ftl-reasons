"""Shared LLM invocation via CLI subprocesses.

Supports named models (claude, gemini), Claude submodels via
'claude:<model>' syntax, and ollama models via 'ollama:<model>'
syntax. All invocations pipe prompts to stdin and read responses
from stdout.
"""

import os
import shutil
import subprocess


MODEL_COMMANDS = {
    "claude": ["claude", "-p"],
    "gemini": ["gemini", "--skip-trust", "-p", ""],
}


def resolve_model_cmd(model: str) -> list[str]:
    """Resolve a model name to a CLI command list.

    Supports named models ('claude', 'gemini'), Claude submodels
    via 'claude:<model>' (e.g. 'claude:sonnet'), Gemini submodels
    via 'gemini:<model>' (e.g. 'gemini:gemini-2.5-flash'), and
    ollama models via 'ollama:<model>' syntax (e.g. 'ollama:gemma3:4b').
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
    available = list(MODEL_COMMANDS) + ["claude:<model>", "gemini:<model>", "ollama:<model>"]
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
    output = result.stdout
    # Fragile: ollama thinking markers may change across versions
    if model.startswith("ollama:") and "Thinking...\n" in output:
        parts = output.split("...done thinking.\n", 1)
        if len(parts) == 2:
            output = parts[1]
    return output
