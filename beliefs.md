# Beliefs Registry

## Repos


### plan-1-1 [IN] AXIOM
**What went well:** The bug is unambiguous — wrong indentation level, clear before/after. The existing test file and fixtures made it easy to design a regression test.
- Date: 2026-04-23

### plan-1-2 [IN] AXIOM
**What I was missing:** `_build_beliefs_section` doesn't return `count`, so I can't directly assert on it. I had to design the test to observe the *effect* of the inflated count (non-agent budget star
- Date: 2026-04-23

### plan-1-3 [IN] AXIOM
**What would help next time:** If the function returned a stats dict (like `build_prompt` does), the test could be more precise. But changing that is out of scope for this fix.
- Date: 2026-04-23

### test-1-1 [IN] OBSERVATION
Tests TESTS_PASSED
- Date: 2026-04-23
