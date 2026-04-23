Plan written to `workspaces/issue-25/planner/PLAN.md`.

**Summary:** This is a small, surgical fix across 3 files:

- **`check_stale.py`** (lines 62-73): Instead of `continue` when the source file is missing, append a stale result with `reason: "source_deleted"`, `new_hash: None`. Also add `reason: "content_changed"` to the existing stale-result dict so all results carry a uniform `reason` field.
- **`cli.py`** (lines 547-551): Branch on `reason` to print `DELETED` vs `STALE` labels, skipping the hash line for deleted sources.
- **`test_check_stale.py`**: Update `test_skips_missing_source_files` to assert the node *is* reported (not skipped), add field verification test, add `reason` assertion to existing stale test.

No changes needed to `resolve_source_path`, `hash_sources`, or `api.py`. ~40 lines total across all files.

[Committed changes to planner branch]