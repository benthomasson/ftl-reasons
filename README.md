# RMS — Reason Maintenance System

An implementation of Doyle's (1979) Truth Maintenance System. Tracks beliefs as nodes in a dependency network with automatic retraction cascades and restoration.

## Core Ideas

A **node** is a belief with a truth value: IN (believed) or OUT (retracted). Nodes can be **premises** (believed by default) or **derived** (believed because of justifications).

A **justification** is a reason for believing a node. Type SL (Support List) means the node is IN when all its antecedents are IN. A node can have multiple justifications — it's IN if *any* of them are valid.

When a node goes OUT, all dependents whose justifications become invalid go OUT too — this is the **retraction cascade**. When a retracted node comes back IN, dependents are automatically recomputed — **restoration without rederivation**.

A **nogood** records a contradiction: a set of nodes that cannot all be IN simultaneously. When a nogood is detected, the least-entrenched node is retracted.

## Install

```bash
uv tool install -e ~/git/rms
```

Or run directly:

```bash
cd ~/git/rms
uv run rms <command>
```

## Usage

```bash
# Initialize database
rms init

# Add premises
rms add source-uses-langgraph "Source code uses LangGraph" --source "agents-python:src/graph.py"
rms add graph-has-cycles "Graph contains cycles"

# Add derived nodes with SL justifications
rms add topology-is-static "Graph topology is static" --sl source-uses-langgraph --label "observed from source"
rms add no-runtime-modification "No runtime graph modification" --sl topology-is-static

# See what's believed
rms status
#   [+] graph-has-cycles: Graph contains cycles  (premise)
#   [+] no-runtime-modification: No runtime graph modification  (1 justification)
#   [+] source-uses-langgraph: Source code uses LangGraph  (premise)
#   [+] topology-is-static: Graph topology is static  (1 justification)
#
# 4/4 IN

# Retract a premise — cascade propagates
rms retract source-uses-langgraph
# Retracted: source-uses-langgraph, topology-is-static, no-runtime-modification

rms status
#   [+] graph-has-cycles: Graph contains cycles  (premise)
#   [-] no-runtime-modification: No runtime graph modification  (1 justification)
#   [-] source-uses-langgraph: Source code uses LangGraph  (premise)
#   [-] topology-is-static: Graph topology is static  (1 justification)
#
# 1/4 IN

# Restore — dependents come back automatically
rms assert source-uses-langgraph
# Asserted: source-uses-langgraph, topology-is-static, no-runtime-modification

# Record a contradiction
rms add graph-is-dynamic "Graph is dynamically modified"
rms nogood topology-is-static graph-is-dynamic
# Recorded nogood-001: topology-is-static, graph-is-dynamic
# Retracted: graph-is-dynamic

# Explain why a node is IN or OUT
rms explain no-runtime-modification
#   [+] no-runtime-modification: SL justification valid — antecedents: topology-is-static
#   [+] topology-is-static: SL justification valid — antecedents: source-uses-langgraph [observed from source]
#   [+] source-uses-langgraph: premise

# Show node details
rms show topology-is-static

# View propagation history
rms log

# Export as JSON
rms export

# Import from a beliefs CLI registry
rms import-beliefs ~/git/physics-pi-meta/beliefs.md
# Imported 39 claims (2 retracted)
# Imported 8 nogoods

# nogoods.md is auto-detected next to beliefs.md, or specify explicitly:
rms import-beliefs ~/git/physics-pi-meta/beliefs.md --nogoods ~/git/physics-pi-meta/nogoods.md

# After import, cascading works on the imported dependency graph:
rms retract beliefs-improve-accuracy
# Retracted: beliefs-improve-accuracy, engineering-intuition-unreliable, beliefs-beat-expert-prompting, ...

# Search for nodes
rms search "tool-use"
#   [+] tool-use-calibration-determines-benefit: Whether beliefs help a model...  (5 dependents)
#   [+] tool-deference-failure-mode: Models with poor tool-use calibration...
# 7 results

# List premises (foundations of the argument)
rms list --premises
# List nodes that others depend on
rms list --has-dependents
# List only OUT nodes
rms list --status OUT

# Export as readable markdown
rms export-markdown -o beliefs.md

# Check for source file changes
rms check-stale
# 5 fresh, 14 STALE (of 19 checked)

# Token-budgeted summary for context injection
rms compact --budget 500
```

## Commands

| Command | Description |
|---------|-------------|
| `rms init` | Create rms.db |
| `rms add ID "text"` | Add a premise |
| `rms add ID "text" --sl a,b` | Add with SL justification (all antecedents must be IN) |
| `rms add ID "text" --cp a,b` | Add with CP justification (assumptions must be consistent) |
| `rms retract ID` | Mark OUT + cascade to dependents |
| `rms assert ID` | Mark IN + cascade restoration |
| `rms status` | Show all nodes with truth values |
| `rms show ID` | Show node details, justifications, dependents |
| `rms explain ID` | Trace why a node is IN or OUT |
| `rms nogood A B ...` | Record contradiction, retract least-entrenched |
| `rms propagate` | Recompute all truth values |
| `rms log` | Show propagation audit trail |
| `rms search QUERY` | Search nodes by text or ID (case-insensitive) |
| `rms list` | List nodes with filters (`--status IN\|OUT`, `--premises`, `--has-dependents`) |
| `rms import-beliefs FILE` | Import a beliefs.md registry (auto-detects nogoods.md) |
| `rms export` | Export network as JSON |
| `rms export-markdown` | Export as beliefs.md-compatible markdown (`-o FILE` to write) |
| `rms check-stale` | Check IN nodes for source file hash changes |
| `rms compact` | Token-budgeted summary (`--budget N`, `--no-truncate`) |

## Tests

```bash
uv run --extra test pytest tests/ -v
```

120 tests covering propagation, retraction cascades, restoration, multiple justifications, diamond dependencies, nogoods, explain traces, SQLite round-trips, beliefs.md import, export-markdown, check-stale, compact, search, and list.

## References

Doyle, J. (1979). A Truth Maintenance System. *Artificial Intelligence*, 12(3), 231–272.
