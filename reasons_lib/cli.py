"""CLI for the Reason Maintenance System.

Thin wrappers around reasons_lib.api — each command calls an api function
and formats the result dict for terminal output.
"""

import argparse
import json
import sys
from pathlib import Path

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
            namespace=getattr(args, "namespace", None),
            db_path=args.db,
        )
        print(f"Added {result['node_id']} [{result['truth_value']}] ({result['type']})")
    except ValueError as e:
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


def cmd_retract(args):
    try:
        result = api.retract_node(args.node_id, reason=args.reason or "", db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result["changed"]:
        print(f"{args.node_id} is already OUT")
    else:
        print(f"Retracted {args.node_id}")
        _print_cascade(result)


def cmd_assert(args):
    try:
        result = api.assert_node(args.node_id, db_path=args.db)
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
            result = api.what_if_retract(args.node_id, db_path=args.db)
            if result.get("already_out"):
                print(f"{args.node_id} is already OUT — nothing to simulate.")
                return
        else:
            result = api.what_if_assert(args.node_id, db_path=args.db)
            if result.get("already_in"):
                print(f"{args.node_id} is already IN — nothing to simulate.")
                return
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    _print_what_if_results(result, action, args.node_id)


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

    if node["metadata"].get("retract_reason"):
        print(f"\nRetract reason: {node['metadata']['retract_reason']}")

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


def cmd_supersede(args):
    try:
        result = api.supersede(args.old_id, args.new_id, db_path=args.db)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Superseded {result['old_id']} by {result['new_id']}")
    if result["changed"]:
        print(f"Changed: {', '.join(result['changed'])}")


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
    from .storage import Storage
    store = Storage(args.db)
    net = store.load()

    changed = net.recompute_all()

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


def cmd_add_repo(args):
    result = api.add_repo(args.name, args.path, db_path=args.db)
    print(f"Added repo {result['name']}: {result['path']}")


def cmd_repos(args):
    result = api.list_repos(db_path=args.db)
    if not result["repos"]:
        print("No repos registered.")
        return
    for name, path in sorted(result["repos"].items()):
        print(f"  {name}: {path}")
    print(f"\n{len(result['repos'])} repo(s)")


def cmd_import_agent(args):
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


def cmd_deduplicate(args):
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


def _derive_one_round(args, round_num=None):
    """Run a single derive round. Returns number of beliefs added (0 = saturated).

    Used by cmd_derive for both single-round and --exhaust mode.
    """
    import asyncio
    import os
    import shutil

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
    )

    print(f"{prefix}Network: {stats['total_in']} IN beliefs, "
          f"{stats['total_derived']} derived, max depth {stats['max_depth']}",
          file=sys.stderr)
    if stats.get("topic"):
        print(f"{prefix}Topic filter: {stats['topic']}", file=sys.stderr)
    if stats.get("sample"):
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
    model_commands = {
        "claude": ["claude", "-p"],
        "gemini": ["gemini", "-p", ""],
    }

    if model not in model_commands:
        print(f"{prefix}Unknown model: {model}. Available: {list(model_commands.keys())}",
              file=sys.stderr)
        return -1

    cmd = model_commands[model]
    if not shutil.which(cmd[0]):
        print(f"{prefix}Error: '{cmd[0]}' CLI not found in PATH", file=sys.stderr)
        return -1

    print(f"{prefix}Deriving with {model}...", file=sys.stderr)

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    async def _invoke():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode()),
            timeout=args.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Model failed: {stderr.decode()}")
        return stdout.decode()

    try:
        response = asyncio.run(_invoke())
    except TimeoutError:
        print(f"{prefix}Model timed out after {args.timeout}s", file=sys.stderr)
        return -1
    except Exception as e:
        print(f"{prefix}Error: {e}", file=sys.stderr)
        return -1

    # Parse and validate proposals
    proposals = parse_proposals(response)

    if not proposals:
        print(f"{prefix}No new proposals — network saturated.", file=sys.stderr)
        return 0

    valid, skipped = validate_proposals(proposals, nodes)

    for p, reason in skipped:
        print(f"  SKIP {p['id']}: {reason}", file=sys.stderr)

    print(f"\n{prefix}{len(valid)} valid proposals "
          f"({len(skipped)} skipped)", file=sys.stderr)

    if not valid:
        return 0

    if args.auto or args.exhaust:
        results = apply_proposals(valid, db_path=args.db)
        added = 0
        for p, result in results:
            if isinstance(result, dict):
                print(f"  Added {p['id']} [{result['truth_value']}]")
                added += 1
            else:
                print(f"  FAIL {p['id']}: {result}", file=sys.stderr)
        if added:
            print(f"\n{prefix}Added {added} derived beliefs.", file=sys.stderr)
        return added
    else:
        output_path = Path(args.output)
        write_proposals_file(valid, output_path)
        print(f"\n{prefix}Wrote {output_path} ({len(valid)} proposals)")
        return len(valid)


def cmd_derive(args):
    if args.exhaust:
        max_rounds = args.max_rounds
        total_added = 0
        for round_num in range(1, max_rounds + 1):
            print(f"\n{'=' * 40}", file=sys.stderr)
            print(f"Round {round_num}/{max_rounds}", file=sys.stderr)
            print(f"{'=' * 40}", file=sys.stderr)
            added = _derive_one_round(args, round_num=round_num)
            if added < 0:
                print(f"\nExhaust stopped: error in round {round_num}.",
                      file=sys.stderr)
                sys.exit(1)
            if added == 0:
                print(f"\nExhaust complete: saturated after {round_num} rounds. "
                      f"Total added: {total_added}.", file=sys.stderr)
                return
            total_added += added
        print(f"\nExhaust complete: hit max rounds ({max_rounds}). "
              f"Total added: {total_added}.", file=sys.stderr)
    else:
        added = _derive_one_round(args)
        if added < 0:
            sys.exit(1)


def cmd_accept(args):
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


def cmd_namespaces(args):
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
    parser.add_argument("--db", default=api.DEFAULT_DB, help="Path to database (default: reasons.db)")
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
    p.add_argument("-n", "--namespace", help="Namespace prefix (auto-creates ns:active premise)")

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

    # supersede
    p = sub.add_parser("supersede", help="Mark a belief as superseded by another")
    p.add_argument("old_id", help="Belief being superseded")
    p.add_argument("new_id", help="Belief that supersedes it")

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
                   help="Model to use: claude or gemini (default: claude)")
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
    p.add_argument("--exhaust", action="store_true",
                   help="Repeat derive until no new proposals (implies --auto)")
    p.add_argument("--max-rounds", type=int, default=10,
                   help="Maximum rounds for --exhaust (default: 10)")

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

    # namespaces
    sub.add_parser("namespaces", help="List all agent namespaces in the database")

    # list
    p = sub.add_parser("list", help="List nodes with filters")
    p.add_argument("--status", choices=["IN", "OUT"], help="Filter by truth value")
    p.add_argument("--premises", action="store_true", help="Only show premises (no justifications)")
    p.add_argument("--has-dependents", action="store_true", help="Only show nodes that others depend on")
    p.add_argument("--challenged", action="store_true", help="Only show nodes with active challenges")
    p.add_argument("-n", "--namespace", help="Filter to nodes in this namespace")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "add": cmd_add,
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
        "challenge": cmd_challenge,
        "defend": cmd_defend,
        "trace": cmd_trace,
        "search": cmd_search,
        "lookup": cmd_lookup,
        "deduplicate": cmd_deduplicate,
        "list": cmd_list,
        "namespaces": cmd_namespaces,
    }
    commands[args.command](args)
