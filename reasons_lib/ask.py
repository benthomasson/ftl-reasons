"""Ask natural language questions against a belief network.

Uses FTS5 search to find relevant beliefs, then optionally synthesizes
an answer via an LLM with a tool loop that allows the model to
request additional belief searches.
"""

import json
import re
import sqlite3
import subprocess
import sys

from . import api
from .llm import invoke_model


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
- ONLY answer based on the beliefs provided. Do NOT use your training data or
  general knowledge to fill gaps.
- If the beliefs are insufficient to answer, respond EXACTLY with:
  "I don't have enough beliefs in the network to answer this question."
  Do NOT attempt a partial or speculative answer.

## Question

{question}

## Belief matches

{beliefs_context}
{tool_history}"""


FINAL_ASK_PROMPT = """\
You are answering a question using a belief network (a Truth Maintenance System).
Each belief has an ID, text, truth value (IN = held true, OUT = retracted), and
may have justifications tracing why it is believed.

Rules:
- Cite belief IDs in [brackets] when referencing specific beliefs.
- ONLY answer based on the beliefs provided. Do NOT use your training data or
  general knowledge to fill gaps.
- If the beliefs are insufficient to answer, respond EXACTLY with:
  "I don't have enough beliefs in the network to answer this question."
  Do NOT attempt a partial or speculative answer.
- Write your answer now.

## Question

{question}

## Belief matches

{beliefs_context}
{tool_history}"""


SIMPLE_ASK_PROMPT = """\
You are answering a question using a belief network (a Truth Maintenance System).
Each belief has an ID, text, truth value (IN = held true, OUT = retracted), and
may have justifications tracing why it is believed.

Rules:
- Cite belief IDs in [brackets] when referencing specific beliefs.
- ONLY answer based on the beliefs provided. Do NOT use your training data or
  general knowledge to fill gaps.
- If the beliefs are insufficient to answer, respond EXACTLY with:
  "I don't have enough beliefs in the network to answer this question."
  Do NOT attempt a partial or speculative answer.

## Question

{question}

## Belief matches

{beliefs_context}"""


def build_simple_prompt(question, beliefs_context):
    """Build prompt for simple single-pass synthesis — no tool definitions."""
    return SIMPLE_ASK_PROMPT.format(
        question=question,
        beliefs_context=beliefs_context,
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


def build_final_prompt(question, beliefs_context, tool_history=None):
    """Build prompt for final synthesis — no tool definition."""
    history_section = ""
    if tool_history:
        parts = []
        for entry in tool_history:
            parts.append(
                f"### Tool call: search_beliefs(\"{entry['query']}\")\n\n"
                f"{entry['result']}"
            )
        history_section = "\n\n## Additional search results\n\n" + "\n\n---\n\n".join(parts)

    return FINAL_ASK_PROMPT.format(
        question=question,
        beliefs_context=beliefs_context,
        tool_history=history_section,
    )


def _invoke_claude(prompt, timeout=300):
    """Call the default LLM (claude). Backward-compat wrapper."""
    return invoke_model(prompt, model="claude", timeout=timeout)


def _strip_belief_metadata(beliefs_context):
    """Strip IDs, status markers, and justification metadata from belief context.

    Converts structured belief format to plain natural language paragraphs.
    """
    if not beliefs_context:
        return beliefs_context
    lines = beliefs_context.split("\n")
    out = []
    for line in lines:
        if line.startswith("### "):
            continue
        if line.startswith("**Status:**"):
            continue
        if line.startswith("**Source:**"):
            continue
        if line.startswith("**Depends on:**"):
            continue
        if line.startswith("**Justification:**"):
            continue
        if line.startswith("**Supported by:**"):
            continue
        if line.startswith("**Supports:**"):
            continue
        out.append(line)
    result = "\n".join(out).strip()
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result


def _search_source_chunks(question, sources_db, top_k=10):
    """Search FTS5 index of source document chunks."""
    words = re.findall(r'\w+', question)
    words = [w for w in words if len(w) > 1]
    if not words:
        return ""
    fts_query = " OR ".join(f'"{w}"' for w in words)

    try:
        conn = sqlite3.connect(sources_db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT c.text, c.cluster, c.filename, c.section
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY chunks_fts.rank
            LIMIT ?
        """, (fts_query, top_k))
        rows = cur.fetchall()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return ""

    if not rows:
        return ""

    parts = []
    for i, row in enumerate(rows, 1):
        header = f"[{i}] {row['filename']}"
        if row["section"]:
            header += f" > {row['section']}"
        parts.append(f"### {header}\n\n{row['text']}")
    return "\n\n---\n\n".join(parts)


MAX_ITERATIONS = 3

NO_BELIEFS_MSG = "No matching beliefs found. Cannot answer from the belief network."


def _beliefs_or_no_match(beliefs_context):
    if not beliefs_context or beliefs_context.strip() == "No results found.":
        return NO_BELIEFS_MSG
    return beliefs_context


def ask(question, db_path="reasons.db", timeout=300, no_synth=False, format=None,
        model="claude", simple=False, sources_db=None, natural=False):
    """Answer a question using FTS5 belief search and optional LLM synthesis.

    Args:
        sources_db: path to FTS5 index of source document chunks (rag_fts.db).
                    When provided, appends retrieved document excerpts to the
                    belief context for fuller coverage.
        natural: strip belief IDs, status markers, and justification metadata
                 from context, presenting beliefs as plain natural language.

    Returns the answer text.
    """
    if no_synth:
        fmt = format or "compact"
        return api.search(question, db_path=db_path, format=fmt)

    if simple:
        beliefs_context = api.search(question, db_path=db_path, format="markdown",
                                     depth=2)
        if not beliefs_context or beliefs_context.strip() == "No results found.":
            beliefs_context = ""

        if natural and beliefs_context:
            beliefs_context = _strip_belief_metadata(beliefs_context)

        if sources_db:
            sources_context = _search_source_chunks(question, sources_db)
            if sources_context:
                beliefs_context = beliefs_context + "\n\n## Source Documents\n\n" + sources_context

        if not beliefs_context.strip():
            return NO_BELIEFS_MSG

        prompt = build_simple_prompt(question, beliefs_context)
        print("Synthesizing (simple)...", file=sys.stderr)
        try:
            response = invoke_model(prompt, model=model, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"LLM timed out after {timeout}s", file=sys.stderr)
            return _beliefs_or_no_match(beliefs_context)
        except Exception as e:
            print(f"LLM error: {e}", file=sys.stderr)
            return _beliefs_or_no_match(beliefs_context)
        return response.strip()

    beliefs_context = api.search(question, db_path=db_path, format="markdown")

    if natural and beliefs_context:
        beliefs_context = _strip_belief_metadata(beliefs_context)

    if sources_db:
        sources_context = _search_source_chunks(question, sources_db)
        if sources_context:
            beliefs_context = (beliefs_context or "") + "\n\n## Source Documents\n\n" + sources_context

    tool_history = []

    for iteration in range(MAX_ITERATIONS):
        if iteration == MAX_ITERATIONS - 1:
            prompt = build_final_prompt(question, beliefs_context, tool_history)
        else:
            prompt = build_ask_prompt(question, beliefs_context, tool_history)

        print(f"Synthesizing (round {iteration + 1}/{MAX_ITERATIONS})...",
              file=sys.stderr)

        try:
            response = invoke_model(prompt, model=model, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"LLM timed out after {timeout}s", file=sys.stderr)
            return _beliefs_or_no_match(beliefs_context)
        except Exception as e:
            print(f"LLM error: {e}", file=sys.stderr)
            return _beliefs_or_no_match(beliefs_context)

        tool_call = extract_tool_call(response)

        if tool_call is None:
            return response.strip()

        if tool_call.get("tool") == "search_beliefs":
            query = tool_call.get("query", "")
            print(f"  Searching: {query}", file=sys.stderr)
            result = api.search(query, db_path=db_path, format="markdown")
            tool_history.append({"query": query, "result": result})
            if result and result.strip() != "No results found.":
                beliefs_context = result
        else:
            return response.strip()

        if iteration == MAX_ITERATIONS - 1:
            print(f"Synthesizing (final)...", file=sys.stderr)
            prompt = build_final_prompt(question, beliefs_context, tool_history)
            try:
                response = invoke_model(prompt, model=model, timeout=timeout)
            except subprocess.TimeoutExpired:
                print(f"LLM timed out after {timeout}s", file=sys.stderr)
                return _beliefs_or_no_match(beliefs_context)
            except Exception as e:
                print(f"LLM error: {e}", file=sys.stderr)
                return _beliefs_or_no_match(beliefs_context)
            if extract_tool_call(response):
                return _beliefs_or_no_match(beliefs_context)
            return response.strip()

    return _beliefs_or_no_match(beliefs_context)
