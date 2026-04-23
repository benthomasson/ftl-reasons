# Code Review: Fix `_build_beliefs_section` belief count inflation (Round 2)

## FEEDBACK FOR IMPLEMENTER

### Production fix: CORRECT

The dedent of `count += len(belief_ids)` at `derive.py:214` is correct. It runs once per agent after the inner loop, accumulating the actual number of beliefs shown rather than N² per agent. Minimal, targeted, no side effects.

### Regression test: NOW EFFECTIVE

The updated `test_build_prompt_agent_count_does_not_starve_local` (lines 92-119) addresses all issues from Round 1:

1. **Premise agent beliefs** (no `sl=`) — they stay in `in_nodes` instead of being excluded as derived nodes. This gives N=5 agent beliefs where N²=25 ≠ N=5.
2. **8 local beliefs** — exceeds the `max(5, ...)` floor so budget starvation is observable (only 5 of 8 would survive with the bug).
3. **`budget=15`** — small enough that the quadratic inflation (count=25 > budget=15) starves locals, but large enough that the correct count (5) leaves room for all 8.
4. **Assertion on `local-belief-07`** — the 8th local belief (alphabetically last) is the canary. With the bug it's excluded (only 5 locals fit); with the fix it's included (all 8 fit in remaining=10).

The inline math comments (lines 113-114) document the discriminating logic clearly. The error message on assertion failure points the developer directly at the root cause.

**No issues found. Both changes are correct and ready to merge.**

One note: the implementer flagged that tests were not executed due to sandbox restrictions. The tester should run `uv run --extra test pytest tests/test_derive.py -v` to confirm.

## FEED-FORWARD FOR TESTER

### Key behaviors to test
- Run `uv run --extra test pytest tests/test_derive.py -v` — all tests should pass
- **Mutation test**: temporarily re-indent `count += len(belief_ids)` back inside the for loop in `derive.py:214` and verify `test_build_prompt_agent_count_does_not_starve_local` fails. This confirms the test catches the regression.

### Edge cases to consider
- Multiple agents with varying belief counts — count should be sum of per-agent N, not sum of N²
- Agent with all derived beliefs (like the original `agent_network` fixture with `sl=`) — count should only include premise beliefs that survive into `in_nodes`
- `budget` smaller than agent count — `max(5, ...)` floor still guarantees 5 local slots
- Very large networks — verify no performance regression from the fix (though this is just indentation)

### Suggested test scenarios
1. Run the full test suite to check for regressions: `uv run --extra test pytest tests/ -v`
2. Spot-check `build_prompt` output with a real network (`network.json`) to verify prompt quality isn't affected
3. If possible, re-run a derive pass to confirm the 9 gated beliefs can now be derived with the corrected budget

### Areas of concern
- The fix changes token budget allocation for the LLM prompt. While the fix is correct (restoring intended behavior), any existing derived beliefs were created under the buggy budget. They should still be valid, but the tester should verify no existing derivations break.

## SELF-REVIEW

1. **What was easy to review:** The production fix is trivially verifiable — one indentation level. The updated test has clear inline comments documenting the expected math for buggy vs. fixed code, making it possible to verify by reading rather than running.

2. **What made review difficult:** Nothing this round. The implementer's self-review included a complete trace of the test math (buggy count=25 → remaining=5 → 07 missing; fixed count=5 → remaining=10 → 07 present), which made verification straightforward.

3. **What would help next time:** The implementer did everything right this round: clear self-review, math trace, documented concerns. The only gap is test execution — if sandbox restrictions could be relaxed, implementer-run tests would eliminate the last uncertainty.

4. **For future reviews:** When writing regression tests for numerical bugs, include the discriminating math as comments in the test (as was done here on lines 113-114). This makes the test self-documenting and reviewable without running it.

## Verdict

Production fix is correct. Regression test now properly catches the bug (fails with buggy code, passes with fixed code). Previous round's feedback was fully addressed. Tests should be executed by the tester to confirm.

STATUS: APPROVED
OPEN_ISSUES: none
