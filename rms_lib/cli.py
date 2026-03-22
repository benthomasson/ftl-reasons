"""CLI for the Reason Maintenance System.

Thin wrappers around rms_lib.api — each command calls an api function
and formats the result dict for terminal output.
"""

import argparse
import json
import sys

from . import api


def cmd_init(args):
    try:
        result = api.init_db(db_path=args.db, force=args.force)
        print(f"Initialized RMS database: {result['db_path']}")
    except FileExistsError as e:
        print(f"{e}", file=sys.stderr)
        print("Use --force to reinitialize.", file=sys.stderr)
        sys.exit(1)


def cmd_add(args):
    try:
        result = api.add_node(
            node_id=args.node_id,
            text=args.text,
            sl=args.sl or "",
            cp=args.cp or "",
            unless=args.unless or "",
            label=args.label or "",
            source=args.source or "",
            db_path=args.db,
        )
        print(f"Added {result['node_id']} [{result['truth_value']}] ({result['type']})")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_retract(args):
    try:
        result = api.retract_node(args.node_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["changed"]:
        print(f"{args.node_id} is already OUT")
    else:
        print(f"Retracted: {', '.join(result['changed'])}")


def cmd_assert(args):
    try:
        result = api.assert_node(args.node_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["changed"]:
        print(f"{args.node_id} is already IN")
    else:
        print(f"Asserted: {', '.join(result['changed'])}")


def cmd_status(args):
    result = api.get_status(db_path=args.db)

    if not result["nodes"]:
        print("No nodes in the network.")
        return

    for node in result["nodes"]:
        marker = "+" if node["truth_value"] == "IN" else "-"
        jcount = node["justification_count"]
        jinfo = f"  ({jcount} justification{'s' if jcount != 1 else ''})" if jcount else "  (premise)"
        print(f"  [{marker}] {node['id']}: {node['text']}{jinfo}")

    print(f"\n{result['in_count']}/{result['total']} IN")


def cmd_show(args):
    try:
        node = api.show_node(args.node_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"ID:     {node['id']}")
    print(f"Text:   {node['text']}")
    print(f"Status: {node['truth_value']}")
    if node["source"]:
        print(f"Source: {node['source']}")
    if node["source_hash"]:
        print(f"Hash:   {node['source_hash']}")

    if node["justifications"]:
        print(f"\nJustifications ({len(node['justifications'])}):")
        for j in node["justifications"]:
            ants = ", ".join(j["antecedents"])
            label = f" [{j['label']}]" if j["label"] else ""
            print(f"  {j['type']}({ants}){label}")
    else:
        print("\nPremise (no justifications)")

    if node["dependents"]:
        print(f"\nDependents: {', '.join(node['dependents'])}")


def cmd_explain(args):
    try:
        result = api.explain_node(args.node_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for step in result["steps"]:
        nid = step["node"]
        tv = step["truth_value"]
        reason = step["reason"]
        marker = "+" if tv == "IN" else "-"
        line = f"  [{marker}] {nid}: {reason}"
        if "antecedents" in step:
            line += f" — antecedents: {', '.join(step['antecedents'])}"
        if "outlist" in step:
            line += f" — unless: {', '.join(step['outlist'])}"
        if "failed_antecedents" in step:
            line += f" — failed: {', '.join(step['failed_antecedents'])}"
        if "violated_outlist" in step:
            line += f" — violated unless: {', '.join(step['violated_outlist'])}"
        if step.get("label"):
            line += f" [{step['label']}]"
        print(line)


def cmd_convert_to_premise(args):
    try:
        result = api.convert_to_premise(args.node_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Converted {result['node_id']} to premise (stripped {result['old_justifications']} justification(s))")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


def cmd_summarize(args):
    over = [n.strip() for n in args.over.split(",")]
    try:
        result = api.summarize(
            args.summary_id, args.text, over,
            source=args.source or "",
            db_path=args.db,
        )
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Created summary {result['summary_id']} [{result['truth_value']}] over {len(result['over'])} nodes")


def cmd_challenge(args):
    try:
        result = api.challenge(
            args.target_id, args.reason,
            challenge_id=args.id,
            db_path=args.db,
        )
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Challenged {result['target_id']} with {result['challenge_id']}")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


def cmd_defend(args):
    try:
        result = api.defend(
            args.target_id, args.challenge_id, args.reason,
            defense_id=args.id,
            db_path=args.db,
        )
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Defended {result['target_id']} against {result['challenge_id']} with {result['defense_id']}")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


def cmd_nogood(args):
    try:
        result = api.add_nogood(args.node_ids, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Recorded {result['nogood_id']}: {', '.join(result['nodes'])}")
    if result["backtracked_to"]:
        print(f"Backtracked to premise: {result['backtracked_to']}")
    if result["changed"]:
        print(f"Retracted: {', '.join(result['changed'])}")


def cmd_trace(args):
    try:
        result = api.trace_assumptions(args.node_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["premises"]:
        print(f"{args.node_id} is a premise (no dependencies).")
        return

    print(f"{args.node_id} rests on {len(result['premises'])} premise(s):")
    for pid in result["premises"]:
        node = api.show_node(pid, db_path=args.db)
        marker = "+" if node["truth_value"] == "IN" else "-"
        deps = f"  ({len(node['dependents'])} dependents)" if node["dependents"] else ""
        print(f"  [{marker}] {pid}: {node['text'][:80]}{deps}")


def cmd_propagate(args):
    # Propagate is a special case — not in api.py since it's a maintenance operation
    from .storage import Storage
    store = Storage(args.db)
    net = store.load()

    changed = []
    for node in net.nodes.values():
        if node.justifications:
            old = node.truth_value
            new = net._compute_truth(node)
            if old != new:
                node.truth_value = new
                changed.append(node.id)

    store.save(net)
    store.close()

    if changed:
        print(f"Updated: {', '.join(changed)}")
    else:
        print("All truth values are current.")


def cmd_log(args):
    result = api.get_log(last=args.last, db_path=args.db)

    if not result["entries"]:
        print("No propagation events.")
        return

    for entry in result["entries"]:
        print(f"  {entry['timestamp']}  {entry['action']:10s}  {entry['target']:20s}  {entry['value']}")


def cmd_import_beliefs(args):
    try:
        result = api.import_beliefs(
            beliefs_file=args.beliefs_file,
            nogoods_file=args.nogoods_file,
            db_path=args.db,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Imported {result['claims_imported']} claims ({result['claims_retracted']} retracted)")
    if result['claims_skipped']:
        print(f"Skipped {result['claims_skipped']} (already in network)")
    if result['nogoods_imported']:
        print(f"Imported {result['nogoods_imported']} nogoods")


def cmd_import_json(args):
    try:
        result = api.import_json(args.json_file, db_path=args.db)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Imported {result['nodes_imported']} nodes")
    if result['nogoods_imported']:
        print(f"Imported {result['nogoods_imported']} nogoods")


def cmd_export(args):
    data = api.export_network(db_path=args.db)
    print(json.dumps(data, indent=2))


def cmd_export_markdown(args):
    md = api.export_markdown(db_path=args.db)
    if args.output:
        Path(args.output).write_text(md)
        print(f"Written to {args.output}")
    else:
        print(md)


def cmd_hash_sources(args):
    result = api.hash_sources(force=args.force, db_path=args.db)

    if not result["hashed"]:
        print("No nodes to hash (all sources already have hashes, or source files not found).")
        if not args.force:
            print("Use --force to re-hash nodes that already have hashes.")
        return

    for item in result["hashed"]:
        action = "backfilled" if item["was_empty"] else "re-hashed"
        print(f"  {action}  {item['node_id']}  {item['hash']}  ({item['source']})")

    backfilled = sum(1 for h in result["hashed"] if h["was_empty"])
    rehashed = result["count"] - backfilled
    parts = []
    if backfilled:
        parts.append(f"{backfilled} backfilled")
    if rehashed:
        parts.append(f"{rehashed} re-hashed")
    print(f"\n{', '.join(parts)}")


def cmd_check_stale(args):
    result = api.check_stale(db_path=args.db)

    if not result["stale"]:
        print(f"All {result['checked']} nodes with sources are fresh.")
        return

    for item in result["stale"]:
        print(f"  STALE  {item['node_id']}")
        print(f"         source: {item['source']}")
        print(f"         hash: {item['old_hash']} -> {item['new_hash']}")
        print()

    fresh = result["checked"] - result["stale_count"]
    print(f"{fresh} fresh, {result['stale_count']} STALE (of {result['checked']} checked)")
    sys.exit(1)


def cmd_compact(args):
    summary = api.compact(
        budget=args.budget,
        truncate=not args.no_truncate,
        db_path=args.db,
    )
    print(summary)


def cmd_search(args):
    fmt = getattr(args, "format", "markdown")
    result = api.search(args.query, db_path=args.db, format=fmt)
    print(result)


def cmd_lookup(args):
    result = api.lookup(args.query, db_path=args.db)
    print(result)


def cmd_list(args):
    result = api.list_nodes(
        status=args.status,
        premises_only=args.premises,
        has_dependents=args.has_dependents,
        challenged=args.challenged,
        db_path=args.db,
    )

    if not result["nodes"]:
        print("No matching nodes.")
        return

    for node in result["nodes"]:
        marker = "+" if node["truth_value"] == "IN" else "-"
        jinfo = f"  ({node['justification_count']} justification{'s' if node['justification_count'] != 1 else ''})" if node["justification_count"] else "  (premise)"
        deps = f"  [{node['dependent_count']} dependents]" if node["dependent_count"] else ""
        print(f"  [{marker}] {node['id']}{jinfo}{deps}")

    print(f"\n{result['count']} node{'s' if result['count'] != 1 else ''}")


def main():
    parser = argparse.ArgumentParser(
        prog="rms",
        description="Reason Maintenance System — automatic belief retraction and dependency-directed backtracking",
    )
    parser.add_argument("--db", default=api.DEFAULT_DB, help="Path to RMS database (default: rms.db)")
    sub = parser.add_subparsers(dest="command")

    # init
    p = sub.add_parser("init", help="Initialize a new RMS database")
    p.add_argument("--force", action="store_true", help="Overwrite existing database")

    # add
    p = sub.add_parser("add", help="Add a node")
    p.add_argument("node_id", help="Node identifier")
    p.add_argument("text", help="Node text")
    p.add_argument("--sl", metavar="A,B", help="SL justification: comma-separated antecedent IDs")
    p.add_argument("--cp", metavar="A,B", help="CP justification: comma-separated antecedent IDs")
    p.add_argument("--unless", metavar="X,Y", help="Outlist: comma-separated node IDs that must be OUT")
    p.add_argument("--label", help="Justification label")
    p.add_argument("--source", help="Provenance (repo:path)")

    # retract
    p = sub.add_parser("retract", help="Retract a node (mark OUT + cascade)")
    p.add_argument("node_id", help="Node to retract")

    # assert
    p = sub.add_parser("assert", help="Assert a node (mark IN + cascade)")
    p.add_argument("node_id", help="Node to assert")

    # status
    sub.add_parser("status", help="Show all nodes with truth values")

    # show
    p = sub.add_parser("show", help="Show node details")
    p.add_argument("node_id", help="Node to show")

    # explain
    p = sub.add_parser("explain", help="Explain why a node is IN or OUT")
    p.add_argument("node_id", help="Node to explain")

    # convert-to-premise
    p = sub.add_parser("convert-to-premise", help="Strip justifications, make a node a premise")
    p.add_argument("node_id", help="Node to convert")

    # summarize
    p = sub.add_parser("summarize", help="Create a summary node over a group of nodes")
    p.add_argument("summary_id", help="Summary node ID")
    p.add_argument("text", help="High-level summary text")
    p.add_argument("--over", required=True, metavar="A,B,C", help="Comma-separated node IDs to summarize")
    p.add_argument("--source", help="Provenance (repo:path)")

    # challenge
    p = sub.add_parser("challenge", help="Challenge a node — target goes OUT")
    p.add_argument("target_id", help="Node to challenge")
    p.add_argument("reason", help="Why the node is being challenged")
    p.add_argument("--id", help="Custom challenge node ID (default: challenge-TARGET)")

    # defend
    p = sub.add_parser("defend", help="Defend a node against a challenge")
    p.add_argument("target_id", help="Node being defended")
    p.add_argument("challenge_id", help="Challenge to defend against")
    p.add_argument("reason", help="Defense argument")
    p.add_argument("--id", help="Custom defense node ID")

    # nogood
    p = sub.add_parser("nogood", help="Record a contradiction")
    p.add_argument("node_ids", nargs="+", help="Node IDs that cannot all be IN")

    # trace
    p = sub.add_parser("trace", help="Trace backward to find premises a node rests on")
    p.add_argument("node_id", help="Node to trace")

    # propagate
    sub.add_parser("propagate", help="Recompute all truth values")

    # log
    p = sub.add_parser("log", help="Show propagation history")
    p.add_argument("--last", type=int, help="Show only last N entries")

    # import-beliefs
    p = sub.add_parser("import-beliefs", help="Import a beliefs.md registry")
    p.add_argument("beliefs_file", help="Path to beliefs.md")
    p.add_argument("--nogoods", dest="nogoods_file", help="Path to nogoods.md (auto-detected if next to beliefs.md)")

    # import-json
    p = sub.add_parser("import-json", help="Import network from JSON (produced by export)")
    p.add_argument("json_file", help="Path to JSON file")

    # export
    sub.add_parser("export", help="Export network as JSON")

    # export-markdown
    p = sub.add_parser("export-markdown", help="Export network as beliefs.md-compatible markdown")
    p.add_argument("-o", "--output", help="Write to file instead of stdout")

    # hash-sources
    p = sub.add_parser("hash-sources", help="Backfill source hashes for nodes without them")
    p.add_argument("--force", action="store_true", help="Re-hash all nodes, even those with existing hashes")

    # check-stale
    sub.add_parser("check-stale", help="Check IN nodes for source file staleness")

    # compact
    p = sub.add_parser("compact", help="Token-budgeted belief state summary")
    p.add_argument("--budget", type=int, default=500, help="Token budget (default: 500)")
    p.add_argument("--no-truncate", action="store_true", help="Show full node text")

    # search
    p = sub.add_parser("search", help="Search nodes using full-text search with neighbor expansion")
    p.add_argument("query", help="Search terms (FTS5 all-terms matching)")
    p.add_argument("--format", choices=["markdown", "json", "minimal"], default="markdown",
                   help="Output format (default: markdown)")

    # lookup
    p = sub.add_parser("lookup", help="Simple keyword search over beliefs (no neighbor expansion)")
    p.add_argument("query", help="Search terms (all must match, case-insensitive)")

    # list
    p = sub.add_parser("list", help="List nodes with filters")
    p.add_argument("--status", choices=["IN", "OUT"], help="Filter by truth value")
    p.add_argument("--premises", action="store_true", help="Only show premises (no justifications)")
    p.add_argument("--has-dependents", action="store_true", help="Only show nodes that others depend on")
    p.add_argument("--challenged", action="store_true", help="Only show nodes with active challenges")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "add": cmd_add,
        "retract": cmd_retract,
        "assert": cmd_assert,
        "status": cmd_status,
        "show": cmd_show,
        "explain": cmd_explain,
        "nogood": cmd_nogood,
        "propagate": cmd_propagate,
        "log": cmd_log,
        "import-beliefs": cmd_import_beliefs,
        "import-json": cmd_import_json,
        "export": cmd_export,
        "export-markdown": cmd_export_markdown,
        "hash-sources": cmd_hash_sources,
        "check-stale": cmd_check_stale,
        "compact": cmd_compact,
        "convert-to-premise": cmd_convert_to_premise,
        "summarize": cmd_summarize,
        "challenge": cmd_challenge,
        "defend": cmd_defend,
        "trace": cmd_trace,
        "search": cmd_search,
        "lookup": cmd_lookup,
        "list": cmd_list,
    }
    commands[args.command](args)
