# Beliefs Registry

## Repos


### review-warn-1-1-1 [IN] WARNING
`import_beliefs.py:import_into_network` appends raw Nogood objects with non-prefixed IDs but does not call `network._compute_next_nogood_id()` afterward — same class of bug the fix is solving
- Date: 2026-04-23

### test-1-1 [IN] OBSERVATION
Tests TESTS_PASSED
- Date: 2026-04-23
