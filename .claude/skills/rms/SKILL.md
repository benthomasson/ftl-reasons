---
name: rms
description: Reason Maintenance System — track justified beliefs with automatic retraction cascades and restoration
argument-hint: "[init|add|retract|assert|status|show|explain|nogood|propagate|import-beliefs|log|export] [args...]"
allowed-tools: Bash(rms *), Bash(cd * && uv run rms *), Bash(uvx *rms*), Read, Grep, Glob
---

You are managing a dependency network using the `rms` CLI tool. Unlike `beliefs` (which tracks independent facts for expert registries), `rms` tracks **justified conclusions** where beliefs depend on other beliefs and changes propagate automatically.

## When to Use `rms` vs `beliefs`

| Use `beliefs` when | Use `rms` when |
|---|---|
| Facts are independent (no dependency chains) | Conclusions build on premises (dependency chains) |
| Expert/knowledge registries (RHEL, agents-python) | Research registries (physics, bethe, beliefs-pi) |
| Staleness = source file changed | Staleness = upstream belief retracted |
| Maintenance = check-stale, contradictions | Maintenance = retraction cascades, backtracking |
| Density 0.00 (flat) | Density 0.74+ (dense) |

**Rule of thumb:** If beliefs depend on other beliefs, use `rms`. If beliefs depend only on external sources, use `beliefs`.

## How to Run

Try these in order until one works:
1. `rms $ARGUMENTS` (if installed via `uv tool install -e ~/git/rms`)
2. `cd ~/git/rms && uv run rms $ARGUMENTS` (from repo directory)
3. `uvx --from git+https://github.com/benthomasson/rms rms $ARGUMENTS` (fallback)

## Key Concepts

- **Premise**: A node with no justifications — IN by default. Created when you `add` without `--sl` or `--cp`.
- **Justified node**: A node that is IN because its justification is valid. Goes OUT automatically when the justification fails.
- **SL justification** (Support List): Node is IN when ALL antecedents are IN. This is the main justification type.
- **Multiple justifications**: A node can have multiple justifications. It stays IN if ANY of them is valid. Only goes OUT when ALL fail.
- **Retraction cascade**: When a node goes OUT, all dependents whose justifications become invalid also go OUT — automatically, transitively.
- **Restoration**: When a retracted node comes back IN, dependents are recomputed — no manual rederivation needed.
- **Nogood**: A set of nodes that cannot all be IN simultaneously. When detected, the least-entrenched node is retracted.

## Subcommand Behavior

### `init`
Run `rms init` to create `rms.db` in the current directory. Use `--force` to reinitialize.

### `add`
Add a node to the network. Three forms:

```bash
# Premise (no justification — IN by default)
rms add node-id "Description of the belief"

# Justified by other nodes (SL = all antecedents must be IN)
rms add node-id "Description" --sl antecedent-a,antecedent-b

# With provenance
rms add node-id "Description" --sl dep-a --source "repo:path/to/file.md" --label "why this justification holds"
```

If the user describes a belief in natural language, convert it:
- Extract the node ID (kebab-case the key phrase)
- Extract the description text
- Identify dependencies → `--sl dep-a,dep-b`
- Identify source → `--source repo:path`

Example: "The threshold is tool-use calibration, based on beliefs-improve-accuracy"
becomes: `rms add threshold-is-calibration "The threshold is tool-use calibration, not intelligence" --sl beliefs-improve-accuracy`

### `retract`
Run `rms retract node-id`. The node goes OUT and the cascade propagates to all dependents. Report what was retracted.

**This is the most important operation.** When evidence invalidates a belief, retract it and let the network figure out what else falls. Do not manually retract dependents — the cascade handles it.

### `assert`
Run `rms assert node-id`. The node comes back IN and dependents are restored. Use when a retracted belief is re-validated.

### `status`
Run `rms status`. Shows all nodes with `[+]` (IN) or `[-]` (OUT) markers, justification counts, and an IN/total summary.

### `show`
Run `rms show node-id`. Shows full details: text, status, source, justifications with antecedents, and dependents.

### `explain`
Run `rms explain node-id`. Traces why a node is IN or OUT through the justification chain back to premises. This is the debugging command — use it when you need to understand why something is believed or not believed.

### `nogood`
Run `rms nogood node-a node-b [node-c ...]`. Records a contradiction and retracts the least-entrenched node. Use when you discover that two or more beliefs cannot both be true.

### `import-beliefs`
Import a `beliefs.md` registry into the RMS network:

```bash
rms import-beliefs path/to/beliefs.md
```

This converts a beliefs CLI registry into RMS nodes:
- IN claims with `Depends on:` → SL-justified nodes
- IN claims without dependencies → premises
- STALE/OUT claims → retracted nodes (preserved for restoration)
- `nogoods.md` auto-detected next to `beliefs.md`, or specify with `--nogoods path/to/nogoods.md`

**Use this to migrate research registries from `beliefs` to `rms`.** After import, retraction cascades work on the imported dependency graph.

### `propagate`
Run `rms propagate`. Recomputes all truth values from justifications. Use after manual database edits or to verify consistency.

### `log`
Run `rms log` or `rms log --last 20`. Shows the propagation audit trail — every add, retract, assert, and cascade event with timestamps.

### `export`
Run `rms export`. Outputs the entire network as JSON.

## Common Workflows

### Starting a new research registry
```bash
rms init
rms add observation-1 "What we observed" --source "repo:entries/2026/03/17/finding.md"
rms add observation-2 "Another observation"
rms add conclusion-1 "What follows from both" --sl observation-1,observation-2
```

### Importing from beliefs and then working
```bash
rms init --force
rms import-beliefs ~/git/my-project/beliefs.md
rms status
# Now use retract/assert as evidence changes
```

### Evidence invalidates a foundation
```bash
rms retract observation-1
# Cascade: conclusion-1 also goes OUT (lost its justification)
rms status  # see what's still believed
rms explain conclusion-1  # see why it went OUT
```

### New evidence restores a belief
```bash
rms assert observation-1
# Cascade: conclusion-1 restored (justification valid again)
```

### Recording a contradiction
```bash
rms nogood belief-a belief-b
# One gets retracted, cascade propagates
```

## After Any Command

- After `retract`: report what cascaded and suggest running `status` to see the new belief set
- After `import-beliefs`: report counts and suggest `status` to review
- After `nogood`: report what was retracted and why
- After `explain`: summarize the justification chain in plain language
- Keep responses concise — the tool output speaks for itself

## Storage

RMS uses SQLite (`rms.db`), not markdown. This provides ACID transactions during propagation cascades — a retraction that touches 20 nodes either completes fully or not at all. The `--db` flag overrides the database path.
