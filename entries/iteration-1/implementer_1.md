Here's the summary:

**Files modified (3):**

1. **`reasons_lib/check_stale.py`** — Missing source files now produce a result with `reason: "source_deleted"` and `new_hash: None` instead of being silently skipped. Content-changed results now carry `reason: "content_changed"`. Updated docstring.

2. **`reasons_lib/cli.py`** — `cmd_check_stale` branches on reason to print `DELETED` vs `STALE` labels, omitting the hash line for deleted sources.

3. **`tests/test_check_stale.py`** — Renamed `test_skips_missing_source_files` to `test_reports_missing_source_files` with full field assertions. Added `reason` assertion to `test_stale_node`.

**Concerns for reviewer:**
- Tests were not executed (sandbox permissions) — need a test run to confirm.
- `api.py` should be checked to ensure it passes results through without filtering on dict keys.
- CLI summary line still says "STALE" for all results including deletions — may want a separate count.

[Committed changes to implementer branch]