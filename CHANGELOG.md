# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.18.0] - 2026-04-25

### Added
- Access tags (`access_tags`) for data source provenance filtering (RBAC) (#38, PR #42)
- `--visible-to` flag on all read commands: `show`, `list`, `search`, `lookup`, `status`, `explain`, `trace`, `export`, `export-markdown`, `compact`
- `trace-access-tags` command to audit tag provenance through dependency chains
- `--access-tags` flag on `add` command
- Tag inheritance: derived nodes automatically inherit union of parent access tags
- Forward tag propagation: adding justifications cascades tags to existing dependents
- `PermissionError` on single-node queries (`show`, `explain`, `trace`) when access denied
- Nogood filtering in exports: nogoods referencing restricted nodes are excluded
- CLI test suite: 63 tests covering 27 commands (cli.py 0% -> 60% coverage)
- `--version` flag on CLI

## [0.17.0] - 2026-04-18

### Added
- `add-justification` command to add justifications to existing nodes
- `--any` flag for OR-mode justifications (one SL per premise instead of conjunctive)
- 3+ premise warning with `--any` tip when AND-mode might not be intended
- Restoration hints on retraction: suggests `--any` when multi-premise nodes go OUT with surviving premises
- `sync-agent` command for updating beliefs after initial import (remote-wins reconciliation)

## [0.16.0] - 2026-04-18

### Fixed
- Import-agent: moved active premise from antecedent to outlist so per-belief retraction works independently (#16, PR #17)
- `_retracted` flag now set even when node is already OUT
- Internal metadata keys (`_retracted`, etc.) filtered from JSON export

## [0.15.0] - 2026-04-18

### Added
- `--min-depth` and `--max-depth` filters on `derive` and `list` commands
- `--premises` and `--has-dependents` filters on `derive`
- Depth computation from full graph before filtering

### Fixed
- `max_depth` recomputed after any filter, not just depth filters
- Cycle guard in depth computation

## [0.14.0] - 2026-04-17

### Fixed
- Outlist/supersession preserved during import-agent (#11, PR #14)
- JSON import path validates outlist references
- Propagation runs after import-agent to fix truth values (#9, PR #12)
- `recompute_all` uses fixpoint iteration with iteration cap (#12)
- Backtick-wrapped IDs stripped in derive format parser (#10, PR #13)

## [0.13.0] - 2026-04-17

### Added
- GitHub Actions CI workflow for running tests on push and PR (#8)

### Fixed
- Retract/assert cascade output split into "Went OUT" and "Went IN" sections (#7)
- Deduplicate: rewrite dependents' justifications when retracting duplicates (#6)
- Accept/derive guards against re-introducing retracted beliefs under variant IDs (#5)

## [0.12.0] - 2026-04-17

### Added
- `deduplicate` command with Jaccard similarity clustering, auto-retract, and review-then-accept workflow

## [0.10.0] - 2026-03-29

### Added
- `accept` command for applying derive proposals from file
- `--exhaust` flag on `derive`: repeat until saturation (0.9.0)
- Topic filter, budget, and random sampling on `derive` (0.8.0)

## [0.7.0] - 2026-03-28

### Added
- `derive` command: propose deeper reasoning chains from existing beliefs via LLM
- `import-agent` command: multi-agent belief tracking with namespace prefixing and kill-switch

## [0.6.0] - 2026-03-24

### Added
- `what-if` command for read-only retraction/assertion simulation with depth-grouped output

### Fixed
- Missing `Path` import in cli.py `export-markdown`

## [0.5.0] - 2026-03-24

### Added
- `what-if retract` command for read-only retraction simulation

## [0.4.0] - 2026-03-23

### Added
- `supersede` command: model belief supersession via outlist mechanism (#3)
- `--reason` flag on `retract` command with audit trail (#1)
- Repos as first-class citizens with SQLite table (#2)
- Retract reason included in `export-markdown` and `compact` output

## [0.3.0] - 2026-03-23

### Changed
- Renamed from `rms` to `reasons` (CLI, library, package) based on 5pp LLM accuracy improvement in ablation study
- Published to PyPI as `ftl-reasons`

## [0.2.0] - 2026-03-23

### Added
- PyPI packaging with readme and license
- `lookup` command: simple flat-text belief search
- FTS5 full-text search upgrade with markdown output and neighbor expansion
- `convert-to-premise` command
- `import-json` for lossless JSON round-trip
- Summarization justifications: abstract over groups of nodes

### Fixed
- Backtracking: entrenchment scoring protects evidence over speculation
- Lookup searches full belief block including source, deps, metadata

## [0.1.0] - 2026-03-23

### Added
- Initial TMS implementation: nodes, justifications, truth value propagation
- SL justifications with retraction cascades and restoration
- Non-monotonic reasoning via outlist ("believe X unless Y")
- Dependency-directed backtracking with nogood detection
- Dialectical argumentation: `challenge` and `defend` commands
- `hash-sources` command for source file change detection
- SQLite persistence with ACID transactions
- Python API layer (`reasons_lib.api`) returning dicts for CLI and tool-call consumers
- CLI with `add`, `retract`, `assert`, `status`, `show`, `explain`, `trace`, `search`, `list`, `nogood`, `propagate`, `log` commands
- `import-beliefs` for parsing beliefs.md into the network
- `export-markdown`, `check-stale`, `compact` commands
