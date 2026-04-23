# Task

## check_stale silently skips nodes with missing source files

## Problem

In `check_stale.py`, if a node's `source` file no longer exists on disk, the function silently skips it. Callers cannot distinguish between a deleted source file and a file that was never tracked. This creates a false-negative gap in staleness detection — beliefs derived from deleted files appear up-to-date when they should be flagged.

## Impact

This root defect gates **5 derived beliefs** in the knowledge base, including:
- `staleness-checking-is-comprehensive`
- `staleness-gate-catches-all-drift`
- `external-belief-lifecycle-is-complete`

## Suggested fix

When `os.path.exists(source)` returns False, include the node in the stale results with a distinct reason (e.g., `reason: "source_deleted"`) rather than skipping it. This lets callers handle deleted sources explicitly.

## Source

Belief: `missing-source-file-is-silent`
Entry: `entries/2026/04/23/reasons_lib-check_stale-check_stale.md`

Closes #25

Started: 2026-04-23T18:20:02.479334