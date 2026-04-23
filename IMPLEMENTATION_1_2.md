# Implementation (Iteration 1, Attempt 2)

## Changes Made

### Round 1 (initial implementation)

1. **`reasons_lib/network.py`**
   - Added `import re` at top
   - Added `self._next_nogood_id: int = 1` to `__init__`
   - Added `_compute_next_nogood_id()` method that scans existing nogoods using `re.fullmatch(r"nogood-(\d+)")`, finds the max numeric suffix, and sets `self._next_nogood_id = max + 1`
   - In `add_nogood`: replaced `f"nogood-{len(self.nogoods) + 1:03d}"` with `f"nogood-{self._next_nogood_id:03d}"` and added `self._next_nogood_id += 1`

2. **`reasons_lib/storage.py`** (line 183)
   - Added `network._compute_next_nogood_id()` after the nogood loading loop in `load()`

3. **`reasons_lib/api.py`** (line 937)
   - Added `net._compute_next_nogood_id()` after the nogood import loop in `import_json()`

4. **`tests/test_network.py`**
   - `test_nogood_id_survives_deletion` — creates 3 nogoods, deletes middle one, recomputes, adds another, asserts ID is `nogood-004`
   - `test_nogood_counter_empty_list` — empty list produces counter = 1
   - `test_nogood_counter_ignores_prefixed_ids` — `agent:nogood-099` doesn't inflate counter (verified via `re.fullmatch`)

### Round 2 (reviewer fix)

5. **`reasons_lib/import_beliefs.py`** (line 244)
   - Added `network._compute_next_nogood_id()` after the nogood import loop in `import_into_network()` — this was a missed call site where raw `Nogood` objects with non-prefixed IDs are appended without updating the counter

## Self-Review

**What went well:** The core fix was clean and mechanical — small surface area, well-scoped. The `re.fullmatch` choice correctly handles prefixed vs unprefixed IDs without special-casing.

**What was unclear in the plan:** Nothing significant. Line numbers had shifted due to a linter-added `_rebuild_dependents` method, but surrounding context was sufficient.

**Concerns for the reviewer:**
- Tests were not run due to permission restrictions during implementation. The reviewer should run `uv run --extra test pytest tests/ -v` to confirm all tests pass.
- The reviewer correctly caught that I missed the `import_beliefs.py` call site in round 1. I should have grepped for all `nogoods.append` sites before considering the implementation complete. That grep shows one remaining site in `import_agent.py:251` — it uses prefixed IDs (`agent:nogood-XXX`) so the regex safely ignores them, but a defensive `_compute_next_nogood_id()` call there would guard against future format changes. I did not add it since the reviewer marked it as non-blocking.