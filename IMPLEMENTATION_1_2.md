# Implementation (Iteration 1, Attempt 2)

## Implementation Summary

### Files Modified

1. **`reasons_lib/derive.py`** (line 214)
   - Dedented `count += len(belief_ids)` one level — moved it outside the `for belief_id in belief_ids:` loop but kept it inside the per-agent loop. This was the one-line production fix.

2. **`tests/test_derive.py`** (inserted after line 89)
   - Added `test_build_prompt_agent_count_does_not_starve_local` regression test.

### Self-Review

1. **Source files modified:**
   - `reasons_lib/derive.py`
   - `tests/test_derive.py`

2. **What went well:** The production fix was unambiguous — one indentation change. The second iteration of the test (after reviewer feedback) correctly exercises the bug: premise agent beliefs stay in `in_nodes` so N=5 makes the N²=25 vs N=5 difference visible, and 8 local beliefs exceed the `max(5, ...)` floor so budget starvation is observable.

3. **What was unclear in the plan:** Nothing in the production fix. The plan's test outline was incomplete (cut off), so I designed the test independently. My first attempt used `sl=` on agent beliefs, which made them derived and invisible to `in_nodes` — the reviewer caught this correctly.

4. **Concerns for the reviewer:**
   - **Tests were not executed** due to sandbox directory restrictions. The reviewer should run `uv run --extra test pytest tests/test_derive.py -v` to confirm all tests pass.
   - The test asserts on `local-belief-07` appearing in the prompt. The math: with `budget=15` and 5 agent premises, the fixed code gives `remaining = max(5, 15-5) = 10` (all 8 locals fit), while the buggy code would give `remaining = max(5, 15-25) = 5` (only `local-belief-00` through `local-belief-04` fit alphabetically, so `local-belief-07` is missing). This makes the test a reliable discriminator between buggy and fixed code.