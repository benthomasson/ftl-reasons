All tests pass. Here's the summary:

**Tests:** 15 new test cases in `tests/test_derive_budget.py` covering the core regression, multiple agents, edge cases (empty network, no locals, single belief, derived agent beliefs), sampling mode, budget floor behavior, and a large network scenario. Plus the implementer's existing regression test.

**Mutation test:** Confirmed — re-introducing the bug causes the regression test to fail as expected.

**Full suite:** 411 tests pass (396 existing + 15 new), no regressions.

STATUS: TESTS_PASSED
OPEN_ISSUES: none

[Committed changes to tester branch]