"""Ask natural language questions against a belief network.

Uses FTS5 search to find relevant beliefs, then optionally synthesizes
an answer via `claude -p` with a tool loop that allows the LLM to
request additional belief searches.
"""

import json
import os
import shutil
import subprocess
import sys

from . import api


ASK_PROMPT = """\
You are answering a question using a belief network (a Truth Maintenance System).
Each belief has an ID, text, truth value (IN = held true, OUT = retracted), and
may have justifications tracing why it is believed.

You have one tool available:

{{"tool": "search_beliefs", "query": "search terms"}}

Rules:
- If the belief matches below are sufficient to answer the question, write your
  answer directly. Do NOT call the tool.
- If you need to search for more beliefs, respond with ONLY a single JSON line
  (no other text). The system will run the search and give you the results.
- Cite belief IDs in [brackets] when referencing specific beliefs.
- If the beliefs are insufficient to answer, say so honestly.

## Question

{question}

## Belief matches

{beliefs_context}
{tool_history}"""


FINAL_TURN_INSTRUCTION = (
    "\n\n**Final turn — write your answer now, no more tool calls.**"
)


def extract_tool_call(text):
    """Extract a tool call from LLM response text.

    Scans each line for valid JSON with a "tool" key.
    Returns the parsed dict or None.
    """
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def build_ask_prompt(question, beliefs_context, tool_history=None):
    """Build the full prompt for LLM synthesis."""
    history_section = ""
    if tool_history:
        parts = []
        for entry in tool_history:
            parts.append(
                f"### Tool call: search_beliefs(\"{entry['query']}\")\n\n"
                f"{entry['result']}"
            )
        history_section = "\n\n## Additional search results\n\n" + "\n\n---\n\n".join(parts)

    return ASK_PROMPT.format(
        question=question,
        beliefs_context=beliefs_context,
        tool_history=history_section,
    )


def _invoke_claude(prompt, timeout=300):
    """Call `claude -p` with the given prompt. Returns response text.

    Raises FileNotFoundError if claude is not in PATH.
    Raises RuntimeError if claude exits non-zero.
    Raises subprocess.TimeoutExpired on timeout.
    """
    if not shutil.which("claude"):
        raise FileNotFoundError("'claude' CLI not found in PATH")

    # Strip CLAUDECODE to avoid recursive invocation inside Claude Code
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    result = subprocess.run(
        ["claude", "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude failed: {result.stderr}")
    return result.stdout


MAX_ITERATIONS = 3


def ask(question, db_path="reasons.db", timeout=300, no_synth=False):
    """Answer a question using FTS5 belief search and optional LLM synthesis.

    Returns the answer text.
    """
    beliefs_context = api.search(question, db_path=db_path, format="markdown")

    if no_synth:
        return beliefs_context

    tool_history = []

    for iteration in range(MAX_ITERATIONS):
        prompt = build_ask_prompt(question, beliefs_context, tool_history)

        if iteration == MAX_ITERATIONS - 1:
            prompt += FINAL_TURN_INSTRUCTION

        print(f"Synthesizing (round {iteration + 1}/{MAX_ITERATIONS})...",
              file=sys.stderr)

        try:
            response = _invoke_claude(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"LLM timed out after {timeout}s", file=sys.stderr)
            return beliefs_context
        except Exception as e:
            print(f"LLM error: {e}", file=sys.stderr)
            return beliefs_context

        tool_call = extract_tool_call(response)

        if tool_call is None or iteration == MAX_ITERATIONS - 1:
            return response.strip()

        if tool_call.get("tool") == "search_beliefs":
            query = tool_call.get("query", "")
            print(f"  Searching: {query}", file=sys.stderr)
            result = api.search(query, db_path=db_path, format="markdown")
            tool_history.append({"query": query, "result": result})
        else:
            return response.strip()

    return beliefs_context
