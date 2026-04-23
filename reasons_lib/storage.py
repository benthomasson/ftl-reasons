"""SQLite persistence for the dependency network.

Stores nodes, justifications, nogoods, and propagation log in a single
SQLite database. ACID transactions ensure propagation cascades are atomic.
"""

import json
import sqlite3
from pathlib import Path

from . import Node, Justification, Nogood
from .network import Network


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    truth_value TEXT NOT NULL DEFAULT 'IN',
    source TEXT DEFAULT '',
    source_hash TEXT DEFAULT '',
    date TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS justifications (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES nodes(id),
    type TEXT NOT NULL,
    antecedents_json TEXT NOT NULL DEFAULT '[]',
    outlist_json TEXT NOT NULL DEFAULT '[]',
    label TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS nogoods (
    id TEXT PRIMARY KEY,
    nodes_json TEXT NOT NULL DEFAULT '[]',
    discovered TEXT DEFAULT '',
    resolution TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS repos (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS propagation_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS network_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(id, text);
"""


class Storage:
    """SQLite persistence for a Network."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save(self, network: Network) -> None:
        """Persist the entire network state to SQLite."""
        with self.conn:
            # Clear and rewrite (simple strategy for small networks)
            self.conn.execute("DELETE FROM justifications")
            self.conn.execute("DELETE FROM nodes_fts")
            self.conn.execute("DELETE FROM nodes")
            self.conn.execute("DELETE FROM nogoods")
            self.conn.execute("DELETE FROM repos")
            self.conn.execute("DELETE FROM propagation_log")
            self.conn.execute("DELETE FROM network_meta")

            for node in network.nodes.values():
                self.conn.execute(
                    "INSERT INTO nodes (id, text, truth_value, source, source_hash, date, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        node.id,
                        node.text,
                        node.truth_value,
                        node.source,
                        node.source_hash,
                        node.date,
                        json.dumps(node.metadata),
                    ),
                )
                self.conn.execute(
                    "INSERT INTO nodes_fts (id, text) VALUES (?, ?)",
                    (node.id, node.text),
                )
                for j in node.justifications:
                    self.conn.execute(
                        "INSERT INTO justifications (node_id, type, antecedents_json, outlist_json, label) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (node.id, j.type, json.dumps(j.antecedents), json.dumps(j.outlist), j.label),
                    )

            for nogood in network.nogoods:
                self.conn.execute(
                    "INSERT INTO nogoods (id, nodes_json, discovered, resolution) "
                    "VALUES (?, ?, ?, ?)",
                    (nogood.id, json.dumps(nogood.nodes), nogood.discovered, nogood.resolution),
                )

            self.conn.execute(
                "INSERT INTO network_meta (key, value) VALUES (?, ?)",
                ("next_nogood_id", str(network._next_nogood_id)),
            )

            for name, path in network.repos.items():
                self.conn.execute(
                    "INSERT INTO repos (name, path) VALUES (?, ?)",
                    (name, path),
                )

            for entry in network.log:
                self.conn.execute(
                    "INSERT INTO propagation_log (timestamp, action, target, value) "
                    "VALUES (?, ?, ?, ?)",
                    (entry["timestamp"], entry["action"], entry["target"], entry["value"]),
                )

    def load(self) -> Network:
        """Load a Network from SQLite."""
        network = Network()

        # Load nodes (without justifications first, to avoid ordering issues)
        cursor = self.conn.execute(
            "SELECT id, text, truth_value, source, source_hash, date, metadata_json FROM nodes"
        )
        node_rows = cursor.fetchall()

        # Load justifications keyed by node_id
        just_cursor = self.conn.execute(
            "SELECT node_id, type, antecedents_json, outlist_json, label FROM justifications ORDER BY rowid"
        )
        justifications_by_node: dict[str, list[Justification]] = {}
        for node_id, jtype, ant_json, out_json, label in just_cursor:
            j = Justification(
                type=jtype,
                antecedents=json.loads(ant_json),
                outlist=json.loads(out_json),
                label=label,
            )
            justifications_by_node.setdefault(node_id, []).append(j)

        # Build nodes directly (bypass add_node to preserve exact state)
        for row in node_rows:
            nid, text, truth_value, source, source_hash, date, meta_json = row
            node = Node(
                id=nid,
                text=text,
                truth_value=truth_value,
                justifications=justifications_by_node.get(nid, []),
                source=source,
                source_hash=source_hash,
                date=date,
                metadata=json.loads(meta_json),
            )
            network.nodes[nid] = node

        # Rebuild dependent index from justifications (canonical method)
        network._rebuild_dependents()

        # Load nogoods
        ng_cursor = self.conn.execute(
            "SELECT id, nodes_json, discovered, resolution FROM nogoods"
        )
        for ng_id, nodes_json, discovered, resolution in ng_cursor:
            network.nogoods.append(Nogood(
                id=ng_id,
                nodes=json.loads(nodes_json),
                discovered=discovered,
                resolution=resolution,
            ))

        # Load network metadata
        try:
            row = self.conn.execute(
                "SELECT value FROM network_meta WHERE key = 'next_nogood_id'"
            ).fetchone()
            if row:
                network._next_nogood_id = int(row[0])
            elif network.nogoods:
                # Old database without persisted counter — derive from existing nogoods
                import re
                max_id = 0
                for ng in network.nogoods:
                    m = re.fullmatch(r"nogood-(\d+)", ng.id)
                    if m:
                        max_id = max(max_id, int(m.group(1)))
                network._next_nogood_id = max_id + 1
        except Exception:
            pass  # network_meta table may not exist in old databases

        # Load repos
        try:
            repos_cursor = self.conn.execute("SELECT name, path FROM repos")
            for name, path in repos_cursor:
                network.repos[name] = path
        except Exception:
            pass  # repos table may not exist in old databases

        # Load log
        log_cursor = self.conn.execute(
            "SELECT timestamp, action, target, value FROM propagation_log ORDER BY rowid"
        )
        for ts, action, target, value in log_cursor:
            network.log.append({
                "timestamp": ts,
                "action": action,
                "target": target,
                "value": value,
            })

        return network

    def close(self) -> None:
        self.conn.close()
