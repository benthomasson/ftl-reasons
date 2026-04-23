# Tester Review: Nogood ID Uniqueness Fix (Issue #26)

## TEST CASES

21 tests written in `tests/test_nogood_id.py`, organized into 6 classes:

### TestNogoodIdCounter (7 tests)
Core `_compute_next_nogood_id()` behavior:
- Empty list yields counter = 1
- Single nogood sets counter correctly
- Gap in IDs (nogood-001, nogood-005) sets counter to 6
- Prefixed IDs (`agent:nogood-099`) are ignored by `re.fullmatch`
- Mix of prefixed and unprefixed — only unprefixed count
- Large numbers (>999) work correctly
- Fresh Network initializes counter to 1

### TestNogoodIdAfterDeletion (4 tests)
The core bug scenario:
- Delete middle nogood, recompute, add — produces nogood-004 (not a collision)
- Delete last nogood — counter derives from remaining max
- Delete all nogoods — counter resets to 1 (by design: derive-on-load)
- Sequential adds without deletion — IDs are sequential (regression check)

### TestNogoodIdStorageRoundTrip (2 tests)
SQLite persistence via `storage.py`:
- Save/load/add — counter continues from max in loaded data
- Save with gaps in IDs — loaded counter picks up from max

### TestNogoodIdJsonImport (2 tests)
JSON import via `api.py import_json`:
- Import then add via API — new nogood gets next sequential ID
- Direct counter verification after import of a JSON with `nogood-003`

### TestNogoodIdBeliefImport (3 tests)
Markdown import via `import_beliefs.py`:
- Import nogoods.md with `nogood-005`, then add — next is `nogood-006`
- Import with no nogoods section — counter stays at 1
- Import then add multiple — IDs are sequential from the imported max

### TestNogoodIdFormatting (3 tests)
ID string formatting:
- Three-digit zero-padding (`nogood-001`)
- Four-digit numbers produce `nogood-1000` (no truncation)
- Counter increments are monotonic across multiple adds

## USAGE INSTRUCTIONS FOR USER

### Running Tests

```bash
# Run just the new nogood ID tests
uv run --extra test pytest tests/test_nogood_id.py -v

# Run the full test suite (396 tests)
uv run --extra test pytest tests/ -v
```

### Using Nogoods (CLI)

Record a contradiction between two beliefs:
```bash
uv run reasons nogood NODE_A NODE_B
```

This creates a nogood with a unique ID (e.g., `nogood-001`) and uses dependency-directed backtracking to retract the least-entrenched premise.

View all nogoods:
```bash
uv run reasons status
```

### Using Nogoods (Python API)

```python
from reasons_lib import api

# Initialize database
api.init_db(db_path="reasons.db")

# Add nodes
api.add_node("claim-a", "Earth is flat", db_path="reasons.db")
api.add_node("claim-b", "Earth is round", db_path="reasons.db")

# Record contradiction
result = api.add_nogood(["claim-a", "claim-b"], db_path="reasons.db")
print(result["nogood_id"])      # "nogood-001"
print(result["backtracked_to"]) # which premise was retracted
print(result["changed"])        # list of nodes whose truth values changed
```

### Using Nogoods (Network object directly)

```python
from reasons_lib.network import Network

net = Network()
net.add_node("a", "Premise A")
net.add_node("b", "Premise B")

# Record contradiction — automatically retracts least-entrenched node
changed = net.add_nogood(["a", "b"])

# Check what was recorded
print(net.nogoods[-1].id)    # "nogood-001"
print(net.nogoods[-1].nodes) # ["a", "b"]

# Add more nogoods — IDs increment safely
net.add_node("c", "C")
net.add_node("d", "D")
net.add_nogood(["c", "d"])
print(net.nogoods[-1].id)    # "nogood-002"
```

### Import/Export with Nogoods

JSON round-trip:
```bash
uv run reasons export > network.json
uv run reasons import-json network.json
```

Markdown import with nogoods:
```bash
uv run reasons import-beliefs beliefs.md
```

The nogoods section in `nogoods.md` uses this format:
```markdown
### nogood-001: Description of contradiction
- Discovered: 2026-04-23
- Resolution: Unresolved
- Affects: node-a, node-b
```

### What Changed (Issue #26)

Previously, nogood IDs were derived from `len(self.nogoods) + 1`. If a nogood was ever deleted, the next ID would collide with an existing one.

Now, a monotonically increasing counter (`_next_nogood_id`) tracks the next available ID. After any bulk load of nogoods (SQLite load, JSON import, beliefs.md import), `_compute_next_nogood_id()` scans existing nogoods to find the maximum numeric suffix and sets the counter to `max + 1`.

### Expected Behavior After Fix

| Scenario | Old Behavior | New Behavior |
|----------|-------------|-------------|
| 3 nogoods, delete middle, add new | `nogood-003` (collision!) | `nogood-004` |
| Import JSON with `nogood-005`, add new | `nogood-002` (wrong) | `nogood-006` |
| Import beliefs with `nogood-003`, add new | `nogood-001` (wrong) | `nogood-004` |
| Normal sequential adds | `nogood-001`, `002`, `003` | Same (no change) |

### Common Errors

- **`KeyError: "Node 'X' not found"`** — You tried to create a nogood referencing a node that doesn't exist. Add the node first.
- **Counter reset after clear** — If all nogoods are deleted and `_compute_next_nogood_id()` is called, the counter resets to 1. This is by design (derive-on-load), since there's no data to derive from.

## SELF-REVIEW

### What was easy to test?
The core counter logic (`_compute_next_nogood_id`) was straightforward — it's a pure computation on the nogoods list. The deletion + re-add scenario was also easy since Network methods are well-isolated.

### What was hard to test?
The API-level test (`test_import_json_then_add_nogood`) required understanding that `get_status()` doesn't return a `nogoods` field — I had to use the `add_nogood` return value instead. The `test_delete_last_then_add` initially tripped me up: I expected `nogood-003` but the correct behavior is `nogood-002` because the counter derives from remaining data (max=1), not from history.

### What information was missing?
The reviewer's feed-forward was excellent and covered all the cases I needed. The only gap was clarifying the "derive on load" design decision more explicitly — specifically that deleting all nogoods resets the counter to 1, which is correct but potentially surprising.

### What would make the job easier next time?
- API return type documentation (what fields does `get_status` return?)
- A note about whether the `import_agent.py` path needs testing (reviewer said no, but it wasn't obvious from the task description)

### Gaps revealed by testing?
None. The implementation is correct for all tested scenarios. The counter derivation logic is clean and the call sites are comprehensive.

## Verdict

STATUS: TESTS_PASSED
OPEN_ISSUES: none
