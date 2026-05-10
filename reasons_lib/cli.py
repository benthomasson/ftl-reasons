"""CLI for the Reason Maintenance System.

Thin wrappers around reasons_lib.api — each command calls an api function
and formats the result dict for terminal output.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from importlib.metadata import version as _pkg_version

from . import api


def cmd_init(args):
    try:
        result = api.init_db(force=args.force, **_backend_kwargs(args))
        if "db_path" in result:
            print(f"Initialized RMS database: {result['db_path']}")
        else:
            print(f"Initialized PostgreSQL project: {result['project_id']}")
    except FileExistsError as e:
        print(f"{e}", file=sys.stderr)
        print("Use --force to reinitialize.", file=sys.stderr)
        sys.exit(1)


def _warn_multi_premise(premise_count, any_mode):
    """Print a tip when an SL has 3+ premises and --any was not used."""
    if premise_count >= 3 and not any_mode:
        print(f"  Tip: This SL requires ALL {premise_count} premises to be IN. If any single")
        print(f"  premise is sufficient, use --any to create separate justifications.")


def cmd_add(args):
    access_tags = None
    if getattr(args, "access_tags", None):
        access_tags = [t.strip() for t in args.access_tags.split(",") if t.strip()]
    try:
        result = api.add_node(
            node_id=args.node_id,
            text=args.text,
            sl=args.sl or "",
            cp=args.cp or "",
            unless=args.unless or "",
            label=args.label or "",
            source=args.source or "",
            source_url=args.source_url or "",
            namespace=getattr(args, "namespace", None),
            any_mode=getattr(args, "any", False),
            access_tags=access_tags,
            **_backend_kwargs(args),
        )
        print(f"Added {result['node_id']} [{result['truth_value']}] ({result['type']})")
        _warn_multi_premise(result.get("premise_count", 0), getattr(args, "any", False))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_add_justification(args):
    try:
        result = api.add_justification(
            node_id=args.node_id,
            sl=args.sl or "",
            cp=args.cp or "",
            unless=args.unless or "",
            label=args.label or "",
            namespace=getattr(args, "namespace", None),
            any_mode=getattr(args, "any", False),
            **_backend_kwargs(args),
        )
        print(f"Added justification to {result['node_id']}")
        print(f"  Truth value: {result['old_truth_value']} → {result['new_truth_value']}")
        if result["changed"]:
            print(f"  Cascade: {', '.join(result['changed'])}")
        _warn_multi_premise(result.get("premise_count", 0), getattr(args, "any", False))
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_remove_justification(args):
    try:
        result = api.remove_justification(
            node_id=args.node_id,
            index=args.index,
            **_backend_kwargs(args),
        )
        removed = result["removed"]
        ants = ", ".join(removed["antecedents"])
        label = f" [{removed['label']}]" if removed["label"] else ""
        print(f"Removed justification {args.index} from {result['node_id']}")
        print(f"  Was: {removed['type']}({ants}){label}")
        print(f"  Truth value: {result['old_truth_value']} → {result['new_truth_value']}")
        print(f"  Remaining justifications: {result['remaining']}")
        if result["changed"]:
            print(f"  Cascade: {', '.join(result['changed'])}")
    except (KeyError, ValueError, IndexError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _print_cascade(result):
    """Print cascade results, splitting went_out from went_in."""
    went_out = result.get("went_out", [])
    went_in = result.get("went_in", [])
    if went_out:
        print(f"  Went OUT ({len(went_out)}):")
        for nid in went_out:
            print(f"    [-] {nid}")
    if went_in:
        print(f"  Went IN ({len(went_in)}):")
        for nid in went_in:
            print(f"    [+] {nid}")


def _print_restoration_hints(hints):
    """Print hints when multi-premise SL nodes go OUT with surviving premises."""
    for hint in hints:
        surviving = ", ".join(hint["surviving_premises"])
        print(f"  Note: {hint['node_id']} went OUT because its justification required ALL of")
        print(f"    {hint['all_premises']}")
        print(f"    Surviving premises still IN: {surviving}")
        print(f"    If any single premise is sufficient, restore with:")
        print(f"      reasons add-justification {hint['node_id']} --sl {surviving} --any")


def cmd_retract(args):
    try:
        result = api.retract_node(args.node_id, reason=args.reason or "", **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["changed"]:
        print(f"{args.node_id} is already OUT")
    else:
        print(f"Retracted {args.node_id}")
        _print_cascade(result)
        if result.get("restoration_hints"):
            _print_restoration_hints(result["restoration_hints"])


def cmd_assert(args):
    try:
        result = api.assert_node(args.node_id, **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["changed"]:
        print(f"{args.node_id} is already IN")
    else:
        print(f"Asserted {args.node_id}")
        _print_cascade(result)


def _print_what_if_results(result, action, node_id):
    """Shared output formatting for what-if retract and assert."""
    if not result["retracted"] and not result["restored"]:
        verb = "Retracting" if action == "retract" else "Asserting"
        print(f"{verb} {node_id} would affect no other nodes.")
        return

    verb = "retracted" if action == "retract" else "asserted"
    print(f"What if '{node_id}' were {verb}?\n")

    if result["retracted"]:
        print("  Would go OUT:")
        current_depth = 0
        for item in result["retracted"]:
            if item["depth"] != current_depth:
                current_depth = item["depth"]
                print(f"  --- depth {current_depth} ---")
            deps = f"  ({item['dependents']} dependents)" if item["dependents"] else ""
            text = item["text"][:80]
            print(f"  [-] {item['id']}: {text}{deps}")

    if result["restored"]:
        if result["retracted"]:
            print()
        print("  Would go IN:")
        current_depth = 0
        for item in result["restored"]:
            if item["depth"] != current_depth:
                current_depth = item["depth"]
                print(f"  --- depth {current_depth} ---")
            deps = f"  ({item['dependents']} dependents)" if item["dependents"] else ""
            text = item["text"][:80]
            print(f"  [+] {item['id']}: {text}{deps}")

    parts = []
    if result["retracted"]:
        parts.append(f"{len(result['retracted'])} would go OUT")
    if result["restored"]:
        parts.append(f"{len(result['restored'])} would go IN")
    print(f"\nTotal: {', '.join(parts)} (database NOT modified)")


def cmd_what_if(args):
    action = args.action
    try:
        if action == "retract":
            result = api.what_if_retract(args.node_id, **_backend_kwargs(args))
            if result.get("already_out"):
                print(f"{args.node_id} is already OUT — nothing to simulate.")
                return
        else:
            result = api.what_if_assert(args.node_id, **_backend_kwargs(args))
            if result.get("already_in"):
                print(f"{args.node_id} is already IN — nothing to simulate.")
                return
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    _print_what_if_results(result, action, args.node_id)


def cmd_status(args):
    result = api.get_status(visible_to=_parse_visible_to(args), **_backend_kwargs(args))

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
    visible_to = _parse_visible_to(args)
    try:
        node = api.show_node(args.node_id, visible_to=visible_to, **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Access denied: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"ID:     {node['id']}")
    print(f"Text:   {node['text']}")
    print(f"Status: {node['truth_value']}")
    if node["source"]:
        print(f"Source: {node['source']}")
    if node.get("source_url"):
        print(f"URL:    {node['source_url']}")
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

    if node["metadata"].get("retract_reason"):
        print(f"\nRetract reason: {node['metadata']['retract_reason']}")

    if node["dependents"]:
        print(f"\nDependents: {', '.join(node['dependents'])}")


def cmd_explain(args):
    try:
        result = api.explain_node(args.node_id, visible_to=_parse_visible_to(args), **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Access denied: {e}", file=sys.stderr)
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
        result = api.convert_to_premise(args.node_id, **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Converted {result['node_id']} to premise (stripped {result['old_justifications']} justification(s))")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


def cmd_summarize(args):
    _require_sqlite(args, "summarize")
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


def cmd_supersede(args):
    _require_sqlite(args, "supersede")
    try:
        result = api.supersede(args.old_id, args.new_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Superseded {result['old_id']} by {result['new_id']}")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


def cmd_update(args):
    if not any([args.text, args.source, args.source_url]):
        print("Error: at least one of --text, --source, or --source-url required",
              file=sys.stderr)
        sys.exit(1)
    try:
        result = api.update_node(
            args.node_id, text=args.text,
            source=args.source,
            source_url=args.source_url,
            **_backend_kwargs(args),
        )
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    fields = ", ".join(result["updated_fields"])
    print(f"Updated {result['node_id']} ({fields})")


def cmd_challenge(args):
    try:
        result = api.challenge(
            args.target_id, args.reason,
            challenge_id=args.id,
            **_backend_kwargs(args),
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
            **_backend_kwargs(args),
        )
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Defended {result['target_id']} against {result['challenge_id']} with {result['defense_id']}")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


def cmd_nogood(args):
    try:
        result = api.add_nogood(args.node_ids, **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Recorded {result['nogood_id']}: {', '.join(result['nodes'])}")
    if result["backtracked_to"]:
        print(f"Backtracked to premise: {result['backtracked_to']}")
    if result["changed"]:
        print(f"Retracted: {', '.join(result['changed'])}")


def cmd_trace_access_tags(args):
    _require_sqlite(args, "trace-access-tags")
    try:
        result = api.trace_access_tags(args.node_id, visible_to=_parse_visible_to(args), db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Access denied: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["access_tags"]:
        print(f"{args.node_id} has no access tags in its dependency chain (unrestricted).")
        return

    print(f"{args.node_id} depends on data tagged: {', '.join(result['access_tags'])}")


def cmd_trace(args):
    try:
        result = api.trace_assumptions(args.node_id, visible_to=_parse_visible_to(args), **_backend_kwargs(args))
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Access denied: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["premises"]:
        print(f"{args.node_id} is a premise (no dependencies).")
        return

    print(f"{args.node_id} rests on {len(result['premises'])} premise(s):")
    for pid in result["premises"]:
        node = api.show_node(pid, **_backend_kwargs(args))
        marker = "+" if node["truth_value"] == "IN" else "-"
        deps = f"  ({len(node['dependents'])} dependents)" if node["dependents"] else ""
        print(f"  [{marker}] {pid}: {node['text'][:80]}{deps}")


def cmd_propagate(args):
    _require_sqlite(args, "propagate")
    result = api.propagate(db_path=args.db)
    changed = result["changed"]
    if changed:
        print(f"Updated: {', '.join(changed)}")
    else:
        print("All truth values are current.")


def cmd_log(args):
    result = api.get_log(last=args.last, **_backend_kwargs(args))

    if not result["entries"]:
        print("No propagation events.")
        return

    for entry in result["entries"]:
        print(f"  {entry['timestamp']}  {entry['action']:10s}  {entry['target']:20s}  {entry['value']}")


def cmd_add_repo(args):
    _require_sqlite(args, "add-repo")
    result = api.add_repo(args.name, args.path, db_path=args.db)
    print(f"Added repo {result['name']}: {result['path']}")


def cmd_repos(args):
    _require_sqlite(args, "repos")
    result = api.list_repos(db_path=args.db)
    if not result["repos"]:
        print("No repos registered.")
        return
    for name, path in sorted(result["repos"].items()):
        print(f"  {name}: {path}")
    print(f"\n{len(result['repos'])} repo(s)")


def cmd_import_agent(args):
    _require_sqlite(args, "import-agent")
    try:
        result = api.import_agent(
            agent_name=args.agent_name,
            beliefs_file=args.beliefs_file,
            nogoods_file=args.nogoods_file,
            only_in=args.only_in,
            db_path=args.db,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Agent '{result['agent']}' imported:")
    if result['created_premise']:
        print(f"  Created premise: {result['active_node']}")
    else:
        print(f"  Premise exists:  {result['active_node']}")
    print(f"  Imported:  {result['claims_imported']} beliefs (as {result['prefix']}*)")
    if result['claims_skipped']:
        print(f"  Skipped:   {result['claims_skipped']} (already in network)")
    if result['claims_retracted']:
        print(f"  Retracted: {result['claims_retracted']} (STALE/OUT in source)")
    if result.get('claims_propagated'):
        print(f"  Propagated: {result['claims_propagated']} (truth values recomputed)")
    if result['nogoods_imported']:
        print(f"  Nogoods:   {result['nogoods_imported']}")
    print(f"\n  To revoke all: reasons retract {result['active_node']}")


def cmd_sync_agent(args):
    _require_sqlite(args, "sync-agent")
    try:
        result = api.sync_agent(
            agent_name=args.agent_name,
            beliefs_file=args.beliefs_file,
            nogoods_file=args.nogoods_file,
            only_in=args.only_in,
            db_path=args.db,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Agent '{result['agent']}' synced:")
    if result['created_premise']:
        print(f"  Created premise: {result['active_node']}")
    if result['beliefs_added']:
        print(f"  Added:     {result['beliefs_added']} new beliefs")
    if result['beliefs_updated']:
        print(f"  Updated:   {result['beliefs_updated']} beliefs")
    if result['beliefs_removed']:
        print(f"  Removed:   {result['beliefs_removed']} beliefs (retracted)")
    if result['beliefs_retracted']:
        print(f"  Retracted: {result['beliefs_retracted']} (OUT/STALE in source)")
    if result['beliefs_unchanged']:
        print(f"  Unchanged: {result['beliefs_unchanged']}")
    if result.get('beliefs_propagated'):
        print(f"  Propagated: {result['beliefs_propagated']} (truth values recomputed)")
    if result['nogoods_imported']:
        print(f"  Nogoods:   {result['nogoods_imported']}")


def cmd_import_beliefs(args):
    _require_sqlite(args, "import-beliefs")
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
    _require_sqlite(args, "import-json")
    try:
        result = api.import_json(args.json_file, db_path=args.db)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Imported {result['nodes_imported']} nodes")
    if result['nogoods_imported']:
        print(f"Imported {result['nogoods_imported']} nogoods")


def cmd_export(args):
    data = api.export_network(visible_to=_parse_visible_to(args), **_backend_kwargs(args))
    output = json.dumps(data, indent=2)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}")
    else:
        print(output)


def cmd_export_markdown(args):
    md = api.export_markdown(visible_to=_parse_visible_to(args), **_backend_kwargs(args))
    if args.output:
        Path(args.output).write_text(md)
        print(f"Written to {args.output}")
    else:
        print(md)


def cmd_hash_sources(args):
    _require_sqlite(args, "hash-sources")
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
    _require_sqlite(args, "check-stale")
    result = api.check_stale(upgrade_hashes=args.upgrade_hashes, db_path=args.db)

    if result.get("upgraded"):
        print(f"Upgraded {result['upgraded']} truncated hash(es) to full length.")

    if not result["stale"]:
        print(f"All {result['checked']} nodes with sources are fresh.")
        return

    truncated = [i for i in result["stale"] if i.get("reason") == "truncated_hash"]
    stale = [i for i in result["stale"] if i.get("reason") != "truncated_hash"]

    for item in stale:
        if item.get("reason") == "source_deleted":
            print(f"  DELETED  {item['node_id']}")
            print(f"           source: {item['source']}")
        else:
            print(f"  STALE  {item['node_id']}")
            print(f"         source: {item['source']}")
            print(f"         hash: {item['old_hash']} -> {item['new_hash']}")
        print()

    if truncated:
        print(f"WARNING: {len(truncated)} node(s) have truncated hashes.")
        print("  Run 'reasons check-stale --upgrade-hashes' to upgrade them.\n")

    fresh = result["checked"] - len(stale)
    print(f"{fresh} fresh, {len(stale)} stale (of {result['checked']} checked)")
    if stale:
        sys.exit(1)


def cmd_compact(args):
    summary = api.compact(
        budget=args.budget,
        truncate=not args.no_truncate,
        visible_to=_parse_visible_to(args),
        **_backend_kwargs(args),
    )
    print(summary)


def _parse_visible_to(args):
    val = getattr(args, "visible_to", None)
    if val is not None:
        return [t.strip() for t in val.split(",") if t.strip()]
    return None


def _backend_kwargs(args):
    pg = getattr(args, "pg", None) or os.environ.get("REASONS_PG_CONNINFO")
    pid = getattr(args, "project_id", None) or os.environ.get("REASONS_PROJECT_ID")
    if pg:
        if not pid:
            print("Error: --project-id is required with --pg", file=sys.stderr)
            sys.exit(1)
        return {"pg_conninfo": pg, "project_id": pid}
    return {"db_path": args.db}


def _require_sqlite(args, command_name):
    pg = getattr(args, "pg", None) or os.environ.get("REASONS_PG_CONNINFO")
    if pg:
        print(f"Error: {command_name} is not supported with --pg", file=sys.stderr)
        sys.exit(1)


def cmd_search(args):
    fmt = getattr(args, "format", "markdown")
    result = api.search(args.query, visible_to=_parse_visible_to(args), format=fmt, **_backend_kwargs(args))
    print(result)


def cmd_lookup(args):
    _require_sqlite(args, "lookup")
    result = api.lookup(args.query, visible_to=_parse_visible_to(args), db_path=args.db)
    print(result)


def cmd_ask(args):
    _require_sqlite(args, "ask")
    from .ask import ask
    result = ask(
        question=args.question,
        db_path=args.db,
        timeout=args.timeout,
        no_synth=args.no_synth,
        format=getattr(args, "format", None),
        model=args.model or "claude",
        simple=args.simple,
        sources_db=args.full_sources,
        natural=args.natural,
        dual=args.dual,
    )
    print(result)


def cmd_cluster_list(args):
    _require_sqlite(args, "cluster-list")
    result = api.list_clusters(
        status=args.status,
        n_clusters=args.n_clusters,
        seed=args.seed,
        embedding_model=args.embedding_model,
        visible_to=_parse_visible_to(args),
        db_path=args.db,
    )

    if not result["clusters"]:
        print("No beliefs to cluster.")
        return

    fmt = args.format

    if fmt == "json":
        print(json.dumps(result, indent=2))
        return

    if fmt == "markdown":
        for i, cluster in enumerate(result["clusters"], 1):
            size = len(cluster["beliefs"])
            print(f"\n## Cluster {i} ({size} belief{'s' if size != 1 else ''})\n")
            for b in cluster["beliefs"]:
                print(f"- **{b['id']}**: {b['text']}")
        return

    total = 0
    for i, cluster in enumerate(result["clusters"], 1):
        size = len(cluster["beliefs"])
        total += size
        print(f"\nCluster {i} ({size} belief{'s' if size != 1 else ''}):")
        for b in cluster["beliefs"]:
            marker = "+" if args.status == "IN" else "-"
            print(f"  [{marker}] {b['id']}")
            text = b['text'][:100] + "..." if len(b['text']) > 100 else b['text']
            print(f"      {text}")

    print(f"\n{result['n_clusters']} cluster(s), {total} beliefs")
    print(f"Model: {result['embedding_model']}")


def cmd_deduplicate(args):
    _require_sqlite(args, "deduplicate")
    if args.accept:
        accept_path = Path(args.accept)
        if not accept_path.exists():
            print(f"File not found: {accept_path}", file=sys.stderr)
            sys.exit(1)
        plan = api.parse_dedup_plan(accept_path.read_text())
        if not plan:
            print("No clusters found in plan file.")
            return
        result = api.apply_dedup_plan(plan, db_path=args.db)
        for err in result["errors"]:
            print(f"  ERROR: {err}", file=sys.stderr)
        if result["retracted"]:
            print(f"Retracted {len(result['retracted'])} duplicates "
                  f"(from {result['applied']} cluster(s)).")
            for nid in result["retracted"]:
                print(f"  RETRACTED {nid}")
        else:
            print("No duplicates to retract.")
        return

    result = api.deduplicate(
        threshold=args.threshold,
        auto=args.auto,
        db_path=args.db,
    )

    if not result["clusters"]:
        print("No duplicate clusters found.")
        return

    for i, cluster in enumerate(result["clusters"], 1):
        print(f"\nCluster {i} ({cluster['size']} beliefs):")
        for b in cluster["beliefs"]:
            deps = f"  [{b['dependents']} dependents]" if b["dependents"] else ""
            kept = "  <- kept" if cluster.get("kept") == b["id"] else ""
            retracted = "  RETRACTED" if b["id"] in result["retracted"] else ""
            print(f"  {b['id']}{deps}{kept}{retracted}")
            print(f"    {b['text'][:100]}")

    print(f"\n{len(result['clusters'])} cluster(s), "
          f"{sum(c['size'] for c in result['clusters'])} beliefs involved")
    if result["retracted"]:
        print(f"Retracted {len(result['retracted'])} duplicates.")
    elif not args.auto:
        output = args.output
        api.write_dedup_plan(result["clusters"], output)
        print(f"\nWrote {output} — review, then run:")
        print(f"  reasons deduplicate --accept {output}")


def _derive_one_round(args, round_num=None, report_state=None,
                      cluster_cache=None):
    """Run a single derive round. Returns number of beliefs added (0 = saturated).

    Used by cmd_derive for both single-round and --exhaust mode.
    If report_state is provided, appends round results and writes the report.
    """
    import subprocess

    from .derive import (
        build_prompt,
        parse_proposals,
        validate_proposals,
        apply_proposals,
        write_proposals_file,
    )

    prefix = f"[round {round_num}] " if round_num is not None else ""

    # Load network (fresh each round)
    try:
        result = api.export_network(db_path=args.db)
    except Exception as e:
        print(f"{prefix}Error loading network: {e}", file=sys.stderr)
        return -1

    nodes = result.get("nodes", {})
    if not nodes:
        print(f"{prefix}No nodes in the network.", file=sys.stderr)
        return -1

    prompt, stats = build_prompt(
        nodes, domain=args.domain, topic=args.topic,
        budget=args.budget, sample=args.sample, seed=args.seed,
        min_depth=args.min_depth, max_depth_filter=args.max_depth,
        premises_only=args.premises, has_dependents=args.has_dependents,
        cluster=args.cluster, cluster_cache=cluster_cache,
        embedding_model=args.embedding_model, n_clusters=args.n_clusters,
    )

    print(f"{prefix}Network: {stats['total_in']} IN beliefs, "
          f"{stats['total_derived']} derived, max depth {stats['max_depth']}",
          file=sys.stderr)
    if stats.get("topic"):
        print(f"{prefix}Topic filter: {stats['topic']}", file=sys.stderr)
    if stats.get("min_depth") is not None or stats.get("max_depth_filter") is not None:
        lo = stats.get("min_depth", 0)
        hi = stats.get("max_depth_filter", "∞")
        print(f"{prefix}Depth filter: {lo}–{hi}", file=sys.stderr)
    if stats.get("cluster"):
        print(f"{prefix}Clustering: {stats['n_clusters']} clusters, "
              f"model={stats['embedding_model']}", file=sys.stderr)
    elif stats.get("sample"):
        print(f"{prefix}Sampling: {stats['budget']} beliefs (random)", file=sys.stderr)
    elif stats.get("budget", 300) != 300:
        print(f"{prefix}Budget: {stats['budget']} beliefs", file=sys.stderr)
    if stats["agents"]:
        print(f"{prefix}Agents: {', '.join(stats['agent_names'])}", file=sys.stderr)

    if args.dry_run:
        print(f"\n=== Prompt ({len(prompt)} chars) ===\n")
        print(prompt[:3000])
        if len(prompt) > 3000:
            print(f"\n... ({len(prompt) - 3000} more chars)")
        return 0

    # Model invocation via CLI
    model = args.model or "claude"

    print(f"{prefix}Deriving with {model}...", file=sys.stderr)

    from .llm import invoke_model
    try:
        response = invoke_model(prompt, model=model, timeout=args.timeout)
    except FileNotFoundError as e:
        print(f"{prefix}Error: {e}", file=sys.stderr)
        return -1
    except subprocess.TimeoutExpired:
        print(f"{prefix}Model timed out after {args.timeout}s", file=sys.stderr)
        return -1
    except Exception as e:
        print(f"{prefix}Error: {e}", file=sys.stderr)
        return -1

    # Parse and validate proposals
    proposals = parse_proposals(response)

    if not proposals:
        print(f"{prefix}No new proposals — network saturated.", file=sys.stderr)
        if report_state is not None:
            report_state["rounds"].append({
                "round": round_num or 1,
                "network_stats": stats,
                "proposals_found": 0, "valid": 0,
                "skipped": [], "applied": [], "added": 0,
            })
            _write_derive_report(report_state, "partial")
        return 0

    valid, skipped = validate_proposals(proposals, nodes)

    for p, reason in skipped:
        print(f"  SKIP {p['id']}: {reason}", file=sys.stderr)

    print(f"\n{prefix}{len(valid)} valid proposals "
          f"({len(skipped)} skipped)", file=sys.stderr)

    round_result = {
        "round": round_num or 1,
        "network_stats": stats,
        "proposals_found": len(proposals),
        "valid": len(valid),
        "skipped": [{"id": p["id"], "reason": reason} for p, reason in skipped],
        "applied": [],
        "added": 0,
    }

    if not valid:
        if report_state is not None:
            report_state["rounds"].append(round_result)
            _write_derive_report(report_state, "partial")
        return 0

    if args.auto or args.exhaust:
        results = apply_proposals(valid, db_path=args.db)
        added = 0
        for p, result in results:
            if isinstance(result, dict):
                print(f"  Added {p['id']} [{result['truth_value']}]")
                round_result["applied"].append({
                    "id": p["id"], "truth_value": result["truth_value"],
                })
                added += 1
            else:
                print(f"  FAIL {p['id']}: {result}", file=sys.stderr)
        round_result["added"] = added
        if added:
            print(f"\n{prefix}Added {added} derived beliefs.", file=sys.stderr)
        if report_state is not None:
            report_state["rounds"].append(round_result)
            _write_derive_report(report_state, "partial")
        return added
    else:
        output_path = Path(args.output)
        write_proposals_file(valid, output_path)
        print(f"\n{prefix}Wrote {output_path} ({len(valid)} proposals)")
        round_result["added"] = 0
        round_result["proposed"] = len(valid)
        if report_state is not None:
            report_state["rounds"].append(round_result)
            _write_derive_report(report_state, "partial")
        return len(valid)


def _write_derive_report(report_state, status):
    """Write derive JSON report to disk."""
    import json
    if report_state.get("report_path") is None:
        return
    total = sum(r["added"] for r in report_state["rounds"])
    report = {
        "timestamp": report_state["ts"],
        "status": status,
        "model": report_state["model"],
        "timeout": report_state["timeout"],
        "exhaust": report_state["exhaust"],
        "filters": report_state["filters"],
        "rounds": report_state["rounds"],
        "total_added": total,
    }
    report_state["report_path"].write_text(json.dumps(report, indent=2))


def cmd_derive(args):
    _require_sqlite(args, "derive")
    from datetime import datetime

    if args.cluster and args.sample:
        print("Error: --cluster and --sample are mutually exclusive.",
              file=sys.stderr)
        sys.exit(1)

    cluster_cache = None
    if args.cluster:
        try:
            from .cluster import ClusterCache
            print("Loading embedding model...", file=sys.stderr)
            cluster_cache = ClusterCache(
                model_name=args.embedding_model or "all-MiniLM-L6-v2"
            )
        except ImportError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    report_state = None
    if not args.no_report:
        ts = datetime.now().isoformat(timespec="seconds")
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"derive-{ts.replace(':', '')}.json"
        model = args.model or "claude"
        report_state = {
            "report_path": report_path,
            "ts": ts,
            "model": model,
            "timeout": args.timeout,
            "exhaust": args.exhaust,
            "filters": {
                "domain": args.domain,
                "topic": args.topic,
                "min_depth": args.min_depth,
                "max_depth": args.max_depth,
                "premises": args.premises,
                "has_dependents": args.has_dependents,
                "budget": args.budget,
                "sample": args.sample,
                "cluster": args.cluster,
                "embedding_model": args.embedding_model,
                "n_clusters": args.n_clusters,
            },
            "rounds": [],
        }

    if args.exhaust:
        max_rounds = args.max_rounds
        total_added = 0
        for round_num in range(1, max_rounds + 1):
            print(f"\n{'=' * 40}", file=sys.stderr)
            print(f"Round {round_num}/{max_rounds}", file=sys.stderr)
            print(f"{'=' * 40}", file=sys.stderr)
            added = _derive_one_round(args, round_num=round_num,
                                      report_state=report_state,
                                      cluster_cache=cluster_cache)
            if added < 0:
                print(f"\nExhaust stopped: error in round {round_num}.",
                      file=sys.stderr)
                sys.exit(1)
            if added == 0:
                print(f"\nExhaust complete: saturated after {round_num} rounds. "
                      f"Total added: {total_added}.", file=sys.stderr)
                break
            total_added += added
        else:
            print(f"\nExhaust complete: hit max rounds ({max_rounds}). "
                  f"Total added: {total_added}.", file=sys.stderr)
    else:
        added = _derive_one_round(args, report_state=report_state,
                                  cluster_cache=cluster_cache)
        if added < 0:
            sys.exit(1)

    if report_state is not None:
        _write_derive_report(report_state, "complete")
        print(f"  Report: {report_state['report_path']}")


def cmd_accept(args):
    _require_sqlite(args, "accept")
    from .derive import parse_proposals, validate_proposals, apply_proposals

    proposals_path = Path(args.file)
    if not proposals_path.exists():
        print(f"File not found: {proposals_path}", file=sys.stderr)
        sys.exit(1)

    text = proposals_path.read_text()
    proposals = parse_proposals(text)

    if not proposals:
        print("No proposals found in file.")
        return

    # Load network for validation
    result = api.export_network(db_path=args.db)
    nodes = result.get("nodes", {})

    valid, skipped = validate_proposals(proposals, nodes)

    for p, reason in skipped:
        print(f"  SKIP {p['id']}: {reason}", file=sys.stderr)

    if not valid:
        print("No valid proposals to accept.")
        return

    results = apply_proposals(valid, db_path=args.db)
    added = 0
    for p, result in results:
        if isinstance(result, dict):
            print(f"  Added {p['id']} [{result['truth_value']}]")
            added += 1
        else:
            print(f"  FAIL {p['id']}: {result}", file=sys.stderr)

    print(f"\nAccepted {added} of {len(proposals)} proposals "
          f"({len(skipped)} skipped).", file=sys.stderr)


def cmd_list(args):
    result = api.list_nodes(
        status=args.status,
        premises_only=args.premises,
        has_dependents=args.has_dependents,
        challenged=args.challenged,
        namespace=getattr(args, "namespace", None),
        min_depth=args.min_depth,
        max_depth=args.max_depth,
        visible_to=_parse_visible_to(args),
        not_reviewed_since=args.not_reviewed_since,
        never_reviewed=args.never_reviewed,
        by_impact=args.by_impact,
        **_backend_kwargs(args),
    )

    if args.never_reviewed and args.not_reviewed_since is not None:
        print("Warning: --never-reviewed makes --not-reviewed-since a no-op",
              file=sys.stderr)

    if not result["nodes"]:
        print("No matching nodes.")
        return

    show_review = args.never_reviewed or args.not_reviewed_since is not None
    for node in result["nodes"]:
        marker = "+" if node["truth_value"] == "IN" else "-"
        jinfo = f"  ({node['justification_count']} justification{'s' if node['justification_count'] != 1 else ''})" if node["justification_count"] else "  (premise)"
        deps = f"  [{node['dependent_count']} dependents]" if node["dependent_count"] else ""
        review_info = ""
        if show_review:
            if node.get("last_reviewed"):
                review_info = f"  (reviewed: {node['last_reviewed']}, {node.get('review_result', '?')})"
            elif node.get("justification_count", 0) > 0:
                review_info = "  (never reviewed)"
        print(f"  [{marker}] {node['id']}{jinfo}{deps}{review_info}")

    print(f"\n{result['count']} node{'s' if result['count'] != 1 else ''}")


def cmd_list_gated(args):
    result = api.list_gated(
        visible_to=_parse_visible_to(args),
        **_backend_kwargs(args),
    )

    if not result["blockers"]:
        print("No active gates found. All gated beliefs are satisfied.")
        return

    for blocker_id, info in sorted(result["blockers"].items()):
        print(f"  [{blocker_id}] {info['text']}")
        for gated in info["gated"]:
            print(f"    ⊢ {gated['id']}: {gated['text']}")
        print()

    print(f"{result['blocker_count']} blocker(s) gating {result['gated_count']} belief(s)")


def cmd_list_negative(args):
    _require_sqlite(args, "list-negative")
    result = api.list_negative(
        visible_to=_parse_visible_to(args),
        model=getattr(args, "model", None) or "claude",
        db_path=args.db,
    )

    if not result["negative"]:
        print("No negative beliefs found.")
        return

    for item in result["negative"]:
        print(f"  [-] {item['id']}: {item['text']}")

    print(f"\n{result['count']} negative belief(s) "
          f"({result['candidates']} candidates from {result['total']} IN nodes)")


def cmd_review_beliefs(args):
    _require_sqlite(args, "review-beliefs")
    import json
    from datetime import datetime

    model = getattr(args, "model", None) or "claude"
    ts = datetime.now().isoformat(timespec="seconds")
    write_report = not args.no_report

    report_path = None
    if write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"review-beliefs-{ts.replace(':', '')}.json"

    def _build_report(results, status):
        invalid = sum(1 for r in results if not r.get("valid", True))
        insufficient = sum(1 for r in results if not r.get("sufficient", True))
        unnecessary = sum(1 for r in results if not r.get("necessary", True))
        return {
            "timestamp": ts,
            "status": status,
            "model": model,
            "timeout": args.timeout,
            "dry_run": args.dry_run,
            "filters": {
                "belief_ids": args.ids or None,
                "min_depth": args.min_depth,
                "depends_on": args.depends_on,
                "sample": args.sample,
                "visible_to": _parse_visible_to(args),
            },
            "reviewed": len(results),
            "total_derived": None,
            "summary": {
                "invalid": invalid,
                "insufficient": insufficient,
                "unnecessary": unnecessary,
            },
            "results": results,
        }

    def _write_report(results, status):
        if report_path is not None:
            report_path.write_text(json.dumps(_build_report(results, status), indent=2))

    on_batch = (lambda results: _write_report(results, "partial")) if write_report else None

    result = api.review_beliefs(
        belief_ids=args.ids or None,
        model=model,
        timeout=args.timeout,
        min_depth=args.min_depth,
        depends_on=args.depends_on,
        sample=args.sample,
        visible_to=_parse_visible_to(args),
        dry_run=args.dry_run,
        on_batch=on_batch,
        db_path=args.db,
    )

    reviews = result["results"]
    if not reviews:
        print("No derived beliefs to review.")
        return

    invalid = [r for r in reviews if not r.get("valid", True)]
    insufficient = [r for r in reviews if not r.get("sufficient", True)]
    unnecessary = [r for r in reviews if not r.get("necessary", True)]

    for r in reviews:
        flags = []
        if not r.get("valid", True):
            flags.append("INVALID")
        if not r.get("sufficient", True):
            flags.append("INSUFFICIENT")
        if not r.get("necessary", True):
            unneeded = r.get("unnecessary_antecedents", [])
            flag = "UNNECESSARY"
            if unneeded:
                flag += f"({', '.join(unneeded)})"
            flags.append(flag)

        if flags:
            print(f"  [{' | '.join(flags)}] {r['id']}")
            if r.get("comment"):
                print(f"    {r['comment']}")

    print(f"\nReviewed {result['reviewed']} of {result['total_derived']} derived beliefs")
    print(f"  Invalid: {result['invalid']}  Insufficient: {result['insufficient']}"
          f"  Unnecessary: {result['unnecessary']}")

    if report_path is not None:
        report = _build_report(reviews, "complete")
        report["total_derived"] = result["total_derived"]
        report_path.write_text(json.dumps(report, indent=2))
        print(f"  Report: {report_path}")

    if args.output:
        with open(args.output, "w") as f:
            f.write("# Belief Review Findings\n\n")
            for r in reviews:
                v = "PASS" if r.get("valid", True) else "FAIL"
                s = "PASS" if r.get("sufficient", True) else "FAIL"
                n = "PASS" if r.get("necessary", True) else "FAIL"
                f.write(f"### {r['id']}\n")
                f.write(f"- Valid: {v}\n- Sufficient: {s}\n- Necessary: {n}\n")
                if r.get("unnecessary_antecedents"):
                    f.write(f"- Unnecessary antecedents: {', '.join(r['unnecessary_antecedents'])}\n")
                if r.get("comment"):
                    f.write(f"- Comment: {r['comment']}\n")
                f.write("\n")
        print(f"\nWrote findings to {args.output}")

    if args.auto_retract and not args.dry_run and invalid:
        print(f"\nRetracting {len(invalid)} invalid belief(s)...")
        for r in invalid:
            try:
                api.retract_node(r["id"], reason=f"review-beliefs: {r.get('comment', 'invalid')}", db_path=args.db)
                print(f"  RETRACTED {r['id']}")
            except Exception as e:
                print(f"  ERROR retracting {r['id']}: {e}", file=sys.stderr)


def cmd_contradictions(args):
    _require_sqlite(args, "detect-contradictions")
    model = getattr(args, "model", None) or "claude"
    auto_apply = args.auto_apply and not args.dry_run
    result = api.detect_contradictions(
        belief_ids=args.ids or None,
        model=model,
        timeout=args.timeout,
        sample=args.sample,
        auto_apply=auto_apply,
        db_path=args.db,
    )

    contradictions = result["contradictions"]
    if not contradictions:
        print(f"No contradictions detected among {result['checked']} IN beliefs.")
        return

    for c in contradictions:
        severity = c.get("severity", "")
        sev_str = f" ({severity})" if severity else ""
        print(f"  [NOGOOD] {c['id']}{sev_str}")
        print(f"    Claims: {', '.join(c['claims'])}")
        if c.get("analysis"):
            print(f"    Analysis: {c['analysis']}")

    print(f"\nChecked {result['checked']} of {result['total_in']} IN beliefs")
    print(f"  Found: {result['found']}  Applied: {result['applied']}")

    if args.output:
        with open(args.output, "w") as f:
            f.write("# Contradiction Detection Findings\n\n")
            f.write(f"Checked {result['checked']} beliefs, "
                    f"found {result['found']} contradictions.\n\n")
            for c in contradictions:
                f.write(f"### NOGOOD {c['id']}\n")
                f.write(f"- Claims: {', '.join(c['claims'])}\n")
                if c.get("analysis"):
                    f.write(f"- Analysis: {c['analysis']}\n")
                if c.get("severity"):
                    f.write(f"- Severity: {c['severity']}\n")
                f.write("\n")
        print(f"\nWrote findings to {args.output}")

    if auto_apply and result.get("applied_details"):
        print(f"\nApplied {result['applied']} nogood(s):")
        for d in result["applied_details"]:
            changed = d.get("changed", [])
            print(f"  {d.get('id', '?')}: nogood={d.get('nogood_id', '?')}, "
                  f"changed {len(changed)} node(s)")


def cmd_namespaces(args):
    _require_sqlite(args, "namespaces")
    result = api.list_namespaces(db_path=args.db)
    if not result["namespaces"]:
        print("No namespaces found. Use --namespace/-n with 'add' or 'import-agent' to create one.")
        return
    for ns in result["namespaces"]:
        status = "ACTIVE" if ns["active"] else "INACTIVE"
        print(f"  {ns['namespace']:30s} {status:8s} {ns['in_beliefs']:3d} IN / {ns['total_beliefs']} total")
    print(f"\n{len(result['namespaces'])} namespace(s)")


def main():
    parser = argparse.ArgumentParser(
        prog="reasons",
        description="Reasons — automatic belief retraction and dependency-directed backtracking",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_pkg_version('ftl-reasons')}")
    parser.add_argument("--db", default=api.DEFAULT_DB, help="Path to database (default: reasons.db)")
    parser.add_argument("--pg", default=None, metavar="CONNINFO",
                        help="PostgreSQL connection string (or set REASONS_PG_CONNINFO)")
    parser.add_argument("--project-id", default=None,
                        help="Project ID for PostgreSQL (or set REASONS_PROJECT_ID)")
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
    p.add_argument("--any", action="store_true", help="Expand SL into one justification per premise (OR instead of AND)")
    p.add_argument("--label", help="Justification label")
    p.add_argument("--source", help="Provenance (repo:path)")
    p.add_argument("--source-url", help="URL for the source document")
    p.add_argument("-n", "--namespace", help="Namespace prefix (auto-creates ns:active premise)")
    p.add_argument("--access-tags", metavar="TAG,TAG", help="Data source provenance tags (comma-separated)")

    # add-justification
    p = sub.add_parser("add-justification", help="Add a justification to an existing node")
    p.add_argument("node_id", help="Node to add justification to")
    p.add_argument("--sl", metavar="A,B", help="SL justification: comma-separated antecedent IDs")
    p.add_argument("--cp", metavar="A,B", help="CP justification: comma-separated antecedent IDs")
    p.add_argument("--unless", metavar="X,Y", help="Outlist: comma-separated node IDs that must be OUT")
    p.add_argument("--any", action="store_true", help="Expand SL into one justification per premise (OR instead of AND)")
    p.add_argument("--label", help="Justification label")
    p.add_argument("-n", "--namespace", help="Namespace prefix")

    # remove-justification
    p = sub.add_parser("remove-justification", help="Remove a justification by index")
    p.add_argument("node_id", help="Node to remove justification from")
    p.add_argument("index", type=int, help="0-based justification index (see 'show' output)")

    # retract
    p = sub.add_parser("retract", help="Retract a node (mark OUT + cascade)")
    p.add_argument("node_id", help="Node to retract")
    p.add_argument("--reason", help="Why this node is being retracted")

    # assert
    p = sub.add_parser("assert", help="Assert a node (mark IN + cascade)")
    p.add_argument("node_id", help="Node to assert")

    # what-if
    p = sub.add_parser("what-if", help="Simulate retracting or asserting a node (read-only)")
    p.add_argument("action", choices=["retract", "assert"], help="Action to simulate")
    p.add_argument("node_id", help="Node to simulate")

    # status
    p = sub.add_parser("status", help="Show all nodes with truth values")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show nodes whose access_tags are a subset of these tags")

    # show
    p = sub.add_parser("show", help="Show node details")
    p.add_argument("node_id", help="Node to show")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show if access_tags are a subset of these tags")

    # explain
    p = sub.add_parser("explain", help="Explain why a node is IN or OUT")
    p.add_argument("node_id", help="Node to explain")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show if access_tags are a subset of these tags")

    # convert-to-premise
    p = sub.add_parser("convert-to-premise", help="Strip justifications, make a node a premise")
    p.add_argument("node_id", help="Node to convert")

    # summarize
    p = sub.add_parser("summarize", help="Create a summary node over a group of nodes")
    p.add_argument("summary_id", help="Summary node ID")
    p.add_argument("text", help="High-level summary text")
    p.add_argument("--over", required=True, metavar="A,B,C", help="Comma-separated node IDs to summarize")
    p.add_argument("--source", help="Provenance (repo:path)")

    # supersede
    p = sub.add_parser("supersede", help="Mark a belief as superseded by another")
    p.add_argument("old_id", help="Belief being superseded")
    p.add_argument("new_id", help="Belief that supersedes it")

    # update
    p = sub.add_parser("update", help="Update a belief's text or source in place")
    p.add_argument("node_id", help="Belief to update")
    p.add_argument("--text", default=None, help="New text for the belief")
    p.add_argument("--source", default=None, help="Update source path")
    p.add_argument("--source-url", default=None, help="Update source URL")

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
    p = sub.add_parser("trace-access-tags", help="Trace all access tags in a node's dependency chain")
    p.add_argument("node_id", help="Node to trace")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only allow if access_tags are a subset of these tags")

    p = sub.add_parser("trace", help="Trace backward to find premises a node rests on")
    p.add_argument("node_id", help="Node to trace")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show premises whose access_tags are a subset of these tags")

    # propagate
    sub.add_parser("propagate", help="Recompute all truth values")

    # log
    p = sub.add_parser("log", help="Show propagation history")
    p.add_argument("--last", type=int, help="Show only last N entries")

    # add-repo
    p = sub.add_parser("add-repo", help="Register a repo name and path")
    p.add_argument("name", help="Repo name (used in source paths)")
    p.add_argument("path", help="Filesystem path to the repo")

    # repos
    sub.add_parser("repos", help="List registered repos")

    # derive
    p = sub.add_parser("derive", help="Derive deeper reasoning chains from existing beliefs")
    p.add_argument("-o", "--output", default="proposed-derivations.md",
                   help="Output file for proposals (default: proposed-derivations.md)")
    p.add_argument("-m", "--model", default=None,
                   help="Model to use (default: claude). Use ollama:<model> for local models")
    p.add_argument("--auto", action="store_true",
                   help="Automatically add proposals (no review step)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show prompt without invoking the model")
    p.add_argument("--domain", default=None,
                   help="Domain description for context (auto-detected from agents)")
    p.add_argument("--topic", default=None,
                   help="Keyword filter — only include beliefs matching these keywords")
    p.add_argument("--budget", type=int, default=300,
                   help="Maximum number of beliefs in prompt (default: 300)")
    p.add_argument("--sample", action="store_true",
                   help="Randomly sample beliefs instead of alphabetical truncation")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducible sampling")
    p.add_argument("--timeout", type=int, default=300,
                   help="Model timeout in seconds (default: 300)")
    p.add_argument("--premises", action="store_true",
                   help="Only include premises (no justifications)")
    p.add_argument("--has-dependents", action="store_true",
                   help="Only include nodes that others depend on")
    p.add_argument("--min-depth", type=int, default=None,
                   help="Only include beliefs at this depth or deeper (0=premises)")
    p.add_argument("--max-depth", type=int, default=None,
                   help="Only include beliefs at this depth or shallower")
    p.add_argument("--exhaust", action="store_true",
                   help="Repeat derive until no new proposals (implies --auto)")
    p.add_argument("--max-rounds", type=int, default=10,
                   help="Maximum rounds for --exhaust (default: 10)")
    p.add_argument("--report-dir", default="reviews/",
                   help="Directory for JSON reports (default: reviews/)")
    p.add_argument("--no-report", action="store_true",
                   help="Suppress JSON report generation")
    p.add_argument("--cluster", action="store_true",
                   help="Use semantic clustering to sample across domains")
    p.add_argument("--embedding-model", default=None,
                   help="Sentence-transformers model for --cluster "
                        "(default: all-MiniLM-L6-v2)")
    p.add_argument("--n-clusters", type=int, default=None,
                   help="Override automatic cluster count for --cluster")

    # accept
    p = sub.add_parser("accept", help="Accept proposals from a derive proposals file")
    p.add_argument("file", nargs="?", default="proposed-derivations.md",
                   help="Proposals file (default: proposed-derivations.md)")

    # import-agent
    p = sub.add_parser("import-agent", help="Import another agent's beliefs with namespacing")
    p.add_argument("agent_name", help="Agent name (used as namespace prefix)")
    p.add_argument("beliefs_file", help="Path to the agent's beliefs.md or network.json")
    p.add_argument("--nogoods", dest="nogoods_file", help="Path to nogoods.md (auto-detected if next to beliefs.md)")
    p.add_argument("--only-in", action="store_true", help="Only import beliefs with status IN")

    # sync-agent
    p = sub.add_parser("sync-agent", help="Sync another agent's beliefs (remote wins)")
    p.add_argument("agent_name", help="Agent name (must match previous import)")
    p.add_argument("beliefs_file", help="Path to the agent's beliefs.md or network.json")
    p.add_argument("--nogoods", dest="nogoods_file", help="Path to nogoods.md (auto-detected if next to beliefs.md)")
    p.add_argument("--only-in", action="store_true", help="Only sync beliefs with status IN")

    # import-beliefs
    p = sub.add_parser("import-beliefs", help="Import a beliefs.md registry")
    p.add_argument("beliefs_file", help="Path to beliefs.md")
    p.add_argument("--nogoods", dest="nogoods_file", help="Path to nogoods.md (auto-detected if next to beliefs.md)")

    # import-json
    p = sub.add_parser("import-json", help="Import network from JSON (produced by export)")
    p.add_argument("json_file", help="Path to JSON file")

    # export
    p = sub.add_parser("export", help="Export network as JSON")
    p.add_argument("-o", "--output", help="Write to file instead of stdout")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only export nodes whose access_tags are a subset of these tags")

    # export-markdown
    p = sub.add_parser("export-markdown", help="Export network as beliefs.md-compatible markdown")
    p.add_argument("-o", "--output", help="Write to file instead of stdout")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only export nodes whose access_tags are a subset of these tags")

    # hash-sources
    p = sub.add_parser("hash-sources", help="Backfill source hashes for nodes without them")
    p.add_argument("--force", action="store_true", help="Re-hash all nodes, even those with existing hashes")

    # check-stale
    p = sub.add_parser("check-stale", help="Check IN nodes for source file staleness")
    p.add_argument("--upgrade-hashes", action="store_true",
                   help="Upgrade truncated hashes to full length in place")

    # compact
    p = sub.add_parser("compact", help="Token-budgeted belief state summary")
    p.add_argument("--budget", type=int, default=500, help="Token budget (default: 500)")
    p.add_argument("--no-truncate", action="store_true", help="Show full node text")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only include nodes whose access_tags are a subset of these tags")

    # search
    p = sub.add_parser("search", help="Search nodes using full-text search with neighbor expansion")
    p.add_argument("query", help="Search terms (FTS5 all-terms matching)")
    p.add_argument("--format", choices=["markdown", "json", "minimal"], default="markdown",
                   help="Output format (default: markdown)")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show nodes whose access_tags are a subset of these tags")

    # lookup
    p = sub.add_parser("lookup", help="Simple keyword search over beliefs (no neighbor expansion)")
    p.add_argument("query", help="Search terms (all must match, case-insensitive)")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show nodes whose access_tags are a subset of these tags")

    # ask
    p = sub.add_parser("ask", help="Ask a question about beliefs (FTS5 search + LLM synthesis)")
    p.add_argument("question", help="Natural language question")
    p.add_argument("--no-synth", action="store_true",
                   help="Show belief matches only, no LLM synthesis")
    p.add_argument("--format", choices=["compact", "markdown", "json", "minimal"],
                   default=None,
                   help="Output format for --no-synth (default: compact)")
    p.add_argument("--timeout", type=int, default=300,
                   help="LLM timeout in seconds (default: 300)")
    p.add_argument("-m", "--model", default=None,
                   help="Model to use (default: claude). Use ollama:<model> for local models")
    p.add_argument("--simple", action="store_true",
                   help="Single-pass synthesis with pre-retrieved beliefs (better for smaller models)")
    p.add_argument("--full-sources", default=None, metavar="FTS_DB",
                   help="Also search source document chunks from FTS5 index (e.g. rag_fts.db)")
    p.add_argument("--natural", action="store_true",
                   help="Strip belief IDs, status, and justification metadata from context")
    p.add_argument("--dual", action="store_true",
                   help="Run TMS and FTS RAG separately, then merge (requires --full-sources)")

    # deduplicate
    p = sub.add_parser("deduplicate", help="Find and optionally retract duplicate IN beliefs")
    p.add_argument("--threshold", type=float, default=0.5,
                   help="Jaccard similarity threshold for ID tokens (default: 0.5)")
    p.add_argument("--auto", action="store_true",
                   help="Automatically retract duplicates (keeps one per cluster)")
    p.add_argument("-o", "--output", default="proposed-dedup.md",
                   help="Output file for dedup plan (default: proposed-dedup.md)")
    p.add_argument("--accept", metavar="FILE",
                   help="Apply a reviewed dedup plan file")

    # cluster-list
    p = sub.add_parser("cluster-list", help="List semantic similarity clusters")
    p.add_argument("--status", choices=["IN", "OUT"], default="IN",
                   help="Filter by truth value (default: IN)")
    p.add_argument("--n-clusters", type=int, default=None,
                   help="Override automatic cluster count")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducible clustering")
    p.add_argument("--embedding-model", default=None,
                   help="Sentence-transformers model (default: all-MiniLM-L6-v2)")
    p.add_argument("--visible-to", metavar="TAG,TAG",
                   help="Only show nodes whose access_tags are a subset of these tags")
    p.add_argument("--format", choices=["text", "json", "markdown"], default="text",
                   help="Output format (default: text)")

    # namespaces
    p = sub.add_parser("list-gated", help="List OUT nodes blocked by IN outlist nodes")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show nodes whose access_tags are a subset of these tags")

    p = sub.add_parser("list-negative", help="Find IN beliefs describing problems/defects/risks (LLM-classified)")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show nodes whose access_tags are a subset of these tags")
    p.add_argument("-m", "--model", default=None,
                   help="Model to use (default: claude). Use ollama:<model> for local models")

    sub.add_parser("namespaces", help="List all agent namespaces in the database")

    # review-beliefs
    p = sub.add_parser("review-beliefs", help="Review derived beliefs for validity, sufficiency, and necessity")
    p.add_argument("ids", nargs="*", help="Specific belief IDs to review (default: all derived)")
    p.add_argument("-m", "--model", default=None,
                   help="Model to use (default: claude). Use ollama:<model> for local models")
    p.add_argument("--timeout", type=int, default=300,
                   help="LLM timeout in seconds (default: 300)")
    p.add_argument("--min-depth", type=int, default=None,
                   help="Only review beliefs at this depth or deeper")
    p.add_argument("--depends-on", default=None,
                   help="Only review beliefs depending on this node")
    p.add_argument("--sample", type=int, default=None,
                   help="Randomly sample N beliefs to review")
    p.add_argument("--dry-run", action="store_true",
                   help="Report findings without taking action")
    p.add_argument("--auto-retract", action="store_true",
                   help="Retract beliefs found invalid")
    p.add_argument("-o", "--output", default=None,
                   help="Write findings to markdown file")
    p.add_argument("--visible-to", metavar="TAG,TAG",
                   help="Only review nodes whose access_tags are a subset of these tags")
    p.add_argument("--report-dir", default="reviews",
                   help="Directory for JSON reports (default: reviews/)")
    p.add_argument("--no-report", action="store_true",
                   help="Skip JSON report generation")

    # contradictions
    p = sub.add_parser("contradictions", help="Detect contradictions between IN beliefs")
    p.add_argument("ids", nargs="*", help="Specific belief IDs to check (default: all IN)")
    p.add_argument("-m", "--model", default=None,
                   help="Model to use (default: claude). Use ollama:<model> for local models")
    p.add_argument("--timeout", type=int, default=300,
                   help="LLM timeout in seconds (default: 300)")
    p.add_argument("--sample", type=int, default=None,
                   help="Randomly sample N beliefs to check")
    p.add_argument("--dry-run", action="store_true",
                   help="Show findings without applying nogoods")
    p.add_argument("--auto-apply", action="store_true",
                   help="Auto-apply detected nogoods via dependency-directed backtracking")
    p.add_argument("-o", "--output", default=None,
                   help="Write proposals to markdown file")

    # list
    p = sub.add_parser("list", help="List nodes with filters")
    p.add_argument("--status", choices=["IN", "OUT"], help="Filter by truth value")
    p.add_argument("--premises", action="store_true", help="Only show premises (no justifications)")
    p.add_argument("--has-dependents", action="store_true", help="Only show nodes that others depend on")
    p.add_argument("--challenged", action="store_true", help="Only show nodes with active challenges")
    p.add_argument("-n", "--namespace", help="Filter to nodes in this namespace")
    p.add_argument("--min-depth", type=int, default=None,
                   help="Only show beliefs at this depth or deeper (0=premises)")
    p.add_argument("--max-depth", type=int, default=None,
                   help="Only show beliefs at this depth or shallower")
    p.add_argument("--visible-to", metavar="TAG,TAG", help="Only show nodes whose access_tags are a subset of these tags")
    p.add_argument("--not-reviewed-since", type=int, default=None, metavar="DAYS",
                   help="Derived beliefs not reviewed in the last N days (or never)")
    p.add_argument("--never-reviewed", action="store_true",
                   help="Derived beliefs that have never been reviewed")
    p.add_argument("--by-impact", action="store_true",
                   help="Sort output by dependent count (descending)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "add": cmd_add,
        "add-justification": cmd_add_justification,
        "remove-justification": cmd_remove_justification,
        "retract": cmd_retract,
        "assert": cmd_assert,
        "what-if": cmd_what_if,
        "status": cmd_status,
        "show": cmd_show,
        "explain": cmd_explain,
        "nogood": cmd_nogood,
        "propagate": cmd_propagate,
        "log": cmd_log,
        "add-repo": cmd_add_repo,
        "repos": cmd_repos,
        "derive": cmd_derive,
        "accept": cmd_accept,
        "import-agent": cmd_import_agent,
        "sync-agent": cmd_sync_agent,
        "import-beliefs": cmd_import_beliefs,
        "import-json": cmd_import_json,
        "export": cmd_export,
        "export-markdown": cmd_export_markdown,
        "hash-sources": cmd_hash_sources,
        "check-stale": cmd_check_stale,
        "compact": cmd_compact,
        "convert-to-premise": cmd_convert_to_premise,
        "summarize": cmd_summarize,
        "supersede": cmd_supersede,
        "update": cmd_update,
        "challenge": cmd_challenge,
        "defend": cmd_defend,
        "trace": cmd_trace,
        "trace-access-tags": cmd_trace_access_tags,
        "search": cmd_search,
        "lookup": cmd_lookup,
        "ask": cmd_ask,
        "deduplicate": cmd_deduplicate,
        "cluster-list": cmd_cluster_list,
        "list": cmd_list,
        "list-gated": cmd_list_gated,
        "list-negative": cmd_list_negative,
        "review-beliefs": cmd_review_beliefs,
        "contradictions": cmd_contradictions,
        "namespaces": cmd_namespaces,
    }
    commands[args.command](args)
