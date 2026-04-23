I've reviewed all the changed files and traced every code path that appends raw `Nogood` objects to the network. Here's my review.

---

## FEEDBACK FOR IMPLEMENTER

**Correctness — core fix: Solid.** The `_compute_next_nogood_id()` method correctly uses `re.fullmatch` to scan existing nogoods, extract max numeric suffix, and set the counter to `max + 1`. The `add_nogood` method correctly uses and increments the counter. The regex properly rejects prefixed IDs like `agent:nogood-099`.

**Correctness — missed call site: Bug.** `import_beliefs.py:import_into_network` (line 241) appends raw `Nogood` objects with non-prefixed IDs (`nogood-001`, `nogood-002`, etc.) and does **not** call `_compute_next_nogood_id()` afterward. This is the exact same class of bug the fix is meant to solve.

In the `api.py:import_beliefs` path, the save/reload cycle happens to fix it (because `storage.load()` calls `_compute_next_nogood_id()`), but `import_into_network` is a public function. Any caller that uses it directly and then calls `add_nogood()` on the same network object will get ID collisions.

**Required change:** Add `network._compute_next_nogood_id()` after the nogood import loop in `import_beliefs.py:import_into_network`, around line 242:

```python
            network.nogoods.append(nogood)
            nogoods_imported += 1

    network._compute_next_nogood_id()  # <-- add this
```

**Minor note (not blocking):** The `import_agent.py:_import_nogoods` function also appends raw `Nogood` objects but uses prefixed IDs (`agent:nogood-XXX`), which the regex correctly ignores. No action needed, but a defensive `_compute_next_nogood_id()` call there would guard against future format changes.

---

## FEED-FORWARD FOR TESTER

**Key behaviors to test:**
1. Create nogoods, delete one from the middle, recompute, add another — verify no ID collision (covered by existing test)
2. Round-trip through SQLite: save network with nogoods, reload, add new nogood — verify counter continuity
3. `import_json` with nogoods, then `add_nogood` on the same network object — verify no collision
4. `import_beliefs` with nogoods, then `add_nogood` on the same network object — **this is the gap**, should be tested after the fix

**Edge cases:**
- Import nogoods with gaps in numbering (e.g., `nogood-001`, `nogood-005`) — counter should be 6
- Mix of prefixed and unprefixed nogoods — only unprefixed should affect counter
- Large nogood numbers (>999) — verify `:03d` formatting doesn't truncate (it doesn't, but worth a quick check)
- Import empty nogoods list — counter stays at its previous value

**Suggested test scenario for the bug:**
```python
def test_import_beliefs_then_add_nogood():
    net = Network()
    net.add_node("a", "A"); net.add_node("b", "B")
    # Simulate what import_into_network does
    net.nogoods.append(Nogood(id="nogood-001", nodes=["a", "b"], discovered=""))
    net._compute_next_nogood_id()  # after fix
    net.add_node("c", "C"); net.add_node("d", "D")
    net.add_nogood(["c", "d"])
    assert net.nogoods[-1].id == "nogood-002"  # not "nogood-001"
```

---

## SELF-REVIEW

1. **Easy to review:** The core fix is small, well-scoped, and mechanically obvious. The `_compute_next_nogood_id()` method is straightforward. Tests directly verify the stated invariant.

2. **What made review harder:** Tracing all code paths that append raw `Nogood` objects required reading 4 files (`network.py`, `storage.py`, `api.py`, `import_agent.py`, `import_beliefs.py`). The implementer's self-review flagging `import_agent.py` was helpful — it prompted me to also check `import_beliefs.py`, which is where the actual bug is.

3. **What would help next time:** A grep for `nogoods.append` in the implementer's notes would have caught the `import_beliefs.py` path. When a fix touches all callers of a pattern, listing every call site found (even if no change needed) makes the review faster.

4. **For the implementer:** When fixing a bug class (here: "raw append without counter update"), search exhaustively for every instance of the pattern (`nogoods.append`). The one you checked (`import_agent.py`) was safe by accident (prefixed IDs). The one you didn't check (`import_beliefs.py`) has the bug.

---

## Verdict

STATUS: NEEDS_CHANGES
OPEN_ISSUES:
- `import_beliefs.py:import_into_network` appends raw Nogood objects with non-prefixed IDs but does not call `network._compute_next_nogood_id()` afterward — same class of bug the fix is solving