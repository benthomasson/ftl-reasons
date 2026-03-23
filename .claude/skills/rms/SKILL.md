---
name: rms
description: Reason Maintenance System — track justified beliefs with automatic retraction cascades and restoration
argument-hint: "[init|add|retract|assert|challenge|defend|convert-to-premise|summarize|nogood|trace|status|show|explain|search|list|hash-sources|check-stale|compact|propagate|import-beliefs|import-json|export|export-markdown|log] [args...]"
allowed-tools: Bash(reasons *), Bash(cd * && uv run reasons *), Bash(uvx *rms*), Read, Grep, Glob
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
1. `reasons $ARGUMENTS` (if installed via `uv tool install -e ~/git/rms`)
2. `cd ~/git/rms && uv run reasons $ARGUMENTS` (from repo directory)
3. `uvx --from git+https://github.com/benthomasson/rms rms $ARGUMENTS` (fallback)

## Key Concepts

- **Premise**: A node with no justifications — IN by default. Created when you `add` without `--sl` or `--cp`.
- **Justified node**: A node that is IN because its justification is valid. Goes OUT automatically when the justification fails.
- **SL justification** (Support List): Node is IN when ALL antecedents are IN. This is the main justification type.
- **Multiple justifications**: A node can have multiple justifications. It stays IN if ANY of them is valid. Only goes OUT when ALL fail.
- **Retraction cascade**: When a node goes OUT, all dependents whose justifications become invalid also go OUT — automatically, transitively.
- **Restoration**: When a retracted node comes back IN, dependents are recomputed — no manual rederivation needed.
- **Outlist** (non-monotonic): A justification can require nodes to be OUT (not just IN). "Believe X unless Y" — if Y goes IN, the justification fails. This enables default reasoning and defeasible inference.
- **Nogood**: A set of nodes that cannot all be IN simultaneously. When detected, dependency-directed backtracking traces to the responsible premise and retracts it.
- **Challenge/Defend**: Dialectical argumentation. Challenging a node makes it go OUT. Defending it neutralises the challenge. Multi-level chains are supported.

## Subcommand Behavior

### `init`
Run `reasons init` to create `rms.db` in the current directory. Use `--force` to reinitialize.

### `add`
Add a node to the network. Three forms:

```bash
# Premise (no justification — IN by default)
rms add node-id "Description of the belief"

# Justified by other nodes (SL = all antecedents must be IN)
rms add node-id "Description" --sl antecedent-a,antecedent-b

# Non-monotonic: believe X unless Y (outlist)
rms add node-id "Default holds" --unless counter-evidence
rms add node-id "X if A and not Y" --sl dep-a --unless dep-y

# With provenance
rms add node-id "Description" --sl dep-a --source "repo:path/to/file.md" --label "why this justification holds"
```

If the user describes a belief in natural language, convert it:
- Extract the node ID (kebab-case the key phrase)
- Extract the description text
- Identify dependencies → `--sl dep-a,dep-b`
- Identify source → `--source repo:path`

Example: "The threshold is tool-use calibration, based on beliefs-improve-accuracy"
becomes: `reasons add threshold-is-calibration "The threshold is tool-use calibration, not intelligence" --sl beliefs-improve-accuracy`

### `retract`
Run `reasons retract node-id`. The node goes OUT and the cascade propagates to all dependents. Report what was retracted.

**This is the most important operation.** When evidence invalidates a belief, retract it and let the network figure out what else falls. Do not manually retract dependents — the cascade handles it.

### `assert`
Run `reasons assert node-id`. The node comes back IN and dependents are restored. Use when a retracted belief is re-validated.

### `status`
Run `reasons status`. Shows all nodes with `[+]` (IN) or `[-]` (OUT) markers, justification counts, and an IN/total summary.

### `show`
Run `reasons show node-id`. Shows full details: text, status, source, justifications with antecedents, and dependents.

### `explain`
Run `reasons explain node-id`. Traces why a node is IN or OUT through the justification chain back to premises. This is the debugging command — use it when you need to understand why something is believed or not believed.

### `challenge`
Run `reasons challenge TARGET "reason"`. Creates a challenge node (IN by default) and adds it to the target's outlist. Target goes OUT immediately, cascading to dependents. Use `--id` for a custom challenge node ID.

Use when a reviewer or new evidence disputes a belief but you want to preserve the original argument (unlike `retract` which just marks it OUT).

### `defend`
Run `reasons defend TARGET CHALLENGE-ID "reason"`. Creates a defense node that neutralises the challenge. The challenge goes OUT, the target is restored. Multi-level chains work: challenge the defense, defend the defense, etc.

### `nogood`
Run `reasons nogood node-a node-b [node-c ...]`. Records a contradiction. Uses dependency-directed backtracking to trace backward through justification chains and retract the responsible *premise* with fewest dependents (minimal disruption), not an arbitrary node.

### `trace`
Run `reasons trace node-id`. Traces backward through justification chains to find all premises (nodes with no justifications) that a conclusion rests on. Answers "what assumptions is this built on?"

### `convert-to-premise`
Run `reasons convert-to-premise node-id`. Strips all justifications from a node, making it a premise (IN by default). Cascades restoration to dependents.

**Use after `import-beliefs`** when a `Depends on:` relationship in beliefs.md was contextual ("derived while investigating X") rather than logical ("true only if X is true"). The import treats all dependencies as SL justifications, which means nodes can be incorrectly OUT if their context-dependency was retracted. Converting to premise fixes this.

**Important:** `reasons assert` alone is NOT sufficient for this — it marks the node IN but doesn't remove the SL justification. The node will revert to OUT on the next recomputation. `convert-to-premise` removes the justification entirely.

### `hash-sources`
Run `reasons hash-sources`. Backfills SHA-256 source hashes for nodes that have a source path but no stored hash. Use `--force` to re-hash all nodes (after confirming source changes are expected).

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

**Caveat:** `import-beliefs` treats all `Depends on:` as SL justifications (all antecedents must be IN). If a dependency was contextual ("derived while investigating X") rather than logical ("true only if X is true"), the node may be incorrectly OUT. Use `reasons convert-to-premise` to fix these after import.

### `propagate`
Run `reasons propagate`. Recomputes all truth values from justifications. Use after manual database edits or to verify consistency.

### `log`
Run `reasons log` or `reasons log --last 20`. Shows the propagation audit trail — every add, retract, assert, and cascade event with timestamps.

### `search`
Run `reasons search "query"`. Case-insensitive substring match on both node ID and text. Shows truth value and dependent count.

Example: `reasons search "tool-use"` finds all nodes mentioning tool-use calibration.

### `list`
Run `reasons list` with optional filters:
- `--status IN` or `--status OUT` — filter by truth value
- `--premises` — only nodes with no justifications (the foundations)
- `--has-dependents` — only nodes that other nodes depend on (load-bearing)

Filters combine: `reasons list --status IN --premises` shows IN premises only.

### `export`
Run `reasons export`. Outputs the entire network as JSON.

### `export-markdown`
Run `reasons export-markdown`. Generates a `beliefs.md`-compatible markdown file from the DB. Use `-o beliefs.md` to write to file. The output is generated — operate through `rms`, not by editing the markdown.

### `check-stale`
Run `reasons check-stale`. Compares stored source hashes against current file content (SHA-256). Flags any IN node whose source file has changed. Exits 1 if any stale nodes found.

Source paths are resolved as `~/git/<repo-name>/<path>` from the `source` field.

### `compact`
Run `reasons compact`. Token-budgeted summary for CLAUDE.md or context injection. Priority: nogoods (never dropped) → OUT nodes → IN nodes by dependent count (most-depended-on first).

Options:
- `--budget 500` (default) — token limit
- `--no-truncate` — show full node text instead of 80-char truncation

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

### Generating readable output
```bash
rms export-markdown -o beliefs.md
# beliefs.md is now a generated snapshot, not an input
```

### Checking for stale sources
```bash
rms check-stale
# Flags nodes whose source files have changed since registration
```

### Context injection for agents
```bash
rms compact --budget 500
# Token-budgeted summary suitable for CLAUDE.md or system prompts
```

### Finding specific beliefs
```bash
rms search "calibration"
rms list --premises              # what are the foundations?
rms list --has-dependents        # what's load-bearing?
rms list --status OUT            # what was retracted?
rms list --challenged            # what has active challenges?
```

### Dialectical argumentation (peer review)
```bash
# Reviewer challenges a belief
rms challenge velocity-constraint "Not derived — postulated without proof"
# velocity-constraint goes OUT, all dependents cascade

# Author defends
rms defend velocity-constraint challenge-velocity-constraint \
  "Follows from variational principle on elastic medium"
# challenge goes OUT, velocity-constraint restored

# Reviewer challenges the defense
rms challenge defense-challenge-velocity-constraint "Variational argument is circular"
# defense goes OUT, challenge restored, velocity-constraint OUT again
```

### Tracing assumptions
```bash
rms trace conclusion-node        # what premises does this rest on?
rms explain conclusion-node      # why is this IN or OUT? (forward trace)
```

## After Any Command

- After `retract`: report what cascaded and suggest running `status` to see the new belief set
- After `challenge`: report what went OUT and the blast radius
- After `defend`: report what was restored
- After `import-beliefs`: report counts and suggest `status` to review
- After `nogood`: report what premise was backtracked to and what cascaded
- After `explain`: summarize the justification chain in plain language
- After `trace`: summarize which premises the conclusion rests on
- Keep responses concise — the tool output speaks for itself

## Storage

RMS uses SQLite (`rms.db`), not markdown. This provides ACID transactions during propagation cascades — a retraction that touches 20 nodes either completes fully or not at all. The `--db` flag overrides the database path.
