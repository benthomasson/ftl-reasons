# Plan: Fix `_build_beliefs_section` belief count inflation

## Requirements

Fix a one-line indentation bug in `_build_beliefs_section` (`reasons_lib/derive.py`). The line `count += len(belief_ids)` is inside the per-belief `for` loop (line 214), so it runs once per belief instead of once per agent. This multiplies the agent belief count by itself (`n * n` instead of `n`), inflating `count` and starving the non-agent budget on line 218.

**Why it matters:** The inflated `count` makes `remaining = max(5, max_beliefs - count)` much smaller than intended, so fewer non-agent beliefs appear in the derive prompt. This distorts the LLM's view of the belief network and blocks 9 downstream derived beliefs.

## Implementation

### Step 1: Fix the indentation bug

| File | Line(s) | Change |
|------|---------|--------|
| `reasons_lib/derive.py` | 214 | Dedent `count += len(belief_ids)` by one level so it's inside the per-agent loop but outside the per-belief loop. It should align with the `for belief_id in belief_ids:` line (line 211), not be indented under it. |

**Before** (lines 211-214):
```python
            for belief_id in belief_ids:
                text = agent_beliefs[belief_id]["text"][:120]
                lines.append(f"- `{belief_id}`: {text}")
                count += len(belief_ids)
```

**After:**
```python
            for belief_id in belief_ids:
                text = agent_beliefs[belief_id]["text"][:120]
                lines.append(f"- `{belief_id}`: {text}")
            count += len(belief_ids)
```

That's it for the production code. One line, one indentation change.

### Step 2: Add a regression test

There is no existing test for `_build_beliefs_section` count behavior. The function is private but its effect is observable through `build_prompt` stats and output.

| File | Line(s) | Change |
|------|---------|--------|
| `tests/test_derive.py` | after line 88 (end of `test_build_prompt_detects_agents`) | Add a new test `test_build_prompt_agent_count_does_not_inflate` |

The test should:
1. Use the existing `agent_network` fixture (2 agents, 5 namespaced beliefs total).
2. Call `build_prompt` with a small `budget` (e.g., 10).
3. Verify that non-agent beliefs (if any exist) still appear in the output — or more directly, add a local (non-namespaced) belief to the fixture and verify it's present in the prompt.
4. Alternatively: add `_build_beliefs_section` to the test imports and call it directly, asserting the returned count equals the number of agent beliefs (not their square).

**Decision:** Import and test `_build_beliefs_section` directly. The test file already imports several private functions from `derive.py`. Direct testing is clearer and avoids coupling to `build_prompt`'s formatting.

Add to the import list at line 8-21:
```python
from reasons_lib.derive import (
    ...
    _build_beliefs_section,
)
```

Test body:
```python
def test_build_beliefs_section_count_not_inflated(agent_network):
    """Regression: count must accumulate once per agent, not once per belief."""
    data = api.export_network(db_path=agent_network)
    nodes = data["nodes"]
    agents = _detect_agents(nodes)
    
    # _build_beliefs_section returns (lines, section_text) — we need to inspect the count
    # But the function doesn't return count. Instead, verify the non-agent budget isn't starved:
    # Add a non-agent belief and confirm it appears.
    api.add_node("local-fact", "A local non-agent belief", db_path=agent_network)
    data = api.export_network(db_path=agent_network)
    prompt, stats = build_prompt(data["nodes"], budget=20)
    assert "local-fact" in prompt
```

**Decision on test approach:** Since `_build_beliefs_section` doesn't return the count value, test through `build_prompt` by adding a non-agent belief and confirming it survives the budget. With the bug, the inflated count would push `remaining` to 5 (the floor), but with only 5 agent beliefs the correct count is 5, leaving `remaining = max(5, 20-5) = 15` — plenty of room. The test asserts `local-fact` appears in the prompt. This is sufficient because with the bug and a tight budget, non-agent beliefs get squeezed out.

## Key Decisions

1. **Scope:** Fix only the indentation bug. No refactoring of `_build_beliefs_section` or adjacent code.
2. **Test strategy:** Integration test through `build_prompt` rather than exposing `count` from `_build_beliefs_section`. Avoids changing the function signature.
3. **No version bump:** This is a bugfix to internal derive logic, not a user-facing API change.

## Success Criteria

1. `count` accumulates `len(belief_ids)` once per agent, not once per belief.
2. Non-agent budget (`remaining`) is calculated from the correct count.
3. All existing tests pass (`pytest tests/`).
4. New regression test passes and would fail if the fix were reverted.
5. Closes #23.
