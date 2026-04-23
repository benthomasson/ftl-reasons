# Plan (Iteration 1)

Task: ## check_stale silently skips nodes with missing source files

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

EFFORT LEVEL: MODERATE
Keep plan focused and concise. Cover key design decisions but avoid over-analysis.

Plan written to `workspaces/issue-25/planner/PLAN.md`.

**Summary:** This is a small, surgical fix across 3 files:

- **`check_stale.py`** (lines 62-73): Instead of `continue` when the source file is missing, append a stale result with `reason: "source_deleted"`, `new_hash: None`. Also add `reason: "content_changed"` to the existing stale-result dict so all results carry a uniform `reason` field.
- **`cli.py`** (lines 547-551): Branch on `reason` to print `DELETED` vs `STALE` labels, skipping the hash line for deleted sources.
- **`test_check_stale.py`**: Update `test_skips_missing_source_files` to assert the node *is* reported (not skipped), add field verification test, add `reason` assertion to existing stale test.

No changes needed to `resolve_source_path`, `hash_sources`, or `api.py`. ~40 lines total across all files.

[Committed changes to planner branch]