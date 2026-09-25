"""SQLite persistence for the dependency network.

Stores nodes, justifications, nogoods, and propagation log in a single
SQLite database. ACID transactions ensure propagation cascades are atomic.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import Node, Justification, Nogood
from .metadata import SCHEMA_VERSION, build_meta
from .network import Network


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    truth_value TEXT NOT NULL DEFAULT 'IN',
    supporting_justification INTEGER DEFAULT NULL,
    source TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    source_hash TEXT DEFAULT '',
    text_hash TEXT DEFAULT '',
    date TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    reviewed_at TEXT DEFAULT '',
    verified_at TEXT DEFAULT '',
    retracted_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS justifications (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES nodes(id),
    type TEXT NOT NULL,
    antecedents_json TEXT NOT NULL DEFAULT '[]',
    outlist_json TEXT NOT NULL DEFAULT '[]',
    label TEXT DEFAULT '',
    content_hash TEXT DEFAULT ''
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

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(id, text, tokenize="porter unicode61 tokenchars '-_'");

CREATE TABLE IF NOT EXISTS node_tags (
    node_id TEXT NOT NULL REFERENCES nodes(id),
    tag TEXT NOT NULL,
    PRIMARY KEY (node_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_node_tags_tag ON node_tags(tag);

CREATE TABLE IF NOT EXISTS node_sources (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES nodes(id),
    source_type TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    source_url TEXT DEFAULT '',
    source_hash TEXT DEFAULT '',
    pinned_sha TEXT DEFAULT '',
    pinned_lines TEXT DEFAULT '',
    label TEXT DEFAULT '',
    added_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_node_sources_node ON node_sources(node_id);
"""

PROPOSALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id              TEXT PRIMARY KEY,
    action          TEXT NOT NULL CHECK (action IN ('retract','supersede','add','nogood')),
    target_id       TEXT NOT NULL,
    new_id          TEXT DEFAULT '',
    proposed_text   TEXT DEFAULT '',
    reason          TEXT DEFAULT '',
    failure_mode    TEXT DEFAULT '',
    basis           TEXT DEFAULT 'prior-knowledge',
    evidence        TEXT DEFAULT '',
    proposer        TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','accepted','rejected','withdrawn','stale')),
    snapshot_json   TEXT DEFAULT '{}',
    impact_json     TEXT DEFAULT '{}',
    tags_json       TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    resolved_at     TEXT DEFAULT '',
    resolved_by     TEXT DEFAULT '',
    result_json     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_proposals_target ON proposals (target_id, status);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals (status);
"""


class Storage:
    """SQLite persistence for a Network."""

    def __init__(self, db_path: str | Path, project_name: str = ""):
        self.db_path = Path(db_path)
        self._is_new = not self.db_path.exists()
        self._project_name = project_name
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        # Migrate existing databases: add source_url if missing
        cols = [c[1] for c in self.conn.execute("PRAGMA table_info(nodes)").fetchall()]
        if "source_url" not in cols:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN source_url TEXT DEFAULT ''")
        for col in ("created_at", "updated_at", "reviewed_at", "verified_at", "retracted_at"):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} TEXT DEFAULT ''")
        if "supporting_justification" not in cols:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN supporting_justification INTEGER DEFAULT NULL")
        if "text_hash" not in cols:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN text_hash TEXT DEFAULT ''")
        j_cols = [c[1] for c in self.conn.execute("PRAGMA table_info(justifications)").fetchall()]
        if "content_hash" not in j_cols:
            self.conn.execute("ALTER TABLE justifications ADD COLUMN content_hash TEXT DEFAULT ''")
        # Migrate: create node_tags / node_sources if missing
        tables = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "node_tags" not in tables:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS node_tags (
                    node_id TEXT NOT NULL REFERENCES nodes(id),
                    tag TEXT NOT NULL,
                    PRIMARY KEY (node_id, tag)
                );
                CREATE INDEX IF NOT EXISTS idx_node_tags_tag ON node_tags(tag);
            """)
            for nid, meta_json in self.conn.execute(
                "SELECT id, metadata_json FROM nodes"
            ).fetchall():
                meta = json.loads(meta_json) if meta_json else {}
                for t in meta.get("access_tags", []):
                    self.conn.execute(
                        "INSERT OR IGNORE INTO node_tags (node_id, tag) VALUES (?, ?)",
                        (nid, f"access:{t}"),
                    )
            self.conn.commit()
        if "node_sources" not in tables:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS node_sources (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL REFERENCES nodes(id),
                    source_type TEXT NOT NULL DEFAULT '',
                    source_ref TEXT NOT NULL DEFAULT '',
                    source_url TEXT DEFAULT '',
                    source_hash TEXT DEFAULT '',
                    pinned_sha TEXT DEFAULT '',
                    pinned_lines TEXT DEFAULT '',
                    label TEXT DEFAULT '',
                    added_at TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_node_sources_node ON node_sources(node_id);
            """)
            for nid, source, source_url, source_hash, meta_json in self.conn.execute(
                "SELECT id, source, source_url, source_hash, metadata_json FROM nodes"
            ).fetchall():
                if not source:
                    continue
                meta = json.loads(meta_json) if meta_json else {}
                self.conn.execute(
                    "INSERT INTO node_sources "
                    "(node_id, source_type, source_ref, source_url, source_hash, pinned_sha, pinned_lines) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        nid,
                        meta.get("source_type", ""),
                        source,
                        source_url or "",
                        source_hash or "",
                        meta.get("pinned_sha", ""),
                        meta.get("pinned_lines", ""),
                    ),
                )
            self.conn.commit()

        if self._is_new:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            project_name = self._project_name or self.db_path.stem
            for key, val in [
                ("schema_version", SCHEMA_VERSION),
                ("project_name", project_name),
                ("created_at", now),
                ("updated_at", now),
            ]:
                self.conn.execute(
                    "INSERT OR IGNORE INTO network_meta (key, value) VALUES (?, ?)",
                    (key, val),
                )
        self.conn.commit()

    def save(self, network: Network) -> None:
        """Persist the entire network state to SQLite."""
        with self.conn:
            # Snapshot externally-added tags/sources before clearing.
            # add_tags()/add_source() write directly to these tables,
            # bypassing the in-memory Network, so we must preserve them.
            ext_tags = self.conn.execute(
                "SELECT node_id, tag FROM node_tags"
            ).fetchall()
            ext_sources = self.conn.execute(
                "SELECT node_id, source_type, source_ref, source_url, "
                "source_hash, pinned_sha, pinned_lines, label, added_at "
                "FROM node_sources"
            ).fetchall()

            # Clear and rewrite (simple strategy for small networks)
            self.conn.execute("DELETE FROM node_tags")
            self.conn.execute("DELETE FROM node_sources")
            self.conn.execute("DELETE FROM justifications")
            self.conn.execute("DROP TABLE IF EXISTS nodes_fts")
            self.conn.execute('CREATE VIRTUAL TABLE nodes_fts USING fts5(id, text, tokenize="porter unicode61 tokenchars \'-_\'")')
            self.conn.execute("DELETE FROM nodes")
            self.conn.execute("DELETE FROM nogoods")
            self.conn.execute("DELETE FROM repos")
            self.conn.execute("DELETE FROM propagation_log")
            self.conn.execute("DELETE FROM network_meta")

            for node in network.nodes.values():
                self.conn.execute(
                    "INSERT INTO nodes (id, text, truth_value, supporting_justification, "
                    "source, source_url, source_hash, text_hash, date, metadata_json, "
                    "created_at, updated_at, reviewed_at, verified_at, retracted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        node.id,
                        node.text,
                        node.truth_value,
                        node.supporting_justification,
                        node.source,
                        node.source_url,
                        node.source_hash,
                        node.text_hash,
                        node.date,
                        json.dumps(node.metadata),
                        node.created_at,
                        node.updated_at,
                        node.reviewed_at,
                        node.verified_at,
                        node.retracted_at,
                    ),
                )
                self.conn.execute(
                    "INSERT INTO nodes_fts (id, text) VALUES (?, ?)",
                    (node.id, node.text),
                )
                for j in node.justifications:
                    self.conn.execute(
                        "INSERT INTO justifications (node_id, type, antecedents_json, outlist_json, label, content_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (node.id, j.type, json.dumps(j.antecedents), json.dumps(j.outlist), j.label, j.content_hash),
                    )

            # Sync node_tags and node_sources (already cleared above before nodes)
            written_sources = set()
            for node in network.nodes.values():
                for t in node.metadata.get("access_tags", []):
                    self.conn.execute(
                        "INSERT OR IGNORE INTO node_tags (node_id, tag) VALUES (?, ?)",
                        (node.id, f"access:{t}"),
                    )
                for t in node.metadata.get("tags", []):
                    self.conn.execute(
                        "INSERT OR IGNORE INTO node_tags (node_id, tag) VALUES (?, ?)",
                        (node.id, t),
                    )
                if node.source:
                    self.conn.execute(
                        "INSERT INTO node_sources "
                        "(node_id, source_type, source_ref, source_url, source_hash, pinned_sha, pinned_lines) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            node.id,
                            node.metadata.get("source_type", ""),
                            node.source,
                            node.source_url or "",
                            node.source_hash or "",
                            node.metadata.get("pinned_sha", ""),
                            node.metadata.get("pinned_lines", ""),
                        ),
                    )
                    written_sources.add((node.id, node.source))

            # Restore externally-added tags/sources for nodes still in network
            node_ids = set(network.nodes.keys())
            for nid, tag in ext_tags:
                if nid in node_ids:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO node_tags (node_id, tag) VALUES (?, ?)",
                        (nid, tag),
                    )
            for row in ext_sources:
                nid, src_ref = row[0], row[2]
                if nid in node_ids and (nid, src_ref) not in written_sources:
                    self.conn.execute(
                        "INSERT INTO node_sources "
                        "(node_id, source_type, source_ref, source_url, source_hash, "
                        "pinned_sha, pinned_lines, label, added_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )

            for nogood in network.nogoods:
                self.conn.execute(
                    "INSERT INTO nogoods (id, nodes_json, discovered, resolution) "
                    "VALUES (?, ?, ?, ?)",
                    (nogood.id, json.dumps(nogood.nodes), nogood.discovered, nogood.resolution),
                )

            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            meta = dict(network.meta)
            meta.setdefault("schema_version", SCHEMA_VERSION)
            meta.setdefault("project_name", self.db_path.stem)
            meta.setdefault("created_at", now)
            meta["updated_at"] = now
            for key, val in meta.items():
                self.conn.execute(
                    "INSERT OR REPLACE INTO network_meta (key, value) VALUES (?, ?)",
                    (key, str(val)),
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
        cols = [c[1] for c in self.conn.execute("PRAGMA table_info(nodes)").fetchall()]
        has_source_url = "source_url" in cols
        has_timestamps = "created_at" in cols
        has_supporting = "supporting_justification" in cols
        has_text_hash = "text_hash" in cols
        if has_timestamps:
            if has_supporting:
                cursor = self.conn.execute(
                    "SELECT id, text, truth_value, supporting_justification, "
                    "source, source_url, source_hash, date, metadata_json, "
                    "created_at, updated_at, reviewed_at, verified_at, retracted_at"
                    + (", text_hash" if has_text_hash else ", ''")
                    + " FROM nodes"
                )
            else:
                cursor = self.conn.execute(
                    "SELECT id, text, truth_value, NULL, "
                    "source, source_url, source_hash, date, metadata_json, "
                    "created_at, updated_at, reviewed_at, verified_at, retracted_at"
                    + (", text_hash" if has_text_hash else ", ''")
                    + " FROM nodes"
                )
        elif has_source_url:
            cursor = self.conn.execute(
                "SELECT id, text, truth_value, NULL, "
                "source, source_url, source_hash, date, metadata_json, '', '', '', '', '', '' FROM nodes"
            )
        else:
            cursor = self.conn.execute(
                "SELECT id, text, truth_value, NULL, "
                "source, '', source_hash, date, metadata_json, '', '', '', '', '', '' FROM nodes"
            )
        node_rows = cursor.fetchall()

        # Load justifications keyed by node_id
        j_cols = [c[1] for c in self.conn.execute("PRAGMA table_info(justifications)").fetchall()]
        has_content_hash = "content_hash" in j_cols
        just_cursor = self.conn.execute(
            "SELECT node_id, type, antecedents_json, outlist_json, label"
            + (", content_hash" if has_content_hash else ", ''")
            + " FROM justifications ORDER BY rowid"
        )
        justifications_by_node: dict[str, list[Justification]] = {}
        for node_id, jtype, ant_json, out_json, label, content_hash in just_cursor:
            j = Justification(
                type=jtype,
                antecedents=json.loads(ant_json),
                outlist=json.loads(out_json),
                label=label,
                content_hash=content_hash or "",
            )
            justifications_by_node.setdefault(node_id, []).append(j)

        # Build nodes directly (bypass add_node to preserve exact state)
        for row in node_rows:
            nid, text, truth_value, supporting_j, source, source_url, source_hash, \
                date, meta_json, created_at, updated_at, reviewed_at, verified_at, \
                retracted_at, text_hash = row
            node = Node(
                id=nid,
                text=text,
                truth_value=truth_value,
                justifications=justifications_by_node.get(nid, []),
                supporting_justification=supporting_j,
                source=source,
                source_url=source_url or "",
                source_hash=source_hash,
                text_hash=text_hash or "",
                date=date,
                metadata=json.loads(meta_json) if meta_json else {},
                created_at=created_at or "",
                updated_at=updated_at or "",
                reviewed_at=reviewed_at or "",
                verified_at=verified_at or "",
                retracted_at=retracted_at or "",
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

        # Load network metadata — persisted counter takes priority,
        # otherwise derive from existing nogoods to avoid ID collisions
        try:
            meta_cursor = self.conn.execute("SELECT key, value FROM network_meta")
            for key, value in meta_cursor:
                if key == "next_nogood_id":
                    continue
                network.meta[key] = value
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
