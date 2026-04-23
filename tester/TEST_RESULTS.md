# Test Results: Issue #25 — check_stale reports missing source files

## Test File

`tests/test_check_stale_issue25.py` — 24 test cases across 6 test classes.

## Test Classes

### TestDeletedSourceDetection (7 tests)
Core behavior: deleted source files produce a result instead of being skipped.
- `test_deleted_source_returns_result` — node with missing file appears in results
- `test_deleted_source_reason_field` — reason is "source_deleted"
- `test_deleted_source_new_hash_is_none` — new_hash is None (no file to hash)
- `test_deleted_source_source_path_is_none` — source_path is None
- `test_deleted_source_preserves_old_hash` — old_hash matches stored hash
- `test_deleted_source_preserves_source` — source string preserved
- `test_deleted_source_preserves_node_id` — node_id field correct

### TestResultShape (4 tests)
Uniform result dict structure across both reason types.
- `test_content_changed_has_reason_field` — content-changed carries reason="content_changed"
- `test_content_changed_has_source_path` — resolved path included
- `test_all_results_have_same_keys` — deleted and changed results share same dict keys
- `test_expected_keys_present` — exactly the 6 documented keys

### TestMixedScenarios (4 tests)
Real-world combinations of fresh, changed, and deleted nodes.
- `test_mix_of_deleted_changed_and_fresh` — three-node scenario with all states
- `test_multiple_deleted_sources` — all deleted nodes reported
- `test_deleted_source_then_recreated` — transitions from source_deleted to content_changed
- `test_deleted_source_then_recreated_same_content` — recreated with same content = fresh

### TestExclusions (3 tests)
Nodes that should NOT appear in results.
- `test_out_node_with_deleted_source_not_reported` — OUT nodes still skipped
- `test_node_without_source_not_reported` — no source field = skipped
- `test_node_with_source_but_no_hash_not_reported` — source but no hash = skipped

### TestAPIPassthrough (3 tests)
API layer passes deleted-source results through correctly.
- `test_api_includes_deleted_source_in_stale` — reason field preserved through api
- `test_api_counts_deleted_source_in_checked` — deleted-source nodes count as checked
- `test_api_stale_count_matches_results_length` — stale_count == len(stale)

### TestCLIOutput (3 tests)
CLI display formatting.
- `test_cli_deleted_shows_deleted_label` — prints "DELETED" label
- `test_cli_deleted_omits_hash_line` — no "hash:" line for deleted sources
- `test_cli_changed_shows_stale_label` — changed sources still show "STALE" with hash

## Results

```
24 passed in 0.08s
```

Full suite: **375 passed in 1.07s** — no regressions.
