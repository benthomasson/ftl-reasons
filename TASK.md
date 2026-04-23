# Task

## Bug: _build_beliefs_section inflates belief count per agent

## Problem

In `derive.py`, `_build_beliefs_section` has a bug: `count += len(belief_ids)` is inside the per-belief loop instead of outside it. This inflates the count for each agent, shrinking the non-agent budget below its intended size and distorting proportional token allocation during LLM-driven derivation.

## Impact

This root defect gates **9 derived beliefs** in the knowledge base, including:
- `derive-budget-allocation-is-accurate`
- `derive-pipeline-is-production-ready`
- `all-external-inputs-safely-integrated`
- `system-achieves-full-correctness`

## Suggested fix

Move `count += len(belief_ids)` outside the inner loop so it accumulates once per agent, not once per belief.

## Source

Belief: `derive-agent-count-bug`
Entry: `entries/2026/04/23/reasons_lib-derive.md`

Closes #23

Started: 2026-04-23T18:19:55.314705