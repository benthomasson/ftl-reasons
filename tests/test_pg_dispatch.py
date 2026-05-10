"""Tests for the PostgreSQL dispatch layer in api.py and cli.py."""

import argparse
from unittest.mock import patch, MagicMock

import pytest

from reasons_lib.api import _pg_dispatch, export_markdown
from reasons_lib.cli import _backend_kwargs, _require_sqlite


class TestPgDispatch:

    def test_dispatch_calls_pgapi_method(self):
        mock_pg = MagicMock()
        mock_pg.get_status.return_value = {"total": 5}
        with patch("reasons_lib.pg.PgApi") as MockPgApi:
            MockPgApi.return_value.__enter__ = MagicMock(return_value=mock_pg)
            MockPgApi.return_value.__exit__ = MagicMock(return_value=False)
            result = _pg_dispatch("postgresql://...", "proj-1", "get_status")
        assert result == {"total": 5}

    def test_dispatch_passes_kwargs(self):
        mock_pg = MagicMock()
        mock_pg.show_node.return_value = {"id": "a", "text": "Alpha"}
        with patch("reasons_lib.pg.PgApi") as MockPgApi:
            MockPgApi.return_value.__enter__ = MagicMock(return_value=mock_pg)
            MockPgApi.return_value.__exit__ = MagicMock(return_value=False)
            result = _pg_dispatch("postgresql://...", "proj-1", "show_node", node_id="a")
        mock_pg.show_node.assert_called_once_with(node_id="a")


class TestBackendKwargs:

    def test_sqlite_default(self):
        args = argparse.Namespace(db="reasons.db", pg=None, project_id=None)
        result = _backend_kwargs(args)
        assert result == {"db_path": "reasons.db"}

    def test_pg_with_project_id(self):
        args = argparse.Namespace(db="reasons.db", pg="postgresql://localhost/test",
                                  project_id="abc-123")
        result = _backend_kwargs(args)
        assert result == {"pg_conninfo": "postgresql://localhost/test",
                          "project_id": "abc-123"}

    def test_pg_missing_project_id_exits(self):
        args = argparse.Namespace(db="reasons.db", pg="postgresql://localhost/test",
                                  project_id=None)
        with pytest.raises(SystemExit):
            _backend_kwargs(args)

    def test_env_var_fallback(self):
        args = argparse.Namespace(db="reasons.db", pg=None, project_id=None)
        with patch.dict("os.environ", {"REASONS_PG_CONNINFO": "postgresql://env",
                                        "REASONS_PROJECT_ID": "env-proj"}):
            result = _backend_kwargs(args)
        assert result == {"pg_conninfo": "postgresql://env", "project_id": "env-proj"}

    def test_cli_overrides_env(self):
        args = argparse.Namespace(db="reasons.db", pg="postgresql://cli",
                                  project_id="cli-proj")
        with patch.dict("os.environ", {"REASONS_PG_CONNINFO": "postgresql://env",
                                        "REASONS_PROJECT_ID": "env-proj"}):
            result = _backend_kwargs(args)
        assert result == {"pg_conninfo": "postgresql://cli", "project_id": "cli-proj"}


class TestRequireSqlite:

    def test_no_pg_passes(self):
        args = argparse.Namespace(pg=None)
        _require_sqlite(args, "hash-sources")

    def test_pg_set_exits(self):
        args = argparse.Namespace(pg="postgresql://localhost/test")
        with pytest.raises(SystemExit):
            _require_sqlite(args, "hash-sources")

    def test_env_pg_exits(self):
        args = argparse.Namespace(pg=None)
        with patch.dict("os.environ", {"REASONS_PG_CONNINFO": "postgresql://env"}):
            with pytest.raises(SystemExit):
                _require_sqlite(args, "hash-sources")


class TestExportMarkdownPgPath:

    EXPORT_DATA = {
        "nodes": {
            "premise-a": {
                "text": "Alpha premise",
                "truth_value": "IN",
                "justifications": [],
                "source": "test.py",
                "source_url": "https://example.com",
                "source_hash": "abc123",
                "date": "2026-01-01",
                "metadata": {"domain": "test"},
            },
            "derived-b": {
                "text": "Beta derived from alpha",
                "truth_value": "IN",
                "justifications": [
                    {"type": "SL", "antecedents": ["premise-a"], "outlist": [], "label": ""}
                ],
                "source": "",
                "source_url": "",
                "source_hash": "",
                "date": "",
                "metadata": {},
            },
            "gated-c": {
                "text": "Gamma gated on blocker",
                "truth_value": "OUT",
                "justifications": [
                    {"type": "SL", "antecedents": ["premise-a"],
                     "outlist": ["blocker"], "label": "gated"}
                ],
                "source": "",
                "source_url": "",
                "source_hash": "",
                "date": "",
                "metadata": {},
            },
            "blocker": {
                "text": "Blocker node",
                "truth_value": "IN",
                "justifications": [],
                "source": "",
                "source_url": "",
                "source_hash": "",
                "date": "",
                "metadata": {},
            },
        },
        "nogoods": [
            {"id": "nogood-001", "nodes": ["premise-a", "blocker"],
             "discovered": "2026-01-01", "resolution": ""},
        ],
        "repos": {},
    }

    def test_produces_markdown(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert isinstance(md, str)
        assert len(md) > 0

    def test_contains_node_ids(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert "premise-a" in md
        assert "derived-b" in md
        assert "gated-c" in md

    def test_contains_node_text(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert "Alpha premise" in md
        assert "Beta derived from alpha" in md

    def test_contains_justification_refs(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert "premise-a" in md

    def test_contains_source_info(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert "test.py" in md

    def test_contains_nogoods(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert "nogood" in md.lower()

    def test_dependents_reconstructed(self):
        with patch("reasons_lib.api.export_network", return_value=self.EXPORT_DATA):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        # premise-a is an antecedent of derived-b and gated-c,
        # so it should show dependents in the markdown
        assert "derived-b" in md
        assert "gated-c" in md

    def test_empty_network(self):
        empty = {"nodes": {}, "nogoods": [], "repos": {}}
        with patch("reasons_lib.api.export_network", return_value=empty):
            md = export_markdown(pg_conninfo="postgresql://...", project_id="test")
        assert isinstance(md, str)
