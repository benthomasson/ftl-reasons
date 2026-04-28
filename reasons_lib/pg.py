"""PostgreSQL-native storage backend for the dependency network.

Each operation is a SQL transaction — no full-network load/save.
Enables concurrent writers and multi-tenant deployment.

Requires psycopg v3: pip install 'psycopg[binary]>=3.1'
"""

import json
from collections import deque
from datetime import datetime

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]


SCHEMA = """
CREATE TABLE IF NOT EXISTS rms_nodes (
    id TEXT NOT NULL,
    project_id UUID NOT NULL,
    text TEXT NOT NULL,
    truth_value TEXT NOT NULL DEFAULT 'IN' CHECK (truth_value IN ('IN', 'OUT')),
    source TEXT DEFAULT '',
    source_hash TEXT DEFAULT '',
    date TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS rms_justifications (
    id SERIAL PRIMARY KEY,
    node_id TEXT NOT NULL,
    project_id UUID NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('SL', 'CP')),
    antecedents JSONB NOT NULL DEFAULT '[]',
    outlist JSONB NOT NULL DEFAULT '[]',
    label TEXT DEFAULT '',
    FOREIGN KEY (node_id, project_id) REFERENCES rms_nodes(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rms_nogoods (
    id TEXT NOT NULL,
    project_id UUID NOT NULL,
    nodes JSONB NOT NULL DEFAULT '[]',
    discovered TEXT DEFAULT '',
    resolution TEXT DEFAULT '',
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS rms_propagation_log (
    id SERIAL PRIMARY KEY,
    project_id UUID NOT NULL,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rms_network_meta (
    key TEXT NOT NULL,
    project_id UUID NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (key, project_id)
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_rms_nodes_project ON rms_nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_rms_nodes_status ON rms_nodes(project_id, truth_value);
CREATE INDEX IF NOT EXISTS idx_rms_justifications_node ON rms_justifications(node_id, project_id);
CREATE INDEX IF NOT EXISTS idx_rms_nogoods_project ON rms_nogoods(project_id);
CREATE INDEX IF NOT EXISTS idx_rms_log_project ON rms_propagation_log(project_id);
CREATE INDEX IF NOT EXISTS idx_rms_nodes_fts ON rms_nodes USING gin(to_tsvector('english', text));
CREATE INDEX IF NOT EXISTS idx_rms_justifications_antecedents ON rms_justifications USING gin(antecedents);
CREATE INDEX IF NOT EXISTS idx_rms_justifications_outlist ON rms_justifications USING gin(outlist);
"""


def _require_psycopg():
    if psycopg is None:
        raise ImportError(
            "psycopg is required for PostgreSQL support. "
            "Install it with: pip install 'psycopg[binary]>=3.1'"
        )


class PgApi:
    """PostgreSQL-native API for the dependency network.

    Each method executes as a SQL transaction. No in-memory Network object.
    """

    def __init__(self, conninfo, project_id):
        _require_psycopg()
        if isinstance(conninfo, str):
            self.conn = psycopg.connect(conninfo, autocommit=False)
            self._owns_conn = True
        else:
            self.conn = conninfo
            self._owns_conn = False
        self.project_id = str(project_id)

    def close(self):
        if self._owns_conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *exc):
        if exc_type is not None:
            self.conn.rollback()
        self.close()

    # ── Schema ──────────────────────────────────────────────────

    def init_db(self):
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute(INDEXES)
        self.conn.commit()
        return {"project_id": self.project_id, "created": True}

    # ── Core mutations ──────────────────────────────────────────

    def add_node(self, node_id, text, sl="", cp="", unless="", label="",
                 source="", access_tags=None):
        pid = self.project_id
        now = datetime.now().isoformat(timespec="seconds")
        metadata = {}
        if access_tags:
            metadata["access_tags"] = sorted(access_tags)

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM rms_nodes WHERE id = %s AND project_id = %s",
                (node_id, pid),
            )
            if cur.fetchone():
                raise ValueError(f"Node '{node_id}' already exists")

            cur.execute(
                "INSERT INTO rms_nodes (id, project_id, text, source, date, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (node_id, pid, text, source, now, json.dumps(metadata)),
            )

            justifications = self._parse_justifications(sl, cp, unless, label)

            for j in justifications:
                cur.execute(
                    "INSERT INTO rms_justifications (node_id, project_id, type, antecedents, outlist, label) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (node_id, pid, j["type"],
                     json.dumps(j["antecedents"]), json.dumps(j["outlist"]), j["label"]),
                )

            # Inherit access tags from antecedents
            if justifications:
                self._inherit_access_tags(cur, node_id, justifications)

            # Compute initial truth value
            if justifications:
                truth = self._compute_truth(cur, node_id)
            else:
                truth = "IN"

            cur.execute(
                "UPDATE rms_nodes SET truth_value = %s WHERE id = %s AND project_id = %s",
                (truth, node_id, pid),
            )

            self._log(cur, "add", node_id, truth)

            # Count premises for return value
            cur.execute(
                "SELECT COUNT(*) FROM rms_nodes WHERE project_id = %s "
                "AND NOT EXISTS (SELECT 1 FROM rms_justifications j "
                "WHERE j.node_id = rms_nodes.id AND j.project_id = rms_nodes.project_id)",
                (pid,),
            )
            premise_count = cur.fetchone()[0]

        self.conn.commit()
        return {
            "node_id": node_id,
            "truth_value": truth,
            "type": "premise" if not justifications else "derived",
            "premise_count": premise_count,
        }

    def add_justification(self, node_id, sl="", cp="", unless="", label=""):
        pid = self.project_id

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT truth_value FROM rms_nodes WHERE id = %s AND project_id = %s",
                (node_id, pid),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"Node '{node_id}' not found")
            old_value = row[0]

            justifications = self._parse_justifications(sl, cp, unless, label)
            if not justifications:
                raise ValueError("No justification specified (use --sl or --cp)")

            for j in justifications:
                cur.execute(
                    "INSERT INTO rms_justifications (node_id, project_id, type, antecedents, outlist, label) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (node_id, pid, j["type"],
                     json.dumps(j["antecedents"]), json.dumps(j["outlist"]), j["label"]),
                )

            self._inherit_access_tags(cur, node_id, justifications)

            new_value = self._compute_truth(cur, node_id)
            changed = []

            if old_value != new_value:
                cur.execute(
                    "UPDATE rms_nodes SET truth_value = %s WHERE id = %s AND project_id = %s",
                    (new_value, node_id, pid),
                )
                changed.append(node_id)
                went_out, went_in = self._propagate(cur, node_id)
                changed.extend(went_out)
                changed.extend(went_in)

            self._log(cur, "add-justification", node_id, new_value)

        self.conn.commit()
        return {
            "node_id": node_id,
            "old_truth_value": old_value,
            "new_truth_value": new_value,
            "changed": changed,
        }

    def retract_node(self, node_id, reason=""):
        pid = self.project_id

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT truth_value, metadata FROM rms_nodes WHERE id = %s AND project_id = %s",
                (node_id, pid),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"Node '{node_id}' not found")

            old_value, metadata = row[0], row[1]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            metadata["_retracted"] = True
            if reason:
                metadata["retract_reason"] = reason

            if old_value == "OUT":
                cur.execute(
                    "UPDATE rms_nodes SET metadata = %s WHERE id = %s AND project_id = %s",
                    (json.dumps(metadata), node_id, pid),
                )
                self.conn.commit()
                return {"changed": [], "went_out": [], "went_in": []}

            cur.execute(
                "UPDATE rms_nodes SET truth_value = 'OUT', metadata = %s "
                "WHERE id = %s AND project_id = %s",
                (json.dumps(metadata), node_id, pid),
            )
            self._log(cur, "retract", node_id, reason or "OUT")

            went_out, went_in = self._propagate(cur, node_id)

        self.conn.commit()
        all_changed = [node_id] + went_out + went_in
        return {"changed": all_changed, "went_out": [node_id] + went_out, "went_in": went_in}

    def assert_node(self, node_id):
        pid = self.project_id

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT truth_value, metadata FROM rms_nodes WHERE id = %s AND project_id = %s",
                (node_id, pid),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"Node '{node_id}' not found")

            old_value, metadata = row[0], row[1]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            if old_value == "IN":
                return {"changed": [], "went_out": [], "went_in": []}

            metadata.pop("_retracted", None)
            cur.execute(
                "UPDATE rms_nodes SET truth_value = 'IN', metadata = %s "
                "WHERE id = %s AND project_id = %s",
                (json.dumps(metadata), node_id, pid),
            )
            self._log(cur, "assert", node_id, "IN")

            went_out, went_in = self._propagate(cur, node_id)

        self.conn.commit()
        all_changed = [node_id] + went_out + went_in
        return {"changed": all_changed, "went_out": went_out, "went_in": [node_id] + went_in}

    # ── Read operations ─────────────────────────────────────────

    def get_status(self, visible_to=None):
        pid = self.project_id
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT n.id, n.text, n.truth_value, n.metadata, "
                "(SELECT COUNT(*) FROM rms_justifications j "
                " WHERE j.node_id = n.id AND j.project_id = n.project_id) AS jcount "
                "FROM rms_nodes n WHERE n.project_id = %s ORDER BY n.id",
                (pid,),
            )
            rows = cur.fetchall()

        nodes = []
        for row in rows:
            nid, text, tv, meta, jcount = row
            if isinstance(meta, str):
                meta = json.loads(meta)
            if visible_to is not None and not self._is_visible(meta, visible_to):
                continue
            nodes.append({
                "id": nid,
                "text": text,
                "truth_value": tv,
                "justification_count": jcount,
            })

        in_count = sum(1 for n in nodes if n["truth_value"] == "IN")
        return {"nodes": nodes, "in_count": in_count, "total": len(nodes)}

    def show_node(self, node_id, visible_to=None):
        pid = self.project_id
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, text, truth_value, source, source_hash, metadata "
                "FROM rms_nodes WHERE id = %s AND project_id = %s",
                (node_id, pid),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"Node '{node_id}' not found")

            nid, text, tv, source, source_hash, meta = row
            if isinstance(meta, str):
                meta = json.loads(meta)

            if visible_to is not None and not self._is_visible(meta, visible_to):
                raise PermissionError(f"Access denied for node '{node_id}'")

            cur.execute(
                "SELECT type, antecedents, outlist, label FROM rms_justifications "
                "WHERE node_id = %s AND project_id = %s ORDER BY id",
                (node_id, pid),
            )
            justifications = []
            for jrow in cur.fetchall():
                jtype, ants, outs, jlabel = jrow
                if isinstance(ants, str):
                    ants = json.loads(ants)
                if isinstance(outs, str):
                    outs = json.loads(outs)
                j = {"type": jtype, "antecedents": ants, "outlist": outs, "label": jlabel}
                justifications.append(j)

            dependents = sorted(self._find_dependents(cur, [node_id]))

        return {
            "id": nid,
            "text": text,
            "truth_value": tv,
            "source": source,
            "source_hash": source_hash,
            "justifications": justifications,
            "dependents": dependents,
            "metadata": meta,
        }

    def search(self, query, visible_to=None, format="markdown"):
        pid = self.project_id

        with self.conn.cursor() as cur:
            # plainto_tsquery handles arbitrary user input safely
            if query.strip():
                cur.execute(
                    "SELECT id, text, truth_value, source, metadata "
                    "FROM rms_nodes "
                    "WHERE project_id = %s "
                    "AND (to_tsvector('english', text) @@ plainto_tsquery('english', %s) "
                    "     OR id ILIKE %s) "
                    "ORDER BY ts_rank(to_tsvector('english', text), "
                    "         plainto_tsquery('english', %s)) DESC "
                    "LIMIT 20",
                    (pid, query, f"%{query}%", query),
                )
            else:
                cur.execute(
                    "SELECT id, text, truth_value, source, metadata "
                    "FROM rms_nodes WHERE project_id = %s AND id ILIKE %s LIMIT 20",
                    (pid, f"%{query}%"),
                )

            matched_rows = cur.fetchall()

        if not matched_rows:
            return "No results found."

        # Apply visibility filter
        matched = []
        for row in matched_rows:
            nid, text, tv, source, meta = row
            if isinstance(meta, str):
                meta = json.loads(meta)
            if visible_to is not None and not self._is_visible(meta, visible_to):
                continue
            matched.append({
                "id": nid, "text": text, "truth_value": tv,
                "source": source, "metadata": meta,
            })

        if not matched:
            return "No results found."

        matched_ids = [m["id"] for m in matched]

        # Neighbor expansion
        with self.conn.cursor() as cur:
            neighbors = self._expand_neighbors(cur, matched_ids, visible_to)

        return self._format_results(matched, neighbors, format)

    def list_nodes(self, status=None, premises_only=False, has_dependents=False,
                   namespace=None, visible_to=None):
        pid = self.project_id
        conditions = ["n.project_id = %s"]
        params = [pid]

        if status:
            conditions.append("n.truth_value = %s")
            params.append(status)

        if premises_only:
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM rms_justifications j "
                "WHERE j.node_id = n.id AND j.project_id = n.project_id)"
            )

        if namespace:
            conditions.append("n.id LIKE %s")
            params.append(f"{namespace}:%")

        where = " AND ".join(conditions)

        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT n.id, n.text, n.truth_value, n.metadata, "
                f"(SELECT COUNT(*) FROM rms_justifications j "
                f" WHERE j.node_id = n.id AND j.project_id = n.project_id) AS jcount "
                f"FROM rms_nodes n WHERE {where} ORDER BY n.id",
                params,
            )
            rows = cur.fetchall()

            # For has_dependents filter, we need the reverse lookup
            if has_dependents:
                all_ids = [r[0] for r in rows]
                dep_set = self._find_dependents(cur, all_ids) if all_ids else set()
                # dep_set contains nodes that ARE dependents, not nodes that HAVE dependents
                # We need nodes that appear in others' justifications
                ids_with_deps = set()
                if all_ids:
                    cur.execute(
                        "SELECT DISTINCT je.value FROM rms_justifications j, "
                        "jsonb_array_elements_text(j.antecedents) je(value) "
                        "WHERE j.project_id = %s "
                        "UNION "
                        "SELECT DISTINCT je.value FROM rms_justifications j, "
                        "jsonb_array_elements_text(j.outlist) je(value) "
                        "WHERE j.project_id = %s",
                        (pid, pid),
                    )
                    ids_with_deps = {r[0] for r in cur.fetchall()}

        nodes = []
        for row in rows:
            nid, text, tv, meta, jcount = row
            if isinstance(meta, str):
                meta = json.loads(meta)
            if visible_to is not None and not self._is_visible(meta, visible_to):
                continue
            if has_dependents and nid not in ids_with_deps:
                continue
            nodes.append({
                "id": nid,
                "text": text,
                "truth_value": tv,
                "justification_count": jcount,
            })

        return {"nodes": nodes, "count": len(nodes)}

    def get_log(self, last=None):
        pid = self.project_id
        with self.conn.cursor() as cur:
            if last:
                cur.execute(
                    "SELECT timestamp, action, target, value FROM rms_propagation_log "
                    "WHERE project_id = %s ORDER BY id DESC LIMIT %s",
                    (pid, last),
                )
                entries = [
                    {"timestamp": r[0], "action": r[1], "target": r[2], "value": r[3]}
                    for r in reversed(cur.fetchall())
                ]
            else:
                cur.execute(
                    "SELECT timestamp, action, target, value FROM rms_propagation_log "
                    "WHERE project_id = %s ORDER BY id",
                    (pid,),
                )
                entries = [
                    {"timestamp": r[0], "action": r[1], "target": r[2], "value": r[3]}
                    for r in cur.fetchall()
                ]
        return {"entries": entries}

    # ── Nogoods + explain ───────────────────────────────────────

    def add_nogood(self, node_ids):
        pid = self.project_id

        with self.conn.cursor() as cur:
            # Verify all nodes exist
            cur.execute(
                "SELECT id, truth_value FROM rms_nodes WHERE project_id = %s AND id = ANY(%s)",
                (pid, node_ids),
            )
            found = {r[0]: r[1] for r in cur.fetchall()}
            for nid in node_ids:
                if nid not in found:
                    raise KeyError(f"Node '{nid}' not found")

            # Get next nogood ID
            cur.execute(
                "SELECT value FROM rms_network_meta "
                "WHERE key = 'next_nogood_id' AND project_id = %s",
                (pid,),
            )
            row = cur.fetchone()
            next_id = int(row[0]) if row else 1
            nogood_id = f"nogood-{next_id:03d}"

            cur.execute(
                "INSERT INTO rms_network_meta (key, project_id, value) "
                "VALUES ('next_nogood_id', %s, %s) "
                "ON CONFLICT (key, project_id) DO UPDATE SET value = EXCLUDED.value",
                (pid, str(next_id + 1)),
            )

            cur.execute(
                "INSERT INTO rms_nogoods (id, project_id, nodes, discovered) "
                "VALUES (%s, %s, %s, %s)",
                (nogood_id, pid, json.dumps(node_ids),
                 datetime.now().isoformat(timespec="seconds")),
            )
            self._log(cur, "nogood", nogood_id, str(node_ids))

            # Check if contradiction is active
            all_in = all(found.get(nid) == "IN" for nid in node_ids)
            if not all_in:
                self.conn.commit()
                return {"nogood_id": nogood_id, "changed": [], "backtracked_to": None}

            # Dependency-directed backtracking
            culprits = self._find_culprits_internal(cur, node_ids)

            if culprits:
                victim_id = culprits[0]["premise"]
                self._log(cur, "backtrack", victim_id, f"culprit for {nogood_id}")
            else:
                # Fallback: retract node with fewest dependents
                dep_counts = []
                for nid in node_ids:
                    deps = self._find_dependents(cur, [nid])
                    dep_counts.append((nid, len(deps)))
                dep_counts.sort(key=lambda x: x[1])
                victim_id = dep_counts[0][0]

            # Retract the victim
            cur.execute(
                "SELECT metadata FROM rms_nodes WHERE id = %s AND project_id = %s",
                (victim_id, pid),
            )
            meta = cur.fetchone()[0]
            if isinstance(meta, str):
                meta = json.loads(meta)
            meta["_retracted"] = True
            cur.execute(
                "UPDATE rms_nodes SET truth_value = 'OUT', metadata = %s "
                "WHERE id = %s AND project_id = %s",
                (json.dumps(meta), victim_id, pid),
            )
            self._log(cur, "retract", victim_id, f"backtrack for {nogood_id}")

            went_out, went_in = self._propagate(cur, victim_id)

        self.conn.commit()
        changed = [victim_id] + went_out + went_in
        return {"nogood_id": nogood_id, "changed": changed, "backtracked_to": victim_id}

    def find_culprits(self, node_ids):
        with self.conn.cursor() as cur:
            culprits = self._find_culprits_internal(cur, node_ids)
        return {"culprits": culprits}

    def explain_node(self, node_id, visible_to=None):
        pid = self.project_id

        with self.conn.cursor() as cur:
            steps = self._explain_recursive(cur, node_id, visible_to, set())
        return {"steps": steps}

    def trace_assumptions(self, node_id, visible_to=None):
        pid = self.project_id
        premises = []
        visited = set()

        with self.conn.cursor() as cur:
            self._trace_assumptions_recursive(cur, node_id, premises, visited)

        return {"node_id": node_id, "premises": premises}

    # ── Internal: propagation ───────────────────────────────────

    def _propagate(self, cur, changed_id):
        """BFS propagation of truth value changes through dependents.

        Returns (went_out, went_in) lists.
        """
        went_out = []
        went_in = []
        queue = deque([changed_id])
        visited = {changed_id}
        pid = self.project_id

        while queue:
            batch = []
            while queue:
                batch.append(queue.popleft())

            # Find all dependents of this batch
            dep_ids = self._find_dependents(cur, batch) - visited

            if not dep_ids:
                continue

            # Fetch current state of all dependents
            cur.execute(
                "SELECT id, truth_value, metadata FROM rms_nodes "
                "WHERE project_id = %s AND id = ANY(%s)",
                (pid, list(dep_ids)),
            )
            dep_states = {}
            for row in cur.fetchall():
                nid, tv, meta = row
                if isinstance(meta, str):
                    meta = json.loads(meta)
                dep_states[nid] = (tv, meta)

            # Fetch all justifications for these dependents
            cur.execute(
                "SELECT node_id, type, antecedents, outlist FROM rms_justifications "
                "WHERE project_id = %s AND node_id = ANY(%s)",
                (pid, list(dep_ids)),
            )
            justs_by_node = {}
            all_referenced = set()
            for row in cur.fetchall():
                nid, jtype, ants, outs = row
                if isinstance(ants, str):
                    ants = json.loads(ants)
                if isinstance(outs, str):
                    outs = json.loads(outs)
                justs_by_node.setdefault(nid, []).append((jtype, ants, outs))
                all_referenced.update(ants)
                all_referenced.update(outs)

            # Batch-fetch truth values for all referenced nodes
            truth_cache = {}
            if all_referenced:
                cur.execute(
                    "SELECT id, truth_value FROM rms_nodes "
                    "WHERE project_id = %s AND id = ANY(%s)",
                    (pid, list(all_referenced)),
                )
                for row in cur.fetchall():
                    truth_cache[row[0]] = row[1]

            # Evaluate each dependent
            for dep_id in dep_ids:
                if dep_id not in dep_states:
                    continue
                old_tv, meta = dep_states[dep_id]

                if meta.get("_retracted"):
                    continue

                justs = justs_by_node.get(dep_id, [])
                if not justs:
                    continue  # premise — keep current

                new_tv = "OUT"
                for jtype, ants, outs in justs:
                    inlist_ok = all(
                        truth_cache.get(a, "OUT") == "IN" for a in ants
                    )
                    outlist_ok = all(
                        truth_cache.get(o, "OUT") == "OUT" for o in outs
                    )
                    if inlist_ok and outlist_ok:
                        new_tv = "IN"
                        break

                if old_tv != new_tv:
                    cur.execute(
                        "UPDATE rms_nodes SET truth_value = %s "
                        "WHERE id = %s AND project_id = %s",
                        (new_tv, dep_id, pid),
                    )
                    self._log(cur, "propagate", dep_id, new_tv)
                    truth_cache[dep_id] = new_tv
                    visited.add(dep_id)
                    queue.append(dep_id)
                    if new_tv == "OUT":
                        went_out.append(dep_id)
                    else:
                        went_in.append(dep_id)

        return went_out, went_in

    def _compute_truth(self, cur, node_id):
        """Compute truth value from justifications."""
        pid = self.project_id
        cur.execute(
            "SELECT type, antecedents, outlist FROM rms_justifications "
            "WHERE node_id = %s AND project_id = %s",
            (node_id, pid),
        )
        justs = cur.fetchall()
        if not justs:
            return "IN"  # premise

        # Collect all referenced nodes
        all_refs = set()
        parsed = []
        for jtype, ants, outs in justs:
            if isinstance(ants, str):
                ants = json.loads(ants)
            if isinstance(outs, str):
                outs = json.loads(outs)
            parsed.append((jtype, ants, outs))
            all_refs.update(ants)
            all_refs.update(outs)

        # Batch-fetch truth values
        truth_cache = {}
        if all_refs:
            cur.execute(
                "SELECT id, truth_value FROM rms_nodes "
                "WHERE project_id = %s AND id = ANY(%s)",
                (pid, list(all_refs)),
            )
            for row in cur.fetchall():
                truth_cache[row[0]] = row[1]

        for jtype, ants, outs in parsed:
            inlist_ok = all(truth_cache.get(a, "OUT") == "IN" for a in ants)
            outlist_ok = all(truth_cache.get(o, "OUT") == "OUT" for o in outs)
            if inlist_ok and outlist_ok:
                return "IN"
        return "OUT"

    def _find_dependents(self, cur, node_ids):
        """Find nodes that have any of node_ids in their antecedents or outlist."""
        if not node_ids:
            return set()
        pid = self.project_id
        # Use JSONB containment: antecedents @> '["node_id"]'
        dep_ids = set()
        for nid in node_ids:
            needle = json.dumps([nid])
            cur.execute(
                "SELECT DISTINCT node_id FROM rms_justifications "
                "WHERE project_id = %s "
                "AND (antecedents @> %s::jsonb OR outlist @> %s::jsonb)",
                (pid, needle, needle),
            )
            for row in cur.fetchall():
                dep_ids.add(row[0])
        return dep_ids

    def _log(self, cur, action, target, value):
        cur.execute(
            "INSERT INTO rms_propagation_log (project_id, timestamp, action, target, value) "
            "VALUES (%s, %s, %s, %s, %s)",
            (self.project_id, datetime.now().isoformat(timespec="seconds"),
             action, target, value),
        )

    # ── Internal: nogoods + explain ─────────────────────────────

    def _find_culprits_internal(self, cur, nogood_node_ids):
        pid = self.project_id

        # Get truth values
        cur.execute(
            "SELECT id, truth_value FROM rms_nodes WHERE project_id = %s AND id = ANY(%s)",
            (pid, nogood_node_ids),
        )
        node_tvs = {r[0]: r[1] for r in cur.fetchall()}

        assumptions_by_node = {}
        all_premises = set()

        for nid in nogood_node_ids:
            if node_tvs.get(nid) != "IN":
                continue
            premises = []
            visited = set()
            self._trace_assumptions_recursive(cur, nid, premises, visited)
            assumptions_by_node[nid] = premises
            all_premises.update(premises)

        candidates = []
        for premise_id in all_premises:
            would_resolve = [
                nid for nid, assumptions in assumptions_by_node.items()
                if premise_id in assumptions
            ]
            if would_resolve:
                entrenchment = self._entrenchment(cur, premise_id)
                deps = self._find_dependents(cur, [premise_id])
                candidates.append({
                    "premise": premise_id,
                    "would_resolve": would_resolve,
                    "dependent_count": len(deps),
                    "entrenchment": entrenchment,
                })

        candidates.sort(key=lambda c: c["entrenchment"])
        return candidates

    def _entrenchment(self, cur, node_id):
        pid = self.project_id
        cur.execute(
            "SELECT source, source_hash, metadata FROM rms_nodes "
            "WHERE id = %s AND project_id = %s",
            (node_id, pid),
        )
        row = cur.fetchone()
        if not row:
            return 0
        source, source_hash, meta = row
        if isinstance(meta, str):
            meta = json.loads(meta)

        score = 0

        # Premises are more entrenched
        cur.execute(
            "SELECT COUNT(*) FROM rms_justifications "
            "WHERE node_id = %s AND project_id = %s",
            (node_id, pid),
        )
        if cur.fetchone()[0] == 0:
            score += 100

        if source:
            score += 50
        if source_hash:
            score += 25

        deps = self._find_dependents(cur, [node_id])
        score += len(deps) * 10

        btype = meta.get("beliefs_type", "").upper()
        type_scores = {
            "AXIOM": 90, "WARNING": 90,
            "OBSERVATION": 80,
            "DERIVED": 40,
            "PREDICTED": 30,
            "NOTE": 10,
        }
        score += type_scores.get(btype, 20)

        return score

    def _trace_assumptions_recursive(self, cur, node_id, premises, visited):
        if node_id in visited:
            return
        visited.add(node_id)
        pid = self.project_id

        cur.execute(
            "SELECT type, antecedents FROM rms_justifications "
            "WHERE node_id = %s AND project_id = %s",
            (node_id, pid),
        )
        justs = cur.fetchall()

        if not justs:
            if node_id not in premises:
                premises.append(node_id)
            return

        for jtype, ants in justs:
            if isinstance(ants, str):
                ants = json.loads(ants)
            for ant_id in ants:
                self._trace_assumptions_recursive(cur, ant_id, premises, visited)

    def _explain_recursive(self, cur, node_id, visible_to, visited):
        if node_id in visited:
            return []
        visited.add(node_id)
        pid = self.project_id

        cur.execute(
            "SELECT truth_value, metadata FROM rms_nodes "
            "WHERE id = %s AND project_id = %s",
            (node_id, pid),
        )
        row = cur.fetchone()
        if not row:
            return []
        tv, meta = row
        if isinstance(meta, str):
            meta = json.loads(meta)

        if visible_to is not None and not self._is_visible(meta, visible_to):
            return []

        cur.execute(
            "SELECT type, antecedents, outlist, label FROM rms_justifications "
            "WHERE node_id = %s AND project_id = %s ORDER BY id",
            (node_id, pid),
        )
        justs = cur.fetchall()

        steps = []

        if not justs:
            steps.append({
                "node": node_id,
                "truth_value": tv,
                "reason": "premise" if tv == "IN" else "retracted premise",
            })
            return steps

        if tv == "IN":
            # Find the valid justification
            for jtype, ants, outs, jlabel in justs:
                if isinstance(ants, str):
                    ants = json.loads(ants)
                if isinstance(outs, str):
                    outs = json.loads(outs)

                # Check validity
                if self._justification_valid_cached(cur, ants, outs):
                    step = {
                        "node": node_id,
                        "truth_value": "IN",
                        "reason": f"{jtype} justification valid",
                        "antecedents": list(ants),
                        "label": jlabel,
                    }
                    if outs:
                        step["outlist"] = list(outs)
                    steps.append(step)
                    for ant_id in ants:
                        steps.extend(self._explain_recursive(cur, ant_id, visible_to, visited))
                    break
        else:
            # All justifications invalid
            for jtype, ants, outs, jlabel in justs:
                if isinstance(ants, str):
                    ants = json.loads(ants)
                if isinstance(outs, str):
                    outs = json.loads(outs)

                # Find failed antecedents and violated outlist
                all_refs = set(ants) | set(outs)
                truth_cache = {}
                if all_refs:
                    cur.execute(
                        "SELECT id, truth_value FROM rms_nodes "
                        "WHERE project_id = %s AND id = ANY(%s)",
                        (pid, list(all_refs)),
                    )
                    truth_cache = {r[0]: r[1] for r in cur.fetchall()}

                failed = [a for a in ants if truth_cache.get(a, "OUT") == "OUT"]
                violated = [o for o in outs if truth_cache.get(o, "OUT") == "IN"]

                step = {
                    "node": node_id,
                    "truth_value": "OUT",
                    "reason": f"{jtype} justification invalid",
                    "failed_antecedents": failed,
                    "label": jlabel,
                }
                if violated:
                    step["violated_outlist"] = violated
                steps.append(step)

        return steps

    def _justification_valid_cached(self, cur, antecedents, outlist):
        pid = self.project_id
        all_refs = set(antecedents) | set(outlist)
        if not all_refs:
            return True
        cur.execute(
            "SELECT id, truth_value FROM rms_nodes "
            "WHERE project_id = %s AND id = ANY(%s)",
            (pid, list(all_refs)),
        )
        truth_cache = {r[0]: r[1] for r in cur.fetchall()}

        inlist_ok = all(truth_cache.get(a, "OUT") == "IN" for a in antecedents)
        outlist_ok = all(truth_cache.get(o, "OUT") == "OUT" for o in outlist)
        return inlist_ok and outlist_ok

    # ── Internal: formatting ────────────────────────────────────

    def _expand_neighbors(self, cur, matched_ids, visible_to):
        """Expand matched nodes to include 1-hop neighbors."""
        pid = self.project_id
        neighbor_ids = set()

        # Get justifications for matched nodes (dependencies)
        if matched_ids:
            cur.execute(
                "SELECT antecedents FROM rms_justifications "
                "WHERE project_id = %s AND node_id = ANY(%s)",
                (pid, matched_ids),
            )
            for row in cur.fetchall():
                ants = row[0]
                if isinstance(ants, str):
                    ants = json.loads(ants)
                neighbor_ids.update(ants)

        # Get dependents (nodes that reference matched nodes)
        dep_ids = self._find_dependents(cur, matched_ids)
        neighbor_ids.update(dep_ids)

        # Remove already-matched
        neighbor_ids -= set(matched_ids)

        if not neighbor_ids:
            return []

        # Fetch neighbor data
        cur.execute(
            "SELECT id, text, truth_value, source, metadata FROM rms_nodes "
            "WHERE project_id = %s AND id = ANY(%s) ORDER BY id",
            (pid, list(neighbor_ids)),
        )
        neighbors = []
        for row in cur.fetchall():
            nid, text, tv, source, meta = row
            if isinstance(meta, str):
                meta = json.loads(meta)
            if visible_to is not None and not self._is_visible(meta, visible_to):
                continue
            neighbors.append({
                "id": nid, "text": text, "truth_value": tv,
                "source": source, "metadata": meta,
            })
        return neighbors

    def _format_results(self, matched, neighbors, format):
        if format == "json":
            return self._format_json(matched, neighbors)
        elif format == "minimal":
            return self._format_minimal(matched, neighbors)
        elif format == "compact":
            return self._format_compact(matched, neighbors)
        else:
            return self._format_markdown(matched, neighbors)

    def _format_markdown(self, matched, neighbors):
        parts = []
        for m in matched:
            parts.append(f"### {m['id']}")
            parts.append(f"**Status:** {m['truth_value']}")
            parts.append(m["text"])
            if m.get("source"):
                parts.append(f"**Source:** {m['source']}")
            parts.append("")

        if neighbors:
            parts.append("---")
            parts.append("**Related nodes:**\n")
            for n in neighbors:
                parts.append(f"- **{n['id']}** ({n['truth_value']}): {n['text']}")
            parts.append("")

        return "\n".join(parts)

    def _format_json(self, matched, neighbors):
        results = []
        for m in matched:
            results.append({
                "id": m["id"], "text": m["text"],
                "truth_value": m["truth_value"],
                "source": m.get("source", ""), "match": True,
            })
        for n in neighbors:
            results.append({
                "id": n["id"], "text": n["text"],
                "truth_value": n["truth_value"],
                "source": n.get("source", ""), "match": False,
                "relation": "neighbor",
            })
        return json.dumps(results, indent=2)

    def _format_minimal(self, matched, neighbors):
        parts = [m["text"] for m in matched]
        if neighbors:
            parts.append("")
            parts.extend(n["text"] for n in neighbors)
        return "\n".join(parts)

    def _format_compact(self, matched, neighbors):
        lines = []
        for m in matched:
            lines.append(f"[{m['truth_value']}] {m['id']} — {m['text']}")
        for n in neighbors:
            lines.append(f"[{n['truth_value']}] {n['id']} — {n['text']}")
        return "\n".join(lines) if lines else "No results found."

    # ── Internal: helpers ───────────────────────────────────────

    def _parse_justifications(self, sl, cp, unless, label):
        justs = []
        outlist = [o.strip() for o in unless.split(",") if o.strip()] if unless else []

        if sl:
            antecedents = [a.strip() for a in sl.split(",") if a.strip()]
            justs.append({
                "type": "SL",
                "antecedents": antecedents,
                "outlist": outlist,
                "label": label,
            })
        if cp:
            antecedents = [a.strip() for a in cp.split(",") if a.strip()]
            justs.append({
                "type": "CP",
                "antecedents": antecedents,
                "outlist": outlist,
                "label": label,
            })
        return justs

    def _is_visible(self, metadata, visible_to):
        tags = metadata.get("access_tags", [])
        if not tags:
            return True
        return all(t in visible_to for t in tags)

    def _inherit_access_tags(self, cur, node_id, justifications):
        pid = self.project_id
        all_ant_ids = set()
        for j in justifications:
            all_ant_ids.update(j["antecedents"])

        if not all_ant_ids:
            return

        cur.execute(
            "SELECT metadata FROM rms_nodes WHERE project_id = %s AND id = ANY(%s)",
            (pid, list(all_ant_ids)),
        )
        inherited = set()
        for row in cur.fetchall():
            meta = row[0]
            if isinstance(meta, str):
                meta = json.loads(meta)
            inherited.update(meta.get("access_tags", []))

        if not inherited:
            return

        cur.execute(
            "SELECT metadata FROM rms_nodes WHERE id = %s AND project_id = %s",
            (node_id, pid),
        )
        row = cur.fetchone()
        meta = row[0] if row else {}
        if isinstance(meta, str):
            meta = json.loads(meta)

        existing = set(meta.get("access_tags", []))
        merged = existing | inherited
        meta["access_tags"] = sorted(merged)

        cur.execute(
            "UPDATE rms_nodes SET metadata = %s WHERE id = %s AND project_id = %s",
            (json.dumps(meta), node_id, pid),
        )
