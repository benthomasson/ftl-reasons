# Tester (Iteration 1, Attempt 1)

Everything looks good. Let me write the final output.

---

## TEST CASES

**Test file:** `tests/test_check_stale_issue25.py` — 24 tests across 6 classes.

| Class | Count | What it covers |
|-------|-------|----------------|
| `TestDeletedSourceDetection` | 7 | Every field in a deleted-source result dict |
| `TestResultShape` | 4 | Uniform keys across both reason types |
| `TestMixedScenarios` | 4 | Fresh + changed + deleted combinations, file resurrection |
| `TestExclusions` | 3 | OUT nodes, no-source nodes, no-hash nodes still excluded |
| `TestAPIPassthrough` | 3 | `api.check_stale()` passes results through correctly |
| `TestCLIOutput` | 3 | DELETED/STALE labels, hash line presence/absence |

Key edge cases tested:
- File deleted then recreated with different content (transitions from `source_deleted` to `content_changed`)
- File deleted then recreated with identical content (becomes fresh again)
- Multiple deleted sources all reported
- Mix of all three states (fresh, changed, deleted) in one call
- API `checked` count includes deleted-source nodes
- CLI exits with code 1 on stale results

## USAGE INSTRUCTIONS FOR USER

See `tester/USAGE.md` for the full guide. Quick summary:

```bash
# Check for stale beliefs (now catches deleted source files)
uv run reasons check-stale

# Output distinguishes DELETED vs STALE:
#   DELETED  belief-id
#            source: repo/deleted-file.md
#
#   STALE  belief-id
#          source: repo/changed-file.md
#          hash: abc123 -> def456

# Retract a belief whose source was deleted
uv run reasons retract belief-id

# Re-hash after confirming a source change is expected
uv run reasons hash-sources
```

Python API returns `reason` field (`"source_deleted"` or `"content_changed"`) on each result dict. `new_hash` is `None` and `source_path` is `None` for deleted sources.

## SELF-REVIEW

1. **What was easy:** The core `check_stale` function tests were straightforward — the Network class makes it simple to set up nodes with source/source_hash directly. The implementation was clean and well-scoped.

2. **What was hard:** The API/CLI layer tests required a workaround because `api.add_node()` doesn't expose `source_hash` as a parameter. I had to use direct SQLite updates (`_set_source_hash` helper) to set up test state. The CLI test for content-changed also required patching `resolve_source_path` since the API layer resolves paths through the repos table which the test DB doesn't have configured.

3. **What would help next time:** If `api.add_node()` accepted `source_hash` (or if there was a test helper for it), the API/CLI tests would be cleaner. Also, documenting the `api.add_node` signature in CLAUDE.md would save investigation time.

4. **Gaps found:** None in the implementation. The reviewer's observation about the summary line saying "STALE" for all results (including deletions) is a minor UX nit but not a bug — it's accurate at a summary level since all are stale in the broad sense.

## Verdict

STATUS: TESTS_PASSED
OPEN_ISSUES: none

[Committed changes to tester branch]