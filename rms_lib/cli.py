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
        if "failed_antecedents" in step:
            line += f" — failed: {', '.join(step['failed_antecedents'])}"
        if step.get("label"):
            line += f" [{step['label']}]"
        print(line)


def cmd_nogood(args):
    try:
        result = api.add_nogood(args.node_ids, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Recorded {result['nogood_id']}: {', '.join(result['nodes'])}")
    if result["changed"]:
        print(f"Retracted: {', '.join(result['changed'])}")


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

    # nogood
    p = sub.add_parser("nogood", help="Record a contradiction")
    p.add_argument("node_ids", nargs="+", help="Node IDs that cannot all be IN")

    # propagate
    sub.add_parser("propagate", help="Recompute all truth values")

    # log
    p = sub.add_parser("log", help="Show propagation history")
    p.add_argument("--last", type=int, help="Show only last N entries")

    # import-beliefs
    p = sub.add_parser("import-beliefs", help="Import a beliefs.md registry")
    p.add_argument("beliefs_file", help="Path to beliefs.md")
    p.add_argument("--nogoods", dest="nogoods_file", help="Path to nogoods.md (auto-detected if next to beliefs.md)")

    # export
    sub.add_parser("export", help="Export network as JSON")

    # export-markdown
    p = sub.add_parser("export-markdown", help="Export network as beliefs.md-compatible markdown")
    p.add_argument("-o", "--output", help="Write to file instead of stdout")

    # check-stale
    sub.add_parser("check-stale", help="Check IN nodes for source file staleness")

    # compact
    p = sub.add_parser("compact", help="Token-budgeted belief state summary")
    p.add_argument("--budget", type=int, default=500, help="Token budget (default: 500)")
    p.add_argument("--no-truncate", action="store_true", help="Show full node text")

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
        "export": cmd_export,
        "export-markdown": cmd_export_markdown,
        "check-stale": cmd_check_stale,
        "compact": cmd_compact,
    }
    commands[args.command](args)
