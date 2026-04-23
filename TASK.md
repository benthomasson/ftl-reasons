# Task

## Nogood IDs assume append-only list, deletion causes collisions

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

Started: 2026-04-23T18:20:06.078398