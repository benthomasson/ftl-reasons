# Iteration 1 Understanding

## What We Learned

### From Planner
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

### From Implementer
Files created: None

### From Reviewer
Verdict: APPROVED

Review complete. Written to `workspaces/issue-23/reviewer/REVIEW.md`.

**STATUS: APPROVED.** Both changes are correct:

- **Production fix** (`derive.py:214`): `count += len(belief_ids)` is now correctly outside the per-belief loop. One indentation change, no side effects.
- **Regression test**: The Round 1 issue is fully resolved — premise agent beliefs (no `sl=`) stay in `in_nodes` giving N=5 where N²≠N, and 8 local beliefs exceed the `max(5,...)` floor so budget starvation is observable. The test provably fails with the bug and passes with the fix.

Only remaining action: run `uv run --extra test pytest tests/test_derive.py -v` to confirm execution (implementer couldn't run due to sandbox restrictions).

[Committed changes to reviewer branch]

### From Tester
All tests pass. Here's the summary:

**Tests:** 15 new test cases in `tests/test_derive_budget.py` covering the core regression, multiple agents, edge cases (empty network, no locals, single belief, derived agent beliefs), sampling mode, budget floor behavior, and a large network scenario. Plus the implementer's existing regression test.

**Mutation test:** Confirmed — re-introducing the bug causes the regression test to fail as expected.

**Full suite:** 411 tests pass (396 existing + 15 new), no regressions.

STATUS: TESTS_PASSED
OPEN_ISSUES: none

[Committed changes to tester branch]

### From User
Verdict: SATISFIED

Skipped - effort level does not include user testing

## Summary

- Reviewer verdict: APPROVED
- User verdict: SATISFIED
- Unresolved issues: 0
