# Usage Guide: Staleness Detection with Deleted Source Files

## Overview

`reasons check-stale` detects when beliefs are based on source files that have changed or been deleted. After issue #25, deleted source files are now reported instead of silently skipped.

## Commands

### Check for stale beliefs

```bash
uv run reasons check-stale
```

**Output when all fresh:**
```
All 12 nodes with sources are fresh.
```

**Output with stale/deleted nodes:**
```
  DELETED  missing-source-belief
           source: myrepo/deleted-file.md

  STALE  outdated-belief
         source: myrepo/changed-file.md
         hash: a1b2c3d4e5f6g7h8 -> i9j0k1l2m3n4o5p6

10 fresh, 2 STALE (of 12 checked)
```

Exit code is 1 when any stale/deleted nodes are found, 0 when all fresh.

### Update hashes after reviewing changes

After confirming a source change is expected:

```bash
uv run reasons hash-sources
```

This backfills hashes for nodes that have a source but no hash. To re-hash all nodes (including those with existing hashes):

```bash
# Not a CLI flag — use the Python API:
from reasons_lib import api
api.hash_sources(force=True)
```

### Retract beliefs from deleted sources

When a source file is deleted and the belief is no longer valid:

```bash
uv run reasons retract missing-source-belief
```

## Python API

```python
from reasons_lib import api

result = api.check_stale()
# result = {
#   "stale": [
#     {"node_id": "x", "reason": "source_deleted", "old_hash": "abc",
#      "new_hash": None, "source": "repo/file.md", "source_path": None},
#     {"node_id": "y", "reason": "content_changed", "old_hash": "abc",
#      "new_hash": "def", "source": "repo/file.md", "source_path": "/abs/path"},
#   ],
#   "checked": 12,
#   "stale_count": 2,
# }

# Filter by reason
deleted = [s for s in result["stale"] if s["reason"] == "source_deleted"]
changed = [s for s in result["stale"] if s["reason"] == "content_changed"]
```

## Result Fields

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | `str` | The belief node ID |
| `reason` | `str` | `"content_changed"` or `"source_deleted"` |
| `old_hash` | `str` | Hash stored when the belief was created |
| `new_hash` | `str \| None` | Current file hash, or `None` if file deleted |
| `source` | `str` | Source path as stored (e.g. `repo/path/file.md`) |
| `source_path` | `str \| None` | Resolved absolute path, or `None` if file deleted |

## Common Scenarios

### Source file was intentionally deleted
The belief is no longer grounded. Retract it:
```bash
uv run reasons retract the-belief-id
```

### Source file was moved/renamed
Retract the old belief and re-add it with the new source path, or update the source field in the database.

### Source file content changed but belief still holds
Re-hash to update the stored hash:
```bash
uv run reasons hash-sources
```

### False positive: file is in an unmapped repo
If `check-stale` reports `source_deleted` but the file exists in a repo not in the repos table, the file can't be resolved. Add the repo mapping:
```bash
# In the Python API (no CLI for this yet):
# The repos table maps repo names to local paths
```
