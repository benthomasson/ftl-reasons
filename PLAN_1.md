# Plan (Iteration 1)

Task: ## Nogood IDs assume append-only list, deletion causes collisions

## Problem

In `network.py`, `add_nogood` derives nogood IDs from `len(self.nogoods) + 1`. If a nogood is ever deleted from the list, subsequent calls will generate IDs that collide with existing entries, corrupting the contradiction history.

## Impact

This root defect gates **3 derived beliefs** in the knowledge base, including:
- `nogood-resolution-maintains-consistent-ids`
- `belief-revision-is-fully-reliable`

## Suggested fix

Use a monotonically increasing counter (e.g., `self._next_nogood_id`) that is persisted alongside the nogoods, or use UUIDs, so that IDs remain unique regardless of deletions.

## Source

Belief: `nogood-ids-assume-append-only`
Entry: `entries/2026/04/23/reasons_lib-network-add_nogood.md`

Closes #26

EFFORT LEVEL: MODERATE
Keep plan focused and concise. Cover key design decisions but avoid over-analysis.

Plan written to `workspaces/issue-26/planner/PLAN.md`.

**Summary:** The fix adds a `_next_nogood_id` monotonic counter to `Network`, replacing the `len(self.nogoods) + 1` derivation. The counter is derived from the max existing nogood ID on load (no schema changes needed). Four files change: `network.py` (counter + helper + updated `add_nogood`), `storage.py` and `api.py` (call helper after loading/importing), and `test_network.py` (3 new tests covering deletion, empty list, and prefixed ID scenarios).

[Committed changes to planner branch]