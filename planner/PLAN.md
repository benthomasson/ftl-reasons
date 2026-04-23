# Plan: check_stale should report missing source files as stale

**Issue:** #25 — `check_stale` silently skips nodes whose source file no longer exists on disk.

## Requirements

When a node has `truth_value="IN"`, a `source`, and a `source_hash`, but the source file no longer exists on disk, `check_stale` must include that node in its stale results with `reason: "source_deleted"`. Today it returns `None` from `resolve_source_path` and hits `continue`, so the node is invisible to callers.

The fix has three layers: the core function, the CLI display, and the tests.

## Implementation Steps

### Step 1: Add `reason` field to `check_stale()` results

**File:** `reasons_lib/check_stale.py`

| Line(s) | Change |
|---------|--------|
| 62-63 | Replace the `if path is None: continue` block. When `path is None`, append a stale result with `reason: "source_deleted"`, `old_hash` set to the stored hash, `new_hash` set to `None`, and `source_path` set to `None`. |
| 67-73 | Add `"reason": "content_changed"` to the existing stale-result dict so all results carry a `reason` field. |

After this change, lines 61-73 should look like:

```python
        path = resolve_source_path(node.source, repos)
        if path is None:
            results.append({
                "node_id": nid,
                "old_hash": node.source_hash,
                "new_hash": None,
                "source": node.source,
                "source_path": None,
                "reason": "source_deleted",
            })
            continue

        current_hash = hash_file(path)
        if current_hash != node.source_hash:
            results.append({
                "node_id": nid,
                "old_hash": node.source_hash,
                "new_hash": current_hash,
                "source": node.source,
                "source_path": str(path),
                "reason": "content_changed",
            })
```

**Design decision:** `new_hash: None` (not empty string) for deleted files. This is unambiguous — there is no file to hash. Callers can check `reason` or `new_hash is None` interchangeably.

**Design decision:** Every stale result now carries `reason`. This is a backwards-compatible addition (new key in existing dict), so no callers break. Adding `reason` to *all* results (not just deleted) means callers don't need to special-case which results have it.

### Step 2: Update CLI display for deleted sources

**File:** `reasons_lib/cli.py`

| Line(s) | Change |
|---------|--------|
| 547-550 | Branch on `item.get("reason")`. For `"source_deleted"`, print a `DELETED` label and skip the hash line (there's no `new_hash`). For `"content_changed"` (or any other), keep the existing display. |

After this change, lines 547-551 should look like:

```python
    for item in result["stale"]:
        if item.get("reason") == "source_deleted":
            print(f"  DELETED  {item['node_id']}")
            print(f"           source: {item['source']}")
        else:
            print(f"  STALE  {item['node_id']}")
            print(f"         source: {item['source']}")
            print(f"         hash: {item['old_hash']} -> {item['new_hash']}")
        print()
```

**Design decision:** Use `DELETED` label, not `STALE`. Deleted sources are a different category — the source didn't change, it vanished. The user needs to decide whether to retract or re-source the belief, and a distinct label makes that clear.

### Step 3: Update `api.py` — no changes needed

The `checked` count at `api.py:1025-1028` counts nodes with `truth_value == "IN" and source and source_hash`. Nodes with deleted source files satisfy all three conditions, so they are already counted. The `stale_count` is `len(results)`, which will now include deleted-source nodes. **No change required.**

### Step 4: Update existing tests, add new tests

**File:** `tests/test_check_stale.py`

| Line(s) | Change |
|---------|--------|
| 100-105 | **Modify** `test_skips_missing_source_files`: rename to `test_reports_missing_source_files`. Assert that `results` has 1 entry with `reason == "source_deleted"`, `new_hash is None`, and `source_path is None`. |
| 74-77 | **Update** `test_stale_node`: add assertion `results[0]["reason"] == "content_changed"` to verify the reason field on normal stale results. |
| After 105 | **Add** `test_deleted_source_has_correct_fields`: create a node with source and hash, don't create the file, verify all dict fields are correct (`node_id`, `old_hash`, `new_hash=None`, `source`, `source_path=None`, `reason="source_deleted"`). |

**New test case to add:**

```python
    def test_deleted_source_fields(self, tmp_path):
        net = Network()
        net.add_node("a", "Premise A", source="myrepo/gone.md", source_hash="abc123")

        results = check_stale(net, repos={"myrepo": tmp_path})
        assert len(results) == 1
        r = results[0]
        assert r["node_id"] == "a"
        assert r["old_hash"] == "abc123"
        assert r["new_hash"] is None
        assert r["source"] == "myrepo/gone.md"
        assert r["source_path"] is None
        assert r["reason"] == "source_deleted"
```

### Step 5: `hash_sources` — leave as-is

`hash_sources` (line 78-113) also skips missing files, but this is correct behavior for that function. You can't compute a hash for a file that doesn't exist. No change needed.

### Step 6: `resolve_source_path` — leave as-is

The `None` return for missing files is the right API for this helper. The caller (`check_stale`) is where the policy decision lives — *what to do* when the file is missing. Changing `resolve_source_path` would break `hash_sources`.

## Key Design Decisions

1. **`reason` field on all stale results** — not just deleted ones. Uniform schema is easier for callers.
2. **`new_hash: None`** — not empty string, not a sentinel. `None` means "no file to hash."
3. **`source_path: None`** — consistent with `new_hash`. The path doesn't exist.
4. **`DELETED` label in CLI** — distinct from `STALE` so the user knows the action needed is different (re-source or retract, not just review the diff).
5. **No change to `resolve_source_path`** — it's a path resolver, not a policy function. Policy lives in the caller.
6. **No change to `hash_sources`** — skipping missing files is correct when your job is to compute hashes.
7. **No change to `api.py` `checked` count** — deleted-source nodes are already counted by the existing filter.

## Success Criteria

1. `reasons check-stale` reports nodes whose source files were deleted, with a `DELETED` label.
2. `reasons check-stale` still reports content-changed nodes with `STALE` label and hash diff.
3. All stale results include a `reason` field (`"source_deleted"` or `"content_changed"`).
4. Existing tests pass (with updates to reflect new behavior).
5. New test covers the deleted-source case with full field verification.
6. `hash_sources` behavior is unchanged (still skips missing files).

## Scope

This is a **small, focused change**: ~15 lines in `check_stale.py`, ~8 lines in `cli.py`, ~20 lines in tests. No new files, no new dependencies, no API signature changes.

---

## Self-Review

1. **What went well:** The codebase is clean and well-structured — the fix is surgical. Reading the actual code confirmed the exact line numbers and the dict structure, so the plan is precise.

2. **What information was I missing:** Nothing critical. I briefly considered whether other callers (beyond the CLI) consume `check_stale` results, but the API wrapper is the only path and it passes through transparently.

3. **What would make my job easier next time:** The task description was excellent — it identified the exact file, the exact behavior, and the exact fix. More issues like this one.
