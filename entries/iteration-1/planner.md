Plan written to `workspaces/issue-23/planner/PLAN.md`.

## PLAN

**One-line fix:** Dedent `count += len(belief_ids)` at `reasons_lib/derive.py:214` so it's outside the per-belief loop but still inside the per-agent loop. Currently it runs N times per agent (once per belief), inflating the count quadratically. It should run once per agent.

| File | Line | Change |
|------|------|--------|
| `reasons_lib/derive.py` | 214 | Dedent `count += len(belief_ids)` one level (align with `for belief_id`) |
| `tests/test_derive.py` | after ~88 | Add regression test: create agent network + local belief, call `build_prompt`, assert local belief appears in output |

**Key decisions:**
- No signature changes to `_build_beliefs_section` — test through `build_prompt` instead.
- No refactoring scope creep. One indentation fix, one regression test.
- No version bump (internal bugfix).

## SELF-REVIEW

1. **What went well:** The bug is unambiguous — wrong indentation level, clear before/after. The existing test file and fixtures made it easy to design a regression test.
2. **What I was missing:** `_build_beliefs_section` doesn't return `count`, so I can't directly assert on it. I had to design the test to observe the *effect* of the inflated count (non-agent budget starvation) rather than the count itself.
3. **What would help next time:** If the function returned a stats dict (like `build_prompt` does), the test could be more precise. But changing that is out of scope for this fix.

[Committed changes to planner branch]