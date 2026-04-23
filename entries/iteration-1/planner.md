Plan written to `workspaces/issue-26/planner/PLAN.md`.

**Summary:** The fix adds a `_next_nogood_id` monotonic counter to `Network`, replacing the `len(self.nogoods) + 1` derivation. The counter is derived from the max existing nogood ID on load (no schema changes needed). Four files change: `network.py` (counter + helper + updated `add_nogood`), `storage.py` and `api.py` (call helper after loading/importing), and `test_network.py` (3 new tests covering deletion, empty list, and prefixed ID scenarios).

[Committed changes to planner branch]