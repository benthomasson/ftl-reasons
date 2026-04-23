# Test Report: Fix `_build_beliefs_section` belief count inflation (Issue #23)

## TEST CASES

### Tests Added

**File:** `tests/test_derive_budget.py` — 15 new test cases

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_count_is_linear_not_quadratic` | Core regression: 6 agent beliefs count as 6, not 36 |
| 2 | `test_multiple_agents_count_accumulates_correctly` | Count sums across 2 agents (4+3=7, not 16+9=25) |
| 3 | `test_single_agent_belief_no_inflation` | Degenerate case: N=1 where N²=N — fix doesn't break it |
| 4 | `test_no_agents_all_budget_to_local` | No agents → full budget to locals (unaffected code path) |
| 5 | `test_agent_fills_entire_budget` | Agent consumes full budget → locals get floor of 5 |
| 6 | `test_agent_exceeds_budget_locals_get_floor` | Agent exceeds budget → `max(5, ...)` floor still applies |
| 7 | `test_no_local_beliefs` | Agent-only network produces valid prompt, no crash |
| 8 | `test_empty_network` | Empty network produces valid prompt with zero beliefs |
| 9 | `test_derived_agent_beliefs_not_double_counted` | Derived agent beliefs excluded from `in_nodes`, don't inflate count |
| 10 | `test_sample_mode_budget_correct` | Sampling mode uses same count logic, locals not starved |
| 11 | `test_stats_total_in_correct` | Stats dict reflects actual IN count, not inflated |
| 12 | `test_budget_floor_protects_locals` | `max(5, ...)` floor guarantees ≥5 locals even with tight budget |
| 13 | `test_three_agents_count_accumulates` | Three agents: count = sum of shown, not quadratic per-agent |
| 14 | `test_large_network_budget_correct` | 50 agent + 50 local beliefs: locals get fair share |
| 15 | `test_build_beliefs_section_direct` | Calls `_build_beliefs_section` directly to verify output |

### Existing Regression Test (from implementer)

**File:** `tests/test_derive.py`, line 92 — `test_build_prompt_agent_count_does_not_starve_local`

### Mutation Test Results

Temporarily re-indented `count += len(belief_ids)` back inside the inner loop at `derive.py:214`. Result:
- `test_build_prompt_agent_count_does_not_starve_local` **FAILED** as expected
- Error: `"last local belief missing — agent count likely inflated the budget"`
- The test correctly detects the regression.

### Full Test Suite Results

```
411 passed in 1.44s
```

All tests pass, including the 15 new budget tests and all 396 pre-existing tests.

---

## USAGE INSTRUCTIONS FOR USER

### What Changed

The `_build_beliefs_section` function in `reasons_lib/derive.py` had a bug where the line `count += len(belief_ids)` was inside the per-belief `for` loop. This caused each agent's belief count to be multiplied by itself (N² instead of N), reducing the budget available for non-agent ("local") beliefs.

### How to Use the Derive Pipeline

#### 1. Initialize a reasons database

```bash
uv run reasons init
```

#### 2. Add beliefs to the network

```bash
# Add premises (base facts)
uv run reasons add fact-a "Alpha is true"
uv run reasons add fact-b "Beta is true"

# Add derived beliefs (with justifications)
uv run reasons add derived-ab "Alpha and Beta combined" --sl fact-a,fact-b

# Import agent beliefs (from another knowledge base)
uv run reasons import-json agent-export.json --agent agent-name
```

#### 3. Run the derive pipeline

The derive pipeline builds a prompt with the current belief network and asks an LLM to propose new derived beliefs.

```bash
# Basic derive (default budget=300)
uv run reasons derive

# With a custom budget (controls how many beliefs appear in the prompt)
uv run reasons derive --budget 50

# Filter to a specific topic
uv run reasons derive --topic auth

# Use sampling instead of alphabetical truncation
uv run reasons derive --sample --seed 42
```

#### 4. Review and accept proposals

```bash
# Accept proposals written to proposals.md
uv run reasons accept-beliefs
```

### How the Budget Works (Post-Fix)

When agent-namespaced beliefs exist (e.g., `agent-a:knows-auth`):

1. **Agent budget**: Each agent gets a proportional share of `budget` based on belief count
2. **Count**: After listing each agent's beliefs, `count` accumulates the number of beliefs shown (linearly)
3. **Local budget**: `remaining = max(5, budget - count)` — locals get the leftover, with a floor of 5

**Before the fix**, `count` grew as N² per agent, starving the local budget. **After the fix**, `count` grows linearly.

### Expected Output

When running `build_prompt` with agents and locals:
- Agent sections show proportional beliefs: `### Agent: agent-a (10 beliefs, showing 5)`
- Local section shows remaining beliefs: `### Local beliefs (8 beliefs, showing 8)`
- Stats dict includes: `total_in`, `total_derived`, `max_depth`, `agents`, `agent_names`

### Common Error Scenarios

| Scenario | What Happens | What to Do |
|----------|--------------|------------|
| No beliefs in network | Empty prompt, `total_in=0` | Add beliefs first |
| Agent beliefs are all derived (have `sl=`) | They don't appear in `in_nodes` | Expected — only premises are shown in the agent section |
| Very small budget with many agents | Locals get the floor of 5 | Increase budget or use `--topic` to filter |

---

## SELF-REVIEW

1. **What was easy to test?** The core regression was easy — the existing test from the implementer (`test_build_prompt_agent_count_does_not_starve_local`) is well-designed with a clear discriminating assertion. Edge cases (empty network, no agents, single agent) were also straightforward.

2. **What was hard?** Testing the budget floor behavior required careful arithmetic to set up scenarios where the floor (`max(5, ...)`) was the binding constraint. The proportional budget allocation per agent adds complexity — you need to understand how `agent_budget = max(5, int(max_beliefs * len(agent_beliefs) / total_all))` interacts with the count.

3. **What information was missing?** The plan's test outline was cut off, but the implementer designed a good test independently. The reviewer's feed-forward was clear and actionable.

4. **Any gaps revealed?** No gaps in the implementation. The fix is minimal and correct. One observation: the function doesn't return the `count` value, so we can only observe its effect indirectly through which local beliefs appear in the prompt. A direct unit test of `_build_beliefs_section` would be cleaner if the function returned structured data, but the current approach works.

---

## Verdict

STATUS: TESTS_PASSED
OPEN_ISSUES: none
