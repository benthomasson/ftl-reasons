# Code Review: check_stale should report missing source files as stale (#25)

## FEEDBACK FOR IMPLEMENTER

**Correctness: Pass.** The core fix is correct and well-targeted. The `if path is None: continue` block in `check_stale.py:62-63` is replaced with a block that appends a result with `reason: "source_deleted"`, `new_hash: None`, `source_path: None`. The existing content-changed path now carries `reason: "content_changed"`. All results have a uniform shape.

**API passthrough: No issues.** `api.check_stale()` (lines 1011-1036) returns `{"stale": results, ...}` where `results` comes directly from the core `check_stale()`. It doesn't filter on dict keys, so the new `reason` and `source_path` fields pass through cleanly. The `checked` count (`in_with_source`) is computed independently and remains correct because it counts nodes that have both `source` and `source_hash` — which includes nodes whose source file was later deleted.

**CLI display: Correct.** `cmd_check_stale` in `cli.py:547-555` branches on `item.get("reason") == "source_deleted"` and prints `DELETED` with the source path but no hash line (since `new_hash` is `None`). The `else` branch handles `content_changed` with the existing STALE format.

**Minor observation (not blocking):** The summary line at `cli.py:558` reports all results as "STALE" (`{result['stale_count']} STALE`). This is accurate at a summary level (all are stale), but if you wanted to split the count into "N stale, M deleted" for clarity, it would be a small enhancement. Not necessary for this PR.

**Docstring: Good.** Updated to document the `reason` field, the two possible values, and that `new_hash`/`source_path` can be `None` for deleted sources.

**No regressions detected.** The change is additive — the result dict has two new keys (`reason`, `source_path`) that existing consumers would ignore if they don't read them. The `source_path: str(path)` for content-changed results is new but was not present before at all, so nothing breaks.

**Error handling: Adequate.** `resolve_source_path` returns `None` for multiple reasons (empty source, missing file, no repo mapping). The fix correctly treats all `None` returns as "source deleted." This is a reasonable interpretation — if the source can't be resolved, the belief's provenance is gone regardless of the specific cause.

No changes required.

## FEED-FORWARD FOR TESTER

### Key behaviors to test
1. **Deleted source file produces `reason: "source_deleted"`** — node has `source` and `source_hash`, file does not exist on disk.
2. **Changed source file produces `reason: "content_changed"`** — node has `source` and `source_hash`, file exists but hash differs.
3. **Fresh node produces no result** — file exists and hash matches.
4. **OUT nodes are still skipped** — even if their source is deleted.
5. **Nodes without `source_hash` are still skipped** — the `source_hash` guard on line 64 hasn't changed.

### Edge cases to consider
- **Source path with no repo mapping:** `resolve_source_path("unknown-repo/file.md", repos)` falls back to `~/git/unknown-repo/file.md`. If that doesn't exist, it returns `None` → `source_deleted`. Is this the right label? The file may never have existed in the first place. The current behavior is arguably correct (if you can't find the source, the belief is unsupported), but a test documenting this would be valuable.
- **Bare filename source (no slash):** `resolve_source_path("bare.md")` checks `Path("bare.md").exists()`. If this is a relative path and CWD changes, resolution changes. Not a new issue, but worth noting.
- **Mixed results:** One node has a deleted source, another has a changed source. Verify both appear in results with correct `reason` values.
- **CLI exit code:** `cmd_check_stale` calls `sys.exit(1)` when any stale results exist (line 559). Verify this still fires for deleted-source results.

### Suggested test scenarios
1. Integration test through `api.check_stale()` to verify the `checked` count includes nodes with deleted sources.
2. CLI output test (capture stdout) to verify `DELETED` label appears for deleted sources and `STALE` for changed sources.
3. Round-trip: create a node with a source file, hash it, delete the file, run `check_stale`, verify the result, then verify `hash_sources` still skips it (it does — `hash_sources` also calls `resolve_source_path` and continues on `None`).

### Areas of concern
- Tests were not executed during implementation (sandbox limitation). Priority one is running the test suite.

## SELF-REVIEW

1. **What was easy to review:** The change is small, well-scoped, and mechanical. Three files, one behavioral change, uniform dict shape. The plan matched the implementation line-by-line, which made verification fast. The test rename from `test_skips_` to `test_reports_` clearly signals the intent change.

2. **What made review harder:** The `api.py` passthrough needed checking — it's 1500 lines and the reviewer has to verify that `api.check_stale` doesn't filter or reshape the result dict. A comment or note in the implementation summary pointing to the relevant `api.py` lines would have saved time. The implementer did flag this as a concern, which was helpful.

3. **What would help next time:** Running the tests. The implementer noted they couldn't run tests due to sandbox permissions — this is the single biggest risk. A CI check or pre-merge test run is essential.

4. **For the implementer:** The self-review checklist in IMPLEMENTATION.md was genuinely useful. Including "what I didn't change and why" (api.py, resolve_source_path) saved me from hunting for missing pieces.

## Verdict

STATUS: APPROVED
OPEN_ISSUES: none
