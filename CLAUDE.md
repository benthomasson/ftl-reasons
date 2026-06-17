# CLAUDE.md

## What This Is

Reasons — a belief tracking system based on Doyle's 1979 Truth Maintenance System. Tracks beliefs as nodes in a dependency network with automatic retraction cascades and restoration. Previously called "rms" — renamed because tool name ablation showed "rms" confused LLMs by 5pp (root mean square is far more common than reason maintenance system).

## Key Concepts

- **Node**: A belief with a truth value (IN or OUT)
- **Premise**: A node with no justifications — IN by default
- **Justification**: Why a node is believed (SL = all antecedents must be IN AND all outlist must be OUT)
- **Outlist**: Non-monotonic reasoning — "believe X unless Y is believed"
- **Retraction cascade**: When a node goes OUT, all dependents whose justifications become invalid also go OUT
- **Restoration**: When a retracted node comes back IN, dependents are automatically recomputed
- **Nogood**: A set of nodes that cannot all be IN simultaneously (contradiction)
- **Backtracking**: When a nogood is detected, traces backward to find the responsible premise using entrenchment scoring
- **Challenge/Defend**: Dialectical argumentation — challenge a belief, defend against challenges
- **Multiple justifications**: A node is IN if ANY justification is valid
- **Summary nodes**: Abstract over groups of nodes in compact output

## Project Structure

```
reasons/                # importable as `import reasons` (also aliased as reasons_lib for backwards compat)
  __init__.py         # Node, Justification, Nogood dataclasses
  network.py          # Network class — dependency graph + propagation + dialectical
  api.py              # Functional Python API (returns dicts, for CLI + LangGraph)
  storage.py          # SQLite persistence
  cli.py              # CLI entry point
  import_beliefs.py   # Parse beliefs.md into network
  export_markdown.py  # Generate beliefs.md from network
  check_stale.py      # Source hash comparison + hash_sources
  compact.py          # Token-budgeted summary with summary node support
reasons_lib/            # backwards-compat shim — re-exports from reasons/
tests/
  test_network.py     # Propagation, cascading, diamond dependencies
  test_storage.py     # SQLite round-trips
  test_api.py         # Functional API
  test_outlist.py     # Non-monotonic justifications
  test_backtracking.py # Trace, find_culprits, entrenchment
  test_dialectical.py # Challenge/defend
  test_summarize.py   # Summary nodes
  test_import_beliefs.py # beliefs.md import
  test_import_json.py # JSON round-trip
  test_export_markdown.py # Markdown export
  test_check_stale.py # Staleness + hash_sources
  test_compact.py     # Token-budgeted summary
```

## Commands

```bash
uv run reasons init                              # create reasons.db
uv run reasons add NODE "text" --sl a,b          # add with SL justification
uv run reasons add NODE "text" --unless y        # non-monotonic (outlist)
uv run reasons add NODE "text"                   # add as premise
uv run reasons retract NODE                      # mark OUT + cascade
uv run reasons assert NODE                       # mark IN + cascade
uv run reasons status                            # show all nodes
uv run reasons show NODE                         # node details
uv run reasons explain NODE                      # trace why IN or OUT
uv run reasons trace NODE                        # find all premises it rests on
uv run reasons challenge NODE "reason"           # challenge — target goes OUT
uv run reasons defend TARGET CHALLENGE "reason"  # defend — neutralise challenge
uv run reasons nogood A B                        # record contradiction + backtrack
uv run reasons search "query"                    # search by text or ID
uv run reasons list --premises                   # list with filters
uv run reasons import-beliefs beliefs.md         # import from beliefs CLI
uv run reasons import-json network.json          # import from JSON (lossless)
uv run reasons export                            # JSON export
uv run reasons export-markdown                   # beliefs.md-compatible export
uv run reasons check-stale                       # detect source file changes
uv run reasons hash-sources                      # backfill source hashes
uv run reasons compact --budget 500              # token-budgeted summary
uv run reasons propagate                         # recompute all truth values
uv run reasons log                               # propagation history
```

## Running Tests

```bash
uv run --extra test pytest tests/ -v
```

211 tests covering all features.

## Design Decisions

- SQLite (not markdown) for ACID transactions during propagation cascades
- No STALE status — uses IN/OUT only; staleness triggers retraction
- Retracted nodes stay in DB (Doyle's insight: enables restoration without rederivation)
- BFS propagation ensures all dependents are recomputed when a node changes
- Entrenchment scoring protects evidence over speculation in backtracking
- Tool name "reasons" chosen over "rms" based on 5pp accuracy improvement in ablation study
