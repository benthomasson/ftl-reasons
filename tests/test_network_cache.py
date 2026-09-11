"""Tests for the in-memory network cache in _with_network."""

import tempfile
from pathlib import Path

from reasons.api import (
    _network_cache,
    _with_network,
    add_node,
    clear_network_cache,
    init_db,
    search,
    show_node,
    what_if_retract,
    what_if_assert,
)


def setup_function():
    clear_network_cache()


def test_read_populates_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("a", "First belief", db_path=db)
        clear_network_cache()

        with _with_network(db) as net:
            assert "a" in net.nodes

        assert db in _network_cache
        assert _network_cache[db][1].nodes["a"].text == "First belief"


def test_cached_read_skips_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("a", "First belief", db_path=db)
        clear_network_cache()

        with _with_network(db) as net1:
            pass

        with _with_network(db) as net2:
            pass

        assert net1 is net2


def test_write_loads_fresh():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("a", "First belief", db_path=db)
        clear_network_cache()

        with _with_network(db) as net1:
            pass

        with _with_network(db, write=True) as net2:
            pass

        assert net1 is not net2


def test_write_updates_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("a", "First belief", db_path=db)
        clear_network_cache()

        add_node("b", "Second belief", db_path=db)

        assert db in _network_cache
        assert "b" in _network_cache[db][1].nodes


def test_external_modification_invalidates_cache():
    """If the db file is modified externally, mtime changes and cache is bypassed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("a", "First belief", db_path=db)

        cached_mtime = _network_cache[db][0]

        import os
        import time
        time.sleep(0.05)
        os.utime(db, None)

        with _with_network(db) as net:
            pass

        assert _network_cache[db][0] != cached_mtime


def test_clear_cache_specific_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        db1 = str(Path(tmpdir) / "a.db")
        db2 = str(Path(tmpdir) / "b.db")
        init_db(db_path=db1)
        init_db(db_path=db2)
        add_node("x", "belief x", db_path=db1)
        add_node("y", "belief y", db_path=db2)

        assert db1 in _network_cache
        assert db2 in _network_cache

        clear_network_cache(db1)
        assert db1 not in _network_cache
        assert db2 in _network_cache


def test_clear_cache_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        db1 = str(Path(tmpdir) / "a.db")
        db2 = str(Path(tmpdir) / "b.db")
        init_db(db_path=db1)
        init_db(db_path=db2)
        add_node("x", "belief x", db_path=db1)
        add_node("y", "belief y", db_path=db2)

        clear_network_cache()
        assert len(_network_cache) == 0


def test_write_exception_does_not_poison_cache():
    """If a write context raises, the dirty network must not enter the cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("a", "Original belief", db_path=db)

        cached_net = _network_cache[db][1]
        assert "a" in cached_net.nodes

        try:
            with _with_network(db, write=True) as net:
                net.nodes["a"].text = "CORRUPTED"
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass

        assert _network_cache[db][1].nodes["a"].text == "Original belief"


def test_search_uses_cache():
    """Search should work correctly with cached networks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("widget-config", "The widget configuration for deployment", db_path=db)
        clear_network_cache()

        result1 = search("widget", db_path=db)
        assert "widget-config" in result1

        result2 = search("widget", db_path=db)
        assert "widget-config" in result2


def test_show_node_uses_cache():
    """show_node should work correctly with cached networks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("test-node", "A test belief", db_path=db)
        clear_network_cache()

        result1 = show_node("test-node", db_path=db)
        assert result1["id"] == "test-node"

        result2 = show_node("test-node", db_path=db)
        assert result2["id"] == "test-node"


def test_what_if_retract_does_not_corrupt_cache():
    """what_if_retract mutates a network copy, not the cached original."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("premise", "A premise", db_path=db)
        add_node("conclusion", "Follows from premise", source="sl:premise",
                 sl="premise", db_path=db)

        result = what_if_retract("premise", db_path=db)
        assert result["total_affected"] >= 1

        cached_net = _network_cache[db][1]
        assert cached_net.nodes["premise"].truth_value == "IN"
        assert cached_net.nodes["conclusion"].truth_value == "IN"


def test_what_if_assert_does_not_corrupt_cache():
    """what_if_assert mutates a network copy, not the cached original."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from reasons.api import retract_node
        db = str(Path(tmpdir) / "test.db")
        init_db(db_path=db)
        add_node("premise", "A premise", db_path=db)
        retract_node("premise", db_path=db)

        assert _network_cache[db][1].nodes["premise"].truth_value == "OUT"

        result = what_if_assert("premise", db_path=db)
        assert not result.get("already_in", False)

        assert _network_cache[db][1].nodes["premise"].truth_value == "OUT"
